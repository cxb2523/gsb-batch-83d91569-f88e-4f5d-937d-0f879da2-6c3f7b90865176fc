from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .raw_item import RawItem
from .source import SourceType


class EvidenceKind(StrEnum):
    CAPTION = 'caption'
    IMAGE_OCR = 'image_ocr'
    CAROUSEL_SLIDE_OCR = 'carousel_slide_ocr'
    REEL_FRAME_OCR = 'reel_frame_ocr'
    WEBSITE_TEXT = 'website_text'
    # The item's own card on the approved listing page, from the same observation.
    WEBSITE_LISTING = 'website_listing'


def _digest(*parts: object) -> str:
    payload = '\x1f'.join('' if part is None else str(part) for part in parts)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


@dataclass(frozen=True, slots=True)
class EvidenceFragment:
    '''One source-supported piece of text with its extraction provenance.'''

    fragment_id: str
    raw_item_id: str
    kind: EvidenceKind
    text: str
    source_url: str | None = None
    local_asset_path: str | None = None
    asset_hash: str | None = None
    slide_index: int | None = None
    frame_timestamp_ms: int | None = None
    extraction_engine: str | None = None
    extraction_version: str | None = None
    extraction_config: str | None = None
    raw_text: str | None = None
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.fragment_id.strip() or not self.raw_item_id.strip():
            raise ValueError('fragment_id and raw_item_id must not be empty')
        for name, required_kind in (
            ('slide_index', EvidenceKind.CAROUSEL_SLIDE_OCR),
            ('frame_timestamp_ms', EvidenceKind.REEL_FRAME_OCR),
        ):
            value = getattr(self, name)
            if self.kind is required_kind:
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise ValueError(f'{required_kind.value} requires a non-negative integer {name}')
            elif value is not None:
                raise ValueError(f'{name} is only valid for {required_kind.value}')

    @property
    def meaningful(self) -> bool:
        return bool(self.text.strip()) and self.failure_reason is None

    @property
    def sort_key(self) -> tuple[int, int, str]:
        order = {kind: index for index, kind in enumerate(EvidenceKind)}
        position = self.slide_index
        if position is None:
            position = self.frame_timestamp_ms if self.frame_timestamp_ms is not None else -1
        return order[self.kind], position, self.fragment_id

    @classmethod
    def create(
        cls, *, raw_item_id: str, kind: EvidenceKind, text: str,
        source_url: str | None = None, local_asset_path: str | Path | None = None,
        asset_hash: str | None = None, slide_index: int | None = None,
        frame_timestamp_ms: int | None = None, extraction_engine: str | None = None,
        extraction_version: str | None = None, extraction_config: str | None = None,
        raw_text: str | None = None, failure_reason: str | None = None,
    ) -> EvidenceFragment:
        path = str(local_asset_path) if local_asset_path is not None else None
        fragment_id = 'evidence:' + _digest(
            raw_item_id, kind.value, slide_index, frame_timestamp_ms, asset_hash,
            extraction_engine, extraction_version, extraction_config, raw_text, text,
            failure_reason,
        )
        return cls(
            fragment_id=fragment_id, raw_item_id=raw_item_id, kind=kind, text=text,
            source_url=source_url, local_asset_path=path, asset_hash=asset_hash,
            slide_index=slide_index, frame_timestamp_ms=frame_timestamp_ms,
            extraction_engine=extraction_engine, extraction_version=extraction_version,
            extraction_config=extraction_config, raw_text=raw_text,
            failure_reason=failure_reason,
        )


def caption_fragment(raw_item: RawItem) -> EvidenceFragment:
    return EvidenceFragment.create(
        raw_item_id=raw_item.id, kind=EvidenceKind.CAPTION,
        text=raw_item.raw_text, raw_text=raw_item.raw_text,
        source_url=raw_item.content_url, asset_hash=raw_item.content_hash,
    )


def primary_fragment(raw_item: RawItem) -> EvidenceFragment:
    if raw_item.source_type is SourceType.INSTAGRAM:
        return caption_fragment(raw_item)
    return EvidenceFragment.create(
        raw_item_id=raw_item.id, kind=EvidenceKind.WEBSITE_TEXT,
        text=raw_item.raw_text, raw_text=raw_item.raw_text,
        source_url=raw_item.content_url, asset_hash=raw_item.content_hash,
    )


def website_listing_fragment(raw_item: RawItem) -> EvidenceFragment | None:
    '''This observation's own listing-card text, never a historical listing.'''
    if raw_item.source_type is not SourceType.WEBSITE:
        return None
    text = raw_item.raw_metadata.get('listing_card_text')
    if not isinstance(text, str) or not text.strip():
        return None
    list_url = raw_item.raw_metadata.get('list_url')
    return EvidenceFragment.create(
        raw_item_id=raw_item.id, kind=EvidenceKind.WEBSITE_LISTING, text=text, raw_text=text,
        source_url=list_url if isinstance(list_url, str) else None, asset_hash=raw_item.content_hash,
    )


