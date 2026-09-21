"""v21r2 R5 热区回归：安静时间拦截=非交互来源完全静默（问题 B 根因锁死）。

生产实锤（凌晨实弹）：bot 在无任何 @ 的情况下主动发「当前处于安静时间，已
暂停非必要回复。」。根因=旧版 pipeline 安静时间拦截回执携带非空
public_message 并被投递；修复=拦截回执 public_message 置空（与限流拦截同款
裁定，BLOCKED 回执在 handle/handle_async 即返回，不进能力、不进发送队列）。

本文件把该语义钉死为回归门（全离线、注入时钟）：
- 安静窗口内、无人 @ 的 bot.chat：BLOCKED + public_message=="" + 发送队列
  零入队（handle 与 handle_async 双路）；
- 显式交互既有门语义不变：mentions_bot 直通（direct_request_bypass）、
  非 chat/bot.content 能力（指令族）直通——能力照常执行、回复照常入队。

复跑：
  PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_v21r2_hotzone_quiet_silence.py -q \
      --basetemp=$TEMP/v21r2-r5c -p no:cacheprovider
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    ReceiptState,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.policy.quiet_hours import (
    QuietHoursChecker,
    QuietHoursSettings,
)
from plugins.bot_unified_runtime.runtime.pipeline import RuntimePipeline
from plugins.bot_unified_runtime.sender.queue import InMemorySendQueue

_QUIET_NOW = datetime(2026, 9, 17, 23, 30, tzinfo=timezone.utc)


def _settings() -> QuietHoursSettings:
    # session_types 显式含 private：把私聊也纳入安静门，测试才不被
    # 「session 排除」旁路，真正压在 quiet_hours 判定本身上。
    return QuietHoursSettings(
        enabled=True,
        start_time="23:00",
        end_time="07:00",
        timezone_name="UTC",
        session_types=["group", "private"],
    )


def _message(*, mentions: bool) -> IncomingMessage:
    # 私聊形态：默认门禁对私聊全放行，测试焦点落在安静时间门本身。
    return IncomingMessage(
        platform="qq",
        adapter="nonebot",
        bot_id="bot-1",
        session_id="p1",
        session_type=SessionType.PRIVATE,
        sender_id="u1",
        sender_roles=["user"],
        mentions_bot=mentions,
    )


def _pipeline() -> tuple[RuntimePipeline, InMemorySendQueue]:
    queue = InMemorySendQueue(InMemoryAuditLogger())
    pipeline = RuntimePipeline(
        queue,
        InMemoryAuditLogger(),
        quiet_hours_checker=QuietHoursChecker(_settings(), clock=lambda: _QUIET_NOW),
    )
    return pipeline, queue


def _capability(message: IncomingMessage, decision: Any) -> CapabilityResult:
    return CapabilityResult(
        request_id=message.request_id,
        capability_id=decision.capability_id,
        kind="text",
        body="好的，我在。",
        audit_tags=["t"],
    )


async def _async_capability(
    message: IncomingMessage, decision: Any
) -> CapabilityResult:
    return _capability(message, decision)


# ------------------------------------------------------------- 非交互=完全静默


def test_quiet_hours_blocks_noninteractive_without_any_message_in_handle() -> None:
    pipeline, queue = _pipeline()
    message = _message(mentions=False)
    receipt = pipeline.handle(message, _capability, capability_id="bot.chat")
    assert receipt.state is ReceiptState.BLOCKED
    assert receipt.public_message == ""
    assert queue.sent_requests == []
    assert queue.find_request(message.request_id) is None


@pytest.mark.asyncio
async def test_quiet_hours_blocks_noninteractive_without_any_message_in_handle_async() -> None:
    pipeline, queue = _pipeline()
    message = _message(mentions=False)
    receipt = await pipeline.handle_async(
        message, _async_capability, capability_id="bot.chat"
    )
    assert receipt.state is ReceiptState.BLOCKED
    assert receipt.public_message == ""
    assert queue.sent_requests == []
    assert queue.find_request(message.request_id) is None


# ------------------------------------------------- 显式交互=既有门语义不变


def test_quiet_hours_direct_mention_bypass_preserved() -> None:
    pipeline, queue = _pipeline()
    message = _message(mentions=True)
    receipt = pipeline.handle(message, _capability, capability_id="bot.chat")
    assert receipt.state is ReceiptState.SENT
    assert len(queue.sent_requests) == 1
    assert queue.sent_requests[0].content.text_fallback == "好的，我在。"


def test_quiet_hours_command_capability_bypass_preserved() -> None:
    pipeline, queue = _pipeline()
    message = _message(mentions=False)
    receipt = pipeline.handle(message, _capability, capability_id="bot.status")
    assert receipt.state is ReceiptState.SENT
    assert len(queue.sent_requests) == 1
    assert queue.sent_requests[0].content.text_fallback == "好的，我在。"
