"""Historical L2 order book data downloader.

Downloads from Tardis.dev — professional-grade tick-level data for 40+
crypto exchanges. Free sample data (1st of each month) without API key
via direct HTTP download. Full access requires a paid API key from
https://tardis.dev.
"""

from __future__ import annotations

import contextlib
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

DEFAULT_RAW_DIR = Path(__file__).parent / "raw"

# Retry policy defaults. Only transient failures are retried: network
# exceptions and HTTP 5xx responses. 4xx responses (401, 404, ...) are
# definitive and are never retried.
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 1.0  # seconds between attempts

# ---------------------------------------------------------------------------
# Tardis.dev downloader (direct HTTP — no SDK required)
# ---------------------------------------------------------------------------

TARDIS_DATASETS_URL = "https://datasets.tardis.dev/v1"

# Map common exchange names to Tardis exchange identifiers.
TARDIS_EXCHANGE_MAP = {
    "bybit": "bybit",
    "binance": "binance-futures",
    "binance-spot": "binance",
    "okx": "okex-swap",
    "deribit": "deribit",
}


class DownloadStatus(StrEnum):
    """Outcome of a single-day download attempt."""

    EXISTING = "existing"  # file was already on disk, nothing was fetched
    DOWNLOADED = "downloaded"  # file was fetched and written in this run
    FAILED = "failed"  # every allowed attempt failed


@dataclass(frozen=True)
class DayDownloadResult:
    """Per-day audit record produced by the download chain.

    Attributes:
        date: Trading date the record refers to.
        status: One of :class:`DownloadStatus` (``existing`` / ``downloaded``
            / ``failed``).
        attempts: Number of HTTP attempts made. Zero when the file already
            existed and nothing was requested.
        error: Failure reason for ``failed`` records, otherwise ``None``.
        path: Path to the file for ``existing`` / ``downloaded`` records,
            otherwise ``None``.
    """

    date: date
    status: DownloadStatus
    attempts: int
    error: str | None = None
    path: Path | None = None

    # Convenience aliases so callers can use whichever name reads best.
    @property
    def reason(self) -> str | None:
        """Alias for :attr:`error`."""
        return self.error

    @property
    def dt(self) -> date:
        """Alias for :attr:`date`."""
        return self.date

    @property
    def date_str(self) -> str:
        """ISO date string (``YYYY-MM-DD``)."""
        return self.date.strftime("%Y-%m-%d")

    @property
    def ok(self) -> bool:
        """True when the day is usable (already present or newly written)."""
        return self.status != DownloadStatus.FAILED

    @property
    def is_failure(self) -> bool:
        """True for failed days."""
        return self.status == DownloadStatus.FAILED

    def as_dict(self) -> dict:
        """Plain-dict representation, useful for reports/serialization."""
        return {
            "date": self.date_str,
            "status": self.status.value,
            "attempts": self.attempts,
            "error": self.error,
            "path": str(self.path) if self.path is not None else None,
        }


class DownloadPaths(list):
    """List of usable paths returned by :func:`download`.

    It behaves exactly like the plain ``list[Path]`` returned before this
    module gained per-day reporting, so existing callers keep working. The
    per-day audit records are available on :attr:`details`.
    """

    def __init__(
        self,
        paths: list[Path] | tuple[Path, ...] = (),
        details: list[DayDownloadResult] | None = None,
    ) -> None:
        super().__init__(paths)
        self.details: list[DayDownloadResult] = list(details or [])

    @property
    def results(self) -> list[DayDownloadResult]:
        """Alias for :attr:`details`."""
        return self.details


def _build_tardis_url(exchange: str, data_type: str, dt: date, symbol: str) -> str:
    """Build a direct Tardis.dev datasets download URL.

    URL format: https://datasets.tardis.dev/v1/{exchange}/{data_type}/{YYYY}/{MM}/{DD}/{SYMBOL}.csv.gz
    """
    return (
        f"{TARDIS_DATASETS_URL}/{exchange}/{data_type}"
        f"/{dt.year:04d}/{dt.month:02d}/{dt.day:02d}/{symbol}.csv.gz"
    )


def _tardis_day_path(
    exchange: str, data_type: str, dt: date, symbol: str, output_dir: Path
) -> Path:
    """Return the canonical output path for one day of Tardis data."""
    date_str = dt.strftime("%Y-%m-%d")
    return output_dir / f"{exchange}_{data_type}_{date_str}_{symbol}.csv.gz"


