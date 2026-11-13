"""
tests/test_page_outcomes.py
---------------------------
Offline coverage for the Playwright engine's per-page verdicts.

Nothing here opens a browser or touches the network: every case builds
``PageOutcome`` objects by hand and drives the same pure merge/summary logic
the engine feeds its run-metadata sidecar (``build_page_outcome_records`` /
``classify_undispatched_pages``), then checks the resulting records — and, in
one case, the actual ``<out>.meta.json`` / ``<out>.last_attempt.json`` files
written through ``output_writer.finish_run``.

The engine driver (playwright) is optional in CI — the plain ``pytest`` job
installs no engine library — so importing the module skips the whole module
with an explicit reason, exactly the convention smoke_test.py uses.
"""

import json
import os

import pytest

from output_writer import Product, finish_run

try:
    import playwright_scraper as ps
except ImportError as exc:  # pragma: no cover - exercised only when the driver is absent
    pytest.skip(f"playwright not importable in this environment: {exc}",
                allow_module_level=True)


# Status constants under test, imported from the engine so a rename fails the
# suite rather than the tests silently asserting on stale strings.
S = {
    "success": ps.PAGE_SUCCESS,
    "blocked": ps.PAGE_BLOCKED,
    "load_failed": ps.PAGE_LOAD_FAILED,
    "needs_signin": ps.PAGE_NEEDS_SIGNIN,
    "not_found": ps.PAGE_NOT_FOUND,
    "not_dispatched": ps.PAGE_NOT_DISPATCHED,
    "not_attempted": ps.PAGE_NOT_ATTEMPTED,
}

PROXY_A = "http://user:pass@exit-a.example:8000"
PROXY_A_MASKED = "http://***:***@exit-a.example:8000"
PROXY_B = "http://user:pass@exit-b.example:8001"


def _ok_page(page_num, rows, proxy_exit=ps.NO_PROXY_EXIT, url=None):
    """A fetched page that parsed `rows` products."""
    products = [Product(sku=f"ASIN-{page_num}-{i}") for i in range(rows)]
    return ps.PageOutcome(
        page_num=page_num, url=url or f"https://www.amazon.com/s?k=x&page={page_num}",
        final_url=url or f"https://www.amazon.com/s?k=x&page={page_num}",
        products=products, proxy_exit=proxy_exit)


def _by_page(records):
    return {r["page"]: r for r in records}


def test_all_pages_successful_one_record_each(tmp_path):
    """Normal run: every requested page fetched, verdict success, row counts
    and the no-proxy exit carried through, and the same list lands in BOTH
    sidecars via finish_run without changing the run-level semantics."""
    out = os.path.join(tmp_path, "ok_run")
    fetched = [_ok_page(1, 10), _ok_page(2, 8), _ok_page(3, 6)]
    rows = [p for o in fetched for p in o.products]

    records = ps.build_page_outcome_records(fetched, pages_requested=3)
    assert len(records) == 3
    by_page = _by_page(records)
    for page_num, expected_rows in ((1, 10), (2, 8), (3, 6)):
        rec = by_page[page_num]
        assert rec["status"] == S["success"]
        assert rec["rows_parsed"] == expected_rows
        assert rec["proxy_exit"] == ps.NO_PROXY_EXIT
        assert rec["blocked_by"] is None
        assert set(rec) >= {"page", "status", "rows_parsed", "proxy_exit"}
    assert [r["page"] for r in records] == [1, 2, 3]

    # Through the real sidecar writer: page_outcomes rides `extra` into the
    # identical metadata dict used for both files.
    rc = finish_run(
        rows, out, "json", allow_empty=False, blocked=False,
        stop_reason="completed", pages_requested=3, pages_completed=3,
        pages_failed=[], mode="listing", start_url=fetched[0].url,
        final_url=fetched[-1].final_url, extra={"page_outcomes": records})
    assert rc == 0

    meta = json.loads(open(f"{out}.meta.json", encoding="utf-8").read())
    last = json.loads(open(f"{out}.last_attempt.json", encoding="utf-8").read())
    # Existing run-level contract is untouched...
    assert meta["status"] == "complete"
    assert meta["pages_completed"] == 3
    assert meta["pages_failed"] == []
    # ...and the per-page conclusions supplement it in both files.
    for sidecar in (meta, last):
        assert sidecar["page_outcomes"] == records
        assert [r["page"] for r in sidecar["page_outcomes"]] == [1, 2, 3]


