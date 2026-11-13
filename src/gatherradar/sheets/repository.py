"""Immutable review snapshots with atomic publication and run-ID reconciliation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import re
from zoneinfo import ZoneInfo

from ..deduplication.models import CanonicalizationResult
from .client import SheetsClient, SheetsError, validate_id
from .schema import (
    SCHEMA_VERSION, GUIDE, RUNS, DUPLICATES, EVENT_MAP, SYNC_STATE, PERMANENT,
    GUIDE_ROWS, EVENT_HEADERS, EVENT_VISIBLE, PLACE_HEADERS, PLACE_VISIBLE,
    DECISIONS, DUPLICATE_DECISIONS,
    cells, write_rows, append_rows, properties, formatting,
)
from .serialization import (ReviewWindow, duplicate_rows, event_row, place_row,
                            snapshot_title, jalali, persian)
from .state import RuntimeState


from ..review.models import SnapshotResult


class SheetRepository:
    def __init__(self, client: SheetsClient, state: RuntimeState, *, spreadsheet_id: str | None = None) -> None:
        self.client, self.state = client, state
        self.override = validate_id(spreadsheet_id) if spreadsheet_id else None
        self.spreadsheet_id = self.override or state.read().get('spreadsheet_id')
        self.meta: dict = {}
        self.tabs: dict = {}

    def _metadata(self) -> None:
        if not self.spreadsheet_id:
            raise SheetsError('Workbook not configured; run sheets setup first.')
        self.meta = self.client.metadata(self.spreadsheet_id)
        try:
            self.tabs = {s['properties']['title']: s for s in self.meta['sheets']}
            if len(self.tabs) != len(self.meta['sheets']):
                raise ValueError
            for tab in self.tabs.values():
                p = tab['properties']
                if type(p['sheetId']) is not int or type(p['gridProperties']['rowCount']) is not int:
                    raise ValueError
        except (KeyError, ValueError, TypeError):
            raise SheetsError('Invalid workbook metadata.') from None

    def _rows(self, title: str, columns: int) -> list[list]:
        if title not in self.tabs:
            raise SheetsError('Required workbook tab is missing; run sheets setup.')
        total = self.tabs[title]['properties']['gridProperties']['rowCount']
        if total > 100000:
            raise SheetsError('Workbook tab exceeds the supported personal-review read bound.')
        result = []
        for start in range(1, total + 1, 500):
            end = min(start + 499, total)
            rows = self.client.read(self.spreadsheet_id, title, start, end, columns)
            result.extend(rows + [[] for _ in range(end - start + 1 - len(rows))])
        while result and not any(v != '' for v in result[-1]):
            result.pop()
        return result

    def _table(self, title: str) -> list[list]:
        headers = PERMANENT[title][0]
        rows = self._rows(title, len(headers))
        if not rows or tuple(rows[0]) != headers:
            raise SheetsError('Workbook headers changed; restore machine headers before syncing. No data was reset.')
        return [r + [''] * (len(headers) - len(r)) for r in rows[1:]]

    def _sid(self, title: str) -> int:
        return self.tabs[title]['properties']['sheetId']

    def validate(self) -> None:
        self._metadata()
        if SYNC_STATE not in self.tabs:
            raise SheetsError('This workbook has no GatherRadar schema marker; it cannot be adopted automatically.')
        state = dict((r[0], r[1]) for r in self._table(SYNC_STATE) if r[0])
        if str(state.get('schema_version')) != str(SCHEMA_VERSION):
            raise SheetsError('Workbook schema version is incompatible; no automatic migration was performed.')
        for title in (RUNS, DUPLICATES, EVENT_MAP):
            self._table(title)

    def setup(self, *, title: str = 'GatherRadar', new: bool = False) -> str:
        local = self.state.read()
        if new and self.override:
            raise SheetsError('Choose either --new or a spreadsheet-ID override.')
        if not title.strip() or len(title) > 100:
            raise SheetsError('Workbook title must contain 1–100 characters.')
        if not self.spreadsheet_id or new:
            if local.get('creation_pending'):
                raise SheetsError('A previous workbook creation has an uncertain outcome. Inspect Google Sheets and configure its ID before creating another.')
            # Persist intent BEFORE a non-idempotent create, even if the response is lost.
            self.state.save(dict(local, creation_pending=True))
            sheets = []
            for sid, (name, (headers, visible)) in enumerate(PERMANENT.items(), 1):
                rows = GUIDE_ROWS if name == GUIDE else [list(headers)]
                if name == SYNC_STATE:
                    rows += [['schema_version', 'initializing']]
                sheets.append({'properties': properties(sid, name, len(headers), hidden=visible == 0),
                               'data': [{'rowData': [cells(r) for r in rows]}]})
            created = self.client.create({'properties': {'title': title, 'timeZone': 'Asia/Tehran'}, 'sheets': sheets})
            self.spreadsheet_id = validate_id(created['spreadsheetId'])
            self.state.save({'spreadsheet_id': self.spreadsheet_id, 'spreadsheet_url': created['spreadsheetUrl'],
                             'created_at': datetime.now(timezone.utc).isoformat(), 'schema_version': SCHEMA_VERSION})
        self._metadata()
        if SYNC_STATE not in self.tabs:
            raise SheetsError('Unrecognized workbook: missing schema marker; nothing was changed.')
        version = dict((r[0], r[1]) for r in self._table(SYNC_STATE) if r[0]).get('schema_version')
        if str(version) not in {str(SCHEMA_VERSION), 'initializing'}:
            raise SheetsError('Workbook schema version is incompatible; no automatic migration was performed.')
        requests = []
        next_id = max(s['properties']['sheetId'] for s in self.tabs.values()) + 1
        for name, (headers, visible) in PERMANENT.items():
            missing = name not in self.tabs
            if missing:
                sid = next_id
                next_id += 1
                requests += [{'addSheet': {'properties': properties(sid, name, len(headers), hidden=visible == 0)}},
                             write_rows(sid, GUIDE_ROWS if name == GUIDE else [list(headers)])]
            else:
                sid = self._sid(name)
                if name != GUIDE:
                    self._table(name)
            if missing or version == 'initializing':
                requests.extend(formatting(sid, len(headers), visible, 1000,
                    decisions=DUPLICATE_DECISIONS if name == DUPLICATES else (), table=name not in {GUIDE, SYNC_STATE, EVENT_MAP}))
        if version == 'initializing':
            requests.append(write_rows(self._sid(SYNC_STATE), [['schema_version', str(SCHEMA_VERSION)]], row=1))
        self.client.batch(self.spreadsheet_id, requests)
        self.validate()
        local = self.state.read()
        if local.get('spreadsheet_id') != self.spreadsheet_id:
            local = {}
        self.state.save(dict(local, spreadsheet_id=self.spreadsheet_id,
            spreadsheet_url=self.meta['spreadsheetUrl'], schema_version=SCHEMA_VERSION, creation_pending=False))
        return self.meta['spreadsheetUrl']

    def find_run(self, run_id: str) -> SnapshotResult | None:
        self.validate()
        found = [r for r in self._table(RUNS) if r[0] == run_id]
        if len(found) > 1:
            raise SheetsError('Duplicate run identities in the index; manual inspection is required.')
        if not found:
            if any(not s['properties']['title'].startswith('_tmp_') and any(
                    m.get('metadataKey') == 'gatherradar_run' and m.get('metadataValue') == run_id
                    for m in s.get('developerMetadata', [])) for s in self.tabs.values()):
                raise SheetsError('Completed snapshot metadata exists without its run index. Restore the index before retrying; no duplicate snapshot was created.')
            return None
        row = found[0]
        if row[4] not in {'success', 'partial', 'failed'}:
            raise SheetsError('Invalid run status in workbook history.')
        try:
            # Stable sheet IDs survive user renames and tab reordering.
            by_id = {str(s['properties']['sheetId']): s['properties']['title'] for s in self.tabs.values()}
            return SnapshotResult(run_id, self.meta['spreadsheetUrl'], by_id.get(str(row[14]), ''),
                by_id.get(str(row[15]), ''), int(row[6]), int(row[7]), int(row[8]), str(row[4]),
                int(row[16]), int(row[17]), True)
        except (TypeError, ValueError):
            raise SheetsError('Invalid completed run index; no snapshot was overwritten.') from None

    def _human_state(self) -> dict[str, tuple[str, str]]:
        prior = self._table(RUNS)
        try:
            # Never depend on a user's sort order in the run index.
            prior.sort(key=lambda r: (datetime.fromisoformat(r[12]), r[0]))
        except (TypeError, ValueError):
            raise SheetsError('Invalid run timestamp in workbook history.') from None
        by_id = {str(s['properties']['sheetId']): s['properties']['title'] for s in self.tabs.values()}
        state = {}
        for run in prior:
            if run[4] not in {'success', 'partial'} or not run[14]:
                continue
            title = by_id.get(str(run[14]))
            if title is None:
                raise SheetsError('Historical Event snapshot is missing; cannot safely carry forward review decisions.')
            rows = self._rows(title, len(EVENT_HEADERS))
            if not rows or any(rows[0].count(h) != 1 for h in ('event_id', 'تصمیم من', 'یادداشت من')):
                raise SheetsError('Historical Event identity/review headers changed; cannot safely carry forward decisions.')
            indices = [rows[0].index(h) for h in ('event_id', 'تصمیم من', 'یادداشت من')]
            seen = set()
            for row in rows[1:]:
                row = row + [''] * (len(EVENT_HEADERS) - len(row))
                eid, decision, note = (row[i] for i in indices)
                if not eid:
                    continue
                if not isinstance(eid, str) or eid in seen:
                    raise SheetsError('Ambiguous historical Event identity; decisions were not guessed.')
                seen.add(eid)
                state[eid] = (str(decision), str(note))
        return state

    def _machine_updates(self, result: CanonicalizationResult, run_id: str,
                         initial_duplicate_review: dict | None = None) -> tuple[list[dict], int]:
        requests = []
        mappings = self._table(EVENT_MAP)
        known = {r[0]: (i + 1, r) for i, r in enumerate(mappings) if r[0]}
        if len(known) != len([r for r in mappings if r[0]]):
            raise SheetsError('Duplicate Event mappings require manual inspection.')
        additions = []
        for event in result.events:
            if event.event_id in known:
                i, row = known[event.event_id]
                if row[1:3] != [event.identity_anchor_raw_item_id, event.identity_anchor_slot]:
                    raise SheetsError('Event identity anchor conflict; no mapping was reassigned.')
                requests.append(write_rows(self._sid(EVENT_MAP), [[run_id]], row=i, column=4))
            else:
                additions.append([event.event_id, event.identity_anchor_raw_item_id,
                                  event.identity_anchor_slot, run_id, run_id])
        if additions:
            requests.append(append_rows(self._sid(EVENT_MAP), additions))
        old_pairs = self._table(DUPLICATES)
        known_pairs = {r[9]: (i + 1, r) for i, r in enumerate(old_pairs) if r[9]}
        if len(known_pairs) != len([r for r in old_pairs if r[9]]):
            raise SheetsError('Duplicate pair keys in review queue require manual inspection.')
        pairs = duplicate_rows(result, run_id)
        new_pairs = []
        for row in pairs:
            if row[9] in known_pairs:
                i, old = known_pairs[row[9]]
                if old[10:12] != row[10:12]:
                    raise SheetsError('Duplicate review identity conflict.')
                # Human columns 0 and 8 are NEVER part of an update request.
                requests += [write_rows(self._sid(DUPLICATES), [row[1:8]], row=i, column=1),
                             write_rows(self._sid(DUPLICATES), [row[13:15]], row=i, column=13)]
            else:
                if initial_duplicate_review and row[9] in initial_duplicate_review:
                    row[0], row[8] = initial_duplicate_review[row[9]]
                new_pairs.append(row)
        if new_pairs:
            requests.append(append_rows(self._sid(DUPLICATES), new_pairs))
        return requests, len(pairs)

    def sync(self, result: CanonicalizationResult, window: ReviewWindow, *, run_id: str,
             started_at: datetime, finished_at: datetime, days: int, review_timezone: str,
             source_count: int, failures: tuple[str, ...] = (), status: str = 'success', run_metadata: dict | None = None) -> SnapshotResult:
        from ..review.serialization import eligible_review
        result, window = eligible_review(result, window)
        if (not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', run_id)
                or type(days) is not int or not 1 <= days <= 90
                or type(source_count) is not int or source_count < 0
                or any(t.tzinfo is None or t.utcoffset() is None for t in (started_at, finished_at))
                or finished_at < started_at):
            raise SheetsError('Invalid snapshot run context.')
        ZoneInfo(review_timezone)
        previous = self.find_run(run_id)
        if previous:
            if previous.events != len(window.events) or previous.filtered != window.filtered:
                # Append an eligible projection of an old published snapshot;
                # never rewrite its facts or human review.
                if (run_metadata or {}).get('projection_of'):
                    raise SheetsError('Existing eligible projection counts differ; historical snapshots were preserved.')
                membership = '\n'.join(sorted(e.event_id for e in result.events))
                membership += '\nvisible:\n' + '\n'.join(sorted(e.event_id for e in window.events))
                digest = sha256((run_id + '\n' + membership).encode()).hexdigest()[:16]
                projection_id = run_id[:35] + '_eligible_' + digest
                return self.sync(result, window, run_id=projection_id,
                    started_at=started_at, finished_at=finished_at, days=days,
                    review_timezone=review_timezone, source_count=source_count,
                    failures=failures, status=status,
                    run_metadata=dict(run_metadata or {}, projection_of=run_id))
            return previous
        if status not in {'success', 'partial', 'failed'}:
            raise SheetsError('Invalid run status.')
        human = self._human_state()
        # Initial local decisions may seed a new Google review identity. Existing
        # Google-owned review always wins; there is no implicit reverse sync.
        human = dict((run_metadata or {}).get('initial_event_review', {}), **human)
        requests, pair_count = self._machine_updates(result, run_id,
            (run_metadata or {}).get('initial_duplicate_review'))
        source_by_raw = {c.raw_item.id: c.source.id for c in result.contexts}
        source_by_raw.update((run_metadata or {}).get('place_source_ids', {}))
        tables = []
        if status != 'failed':
            tables.append(('events', 'رویدادها', EVENT_HEADERS, len(EVENT_VISIBLE),
                [event_row(e, run_id, human.get(e.event_id)) for e in window.events]))
            if result.places:
                tables.append(('places', 'مکان‌ها', PLACE_HEADERS, len(PLACE_VISIBLE),
                    [place_row(p, run_id, source_by_raw.get(p.raw_item_id, '')) for p in result.places]))
        digest = sha256(run_id.encode()).hexdigest()[:20]
        next_id = max(s['properties']['sheetId'] for s in self.tabs.values()) + 1
        temporary = []
        final_tabs = {}
        try:
            for kind, label, headers, visible, rows in tables:
                temporary_title = f'_tmp_{digest}_{kind}'
                name = snapshot_title(label, started_at, review_timezone)
                if name in self.tabs:
                    name += '_' + digest[:8]
                if name in self.tabs:
                    raise SheetsError('Snapshot name collision; no existing snapshot was overwritten.')
                sid = next_id
                next_id += 1
                if temporary_title in self.tabs:
                    tab = self.tabs[temporary_title]
                    owned = any(m.get('metadataKey') == 'gatherradar_run' and m.get('metadataValue') == run_id
                                for m in tab.get('developerMetadata', []))
                    if not owned:
                        raise SheetsError('Unowned temporary tab collision; nothing was replaced.')
                    self.client.batch(self.spreadsheet_id, [{'deleteSheet': {'sheetId': tab['properties']['sheetId']}}])
                initial = [
                    {'addSheet': {'properties': properties(sid, temporary_title, len(headers), len(rows) + 1, hidden=True)}},
                    {'createDeveloperMetadata': {'developerMetadata': {'metadataKey': 'gatherradar_run',
                        'metadataValue': run_id, 'location': {'sheetId': sid}, 'visibility': 'DOCUMENT'}}},
                ]
                self.client.batch(self.spreadsheet_id, initial)
                temporary.append(sid)
                data = [list(headers)] + rows
                for offset in range(0, len(data), 250):
                    self.client.batch(self.spreadsheet_id, [write_rows(sid, data[offset:offset + 250], row=offset)])
                self.client.batch(self.spreadsheet_id, formatting(sid, len(headers), visible,
                    len(data), decisions=DECISIONS))
                # Verify literal values and complete row membership before publication.
                actual = []
                for offset in range(0, len(data), 500):
                    actual.extend(self.client.read(self.spreadsheet_id, temporary_title,
                        offset + 1, min(offset + 500, len(data)), len(headers)))
                expected = [[str(v) if v is not None else '' for v in r] for r in data]
                actual = [r + [''] * (len(headers) - len(r)) for r in actual]
                if actual != expected:
                    raise SheetsError('Temporary snapshot verification failed; run was not published.')
                final_tabs[kind] = (sid, name)
                requests.append({'updateSheetProperties': {'properties': {'sheetId': sid, 'title': name,
                    'hidden': False, 'rightToLeft': True, 'index': 3 + len(final_tabs) - 1},
                    'fields': 'title,hidden,rightToLeft,index'}})
        except Exception:
            # Only our known, unpublished temporary tabs may be removed.
            if temporary:
                try:
                    self.client.batch(self.spreadsheet_id, [{'deleteSheet': {'sheetId': sid}} for sid in temporary])
                except SheetsError:
                    pass
            raise
        local = started_at.astimezone(ZoneInfo(review_timezone))
        event_sid, event_title = final_tabs.get('events', ('', ''))
        place_sid, place_title = final_tabs.get('places', ('', ''))
        base = self.meta['spreadsheetUrl'].split('#')[0]
        row = [run_id, jalali(local.date()), persian(local.strftime('%H:%M')), days, status,
            source_count, len(window.events), len(result.places), pair_count, '\n'.join(failures),
            f'{base}#gid={event_sid}' if event_sid != '' else '',
            f'{base}#gid={place_sid}' if place_sid != '' else '', started_at.isoformat(), finished_at.isoformat(),
            event_sid, place_sid, window.filtered, window.undated]
        requests.append(append_rows(self._sid(RUNS), [row]))
        # This is the commit point: renames + run index + mapping + duplicate
        # updates succeed together. Never clean up on an ambiguous response here.
        try:
            self.client.batch(self.spreadsheet_id, requests)
        except SheetsError:
            reconciled = self.find_run(run_id)
            if reconciled:
                return reconciled
            raise
        confirmed = self.find_run(run_id)
        if confirmed is None:
            raise SheetsError('Run completion could not be verified; retry the same run ID.')
        local_state = self.state.read()
        if local_state.get('spreadsheet_id') == self.spreadsheet_id:
            self.state.save(dict(local_state, latest_successful_run_id=run_id))
        return SnapshotResult(run_id, self.meta['spreadsheetUrl'], event_title, place_title,
            len(window.events), len(result.places), pair_count, status, window.filtered, window.undated)
