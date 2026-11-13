from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from ..domain import DiscoveryType, DiscoveryUnit, EvidenceBundle, EvidenceFragment, EvidenceKind
from ..extraction import fields, rules
from ..extraction.rule_based import classify
from ..extraction.signals import SignalSet, analyze, has_meaningful_content
from ..extraction.text import normalize, phrase_tokens, title_equivalence_key
from ..extraction.titles import event_title, descriptive_title

# Grouping explanations stay on `DiscoveryUnit.notes`; extraction promotes the two
# uncertainty/role-correction codes below into persistent candidate diagnostics.
NOTE_SUPPORT_ATTACHED = 'support_attached_to_anchor'
NOTE_REPEATED_ANCHOR = 'repeated_anchor_collapsed'
NOTE_INSUFFICIENT_OCR = 'ocr_fragment_insufficient_for_independent_event'
NOTE_TEMPORAL_OCR = 'repeated_anchor_with_unreliable_temporal_ocr'
NOTE_VENUE_ROLE = 'source_venue_reclassified_from_ocr_title'
NOTE_CAPTION_BRIDGE = 'caption_date_corroborates_noisy_reel_anchor'

_MEDIA_OCR = frozenset({EvidenceKind.IMAGE_OCR, EvidenceKind.CAROUSEL_SLIDE_OCR, EvidenceKind.REEL_FRAME_OCR})
# An unlabelled clock or numeric date alone on its OCR line ("3 am", "18:30", "9/25").
# Without a label, month or weekday it cannot be told apart from OCR noise.
_ISOLATED_TEMPORAL = re.compile(
    r'[^\w]*(?:\d{1,2}(?::\d{2})?\s*(?:am|pm)?|\d{1,4}[/\-]\d{1,2}(?:[/\-]\d{1,4})?)[^\w]*'
)


class GroupingStrategy(Protocol):
    name: str

    def group(self, bundle: EvidenceBundle) -> tuple[DiscoveryUnit, ...]: ...


def _equivalent(text: str) -> str:
    # No fuzzy word deletion: even a one-digit date/price change must survive.
    return ' '.join(normalize(text).split())


def _anchor(found: SignalSet) -> bool:
    return bool(found.named_event or found.named_place or classify(found)[0] is not DiscoveryType.OTHER)


def _support_line(text: str) -> bool:
    found = analyze(text)
    if not found.tokens:
        return False
    first = found.tokens[0].start
    # A label is only structural when it opens the line and has a value.
    if any(start <= first and text[end:].strip() for start, end in found.labels.values()):
        return True
    temporal = fields.source_date_text(found)
    if temporal and phrase_tokens(temporal) == phrase_tokens(text):
        return True
    if fields.price_text(found) and any(signal.start == first for signal in found.prices):
        return True
    if any(signal.start == first and signal.term in rules.OPENING_HOURS_TERMS
           for signal in found.place_context):
        return True
    # Registration wording must be tied to a URL; arbitrary prose stays separate.
    if fields.registration_url(found) and any(signal.start == first for signal in found.registration):
        remainder = text
        for signal in sorted(found.registration + found.urls, key=lambda item: item.start, reverse=True):
            remainder = remainder[:signal.start] + ' ' * (signal.end - signal.start) + remainder[signal.end:]
        return not has_meaningful_content(remainder)
    return False


@dataclass(frozen=True)
class _Profile:
    fragment: EvidenceFragment
    signals: SignalSet
    anchor: bool
    support: bool
    ambiguous: bool
    lines: tuple[str, ...]
    # Kind-tagged equivalence key of the fragment's single named title, if it anchors.
    title: tuple[str, ...] | None
    # Media OCR holding only isolated clock/numeric-date lines: never support text.
    insufficient: bool


