"""
run_local.py
------------
End-to-end verification of the Playwright engine's per-round scroll record,
using generated local HTML and a Playwright route interceptor — NO network
and NO change to the production parsing/host logic.

The browser is pointed at the REAL https://www.spinny.com URLs, so the
engine's own parse_args() host validation, URL classifiers and car-path
checks all run unchanged. Every request the browser makes is intercepted and
fulfilled from a generated fixture file instead of being sent anywhere:

    page.route("**/*", handler) -> route.fulfill(status=200, body=<local html>)

The engine reaches this through one explicit, otherwise-unused seam —
`args.route_handler`, wired on the browser session in
playwright_scraper.py — rather than through a monkeypatch.

Run with isolated mode so the generated HTML directory is never importable:

    python -I run_local.py <fixture-dir> <work-dir>

Each scenario asserts on the actual <out>.meta.json written to disk.
"""

import json
import os
import sys

# The generated HTML is untrusted input in a separate directory; only repo
# code is imported, and -I keeps the fixture directory off sys.path.
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

import playwright_scraper as eng                      # noqa: E402
import page_flow                                     # noqa: E402

LISTING_BASE = "https://www.spinny.com"
DETAIL_PATH = ("/buy-used-cars/faridabad/hyundai/grand-i10/"
               "sportz-12-kappa-vtvt-2019/31483859")

# Real Spinny URL paths -> generated fixture files. The paths match
# product_parser's listing/detail regexes, so classification is the normal
# production path rather than an "unknown" fallback.
ROUTES = {
    "/used-cars-in-delhi-ncr/s": "target_reached.html",
    "/used-cars-in-mumbai/s": "exhausted.html",
    "/used-cars-in-pune/s": "stalled.html",
    "/used-cars-in-kolkata/s": "stalled_no_total.html",
    "/used-cars-in-jaipur/s": "stalled_zero_total.html",
    DETAIL_PATH: "detail.html",
}

failures = []


def check(label, condition):
    print(("  PASS  " if condition else "  FAIL  ") + label)
    if not condition:
        failures.append(label)
    return bool(condition)


def make_route_handler(fixture_dir):
    """Fulfill every browser request from a local fixture, never the wire."""

    def handler(route, request):
        from urllib.parse import urlsplit
        path = urlsplit(request.url).path.rstrip("/") or "/"
        name = ROUTES.get(path)
        if name is None:
            # The page itself requests no external subresources (the asset
            # refs are inert <img> tags whose load we also intercept); a
            # path we did not plan for is a fixture bug, surfaced as 404
            # rather than silently allowed onto the network.
            route.fulfill(status=404, body=b"not part of the local fixture")
            return
        with open(os.path.join(fixture_dir, name), "rb") as fh:
            body = fh.read()
        route.fulfill(status=200, content_type="text/html; charset=utf-8",
                      body=body)

    return handler


def run_scenario(fixture_dir, work_dir, name, url, mode, pages,
                 expect_summary, expect_status, expect_code, expect_reason):
    print("\n== scenario: %s" % name)
    out = os.path.join(work_dir, name)
    # The REAL parser: host checks, mode validation, --pages validation all
    # run, with only the argv tail supplied by the harness.
    argv = ["playwright_scraper.py", "--url", url, "--mode", mode,
            "--pages", str(pages), "--format", "json", "--out", out,
            "--headless"]
    sys.argv = argv
    args = eng.parse_args()
    # The one test-only seam: intercept the browser instead of networking.
    args.route_handler = make_route_handler(fixture_dir)
    code = eng.scrape(args)

    meta_path = out + ".meta.json"
    meta = json.load(open(meta_path, encoding="utf-8")) \
        if os.path.exists(meta_path) else None

    check("the process exit code is %d (got %d)" % (expect_code, code),
          code == expect_code)
    check("a sidecar was written", meta is not None)
    if meta is None:
        return
    check("status is %r (got %r)" % (expect_status, meta.get("status")),
          meta.get("status") == expect_status)
    check("stop_reason is %r (got %r)" % (expect_reason,
                                          meta.get("stop_reason")),
          meta.get("stop_reason") == expect_reason)

    if mode == "detail":
        # Detail has one page and never scrolls. It therefore carries none of
        # the listing-only blocks — no scroll, no completeness, no per-round
        # record — and its single_page_mode status must be untouched.
        check("detail mode carries NO scroll_progress record",
              "scroll_progress" not in meta)
        check("detail mode carries no scroll block", "scroll" not in meta)
        check("detail mode carries no completeness block",
              "completeness" not in meta)
        check("detail mode keeps single_page_mode",
              meta["stop_reason"] == "single_page_mode")
        check("detail mode stays complete / exit 0",
              meta["status"] == "complete" and code == 0)
        return

    check("the legacy scroll block is still present, unchanged in shape",
          isinstance(meta.get("scroll"), dict)
          and {"settled", "reached_target", "rounds", "cards",
               "height", "boundaries"} <= set(meta["scroll"]))
    check("the completeness block is still present",
          isinstance(meta.get("completeness"), dict))
    progress = meta.get("scroll_progress")
    check("scroll_progress sits beside scroll/completeness",
          isinstance(progress, dict)
          and set(progress) == {"rounds", "stop_summary"})
    check("stop_summary is %r (got %r)" % (expect_summary,
                                           progress["stop_summary"]),
          progress["stop_summary"] == expect_summary)
    assert_rounds_internally_consistent(meta)


