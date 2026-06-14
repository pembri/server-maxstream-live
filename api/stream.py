import re
import requests
from urllib.parse import urlparse, parse_qs, urljoin, quote
from http.server import BaseHTTPRequestHandler

BASE_URL = "https://cdn-server-indihometv.vidiraplay.biz.id"

CHANNELS = {
    "btv": "https://cdnbal1.indihometv.com/atm/DASH/beritasatu/beritasatu-avc1_2500000=7-3277707030000000.mpd",
    "gtv": "https://cdnbal1.indihometv.com/atm/DASH/globaltv/globaltv-avc1_2500000=7-3277707030000000.mpd",
    "idx_channel": "https://cdnbal1.indihometv.com/atm/DASH/idx/idx-avc1_2500000=7-3277707030000000.mpd",
    "indosiar": "https://cdnbal1.indihometv.com/atm/DASH/indosiar/indosiar-avc1_2500000=7-3277707030000000.mpd",
    "inews": "https://cdnbal1.indihometv.com/atm/DASH/inews/inews-avc1_2500000=7-3277707030000000.mpd",
    "kompas_tv": "https://cdnbal1.indihometv.com/atm/DASH/KOMPAS_TV/KOMPAS_TV-avc1_2500000=7-3277707030000000.mpd",
    "mdtv": "https://cdnbal1.indihometv.com/dassdvr/134/net/manifest_wuseetv.mpd",
    "metro_tv": "https://cdnbal1.indihometv.com/dassdvr/134/metrotv/manifest_wuseetv.mpd",
    "mnctv": "https://cdnbal1.indihometv.com/atm/DASH/mnctv/mnctv-avc1_2500000=7-3277707030000000.mpd",
    "nusantara_tv": "https://cdnbal1.indihometv.com/atm/DASH/nusantaratv/nusantaratv-avc1_2500000=7-3277707030000000.mpd",
    "rcti": "https://cdnbal1.indihometv.com/atm/DASH/rcti/rcti-avc1_2500000=7-3277707030000000.mpd",
    "rtv": "https://cdnbal1.indihometv.com/atm/DASH/RAJAWALI_TV/RAJAWALI_TV-avc1_2500000=7-3277707030000000.mpd",
    "sctv": "https://cdnbal1.indihometv.com/atm/DASH/sctv/sctv-avc1_2500000=7-3277707030000000.mpd",
    "sindonews": "https://cdnbal1.indihometv.com/atm/DASH/mncnews/mncnews-avc1_2500000=7-3277707030000000.mpd",
    "trans7": "https://cdnbal1.indihometv.com/dassdvr/130/trans7/manifest_wuseetv.mpd",
    "transtv": "https://cdnbal1.indihometv.com/dassdvr/130/transtv/manifest_wuseetv.mpd",
    "tvone": "https://cdnbal1.indihometv.com/atm/DASH/tvone/tvone-avc1_2500000=7-3277707030000000.mpd",
    "tvri": "https://cdnbal1.indihometv.com/atm/DASH/TVRI/TVRI-avc1_2500000=7-3277707030000000.mpd",
    "rcti": "https://cdnbal1.indihometv.com/atm/DASH/rcti/rcti-avc1_2500000=7-3277707030000000.mpd",
    "mnctv": "https://cdnbal1.indihometv.com/atm/DASH/mnctv/mnctv-avc1_2500000=7-3277707030000000.mpd",
    "al_jazeera": "https://cdnbal1.indihometv.com/atm/DASH/aljazeera/aljazeera-avc1_2500000=7-3277707030000000.mpd",
    "bbc_news": "https://cdnbal1.indihometv.com/atm/DASH/bbcnews/bbcnews-avc1_2500000=7-3277707030000000.mpd",
    "bloomberg": "https://cdnbal1.indihometv.com/atm/DASH/BLOOMBERG_AT/BLOOMBERG_AT-avc1_2500000=7-3277707030000000.mpd",
    "cna": "https://cdnbal1.indihometv.com/atm/DASH/newsasia/newsasia-avc1_2500000=7-3277707030000000.mpd",
    "dw": "https://cdnbal1.indihometv.com/atm/DASH/DWTV/DWTV-avc1_2500000=7-3277707030000000.mpd",
    "france24": "https://cdnbal1.indihometv.com/atm/DASH/FRANCE_24/FRANCE_24-avc1_2500000=7-3277707030000000.mpd",
    "nhk": "https://cdnbal1.indihometv.com/atm/DASH/NHK_WORLD_JAPAN/NHK_WORLD_JAPAN-avc1_2500000=7-3277707030000000.mpd",
    "russia_today": "https://cdnbal1.indihometv.com/atm/DASH/rusiatv/rusiatv-avc1_2500000=7-3277707030000000.mpd",
    "hbo": "https://cdnbal1.indihometv.com/atm/DASH/hbo/hbo-avc1_2500000=7-3277707030000000.mpd",
    "hbo_hits": "https://cdnbal1.indihometv.com/atm/DASH/hbohits/hbohits-avc1_2500000=7-3277707030000000.mpd",
    "hbo_signature": "https://cdnbal1.indihometv.com/atm/DASH/hbosignature/hbosignature-avc1_2500000=7-3277707030000000.mpd",
    "discovery": "https://cdnbal1.indihometv.com/atm/DASH/disco/disco-avc1_2500000=7-3277707030000000.mpd",
    "spotv": "https://cdnbal1.indihometv.com/dassdvr/130/beib1/manifest_wuseetv.mpd",
    "spotv2": "https://cdnbal1.indihometv.com/dassdvr/130/beib2/manifest_wuseetv.mpd",
    "nickelodeon": "https://cdnbal1.indihometv.com/atm/DASH/nickelodeon/nickelodeon-avc1_2500000=7-3277707030000000.mpd",
    "cinemax": "https://cdnbal1.indihometv.com/atm/DASH/cinemax/cinemax-avc1_2500000=7-3277707030000000.mpd",
    "fight_sports": "https://cdnbal1.indihometv.com/atm/DASH/fightsport/fightsport-avc1_2500000=7-3277707030000000.mpd",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 11) AppleWebKit/537.36",
    "Referer": "https://www.indihometv.com/",
    "Origin": "https://www.indihometv.com",
}


