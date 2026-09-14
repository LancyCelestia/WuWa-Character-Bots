"""审查 A-22 回归：内联首投与 worker 认领的竞态收口（单发保证）。

离线运行（SQLite 用 tmp_path，无网络、无 NapCat）：

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_a22_inline_claim_race.py -q

背景（A 方审计 A-22，锚点 sender/queue.py 内联宽限期）：内联首投与 worker
投递原先只靠 next_retry_at=now+宽限期做时间错开——内联耗时超过宽限期
（多分片×传输超时、事件循环停顿等）worker 即认领同一行 → 同一条消息双发。
时间错开不可论证正确，本批改为进程内「内联认领台账」硬互斥：

- submit（事件循环内、无 deliver_after）登记 request_id → 提交任务；
- claim_due 对「提交任务仍存活且认领者非提交任务本人」的行否决认领——
  与宽限期长短无关，内联在途期间 worker 永不重复投递；
- mark_sent / mark_retryable_failure / mark_final_failure / mark_partial
  释放台账（内联已终结，无论成败）；
- 提交任务已终结仍未 mark_*（取消/异常路径）→ 死认领清簿放行，保住
  「内联丢失后 worker 接管」的既有恢复语义（不丢消息）；
- 进程重启台账自然清空 → 磁盘 next_retry_at 宽限兜底，跨重启语义不变。

覆盖项：
- ①慢内联（提交任务挂起远超宽限期，行已到期）+ worker 认领竞态：
  worker 不得认领、不得投递，终局单发（修前该场景双发，RED 钉死）。
- ②正常快内联路径零变化：submit→mark_sent 后 worker 无行可认领。
- ③提交任务死亡（取消，未及 mark_*）：死认领清簿放行，worker 接管补投
  （防「互斥把恢复语义也堵死」的反向回归——不丢消息优先级不变）。
- ④mark_retryable_failure 释放台账：内联明确可重试失败（零送达）后，
  即便提交任务仍存活，退避到期行也可被 worker 接管重投。
- ⑤deliver_after 入队（声明无内联首投，如错误卡补发）永不登记台账：
  提交任务存活也不阻塞 worker 到点认领。
"""

from __future__ import annotations

import asyncio
import contextlib
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
from plugins.bot_unified_runtime.sender.queue import SQLiteSendRequestQueue
from plugins.bot_unified_runtime.sender.worker import drain_send_queue_once


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _send_request(request_id: str) -> SendRequest:
    rendered = RenderedOutput(
        request_id=request_id,
        content_type="text",
        content_ref={"text": "A-22 内联认领竞态回归正文"},
        text_fallback="A-22 内联认领竞态回归正文",
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
        max_messages=1,
        dedupe_key=f"dedupe-{request_id}",
        cooldown_key="bot.chat:private:user-1",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="default",
    )


def _sent_receipt(request: SendRequest) -> DeliveryReceipt:
    return DeliveryReceipt(
        request_id=request.request_id,
        state=ReceiptState.SENT,
        transport="fake",
        public_message="sent",
    )


@pytest.mark.asyncio
async def test_a22_slow_inline_delivery_not_duplicated_by_worker_claim(
    tmp_path: Path,
) -> None:
    """①慢内联 + worker 认领竞态：内联在途（提交任务存活）期间 worker
    不得认领已到期行——单发保证不依赖宽限期长短。修前（纯时间错开）
    本场景 worker 在宽限期外认领同一行 → 双发。"""
    queue = SQLiteSendRequestQueue(tmp_path / "q.sqlite3", InMemoryAuditLogger())
    # 回拨 1 小时入队：行对 worker 立即到期——证明保护与时间窗无关。
    base = _utc_now() - timedelta(hours=1)
    request = _send_request("req-a22-slow")
    submitted = asyncio.Event()
    inline_release = asyncio.Event()
    sends: list[str] = []  # 每次真实投递（内联/worker）记一条，终局核对总数

    async def worker_transport(request: SendRequest) -> DeliveryReceipt:
        sends.append(f"worker:{request.request_id}")
        return _sent_receipt(request)

    async def handler() -> None:
        # 生产形态复刻：同一协程内 submit → 慢内联 transport → mark_sent。
        queue.submit(request, now=base)
        submitted.set()
        await inline_release.wait()  # 慢内联：挂起远超 60s 宽限期
        sends.append(f"inline:{request.request_id}")
        queue.mark_sent(request.request_id, now=base + timedelta(hours=2))

    task = asyncio.create_task(handler())
    await submitted.wait()

    # worker pass（另一任务认领）：内联在途 → 必须拿不到该行。
    result = await drain_send_queue_once(
        queue, worker_transport, now=base + timedelta(minutes=10)
    )
    assert result.checked == 0  # A-22：内联在途，worker 不得认领

    inline_release.set()
    await task

    # 终局单发：只有内联那一次，worker 从未投递。
    assert sends == ["inline:req-a22-slow"]
    assert queue.safe_summary().get("sent", 0) == 1


