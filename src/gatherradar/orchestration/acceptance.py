"""Owner-side acceptance of ONE fresh run: validate outputs, pack one review bundle.

Reads only local outputs of a run that already happened (its isolated SQLite,
workbook and exports, the run manifest and the append-only raw/evidence
stores). It collects nothing, opens no browser, runs no OCR and uploads
nothing. The bundle excludes the database, cookies, browser profiles, `.env`,
full raw stores, absolute local paths and signed media URLs; original media
files are copied only when the owner asks, and then only a bounded selection
for the tracked cases.
"""
from __future__ import annotations

import json
import shutil
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from ..exports.excel import OVERFLOW, XLSX_CELL_LIMIT, overflow_value
from ..ocr.quality import QUALITY_POLICY, assess_text

REPORT_VERSION = 1
PERSIAN_FONT, LATIN_FONT = 'Vazir', 'Poppins'
# Visible main-sheet columns whose fill rate the owner reviews.
CORE_COLUMNS = ('عنوان', 'تاریخ شمسی شروع', 'ساعت شروع', 'جلسه بعدی', 'مکان', 'منطقه / محله', 'آدرس',
                'شهر', 'مدت', 'هزینه', 'ظرفیت / وضعیت ثبت‌نام', 'برگزارکننده', 'توضیحات / معرفی',
                'ثبت‌نام / خرید', 'منبع اصلی')


def _rows(sheet) -> tuple[list, list[tuple]]:
    values = list(sheet.iter_rows(values_only=True))
    return (list(values[0]) if values else []), values[1:]


def validate_workbook(path: Path, document: dict) -> dict:
    """Reopen the workbook and check it against the persisted run document."""
    from openpyxl import load_workbook
    result: dict = {'exists': path.exists(), 'checks': {}}
    if not path.exists():
        result['ok'] = False
        return result
    book = load_workbook(path)
    try:
        run_id = document['run']['run_id']
        found = {'main': set(), 'schedule_review': set()}
        sheets, fills, longest, overflow_refs, overflow_bad = {}, Counter(), 0, 0, []
        fonts, frozen = Counter(), {}
        for sheet in book.worksheets:
            headers, rows = _rows(sheet)
            for row in rows:
                for header, value in zip(headers, row):
                    if isinstance(value, str):
                        longest = max(longest, len(value))
                        if value.startswith('[[gatherradar-overflow') and 'event_id' in headers:
                            overflow_refs += 1
                            try:
                                overflow_value(book, sheet.title, row[headers.index('event_id')], header)
                            except Exception:  # an altered or incomplete stored value
                                overflow_bad.append(f'{sheet.title}/{header}')
            if 'event_id' not in headers or 'run_id' not in headers:
                continue
            mine = [r for r in rows if r[headers.index('run_id')] == run_id]
            if not mine:
                continue
            kind = 'main' if sheet.title.startswith('رویدادها') else 'schedule_review'
            sheets[kind] = sheet.title
            frozen[kind] = sheet.freeze_panes
            found[kind] |= {r[headers.index('event_id')] for r in mine}
            for cell in sheet[1] + (sheet[2] if sheet.max_row > 1 else ()):
                fonts[cell.font.name] += 1
            if kind == 'main':
                for column in CORE_COLUMNS:
                    if column in headers:
                        fills[column] = sum(1 for r in mine if r[headers.index(column)] not in (None, ''))
        expected = {'main': {e['event_id'] for e in document['events']},
                    'schedule_review': {e['event_id'] for e in document.get('schedule_review', ())}}
        checks = {
            'main_rows_match_run': found['main'] == expected['main'],
            'schedule_review_rows_match_run': found['schedule_review'] == expected['schedule_review'],
            'no_cell_over_xlsx_limit': longest <= XLSX_CELL_LIMIT,
            'overflow_values_intact': not overflow_bad,
            'header_row_only_frozen': all(value == 'A2' for value in frozen.values()),
            'fonts_vazir_poppins_only': set(fonts) <= {PERSIAN_FONT, LATIN_FONT},
        }
        result.update(
            ok=all(checks.values()), checks=checks, sheets=sheets, sheet_names=book.sheetnames,
            main_rows=len(found['main']), schedule_review_rows=len(found['schedule_review']),
            overflow_references=overflow_refs, overflow_hidden=(OVERFLOW not in book.sheetnames
                                                                or book[OVERFLOW].sheet_state == 'hidden'),
            core_field_fill={column: f'{count}/{len(found["main"])}' for column, count in fills.items()},
            overflow_problems=overflow_bad, fonts=dict(fonts))
        return result
    finally:
        book.close()


