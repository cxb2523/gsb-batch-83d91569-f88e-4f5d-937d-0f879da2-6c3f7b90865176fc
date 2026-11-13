"""tests/test_http_page_log.py
------------------------------
The HTTP transport's per-page run log (`facts["page_log"]`) and stop reasons,
exercised end to end through `http_scraper.scrape()` with a FAKE session.

Every page is served from HTML built in this file and every "response" comes
from a stub session object — no socket is ever opened, no proxy is contacted.
The three paths covered are the ones an operator has to tell apart from the
sidecar alone:

1. a normal multi-page run that paginates until a page adds no new SKU;
2. a page refused (403) on one exit that succeeds after rotating to another;
3. the proxy budget running out before page 2 — rows already gathered are
   kept and the run is a partial success (and a failure when it has no rows).
"""

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import http_scraper  # noqa: E402
import output_writer  # noqa: E402
import proxy_meter  # noqa: E402

BASE_URL = ("https://www.homedepot.com/b/Tools-Power-Tools-Saws-Miter-Saws"
            "/N-5yc1vZc2d7")

PAGE_ENTRY_KEYS = {"page", "url", "state", "http_status", "attempts",
                   "rotated", "new_rows", "exit", "elapsed_ms"}


def listing_html(skus):
    """A minimal but real-shaped listing page: an Apollo state whose
    SearchModel declares `contentType: plppage` and points at one BaseProduct
    node per sku — exactly what `product_parser.listing_products` reads."""
    refs = []
    state = {"search-model": {
        "__typename": "SearchModel",
        "metadata": {"contentType": "plppage",
                     "stores": {"storeId": "121", "storeName": "Cumberland",
                                "address": {"postalCode": "30339"}}},
        "searchReport": {"totalProducts": len(skus), "pageSize": 12},
        "products": refs}}
    for sku in skus:
        key = "base-searchNav-%s" % sku
        refs.append({"__ref": key})
        state[key] = {
            "__typename": "BaseProduct",
            "identifiers": {"itemId": str(sku),
                            "productLabel": "Saw %s" % sku,
                            "canonicalUrl": "/p/saw/%s" % sku},
            "pricing": {"value": 99.0}}
    return ("<html><body><script>window.__APOLLO_STATE__="
            + json.dumps(state) + ";</script></body></html>")


BLOCKED_HTML = ("<html><head><title>Access Denied</title></head>"
                "<body>Access Denied</body></html>")


class FakeResponse:
    """Just enough of a `requests.Response` for `http_scraper.fetch`."""

    def __init__(self, status, text, url):
        self.status_code = status
        self.text = text
        self.url = url
        self.headers = {}


class FakeSession:
    """A session whose `.get` is answered by the test's responder."""

    def __init__(self, responder):
        self.responder = responder
        self.requested = []

    def get(self, url, timeout=60, allow_redirects=True):
        self.requested.append(url)
        return self.responder(url, self)


