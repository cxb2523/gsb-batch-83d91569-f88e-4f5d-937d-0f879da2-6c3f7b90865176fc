"""Offline tests for per-page crawl run recording.

These tests never touch the network: a :class:`FakeDriver` replaces the Selenium
driver and serves scripted page responses (including scripted rate-limiting,
timeouts, missing elements and keyboard interrupts).
"""

import json
from pathlib import Path
from typing import Any

import pytest
from bs4 import BeautifulSoup
from selenium.common.exceptions import TimeoutException

from mpscraper import mpscraper as mpscraper_module
from mpscraper.exceptions import (
    ElementNotFoundError,
    ForbiddenError,
    ListingsInterruptError,
)
from mpscraper.mpscraper import MARTKPLAATS_BASE_URL, Category, MpScraper
from mpscraper.run_recorder import (
    RESULT_ELEMENT_MISSING,
    RESULT_EMPTY,
    RESULT_RATE_LIMITED,
    RESULT_SUCCESS,
    RESULT_TIMEOUT,
    STATUS_COMPLETED,
    STATUS_INTERRUPTED,
    STATUS_RUNNING,
    STOP_EMPTY_PAGE,
    STOP_INTERRUPTED,
    STOP_LIMIT_REACHED,
    STOP_RETRIES_EXHAUSTED,
    RunRecorder,
)

PARENT_CATEGORY = Category(id=100, url=f"{MARTKPLAATS_BASE_URL}/l/parent/")
SUBCATEGORY = Category(id=200, url=f"{MARTKPLAATS_BASE_URL}/l/parent/child/")
SUBCATEGORY_ID = 200


def make_listing(item_id: str, category_id: int = SUBCATEGORY_ID) -> dict[str, Any]:
    """Return a minimal Marktplaats listing payload for the fake page JSON."""
    return {
        "itemId": item_id,
        "categoryId": category_id,
        "title": f"Title {item_id}",
        "vipUrl": f"/v/{item_id}/",
        "pictures": [{"extraExtraLargeUrl": f"https://img/{item_id}.jpg"}],
        "location": {"countryAbbreviation": "NL", "cityName": "Amsterdam"},
        "verticals": ["Parent", "Child"],
        "sellerInformation": {"sellerId": "seller-1"},
    }


def make_listing_details() -> dict[str, Any]:
    """Return the window.__CONFIG__ payload returned by the fake driver."""
    return {
        "listing": {
            "adType": "CIRCULAR",
            "priceInfo": {"priceType": "FIXED", "priceCents": 1234},
            "stats": {
                "viewCount": 10,
                "favoritedCount": 2,
                "since": "2024-01-01T00:00:00+00:00",
            },
        }
    }


def make_soup(listings: list[dict[str, Any]] | None) -> BeautifulSoup:
    """Return a BeautifulSoup page carrying the given listings in __NEXT_DATA__."""
    payload = {
        "props": {
            "pageProps": {
                "searchRequestAndResponse": {
                    "listings": listings if listings is not None else [],
                    "totalResultCount": 4,
                    "searchCategoryOptions": [
                        {
                            "id": SUBCATEGORY_ID,
                            "key": "child",
                            "parentId": PARENT_CATEGORY.id,
                            "parentKey": "parent",
                        }
                    ],
                }
            }
        }
    }
    next_data = json.dumps(payload)
    html = (
        '<html><body><div id="content"></div>'
        f'<script id="__NEXT_DATA__" type="application/json">{next_data}</script>'
        "</body></html>"
    )

    return BeautifulSoup(html, "lxml")


LISTING_DETAIL_SOUP = BeautifulSoup(
    '<html><body><div id="listing-root"></div>'
    '<div class="Description-description">A nice description</div>'
    '<div class="Attributes-item"><strong class="Attributes-label">type</strong>'
    '<span class="Attributes-value">Used</span></div></body></html>',
    "lxml",
)


