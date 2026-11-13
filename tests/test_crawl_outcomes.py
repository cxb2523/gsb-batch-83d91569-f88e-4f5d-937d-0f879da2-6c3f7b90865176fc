"""End-to-end outcome tracking against a local site served by a threaded HTTP server.

The sample site serves every candidate ending in one place:
  /            normal HTML page, linking to all the others
  /about       normal HTML page
  /private     disallowed in robots.txt
  /broken      always answers HTTP 500
  /slow        never answers, so the browser navigation times out
  /flaky       200 on the first request (the browser crawl), 503 afterwards (mirror download)
  /plain       answers 200 with text/plain, so the response is not an HTML page
  /app.css     a normal asset, so a successful asset download happens too
"""
import http.server
import threading

import pytest

from perfectclone.cli import main
from perfectclone.crawl import crawl
from perfectclone.mirror import mirror
from perfectclone.outcomes import CRAWL_ERROR, MIRROR_FAILED, RESPONSE_REJECTED, ROBOTS_SKIPPED, SAVED, OutcomeBook

ROBOTS_TXT = "User-agent: *\nDisallow: /private\n"

INDEX = """<!doctype html><html><head><link rel="stylesheet" href="/app.css"></head><body>
<h1>Home</h1>
<a href="/about">About</a>
<a href="/private">Private</a>
<a href="/broken">Broken</a>
<a href="/slow">Slow</a>
<a href="/flaky">Flaky</a>
<a href="/plain">Plain</a>
</body></html>"""

ABOUT = "<!doctype html><html><body><h1>About</h1><a href=\"/\">Home</a></body></html>"


class SampleHandler(http.server.BaseHTTPRequestHandler):
    # HTTP/1.1 keep-alive: without it the server closes each connection after one response and
    # Chromium reports the next navigation as interrupted instead of following it.
    protocol_version = "HTTP/1.1"

    # One entry per flaky path: counts successful responses, so the second client gets 503.
    flaky_hits = {}
    # Longer than the 1s goto_timeout the tests use, so the browser times out first; short
    # enough that the lingering daemon handler cannot pile up across tests.
    slow_sleep = 3

    def log_message(self, *args):
        pass

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        try:
            if path == "/robots.txt":
                return self._text(200, "text/plain", ROBOTS_TXT)
            if path == "/":
                return self._text(200, "text/html", INDEX)
            if path == "/about":
                return self._text(200, "text/html", ABOUT)
            if path == "/private":
                return self._text(200, "text/html", "<html><body>private</body></html>")
            if path == "/app.css":
                return self._text(200, "text/css", "h1{color:red}\n")
            if path == "/plain":
                return self._text(200, "text/plain", "just text, not a page\n")
            if path == "/broken":
                return self._text(500, "text/html", "<html><body>boom</body></html>")
            if path == "/flaky":
                hits = self.flaky_hits.get(path, 0)
                self.flaky_hits[path] = hits + 1
                if hits == 0:
                    return self._text(200, "text/html",
                                      "<!doctype html><html><body><h1>Flaky</h1></body></html>")
                return self._text(503, "text/html", "<html><body>unavailable</body></html>")
            if path == "/slow":
                # Interruptible sleep: server shutdown closes the socket and wakes the handler.
                event = threading.Event()
                event.wait(self.slow_sleep)
                return
            self._text(404, "text/plain", "not found\n")
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _text(self, status, ctype, body):
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class SampleServer(http.server.ThreadingHTTPServer):
    daemon_threads = True


