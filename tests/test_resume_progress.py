"""
tests/test_resume_progress.py
-----------------------------
Drives http_scraper's resumable pagination against a LOCAL two-page listing,
so the three paths that matter are exercised without a network or a proxy:

1. an interrupted run resumes — page 2 is refused on the first run (exit 6,
   rows kept, manifest written), then served on the second, which must fetch
   ONLY page 2 and finish complete (exit 0);
2. a manifest that does not match this run (different --mode, or no manifest
   at all) is reported and the run starts fresh — never silently reused;
3. a mid-run refusal keeps the exit-code contract (partial rows -> exit 6)
   and records the stop reason in the manifest.

Plus the two edges of the resume contract: a fully-completed manifest
finalizes from the existing output without any fetch, and a page that adds
no new sku still ends the listing (no_new_products), on resume as well.

The two pages are real parser input: the listing payload is encoded into the
site's own turbo-stream format (a flat array of index references, see
product_parser.decode_turbo_stream), so these tests fail if the resume
machinery AND the parser stop agreeing on what a page is.
"""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import env_config          # noqa: E402
import http_scraper        # noqa: E402
import product_parser      # noqa: E402


# ---------------------------------------------------------------------------
# A two-page Sleep Number listing, built from scratch
# ---------------------------------------------------------------------------

def _encode_turbo(obj) -> str:
    """Encode a Python object graph into the site's turbo-stream flat array.

    Every value is an index into one array; an object is {"_<keyIndex>":
    <valueIndex>}. The root must sit at index 0, which it does because it is
    emitted first. This is the inverse of product_parser.decode_turbo_stream.
    """
    flat = []

    def intern(value):
        flat.append(value)
        return len(flat) - 1

    def emit(node):
        if isinstance(node, dict):
            slot = intern(None)
            out = {}
            for key, value in node.items():
                out[f"_{intern(key)}"] = emit(value)
            flat[slot] = out
            return slot
        if isinstance(node, (list, tuple)):
            slot = intern(None)
            items = [emit(v) for v in node]
            flat[slot] = items
            return slot
        return intern(node)

    emit(obj)
    return json.dumps(flat, ensure_ascii=False)


def _product(sku: str, name: str, cents: int) -> dict:
    return {
        "id": f"ID-{sku}",
        "name": name,
        "branded_name": name,
        "slug": name.lower().replace(" ", "-"),
        "canonical_url": "https://www.sleepnumber.com/products/"
                         + name.lower().replace(" ", "-"),
        "type": "mattress",
        "category_slug": "testcat-collection",
        "purchasable": True,
        "images": [],
        "review_stats": {"average_overall_rating": 4.5, "review_count": 12},
        "variants": [{
            "sku": sku,
            "details": {"Size": ["Queen"]},
            "active": True,
            "sale": {"cents": cents, "currency_iso": "USD"},
            "regular": {"cents": cents + 10000, "currency_iso": "USD"},
        }],
    }


def _page_html(products, *, page: int, last_page: bool, next_page,
               total_results: int = 2) -> str:
    category = {
        "name": "Testcat",
        "slug": "testcat",
        "page": page,
        "per_page": 1,
        "total_results": total_results,
        "next_page": next_page,
        "prev_page": None,
        "last_page": last_page,
        "full_url": "https://www.sleepnumber.com/categories/testcat",
        "products": products,
    }
    payload = {"loaderData": {"root": {},
                              "routes/categories.$slug": {"category": category}}}
    stream = _encode_turbo(payload).replace("\\", "\\\\").replace('"', '\\"')
    return ("<!DOCTYPE html><html><head><title>Testcat | Sleep Number</title>"
            '<link rel="preconnect" href="https://cdn.sleepnumber.com"></head>'
            '<body><div id="root"></div>'
            "<script>window.__reactRouterContext = {};</script>"
            "<script>window.__reactRouterContext.streamController.enqueue(\""
            + stream + "\");</script></body></html>")


# A CloudFront-style refusal: small, no site asset markers, status 403.
REFUSAL_HTML = ("<html><head><title>ERROR: The request could not be "
                "satisfied</title></head><body>Request blocked.</body></html>")