def _matches(record: dict, locator: str) -> bool:
    return any(locator in (url or '') for url in (record.get('canonical_source_url'), *record.get('evidence_urls', ())))


def _expect(record: dict, expect: dict) -> list[str]:
    """Human-readable failed expectations for one matched record."""
    failed = []
    reasons = set(record.get('readiness_reasons') or ())
    for key, wanted in expect.items():
        if key == 'occurrences_min':
            if len(record.get('occurrences') or ()) < wanted:
                failed.append(f'occurrences < {wanted}')
        elif key == 'reason':
            if wanted not in reasons:
                failed.append(f'missing reason {wanted}')
        elif key == 'no_reason':
            if wanted in reasons:
                failed.append(f'unexpected reason {wanted}')
        elif key == 'venue_present':
            if not record.get('venue_name'):
                failed.append('venue missing')
        elif key == 'no_start_time':
            starts = {record.get('start_time'), *(o.get('start_time') for o in record.get('occurrences') or ())}
            if wanted in starts:
                failed.append(f'start time {wanted} present')
        elif record.get(key) != wanted:
            failed.append(f'{key}={record.get(key)!r} (expected {wanted!r})')
    return failed


def case_results(full: dict, manifest: dict, cases: list[dict]) -> list[dict]:
    """Match each tracked case to this run: Event outcome, exclusion, or absence."""
    dispositions = {d['event_id']: d for d in full.get('event_dispositions', ())}
    records = [*full['events'], *full.get('schedule_review', ())]
    unique = {r['event_id']: r for r in records}.values()
    observed = {item for source in manifest.get('sources', ()) for item in source.get('observed_item_ids', ())}
    investigations = [i for funnel in manifest.get('source_funnel', ()) for i in funnel.get('investigations', ())]
    results = []
    for case in cases:
        entries = []
        for locator in case.get('locators', ()):
            matched = [r for r in unique if _matches(r, locator)]
            if matched:
                for record in matched:
                    disposition = dispositions.get(record['event_id'], {})
                    failed = _expect(record, case.get('expect', {}))
                    entries.append({
                        'locator': locator, 'outcome': 'event', 'event_id': record['event_id'],
                        'title': record.get('title'), 'disposition': disposition.get('disposition'),
                        'schedule_reason': disposition.get('reason'), 'readiness': record.get('data_readiness'),
                        'readiness_explanation': record.get('readiness_explanation'),
                        'fields': {k: record.get(k) for k in (
                            'venue_name', 'area_text', 'location_context', 'address', 'city', 'duration_text',
                            'price_text', 'availability_text', 'start_date', 'start_time', 'end_date',
                            'next_session_date', 'next_session_start_time', 'remaining_session_count')},
                        'occurrences': len(record.get('occurrences') or ()),
                        'status': 'NEEDS_OWNER_REVIEW' if case.get('media') and not failed
                                  else ('CHECK' if failed else 'PASS'),
                        'failed_expectations': failed})
                continue
            notes = [i['reason'] for i in investigations if locator.strip('/').split('/')[-1] in i.get('raw_item_id', '')]
            seen = any(locator.strip('/').split('/')[-1] in item for item in observed)
            entries.append({'locator': locator,
                            'outcome': 'not_an_event_in_run' if seen else 'not_in_run',
                            'investigations': notes,
                            'status': 'NEEDS_OWNER_REVIEW' if seen else 'NOT_IN_RUN'})
        for source_id in case.get('sources', ()):
            funnel = next((f for f in manifest.get('source_funnel', ()) if f.get('source_id') == source_id), {})
            entries.append({'source_id': source_id, 'outcome': 'source_funnel',
                            'funnel': {k: funnel.get(k) for k in (
                                'raw_items_selected', 'event_candidates', 'canonical_events',
                                'unclassified_items', 'confirmed_non_event_items', 'actionable_events',
                                'schedule_review_events')},
                            'investigations': [i.get('reason') for i in funnel.get('investigations', ())],
                            'status': 'NEEDS_OWNER_REVIEW'})
        results.append({'id': case['id'], 'summary': case.get('summary'), 'entries': entries})
    return results


