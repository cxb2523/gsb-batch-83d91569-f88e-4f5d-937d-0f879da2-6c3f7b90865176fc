"""One effective source registry: the tracked base YAML plus a local overlay.

Storage and precedence
----------------------
* `config/sources.yaml` (tracked) holds the base definitions. Nothing here
  rewrites it, so `git pull` keeps updating it normally.
* `config/sources.local.json` (git-ignored, beside the base file) is the
  runtime overlay. It holds only (a) sources the owner registered locally and
  (b) lifecycle state for base sources: an owner pause, an owner re-enable of an
  owner-paused base source, or an archive flag. Base IDs, URLs, adapters and
  publisher identities are never copied or changed by the overlay.
  `GATHERRADAR_SOURCE_OVERLAY` may point to another file (or `none` to ignore).
* Base definitions win: a local source whose ID, Instagram account or canonical
  website URL now also appears in the base file is shadowed (kept in the file,
  not loaded) instead of producing a duplicate crawl.
* A policy reason (`robots`, `terms`) or `unsupported` can never be cleared by
  the overlay; such a source stays non-runnable whatever the overlay says.
* Writes are validated as a whole effective registry first, serialized by a
  file lock, written atomically, and the previous good version is kept as a
  `.bak` file that is used if the overlay itself becomes unreadable.

Nothing in this module deletes events, runs, evidence or review decisions:
archiving only hides a source from the active list and from future crawls.
"""
from __future__ import annotations

import json
import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .config import load_base_sources, source_from_mapping
from .domain.source import LOCKED_REASONS, Source, SourceType

LOGGER = logging.getLogger('gatherradar.registry')
OVERLAY_ENV = 'GATHERRADAR_SOURCE_OVERLAY'
VERSION = 1
MAX_LOCAL_SOURCES = 200
LOCK_TIMEOUT = 5.0


class RegistryError(ValueError):
    """A registry change that may not be applied; `code` is a stable reason."""

    def __init__(self, code: str, source_id: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.source_id = source_id


@dataclass(frozen=True)
class RegistryEntry:
    source: Source
    origin: str  # 'base' | 'local'

    @property
    def locked(self) -> bool:
        """Not runnable for a reason the owner cannot clear from a UI."""
        return self.source.disabled_reason in LOCKED_REASONS


def overlay_path(config_path: str | Path) -> Path | None:
    configured = os.environ.get(OVERLAY_ENV)
    if configured is not None:
        return None if configured.strip().lower() in ('', 'none', 'off') else Path(configured)
    base = Path(config_path)
    return base.with_name(base.stem + '.local.json')


def atomic_json(path: Path, value: dict) -> None:
    """Write-then-replace with fsync (kept local so loading config stays light)."""
    from uuid import uuid4
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    content = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')
    try:
        with temporary.open('xb') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def instagram_key(source: Source) -> str | None:
    return source.username.lower() if source.source_type is SourceType.INSTAGRAM and source.username else None


def website_key(url: str) -> str:
    """Canonical comparison key: host without `www.`, path without trailing
    slash, query kept (it can select a different listing), fragment dropped."""
    parts = urlsplit(url)
    host = (parts.hostname or '').lower()
    host = host[4:] if host.startswith('www.') else host
    path = parts.path.rstrip('/') or '/'
    query = '&'.join(sorted(p for p in parts.query.split('&') if p and not p.lower().startswith('utm_')))
    return f'{host}{path}' + (f'?{query}' if query else '')


def identity(source: Source) -> str:
    return f'ig:{instagram_key(source)}' if source.source_type is SourceType.INSTAGRAM else f'web:{website_key(source.url)}'


class _FileLock:
    """Cross-process exclusive lock with a bounded wait (msvcrt/fcntl)."""

    def __init__(self, path: Path, timeout: float = LOCK_TIMEOUT) -> None:
        self.path, self.timeout, self._handle = path, timeout, None

    def __enter__(self) -> _FileLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, 'a+b')
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                if os.name == 'nt':
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    handle.close()
                    raise RegistryError('registry_busy') from None
                time.sleep(0.05)
        self._handle = handle
        return self

    def __exit__(self, *exc) -> None:
        handle, self._handle = self._handle, None
        try:
            if os.name == 'nt':
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _empty() -> dict:
    return {'version': VERSION, 'sources': [], 'states': {}}


