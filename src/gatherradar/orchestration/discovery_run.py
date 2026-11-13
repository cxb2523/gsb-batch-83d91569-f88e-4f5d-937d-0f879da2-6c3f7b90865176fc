from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ..collectors.instagram import DEFAULT_LIMIT
from ..domain import DiscoveryType, EventCandidate, PlaceCandidate, RawItem, Source
from ..extraction import DiscoveryOutcome, DiscoveryService, DiscoveryStatus, RuleBasedDiscoveryProvider
from ..storage.jsonl import JsonlRawItemStore
from .collection_run import find_source, instagram_output_path


@dataclass(frozen=True, slots=True)
class DiscoveryRunSummary:
    provider_name: str
    outcomes: tuple[DiscoveryOutcome, ...] = ()
    run_id: str = ""
    source: Source | None = None
    input_path: Path | None = None
    malformed: tuple[str, ...] = ()
    raw_items: tuple[RawItem, ...] = field(default=(), kw_only=True, repr=False)

    @property
    def observed(self) -> int:
        return len(self.outcomes)

    @property
    def discovered(self) -> int:
        return self._count(DiscoveryStatus.DISCOVERED)

    @property
    def events(self) -> int:
        return self._of_type(DiscoveryType.EVENT)

    @property
    def places(self) -> int:
        return self._of_type(DiscoveryType.PLACE)

    @property
    def other(self) -> int:
        return self._of_type(DiscoveryType.OTHER)

    @property
    def skipped(self) -> int:
        return self._count(DiscoveryStatus.SKIPPED)

    @property
    def failed(self) -> int:
        return self._count(DiscoveryStatus.PROVIDER_FAILED) + self._count(DiscoveryStatus.INVALID_OUTPUT)

    @property
    def event_candidates(self) -> tuple[EventCandidate, ...]:
        return tuple(outcome.event for outcome in self.outcomes if outcome.event is not None)

    @property
    def place_candidates(self) -> tuple[PlaceCandidate, ...]:
        return tuple(outcome.place for outcome in self.outcomes if outcome.place is not None)

    @property
    def candidates(self) -> tuple[EventCandidate | PlaceCandidate, ...]:
        return tuple(outcome.candidate for outcome in self.outcomes if outcome.candidate is not None)

    def _count(self, status: DiscoveryStatus) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status is status)

    def _of_type(self, discovery_type: DiscoveryType) -> int:
        return sum(1 for outcome in self.outcomes if outcome.discovery_type is discovery_type)


def run_discovery(
    raw_items: Iterable[RawItem],
    service: DiscoveryService,
    *,
    sources: Mapping[str, Source] | None = None,
    run_id: str = "",
    source: Source | None = None,
    input_path: Path | None = None,
    malformed: tuple[str, ...] = (),
) -> DiscoveryRunSummary:
    """Analyze every RawItem independently; a failed item never discards the others.

    `sources` maps source ids to their configuration, used as optional context.
    Candidates are returned in memory only: EventCandidate and PlaceCandidate are a
    transient boundary and are not persisted. Normalization is a separate, later step.
    """
    known_sources = sources or {}
    raw_items = tuple(raw_items)
    outcomes = tuple(
        service.discover(raw_item, known_sources.get(raw_item.source_id)) for raw_item in raw_items
    )
    return DiscoveryRunSummary(
        provider_name=service.provider_name,
        outcomes=outcomes,
        run_id=run_id,
        source=source,
        input_path=input_path,
        malformed=malformed,
        raw_items=raw_items,
    )


def select_latest(items: Sequence[RawItem], limit: int) -> tuple[RawItem, ...]:
    """The `limit` most recent stored observations, chosen deterministically.

    Newest publish date first, undated items after dated ones, and storage order
    breaking every tie — so the same file and the same limit always select the same
    items, and an item without a publish date never displaces a dated one.
    """
    dated = [item for item in items if item.published_at is not None]
    undated = [item for item in items if item.published_at is None]
    ordered = sorted(dated, key=lambda item: item.published_at, reverse=True) + undated
    return tuple(ordered[:limit])


def run_instagram_discovery(
    source_id: str,
    *,
    config_path: str | Path = "config/sources.yaml",
    data_dir: str | Path = "data",
    limit: int = DEFAULT_LIMIT,
    provider: object | None = None,
) -> DiscoveryRunSummary:
    """Analyze already-collected Instagram observations for one source.

    Strictly a read of local storage: it opens no browser, contacts no source, and
    writes nothing. Collection is a separate, explicit command.
    """
    source = find_source(source_id, config_path)
    store = JsonlRawItemStore(instagram_output_path(source, data_dir))
    stored = store.read_latest_items()

    service = DiscoveryService(provider if provider is not None else RuleBasedDiscoveryProvider())
    return run_discovery(
        select_latest(stored.items, limit),
        service,
        sources={source.id: source},
        run_id=uuid.uuid4().hex[:12],
        source=source,
        input_path=stored.path,
        malformed=stored.malformed,
    )


__all__ = [
    "DiscoveryRunSummary",
    "run_discovery",
    "run_instagram_discovery",
    "select_latest",
]
