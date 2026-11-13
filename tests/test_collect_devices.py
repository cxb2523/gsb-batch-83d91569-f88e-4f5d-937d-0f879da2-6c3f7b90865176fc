"""Offline tests for scripts/collect_devices.py.

All network access is replaced by an injected fake fetcher returning
FetchResponse objects built from local HTML fixtures. Covers: success page,
missing-model page, non-Android page, 429-then-success, 429-exhausted,
non-200-no-retry, per-device exception isolation, and output merging.
"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from collect_devices import (  # noqa: E402
    CollectionSummary,
    DeviceFailure,
    DeviceInfo,
    FetchResponse,
    REASON_FETCH_FAILED,
    REASON_NOT_ANDROID,
    REASON_NO_MODEL,
    collect_brand,
    collect_brand_sync,
    fetch_with_retries,
    merge_summaries,
    parse_device_page,
    parse_device_page_detailed,
)


# ---------------------------------------------------------------------------
# HTML fixtures
# ---------------------------------------------------------------------------

SUCCESS_HTML = """
<html><body>
<h1 data-spec="modelname">Samsung Galaxy S23</h1>
<table>
  <tr><td data-spec="os">Android 13, upgradable to Android 14, One UI 6</td></tr>
  <tr><td data-spec="models">SM-S911B, SM-S911U</td></tr>
  <tr><td data-spec="year">2023, February 01</td></tr>
  <tr><td data-spec="cpu">Octa-core (1x3.36 GHz Cortex-X3)</td></tr>
  <tr><td data-spec="chipset">Qualcomm SM8550 Snapdragon 8 Gen 2</td></tr>
  <tr><td data-spec="internalmemory">128GB 8GB RAM, 256GB 8GB RAM</td></tr>
</table>
<span data-spec="ramsize-hl">8</span>
<li class="help-popularity">2,960,930 hits</li>
</body></html>
"""

NO_MODEL_HTML = """
<html><body>
<table>
  <tr><td data-spec="os">Android 13</td></tr>
  <tr><td data-spec="models">SM-S911B</td></tr>
</table>
</body></html>
"""

NOT_ANDROID_HTML = """
<html><body>
<h1 data-spec="modelname">Apple iPhone 15</h1>
<table>
  <tr><td data-spec="os">iOS 17, upgradable to iOS 17.4</td></tr>
</table>
</body></html>
"""

UNPARSEABLE_OS_HTML = """
<html><body>
<h1 data-spec="modelname">Mystery Phone</h1>
<table>
  <tr><td data-spec="os">Android, some custom skin</td></tr>
