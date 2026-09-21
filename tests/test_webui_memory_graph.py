"""WebUI 记忆图谱端点（/api/v1/memory/graph）服务层契约：tmp 库、离线、只读。

数据源（全部只读，URI mode=ro + query_only，缺库 = 该源标记 missing、
对应 stats 0，绝不创建文件、绝不造数）：
- history sqlite（conversation_turns）：人物×会话发言边、群聊-会话 hosts 边；
- memory sqlite（memory_facts）：人物-长期记忆归属边；
- quirks sqlite（persona_quirks active）+ affinity 已学昵称（nickname≠空）：
  rule 节点与人物-规则边；
- affinity（user_affinity.affinity）：人物节点 weight。

图谱语义：窗口过滤（24h/7d/30d/all）、节点按度数封顶（max_nodes ≤200，
默认 120；截断如实 truncated:true + nodes_total）、确定性排序
（度数降序 + id 升序）。
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.control_plane.webui_memory_graph import (
    MemoryGraphService,
    build_default_memory_graph_service,
)

NOW = datetime.now(timezone.utc)


@pytest.fixture
def history_db(tmp_path: Path) -> Path:
    path = tmp_path / "history.sqlite3"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            "CREATE TABLE conversation_turns (request_id TEXT, platform TEXT,"
            " adapter TEXT, bot_id TEXT, session_id TEXT, sender_id TEXT,"
            " role TEXT, text TEXT, created_at TEXT, kind TEXT"
            " NOT NULL DEFAULT 'chat')"
        )

        def turn(session: str, sender: str, hours_ago: float) -> None:
            stamp = (NOW - timedelta(hours=hours_ago)).isoformat()
            connection.execute(
                "INSERT INTO conversation_turns (request_id, platform, adapter,"
                " bot_id, session_id, sender_id, role, text, created_at)"
                " VALUES ('r', 'qq', 'onebot', 'bot', ?, ?, 'user', 'hi', ?)",
                (session, sender, stamp),
            )

        turn("group_100_20001", "20001", 2)
        turn("group_100_20001", "20001", 3)
        turn("group_100_20001", "20001", 5)
        turn("group_100_20002", "20002", 4)
        turn("private_20001", "20001", 1)
        turn("private_20001", "20001", 2)
        # 40 天前：仅 window=all 计入。
        turn("group_200_20001", "20001", 40 * 24)
    return path


@pytest.fixture
def memory_db(tmp_path: Path) -> Path:
    path = tmp_path / "memory.sqlite3"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            "CREATE TABLE memory_facts (fact_id TEXT PRIMARY KEY,"
            " subject_user_id TEXT NOT NULL, session_id TEXT NOT NULL DEFAULT '',"
            " memory_kind TEXT NOT NULL, text TEXT NOT NULL,"
            " confidence REAL NOT NULL DEFAULT 0.8,"
            " source TEXT NOT NULL DEFAULT 'sqlite',"
            " sensitivity TEXT NOT NULL DEFAULT 'personal',"
            " scope_key TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,"
            " updated_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO memory_facts (fact_id, subject_user_id, memory_kind,"
            " text, created_at, updated_at) VALUES ('f1', '20001', 'preference',"
            " ?, ?, ?)",
            (
                "喜欢被叫澜汐，" + "细节" * 60,  # >80 字，label 须截断
                (NOW - timedelta(hours=1)).isoformat(),
                (NOW - timedelta(hours=1)).isoformat(),
            ),
        )
        # 40 天前：仅 window=all 计入。
        connection.execute(
            "INSERT INTO memory_facts (fact_id, subject_user_id, memory_kind,"
            " text, created_at, updated_at) VALUES ('f2', '30001', 'fact',"
            " '旧事实', ?, ?)",
            ((NOW - timedelta(days=40)).isoformat(),) * 2,
        )
    return path


@pytest.fixture
def quirks_db(tmp_path: Path) -> Path:
    path = tmp_path / "quirks.sqlite3"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            "CREATE TABLE persona_quirks (quirk_id TEXT PRIMARY KEY,"
            " quirk_text TEXT NOT NULL,"
            " status TEXT NOT NULL DEFAULT 'pending_review',"
            " source TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,"
            " reviewed_at TEXT, scope_kind TEXT NOT NULL DEFAULT 'global',"
            " scope_key TEXT NOT NULL DEFAULT '')"
        )
        rows = [
            ("q1", "说话喜欢用波浪号", "active", "global", ""),
            ("q2", "被夸时会脸红", "active", "user", "20001"),
            ("q3", "已退役的习惯", "retired", "global", ""),
        ]
        for quirk_id, text, status, kind, key in rows:
            connection.execute(
                "INSERT INTO persona_quirks (quirk_id, quirk_text, status,"
                " created_at, scope_kind, scope_key) VALUES (?, ?, ?, ?, ?, ?)",
                (quirk_id, text, status, NOW.isoformat(), kind, key),
            )
    return path


@pytest.fixture
def affinity_db(tmp_path: Path) -> Path:
    path = tmp_path / "user_affinity.sqlite3"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            "CREATE TABLE user_affinity (sender_id TEXT PRIMARY KEY,"
            " affinity REAL NOT NULL DEFAULT 0.1,"
            " interaction_count INTEGER NOT NULL DEFAULT 0,"
            " nickname TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO user_affinity (sender_id, affinity, nickname,"
            " interaction_count, updated_at) VALUES (?, ?, ?, ?, ?)",
            [
                ("20001", 0.85, "澜汐", 42, NOW.isoformat()),
                ("20002", -0.2, "", 3, NOW.isoformat()),
                ("30001", 0.1, "小岸", 7, (NOW - timedelta(days=40)).isoformat()),
            ],
        )
    return path


def _service(
    tmp_path: Path,
    *,
    history: Path | None = None,
    memory: Path | None = None,
    quirks: Path | None = None,
    affinity: Path | None = None,
) -> MemoryGraphService:
    return MemoryGraphService(
        history_db_path=history or "",
        memory_db_path=memory or "",
        quirks_db_path=quirks or "",
        affinity_db_path=affinity or "",
    )


@pytest.fixture
def full_service(
    history_db: Path, memory_db: Path, quirks_db: Path, affinity_db: Path
) -> MemoryGraphService:
    return MemoryGraphService(
        history_db_path=history_db,
        memory_db_path=memory_db,
        quirks_db_path=quirks_db,
        affinity_db_path=affinity_db,
    )


# ---------------------------------------------------------------------------
# 聚合语义
# ---------------------------------------------------------------------------


def test_graph_aggregates_all_sources_within_window(full_service: MemoryGraphService) -> None:
    result = full_service.graph(window="24h")
    assert result["status"] == "ok"
    assert result["source"] == "memory_graph"
    data = result["data"]
    assert data["window"] == "24h"
    stats = data["stats"]
    assert stats["persons"] == 3  # 20001/20002（发言）+ 30001（记忆/昵称）
    assert stats["groups"] == 1
    assert stats["conversations"] == 3
    assert stats["long_term_memories"] == 1
    assert stats["learned_rules"] == 4  # active quirk×2 + 已学昵称×2
    assert stats["speaker_count"] == 2  # 24h 内真发过言的人物

    nodes = {node["id"]: node for node in data["nodes"]}
    assert nodes["person:20001"]["weight"] == pytest.approx(0.85)
    assert nodes["person:20002"]["weight"] == pytest.approx(-0.2)
    assert nodes["person:30001"]["weight"] == pytest.approx(0.1)
    assert nodes["person:20001"]["type"] == "person"
    assert nodes["group:100"]["type"] == "group"
    assert nodes["conv:group_100_20001"]["type"] == "conversation"
    assert nodes["memory:f1"]["type"] == "memory"
    assert len(nodes["memory:f1"]["label"]) <= 80
    assert nodes["rule:nick:20001"]["type"] == "rule"
    assert nodes["rule:quirk:q2"]["type"] == "rule"
    # 全局怪癖=规则节点但无人物边（scope 事实如此，不硬造归属）。
    assert nodes["rule:quirk:q1"]["type"] == "rule"

    edges = {
        (edge["source"], edge["target"]): edge for edge in data["edges"]
    }
    assert edges[("person:20001", "conv:group_100_20001")]["kind"] == "speaks_in"
    assert edges[("person:20001", "conv:group_100_20001")]["weight"] == 3
    assert edges[("person:20001", "conv:private_20001")]["weight"] == 2
    assert edges[("group:100", "conv:group_100_20001")]["kind"] == "hosts"
    assert edges[("person:20001", "memory:f1")]["kind"] == "about"
    assert edges[("person:20001", "rule:quirk:q2")]["kind"] == "learned_rule"
    assert edges[("person:20001", "rule:nick:20001")]["kind"] == "nickname"
    assert len(data["nodes"]) == 12 and len(data["edges"]) == 9
    assert data["sources"] == {
        "history": "ok",
        "memory": "ok",
        "quirks": "ok",
        "affinity": "ok",
    }


def test_graph_all_window_pulls_old_rows(full_service: MemoryGraphService) -> None:
    data = full_service.graph(window="all")["data"]
    assert data["stats"]["groups"] == 2
    assert data["stats"]["conversations"] == 4
    assert data["stats"]["long_term_memories"] == 2
    assert data["stats"]["speaker_count"] == 2
    ids = {node["id"] for node in data["nodes"]}
    assert "group:200" in ids and "memory:f2" in ids


def test_graph_deterministic_ordering(full_service: MemoryGraphService) -> None:
    service = full_service
    first = service.graph(window="24h")
    second = service.graph(window="24h")
    assert json.dumps(first, ensure_ascii=False, sort_keys=True) == json.dumps(
        second, ensure_ascii=False, sort_keys=True
    )
    nodes = first["data"]["nodes"]
    degrees: dict[str, int] = {}
    for edge in first["data"]["edges"]:
        degrees[edge["source"]] = degrees.get(edge["source"], 0) + 1
        degrees[edge["target"]] = degrees.get(edge["target"], 0) + 1
    keys = [(-degrees.get(node["id"], 0), node["id"]) for node in nodes]
    assert keys == sorted(keys)


def test_graph_truncation_caps_nodes_and_drops_edges(full_service: MemoryGraphService) -> None:
    data = full_service.graph(window="24h", max_nodes=5)["data"]
    assert data["truncated"] is True
    assert data["nodes_total"] == 12
    assert len(data["nodes"]) == 5
    node_ids = {node["id"] for node in data["nodes"]}
    for edge in data["edges"]:
        assert edge["source"] in node_ids
        assert edge["target"] in node_ids
    # stats 仍为截断前总量（不因截断撒谎）。
    assert data["stats"]["persons"] == 3
    assert data["stats"]["speaker_count"] == 2


@pytest.mark.parametrize("window", ["24h", "7d", "30d", "all"])
def test_graph_window_closed_enum_ok(full_service: MemoryGraphService, window: str) -> None:
    result = full_service.graph(window=window)
    assert result["status"] == "ok"
    assert result["data"]["window"] == window


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"window": "99w"}, "invalid_window"),
        ({"window": "24h; DROP TABLE"}, "invalid_window"),
        ({"window": None}, "invalid_window"),
        ({"max_nodes": 0}, "invalid_max_nodes"),
        ({"max_nodes": 201}, "invalid_max_nodes"),
        ({"max_nodes": "5"}, "invalid_max_nodes"),
        ({"max_nodes": 1.5}, "invalid_max_nodes"),
    ],
)
def test_graph_invalid_params_rejected_without_io(
    tmp_path: Path, monkeypatch, kwargs, reason: str
) -> None:
    def no_connect(*args, **kwargs2):
        pytest.fail("invalid request opened database")

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.control_plane.webui_memory_graph.sqlite3.connect",
        no_connect,
    )
    result = _service(tmp_path).graph(**kwargs)
    assert result == {"status": "invalid_request", "reason": reason, "data": None}


# ---------------------------------------------------------------------------
# 缺源诚实降级 + 只读
# ---------------------------------------------------------------------------


def test_graph_all_sources_missing_is_honest(tmp_path: Path) -> None:
    result = _service(tmp_path).graph(window="24h")
    assert result["status"] == "source_unavailable"
    assert result["reason"] == "all_sources_missing"
    data = result["data"]
    assert data["stats"] == {
        "persons": 0,
        "groups": 0,
        "conversations": 0,
        "long_term_memories": 0,
        "learned_rules": 0,
        "speaker_count": 0,
    }
    assert data["nodes"] == [] and data["edges"] == []
    assert set(data["sources"].values()) == {"missing"}
    assert str(tmp_path) not in json.dumps(result, ensure_ascii=False)


def test_graph_partial_missing_source_marks_and_zeros(
    tmp_path: Path, history_db: Path
) -> None:
    data = MemoryGraphService(
        history_db_path=history_db,
        memory_db_path="",
        quirks_db_path="",
        affinity_db_path="",
    ).graph(window="24h")["data"]
    assert data["sources"]["history"] == "ok"
    assert data["sources"]["memory"] == "missing"
    assert data["stats"]["long_term_memories"] == 0
    assert data["stats"]["conversations"] == 3
    assert data["stats"]["speaker_count"] == 2
    assert str(tmp_path) not in json.dumps(data, ensure_ascii=False)


def test_graph_bad_schema_is_contained(tmp_path: Path) -> None:
    path = tmp_path / "history.sqlite3"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE conversation_turns (created_at TEXT)")
    memory = tmp_path / "memory.sqlite3"
    with closing(sqlite3.connect(memory)) as connection, connection:
        connection.execute(
            "CREATE TABLE memory_facts (fact_id TEXT PRIMARY KEY,"
            " subject_user_id TEXT NOT NULL, memory_kind TEXT NOT NULL,"
            " text TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
    result = _service(tmp_path, history=path, memory=memory).graph(window="24h")
    assert result["status"] == "ok"
    assert result["data"]["sources"]["history"] == "unreadable"
    assert result["data"]["stats"]["conversations"] == 0
    assert result["data"]["stats"]["long_term_memories"] == 0


def test_graph_reads_never_mutate(
    full_service: MemoryGraphService,
    history_db: Path,
    memory_db: Path,
    quirks_db: Path,
    affinity_db: Path,
) -> None:
    paths = [history_db, memory_db, quirks_db, affinity_db]
    before = [path.read_bytes() for path in paths]
    full_service.graph(window="all")
    full_service.graph(window="24h", max_nodes=5)
    assert [path.read_bytes() for path in paths] == before


def test_build_default_service_from_config(tmp_path: Path) -> None:
    from types import SimpleNamespace

    config = SimpleNamespace(
        bot_history_db_path=str(tmp_path / "history.sqlite3"),
        bot_memory_db_path=str(tmp_path / "memory.sqlite3"),
        bot_quirks_db_path=str(tmp_path / "quirks.sqlite3"),
        bot_affinity_db_path=str(tmp_path / "user_affinity.sqlite3"),
    )
    service = build_default_memory_graph_service(config)
    assert service.graph(window="24h")["status"] == "source_unavailable"


# ---------------------------------------------------------------------------
# HTTP 投影：统一信封 / 认证 / 422 映射（挂 _app 装配）
# ---------------------------------------------------------------------------


def test_memory_graph_http_envelope_auth_and_422(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from plugins.bot_unified_runtime.control_plane import create_control_plane_app
    from plugins.bot_unified_runtime.control_plane.audit import ControlPlaneAuditStore
    from plugins.bot_unified_runtime.control_plane.auth import hash_token

    config = SimpleNamespace(
        bot_control_plane_enabled=True,
        bot_control_plane_token_sha256=hash_token("admin-token"),
        bot_control_plane_super_admin_token_sha256=hash_token("root-token"),
        bot_runtime_settings_dir=str(tmp_path / "settings"),
        bot_control_plane_config_db=str(tmp_path / "config.sqlite3"),
        bot_runtime_settings_file=str(tmp_path / "settings.json"),
        bot_control_plane_features_file=str(tmp_path / "features.json"),
        bot_timezone="UTC",
        bot_history_db_path=str(tmp_path / "history.sqlite3"),
        bot_memory_db_path=str(tmp_path / "memory.sqlite3"),
        bot_quirks_db_path=str(tmp_path / "quirks.sqlite3"),
        bot_affinity_db_path=str(tmp_path / "user_affinity.sqlite3"),
    )
    app = create_control_plane_app(
        config,
        audit_store=ControlPlaneAuditStore(str(tmp_path / "cp-audit.sqlite3")),
        channel_health_store=object(),
        webui_dist_dir=str(tmp_path / "dist"),
    )
    headers = {"Authorization": "Bearer admin-token"}
    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        assert client.get("/api/v1/memory/graph").status_code == 401
        response = client.get(
            "/api/v1/memory/graph?window=24h&max_nodes=50", headers=headers
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["error"] is None
        assert payload["data"]["status"] == "source_unavailable"
        assert payload["data"]["reason"] == "all_sources_missing"

        invalid = client.get("/api/v1/memory/graph?window=99w", headers=headers)
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "memory_graph_invalid_query"
