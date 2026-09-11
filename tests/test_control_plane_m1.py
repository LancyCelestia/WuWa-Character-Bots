"""B4 M1 控制面回归：默认关、Bearer 认证（SHA-256 恒定时间）、失败限速、
healthz/health/status 最小面 DTO 白名单、审计落库与脱敏、错误体契约。

规格：docs/design/control-plane-api.md（仅 M1）。
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import plugins.bot_unified_runtime.control_plane._app as cp_app_module
from plugins.bot_unified_runtime.control_plane import (
    ControlPlaneSettings,
    control_plane_enabled,
    control_plane_settings,
    create_control_plane_app,
    serve,
)
from plugins.bot_unified_runtime.control_plane.audit import ControlPlaneAuditStore
from plugins.bot_unified_runtime.control_plane.auth import hash_token

TOKEN = "unit-test-token"
DEBUG_ID_RE = re.compile(r"^cp-\d{8}-[0-9a-f]{8}$")


@pytest.fixture(autouse=True)
def _clean_cp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """隔离控制面环境变量：默认关的断言不受本机环境污染。"""
    for name in (
        "BOT_CONTROL_PLANE_ENABLED",
        "BOT_CONTROL_PLANE_HOST",
        "BOT_CONTROL_PLANE_PORT",
        "BOT_CONTROL_PLANE_TOKEN_SHA256",
    ):
        monkeypatch.delenv(name, raising=False)


class FakeChannelHealthStore:
    def __init__(
        self,
        rows: list[dict[str, object]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.rows = rows if rows is not None else []
        self.error = error

    def report(self) -> list[dict[str, object]]:
        if self.error is not None:
            raise self.error
        return self.rows


def _config(token_sha256: str = "", **extra: object) -> SimpleNamespace:
    return SimpleNamespace(
        bot_control_plane_token_sha256=token_sha256, **extra
    )


def _client(
    tmp_path,
    *,
    token_sha256: str = "",
    rows: list[dict[str, object]] | None = None,
    store_error: Exception | None = None,
    config: SimpleNamespace | None = None,
    started_at: datetime | None = None,
) -> TestClient:
    app = create_control_plane_app(
        config if config is not None else _config(token_sha256),
        channel_health_store=FakeChannelHealthStore(rows, store_error),
        audit_store=ControlPlaneAuditStore(str(tmp_path / "cp.sqlite3")),
        started_at=started_at or datetime.now().astimezone(),
    )
    return TestClient(app)


# ==================== 开关与设置（默认关） ====================


def test_settings_default_off_and_loopback() -> None:
    settings = control_plane_settings(SimpleNamespace())
    assert settings == ControlPlaneSettings(
        enabled=False, host="127.0.0.1", port=8742, token_sha256=""
    )
    assert control_plane_enabled(None) is False
    assert control_plane_enabled(SimpleNamespace()) is False


def test_settings_config_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_CONTROL_PLANE_ENABLED", "true")
    monkeypatch.setenv("BOT_CONTROL_PLANE_HOST", "0.0.0.0")
    monkeypatch.setenv("BOT_CONTROL_PLANE_PORT", "9999")
    # 全部走 env 兜底。
    settings = control_plane_settings(SimpleNamespace())
    assert settings.enabled is True
    assert settings.host == "0.0.0.0"
    assert settings.port == 9999
    # Config 字段优先于 env。
    settings = control_plane_settings(
        SimpleNamespace(
            bot_control_plane_enabled="false",
            bot_control_plane_host="127.0.0.1",
            bot_control_plane_port="8742",
        )
    )
    assert settings.enabled is False
    assert settings.host == "127.0.0.1"
    assert settings.port == 8742


def test_settings_invalid_values_fall_back_to_defaults() -> None:
    settings = control_plane_settings(
        SimpleNamespace(
            bot_control_plane_enabled="maybe",
            bot_control_plane_port="not-a-port",
        )
    )
    assert settings.enabled is False
    assert settings.port == 8742


# ==================== healthz 与认证 ====================


def test_healthz_is_constant_no_auth(tmp_path) -> None:
    with _client(tmp_path) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_api_503_when_token_not_provisioned(tmp_path) -> None:
    with _client(tmp_path) as client:
        response = client.get("/admin/api/v1/health")
    assert response.status_code == 503
    body = response.json()["error"]
    assert body["code"] == "control_plane_not_provisioned"
    assert DEBUG_ID_RE.match(body["debug_id"])
    assert "Traceback" not in body["message"]


def test_bearer_token_flow(tmp_path) -> None:
    digest = hash_token(TOKEN)
    with _client(tmp_path, token_sha256=digest) as client:
        missing = client.get("/admin/api/v1/health")
        wrong = client.get(
            "/admin/api/v1/health",
            headers={"Authorization": "Bearer wrong-token"},
        )
        ok = client.get(
            "/admin/api/v1/health",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "unauthorized"
    assert ok.status_code == 200
    payload = ok.json()
    assert payload["ok"] is True
    assert payload["checks"]["audit_store"] == "ok"
    assert payload["checks"]["control_plane"] == "ok"


def test_failure_rate_limit_429_with_retry_after(tmp_path) -> None:
    digest = hash_token(TOKEN)
    with _client(tmp_path, token_sha256=digest) as client:
        for _ in range(5):
            response = client.get("/admin/api/v1/health")
            assert response.status_code == 401
        blocked = client.get(
            "/admin/api/v1/health",
            headers={"Authorization": f"Bearer {TOKEN}"},  # 对的 token 也被限
        )
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert "Retry-After" in blocked.headers


def test_token_hash_is_sha256_hex() -> None:
    import hashlib

    assert hash_token("abc") == hashlib.sha256(b"abc").hexdigest()


# ==================== 只读 status 最小面（DTO 白名单） ====================


def test_status_models_projection_masks_secrets(tmp_path) -> None:
    rows = [
        {
            "model_id": "ch-a",
            "state": "ok",
            "consecutive_fails": 0,
            "latency_ms": 812,
            "ema_ms": 900,
            "samples": 3,
            "last_error": "api_key=supersecret123 sk-deadbeefcafe bad",
            "last_ok_at": "2026-09-12T10:03:11+08:00",
        }
    ]
    with _client(tmp_path, token_sha256=hash_token(TOKEN), rows=rows) as client:
        response = client.get(
            "/admin/api/v1/status/models",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"items", "generated_at"}
    item = payload["items"][0]
    # DTO 白名单：绝不出现 ema_ms/samples/api_key/base_url 等额外字段。
    assert set(item) == {
        "model_id",
        "state",
        "consecutive_fails",
        "latency_ms",
        "last_error",
        "last_ok_at",
    }
    assert "supersecret123" not in item["last_error"]
    assert "sk-deadbeefcafe" not in item["last_error"]
    assert "[redacted]" in item["last_error"]


def test_status_models_store_failure_maps_to_503(tmp_path) -> None:
    with _client(
        tmp_path,
        token_sha256=hash_token(TOKEN),
        store_error=RuntimeError("db locked"),
    ) as client:
        response = client.get(
            "/admin/api/v1/status/models",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "store_unavailable"


def test_status_bot_fields(tmp_path) -> None:
    started = datetime.now().astimezone()
    with _client(
        tmp_path,
        token_sha256=hash_token(TOKEN),
        started_at=started,
        config=_config(hash_token(TOKEN), bot_timezone="Asia/Hong_Kong"),
    ) as client:
        response = client.get(
            "/admin/api/v1/status/bot",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"started_at", "uptime_seconds", "timezone"}
    assert payload["started_at"].startswith(str(started.year))
    assert payload["uptime_seconds"] >= 0
    assert payload["timezone"] == "Asia/Hong_Kong"


# ==================== 审计 ====================


def test_audit_rows_written_and_query_redacted(tmp_path) -> None:
    db_path = str(tmp_path / "cp.sqlite3")
    store = ControlPlaneAuditStore(db_path)
    app = create_control_plane_app(
        _config(hash_token(TOKEN)),
        channel_health_store=FakeChannelHealthStore(),
        audit_store=store,
        started_at=datetime.now().astimezone(),
    )
    with TestClient(app) as client:
        client.get(
            "/admin/api/v1/health?token=topsecret&limit=5",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        client.get("/admin/api/v1/health")  # 401 失败也要留痕
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM control_plane_audit ORDER BY id"
        ).fetchall()
    assert len(rows) == 2
    ok_row, denied_row = rows
    assert ok_row["subject"] == "bearer-admin"
    assert ok_row["status_code"] == 200
    assert ok_row["method"] == "GET"
    assert ok_row["path"] == "/admin/api/v1/health"
    assert "topsecret" not in ok_row["query"]
    assert "token=[redacted]" in ok_row["query"]
    assert "limit=5" in ok_row["query"]
    assert denied_row["subject"] == "anonymous"
    assert denied_row["status_code"] == 401


# ==================== serve 入口守卫 ====================


def test_serve_disabled_by_default() -> None:
    assert serve(None) == 0
    assert serve(SimpleNamespace()) == 0


def test_serve_refuses_non_loopback_without_confirmation(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cp_app_module,
        "_public_confirmation_file",
        lambda: str(tmp_path / "control_plane_public.confirmed"),
    )
    config = SimpleNamespace(
        bot_control_plane_enabled="true",
        bot_control_plane_host="0.0.0.0",
    )
    assert serve(config) == 2  # 无确认文件 → 拒绝启动（B4 §9.7）
