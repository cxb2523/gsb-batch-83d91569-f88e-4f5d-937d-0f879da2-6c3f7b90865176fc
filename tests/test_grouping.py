'''Synthetic evidence only: no owner runtime captures or OCR text.'''
import unittest
from dataclasses import replace

from discovery_fakes import make_raw_item
from gatherradar.domain import DiscoveryUnit, EvidenceFragment, EvidenceKind, caption_fragment
from gatherradar.grouping import ConservativeGrouping, select_semantic_evidence


def fragment(item, text, *, slide=None, frame=None, kind=None, **kwargs):
    kind = kind or (EvidenceKind.CAROUSEL_SLIDE_OCR if slide is not None else
                    EvidenceKind.REEL_FRAME_OCR if frame is not None else EvidenceKind.IMAGE_OCR)
    return EvidenceFragment.create(
        raw_item_id=item.id, kind=kind, text=text, slide_index=slide,
        frame_timestamp_ms=frame, **kwargs,
    )


class UnitIdentityTests(unittest.TestCase):
    def setUp(self):
        self.item = make_raw_item('کارگاه سفالگری')
        self.parts = (caption_fragment(self.item), fragment(self.item, 'جمعه ساعت ۱۸'))

    def build(self, parts=None, version='conservative/1'):
        return DiscoveryUnit.from_fragments(self.parts if parts is None else parts, strategy=version)

    def test_deterministic_identity_text_order_and_provenance(self):
        first = self.build()
        self.assertEqual(first, self.build(tuple(reversed(self.parts))))
        self.assertEqual(first.fragments, self.parts)
        self.assertEqual(first.text, '\n'.join(part.text for part in self.parts))

    def test_version_changes_identity(self):
        self.assertNotEqual(self.build().unit_id, self.build(version='conservative/2').unit_id)

    def test_changed_ocr_fragment_changes_identity(self):
        changed = fragment(self.item, 'جمعه ساعت ۱۹')
        self.assertNotEqual(self.build().unit_id, self.build((self.parts[0], changed)).unit_id)

    def test_raw_item_changes_identity(self):
        other = tuple(replace(part, raw_item_id='other') for part in self.parts)
        self.assertNotEqual(self.build().unit_id, self.build(other).unit_id)

    def test_invalid_groups_are_rejected(self):
        for parts in ((), (self.parts[0], self.parts[0]),
                      (self.parts[0], replace(self.parts[1], raw_item_id='other'))):
            with self.subTest(parts=parts), self.assertRaises(ValueError):
                self.build(parts)
        with self.assertRaises(ValueError):
            self.build(version=' ')


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.item = make_raw_item('current caption')

    def test_current_caption_replaces_stale_stored_caption(self):
        stale = caption_fragment(replace(self.item, raw_text='old caption'))
        selected = select_semantic_evidence(self.item, (stale,))
        self.assertEqual(selected.fragments, (caption_fragment(self.item),))

    def test_latest_wins_for_each_kind_and_position(self):
        positions = ({}, {'slide': 0}, {'slide': 1}, {'frame': 0}, {'frame': 1000})
        old = tuple(fragment(self.item, 'old', **position) for position in positions)
        new = tuple(fragment(self.item, 'new', **position) for position in positions)
        selected = select_semantic_evidence(self.item, (*old, *new))
        self.assertEqual(selected.fragments[1:], new)

    def test_append_order_wins_not_fragment_id_sort_order(self):
        a, b = sorted((fragment(self.item, 'alpha'), fragment(self.item, 'beta')),
                      key=lambda part: part.fragment_id)
        self.assertEqual(select_semantic_evidence(self.item, (b, a)).fragments[1], a)

    def test_latest_failed_or_empty_does_not_fall_back(self):
        old = fragment(self.item, 'کارگاه سفالگری جمعه')
        for latest in (fragment(self.item, ''), fragment(self.item, 'stale-looking text', failure_reason='failed')):
            with self.subTest(latest=latest):
                selected = select_semantic_evidence(self.item, (old, latest))
                self.assertEqual(selected.fragments[1:], (latest,))
                units = ConservativeGrouping().group(selected)
                self.assertEqual(len(units), 1)
                self.assertEqual(units[0].text, self.item.raw_text)

    def test_unrelated_raw_item_is_excluded(self):
        unrelated = fragment(make_raw_item('other', shortcode='OTHER'), 'other poster')
        self.assertEqual(select_semantic_evidence(self.item, (unrelated,)).fragments,
                         (caption_fragment(self.item),))

    def test_website_text_remains_supported_per_url(self):
        history = tuple(fragment(self.item, text, kind=EvidenceKind.WEBSITE_TEXT, source_url=url)
                        for text, url in [('old', 'https://example.test/a'),
                                          ('new', 'https://example.test/a'),
                                          ('another', 'https://example.test/b')])
        self.assertEqual(set(select_semantic_evidence(self.item, history).fragments[1:]), set(history[1:]))


