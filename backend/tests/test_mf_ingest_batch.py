"""
Tests for per-scheme ingestion status records and weekend-removal accounting
in app.domains.ingestion.mf_ingest.

All NAV payloads are fabricated locally; no external network calls are made
(the fetcher source methods are replaced with async fakes).
"""
import asyncio
from datetime import datetime

import pytest

from app.domains.ingestion import mf_ingest
from app.domains.ingestion.mf_ingest import (
    IngestionBatchResult,
    IngestionFailureReason,
    IngestionStatus,
    MFAPIFetcher,
)
from app.domains.ingestion.schemas import MutualFundNavResponse

MAX_RETRIES = 4  # must mirror mf_ingest.fetch_scheme


@pytest.fixture(autouse=True)
def no_retry_sleep(monkeypatch):
    """Neutralize backoff sleeps so retry paths run fast."""
    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(mf_ingest.asyncio, "sleep", fake_sleep)


def make_scheme_item(scheme_code, scheme_type="Open Ended Schemes", isin="INF123456789"):
    return {
        "scheme_code": scheme_code,
        "scheme_name": "Test Flexi Cap Fund - Direct Plan - Growth",
        "scheme_category": "Equity Scheme - Flexi Cap Fund",
        "fund_house": "Test Mutual Fund",
        "scheme_type": scheme_type,
        "isin_code": isin,
    }


def make_nav_rows(dates):
    return [{"date": d, "nav": f"{100.0 + i:.2f}"} for i, d in enumerate(dates)]


def make_raw_payload(scheme_code, nav_rows):
    """MFAPI-shaped raw payload for one scheme."""
    return {
        "meta": {
            "scheme_name": "Test Flexi Cap Fund - Direct Plan - Growth",
            "scheme_category": "Equity Scheme - Flexi Cap Fund",
            "fund_house": "Test Mutual Fund",
            "scheme_code": scheme_code,
            "scheme_type": "Open Ended Schemes",
            "isin_growth": "INF123456789",
        },
        "data": nav_rows,
    }


def make_fetcher(mfapi_handler, captnemo_handler=None):
    """MFAPIFetcher with both NAV sources replaced by local async fakes."""
    fetcher = MFAPIFetcher()

    async def fake_mfapi(session, scheme_code):
        return mfapi_handler(scheme_code)

    async def fake_captnemo(session, isin_code, scheme_item):
        if captnemo_handler is None:
            return None
        return captnemo_handler(isin_code, scheme_item)

    fetcher._fetch_scheme_raw_from_mfapi = fake_mfapi
    fetcher._fetch_scheme_raw_from_captnemo = fake_captnemo
    return fetcher


def run_batch(fetcher, schemes):
    return asyncio.run(fetcher.fetch_schemes_from_list(schemes))


# A full local week: Mon 02-11-2026 .. Sun 08-11-2026 (07/08 are Sat/Sun).
WEEKDATES = [
    "02-11-2026", "03-11-2026", "04-11-2026", "05-11-2026",
    "06-11-2026", "07-11-2026", "08-11-2026",
]
EXPECTED_WEEKEND = {"2026-11-07", "2026-11-08"}


def test_weekday_assumptions_hold():
    weekends = {
        datetime.strptime(d, "%d-%m-%Y").strftime("%Y-%m-%d")
        for d in WEEKDATES
        if datetime.strptime(d, "%d-%m-%Y").weekday() >= 5
    }
    assert weekends == EXPECTED_WEEKEND


