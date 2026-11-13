from __future__ import annotations

from collections.abc import Iterable

from ..domain import EvidenceBundle, EvidenceFragment, EvidenceKind, RawItem
from ..domain.evidence import primary_fragment
from ..ocr.quality import assess_text


def select_semantic_evidence(
    raw_item: RawItem, history: Iterable[EvidenceFragment]
) -> EvidenceBundle:
    '''Latest stored version per semantic slot, with a fresh current caption.

    Input order is storage append order, NOT bundle sort order. Failed/empty
    versions of a new capture replace earlier successes too; grouping decides
    semantic eligibility. Several OCR readings of the SAME image (same asset
    hash, e.g. a fallback engine) are alternative hypotheses: the latest one
    the OCR quality policy finds usable is chosen, else the latest reading.
    There is no run manifest, tombstone, or re-observation timestamp in Stage 4.
    This is therefore a latest-known-slot view, not a complete media-run snapshot.
    '''
    primary = primary_fragment(raw_item)
    latest: dict[tuple[EvidenceKind, int | str | None], EvidenceFragment] = {}
    readings: dict[tuple[EvidenceKind, int | str | None], list[EvidenceFragment]] = {}
    for fragment in history:
        # Caption and listing card always come from the current observation.
        if fragment.raw_item_id != raw_item.id or fragment.kind in (EvidenceKind.CAPTION, EvidenceKind.WEBSITE_LISTING):
            continue
        if (primary.kind is EvidenceKind.WEBSITE_TEXT and fragment.kind is primary.kind
                and fragment.source_url == primary.source_url):
            continue
        position: int | str | None = None
        if fragment.kind is EvidenceKind.CAROUSEL_SLIDE_OCR:
            position = fragment.slide_index
        elif fragment.kind is EvidenceKind.REEL_FRAME_OCR:
            position = fragment.frame_timestamp_ms
        elif fragment.kind is EvidenceKind.WEBSITE_TEXT:
            # One text slot per page URL; section identities need a future contract.
            position = fragment.source_url
        latest[fragment.kind, position] = fragment
        readings.setdefault((fragment.kind, position), []).append(fragment)
    for slot, fragment in latest.items():
        if fragment.kind in _OCR_KINDS and fragment.asset_hash:
            usable = [f for f in readings[slot] if f.asset_hash == fragment.asset_hash
                      and not f.failure_reason and assess_text(f.text).usable]
            if usable:
                latest[slot] = usable[-1]
    return EvidenceBundle.from_raw_item(raw_item, tuple(latest.values()))


_OCR_KINDS = frozenset({EvidenceKind.IMAGE_OCR, EvidenceKind.CAROUSEL_SLIDE_OCR, EvidenceKind.REEL_FRAME_OCR})
