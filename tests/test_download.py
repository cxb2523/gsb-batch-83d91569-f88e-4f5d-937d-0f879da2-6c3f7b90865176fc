"""Tests for data download module (Tardis.dev).

All tests are offline: ``data.download.requests.get`` is mocked, so no real
network access is ever made.
"""

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from data.download import (
    DEFAULT_MAX_RETRIES,
    DayDownloadResult,
    DownloadPaths,
    DownloadStatus,
    _atomic_write_bytes,
    _build_tardis_url,
    _download_tardis_day,
    _download_tardis_day_detailed,
    download,
    download_tardis,
)

SYMBOL = "BTCUSDT"
EXCHANGE = "bybit"
DATA_TYPE = "book_snapshot_25"
DAY = date(2024, 1, 1)


def _make_response(status_code: int, content: bytes = b"payload"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    return resp


def _out_path(directory, dt=DAY):
    date_str = dt.strftime("%Y-%m-%d")
    return directory / f"{EXCHANGE}_{DATA_TYPE}_{date_str}_{SYMBOL}.csv.gz"


# ---------------------------------------------------------------------------
# Tardis URL building
# ---------------------------------------------------------------------------


class TestBuildTardisUrl:
    def test_bybit_snapshot_url(self):
        url = _build_tardis_url("bybit", "book_snapshot_25", date(2024, 1, 1), "BTCUSDT")
        assert url == (
            "https://datasets.tardis.dev/v1/bybit/book_snapshot_25/2024/01/01/BTCUSDT.csv.gz"
        )

    def test_binance_futures_url(self):
        url = _build_tardis_url(
            "binance-futures", "incremental_book_L2", date(2024, 3, 1), "ETHUSDT"
        )
        assert url == (
            "https://datasets.tardis.dev/v1/binance-futures/incremental_book_L2"
            "/2024/03/01/ETHUSDT.csv.gz"
        )

    def test_pads_month_and_day(self):
        url = _build_tardis_url("bybit", "book_snapshot_5", date(2024, 2, 5), "BTCUSDT")
        assert "/2024/02/05/" in url


# ---------------------------------------------------------------------------
# Tardis _download_tardis_day (direct HTTP)
# ---------------------------------------------------------------------------


class TestDownloadTardisDay:
    @patch("data.download.requests.get")
    def test_downloads_and_saves(self, mock_get, tmp_path):
        mock_get.return_value = _make_response(200, b"fake,csv,data\n1,2,3\n")

        result = _download_tardis_day("bybit", "book_snapshot_25", DAY, "BTCUSDT", tmp_path)

        assert result is not None
        assert result.exists()
        assert result.name == "bybit_book_snapshot_25_2024-01-01_BTCUSDT.csv.gz"
        assert result.read_bytes() == b"fake,csv,data\n1,2,3\n"

    @patch("data.download.requests.get")
    def test_sends_auth_header(self, mock_get, tmp_path):
        mock_get.return_value = _make_response(200)

        _download_tardis_day(
            "bybit", "book_snapshot_25", DAY, "BTCUSDT", tmp_path, api_key="test-key"
        )

        _, kwargs = mock_get.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer test-key"

    @patch("data.download.requests.get")
    def test_no_auth_header_without_key(self, mock_get, tmp_path):
        mock_get.return_value = _make_response(200)

        _download_tardis_day("bybit", "book_snapshot_25", DAY, "BTCUSDT", tmp_path)

        _, kwargs = mock_get.call_args
        assert "Authorization" not in kwargs["headers"]

    @patch("data.download.requests.get")
    def test_skips_existing(self, mock_get, tmp_path):
        existing = _out_path(tmp_path)
        existing.write_bytes(b"cached")

        result = _download_tardis_day("bybit", "book_snapshot_25", DAY, "BTCUSDT", tmp_path)

        assert result == existing
        mock_get.assert_not_called()

    @patch("data.download.requests.get")
    def test_returns_none_on_401(self, mock_get, tmp_path):
        mock_get.return_value = _make_response(401)

        result = _download_tardis_day(
            "bybit",
            "book_snapshot_25",
            date(2024, 6, 15),
            "BTCUSDT",
            tmp_path,
            retry_delay=0,
        )

        assert result is None
        assert mock_get.call_count == 1

    @patch("data.download.requests.get")
    def test_returns_none_on_404(self, mock_get, tmp_path):
        mock_get.return_value = _make_response(404)

        result = _download_tardis_day(
            "bybit", "book_snapshot_25", DAY, "INVALID", tmp_path, retry_delay=0
        )

        assert result is None
        assert mock_get.call_count == 1

    @patch("data.download.requests.get")
    def test_reports_detailed_record(self, mock_get, tmp_path):
        mock_get.return_value = _make_response(200, b"payload")
        report = []
        _download_tardis_day("bybit", "book_snapshot_25", DAY, "BTCUSDT", tmp_path, report=report)

        assert len(report) == 1
        assert report[0].status == DownloadStatus.DOWNLOADED
        assert report[0].path == _out_path(tmp_path)


# ---------------------------------------------------------------------------
# Retry policy
# ---------------------------------------------------------------------------


class TestRetryPolicy:
    @patch("data.download.requests.get")
    def test_retries_5xx_then_succeeds(self, mock_get, tmp_path):
        mock_get.side_effect = [
            _make_response(503),
            _make_response(200, b"clean,data"),
        ]

        result = _download_tardis_day_detailed(
            "bybit",
            "book_snapshot_25",
            DAY,
            "BTCUSDT",
            tmp_path,
            max_retries=2,
            retry_delay=0,
        )

        assert result.status == DownloadStatus.DOWNLOADED
        assert result.attempts == 2
        assert result.error is None
        assert _out_path(tmp_path).read_bytes() == b"clean,data"
        assert mock_get.call_count == 2

    @patch("data.download.requests.get")
    def test_retries_network_errors_then_succeeds(self, mock_get, tmp_path):
        mock_get.side_effect = [
            requests.ConnectionError("connection reset"),
            _make_response(200, b"ok"),
        ]

        result = _download_tardis_day_detailed(
            "bybit",
            "book_snapshot_25",
            DAY,
            "BTCUSDT",
            tmp_path,
            max_retries=1,
            retry_delay=0,
        )

        assert result.status == DownloadStatus.DOWNLOADED
        assert result.attempts == 2
        assert mock_get.call_count == 2

    @patch("data.download.requests.get")
    def test_401_is_not_retried(self, mock_get, tmp_path):
        mock_get.return_value = _make_response(401)

        result = _download_tardis_day_detailed(
            "bybit",
            "book_snapshot_25",
            date(2024, 6, 15),
            "BTCUSDT",
            tmp_path,
            max_retries=5,
            retry_delay=0,
        )

        assert result.status == DownloadStatus.FAILED
        assert result.attempts == 1
        assert "401" in result.error
        assert mock_get.call_count == 1

    @patch("data.download.requests.get")
    def test_404_is_not_retried(self, mock_get, tmp_path):
        mock_get.return_value = _make_response(404)

        result = _download_tardis_day_detailed(
            "bybit",
            "book_snapshot_25",
            DAY,
            "INVALID",
            tmp_path,
            max_retries=5,
            retry_delay=0,
        )

        assert result.status == DownloadStatus.FAILED
        assert result.attempts == 1
        assert "404" in result.error
        assert mock_get.call_count == 1

    @patch("data.download.requests.get")
    def test_other_4xx_is_not_retried(self, mock_get, tmp_path):
        mock_get.return_value = _make_response(403)

        result = _download_tardis_day_detailed(
            "bybit",
            "book_snapshot_25",
            DAY,
            "BTCUSDT",
            tmp_path,
            max_retries=3,
            retry_delay=0,
        )

        assert result.status == DownloadStatus.FAILED
        assert result.attempts == 1
        assert mock_get.call_count == 1

    @patch("data.download.requests.get")
    def test_exhausts_default_retries_on_persistent_5xx(self, mock_get, tmp_path):
        mock_get.return_value = _make_response(500)

        result = _download_tardis_day_detailed(
            "bybit", "book_snapshot_25", DAY, "BTCUSDT", tmp_path, retry_delay=0
        )

        assert result.status == DownloadStatus.FAILED
        assert result.attempts == DEFAULT_MAX_RETRIES + 1
        assert result.error is not None
        assert mock_get.call_count == DEFAULT_MAX_RETRIES + 1
        assert not _out_path(tmp_path).exists()

    @patch("data.download.requests.get")
    def test_exhausts_retries_on_persistent_network_error(self, mock_get, tmp_path):
        mock_get.side_effect = requests.Timeout("timed out")

        result = _download_tardis_day_detailed(
            "bybit",
            "book_snapshot_25",
            DAY,
            "BTCUSDT",
            tmp_path,
            max_retries=2,
            retry_delay=0,
        )

        assert result.status == DownloadStatus.FAILED
        assert result.attempts == 3
        assert "Timeout" in result.error
        assert mock_get.call_count == 3

    @patch("data.download.requests.get")
    def test_retry_delay_is_used_between_attempts(self, mock_get, tmp_path):
        mock_get.side_effect = [
            _make_response(500),
            _make_response(200),
        ]

        with patch("data.download.time.sleep") as mock_sleep:
            result = _download_tardis_day_detailed(
                "bybit",
                "book_snapshot_25",
                DAY,
                "BTCUSDT",
                tmp_path,
                max_retries=1,
                retry_delay=0.25,
            )

        assert result.status == DownloadStatus.DOWNLOADED
        mock_sleep.assert_called_once_with(0.25)

    @patch("data.download.requests.get")
    def test_zero_max_retries_single_attempt(self, mock_get, tmp_path):
        mock_get.return_value = _make_response(503)

        result = _download_tardis_day_detailed(
            "bybit",
            "book_snapshot_25",
            DAY,
            "BTCUSDT",
            tmp_path,
            max_retries=0,
            retry_delay=0,
        )

        assert result.status == DownloadStatus.FAILED
        assert result.attempts == 1
        assert mock_get.call_count == 1


# ---------------------------------------------------------------------------
# Atomic writes
# ---------------------------------------------------------------------------


class TestAtomicWrites:
    def test_atomic_write_replaces_target(self, tmp_path):
        target = tmp_path / "target.csv.gz"
        target.write_bytes(b"old")

        _atomic_write_bytes(target, b"new")

        assert target.read_bytes() == b"new"
        # No stray temp files remain.
        assert list(tmp_path.iterdir()) == [target]

    def test_write_failure_leaves_no_partial_file(self, tmp_path):
        target = _out_path(tmp_path)

        # Simulate a disk failure during the temporary-file write.
        def explode(*args, **kwargs):
            raise OSError("disk full")

        with (
            patch("data.download.os.fdopen", side_effect=explode),
            pytest.raises(OSError, match="disk full"),
        ):
            _atomic_write_bytes(target, b"content")

        assert not target.exists()
        assert list(tmp_path.iterdir()) == []

    @patch("data.download.requests.get")
    def test_failed_write_is_not_retried_and_reported(self, mock_get, tmp_path, monkeypatch):
        mock_get.return_value = _make_response(200, b"payload")

        def explode(out_path, content):
            raise OSError("no space left on device")

        monkeypatch.setattr("data.download._atomic_write_bytes", explode)

        result = _download_tardis_day_detailed(
            "bybit",
            "book_snapshot_25",
            DAY,
            "BTCUSDT",
            tmp_path,
            max_retries=3,
            retry_delay=0,
        )

        assert result.status == DownloadStatus.FAILED
        assert result.attempts == 1
        assert "write failed" in result.error
        # A local write error must not be retried as a network failure.
        assert mock_get.call_count == 1
        assert not _out_path(tmp_path).exists()
        assert list(tmp_path.iterdir()) == []

    @patch("data.download.requests.get")
    def test_rename_failure_leaves_no_partial_file(self, mock_get, tmp_path):
        mock_get.return_value = _make_response(200, b"payload")

        with patch("data.download.os.replace", side_effect=PermissionError("locked")):
            result = _download_tardis_day_detailed(
                "bybit",
                "book_snapshot_25",
                DAY,
                "BTCUSDT",
                tmp_path,
                max_retries=0,
                retry_delay=0,
            )

        assert result.status == DownloadStatus.FAILED
        assert not _out_path(tmp_path).exists()
        # The temporary file is cleaned up as well.
        assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# download (multi-day)
# ---------------------------------------------------------------------------


class TestDownload:
    @patch("data.download._download_tardis_day")
    def test_downloads_date_range(self, mock_dl, tmp_path):
        mock_dl.side_effect = [tmp_path / "f1.csv.gz", tmp_path / "f2.csv.gz"]

        result = download("BTCUSDT", "2024-01-01", "2024-01-02", output_dir=tmp_path)
        assert len(result) == 2
        assert mock_dl.call_count == 2

    @patch("data.download._download_tardis_day")
    def test_maps_exchange_name(self, mock_dl, tmp_path):
        mock_dl.return_value = tmp_path / "f.csv.gz"

        download("BTCUSDT", "2024-01-01", "2024-01-01", output_dir=tmp_path, exchange="binance")

        # Should map "binance" -> "binance-futures"
        _, kwargs = mock_dl.call_args
        assert kwargs["exchange"] == "binance-futures"

    @patch("data.download._download_tardis_day")
    def test_passes_api_key(self, mock_dl, tmp_path):
        mock_dl.return_value = tmp_path / "f.csv.gz"

        download("BTCUSDT", "2024-01-01", "2024-01-01", output_dir=tmp_path, api_key="my-key")

        _, kwargs = mock_dl.call_args
        assert kwargs["api_key"] == "my-key"

    @patch("data.download._download_tardis_day")
    def test_passes_retry_options(self, mock_dl, tmp_path):
        mock_dl.return_value = tmp_path / "f.csv.gz"

        download(
            "BTCUSDT",
            "2024-01-01",
            "2024-01-01",
            output_dir=tmp_path,
            max_retries=7,
            retry_delay=0.5,
        )

        _, kwargs = mock_dl.call_args
        assert kwargs["max_retries"] == 7
        assert kwargs["retry_delay"] == 0.5

    def test_invalid_range_raises(self, tmp_path):
        with pytest.raises(ValueError, match=r"end .* must be >= start"):
            download("BTCUSDT", "2024-02-01", "2024-01-01", tmp_path)

    def test_download_tardis_alias(self):
        assert download_tardis is download


class TestDownloadDetails:
    """End-to-end per-day reporting through download(), with HTTP mocked."""

    @patch("data.download.requests.get")
    def test_returns_list_subclass_with_details(self, mock_get, tmp_path):
        mock_get.side_effect = [
            _make_response(200, b"day1"),
            _make_response(200, b"day2"),
        ]

        result = download(SYMBOL, "2024-01-01", "2024-01-02", output_dir=tmp_path, retry_delay=0)

        assert isinstance(result, list)
        assert isinstance(result, DownloadPaths)
        assert len(result) == 2
        assert len(result.details) == 2
        assert all(isinstance(d, DayDownloadResult) for d in result.details)

    @patch("data.download.requests.get")
    def test_existing_file_not_counted_as_new_download(self, mock_get, tmp_path):
        existing = _out_path(tmp_path, date(2024, 1, 1))
        existing.write_bytes(b"already here")

        result = download(SYMBOL, "2024-01-01", "2024-01-01", output_dir=tmp_path, retry_delay=0)

        mock_get.assert_not_called()  # no network for this day
        detail = result.details[0]
        assert detail.status == DownloadStatus.EXISTING
        assert detail.attempts == 0
        assert detail.path == existing
        assert existing.read_bytes() == b"already here"
        assert result == [existing]
        assert DownloadStatus.DOWNLOADED not in [d.status for d in result.details]

    @patch("data.download.requests.get")
    def test_mixed_statuses_across_three_days(self, mock_get, tmp_path):
        existing_day = date(2024, 1, 1)
        new_day = date(2024, 1, 2)
        failed_day = date(2024, 1, 3)

        existing = _out_path(tmp_path, existing_day)
        existing.write_bytes(b"already here")

        def fake_get(url, **_kwargs):
            if "/2024/01/03/" in url:
                return _make_response(500)
            return _make_response(200, b"fresh")

        mock_get.side_effect = fake_get

        result = download(
            SYMBOL,
            "2024-01-01",
            "2024-01-03",
            output_dir=tmp_path,
            retry_delay=0,
        )

        statuses = [d.status for d in result.details]
        assert statuses == [
            DownloadStatus.EXISTING,
            DownloadStatus.DOWNLOADED,
            DownloadStatus.FAILED,
        ]
        assert [d.date for d in result.details] == [existing_day, new_day, failed_day]
        assert result.details[0].attempts == 0
        assert result.details[1].attempts == 1
        assert result.details[2].attempts == DEFAULT_MAX_RETRIES + 1
        assert result.details[2].error is not None
        assert "500" in result.details[2].error

        # Only the usable files are returned, preserving the legacy contract.
        assert len(result) == 2
        assert existing in result
        assert _out_path(tmp_path, new_day) in result
        assert _out_path(tmp_path, failed_day) not in result

    @patch("data.download.requests.get")
    def test_details_available_through_details_out(self, mock_get, tmp_path):
        mock_get.return_value = _make_response(401)
        collected = []

        result = download(
            SYMBOL,
            "2024-06-15",
            "2024-06-15",
            output_dir=tmp_path,
            retry_delay=0,
            details_out=collected,
        )

        assert result == []
        assert len(collected) == 1
        assert collected[0].status == DownloadStatus.FAILED
        assert collected[0].attempts == 1
        assert "401" in collected[0].error

    @patch("data.download.requests.get")
    def test_one_detail_per_day_including_failures(self, mock_get, tmp_path):
        mock_get.return_value = _make_response(404)

        result = download(SYMBOL, "2024-01-01", "2024-01-05", output_dir=tmp_path, retry_delay=0)

        assert len(result.details) == 5
        assert result == []
        assert [d.date_str for d in result.details] == [
            "2024-01-01",
            "2024-01-02",
            "2024-01-03",
            "2024-01-04",
            "2024-01-05",
        ]
        assert all(d.status == DownloadStatus.FAILED for d in result.details)

    @patch("data.download.requests.get")
    def test_detail_dict_shape(self, mock_get, tmp_path):
        mock_get.return_value = _make_response(200, b"content")

        result = download(SYMBOL, "2024-01-01", "2024-01-01", output_dir=tmp_path, retry_delay=0)

        record = result.details[0].as_dict()
        assert set(record) == {"date", "status", "attempts", "error", "path"}
        assert record["date"] == "2024-01-01"
        assert record["status"] == "downloaded"
        assert record["attempts"] == 1
        assert record["error"] is None
        assert Path(record["path"]) == result[0]

    @patch("data.download.requests.get")
    def test_day_count_and_spacing(self, mock_get, tmp_path):
        mock_get.return_value = _make_response(200)

        result = download(SYMBOL, "2024-01-30", "2024-02-02", output_dir=tmp_path, retry_delay=0)

        dates = [d.date for d in result.details]
        assert dates == [
            date(2024, 1, 30),
            date(2024, 1, 31),
            date(2024, 2, 1),
            date(2024, 2, 2),
        ]
        assert dates[2] - dates[1] == timedelta(days=1)
