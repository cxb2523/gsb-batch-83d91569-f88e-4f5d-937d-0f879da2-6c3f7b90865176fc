"""Telegram update handlers. Authorization runs before any handler and again inside it.

Handlers stay thin: they parse an allowlisted callback, ask `LocalOperations`
(possibly in a worker thread) and render with `presentation`. Crawls start only
from a one-time confirmation token, so a replayed or forged callback cannot
launch a job.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass

from telegram import BotCommand, BotCommandScopeChat, BotCommandScopeDefault, Update
from telegram.constants import ChatAction
from telegram.error import BadRequest, Conflict, RetryAfter, TelegramError
from telegram.ext import (Application, ApplicationHandlerStop, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, TypeHandler, filters)

from . import presentation as ui
from .auth import OwnerPolicy
from .jobs import ACTIVE, JobBusyError, JobRecord
from .services import PlannedFeature, SourceCatalog
from .settings import TelegramSettings

LOGGER = logging.getLogger('gatherradar.telegram')
OWNER_COMMANDS = (('menu', 'منوی اصلی'), ('sources', 'فهرست منابع'), ('help', 'راهنما'),
                  ('cancel', 'لغو گفتگوی جاری'), ('whoami', 'شناسه من'))
CONFIRM_TTL = 600          # seconds a crawl or source-change confirmation stays valid
CONVERSATION_TTL = 900     # an unfinished add-source conversation expires after this
PROGRESS_INTERVAL = 4.0    # minimum seconds between progress edits of one message
TICK_INTERVAL = 10.0       # live elapsed-time refresh while a source is running
MAX_RETRY_AFTER = 60.0


@dataclass
class Conversation:
    """The only conversation state: in memory, owner-only, never half-committed."""
    step: str                      # 'type' | 'input' | 'preview'
    started: float
    kind: str | None = None        # 'instagram' | 'website'
    proposal: object = None
    nonce: str | None = None


def _retry_seconds(error: RetryAfter) -> float:
    import warnings
    with warnings.catch_warnings():  # PTB 22.x warns that the type will become timedelta
        warnings.simplefilter('ignore')
        value = error.retry_after
    seconds = value.total_seconds() if hasattr(value, 'total_seconds') else float(value)
    return min(max(seconds, 1.0), MAX_RETRY_AFTER)


class BotHandlers:
    def __init__(self, settings: TelegramSettings, catalog: SourceCatalog, operations=None) -> None:
        self.settings, self.catalog, self.ops = settings, catalog, operations
        self.policy = OwnerPolicy(settings.owner_id)
        self.selection: set[str] = set()
        self.pending: dict[str, tuple[tuple[str, ...] | None, float]] = {}
        self.status_messages: dict[str, tuple[int, int]] = {}   # job id -> (chat id, message id)
        self._last_edit: dict[str, tuple[float, str]] = {}
        self._edit_locks: dict[str, asyncio.Lock] = {}
        self._tickers: dict[str, asyncio.Task] = {}
        self._frames: dict[str, int] = {}
        self._backoff_until = 0.0
        self.tick_interval = TICK_INTERVAL
        self.min_edit_interval = PROGRESS_INTERVAL
        self.conversation: Conversation | None = None
        self.source_actions: dict[str, tuple[str, str, float]] = {}  # nonce -> (source id, action, created)
        self.loop: asyncio.AbstractEventLoop | None = None
        self.bot = None
        if operations is not None:
            operations.jobs.subscribe(self._job_changed)

    # -- authorization -------------------------------------------------------
    async def guard(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Group -1: every update. Only the owner (or bootstrap /whoami) passes."""
        if self.policy.is_owner(update) or self._bootstrap_whoami(update):
            return
        LOGGER.warning('telegram_unauthorized_update', extra={
            'user_id': getattr(update.effective_user, 'id', None),
            'chat_type': getattr(update.effective_chat, 'type', None)})
        if update.callback_query is not None:
            await self._safe(update.callback_query.answer(ui.PRIVATE_ONLY, show_alert=False))
        elif update.effective_message is not None and getattr(update.effective_chat, 'type', None) == 'private':
            await self._safe(update.effective_message.reply_text(
                ui.BOOTSTRAP if self.settings.bootstrap else ui.PRIVATE_ONLY))
        raise ApplicationHandlerStop

    def _bootstrap_whoami(self, update: Update) -> bool:
        message = update.effective_message
        text = (message.text or '') if message is not None and update.callback_query is None else ''
        command = text.split(maxsplit=1)[0].split('@', 1)[0] if text.startswith('/') else ''
        return command == '/whoami' and self.policy.may_ask_whoami(update)

    def _owner(self, update: Update) -> bool:
        # Defence in depth: handlers re-check even though the guard ran first.
        return self.policy.is_owner(update)

    # -- commands --------------------------------------------------------------
    def _active(self) -> bool:
        return self.ops is not None and self.ops.crawl_active()

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if self._owner(update):
            self.conversation = None  # a fresh menu never commits a half-finished source
            await update.effective_message.reply_html(ui.main_text(), reply_markup=ui.main_keyboard(self._active()))

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if self._owner(update):
            had = self.conversation is not None
            self.conversation = None
            await update.effective_message.reply_html(
                'گفتگوی افزودن منبع لغو شد؛ چیزی ذخیره نشد.' if had else 'گفتگوی بازی برای لغو وجود ندارد.',
                reply_markup=ui.main_keyboard(self._active()))

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if self._owner(update):
            await update.effective_message.reply_html(ui.help_text(), reply_markup=ui.help_keyboard())

    async def sources(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if self._owner(update):
            views = self.catalog.list()
            await update.effective_message.reply_html(ui.sources_text(views),
                                                      reply_markup=ui.sources_keyboard(views, 0))

    async def whoami(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if self._owner(update) or self.policy.may_ask_whoami(update):
            await update.effective_message.reply_html(
                ui.whoami_text(update.effective_user.id, self.settings.bootstrap))

    # -- callbacks -------------------------------------------------------------
    async def callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query is None or not self._owner(update):
            return
        self.bot = context.bot
        action = ui.parse_callback(query.data)
        if action is None:
            await self._safe(query.answer(ui.INVALID))
            return
        if 'soon' in action:
            unfinished = action['soon'] in {f.value for f in ui.UNFINISHED}
            if unfinished:
                await self._safe(query.answer(ui.NOT_YET, show_alert=True))
            elif action['soon'] in {f.value for f in PlannedFeature}:
                # An old Phase 1 button: reopen the current menu; it never starts anything.
                await self._render(query, ui.main_text(), ui.main_keyboard(self._active()))
            else:
                await self._safe(query.answer(ui.INVALID))
            return
        if 'menu' in action:
            await self._render(query, ui.main_text(), ui.main_keyboard(self._active()))
        elif 'help' in action:
            await self._render(query, ui.help_text(), ui.help_keyboard())
        elif 'about' in action:
            await self._render(query, ui.about_text(), ui.about_keyboard())
        elif 'page' in action:
            views = self.catalog.list()
            await self._render(query, ui.sources_text(views), ui.sources_keyboard(views, int(action['page'])))
        elif 'source' in action:
            view = self.catalog.get(action['source'])
            if view is None:  # a forged or stale id never reaches data
                await self._safe(query.answer(ui.INVALID))
                return
            await self._render(query, ui.source_text(view), ui.source_keyboard(view))
        elif self.ops is None:
            await self._safe(query.answer(ui.NOT_YET))
        else:
            await self._phase2(query, action, update)

    async def _phase2(self, query, action: dict, update: Update) -> None:
        if any(key.startswith('sm_') for key in action):
            await self._manage(query, action, update)
            return
        if 'settings' in action:
            await self._render(query, ui.settings_text(self.ops.limit, self.ops.days), ui.back_keyboard())
        elif 'crawl_all' in action:
            await self._confirm(query, None, back=ui.MAIN)
        elif any(k in action for k in ('sel_page', 'sel_toggle', 'sel_all', 'sel_clear')):
            await self._selection(query, action)
        elif 'sel_ok' in action:
            enabled = {v.id for v in self.ops.enabled_sources()}
            self.selection &= enabled  # a source disabled meanwhile leaves the selection
            if not self.selection:
                await self._safe(query.answer('هیچ منبعی انتخاب نشده است.', show_alert=True))
                return
            await self._confirm(query, tuple(sorted(self.selection)), back=ui.SELECT + '0')
        elif 'go' in action:
            await self._launch(query, action['go'], update)
        elif 'no' in action:
            self.pending.pop(action['no'], None)
            await self._render(query, ui.main_text(), ui.main_keyboard(self._active()),
                               'جمع‌آوری شروع نشد.')
        elif 'job' in action:
            await self._show_job(query)
        elif 'job_cancel' in action:
            job = self.ops.jobs.cancel()
            await self._safe(query.answer('درخواست توقف ثبت شد؛ اجرا پس از پایان منبع فعلی متوقف می‌شود '
                                          'و نتیجه‌ای ثبت نمی‌شود.' if job else 'اجرایی در جریان نیست.',
                                          show_alert=True))
            if job:
                await self._edit(query, ui.job_text(job, self._names(), self.ops.progress_view(job)),
                                 ui.job_keyboard(job))
        elif 'outputs' in action:
            run = await asyncio.to_thread(self.ops.latest_exported_run)
            if run is None:
                await self._render(query, '<b>📊 دریافت خروجی</b>\nهنوز خروجی Excel معتبری ثبت نشده است. '
                                   'ابتدا از منوی اصلی یک جمع‌آوری اجرا کنید.', ui.back_keyboard())
            else:
                await self._render(query, ui.run_summary_text(run, self._names(), True, '📊 آخرین خروجی'),
                                   ui.outputs_keyboard(run.token, True, details=True))
        elif 'runs' in action:
            runs = await asyncio.to_thread(self.ops.recent_runs, 30)
            page = int(action['runs'])
            await self._render(query, ui.runs_text(runs, page), ui.runs_keyboard(runs, page))
        elif 'run' in action:
            await self._show_run(query, action['run'])
        elif 'excel' in action:
            await self._send_excel(query, action['excel'], update)
        elif 'ev_run' in action:
            await self._events(query, action['ev_run'], action['ev_kind'], int(action['ev_page']))
        elif 'ed_run' in action:
            await self._event(query, action['ed_run'], action['ed_kind'], int(action['ed_index']))

    # -- crawl -----------------------------------------------------------------
    async def _confirm(self, query, scope: tuple[str, ...] | None, back: str) -> None:
        current = self.ops.jobs.current
        if current is not None and current.status in ACTIVE:
            await self._render(query, ui.job_text(current, self._names(), self.ops.progress_view(current)),
                               ui.job_keyboard(current), ui.BUSY)
            return
        try:
            resolved = self.ops.resolve_scope(scope)
        except ValueError:
            await self._safe(query.answer('منبع فعالی برای اجرا وجود ندارد یا انتخاب شما دیگر معتبر نیست.',
                                          show_alert=True))
            return
        now = time.monotonic()
        self.pending = {k: v for k, v in self.pending.items() if now - v[1] < CONFIRM_TTL}
        nonce = secrets.token_hex(6)
        self.pending[nonce] = (scope, now, resolved)  # the snapshot the owner sees is the one that runs
        views = tuple(v for v in self.ops.enabled_sources() if v.id in resolved)
        estimate = await asyncio.to_thread(self.ops.preview_estimate, resolved)
        await self._render(query, ui.crawl_confirm_text(views, scope is None, self.ops.limit, self.ops.days, estimate),
                           ui.confirm_keyboard(nonce, back))

    async def _launch(self, query, nonce: str, update: Update) -> None:
        pending = self.pending.pop(nonce, None)  # one-time: a replayed tap finds nothing
        if pending is None or time.monotonic() - pending[1] >= CONFIRM_TTL:
            await self._safe(query.answer(ui.INVALID, show_alert=True))
            return
        scope, expected = pending[0], (pending[2] if len(pending) > 2 else None)
        try:
            job = self.ops.start_crawl(scope, expected=expected)
        except JobBusyError as busy:
            await self._render(query, ui.job_text(busy.current, self._names()), ui.job_keyboard(busy.current), ui.BUSY)
            return
        except ValueError:  # the registry changed: a source is now unknown, disabled or archived
            await self._safe(query.answer('فهرست منابع پس از تأیید تغییر کرده است؛ چیزی اجرا نشد. '
                                          'دوباره انتخاب و تأیید کنید.', show_alert=True))
            return
        self.loop = asyncio.get_running_loop()
        self.status_messages[job.job_id] = (update.effective_chat.id, query.message.message_id)
        self.selection.clear()
        await self._safe(query.get_bot().send_chat_action(update.effective_chat.id, ChatAction.TYPING))
        await self._render(query, ui.job_text(job, self._names(), self.ops.progress_view(job)),
                           ui.job_keyboard(job), 'جمع‌آوری شروع شد.')
        self._last_edit[job.job_id] = (time.monotonic(), '')
        self._start_ticker(job.job_id)

    async def _selection(self, query, action: dict) -> None:
        views = self.ops.enabled_sources()
        enabled = {v.id for v in views}
        if 'sel_toggle' in action:
            source = action['sel_toggle']
            if source not in enabled:  # disabled, unknown or forged
                await self._safe(query.answer(ui.INVALID, show_alert=True))
                return
            self.selection ^= {source}
            page = int(action['sel_toggle_page'])
        elif 'sel_all' in action:
            self.selection = set(enabled)
            page = int(action['sel_all'])
        elif 'sel_clear' in action:
            self.selection.clear()
            page = int(action['sel_clear'])
        else:
            page = int(action['sel_page'])
        self.selection &= enabled
        await self._render(query, ui.selection_text(views, self.selection),
                           ui.selection_keyboard(views, self.selection, page))

    async def _show_job(self, query) -> None:
        job = self.ops.jobs.current or next(iter(reversed(self.ops.jobs.store.read())), None)
        if job is None:
            await self._render(query, '<b>وضعیت اجرا</b>\nهنوز اجرایی از طریق ربات انجام نشده است.', ui.back_keyboard())
        elif job.status in ACTIVE:
            await self._render(query, ui.job_text(job, self._names(), self.ops.progress_view(job)), ui.job_keyboard(job))
        else:
            await self._show_run(query, job.job_id[:12])

    # -- live progress -------------------------------------------------------------
    def _start_ticker(self, job_id: str) -> None:
        """One ticker per job: elapsed time keeps moving during a long source."""
        task = self._tickers.get(job_id)
        if task is not None and not task.done():
            return
        self._tickers[job_id] = asyncio.get_running_loop().create_task(self._ticker(job_id))

    async def _ticker(self, job_id: str) -> None:
        try:
            while job_id in self.status_messages:
                await asyncio.sleep(self.tick_interval)
                job = self.ops.jobs.current
                if job is None or job.job_id != job_id or job.status not in ACTIVE:
                    break
                self._frames[job_id] = self._frames.get(job_id, 0) + 1
                await self._push(job, final=False)
        except asyncio.CancelledError:
            pass
        except Exception as error:  # progress display never affects the crawl
            LOGGER.warning('telegram_progress_ticker_failed: %s', type(error).__name__)
        finally:
            self._tickers.pop(job_id, None)

    async def close(self, application=None) -> None:
        """Shutdown: stop every progress loop; the crawl itself is stopped by the runner."""
        for task in list(self._tickers.values()):
            task.cancel()
        for task in list(self._tickers.values()):
            try:
                await task
            except BaseException:
                pass
        self._tickers.clear()

    def _job_changed(self, job: JobRecord) -> None:
        """Called in the worker thread; schedules a bounded number of edits."""
        if self.loop is None or self.loop.is_closed() or job.job_id not in self.status_messages:
            return
        final = job.status not in ACTIVE
        try:
            asyncio.run_coroutine_threadsafe(self._push(job, final=final), self.loop)
        except RuntimeError:  # the loop is shutting down
            pass

    async def _push(self, job: JobRecord, *, final: bool) -> None:
        lock = self._edit_locks.setdefault(job.job_id, asyncio.Lock())
        async with lock:
            target = self.status_messages.get(job.job_id)
            if target is None:
                return
            now = time.monotonic()
            if not final:
                key = f'{job.status}:{job.stage}:{job.current_source}:{job.done_sources}'
                text = ui.job_text(job, self._names(), self.ops.progress_view(job), self._frames.get(job.job_id, 0))
                last_time, last_text = self._last_edit.get(job.job_id, (0.0, ''))
                if text == last_text or now - last_time < self.min_edit_interval or now < self._backoff_until:
                    return
                self._last_edit[job.job_id] = (now, text)
                await self._edit_status(job.job_id, target, text, ui.job_keyboard(job), final=False)
                return
            text, markup = await self._final_view(job)
            self.status_messages.pop(job.job_id, None)
            task = self._tickers.pop(job.job_id, None)
            if task is not None and task is not asyncio.current_task():
                task.cancel()
            await self._edit_status(job.job_id, target, text, markup, final=True)
            self._last_edit.pop(job.job_id, None)
            self._frames.pop(job.job_id, None)

    async def _final_view(self, job: JobRecord):
        run = await asyncio.to_thread(self.ops.find_run, job.job_id[:12])
        if run is None:
            return ui.job_text(job, self._names()), ui.back_keyboard()
        excel = run.persisted and (await asyncio.to_thread(self.ops.workbook_for, run.run_id)).ok
        text = ui.run_summary_text(run, self._names(), job.export_ok if run.persisted else None,
                                   duration_seconds=job.duration_seconds)
        if job.message:
            text += '\n\n' + ui.e(job.message)
        return text, ui.outputs_keyboard(run.token if run.persisted else None, excel, details=run.persisted)

    async def _edit_status(self, job_id: str, target: tuple[int, int], text: str, markup, *, final: bool) -> None:
        chat_id, message_id = target
        for attempt in range(2):
            try:
                await self.bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, parse_mode='HTML',
                                                 reply_markup=markup, disable_web_page_preview=True)
                return
            except RetryAfter as error:
                wait = _retry_seconds(error)
                self._backoff_until = time.monotonic() + wait
                if not final or attempt:
                    LOGGER.warning('telegram_progress_rate_limited')
                    return
                await asyncio.sleep(wait)  # the final result is worth one bounded wait
            except BadRequest as error:
                message = str(error).lower()
                if 'not modified' in message:
                    return
                if 'not found' in message or "can't be edited" in message:
                    # The status message was deleted or is too old: continue in a new one.
                    try:
                        sent = await self.bot.send_message(chat_id, text, parse_mode='HTML', reply_markup=markup,
                                                           disable_web_page_preview=True)
                        if not final and job_id in self.status_messages:
                            self.status_messages[job_id] = (chat_id, sent.message_id)
                    except TelegramError as again:
                        LOGGER.warning('telegram_progress_send_failed: %s', type(again).__name__)
                    return
                LOGGER.warning('telegram_progress_edit_failed: %s', type(error).__name__)
                return
            except TelegramError as error:  # transient network failure: the next tick retries
                LOGGER.warning('telegram_progress_edit_failed: %s', type(error).__name__)
                if not final or attempt:
                    return
                await asyncio.sleep(2)

    # -- runs, outputs and events (read-only) ------------------------------------
    async def _run(self, token: str):
        return await asyncio.to_thread(self.ops.find_run, token)

    async def _show_run(self, query, token: str) -> None:
        run = await self._run(token)
        if run is None:
            await self._safe(query.answer(ui.INVALID, show_alert=True))
            return
        check = await asyncio.to_thread(self.ops.workbook_for, run.run_id) if run.persisted else None
        job = await asyncio.to_thread(self.ops.jobs.store.get, run.run_id)
        text = ui.run_summary_text(run, self._names(), check.ok if check else None,
                                   duration_seconds=job.duration_seconds if job is not None else None)
        if job is not None and job.message and not run.persisted:
            text += '\n\n' + ui.e(job.message)
        if check is not None and not check.ok:
            text += '\n\n' + ui.e(check.reason)
        await self._render(query, text, ui.outputs_keyboard(run.token if run.persisted else None,
                                                            bool(check and check.ok)))

    async def _send_excel(self, query, token: str, update: Update) -> None:
        run = await self._run(token)
        if run is None or not run.persisted:
            await self._safe(query.answer(ui.INVALID, show_alert=True))
            return
        check = await asyncio.to_thread(self.ops.workbook_for, run.run_id)
        if not check.ok:  # never send an older or unrelated file instead
            await self._safe(query.answer(check.reason, show_alert=True))
            return
        await self._safe(query.answer('در حال ارسال فایل Excel…'))
        await self._safe(query.get_bot().send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_DOCUMENT))
        content = await asyncio.to_thread(check.path.read_bytes)
        try:
            await query.get_bot().send_document(update.effective_chat.id, document=content,
                                                filename=check.filename,
                                                caption=ui.excel_caption(run, check.sheet, self._names()))
        except TelegramError as error:
            LOGGER.warning('telegram_document_failed: %s', type(error).__name__)
            await self._safe(query.get_bot().send_message(update.effective_chat.id,
                                                          'ارسال فایل ناموفق بود؛ دوباره تلاش کنید.'))

    async def _records(self, token: str, kind: str):
        run = await self._run(token)
        if run is None or not run.persisted:
            return None, None
        document = await asyncio.to_thread(self.ops.run_document, run.run_id)
        if document is None:
            return None, None
        return run, document['events'] if kind == 'a' else document.get('schedule_review', [])

    async def _events(self, query, token: str, kind: str, page: int) -> None:
        run, records = await self._records(token, kind)
        if run is None:
            await self._safe(query.answer(ui.INVALID, show_alert=True))
            return
        await self._render(query, ui.events_text(records, kind, page, run),
                           ui.events_keyboard(records, kind, page, run.token))

    async def _event(self, query, token: str, kind: str, index: int) -> None:
        run, records = await self._records(token, kind)
        if run is None or not 0 <= index < len(records):  # stale or forged index
            await self._safe(query.answer(ui.INVALID, show_alert=True))
            return
        await self._render(query, ui.event_text(records[index], kind, index, len(records)),
                           ui.event_keyboard(records[index], kind, index, len(records), run.token))

    # -- source management (Phase 3) ---------------------------------------------------
    async def _manage(self, query, action: dict, update: Update) -> None:
        from ..source_registry import RegistryError
        if 'sm_home' in action:
            await self._manage_home(query)
        elif 'sm_filter' in action:
            kind, page = action['sm_filter'], int(action['sm_page'])
            views = ui.filter_views(self.catalog.all(), kind)
            await self._render(query, ui.manage_list_text(views, kind, page), ui.manage_list_keyboard(views, kind, page))
        elif 'sm_view' in action:
            view = self.catalog.get(action['sm_view'])
            if view is None:
                await self._safe(query.answer(ui.INVALID, show_alert=True))
                return
            await self._render(query, ui.source_text(view), ui.manage_source_keyboard(view))
        elif 'sm_op' in action:
            await self._ask_action(query, action['sm_target'], ui.ACTIONS[action['sm_op']])
        elif 'sm_ok' in action:
            await self._apply_action(query, action['sm_ok'], RegistryError)
        elif 'sm_no' in action:
            pending = self.source_actions.pop(action['sm_no'], None)
            view = self.catalog.get(pending[0]) if pending else None
            if view is None:
                await self._manage_home(query, 'تغییری انجام نشد.')
            else:
                await self._render(query, ui.source_text(view) + '\n\nتغییری انجام نشد.',
                                   ui.manage_source_keyboard(view))
        elif 'sm_addmenu' in action:
            if self._active():
                await self._safe(query.answer(ui.ERRORS['busy'], show_alert=True))
                return
            self.conversation = Conversation('type', time.monotonic())
            await self._render(query, ui.add_type_text(), ui.add_type_keyboard())
        elif 'sm_add' in action:
            if self._conversation() is None:
                self.conversation = Conversation('type', time.monotonic())
            self.conversation.kind = 'instagram' if action['sm_add'] == 'i' else 'website'
            self.conversation.step, self.conversation.proposal, self.conversation.nonce = 'input', None, None
            await self._render(query, ui.add_input_text(self.conversation.kind), ui.add_input_keyboard())
        elif 'sm_back' in action:
            conversation = self._conversation()
            if conversation is None or conversation.kind is None:
                await self._manage_home(query, ui.ERRORS['expired'])
                return
            conversation.step, conversation.proposal, conversation.nonce = 'input', None, None
            await self._render(query, ui.add_input_text(conversation.kind), ui.add_input_keyboard())
        elif 'sm_cancel' in action:
            self.conversation = None
            await self._manage_home(query, 'افزودن منبع لغو شد؛ چیزی ذخیره نشد.')
        elif 'sm_save' in action:
            await self._save_source(query, action['sm_save'], action['sm_mode'] == 'a', RegistryError)

    async def _manage_home(self, query, notice: str | None = None) -> None:
        counts = await asyncio.to_thread(self.ops.management_counts)
        if self._active():
            notice = ((notice + '\n') if notice else '') + ui.ERRORS['busy']
        await self._render(query, ui.manage_text(counts, notice), ui.manage_keyboard())

    @staticmethod
    def _applicable(view, action: str) -> bool:
        if action == 'restore':
            return view.archived
        if view.archived:
            return False
        if action == 'enable':
            return not view.enabled and not view.locked
        if action == 'disable':
            return view.enabled
        return action == 'archive'

    async def _ask_action(self, query, source_id: str, action: str) -> None:
        view = self.catalog.get(source_id)
        if view is None or not self._applicable(view, action):  # forged, stale or locked
            await self._safe(query.answer(ui.ERRORS['locked'] if view is not None and view.locked
                                          and action == 'enable' else ui.INVALID, show_alert=True))
            return
        if self._active():
            await self._safe(query.answer(ui.ERRORS['busy'], show_alert=True))
            return
        now = time.monotonic()
        self.source_actions = {k: v for k, v in self.source_actions.items() if now - v[2] < CONFIRM_TTL}
        nonce = secrets.token_hex(6)
        self.source_actions[nonce] = (source_id, action, now)
        await self._render(query, ui.action_confirm_text(view, action), ui.action_confirm_keyboard(nonce, action, source_id))

    async def _apply_action(self, query, nonce: str, registry_error) -> None:
        from .operations import RegistryBusyError
        pending = self.source_actions.pop(nonce, None)  # one-time
        if pending is None or time.monotonic() - pending[2] >= CONFIRM_TTL:
            await self._safe(query.answer(ui.INVALID, show_alert=True))
            return
        source_id, action, _ = pending
        view = self.catalog.get(source_id)
        if view is None or not self._applicable(view, action):  # re-checked at confirmation
            await self._safe(query.answer(ui.ERRORS['stale'], show_alert=True))
            return
        try:
            await asyncio.to_thread(self.ops.change_source, source_id, action)
        except RegistryBusyError:
            await self._safe(query.answer(ui.ERRORS['busy'], show_alert=True))
            return
        except registry_error as error:
            await self._safe(query.answer(ui.error_text(error.code, error.source_id), show_alert=True))
            return
        view = self.catalog.get(source_id)
        await self._render(query, ui.source_text(view) + '\n\n✅ ' + ui.ACTION_DONE[action],
                           ui.manage_source_keyboard(view), 'انجام شد.')

    def _conversation(self) -> Conversation | None:
        conversation = self.conversation
        if conversation is not None and time.monotonic() - conversation.started >= CONVERSATION_TTL:
            self.conversation = conversation = None
        return conversation

    async def text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Free text is accepted only as the address step of an add-source conversation."""
        if not self._owner(update) or update.effective_message is None:
            return
        conversation = self._conversation()
        message = update.effective_message
        if conversation is None or conversation.step not in ('input', 'preview') or conversation.kind is None:
            await message.reply_html('برای شروع از منوی زیر یک گزینه را انتخاب کنید.',
                                     reply_markup=ui.main_keyboard(self._active()))
            return
        from ..source_intake import IntakeError
        await self._safe(context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING))
        try:
            proposal = await asyncio.to_thread(self.ops.propose_source, conversation.kind, message.text or '')
        except IntakeError as error:
            archived = bool(error.source_id and (view := self.catalog.get(error.source_id)) and view.archived)
            # Invalid input keeps the conversation at the same step.
            await message.reply_html(ui.add_input_text(conversation.kind, ui.error_text(error.code, error.source_id,
                                                                                       archived)),
                                     reply_markup=ui.add_input_keyboard())
            return
        except ValueError:
            await message.reply_html(ui.add_input_text(conversation.kind, ui.ERRORS['format']),
                                     reply_markup=ui.add_input_keyboard())
            return
        conversation.step, conversation.proposal = 'preview', proposal
        conversation.nonce = secrets.token_hex(6)
        await message.reply_html(ui.preview_text(proposal), reply_markup=ui.preview_keyboard(conversation.nonce,
                                                                                            proposal.runnable),
                                 disable_web_page_preview=True)

    async def _save_source(self, query, nonce: str, activate: bool, registry_error) -> None:
        from .operations import RegistryBusyError
        conversation = self._conversation()
        if conversation is None or conversation.step != 'preview' or conversation.nonce != nonce:
            # An old preview, a second tap after saving, or a restart: nothing is committed.
            await self._safe(query.answer(ui.ERRORS['expired'], show_alert=True))
            return
        conversation.nonce = None  # one-time
        try:
            entry = await asyncio.to_thread(self.ops.register_source, conversation.proposal, activate=activate)
        except RegistryBusyError:
            conversation.nonce = nonce  # nothing saved; the owner can retry after the crawl
            await self._safe(query.answer(ui.ERRORS['busy'], show_alert=True))
            return
        except registry_error as error:
            self.conversation = None
            await self._render(query, ui.manage_text(await asyncio.to_thread(self.ops.management_counts),
                                                     ui.error_text(error.code, error.source_id)), ui.manage_keyboard())
            return
        self.conversation = None
        activated = activate and conversation.proposal.runnable
        await self._render(query, ui.saved_text(entry, activated), ui.manage_source_keyboard(self.catalog.get(entry.source.id)),
                           'ذخیره شد.')

    def _names(self) -> dict[str, str]:
        return {v.id: v.name for v in self.catalog.all()}

    # -- message helpers ---------------------------------------------------------
    async def _render(self, query, text, markup, notice: str | None = None) -> None:
        await self._safe(query.answer(notice) if notice else query.answer())
        await self._edit(query, text, markup)

    async def _edit(self, query, text, markup) -> None:
        try:
            await query.edit_message_text(text, parse_mode='HTML', reply_markup=markup,
                                          disable_web_page_preview=True)
        except RetryAfter:
            LOGGER.warning('telegram_edit_rate_limited')  # the owner can tap again; nothing is lost
        except BadRequest as error:
            # A repeated tap re-renders the same content; Telegram refuses that edit.
            if 'not modified' not in str(error).lower():
                raise

    @staticmethod
    async def _safe(awaitable) -> None:
        try:
            await awaitable
        except TelegramError as error:
            # An expired callback query or a transient network failure: logged, not raised.
            LOGGER.warning('telegram_reply_failed: %s', type(error).__name__)

    # -- errors ----------------------------------------------------------------
    async def on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        error = context.error
        if isinstance(error, Conflict):
            LOGGER.error('telegram_polling_conflict: another process is polling this bot; stopping.')
            context.application.stop_running()
            return
        LOGGER.error('telegram_handler_error: %s', type(error).__name__, exc_info=error)
        if isinstance(update, Update) and self.policy.is_owner(update) and update.effective_chat is not None:
            await self._safe(context.bot.send_message(update.effective_chat.id, ui.ERROR))


def register(application: Application, handlers: BotHandlers) -> None:
    handlers.bot = application.bot
    application.add_handler(TypeHandler(Update, handlers.guard), group=-1)
    application.add_handler(CommandHandler(['start', 'menu'], handlers.start))
    application.add_handler(CommandHandler('help', handlers.help))
    application.add_handler(CommandHandler('sources', handlers.sources))
    application.add_handler(CommandHandler('whoami', handlers.whoami))
    application.add_handler(CommandHandler('cancel', handlers.cancel))
    application.add_handler(CallbackQueryHandler(handlers.callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handlers.text))
    application.bot_data['gatherradar_handlers'] = handlers
    application.add_error_handler(handlers.on_error)


async def publish_commands(application: Application, settings: TelegramSettings) -> None:
    """Default scope shows only /whoami; the owner's private chat gets the full list."""
    bot = application.bot
    await bot.set_my_commands([BotCommand('whoami', 'شناسه من')], scope=BotCommandScopeDefault())
    if settings.owner_id is not None:
        await bot.set_my_commands([BotCommand(c, d) for c, d in OWNER_COMMANDS],
                                  scope=BotCommandScopeChat(settings.owner_id))
