"""Per-page crawl run recording.

This module provides :class:`RunRecorder`, which records every page attempt made
while crawling (one record per sub-category + page number attempt, including every
retry), the reason each sub-category stopped paging, and an aggregate summary.

The recorder can optionally persist itself to a JSON file after every recorded
attempt, so pages completed before a Ctrl+C / SIGTERM interrupt are never lost.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .utils import get_utc_iso_now

# Page attempt result types
RESULT_SUCCESS = "success"
RESULT_EMPTY = "empty"
RESULT_RATE_LIMITED = "rate_limited"
RESULT_TIMEOUT = "timeout"
RESULT_ELEMENT_MISSING = "element_missing"
RESULT_ERROR = "error"

# Reasons a sub-category stopped paging
STOP_EMPTY_PAGE = "empty_page"
STOP_LIMIT_REACHED = "limit_reached"
STOP_RETRIES_EXHAUSTED = "retries_exhausted"
STOP_INTERRUPTED = "interrupted"
STOP_ERROR = "error"

# Overall run statuses
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_INTERRUPTED = "interrupted"


@dataclass
class PageAttempt:
    """A single attempt to fetch one page of a sub-category."""

    page: int
    attempt: int
    result: str
    new_listings: int = 0
    error: str | None = None
    timestamp: str = field(default_factory=get_utc_iso_now)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable representation of this attempt."""
        data: dict[str, object] = {
            "page": self.page,
            "attempt": self.attempt,
            "result": self.result,
            "new_listings": self.new_listings,
            "timestamp": self.timestamp,
        }
        if self.error is not None:
            data["error"] = self.error

        return data


@dataclass
class SubCategoryRecord:
    """The paging record for one sub-category."""

    category_id: int
    category_url: str
    attempts: list[PageAttempt] = field(default_factory=list)
    stop_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable representation of this sub-category."""
        return {
            "category_id": self.category_id,
            "category_url": self.category_url,
            "stop_reason": self.stop_reason,
            "pages": [attempt.to_dict() for attempt in self.attempts],
        }


@dataclass
class ParentCategoryRecord:
    """The paging record for one parent category and its sub-categories."""

    category_id: int
    category_url: str
    subcategories: list[SubCategoryRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable representation of this parent category."""
        return {
            "category_id": self.category_id,
            "category_url": self.category_url,
            "subcategories": [subcategory.to_dict() for subcategory in self.subcategories],
        }


