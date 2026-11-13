import csv
import io
import json
from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
from unittest.mock import patch

from gatherradar.exports.gemini import GeminiBundleExporter, INSTRUCTIONS
from gatherradar.exports.portable import CsvReviewExporter, JsonReviewExporter, csv_cell
from gatherradar.review.records import dumps, event_from_record, event_record
from local_review_fakes import LocalCase


class PortableTests(LocalCase):
    def setUp(self):
        super().setUp()
        self.persist()
        self.document = self.repo.load()
        self.exports = self.root / 'exports'

    def test_csv_utf8_bom_machine_headers_nulls_and_urls(self):
        paths = CsvReviewExporter(self.exports).export(self.document)
        self.assertEqual(len(paths), 8)
        path = self.exports / 'latest/events.csv'
        self.assertTrue(path.read_bytes().startswith(b'\xef\xbb\xbf'))
        with path.open(encoding='utf-8-sig', newline='') as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(rows[0]['title'], 'کارگاه مهتاب')
        self.assertEqual(rows[0]['registration_url'], '')
        self.assertTrue(rows[0]['canonical_source_url'].startswith('https://'))
        self.assertEqual(len(rows), 2)
        self.assertIn('review_decision', rows[0])

    def test_csv_formula_risks_and_leading_whitespace(self):
        for value in ('=1', '+1', '-1', '@x', ' \t=1', '\ttext', '\rtext', '\ufeff=1'):
            self.assertTrue(csv_cell(value).startswith("'"), value)
        self.assertEqual(csv_cell(None), '')
        self.assertEqual(csv_cell('متن'), 'متن')

    def test_json_schema_arrays_and_original_formula_string(self):
        self.document['events'][0]['title'] = '=original'
        JsonReviewExporter(self.exports).export(self.document)
        data = json.loads((self.exports / 'latest/review.json').read_text(encoding='utf-8'))
        self.assertEqual(data['schema_version'], 3)
        self.assertIsInstance(data['events'][0]['candidate_ids'], list)
        self.assertEqual(data['events'][0]['title'], '=original')
        self.assertEqual(len(data['places']), 1)
        self.assertEqual(len(data['possible_duplicates']), 1)

    def test_decimal_temporal_enum_roundtrip(self):
        event = replace(self.result.events[0], price_amount=Decimal('123.40'), currency='TOMAN')
        record = json.loads(dumps(event_record(event)))
        self.assertEqual(record['price_amount'], '123.40')
        self.assertEqual(record['start_date'], '2026-10-01')
        self.assertEqual(record['start_time'], '18:00:00')
        self.assertEqual(record['date_precision'], 'exact')
        self.assertEqual(event_from_record(record), event)

    def test_deterministic_csv_json_bytes_and_order(self):
        exporters = (CsvReviewExporter(self.exports), JsonReviewExporter(self.exports))
        for exporter in exporters:
            paths = exporter.export(self.document)
            before = {path: path.read_bytes() for path in paths}
            exporter.export(self.document)
            self.assertEqual(before, {path: path.read_bytes() for path in paths})

    def test_gemini_structure_manifest_hashes_and_counts(self):
        paths = GeminiBundleExporter(self.exports / 'gemini').export(self.document)
        self.assertEqual(len(paths), 14)
        latest = self.exports / 'gemini/latest'
        manifest = json.loads((latest / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual((manifest['bundle_schema_version'], manifest['export_schema_version']), (1, 3))
        self.assertEqual(manifest['counts'], {'events':2,'schedule_review':0,'places':1,'possible_duplicates':1})
        self.assertEqual(set(manifest['files']), {p.name for p in latest.iterdir()})
        for filename, digest in manifest['sha256'].items():
            self.assertEqual(sha256((latest / filename).read_bytes()).hexdigest(), digest)
        self.assertNotIn(str(self.root), json.dumps(manifest))

    def test_gemini_reuses_exact_portable_bytes(self):
        CsvReviewExporter(self.exports).export(self.document)
        JsonReviewExporter(self.exports).export(self.document)
        GeminiBundleExporter(self.exports / 'gemini').export(self.document)
        for filename in ('events.csv','places.csv','possible_duplicates.csv','review.json'):
            self.assertEqual((self.exports / 'latest' / filename).read_bytes(),
                             (self.exports / 'gemini/latest' / filename).read_bytes())

    def test_gemini_empty_optional_tables_are_explicit(self):
        self.document['places'] = []
        self.document['possible_duplicates'] = []
        GeminiBundleExporter(self.exports).export(self.document)
        manifest = json.loads((self.exports / 'latest/manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['counts']['places'], 0)
        with (self.exports / 'latest/places.csv').open(encoding='utf-8-sig') as handle:
            self.assertEqual(len(list(csv.reader(handle))), 1)
        self.assertIn('headers', manifest['empty_tables'])

    def test_gemini_instructions_protect_integrity_and_one_way_boundary(self):
        for phrase in ('Do not invent facts', 'silent row deletion', 'automatic duplicate merge',
                       'Never remove Event IDs', 'do not rewrite source URLs', 'leave blank/unknown',
                       'NOT automatically', 'untrusted data', 'JSON', 'RTL', 'علاقه‌مندم', 'جدا هستند'):
            self.assertIn(phrase, INSTRUCTIONS)

    def test_gemini_deterministic_and_no_raw_or_secrets(self):
        exporter = GeminiBundleExporter(self.exports)
        paths = exporter.export(self.document)
        before = {path: path.read_bytes() for path in paths}
        exporter.export(self.document)
        self.assertEqual(before, {path: path.read_bytes() for path in paths})
        record = json.loads((self.exports / 'latest/review.json').read_text(encoding='utf-8'))
        for forbidden in ('raw_text','raw_metadata','raw_ocr','access_token','refresh_token','client_secret'):
            self.assertNotIn(forbidden, json.dumps(record))

    def test_portable_exports_do_not_import_openpyxl_or_google(self):
        import builtins
        original = builtins.__import__
        def checked(name, *args, **kwargs):
            if name.startswith(('openpyxl','google','httplib2')):
                raise AssertionError('unexpected optional import')
            return original(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=checked):
            CsvReviewExporter(self.exports).export(self.document)
            JsonReviewExporter(self.exports).export(self.document)
            GeminiBundleExporter(self.exports / 'gemini').export(self.document)
