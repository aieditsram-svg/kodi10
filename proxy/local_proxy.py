#!/usr/bin/env python3
"""Promptioo TV local helper: free, unlimited http:// playback in the web page, on your own computer.

Run it (Python 3.8+, nothing to install):   python local_proxy.py
Leave the window open, then open the Promptioo TV page in Chrome, Edge or Firefox. The page finds the helper
by itself (http://127.0.0.1:8787) and plays http:// channels through it. Only your own computer can reach it.
Same address format as the Cloudflare worker:  http://127.0.0.1:8787/?url=<stream address>
"""
import sys
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
    "Access-Control-Allow-Headers": "range, content-type",
    "Access-Control-Expose-Headers": "content-length, content-range, content-type",
    "Access-Control-Allow-Private-Network": "true",
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def send(self, code, body=b"", headers=None):
        self.send_response(code)
        for k, v in {**CORS, **(headers or {})}.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def open_vlc(self, url):
        import os
        import shutil
        import subprocess
        paths = [shutil.which("vlc"),
                 r"C:\Program Files\VideoLAN\VLC\vlc.exe", r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
                 "/Applications/VLC.app/Contents/MacOS/VLC", "/usr/bin/vlc", "/snap/bin/vlc"]
        exe = next((p for p in paths if p and os.path.exists(p)), None)
        if not exe and os.name == "nt":                 # no VLC: try Windows Media Player
            wmp = next((p for p in (r"C:\Program Files\Windows Media Player\wmplayer.exe",
                                    r"C:\Program Files (x86)\Windows Media Player\wmplayer.exe") if os.path.exists(p)), None)
            if wmp:
                subprocess.Popen([wmp, url])
                note = b"opened in Windows Media Player (it cannot play .m3u8 live streams; install VLC if it stays blank)"
                return self.send(200, note, {"Content-Type": "text/plain"})
        if not exe:
            return self.send(404, b"No player found. Install VLC from videolan.org")
        subprocess.Popen([exe, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return self.send(200, b"opened", {"Content-Type": "text/plain"})

    def do_OPTIONS(self):
        self.send(204)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/ping":
            return self.send(200, b"promptioo-local", {"Content-Type": "text/plain"})
        target = urllib.parse.parse_qs(parsed.query).get("url", [""])[0]
        if parsed.path == "/open":                      # the page's "Open in VLC" button
            if not target.lower().startswith(("http://", "https://")):
                return self.send(400, b"bad address")
            return self.open_vlc(target)
        if not target.lower().startswith(("http://", "https://")):
            return self.send(400, b"use /?url=<stream address>")
        req = urllib.request.Request(target, headers={"User-Agent": "Mozilla/5.0"})
        if self.headers.get("Range"):
            req.add_header("Range", self.headers["Range"])
        try:
            up = urllib.request.urlopen(req, timeout=20)
        except Exception as exc:
            return self.send(502, ("stream unreachable: %s" % exc).encode())
        ctype = up.headers.get("Content-Type", "")
        final = up.geturl()
        if "mpegurl" in ctype.lower() or urllib.parse.urlparse(final).path.lower().endswith((".m3u8", ".m3u")):
            wrap = lambda u: "http://127.0.0.1:%d/?url=%s" % (PORT, urllib.parse.quote(urllib.parse.urljoin(final, u), safe=""))
            out = []
            for line in up.read().decode("utf-8", "replace").splitlines():
                if not line.strip():
                    out.append(line)
                elif line.startswith("#"):
                    import re
                    out.append(re.sub(r'URI="([^"]+)"', lambda m: 'URI="%s"' % wrap(m.group(1)), line))
                else:
                    out.append(wrap(line.strip()))
            return self.send(200, "\n".join(out).encode(), {"Content-Type": "application/vnd.apple.mpegurl"})
        # video data: pass it through as it arrives
        self.send_response(up.status)
        for k, v in CORS.items():
            self.send_header(k, v)
        for h in ("Content-Type", "Content-Range", "Accept-Ranges"):
            if up.headers.get(h):
                self.send_header(h, up.headers[h])
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            while True:
                chunk = up.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        self.close_connection = True


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("Promptioo TV helper running on http://127.0.0.1:%d  (close this window to stop)" % PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