class RunRecorder:
    """Records per-page crawl attempts and summary statistics for a crawl run."""

    def __init__(self, file_path: str | Path | None = None) -> None:
        self.file_path: Path | None = Path(file_path) if file_path is not None else None
        self.started_at: str = get_utc_iso_now()
        self.finished_at: str | None = None
        self.status: str = STATUS_RUNNING
        self.parent_categories: list[ParentCategoryRecord] = []

        self._current_parent: ParentCategoryRecord | None = None
        self._current_subcategory: SubCategoryRecord | None = None

    def start_parent_category(self, category_id: int, category_url: str) -> None:
        """Begin recording a parent category."""
        self._current_parent = ParentCategoryRecord(
            category_id=category_id, category_url=category_url
        )
        self.parent_categories.append(self._current_parent)
        self._current_subcategory = None

    def start_subcategory(self, category_id: int, category_url: str) -> None:
        """Begin recording a sub-category under the current parent category."""
        if self._current_parent is None:
            raise RuntimeError("Cannot start a sub-category before a parent category")

        self._current_subcategory = SubCategoryRecord(
            category_id=category_id, category_url=category_url
        )
        self._current_parent.subcategories.append(self._current_subcategory)

    def record_attempt(
        self,
        page: int,
        attempt: int,
        result: str,
        new_listings: int = 0,
        error: str | None = None,
    ) -> None:
        """Record a single page fetch attempt and persist if a file is configured."""
        if self._current_subcategory is None:
            raise RuntimeError("Cannot record an attempt before a sub-category is started")

        self._current_subcategory.attempts.append(
            PageAttempt(
                page=page,
                attempt=attempt,
                result=result,
                new_listings=new_listings,
                error=error,
            )
        )
        self._flush()

    def set_stop_reason(self, reason: str) -> None:
        """Record why the current sub-category stopped paging."""
        if self._current_subcategory is not None:
            self._current_subcategory.stop_reason = reason
            self._flush()

    def mark_interrupted(self) -> None:
        """Mark the run as interrupted, tagging the active sub-category, and persist."""
        self.status = STATUS_INTERRUPTED
        if self._current_subcategory is not None and self._current_subcategory.stop_reason is None:
            self._current_subcategory.stop_reason = STOP_INTERRUPTED
        self._flush()

    def finalize(self, interrupted: bool = False) -> None:
        """Close the run, setting the final status and timestamp, and persist."""
        if interrupted:
            self.status = STATUS_INTERRUPTED
            if (
                self._current_subcategory is not None
                and self._current_subcategory.stop_reason is None
            ):
                self._current_subcategory.stop_reason = STOP_INTERRUPTED
        elif self.status == STATUS_RUNNING:
            self.status = STATUS_COMPLETED

        self.finished_at = get_utc_iso_now()
        self._flush()

    def has_records(self) -> bool:
        """Return True if at least one page attempt has been recorded."""
        return any(
            len(subcategory.attempts) > 0
            for parent in self.parent_categories
            for subcategory in parent.subcategories
        )

    def all_attempts(self) -> list[tuple[ParentCategoryRecord, SubCategoryRecord, PageAttempt]]:
        """Return every recorded attempt with its parent and sub-category context."""
        attempts: list[tuple[ParentCategoryRecord, SubCategoryRecord, PageAttempt]] = []
        for parent in self.parent_categories:
            for subcategory in parent.subcategories:
                for page_attempt in subcategory.attempts:
                    attempts.append((parent, subcategory, page_attempt))

        return attempts

    def summary(self) -> dict[str, object]:
        """Return aggregate counts across the whole run.

        Every page attempt is counted by its result type. A page whose retries were
        all exhausted is additionally counted once as an error-skipped page, keyed on
        the final (non-transient or last) attempt of that page.
        """
        attempts = self.all_attempts()

        successful_pages = sum(1 for _, _, a in attempts if a.result == RESULT_SUCCESS)
        empty_pages = sum(1 for _, _, a in attempts if a.result == RESULT_EMPTY)
        rate_limited = sum(1 for _, _, a in attempts if a.result == RESULT_RATE_LIMITED)
        timeouts = sum(1 for _, _, a in attempts if a.result == RESULT_TIMEOUT)
        element_missing = sum(1 for _, _, a in attempts if a.result == RESULT_ELEMENT_MISSING)
        other_errors = sum(1 for _, _, a in attempts if a.result == RESULT_ERROR)
        total_new_listings = sum(a.new_listings for _, _, a in attempts)

        # Count each distinct page whose final attempt did not yield a page, once.
        error_skipped_pages = 0
        for parent in self.parent_categories:
            for subcategory in parent.subcategories:
                final_by_page: dict[int, PageAttempt] = {}
                for page_attempt in subcategory.attempts:
                    final_by_page[page_attempt.page] = page_attempt

                for page_attempt in final_by_page.values():
                    if page_attempt.result in (
                        RESULT_TIMEOUT,
                        RESULT_ELEMENT_MISSING,
                        RESULT_ERROR,
                        RESULT_RATE_LIMITED,
                    ):
                        error_skipped_pages += 1

        return {
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "parent_categories_crawled": len(self.parent_categories),
            "successful_pages": successful_pages,
            "empty_pages": empty_pages,
            "rate_limited_attempts": rate_limited,
            "timeout_attempts": timeouts,
            "element_missing_attempts": element_missing,
            "other_error_attempts": other_errors,
            "error_skipped_pages": error_skipped_pages,
            "total_attempts": len(attempts),
            "total_new_listings": total_new_listings,
        }

    def to_dict(self) -> dict[str, object]:
        """Return the full JSON-serialisable run record."""
        return {
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "summary": self.summary(),
            "parent_categories": [parent.to_dict() for parent in self.parent_categories],
        }

    def format_summary(self) -> str:
        """Return a human-readable multi-line summary string for end-of-run output."""
        counts = self.summary()
        lines = [
            "Crawl run summary:",
            f"  Status:                 {counts['status']}",
            f"  Parent categories:      {counts['parent_categories_crawled']}",
            f"  Successful pages:       {counts['successful_pages']}",
            f"  Empty pages:            {counts['empty_pages']}",
            f"  Rate-limited attempts:  {counts['rate_limited_attempts']}",
            f"  Timeout attempts:       {counts['timeout_attempts']}",
            f"  Element-missing:        {counts['element_missing_attempts']}",
            f"  Other error attempts:   {counts['other_error_attempts']}",
            f"  Error-skipped pages:    {counts['error_skipped_pages']}",
            f"  New listings recorded:  {counts['total_new_listings']}",
        ]
        if self.file_path is not None and self.has_records():
            lines.append(f"  Page-level run record:  {self.file_path}")

        return os.linesep.join(lines)

    def _flush(self) -> None:
        """Persist the record to disk atomically.

        Nothing is written when no file path is configured, or no page attempt has
        been recorded yet (an empty file is never produced).
        """
        if self.file_path is None or not self.has_records():
            return

        path = self.file_path
        path.parent.mkdir(parents=True, exist_ok=True)

        tmp_path = path.with_name(f"{path.name}.tmp")
        with tmp_path.open("w", encoding="utf-8") as file_obj:
            json.dump(self.to_dict(), file_obj, indent=2, ensure_ascii=False)

        os.replace(tmp_path, path)