def test_single_failure_is_recorded_and_not_silently_dropped():
    ok_code, fail_code, closed_code = 100001, 100002, 100003
    schemes = [
        make_scheme_item(ok_code),
        make_scheme_item(fail_code, isin="INF000000002"),
        make_scheme_item(closed_code, scheme_type="Close Ended Schemes"),
    ]

    def mfapi_handler(scheme_code):
        if scheme_code == ok_code:
            return make_raw_payload(ok_code, make_nav_rows(WEEKDATES[:5]))
        return None  # primary source fails for the other scheme

    fetcher = make_fetcher(mfapi_handler)  # captnemo fallback also fails
    batch = run_batch(fetcher, schemes)

    assert isinstance(batch, IngestionBatchResult)

    # Success list contains only the successful scheme.
    assert [item["meta"]["scheme_code"] for item in batch.successful] == [ok_code]

    # The failed scheme has an auditable record with reason and retry count.
    failed_by_code = {r.scheme_code: r for r in batch.failed}
    assert set(failed_by_code) == {fail_code, closed_code}

    fail_rec = failed_by_code[fail_code]
    assert fail_rec.status == IngestionStatus.FAILED
    assert fail_rec.reason == IngestionFailureReason.BOTH_SOURCES_FAILED
    assert fail_rec.retry_count == MAX_RETRIES - 1

    # Non-open-ended scheme is reported as skipped, not fetched.
    skip_rec = failed_by_code[closed_code]
    assert skip_rec.status == IngestionStatus.SKIPPED
    assert skip_rec.reason == IngestionFailureReason.NON_OPEN_ENDED
    assert skip_rec.retry_count == 0

    # Failed/skipped schemes must not appear in the success list.
    success_codes = {item["meta"]["scheme_code"] for item in batch.successful}
    assert fail_code not in success_codes
    assert closed_code not in success_codes

    summary = batch.summary()
    assert summary["total"] == 3
    assert summary["success"] == 1
    assert summary["failed"] == 1
    assert summary["skipped"] == 1
    assert summary["failure_reasons"][IngestionFailureReason.BOTH_SOURCES_FAILED] == 1


def test_all_failures_yield_empty_success_list_and_full_failure_records():
    schemes = [make_scheme_item(200001), make_scheme_item(200002, isin="INF000000003")]

    fetcher = make_fetcher(lambda scheme_code: None)  # both sources fail for all
    batch = run_batch(fetcher, schemes)

    assert batch.successful == []
    assert len(batch) == 0
    assert list(batch) == []

    assert len(batch.failed) == 2
    for record in batch.failed:
        assert record.status == IngestionStatus.FAILED
        assert record.reason == IngestionFailureReason.BOTH_SOURCES_FAILED
        assert record.retry_count == MAX_RETRIES - 1
        assert record.scheme_code in {200001, 200002}

    summary = batch.summary()
    assert summary["success"] == 0
    assert summary["failed"] == 2


def test_weekend_removal_counts_are_consistent_with_final_data():
    scheme_code = 300001
    schemes = [make_scheme_item(scheme_code)]

    def mfapi_handler(code):
        return make_raw_payload(code, make_nav_rows(WEEKDATES))

    fetcher = make_fetcher(mfapi_handler)
    batch = run_batch(fetcher, schemes)

    assert len(batch.successful) == 1
    result = batch.successful[0]

    # Counts exist and agree with the actual payload.
    assert result["removed_weekend_count"] == len(result["removed_weekend_dates"]) == 2
    assert result["kept_nav_count"] == len(result["data"]) == 5
    assert result["kept_nav_count"] + result["removed_weekend_count"] == len(WEEKDATES)
    assert set(result["removed_weekend_dates"]) == EXPECTED_WEEKEND

    # No weekend date survives in the final NAV series.
    for point in result["data"]:
        parsed = datetime.strptime(point["date"], "%Y-%m-%d")
        assert parsed.weekday() < 5

    # meta/data still pass the response schema; enrichment fields stay hidden
    # while MF_ENRICHMENT_ENABLED is False.
    validated = MutualFundNavResponse.model_validate(
        {k: result[k] for k in ("meta", "data", "removed_weekend_dates")}
    )
    assert validated.meta.scheme_code == scheme_code
    for field_name in mf_ingest.MFDATA_ENRICHMENT_META_FIELDS:
        assert field_name not in result["meta"]

    # The success record carries retry bookkeeping too.
    record = next(r for r in batch.records if r.scheme_code == scheme_code)
    assert record.status == IngestionStatus.SUCCESS
    assert record.retry_count == 0
