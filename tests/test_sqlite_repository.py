import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import timedelta

from gatherradar.review.models import ReviewError
from gatherradar.review.schema import DECISIONS, DUPLICATE_DECISIONS
from gatherradar.storage.sqlite_repository import SqliteCanonicalRepository
from local_review_fakes import LocalCase


class SqliteTests(LocalCase):
    def test_schema_and_pragmas(self):
        for pragma, expected in [('user_version', 1), ('foreign_keys', 1), ('busy_timeout', 5000), ('journal_mode', 'wal')]:
            self.assertEqual(self.repo.connection.execute('PRAGMA ' + pragma).fetchone()[0], expected)

    def test_reopen_is_noop(self):
        self.persist()
        with SqliteCanonicalRepository(self.repo.path) as other:
            self.assertEqual(other.load(), self.repo.load())

    def test_newer_version_refused_without_deleting_data(self):
        path = self.root / 'new.sqlite3'
        with closing(sqlite3.connect(path)) as connection:
            connection.execute('CREATE TABLE owner(value)')
            connection.execute('INSERT INTO owner VALUES (42)')
            connection.execute('PRAGMA user_version=99')
            connection.commit()
        with self.assertRaises(ReviewError):
            SqliteCanonicalRepository(path)
        with closing(sqlite3.connect(path)) as connection:
            self.assertEqual(connection.execute('SELECT value FROM owner').fetchone()[0], 42)
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], 99)

    def test_unversioned_existing_tables_refused(self):
        path = self.root / 'unknown.sqlite3'
        with closing(sqlite3.connect(path)) as connection:
            connection.execute('CREATE TABLE owner(value)')
        with self.assertRaises(ReviewError):
            SqliteCanonicalRepository(path)

    def test_foreign_key_rejects_orphan(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.connection.execute("INSERT INTO event_review VALUES ('missing','x','','now')")

    def test_idempotency_has_constraints_and_no_duplicate_rows(self):
        self.persist()
        self.assertTrue(self.persist().already_synced)
        for table, expected in [('runs',1), ('events',2), ('event_snapshots',2), ('duplicate_review',1), ('place_snapshots',1)]:
            self.assertEqual(self.repo.connection.execute('SELECT count(*) FROM ' + table).fetchone()[0], expected)
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.connection.execute('INSERT INTO event_snapshots SELECT * FROM event_snapshots')

    def test_history_and_current_state_are_separate(self):
        self.persist()
        changed = replace(self.result, events=(replace(self.result.events[0], title='عنوان تازه'), self.result.events[1]))
        self.persist('two', changed, 1)
        self.assertEqual(self.repo.load('one')['events'][0]['title'], 'کارگاه مهتاب')
        self.assertEqual({e['title'] for e in self.repo.load('two')['events']}, {'عنوان تازه', 'کارگاه مهتاب'})
        self.assertEqual(self.repo.connection.execute('SELECT count(*) FROM events').fetchone()[0], 2)

    def test_new_support_keeps_identity_and_review(self):
        self.persist()
        event = self.result.events[0]
        token = self.repo.review_token('event', event.event_id, 'one')
        self.repo.import_review(token, 'event', event.event_id, 'one', DECISIONS[2], 'یادداشت')
        changed = replace(event, source_ids=event.source_ids + ('later_source',))
        self.persist('two', replace(self.result, events=(changed, self.result.events[1])), 1)
        item = next(e for e in self.repo.load('two')['events'] if e['event_id'] == event.event_id)
        self.assertEqual((item['review_decision'], item['review_notes']), (DECISIONS[2], 'یادداشت'))
        self.assertEqual(self.repo.connection.execute('SELECT count(*) FROM event_identity_map').fetchone()[0], 2)

    def test_anchor_conflict_rolls_back_entire_batch(self):
        self.persist()
        bad = replace(self.result.events[1], identity_anchor_slot='different')
        with self.assertRaises(ReviewError):
            self.persist('bad', replace(self.result, events=(replace(self.result.events[0], title='changed'), bad)), 1)
        self.assertIsNone(self.repo.find_run('bad'))
        self.assertEqual(self.repo.connection.execute('SELECT count(*) FROM event_snapshots').fetchone()[0], 2)
        self.assertNotIn('changed', [json.loads(r[0])['title'] for r in self.repo.connection.execute('SELECT payload FROM events')])

    def test_place_review_is_run_scoped(self):
        self.persist()
        key = self.result.places[0].candidate_id
        token = self.repo.review_token('place', key, 'one')
        self.assertEqual(self.repo.import_review(token, 'place', key, 'one', DECISIONS[1], 'place'), 'imported')
        self.persist('two', delta=1)
        self.assertEqual(self.repo.load('one')['places'][0]['review_notes'], 'place')
        self.assertEqual(self.repo.load('two')['places'][0]['review_notes'], '')

    def test_duplicate_review_persists_without_merging(self):
        self.persist()
        key = self.repo.load()['possible_duplicates'][0]['pair_key']
        token = self.repo.review_token('duplicate', key, 'one')
        self.repo.import_review(token, 'duplicate', key, 'one', DUPLICATE_DECISIONS[1], 'same')
        self.persist('two', delta=1)
        self.assertEqual(self.repo.load()['possible_duplicates'][0]['review_notes'], 'same')
        self.assertEqual(len(self.repo.load()['events']), 2)
        self.assertEqual(self.repo.duplicate_queue()[0]['first_seen_run'], 'one')

    def test_filtered_events_persist_but_are_not_exported(self):
        self.persist()
        self.persist('later', delta=90*86400)
        self.assertEqual(self.repo.load('later')['events'], [])
        self.assertEqual(self.repo.load('later')['run']['canonical_event_count'], 2)
        self.assertEqual(len(self.repo.load('one')['events']), 2)

    def test_invalid_review_unknown_id_and_title_collision(self):
        self.persist()
        key = self.result.events[0].event_id
        token = self.repo.review_token('event', key, 'one')
        self.assertEqual(self.repo.import_review(token, 'event', key, 'one', 'invalid', ''), 'malformed')
        self.assertEqual(self.repo.import_review(token, 'event', 'unknown', 'one', DECISIONS[1], ''), 'malformed')
        self.assertEqual(self.repo.import_review(token, 'event', self.result.events[1].event_id, 'one', DECISIONS[1], ''), 'malformed')

    def test_stale_review_conflict_and_unchanged_baseline(self):
        self.persist()
        key = self.result.events[0].event_id
        token = self.repo.review_token('event', key, 'one')
        self.repo.import_review(token, 'event', key, 'one', DECISIONS[1], 'new')
        self.assertEqual(self.repo.import_review(token, 'event', key, 'one', DECISIONS[0], ''), 'skipped')
        self.assertEqual(self.repo.import_review(token, 'event', key, 'one', DECISIONS[2], 'old file'), 'conflict')

    def test_no_raw_contexts_in_persistence(self):
        self.persist()
        serialized = json.dumps(self.repo.load(), ensure_ascii=False)
        for key in ('raw_text', 'raw_metadata', 'raw_ocr', 'cookies', 'credentials'):
            self.assertNotIn(key, serialized)

    def test_path_traversal_and_invalid_context_rejected(self):
        for run_id in ('../escape', '', 'x/y'):
            with self.subTest(run_id=run_id), self.assertRaises(ReviewError):
                self.persist(run_id)

    def test_empty_database_load_has_actionable_error(self):
        with self.assertRaisesRegex(ReviewError, 'No persisted runs'):
            self.repo.load()
