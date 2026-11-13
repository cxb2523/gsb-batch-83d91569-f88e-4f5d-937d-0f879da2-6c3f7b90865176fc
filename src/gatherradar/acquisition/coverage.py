"""Publisher coverage: represented publishers versus healthy channels."""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import replace

from ..domain import Event
from .models import ChannelResult, ChannelStatus, PublisherCoverage
from .strategies import CHANNEL_STRUCTURED_FIELDS

_HEALTHY = frozenset({ChannelStatus.SUCCESS, ChannelStatus.EMPTY, ChannelStatus.STORED})


def publisher_coverage(results: Sequence[ChannelResult]) -> tuple[PublisherCoverage, ...]:
    """A publisher is covered when any channel contributed current-run observations."""
    coverage = []
    for publisher in sorted({r.publisher_key for r in results}):
        own = [r for r in results if r.publisher_key == publisher]
        contributing = [r for r in own if r.status in (ChannelStatus.SUCCESS, ChannelStatus.STORED) and r.observed]
        unavailable = [r for r in own if r.status not in _HEALTHY]
        covering_fields = set().union(*(CHANNEL_STRUCTURED_FIELDS.get(r.channel, ()) for r in contributing))
        # A channel that failed but whose peer of the same kind contributed does
        # not reduce coverage (for example two website listings of one publisher).
        missing_channels = {r.channel for r in unavailable} - {r.channel for r in contributing}
        potentially = set().union(*(CHANNEL_STRUCTURED_FIELDS.get(c, ()) for c in missing_channels)) - covering_fields
        coverage.append(PublisherCoverage(
            publisher, bool(contributing), not unavailable,
            tuple((r.source_id, r.strategy, r.status.value) for r in own),
            tuple(sorted({r.source_id for r in contributing})),
            tuple(sorted({r.source_id for r in unavailable})),
            tuple(sorted(potentially)) if contributing else ()))
    return tuple(coverage)


def with_channel_gaps(events: Iterable[Event], coverage: Iterable[PublisherCoverage]) -> tuple[Event, ...]:
    """Mark null fields an unavailable channel of the Event's publisher usually supplies.

    This distinguishes "missing because a channel was unavailable" from "the source
    did not expose it". Facts are never filled; only the reason for absence is kept.
    """
    reduced = {c.publisher_key: set(c.potentially_unavailable_fields) for c in coverage}
    marked = []
    for event in events:
        fields = set().union(*(reduced.get(p, ()) for p in event.publisher_keys))
        gaps = tuple(sorted(f for f in fields if getattr(event, f, None) is None))
        marked.append(replace(event, channel_gaps=gaps) if gaps != event.channel_gaps else event)
    return tuple(marked)
