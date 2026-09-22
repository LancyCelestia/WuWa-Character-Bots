"""V2.1 S8 DatabaseBroker 离线测试（V21-DB-001）。

覆盖：query_id 白名单、注入样例全拒绝、参数 schema 类型校验、排序枚举、
行限 200 截断诚实标记、语句超时、只读连接、注册期模板静态校验、五个
预注册查询对真实 schema 的形状。库全部 tmp_path 临时建库。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.runtime.database_broker import (
    DatabaseBroker,
    QueryParamError,
    QuerySortError,
    QuerySpec,
    QueryTemplateError,
    QueryTimeoutError,
    UnknownQueryError,
    build_database_broker,
    build_default_registry,
)

# ---------------------------------------------------------------- 建库夹具


def _make_databases(tmp_path: Path) -> dict[str, str]:
    """按 docs/db-owners.md 在册库的真实列建临时库（列子集足够查询用）。"""
    send_queue = tmp_path / "send_queue.sqlite3"
    with sqlite3.connect(send_queue) as conn:
        conn.execute(
            "CREATE TABLE send_requests ("
            "dedupe_key TEXT PRIMARY KEY, request_id TEXT NOT NULL, "
            "state TEXT NOT NULL, retry_count INTEGER NOT NULL DEFAULT 0, "
            "session_id TEXT)"
        )
        conn.executemany(
            "INSERT INTO send_requests (dedupe_key, request_id, state, retry_count)"
            " VALUES (?, ?, ?, ?)",
            [
                ("k1", "r1", "queued", 0),
                ("k2", "r2", "queued", 1),
                ("k3", "r3", "sent", 0),
            ],
        )

    affinity = tmp_path / "affinity.sqlite3"
    with sqlite3.connect(affinity) as conn:
        conn.execute(
            "CREATE TABLE user_affinity (sender_id TEXT PRIMARY KEY, "
            "affinity REAL NOT NULL DEFAULT 0.1)"
        )
        conn.executemany(
            "INSERT INTO user_affinity (sender_id, affinity) VALUES (?, ?)",
            [
                ("u1", 80.0),
                ("u2", 30.0),
                ("u3", 5.0),
                ("u4", -50.0),
            ],
        )

    ledger = tmp_path / "ledger.sqlite3"
    with sqlite3.connect(ledger) as conn:
        conn.execute(
            "CREATE TABLE llm_usage_daily (day TEXT NOT NULL, dimension TEXT NOT NULL, "
            "dimension_key TEXT NOT NULL DEFAULT '', calls INTEGER NOT NULL DEFAULT 0, "
            "failed_calls INTEGER NOT NULL DEFAULT 0, total_tokens INTEGER NOT NULL DEFAULT 0, "
            "total_cost_milli INTEGER NOT NULL DEFAULT 0, unpriced_calls INTEGER NOT NULL DEFAULT 0, "
            "PRIMARY KEY (day, dimension, dimension_key))"
        )
        conn.executemany(
            "INSERT INTO llm_usage_daily (day, dimension, dimension_key, calls, "
            "failed_calls, total_tokens, total_cost_milli, unpriced_calls)"
            " VALUES (?, 'model', 'm', ?, ?, ?, ?, ?)",
            [
                ("2026-09-16", 10, 1, 1000, 500, 0),
                ("2026-09-17", 5, 0, 800, 300, 2),
            ],
        )

    audit = tmp_path / "audit.sqlite3"
    with sqlite3.connect(audit) as conn:
        conn.execute(
            "CREATE TABLE audit_records (audit_id TEXT PRIMARY KEY, "
            "request_id TEXT NOT NULL, session_id TEXT NOT NULL, "
            "capability_id TEXT NOT NULL, stage TEXT NOT NULL, event TEXT NOT NULL, "
            "severity TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        conn.executemany(
            "INSERT INTO audit_records VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (f"a{i}", f"req{i}", f"sess{i % 3}", f"cap{i % 2}", "run", "e", "info", f"2026-09-17T10:{i:02d}:00")
                for i in range(12)
            ],
        )

    subscriptions = tmp_path / "subscriptions.sqlite3"
    with sqlite3.connect(subscriptions) as conn:
        conn.execute(
            "CREATE TABLE subscription_targets (id TEXT PRIMARY KEY, "
            "platform TEXT NOT NULL, target_kind TEXT NOT NULL, target_key TEXT NOT NULL, "
            "enabled INTEGER NOT NULL DEFAULT 1, health_state TEXT NOT NULL DEFAULT 'healthy', "
            "failure_count INTEGER NOT NULL DEFAULT 0)"
        )
        conn.executemany(
            "INSERT INTO subscription_targets (id, platform, target_kind, target_key, "
            "enabled, health_state, failure_count) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("s1", "bilibili", "uploader", "u1", 1, "healthy", 0),
                ("s2", "bilibili", "uploader", "u2", 0, "degraded", 3),
                ("s3", "weibo", "creator", "w1", 1, "healthy", 0),
            ],
        )

    return {
        "send_queue": str(send_queue),
        "affinity": str(affinity),
        "ledger": str(ledger),
        "audit": str(audit),
        "subscriptions": str(subscriptions),
    }


def _make_broker(tmp_path: Path, **overrides) -> DatabaseBroker:
    return DatabaseBroker(build_default_registry(**overrides), _make_databases(tmp_path))


# ---------------------------------------------------------------- 白名单与注入


def test_unregistered_query_id_rejected(tmp_path) -> None:
    broker = _make_broker(tmp_path)
    assert set(broker.query_ids()) == {
        "queue.depth",
        "affinity.distribution",
        "ledger.daily",
        "audit.recent",
        "subscriptions.status",
    }
    with pytest.raises(UnknownQueryError):
        broker.execute("send_requests; DROP TABLE send_requests", {})


def test_unknown_param_rejected(tmp_path) -> None:
    broker = _make_broker(tmp_path)
    with pytest.raises(QueryParamError):
        broker.execute(
            "queue.depth", {"state": "queued' OR '1'='1"}
        )


def test_missing_required_param_rejected(tmp_path) -> None:
    broker = _make_broker(tmp_path)
    with pytest.raises(QueryParamError):
        broker.execute("ledger.daily", {})


def test_injection_samples_rejected(tmp_path) -> None:
    """注入样例矩阵：类型不符全部拒绝；字符串参数只能作字面值。"""
    broker = _make_broker(tmp_path)
    # 整型参数喂 SQL 片段 → 类型拒绝。
    with pytest.raises(QueryParamError):
        broker.execute("audit.recent", {"limit": "5; DROP TABLE audit_records", "order_by": "created_at"})
    with pytest.raises(QueryParamError):
        broker.execute("audit.recent", {"limit": "1 OR 1=1", "order_by": "created_at"})
    # bool 伪装 int → 拒绝。
    with pytest.raises(QueryParamError):
        broker.execute("audit.recent", {"limit": True, "order_by": "created_at"})
    # 排序列注入 → 枚举拒绝。
    with pytest.raises(QuerySortError):
        broker.execute(
            "audit.recent",
            {"limit": 5, "order_by": "created_at; DROP TABLE audit_records"},
        )
    with pytest.raises(QuerySortError):
        broker.execute(
            "audit.recent",
            {"limit": 5, "order_by": "(SELECT 1)"},
        )
    with pytest.raises(QuerySortError):
        broker.execute(
            "audit.recent",
            {"limit": 5, "order_by": "secret_column"},
        )


def test_string_param_is_bound_literal_not_sql(tmp_path) -> None:
    """字符串参数里的 SQL 元字符作为字面值绑定，语句不逃逸、表不被改。"""
    broker = _make_broker(tmp_path)
    result = broker.execute(
        "ledger.daily", {"min_day": "9999-01-01' OR '1'='1"}
    )
    # 参数化绑定：整串作为字面值参与比较（永远大于任何真实日期），无匹配行；
    # 引号未逃逸成 SQL 结构（OR '1'='1 没有放行全部行）。
    assert result.row_count == 0
    # 目标表仍在（注入未发生）。
    with sqlite3.connect(broker._database_paths["ledger"]) as conn:
        count = conn.execute("SELECT COUNT(*) FROM llm_usage_daily").fetchone()[0]
    assert count == 2


# ---------------------------------------------------------------- 行限与超时


def test_row_limit_200_truncation_is_honest(tmp_path) -> None:
    broker = _make_broker(tmp_path)
    with sqlite3.connect(broker._database_paths["audit"]) as conn:
        for i in range(12, 260):
            conn.execute(
                "INSERT INTO audit_records VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (f"a{i}", f"req{i}", "s", "cap", "run", "e", "info", f"2026-09-17T11:{i:02d}:00"),
            )
    result = broker.execute(
        "audit.recent", {"limit": 1000, "order_by": "created_at"}
    )
    # 参数 limit=1000 也压不破 200 行硬限额；截断必须如实标记。
    assert result.row_count == 200
    assert result.truncated is True


def test_statement_timeout_aborts(tmp_path) -> None:
    registry = build_default_registry()
    heavy_path = tmp_path / "heavy.sqlite3"
    with sqlite3.connect(heavy_path) as conn:
        conn.execute("CREATE TABLE placeholder(a INTEGER)")
    db_path = str(heavy_path)
    registry["heavy.burn"] = QuerySpec(
        query_id="heavy.burn",
        sql=(
            "WITH RECURSIVE cnt(x) AS ("
            "SELECT 1 UNION ALL SELECT x + 1 FROM cnt WHERE x < 500000000"
            ") SELECT COUNT(*) AS burned FROM cnt"
        ),
        db="heavy",
        timeout_seconds=0.2,
        description="CPU 燃烧弹（仅测试超时用）",
    )
    broker = DatabaseBroker(
        registry, {"heavy": db_path, **_make_databases(tmp_path)}
    )
    with pytest.raises(QueryTimeoutError):
        broker.execute("heavy.burn", {})


# ---------------------------------------------------------------- 只读与模板校验


def test_connection_is_readonly(tmp_path) -> None:
    broker = _make_broker(tmp_path)
    connection = broker._open_readonly("send_queue")
    try:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute(
                "CREATE TABLE evil(a TEXT)"
            )
    finally:
        connection.close()


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE send_requests",
        "INSERT INTO send_requests VALUES (1)",
        "UPDATE send_requests SET state = 'x'",
        "DELETE FROM send_requests",
        "SELECT 1; DROP TABLE send_requests",
        "SELECT 1 -- hidden",
        "ATTACH DATABASE 'x' AS y",
        "PRAGMA journal_mode=off",
        "SELECT * FROM send_requests WHERE state = 'x' OR 1=1; DELETE FROM send_requests",
    ],
)
def test_template_static_validation_rejects(tmp_path, sql) -> None:
    databases = _make_databases(tmp_path)
    with pytest.raises(QueryTemplateError):
        DatabaseBroker(
            {
                "evil.q": QuerySpec(
                    query_id="evil.q", sql=sql, db="send_queue"
                )
            },
            databases,
        )


def test_template_placeholder_must_be_registered_sort_enum(tmp_path) -> None:
    databases = _make_databases(tmp_path)
    with pytest.raises(QueryTemplateError):
        DatabaseBroker(
            {
                "evil.q": QuerySpec(
                    query_id="evil.q",
                    sql="SELECT * FROM send_requests ORDER BY {col}",
                    db="send_queue",
                    params={"col": "str"},
                )
            },
            databases,
        )


def test_spec_db_must_be_registered() -> None:
    with pytest.raises(QueryTemplateError):
        DatabaseBroker(
            {"q": QuerySpec(query_id="q", sql="SELECT 1", db="nowhere")},
            {"known": "x.sqlite3"},
        )


# ---------------------------------------------------------------- 五个真实查询


def test_all_five_registered_queries_return_sane_shapes(tmp_path) -> None:
    broker = _make_broker(tmp_path)

    queue = broker.execute("queue.depth", {})
    states = {row["state"]: row["requests"] for row in queue.rows}
    assert states == {"queued": 2, "sent": 1}

    affinity = broker.execute("affinity.distribution", {})
    buckets = {row["bucket"]: row["senders"] for row in affinity.rows}
    assert buckets["devoted"] == 1
    assert buckets["hostile"] == 1
    assert buckets["neutral"] == 1
    assert buckets["close"] == 1

    ledger = broker.execute("ledger.daily", {"min_day": "2026-09-17"})
    assert ledger.row_count == 1
    assert ledger.rows[0]["calls"] == 5
    assert ledger.rows[0]["total_tokens"] == 800

    audit = broker.execute(
        "audit.recent", {"limit": 5, "order_by": "created_at"}
    )
    assert audit.row_count == 5
    created = [row["created_at"] for row in audit.rows]
    assert created == sorted(created, reverse=True)
    # 排序枚举切换列也可执行。
    by_cap = broker.execute(
        "audit.recent", {"limit": 3, "order_by": "capability_id"}
    )
    assert by_cap.row_count == 3

    subs = broker.execute("subscriptions.status", {})
    platforms = {row["platform"]: row for row in subs.rows}
    assert platforms["bilibili"]["targets"] == 2
    assert platforms["bilibili"]["unhealthy"] == 1
    assert platforms["weibo"]["enabled_targets"] == 1


def test_elapsed_ms_and_columns_reported(tmp_path) -> None:
    broker = _make_broker(tmp_path)
    result = broker.execute("queue.depth", {})
    assert result.columns[0] == "state"
    assert result.elapsed_ms >= 0.0
    assert result.truncated is False


def test_build_database_broker_from_config(tmp_path) -> None:
    class _Cfg:
        bot_send_queue_db_path = str(tmp_path / "q.sqlite3")
        bot_affinity_db_path = str(tmp_path / "a.sqlite3")
        bot_audit_db_path = str(tmp_path / "au.sqlite3")
        bot_subscribe_db_path = str(tmp_path / "s.sqlite3")

    broker = build_database_broker(_Cfg())
    assert set(broker.query_ids()) == set(build_default_registry())
