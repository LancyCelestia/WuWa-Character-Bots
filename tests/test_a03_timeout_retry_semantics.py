"""审查 A-03 回归：OneBot 发送超时的失败语义分级 + 告警可见性。

离线运行（无网络、无 SnowLuma、队列用 tmp_path）：

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_a03_timeout_retry_semantics.py -q

覆盖项：
- ①超时且零内容送达（progress.count==0）→ FAILED_RETRYABLE + issue.retryable=True，
  交回队列按既有重试/断点续发机制走；public_message 仍为空（群聊失败静默是
  产品裁定，不随重试语义改变）。
- ②超时但已有部分内容送达（progress.count>0）→ 维持 FAILED_FINAL +
  result_unknown 终态不变（从头重发会重复投递）。
- ③失败回执必须经 worker 的 operational_notifier 到达告警链，且
  runtime/alerts.notify_operational_issue 能把该 issue 派发到管理员目标
  （fake alerts sink；300s 抑制键含 stage/kind，见 test_operational_failures）。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.contracts import (
    DeliveryReceipt,
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.domains.ops.monitor.alerts import (
    AdminTarget,
    notify_operational_issue,
)
from plugins.bot_unified_runtime.sender.onebot import send_onebot_v11
from plugins.bot_unified_runtime.sender.queue import SQLiteSendRequestQueue
from plugins.bot_unified_runtime.sender.worker import drain_send_queue_once


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _text_request(request_id: str) -> SendRequest:
    rendered = RenderedOutput(
        request_id=request_id,
        content_type="text",
        content_ref={"text": "A-03 超时语义回归"},
        text_fallback="A-03 超时语义回归",
        privacy_level=PrivacyLevel.PERSONAL,
    )
    return SendRequest(
        request_id=request_id,
        session_id="group:g-1",
        target_scope=SessionType.GROUP,
        target_id="g-1",
        capability_id="bot.chat",
        content=rendered,
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key=f"dedupe-{request_id}",
        cooldown_key="bot.chat:group:g-1",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="default",
        allow_forward=False,
        adapter="onebot",
        bot_id="qq-bot",
    )


def _chunk_request(request_id: str, chunks: list[str]) -> SendRequest:
    rendered = RenderedOutput(
        request_id=request_id,
        content_type="chunks",
        content_ref={"chunks": list(chunks)},
        text_fallback="".join(chunks),
        privacy_level=PrivacyLevel.PERSONAL,
    )
    return SendRequest(
        request_id=request_id,
        session_id="private:user-1",
        target_scope=SessionType.PRIVATE,
        target_id="user-1",
        capability_id="bot.chat",
        content=rendered,
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=len(chunks),
        dedupe_key=f"dedupe-{request_id}",
        cooldown_key="bot.chat:private:user-1",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="default",
        adapter="onebot",
        bot_id="qq-bot",
    )


class _SlowAllBot:
    """任何发送都慢于超时预算：整发超时且零副作用。"""

    async def send_group_msg(self, **kwargs: object) -> dict:
        await asyncio.sleep(1.0)
        return {"status": "ok", "retcode": 0}

    async def send_private_msg(self, **kwargs: object) -> dict:
        await asyncio.sleep(1.0)
        return {"status": "ok", "retcode": 0}


class _FirstOkThenSlowBot:
    """首次发送立即成功（记副作用），之后的发送慢于剩余预算。"""

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_private_msg(self, *, user_id: object, message: list[dict]) -> dict:
        if self.sent:
            await asyncio.sleep(1.0)
            return {"status": "ok", "retcode": 0}
        text = str(message[0]["data"]["text"])
        self.sent.append(text)
        return {"status": "ok", "retcode": 0, "message_id": f"mid-{len(self.sent)}"}

    async def send_group_msg(self, *, group_id: object, message: list[dict]) -> dict:
        return await self.send_private_msg(user_id=group_id, message=message)


@pytest.mark.asyncio
async def test_a03_timeout_zero_delivered_is_retryable() -> None:
    """①超时+零内容送达 → FAILED_RETRYABLE，issue.retryable=True。"""
    request = _text_request("req-a03-zero")
    receipt = await send_onebot_v11(
        _SlowAllBot(), request, timeout_seconds=0.2
    )  # type: ignore[arg-type]
    assert receipt.state is ReceiptState.FAILED_RETRYABLE
    assert receipt.public_message == ""  # 群聊失败静默：产品裁定，不因重试语义改变
    assert receipt.operational_issue is not None
    assert receipt.operational_issue.stage == "onebot"
    assert receipt.operational_issue.kind == "timeout_zero_part_delivered"
    assert receipt.operational_issue.retryable is True


@pytest.mark.asyncio
async def test_a03_timeout_partial_delivery_stays_result_unknown() -> None:
    """②超时+部分送达 → 维持 FAILED_FINAL + result_unknown 终态不变。"""
    bot = _FirstOkThenSlowBot()
    receipt = await send_onebot_v11(
        bot,
        _chunk_request("req-a03-partial", ["分片一", "分片二"]),
        timeout_seconds=0.3,
    )
    assert bot.sent == ["分片一"]  # 第一段已确认送达
    assert receipt.state is ReceiptState.FAILED_FINAL
    assert receipt.public_message == ""
    assert receipt.operational_issue is not None
    assert receipt.operational_issue.kind == "result_unknown"
    assert receipt.operational_issue.retryable is False


@pytest.mark.asyncio
async def test_a03_timed_out_part_resumes_only_failed_part(tmp_path: Path) -> None:
    """part 级零送达超时 → 该 part 回 PENDING，后续 part 照常推进，
    下一轮只补发该 part（§9.3 验收场景 2 的超时版）。"""
    queue = SQLiteSendRequestQueue(
        tmp_path / "part-timeout.sqlite3",
        InMemoryAuditLogger(),
        retry_base_seconds=1,
        retry_max_seconds=2,
    )
    base = _utc_now()
    chunks = ["分片一", "分片二", "分片三"]
    queue.submit(_chunk_request("req-a03-part", chunks), now=base)

    class _ScriptedBot:
        """可配置慢速文本：命中即拖过超时预算（零送达超时），其余立即成功。"""

        def __init__(self, slow_text: str = "") -> None:
            self.slow_text = slow_text
            self.sent: list[str] = []

        async def send_private_msg(self, *, user_id: object, message: list[dict]) -> dict:
            text = str(message[0]["data"]["text"])
            self.sent.append(text)
            if text == self.slow_text:
                await asyncio.sleep(1.0)
            return {"status": "ok", "retcode": 0, "message_id": f"mid-{len(self.sent)}"}

        async def send_group_msg(self, *, group_id: object, message: list[dict]) -> dict:
            return await self.send_private_msg(user_id=group_id, message=message)

    def _transport_with(bot: _ScriptedBot):
        async def transport(send_request: SendRequest) -> DeliveryReceipt:
            return await send_onebot_v11(bot, send_request, timeout_seconds=0.3)  # type: ignore[arg-type]

        return transport

    bot1 = _ScriptedBot(slow_text="分片二")
    first = await drain_send_queue_once(
        queue, _transport_with(bot1), now=base + timedelta(seconds=120)
    )
    # 分片二超时（零送达 → 可重试）：分片三同一轮照常推进，不整封终态。
    assert bot1.sent == ["分片一", "分片二", "分片三"]
    assert first.retryable_failed == 1

    # 退避后第二轮：只补发分片二，全部送达 → SENT。
    bot2 = _ScriptedBot()
    second = await drain_send_queue_once(
        queue, _transport_with(bot2), now=base + timedelta(seconds=240)
    )
    assert bot2.sent == ["分片二"]
    assert second.delivered == 1
    assert bot1.sent.count("分片一") == 1  # 已送达 part 全链路只发一次


@pytest.mark.asyncio
async def test_a03_failure_reaches_alerts_sink(tmp_path: Path) -> None:
    """③失败回执经 worker operational_notifier 到达告警链并可派发管理员。"""
    queue = SQLiteSendRequestQueue(
        tmp_path / "queue.sqlite3",
        InMemoryAuditLogger(),
        retry_base_seconds=1,
        retry_max_seconds=2,
    )
    base = _utc_now()
    request = _text_request("req-a03-alert")
    queue.submit(request, now=base)

    captured: list[tuple[SendRequest, DeliveryReceipt]] = []

    def fake_alerts_sink(send_request: SendRequest, receipt: DeliveryReceipt) -> None:
        # 生产里这里是 __init__._notify_queue_operational_receipt →
        # notify_operational_issue；测试用 fake sink 捕获事件本身。
        captured.append((send_request, receipt))

    async def transport(send_request: SendRequest) -> DeliveryReceipt:
        return await send_onebot_v11(
            _SlowAllBot(), send_request, timeout_seconds=0.2
        )  # type: ignore[arg-type]

    result = await drain_send_queue_once(
        queue,
        transport,
        now=base + timedelta(seconds=120),  # 跨过内联投递宽限期
        operational_notifier=fake_alerts_sink,
    )

    assert result.retryable_failed == 1
    assert len(captured) == 1
    send_request, receipt = captured[0]
    assert receipt.state is ReceiptState.FAILED_RETRYABLE
    assert receipt.operational_issue is not None
    assert receipt.operational_issue.kind == "timeout_zero_part_delivered"
    assert receipt.operational_issue.retryable is True

    # 捕获到的 issue 走真实 alerts API（fake 派发通道）：管理员侧可见。
    deliveries: list[tuple[AdminTarget, str]] = []

    async def fake_delivery(target: AdminTarget, bot: object, req: SendRequest) -> DeliveryReceipt:
        text = str(req.content.text_fallback)
        deliveries.append((target, text))
        return DeliveryReceipt(
            request_id=req.request_id,
            state=ReceiptState.SENT,
            transport="fake",
            public_message="sent",
        )

    dispatch = await notify_operational_issue(
        receipt.operational_issue,
        source_adapter=send_request.adapter,
        source_bot=send_request.bot_id,
        session_type=send_request.target_scope,
        targets=[
            AdminTarget(adapter="onebot", bot_id="qq-bot", target_id="10000")
        ],
        online_bots={"qq-bot": object()},
        delivery=fake_delivery,
    )
    assert len(dispatch) == 1 and dispatch[0].success is True
    assert len(deliveries) == 1
    # 告警文本自解释：kind 写明超时零送达，retryable 写明会重试。
    assert "kind=timeout_zero_part_delivered" in deliveries[0][1]
    assert "retryable=true" in deliveries[0][1]
