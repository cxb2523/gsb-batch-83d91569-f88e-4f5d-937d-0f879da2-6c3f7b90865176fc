"""Pydantic v2 data models for psxdata.

Thin models — types and required fields only. No business logic validators.
OHLC constraint validation lives in utils.validate_ohlc_dataframe.

All models use strict=False to allow coercion from strings
(scrapers pass raw parsed cell values).
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class OHLCVRow(BaseModel):
    """Single OHLCV candlestick row from PSX historical data."""

    model_config = ConfigDict(strict=False)

    date: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class Quote(BaseModel):
    """Real-time quote snapshot from /trading-panel."""

    model_config = ConfigDict(strict=False)

    symbol: str
    price: float
    change: float
    change_pct: float
    volume: int
    timestamp: datetime


class IndexRecord(BaseModel):
    """Index snapshot from /indices."""

    model_config = ConfigDict(strict=False)

    name: str
    current: float
    high: float
    low: float
    change: float
    change_pct: float


class SectorSummary(BaseModel):
    """Sector-level aggregate row from /sector-summary."""

    model_config = ConfigDict(strict=False)

    code: str
    name: str
    advance: int
    decline: int
    unchanged: int
    turnover: int
    market_cap_b: float


class TickerInfo(BaseModel):
    """Screener row from /screener — one listed stock."""

    model_config = ConfigDict(strict=False)

    symbol: str
    sector: str
    listed_in: str
    market_cap: float | None
    price: float
    pe_ratio: float | None       # missing for some tickers
    dividend_yield: float | None  # missing for some tickers


class DebtInstrument(BaseModel):
    """Debt market instrument from /debt-market."""

    model_config = ConfigDict(strict=False)

    security_code: str
    name: str
    face_value: float
    maturity_date: datetime | None  # None for perpetual instruments
    coupon_rate: float


class EligibleScrip(BaseModel):
    """Margin-trading eligible stock from /eligible-scrips."""

    model_config = ConfigDict(strict=False)

    symbol: str
    name: str
