import unittest
from datetime import datetime, timezone

from discovery_fakes import FixedProvider, OTHER_FACTS
from gatherradar.domain import (
    DiscoveryUnit, EvidenceBundle, EvidenceFragment, EvidenceKind, RawItem,
    SourceType, caption_discovery_units, caption_fragment,
)
from gatherradar.extraction import DiscoveryService


def raw_item(text='caption text'):
    return RawItem(
        id='instagram:source:ABC', source_id='source',
        source_type=SourceType.INSTAGRAM, external_id='ABC', content_type='image',
        content_url='https://www.instagram.com/p/ABC/', raw_text=text,
        captured_at=datetime(2026, 9, 21, tzinfo=timezone.utc),
        content_hash='a' * 64,
    )


class EvidenceFragmentTests(unittest.TestCase):
    def test_evidence_kind_is_closed_and_website_ready(self):
        self.assertEqual(
            {item.value for item in EvidenceKind},
            {'caption', 'image_ocr', 'carousel_slide_ocr', 'reel_frame_ocr', 'website_text',
             'website_listing'},
        )

    def test_fragment_identity_is_deterministic(self):
        values = dict(
            raw_item_id='raw', kind=EvidenceKind.CAROUSEL_SLIDE_OCR,
            text='کارگاه', slide_index=2, asset_hash='b' * 64,
            extraction_engine='fake', extraction_version='1',
        )
        self.assertEqual(
            EvidenceFragment.create(**values).fragment_id,
            EvidenceFragment.create(**values).fragment_id,
        )

    def test_engine_change_is_a_new_auditable_fragment(self):
        base = dict(raw_item_id='raw', kind=EvidenceKind.IMAGE_OCR, text='text')
        first = EvidenceFragment.create(**base, extraction_version='1')
        second = EvidenceFragment.create(**base, extraction_version='2')
        self.assertNotEqual(first.fragment_id, second.fragment_id)

    def test_slide_and_frame_positions_are_represented(self):
        slide = EvidenceFragment.create(
            raw_item_id='raw', kind=EvidenceKind.CAROUSEL_SLIDE_OCR,
            text='slide', slide_index=3,
        )
        frame = EvidenceFragment.create(
            raw_item_id='raw', kind=EvidenceKind.REEL_FRAME_OCR,
            text='frame', frame_timestamp_ms=1500,
        )
        self.assertEqual(slide.slide_index, 3)
        self.assertEqual(frame.frame_timestamp_ms, 1500)

    def test_media_kinds_require_their_position(self):
        for kind in (EvidenceKind.CAROUSEL_SLIDE_OCR, EvidenceKind.REEL_FRAME_OCR):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                EvidenceFragment.create(raw_item_id='raw', kind=kind, text='')

    def test_incompatible_positions_are_rejected(self):
        for kind in EvidenceKind:
            valid = {}
            if kind is EvidenceKind.CAROUSEL_SLIDE_OCR:
                valid['slide_index'] = 0
            if kind is EvidenceKind.REEL_FRAME_OCR:
                valid['frame_timestamp_ms'] = 0
            for field in ('slide_index', 'frame_timestamp_ms'):
                if field in valid:
                    continue
                with self.subTest(kind=kind, field=field), self.assertRaises(ValueError):
                    EvidenceFragment.create(
                        raw_item_id='raw', kind=kind, text='', **{**valid, field: 0}
                    )

    def test_media_positions_are_nonnegative_integers(self):
        for kind, field in (
            (EvidenceKind.CAROUSEL_SLIDE_OCR, 'slide_index'),
            (EvidenceKind.REEL_FRAME_OCR, 'frame_timestamp_ms'),
        ):
            for value in (-1, True, 0.5, '0'):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    EvidenceFragment.create(
                        raw_item_id='raw', kind=kind, text='', **{field: value}
                    )

    def test_website_text_uses_the_same_source_neutral_fragment(self):
        fragment = EvidenceFragment.create(
            raw_item_id='website:item:1', kind=EvidenceKind.WEBSITE_TEXT,
            text='Workshop details', source_url='https://example.com/events/1',
        )
        self.assertEqual(fragment.kind, EvidenceKind.WEBSITE_TEXT)
        self.assertIsNone(fragment.slide_index)
        self.assertIsNone(fragment.frame_timestamp_ms)

    def test_ocr_provenance_is_preserved(self):
        fragment = EvidenceFragment.create(
            raw_item_id='raw', kind=EvidenceKind.IMAGE_OCR, text='clean',
            raw_text=' clean\r\n', local_asset_path='data/media/image.png',
            asset_hash='c' * 64, extraction_engine='fake',
            extraction_version='1.2', extraction_config='fas+eng',
        )
        self.assertEqual(fragment.raw_text, ' clean\r\n')
        self.assertEqual(fragment.asset_hash, 'c' * 64)
        self.assertEqual(fragment.extraction_config, 'fas+eng')

    def test_caption_preserves_raw_text_and_provenance(self):
        item = raw_item('  متن کپشن\n')
        fragment = caption_fragment(item)
        self.assertEqual(fragment.text, item.raw_text)
        self.assertEqual(fragment.raw_text, item.raw_text)
        self.assertEqual(fragment.source_url, item.content_url)


