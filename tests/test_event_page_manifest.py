"""
tests/test_event_page_manifest.py
---------------------------------
Offline tests for the per-page manifest written by ``playwright_scraper.py``
in ``--mode events``.

Nothing here launches a browser or touches polymarket.com: every page result
is a hand-built ``PageOutcome`` (the same dataclass the workers return), and
the worker pool is driven with the browser stubbed out exactly the way
``smoke_test.test_concurrency_machinery`` stubs it. The four results a named
event page can have are all covered — success, failed, no_rows and
unattempted — as is the mapping from a walk's outcomes to ``stop_reason`` and
the process exit code.

Both fetch paths are exercised against the SAME specs and outcomes so their
manifests are asserted byte-for-byte identical: ``--concurrency 1`` must emit
the same structure as the worker pool, which is what makes two runs over the
same input comparable.
"""
import json
import threading
import types

import pytest

pytest.importorskip("playwright")

import playwright_scraper as eng  # noqa: E402
from output_writer import (  # noqa: E402
    EXIT_BLOCKED,
    EXIT_FETCH_FAILED,
    EXIT_NO_PRODUCTS,
    EXIT_PARTIAL,
    finish_run,
)
import page_flow  # noqa: E402

URL = "https://polymarket.com/event/test-event-{:02d}"


def _outcome(page_num, *, rows=3, load_failed=False, blocked_by=None,
             browser_failure=None, proxy_error=None, state="content"):
    """Build a PageOutcome the way _fetch_one_page would for one result kind."""
    from output_writer import Market
    outcome = eng.PageOutcome(page_num=page_num, url=URL.format(page_num))
    outcome.state = state
    outcome.load_failed = load_failed
    outcome.blocked_by = blocked_by
    outcome.browser_failure = browser_failure
    outcome.proxy_error = proxy_error
    if rows:
        outcome.products = [
            Market(sku="{:012x}".format(page_num * 1000 + i),
                   url=outcome.url, title="t{}".format(i))
            for i in range(rows)
        ]
    return outcome


def _specs(pages):
    """The [(page_num, url), ...] plan a --mode events walk builds."""
    return [(n, URL.format(n)) for n in pages]


# ---------------------------------------------------------------------------
# page_manifest_result / page_manifest_reason — the four result kinds
# ---------------------------------------------------------------------------
def test_result_classification_covers_all_four_kinds():
    success = _outcome(2, rows=2)
    no_rows = _outcome(3, rows=0)
    failed = _outcome(4, load_failed=True)
    # An outcome object only ever represents a FETCHED page; unattempted is a
    # property of the plan, so build the record through the manifest to assert
    # its spelling there rather than pretending an outcome carries it.
    records = eng.build_event_page_manifest(
        _specs([2, 3, 4, 5]),
        [success, no_rows, failed],
        unattempted=[(5, URL.format(5), eng.REASON_WORKER_DIED)])

    by_page = {r["page"]: r for r in records}
    assert by_page[2]["result"] == eng.PAGE_RESULT_SUCCESS
    assert by_page[3]["result"] == eng.PAGE_RESULT_NO_ROWS
    assert by_page[4]["result"] == eng.PAGE_RESULT_FAILED
    assert by_page[5]["result"] == eng.PAGE_RESULT_UNATTEMPTED


def test_failure_reasons_are_distinguished():
    # timeout (load failed, no browser/proxy marker)
    timeout = _outcome(2, load_failed=True)
    assert eng.page_manifest_reason(timeout) == "page_load_timeout"

    # dead proxy
    proxy = _outcome(3, load_failed=True,
                     proxy_error="ERR_PROXY_CONNECTION_FAILED")
    assert eng.page_manifest_reason(proxy) == "proxy_unavailable"

    # crashed browser
    crashed = _outcome(4, load_failed=True,
                       browser_failure="the page crashed")
    assert eng.page_manifest_reason(crashed) == "browser_failed"

    # intercepted / blocked by the edge
    blocked = _outcome(5, blocked_by="cloudflare")
    assert eng.page_manifest_reason(blocked) == "blocked_cloudflare"

    # a successful or empty page carries no failure reason
    assert eng.page_manifest_reason(_outcome(6, rows=1)) is None
    assert eng.page_manifest_reason(_outcome(7, rows=0)) is None


