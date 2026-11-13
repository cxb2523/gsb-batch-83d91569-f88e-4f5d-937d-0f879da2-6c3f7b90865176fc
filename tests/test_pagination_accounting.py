"""Pagination accounting: every search must leave a checkable conclusion in
the sidecar, even when it ends early — the reader has to be able to tell
"only this many results exist" apart from "the run was cut off here".

These tests drive page_flow.run() with a fake browser session (no network,
no browser binary) and locally constructed GraphQL answer samples. The
samples live next to the real captures in tests/fixtures/ :

  fb_mp_pagination_rate_limited_20261113.txt
      a "Rate limit exceeded" GraphQL error answer — pagination ends
      "rate_limited"; every row read before it is kept.
  fb_mp_pagination_stall_20261113.txt
      a well-formed answer that still announces a next page but repeats a
      listing the embedded search already carried, so it adds nothing new.
      Three in a row end pagination "stalled".
  fb_mp_pagination_no_request_20261113.json
      a marker (no GraphQL body exists for this case): the page never sends
      its pagination request, so the run ends "no_request" having read zero
      pagination answers.

For every early ending the sidecar's `pages[0]` entry must show how many
rows were written (`rows`), how many pagination answers were read
(`pagination_answers`) and why it stopped (`pagination` / `result`), and
the rows already read must all be in the output file. A search that reads
to its natural end still reports result "ok" and exits 0; only an actual
unfinished reason yields exit 6. A run that reads nothing at all must not
overwrite the previous good output.
"""
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import output_writer as ow  # noqa: E402
import page_flow as flow  # noqa: E402
import playwright_scraper as playwright  # noqa: E402

FIX = Path(__file__).parent / "fixtures"
SEARCH_HTML = (FIX / "fb_mp_search_bike_nyc_20261006.html").read_text(encoding="utf-8")
PAGINATION_FORM = (FIX / "fb_mp_pagination_form_20261006.txt").read_text(encoding="utf-8").splitlines()[-1]
RATE_LIMITED_ANSWER = (FIX / "fb_mp_pagination_rate_limited_20261113.txt").read_text(encoding="utf-8")
STALL_ANSWER = (FIX / "fb_mp_pagination_stall_20261113.txt").read_text(encoding="utf-8")
# A normal "there is more" answer, re-keyed from the REAL captured answer.
GOOD_ANSWER = (FIX / "fb_mp_pagination_answer_20261006.txt").read_text(encoding="utf-8")
END_ANSWER = GOOD_ANSWER.replace('"has_next_page":true', '"has_next_page":false')

URL = "https://www.facebook.com/marketplace/nyc/search/?query=bike"
EMBEDDED_ROWS = 6  # the trimmed bike search fixture keeps 6 of the 24 listings


class FakeSession:
    """The engine boundary page_flow talks to. `script` decides whether the
    page's own pagination request appears and what each replayed POST
    answers."""

    def __init__(self, engine, url, script):
        self.engine = engine
        self.url = url
        self.html = script.get("html", SEARCH_HTML)
        self.answers = list(script.get("answers") or [])
        self.sends_first_request = script.get("sends_first_request", True)
        self.request_after = script.get("request_after", 1)
        # The page's own first pagination request answers with this body;
        # a stall test overrides it so even the first captured answer adds
        # nothing new.
        self.first_answer = script.get("first_answer", GOOD_ANSWER)
        self.wheels = 0
        self._first_request_served = False
        self.posted = []
        self.closed = False

    async def goto(self, target):
        self.url = target
        return 200

    async def content(self):
        return self.html

    async def current_url(self):
        return self.url

    async def wait(self, seconds):
        return None

    async def close(self):
        self.closed = True

    async def dismiss_dialog(self):
        return True

    async def wheel(self, pixels):
        self.wheels += 1

    async def take_requests(self):
        # The page emits its own request only after enough wheel rounds;
        # a no_request script never emits one.
        if (self.sends_first_request and not self._first_request_served
                and self.wheels >= self.request_after):
            self._first_request_served = True
            return [(PAGINATION_FORM, self.first_answer)]
        return []

    async def post_form(self, data):
        self.posted.append(data)
        status, body = self.answers[min(len(self.posted) - 1, len(self.answers) - 1)]
        return status, body


