"""HTTP server: JSON API + the static web app, on one port, standard library only."""

import hmac
import json
import socket
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from . import __version__

WEB = Path(__file__).resolve().parent / "web"
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".json": "application/json", ".svg": "image/svg+xml",
                 ".png": "image/png", ".ico": "image/x-icon", ".webmanifest": "application/manifest+json"}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
COOKIE = "meshatlas_token"


def make_handler(atlas=None, token="", demo=False):
    """atlas=None with demo=True serves the web app only; the browser generates demo data itself."""

    class Handler(BaseHTTPRequestHandler):
        server_version = f"meshatlas/{__version__}"

        def log_message(self, fmt, *args):  # keep stdout quiet
            pass

        def send_bytes(self, body, ctype, status=HTTPStatus.OK, cache="no-store", extra=None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", CSP)
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, payload, status=HTTPStatus.OK):
            self.send_bytes(json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8", status)

        def authorized(self, url):
            if not token:
                return True
            auth = self.headers.get("Authorization", "")
            if auth.startswith("Bearer ") and hmac.compare_digest(auth[7:].strip(), token):
                return True
            jar = SimpleCookie(self.headers.get("Cookie", ""))
            if COOKIE in jar and hmac.compare_digest(jar[COOKIE].value, token):
                return True
            given = (parse_qs(url.query).get("token") or [""])[0]
            if given and hmac.compare_digest(given, token):
                # remember it in a cookie and drop it from the address bar
                rest = {k: v for k, v in parse_qs(url.query).items() if k != "token"}
                loc = url.path + ("?" + urlencode(rest, doseq=True) if rest else "")
                self.send_bytes(b"", "text/plain", HTTPStatus.FOUND, extra={
                    "Location": loc,
                    "Set-Cookie": f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000"})
                return None
            return False

        def do_GET(self):
            url = urlparse(self.path)
            path = url.path
            if path == "/healthz":
                return self.send_bytes(b"ok\n", "text/plain")
            ok = self.authorized(url)
            if ok is None:
                return
            if not ok:
                return self.send_bytes(b"MeshAtlas: open this page once with ?token=<your token>\n", "text/plain",
                                       HTTPStatus.UNAUTHORIZED)
            if path == "/config.js":
                body = f"window.MESHATLAS = {json.dumps({'demo': demo, 'version': __version__})};\n".encode()
                return self.send_bytes(body, CONTENT_TYPES[".js"])
            if path.startswith("/api/"):
                if atlas is None:
                    return self.send_json({"error": "demo mode: data is generated in the browser"}, HTTPStatus.NOT_FOUND)
                return self.api(path, parse_qs(url.query))
            if path in ("/", "/index.html"):
                path = "/index.html"
            target = (WEB / path.lstrip("/")).resolve()
            if WEB not in target.parents or not target.is_file():
                return self.send_bytes(b"not found\n", "text/plain", HTTPStatus.NOT_FOUND)
            cache = "public, max-age=86400" if "/vendor/" in path else "no-cache"
            return self.send_bytes(target.read_bytes(), CONTENT_TYPES.get(target.suffix, "application/octet-stream"),
                                   cache=cache)

        def api(self, path, q):
            def num(name, default, lo, hi):
                try:
                    return max(lo, min(int((q.get(name) or [default])[0]), hi))
                except ValueError:
                    return default
            keep_h = 24 * atlas.col["keep_days"]
            if path == "/api/state":
                return self.send_json(atlas.api_state())
            if path == "/api/history":
                node = (q.get("node") or [""])[0]
                if node not in atlas.nodes:
                    return self.send_json({"error": "unknown node"}, HTTPStatus.NOT_FOUND)
                return self.send_json(atlas.api_history(node, num("hours", 24, 1, keep_h)))
            if path == "/api/uptime":
                return self.send_json(atlas.api_uptime(num("hours", 24, 1, keep_h), num("buckets", 48, 6, 240)))
            if path == "/api/events":
                node = (q.get("node") or [""])[0] or None
                levels = [x for x in (q.get("level") or [""])[0].split(",") if x in ("info", "ok", "warn", "error")]
                before = num("before", 0, 0, 2 ** 62) or None
                return self.send_json(atlas.api_events(node, levels, num("limit", 100, 1, 500), before))
            return self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    return Handler


class Server(ThreadingHTTPServer):
    """On Linux, IP_FREEBIND lets us bind the Tailscale IP even if tailscaled is not up yet (boot ordering)."""
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, "IP_FREEBIND"):
            try:
                self.socket.setsockopt(socket.SOL_IP, socket.IP_FREEBIND, 1)
            except OSError:
                pass
        super().server_bind()


def serve(host, port, handler):
    httpd = Server((host, port), handler)
    return httpd