def _atomic_write_bytes(out_path: Path, content: bytes) -> None:
    """Write ``content`` to ``out_path`` atomically.

    Data is written to a temporary file in the same directory and only
    renamed onto ``out_path`` after it has been fully written (and fsynced).
    Any failure removes the temporary file, so a partially written file can
    never be mistaken for a completed download on the next run.
    """
    fd, tmp_name = tempfile.mkstemp(
        dir=str(out_path.parent),
        prefix=f".{out_path.name}.",
        suffix=".part",
    )
    try:
        try:
            fh = os.fdopen(fd, "wb")
        except BaseException:
            # fdopen failed, so the descriptor is still ours to close; do it
            # before unlinking, or Windows would keep the temp file locked.
            with contextlib.suppress(OSError):
                os.close(fd)
            fd = -1
            raise
        fd = -1  # the file object now owns (and closes) the descriptor
        with fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, out_path)
    finally:
        if fd >= 0:  # pragma: no cover - defensive
            with contextlib.suppress(OSError):
                os.close(fd)
        # `tmp_name` is gone after a successful replace; this only cleans up
        # after a write/rename failure.
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)


def _http_failure_reason(status_code: int, exchange: str, symbol: str, date_str: str) -> str:
    """Build a human-readable failure reason for a non-200 response."""
    if status_code == 401:
        return (
            "HTTP 401 Unauthorized — free data is only available for the 1st "
            "of each month; provide an API key via --tardis-api-key or the "
            "TARDIS_API_KEY environment variable"
        )
    if status_code == 404:
        return f"HTTP 404 Not Found — {exchange} {symbol} may not be available on {date_str}"
    return f"HTTP {status_code}"


def _download_tardis_day_detailed(
    exchange: str,
    data_type: str,
    dt: date,
    symbol: str,
    output_dir: Path,
    api_key: str = "",
    timeout: int = 300,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_delay: float = DEFAULT_RETRY_DELAY,
) -> DayDownloadResult:
    """Download one day and return a detailed per-day record.

    Retries are bounded and only applied to transient failures:
    ``requests.RequestException`` and HTTP 5xx responses. Any 4xx response
    fails immediately without retrying.
    """
    out_path = _tardis_day_path(exchange, data_type, dt, symbol, output_dir)
    date_str = dt.strftime("%Y-%m-%d")

    if out_path.exists():
        logger.info("Already downloaded: %s", out_path.name)
        return DayDownloadResult(
            date=dt,
            status=DownloadStatus.EXISTING,
            attempts=0,
            path=out_path,
        )

    url = _build_tardis_url(exchange, data_type, dt, symbol)
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    max_retries = max(0, int(max_retries))
    retry_delay = max(0.0, float(retry_delay))
    total_attempts = max_retries + 1

    reason = "download failed"
    attempts = 0

    for attempt in range(1, total_attempts + 1):
        attempts = attempt
        logger.info("Downloading %s (attempt %d/%d) ...", url, attempt, total_attempts)

        retryable = False
        try:
            resp = requests.get(url, headers=headers, timeout=timeout, stream=True)
            status_code = int(resp.status_code)
        except requests.RequestException as exc:
            reason = f"network error: {type(exc).__name__}: {exc}"
            retryable = True
        except Exception as exc:  # pragma: no cover - defensive boundary
            reason = f"unexpected error: {type(exc).__name__}: {exc}"
        else:
            if status_code == 200:
                try:
                    content = resp.content
                except requests.RequestException as exc:
                    reason = f"network error while reading response: {type(exc).__name__}: {exc}"
                    retryable = True
                else:
                    try:
                        _atomic_write_bytes(out_path, content)
                    except Exception as exc:
                        # A local write failure is not transient network
                        # trouble; retrying the HTTP request would not help.
                        reason = f"write failed: {type(exc).__name__}: {exc}"
                        logger.error("Tardis write failed for %s: %s", date_str, reason)
                        return DayDownloadResult(
                            date=dt,
                            status=DownloadStatus.FAILED,
                            attempts=attempt,
                            error=reason,
                        )

                    size_mb = len(content) / (1024 * 1024)
                    logger.info("Saved: %s (%.1f MB)", out_path.name, size_mb)
                    return DayDownloadResult(
                        date=dt,
                        status=DownloadStatus.DOWNLOADED,
                        attempts=attempt,
                        path=out_path,
                    )

            reason = _http_failure_reason(status_code, exchange, symbol, date_str)
            retryable = 500 <= status_code <= 599

        if retryable and attempt < total_attempts:
            logger.warning(
                "Tardis request for %s failed (attempt %d/%d): %s; retrying in %.1fs",
                date_str,
                attempt,
                total_attempts,
                reason,
                retry_delay,
            )
            if retry_delay > 0:
                time.sleep(retry_delay)
            continue

        logger.error(
            "Tardis download failed for %s after %d attempt(s): %s",
            date_str,
            attempt,
            reason,
        )
        break

    return DayDownloadResult(
        date=dt,
        status=DownloadStatus.FAILED,
        attempts=attempts,
        error=reason,
    )


