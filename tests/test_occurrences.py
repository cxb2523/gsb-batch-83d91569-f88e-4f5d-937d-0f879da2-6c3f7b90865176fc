import unittest
from dataclasses import replace
from datetime import date, datetime, time, timezone
from decimal import Decimal

from gatherradar.deduplication import CandidateContext, canonicalize
from gatherradar.deduplication.matcher import match_pair
from gatherradar.deduplication.resolution import resolve_group
from gatherradar.domain import EventCandidate, ScheduleKind
from gatherradar.domain.occurrence import identify_occurrence
from gatherradar.domain.website import SourceSession
from gatherradar.normalization import NormalizationService, normalize_temporal
from test_normalization_temporal import RAW, SOURCE, codes


def normalized(text=None, *, schedule=None, raw=RAW, **kwargs):
    candidate = EventCandidate("candidate:occurrence", raw.id, True, title="کارگاه سفال ماه",
                               source_date_text=text, source_schedule_text=schedule,
                               evidence_url=raw.content_url, evidence_fragment_ids=("evidence:1",),
                               **kwargs)
    return NormalizationService().normalize(candidate, raw, SOURCE)


def canonical(outcome, *, raw=RAW):
    context = CandidateContext(outcome, outcome.candidate, raw, SOURCE, raw.captured_at)
    result = canonicalize((context,))
    assert not result.rejected, result.diagnostics
    return result.events[0]


def session(key="1", *, start="2026-10-01T14:30:00Z", **kwargs):
    return SourceSession(key, "event1", start, "react-router:loaderData/routes/events.$id/sessions/0", **kwargs)


