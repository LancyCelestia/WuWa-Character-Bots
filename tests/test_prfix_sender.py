"""管线检视修复回归（PR-fix #6/#10/#13）：断线挂起 / 分段超时下限 / 单连接事务。

离线运行（SQLite 用 tmp_path，无网络、无 NapCat）：

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_prfix_sender.py -q

覆盖项：
- #6 bot_unavailable 挂起不消耗重试预算：断线窗口内重排退避 90s、
  retry_count 不递增；入队年龄超过上限（默认 1800s，可配置覆盖）后
  置终态防死挂堆积；普通失败计次路径不受豁免影响。
- #13 mark_* 终态迁移在进程内共享长连接的单事务内完成且幂等：
  全流程连接数不随操作数增长（queue 与 receipts 两侧）。
- #10 分片超时均分带每段下限 10s：6 段 × 15s 预算下每段拿到 10s 而非
  2.5s；剩余预算不足时取剩余，耗尽抛 TimeoutError。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.contracts import (
    OperationalIssue,
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.sender import onebot as onebot_sender
from plugins.bot_unified_runtime.sender import queue as queue_module
from plugins.bot_unified_runtime.sender import receipts as receipts_module
from plugins.bot_unified_runtime.sender.queue import SQLiteSendRequestQueue
from plugins.bot_unified_runtime.sender.receipts import SQLiteReceiptRepository


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _send_request(
    request_id: str,
    dedupe_key: str,
    *,
    text: str = "PR-fix 回归正文",
) -> SendRequest:
    rendered = RenderedOutput(
        request_id=request_id,
        content_type="text",
        content_ref={"text": text},
        text_fallback=text,
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
        dedupe_key=dedupe_key,
        cooldown_key="bot.chat:private:user-1",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="default",
    )


def _build_queue(
    tmp_path: Path,
    *,
    bot_unavailable_max_age_seconds: float | None = None,
) -> SQLiteSendRequestQueue:
    kwargs: dict[str, float] = {}
    if bot_unavailable_max_age_seconds is not None:
        kwargs["bot_unavailable_max_age_seconds"] = bot_unavailable_max_age_seconds
    return SQLiteSendRequestQueue(
        tmp_path / "send_queue.sqlite3",
        InMemoryAuditLogger(),
        **kwargs,  # type: ignore[arg-type]
    )


def _bot_unavailable_issue() -> OperationalIssue:
    return OperationalIssue(
        stage="queue",
        kind="bot_unavailable",
        retryable=True,
        safe_summary="bot_unavailable",
    )


# ==================== #6：断线挂起不烧重试预算 ====================


def test_prfix6_bot_unavailable_defer_does_not_consume_attempts(tmp_path) -> None:
    """断线重排不递增 retry_count，退避固定 90s，恢复后照常送达。"""
    queue = _build_queue(tmp_path)
    base = _utc_now()
    queue.submit(_send_request("req-p6", "dedupe-p6"), now=base)
    issue = _bot_unavailable_issue()

    # 远超 max_attempts=3 轮断线失败：不消耗重试预算，退避恒为 90s。
    for round_index in range(6):
        mark_time = base + timedelta(seconds=round_index * 90)
        receipt = queue.mark_retryable_failure(
            "req-p6", "failed", now=mark_time, operational_issue=issue
        )
        assert receipt.state is ReceiptState.FAILED_RETRYABLE
        assert receipt.retry_count == 0
        assert receipt.next_retry_at == mark_time + timedelta(seconds=90.0)

    entry = queue._find_entry_by_request_id("req-p6")
    assert entry is not None
    assert entry.retry_count == 0
    assert entry.state is ReceiptState.FAILED_RETRYABLE

    # bot 恢复后照常标记送达，消息不被静默丢弃。
    sent = queue.mark_sent("req-p6", now=base + timedelta(seconds=600))
    assert sent.state is ReceiptState.SENT


def test_prfix6_age_guard_finalizes_after_max_age(tmp_path) -> None:
    """入队年龄超过默认 1800s 上限后，断线失败也回落终态路径防死挂堆积。"""
    queue = _build_queue(tmp_path)
    base = _utc_now()
    queue.submit(_send_request("req-p6-age", "dedupe-p6-age"), now=base)
    issue = _bot_unavailable_issue()

    # 临界内（<1800s）仍挂起不计数。
    inside = queue.mark_retryable_failure(
        "req-p6-age", "failed", now=base + timedelta(seconds=1799), operational_issue=issue
    )
    assert inside.state is ReceiptState.FAILED_RETRYABLE
    assert inside.retry_count == 0

    # 达到上限（>=1800s）置 FAILED_FINAL，不再挂起。
    expired = queue.mark_retryable_failure(
        "req-p6-age", "failed", now=base + timedelta(seconds=1800), operational_issue=issue
    )
    assert expired.state is ReceiptState.FAILED_FINAL
    entry = queue._find_entry_by_request_id("req-p6-age")
    assert entry is not None
    assert entry.state is ReceiptState.FAILED_FINAL
    summary = queue.safe_summary()
    assert summary[ReceiptState.FAILED_FINAL.value] == 1


def test_prfix6_age_guard_overridable_per_config(tmp_path) -> None:
    """年龄上限可经构造参数（build_send_queue 的 config 旋钮）覆盖。"""
    queue = _build_queue(tmp_path, bot_unavailable_max_age_seconds=60.0)
    base = _utc_now()
    queue.submit(_send_request("req-p6-cfg", "dedupe-p6-cfg"), now=base)
    issue = _bot_unavailable_issue()

    inside = queue.mark_retryable_failure(
        "req-p6-cfg", "failed", now=base + timedelta(seconds=59), operational_issue=issue
    )
    assert inside.state is ReceiptState.FAILED_RETRYABLE

    expired = queue.mark_retryable_failure(
        "req-p6-cfg", "failed", now=base + timedelta(seconds=60), operational_issue=issue
    )
    assert expired.state is ReceiptState.FAILED_FINAL


def test_prfix6_regular_failures_still_exhaust_attempts(tmp_path) -> None:
    """对照：豁免只针对 bot_unavailable；普通失败照常计次至终态。"""
    queue = _build_queue(tmp_path)
    base = _utc_now()
    queue.submit(_send_request("req-p6-norm", "dedupe-p6-norm"), now=base)

    receipt = None
    for _ in range(3):
        receipt = queue.mark_retryable_failure("req-p6-norm", "failed", now=base)
    assert receipt is not None
    assert receipt.state is ReceiptState.FAILED_FINAL
    assert receipt.retry_count == 3


# ==================== #13：单连接单事务终态迁移且幂等 ====================


def _counting_connect(monkeypatch: pytest.MonkeyPatch, module: object) -> list[str]:
    """统计模块 sqlite3.connect 调用次数（建表 1 次 + 长连接 1 次为基准）。"""
    calls: list[str] = []
    real_connect = module.sqlite3.connect  # type: ignore[attr-defined]

    def counting_connect(path: object, *args: object, **kwargs: object) -> object:
        calls.append(str(path))
        return real_connect(path, *args, **kwargs)

    monkeypatch.setattr(module.sqlite3, "connect", counting_connect)
    return calls


def test_prfix13_queue_full_cycle_single_connection_and_idempotent(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """queue 侧：提交-失败-送达-查询全流程只开一次长连接，mark 幂等。"""
    calls = _counting_connect(monkeypatch, queue_module)
    queue = _build_queue(tmp_path)
    base = _utc_now()
    queue.submit(_send_request("req-p13", "dedupe-p13"), now=base)

    retry_receipt = queue.mark_retryable_failure(
        "req-p13", "failed", now=base + timedelta(seconds=120)
    )
    assert retry_receipt.state is ReceiptState.FAILED_RETRYABLE

    # 重复 mark_sent：终态迁移幂等，结果一致、计数不重复。
    first_sent = queue.mark_sent("req-p13", now=base + timedelta(seconds=240))
    second_sent = queue.mark_sent("req-p13", now=base + timedelta(seconds=241))
    assert first_sent.state is ReceiptState.SENT
    assert second_sent.state is ReceiptState.SENT

    summary = queue.safe_summary()
    assert summary[ReceiptState.SENT.value] == 1
    entry = queue._find_entry_by_request_id("req-p13")
    assert entry is not None
    assert entry.state is ReceiptState.SENT

    # 建表独立连接 1 次 + 进程内长连接 1 次；后续操作零新建。
    assert len(calls) == 2


def test_prfix13_queue_terminal_migration_in_one_transaction(tmp_path) -> None:
    """同一条行 QUEUED→RETRYABLE→FINAL 的迁移各自在单事务内完成。"""
    queue = _build_queue(tmp_path)
    base = _utc_now()
    queue.submit(_send_request("req-p13b", "dedupe-p13b"), now=base)

    first = queue.mark_retryable_failure("req-p13b", "failed", now=base)
    second = queue.mark_retryable_failure(
        "req-p13b", "failed", now=base + timedelta(seconds=30)
    )
    third = queue.mark_retryable_failure(
        "req-p13b", "failed", now=base + timedelta(seconds=90)
    )
    assert (first.state, second.state) == (
        ReceiptState.FAILED_RETRYABLE,
        ReceiptState.FAILED_RETRYABLE,
    )
    assert third.state is ReceiptState.FAILED_FINAL
    summary = queue.safe_summary()
    assert summary[ReceiptState.FAILED_RETRYABLE.value] == 0
    assert summary[ReceiptState.FAILED_FINAL.value] == 1


def test_prfix13_receipts_repository_single_connection(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """receipts 侧：record/latest/find/list 复用同一长连接。"""
    from plugins.bot_unified_runtime.contracts import DeliveryReceipt

    calls = _counting_connect(monkeypatch, receipts_module)
    repository = SQLiteReceiptRepository(tmp_path / "receipts.sqlite3")
    receipt = DeliveryReceipt(
        request_id="req-p13r",
        state=ReceiptState.SENT,
        transport="onebot.v11",
        public_message="sent",
    )
    repository.record(receipt)
    assert repository.latest("req-p13r") is not None
    assert repository.find("req-p13r") is not None
    assert len(repository.list_receipts("req-p13r")) == 1

    # 建表独立连接 1 次 + 进程内长连接 1 次；后续操作零新建。
    assert len(calls) == 2


# ==================== #10：分片超时每段下限 ====================


def test_prfix10_chunk_slice_floor_for_many_chunks() -> None:
    """6 段 × 15s 预算：均分 2.5s 低于下限，每段拿到 10s；单段取全额。"""
    assert onebot_sender._MIN_CHUNK_WAIT_SECONDS == 10.0
    budget = onebot_sender._TimeoutBudget(15.0)
    assert budget.slice_for(6) == 10.0
    assert budget.slice_for(1) == 15.0


def test_prfix10_slice_floor_never_exceeds_remaining(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """剩余预算低于下限时取剩余；预算耗尽抛 TimeoutError（外层护栏）。"""
    consumed: list[float] = []
    real_monotonic = onebot_sender.time.monotonic

    def fake_monotonic() -> float:
        return consumed[-1] if consumed else real_monotonic()

    monkeypatch.setattr(onebot_sender.time, "monotonic", fake_monotonic)
    budget = onebot_sender._TimeoutBudget(15.0)
    # 快进 12s：remaining=3s < 下限 10s → 取剩余 3s，绝不超过总 deadline。
    consumed.append(budget._started + 12.0)
    assert budget.slice_for(6) == 3.0
    # 快进 16s：总预算耗尽 → TimeoutError。
    consumed.append(budget._started + 16.0)
    with pytest.raises(asyncio.TimeoutError):
        budget.slice_for(6)


def test_prfix6_constants_match_spec() -> None:
    """语义参数与检视报告规定一致（退避 90s、年龄上限 1800s）。"""
    assert queue_module._BOT_UNAVAILABLE_RETRY_DELAY_SECONDS == 90.0
    assert queue_module._BOT_UNAVAILABLE_MAX_AGE_SECONDS == 1800.0
