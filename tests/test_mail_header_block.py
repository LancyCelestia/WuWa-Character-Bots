"""邮件信头元数据块（票 T-META-INGEST-1，2026-10-03 检索与知识波）的判据锁。

锁四件事：

① 块内容：From 显示名（消毒后）/ To / Cc 进块；To/Cc **只报地址不带名字**
   （第三方自填串是伪装面，暴露面收窄一格）。
② 消毒：From 显示名过 ``sanitize_display_name`` 唯一真身——零宽/RTL 伪装
   进不了会话；普通名字逐字节不变。
③ 有界：块长有帽，超长截断并留省略号。
④ 咽喉接线：``_fetch_new_mail`` 把块作为**首段** text 插进事件消息；任何
   失败只丢这一块、绝不打断收信（与附件腿同一口径）；无信头（无显示名且
   To/Cc 全空）时不产段。

全部离线：假 IMAP/事件记录器，零网络、零真实凭据、零 Runtime 写。
"""

from __future__ import annotations

import asyncio
from email.mime.text import MIMEText
from email.utils import formatdate
from types import SimpleNamespace
from typing import Any

import pytest
from nonebot.adapters.mail.bot import Bot as MailBot
from nonebot.adapters.mail.config import BotInfo

from plugins.bot_unified_runtime.domains.transport.mail import mail_adapter
from plugins.bot_unified_runtime.domains.transport.mail.mail_adapter import (
    ResilientMailAdapter,
    build_mail_header_block,
)

# ---------------------------------------------------------------------------
# ①②③ 纯单元：build_mail_header_block
# ---------------------------------------------------------------------------


class _User:
    def __init__(self, name: str = "", id: str = "") -> None:
        self.name = name
        self.id = id


def _fake_mail(**over: Any) -> SimpleNamespace:
    body: dict[str, Any] = {
        "sender": _User(name="阿澜", id="lan@example.com"),
        "recipients_to": [_User(name="守岸人", id="bot@example.com")],
        "recipients_cc": [_User(name="副本", id="cc@example.com")],
    }
    body.update(over)
    return SimpleNamespace(**body)


def test_header_block_carries_display_name_and_addresses() -> None:
    block = build_mail_header_block(_fake_mail())
    assert block.startswith("[邮件信头] ")
    assert "发件人显示名：阿澜" in block
    assert "收件人（To）：bot@example.com" in block
    assert "抄送（Cc）：cc@example.com" in block
    # To/Cc 的名字是第三方自填串：只报地址，不带名字。
    assert "守岸人" not in block.split("发件人显示名：", 1)[1].split("；", 1)[-1]


def test_header_block_sanitizes_display_name_but_keeps_plain_names_verbatim() -> None:
    assert "发件人显示名：阿澜" in build_mail_header_block(_fake_mail())
    poisoned = _fake_mail(sender=_User(name="岸\u200b宝", id="x@y.com"))
    clean = build_mail_header_block(poisoned)
    assert "\u200b" not in clean, "零宽伪装必须被消毒真身剥掉"


def test_header_block_omits_absent_parts_and_empty_block_yields_empty_string() -> None:
    minimal = build_mail_header_block(_fake_mail(recipients_to=[], recipients_cc=[]))
    assert "收件人" not in minimal and "抄送" not in minimal
    assert "发件人显示名：阿澜" in minimal
    # 无显示名 + 无 To/Cc ⇒ 空串（不产段，不写「无」谎报）。
    assert (
        build_mail_header_block(
            _fake_mail(
                sender=_User(name="", id="a@b.com"), recipients_to=[], recipients_cc=[]
            )
        )
        == ""
    )


def test_header_block_tolerates_dumped_dict_rows_and_none() -> None:
    block = build_mail_header_block(
        _fake_mail(
            recipients_to=[{"id": "d@e.com", "name": "名字"}],
            recipients_cc=None,
        )
    )
    assert "收件人（To）：d@e.com" in block
    assert "抄送" not in block


def test_header_block_is_bounded() -> None:
    long_rows = [{"id": f"u{i}@example.com"} for i in range(200)]
    block = build_mail_header_block(_fake_mail(recipients_to=long_rows))
    assert len(block) <= mail_adapter._MAIL_HEADER_BLOCK_CHARS + 1
    assert block.endswith("…")


# ---------------------------------------------------------------------------
# ④ 咽喉接线：_fetch_new_mail 首段插入 + 绝不打断收信
# ---------------------------------------------------------------------------


class _Response:
    def __init__(self, result: str = "OK", lines: list[bytes] | None = None) -> None:
        self.result = result
        self.lines = lines if lines is not None else []


def _raw_mail_with_headers() -> bytes:
    # ⚠ 显示名用 ASCII：在册适配器 parse_byte_mail 对规范 RFC2047 编码字本就能解，
    # 解不动的是**裸非 ASCII 显示名**（name 落空、整串被打成 base64 塞进 id）——
    # 原注「不解 RFC2047」系归因错位。该族已由摄取链兜底修复（席9R 显示名解码 +
    # 席35 地址侧拆回），本件仍用 ASCII 名锁定纯头块装配语义，不与解码腿耦合。
    mail = MIMEText("正文占位", "plain", "utf-8")
    mail["Subject"] = "季度报告"
    mail["From"] = "Alan <lan@example.com>"
    mail["To"] = "Shorekeeper <bot@example.com>"
    mail["Cc"] = "cc-one@example.com"
    mail["Message-ID"] = "<hdr@example.com>"
    mail["Date"] = formatdate(localtime=False)
    return mail.as_bytes()


