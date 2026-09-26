"""账本窗口查询索引与范围比较（P3-9，2026-09-15）。

锁定：①aggregate_channel_usage 的日期过滤用 completed_at 范围比较
（``completed_at >= start_day AND completed_at < 结束日次日``，ISO 文本
字典序即时序），与旧 ``substr(completed_at,1,10) BETWEEN`` 实现在同一
数据集（含跨日边界行、无毫秒尾缀行）上结果完全一致；②EXPLAIN QUERY
PLAN 走 ``idx_llm_call_completed`` 索引、无裸全表扫；③``_SCHEMA_SQL``
幂等（重复执行/重复开库不炸、索引不重复建）；④升级前旧库（无该索引）
只读查询不炸、结果照旧。全部离线（临时 SQLite，实写实读）。
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.ledger import (
    _CHANNEL_AGGREGATE_SINCE_SQL,
    _CHANNEL_AGGREGATE_SQL,
    _SCHEMA_SQL,
    LedgerService,
    aggregate_channel_usage,
    build_call_draft,
)

# 旧 substr 实现的参照 SQL（语义等价性的对照基准，仅测试内使用）。
_OLD_SUBSTR_BASE = (
    "SELECT actual_model, model_id, COUNT(*) AS calls, "
    "SUM(COALESCE(total_tokens, 0)) AS total_tokens "
    "FROM llm_call_records "
    "WHERE substr(completed_at, 1, 10) BETWEEN ? AND ? "
)
_OLD_SUBSTR_SINCE = _OLD_SUBSTR_BASE + "AND completed_at >= ? "
_OLD_SUBSTR_TAIL = "GROUP BY actual_model, model_id"


def _write_call(db_path: Path, **overrides: object) -> None:
    """桩写线程（不起后台线程）：submit + flush 全同步，实写实读。"""
    usage: dict[str, object] = {
        key: overrides.pop(key)
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        if key in overrides
    }
    service = LedgerService(
        str(db_path), writer_thread=threading.Thread(target=lambda: None)
    )
    try:
        draft = build_call_draft(
            request_id=str(overrides.pop("request_id", "r1")),
            session_id="sess",
            capability="chat",
            started_at="2026-09-13T12:00:00.000+08:00",
            completed_at=str(
                overrides.pop("completed_at", "2026-09-13T12:00:01.000+08:00")
            ),
            status="success",
            usage=usage,
            **overrides,  # type: ignore[arg-type]
        )
        service.submit(draft)
        assert service.flush() == 1
    finally:
        service.close()


# 跨日边界数据集：每个 actual_model 唯一、total_tokens 唯一，
# 任何一行被多选/漏选都会反映为结果集差异。
# completed_at 形态对齐生产写入：datetime.now(zone).isoformat(
# timespec="milliseconds") → 带时区后缀；no_milli 行模拟微秒为 0 时
# isoformat 省略毫秒尾缀的形态。
_BOUNDARY_ROWS: list[tuple[str, str, int]] = [
    ("m-prev-last-ms", "2026-09-12T23:59:59.999+08:00", 1001),  # 开始日前一天
    ("m-first-ms", "2026-09-13T00:00:00.000+08:00", 1002),  # 开始日首个毫秒
    ("m-no-milli", "2026-09-13T08:30:00+08:00", 1003),  # 无毫秒尾缀
    ("m-mid-day", "2026-09-13T12:00:00.000+08:00", 1004),
    ("m-last-ms", "2026-09-13T23:59:59.999+08:00", 1005),  # 结束日最后毫秒
    ("m-after-first-ms", "2026-09-14T00:00:00.000+08:00", 1006),  # 结束日次日
]


def _write_boundary_db(db_path: Path) -> None:
    for i, (model, completed_at, tokens) in enumerate(_BOUNDARY_ROWS):
        _write_call(
            db_path,
            request_id=f"r{i}",
            model_id="ch",
            actual_model=model,
            completed_at=completed_at,
            total_tokens=tokens,
        )


def _observed(db_path: Path, **kwargs: str) -> dict[tuple[str, str], tuple[int, int]]:
    raw = aggregate_channel_usage(str(db_path), **kwargs)  # type: ignore[arg-type]
    return {
        key: (stats["calls"], stats["total_tokens"]) for key, stats in raw.items()
    }


def _old_substr_oracle(
    db_path: Path, params: list[str], *, since: bool = False
) -> dict[tuple[str, str], tuple[int, int]]:
    sql = (_OLD_SUBSTR_SINCE if since else _OLD_SUBSTR_BASE) + _OLD_SUBSTR_TAIL
    connection = sqlite3.connect(str(db_path))
    try:
        rows = connection.execute(sql, params).fetchall()
    finally:
        connection.close()
    return {(str(r[0]), str(r[1])): (int(r[2]), int(r[3])) for r in rows}


# ==================== ① 范围比较与旧 substr 语义等价 ====================


def test_range_matches_old_substr_single_day(tmp_path: Path) -> None:
    db = tmp_path / "billing.sqlite3"
    _write_boundary_db(db)

    observed = _observed(db, start_day="2026-09-13", end_day="2026-09-13")

    expected = {
        (("m-first-ms"), "ch"): (1, 1002),
        (("m-no-milli"), "ch"): (1, 1003),
        (("m-mid-day"), "ch"): (1, 1004),
        (("m-last-ms"), "ch"): (1, 1005),
    }
    assert observed == expected
    # 与旧 substr 实现逐组对照（同数据集同结果）。
    assert observed == _old_substr_oracle(
        db, ["2026-09-13", "2026-09-13"]
    )


def test_range_matches_old_substr_multi_day_window(tmp_path: Path) -> None:
    db = tmp_path / "billing.sqlite3"
    _write_boundary_db(db)

    observed = _observed(db, start_day="2026-09-12", end_day="2026-09-13")

    expected = {
        (("m-prev-last-ms"), "ch"): (1, 1001),
        (("m-first-ms"), "ch"): (1, 1002),
        (("m-no-milli"), "ch"): (1, 1003),
        (("m-mid-day"), "ch"): (1, 1004),
        (("m-last-ms"), "ch"): (1, 1005),
    }
    assert observed == expected
    assert observed == _old_substr_oracle(db, ["2026-09-12", "2026-09-13"])


def test_range_matches_old_substr_with_since_iso(tmp_path: Path) -> None:
    db = tmp_path / "billing.sqlite3"
    _write_boundary_db(db)

    observed = _observed(
        db,
        start_day="2026-09-13",
        end_day="2026-09-13",
        since_iso="2026-09-13T12:00:00.000+08:00",
    )

    expected = {
        (("m-mid-day"), "ch"): (1, 1004),
        (("m-last-ms"), "ch"): (1, 1005),
    }
    assert observed == expected
    assert observed == _old_substr_oracle(
        db,
        ["2026-09-13", "2026-09-13", "2026-09-13T12:00:00.000+08:00"],
        since=True,
    )


# ==================== ② EXPLAIN QUERY PLAN 走索引 ====================


def test_query_plan_uses_completed_at_index(tmp_path: Path) -> None:
    db = tmp_path / "billing.sqlite3"
    _write_call(
        db,
        request_id="r1",
        model_id="ch",
        actual_model="m",
        completed_at="2026-09-13T12:00:00.000+08:00",
        total_tokens=10,
    )
    connection = sqlite3.connect(str(db))
    try:
        cases: list[tuple[str, list[str]]] = [
            (_CHANNEL_AGGREGATE_SQL, ["2026-09-13", "2026-09-14"]),
            (
                _CHANNEL_AGGREGATE_SINCE_SQL,
                ["2026-09-13", "2026-09-14", "2026-09-13T00:00:00.000+08:00"],
            ),
        ]
        for sql, params in cases:
            plan_rows = connection.execute(
                "EXPLAIN QUERY PLAN " + sql, params
            ).fetchall()
            detail = " | ".join(str(row[-1]) for row in plan_rows)
            assert (
                "SEARCH llm_call_records USING INDEX idx_llm_call_completed"
                in detail
            ), detail
            # 无裸全表扫（不带 USING INDEX 的 SCAN llm_call_records）。
            assert "SCAN llm_call_records" not in detail, detail
    finally:
        connection.close()


# ==================== ③ schema/索引幂等 ====================


def test_schema_and_index_idempotent_on_reopen(tmp_path: Path) -> None:
    db = tmp_path / "billing.sqlite3"
    for _ in range(2):
        connection = sqlite3.connect(str(db))
        try:
            connection.executescript(_SCHEMA_SQL)
            connection.commit()
        finally:
            connection.close()

    # 经服务正常开库写读一轮：DDL 幂等，重复开库不炸。
    _write_call(
        db,
        request_id="r1",
        model_id="ch",
        actual_model="m",
        completed_at="2026-09-13T12:00:01.000+08:00",
        total_tokens=10,
    )

    connection = sqlite3.connect(str(db))
    try:
        indexes = [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND tbl_name='llm_call_records'"
            )
        ]
    finally:
        connection.close()
    assert indexes.count("idx_llm_call_completed") == 1

    got = aggregate_channel_usage(str(db), start_day="2026-09-13", end_day="2026-09-13")
    assert got[("m", "ch")]["calls"] == 1
    assert got[("m", "ch")]["total_tokens"] == 10


# ==================== ④ 升级前旧库（无新索引）查询不炸 ====================


def test_legacy_db_without_completed_at_index_still_queries(tmp_path: Path) -> None:
    db = tmp_path / "billing.sqlite3"
    connection = sqlite3.connect(str(db))
    try:
        connection.executescript(_SCHEMA_SQL)
        connection.execute("DROP INDEX IF EXISTS idx_llm_call_completed")
        connection.execute(
            "INSERT INTO llm_call_records ("
            "request_id, started_at, completed_at, model_id, actual_model, "
            "status, created_at, total_tokens"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "r1",
                "2026-09-13T12:00:00.000+08:00",
                "2026-09-13T12:00:01.000+08:00",
                "ch",
                "m",
                "success",
                "2026-09-13T12:00:01.000+08:00",
                7,
            ),
        )
        connection.commit()
        remaining = [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND tbl_name='llm_call_records'"
            )
        ]
        assert "idx_llm_call_completed" not in remaining
    finally:
        connection.close()

    got = aggregate_channel_usage(str(db), start_day="2026-09-13", end_day="2026-09-13")
    assert got[("m", "ch")]["total_tokens"] == 7
