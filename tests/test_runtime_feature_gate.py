"""能力状态必须在限流、幂等与执行之前阻断同步/异步主链。"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.contracts import (
    IncomingMessage,
    ReceiptState,
    SessionType,
)
from plugins.bot_unified_runtime.runtime.pipeline import RuntimePipeline
from plugins.bot_unified_runtime.sender import InMemorySendQueue


def test_disabled_feature_blocks_before_policy_or_capability():
    audit = InMemoryAuditLogger()
    calls = []
    pipeline = RuntimePipeline(
        send_queue=InMemorySendQueue(audit_logger=audit), audit_logger=audit,
        feature_gate=lambda message, capability: SimpleNamespace(allowed=False, reason="feature_disabled"),
    )
    def forbidden(*args):
        calls.append(args)
        raise AssertionError("disabled feature reached a side effect")
    pipeline.policy_evaluator = forbidden
    message = IncomingMessage(platform="qq", adapter="onebot", bot_id="b", sender_id="u", session_id="private:u", session_type=SessionType.PRIVATE, plain_text="天气")
    assert pipeline.handle(message, forbidden, "bot.weather").state == ReceiptState.BLOCKED
    assert asyncio.run(pipeline.handle_async(message, forbidden, "bot.weather")).state == ReceiptState.BLOCKED
    assert calls == []


def test_failed_feature_lookup_is_fail_closed():
    audit = InMemoryAuditLogger()
    def unavailable(*args):
        raise OSError("database unavailable")
    pipeline = RuntimePipeline(send_queue=InMemorySendQueue(audit_logger=audit), audit_logger=audit, feature_gate=unavailable)
    message = IncomingMessage(platform="qq", adapter="onebot", bot_id="b", sender_id="u", session_id="private:u", session_type=SessionType.PRIVATE, plain_text="hi")
    receipt = pipeline.handle(message, lambda *args: None, "bot.chat")
    assert receipt.state == ReceiptState.BLOCKED
    assert "database" not in receipt.public_message


def test_catalog_registers_all_declared_route_capabilities():
    from plugins.bot_unified_runtime.control_plane.features import FeatureRegistry
    from plugins.bot_unified_runtime.domains.ops.features.feature_catalog import (
        build_product_descriptors,
        capability_feature_bindings,
    )
    from plugins.bot_unified_runtime.runtime.capability_registry import (
        ROUTE_CAPABILITY_DECLARATIONS,
    )
    registry = FeatureRegistry(build_product_descriptors())
    bindings = capability_feature_bindings()
    for declaration in ROUTE_CAPABILITY_DECLARATIONS:
        if declaration.has_rule:
            assert registry.get(bindings[declaration.capability_id]).capability_id == declaration.capability_id

def test_feature_command_uses_service_and_super_admin(tmp_path):
    from plugins.bot_unified_runtime.control_plane.features import FeatureStateStore
    from plugins.bot_unified_runtime.control_plane.services import FeatureControlService
    from plugins.bot_unified_runtime.domains.ops.features.feature_catalog import (
        build_product_descriptors,
    )
    from plugins.bot_unified_runtime.domains.ops.features.feature_control import (
        build_feature_control_result,
    )
    store = FeatureStateStore(tmp_path / "state.json", descriptors=build_product_descriptors())
    service = FeatureControlService(store)
    rejected = build_feature_control_result(service, request_id="req_cmd_denied", actor_id="reader", actor_roles=["admin"], command_text="disable bot.plugin.weather")
    assert "forbidden" in rejected.audit_tags
    assert store.get("bot.plugin.weather").effective_enabled
    changed = build_feature_control_result(service, request_id="req_cmd", actor_id="root", actor_roles=["super_admin"], command_text="disable bot.plugin.weather")
    assert "审计" in changed.body
    assert not store.get("bot.plugin.weather").effective_enabled
    assert store.audit("bot.plugin.weather")[-1]["request_id"] == "req_cmd"


def test_unregistered_features_fail_closed_and_core_is_recoverable(tmp_path):
    from plugins.bot_unified_runtime.control_plane.features import FeatureStateStore
    from plugins.bot_unified_runtime.control_plane.services import FeatureControlService
    from plugins.bot_unified_runtime.domains.ops.features.feature_gate import (
        ProductFeatureGate,
    )
    service = FeatureControlService(FeatureStateStore(tmp_path / "state.json"))
    gate = ProductFeatureGate(service)
    assert not gate(None, "bot.not_registered").allowed
    assert gate(None, "bot.runtime").allowed

def test_api_sqlite_change_controls_separate_runtime_instance(tmp_path):
    from fastapi.testclient import TestClient

    from plugins.bot_unified_runtime.control_plane import create_control_plane_app
    from plugins.bot_unified_runtime.control_plane.audit import ControlPlaneAuditStore
    from plugins.bot_unified_runtime.control_plane.auth import hash_token
    from plugins.bot_unified_runtime.control_plane.factory import build_feature_service
    from plugins.bot_unified_runtime.domains.ops.features.feature_gate import (
        ProductFeatureGate,
    )
    config = SimpleNamespace(
        bot_control_plane_features_db=str(tmp_path / "features.sqlite3"),
        bot_control_plane_features_file=str(tmp_path / "legacy.json"),
        bot_control_plane_token_sha256=hash_token("reader"),
        bot_control_plane_super_admin_token_sha256=hash_token("root"),
    )
    service = build_feature_service(config)  # 独立实例，不共享API里的store内存
    app_audit = ControlPlaneAuditStore(str(tmp_path / "audit.sqlite3"))
    app = create_control_plane_app(config, audit_store=app_audit, channel_health_store=object())
    audit = InMemoryAuditLogger()
    pipeline = RuntimePipeline(send_queue=InMemorySendQueue(audit_logger=audit), audit_logger=audit, feature_gate=ProductFeatureGate(service))
    calls = []
    message = IncomingMessage(platform="qq", adapter="onebot", bot_id="b", sender_id="u", session_id="private:u", session_type=SessionType.PRIVATE, plain_text="天气", mentions_bot=True)
    try:
        with TestClient(app, base_url="http://127.0.0.1:8742") as client:
            headers = {"Authorization": "Bearer root"}
            missing_revision = client.post("/api/v1/features/weather/disable", headers=headers, json={"expected_version": 0})
            assert missing_revision.status_code == 422
            changed = client.post("/api/v1/features/weather/disable", headers=headers, json={"expected_version": 0, "expected_revision": 0})
            assert changed.status_code == 200
            assert changed.json()["data"]["state"]["graph_revision"] == 1
            receipt = pipeline.handle(message, lambda *args: calls.append(True), "bot.weather")
            assert receipt.state == ReceiptState.BLOCKED
            assert calls == []
            stale = client.post("/api/v1/features/chat/disable", headers=headers, json={"expected_version": 0, "expected_revision": 0})
            assert stale.status_code == 409  # 其他节点变化也使旧图快照失效
    finally:
        app_audit.close()

def test_app_mounts_event_service_and_shared_error_protocol(tmp_path):
    from fastapi.testclient import TestClient

    from plugins.bot_unified_runtime.control_plane import create_control_plane_app
    from plugins.bot_unified_runtime.control_plane.audit import ControlPlaneAuditStore
    from plugins.bot_unified_runtime.control_plane.auth import hash_token
    from plugins.bot_unified_runtime.control_plane.events import (
        RuntimeEventService,
        RuntimeLogEvent,
    )
    service = RuntimeEventService(tmp_path / "events.sqlite3")
    service.append(RuntimeLogEvent(source="bot", category="success", details={"request_id": "req_seed"}))
    config = SimpleNamespace(bot_control_plane_token_sha256=hash_token("read"), bot_control_plane_features_file=str(tmp_path / "features.json"))
    audit = ControlPlaneAuditStore(str(tmp_path / "audit.sqlite3"))
    app = create_control_plane_app(config, audit_store=audit, channel_health_store=object(), event_service=service)
    try:
        with TestClient(app, base_url="http://127.0.0.1:8742") as client:
            headers = {"Authorization": "Bearer read"}
            response = client.get("/api/v1/logs?source=bot", headers=headers)
            assert response.status_code == 200
            assert response.json()["data"]["items"][0]["category"] == "success"
            invalid = client.get("/api/v1/logs?category=invalid", headers=headers)
            assert invalid.status_code == 422
            assert invalid.json()["error"]["request_id"] == invalid.headers["X-Request-ID"]
            assert client.get("/api/v1/logs/stream").status_code == 401
    finally:
        audit.close()

def test_broken_feature_database_keeps_recovery_gate_available(tmp_path):
    import pytest

    from plugins.bot_unified_runtime.control_plane.factory import build_feature_service
    from plugins.bot_unified_runtime.control_plane.services import ControlServiceError
    from plugins.bot_unified_runtime.domains.ops.features.feature_gate import (
        ProductFeatureGate,
    )
    path = tmp_path / "broken.sqlite3"
    path.write_bytes(b"not a database")
    service = build_feature_service(SimpleNamespace(bot_control_plane_features_db=str(path)))
    assert ProductFeatureGate(service)(None, "bot.runtime").allowed
    with pytest.raises(ControlServiceError) as error:
        service.detail("weather")
    assert error.value.code == "feature_state_unavailable"

def test_config_api_and_command_share_live_consumers(tmp_path):
    from fastapi.testclient import TestClient

    from plugins.bot_unified_runtime.control_plane import create_control_plane_app
    from plugins.bot_unified_runtime.control_plane.audit import ControlPlaneAuditStore
    from plugins.bot_unified_runtime.control_plane.auth import hash_token
    from plugins.bot_unified_runtime.domains.ops.admin.runtime_admin import (
        build_runtime_admin_result,
    )
    from plugins.bot_unified_runtime.runtime.settings import (
        build_instance_settings_manager,
    )
    config = SimpleNamespace(
        bot_control_plane_config_db=str(tmp_path / "config.sqlite3"),
        bot_runtime_settings_dir=str(tmp_path / "settings"), bot_runtime_instance="default",
        bot_control_plane_features_file=str(tmp_path / "features.json"),
        bot_control_plane_token_sha256=hash_token("reader"),
        bot_control_plane_super_admin_token_sha256=hash_token("root"),
        bot_chat_temperature=0.2,
    )
    manager = build_instance_settings_manager(config)
    runtime_settings = manager.get("default")
    notifications = []
    runtime_settings.register_change_listener(lambda: notifications.append(True))
    audit = ControlPlaneAuditStore(str(tmp_path / "audit.sqlite3"))
    app = create_control_plane_app(config, audit_store=audit, channel_health_store=object(), settings_store=runtime_settings)
    try:
        with TestClient(app, base_url="http://127.0.0.1:8742") as client:
            headers = {"Authorization": "Bearer root"}
            response = client.post("/api/v1/config/BOT_CHAT_TEMPERATURE/set", headers=headers, json={"value": 0.7, "expected_version": 0})
            assert response.status_code == 200
            assert runtime_settings.get("BOT_CHAT_TEMPERATURE", config) == 0.7
            assert len(notifications) == 1
            result = build_runtime_admin_result(manager, "default", config, request_id="req_command", actor_id="owner", actor_roles=["super_admin"], command_text="set BOT_CHAT_TEMPERATURE 0.8")
            assert "已保存" in result.body
            assert len(notifications) == 2
            row = client.get("/api/v1/config/BOT_CHAT_TEMPERATURE", headers=headers).json()["data"]
            assert row["value"] == 0.8 and row["version"] == 2
            denied = build_runtime_admin_result(manager, "default", config, request_id="req_denied", actor_id="admin", actor_roles=["admin"], command_text="SeT BOT_CHAT_TEMPERATURE 0.9")
            assert "super_admin" in denied.body
            assert runtime_settings.get("BOT_CHAT_TEMPERATURE", config) == 0.8
            history = client.get("/api/v1/config/changes", headers=headers).json()["data"]["items"]
            assert history[-1]["actor"] == "owner"
            assert history[-1]["request_id"] == "req_command"
    finally:
        audit.close()

def test_main_ingress_capability_ids_are_registered():
    import ast
    from pathlib import Path

    from plugins.bot_unified_runtime.domains.ops.features.feature_catalog import (
        capability_feature_bindings,
    )
    source = Path(__file__).resolve().parents[1] / "plugins/bot_unified_runtime/__init__.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "capability_id" and isinstance(node.value, ast.Constant):
            ids.add(node.value.value)
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                and any(isinstance(target, ast.Name) and target.id == "capability_id" for target in node.targets)):
            ids.add(node.value.value)
    missing = {value for value in ids if isinstance(value, str) and value.startswith("bot.")} - set(capability_feature_bindings())
    assert not missing, f"入站声明了未登记能力：{sorted(missing)}"