class FakeDriver:
    """In-memory replacement for MPDriver serving scripted responses."""

    def __init__(
        self,
        pages: dict[int, Any],
        total_result_count: int = 4,
        subcategory_options: list[dict[str, Any]] | None = None,
    ) -> None:
        # page number -> either a list of listing dicts, an Exception instance,
        # or None (page with missing __NEXT_DATA__ script)
        self.pages = pages
        self.total_result_count = total_result_count
        self.subcategory_options = subcategory_options or [
            {
                "id": SUBCATEGORY_ID,
                "key": "child",
                "parentId": PARENT_CATEGORY.id,
                "parentKey": "parent",
            }
        ]
        self.config_payload = make_listing_details()
        self.get_calls: list[str] = []
        self.current_url: str = ""
        self._attempt_cursor: dict[int, int] = {}

    def get(self, url: str) -> None:
        self.get_calls.append(url)
        self.current_url = url

    def find_element(self, by: str, value: str) -> object:
        # Minimal stand-in so WebDriverWait(...).until(presence_of_element_located) passes
        return object()

    @staticmethod
    def _page_number(url: str) -> int:
        # URLs end with .../p/<page>/#sortBy:...
        part = url.split("/p/")[1]
        return int(part.split("/")[0])

    def get_soup(self) -> BeautifulSoup:
        # Listing detail pages
        if "/v/" in self.current_url:
            return LISTING_DETAIL_SOUP

        if "/p/" not in self.current_url:
            # Category landing page (used by listings_count / subcategories)
            payload = {
                "props": {
                    "pageProps": {
                        "searchRequestAndResponse": {
                            "totalResultCount": self.total_result_count,
                            "searchCategoryOptions": self.subcategory_options,
                        }
                    }
                }
            }
            html = (
                '<html><body><div id="content"></div>'
                f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
                "</body></html>"
            )
            return BeautifulSoup(html, "lxml")

        page_number = self._page_number(self.current_url)
        response = self.pages.get(page_number, [])

        # Retry scripts are stored as a list of per-attempt responses; each response
        # is either an Exception (raised for that attempt), None (missing element) or
        # a list of listing dicts. A sequence containing an Exception/None entry marks
        # a retry script (a plain listings page only contains dict entries). A cursor
        # tracks which attempt is next, without mutating the shared script.
        if isinstance(response, list) and any(
            item is None or isinstance(item, BaseException) for item in response
        ):
            cursor = self._attempt_cursor.get(page_number, 0)
            scripted = response[cursor] if cursor < len(response) else response[-1]
            self._attempt_cursor[page_number] = cursor + 1
            response = scripted

        if isinstance(response, BaseException):
            raise response

        if response is None:
            # Page without the expected __NEXT_DATA__ script element
            return BeautifulSoup('<html><body><div id="content"></div></body></html>', "lxml")

        return make_soup(response)

    def execute_script(self, script: str) -> dict[str, Any]:
        return self.config_payload

    def quit(self) -> None:
        pass


def build_scraper(
    pages: dict[int, Any],
    recorder: RunRecorder,
    max_page_retries: int = 3,
    total_result_count: int = 4,
) -> MpScraper:
    """Construct an MpScraper wired to a FakeDriver without starting a browser."""
    driver = FakeDriver(pages=pages, total_result_count=total_result_count)

    return MpScraper(
        headless=True,
        timeout_seconds=0,
        wait_seconds=0,
        max_page_retries=max_page_retries,
        run_recorder=recorder,
        driver=driver,
    )


def subcategory_attempts(recorder: RunRecorder) -> list[dict[str, Any]]:
    """Return the raw attempt dicts of the single crawled sub-category."""
    assert len(recorder.parent_categories) == 1
    parent = recorder.parent_categories[0]
    assert parent.category_id == PARENT_CATEGORY.id
    assert len(parent.subcategories) == 1

    return [attempt.to_dict() for attempt in parent.subcategories[0].attempts]


def subcategory_record(recorder: RunRecorder):
    return recorder.parent_categories[0].subcategories[0]


