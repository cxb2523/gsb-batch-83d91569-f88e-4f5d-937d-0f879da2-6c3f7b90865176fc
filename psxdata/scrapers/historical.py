"""HistoricalScraper — OHLCV price history for a single PSX symbol.

Endpoint:  POST https://dps.psx.com.pk/historical
Method:    POST with form data {symbol: <ticker>}
Mode:      requests + BeautifulSoup (plain HTTP AJAX)

Quirk:     PSX ignores date params server-side — the POST always returns ALL
           available history for the symbol. Date filtering is applied in memory
           after the response is parsed.

Two entry points:
  - :meth:`HistoricalScraper.fetch` returns a bare DataFrame and raises when
    nothing could be delivered (backwards-compatible).
  - :meth:`HistoricalScraper.fetch_report` returns a
    :class:`~psxdata.models.results.HistoricalFetchResult` that also states
    whether the fetch fully succeeded, which dates were actually delivered,
    and why a degraded fetch was degraded. Use it when partial data is
    preferable to no data.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

import pandas as pd
import requests
from bs4 import BeautifulSoup

from psxdata.exceptions import (
    PSXMissingColumnsError,
    PSXServerError,
    PSXUnavailableError,
)
from psxdata.models.results import HistoricalFetchResult, HistoricalOutcome
from psxdata.parsers.html import extract_table_headers, parse_html_table
from psxdata.parsers.normalizers import coerce_numeric, parse_date_safely
from psxdata.scrapers.base import AttemptObserver, BaseScraper, RequestAttempt
from psxdata.utils import validate_ohlc_dataframe

logger = logging.getLogger(__name__)

OHLCV_COLUMNS: tuple[str, ...] = ("date", "open", "high", "low", "close", "volume")
# Columns validate_ohlc_dataframe requires. ``date`` is needed to sort/filter.
REQUIRED_COLUMNS: frozenset[str] = frozenset(OHLCV_COLUMNS)


def _empty_frame() -> pd.DataFrame:
    """The canonical empty historical frame (same columns as a populated one)."""
    return pd.DataFrame(columns=[*OHLCV_COLUMNS, "is_anomaly"])


def _coerce_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Build a typed frame from raw parsed rows, before date filtering.

    Applies the same coercions as :meth:`HistoricalScraper.fetch`:
    ``date`` via :func:`parse_date_safely`, prices via :func:`coerce_numeric`
    to float, volume to nullable ``Int64``. Rows whose date cannot be parsed
    are dropped.
    """
    df = pd.DataFrame(rows)
    df["date"] = df["date"].apply(parse_date_safely)
    for col in ("open", "high", "low", "close"):
        if col in df.columns:
            df[col] = df[col].apply(coerce_numeric).astype(float)
    if "volume" in df.columns:
        df["volume"] = df["volume"].apply(coerce_numeric)
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").astype("Int64")
    return df.dropna(subset=["date"]).reset_index(drop=True)


def _response_shape(html: str) -> tuple[bool, list[str]]:
    """Return ``(has_table, normalized_headers)`` for the first table in html.

    Used only to explain why a response yielded no rows (no table at all vs a
    table whose headers/rows are unusable), so it never raises.
    """
    try:
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table")
        if table is None:
            return False, []
        return True, extract_table_headers(table)
    except Exception:  # malformed HTML must not mask the real outcome
        return False, []


def _is_network_error(exc: Exception) -> bool:
    return isinstance(exc, requests.RequestException)


