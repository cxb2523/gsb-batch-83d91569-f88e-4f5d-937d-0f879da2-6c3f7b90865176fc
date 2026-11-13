"""proxy_meter: the byte count against a stub proxy that serves known sizes,
the budget, and every engine's way of counting.

The stub proxy IS the site: it answers absolute-URI requests for
http://meter.test/... itself and counts every byte that crosses its sockets,
which is the ground truth the meter is compared with. Nothing leaves this
machine.

The real-browser tests run when that engine and a Chrome/Chromium binary are
present; with PROXY_METER_REQUIRE=<playwright|pyppeteer|selenium> (CI's
engine jobs) a missing engine or browser is a failure, not a skip.
"""
import argparse
import asyncio
import json
import os
import queue as queue_mod
import shutil
import socket
import sys
import threading
import time
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import proxy_meter  # noqa: E402

REQUIRE = os.environ.get("PROXY_METER_REQUIRE", "")
SITE = "http://meter.test/"
PAGES = {
    "/": ("text/html", b"<html><head><link rel='stylesheet' href='/style.css'><script src='/app.js'></script>"
          b"</head><body>" + b"<p>row</p>" * 2000
          + b"<script>fetch('/data.json').then(function (r) { return r.text(); })"
            b".then(function (t) { document.title = 'done ' + t.length; });</script></body></html>"),
    "/app.js": ("application/javascript", b"var a = 1;" * 5000),
    "/style.css": ("text/css", b"p { color: #123456; }" * 2000),
    "/data.json": ("application/json", b'{"k": "' + b"v" * 30000 + b'"}'),
}
PAGE_BYTES = sum(len(body) for _, body in PAGES.values())  # ~152 KB of bodies


class StubProxy:
    """A forward proxy that serves PAGES itself and counts bytes per path."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(64)
        self.port = self.sock.getsockname()[1]
        self.url = "http://127.0.0.1:%d" % self.port
        self.per_path = {}
        self.lock = threading.Lock()
        threading.Thread(target=self._serve, daemon=True).start()

    def site_bytes(self):
        """Bytes in + out for the stub site's own paths (a browser's own
        background CONNECTs to its vendor are not the page's traffic)."""
        with self.lock:
            return sum(v for k, v in self.per_path.items() if k in PAGES or k.startswith("/"))

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        buf = b""
        try:
            while True:
                while b"\r\n\r\n" not in buf:
                    chunk = conn.recv(65536)
                    if not chunk:
                        return
                    buf += chunk
                head, buf = buf.split(b"\r\n\r\n", 1)
                lines = head.split(b"\r\n")
                method, target = lines[0].decode("latin-1").split(" ")[:2]
                length = 0
                for line in lines[1:]:
                    if line.lower().startswith(b"content-length:"):
                        length = int(line.split(b":", 1)[1])
                while len(buf) < length:
                    chunk = conn.recv(65536)
                    if not chunk:
                        return
                    buf += chunk
                received = len(head) + 4 + length
                buf = buf[length:]
                if method == "CONNECT":
                    path = target
                    body, status, ctype = b"", "403 Forbidden", "text/plain"
                else:
                    path = ("/" + target.split("://", 1)[1].split("/", 1)[1]) if "://" in target else target
                    path = path.split("?", 1)[0]
                    ctype, body = PAGES.get(path, ("text/plain", b"not found"))
                    status = "200 OK" if path in PAGES else "404 Not Found"
                response = ("HTTP/1.1 %s\r\nContent-Type: %s\r\nContent-Length: %d\r\nCache-Control: no-store\r\n"
                            "Connection: %s\r\n\r\n" % (status, ctype, len(body),
                                                        "close" if method == "CONNECT" else "keep-alive")).encode()
                if method != "HEAD":
                    response += body
                conn.sendall(response)
                with self.lock:
                    self.per_path[path] = self.per_path.get(path, 0) + received + len(response)
                if method == "CONNECT":
                    return
        except OSError:
            return
        finally:
            conn.close()

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def chrome_binary():
    for candidate in (os.environ.get("CHROME_BIN"), "/usr/bin/chromium", "/usr/bin/chromium-browser",
                      "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable"):
        if candidate and Path(candidate).exists():
            return candidate
    return shutil.which("chromium") or shutil.which("google-chrome")


def unavailable(test, engine, why):
    if REQUIRE == engine:
        test.fail("PROXY_METER_REQUIRE=%s but %s" % (engine, why))
    test.skipTest(why)


