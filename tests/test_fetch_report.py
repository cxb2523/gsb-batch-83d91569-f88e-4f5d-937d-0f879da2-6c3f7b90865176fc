"""Tests for the per-URL fetch outcome report."""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from email_harvester.config import HarvestConfig
from email_harvester.io_csv import FETCH_REPORT_FIELDS, write_fetch_report
from email_harvester.models import FetchOutcome, FetchStatus
from email_harvester.pipeline import harvest_records
from email_harvester.validation import normalize_candidate_urls


def _no_sleep(_min_delay: float, _max_delay: float) -> None:
    return None


class ScriptedSearchBackend:
    """Fake search backend returning a fixed, caller-supplied URL list."""

    def __init__(self, urls: list[str]) -> None:
        self._urls = urls

    def search(self, query: str, num: int, min_delay: float, max_delay: float) -> list[str]:
        _ = (query, num, min_delay, max_delay)
        return list(self._urls)


class ScriptedFetcher:
    """Fake fetcher whose fetch_detailed results are scripted per URL."""

    def __init__(self, outcomes: dict[str, FetchOutcome]) -> None:
        self._outcomes = outcomes
        self.calls: list[str] = []

    def fetch_detailed(self, url: str) -> FetchOutcome:
        self.calls.append(url)
        return self._outcomes[url]

    def fetch(self, url: str) -> str:
        return self.fetch_detailed(url).content


class LegacyStringFetcher:
    """Fetcher implementing only the original string-returning contract."""

    def __init__(self, pages: dict[str, str]) -> None:
        self._pages = pages

    def fetch(self, url: str) -> str:
        return self._pages.get(url, "")


def _outcome(url: str, status: FetchStatus, *, detail: str = "", content: str = "") -> FetchOutcome:
    return FetchOutcome(url=url, status=status, detail=detail, content=content)


def _config(*, use_selenium: bool = False, fetch_report: str | None = None) -> HarvestConfig:
    return HarvestConfig(
        categories=("seo",),
        seeds=tuple(),
        output="emails.csv",
        use_selenium=use_selenium,
        workers=4,
        min_delay=0,
        max_delay=0,
        show_progress=False,
        fetch_report=fetch_report,
    )


def test_mixed_outcomes_one_row_per_url_in_candidate_order() -> None:
    urls = [
        "https://ok.example.com",
        "https://blocked.example.com",
        "https://broken.example.com",
        "ftp://files.example.com/payload",
        "https://ok.example.com",  # duplicate of the first URL, must collapse
    ]
    fetcher = ScriptedFetcher(
        {
            "https://ok.example.com": _outcome(
                "https://ok.example.com", FetchStatus.SUCCESS, content="hi@ok.example.com"
            ),
            "https://blocked.example.com": _outcome(
                "https://blocked.example.com",
                FetchStatus.ROBOTS_BLOCKED,
                detail="Blocked by robots.txt policy.",
            ),
            "https://broken.example.com": _outcome(
                "https://broken.example.com",
                FetchStatus.FETCH_FAILED,
                detail="Request failed: boom",
            ),
        }
    )
    outcomes: list[FetchOutcome] = []
    rows = harvest_records(
        config=_config(),
        search_backend=ScriptedSearchBackend(urls),
        requests_fetcher=fetcher,
        fetch_outcomes=outcomes,
        mx_checker=lambda _email: True,
        sleep_fn=_no_sleep,
        logger=logging.getLogger("test"),
    )

    expected_urls = [
        "https://ok.example.com",
        "https://blocked.example.com",
        "https://broken.example.com",
        "ftp://files.example.com/payload",
    ]
    assert [outcome.url for outcome in outcomes] == expected_urls
    assert [outcome.status for outcome in outcomes] == [
        FetchStatus.SUCCESS,
        FetchStatus.ROBOTS_BLOCKED,
        FetchStatus.FETCH_FAILED,
        FetchStatus.UNSUPPORTED_URL,
    ]
    # Every candidate URL appears exactly once.
    assert len(outcomes) == len(expected_urls)
    assert len({outcome.url for outcome in outcomes}) == len(expected_urls)
    # Success has an empty detail; failures/blocks carry a readable reason.
    assert outcomes[0].detail == ""
    assert outcomes[1].detail
    assert outcomes[2].detail == "Request failed: boom"
    assert outcomes[3].detail
    # Harvesting still produced the email found on the successful page.
    assert any(row["email"] == "hi@ok.example.com" for row in rows)
    # The unsupported URL never reached the fetcher.
    assert "ftp://files.example.com/payload" not in fetcher.calls


