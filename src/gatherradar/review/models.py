"""Application persistence and export boundaries, independent of any vendor."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import ContextManager, Protocol

from ..deduplication.models import CanonicalizationResult
from .serialization import ReviewWindow


class ReviewError(Exception):
    """An actionable, payload-free review/persistence error."""


@dataclass(frozen=True)
class SnapshotResult:
    run_id: str
    spreadsheet_url: str
    event_tab: str
    place_tab: str
    events: int
    places: int
    duplicates: int
    status: str
    filtered: int = 0
    undated: int = 0
    already_synced: bool = False


class RunLock(Protocol):
    def lock(self) -> ContextManager: ...


class SnapshotRepository(Protocol):
    """Shared application seam also implemented by the optional Sheets adapter."""
    state: RunLock

    def find_run(self, run_id: str) -> SnapshotResult | None: ...

    def sync(self, result: CanonicalizationResult, window: ReviewWindow, *,
             run_id: str, started_at: datetime, finished_at: datetime, days: int,
             review_timezone: str, source_count: int, failures: tuple[str, ...] = (),
             status: str = 'success', run_metadata: dict | None = None) -> SnapshotResult: ...


class CanonicalRepository(SnapshotRepository, Protocol):
    def load(self, run_id: str = 'latest', *, include_filtered: bool = False) -> dict: ...
    def list_runs(self) -> list[dict]: ...
    def duplicate_queue(self) -> list[dict]: ...
    def review_token(self, kind: str, key: str, run_id: str) -> str: ...
    def import_review(self, token: str, kind: str, key: str, run_id: str,
                      decision: str, notes: str) -> str: ...


class ReviewExporter(Protocol):
    def export(self, document: dict) -> tuple[Path, ...]: ...