def test_blocked_page_marks_every_later_page_not_attempted(tmp_path):
    """Sequential path: page 2 is blocked, the loop breaks, and pages 3-5
    still appear in the conclusions as `not_attempted` — never as failures,
    never missing. The failed page itself stays in pages_failed."""
    out = os.path.join(tmp_path, "blocked_run")
    first = _ok_page(1, 10)
    blocked = ps.PageOutcome(
        page_num=2, url="https://www.amazon.com/s?k=x&page=2",
        blocked_by="amazon-captcha", proxy_exit=PROXY_A_MASKED)
    fetched = [first, blocked]

    # Mirrors the sequential branch's trailing-page bookkeeping: the break
    # happened after page 2, so 3..5 were never tried.
    not_attempted = list(range(3, 6))
    records = ps.build_page_outcome_records(
        fetched, pages_requested=5, not_attempted=not_attempted)
    by_page = _by_page(records)

    assert [r["page"] for r in records] == [1, 2, 3, 4, 5]
    assert by_page[1]["status"] == S["success"]
    assert by_page[2]["status"] == S["blocked"]
    assert by_page[2]["blocked_by"] == "amazon-captcha"
    assert by_page[2]["rows_parsed"] == 0
    for page_num in (3, 4, 5):
        rec = by_page[page_num]
        assert rec["status"] == S["not_attempted"]
        assert rec["rows_parsed"] == 0
        # A page never fetched produced no traffic — the absence of an exit is
        # stated explicitly rather than left blank.
        assert rec["proxy_exit"] == ps.NO_PROXY_EXIT

    # A load failure and the other non-ok verdicts map to their own statuses.
    load_failed = ps.PageOutcome(
        page_num=2, url="u", load_failed=True, proxy_exit=PROXY_A_MASKED)
    signin = ps.PageOutcome(page_num=3, url="u", needs_signin=True)
    missing = ps.PageOutcome(page_num=4, url="u", not_found=True)
    assert load_failed.page_status == S["load_failed"]
    assert signin.page_status == S["needs_signin"]
    assert missing.page_status == S["not_found"]
    # Placeholder constructors pin their verdict and parse zero rows.
    assert ps.PageOutcome.not_dispatched(9).page_status == S["not_dispatched"]
    assert ps.PageOutcome.not_attempted(9).page_status == S["not_attempted"]
    assert ps.PageOutcome.not_dispatched(9).rows_parsed == 0

    # And through finish_run: pages_failed keeps ONLY the fetched failure;
    # exit code is the partial-run code because page 1 gathered rows.
    rc = finish_run(
        first.products, out, "json", allow_empty=False, blocked=True,
        stop_reason="blocked_amazon-captcha", pages_requested=5,
        pages_completed=1, pages_failed=[2], mode="listing",
        start_url=first.url, final_url=first.final_url,
        extra={"page_outcomes": records})
    from output_writer import EXIT_PARTIAL
    assert rc == EXIT_PARTIAL
    last = json.loads(open(f"{out}.last_attempt.json", encoding="utf-8").read())
    assert last["pages_failed"] == [2]
    statuses = {r["page"]: r["status"] for r in last["page_outcomes"]}
    assert statuses == {1: S["success"], 2: S["blocked"],
                        3: S["not_attempted"], 4: S["not_attempted"],
                        5: S["not_attempted"]}


