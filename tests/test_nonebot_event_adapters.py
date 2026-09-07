from __future__ import annotations

from types import SimpleNamespace

from plugins.bot_unified_runtime import _incoming_from_nonebot_event
from plugins.bot_unified_runtime.contracts import SessionType


class BaseFakeEvent:
    __module__ = "nonebot.adapters.telegram.event"

    def __init__(self, text: str, session_id: str, chat_id: int | None = None) -> None:
        self._text = text
        self._session_id = session_id
        self.chat = SimpleNamespace(id=chat_id) if chat_id is not None else None
        self.message_id = 42

    def get_plaintext(self) -> str:
        return self._text

    def get_session_id(self) -> str:
        return self._session_id


class TelegramPrivateEvent(BaseFakeEvent):
    __module__ = "nonebot.adapters.telegram.event"
    def get_user_id(self) -> str:
        return "1001"

    def is_tome(self) -> bool:
        return True


class TelegramGroupEvent(BaseFakeEvent):
    __module__ = "nonebot.adapters.telegram.event"
    def get_user_id(self) -> str:
        return "1002"

    def is_tome(self) -> bool:
        return False


class TelegramChannelEvent(BaseFakeEvent):
    __module__ = "nonebot.adapters.telegram.event"
    sender_chat = SimpleNamespace(id=777)

    def get_user_id(self) -> str:
        raise ValueError("Event has no user!")


class MailEvent:
    __module__ = "nonebot.adapters.mail.event"

    id = "mail-1"
    subject = "问候"
    sender = SimpleNamespace(id="user@example.com")

    def get_plaintext(self) -> str:
        return "正文"

    def get_session_id(self) -> str:
        return "user@example.com"

    def get_user_id(self) -> str:
        return "user@example.com"


def test_telegram_private_event_maps_to_private_message() -> None:
    incoming = _incoming_from_nonebot_event(
        TelegramPrivateEvent("你好", "private_10", 10),
        bot_id="bot-1",
    )

    assert incoming.platform == "telegram"
    assert incoming.adapter == "telegram"
    assert incoming.session_type is SessionType.PRIVATE
    assert incoming.sender_id == "1001"
    assert incoming.mentions_bot is True


def test_telegram_group_event_maps_chat_and_sender_separately() -> None:
    incoming = _incoming_from_nonebot_event(
        TelegramGroupEvent("你好", "group_20_1002", 20),
        bot_id="bot-1",
    )

    assert incoming.session_type is SessionType.GROUP
    assert incoming.group_id == "20"
    assert incoming.sender_id == "1002"


def test_telegram_channel_post_without_get_user_id_uses_sender_chat_id() -> None:
    incoming = _incoming_from_nonebot_event(
        TelegramChannelEvent("公告", "channel_30", 30),
        bot_id="bot-1",
    )

    assert incoming.session_type is SessionType.CHANNEL
    assert incoming.group_id == "30"
    assert incoming.sender_id == "777"
    assert incoming.mentions_bot is False


def test_mail_event_maps_subject_and_email_session() -> None:
    incoming = _incoming_from_nonebot_event(MailEvent(), bot_id="bot@qq.com")

    assert incoming.platform == "email"
    assert incoming.adapter == "mail"
    assert incoming.session_type is SessionType.EMAIL
    assert incoming.sender_id == "user@example.com"
    assert incoming.session_id == "email:user@example.com"
    assert incoming.plain_text == "主题：问候\n\n正文"