def _describe_attempts(attempts: list[RequestAttempt]) -> tuple[str, str]:
    """Summarise failed attempts as ``(reason_slug, human_text)``.

    The first failed attempt decides the slug. Returns ``("", "")`` when no
    attempt failed.
    """
    failed = [a for a in attempts if not a.succeeded]
    if not failed:
        return "", ""
    first = failed[0]
    count = len(failed)
    if first.error is not None and _is_network_error(first.error):
        text, slug = f"network error ({type(first.error).__name__})", "network_error"
    elif first.status_code is not None and first.status_code >= 500:
        text, slug = f"server error ({first.status_code})", "server_error_5xx"
    elif first.status_code == 429:
        text, slug = "rate limit (429)", "rate_limited"
    elif first.status_code in (401, 403):
        text, slug = f"auth error ({first.status_code})", "auth_error"
    elif first.status_code is not None:
        text, slug = f"HTTP {first.status_code}", "http_error"
    elif first.error is not None:
        text, slug = f"{type(first.error).__name__}: {first.error}", "http_error"
    else:  # pragma: no cover — defensive; every failed attempt has one of the above
        text, slug = "unknown error", "unknown_error"
    if count > 1:
        text += f" on {count} attempts"
    return slug, text


def _fmt_range(first: date | None, last: date | None) -> str:
    if first is None or last is None:
        return "no dates"
    return f"{first.isoformat()}..{last.isoformat()}"


