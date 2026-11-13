"""Explicit units from selected observations through current canonical outputs."""
from __future__ import annotations

from .eligibility import eligible


def source_output_funnel(review, window, collection_reports=()) -> list[dict]:
    decisions = {d.event_id: d.disposition for d in window.dispositions}
    reports = {r.source_id: r for r in collection_reports}
    rows = []
    for source in review.sources:
        events = [e for e in review.result.events if source.source.id in e.source_ids and eligible(e)]
        row = dict(source_id=source.source.id, publisher_key=source.source.publisher_key, **source.funnel)
        row.update(canonical_events=len(events),
            actionable_events=sum(decisions.get(e.event_id) == 'actionable' for e in events),
            expired_events=sum(decisions.get(e.event_id) == 'expired' for e in events),
            schedule_review_events=sum(decisions.get(e.event_id) == 'needs_schedule_review' for e in events),
            beyond_horizon_events=sum(decisions.get(e.event_id) == 'beyond_horizon' for e in events),
            otherwise_excluded_events=sum(decisions.get(e.event_id) == 'otherwise_excluded' for e in events),
            media_capture_failure_reported=bool(source.source.id in reports and
                'media_evidence_partial' in reports[source.source.id].failures),
            investigations=list(source.investigations))
        rows.append(row)
    return rows
