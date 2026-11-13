"""Venue, explicit city, stated duration and approximate area (cloud field hardening).

Positive cases use the public caption/page wording quoted by the frozen
2026-10-23 audit; every grammar has negative fixtures. See
docs/CLOUD_FIELD_HARDENING_VALIDATION.md.
"""
from __future__ import annotations

import unittest
from datetime import date

from gatherradar.extraction.fields import area_text, city, duration_text, location_context, venue_name
from gatherradar.extraction.signals import analyze
from gatherradar.review.relevance import assess_relevance

OKTOBER = '''Oktober in Istanbul | استانبول

فستیوال اکتبر در استانبول، با الهام از سنت جشنواره‌های آلمان، برای چهارمین بار از ۲ تا ۴ اکتبر ۲۰۲۶ در کوچوک‌چیفتلیک پارک برگزار شد.

این رویداد سه‌روزه با ترکیبی از کنسرت‌های زنده، اجراهای دی‌جی، بازی‌های جشنواره‌ای، دکورهای تماتیک و فضاهای غذا و نوشیدنی، تجربه‌ای از موسیقی، سرگرمی و دورهمی را برای شرکت‌کنندگان رقم زد.
___________________
Oktober in Istanbul | Istanbul

Inspired by Germany’s long-standing festival traditions, Oktober in Istanbul took place for the fourth time at KüçükÇiftlik Park from October 2 to 4, 2026.

The three-day festival brought together live concerts, DJ performances, festival games, themed decorations, and food and drink experiences, offering visitors a vibrant blend of music, entertainment, and social gatherings.'''

EAGLE = '''رویداد هنری رقص دستان در خزان 🍂

این رویداد که توسط تیم هونر برگزار می‌شه، این آخر هفته توی عمارت عقاب در جریانه که حضور برندهای باکیفیت این رویداد رو به یک مقصد مناسب برای خرید کردن تبدیل کرده است.
حتما بهشون سر بزنید 🧡

مکان: تهران، بزرگراه شهید صیاد شیرازی، یوسف، گلزار، فاوانیا، عمارت عقاب
زمان: چهارشنبه تا جمعه، ساعت ۱۲ تا ۲۲'''

MUG = 'کارگاه ساخت ماگ\nلوکیشن حدودی این تجربه ستارخانه. لوکیشن دقیق بعد از رزرو براتون ارسال میشه.'
ADDRESS = '\nمکان: تهران، بزرگراه نمونه، کوچه گل، عمارت عقاب'


def pipeline_event(text, day):
    from test_event_recall import PUBLISHED, pipeline
    events, _ = pipeline(text, published=PUBLISHED.replace(day=day))
    event, = events
    return event


class OktoberIstanbulTests(unittest.TestCase):
    def test_venue_explicit_city_and_three_day_wording_while_expired(self):
        from test_event_recall import REFERENCE
        event = pipeline_event(OKTOBER, 6)
        self.assertEqual(event.venue_name, 'کوچوک‌چیفتلیک پارک')
        self.assertEqual(event.city, 'استانبول')
        self.assertEqual(event.duration_text, 'سه‌روزه')
        self.assertIsNone(event.address)  # no street address is invented
        self.assertEqual((event.start_date, event.end_date), (date(2026, 10, 2), date(2026, 10, 4)))
        self.assertEqual(assess_relevance(event, REFERENCE).disposition, 'expired')

    def test_trailing_head_venue_negatives(self):
        for text in ('کنسرت در پارک برگزار می‌شود ۲ مهر',          # no name
                     'کنسرت در این پارک برگزار می‌شود ۲ مهر',       # determiner, not a name
                     'کنسرت در کوچوک پارک، و در مرکز دیگر'):          # no holding wording
            with self.subTest(text=text):
                self.assertIsNone(venue_name(analyze(text)))
        self.assertIsNone(venue_name(analyze('در آبی پارک برگزار شد و در سبز پارک برگزار شد')))  # two names

    def test_explicit_city_needs_event_in_city_construction(self):
        self.assertEqual(city(analyze('کارگاه سفرنامه استانبول در تهران')), 'تهران')  # default list first
        for text in ('گفتگو درباره خاطرات استانبول', 'کافه استانبول، ۲ مهر',
                     'فستیوال در استانبول و جشنواره در دبی'):
            with self.subTest(text=text):
                self.assertIsNone(city(analyze(text)))
        self.assertEqual(city(analyze('جشنواره پاییز in Istanbul')), 'Istanbul')

    def test_unlabelled_duration_only_modifies_event_noun(self):
        self.assertEqual(duration_text(analyze('کارگاه دو ساعته سفال')), 'دو ساعته')
        self.assertEqual(duration_text(analyze('مدت: ۳ ساعت\nاین رویداد سه‌روزه')), '۳ ساعت')  # label wins
        for text in ('تخفیف سه‌روزه', 'سه‌روزه', 'کارگاه سه‌روزه و دوره پنج‌روزه'):
            with self.subTest(text=text):
                self.assertIsNone(duration_text(analyze(text)))