def test_failure_reason_matches_failure_stop_reason_vocabulary():
    # The manifest reason and the sidecar's stop_reason must name the same
    # failure, so a reader joining the two never has to translate.
    crashed = _outcome(2, load_failed=True,
                       browser_failure="the browser connection closed")
    assert eng.page_manifest_reason(crashed) == \
        page_flow.failure_stop_reason(crashed)

    timeout = _outcome(3, load_failed=True)
    assert eng.page_manifest_reason(timeout) == \
        page_flow.failure_stop_reason(timeout)

    blocked = _outcome(4, blocked_by="not-served")
    assert eng.page_manifest_reason(blocked) == \
        page_flow.failure_stop_reason(blocked)


# ---------------------------------------------------------------------------
# build_event_page_manifest — coverage, ordering, stability
# ---------------------------------------------------------------------------
def test_every_named_page_gets_exactly_one_record():
    pages = list(range(2, 12))
    records = eng.build_event_page_manifest(
        _specs(pages),
        [_outcome(n, rows=1) for n in pages])
    assert sorted(r["page"] for r in records) == pages
    assert len(records) == len(pages)
    # Record shape and field order are part of the contract.
    assert list(records[0].keys()) == ["page", "url", "result", "reason"]


def test_unattempted_pages_never_mix_into_failed():
    records = eng.build_event_page_manifest(
        _specs([2, 3, 4, 5]),
        [_outcome(2, rows=1), _outcome(4, load_failed=True)],
        unattempted=[
            (3, URL.format(3), eng.REASON_WORKER_DIED),
            (5, URL.format(5), eng.REASON_WORKER_DIED),
        ])
    by_page = {r["page"]: r for r in records}
    assert by_page[4]["result"] == eng.PAGE_RESULT_FAILED
    assert by_page[3]["result"] == eng.PAGE_RESULT_UNATTEMPTED
    assert by_page[5]["result"] == eng.PAGE_RESULT_UNATTEMPTED
    assert by_page[3]["reason"] == "worker_died"

    summary = eng.summarize_page_manifest(records)
    assert summary["failed"] == 1
    assert summary["unattempted"] == 2
    assert summary["succeeded"] == 1
    # The two losses stay in separate buckets and separate page lists.
    assert summary["pages_unattempted"] == [3, 5]
    failed_nums = [r["page"] for r in records
                   if r["result"] == eng.PAGE_RESULT_FAILED]
    assert failed_nums == [4]
    assert set(summary["pages_unattempted"]).isdisjoint(failed_nums)


def test_manifest_is_sorted_by_page_regardless_of_arrival_order():
    pages = list(range(2, 9))
    # Hand the outcomes back in shuffled arrival order, as real workers do.
    outcomes = [_outcome(n, rows=1) for n in reversed(pages)]
    first = eng.build_event_page_manifest(_specs(pages), outcomes)
    second = eng.build_event_page_manifest(
        _specs(pages), list(reversed(outcomes)))
    assert [r["page"] for r in first] == pages
    assert first == second  # stable across arrival order and across runs


def test_summary_counts_and_no_rows_is_complete():
    records = eng.build_event_page_manifest(
        _specs([2, 3, 4]),
        [_outcome(2, rows=2), _outcome(3, rows=0),
         _outcome(4, load_failed=True)])
    summary = eng.summarize_page_manifest(records)
    assert summary == {
        "total": 3,
        "succeeded": 1,
        "without_rows": 1,
        "failed": 1,
        "unattempted": 0,
        "pages_unattempted": [],
    }


