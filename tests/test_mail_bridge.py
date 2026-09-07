from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.mail_bridge import (
    MailBridgeState,
    mail_event_dedupe_id,
    send_mail_from_account,
    unresolved_mail_aliases,
)


def _test_state_path(tmp_path: Path, name: str) -> Path:
    # 状态文件留在 pytest 临时目录，不写入源码树工作目录。
    return tmp_path / f".mail-bridge-{name}.json"


def test_mail_notification_claim_is_persistent_and_account_scoped(tmp_path: Path) -> None:
    path = _test_state_path(tmp_path, "notification")
    try:
        state = MailBridgeState(path)

        assert state.claim_notification("<message-1>", "shorekeeper@foxmail.com") is True
        assert state.claim_notification("<message-1>", "shorekeeper@foxmail.com") is False
        assert state.claim_notification("<message-1>", "other@example.com") is True

        reloaded = MailBridgeState(path)
        assert reloaded.claim_notification("<message-1>", "shorekeeper@foxmail.com") is False

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["notified_mail_ids"]
    finally:
        path.unlink(missing_ok=True)


def test_mail_reply_claim_can_be_released_and_marked_sent(tmp_path: Path) -> None:
    path = _test_state_path(tmp_path, "reply")
    try:
        state = MailBridgeState(path)

        assert state.claim_reply("<message-2>", "shorekeeper@foxmail.com") is True
        assert state.claim_reply("<message-2>", "shorekeeper@foxmail.com") is False

        state.release_reply("<message-2>", "shorekeeper@foxmail.com")
        assert state.claim_reply("<message-2>", "shorekeeper@foxmail.com") is True

        state.mark_reply_sent("<message-2>", "shorekeeper@foxmail.com")
        assert state.claim_reply("<message-2>", "shorekeeper@foxmail.com") is False
        assert MailBridgeState(path).claim_reply(
            "<message-2>", "shorekeeper@foxmail.com"
        ) is False
    finally:
        path.unlink(missing_ok=True)


class MailEvent:
    id = "<message-3>"


def test_mail_event_id_uses_message_id_stable_identifier() -> None:
    from plugins.bot_unified_runtime.mail_bridge import mail_event_id

    assert mail_event_id(MailEvent()) == "<message-3>"


def test_mail_event_dedupe_id_prefers_adapter_id_over_alternate_message_id() -> None:
    event = SimpleNamespace(
        id="<stable@example.com>",
        message_id="uid-17",
    )

    assert mail_event_dedupe_id(event) == ("<stable@example.com>", False)


def test_mail_event_dedupe_id_uses_same_fingerprint_without_message_id() -> None:
    def make_event():
        return SimpleNamespace(
            id="",
            message_id="",
            sender=SimpleNamespace(id="3865067623@qq.com"),
            subject="回复：【守岸人测试】邮箱发送链路测试",
            date="2026-08-28T10:00:00+08:00",
            in_reply_to="",
            get_plaintext=lambda: "你好",
        )

    first = mail_event_dedupe_id(make_event())
    second = mail_event_dedupe_id(make_event())
    assert first == second
    assert first[0].startswith("fingerprint:")
    assert first[1] is True


class _MailAdapter:
    def get_name(self) -> str:
        return "Mail"


class _MailBot:
    adapter = _MailAdapter()
    self_id = "3958874605@qq.com"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def send_to(self, recipient: str, body: str, **kwargs: object) -> None:
        self.calls.append((recipient, body, str(kwargs.get("subject", ""))))

    async def send_mail(self, message: object) -> None:
        self.calls.append(
            (
                str(message["To"]),
                str(message.get_content()).strip(),
                str(message["Subject"]),
            )
        )


@pytest.mark.asyncio
async def test_mail_alias_routes_send_to_authentication_bot() -> None:
    bot = _MailBot()

    await send_mail_from_account(
        {"mail": bot},
        account="shorekeeper@foxmail.com",
        recipient="3865067623@qq.com",
        subject="测试主题",
        body="你好",
        aliases={"shorekeeper@foxmail.com": "3958874605@qq.com"},
    )

    assert bot.calls == [("3865067623@qq.com", "你好", "测试主题")]


def test_unresolved_mail_aliases_reports_only_missing_auth_targets() -> None:
    bot = _MailBot()

    assert unresolved_mail_aliases(
        {"mail": bot},
        {
            "shorekeeper@foxmail.com": "3958874605@qq.com",
            "missing@example.com": "other@example.com",
        },
    ) == ["missing@example.com->other@example.com"]
