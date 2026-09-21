"""只读 usage 契约：真实 ledger DDL、隔离临时库，不导入 Bot/Runtime。"""

from __future__ import annotations

import ast
import importlib.util
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "plugins/bot_unified_runtime/control_plane/metrics.py"


@pytest.fixture(scope="module")
def metrics():
    spec = importlib.util.spec_from_file_location("isolated_ledger_metrics", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def database(tmp_path):
    # 直接消费现行 DDL，schema 演进会影响本测试，不维护另一个假 schema。
    tree = ast.parse(
        (ROOT / "plugins/bot_unified_runtime/domains/chat_reply/llm_engine/ledger.py").read_text(encoding="utf-8")
    )
    schema = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_SCHEMA_SQL"
            for target in node.targets
        )
    )
    path = tmp_path / "账本 #%3F只读.sqlite3"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(schema)
    return path


def insert(path, **changes):
    row = {
        "request_id": "request",
        "started_at": "2026-09-15T00:00:00Z",
        "completed_at": "2026-09-15T00:00:01Z",
        "created_at": "2026-09-15T00:00:01Z",
        "model_id": "channel-not-model",
        "actual_model": "model-a",
        "provider_id": "provider-a",
        "session_id": "私聊:用户123:原文不能输出",
        "status": "success",
        "prompt_tokens": None,
        "completion_tokens": None,
        "cache_read_tokens": None,
        "cache_creation_tokens": None,
        "attempts_json": '["failover:deadline", "secret-provider:winner"]',
        "attempts_count": 987,
        "error_summary": "sk-secret C:/private/ledger.sqlite SELECT * FROM secrets",
    }
    row.update(changes)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            "INSERT INTO llm_call_records ("
            + ",".join(row)
            + ") VALUES ("
            + ",".join("?" for _ in row)
            + ")",
            tuple(row.values()),
        )


@pytest.fixture
def seeded(database):
    insert(
        database,
        started_at="2026-09-15T08:00:00+08:00",
        prompt_tokens=10,
        completion_tokens=4,
        cache_read_tokens=2,
    )
    insert(database, status="deadline", started_at="2026-09-14T19:30:00-05:00")
    insert(
        database,
        actual_model="model-b",
        provider_id="provider-b",
        session_id="group:987654321",
        status="provider_failed",
        started_at="2026-09-15T01:10:00Z",
        prompt_tokens=20,
        completion_tokens=0,
        cache_read_tokens=0,
        cache_creation_tokens=5,
    )
    insert(
        database,
        actual_model="model-b",
        session_id="group:987654321",
        started_at="2026-09-16T00:10:00+08:00",
        prompt_tokens=0,
        completion_tokens=6,
        cache_read_tokens=1,
        cache_creation_tokens=0,
    )
    return database


def value(total, known, unknown, quality):
    return {
        "value": total,
        "known_rows": known,
        "unknown_rows": unknown,
        "quality": quality,
    }


def test_overview_matches_official_schema_and_real_statuses(metrics, seeded):
    result = metrics.LedgerMetricsService(seeded).overview()
    assert result["status"] == "ok"
    data = result["data"]
    assert (
        data["recorded_calls"],
        data["successful_calls"],
        data["failed_calls"],
        data["unknown_status_calls"],
    ) == (4, 2, 2, 0)
    assert data["tokens"] == {
        "prompt": value(30, 3, 1, "partial"),
        "completion": value(10, 3, 1, "partial"),
        "cache_read": value(3, 3, 1, "partial"),
        "cache_creation": value(5, 2, 2, "partial"),
    }
    for name in ("attempt_total", "failover_calls"):
        assert data[name]["value"] is None
        assert data[name]["quality"] == "unknown"


@pytest.mark.parametrize("method", ["overview", "models", "sessions", "trends"])
def test_missing_source_never_creates_database(metrics, tmp_path, method):
    path = tmp_path / "missing-parent" / "secret.sqlite3"
    result = getattr(metrics.LedgerMetricsService(path), method)()
    assert result["status"] == "source_unavailable"
    assert result["data"] is None
    assert not path.parent.exists()
    assert str(path) not in json.dumps(result)