class ConservativeGroupingTests(unittest.TestCase):
    def group(self, caption='', slides=(), frames=(), images=()):
        item = make_raw_item(caption)
        parts = tuple(fragment(item, text, slide=i) for i, text in enumerate(slides))
        parts += tuple(fragment(item, text, frame=i * 1000) for i, text in enumerate(frames))
        parts += tuple(fragment(item, text) for text in images)
        return ConservativeGrouping().group(select_semantic_evidence(item, parts))

    def test_caption_only_retains_exact_wording(self):
        caption = '  کارگاه سفالگری\nجمعه ساعت ۱۸\n'
        units = self.group(caption)
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0].text, caption)

    def test_caption_plus_single_supporting_image(self):
        units = self.group('کارگاه سفالگری', images=['جمعه ساعت ۱۸\nآدرس: تهران، خیابان نمونه'])
        self.assertEqual(len(units), 1)
        self.assertEqual([part.kind for part in units[0].fragments], [EvidenceKind.CAPTION, EvidenceKind.IMAGE_OCR])

    def test_supporting_caption_plus_media_anchor(self):
        units = self.group('جمعه ساعت ۱۸', images=['کارگاه سفالگری'])
        self.assertEqual(len(units), 1)

    def test_different_caption_and_image_anchors_never_merge(self):
        self.assertEqual(len(self.group('کارگاه سفالگری', images=['کنسرت باران\nجمعه'])), 2)

    def test_generic_caption_is_not_assumed_to_describe_single_image(self):
        self.assertEqual(len(self.group('Our weekly selection', images=['concert Friday'])), 2)

    def test_one_event_carousel_across_three_slides(self):
        units = self.group(slides=['کارگاه سفالگری', 'جمعه ساعت ۱۸', 'آدرس: تهران، خیابان نمونه'])
        self.assertEqual(len(units), 1)
        self.assertEqual([part.slide_index for part in units[0].fragments], [0, 1, 2])

    def test_two_events_and_support_attaches_to_correct_anchor(self):
        units = self.group(slides=['کارگاه سفالگری', 'جمعه ساعت ۱۸', 'کنسرت باران', 'شنبه ساعت ۲۰', 'آدرس: شیراز'])
        self.assertEqual([[part.slide_index for part in unit.fragments] for unit in units], [[0, 1], [2, 3, 4]])
        self.assertNotIn('شیراز', units[0].text)
        self.assertNotIn('جمعه', units[1].text)

    def test_place_anchor_and_opening_hours(self):
        units = self.group(slides=['گالری نگاه', 'ساعات بازدید: هر روز از ۱۱ تا ۲۰', 'آدرس: تهران'])
        self.assertEqual(len(units), 1)

    def test_independent_english_event_is_a_boundary_without_named_title(self):
        units = self.group(slides=['concert Friday', 'workshop Saturday', 'Address: Example Street'])
        self.assertEqual([len(unit.fragments) for unit in units], [1, 2])

    def test_ambiguous_slide_remains_separate_and_breaks_chain(self):
        units = self.group(slides=['کارگاه سفالگری', 'A different adventure awaits', 'جمعه ساعت ۱۸'])
        self.assertEqual([len(unit.fragments) for unit in units], [1, 1, 1])

    def test_prose_containing_date_is_not_support_only(self):
        units = self.group(slides=['کارگاه سفالگری', 'Friday we explore another story'])
        self.assertEqual(len(units), 2)

    def test_conflicting_dates_addresses_prices_do_not_merge(self):
        for first, second in [('جمعه ساعت ۱۸', 'شنبه ساعت ۲۰'),
                              ('آدرس: تهران', 'آدرس: شیراز'),
                              ('قیمت: ۱۰۰ تومان', 'قیمت: ۲۰۰ تومان')]:
            with self.subTest(second=second):
                self.assertEqual(len(self.group(slides=['کارگاه سفالگری\n' + first, second])), 2)

    def test_conflict_is_checked_against_whole_group(self):
        units = self.group(slides=['کارگاه سفالگری', 'جمعه ساعت ۱۸', 'آدرس: تهران', 'شنبه ساعت ۲۰'])
        self.assertEqual([len(unit.fragments) for unit in units], [3, 1])

    def test_multiple_groups_never_receive_copies_of_caption(self):
        units = self.group('Our weekly selection', slides=['کارگاه سفالگری', 'جمعه', 'کنسرت باران', 'شنبه'])
        self.assertEqual([len(unit.fragments) for unit in units], [1, 2, 2])
        self.assertEqual(sum(part.kind is EvidenceKind.CAPTION for unit in units for part in unit.fragments), 1)

    def test_repeated_reel_scene_has_one_unit_with_all_provenance(self):
        units = self.group(frames=['concert Friday at 7 PM', 'CONCERT  Friday at 7 PM', 'concert Friday at 7 PM'])
        self.assertEqual(len(units), 1)
        self.assertEqual(len(units[0].fragments), 3)
        self.assertIn('CONCERT  Friday', units[0].text)

    def test_reel_new_anchor_and_support_start_new_unit(self):
        units = self.group(frames=['کارگاه سفالگری', 'جمعه ساعت ۱۸', 'کنسرت باران', 'شنبه ساعت ۲۰'])
        self.assertEqual([len(unit.fragments) for unit in units], [2, 2])

    def test_near_identical_reel_with_changed_digit_is_separate(self):
        units = self.group(frames=['concert Friday at 7 PM', 'concert Friday at 8 PM'])
        self.assertEqual(len(units), 2)

    def test_multiple_named_events_in_image_do_not_anchor_support(self):
        units = self.group(slides=['کارگاه سفالگری\nکنسرت باران', 'جمعه ساعت ۱۸'])
        self.assertEqual(len(units), 2)

    def test_multiple_english_occurrences_do_not_anchor_support_or_merge_caption(self):
        units = self.group('Price: free', images=['concert Friday\nworkshop Saturday'])
        self.assertEqual(len(units), 2)

    def test_caption_with_conflicting_facts_stays_separate(self):
        units = self.group('کارگاه سفالگری\nجمعه', images=['شنبه ساعت ۱۸'])
        self.assertEqual(len(units), 2)

    def test_registration_url_and_price_support_attach(self):
        units = self.group(slides=['کارگاه سفالگری', 'Register at https://example.test/book', 'Price: free'])
        self.assertEqual(len(units), 1)

    def test_support_without_anchor_never_merges_to_improve_score(self):
        units = self.group(slides=['Friday at 7 PM', 'Address: Example Street', 'Price: free'])
        self.assertEqual([len(unit.fragments) for unit in units], [1, 1, 1])

    def test_missing_slide_and_failed_observation_break_adjacency(self):
        item = make_raw_item('')
        for middle in ((), (fragment(item, 'ignored text', slide=1, failure_reason='failed'),)):
            parts = (fragment(item, 'کارگاه سفالگری', slide=0), *middle,
                     fragment(item, 'جمعه ساعت ۱۸', slide=2))
            units = ConservativeGrouping().group(select_semantic_evidence(item, parts))
            self.assertEqual([len(unit.fragments) for unit in units], [1, 1])

    def test_failed_reel_frame_breaks_support_chain(self):
        item = make_raw_item('')
        parts = (fragment(item, 'کارگاه سفالگری', frame=0),
                 fragment(item, '', frame=1000, failure_reason='failed'),
                 fragment(item, 'جمعه ساعت ۱۸', frame=2000))
        units = ConservativeGrouping().group(select_semantic_evidence(item, parts))
        self.assertEqual(len(units), 2)

    def test_zero_meaningful_evidence_yields_zero_units(self):
        for caption in ('', ' ', 'and', '...'):
            self.assertEqual(self.group(caption, slides=['', '...', 'and']), ())

    def test_same_input_gives_identical_units_and_order(self):
        args = dict(caption='Our weekly selection', slides=['کنسرت باران', 'جمعه', 'کارگاه سفالگری', 'شنبه'])
        self.assertEqual(self.group(**args), self.group(**args))

    def test_no_merge_across_media_kinds(self):
        units = self.group(slides=['کارگاه سفالگری'], frames=['جمعه ساعت ۱۸'])
        self.assertEqual(len(units), 2)


if __name__ == '__main__':
    unittest.main()