def test_all_success_outcomes() -> None:
    urls = ["https://a.example.com", "https://b.example.com"]
    fetcher = ScriptedFetcher(
        {
            "https://a.example.com": _outcome(
                "https://a.example.com", FetchStatus.SUCCESS, content="a@example.com"
            ),
            "https://b.example.com": _outcome(
                "https://b.example.com", FetchStatus.SUCCESS, content="b@example.com"
            ),
        }
    )
    outcomes: list[FetchOutcome] = []
    harvest_records(
        config=_config(),
        search_backend=ScriptedSearchBackend(urls),
        requests_fetcher=fetcher,
        fetch_outcomes=outcomes,
        mx_checker=lambda _email: True,
        sleep_fn=_no_sleep,
        logger=logging.getLogger("test"),
    )
    assert [outcome.status for outcome in outcomes] == [FetchStatus.SUCCESS, FetchStatus.SUCCESS]
    assert all(outcome.detail == "" for outcome in outcomes)


def test_single_url_failure_does_not_stop_other_urls() -> None:
    class ExplodingFetcher:
        def fetch_detailed(self, url: str) -> FetchOutcome:
            if "explode" in url:
                raise RuntimeError("kaboom")
            return _outcome(url, FetchStatus.SUCCESS, content="safe@example.com")

        def fetch(self, url: str) -> str:
            return self.fetch_detailed(url).content

    urls = ["https://explode.example.com", "https://safe.example.com"]
    outcomes: list[FetchOutcome] = []
    harvest_records(
        config=_config(),
        search_backend=ScriptedSearchBackend(urls),
        requests_fetcher=ExplodingFetcher(),
        fetch_outcomes=outcomes,
        mx_checker=lambda _email: True,
        sleep_fn=_no_sleep,
        logger=logging.getLogger("test"),
    )
    statuses = dict((outcome.url, outcome.status) for outcome in outcomes)
    assert statuses["https://explode.example.com"] == FetchStatus.FETCH_FAILED
    assert statuses["https://safe.example.com"] == FetchStatus.SUCCESS


def test_selenium_mode_produces_same_outcome_records() -> None:
    urls = [
        "https://ok.example.com",
        "https://blocked.example.com",
        "https://broken.example.com",
        "ftp://files.example.com/payload",
    ]

    class SeleniumFetcher:
        def __init__(self) -> None:
            self.closed = False
            self._pages = {
                "https://ok.example.com": "page@example.com",
                "https://blocked.example.com": "other@example.com",
            }

        def fetch_detailed(self, url: str) -> FetchOutcome:
            if url == "https://ok.example.com":
                return _outcome(url, FetchStatus.SUCCESS, content=self._pages[url])
            if url == "https://blocked.example.com":
                return _outcome(
                    url, FetchStatus.ROBOTS_BLOCKED, detail="Blocked by robots.txt policy."
                )
            if url == "https://broken.example.com":
                return _outcome(url, FetchStatus.FETCH_FAILED, detail="Browser fetch failed: x")
            return _outcome(
                url,
                FetchStatus.UNSUPPORTED_URL,
                detail="Unsupported URL scheme (only http/https are supported).",
            )

        def fetch(self, url: str) -> str:
            return self.fetch_detailed(url).content

        def close(self) -> None:
            self.closed = True

    fetcher = SeleniumFetcher()
    outcomes: list[FetchOutcome] = []
    harvest_records(
        config=_config(use_selenium=True),
        search_backend=ScriptedSearchBackend(urls),
        requests_fetcher=ScriptedFetcher({}),
        selenium_fetcher_factory=lambda: fetcher,
        fetch_outcomes=outcomes,
        mx_checker=lambda _email: True,
        sleep_fn=_no_sleep,
        logger=logging.getLogger("test"),
    )

    assert [outcome.url for outcome in outcomes] == urls
    assert [outcome.status for outcome in outcomes] == [
        FetchStatus.SUCCESS,
        FetchStatus.ROBOTS_BLOCKED,
        FetchStatus.FETCH_FAILED,
        FetchStatus.UNSUPPORTED_URL,
    ]
    assert fetcher.closed is True


