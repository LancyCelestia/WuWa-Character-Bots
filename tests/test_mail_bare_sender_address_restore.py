"""Mail 裸名族地址侧恢复（席35，2026-10-03 用户授权）的判据锁。

病根（``parse_byte_mail`` 实测）：``From: 阿澜 <lan@example.com>``（显示名未按
RFC2047 编码，国内客户端常见）⇒ ``sender.name=''``、``sender.id``＝**整条 From
值重打的 base64 编码字垃圾**。会话身份/防冒名面（roles/affinity/memory 裸键）
吃的就是这段垃圾。修复真身＝``mail_adapter.restore_mail_sender_address``（摄取
咽喉 ``fetch_mail_by_uid`` 接线），本锁五件事：

① 拆回腿：裸名族垃圾 id 解出「名+址」⇒ id 恢复真实地址、名回填；多址取首个
   带 @ 的作者（RFC 5322 首作者；mailparser 截断型编码字一并吃到）。
② 现行为腿：纯名无址／裸 token 无 @／畸形编码字／解码失败 ⇒ 原值原样回，
   绝不炸摄取链（裸 token 的隔离腿在根摄取，Mail-1 配对档＝M ``__init__.py``）。
③ 不误伤腿：正常 ``name <addr>``／裸地址（name 空但带 @）一字不动。
④ collision 语义腿（全链离线）：裸名邮件经真实摄取链（``fetch_mail_by_uid`` →
   ``_fetch_new_mail`` → ``_incoming_from_nonebot_event``）后 ``sender_id``＝
   真实地址而非垃圾串——trusted 名单按地址命中/不命中双向成立。
⑤ 信头块腿：拆回的显示名随 ``build_mail_header_block`` 进会话。

全部离线：假 IMAP/事件记录器，零网络、零真实凭据、零 Runtime 写。
"""

from __future__ import annotations

import asyncio
import base64
from email.mime.text import MIMEText
from email.utils import formatdate
from types import SimpleNamespace
from typing import Any

import pytest
from nonebot.adapters.mail.bot import Bot as MailBot
from nonebot.adapters.mail.config import BotInfo

from plugins.bot_unified_runtime import _incoming_from_nonebot_event
from plugins.bot_unified_runtime.domains.chat_reply.policy.roles import (
    build_role_settings,
)
from plugins.bot_unified_runtime.domains.transport.mail.mail_adapter import (
    ResilientMailAdapter,
    build_mail_header_block,
    fetch_mail_by_uid,
    restore_mail_sender_address,
)

# 攻击者在裸名显示名里逐字写的"受害者"QQ 号形态（与 atk 锁同号，语义对齐）。
VICTIM_QQ = "123456789"
ATTACKER_ADDR = "attacker@evil.com"


def _stuffed(from_value: str, charset: str = "utf-8") -> str:
    """复刻 mailparser 实测行为：整条 From 值重打成单枚 base64 编码字。"""
    payload = base64.b64encode(from_value.encode(charset)).decode("ascii")
    return f"=?{charset}?b?{payload}?="


# ---------------------------------------------------------------------------
# ①②③ 纯单元：restore_mail_sender_address
# ---------------------------------------------------------------------------


def test_stuffed_id_splits_back_to_name_and_address() -> None:
    assert restore_mail_sender_address("", _stuffed("阿澜 <lan@example.com>")) == (
        "阿澜",
        "lan@example.com",
    )


def test_multi_author_stuffed_id_takes_first_author() -> None:
    stuffed = _stuffed("阿澜 <lan@example.com>, 守岸人 <sk@example.com>")
    assert restore_mail_sender_address("", stuffed) == ("阿澜", "lan@example.com")


def test_mailparser_truncated_stuffed_id_takes_first_complete_author() -> None:
    # mailparser 实产会把超长 From 截断（第二址残缺）：首个完整地址仍须拆回。
    truncated = "=?utf-8?b?6Zi/5r6cIDxsYW5AZXhhbXBsZS5jb20+LCDlrojlsrjkurogPHNrQGV4YW1w?="
    assert restore_mail_sender_address("", truncated) == ("阿澜", "lan@example.com")


def test_pure_name_without_address_stays_untouched() -> None:
    # 纯名无址：无地址可恢复，保持现行为（显示名侧不在本席授权面）。
    stuffed = _stuffed("阿澜")
    assert restore_mail_sender_address("", stuffed) == ("", stuffed)


def test_bare_numeric_token_stays_untouched() -> None:
    # 无 @ 裸 token（atk 攻击形）：本腿只拆「名+址」，不产地址即不动；
    # 逐字穿透的隔离腿在根摄取（Mail-1 配对档＝M __init__.py），另行登记。
    assert restore_mail_sender_address("", VICTIM_QQ) == ("", VICTIM_QQ)


def test_malformed_encoded_word_stays_untouched() -> None:
    raw = "=?utf-8?B?6Zi/5r6c"  # 缺 ?= 收尾
    assert restore_mail_sender_address("", raw) == ("", raw)