@pytest.mark.parametrize(
    "kind", ["empty_file", "missing_table", "incomplete", "view", "corrupt"]
)
@pytest.mark.parametrize("method", ["overview", "models", "sessions", "trends"])
def test_bad_sources_are_explicit_and_sanitized(metrics, tmp_path, kind, method):
    path = tmp_path / "private.sqlite3"
    if kind == "corrupt":
        path.write_bytes(b"not SQLite sk-secret")
    else:
        with closing(sqlite3.connect(path)) as connection, connection:
            if kind == "missing_table":
                connection.execute("CREATE TABLE something_else (id INTEGER)")
            elif kind == "incomplete":
                connection.execute("CREATE TABLE llm_call_records (status TEXT)")
            elif kind == "view":
                connection.execute(
                    "CREATE VIEW llm_call_records AS SELECT 'success' AS status"
                )
    before = path.read_bytes()
    result = getattr(metrics.LedgerMetricsService(path), method)()
    assert result["status"] == "source_unavailable"
    assert result["data"] is None
    assert path.read_bytes() == before
    assert not any(
        term in json.dumps(result)
        for term in (str(path), "sk-secret", "SELECT", "sqlite3")
    )


def test_empty_and_null_zero_have_distinct_quality(metrics, database):
    service = metrics.LedgerMetricsService(database)
    empty = service.overview()["data"]
    assert empty["recorded_calls"] == 0
    assert empty["tokens"]["prompt"] == value(None, 0, 0, "unknown")
    assert service.models()["data"]["models"] == []
    assert service.sessions()["data"]["sessions"] == []
    assert service.trends()["data"]["items"] == []
    insert(database)
    assert service.overview()["data"]["tokens"]["prompt"] == value(
        None, 0, 1, "unknown"
    )
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("UPDATE llm_call_records SET prompt_tokens = 0")
    assert service.overview()["data"]["tokens"]["prompt"] == value(0, 1, 0, "complete")


def test_unknown_status_is_not_falsely_failure(metrics, database):
    for status in ("", "error", "future_status", "SUCCESS"):
        insert(database, status=status)
    data = metrics.LedgerMetricsService(database).overview()["data"]
    assert (
        data["recorded_calls"],
        data["successful_calls"],
        data["failed_calls"],
        data["unknown_status_calls"],
    ) == (4, 0, 0, 4)


def test_model_provider_ranking_and_limit_do_not_truncate_aggregates(metrics, seeded):
    service = metrics.LedgerMetricsService(seeded)
    result = service.models(limit=1)["data"]
    assert result["recorded_calls"] == 4
    assert len(result["models"]) == len(result["providers"]) == 1
    assert result["models"][0]["model"] == "model-a"
    assert result["models"][0]["recorded_calls"] == 2
    assert result["providers"][0]["provider"] == "provider-a"
    assert result["providers"][0]["recorded_calls"] == 3
    assert result["providers"][0]["tokens"]["prompt"] == value(10, 2, 1, "partial")
    assert service.overview(limit=1)["data"]["recorded_calls"] == 4
    insert(seeded, actual_model="", provider_id="")
    full = service.models()["data"]
    assert any(row["model"] is None for row in full["models"])
    assert "channel-not-model" not in json.dumps(full)


def test_sessions_are_keyed_hashes_stable_in_process_without_raw_identifiers(
    metrics, seeded
):
    first = metrics.LedgerMetricsService(seeded).sessions()["data"]["sessions"]
    second = metrics.LedgerMetricsService(seeded).sessions()["data"]["sessions"]
    assert first == second
    assert len(first) == 2
    assert len({row["session"] for row in first}) == 2
    assert all(row["session"].startswith("session_") for row in first)
    assert all(row["recorded_calls"] == 2 for row in first)
    text = json.dumps(first, ensure_ascii=False)
    assert "用户123" not in text and "987654321" not in text
    assert "私聊" not in text and "error_summary" not in text


@pytest.mark.parametrize("method", ["overview", "models", "sessions", "trends"])
def test_no_sensitive_columns_are_even_read(metrics, seeded, monkeypatch, method):
    original = sqlite3.connect
    forbidden = {"error_summary", "attempts_json", "attempts_count", "request_id"}

    def connect(*args, **kwargs):
        connection = original(*args, **kwargs)
        connection.set_authorizer(
            lambda action, table, column, *_: (
                sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_READ and column in forbidden
                else sqlite3.SQLITE_OK
            )
        )
        return connection

    monkeypatch.setattr(metrics.sqlite3, "connect", connect)
    result = getattr(metrics.LedgerMetricsService(seeded), method)()
    assert result["status"] == "ok"
    text = json.dumps(result, ensure_ascii=False)
    assert not any(
        secret in text for secret in ("sk-secret", "SELECT", "C:/private", "用户123")
    )


