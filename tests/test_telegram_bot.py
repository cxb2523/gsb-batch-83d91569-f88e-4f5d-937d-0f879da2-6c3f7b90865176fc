"""Owner-only Telegram bot, Phase 1. Fully offline: a fake Telegram HTTP transport.

No live credentials, network, crawler run or registry write is involved. The
token below is a syntactically valid fake and must never appear in output.
"""
from __future__ import annotations

import os

# The suite never reads the owner's local registry overlay (config/sources.local.json);
# tests that need an overlay point GATHERRADAR_SOURCE_OVERLAY at a temporary file.
os.environ.setdefault('GATHERRADAR_SOURCE_OVERLAY', 'none')

import asyncio
import io
import json
import logging
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from telegram import Update
from telegram.error import NetworkError
from telegram.request import BaseRequest

from gatherradar.cli import main
from gatherradar.telegram_bot import presentation as ui
from gatherradar.telegram_bot.lock import AlreadyRunningError, SingleInstanceLock
from gatherradar.telegram_bot.runner import (RedactingFilter, StartupError, build_application, preflight,
                                             verify_identity)
from gatherradar.telegram_bot.services import SourceCatalog, SourceView
from gatherradar.telegram_bot.settings import (OWNER_ENV, TOKEN_ENV, SettingsError, TelegramSettings, redact)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'config' / 'sources.yaml'
TOKEN = '1234567890:AAFakeTokenForOfflineTestsOnly_abcdefghijk'
OWNER, STRANGER = 111222333, 999888777


class FakeTelegram(BaseRequest):
    """Records Bot API calls and answers like Telegram would; nothing leaves the process."""

    def __init__(self, username='GatherRadar_Bot', fail=None, not_modified=False):
        self.username, self.fail, self.not_modified = username, dict(fail or {}), not_modified
        self.calls: list[tuple[str, dict]] = []

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    @property
    def read_timeout(self):
        return 1.0

    async def do_request(self, url, method, request_data=None, read_timeout=None, write_timeout=None,
                         connect_timeout=None, pool_timeout=None):
        name = url.rsplit('/', 1)[-1]
        params = dict(request_data.json_parameters) if request_data else {}
        self.calls.append((name, params))
        if name in self.fail:
            raise self.fail[name]
        if name == 'getMe':
            result = {'id': 42, 'is_bot': True, 'first_name': 'GatherRadar', 'username': self.username}
        elif name in ('sendMessage', 'editMessageText'):
            if name == 'editMessageText' and self.not_modified:
                return 400, json.dumps({'ok': False, 'error_code': 400, 'description':
                    'Bad Request: message is not modified'}).encode()
            chat = int(params.get('chat_id', OWNER))
            result = {'message_id': 7, 'date': 0, 'chat': {'id': chat, 'type': 'private'},
                      'text': params.get('text', '')}
        else:
            result = True
        return 200, json.dumps({'ok': True, 'result': result}).encode()

    def sent(self, method):
        return [p for name, p in self.calls if name == method]


def user(uid):
    return {'id': uid, 'is_bot': False, 'first_name': 'تست'}


def command(text, uid=OWNER, chat_type='private', chat_id=None):
    word = text.split()[0]
    return {'update_id': 1, 'message': {
        'message_id': 1, 'date': 0, 'from': user(uid), 'text': text,
        'chat': {'id': uid if chat_id is None else chat_id, 'type': chat_type},
        'entities': [{'type': 'bot_command', 'offset': 0, 'length': len(word)}]}}


def callback(data, uid=OWNER):
    return {'update_id': 2, 'callback_query': {
        'id': 'cb', 'from': user(uid), 'chat_instance': 'ci', 'data': data,
        'message': {'message_id': 7, 'date': 0, 'chat': {'id': uid, 'type': 'private'}, 'text': 'x',
                    'from': {'id': 42, 'is_bot': True, 'first_name': 'GatherRadar'}}}}


class BotCase(unittest.TestCase):
    owner = OWNER

    def setUp(self):
        self.fake = FakeTelegram()
        self.settings = TelegramSettings(TOKEN, self.owner)
        # A crawl, refresh or export started by any handler fails the test.
        for target in ('gatherradar.orchestration.refresh.RefreshService.run',
                       'gatherradar.collectors.website.WebsiteCollector.collect',
                       'gatherradar.config.Path.write_text'):
            patcher = mock.patch(target, side_effect=AssertionError('side effect'))
            patcher.start()
            self.addCleanup(patcher.stop)

    def send(self, *updates, fake=None):
        fake = fake or self.fake

        async def go():
            app = build_application(self.settings, SourceCatalog(CONFIG), request=fake)
            async with app:
                for payload in updates:
                    await app.process_update(Update.de_json(payload, app.bot))
        asyncio.run(go())
        return fake

    def texts(self, fake=None):
        fake = fake or self.fake
        return [p['text'] for p in fake.sent('sendMessage') + fake.sent('editMessageText')]


