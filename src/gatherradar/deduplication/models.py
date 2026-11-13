from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from ..domain import Event, EventCandidate, PlaceCandidate, RawItem, Source
from ..domain.event import CanonicalDiagnostic
from ..normalization.models import NormalizationOutcome


class MatchKind(StrEnum):
    SAME_EVENT = "same_event"
    POSSIBLE_DUPLICATE = "possible_duplicate"
    DISTINCT = "distinct"
    INSUFFICIENT = "insufficient"


@dataclass(frozen=True, slots=True)
class CandidateContext:
    outcome: NormalizationOutcome
    original: EventCandidate | PlaceCandidate
    raw_item: RawItem
    source: Source
    first_seen_at: datetime
    # Stable evidence position, never content hash or candidate ID. Primary text
    # uses 'primary'; a separate media unit uses its earliest kind/position slot.
    identity_slot: str = "primary"

    @property
    def candidate(self) -> EventCandidate | PlaceCandidate:
        return self.outcome.candidate

    @property
    def candidate_id(self) -> str:
        # Validation may be reporting a malformed normalization result. Retain
        # the original identity without letting diagnostic construction fail.
        value = getattr(self.candidate, "candidate_id", None)
        return value if isinstance(value, str) and value else self.original.candidate_id


@dataclass(frozen=True, slots=True)
class DuplicateDecision:
    candidate_ids: tuple[str, str]
    kind: MatchKind
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DuplicateGroup:
    duplicate_group_id: str
    candidate_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CanonicalizationResult:
    events: tuple[Event, ...] = ()
    groups: tuple[DuplicateGroup, ...] = ()
    decisions: tuple[DuplicateDecision, ...] = ()
    possible_duplicates: tuple[DuplicateDecision, ...] = ()
    places: tuple[PlaceCandidate, ...] = ()
    contexts: tuple[CandidateContext, ...] = ()
    rejected: tuple[CandidateContext, ...] = ()
    diagnostics: tuple[CanonicalDiagnostic, ...] = ()

    @property
    def singletons(self) -> tuple[Event, ...]:
        return tuple(event for event in self.events if len(event.candidate_ids) == 1)