class _ScriptedIMAP:
    def __init__(self, raw: bytes) -> None:
        self.raw = raw
        self.uid_calls: list[tuple[str, ...]] = []

    async def store(self, *criteria: str) -> _Response:
        return _Response()

    async def uid(self, command: str, *criteria: str) -> Any:
        self.uid_calls.append((command, *criteria))
        if command == "FETCH":
            return _Response(
                lines=[bytearray(b"* 1 FETCH (RFC822 {n}"), self.raw]
            )
        return _Response()


def _make_adapter() -> ResilientMailAdapter:
    adapter = ResilientMailAdapter.__new__(ResilientMailAdapter)
    adapter.driver = SimpleNamespace(
        _bot_connect=lambda bot: None, _bot_disconnect=lambda bot: None
    )
    adapter.bots = {}
    adapter.tasks = set()
    adapter._inflight_uids = set()
    return adapter


def _make_bot(adapter: Any, imap: Any) -> MailBot:
    bot = MailBot(
        adapter,
        "bot@example.com",
        BotInfo.model_validate(
            {
                "id": "bot@example.com",
                "name": "守岸人",
                "password": "secret",
                "subject": "守岸人测试",
                "imap": {"host": "imap.example.com", "port": 993, "tls": True},
                "smtp": {"host": "smtp.example.com", "port": 465, "tls": True},
            }
        ),
    )
    bot.imap_client = imap
    bot.mailbox = "INBOX"
    bot.readonly = False
    return bot


@pytest.mark.asyncio
async def test_fetch_new_mail_prepends_header_block_segment() -> None:
    imap = _ScriptedIMAP(_raw_mail_with_headers())
    adapter = _make_adapter()
    bot = _make_bot(adapter, imap)
    handled: list[Any] = []

    async def _record(event: Any) -> None:
        handled.append(event)

    bot.handle_event = _record  # type: ignore[assignment]
    search = _Response(lines=[bytearray(b"1")])

    async def _search(_criteria: str) -> _Response:
        return search

    imap.search = _search  # type: ignore[assignment]

    await adapter._fetch_new_mail(bot)
    pending = [task for task in list(adapter.tasks) if not task.done()]
    if pending:
        await asyncio.gather(*pending)

    assert len(handled) == 1
    segments = handled[0].message
    assert isinstance(segments, list) and segments

    def _seg_text(segment: Any) -> str:
        # 事件侧 pydantic 会把段 dict 回铸成 MessageSegment；两种形态都认。
        if isinstance(segment, dict):
            return str((segment.get("data") or {}).get("text") or "")
        return str(getattr(segment.data, "text", "") or (segment.data or {}).get("text", ""))

    def _seg_type(segment: Any) -> str:
        return str(segment.get("type") or "") if isinstance(segment, dict) else str(segment.type)

    head = segments[0]
    assert _seg_type(head) == "text"
    assert _seg_text(head).startswith("[邮件信头] ")
    assert "发件人显示名：Alan" in _seg_text(head)
    assert "bot@example.com" in _seg_text(head)
    # 头块是首段：正文段仍在其后（附件腿的 append 语义不变）。
    body_texts = [_seg_text(s) for s in segments[1:]]
    assert any("正文占位" in text for text in body_texts)


@pytest.mark.asyncio
async def test_fetch_new_mail_survives_a_poisoned_header_builder() -> None:
    """头块构造炸 ⇒ 只丢这一块（WARNING），邮件照常派发——绝不打断收信。"""
    imap = _ScriptedIMAP(_raw_mail_with_headers())
    adapter = _make_adapter()
    bot = _make_bot(adapter, imap)
    handled: list[Any] = []

    async def _record(event: Any) -> None:
        handled.append(event)

    bot.handle_event = _record  # type: ignore[assignment]
    search = _Response(lines=[bytearray(b"1")])

    async def _search(_criteria: str) -> _Response:
        return search

    imap.search = _search  # type: ignore[assignment]

    original = mail_adapter.build_mail_header_block

    def _boom(_mail: Any) -> str:
        raise RuntimeError("poisoned header leg")

    mail_adapter.build_mail_header_block = _boom  # type: ignore[assignment]
    try:
        await adapter._fetch_new_mail(bot)
    finally:
        mail_adapter.build_mail_header_block = original  # type: ignore[assignment]
    pending = [task for task in list(adapter.tasks) if not task.done()]
    if pending:
        await asyncio.gather(*pending)

    assert len(handled) == 1, "头块腿炸了，信也必须照常进来"
    segments = handled[0].message

    def _seg_text(segment: Any) -> str:
        if isinstance(segment, dict):
            return str((segment.get("data") or {}).get("text") or "")
        return str(getattr(segment.data, "text", "") or (segment.data or {}).get("text", ""))

    assert all(
        not _seg_text(s).startswith("[邮件信头]")
        for s in segments
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
