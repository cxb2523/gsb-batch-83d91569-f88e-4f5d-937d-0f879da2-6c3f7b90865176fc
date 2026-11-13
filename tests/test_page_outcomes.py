"""
tests/test_page_outcomes.py
---------------------------
The per-page ledger (`page_outcomes` in `<out>.meta.json` and
`<out>.latest_attempt.meta.json`): every requested page number classified,
in ascending order, into exactly one of `content` / `failed` /
`listing_ended` / `unattempted`, derived from the existing
failed_pages / unattempted_pages / exhausted_pages lists.

Everything here is offline: the engine's real `scrape()` runs against a
fake `_fetch_page` and a real `proxy_meter.ProxyMeter` whose budget the
fake spends itself -- no browser, no network. Engines whose driver is not
installed are skipped, not failed, like the rest of this suite.
"""

import importlib
import json
import os
import sys
import types

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

# The pyppeteer/appdirs sandbox shim lives in tests/conftest.py so every
# engine can be collected even when the Windows shell-folder lookup fails.
import output_writer as ow  # noqa: E402
import proxy_check  # noqa: E402
import proxy_meter  # noqa: E402
from output_writer import Product  # noqa: E402

URL = "https://www.zimmo.be/nl/gent-9000/te-koop/"

ENGINES = [
    ("playwright_scraper", "scrape", False),
    ("puppeteer_scraper", "scrape_async", True),
    ("selenium_scraper", "scrape", False),
]


def _load(module_name):
    try:
        return importlib.import_module(module_name)
    except ImportError as e:
        pytest.skip(f"{module_name} unavailable: {e}")


def _proxied_args(tmp_path, pages, concurrency=2, budget_mb=0.01):
    """Args as parse_args() builds them for a metered local-proxy run."""
    return types.SimpleNamespace(
        url=URL, category=None, pages=pages, concurrency=concurrency,
        delay=0, retries=0, retry_delay=0, format="json",
        out=str(tmp_path / "run"), allow_empty=False,
        proxy="http://user:pass@127.0.0.1:9", proxy_file=None,
        proxy_urls=["http://user:pass@127.0.0.1:9"], proxy_shuffle=False,
        proxy_block_retries=3, proxy_rotate=True,
        proxy_budget_mb=budget_mb, cdp_endpoint=None,
        solve_captcha="never", twocaptcha_key=None, min_score=None,
        dump_html=False, headless=True,
    )


def _drive(engine, tmp_path, monkeypatch, plan, *, pages, budget_mb=0.01,
           concurrency=2):
    """Run the engine's real scrape() with a fake fetcher.

    `plan` maps a page number to either a result tuple
    `(products, ok, blocked, remote_error[, parser_failed])`, or to the
    string "budget", which spends the meter past its cap and then raises
    ProxyBudgetExceeded -- exactly what a real navigation refused by the
    budget gate does.
    """
    module_name, entry, is_async = engine
    mod = _load(module_name)
    args = _proxied_args(tmp_path, pages, concurrency=concurrency,
                         budget_mb=budget_mb)
    # The proxy pre-check would open a socket; nothing here uses the network.
    monkeypatch.setattr(proxy_check, "gate", lambda pool, url, timeout=None: None)
    fetched = []

    def _handle(page_num):
        proxy_meter.check(args)
        action = plan.get(page_num, ("missing",))
        if action == "budget":
            proxy_meter.of(args).add(10 ** 9)
            proxy_meter.check(args)  # raises ProxyBudgetExceeded
            raise AssertionError("the meter must refuse an over-budget request")
        fetched.append(page_num)
        result = tuple(action)
        while len(result) < 4:
            result = result + (False,)
        return result

    if is_async:
        async def fake(url, page_num, *a, **k):
            return _handle(page_num)
    else:
        def fake(url, page_num, *a, **k):
            return _handle(page_num)
    monkeypatch.setattr(mod, "_fetch_page", fake)

    import asyncio
    result = getattr(mod, entry)(args)
    code = asyncio.run(result) if is_async else result

    out = args.out
    meta = (json.load(open(out + ".meta.json", encoding="utf-8"))
            if os.path.exists(out + ".meta.json") else None)
    attempt = (json.load(open(out + ".latest_attempt.meta.json", encoding="utf-8"))
               if os.path.exists(out + ".latest_attempt.meta.json") else None)
    return code, meta, attempt, fetched


