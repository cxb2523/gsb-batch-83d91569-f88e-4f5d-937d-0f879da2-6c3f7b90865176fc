"""Evidence-audited field retention, with explicit earliest-loss attribution.

An expectation is a review assertion, not an extractor guess. A missing output
alone can never establish SOURCE_MISSING or EXTRACTION_BUG.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping, Sequence


class CoverageOutcome(StrEnum):
    MATCHED = "MATCHED"
    SOURCE_MISSING = "SOURCE_MISSING"
    EXTRACTION_BUG = "EXTRACTION_BUG"
    AMBIGUOUS = "AMBIGUOUS"
    ACCESS_RESTRICTED = "ACCESS_RESTRICTED"
    INTENTIONALLY_UNSUPPORTED = "INTENTIONALLY_UNSUPPORTED"
    CONFLICT = "CONFLICT"


STAGES = ("collection", "evidence", "grouping", "extraction", "normalization",
          "canonicalization", "persistence", "export")


@dataclass(frozen=True)
class FieldAudit:
    event_id: str
    field: str
    outcome: CoverageOutcome
    evidence_reference: str
    explanation: str
    earliest_loss: str | None = None
    publisher: str = ""
    source: str = ""
    channel: str = ""
    evidence_type: str = ""
    readiness: str = ""


def audit_field(*, event_id: str, field: str, evidence_reference: str,
                explanation: str, stages: Mapping[str, bool | None] | None = None,
                unresolved: CoverageOutcome | None = None, **dimensions: str) -> FieldAudit:
    """Check one explicitly verified source fact through ordered boundaries.

    `True` means verified retained, `False` means verified lost, and `None` means
    not inspected. An uninspected preceding stage prevents an earliest-loss claim.
    A fact may first become structured in extraction; earlier booleans mean its
    source wording/evidence survived, not that a structured field existed yet.
    """
    if not event_id or not field or not evidence_reference or not explanation:
        raise ValueError("An audit needs identity, evidence reference and an explanation")
    if set(dimensions) - {"publisher", "source", "channel", "evidence_type", "readiness"}:
        raise ValueError("Unknown audit dimension")
    if unresolved is not None:
        if unresolved in {CoverageOutcome.MATCHED, CoverageOutcome.EXTRACTION_BUG} or stages:
            raise ValueError("Use stage checks for matched or lost source facts")
        return FieldAudit(event_id, field, unresolved, evidence_reference, explanation, **dimensions)
    checks = dict(stages or {})
    if set(checks) - set(STAGES) or any(v is not None and type(v) is not bool for v in checks.values()):
        raise ValueError("Invalid audit stage checks")
    unknown_before = False
    for stage in STAGES:
        check = checks.get(stage)
        if check is None:
            unknown_before = True
        elif check is False:
            return FieldAudit(event_id, field, CoverageOutcome.EXTRACTION_BUG, evidence_reference,
                explanation, None if unknown_before else stage, **dimensions)
    outcome = CoverageOutcome.AMBIGUOUS if unknown_before else CoverageOutcome.MATCHED
    return FieldAudit(event_id, field, outcome, evidence_reference, explanation, **dimensions)


def coverage_summary(rows: Sequence[FieldAudit]) -> dict:
    """Counts, never a fabricated completeness percentage or probability."""
    dimensions = ("publisher", "source", "channel", "field", "evidence_type", "readiness")
    grouped = {name: defaultdict(Counter) for name in dimensions}
    for row in rows:
        for name in dimensions:
            grouped[name][getattr(row, name) or "unknown"][row.outcome.value] += 1
    return {"total": len(rows), "outcomes": dict(Counter(r.outcome.value for r in rows)),
            "by": {name: {key: dict(counts) for key, counts in sorted(values.items())}
                   for name, values in grouped.items()}}