def test_selenium_mode_isolates_single_url_failure() -> None:
    class FlakySeleniumFetcher:
        def fetch_detailed(self, url: str) -> FetchOutcome:
            if "explode" in url:
                raise RuntimeError("driver gone")
            return _outcome(url, FetchStatus.SUCCESS, content="fine@example.com")

        def fetch(self, url: str) -> str:
            return self.fetch_detailed(url).content

        def close(self) -> None:
            return None

    outcomes: list[FetchOutcome] = []
    harvest_records(
        config=_config(use_selenium=True),
        search_backend=ScriptedSearchBackend(
            ["https://explode.example.com", "https://fine.example.com"]
        ),
        requests_fetcher=ScriptedFetcher({}),
        selenium_fetcher_factory=FlakySeleniumFetcher,
        fetch_outcomes=outcomes,
        mx_checker=lambda _email: True,
        sleep_fn=_no_sleep,
        logger=logging.getLogger("test"),
    )
    statuses = dict((outcome.url, outcome.status) for outcome in outcomes)
    assert statuses["https://explode.example.com"] == FetchStatus.FETCH_FAILED
    assert statuses["https://fine.example.com"] == FetchStatus.SUCCESS


def test_without_report_path_harvest_still_works_without_sink() -> None:
    urls = ["https://a.example.com", "https://b.example.com"]
    fetcher = ScriptedFetcher(
        {
            "https://a.example.com": _outcome(
                "https://a.example.com", FetchStatus.SUCCESS, content="a@example.com"
            ),
            "https://b.example.com": _outcome(
                "https://b.example.com", FetchStatus.FETCH_FAILED, detail="Request failed: x"
            ),
        }
    )
    # No fetch_outcomes sink and no fetch_report path: legacy call shape still works.
    rows = harvest_records(
        config=_config(),
        search_backend=ScriptedSearchBackend(urls),
        requests_fetcher=fetcher,
        mx_checker=lambda _email: True,
        sleep_fn=_no_sleep,
        logger=logging.getLogger("test"),
    )
    assert any(row["email"] == "a@example.com" for row in rows)


def test_legacy_string_only_fetcher_is_supported() -> None:
    fetcher = LegacyStringFetcher({"https://a.example.com": "a@example.com"})
    outcomes: list[FetchOutcome] = []
    harvest_records(
        config=_config(),
        search_backend=ScriptedSearchBackend(["https://a.example.com", "https://b.example.com"]),
        requests_fetcher=fetcher,
        fetch_outcomes=outcomes,
        mx_checker=lambda _email: True,
        sleep_fn=_no_sleep,
        logger=logging.getLogger("test"),
    )
    statuses = dict((outcome.url, outcome.status) for outcome in outcomes)
    assert statuses["https://a.example.com"] == FetchStatus.SUCCESS
    assert statuses["https://b.example.com"] == FetchStatus.FETCH_FAILED


