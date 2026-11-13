import unittest
from datetime import date, time

from gatherradar.deduplication import MatchKind, match_pair
from gatherradar.deduplication.keys import text_key, title_relation, registration_key
from gatherradar.domain.temporal import DatePrecision
from gatherradar.normalization.models import Diagnostic
from deduplication_fakes import context


class TextMatchingTests(unittest.TestCase):
    def test_persian_arabic_digits_letters_punctuation(self):
        self.assertEqual(text_key('كارگاهِ «سراميک ۱۲»'), text_key('کارگاه سرامیک 12'))

    def test_english_case_unicode_whitespace(self):
        self.assertEqual(text_key('ＭＯＯＮ Light—Ceramics\nWorkshop'), text_key('moon light ceramics workshop'))

    def test_generic_words_are_weak(self):
        for a, b in [('workshop', 'workshop'), ('رویداد', 'رویداد'), ('ایونت', 'ایونت'), ('event 12', 'event 12'), ('', None)]:
            self.assertEqual(title_relation(a, b), 'weak')

    def test_generic_overlap_is_not_distinctive(self):
        self.assertEqual(title_relation('Moonlight workshop', 'River workshop'), 'different')

    def test_multiword_distinctive_overlap(self):
        self.assertEqual(title_relation('the moonlight ceramic workshop', 'Moonlight Ceramic event'), 'strong')

    def test_short_shared_word_is_only_partial(self):
        self.assertEqual(title_relation('Moonlight painting', 'Moonlight pottery'), 'partial')

    def test_changed_edition_number_is_not_fuzzy_match(self):
        self.assertEqual(title_relation('Moonlight ceramic workshop ۱', 'Moonlight ceramic workshop 2'), 'different')

    def test_registration_tracking_only(self):
        self.assertEqual(registration_key('https://tickets.test/event/1?id=2&utm_source=x'),
                         'https://tickets.test/event/1?id=2')
        self.assertNotEqual(registration_key('https://tickets.test/event/1?id=2'),
                            registration_key('https://tickets.test/event/1?id=3'))
        self.assertEqual(registration_key('https://tickets.test/e?id=2&&slot=3'), 'https://tickets.test/e?id=2&&slot=3')

    def test_registration_homepages_invalid_and_opaque_parts(self):
        for url in ['https://tickets.test/', 'https://tickets.test/?utm_source=x', 'javascript:x',
                    'https://user:secret@tickets.test/event/1', 'https://tickets.test:bad/event/1']:
            self.assertIsNone(registration_key(url))
        self.assertIsNone(registration_key('https://publisher.test/app/events', ('https://publisher.test/app/events',)))
        self.assertIsNone(registration_key('https://publisher.test/app/events', ('https://PUBLISHER.test/app/events?utm_source=home',)))
        self.assertNotEqual(registration_key('https://tickets.test/e/1#one'), registration_key('https://tickets.test/e/1#two'))


