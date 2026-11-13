"""Source-neutral date/time composition, reference selection, and timezone validation."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..domain import RawItem, Source
from ..domain.temporal import DatePrecision
from ..domain.occurrence import EventOccurrence, ScheduleKind, identify_occurrence
from .dates import parse_dates, MONTHS
from .models import Diagnostic, Severity, TemporalResult
from .text import fold
from .times import parse_times

_RECURRING = re.compile(r"(?<!\w)(?:هر\s*(?:هفته|روز|شب|ماه|شنبه|یکشنبه|دوشنبه|سه شنبه|چهارشنبه|پنجشنبه|جمعه)|روزانه|هفتگی|ساعات بازدید|every|daily|weekly)(?!\w)")
_WEEKLY_DAYS = {"دوشنبه": "MO", "سه شنبه": "TU", "سهشنبه": "TU", "چهارشنبه": "WE",
                "پنجشنبه": "TH", "پنج شنبه": "TH", "جمعه": "FR", "شنبه": "SA",
                "یکشنبه": "SU", "یک شنبه": "SU"}
_DAY_NAMES = "(?:" + "|".join(sorted(_WEEKLY_DAYS, key=len, reverse=True)) + ")"
_WEEKLY = re.compile(rf"^(?:(?:هر\s+(?P<every>{_DAY_NAMES}))|(?P<plural>{_DAY_NAMES})\s*ها)(?!\w)\s*")
_DAILY = re.compile(r"^(?:هر\s*(?:روز|شب)|روزانه|daily|every day)(?!\w)\s*")


def _local_datetime(day, clock, zone: ZoneInfo) -> datetime | None:
    """Reject DST gaps and folds rather than arbitrarily choosing an offset."""
    naive = datetime.combine(day, clock)
    first, second = naive.replace(tzinfo=zone, fold=0), naive.replace(tzinfo=zone, fold=1)
    if first.utcoffset() != second.utcoffset():
        return None
    if first.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != naive:
        return None
    return first


def normalize_temporal(source_text: str | None, raw_item: RawItem, source: Source) -> TemporalResult:
    reference = raw_item.published_at if raw_item.published_at is not None else raw_item.captured_at
    basis = "published_at" if raw_item.published_at is not None else "captured_at"
    context = {"reference_at": reference, "reference_basis": basis}
    try:
        zone = ZoneInfo(source.timezone)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return TemporalResult(**context, diagnostics=(Diagnostic("invalid_timezone", "timezone", "Configured IANA timezone is invalid or unavailable.", Severity.ERROR),))
    context["timezone"] = source.timezone
    if not isinstance(reference, datetime) or reference.tzinfo is None or reference.utcoffset() is None:
        return TemporalResult(**context, diagnostics=(Diagnostic("invalid_reference", "reference_at", "Stored reference must be an aware datetime.", Severity.ERROR),))
    if source_text is None or not source_text.strip():
        return TemporalResult(**context, diagnostics=(Diagnostic("missing_date", "source_date_text", "No temporal wording was supplied."),))
    if len(source_text) > 4096:
        return TemporalResult(**context, diagnostics=(Diagnostic("temporal_too_long", "source_date_text", "Temporal wording exceeds parsing limit."),))
    text = fold(source_text).lstrip(" 📅🗓⏰🕒")
    text = re.sub(r'^(?:زمان|تاریخ)\s*[:：]\s*', '', text)
    date_head = r'\d{1,2}\s+(?:' + '|'.join(MONTHS) + r')(?:\s*ماه)?'
    clauses = re.split(r'\s*[،,؛;]\s*(?=' + date_head + r')', text)
    if 1 < len(clauses) <= 20:
        parts = [normalize_temporal(clause, raw_item, source) for clause in clauses]
        if all(p.occurrences and len(p.occurrences) == 1 for p in parts):
            occurrences = tuple(o for p in parts for o in p.occurrences)
            return TemporalResult(**context, occurrences=occurrences, schedule_kind=ScheduleKind.DISCRETE,
                                  diagnostics=tuple(dict.fromkeys(d for p in parts for d in p.diagnostics)))
    if raw_item.published_at is None and re.search(r'(?<!\w)(امروز|فردا|today|tomorrow)(?!\w)', text):
        return TemporalResult(**context, diagnostics=(Diagnostic('unknown_publication_reference', 'source_date_text',
            'Relative announcements require their original publication timestamp.'),))
    weekly = _WEEKLY.match(text)
    daily = _DAILY.match(text)
    recurring = bool(_RECURRING.search(text) or weekly)
    dates = parse_dates(text, reference.astimezone(zone).date())
    diagnostics = list(dates.diagnostics)
    if dates.blocked:
        return TemporalResult(**context, diagnostics=tuple(diagnostics))
    remainder = dates.remainder.strip()
    if dates.start is not None or dates.discrete_dates:
        remainder = re.sub(r"^(?:از\s+)?(?:تاریخ\s*[:：]?\s*)?", "", remainder).strip()
        remainder = remainder.lstrip(" :：|,،؛;.·•📅🗓⏰🕒")
        # A dash separates the date and a labelled clock; it is not a negative
        # hour. Keep negative/malformed standalone clocks rejected.
        remainder = re.sub(r"^[-–—|]\s*(?=(?:از\s+)?ساعت\b|[0-9]{1,2}:[0-9]{2}\b)", "", remainder).strip()
    if weekly:
        remainder = _WEEKLY.sub("", remainder, count=1).strip()
    elif daily:
        remainder = _DAILY.sub("", remainder, count=1).strip()
    hours_exception = False
    if dates.end is not None:
        cleaned, count = re.subn(r'\(\s*' + _DAY_NAMES + r'\s*ها\s+تعطیل\s*\)', '', remainder)
        if count:
            remainder, hours_exception = cleaned.strip(), True
    times = parse_times(remainder)
    diagnostics.extend(times.diagnostics)
    if hours_exception:
        diagnostics.append(Diagnostic('visiting_hours_exception', 'source_schedule_text',
                                      'Date range is established; daily closure exceptions require confirmation.'))
    if recurring:
        diagnostics.append(Diagnostic("recurring_schedule", "source_date_text", "Recurring or visiting hours are not an occurrence interval."))
    if dates.end is not None and times.start is not None:
        diagnostics.append(Diagnostic("multi_day_hours", "source_date_text", "Date bounds and hours do not establish a continuous multi-day interval."))
    if dates.start is None and not dates.discrete_dates:
        diagnostics.append(Diagnostic("missing_date", "source_date_text", "No supported calendar date; time alone is partial."))
    starts_at = ends_at = None
    # Any unconsumed prose, recurrence, invalid clock or reversed time blocks composition.
    # Inferred year is reviewable but does not prevent deterministic composition.
    safe = all(d.code in {"inferred_year", "relative_date", "multiple_dates"} for d in diagnostics)
    if safe and dates.start is not None and dates.end is None and times.start is not None:
        starts_at = _local_datetime(dates.start, times.start, zone)
        if times.end is not None:
            ends_at = _local_datetime(dates.start, times.end, zone)
        if starts_at is None or (times.end is not None and ends_at is None):
            starts_at = ends_at = None
            diagnostics.append(Diagnostic("ambiguous_local_time", "source_date_text", "Local clock falls in a timezone transition gap or fold.", Severity.ERROR))
    precision = DatePrecision.UNKNOWN
    if dates.start is not None:
        precision = DatePrecision.RANGE if dates.end is not None else DatePrecision.DAY
    if starts_at is not None:
        precision = DatePrecision.EXACT
    if dates.start is not None and dates.end is None and any(d.code == "inferred_year" for d in diagnostics):
        precision = DatePrecision.INFERRED
    kind = (ScheduleKind.RECURRING if recurring else ScheduleKind.DISCRETE if dates.discrete_dates
            else ScheduleKind.RANGE if dates.end else ScheduleKind.SINGLE if dates.start else ScheduleKind.UNKNOWN)
    occurrences = []
    if not recurring:
        for day in dates.discrete_dates or ((dates.start,) if dates.start is not None else ()):
            start, end = starts_at, ends_at
            occurrence_precision = precision
            if dates.discrete_dates:
                start = _local_datetime(day, times.start, zone) if safe and times.start is not None else None
                end = _local_datetime(day, times.end, zone) if start is not None and times.end is not None else None
                occurrence_precision = (DatePrecision.INFERRED if any(d.code == "inferred_year" for d in diagnostics)
                                        else DatePrecision.EXACT if start else DatePrecision.DAY)
                if safe and times.start is not None and (start is None or (times.end is not None and end is None)):
                    start = end = None
                    occurrence_precision = (DatePrecision.INFERRED if any(d.code == "inferred_year" for d in diagnostics)
                                            else DatePrecision.DAY)
                    diagnostics.append(Diagnostic("ambiguous_local_time", "source_date_text",
                                                  "A listed date crosses an ambiguous local clock.", Severity.ERROR))
            occurrence = EventOccurrence(
                "pending", day, source.timezone, end_date=dates.end,
                start_time=times.start, end_time=times.end, starts_at=start, ends_at=end,
                date_precision=occurrence_precision, source_schedule_text=source_text,
                source_item_ids=(raw_item.id,), evidence_urls=(raw_item.content_url,),
                diagnostics=tuple(sorted({d.code for d in diagnostics if d.code != "multiple_dates"})),
            )
            occurrences.append(identify_occurrence(occurrence, raw_item.id))
    return TemporalResult(
        **context, start_date=dates.start, end_date=dates.end, start_time=times.start,
        end_time=times.end, starts_at=starts_at, ends_at=ends_at,
        date_precision=precision, diagnostics=tuple(diagnostics), occurrences=tuple(occurrences),
        schedule_kind=kind,
        recurrence_rule=(("FREQ=WEEKLY;BYDAY=" + _WEEKLY_DAYS[weekly["every"] or weekly["plural"]])
                         if weekly else "FREQ=DAILY" if daily else None),
    )
