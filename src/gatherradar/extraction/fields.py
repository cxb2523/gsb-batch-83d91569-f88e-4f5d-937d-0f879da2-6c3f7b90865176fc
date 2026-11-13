"""Source-supported field extraction for one classified observation.

Two rules govern everything here. Every value is a slice of the operator's own
text — never a rewrite, a summary, or a guess — and a field the source does not
support stays None. Nothing is normalized: Jalali dates, price amounts, and
timezones belong to the later normalization step, so `source_date_text` and
`price_text` keep the wording exactly as published.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from . import rules
from .signals import CITY_TOKENS, Signal, SignalSet, has_address_detail
from .text import line_bounds, normalize, phrase_tokens, tokenize

_MAX_PLACE_SUMMARY = 200
_TRIM = " \t\r‌؛،,;:-–—•*_\u2066\u2067\u2068\u2069\ufeff"

# A day written as a number or a Persian ordinal ("۹", "یکم", "سی و یکم").
_DAY_WORD = (r"(?:\d{1,4}|" + "|".join(
    re.escape(normalize(word)).replace(r"\ ", r"\s*")
    for word in sorted(rules.PERSIAN_DAY_ORDINALS, key=len, reverse=True)) + r")")
# Leading days that belong with the month term they precede: "۱۹ و ۲۰ شهریور",
# "۸ تا ۱۰ مهرماه", "۵، ۱۲، ۱۹ و ۲۶ مهر", "یکم تا سوم مهرماه".
_LEADING_NUMBERS = re.compile(
    r"((?<!\w)" + _DAY_WORD + r"(?:\s*(?:و|,|،|-|–|تا|الی)\s*" + _DAY_WORD + r")*\s*)$"
)
# A trailing range that belongs with the time it follows: "از ساعت ۱۶ تا ۲۲".
_TRAILING_PART = re.compile(r"^(\s*(?:صبح|بامداد|ظهر|بعد\s?از\s?ظهر|عصر|شب))(?!\w)")
_TRAILING_RANGE = re.compile(r"^(\s*(?:تا|الی|to|-|–|—)\s*\d{1,2}(?::\d{2})?)")
_ENGLISH_DATE = re.compile(r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:\s*(?:to|[-–—])\s*\d{1,2})?,?\s+\d{4}\b', re.I)
# An explicit year written right after the month it belongs to: "۱۷ مهر ۱۴۰۵".
_TRAILING_YEAR = re.compile(r"^([ \t\u200c]+\d{4})(?![\d:/\-])")
_MONTH_TERMS = frozenset(rules.JALALI_MONTHS + rules.JALALI_MONTH_FORMS + rules.GREGORIAN_MONTHS)
_EXPLICIT_FREE = re.compile(r"(?<!\w)(?:رایگان|بدون\s+هزینه|free|no\s+fee)(?!\w)")
_AMOUNT_WITH_CURRENCY = re.compile(
    r"(?:[$€£]\s*\d[\d\s,٬،.]*)|"
    r"(?:\d[\d\s,٬،.]*(?:هزار|میلیون|million|thousand)?\s*"
    r"(?:تومان|تومن|ریال|دلار|usd|eur|gbp|dollars?))\b"
)
_ANY_AMOUNT = re.compile(r"(?<!\w)\d[\d\s,٬،.]*(?!\w)")
_TEMPORAL_CONNECTORS = frozenset({"و", "تا", "الی", "از", "ماه", "ها", "and", "to", "at"})
_ORDINAL_WORDS = frozenset(token.text for word in rules.PERSIAN_DAY_ORDINALS for token in tokenize(normalize(word)))


@dataclass(frozen=True, slots=True)
class _TemporalFragment:
    start: int
    end: int
    line_start: int
    line_end: int
    signals: tuple[Signal, ...]

    @property
    def has_date(self) -> bool:
        return any(signal.kind == "date" for signal in self.signals)

    @property
    def has_time(self) -> bool:
        return any(signal.kind == "time" for signal in self.signals)

    @property
    def has_concrete_date(self) -> bool:
        return any(
            signal.kind == "date" and signal.term not in rules.RELATIVE_DATES
            for signal in self.signals
        )

    @property
    def visual(self) -> bool:
        return any(signal.term.startswith("visual_") for signal in self.signals)


def _line(text: str, position: int) -> str:
    start, end = line_bounds(text, position)
    return text[start:end].strip(_TRIM)


def _trimmed_span(text: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and text[start] in _TRIM:
        start += 1
    while end > start and text[end - 1] in _TRIM:
        end -= 1
    return (start, end) if start < end else None


def _labelled_span(found: SignalSet, name: str) -> tuple[int, int] | None:
    """The operator's value for a labelled field, e.g. the text after "آدرس:".

    When the label ends its line, the value is taken from the next non-empty line,
    which is how addresses are often written.
    """
    position = found.labels.get(name)
    if position is None:
        return None
    _, value_start = position
    _, line_end = line_bounds(found.text, value_start)
    span = _trimmed_span(found.text, value_start, line_end)
    if span is not None:
        return span

    cursor = line_end
    while cursor < len(found.text):
        cursor += 1 if found.text[cursor : cursor + 1] == "\n" else 0
        _, next_end = line_bounds(found.text, cursor)
        span = _trimmed_span(found.text, cursor, next_end)
        if span is not None:
            return span
        if next_end == len(found.text):
            break
        cursor = next_end
    return None


def _labelled_value(found: SignalSet, name: str) -> str | None:
    span = _labelled_span(found, name)
    return found.text[slice(*span)] if span is not None else None


def _first(signals: tuple[Signal, ...]) -> Signal | None:
    return signals[0] if signals else None


def title(found: SignalSet, named: Signal | None) -> str | None:
    """A title only from a validated named construction or an explicit quoted name.

    Deliberately not "the first line that mentions an event word": a line like
    "اینجا فقط ایونت نیست" mentions one and names nothing, so it yields None.
    """
    if named is None:
        return None
    end = named.end
    # A numbered edition is part of the name; a date/time token is not.
    for token in found.tokens:
        if token.start < end:
            continue
        date_follows = any(
            signal.start >= token.end
            and not found.text[token.end:signal.start].strip(" \t‌")
            for signal in found.dates
        )
        if (not token.text.isdigit() or any(char not in " \t‌" for char in found.text[end:token.start])
                or date_follows or any(s.start <= token.start < s.end for s in found.dates + found.times)):
            break
        end = token.end
    return found.text[named.start:end].strip(_TRIM) or None


def _temporal_gap_is_related(gap: str) -> bool:
    if len(gap) > 40 or any(char in gap for char in "؟?!؛;"):
        return False
    tokens = tuple(token.text for token in tokenize(normalize(gap)))
    return all(token.isdigit() or token in _TEMPORAL_CONNECTORS or token in _ORDINAL_WORDS for token in tokens)


_ORDINAL_PREFIXES = frozenset(
    normalize(word) for word in (*rules.PERSIAN_WEEKDAYS, "از", "تاریخ", "زمان", "روز", "روزهای")
) | frozenset(token for day in rules.PERSIAN_WEEKDAYS for token in tokenize(normalize(day)))


def _leading_day_context(prefix: str, days: str) -> bool:
    """Whether a run of ordinal days really is the day of the following month.

    "هفته اول مهر" or "نیمه دوم مهر" name part of a month, not its first or second
    day. An ordinal run therefore needs a line start, punctuation, or a weekday /
    date word ("از", "روز") right before it. Numeric days keep the existing rule.
    """
    if days.strip()[:1].isdigit():
        return True
    words = tokenize(prefix)
    if not words or prefix[words[-1].end:].strip():
        return True
    return words[-1].text in _ORDINAL_PREFIXES


def _temporal_fragments(found: SignalSet) -> list[_TemporalFragment]:
    by_line: dict[tuple[int, int], list[Signal]] = {}
    for signal in found.dates + found.times:
        by_line.setdefault(line_bounds(found.text, signal.start), []).append(signal)

    fragments: list[_TemporalFragment] = []
    for (line_start, line_end), line_signals in by_line.items():
        clusters: list[list[Signal]] = []
        for signal in sorted(line_signals, key=lambda item: (item.start, -item.end)):
            if not clusters:
                clusters.append([signal])
                continue
            cluster_end = max(item.end for item in clusters[-1])
            if signal.start <= cluster_end or _temporal_gap_is_related(
                found.normalized[cluster_end:signal.start]
            ):
                clusters[-1].append(signal)
            else:
                clusters.append([signal])

        for cluster in clusters:
            start = min(signal.start for signal in cluster)
            end = max(signal.end for signal in cluster)
            leading = _LEADING_NUMBERS.search(found.normalized[line_start:start])
            if leading and _leading_day_context(found.normalized[line_start:line_start + leading.start(1)],
                                                leading.group(1)):
                start = line_start + leading.start(1)
            part = _TRAILING_PART.match(found.normalized[end:line_end]) if any(
                s.kind == "time" for s in cluster) else None
            if part:  # "ساعت ۵ عصر": the day-part word belongs to the clock.
                end += part.end(1)
            trailing = _TRAILING_RANGE.match(found.normalized[end:line_end])
            if trailing:
                end += trailing.end(1)
                part = _TRAILING_PART.match(found.normalized[end:line_end])
                if part:
                    end += part.end(1)
            elif max(cluster, key=lambda item: item.end).term in _MONTH_TERMS:
                year = _TRAILING_YEAR.match(found.normalized[end:line_end])
                if year:
                    end += year.end(1)
            if '(' in found.text[start:end] and re.fullmatch(r'\s*ها\s+تعطیل\s*\)', found.normalized[end:line_end]):
                end = line_end
            trimmed = _trimmed_span(found.text, start, end)
            if trimmed is not None:
                fragments.append(
                    _TemporalFragment(
                        start=trimmed[0],
                        end=trimmed[1],
                        line_start=line_start,
                        line_end=line_end,
                        signals=tuple(cluster),
                    )
                )
    return fragments


def _fragment_rank(fragment: _TemporalFragment) -> tuple[int, int, int, int, int]:
    return (
        int(fragment.visual),
        int(fragment.has_date and fragment.has_time),
        int(fragment.has_concrete_date),
        int(fragment.has_time),
        -fragment.start,
    )


def _adjacent(first: _TemporalFragment, second: _TemporalFragment, text: str) -> bool:
    earlier, later = sorted((first, second), key=lambda item: item.line_start)
    return text[earlier.line_end : later.line_start] in {"\n", "\r\n"}


def _with_adjacent_complement(
    found: SignalSet,
    selected: _TemporalFragment,
    fragments: list[_TemporalFragment],
) -> str:
    selected_terms = {signal.term for signal in selected.signals}
    visual_counterpart = None
    if "visual_calendar" in selected_terms:
        visual_counterpart = "visual_clock"
    elif "visual_clock" in selected_terms:
        visual_counterpart = "visual_calendar"
    if visual_counterpart is not None:
        visual_neighbours = [
            fragment
            for fragment in fragments
            if fragment is not selected
            and _adjacent(selected, fragment, found.text)
            and any(signal.term == visual_counterpart for signal in fragment.signals)
        ]
        if visual_neighbours:
            complement = max(visual_neighbours, key=_fragment_rank)
            first, second = sorted((selected, complement), key=lambda item: item.start)
            return f"{found.text[first.start:first.end]}\n{found.text[second.start:second.end]}"

    if selected.has_date and selected.has_time:
        return found.text[selected.start:selected.end]

    complements = [
        fragment
        for fragment in fragments
        if fragment is not selected
        and _adjacent(selected, fragment, found.text)
        and (
            (selected.has_date and fragment.has_time)
            or (selected.has_time and fragment.has_date)
        )
    ]
    if not complements:
        return found.text[selected.start:selected.end]

    complement = max(complements, key=_fragment_rank)
    first, second = sorted((selected, complement), key=lambda item: item.start)
    return f"{found.text[first.start:first.end]}\n{found.text[second.start:second.end]}"


def source_date_text(found: SignalSet) -> str | None:
    """The source's own date and time wording, unconverted.

    A labelled value wins. Otherwise compact temporal fragments are preferred over
    conversational prose. Complementary date and time fragments on adjacent lines
    are kept together without joining unrelated paragraphs.
    """
    fragments = _temporal_fragments(found)
    english = list(_ENGLISH_DATE.finditer(found.text))
    if english:
        other_dates = [f for f in fragments if f.has_date
            and not any(f.start < e.end() and e.start() < f.end for e in english)
            and any(s.term in rules.JALALI_MONTHS + rules.JALALI_MONTH_FORMS for s in f.signals)
            and re.search(r'\d', found.text[f.start:f.end])]
        if len(english) > 1 or other_dates:
            # Keep competing calendar evidence instead of silently selecting one.
            return '\n'.join([e[0] for e in english] + [found.text[f.start:f.end] for f in other_dates])
        match = english[0]
        end = max([match.end()] + [f.end for f in fragments
                                  if f.has_time and f.start <= match.end() < f.end])
        selected = _TemporalFragment(match.start(), end, *line_bounds(found.text, match.start()),
            (Signal('date', 'explicit_gregorian', match[0], match.start(), match.end()),)
            + tuple(s for s in found.times if match.end() <= s.start < end))
        return _with_adjacent_complement(found, selected, fragments)
    labelled_span = _labelled_span(found, "date")
    if labelled_span is not None:
        start, end = labelled_span
        overlapping = tuple(
            signal
            for signal in found.dates + found.times
            if start <= signal.start < end or signal.start <= start < signal.end
        )
        labelled = _TemporalFragment(
            start=start,
            end=end,
            line_start=line_bounds(found.text, start)[0],
            line_end=line_bounds(found.text, start)[1],
            signals=overlapping or (Signal("date", "labelled_date", found.text[start:end], start, end),),
        )
        return _with_adjacent_complement(found, labelled, fragments)

    if not fragments:
        return None
    ranges = [f for f in fragments if re.search(r'\d{1,2}\s+\S+(?:\s+\d{4})?\s+(?:تا|الی)\s+\d{1,2}\s+\S+',
                                               found.normalized[f.start:f.end]) and f.has_date and not f.has_time]
    if len(ranges) == 1:
        return _with_adjacent_complement(found, ranges[0], fragments).strip(_TRIM)
    selected = max(fragments, key=_fragment_rank)
    return _with_adjacent_complement(found, selected, fragments).strip(_TRIM) or None


def _label_term(found: SignalSet, name: str, labels: tuple[str, ...]) -> str | None:
    position = found.labels.get(name)
    if position is None:
        return None
    label_start, value_start = position
    written = normalize(found.text[label_start:value_start]).strip(
        f" \t{rules.LABEL_SEPARATORS}"
    )
    for label in labels:
        if written == normalize(label):
            return label
    return None


def _ambiguous_venue_address_span(found: SignalSet) -> tuple[int, int] | None:
    label = _label_term(found, "venue", rules.VENUE_LABELS)
    if label not in rules.AMBIGUOUS_VENUE_LABELS:
        return None
    span = _labelled_span(found, "venue")
    if span is None or not has_address_detail(found.text[slice(*span)]):
        return None
    return span


def venue_name(found: SignalSet) -> str | None:
    """An explicit venue value, unless an ambiguous Persian label holds an address."""
    if _ambiguous_venue_address_span(found) is None:
        labelled = _labelled_value(found, "venue")
        # "محل برگزاری: تهران" names a city, which `city` already reports.
        if labelled and " ".join(normalize(labelled).split()) not in CITY_TOKENS:
            return labelled
    compound = _compound_location(found)
    return ((compound[1] if compound else None) or _visual_venue(found) or _corroborated_venue(found)
            or _address_agreed_venue(found) or _natural_venue(found) or _trailing_head_venue(found)
            or _standalone_venue_line(found) or _address_component_venue(found))


def _compound_location(found: SignalSet) -> tuple[str, str, str] | None:
    """A pinned area/building/venue hierarchy, without geographic inference."""
    values = set()
    for line in found.text.splitlines():
        clean = line.strip(' \t\u2066\u2067\u2068\u2069\u200c')
        if not clean.startswith('📍'):
            continue
        if re.search(r'(?<!\w)(?:دفتر|حامی|اسپانسر)(?!\w)', normalize(clean)):
            continue
        parts = [p.strip(' \t\u2066\u2067\u2068\u2069\u200c') for p in re.split('[،,]', clean[1:])]
        if (len(parts) == 3 and re.fullmatch(r'(?:مجتمع|ساختمان|برج)\s+[\w‌ /-]{2,60}', parts[1])
                and re.fullmatch(r'(?:گالری|کافه|سالن|استودیو)\s+[\w‌ /-]{2,60}', parts[2])
                and 1 <= len(phrase_tokens(parts[0])) <= 3
                and not has_address_detail(parts[0]) and normalize(parts[0]) not in CITY_TOKENS):
            values.add((parts[0], parts[2], parts[1]))
    return next(iter(values)) if len(values) == 1 else None


def _visual_venue(found: SignalSet) -> str | None:
    """A location pin plus an explicit physical venue name, never an organizer."""
    names = {}
    for line in found.text.splitlines():
        if not line.lstrip(" \t\u2066\u2067\u2068\u2069").startswith("📍"):
            continue
        value = line.split("📍", 1)[1].strip()
        if re.search(r'(?<!\w)(?:دفتر|حامی|اسپانسر)(?!\w)', normalize(value)):
            continue
        # Parenthetical directions are address context, never part of a name.
        parts = [part.strip() for part in re.split("[،,|]", value.split('(', 1)[0])]
        if parts and normalize(parts[0]) in CITY_TOKENS:
            parts = parts[1:]
        if not parts:
            continue
        name = parts[0].strip(' \t\u2066\u2067\u2068\u2069')
        folded = normalize(name)
        heads = (*rules.NATURAL_VENUE_HEADS, *rules.GENERIC_VENUE_HEADS)
        explicit_branch = (len(parts) == 2 and re.fullmatch(r'شعبه\s+[\w‌ ]{2,60}', parts[1]))
        if explicit_branch and 1 <= len(phrase_tokens(name)) <= 3 and not has_address_detail(name):
            names.setdefault(' '.join(phrase_tokens(name)), name)
        if (2 <= len(phrase_tokens(name)) <= 7 and not has_address_detail(name)
                and any(folded.startswith(normalize(head) + " ") for head in heads)
                and not any(token in _NOT_A_NAME - {'و'} for token in phrase_tokens(name)[1:])):
            names.setdefault(" ".join(phrase_tokens(name)), name)
    return next(iter(names.values())) if len(names) == 1 else None


def _folded_tokens(phrases: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    return tuple(sorted({tuple(t.text for t in tokenize(normalize(p))) for p in phrases}, key=len, reverse=True))


_VENUE_INTRODUCERS = _folded_tokens(rules.NATURAL_VENUE_INTRODUCERS)
_VENUE_HEADS = _folded_tokens(rules.NATURAL_VENUE_HEADS)
_GENERIC_VENUE_HEADS = _folded_tokens(rules.GENERIC_VENUE_HEADS)
_VENUE_BRANCHES = _folded_tokens(rules.VENUE_BRANCH_TERMS)
_VENUE_HOLDING = frozenset(normalize(term) for term in rules.VENUE_HOLDING_TERMS)
_VENUE_PRESENCE = frozenset(normalize(term) for term in rules.VENUE_PRESENCE_PREDICATES)
_NOT_A_NAME = (frozenset(normalize(word) for word in rules.NAME_STOPWORDS | rules.VENUE_NAME_STOPWORDS)
               | frozenset(t for phrase in rules.DATE_TERMS for t in phrase_tokens(phrase)) | CITY_TOKENS)
_PAST_CLAUSE = re.compile(r"(?<!\w)(?:قبلی|گذشته|پیشین|قبلا|بودیم|previous|last)(?!\w)")


def _phrase_at(tokens, index: int, phrases: tuple[tuple[str, ...], ...], text: str) -> int:
    """Token length of the first phrase starting at `index` without crossing punctuation."""
    for phrase in phrases:
        end = index + len(phrase)
        if end <= len(tokens) and all(tokens[index + k].text == phrase[k] for k in range(len(phrase))) and not any(
                _crosses(text, tokens[k - 1].end, tokens[k].start) for k in range(index + 1, end)):
            return len(phrase)
    return 0


def _crosses(text: str, previous_end: int, next_start: int) -> bool:
    return any(char not in " \t‌" for char in text[previous_end:next_start])


def _venue_span(found: SignalSet, start: int, busy: frozenset[int]) -> tuple[int, int, bool, bool] | None:
    """`[branch area] head name [branch area]` from token `start`, or None.

    Returns (first token, end token exclusive, generic head, has branch).
    """
    tokens, text = found.tokens, found.text

    def joined(index: int) -> bool:
        return index < len(tokens) and not _crosses(text, tokens[index - 1].end, tokens[index].start)

    def name_run(index: int, limit: int) -> int:
        count = 0
        while count < limit and joined(index + count) and index + count not in busy:
            cursor = index + count
            numeric_connector = (tokens[cursor].text == "و" and cursor > index
                and cursor + 1 < len(tokens) and joined(cursor + 1)
                and tokens[cursor - 1].text in rules.VENUE_NUMBER_WORDS
                and tokens[cursor + 1].text in rules.VENUE_NUMBER_WORDS)
            if not numeric_connector and (
                    len(tokens[cursor].text) < rules.MIN_NAME_TOKEN_LENGTH
                    or tokens[cursor].text.isdigit() or tokens[cursor].text in _NOT_A_NAME
                    or _phrase_at(tokens, cursor, _VENUE_HEADS + _GENERIC_VENUE_HEADS + _VENUE_BRANCHES, text)):
                break
            count += 1
        return count

    def branch(index: int) -> int:
        size = _phrase_at(tokens, index, _VENUE_BRANCHES, text)
        if not size:
            return 0
        if joined(index + size) and tokens[index + size].text == "ی":  # شعبه‌ی
            size += 1
        area = name_run(index + size, rules.MAX_VENUE_BRANCH_TOKENS)
        return size + area if area else 0

    cursor = start
    leading = branch(cursor)
    cursor += leading
    if leading and not joined(cursor):
        return None
    head = _phrase_at(tokens, cursor, _VENUE_HEADS, text)
    generic = not head
    head = head or _phrase_at(tokens, cursor, _GENERIC_VENUE_HEADS, text)
    if not head:
        return None
    cursor += head
    name = name_run(cursor, rules.MAX_VENUE_NAME_TOKENS)
    if not name:
        return None
    cursor += name
    trailing = 0 if leading or not joined(cursor) else branch(cursor)
    cursor += trailing
    # A name still running past the limit has no defensible end.
    if joined(cursor) and cursor not in busy and name_run(cursor, 1) and not trailing:
        return None
    return start, cursor, generic, bool(leading or trailing)


def _natural_venue(found: SignalSet) -> str | None:
    """A venue written in ordinary event phrasing, kept in the source's own words.

    Requires a recognized venue head after an introducer ("در", "توی", "میزبان شما")
    or a branch line, plus event context: attendance wording in the same clause, a
    standalone location line, or — for generic heads such as "خانه" or "مرکز" —
    holding wording ("برگزار ...") directly after the name. Retrospective or past
    clauses never qualify. Several different names yield None.
    """
    tokens, text = found.tokens, found.text
    busy = set()
    for signal in (found.attendance + found.dates + found.times + found.prices
                   + found.registration + found.retrospective):
        if signal.first_token >= 0:
            busy.update(range(signal.first_token, signal.last_token + 1))
    busy = frozenset(busy)
    attendance = found.attendance
    names: dict[str, str] = {}
    for index in range(len(tokens)):
        intro = _phrase_at(tokens, index, _VENUE_INTRODUCERS, text)
        line_start, line_end = line_bounds(text, tokens[index].start)
        line_initial = index == 0 or tokens[index - 1].end <= line_start
        if not intro and not (line_initial and _phrase_at(
                tokens, index, _VENUE_BRANCHES + _VENUE_HEADS + _GENERIC_VENUE_HEADS, text)):
            continue
        if intro and (index + intro >= len(tokens) or _crosses(text, tokens[index + intro - 1].end, tokens[index + intro].start)):
            continue
        span = _venue_span(found, index + intro, busy)
        if span is None:
            continue
        first, last, generic, has_branch = span
        start, end = tokens[first].start, tokens[last - 1].end
        clause = _clause_bounds(text, start)
        folded_clause = found.normalized[slice(*clause)]
        if _PAST_CLAUSE.search(folded_clause) or any(clause[0] <= s.start < clause[1] for s in found.retrospective):
            continue
        # "در کافه الف و گالری ب": a listed alternative is not one venue.
        if (last + 1 < len(tokens) and tokens[last].text in {"و", "یا", "and", "or"}
                and _phrase_at(tokens, last + 1, _VENUE_HEADS + _GENERIC_VENUE_HEADS + _VENUE_BRANCHES, text)):
            return None
        after = last < len(tokens) and tokens[last].text in _VENUE_HOLDING and not _crosses(text, end, tokens[last].start)
        after = after or bool(intro and found.dates and _phrase_at(
            tokens, last, _folded_tokens(rules.VENUE_ATTENDANCE_SUFFIXES), text))
        # "از ۶ تا ۸ آبان، توی عمارت زیرخاکی منتظر …": the clause gives the
        # event's own dates and the name is directly followed by a presence verb.
        after = after or bool(intro and last < len(tokens) and not _crosses(text, end, tokens[last].start)
                              and tokens[last].text in _VENUE_PRESENCE
                              and any(clause[0] <= s.start < clause[1] for s in found.dates))
        hosted = intro and tokens[index].text.startswith("میزبان")
        in_clause = hosted or any(clause[0] <= s.start < clause[1] for s in attendance)
        rest = (text[line_start:tokens[index].start] + " " + text[end:line_end])
        standalone = not any(
            t.text not in {a.text for a in tokenize(normalize(" ".join(s.text for s in attendance)))}
            for t in tokenize(normalize(rest)))
        if generic and not (after or has_branch):
            continue
        explicit_event_branch = bool(has_branch and intro and (found.event_strong or found.event_weak)
                                     and (found.dates or found.attendance))
        if not (after or in_clause or (has_branch and standalone) or explicit_event_branch):
            continue
        if not intro and not (has_branch and standalone):
            continue
        value = text[start:end]
        names.setdefault(" ".join(phrase_tokens(value)), value)
    return next(iter(names.values())) if len(names) == 1 else None


def _clause_bounds(text: str, position: int) -> tuple[int, int]:
    start = max(text.rfind(mark, 0, position) for mark in "\n.!?؟؛;") + 1
    ends = [found for mark in "\n.!?؟؛;" if (found := text.find(mark, position)) != -1]
    return start, min(ends) if ends else len(text)


def _corroborated_venue(found: SignalSet) -> str | None:
    """A separately written name + explicit event-at-name + labelled address.

    A name appearing only as an organizer, in prose, or at the end of an address
    cannot establish a venue. All three independent textual roles must agree.
    This uses retained text, not source IDs, HTML selectors or fabricated labels.
    """
    street_address = address(found)
    if not street_address or not has_address_detail(street_address):
        return None
    candidates = set()
    for line in found.text.splitlines():
        name = line.strip(_TRIM)
        if (not name or len(name) > 80 or len(name.split()) > 6 or has_address_detail(name)
                or any(c.isdigit() or c in ':：،,.!?؟' for c in name)):
            continue
        folded = re.escape(normalize(name))
        if not re.search(r'(?<!\w)' + folded + r'(?!\w)', normalize(street_address)):
            continue
        # Limited occurrence wording, at most four intervening name words, and
        # a clause boundary immediately after the complete name. Not arbitrary prose.
        pattern = (r'(?<!\w)(?:برنامه|رویداد|کارگاه|اکران|event|workshop|screening)'
                   r'(?:\s+[^\W\d_]+){0,4}\s+(?:در|at)\s+' + folded + r'(?=\s*[,،.;؛\n]|\s*$)')
        matches = re.finditer(pattern, found.normalized)
        if any(not re.search(r'قبلی|گذشته|پیشین|previous|last', match[0]) for match in matches):
            candidates.add(name)
    return next(iter(candidates)) if len(candidates) == 1 else None


_OFFICE_OR_SPONSOR = re.compile(r"(?<!\w)(?:دفتر|حامی|اسپانسر|حمایت|شعبه\s+مرکزی)(?!\w)")


def _address_agreed_venue(found: SignalSet) -> str | None:
    """A prose "در/توی <head> <name>" that is also the final part of the address.

    "این رویداد … توی عمارت عقاب در جریانه" plus "مکان: …، عمارت عقاب": the
    prose says the event is happening/held at the name ("در جریان", "برگزار"
    directly after it) and the labelled address ends with exactly that name.
    Both roles are required; neither alone is a venue, and mere mention in prose
    ("برنامه اکران در خانه آبی، فرصتی …") is not. The clause must speak about
    the event, not an office, sponsor or the past.
    """
    street_address = address(found)
    if not street_address or not has_address_detail(street_address):
        return None
    tail = re.split("[،,]", street_address)[-1].strip(_TRIM)
    words = phrase_tokens(tail)
    heads = _VENUE_HEADS + _GENERIC_VENUE_HEADS
    if not 2 <= len(words) <= 6 or not any(words[:len(head)] == head for head in heads):
        return None
    span = _labelled_span(found, "address") or _ambiguous_venue_address_span(found)
    folded = re.escape(normalize(tail))
    introducers = "|".join(re.escape(normalize(p)) for p in rules.NATURAL_VENUE_INTRODUCERS)
    happening = "|".join(re.escape(normalize(p)) for p in rules.VENUE_HAPPENING_PREDICATES)
    nouns = "|".join(re.escape(normalize(n)) for n in rules.DURATION_EVENT_NOUNS)
    # "… توی <head> <name> در جریانه" or a quoted event name "ایونت «چیزمیز» در
    # <head> <name>،": the event is said to be at the name the address ends with.
    # An unnamed mention ("برنامه اکران در خانه آبی، …") is not enough.
    placed = (r"(?<!\w)(?:" + introducers + r")\s+(" + folded + r")\s+(?:" + happening + r")"
              r"|(?<!\w)(?:" + nouns + r")\s+«[^»\n]{1,40}»\s+(?:در|توی)\s+("
              + folded + r")(?=\s*[،,.!؛\n]|\s*$)")
    for match in re.finditer(placed, found.normalized):
        group = 1 if match.group(1) is not None else 2
        if span is not None and span[0] <= match.start() < span[1]:
            continue
        clause = found.normalized[slice(*_clause_bounds(found.text, match.start()))]
        if _PAST_CLAUSE.search(clause) or _OFFICE_OR_SPONSOR.search(clause):
            continue
        if not any(normalize(term) in clause for term in rules.DURATION_EVENT_NOUNS):
            continue
        return found.text[match.start(group):match.end(group)]
    return None


def _address_component_venue(found: SignalSet) -> str | None:
    """A prose "در/توی <name>" that is a building named in the labelled address.

    "توی فصل پنجم ایونت ویرا در تیدا سنتر، قراره …" plus an address component
    "مجتمع تجاری تیدا سنتر": the event clause places itself at exactly the name
    that the address gives a building head. The prose wording is the venue; the
    building, floor and street stay in the address. The clause must carry an
    event noun or the event's dates and must not be about an office, sponsor
    or the past. A name without such an address component is not enough.
    """
    street_address = address(found)
    if not street_address or not has_address_detail(street_address):
        return None
    heads = sorted((tuple(phrase_tokens(h)) for h in rules.ADDRESS_BUILDING_HEADS), key=len, reverse=True)
    buildings = set()
    for part in re.split("[،,]", street_address):
        words = tuple(phrase_tokens(part.strip(_TRIM)))
        head = next((h for h in heads if words[:len(h)] == h), None)
        if head and 1 <= len(words) - len(head) <= 4:
            buildings.add(words[len(head):])
    if not buildings:
        return None
    span = _labelled_span(found, "address") or _ambiguous_venue_address_span(found)
    nouns = tuple(normalize(n) for n in rules.DURATION_EVENT_NOUNS)
    values = {}
    for name in buildings:
        if any(token in CITY_TOKENS for token in name):
            continue
        pattern = (r"(?<![\w‌])(?:در|توی)\s+(" + r"\s+".join(re.escape(t) for t in name)
                   + r")(?=\s*[،,.!؛\n]|\s+(?:" + "|".join(re.escape(normalize(p)) for p in
                                                      (*rules.VENUE_PRESENCE_PREDICATES, *rules.VENUE_HOLDING_TERMS))
                   + r")(?!\w))")
        for match in re.finditer(pattern, found.normalized):
            if span is not None and span[0] <= match.start() < span[1]:
                continue
            bounds = _clause_bounds(found.text, match.start())
            clause = found.normalized[slice(*bounds)]
            if _PAST_CLAUSE.search(clause) or _OFFICE_OR_SPONSOR.search(clause):
                continue
            if not (any(noun in clause for noun in nouns)
                    or any(bounds[0] <= s.start < bounds[1] for s in found.dates)):
                continue
            value = found.text[match.start(1):match.end(1)]
            values.setdefault(" ".join(name), value)
    return next(iter(values.values())) if len(values) == 1 else None


def _standalone_venue_line(found: SignalSet) -> str | None:
    """A whole line "در/توی <head> <name>" directly under an event title line.

    "رویداد “سکانس چهارم”\nدر عمارت زیرخاکی": the same head+name must also
    appear elsewhere in the text, so a one-off phrase ("در خانه بمانید") never
    becomes a venue. Several different names yield None.
    """
    heads = "|".join(re.escape(normalize(h)) for h in (*rules.NATURAL_VENUE_HEADS, *rules.GENERIC_VENUE_HEADS))
    nouns = tuple(normalize(n) for n in rules.DURATION_EVENT_NOUNS)
    lines = found.text.splitlines(keepends=True)
    names = {}
    offset, previous = 0, ""
    for line in lines:
        folded = found.normalized[offset:offset + len(line)]
        match = re.fullmatch(r"\s*(?:در|توی)\s+((?:" + heads + r")(?:\s+[^\W\d_]{2,}){1,3})\s*", folded)
        if match and any(noun in previous for noun in nouns):
            value = found.text[offset + match.start(1):offset + match.end(1)]
            tokens = phrase_tokens(value)
            pattern = r"(?<!\w)" + r"\s+".join(re.escape(t) for t in tokens) + r"(?!\w)"
            elsewhere = [m for m in re.finditer(pattern, found.normalized)
                         if not offset <= m.start() < offset + len(line)]
            if elsewhere and not any(t in _NOT_A_NAME for t in tokens[1:]):
                names.setdefault(" ".join(tokens), value)
        if folded.strip(" \t\r\n.") :
            previous = folded
        offset += len(line)
    return next(iter(names.values())) if len(names) == 1 else None


def _trailing_head_venue(found: SignalSet) -> str | None:
    """"در <name> پارک برگزار …": a head written after a short foreign name."""
    heads = "|".join(re.escape(normalize(h)) for h in rules.TRAILING_VENUE_HEADS)
    holding = "|".join(re.escape(normalize(h)) for h in rules.VENUE_HOLDING_TERMS)
    values = {}
    for match in re.finditer(r"(?<![\w‌])در\s+((?:[^\W\d_]+[\s‌]){1,3}?(?:" + heads + r"))\s+(?:" + holding + r")",
                             found.normalized):
        value = found.text[match.start(1):match.end(1)]
        name = phrase_tokens(value)[:-1]
        if any(token in _NOT_A_NAME or len(token) < rules.MIN_NAME_TOKEN_LENGTH for token in name):
            continue
        values.setdefault(" ".join(phrase_tokens(value)), value)
    return next(iter(values.values())) if len(values) == 1 else None


def address(found: SignalSet) -> str | None:
    explicit = _labelled_value(found, "address")
    if explicit is not None:
        position = found.labels.get("address")
        if position and "📍" in found.text[position[0]:position[1]]:
            without_area = re.sub(r"(?<!\w)(?:محدوده|محله|منطقه)\s+[^\n،,]+", "", normalize(explicit))
            if not has_address_detail(without_area):
                return None
        return explicit
    span = _ambiguous_venue_address_span(found)
    return found.text[slice(*span)] if span is not None else None


def city(found: SignalSet) -> str | None:
    """A city only when the text says one, in the source's own wording.

    A neighborhood never implies its city: "نیاوران" yields None, while an explicit
    "تهران" yields "تهران".
    """
    labelled = _labelled_value(found, "city")
    if labelled:
        return labelled
    address_span = _labelled_span(found, "address") or _ambiguous_venue_address_span(found)
    if address_span is not None:
        address_start, address_end = address_span
        for token in found.tokens:
            if address_start <= token.start < address_end and token.text in CITY_TOKENS:
                return found.text[token.start : token.end]
    # A promotional hashtag or handle ("#ایونت_تهران") does not say where the
    # event is; only ordinary written text can.
    tags = [m.span() for m in re.finditer(r"[#@][\w‌]+", found.text)]
    for token in found.tokens:
        if token.text in CITY_TOKENS and not any(a <= token.start < b for a, b in tags):
            return found.text[token.start : token.end]
    return _explicit_event_city(found)


def _explicit_event_city(found: SignalSet) -> str | None:
    """"فستیوال اکتبر در استانبول": a city outside the default list, only when an
    event noun is directly said to be in it. Persian/English spellings of one city
    agree; two different cities yield None."""
    nouns = "|".join(re.escape(normalize(n)) for n in rules.DURATION_EVENT_NOUNS)
    cities = "|".join(re.escape(normalize(c)) for c in sorted(rules.EXPLICIT_EVENT_CITIES, key=len, reverse=True))
    pattern = (r"(?<!\w)(?:" + nouns + r")(?:\s+[^\W\d_]+){0,3}\s+(?:در|in)\s+(" + cities + r")(?!\w)")
    found_cities = {}
    for match in re.finditer(pattern, found.normalized):
        key = rules.EXPLICIT_EVENT_CITIES[match[1]]
        found_cities.setdefault(key, found.text[match.start(1):match.end(1)])
    return next(iter(found_cities.values())) if len(found_cities) == 1 else None


def event_format(found: SignalSet) -> str | None:
    """`online`, `in_person`, `hybrid`, or None — explicit wording only.

    An address is never taken as proof that an event is in person.
    """
    has_online = has_in_person = False
    for clause in re.split(r'[\n.!?؟؛;]', found.normalized):
        clause = clause.strip()
        # Historical or negated participation does not establish current format.
        if re.search(r'(?<!\w)(?:قبلا|قبلی|گذشته|پیشین|نیست|نبود|نخواهد|نمی|not|previous|previously|last)(?!\w)', clause):
            continue
        if _direct_format(clause, rules.HYBRID_TERMS):
            return 'hybrid'
        has_online |= _direct_format(clause, rules.ONLINE_TERMS)
        has_in_person |= _direct_format(clause, rules.IN_PERSON_TERMS)
    if has_online and has_in_person:
        return "hybrid"
    if has_online:
        return "online"
    if has_in_person:
        return "in_person"
    return None


def _direct_format(clause: str, terms: tuple[str, ...]) -> bool:
    mode = '(?:' + '|'.join(re.escape(normalize(term)) for term in terms) + ')'
    if re.fullmatch(r'(?:(?:نحوه برگزاری|نوع برگزاری|فرمت|format)\s*[:：]\s*)?' + mode, clause):
        return True
    if re.fullmatch(r'(?:به صورت|به شکل)\s+' + mode, clause):
        return True
    attendance = r'(?:برگزاری|رویداد|کارگاه|وبینار|کلاس|جلسه|شرکت|حضور|event|workshop|webinar|class|participation)'
    patterns = (
        r'(?<!\w)' + attendance + r'\s+(?:(?:به صورت|به شکل)\s+)?' + mode + r'(?!\w)',
        r'(?<!\w)' + mode + r'\s+' + attendance + r'(?!\w)',
        r'(?<!\w)(?:attend|join|held)\s+' + mode + r'(?!\w)',
        r'(?<!\w)(?:به صورت|به شکل)\s+' + mode + r'\s+برگزار(?!\w)',
    )
    return any(re.search(pattern, clause) for pattern in patterns)


def price_text(found: SignalSet) -> str | None:
    """Conservative source price wording; a bare price-related word is not enough."""
    labelled = _labelled_value(found, "price")
    if labelled:
        normalized = normalize(labelled)
        if (
            _EXPLICIT_FREE.search(normalized)
            or _AMOUNT_WITH_CURRENCY.search(normalized)
            or _ANY_AMOUNT.search(normalized)
        ):
            return labelled

    seen_lines: set[tuple[int, int]] = set()
    for signal in found.prices:
        bounds = line_bounds(found.text, signal.start)
        if bounds in seen_lines:
            continue
        seen_lines.add(bounds)
        line = found.text[slice(*bounds)].strip(_TRIM)
        normalized = normalize(line)
        if _EXPLICIT_FREE.search(normalized) or _AMOUNT_WITH_CURRENCY.search(normalized):
            return line
    return None


# Platform hosts whose links are navigation/self-references, not Event pages.
_SELF_REFERENCE_HOSTS = ("instagram.com", "instagr.am")


def reference_urls(found: SignalSet) -> tuple[str, ...]:
    """Every public http(s) URL written in the evidence, verbatim and deduplicated."""
    urls: list[str] = []
    for url in found.urls:
        host = (urlsplit(url.text).hostname or "").lower()
        if host and not any(host == h or host.endswith("." + h) for h in _SELF_REFERENCE_HOSTS)                 and url.text not in urls:
            urls.append(url.text)
    return tuple(urls[:5])


def registration_url(found: SignalSet) -> str | None:
    """A URL explicitly associated with registration wording on its source line."""
    candidates: list[tuple[int, int, str]] = []
    for url in found.urls:
        url_line = line_bounds(found.text, url.start)
        for context in found.registration:
            if line_bounds(found.text, context.start) != url_line:
                continue
            distance = max(context.start - url.end, url.start - context.end, 0)
            candidates.append((distance, url.start, url.text))
    return min(candidates)[2] if candidates else None


def _short_labelled(found: SignalSet, name: str, limit: int) -> str | None:
    value = _labelled_value(found, name)
    return value if value and len(value) <= limit else None


def area_text(found: SignalSet) -> str | None:
    """An explicitly labelled neighborhood/locality, kept as written; never geocoded."""
    compound = _compound_location(found)
    if compound:
        return compound[0]
    branches = []
    for line in found.text.splitlines():
        if line.lstrip(' \t\u2066\u2067\u2068\u2069').startswith('📍'):
            branch = re.fullmatch(r'📍\s*([\w‌ ]{2,60})[،,]\s*شعبه\s+([\w‌ ]{2,60})', line.strip(' \t\u2066\u2067\u2068\u2069'))
            if branch:
                branches.append(branch[2])
    if len(set(branches)) == 1:
        return branches[0]
    labelled = _short_labelled(found, "area", 120)
    if labelled:
        return labelled
    approximate = _approximate_area(found)
    if approximate:
        return approximate
    values = {}
    for line in found.text.splitlines():
        if not line.lstrip(" \t\u2066\u2067\u2068\u2069").startswith("📍"):
            continue
        match = re.search(r"(?<!\w)(?:محدوده|محله|منطقه)\s+([^،,\n]+)", normalize(line))
        if match:
            value = line[match.start(1):match.end(1)].strip(_TRIM)
            if value and len(value) <= 120 and not has_address_detail(value):
                values.setdefault(" ".join(phrase_tokens(value)), value)
    return next(iter(values.values())) if len(values) == 1 else None


def _approximate_area(found: SignalSet) -> str | None:
    """"لوکیشن حدودی این تجربه ستارخانه." -> "ستارخانه", exactly as written.

    The sentence must say the location is approximate, and the value must be a
    short name ending the sentence: no address detail, no city, no geocoding.
    """
    terms = "|".join(re.escape(normalize(t)) for t in rules.APPROXIMATE_LOCATION_TERMS)
    qualifiers = "|".join(re.escape(normalize(q)) for q in rules.APPROXIMATE_QUALIFIERS)
    nouns = "|".join(re.escape(normalize(n)) for n in ("تجربه", *rules.DURATION_EVENT_NOUNS))
    pattern = (r"(?<!\w)(?:" + terms + r")\s+(?:" + qualifiers + r")\s*(?::\s*)?(?:(?:این|of\s+this)\s+(?:"
               + nouns + r")\s+)?([^\W\d_](?:[^\n.،,!؟?:]{0,38}[^\W\d_])?)\s*(?=[.\n،,!؟?]|$)")
    values = {}
    for match in re.finditer(pattern, found.normalized):
        value = found.text[match.start(1):match.end(1)].strip(_TRIM)
        tokens = phrase_tokens(value)
        if (not 1 <= len(tokens) <= 3 or has_address_detail(value)
                or " ".join(tokens) in CITY_TOKENS or any(t in {"است", "هست", "دقیق"} for t in tokens)):
            continue
        values.setdefault(" ".join(tokens), value)
    return next(iter(values.values())) if len(values) == 1 else None


def location_context(found: SignalSet) -> str | None:
    """Explicit building context, separate from street address and named venue."""
    compound = _compound_location(found)
    return compound[2] if compound else None


def duration_text(found: SignalSet) -> str | None:
    """An explicitly stated length; clocks never imply one.

    A labelled value ("مدت: ۳ ساعت") wins. Otherwise only an "N‌روزه"/"N‌ساعته"
    adjective directly modifying an event noun ("این رویداد سه‌روزه") counts.
    """
    labelled = _short_labelled(found, "duration", 60)
    if labelled:
        return labelled
    nouns = "|".join(re.escape(normalize(n)) for n in rules.DURATION_EVENT_NOUNS)
    numbers = "|".join(re.escape(normalize(n)) for n in rules.DURATION_NUMBER_WORDS if n not in {"نیم", "چند"})
    pattern = (r"(?<!\w)(?:" + nouns + r")\s+((?:\d{1,2}|" + numbers + r")[\s‌]?(?:روزه|ساعته))(?!\w)")
    values = {}
    for match in re.finditer(pattern, found.normalized):
        value = found.text[match.start(1):match.end(1)]
        values.setdefault("".join(normalize(value).split()).replace("‌", ""), value)
    return next(iter(values.values())) if len(values) == 1 else None


_LENGTH_WORDS = {"یک": 1, "دو": 2, "سه": 3, "چهار": 4, "پنج": 5, "شش": 6, "هفت": 7, "هشت": 8, "نه": 9, "ده": 10}
_LENGTH = re.compile(r"(?:(?P<number>\d{1,3}|" + "|".join(_LENGTH_WORDS) + r")\s*)?(?P<unit>ساعت|دقیقه)"
                     r"(?P<half>\s*و\s*نیم)?")


def duration_minutes(value: str) -> int | None:
    """Minutes of an explicit length ("۲ ساعت", "یک ساعت و نیم", "۹۰ دقیقه",
    "سه‌ساعته"), else None."""
    folded = " ".join(normalize(value).replace("‌", " ").split())
    folded = re.sub(r"(ساعت|دقیقه)(?:ه|\s?ای)$", r"\1", folded)
    if folded in {"نیم ساعت"}:
        return 30
    match = _LENGTH.fullmatch(folded)
    if match is None or match["number"] is None:
        return None
    number = int(match["number"]) if match["number"].isdigit() else _LENGTH_WORDS[match["number"]]
    minutes = number * (60 if match["unit"] == "ساعت" else 1)
    return minutes + (30 if match["half"] and match["unit"] == "ساعت" else 0) if not (
        match["half"] and match["unit"] == "دقیقه") else None


def narrative_durations(found: SignalSet) -> tuple[str, ...]:
    """Lengths stated in prose, exactly as written: "به مدت <length>", or a
    length adjective directly after an activity noun ("تجربه‌ای سه‌ساعته")."""
    values = []
    for match in re.finditer(r"(?<!\w)به\s+مدت\s+((?:\d{1,3}|" + "|".join(_LENGTH_WORDS)
                             + r"|نیم)\s*(?:ساعت|دقیقه)(?:\s*و\s*نیم)?)(?!\w)", found.normalized):
        values.append(found.text[match.start(1):match.end(1)])
    nouns = "|".join(re.escape(normalize(n)) for n in (*rules.DURATION_EVENT_NOUNS, *rules.NARRATIVE_DURATION_NOUNS))
    numbers = "|".join(re.escape(w) for w in _LENGTH_WORDS)
    for match in re.finditer(r"(?<!\w)(?:" + nouns + r")(?:[\s‌]?ای)?\s+((?:\d{1,2}|" + numbers
                             + r")[\s‌]?(?:ساعته|دقیقه‌ای|دقیقه ای))(?!\w)", found.normalized):
        values.append(found.text[match.start(1):match.end(1)])
    return tuple(dict.fromkeys(values))


def organizer_name(found: SignalSet) -> str | None:
    """Explicit organizer label or event-is-held-by wording; never the publisher."""
    labelled = _short_labelled(found, "organizer", 120)
    if labelled:
        return labelled
    matches = list(re.finditer(r'(?<!\w)(?:این\s+)?(?:رویداد|کارگاه|نمایشگاه)\s+که\s+توسط\s+'
        r'(?P<name>[^،,.!\n]{2,80}?)\s+برگزار\s+می[‌ ]?(?:شود|شه)(?!\w)', found.text))
    names = {m['name'].strip() for m in matches}
    return names.pop() if len(names) == 1 else None


def availability_text(found: SignalSet) -> str | None:
    """Explicit capacity/availability wording: a labelled value or a whole status line."""
    labelled = _short_labelled(found, "capacity", 80)
    if labelled:
        return labelled
    phrases = {" ".join(normalize(p).split()) for p in rules.AVAILABILITY_PHRASES}
    for line in found.text.splitlines():
        value = line.strip(_TRIM)
        if value and " ".join(normalize(value).split()) in phrases:
            return value
    return None


def is_sold_out(value: str | None) -> bool:
    folded = " ".join(normalize(value or "").split()).strip(_TRIM)
    return folded in {" ".join(normalize(p).split()) for p in rules.SOLD_OUT_PHRASES}


_WEEKDAY = "|".join(sorted((re.escape(normalize(d)) for d in rules.PERSIAN_WEEKDAYS), key=len, reverse=True))
_MONTH = "|".join(sorted((re.escape(normalize(m)) for m in rules.JALALI_MONTHS + rules.GREGORIAN_MONTHS),
                         key=len, reverse=True))
_PLURAL_WEEKDAY = re.compile(r"(?<!\w)(?:" + _WEEKDAY + r")\s?ها(?!\w)")
_WEEKDAY_TOKEN = re.compile(r"(?<!\w)(?:" + _WEEKDAY + r")(?!\w)")
_SESSIONS = re.compile(r"(?<!\w)(?:[2-9]|[1-9]\d+|" + "|".join(rules.SESSION_COUNT_WORDS) + r")\s*(?:جلسه|سانس)(?!\w)")
_DAY_LIST = re.compile(r"(?<!\d)\d{1,2}(?:\s*(?:[،,]|و)\s*\d{1,2})+\s*(?:" + _MONTH + r")(?:\s*ماه)?(?!\w)")
_RECURRENCE = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(normalize(t)) for t in rules.RECURRENCE_TERMS) + r")(?!\w)")
_SENTENCE = re.compile(r"(?:[^\n.!?؟؛;]|\.(?=\s*\d))+")
_NEXT_CLOCK_LINE = re.compile(r"[ \t]*\n[ \t]*((?:ساعت\s*)?\d{1,2}(?::\d{2})?\s*(?:تا|الی|-|–)\s*\d{1,2}(?::\d{2})?"
                              r"(?:\s*(?:صبح|ظهر|عصر|شب))?)[ \t]*(?=\n|$)")
_ONLY_WEEKDAYS = re.compile(r"(?:\s|[،,\-–]|و|(?:" + _WEEKDAY + r")(?:\s?ها)?)+")


def source_schedule_text(found: SignalSet, exclude: str | None = None) -> str | None:
    """Exact multi-session/recurring schedule sentences; no occurrences are generated.

    A sentence qualifies with explicit schedule wording — a plural weekday
    ("یکشنبه‌ها"), several weekdays, a session count, recurrence vocabulary, or a
    day list before a month ("5،12،19 و 26 مهر") — together with temporal
    evidence. A single ordinary date stays in `source_date_text` only.
    """
    kept: dict[str, str] = {}
    for match in _SENTENCE.finditer(found.text):
        span = _trimmed_span(found.text, match.start(), match.end())
        if span is None:
            continue
        start, end = span
        value, folded = found.text[start:end], found.normalized[start:end]
        if exclude is not None and value.strip() == exclude.strip():
            continue  # A title mentioning "(۴ جلسه)" is not a schedule statement.
        # A weekday is its own date signal, so it cannot also be the evidence
        # that a plural weekday is a schedule: prose like "چهارشنبه‌ها تجریش
        # شلوغ است" needs a clock, a number or another date to qualify, unless
        # the sentence is nothing but weekday wording ("جمعه‌ها").
        has_temporal = (any(start <= s.start < end for s in found.times)
                        or any(start <= s.start < end and not _WEEKDAY_TOKEN.fullmatch(found.normalized[s.start:s.end])
                               for s in found.dates)
                        or bool(re.search(r"\d", folded))
                        or bool(_ONLY_WEEKDAYS.fullmatch(folded)))
        weekdays = {w.group(0).replace(" ", "") for w in _WEEKDAY_TOKEN.finditer(folded)}
        marked = bool(_PLURAL_WEEKDAY.search(folded) or len(weekdays) > 1
                      or _SESSIONS.search(folded) or _RECURRENCE.search(folded))
        key = " ".join(folded.split())
        # The same wording repeated (header, card, body) is kept once, even
        # when a card prefixes it with its city.
        if (_DAY_LIST.search(folded) or (marked and has_temporal)) and not any(
                key in other or other in key for other in kept):
            # A clock-only line directly under a date list ("۵ تا ۸ صبح") is
            # that list's stated hours; keep both lines as one exact slice.
            clock = _NEXT_CLOCK_LINE.match(found.normalized, end) if _DAY_LIST.search(folded) else None
            if clock:
                value = found.text[start:clock.end(1)]
            kept[key] = value
        if len(kept) == rules.MAX_SCHEDULE_SENTENCES:
            break
    return "\n".join(kept.values()) or None


def opening_hours_text(found: SignalSet) -> str | None:
    """The line a place uses to state when it is open, unconverted."""
    for signal in found.place_context:
        if signal.term in rules.OPENING_HOURS_TERMS:
            line = _line(found.text, signal.start)
            if line:
                return line
    return None


def category(found: SignalSet) -> str | None:
    """A controlled category, only from a term whose category wording is unambiguous."""
    for signal in found.event_strong + found.event_weak:
        mapped = rules.EVENT_CATEGORIES.get(signal.term)
        if mapped:
            return mapped
    return None


def place_category(found: SignalSet) -> str | None:
    for signal in found.place_terms:
        mapped = rules.PLACE_CATEGORIES.get(signal.term)
        if mapped:
            return mapped
    return None


def place_summary(found: SignalSet) -> str | None:
    """The source's own one-line description of itself, quoted rather than written."""
    signal = _first(found.place_terms)
    if signal is None:
        return None
    line = _line(found.text, signal.start)
    return line if line and len(line) <= _MAX_PLACE_SUMMARY else None


__all__ = [
    "address",
    "area_text",
    "availability_text",
    "category",
    "city",
    "duration_text",
    "event_format",
    "is_sold_out",
    "organizer_name",
    "source_schedule_text",
    "opening_hours_text",
    "place_category",
    "place_summary",
    "price_text",
    "reference_urls",
    "registration_url",
    "source_date_text",
    "title",
    "venue_name",
]
