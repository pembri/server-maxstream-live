import json
import os
from http.server import BaseHTTPRequestHandler

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(BASE_DIR, "channels.json")) as f:
    CHANNELS = json.load(f)

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.lstrip("/").split("?")[0]
        parts = path.split("/")

        if len(parts) != 3 or parts[0] != "stream-dash" or parts[2] != "master.mpd":
            self._error(400, "Bad request")
            return

        slug = parts[1]

        if slug not in CHANNELS:
            self._error(404, f"Channel not found: {slug}")
            return

        origin_url = CHANNELS[slug]

        self.send_response(301)
        self.send_header("Location", origin_url)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def _error(self, code, msg):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(msg.encode())

    def log_message(self, format, *args):
        pass