class OwnerMenuTests(BotCase):
    def test_start_and_menu_show_the_persian_main_menu(self):
        self.send(command('/start'), command('/menu'))
        first, second = self.fake.sent('sendMessage')
        self.assertEqual(first['text'], second['text'])
        self.assertIn('به GatherRadar خوش آمدید', first['text'])
        self.assertEqual(first['parse_mode'], 'HTML')
        buttons = [b['text'] for row in json.loads(first['reply_markup'])['inline_keyboard'] for b in row]
        for label in ('🔄 کرال همه منابع', '🎯 انتخاب منابع', '📋 مدیریت منابع', '📊 دریافت خروجی',
                      '🕘 آخرین اجراها', '⚙️ تنظیمات (فقط نمایش)', '❓ راهنما'):
            self.assertIn(label, buttons)
        self.assertFalse(any('به‌زودی' in b for b in buttons))  # every visible action is implemented
        self.assertNotIn('⏳ وضعیت اجرای جاری', buttons)  # shown only while a crawl runs

    def test_help_and_whoami(self):
        self.send(command('/help'), command('/whoami'))
        help_text, whoami = self.texts()
        self.assertIn('/sources', help_text)
        self.assertIn(str(OWNER), whoami)
        self.assertNotIn('GATHERRADAR_TELEGRAM_OWNER_ID', whoami)  # bootstrap hint only before setup

    def test_sources_lists_registry_with_disabled_state(self):
        self.send(command('/sources'))
        text = self.texts()[0]
        for view in SourceCatalog(CONFIG).list():
            self.assertIn(ui.e(view.name), text)
        self.assertIn('<b>اینستاگرام</b>', text)
        self.assertIn('<b>وب‌سایت</b>', text)
        self.assertIn('Davvvat Website — ⛔️ مسدود به‌دلیل سیاست سایت', text)
        self.assertNotIn(str(ROOT), text)

    def test_source_detail_and_navigation_callbacks(self):
        self.send(callback(ui.SOURCE + 'davvvat_website'), callback(ui.SOURCES + '1'), callback(ui.MAIN))
        detail, page, menu = [p['text'] for p in self.fake.sent('editMessageText')]
        self.assertIn('davvvat_website', detail)
        self.assertIn('غیرفعال', detail)
        self.assertIn('https://davvvat.ir/', detail)
        self.assertIn('منابع ثبت‌شده', page)
        self.assertIn('به GatherRadar خوش آمدید', menu)

    def test_old_soon_buttons_now_reopen_the_menu(self):
        # Manage sources and Settings are implemented; an old «به‌زودی» button only reopens the menu.
        self.send(callback(ui.SOON + 'manage_sources'), callback(ui.SOON + 'settings'))
        menus = [p['text'] for p in self.fake.sent('editMessageText')]
        self.assertEqual(len(menus), 2)
        self.assertTrue(all('به GatherRadar خوش آمدید' in m for m in menus))

    def test_old_phase1_soon_button_reopens_the_menu_without_crawling(self):
        self.send(callback(ui.SOON + 'crawl_all'))
        menu, = self.fake.sent('editMessageText')
        self.assertIn('به GatherRadar خوش آمدید', menu['text'])

    def test_repeated_callback_is_harmless(self):
        fake = FakeTelegram(not_modified=True)
        self.send(callback(ui.MAIN), callback(ui.MAIN), fake=fake)
        self.assertEqual(len(fake.sent('answerCallbackQuery')), 2)
        self.assertEqual(fake.sent('sendMessage'), [])  # no error message for an unchanged edit

    def test_forged_callbacks_are_refused(self):
        self.send(callback('gr1:src:show:not_a_source'), callback('gr1:admin:crawl'),
                  callback('gr1:soon:delete_everything'), callback('x' * 70))
        answers = [p.get('text') for p in self.fake.sent('answerCallbackQuery')]
        self.assertEqual(answers, [ui.INVALID] * 4)
        self.assertEqual(self.fake.sent('editMessageText'), [])

    def test_no_collection_side_effects_and_registry_unchanged(self):
        before = CONFIG.read_bytes()
        self.send(command('/start'), command('/sources'), callback(ui.SOON + 'crawl_all'),
                  callback(ui.SOURCE + 'davvvat_instagram'))
        self.assertEqual(CONFIG.read_bytes(), before)