class OccurrenceTests(unittest.TestCase):
    def test_time_after_dash_and_punctuation(self):
        for text in ("پنجشنبه ۳۰ مهر - ساعت ۱۹", "جمعه ۱ آبان – ساعت ۲۱",
                     "۳۰ مهر ۱۴۰۵ — ساعت ۱۹:۳۰", "۳۰ مهر ۱۴۰۵،\nساعت ۱۹",
                     "دوشنبه ۲۷ مهر | ساعت ۱۷"):
            with self.subTest(text=text):
                result = normalize_temporal(text, RAW, SOURCE)
                self.assertIsNotNone(result.start_time)
                self.assertNotIn("unparsed_temporal", codes(result))
                self.assertEqual(len(result.occurrences), 1)

    def test_discrete_dates_are_distinct_and_no_arbitrary_primary(self):
        result = normalized("۹ و ۱۰ مهرماه")
        self.assertEqual(result.candidate.schedule_kind, ScheduleKind.DISCRETE)
        self.assertIsNone(result.candidate.start_date)
        self.assertIsNone(result.candidate.starts_at)
        self.assertEqual([o.start_date for o in result.candidate.occurrences],
                         [date(2026, 10, 1), date(2026, 10, 2)])
        self.assertEqual(len({o.occurrence_id for o in result.candidate.occurrences}), 2)
        self.assertIn("inferred_year", codes(result))
        for value in result.candidate.occurrences:
            self.assertEqual(value.source_schedule_text, "۹ و ۱۰ مهرماه")
            self.assertEqual(value.evidence_fragment_ids, ("evidence:1",))
            self.assertEqual(value.source_item_ids, (RAW.id,))

    def test_multiple_sessions_share_only_explicit_clock(self):
        result = normalized("۵، ۱۲، ۱۹ و ۲۶ مهر ۱۴۰۵ ساعت ۱۶ تا ۱۹")
        self.assertEqual(len(result.candidate.occurrences), 4)
        self.assertTrue(all(o.start_time == time(16) and o.end_time == time(19)
                            and o.starts_at is not None for o in result.candidate.occurrences))
        self.assertIsNone(result.candidate.start_date)

    def test_ordinal_discrete_dates(self):
        result = normalized("بیست و یکم و بیست و دوم مهر ۱۴۰۵")
        self.assertEqual([o.start_date for o in result.candidate.occurrences],
                         [date(2026, 10, 13), date(2026, 10, 14)])

    def test_discrete_year_inference_requires_every_day_near_reference(self):
        result = normalized("۱ و ۳۰ آبان")
        self.assertFalse(result.candidate.occurrences)
        self.assertIn("missing_year", codes(result))

    def test_discrete_before_nowruz_infers_one_year(self):
        raw = replace(RAW, captured_at=datetime(2026, 3, 20, tzinfo=timezone.utc))
        result = normalized("۱ و ۲ فروردین", raw=raw)
        self.assertEqual([o.start_date for o in result.candidate.occurrences],
                         [date(2026, 3, 21), date(2026, 3, 22)])

    def test_invalid_discrete_day_abstains(self):
        result = normalized("۳۰ و ۳۱ مهر ۱۴۰۵")
        self.assertFalse(result.candidate.occurrences)
        self.assertIn("invalid_date", codes(result))

    def test_range_has_bounds_and_never_continuous_attendance(self):
        result = normalized("یکم تا سوم مهرماه ۱۴۰۵ از ساعت ۱۶ تا ۲۲")
        value, = result.candidate.occurrences
        self.assertEqual(result.candidate.schedule_kind, ScheduleKind.RANGE)
        self.assertEqual(value.end_date, date(2026, 9, 25))
        self.assertIsNone(value.starts_at)
        self.assertIsNone(value.ends_at)
        self.assertIn("multi_day_hours", codes(result))

    def test_weekly_wording_gets_rule_without_fabricated_dates(self):
        for text, weekday, start in (("جمعه‌ها ساعت ۱۶ تا ۱۹", "FR", time(16)),
                                     ("سه‌شنبه‌ها از ساعت ۱۰ تا ۱۳", "TU", time(10)),
                                     ("شنبه‌ها ساعت ۲۱", "SA", time(21))):
            with self.subTest(text=text):
                result = normalized(schedule=text)
                self.assertEqual(result.candidate.recurrence_rule, "FREQ=WEEKLY;BYDAY=" + weekday)
                self.assertEqual(result.candidate.schedule_kind, ScheduleKind.RECURRING)
                self.assertFalse(result.candidate.occurrences)
                self.assertIsNone(result.candidate.start_date)
                self.assertEqual(result.candidate.start_time, start)

    def test_daily_schedule_retains_known_clock_without_fabricating_date(self):
        result = normalized("ساعت ۲۱:۰۰", schedule="📅 هر شب ساعت ۲۱:۰۰")
        self.assertEqual(result.candidate.start_time, time(21))
        self.assertEqual(result.candidate.recurrence_rule, "FREQ=DAILY")
        self.assertEqual(result.candidate.schedule_kind, ScheduleKind.RECURRING)
        self.assertIsNone(result.candidate.start_date)
        self.assertFalse(result.candidate.occurrences)

    def test_explicit_two_clocks_on_one_date_are_separate_sessions(self):
        result = normalized("۲۴ مهرماه", schedule="در دو سانس ۱۷ و ۲۰")
        self.assertEqual([o.start_time for o in result.candidate.occurrences], [time(17), time(20)])
        self.assertEqual({o.start_date for o in result.candidate.occurrences}, {date(2026, 10, 16)})
        self.assertIsNone(result.candidate.start_time)
        self.assertIsNone(result.candidate.starts_at)
        self.assertEqual(len({o.occurrence_id for o in result.candidate.occurrences}), 2)

    def test_invalid_session_clock_does_not_create_occurrence(self):
        result = normalized("۲۴ مهرماه", schedule="در دو سانس ۱۷ و ۲۵")
        self.assertEqual(len(result.candidate.occurrences), 1)
        self.assertIsNone(result.candidate.occurrences[0].start_time)
        self.assertIn("invalid_time", codes(result))

    def test_repeated_session_clocks_require_identity_review(self):
        result = normalized("۲۴ مهرماه", schedule="در دو سانس ۱۷ و ۱۷")
        self.assertIsNone(result.candidate.occurrences[0].start_time)
        self.assertIn("ambiguous_session_clocks", codes(result))

    def test_schedule_recovers_missing_primary_date(self):
        result = normalized(schedule="پنجشنبه ۳۰ مهر ۱۴۰۵ - ساعت ۱۹")
        self.assertEqual(result.candidate.start_date, date(2026, 10, 22))
        self.assertEqual(result.candidate.start_time, time(19))
        self.assertIsNone(result.candidate.source_date_text)

    def test_separate_date_and_clock_schedule_compose_on_same_candidate(self):
        result = normalized("۳۰ مهر ۱۴۰۵", schedule="ساعت ۱۹")
        self.assertEqual(result.candidate.starts_at.isoformat(), "2026-10-22T19:00:00+03:30")
        self.assertEqual(result.candidate.occurrences[0].source_schedule_text, "ساعت ۱۹")
        self.assertEqual(result.candidate.source_date_text, "۳۰ مهر ۱۴۰۵")

    def test_schedule_conflict_retains_both_facts_without_primary(self):
        result = normalized("۹ مهر ۱۴۰۵ ساعت ۱۶", schedule="۱۰ مهر ۱۴۰۵ ساعت ۱۸")
        self.assertEqual(result.candidate.schedule_kind, ScheduleKind.CONFLICT)
        self.assertIsNone(result.candidate.start_date)
        self.assertEqual(len(result.candidate.occurrences), 2)
        self.assertIn("schedule_conflict", codes(result))
        event = canonical(result)
        self.assertIn("normalization:schedule_conflict", {d.code for d in event.diagnostics})
        self.assertEqual(len(event.occurrences), 2)

    def test_multi_session_schedule_supersedes_covered_single_date(self):
        result = normalized("۹ مهر ۱۴۰۵", schedule="۹ و ۱۰ مهر ۱۴۰۵")
        self.assertEqual(len(result.candidate.occurrences), 2)
        self.assertIsNone(result.candidate.start_date)
        self.assertNotIn("schedule_conflict", codes(result))

    def test_occurrence_identity_independent_of_prices_and_event_id_stable(self):
        first = canonical(normalized("۹ مهر ۱۴۰۵ ساعت ۱۶"))
        second = canonical(normalized("۹ و ۱۰ مهر ۱۴۰۵ ساعت ۱۶"))
        self.assertEqual(first.event_id, second.event_id)
        self.assertEqual(first.occurrences[0].occurrence_id, second.occurrences[0].occurrence_id)
        priced = replace(first.occurrences[0], price_amount=Decimal(500))
        self.assertEqual(identify_occurrence(priced, first.event_id).occurrence_id,
                         first.occurrences[0].occurrence_id)

    def test_source_sessions_keep_individual_price_availability(self):
        result = normalized(source_sessions=(
            session("a", price_per_person="500", remaining_seats=0, enabled=False, duration_hours="2"),
            session("b", start="2026-10-02T14:30:00Z", price_per_person="700", remaining_seats=3),
        ), price_text="۹۰۰ هزار تومان")
        a, b = result.candidate.occurrences
        self.assertEqual((a.price_amount, b.price_amount), (Decimal(500), Decimal(700)))
        self.assertIsNone(a.currency)
        self.assertEqual((a.remaining_seats, b.remaining_seats), (0, 3))
        self.assertFalse(a.enabled)
        self.assertEqual(a.start_time, time(18))
        self.assertEqual(a.end_time, time(20))
        self.assertEqual(a.source_session_id, "a")
        self.assertIsNone(result.candidate.start_date)

    def test_session_does_not_inherit_event_price(self):
        result = normalized(source_sessions=(session(),), price_text="۹۰۰ هزار تومان")
        self.assertIsNone(result.candidate.occurrences[0].price_amount)
        self.assertIsNone(result.candidate.occurrences[0].price_text)

    def test_session_price_conflict_preserves_raw_keys(self):
        result = normalized(source_sessions=(session(price_per_person="500", unit_price="700"),))
        value, = result.candidate.occurrences
        self.assertIsNone(value.price_amount)
        self.assertIsNone(value.price_text)
        self.assertEqual((value.price_per_person, value.unit_price), ("500", "700"))
        self.assertIn("session_price_conflict", codes(result))

    def test_session_discount_never_labels_base_amount_as_payable(self):
        result = normalized(source_sessions=(session(price_per_person="500", host_discount_pct="10"),))
        value, = result.candidate.occurrences
        self.assertIsNone(value.price_amount)
        self.assertIsNone(value.price_text)
        self.assertEqual(value.host_discount_pct, "10")
        self.assertIn("embedded_session_discount_unresolved", codes(result))

    def test_occurrence_clock_and_date_validation(self):
        value = normalized("۹ مهر ۱۴۰۵ ساعت ۱۶").candidate.occurrences[0]
        with self.assertRaises(ValueError):
            replace(value, start_time=time(17))
        with self.assertRaises(ValueError):
            replace(value, start_date=datetime(2026, 10, 1))

    def test_native_session_identity_is_scoped_to_source_host(self):
        value = normalized(source_sessions=(session(),)).candidate.occurrences[0]
        other = replace(value, evidence_urls=("https://another.example/event/1",),
                        source_session_origin="another.example")
        self.assertNotEqual(identify_occurrence(value, "event:1").occurrence_id,
                            identify_occurrence(other, "event:1").occurrence_id)

    def test_session_id_does_not_change_when_supporting_evidence_is_added(self):
        value = normalized(source_sessions=(session(),)).candidate.occurrences[0]
        other = replace(value, evidence_urls=("https://another.example/event/1", *value.evidence_urls))
        self.assertEqual(identify_occurrence(value, "event:1").occurrence_id,
                         identify_occurrence(other, "event:1").occurrence_id)

    def test_native_session_conflicting_time_retains_both_interpretations(self):
        first = normalized(source_sessions=(session(),))
        second = normalized(source_sessions=(session(start="2026-10-02T14:30:00Z"),))
        contexts = tuple(CandidateContext(result, result.candidate, RAW, SOURCE, RAW.captured_at)
                         for result in (first, second))
        event = resolve_group(contexts, "group:forced-review")
        self.assertEqual(event.schedule_kind, ScheduleKind.CONFLICT)
        self.assertEqual(len(event.occurrences), 2)
        self.assertEqual(len({o.occurrence_id for o in event.occurrences}), 2)
        self.assertIsNone(event.start_date)
        self.assertIn("occurrence_temporal_conflict", {d.code for d in event.diagnostics})

    def test_relative_schedule_needs_same_context_guard_as_date(self):
        result = normalized(schedule="فردا", raw=replace(RAW, raw_text="در گالری فردا"))
        self.assertFalse(result.candidate.occurrences)
        self.assertIn("ambiguous_relative_context", codes(result))

    def test_rejected_relative_token_does_not_erase_explicit_schedule(self):
        result = normalized("فردا", schedule="۹ مهر ۱۴۰۵ ساعت ۱۸",
                            raw=replace(RAW, raw_text="در گالری فردا"))
        self.assertEqual(result.candidate.start_date, date(2026, 10, 1))
        self.assertEqual(result.candidate.start_time, time(18))
        self.assertIn("ambiguous_relative_context", codes(result))

    def test_selected_visible_date_keeps_session_schema_diagnostic(self):
        result = normalized("۹ مهر ۱۴۰۵ ساعت ۱۸ تا ۲۰",
                            source_sessions=(session(),),
                            source_session_diagnostics=("embedded_session_schema_drift",))
        self.assertIn("embedded_session_schema_drift", codes(result))
        self.assertEqual(result.candidate.occurrences[0].source_session_id, "1")

    def test_session_conflicting_with_visible_date_requires_review(self):
        result = normalized("۲۰ مهر ۱۴۰۵", source_sessions=(session(),))
        self.assertEqual(result.candidate.schedule_kind, ScheduleKind.CONFLICT)
        self.assertIsNone(result.candidate.start_date)

    def test_covering_schedule_does_not_erase_weekday_conflict(self):
        result = normalized("جمعه ۹ مهر ۱۴۰۵", schedule="۹ مهر ۱۴۰۵ ساعت ۱۸")
        self.assertIn("weekday_contradiction", codes(result))

    def test_partial_native_session_overlay_keeps_other_date_without_lending_facts(self):
        result = normalized("۱ و ۲ مهر ماه ساعت ۲۰:۳۰", source_sessions=(
            session(start="2026-09-24T17:00:00Z", duration_hours="2", remaining_seats=45),))
        first, second = result.candidate.occurrences
        self.assertEqual((first.start_date, second.start_date), (date(2026, 9, 23), date(2026, 9, 24)))
        self.assertIsNone(first.source_session_id)
        self.assertIsNone(first.remaining_seats)
        self.assertEqual(second.source_session_id, "1")
        self.assertEqual(second.remaining_seats, 45)
        self.assertEqual(second.end_time, time(22, 30))
        self.assertNotIn("schedule_conflict", codes(result))

    def test_visible_end_clock_does_not_discard_native_session_facts(self):
        result = normalized("۹ مهر ۱۴۰۵ ساعت ۱۸ تا ۲۰", source_sessions=(
            session(price_per_person="500", remaining_seats=3),))
        value, = result.candidate.occurrences
        self.assertEqual(value.source_session_id, "1")
        self.assertEqual(value.price_amount, Decimal(500))
        self.assertEqual(value.end_time, time(20))
        self.assertEqual(value.ends_at.time(), time(20))

    def test_explicit_overnight_session_duration_remains_occurrence_only(self):
        result = normalized(source_sessions=(session(start="2026-10-01T19:30:00Z", duration_hours="3"),))
        value, = result.candidate.occurrences
        self.assertEqual(value.ends_at.date(), date(2026, 10, 2))
        self.assertIsNone(result.candidate.ends_at)
        self.assertEqual(len(canonical(result).occurrences), 1)

    def test_repeated_normalization_is_identical(self):
        first = normalized("۹ و ۱۰ مهر ۱۴۰۵ ساعت ۱۶")
        second = NormalizationService().normalize(first.candidate, RAW, SOURCE)
        self.assertEqual(first, second)

    def test_different_explicit_occurrence_sets_do_not_auto_merge(self):
        a = normalized("۹ و ۱۰ مهر ۱۴۰۵ ساعت ۱۶")
        b = normalized("۱۱ و ۱۲ مهر ۱۴۰۵ ساعت ۱۶")
        ca = CandidateContext(a, a.candidate, RAW, SOURCE, RAW.captured_at)
        cb = CandidateContext(b, b.candidate, RAW, SOURCE, RAW.captured_at)
        decision = match_pair(ca, cb)
        self.assertEqual(decision.kind.value, "distinct")
        self.assertIn("conflicting_occurrence_dates", decision.reasons)


if __name__ == "__main__":
    unittest.main()