def _profile(fragment: EvidenceFragment) -> _Profile:
    found = analyze(fragment.text)
    lines = tuple(line for line in fragment.text.splitlines() if line.strip())
    # Multiple named occurrences within one image cannot safely anchor more text.
    line_signals = [analyze(line) for line in lines]
    names = {_equivalent(part.named_event.text) for part in line_signals if part.named_event}
    places = {_equivalent(part.named_place.text) for part in line_signals if part.named_place}
    occurrences = {_equivalent(part.text) for part in line_signals
                   if classify(part)[0] is DiscoveryType.EVENT}
    ambiguous = len(names) > 1 or len(places) > 1 or len(occurrences) > 1
    anchor = _anchor(found) and not ambiguous
    insufficient = fragment.kind in _MEDIA_OCR and all(
        _weak_temporal(line) for line in lines if has_meaningful_content(line))
    support = not (
        anchor or ambiguous or insufficient or found.event_strong or found.event_weak
        or found.place_terms or found.retrospective or found.attendance
    ) and bool(lines) and all(_support_line(line) for line in lines)
    named = found.named_event or found.named_place
    title = None
    if anchor and named is not None:
        title = ('event' if found.named_event else 'place', *_title_words(found, named.start, named.end))
    return _Profile(fragment, found, anchor, support, ambiguous, lines, title, insufficient)


def _title_words(found: SignalSet, start: int, end: int) -> tuple[str, ...]:
    '''Folded title words plus numbers written directly after them on the same line.

    A named construction never contains a bare number, but "کارگاه سفال ۱" and
    "کارگاه سفال ۲" are different occurrences, so trailing numbers stay significant.
    '''
    words = list(title_equivalence_key(found.text[start:end]))
    for token in found.tokens:
        if token.start < end:
            continue
        if not token.text.isdigit() or any(char not in ' \t\u200c' for char in found.text[end:token.start]):
            break
        words.append(token.text)
        end = token.end
    return tuple(words)


def _weak_temporal(line: str) -> bool:
    return bool(_ISOLATED_TEMPORAL.fullmatch(normalize(line).strip()))


def _temporal_conflict(a: SignalSet, b: SignalSet) -> bool:
    left, right = fields.source_date_text(a), fields.source_date_text(b)
    if not (left and right) or _equivalent(left) == _equivalent(right):
        return False
    # Date-only wording and clock-only wording describe different components of
    # one occurrence; any other unequal pair abstains.
    return not ((a.dates and not a.times and b.times and not b.dates)
                or (b.dates and not b.times and a.times and not a.dates))


def _conflicts(first: _Profile, second: _Profile) -> bool:
    a, b = first.signals, second.signals
    if _temporal_conflict(a, b):
        return True
    # Compare source wording only; no date, price, or address normalization here.
    for reader in (fields.address, fields.venue_name, fields.city, fields.price_text,
                   fields.registration_url, fields.opening_hours_text):
        left, right = reader(a), reader(b)
        if left and right and _equivalent(left) != _equivalent(right):
            return True
    return False


def _adjacent(first: EvidenceFragment, second: EvidenceFragment) -> bool:
    if first.kind is not second.kind:
        return False
    if first.kind is EvidenceKind.CAROUSEL_SLIDE_OCR:
        return second.slide_index == first.slide_index + 1
    # Adjacent *stored* samples only; unavailable observations reset the chain.
    return first.kind is EvidenceKind.REEL_FRAME_OCR


def _title_line(line: str, title: tuple[str, ...]) -> bool:
    '''The whole title, or an exact contiguous run of at least two of its words.'''
    words = title_equivalence_key(line)
    if not words or len(words) > len(title):
        return False
    if words == title:
        return True
    return len(words) >= 2 and any(
        title[start:start + len(words)] == words for start in range(len(title) - len(words) + 1)
    )


def _states_no_fact(text: str) -> bool:
    '''Whether text carries nothing discovery could read or anchor on.'''
    found = analyze(text)
    return not (found.positive or found.named_event or found.named_place or found.urls
                or found.labels or found.retrospective
                or fields.city(found) or fields.venue_name(found))


