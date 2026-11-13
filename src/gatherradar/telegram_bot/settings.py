"""Telegram settings from environment variables only; the token is never printed."""
from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

TOKEN_ENV = 'GATHERRADAR_TELEGRAM_BOT_TOKEN'
OWNER_ENV = 'GATHERRADAR_TELEGRAM_OWNER_ID'
EXPECTED_USERNAME = 'GatherRadar_Bot'
# BotFather tokens: "<numeric bot id>:<secret>".
_TOKEN = re.compile(r'[0-9]{5,15}:[A-Za-z0-9_-]{30,100}')


class SettingsError(ValueError):
    """A configuration problem whose message never contains the token."""


@dataclass(frozen=True)
class TelegramSettings:
    token: str = field(repr=False)
    owner_id: int | None = None
    expected_username: str = EXPECTED_USERNAME

    def __post_init__(self) -> None:
        if not isinstance(self.token, str) or not _TOKEN.fullmatch(self.token):
            raise SettingsError(f'{TOKEN_ENV} is missing or not a BotFather token.')
        if self.owner_id is not None and (type(self.owner_id) is not int or self.owner_id <= 0):
            raise SettingsError(f'{OWNER_ENV} must be a positive numeric Telegram user ID.')

    @property
    def bootstrap(self) -> bool:
        """No owner yet: only /whoami answers, nothing administrative."""
        return self.owner_id is None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> TelegramSettings:
        env = os.environ if environ is None else environ
        token = (env.get(TOKEN_ENV) or '').strip()
        if not token:
            raise SettingsError(f'{TOKEN_ENV} is not set.')
        raw_owner = (env.get(OWNER_ENV) or '').strip()
        if raw_owner and not raw_owner.isdigit():
            raise SettingsError(f'{OWNER_ENV} must be a positive numeric Telegram user ID.')
        return cls(token=token, owner_id=int(raw_owner) if raw_owner else None)


def redact(text: str, token: str | None) -> str:
    """Remove a token (and its secret half) from text before it is logged."""
    if token:
        text = text.replace(token, '[REDACTED]')
        secret = token.split(':', 1)[-1]
        if len(secret) >= 20:
            text = text.replace(secret, '[REDACTED]')
    return text
