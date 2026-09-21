"""动作 HTTP 协议必须走公开服务面，并保持权限、版本和路由语义。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from plugins.bot_unified_runtime.control_plane import create_control_plane_app
from plugins.bot_unified_runtime.control_plane.actions import (
    ControlActionDescriptor,
    ControlActionService,
)
from plugins.bot_unified_runtime.control_plane.audit import ControlPlaneAuditStore
from plugins.bot_unified_runtime.control_plane.auth import hash_token

ROOT = {"Authorization": "Bearer root-test-token"}
READ = {"Authorization": "Bearer read-test-token"}


@pytest.fixture
def api(tmp_path):
    handler = AsyncMock(return_value={"status": "ok", "details": {}})
    service = ControlActionService(tmp_path / "actions.sqlite3", registrations=(
        (ControlActionDescriptor("diagnostics.snapshot", "诊断"), handler),
        (ControlActionDescriptor("resources.refresh", "刷新", confirmation_required=False), handler),
    ))
    config = SimpleNamespace(
        bot_control_plane_enabled=True,
        bot_control_plane_token_sha256=hash_token("read-test-token"),
        bot_control_plane_super_admin_token_sha256=hash_token("root-test-token"),
        bot_runtime_settings_dir=str(tmp_path / "settings"),
        bot_control_plane_config_db=str(tmp_path / "config.sqlite3"),
        bot_runtime_settings_file=str(tmp_path / "settings.json"),
        bot_control_plane_features_file=str(tmp_path / "features.json"),
        bot_timezone="UTC",
    )
    app = create_control_plane_app(config, action_service=service,
        audit_store=ControlPlaneAuditStore(str(tmp_path / "audit.sqlite3")), channel_health_store=object())
    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        yield client, service, handler


def test_catalog_and_manifest_reflect_injected_service(api):
    client, _, _ = api
    assert client.get("/api/v1/protocol", headers=READ).json()["data"]["services"]["actions"]["available"] is True
    items = client.get("/api/v1/actions", headers=READ).json()["data"]["items"]
    assert items[0]["version"] == 0
    assert client.get("/api/v1/actions/diagnostics.snapshot", headers=READ).json()["data"]["version"] == 0


def test_static_runs_route_is_not_shadowed(api):
    client, _, _ = api
    response = client.get("/api/v1/actions/runs", headers=READ)
    assert response.status_code == 200
    assert response.json()["data"]["items"] == []


def test_confirmation_conflict_status_and_success_idempotency(api):
    client, service, handler = api
    path = "/api/v1/actions/diagnostics.snapshot"
    body = {"expected_version": 0, "parameters": {}, "idempotency_key": "once"}
    missing = client.post(path + "/execute", headers=ROOT, json=body)
    assert missing.status_code == 409
    assert missing.json()["error"]["code"] == "confirmation_required"
    token = client.post(path + "/preview", headers=ROOT, json={"expected_version": 0}).json()["data"]["confirmation_token"]
    body["confirmation_token"] = token
    first = client.post(path + "/execute", headers=ROOT, json=body)
    assert first.status_code == 200
    run = first.json()["data"]
    assert run["state"] == "succeeded"
    assert client.post(path + "/execute", headers=ROOT, json=body).json()["data"]["run_id"] == run["run_id"]
    handler.assert_awaited_once()
    conflict = client.post(path + "/preview", headers=ROOT, json={"expected_version": 0})
    assert conflict.status_code == 409
    assert service.audit(run["run_id"])[-1]["state"] == "succeeded"


def test_unconfirmed_low_risk_action_and_unknown_action(api):
    client, _, _ = api
    response = client.post("/api/v1/actions/resources.refresh/execute", headers=ROOT,
        json={"expected_version": 0, "idempotency_key": "refresh"})
    assert response.status_code == 200
    missing = client.post("/api/v1/actions/shell.exec/preview", headers=ROOT, json={"expected_version": 0})
    assert missing.status_code == 404


@pytest.mark.parametrize("suffix", ["preview", "execute"])
def test_readers_cannot_mutate_actions(api, suffix):
    client, _, handler = api
    response = client.post("/api/v1/actions/diagnostics.snapshot/" + suffix, headers=READ,
        json={"expected_version": 0, "idempotency_key": "forbidden"})
    assert response.status_code == 403
    handler.assert_not_awaited()


def test_strict_payloads_and_cancel_does_not_ignore_parameters(api):
    client, _, handler = api
    for body in ({"expected_version": True}, {"expected_version": 0, "shell": "private"}):
        assert client.post("/api/v1/actions/diagnostics.snapshot/preview", headers=ROOT, json=body).status_code == 422
    response = client.post("/api/v1/actions/runs/nonexistent/cancel", headers=ROOT,
        json={"expected_version": 0, "parameters": {"ignored": True}})
    assert response.status_code == 422
    assert client.post("/api/v1/actions/runs/nonexistent/cancel", headers=ROOT,
        json={"expected_version": 0}).status_code == 404
    handler.assert_not_awaited()