def test_empty_plan_yields_empty_but_well_formed_manifest():
    records = eng.build_event_page_manifest([], [])
    assert records == []
    assert eng.summarize_page_manifest(records) == {
        "total": 0, "succeeded": 0, "without_rows": 0, "failed": 0,
        "unattempted": 0, "pages_unattempted": []}


def test_unattempted_without_url_still_resolves_its_named_url():
    # The concurrent path supplies (num, url, reason); a reason-less triple or
    # a plan-only page must still pick up the URL from the plan and a reason.
    records = eng.build_event_page_manifest(
        _specs([2, 3]),
        [_outcome(2, rows=1)],
        unattempted=[(3, URL.format(3), eng.REASON_PRECEDING_FAILED)])
    assert records[1] == {
        "page": 3, "url": URL.format(3),
        "result": eng.PAGE_RESULT_UNATTEMPTED,
        "reason": eng.REASON_PRECEDING_FAILED}


# ---------------------------------------------------------------------------
# event_walk_stop_reason — stop_reason alignment
# ---------------------------------------------------------------------------
def test_stop_reason_all_success_is_completed_even_with_no_rows_pages():
    # All named pages fetched; one happened to have no markets. Still complete.
    outcomes = [_outcome(2, rows=1), _outcome(3, rows=0), _outcome(4, rows=2)]
    assert eng.event_walk_stop_reason(outcomes, [], "completed") == "completed"


def test_stop_reason_failed_page_wins_over_unattempted():
    failed = _outcome(3, load_failed=True)
    reason = eng.event_walk_stop_reason(
        [_outcome(2, rows=1), failed], [4, 5], "completed")
    assert reason == page_flow.failure_stop_reason(failed)
    assert reason != "pages_unattempted"
    assert reason not in ("completed",)


def test_stop_reason_unattempted_only_is_pages_unattempted():
    reason = eng.event_walk_stop_reason([_outcome(2, rows=1)], [3, 4])
    assert reason == "pages_unattempted"


def test_stop_reason_blocked_uses_blocked_vocabulary():
    blocked = _outcome(2, blocked_by="cloudflare")
    reason = eng.event_walk_stop_reason([blocked], [3])
    assert reason == "blocked_cloudflare"


# ---------------------------------------------------------------------------
# finish_run — exit code / status mapping over manifest-shaped outcomes
# ---------------------------------------------------------------------------
def _finish(rows, stop_reason, failed_nums, tmp_path, *, allow_empty=False,
            blocked=False):
    return finish_run(
        rows, str(tmp_path / "out"), "json", allow_empty,
        blocked=blocked, stop_reason=stop_reason,
        pages_requested=1 + len(rows) + len(failed_nums),
        pages_completed=1 + len(rows), pages_failed=failed_nums,
        mode="events", start_url=URL.format(0), final_url=URL.format(0))


