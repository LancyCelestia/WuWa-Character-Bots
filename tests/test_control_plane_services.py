"""Shared feature service and v1 transport regression contracts."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from plugins.bot_unified_runtime.control_plane import create_control_plane_app
from plugins.bot_unified_runtime.control_plane.audit import ControlPlaneAuditStore
from plugins.bot_unified_runtime.control_plane.auth import Principal, hash_token
from plugins.bot_unified_runtime.control_plane.features import FeatureStateStore


@pytest.fixture
def client(tmp_path: Path):
    config = SimpleNamespace(
        bot_control_plane_enabled=True,
        bot_control_plane_token_sha256=hash_token("reader"),
        bot_control_plane_super_admin_token_sha256=hash_token("writer"),
        bot_control_plane_features_file=str(tmp_path / "features.json"),
        bot_runtime_settings_file=str(tmp_path / "settings.json"),
        bot_timezone="UTC",
    )
    audit = ControlPlaneAuditStore(str(tmp_path / "audit.sqlite3"))
    app = create_control_plane_app(config, audit_store=audit, channel_health_store=object())
    with TestClient(app, base_url="http://127.0.0.1:8742", raise_server_exceptions=False) as result:
        yield result
    audit.close()


def headers(token="writer"):
    return {"Authorization": f"Bearer {token}"}


def test_service_enforces_roles_without_http(tmp_path):
    from plugins.bot_unified_runtime.control_plane.services import (
        ControlServiceError,
        FeatureControlService,
    )
    service = FeatureControlService(FeatureStateStore(tmp_path / "features.json"))
    with pytest.raises(ControlServiceError) as failure:
        service.change("weather", False, principal=Principal("admin"), expected_version=0)
    assert failure.value.code == "forbidden"
    result = service.change("weather", False, principal=Principal("root", ("super_admin",)), expected_version=0, request_id="req_test")
    assert result["state"]["version"] == 1
    assert service.audit("weather")[0]["request_id"] == "req_test"


@pytest.mark.parametrize("path,token,status", [
    ("/api/v1/features", "reader", 200),
    ("/api/v1/features", "writer", 200),
    ("/api/v1/features/does-not-exist", "reader", 404),
    ("/api/v1/features", "invalid", 401),
    ("/api/v1/does-not-exist", "reader", 404),
])
def test_v1_envelope_and_request_id(client, path, token, status):
    response = client.get(path, headers=headers(token))
    assert response.status_code == status
    body = response.json()
    assert body["meta"]["schema_version"] == "v1"
    assert body["meta"]["request_id"] == response.headers["X-Request-ID"]
    if status != 200:
        assert body["data"] is None
        assert body["error"]["request_id"] == body["meta"]["request_id"]
        assert body["error"]["retryable"] is False


@pytest.mark.parametrize("payload", [{}, {"expected_version": True}, {"expected_version": "0"}, {"expected_version": -1}, {"expected_version": 0, "other": "secret"}])
def test_invalid_mutation_is_rejected_and_not_echoed(client, payload):
    response = client.post("/api/v1/features/weather/disable", json=payload, headers=headers())
    assert response.status_code == 422
    assert response.json()["meta"]["schema_version"] == "v1"
    assert "secret" not in response.text


def test_reset_preserves_conflict_detection(client):
    base = "/api/v1/features/weather/"
    first = client.post(base + "disable", json={"expected_version": 0}, headers=headers())
    assert first.status_code == 200
    reset = client.post(base + "reset", json={"expected_version": 1}, headers=headers())
    assert reset.json()["data"]["state"]["version"] == 2
    stale = client.post(base + "enable", json={"expected_version": 0}, headers=headers())
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "version_conflict"


def test_preview_does_not_mutate(client):
    response = client.post("/api/v1/features/weather/preview", json={"enabled": False, "expected_version": 0}, headers=headers())
    assert response.status_code == 200
    assert "bot.plugin.weather.command.forecast" in response.json()["data"]["affected_ids"]
    state = client.get("/api/v1/features/weather/state", headers=headers("reader"))
    assert state.json()["data"]["version"] == 0
    assert state.json()["data"]["effective_enabled"] is True


def test_schema_is_authenticated_and_static_route_is_not_shadowed(client):
    schema = client.get("/api/v1/openapi.json", headers=headers())
    assert schema.status_code == 200
    assert "/api/v1/features/{feature_id}/preview" in schema.json()["data"]["paths"]
    assert client.get("/api/v1/openapi.json").status_code == 401
    changes = client.get("/api/v1/config/changes", headers=headers())
    assert changes.status_code == 503  # not implemented, never a fake empty history


def test_unimplemented_workspace_does_not_claim_creation(client):
    response = client.post("/api/v1/workspaces", json={"mode": "sandbox"}, headers=headers())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "workspace_unavailable"

def test_v1_host_guard_and_method_errors_use_envelope(client):
    for response in (
        client.get("/api/v1/features", headers={**headers(), "Host": "evil.invalid"}),
        client.delete("/api/v1/features", headers=headers()),
    ):
        assert response.status_code in (400, 405)
        assert response.json()["meta"]["request_id"] == response.headers["X-Request-ID"]
        assert response.json()["data"] is None


def test_v1_mutation_audit_has_actor_and_same_request_id(client):
    response = client.post("/api/v1/features/weather/disable", json={"expected_version": 0}, headers=headers())
    assert response.status_code == 200
    rows = client.get("/api/v1/features/weather/audit", headers=headers()).json()["data"]["items"]
    assert rows[-1]["actor"] == "bearer-super-admin"
    assert rows[-1]["request_id"] == response.headers["X-Request-ID"]
    assert rows[-1]["before"]["effective_enabled"] is True
    assert rows[-1]["after"]["effective_enabled"] is False


def test_distinct_admin_tokens_are_required(tmp_path):
    config = SimpleNamespace(
        bot_control_plane_enabled=True,
        bot_control_plane_token_sha256=hash_token("same"),
        bot_control_plane_super_admin_token_sha256=hash_token("same"),
        bot_control_plane_features_file=str(tmp_path / "features.json"),
    )
    audit = ControlPlaneAuditStore(str(tmp_path / "audit.sqlite3"))
    app = create_control_plane_app(config, audit_store=audit, channel_health_store=object())
    try:
        with TestClient(app, base_url="http://127.0.0.1:8742") as test_client:
            assert test_client.get("/api/v1/features", headers=headers("same")).status_code == 200
            assert test_client.post("/api/v1/features/weather/disable", json={"expected_version": 0}, headers=headers("same")).status_code == 503
    finally:
        audit.close()

def test_openapi_declares_bearer_and_strict_feature_mutation(client):
    schema = client.get("/api/v1/openapi.json", headers=headers()).json()["data"]
    assert schema["components"]["securitySchemes"]["ControlPlaneBearer"]["scheme"] == "bearer"
    operation = schema["paths"]["/api/v1/features/{feature_id}/disable"]["post"]
    assert operation["security"] == [{"ControlPlaneBearer": []}]
    payload = schema["components"]["schemas"]["FeatureChangePayload"]
    assert payload["required"] == ["expected_version"]
    assert payload["additionalProperties"] is False

@pytest.mark.parametrize("method,args", [("list_features", ()), ("tree", ()), ("children", ("bot",))])
def test_aggregate_queries_use_one_locked_snapshot(tmp_path, monkeypatch, method, args):
    from plugins.bot_unified_runtime.control_plane.services import FeatureControlService
    store = FeatureStateStore(tmp_path / "features.json")
    service = FeatureControlService(store)
    original = store.list_states
    calls = []
    def snapshot():
        calls.append(True)
        return original()
    monkeypatch.setattr(store, "list_states", snapshot)
    assert getattr(service, method)(*args)
    assert len(calls) == 1

def test_feature_openapi_includes_typed_response_contract(client):
    schema = client.get("/api/v1/openapi.json", headers=headers()).json()["data"]
    assert "FeatureItem" in schema["components"]["schemas"]
    assert "FeatureState" in schema["components"]["schemas"]
    assert "graph_revision" in schema["components"]["schemas"]["FeatureState"]["properties"]

def test_protocol_discovery_does_not_advertise_unimplemented_services(client):
    response = client.get("/api/v1/protocol", headers=headers())
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["runtime_binding"] == "storage_only"
    assert data["services"]["features"]["available"] is True
    assert data["services"]["workspaces"]["available"] is False
    # V2.1 批次已默认装配 ControlActionService（_app.py 工厂内建 13 动作 +
    # api/actions.py 路由），actions 由未实现转为已实现 → 诚实上报 available=True。
    assert data["services"]["actions"]["available"] is True
