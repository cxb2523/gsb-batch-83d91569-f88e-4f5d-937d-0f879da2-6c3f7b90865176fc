"""A tiny stand-in for the site, serving the synthetic fixtures on localhost.

Used by the tests, and handy for trying the crawler without touching the real
site::

    python -m tests.fake_site            # prints the address, Ctrl+C to stop

Every page is a hand-written fixture with placeholder text; the "images" are a
few bytes of plain text.
"""

from __future__ import annotations

import contextlib
import re
import sys
import threading
from collections import Counter
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

FIXTURES = Path(__file__).parent / "fixtures"


def render(name: str, **values: object) -> str:
    """Read a fixture and fill its ``{{KEY}}`` placeholders."""
    text = (FIXTURES / name).read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


@dataclass(frozen=True)
class FakeGallery:
    url_hash: str
    kind: str  # "multi" (3 images over 2 thumbnail pages), "single" or "removed"

    @property
    def images(self) -> int:
        return {"multi": 3, "single": 1, "removed": 0}[self.kind]

    def file_name(self, page: int) -> str:
        return f"page {page:03d}.jpg" if self.kind == "multi" else "single.png"


#: The galleries listed by list_page.html and list_page_last.html.
GALLERIES = {
    1005: FakeGallery("0a1b2c3d4e", "multi"),
    1004: FakeGallery("5f6a7b8c9d", "single"),
    1003: FakeGallery("1e2f3a4b5c", "removed"),
    1002: FakeGallery("6d7e8f9a0b", "single"),
    1001: FakeGallery("c1d2e3f4a5", "single"),
}
QUOTA_IMAGE = "img/509.gif"

GALLERY_PATH = re.compile(r"^/g/(\d+)/([0-9a-f]+)/$")
IMAGE_PAGE_PATH = re.compile(r"^/s/[0-9a-f]+/(\d+)-(\d+)$")
IMAGE_PATH = re.compile(r"^/img/(\d+)-(\d+)\.\w+$")


def image_bytes(gallery_id: int, page: int) -> bytes:
    return f"synthetic image {gallery_id}-{page}\n".encode()


@dataclass
class FakeSite:
    host: str = "127.0.0.1"
    port: int = 0
    #: Every request as (path with query, Cookie header).
    requests: list[tuple[str, str]] = field(default_factory=list)
    #: Path (with query) -> how many more times to answer with the 503 page.
    fail: Counter[str] = field(default_factory=Counter)
    #: Path (with query) -> ban duration text, answered once.
    ban: dict[str, str] = field(default_factory=dict)
    #: Galleries that show the content warning until ``nw=`` is in the URL.
    content_warning: set[int] = field(default_factory=set)
    #: Serve the quota placeholder after this many image pages.
    quota_after: int | None = None

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        self._image_pages = 0
        site = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                site._handle(self)

            def log_message(self, format: str, *args: object) -> None:
                pass

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._server.daemon_threads = True
        self.base = f"http://{self.host}:{self._server.server_address[1]}/"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> FakeSite:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()

    def gallery_url(self, gallery_id: int) -> str:
        return f"{self.base}g/{gallery_id}/{GALLERIES[gallery_id].url_hash}/"

    def paths(self, prefix: str = "") -> list[str]:
        with self._lock:
            return [path for path, _ in self.requests if path.startswith(prefix)]

    # --- routing ---------------------------------------------------------------

    def _handle(self, handler: BaseHTTPRequestHandler) -> None:
        with self._lock:
            self.requests.append((handler.path, handler.headers.get("Cookie", "")))
            failing = self.fail[handler.path] > 0
            if failing:
                self.fail[handler.path] -= 1
            banned_for = self.ban.pop(handler.path, None)
        if failing:
            return self._send(handler, 503, "<html><body>Error 503 Service Unavailable</body></html>")
        if banned_for is not None:
            return self._send(handler, 200, render("banned.html", EXPIRES=banned_for))
        status, body, content_type = self._route(handler.path)
        self._send(handler, status, body, content_type)

    def _route(self, raw_path: str) -> tuple[int, str | bytes, str]:
        parts = urlsplit(raw_path)
        query = parse_qs(parts.query)
        html = "text/html; charset=UTF-8"
        if parts.path == "/":
            if not query:
                return 200, render("list_page.html", BASE=self.base), html
            if query.get("next") == ["1003"]:
                return 200, render("list_page_last.html", BASE=self.base), html
        if match := GALLERY_PATH.match(parts.path):
            return self._gallery(int(match.group(1)), match.group(2), query)
        if match := IMAGE_PAGE_PATH.match(parts.path):
            return self._image_page(int(match.group(1)), int(match.group(2)))
        if parts.path == "/" + QUOTA_IMAGE:
            return 200, b"quota placeholder\n", "image/gif"
        if match := IMAGE_PATH.match(parts.path):
            return 200, image_bytes(int(match.group(1)), int(match.group(2))), "application/octet-stream"
        return 404, "<html><body>Not found</body></html>", html

    def _gallery(self, gallery_id: int, url_hash: str, query: dict[str, list[str]]) -> tuple[int, str, str]:
        html = "text/html; charset=UTF-8"
        gallery = GALLERIES.get(gallery_id)
        if gallery is None or gallery.url_hash != url_hash:
            return 404, "<html><body>Gallery not found.</body></html>", html
        values = {"BASE": self.base, "GID": gallery_id, "HASH": url_hash}
        if gallery.kind == "removed":
            return 200, render("removed.html"), html
        if gallery_id in self.content_warning and "nw" not in query:
            return 200, render("content_warning.html", **values), html
        if gallery.kind == "single":
            return 200, render("gallery_single.html", **values), html
        page = query.get("p", ["0"])[0]
        return 200, render("gallery_multi_p1.html" if page == "1" else "gallery_multi.html", **values), html

    def _image_page(self, gallery_id: int, page: int) -> tuple[int, str, str]:
        gallery = GALLERIES[gallery_id]
        with self._lock:
            self._image_pages += 1
            over_quota = self.quota_after is not None and self._image_pages > self.quota_after
        image = self.base + (QUOTA_IMAGE if over_quota else f"img/{gallery_id}-{page}.jpg")
        body = render(
            "image_page.html",
            BASE=self.base,
            GID=gallery_id,
            PAGE=page,
            TOTAL=gallery.images,
            NAME=gallery.file_name(page),
            IMAGE=image,
        )
        return 200, body, "text/html; charset=UTF-8"

    @staticmethod
    def _send(
        handler: BaseHTTPRequestHandler, status: int, body: str | bytes, content_type: str = "text/html; charset=UTF-8"
    ) -> None:
        data = body.encode() if isinstance(body, str) else body
        handler.send_response(status)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    with FakeSite(port=port) as fake:
        print(f"fake site at {fake.base} (Ctrl+C to stop)", flush=True)
        with contextlib.suppress(KeyboardInterrupt):
            threading.Event().wait()
