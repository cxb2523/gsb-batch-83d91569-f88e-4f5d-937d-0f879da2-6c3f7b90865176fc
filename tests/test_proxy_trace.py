"""Per-Page proxy trace sidecar (`.proxy-trace.json`): acceptance coverage.

Everything here runs offline: a scripted fake engine and the REAL
ProxyPool over synthetic local Proxy objects stand in for exits — no
browser, no network, no paid task. The four required scenarios plus the
masking and allow-empty edges:

  1. a normal single Page on a direct connection (no pool) is labelled
     "direct";
  2. an exit the site refuses is killed between two Pages and the next
     Page is read through a different exit (and the same rotation inside
     one Page's retries is counted as a switch);
  3. once every exit is dead, the next Page is proxy_pool_exhausted and
     every remaining input is not_attempted, while a run that kept some
     rows still returns the partial exit code;
  4. a run that does not read a single Page writes nothing, so a previous
     successful output (and its trace) is left byte-identical;
  5. proxy identities are masked — a password never reaches the sidecar.
"""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import output_writer as ow
import page_flow as flow
import playwright_scraper as playwright
from proxy_pool import Proxy, ProxyPool

FIX = Path(__file__).parent / "fixtures"
NIKE = (FIX / "fb_page_nike_20261006.html").read_text(encoding="utf-8")
NOT_FOUND = (FIX / "fb_page_not_found_20261006.html").read_text(encoding="utf-8")
NIKE_URL = "https://www.facebook.com/nike"
CHROMIUM_ERROR = ("<html><head><title>www.facebook.com</title></head><body>"
                  "<div id=\"main-message\"><h1>This site can't be reached</h1>"
                  "<div class=\"error-code\">ERR_TIMED_OUT</div></div></body></html>")


class FakeSession:
    """A page session whose answers depend on the exit it was opened on.

    `engine.script` maps a proxy host to a queue of behaviours
    (`ok` | `block` | `dead`); the last behaviour repeats. A direct
    session (proxy is None) always answers `ok`."""

    def __init__(self, engine, proxy):
        self.engine, self.proxy = engine, proxy
        self.behavior = "ok"

    def _next_behavior(self):
        host = self.proxy.host if self.proxy is not None else None
        seq = self.engine.script.get(host)
        if not seq:
            self.behavior = "ok"
        else:
            seen = self.engine.host_counts.get(host, 0)
            self.engine.host_counts[host] = seen + 1
            self.behavior = seq[min(seen, len(seq) - 1)]
        return self.behavior

    async def goto(self, url):
        self.engine.last_url = url
        behavior = self._next_behavior()
        if behavior == "dead":
            raise RuntimeError("net::ERR_PROXY_CONNECTION_FAILED")
        if behavior == "block":
            return 403
        return 200

    async def content(self):
        if self.behavior == "block":
            return CHROMIUM_ERROR
        return self.engine.default_html

    async def current_url(self):
        return self.engine.last_url or NIKE_URL

    async def wait(self, seconds):
        return None

    async def take_responses(self):
        return []

    async def close(self):
        return None


class FakeEngine:
    name = "fake"
    readiness_s = 0

    def __init__(self, script=None, default_html=NIKE):
        self.script = script or {}
        self.default_html = default_html
        self.host_counts = {}
        self.opened = []
        self.last_url = None

    async def open(self, proxy):
        self.opened.append(proxy)
        return FakeSession(self, proxy)

    async def sleep(self, seconds):
        return None

    async def solve_captcha(self, session, *, html, url):
        return None


def make_pool(hosts, block_retries=1):
    proxies = [Proxy(host=host, port=8000 + i, login="user", password="secret-%d" % i)
               for i, host in enumerate(hosts)]
    return ProxyPool(proxies, block_retries=block_retries), proxies


