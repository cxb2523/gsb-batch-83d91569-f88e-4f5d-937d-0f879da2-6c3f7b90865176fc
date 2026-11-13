from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from ..collectors.base import SourceNotFoundError
from ..collectors.instagram import DEFAULT_LIMIT, InstagramCollector
from ..config import load_sources
from ..domain import RawItem, Source
from ..storage.jsonl import JsonlRawItemStore


@dataclass(frozen=True, slots=True)
class RunSummary:
    run_id: str
    source: Source
    observed: int
    new: int
    changed: int
    already_existing: int
    failed: int
    output_path: Path
    failure_reasons: tuple[str, ...] = ()
    observed_items: tuple[RawItem, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def observed_item_ids(self) -> tuple[str, ...]:
        return tuple(sorted({item.id for item in self.observed_items}))


def find_source(source_id: str, config_path: str | Path) -> Source:
    for source in load_sources(config_path):
        if source.id == source_id:
            return source
    raise SourceNotFoundError(f"source id '{source_id}' is not in {config_path}")


def instagram_output_path(source: Source, data_dir: str | Path) -> Path:
    username = (source.username or source.id).strip().lower()
    return Path(data_dir) / "raw" / "instagram" / f"{username}.jsonl"


def run_instagram_collection(
    source_id: str,
    *,
    config_path: str | Path = "config/sources.yaml",
    data_dir: str | Path = "data",
    limit: int = DEFAULT_LIMIT,
    collector: InstagramCollector | None = None,
) -> RunSummary:
    """Collect one Instagram source into JSONL and summarize what changed."""
    source = find_source(source_id, config_path)
    active_collector = (
        collector if collector is not None else InstagramCollector(data_dir=data_dir)
    )

    result = active_collector.collect(source, limit=limit)

    store = JsonlRawItemStore(instagram_output_path(source, data_dir))
    outcome = store.append_new(result.items)

    return RunSummary(
        run_id=uuid.uuid4().hex[:12],
        source=source,
        observed=result.observed,
        new=outcome.new,
        changed=outcome.changed,
        already_existing=outcome.already_existing,
        failed=len(result.failures),
        output_path=outcome.path,
        failure_reasons=tuple(failure.reason for failure in result.failures),
        observed_items=result.items,
        warnings=result.warnings,
    )


__all__ = [
    "RunSummary",
    "find_source",
    "instagram_output_path",
    "run_instagram_collection",
]