def _rows(page):
    return [Product(sku=f"P{page}-{i}", url=f"https://www.zimmo.be/x/{page}/{i}")
            for i in range(3)]


def _outcomes(meta):
    return {entry["page"]: entry["outcome"] for entry in meta["page_outcomes"]}


# ---------------------------------------------------------------------------
# The builder itself: derived from the three authoritative lists
# ---------------------------------------------------------------------------

def test_build_page_outcomes_partitions_every_page_once():
    ledger = ow.build_page_outcomes(
        pages_requested=6, failed_pages=[3], unattempted_pages=[5, 6],
        exhausted_pages=[4])
    assert [e["page"] for e in ledger] == [1, 2, 3, 4, 5, 6]
    assert [e["outcome"] for e in ledger] == [
        ow.PAGE_OUTCOME_CONTENT, ow.PAGE_OUTCOME_CONTENT,
        ow.PAGE_OUTCOME_FAILED, ow.PAGE_OUTCOME_EXHAUSTED,
        ow.PAGE_OUTCOME_UNATTEMPTED, ow.PAGE_OUTCOME_UNATTEMPTED]
    # Exactly one row per requested page, every outcome one of the four.
    assert len(ledger) == 6
    assert {e["outcome"] for e in ledger} <= {
        ow.PAGE_OUTCOME_CONTENT, ow.PAGE_OUTCOME_FAILED,
        ow.PAGE_OUTCOME_EXHAUSTED, ow.PAGE_OUTCOME_UNATTEMPTED}


def test_build_page_outcomes_refuses_overlapping_lists():
    with pytest.raises(ValueError):
        ow.build_page_outcomes(3, failed_pages=[2], unattempted_pages=[2],
                               exhausted_pages=[])
    with pytest.raises(ValueError):
        ow.build_page_outcomes(3, failed_pages=[2], unattempted_pages=[],
                               exhausted_pages=[2])
    with pytest.raises(ValueError):
        ow.build_page_outcomes(3, failed_pages=[], unattempted_pages=[2],
                               exhausted_pages=[2])


def test_build_page_outcomes_refuses_pages_outside_range():
    with pytest.raises(ValueError):
        ow.build_page_outcomes(2, failed_pages=[3], unattempted_pages=[],
                               exhausted_pages=[])


# ---------------------------------------------------------------------------
# Acceptance scenario 1: 5 pages, page 2 OK, page 3 fails, then the budget
# is spent. Page 2 content, page 3 failed, pages 4-5 unattempted; rows are
# kept and the run exits 6.
# ---------------------------------------------------------------------------

@pytest.fixture(params=ENGINES, ids=[e[0] for e in ENGINES])
def engine(request):
    return request.param


def test_budget_after_a_failure_keeps_failed_and_unattempted_apart(
        engine, tmp_path, monkeypatch):
    plan = {
        1: (_rows(1), True, False, False),
        2: (_rows(2), True, False, False),
        3: ([], False, False, True),   # attempted, never got content
        4: "budget",                    # meter now refuses before the request
        5: "budget",
    }
    code, meta, attempt, fetched = _drive(
        engine, tmp_path, monkeypatch, plan, pages=5)

    assert code == ow.EXIT_PARTIAL
    assert sorted(fetched) == [1, 2, 3], "the budget must stop pages 4 and 5"

    # The existing lists keep their exact semantics.
    assert meta["failed_pages"] == [3]
    assert meta["unattempted_pages"] == [4, 5]
    assert meta["exhausted_pages"] == []
    assert meta["stop_reason"] == ow.STOP_PROXY_BUDGET_EXCEEDED
    assert meta["proxy_budget_exceeded"] is True
    assert meta["product_count"] > 0, "the rows already gathered are still written"

    # The ledger says the same thing, page by page.
    assert _outcomes(meta) == {
        1: ow.PAGE_OUTCOME_CONTENT,
        2: ow.PAGE_OUTCOME_CONTENT,
        3: ow.PAGE_OUTCOME_FAILED,
        4: ow.PAGE_OUTCOME_UNATTEMPTED,
        5: ow.PAGE_OUTCOME_UNATTEMPTED,
    }
    # The attempt sidecar carries the identical ledger.
    assert attempt["page_outcomes"] == meta["page_outcomes"]
    assert attempt["stop_reason"] == ow.STOP_PROXY_BUDGET_EXCEEDED