@pytest.fixture
def server():
    SampleHandler.flaky_hits = {}  # reset per test: the flaky page is 200 only on its first hit
    SampleHandler.slow_sleep = 60  # longer than the default 45s goto timeout used by the CLI
    httpd = SampleServer(("127.0.0.1", 0), SampleHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def by_url(entries):
    return {e["url"]: e for e in entries}


def test_candidate_page_outcomes_cover_every_ending(server, tmp_path):
    SampleHandler.slow_sleep = 3
    book = OutcomeBook()
    pages, assets, external, skipped, book = crawl(
        server + "/", max_pages=200, respect_robots=True, outcomes=book,
        goto_timeout=1500, log=lambda *_: None,
    )

    outcomes = by_url(book.as_list())
    base = server.rstrip("/")
    # Every candidate page URL appears exactly once.
    assert sorted(outcomes) == sorted([
        base + "/", base + "/about", base + "/private", base + "/broken",
        base + "/slow", base + "/flaky", base + "/plain",
    ])
    assert outcomes[base + "/private"]["outcome"] == ROBOTS_SKIPPED
    assert "robots.txt" in outcomes[base + "/private"]["reason"]
    assert outcomes[base + "/broken"]["outcome"] == RESPONSE_REJECTED
    assert "500" in outcomes[base + "/broken"]["reason"]
    assert outcomes[base + "/plain"]["outcome"] == RESPONSE_REJECTED
    assert "text/plain" in outcomes[base + "/plain"]["reason"]
    assert outcomes[base + "/slow"]["outcome"] == CRAWL_ERROR
    assert outcomes[base + "/"]["outcome"] == SAVED
    assert outcomes[base + "/about"]["outcome"] == SAVED
    # The flaky page crawled fine; its mirror outcome is decided below.
    assert outcomes[base + "/flaky"]["outcome"] == SAVED

    # The legacy skipped list still carries the same failures, one entry each.
    skipped_urls = {s["url"] for s in skipped}
    assert {base + "/private", base + "/broken", base + "/slow", base + "/plain"} <= skipped_urls

    saved, fetched, failures, book = mirror(pages, assets, tmp_path / "site",
                                            outcomes=book, log=lambda *_: None)

    outcomes = by_url(book.as_list())
    assert len(outcomes) == 7  # still one record per URL, mirror added no duplicates
    assert outcomes[base + "/flaky"]["outcome"] == MIRROR_FAILED
    assert "503" in outcomes[base + "/flaky"]["reason"]
    assert outcomes[base + "/"]["outcome"] == SAVED
    assert outcomes[base + "/about"]["outcome"] == SAVED

    # Failed pages were never written to the site folder; successful pages were.
    assert not (tmp_path / "site" / "flaky" / "index.html").exists()
    assert (tmp_path / "site" / "index.html").exists()
    assert (tmp_path / "site" / "about" / "index.html").exists()
    assert saved == 2

    # The flaky page's download failure is also in the asset-agnostic failures list.
    assert any(f.get("url") == base + "/flaky" for f in failures)


def test_successful_pages_correspond_to_manifest_page_entries(server, tmp_path):
    SampleHandler.slow_sleep = 3
    book = OutcomeBook()
    pages, assets, _, _, book = crawl(server + "/", outcomes=book, goto_timeout=1500,
                                      log=lambda *_: None)
    _, _, _, book = mirror(pages, assets, tmp_path / "site", outcomes=book, log=lambda *_: None)

    saved_urls = set(book.urls(SAVED))
    page_urls = {p["url"] for p in pages if p["url"] not in set(book.urls(MIRROR_FAILED))}
    assert saved_urls == page_urls == {server + "/", server + "/about"}
    for entry in book.as_list():
        if entry["outcome"] == SAVED:
            assert entry["url"] in page_urls
            assert entry["reason"]


def test_clone_command_writes_manifest_without_raising(server, tmp_path, monkeypatch):
    SampleHandler.slow_sleep = 3
    # The CLI defaults to a 45s navigation timeout; keep the timeout-path test fast.
    monkeypatch.setenv("PERFECTCLONE_GOTO_TIMEOUT", "1500")
    out = tmp_path / "clone"
    # Should not raise even though half the candidate pages fail.
    main(["clone", server, "-o", str(out), "--max-pages", "200"])

    import json
    manifest = json.loads((out / "manifest.json").read_text())
    # All pre-existing fields keep their meaning.
    assert manifest["source"] == server
    assert {p["url"] for p in manifest["pages"]} == {server + "/", server + "/about"}
    assert isinstance(manifest["assets_fetched"], int) and manifest["assets_fetched"] >= 1
    assert isinstance(manifest["failures"], list)
    assert any(s["reason"] == "robots.txt" for s in manifest["skipped"])
    assert isinstance(manifest["external_hosts"], list)

    entries = by_url(manifest["page_outcomes"])
    base = server.rstrip("/")
    assert len(entries) == len(manifest["page_outcomes"])  # unique URLs
    assert entries[base + "/"]["outcome"] == SAVED
    assert entries[base + "/private"]["outcome"] == ROBOTS_SKIPPED
    assert entries[base + "/broken"]["outcome"] == RESPONSE_REJECTED
    assert entries[base + "/plain"]["outcome"] == RESPONSE_REJECTED
    assert entries[base + "/slow"]["outcome"] == CRAWL_ERROR
    assert entries[base + "/flaky"]["outcome"] == MIRROR_FAILED

    # Failed pages appear neither in pages nor under the site folder.
    manifest_page_urls = {p["url"] for p in manifest["pages"]}
    assert not {base + "/broken", base + "/slow", base + "/private",
                base + "/flaky", base + "/plain"} & manifest_page_urls
    assert not (out / "site" / "broken").exists()
    assert not (out / "site" / "slow").exists()
    assert not (out / "site" / "private").exists()
    assert not (out / "site" / "flaky").exists()
    assert not (out / "site" / "plain").exists()
    assert (out / "site" / "index.html").exists()


def test_ignore_robots_crawls_the_disallowed_page(server, tmp_path):
    SampleHandler.slow_sleep = 3
    book = OutcomeBook()
    pages, _, _, skipped, book = crawl(server + "/", respect_robots=False, outcomes=book,
                                       goto_timeout=1500, log=lambda *_: None)
    urls = {p["url"] for p in pages}
    assert server + "/private" in urls
    assert all(s["url"] != server + "/private" for s in skipped)
    assert by_url(book.as_list())[server + "/private"]["outcome"] == SAVED


def test_max_pages_marks_remaining_candidates_as_not_visited(server, tmp_path):
    SampleHandler.slow_sleep = 3
    book = OutcomeBook()
    pages, _, _, _, book = crawl(server + "/", max_pages=2, outcomes=book,
                                 goto_timeout=1500, log=lambda *_: None)
    assert len(pages) == 2
    not_visited = set(book.urls("not_visited"))
    # The crawl stops after two saved pages; everything still queued gets an ending anyway.
    assert not_visited
    assert not (not_visited & {p["url"] for p in pages})
    for entry in book.as_list():
        assert entry["outcome"] and entry["reason"]