def test_unsafe_model_and_provider_identifiers_do_not_leak(metrics, database):
    insert(database, actual_model="C:/secret/model", provider_id="sk-private")
    data = metrics.LedgerMetricsService(database).models()["data"]
    text = json.dumps(data)
    assert "C:/secret" not in text and "sk-private" not in text
    assert data["models"][0]["model"].startswith("model_")
    assert data["providers"][0]["provider"].startswith("provider_")


def test_utc_hour_day_buckets_and_invalid_timestamps(metrics, seeded):
    service = metrics.LedgerMetricsService(seeded)
    data = service.trends(bucket="hour")["data"]
    assert data["timezone"] == "UTC"
    assert {row["bucket_start"]: row["recorded_calls"] for row in data["items"]} == {
        "2026-09-15T00:00:00Z": 2,
        "2026-09-15T01:00:00Z": 1,
        "2026-09-15T16:00:00Z": 1,
    }
    day = service.trends(bucket="day")["data"]["items"]
    assert len(day) == 1
    assert day[0]["bucket_start"] == "2026-09-15T00:00:00Z"
    assert day[0]["recorded_calls"] == 4
    for stamp in ("invalid-secret", "2026-09-15T00:00:00", "2026-99-99T00:00:00Z", ""):
        insert(seeded, started_at=stamp)
    data = service.trends(limit=1)["data"]
    assert data["recorded_calls"] == 8
    assert data["unknown_timestamp_calls"] == 4
    assert len(data["items"]) == 1
    assert "invalid-secret" not in json.dumps(data)


@pytest.mark.parametrize(
    "limit", [0, -1, 101, True, 1.5, "1; DROP TABLE llm_call_records", None]
)
@pytest.mark.parametrize("method", ["overview", "models", "sessions", "trends"])
def test_invalid_limits_rejected_without_opening_database(
    metrics, monkeypatch, limit, method
):
    def no_connect(*args, **kwargs):
        pytest.fail("invalid request opened database")

    monkeypatch.setattr(metrics.sqlite3, "connect", no_connect)
    result = getattr(metrics.LedgerMetricsService("unused"), method)(limit=limit)
    assert result == {
        "status": "invalid_request",
        "reason": "invalid_limit",
        "data": None,
    }


@pytest.mark.parametrize(
    "bucket", ["week", "HOUR", "hour'); DROP TABLE llm_call_records; --", None, []]
)
def test_bucket_is_a_closed_enum(metrics, database, bucket):
    result = metrics.LedgerMetricsService(database).trends(bucket=bucket)
    assert result == {
        "status": "invalid_request",
        "reason": "invalid_bucket",
        "data": None,
    }


def test_read_only_uri_query_only_timeout_progress_and_close(
    metrics, seeded, monkeypatch
):
    original = sqlite3.connect
    seen = []

    class CheckedConnection(sqlite3.Connection):
        def set_progress_handler(self, callback, n):
            seen.append((callable(callback), n))
            return super().set_progress_handler(callback, n)

        def close(self):
            assert self.execute("PRAGMA query_only").fetchone()[0] == 1
            with pytest.raises(sqlite3.OperationalError):
                self.execute("CREATE TABLE forbidden_write (id INTEGER)")
            seen.append("closed")
            super().close()

    def connect(database_uri, **kwargs):
        assert database_uri.startswith("file:") and database_uri.endswith("?mode=ro")
        assert "%253F" in database_uri and "%23" in database_uri
        assert kwargs["uri"] is True and 0 < kwargs["timeout"] <= 1
        return original(database_uri, factory=CheckedConnection, **kwargs)

    monkeypatch.setattr(metrics.sqlite3, "connect", connect)
    before = seeded.read_bytes()
    assert metrics.LedgerMetricsService(seeded).overview()["status"] == "ok"
    assert any(isinstance(entry, tuple) and entry[0] and entry[1] > 0 for entry in seen)
    assert seen[-1] == "closed"
    assert seeded.read_bytes() == before


def test_query_budget_interrupts_and_never_returns_partial_results(
    metrics, database, monkeypatch
):
    insert(database)
    with closing(sqlite3.connect(database)) as connection, connection:
        for _ in range(11):
            connection.execute(
                "INSERT INTO llm_call_records (request_id, started_at, completed_at, model_id, status, created_at) SELECT request_id, started_at, completed_at, model_id, status, created_at FROM llm_call_records"
            )
    monkeypatch.setattr(metrics, "_QUERY_TIMEOUT_SECONDS", 0)
    result = metrics.LedgerMetricsService(database).overview()
    assert result == {
        "status": "source_unavailable",
        "reason": "query_budget_exceeded",
        "data": None,
    }