class AuthorizationTests(BotCase):
    def test_stranger_gets_no_menu_data_or_sources(self):
        self.send(command('/start', STRANGER), command('/sources', STRANGER), command('/whoami', STRANGER))
        self.assertEqual(self.texts(), [ui.PRIVATE_ONLY] * 3)
        self.assertEqual([p for p in self.fake.sent('sendMessage') if 'reply_markup' in p], [])

    def test_stranger_callbacks_are_refused_even_when_valid(self):
        self.send(callback(ui.SOURCES + '0', STRANGER), callback(ui.SOURCE + 'davvvat_website', STRANGER))
        self.assertEqual([p['text'] for p in self.fake.sent('answerCallbackQuery')], [ui.PRIVATE_ONLY] * 2)
        self.assertEqual(self.fake.sent('editMessageText'), [])

    def test_owner_outside_a_private_chat_is_refused_silently(self):
        self.send(command('/sources', OWNER, chat_type='group', chat_id=-100123))
        self.assertEqual(self.fake.sent('sendMessage'), [])


class BootstrapTests(BotCase):
    owner = None

    def test_without_owner_only_whoami_answers(self):
        self.send(command('/whoami', STRANGER), command('/start', STRANGER), command('/sources', STRANGER),
                  callback(ui.SOURCES + '0', STRANGER))
        whoami, start, sources = self.texts()
        self.assertIn(str(STRANGER), whoami)
        self.assertIn('GATHERRADAR_TELEGRAM_OWNER_ID', whoami)
        self.assertEqual((start, sources), (ui.BOOTSTRAP, ui.BOOTSTRAP))  # nobody becomes owner
        self.assertEqual(self.fake.sent('editMessageText'), [])

    def test_whoami_is_not_answered_in_groups(self):
        self.send(command('/whoami', STRANGER, chat_type='group', chat_id=-100))
        self.assertEqual(self.fake.sent('sendMessage'), [])


class TransportFailureTests(BotCase):
    def test_send_failure_is_logged_without_the_token(self):
        fake = FakeTelegram(fail={'sendMessage': NetworkError('connection reset')})
        with self.assertLogs('gatherradar.telegram', level='ERROR') as logs:
            self.send(command('/start'), fake=fake)
        self.assertTrue(any('NetworkError' in line for line in logs.output))
        self.assertFalse(any(TOKEN.split(':')[1] in line for line in logs.output))

    def test_identity_check_retries_then_fails_clearly(self):
        fake = FakeTelegram(fail={'getMe': NetworkError('down')})

        async def go():
            from telegram import Bot
            async with Bot(TOKEN, request=fake) as bot:
                pass
        with self.assertRaises(NetworkError):  # Bot.initialize itself needs getMe
            asyncio.run(go())

        async def check():
            from telegram import Bot
            bot = Bot(TOKEN, request=fake)
            return await verify_identity(bot, 'GatherRadar_Bot', attempts=3, backoff=(0.0,))
        fake.calls.clear()
        with self.assertRaises(StartupError) as caught:
            asyncio.run(check())
        self.assertEqual(len(fake.sent('getMe')), 3)
        self.assertIn('unreachable', str(caught.exception))
        self.assertNotIn(TOKEN, str(caught.exception))

    def test_wrong_bot_username_is_refused(self):
        with self.assertRaises(StartupError) as caught:
            asyncio.run(preflight(TelegramSettings(TOKEN, OWNER), request=FakeTelegram(username='OtherBot')))
        self.assertIn('@OtherBot', str(caught.exception))
        self.assertEqual(asyncio.run(preflight(TelegramSettings(TOKEN, OWNER), request=FakeTelegram())),
                         'GatherRadar_Bot')

    def test_commands_are_scoped_to_the_owner(self):
        from gatherradar.telegram_bot.handlers import publish_commands

        async def go():
            app = build_application(TelegramSettings(TOKEN, OWNER), SourceCatalog(CONFIG), request=self.fake)
            async with app:
                await publish_commands(app, TelegramSettings(TOKEN, OWNER))
        asyncio.run(go())
        default, owner = self.fake.sent('setMyCommands')
        self.assertEqual([c['command'] for c in json.loads(default['commands'])], ['whoami'])
        self.assertEqual(json.loads(owner['scope']), {'type': 'chat', 'chat_id': OWNER})
        self.assertIn('sources', [c['command'] for c in json.loads(owner['commands'])])


