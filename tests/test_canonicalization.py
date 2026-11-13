import itertools
import unittest
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

from gatherradar.deduplication import canonicalize, MatchKind
from gatherradar.deduplication.resolution import resolve_group
from gatherradar.domain import PlaceCandidate, ReviewStatus
from gatherradar.domain.temporal import DatePrecision
from gatherradar.normalization.models import NormalizationOutcome, Diagnostic
from deduplication_fakes import context, changed, STAMP


class GroupingTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(canonicalize(()).events, ())

    def test_pair_and_singleton(self):
        result = canonicalize((context('a'), context('b'), context('c', city='Shiraz')))
        self.assertEqual(len(result.groups), 1)
        self.assertEqual(len(result.singletons), 1)
        self.assertEqual(len(result.contexts), 3)

    def test_three_compatible(self):
        result = canonicalize(context(c) for c in 'abc')
        self.assertEqual(len(result.groups[0].candidate_ids), 3)
        self.assertEqual(len(result.events), 1)

    def test_possible_remains_separate(self):
        result = canonicalize((context('a'), context('b', date_precision=DatePrecision.INFERRED)))
        self.assertEqual(len(result.events), 2)
        self.assertEqual(len(result.possible_duplicates), 1)

    def test_bridge_does_not_overmerge_and_blocked_edge_is_visible(self):
        inputs = (context('a', city='Tehran'), context('b', city=None), context('c', city='Shiraz'))
        result = canonicalize(inputs)
        self.assertEqual([d.kind for d in result.decisions], [MatchKind.SAME_EVENT, MatchKind.DISTINCT, MatchKind.SAME_EVENT])
        self.assertEqual(len(result.events), 2)
        self.assertEqual(len(result.groups[0].candidate_ids), 2)
        self.assertIn('all_member_grouping_blocked', result.possible_duplicates[0].reasons)
        self.assertEqual(sum(len(e.candidate_ids) for e in result.events), 3)
        for permutation in itertools.permutations(inputs):
            self.assertEqual(result, canonicalize(permutation))

    def test_inferred_chain_no_group(self):
        inputs = (context('a'), context('b', date_precision=DatePrecision.INFERRED), context('c', title=None))
        self.assertFalse(canonicalize(inputs).groups)

    def test_pair_exception_isolated(self):
        from gatherradar.deduplication.matcher import match_pair
        def matcher(a, b):
            if a.candidate_id == 'candidate:a':
                raise RuntimeError('private secret')
            return match_pair(a, b)
        with patch('gatherradar.deduplication.service.match_pair', side_effect=matcher):
            result = canonicalize(context(c) for c in 'abc')
        self.assertEqual(len(result.events), 2)
        self.assertNotIn('private secret', repr(result))
        self.assertTrue(result.diagnostics)

    def test_resolution_exception_does_not_destroy_other_groups(self):
        from gatherradar.deduplication.resolution import resolve_group
        def resolver(members, gid):
            if members[0].candidate_id == 'candidate:a':
                raise RuntimeError('private secret')
            return resolve_group(members, gid)
        with patch('gatherradar.deduplication.service.resolve_group', side_effect=resolver):
            result = canonicalize((context('a'), context('b', city='Shiraz')))
        self.assertEqual(len(result.events), 1)
        self.assertEqual(len(result.rejected), 1)
        self.assertNotIn('private secret', repr(result.diagnostics))

    def test_bad_candidate_isolated(self):
        result = canonicalize((context('a', start_date='not-a-date'), context('b')))
        self.assertEqual(len(result.events), 1)
        self.assertEqual(len(result.rejected), 1)

    def test_wrong_context_and_unnormalized_input_rejected(self):
        a = context('a')
        for bad in (replace(a, raw_item=replace(a.raw_item, source_id='wrong')),
                    replace(a, outcome=NormalizationOutcome(a.candidate)),
                    replace(a, outcome=NormalizationOutcome(None)),
                    replace(a, first_seen_at=datetime(2026, 9, 1)),
                    changed(a, starts_at=datetime(2020, 1, 1, tzinfo=timezone.utc)),
                    changed(a, price_amount=Decimal('NaN')),
                    changed(a, evidence_url='https://user:secret@example.test/event'),
                    changed(a, date_precision=DatePrecision.RANGE)):
            self.assertEqual(len(canonicalize((bad, context('b'))).rejected), 1)

    def test_duplicate_candidate_ids_are_quarantined(self):
        a = context('a')
        result = canonicalize((a, a, context('b')))
        self.assertEqual(len(result.rejected), 2)
        self.assertEqual(len(result.events), 1)

    def test_place_passthrough(self):
        a = context('a')
        place = PlaceCandidate('place:1', a.raw_item.id, title='Gallery')
        a = replace(a, outcome=NormalizationOutcome(place), original=place)
        result = canonicalize((a, context('b')))
        self.assertIs(result.places[0], place)
        self.assertEqual(len(result.events), 1)
        self.assertEqual(result.decisions, ())


