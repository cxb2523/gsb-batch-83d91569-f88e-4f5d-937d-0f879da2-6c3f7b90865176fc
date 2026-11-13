from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..domain import EvidenceFragment, EvidenceKind
from .jsonl import StorageError


@dataclass(frozen=True, slots=True)
class EvidenceStoreOutcome:
    path: Path
    new: int
    already_existing: int


@dataclass(frozen=True, slots=True)
class EvidenceReadOutcome:
    path: Path
    fragments: tuple[EvidenceFragment, ...] = ()
    malformed: tuple[str, ...] = ()


def evidence_fragment_to_dict(fragment: EvidenceFragment) -> dict[str, Any]:
    return {
        'fragment_id': fragment.fragment_id, 'raw_item_id': fragment.raw_item_id,
        'kind': fragment.kind.value, 'text': fragment.text,
        'source_url': fragment.source_url, 'local_asset_path': fragment.local_asset_path,
        'asset_hash': fragment.asset_hash, 'slide_index': fragment.slide_index,
        'frame_timestamp_ms': fragment.frame_timestamp_ms,
        'extraction_engine': fragment.extraction_engine,
        'extraction_version': fragment.extraction_version,
        'extraction_config': fragment.extraction_config, 'raw_text': fragment.raw_text,
        'failure_reason': fragment.failure_reason,
    }


def _optional_text(payload: dict[str, Any], name: str) -> str | None:
    value = payload.get(name)
    if value is not None and not isinstance(value, str):
        raise ValueError(f'{name} must be text or null')
    return value


def _optional_int(payload: dict[str, Any], name: str) -> int | None:
    value = payload.get(name)
    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
        raise ValueError(f'{name} must be an integer or null')
    return value


def evidence_fragment_from_dict(payload: dict[str, Any]) -> EvidenceFragment:
    required = ('fragment_id', 'raw_item_id', 'kind', 'text')
    if any(not isinstance(payload.get(name), str) for name in required):
        raise ValueError('fragment identity, kind, and text must be text')
    try:
        kind = EvidenceKind(payload['kind'])
    except ValueError as exc:
        raise ValueError('unknown evidence kind') from exc
    return EvidenceFragment(
        fragment_id=payload['fragment_id'], raw_item_id=payload['raw_item_id'],
        kind=kind, text=payload['text'], source_url=_optional_text(payload, 'source_url'),
        local_asset_path=_optional_text(payload, 'local_asset_path'),
        asset_hash=_optional_text(payload, 'asset_hash'),
        slide_index=_optional_int(payload, 'slide_index'),
        frame_timestamp_ms=_optional_int(payload, 'frame_timestamp_ms'),
        extraction_engine=_optional_text(payload, 'extraction_engine'),
        extraction_version=_optional_text(payload, 'extraction_version'),
        extraction_config=_optional_text(payload, 'extraction_config'),
        raw_text=_optional_text(payload, 'raw_text'),
        failure_reason=_optional_text(payload, 'failure_reason'),
    )


class JsonlEvidenceStore:
    '''Append-only evidence storage keyed by deterministic fragment id.'''

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def read(self) -> EvidenceReadOutcome:
        if not self._path.exists():
            return EvidenceReadOutcome(self._path)
        try:
            content = self._path.read_text(encoding='utf-8')
        except OSError as exc:
            raise StorageError(f'could not read {self._path}: {exc}') from exc
        fragments: list[EvidenceFragment] = []
        malformed: list[str] = []
        seen: set[str] = set()
        for number, line in enumerate(content.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    raise ValueError('expected a JSON object')
                fragment = evidence_fragment_from_dict(payload)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                malformed.append(f'line {number}: {exc}')
                continue
            if fragment.fragment_id not in seen:
                seen.add(fragment.fragment_id)
                fragments.append(fragment)
        return EvidenceReadOutcome(
            self._path, fragments=tuple(fragments), malformed=tuple(malformed)
        )

    def append_new(self, fragments: Iterable[EvidenceFragment]) -> EvidenceStoreOutcome:
        known = {fragment.fragment_id for fragment in self.read().fragments}
        pending: list[EvidenceFragment] = []
        existing = 0
        for fragment in fragments:
            if fragment.fragment_id in known:
                existing += 1
                continue
            known.add(fragment.fragment_id)
            pending.append(fragment)
        if pending:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open('a', encoding='utf-8', newline='\n') as handle:
                    for fragment in pending:
                        payload = evidence_fragment_to_dict(fragment)
                        handle.write(json.dumps(payload, ensure_ascii=False) + '\n')
            except OSError as exc:
                raise StorageError(f'could not write {self._path}: {exc}') from exc
        return EvidenceStoreOutcome(self._path, len(pending), existing)


__all__ = [
    'EvidenceReadOutcome', 'EvidenceStoreOutcome', 'JsonlEvidenceStore',
    'evidence_fragment_from_dict', 'evidence_fragment_to_dict',
]