def _relation(profile: _Profile, title: tuple[str, ...]) -> tuple[bool, str] | None:
    '''How a media fragment relates to an anchor with `title`, or None.

    (True, note): it only repeats the anchor title, plus at most text that states no
    fact or isolated clock/numeric-date OCR lines. Provenance only, no text.
    (False, note): it repeats the title and otherwise holds only supporting lines;
    its text may join the anchor after the usual conflict checks.
    '''
    if profile.ambiguous or profile.fragment.kind not in _MEDIA_OCR:
        return None
    if profile.title is not None and profile.title != title:
        return None  # A different named occurrence.
    words = title[1:]
    residual = [line for line in profile.lines if not _title_line(line, words)]
    if len(residual) == len(profile.lines):
        return None  # The title is not repeated at all.
    meaningful = [line for line in residual if has_meaningful_content(line)]
    weak = [line for line in meaningful if _weak_temporal(line)]
    rest = [line for line in meaningful if line not in weak]
    # Tesseract can wrap a single unlabelled clock across lines ("۳\n‎am").
    # Inspect the complete residual, including numeric-only lines that the
    # meaningful-content guard would otherwise discard. The OCR stays intact in
    # collapsed provenance; it never becomes authoritative temporal wording.
    residual_text = '\n'.join(residual)
    residual_signals = analyze(residual_text)
    weak_spans = [s for s in residual_signals.times
                  if _weak_temporal(s.text) and '\n' in s.text]
    for signal in sorted(weak_spans, key=lambda s: s.start, reverse=True):
        residual_text = residual_text[:signal.start] + ' ' * (signal.end - signal.start) + residual_text[signal.end:]
    if weak_spans and _states_no_fact(residual_text):
        return True, NOTE_INSUFFICIENT_OCR
    if not rest or _states_no_fact('\n'.join(rest)):
        return True, NOTE_INSUFFICIENT_OCR if weak else NOTE_REPEATED_ANCHOR
    if profile.title is not None and all(_support_line(line) for line in rest):
        return False, NOTE_SUPPORT_ATTACHED
    return None


def _inline_noisy_repetition(first: _Profile, second: _Profile) -> bool:
    """A repeated named Reel anchor with the same unusable temporal line.

    This only covers mixed-script corruption between a Persian weekday and its
    labelled clock. A clean changed clock/date remains distinct. Both observations
    must have the exact title and date wording, plus another repeated multiword
    line; title/URL alone never qualify. The repeated frame stays auditable.
    """
    if (first.fragment.kind is not EvidenceKind.REEL_FRAME_OCR
            or second.fragment.kind is not EvidenceKind.REEL_FRAME_OCR
            or first.title is None or first.title != second.title
            or first.ambiguous or second.ambiguous):
        return False
    left, right = fields.source_date_text(first.signals), fields.source_date_text(second.signals)
    if not left or not right or _equivalent(left) != _equivalent(right):
        return False
    weekdays = {normalize(day) for day in rules.PERSIAN_WEEKDAYS}
    if normalize(left).strip() not in weekdays:
        return False
    if not (_corrupt_temporal(first) and _corrupt_temporal(second)):
        return False
    for reader in (fields.address, fields.venue_name, fields.city, fields.price_text,
                   fields.registration_url):
        a, b = reader(first.signals), reader(second.signals)
        if a or b:
            return False
    return bool(_subtitle_keys(first) & _subtitle_keys(second))


def _corrupt_temporal(profile: _Profile) -> bool:
    """The named title's own line has mixed-script garbage between weekday and clock.

    E.g. "ورکشاپ پیتزاء دوشنبه yao ساعت ۷": Latin letters inside Persian
    weekday/clock wording are OCR corruption, so its clock is not evidence.
    """
    weekdays = {normalize(day) for day in rules.PERSIAN_WEEKDAYS}
    named = profile.signals.named_event
    if named is None:
        return False
    for line in profile.lines:
        if named.text not in line:
            continue
        tail = normalize(line.split(named.text, 1)[1])
        return bool(re.search(r'[a-z]{2,}', tail) and 'ساعت' in tail
                    and any(day in tail for day in weekdays))
    return False


# One OCR letter substitution is tolerated only inside a word of at least this
# many letters, and only when the frame's own temporal line is proven corrupt.
_MIN_SUBSTITUTION_WORD = 4