def test_nonempty_name_never_enters_the_leg() -> None:
    # 介入签名＝name 为空：正常解析（无论 id 什么形）一律不进本腿。
    assert restore_mail_sender_address("Alan", "whatever<garbage") == (
        "Alan",
        "whatever<garbage",
    )


def test_bare_address_stays_untouched() -> None:
    assert restore_mail_sender_address("", "lan@example.com") == (
        "",
        "lan@example.com",
    )


# ---------------------------------------------------------------------------
# ④⑤ 摄取链接线：fetch_mail_by_uid → sender.name/id → 信头块
# ---------------------------------------------------------------------------


class _Response:
    def __init__(self, result: str = "OK", lines: list[bytes] | None = None) -> None:
        self.result = result
        self.lines = lines if lines is not None else []


def _raw_mail(from_header: str) -> bytes:
    mail = MIMEText("正文占位", "plain", "utf-8")
    mail["Subject"] = "季度报告"
    mail["From"] = from_header
    mail["To"] = "Shorekeeper <bot@example.com>"
    mail["Message-ID"] = "<bare-restore-seat35@example.com>"
    mail["Date"] = formatdate(localtime=False)
    return mail.as_bytes()


class _ScriptedIMAP:
    def __init__(self, raw: bytes) -> None:
        self.raw = raw

    async def store(self, *criteria: str) -> _Response:
        return _Response()

    async def uid(self, command: str, *criteria: str) -> Any:
        if command == "FETCH":
            return _Response(lines=[bytearray(b"* 1 FETCH (RFC822 {n}"), self.raw])
        return _Response()


@pytest.mark.asyncio
async def test_fetch_restores_attacker_display_name_with_victim_number() -> None:
    """拆回腿（摄取点）：裸名里带受害者号——id 必须恢复攻击者真实地址，
    显示名解出进信头块；垃圾编码字不得再当身份键。"""
    mail = await fetch_mail_by_uid(
        _ScriptedIMAP(_raw_mail(f"群友{VICTIM_QQ} <{ATTACKER_ADDR}>")),
        "1",
    )
    assert mail is not None
    assert mail.sender.id == ATTACKER_ADDR
    assert mail.sender.name == f"群友{VICTIM_QQ}"
    block = build_mail_header_block(mail)
    assert f"发件人显示名：群友{VICTIM_QQ}" in block


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


async def _capture_event(from_header: str) -> Any:
    """裸名邮件走真实咽喉（_fetch_new_mail）→ 记录派发事件（全离线）。"""
    imap = _ScriptedIMAP(_raw_mail(from_header))
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
    assert len(handled) == 1, "裸名邮件必须照常派发一封事件"
    return handled[0]


def _role_settings(*trusted: str) -> Any:
    config = SimpleNamespace(
        bot_admin_user_ids=[],
        bot_telegram_admin_user_ids=[],
        bot_super_admin_user_ids=[],
        bot_enterprise_user_ids=[],
        bot_trusted_user_ids=list(trusted),
        bot_blocked_user_ids=[],
    )
    return build_role_settings(config)


@pytest.mark.asyncio
async def test_forged_bare_name_collision_judgment_uses_real_address() -> None:
    """collision 语义腿（防冒名）：攻击者裸名里写受害者号 ⇒ 全链 sender_id 是
    攻击者**真实地址**（非垃圾编码字、非受害者号），trusted 名单吃不到。"""
    event = await _capture_event(f"群友{VICTIM_QQ} <{ATTACKER_ADDR}>")
    assert event.get_user_id() == ATTACKER_ADDR
    message = _incoming_from_nonebot_event(
        event,
        bot_id="shorekeeper@example.com",
        adapter_name="mail",
    )
    assert message.sender_id == ATTACKER_ADDR
    assert "=?utf-8" not in message.sender_id, "垃圾编码字不得再当身份键"
    assert message.sender_id != VICTIM_QQ, "受害者号不得被冒名键碰撞"
    assert message.session_id == f"email:{ATTACKER_ADDR}"
    roles = _role_settings(VICTIM_QQ).resolve_roles(message)
    assert "trusted" not in roles, "冒名者不得经裸名垃圾键领到受害者 trusted"


@pytest.mark.asyncio
async def test_legit_bare_name_sender_regains_role_by_real_address() -> None:
    """collision 语义腿（防误伤正向）：真用户裸名寄件 ⇒ 按真实地址命中 trusted
    ——修复前垃圾编码字键领不到角色，本枚钉住「判定吃真实地址」的收益面。"""
    event = await _capture_event("阿澜 <lan@example.com>")
    message = _incoming_from_nonebot_event(
        event,
        bot_id="shorekeeper@example.com",
        adapter_name="mail",
    )
    assert message.sender_id == "lan@example.com"
    roles = _role_settings("lan@example.com").resolve_roles(message)
    assert "trusted" in roles


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
