"""Local verification for skip-record tracking (no browser / no network needed).

Simulates a mixed result list:
  - normal businesses       -> land in CSV/JSON
  - detail page not loaded  -> skip record (detail_not_loaded)
  - empty business name     -> skip record (empty_name)
  - extraction exception    -> skip record (extraction_error)

Also verifies the all-fail case and the Flask /api/status + download endpoints.
"""
import csv
import json
import os
import sys
from types import SimpleNamespace
from unittest import mock

import maps_scraper as ms
import app as webapp

KEYWORD = "SkipTest KW!"
CITY = "SkipTest City"
BASE = f"{ms.safe_filename(KEYWORD)}_{ms.safe_filename(CITY)}"
CSV_FILE = os.path.join(ms.OUTPUT_DIR, f"{BASE}_businesses.csv")
JSON_FILE = os.path.join(ms.OUTPUT_DIR, f"{BASE}_businesses.json")
SKIPPED_FILE = os.path.join(ms.OUTPUT_DIR, f"{BASE}_skipped.json")

AF_KEYWORD = "SkipTest AllFail"
AF_BASE = f"{ms.safe_filename(AF_KEYWORD)}_{ms.safe_filename(CITY)}"
AF_CSV = os.path.join(ms.OUTPUT_DIR, f"{AF_BASE}_businesses.csv")
AF_JSON = os.path.join(ms.OUTPUT_DIR, f"{AF_BASE}_businesses.json")
AF_SKIPPED = os.path.join(ms.OUTPUT_DIR, f"{AF_BASE}_skipped.json")

CHECKPOINT = os.path.join(ms.CHECKPOINT_DIR, f"{BASE}.json")
AF_CHECKPOINT = os.path.join(ms.CHECKPOINT_DIR, f"{AF_BASE}.json")


class FakePage:
    """Minimal stand-in for a Playwright page."""
    def __init__(self):
        self.current_href = None

    def goto(self, href, timeout=None):
        if "crash" in href:
            raise RuntimeError("simulated navigation explosion")
        self.current_href = href


def fake_wait_for_selector(page, selectors, timeout=0):
    # detail page never loads for these hrefs
    return "timeout" not in page.current_href


def fake_extract_business_data(page):
    href = page.current_href
    if "emptyname" in href:
        return None  # name empty / invalid
    return {
        "name": f"Business for {href}",
        "address": "1 Test Street",
        "phone": "1234567890",
        "website": "N/A",
        "emails": "N/A",
    }


def run_batch(hrefs):
    """Drive the same per-business loop maps_scraper.main uses."""
    page = FakePage()
    businesses, skipped = [], []
    with mock.patch.object(ms.time, "sleep", lambda *a, **k: None), \
         mock.patch.object(ms, "wait_for_selector", fake_wait_for_selector), \
         mock.patch.object(ms, "extract_business_data", fake_extract_business_data):
        for index, href in enumerate(hrefs):
            business, skip_record = ms.process_single_business(
                page, href, index, len(hrefs), skip_emails=True
            )
            if skip_record:
                skipped.append(skip_record)
            else:
                businesses.append(business)
    return businesses, skipped


def cleanup(*paths):
    for p in paths:
        if os.path.exists(p):
            os.remove(p)


