from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from ..collectors.instagram import DEFAULT_LIMIT
from ..domain import DiscoveryUnit, EvidenceFragment, RawItem, Source
from ..extraction import DiscoveryOutcome, DiscoveryService, DiscoveryStatus, RuleBasedDiscoveryProvider
from ..extraction.base import DiscoveryProvider
from ..grouping import ConservativeGrouping, GroupingStrategy, select_semantic_evidence
from ..storage import JsonlEvidenceStore, JsonlRawItemStore
from .collection_run import find_source, instagram_output_path
from .discovery_run import DiscoveryRunSummary, select_latest
from .evidence_paths import instagram_evidence_output_path


@dataclass(frozen=True, slots=True)
class EvidenceItemDiscovery:
    raw_item_id: str
    units: tuple[DiscoveryUnit, ...] = ()
    outcomes: tuple[DiscoveryOutcome, ...] = ()
    ignored_fragments: int = 0
    reason: str | None = None
    failed: bool = False


@dataclass(frozen=True, slots=True)
class EvidenceDiscoveryRunSummary(DiscoveryRunSummary):
    items: tuple[EvidenceItemDiscovery, ...] = ()
    grouping_strategy: str = 'conservative/2'

    @property
    def observed(self) -> int:
        return len(self.items)

    @property
    def unit_count(self) -> int:
        return sum(len(item.units) for item in self.items)

    @property
    def failed(self) -> int:
        return (self._count(DiscoveryStatus.PROVIDER_FAILED)
                + self._count(DiscoveryStatus.INVALID_OUTPUT)
                + sum(item.failed for item in self.items))


def run_evidence_discovery(
    raw_items: Iterable[RawItem], history: Iterable[EvidenceFragment],
    service: DiscoveryService, *, sources: Mapping[str, Source] | None = None,
    strategy: GroupingStrategy | None = None, run_id: str = '',
    source: Source | None = None, input_path: Path | None = None,
    malformed: tuple[str, ...] = (),
) -> EvidenceDiscoveryRunSummary:
    '''Read-only grouping and discovery, isolating failures per raw item and unit.'''
    grouping = strategy if strategy is not None else ConservativeGrouping()
    raw_items = tuple(raw_items)
    by_item: dict[str, list[EvidenceFragment]] = {}
    for fragment in history:
        by_item.setdefault(fragment.raw_item_id, []).append(fragment)
    items: list[EvidenceItemDiscovery] = []
    all_outcomes: list[DiscoveryOutcome] = []
    for raw_item in raw_items:
        try:
            bundle = select_semantic_evidence(raw_item, by_item.get(raw_item.id, ()))
            units = grouping.group(bundle)
        except Exception as exc:
            items.append(EvidenceItemDiscovery(
                raw_item.id, reason=f'grouping_failed ({type(exc).__name__})', failed=True,
            ))
            continue
        outcomes: list[DiscoveryOutcome] = []
        for unit in units:
            try:
                # Singleton batches retain service semantics and isolate unexpected
                # bugs to a unit without retrying already-discovered neighbours.
                outcome, = service.discover_units(raw_item, (unit,), (sources or {}).get(raw_item.source_id))
            except Exception as exc:
                outcome = DiscoveryOutcome(
                    raw_item_id=raw_item.id, status=DiscoveryStatus.PROVIDER_FAILED,
                    provider_name=service.provider_name, discovery_unit_id=unit.unit_id,
                    reason=f'unit_discovery_failed ({type(exc).__name__})',
                )
            outcomes.append(outcome)
        items.append(EvidenceItemDiscovery(
            raw_item.id, units, tuple(outcomes),
            ignored_fragments=len(bundle.fragments) - sum(
                len(unit.fragments) + len(unit.collapsed) for unit in units),
            reason='no_meaningful_evidence' if not units else None,
        ))
        all_outcomes.extend(outcomes)
    return EvidenceDiscoveryRunSummary(
        provider_name=service.provider_name, outcomes=tuple(all_outcomes),
        run_id=run_id, source=source, input_path=input_path, malformed=malformed,
        items=tuple(items), grouping_strategy=grouping.name,
        raw_items=raw_items,
    )


def run_instagram_evidence_discovery(
    source_id: str, *, config_path: str | Path = 'config/sources.yaml',
    data_dir: str | Path = 'data', limit: int = DEFAULT_LIMIT,
    provider: DiscoveryProvider | None = None,
) -> EvidenceDiscoveryRunSummary:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError('limit must be a positive integer')
    source = find_source(source_id, config_path)
    stored = JsonlRawItemStore(instagram_output_path(source, data_dir)).read_latest_items()
    evidence = JsonlEvidenceStore(instagram_evidence_output_path(source, data_dir)).read()
    return run_evidence_discovery(
        select_latest(stored.items, limit), evidence.fragments,
        DiscoveryService(provider if provider is not None else RuleBasedDiscoveryProvider()),
        sources={source.id: source}, run_id=uuid.uuid4().hex[:12], source=source,
        input_path=stored.path,
        # Diagnostics identify the store and line, never an untrusted field value.
        malformed=tuple(
            f'{store}: {reason.split(":", 1)[0]}: invalid record'
            for store, reasons in (('raw', stored.malformed), ('evidence', evidence.malformed))
            for reason in reasons
        ),
    )