def test_exit_code_zero_when_all_pages_completed_even_with_no_rows(tmp_path):
    from output_writer import Market
    rows = [Market(sku="abc", url=URL.format(2), title="t")]
    # One no_rows page is NOT a failure: pages_failed stays empty and the
    # stop reason remains a complete one -> exit 0, status complete.
    rc = _finish(rows, "completed", [], tmp_path)
    assert rc == 0
    meta = json.loads((tmp_path / "out.meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == "complete"
    assert meta["pages_failed"] == []


def test_exit_code_partial_when_a_page_failed_but_rows_gathered(tmp_path):
    from output_writer import Market
    rows = [Market(sku="abc", url=URL.format(2), title="t")]
    rc = _finish(rows, "page_load_timeout", [4], tmp_path)
    assert rc == EXIT_PARTIAL
    meta = json.loads((tmp_path / "out.meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == "partial"
    assert meta["pages_failed"] == [4]


def test_exit_code_fetch_failed_when_nothing_gathered_and_not_blocked(
        tmp_path):
    rc = _finish([], "page_load_timeout", [2], tmp_path)
    assert rc == EXIT_FETCH_FAILED


def test_exit_code_blocked_when_nothing_gathered_and_blocked(tmp_path):
    rc = _finish([], "blocked_cloudflare", [2], tmp_path, blocked=True)
    assert rc == EXIT_BLOCKED


def test_exit_code_no_products_when_completed_but_empty(tmp_path):
    # A genuinely empty-but-completed run (e.g. no event pages named) is 4.
    rc = _finish([], "completed", [], tmp_path)
    assert rc == EXIT_NO_PRODUCTS


# ---------------------------------------------------------------------------
# The real dispatcher, browser stubbed — both paths, identical manifest
# ---------------------------------------------------------------------------
class _NoPlaywright:
    """A stand-in for the sync_playwright() context manager (real class:
    Python resolves __enter__ on the type, not an instance attribute)."""

    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


def _drive_dispatcher(behaviour, pages, concurrency):
    """Run the real _fetch_pages_concurrently with no browser in it."""
    fake_session = types.SimpleNamespace(
        pool=None, close=lambda: None, open=lambda self=None: fake_session)

    def fake_fetch(session, args, pool, page_num, url):
        return behaviour(page_num, url)

    real_session, real_fetch, real_pw = (
        eng._BrowserSession, eng._fetch_one_page, eng.sync_playwright)
    eng._BrowserSession = lambda *a, **k: fake_session
    eng._fetch_one_page = fake_fetch
    eng.sync_playwright = _NoPlaywright
    args = types.SimpleNamespace(delay=0, out="unused")
    try:
        return eng._fetch_pages_concurrently(
            args, None, _specs(pages), concurrency)
    finally:
        eng._BrowserSession, eng._fetch_one_page, eng.sync_playwright = (
            real_session, real_fetch, real_pw)


def test_concurrent_worker_death_marks_its_pages_unattempted_with_reason():
    def behaviour(page_num, url):
        if page_num == 4:
            raise RuntimeError("simulated worker death")
        return _outcome(page_num, rows=1)

    pages = list(range(2, 8))
    results, unattempted, _exhausted = _drive_dispatcher(
        behaviour, pages, concurrency=2)

    # The dead worker's own page (and any still queued) never became outcomes.
    attempted = {o.page_num for o in results}
    assert 4 not in attempted
    # Every unattempted entry carries a reason naming the dead worker.
    assert all(reason == eng.REASON_WORKER_DIED
               for _n, _u, reason in unattempted)
    unattempted_nums = [n for n, _u, _r in unattempted]
    assert 4 in unattempted_nums
    assert set(unattempted_nums).isdisjoint(attempted)

    # The manifest then splits failed (none here — the fetch never ran) from
    # unattempted, and nothing is silently dropped.
    records = eng.build_event_page_manifest(
        _specs(pages), results, unattempted)
    assert len(records) == len(pages)
    summary = eng.summarize_page_manifest(records)
    assert summary["failed"] == 0
    assert summary["unattempted"] == len(unattempted_nums)
    assert summary["succeeded"] == len(attempted)
    assert summary["pages_unattempted"] == sorted(unattempted_nums)


def test_concurrent_failed_page_is_failed_not_unattempted():
    def behaviour(page_num, url):
        if page_num == 5:
            return _outcome(page_num, load_failed=True)
        return _outcome(page_num, rows=1)

    pages = list(range(2, 9))
    results, unattempted, _ = _drive_dispatcher(behaviour, pages, concurrency=3)
    assert unattempted == []  # a failed fetch still consumed the queue item
    records = eng.build_event_page_manifest(_specs(pages), results, unattempted)
    by_page = {r["page"]: r for r in records}
    assert by_page[5]["result"] == eng.PAGE_RESULT_FAILED
    assert by_page[5]["reason"] == "page_load_timeout"
    assert eng.summarize_page_manifest(records)["unattempted"] == 0


def test_concurrent_and_sequential_manifests_match_for_the_same_inputs():
    # The same plan, the same per-page outcomes: the worker pool and the
    # sequential walk must produce structurally identical manifests.
    pages = list(range(2, 10))

    def behaviour(page_num, url):
        if page_num == 4:
            return _outcome(page_num, rows=0)          # no_rows
        if page_num == 7:
            return _outcome(page_num, load_failed=True,
                            proxy_error="ERR_TUNNEL_CONNECTION_FAILED")
        return _outcome(page_num, rows=2)

    # Concurrent: the failure does not stop the other workers.
    results_c, unattempted_c, _ = _drive_dispatcher(
        behaviour, pages, concurrency=3)
    concurrent = eng.build_event_page_manifest(
        _specs(pages), results_c, unattempted_c)

    # Sequential: the walk halts at page 7; pages 8-9 are then unattempted.
    results_s, unattempted_s = [], []
    for num, url in _specs(pages):
        if num > 7:  # pages after the failure were never reached
            unattempted_s.append((num, url, eng.REASON_PRECEDING_FAILED))
            continue
        results_s.append(behaviour(num, url))
    sequential = eng.build_event_page_manifest(
        _specs(pages), results_s, unattempted_s)

    # Shared pages agree exactly on result and reason.
    common = {2, 3, 4, 5, 6, 7}
    seq_by_page = {r["page"]: r for r in sequential}
    for record in concurrent:
        if record["page"] in common:
            assert record == seq_by_page[record["page"]]
    # Both manifests are sorted and cover every named page.
    assert [r["page"] for r in concurrent] == pages
    assert [r["page"] for r in sequential] == pages
    # And the difference is ONLY the pages the sequential halt left behind.
    assert [r["page"] for r in sequential
            if r["result"] == eng.PAGE_RESULT_UNATTEMPTED] == [8, 9]
    assert all(r["reason"] == eng.REASON_PRECEDING_FAILED
               for r in sequential
               if r["result"] == eng.PAGE_RESULT_UNATTEMPTED)


def test_sequential_page_cap_records_remaining_pages_as_unattempted():
    pages = list(range(2, 8))
    # Simulate the cap stopping the walk after page 4: 5-7 never attempted.
    results_s = [_outcome(n, rows=1) for n in (2, 3, 4)]
    unattempted_s = [(n, URL.format(n), eng.REASON_PAGE_CAP)
                     for n in (5, 6, 7)]
    records = eng.build_event_page_manifest(
        _specs(pages), results_s, unattempted_s)
    by_page = {r["page"]: r for r in records}
    for n in (5, 6, 7):
        assert by_page[n]["result"] == eng.PAGE_RESULT_UNATTEMPTED
        assert by_page[n]["reason"] == "page_cap"
    assert eng.summarize_page_manifest(records)["failed"] == 0


def test_stop_reason_and_exit_code_for_worker_death_with_rows(tmp_path):
    # End-to-end shape of the original bug: a worker dies, rows from the
    # surviving pages exist, and pages remain unattempted. It must NOT report
    # complete and must not call the unattempted pages failed.
    from output_writer import Market
    outcomes = [_outcome(2, rows=1), _outcome(3, rows=1)]
    unattempted = [(4, URL.format(4), eng.REASON_WORKER_DIED)]
    reason = eng.event_walk_stop_reason(
        outcomes, [n for n, _u, _r in unattempted])
    assert reason == "pages_unattempted"

    rows = [Market(sku="a", url=URL.format(2), title="t")]
    rc = finish_run(
        rows, str(tmp_path / "out"), "json", False,
        blocked=False, stop_reason=reason, pages_requested=4,
        pages_completed=3, pages_failed=[],  # unattempted must stay out
        mode="events", start_url=URL.format(0), final_url=URL.format(0))
    assert rc == EXIT_PARTIAL
    meta = json.loads((tmp_path / "out.meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == "partial"
    assert meta["pages_failed"] == []
    assert meta["stop_reason"] == "pages_unattempted"


def test_threads_actually_run_under_the_stub():
    # Guard against a stub that silently runs zero workers (the dunder-method
    # trap noted in smoke_test): a real death must be observable.
    ran = threading.Event()

    def behaviour(page_num, url):
        ran.set()
        return _outcome(page_num, rows=1)

    _drive_dispatcher(behaviour, [2, 3], concurrency=2)
    assert ran.is_set()


# ---------------------------------------------------------------------------
# Full scrape() integration — the manifest lands in the real .meta.json
# ---------------------------------------------------------------------------
def _scrape_args(tmp_path, concurrency):
    """The subset of the argparse namespace scrape() reads, with a listing URL
    and an output prefix inside the test's temp directory."""
    return types.SimpleNamespace(
        url="https://polymarket.com/predictions/politics",
        mode="events", pages=4, concurrency=concurrency, delay=0,
        retries=1, retry_delay=0, proxy_block_retries=0, out=str(tmp_path / "run"),
        format="json", allow_empty=False, headless=True, locale="en-US",
        browser_channel=None, fingerprint=False, twocaptcha_key=None,
        fp_tags="Windows", fp_country=None, captcha_api="v2",
        solve_captcha="when-blocked", min_score=0.7, cdp_endpoint=None,
        cdp_connect_timeout=150, proxy=None, proxy_file=None,
        proxy_rotate="per-run", proxy_shuffle=False, dump_html=None,
        category=None)


class _FakePlaywright:
    """sync_playwright() stand-in: both the main session and each worker ask
    for one of these, so it only has to be a no-op context manager."""

    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


def _listing_outcome(engine, event_slugs):
    """A page-1 listing outcome whose rows each name one event page, so the
    real event_urls_from() planner builds a plan from them."""
    from output_writer import Market
    outcome = engine.PageOutcome(
        page_num=1, url="https://polymarket.com/predictions/politics")
    outcome.state = "content"
    outcome.final_url = outcome.url
    outcome.products = [
        Market(sku="listing-{}".format(slug),
               url="https://polymarket.com/event/{}".format(slug),
               event_slug=slug,
               event_url="https://polymarket.com/event/{}".format(slug),
               title="listing row {}".format(slug))
        for slug in event_slugs]
    return outcome


def _run_scrape(engine, monkeypatch, tmp_path, concurrency, page1, behaviour):
    """Drive the real scrape() with every browser entry point stubbed."""
    fake_session = types.SimpleNamespace(
        pool=None, page=types.SimpleNamespace(url=page1.url),
        close=lambda: None, browser_failure=None)
    # open() must return the session itself: scrape() does `session = ...open()`.
    fake_session.open = lambda: fake_session

    def fake_session_factory(*a, **k):
        return fake_session

    def fake_fetch(session, args, pool, page_num, url):
        if page_num == 1:
            return page1
        return behaviour(page_num, url)

    monkeypatch.setattr(engine, "sync_playwright", lambda: _FakePlaywright())
    monkeypatch.setattr(engine, "_BrowserSession", fake_session_factory)
    monkeypatch.setattr(engine, "_fetch_one_page", fake_fetch)
    monkeypatch.setattr(engine, "proxy_pool_from_args", lambda args: None)

    args = _scrape_args(tmp_path, concurrency)
    return engine.scrape(args)


def test_scrape_writes_manifest_for_sequential_path(monkeypatch, tmp_path):
    slugs = ["ev-a", "ev-b", "ev-c"]
    page1 = _listing_outcome(eng, slugs)

    def behaviour(page_num, url):
        if page_num == 3:
            return _outcome(page_num, rows=0)          # no_rows
        return _outcome(page_num, rows=2)

    rc = _run_scrape(eng, monkeypatch, tmp_path, 1, page1, behaviour)
    assert rc == 0  # all pages fetched; a no_rows page is still complete
    meta = json.loads((tmp_path / "run.meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == "complete"
    assert meta["stop_reason"] == "completed"
    assert meta["pages_failed"] == []

    manifest = meta["event_page_results"]
    assert [r["page"] for r in manifest] == [2, 3, 4]
    assert [r["result"] for r in manifest] == [
        eng.PAGE_RESULT_SUCCESS, eng.PAGE_RESULT_NO_ROWS,
        eng.PAGE_RESULT_SUCCESS]
    assert all(r["reason"] is None for r in manifest)
    assert meta["event_page_summary"]["without_rows"] == 1
    assert meta["pages_unattempted"] == []


def test_scrape_concurrent_worker_death_is_partial_with_manifest(
        monkeypatch, tmp_path):
    slugs = ["ev-a", "ev-b", "ev-c"]
    page1 = _listing_outcome(eng, slugs)

    def behaviour(page_num, url):
        if page_num == 3:
            raise RuntimeError("simulated worker death")
        return _outcome(page_num, rows=2)

    rc = _run_scrape(eng, monkeypatch, tmp_path, 3, page1, behaviour)
    # Rows were gathered (page 1 + surviving event pages), so this is the
    # partial code, never a silent complete.
    assert rc == EXIT_PARTIAL
    meta = json.loads((tmp_path / "run.meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == "partial"
    assert meta["stop_reason"] == "pages_unattempted"

    manifest = meta["event_page_results"]
    by_page = {r["page"]: r for r in manifest}
    # The dead worker's page is unattempted/worker_died, NOT failed.
    assert by_page[3]["result"] == eng.PAGE_RESULT_UNATTEMPTED
    assert by_page[3]["reason"] == eng.REASON_WORKER_DIED
    # And it is absent from pages_failed.
    assert 3 not in meta["pages_failed"]
    assert meta["pages_unattempted"] == [3]
    assert meta["event_page_summary"]["unattempted"] == 1
    assert meta["event_page_summary"]["failed"] == 0
    # Every named event page still has exactly one record.
    assert sorted(by_page) == [2, 3, 4]


def test_scrape_failed_event_page_is_failed_not_unattempted(
        monkeypatch, tmp_path):
    slugs = ["ev-a", "ev-b"]
    page1 = _listing_outcome(eng, slugs)

    def behaviour(page_num, url):
        if page_num == 3:
            return _outcome(page_num, load_failed=True,
                            proxy_error="ERR_PROXY_CONNECTION_FAILED")
        return _outcome(page_num, rows=2)

    # Sequential: the walk halts at the failed page 3, so page 4 is unattempted.
    rc = _run_scrape(eng, monkeypatch, tmp_path, 1, page1, behaviour)
    assert rc == EXIT_PARTIAL
    meta = json.loads((tmp_path / "run.meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == "partial"
    assert meta["pages_failed"] == [3]           # the failed fetch only
    assert meta["pages_unattempted"] == []        # plan ended at the failure

    manifest = {r["page"]: r for r in meta["event_page_results"]}
    assert manifest[3]["result"] == eng.PAGE_RESULT_FAILED
    assert manifest[3]["reason"] == "proxy_unavailable"


def test_scrape_manifest_identical_shape_both_concurrency_settings(
        monkeypatch, tmp_path):
    slugs = ["ev-a", "ev-b", "ev-c"]

    def make_page1():
        return _listing_outcome(eng, slugs)

    def behaviour(page_num, url):
        return _outcome(page_num, rows=1 if page_num != 4 else 0)

    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    rc1 = _run_scrape(eng, monkeypatch, tmp_path / "a", 1,
                      make_page1(), behaviour)
    rc2 = _run_scrape(eng, monkeypatch, tmp_path / "b", 3,
                      make_page1(), behaviour)
    assert (rc1, rc2) == (0, 0)
    m1 = json.loads((tmp_path / "a" / "run.meta.json").read_text("utf-8"))
    m2 = json.loads((tmp_path / "b" / "run.meta.json").read_text("utf-8"))
    # Same records, same ordering, same result vocabulary in both paths.
    assert m1["event_page_results"] == m2["event_page_results"]
    assert m1["event_page_summary"] == m2["event_page_summary"]
    assert [r["page"] for r in m1["event_page_results"]] == [2, 3, 4]
