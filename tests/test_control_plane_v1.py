"""Control-plane v1 contracts for the future WebUI backend."""

from __future__ import annotations

import shutil
import tempfile
import warnings
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from plugins.bot_unified_runtime.control_plane import create_control_plane_app
from plugins.bot_unified_runtime.control_plane.audit import ControlPlaneAuditStore
from plugins.bot_unified_runtime.control_plane.auth import hash_token
from plugins.bot_unified_runtime.control_plane.features import (
    FeatureDescriptor,
    FeatureStateStore,
)


def _test_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="control-plane-v1-"))


def _config(tmp_path: Path, *, admin: str, super_admin: str) -> SimpleNamespace:
    return SimpleNamespace(
        bot_control_plane_enabled=True,
        bot_control_plane_token_sha256=hash_token(admin),
        bot_control_plane_super_admin_token_sha256=hash_token(super_admin),
        bot_runtime_settings_dir=str(tmp_path / "settings"),
        bot_control_plane_config_db=str(tmp_path / "config.sqlite3"),
        bot_runtime_settings_file=str(tmp_path / "settings.json"),
        bot_control_plane_features_file=str(tmp_path / "features.json"),
        bot_timezone="UTC",
    )


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_feature_state_inherits_parent_and_supports_versioned_changes() -> None:
    tmp_path = _test_dir()
    descriptors = (
        FeatureDescriptor(
            id="bot",
            parent_id=None,
            kind="group",
            label="Bot",
            default_enabled=True,
        ),
        FeatureDescriptor(
            id="bot.plugin.weather",
            parent_id="bot",
            kind="plugin",
            label="天气",
            default_enabled=True,
        ),
        FeatureDescriptor(
            id="bot.plugin.weather.command.forecast",
            parent_id="bot.plugin.weather",
            kind="command",
            label="天气命令",
            default_enabled=True,
        ),
    )
    try:
        store = FeatureStateStore(tmp_path / "features.json", descriptors=descriptors)
        assert store.get("bot.plugin.weather.command.forecast").effective_enabled is True
        changed = store.set_enabled("bot.plugin.weather", False, actor="root", expected_version=0)
        assert changed["state"]["version"] == 1
        child = store.get("bot.plugin.weather.command.forecast")
        assert child.effective_enabled is False
        assert child.blocked_by == ("bot.plugin.weather",)
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_control_plane_v1_uses_common_envelope_and_super_admin_write() -> None:
    tmp_path = _test_dir()
    app = create_control_plane_app(
        _config(tmp_path, admin="admin-token", super_admin="root-token"),
        audit_store=ControlPlaneAuditStore(str(tmp_path / "audit.sqlite3")),
        channel_health_store=object(),
    )
    try:
        with TestClient(app, base_url="http://127.0.0.1:8742") as client:
            listed = client.get("/api/v1/features", headers=_headers("admin-token"))
            assert listed.status_code == 200
            payload = listed.json()
            assert payload["error"] is None
            assert payload["meta"]["schema_version"] == "v1"
            assert any(item["descriptor"]["id"] == "bot" for item in payload["data"]["items"])
            denied = client.post(
                "/api/v1/features/bot.plugin.weather/disable",
                headers=_headers("admin-token"),
                json={"expected_version": 0},
            )
            assert denied.status_code == 403
            assert denied.json()["error"]["code"] == "forbidden"

            enabled = client.post(
                "/api/v1/features/bot.plugin.weather/disable",
                headers=_headers("root-token"),
                json={"expected_version": 0},
            )
            assert enabled.status_code == 200
            body = enabled.json()
            assert body["data"]["state"]["effective_enabled"] is False
            assert body["data"]["audit_id"]
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_control_plane_v1_config_preview_and_allowlisted_write() -> None:
    tmp_path = _test_dir()
    app = create_control_plane_app(
        _config(tmp_path, admin="admin-token", super_admin="root-token"),
        audit_store=ControlPlaneAuditStore(str(tmp_path / "audit.sqlite3")),
        channel_health_store=object(),
    )
    try:
        with TestClient(app, base_url="http://127.0.0.1:8742") as client:
            preview = client.post(
                "/api/v1/config/BOT_CHAT_TEMPERATURE/preview",
                headers=_headers("root-token"),
                json={"value": "0.7", "expected_version": 0},
            )
            assert preview.status_code == 200
            assert preview.json()["data"]["value"] == 0.7

            written = client.post(
                "/api/v1/config/BOT_CHAT_TEMPERATURE/set",
                headers=_headers("root-token"),
                json={"value": "0.7", "expected_version": 0},
            )
            assert written.status_code == 200
            assert written.json()["data"]["value"] == 0.7

            secret = client.get("/api/v1/config", headers=_headers("admin-token"))
            assert secret.status_code == 200
            assert all("api_key" not in item["key"].lower() for item in secret.json()["data"]["items"])
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_openapi_operation_ids_are_unique() -> None:
    """回归锁：全 schema operationId 唯一且零 Duplicate 警告。

    2026-09-18 曾因 platform 路由（真数据 /api/v1/traces，先注册）与 v1 stub
    /traces 同 name+path+method 撞出 ``traces_api_v1_traces_get``，FastAPI 发
    Duplicate Operation ID 警告且 schema 覆写真端点；v1 stub 现显式
    ``operation_id="traces_stub_api_v1_traces_get"``。
    """
    tmp_path = _test_dir()
    app = create_control_plane_app(
        SimpleNamespace(
            **{
                **_config(tmp_path, admin="admin-token", super_admin="root-token").__dict__,
                "bot_control_plane_events_db": str(tmp_path / "events.sqlite3"),
                "bot_control_plane_actions_db": str(tmp_path / "actions.sqlite3"),
                "bot_control_plane_platform_db": str(tmp_path / "platform.sqlite3"),
            }
        ),
        audit_store=ControlPlaneAuditStore(str(tmp_path / "audit.sqlite3")),
        channel_health_store=object(),
    )
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            schema = app.openapi()
        duplicate_warnings = [
            str(item.message)
            for item in caught
            if "Duplicate Operation ID" in str(item.message)
        ]
        assert duplicate_warnings == []
        operation_ids = [
            operation["operationId"]
            for path in schema["paths"].values()
            for operation in path.values()
            if isinstance(operation, dict) and "operationId" in operation
        ]
        assert operation_ids
        assert len(operation_ids) == len(set(operation_ids))
        # 存活端点（后注册的 v1 stub 覆写 schema 同 path+method 条目）可寻址。
        assert "traces_stub_api_v1_traces_get" in operation_ids
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)
