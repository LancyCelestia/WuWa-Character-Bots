"""TXN-B 事务并发与故障注入验收：SQLite 持久化层并发安全与崩溃一致性。

本文件是 TXN-B 席位（事务并发与故障注入验收）的交付，覆盖两个生产 SQLite
事务面——发送队列 SQLiteSendRequestQueue 与入站事件幂等表
SqliteEventIdempotencyTable——在以下三个维度的验收：

  并发 (Concurrency)
    多线程并发写/认领时，每条请求行只被投递一次，不丢消息、不双发。

  崩溃一致性 (Crash consistency)
    进程崩溃/重启后，已提交状态完整持久化，PARTIAL 断点不丢 part 进度。

  提交边界故障注入 (Commit-boundary fault injection)
    事务体内任意一点抛出 sqlite3.Error，整笔事务（包括关联表汇总列）必须
    要么全部落盘、要么全部回滚，绝不出现一半写进去的中间态。

发送队列的 RLock + BEGIN IMMEDIATE 设计意图：进程内多线程串行化事务临界区；
跨进程/跨连接依赖 SQLite 文件锁与 PK 约束。本验收在单进程多线程维度验证
无双重认领与原子去重；同时通过两个独立连接（两个实例）在单文件上模拟进程
间并发写入，验证 SQLite 自身隔离保证。

离线运行（无网络、无 SnowLuma）：

    PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe \
        -m pytest tests/test_txn_b_sqlite_concurrency_crash.py \
        -p no:cacheprovider --basetemp="$TEMP/txn-b" -q
"""

from __future__ import annotations

import sqlite3
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from plugins.bot_unified_runtime.domains.chat_reply.runtime.event_idempotency import (
    SqliteEventIdempotencyTable,
)
from plugins.bot_unified_runtime.domains.transport.sender.queue import (
    PART_STATE_PENDING,
    PART_STATE_SENT,
    PARTIAL_ROW_STATE,
    SQLiteSendRequestQueue,
)

# ---------------------------------------------------------------------------
# 公共辅助
# ---------------------------------------------------------------------------

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _send_request(
    request_id: str,
    *,
    session_id: str = "private:user-1",
    dedupe_key: str | None = None,
) -> SendRequest:
    rendered = RenderedOutput(
        request_id=request_id,
        content_type="text",
        content_ref={"text": "TXN-B 验收正文"},
        text_fallback="TXN-B 验收正文",
        privacy_level=PrivacyLevel.PERSONAL,
    )
    return SendRequest(
        request_id=request_id,
        session_id=session_id,
        target_scope=SessionType.PRIVATE,
        target_id="user-1",
        capability_id="bot.chat",
        content=rendered,
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key=dedupe_key if dedupe_key is not None else f"dedupe-{request_id}",
        cooldown_key=f"bot.chat:{session_id}",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="default",
    )


def _row_count(queue: SQLiteSendRequestQueue, state: str | None = None) -> int:
    """安全读取队列行数（不依赖外部连接锁，用新连接读）。"""
    with sqlite3.connect(str(queue.db_path), timeout=5.0) as conn:
        if state is None:
            return conn.execute("SELECT COUNT(*) FROM send_requests").fetchone()[0]
        row = conn.execute(
            "SELECT COUNT(*) FROM send_requests WHERE state = ?", (state,)
        ).fetchone()
    return int(row[0])


# ---------------------------------------------------------------------------
# T1: 单实例并发 submit 相同 dedupe_key → 原子去重，只落一行
# ---------------------------------------------------------------------------

def test_concurrent_submit_same_dedupe_key_exactly_one_row(
    tmp_path: Path,
) -> None:
    """多个线程并发提交同一 dedupe_key，INSERT ON CONFLICT DO NOTHING 保证
    有且仅有一行落库，其余线程收到 SKIPPED 回执。验证 PK+原子性（A 维度）。

    单进程实例内 RLock 串行化事务临界区，ON CONFLICT 保证逻辑原子性。
    """
    queue = SQLiteSendRequestQueue(tmp_path / "q.sqlite3", InMemoryAuditLogger())
    base = _utc_now()
    request = _send_request("dup-key-test", dedupe_key="same-dedupe")
    results: list[DeliveryReceipt] = []
    barrier = threading.Barrier(6)

    def worker() -> None:
        barrier.wait()
        results.append(queue.submit(request, now=base))

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda _: worker(), range(6)))

    states = [r.state for r in results]
    queued_count = states.count(ReceiptState.QUEUED)
    skipped_count = states.count(ReceiptState.SKIPPED)
    assert queued_count == 1, f"应只有一行 QUEUED，实际 {queued_count}"
    assert skipped_count == 5, f"其余应全 SKIPPED，实际 {skipped_count}"
    assert _row_count(queue, ReceiptState.QUEUED.value) == 1
    assert _row_count(queue) == 1  # 整张表只有一行