def run_flow(engine, urls, proxy_pool, *, argv=()):
    args = playwright.build_arg_parser().parse_args(["--delay-between-pages", "0", *argv])
    args._solve_budget = flow.SolveBudget(args.max_solves)
    with tempfile.TemporaryDirectory() as td:
        args.out = str(Path(td) / "out.json")
        rc = asyncio.run(flow.run(engine, args, urls=urls, proxy_pool=proxy_pool,
                                  client=None, started_at=0.0))
        root = Path(td)
        trace_path = root / ("out.json" + ow.PROXY_TRACE_SUFFIX)
        meta_path = root / "out.json.meta.json"
        out_path = root / "out.json"
        trace = json.loads(trace_path.read_text()) if trace_path.exists() else None
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else None
        rows = json.loads(out_path.read_text()) if out_path.exists() else None
        listing = sorted(p.name for p in root.iterdir())
        raw_trace = trace_path.read_text() if trace_path.exists() else None
        raw_out = out_path.read_bytes() if out_path.exists() else None
        raw_meta = meta_path.read_bytes() if meta_path.exists() else None
    return rc, trace, meta, rows, listing, raw_trace, raw_out, raw_meta


def label(proxy):
    return flow.proxy_label(proxy)


class ProxyTraceSidecar(unittest.TestCase):
    def test_1_single_page_direct_connection(self):
        engine = FakeEngine()
        rc, trace, meta, rows, listing, raw_trace, _, _ = run_flow(engine, [NIKE_URL], None)
        self.assertEqual(rc, ow.EXIT_OK)
        self.assertEqual(1, len(rows))
        self.assertEqual("complete", meta["status"])
        # the new information lives ONLY in the sidecar: .meta.json is unchanged
        self.assertNotIn("proxies_used", meta)
        self.assertIsNotNone(trace)
        self.assertEqual(trace["engine"], "fake")
        self.assertEqual(trace["pages_requested"], 1)
        self.assertEqual(set(trace), {"engine", "pages_requested", "started_at", "finished_at", "pages"})
        (record,) = trace["pages"]
        self.assertEqual(record, {
            "url": NIKE_URL,
            "result": "ok",
            "reason": None,
            "proxies_used": [ow.DIRECT_PROXY_LABEL],
            "proxy_switches": 0,
        })
        # no temp files are left behind after the atomic publications
        self.assertEqual(sorted(listing), ["out.json", "out.json.meta.json", "out.json.proxy-trace.json"])

    def test_2_exit_refused_between_two_pages_rotates_to_another(self):
        pool, (bad, good) = make_pool(["bad.exit", "good.exit"])
        engine = FakeEngine(script={"bad.exit": ["block"], "good.exit": ["ok"]})
        u2 = "https://www.facebook.com/bbcnews"
        rc, trace, meta, rows, listing, raw_trace, _, _ = run_flow(
            engine, [NIKE_URL, u2], pool, argv=["--retries", "0"])
        self.assertEqual(rc, ow.EXIT_PARTIAL)  # one blocked Page, one row kept
        self.assertEqual(meta["stop_reason"], "blocked")
        self.assertEqual([p.host for p in engine.opened], ["bad.exit", "good.exit"])
        first, second = trace["pages"]
        self.assertEqual(first["result"], "failed")
        self.assertEqual(first["reason"], "blocked")
        self.assertEqual(first["proxies_used"], [label(bad)])
        self.assertEqual(first["proxy_switches"], 0)
        self.assertEqual(second["result"], "ok")
        self.assertEqual(second["proxies_used"], [label(good)])
        self.assertEqual(second["proxy_switches"], 0)
        # a password must never reach the sidecar; host:port and the masked login stay
        self.assertNotIn("secret-0", raw_trace)
        self.assertNotIn("secret-1", raw_trace)
        self.assertIn("bad.exit:8000", raw_trace)
        self.assertIn("user=***", raw_trace)

    def test_2b_dead_exit_mid_page_rotates_within_the_retry_budget(self):
        pool, (bad, good) = make_pool(["bad.exit", "good.exit"])
        engine = FakeEngine(script={"bad.exit": ["dead"], "good.exit": ["ok"]})
        rc, trace, _, rows, _, _, _, _ = run_flow(
            engine, [NIKE_URL], pool, argv=["--retries", "1"])
        self.assertEqual(rc, ow.EXIT_OK)
        (record,) = trace["pages"]
        self.assertEqual(record["result"], "ok")
        self.assertEqual(record["proxies_used"], [label(bad), label(good)])
        self.assertEqual(record["proxy_switches"], 1)
        self.assertEqual([p.host for p in engine.opened], ["bad.exit", "good.exit"])

    def test_3_pool_exhaustion_marks_remaining_pages_not_attempted_partial_exit(self):
        # first read succeeds on a; b is refused and killed; a's second use
        # is refused and killed too — the pool is then empty.
        pool, (a, b) = make_pool(["a.exit", "b.exit"])
        engine = FakeEngine(script={"a.exit": ["ok", "block"], "b.exit": ["block"]})
        urls = [NIKE_URL, "https://www.facebook.com/p2",
                "https://www.facebook.com/p3", "https://www.facebook.com/p4",
                "https://www.facebook.com/p5"]
        rc, trace, meta, rows, _, _, _, _ = run_flow(
            engine, urls, pool, argv=["--retries", "0"])
        self.assertEqual(rc, ow.EXIT_PARTIAL)
        self.assertEqual(1, len(rows), "the one Page read before exhaustion is kept")
        records = trace["pages"]
        self.assertEqual([r["url"] for r in records], urls)
        self.assertEqual([r["result"] for r in records],
                         ["ok", "failed", "failed", "failed", "not_attempted"])
        self.assertEqual(records[0]["proxies_used"], [label(a)])
        self.assertEqual(records[1]["proxies_used"], [label(b)])
        self.assertEqual(records[2]["proxies_used"], [label(a)])
        self.assertEqual(records[3]["reason"], "proxy_pool_exhausted")
        self.assertEqual(records[3]["proxies_used"], [])
        self.assertEqual(records[4]["reason"], "not_attempted")
        self.assertEqual(records[4]["result"], "not_attempted")
        self.assertEqual(records[4]["proxies_used"], [])
        self.assertEqual(records[4]["proxy_switches"], 0)
        # the same facts are in the run status, whose exit semantics are unchanged
        self.assertEqual([f["reason"] for f in meta["failed_urls"]],
                         ["blocked", "blocked", "proxy_pool_exhausted", "not_attempted"])

    def test_4_zero_pages_read_never_overwrites_the_previous_good_output(self):
        good_engine = FakeEngine()
        rc1, trace1, _, _, _, _, out_bytes1, meta_bytes1 = run_flow(
            good_engine, [NIKE_URL], None)
        self.assertEqual(rc1, ow.EXIT_OK)
        trace_bytes1 = json.dumps(trace1).encode()
        # second run into the SAME output path: the only exit is refused,
        # then the pool is exhausted before any Page is read.
        pool, (only,) = make_pool(["only.exit"])
        bad_engine = FakeEngine(script={"only.exit": ["block"]})
        with tempfile.TemporaryDirectory() as td:
            out = str(Path(td) / "out.json")
            Path(out).write_bytes(out_bytes1)
            Path(ow.meta_path_for(out)).write_bytes(meta_bytes1)
            Path(ow.proxy_trace_path_for(out)).write_bytes(trace_bytes1)
            args = playwright.build_arg_parser().parse_args(
                ["--delay-between-pages", "0", "--retries", "0", "--out", out])
            args._solve_budget = flow.SolveBudget(args.max_solves)
            rc2 = asyncio.run(flow.run(bad_engine, args, urls=[NIKE_URL, "https://www.facebook.com/p2"],
                                       proxy_pool=pool, client=None, started_at=0.0))
            self.assertEqual(rc2, ow.EXIT_BLOCKED)
            self.assertEqual(Path(out).read_bytes(), out_bytes1)
            self.assertEqual(Path(ow.meta_path_for(out)).read_bytes(), meta_bytes1)
            self.assertEqual(Path(ow.proxy_trace_path_for(out)).read_bytes(), trace_bytes1)
            self.assertEqual(sorted(p.name for p in Path(td).iterdir()),
                             ["out.json", "out.json.meta.json", "out.json.proxy-trace.json"])

    def test_5_not_found_is_recorded_and_allow_empty_still_writes_the_trace(self):
        engine = FakeEngine(default_html=NOT_FOUND)
        rc, trace, _, rows, _, _, _, _ = run_flow(
            engine, ["https://www.facebook.com/zzqx-no-such-page-88123"], None, argv=["--allow-empty"])
        self.assertEqual(rc, ow.EXIT_ZERO_PRODUCTS)
        (record,) = trace["pages"]
        self.assertEqual(record["result"], "not_found")
        self.assertIsNone(record["reason"])
        self.assertEqual(record["proxies_used"], [ow.DIRECT_PROXY_LABEL])
        self.assertEqual(record["proxy_switches"], 0)


if __name__ == "__main__":
    unittest.main()
