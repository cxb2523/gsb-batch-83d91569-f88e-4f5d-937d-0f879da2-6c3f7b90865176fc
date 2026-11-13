"""Strict clock grammar; no implicit overnight rollover or AM/PM guessing.

Explicit AM/PM and Persian day-part words are applied with fixed bounds. A bare
early hour without minutes or a day-part word is ambiguous, never chosen.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import time

from .models import Diagnostic, Severity

_CLOCK = r"([0-9]{1,2})(?::([0-9]{2}))?"
_RANGE = re.compile(rf"(?:از\s+)?(?:ساعت\s*)?{_CLOCK}\s*(?:تا|الی|to|–|-)\s*(?:ساعت\s*)?{_CLOCK}")
_SINGLE = re.compile(rf"(?:ساعت\s*)?{_CLOCK}")
# Persian day-part words written after a clock ("۵ عصر", "۸ شب", "۱۰ صبح").
_PART = r"(صبح|بامداد|ظهر|بعد ?از ?ظهر|عصر|شب)"
_PARTED = re.compile(rf"(?:از\s+)?(?:ساعت\s*)?{_CLOCK}(?:\s*{_PART})?"
                     rf"(?:\s*(?:تا|الی|–|-)\s*(?:ساعت\s*)?{_CLOCK}(?:\s*{_PART})?)?")
# A bare hour below this, with no minutes and no day-part word, is commonly
# written for an afternoon ("ساعت ۵" = 17:00) and is not chosen either way.
AMBIGUOUS_BARE_HOURS = range(1, 7)


def _with_part(hour: int, part: str) -> int | None:
    """24-hour value of a 12-hour clock with its Persian day-part, or None if unsure."""
    part = part.replace(" ", "")
    if hour > 12:
        # Already a 24-hour value; keep it only when the day-part agrees.
        return hour if part in {"عصر", "بعدازظهر", "شب"} or (part == "ظهر" and hour <= 16) else None
    if part in {"صبح", "بامداد"}:
        return hour if 1 <= hour <= 11 else None
    if part in {"عصر", "بعدازظهر"}:
        return hour + 12 if 1 <= hour <= 11 else 12 if hour == 12 else None
    if part == "ظهر":
        return hour if 9 <= hour <= 12 else hour + 12 if 1 <= hour <= 4 else None
    return hour + 12 if 6 <= hour <= 11 else None  # شب; "۱۲ شب" and "۲ شب" stay unsure


def _ambiguous() -> ParsedTimes:
    return ParsedTimes(diagnostics=(Diagnostic(
        "ambiguous_meridiem", "source_date_text",
        "A bare 12-hour clock without a day-part word could be morning or afternoon; no clock was chosen."),))


def _parted(match: re.Match) -> ParsedTimes:
    h1, m1, p1, h2, m2, p2 = match.groups()
    end_part = p2 or (p1 if h2 is None else None)
    start_part = p1 or p2
    try:
        start_minute, end_minute = int(m1 or 0), int(m2 or 0)
        start_hour = _with_part(int(h1), start_part)
        end_hour = _with_part(int(h2), end_part) if h2 is not None else None
        if h2 is not None and p1 is None and start_hour is not None and end_hour is not None and start_hour >= end_hour:
            start_hour = int(h1)  # "۱۰ تا ۲ ظهر": the trailing day-part names the end.
        if start_hour is None or (h2 is not None and end_hour is None):
            return _ambiguous()
        start = time(start_hour, start_minute)
        end = time(end_hour, end_minute) if end_hour is not None else None
    except ValueError:
        return ParsedTimes(diagnostics=(Diagnostic("invalid_time", "source_date_text",
                                                   "Hour or minute is outside the clock.", Severity.ERROR),))
    if end is not None and end <= start:
        return ParsedTimes(start, end, (Diagnostic("ambiguous_overnight", "source_date_text",
                                                   "End is not later than start; no overnight day was inferred."),))
    return ParsedTimes(start, end)


@dataclass(frozen=True)
class ParsedTimes:
    start: time | None = None
    end: time | None = None
    diagnostics: tuple[Diagnostic, ...] = ()


def parse_times(text: str) -> ParsedTimes:
    text = text.strip(" ,،؛;.📅🗓⏰🕒")
    text = re.sub(r"^(?:زمان|تاریخ)\s*[:：]\s*", "", text).strip()
    if not text:
        return ParsedTimes()
    meridiem = re.fullmatch(r'(?:ساعت\s*)?([0-9]{1,2})(?::([0-9]{2}))?\s*([ap])\.?\s*m\.?', text, re.I)
    if meridiem:
        hour, minute = int(meridiem[1]), int(meridiem[2] or 0)
        if not 1 <= hour <= 12 or not 0 <= minute <= 59:
            return ParsedTimes(diagnostics=(Diagnostic('invalid_time', 'source_date_text',
                'Explicit AM/PM requires a 1–12 hour and valid minute.', Severity.ERROR),))
        return ParsedTimes(start=time(hour % 12 + (12 if meridiem[3].lower() == 'p' else 0), minute))
    parted = _PARTED.fullmatch(text)
    if parted and (parted[3] or parted[6]):
        return _parted(parted)
    match = _RANGE.fullmatch(text) or _SINGLE.fullmatch(text)
    if not match or (match.re is _SINGLE and ":" not in text and "ساعت" not in text):
        return ParsedTimes(diagnostics=(Diagnostic("unparsed_temporal", "source_date_text", "Temporal wording is not a supported single date/time expression."),))
    try:
        start = time(int(match[1]), int(match[2] or 0))
        end = time(int(match[3]), int(match[4] or 0)) if match.re is _RANGE else None
    except ValueError:
        return ParsedTimes(diagnostics=(Diagnostic("invalid_time", "source_date_text", "Hour or minute is outside the 24-hour clock.", Severity.ERROR),))
    if end is not None and end <= start:
        return ParsedTimes(start, end, (Diagnostic("ambiguous_overnight", "source_date_text", "End is not later than start; no overnight day was inferred."),))
    if any(hour is not None and minute is None and int(hour) in AMBIGUOUS_BARE_HOURS
           for hour, minute in ((match[1], match[2]), (match[3], match[4]) if match.re is _RANGE else (None, None))):
        return _ambiguous()
    return ParsedTimes(start, end)