def assert_rounds_internally_consistent(meta):
    """The history must reconstruct itself: deltas sum to the last total."""
    rounds = meta["scroll_progress"]["rounds"]
    check("the record has one entry per scroll round", len(rounds) >= 2)
    check("round numbers are contiguous from 0",
          [r["round"] for r in rounds] == list(range(len(rounds))))
    check("every entry carries a non-negative card total and increment",
          all(isinstance(r["cards"], int) and isinstance(r["added"], int)
              and r["cards"] >= 0 and r["added"] >= 0 for r in rounds))
    check("the first round counts its initial grid as new",
          rounds[0]["added"] == rounds[0]["cards"] and rounds[0]["cards"] > 0)
    check("each round's added equals its cards minus the previous round's",
          all(rounds[i]["added"] == rounds[i]["cards"] - rounds[i - 1]["cards"]
              for i in range(1, len(rounds))))
    check("the sum of increments reconstructs the final card total",
          sum(r["added"] for r in rounds) == rounds[-1]["cards"])
    check("the last record matches the scroll block's own card count",
          rounds[-1]["cards"] == meta["scroll"]["cards"])


def main(argv):
    fixture_dir, work_dir = argv[1], argv[2]
    os.makedirs(work_dir, exist_ok=True)

    # 1. --pages 3 asks for 60 cars; the page holds 80 and advertises 200.
    #    The target is reached mid-grid: complete, exit 0, and the per-round
    #    history shows the climb.
    run_scenario(fixture_dir, work_dir, "target_reached",
                 LISTING_BASE + "/used-cars-in-delhi-ncr/s/",
                 "listing", 3,
                 page_flow.SCROLL_SUMMARY_TARGET, "complete", 0, "completed")

    # 2. The whole advertised catalogue renders, then the grid settles with
    #    nothing left. Under the new rule this is PARTIAL / exit 6, named
    #    distinctly from a stall.
    run_scenario(fixture_dir, work_dir, "exhausted",
                 LISTING_BASE + "/used-cars-in-mumbai/s/",
                 "listing", 10,
                 page_flow.SCROLL_SUMMARY_EXHAUSTED, "partial", 6,
                 page_flow.STOP_REASON_EXHAUSTED)

    # 3. The lazy loader dies at 62 cars while the heading still promises
    #    200: a stall, partial / exit 6, and the zero-growth tail rounds must
    #    all survive in the history.
    run_scenario(fixture_dir, work_dir, "stalled",
                 LISTING_BASE + "/used-cars-in-pune/s/",
                 "listing", 10,
                 page_flow.SCROLL_SUMMARY_STALLED, "partial", 6,
                 "scroll_stalled")

    # 4. Same stall, but the heading node is absent. No usable total means
    #    exhaustion cannot be established, so it stays a stall.
    run_scenario(fixture_dir, work_dir, "stalled_no_total",
                 LISTING_BASE + "/used-cars-in-kolkata/s/",
                 "listing", 10,
                 page_flow.SCROLL_SUMMARY_STALLED, "partial", 6,
                 "scroll_stalled")

    # 5. Same stall, heading literally reads 0: treated like missing.
    run_scenario(fixture_dir, work_dir, "stalled_zero_total",
                 LISTING_BASE + "/used-cars-in-jaipur/s/",
                 "listing", 10,
                 page_flow.SCROLL_SUMMARY_STALLED, "partial", 6,
                 "scroll_stalled")

    # 6. Detail mode: one page, no scrolling, no per-round record, and
    #    single_page_mode unchanged.
    run_scenario(fixture_dir, work_dir, "detail",
                 LISTING_BASE + DETAIL_PATH + "/",
                 "detail", 1, None, "complete", 0, "single_page_mode")

    print()
    if failures:
        print("%d local scenario check(s) FAILED" % len(failures))
        for item in failures:
            print("  - " + item)
        return 1
    print("local verification: ALL SCENARIOS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
