from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.mail_adapter import (
    QuietMailMessageEvent,
    mail_retry_delay,
    mark_mail_seen,
)


class _Response:
    result = "OK"


class _FakeIMAP:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    async def store(self, *criteria: str) -> _Response:
        self.calls.append(criteria)
        return _Response()


@pytest.mark.parametrize(
    ("attempt", "expected"),
    [(0, 3.0), (1, 6.0), (2, 12.0), (3, 24.0), (4, 48.0), (5, 60.0), (99, 60.0)],
)
def test_mail_retry_delay_is_bounded_exponential(attempt: int, expected: float) -> None:
    assert mail_retry_delay(attempt) == expected


@pytest.mark.asyncio
async def test_mark_mail_seen_sets_seen_flag_after_fetch() -> None:
    imap = _FakeIMAP()

    await mark_mail_seen(imap, "42")

    assert imap.calls == [("42", "+FLAGS", "\\Seen")]


def test_quiet_mail_event_description_excludes_body() -> None:
    event = QuietMailMessageEvent(
        id="<mail@example.com>",
        sender={"id": "sender@example.com", "name": "Sender"},
        subject="测试主题",
        recipients_to=[],
        recipients_cc=[],
        recipients_bcc=[],
        date=None,
        timezone=None,
        message={"type": "text", "data": {"text": "secret body"}},
        original_message={"type": "text", "data": {"text": "secret body"}},
    )

    description = event.get_event_description()
    assert "测试主题" in description
    assert "secret body" not in description
    assert QuietMailMessageEvent.__module__ == "nonebot.adapters.mail.event"
