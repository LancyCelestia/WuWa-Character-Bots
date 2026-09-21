"""工作区 HTTP 权限、版本、隔离和确认协议。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from plugins.bot_unified_runtime.control_plane import create_control_plane_app
from plugins.bot_unified_runtime.control_plane.audit import ControlPlaneAuditStore
from plugins.bot_unified_runtime.control_plane.auth import hash_token
from plugins.bot_unified_runtime.control_plane.workspaces import WorkspaceService

ROOT = {"Authorization": "Bearer workspace-root"}
READ = {"Authorization": "Bearer workspace-read"}


@pytest.fixture
def api(tmp_path):
    service = WorkspaceService(tmp_path / "workspaces.sqlite3", sandbox_generator=AsyncMock(return_value={"reply": "reply"}))
    cfg = SimpleNamespace(bot_control_plane_enabled=True,
        bot_control_plane_token_sha256=hash_token("workspace-read"),
        bot_control_plane_super_admin_token_sha256=hash_token("workspace-root"),
        bot_runtime_settings_dir=str(tmp_path / "settings"),
        bot_control_plane_config_db=str(tmp_path / "config.sqlite3"),
        bot_runtime_settings_file=str(tmp_path / "settings.json"),
        bot_control_plane_features_file=str(tmp_path / "features.json"), bot_timezone="UTC")
    app = create_control_plane_app(cfg, workspace_service=service,
        audit_store=ControlPlaneAuditStore(str(tmp_path / "audit.sqlite3")), channel_health_store=object())
    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        yield client


def test_sandbox_http_flow_and_schema(api):
    manifest = api.get("/api/v1/protocol", headers=ROOT).json()["data"]["services"]["workspaces"]
    assert manifest["available"] and manifest["sandbox_generation"]
    assert manifest["real_session"] is False
    created = api.post("/api/v1/workspaces", headers=ROOT, json={})
    assert created.status_code == 200
    item = created.json()["data"]
    base = "/api/v1/workspaces/" + item["workspace_id"]
    added = api.post(base + "/messages", headers=ROOT, json={"content": "test", "expected_version": 0})
    assert added.status_code == 200
    assert api.get(base + "/messages", headers=ROOT).json()["data"]["items"][0]["content"] == "test"
    preview = api.post(base + "/preview", headers=ROOT, json={"expected_version": 1}).json()["data"]
    sent = api.post(base + "/send", headers=ROOT, json={"expected_version": preview["version"], "confirmation_token": preview["confirmation_token"], "idempotency_key": "once"})
    assert sent.status_code == 200 and sent.json()["data"]["receipt"]["state"] == "simulated"
    version = sent.json()["data"]["version"]
    reset = api.post(base + "/reset", headers=ROOT, json={"expected_version": version})
    assert reset.status_code == 200
    assert api.get(base + "/messages", headers=ROOT).json()["data"]["items"] == []
    deleted = api.delete(base, headers=ROOT, params={"expected_version": reset.json()["data"]["version"]})
    assert deleted.status_code == 200
    assert api.get(base, headers=ROOT).status_code == 404
    assert api.get("/api/v1/workspaces", headers=ROOT).json()["data"]["items"] == []


def test_workspace_http_permissions_and_validation(api):
    assert api.get("/api/v1/workspaces", headers=READ).status_code == 403
    assert api.post("/api/v1/workspaces", headers=READ, json={}).status_code == 403
    for body in ({"mode": "sandbox", "session_id": "production"}, {"allow_external_tools": True}, {"shell": "ignored"}):
        result = api.post("/api/v1/workspaces", headers=ROOT, json=body)
        assert result.status_code == 422
        assert result.json()["error"]["code"] == "validation_error"
    assert api.post("/api/v1/workspaces", headers=ROOT, json={"mode": "real_session", "session_id": "real"}).status_code == 503
    schema = api.get("/api/v1/openapi.json", headers=ROOT).json()["data"]
    assert "/api/v1/workspaces/{workspace_id}/send" in schema["paths"]
    assert schema["components"]["schemas"]["WorkspaceSettings"]["additionalProperties"] is False