class FakeEngine:
    name = "fake"
    readiness_s = 0.0
    can_paginate = True

    def __init__(self, scripts):
        # scripts: {url: script}; "*" is the fallback.
        self.scripts = scripts
        self.sessions = []

    async def open(self, proxy):
        session = FakeSession(self, URL, self.scripts.get(URL) or self.scripts.get("*") or {})
        self.sessions.append(session)
        return session

    async def sleep(self, seconds):
        return None

    async def solve_captcha(self, session, *, html, url):
        return None


def run_pagination(script, *, argv=(), html=None, prior_data=None):
    """One page_flow.run over the fake engine; returns (rc, meta, rows, engine, extra)."""
    extra = list(argv)
    args = playwright.build_arg_parser().parse_args(["--url", URL, "--delay-between-pages", "0", *extra])
    args._solve_budget = flow.SolveBudget(args.max_solves)
    if html is not None:
        script = {**script, "html": html}
    engine = FakeEngine({URL: script})
    with tempfile.TemporaryDirectory() as td:
        args.out = str(Path(td) / "out.json")
        if prior_data is not None:
            Path(args.out).write_text(prior_data, encoding="utf-8")
        rc = asyncio.run(flow.run(engine, args, urls=[URL], proxy_pool=None, client=None, started_at=0.0))
        meta_path = Path(args.out + ".meta.json")
        attempt_path = Path(args.out + ow.ATTEMPT_META_SUFFIX)
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else None
        attempt = (json.loads(attempt_path.read_text(encoding="utf-8"))
                   if attempt_path.exists() else None)
        rows = json.loads(Path(args.out).read_text(encoding="utf-8")) if Path(args.out).exists() else None
        files = sorted(p.name for p in Path(td).iterdir())
        data_on_disk = Path(args.out).read_text(encoding="utf-8") if Path(args.out).exists() else None
    return rc, meta, rows, engine, {"attempt": attempt, "files": files, "data": data_on_disk}


