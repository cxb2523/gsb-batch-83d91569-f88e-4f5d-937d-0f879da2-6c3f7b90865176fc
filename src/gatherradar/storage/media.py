from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from ..domain import MediaArtifact, MediaKind, RawItem
from .jsonl import StorageError

_SAFE_COMPONENT = re.compile(r'[^A-Za-z0-9._-]+')


def safe_component(value: str) -> str:
    cleaned = _SAFE_COMPONENT.sub('-', value.strip()).strip('.-')
    if not cleaned:
        raise ValueError('storage path component must not be empty')
    return cleaned


@dataclass(frozen=True, slots=True)
class ArtifactWriteOutcome:
    artifact: MediaArtifact
    created: bool


class MediaArtifactStore:
    '''Content-addressed runtime storage below data/media.'''

    def __init__(self, data_dir: str | Path, source_family: str, source_name: str) -> None:
        self.root = (
            Path(data_dir) / 'media' / safe_component(source_family) /
            safe_component(source_name.lower())
        )

    def write(
        self, raw_item: RawItem, kind: MediaKind, content: bytes, *,
        slide_index: int | None = None, frame_timestamp_ms: int | None = None,
        extension: str = 'png',
    ) -> ArtifactWriteOutcome:
        if not content:
            raise ValueError('captured artifact must not be empty')
        asset_hash = hashlib.sha256(content).hexdigest()
        item_dir = self.root / safe_component(raw_item.external_id)
        prefix = self._prefix(kind, slide_index, frame_timestamp_ms)
        filename = f'{prefix}-{asset_hash[:12]}.{safe_component(extension)}'
        path = item_dir / filename
        created = not path.exists()
        if created:
            try:
                item_dir.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            except OSError as exc:
                raise StorageError(f'could not write media artifact {path}: {exc}') from exc
        artifact = MediaArtifact.create(
            raw_item_id=raw_item.id, kind=kind, local_path=path,
            asset_hash=asset_hash, source_url=raw_item.content_url,
            slide_index=slide_index, frame_timestamp_ms=frame_timestamp_ms,
        )
        return ArtifactWriteOutcome(artifact=artifact, created=created)

    @staticmethod
    def _prefix(
        kind: MediaKind, slide_index: int | None, frame_timestamp_ms: int | None
    ) -> str:
        if kind is MediaKind.IMAGE:
            return 'image'
        if kind is MediaKind.CAROUSEL_SLIDE:
            if slide_index is None or slide_index < 0:
                raise ValueError('carousel slides require a non-negative slide_index')
            return f'slide-{slide_index:03d}'
        if frame_timestamp_ms is None or frame_timestamp_ms < 0:
            raise ValueError('reel frames require a non-negative frame_timestamp_ms')
        return f'reel-frame-{frame_timestamp_ms:09d}'


__all__ = ['ArtifactWriteOutcome', 'MediaArtifactStore', 'safe_component']