def evidence_index(data_dir: Path, config_path: Path, manifest: dict, locators: list[str],
                   media_dir: Path | None = None, max_media: int = 40) -> list[dict]:
    """Stored caption and OCR evidence for tracked media items, by recorded IDs only.

    With `media_dir`, selected images are copied round-robin across items (one per
    item per pass) so a long carousel never uses up the whole `max_media` budget.
    """
    from ..config import load_sources
    from ..domain import SourceType
    from ..grouping.selection import select_semantic_evidence
    from ..storage import JsonlEvidenceStore, JsonlRawItemStore
    from .collection_run import instagram_output_path
    from .evidence_paths import instagram_evidence_output_path
    sources = {s.id: s for s in load_sources(config_path)}
    pending: list[list[tuple[dict, Path]]] = []
    index = []
    keys = [locator.strip('/').split('/')[-1] for locator in locators]
    for report in manifest.get('sources', ()):
        source = sources.get(report.get('source_id'))
        if source is None or source.source_type is not SourceType.INSTAGRAM:
            continue
        wanted = [item for item in report.get('observed_item_ids', ()) if any(item.endswith(':' + k) for k in keys)]
        if not wanted:
            continue
        raw = {i.id: i for i in JsonlRawItemStore(instagram_output_path(source, data_dir)).read_latest_items().items}
        history = JsonlEvidenceStore(instagram_evidence_output_path(source, data_dir)).read().fragments
        for item_id in wanted:
            item = raw.get(item_id)
            if item is None:
                index.append({'raw_item_id': item_id, 'status': 'EVIDENCE_GAP', 'reason': 'raw item not stored'})
                continue
            chosen = {f.fragment_id for f in select_semantic_evidence(item, history).fragments}
            readings, media = [], []
            for fragment in history:
                if fragment.raw_item_id != item_id or fragment.kind.value == 'caption':
                    continue
                quality = assess_text(fragment.text)
                asset = Path(fragment.local_asset_path) if fragment.local_asset_path else None
                entry = {'kind': fragment.kind.value, 'slide_index': fragment.slide_index,
                         'frame_timestamp_ms': fragment.frame_timestamp_ms, 'engine': fragment.extraction_engine,
                         'engine_version': fragment.extraction_version, 'asset_hash': fragment.asset_hash,
                         'asset_file': asset.name if asset else None,
                         'asset_present': bool(asset and asset.exists()), 'selected': fragment.fragment_id in chosen,
                         'failure': fragment.failure_reason, 'quality': quality.reason,
                         'text_excerpt': (fragment.text or '')[:300]}
                if entry['selected'] and asset and asset.exists():
                    media.append((entry, asset))
                readings.append(entry)
            pending.append(media)
            # The caption is public post text the extractor saw alongside the media.
            index.append({'raw_item_id': item_id, 'source_id': source.id,
                          'status': 'READINGS_STORED' if readings else 'EVIDENCE_GAP',
                          'reason': None if readings else 'no stored media readings for this item',
                          'caption_excerpt': (item.raw_text or '')[:2000], 'readings': readings})
    copied, position = 0, 0
    while media_dir is not None and copied < max_media and any(position < len(m) for m in pending):
        for media in pending:
            if position < len(media) and copied < max_media:
                entry, asset = media[position]
                media_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(asset, media_dir / asset.name)
                entry['bundled_media'] = f'media/{asset.name}'
                copied += 1
        position += 1
    for key in keys:
        if not any(entry['raw_item_id'].endswith(':' + key) for entry in index):
            index.append({'raw_item_id': key, 'status': 'EVIDENCE_GAP',
                          'reason': 'not among the latest observed items of this run'})
    return index


