#!/usr/bin/env python3
"""test_batch_per_route.py — offline, no-network checks for batch_scraper's
per-route bookkeeping.

Every engine call is faked, so nothing here touches Chrome, a proxy or the
network. The five things a single route can end as are all covered in one
batch:

    success       — local run, exit 0 with rows
    empty         — local run, exit 0, no rows (a genuine "no flights" answer)
    blocked       — blocked locally (3) AND on the 2Captcha fallback (3)
    scrape_failed — blocked locally, then the fallback attempt RAISES
    not_run       — the proxy budget was spent before the route ran

Each scenario asserts the per_route record's status, path sequence, attempt
count, exit code and budget flag, plus the batch-level exit code and that
`failed_pages` contains ONLY the routes that actually ran and failed.

Run either way:

    python test_batch_per_route.py
    python -m unittest test_batch_per_route -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import batch_scraper  # noqa: E402
from output_writer import (  # noqa: E402
    EXIT_BLOCKED, EXIT_OK, EXIT_PARTIAL, EXIT_REMOTE_API_ERROR,
    EXIT_ZERO_PRODUCTS,
)

# A valid Product row's family-common keys (the skyscanner-specific ones
# all default to None). Faked engine runs write one of these per success.
_PRODUCT_KEYS = (
    "sku", "source", "category", "title", "brand", "price", "currency",
    "price_source", "product_url", "image_url", "scraped_at",
)


def _product_row(sku: str) -> dict:
    return dict(zip(_PRODUCT_KEYS, (
        sku, "skyscanner.com", "flights", f"Itinerary {sku}", "Example Air",
        100.0, "USD", "dom", f"https://www.skyscanner.com/{sku}", None,
        "2026-11-13T00:00:00Z",
    )))


def _routes_csv(directory: Path, destinations) -> Path:
    rows = "origin,destination,depart_date\n" + "".join(
        f"LHR,{dest},2026-12-0{i + 1}\n" for i, dest in enumerate(destinations))
    path = directory / "routes.csv"
    path.write_text(rows, encoding="utf-8")
    return path


class FakeEngine:
    """Stand-in for one engine process. Behaviour is keyed by
    (destination, via); every metered attempt spends 2 MB of the shared
    batch budget. Six attempts (JFK, BCN, MAD local+fallback, CDG
    local+crashing fallback) total 12 MB of the 10 MB cap, so the cap is
    still within limit at 8 MB when CDG's fallback runs and trips only as
    the batch reaches FCO — leaving FCO as the single not_run route."""

    SPEND_BYTES = 2_000_000

    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.calls = []  # one entry per engine invocation: (destination, via, argv)

    def __call__(self, argv):
        out = argv[argv.index("--out") + 1]
        destination = argv[argv.index("--destination") + 1]
        # The local attempt always carries --cdp-endpoint; the fallback does not.
        via = "local" if "--cdp-endpoint" in argv else "2captcha"
        self.calls.append((destination, via, argv))
        action = self.behaviour[(destination, via)]

        # Even a crashed attempt still meters what it spent through the proxy.
        Path(out + ".latest_attempt.meta.json").write_text(json.dumps(
            {"proxy_bytes": self.SPEND_BYTES, "proxy_budget_bytes": 10_000_000,
             "proxy_budget_exceeded": False}), encoding="utf-8")

        if isinstance(action, Exception):
            raise action
        if action == EXIT_OK:
            Path(out).write_text(json.dumps([_product_row(f"{destination}-1")]),
                                 encoding="utf-8")
        return action


def _run_batch(directory: Path, destinations, behaviour, *, budget_mb="10",
               allow_empty=False):
    routes = _routes_csv(directory, destinations)
    out = str(directory / "batch.json")
    engine = FakeEngine(behaviour)
    argv = ["--routes-file", str(routes), "--out", out, "--no-launch-chrome",
            "--proxy-budget-mb", budget_mb]
    if allow_empty:
        argv.append("--allow-empty")
    # scrape_route's run_engine default is bound at def time, so patching
    # _run_engine would not reach it; wrap scrape_route and inject explicitly.
    orig_scrape = batch_scraper.scrape_route
    with mock.patch.object(batch_scraper, "local_cdp_alive", return_value=True), \
            mock.patch.object(batch_scraper, "fallback_configured", return_value=True), \
            mock.patch.object(batch_scraper.time, "sleep"), \
            mock.patch.object(
                batch_scraper, "scrape_route",
                lambda route, **kw: orig_scrape(route, run_engine=engine, **kw)):
        code = batch_scraper.main(argv)
    meta_path = Path(out + ".meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    return code, meta, engine


class PerRouteBookkeepingTests(unittest.TestCase):
    def _five_way_batch(self, directory):
        # Order matters: the two metered runs before the cap is spent are the
        # ones that must still execute; everything after MAD is not_run.
        destinations = ["JFK", "BCN", "MAD", "CDG", "FCO"]
        behaviour = {
            # success on local Chrome
            ("JFK", "local"): EXIT_OK,
            # a genuinely empty search: exit 0, no file, never retried
            ("BCN", "local"): EXIT_ZERO_PRODUCTS,
            # blocked locally AND on the 2Captcha fallback
            ("MAD", "local"): EXIT_BLOCKED,
            ("MAD", "2captcha"): EXIT_BLOCKED,
            # blocked locally; the fallback blows up — it must not kill the batch
            ("CDG", "local"): EXIT_BLOCKED,
            ("CDG", "2captcha"): RuntimeError("scraping browser exploded"),
        }
        code, meta, engine = _run_batch(directory, destinations, behaviour)
        by_dest = {r["destination"]: r for r in meta["per_route"]}
        return code, meta, engine, by_dest

    def test_five_outcomes_status_path_and_attempts(self):
        with tempfile.TemporaryDirectory() as d:
            code, meta, engine, by_dest = self._five_way_batch(Path(d))

        # One record per REQUESTED route — the budget-skipped routes included.
        self.assertEqual(len(meta["per_route"]), 5)
        self.assertEqual(meta["routes_requested"], 5)

        success = by_dest["JFK"]
        self.assertEqual(success["status"], "success")
        self.assertEqual(success["exit_code"], EXIT_OK)
        self.assertEqual(success["path"], ["local"])
        self.assertEqual(success["attempt_count"], 1)
        self.assertFalse(success["not_run"])
        self.assertFalse(success["budget_exhausted"])
        self.assertEqual((success["origin"], success["destination"],
                          success["depart_date"]), ("LHR", "JFK", "2026-12-01"))

        empty = by_dest["BCN"]
        self.assertEqual(empty["status"], "empty")
        # The engine's own zero-products answer is exit 4; an empty search
        # is still an answer, not a failure (it is absent from failed_pages).
        self.assertEqual(empty["exit_code"], EXIT_ZERO_PRODUCTS)
        self.assertEqual(empty["path"], ["local"])
        self.assertEqual(empty["attempt_count"], 1)
        self.assertEqual(empty["rows"], 0)

        blocked = by_dest["MAD"]
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["exit_code"], EXIT_BLOCKED)
        self.assertEqual(blocked["path"], ["local", "2captcha"])
        self.assertEqual(blocked["attempt_count"], 2)
        self.assertFalse(blocked["not_run"])

        crashed = by_dest["CDG"]
        self.assertEqual(crashed["status"], "scrape_failed")
        # A crash on the fallback is normalised to 5, but the raw code (1)
        # is preserved on the attempt itself.
        self.assertEqual(crashed["exit_code"], EXIT_REMOTE_API_ERROR)
        self.assertEqual(crashed["path"], ["local", "2captcha"])
        self.assertEqual(crashed["attempt_count"], 2)
        self.assertEqual(crashed["attempts"][-1]["exit_code"], 1)
        self.assertEqual(crashed["attempts"][-1]["via"], "2captcha")

        # Only FCO was kept from running by the spent budget; CDG ran (its
        # fallback crashed) before the cap tripped at the top of FCO's turn.
        skipped = by_dest["FCO"]
        self.assertEqual(skipped["status"], "not_run")
        self.assertIsNone(skipped["exit_code"])
        self.assertEqual(skipped["path"], [])
        self.assertEqual(skipped["attempt_count"], 0)
        self.assertTrue(skipped["not_run"])
        self.assertTrue(skipped["budget_exhausted"])
        self.assertEqual(
            (skipped["origin"], skipped["destination"], skipped["depart_date"]),
            ("LHR", "FCO", "2026-12-05"))

        invoked = {call[0] for call in engine.calls}
        self.assertEqual(invoked, {"JFK", "BCN", "MAD", "CDG"})
        self.assertNotIn("FCO", invoked)

    def test_batch_exit_code_and_failed_pages(self):
        with tempfile.TemporaryDirectory() as d:
            code, meta, _engine, by_dest = self._five_way_batch(Path(d))

        # Rows were kept (JFK) but MAD/CDG failed and CDG/FCO never ran:
        # the batch is partial (6), never laundered into a full success.
        self.assertEqual(code, EXIT_PARTIAL)
        self.assertEqual(meta["status"], "partial")
        self.assertEqual(meta["stop_reason"], "proxy_budget_exceeded")
        # Routes 3 (blocked) and 4 (scrape failed) really ran and failed;
        # routes 1-2 did not fail and route 5 was never executed, so it is
        # NOT a failed page.
        self.assertEqual(meta["failed_pages"], [3, 4])
        self.assertEqual(meta["pages_requested"], 5)
        self.assertEqual(meta["pages_completed"], 2)  # JFK success, BCN empty
        self.assertEqual(meta["product_count"], 1)
        self.assertTrue(meta["proxy_budget_exceeded"])

    def test_all_blocked_no_rows_is_exit_3_and_records_every_route(self):
        destinations = ["JFK", "BCN"]
        behaviour = {
            ("JFK", "local"): EXIT_BLOCKED, ("JFK", "2captcha"): EXIT_BLOCKED,
            ("BCN", "local"): EXIT_BLOCKED, ("BCN", "2captcha"): EXIT_BLOCKED,
        }
        with tempfile.TemporaryDirectory() as d:
            code, meta, _engine = _run_batch(
                Path(d), destinations, behaviour, budget_mb="0", allow_empty=True)
        self.assertEqual(code, EXIT_BLOCKED)
        self.assertEqual(meta["status"], "blocked")
        self.assertEqual(meta["failed_pages"], [1, 2])
        self.assertEqual([r["status"] for r in meta["per_route"]],
                         ["blocked", "blocked"])
        for record in meta["per_route"]:
            self.assertEqual(record["path"], ["local", "2captcha"])
            self.assertFalse(record["not_run"])

    def test_all_success_or_empty_is_exit_0_with_no_failed_pages(self):
        destinations = ["JFK", "BCN"]
        behaviour = {
            ("JFK", "local"): EXIT_OK,
            ("BCN", "local"): EXIT_ZERO_PRODUCTS,
        }
        with tempfile.TemporaryDirectory() as d:
            code, meta, _engine = _run_batch(
                Path(d), destinations, behaviour, budget_mb="0", allow_empty=True)
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(meta["failed_pages"], [])
        self.assertEqual([r["status"] for r in meta["per_route"]],
                         ["success", "empty"])

    def test_fallback_exception_does_not_stop_later_routes(self):
        # No budget cap: after the crashing fallback the next route still runs.
        destinations = ["MAD", "JFK"]
        behaviour = {
            ("MAD", "local"): EXIT_BLOCKED,
            ("MAD", "2captcha"): RuntimeError("boom"),
            ("JFK", "local"): EXIT_OK,
        }
        with tempfile.TemporaryDirectory() as d:
            code, meta, engine = _run_batch(
                Path(d), destinations, behaviour, budget_mb="0")
        self.assertEqual(code, EXIT_PARTIAL)
        self.assertEqual(meta["failed_pages"], [1])  # only the crashed route
        invoked = [call[0] for call in engine.calls]
        self.assertEqual(invoked[0], "MAD")
        self.assertIn("JFK", invoked, "the batch must continue after a fallback crash")
        records = {r["destination"]: r for r in meta["per_route"]}
        self.assertEqual(records["MAD"]["status"], "scrape_failed")
        self.assertEqual(records["JFK"]["status"], "success")


class StatusMappingTests(unittest.TestCase):
    def test_status_is_consistent_with_exit_code(self):
        cases = [
            (EXIT_OK, 1, False, "success"),
            (EXIT_OK, 0, False, "empty"),
            (EXIT_BLOCKED, 0, False, "blocked"),
            (EXIT_REMOTE_API_ERROR, 0, False, "scrape_failed"),
            (EXIT_PARTIAL, 1, False, "partial"),
            (EXIT_OK, 5, True, "not_run"),
        ]
        for code, rows, not_run, expected in cases:
            with self.subTest(code=code, rows=rows, not_run=not_run):
                self.assertEqual(batch_scraper.route_status(code, rows, not_run), expected)

    def test_crash_normalises_to_scrape_failure(self):
        self.assertEqual(batch_scraper.terminal_exit(1), EXIT_REMOTE_API_ERROR)
        self.assertEqual(batch_scraper.route_status(1, 0), "scrape_failed")
        # Every other code passes through untouched.
        for code in (EXIT_OK, EXIT_BLOCKED, EXIT_ZERO_PRODUCTS,
                     EXIT_REMOTE_API_ERROR, EXIT_PARTIAL):
            self.assertEqual(batch_scraper.terminal_exit(code), code)

    def test_budget_skipped_record(self):
        route = {"origin": "LHR", "destination": "JFK", "depart_date": "2026-12-01"}
        outcome = batch_scraper.RouteOutcome.budget_skipped(route)
        self.assertEqual(outcome.status, "not_run")
        self.assertIsNone(outcome.exit_code)
        self.assertEqual(outcome.path, [])
        self.assertEqual(outcome.attempt_count, 0)
        self.assertTrue(outcome.not_run and outcome.budget_exhausted)
        self.assertEqual(outcome.origin, "LHR")
        # It must serialise cleanly into the meta JSON.
        json.dumps(batch_scraper.asdict(outcome))


if __name__ == "__main__":
    unittest.main(verbosity=2)
