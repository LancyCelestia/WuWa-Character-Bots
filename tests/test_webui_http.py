"""WebUI 端点 HTTP 契约：信封/认证语义/静态挂载（TestClient，离线）。

- /api/v1/stats/*、/api/v1/affinity/board 走与既有 v1 相同的统一信封、
  Bearer 双令牌认证、未配置令牌 503 not_provisioned、参数非法 422；
- /ui 静态壳：产物存在 200 text/html，缺失 404 诚实体（host 白名单等
  既有中间件语义不变，静态壳不含数据，数据面全部经认证端点）。
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from plugins.bot_unified_runtime.control_plane import create_control_plane_app
from plugins.bot_unified_runtime.control_plane.audit import ControlPlaneAuditStore
from plugins.bot_unified_runtime.control_plane.auth import hash_token
from plugins.bot_unified_runtime.control_plane.metrics import LedgerMetricsService
from plugins.bot_unified_runtime.control_plane.webui_stats import (
    AffinityBoardService,
    AuditCallStatsService,
    WebUIStatsBundle,
)


def _config(tmp_path: Path, *, admin: str, super_admin: str) -> SimpleNamespace:
    return SimpleNamespace(
        bot_control_plane_enabled=True,
        # 空令牌=未配置（sha256 设置串本身为空串，而非空串的哈希）。
        bot_control_plane_token_sha256=hash_token(admin) if admin else "",
        bot_control_plane_super_admin_token_sha256=hash_token(super_admin) if super_admin else "",
        bot_runtime_settings_dir=str(tmp_path / "settings"),
        bot_control_plane_config_db=str(tmp_path / "config.sqlite3"),
        bot_runtime_settings_file=str(tmp_path / "settings.json"),
        bot_control_plane_features_file=str(tmp_path / "features.json"),
        bot_timezone="UTC",
    )


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _audit_table(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            "CREATE TABLE audit_records (audit_id TEXT PRIMARY KEY, request_id TEXT,"
            " session_id TEXT, capability_id TEXT, stage TEXT, event TEXT,"
            " severity TEXT, public_message TEXT, private_debug TEXT, created_at TEXT)"
        )
        # 种子时间必须动态取近期：stats/calls 按 now-24h 相对窗口过滤，
        # 硬编码日期会在次日滑出窗口（2026-09-19 时间炸弹事故）。
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        connection.execute(
            "INSERT INTO audit_records VALUES ('a1','r1','private_777','bot.chat',"
            f"'invoke','done','low','ok','','{recent}')"
        )


def _affinity_table(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            "CREATE TABLE user_affinity (sender_id TEXT PRIMARY KEY,"
            " affinity REAL NOT NULL DEFAULT 0.1, interaction_count INTEGER"
            " NOT NULL DEFAULT 0, nickname TEXT NOT NULL DEFAULT '',"
            " updated_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO user_affinity (sender_id, affinity, nickname,"
            " interaction_count, updated_at) VALUES ('777', 0.5, '岸宝', 9, 'x')"
        )


def _app(tmp_path: Path, **overrides):
    calls_db = tmp_path / "audit.sqlite3"
    affinity_db = tmp_path / "affinity.sqlite3"
    ledger_db = tmp_path / "ledger.sqlite3"
    _audit_table(calls_db)
    _affinity_table(affinity_db)
    kwargs: dict[str, object] = {
        "stats_service": WebUIStatsBundle(
            calls=AuditCallStatsService(calls_db),
            affinity=AffinityBoardService(affinity_db),
        ),
        "metrics_service": LedgerMetricsService(ledger_db),
        "webui_dist_dir": str(tmp_path / "dist"),
    }
    kwargs.update(overrides)
    return create_control_plane_app(
        _config(tmp_path, admin="admin-token", super_admin="root-token"),
        audit_store=ControlPlaneAuditStore(str(tmp_path / "cp-audit.sqlite3")),
        channel_health_store=object(),
        **kwargs,
    )


READ_PATHS = (
    "/api/v1/stats/calls",
    "/api/v1/stats/tokens",
    "/api/v1/stats/latency",
    "/api/v1/affinity/board",
)


def test_stats_endpoints_require_bearer_and_use_common_envelope(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        for path in READ_PATHS:
            assert client.get(path).status_code == 401, path
        response = client.get("/api/v1/stats/calls", headers=_headers("admin-token"))
        assert response.status_code == 200
        assert response.headers["x-request-id"]
        assert response.headers["cache-control"] == "no-store"
        payload = response.json()
        assert payload["error"] is None
        assert payload["meta"]["schema_version"] == "v1"
        assert payload["data"]["status"] == "ok"
        assert payload["data"]["data"]["total_calls"] == 1


def test_stats_invalid_query_maps_to_422(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        for path, query in (
            ("/api/v1/stats/calls", "window=99w"),
            ("/api/v1/stats/tokens", "window=week"),
            ("/api/v1/affinity/board", "order=sideways"),
            ("/api/v1/stats/calls", "limit=0"),
        ):
            response = client.get(
                f"{path}?{query}", headers=_headers("admin-token")
            )
            assert response.status_code == 422, (path, query, response.status_code)
            assert response.json()["error"]["code"] == "stats_invalid_query"


def test_stats_endpoints_return_503_when_unprovisioned(tmp_path: Path) -> None:
    app = create_control_plane_app(
        _config(tmp_path, admin="", super_admin=""),
        audit_store=ControlPlaneAuditStore(str(tmp_path / "cp-audit.sqlite3")),
        stats_service=WebUIStatsBundle(
            calls=AuditCallStatsService(tmp_path / "a.sqlite3"),
            affinity=AffinityBoardService(tmp_path / "b.sqlite3"),
        ),
    )
    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        for path in READ_PATHS:
            response = client.get(path)
            assert response.status_code == 503, path
            assert response.json()["error"]["code"] == "control_plane_not_provisioned"


def test_latency_and_tokens_degraded_sources_still_envelope_ok(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        latency = client.get("/api/v1/stats/latency", headers=_headers("admin-token"))
        assert latency.status_code == 200
        body = latency.json()["data"]
        # channel_health_store=object()：无 report 接口 → 如实降级不炸 500。
        assert body["status"] == "source_unavailable"

        tokens = client.get("/api/v1/stats/tokens", headers=_headers("admin-token"))
        assert tokens.status_code == 200
        assert tokens.json()["data"]["status"] == "source_unavailable"  # 账本库缺失=诚实降级


def test_ui_serves_single_file_index_or_honest_404(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        missing = client.get("/ui")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "ui_not_built"

    index = tmp_path / "dist" / "index.html"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text("<html><body>shorekeeper-ui</body></html>", encoding="utf-8")

    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        served = client.get("/ui")
        assert served.status_code == 200
        assert served.headers["content-type"].startswith("text/html")
        assert "shorekeeper-ui" in served.text
        assert served.headers["cache-control"] == "no-store"


def test_ui_static_shell_served_even_when_tokens_unprovisioned(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>shell</html>", encoding="utf-8")
    app = create_control_plane_app(
        _config(tmp_path, admin="", super_admin=""),
        audit_store=ControlPlaneAuditStore(str(tmp_path / "cp-audit.sqlite3")),
        webui_dist_dir=str(dist),
    )
    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        # 静态壳无数据（healthz 同级）；数据端点此刻 503 not_provisioned。
        assert client.get("/ui").status_code == 200
        assert client.get("/api/v1/stats/calls").status_code == 503
