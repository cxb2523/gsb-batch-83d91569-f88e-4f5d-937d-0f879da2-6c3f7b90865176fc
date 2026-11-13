"""psxdata — Python library for Pakistan Stock Exchange data."""
from psxdata.client import (
    PSXClient,
    configure,
    debt_market,
    eligible_scrips,
    fundamentals,
    indices,
    quote,
    screener,
    sectors,
    stocks,
    stocks_report,
    symbols,
    tickers,
)
from psxdata.models.results import HistoricalFetchResult, HistoricalOutcome
from psxdata.scrapers.base import BaseScraper
from psxdata.scrapers.historical import HistoricalScraper

__version__ = "1.5.0"

__all__ = [
    "BaseScraper",
    "HistoricalScraper",
    "HistoricalFetchResult",
    "HistoricalOutcome",
    "PSXClient",
    "configure",
    "stocks",
    "stocks_report",
    "tickers",
    "quote",
    "indices",
    "sectors",
    "fundamentals",
    "debt_market",
    "eligible_scrips",
    "symbols",
    "screener",
]