# ---------------------------------------------------------------------------
# T2: 两实例（两连接）并发提交不同键 → 全部落库，无丢写
# ---------------------------------------------------------------------------

def test_concurrent_two_instances_distinct_keys_all_committed(
    tmp_path: Path,
) -> None:
    """两个 SQLiteSendRequestQueue 实例（模拟两进程）写同一文件，各线程提交
    互不相同的 dedupe_key，SQLite 文件锁保证所有事务提交、无丢行。验证写入
    隔离性（A 维度）。"""
    db = tmp_path / "q.sqlite3"
    base = _utc_now()
    # 预建 schema（两实例均会建表，幂等）。
    SQLiteSendRequestQueue(db, InMemoryAuditLogger())._ensure_schema()

    queue_a = SQLiteSendRequestQueue(db, InMemoryAuditLogger())
    queue_b = SQLiteSendRequestQueue(db, InMemoryAuditLogger())

    requests_per_queue = 3
    all_requests = [
        _send_request(
            f"distinct-{qname}-{i}",
            session_id=f"private:{qname}-{i}",
        )
        for qname, queue in (("a", queue_a), ("b", queue_b))
        for i in range(requests_per_queue)
    ]

    def submit_with_retry(q: SQLiteSendRequestQueue, req: SendRequest) -> None:
        for attempt in range(3):
            try:
                q.submit(req, now=base)
                return
            except sqlite3.OperationalError:  # pragma: no cover - rare busy
                if attempt == 2:
                    raise
                import time
                time.sleep(0.1)

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = []
        for queue_inst, group in (
            (queue_a, all_requests[:requests_per_queue]),
            (queue_b, all_requests[requests_per_queue:]),
        ):
            for req in group:
                futures.append(pool.submit(submit_with_retry, queue_inst, req))
        for fut in as_completed(futures):
            fut.result()

    # 用新实例验证磁盘状态
    verify_queue = SQLiteSendRequestQueue(db, InMemoryAuditLogger())
    total = _row_count(verify_queue)
    assert total == requests_per_queue * 2, f"应全部落库，实际 {total} 行"


# ---------------------------------------------------------------------------
# T3: 多线程并发 claim_due 不得重复认领同一行
# ---------------------------------------------------------------------------

def test_concurrent_claim_due_no_double_claim(tmp_path: Path) -> None:
    """6 条到期行（各 session 唯一），4 线程并发 claim_due，任何行最多被一个
    线程认领一次。BEGIN IMMEDIATE + RLock 保证认领临界区内不可并发。
    验证认领互斥性（A 维度）。"""
    queue = SQLiteSendRequestQueue(tmp_path / "q.sqlite3", InMemoryAuditLogger())
    base = _utc_now() - timedelta(hours=2)  # 所有行对 claim_due 均已到期
    row_count = 6
    for i in range(row_count):
        req = _send_request(f"claim-{i}", session_id=f"private:sess-{i}")
        # deliver_after=base：next_retry_at 为过去，立即到期；不登记内联台账。
        queue.submit(req, now=base, deliver_after=base)

    claimed_ids: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(4)
    now_claim = base + timedelta(hours=1)

    def claim_worker() -> None:
        barrier.wait()
        batch = queue.claim_due(now=now_claim, limit=10, lease_seconds=600)
        with lock:
            claimed_ids.extend(e.send_request.request_id for e in batch)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: claim_worker(), range(4)))

    counts = Counter(claimed_ids)
    duplicates = {rid: c for rid, c in counts.items() if c > 1}
    assert not duplicates, f"发现重复认领（双发风险）：{duplicates}"
    # 所有行最终被认领（4 线程 × 10 limit ≥ 6 行，单轮即尽）
    assert len(claimed_ids) == row_count, (
        f"应恰好认领 {row_count} 行，实际 {len(claimed_ids)}"
    )


# ---------------------------------------------------------------------------
# T4: 提交边界故障注入——事务体内 sqlite3.Error → 整笔回滚 + 连接丢弃
# ---------------------------------------------------------------------------