class BundleAndUnitTests(unittest.TestCase):
    def test_bundle_can_be_empty_deliberately(self):
        self.assertEqual(EvidenceBundle('raw').fragments, ())

    def test_bundle_orders_caption_then_slides_then_frames(self):
        item = raw_item()
        slide_two = EvidenceFragment.create(
            raw_item_id=item.id, kind=EvidenceKind.CAROUSEL_SLIDE_OCR,
            text='two', slide_index=2,
        )
        slide_one = EvidenceFragment.create(
            raw_item_id=item.id, kind=EvidenceKind.CAROUSEL_SLIDE_OCR,
            text='one', slide_index=1,
        )
        frame = EvidenceFragment.create(
            raw_item_id=item.id, kind=EvidenceKind.REEL_FRAME_OCR,
            text='frame', frame_timestamp_ms=0,
        )
        bundle = EvidenceBundle.from_raw_item(item, (frame, slide_two, slide_one))
        self.assertEqual(
            [fragment.kind for fragment in bundle.fragments],
            [EvidenceKind.CAPTION, EvidenceKind.CAROUSEL_SLIDE_OCR,
             EvidenceKind.CAROUSEL_SLIDE_OCR, EvidenceKind.REEL_FRAME_OCR],
        )
        self.assertEqual([bundle.fragments[1].slide_index, bundle.fragments[2].slide_index], [1, 2])

    def test_default_strategy_creates_one_caption_unit(self):
        item = raw_item('exact caption')
        units = caption_discovery_units(EvidenceBundle.from_raw_item(item))
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0].text, 'exact caption')

    def test_unit_identity_is_deterministic(self):
        fragment = caption_fragment(raw_item())
        self.assertEqual(
            DiscoveryUnit.from_fragment(fragment).unit_id,
            DiscoveryUnit.from_fragment(fragment).unit_id,
        )

    def test_service_supports_zero_units(self):
        outcomes = DiscoveryService(FixedProvider(OTHER_FACTS)).discover_units(raw_item(), ())
        self.assertEqual(outcomes, ())

    def test_caption_reaches_existing_provider_unchanged(self):
        provider = FixedProvider(OTHER_FACTS)
        item = raw_item('  exact caption\n')
        DiscoveryService(provider).discover(item)
        self.assertEqual(provider.calls[0].raw_text, item.raw_text)

    def test_multiple_units_have_distinct_candidate_identity(self):
        provider = FixedProvider(OTHER_FACTS)
        item = raw_item()
        fragments = tuple(
            EvidenceFragment.create(
                raw_item_id=item.id, kind=EvidenceKind.WEBSITE_TEXT, text=text
            ) for text in ('first unit', 'second unit')
        )
        units = tuple(DiscoveryUnit.from_fragment(fragment) for fragment in fragments)
        outcomes = DiscoveryService(provider).discover_units(item, units)
        self.assertEqual(len(outcomes), 2)
        self.assertNotEqual(outcomes[0].discovery_unit_id, outcomes[1].discovery_unit_id)


if __name__ == '__main__':
    unittest.main()