class PairMatchingTests(unittest.TestCase):
    def assertKind(self, kind, a=None, b=None):
        a, b = a or context('a'), b or context('b')
        decision = match_pair(a, b)
        self.assertEqual(decision.kind, kind, decision.reasons)
        self.assertEqual(decision, match_pair(b, a))
        self.assertTrue(decision.reasons)
        return decision

    def test_exact_same_publisher(self):
        self.assertKind(MatchKind.SAME_EVENT)

    def test_cross_publisher_requires_occurrence_and_location(self):
        self.assertKind(MatchKind.SAME_EVENT, b=context('b', publisher='other'))

    def test_cross_publisher_missing_location_possible(self):
        self.assertKind(MatchKind.POSSIBLE_DUPLICATE, b=context('b', publisher='other', venue_name=None, city=None))

    def test_cross_publisher_date_only_possible(self):
        self.assertKind(MatchKind.POSSIBLE_DUPLICATE,
                        b=context('b', publisher='other', start_time=None, starts_at=None, date_precision=DatePrecision.DAY))

    def test_same_publisher_date_only_can_group(self):
        self.assertKind(MatchKind.SAME_EVENT, b=context('b', start_time=None, starts_at=None, date_precision=DatePrecision.DAY))

    def test_same_publisher_alone_insufficient(self):
        self.assertKind(MatchKind.INSUFFICIENT,
                        a=context('a', title=None, start_date=None, starts_at=None),
                        b=context('b', title=None, start_date=None, starts_at=None))

    def test_date_conflict_overrides_title_registration_publisher(self):
        self.assertKind(MatchKind.DISTINCT, b=context('b', start_date=date(2026, 10, 2), starts_at=None))

    def test_city_conflict(self):
        self.assertKind(MatchKind.DISTINCT, b=context('b', city='Shiraz'))

    def test_venue_conflict(self):
        self.assertKind(MatchKind.DISTINCT, b=context('b', venue_name='Red Gallery'))

    def test_address_conflict(self):
        self.assertKind(MatchKind.DISTINCT, a=context('a', address='First Street'), b=context('b', address='Second Street'))

    def test_time_conflict(self):
        self.assertKind(MatchKind.DISTINCT, b=context('b', start_time=time(20), starts_at=None))

    def test_end_time_conflict(self):
        self.assertKind(MatchKind.DISTINCT, a=context('a', end_time=time(20)), b=context('b', end_time=time(21)))

    def test_timezone_conflict(self):
        self.assertKind(MatchKind.DISTINCT, b=context('b', timezone='Asia/Tehran', starts_at=None))

    def test_title_conflict(self):
        self.assertKind(MatchKind.DISTINCT, b=context('b', title='River Jazz Concert'))

    def test_missing_values_neutral(self):
        self.assertKind(MatchKind.SAME_EVENT, b=context('b', venue_name=None, address=None, city=None, registration_url=None))

    def test_inferred_dates_cannot_auto_group(self):
        self.assertKind(MatchKind.POSSIBLE_DUPLICATE, b=context('b', date_precision=DatePrecision.INFERRED))

    def test_range_inferred_diagnostic_blocks_auto_group(self):
        self.assertKind(MatchKind.POSSIBLE_DUPLICATE, b=context('b', date_precision=DatePrecision.RANGE,
                        diagnostics=(Diagnostic('inferred_year', 'source_date_text', 'review'),)))

    def test_uncertain_conflicting_date_is_not_strong_distinct(self):
        self.assertKind(MatchKind.POSSIBLE_DUPLICATE, b=context('b', start_date=date(2027, 10, 1),
                        starts_at=None, date_precision=DatePrecision.INFERRED))

    def test_recurrence_and_multiple_sessions_never_auto_group(self):
        for code in ('recurring_schedule', 'multiple_dates', 'unparsed_temporal', 'relative_date', 'ambiguous_overnight'):
            self.assertKind(MatchKind.POSSIBLE_DUPLICATE,
                            b=context('b', diagnostics=(Diagnostic(code, 'source_date_text', 'review'),)))

    def test_multiday_ranges_remain_review_only(self):
        self.assertKind(MatchKind.POSSIBLE_DUPLICATE, b=context('b', end_date=date(2026, 10, 3),
                        starts_at=None, date_precision=DatePrecision.RANGE))

    def test_registration_corroborates_cross_publisher(self):
        self.assertKind(MatchKind.SAME_EVENT,
                        a=context('a', registration_url='https://tickets.test/e/1?utm_source=a'),
                        b=context('b', publisher='other', venue_name=None, registration_url='https://tickets.test/e/1'))

    def test_different_registration_vendors_are_not_veto(self):
        self.assertKind(MatchKind.SAME_EVENT,
                        a=context('a', registration_url='https://one.test/e/1'),
                        b=context('b', registration_url='https://two.test/ticket/2'))

    def test_generic_title_cannot_auto_merge(self):
        self.assertKind(MatchKind.POSSIBLE_DUPLICATE, a=context('a', title='workshop'), b=context('b', title='workshop'))

    def test_missing_title_date_location_is_possible(self):
        self.assertKind(MatchKind.POSSIBLE_DUPLICATE, b=context('b', title=None))

    def test_price_diagnostics_do_not_weaken_occurrence(self):
        self.assertKind(MatchKind.SAME_EVENT, b=context('b', diagnostics=(Diagnostic('missing_price', 'price_text', 'review'),)))