class _Site:
    """A throwaway HTTP server whose routes can change mid-test."""

    def __init__(self):
        self.routes = {}
        self.requests = []

    def __enter__(self):
        site = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                site.requests.append(self.path)
                status, body = site.routes.get(self.path, (404, "not found"))
                raw = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()

    @property
    def page1_url(self) -> str:
        port = self.server.server_address[1]
        return f"http://127.0.0.1:{port}/categories/testcat"

    @property
    def page2_url(self) -> str:
        return self.page1_url + "?page=2"

    def serve_two_pages(self, page2_sku="BBB", total_results=2):
        self.routes["/categories/testcat"] = (
            200, _page_html([_product("AAA", "Alpha Bed", 99900)],
                            page=1, last_page=False, next_page=self.page2_url,
                            total_results=total_results))
        self.routes["/categories/testcat?page=2"] = (
            200, _page_html([_product(page2_sku, "Beta Bed", 129900)],
                            page=2, last_page=True, next_page=None,
                            total_results=total_results))

    def refuse_page2(self):
        self.routes["/categories/testcat?page=2"] = (403, REFUSAL_HTML)


# ---------------------------------------------------------------------------
# Driving the engine
# ---------------------------------------------------------------------------

def _args(monkeypatch, tmp_path, url, *extra):
    """The engine's own parser, pointed at the local site, no .env in play."""
    monkeypatch.setattr(product_parser, "HOSTS",
                        tuple(product_parser.HOSTS) + ("127.0.0.1",))
    monkeypatch.setattr(env_config, "load_env", lambda *a, **k: None)
    for var in ("SLEEPNUMBER_PROXY", "SLEEPNUMBER_URL", "TWOCAPTCHA_KEY",
                    "SLEEPNUMBER_PROXY_BUDGET_MB", "SLEEPNUMBER_LOAD_MEDIA"):
        monkeypatch.delenv(var, raising=False)
    argv = ["http_scraper.py", "--url", url, "--out", str(tmp_path / "out"),
            "--pages", "2", "--delay", "0", "--retries", "1", *extra]
    monkeypatch.setattr(sys, "argv", argv)
    return http_scraper.parse_args()


def _skus(tmp_path):
    return sorted(row["sku"] for row in
                  json.loads((tmp_path / "out.json").read_text()))


def _progress(tmp_path):
    return json.loads((tmp_path / "out.progress.json").read_text())


def _meta(tmp_path):
    return json.loads((tmp_path / "out.meta.json").read_text())


# ---------------------------------------------------------------------------
# Path 1 + 3: a mid-run refusal keeps the contract, then --resume finishes
# ---------------------------------------------------------------------------

def test_refusal_then_resume(monkeypatch, tmp_path):
    with _Site() as site:
        site.serve_two_pages()
        site.refuse_page2()

        # Run 1: page 1 served, page 2 refused -> partial run, exit 6.
        rc = http_scraper.scrape(_args(monkeypatch, tmp_path, site.page1_url))
        assert rc == 6
        assert _skus(tmp_path) == ["AAA"]          # gathered rows are kept
        meta = _meta(tmp_path)
        assert meta["status"] == "partial"
        assert meta["stop_reason"].startswith("blocked")

        progress = _progress(tmp_path)
        assert progress["pages_completed"] == [1]
        assert progress["stop_reason"].startswith("blocked")
        # The plan is in the manifest: page 2's URL, planned from page 1.
        assert progress["planned_pages"] == [
            {"page": 2, "url": site.page2_url}]
        assert progress["pages"] == [
            {"page": 1, "url": site.page1_url, "rows": 1, "new_skus": 1}]
        assert progress["seen_skus"] == ["AAA"]
        # The manifest never carries a proxy credential.
        assert ":***@" not in json.dumps(progress) and "proxy" not in json.dumps(progress).lower()

        # Run 2 with --resume: page 2 now served. Page 1 must NOT be
        # re-fetched — its traffic was already paid for in run 1.
        site.serve_two_pages()
        site.requests.clear()
        rc = http_scraper.scrape(
            _args(monkeypatch, tmp_path, site.page1_url, "--resume"))
        assert rc == 0
        assert site.requests == ["/categories/testcat?page=2"]
        assert _skus(tmp_path) == ["AAA", "BBB"]
        meta = _meta(tmp_path)
        assert meta["status"] == "complete"
        assert meta["pages_completed"] == 2
        assert _progress(tmp_path)["pages_completed"] == [1, 2]
        assert _progress(tmp_path)["stop_reason"] == "completed"