def test_fetch_report_file_header_and_row_count(tmp_path: Path) -> None:
    report = tmp_path / "report.csv"
    outcomes = [
        _outcome("https://ok.example.com", FetchStatus.SUCCESS),
        _outcome(
            "https://blocked.example.com",
            FetchStatus.ROBOTS_BLOCKED,
            detail="Blocked by robots.txt policy.",
        ),
        _outcome(
            "https://broken.example.com",
            FetchStatus.FETCH_FAILED,
            detail="Request failed: boom",
        ),
        _outcome(
            "ftp://files.example.com/x",
            FetchStatus.UNSUPPORTED_URL,
            detail="Unsupported URL scheme.",
        ),
    ]
    write_fetch_report(str(report), outcomes)

    with report.open(encoding="utf-8", newline="") as file_obj:
        reader = csv.reader(file_obj)
        header = next(reader)
        body = list(reader)

    assert header == FETCH_REPORT_FIELDS == ["url", "status", "detail"]
    assert len(body) == len(outcomes)
    assert body[0] == ["https://ok.example.com", "success", ""]
    assert body[1][1] == "robots_blocked" and body[1][2]
    assert body[2][1] == "fetch_failed" and body[2][2] == "Request failed: boom"
    assert body[3][1] == "unsupported_url" and body[3][2]


def test_run_pipeline_writes_report_only_when_configured(tmp_path: Path) -> None:
    from email_harvester import pipeline

    output_csv = tmp_path / "emails.csv"
    report_csv = tmp_path / "report.csv"
    config = HarvestConfig(
        categories=("seo",),
        seeds=tuple(),
        output=str(output_csv),
        fetch_report=str(report_csv),
        min_delay=0,
        max_delay=0,
        show_progress=False,
    )

    scripted_outcomes = [
        _outcome("https://ok.example.com", FetchStatus.SUCCESS),
        _outcome(
            "https://blocked.example.com",
            FetchStatus.ROBOTS_BLOCKED,
            detail="Blocked by robots.txt policy.",
        ),
    ]

    def fake_harvest_records(**kwargs):
        kwargs["fetch_outcomes"].extend(scripted_outcomes)
        return []

    original_harvest = pipeline.harvest_records
    original_write_rows = pipeline.write_rows
    try:
        pipeline.harvest_records = fake_harvest_records  # type: ignore[assignment]
        pipeline.write_rows = lambda path, rows: Path(path).write_text("", encoding="utf-8")  # type: ignore[assignment]
        result = pipeline.run_pipeline(config, logger=logging.getLogger("test"))
    finally:
        pipeline.harvest_records = original_harvest  # type: ignore[assignment]
        pipeline.write_rows = original_write_rows  # type: ignore[assignment]

    assert result == str(output_csv)
    assert output_csv.exists()
    assert report_csv.exists()
    with report_csv.open(encoding="utf-8", newline="") as file_obj:
        reader = csv.reader(file_obj)
        header = next(reader)
        body = list(reader)
    assert header == FETCH_REPORT_FIELDS
    assert len(body) == 2


def test_run_pipeline_skips_report_when_path_not_configured(tmp_path: Path) -> None:
    from email_harvester import pipeline

    output_csv = tmp_path / "emails.csv"
    report_csv = tmp_path / "report.csv"
    config = HarvestConfig(
        categories=("seo",),
        seeds=tuple(),
        output=str(output_csv),
        fetch_report=None,
        min_delay=0,
        max_delay=0,
        show_progress=False,
    )

    original_harvest = pipeline.harvest_records
    original_write_rows = pipeline.write_rows
    try:
        pipeline.harvest_records = lambda **kwargs: []  # type: ignore[assignment]
        pipeline.write_rows = lambda path, rows: Path(path).write_text("", encoding="utf-8")  # type: ignore[assignment]
        pipeline.run_pipeline(config, logger=logging.getLogger("test"))
    finally:
        pipeline.harvest_records = original_harvest  # type: ignore[assignment]
        pipeline.write_rows = original_write_rows  # type: ignore[assignment]

    assert output_csv.exists()
    assert not report_csv.exists()


def test_normalize_candidate_urls_keeps_unsupported_and_dedupes() -> None:
    urls = [
        "https://example.com/a",
        "https://example.com/a?x=1",  # same dedupe key as the first URL
        "ftp://example.com/file",
        "ftp://example.com/file",
        "  ",
    ]
    assert normalize_candidate_urls(urls) == [
        "https://example.com/a",
        "ftp://example.com/file",
    ]
