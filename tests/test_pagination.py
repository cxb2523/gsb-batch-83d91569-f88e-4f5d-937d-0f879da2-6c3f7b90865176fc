"""Tests for AntiBlockingScraper.scrape_paginated using local HTML pages."""

import pytest

pytest.importorskip("playwright")

from anti_scraping_playwright.scraper import (
    AntiBlockingScraper,
    ScraperConfig,
    PAGE_STATUS_FAILED,
    PAGE_STATUS_SKIPPED,
    PAGE_STATUS_SUCCESS,
)


def make_scraper():
    return AntiBlockingScraper(ScraperConfig(
        headless=True,
        enable_human_behavior=False,
        stealth_mode=False,
        detect_honeypots=False,
        rotate_user_agent=False,
    ))


def page_html(items, next_url=None):
    lis = "\n".join(
        f'<li class="item" data-id="{iid}">{title}</li>' for iid, title in items
    )
    nxt = f'<a class="next" href="{next_url}">next</a>' if next_url else ""
    return f"<html><body><ul>{lis}</ul>{nxt}</body></html>"


@pytest.fixture
def listing(tmp_path):
    """Three local pages: page1 -> page2 -> page3, with duplicate item ids."""
    p3 = tmp_path / "page3.html"
    p3.write_text(page_html([("x4", "Delta"), ("x1", "Alpha")]), encoding="utf-8")
    p2 = tmp_path / "page2.html"
    p2.write_text(
        page_html([("x2", "Beta"), ("x3", "Gamma")], p3.as_uri()), encoding="utf-8"
    )
    p1 = tmp_path / "page1.html"
    p1.write_text(
        page_html([("x1", "Alpha"), ("x2", "Beta")], p2.as_uri()), encoding="utf-8"
    )
    return {"pages": [p1, p2, p3], "start_url": p1.as_uri()}


def extract_items(page, url):
    return [
        {"id": li.get_attribute("data-id"), "title": li.text_content().strip()}
        for li in page.query_selector_all("li.item")
    ]


def next_page(page):
    link = page.query_selector("a.next")
    return link.get_attribute("href") if link else None


def by_id(item):
    return item["id"]


def test_normal_pagination(listing):
    result = make_scraper().scrape_paginated(
        listing["start_url"], 10, extract_items, next_page, item_key=by_id
    )

    assert [i.data["id"] for i in result.items] == ["x1", "x2", "x3", "x4"]
    assert [i.page for i in result.items] == [1, 1, 2, 3]
    assert result.pages_completed == 3
    assert result.completed_pages == {1, 2, 3}
    assert [p.status for p in result.pages] == [PAGE_STATUS_SUCCESS] * 3
    assert [p.page_number for p in result.pages] == [1, 2, 3]


def test_duplicate_items_keep_first_occurrence(listing):
    result = make_scraper().scrape_paginated(
        listing["start_url"], 10, extract_items, next_page, item_key=by_id
    )

    # x2 reappears on page 2, x1 reappears on page 3: first occurrence wins.
    assert result.duplicates == {"x2": 1, "x1": 1}
    kept = {i.data["id"]: i.page for i in result.items}
    assert kept["x1"] == 1
    assert kept["x2"] == 1


def test_failure_stops_pagination(listing):
    def failing_extract(page, url):
        if "page2" in url:
            raise RuntimeError("boom on page 2")
        return extract_items(page, url)

    result = make_scraper().scrape_paginated(
        listing["start_url"], 10, failing_extract, next_page, item_key=by_id
    )

    # Page 1 results are kept, page 2 is marked failed, page 3 never attempted.
    assert [i.data["id"] for i in result.items] == ["x1", "x2"]
    assert [p.status for p in result.pages] == [PAGE_STATUS_SUCCESS, PAGE_STATUS_FAILED]
    failed = result.pages[1]
    assert failed.page_number == 2
    assert "boom on page 2" in failed.error
    assert result.pages_completed == 1
    assert result.completed_pages == {1}


def test_first_page_failure_returns_empty_items(listing, tmp_path):
    missing = (tmp_path / "does-not-exist.html").as_uri()
    result = make_scraper().scrape_paginated(
        missing, 10, extract_items, next_page, item_key=by_id
    )

    assert result.items == []
    assert result.pages_completed == 0
    assert result.completed_pages == set()
    assert len(result.pages) == 1
    assert result.pages[0].status == PAGE_STATUS_FAILED
    assert result.pages[0].error  # reason is visible


def test_max_pages_zero_starts_no_browser(listing):
    def forbidden_extract(page, url):
        raise AssertionError("extract_callback must not be called")

    result = make_scraper().scrape_paginated(
        listing["start_url"], 0, forbidden_extract, next_page, item_key=by_id
    )

    assert result.items == []
    assert result.pages == []
    assert result.pages_completed == 0
    assert result.completed_pages == set()


def test_resume_skips_completed_pages(listing):
    # First run fails on page 2.
    state = {"fail": True}

    def flaky_extract(page, url):
        if state["fail"] and "page2" in url:
            raise RuntimeError("boom on page 2")
        return extract_items(page, url)

    scraper = make_scraper()
    first = scraper.scrape_paginated(
        listing["start_url"], 10, flaky_extract, next_page, item_key=by_id
    )
    assert first.completed_pages == {1}
    failed_url = first.pages[-1].url

    # Resume from the failed page; page 1 must be skipped entirely.
    state["fail"] = False
    result = scraper.scrape_paginated(
        failed_url, 10, extract_items, next_page,
        item_key=by_id, completed_pages=first.completed_pages,
    )

    # Page 1 shows up as skipped, pages 2 and 3 are scraped now.
    assert [(p.page_number, p.status) for p in result.pages] == [
        (1, PAGE_STATUS_SKIPPED),
        (2, PAGE_STATUS_SUCCESS),
        (3, PAGE_STATUS_SUCCESS),
    ]
    assert [i.page for i in result.items] == [2, 2, 3, 3]
    assert result.pages_completed == 2
    assert result.completed_pages == {1, 2, 3}

    # Skipped page 1 items do not participate in dedup: x1/x2 appear again on
    # pages 2/3 but must not be counted as duplicates.
    assert result.duplicates == {}
