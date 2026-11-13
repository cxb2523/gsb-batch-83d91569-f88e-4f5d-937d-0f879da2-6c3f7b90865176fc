"""CSV serialization helpers."""

from __future__ import annotations

import csv
from pathlib import Path

from .models import FetchOutcome

CSV_FIELDS = [
    "email",
    "first_seen_source",
    "all_sources",
    "domain",
    "mx_ok",
    "hunter_result",
    "hunter_confidence",
    "quality",
    "date_scraped_utc",
    "notes",
]

FETCH_REPORT_FIELDS = ["url", "status", "detail"]


def write_rows(path: str, rows: list[dict[str, str]]) -> None:
    """Write harvest rows to CSV with stable schema."""
    output_path = Path(path)
    with output_path.open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def fetch_outcomes_to_rows(
    outcomes: list[FetchOutcome],
) -> list[dict[str, str]]:
    """Convert fetch outcomes to report rows with stable schema."""
    return [
        {
            "url": outcome.url,
            "status": outcome.status.value,
            "detail": outcome.detail,
        }
        for outcome in outcomes
    ]


def write_fetch_report(path: str, outcomes: list[FetchOutcome]) -> None:
    """Write one row per candidate URL describing how its fetch ended."""
    output_path = Path(path)
    with output_path.open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=FETCH_REPORT_FIELDS)
        writer.writeheader()
        for row in fetch_outcomes_to_rows(outcomes):
            writer.writerow(row)
