"""Venue gaps confirmed in live run e3ddedf31d5248808f78e5586b58d703 (2026-10-29).

Positive inputs are the live captions' location wording; each rule has negatives.
"""
from __future__ import annotations

import unittest

from gatherradar.extraction.fields import venue_name
from gatherradar.extraction.signals import analyze

SEQUENCE = ('🪄✨\nرویداد “سکانس چهارم”\nدر عمارت زیرخاکی\n.\n@emarate_zirkhaki\n.\n'
            'این رویداد فقط یک ایونت برای فروش نیست؛ بلکه همزمان اکران فیلم با حضور عوامل و کارگردان و اجرای موسیقی داره؛\n'
            'در محیط عمارت زیرخاکی حسابی بهتون خوش میگذره.\n.\n📌۶ تا ۸ آبان | ساعت ۱۱ تا ۲۳\n.\n'
            '📍نیاوران، جمال‌آباد، میدان خبیر، بن‌بست ترانه، پلاک ۳.')
CHIZMIZ = ('ایونت چیزمیز🧡\n\nاز ۶ تا ۸ آبان، توی ایونت «چیزمیز» در کافه‌کتاب مدیا، قراره کلی چیزهای خلاقانه کشف کنید!\n'
           'از ۱۲ برند خلاق و متفاوت دیدن کنید.\n\n📍آدرس: میدان ولیعصر، کوچه فرخی، کافه کتاب مدیا')


class StandaloneVenueLineTests(unittest.TestCase):
    def test_line_under_title_repeated_in_prose_is_the_venue(self):
        self.assertEqual(venue_name(analyze(SEQUENCE)), 'عمارت زیرخاکی')

    def test_unrepeated_or_untitled_or_competing_lines_are_not_venues(self):
        for text in ('رویداد پاییزی\nدر خانه بمانید\n۶ آبان ساعت ۱۸',                       # one-off phrase
                     'تخفیف ویژه\nدر عمارت زیرخاکی\nمحصولات عمارت زیرخاکی',               # no event title above
                     'رویداد الف\nدر عمارت آبی\nرویداد ب\nدر عمارت سبز\nعمارت آبی و عمارت سبز'):  # two names
            with self.subTest(text=text):
                self.assertIsNone(venue_name(analyze(text)))


class EventAtAddressTailTests(unittest.TestCase):
    def test_event_noun_at_name_matching_address_tail(self):
        self.assertEqual(venue_name(analyze(CHIZMIZ)), 'کافه‌کتاب مدیا')

    def test_mismatching_tail_or_no_event_noun_is_not_a_venue(self):
        for text in (CHIZMIZ.replace('کافه کتاب مدیا', 'کافه نمونه'),
                     CHIZMIZ.replace('توی ایونت «چیزمیز» در', 'توی ویترین ما و'),
                     CHIZMIZ.replace('ایونت «چیزمیز» در', 'ایونت در')):  # unnamed mention
            with self.subTest(text=text[:40]):
                self.assertIsNone(venue_name(analyze(text)))


if __name__ == '__main__':
    unittest.main()
