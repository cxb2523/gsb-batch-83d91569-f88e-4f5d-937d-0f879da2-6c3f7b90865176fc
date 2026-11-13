from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

# Facts an adapter may read from explicit page structure (a labelled section,
# a fixed header slot, a caption label). Values are exact retained source text.
STRUCTURED_FIELDS = frozenset({
    'description_text', 'area_text', 'duration_text', 'organizer_name', 'availability_text',
    'price_text', 'source_date_text', 'source_category_text',
})
# Where a structured value was observed: the item's own detail page, or its own
# listing card on the approved listing page.
FIELD_ORIGINS = ('detail', 'listing')
MAX_CARD_TEXT = 1500
SESSION_UNVERIFIED_PROPERTIES = 'unverified_properties'
# Child timeslot statuses: ownership and start/end order were validated, but the
# timeslot does not lie inside, or cannot be placed against, its parent window.
TIMESLOT_OUTSIDE_PARENT_WINDOW = 'timeslot_outside_parent_window'
TIMESLOT_PARENT_WINDOW_UNKNOWN = 'timeslot_parent_window_unknown'
# Whole sessions plus child timeslots retained from one page (observed maximum 324).
MAX_SESSION_RECORDS = 2_000
SESSION_SCHEMA_STATUSES = (None, SESSION_UNVERIFIED_PROPERTIES, TIMESLOT_OUTSIDE_PARENT_WINDOW,
                           TIMESLOT_PARENT_WINDOW_UNKNOWN)
# Added after the first stored shape; omitted from serialization while unset so
# documented sessions serialize, and therefore hash, exactly as before.
_OPTIONAL_KEYS = frozenset(('schema_status', 'source_timeslot_id', 'end_iso', 'capacity_limit',
                            'booked_count', 'sold_out'))
_ISO = r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})'
_LOCATOR = r'react-router:loaderData/routes/events\.\$id/sessions/[0-9]{1,3}'


def parse_source_instant(value: object) -> datetime:
    """An exact public ISO instant with an explicit offset (``Z`` or ``±HH:MM``)."""
    if not isinstance(value, str) or len(value) > 40 or not re.fullmatch(_ISO, value):
        raise ValueError('invalid source session timestamp')
    try:
        instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('invalid source session timestamp') from exc
    if instant.utcoffset() is None:
        raise ValueError('source session timestamp requires an offset')
    return instant


def is_source_slice(name: str, value: str, text: str) -> bool:
    """A structural value is an exact slice of retained text. A description made
    of separate page sections may instead be blank-line-separated parts that are
    each an exact slice, in page order (no contiguous span is implied)."""
    if value in text:
        return True
    if name != 'description_text' or '\n\n' not in value:
        return False
    position = 0
    for part in value.split('\n\n'):
        found = text.find(part, position) if part.strip() else -1
        if found < 0:
            return False
        position = found + len(part)
    return True


