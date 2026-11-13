"""Reliability tests for HistoricalScraper.fetch_report — mocked network only.

Covers the outcome report: complete success, recovered-after-timeout (partial),
exhausted retries (failed), and HTTP 200 with nothing to parse (no data).
Every HTML body is constructed locally; no request leaves the process.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import requests

from psxdata.exceptions import PSXMissingColumnsError, PSXServerError
from psxdata.models.results import HistoricalFetchResult, HistoricalOutcome
from psxdata.scrapers.historical import HistoricalScraper

pytestmark = pytest.mark.reliability

FIXTURE = (
    Path(__file__).parent.parent / "fixtures" / "historical_engro.html"
).read_text(encoding="utf-8")


def _mock_response(text: str, status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.text = text
    return resp


TABLE_HEADERS = """
<table id="historicalTable">
  <thead><tr>
    <th>DATE</th><th>OPEN</th><th>HIGH</th><th>LOW</th><th>CLOSE</th><th>VOLUME</th>
  </tr></thead>
"""


def make_table(rows: list[tuple], headers: str | None = None) -> str:
    """Build a PSX-shaped historical table from (date, o, h, l, c, v) tuples."""
    head = headers or "DATE,OPEN,HIGH,LOW,CLOSE,VOLUME"
    cells = []
    for r in rows:
        cells.append("<tr>" + "".join(f"<td>{v}</td>" for v in r) + "</tr>")
    header_row = "<tr>" + "".join(f"<th>{h}</th>" for h in head.split(",")) + "</tr>"
    return (
        f'<table id="historicalTable"><thead>{header_row}</thead>'
        f"<tbody>{''.join(cells)}</tbody></table>"
    )


MULTI_ROW_HTML = make_table(
    [
        ("Jan 3, 2025", "481.99", "496.00", "474.01", "485.38", "4,496,408"),
        ("Jan 2, 2025", "452.00", "484.00", "451.51", "478.30", "3,602,326"),
        ("Jan 1, 2025", "448.90", "455.00", "444.50", "451.15", "1,299,509"),
    ]
)
# Dates deliberately out of order above — the result must still be ascending.


def run(scraper: HistoricalScraper, side_effect, **kwargs) -> HistoricalFetchResult:
    """Call fetch_report with a mocked session.request, silencing retry sleeps."""
    with patch.object(scraper._session, "request", side_effect=side_effect), patch(
        "psxdata.scrapers.base.time.sleep"
    ):
        return scraper.fetch_report("ENGRO", **kwargs)


class TestCompleteOutcome:
    def test_multi_row_response_is_complete_with_date_bounds(self):
        report = run(HistoricalScraper(), lambda *a, **k: _mock_response(MULTI_ROW_HTML))

        assert report.outcome is HistoricalOutcome.COMPLETE
        assert report.complete is True
        assert report.failure_reason is None
        assert report.attempts == 1
        assert len(report.data) == 3
        assert report.first_date == date(2025, 1, 1)
        assert report.last_date == date(2025, 1, 3)
        assert of_dates(report.data) == sorted(of_dates(report.data))
        assert "Complete" in report.message
        assert report.message.startswith("Complete: ENGRO")

    def test_dataframe_is_validated_and_typed(self):
        report = run(HistoricalScraper(), lambda *a, **k: _mock_response(FIXTURE))

        assert len(report.data) > 0
        assert "is_anomaly" in report.data.columns
        assert report.data["close"].dtype == float
        assert str(report.data["volume"].dtype) == "Int64"

    def test_date_filter_bounds_reflect_delivered_rows(self):
        report = run(
            HistoricalScraper(),
            lambda *a, **k: _mock_response(FIXTURE),
            start=date(2022, 1, 1),
            end=date(2022, 12, 31),
        )
        assert report.outcome is HistoricalOutcome.COMPLETE
        assert report.first_date >= date(2022, 1, 1)
        assert report.last_date <= date(2022, 12, 31)
        assert report.message.endswith("Date filter applied: 2022-01-01..2022-12-31.")


def of_dates(df: pd.DataFrame) -> list[date]:
    return [d.date() if isinstance(d, pd.Timestamp) else d for d in df["date"]]


class TestPartialOutcome:
    def test_timeout_then_success_keeps_rows_and_reports_partial(self):
        responses = [requests.Timeout("timed out"), _mock_response(MULTI_ROW_HTML)]
        report = run(HistoricalScraper(), responses)

        assert report.outcome is HistoricalOutcome.PARTIAL
        assert report.complete is False
        assert report.failure_reason == "network_error"
        assert report.attempts == 2
        assert len(report.data) == 3
        assert report.first_date == date(2025, 1, 1)
        assert report.last_date == date(2025, 1, 3)
        assert "network error" in report.message
        assert "retained" in report.message

    def test_5xx_then_success_is_partial(self):
        responses = [_mock_response("", status_code=503), _mock_response(MULTI_ROW_HTML)]
        report = run(HistoricalScraper(), responses)

        assert report.outcome is HistoricalOutcome.PARTIAL
        assert report.failure_reason == "server_error_5xx"
        assert len(report.data) == 3
        assert "server error (503)" in report.message

    def test_rows_dropped_by_validation_make_partial(self):
        html = make_table(
            [
                ("Jan 2, 2025", "452.00", "484.00", "451.51", "478.30", "3,602,326"),
                ("Jan 3, 2025", "481.99", "496.00", "474.01", "", ""),  # no close/volume
            ]
        )
        report = run(HistoricalScraper(), lambda *a, **k: _mock_response(html))

        assert report.outcome is HistoricalOutcome.PARTIAL
        assert len(report.data) == 1
        assert report.failure_reason == "rows_dropped_by_validation"
        assert "dropped by OHLC validation" in report.message

    def test_exhausted_5xx_salvages_rows_from_earlier_error_body(self):
        """All three attempts fail, but attempt 1's body held a parseable table."""
        responses = [
            _mock_response(MULTI_ROW_HTML, status_code=503),
            _mock_response("", status_code=502),
            _mock_response("", status_code=500),
        ]
        report = run(HistoricalScraper(), responses)

        assert report.outcome is HistoricalOutcome.PARTIAL
        assert report.complete is False
        assert report.failure_reason == "server_error_5xx"
        assert len(report.data) == 3
        assert report.first_date == date(2025, 1, 1)
        assert "attempt 1" in report.message
        assert "retries were exhausted" in report.message

    def test_fetch_returns_salvaged_rows_instead_of_raising(self):
        responses = [
            _mock_response(MULTI_ROW_HTML, status_code=503),
            _mock_response("", status_code=502),
            _mock_response("", status_code=500),
        ]
        scraper = HistoricalScraper()
        with patch.object(scraper._session, "request", side_effect=responses), patch(
            "psxdata.scrapers.base.time.sleep"
        ):
            df = scraper.fetch("ENGRO")
        assert len(df) == 3