def _download_tardis_day(
    exchange: str,
    data_type: str,
    dt: date,
    symbol: str,
    output_dir: Path,
    api_key: str = "",
    timeout: int = 300,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_delay: float = DEFAULT_RETRY_DELAY,
    report: list[DayDownloadResult] | None = None,
) -> Path | None:
    """Download a single day of Tardis data via direct HTTP.

    Args:
        exchange: Tardis exchange identifier (e.g. 'bybit').
        data_type: Tardis data type (e.g. 'book_snapshot_25').
        dt: Date to download.
        symbol: Trading pair (e.g. 'BTCUSDT').
        output_dir: Directory to save the file.
        api_key: Tardis API key (empty for free 1st-of-month data).
        timeout: Request timeout in seconds.
        max_retries: Retries after the initial attempt for transient
            failures (network errors / HTTP 5xx).
        retry_delay: Seconds to wait between attempts.
        report: Optional list that receives a :class:`DayDownloadResult`
            describing this day's outcome.

    Returns:
        Path to the file when it exists or was downloaded, or None if the
        download failed. The detailed outcome is appended to ``report`` when
        provided.
    """
    result = _download_tardis_day_detailed(
        exchange=exchange,
        data_type=data_type,
        dt=dt,
        symbol=symbol,
        output_dir=output_dir,
        api_key=api_key,
        timeout=timeout,
        max_retries=max_retries,
        retry_delay=retry_delay,
    )
    if report is not None:
        report.append(result)
    return result.path


def download(
    symbol: str,
    start: date | str,
    end: date | str,
    output_dir: Path | None = None,
    exchange: str = "bybit",
    data_type: str = "book_snapshot_25",
    api_key: str = "",
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_delay: float = DEFAULT_RETRY_DELAY,
    details_out: list[DayDownloadResult] | None = None,
) -> list[Path]:
    """Download order book data via Tardis.dev using direct HTTP.

    Downloads pre-reconstructed L2 order book snapshots as compressed
    CSV files. No SDK installation required — uses the Tardis datasets
    HTTP API directly.

    Free sample data (1st of each month) is available without an API key.
    For other dates, provide an API key from https://tardis.dev.

    Each day is resolved to exactly one of three outcomes: the file already
    existed (no request made), it was newly downloaded and atomically
    written, or it failed after the configured retries. The audit trail is
    available on the returned list's ``details`` attribute and/or appended
    to ``details_out``.

    Args:
        symbol: Trading pair (e.g. 'BTCUSDT').
        start: Start date (inclusive).
        end: End date (inclusive).
        output_dir: Directory to save files. Defaults to data/raw/.
        exchange: Exchange name (bybit, binance, okx, deribit).
        data_type: Tardis data type. Recommended:
            'book_snapshot_25' — top 25 levels per side, snapshot on every change
            'book_snapshot_5'  — top 5 levels (smaller files)
            'incremental_book_L2' — raw incremental updates
        api_key: Tardis API key. Empty string uses free sample data
            (only 1st of each month available).
        max_retries: Retries after an initial attempt for network errors
            and HTTP 5xx responses (4xx is never retried).
        retry_delay: Seconds between attempts.
        details_out: Optional list that receives one
            :class:`DayDownloadResult` per date in the range.

    Returns:
        List of paths to usable CSV files. The concrete value is a
        :class:`DownloadPaths` (a ``list`` subclass) whose ``details``
        attribute holds the per-day records.
    """
    if isinstance(start, str):
        start = datetime.strptime(start, "%Y-%m-%d").date()
    if isinstance(end, str):
        end = datetime.strptime(end, "%Y-%m-%d").date()

    if end < start:
        raise ValueError(f"end ({end}) must be >= start ({start})")

    if output_dir is None:
        output_dir = DEFAULT_RAW_DIR
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    tardis_exchange = TARDIS_EXCHANGE_MAP.get(exchange, exchange)

    logger.info(
        "Downloading %s %s from Tardis.dev (%s, %s to %s) ...",
        tardis_exchange,
        symbol,
        data_type,
        start.strftime("%Y-%m-%d"),
        end.strftime("%Y-%m-%d"),
    )
    if not api_key:
        # Check if any requested dates are NOT 1st of month
        non_free = []
        current = start
        while current <= end:
            if current.day != 1:
                non_free.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=1)
        if non_free:
            logger.warning(
                "No API key provided — only the 1st of each month is free. "
                "These dates will likely fail: %s. "
                "Get an API key at https://tardis.dev",
                ", ".join(non_free[:5]) + ("..." if len(non_free) > 5 else ""),
            )
        else:
            logger.info("No API key — using free sample data (1st of each month).")

    paths = []
    details: list[DayDownloadResult] = []
    current = start
    while current <= end:
        day_report: list[DayDownloadResult] = []
        existed_before = _tardis_day_path(
            tardis_exchange, data_type, current, symbol, output_dir
        ).exists()
        path = _download_tardis_day(
            exchange=tardis_exchange,
            data_type=data_type,
            dt=current,
            symbol=symbol,
            output_dir=output_dir,
            api_key=api_key,
            max_retries=max_retries,
            retry_delay=retry_delay,
            report=day_report,
        )
        if day_report:
            result = day_report[0]
        elif path is None:
            # Only reachable when _download_tardis_day is replaced/mocked and
            # does not emit a report.
            result = DayDownloadResult(
                date=current,
                status=DownloadStatus.FAILED,
                attempts=1,
                error="download failed",
            )
        else:
            result = DayDownloadResult(
                date=current,
                status=(DownloadStatus.EXISTING if existed_before else DownloadStatus.DOWNLOADED),
                attempts=0 if existed_before else 1,
                path=path,
            )

        details.append(result)
        if path is not None:
            paths.append(path)
        current += timedelta(days=1)

    if details_out is not None:
        details_out.extend(details)

    existing = sum(d.status == DownloadStatus.EXISTING for d in details)
    downloaded = sum(d.status == DownloadStatus.DOWNLOADED for d in details)
    failed = sum(d.status == DownloadStatus.FAILED for d in details)
    logger.info(
        "Tardis range complete for %s: %d/%d usable (%d downloaded, %d already present, %d failed)",
        symbol,
        existing + downloaded,
        len(details),
        downloaded,
        existing,
        failed,
    )
    for result in details:
        if result.status == DownloadStatus.FAILED:
            logger.error(
                "Day %s failed after %d attempt(s): %s",
                result.date_str,
                result.attempts,
                result.error,
            )

    return DownloadPaths(paths, details)


