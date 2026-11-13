"""Result types for scraper calls that can succeed only partially.

:class:`HistoricalFetchResult` is returned by
:meth:`psxdata.scrapers.historical.HistoricalScraper.fetch_report`. Unlike a
bare DataFrame it records *what was actually obtained*: whether the request
fully succeeded, the delivered date range, the failure reason when one exists,
and a human-readable conclusion that can be logged or checked.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

import pandas as pd


class HistoricalOutcome(str, Enum):
    """How a single-symbol historical fetch ended.

    Values compare equal to their plain string form (``outcome == "complete"``).
    """

    COMPLETE = "complete"   # request succeeded and all parsed rows were delivered
    PARTIAL = "partial"     # rows delivered, but the request/fetch was not clean
    FAILED = "failed"       # no rows could be delivered; ``failure_reason`` says why
    NO_DATA = "no_data"     # HTTP 200 with no parseable rows — PSX has no data


@dataclass(frozen=True, eq=False)
class HistoricalFetchResult:
    """Outcome of one historical fetch for a single PSX symbol.

    Attributes:
        symbol: PSX ticker the fetch was made for.
        data: DataFrame with columns ``date, open, high, low, close, volume,
            is_anomaly``, sorted by date ascending, already run through
            :func:`psxdata.utils.validate_ohlc_dataframe`. May be empty.
        complete: ``True`` only when the request succeeded cleanly and every
            parsed row was delivered. A retry that recovered, a partial
            response, a filter that removed everything, and an empty response
            are all ``False``.
        outcome: One of :class:`HistoricalOutcome`.
        first_date: Earliest date actually delivered, or ``None`` if empty.
        last_date: Latest date actually delivered, or ``None`` if empty.
        message: Human-readable conclusion, safe to log.
        failure_reason: Short machine-friendly explanation when the fetch was
            not clean (network error, 5xx, missing columns, ...); ``None`` on
            complete success.
        attempts: Number of HTTP attempts made, retries included.
        rows_parsed: Raw rows parsed from the response, before filtering and
            validation.
        raw_columns: Normalized column names the parsed table actually had.
        error: The exception that caused a ``FAILED`` outcome, if any; ``None``
            otherwise. :meth:`HistoricalScraper.fetch` re-raises this.
    """

    symbol: str
    data: pd.DataFrame
    complete: bool
    outcome: HistoricalOutcome
    first_date: date | None
    last_date: date | None
    message: str
    failure_reason: str | None = None
    attempts: int = 1
    rows_parsed: int = 0
    raw_columns: frozenset[str] = field(default_factory=frozenset)
    error: Exception | None = field(default=None, repr=False, compare=False)

    # -- aliases so callers can use the vocabulary that fits their code -----

    @property
    def df(self) -> pd.DataFrame:
        """Alias for :attr:`data`."""
        return self.data

    @property
    def frame(self) -> pd.DataFrame:
        """Alias for :attr:`data`."""
        return self.data

    @property
    def success(self) -> bool:
        """Alias for :attr:`complete`."""
        return self.complete

    @property
    def is_complete(self) -> bool:
        """Alias for :attr:`complete`."""
        return self.complete

    @property
    def conclusion(self) -> str:
        """Alias for :attr:`message`."""
        return self.message

    @property
    def earliest_date(self) -> date | None:
        """Alias for :attr:`first_date`."""
        return self.first_date

    @property
    def latest_date(self) -> date | None:
        """Alias for :attr:`last_date`."""
        return self.last_date

    @property
    def date_range(self) -> tuple[date | None, date | None]:
        """``(first_date, last_date)``."""
        return (self.first_date, self.last_date)

    @property
    def empty(self) -> bool:
        """Whether the delivered DataFrame has no rows."""
        return self.data.empty

    def __repr__(self) -> str:  # keep logs compact — no DataFrame dump
        return (
            f"HistoricalFetchResult(symbol={self.symbol!r}, "
            f"outcome={self.outcome.value!r}, rows={len(self.data)}, "
            f"range={self.first_date}..{self.last_date}, complete={self.complete})"
        )