def test_commit_boundary_fault_rolls_back_entire_submit(
    tmp_path: Path,
) -> None:
    """在事务体最后一步（INSERT 后、commit 前）注入 sqlite3.OperationalError，
    验证：(1) submit 抛出 OperationalError；(2) 行未落库（原子回滚）；
    (3) _connection 被丢弃；(4) 未注入后正常提交可恢复。
    验证原子性/回滚路径（I 维度）。"""
    db = tmp_path / "q.sqlite3"
    queue = SQLiteSendRequestQueue(db, InMemoryAuditLogger())
    base = _utc_now()
    request = _send_request("fault-test-1", session_id="private:fault")

    original_prune = queue._prune

    def _fault_prune(conn: sqlite3.Connection) -> None:
        raise sqlite3.OperationalError("TXN-B 注入：提交边界故障")

    # 注入 _prune（在事务体内 INSERT 之后被调用）
    queue._prune = _fault_prune  # type: ignore[assignment]
    with pytest.raises(sqlite3.OperationalError, match="TXN-B 注入"):
        queue.submit(request, now=base)

    # (1) 事务回滚：用新连接直接查磁盘，行不存在
    with sqlite3.connect(str(db), timeout=5.0) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM send_requests WHERE request_id = ?",
            ("fault-test-1",),
        ).fetchone()
    assert int(row[0]) == 0, "故障注入后行不应存在（原子回滚）"

    # (2) 连接被丢弃（_connection is None）
    assert queue._connection is None, "故障后应丢弃连接"

    # (3) 还原 _prune 后正常提交成功（连接重建）
    queue._prune = original_prune  # type: ignore[assignment]
    receipt = queue.submit(request, now=base)
    assert receipt.state == ReceiptState.QUEUED
    assert _row_count(queue, ReceiptState.QUEUED.value) == 1


# ---------------------------------------------------------------------------
# T5: part 明细与请求行汇总的同事务原子性——故障注入两表均回滚
# ---------------------------------------------------------------------------

def test_part_progress_atomic_rollback_on_mid_txn_fault(
    tmp_path: Path,
) -> None:
    """mark_part_sent 事务体内：UPDATE part_detail → _refresh_request_summary。
    若在汇总步骤注入故障，part 明细的更新也必须一并回滚（两表同事务）。
    验证多表写原子性（I 维度）。"""
    db = tmp_path / "q.sqlite3"
    queue = SQLiteSendRequestQueue(db, InMemoryAuditLogger())
    base = _utc_now()
    req = _send_request("part-atomic", session_id="private:pa")
    queue.submit(req, now=base, deliver_after=base)
    queue.ensure_parts_planned("part-atomic", ["d0", "d1"], now=base)
    queue.mark_part_attempt("part-atomic", 0, now=base)

    # 确认 part0 在 attempt 后为 pending、parts_delivered==0
    progress_before = queue.part_progress("part-atomic")
    assert progress_before is not None
    assert progress_before.records[0].state == PART_STATE_PENDING

    # 注入：在 _refresh_request_part_summary_in 抛 sqlite3.Error
    # （SEAT-FIX-QKEY 跟随：真身新增行身份寻址参数 dedupe_key/row_identity，
    # 故障替身签名同步扩展，注入点与断言语义零改动）
    original_refresh = queue._refresh_request_part_summary_in

    def _fault_refresh(
        conn: sqlite3.Connection,
        request_id: str,
        *,
        now: datetime,
        dedupe_key: str | None = None,
        row_identity: str | None = None,
    ) -> None:
        raise sqlite3.OperationalError("TXN-B 注入：part 汇总步骤故障")

    queue._refresh_request_part_summary_in = _fault_refresh  # type: ignore[assignment]
    result = queue.mark_part_sent("part-atomic", 0, provider_message_id="msg-x", now=base)
    # _update_part_row 捕获 sqlite3.Error → return False，不向外抛
    assert result is False, "注入故障时 mark_part_sent 应返回 False"

    # part0 状态仍 pending（UPDATE send_request_parts 也一并回滚）
    progress_after_fault = queue.part_progress("part-atomic")
    assert progress_after_fault is not None
    assert progress_after_fault.records[0].state == PART_STATE_PENDING, (
        "part 明细应与汇总一同回滚为 pending"
    )

    # 还原后正常 mark_part_sent → True，两表均更新且一致
    queue._refresh_request_part_summary_in = original_refresh  # type: ignore[assignment]
    assert queue.mark_part_sent("part-atomic", 0, provider_message_id="msg-x", now=base)
    progress_final = queue.part_progress("part-atomic")
    assert progress_final is not None
    assert progress_final.records[0].state == PART_STATE_SENT
    assert progress_final.delivered == 1


