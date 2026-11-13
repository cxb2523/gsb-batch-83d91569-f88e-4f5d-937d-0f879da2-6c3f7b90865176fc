from __future__ import annotations

import uuid
from pathlib import Path

from ..collectors.website import WebsiteCollector, validate_website_source
from ..domain import Source, SourceType
from ..extraction import DiscoveryService, RuleBasedDiscoveryProvider
from ..storage import JsonlRawItemStore
from .collection_run import RunSummary, find_source
from .evidence_discovery_run import EvidenceDiscoveryRunSummary, run_evidence_discovery


def website_output_path(source: Source, data_dir: str | Path) -> Path:
    return Path(data_dir) / 'raw' / 'website' / f'{source.id}.jsonl'


def run_website_collection(
    source_id: str, *, config_path: str | Path = 'config/sources.yaml',
    data_dir: str | Path = 'data', limit: int = 5, collector: WebsiteCollector | None = None,
) -> RunSummary:
    source = find_source(source_id, config_path)
    validate_website_source(source, limit)
    result = (collector or WebsiteCollector()).collect(source, limit=limit)
    stored = JsonlRawItemStore(website_output_path(source, data_dir)).append_new(result.items)
    return RunSummary(
        uuid.uuid4().hex[:12], source, result.observed, stored.new, stored.changed,
        stored.already_existing, len(result.failures), stored.path,
        tuple(failure.reason for failure in result.failures),
        observed_items=result.items,
    )


def run_website_discovery(
    source_id: str, *, config_path: str | Path = 'config/sources.yaml',
    data_dir: str | Path = 'data', limit: int = 5,
) -> EvidenceDiscoveryRunSummary:
    source = find_source(source_id, config_path)
    validate_website_source(source, limit)
    stored = JsonlRawItemStore(website_output_path(source, data_dir)).read_latest_items()
    # Storage first-seen order, with the latest observation per identity; there is
    # no listing-run manifest and no claim of publication recency.
    items = tuple(item for item in stored.items
                  if item.source_id == source.id and item.source_type is SourceType.WEBSITE)[:limit]
    return run_evidence_discovery(
        items, (), DiscoveryService(RuleBasedDiscoveryProvider()), sources={source.id: source},
        source=source, input_path=stored.path, run_id=uuid.uuid4().hex[:12],
        malformed=tuple(f'raw: {reason.split(":", 1)[0]}: invalid record' for reason in stored.malformed),
    )
