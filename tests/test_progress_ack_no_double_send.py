"""需求项 6 之 2（2026-09-29 用户裁定）：同一轮内 ack 与失败兜底不得连发两条。

现网形态：能力在阈值之后才失败 ⇒ 用户先收到一句「我在想」（回执已出口、QQ
收不回），随后又收到人格失败话术/群内降级文案——两气泡说同一件事，还都算数。
本族用例钉：

- 私聊：回执发出后失败 ⇒ 纯失败话术不再外送（一轮至多一句），审计留痕。
- 群聊：回执发出后失败 ⇒ 池内降级通知不再外送。
- 反例守恒：**带接地内容的兜底（kb_grounded_fallback）不压**——那是真资料，
  吞掉就是吞回复（红线）；没发过回执的失败轮照旧各发各的（A-19 现状不动）。
- 慢而成功的正常轮：回执 + 真回复照发（本治理只针对失败兜底，不碰成功回复）。
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    OperationalIssue,
    SendPolicy,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.pipeline import (
    RuntimePipeline,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.progress_ack import (
    ProgressAckSettings,
)
from plugins.bot_unified_runtime.domains.transport.sender.queue import (
    InMemorySendQueue,
)


def _incoming(*, group: bool = False, sender_id: str = "u-1") -> IncomingMessage:
    if group:
        return IncomingMessage(
            platform="qq", adapter="onebot", bot_id="10000",
            session_id="group_662948429_u1", session_type=SessionType.GROUP,
            sender_id=sender_id, group_id="662948429",
            plain_text="这条我要等很久", message_id="m-double",
            mentions_bot=True,
        )
    return IncomingMessage(
        platform="qq", adapter="onebot", bot_id="10000",
        session_id=f"private:{sender_id}", session_type=SessionType.PRIVATE,
        sender_id=sender_id, plain_text="这条我要等很久", message_id="m-double",
    )


def _failure_result(message: IncomingMessage, *, grounded: bool = False) -> CapabilityResult:
    return CapabilityResult(
        request_id=message.request_id,
        capability_id="bot.chat",
        kind="text",
        title="守岸人的回复",
        body="" if grounded else "回应生成到一半，链路断了……再发一次，这次我会把它写完。",
        send_policy=SendPolicy.IMMEDIATE,
        operational_issue=OperationalIssue(
            stage="llm", kind="provider_failed", retryable=True,
            safe_summary="provider_failed",
        ),
        audit_tags=(["llm_error", "kb_grounded_fallback"] if grounded else ["llm_error"]),
    )


def _ok_result(message: IncomingMessage) -> CapabilityResult:
    return CapabilityResult(
        request_id=message.request_id, capability_id="bot.chat", kind="text",
        title="守岸人的回复", body="潮水替我算完了这一条。",
        send_policy=SendPolicy.IMMEDIATE,
    )


def _pipeline(
    submits: list[Any],
    *,
    group: bool = False,
) -> RuntimePipeline:
    """自适应关、静态阈值亚秒：保证「先回执」必然发生，再演失败时序。

    floor 也压到亚秒——自适应开时地板会接管一切静态值（2026-09-28 口径），
    本族要的是「阈值到点、回执出口、随后才失败」这一条支路。
    """
    settings = ProgressAckSettings(
        enabled=True,
        delay_seconds=0.02,
        adaptive_enabled=False,
        group_whitelist=frozenset({"662948429"}) if group else frozenset(),
    )

    def _submit(request: Any) -> None:
        submits.append(request)

    audit = InMemoryAuditLogger()
    queue = InMemorySendQueue(audit)
    pipeline = RuntimePipeline(
        send_queue=queue,
        audit_logger=audit,
        progress_ack_settings=settings,
        progress_ack_submit=_submit,
    )
    pipeline._ack_test_queue = queue  # type: ignore[attr-defined]
    return pipeline


async def _run(pipeline: RuntimePipeline, message: IncomingMessage, result_factory) -> Any:
    async def capability(cap_msg, _decision):
        await asyncio.sleep(0.2)
        return result_factory(cap_msg)

    return await pipeline.handle_async(message, capability, "bot.chat")


@pytest.mark.asyncio
async def test_private_failure_after_ack_does_not_send_second_bubble() -> None:
    submits: list[Any] = []
    pipeline = _pipeline(submits)
    receipt = await _run(pipeline, _incoming(), _failure_result)
    assert len(submits) == 1, "回执一句该出口"
    assert not pipeline._ack_test_queue.sent_requests, (  # type: ignore[attr-defined]
        "同轮失败兜底不得再发第二条（私聊连发治理）"
    )
    from plugins.bot_unified_runtime.contracts import ReceiptState

    assert receipt.state is ReceiptState.SKIPPED


@pytest.mark.asyncio
async def test_group_failure_notice_suppressed_after_ack() -> None:
    submits: list[Any] = []
    pipeline = _pipeline(submits, group=True)
    await _run(pipeline, _incoming(group=True), _failure_result)
    assert len(submits) == 1, "群白名单回执一句该出口"
    notices = [
        request
        for request in pipeline._ack_test_queue.sent_requests  # type: ignore[attr-defined]
        if request.capability_id == "bot.group_failure_notice"
    ]
    assert not notices, "同轮已开口 ⇒ A-19 群内降级文案不得连发"


@pytest.mark.asyncio
async def test_grounding_fallback_is_never_suppressed() -> None:
    """带真资料的兜底（kb_grounded_fallback）照发——治理只压纯失败话术。"""
    submits: list[Any] = []
    pipeline = _pipeline(submits)
    await _run(pipeline, _incoming(), lambda msg: _failure_result(msg, grounded=True))
    assert len(submits) == 1
    assert pipeline._ack_test_queue.sent_requests, (  # type: ignore[attr-defined]
        "接地兜底被压＝吞回复，红线禁止"
    )


@pytest.mark.asyncio
async def test_failure_without_prior_ack_keeps_old_behaviour_byte_identical() -> None:
    """没发过回执的失败轮：群内降级文案照发（A-19 现状一字不动）。"""
    submits: list[Any] = []
    settings_on = _pipeline(submits, group=True)
    # 阈值放到很远 ⇒ 回执不发，只演「失败 → 群内通知」旧路径。
    settings_on.progress_ack_settings = ProgressAckSettings(
        enabled=True,
        delay_seconds=3600.0,
        adaptive_enabled=False,
        group_whitelist=frozenset({"662948429"}),
    )
    await _run(settings_on, _incoming(group=True), _failure_result)
    assert submits == [], "阈值内不该有回执"
    notices = [
        request
        for request in settings_on._ack_test_queue.sent_requests  # type: ignore[attr-defined]
        if request.capability_id == "bot.group_failure_notice"
    ]
    assert len(notices) == 1, "无回执的失败轮必须照发群内降级文案（旧行为回归锁）"


@pytest.mark.asyncio
async def test_slow_success_round_still_delivers_the_real_answer() -> None:
    """慢而成功：回执 + 真回复都发——本治理绝不碰成功回复（不撤回裁定保留）。"""
    submits: list[Any] = []
    pipeline = _pipeline(submits)
    await _run(pipeline, _incoming(), _ok_result)
    assert len(submits) == 1
    assert len(pipeline._ack_test_queue.sent_requests) == 1, (  # type: ignore[attr-defined]
        "真回复被误压＝吞回复"
    )
