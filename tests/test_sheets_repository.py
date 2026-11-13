from copy import deepcopy
from dataclasses import replace
from datetime import timedelta

from gatherradar.deduplication import canonicalize
from gatherradar.deduplication.models import CanonicalizationResult, DuplicateDecision, MatchKind
from gatherradar.domain import PlaceCandidate
from gatherradar.domain.temporal import DatePrecision
from gatherradar.sheets.client import SheetsError
from gatherradar.sheets.repository import SheetRepository
from gatherradar.sheets.schema import (
    GUIDE, RUNS, DUPLICATES, EVENT_MAP, SYNC_STATE, PERMANENT, EVENT_HEADERS,
    EVENT_VISIBLE, PLACE_HEADERS, DECISIONS, write_rows,
)
from gatherradar.sheets.serialization import review_window
from deduplication_fakes import context
from sheets_fakes import RepositoryCase, STAMP


class SnapshotTests(RepositoryCase):
    def sync(self, run='run_one', result=None, **kwargs):
        result = result or canonicalize([context()])
        started_at = kwargs.pop('started_at', STAMP)
        return self.repo.sync(result, review_window(result.events, started_at), run_id=run,
            started_at=started_at, finished_at=started_at + timedelta(minutes=1),
            days=14, review_timezone='Asia/Tehran', source_count=1, **kwargs)

    def test_invalid_run_context_is_rejected_before_writes(self):
        result = canonicalize([context()])
        before = deepcopy(self.client.sheets)
        with self.assertRaises(SheetsError):
            self.repo.sync(result, review_window(result.events, STAMP), run_id='bad-context',
                started_at=STAMP, finished_at=STAMP - timedelta(minutes=1), days=14,
                review_timezone='Asia/Tehran', source_count=1)
        self.assertEqual(self.client.sheets, before)

    def test_setup_idempotent_and_non_destructive(self):
        before = deepcopy(self.client.sheets)
        self.repo.setup()
        self.assertEqual(self.client.created, 1)
        self.assertEqual(self.client.sheets, before)
        self.assertEqual(set(self.client.metadata('fake_workbook_123')['sheets'][i]['properties']['title']
                             for i in range(5)), set(PERMANENT))

    def test_missing_permanent_structure_created_without_reset(self):
        del self.client.sheets[self.repo._sid(EVENT_MAP)]
        before = deepcopy(self.client.named(DUPLICATES))
        self.repo.setup()
        self.assertEqual(self.client.named(DUPLICATES), before)
        self.assertEqual(self.client.values(EVENT_MAP)[0][0], 'event_id')

    def test_unknown_newer_schema_refused(self):
        self.client.edit(SYNC_STATE, 1, 1, '999')
        before = deepcopy(self.client.sheets)
        with self.assertRaises(SheetsError):
            self.repo.setup()
        self.assertEqual(self.client.sheets, before)

    def test_unrecognized_workbook_is_not_adopted(self):
        del self.client.sheets[self.repo._sid(SYNC_STATE)]
        with self.assertRaises(SheetsError):
            self.repo.setup()

    def test_setup_preserves_guide_edits(self):
        self.client.edit(GUIDE, 2, 1, 'owner wording')
        self.repo.setup()
        self.assertEqual(self.client.values(GUIDE)[2][1], 'owner wording')

    def test_one_run_event_snapshot_and_no_empty_places_tab(self):
        result = self.sync()
        self.assertEqual(result.events, 1)
        self.assertEqual(result.place_tab, '')
        self.assertEqual(self.client.values(result.event_tab)[0], list(EVENT_HEADERS))
        self.assertTrue(result.event_tab.startswith('رویدادها_1405-07-03_'))
        self.assertEqual(len(self.client.values(RUNS)), 2)

    def test_second_run_never_changes_historical_snapshot(self):
        first = self.sync()
        self.client.edit(first.event_tab, 1, 1, 'manually corrected title')
        before = deepcopy(self.client.named(first.event_tab))
        second = self.sync('run_two')
        self.assertNotEqual(first.event_tab, second.event_tab)
        self.assertEqual(self.client.named(first.event_tab), before)
        self.assertNotEqual(self.client.values(second.event_tab)[1][1], 'manually corrected title')

    def test_same_run_id_is_already_synced_without_writes(self):
        first = self.sync()
        before, calls = deepcopy(self.client.sheets), len(self.client.calls)
        second = self.sync()
        self.assertTrue(second.already_synced)
        self.assertEqual(second.event_tab, first.event_tab)
        self.assertEqual(self.client.sheets, before)
        self.assertEqual(len(self.client.calls), calls)

    def test_deleted_run_index_does_not_duplicate_existing_snapshot(self):
        self.sync()
        self.client.named(RUNS)['rows'] = self.client.named(RUNS)['rows'][:1]
        before = deepcopy(self.client.sheets)
        with self.assertRaises(SheetsError):
            self.sync()
        self.assertEqual(self.client.sheets, before)

    def test_human_decision_and_note_follow_identity(self):
        first = self.sync()
        self.client.edit(first.event_tab, 1, 0, 'رفتم')
        self.client.edit(first.event_tab, 1, EVENT_HEADERS.index('یادداشت من'), '=literal owner note')
        second = self.sync('run_two')
        row = self.client.values(second.event_tab)[1]
        self.assertEqual((row[0], row[EVENT_HEADERS.index('یادداشت من')]), ('رفتم', '=literal owner note'))

    def test_similar_title_different_identity_does_not_inherit(self):
        first = self.sync()
        self.client.edit(first.event_tab, 1, 0, 'رد شد')
        result = canonicalize([context('different')])
        second = self.sync('run_two', result)
        self.assertEqual(self.client.values(second.event_tab)[1][0], 'بررسی نشده')

    def test_latest_completed_snapshot_wins_even_if_index_sorted(self):
        first = self.sync()
        self.client.edit(first.event_tab, 1, 0, 'رد شد')
        second = self.sync('run_two', started_at=STAMP + timedelta(minutes=2))
        self.client.edit(second.event_tab, 1, 0, 'می‌خوام برم')
        self.client.named(RUNS)['rows'][1:] = reversed(self.client.named(RUNS)['rows'][1:])
        third = self.sync('run_three', started_at=STAMP + timedelta(minutes=3))
        self.assertEqual(self.client.values(third.event_tab)[1][0], 'می‌خوام برم')

    def test_renamed_historical_tab_carries_by_sheet_id(self):
        first = self.sync()
        tab = self.client.named(first.event_tab)
        self.client.edit(first.event_tab, 1, EVENT_HEADERS.index('یادداشت من'), 'saved note')
        tab['properties']['title'] = 'My renamed history'
        second = self.sync('run_two')
        self.assertEqual(self.client.values(second.event_tab)[1][EVENT_HEADERS.index('یادداشت من')], 'saved note')

    def test_missing_historical_identity_fails_closed(self):
        first = self.sync()
        self.client.edit(first.event_tab, 0, EVENT_HEADERS.index('event_id'), 'edited_header')
        with self.assertRaises(SheetsError):
            self.sync('run_two')
        self.assertEqual(len(self.client.values(RUNS)), 2)

    def test_places_are_separate_candidates(self):
        c = context()
        p = PlaceCandidate('place:1', c.raw_item.id, title='Gallery', evidence_url=c.raw_item.content_url)
        result = replace(canonicalize([c]), places=(p,))
        snapshot = self.sync(result=result)
        self.assertEqual(snapshot.places, 1)
        self.assertEqual(self.client.values(snapshot.place_tab)[0], list(PLACE_HEADERS))
        self.assertEqual(self.client.values(snapshot.place_tab)[1][10], p.candidate_id)

    def test_rtl_filters_freeze_hidden_columns_dropdown_and_warning_protection(self):
        snapshot = self.sync()
        tab = self.client.named(snapshot.event_tab)
        self.assertTrue(tab['properties']['rightToLeft'])
        self.assertEqual(tab['properties']['gridProperties']['frozenRowCount'], 1)
        requests = tab['formats']
        self.assertTrue(any('setBasicFilter' in r for r in requests))
        rule = next(r['setDataValidation']['rule'] for r in requests if 'setDataValidation' in r)
        self.assertEqual([v['userEnteredValue'] for v in rule['condition']['values']], list(DECISIONS))
        self.assertTrue(any(r.get('updateDimensionProperties', {}).get('properties', {}).get('hiddenByUser') for r in requests))
        self.assertTrue(next(r['addProtectedRange']['protectedRange']['warningOnly'] for r in requests if 'addProtectedRange' in r))
        self.assertTrue(self.client.named(EVENT_MAP)['properties']['hidden'])

    def test_failed_value_verification_never_publishes(self):
        self.client.corrupt_read = True
        with self.assertRaises(SheetsError):
            self.sync()
        self.assertEqual(len(self.client.values(RUNS)), 1)
        self.assertFalse(any(s['properties']['title'].startswith('_tmp_') for s in self.client.sheets.values()))
        self.assertEqual(len(self.client.values(EVENT_MAP)), 1)

    def test_atomic_commit_rejection_and_retry(self):
        def reject(requests):
            if any('updateSheetProperties' in r for r in requests):
                raise SheetsError('simulated transient commit rejection')
        self.client.before = reject
        with self.assertRaises(SheetsError):
            self.sync()
        self.assertEqual(len(self.client.values(RUNS)), 1)
        self.assertEqual(len(self.client.values(EVENT_MAP)), 1)
        self.client.before = None
        result = self.sync()
        self.assertEqual(result.events, 1)
        self.assertEqual(len(self.client.values(RUNS)), 2)

    def test_lost_success_response_reconciles_without_duplicate(self):
        self.client.lose_commit_response = True
        result = self.sync()
        self.assertTrue(result.already_synced)
        self.assertEqual(len(self.client.values(RUNS)), 2)
        self.sync()
        self.assertEqual(len(self.client.values(RUNS)), 2)

    def test_failed_run_has_index_but_no_snapshot(self):
        result = self.sync(result=CanonicalizationResult(), status='failed', failures=('source_a:failed',))
        self.assertEqual(result.status, 'failed')
        self.assertEqual(result.event_tab, '')
        self.assertEqual(len(self.client.values(RUNS)), 2)

    def test_identity_mapping_updates_last_seen_without_duplicate(self):
        first = canonicalize([context()])
        self.sync(result=first)
        expanded = canonicalize([context(), context('b', seen=STAMP)])
        self.sync('run_two', expanded)
        rows = self.client.values(EVENT_MAP)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][0], first.events[0].event_id)
        self.assertEqual(rows[1][-2:], ['run_one', 'run_two'])

    def test_anchor_mismatch_is_rejected(self):
        self.sync()
        self.client.edit(EVENT_MAP, 1, 1, 'another_anchor')
        with self.assertRaises(SheetsError):
            self.sync('run_two')

    def test_duplicate_queue_preserves_human_cells(self):
        a, b = context(), context('b', publisher='other', start_time=None, starts_at=None, date_precision=DatePrecision.DAY)
        result = canonicalize([a, b])
        # Explicit possible relationship uses real stable canonical identities.
        result = replace(result, possible_duplicates=(DuplicateDecision(
            (a.candidate_id, b.candidate_id), MatchKind.POSSIBLE_DUPLICATE, ('missing_time',)),))
        self.assertEqual(len(result.events), 2)
        self.sync(result=result)
        self.client.edit(DUPLICATES, 1, 0, 'جدا هستند')
        self.client.edit(DUPLICATES, 1, 8, 'keep this note')
        self.sync('run_two', result)
        rows = self.client.values(DUPLICATES)
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows[1][0], rows[1][8], rows[1][13]), ('جدا هستند', 'keep this note', 'run_two'))

    def test_distinct_pairs_are_not_queued(self):
        a, b = context(), context('b', title='Unrelated Star Festival')
        result = canonicalize([a, b])
        self.sync(result=result)
        self.assertEqual(len(self.client.values(DUPLICATES)), 1)

    def test_pending_creation_requires_reconciliation(self):
        self.state.save({'creation_pending': True})
        repo = SheetRepository(self.client, self.state)
        with self.assertRaises(SheetsError):
            repo.setup()
        self.assertEqual(self.client.created, 1)