class PaginationAccounting(unittest.TestCase):
    def _page_entry(self, meta):
        self.assertEqual(len(meta["pages"]), 1, meta["pages"])
        return meta["pages"][0]

    def test_rate_limited_keeps_every_row_and_records_the_cutoff(self):
        # One good answer (6 new listings) then the rate-limit answer.
        script = {"answers": [(200, RATE_LIMITED_ANSWER)]}
        rc, meta, rows, engine, extra = run_pagination(script, argv=["--max-results", "500"])
        page = self._page_entry(meta)
        self.assertEqual(rc, ow.EXIT_PARTIAL)
        self.assertEqual(meta["status"], "partial")
        self.assertEqual(meta["stop_reason"], "rate_limited")
        # The sidecar entry answers all three questions at a glance.
        self.assertEqual(page["pagination"], "rate_limited")
        self.assertEqual(page["result"], "rate_limited")
        self.assertEqual(page["pagination_answers"], 2)  # the page's own + the replayed one
        self.assertEqual(page["rows"], EMBEDDED_ROWS + 6)  # 6 embedded + 6 from the good answer
        # Not one row read so far is lost.
        self.assertEqual(len(rows), page["rows"])
        self.assertEqual(len({r["sku"] for r in rows}), len(rows))
        # The throttle ends the search: exactly one replay was sent, then it stopped.
        self.assertEqual(len(engine.sessions[0].posted), 1)

    def test_three_answers_with_nothing_new_end_stalled(self):
        # Every answer — including the page's own captured first one — repeats
        # an already-embedded listing (zero new rows) while still announcing
        # another cursor, so the loop keeps asking until
        # PAGINATION_STALL_ROUNDS empty answers end it.
        script = {"first_answer": STALL_ANSWER,
                  "answers": [(200, STALL_ANSWER)] * flow.PAGINATION_STALL_ROUNDS}
        rc, meta, rows, engine, extra = run_pagination(script, argv=["--max-results", "500"])
        page = self._page_entry(meta)
        self.assertEqual(rc, ow.EXIT_PARTIAL)
        self.assertEqual(meta["status"], "partial")
        self.assertEqual(meta["stop_reason"], "stalled")
        self.assertEqual(page["pagination"], "stalled")
        self.assertEqual(page["result"], "stalled")
        # The page's own first answer + the three stalled replays.
        self.assertEqual(page["pagination_answers"], 1 + flow.PAGINATION_STALL_ROUNDS)
        self.assertEqual(page["rows"], EMBEDDED_ROWS)
        self.assertEqual(len(rows), EMBEDDED_ROWS)  # the repeated listings add no rows, none are dropped either
        self.assertEqual(len(engine.sessions[0].posted), flow.PAGINATION_STALL_ROUNDS)

    def test_a_page_that_never_requests_more_is_no_request(self):
        script = {"sends_first_request": False}
        rc, meta, rows, engine, extra = run_pagination(script, argv=["--max-results", "500"])
        page = self._page_entry(meta)
        self.assertEqual(rc, ow.EXIT_PARTIAL)
        self.assertEqual(meta["stop_reason"], "stalled")
        self.assertEqual(page["pagination"], "no_request")
        self.assertEqual(page["result"], "stalled")
        self.assertEqual(page["pagination_answers"], 0)  # no pagination request ever went out
        self.assertEqual(page["rows"], EMBEDDED_ROWS)
        self.assertEqual(len(rows), EMBEDDED_ROWS)  # the embedded rows are still written out
        self.assertEqual(engine.sessions[0].posted, [])
        self.assertEqual(engine.sessions[0].wheels, flow.WHEEL_ROUNDS)  # it really tried to trigger one

    def test_natural_end_is_complete_exit_0(self):
        # The page's own answer says "more", the single replay says has_next=false.
        script = {"answers": [(200, END_ANSWER)]}
        rc, meta, rows, engine, extra = run_pagination(script, argv=["--max-results", "500"])
        page = self._page_entry(meta)
        self.assertEqual(rc, ow.EXIT_OK)
        self.assertEqual(meta["status"], "complete")
        self.assertEqual(meta["stop_reason"], "complete")
        self.assertEqual(page["pagination"], "end")
        self.assertEqual(page["result"], "ok")  # a clean read still says ok
        self.assertEqual(page["pagination_answers"], 2)
        self.assertEqual(page["rows"], EMBEDDED_ROWS + 6)
        self.assertEqual(len(rows), page["rows"])
        self.assertFalse(meta.get("capped"))

    def test_zero_row_run_does_not_overwrite_the_previous_good_data(self):
        # A page that never paints a feed: the run reads nothing at all.
        shell = ('<script type="application/json">'
                 '{"canonicalRouteName":"comet.fbweb.CometMarketplaceSearchRoute"}</script>')
        script = {"sends_first_request": False}
        previous = json.dumps([{"sku": "previous-good-row"}])
        rc, meta, _rows, engine, extra = run_pagination(
            script, html=shell, argv=["--max-results", "500"], prior_data=previous)
        self.assertEqual(rc, ow.EXIT_REMOTE_API_ERROR)  # not_painted, no rows
        self.assertIsNone(meta, "no sidecar may be written beside the previous good data")
        self.assertIsNone(extra["attempt"], "without an active proxy meter nothing else is written either")
        self.assertEqual(extra["data"], previous, "the previous good output must be untouched")
        self.assertEqual(extra["files"], ["out.json"], "no new file may appear next to the previous good data")


if __name__ == "__main__":
    unittest.main()
