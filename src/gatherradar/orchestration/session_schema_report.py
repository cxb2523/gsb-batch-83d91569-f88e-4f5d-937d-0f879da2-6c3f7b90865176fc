"""Read-only, value-free report of retained Jabama embedded-session evidence.

Reads the local website raw store (and optionally browser-saved public detail
pages) and reports only structure: source IDs, public Event IDs, observation IDs,
diagnostics, unexpected property names, value types, string forms, array lengths
and nullability. It opens no browser, contacts no source, and writes nothing but
the optional report file.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from ..collectors.websites.html import parse_html
from ..collectors.websites.jabama_relationships import relationship_report
from ..collectors.websites.jabama_sessions import describe_embedded_sessions
from ..storage import JsonlRawItemStore

REPORT_VERSION = 1
MAX_HTML_BYTES = 5_000_000
_SAFE = re.compile(r'[A-Za-z0-9_.:/-]{1,120}')


def _safe(value: object) -> str | None:
    return value if isinstance(value, str) and _SAFE.fullmatch(value) else None


def _codes(values: object) -> list[str]:
    return [v for v in values if _safe(v)] if isinstance(values, list) else []


def observation_report(data_dir: str | Path = 'data') -> list[dict]:
    """One entry per latest retained Jabama website observation."""
    rows = []
    for path in sorted((Path(data_dir) / 'raw' / 'website').glob('*.jsonl')):
        read = JsonlRawItemStore(path).read_latest_items()
        for item in read.items:
            meta = item.raw_metadata or {}
            if not str(meta.get('adapter', '')).startswith('jabama') and 'source_session_schema' not in meta:
                continue
            sessions = meta.get('source_sessions') if isinstance(meta.get('source_sessions'), list) else []
            statuses: dict[str, int] = {}
            for session in sessions:
                status = (session.get('schema_status') if isinstance(session, dict) else None) or 'documented'
                statuses[status] = statuses.get(status, 0) + 1
            shapes = meta.get('source_session_drift_shapes')
            rows.append({
                'source_id': _safe(item.source_id), 'public_event_id': _safe(item.external_id),
                'observation_id': _safe(item.id), 'content_hash_prefix': item.content_hash[:16],
                'captured_at': item.captured_at.isoformat(), 'adapter': _safe(meta.get('adapter')),
                'session_schema': _safe(meta.get('source_session_schema')),
                'session_diagnostics': _codes(meta.get('source_session_diagnostics')),
                'unexpected_session_properties': _codes(meta.get('source_session_drift_keys')),
                'stored_sessions': len(sessions), 'stored_session_status': statuses,
                # Recorded by collectors from this version on; absent in older observations.
                'drift_shapes': shapes if isinstance(shapes, list) else None,
                'malformed_lines_in_file': len(read.malformed),
            })
    return rows


def html_report(paths: list[str | Path]) -> list[dict]:
    """Structure of browser-saved public detail pages (file name only, no path)."""
    rows = []
    for path in map(Path, paths):
        entry: dict = {'file': path.name}
        try:
            if path.stat().st_size > MAX_HTML_BYTES:
                entry['error'] = 'file_too_large'
            else:
                entry.update(describe_embedded_sessions(parse_html(path.read_text(encoding='utf-8', errors='replace'))))
        except OSError:
            entry['error'] = 'unreadable_file'
        rows.append(entry)
    return rows


def build_report(data_dir: str | Path = 'data', html: list[str | Path] = ()) -> dict:
    observations = observation_report(data_dir)
    properties: dict[str, int] = {}
    diagnostics: dict[str, int] = {}
    for row in observations:
        for name in row['unexpected_session_properties']:
            properties[name] = properties.get(name, 0) + 1
        for code in row['session_diagnostics']:
            diagnostics[code] = diagnostics.get(code, 0) + 1
    return {
        'report': 'gatherradar-jabama-session-schema', 'version': REPORT_VERSION,
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'privacy': 'Structure only: no page text, prices, identifiers inside sessions, tokens or URLs.',
        'summary': {'observations': len(observations), 'unexpected_properties': properties,
                    'diagnostics': diagnostics,
                    'observations_with_shapes': sum(1 for r in observations if r['drift_shapes'])},
        'observations': observations,
        'saved_pages': html_report(list(html)),
    }


def build_relationship_report(paths: list[str | Path]) -> dict:
    """Booleans and counts per saved page, identified only by its position."""
    pages = []
    summary: dict = {}
    for position, path in enumerate(map(Path, paths), start=1):
        entry: dict = {'page': position}
        try:
            if path.stat().st_size > MAX_HTML_BYTES:
                entry['error'] = 'file_too_large'
            else:
                entry.update(relationship_report(parse_html(path.read_text(encoding='utf-8', errors='replace'))))
        except OSError:
            entry['error'] = 'unreadable_file'
        pages.append(entry)
        for key, value in entry.items():
            if key == 'page':
                continue
            if isinstance(value, int) and not isinstance(value, bool):
                summary[key] = summary.get(key, 0) + value
            elif isinstance(value, dict) and all(isinstance(v, int) for v in value.values()):
                bucket = summary.setdefault(key, {})
                for name, count in value.items():
                    bucket[name] = bucket.get(name, 0) + count
    return {
        'report': 'gatherradar-jabama-timeslot-relationships', 'version': REPORT_VERSION,
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'privacy': 'Booleans and counts only: no file names, identifiers, timestamps, prices or text.',
        'summary': dict(sorted(summary.items())), 'pages': pages,
    }


__all__ = ['build_relationship_report', 'build_report', 'html_report', 'observation_report']
