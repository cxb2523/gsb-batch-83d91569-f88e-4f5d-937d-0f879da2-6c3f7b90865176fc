"""CLI wiring only; refresh behavior belongs to the application service."""
from __future__ import annotations

import argparse
import os
import sys
from uuid import uuid4

from .auth import authenticate, build_client, token_path
from .client import SheetsError
from .repository import SheetRepository
from .state import RuntimeState


def add_commands(subcommands: object, auth_kinds: object) -> None:
    google = auth_kinds.add_parser('google', help='Authorize personal Google Desktop OAuth.')
    google.add_argument('--credentials', required=True, help='Local Desktop OAuth JSON path; never paste its contents.')
    google.add_argument('--data-dir', default='data')
    sheets = subcommands.add_parser('sheets', help='Google Sheets workbook and stored-data review snapshots.')
    commands = sheets.add_subparsers(dest='sheets_command', required=True)
    setup = commands.add_parser('setup', help='Create once or validate the configured workbook.')
    setup.add_argument('--new', action='store_true', help='Deliberately create a separate workbook; preserve the old one.')
    setup.add_argument('--title', default='GatherRadar')
    status = commands.add_parser('status', help='Check Google authentication, reachability and schema.')
    sync = commands.add_parser('sync', help='Analyze stored data and sync; does not recollect or run OCR.')
    export = commands.add_parser('export', help='Publish a persisted SQLite run to Google; no collection or analysis.')
    export.add_argument('--run', default='latest')
    export.add_argument('--db')
    refresh = commands.add_parser('refresh', help='Optional Google workflow: collect and publish directly to Sheets.')
    for parser in (setup, status, sync, refresh, export):
        parser.add_argument('--data-dir', default='data')
        parser.add_argument('--spreadsheet-id', help='Override GATHERRADAR_SPREADSHEET_ID / local state.')
    for parser in (sync, refresh):
        selection = parser.add_mutually_exclusive_group(required=True)
        selection.add_argument('--source', action='append', dest='sources')
        selection.add_argument('--all-enabled', action='store_true')
        parser.add_argument('--config', default='config/sources.yaml')
        parser.add_argument('--limit', type=int, default=5, help='Maximum raw items per source, 1–30.')
        parser.add_argument('--days', type=int, default=14, help='Inclusive review horizon, 1–90 days.')
        parser.add_argument('--review-timezone', default='Asia/Tehran')
        parser.add_argument('--skip-instagram-evidence', action='store_true', help='Caption-only Instagram analysis; skip capture/OCR during refresh.')
        parser.add_argument('--run-id', help='Reuse a logical run ID for safe retry; completed runs report already synced.')


def run(args: argparse.Namespace) -> int:
    try:
        if args.command == 'auth':
            authenticate(args.credentials, data_dir=args.data_dir)
            print('Google authorization saved locally. No credential values were logged.')
            return 0
        state = RuntimeState(args.data_dir)
        override = args.spreadsheet_id or os.environ.get('GATHERRADAR_SPREADSHEET_ID')
        configured = bool(override or state.read().get('spreadsheet_id'))
        status = args.command == 'sheets' and args.sheets_command == 'status'
        if status:
            print(f'Google token present: {token_path(args.data_dir).exists()}')
            print(f'Workbook configured: {configured}')
        client = build_client(data_dir=args.data_dir)
        if status:
            print('Authenticated: yes')
        repo = SheetRepository(client, state, spreadsheet_id=override)
        if args.command == 'sheets' and args.sheets_command == 'setup':
            with state.lock():
                print(repo.setup(title=args.title, new=args.new))
            return 0
        if status:
            repo.validate()
            print('Workbook reachable: yes\nSchema compatible: yes')
            return 0
        if args.sheets_command == 'export':
            from pathlib import Path
            from ..storage.sqlite_repository import SqliteCanonicalRepository
            from .exporter import publish_persisted
            with SqliteCanonicalRepository(args.db or Path(args.data_dir) / 'state/gatherradar.sqlite3') as local:
                snapshot = publish_persisted(local, repo, args.run)
            print(f'Run id: {snapshot.run_id}\nStatus: {snapshot.status}\n{snapshot.spreadsheet_url}')
            return 0 if snapshot.status == 'success' else 1
        from ..orchestration.refresh import RefreshService
        run_id = args.run_id or uuid4().hex
        print(f'Run id: {run_id}', flush=True)
        result = RefreshService(repo).run(tuple(args.sources or ()), all_enabled=args.all_enabled,
            config_path=args.config, data_dir=args.data_dir, limit=args.limit, days=args.days,
            review_timezone=args.review_timezone, skip_instagram_evidence=args.skip_instagram_evidence,
            collect=args.sheets_command == 'refresh', run_id=run_id)
        snapshot = result.snapshot
        print(f'Run id: {snapshot.run_id}\nStatus: {snapshot.status}')
        if snapshot.already_synced:
            print('already synced')
        for source in result.sources:
            print(f'{source.source_id}: {source.status}; observed={len(source.observed_item_ids)}')
            for error in source.failures:
                print(f'  {error}')
        print(f'Events: {snapshot.events}\nPlaces: {snapshot.places}\nPossible duplicates: {snapshot.duplicates}')
        print(f'Filtered expired/out-of-window: {snapshot.filtered}\nUndated: {snapshot.undated}')
        print(f'Event tab: {snapshot.event_tab}\nPlace tab: {snapshot.place_tab}\n{snapshot.spreadsheet_url}')
        return 0 if snapshot.status == 'success' else 1
    except ImportError:
        print('error: Optional Google libraries are missing. Install with: python -m pip install -e ".[google-sheets]"', file=sys.stderr)
        return 1
    except (SheetsError, ValueError, OSError) as exc:
        message = str(exc) if isinstance(exc, SheetsError) else 'Invalid configuration, selection, runtime path or review options.'
        print(f'error: {message}', file=sys.stderr)
        return 1
    except Exception:
        print('error: Sheets operation failed; inspect local setup and retry the same run ID. No raw exception was logged.', file=sys.stderr)
        return 1
