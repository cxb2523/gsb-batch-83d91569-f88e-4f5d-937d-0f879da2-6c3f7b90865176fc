"""Conservative title recovery after an observation has qualified as an Event."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from . import fields, rules
from .signals import SignalSet, analyze
from .text import normalize, phrase_tokens, title_equivalence_key

_EDGE = " \t\r\n\u2066\u2067\u2068\u2069\u200e\u200f"


def display_text(value: str) -> str:
    """Presentation spelling only; preserve names, accents and meaningful ZWNJ."""
    value = unicodedata.normalize('NFC', value).translate(str.maketrans({'ي': 'ی', 'ك': 'ک'}))
    return ' '.join(''.join(c for c in value if c == '\u200c' or unicodedata.category(c) != 'Cf').split()).strip(' «»“”"،,.؛:')


_ACTIVITY = r'(?:نمایشگاه(?:\s+انفرادی|\s+گروهی)?|کارگاه|ورکشاپ|کنسرت|فستیوال|جشنواره|ایونت|رویداد|نمایش)'
_QUOTED_ACTIVITY = re.compile(r'(?P<head>' + _ACTIVITY + r')\s*[«“"](?P<name>[^»”"\n]{2,100})[»”"]')
_NAMED = re.compile(r'(?:با نام|به نام|با عنوان)\s*[«“"](?P<name>[^»”"]{2,100})[»”"]')
_WORKSHOP_SUBJECT = re.compile(r'(?:کارگاه|ورکشاپ)[^\n.!؟]{0,95}?(?P<subject>(?:ساخت|درست کردن|پخت|آموزش)\s+[^،,.!؟\n]{2,65}?)(?:\s+(?:رو|را|آشنا|یاد|می[\s‌])|[.!؟])')
_BAND = re.compile(r'گروه\s*[«“"]([^»”"\n]{2,80})[»”"][^\n]{0,100}(?:روی صحنه|اجرا)')
_FILM_DISCUSSION = re.compile(r'(?:ایونت|دورهمی)\s+فیلم\s+و\s+گفتگو(?:\s+با حضور\s+روانشناس)?')


@dataclass(frozen=True)
class TitleResolution:
    title: str | None = None
    source_title: str | None = None
    origin: str | None = None
    evidence_text: str | None = None
    review_required: bool = False


def descriptive_title(text: str) -> str | None:
    """Small auditable transformations, never unrestricted text generation."""
    clean = display_text(text)
    match = _WORKSHOP_SUBJECT.search(clean)
    if match:
        head = 'ورکشاپ' if 'ورکشاپ' in match[0] else 'کارگاه'
        subject = re.sub(r'دست[\s‌]+ساز', 'دست‌ساز', match['subject'])
        # Colloquial "درست کردن" has a literal, shorter activity equivalent.
        subject = subject.replace('درست کردن', 'ساخت')
        return display_text(head + ' ' + subject)
    match = _BAND.search(clean)
    if match:
        return 'اجرای گروه ' + display_text(match[1])
    match = _FILM_DISCUSSION.search(clean)
    if match:
        return display_text(match[0].replace('با حضور', 'با'))
    return None


def resolve_title(extraction_input) -> TitleResolution:
    """Resolve within this candidate's own fragments, explicit before descriptive."""
    heading = extraction_input.source_title
    if heading and heading in extraction_input.raw_text:
        return TitleResolution(heading, heading, 'explicit_website', heading)
    segments = extraction_input.segments or (('caption', extraction_input.raw_text),)
    explicit = []
    derived = []
    for origin, text in segments:
        found = analyze(text)
        title, diagnostics = event_title(found)
        if title and 'ambiguous_event_title' not in diagnostics:
            # The complete containing line is kept when punctuation was removed.
            evidence = next((line.strip(_EDGE) for line in text.splitlines()
                             if title_equivalence_key(title) == title_equivalence_key(line)
                             or title in line), None)
            if evidence is None:
                evidence = text  # e.g. "با نام" and its quote cross a line boundary
            original = title if title in text else next((m[0] for m in _QUOTED_ACTIVITY.finditer(text)), None)
            if original is None:
                original = next((m['name'] for m in _NAMED.finditer(text)), None)
            explicit.append(TitleResolution(title, original,
                'explicit_caption' if origin == 'caption' else 'explicit_website' if origin in {'detail', 'listing'} else 'explicit_media_ocr', evidence))
        value = descriptive_title(text)
        if value:
            derived.append(TitleResolution(value, None, 'derived_from_source_description', text, True))
    # Caption/detail identity outranks noisy OCR. Different independent media
    # names cannot be selected arbitrarily inside an incorrectly grouped unit.
    preferred = [v for v in explicit if v.origin != 'explicit_media_ocr'] or explicit
    keys = {title_equivalence_key(v.title) for v in preferred}
    if len(keys) == 1:
        return preferred[0]
    if preferred:
        return TitleResolution()
    if len({title_equivalence_key(v.title) for v in derived}) == 1:
        return derived[0]
    return TitleResolution()