# ---------------------------------------------------------------------------
# T6: 崩溃恢复——PARTIAL 断点与已 SENT part 跨实例（重启）持久化
# ---------------------------------------------------------------------------

def test_crash_recovery_partial_breakpoint_survives_reopen(
    tmp_path: Path,
) -> None:
    """模拟进程崩溃后重启：instance1 置部分 part SENT → 实例被销毁（进程崩）
    → instance2 在同一文件重建，PARTIAL 断点可见，已 SENT part 不变，
    未发送 part 仍可续发。验证持久性/断点恢复（D 维度）。"""
    db = tmp_path / "q.sqlite3"
    base = _utc_now()
    req = _send_request("crash-partial", session_id="private:cp")

    # --- instance1：正常投递至 PARTIAL ---
    q1 = SQLiteSendRequestQueue(db, InMemoryAuditLogger())
    q1.submit(req, now=base, deliver_after=base)
    q1.ensure_parts_planned("crash-partial", ["p0", "p1"], now=base)
    q1.mark_part_sent("crash-partial", 0, provider_message_id="m0", now=base)
    q1.mark_part_attempt("crash-partial", 1, now=base)
    # part1 尚未发出；mark_final_failure → 断点守卫转为 PARTIAL
    q1.mark_final_failure("crash-partial", "boom", now=base)

    # --- 模拟进程崩溃：丢弃 q1 的连接（不显式 close，仅放弃实例） ---
    del q1

    # --- instance2：跨"重启"读同一文件 ---
    q2 = SQLiteSendRequestQueue(db, InMemoryAuditLogger())
    # 持久化的行状态必须是裸字符串 'partial'（断点语义，非 FAILED_FINAL）。
    assert _row_count(q2, PARTIAL_ROW_STATE) == 1, "行应持久化为 PARTIAL 状态"
    partials = q2.list_partial_requests(now=base)
    partial_ids = [e.send_request.request_id for e in partials]
    assert "crash-partial" in partial_ids, "重启后 PARTIAL 行应可见"

    progress = q2.part_progress("crash-partial")
    assert progress is not None
    assert progress.total == 2
    assert progress.delivered == 1, "已 SENT 的 part0 不应在重启后丢失"
    assert progress.records[0].state == PART_STATE_SENT
    assert progress.records[1].state == PART_STATE_PENDING
    # part1 仍为 pending，可被续发（attempts>=1 记录已有）
    assert progress.records[1].attempts >= 1, "part1 尝试次数应至少为 1"


# ---------------------------------------------------------------------------
# T7: 事件幂等表——并发 claim 同键，恰好一个赢家
# ---------------------------------------------------------------------------

def test_event_idempotency_concurrent_same_key_exactly_one_winner(
    tmp_path: Path,
) -> None:
    """多线程同时 claim 同一 (event_key, capability_id)，本进程内锁 +
    PRIMARY KEY 保证有且仅有一个 claim() 返回 True（首次出现）。
    验证幂等保证在并发下成立（A 维度）。"""
    table = SqliteEventIdempotencyTable(tmp_path / "dedup.sqlite3")
    key = "snowluma|bot1|msg42"
    cap = "bot.chat"
    results: list[bool] = []
    barrier = threading.Barrier(6)

    def worker() -> None:
        barrier.wait()
        results.append(table.claim(key, capability_id=cap))

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda _: worker(), range(6)))

    winners = sum(results)
    assert winners == 1, f"同键并发 claim 应只有一个 True，实际 {winners}"
    assert len(table) == 1


# ---------------------------------------------------------------------------
# T8: 事件幂等跨重启——持久化拦截重放事件
# ---------------------------------------------------------------------------

def test_event_idempotency_persist_across_restart(tmp_path: Path) -> None:
    """instance1 首次 claim → True；模拟重启（新 instance2），同键仍被拒
    (False)；不同 capability_id 独立放行（多 matcher 共存）。验证持久化
    正确性（D 维度）。"""
    db = tmp_path / "dedup.sqlite3"
    base = float(1_700_000_000)  # 固定时间戳，避免 TTL 窗口飘
    t1 = SqliteEventIdempotencyTable(db, clock=lambda: base)
    assert t1.claim("onebot|bot1|msg1", capability_id="bot.chat") is True

    # 重启
    t2 = SqliteEventIdempotencyTable(db, clock=lambda: base + 10)
    assert t2.claim("onebot|bot1|msg1", capability_id="bot.chat") is False, (
        "重启后同键应被拦截"
    )
    # 不同 capability_id 独立放行（PK 复合键，不同能力互不影响）
    assert t2.claim("onebot|bot1|msg1", capability_id="bot.digest") is True