def test_mixed_batch():
    print("== Test 1: mixed batch (normal / not-loaded / empty-name / exception) ==")
    hrefs = [
        "https://maps.example.com/biz/normal1",
        "https://maps.example.com/biz/timeout1",     # detail not loaded
        "https://maps.example.com/biz/emptyname1",   # empty name
        "https://maps.example.com/biz/crash1",       # extraction exception
        "https://maps.example.com/biz/normal2",
    ]
    businesses, skipped = run_batch(hrefs)
    assert len(businesses) == 2, f"expected 2 successes, got {len(businesses)}"
    assert len(skipped) == 3, f"expected 3 skips, got {len(skipped)}"

    ms.finalize_results(businesses, skipped, KEYWORD, CITY, CHECKPOINT)

    # Normal results in CSV
    assert os.path.exists(CSV_FILE), "CSV file missing"
    with open(CSV_FILE, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2, f"CSV should have 2 rows, got {len(rows)}"
    assert set(rows[0].keys()) == {"name", "address", "phone", "website", "emails"}, "CSV fields changed!"

    # Normal results in JSON
    assert os.path.exists(JSON_FILE), "JSON file missing"
    with open(JSON_FILE, encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 2, f"JSON should have 2 entries, got {len(data)}"

    # Skip records: file exists, indices/hrefs/categories match
    assert os.path.exists(SKIPPED_FILE), "skipped file missing"
    with open(SKIPPED_FILE, encoding="utf-8") as f:
        payload = json.load(f)
    assert payload["skipped_count"] == 3
    records = payload["skipped"]
    assert [r["index"] for r in records] == [2, 3, 4], f"wrong indices: {[r['index'] for r in records]}"
    assert [r["href"] for r in records] == hrefs[1:4], "hrefs do not match result-list positions"
    assert [r["category"] for r in records] == [
        ms.SKIP_DETAIL_NOT_LOADED, ms.SKIP_EMPTY_NAME, ms.SKIP_EXTRACTION_ERROR,
    ], f"wrong categories: {[r['category'] for r in records]}"
    assert all(r["reason"] for r in records), "every skip record needs a reason"
    print("   CSV rows:", len(rows), "| JSON entries:", len(data), "| skips:", len(records))
    for r in records:
        print(f"   skip #{r['index']} [{r['category']}] {r['reason']} | {r['href']}")
    print("   OK\n")


def test_all_fail():
    print("== Test 2: all businesses fail ==")
    hrefs = [
        "https://maps.example.com/biz/timeout1",
        "https://maps.example.com/biz/emptyname1",
        "https://maps.example.com/biz/crash1",
    ]
    businesses, skipped = run_batch(hrefs)
    assert len(businesses) == 0 and len(skipped) == 3

    ms.finalize_results(businesses, skipped, AF_KEYWORD, CITY, AF_CHECKPOINT)

    assert not os.path.exists(AF_CSV), "no CSV should be written when everything failed"
    assert not os.path.exists(AF_JSON), "no JSON should be written when everything failed"
    assert os.path.exists(AF_SKIPPED), "skipped file must still be written"
    with open(AF_SKIPPED, encoding="utf-8") as f:
        payload = json.load(f)
    assert payload["skipped_count"] == 3
    assert [r["index"] for r in payload["skipped"]] == [1, 2, 3]
    assert all(r["reason"] for r in payload["skipped"])
    print(f"   no CSV/JSON written; skipped file records all {len(payload['skipped'])} failures")
    print("   OK\n")


def test_flask_status_and_downloads():
    print("== Test 3: Flask /api/status + downloads consistent with files ==")
    # Simulate the scraper subprocess finishing successfully (files from Test 1 exist)
    with mock.patch.object(webapp.subprocess, "run",
                           return_value=SimpleNamespace(returncode=0, stderr="")):
        webapp.run_scraper(KEYWORD, CITY, None, True, True, 60)

    status = webapp.scraper_status
    assert status["total_businesses"] == 2, f"status total {status['total_businesses']} != CSV rows 2"
    assert status["skipped_count"] == 3, f"status skipped_count {status['skipped_count']} != skipped file 3"
    assert len(status["skipped"]) == 3
    assert "成功 2 条、跳过 3 条" in status["message"]

    client = webapp.app.test_client()
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["skipped_count"] == 3 and len(data["skipped"]) == 3
    assert data["skipped"][0]["index"] == 2
    assert data["skipped"][0]["href"] == "https://maps.example.com/biz/timeout1"

    # Downloads serve the per-run files
    resp = client.get("/api/results/csv")
    assert resp.status_code == 200, f"CSV download failed: {resp.status_code}"
    resp = client.get("/api/results/json")
    assert resp.status_code == 200, f"JSON download failed: {resp.status_code}"

    # Missing result files -> 404 with original error message
    webapp.current_output = {"csv": "output/definitely_missing.csv", "json": None}
    resp = client.get("/api/results/csv")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "No results available"
    resp = client.get("/api/results/json")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "No results available"

    # Zero-skip run: skipped file with 0 records -> count 0, empty list
    ms.save_skipped_records([], AF_KEYWORD, CITY)
    with mock.patch.object(webapp.subprocess, "run",
                           return_value=SimpleNamespace(returncode=0, stderr="")):
        webapp.run_scraper(AF_KEYWORD, CITY, None, True, True, 60)
    assert webapp.scraper_status["skipped_count"] == 0
    assert webapp.scraper_status["skipped"] == []
    assert webapp.scraper_status["total_businesses"] == 0
    print("   status: 成功 2 / 跳过 3 matches files; downloads 200; missing files -> 404")
    print("   zero-skip run -> skipped_count 0, empty details")
    print("   OK\n")


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    cleanup(CSV_FILE, JSON_FILE, SKIPPED_FILE, AF_CSV, AF_JSON, AF_SKIPPED,
            CHECKPOINT, AF_CHECKPOINT)
    try:
        test_mixed_batch()
        test_all_fail()
        test_flask_status_and_downloads()
    finally:
        cleanup(CSV_FILE, JSON_FILE, SKIPPED_FILE, AF_CSV, AF_JSON, AF_SKIPPED,
                CHECKPOINT, AF_CHECKPOINT)
    print("ALL TESTS PASSED")
