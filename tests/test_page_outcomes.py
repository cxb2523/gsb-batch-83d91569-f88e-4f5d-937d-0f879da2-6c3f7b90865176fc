"""Per-URL page outcomes (`page_outcomes` in the .meta.json sidecar).

Every requested URL gets exactly ONE final verdict — row_read,
page_not_found, login_wall, rate_limited, parse_error or not_requested —
driven through the shared page_flow.run loop with a fake engine over the
REAL captured fixtures in tests/fixtures. No network, no browser, no paid
tasks. These tests pin:

* the six-way verdict split on a mixed run, one entry per requested URL
  (including every post expanded by --posts), with the counts and the
  existing status / stop_reason / exit-code semantics unchanged;
* skipped (--incremental-from) and filtered (--since) posts recorded as
  not_requested with their reason, never as failures;
* a retried URL leaving only its FINAL verdict and one entry, however many
  times it was fetched (both an in-run navigation retry and a --resume).
"""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import page_flow as flow
import page_parser as parser
import playwright_scraper as playwright

FIX = Path(__file__).parent / "fixtures"
PROFILE = (FIX / "instagram_profile_natgeo_live_20261004.html").read_text(encoding="utf-8")
POST = (FIX / "instagram_post_image_live_20261004.html").read_text(encoding="utf-8")
NOT_FOUND = (FIX / "instagram_not_found_live_20261004.html").read_text(encoding="utf-8")
LOGIN = (FIX / "instagram_login_wall_live_20261004.html").read_text(encoding="utf-8")
THROTTLED = (FIX / "instagram_throttled_post_live_20261004.html").read_text(encoding="utf-8")
CODE = "DeAZ0uAgNuA"

PROFILE_URL = parser.profile_url("natgeo")
# The first shortcode the natgeo capture's timeline embeds (pinned first).
EXPANDED_CODE = parser.timeline_shortcodes(PROFILE)[0]
EXPANDED_URL = parser.post_url(EXPANDED_CODE)


def post_url(n):
    return parser.post_url(n)


def post_page(code):
    """The real image-post capture, re-keyed to another shortcode."""
    return POST.replace(CODE, code)


def parse_error_profile(username):
    """A real profile route that still carries its data block, but with the
    field the parser requires removed: decide() must call this parse_error,
    never a row and never a block."""
    return PROFILE.replace('"username":"natgeo"', '"username":"%s"' % username).replace(
        '"follower_count"', '"follower_kount"')


class FakeEngine:
    """page_flow.Engine over a {url: html} map. `fail_first` are URLs whose
    FIRST navigation raises (a later --retries attempt then succeeds)."""

    name = "test"
    readiness_s = 0

    def __init__(self, pages, fail_first=()):
        self.pages, self.fail_first = pages, set(fail_first)
        self.asked, self.goto_count = [], {}

    async def open(self, proxy):
        engine = self

        class Session:
            async def goto(self, target):
                url = target.removesuffix("?hl=en")  # page_flow pins the language
                engine.asked.append(url)
                engine.goto_count[url] = engine.goto_count.get(url, 0) + 1
                if url in engine.fail_first and engine.goto_count[url] == 1:
                    raise RuntimeError("net::ERR_TIMED_OUT")
                self.url = url
                return 200

            async def content(self):
                return engine.pages[self.url]

            async def wait(self, seconds):
                pass

            async def close(self):
                pass

        return Session()

    async def sleep(self, seconds):
        pass

    async def solve_captcha(self, *a, **kw):
        raise AssertionError("no paid solving in page-outcome tests")