# ---------------------------------------------------------------------------
# Acceptance scenario 2: the budget is already spent before the FIRST
# request. Every page (1..3) is unattempted, none failed; no rows, exit 5,
# stop_reason proxy_budget_exceeded; only the attempt sidecar is written.
# ---------------------------------------------------------------------------

def test_budget_spent_before_first_request_marks_every_page_unattempted(
        engine, tmp_path, monkeypatch):
    plan = {1: "budget", 2: "budget", 3: "budget"}
    code, meta, attempt, fetched = _drive(
        engine, tmp_path, monkeypatch, plan, pages=3)

    assert code == ow.EXIT_FETCH_FAILED
    assert fetched == [], "not one page may be requested once the cap is met"
    assert meta is None, "a run with no rows writes no output sidecar"

    assert attempt["stop_reason"] == ow.STOP_PROXY_BUDGET_EXCEEDED
    assert attempt["status"] == "failed"
    assert attempt["failed_pages"] == [], "an unrequested page is never a failure"
    assert attempt["unattempted_pages"] == [1, 2, 3]
    assert _outcomes(attempt) == {
        1: ow.PAGE_OUTCOME_UNATTEMPTED,
        2: ow.PAGE_OUTCOME_UNATTEMPTED,
        3: ow.PAGE_OUTCOME_UNATTEMPTED,
    }
    assert not os.path.exists(str(tmp_path / "run.meta.json"))


# ---------------------------------------------------------------------------
# The listing ending is its own class, never "unattempted".
# ---------------------------------------------------------------------------

def test_listing_end_pages_are_classified_listing_ended(
        engine, tmp_path, monkeypatch):
    # Page 2 adds no new sku: the dispatcher stops and never asks for 3-5.
    seen = {p.sku for p in _rows(1)}
    plan = {
        1: (_rows(1), True, False, False),
        2: ([Product(sku=s, url=f"u-{s}") for s in sorted(seen)], True, False, False),
    }
    # No proxy: an unlimited run, so no meter fields and no budget class.
    module_name, entry, is_async = engine
    mod = _load(module_name)
    args = types.SimpleNamespace(
        url=URL, category=None, pages=5, concurrency=1, delay=0, retries=0,
        retry_delay=0, format="json", out=str(tmp_path / "run"),
        allow_empty=False, proxy=None, proxy_file=None, proxy_urls=None,
        proxy_shuffle=False, proxy_block_retries=3, proxy_rotate=True,
        proxy_budget_mb=0, cdp_endpoint=None, solve_captcha="never",
        twocaptcha_key=None, min_score=None, dump_html=False, headless=True)
    monkeypatch.setattr(proxy_check, "gate", lambda pool, url, timeout=None: None)

    import asyncio

    if is_async:
        async def fake(url, page_num, *a, **k):
            return plan[page_num] if page_num in plan else (
                [], False, False, False)
    else:
        def fake(url, page_num, *a, **k):
            return plan[page_num] if page_num in plan else (
                [], False, False, False)
    monkeypatch.setattr(mod, "_fetch_page", fake)

    result = getattr(mod, entry)(args)
    code = asyncio.run(result) if is_async else result
    assert code == ow.EXIT_OK

    meta = json.load(open(args.out + ".meta.json", encoding="utf-8"))
    assert meta["exhausted_pages"] == [3, 4, 5]
    assert meta["unattempted_pages"] == [] and meta["failed_pages"] == []
    assert _outcomes(meta) == {
        1: ow.PAGE_OUTCOME_CONTENT,
        2: ow.PAGE_OUTCOME_CONTENT,
        3: ow.PAGE_OUTCOME_EXHAUSTED,
        4: ow.PAGE_OUTCOME_EXHAUSTED,
        5: ow.PAGE_OUTCOME_EXHAUSTED,
    }
    # Without a proxy there is no attempt sidecar; nothing to keep in sync.
    assert not os.path.exists(args.out + ".latest_attempt.meta.json")