def make_args(**overrides):
    defaults = dict(
        url=BASE_URL, mode="category", category=None, pages=3,
        max_products=None, retries=0, retry_delay=0.0, delay=0.0,
        timeout=5, dump_html=None, verbose=False, http_client="requests",
        proxy=None, proxy_file=None, proxy_rotate="per-run",
        proxy_shuffle=False, proxy_sessions=None, proxy_block_retries=3,
        proxy_budget_mb=0,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def run_scrape(args, responder):
    """`scrape()` with `build_session` replaced by a FakeSession factory.
    Returns `(rows, facts, sessions)` — one FakeSession per built session, so
    a test can tell the first exit's session from a rotated one."""
    sessions = []

    def factory(proxy=None, client=None):
        session = FakeSession(responder)
        sessions.append(session)
        return session

    with mock.patch.object(http_scraper, "build_session", factory):
        rows, facts = http_scraper.scrape(args)
    return rows, facts, sessions


class PageLog(unittest.TestCase):

    def test_normal_multipage_run_logs_every_page(self):
        """Four pages planned; the third adds no NEW sku and ends the run, so
        page 4 is never requested."""
        pages = {None: [101, 102], "12": [103, 104], "24": [103, 104]}

        def responder(url, session):
            nao = url.split("Nao=")[1] if "Nao=" in url else None
            return FakeResponse(200, listing_html(pages[nao]), url)

        args = make_args(pages=4)
        rows, facts, sessions = run_scrape(args, responder)

        self.assertEqual(len(rows), 4)
        self.assertEqual(len(sessions), 1, "no rotation on a clean run")
        log = facts["page_log"]
        self.assertEqual([e["page"] for e in log], [1, 2, 3])
        for entry in log:
            self.assertEqual(set(entry), PAGE_ENTRY_KEYS)
            self.assertEqual(entry["state"], "content")
            self.assertEqual(entry["http_status"], 200)
            self.assertEqual(entry["attempts"], 1)
            self.assertIs(entry["rotated"], False)
        self.assertEqual(log[0]["url"], BASE_URL)
        self.assertIn("Nao=12", log[1]["url"])
        self.assertIn("Nao=24", log[2]["url"])
        self.assertEqual([e["new_rows"] for e in log], [2, 2, 0])
        self.assertEqual(http_scraper._stop_reason(args, facts), "no_new_products")
        self.assertEqual(facts["rotations"], 0)

    def test_run_that_reaches_the_last_page_is_completed(self):
        def responder(url, session):
            skus = [103, 104] if "Nao=" in url else [101, 102]
            return FakeResponse(200, listing_html(skus), url)

        args = make_args(pages=2)
        rows, facts, _ = run_scrape(args, responder)

        self.assertEqual(len(rows), 4)
        self.assertEqual([e["new_rows"] for e in facts["page_log"]], [2, 2])
        self.assertEqual(http_scraper._stop_reason(args, facts), "completed")

    def test_blocked_page_rotates_exit_and_succeeds(self):
        """Page 2 is refused (403) on the first exit; the rotated exit serves
        it. The log must show the rotation and never a credential."""
        with tempfile.TemporaryDirectory() as tmp:
            proxy_file = Path(tmp) / "proxies.txt"
            proxy_file.write_text(
                "http://user1:secret1@exit-a.example:1001\n"
                "http://user2:secret2@exit-b.example:1002\n",
                encoding="utf-8")

            def responder(url, session):
                if "Nao=12" in url:
                    if session is sessions[0]:
                        return FakeResponse(403, BLOCKED_HTML, url)
                    return FakeResponse(200, listing_html([103, 104]), url)
                return FakeResponse(200, listing_html([101, 102]), url)

            args = make_args(pages=2, retries=2,
                             proxy_file=str(proxy_file))
            sessions_holder = []
            original_factory_sessions = None

            # run_scrape builds the session list internally; re-implement the
            # factory here so the responder can compare against sessions[0].
            def factory(proxy=None, client=None):
                session = FakeSession(responder)
                sessions_holder.append(session)
                return session

            sessions = sessions_holder
            with mock.patch.object(http_scraper, "build_session", factory):
                rows, facts = http_scraper.scrape(args)

        self.assertEqual(len(rows), 4)
        self.assertEqual(len(sessions), 2, "the run moved to a second session")
        self.assertEqual(facts["rotations"], 1)
        log = facts["page_log"]
        self.assertEqual(len(log), 2)
        first, second = log
        self.assertEqual(first["state"], "content")
        self.assertIs(first["rotated"], False)
        # The refused attempt and the successful one are ONE page entry.
        self.assertEqual(second["state"], "content")
        self.assertEqual(second["http_status"], 200)
        self.assertEqual(second["attempts"], 2)
        self.assertIs(second["rotated"], True)
        self.assertEqual(second["new_rows"], 2)
        # The last exit used is recorded, masked, and is the second exit.
        self.assertIn("exit-b.example", facts["exit"])
        self.assertEqual(second["exit"], facts["exit"])
        self.assertNotIn("secret1", json.dumps(facts))
        self.assertNotIn("secret2", json.dumps(facts))
        self.assertEqual(http_scraper._stop_reason(args, facts), "completed")

    def test_budget_exhausted_before_page_two_keeps_rows(self):
        """The budget trips during page 1: page 2 is never requested, the
        rows from page 1 are kept, and the run exits as a PARTIAL success."""

        def responder(url, session):
            # The metered transport counts its own traffic; the fake does it
            # by hand so the 1-byte budget trips on the first page.
            proxy_meter.current().add(2000)
            return FakeResponse(200, listing_html([101, 102]), url)

        args = make_args(pages=3, proxy_budget_mb=0.000001,  # 1 byte
                         proxy="http://user:secret@exit-a.example:1001")
        rows, facts, sessions = run_scrape(args, responder)

        self.assertEqual(len(rows), 2, "the rows page 1 gave are kept")
        self.assertEqual(facts["stop_reason"], proxy_meter.STOP_REASON)
        self.assertEqual(http_scraper._stop_reason(args, facts),
                         "proxy_budget_exceeded")
        # Page 2 was never requested, so there is exactly one page entry.
        self.assertEqual(len(sessions[0].requested), 1)
        log = facts["page_log"]
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["page"], 1)
        self.assertEqual(log[0]["state"], "content")
        self.assertEqual(log[0]["new_rows"], 2)

        # ... and the sidecar a run like this writes says the same: partial,
        # with the per-page log inside transport_facts.
        with tempfile.TemporaryDirectory() as tmp:
            prefix = str(Path(tmp) / "out")
            rc = output_writer.finish_run(
                rows, prefix, "json", False,
                blocked=False, stop_reason=facts["stop_reason"],
                pages_requested=args.pages,
                pages_completed=facts["pages_completed"],
                pages_failed=facts["failed_pages"], mode="category",
                start_url=facts["start_url"], final_url=facts["final_url"],
                extra=facts)
            self.assertEqual(rc, output_writer.EXIT_PARTIAL)
            sidecar = json.loads((Path(tmp) / "out.latest_attempt.meta.json")
                                 .read_text(encoding="utf-8"))
            self.assertEqual(sidecar["status"], "partial")
            self.assertEqual(sidecar["stop_reason"], "proxy_budget_exceeded")
            logged = sidecar["transport_facts"]["page_log"]
            self.assertEqual([e["page"] for e in logged], [1])
            self.assertEqual(logged[0]["new_rows"], 2)

    def test_budget_exhausted_before_any_row_keeps_failure_semantics(self):
        """The same budget stop with zero rows gathered is exit 5, not a
        partial success — there is no answer to keep."""
        proxy_meter.start(0.000001, active=True)
        proxy_meter.current().add(2000)
        self.assertTrue(proxy_meter.exceeded())
        with tempfile.TemporaryDirectory() as tmp:
            prefix = str(Path(tmp) / "out")
            rc = output_writer.finish_run(
                [], prefix, "json", False,
                blocked=False, stop_reason=proxy_meter.STOP_REASON,
                pages_requested=3, pages_completed=0, pages_failed=[],
                mode="category", start_url=BASE_URL, final_url=BASE_URL,
                extra={"page_log": []})
            self.assertEqual(rc, output_writer.EXIT_REMOTE_API_ERROR)
            sidecar = json.loads((Path(tmp) / "out.latest_attempt.meta.json")
                                 .read_text(encoding="utf-8"))
            self.assertEqual(sidecar["stop_reason"], "proxy_budget_exceeded")
            self.assertEqual(sidecar["status"], "failed")
        proxy_meter.start(None, active=False)


if __name__ == "__main__":
    unittest.main()