def test_lock_timeout_is_bounded_and_error_is_private(metrics, seeded):
    with closing(sqlite3.connect(seeded)) as lock, lock:
        lock.execute("BEGIN EXCLUSIVE")
        started = time.monotonic()
        result = metrics.LedgerMetricsService(seeded).overview()
        elapsed = time.monotonic() - started
    assert result["status"] == "source_unavailable"
    assert result["data"] is None
    assert elapsed < 2
    assert str(seeded) not in json.dumps(result)


def test_bad_token_types_are_unknown_not_coerced_to_zero(metrics, database):
    for tokens in ("private-string", -10, 1.5, None):
        insert(database, prompt_tokens=tokens)
    assert metrics.LedgerMetricsService(database).overview()["data"]["tokens"][
        "prompt"
    ] == value(None, 0, 4, "unknown")


def test_large_ledger_is_aggregated_with_bounded_output(metrics, database):
    insert(database, prompt_tokens=2)
    with closing(sqlite3.connect(database)) as connection, connection:
        for _ in range(13):
            connection.execute(
                "INSERT INTO llm_call_records (request_id, started_at, completed_at, model_id, actual_model, provider_id, session_id, status, created_at, prompt_tokens) SELECT request_id, started_at, completed_at, model_id, actual_model, provider_id, session_id, status, created_at, prompt_tokens FROM llm_call_records"
            )
    started = time.monotonic()
    data = metrics.LedgerMetricsService(database).models(limit=1)["data"]
    assert data["recorded_calls"] == 8192
    assert data["models"][0]["tokens"]["prompt"] == value(16384, 8192, 0, "complete")
    assert time.monotonic() - started < 3


@pytest.mark.parametrize(
    "column",
    [
        "status",
        "started_at",
        "actual_model",
        "provider_id",
        "session_id",
        "prompt_tokens",
        "completion_tokens",
        "cache_read_tokens",
        "cache_creation_tokens",
    ],
)
def test_each_required_column_is_checked_before_statistics(metrics, tmp_path, column):
    # 无索引的最小完整投影，使测试不依赖 ALTER TABLE DROP COLUMN 的 SQLite 版本。
    names = {
        "status",
        "started_at",
        "actual_model",
        "provider_id",
        "session_id",
        "prompt_tokens",
        "completion_tokens",
        "cache_read_tokens",
        "cache_creation_tokens",
    }
    path = tmp_path / "incomplete.sqlite3"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            "CREATE TABLE llm_call_records ("
            + ", ".join(sorted(names - {column}))
            + ")"
        )
    for method in ("overview", "models", "sessions", "trends"):
        result = getattr(metrics.LedgerMetricsService(path), method)()
        assert result == {
            "status": "source_unavailable",
            "reason": "incomplete_schema",
            "data": None,
        }


def test_optional_attempt_columns_can_be_absent_and_remain_unknown(metrics, tmp_path):
    path = tmp_path / "minimal.sqlite3"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("""CREATE TABLE llm_call_records (
            status TEXT, started_at TEXT, actual_model TEXT, provider_id TEXT, session_id TEXT,
            prompt_tokens INTEGER, completion_tokens INTEGER, cache_read_tokens INTEGER,
            cache_creation_tokens INTEGER)""")
        connection.execute("""INSERT INTO llm_call_records VALUES
            ('success', '2026-09-15T00:00:00Z', 'model', 'provider', 'private', 1, 2, 3, 4)""")
    service = metrics.LedgerMetricsService(path)
    for method in ("overview", "models", "sessions", "trends"):
        result = getattr(service, method)()
        assert result["status"] == "ok"
        data = result["data"]
        for name, total in (
            ("prompt", 1),
            ("completion", 2),
            ("cache_read", 3),
            ("cache_creation", 4),
        ):
            assert data["tokens"][name] == value(total, 1, 0, "complete")
        assert data["attempt_total"]["value"] is None
        assert data["failover_calls"]["quality"] == "unknown"


