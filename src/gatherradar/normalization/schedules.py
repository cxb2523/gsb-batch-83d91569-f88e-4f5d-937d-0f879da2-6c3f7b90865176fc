"""Reconcile visible schedule wording and separately evidenced public sessions."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import re
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit

from ..domain import EventCandidate, RawItem, Source
from ..domain.occurrence import EventOccurrence, ScheduleKind, identify_occurrence, occurrence_key
from ..domain.temporal import DatePrecision
from .models import Diagnostic, Severity, TemporalResult
from .temporal import _local_datetime, normalize_temporal
from .text import fold
from .times import parse_times
from ..extraction.fields import duration_minutes
from .dates import _DAY, _DISCRETE, _SINGLE, _WEEKDAYS, _WEEKDAY_TEXT, MONTHS
from .ordinals import parse_day

_SESSION_CLOCKS = re.compile(
    r"(?:در\s+)?(?:(?P<count>دو|سه|چهار|[2-9])\s+)?سانس(?:\s*های)?\s*(?:ساعت\s*)?"
    r"(?P<clocks>[0-9]{1,2}(?::[0-9]{2})?(?:\s*(?:و|،|,)\s*(?:ساعت\s*)?[0-9]{1,2}(?::[0-9]{2})?)+)"
)


UNVERIFIED_SHAPE = "embedded_session_unverified_shape"
TIMESLOT_UNVERIFIED = "embedded_timeslot_unverified_shape"
TIMESLOT_WINDOW_CONFLICT = "embedded_timeslot_parent_window_conflict"
SOLD_OUT_UNVERIFIED = "embedded_session_sold_out_unverified"
# Named "availability" so it never questions the session's own date.
SOLD_OUT_CONFLICT = "embedded_session_sold_out_availability_conflict"
SOLD_OUT = "source_session_sold_out"
SESSION_WINDOW_CONFLICT = "session_window_duration_conflict"
# Public session semantics confirmed by owner-produced local evidence.
# "timeslots": a child timeslot that passed the collector's strict Jabama checks
# (12 typed keys, sessionId == parent id, explicit offsets, start < end, unique
# IDs, inside the parent window) is a dated occurrence with its own start/end.
# Evidence: the 2026-10-29 relationship report over two saved public pages
# (88 parents / 295 timeslots): every link, order, containment and seat-count
# check held, all 590 endpoints were UTC "Z". This is temporal eligibility only,
# never a claim that a seat can be booked.
# "sold_out" (soldOut=true means sold out) stays absent: all 88 inspected
# parents were false, so true is shown as the source's flag and never a status.
VERIFIED_SESSION_SEMANTICS: frozenset[str] = frozenset({"timeslots"})


def _covers(a: EventOccurrence, b: EventOccurrence) -> bool:
    if (a.end_date is None) != (b.end_date is None):
        return False
    return all(getattr(b, field) is None or getattr(a, field) == getattr(b, field)
               for field in ("start_date", "end_date", "start_time", "end_time", "timezone"))


def _choose(selected: TemporalResult, other: TemporalResult) -> TemporalResult:
    diagnostics = tuple(dict.fromkeys((*selected.diagnostics, *(
        d for d in other.diagnostics if d.code != "missing_date"
    ))))
    return replace(selected, diagnostics=diagnostics)


def _overlay_sessions(primary: TemporalResult, schedule: TemporalResult) -> TemporalResult | None:
    if not schedule.occurrences or not all(o.source_session_id for o in schedule.occurrences):
        return None
    def compatible(a, b):
        return ((a.end_date is None) == (b.end_date is None)
                and all(getattr(a, field) is None or getattr(b, field) is None
                        or getattr(a, field) == getattr(b, field)
                        for field in ("start_date", "end_date", "start_time", "end_time", "timezone")))
    def window(a, b):
        # A visible same-day clock range that contains a child timeslot is that
        # timeslot's parent window, not another session.
        return (b.source_timeslot_id is not None and a.end_date is None and a.start_date == b.start_date
                and a.start_time is not None and b.start_time is not None and a.start_time <= b.start_time
                and (a.end_time is None or (b.end_time is not None and b.end_time <= a.end_time)))
    if not all(any(compatible(a, b) or window(a, b) for a in primary.occurrences) for b in schedule.occurrences):
        return None
    values = []
    for value in schedule.occurrences:
        matching = [a for a in primary.occurrences if compatible(a, value)]
        if len(matching) == 1:
            value = replace(value, **{
                field: getattr(matching[0], field)
                for field in ("end_date", "start_time", "end_time", "starts_at", "ends_at")
                if getattr(value, field) is None and getattr(matching[0], field) is not None
            })
            if (UNVERIFIED_SHAPE in value.diagnostics and matching[0].start_time is not None
                    and matching[0].start_time == value.start_time):
                # The page's own visible date and clock state this session, so its
                # date is not in doubt; its price/availability were never read.
                value = replace(value, diagnostics=tuple(sorted(
                    (set(value.diagnostics) - {UNVERIFIED_SHAPE}) | {"embedded_session_corroborated_by_page_text"})))
        values.append(value)
    values.extend(a for a in primary.occurrences
                  if not any(compatible(a, b) or window(a, b) for b in schedule.occurrences))
    values.sort(key=lambda o: (o.start_date, o.start_time is None, o.start_time or datetime.min.time(), o.occurrence_id))
    result = replace(schedule, occurrences=tuple(values),
                     schedule_kind=ScheduleKind.SINGLE if len(values) == 1 else ScheduleKind.DISCRETE)
    if len(values) > 1:
        result = replace(result, start_date=None, end_date=None, start_time=None, end_time=None,
                         starts_at=None, ends_at=None, date_precision=DatePrecision.UNKNOWN)
    elif values:
        value = values[0]
        same_day = value.ends_at is None or value.ends_at.date() == value.start_date
        result = replace(result, start_date=value.start_date, start_time=value.start_time,
                         end_time=value.end_time if same_day else None, starts_at=value.starts_at,
                         ends_at=value.ends_at if same_day else None, date_precision=value.date_precision)
    return _choose(result, primary)


def _dated_session_clocks(primary: TemporalResult, wording: str) -> TemporalResult | None:
    match = _SESSION_CLOCKS.fullmatch(fold(wording).strip(" .،؛📅🗓⏰🕒"))
    if (not match or len(primary.occurrences) != 1 or primary.end_date is not None
            or primary.start_time is not None
            or any(d.code not in {"inferred_year", "relative_date"} for d in primary.diagnostics)):
        return None
    parts = re.split(r"\s*(?:و|،|,)\s*", match["clocks"])
    count = {"دو": 2, "سه": 3, "چهار": 4}.get(match["count"], int(match["count"]) if (match["count"] or "").isdigit() else len(parts))
    parsed = [parse_times(part if "ساعت" in part else "ساعت " + part) for part in parts]
    diagnostics = tuple(d for clock in parsed for d in clock.diagnostics)
    if count != len(parts) or len(parts) > 12:
        diagnostics += (Diagnostic("session_count_conflict", "source_schedule_text",
                                   "The stated session count disagrees with the listed clocks."),)
    if not diagnostics and len({clock.start for clock in parsed}) != len(parsed):
        diagnostics += (Diagnostic("ambiguous_session_clocks", "source_schedule_text",
                                   "Repeated clocks do not identify separate sessions without session IDs."),)
    if diagnostics:
        return TemporalResult(timezone=primary.timezone, diagnostics=diagnostics,
                              schedule_kind=ScheduleKind.DISCRETE)
    original = primary.occurrences[0]
    values = []
    for clock in sorted({value.start for value in parsed}):
        start = _local_datetime(original.start_date, clock, ZoneInfo(original.timezone))
        precision = (DatePrecision.INFERRED if original.date_precision is DatePrecision.INFERRED
                     else DatePrecision.EXACT if start else DatePrecision.DAY)
        if start is None:
            diagnostics += (Diagnostic("ambiguous_local_time", "source_schedule_text",
                                       "A session clock crosses a timezone gap or fold.", Severity.ERROR),)
        values.append(replace(original, start_time=clock, starts_at=start, date_precision=precision,
                              source_schedule_text=wording))
    return TemporalResult(
        timezone=primary.timezone, reference_at=primary.reference_at, reference_basis=primary.reference_basis,
        occurrences=tuple(values), schedule_kind=ScheduleKind.DISCRETE,
        diagnostics=tuple(dict.fromkeys((*primary.diagnostics, *diagnostics, Diagnostic(
            "multiple_sessions", "source_schedule_text", "The source states separate clocks on the same date.")))),
    )


def reconcile(primary: TemporalResult, schedule: TemporalResult) -> TemporalResult:
    """Choose an existing covering interpretation, never an arbitrary session."""
    if (primary.schedule_kind is ScheduleKind.RECURRING and not primary.occurrences
            and schedule.occurrences and all(o.source_session_id for o in schedule.occurrences)):
        days = {'MO': 0, 'TU': 1, 'WE': 2, 'TH': 3, 'FR': 4, 'SA': 5, 'SU': 6}
        rule = primary.recurrence_rule or ''
        weekday = days.get(rule.removeprefix('FREQ=WEEKLY;BYDAY='))
        supported_rule = rule == 'FREQ=DAILY' or weekday is not None
        if supported_rule and all(
                (weekday is None or o.start_date.weekday() == weekday)
                and (primary.start_time is None or o.start_time == primary.start_time)
                and (primary.end_time is None or o.end_time == primary.end_time)
                for o in schedule.occurrences):
            # Verify existing dated sessions against the recurrence; never
            # generate instances. Retain the rule for review after those dates.
            return _choose(replace(schedule, schedule_kind=ScheduleKind.RECURRING,
                                   recurrence_rule=rule), primary)
    if not primary.occurrences and primary.schedule_kind is not ScheduleKind.RECURRING:
        if schedule.occurrences or schedule.schedule_kind is ScheduleKind.RECURRING:
            return _choose(schedule, primary)
    if not schedule.occurrences and schedule.schedule_kind is not ScheduleKind.RECURRING:
        if primary.occurrences:
            selected = _choose(primary, schedule)
            return replace(selected, diagnostics=selected.diagnostics + (Diagnostic(
                "unresolved_schedule", "source_schedule_text",
                "Additional schedule wording could not be fully interpreted."),))
        return _choose(schedule, primary)
    if primary.schedule_kind is schedule.schedule_kind is ScheduleKind.RECURRING:
        if (primary.recurrence_rule, primary.start_time, primary.end_time) == (
                schedule.recurrence_rule, schedule.start_time, schedule.end_time):
            return _choose(schedule, primary)
    elif primary.occurrences and schedule.occurrences:
        overlay = _overlay_sessions(primary, schedule)
        if overlay is not None:
            return overlay
        if all(any(_covers(a, b) for a in schedule.occurrences) for b in primary.occurrences):
            return _choose(schedule, primary)
        if all(any(_covers(a, b) for a in primary.occurrences) for b in schedule.occurrences):
            return _choose(primary, schedule)
    retained = {occurrence_key(o): o for o in (*primary.occurrences, *schedule.occurrences)}
    diagnostics = tuple(dict.fromkeys((*primary.diagnostics, *schedule.diagnostics, Diagnostic(
        "schedule_conflict", "source_schedule_text",
        "Date and schedule evidence disagree; no primary date or session was selected."))))
    return TemporalResult(
        timezone=primary.timezone or schedule.timezone, reference_at=primary.reference_at,
        reference_basis=primary.reference_basis, diagnostics=diagnostics,
        occurrences=tuple(replace(o, diagnostics=tuple(sorted(set(o.diagnostics) | {"schedule_conflict"})))
                          for _, o in sorted(retained.items())),
        schedule_kind=ScheduleKind.CONFLICT,
        recurrence_rule=schedule.recurrence_rule or primary.recurrence_rule,
    )


def normalize_sessions(candidate: EventCandidate, raw: RawItem, source: Source) -> TemporalResult:
    zone = ZoneInfo(source.timezone)
    values = []
    diagnostics = [Diagnostic(code, "source_sessions", "Public session data requires source review.")
                   for code in candidate.source_session_diagnostics]
    for session in candidate.source_sessions:
        start = datetime.fromisoformat(session.start_iso.replace("Z", "+00:00")).astimezone(zone)
        end = None
        if session.end_iso is not None:
            # A timeslot states its own end; the parent duration is not reused.
            end = datetime.fromisoformat(session.end_iso.replace("Z", "+00:00")).astimezone(zone)
        elif session.duration_hours is not None:
            # Duration is elapsed time; arithmetic in UTC also handles DST changes.
            seconds = Decimal(session.duration_hours) * Decimal(3600)
            end = (start.astimezone(timezone.utc) + timedelta(seconds=float(seconds))).astimezone(zone)
        prices = {Decimal(value) for value in (session.price_per_person, session.unit_price) if value is not None}
        discounted = any(value is not None and Decimal(value) != 0
                         for value in (session.host_discount_pct, session.platform_discount_pct))
        own_codes = []
        if session.source_timeslot_id is not None:
            # Ownership and order were proven by the collector. Outside its parent
            # window it is contradictory; otherwise it waits for verified semantics.
            if session.schema_status == "timeslot_outside_parent_window":
                own_codes.append(TIMESLOT_WINDOW_CONFLICT)
            elif session.schema_status is not None or "timeslots" not in VERIFIED_SESSION_SEMANTICS:
                own_codes.append(TIMESLOT_UNVERIFIED)
        elif session.schema_status is not None:
            # Dated by the source's own session, but its unknown properties were
            # not inspected: reviewable, never actionable as is.
            own_codes.append(UNVERIFIED_SHAPE)
        remaining_seats = session.remaining_seats
        if session.sold_out is True:
            # False proves nothing. True is a status only once its meaning is
            # verified and no seat count on the same record contradicts it.
            # Either way it is a booking fact, never the session's expiry.
            if session.remaining_seats:
                own_codes.append(SOLD_OUT_CONFLICT)
                remaining_seats = None  # contradicted counts are never published
            elif "sold_out" in VERIFIED_SESSION_SEMANTICS:
                own_codes.append(SOLD_OUT)
            else:
                own_codes.append(SOLD_OUT_UNVERIFIED)
        if session.source_timeslot_id is None and session.duration_hours is not None:
            # A whole-session window much longer (or shorter) than the activity's
            # own stated length is an opening/booking window, not attendance time:
            # its dates stay, the exact attendance clock goes to review.
            activity = duration_minutes(candidate.duration_text) if candidate.duration_text else None
            window = Decimal(session.duration_hours) * 60
            if activity and (window < activity or window >= 2 * activity and window - activity >= 60):
                own_codes.append(SESSION_WINDOW_CONFLICT)
        if len(prices) > 1:
            own_codes.append("session_price_conflict")
            diagnostics.append(Diagnostic("session_price_conflict", "source_sessions",
                                          "The session's own price keys disagree; no amount was selected."))
        if discounted:
            own_codes.append("embedded_session_discount_unresolved")
            diagnostics.append(Diagnostic("embedded_session_discount_unresolved", "source_sessions",
                                          "Session discount semantics are unresolved; no payable amount was selected."))
        occurrence = EventOccurrence(
            "pending", start.date(), source.timezone,
            start_time=start.time(), end_time=end.time() if end else None,
            starts_at=start, ends_at=end, date_precision=DatePrecision.EXACT,
            source_schedule_text=session.start_iso, source_session_id=session.source_session_id,
            source_locator=session.source_locator,
            source_session_origin=urlsplit(raw.content_url).netloc,
            source_item_ids=(raw.id,), candidate_ids=(candidate.candidate_id,),
            evidence_urls=(candidate.evidence_url or raw.content_url,),
            evidence_fragment_ids=candidate.evidence_fragment_ids,
            price_amount=next(iter(prices)) if len(prices) == 1 and not discounted else None,
            price_per_person=session.price_per_person, unit_price=session.unit_price,
            host_discount_pct=session.host_discount_pct, platform_discount_pct=session.platform_discount_pct,
            remaining_seats=remaining_seats, enabled=session.enabled,
            diagnostics=tuple(own_codes), source_timeslot_id=session.source_timeslot_id,
            source_sold_out=session.sold_out, capacity_limit=session.capacity_limit,
        )
        values.append(identify_occurrence(occurrence, candidate.candidate_id))
    if any(SESSION_WINDOW_CONFLICT in o.diagnostics for o in values):
        diagnostics.append(Diagnostic(SESSION_WINDOW_CONFLICT, "source_sessions",
                                      "Session windows disagree with the stated activity length; "
                                      "the attendance clock is unresolved."))
    occurrences = tuple(sorted(values, key=lambda o: (o.start_date, o.start_time, o.occurrence_id)))
    result = TemporalResult(
        timezone=source.timezone, occurrences=occurrences,
        schedule_kind=ScheduleKind.SINGLE if len(occurrences) == 1 else ScheduleKind.DISCRETE,
        reference_at=raw.published_at or raw.captured_at,
        reference_basis="published_at" if raw.published_at else "captured_at",
        diagnostics=tuple(diagnostics),
    )
    if len(occurrences) == 1:
        value = occurrences[0]
        # Legacy parent timestamps support a single local day only. The
        # occurrence still retains a source-supported overnight end instant.
        same_day = value.ends_at is None or value.ends_at.date() == value.start_date
        result = replace(result, start_date=value.start_date, start_time=value.start_time,
                         end_time=value.end_time if same_day else None, starts_at=value.starts_at,
                         ends_at=value.ends_at if same_day else None, date_precision=value.date_precision)
    return result


def _publication_schedule(candidate: EventCandidate, raw: RawItem, source: Source) -> TemporalResult | None:
    """Bounded relative announcements; never project an old post onto run day."""
    if raw.published_at is None:
        return None
    wording = candidate.source_date_text or ''
    text = fold(wording)
    description = fold(candidate.description_text or '')
    reference = raw.published_at.astimezone(ZoneInfo(source.timezone)).date()
    pair = bool(re.search(r'(?<!\w)(?:امروز\s+و\s+فردا|today\s+and\s+tomorrow)(?!\w)', description + ' ' + text))
    match = re.fullmatch(rf'(?P<a>{_WEEKDAY_TEXT})\s*(?P<link>و|تا)\s*(?P<b>{_WEEKDAY_TEXT})\s*[،,|]?\s*(?P<hours>.*)', text)
    dates = []
    clocks = ''
    if match:
        a, b = _WEEKDAYS[match['a']], _WEEKDAYS[match['b']]
        clocks = match['hours']
        if pair:
            dates = [reference, reference + timedelta(days=1)]
            if [d.weekday() for d in dates] != [a, b]:
                return TemporalResult(timezone=source.timezone, diagnostics=(Diagnostic(
                    'relative_weekday_conflict', 'source_date_text', 'Publication-relative days disagree with stated weekdays.'),))
        elif reference.weekday() == a or any(v in description for v in ('این هفته', 'این آخر هفته')):
            week_start = reference - timedelta(days=(reference.weekday() - 5) % 7)
            start = week_start + timedelta(days=(a - 5) % 7)
            end = week_start + timedelta(days=(b - 5) % 7)
            if end < start:
                return None
            dates = ([start + timedelta(days=n) for n in range((end - start).days + 1)]
                     if match['link'] == 'تا' else [start, end])
    elif pair:
        relative = re.fullmatch(r'(?:امروز\s+و\s+فردا|today\s+and\s+tomorrow)\s*(.*)', text)
        if relative:
            dates = [reference, reference + timedelta(days=1)]
            clocks = relative[1]
    if not dates:
        return None
    parsed = parse_times(clocks)
    if parsed.diagnostics:
        return None
    parts = [normalize_temporal(day.isoformat() + (' ' + clocks if clocks else ''), raw, source) for day in dates]
    occurrences = tuple(replace(o, source_schedule_text=wording) for p in parts for o in p.occurrences)
    return TemporalResult(timezone=source.timezone, reference_at=raw.published_at, reference_basis='published_at',
        occurrences=occurrences, schedule_kind=ScheduleKind.DISCRETE,
        diagnostics=(Diagnostic('relative_date', 'source_date_text', 'Finite days anchored to original publication in source timezone.', Severity.INFO),))


def _prose_dated_sessions(primary: TemporalResult, wording: str, raw: RawItem,
                         source: Source) -> TemporalResult | None:
    """An explicit finite list is not an unbounded weekly recurrence.

    Keep the detail header's clock only on its matching date. The other listed
    dates remain date-only unless their own source evidence supplies a clock.
    """
    text = fold(wording)
    matches = list(_DISCRETE.finditer(text))
    if len(matches) != 1:
        return None
    match = matches[0]
    if (not re.search(r'به تاریخ\s*[:،,]?\s*$', text[:match.start()])
            or not re.fullmatch(r'\s*(?:برگزار (?:خواهد شد|می شود|شد))?[.\s]*', text[match.end():])):
        return None
    parsed = normalize_temporal(match[0], raw, source)
    if not parsed.occurrences:
        return None
    weekdays = re.findall(rf'({_WEEKDAY_TEXT})\s*ها', text[:match.start()])
    if weekdays and (len(set(weekdays)) != 1 or any(
            o.start_date.weekday() != _WEEKDAYS[weekdays[0]] for o in parsed.occurrences)):
        return TemporalResult(timezone=source.timezone, diagnostics=(Diagnostic(
            'weekday_contradiction', 'source_schedule_text', 'Listed dates disagree with their stated weekday.'),))
    if any(not any(_covers(a, b) for b in parsed.occurrences) for a in primary.occurrences):
        return reconcile(primary, parsed)
    values = []
    for value in parsed.occurrences:
        matching = [a for a in primary.occurrences if _covers(a, value)]
        values.extend(replace(a, source_schedule_text=wording) for a in matching)
        if not matching:
            values.append(replace(value, source_schedule_text=wording))
    return _choose(replace(parsed, occurrences=tuple(values)), primary)


_LIST_SEPARATOR = re.compile(r"\s*(?:،|,|و)\s*")
_HOLDING_TAIL = re.compile(r"\s*برگزار\s*(?:خواهد شد|می شود|میشود|می شه|میشه|شد)?\s*[.!]*\s*$")
_LIST_PREFIX = re.compile(r"(?:^|\s)به تاریخ\s*[:،,]?\s*$")


def _date_list(text: str) -> tuple[int, int, list[tuple[int, int, int | None]]] | None:
    """One explicit list: "5، 12، 19 و 26 آبان" or "5 آبان، 12 آبان، … و 26 آبان".

    Returns its span and (day, month, year) items. Anything else, including a
    second separate date expression, is not a list.
    """
    discrete = list(_DISCRETE.finditer(text))
    singles = list(_SINGLE.finditer(text))
    if len(discrete) == 1:
        match = discrete[0]
        if any(not (match.start() <= s.start() < match.end()) for s in singles):
            return None
        year = int(match["year"]) if match["year"] else None
        days = [parse_day(token[0]) for token in re.finditer(_DAY, match["days"])]
        return match.start(), match.end(), [(day, MONTHS[match["month"]], year) for day in days]
    if discrete or len(singles) < 2:
        return None
    if any(not _LIST_SEPARATOR.fullmatch(text[a.end():b.start()]) for a, b in zip(singles, singles[1:])):
        return None
    years = {s["year"] for s in singles}
    if len(years) != 1:
        return None
    return singles[0].start(), singles[-1].end(), [
        (parse_day(s["day"]), MONTHS[s["month"]], int(s["year"]) if s["year"] else None) for s in singles]


def _list_dates(items: list[tuple[int, int, int | None]], reference) -> tuple[tuple, bool] | None:
    """Dates for every item with one safe year (explicit, or within 45 reference days)."""
    from persiantools.jdatetime import JalaliDate
    try:
        if items[0][2] is not None:
            return tuple(JalaliDate(y, m, d).to_gregorian() for d, m, y in items), False
        year = JalaliDate(reference).year
        possible = []
        for candidate_year in (year - 1, year, year + 1):
            try:
                dates = tuple(JalaliDate(candidate_year, m, d).to_gregorian() for d, m, _ in items)
            except ValueError:
                continue
            if all(abs((day - reference).days) <= 45 for day in dates):
                possible.append(dates)
        return (possible[0], True) if len(possible) == 1 else None
    except (ValueError, OverflowError):
        return None


def _shared_clock(text: str):
    """The one clock (range) stated after a date list, or None if absent/unsupported."""
    text = _HOLDING_TAIL.sub("", text).strip(" ،,.:؛")
    text = re.sub(r"^(?:از\s+)?", "", text)
    if not text:
        return "absent"
    parsed = parse_times(text)  # Persian day-part words ("۵ تا ۸ صبح") are bounded there.
    if parsed.diagnostics or parsed.start is None:
        return None
    return parsed


def _listed_sessions(primary: TemporalResult, wording: str, raw: RawItem,
                     source: Source) -> TemporalResult | None:
    """An explicit finite date list, with at most one clock shared by every date.

    "به تاریخ ۵ آبان، ۱۲ آبان، ۱۹ آبان و ۲۶ آبان ساعت ۱۹ الی ۲۰:۳۰" states the
    same clock for each listed date. A detail-header date must be one of the
    listed dates. When the header clock and the shared clock disagree, every
    date is kept date-only with `schedule_clock_conflict`: neither clock is
    chosen and no session hour is overridden. Without a shared clock, the header
    clock stays on its own date only. Weekdays must agree with every date.
    """
    text = fold(wording)
    found = _date_list(text)
    if found is None or len(found[2]) < 2 or len(found[2]) > 12:
        return None
    start, end, items = found
    prefix = text[:start]
    bare = re.sub(rf"(?:{_WEEKDAY_TEXT})(?:\s*ها)?|زمان|تاریخ|[:：،,\s📅🗓⏰🕒🚨]", "", prefix)
    if bare and not _LIST_PREFIX.search(prefix):
        return None
    clock = _shared_clock(text[end:])
    if clock is None:
        return None
    clock = None if clock == "absent" else clock
    zone = ZoneInfo(source.timezone)
    reference = (raw.published_at or raw.captured_at).astimezone(zone).date()
    resolved = _list_dates(items, reference)
    if resolved is None:
        return None
    dates, inferred = resolved
    if list(dates) != sorted(set(dates)):
        return None
    weekdays = {_WEEKDAYS[w] for w in re.findall(_WEEKDAY_TEXT, prefix)}
    if weekdays and (len(weekdays) != 1 or any(day.weekday() not in weekdays for day in dates)):
        return TemporalResult(timezone=source.timezone, diagnostics=(Diagnostic(
            'weekday_contradiction', 'source_schedule_text', 'Listed dates disagree with their stated weekday.'),))
    diagnostics = []
    if inferred:
        diagnostics.append(Diagnostic("inferred_year", "source_schedule_text",
                                      "Every listed date falls within 45 days of the stored reference; review required."))
    header = primary.occurrences
    if header and (len(header) != 1 or header[0].start_date not in dates or header[0].end_date is not None):
        return None
    header_clock = (header[0].start_time, header[0].end_time) if header and header[0].start_time else None
    conflict = bool(clock and header_clock and (
        clock.start != header_clock[0] or (header_clock[1] is not None and clock.end != header_clock[1])))
    if conflict:
        diagnostics.append(Diagnostic("schedule_clock_conflict", "source_schedule_text",
            "The detail header clock and the listed sessions' clock disagree; no clock was chosen."))
    values = []
    for day in dates:
        if conflict:
            times = (None, None)
        elif clock is not None:
            times = (clock.start, clock.end)
        elif header_clock and day == header[0].start_date:
            times = header_clock
        else:
            times = (None, None)
        starts = _local_datetime(day, times[0], zone) if times[0] is not None else None
        ends = _local_datetime(day, times[1], zone) if starts is not None and times[1] is not None else None
        if times[0] is not None and (starts is None or (times[1] is not None and ends is None)):
            return None  # A DST gap/fold is never resolved by choosing an offset.
        precision = (DatePrecision.INFERRED if inferred else DatePrecision.EXACT if starts else DatePrecision.DAY)
        occurrence = EventOccurrence(
            "pending", day, source.timezone, start_time=times[0], end_time=times[1],
            starts_at=starts, ends_at=ends, date_precision=precision, source_schedule_text=wording,
            source_item_ids=(raw.id,), evidence_urls=(raw.content_url,),
            diagnostics=tuple(sorted({d.code for d in diagnostics})))
        values.append(identify_occurrence(occurrence, raw.id))
    return TemporalResult(
        timezone=source.timezone, reference_at=raw.published_at or raw.captured_at,
        reference_basis="published_at" if raw.published_at else "captured_at",
        occurrences=tuple(values), schedule_kind=ScheduleKind.DISCRETE,
        diagnostics=tuple(dict.fromkeys((*diagnostics, *(
            d for d in primary.diagnostics if d.code not in {"missing_date", "inferred_year"})))))


def normalize_schedule(candidate: EventCandidate, raw: RawItem, source: Source) -> TemporalResult:
    relative = _publication_schedule(candidate, raw, source)
    result = relative or normalize_temporal(candidate.source_date_text, raw, source)
    schedule = candidate.source_schedule_text
    if schedule and relative is None and fold(schedule) != fold(candidate.source_date_text or ""):
        sessions = (_dated_session_clocks(result, schedule)
                    or _prose_dated_sessions(result, schedule, raw, source)
                    or _listed_sessions(result, schedule, raw, source))
        secondary = sessions or normalize_temporal(schedule, raw, source)
        if sessions is not None and sessions.occurrences:
            result = sessions
        elif (result.occurrences and result.start_time is None and secondary.start_time is not None
                and not secondary.occurrences and secondary.schedule_kind is ScheduleKind.UNKNOWN
                and all(d.code == "missing_date" for d in secondary.diagnostics)
                and candidate.source_date_text):
            # Two explicitly temporal fields on this same candidate can express
            # date and clock separately. Run the normal composition guards over
            # both verbatim pieces; no clock is borrowed from another Event.
            combined = normalize_temporal(candidate.source_date_text + "\n" + schedule, raw, source)
            result = replace(combined, occurrences=tuple(replace(o, source_schedule_text=schedule)
                                                         for o in combined.occurrences))
        else:
            result = reconcile(result, secondary)
    if candidate.source_sessions and result.timezone is not None:
        result = reconcile(result, normalize_sessions(candidate, raw, source))
    elif candidate.source_session_diagnostics:
        result = replace(result, diagnostics=result.diagnostics + tuple(
            Diagnostic(code, "source_sessions", "Public session data is unavailable or unresolved.")
            for code in candidate.source_session_diagnostics))
    return replace(result, occurrences=tuple(identify_occurrence(replace(
        o, candidate_ids=(candidate.candidate_id,), evidence_fragment_ids=candidate.evidence_fragment_ids,
        evidence_urls=(candidate.evidence_url or raw.content_url,),
    ), candidate.candidate_id) for o in result.occurrences))