def _ocr_same_word(media: str, caption: str, *, noisy: bool) -> bool:
    """Whether an OCR word plausibly renders the caption's word.

    Always: identical, or one extra trailing character ("پیتزاء", "پیتزاه").
    Only for a frame already proven noisy: additionally one in-place letter
    substitution ("پیعزاء"). Digits never take part, so numbers stay significant.
    """
    if media == caption:
        return True
    if len(media) == len(caption) + 1 and media.startswith(caption):
        return True
    if not noisy:
        return False
    if len(media) == len(caption) + 1:
        media = media[:-1]
    if len(media) != len(caption) or len(caption) < _MIN_SUBSTITUTION_WORD:
        return False
    changed = [(a, b) for a, b in zip(media, caption) if a != b]
    return len(changed) == 1 and all(char.isalpha() and not char.isascii() for char in changed[0])


def _subtitle_keys(profile: _Profile) -> set[tuple[str, ...]]:
    return {title_equivalence_key(re.split(r'[؟?/<>]', line, maxsplit=1)[0]) for line in profile.lines
            if len(title_equivalence_key(re.split(r'[؟?/<>]', line, maxsplit=1)[0])) >= 3
            and not analyze(line).positive}


def _single_calendar_key(found: SignalSet) -> tuple[str, ...] | None:
    """Exact weekday/day/month/year wording, excluding its optional clock."""
    if fields.source_schedule_text(found):
        return None
    wording = fields.source_date_text(found)
    if not wording:
        return None
    selected = analyze(wording)
    end = min((signal.start for signal in selected.times), default=len(wording))
    tokens = phrase_tokens(wording[:end])
    months = {normalize(month) for month in rules.JALALI_MONTHS + rules.JALALI_MONTH_FORMS}
    if (not any(token in months for token in tokens)
            or not any(token.isdigit() and 1 <= int(token) <= 31 for token in tokens)
            or any(token in {"و", "تا", "الی"} for token in tokens)):
        return None
    return tokens


def _caption_date_bridge(caption: _Profile, groups: list[_Group]) -> tuple[_Group, _Group] | None:
    """Link repeated noisy titles only through independently matching date evidence.

    The current caption and a separate non-anchor Reel frame must state the exact
    same single calendar date. That frame must also repeat the multiword subtitle
    of the sole remaining Event anchor, already proven to contain repeated corrupt
    temporal OCR. No fuzzy title comparison, extra Event, clock conflict or
    multi-session caption qualifies.
    """
    if not caption.anchor or caption.ambiguous or caption.title is not None:
        return None
    calendar = _single_calendar_key(caption.signals)
    if calendar is None or not caption.signals.times:
        return None
    anchors = [group for group in groups if group.members[0].anchor]
    if len(anchors) != 1:
        return None
    anchor = anchors[0]
    if not any(note == NOTE_TEMPORAL_OCR for _, note in anchor.notes):
        return None
    matches = []
    for bridge in groups:
        if bridge is anchor or len(bridge.members) != 1:
            continue
        member = bridge.members[0]
        if (member.fragment.kind is not EvidenceKind.REEL_FRAME_OCR or member.anchor
                or member.ambiguous or member.signals.times
                or _single_calendar_key(member.signals) != calendar
                or not (_subtitle_keys(member) & _subtitle_keys(anchor.members[0]))):
            continue
        if any(
            left and right and _equivalent(left) != _equivalent(right)
            for reader in (fields.address, fields.venue_name, fields.city, fields.price_text, fields.registration_url)
            for left, right in [(reader(caption.signals), reader(member.signals))]
        ):
            continue
        matches.append(bridge)
    return (anchor, matches[0]) if len(matches) == 1 else None


