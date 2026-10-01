"""atkfix 复查波（2026-09-27）：TG/Mail 出站失败原因元信息两缺口（M-1/M-2）。

- M-1：``sender/nonebot.py`` _FinalSendError 分支旧写法
  ``redact_local_secrets(str(exc)[:48])`` 是**先截后洗**：截断窗口若恰好切开
  密钥形态（如 ``sk-`` 连段被截成 ``sk-Q``），打码腿因残缺而整腿不命中，
  残段原样进 kind/safe_summary，再随 alerts/诊断卡出站。修法与
  S-ATKFIX-OUTB 波已裁定的口径一致：先整串打码、后截断。
- M-2：通用 except 两条分支把 kind 与 safe_summary 同写成一枚字面量
  （"result_unknown"/"send_exception"），异常**类型**在持久化回执元数据里
  当场蒸发（诊断卡/告警只剩一个分类词）。kind 是 worker 判据的承重串
  （``worker.py`` 按 kind 逐字比对决定确认/拒绝），一个字节都不能动；且
  既有裁决锁（tests/test_operational_failures.py:368-373）钉死**异常消息
  原文**绝不进回执 JSON（回执落库）——故本席收窄口径：safe_summary 只补
  非敏感的异常类型词，消息原文改落本地 warning 日志（detail=%s，与
  _FinalSendError 分支「本地日志保留原文」同口径先例）。

本文件只做两件事：钉住「残段不泄漏」「原因不蒸发」「public_message 不变」。
"""
from __future__ import annotations

import re

import pytest

