"""tests/test_page_ledger.py — per-page ledger behaviour.

Covers the four pagination-accounting cases the ledger was built for, all
driven through playwright_scraper.scrape_listing with locally constructed
HTML and a faked browser (no network, no real Chromium):

  1. a normal multi-page run — every page registered ok with its product
     and NEW-sku counts, in page order;
  2. concurrent workers that finish OUT OF PAGE ORDER — the ledger is still
     written in ascending page-number order;
  3. a failed page 1 — later pages are registered as "skipped", never as
     fabricated successes, and no ledger file is written when no page
     completed;
  4. a repeated page-number registration — the first result is kept and
     add_page() returns False.

Plus the "page served but added zero new skus" rule: such a page is still
recorded as ok with new_sku_count 0 before the run stops.
"""
from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import page_ledger  # noqa: E402
import playwright_scraper  # noqa: E402
from page_ledger import PageLedger, ledger_path_for  # noqa: E402

START_URL = "https://stockx.com/category/sneakers"


# --------------------------------------------------------------------------- #
# Locally constructed listing HTML — a minimal getDiscoveryData payload in
# the exact __NEXT_DATA__ shape product_parser reads.
# --------------------------------------------------------------------------- #
def listing_html(*url_keys: str, page: int = 1, page_count: int = 25, total: int = 100) -> str:
    edges = [
        {"node": {
            "__typename": "Product",
            "title": f"Shoe {key}",
            "brand": "Jordan",
            "urlKey": key,
            "productCategory": "sneakers",
            "media": {"thumbUrl": f"https://images.example/{key}.jpg"},
            "market": {"state": {"lowestAsk": {"amount": 100 + i}},
                       "statistics": {}},
        }}
        for i, key in enumerate(url_keys)
    ]
    query = {
        "queryKey": ["getDiscoveryData", {"variables": {"currency": "USD", "flow": "CATEGORY"}}],
        "state": {"data": {"browse": {"results": {
            "edges": edges,
            "pageInfo": {"page": page, "pageCount": page_count, "total": total},
        }}}},
    }
    next_data = {"props": {"pageProps": {"req": {"appContext": {"states": {"query": {"value": {
        "queries": [query]
    }}}}}}}}
    return (
        '<!DOCTYPE html><html><body><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(next_data)
        + "</script></body></html>"
    )


BLOCK_HTML = '<!DOCTYPE html><html id="__next_error__"><body>Something went wrong</body></html>'
NOT_FOUND_HTML = "<html><body><h1>Page not found</h1></body></html>"


def _page_number(url: str) -> int:
    from urllib.parse import parse_qs, urlparse

    return int(parse_qs(urlparse(url).query).get("page", ["1"])[0])


# --------------------------------------------------------------------------- #
# Faked Playwright browser/context/page — goto/content only, enough for the
# engine's _fetch/classify/parse path.
# --------------------------------------------------------------------------- #
class FakePage:
    def __init__(self, route, delays):
        self._route = route
        self._delays = delays

    async def goto(self, url, wait_until=None, timeout=None):
        n = _page_number(url)
        delay = self._delays.get(n, 0)
        if delay:
            await asyncio.sleep(delay)
        status, html = self._route(n, url)
        self._html = html
        return types.SimpleNamespace(status=status)

    async def wait_for_timeout(self, ms):
        pass

    async def content(self):
        return self._html


class FakeContext:
    def __init__(self, route, delays):
        self._route = route
        self._delays = delays

    async def new_page(self):
        return FakePage(self._route, self._delays)

    async def close(self):
        pass


class FakeBrowser:
    def __init__(self, route, delays=None):
        self._route = route
        self._delays = delays or {}

    async def new_context(self, **kwargs):
        return FakeContext(self._route, self._delays)


class Args:
    def __init__(self, *, pages, concurrency=1, out="unused.json"):
        self.pages = pages
        self.concurrency = concurrency
        self.delay = 0
        self.retries = 0
        self.retry_delay = 0
        self.proxy_rotate = False
        self.dump_html = False
        self.solve_captcha = "off"
        self.out = out


def run_scrape(route, *, pages, concurrency=1, delays=None, ledger=None):
    browser = FakeBrowser(route, delays)
    return asyncio.run(
        playwright_scraper.scrape_listing(
            args=Args(pages=pages, concurrency=concurrency),
            start_url=START_URL,
            browser=browser,
            proxy_pool=None,
            client=None,
            ledger=ledger,
        )
    )