class TestFailedOutcome:
    def test_persistent_5xx_returns_failed_report_with_reason(self):
        scraper = HistoricalScraper()
        report = run(
            scraper, lambda *a, **k: _mock_response("", status_code=503)
        )

        assert report.outcome is HistoricalOutcome.FAILED
        assert report.complete is False
        assert report.failure_reason == "server_error_5xx"
        assert report.data.empty
        assert report.first_date is None and report.last_date is None
        assert report.attempts == 3
        assert "Failed" in report.message and "server error (503)" in report.message
        assert isinstance(report.error, PSXServerError)

    def test_persistent_timeout_returns_failed_report(self):
        report = run(
            HistoricalScraper(),
            requests.Timeout("timeout"),
        )
        assert report.outcome is HistoricalOutcome.FAILED
        assert report.failure_reason == "network_error"
        assert report.data.empty
        assert "network error (Timeout)" in report.message

    def test_fetch_raises_server_error_when_nothing_delivered(self):
        scraper = HistoricalScraper()
        with patch.object(
            scraper._session, "request", side_effect=lambda *a, **k: _mock_response("", 503)
        ), patch("psxdata.scrapers.base.time.sleep"):
            with pytest.raises(PSXServerError):
                scraper.fetch("ENGRO")

    def test_rate_limit_fails_without_retry(self):
        report = run(HistoricalScraper(), lambda *a, **k: _mock_response("", 429))
        assert report.outcome is HistoricalOutcome.FAILED
        assert report.failure_reason == "rate_limited"
        assert report.attempts == 1
        assert "429" in report.message

    def test_unexpected_4xx_is_http_error(self):
        report = run(HistoricalScraper(), lambda *a, **k: _mock_response("", 404))
        assert report.outcome is HistoricalOutcome.FAILED
        assert report.failure_reason == "http_error"
        assert "404" in report.message
        assert "[HTTP 404]" not in report.message  # cause already named

    def test_missing_required_column_fails_with_named_columns(self):
        html = make_table(
            [("Jan 2, 2025", "452.00", "484.00", "451.51", "478.30", "3,602,326")],
            headers="DATE,OPEN,HIGH,LOW,VOLUME",  # CLOSE missing
        )
        report = run(HistoricalScraper(), lambda *a, **k: _mock_response(html))

        assert report.outcome is HistoricalOutcome.FAILED
        assert report.failure_reason == "missing_columns"
        assert "close" in report.message
        assert isinstance(report.error, PSXMissingColumnsError)
        assert isinstance(report.error, ValueError)
        assert report.error.missing == ["close"]
        assert report.raw_columns == frozenset({"date", "open", "high", "low", "volume"})


