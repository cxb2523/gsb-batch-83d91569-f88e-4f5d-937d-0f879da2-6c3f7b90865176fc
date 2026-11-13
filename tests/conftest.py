"""Shared fixtures for the sitemap-harvester test suite.

Every test builds its own static "website" (XML + HTML files) inside a
temporary directory and serves it over real HTTP on 127.0.0.1 using only the
Python standard library. No mocking of ``requests`` is required, so the full
request/parse pipeline -- including HTTP error codes and connection failures
-- is exercised end to end.
"""

import functools
import http.server
import socketserver
import threading
from urllib.parse import urljoin

import pytest


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler without per-request log spam."""

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass


@pytest.fixture
def site_server(tmp_path):
    """Serve ``tmp_path`` over HTTP and return a small helper object."""

    handler = functools.partial(QuietHandler, directory=str(tmp_path))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    httpd.allow_reuse_address = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    host, port = httpd.server_address

    class Site:
        base_url = f"http://{host}:{port}"
        root = tmp_path

        def url(self, path):
            return urljoin(self.base_url, path)

        def write(self, rel_path, content):
            path = tmp_path / rel_path
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                path.write_bytes(content)
            else:
                path.write_text(content, encoding="utf-8")
            return self.url("/" + rel_path.replace("\\", "/"))

    site = Site()
    try:
        yield site
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <meta name="description" content="{description}">
  <meta name="keywords" content="{keywords}">
  <meta name="author" content="{author}">
  <link rel="canonical" href="{canonical}">
  <meta property="og:title" content="{og_title}">
  <meta property="og:type" content="website">
  <meta property="og:image" content="{og_image}">
</head>
<body><h1>{title}</h1></body>
</html>
"""


def write_page(site, rel_path, slug):
    """Create a valid metadata-rich HTML page and return its URL."""
    return site.write(
        rel_path,
        HTML_TEMPLATE.format(
            title=f"Page {slug}",
            description=f"Description of {slug}",
            keywords=f"key-{slug}, test",
            author=f"Author {slug}",
            canonical=site.url(f"/{rel_path}"),
            og_title=f"OG {slug}",
            og_image=site.url(f"/img-{slug}.png"),
        ),
    )


SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


def url_sitemap(urls):
    """Build a plain urlset sitemap document for the given page URLs."""
    locs = "".join(f"  <url><loc>{u}</loc></url>\n" for u in urls)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<urlset xmlns="{SITEMAP_NS}">\n'
        f"{locs}"
        "</urlset>\n"
    )


def index_sitemap(child_urls):
    """Build a sitemap index document referencing the given sitemap URLs."""
    locs = "".join(
        f"  <sitemap><loc>{u}</loc></sitemap>\n" for u in child_urls
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<sitemapindex xmlns="{SITEMAP_NS}">\n'
        f"{locs}"
        "</sitemapindex>\n"
    )