def build_bundle(run_dir: Path, *, data_dir: Path = Path('data'), config_path: Path = Path('config/sources.yaml'),
                 cases_path: Path = Path('scripts/acceptance_cases.json'), test_log: Path | None = None,
                 include_media: bool = False, max_media: int = 40,
                 extra_files: tuple[Path, ...] = ()) -> tuple[Path, dict]:
    """Validate one run directory and write `review-bundle/` plus its zip."""
    from ..storage.sqlite_repository import SqliteCanonicalRepository
    run_dir = Path(run_dir)
    database, workbook, exports = run_dir / 'state.sqlite3', run_dir / 'GatherRadar.xlsx', run_dir / 'exports'
    with SqliteCanonicalRepository(database) as repository:
        document = repository.load('latest')
        full = repository.load('latest', include_filtered=True)
    run = document['run']
    manifest_path = Path(data_dir) / 'runs' / f'{run["run_id"]}.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
    cases = json.loads(Path(cases_path).read_text(encoding='utf-8'))['cases']
    bundle = run_dir / 'review-bundle'
    if bundle.exists():
        shutil.rmtree(bundle)
    bundle.mkdir(parents=True)
    media_locators = [loc for case in cases if case.get('media') for loc in case.get('locators', ())]
    # Every item this run could not admit (title or evidence investigations) is
    # indexed too, so exclusions outside the tracked list are still auditable.
    media_locators += [i['raw_item_id'].rsplit(':', 1)[-1] for funnel in manifest.get('source_funnel', ())
                       for i in funnel.get('investigations', ())
                       if i.get('reason', '').startswith(('title_resolution_failed', 'needs_evidence'))]
    media_locators = list(dict.fromkeys(media_locators))
    report = {
        'report': 'gatherradar-final-excel-acceptance', 'version': REPORT_VERSION,
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'run': {k: run.get(k) for k in ('run_id', 'status', 'started_at', 'finished_at', 'days', 'review_timezone',
                                         'event_count', 'canonical_event_count', 'undated', 'filtered',
                                         'disposition_counts', 'data_readiness_counts')},
        'collection': [{k: s.get(k) for k in ('source_id', 'status', 'channel_status', 'failures',
                                               'media_diagnostics')} | {'observed': len(s.get('observed_item_ids', ()))}
                       for s in manifest.get('sources', ())],
        'admission': {k: manifest.get(k) for k in ('discovered_event_count', 'excluded_missing_title',
                                                     'excluded_missing_title_by_source', 'title_exclusion_reasons')},
        'workbook': validate_workbook(workbook, document),
        'exports': {name: (exports / 'latest' / name).exists() for name in ('review.json', 'events.csv')},
        'cases': case_results(full, manifest, cases),
        'ocr_quality_policy': QUALITY_POLICY,
        'evidence_index': evidence_index(Path(data_dir), Path(config_path), manifest, media_locators,
                                         bundle / 'media' if include_media else None, max_media),
        'limits': ['Values are this run\'s stored facts; uninspected image content is not claimed.',
                   'Raw and evidence stores are shared append-only local history, not isolated per run.'],
    }
    (bundle / 'acceptance-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if workbook.exists():
        shutil.copy2(workbook, bundle / 'GatherRadar.xlsx')
    if (exports / 'latest' / 'review.json').exists():
        shutil.copy2(exports / 'latest' / 'review.json', bundle / 'review.json')
    if manifest_path.exists():
        shutil.copy2(manifest_path, bundle / manifest_path.name)
    if test_log is not None and Path(test_log).exists():
        shutil.copy2(test_log, bundle / 'test-summary.txt')
    for extra in map(Path, extra_files):
        if extra.is_file() and extra.suffix.lower() in ('.txt', '.json', '.log'):
            shutil.copy2(extra, bundle / extra.name)
    archive = run_dir / 'GatherRadar-review-bundle.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as handle:
        for path in sorted(bundle.rglob('*')):
            if path.is_file():
                handle.write(path, path.relative_to(bundle).as_posix())
    return archive, report


__all__ = ['build_bundle', 'case_results', 'evidence_index', 'validate_workbook']
