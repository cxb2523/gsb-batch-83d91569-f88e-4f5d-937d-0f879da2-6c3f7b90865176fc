"""Pure review presentation; no spreadsheet client or source mutation."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, time, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from persiantools.jdatetime import JalaliDate

from ..deduplication.models import CanonicalizationResult, MatchKind
from ..deduplication.keys import stable_id
from ..domain import Event, PlaceCandidate
from ..domain.temporal import DatePrecision
from .schema import DECISIONS
from .readiness import assess_readiness
from .eligibility import eligible, _undated

WEEKDAYS = ('دوشنبه', 'سه‌شنبه', 'چهارشنبه', 'پنجشنبه', 'جمعه', 'شنبه', 'یکشنبه')
MONTHS = ('فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور',
          'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند')
STATUS = {'unknown': 'نامشخص', 'upcoming': 'پیش رو', 'expired': 'پایان یافته',
          'cancelled': 'لغو شده', 'postponed': 'به تعویق افتاده', 'sold_out': 'تکمیل ظرفیت'}
FORMATS = {'in_person': 'حضوری', 'online': 'آنلاین', 'hybrid': 'ترکیبی', 'unknown': 'نامشخص'}
REASONS = {
    'exact_date_match': 'تاریخ یکسان', 'uncertain_date_match': 'تاریخ مشابه با قطعیت ناکافی',
    'uncertain_date_difference': 'اختلاف در تاریخ نامطمئن',
    'distinctive_title_exact': 'عنوان متمایز یکسان', 'distinctive_title_strong': 'عنوان بسیار مشابه',
    'title_similarity_only': 'شباهت عنوان به‌تنهایی کافی نیست', 'city_match': 'شهر یکسان',
    'venue_name_match': 'نام مکان یکسان', 'address_match': 'آدرس یکسان',
    'start_time_match': 'زمان شروع یکسان', 'end_time_match': 'زمان پایان یکسان',
    'uncertain_start_time_difference': 'اختلاف در ساعت شروع نامطمئن',
    'uncertain_end_time_difference': 'اختلاف در ساعت پایان نامطمئن',
    'registration_url_match': 'پیوند ثبت‌نام یکسان', 'different_registration_urls': 'پیوندهای ثبت‌نام متفاوت',
    'same_publisher': 'ناشر مشترک', 'insufficient_occurrence_evidence': 'شواهد برای یکی دانستن رویداد کافی نیست',
    'same_source_page': 'صفحه منبع یکسان',
    'all_member_grouping_blocked': 'همه اعضای گروه با هم سازگار نیستند',
}


def persian(value: object) -> str:
    return str(value).translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))


def jalali(value: date | None) -> str:
    if value is None:
        return ''
    j = JalaliDate(value)
    return f'{persian(j.day)} {MONTHS[j.month - 1]} {persian(j.year)}'


def url(value: str | None) -> str:
    if not value:
        return ''
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {'https', 'http'} or not parsed.hostname or parsed.username
                or parsed.password or any(c.isspace() or ord(c) < 32 for c in value)):
            raise ValueError
        parsed.port
    except (ValueError, TypeError):
        raise ValueError('invalid review URL') from None
    return value


def encoded(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def iso(value: object) -> str:
    return value.isoformat() if value is not None else ''


def quality(event: Event) -> str:
    if any('conflict' in d.code or 'unresolved_temporal' in d.code for d in event.diagnostics):
        return 'تعارض داده'
    if not event.occurrences and (event.start_date is None or event.date_precision is DatePrecision.UNKNOWN):
        return 'تاریخ نامشخص'
    if event.diagnostics or event.date_precision is DatePrecision.INFERRED:
        return 'نیاز به بررسی'
    if not event.title or not event.event_format or (not event.venue_name and event.event_format != 'online'):
        return 'اطلاعات ناقص'
    return 'کامل'


def price(event: Event) -> str:
    if event.price_text:
        return event.price_text
    if event.price_amount is None:
        return ''
    if event.price_amount == 0:
        return 'رایگان'
    unit = {'TOMAN': 'تومان', 'IRR': 'ریال'}.get(event.currency, event.currency or '')
    return f'{persian(format(event.price_amount, "f"))} {unit}'.strip()


def booking(event: Event) -> str:
    """Booking status in plain Persian, kept apart from temporal relevance.

    The source's own availability wording wins. Otherwise per-session source
    facts are described as facts, never as a promise that a seat can be booked:
    a sellout flag, a flag contradicted by seat counts, or the first listed
    session's remaining seats.
    """
    if event.availability_text:
        return event.availability_text
    ordered = sorted(event.occurrences, key=lambda o: (o.start_date, o.start_time is None,
                                                       o.start_time or time.min, o.occurrence_id))
    if any('sold_out_availability_conflict' in c for o in ordered for c in o.diagnostics):
        return 'علامت «تکمیل ظرفیت» و تعداد صندلی در منبع ناسازگار است؛ در منبع بررسی کنید'
    flagged = [o for o in ordered if o.source_sold_out is True]
    if flagged:
        if len(flagged) == len(ordered):
            return 'منبع همه جلسه‌ها را «تکمیل ظرفیت» علامت زده است'
        return f'منبع {persian(len(flagged))} از {persian(len(ordered))} جلسه را «تکمیل ظرفیت» علامت زده است'
    seats = next((o for o in ordered if o.remaining_seats is not None), None)
    if seats is not None:
        when = jalali(seats.start_date) + (('، ' + persian(seats.start_time.strftime('%H:%M')))
                                           if seats.start_time else '')
        return (f'صندلی باقی‌مانده طبق منبع: {persian(seats.remaining_seats)} (جلسه {when})؛ '
                'امکان رزرو را در منبع بررسی کنید')
    return ''


def schedule(event: Event) -> str:
    """Visible source schedule wording, without repeating a fully modelled date.

    Multi-session/recurring wording is always shown. Otherwise the primary
    source date text is shown only when normalized date/time is incomplete,
    inferred or diagnosed; the full machine values stay in portable exports.
    """
    if event.source_schedule_text:
        return event.source_schedule_text
    incomplete = (event.start_date is None
                  or event.date_precision in {DatePrecision.UNKNOWN, DatePrecision.INFERRED}
                  or any(d.field in {'temporal', 'source_date_text'} for d in event.diagnostics))
    return (event.source_date_text or '') if incomplete else ''


def event_row(event: Event, run_id: str, human: tuple[str, str] | None = None) -> list:
    from .records import primitive
    decision, note = human if human is not None else (DECISIONS[0], '')
    readiness = assess_readiness(event)
    links = sorted({url(u) for u in (*event.evidence_urls, event.canonical_source_url) if u})
    visible = [decision, event.title, event.category, STATUS[event.status.value],
        jalali(event.start_date), WEEKDAYS[event.start_date.weekday()] if event.start_date else '',
        persian(event.start_time.strftime('%H:%M')) if event.start_time else '', jalali(event.end_date),
        persian(event.end_time.strftime('%H:%M')) if event.end_time else '', schedule(event),
        event.venue_name, event.area_text, event.city, event.address, event.duration_text, price(event),
        booking(event), FORMATS.get(event.event_format, ''), event.description_text,
        event.organizer_name, url(event.registration_url), url(event.canonical_source_url), '\n'.join(links),
        len(event.source_ids) or len(links), quality(event), note,
        readiness.label, readiness.explanation, occurrence_text(event)]
    technical = [event.event_id, run_id, iso(event.start_date), iso(event.end_date), event.timezone,
        event.date_precision.value, iso(event.starts_at), iso(event.ends_at),
        str(event.price_amount) if event.price_amount is not None else '', event.currency,
        event.source_date_text, event.source_schedule_text, encoded(event.source_ids), encoded(event.publisher_keys),
        encoded(event.candidate_ids), encoded(event.source_item_ids), encoded(links),
        url(event.canonical_source_url), encoded([asdict(d) for d in event.diagnostics]),
        iso(event.first_seen_at), iso(event.last_seen_at), event.duplicate_group_id,
        encoded([asdict(p) for p in event.field_provenance]), event.extraction_confidence,
        encoded(primitive(event.occurrences)), event.schedule_kind.value, event.recurrence_rule,
        readiness.status.value, encoded(readiness.reasons), encoded(readiness.indicators),
        event.source_title, event.display_title_origin, encoded(event.display_title_evidence_ids),
        event.title_evidence_text, event.title_review_required, event.event_detection_reason]
    return [v if v is not None else '' for v in visible + technical]


def occurrence_text(event: Event) -> str:
    rows = []
    # Chronological for reading; stored occurrence order and identity are unchanged.
    ordered = sorted(event.occurrences, key=lambda o: (o.start_date, o.start_time is None,
                                                       o.start_time or time.min, o.occurrence_id))
    for occurrence in ordered:
        text = jalali(occurrence.start_date)
        if occurrence.end_date:
            text += ' تا ' + jalali(occurrence.end_date)
        if occurrence.start_time:
            text += '، ' + persian(occurrence.start_time.strftime('%H:%M'))
        if occurrence.end_time:
            text += ' تا ' + persian(occurrence.end_time.strftime('%H:%M'))
        if occurrence.price_text:
            text += ' — ' + occurrence.price_text
        if occurrence.availability_text:
            text += ' — ' + occurrence.availability_text
        rows.append(text)
    return '\n'.join(rows)


def place_row(place: PlaceCandidate, run_id: str, source_id: str) -> list:
    return [v if v is not None else '' for v in [DECISIONS[0], place.title, place.category,
        place.city, place.address, place.opening_hours_text, place.price_text, place.summary,
        url(place.evidence_url), '', place.candidate_id, place.raw_item_id, source_id,
        run_id, url(place.evidence_url)]]


@dataclass(frozen=True)
class ReviewWindow:
    events: tuple[Event, ...]
    filtered: int
    undated: int
    schedule_review: tuple[Event, ...] = ()
    dispositions: tuple = ()


def review_window(events: tuple[Event, ...], started_at: datetime, days: int = 14,
                  review_timezone: str = 'Asia/Tehran') -> ReviewWindow:
    from .relevance import assess_relevance
    # Validate even empty input.
    if type(days) is not int or not 1 <= days <= 90:
        raise ValueError('days must be between 1 and 90')
    if started_at.tzinfo is None or started_at.utcoffset() is None:
        raise ValueError('run start must be timezone-aware')
    ZoneInfo(review_timezone)
    accepted = tuple(e for e in events if eligible(e))
    decisions = tuple(assess_relevance(e, started_at, days, review_timezone) for e in accepted)
    retained = [e for e, d in zip(accepted, decisions) if d.disposition == 'actionable']
    review = tuple(e for e, d in zip(accepted, decisions) if d.disposition == 'needs_schedule_review')
    by_id = {d.event_id: d for d in decisions}
    def ordering(event):
        visible = [o for o in event.occurrences if o.occurrence_id in by_id[event.event_id].occurrence_ids]
        first = min(visible, key=lambda o: (o.start_date, iso(o.start_time))) if visible else event
        return (first.start_date or date.max, first.start_time is None, iso(first.start_time),
                event.title or '', event.event_id)
    retained.sort(key=ordering)
    return ReviewWindow(tuple(retained), len(accepted) - len(retained), len(review), review, decisions)


def eligible_review(result: CanonicalizationResult, window: ReviewWindow
                    ) -> tuple[CanonicalizationResult, ReviewWindow]:
    events = tuple(e for e in result.events if eligible(e))
    visible = tuple(e for e in window.events if eligible(e))
    review = tuple(e for e in window.schedule_review if eligible(e))
    ids = {e.event_id for e in events}
    return replace(result, events=events), ReviewWindow(
        visible, len(events) - len(visible), len(review), review,
        tuple(d for d in window.dispositions if d.event_id in ids))


def snapshot_title(kind: str, started_at: datetime, review_timezone: str) -> str:
    local = started_at.astimezone(ZoneInfo(review_timezone))
    return f'{kind}_{JalaliDate(local.date()).isoformat()}_{local:%H%M}'


def duplicate_rows(result: CanonicalizationResult, run_id: str) -> list[list]:
    membership = {cid: e for e in result.events if eligible(e) for cid in e.candidate_ids}
    rows = {}
    for pair in result.possible_duplicates:
        if pair.kind is not MatchKind.POSSIBLE_DUPLICATE:
            continue
        a, b = (membership.get(cid) for cid in pair.candidate_ids)
        if a is None or b is None or a.event_id == b.event_id:
            continue
        a, b = sorted((a, b), key=lambda e: e.event_id)
        key = stable_id('pair:', (a.event_id, b.event_id))
        # Aggregate candidate-level reasons for the same canonical pair.
        reasons = set(pair.reasons)
        if key in rows:
            reasons.update(rows[key][7].split('\n'))
        rows[key] = [DECISIONS[0], a.title or '', jalali(a.start_date),
            '\n'.join(url(u) for u in a.evidence_urls), b.title or '', jalali(b.start_date),
            '\n'.join(url(u) for u in b.evidence_urls), '\n'.join(sorted(reasons)), '',
            key, a.event_id, b.event_id, run_id, run_id]
    output = []
    for key in sorted(rows):
        row = rows[key]
        codes = row[7].split('\n')
        row[7] = '\n'.join(dict.fromkeys(REASONS.get(code, 'نیاز به بررسی شواهد') for code in codes))
        row.append(encoded(codes))
        output.append(row)
    return output