def test_listing_exhaustion_marks_queued_pages_not_dispatched():
    """Concurrent path: page 3 returns zero rows, the end-of-listing stop
    trips, and the pages still queued are `not_dispatched` — NOT failed
    pages. A page a dead worker had already pulled is `not_attempted`."""
    specs = [(n, f"https://www.amazon.com/s?k=x&page={n}") for n in range(2, 7)]

    # Workers fetched pages 2 (rows) and 3 (the empty page that tripped the
    # stop). Page 4 had been pulled by a worker that then died; pages 5-6
    # were still sitting in the queue.
    fetched_page_nums = [2, 3]
    dispatched_page_nums = [2, 3, 4]
    not_dispatched, not_attempted = ps.classify_undispatched_pages(
        specs, fetched_page_nums, dispatched_page_nums, exhausted=True)

    assert not_dispatched == [5, 6]
    assert not_attempted == [4]
    # The two buckets are disjoint and, with the fetched pages, cover the
    # whole spec exactly once.
    assert not set(not_dispatched) & set(not_attempted)
    assert (set(not_dispatched) | set(not_attempted)
            | set(fetched_page_nums)) == {2, 3, 4, 5, 6}

    page3 = _ok_page(3, 0)  # fetched and parsed — zero rows is still success
    assert page3.page_status == S["success"]
    page2 = _ok_page(2, 11, proxy_exit=PROXY_A_MASKED)
    records = ps.build_page_outcome_records(
        [page2, page3], pages_requested=6,
        not_dispatched=not_dispatched, not_attempted=not_attempted,
        url_for_page={n: f"https://www.amazon.com/s?k=x&page={n}"
                      for n in range(1, 7)})
    by_page = _by_page(records)
    assert by_page[3]["status"] == S["success"]
    assert by_page[3]["rows_parsed"] == 0
    assert by_page[4]["status"] == S["not_attempted"]
    for page_num in (5, 6):
        rec = by_page[page_num]
        assert rec["status"] == S["not_dispatched"]
        # The URL the page WOULD have used is retained so the record is
        # checkable against the requested pagination.
        assert rec["url"] == f"https://www.amazon.com/s?k=x&page={page_num}"


def test_worker_death_without_exhaustion_marks_everything_else_not_attempted():
    """When no zero-row page tripped the stop, every unfetched spec — queued
    or already pulled by the dead worker — is `not_attempted`, and nothing is
    labelled `not_dispatched`."""
    specs = [(n, f"u{n}") for n in range(2, 6)]
    not_dispatched, not_attempted = ps.classify_undispatched_pages(
        specs, fetched_page_nums=[2], dispatched_page_nums=[2, 3],
        exhausted=False)
    assert not_dispatched == []
    assert not_attempted == [3, 4, 5]

    # Exhaustion flag set but every remaining page was already in flight:
    # none qualifies as never-dispatched.
    not_dispatched2, not_attempted2 = ps.classify_undispatched_pages(
        specs, fetched_page_nums=[2, 3], dispatched_page_nums=[2, 3, 4, 5],
        exhausted=True)
    assert not_dispatched2 == []
    assert not_attempted2 == [4, 5]


def test_proxy_exit_field_with_and_without_a_pool():
    """The proxy exit is the masked exit actually used; with no pool it is the
    explicit `none` marker on every kind of record."""
    via_proxy = _ok_page(2, 4, proxy_exit=PROXY_A_MASKED)
    assert via_proxy.to_record()["proxy_exit"] == PROXY_A_MASKED

    no_pool = _ok_page(1, 4)  # default constructor => no proxy
    assert no_pool.to_record()["proxy_exit"] == ps.NO_PROXY_EXIT

    blocked_no_pool = ps.PageOutcome(page_num=3, url="u", blocked_by="aws-waf")
    assert blocked_no_pool.proxy_exit == ps.NO_PROXY_EXIT
    assert blocked_no_pool.to_record()["proxy_exit"] == ps.NO_PROXY_EXIT

    # Placeholders never sent traffic, from a proxied run or otherwise.
    assert ps.PageOutcome.not_dispatched(5).proxy_exit == ps.NO_PROXY_EXIT
    assert ps.PageOutcome.not_attempted(6).proxy_exit == ps.NO_PROXY_EXIT

    # The masked form is what mask() produces for the real proxy URL, so the
    # engine can hand pool.current straight to the record without leaking
    # credentials.
    from proxy_pool import mask
    assert mask(PROXY_A) == PROXY_A_MASKED
    assert mask(PROXY_B) != PROXY_A_MASKED
