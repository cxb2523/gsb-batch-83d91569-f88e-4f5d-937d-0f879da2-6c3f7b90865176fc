from dataclasses import replace
from datetime import date, datetime, time, timezone

from gatherradar.deduplication import CandidateContext
from gatherradar.domain import EventCandidate, RawItem, Source, SourceType
from gatherradar.domain.temporal import DatePrecision
from gatherradar.normalization.models import NormalizationOutcome, TemporalResult, PriceResult

STAMP = datetime(2026, 9, 1, tzinfo=timezone.utc)


def context(key='a', *, publisher='publisher', seen=STAMP, diagnostics=(), slot='primary', **fields):
    source = Source('source_' + key, publisher, 'Source ' + key, SourceType.WEBSITE, 'https://example.test/' + key)
    raw = RawItem('raw:' + key, source.id, source.source_type, key, 'webpage',
                  'https://example.test/events/' + key, 'sanitized event evidence', seen)
    defaults = dict(title='Moonlight Ceramic Workshop', start_date=date(2026, 10, 1),
                    start_time=time(18), timezone='UTC', date_precision=DatePrecision.EXACT,
                    starts_at=datetime(2026, 10, 1, 18, tzinfo=timezone.utc),
                    venue_name='Blue Gallery', city='Tehran', evidence_url=raw.content_url)
    defaults.update(fields)
    candidate = EventCandidate('candidate:' + key, raw.id, True, **defaults)
    original = replace(candidate, start_date=None, start_time=None, starts_at=None,
                       timezone=None, date_precision=DatePrecision.UNKNOWN)
    return CandidateContext(outcome(candidate, diagnostics), original, raw, source, seen, slot)


def outcome(candidate, diagnostics=()):
    temporal = TemporalResult(**{f: getattr(candidate, f) for f in (
        'start_date', 'end_date', 'start_time', 'end_time', 'timezone', 'starts_at', 'ends_at', 'date_precision')})
    return NormalizationOutcome(candidate, temporal, PriceResult(candidate.price_amount, candidate.currency), diagnostics)


def changed(ctx, **fields):
    candidate = replace(ctx.candidate, **fields)
    return replace(ctx, outcome=outcome(candidate, ctx.outcome.diagnostics))