class Budget(unittest.TestCase):
    def test_flag_default_and_validation(self):
        parser = argparse.ArgumentParser()
        proxy_meter.add_budget_argument(parser)
        self.assertEqual(parser.parse_args([]).proxy_budget_mb, 10)
        self.assertEqual(parser.parse_args(["--proxy-budget-mb", "0"]).proxy_budget_mb, 0)
        self.assertEqual(parser.parse_args(["--proxy-budget-mb", "2.5"]).proxy_budget_mb, 2.5)
        for bad in ("-1", "x", "nan", "inf"):
            with self.assertRaises(SystemExit):
                parser.parse_args(["--proxy-budget-mb", bad])

    def test_running_total_budget_and_callback(self):
        meter = proxy_meter.ProxyMeter(1, active=True)
        fired = []
        meter.on_exceeded(lambda: fired.append(1))
        self.assertFalse(meter.add(600_000))
        meter.check()
        self.assertFalse(meter.add(400_000), "exactly the budget is not over it")
        self.assertTrue(meter.add(1))
        meter.add(5)
        self.assertEqual(fired, [1], "the callback fires once")
        with self.assertRaises(proxy_meter.ProxyBudgetExceeded):
            meter.check()
        # No page ever started here, so the bytes are reported as one
        # unattributed entry rather than silently dropped from the ledger.
        self.assertEqual(
            meter.sidecar(),
            {"proxy_bytes": 1_000_006, "proxy_budget_bytes": 1_000_000,
             "proxy_budget_exceeded": True,
             "proxy_pages": [{"page": None, "bytes": 1_000_006, "ok": None,
                              "budget_exceeded": True}]})
        self.assertEqual(meter.summary_line(), "Proxy traffic: 1.0 MB of 1 MB budget")

    def test_zero_is_unlimited(self):
        meter = proxy_meter.ProxyMeter(0, active=True)
        meter.add(10 ** 12)
        self.assertFalse(meter.exceeded)
        self.assertEqual(meter.sidecar()["proxy_budget_bytes"], None)

    def test_inactive_meter_counts_nothing(self):
        meter = proxy_meter.ProxyMeter(0.001, active=False)
        meter.add(10 ** 9)
        self.assertEqual(meter.sidecar(), {"proxy_bytes": None, "proxy_budget_bytes": None,
                                           "proxy_budget_exceeded": False, "proxy_pages": None})
        self.assertFalse(meter.exceeded)

    def test_start_replaces_the_run_meter(self):
        meter = proxy_meter.start(3, active=True)
        self.assertIs(proxy_meter.current(), meter)
        self.assertEqual(meter.budget_bytes, 3_000_000)
        proxy_meter.start(None, active=False)
        self.assertEqual(proxy_meter.current().budget_bytes, 10_000_000)


