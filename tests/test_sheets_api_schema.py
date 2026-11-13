"""Validate generated request bodies against Google's bundled discovery schema."""
from dataclasses import replace

import unittest
try:
    from googleapiclient.discovery import build
except ImportError:
    build = None
from gatherradar.deduplication import canonicalize
from gatherradar.domain import PlaceCandidate
from gatherradar.sheets.serialization import review_window
from deduplication_fakes import context
from sheets_fakes import RepositoryCase, STAMP


@unittest.skipIf(build is None, 'Install .[google-sheets] to validate official Google request schemas.')
class OfficialRequestSchemaTests(RepositoryCase):
    def test_all_generated_requests_match_official_sheets_schema(self):
        # A static discovery document is bundled with the official package;
        # no credentials, service discovery HTTP, or API requests are made.
        service = build('sheets', 'v4', developerKey='synthetic-test-key',
                        static_discovery=True, cache_discovery=False)
        schemas = service._rootDesc['schemas']

        def check(value, shape, path):
            if '$ref' in shape:
                shape = schemas[shape['$ref']]
            kind = shape.get('type')
            if kind == 'object':
                self.assertIsInstance(value, dict, path)
                known = shape.get('properties', {})
                for key, child in value.items():
                    self.assertTrue(key in known or 'additionalProperties' in shape, f'{path}.{key}')
                    check(child, known.get(key, shape.get('additionalProperties', {})), f'{path}.{key}')
            elif kind == 'array':
                self.assertIsInstance(value, list, path)
                for child in value:
                    check(child, shape['items'], path + '[]')
            elif kind == 'string':
                self.assertIsInstance(value, str, path)
                if 'enum' in shape:
                    self.assertIn(value, shape['enum'], path)
            elif kind == 'integer':
                self.assertIs(type(value), int, path)
            elif kind == 'boolean':
                self.assertIs(type(value), bool, path)
            elif kind == 'number':
                self.assertIsInstance(value, (float, int), path)

        c = context()
        result = replace(canonicalize([c]), places=(PlaceCandidate('place:1', c.raw_item.id,
            title='Gallery', evidence_url=c.raw_item.content_url),))
        self.repo.sync(result, review_window(result.events, STAMP), run_id='schema-test',
            started_at=STAMP, finished_at=STAMP, days=14, review_timezone='Asia/Tehran', source_count=1)
        for batch in self.client.calls:
            check({'requests': batch}, schemas['BatchUpdateSpreadsheetRequest'], 'batch')
        check(self.client.create_body, schemas['Spreadsheet'], 'create')
        for sheet in self.client.sheets.values():
            grid = sheet['properties']['gridProperties']
            self.assertLess(grid['frozenColumnCount'], grid['columnCount'])
            self.assertLess(grid['frozenRowCount'], grid['rowCount'])