def _validate_payload(payload: object) -> dict:
    if not isinstance(payload, dict) or payload.get('version') != VERSION:
        raise ValueError('unsupported source overlay version')
    sources, states = payload.get('sources', []), payload.get('states', {})
    if not isinstance(sources, list) or not isinstance(states, dict) or len(sources) > MAX_LOCAL_SOURCES:
        raise ValueError('invalid source overlay shape')
    for record in sources:
        if not isinstance(record, dict):
            raise ValueError('invalid local source record')
        source_from_mapping({k: v for k, v in record.items() if k not in ('added_at', 'updated_at')})
    for key, state in states.items():
        if not isinstance(key, str) or not isinstance(state, dict) or set(state) - {'enabled', 'archived', 'updated_at'}:
            raise ValueError('invalid base source state')
        if 'enabled' in state and not isinstance(state['enabled'], bool):
            raise ValueError('invalid base source state')
        if not isinstance(state.get('archived', False), bool):
            raise ValueError('invalid base source state')
    return {'version': VERSION, 'sources': sources, 'states': states}


class SourceRegistry:
    def __init__(self, config_path: str | Path = 'config/sources.yaml', overlay: Path | None | str = 'default') -> None:
        self.config_path = Path(config_path)
        self.overlay = overlay_path(config_path) if overlay == 'default' else (Path(overlay) if overlay else None)

    # -- reading ---------------------------------------------------------------
    def _backup(self) -> Path:
        return self.overlay.with_name(self.overlay.name + '.bak')

    def _read_overlay(self) -> dict:
        if self.overlay is None or not self.overlay.exists():
            return _empty()
        try:
            return _validate_payload(json.loads(self.overlay.read_text(encoding='utf-8')))
        except (OSError, ValueError, TypeError, KeyError):
            backup = self._backup()
            try:
                payload = _validate_payload(json.loads(backup.read_text(encoding='utf-8')))
            except (OSError, ValueError, TypeError, KeyError):
                raise ValueError('the local source overlay is unreadable and has no valid backup; '
                                 'fix or move config/sources.local.json') from None
            LOGGER.warning('source_overlay_recovered_from_backup')
            return payload

    def entries(self, *, include_shadowed: bool = False) -> list[RegistryEntry]:
        return self._effective(load_base_sources(self.config_path), self._read_overlay(), include_shadowed)

    def sources(self) -> list[Source]:
        return [entry.source for entry in self.entries()]

    def get(self, source_id: str) -> RegistryEntry | None:
        return next((e for e in self.entries() if e.source.id == source_id), None)

    @staticmethod
    def _effective(base: list[Source], payload: dict, include_shadowed: bool = False) -> list[RegistryEntry]:
        entries = []
        for source in base:
            state = payload['states'].get(source.id) or {}
            if 'enabled' in state and source.disabled_reason not in LOCKED_REASONS:
                if state['enabled'] and (source.enabled or source.disabled_reason in (None, 'owner')):
                    source = replace(source, enabled=True, disabled_reason=None)
                elif not state['enabled'] and source.enabled:
                    source = replace(source, enabled=False, disabled_reason='owner')
            if state.get('archived'):
                source = replace(source, enabled=False, archived=True,
                                 disabled_reason=source.disabled_reason or 'owner')
            entries.append(RegistryEntry(source, 'base'))
        taken_ids = {s.id for s in base}
        taken = {identity(s) for s in base}
        for record in payload['sources']:
            source = source_from_mapping({k: v for k, v in record.items() if k not in ('added_at', 'updated_at')})
            if source.id in taken_ids or identity(source) in taken:
                if include_shadowed:
                    entries.append(RegistryEntry(source, 'shadowed'))
                LOGGER.warning('source_overlay_entry_shadowed', extra={'source_id': source.id})
                continue
            taken_ids.add(source.id)
            taken.add(identity(source))
            entries.append(RegistryEntry(source, 'local'))
        return entries

    # -- writing ---------------------------------------------------------------
    @contextmanager
    def _transaction(self):
        if self.overlay is None:
            raise RegistryError('overlay_disabled')
        with _FileLock(self.overlay.with_name(self.overlay.name + '.lock')):
            payload = self._read_overlay()
            yield payload
            # Validate the complete effective registry before anything is written.
            _validate_payload(payload)
            self._effective(load_base_sources(self.config_path), payload)
            if self.overlay.exists():
                try:
                    current = _validate_payload(json.loads(self.overlay.read_text(encoding='utf-8')))
                    atomic_json(self._backup(), current)
                except (OSError, ValueError, TypeError, KeyError):
                    pass  # an unreadable current file is replaced; the backup stays the last good one
            atomic_json(self.overlay, payload)

    def add(self, source: Source) -> RegistryEntry:
        with self._transaction() as payload:
            effective = self._effective(load_base_sources(self.config_path), payload)
            for entry in effective:
                if entry.source.id == source.id:
                    raise RegistryError('duplicate_id', entry.source.id)
                if identity(entry.source) == identity(source):
                    raise RegistryError('duplicate_source', entry.source.id)
            if len(payload['sources']) >= MAX_LOCAL_SOURCES:
                raise RegistryError('too_many_sources')
            payload['sources'].append(dict(source_to_mapping(source), added_at=_now()))
        return RegistryEntry(source, 'local')

    def set_enabled(self, source_id: str, enabled: bool) -> RegistryEntry:
        return self._change(source_id, 'enable' if enabled else 'disable')

    def set_archived(self, source_id: str, archived: bool) -> RegistryEntry:
        return self._change(source_id, 'archive' if archived else 'restore')

    def _change(self, source_id: str, action: str) -> RegistryEntry:
        with self._transaction() as payload:
            entry = next((e for e in self._effective(load_base_sources(self.config_path), payload)
                          if e.source.id == source_id), None)
            if entry is None:
                raise RegistryError('unknown_source', source_id)
            source = entry.source
            if action == 'enable':
                if source.archived:
                    raise RegistryError('archived', source_id)
                if entry.locked:
                    raise RegistryError('locked', source_id)
                if source.enabled:
                    return entry
            elif action == 'disable' and (source.archived or not source.enabled):
                return entry
            elif action == 'archive' and source.archived:
                return entry
            elif action == 'restore' and not source.archived:
                return entry
            if entry.origin == 'base':
                state = dict(payload['states'].get(source_id) or {})
                if action in ('enable', 'disable'):
                    state['enabled'] = action == 'enable'
                else:
                    state['archived'] = action == 'archive'
                    if action == 'archive' and entry.locked is False:
                        state['enabled'] = False  # a restored source comes back paused
                state['updated_at'] = _now()
                payload['states'][source_id] = state
            else:
                record = next(r for r in payload['sources'] if r.get('id') == source_id)
                if action == 'enable':
                    record.update(enabled=True, updated_at=_now())
                    record.pop('disabled_reason', None)
                elif action == 'disable':
                    record.update(enabled=False, disabled_reason='owner', updated_at=_now())
                elif action == 'archive':
                    record.update(archived=True, enabled=False, updated_at=_now())
                    if record.get('disabled_reason') is None:
                        record['disabled_reason'] = 'owner'
                else:  # restore: back to the list, paused (or still locked); never straight into crawls
                    record.update(archived=False, updated_at=_now())
            result = next(e for e in self._effective(load_base_sources(self.config_path), payload)
                          if e.source.id == source_id)
        return result


def source_to_mapping(source: Source) -> dict:
    record = {'id': source.id, 'publisher_key': source.publisher_key, 'name': source.name,
              'type': source.source_type.value, 'url': source.url, 'enabled': source.enabled,
              'timezone': source.timezone, 'locale': source.locale}
    if source.username:
        record['username'] = source.username
    if source.city_hint:
        record['city_hint'] = source.city_hint
    if source.disabled_reason:
        record['disabled_reason'] = source.disabled_reason
    if source.archived:
        record['archived'] = True
    if source.website is not None:
        w = source.website
        record['website'] = {'adapter': w.adapter, 'detail_path_prefixes': list(w.detail_path_prefixes),
                             'content_selector': w.content_selector, 'exclude_selectors': list(w.exclude_selectors),
                             'drop_query_params': list(w.drop_query_params)}
    return record
