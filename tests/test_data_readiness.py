import unittest
from dataclasses import replace
from datetime import date, time

from gatherradar.domain.event import CanonicalDiagnostic
from gatherradar.domain.occurrence import EventOccurrence, ScheduleKind
from gatherradar.domain.temporal import DatePrecision
from gatherradar.review.coverage import CoverageOutcome, STAGES, audit_field, coverage_summary
from gatherradar.review.readiness import DataReadiness, assess_readiness, run_readiness_record
from gatherradar.review.serialization import review_window
from local_review_fakes import sample, STAMP


def event(**kwargs):
    return replace(sample().events[0], start_date=date(2026, 9, 26),
                   date_precision=DatePrecision.DAY, diagnostics=(), **kwargs)


class ReadinessTests(unittest.TestCase):
    def test_missing_optional_fields_do_not_prevent_review(self):
        result = assess_readiness(event(price_text=None, price_amount=None, venue_name=None,
                                        description_text=None, event_format=None))
        self.assertEqual(result.status, DataReadiness.READY)
        self.assertEqual(result.reasons, ("supported_facts_preserved",))

    def test_missing_title_is_explicit_enrichment(self):
        result = assess_readiness(event(title=None))
        self.assertEqual(result.status, DataReadiness.ENRICHMENT)
        self.assertIn("missing_title", result.reasons)

    def test_recurrence_is_not_ready_as_a_concrete_date(self):
        result = assess_readiness(event(schedule_kind=ScheduleKind.RECURRING,
                                        source_schedule_text="جمعه‌ها ساعت ۱۶"))
        self.assertEqual(result.status, DataReadiness.SCHEDULE)
        self.assertIn("unresolved_schedule", result.reasons)

    def test_conflicts_never_silently_look_ready(self):
        base = event()
        for field, state in (("temporal", DataReadiness.SCHEDULE), ("venue_name", DataReadiness.ENRICHMENT)):
            value = replace(base, diagnostics=(CanonicalDiagnostic("field_conflict", field),))
            self.assertEqual(assess_readiness(value).status, state)

    def test_bad_source_url(self):
        self.assertEqual(assess_readiness(event(canonical_source_url="javascript:alert(1)")).status,
                         DataReadiness.ENRICHMENT)

    def test_inferred_year_is_schedule_review(self):
        self.assertIn("inferred_year", assess_readiness(
            replace(event(), date_precision=DatePrecision.INFERRED)).reasons)

    def test_successful_channel_prevents_false_source_unavailable(self):
        value = event(source_ids=("web", "ig"))
        run = {"channels": [{"source_id": "web", "status": "policy_blocked"},
                            {"source_id": "ig", "status": "success"}]}
        self.assertEqual(run_readiness_record(value, run)["data_readiness"], "ready_for_review")
        run["channels"][1]["status"] = "access_restricted"
        self.assertEqual(run_readiness_record(value, run)["data_readiness"], "source_unavailable")

    def test_partial_ocr_is_visible_without_mutating_owner_decision(self):
        value = event(source_ids=("ig",), reviewer_notes="owner note")
        record = run_readiness_record(value, {"source_failures": ["ig:media_evidence_partial"]})
        self.assertIn("ocr_evidence_incomplete", record["quality_indicators"])
        self.assertEqual(value.reviewer_notes, "owner note")

    def test_unreliable_ocr_clock_never_looks_ready_even_with_exact_date(self):
        value = replace(event(), diagnostics=(CanonicalDiagnostic(
            "extraction:repeated_anchor_with_unreliable_temporal_ocr", "extraction"),))
        self.assertEqual(assess_readiness(value).status, DataReadiness.SCHEDULE)
        self.assertIn("unreliable_temporal_ocr", assess_readiness(value).reasons)

    def test_known_caption_attribution_ambiguity_is_not_optional_absence(self):
        value = replace(event(), diagnostics=(CanonicalDiagnostic(
            "extraction:ambiguous_caption_description", "extraction"),))
        self.assertEqual(assess_readiness(value).status, DataReadiness.ENRICHMENT)

    def test_discrete_occurrences_filter_by_membership_not_bounds(self):
        occurrences = (
            EventOccurrence("early", date(2026, 9, 20), "Asia/Tehran"),
            EventOccurrence("late", date(2026, 10, 20), "Asia/Tehran"),
        )
        value = replace(event(), start_date=None, date_precision=DatePrecision.UNKNOWN,
                        schedule_kind=ScheduleKind.DISCRETE, occurrences=occurrences)
        self.assertEqual(assess_readiness(value).status, DataReadiness.READY)
        self.assertEqual(review_window((value,), STAMP, 14).filtered, 1)
        result = review_window((value,), STAMP, 30)
        self.assertEqual((len(result.events), result.undated), (1, 0))

    def test_unresolved_conflict_remains_visible_outside_resolved_session(self):
        value = replace(event(), start_date=None, schedule_kind=ScheduleKind.CONFLICT,
            occurrences=(EventOccurrence("past", date(2026, 9, 1), "Asia/Tehran"),))
        self.assertEqual(review_window((value,), STAMP).undated, 1)


class CoverageTests(unittest.TestCase):
    def audit(self, **kwargs):
        return audit_field(event_id="event", field="start_time",
            evidence_reference="fixture:caption:line2", explanation="Source explicitly says ساعت ۱۹",
            publisher="sample", source="sample_ig", channel="instagram", evidence_type="caption", **kwargs)

    def test_finds_first_loss_even_if_later_stage_is_populated(self):
        checks = dict.fromkeys(STAGES, True)
        checks["normalization"] = False
        result = self.audit(stages=checks)
        self.assertEqual((result.outcome, result.earliest_loss),
                         (CoverageOutcome.EXTRACTION_BUG, "normalization"))

    def test_unknown_prior_stage_prevents_false_earliest_claim(self):
        result = self.audit(stages={"extraction": False})
        self.assertIsNone(result.earliest_loss)
        self.assertEqual(result.outcome, CoverageOutcome.EXTRACTION_BUG)

    def test_missing_output_alone_is_not_source_missing(self):
        self.assertEqual(self.audit().outcome, CoverageOutcome.AMBIGUOUS)
        self.assertEqual(self.audit(unresolved=CoverageOutcome.SOURCE_MISSING).outcome,
                         CoverageOutcome.SOURCE_MISSING)

    def test_retention_and_grouped_counts(self):
        result = self.audit(stages=dict.fromkeys(STAGES, True))
        report = coverage_summary([result])
        self.assertEqual(report["outcomes"], {"MATCHED": 1})
        self.assertEqual(report["by"]["channel"]["instagram"], {"MATCHED": 1})

    def test_rejects_unsupported_assertions(self):
        with self.assertRaises(ValueError):
            self.audit(stages={"invented_stage": True})
        with self.assertRaises(ValueError):
            self.audit(unresolved=CoverageOutcome.MATCHED)
