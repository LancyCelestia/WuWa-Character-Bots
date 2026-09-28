"""atkfix 复查波（2026-09-27）：TG/Mail 出站消息号元信息两缺口（M-3/M-4）。

- M-3（已发部件的消息号蒸发）：``sender/nonebot.py`` 的「图先单独发」腿丢弃
  send_photo 返回的 Message；且两条 result_unknown 回执（超时、已送达部件后
  异常）一律不带 provider_message_id——明明有**已被出口确认**的部件号可指认，
  管理员与队列却拿到「结果未知」且零把手。修法：成功返回的腿逐条记录消息号，
  只在结果未知/SENT 回执携带**已证明送达**的号；失败腿一个号都不带。
- M-4（邮件出站根本没有消息号）：nonebot-adapter-mail 的 ``send_mail`` 走
  stdlib ``smtplib.send_message``，**不自动盖 Message-ID**；装配层
  ``_build_mail_reply_message`` 也没盖 ⇒ 出站邮件无 Message-ID、回执
  provider_message_id 永远 None、对方回复时无任何头部可引用（In-Reply-To
  链路自源头断裂）。修法：装配回复报文时用 ``email.utils.make_msgid`` 幂等
  自盖（域取发件地址域），SENT 回执以「出口回号 > 已证明部件号 > 本腿自盖号」
  兜底；任何失败/结果未知回执**不得**携带未经出口证明的自盖号。

边界（既有锁不可违）：邮件**附件**腿的 FileTransferReceipt.provider_file_id
保持 None（tests/test_file_outbound_channels.py:301「SMTP 出口不回消息号 ⇒
诚实 None」）——本文件的自盖号只进文本回复腿的 DeliveryReceipt，不碰附件腿。
"""
from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.contracts import (
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.domains.transport.sender.nonebot import (
    send_nonebot_message,
)

_MSGID_RE = re.compile(r"^<[^@<>]+@[^<>]+>$")


class _FakeAdapter:
    def __init__(self, name: str) -> None:
        self._name = name

    def get_name(self) -> str:
        return self._name


def _mail_request() -> SendRequest:
    return SendRequest(
        request_id="req-m4",
        session_id="email:sender@example.com",
        target_scope=SessionType.EMAIL,
        target_id="sender@example.com",
        origin_message_id="message-1",
        capability_id="bot.chat",
        content=RenderedOutput(
            request_id="req-m4",
            content_type="text",
            content_ref={},
            text_fallback="你好",
            privacy_level=PrivacyLevel.PERSONAL,
        ),
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key="bot.chat:email:sender-1",
        cooldown_key="email:sender",
        privacy_level=PrivacyLevel.PERSONAL,
        allow_split=False,
        allow_forward=False,
        persona_profile_id="default",
        adapter="mail",
        bot_id="qq@example.com",
    )


def _mail_event() -> SimpleNamespace:
    return SimpleNamespace(
        id="<incoming@example.com>",
        subject="测试主题",
        sender=SimpleNamespace(id="sender@example.com"),
    )


class _MailBot:
    """记录 send_mail 收到的报文；返回值可配置（None=真适配器形，dict=出口回号）。"""

    def __init__(self, *, result: object) -> None:
        self.adapter = _FakeAdapter("Mail")
        self.self_id = "qq@example.com"
        self.bot_info = SimpleNamespace(id="qq@example.com", name="守岸人")
        self.sent: list[object] = []
        self._result = result

    async def send_mail(self, message: object) -> object:
        self.sent.append(message)
        return self._result


# ---------------------------------------------------------------------------
# M-4：邮件文本腿自盖 Message-ID
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mail_reply_is_stamped_with_own_message_id() -> None:
    """真适配器 send_mail 返回 None：出站报文仍必须带 RFC 合法的 Message-ID，
    且 SENT 回执以该自盖号为兜底把手（回复方从此有头部可引用）。"""
    bot = _MailBot(result=None)

    receipt = await send_nonebot_message(bot, _mail_event(), _mail_request())

    assert receipt.state is ReceiptState.SENT
    message = bot.sent[0]
    stamp = str(message["Message-ID"])
    assert _MSGID_RE.match(stamp), stamp
    # 域取发件地址域：可指向真投递源，不做无域裸号。
    assert stamp.endswith("@example.com>")
    assert receipt.provider_message_id == stamp
    # In-Reply-To 引用链头部零回归。
    assert message["In-Reply-To"] == "<incoming@example.com>"


@pytest.mark.asyncio
async def test_mail_provider_echo_wins_over_own_stamp() -> None:
    """出口若回号（替身 dict 形），回执优先用出口号——自盖号只是兜底。"""
    bot = _MailBot(result={"message_id": "mail-message-1"})

    receipt = await send_nonebot_message(bot, _mail_event(), _mail_request())

    assert receipt.state is ReceiptState.SENT
    assert receipt.provider_message_id == "mail-message-1"
    stamp = str(bot.sent[0]["Message-ID"])
    assert _MSGID_RE.match(stamp)
    assert stamp != "mail-message-1"


@pytest.mark.asyncio
async def test_mail_send_failure_never_carries_unproven_stamp() -> None:
    """send_mail 抛错：自盖号未经出口证明，失败回执一个号都不带。"""

    class _RaisingMailBot(_MailBot):
        async def send_mail(self, message: object) -> object:
            self.sent.append(message)
            raise RuntimeError("smtp handshake exploded")

    bot = _RaisingMailBot(result=None)
    receipt = await send_nonebot_message(bot, _mail_event(), _mail_request())

    assert receipt.state is ReceiptState.FAILED_RETRYABLE
    assert receipt.provider_message_id is None
    issue = receipt.operational_issue
    assert issue is not None
    assert issue.kind == "send_exception"


# ---------------------------------------------------------------------------
# S-FIX-ATK-MAIL R3：Message-ID 必须由邮件身份确定性派生（重投同号 → 去重）
# 旧写法每装配一次盖一个随机新号：DATA 后 SMTP 断连 ⇒ FAILED_RETRYABLE ⇒ 队列
# 重投 ⇒ 每重投换号 ⇒ 收件人收到多封「同文不同号」重复邮件。修法＝同 request_id
# + 同正文/收件/主题 ⇒ 同一个号；不同 request_id ⇒ 不同号（不破部件级幂等）。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_request_retried_reuses_identical_message_id() -> None:
    """同一条重投两次 ⇒ 同一个 Message-ID，收件端可据 RFC 5322 去重。"""
    bot = _MailBot(result=None)
    request = _mail_request()

    await send_nonebot_message(bot, _mail_event(), request)
    await send_nonebot_message(bot, _mail_event(), request)

    assert len(bot.sent) == 2
    first = str(bot.sent[0]["Message-ID"])
    second = str(bot.sent[1]["Message-ID"])
    assert _MSGID_RE.match(first)
    assert first == second


@pytest.mark.asyncio
async def test_different_request_or_content_gets_different_message_id() -> None:
    """不同 request_id、或不同正文 ⇒ 不同号：确定但不碰撞，部件级幂等不受损。"""
    bot = _MailBot(result=None)
    base = _mail_request()
    other_id = base.model_copy(update={"request_id": "req-m4-b"})

    await send_nonebot_message(bot, _mail_event(), base)
    await send_nonebot_message(bot, _mail_event(), other_id)

    assert len(bot.sent) == 2
    assert str(bot.sent[0]["Message-ID"]) != str(bot.sent[1]["Message-ID"])

    bot2 = _MailBot(result=None)
    changed_body = base.model_copy(
        update={
            "content": base.content.model_copy(update={"text_fallback": "完全不同的正文"})
        }
    )
    await send_nonebot_message(bot2, _mail_event(), base)
    await send_nonebot_message(bot2, _mail_event(), changed_body)
    assert str(bot2.sent[0]["Message-ID"]) != str(bot2.sent[1]["Message-ID"])


# ---------------------------------------------------------------------------
# M-3：已证明送达部件的消息号随结果未知回执出站
# ---------------------------------------------------------------------------


def _tg_media_request(text: str) -> SendRequest:
    base = _mail_request()
    return base.model_copy(
        update={
            "request_id": "req-m3",
            "session_id": "private:user-1",
            "target_scope": SessionType.PRIVATE,
            "target_id": "user-1",
            "dedupe_key": "bot.chat:private:user-1:m3",
            "cooldown_key": "private:user-1",
            "adapter": "telegram",
            "bot_id": "telegram-bot",
            "content": RenderedOutput(
                request_id="req-m3",
                content_type="mixed",
                content_ref={"parts": [{"type": "image", "url": "https://example.com/c.jpg"}]},
                text_fallback=text,
                privacy_level=PrivacyLevel.PERSONAL,
            ),
        }
    )


class _PhotoThenHangingTextBot:
    """send_photo 成功拿到 message_id，随后文本腿挂死到超时。"""

    def __init__(self) -> None:
        self.adapter = _FakeAdapter("Telegram")
        self.self_id = "telegram-bot"

    async def send_photo(self, chat_id=None, photo=None, **kwargs: object):
        return {"message_id": "photo-9"}

    async def send_to(self, target_id: str, message: str):
        await asyncio.sleep(10)
        return {"id": "late"}


@pytest.mark.asyncio
async def test_timeout_after_delivered_photo_receipt_carries_proven_id() -> None:
    """超时腿此前把已确认送达的 photo-9 一起蒸发：结果未知回执必须带已证明号。"""
    receipt = await send_nonebot_message(
        _PhotoThenHangingTextBot(),
        None,
        _tg_media_request("x" * 1200),  # 超长正文 ⇒ 图先单独发、文本另起一条
        timeout_seconds=0.01,
    )
    assert receipt.state is ReceiptState.FAILED_FINAL
    issue = receipt.operational_issue
    assert issue is not None
    assert issue.kind == "result_unknown"
    assert receipt.provider_message_id == "photo-9"


class _PhotoThenRaisingTextBot:
    def __init__(self) -> None:
        self.adapter = _FakeAdapter("Telegram")
        self.self_id = "telegram-bot"

    async def send_photo(self, chat_id=None, photo=None, **kwargs: object):
        return {"message_id": "photo-9"}

    async def send_to(self, target_id: str, message: str):
        raise RuntimeError("text leg blew up")


@pytest.mark.asyncio
async def test_partial_delivery_unknown_receipt_carries_proven_id() -> None:
    """部件已送达后异常：result_unknown 回执携带已证明部件号（此前恒 None）。"""
    receipt = await send_nonebot_message(
        _PhotoThenRaisingTextBot(), None, _tg_media_request("x" * 1200)
    )
    assert receipt.state is ReceiptState.FAILED_FINAL
    issue = receipt.operational_issue
    assert issue is not None
    assert issue.kind == "result_unknown"
    assert receipt.provider_message_id == "photo-9"


@pytest.mark.asyncio
async def test_sent_receipt_prefers_final_leg_result_id() -> None:
    """成功链不变：SENT 回执优先用最终 result 的出口号（黄金值零漂移）。"""

    class _PhotoThenOkTextBot(_PhotoThenHangingTextBot):
        async def send_to(self, target_id: str, message: str):
            return {"id": "direct-message-1"}

    receipt = await send_nonebot_message(
        _PhotoThenOkTextBot(), None, _tg_media_request("x" * 1200)
    )
    assert receipt.state is ReceiptState.SENT
    assert receipt.provider_message_id == "direct-message-1"
