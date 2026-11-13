"""Bounded date grammar. Calendar validation/conversion belongs to persiantools."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from persiantools.jdatetime import JalaliDate

from .models import Diagnostic, Severity
from .ordinals import DAY_PATTERN, parse_day

MONTHS = {name: number for number, name in enumerate(
    "فروردین اردیبهشت خرداد تیر مرداد شهریور مهر آبان آذر دی بهمن اسفند".split(), 1
)}
_MONTH = "(?:" + "|".join(MONTHS) + ")"
_DAY = rf"(?:[0-9]{{1,2}}|{DAY_PATTERN})"
_YEAR = r"[0-9]{4}"
_WEEKDAYS = {"دوشنبه": 0, "سه شنبه": 1, "سهشنبه": 1, "چهارشنبه": 2,
             "پنجشنبه": 3, "پنج شنبه": 3, "جمعه": 4, "شنبه": 5, "یکشنبه": 6, "یک شنبه": 6}
_WEEKDAY_TEXT = "(?:" + "|".join(sorted(_WEEKDAYS, key=len, reverse=True)) + ")"
_RANGE = re.compile(
    rf"(?<!\w)(?P<d1>{_DAY})\s+(?:(?P<m1>{_MONTH})(?:\s*ماه)?\s*(?P<y1>{_YEAR})?\s*)?"
    rf"(?:تا|الی|–|-)\s*(?:(?P<w2>{_WEEKDAY_TEXT})\s+)?(?P<d2>{_DAY})\s+(?P<m2>{_MONTH})(?:\s*ماه)?(?:\s+(?P<y2>{_YEAR}))?(?!\w)"
)
_SINGLE = re.compile(rf"(?<!\w)(?P<day>{_DAY})\s+(?P<month>{_MONTH})(?:\s*ماه)?(?:\s+(?P<year>{_YEAR}))?(?!\w)")
_ISO = re.compile(r"(?<![\w/.-])(?P<year>[0-9]{4})-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})(?![\w/.-])")
_RELATIVE = re.compile(r"(?<!\w)(امروز|فردا|today|tomorrow)(?!\w)")
_BROAD = re.compile(r"این هفته|آخر هفته|هفته آینده|هفته بعد|next week|this week|weekend")
_DISCRETE = re.compile(
    rf"(?<!\w)(?P<days>{_DAY}(?:\s*(?:و|,|،|and)\s*{_DAY})+)"
    rf"\s+(?P<month>{_MONTH})(?:\s*ماه)?(?:\s+(?P<year>{_YEAR}))?(?!\w)"
)
_WEEKDAY = re.compile(r"(?<!\w)(" + "|".join(sorted(_WEEKDAYS, key=len, reverse=True)) + r")(?!\w)")


GREGORIAN_MONTHS = {name: i for i, name in enumerate('january february march april may june july august september october november december'.split(), 1)}
_ENGLISH = re.compile(r'(?<!\w)(?P<month>' + '|'.join(GREGORIAN_MONTHS) + r')\s+(?P<day>\d{1,2})(?:\s*(?:to|[-–—])\s*(?P<end>\d{1,2}))?,?\s+(?P<year>\d{4})(?!\w)')


@dataclass(frozen=True)
class ParsedDates:
    start: date | None
    end: date | None
    remainder: str
    diagnostics: tuple[Diagnostic, ...] = ()
    blocked: bool = False
    discrete_dates: tuple[date, ...] = ()


def _diagnostic(code: str, message: str, invalid: bool = False) -> Diagnostic:
    return Diagnostic(code, "source_date_text", message, Severity.ERROR if invalid else Severity.REVIEW)


def parse_dates(text: str, reference: date) -> ParsedDates:
    """Infer a year only for one adjacent-year candidate within +/-45 reference days.

    Yearless ranges must also be ordered, within one Jalali year, and <=90 days.
    This bounded proximity rule never rolls an old announcement forward a year.
    """
    # Harakat are optional spelling marks (e.g. سوّم / سی‌اُم), not date facts.
    text = re.sub(r'[\u064b-\u065f\u0670]', '', text)
    english = _ENGLISH.search(text)
    if english:
        remaining = text[:english.start()] + ' ' + text[english.end():]
        if text[:english.start()].strip() not in {'', 'from', 'از'} or _ENGLISH.search(remaining) or _SINGLE.search(remaining):
            return ParsedDates(None, None, text, (_diagnostic('ambiguous_date_context', 'Conflicting or qualified Gregorian wording.'),), True)
        try:
            start = date(int(english['year']), GREGORIAN_MONTHS[english['month']], int(english['day']))
            end = start.replace(day=int(english['end'])) if english['end'] else None
            if end and end < start:
                raise ValueError('reversed range')
        except ValueError:
            return ParsedDates(None, None, remaining, (_diagnostic('invalid_date', 'Invalid Gregorian range.', True),), True)
        return ParsedDates(start, end, remaining.replace('from', '', 1).strip())
    if _BROAD.search(text):
        return ParsedDates(None, None, text, (_diagnostic("broad_relative_date", "Broad relative wording has no single supported day."),), True)
    discrete = _DISCRETE.search(text)
    if discrete:
        return _parse_discrete(discrete, text, reference)
    match = _RANGE.search(text)
    is_range = match is not None
    if match is None:
        match = _SINGLE.search(text) or _ISO.search(text) or _RELATIVE.search(text)
    if match is None:
        return ParsedDates(None, None, text)
    if match.re in {_SINGLE, _RANGE} and re.match(r"\s+[0-9]{3,}", text[match.end():]):
        return ParsedDates(None, None, text, (_diagnostic("invalid_date", "Malformed or additional year; no replacement year was inferred.", True),), True)
    prefix = _WEEKDAY.sub("", text[:match.start()]).strip(" :：,،📅🗓")
    if prefix not in {"", "از", "تاریخ", "زمان", "از تاریخ"}:
        return ParsedDates(None, None, text, (_diagnostic("ambiguous_date_context", "Date is qualified by unsupported preceding wording."),), True)
    remaining = text[:match.start()] + " " + text[match.end():]
    # Any second date or leftover month/day list invalidates a single occurrence interpretation.
    if (_SINGLE.search(remaining) or _ISO.search(remaining) or _RELATIVE.search(remaining)
            or re.search(_MONTH, remaining) or re.search(r"[0-9]\s*(?:و|,|،|and)\s*$", text[:match.start()])):
        return ParsedDates(None, None, text, (_diagnostic("multiple_dates", "Multiple date expressions need occurrence review."),), True)
    diagnostics: list[Diagnostic] = []
    try:
        if match.re is _RELATIVE:
            start = reference + timedelta(days=int(match[0] in {"فردا", "tomorrow"}))
            end = None
            diagnostics.append(Diagnostic("relative_date", "source_date_text", "Day resolved from the stored reference in the source timezone.", Severity.INFO))
        elif match.re is _ISO:
            # ISO-like years >= 1700 are Gregorian; smaller years need calendar context.
            if int(match["year"]) < 1700:
                return ParsedDates(None, None, remaining, (_diagnostic("ambiguous_calendar", "Numeric calendar is not explicit."),), True)
            start, end = date(int(match["year"]), int(match["month"]), int(match["day"])), None
        else:
            if is_range:
                d1, d2 = parse_day(match["d1"]), parse_day(match["d2"])
                m1, m2 = MONTHS[match["m1"] or match["m2"]], MONTHS[match["m2"]]
                y1, y2 = match["y1"] or match["y2"], match["y2"] or match["y1"]
            else:
                d1, m1, y1 = parse_day(match["day"]), MONTHS[match["month"]], match["year"]
                d2, m2, y2 = d1, m1, y1
            if y1:
                start = JalaliDate(int(y1), m1, d1).to_gregorian()
                end = JalaliDate(int(y2), m2, d2).to_gregorian() if is_range else None
            else:
                year = JalaliDate(reference).year
                possibilities = []
                valid_calendar = False
                for candidate_year in (year - 1, year, year + 1):
                    try:
                        a = JalaliDate(candidate_year, m1, d1).to_gregorian()
                        b = JalaliDate(candidate_year, m2, d2).to_gregorian() if is_range else None
                    except ValueError:
                        continue
                    valid_calendar = True
                    if abs((a - reference).days) <= 45 and (b is None or 0 <= (b - a).days <= 90):
                        possibilities.append((a, b))
                if not valid_calendar:
                    raise ValueError("impossible day in adjacent years")
                if len(possibilities) != 1:
                    return ParsedDates(None, None, remaining, (_diagnostic("missing_year", "No unique year within 45 days of the stored reference."),), True)
                start, end = possibilities[0]
                diagnostics.append(_diagnostic("inferred_year", "Year inferred within 45 days of the stored reference; review required."))
        if end is not None and end < start:
            raise ValueError("reversed dates")
    except (ValueError, OverflowError):
        return ParsedDates(None, None, remaining, (_diagnostic("invalid_date", "Invalid calendar date or reversed date range.", True),), True)
    weekdays = list(_WEEKDAY.finditer(text[:match.start()]))
    if weekdays:
        if len(weekdays) != 1 or _WEEKDAYS[weekdays[0][0]] != start.weekday():
            return ParsedDates(None, None, remaining, (_diagnostic("weekday_contradiction", "Weekday conflicts with the date; neither was corrected.", True),), True)
        remaining = _WEEKDAY.sub(" ", remaining, count=1)
    if is_range and match["w2"] and _WEEKDAYS[match["w2"]] != end.weekday():
        return ParsedDates(None, None, remaining, (_diagnostic("weekday_contradiction", "End weekday conflicts with the range end date.", True),), True)
    return ParsedDates(start, end, remaining, tuple(diagnostics))


def _parse_discrete(match: re.Match, text: str, reference: date) -> ParsedDates:
    """Expand only an explicit same-month list with one safe year for every day."""
    prefix = text[:match.start()].strip(" :：,،📅🗓")
    remaining = text[:match.start()] + " " + text[match.end():]
    # "جمعه و شنبه ۸ و ۹ آبان": one weekday per listed day, checked in order below.
    listed_weekdays = (re.fullmatch(rf"{_WEEKDAY_TEXT}(?:\s*(?:و|،|,)\s*{_WEEKDAY_TEXT})+", prefix)
                       and re.findall(_WEEKDAY_TEXT, prefix))
    if listed_weekdays:
        prefix = ""
    if prefix not in {"", "تاریخ", "زمان"}:
        return ParsedDates(None, None, text, (_diagnostic(
            "ambiguous_date_context", "A discrete date list has unsupported qualifying wording."),), True)
    if (re.search(r"\s+[0-9]{3,}", text[match.end():])
            or _SINGLE.search(remaining) or _ISO.search(remaining)
            or re.search(_MONTH, remaining)):
        return ParsedDates(None, None, text, (_diagnostic(
            "multiple_dates", "Separate date expressions require schedule review."),), True)
    days = [parse_day(token[0]) for token in re.finditer(_DAY, match["days"])]
    month = MONTHS[match["month"]]
    diagnostics = [_diagnostic("multiple_dates", "The source identifies distinct dated occurrences.")]
    try:
        if match["year"]:
            values = tuple(JalaliDate(int(match["year"]), month, day).to_gregorian() for day in days)
        else:
            year = JalaliDate(reference).year
            possible = []
            valid = False
            for candidate_year in (year - 1, year, year + 1):
                try:
                    dates = tuple(JalaliDate(candidate_year, month, day).to_gregorian() for day in days)
                except ValueError:
                    continue
                valid = True
                if all(abs((day - reference).days) <= 45 for day in dates):
                    possible.append(dates)
            if not valid:
                raise ValueError("impossible calendar date")
            if len(possible) != 1:
                return ParsedDates(None, None, remaining, tuple(diagnostics) + (_diagnostic(
                    "missing_year", "No unique year places every listed date within 45 reference days."),), True)
            values = possible[0]
            diagnostics.append(_diagnostic("inferred_year", "Every listed date falls within 45 days of the stored reference; review required."))
    except (ValueError, OverflowError):
        return ParsedDates(None, None, remaining, (_diagnostic(
            "invalid_date", "A listed calendar date is invalid.", True),), True)
    if listed_weekdays and [_WEEKDAYS[w] for w in listed_weekdays] != [day.weekday() for day in values]:
        return ParsedDates(None, None, remaining, (_diagnostic(
            "weekday_contradiction", "Listed weekdays do not match the listed dates in order.", True),), True)
    if listed_weekdays:
        remaining = text[match.end():]
    return ParsedDates(None, None, remaining, tuple(diagnostics),
                       discrete_dates=tuple(sorted(set(values))))