class HistoricalScraper(BaseScraper):
    """Fetch OHLCV price history for a PSX-listed symbol."""

    def fetch(
        self,
        symbol: str,
        start: date | None = None,
        end: date | None = None,
    ) -> pd.DataFrame:
        """Fetch all available OHLCV history for symbol, optionally filtered.

        PSX returns ALL historical data in one POST regardless of any date
        parameters. Filtering is applied in memory after parsing.

        Thin wrapper over :meth:`fetch_report`: returns its DataFrame and
        re-raises the underlying error when nothing could be delivered, so
        callers that only want the frame keep the previous behaviour. When a
        fetch is degraded but rows were delivered, those rows are returned
        rather than thrown away. Use ``fetch_report`` to learn whether the
        data is complete.

        Args:
            symbol: PSX ticker (e.g. "ENGRO", "LUCK").
            start: First date (inclusive). None = no lower bound.
            end:   Last date (inclusive). None = no upper bound.

        Returns:
            DataFrame with columns: date, open, high, low, close, volume, is_anomaly,
            sorted by date ascending. Empty DataFrame if PSX returns no table data
            or none of the parsed rows pass validation / the date filter.

        Raises:
            ValueError: If start > end.
            PSXConnectionError: Network failure after retries.
            PSXServerError: 5xx after retries.
            PSXParseError: Malformed response (e.g. table missing required columns).
        """
        result = self.fetch_report(symbol, start=start, end=end)
        if result.outcome is HistoricalOutcome.FAILED and result.error is not None:
            raise result.error
        return result.data

    def fetch_report(
        self,
        symbol: str,
        start: date | None = None,
        end: date | None = None,
    ) -> HistoricalFetchResult:
        """Fetch historical data and report exactly what was obtained.

        The request goes through :meth:`BaseScraper._post` unchanged — same
        retry policy, rate limiter and ``X-Req-Id`` handling. Every attempt is
        observed on top, so the returned
        :class:`~psxdata.models.results.HistoricalFetchResult` can distinguish:

        ``COMPLETE``
            One clean attempt; every validated row was delivered.
        ``PARTIAL``
            Rows were delivered, but the fetch was not clean: an earlier
            attempt failed (network error, 5xx, ...) and a retry recovered,
            some parsed rows had unusable dates or were dropped by OHLC
            validation, or retries were exhausted but an earlier error
            response still carried a parseable table. The deliverable rows are
            kept and ``failure_reason`` / ``message`` say what went wrong.
        ``FAILED``
            Nothing could be delivered. ``failure_reason`` says whether the
            retries were exhausted on network errors / 5xx / another HTTP error,
            or the response was unusable (e.g. a table missing a required
            column). The exception is attached as ``error``;
            :meth:`fetch` re-raises it.
        ``NO_DATA``
            HTTP 200, but no parseable rows (no table, no headers, empty table,
            all dates unparseable), or every row was removed by the in-memory
            ``start``/``end`` filter or OHLC validation. The DataFrame is empty
            and the result says so instead of reporting success.

        Args:
            symbol: PSX ticker (e.g. "ENGRO", "LUCK").
            start: First date (inclusive). None = no lower bound.
            end:   Last date (inclusive). None = no upper bound.

        Returns:
            HistoricalFetchResult. ``data`` is sorted by date ascending and has
            passed ``validate_ohlc_dataframe``; it is empty when the outcome is
            ``FAILED`` or ``NO_DATA``.

        Raises:
            ValueError: If start > end (checked before any request). Transport
            failures do not raise here — they become ``FAILED`` results.
        """
        if start is not None and end is not None and start > end:
            raise ValueError(f"start ({start}) must be <= end ({end})")

        logger.debug("Fetching historical data for %s", symbol)
        attempts: list[RequestAttempt] = []
        observer: AttemptObserver = attempts.append

        try:
            resp = self._post("historical", data={"symbol": symbol}, on_attempt=observer)
        except Exception as exc:  # noqa: BLE001 — every transport error becomes a result
            return self._report_from_failure(symbol, exc, attempts, start, end)

        return self._report_from_response(symbol, resp.text, attempts, start, end)

    def fetch_with_report(
        self,
        symbol: str,
        start: date | None = None,
        end: date | None = None,
    ) -> HistoricalFetchResult:
        """Alias for :meth:`fetch_report` — same call, more explicit name."""
        return self.fetch_report(symbol, start=start, end=end)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _attempt_count(attempts: list[RequestAttempt]) -> int:
        """Retry attempts used. An ``X-Req-Id`` refresh retry keeps its number."""
        return max((a.number for a in attempts), default=1)

    @staticmethod
    def _describe_failure(exc: Exception, attempts: list[RequestAttempt]) -> str:
        """One clause naming the final failure, for the conclusion message.

        Combines the exception's own wording (e.g. "PSX unreachable after 3
        attempts") with the concrete cause seen on the wire (timeout, 503, ...),
        so the conclusion always names the failure kind.
        """
        slug, attempt_text = _describe_attempts(attempts)
        base = str(exc).strip()
        if not base:
            base = "PSX unreachable" if isinstance(exc, PSXUnavailableError) else type(exc).__name__
        if not attempt_text or attempt_text in base:
            return base
        # Avoid repeating a cause the exception message already names.
        status_codes = [a.status_code for a in attempts if a.status_code is not None]
        if any(str(code) in base for code in status_codes):
            return base
        if slug == "network_error" and any(
            type(a.error).__name__ in base for a in attempts if a.error is not None
        ):
            return base
        return f"{base} [{attempt_text}]"

    @staticmethod
    def _failure_reason(exc: Exception, attempts: list[RequestAttempt]) -> str:
        """Stable failure slug: ``network_error``, ``server_error_5xx``, ..."""
        slug, _ = _describe_attempts(attempts)
        if slug:
            return slug
        if isinstance(exc, PSXServerError):
            return "server_error_5xx"
        if isinstance(exc, PSXUnavailableError):
            return "network_error"
        return "http_error"

    def _deliver(
        self,
        rows: list[dict[str, Any]],
        start: date | None,
        end: date | None,
    ) -> tuple[pd.DataFrame, int, int]:
        """Coerce, filter and validate parsed rows.

        Returns ``(validated_or_empty, rows_unusable, rows_dropped)`` where
        ``rows_unusable`` were discarded for having no parseable date and
        ``rows_dropped`` were removed by :func:`validate_ohlc_dataframe`.
        """
        df = _coerce_frame(rows)
        rows_unusable = len(rows) - len(df)

        if start is not None:
            df = df[df["date"] >= pd.Timestamp(start)]
        if end is not None:
            df = df[df["date"] <= pd.Timestamp(end)]

        if df.empty:
            return _empty_frame(), rows_unusable, 0

        df = df.sort_values("date", kind="stable").reset_index(drop=True)
        validated = validate_ohlc_dataframe(df)
        validated = validated.sort_values("date", kind="stable").reset_index(drop=True)
        return validated, rows_unusable, len(df) - len(validated)

    def _report_from_failure(
        self,
        symbol: str,
        exc: Exception,
        attempts: list[RequestAttempt],
        start: date | None,
        end: date | None,
    ) -> HistoricalFetchResult:
        """Result for an exception raised by ``_post``.

        Retries may have received error responses whose bodies still contain a
        usable table (a 5xx proxy page, a truncated but parseable fragment).
        Those rows are salvaged and delivered as ``PARTIAL`` rather than
        discarded; if none are usable the result is ``FAILED``.
        """
        reason = self._failure_reason(exc, attempts)
        failure_text = self._describe_failure(exc, attempts)
        attempt_count = self._attempt_count(attempts)

        for attempt in reversed(attempts):
            if attempt.response is None:
                continue
            try:
                html = attempt.response.text
                rows = parse_html_table(html)
            except Exception:  # a broken response body must not mask the failure
                continue
            if not rows or REQUIRED_COLUMNS - set(rows[0].keys()):
                continue
            data, rows_unusable, rows_dropped = self._deliver(rows, start, end)
            if data.empty:
                continue
            first = data["date"].min()
            last = data["date"].max()
            first_date = first.date() if isinstance(first, pd.Timestamp) else first
            last_date = last.date() if isinstance(last, pd.Timestamp) else last
            message = (
                f"Partial: {symbol} delivered {len(data)} row(s) covering "
                f"{_fmt_range(first_date, last_date)}, salvaged from the body of "
                f"attempt {attempt.number} after {failure_text}; retries were "
                "exhausted. Parsed rows were retained."
            )
            logger.warning("%s", message)
            return HistoricalFetchResult(
                symbol=symbol,
                data=data,
                complete=False,
                outcome=HistoricalOutcome.PARTIAL,
                first_date=first_date,
                last_date=last_date,
                message=message,
                failure_reason=reason,
                attempts=attempt_count,
                rows_parsed=len(rows),
                raw_columns=frozenset(rows[0].keys()),
                error=exc,
            )

        message = (
            f"Failed: {symbol} historical data could not be fetched — "
            f"{failure_text}. No rows delivered."
        )
        logger.warning("%s", message)
        return HistoricalFetchResult(
            symbol=symbol,
            data=_empty_frame(),
            complete=False,
            outcome=HistoricalOutcome.FAILED,
            first_date=None,
            last_date=None,
            message=message,
            failure_reason=reason,
            attempts=attempt_count,
            rows_parsed=0,
            error=exc,
        )

    def _report_from_response(
        self,
        symbol: str,
        html: str,
        attempts: list[RequestAttempt],
        start: date | None,
        end: date | None,
    ) -> HistoricalFetchResult:
        rows = parse_html_table(html)
        attempt_count = self._attempt_count(attempts)
        failed_slug, failed_text = _describe_attempts(attempts)

        if not rows:
            has_table, headers = _response_shape(html)
            if not has_table:
                detail, reason = "the response contained no table", "no_table"
            elif not headers:
                detail, reason = "the response table had no headers", "no_table_headers"
            else:
                detail = f"the response table held no rows (columns: {', '.join(headers)})"
                reason = "empty_table"
            message = (
                f"No data: PSX returned HTTP 200 for {symbol} but {detail}. "
                "Empty DataFrame returned."
            )
            logger.warning("%s", message)
            return HistoricalFetchResult(
                symbol=symbol,
                data=_empty_frame(),
                complete=False,
                outcome=HistoricalOutcome.NO_DATA,
                first_date=None,
                last_date=None,
                message=message,
                failure_reason=reason,
                attempts=attempt_count,
                rows_parsed=0,
                raw_columns=frozenset(headers),
            )

        raw_columns = frozenset(rows[0].keys())
        missing = REQUIRED_COLUMNS - raw_columns
        if missing:
            exc = PSXMissingColumnsError(
                f"Historical response for {symbol} is missing column(s): "
                f"{', '.join(sorted(missing))}",
                missing=sorted(missing),
            )
            message = (
                f"Failed: PSX returned {len(rows)} row(s) for {symbol} but the table "
                f"is missing required column(s): {', '.join(sorted(missing))}. "
                "No validated rows can be delivered."
            )
            logger.warning("%s", message)
            return HistoricalFetchResult(
                symbol=symbol,
                data=_empty_frame(),
                complete=False,
                outcome=HistoricalOutcome.FAILED,
                first_date=None,
                last_date=None,
                message=message,
                failure_reason="missing_columns",
                attempts=attempt_count,
                rows_parsed=len(rows),
                raw_columns=raw_columns,
                error=exc,
            )

        data, rows_unusable, rows_dropped = self._deliver(rows, start, end)

        if data.empty:
            if len(rows) == rows_unusable:
                detail, reason = "none of the parsed rows had a usable date", "unparseable_dates"
            elif rows_unusable:
                detail = (
                    f"{rows_unusable} parsed row(s) had unusable dates and the rest "
                    f"fall outside the requested range [{start}..{end}]"
                )
                reason = "filtered_out"
            else:
                detail = (
                    f"{len(rows)} parsed row(s) exist but none fall in the "
                    f"requested range [{start}..{end}]"
                )
                reason = "filtered_out"
            message = (
                f"No data: PSX returned {len(rows)} row(s) for {symbol}, but {detail}. "
                "Empty DataFrame returned."
            )
            logger.warning("%s", message)
            return HistoricalFetchResult(
                symbol=symbol,
                data=_empty_frame(),
                complete=False,
                outcome=HistoricalOutcome.NO_DATA,
                first_date=None,
                last_date=None,
                message=message,
                failure_reason=reason,
                attempts=attempt_count,
                rows_parsed=len(rows),
                raw_columns=raw_columns,
            )

        first = data["date"].min()
        last = data["date"].max()
        first_date = first.date() if isinstance(first, pd.Timestamp) else first
        last_date = last.date() if isinstance(last, pd.Timestamp) else last

        degradations: list[str] = []
        if failed_slug:
            degradations.append(
                f"an earlier attempt failed with {failed_text} and a retry "
                f"recovered the data on attempt {attempt_count}"
            )
        if rows_unusable:
            degradations.append(f"{rows_unusable} row(s) had unusable dates and were dropped")
        if rows_dropped:
            degradations.append(f"{rows_dropped} row(s) were dropped by OHLC validation")

        if degradations:
            message = (
                f"Partial: {symbol} delivered {len(data)} row(s) covering "
                f"{_fmt_range(first_date, last_date)}, but {', and '.join(degradations)}. "
                "Parsed rows were retained."
            )
            reason_parts = ([failed_slug] if failed_slug else []) + (
                ["rows_dropped_by_validation"] if rows_dropped else []
            ) + (["unparseable_dates"] if rows_unusable else [])
            logger.warning("%s", message)
            return HistoricalFetchResult(
                symbol=symbol,
                data=data,
                complete=False,
                outcome=HistoricalOutcome.PARTIAL,
                first_date=first_date,
                last_date=last_date,
                message=message,
                failure_reason="; ".join(reason_parts),
                attempts=attempt_count,
                rows_parsed=len(rows),
                raw_columns=raw_columns,
            )

        message = (
            f"Complete: {symbol} fetched {len(data)} row(s) covering "
            f"{_fmt_range(first_date, last_date)} in {attempt_count} attempt(s)."
        )
        if start is not None or end is not None:
            message += f" Date filter applied: {start or 'none'}..{end or 'none'}."
        logger.debug("%s", message)
        return HistoricalFetchResult(
            symbol=symbol,
            data=data,
            complete=True,
            outcome=HistoricalOutcome.COMPLETE,
            first_date=first_date,
            last_date=last_date,
            message=message,
            failure_reason=None,
            attempts=attempt_count,
            rows_parsed=len(rows),
            raw_columns=raw_columns,
        )

