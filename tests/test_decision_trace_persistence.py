"""审查 P-03：决策影子痕迹落盘 + /bot decision 查询消费回归测试。

覆盖四条验收：
① 落盘：produce N 条后 SQLite 有 N 行、字段齐全（agree 三态/stages JSON/
   created_at ISO）；建表幂等（重开同库续写不炸）。
② 查询命令：管理员可见分歧摘要；非管理员拒绝；自由文本字段脱敏+截断；
   不回显任何消息原文；N 参数缺省/钳制/垃圾输入兜底。
③ 热缓冲语义零变化：SqliteDecisionTraceSink 的 deque 行为与
   InMemoryDecisionTraceSink 逐项对齐（有界、超限丢最旧、顺序、clear）。
④ recent 回退：库文件缺失时回落热缓冲；脏行跳过不炸查询。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from plugins.bot_unified_runtime.capabilities.echo import build_decision_query_result
from plugins.bot_unified_runtime.decision.trace import (
    DEFAULT_TRACE_DB_FILENAME,
    DecisionStageRow,
    DecisionTrace,
    InMemoryDecisionTraceSink,
    SqliteDecisionTraceSink,
)

_BASE = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)


def _trace(
    index: int,
    *,
    agree: bool | None = None,
    note: str = "",
    error: str = "",
    stages: tuple[DecisionStageRow, ...] = (),
) -> DecisionTrace:
    """确定性痕迹工厂：id/时间随 index 递增，便于断言顺序。"""
    return DecisionTrace(
        trace_id=f"dt_{index:03d}",
        request_id=f"req_{index:03d}",
        mode="shadow",
        origin="pipeline_hook",
        plan_action="reply_text",
        plan_capability_id="bot.content" if agree is False else "bot.chat",
        plan_reason="引擎测试理由",
        route_kind="content" if agree is False else "chat",
        route_priority=46 if agree is False else 50,
        legacy_capability_id="bot.chat",
        agree=agree,
        compare_note=note,
        elapsed_ms=1.0 + index,
        error=error,
        stages=stages
        or (
            DecisionStageRow(stage="router", kind="route", allowed=None, reason="r", ms=0.1),
            DecisionStageRow(stage="action_resolver", kind="plan", allowed=True, reason="p", ms=0.2),
        ),
        created_at=_BASE + timedelta(seconds=index),
    )


# -------------------- ① 落盘 --------------------


def test_persist_writes_all_rows_with_full_fields(tmp_path) -> None:
    db = tmp_path / DEFAULT_TRACE_DB_FILENAME
    sink = SqliteDecisionTraceSink(db, max_entries=100)
    try:
        traces = [
            _trace(0, agree=False, note="expected=bot.chat|bot.content"),
            _trace(1, agree=True),
            _trace(2, agree=None, note="unmodeled_legacy_capability:bot.group_policy"),
            _trace(3, error="RuntimeError: engine exploded"),
            _trace(4),
        ]
        for trace in traces:
            sink.record(trace)
        assert sink.flush(timeout=5.0) is True

        with sqlite3.connect(db) as conn:
            rows = conn.execute(
                "SELECT trace_id, request_id, mode, origin, plan_action,"
                " plan_capability_id, route_kind, route_priority,"
                " legacy_capability_id, agree, compare_note, elapsed_ms,"
                " error, stages_json, created_at"
                " FROM decision_trace ORDER BY id"
            ).fetchall()
        assert len(rows) == 5

        divergent = rows[0]
        assert divergent[0] == "dt_000"
        assert divergent[1] == "req_000"
        assert divergent[2] == "shadow"
        assert divergent[3] == "pipeline_hook"
        assert divergent[4] == "reply_text"
        assert divergent[5] == "bot.content"
        assert divergent[6] == "content"
        assert divergent[7] == 46
        assert divergent[8] == "bot.chat"
        assert divergent[9] == 0  # agree False → 0
        assert divergent[10] == "expected=bot.chat|bot.content"
        assert divergent[11] == 1.0
        assert divergent[12] == ""
        assert divergent[14] == "2026-09-15T12:00:00+00:00"
        import json

        stages = json.loads(divergent[13])
        assert [item["stage"] for item in stages] == ["router", "action_resolver"]
        assert stages[1]["allowed"] is True

        incomparable = rows[2]
        assert incomparable[9] is None  # agree None → NULL
        errored = rows[3]
        assert errored[12] == "RuntimeError: engine exploded"
        agree_true = rows[1]
        assert agree_true[9] == 1  # agree True → 1
    finally:
        sink.close()


def test_schema_recreate_is_idempotent_and_appends(tmp_path) -> None:
    db = tmp_path / DEFAULT_TRACE_DB_FILENAME
    sink = SqliteDecisionTraceSink(db)
    try:
        sink.record(_trace(0))
        assert sink.flush(timeout=5.0) is True
    finally:
        sink.close()
    # 重开同一库（模拟重启）：建表幂等，续写不冲突。
    sink2 = SqliteDecisionTraceSink(db)
    try:
        sink2.record(_trace(1))
        sink2.record(_trace(2))
        assert sink2.flush(timeout=5.0) is True
        with sqlite3.connect(db) as conn:
            (count,) = conn.execute("SELECT COUNT(*) FROM decision_trace").fetchone()
        assert count == 3
    finally:
        sink2.close()


def test_concurrent_records_all_persist(tmp_path) -> None:
    import threading

    db = tmp_path / DEFAULT_TRACE_DB_FILENAME
    sink = SqliteDecisionTraceSink(db, max_entries=4096)
    try:
        def _produce(worker: int) -> None:
            for i in range(20):
                sink.record(_trace(worker * 100 + i))

        threads = [threading.Thread(target=_produce, args=(w,)) for w in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sink.flush(timeout=10.0) is True
        with sqlite3.connect(db) as conn:
            (count,) = conn.execute("SELECT COUNT(*) FROM decision_trace").fetchone()
        assert count == 80
    finally:
        sink.close()


# -------------------- ② 查询命令 --------------------


def test_query_denies_non_admin() -> None:
    result = build_decision_query_result(actor_roles=["user"], query="", sink=None)
    assert result.capability_id == "bot.decision"
    assert "decision_denied" in (result.audit_tags or [])
    assert result.body  # 守岸人语气拒绝文案，非空


def test_query_outputs_divergence_summary_from_persisted_rows(tmp_path) -> None:
    db = tmp_path / DEFAULT_TRACE_DB_FILENAME
    sink = SqliteDecisionTraceSink(db)
    try:
        sink.record(_trace(0, agree=True))
        sink.record(_trace(1, agree=False, note="expected=bot.chat|bot.content"))
        sink.record(_trace(2, agree=None))
        assert sink.flush(timeout=5.0) is True
        result = build_decision_query_result(
            request_id="req_q", actor_roles=["admin"], query="", sink=sink
        )
    finally:
        sink.close()
    assert result.capability_id == "bot.decision"
    assert "decision_denied" not in (result.audit_tags or [])
    # 双方判定与分歧摘要齐出（新→旧：dt_002 在最前）。
    assert "决策影子痕迹：最近 3 条（新→旧）" in result.body
    assert "bot.content" in result.body
    assert "bot.chat" in result.body
    assert "一致" in result.body and "分歧" in result.body and "不可比" in result.body
    assert "路由 content" in result.body and "路由 chat" in result.body
    assert "expected=bot.chat|bot.content" in result.body
    assert "（只含结构字段，不回显消息原文）" in result.body


def test_query_redacts_and_truncates_free_text_fields(tmp_path) -> None:
    db = tmp_path / DEFAULT_TRACE_DB_FILENAME
    sink = SqliteDecisionTraceSink(db)
    try:
        long_marker = "x" * 200
        sink.record(
            _trace(
                0,
                agree=False,
                note=f"session_id=abc123 secret leaked sk-abcdefgh12345678 {long_marker}",
                error="boom",
            )
        )
        sink.record(_trace(1, agree=True, note="引擎测试理由"))
        assert sink.flush(timeout=5.0) is True
        result = build_decision_query_result(
            actor_roles=["admin"], query="", sink=sink
        )
    finally:
        sink.close()
    # 脱敏：键值形态敏感值与 sk- 串绝不原样出卡。
    assert "abc123" not in result.body
    assert "sk-abcdefgh12345678" not in result.body
    assert "session_id=[redacted]" in result.body
    assert "sk-[redacted]" in result.body
    # 截断：超长备注（dt_000 那条）截到 80 字符 + 省略号；短备注原样。
    note_lines = [
        line for line in result.body.splitlines() if line.strip().startswith("备注:")
    ]
    truncated = next(line for line in note_lines if "x" in line)
    assert len(truncated.strip()) <= len("备注: ") + 80 + 1
    assert "…" in truncated
    assert "   备注: 引擎测试理由" in note_lines  # 短备注原样出


def test_query_never_echoes_message_original_text(tmp_path) -> None:
    db = tmp_path / DEFAULT_TRACE_DB_FILENAME
    sink = SqliteDecisionTraceSink(db)
    try:
        # 消息原文从设计上就不进 DecisionTrace；这里用哨兵串证明即使调用方
        # 传过含原文的消息，痕迹与出卡正文里也不会出现。
        sentinel = "机密原文绝不出卡"
        trace = _trace(0, agree=False, note="expected=bot.chat|bot.content")
        assert all(sentinel not in str(getattr(trace, field)) for field in trace.__dataclass_fields__)
        sink.record(trace)
        assert sink.flush(timeout=5.0) is True
        result = build_decision_query_result(
            actor_roles=["admin"], query="", sink=sink
        )
    finally:
        sink.close()
    assert sentinel not in result.body
    assert "expected=bot.chat|bot.content" in result.body  # 结构字段（比对备注）正常出


def test_query_limit_default_clamp_and_garbage(tmp_path) -> None:
    db = tmp_path / DEFAULT_TRACE_DB_FILENAME
    sink = SqliteDecisionTraceSink(db)
    try:
        for i in range(5):
            sink.record(_trace(i, agree=(i % 2 == 0)))
        assert sink.flush(timeout=5.0) is True

        def _body(query: str) -> str:
            return build_decision_query_result(
                actor_roles=["admin"], query=query, sink=sink
            ).body

        # 缺省 20（只有 5 条则全出）；N=2 取最近 2 条；N=0 钳到 1；垃圾回缺省。
        # 行结构：头行 + N 条痕迹行 + 尾注行（无备注行，note 全空）。
        assert "最近 5 条" in _body("")
        assert len(_body("").splitlines()) == 5 + 2
        two = _body("2")
        assert "最近 2 条" in two and len(two.splitlines()) == 2 + 2
        one = _body("1")
        assert "最近 1 条" in one and len(one.splitlines()) == 1 + 2
        assert "5.0ms" in one  # 新→旧：只有 dt_004（elapsed=1+4）这 1 条
        assert "最近 5 条" in _body("abc")
        assert "最近 5 条" in _body("500")  # 只有 5 条；500 钳到 100
    finally:
        sink.close()


def test_query_empty_state_mentions_shadow_mode() -> None:
    class _EmptySink:
        def recent(self, limit: int) -> list[DecisionTrace]:
            return []

    result = build_decision_query_result(
        actor_roles=["admin"], query="", sink=_EmptySink()
    )
    assert "暂无记录" in result.body
    assert "BOT_DECISION_ENGINE_MODE=shadow" in result.body


# -------------------- ③ 热缓冲语义零变化 --------------------


def test_hot_buffer_semantics_match_inmemory(tmp_path) -> None:
    mem = InMemoryDecisionTraceSink(max_entries=3)
    per = SqliteDecisionTraceSink(tmp_path / DEFAULT_TRACE_DB_FILENAME, max_entries=3)
    try:
        for i in range(5):
            mem.record(_trace(i))
            per.record(_trace(i))
        # 与既有 test_trace_sink_is_bounded 同口径：有界、超限丢最旧、顺序一致。
        assert [t.trace_id for t in per.snapshot()] == ["dt_002", "dt_003", "dt_004"]
        assert [t.trace_id for t in per.snapshot()] == [t.trace_id for t in mem.snapshot()]
        assert len(per) == len(mem) == 3
        per.clear()
        assert len(per) == 0
        assert per.snapshot() == []
    finally:
        per.close()


# -------------------- ④ recent 回退与脏行 --------------------


def test_recent_falls_back_to_memory_when_db_missing(tmp_path) -> None:
    db = tmp_path / DEFAULT_TRACE_DB_FILENAME
    sink = SqliteDecisionTraceSink(db, max_entries=100)
    try:
        for i in range(3):
            sink.record(_trace(i))
        assert sink.flush(timeout=5.0) is True
    finally:
        sink.close()  # 先关写线程释放文件句柄（Windows 下打开即锁）。
    db.unlink()
    # 库没了：回落热缓冲，同口径新→旧。
    recent = sink.recent(2)
    assert [t.trace_id for t in recent] == ["dt_002", "dt_001"]


def test_recent_skips_malformed_rows(tmp_path) -> None:
    db = tmp_path / DEFAULT_TRACE_DB_FILENAME
    sink = SqliteDecisionTraceSink(db)
    try:
        sink.record(_trace(0, agree=True))
        assert sink.flush(timeout=5.0) is True
        with sqlite3.connect(db) as conn:
            conn.execute(
                "INSERT INTO decision_trace (trace_id, stages_json, created_at)"
                " VALUES ('dt_bad', 'not-json{', 'garbage-timestamp')"
            )
        recent = sink.recent(10)
        assert [t.trace_id for t in recent] == ["dt_000"]
    finally:
        sink.close()
