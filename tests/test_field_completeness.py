import unittest
from gatherradar.extraction.signals import analyze
from gatherradar.extraction import fields


class LocationCompletenessTests(unittest.TestCase):
    def test_compound_pin_keeps_venue_and_area_without_city_or_street(self):
        found = analyze('نمایشگاه «آبی»\n📍 محله نمونه، مجتمع سپید، گالری ابر/باران')
        self.assertEqual(fields.venue_name(found), 'گالری ابر/باران')
        self.assertEqual(fields.area_text(found), 'محله نمونه')
        self.assertEqual(fields.location_context(found), 'مجتمع سپید')
        self.assertIsNone(fields.city(found))
        self.assertIsNone(fields.address(found))

    def test_sponsor_and_office_are_not_event_location(self):
        for text in ('حامی: مجتمع سپید، گالری ابر', 'دفتر برگزارکننده: محله نمونه، مجتمع سپید، گالری ابر'):
            self.assertIsNone(fields.venue_name(analyze(text)))
        found = analyze('📍 دفتر برگزارکننده، مجتمع سپید، گالری ابر')
        self.assertIsNone(fields.venue_name(found))
        self.assertIsNone(fields.location_context(found))

    def test_pin_city_separator_and_parenthetical_directions(self):
        self.assertEqual(fields.venue_name(analyze('📍 تهران | خانه فرهنگ و هنر سپید')), 'خانه فرهنگ و هنر سپید')
        self.assertEqual(fields.venue_name(analyze('📍عمارت سپید (محله نمونه، خیابان آبی)')), 'عمارت سپید')
        self.assertEqual(fields.area_text(analyze('📍 نام نمونه، شعبه نیاوران')), 'نیاوران')

    def test_explicit_duration_and_event_organizer_prose(self):
        self.assertEqual(fields.duration_text(analyze('مدت زمان اجرا: ۷۵ دقیقه')), '۷۵ دقیقه')
        self.assertEqual(fields.organizer_name(analyze('این رویداد که توسط تیم نمونه برگزار می‌شه، در گالری است.')), 'تیم نمونه')
        self.assertIsNone(fields.organizer_name(analyze('تبلیغ توسط تیم نمونه منتشر شد')))

    def test_explicit_english_meridiem_survives_field_selection(self):
        from gatherradar.normalization.times import parse_times
        from gatherradar.normalization.text import fold
        from datetime import time
        for wording, expected in (('4:30 P.M', time(16,30)), ('12:00 a.m.', time(0)), ('12 pm', time(12))):
            selected = fields.source_date_text(analyze(wording))
            self.assertEqual(parse_times(fold(selected)).start, expected)
