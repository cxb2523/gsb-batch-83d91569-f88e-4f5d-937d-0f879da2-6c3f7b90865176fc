"""--proxy-budget-mb, accounted per search.

When the running proxy total passes the budget, the run stops, but the
sidecar must say what happened to EVERY search on its own: read to the end,
stopped mid-pagination by the budget (with the rows read so far kept and
counted), or never attempted. This drives the real `page_flow.run` with a
fake session (fixture pages, scripted scroll batches) and a fake meter whose
byte count the test controls exactly, so no browser, no network and no
sleeping are involved.

The run-level sidecar keys are checked here too: `proxy_budget_bytes`,
`proxy_bytes` and `proxy_budget_exceeded`.
"""
import asyncio
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import output_writer  # noqa: E402
import page_flow  # noqa: E402
import playwright_scraper  # noqa: E402
import proxy_meter  # noqa: E402
from ad_parser import search_url  # noqa: E402

FIX = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
PAGE = (FIX / "fb_ads_search_nike_us_20261005.html").read_text(encoding="utf-8")
SCROLL = (FIX / "fb_ads_scroll_nike_us_20261005.txt").read_text(encoding="utf-8")


def rekey(text, n):
    """The real capture, its ad ids re-keyed so batch n is made of new ads."""
    return re.sub(r'"ad_archive_id":"(\d+)"', lambda m: '"ad_archive_id":"9%02d%s"' % (n, m.group(1)[-9:]),
                  text)


def search_page(n):
    return rekey(PAGE, n)


def scroll_batch(n, last=False):
    """One scroll's GraphQL answer. `last=True` marks the end of the results
    (`has_next_page: false`), the way the real library ends a search."""
    body = rekey(SCROLL, n)
    return body.replace('"has_next_page":true', '"has_next_page":false') if last else body


class FakeMeter:
    """A meter the test charges itself: no clocks, no threads, no printing.

    It answers exactly the surface `page_flow` and `output_writer` use —
    `exceeded`, `active`, `add()`, `sidecar()`, `report()` — and applies the
    real rule: the budget is passed only when the running total is strictly
    greater than it.
    """

    def __init__(self, budget_bytes, used_bytes=0):
        self.budget_bytes = int(budget_bytes)
        self.bytes = int(used_bytes)
        self.active = True
        self.exceeded = bool(self.budget_bytes) and self.bytes > self.budget_bytes

    def add(self, n):
        try:
            n = int(n or 0)
        except (TypeError, ValueError):
            return self.exceeded
        self.bytes += max(0, n)
        if self.budget_bytes and self.bytes > self.budget_bytes:
            self.exceeded = True
        return self.exceeded

    def sidecar(self):
        return {"proxy_bytes": self.bytes,
                "proxy_budget_bytes": self.budget_bytes or None,
                "proxy_budget_exceeded": bool(self.exceeded)}

    def report(self):
        pass


class FakeSession:
    """One search's page: the fixture page plus a queue of scroll batches.
    Every navigation and every scroll charges the meter `charge` bytes.

    `details_form`/`details_answer` (on the script) make the fake page
    behave as if its "See ad details" dialog would answer: a click succeeds
    and hands back the page's own request — so a run that is forbidden to
    send more requests must not click at all.
    """

    def __init__(self, engine):
        self.engine = engine
        self.url = ""
        self.html = ""
        self.batches = []
        self.pending = []
        self.scrolls = 0
        self.gotos = []
        self.clicks = []
        self.posts = []
        self.closed = False

    async def goto(self, url):
        self.gotos.append(url)
        self.url = url
        self.engine.meter.add(self.engine.charge)
        for key, script in self.engine.scripts.items():
            if url.startswith(key):
                self.html = script["html"]
                self.batches = list(script.get("batches") or [])
                self.script = script
                break
        return 403  # the library's own status for a good page

    async def content(self):
        return self.html

    async def current_url(self):
        return self.url

    async def wait(self, seconds):
        pass  # no real clock: the scripted page is already painted

    async def scroll_to_bottom(self):
        self.engine.meter.add(self.engine.charge)
        self.scrolls += 1
        self.pending = self.batches.pop(0) if self.batches else []

    async def page_height(self):
        return 3000 + 500 * self.scrolls  # always a drawn list, never a render wait

    async def take_responses(self):
        bodies, self.pending = self.pending, []
        return bodies

    async def click_text(self, text):
        self.clicks.append(text)
        clicked = bool(getattr(self, "script", {}).get("details_form"))
        if clicked:
            self._clicked = True
        return clicked

    async def take_requests(self):
        if getattr(self, "_clicked", False) and not getattr(self, "_taken", False):
            self._taken = True
            return [(self.script["details_form"], self.script["details_answer"])]
        return []

    async def post_form(self, data):
        self.posts.append(data)
        return 200, self.script.get("details_answer", "")

    async def close(self):
        self.closed = True


