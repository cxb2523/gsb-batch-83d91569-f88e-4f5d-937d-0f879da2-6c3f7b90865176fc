"""Application boundary used by the Telegram handlers.

`SourceCatalog` is a read-only view of the effective source registry
(`config/sources.yaml` plus the local overlay, see `source_registry`). Crawls,
source changes and reads go through `LocalOperations`, which reuses
`RefreshService`, the SQLite repository and the existing exporters (no second
database, event model or export path). Adding a source never implies that an
arbitrary website is supported: unknown layouts need an adapter, and
robots/access policy applies.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from ..domain import SourceType


@dataclass(frozen=True)
class SourceView:
    """What the owner may see about one configured source (no local paths)."""

    id: str
    name: str
    kind: str  # 'instagram' | 'website'
    enabled: bool
    disabled_reason: str | None
    public_url: str
    archived: bool = False
    origin: str = 'base'     # 'base' (tracked YAML) | 'local' (added by the owner)
    locked: bool = False     # policy-blocked or unsupported: never runnable from the bot


class SourceCatalog:
    """Read-only view of the effective registry (base YAML + local overlay)."""

    def __init__(self, config_path: str | Path = 'config/sources.yaml') -> None:
        self.config_path = Path(config_path)

    def all(self) -> tuple[SourceView, ...]:
        from ..source_registry import SourceRegistry
        views = []
        for entry in SourceRegistry(self.config_path).entries():
            source = entry.source
            parts = urlsplit(source.url)
            views.append(SourceView(
                id=source.id, name=source.name,
                kind='instagram' if source.source_type is SourceType.INSTAGRAM else 'website',
                enabled=bool(source.enabled), disabled_reason=source.disabled_reason,
                # Query strings are kept only for websites (they can select a listing).
                public_url=urlunsplit((parts.scheme, parts.netloc, parts.path,
                                       parts.query if source.source_type is SourceType.WEBSITE else '', '')),
                archived=source.archived, origin=entry.origin, locked=entry.locked))
        return tuple(views)

    def list(self) -> tuple[SourceView, ...]:
        """Sources in the active list (archived ones are hidden), registry order."""
        return tuple(view for view in self.all() if not view.archived)

    def get(self, source_id: str) -> SourceView | None:
        return next((view for view in self.all() if view.id == source_id), None)


class PlannedFeature(str, Enum):
    """Menu entries that are visible but not implemented in Phase 1."""

    CRAWL_ALL = 'crawl_all'
    SELECT_SOURCES = 'select_sources'
    MANAGE_SOURCES = 'manage_sources'
    EXPORTS = 'exports'
    RUNS = 'runs'
    SETTINGS = 'settings'


class GatherRadarOperations(Protocol):
    """Phase 2+ boundary; every call is owner-authorized by the caller.

    Implementations wrap existing services and run at most one job at a time.
    """

    def collect_all_enabled(self) -> str: ...  # job id; RefreshService(all_enabled=True)
    def collect_sources(self, source_ids: tuple[str, ...]) -> str: ...  # single or multi-source
    def cancel_job(self, job_id: str) -> bool: ...
    def job_status(self, job_id: str) -> dict: ...
    def recent_runs(self, limit: int = 5) -> tuple[dict, ...]: ...  # repository.load / manifests
    def validate_source(self, url: str) -> dict: ...  # robots + adapter support, no write
    def register_source(self, definition: dict) -> str: ...
    def set_source_enabled(self, source_id: str, enabled: bool) -> None: ...  # reversible, never delete
    def workbook_path(self, run_id: str = 'latest') -> Path: ...  # existing XLSX export
    def event_list(self, run_id: str = 'latest', limit: int = 20) -> tuple[dict, ...]: ...
