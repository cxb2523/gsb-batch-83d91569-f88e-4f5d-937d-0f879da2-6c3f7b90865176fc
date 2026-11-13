"""Source-field recall: listing-card evidence, structural facts and their propagation.

All inputs are sanitized fixtures with the observed Vadoostan / Jabama layouts.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from gatherradar.collectors.website import WebsiteCollector
from gatherradar.collectors.websites.adapters import build_adapter
from gatherradar.collectors.websites.transport import Page
from gatherradar.domain import EvidenceKind, EventStatus
from gatherradar.domain.evidence import website_listing_fragment
from gatherradar.domain.temporal import DatePrecision
from gatherradar.domain.website import WebsiteConfig
from gatherradar.extraction import fields
from gatherradar.extraction.signals import analyze
from gatherradar.orchestration.canonicalization_run import run_canonical_review
from gatherradar.review.serialization import quality, schedule
from gatherradar.storage import JsonlRawItemStore

FIXTURES = Path(__file__).parent / 'fixtures' / 'websites'
NOW = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
V_LIST = 'https://vadoostan.example/app/experiences'
J_LIST = 'https://jabama.example/all?city=tehran&type=experiences'
CONFIG = f'''sources:
  - id: vadoostan_fixture
    publisher_key: vadoostan
    name: Vadoostan fixture
    type: website
    url: {V_LIST}
    website: {{adapter: vadoostan, detail_path_prefixes: [/app/experiences/], content_selector: main}}
  - id: jabama_experiences_fixture
    publisher_key: jabama
    name: Jabama experiences fixture
    type: website
    url: {J_LIST}
    city_hint: Tehran
    website: {{adapter: jabama-events, detail_path_prefixes: [/events/], content_selector: article}}
  - id: jabama_events_fixture
    publisher_key: jabama
    name: Jabama events fixture
    type: website
    url: https://jabama.example/all?city=tehran
    city_hint: Tehran
    website: {{adapter: jabama-events, detail_path_prefixes: [/events/], content_selector: article}}
'''


def html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding='utf-8')


class Pages:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages

    def fetch(self, url, *, allowed=None):
        if url not in self.pages:
            raise AssertionError('unexpected fetch ' + url)
        return Page(url, self.pages[url], 'fixture')


def vadoostan_pages(**overrides) -> dict[str, str]:
    pages = {V_LIST: html('vadoostan-list-cards.html'),
             V_LIST + '/GameNightA1': html('vadoostan-experience-detail.html'),
             V_LIST + '/MusicGroupB2': html('vadoostan-multisession-detail.html'),
             V_LIST + '/PingPongC3': html('vadoostan-experience-detail.html')
                 .replace('شب بازی نقش‌آفرینی: قلعه مه‌آلود', 'گروه ورزش: «پینگ‌پنگ» (۳ جلسه)')
                 .replace('ایرانشهر - سمیه', 'کریمخان').replace('۵ مهر ساعت ۱۷:۰۰', '۶ مهر ساعت ۱۹:۱۵')}
    pages.update(overrides)
    return pages


def jabama_pages(**overrides) -> dict[str, str]:
    detail = html('jabama-experience-detail.html')
    schedule_detail = (detail.replace('تجربه ساخت گوشواره سرامیکی در تهران', 'منجوق بافی ژاپنی')
                       .replace('۲ ساعت کارگاه', 'دوشنبه ساعت ۱۱ و ۱۶ - جمعه ساعت ۱۶')
                       .replace('با راهنمایی مربی،', 'در این ورکشاپ با راهنمایی مربی،')
                       .replace('<aside', '<aside data-x="no price"').replace('<p>از ۷۵۰٬۰۰۰ تومان</p>', ''))
    pages = {J_LIST: html('jabama-experiences-list.html'),
             'https://jabama.example/events/event-11112222': detail,
             'https://jabama.example/events/33334444': schedule_detail}
    pages.update(overrides)
    return pages


class Pipeline:
    """Collect from fixture pages, store, then run the unchanged offline review."""

    def __init__(self, case: unittest.TestCase) -> None:
        directory = TemporaryDirectory()
        case.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.config = self.root / 'sources.yaml'
        self.config.write_text(CONFIG, encoding='utf-8')
        from gatherradar.config import load_sources
        self.sources = {s.id: s for s in load_sources(self.config)}

    def collect(self, source_id: str, pages: dict[str, str], limit: int = 3, now: datetime = NOW):
        source = self.sources[source_id]
        result = WebsiteCollector(transport=Pages(pages), now=lambda: now).collect(source, limit=limit)
        path = self.root / 'raw' / 'website' / f'{source_id}.jsonl'
        JsonlRawItemStore(path).append_new(result.items)
        return result

    def review(self, observed: dict):
        return run_canonical_review(tuple(observed), config_path=self.config, data_dir=self.root,
                                    limit=5, observed_items=observed).result

    def events(self, source_id: str, pages: dict[str, str], limit: int = 3):
        result = self.collect(source_id, pages, limit)
        return {e.title: e for e in self.review({source_id: result.items}).events}


class ListingCardTests(unittest.TestCase):
    def setUp(self):
        self.adapter = build_adapter(WebsiteConfig('vadoostan', ('/app/experiences/',), 'main'))

    def cards(self, page: str):
        return self.adapter.cards(Page(V_LIST, page), V_LIST)

    def test_each_card_is_only_its_own_anchor(self):
        cards = self.cards(html('vadoostan-list-cards.html'))
        game = cards[V_LIST + '/GameNightA1'].text
        self.assertEqual(game.splitlines(), ['بازی', 'شب بازی نقش‌آفرینی: قلعه مه‌آلود',
                                             'محله: ایرانشهر - سمیه', 'ساعت: ۱۷:۰۰', '۵۰۰٬۰۰۰ تومان'])
        # Neighbouring cards, day headers and filters never leak in.
        for foreign in ('تکمیل ظرفیت', '۱٬۲۰۰٬۰۰۰', 'کریمخان', 'پینگ', 'یکشنبه ۵ مهر', 'دسته‌بندی', 'ورود'):
            self.assertNotIn(foreign, game)
        self.assertIn('تکمیل ظرفیت', cards[V_LIST + '/MusicGroupB2'].text)
        self.assertNotIn('تومان', cards[V_LIST + '/MusicGroupB2'].text)

    def test_differing_cards_for_one_url_are_ambiguous(self):
        page = html('vadoostan-list-cards.html').replace(
            '</main>', '<a href="/app/experiences/GameNightA1">ویژه: ۹۹۹ تومان</a></main>')
        self.assertNotIn(V_LIST + '/GameNightA1', self.cards(page))
        self.assertIn(V_LIST + '/PingPongC3', self.cards(page))

    def test_identical_repeat_and_image_only_links_keep_the_card(self):
        page = html('vadoostan-list-cards.html')
        card = page[page.index('<a href="/app/experiences/PingPongC3"'):page.index('</main>')]
        page = page.replace('</main>', card + '<a href="/app/experiences/PingPongC3"><img alt=""/></a></main>')
        self.assertIn('کریمخان', self.cards(page)[V_LIST + '/PingPongC3'].text)

    def test_oversized_wrapper_is_not_card_evidence(self):
        page = html('vadoostan-list-cards.html').replace(
            '</main>', '<a href="/app/experiences/PingPongC3">' + 'متن ' * 600 + '</a></main>')
        self.assertNotIn(V_LIST + '/PingPongC3', self.cards(page))


class VadoostanDetailTests(unittest.TestCase):
    def setUp(self):
        self.adapter = build_adapter(WebsiteConfig('vadoostan', ('/app/experiences/',), 'main'))

    def test_header_slots_description_and_organizer_are_structural_facts(self):
        detail = self.adapter.extract(Page(V_LIST + '/GameNightA1', html('vadoostan-experience-detail.html')), V_LIST)
        found = dict(detail.fields)
        self.assertEqual(found['area_text'], 'ایرانشهر - سمیه')
        self.assertEqual(found['duration_text'], '۳ ساعت')
        self.assertEqual(found['organizer_name'], 'سارا نمونه')
        self.assertTrue(found['description_text'].startswith('بازی: «قلعه مه‌آلود»'))
        self.assertTrue(found['description_text'].endswith('آماده ورود به قلعه هستید؟🏰'))
        for value in found.values():
            self.assertIn(value, detail.text)
        # FAQ policies and the organizer biography stay out of evidence.
        for excluded in ('قوانین لغو', 'امکان لغو', 'بیوگرافی'):
            self.assertNotIn(excluded, detail.text)
        self.assertEqual(detail.text.splitlines()[-2:], ['سارا نمونه', 'برگزار کننده'])

    def test_unrecognized_header_shape_yields_no_area_or_duration(self):
        page = html('vadoostan-experience-detail.html').replace('<div>۵ مهر ساعت ۱۷:۰۰</div>', '<div>بزودی</div>')
        found = dict(self.adapter.extract(Page(V_LIST + '/GameNightA1', page), V_LIST).fields)
        self.assertNotIn('area_text', found)
        self.assertNotIn('duration_text', found)
        self.assertIn('description_text', found)

    def test_co_organizers_are_not_guessed(self):
        page = html('vadoostan-experience-detail.html')
        card = page[page.index('<div class="q-card'):page.index('</div></main>')]
        found = dict(self.adapter.extract(Page(V_LIST + '/A', page.replace(card, card + card.replace('سارا', 'مینا'))), V_LIST).fields)
        self.assertNotIn('organizer_name', found)


class CollectorEvidenceTests(unittest.TestCase):
    def test_raw_item_keeps_card_and_field_provenance(self):
        pipeline = Pipeline(self)
        item = pipeline.collect('vadoostan_fixture', vadoostan_pages(), limit=1).items[0]
        self.assertEqual(item.raw_metadata['listing_card_text'].splitlines()[2], 'محله: ایرانشهر - سمیه')
        origins = {(f['name'], f['origin']) for f in item.raw_metadata['source_fields']}
        self.assertIn(('area_text', 'detail'), origins)
        self.assertIn(('description_text', 'detail'), origins)
        self.assertNotIn('۵۰۰٬۰۰۰', item.raw_text)  # list-only price is card evidence, not page text
        fragment = website_listing_fragment(item)
        self.assertEqual((fragment.kind, fragment.source_url), (EvidenceKind.WEBSITE_LISTING, V_LIST))

    def test_changed_card_is_a_new_observation_and_unchanged_is_stable(self):
        pipeline = Pipeline(self)
        first = pipeline.collect('vadoostan_fixture', vadoostan_pages(), limit=1).items[0]
        again = pipeline.collect('vadoostan_fixture', vadoostan_pages(), limit=1).items[0]
        self.assertEqual(first.content_hash, again.content_hash)
        sold = html('vadoostan-list-cards.html').replace('<!--[-->۵۰۰٬۰۰۰ تومان <!--]-->', 'تکمیل ظرفیت', 1)
        changed = pipeline.collect('vadoostan_fixture', vadoostan_pages(**{V_LIST: sold}), limit=1).items[0]
        self.assertNotEqual(first.content_hash, changed.content_hash)


class VadoostanPipelineTests(unittest.TestCase):
    def setUp(self):
        self.events = Pipeline(self).events('vadoostan_fixture', vadoostan_pages())
        self.game = self.events['شب بازی نقش‌آفرینی: قلعه مه‌آلود']
        self.music = self.events['گروه کشف موسیقی: «جز و آزادی» (۴ جلسه)']
        self.pong = self.events['گروه ورزش: «پینگ‌پنگ» (۳ جلسه)']

    def test_list_only_price_and_detail_only_description_both_survive(self):
        self.assertEqual(self.game.price_text, '۵۰۰٬۰۰۰ تومان')
        self.assertEqual(str(self.game.price_amount), '500000')
        self.assertTrue(self.game.description_text.startswith('بازی: «قلعه مه‌آلود»'))
        self.assertIsNone(self.game.summary)  # a description is never a generated summary
        provenance = {p.field for p in self.game.field_provenance}
        self.assertTrue({'price_text', 'description_text', 'area_text'} <= provenance)

    def test_matching_listing_and_detail_area_is_one_fact(self):
        self.assertEqual(self.game.area_text, 'ایرانشهر - سمیه')
        self.assertIsNone(self.game.venue_name)  # a neighborhood is not a venue
        self.assertIsNone(self.game.address)
        self.assertFalse([d for d in self.game.diagnostics if 'conflict' in d.code])

    def test_duration_organizer_and_primary_date(self):
        self.assertEqual((self.game.duration_text, self.game.organizer_name), ('۳ ساعت', 'سارا نمونه'))
        self.assertEqual((self.game.start_date.isoformat(), self.game.start_time.isoformat()),
                         ('2026-09-27', '17:00:00'))
        self.assertIsNone(self.game.end_time)  # a duration never becomes an end time

    def test_neighbouring_card_facts_do_not_contaminate(self):
        self.assertEqual(self.pong.price_text, '۱٬۲۰۰٬۰۰۰ تومان')
        self.assertEqual(self.pong.area_text, 'کریمخان')
        self.assertIsNone(self.game.availability_text)
        self.assertEqual(self.game.status, EventStatus.UNKNOWN)

    def test_sold_out_card_maps_status_without_inventing_price(self):
        self.assertEqual(self.music.availability_text, 'تکمیل ظرفیت')
        self.assertEqual(self.music.status, EventStatus.SOLD_OUT)
        self.assertIsNone(self.music.price_text)
        self.assertIsNone(self.music.price_amount)

    def test_multi_session_schedule_is_visible_but_not_expanded(self):
        self.assertIn('یکشنبه‌ها ساعت 19', self.music.source_schedule_text)
        self.assertIn('5،12،19 و 26 مهر', self.music.source_schedule_text)
        self.assertNotIn('(۴ جلسه)', self.music.source_schedule_text)  # title is not the schedule
        self.assertIsNone(self.music.end_date)
        self.assertEqual(len([e for e in self.events.values() if 'موسیقی' in (e.title or '')]), 1)
        self.assertEqual(schedule(self.music), self.music.source_schedule_text)
        self.assertEqual(schedule(self.game), self.game.source_date_text)  # inferred year stays visible

    def test_explicit_listing_detail_disagreement_is_not_resolved(self):
        card = html('vadoostan-list-cards.html').replace('محله: ایرانشهر - سمیه', 'محله: پاسداران')
        events = Pipeline(self).events('vadoostan_fixture', vadoostan_pages(**{V_LIST: card}), limit=1)
        event, = events.values()
        self.assertIsNone(event.area_text)
        self.assertIn(('source_field_conflict', 'area_text'), {(d.code, d.field) for d in event.diagnostics})
        self.assertEqual(quality(event), 'تعارض داده')
        self.assertEqual(event.duration_text, '۳ ساعت')  # unrelated facts are unaffected

    def test_current_listing_not_history_supplies_price(self):
        pipeline = Pipeline(self)
        pipeline.collect('vadoostan_fixture', vadoostan_pages(), limit=1)  # stored: card with price
        no_price = html('vadoostan-list-cards.html').replace('<!--[-->۵۰۰٬۰۰۰ تومان <!--]-->', '', 1)
        later = NOW.replace(hour=13)
        current = pipeline.collect('vadoostan_fixture', vadoostan_pages(**{V_LIST: no_price}), 1, later)
        event, = pipeline.review({'vadoostan_fixture': current.items}).events
        self.assertIsNone(event.price_text)
        self.assertEqual(event.area_text, 'ایرانشهر - سمیه')


class JabamaExperiencesTests(unittest.TestCase):
    def test_cards_and_detail_structure(self):
        adapter = build_adapter(WebsiteConfig('jabama-events', ('/events/',), 'article'))
        cards = adapter.cards(Page(J_LIST, html('jabama-experiences-list.html')), J_LIST)
        card = cards['https://jabama.example/events/event-11112222']
        self.assertIn('تهران · استودیو نمونه ۲ ساعت کارگاه', card.text)  # CSS gap is not a glued word
        self.assertIn('از ۷۵۰٬۰۰۰ تومان', card.text)
        self.assertEqual(card.fields, (('duration_text', '۲ ساعت'), ('price_text', 'از ۷۵۰٬۰۰۰ تومان')))
        self.assertEqual(cards['https://jabama.example/events/33334444'].fields,
                         (('price_text', 'از ۲٬۴۰۰٬۰۰۰ تومان'),))
        detail = adapter.extract(Page('https://jabama.example/events/event-11112222',
                                      html('jabama-experience-detail.html')), J_LIST)
        found = dict(detail.fields)
        self.assertEqual((found['organizer_name'], found['duration_text']), ('استودیو نمونه', '۲ ساعت'))
        self.assertEqual(found['price_text'], 'از ۷۵۰٬۰۰۰ تومان')  # booking aside
        self.assertTrue(found['description_text'].startswith('با راهنمایی مربی'))
        self.assertIn('میزبان\nاستودیو نمونه', detail.text)
        self.assertNotIn('https://jabama.example/sample-host', detail.links)

    def test_experiences_flow_through_the_same_pipeline(self):
        events = Pipeline(self).events('jabama_experiences_fixture', jabama_pages(), limit=2)
        earring = events['تجربه ساخت گوشواره سرامیکی در تهران']
        self.assertEqual((earring.duration_text, earring.venue_name, earring.city),
                         ('۲ ساعت', 'استودیو نمونه', 'تهران'))
        self.assertIsNone(earring.source_date_text)  # "۲ ساعت" is a length, not a clock time
        self.assertEqual(earring.price_text, 'از ۷۵۰٬۰۰۰ تومان')
        beads = events['منجوق بافی ژاپنی']
        self.assertEqual(beads.source_schedule_text, 'دوشنبه ساعت ۱۱ و ۱۶ - جمعه ساعت ۱۶')
        self.assertEqual(beads.price_text, 'از ۲٬۴۰۰٬۰۰۰ تومان')  # list-only price
        self.assertIsNone(beads.duration_text)
        self.assertIsNone(beads.start_date)  # recurrence is not expanded
        self.assertEqual(schedule(beads), beads.source_schedule_text)

    def test_same_page_listed_by_events_and_experiences_is_one_event(self):
        pipeline = Pipeline(self)
        experiences = pipeline.collect('jabama_experiences_fixture', jabama_pages(), limit=1)
        events_list = html('jabama-experiences-list.html').replace('<span>۲ ساعت کارگاه</span>', '')
        other = pipeline.collect('jabama_events_fixture', {
            'https://jabama.example/all?city=tehran': events_list,
            'https://jabama.example/events/event-11112222': html('jabama-experience-detail.html')}, limit=1)
        result = pipeline.review({'jabama_experiences_fixture': experiences.items,
                                  'jabama_events_fixture': other.items})
        event, = result.events
        self.assertEqual(len(event.source_ids), 2)
        self.assertEqual(event.duration_text, '۲ ساعت')


class SourceNeutralRuleTests(unittest.TestCase):
    def test_duration_is_never_a_clock_time(self):
        for text in ('۲ ساعت کارگاه', 'به مدت یک ساعت و نیم', '12 ساعت'):
            self.assertEqual(analyze(text).times, (), text)
        self.assertTrue(analyze('ساعت ۱۷').times)
        self.assertTrue(analyze('۵ مهر ساعت ۱۷:۰۰').times)

    def test_labelled_facts_in_any_source_text(self):
        found = analyze('کارگاه عکاسی\nمحله: نیاوران\nمدت: ۳ ساعت\nبرگزارکننده: گروه نمونه\nظرفیت: ۲۰ نفر')
        self.assertEqual((fields.area_text(found), fields.duration_text(found),
                          fields.organizer_name(found), fields.availability_text(found)),
                         ('نیاوران', '۳ ساعت', 'گروه نمونه', '۲۰ نفر'))
        self.assertIsNone(fields.city(found))  # a neighborhood never implies its city

    def test_unlabelled_names_publishers_and_prose_are_not_facts(self):
        found = analyze('کارگاه عکاسی با حضور مریم نمونه\nمنتشرشده توسط صفحه ما\nقبل از تکمیل ظرفیت ثبت‌نام کنید')
        self.assertIsNone(fields.organizer_name(found))
        self.assertIsNone(fields.availability_text(found))
        self.assertIsNone(fields.area_text(found))

    def test_availability_wording_and_sold_out_mapping(self):
        self.assertEqual(fields.availability_text(analyze('کنسرت\nتکمیل ظرفیت')), 'تکمیل ظرفیت')
        self.assertTrue(fields.is_sold_out('تکمیل ظرفیت'))
        self.assertTrue(fields.is_sold_out('Sold out'))
        self.assertEqual(fields.availability_text(analyze('کارگاه\nظرفیت محدود')), 'ظرفیت محدود')
        self.assertFalse(fields.is_sold_out('ظرفیت محدود'))
        self.assertFalse(fields.is_sold_out(None))

    def test_schedule_requires_explicit_multi_session_wording(self):
        self.assertIsNone(fields.source_schedule_text(analyze('کنسرت\n۵ مهر ساعت ۱۷:۰۰')))
        self.assertIsNone(fields.source_schedule_text(analyze('گروه ورزش (۴ جلسه)'), exclude='گروه ورزش (۴ جلسه)'))
        self.assertEqual(fields.source_schedule_text(analyze('کلاس\nجمعه‌ها ساعت ۱۶ تا ۱۹')), 'جمعه‌ها ساعت ۱۶ تا ۱۹')
        self.assertEqual(fields.source_schedule_text(analyze('نشست ۵، ۱۲ و ۱۹ مهر')), 'نشست ۵، ۱۲ و ۱۹ مهر')
        self.assertIsNone(fields.source_schedule_text(analyze('نشست یک جلسه ساعت ۱۷')))

    def test_city_only_venue_label_is_a_city(self):
        found = analyze('کارگاه\nمحل برگزاری\nتهران')
        self.assertIsNone(fields.venue_name(found))
        self.assertEqual(fields.city(found), 'تهران')


if __name__ == '__main__':
    unittest.main()


class ExtractionBoundaryTests(unittest.TestCase):
    def raw(self, fields_, listing='محله: ایرانشهر\n۵۰۰ تومان'):
        from gatherradar.domain import RawItem, SourceType
        return RawItem('website:s:a', 's', SourceType.WEBSITE, 'a', 'webpage', 'https://x.example/events/a',
                       'کارگاه نمونه\n۵ مهر ساعت ۱۷:۰۰\nایرانشهر', NOW,
                       raw_metadata={'listing_card_text': listing, 'list_url': 'https://x.example/',
                                     'source_fields': fields_})

    def test_structured_fields_must_be_exact_fragment_slices(self):
        from gatherradar.domain import EvidenceBundle
        from gatherradar.extraction.service import build_extraction_input
        from gatherradar.grouping import ConservativeGrouping
        raw = self.raw([
            {'name': 'area_text', 'value': 'ایرانشهر', 'origin': 'detail'},
            {'name': 'area_text', 'value': 'ایرانشهر', 'origin': 'listing'},
            {'name': 'area_text', 'value': 'سمیه', 'origin': 'detail'},          # not in the text
            {'name': 'title', 'value': 'کارگاه نمونه', 'origin': 'detail'},      # not a structural field
            {'name': 'duration_text', 'value': 'ایرانشهر', 'origin': 'archive'},  # unknown origin
            'malformed'])
        unit, = ConservativeGrouping().group(EvidenceBundle.from_raw_item(raw))
        self.assertEqual([f.kind for f in unit.fragments], [EvidenceKind.WEBSITE_TEXT, EvidenceKind.WEBSITE_LISTING])
        extraction_input = build_extraction_input(replace(raw, raw_text=unit.text), None, unit)
        self.assertEqual([(f.name, f.origin) for f in extraction_input.source_fields],
                         [('area_text', 'detail'), ('area_text', 'listing')])
        self.assertEqual([o for o, _ in extraction_input.segments], ['detail', 'listing'])

    def test_instagram_input_has_caption_segment_but_no_metadata_structural_fields(self):
        from gatherradar.domain import RawItem, SourceType
        from gatherradar.extraction.service import build_extraction_input
        item = RawItem('instagram:s:a', 's', SourceType.INSTAGRAM, 'a', 'post', 'https://x.example/p/a',
                       'کارگاه', NOW, raw_metadata={'source_fields': [{'name': 'area_text', 'value': 'کارگاه',
                                                                        'origin': 'detail'}]})
        extraction_input = build_extraction_input(item)
        self.assertEqual(extraction_input.segments, (('caption', item.raw_text),))
        self.assertEqual(extraction_input.source_fields, ())

    def test_conflict_and_place_field_contracts(self):
        from gatherradar.domain import DiscoveryType
        from gatherradar.extraction.base import InvalidExtractionOutputError
        from gatherradar.extraction.models import DiscoveryFacts
        from gatherradar.extraction.validation import validate_discovery_facts
        for facts in (DiscoveryFacts(DiscoveryType.EVENT, field_conflicts=('unknown',)),
                      DiscoveryFacts(DiscoveryType.EVENT, area_text='x', field_conflicts=('area_text',)),
                      DiscoveryFacts(DiscoveryType.PLACE, area_text='x'),
                      DiscoveryFacts(DiscoveryType.PLACE, field_conflicts=('price_text',))):
            with self.subTest(facts=facts), self.assertRaises(InvalidExtractionOutputError):
                validate_discovery_facts(facts)
        valid = validate_discovery_facts(DiscoveryFacts(DiscoveryType.EVENT, field_conflicts=('price_text',)))
        self.assertEqual(valid.field_conflicts, ('price_text',))

    def test_same_source_slots_are_never_one_page(self):
        from gatherradar.deduplication.matcher import match_pair
        from gatherradar.deduplication.models import MatchKind
        from deduplication_fakes import context
        a = context('a', publisher='p', date_precision=DatePrecision.UNKNOWN,
                    start_date=None, start_time=None, starts_at=None, timezone=None)
        b = replace(a, original=replace(a.original, candidate_id='candidate:b'),
                    outcome=replace(a.outcome, candidate=replace(a.candidate, candidate_id='candidate:b')),
                    identity_slot='carousel_slide_ocr:1')
        self.assertNotIn('same_source_page', match_pair(a, b).reasons)
        self.assertNotEqual(match_pair(a, b).kind, MatchKind.SAME_EVENT)

    def test_davvvat_venue_address_and_heading_organizer_with_card(self):
        from gatherradar.domain import Source, SourceType
        source = Source('davvvat_fixture', 'davvvat', 'Davvvat fixture', SourceType.WEBSITE, 'https://davvvat.example/',
                        website=WebsiteConfig('davvvat', ('/event/',), '.event-detail-right'))
        pages = {'https://davvvat.example/': '<a href="/event/sample"><h3>اکران فیلم آبی</h3><p>۶ مهر</p></a>',
                 'https://davvvat.example/event/sample': html('venue-address-detail.html')}
        item, = WebsiteCollector(transport=Pages(pages), now=lambda: NOW).collect(source, limit=1).items
        self.assertEqual(item.raw_metadata['listing_card_text'], 'اکران فیلم آبی\n۶ مهر')
        from gatherradar.extraction import DiscoveryService, RuleBasedDiscoveryProvider
        from gatherradar.domain import EvidenceBundle
        from gatherradar.grouping import ConservativeGrouping
        unit, = ConservativeGrouping().group(EvidenceBundle.from_raw_item(item))
        event = DiscoveryService(RuleBasedDiscoveryProvider()).discover_unit(item, unit, source).event
        self.assertEqual((event.venue_name, event.organizer_name), ('خانه آبی', 'خانه آبی'))
        self.assertIn('خیابان نمونه', event.address)
        self.assertEqual(event.field_conflicts, ())


class StructuralPrecedenceTests(unittest.TestCase):
    """Findings from the live audit: header date, badge price and prose schedules."""

    def test_card_badges_and_label_are_structural(self):
        adapter = build_adapter(WebsiteConfig('vadoostan', ('/app/experiences/',), 'main'))
        cards = adapter.cards(Page(V_LIST, html('vadoostan-list-cards.html')), V_LIST)
        self.assertEqual(dict(cards[V_LIST + '/GameNightA1'].fields),
                         {'area_text': 'ایرانشهر - سمیه', 'price_text': '۵۰۰٬۰۰۰ تومان',
                          'source_category_text': 'بازی'})
        self.assertEqual(dict(cards[V_LIST + '/MusicGroupB2'].fields),
                         {'area_text': 'ایرانشهر - خیابان سمیه', 'availability_text': 'تکمیل ظرفیت',
                          'source_category_text': 'موسیقی'})

    def test_header_date_and_badge_price_outrank_prose(self):
        prose = ('آماده ورود به قلعه هستید؟🏰\n📅 زمان: سه‌شنبه صبح‌ها\nسه‌شنبه 7، 14 و 21 مهر\n'
                 'هزینه صبحانه در کافه با خود افراد است (قیمت املت: حدود ۲۵۰ هزار تومان)')
        detail = html('vadoostan-experience-detail.html').replace('آماده ورود به قلعه هستید؟🏰', prose)
        events = Pipeline(self).events('vadoostan_fixture', vadoostan_pages(**{V_LIST + '/GameNightA1': detail}), 1)
        event, = events.values()
        self.assertEqual(event.source_date_text, '۵ مهر ساعت ۱۷:۰۰')
        self.assertEqual((event.start_date.isoformat(), event.start_time.isoformat()), ('2026-09-27', '17:00:00'))
        self.assertEqual(event.price_text, '۵۰۰٬۰۰۰ تومان')
        self.assertFalse([d for d in event.diagnostics if 'conflict' in d.code])
        self.assertIn('سه‌شنبه 7، 14 و 21 مهر', event.source_schedule_text)

    def test_differing_structural_prices_still_conflict(self):
        detail = html('jabama-experience-detail.html').replace('<p>از ۷۵۰٬۰۰۰ تومان</p>', '<p>از ۹۰۰٬۰۰۰ تومان</p>')
        events = Pipeline(self).events('jabama_experiences_fixture', jabama_pages(**{
            'https://jabama.example/events/event-11112222': detail}), limit=1)
        event, = events.values()
        self.assertIsNone(event.price_text)
        self.assertIn(('source_field_conflict', 'price_text'), {(d.code, d.field) for d in event.diagnostics})

    def test_plural_weekday_prose_is_not_a_schedule(self):
        found = analyze('استندآپ\nچهارشنبه‌ها تجریش شلوغ است\nجمعه‌ها\nشنبه ها، ساعت 21')
        self.assertEqual(fields.source_schedule_text(found), 'جمعه‌ها\nشنبه ها، ساعت 21')


class SourceCategoryTests(unittest.TestCase):
    """Release gate: an explicit source category outranks free-text keyword inference."""

    def test_incidental_class_word_does_not_become_workshop(self):
        detail = html('vadoostan-experience-detail.html').replace(
            'آماده ورود به قلعه هستید؟🏰', 'پشت کلاس‌های جادو همیشه ماجرایی هست.\nآماده ورود به قلعه هستید؟🏰')
        events = Pipeline(self).events('vadoostan_fixture', vadoostan_pages(**{V_LIST + '/GameNightA1': detail}))
        game = events['شب بازی نقش‌آفرینی: قلعه مه‌آلود']
        self.assertEqual(game.source_category_text, 'بازی')
        self.assertIsNone(game.category)  # no supported mapping: stays null, never کارگاه
        pong = events['گروه ورزش: «پینگ‌پنگ» (۳ جلسه)']
        self.assertEqual((pong.source_category_text, pong.category), ('ورزش', None))
        self.assertIn('source_category_text', {p.field for p in game.field_provenance})

    def test_mapped_source_label_populates_category(self):
        cards = html('vadoostan-list-cards.html').replace('>بازی</div>', '>کارگاه</div>', 1)
        events = Pipeline(self).events('vadoostan_fixture', vadoostan_pages(**{V_LIST: cards}))
        game = events['شب بازی نقش‌آفرینی: قلعه مه‌آلود']
        self.assertEqual((game.source_category_text, game.category), ('کارگاه', 'workshop'))

    def test_without_a_source_label_text_inference_is_unchanged(self):
        from gatherradar.extraction import RuleBasedDiscoveryProvider
        facts = RuleBasedDiscoveryProvider().discover(structured_input(
            'کارگاه سفالگری\n۵ مهر ساعت ۱۷\nهزینه: ۵۰۰ هزار تومان', ()))
        self.assertEqual((facts.category, facts.source_category_text), ('workshop', None))


def structured_input(text: str, source_fields: tuple):
    from gatherradar.extraction.models import ExtractionInput, SourceField
    return ExtractionInput(raw_item_id='website:fixture:1', source_id='fixture', source_type='website',
                           raw_text=text, content_url='https://example.org/items/1', content_type='webpage',
                           source_fields=tuple(SourceField(*f) for f in source_fields),
                           segments=(('detail', text),))


BOARD_GAME = ('بردگیم «عمارت نمونه»\n۷ مهر ساعت ۱۸:۰۰\nپاسداران\n۳ ساعت\nتوضیحات\n'
              'امشب با هم معمای یک عمارت خیالی را حل می‌کنیم؛ تجربه‌ای خاطره انگیز.\n۴۲۰٬۰۰۰ تومان')


class StructuredOccurrenceTests(unittest.TestCase):
    """Concrete detail occurrence recovers Events lacking generic Event vocabulary."""

    def discover(self, text, source_fields):
        from gatherradar.extraction import RuleBasedDiscoveryProvider
        return RuleBasedDiscoveryProvider().discover(structured_input(text, source_fields))

    def test_listing_item_with_concrete_detail_occurrence_is_event(self):
        facts = self.discover(BOARD_GAME, (('source_date_text', '۷ مهر ساعت ۱۸:۰۰', 'detail'),
                                           ('price_text', '۴۲۰٬۰۰۰ تومان', 'listing')))
        self.assertEqual(facts.discovery_type.value, 'event')
        self.assertIn('verified detail date/time', facts.evidence.reason)
        self.assertEqual(facts.source_date_text, '۷ مهر ساعت ۱۸:۰۰')

    def test_same_item_without_structured_occurrence_stays_other(self):
        self.assertEqual(self.discover(BOARD_GAME, ()).discovery_type.value, 'other')

    def test_experience_without_occurrence_is_not_forced(self):
        text = ('تجربه رنگ آمیزی سفال\nاستودیو نمونه\n۲ ساعت\nدرباره این تجربه\n'
                'روی سفال نقش می‌زنی.\nمیزبان\nاستودیو نمونه\nاز ۱٬۴۰۰٬۰۰۰ تومان')
        facts = self.discover(text, (('duration_text', '۲ ساعت', 'detail'),
                                     ('price_text', 'از ۱٬۴۰۰٬۰۰۰ تومان', 'listing')))
        self.assertEqual(facts.discovery_type.value, 'other')

    def test_source_context_or_weak_slots_alone_are_insufficient(self):
        for source_fields in ((('source_date_text', '۷ مهر ساعت ۱۸:۰۰', 'listing'),),  # card only
                              (('source_date_text', '۷ مهر', 'detail'),)):  # no clock time
            self.assertEqual(self.discover(BOARD_GAME, source_fields).discovery_type.value, 'other')
        bare = 'عمارت نمونه\n۷ مهر ساعت ۱۸:۰۰'  # no price/registration/attendance
        self.assertEqual(self.discover(bare, (('source_date_text', '۷ مهر ساعت ۱۸:۰۰', 'detail'),))
                         .discovery_type.value, 'other')

    def test_place_like_item_keeps_existing_classification(self):
        text = 'کافه گالری نمونه\nیک کافه دنج برای دیدن آثار هنری\nآدرس: تهران، خیابان نمونه'
        without = self.discover(text, ()).discovery_type
        self.assertEqual(self.discover(text, (('area_text', 'نمونه', 'detail'),)).discovery_type, without)
        self.assertNotEqual(without.value, 'event')