@dataclass
class _Group:
    members: list[_Profile]
    collapsed: list[EvidenceFragment] = field(default_factory=list)
    notes: list[tuple[str, str]] = field(default_factory=list)

    @property
    def title(self) -> tuple[str, ...] | None:
        return self.members[0].title

    def admit(self, profile: _Profile, title: tuple[str, ...]) -> bool:
        '''Attach a repetition of this group's anchor; False leaves the group unchanged.'''
        if _inline_noisy_repetition(self.members[0], profile):
            self.collapsed.append(profile.fragment)
            self.notes.append((profile.fragment.fragment_id, NOTE_TEMPORAL_OCR))
            return True
        relation = _relation(profile, title)
        if relation is None:
            return False
        collapse, note = relation
        if collapse:
            self.collapsed.append(profile.fragment)
        elif any(_conflicts(member, profile) for member in self.members):
            return False
        else:
            self.members.append(profile)
        self.notes.append((profile.fragment.fragment_id, note))
        return True


class ConservativeGrouping:
    '''Precision-first segmentation; never classify concatenations to decide merges.

    Version 2 adds same-occurrence handling within one RawItem: a media fragment
    that repeats an anchor's exact (folded) title, with no conflicting facts,
    joins that anchor instead of becoming a parallel candidate.
    '''

    name = 'conservative/2'

    @staticmethod
    def _split_caption(fragment: EvidenceFragment) -> tuple[EvidenceFragment, ...]:
        """Only separate independently headed, scheduled announcement blocks.

        Exact offsets and the original fragment remain in provenance. A list of
        names without per-activity schedule/attendance context stays unresolved.
        """
        headings = []
        cursor = 0
        for line in fragment.text.splitlines(keepends=True):
            text = line.strip()
            found = analyze(text)
            title, _ = event_title(found)
            if (title and len(text) <= 160 and found.event_strong
                    and not found.dates and not found.times and not found.registration
                    and found.tokens and found.event_strong[0].start == found.tokens[0].start):
                headings.append((cursor, title_equivalence_key(title)))
            cursor += len(line)
        if not 2 <= len(headings) <= 12 or len({key for _, key in headings}) != len(headings):
            return ()
        spans = [(start, headings[index + 1][0] if index + 1 < len(headings) else len(fragment.text))
                 for index, (start, _) in enumerate(headings)]
        if any(not (analyze(fragment.text[a:b]).dates or analyze(fragment.text[a:b]).registration)
               for a, b in spans):
            return ()
        return tuple(EvidenceFragment.create(raw_item_id=fragment.raw_item_id, kind=EvidenceKind.CAPTION,
            text=fragment.text[a:b], source_url=fragment.source_url, raw_text=fragment.text,
            extraction_engine='caption-segmentation', extraction_version='1',
            extraction_config=f'index={index};start={a};end={b};parent={fragment.fragment_id}')
            for index, (a, b) in enumerate(spans))

    def group(self, bundle: EvidenceBundle) -> tuple[DiscoveryUnit, ...]:
        caption: _Profile | None = None
        listing: list[_Profile] = []
        groups: list[_Group] = []
        current: _Group | None = None
        previous: EvidenceFragment | None = None
        for fragment in bundle.fragments:
            if not fragment.meaningful or not has_meaningful_content(fragment.text):
                current = None
                previous = None
                continue
            profile = _profile(fragment)
            if fragment.kind is EvidenceKind.CAPTION:
                caption = profile
                continue
            if fragment.kind is EvidenceKind.WEBSITE_LISTING:
                listing.append(profile)
                continue
            adjacent = previous is not None and _adjacent(previous, fragment)
            if profile.insufficient and adjacent and current is not None and current.members[0].anchor:
                # Kept as provenance of the neighbouring anchor; it is not a fact.
                current.collapsed.append(fragment)
                current.notes.append((fragment.fragment_id, NOTE_INSUFFICIENT_OCR))
                previous = fragment
                continue
            repeated = (
                adjacent and current is not None
                and fragment.kind is EvidenceKind.REEL_FRAME_OCR
                and _equivalent(fragment.text) == _equivalent(current.members[-1].fragment.text)
            )
            support = (
                adjacent and current is not None and current.members[0].anchor and profile.support
                and not any(_conflicts(prior, profile) for prior in current.members)
            )
            if repeated or support:
                current.members.append(profile)
                if not repeated:
                    current.notes.append((fragment.fragment_id, NOTE_SUPPORT_ATTACHED))
            else:
                # The most recent earlier anchor with the same title, if it admits this.
                target = next((group for group in reversed(groups)
                               if group.title is not None and group.admit(profile, group.title)), None)
                if target is not None:
                    current = target
                else:
                    current = _Group([profile])
                    groups.append(current)
            previous = fragment

        if caption is not None:
            lead = _Group([caption])
            absorbed = False
            # A described workshop may corroborate a repeated noisy Reel title.
            # Activity, subject and weekday must agree. Clean changed dates stay
            # separate; a one-character OCR suffix is corrected only by caption.
            described = descriptive_title(caption.fragment.text)
            if described and fields.source_date_text(caption.signals):
                words = title_equivalence_key(described)
                subjects = tuple(w for w in words[1:] if w not in {'ساخت', 'درست', 'کردن', 'پخت', 'اموزش'})
                weekdays = {normalize(d) for d in rules.PERSIAN_WEEKDAYS}
                caption_days = {normalize(s.text) for s in caption.signals.dates} & weekdays
                for group in list(groups):
                    member = group.members[0]
                    media_title, _ = event_title(member.signals)
                    media_words = title_equivalence_key(media_title or '')
                    media_days = {normalize(s.text) for s in member.signals.dates} & weekdays
                    # Every frame of the group shows corrupt weekday/clock wording,
                    # so neither its clock nor one substituted letter is evidence
                    # of a different activity. Clean frames get no such tolerance.
                    noisy = all(p.fragment.kind is EvidenceKind.REEL_FRAME_OCR and _corrupt_temporal(p)
                                for p in group.members)
                    same_subject = (len(media_words) == len(subjects) + 1 and media_words[:1] == words[:1]
                        and all(_ocr_same_word(a, b, noisy=noisy)
                                for a, b in zip(media_words[1:], subjects)))
                    media_date = fields.source_date_text(member.signals)
                    calendar_terms = {normalize(m) for m in rules.JALALI_MONTHS + rules.JALALI_MONTH_FORMS + rules.GREGORIAN_MONTHS}
                    no_calendar = not any(normalize(s.term) in calendar_terms or s.term.startswith('numeric')
                                          for s in member.signals.dates)
                    caption_clocks = {phrase_tokens(s.text) for s in caption.signals.times}
                    media_clocks = {phrase_tokens(s.text) for s in member.signals.times}
                    if (member.fragment.kind is EvidenceKind.REEL_FRAME_OCR and same_subject
                            and caption_days and media_days == caption_days
                            and no_calendar and (noisy or not media_clocks or media_clocks.issubset(caption_clocks))):
                        lead.collapsed.extend(p.fragment for p in group.members)
                        lead.collapsed.extend(group.collapsed)
                        # Corrupt OCR clocks are not evidence against the caption's
                        # clean schedule; the frames stay auditable as collapsed provenance.
                        lead.notes.append((member.fragment.fragment_id, 'caption_corroborates_noisy_activity_title'))
                        groups.remove(group)
                        absorbed = True
            bridge = _caption_date_bridge(caption, groups)
            if bridge is not None:
                anchor_group, date_group = bridge
                lead.members.extend(anchor_group.members)
                lead.collapsed.extend(anchor_group.collapsed)
                lead.collapsed.extend(p.fragment for p in date_group.members)
                lead.collapsed.extend(date_group.collapsed)
                lead.notes.extend(anchor_group.notes)
                lead.notes.append((date_group.members[0].fragment.fragment_id, NOTE_CAPTION_BRIDGE))
                groups.remove(anchor_group)
                groups.remove(date_group)
                absorbed = True
            caption_title, _ = event_title(caption.signals)
            caption_venue = fields.venue_name(caption.signals)
            if caption_title and caption_venue:
                venue_key = ''.join(phrase_tokens(caption_venue))
                for group in list(groups):
                    anchor = group.members[0]
                    named = anchor.signals.named_event
                    temporal = fields.source_date_text(anchor.signals)
                    month_only = (not temporal or normalize(temporal).strip() in
                                  {normalize(month) for month in rules.JALALI_MONTHS + rules.JALALI_MONTH_FORMS})
                    if (named is not None and anchor.fragment.kind in _MEDIA_OCR
                            and ''.join(phrase_tokens(named.text)) == venue_key
                            and ''.join(phrase_tokens(caption_title)) != venue_key
                            and not anchor.ambiguous and month_only and not anchor.signals.times
                            and not anchor.signals.registration and not anchor.signals.prices
                            and not fields.venue_name(anchor.signals) and not fields.address(anchor.signals)):
                        # The caption explicitly states the exact wording as a
                        # venue of a separately named Event. Retain the OCR as
                        # provenance rather than manufacturing a second Event.
                        lead.collapsed.extend(p.fragment for p in group.members)
                        lead.collapsed.extend(group.collapsed)
                        lead.notes.append((anchor.fragment.fragment_id, NOTE_VENUE_ROLE))
                        groups.remove(group)
                        absorbed = True
            if caption.title is not None:
                for group in list(groups):
                    if self._absorb(lead, group, caption.title):
                        groups.remove(group)
                        absorbed = True
            if absorbed:
                groups.insert(0, lead)
            elif len(groups) == 1 and self._caption_compatible(caption, groups[0].members):
                groups[0].members.insert(0, caption)
            else:
                groups.insert(0, lead)
        # A listing card was selected by the exact detail link, so it describes
        # the same item as that page. It joins the page unit; field-level
        # disagreement is detected by discovery, never resolved here.
        pages = [group for group in groups
                 if any(p.fragment.kind is EvidenceKind.WEBSITE_TEXT for p in group.members)]
        if listing and len(pages) == 1:
            pages[0].members.extend(listing)
        elif listing:
            groups.append(_Group(listing))
        units = tuple(
            DiscoveryUnit.from_fragments(
                tuple(profile.fragment for profile in group.members), strategy=self.name,
                collapsed=tuple(group.collapsed), notes=tuple(group.notes),
            ) for group in groups
        )
        result = []
        for unit in units:
            parts = (self._split_caption(unit.fragments[0]) if len(unit.fragments) == 1
                     and unit.fragments[0].kind is EvidenceKind.CAPTION else ())
            if parts:
                result.extend(DiscoveryUnit.from_fragments((part,), strategy=self.name,
                    collapsed=(unit.fragments[0], *unit.collapsed), notes=unit.notes) for part in parts)
            else:
                result.append(unit)
        return tuple(result)

    @staticmethod
    def _absorb(lead: _Group, group: _Group, title: tuple[str, ...]) -> bool:
        '''Merge a media group that repeats the caption anchor, all or nothing.

        Its first member must repeat the caption title; supporting members must not
        conflict with anything already in the caption unit. Same post alone is never
        enough: a group led by a different title or by unrelated text stays apart.
        '''
        if _relation(group.members[0], title) is None:
            return False
        trial = _Group(list(lead.members), list(lead.collapsed), list(lead.notes))
        for index, member in enumerate(group.members):
            if trial.admit(member, title):
                continue
            # Members the chain attached as support keep their place if compatible.
            if index == 0 or not member.support or any(_conflicts(prior, member) for prior in trial.members):
                return False
            trial.members.append(member)
        trial.collapsed.extend(group.collapsed)
        trial.notes.extend(note for note in group.notes
                           if note not in trial.notes)
        lead.members, lead.collapsed, lead.notes = trial.members, trial.collapsed, trial.notes
        return True

    @staticmethod
    def _caption_compatible(caption: _Profile, group: list[_Profile]) -> bool:
        if caption.ambiguous or any(part.ambiguous or _conflicts(caption, part) for part in group):
            return False
        if all(_equivalent(caption.fragment.text) == _equivalent(part.fragment.text) for part in group):
            return True
        # Same post / a single group alone is not proof of a shared occurrence.
        return (caption.anchor and all(part.support for part in group)) or (
            caption.support and group[0].anchor
        )
