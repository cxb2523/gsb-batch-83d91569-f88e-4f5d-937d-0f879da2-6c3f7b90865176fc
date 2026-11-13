"""Optional SQLite-to-Google publishing through the retained Sheets adapter."""
from __future__ import annotations

from dataclasses import fields
from datetime import datetime

from ..deduplication.models import CanonicalizationResult, DuplicateDecision, MatchKind
from ..domain import PlaceCandidate
from ..review.records import event_from_record
from ..review.models import CanonicalRepository, SnapshotResult
from ..review.serialization import ReviewWindow
from .repository import SheetRepository


def publish_persisted(repository: CanonicalRepository, sheets: SheetRepository,
                      run_id: str = 'latest') -> SnapshotResult:
    """Publish stored facts only; Google review remains separate from local review."""
    document = repository.load(run_id)
    run = document['run']
    complete = repository.load(run['run_id'], include_filtered=True)
    events = tuple(event_from_record(record) for record in complete['events'])
    by_id = {event.event_id: event for event in events}
    pairs = tuple(DuplicateDecision((by_id[pair['event_id_a']].candidate_ids[0],
        by_id[pair['event_id_b']].candidate_ids[0]), MatchKind.POSSIBLE_DUPLICATE,
        tuple(pair['reason_codes'])) for pair in document['possible_duplicates'])
    places = tuple(PlaceCandidate(**{field.name: item[field.name] for field in fields(PlaceCandidate)})
                   for item in document['places'])
    result = CanonicalizationResult(events=events, places=places, possible_duplicates=pairs)
    window = ReviewWindow(tuple(by_id[item['event_id']] for item in document['events']),
                          run['filtered'], run['undated'])
    with sheets.state.lock():
        return sheets.sync(result, window, run_id=run['run_id'],
            started_at=datetime.fromisoformat(run['started_at']), finished_at=datetime.fromisoformat(run['finished_at']),
            days=run['days'], review_timezone=run['review_timezone'], source_count=run['source_count'],
            failures=tuple(run['source_failures']), status=run['status'],
            run_metadata={'place_source_ids': {p['raw_item_id']: p['source_id'] for p in document['places']},
                          'initial_event_review': {e['event_id']: (e['review_decision'], e['review_notes']) for e in document['events']},
                          'initial_duplicate_review': {p['pair_key']: (p['review_decision'], p['review_notes']) for p in document['possible_duplicates']}})
