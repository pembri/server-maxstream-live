import json
import os
import time
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(BASE_DIR, "channels.json")) as f:
    CHANNELS = json.load(f)

NS = {"mpd": "urn:mpeg:dash:schema:mpd:2011"}

# Module-level cache: persists across "warm" invocations of the same
# serverless instance (not guaranteed, but free when it happens). Keeps
# video/audio sub-playlist requests that land close together from each
# triggering their own separate fetch+parse of the same origin .mpd.
_MPD_CACHE = {}
_MPD_CACHE_TTL = 1.5  # seconds; keep well under the MPD's minimumUpdatePeriod

# Tracks the most-advanced manifest snapshot seen per channel so far. The
# origin CDN appears to load-balance across nodes that aren't perfectly
# synced, so a fresh fetch can sometimes come back *older* (lower segment
# timestamps) than one we already served. HLS requires MEDIA-SEQUENCE to
# never decrease, so when that happens we keep serving the more-advanced
# snapshot instead of handing the player something that goes backwards.
_HIGHWATER = {}


def _manifest_ref_time(root):
    """Cheap freshness marker: the first <S t="..."> of the first
    AdaptationSet's SegmentTimeline. Only ever compared against itself for
    the same channel, so differing timescales between adaptation sets don't
    matter."""
    period = root.find("mpd:Period", NS)
    adapt = period.find("mpd:AdaptationSet", NS)
    seg_tpl = adapt.find("mpd:SegmentTemplate", NS)
    timeline = seg_tpl.find("mpd:SegmentTimeline", NS)
    first_s = timeline.find("mpd:S", NS)
    t = first_s.get("t")
    return int(t) if t is not None else 0


# ---------- DASH (MPD) helpers ----------

def fetch_mpd_root(url):
    now = time.monotonic()
    cached = _MPD_CACHE.get(url)
    if cached and (now - cached[0]) < _MPD_CACHE_TTL:
        return cached[1]

    # Cache-bust via query string (standard, harmless) instead of custom
    # headers — Cache-Control/Pragma on the inbound request likely confused
    # the origin/CDN and caused the fetch failures seen after the last change.
    sep = "&" if "?" in url else "?"
    bust_url = f"{url}{sep}_={int(now * 1000)}"

    last_err = None
    for _attempt in range(2):
        try:
            r = requests.get(bust_url, timeout=4, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            root = ET.fromstring(r.content)

            ref_time = _manifest_ref_time(root)
            hw = _HIGHWATER.get(url)
            if hw and hw[0] > ref_time:
                # Fresh fetch is *behind* what we already served — origin
                # node desync. Keep the more-advanced snapshot.
                root = hw[1]
            else:
                _HIGHWATER[url] = (ref_time, root)

            _MPD_CACHE[url] = (now, root)
            return root
        except Exception as e:
            last_err = e
    raise last_err


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
        try:
            path = self.path.lstrip("/").split("?")[0]
            parts = path.split("/")

            if len(parts) == 3 and parts[0] == "stream-dash" and parts[2] == "master.mpd":
                self._handle_dash(parts[1])
            elif len(parts) == 3 and parts[0] == "stream-hls" and parts[2].endswith(".m3u8"):
                self._handle_hls(parts[1], parts[2])
            else:
                self._error(400, "Bad request")
        except Exception as e:
            # Make sure unexpected failures show up in Vercel function logs
            # with a traceback, instead of silently producing a broken
            # response that hls.js can't parse.
            import traceback
            print(f"[proxy] unhandled exception on {self.path}: {e}")
            traceback.print_exc()
            self._error(500, f"Internal error: {e}")

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

        body_bytes = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.apple.mpegurl")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store, max-age=0, must-revalidate")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body_bytes)

    def do_HEAD(self):
        # Some clients probe with HEAD before GET. BaseHTTPRequestHandler
        # returns 501 for it by default, which is harmless on its own but
        # worth eliminating as a source of noise/confusion while debugging.
        self.do_GET()

    def _error(self, code, msg):
        body_bytes = msg.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body_bytes)

    def log_message(self, format, *args):
        pass
