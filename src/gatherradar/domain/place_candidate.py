from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlaceCandidate:
    """A venue a community could visit, as discovered in one source observation.

    Deliberately separate from EventCandidate: a gallery that exists has no date,
    registration, or occurrence, and forcing it into an event record would invent
    exactly the facts GatherRadar must not invent. Unknown values stay None, and
    like EventCandidate this is a transient boundary that is not persisted yet.
    """

    candidate_id: str
    raw_item_id: str
    title: str | None = None
    summary: str | None = None
    category: str | None = None
    address: str | None = None
    city: str | None = None
    opening_hours_text: str | None = None
    price_text: str | None = None
    language: str | None = None
    evidence_url: str | None = None

    def __post_init__(self) -> None:
        if not self.candidate_id.strip() or not self.raw_item_id.strip():
            raise ValueError("candidate_id and raw_item_id must not be empty")
