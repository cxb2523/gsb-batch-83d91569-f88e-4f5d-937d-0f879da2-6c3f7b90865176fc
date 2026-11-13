from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class MediaKind(StrEnum):
    IMAGE = 'image'
    CAROUSEL_SLIDE = 'carousel_slide'
    REEL_FRAME = 'reel_frame'


@dataclass(frozen=True, slots=True)
class MediaArtifact:
    artifact_id: str
    raw_item_id: str
    kind: MediaKind
    local_path: Path
    asset_hash: str
    source_url: str | None = None
    slide_index: int | None = None
    frame_timestamp_ms: int | None = None

    def __post_init__(self) -> None:
        if not self.artifact_id.strip() or not self.raw_item_id.strip():
            raise ValueError('artifact_id and raw_item_id must not be empty')
        if len(self.asset_hash) != 64:
            raise ValueError('asset_hash must be a SHA-256 hex digest')
        try:
            int(self.asset_hash, 16)
        except ValueError as exc:
            raise ValueError('asset_hash must be a SHA-256 hex digest') from exc
        if self.kind is MediaKind.CAROUSEL_SLIDE and self.slide_index is None:
            raise ValueError('carousel slides require slide_index')
        if self.kind is MediaKind.REEL_FRAME and self.frame_timestamp_ms is None:
            raise ValueError('reel frames require frame_timestamp_ms')

    @classmethod
    def create(
        cls, *, raw_item_id: str, kind: MediaKind, local_path: str | Path,
        asset_hash: str, source_url: str | None = None,
        slide_index: int | None = None, frame_timestamp_ms: int | None = None,
    ) -> MediaArtifact:
        identity = '\x1f'.join((
            raw_item_id, kind.value,
            '' if slide_index is None else str(slide_index),
            '' if frame_timestamp_ms is None else str(frame_timestamp_ms), asset_hash,
        ))
        return cls(
            artifact_id='artifact:' + hashlib.sha256(identity.encode('utf-8')).hexdigest(),
            raw_item_id=raw_item_id, kind=kind, local_path=Path(local_path),
            asset_hash=asset_hash, source_url=source_url, slide_index=slide_index,
            frame_timestamp_ms=frame_timestamp_ms,
        )


__all__ = ['MediaArtifact', 'MediaKind']