def test_default_limits_bound_each_ranking_not_record_count(metrics, database):
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.executemany(
            """INSERT INTO llm_call_records
            (request_id, started_at, completed_at, model_id, actual_model, provider_id,
             session_id, status, created_at) VALUES (?, '', '', '', ?, ?, ?, 'success', '')""",
            [
                (str(i), f"model-{i:03d}", f"provider-{i:03d}", f"session-{i:03d}")
                for i in range(105)
            ],
        )
    service = metrics.LedgerMetricsService(database)
    data = service.models()["data"]
    assert data["recorded_calls"] == 105
    assert len(data["models"]) == len(data["providers"]) == 100
    assert data["models"][0]["model"] == "model-000"
    assert len(service.sessions()["data"]["sessions"]) == 100


def test_sqlite_instruction_budget_interrupts_before_time_limit(
    metrics, database, monkeypatch
):
    insert(database)
    with closing(sqlite3.connect(database)) as connection, connection:
        for _ in range(10):
            connection.execute(
                "INSERT INTO llm_call_records (request_id, started_at, completed_at, model_id, status, created_at) SELECT request_id, started_at, completed_at, model_id, status, created_at FROM llm_call_records"
            )
    monkeypatch.setattr(metrics, "_QUERY_TIMEOUT_SECONDS", 10)
    monkeypatch.setattr(metrics, "_MAX_PROGRESS_CALLBACKS", 1)
    result = metrics.LedgerMetricsService(database).models()
    assert result == {
        "status": "source_unavailable",
        "reason": "query_budget_exceeded",
        "data": None,
    }


def test_wal_concurrent_writer_does_not_mix_snapshot_counts(
    metrics, seeded, monkeypatch
):
    original = sqlite3.connect
    with closing(original(seeded)) as connection:
        assert connection.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
    wrote = False

    class SnapshotConnection(sqlite3.Connection):
        def execute(self, statement, *args):
            nonlocal wrote
            if statement == metrics._GROUP_SQL["models"] and not wrote:
                wrote = True
                with closing(original(seeded)) as writer, writer:
                    writer.execute("""INSERT INTO llm_call_records
                        (request_id, started_at, completed_at, model_id, actual_model, status, created_at)
                        VALUES ('concurrent', '2026-09-15T01:00:00Z', '', '', 'new-model', 'success', '')""")
            return super().execute(statement, *args)

    def connect(*args, **kwargs):
        return original(*args, factory=SnapshotConnection, **kwargs)

    monkeypatch.setattr(metrics.sqlite3, "connect", connect)
    service = metrics.LedgerMetricsService(seeded)
    data = service.models()["data"]
    assert wrote
    assert (
        data["recorded_calls"]
        == sum(row["recorded_calls"] for row in data["models"])
        == 4
    )
    assert sum(row["recorded_calls"] for row in data["providers"]) == 4
    assert service.overview()["data"]["recorded_calls"] == 5


@pytest.mark.parametrize("method", ["overview", "models", "sessions", "trends"])
@pytest.mark.parametrize("has_records", [False, True])
def test_provider_identity_is_explicitly_legacy_unverified(
    metrics, database, method, has_records
):
    if has_records:
        insert(database, model_id="registry-route", provider_id="registry-route")
    data = getattr(metrics.LedgerMetricsService(database), method)()["data"]
    assert data["provider_identity_quality"] == "legacy_unverified"
    assert (
        data["provider_identity_source_code"]
        == "schema1_provider_id_from_registry_route_id"
    )


def test_provider_groups_preserve_route_ids_without_claiming_verified_vendors(
    metrics, database
):
    # 复现 schema1 writer：provider_id=model_id，是 registry 路由，不是外部 vendor。
    for route, model, prompt in (
        ("route-alpha", "model-a", 2),
        ("route-beta", "model-a", 3),
        ("route-alpha", "model-b", 5),
    ):
        insert(
            database,
            model_id=route,
            provider_id=route,
            actual_model=model,
            prompt_tokens=prompt,
        )
    data = metrics.LedgerMetricsService(database).models()["data"]
    groups = data["providers"]
    assert [(row["provider"], row["recorded_calls"]) for row in groups] == [
        ("route-alpha", 2),
        ("route-beta", 1),
    ]
    assert groups[0]["tokens"]["prompt"] == value(7, 2, 0, "complete")
    assert groups[1]["tokens"]["prompt"] == value(3, 1, 0, "complete")
    for row in groups:
        assert row["provider_identity_quality"] == "legacy_unverified"
        assert row["provider_identity_quality"] == data["provider_identity_quality"]
        assert (
            row["provider_identity_source_code"]
            == "schema1_provider_id_from_registry_route_id"
        )
        assert (
            row["provider_identity_source_code"]
            == data["provider_identity_source_code"]
        )
        assert "vendor" not in row and "verified_vendor" not in row
