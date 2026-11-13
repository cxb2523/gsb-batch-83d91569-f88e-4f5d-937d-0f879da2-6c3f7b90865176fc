"""Same-post noisy Reel title variants (cloud field hardening).

See docs/CLOUD_FIELD_HARDENING_VALIDATION.md. Synthetic reconstruction only: the
original frames and OCR are not available in Cloud.
"""
from __future__ import annotations

import unittest


class SamePostNoisyReelTests(unittest.TestCase):
    """P1: one described Reel workshop with OCR title variants is one Event.

    Reconstruction of the frozen DeoiH5qRkBU shape: the caption describes the
    workshop; sampled frames render the title as «پیتزاء» / «پیعزاء» with
    mixed-script weekday/clock corruption. Exact frame text is not in Cloud.
    """

    CAPTION = 'تو این ورکشاپ فوت‌وفن درست کردن پیتزا رو یاد بگیری!\nدوشنبه ۲۷ مهر ساعت ۱۷\nثبت نام'

    def run_pipeline(self, *frames, caption=None):
        from test_event_recall import PUBLISHED, pipeline
        from gatherradar.domain.evidence import EvidenceKind
        media = tuple((EvidenceKind.REEL_FRAME_OCR, 1000 * index, text) for index, text in enumerate(frames))
        events, _ = pipeline(self.CAPTION if caption is None else caption, media=media,
                             published=PUBLISHED.replace(day=18))
        return events

    def test_three_variant_candidates_become_one_caption_event(self):
        events = self.run_pipeline(
            'خودت درستش کن >\nورکشاپ پیتزاء دوشنبه yao PY ساعت ۷',
            'خودت درستش کن؟/ ۰\nورکشاپ پیتزاء دوشنبه ingot ساعت ۰',
            'خودت درستش کن\nورکشاپ پیعزاء دوشنبه yao ساعت ۷',
            'خودت درستش کن >\nورکشاپ پیعزاء دوشنبه ingot ساعت ۱۷')
        event, = events
        self.assertEqual(event.title, 'ورکشاپ ساخت پیتزا')
        self.assertEqual(event.source_date_text, 'دوشنبه ۲۷ مهر ساعت ۱۷')
        self.assertEqual(event.start_time.isoformat(), '17:00:00')  # caption clock, not OCR "۷"
        # The clean caption date has passed: expired, not sent to schedule review
        # because of corrupt frame clocks (which stay as collapsed provenance).
        from test_event_recall import REFERENCE
        from gatherradar.review.relevance import assess_relevance
        self.assertEqual(assess_relevance(event, REFERENCE).disposition, 'expired')
        # Identity stays the caption's primary slot, as before the change.
        caption_only, = self.run_pipeline()
        self.assertEqual(event.event_id, caption_only.event_id)

    def test_single_noisy_substituted_frame_joins_only_with_matching_weekday(self):
        self.assertEqual(len(self.run_pipeline('ورکشاپ پیعزاء دوشنبه yao ساعت ۷')), 1)
        self.assertEqual(len(self.run_pipeline('ورکشاپ پیعزاء سه‌شنبه yao ساعت ۷')), 2)

    def test_clean_frames_get_no_substitution_or_clock_tolerance(self):
        for frame in ('ورکشاپ پیعزا دوشنبه ساعت ۱۷',     # clean substitution: different word
                      'ورکشاپ پیتزا دوشنبه ساعت ۱۹',     # clean different clock: different session
                      'ورکشاپ پیتزا\n۲۸ مهر ۱۴۰۵ ساعت ۱۸'):  # own calendar date
            with self.subTest(frame=frame):
                self.assertEqual(len(self.run_pipeline(frame)), 2)

    def test_distinct_activities_in_one_post_stay_separate(self):
        events = self.run_pipeline('کنسرت پاییز دوشنبه yao ساعت ۷',
                                   'ورکشاپ پاستا دوشنبه yao ساعت ۷')  # two letters differ
        self.assertEqual(len(events), 3)

    def test_short_words_never_take_a_substitution(self):
        from gatherradar.grouping.conservative import _ocr_same_word
        self.assertFalse(_ocr_same_word('چای', 'جای', noisy=True))
        self.assertTrue(_ocr_same_word('پیعزاء', 'پیتزا', noisy=True))
        self.assertFalse(_ocr_same_word('پیعزاء', 'پیتزا', noisy=False))
        self.assertFalse(_ocr_same_word('سفال۲', 'سفال۱', noisy=True))  # digits stay significant


if __name__ == '__main__':
    unittest.main()