class SettingsAndFormattingTests(unittest.TestCase):
    def test_environment_settings(self):
        with self.assertRaises(SettingsError) as missing:
            TelegramSettings.from_env({})
        self.assertIn(TOKEN_ENV, str(missing.exception))
        for bad in ('abc', '123:short'):
            with self.subTest(bad=bad), self.assertRaises(SettingsError) as caught:
                TelegramSettings.from_env({TOKEN_ENV: bad})
            self.assertNotIn(bad, str(caught.exception))
        with self.assertRaises(SettingsError):
            TelegramSettings.from_env({TOKEN_ENV: TOKEN, OWNER_ENV: '@me'})
        settings = TelegramSettings.from_env({TOKEN_ENV: TOKEN, OWNER_ENV: str(OWNER)})
        self.assertEqual((settings.owner_id, settings.bootstrap), (OWNER, False))
        self.assertTrue(TelegramSettings.from_env({TOKEN_ENV: TOKEN}).bootstrap)
        self.assertNotIn(TOKEN, repr(settings))

    def test_cli_reports_missing_token_without_starting(self):
        err = io.StringIO()
        with mock.patch.dict('os.environ', {}, clear=True), redirect_stderr(err), redirect_stdout(io.StringIO()):
            self.assertEqual(main(['telegram', 'run']), 2)
        self.assertIn(TOKEN_ENV, err.getvalue())

    def test_token_redaction_in_logs(self):
        record = logging.LogRecord('httpx', logging.INFO, __file__, 1,
                                   'POST https://api.telegram.org/bot%s/getUpdates', (TOKEN,), None)
        RedactingFilter(TOKEN).filter(record)
        self.assertNotIn(TOKEN.split(':')[1], record.getMessage())
        self.assertEqual(redact(f'x {TOKEN} y', TOKEN), 'x [REDACTED] y')

    def test_dynamic_values_are_html_escaped(self):
        view = SourceView('evil_src', '<b>Evil & "Co"</b>', 'website', False, '<script>', 'https://e.test/?a=<x>')
        text = ui.sources_text((view,)) + ui.source_text(view)
        self.assertNotIn('<b>Evil', text)
        self.assertIn('&lt;b&gt;Evil &amp;', text)
        self.assertNotIn('<script>', text)

    def test_callback_data_fits_telegram_limits_and_parses(self):
        for view in SourceCatalog(CONFIG).list():
            data = ui.SOURCE + view.id
            self.assertLessEqual(len(data.encode()), 64)
            self.assertEqual(ui.parse_callback(data), {'source': view.id})
        self.assertIsNone(ui.parse_callback('gr1:src:show:../../etc'))

    def test_catalog_is_read_only_and_ordered(self):
        views = SourceCatalog(CONFIG).list()
        self.assertEqual([v.id for v in views][:2], ['davvvat_website', 'davvvat_instagram'])
        davvvat = SourceCatalog(CONFIG).get('davvvat_website')
        self.assertEqual((davvvat.enabled, davvvat.disabled_reason), (False, 'robots'))


class SingleInstanceTests(unittest.TestCase):
    def test_cli_refuses_a_second_local_instance_before_contacting_telegram(self):
        with tempfile.TemporaryDirectory() as folder, SingleInstanceLock(Path(folder) / 'telegram' / 'bot.lock'):
            err = io.StringIO()
            with mock.patch.dict('os.environ', {TOKEN_ENV: TOKEN, OWNER_ENV: str(OWNER)}), \
                    mock.patch('gatherradar.telegram_bot.runner.preflight', side_effect=AssertionError('network')), \
                    mock.patch('gatherradar.telegram_bot.runner.configure_logging'), \
                    redirect_stderr(err), redirect_stdout(io.StringIO()):
                code = main(['telegram', 'run', '--config', str(CONFIG), '--data-dir', folder])
            self.assertEqual(code, 3)
            self.assertIn('already running', err.getvalue())
            self.assertNotIn(TOKEN, err.getvalue())

    def test_second_instance_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'telegram' / 'bot.lock'
            with SingleInstanceLock(path):
                with self.assertRaises(AlreadyRunningError):
                    SingleInstanceLock(path).acquire()
            with SingleInstanceLock(path):  # released after exit
                pass


if __name__ == '__main__':
    unittest.main()