@pytest.mark.asyncio
async def test_a22_fast_inline_path_unchanged(tmp_path: Path) -> None:
    """②正常快内联路径零变化：submit → 立即 mark_sent → worker 无行可认领。"""
    queue = SQLiteSendRequestQueue(tmp_path / "q.sqlite3", InMemoryAuditLogger())
    base = _utc_now()
    request = _send_request("req-a22-fast")

    async def worker_transport(request: SendRequest) -> DeliveryReceipt:
        raise AssertionError("worker must not deliver inline-completed rows")

    queue.submit(request, now=base)
    queue.mark_sent(request.request_id, now=base)
    result = await drain_send_queue_once(
        queue, worker_transport, now=base + timedelta(hours=1)
    )
    assert result.checked == 0
    assert queue.safe_summary().get("sent", 0) == 1


@pytest.mark.asyncio
async def test_a22_dead_submitter_releases_claim_for_recovery(tmp_path: Path) -> None:
    """③提交任务取消且未及 mark_*：死认领清簿放行，worker 接管补投。
    互斥不得把「内联丢失后 worker 接管」的恢复语义一起堵死（不丢消息）。"""
    queue = SQLiteSendRequestQueue(tmp_path / "q.sqlite3", InMemoryAuditLogger())
    base = _utc_now() - timedelta(hours=1)
    request = _send_request("req-a22-dead")
    submitted = asyncio.Event()
    hang = asyncio.Event()

    async def worker_transport(request: SendRequest) -> DeliveryReceipt:
        return _sent_receipt(request)

    async def handler() -> None:
        queue.submit(request, now=base)
        submitted.set()
        await hang.wait()  # 永不被置位：模拟内联任务中途死亡

    task = asyncio.create_task(handler())
    await submitted.wait()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    # 提交任务已终结：台账放行，宽限期外 worker 正常接管（既有恢复语义）。
    result = await drain_send_queue_once(
        queue, worker_transport, now=base + timedelta(minutes=10)
    )
    assert result.delivered == 1
    assert queue.safe_summary().get("sent", 0) == 1


@pytest.mark.asyncio
async def test_a22_retryable_failure_releases_claim_while_submitter_alive(
    tmp_path: Path,
) -> None:
    """④mark_retryable_failure 释放台账：内联明确可重试失败（零送达）后，
    提交任务仍存活，退避到期行也可被 worker 接管——放行来自 mark_* 清簿，
    不依赖提交任务终结。"""
    queue = SQLiteSendRequestQueue(
        tmp_path / "q.sqlite3",
        InMemoryAuditLogger(),
        retry_base_seconds=1,
        retry_max_seconds=2,
    )
    base = _utc_now() - timedelta(hours=1)
    request = _send_request("req-a22-retry")
    submitted = asyncio.Event()
    release_handler = asyncio.Event()

    async def worker_transport(request: SendRequest) -> DeliveryReceipt:
        return _sent_receipt(request)

    async def handler() -> None:
        queue.submit(request, now=base)
        submitted.set()
        # A-03 语义：超时零送达 → FAILED_RETRYABLE（无副作用，重投安全）。
        queue.mark_retryable_failure(
            request.request_id, "inline failed", now=base + timedelta(seconds=1)
        )
        await release_handler.wait()  # 任务保持存活：证明放行不靠任务终结

    task = asyncio.create_task(handler())
    await submitted.wait()

    # 退避到期（base+1s 入队 + 2s 上限退避 ≪ base+120s）→ worker 接管重投。
    result = await drain_send_queue_once(
        queue, worker_transport, now=base + timedelta(minutes=2)
    )
    release_handler.set()
    await task
    assert result.delivered == 1
    assert queue.safe_summary().get("sent", 0) == 1


@pytest.mark.asyncio
async def test_a22_deliver_after_submit_never_registers_inline_claim(
    tmp_path: Path,
) -> None:
    """⑤deliver_after 入队声明无内联首投（如错误卡补发线程）：永不登记
    台账——提交任务存活也不阻塞 worker 到点认领。"""
    queue = SQLiteSendRequestQueue(tmp_path / "q.sqlite3", InMemoryAuditLogger())
    base = _utc_now()
    request = _send_request("req-a22-defer")
    submitted = asyncio.Event()
    release_handler = asyncio.Event()

    async def worker_transport(request: SendRequest) -> DeliveryReceipt:
        return _sent_receipt(request)

    async def handler() -> None:
        queue.submit(
            request,
            now=base,
            deliver_after=base + timedelta(seconds=3),
        )
        submitted.set()
        await release_handler.wait()  # 提交任务保持存活

    task = asyncio.create_task(handler())
    await submitted.wait()

    result = await drain_send_queue_once(
        queue, worker_transport, now=base + timedelta(seconds=10)
    )
    release_handler.set()
    await task
    assert result.delivered == 1
    assert queue.safe_summary().get("sent", 0) == 1
