import json
import os
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(BASE_DIR, "channels.json")) as f:
    CHANNELS = json.load(f)

NS = {"mpd": "urn:mpeg:dash:schema:mpd:2011"}


# ---------- DASH (MPD) helpers ----------

def fetch_mpd_root(url):
    r = requests.get(url, timeout=6, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return ET.fromstring(r.content)


def origin_base_url(origin_url):
    return origin_url.rsplit("/", 1)[0] + "/"


def fill_template(tpl, rep_id, time_val=None):
    out = tpl.replace("$RepresentationID$", rep_id)
    if time_val is not None:
        out = out.replace("$Time$", str(time_val))
    return out


def expand_timeline(seg_template):
    """Expand a SegmentTemplate's SegmentTimeline into [(start_time, duration), ...]."""
    timeline = seg_template.find("mpd:SegmentTimeline", NS)
    segments = []
    t_cursor = 0
    for s in timeline.findall("mpd:S", NS):
        t = s.get("t")
        d = int(s.get("d"))
        r = int(s.get("r", "0"))
        if t is not None:
            t_cursor = int(t)
        # NOTE: r="-1" (open-ended repeat) is not handled here, none of the
        # IndihomeTV manifests observed so far use it. If it shows up, this
        # needs special-casing against the next <S> or period boundary.
        for _ in range(r + 1):
            segments.append((t_cursor, d))
            t_cursor += d
    return segments


def build_representations(root):
    """
    rep_id -> {content_type, bandwidth, timescale, init_tpl, media_tpl,
               segments: [(t, d), ...], codecs, width, height}
    """
    reps = {}
    period = root.find("mpd:Period", NS)
    for adapt in period.findall("mpd:AdaptationSet", NS):
        content_type = adapt.get("contentType") or adapt.get("mimeType", "").split("/")[0]
        seg_tpl = adapt.find("mpd:SegmentTemplate", NS)
        timescale = int(seg_tpl.get("timescale", "1"))
        init_tpl = seg_tpl.get("initialization")
        media_tpl = seg_tpl.get("media")
        segments = expand_timeline(seg_tpl)
        for rep in adapt.findall("mpd:Representation", NS):
            rep_id = rep.get("id")
            reps[rep_id] = {
                "content_type": content_type,
                "bandwidth": int(rep.get("bandwidth", "0")),
                "timescale": timescale,
                "init_tpl": init_tpl,
                "media_tpl": media_tpl,
                "segments": segments,
                "codecs": rep.get("codecs", ""),
                "width": rep.get("width"),
                "height": rep.get("height"),
            }
    return reps


# ---------- HLS playlist builders ----------

def build_media_playlist(rep_id, rep, origin_base):
    timescale = rep["timescale"]
    segments = rep["segments"]
    if not segments:
        return None

    target_duration = max(d for _, d in segments) / timescale
    # Derive MEDIA-SEQUENCE from the first segment's timestamp so it stays
    # consistent (monotonically increasing) across playlist reloads, since
    # each request regenerates the list from scratch.
    media_sequence = int(segments[0][0] / timescale)

    init_url = origin_base + fill_template(rep["init_tpl"], rep_id)

    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:7",
        f"#EXT-X-TARGETDURATION:{int(target_duration) + 1}",
        f"#EXT-X-MEDIA-SEQUENCE:{media_sequence}",
        f'#EXT-X-MAP:URI="{init_url}"',
    ]
    for t, d in segments:
        dur = d / timescale
        seg_url = origin_base + fill_template(rep["media_tpl"], rep_id, t)
        lines.append(f"#EXTINF:{dur:.3f},")
        lines.append(seg_url)

    return "\n".join(lines) + "\n"


def build_master_playlist(reps):
    video_reps = {k: v for k, v in reps.items() if v["content_type"] == "video"}
    audio_reps = {k: v for k, v in reps.items() if v["content_type"] == "audio"}

    lines = ["#EXTM3U", "#EXT-X-VERSION:7"]

    audio_group = "audio0"
    for rep_id in audio_reps:
        lines.append(
            f'#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="{audio_group}",NAME="audio",'
            f'AUTOSELECT=YES,DEFAULT=YES,URI="{rep_id}.m3u8"'
        )

    for rep_id, rep in sorted(video_reps.items(), key=lambda kv: kv[1]["bandwidth"]):
        attrs = f'BANDWIDTH={rep["bandwidth"]},CODECS="{rep["codecs"]}"'
        if rep["width"] and rep["height"]:
            attrs += f',RESOLUTION={rep["width"]}x{rep["height"]}'
        if audio_reps:
            attrs += f',AUDIO="{audio_group}"'
        lines.append(f"#EXT-X-STREAM-INF:{attrs}")
        lines.append(f"{rep_id}.m3u8")

    return "\n".join(lines) + "\n"


# ---------- HTTP handler ----------

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.lstrip("/").split("?")[0]
        parts = path.split("/")

        if len(parts) == 3 and parts[0] == "stream-dash" and parts[2] == "master.mpd":
            self._handle_dash(parts[1])
        elif len(parts) == 3 and parts[0] == "stream-hls" and parts[2].endswith(".m3u8"):
            self._handle_hls(parts[1], parts[2])
        else:
            self._error(400, "Bad request")

    def _handle_dash(self, slug):
        if slug not in CHANNELS:
            self._error(404, f"Channel not found: {slug}")
            return
        self.send_response(301)
        self.send_header("Location", CHANNELS[slug])
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def _handle_hls(self, slug, filename):
        if slug not in CHANNELS:
            self._error(404, f"Channel not found: {slug}")
            return

        origin_url = CHANNELS[slug]
        try:
            root = fetch_mpd_root(origin_url)
        except Exception as e:
            self._error(502, f"Failed to fetch origin manifest: {e}")
            return

        # Bail out early if the manifest carries DRM — Widevine licenses
        # issued for DASH won't work for an HLS player without FairPlay/AES-128.
        if root.find(".//mpd:ContentProtection", NS) is not None:
            self._error(409, f"Channel '{slug}' is DRM-protected, HLS not supported")
            return

        reps = build_representations(root)
        origin_base = origin_base_url(origin_url)

        if filename == "master.m3u8":
            body = build_master_playlist(reps)
        else:
            rep_id = filename[: -len(".m3u8")]
            rep = reps.get(rep_id)
            if not rep:
                self._error(404, f"Representation not found: {rep_id}")
                return
            body = build_media_playlist(rep_id, rep, origin_base)
            if body is None:
                self._error(502, "No segments available")
                return

        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.apple.mpegurl")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body.encode())

    def _error(self, code, msg):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(msg.encode())

    def log_message(self, format, *args):
        pass