class TestNoDataOutcome:
    def test_unparseable_dates_only_is_no_data(self):
        html = make_table([("n/a", "1", "2", "1", "1", "10"), ("--", "1", "2", "1", "1", "10")])
        report = run(HistoricalScraper(), lambda *a, **k: _mock_response(html))

        assert report.outcome is HistoricalOutcome.NO_DATA
        assert report.failure_reason == "unparseable_dates"
        assert report.data.empty
        assert "usable date" in report.message

    def test_empty_table_with_headers_is_no_data(self):
        html = make_table([])
        report = run(HistoricalScraper(), lambda *a, **k: _mock_response(html))

        assert report.outcome is HistoricalOutcome.NO_DATA
        assert report.failure_reason == "empty_table"
        assert report.data.empty
        assert "held no rows" in report.message

    def test_html_without_table_is_no_data_not_success(self):
        report = run(HistoricalScraper(), lambda *a, **k: _mock_response("<html></html>"))

        assert report.outcome is HistoricalOutcome.NO_DATA
        assert report.complete is False
        assert report.failure_reason == "no_table"
        assert report.data.empty
        assert list(report.data.columns) == [
            "date", "open", "high", "low", "close", "volume", "is_anomaly"
        ]
        assert report.first_date is None and report.last_date is None
        assert "No data" in report.message
        assert "no table" in report.message

    def test_table_without_headers_is_no_data(self):
        report = run(
            HistoricalScraper(),
            lambda *a, **k: _mock_response(
                "<table><tbody><tr><td>100</td></tr></tbody></table>"
            ),
        )
        assert report.outcome is HistoricalOutcome.NO_DATA
        assert report.failure_reason == "no_table_headers"
        assert report.data.empty

    def test_filter_that_removes_everything_is_reported(self):
        report = run(
            HistoricalScraper(),
            lambda *a, **k: _mock_response(MULTI_ROW_HTML),
            start=date(2030, 1, 1),
        )
        assert report.outcome is HistoricalOutcome.NO_DATA
        assert report.failure_reason == "filtered_out"
        assert report.data.empty
        assert "none fall in the requested range" in report.message
