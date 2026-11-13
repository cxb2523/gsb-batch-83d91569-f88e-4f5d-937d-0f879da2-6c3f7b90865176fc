"""Stateful, atomic Sheets fake; every write retains explicit cell value types."""
from copy import deepcopy
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from gatherradar.sheets.client import SheetsError
from gatherradar.sheets.repository import SheetRepository
from gatherradar.sheets.state import RuntimeState

STAMP = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)


class OfflineCase(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ('socket.socket.connect', 'socket.create_connection', 'subprocess.Popen', 'webbrowser.open'):
            self.stack.enter_context(patch(name, side_effect=AssertionError('unexpected external operation')))
        self.directory = Path(self.stack.enter_context(TemporaryDirectory()))


class FakeSheets:
    def __init__(self):
        self.sheets = {}
        self.calls = []
        self.created = 0
        self.before = None
        self.lose_commit_response = False
        self.corrupt_read = False

    def create(self, body):
        self.create_body = deepcopy(body)
        self.created += 1
        self.sheets = {s['properties']['sheetId']: {
            'properties': deepcopy(s['properties']), 'developerMetadata': [],
            'rows': deepcopy(s.get('data', [{}])[0].get('rowData', [])), 'formats': [],
        } for s in body['sheets']}
        return {'spreadsheetId': 'fake_workbook_123', 'spreadsheetUrl': 'https://docs.google.com/spreadsheets/d/fake_workbook_123/edit'}

    def metadata(self, spreadsheet_id):
        return {'spreadsheetId': spreadsheet_id,
            'spreadsheetUrl': f'https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit',
            'sheets': [{'properties': deepcopy(s['properties']), 'developerMetadata': deepcopy(s['developerMetadata'])}
                       for s in self.sheets.values()]}

    def named(self, title):
        return next(s for s in self.sheets.values() if s['properties']['title'] == title)

    def values(self, title):
        return [[c.get('userEnteredValue', {}).get('stringValue', '') for c in r.get('values', [])]
                for r in self.named(title)['rows']]

    def read(self, spreadsheet_id, title, start, end, columns):
        rows = [r[:columns] for r in self.values(title)[start - 1:end]]
        if self.corrupt_read and title.startswith('_tmp_'):
            return []
        return deepcopy(rows)

    def edit(self, title, row, column, value):
        self.named(title)['rows'][row]['values'][column]['userEnteredValue'] = {'stringValue': value}

    def batch(self, spreadsheet_id, requests):
        self.calls.append(deepcopy(requests))
        if self.before:
            self.before(requests)
        staged = deepcopy(self.sheets)
        for request in requests:
            assert len(request) == 1
            kind, value = next(iter(request.items()))
            if kind == 'addSheet':
                p = deepcopy(value['properties'])
                if p['sheetId'] in staged or any(s['properties']['title'] == p['title'] for s in staged.values()):
                    raise SheetsError('collision')
                staged[p['sheetId']] = {'properties': p, 'rows': [], 'developerMetadata': [], 'formats': []}
            elif kind == 'deleteSheet':
                del staged[value['sheetId']]
            elif kind == 'createDeveloperMetadata':
                meta = deepcopy(value['developerMetadata'])
                staged[meta['location']['sheetId']]['developerMetadata'].append(meta)
            elif kind == 'updateSheetProperties':
                p = value['properties']
                staged[p['sheetId']]['properties'].update(deepcopy(p))
            elif kind in {'updateCells', 'appendCells'}:
                if kind == 'appendCells':
                    sheet = staged[value['sheetId']]
                    sheet['rows'].extend(deepcopy(value['rows']))
                    sheet['properties']['gridProperties']['rowCount'] = max(
                        sheet['properties']['gridProperties']['rowCount'], len(sheet['rows']))
                else:
                    start = value['start']
                    sheet = staged[start['sheetId']]
                    for offset, row in enumerate(value['rows']):
                        index = start.get('rowIndex', 0) + offset
                        while len(sheet['rows']) <= index:
                            sheet['rows'].append({'values': []})
                        target = sheet['rows'][index]['values']
                        column = start.get('columnIndex', 0)
                        while len(target) < column + len(row['values']):
                            target.append({})
                        target[column:column + len(row['values'])] = deepcopy(row['values'])
            else:
                sid = (value.get('range', {}).get('sheetId') or value.get('filter', {}).get('range', {}).get('sheetId')
                       or value.get('protectedRange', {}).get('range', {}).get('sheetId')
                       or value.get('rule', {}).get('ranges', [{}])[0].get('sheetId'))
                assert sid in staged, (kind, value)
                staged[sid]['formats'].append(deepcopy(request))
        self.sheets = staged
        if self.lose_commit_response and any('updateSheetProperties' in r for r in requests):
            self.lose_commit_response = False
            raise SheetsError('simulated lost commit response')
        return {}


class RepositoryCase(OfflineCase):
    def setUp(self):
        super().setUp()
        self.client = FakeSheets()
        self.state = RuntimeState(self.directory)
        self.repo = SheetRepository(self.client, self.state)
        self.repo.setup()