class TestRunRecording:
    def test_normal_paging_records_every_page_and_new_counts(self, monkeypatch: pytest.MonkeyPatch):
        """Two successful pages then an empty page stops paging; ads and existing IDs skipped."""
        monkeypatch.setattr(mpscraper_module, "sleep", lambda _seconds: None)

        pages = {
            1: [
                make_listing("a-ad"),  # advertisement prefix -> skipped
                make_listing("1001"),
                make_listing("1002"),
                make_listing("1001"),  # duplicate within page -> skipped
            ],
            2: [
                make_listing("existing"),  # in existing_item_ids -> skipped
                make_listing("1003"),
            ],
            3: [],  # empty page -> stop
        }
        recorder = RunRecorder()
        scraper = build_scraper(pages, recorder, total_result_count=100)

        listings = scraper.get_listings(
            parent_category=PARENT_CATEGORY,
            limit=0,
            existing_item_ids={"existing"},
        )

        assert {listing.item_id for listing in listings} == {"1001", "1002", "1003"}
        assert all(listing.item_id[0] != "a" for listing in listings)

        attempts = subcategory_attempts(recorder)
        assert [(a["page"], a["result"], a["new_listings"]) for a in attempts] == [
            (1, RESULT_SUCCESS, 2),
            (2, RESULT_SUCCESS, 1),
            (3, RESULT_EMPTY, 0),
        ]
        assert all(a["attempt"] == 1 for a in attempts)

        record = subcategory_record(recorder)
        assert record.stop_reason == STOP_EMPTY_PAGE

        summary = recorder.summary()
        assert summary["status"] == STATUS_RUNNING
        assert summary["successful_pages"] == 2
        assert summary["empty_pages"] == 1
        assert summary["rate_limited_attempts"] == 0
        assert summary["timeout_attempts"] == 0
        assert summary["error_skipped_pages"] == 0
        assert summary["total_new_listings"] == 3

        recorder.finalize()
        assert recorder.summary()["status"] == STATUS_COMPLETED

    def test_empty_first_page_stops_immediately(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(mpscraper_module, "sleep", lambda _seconds: None)

        recorder = RunRecorder()
        scraper = build_scraper({1: []}, recorder)

        listings = scraper.get_listings(parent_category=PARENT_CATEGORY, limit=10)

        assert listings == []
        attempts = subcategory_attempts(recorder)
        assert len(attempts) == 1
        assert attempts[0]["page"] == 1
        assert attempts[0]["result"] == RESULT_EMPTY
        assert subcategory_record(recorder).stop_reason == STOP_EMPTY_PAGE
        assert recorder.summary()["empty_pages"] == 1

    def test_rate_limit_then_retry_succeeds_each_attempt_recorded(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(mpscraper_module, "sleep", lambda _seconds: None)

        pages = {
            1: [ForbiddenError("blocked"), ForbiddenError("blocked"), [make_listing("2001")]],
            2: [],
        }
        recorder = RunRecorder()
        scraper = build_scraper(pages, recorder, max_page_retries=3, total_result_count=100)

        listings = scraper.get_listings(parent_category=PARENT_CATEGORY, limit=10)

        assert [listing.item_id for listing in listings] == ["2001"]

        attempts = subcategory_attempts(recorder)
        assert [(a["page"], a["attempt"], a["result"]) for a in attempts] == [
            (1, 1, RESULT_RATE_LIMITED),
            (1, 2, RESULT_RATE_LIMITED),
            (1, 3, RESULT_SUCCESS),
            (2, 1, RESULT_EMPTY),
        ]

        summary = recorder.summary()
        assert summary["rate_limited_attempts"] == 2
        assert summary["successful_pages"] == 1
        # The rate-limited page eventually succeeded, so it is not error-skipped
        assert summary["error_skipped_pages"] == 0
        assert subcategory_record(recorder).stop_reason == STOP_EMPTY_PAGE

    def test_retries_exhausted_stops_subcategory_and_counts_skipped_page(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(mpscraper_module, "sleep", lambda _seconds: None)

        pages = {
            1: [
                TimeoutException("timed out"),
                TimeoutException("timed out"),
            ],
        }
        recorder = RunRecorder()
        # max_page_retries=1 -> initial attempt + one retry = 2 attempts
        scraper = build_scraper(pages, recorder, max_page_retries=1)

        listings = scraper.get_listings(parent_category=PARENT_CATEGORY, limit=10)

        assert listings == []
        attempts = subcategory_attempts(recorder)
        assert [(a["page"], a["attempt"], a["result"]) for a in attempts] == [
            (1, 1, RESULT_TIMEOUT),
            (1, 2, RESULT_TIMEOUT),
        ]
        assert subcategory_record(recorder).stop_reason == STOP_RETRIES_EXHAUSTED

        summary = recorder.summary()
        assert summary["timeout_attempts"] == 2
        assert summary["error_skipped_pages"] == 1
        assert summary["successful_pages"] == 0

    def test_element_missing_retries_then_exhausted(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(mpscraper_module, "sleep", lambda _seconds: None)

        pages = {1: [None, None, None]}  # None -> page without __NEXT_DATA__
        recorder = RunRecorder()
        scraper = build_scraper(pages, recorder, max_page_retries=2)

        listings = scraper.get_listings(parent_category=PARENT_CATEGORY, limit=10)

        assert listings == []
        attempts = subcategory_attempts(recorder)
        assert len(attempts) == 3
        assert all(a["result"] == RESULT_ELEMENT_MISSING for a in attempts)
        assert [a["attempt"] for a in attempts] == [1, 2, 3]
        assert subcategory_record(recorder).stop_reason == STOP_RETRIES_EXHAUSTED
        assert recorder.summary()["element_missing_attempts"] == 3
        assert recorder.summary()["error_skipped_pages"] == 1

    def test_limit_reached_stop_reason(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(mpscraper_module, "sleep", lambda _seconds: None)

        pages = {1: [make_listing("3001"), make_listing("3002")]}
        recorder = RunRecorder()
        scraper = build_scraper(pages, recorder, total_result_count=2)

        listings = scraper.get_listings(parent_category=PARENT_CATEGORY, limit=1)

        assert len(listings) == 1
        attempts = subcategory_attempts(recorder)
        assert len(attempts) == 1
        assert attempts[0]["result"] == RESULT_SUCCESS
        assert attempts[0]["new_listings"] == 1
        assert subcategory_record(recorder).stop_reason == STOP_LIMIT_REACHED

    def test_interrupt_is_persisted_to_file_with_completed_pages(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(mpscraper_module, "sleep", lambda _seconds: None)

        class InterruptingDriver(FakeDriver):
            def get_soup(self) -> BeautifulSoup:
                if "/p/" in self.current_url and self._page_number(self.current_url) == 2:
                    raise KeyboardInterrupt()
                return super().get_soup()

        crawl_file = tmp_path / "crawl_pages.json"
        recorder = RunRecorder(file_path=crawl_file)
        driver = InterruptingDriver(pages={1: [make_listing("4001")], 2: []}, total_result_count=4)
        scraper = MpScraper(
            headless=True,
            timeout_seconds=0,
            wait_seconds=0,
            run_recorder=recorder,
            driver=driver,
        )

        with pytest.raises(ListingsInterruptError):
            scraper.get_listings(parent_category=PARENT_CATEGORY, limit=10)

        # The active sub-category is tagged with the interrupt stop reason
        assert subcategory_record(recorder).stop_reason == STOP_INTERRUPTED

        # Page 1 was flushed to disk before the interrupt on page 2
        assert crawl_file.is_file()
        on_disk = json.loads(crawl_file.read_text(encoding="utf-8"))
        assert on_disk["status"] == STATUS_INTERRUPTED
        pages_on_disk = on_disk["parent_categories"][0]["subcategories"][0]["pages"]
        assert len(pages_on_disk) == 1
        assert pages_on_disk[0]["page"] == 1
        assert pages_on_disk[0]["result"] == RESULT_SUCCESS

        recorder.finalize(interrupted=True)
        finalized = json.loads(crawl_file.read_text(encoding="utf-8"))
        assert finalized["status"] == STATUS_INTERRUPTED
        assert finalized["summary"]["successful_pages"] == 1
        assert finalized["finished_at"] is not None

    def test_no_records_means_no_file_is_written(self, tmp_path: Path):
        crawl_file = tmp_path / "crawl_pages.json"
        recorder = RunRecorder(file_path=crawl_file)

        recorder.finalize()

        assert not crawl_file.exists()
        assert recorder.has_records() is False

    def test_full_run_record_file_structure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(mpscraper_module, "sleep", lambda _seconds: None)

        crawl_file = tmp_path / "data" / "crawl_pages.json"
        recorder = RunRecorder(file_path=crawl_file)
        scraper = build_scraper(
            {1: [make_listing("5001")], 2: []}, recorder, total_result_count=100
        )

        scraper.get_listings(parent_category=PARENT_CATEGORY, limit=0)
        recorder.finalize()

        data = json.loads(crawl_file.read_text(encoding="utf-8"))
        assert set(data.keys()) == {
            "status",
            "started_at",
            "finished_at",
            "summary",
            "parent_categories",
        }
        parent = data["parent_categories"][0]
        assert parent["category_id"] == PARENT_CATEGORY.id
        assert parent["category_url"] == PARENT_CATEGORY.url
        sub = parent["subcategories"][0]
        assert sub["category_id"] == SUBCATEGORY_ID
        assert sub["stop_reason"] == STOP_EMPTY_PAGE
        attempt = sub["pages"][0]
        assert set(attempt.keys()) == {"page", "attempt", "result", "new_listings", "timestamp"}

        summary = data["summary"]
        for key in (
            "successful_pages",
            "empty_pages",
            "rate_limited_attempts",
            "timeout_attempts",
            "error_skipped_pages",
        ):
            assert key in summary

    def test_mixed_rate_limit_timeout_then_failure(self, monkeypatch: pytest.MonkeyPatch):
        """Every retry (rate-limit and timeout variants) leaves its own trace."""
        monkeypatch.setattr(mpscraper_module, "sleep", lambda _seconds: None)

        pages = {
            1: [
                ForbiddenError("blocked"),
                TimeoutException("timed out"),
                ElementNotFoundError("script", {"id": "__NEXT_DATA__"}),
            ]
        }
        recorder = RunRecorder()
        scraper = build_scraper(pages, recorder, max_page_retries=2)

        listings = scraper.get_listings(parent_category=PARENT_CATEGORY, limit=10)

        assert listings == []
        attempts = subcategory_attempts(recorder)
        assert [a["result"] for a in attempts] == [
            RESULT_RATE_LIMITED,
            RESULT_TIMEOUT,
            RESULT_ELEMENT_MISSING,
        ]
        assert subcategory_record(recorder).stop_reason == STOP_RETRIES_EXHAUSTED
        summary = recorder.summary()
        assert summary["rate_limited_attempts"] == 1
        assert summary["timeout_attempts"] == 1
        assert summary["element_missing_attempts"] == 1
        assert summary["error_skipped_pages"] == 1