class PageLedger(unittest.TestCase):
    """The per-page traffic account written beside the run."""

    def test_bytes_are_charged_to_the_page_they_were_spent_on(self):
        meter = proxy_meter.ProxyMeter(0, active=True)
        meter.begin_page(1)
        meter.add(500)
        meter.end_page(1, True)
        meter.begin_page(2)
        meter.add(300)
        meter.add(200)
        meter.end_page(2, False)
        self.assertEqual(meter.ledger(), [
            {"page": 1, "bytes": 500, "ok": True, "budget_exceeded": False},
            {"page": 2, "bytes": 500, "ok": False, "budget_exceeded": False},
        ])
        self.assertEqual(sum(e["bytes"] for e in meter.ledger()), meter.bytes)

    def test_the_page_that_spent_the_budget_is_marked_and_earlier_pages_are_not(self):
        meter = proxy_meter.ProxyMeter(0.001, active=True)  # 1,000 bytes
        meter.begin_page(1)
        meter.add(600)          # page 1: under
        meter.end_page(1, True)
        meter.begin_page(2)
        meter.add(600)          # page 2: over, and it is page 2's byte
        self.assertFalse(meter.ledger()[0]["budget_exceeded"])
        self.assertTrue(meter.ledger()[1]["budget_exceeded"])
        # A page still loading when the budget trips is allowed to finish: its
        # later bytes count, but it is NOT marked as the trigger.
        meter.begin_page(3)
        meter.add(400)
        meter.end_page(3, True)
        meter.end_page(2, True)
        self.assertEqual([e["page"] for e in meter.ledger()], [1, 2, 3])
        self.assertFalse(meter.ledger()[2]["budget_exceeded"])
        self.assertEqual(meter.ledger()[1]["bytes"], 600)
        self.assertEqual(sum(e["bytes"] for e in meter.ledger()), 1600)

    def test_a_page_that_spends_nothing_is_still_listed(self):
        meter = proxy_meter.ProxyMeter(10, active=True)
        meter.begin_page(4)
        meter.end_page(4, True)
        self.assertEqual(meter.ledger(), [
            {"page": 4, "bytes": 0, "ok": True, "budget_exceeded": False}])

    def test_no_proxy_means_a_null_ledger_not_zeroes(self):
        meter = proxy_meter.ProxyMeter(0.001, active=False)
        meter.begin_page(1)
        meter.add(10 ** 9)
        meter.end_page(1, True)
        self.assertIsNone(meter.ledger())
        self.assertIsNone(meter.sidecar()["proxy_pages"])

    def test_zero_budget_still_records_bytes_and_never_trips(self):
        meter = proxy_meter.ProxyMeter(0, active=True)
        for page in (1, 2):
            meter.begin_page(page)
            meter.add(5000)
            meter.end_page(page, True)
        self.assertFalse(meter.exceeded)
        self.assertFalse(any(e["budget_exceeded"] for e in meter.ledger()))
        self.assertEqual([e["bytes"] for e in meter.ledger()], [5000, 5000])

    def test_concurrent_workers_keep_the_ledger_additive(self):
        """Every worker opens pages on its own thread; whatever order the
        bytes land, the entries add up to `proxy_bytes` EXACTLY — never more,
        and never a page missing."""
        meter = proxy_meter.ProxyMeter(0, active=True)
        ids = list(range(2, 14))
        work = queue_mod.Queue()
        for n in ids:
            work.put(n)
        lock, spent = threading.Lock(), []

        def worker():
            while True:
                try:
                    page = work.get_nowait()
                except queue_mod.Empty:
                    return
                meter.begin_page(page)
                for _ in range(3):        # several requests per page
                    meter.add(100)
                meter.end_page(page, True)
                with lock:
                    spent.append(page)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        ledger = meter.ledger()
        self.assertEqual(sorted(e["page"] for e in ledger), sorted(spent))
        self.assertEqual(sum(e["bytes"] for e in ledger), meter.bytes)
        self.assertEqual(meter.bytes, 3 * 100 * len(ids))
        self.assertTrue(all(e["bytes"] == 300 for e in ledger))

    def test_a_page_still_loading_keeps_its_bytes_but_is_not_the_trigger(self):
        """A page that began before the budget tripped, and is still loading
        when a sibling's byte crosses the line, finishes: its bytes are
        charged to it and it is not marked `budget_exceeded`."""
        meter = proxy_meter.ProxyMeter(0.001, active=True)  # 1,000 bytes
        page2_crossed = threading.Event()

        def slow_page():
            meter.begin_page(1)
            meter.add(400)              # 400
            page2_crossed.wait(5)       # its last byte arrives AFTER page 2's
            meter.add(400)              # 800 in total
            meter.end_page(1, True)

        def fast_page():
            meter.begin_page(2)
            meter.add(300)              # 700
            meter.add(400)              # 1,100: THIS page crosses the budget
            page2_crossed.set()
            meter.end_page(2, True)

        slow = threading.Thread(target=slow_page)
        slow.start()
        time.sleep(0.02)                # let page 1 begin first
        fast = threading.Thread(target=fast_page)
        fast.start()
        slow.join(5)
        fast.join(5)
        ledger = {e["page"]: e for e in meter.ledger()}
        self.assertEqual(ledger[1]["bytes"], 800, "the slow page kept its late byte")
        self.assertFalse(ledger[1]["budget_exceeded"],
                         "it began before the budget was spent")
        self.assertTrue(ledger[2]["budget_exceeded"])
        self.assertEqual(sum(e["bytes"] for e in ledger.values()), meter.bytes)

    def test_unattributed_bytes_are_a_null_page_entry_not_page_one(self):
        """The pre-check HEAD goes through the proxy before any page exists.
        Its bytes belong to the run, not to a page, so they are reported as
        one `page: null` entry — the pages' own figures stay honest and the
        entries still sum to `proxy_bytes`."""
        meter = proxy_meter.ProxyMeter(0.001, active=True)
        meter.add(1100)  # the pre-check HEAD alone spends the 1,000-byte budget
        self.assertTrue(meter.ledger()[0]["budget_exceeded"])
        meter.begin_page(1)
        meter.add(500)   # page 1's own request still uses the wire
        meter.end_page(1, True)
        ledger = meter.ledger()
        self.assertEqual([e["page"] for e in ledger], [1, None])
        self.assertEqual(ledger[0]["bytes"], 500)
        self.assertEqual(ledger[1]["bytes"], 1100)
        self.assertEqual(sum(e["bytes"] for e in ledger), meter.bytes)
        self.assertFalse(ledger[0]["budget_exceeded"],
                         "page 1 did not spend it; the run did, before page 1")
        self.assertTrue(ledger[1]["budget_exceeded"])

    def test_a_bound_loop_thread_charges_its_owner_s_page(self):
        """pyppeteer reports CDP events on its own loop thread. The binding
        makes those bytes land on the worker's page, not on page 1."""
        meter = proxy_meter.ProxyMeter(0, active=True)
        ready, go, done = threading.Event(), threading.Event(), threading.Event()
        lent = {}

        def loop_thread():
            lent["ident"] = threading.get_ident()
            ready.set()
            go.wait(5)
            for _ in range(3):
                meter.add(100)          # the CDP event, on the loop's thread
            done.set()

        worker = threading.Thread(target=loop_thread)
        worker.start()
        ready.wait(5)
        meter.bind_source(lent["ident"], threading.get_ident())
        meter.begin_page(2)
        meter.add(50)                   # a byte on the worker's own thread
        go.set()
        done.wait(5)
        worker.join(5)
        meter.end_page(2, True)
        ledger = meter.ledger()
        self.assertEqual(ledger[0]["page"], 2)
        self.assertEqual(ledger[0]["bytes"], 350, "the loop's bytes land on page 2 too")
        self.assertEqual(sum(e["bytes"] for e in ledger), meter.bytes)

    def test_the_ledger_is_stable_when_read_twice(self):
        meter = proxy_meter.ProxyMeter(0, active=True)
        meter.add(300)  # no page: one null-owner entry
        fake = argparse.Namespace()
        for _ in range(2):
            fake.first, fake.second = meter.sidecar(), meter.sidecar()
        self.assertEqual(fake.first, fake.second)
        self.assertEqual(fake.first["proxy_pages"],
                         [{"page": None, "bytes": 300, "ok": None,
                           "budget_exceeded": False}])
        self.assertEqual(sum(e["bytes"] for e in fake.first["proxy_pages"]), meter.bytes)


