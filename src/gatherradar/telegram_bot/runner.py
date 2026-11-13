"""Process lifecycle: settings, one local instance, identity check, long polling."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from telegram import Bot, Update
from telegram.error import Conflict, InvalidToken, NetworkError, TelegramError, TimedOut
from telegram.ext import Application, ApplicationBuilder
from telegram.request import BaseRequest

from .handlers import BotHandlers, publish_commands, register
from .lock import SingleInstanceLock
from .services import SourceCatalog
from .settings import TelegramSettings, redact

LOGGER = logging.getLogger('gatherradar.telegram')
STARTUP_ATTEMPTS = 3
STARTUP_BACKOFF_SECONDS = (2.0, 5.0)


class StartupError(RuntimeError):
    """A start-up refusal with a safe, token-free message."""


class RedactingFilter(logging.Filter):
    """Removes the bot token from every log record (httpx logs request URLs)."""

    def __init__(self, token: str) -> None:
        super().__init__()
        self.token = token

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        clean = redact(message, self.token)
        if clean != message:
            record.msg, record.args = clean, ()
        return True


def configure_logging(settings: TelegramSettings, level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    redactor = RedactingFilter(settings.token)
    for handler in logging.getLogger().handlers:
        handler.addFilter(redactor)
    # httpx/httpcore log full request URLs, which contain the token, at INFO/DEBUG.
    for name in ('httpx', 'httpcore'):
        logging.getLogger(name).setLevel(logging.WARNING)


async def verify_identity(bot: Bot, expected: str, attempts: int = STARTUP_ATTEMPTS,
                          backoff: tuple[float, ...] = STARTUP_BACKOFF_SECONDS) -> str:
    """getMe with bounded retries on network errors; the username must match."""
    for attempt in range(attempts):
        try:
            me = await bot.get_me()
            break
        except InvalidToken:
            raise StartupError('Telegram rejected the bot token. Check GATHERRADAR_TELEGRAM_BOT_TOKEN.') from None
        except (NetworkError, TimedOut) as error:
            if attempt == attempts - 1:
                raise StartupError('Telegram is unreachable (network error). Check the internet connection '
                                   f'or proxy and retry. Last error: {type(error).__name__}.') from None
            await asyncio.sleep(backoff[min(attempt, len(backoff) - 1)])
        except TelegramError as error:
            raise StartupError(f'Telegram refused getMe ({type(error).__name__}).') from None
    if (me.username or '').lower() != expected.lower():
        raise StartupError(f'This token belongs to @{me.username}, not @{expected}. '
                           'Use the GatherRadar bot token.')
    return me.username


def build_application(settings: TelegramSettings, catalog: SourceCatalog,
                      request: BaseRequest | None = None, operations=None) -> Application:
    builder = ApplicationBuilder().token(settings.token).concurrent_updates(False)
    if request is not None:
        builder = builder.request(request).get_updates_request(request)
    application = builder.build()
    register(application, BotHandlers(settings, catalog, operations))
    return application


async def preflight(settings: TelegramSettings, request: BaseRequest | None = None) -> str:
    async with Bot(settings.token, request=request) as bot:
        return await verify_identity(bot, settings.expected_username)


def run_bot(settings: TelegramSettings, *, config_path: str | Path = 'config/sources.yaml',
            data_dir: str | Path = 'data') -> int:
    configure_logging(settings)
    catalog = SourceCatalog(config_path)
    catalog.list()  # fail early on an unreadable registry, before polling
    with SingleInstanceLock(Path(data_dir) / 'telegram' / 'bot.lock'):
        username = asyncio.run(preflight(settings))
        mode = 'bootstrap (/whoami only)' if settings.bootstrap else 'owner configured'
        LOGGER.info('telegram_bot_starting username=@%s mode=%s', username, mode)
        from .operations import LocalOperations
        operations = LocalOperations(catalog, data_dir=data_dir, config_path=config_path)
        application = build_application(settings, catalog, operations=operations)

        async def post_init(app: Application) -> None:
            await publish_commands(app, settings)

        async def post_shutdown(app: Application) -> None:
            handlers = app.bot_data.get('gatherradar_handlers')
            if handlers is not None:
                await handlers.close()  # stop progress loops; no orphaned timers

        application.post_init = post_init
        application.post_shutdown = post_shutdown
        try:
            # Long polling only; stale commands queued while offline are discarded
            # so nothing old is executed after a restart.
            application.run_polling(allowed_updates=[Update.MESSAGE, Update.CALLBACK_QUERY],
                                    drop_pending_updates=True, bootstrap_retries=STARTUP_ATTEMPTS)
        except Conflict:
            raise StartupError('Another process is already polling this bot (maybe on another computer). '
                               'Stop it and retry.') from None
        finally:
            # Never abandon a crawl mid-write: stop at the next safe boundary and wait.
            if operations.jobs.cancel() is not None:
                LOGGER.info('telegram_bot_stopping: waiting for the current source to finish safely')
            operations.jobs.wait()
        LOGGER.info('telegram_bot_stopped')
    return 0
