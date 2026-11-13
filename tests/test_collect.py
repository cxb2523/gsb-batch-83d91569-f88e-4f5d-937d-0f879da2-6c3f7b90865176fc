"""Offline tests for ``collect_trustpilot_reviews``: partial results survive failures.

No network access: every response is served from ``tests/fixtures`` through a fake
``requests.get``, mirroring the approach in ``test_scraper.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest
import requests

import trustpilot_scraper as tp
from trustpilot_scraper import scraper

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeResponse:
    def __init__(self, text: str = "", status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def install_pages(monkeypatch, pages: dict[int, FakeResponse]) -> list[str]:
    calls: list[str] = []

    def _get(url, headers=None, timeout=None):
        calls.append(url)
        page = int(url.rsplit("page=", 1)[1])
        return pages.get(page, FakeResponse("", 404))

    monkeypatch.setattr(scraper.requests, "get", _get)
    return calls


def test_collect_two_pages_success(monkeypatch) -> None:
    pages = {1: FakeResponse(load("page1.html")), 2: FakeResponse(load("page2.html"))}
    calls = install_pages(monkeypatch, pages)
    events: list[tuple[int, int, int]] = []

    with mock.patch.object(scraper.time, "sleep"):
        result = tp.collect_trustpilot_reviews(
            "www.example.com", delay=1.5, on_page=lambda p, n, total: events.append((p, n, total))
        )

    # rev0003 appears on both fixtures and must be de-duplicated, keeping page order.
    assert [r["Author"] for r in result.reviews] == [f"Reviewer {i}" for i in range(1, 6)]
    assert result.successful_pages == [1, 2]
    assert result.failed_page is None
    assert result.failed_pages is None
    assert result.error_message is None
    assert result.error_type is None
    assert result.stopped_early is False
    assert events == [(1, 3, 3), (2, 2, 5)]
    assert len(calls) == 2


def test_collect_second_page_403_keeps_first_page(monkeypatch) -> None:
    pages = {1: FakeResponse(load("page1.html")), 2: FakeResponse("", 403)}
    install_pages(monkeypatch, pages)

    result = tp.collect_trustpilot_reviews("www.example.com", delay=0)

    assert len(result.reviews) == 3
    assert [r["Author"] for r in result.reviews] == ["Reviewer 1", "Reviewer 2", "Reviewer 3"]
    assert result.successful_pages == [1]
    assert result.failed_page == 2
    assert result.failed_pages == [2]
    assert result.error_type == "TrustpilotBlockedError"
    assert result.exception_type == "TrustpilotBlockedError"
    assert result.exception_type_name == "TrustpilotBlockedError"
    assert "HTTP 403" in (result.error_message or "")
    assert result.error == result.error_message
    assert result.pages_succeeded == [1]
    assert result.stopped_early is True


def test_collect_second_page_bad_json(monkeypatch) -> None:
    bad_json = '<script id="__NEXT_DATA__">{broken json</script>'
    pages = {1: FakeResponse(load("page1.html")), 2: FakeResponse(bad_json)}
    install_pages(monkeypatch, pages)

    result = tp.collect_trustpilot_reviews("www.example.com", delay=0)

    assert len(result.reviews) == 3
    assert result.successful_pages == [1]
    assert result.failed_page == 2
    assert result.failed_pages == [2]
    assert result.error_type == "TrustpilotParseError"
    assert "not valid JSON" in (result.error_message or "")
    assert result.stopped_early is True


@pytest.mark.parametrize(
    ("page1", "expected_type"),
    [
        (FakeResponse("", 403), "TrustpilotBlockedError"),
        (FakeResponse(load("challenge.html")), "TrustpilotBlockedError"),
        (FakeResponse("<html><body>nothing</body></html>"), "TrustpilotParseError"),
    ],
)
def test_collect_first_page_failure_has_empty_reviews(
    monkeypatch, page1: FakeResponse, expected_type: str
) -> None:
    install_pages(monkeypatch, {1: page1})

    result = tp.collect_trustpilot_reviews("www.example.com", delay=0)

    assert result.reviews == []
    assert result.successful_pages == []
    assert result.failed_page == 1
    assert result.failed_pages == [1]
    assert result.error_type == expected_type
    assert bool(result.error_message)
    assert result.stopped_early is True


def test_collect_callback_exception_is_wrapped_and_raised(monkeypatch) -> None:
    pages = {1: FakeResponse(load("page1.html")), 2: FakeResponse(load("page2.html"))}
    install_pages(monkeypatch, pages)

    def boom(page: int, new: int, total: int) -> None:
        raise RuntimeError("callback exploded")

    with (
        mock.patch.object(scraper.time, "sleep"),
        pytest.raises(tp.TrustpilotError, match="on_page callback failed on page 1") as info,
    ):
        tp.collect_trustpilot_reviews("www.example.com", delay=0, on_page=boom)

    assert isinstance(info.value.__cause__, RuntimeError)


def test_collect_callback_trustpilot_error_passes_through(monkeypatch) -> None:
    install_pages(monkeypatch, {1: FakeResponse(load("page1.html"))})

    def boom(page: int, new: int, total: int) -> None:
        raise tp.TrustpilotBlockedError("raised inside callback", status_code=429)

    with pytest.raises(tp.TrustpilotBlockedError, match="raised inside callback"):
        tp.collect_trustpilot_reviews("www.example.com", delay=0, on_page=boom)


def test_collect_invalid_max_pages_raises_value_error() -> None:
    with pytest.raises(ValueError, match="max_pages must be >= 1"):
        tp.collect_trustpilot_reviews("www.example.com", max_pages=0)


def test_collect_respects_max_pages_and_stops_without_failure(monkeypatch) -> None:
    pages = {1: FakeResponse(load("page1.html")), 2: FakeResponse(load("page2.html"))}
    calls = install_pages(monkeypatch, pages)

    result = tp.collect_trustpilot_reviews("www.example.com", max_pages=1, delay=0)

    assert len(result.reviews) == 3
    assert result.successful_pages == [1]
    assert result.failed_page is None
    assert result.stopped_early is False
    assert len(calls) == 1


def test_collect_empty_page_stops_cleanly(monkeypatch) -> None:
    body = {"props": {"pageProps": {"reviews": [{"id": "a", "text": "x"}]}}}
    empty = {"props": {"pageProps": {"reviews": []}}}
    pages = {
        1: FakeResponse(f'<script id="__NEXT_DATA__">{json.dumps(body)}</script>'),
        2: FakeResponse(f'<script id="__NEXT_DATA__">{json.dumps(empty)}</script>'),
    }
    install_pages(monkeypatch, pages)
    events: list[tuple[int, int, int]] = []

    result = tp.collect_trustpilot_reviews(
        "x.com", delay=0, on_page=lambda p, n, t: events.append((p, n, t))
    )

    assert [r["Body"] for r in result.reviews] == ["x"]
    assert result.successful_pages == [1, 2]
    assert result.failed_page is None
    assert result.stopped_early is False
    # The empty page still counts as a successfully parsed page for the callback.
    assert events == [(1, 1, 1), (2, 0, 1)]


def test_collect_other_trustpilot_error_is_caught(monkeypatch) -> None:
    install_pages(monkeypatch, {1: FakeResponse("", 404)})

    result = tp.collect_trustpilot_reviews("www.example.com", delay=0)

    assert result.reviews == []
    assert result.failed_page == 1
    assert result.error_type == "TrustpilotError"
    assert "not found" in (result.error_message or "")
    assert result.stopped_early is True


def test_collect_extended_fields_and_custom_session() -> None:
    session = mock.Mock(spec=requests.Session)
    session.get.return_value = FakeResponse(load("page1.html"))

    result = tp.collect_trustpilot_reviews(
        "https://www.trustpilot.com/review/x.com",
        max_pages=1,
        delay=0,
        extended=True,
        session=session,
    )

    assert result.reviews[0]["ReviewId"] == "rev0001"
    assert result.successful_pages == [1]
    session.get.assert_called_once()


def test_collect_dedupes_identical_reviews_without_ids(monkeypatch) -> None:
    review = {"text": "same body", "rating": 4}
    body = {"props": {"pageProps": {"reviews": [dict(review), dict(review)]}}}
    install_pages(
        monkeypatch,
        {1: FakeResponse(f'<script id="__NEXT_DATA__">{json.dumps(body)}</script>')},
    )

    result = tp.collect_trustpilot_reviews("x.com", max_pages=1, delay=0)

    assert len(result.reviews) == 1
    assert result.successful_pages == [1]