def primary_fragments(raw_item: RawItem) -> tuple[EvidenceFragment, ...]:
    listing = website_listing_fragment(raw_item)
    return (primary_fragment(raw_item),) + ((listing,) if listing is not None else ())


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    raw_item_id: str
    fragments: tuple[EvidenceFragment, ...] = ()

    def __post_init__(self) -> None:
        if not self.raw_item_id.strip():
            raise ValueError('raw_item_id must not be empty')
        if any(fragment.raw_item_id != self.raw_item_id for fragment in self.fragments):
            raise ValueError('every fragment must belong to the bundle raw_item_id')
        ordered = tuple(sorted(self.fragments, key=lambda item: item.sort_key))
        object.__setattr__(self, 'fragments', ordered)

    @classmethod
    def from_raw_item(
        cls, raw_item: RawItem, extra_fragments: tuple[EvidenceFragment, ...] = ()
    ) -> EvidenceBundle:
        return cls(raw_item.id, (*primary_fragments(raw_item), *extra_fragments))


@dataclass(frozen=True, slots=True)
class DiscoveryUnit:
    '''An explicit group; multiple units may belong to one evidence bundle.'''

    unit_id: str
    raw_item_id: str
    text: str
    fragments: tuple[EvidenceFragment, ...]
    # Fragments that only repeated this unit's anchor, or whose remaining evidence
    # was too weak to stand alone. Kept as provenance; never part of `text`.
    collapsed: tuple[EvidenceFragment, ...] = ()
    # (fragment_id, reason) grouping explanations for debug output; never persisted.
    notes: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.unit_id.strip() or not self.raw_item_id.strip():
            raise ValueError('unit_id and raw_item_id must not be empty')
        if not self.fragments:
            raise ValueError('a DiscoveryUnit must contain at least one fragment')
        if any(fragment.raw_item_id != self.raw_item_id for fragment in self.fragments + self.collapsed):
            raise ValueError('every fragment must belong to the unit raw_item_id')

    @classmethod
    def from_fragments(
        cls, fragments: tuple[EvidenceFragment, ...], *, strategy: str,
        collapsed: tuple[EvidenceFragment, ...] = (), notes: tuple[tuple[str, str], ...] = (),
    ) -> DiscoveryUnit:
        '''Build a versioned unit after grouping, preserving every source word.

        Collapsed fragments join the identity but never the text.
        '''
        if not fragments or not strategy.strip():
            raise ValueError('fragments and grouping strategy must not be empty')
        ordered = tuple(sorted(fragments, key=lambda fragment: fragment.sort_key))
        repeated = tuple(sorted(collapsed, key=lambda fragment: fragment.sort_key))
        raw_item_id = ordered[0].raw_item_id
        if any(fragment.raw_item_id != raw_item_id for fragment in ordered + repeated):
            raise ValueError('every fragment must belong to the unit raw_item_id')
        identities = [fragment.fragment_id for fragment in ordered + repeated]
        if len(set(identities)) != len(identities):
            raise ValueError('a unit cannot contain duplicate fragment identities')
        content: list[object] = [raw_item_id, strategy, [fragment.fragment_id for fragment in ordered]]
        if repeated:
            content.append([fragment.fragment_id for fragment in repeated])
        payload = json.dumps(content, ensure_ascii=False, separators=(',', ':'))
        known = set(identities)
        return cls(
            unit_id='unit:' + hashlib.sha256(payload.encode('utf-8')).hexdigest(),
            raw_item_id=raw_item_id, text='\n'.join(fragment.text for fragment in ordered),
            fragments=ordered, collapsed=repeated,
            notes=tuple(sorted(note for note in notes if note[0] in known)),
        )

    @classmethod
    def from_fragment(cls, fragment: EvidenceFragment) -> DiscoveryUnit:
        return cls(
            unit_id='unit:' + _digest(fragment.raw_item_id, fragment.fragment_id),
            raw_item_id=fragment.raw_item_id, text=fragment.text,
            fragments=(fragment,),
        )


def caption_discovery_units(bundle: EvidenceBundle) -> tuple[DiscoveryUnit, ...]:
    caption = next(
        (item for item in bundle.fragments if item.kind is EvidenceKind.CAPTION), None
    )
    return (DiscoveryUnit.from_fragment(caption),) if caption is not None else ()


def primary_discovery_units(raw_item: RawItem) -> tuple[DiscoveryUnit, ...]:
    return (DiscoveryUnit.from_fragment(primary_fragment(raw_item)),)


__all__ = [
    'DiscoveryUnit', 'EvidenceBundle', 'EvidenceFragment', 'EvidenceKind',
    'caption_discovery_units', 'caption_fragment', 'primary_fragment', 'primary_fragments',
    'primary_discovery_units', 'website_listing_fragment',
]
