import json
import os
import urllib.request
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler
from urllib.parse import urljoin

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(BASE_DIR, "channels.json")) as f:
    CHANNELS = json.load(f)

NS = {"mpd": "urn:mpeg:dash:schema:mpd:2011"}


def fetch(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def fill_template(tpl, rep_id, time_val=None):
    out = tpl.replace("$RepresentationID$", rep_id)
    if time_val is not None:
        out = out.replace("$Time$", str(time_val))
    return out


def parse_mpd(xml_text):
    root = ET.fromstring(xml_text)
    period = root.find("mpd:Period", NS)
    result = {"video": [], "audio": []}

    for a_set in period.findall("mpd:AdaptationSet", NS):
        content_type = a_set.get("contentType") or a_set.get("mimeType", "").split("/")[0]
        seg_template = a_set.find("mpd:SegmentTemplate", NS)
        timescale = int(seg_template.get("timescale", "1"))
        init_tpl = seg_template.get("initialization")
        media_tpl = seg_template.get("media")
        timeline = seg_template.find("mpd:SegmentTimeline", NS)

        segments = []
        cur_t = None
        for s in timeline.findall("mpd:S", NS):
            t = s.get("t")
            d = int(s.get("d"))
            r = int(s.get("r", "0"))
            if t is not None:
                cur_t = int(t)
            if cur_t is None:
                cur_t = 0
            for _ in range(r + 1):
                segments.append((cur_t, d))
                cur_t += d

        for rep in a_set.findall("mpd:Representation", NS):
            info = {
                "id": rep.get("id"),
                "bandwidth": rep.get("bandwidth"),
                "codecs": rep.get("codecs"),
                "width": rep.get("width"),
                "height": rep.get("height"),
                "timescale": timescale,
                "init_tpl": init_tpl,
                "media_tpl": media_tpl,
                "segments": segments,
            }
            if content_type == "video":
                result["video"].append(info)
            else:
                result["audio"].append(info)

    return result


def build_master(slug, info, host):
    lines = ["#EXTM3U", "#EXT-X-VERSION:7"]

    if info["audio"]:
        a = info["audio"][0]
        lines.append(
            '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Default",AUTOSELECT=YES,DEFAULT=YES,URI="https://{}/stream-hls/{}/{}.m3u8"'.format(
                host, slug, a["id"]
            )
        )

    for v in info["video"]:
        bw = v["bandwidth"] or "0"
        attrs = '#EXT-X-STREAM-INF:BANDWIDTH={},CODECS="{}"'.format(bw, v["codecs"] or "")
        if v["width"] and v["height"]:
            attrs += ",RESOLUTION={}x{}".format(v["width"], v["height"])
        if info["audio"]:
            attrs += ',AUDIO="audio"'
        lines.append(attrs)
        lines.append("https://{}/stream-hls/{}/{}.m3u8".format(host, slug, v["id"]))

    return "\n".join(lines) + "\n"


def build_media_playlist(rep, base_url):
    timescale = rep["timescale"]
    segs = rep["segments"][-10:]  # live window, 10 segmen terakhir

    target_duration = 4
    if segs:
        target_duration = max(1, round(max(d for _, d in segs) / timescale) + 1)

    init_url = urljoin(base_url, fill_template(rep["init_tpl"], rep["id"]))

    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:7",
        "#EXT-X-TARGETDURATION:{}".format(target_duration),
        "#EXT-X-MEDIA-SEQUENCE:0",
        "#EXT-X-PLAYLIST-TYPE:EVENT",
        '#EXT-X-MAP:URI="{}"'.format(init_url),
    ]

    for t, d in segs:
        dur = d / timescale
        seg_url = urljoin(base_url, fill_template(rep["media_tpl"], rep["id"], t))
        lines.append("#EXTINF:{:.3f},".format(dur))
        lines.append(seg_url)

    return "\n".join(lines) + "\n"


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.lstrip("/").split("?")[0]
        parts = path.split("/")

        if len(parts) != 3 or parts[0] != "stream-hls":
            self._error(400, "Bad request")
            return

        slug = parts[1]
        filename = parts[2]

        if slug not in CHANNELS:
            self._error(404, "Channel not found: {}".format(slug))
            return

        origin_mpd_url = CHANNELS[slug]
        base_url = origin_mpd_url.rsplit("/", 1)[0] + "/"

        try:
            xml_text = fetch(origin_mpd_url)
            info = parse_mpd(xml_text)
        except Exception as e:
            self._error(502, "Failed to fetch/parse origin MPD: {}".format(e))
            return

        host = self.headers.get("Host", "")

        if filename == "master.m3u8":
            body = build_master(slug, info, host)
        elif filename.endswith(".m3u8"):
            rep_id = filename[:-5]
            rep = None
            for v in info["video"] + info["audio"]:
                if v["id"] == rep_id:
                    rep = v
                    break
            if rep is None:
                self._error(404, "Representation not found: {}".format(rep_id))
                return
            body = build_media_playlist(rep, base_url)
        else:
            self._error(400, "Bad request")
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
