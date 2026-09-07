from __future__ import annotations

from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.runtime.disconnect_notice import (
    DisconnectNoticeOptions,
    DisconnectNotifier,
    adapter_display_name,
    build_disconnect_notice_text,
    disconnect_notice_options_from,
)


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _TelegramAdapter:
    def get_name(self) -> str:
        return "Telegram"


class _TelegramBot:
    adapter = _TelegramAdapter()
    self_id = "tg-bot"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_to(self, chat_id: str, body: str, **kwargs: object) -> None:
        self.sent.append((chat_id, body))


def _bots(telegram_bot: object | None = None) -> dict[str, object]:
    bots: dict[str, object] = {}
    if telegram_bot is not None:
        bots["tg"] = telegram_bot
    return bots


def test_options_parse_and_filter_blank_entries() -> None:
    config = SimpleNamespace(
        bot_disconnect_notice_enabled=True,
        bot_disconnect_notice_cooldown_seconds="30",
        bot_disconnect_notice_mail_account=" sender@example.com ",
        bot_disconnect_notice_mail_recipients=["a@example.com", " ", ""],
        bot_disconnect_notice_telegram_chat_ids=[" 12345 ", ""],
    )

    options = disconnect_notice_options_from(config)

    assert options == DisconnectNoticeOptions(
        enabled=True,
        cooldown_seconds=30.0,
        mail_account="sender@example.com",
        mail_recipients=("a@example.com",),
        telegram_chat_ids=("12345",),
    )


def test_notice_text_includes_adapter_account_and_optional_reason() -> None:
    text = build_disconnect_notice_text("10000", "OneBot V11", "")
    assert "OneBot V11" in text
    assert "10000" in text
    assert "原因" not in text
    assert "原因：被风控" in build_disconnect_notice_text("10000", "OneBot V11", "被风控")


def test_adapter_display_name_prefers_adapter_get_name() -> None:
    bot = SimpleNamespace(adapter=SimpleNamespace(get_name=lambda: "Mail"))
    assert adapter_display_name(bot) == "Mail"
    assert adapter_display_name(SimpleNamespace(adapter=None)) == "未知适配器"


@pytest.mark.asyncio
async def test_notify_delivers_once_then_respects_cooldown() -> None:
    clock = _FakeClock()
    telegram = _TelegramBot()
    notifier = DisconnectNotifier(
        DisconnectNoticeOptions(
            enabled=True,
            cooldown_seconds=600.0,
            telegram_chat_ids=("12345",),
        ),
        clock=clock,
    )

    delivered = await notifier.notify(_bots(telegram), bot_id="10000", adapter_name="OneBot V11")

    assert delivered == ["telegram"]
    assert telegram.sent == [("12345", build_disconnect_notice_text("10000", "OneBot V11"))]

    clock.advance(60.0)
    assert await notifier.notify(_bots(telegram), bot_id="10000", adapter_name="OneBot V11") == []

    clock.advance(600.0)
    assert await notifier.notify(_bots(telegram), bot_id="10000", adapter_name="OneBot V11") == [
        "telegram"
    ]


@pytest.mark.asyncio
async def test_notify_disabled_returns_empty_without_sending() -> None:
    telegram = _TelegramBot()
    notifier = DisconnectNotifier(
        DisconnectNoticeOptions(enabled=False, telegram_chat_ids=("12345",)),
        clock=_FakeClock(),
    )

    assert await notifier.notify(_bots(telegram), bot_id="1") == []
    assert telegram.sent == []


@pytest.mark.asyncio
async def test_notify_channel_failure_does_not_raise_or_block_other_channel() -> None:
    class _ExplodingTelegramBot:
        adapter = _TelegramAdapter()
        self_id = "tg-bot"

        async def send_to(self, chat_id: str, body: str, **kwargs: object) -> None:
            raise RuntimeError("telegram down")

    class _MailAdapter:
        def get_name(self) -> str:
            return "Mail"

    class _MailBot:
        adapter = _MailAdapter()
        self_id = "sender@example.com"

        def __init__(self) -> None:
            self.mails: list[str] = []

        async def send_to(self, recipient: str, body: str, **kwargs: object) -> None:
            self.mails.append(recipient)

    mail_bot = _MailBot()
    notifier = DisconnectNotifier(
        DisconnectNoticeOptions(
            enabled=True,
            cooldown_seconds=0.0,
            mail_account="sender@example.com",
            mail_recipients=("admin@example.com",),
            telegram_chat_ids=("12345",),
        ),
        clock=_FakeClock(),
    )
    bots = {"tg": _ExplodingTelegramBot(), "mail": mail_bot}

    delivered = await notifier.notify(bots, bot_id="10000", adapter_name="OneBot V11")

    assert delivered == ["mail:admin@example.com"]
    assert mail_bot.mails == ["admin@example.com"]
