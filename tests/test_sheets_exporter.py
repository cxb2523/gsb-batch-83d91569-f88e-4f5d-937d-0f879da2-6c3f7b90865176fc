from gatherradar.sheets.exporter import publish_persisted
from gatherradar.sheets.repository import SheetRepository
from gatherradar.sheets.state import RuntimeState
from gatherradar.review.schema import DECISIONS, DUPLICATE_DECISIONS, EVENT_HEADERS
from local_review_fakes import LocalCase
from sheets_fakes import FakeSheets


class PersistedSheetsExportTests(LocalCase):
    def test_persisted_run_publishes_through_retained_adapter_with_review(self):
        self.persist()
        event = self.repo.load()['events'][0]
        pair = self.repo.load()['possible_duplicates'][0]
        self.repo.import_review(self.repo.review_token('event', event['event_id'], 'one'),
            'event', event['event_id'], 'one', DECISIONS[2], 'local note')
        self.repo.import_review(self.repo.review_token('duplicate', pair['pair_key'], 'one'),
            'duplicate', pair['pair_key'], 'one', DUPLICATE_DECISIONS[2], 'local duplicate')
        client = FakeSheets()
        sheets = SheetRepository(client, RuntimeState(self.root))
        sheets.setup()
        result = publish_persisted(self.repo, sheets)
        self.assertEqual((result.events, result.places, result.duplicates), (2,1,1))
        self.assertEqual(client.values(result.event_tab)[1][EVENT_HEADERS.index('یادداشت من')], 'local note')
        self.assertTrue(publish_persisted(self.repo, sheets).already_synced)

    def test_filtered_event_identity_remains_available_for_duplicate_queue(self):
        self.persist(delta=90*86400)
        client = FakeSheets()
        sheets = SheetRepository(client, RuntimeState(self.root))
        sheets.setup()
        result = publish_persisted(self.repo, sheets)
        self.assertEqual((result.events,result.duplicates), (0,1))
