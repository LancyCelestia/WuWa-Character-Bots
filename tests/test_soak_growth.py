"""浸泡回归（C组，独立命名）：有界增长与异常浸泡的快速门禁版。

对应 docs/capability-audit-2026-09-10.md 的浸泡观察项：多线程异常浸泡下
好感度库行数/线程数稳定、发送队列 max_items 裁剪生效、幂等表有界。
分钟级长跑版（RSS/线程/队列曲线）用 %TEMP% 下的临时脚本执行，不入源码树。
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.character.affinity import DynamicAffinityStore
from plugins.bot_unified_runtime.contracts import PrivacyLevel, SendPolicy, SessionType
from plugins.bot_unified_runtime.contracts.runtime import RenderedOutput, SendRequest
from plugins.bot_unified_runtime.runtime.event_idempotency import EventIdempotencyTable
from plugins.bot_unified_runtime.sender.queue import SQLiteSendRequestQueue

_BEHAVIORS = ("positive", "neutral", "tease", "negative", "insult", "unknown_kind", "")


def _send_request(index: int) -> SendRequest:
    request_id = f"req-soak-{index}"
    return SendRequest(
        request_id=request_id,
        session_id="private:u1",
        target_scope=SessionType.PRIVATE,
        target_id="u1",
        capability_id="bot.chat",
        content=RenderedOutput(
            request_id=request_id,
            content_type="text",
            content_ref={},
            text_fallback="soak",
        ),
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key=f"dedupe-soak-{index}",
        cooldown_key="cooldown-soak",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="default",
    )


def test_affinity_store_survives_concurrent_exception_storm(tmp_path) -> None:
    store = DynamicAffinityStore(tmp_path / "soak.sqlite3")
    baseline_threads = threading.active_count()
    errors: list[BaseException] = []

    def worker(worker_index: int) -> None:
        try:
            for step in range(250):
                user = f"u{(worker_index * step) % 25}"
                store.observe(user, _BEHAVIORS[step % len(_BEHAVIORS)])
                store.observe(user, "positive", delta_override=(-1.0 if step % 97 == 0 else 0.01))
                store.snapshot(user)
                if step % 50 == 0:
                    store.learn_profile(user, "我住在杭州")
                    store.set_nickname(user, f"名{worker_index}")
        except BaseException as exc:  # noqa: BLE001 - 浸泡语义：收集而非中断
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert threading.active_count() == baseline_threads
    connection = sqlite3.connect(tmp_path / "soak.sqlite3")
    try:
        rows = connection.execute(
            "SELECT COUNT(*), MIN(affinity), MAX(affinity) FROM user_affinity"
        ).fetchone()
    finally:
        connection.close()
    assert rows is not None
    assert rows[0] == 25, "行数必须等于用户数：observe 不得为同一用户产生重复行"
    assert 0.0 <= rows[1] <= rows[2] <= 1.0


def test_sqlite_send_queue_prune_and_claim_cycle_stay_bounded(tmp_path) -> None:
    queue = SQLiteSendRequestQueue(
        tmp_path / "soak.sqlite3", InMemoryAuditLogger(), max_items=20
    )
    for index in range(60):
        queue.submit(_send_request(index))
    # 浸泡不变量（跨 prune 语义细节稳定）：终态 sent 行必须被窗口裁剪，不得无限堆积
    for cycle in range(3):
        due = queue.claim_due(now=datetime.now(timezone.utc), limit=20)
        for entry in due:
            queue.mark_sent(entry.send_request.request_id, "soak sent")
        queue.submit(_send_request(1000 + cycle))  # 触发 prune
        summary = queue.safe_summary()
        assert summary.get("sent", 0) <= 20


def test_event_idempotency_table_is_bounded() -> None:
    table = EventIdempotencyTable(max_entries=256)
    for index in range(3000):
        table.claim(f"evt|{index}", capability_id="bot.chat")
    assert len(table._entries) <= 256