# Backwards-compatible alias
download_tardis = download


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Download L2 orderbook data from Tardis.dev",
        epilog=(
            "Examples:\n"
            "  # Free sample (1st of each month, no key needed):\n"
            "  python data/download.py --symbol BTCUSDT "
            "--start 2024-01-01 --end 2024-01-01\n\n"
            "  # With API key (any date):\n"
            "  python data/download.py --symbol BTCUSDT "
            "--start 2024-06-15 --end 2024-06-21 "
            "--tardis-api-key YOUR_KEY\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--symbol", default="BTCUSDT", help="Trading pair")
    parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--output-dir", default=None, help="Output directory")
    parser.add_argument(
        "--exchange",
        default="bybit",
        help="Exchange name (default: bybit)",
    )
    parser.add_argument(
        "--data-type",
        default="book_snapshot_25",
        choices=["book_snapshot_25", "book_snapshot_5", "incremental_book_L2"],
        help="Tardis data type (default: book_snapshot_25)",
    )
    parser.add_argument(
        "--tardis-api-key",
        default="",
        help="Tardis.dev API key (omit for free sample data: 1st of each month)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help=(
            "Retries per day for network errors and HTTP 5xx responses "
            f"(default: {DEFAULT_MAX_RETRIES})"
        ),
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=DEFAULT_RETRY_DELAY,
        help=(f"Seconds to wait between attempts (default: {DEFAULT_RETRY_DELAY})"),
    )

    args = parser.parse_args()
    output_dir = Path(args.output_dir) if args.output_dir else None
    api_key = args.tardis_api_key or os.environ.get("TARDIS_API_KEY", "")

    result = download(
        args.symbol,
        args.start,
        args.end,
        output_dir,
        exchange=args.exchange,
        data_type=args.data_type,
        api_key=api_key,
        max_retries=args.max_retries,
        retry_delay=args.retry_delay,
    )

    print(f"\nPer-day results ({len(result.details)} day(s)):")
    for detail in result.details:
        print(
            f"  {detail.date_str}  {detail.status.value:<10}  "
            f"attempts={detail.attempts}" + (f"  error={detail.error}" if detail.error else "")
        )

    if any(detail.status == DownloadStatus.FAILED for detail in result.details):
        raise SystemExit(1)
