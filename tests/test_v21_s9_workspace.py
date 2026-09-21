"""S9 席：Workspace 服务离线回归（核心要求 §九；V21-WORKSPACE-001）。

覆盖：sandbox 隔离（独立 session/Prompt、模拟发送、不写生产店）、
real_session 超管门+只读脱敏上下文+确认门、真实发送端口缺失时 send
诚实 503 not_wired 且不消费确认、消息变更使旧确认失效、审计 trail+trace。
全离线：生成器/适配器均为注入的 fake，只写 tmp 库。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from plugins.bot_unified_runtime.control_plane import create_control_plane_app
from plugins.bot_unified_runtime.control_plane.audit import ControlPlaneAuditStore
from plugins.bot_unified_runtime.control_plane.auth import hash_token
from plugins.bot_unified_runtime.control_plane.services import ControlServiceError
from plugins.bot_unified_runtime.control_plane.workspaces import (
    WorkspaceService,
    WorkspaceSettings,
)

ADMIN = {"Authorization": "Bearer s9-ws-admin"}
ROOT = {"Authorization": "Bearer s9-ws-root"}

ADMIN_P = SimpleNamespace(subject="admin-a", roles=("admin",))
ROOT_P = SimpleNamespace(subject="root", roles=("super_admin", "admin"))


class RecorderGenerator:
    """sandbox 生成器 fake：记录 scope，返回固定回复。"""

    def __init__(self) -> None:
        self.scopes: list[dict[str, Any]] = []

    async def __call__(self, scope: dict[str, Any]) -> dict[str, Any]:
        self.scopes.append(scope)
        return {"reply": "sandbox-reply", "model_id": "static", "latency_ms": 1}


class RealContextAdapter:
    """real_session 只读适配器 fake：只提供 context+generate，**无 deliver 端口**。"""

    def __init__(self) -> None:
        self.context_calls: list[str] = []
        self.generate_scopes: list[dict[str, Any]] = []

    async def context(self, session_id: str) -> list[dict[str, Any]]:
        self.context_calls.append(session_id)
        return [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "Bearer sk-production-secret-value"},
        ]

    async def generate(self, scope: dict[str, Any]) -> dict[str, Any]:
        self.generate_scopes.append(scope)
        return {"reply": "real-preview-reply", "prompt": "MUST-NOT-LEAK-PROMPT"}


class FullRealAdapter(RealContextAdapter):
    async def deliver(self, scope: dict[str, Any]) -> dict[str, Any]:
        return {"state": "queued"}


@pytest.fixture
def tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.domains.chat_reply.llm_engine.channel_health.get_channel_health_store",
        lambda db_path="": SimpleNamespace(snapshot=None),
    )
    return tmp_path


def _config(tmp_path) -> SimpleNamespace:
    return SimpleNamespace(
        bot_control_plane_enabled=True,
        bot_control_plane_token_sha256=hash_token("s9-ws-admin"),
        bot_control_plane_super_admin_token_sha256=hash_token("s9-ws-root"),
        bot_runtime_settings_dir=str(tmp_path / "settings"),
        bot_control_plane_config_db=str(tmp_path / "config.sqlite3"),
        bot_runtime_settings_file=str(tmp_path / "settings.json"),
        bot_control_plane_features_file=str(tmp_path / "features.json"),
        bot_timezone="UTC",
    )


def _app(tmp_path, service):
    return create_control_plane_app(
        _config(tmp_path), workspace_service=service,
        audit_store=ControlPlaneAuditStore(str(tmp_path / "audit.sqlite3")),
        channel_health_store=object(),
    )


def test_sandbox_isolation_independent_session_and_simulated_send(tmp):
    generator = RecorderGenerator()
    service = WorkspaceService(tmp / "ws.sqlite3", sandbox_generator=generator)

    ws = service.create(WorkspaceSettings(mode="sandbox"), principal=ROOT_P, request_id="req_" + "a" * 12)
    wid = ws["workspace_id"]
    service.message(wid, "BOT_TOKEN=sk-sandbox-secret and normal text",
                    expected_version=0, principal=ROOT_P, request_id="req_" + "b" * 12)
    preview = asyncio.run(service.preview(wid, expected_version=1, principal=ROOT_P,
                                          request_id="req_" + "c" * 12))
    assert preview["artifact"]["reply"] == "sandbox-reply"
    assert preview["confirmation_token"]

    # 隔离：scope 只有工作区值对象；test_session 与生产会话键空间隔离。
    scope = generator.scopes[0]
    assert scope["test_session_id"].startswith("test_")
    assert scope["settings"]["session_id"] is None
    assert set(scope) <= {"test_session_id", "settings", "messages"}
    # 消息内容脱敏后落库（不存明文密钥形态）。
    stored = service.messages(wid, principal=ROOT_P)[0]["content"]
    assert "sk-sandbox-secret" not in stored

    sent = asyncio.run(service.send(wid, expected_version=preview["version"],
                                    confirmation_token=preview["confirmation_token"],
                                    principal=ROOT_P, request_id="req_" + "d" * 12,
                                    idempotency_key="run-1"))
    assert sent["receipt"]["state"] == "simulated"  # 只模拟发送
    roles = service.messages(wid, principal=ROOT_P)
    assert roles[-1]["role"] == "assistant"


def test_real_session_requires_super_admin_and_readonly_redacted_context(tmp):
    adapter = RealContextAdapter()
    service = WorkspaceService(tmp / "ws.sqlite3", sandbox_generator=RecorderGenerator(),
                               real_adapter=adapter)

    with pytest.raises(ControlServiceError) as excinfo:
        service.create(WorkspaceSettings(mode="real_session", session_id="prod-1"),
                       principal=ADMIN_P, request_id="req_" + "a" * 12)
    assert excinfo.value.status_code == 403  # 仅 super_admin

    ws = service.create(WorkspaceSettings(mode="real_session", session_id="prod-1"),
                        principal=ROOT_P, request_id="req_" + "b" * 12)
    service.message(ws["workspace_id"], "please continue", expected_version=0,
                    principal=ROOT_P, request_id="req_" + "c" * 12)
    preview = asyncio.run(service.preview(ws["workspace_id"], expected_version=1,
                                          principal=ROOT_P, request_id="req_" + "d" * 12))
    # 只读脱敏真实上下文：prompt 不回传、密钥形态打码。
    assert adapter.context_calls == ["prod-1"]
    assert "prompt" not in preview["artifact"]
    assert "sk-production-secret-value" not in str(preview["artifact"])


def test_real_session_send_without_deliver_port_is_honest_not_wired(tmp):
    adapter = RealContextAdapter()  # 无 deliver
    service = WorkspaceService(tmp / "ws.sqlite3", sandbox_generator=RecorderGenerator(),
                               real_adapter=adapter)

    ws = service.create(WorkspaceSettings(mode="real_session", session_id="prod-9"),
                        principal=ROOT_P, request_id="req_" + "a" * 12)
    wid = ws["workspace_id"]
    service.message(wid, "hi", expected_version=0, principal=ROOT_P, request_id="req_" + "b" * 12)
    preview = asyncio.run(service.preview(wid, expected_version=1, principal=ROOT_P,
                                          request_id="req_" + "c" * 12))
    with pytest.raises(ControlServiceError) as excinfo:
        asyncio.run(service.send(wid, expected_version=preview["version"],
                                 confirmation_token=preview["confirmation_token"],
                                 principal=ROOT_P, request_id="req_" + "d" * 12,
                                 idempotency_key="send-1"))
    assert excinfo.value.status_code == 503
    assert excinfo.value.code == "not_wired"

    # 确认未被消费：同 token 再次 send（新幂等键）仍走到 not_wired 而非 confirmation_required。
    with pytest.raises(ControlServiceError) as excinfo2:
        asyncio.run(service.send(wid, expected_version=preview["version"],
                                 confirmation_token=preview["confirmation_token"],
                                 principal=ROOT_P, request_id="req_" + "e" * 12,
                                 idempotency_key="send-2"))
    assert excinfo2.value.code == "not_wired"
    data = service.get(wid, principal=ROOT_P)
    assert data["status"] == "idle"  # 未进入 sending 态

    # 对照组：带 deliver 端口的适配器走真实发送并拿到 queued 回执。
    full_service = WorkspaceService(tmp / "ws-full.sqlite3",
                                    sandbox_generator=RecorderGenerator(), real_adapter=FullRealAdapter())
    ws2 = full_service.create(WorkspaceSettings(mode="real_session", session_id="prod-9"),
                              principal=ROOT_P, request_id="req_" + "f" * 12)
    full_service.message(ws2["workspace_id"], "hi", expected_version=0,
                         principal=ROOT_P, request_id="req_" + "g" * 12)
    preview2 = asyncio.run(full_service.preview(ws2["workspace_id"], expected_version=1,
                                                principal=ROOT_P, request_id="req_" + "h" * 12))
    sent = asyncio.run(full_service.send(ws2["workspace_id"], expected_version=preview2["version"],
                                         confirmation_token=preview2["confirmation_token"],
                                         principal=ROOT_P, request_id="req_" + "i" * 12,
                                         idempotency_key="send-1"))
    assert sent["receipt"]["state"] == "queued"


def test_real_session_create_without_adapter_is_honest(tmp):
    service = WorkspaceService(tmp / "ws.sqlite3", sandbox_generator=RecorderGenerator())
    with pytest.raises(ControlServiceError) as excinfo:
        service.create(WorkspaceSettings(mode="real_session", session_id="prod-1"),
                       principal=ROOT_P, request_id="req_" + "a" * 12)
    assert excinfo.value.status_code == 503


def test_message_change_invalidates_previous_confirmation(tmp):
    service = WorkspaceService(tmp / "ws.sqlite3", sandbox_generator=RecorderGenerator())
    ws = service.create(WorkspaceSettings(mode="sandbox"), principal=ROOT_P, request_id="req_" + "a" * 12)
    wid = ws["workspace_id"]
    service.message(wid, "one", expected_version=0, principal=ROOT_P, request_id="req_" + "b" * 12)
    preview = asyncio.run(service.preview(wid, expected_version=1, principal=ROOT_P,
                                          request_id="req_" + "c" * 12))
    # 新消息使旧确认失效（preview 被清空、版本推进）。
    bumped = service.message(wid, "two", expected_version=preview["version"], principal=ROOT_P,
                             request_id="req_" + "d" * 12)
    with pytest.raises(ControlServiceError) as excinfo:
        asyncio.run(service.send(wid, expected_version=bumped["version"],
                                 confirmation_token=preview["confirmation_token"],
                                 principal=ROOT_P, request_id="req_" + "e" * 12,
                                 idempotency_key="late-1"))
    assert excinfo.value.code == "confirmation_required"


def test_workspace_http_rbac_audit_and_trace(tmp):
    service = WorkspaceService(tmp / "ws.sqlite3", sandbox_generator=RecorderGenerator())
    with TestClient(_app(tmp, service), base_url="http://127.0.0.1:8742") as client:
        denied = client.get("/api/v1/workspaces", headers=ADMIN)
        assert denied.status_code == 403  # 读令牌不可入工作区（写依赖=超管）

        created = client.post("/api/v1/workspaces", headers=ROOT, json={"mode": "sandbox"})
        assert created.status_code == 200
        payload = created.json()
        assert payload["meta"]["trace_id"].startswith("trace_")
        meta = payload["data"]
        base = "/api/v1/workspaces/" + meta["workspace_id"]

        added = client.post(base + "/messages", headers=ROOT, json={"content": "hello", "expected_version": 0})
        assert added.status_code == 200
        preview = client.post(base + "/preview", headers=ROOT, json={"expected_version": 1}).json()["data"]
        sent = client.post(base + "/send", headers=ROOT, json={
            "expected_version": preview["version"], "confirmation_token": preview["confirmation_token"],
            "idempotency_key": "http-1"})
        assert sent.status_code == 200 and sent.json()["data"]["receipt"]["state"] == "simulated"

        audit = client.get(base + "/audit", headers=ROOT).json()["data"]["items"]
        operations = [row["operation"] for row in audit]
        assert {"created", "message_added", "preview_started", "preview_ready", "send_simulated"} <= set(operations)
        assert all(row["request_id"].startswith("req_") for row in audit)
