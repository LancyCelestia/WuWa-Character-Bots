"""B组 sender 域回归（管线检视 #6/#10/#13 + B-12 代理注入）。

离线运行（SQLite 用 tmp_path，无网络、无 NapCat）：

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_bgroup_sender_delivery.py -q

覆盖项：
- B-4 bot_unavailable 挂起不消耗重试预算：断线远超 max_attempts 轮次后
  消息仍可投；普通失败照常计数；入队超 24h 保持上限才置终态。
- B-7 分片超时下限：多段均分不再把每段压到秒级以下语义。
- B-10 共享长连接：一次提交-回执-查询全流程只新建一次连接。
- B-12 下载代理注入 getter 优先于 driver config / env 探测链。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

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
from plugins.bot_unified_runtime.sender import nonebot as nonebot_sender
from plugins.bot_unified_runtime.sender import onebot as onebot_sender
from plugins.bot_unified_runtime.sender import queue as queue_module
from plugins.bot_unified_runtime.sender.queue import SQLiteSendRequestQueue


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _send_request(
    request_id: str,
    dedupe_key: str,
    *,
    text: str = "B组回归正文",
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


def _build_queue(tmp_path: Path) -> SQLiteSendRequestQueue:
    return SQLiteSendRequestQueue(
        tmp_path / "send_queue.sqlite3",
        InMemoryAuditLogger(),
    )


def _bot_unavailable_issue() -> OperationalIssue:
    return OperationalIssue(
        stage="queue",
        kind="bot_unavailable",
        retryable=True,
        safe_summary="bot_unavailable",
    )


# ==================== B-4：断线挂起不烧重试预算 ====================


def test_bot_unavailable_defers_without_consuming_attempts(tmp_path) -> None:
    queue = _build_queue(tmp_path)
    queue.submit(_send_request("req-b4", "dedupe-b4"))
    issue = _bot_unavailable_issue()

    # 远超 max_attempts=3 轮断线失败：retry_count 不再递增，行保持可重试。
    for _ in range(6):
        receipt = queue.mark_retryable_failure(
            "req-b4", "failed", operational_issue=issue
        )
        assert receipt.state is ReceiptState.FAILED_RETRYABLE
        assert receipt.retry_count == 0

    entry = queue._find_entry_by_request_id("req-b4")
    assert entry.retry_count == 0
    # bot 恢复后照常标记送达。
    sent = queue.mark_sent("req-b4")
    assert sent.state is ReceiptState.SENT


def test_regular_failures_still_exhaust_attempts(tmp_path) -> None:
    """B-4 只豁免 bot_unavailable；普通失败路径语义不变。"""
    queue = _build_queue(tmp_path)
    queue.submit(_send_request("req-norm", "dedupe-norm"))

    for _ in range(3):
        receipt = queue.mark_retryable_failure("req-norm", "failed")
    assert receipt.state is ReceiptState.FAILED_FINAL


def test_bot_unavailable_hold_expires_to_final(tmp_path) -> None:
    """入队超保持上限后，断线失败也置终态（防 A4 下死挂行无限堆积）。"""
    queue = _build_queue(tmp_path)
    queue.submit(_send_request("req-hold", "dedupe-hold"))
    issue = _bot_unavailable_issue()
    late = _utc_now() + timedelta(hours=25)

    receipt = queue.mark_retryable_failure(
        "req-hold", "failed", now=late, operational_issue=issue
    )
    assert receipt.state is ReceiptState.FAILED_FINAL


def test_bot_unavailable_defer_keeps_retry_interval_positive(tmp_path) -> None:
    queue = _build_queue(tmp_path)
    queue.submit(_send_request("req-b4b", "dedupe-b4b"))
    receipt = queue.mark_retryable_failure(
        "req-b4b", "failed", operational_issue=_bot_unavailable_issue()
    )
    assert receipt.next_retry_at is not None
    assert receipt.next_retry_at > _utc_now() - timedelta(seconds=1)


# ==================== B-7：分片超时下限 ====================


def test_timeout_budget_slice_has_floor_for_many_chunks() -> None:
    budget = onebot_sender._TimeoutBudget(15.0)
    # 6 段均分=2.5s，下限钳到单条消息标准超时 10s。
    assert budget.slice_for(6) == 10.0
    # 段数少时均分值高于下限，取均分。
    assert budget.slice_for(1) == 15.0


def test_timeout_budget_floor_never_exceeds_remaining(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    budget = onebot_sender._TimeoutBudget(15.0)
    consumed: list[float] = []

    real_monotonic = onebot_sender.time.monotonic

    def fake_monotonic() -> float:
        now = consumed[-1] if consumed else real_monotonic()
        return now

    monkeypatch.setattr(onebot_sender.time, "monotonic", fake_monotonic)
    # 建议构造完成后快进 12s：remaining=3s < 下限 10s → 取 remaining。
    consumed.append(budget._started + 12.0)
    assert budget.slice_for(6) == 3.0
    # remaining 耗尽 → TimeoutError。
    consumed.append(budget._started + 16.0)
    with pytest.raises(asyncio.TimeoutError):
        budget.slice_for(6)


# ==================== B-10：共享长连接 ====================


def test_full_delivery_cycle_opens_single_connection(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connect_calls: list[str] = []
    real_connect = queue_module.sqlite3.connect

    def counting_connect(path, *args, **kwargs):
        connect_calls.append(str(path))
        return real_connect(path, *args, **kwargs)

    monkeypatch.setattr(queue_module.sqlite3, "connect", counting_connect)
    queue = _build_queue(tmp_path)
    queue.submit(_send_request("req-b10", "dedupe-b10"))
    queue.mark_retryable_failure("req-b10", "failed")
    queue.mark_sent("req-b10")
    queue.safe_summary()
    queue.find_request("req-b10")

    # 一次建表（独立连接）+ 一个进程内长连接；操作本身不再新建连接。
    assert len(connect_calls) == 2


# ==================== B-12：下载代理注入 ====================


def test_bot_unavailable_max_age_knob_reaches_queue(tmp_path) -> None:
    """终审 Minor② 回归：config 旋钮须真实到达队列实例。

    此前 Config 缺 `bot_send_bot_unavailable_max_age_seconds` 字段声明，
    env 键被 pydantic 丢弃，build_send_queue 的 getattr 恒取默认——旋钮
    名存实亡（§14.4.2：env 键须有同名小写字段）。
    """
    from plugins.bot_unified_runtime.config import Config
    from plugins.bot_unified_runtime.sender.queue import build_send_queue

    config = Config.model_validate(
        {
            "bot_send_queue_enabled": True,
            "bot_send_queue_db_path": str(tmp_path / "q.sqlite3"),
            "bot_send_bot_unavailable_max_age_seconds": 60.0,
        }
    )
    queue = build_send_queue(config, InMemoryAuditLogger())

    assert isinstance(queue, SQLiteSendRequestQueue)
    assert queue._bot_unavailable_max_age_seconds == 60.0


def test_download_proxy_provider_takes_priority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        nonebot_sender, "_download_proxy_provider", lambda: "http://127.0.0.1:7890"
    )
    assert (
        nonebot_sender._resolve_download_proxy(bot=None)
        == "http://127.0.0.1:7890"
    )


def test_download_proxy_provider_error_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken() -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(nonebot_sender, "_download_proxy_provider", broken)
    monkeypatch.setenv("BOT_DOWNLOAD_PROXY", "http://env-fallback:9")
    assert nonebot_sender._resolve_download_proxy(bot=None) == "http://env-fallback:9"


def test_download_proxy_empty_provider_value_uses_bot_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(nonebot_sender, "_download_proxy_provider", lambda: "")

    class _Bot:
        config = SimpleNamespace(bot_download_proxy="http://driver:1")

    assert nonebot_sender._resolve_download_proxy(bot=_Bot()) == "http://driver:1"