from plugins.bot_unified_runtime.contracts import (
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.domains.transport.sender import (
    file_gateway as file_gateway_module,
)
from plugins.bot_unified_runtime.domains.transport.sender.file_gateway import (
    FinalTransferError,
)
from plugins.bot_unified_runtime.domains.transport.sender.nonebot import (
    send_nonebot_message,
)

# 边界骑跨串：``sk-`` 词根落在第 44-47 字符，先截 48 会把密钥连段切成
# ``sk-Q``——残缺形态躲过 _API_KEY_RE（{4,} 不满足），残段原样存活。
_STRADDLE = "x" * 44 + "sk-QQWELLKEYMATERIAL9"
_STRADDLE_RESIDUE = "sk-Q"
_STRADDLE_SECRET = "QQWELLKEYMATERIAL9"


class _FakeAdapter:
    def __init__(self, name: str) -> None:
        self._name = name

    def get_name(self) -> str:
        return self._name


class _StubBot:
    """files 分支在 gateway.stage 就抛终态异常，bot API 不会被触达。"""

    def __init__(self, name: str = "telegram") -> None:
        self.adapter = _FakeAdapter(name)
        self.self_id = f"{name}-bot"


class _RaisingGateway:
    def __init__(self, message: str) -> None:
        self._message = message

    def stage(self, src: object, *, request_id: str = "") -> object:
        raise FinalTransferError(self._message)

    def deliver(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("deliver must not be reached when stage fails")


def _file_request(request_id: str = "req-m1") -> SendRequest:
    return SendRequest(
        request_id=request_id,
        session_id="private:user-1",
        target_scope=SessionType.PRIVATE,
        target_id="user-1",
        origin_message_id="message-1",
        capability_id="bot.admin_alert",
        content=RenderedOutput(
            request_id=request_id,
            content_type="text",
            content_ref={
                "parts": [
                    {"type": "file", "file": "Z:/missing/video.mp4", "name": "video.mp4"}
                ]
            },
            text_fallback="",
            privacy_level=PrivacyLevel.PERSONAL,
        ),
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key=f"bot.admin_alert:private:user-1:{request_id}",
        cooldown_key="admin_alert:private:user-1",
        privacy_level=PrivacyLevel.PERSONAL,
        allow_split=False,
        allow_forward=False,
        persona_profile_id="default",
        adapter="telegram",
        bot_id="telegram-bot",
    )


def _text_request(request_id: str = "req-m2", *, text: str = "你好") -> SendRequest:
    return SendRequest(
        request_id=request_id,
        session_id="private:user-1",
        target_scope=SessionType.PRIVATE,
        target_id="user-1",
        origin_message_id="message-1",
        capability_id="bot.chat",
        content=RenderedOutput(
            request_id=request_id,
            content_type="text",
            content_ref={},
            text_fallback=text,
            privacy_level=PrivacyLevel.PERSONAL,
        ),
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key=f"bot.chat:private:user-1:{request_id}",
        cooldown_key="private:user-1",
        privacy_level=PrivacyLevel.PERSONAL,
        allow_split=False,
        allow_forward=False,
        persona_profile_id="default",
        adapter="telegram",
        bot_id="telegram-bot",
    )


class _MediaRequestBuilder:
    """把正文/部件塞进 SendRequest（与 tests/test_nonebot_sender.py 同法）。"""

    @staticmethod
    def build(parts: list[dict[str, object]], text: str) -> SendRequest:
        base = _text_request("req-m2p")
        return base.model_copy(
            update={
                "content": RenderedOutput(
                    request_id="req-m2p",
                    content_type="mixed",
                    content_ref={"parts": parts},
                    text_fallback=text,
                    privacy_level=PrivacyLevel.PERSONAL,
                )
            }
        )


class _PhotoThenRaisingTextBot:
    """send_photo 成功、send_to 抛错：模拟「部分部件已送达」的整体失败。"""

    def __init__(self, message: str) -> None:
        self.adapter = _FakeAdapter("Telegram")
        self.self_id = "telegram-bot"
        self._message = message
        self.media_calls: list[tuple[str, dict[str, object]]] = []

    async def send_photo(self, chat_id=None, photo=None, caption=None, **kwargs: object):
        self.media_calls.append(("send_photo", {"photo": photo, "caption": caption}))
        return {"message_id": "photo-1"}

    async def send_to(self, target_id: str, message: str):
        raise RuntimeError(self._message)


# ---------------------------------------------------------------------------
# M-1：_FinalSendError 分支先洗后截
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_final_error_truncated_secret_fragment_never_reaches_issue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """骑跨截断窗口的 sk- 密钥形态不得以残段进 kind/safe_summary。"""
    monkeypatch.setattr(
        file_gateway_module, "_default_gateway", _RaisingGateway(_STRADDLE)
    )
    receipt = await send_nonebot_message(_StubBot(), object(), _file_request())
    assert receipt.state is ReceiptState.FAILED_FINAL
    issue = receipt.operational_issue
    assert issue is not None
    # 先截后洗的旧写法在这里会留下 "sk-Q"（连段被切残、打码腿不命中）。
    assert _STRADDLE_RESIDUE not in issue.kind
    assert _STRADDLE_SECRET not in issue.kind
    assert _STRADDLE_RESIDUE not in issue.safe_summary
    assert _STRADDLE_SECRET not in issue.safe_summary
    # 修好后：整串先打码再截断——截断窗口内不得残留任何「sk-+密钥字符」形态
    # （占位符以 "<" 开头，合法产物只有 "sk-<"；旧写法的产物是 "sk-Q"）。
    assert re.search(r"sk-[A-Za-z0-9_]", issue.kind) is None
    assert re.search(r"sk-[A-Za-z0-9_]", issue.safe_summary) is None
    assert len(issue.kind) <= 48
    assert issue.kind == issue.safe_summary


# ---------------------------------------------------------------------------
# M-2：通用 except 分支 safe_summary 携带异常类型（kind 逐字不动，消息原文不进回执）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_exception_summary_carries_type_without_message() -> None:
    """safe_summary 补异常类型词；消息原文不进回执（裁决锁 :368-373 同域）；kind 不动。"""

    class _SendRaises:
        adapter = _FakeAdapter("Telegram")
        self_id = "telegram-bot"

        async def send(self, event: object, message: str, **kwargs: object):
            raise RuntimeError("text leg blew up")

    receipt = await send_nonebot_message(_SendRaises(), object(), _text_request())
    assert receipt.state is ReceiptState.FAILED_RETRYABLE
    assert receipt.public_message == ""
    issue = receipt.operational_issue
    assert issue is not None
    # kind 是 worker 判据的承重串：逐字不变。
    assert issue.kind == "send_exception"
    # 类型词在场（旧写法塌成裸分类词 ⇒ 本断言先红）。
    assert issue.safe_summary == "send_exception RuntimeError"
    # 消息原文一个字符都不进回执 JSON（落库面，既有裁决锁口径）。
    assert "text leg blew up" not in receipt.model_dump_json()
    assert "text leg blew up" not in issue.safe_summary


@pytest.mark.asyncio
async def test_partial_delivered_unknown_summary_carries_type(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """部件已送达的 result_unknown 分支：kind 逐字不变，safe_summary 带类型词。"""
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.domains.transport.sender.nonebot._TG_VOICE_CACHE_DIR",
        tmp_path / "vcache",
    )
    card = tmp_path / "help.png"
    card.write_bytes(b"png-bytes")
    # 超长正文强制走「图先单独发」腿；随后文本腿抛错 ⇒ 已送达部件的整体失败。
    long_text = "x" * 1200
    bot = _PhotoThenRaisingTextBot("text leg blew up")

    receipt = await send_nonebot_message(
        bot, None, _MediaRequestBuilder.build([{"type": "image", "file": str(card)}], long_text)
    )
    assert receipt.state is ReceiptState.FAILED_FINAL
    issue = receipt.operational_issue
    assert issue is not None
    assert issue.kind == "result_unknown"
    assert issue.safe_summary == "result_unknown RuntimeError"
    assert "text leg blew up" not in receipt.model_dump_json()
    assert receipt.public_message == ""


@pytest.mark.asyncio
async def test_failure_summary_never_carries_exception_message_text() -> None:
    """密钥形态的异常消息同样不得随回执落库：safe_summary 只有类型词。"""

    class _LeakySendBot:
        adapter = _FakeAdapter("Telegram")
        self_id = "telegram-bot"

        async def send(self, event: object, message: str, **kwargs: object):
            raise RuntimeError(_STRADDLE)

    receipt = await send_nonebot_message(_LeakySendBot(), object(), _text_request())
    issue = receipt.operational_issue
    assert issue is not None
    assert issue.kind == "send_exception"
    assert issue.safe_summary == "send_exception RuntimeError"
    assert _STRADDLE_RESIDUE not in receipt.model_dump_json()
    assert _STRADDLE_SECRET not in receipt.model_dump_json()
    assert len(issue.safe_summary) <= 96
