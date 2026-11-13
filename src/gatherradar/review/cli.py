"""Local command parsing and output only; the service owns pipeline behavior."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from uuid import uuid4

from .models import ReviewError


def selection_arguments(parser: argparse.ArgumentParser) -> None:
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--source', action='append', dest='sources')
    selection.add_argument('--all-enabled', action='store_true')
    parser.add_argument('--config', default='config/sources.yaml')
    parser.add_argument('--limit', type=int, default=5)
    parser.add_argument('--days', type=int, default=14)
    parser.add_argument('--review-timezone', default='Asia/Tehran')
    parser.add_argument('--skip-instagram-evidence', action='store_true')
    parser.add_argument('--run-id')


def add_commands(subcommands: object) -> None:
    refresh = subcommands.add_parser('refresh', help='Collect and persist locally, then export review files. No Google.')
    selection_arguments(refresh)
    refresh.add_argument('--stored', action='store_true', help='Analyze local observations only; no collection, browser or OCR.')
    export = subcommands.add_parser('export', help='Regenerate artifacts offline from SQLite only.')
    export.add_argument('format', nargs='?', choices=('all','xlsx','csv','json','gemini'), default='all')
    export.add_argument('--run', default='latest')
    review = subcommands.add_parser('review', help='Offline review-state import.')
    review.add_argument('review_command', choices=('import',))
    status = subcommands.add_parser('status', help='Local persistence paths and run state; no network.')
    for parser in (refresh, export, review, status):
        parser.add_argument('--data-dir', default='data')
        parser.add_argument('--db', help='Default: <data-dir>/state/gatherradar.sqlite3')
        parser.add_argument('--workbook', help='Default: <data-dir>/review/GatherRadar.xlsx')
        parser.add_argument('--export-dir', help='Default: <data-dir>/exports')


def _print_import(result) -> None:
    print(f'Review import: imported={result.imported}; skipped={result.skipped}; malformed={result.malformed}; conflicts={result.conflicts}')


CHANNEL_LABELS = {'website_listing': 'Website', 'instagram_profile': 'Instagram', 'linked_page': 'Linked pages'}
FIELD_LABELS = {'description_text': 'full description', 'address': 'exact address', 'area_text': 'area',
                'duration_text': 'duration', 'organizer_name': 'organizer', 'availability_text': 'availability',
                'registration_url': 'registration metadata', 'source_category_text': 'source category'}


def print_publishers(result, names: dict[str, str]) -> None:
    """Publisher coverage first; channel health is reported separately."""
    for coverage in result.publishers:
        print(names.get(coverage.publisher_key, coverage.publisher_key))
        for channel in (c for c in result.channels if c.publisher_key == coverage.publisher_key):
            label = CHANNEL_LABELS.get(channel.strategy, channel.strategy)
            if channel.strategy == 'stored':
                label = channel.channel.capitalize() + ' [stored, offline]'
            detail = f' — {channel.observed} observed' if channel.observed else ''
            print(f'  {label} ({channel.source_id}): {channel.status.value}{detail}')
        state = 'covered' if coverage.covered else 'NOT covered'
        via = f" through {', '.join(coverage.covered_by)}" if coverage.covered_by else ''
        print(f'  publisher_coverage: {state}{via}; all channels healthy: {coverage.all_channels_healthy}')
        if coverage.covered and coverage.potentially_unavailable_fields:
            print('  Coverage may be reduced; potentially unavailable fields: '
                  + ', '.join(FIELD_LABELS.get(f, f) for f in coverage.potentially_unavailable_fields))
    for notice in result.policy_notices:
        if notice.state == 'now_allowed':
            print(f'Policy notice: {notice.source_id} robots now permits GatherRadar; '
                  'set enabled: true in the source registry to resume it (not changed automatically).')
        elif notice.state == 'check_failed':
            print(f'Policy notice: {notice.source_id} policy re-check failed ({notice.detail}); state unchanged.')
    covered = sum(c.covered for c in result.publishers)
    print(f'Publisher coverage: {covered}/{len(result.publishers)} publishers represented')


def run(args: argparse.Namespace) -> int:
    from ..storage.sqlite_repository import SqliteCanonicalRepository
    from .workspace import local_workspace
    root = Path(args.data_dir)
    database = Path(args.db) if args.db else root / 'state' / 'gatherradar.sqlite3'
    workbook = Path(args.workbook) if args.workbook else root / 'review' / 'GatherRadar.xlsx'
    exports = Path(args.export_dir) if args.export_dir else root / 'exports'
    try:
        with SqliteCanonicalRepository(database) as repository:
            if args.command == 'status':
                print(json.dumps(dict(repository.status(), workbook=str(workbook), exports=str(exports),
                    google='optional; use sheets status explicitly to contact Google'), ensure_ascii=False, indent=2))
                return 0
            if args.command == 'review':
                from ..exports.excel import ExcelReviewImporter
                if not workbook.exists():
                    raise ReviewError('Review workbook does not exist; choose --workbook or generate an export first.')
                with repository.state.lock():
                    imported = ExcelReviewImporter(workbook, repository).import_reviews()
                _print_import(imported)
                return int(bool(imported.malformed or imported.conflicts))
            kind = args.format if args.command == 'export' else 'all'
            workspace = local_workspace(repository, workbook, exports, kind)
            if args.command == 'export':
                with repository.state.lock():
                    # CSV/JSON/Gemini have no dependency on the XLSX library or file.
                    if kind in ('all','xlsx'):
                        _print_import(workspace.import_reviews())
                    paths, failures = workspace.export(args.run)
                for path in paths:
                    print(path)
                for failure in failures:
                    print(f'Export error: {failure}', file=sys.stderr)
                print_eligibility(repository.load(args.run)['run'])
                return int(bool(failures))
            from ..orchestration.refresh import application_refresh_service
            run_id = args.run_id or uuid4().hex
            print(f'Run id: {run_id}', flush=True)
            from ..config import load_sources
            result = application_refresh_service(repository, workspace).run(tuple(args.sources or ()), all_enabled=args.all_enabled,
                config_path=args.config, data_dir=root, limit=args.limit, days=args.days,
                review_timezone=args.review_timezone, skip_instagram_evidence=args.skip_instagram_evidence,
                collect=not args.stored, run_id=run_id)
            snapshot = result.snapshot
            print(f'Status: {snapshot.status}; events={snapshot.events}; places={snapshot.places}; duplicates={snapshot.duplicates}')
            print(f'Filtered={snapshot.filtered}; undated={snapshot.undated}; already persisted={snapshot.already_synced}')
            if result.import_summary is not None:
                _print_import(result.import_summary)
            for source in result.sources:
                print(f'{source.source_id}: {source.status}; observed={len(source.observed_item_ids)}; failures={",".join(source.failures)}')
            print_publishers(result, {s.publisher_key: s.name.rsplit(' ', 1)[0] for s in load_sources(args.config)})
            print(f'Canonical Events: {snapshot.events + snapshot.filtered}; Displayed Events: {snapshot.events}')
            run_summary = repository.load(run_id)['run']
            print_eligibility(run_summary)
            counts = run_summary.get('data_readiness_counts', {})
            print('Data readiness: ' + '; '.join(f'{name}={counts.get(name, 0)}' for name in (
                'ready_for_review', 'needs_enrichment', 'needs_schedule_review', 'source_unavailable')))
            # Collection, persistence and each export are separate outcomes; a
            # workbook path is printed only when the workbook was written.
            print(f'Collection: {snapshot.status}')
            print(f'Persistence: committed (run {run_id}); Database: {database}')
            xlsx_failed = any(e.startswith(('ExcelReviewExporter', 'XLSX')) for e in result.export_failures)
            other_failed = [e for e in result.export_failures if not e.startswith(('ExcelReviewExporter', 'XLSX'))]
            if xlsx_failed:
                print('Workbook: NOT written (see Export error). Stored facts are intact; recover offline with:')
                print(f'  python -m gatherradar export all --run {run_id} --db "{database}" '
                      f'--workbook "{workbook}" --export-dir "{exports}"')
            else:
                print(f'Workbook: {workbook}')
            print(f'Exports: {exports}' + (' (with errors)' if other_failed else ''))
            print(f'Gemini: {exports / "gemini/latest"}')
            for error in result.export_failures:
                print(f'Export error (canonical state committed): {error}', file=sys.stderr)
            return int(snapshot.status != 'success' or bool(result.export_failures))
    except (ReviewError, ValueError, OSError, sqlite3.Error) as exc:
        message = str(exc) if isinstance(exc, ReviewError) else 'Local operation failed. Check configuration, database and output paths; no raw exception was logged.'
        print(f'error: {message}', file=sys.stderr)
        return 1


def print_eligibility(run: dict) -> None:
    if run.get('disposition_counts'):
        print('Schedule dispositions: ' + '; '.join(
            f'{name}={count}' for name, count in run['disposition_counts'].items()))
    print(f"Event admission: discovered={run.get('discovered_event_count', 0)}; "
          f"excluded_missing_title={run.get('excluded_missing_title', 0)}; "
          f"canonical persisted={run.get('canonical_event_count', 0)}; "
          f"filtered={run.get('filtered', 0)}; displayed={run.get('event_count', 0)}")
    for source, count in sorted(run.get('excluded_missing_title_by_source', {}).items()):
        print(f'  {source}: excluded_missing_title={count}')