class IdentityTests(unittest.TestCase):
    def test_later_support_changes_group_not_event_id(self):
        a, b = context('a'), context('b', seen=STAMP + timedelta(days=1))
        first, = canonicalize((a,)).events
        second, = canonicalize((b, a)).events
        self.assertEqual(first.event_id, second.event_id)
        self.assertNotEqual(first.duplicate_group_id, second.duplicate_group_id)
        self.assertEqual(second.identity_anchor_raw_item_id, a.raw_item.id)

    def test_edited_candidate_same_raw_anchor(self):
        a = context('a')
        edited = changed(a, candidate_id='candidate:edited')
        edited = replace(edited, original=replace(a.original, candidate_id='candidate:edited'),
                         raw_item=replace(a.raw_item, captured_at=STAMP + timedelta(days=5), content_hash='new'))
        self.assertEqual(canonicalize((a,)).events[0].event_id, canonicalize((edited,)).events[0].event_id)
        self.assertEqual(canonicalize((edited,)).events[0].first_seen_at, STAMP)

    def test_tie_break_uses_raw_id_not_candidate_order(self):
        a, b = context('a'), context('b')
        result, = canonicalize((b, a)).events
        self.assertEqual(result.identity_anchor_raw_item_id, 'raw:a')

    def test_earlier_raw_anchor_wins_over_lexicographic_candidate(self):
        result, = canonicalize((context('a', seen=STAMP + timedelta(days=1)), context('z'))).events
        self.assertEqual(result.identity_anchor_raw_item_id, 'raw:z')

    def test_multiple_units_same_raw_have_distinct_ids(self):
        a, b = context('a'), context('b', city='Shiraz', slot='carousel_slide_ocr:1')
        b = replace(b, raw_item=a.raw_item, source=a.source, original=replace(b.original, raw_item_id=a.raw_item.id))
        b = changed(b, raw_item_id=a.raw_item.id)
        result = canonicalize((a, b))
        self.assertEqual(len(result.events), 2)
        self.assertEqual(len({e.event_id for e in result.events}), 2)

    def test_ambiguous_same_raw_slot_quarantined(self):
        a, b = context('a'), context('b')
        b = replace(b, raw_item=a.raw_item, source=a.source, original=replace(b.original, raw_item_id=a.raw_item.id))
        result = canonicalize((a, changed(b, raw_item_id=a.raw_item.id)))
        self.assertEqual(len(result.rejected), 2)
        self.assertFalse(result.events)


