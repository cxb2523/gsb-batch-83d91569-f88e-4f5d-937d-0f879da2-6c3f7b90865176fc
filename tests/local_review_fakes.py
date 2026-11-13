"""Small synthetic canonical records; no raw runtime captures."""
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import ExitStack
from unittest import TestCase
from unittest.mock import patch

from gatherradar.deduplication import canonicalize
from gatherradar.deduplication.models import CanonicalizationResult, DuplicateDecision, MatchKind
from gatherradar.domain import PlaceCandidate
from gatherradar.review.serialization import review_window
from gatherradar.storage.sqlite_repository import SqliteCanonicalRepository
from deduplication_fakes import context

STAMP = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)


def sample():
    a = canonicalize((context('a', title='کارگاه مهتاب'),)).events[0]
    b = canonicalize((context('b', title='کارگاه مهتاب'),)).events[0]
    place = PlaceCandidate('place:one', 'raw:place', title='گالری آبی', evidence_url='https://example.test/place')
    pair = DuplicateDecision((a.candidate_ids[0], b.candidate_ids[0]), MatchKind.POSSIBLE_DUPLICATE, ('title_similarity_only',))
    return CanonicalizationResult(events=(a, b), places=(place,), possible_duplicates=(pair,))


class LocalCase(TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(TemporaryDirectory()))
        for target in ('socket.socket.connect', 'socket.create_connection', 'subprocess.Popen', 'webbrowser.open'):
            self.stack.enter_context(patch(target, side_effect=AssertionError('unexpected external operation')))
        self.repo = self.stack.enter_context(SqliteCanonicalRepository(self.root / 'state/db.sqlite3'))
        self.book = self.root / 'review/GatherRadar.xlsx'
        self.result = sample()

    def persist(self, run_id='one', result=None, delta=0):
        result = result or self.result
        stamp = STAMP + timedelta(seconds=delta)
        return self.repo.sync(result, review_window(result.events, stamp), run_id=run_id,
            started_at=stamp, finished_at=stamp, days=14, review_timezone='Asia/Tehran', source_count=2)