# ---------------------------------------------------------------------------
# Path 2: a manifest that is missing or belongs to another run -> fresh run
# ---------------------------------------------------------------------------

def test_resume_without_manifest_starts_fresh(monkeypatch, tmp_path, caplog):
    with _Site() as site:
        site.serve_two_pages()
        with caplog.at_level("INFO", logger="http_scraper"):
            rc = http_scraper.scrape(
                _args(monkeypatch, tmp_path, site.page1_url, "--resume"))
        assert rc == 0
        assert "no progress manifest" in caplog.text
        # A fresh run fetches page 1 itself.
        assert "/categories/testcat" in site.requests
        assert _skus(tmp_path) == ["AAA", "BBB"]


def test_resume_with_mismatched_manifest_starts_fresh(monkeypatch, tmp_path,
                                                      caplog):
    with _Site() as site:
        site.serve_two_pages()
        rc = http_scraper.scrape(_args(monkeypatch, tmp_path, site.page1_url))
        assert rc == 0
        assert _progress(tmp_path)["mode"] == "listing"

        # Same --out, same URL, different --mode: the manifest belongs to a
        # different run and must be reported, not silently reused.
        site.requests.clear()
        with caplog.at_level("WARNING", logger="http_scraper"):
            rc = http_scraper.scrape(
                _args(monkeypatch, tmp_path, site.page1_url,
                      "--mode", "product", "--resume"))
        assert "belongs to a different run" in caplog.text
        # It started fresh: page 1 was fetched again.
        assert "/categories/testcat" in site.requests


# ---------------------------------------------------------------------------
# The edges of the resume contract
# ---------------------------------------------------------------------------

def test_completed_manifest_finalizes_without_fetching(monkeypatch, tmp_path):
    with _Site() as site:
        site.serve_two_pages()
        rc = http_scraper.scrape(_args(monkeypatch, tmp_path, site.page1_url))
        assert rc == 0

        site.requests.clear()
        rc = http_scraper.scrape(
            _args(monkeypatch, tmp_path, site.page1_url, "--resume"))
        assert rc == 0
        assert site.requests == []                 # not one page re-fetched
        assert _skus(tmp_path) == ["AAA", "BBB"]
        assert _meta(tmp_path)["status"] == "complete"


def test_no_new_sku_still_ends_the_listing(monkeypatch, tmp_path):
    with _Site() as site:
        # Page 2 carries the SAME products as page 1: the data-side
        # terminating condition, which must hold on a resumed run too.
        # The payload's arithmetic still plans a page 2 (per_page=1,
        # total_results=2 — the site's own numbers, however inconsistent
        # with what it serves), and both products are parsed, so the
        # parser-shortfall check has nothing to complain about.
        products = [_product("AAA", "Alpha Bed", 99900),
                    _product("AAC", "Alpha Bed", 109900)]
        site.routes["/categories/testcat"] = (
            200, _page_html(products, page=1, last_page=False,
                            next_page=site.page2_url))
        site.routes["/categories/testcat?page=2"] = (
            200, _page_html(products, page=1, last_page=False,
                            next_page=site.page2_url))
        rc = http_scraper.scrape(_args(monkeypatch, tmp_path, site.page1_url))
        assert rc == 0
        assert _meta(tmp_path)["stop_reason"] == "no_new_products"
        assert _progress(tmp_path)["stop_reason"] == "no_new_products"
        assert _skus(tmp_path) == ["AAA", "AAC"]

        # A resume of a run that already reached the data-side end must NOT
        # re-fetch the pending pages — the site itself said it was finished.
        site.requests.clear()
        rc = http_scraper.scrape(
            _args(monkeypatch, tmp_path, site.page1_url, "--resume"))
        assert rc == 0
        assert site.requests == []
