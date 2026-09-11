"""评审修复回归（毒行隔离，评审报告 H9）。

离线运行（SQLite 用 tmp_path，无网络、无 Playwright）：

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_queue_poison_row.py -q

背景：90f590e 只给 ``_finalize_expired_lease`` 加了毒行隔离，而
``_entry_from_row`` 的调用点（``claim_due`` 批量重读 / ``list_due`` /
``find_request``）仍会让**单条** ``request_json`` 损坏的行：

- 让整批已认领的消息在事务提交后被一起丢弃（那些行已变 processing）；
- 每轮租约过期重认领都重复抛 → 队列周期性停摆；
- 同批健康行被反复认领、烧完 max_attempts 后 FAILED_FINAL，**从未投递**。

本文件锁定修复后的语义：坏行就地被终态化并跳过，健康行照常返回。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.contracts import (
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.sender.queue import SQLiteSendRequestQueue


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _send_request(request_id: str, dedupe_key: str) -> SendRequest:
    rendered = RenderedOutput(
        request_id=request_id,
        content_type="text",
        content_ref={"text": "毒行隔离回归正文"},
        text_fallback="毒行隔离回归正文",
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
        max_items=1000,
    )


def _insert_poison_row(
    queue: SQLiteSendRequestQueue,
    *,
    dedupe_key: str,
    request_id: str,
    request_json: str = "{not-json",
    retry_count: int = 0,
    created_offset_seconds: int = 0,
) -> None:
    """直接写入一行损坏数据（模拟跨版本 request_json / 磁盘损坏）。

    ``created_at`` 早于健康行，保证它排在 claim_due 批次的第一位——这正是
    真实事故的形态（毒行恒在第一批）。
    """
    stamp = (_utc_now() - timedelta(seconds=600) + timedelta(
        seconds=created_offset_seconds
    )).isoformat()
    queue._ensure_schema_once()
    with queue._transaction() as connection:
        connection.execute(
            """
            INSERT INTO send_requests (
                dedupe_key, request_id, state, request_json, retry_count,
                next_retry_at, created_at, updated_at, claimed_from_state,
                lease_expires_at, last_public_message
            ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, NULL, NULL, ?)
            """,
            (
                dedupe_key,
                request_id,
                ReceiptState.QUEUED.value,
                request_json,
                retry_count,
                stamp,
                stamp,
                "queued",
            ),
        )


def _row_state(db_path: Path, dedupe_key: str) -> str | None:
    """用独立只读连接查状态（避免在共享连接上开事务干扰被测逻辑）。"""
    connection = sqlite3.connect(str(db_path))
    try:
        row = connection.execute(
            "SELECT state FROM send_requests WHERE dedupe_key = ?", (dedupe_key,)
        ).fetchone()
    finally:
        connection.close()
    return None if row is None else str(row[0])


def _db_path(tmp_path: Path) -> Path:
    return tmp_path / "send_queue.sqlite3"


def test_claim_due_skips_poison_row_and_returns_healthy(tmp_path) -> None:
    """毒行在首批时：健康行仍被认领，坏行就地被终态化。"""
    queue = _build_queue(tmp_path)
    _insert_poison_row(queue, dedupe_key="poison", request_id="req-poison")
    queue.submit(_send_request("req-ok", "healthy"))

    future = _utc_now() + timedelta(seconds=queue.retry_base_seconds * 10)
    claimed = queue.claim_due(now=future)

    assert [entry.send_request.request_id for entry in claimed] == ["req-ok"]
    # 坏行被就地终态化，不会每轮重复毒死批次。
    assert _row_state(_db_path(tmp_path), "poison") == ReceiptState.FAILED_FINAL.value
    # 再次认领不再抛异常。
    assert [e.send_request.request_id for e in queue.claim_due(now=future + timedelta(seconds=5))] == []


def test_claim_due_does_not_burn_healthy_attempts(tmp_path) -> None:
    """关键不变量：毒行存在时健康行的 retry_count 不得被无谓消耗。"""
    queue = _build_queue(tmp_path)
    _insert_poison_row(queue, dedupe_key="poison", request_id="req-poison")
    queue.submit(_send_request("req-ok", "healthy"))

    future = _utc_now() + timedelta(seconds=queue.retry_base_seconds * 10)
    claimed = queue.claim_due(now=future)
    assert len(claimed) == 1
    assert claimed[0].retry_count == 0
    assert claimed[0].state is ReceiptState.QUEUED


def test_list_due_skips_poison_row(tmp_path) -> None:
    """list_due 与 claim_due 同型：坏行不得让只读列举整体抛错。"""
    queue = _build_queue(tmp_path)
    _insert_poison_row(queue, dedupe_key="poison", request_id="req-poison")
    queue.submit(_send_request("req-ok", "healthy"))

    future = _utc_now() + timedelta(seconds=queue.retry_base_seconds * 10)
    due = queue.list_due(now=future)
    assert [entry.send_request.request_id for entry in due] == ["req-ok"]
    assert _row_state(_db_path(tmp_path), "poison") == ReceiptState.FAILED_FINAL.value


def test_find_request_survives_poison_row(tmp_path) -> None:
    """find_request 命中坏行时返回 None 并就地终态化，不向上抛。"""
    queue = _build_queue(tmp_path)
    _insert_poison_row(queue, dedupe_key="poison", request_id="req-poison")

    assert queue.find_request("req-poison") is None
    assert _row_state(_db_path(tmp_path), "poison") == ReceiptState.FAILED_FINAL.value


def test_poison_row_only_blocks_itself(tmp_path) -> None:
    """多条坏行 + 多条健康行同批：坏行全终态化，健康行全数返回。"""
    queue = _build_queue(tmp_path)
    _insert_poison_row(queue, dedupe_key="poison-1", request_id="req-p1")
    _insert_poison_row(
        queue, dedupe_key="poison-2", request_id="req-p2", request_json="[]"
    )
    for index in range(3):
        queue.submit(_send_request(f"req-ok-{index}", f"healthy-{index}"))

    future = _utc_now() + timedelta(seconds=queue.retry_base_seconds * 10)
    claimed = queue.claim_due(now=future, limit=20)

    assert sorted(e.send_request.request_id for e in claimed) == [
        "req-ok-0",
        "req-ok-1",
        "req-ok-2",
    ]
    assert _row_state(_db_path(tmp_path), "poison-1") == ReceiptState.FAILED_FINAL.value
    assert _row_state(_db_path(tmp_path), "poison-2") == ReceiptState.FAILED_FINAL.value


def test_invalid_timestamp_row_is_also_isolated(tmp_path) -> None:
    """时间戳非法（非 request_json 损坏）同样被隔离，不毒死整批。"""
    queue = _build_queue(tmp_path)
    _insert_poison_row(queue, dedupe_key="poison", request_id="req-poison")
    with queue._transaction() as connection:
        connection.execute(
            "UPDATE send_requests SET created_at = ? WHERE dedupe_key = ?",
            ("not-a-timestamp", "poison"),
        )
    queue.submit(_send_request("req-ok", "healthy"))

    future = _utc_now() + timedelta(seconds=queue.retry_base_seconds * 10)
    claimed = queue.claim_due(now=future)
    assert [e.send_request.request_id for e in claimed] == ["req-ok"]


def test_poison_row_finalization_is_idempotent(tmp_path) -> None:
    """重复触发（list/claim/find 交替）不产生异常与状态抖动。"""
    queue = _build_queue(tmp_path)
    _insert_poison_row(queue, dedupe_key="poison", request_id="req-poison")

    future = _utc_now() + timedelta(seconds=queue.retry_base_seconds * 10)
    for _ in range(3):
        queue.list_due(now=future)
        queue.claim_due(now=future)
        queue.find_request("req-poison")
    assert _row_state(_db_path(tmp_path), "poison") == ReceiptState.FAILED_FINAL.value


def test_healthy_row_roundtrip_unaffected(tmp_path) -> None:
    """无坏行时行为不变（防过度隔离把正常行也吞掉）。"""
    queue = _build_queue(tmp_path)
    queue.submit(_send_request("req-ok", "healthy"))

    future = _utc_now() + timedelta(seconds=queue.retry_base_seconds * 10)
    claimed = queue.claim_due(now=future)
    assert len(claimed) == 1
    assert queue.find_request("req-ok") is not None
    assert _row_state(_db_path(tmp_path), "healthy") != ReceiptState.FAILED_FINAL.value


def test_corrupt_row_query_does_not_raise(tmp_path) -> None:
    """防御性断言：坏行存在时任何只读入口都不抛 sqlite3/ValidationError。"""
    queue = _build_queue(tmp_path)
    _insert_poison_row(queue, dedupe_key="poison", request_id="req-poison")
    try:
        queue.list_due()
        queue.claim_due()
        queue.find_request("req-poison")
    except (sqlite3.Error, ValueError) as exc:  # pragma: no cover - 回归防线
        raise AssertionError(f"毒行不应向上抛异常: {exc!r}") from exc
