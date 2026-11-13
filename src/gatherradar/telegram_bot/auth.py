"""Owner policy: one numeric Telegram user, in a private chat. Nothing else."""
from __future__ import annotations

from dataclasses import dataclass

from telegram import Update
from telegram.constants import ChatType


@dataclass(frozen=True)
class OwnerPolicy:
    owner_id: int | None

    def is_owner(self, update: Update) -> bool:
        """True only for the configured owner in a private chat with the bot."""
        user, chat = update.effective_user, update.effective_chat
        return (self.owner_id is not None and user is not None and chat is not None
                and user.id == self.owner_id and chat.type == ChatType.PRIVATE
                and chat.id == self.owner_id)

    def may_ask_whoami(self, update: Update) -> bool:
        """Bootstrap only: anyone in a private chat may learn their own ID."""
        chat = update.effective_chat
        if self.owner_id is not None:
            return self.is_owner(update)
        return update.effective_user is not None and chat is not None and chat.type == ChatType.PRIVATE
