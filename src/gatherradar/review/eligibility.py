"""One admission policy for canonical review persistence and Event exports.

Extraction may retain incomplete candidates for offline reprocessing. Admission
requires a real title attributed to a source candidate; confidence is not proof.
This module never repairs titles or mutates evidence or historical records.
"""
from __future__ import annotations

import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping

from ..domain import Event


def _get(value, key, default=None):
    return value.get(key, default) if isinstance(value, Mapping) else getattr(value, key, default)


def _title_key(value: str) -> str:
    value = unicodedata.normalize('NFKC', value).casefold().translate(
        str.maketrans({'ي': 'ی', 'ك': 'ک'}))
    return ' '.join(''.join(
        ' ' if unicodedata.category(c)[0] in {'P', 'S', 'Z'} or c == '\u200c'
        else '' if unicodedata.category(c)[0] in {'C', 'M'}
        else c for c in value).split())


_PLACEHOLDERS = frozenset(_title_key(v) for v in (
    'Untitled', 'Untitled Event', 'Unknown', 'Unknown Event', 'No Title',
    'Title Unknown', 'N/A', 'None', 'Null', 'TBD', 'رویداد بدون عنوان',
    'بدون عنوان', 'عنوان نامشخص', 'رویداد نامشخص', 'نامشخص',
    'رویداد', 'ایونت', 'ایونت جدید', 'نمایشگاه انفرادی', 'کارگاه', 'ورکشاپ',
))


def exclusion_reason(event: Event | Mapping) -> str | None:
    """Return a stable diagnostic, or None for a source-attributed real title."""
    from ..extraction.detection import context_diagnostic
    detection = _get(event, 'event_detection_reason') or ''
    if detection.startswith(('non_event:', 'needs_evidence:')):
        return 'not_established_event'
    # Legacy records with retained captions can still be screened without
    # rewriting historical snapshots. Absent evidence is never invented.
    description = _get(event, 'description_text')
    if description and context_diagnostic(description):
        return 'not_established_event'
    title = _get(event, 'title')
    if not isinstance(title, str) or not (key := _title_key(title)) or not any(c.isalnum() for c in key):
        return 'missing_title'
    if key in _PLACEHOLDERS:
        return 'placeholder_title'
    origin = _get(event, 'display_title_origin')
    if origin:
        from ..extraction.titles import descriptive_title
        from ..extraction.text import title_equivalence_key
        span = _get(event, 'title_evidence_text')
        evidence = set(_get(event, 'display_title_evidence_ids', ()) or ())
        if (not span or not evidence or not evidence.issubset(set(_get(event, 'evidence_fragment_ids', ()) or ()))):
            return 'unsupported_title'
        if origin == 'derived_from_source_description':
            derived = descriptive_title(span)
            if not derived or title_equivalence_key(derived) != title_equivalence_key(title):
                return 'unsupported_title'
        elif origin not in {'explicit_website', 'explicit_caption', 'explicit_media_ocr', 'extracted_from_description'}:
            return 'unsupported_title'
        else:
            words, source_words = title_equivalence_key(title), iter(title_equivalence_key(span))
            if not all(any(w == wanted for w in source_words) for wanted in words):
                return 'unsupported_title'
    candidates = set(_get(event, 'candidate_ids', ()) or ())
    title_sources = [p for p in (_get(event, 'field_provenance', ()) or ())
                     if _get(p, 'field') == 'title']
    if (not _get(event, 'source_ids') or not _get(event, 'canonical_source_url')
            or not any(_get(p, 'candidate_ids') and
                       set(_get(p, 'candidate_ids')).issubset(candidates) for p in title_sources)):
        return 'unsupported_title'
    return None


def eligible(event: Event | Mapping) -> bool:
    return exclusion_reason(event) is None


def eligibility_summary(events: Iterable[Event | Mapping]) -> dict:
    events = tuple(events)
    excluded = [e for e in events if not eligible(e)]
    by_source = Counter(source for event in excluded
                        for source in set(_get(event, 'source_ids', ()) or ('unknown',)))
    return dict(discovered_event_count=len(events),
                excluded_event_count=len(excluded),
                # Aggregate: no reliable source title, including placeholders.
                excluded_missing_title=len(excluded),
                excluded_missing_title_by_source=dict(sorted(by_source.items())),
                title_exclusion_reasons=dict(Counter(exclusion_reason(e) for e in excluded)),
                canonical_event_count=len(events) - len(excluded))


def eligible_document(document: dict) -> dict:
    """Idempotent export guard, including callers supplying legacy documents.

    SQLite supplies full-run counts. A direct document projection can only count
    exclusions in its supplied rows; it preserves any earlier exclusion totals.
    """
    removed = [e for e in document['events'] if not eligible(e)]
    events = [e for e in document['events'] if eligible(e)]
    excluded_ids = {e['event_id'] for e in removed}
    pairs = [p for p in document['possible_duplicates']
             if not excluded_ids.intersection((p['event_id_a'], p['event_id_b']))]
    run = dict(document['run'])
    if removed:
        summary = eligibility_summary(removed)
        sources = Counter(run.get('excluded_missing_title_by_source', {}))
        sources.update(summary['excluded_missing_title_by_source'])
        reasons = Counter(run.get('title_exclusion_reasons', {}))
        reasons.update(summary['title_exclusion_reasons'])
        previous_canonical = run.get('canonical_event_count', len(document['events']) + run.get('filtered', 0))
        run.setdefault('discovered_event_count', previous_canonical + run.get('excluded_event_count', 0))
        run.update(excluded_event_count=run.get('excluded_event_count', 0) + len(removed),
                   excluded_missing_title=run.get('excluded_missing_title', 0) + len(removed),
                   excluded_missing_title_by_source=dict(sorted(sources.items())),
                   title_exclusion_reasons=dict(reasons),
                   canonical_event_count=previous_canonical - len(removed),
                   undated=sum(_undated(e) for e in events))
    run.update(event_count=len(events), duplicate_count=len(pairs))
    run['data_readiness_counts'] = dict(Counter(e['data_readiness'] for e in events if 'data_readiness' in e))
    return dict(document, run=run, events=events, possible_duplicates=pairs)


def _undated(event) -> bool:
    return (_get(event, 'schedule_kind') in {'recurring', 'conflict'}
            or (not any(_get(o, 'start_date') for o in (_get(event, 'occurrences', ()) or ()))
                and (not _get(event, 'start_date') or _get(event, 'date_precision') == 'unknown')))