</table>
</body></html>
"""


# ---------------------------------------------------------------------------
# Fake fetcher
# ---------------------------------------------------------------------------

class FakeFetcher:
    """Returns queued FetchResponses per URL; records every call."""

    def __init__(self, routes):
        # routes: url -> list of FetchResponse; last one repeats if exhausted
        self.routes = {url: list(resps) for url, resps in routes.items()}
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        resps = self.routes[url]
        return resps.pop(0) if len(resps) > 1 else resps[0]


def ok(html=SUCCESS_HTML):
    return FetchResponse(status=200, body=html)


async def no_sleep(_seconds):
    return None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def test_parse_success_page_fields():
    device, reason = parse_device_page_detailed(SUCCESS_HTML, "samsung")
    assert reason is None
    assert device.model_code == "SM-S911B"
    assert device.name == "Samsung Galaxy S23"
    assert device.min_android_api == 33
    assert device.max_android_api == 34
    assert device.year == 2023
    assert device.cpu_cores == 8
    assert "Snapdragon" in device.chipset


def test_parse_missing_model_page():
    device, reason = parse_device_page_detailed(NO_MODEL_HTML, "samsung")
    assert device is None
    assert reason == REASON_NO_MODEL


def test_parse_non_android_page():
    device, reason = parse_device_page_detailed(NOT_ANDROID_HTML, "samsung")
    assert device is None
    assert reason == REASON_NOT_ANDROID


def test_parse_unparseable_os_counts_as_not_android():
    device, reason = parse_device_page_detailed(UNPARSEABLE_OS_HTML, "samsung")
    assert device is None
    assert reason == REASON_NOT_ANDROID


def test_parse_device_page_backwards_compatible():
    assert isinstance(parse_device_page(SUCCESS_HTML, "samsung"), DeviceInfo)
    assert parse_device_page(NO_MODEL_HTML, "samsung") is None
    assert parse_device_page(NOT_ANDROID_HTML, "samsung") is None


# ---------------------------------------------------------------------------
# Retry policy
# ---------------------------------------------------------------------------

def test_429_then_success_retries():
    fetcher = FakeFetcher({"u": [FetchResponse(429), FetchResponse(429), ok()]})
    outcome = asyncio.run(
        fetch_with_retries(fetcher, "u", retries=3, sleep=no_sleep)
    )
    assert outcome.body == SUCCESS_HTML
    assert outcome.attempts == 3
    assert outcome.retries_429 == 2
    assert fetcher.calls == ["u", "u", "u"]


def test_429_exhausted_is_failure():
    fetcher = FakeFetcher({"u": [FetchResponse(429)]})
    outcome = asyncio.run(
        fetch_with_retries(fetcher, "u", retries=3, sleep=no_sleep)
    )
    assert outcome.body is None
    assert outcome.status == 429
    assert outcome.attempts == 3
    assert len(fetcher.calls) == 3


def test_other_non_200_not_retried():
    fetcher = FakeFetcher({"u": [FetchResponse(500)]})
    outcome = asyncio.run(
        fetch_with_retries(fetcher, "u", retries=3, sleep=no_sleep)
    )
    assert outcome.body is None
    assert outcome.status == 500
    assert len(fetcher.calls) == 1  # no retry


def test_429_backoff_waits_are_observable():
    waits = []

    async def record_sleep(seconds):
        waits.append(seconds)

    fetcher = FakeFetcher({"u": [FetchResponse(429), FetchResponse(429), ok()]})
    asyncio.run(fetch_with_retries(fetcher, "u", retries=3, sleep=record_sleep))
    assert waits == [30.0, 60.0]  # linear backoff: base * (attempt + 1)


# ---------------------------------------------------------------------------
# collect_brand
# ---------------------------------------------------------------------------

def test_collect_brand_mixed_outcomes():
    entries = [
        ("ok-1.php", "Galaxy S23"),
        ("nomodel-2.php", "No Model Phone"),
        ("ios-3.php", "iPhone 15"),
        ("gone-4.php", "Deleted Phone"),
        ("flaky-5.php", "Flaky Phone"),
    ]
    fetcher = FakeFetcher({
        "ok-1.php": [ok()],
        "nomodel-2.php": [ok(NO_MODEL_HTML)],
        "ios-3.php": [ok(NOT_ANDROID_HTML)],
        "gone-4.php": [FetchResponse(404)],
        "flaky-5.php": [FetchResponse(429), FetchResponse(429), ok()],
    })

    summary = collect_brand_sync("samsung", entries, fetcher, sleep=no_sleep)

    assert summary.succeeded == 2
    assert summary.failed == 3
    assert summary.total == 5
    assert summary.total == summary.succeeded + summary.failed

    # Successes keep input-list order; device name comes from the page itself
    assert [d.name for d in summary.devices] == ["Samsung Galaxy S23"] * 2

    by_name = {f.name: f for f in summary.failures}
    assert by_name["No Model Phone"].reason == REASON_NO_MODEL
    assert by_name["No Model Phone"].url == "nomodel-2.php"
    assert by_name["iPhone 15"].reason == REASON_NOT_ANDROID
    assert by_name["Deleted Phone"].reason == REASON_FETCH_FAILED
    assert "404" in by_name["Deleted Phone"].detail


def test_collect_brand_429_exhausted_records_fetch_failed():
    entries = [("slow-1.php", "Throttled Phone")]
    fetcher = FakeFetcher({"slow-1.php": [FetchResponse(429)]})

    summary = collect_brand_sync("samsung", entries, fetcher,
                                 retries=2, sleep=no_sleep)

    assert summary.succeeded == 0
    assert summary.failed == 1
    failure = summary.failures[0]
    assert failure.reason == REASON_FETCH_FAILED
    assert "429" in failure.detail
    assert len(fetcher.calls) == 2  # retried up to the limit


def test_collect_brand_exception_does_not_abort_batch():
    def exploding_fetcher(url):
        if url == "boom-1.php":
            raise ConnectionError("connection reset")
        return ok()

    entries = [("boom-1.php", "Boom Phone"), ("ok-2.php", "Fine Phone")]
    summary = collect_brand_sync("samsung", entries, exploding_fetcher)

    assert summary.succeeded == 1
    assert summary.failed == 1
    assert summary.devices[0].name == "Samsung Galaxy S23"
    failure = summary.failures[0]
    assert failure.name == "Boom Phone"
    assert failure.reason == REASON_FETCH_FAILED
    assert "connection reset" in failure.detail


def test_collect_brand_async_fetcher_supported():
    async def async_fetcher(url):
        return ok()

    summary = collect_brand_sync("samsung", [("a.php", "A")], async_fetcher)
    assert summary.succeeded == 1


# ---------------------------------------------------------------------------
# merge_summaries / output shape
# ---------------------------------------------------------------------------

def _summary(brand, devices, failures):
    return CollectionSummary(brand=brand, devices=devices, failures=failures)


def test_merge_summaries_skips_empty_brand_but_keeps_failures():
    ok_device, _ = parse_device_page_detailed(SUCCESS_HTML, "samsung")
    summaries = [
        _summary("samsung", [ok_device], []),
        _summary("google_pixel", [], [
            DeviceFailure(brand="google_pixel", name="Pixel Fold",
                          url="pixel_fold-12265.php", reason=REASON_FETCH_FAILED,
                          detail="HTTP 500"),
        ]),
    ]

    devices_by_brand, failures, stats = merge_summaries(summaries)

    # All-failed brand gets no empty devices group
    assert "google_pixel" not in devices_by_brand
    assert list(devices_by_brand.keys()) == ["samsung"]

    # ...but its failures survive
    assert len(failures) == 1
    assert failures[0]["brand"] == "google_pixel"
    assert failures[0]["reason"] == REASON_FETCH_FAILED

    # Totals invariant
    assert stats == {"total": 2, "succeeded": 1, "failed": 1}
    assert stats["total"] == stats["succeeded"] + stats["failed"]


def test_merge_summaries_device_fields_match_loader_contract():
    ok_device, _ = parse_device_page_detailed(SUCCESS_HTML, "samsung")
    devices_by_brand, _, _ = merge_summaries([_summary("samsung", [ok_device], [])])

    d = devices_by_brand["samsung"][0]
    # Fields the DataLoader reads - names must not change
    for key in ("model_code", "brand", "name", "min_android_api",
                "max_android_api", "popularity", "year"):
        assert key in d


def test_loader_processes_merged_output():
    """The merged devices group feeds DataLoader._process_device_specs."""
    from uaforge.data.loader import DataLoader

    ok_device, _ = parse_device_page_detailed(SUCCESS_HTML, "samsung")
    devices_by_brand, _, _ = merge_summaries([_summary("samsung", [ok_device], [])])

    # Bypass __init__ (data files may be absent in a fresh checkout)
    loader = object.__new__(DataLoader)
    loader.android_device_specs_raw = {"devices": devices_by_brand}
    loader._device_specs = {}
    loader._compatible_devices_cache = {}
    loader._process_device_specs()

    specs = loader.get_compatible_devices("samsung", 33)
    assert any(s.model_code == "SM-S911B" for s in specs)
