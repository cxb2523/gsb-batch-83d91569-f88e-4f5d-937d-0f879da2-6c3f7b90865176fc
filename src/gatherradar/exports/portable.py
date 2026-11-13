"""Standard-library CSV/JSON exporters; intentionally independent of openpyxl."""
from __future__ import annotations

import csv
import io
import re
from dataclasses import fields
from pathlib import Path

from ..domain import Event, PlaceCandidate
from ..review.io import atomic_bytes
from ..review.records import dumps
from ..review.relevance import relevant_document

REVIEW_FIELDS = ('review_decision', 'review_notes', 'review_updated_at')
EVENT_FIELDS = tuple(f.name for f in fields(Event)) + ('jalali_start_date', 'jalali_end_date', 'weekday', 'data_quality') + REVIEW_FIELDS + (
    'data_readiness', 'readiness_label', 'readiness_reasons', 'readiness_explanation', 'quality_indicators')
PLACE_FIELDS = tuple(f.name for f in fields(PlaceCandidate)) + ('source_id',) + REVIEW_FIELDS
DUPLICATE_FIELDS = ('pair_key', 'event_id_a', 'event_id_b', 'title_a', 'title_b', 'jalali_date_a',
    'jalali_date_b', 'source_urls_a', 'source_urls_b', 'reason', 'reason_codes', 'first_seen_run', 'last_seen_run') + REVIEW_FIELDS
EVENT_FIELDS += ('schedule_disposition', 'schedule_reason')
EVENT_FIELDS += ('next_session_date', 'next_session_start_time', 'next_session_end_time', 'remaining_session_count')
TABLES = (('events', EVENT_FIELDS), ('schedule_review', EVENT_FIELDS),
          ('places', PLACE_FIELDS), ('possible_duplicates', DUPLICATE_FIELDS))


def directories(root: Path, run_id: str) -> tuple[Path, Path]:
    if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', run_id):
        raise ValueError('Invalid export run ID')
    return root / 'runs' / run_id, root / 'latest'


def csv_cell(value: object) -> str:
    if value is None:
        return ''
    text = dumps(value) if isinstance(value, (list, dict)) else str(value)
    # Leading whitespace/control characters must not conceal a formula prefix.
    if text.lstrip('\ufeff \t\r\n').startswith(('=', '+', '-', '@')) or text.startswith(('\t', '\r', '\n')):
        return "'" + text
    return text


def csv_bytes(rows: list[dict], headers: tuple[str, ...]) -> bytes:
    buffer = io.StringIO(newline='')
    writer = csv.writer(buffer, lineterminator='\n')
    writer.writerow(headers)
    for row in rows:
        writer.writerow([csv_cell(row.get(key)) for key in headers])
    return buffer.getvalue().encode('utf-8-sig')


def portable_files(document: dict) -> dict[str, bytes]:
    document = relevant_document(document)
    result = {name + '.csv': csv_bytes(document[name], headers) for name, headers in TABLES}
    result['review.json'] = (dumps(document) + '\n').encode('utf-8')
    return result


class CsvReviewExporter:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def export(self, document: dict) -> tuple[Path, ...]:
        document = relevant_document(document)
        paths = []
        for directory in directories(self.root, document['run']['run_id']):
            for name, headers in TABLES:
                path = directory / (name + '.csv')
                atomic_bytes(path, csv_bytes(document[name], headers))
                paths.append(path)
        return tuple(paths)


class JsonReviewExporter:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def export(self, document: dict) -> tuple[Path, ...]:
        document = relevant_document(document)
        paths = []
        content = (dumps(document) + '\n').encode('utf-8')
        for directory in directories(self.root, document['run']['run_id']):
            path = directory / 'review.json'
            atomic_bytes(path, content)
            paths.append(path)
        return tuple(paths)
