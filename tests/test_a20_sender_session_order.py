"""审查 A-20（worker 侧）回归：发送 worker 会话内有序 + busy 饱和可见。

离线运行（SQLite 用 tmp_path，无网络、无 SnowLuma）：

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_a20_sender_session_order.py -q

覆盖项：
- ①同会话 A/B 两条：A 在途（事件屏障挂起）时，并发认领不得拿到 B；
  A 终态后 B 才被认领投递——投递顺序 A→B（跨请求会话内严格按序）。
- ②不同会话仍可并行：S1 的在途行不阻塞 S2 的认领与投递。
- ③在途上限（认领批量）满且仍有到期余量：审计 WARN +
  operational 告警各一次（300s 抑制窗口内重复饱和不再发），
  且绝不向原会话构造任何补发提示（群聊刷屏红线）。
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.contracts import (
    DeliveryReceipt,
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    RiskLevel,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.domains.ops.monitor.alerts import AdminAlertSuppression
from plugins.bot_unified_runtime.domains.transport.sender import worker as worker_module
from plugins.bot_unified_runtime.domains.transport.sender.queue import (
    SQLiteSendRequestQueue,
)
from plugins.bot_unified_runtime.domains.transport.sender.worker import (
    drain_send_queue_once,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _send_request(request_id: str, *, session_id: str) -> SendRequest:
    rendered = RenderedOutput(
        request_id=request_id,
        content_type="text",
        content_ref={"text": "A-20 会话有序回归正文"},
        text_fallback="A-20 会话有序回归正文",
        privacy_level=PrivacyLevel.PERSONAL,
    )
    return SendRequest(
        request_id=request_id,
        session_id=session_id,
        target_scope=SessionType.PRIVATE,
        target_id=session_id.partition(":")[-1],
        capability_id="bot.chat",
        content=rendered,
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key=f"dedupe-{request_id}",
        cooldown_key=f"bot.chat:{session_id}",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="default",
    )


def _build_queue(tmp_path: Path) -> SQLiteSendRequestQueue:
    return SQLiteSendRequestQueue(
        tmp_path / "send_queue.sqlite3",
        InMemoryAuditLogger(),
    )


def _sent_receipt(request: SendRequest) -> DeliveryReceipt:
    return DeliveryReceipt(
        request_id=request.request_id,
        state=ReceiptState.SENT,
        transport="fake",
        public_message="sent",
    )


async def _wait_for_processing(
    queue: SQLiteSendRequestQueue, expected: int = 1
) -> None:
    """事件屏障：轮询直到目标会话行进入 processing（在途）状态。"""
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if queue.safe_summary().get("processing", 0) >= expected:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("queue never reached expected processing state")


@pytest.mark.asyncio
async def test_a20_same_session_delivery_order_under_concurrent_claim(
    tmp_path: Path,
) -> None:
    """①同会话 A/B 并发认领：A 在途时 B 不可认领，投递顺序 A→B。"""
    queue = _build_queue(tmp_path)
    base = _utc_now() - timedelta(hours=1)  # 宽限期外，立即可认领
    # 审查 A-22 契约：本用例模拟纯 worker 行（无内联首投），以 deliver_after
    # 显式声明——否则测试任务 submit 会登记内联认领，跨任务 drain（子任务）
    # 被 A-22 台账否决（生产里这正是「handler 内联在途」的正确保护形态）。
    queue.submit(
        _send_request("req-a", session_id="private:user-1"),
        now=base,
        deliver_after=base,
    )
    queue.submit(
        _send_request("req-b", session_id="private:user-1"),
        now=base + timedelta(seconds=1),
        deliver_after=base + timedelta(seconds=1),
    )

    release_a = asyncio.Event()
    delivery_order: list[str] = []

    async def transport(request: SendRequest) -> DeliveryReceipt:
        delivery_order.append(request.request_id)
        if request.request_id == "req-a":
            # 事件屏障：A 挂起在途，制造并发认领窗口。
            await release_a.wait()
        return _sent_receipt(request)

    # limit=1：第一轮只认领 A（最旧），B 留队——并发认领窗口里 B 仍是候选，
    # 才能真实验证「同会话在途互斥」的认领口排除。
    drain_first = asyncio.create_task(
        drain_send_queue_once(
            queue, transport, now=base + timedelta(minutes=10), limit=1
        )
    )
    await _wait_for_processing(queue)

    # A 在途窗口内的并发认领：同会话 B 必须拿不到（会话互斥）。
    drain_second = await drain_send_queue_once(
        queue, transport, now=base + timedelta(minutes=10, seconds=30)
    )
    assert drain_second.checked == 0
    assert delivery_order == ["req-a"]  # B 尚未投递

    release_a.set()
    first_result = await drain_first
    assert first_result.delivered == 1

    # A 终态（SENT）后，B 才被认领并投递——会话内跨请求严格按序。
    third_result = await drain_send_queue_once(
        queue, transport, now=base + timedelta(minutes=20)
    )
    assert third_result.delivered == 1
    assert delivery_order == ["req-a", "req-b"]


@pytest.mark.asyncio
async def test_a20_same_session_batch_delivers_in_submit_order(tmp_path: Path) -> None:
    """④同会话多行同批认领（如错误报告 ack+卡片共享 request_id）：单 pass
    内按入队序逐条投递，不拆批、不乱序——在途互斥只约束跨认领者。"""
    queue = _build_queue(tmp_path)
    base = _utc_now() - timedelta(hours=1)
    for index in range(3):
        queue.submit(
            _send_request(f"req-seq-{index}", session_id="private:user-1"),
            now=base + timedelta(seconds=index),
        )

    delivery_order: list[str] = []

    async def transport(request: SendRequest) -> DeliveryReceipt:
        # 主动让出事件循环，证明顺序不是靠时序巧合维持的。
        await asyncio.sleep(0)
        delivery_order.append(request.request_id)
        return _sent_receipt(request)

    result = await drain_send_queue_once(
        queue, transport, now=base + timedelta(minutes=10)
    )
    assert result.delivered == 3
    assert delivery_order == ["req-seq-0", "req-seq-1", "req-seq-2"]


@pytest.mark.asyncio
async def test_a20_different_sessions_stay_parallel(tmp_path: Path) -> None:
    """②不同会话仍可并行：S1 在途不阻塞 S2 的认领与投递。"""
    queue = _build_queue(tmp_path)
    base = _utc_now() - timedelta(hours=1)
    # 审查 A-22 契约：跨会话并行用例同为纯 worker 行，deliver_after 声明
    # 无内联首投（原因同 test_a20_same_session_delivery_order 下注释）。
    queue.submit(
        _send_request("req-s1", session_id="private:user-1"),
        now=base,
        deliver_after=base,
    )
    queue.submit(
        _send_request("req-s2", session_id="private:user-2"),
        now=base + timedelta(seconds=1),
        deliver_after=base + timedelta(seconds=1),
    )

    release_s1 = asyncio.Event()
    delivery_order: list[str] = []

    async def transport(request: SendRequest) -> DeliveryReceipt:
        delivery_order.append(request.request_id)
        if request.request_id == "req-s1":
            await release_s1.wait()  # S1 挂起在途
        return _sent_receipt(request)

    # limit=1：第一轮认领只取 S1，制造「S1 在途、S2 待认领」的并发窗口。
    drain_first = asyncio.create_task(
        drain_send_queue_once(
            queue, transport, now=base + timedelta(minutes=10), limit=1
        )
    )
    await _wait_for_processing(queue)

    # S2 的认领与投递不被 S1 阻塞——异会话并行性保持。
    # （S1 仍挂在 release 等待上未完成，S2 却已完整走完认领→投递。）
    second_result = await drain_send_queue_once(
        queue, transport, now=base + timedelta(minutes=10, seconds=30), limit=1
    )
    assert second_result.checked == 1
    assert second_result.delivered == 1
    assert delivery_order == ["req-s1", "req-s2"]

    release_s1.set()
    first_result = await drain_first
    assert first_result.delivered == 1
    assert queue.safe_summary().get("processing", 0) == 0


@pytest.mark.asyncio
async def test_a20_inflight_cap_full_emits_alert_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """③在途上限满且仍有到期余量：审计 WARN + operational 告警（抑制一次）。"""
    # 独立抑制门：隔离其他用例在本窗口内的饱和告警状态。
    monkeypatch.setattr(
        worker_module,
        "_BUSY_ALERT_SUPPRESSION",
        AdminAlertSuppression(window_seconds=300.0),
    )
    audit_logger = InMemoryAuditLogger()
    queue = SQLiteSendRequestQueue(
        tmp_path / "send_queue.sqlite3", audit_logger
    )
    base = _utc_now() - timedelta(hours=1)
    for index in range(3):  # 3 个不同会话：认领上限=2 ⇒ 必有 1 条滞留
        queue.submit(
            _send_request(f"req-cap-{index}", session_id=f"private:user-{index}"),
            now=base + timedelta(seconds=index),
        )

    delivered: list[str] = []

    async def transport(request: SendRequest) -> DeliveryReceipt:
        delivered.append(request.request_id)
        return _sent_receipt(request)

    captured: list[tuple[SendRequest, DeliveryReceipt]] = []

    def fake_alerts_sink(send_request: SendRequest, receipt: DeliveryReceipt) -> None:
        # 生产里这里是 __init__ 注入的 operational_notifier → 管理员告警链。
        captured.append((send_request, receipt))

    result = await drain_send_queue_once(
        queue,
        transport,
        now=base + timedelta(minutes=10),
        limit=2,
        audit_logger=audit_logger,
        operational_notifier=fake_alerts_sink,
    )

    # 在途上限（=2）打满且仍有到期余量 ⇒ 告警恰一次。
    assert result.checked == 2
    assert result.inflight_saturated_alerts == 1
    assert len(captured) == 1
    carrier_request, receipt = captured[0]
    # 审计/告警载体 = 本批最新认领条目（饱和边界行 req-cap-1）。
    assert carrier_request.request_id == "req-cap-1"
    assert receipt.operational_issue is not None
    assert receipt.operational_issue.stage == "queue"
    assert receipt.operational_issue.kind == "send_queue_inflight_saturated"
    assert receipt.operational_issue.retryable is True
    assert receipt.state is ReceiptState.QUEUED  # 滞留行仍在队列，如实表达

    # 审计 WARN 落笔：MEDIUM 级 + 专用事件名。
    warn_records = [
        record
        for record in audit_logger.list_records()
        if record.event == "queue_worker_inflight_saturated"
    ]
    assert len(warn_records) == 1
    assert warn_records[0].severity is RiskLevel.MEDIUM

    # 群聊刷屏红线：告警绝不走投递通道——transport 只被真实投递调用，
    # 队列里也绝不新增告警行（除本批认领/滞留外零写入）。
    assert len(delivered) == 2
    summary = queue.safe_summary()
    assert (
        summary.get("sent", 0)
        + summary.get("queued", 0)
        + summary.get("processing", 0)
        == 3
    )

    # 300s 抑制窗口内的第二次饱和：审计与告警都不再发。
    queue.submit(
        _send_request("req-cap-extra", session_id="private:user-extra"),
        now=base,
    )
    second_result = await drain_send_queue_once(
        queue,
        transport,
        now=base + timedelta(minutes=11),
        limit=1,
        audit_logger=audit_logger,
        operational_notifier=fake_alerts_sink,
    )
    assert second_result.checked == 1
    assert second_result.inflight_saturated_alerts == 0
    assert len(captured) == 1
    assert len(delivered) == 3