class PageOutcomes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def args(self, *flags, name="out"):
        return playwright.build_arg_parser().parse_args(
            ["--retries", "0", "--solve-captcha", "off", "--delay-between-pages", "0",
             "--retry-delay", "0", "--allow-empty",
             "--out", str(self.root / (name + ".json")), *flags])

    def run_flow(self, args, urls, engine):
        code = asyncio.run(flow.run(engine, args, urls=urls, proxy_pool=None, client=None, started_at=0))
        meta = json.loads(Path(args.out + ".meta.json").read_text())
        rows = json.loads(Path(args.out).read_text())
        return code, meta, rows, engine

    def verdict_map(self, meta):
        return {entry["url"]: entry for entry in meta["page_outcomes"]}

    def test_mixed_run_records_every_verdict_once_with_counts_and_exit_code(self):
        # Input order is chosen so blocked answers never reach
        # STOP_AFTER_CONSECUTIVE_BLOCKS (a good/failed page resets the run).
        p_not_found = post_url("Zznotfound01")
        p_login = post_url("Zzloginwall2")
        p_good = post_url("Zzgood00003")
        p_throttle = post_url("Zzthrottle4")
        p_parse_user = parser.profile_url("zzparse0005")
        urls = [PROFILE_URL, p_not_found, p_login, p_good, p_throttle, p_parse_user]
        pages = {
            PROFILE_URL: PROFILE,
            EXPANDED_URL: post_page(EXPANDED_CODE),       # --posts 1 expands this one
            p_not_found: NOT_FOUND,
            p_login: LOGIN,
            p_good: post_page("Zzgood00003"),
            p_throttle: THROTTLED,
            p_parse_user: parse_error_profile("zzparse0005"),
        }
        code, meta, rows, engine = self.run_flow(self.args("--posts", "1", name="mixed"), urls, FakeEngine(pages))

        # Rows were read but the run did not finish cleanly: still exit 6.
        self.assertEqual(code, 6)
        self.assertEqual(meta["status"], "partial")
        # A throttle is present, so it names the throttle rather than the block.
        self.assertEqual(meta["stop_reason"], "rate_limited")

        # One verdict per requested URL, in queue order, posts expanded included.
        fetch_order = [u.removesuffix("?hl=en") for u in engine.asked]
        outcomes = meta["page_outcomes"]
        self.assertEqual([o["url"] for o in outcomes], fetch_order)
        self.assertEqual(len(outcomes), meta["pages_requested"])
        expected = {
            PROFILE_URL: "row_read",
            EXPANDED_URL: "row_read",
            p_not_found: "page_not_found",
            p_login: "login_wall",
            p_good: "row_read",
            p_throttle: "rate_limited",
            p_parse_user: "parse_error",
        }
        self.assertEqual({u: o["verdict"] for u, o in self.verdict_map(meta).items()}, expected)
        # Every one of these pages was fetched exactly once.
        self.assertTrue(all(o["requests"] == 1 for o in outcomes))

        # Counts: each verdict once except row_read (profile + expanded + good).
        self.assertEqual(meta["page_outcome_counts"], {
            "row_read": 3, "page_not_found": 1, "login_wall": 1,
            "rate_limited": 1, "parse_error": 1, "not_requested": 0,
        })
        # The counts sum to the number of requested URLs and to the ledger.
        self.assertEqual(sum(meta["page_outcome_counts"].values()), len(outcomes))

        # The three rows really were written; the not-found page is not a row.
        self.assertEqual(len(rows), 3)
        self.assertIn(p_not_found, meta["not_found_urls"])
        # Failed-page bookkeeping is unchanged and agrees with the ledger.
        self.assertEqual(meta["failed_pages"], [i for i, o in enumerate(outcomes, 1)
                                                if o["verdict"] in ("login_wall", "rate_limited", "parse_error")])

    def test_since_filtered_post_is_not_requested_not_a_failure(self):
        p_old = post_url("Zzoldpost001")
        pages = {PROFILE_URL: PROFILE, p_old: post_page("Zzoldpost001")}
        # A date past every post in the fixtures: the post is fetched then dropped.
        code, meta, rows, engine = self.run_flow(self.args("--since", "2099-01-01"), [PROFILE_URL, p_old],
                                                 FakeEngine(pages))
        self.assertEqual(code, 0)  # profiles are retained; nothing failed
        outcomes = self.verdict_map(meta)
        self.assertEqual(outcomes[p_old]["verdict"], "not_requested")
        self.assertEqual(outcomes[p_old]["detail"], "before_since")
        self.assertEqual(outcomes[PROFILE_URL]["verdict"], "row_read")
        # It WAS fetched (then filtered), and it is not reported as a failed URL.
        self.assertEqual(outcomes[p_old]["requests"], 1)
        self.assertFalse(any(f["url"] == p_old for f in meta["failed_urls"]))
        self.assertIn({"url": p_old, "reason": "before_since"}, meta["excluded_urls"])
        self.assertEqual(meta["page_outcome_counts"]["not_requested"], 1)

    def test_incremental_skipped_post_is_not_requested_with_zero_requests(self):
        p_known = post_url("Zzknownpost1")
        pages = {PROFILE_URL: PROFILE, p_known: post_page("Zzknownpost1")}
        base = self.args(name="base")
        self.run_flow(base, [PROFILE_URL, p_known], FakeEngine(pages))

        delta = self.args("--incremental-from", base.out, name="delta")
        code, meta, rows, engine = self.run_flow(delta, [PROFILE_URL, p_known], FakeEngine(pages))
        self.assertEqual(code, 0)
        # The known post is never asked for again.
        self.assertNotIn(p_known, [u.removesuffix("?hl=en") for u in engine.asked])
        entry = self.verdict_map(meta)[p_known]
        self.assertEqual(entry["verdict"], "not_requested")
        self.assertEqual(entry["detail"], "already_seen")
        self.assertEqual(entry["requests"], 0)
        self.assertFalse(any(f["url"] == p_known for f in meta["failed_urls"]))
        self.assertIn({"url": p_known, "reason": "already_seen"}, meta["excluded_urls"])

    def test_early_stop_leaves_pending_urls_not_requested(self):
        # Without a proxy pool, three blocks in a row stop the run; the rest is
        # reported as not_attempted, which must be a not_requested verdict.
        urls = [post_url("Zzblock%02d" % i) for i in range(5)]
        engine = FakeEngine({u: THROTTLED for u in urls})
        code, meta, rows, _ = self.run_flow(self.args(name="stopped"), urls, engine)
        self.assertEqual(code, 3)  # blocked, no rows
        outcomes = self.verdict_map(meta)
        fetched, pending = urls[:flow.STOP_AFTER_CONSECUTIVE_BLOCKS], urls[flow.STOP_AFTER_CONSECUTIVE_BLOCKS:]
        self.assertTrue(all(outcomes[u]["verdict"] == "rate_limited" and outcomes[u]["requests"] == 1
                            for u in fetched))
        self.assertTrue(all(outcomes[u]["verdict"] == "not_requested"
                            and outcomes[u]["detail"] == "not_attempted" and outcomes[u]["requests"] == 0
                            for u in pending))
        self.assertEqual(meta["page_outcome_counts"]["not_requested"], len(pending))
        self.assertEqual(meta["page_outcome_counts"]["rate_limited"], len(fetched))

    def test_navigation_retry_success_keeps_only_the_final_verdict(self):
        url = post_url("Zzretry0001")
        engine = FakeEngine({url: post_page("Zzretry0001")}, fail_first={url})
        code, meta, rows, _ = self.run_flow(self.args("--retries", "1", name="retry"), [url], engine)
        self.assertEqual(code, 0)
        # Two navigations, but only ONE verdict entry for this URL, the final one.
        self.assertEqual(engine.goto_count[url], 2)
        outcomes = meta["page_outcomes"]
        self.assertEqual(len([o for o in outcomes if o["url"] == url]), 1)
        entry = outcomes[0]
        self.assertEqual(entry["verdict"], "row_read")
        self.assertEqual(entry["requests"], 2)
        self.assertEqual(meta["page_outcome_counts"], {
            "row_read": 1, "page_not_found": 0, "login_wall": 0,
            "rate_limited": 0, "parse_error": 0, "not_requested": 0,
        })

    def test_resume_replaces_a_blocked_verdict_with_the_final_row(self):
        url = post_url("Zzresume001")
        cp = str(self.root / "state.json")
        # First run: the URL answers the login wall -> blocked with no row (3).
        first = self.args("--checkpoint", cp, name="first")
        code, meta, _, _ = self.run_flow(first, [url], FakeEngine({url: LOGIN}))
        self.assertEqual(code, 3)
        self.assertEqual(self.verdict_map(meta)[url]["verdict"], "login_wall")
        # Resume: the same URL now reads fully. Its old record is overwritten,
        # so the final sidecar carries exactly one, successful, verdict.
        resume = self.args("--checkpoint", cp, "--resume", name="resume")
        code, meta, rows, engine = self.run_flow(resume, [url], FakeEngine({url: post_page("Zzresume001")}))
        self.assertEqual(code, 0)
        self.assertEqual([u.removesuffix("?hl=en") for u in engine.asked], [url])
        entries = [o for o in meta["page_outcomes"] if o["url"] == url]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["verdict"], "row_read")
        self.assertEqual(meta["failed_urls"], [])
        self.assertEqual(meta["page_outcome_counts"]["login_wall"], 0)
        self.assertEqual(meta["page_outcome_counts"]["row_read"], 1)

    def test_undecidable_page_defaults_to_parse_error_never_row_read(self):
        # A non-Instagram page (no route, no data): no confident read, so the
        # verdict must be parse_error rather than a defaulted success.
        url = post_url("Zzunknown001")
        code, meta, _, _ = self.run_flow(self.args(name="unknown"), [url],
                                         FakeEngine({url: "<html>Chromium error page</html>"}))
        self.assertEqual(code, 5)  # nothing read, a failure rather than empty
        entry = self.verdict_map(meta)[url]
        self.assertEqual(entry["verdict"], "parse_error")
        self.assertNotEqual(entry["verdict"], "row_read")


if __name__ == "__main__":
    unittest.main()