def event_title(found: SignalSet) -> tuple[str | None, tuple[str, ...]]:
    """Use explicit names, theatrical credits or bounded event headings.

    Neither hashtags nor an arbitrary first line prove an event name. A quoted
    promotional slogan is not a title unless its own line contains performance
    credit wording. Multiple independent titles remain unresolved.
    """
    # A named activity may follow a modifier or a line break. Keep its name,
    # rather than stopping at "نمایشگاه انفرادی" or an organizer's identity.
    clean = display_text(found.text)
    activity_lines = []
    for line in found.text.splitlines():
        match = re.search(r'(?:ایونت|رویداد)\s+(?:بازی|فیلم|گفتگو)(?:\s+و\s+(?:گفتگو|فیلم|شام|بازی))+', display_text(line))
        if match and len(phrase_tokens(line[:line.find(match[0])])) <= 2:
            activity_lines.append(match[0])
    if len(set(activity_lines)) == 1:
        return activity_lines[0], ()
    quoted = [display_text(m['head'] + ' ' + m['name']) for m in _QUOTED_ACTIVITY.finditer(clean)]
    quoted += [display_text(m['name']) for m in _NAMED.finditer(clean)]
    if quoted:
        unique = {title_equivalence_key(v): v for v in quoted}
        return (next(iter(unique.values())), ()) if len(unique) == 1 else (None, ('ambiguous_event_title',))
    choices: dict[tuple[str, ...], str] = {}
    full_title = fields.title(found, found.named_event)
    for line in found.text.splitlines():
        part = analyze(line)
        if part.named_event:
            value = fields.title(part, part.named_event)
            if full_title and full_title in line and value and full_title.startswith(value):
                value = full_title
            if value:
                choices.setdefault(title_equivalence_key(value), value)
        # A standalone quotation tied to a theatre credit, not an unrelated quote.
        folded = normalize(line)
        if any(normalize(term) in folded for term in rules.TITLE_QUOTED_CONTEXT):
            for opening, closing in rules.QUOTE_PAIRS:
                start = line.find(opening)
                end = line.find(closing, start + len(opening)) if start >= 0 else -1
                if start < 0 or end < 0:
                    continue
                prefix = phrase_tokens(line[:start])
                value = line[start + len(opening):end].strip()
                if (not prefix and 2 <= len(phrase_tokens(value)) <= 12
                        and len(value) <= 160):
                    choices.setdefault(title_equivalence_key(value), value)
    if len(choices) > 1:
        return None, ('ambiguous_event_title',)
    if choices:
        value = next(iter(choices.values()))
        first_line = next((line.strip(_EDGE) for line in found.text.splitlines() if line.strip(_EDGE)), '')
        if value in first_line:
            tail = first_line.split(value, 1)[1]
            if (re.fullmatch(r'\s+در\s+[\w‌]+(?:\s+[\w‌]+){0,2}\s*[^\w]*', tail)
                    and not re.search(r'برج|عمارت|کافه|گالری|خانه|سالن|خیابان|پارک', tail)
                    and not any(normalize(head) in normalize(tail) for head in rules.NATURAL_VENUE_HEADS + rules.GENERIC_VENUE_HEADS)):
                value = first_line[first_line.index(value):].strip()
                value = re.sub(r'[^\w‌]+$', '', value)
        # Coordinated activities form one stated title (film and dinner, game
        # and discussion), not two Events. Stop at dates/clauses as usual.
        for line in found.text.splitlines():
            if value in line:
                tail = line.split(value, 1)[1]
                match = re.match(r'\s+و\s+(شام|گفتگو|گفت‌وگو|بازی)(?!\w)', tail)
                if match:
                    value += match[0]
        return display_text(value), ()
    lines = [line.strip(_EDGE) for line in found.text.splitlines() if line.strip(_EDGE)]
    if lines and found.dates:
        heading = display_text(re.sub(r'^\W+', '', lines[0]))
        if (re.fullmatch(_ACTIVITY + r'\s+[^\d،,:؛.!؟\n]{2,65}', heading)
                and 2 <= len(phrase_tokens(heading)) <= 8
                and not any(word in normalize(heading) for word in ('ثبت نام', 'برگزار', 'می ', 'قراره', 'بزرگ', 'هیجان'))
                and not analyze(heading).dates and not analyze(heading).times):
            return heading, ()
    if lines and found.dates and (found.registration or found.attendance or found.event_strong):
        first = analyze(lines[0])
        if first.tokens:
            # Retain a real headline beginning with an occurrence/project head,
            # only when the whole line is a compact heading rather than prose.
            tokens = tuple(t.text for t in first.tokens)
            starts_heading = any(tokens[:len(phrase_tokens(head))] == phrase_tokens(head)
                                 for head in rules.TITLE_HEADING_HEADS)
            # "گروه ... این‌بار در ..." is an announcement headline, not a bare
            # performer/organizer name. Require date, clock and ticket wording.
            performance_heading = bool(found.times and found.registration and any(
                tokens[:len(phrase_tokens(head))] == phrase_tokens(head)
                for head in rules.TITLE_PERFORMANCE_HEADS) and any(
                    normalize(phrase) in normalize(first.text)
                    for phrase in rules.TITLE_PERFORMANCE_ANNOUNCEMENTS))
            promotional = any(normalize(word) in tokens for word in rules.TITLE_PROMOTIONAL_WORDS)
            if ((starts_heading or performance_heading) and 3 <= len(tokens) <= 10 and not promotional
                    and not first.dates and not first.times and not first.urls
                    and not first.attendance and not first.registration):
                value = first.text[first.tokens[0].start:first.tokens[-1].end]
                return display_text(value), ()
        # A calendar celebration heading is a title only with an independently
        # described gathering and dated attendance context elsewhere in the unit.
        if (re.match(r'^\W*روز جهانی\s+\S', lines[0]) and len(phrase_tokens(lines[0])) <= 10
                and any(term in normalize(found.text) for term in ('دورهمی', 'برگزار می'))):
            return display_text(re.sub(r'^\W+', '', lines[0])), ()
    # A visibly announced/quoted name that did not satisfy safe parsing is distinct
    # from a source that never states a defensible title.
    title_shape = any(
        re.match(r'^\W*(?:' + '|'.join(map(re.escape, rules.NAMED_EVENT_HEAD_TERMS)) + r')\s+\S', line)
        for line in lines if not line.lstrip().startswith(('#', '@'))
    )
    return None, ('title_extraction_failed' if title_shape else 'missing_source_title',)


def caption_description(text: str) -> tuple[str | None, tuple[str, ...]]:
    """Preserve one caption verbatim only when it does not name several Events."""
    _, diagnostics = event_title(analyze(text))
    if 'ambiguous_event_title' in diagnostics:
        return None, ('ambiguous_caption_description',)
    return (text if text.strip() else None), ()