def keys_for_page(n):
    return [f"p{n}-sku-{i}" for i in range(3)]


# --------------------------------------------------------------------------- #
# 1. Normal multi-page run, sequential mode
# --------------------------------------------------------------------------- #
def test_normal_multi_page_records_every_page_in_order():
    def route(n, url):
        return 200, listing_html(*keys_for_page(n), page=n)

    ledger = PageLedger()
    pages_products, failed_pages, flags = run_scrape(route, pages=3, ledger=ledger)

    assert failed_pages == []
    assert len(pages_products) == 3
    assert flags.stop_reason == "requested_pages_done"

    data = ledger.to_dict()
    assert [r["page"] for r in data["pages"]] == [1, 2, 3]
    assert all(r["result"] == page_ledger.RESULT_OK for r in data["pages"])
    assert all(r["product_count"] == 3 for r in data["pages"])
    # Distinct skus on every page => every page's rows are all new.
    assert all(r["new_sku_count"] == 3 for r in data["pages"])
    assert data["result_counts"]["ok"] == 3
    assert data["page_count"] == 3


def test_page_with_zero_new_skus_is_ok_with_zero_new_then_stops():
    def route(n, url):
        # Page 2 repeats page 1's rows exactly: served and parsed fine,
        # but adds nothing new.
        return 200, listing_html(*keys_for_page(1), page=n, page_count=5)

    ledger = PageLedger()
    pages_products, failed_pages, flags = run_scrape(route, pages=4, ledger=ledger)

    assert flags.stop_reason == "no_new_rows"
    data = ledger.to_dict()
    assert [r["page"] for r in data["pages"]] == [1, 2]
    p1, p2 = data["pages"]
    assert p1["result"] == "ok" and p1["new_sku_count"] == 3
    assert p2["result"] == "ok", "a repeat page was still served and parsed — ok, not a failure"
    assert p2["new_sku_count"] == 0
    assert p2["product_count"] == 3


# --------------------------------------------------------------------------- #
# 2. Concurrent workers finishing out of page order
# --------------------------------------------------------------------------- #
def test_concurrent_out_of_order_completion_writes_ledger_sorted_by_page(monkeypatch):
    # Higher page numbers are served first: workers 4, 3, 2 finish in that
    # order. READINESS sleeps are zeroed by the fake, so the per-page delay
    # alone controls completion order. Spy on _fetch to record the actual
    # resolution order, proving the workers really do overtake each other.
    finished_at = []
    real_fetch = playwright_scraper._fetch

    async def spy_fetch(ctx_page, url, **kwargs):
        result = await real_fetch(ctx_page, url, **kwargs)
        finished_at.append(_page_number(url))
        return result

    monkeypatch.setattr(playwright_scraper, "_fetch", spy_fetch)

    def route(n, url):
        return 200, listing_html(*keys_for_page(n), page=n)

    delays = {2: 0.30, 3: 0.15, 4: 0.02}
    ledger = PageLedger()
    pages_products, failed_pages, flags = run_scrape(
        route, pages=4, concurrency=3, delays=delays, ledger=ledger)

    assert failed_pages == []
    assert len(pages_products) == 4  # page 1 + workers 2..4
    # The workers really did resolve out of page order ...
    assert finished_at == [1, 4, 3, 2]
    # ... yet merge order stays page order.
    first_skus = {p.sku for p in pages_products[0]}
    assert first_skus == set(keys_for_page(1))

    data = ledger.to_dict()
    pages = data["pages"]
    assert [r["page"] for r in pages] == [1, 2, 3, 4], (
        "concurrent completion order must not leak into ledger order")
    assert all(r["result"] == "ok" for r in pages)
    assert all(r["new_sku_count"] == 3 for r in pages)


def test_concurrent_mid_run_block_is_recorded_per_page():
    def route(n, url):
        if n == 3:
            return 403, BLOCK_HTML
        return 200, listing_html(*keys_for_page(n), page=n)

    ledger = PageLedger()
    _, failed_pages, _ = run_scrape(
        route, pages=4, concurrency=2, delays={2: 0.05}, ledger=ledger)

    assert failed_pages == [3]
    by_page = {r["page"]: r for r in ledger.to_dict()["pages"]}
    assert by_page[1]["result"] == "ok"
    assert by_page[2]["result"] == "ok"
    assert by_page[3]["result"] == "blocked"
    assert "HTTP 403" in by_page[3]["reason"]
    assert by_page[4]["result"] == "ok"