class ResolutionTests(unittest.TestCase):
    def resolve(self, *members):
        return resolve_group(members, 'duplicate:test')

    def test_agreement_provenance_membership_review(self):
        a, b = context('a'), context('b')
        event = self.resolve(b, a)
        self.assertEqual(event.title, a.candidate.title)
        self.assertEqual(event.review_status, ReviewStatus.NEEDS_REVIEW)
        self.assertEqual(dict((p.field, p.candidate_ids) for p in event.field_provenance)['title'], ('candidate:a', 'candidate:b'))
        self.assertEqual(event.source_item_ids, ('raw:a', 'raw:b'))
        self.assertEqual(event.publisher_keys, ('publisher',))

    def test_extraction_confidence_is_preserved_not_recalibrated(self):
        event = self.resolve(context('a', extraction_confidence=0.8))
        self.assertEqual(event.extraction_confidence, 0.8)
        event = self.resolve(context('a', extraction_confidence=0.8), context('b', extraction_confidence=0.9))
        self.assertIsNone(event.extraction_confidence)
        self.assertIn(('field_conflict', 'extraction_confidence'), [(d.code, d.field) for d in event.diagnostics])

    def test_value_plus_null(self):
        event = self.resolve(context('a', address='Street Y'), context('b', title=None, venue_name=None))
        self.assertEqual(event.address, 'Street Y')
        self.assertEqual(event.venue_name, 'Blue Gallery')
        self.assertEqual(event.title, 'Moonlight Ceramic Workshop')

    def test_equal_conflict_remains_unresolved(self):
        event = self.resolve(context('a', summary='One description'), context('b', summary='Another description'))
        self.assertIsNone(event.summary)
        self.assertIn(('field_conflict', 'summary'), [(d.code, d.field) for d in event.diagnostics])

    def test_unknown_title_remains_null(self):
        event = self.resolve(context('a', title=None))
        self.assertIsNone(event.title)
        self.assertIn('missing_canonical_title', [d.code for d in event.diagnostics])

    def test_folded_agreement_selects_original_not_folded(self):
        event = self.resolve(context('a', title='Moonlight—Ceramic WORKSHOP'), context('b'))
        self.assertEqual(event.title, 'Moonlight—Ceramic WORKSHOP')

    def test_explicit_wins_over_inferred_with_diagnostic(self):
        event = self.resolve(context('a', start_date=date(2027, 10, 1), starts_at=None, date_precision=DatePrecision.INFERRED), context('b'))
        self.assertEqual(event.start_date, date(2026, 10, 1))
        self.assertEqual(event.date_precision, DatePrecision.EXACT)
        self.assertIn('stronger_explicit_temporal_selected', [d.code for d in event.diagnostics])

    def test_equal_temporal_conflict_unresolved(self):
        event = self.resolve(context('a'), context('b', start_date=date(2026, 10, 2), starts_at=None))
        self.assertIsNone(event.start_date)
        self.assertIsNone(event.starts_at)
        self.assertEqual(event.date_precision, DatePrecision.UNKNOWN)

    def test_precision_inferred_range_and_original_wording_preserved(self):
        a = context('a', source_date_text='۲ مهر', price_text='۳۰۰ تومان', date_precision=DatePrecision.INFERRED,
                    diagnostics=(Diagnostic('inferred_year', 'source_date_text', 'review'),))
        event = self.resolve(a)
        self.assertEqual(event.date_precision, DatePrecision.INFERRED)
        self.assertEqual(event.source_date_text, '۲ مهر')
        self.assertEqual(event.price_text, '۳۰۰ تومان')
        self.assertIn('normalization:inferred_year', [d.code for d in event.diagnostics])

    def test_decimal_and_currency(self):
        for currency in ('TOMAN', 'IRR', 'USD'):
            event = self.resolve(context('a', price_amount=Decimal('300.50'), currency=currency))
            self.assertEqual(event.price_amount, Decimal('300.50'))
            self.assertEqual(event.currency, currency)

    def test_price_units_not_silently_converted(self):
        event = self.resolve(context('a', price_amount=Decimal(300), currency='TOMAN'),
                             context('b', price_amount=Decimal(300), currency='IRR'))
        self.assertIsNone(event.price_amount)
        self.assertIsNone(event.currency)
        self.assertIn(('field_conflict', 'price'), [(d.code, d.field) for d in event.diagnostics])

    def test_no_amount_currency_synthesis(self):
        event = self.resolve(context('a', price_amount=Decimal(0)), context('b', currency='TOMAN'))
        self.assertIsNone(event.price_amount)
        self.assertIsNone(event.currency)

    def test_no_new_timestamp_from_complementary_fields(self):
        event = self.resolve(context('a', start_time=None, starts_at=None, date_precision=DatePrecision.DAY),
                             context('b', start_date=None, starts_at=None, date_precision=DatePrecision.UNKNOWN))
        self.assertIsNone(event.starts_at)
        self.assertIn('partial_temporal_not_combined', [d.code for d in event.diagnostics])

    def test_url_anchor_and_fallback_are_source_supported(self):
        a, b = context('a', evidence_url=None), context('b')
        event = self.resolve(b, a)
        self.assertEqual(event.canonical_source_url, a.raw_item.content_url)
        self.assertEqual(event, self.resolve(a, b))

    def test_domain_rejects_naive_timestamps(self):
        event = self.resolve(context('a'))
        for field in ('first_seen_at', 'last_seen_at', 'starts_at', 'ends_at'):
            with self.assertRaises(ValueError):
                replace(event, **{field: datetime(2026, 9, 1)})

    def test_domain_timezone_has_no_tehran_default(self):
        from gatherradar.domain import Event
        event = Event('event:unknown', None, 'https://example.test/e/1', STAMP, STAMP)
        self.assertIsNone(event.timezone)
        self.assertIsNone(event.title)