class ProseAddressVenueTests(unittest.TestCase):
    def test_happening_prose_agrees_with_address_tail(self):
        event = pipeline_event(EAGLE, 21)
        self.assertEqual(event.venue_name, 'عمارت عقاب')
        self.assertEqual(event.organizer_name, 'تیم هونر')  # organizer stays separate
        self.assertEqual(event.address, 'تهران، بزرگراه شهید صیاد شیرازی، یوسف، گلزار، فاوانیا، عمارت عقاب')

    def test_sponsor_office_past_mention_and_single_role_negatives(self):
        for prose in ('این رویداد با حمایت عمارت عقاب برگزار می‌شه.',            # sponsor, no locative
                      'دفتر این رویداد توی عمارت عقاب در جریانه.',               # office
                      'رویداد قبلی توی عمارت عقاب برگزار شد.',                    # past
                      'برنامه اکران در عمارت عقاب، فرصتی برای دیدار است.',         # mention only
                      'این رویداد توی عمارت نمونه در جریانه.'):                   # disagrees with address
            with self.subTest(prose=prose):
                self.assertIsNone(venue_name(analyze(prose + ADDRESS)))
        self.assertIsNone(venue_name(analyze('این رویداد توی عمارت عقاب در جریانه.')))  # no address
        self.assertIsNone(venue_name(analyze(ADDRESS.strip())))                       # address only


class ApproximateAreaTests(unittest.TestCase):
    def test_colloquial_approximate_location_is_area_only(self):
        found = analyze(MUG)
        self.assertEqual(area_text(found), 'ستارخانه')
        self.assertIsNone(venue_name(found))
        self.assertIsNone(city(found))

    def test_approximate_area_negatives(self):
        for text in ('لوکیشن حدودی: تهران.',                                     # a city
                     'لوکیشن حدودی این تجربه خیابان ستارخان پلاک ۵.',              # an address
                     'لوکیشن دقیق بعد از رزرو ارسال میشه.',                       # not approximate
                     'لوکیشن حدودی این تجربه ستارخانه. موقعیت تقریبی: ونک.'):      # two areas
            with self.subTest(text=text):
                self.assertIsNone(area_text(analyze(text)))

    def test_jabama_page_sentence_reaches_event_area(self):
        from test_source_coverage import Pipeline, html, jabama_pages
        url = 'https://jabama.example/events/event-11112222'
        page = html('jabama-experience-detail.html').replace(
            '<p class="text-[11px] text-[#6B7472]">تهران</p>',
            '<p class="text-[11px] text-[#6B7472]">تهران</p><p>لوکیشن حدودی این تجربه ستارخانه. '
            'لوکیشن دقیق بعد از رزرو براتون ارسال میشه.</p>')
        events = Pipeline(self).events('jabama_experiences_fixture', jabama_pages(**{url: page}), limit=2)
        event = events['تجربه ساخت گوشواره سرامیکی در تهران']
        self.assertEqual(event.area_text, 'ستارخانه')
        self.assertNotIn('ستارخانه', event.address or '')


class ManaLocationRegressionTests(unittest.TestCase):
    """Previously fixed split stays permanent: area / building / venue."""

    def test_pinned_three_part_location_split(self):
        found = analyze('نمایشگاه انفرادی «مانا»\n📅 ۲۴ مهر تا ۱۵ آبان ۱۴۰۵\n📍 اقدسیه، مجتمع آواپلت، گالری ایت/کیوب')
        self.assertEqual((area_text(found), location_context(found), venue_name(found)),
                         ('اقدسیه', 'مجتمع آواپلت', 'گالری ایت/کیوب'))


if __name__ == '__main__':
    unittest.main()
