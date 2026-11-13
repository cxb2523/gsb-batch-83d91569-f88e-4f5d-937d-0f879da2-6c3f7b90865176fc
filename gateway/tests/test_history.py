import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))
from history_store import HistoryStore, query_history, RETENTION_DAYS

T = 1800000000.0


def row(key='a', *, start=T - 3600, upload=1000, download=2000, host='x.com', source='172.21.0.3', node='node-a'):
    return {'id': key, 'start': datetime.fromtimestamp(start, timezone.utc).isoformat(),
            'upload': upload, 'download': download, 'chains': [node],
            'metadata': {'host': host, 'sourceIP': source, 'destinationPort': '443', 'network': 'tcp',
                         'inboundName': 'DEFAULT-MIXED', 'secret': 'DO-NOT-STORE'}}


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'history.sqlite3'
        self.store = HistoryStore(self.path, T)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def ingest(self, at, *rows):
        self.store.ingest({'connections': list(rows)}, at)

    def query(self, **kwargs):
        return query_history(self.path, **{'start': T - 1, 'end': T + 20, 'now': T + 6, **kwargs})

    def test_preexisting_counters_are_baseline_and_identical_polls_do_not_double_count(self):
        self.ingest(T, row())
        self.ingest(T + 2, row(upload=1100, download=2400))
        self.ingest(T + 4, row(upload=1100, download=2400))
        report = self.query()
        self.assertEqual(report['totals'], {'connections': 1, 'upload': 100, 'download': 400})
        self.assertEqual(report['records']['rows'][0]['upload_total'], 1100)
        self.assertTrue(report['records']['rows'][0]['preexisting'])
        self.assertEqual(sum(p['download'] for p in report['series']), 400)

    def test_new_connections_include_first_observed_bytes(self):
        self.ingest(T)
        self.ingest(T + 2, row(start=T + 1, upload=10, download=20))
        report = self.query()
        self.assertEqual(report['totals']['upload'], 10)
        self.assertFalse(report['records']['rows'][0]['preexisting'])

    def test_disappeared_connections_remain_queryable(self):
        self.ingest(T, row())
        self.ingest(T + 2, row(upload=1500))
        self.ingest(T + 4)
        report = self.query()
        record = report['records']['rows'][0]
        self.assertEqual(record['state'], 'not_seen')
        self.assertEqual(record['last_seen'], T + 2)
        self.assertEqual(report['totals']['upload'], 500)
        self.assertEqual(record['host'], 'x.com')

    def test_interval_boundaries_are_half_open(self):
        self.ingest(T, row())
        self.ingest(T + 2, row(upload=1100))
        self.ingest(T + 4, row(upload=1300))
        self.assertEqual(self.query(start=T + 2, end=T + 4)['totals']['upload'], 100)
        self.assertEqual(self.query(start=T + 4, end=T + 6)['totals']['upload'], 200)

    def test_outage_and_restart_do_not_assign_missing_bytes_to_recovery(self):
        self.ingest(T, row())
        self.store.failed(T + 2)
        self.assertFalse(self.query()['collector']['healthy'])
        self.ingest(T + 4, row(upload=9000))
        self.ingest(T + 6, row(upload=9100))
        self.assertEqual(self.query()['totals']['upload'], 100)
        self.store.close()
        self.store = HistoryStore(self.path, T + 10)
        self.ingest(T + 10, row(upload=12000))
        report = self.query(now=T + 10)
        self.assertEqual(report['totals']['upload'], 100)
        self.assertEqual(report['gap_count'], 2)
        self.assertTrue(report['collector']['healthy'])

    def test_counter_reset_creates_gap_without_negative_or_inflated_traffic(self):
        self.ingest(T, row())
        self.ingest(T + 2, row(upload=50, download=60))
        self.ingest(T + 4, row(upload=80, download=100))
        report = self.query()
        self.assertEqual(report['totals']['upload'], 30)
        self.assertEqual(report['totals']['download'], 40)
        self.assertEqual(report['gaps'][0]['reason'], 'counter_reset')

    def test_classification_drilldown_search_and_pagination_share_totals(self):
        self.ingest(T)
        self.ingest(T + 2, row(start=T + 1, upload=10, download=20),
                    row('b', start=T + 1, upload=30, download=40, host='example.org', node='DIRECT'))
        report = self.query(group_by='route', page_size=1)
        self.assertEqual(report['groups']['total'], 2)
        self.assertEqual(report['groups']['rows'][0]['label'], 'direct')
        self.assertEqual(report['records']['total'], 2)
        self.assertEqual(len(report['records']['rows']), 1)
        filtered = self.query(group_by='route', group_value='direct')
        self.assertEqual(filtered['totals'], {'connections': 1, 'upload': 30, 'download': 40})
        self.assertEqual(sum(p['download'] for p in filtered['series']), 40)
        self.assertEqual(self.query(search='x.com')['totals']['connections'], 1)
        self.assertEqual(self.query(search="%' OR 1=1 --")['totals']['connections'], 0)
        self.assertEqual(self.query(route='proxy')['totals']['upload'], 10)
        categories = self.query(group_by='category')
        self.assertEqual({g['label'] for g in categories['groups']['rows']}, {'社交内容', '其他 / 未分类'})
        self.assertEqual(self.query(group_by='category', group_value='社交内容')['totals']['upload'], 10)

    def test_stale_collection_and_traffic_activity_are_explicit(self):
        self.ingest(T, row())
        report = self.query(now=T + 100)
        self.assertFalse(report['collector']['healthy'])
        self.assertEqual(report['records']['rows'][0]['state'], 'unknown')
        self.assertEqual(report['records']['rows'][0]['activity'], 'idle')
        self.assertEqual(report['totals']['upload'], 0)

    def test_retention_and_whitelisted_metadata(self):
        self.ingest(T)
        self.ingest(T + 2, row(start=T + 1, upload=10))
        self.ingest(T + 4)
        self.store.prune(T + (RETENTION_DAYS + 1) * 86400)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM traffic').fetchone()[0], 0)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM connections').fetchone()[0], 0)
        self.assertNotIn(b'DO-NOT-STORE', self.path.read_bytes())

    def test_invalid_ranges_and_group_identifiers_are_rejected(self):
        for kwargs in ({'start': T + 1, 'end': T}, {'start': float('nan')},
                       {'group_by': 'host); DROP TABLE connections;--'}, {'page': 0},
                       {'start': T - 32 * 86400, 'end': T}):
            with self.assertRaises(ValueError):
                self.query(**kwargs)

    def test_storage_budget_does_not_move_retention_into_the_future(self):
        self.ingest(T)
        self.ingest(T + 2, row(start=T + 1, upload=10))
        with patch('history_store.MAX_BYTES', 1):
            self.store.prune(T + 4)
        report = self.query()
        self.assertLessEqual(report['collector']['retained_from'], T + 4)
        self.assertEqual(report['totals']['upload'], 0)


if __name__ == '__main__':
    unittest.main()