def rewrite_mpd(content, base_url):
    def abs_url(rel):
        if rel.startswith("http"):
            return rel
        return urljoin(base_url, rel)

    content = re.sub(
        r'(initialization|media)="([^"]+)"',
        lambda m: f'{m.group(1)}="{abs_url(m.group(2))}"',
        content
    )
    return content


def parse_segments(seg_template, ns, timescale):
    timeline = seg_template.find("mpd:SegmentTimeline", ns)
    segments = []
    if timeline:
        t = None
        for s in timeline.findall("mpd:S", ns):
            if "t" in s.attrib:
                t = int(s.get("t"))
            d = int(s.get("d", 0))
            r = int(s.get("r", 0))
            for _ in range(r + 1):
                segments.append((t, d))
                t += d
    return segments


def make_abs(template, rep_id, base_url, time=None):
    url = template.replace("$RepresentationID$", rep_id)
    if time is not None:
        url = url.replace("$Time$", str(time))
    if url.startswith("http"):
        return url
    return urljoin(base_url, url)


def mpd_to_hls(mpd_text, base_url):
    import xml.etree.ElementTree as ET
    ns = {"mpd": "urn:mpeg:dash:schema:mpd:2011"}
    root = ET.fromstring(mpd_text)
    period = root.find("mpd:Period", ns)
    if not period:
        raise Exception("No Period")

    video_set = None
    audio_set = None
    for ads in period.findall("mpd:AdaptationSet", ns):
        mime = ads.get("mimeType", "")
        if "video" in mime and not video_set:
            video_set = ads
        elif "audio" in mime and not audio_set:
            audio_set = ads

    if not video_set:
        raise Exception("No video AdaptationSet")

    # Video
    v_tmpl = video_set.find("mpd:SegmentTemplate", ns)
    v_timescale = int(v_tmpl.get("timescale", 1))
    v_init = v_tmpl.get("initialization", "")
    v_media = v_tmpl.get("media", "")
    v_reps = video_set.findall("mpd:Representation", ns)
    v_reps_avc = [r for r in v_reps if "avc" in r.get("codecs", "")]
    if not v_reps_avc:
        v_reps_avc = v_reps
    v_rep = max(v_reps_avc, key=lambda r: int(r.get("bandwidth", 0)))
    v_rep_id = v_rep.get("id")
    v_codecs = v_rep.get("codecs", "avc1.64001f")

    v_segments = parse_segments(v_tmpl, ns, v_timescale)
    v_init_url = make_abs(v_init, v_rep_id, base_url)
    target_dur = max((d / v_timescale for _, d in v_segments), default=3)

    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:7",
        f"#EXT-X-TARGETDURATION:{int(target_dur) + 1}",
        "#EXT-X-MEDIA-SEQUENCE:0",
    ]

    # Audio track
    if audio_set:
        a_tmpl = audio_set.find("mpd:SegmentTemplate", ns)
        a_timescale = int(a_tmpl.get("timescale", 1))
        a_init = a_tmpl.get("initialization", "")
        a_media = a_tmpl.get("media", "")
        a_reps = audio_set.findall("mpd:Representation", ns)
        a_rep = max(a_reps, key=lambda r: int(r.get("bandwidth", 0)))
        a_rep_id = a_rep.get("id")
        a_codecs = a_rep.get("codecs", "mp4a.40.2")
        a_segments = parse_segments(a_tmpl, ns, a_timescale)
        a_init_url = make_abs(a_init, a_rep_id, base_url)

        lines.append(f'#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Audio",DEFAULT=YES,URI="data:application/vnd.apple.mpegurl;base64,"')
        # Buat audio sub-playlist inline
        a_lines = [
            "#EXTM3U",
            "#EXT-X-VERSION:7",
            f"#EXT-X-TARGETDURATION:{int(target_dur) + 1}",
            "#EXT-X-MEDIA-SEQUENCE:0",
            f'#EXT-X-MAP:URI="{a_init_url}"',
        ]
        for t, d in a_segments:
            dur = d / a_timescale
            seg_url = make_abs(a_media, a_rep_id, base_url, t)
            a_lines.append(f"#EXTINF:{dur:.3f},")
            a_lines.append(seg_url)
        import base64
        a_playlist = "\n".join(a_lines)
        a_b64 = base64.b64encode(a_playlist.encode()).decode()

        lines[-1] = f'#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Audio",DEFAULT=YES,URI="data:application/vnd.apple.mpegurl;base64,{a_b64}"' 
        lines.append(f'#EXT-X-STREAM-INF:BANDWIDTH={v_rep.get("bandwidth","1500000")},CODECS="{v_codecs},{a_codecs}",AUDIO="audio"')
    else:
        lines.append(f'#EXT-X-STREAM-INF:BANDWIDTH={v_rep.get("bandwidth","1500000")},CODECS="{v_codecs}"')

    # Video init + segments
    lines.append(f'#EXT-X-MAP:URI="{v_init_url}"')
    for t, d in v_segments:
        dur = d / v_timescale
        seg_url = make_abs(v_media, v_rep_id, base_url, t)
        lines.append(f"#EXTINF:{dur:.3f},")
        lines.append(seg_url)

    return "\n".join(lines)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        # /stream-hls/{channel}.m3u8
        m = re.match(r"^/stream-hls/([^/]+)\.m3u8$", path)
        if m:
            self._handle_hls(m.group(1))
            return

        # /stream-dash/{channel}.mpd
        m = re.match(r"^/stream-dash/([^/]+)\.mpd$", path)
        if m:
            self._handle_mpd(m.group(1))
            return

        self._error(404, "Channel tidak tersedia")

    def _handle_hls(self, channel):
        mpd_url = CHANNELS.get(channel)
        if not mpd_url:
            self._error(404, "Channel tidak tersedia")
            return
        try:
            resp = requests.get(mpd_url, headers=HEADERS, timeout=10)
            resp.raise_for_status()
            base_url = mpd_url.rsplit("/", 1)[0] + "/"
            content = mpd_to_hls(resp.text, base_url)
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.apple.mpegurl")
            self.send_header("Cache-Control", "no-cache, no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(content.encode())
        except Exception as e:
            self._error(502, str(e))

    def _handle_mpd(self, channel):
        mpd_url = CHANNELS.get(channel)
        if not mpd_url:
            self._error(404, "Channel tidak tersedia")
            return
        try:
            resp = requests.get(mpd_url, headers=HEADERS, timeout=10)
            resp.raise_for_status()
            base_url = mpd_url.rsplit("/", 1)[0] + "/"
            content = rewrite_mpd(resp.text, base_url)
            self.send_response(200)
            self.send_header("Content-Type", "application/dash+xml")
            self.send_header("Cache-Control", "no-cache, no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(content.encode())
        except Exception as e:
            self._error(502, str(e))

    def _error(self, code, message):
        import json
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps({"error": message}).encode())

    def log_message(self, format, *args):
        pass
