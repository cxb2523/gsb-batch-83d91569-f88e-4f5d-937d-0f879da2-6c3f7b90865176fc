"""Unit tests for PSXClient.stocks_report — all mocked, no network required."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pandas as pd
import pytest

from psxdata.client import PSXClient
from psxdata.models.results import HistoricalFetchResult, HistoricalOutcome

FIXED_TODAY = pd.Timestamp("2024-06-15")


@pytest.fixture(autouse=True)
def freeze_today(monkeypatch):
    monkeypatch.setattr("psxdata.client._today", lambda: FIXED_TODAY)


@pytest.fixture
def client(tmp_path):
    c = PSXClient(cache_dir=str(tmp_path / "cache"))
    c._historical = MagicMock()
    return c


def _frame(dates: list[str]) -> pd.DataFrame:
    n = len(dates)
    return pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "open": [100.0] * n,
            "high": [105.0] * n,
            "low": [98.0] * n,
            "close": [103.0] * n,
            "volume": pd.array([10_000] * n, dtype="Int64"),
            "is_anomaly": [False] * n,
        }
    )


def _report(
    dates: list[str],
    outcome: HistoricalOutcome = HistoricalOutcome.COMPLETE,
    **overrides,
) -> HistoricalFetchResult:
    data = _frame(dates)
    first = data["date"].min().date() if len(data) else None
    last = data["date"].max().date() if len(data) else None
    defaults = dict(
        symbol="ENGRO",
        data=data,
        complete=outcome is HistoricalOutcome.COMPLETE,
        outcome=outcome,
        first_date=first,
        last_date=last,
        message="Complete.",
        failure_reason=None,
        attempts=1,
        rows_parsed=len(data),
    )
    defaults.update(overrides)
    return HistoricalFetchResult(**defaults)


class TestStocksReport:
    def test_complete_pass_through(self, client):
        client._historical.fetch_report.return_value = _report(
            ["2024-01-01", "2024-01-02", "2024-01-03"]
        )
        result = client.stocks_report("ENGRO")

        assert result.outcome is HistoricalOutcome.COMPLETE
        assert result.complete is True
        assert len(result.data) == 3
        client._historical.fetch_report.assert_called_once_with("ENGRO", start=None, end=None)

    def test_symbol_is_upper_cased(self, client):
        client._historical.fetch_report.return_value = _report(["2024-01-01"])
        client.stocks_report("engro")
        client._historical.fetch_report.assert_called_once_with("ENGRO", start=None, end=None)

    def test_start_end_filter_updates_bounds_and_message(self, client):
        client._historical.fetch_report.return_value = _report(
            ["2023-12-29", "2024-01-02", "2024-01-04", "2024-01-09"]
        )
        result = client.stocks_report("ENGRO", start="2024-01-02", end="2024-01-04")

        assert list(result.data["date"].dt.date) == [date(2024, 1, 2), date(2024, 1, 4)]
        assert result.first_date == date(2024, 1, 2)
        assert result.last_date == date(2024, 1, 4)
        assert result.complete is True
        assert "2024-01-02..2024-01-04" in result.message

    def test_filter_removing_everything_reports_no_data(self, client):
        client._historical.fetch_report.return_value = _report(["2023-01-01", "2023-01-02"])
        result = client.stocks_report("ENGRO", start="2024-03-01", end="2024-04-01")

        assert result.outcome is HistoricalOutcome.NO_DATA
        assert result.complete is False
        assert result.data.empty
        assert result.first_date is None and result.last_date is None
        assert result.failure_reason == "filtered_out"
        assert "No data" in result.message

    def test_partial_report_is_preserved_through_filter(self, client):
        client._historical.fetch_report.return_value = _report(
            ["2023-01-01", "2024-01-02"],
            outcome=HistoricalOutcome.PARTIAL,
            failure_reason="network_error",
            message="Partial: ENGRO delivered 2 row(s) after a timeout retry.",
            attempts=2,
        )
        result = client.stocks_report("ENGRO", start="2024-01-01")

        assert result.outcome is HistoricalOutcome.PARTIAL
        assert result.complete is False
        assert result.failure_reason == "network_error"
        assert result.attempts == 2
        assert len(result.data) == 1
        assert "Partial" in result.message
        assert "Delivered range after filtering" in result.message

    def test_failed_report_does_not_raise(self, client):
        client._historical.fetch_report.return_value = _report(
            [],
            outcome=HistoricalOutcome.FAILED,
            failure_reason="server_error_5xx",
            message="Failed: PSX server error (503). No rows delivered.",
        )
        result = client.stocks_report("ENGRO")

        assert result.outcome is HistoricalOutcome.FAILED
        assert result.data.empty
        assert "Failed" in result.message

    def test_invalid_range_raises_before_scraper_call(self, client):
        with pytest.raises(ValueError, match="must not be after"):
            client.stocks_report("ENGRO", start="2025-01-01", end="2024-01-01")
        client._historical.fetch_report.assert_not_called()

    def test_report_bypasses_cache(self, client, tmp_path):
        client._historical.fetch_report.return_value = _report(["2024-01-01"])
        client.stocks_report("ENGRO")
        # Nothing is written by stocks_report.
        assert client._cache.get("ENGRO_historical") is None
        assert client._cache.get("ENGRO_today") is None


class TestResultType:
    def test_complete_flag_matches_outcome(self):
        r = _report(["2024-01-01"])
        assert r.success is True and r.is_complete is True
        assert r.date_range == (date(2024, 1, 1), date(2024, 1, 1))
        assert r.df is r.data and r.frame is r.data
        assert r.conclusion == r.message

    def test_empty_frame_keeps_canonical_columns(self):
        r = _report([])
        assert r.empty is True
        assert list(r.data.columns) == [
            "date", "open", "high", "low", "close", "volume", "is_anomaly"
        ]

    def test_repr_does_not_dump_the_dataframe(self):
        r = _report(["2024-01-01", "2024-01-02"])
        text = repr(r)
        assert "ENGRO" in text and "rows=2" in text
        assert "open" not in text
