"""Publisher → channel → strategy result model.

A publisher (``publisher_key``) is represented through one or more channels (a
configured Source: its website, its Instagram account, ...). Each channel is
acquired by a strategy. Channel health and publisher coverage are separate facts:
a publisher is covered when at least one channel contributed current-run data,
even while another channel is policy-blocked.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from ..collectors.base import (AuthenticationRequiredError, SourceAccessRestrictedError, SourceDisabledError,
                               SourceUnavailableError, safe_failure)
from ..domain import RawItem


class ChannelStatus(StrEnum):
    SUCCESS = 'success'
    EMPTY = 'empty'
    UNAVAILABLE = 'unavailable'
    POLICY_BLOCKED = 'policy_blocked'
    ACCESS_RESTRICTED = 'access_restricted'
    TEMPORARY_FAILURE = 'temporary_failure'
    PARSE_FAILURE = 'parse_failure'
    # Offline `--stored` analysis: existing observations, nothing acquired.
    STORED = 'stored'


# Deliberately unavailable channels: skipping them is expected, not a run defect.
DELIBERATE = frozenset({ChannelStatus.POLICY_BLOCKED})
_TEMPORARY = frozenset({'dns', 'timeout', 'network', 'tls'})
_PARSE = frozenset({'layout', 'encoding', 'content_type'})


def classify_failure(exc: BaseException) -> ChannelStatus:
    """Map a collector failure onto the fixed channel vocabulary; never by message."""
    category = getattr(exc, 'category', None)
    status = getattr(exc, 'http_status', None)
    if isinstance(exc, SourceDisabledError):
        return ChannelStatus.UNAVAILABLE
    if isinstance(exc, SourceAccessRestrictedError) and category == 'robots':
        return ChannelStatus.POLICY_BLOCKED
    if isinstance(exc, (AuthenticationRequiredError, SourceAccessRestrictedError)):
        return ChannelStatus.TEMPORARY_FAILURE if status == 429 else ChannelStatus.ACCESS_RESTRICTED
    if category in _TEMPORARY or (type(status) is int and (status == 429 or status >= 500)):
        return ChannelStatus.TEMPORARY_FAILURE
    if category in _PARSE:
        return ChannelStatus.PARSE_FAILURE
    if isinstance(exc, SourceUnavailableError):
        return ChannelStatus.UNAVAILABLE
    return ChannelStatus.TEMPORARY_FAILURE


def disabled_status(reason: str | None) -> ChannelStatus:
    return ChannelStatus.POLICY_BLOCKED if reason in ('robots', 'terms') else ChannelStatus.UNAVAILABLE


@dataclass(frozen=True)
class ChannelResult:
    """One channel execution. `items` stay in memory; only the rest is persisted."""

    source_id: str
    publisher_key: str
    channel: str
    strategy: str
    status: ChannelStatus
    observed: int = 0
    diagnostic: str | None = None
    items: tuple[RawItem, ...] = field(default=(), repr=False, compare=False)
    new: int = 0
    changed: int = 0
    existing: int = 0

    def record(self) -> dict:
        return {'source_id': self.source_id, 'publisher_key': self.publisher_key, 'channel': self.channel,
                'strategy': self.strategy, 'status': self.status.value, 'observed': self.observed,
                'diagnostic': self.diagnostic}


def failure_result(source_id: str, publisher_key: str, channel: str, strategy: str,
                   exc: BaseException) -> ChannelResult:
    return ChannelResult(source_id, publisher_key, channel, strategy, classify_failure(exc),
                         diagnostic=safe_failure(exc) if isinstance(exc, Exception) else None)


@dataclass(frozen=True)
class PublisherCoverage:
    publisher_key: str
    covered: bool
    all_channels_healthy: bool
    channels: tuple[tuple[str, str, str], ...]  # (source_id, strategy, status)
    covered_by: tuple[str, ...] = ()
    unavailable_channels: tuple[str, ...] = ()
    # Fields an unavailable channel normally supplies that the covering channels
    # do not state structurally: coverage may be reduced for these.
    potentially_unavailable_fields: tuple[str, ...] = ()

    def record(self) -> dict:
        return {'publisher': self.publisher_key, 'covered': self.covered,
                'all_channels_healthy': self.all_channels_healthy,
                'channels': [{'source_id': s, 'strategy': t, 'status': st} for s, t, st in self.channels],
                'covered_by': list(self.covered_by), 'unavailable_channels': list(self.unavailable_channels),
                'potentially_unavailable_fields': list(self.potentially_unavailable_fields)}