@dataclass(frozen=True, slots=True)
class SourceSession:
    """Whitelisted facts from one public website session, before normalization.

    The source's ISO spelling and separate price keys are retained. No currency,
    end time, event-level price or availability is inferred by the collector.
    ``source_locator`` identifies the precise embedded-data path on the detail URL.

    A child timeslot keeps its parent's ``source_session_id`` and adds its own
    ``source_timeslot_id``, explicit ``end_iso`` and its own capacity facts.
    ``sold_out`` is the parent session's public flag, kept separate from the
    timeslot's ``enabled`` and seat counts; false never proves availability.
    """

    source_session_id: str
    source_event_id: str
    start_iso: str
    source_locator: str
    duration_hours: str | None = None
    price_per_person: str | None = None
    unit_price: str | None = None
    host_discount_pct: str | None = None
    platform_discount_pct: str | None = None
    remaining_seats: int | None = None
    enabled: bool | None = None
    # None for the documented shape. "unverified_properties" when the session also
    # carried properties whose meaning was not inspected: only its identity, start
    # and duration were kept, and it is never actionable until reviewed.
    schema_status: str | None = None
    source_timeslot_id: str | None = None
    end_iso: str | None = None
    capacity_limit: int | None = None
    booked_count: int | None = None
    sold_out: bool | None = None

    def __post_init__(self) -> None:
        if self.schema_status not in SESSION_SCHEMA_STATUSES:
            raise ValueError('invalid source session schema status')
        timeslot = self.source_timeslot_id is not None
        if (self.schema_status in (TIMESLOT_OUTSIDE_PARENT_WINDOW, TIMESLOT_PARENT_WINDOW_UNKNOWN)
                and not timeslot):
            raise ValueError('timeslot status requires a timeslot')
        for value in (self.source_session_id, self.source_event_id, *((self.source_timeslot_id,) if timeslot else ())):
            if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value):
                raise ValueError('invalid source session identity')
        locator = _LOCATOR + (r'/timeslots/[0-9]{1,3}' if timeslot else '')
        if not isinstance(self.source_locator, str) or not re.fullmatch(locator, self.source_locator):
            raise ValueError('invalid source session locator')
        start = parse_source_instant(self.start_iso)
        if timeslot != (self.end_iso is not None):
            raise ValueError('a timeslot, and only a timeslot, states its own end')
        if timeslot and parse_source_instant(self.end_iso) <= start:
            raise ValueError('timeslot end must follow its start')
        for name in ('duration_hours', 'price_per_person', 'unit_price',
                     'host_discount_pct', 'platform_discount_pct'):
            value = getattr(self, name)
            if value is None:
                continue
            if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,15}(?:\.[0-9]{1,6})?', value):
                raise ValueError('invalid source session numeric fact')
            try:
                amount = Decimal(value)
            except InvalidOperation as exc:
                raise ValueError('invalid source session numeric fact') from exc
            if name == 'duration_hours' and not Decimal(0) < amount <= Decimal(744):
                raise ValueError('invalid source session duration')
            if name.endswith('_discount_pct') and amount > 100:
                raise ValueError('invalid source session discount')
        if (self.remaining_seats is not None
                and (type(self.remaining_seats) is not int or not 0 <= self.remaining_seats <= 1_000_000)):
            raise ValueError('invalid source session remaining seats')
        for name in ('capacity_limit', 'booked_count'):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or not 0 <= value <= 1_000_000):
                raise ValueError('invalid source session capacity fact')
        for name in ('enabled', 'sold_out'):
            if getattr(self, name) is not None and type(getattr(self, name)) is not bool:
                raise ValueError('invalid source session flag')

    def to_dict(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__
                if name not in _OPTIONAL_KEYS or getattr(self, name) is not None}

    @classmethod
    def from_mapping(cls, value: object) -> SourceSession:
        if not isinstance(value, dict) or set(value) - cls.__dataclass_fields__.keys():
            raise ValueError('invalid source session mapping')
        try:
            return cls(**value)
        except TypeError as exc:
            raise ValueError('invalid source session mapping') from exc


@dataclass(frozen=True, slots=True)
class WebsiteConfig:
    """Small list/detail configuration; selectors are tag, .class, or #id only."""

    adapter: str = 'generic'
    detail_path_prefixes: tuple[str, ...] = ()
    content_selector: str = 'article'
    exclude_selectors: tuple[str, ...] = ()
    drop_query_params: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.adapter, str) or not re.fullmatch(r'[a-z][a-z0-9_-]*', self.adapter):
            raise ValueError('invalid website adapter key')
        for name in ('detail_path_prefixes', 'exclude_selectors', 'drop_query_params'):
            value = getattr(self, name)
            if not isinstance(value, tuple) or any(not isinstance(x, str) or not x for x in value):
                raise ValueError(f'website {name} must be a sequence of nonempty strings')
        if not self.detail_path_prefixes or any(
            not re.fullmatch(r'/(?:[A-Za-z0-9_-]+/)+', prefix)
            for prefix in self.detail_path_prefixes
        ):
            raise ValueError('website detail_path_prefixes must contain absolute directory paths')
        for selector in (self.content_selector, *self.exclude_selectors):
            if not isinstance(selector, str) or not re.fullmatch(r'[.#]?[A-Za-z_][A-Za-z0-9_-]*', selector):
                raise ValueError('website selectors support only tag, .class, or #id')
        if any(not re.fullmatch(r'[A-Za-z0-9_-]+', key) for key in self.drop_query_params):
            raise ValueError('invalid website drop_query_params')

    @classmethod
    def from_mapping(cls, value: object) -> WebsiteConfig:
        if not isinstance(value, dict) or set(value) - cls.__dataclass_fields__.keys():
            raise ValueError('invalid website configuration')
        options = dict(value)
        for name in ('detail_path_prefixes', 'exclude_selectors', 'drop_query_params'):
            if name in options:
                if not isinstance(options[name], list):
                    raise ValueError(f'website {name} must be a list')
                options[name] = tuple(options[name])
        return cls(**options)