# --------------------------------------------------------------------------- #
# 3. Page 1 failure — later pages become skipped, nothing is fabricated
# --------------------------------------------------------------------------- #
def test_first_page_failure_marks_later_pages_skipped():
    def route(n, url):
        if n == 1:
            return 403, BLOCK_HTML
        return 200, listing_html(*keys_for_page(n), page=n)

    ledger = PageLedger()
    pages_products, failed_pages, flags = run_scrape(route, pages=3, ledger=ledger)

    assert pages_products == []
    assert failed_pages == [1]
    assert flags.blocked is True

    data = ledger.to_dict()
    assert [r["page"] for r in data["pages"]] == [1, 2, 3]
    assert data["pages"][0]["result"] == "blocked"
    assert data["result_counts"]["blocked"] == 1
    assert data["result_counts"]["skipped"] == 2
    for record in data["pages"][1:]:
        assert record["result"] == "skipped"
        assert record["product_count"] == 0
        assert record["new_sku_count"] == 0
        assert record["reason"]


def test_first_page_not_found_is_not_fabricated_as_success():
    def route(n, url):
        if n == 1:
            return 404, NOT_FOUND_HTML
        return 200, listing_html(*keys_for_page(n), page=n)

    ledger = PageLedger()
    _, failed_pages, flags = run_scrape(route, pages=2, ledger=ledger)

    assert failed_pages == [1] and flags.not_found is True
    by_page = {r["page"]: r for r in ledger.to_dict()["pages"]}
    assert by_page[1]["result"] == "not_found"
    assert by_page[2]["result"] == "skipped"


def test_ledger_file_only_written_when_a_page_completed(tmp_path):
    out_path = tmp_path / "run.json"
    ledger_file = Path(ledger_path_for(str(out_path)))

    def failing_route(n, url):
        return 403, BLOCK_HTML

    ledger = PageLedger()
    run_scrape(failing_route, pages=2, ledger=ledger)
    # No page completed: the run must leave no ledger file behind.
    assert not ledger_file.exists()
    assert len(ledger) == 2  # the failure + the skipped page were still recorded in memory

    # And a successful run writes it, atomically-produced and re-readable.
    def good_route(n, url):
        return 200, listing_html(*keys_for_page(n), page=n)

    good_ledger = PageLedger()
    run_scrape(good_route, pages=2, ledger=good_ledger)
    good_ledger.write_json(str(ledger_file))
    written = json.loads(ledger_file.read_text(encoding="utf-8"))
    assert [r["page"] for r in written["pages"]] == [1, 2]
    # No leftover temp files from the atomic write.
    assert sorted(p.name for p in tmp_path.iterdir()) == ["run.pages.json"]


# --------------------------------------------------------------------------- #
# 4. Duplicate page-number registration keeps the first result
# --------------------------------------------------------------------------- #
def test_duplicate_page_registration_keeps_first_and_returns_false():
    ledger = PageLedger()
    assert ledger.add_page(1, "ok", product_count=5, new_sku_count=5) is True

    # Every later attempt at the same page number is rejected, whatever it
    # claims — a failure must not overwrite the recorded success.
    assert ledger.add_page(1, "blocked", reason="late, contradictory report") is False
    assert ledger.add_page(1, "fetch_failed", reason="also rejected") is False

    record = ledger.to_dict()["pages"][0]
    assert record == {
        "page": 1,
        "result": "ok",
        "product_count": 5,
        "new_sku_count": 5,
        "reason": None,
    }
    assert len(ledger) == 1


def test_add_page_rejects_unknown_result_category():
    ledger = PageLedger()
    with pytest.raises(ValueError):
        ledger.add_page(1, "definitely_not_a_status")


def test_ledger_path_derivation_strips_extension():
    assert ledger_path_for("stockx.json").endswith("stockx.pages.json")
    assert ledger_path_for("nested/dir/out.csv").replace("\\", "/").endswith("nested/dir/out.pages.json")


def test_long_reason_is_bounded_but_kept():
    ledger = PageLedger()
    ledger.add_page(2, "fetch_failed", reason="x " * 500)
    reason = ledger.to_dict()["pages"][0]["reason"]
    assert len(reason) <= page_ledger.MAX_REASON_LEN
    assert reason.endswith("…")