class FakeEngine:
    name = "fake"
    readiness_s = 0.0
    can_scroll = True
    can_details = True

    def __init__(self, meter, scripts, charge):
        self.meter = meter
        self.scripts = scripts
        self.charge = charge
        self.sessions = []

    async def open(self, proxy):
        session = FakeSession(self)
        self.sessions.append(session)
        return session

    async def sleep(self, seconds):
        pass

    async def solve_captcha(self, session, *, html, url):
        return None


NIKE = search_url(query="nike", region="US")
ADIDAS = search_url(query="adidas", region="US")


class BudgetStopAccounting(unittest.TestCase):
    def setUp(self):
        self.meter = None
        self._previous = proxy_meter.current()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def tearDown(self):
        proxy_meter._current = self._previous

    def run_flow(self, meter, scripts, urls, charge, argv=()):
        """Run the shared loop with the fake meter installed."""
        self.meter = meter
        proxy_meter._current = meter
        args = playwright_scraper.build_arg_parser().parse_args(
            ["--query", "nike", "--region", "US", "--max-results", "100",
             "--delay-between-pages", "0", *argv])
        args._solve_budget = page_flow.SolveBudget(0)
        args.out = str(Path(self._tmp.name) / "o.json")
        engine = FakeEngine(meter, scripts, charge)
        rc = asyncio.run(page_flow.run(engine, args, urls=urls, proxy_pool=None, client=None, started_at=0.0))
        out = Path(args.out)

        def read(path):
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

        meta = read(Path(str(out) + ".meta.json"))
        attempt = read(Path(str(out) + output_writer.ATTEMPT_META_SUFFIX))
        rows = read(out)
        for session in engine.sessions:
            self.assertTrue(session.closed, "every opened session must be closed")
        return rc, meta, attempt, rows, engine

    def test_enough_budget_reads_every_search_completely(self):
        """A1: usage under the budget — both searches read to the end, no
        budget stop, the run is complete and records bytes + budget."""
        scripts = {
            NIKE: {"html": search_page(1), "batches": [[scroll_batch(1)], [scroll_batch(2, last=True)]]},
            ADIDAS: {"html": search_page(2), "batches": [[scroll_batch(3, last=True)]]},
        }
        rc, meta, attempt, rows, engine = self.run_flow(
            FakeMeter(10_000_000), scripts, [NIKE, ADIDAS], charge=100)

        self.assertEqual(rc, output_writer.EXIT_OK, meta)
        self.assertIsNone(attempt)
        self.assertEqual(len(rows), 21, "6 embedded + 3 + 3 from the first, 6 + 3 from the second")
        self.assertEqual(len(engine.sessions), 2, "both searches were opened")
        self.assertEqual([s.scrolls for s in engine.sessions], [2, 1])
        self.assertEqual(meta["stop_reason"], "complete")
        self.assertEqual([s["ending"] for s in meta["searches"]], ["complete", "complete"])
        self.assertEqual([s["rows"] for s in meta["searches"]], [12, 9])
        self.assertEqual([s["stop"] for s in meta["searches"]], ["end", "end"])
        self.assertEqual(meta["unattempted_pages"], [])
        self.assertEqual((meta["proxy_bytes"], meta["proxy_budget_bytes"], meta["proxy_budget_exceeded"]),
                         (500, 10_000_000, False))

    def test_mid_pagination_stop_keeps_rows_and_marks_the_rest_unattempted(self):
        """A2: the budget trips on the second scroll — that search keeps
        every row read before the stop and says so; the second search is
        never attempted; exit 6 because rows were written."""
        scripts = {
            NIKE: {"html": search_page(1),
                   "batches": [[scroll_batch(1)], [scroll_batch(2)], [scroll_batch(3)]]},
            ADIDAS: {"html": search_page(2), "batches": [[scroll_batch(7)]]},
        }
        # 1,000 bytes: goto 400, first scroll 800, second scroll 1,200 -> over.
        rc, meta, attempt, rows, engine = self.run_flow(
            FakeMeter(1000), scripts, [NIKE, ADIDAS], charge=400)

        self.assertEqual(rc, output_writer.EXIT_PARTIAL, meta)
        self.assertIsNone(attempt)
        self.assertEqual(len(engine.sessions), 1, "no search after the budget")
        self.assertEqual(engine.sessions[0].scrolls, 2, "no scroll after the budget")
        first, second = meta["searches"]
        self.assertEqual(first["ending"], "budget_stopped")
        self.assertEqual(first["stop"], "proxy_budget_exceeded")
        self.assertEqual(first["rows"], 12, "6 embedded + 3 + 3 read before the stop")
        self.assertEqual(len(rows), 12, "every row read before the stop is in the output")
        self.assertEqual(second["ending"], "not_attempted")
        self.assertFalse(second["attempted"])
        self.assertEqual(second["rows"], 0)
        self.assertEqual(meta["unattempted_pages"], [2])
        self.assertEqual((meta["proxy_bytes"], meta["proxy_budget_bytes"], meta["proxy_budget_exceeded"]),
                         (1200, 1000, True))
        self.assertEqual(meta["stop_reason"], "proxy_budget_exceeded")
        self.assertEqual(meta["status"], "partial")

    def test_budget_spent_before_the_first_search_writes_no_rows_and_exits_5(self):
        """A3: the budget is already over when the run starts — nothing is
        opened, no rows are written, every search is never-attempted, and
        the attempt sidecar records the overrun; exit 5."""
        scripts = {NIKE: {"html": search_page(1)}, ADIDAS: {"html": search_page(2)}}
        rc, meta, attempt, rows, engine = self.run_flow(
            FakeMeter(1000, used_bytes=5000), scripts, [NIKE, ADIDAS], charge=400)

        self.assertEqual(rc, output_writer.EXIT_REMOTE_API_ERROR, attempt)
        self.assertIsNone(rows, "no data file is written")
        self.assertIsNone(meta, "no .meta.json is written")
        self.assertEqual(engine.sessions, [], "no browser session is opened")
        self.assertEqual([s["ending"] for s in attempt["searches"]], ["not_attempted", "not_attempted"])
        self.assertEqual(attempt["unattempted_pages"], [1, 2])
        self.assertEqual(attempt["stop_reason"], "proxy_budget_exceeded")
        self.assertEqual(attempt["data_updated"], False)
        self.assertEqual((attempt["proxy_bytes"], attempt["proxy_budget_bytes"], attempt["proxy_budget_exceeded"]),
                         (5000, 1000, True))

    def test_budget_over_after_the_last_batch_is_still_a_complete_search(self):
        """A run may pass the budget on the very scroll that brings the last
        batch: that search WAS read to the end, so it is `complete` (its
        rows are kept), even though the run stops there and reports the
        overrun."""
        scripts = {
            NIKE: {"html": search_page(1), "batches": [[scroll_batch(1, last=True)]]},
            ADIDAS: {"html": search_page(2)},
        }
        # 790 bytes: goto 400 (under), the one scroll 800 -> over, but it is the end.
        rc, meta, attempt, rows, engine = self.run_flow(
            FakeMeter(790), scripts, [NIKE, ADIDAS], charge=400)

        self.assertEqual(rc, output_writer.EXIT_PARTIAL, meta)
        self.assertEqual(meta["searches"][0]["ending"], "complete")
        self.assertEqual(meta["searches"][0]["stop"], "end")
        self.assertEqual(meta["searches"][0]["rows"], 9)
        self.assertEqual(meta["searches"][0]["budget_stopped"], False)
        self.assertEqual(meta["searches"][1]["ending"], "not_attempted")
        self.assertEqual(meta["stop_reason"], "proxy_budget_exceeded")
        self.assertEqual(len(rows), 9, "the rows read before the run stopped are written")

    def test_no_scroll_or_details_request_after_the_budget_is_spent(self):
        """A4: once the budget trips mid-pagination, no further scroll is
        made and --details sends nothing — the rows are kept regardless."""
        scripts = {
            NIKE: {"html": search_page(1),
                   "details_form": (FIX / "fb_ads_details_form_20261006.txt").read_text(
                       encoding="utf-8").splitlines()[-1],
                   "details_answer": (FIX / "fb_ads_details_answer_20261006.txt").read_text(
                       encoding="utf-8"),
                   "batches": [[scroll_batch(1)], [scroll_batch(2)], [scroll_batch(3)]]},
        }
        rc, meta, attempt, rows, engine = self.run_flow(
            FakeMeter(1000), scripts, [NIKE], charge=400, argv=("--details",))

        self.assertEqual(rc, output_writer.EXIT_PARTIAL, meta)
        session = engine.sessions[0]
        self.assertEqual(session.scrolls, 2, "no scroll after the budget")
        self.assertEqual(len(session.gotos), 1, "no re-navigation after the budget")
        self.assertEqual(session.clicks, [], "the details click would send a request: it must not happen")
        self.assertEqual(session.posts, [], "no details request after the budget")
        self.assertEqual(meta["searches"][0]["details"], "proxy_budget_exceeded")
        self.assertEqual(meta["searches"][0]["details_read"], 0)
        self.assertEqual(meta["searches"][0]["rows"], 12)
        self.assertEqual(len(rows), 12)


if __name__ == "__main__":
    unittest.main()
