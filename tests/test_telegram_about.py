"""Telegram «👤 درباره سازنده» screen and the rewritten «❓ راهنما». Offline only."""
from __future__ import annotations

import json

from gatherradar.telegram_bot import presentation as ui
from test_telegram_bot import STRANGER, BotCase, callback, command


def buttons(payload):
    return [b for row in json.loads(payload['reply_markup'])['inline_keyboard'] for b in row]


class AboutAndHelpTests(BotCase):
    def test_main_menu_offers_about_creator(self):
        self.send(command('/start'))
        labels = {b['text']: b.get('callback_data') for b in buttons(self.fake.sent('sendMessage')[0])}
        self.assertEqual(labels['👤 درباره سازنده'], ui.ABOUT)
        self.assertEqual(labels['❓ راهنما'], ui.HELP)

    def test_about_edits_the_current_message_with_links_and_back(self):
        self.send(callback(ui.ABOUT))
        self.assertEqual(self.fake.sent('sendMessage'), [])  # navigation never sends a new message
        about, = self.fake.sent('editMessageText')
        for expected in ('درباره سازنده', 'ابزاری برای کشف، جمع‌آوری و بررسی رویدادها، دورهمی‌ها و تجربه‌های جدید است.',
                         'طراحی و توسعه: Mohamad Mohebali'):
            self.assertIn(expected, about['text'])
        self.assertEqual(about['parse_mode'], 'HTML')
        keys = {b['text']: b for b in buttons(about)}
        self.assertEqual(keys['GitHub']['url'], 'https://github.com/MohebaliDesign')
        self.assertEqual(keys['Repository']['url'], 'https://github.com/MohebaliDesign/GatherRadar')
        self.assertEqual(keys['↩️ بازگشت به منوی اصلی']['callback_data'], ui.MAIN)

    def test_help_explains_the_workflow_and_links_to_about(self):
        self.send(callback(ui.HELP), callback(ui.ABOUT), callback(ui.MAIN))
        help_text, about, menu = self.fake.sent('editMessageText')
        for step in ('۱. ', '۲. ', '۳. ', '۴. ', 'زمان باقی‌مانده', 'Excel', 'مدیریت منابع', 'آخرین اجراها'):
            self.assertIn(step, help_text['text'])
        self.assertTrue(help_text['text'].endswith('ساخته‌شده توسط Mohamad Mohebali'))
        keys = {b['text']: b.get('callback_data') for b in buttons(help_text)}
        self.assertEqual(keys, {'👤 درباره سازنده': ui.ABOUT, '↩️ بازگشت به منوی اصلی': ui.MAIN})
        self.assertIn('درباره سازنده', about['text'])
        self.assertIn('به GatherRadar خوش آمدید', menu['text'])

    def test_help_command_uses_the_same_keyboard(self):
        self.send(command('/help'))
        reply, = self.fake.sent('sendMessage')
        self.assertEqual({b['text'] for b in buttons(reply)}, {'👤 درباره سازنده', '↩️ بازگشت به منوی اصلی'})

    def test_strangers_cannot_open_about(self):
        self.send(callback(ui.ABOUT, STRANGER))
        self.assertEqual([a['text'] for a in self.fake.sent('answerCallbackQuery')], [ui.PRIVATE_ONLY])
        self.assertEqual(self.fake.sent('editMessageText'), [])

    def test_about_callback_is_allowlisted(self):
        self.assertEqual(ui.parse_callback(ui.ABOUT), {'about': 'about'})
        self.assertIsNone(ui.parse_callback(ui.ABOUT + 'x'))