class RunLedger(unittest.TestCase):
    """`page_flow.run_pages` end to end with a fake browser: the sidecar's
    per-page account, the summary line and the exit code."""

    def setUp(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        import smoke_test
        self.smoke = smoke_test

    def tearDown(self):
        proxy_meter.start(None, active=False)

    def _run(self, answers, *, budget_mb, cost, pages=5, proxied=True):
        return self.smoke._budget_run(answers, budget_mb=budget_mb, cost=cost,
                                      pages=pages, proxied=proxied)

    def test_a_spent_budget_names_the_trigger_and_the_pages_never_started(self):
        # 1,000-byte budget, 600 bytes a page: over it on page 2.
        rc, meta, attempt, rows, ops, out = self._run(
            self.smoke._pages("srp_camry_p1", "srp_camry_p2", "srp_camry_p2",
                              "srp_camry_p2", "srp_camry_p2"),
            budget_mb=0.001, cost=600)
        self.assertEqual(rc, 6)
        self.assertEqual(meta["proxy_bytes"], 1200)
        pages = meta["proxy_pages"]
        self.assertEqual([p["page"] for p in pages], [1, 2])
        self.assertEqual([p["bytes"] for p in pages], [600, 600])
        self.assertEqual([p["ok"] for p in pages], [True, True])
        self.assertEqual([p["budget_exceeded"] for p in pages], [False, True])
        self.assertEqual(meta["pages_unattempted"], [3, 4, 5])
        self.assertEqual(meta["pages_failed"], [])
        self.assertEqual(sum(p["bytes"] for p in pages), meta["proxy_bytes"])
        # The rows already read are kept, and the summary line is still there.
        self.assertEqual(len(rows or []), 7)
        self.assertEqual(out.count("Proxy traffic: 0.0 MB of 0.001 MB budget"), 1)

    def test_a_failed_page_is_recorded_as_not_ok_with_its_bytes(self):
        rc, meta, attempt, rows, ops, out = self._run(
            {self.smoke.SEARCH: [(200, self.smoke.fx("refused_unavailable"), None)]},
            budget_mb=0.001, cost=5000, pages=1)
        self.assertEqual(rc, 5)  # no rows: exit 5, not 3, above a block
        self.assertIsNone(meta)  # nothing written beside intact previous data
        self.assertEqual(attempt["stop_reason"], proxy_budget_exceeded())
        pages = attempt["proxy_pages"]
        self.assertEqual([(p["page"], p["bytes"], p["ok"], p["budget_exceeded"])
                          for p in pages], [(1, 5000, False, True)])
        self.assertEqual(sum(p["bytes"] for p in pages), attempt["proxy_bytes"])

    def test_no_proxy_leaves_the_ledger_null(self):
        rc, meta, attempt, rows, ops, out = self._run(
            self.smoke._pages("srp_camry_p1", "srp_camry_p2"), budget_mb=0.001,
            cost=10 ** 9, pages=2, proxied=False)
        self.assertEqual((rc, len(ops.gotos)), (0, 2))
        self.assertIsNone(meta["proxy_pages"])
        self.assertIsNone(meta["proxy_bytes"])

    def test_zero_budget_records_bytes_and_does_not_stop(self):
        rc, meta, attempt, rows, ops, out = self._run(
            self.smoke._pages("srp_camry_p1", "srp_camry_p2"), budget_mb=0,
            cost=5000, pages=2)
        self.assertEqual(rc, 0)
        self.assertEqual(meta["proxy_bytes"], 10000)
        self.assertFalse(meta["proxy_budget_exceeded"])
        self.assertEqual([(p["page"], p["bytes"], p["budget_exceeded"])
                          for p in meta["proxy_pages"]],
                         [(1, 5000, False), (2, 5000, False)])

    def test_a_run_under_its_budget_has_a_full_account(self):
        rc, meta, attempt, rows, ops, out = self._run(
            self.smoke._pages("srp_camry_p1", "srp_camry_p2"), budget_mb=10,
            cost=1000, pages=2)
        self.assertEqual(rc, 0)
        self.assertEqual([p["page"] for p in meta["proxy_pages"]], [1, 2])
        self.assertTrue(all(p["ok"] for p in meta["proxy_pages"]))
        self.assertEqual(sum(p["bytes"] for p in meta["proxy_pages"]),
                         meta["proxy_bytes"])

    def test_concurrent_workers_reconcile_with_the_sidecar_total(self):
        """Four workers, real worker loops, a budget spent partway: the
        ledger names each attempted page once, marks exactly one trigger, and
        adds up to `proxy_bytes` exactly."""
        import page_flow
        import product_parser as P
        answers = self.smoke._pages(*(["srp_camry_p1"] + ["srp_camry_p2"] * 11))

        def run_concurrently(pages, currency):
            work = queue_mod.Queue()
            for n in pages:
                work.put(n)
            results, lock, exhausted = [], threading.Lock(), threading.Event()
            args = types.SimpleNamespace(delay=0, retries=2, retry_delay=0, pages=12,
                                         headless=False, proxy_block_retries=2,
                                         dump_html=None, out=os.devnull)

            def worker():
                ops = self.smoke._MeteredOps(answers, 600)
                page_flow.worker_loop(ops, args, P.Query(mode="listing"), work,
                                      results, lock, exhausted, "w")
            threads = [threading.Thread(target=worker) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(20)
            left = []
            while True:
                try:
                    left.append(work.get_nowait())
                except queue_mod.Empty:
                    break
            return results, sorted(left), exhausted.is_set()

        rc, meta, attempt, rows, ops, out = self.smoke._budget_run(
            answers, budget_mb=0.003, cost=600, pages=12, concurrency=4,
            run_concurrently=run_concurrently)
        self.assertEqual(rc, 6)
        pages = meta["proxy_pages"]
        attempted = [p["page"] for p in pages]
        self.assertEqual(len(attempted), len(set(attempted)), "one entry per page")
        self.assertEqual(sorted(attempted), sorted(set(attempted)))
        self.assertEqual(sum(p["bytes"] for p in pages), meta["proxy_bytes"])
        triggers = [p for p in pages if p["budget_exceeded"]]
        self.assertEqual(len(triggers), 1, pages)
        # Every page is either attempted or named as never started.
        planned = set(range(1, 13))
        self.assertEqual(set(attempted) | set(meta["pages_unattempted"]), planned)


def proxy_budget_exceeded():
    return proxy_meter.STOP_REASON
    def test_requests_through_the_stub_proxy_matches_its_count(self):
        import requests
        proxy = StubProxy()
        try:
            meter = proxy_meter.ProxyMeter(0, active=True)
            session = requests.Session()
            session.hooks["response"].append(meter.requests_hook)
            for path in PAGES:
                response = session.get(SITE + path.lstrip("/"), proxies={"http": proxy.url}, timeout=10)
                self.assertEqual(response.status_code, 200)
            session.post(SITE + "data.json", data=b"x" * 5000, proxies={"http": proxy.url}, timeout=10)
            time.sleep(0.2)
            truth = proxy.site_bytes()
            self.assertGreater(truth, PAGE_BYTES)
            self.assertLess(abs(meter.bytes - truth) / truth, 0.02, (meter.bytes, truth))
        finally:
            proxy.close()


class CdpEvents(unittest.TestCase):
    def test_loading_finished_and_request_sizes(self):
        meter = proxy_meter.ProxyMeter(0, active=True)
        meter.feed_cdp("Network.requestWillBeSent", {"requestId": "1", "request": {
            "method": "POST", "url": "http://x.test/a?b=1", "headers": {"A": "bc"}, "postData": "12345"}})
        sent = len("POST /a?b=1 HTTP/1.1\r\n") + 2 + len("A") + len("bc") + 4 + 5
        self.assertEqual(meter.bytes, sent)
        meter.feed_cdp("Network.responseReceived", {"requestId": "1", "response": {"status": 200}})
        meter.feed_cdp("Network.dataReceived", {"requestId": "1", "encodedDataLength": 400})
        meter.feed_cdp("Network.loadingFinished", {"requestId": "1", "encodedDataLength": 1000})
        self.assertEqual(meter.bytes, sent + 1000, "loadingFinished carries the whole length")
        meter.feed_cdp("Network.responseReceived", {"requestId": "2", "response": {"status": 200}})
        meter.feed_cdp("Network.dataReceived", {"requestId": "2", "encodedDataLength": 300})
        meter.feed_cdp("Network.loadingFailed", {"requestId": "2"})
        self.assertEqual(meter.bytes, sent + 1300, "a failed load counts what arrived")
        # Chrome's error page for a failed navigation: a finished "load" of
        # ~250 KB with no response, generated locally (seen through a refusing proxy).
        meter.feed_cdp("Network.loadingFailed", {"requestId": "e", "errorText": "net::ERR_TUNNEL_CONNECTION_FAILED"})
        meter.feed_cdp("Network.dataReceived", {"requestId": "e", "encodedDataLength": 0})
        meter.feed_cdp("Network.loadingFinished", {"requestId": "e", "encodedDataLength": 250609})
        meter.feed_cdp("Network.responseReceived", {"requestId": "c", "response": {"fromDiskCache": True}})
        meter.feed_cdp("Network.loadingFinished", {"requestId": "c", "encodedDataLength": 900})
        meter.feed_cdp("Network.requestWillBeSent", {"requestId": "n", "request": {
            "method": "GET", "url": "chrome://new-tab-page/x.js", "headers": {"A": "b"}}})
        meter.feed_cdp("Network.responseReceived", {"requestId": "n",
                                                    "response": {"url": "chrome://new-tab-page/x.js"}})
        meter.feed_cdp("Network.loadingFinished", {"requestId": "n", "encodedDataLength": 6575})
        self.assertEqual(meter.bytes, sent + 1300,
                         "an error page, a cache hit or a chrome:// page crossed no proxy")
        before = meter.bytes
        meter.feed_cdp("Network.requestWillBeSent", {"requestId": "3", "request": {"method": "GET", "url": "data:x"}})
        self.assertEqual(meter.bytes, before, "a data: URL never crosses the proxy")
        meter.feed_cdp("Network.requestWillBeSent", {"requestId": "4", "redirectResponse": {"encodedDataLength": 77},
                                                     "request": {"method": "GET", "url": "http://x.test/"}})
        self.assertEqual(meter.bytes, before + 77 + len("GET / HTTP/1.1\r\n") + 2)

    def test_selenium_log_is_teed_not_stolen(self):
        def entry(method, **params):
            return {"message": json.dumps({"message": {"method": method, "params": params}})}

        class Driver:
            def __init__(self):
                self.log = [entry("Network.responseReceived", requestId="a", response={}),
                            entry("Network.loadingFinished", requestId="a", encodedDataLength=600)]
                self.sent = []

            def get_log(self, kind):
                out, self.log = self.log, []
                return out

            def execute_cdp_cmd(self, cmd, params):
                self.sent.append((cmd, params))

        meter = proxy_meter.ProxyMeter(0.001, active=True)  # 1,000 bytes
        driver = Driver()
        meter.attach_selenium(driver, keep_entries=True)
        meter.poll_selenium(driver)
        self.assertEqual(meter.bytes, 600)
        driver.log += [entry("Network.responseReceived", requestId="b", response={}),
                       entry("Network.loadingFinished", requestId="b", encodedDataLength=500)]
        got = driver.get_log("performance")
        self.assertEqual(len(got), 4, "the engine still reads what the meter polled")
        self.assertEqual(meter.bytes, 1100)
        self.assertTrue(meter.exceeded)
        self.assertIn(("Network.setBlockedURLs", {"urls": ["*"]}), driver.sent)
        self.assertEqual(driver.get_log("performance"), [])
        inactive = proxy_meter.ProxyMeter(1, active=False)
        other = Driver()
        inactive.attach_selenium(other)
        self.assertFalse(hasattr(other, "_proxy_meter_poll"), "no proxy: the driver is left alone")

    def test_pyppeteer_session_and_block(self):
        class Client:
            def __init__(self):
                self.handlers, self.sent = {}, []

            def on(self, name, fn):
                self.handlers[name] = fn

            async def send(self, cmd, params=None):
                self.sent.append((cmd, params))

        client = Client()

        async def create():
            return client

        page = argparse.Namespace(target=argparse.Namespace(createCDPSession=create))
        meter = proxy_meter.ProxyMeter(0.001, active=True)

        async def go():
            await meter.attach_pyppeteer(page)
            client.handlers["Network.responseReceived"]({"requestId": "a", "response": {}})
            client.handlers["Network.loadingFinished"]({"requestId": "a", "encodedDataLength": 2000})
            await asyncio.sleep(0)
            await asyncio.sleep(0)

        asyncio.run(go())
        self.assertIn(("Network.enable", {}), client.sent)
        self.assertEqual(meter.bytes, 2000)
        self.assertIn(("Network.setBlockedURLs", {"urls": ["*"]}), client.sent)

    def test_pyppeteer_block_from_a_worker_thread(self):
        """The budget can trip on a thread with no event loop (a concurrent
        worker): the block is still sent, on the page's own loop."""
        sent = []

        class Client:
            def on(self, name, fn):
                pass

            async def send(self, cmd, params=None):
                sent.append(cmd)

        async def create():
            return Client()

        page = argparse.Namespace(target=argparse.Namespace(createCDPSession=create))
        meter = proxy_meter.ProxyMeter(0.001, active=True)

        async def go():
            await meter.attach_pyppeteer(page)
            worker = threading.Thread(target=meter.add, args=(5000,))
            worker.start()
            worker.join()
            for _ in range(5):
                await asyncio.sleep(0)

        asyncio.run(go())
        self.assertTrue(meter.exceeded)
        self.assertIn("Network.setBlockedURLs", sent)


class PlaywrightHooks(unittest.TestCase):
    def test_sizes_and_budget_route(self):
        class Request:
            method, url, headers, post_data_buffer = "GET", "http://x.test/", {"a": "b"}, None

            def sizes(self):
                return {"requestHeadersSize": 100, "requestBodySize": 0,
                        "responseHeadersSize": 200, "responseBodySize": 5000}

        class Failed(Request):
            def sizes(self):
                raise RuntimeError("no sizes for a failed request")

        class Route:
            def __init__(self):
                self.done = []

            def abort(self, reason=None):
                self.done.append("abort")

            def fallback(self):
                self.done.append("fallback")

        meter = proxy_meter.ProxyMeter(0.006, active=True)
        route = Route()
        meter.playwright_budget_route(route)
        meter.playwright_request_done(Request())
        self.assertEqual(meter.bytes, 5300)
        meter.playwright_request_done(Failed())
        self.assertEqual(meter.bytes, 5300 + len("GET / HTTP/1.1\r\n") + 2 + 1 + 1 + 4)
        meter.playwright_request_done(Request())
        self.assertTrue(meter.exceeded)
        meter.playwright_budget_route(route)
        self.assertEqual(route.done, ["fallback", "abort"])


def _assert_close(test, meter, proxy, tolerance=0.10):
    time.sleep(0.3)
    truth = proxy.site_bytes()
    test.assertGreater(truth, PAGE_BYTES, proxy.per_path)
    test.assertLess(abs(meter.bytes - truth) / truth, tolerance, (meter.bytes, truth, proxy.per_path))


class RealBrowsers(unittest.TestCase):
    """The engines' own byte reports against the stub proxy's count."""

    def test_playwright(self):
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return unavailable(self, "playwright", "playwright is not installed")
        proxy = StubProxy()
        meter = proxy_meter.ProxyMeter(0, active=True)

        async def go():
            async with async_playwright() as pw:
                try:
                    browser = await pw.chromium.launch(headless=True)
                except Exception as exc:  # noqa: BLE001
                    return str(exc).splitlines()[0]
                context = await browser.new_context(proxy={"server": proxy.url})
                await meter.attach_playwright_async(context)
                page = await context.new_page()
                await page.goto(SITE)
                await page.wait_for_function("document.title.indexOf('done') === 0", timeout=10000)
                await page.wait_for_timeout(500)
                await context.close()
                await browser.close()
            return None

        try:
            failed = asyncio.run(go())
        finally:
            proxy.close()
        if failed:
            return unavailable(self, "playwright", "Chromium did not launch: %s" % failed)
        _assert_close(self, meter, proxy)

    def test_playwright_budget_aborts_further_requests(self):
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return unavailable(self, "playwright", "playwright is not installed")
        proxy = StubProxy()
        meter = proxy_meter.ProxyMeter(0.05, active=True)  # 50 KB: spent by the first page
        errors = []

        async def go():
            async with async_playwright() as pw:
                try:
                    browser = await pw.chromium.launch(headless=True)
                except Exception as exc:  # noqa: BLE001
                    return str(exc).splitlines()[0]
                context = await browser.new_context(proxy={"server": proxy.url})
                await meter.attach_playwright_async(context)
                page = await context.new_page()
                await page.goto(SITE)
                await page.wait_for_timeout(1500)
                try:
                    await page.goto(SITE + "?second")
                except Exception as exc:  # noqa: BLE001
                    errors.append(str(exc))
                await context.close()
                await browser.close()
            return None

        try:
            failed = asyncio.run(go())
        finally:
            proxy.close()
        if failed:
            return unavailable(self, "playwright", "Chromium did not launch: %s" % failed)
        self.assertTrue(meter.exceeded)
        self.assertTrue(errors and "ERR_BLOCKED_BY_CLIENT" in errors[0], errors)
        self.assertEqual(sum(1 for k in proxy.per_path if k == "/"), 1)

    def test_pyppeteer(self):
        try:
            from pyppeteer import launch
        except ImportError:
            return unavailable(self, "pyppeteer", "pyppeteer is not installed")
        binary = chrome_binary()
        if not binary:
            return unavailable(self, "pyppeteer", "no Chrome/Chromium binary (set CHROME_BIN)")
        proxy = StubProxy()
        meter = proxy_meter.ProxyMeter(0, active=True)

        async def go():
            browser = await launch(headless=True, executablePath=binary, handleSIGINT=False, handleSIGTERM=False,
                                   handleSIGHUP=False, args=["--no-sandbox", "--proxy-server=" + proxy.url])
            try:
                page = await browser.newPage()
                await meter.attach_pyppeteer(page)
                await page.goto(SITE)
                await page.waitForFunction("document.title.indexOf('done') === 0", {"timeout": 10000})
                await asyncio.sleep(0.5)
            finally:
                await browser.close()

        try:
            asyncio.run(go())
        finally:
            proxy.close()
        _assert_close(self, meter, proxy)

    def test_selenium(self):
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service
        except ImportError:
            return unavailable(self, "selenium", "selenium is not installed")
        binary = chrome_binary()
        if not binary:
            return unavailable(self, "selenium", "no Chrome/Chromium binary (set CHROME_BIN)")
        proxy = StubProxy()
        meter = proxy_meter.ProxyMeter(0, active=True)
        options = Options()
        for arg in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--proxy-server=" + proxy.url):
            options.add_argument(arg)
        options.binary_location = binary
        proxy_meter.selenium_logging_prefs(options)
        driver_path = os.environ.get("CHROMEDRIVER") or shutil.which("chromedriver")
        try:
            driver = webdriver.Chrome(service=Service(driver_path) if driver_path else Service(), options=options)
        except Exception as exc:  # noqa: BLE001
            proxy.close()
            return unavailable(self, "selenium", "chromedriver did not start: %s" % str(exc).splitlines()[0])
        try:
            meter.attach_selenium(driver, keep_entries=False)
            driver.get(SITE)
            deadline = time.time() + 10
            while not driver.title.startswith("done") and time.time() < deadline:
                time.sleep(0.2)
            time.sleep(0.5)
            meter.poll_selenium(driver)
        finally:
            driver.quit()
            proxy.close()
        _assert_close(self, meter, proxy)


if __name__ == "__main__":
    unittest.main()
