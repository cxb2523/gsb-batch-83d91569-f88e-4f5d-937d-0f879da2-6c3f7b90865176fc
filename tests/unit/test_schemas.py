"""Unit tests for psxdata/models/schemas.py."""
from datetime import datetime

import pytest

from psxdata.models.schemas import (
    DebtInstrument,
    EligibleScrip,
    IndexRecord,
    OHLCVRow,
    Quote,
    SectorSummary,
    TickerInfo,
)


class TestOHLCVRow:
    def test_valid_instantiation(self):
        row = OHLCVRow(
            date=datetime(2024, 1, 5),
            open=481.99,
            high=496.0,
            low=474.01,
            close=485.38,
            volume=4496408,
        )
        assert row.close == pytest.approx(485.38)

    def test_coerces_string_numerics(self):
        row = OHLCVRow(
            date="2024-01-05",
            open="481.99",
            high="496.00",
            low="474.01",
            close="485.38",
            volume="4496408",
        )
        assert isinstance(row.open, float)
        assert isinstance(row.volume, int)

    def test_coerces_string_date(self):
        row = OHLCVRow(
            date="2024-01-05",
            open=100.0, high=110.0, low=90.0, close=105.0, volume=1000,
        )
        assert isinstance(row.date, datetime)


class TestQuote:
    def test_valid_instantiation(self):
        q = Quote(
            symbol="ENGRO",
            price=481.99,
            change=-5.0,
            change_pct=-1.03,
            volume=4496408,
            timestamp=datetime(2024, 1, 5, 15, 30),
        )
        assert q.symbol == "ENGRO"


class TestIndexRecord:
    def test_valid_instantiation(self):
        r = IndexRecord(
            name="KSE100",
            current=150398.71,
            high=152103.62,
            low=148796.54,
            change=-1612.55,
            change_pct=-1.06,
        )
        assert r.name == "KSE100"


class TestSectorSummary:
    def test_valid_instantiation(self):
        s = SectorSummary(
            code="0801",
            name="AUTOMOBILE ASSEMBLER",
            advance=1,
            decline=9,
            unchanged=0,
            turnover=1575747,
            market_cap_b=622.67,
        )
        assert s.code == "0801"


class TestTickerInfo:
    def test_valid_instantiation(self):
        t = TickerInfo(
            symbol="ENGRO",
            sector="FERTILIZER",
            listed_in="ALLSHR",
            market_cap=1.0e9,
            price=481.99,
            pe_ratio=12.5,
            dividend_yield=3.2,
        )
        assert t.symbol == "ENGRO"

    def test_nullable_fields_accept_none(self):
        t = TickerInfo(
            symbol="XYZ",
            sector="UNKNOWN",
            listed_in="ALLSHR",
            market_cap=None,
            price=10.0,
            pe_ratio=None,
            dividend_yield=None,
        )
        assert t.pe_ratio is None
        assert t.dividend_yield is None


class TestDebtInstrument:
    def test_valid_instantiation(self):
        d = DebtInstrument(
            security_code="P01GIS080227",
            name="1 Year GIS",
            face_value=5000.0,
            maturity_date=datetime(2027, 2, 8),
            coupon_rate=0.0,
        )
        assert d.security_code == "P01GIS080227"

    def test_perpetual_instrument_no_maturity(self):
        d = DebtInstrument(
            security_code="PERP001",
            name="Perpetual Bond",
            face_value=1000.0,
            maturity_date=None,
            coupon_rate=5.0,
        )
        assert d.maturity_date is None


class TestEligibleScrip:
    def test_valid_instantiation(self):
        e = EligibleScrip(symbol="ENGRO", name="Engro Corporation Limited")
        assert e.symbol == "ENGRO"
