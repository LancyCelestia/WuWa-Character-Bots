"""隔离工作区：不加载生产上下文、不直接触碰真实发送器。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from plugins.bot_unified_runtime.control_plane.auth import Principal
from plugins.bot_unified_runtime.control_plane.services import ControlServiceError
from plugins.bot_unified_runtime.control_plane.workspaces import (
    WorkspaceService,
    WorkspaceSettings,
)

ADMIN = Principal("tester", ("super_admin",))
OTHER = Principal("other", ("super_admin",))
READ = Principal("reader", ("admin",))


@pytest.fixture
def ws(tmp_path):
    generator = AsyncMock(return_value={"reply": "我在这里。", "prompt": "test prompt", "context": [], "model_calls": []})
    real = SimpleNamespace(context=AsyncMock(), generate=AsyncMock(), deliver=AsyncMock())
    service = WorkspaceService(tmp_path / "workspaces.sqlite3", sandbox_generator=generator, real_adapter=real)
    return service, generator, real


def create(service, **kwargs):
    return service.create(WorkspaceSettings(**kwargs), principal=ADMIN, request_id="req_create")


def test_default_workspace_is_isolated_persistent_and_owned(ws):
    service, generator, real = ws
    item = create(service)
    assert item["settings"]["mode"] == "sandbox"
    assert item["test_session_id"].startswith("test_")
    peer = WorkspaceService(service.path)
    assert peer.get(item["workspace_id"], principal=ADMIN) == item
    assert peer.list(principal=OTHER) == ()
    with pytest.raises(ControlServiceError) as error:
        peer.get(item["workspace_id"], principal=OTHER)
    assert error.value.status_code == 404
    with pytest.raises(ControlServiceError):
        service.create(WorkspaceSettings(), principal=READ, request_id="req_denied")
    generator.assert_not_awaited()
    real.deliver.assert_not_awaited()


def test_message_cas_and_reset_clear_history_and_keep_audit(ws):
    service, _, _ = ws
    item = create(service)
    wid = item["workspace_id"]
    updated = service.message(wid, "你好", expected_version=0, principal=ADMIN, request_id="req_message")
    assert updated["version"] == 1
    with pytest.raises(ControlServiceError) as conflict:
        service.message(wid, "stale", expected_version=0, principal=ADMIN, request_id="req_stale")
    assert conflict.value.code == "version_conflict"
    assert len(service.messages(wid, principal=ADMIN)) == 1
    assert "你好" not in repr(service.audit(wid, principal=ADMIN))
    service.reset(wid, expected_version=1, principal=ADMIN, request_id="req_reset")
    assert service.messages(wid, principal=ADMIN) == ()


def test_sandbox_preview_and_send_use_only_isolated_ports(ws):
    service, generator, real = ws
    item = create(service)
    wid = item["workspace_id"]
    service.message(wid, "你好", expected_version=0, principal=ADMIN, request_id="req_message")
    preview = asyncio.run(service.preview(wid, expected_version=1, principal=ADMIN, request_id="req_preview"))
    assert preview["artifact"]["reply"] == "我在这里。"
    context = generator.call_args.args[0]
    assert context["test_session_id"] == item["test_session_id"]
    assert context["messages"] == [{"role": "user", "content": "你好"}]
    sent = asyncio.run(service.send(wid, expected_version=preview["version"], confirmation_token=preview["confirmation_token"],
        principal=ADMIN, request_id="req_send", idempotency_key="once"))
    assert sent["receipt"]["state"] == "simulated"
    repeated = asyncio.run(service.send(wid, expected_version=preview["version"], confirmation_token=preview["confirmation_token"],
        principal=ADMIN, request_id="req_retry", idempotency_key="once"))
    assert repeated["receipt"] == sent["receipt"]
    real.context.assert_not_awaited()
    real.generate.assert_not_awaited()
    real.deliver.assert_not_awaited()


def test_stale_preview_cannot_be_sent_after_new_message(ws):
    service, _, _ = ws
    wid = create(service)["workspace_id"]
    preview = asyncio.run(service.preview(wid, expected_version=0, principal=ADMIN, request_id="req_preview"))
    service.message(wid, "改一下", expected_version=preview["version"], principal=ADMIN, request_id="req_change")
    with pytest.raises(ControlServiceError):
        asyncio.run(service.send(wid, expected_version=preview["version"], confirmation_token=preview["confirmation_token"],
            principal=ADMIN, request_id="req_send", idempotency_key="once"))


def test_generation_failure_keeps_workspace_usable_and_hides_exception(ws):
    service, generator, _ = ws
    wid = create(service)["workspace_id"]
    generator.side_effect = RuntimeError("Bearer should-not-leak")
    with pytest.raises(ControlServiceError) as error:
        asyncio.run(service.preview(wid, expected_version=0, principal=ADMIN, request_id="req_preview"))
    assert "should-not-leak" not in str(error.value)
    item = service.get(wid, principal=ADMIN)
    assert item["status"] == "idle"
    assert len(service.messages(wid, principal=ADMIN)) == 0
    service.message(wid, "retry", expected_version=item["version"], principal=ADMIN, request_id="req_retry")


def test_expired_workspace_purges_raw_content_but_retains_summary_audit(ws):
    service, _, _ = ws
    service.clock = lambda: 1000
    wid = create(service)["workspace_id"]
    service.message(wid, "short-lived", expected_version=0, principal=ADMIN, request_id="req_text")
    service.clock = lambda: 1000 + service.ttl_seconds + 1
    assert service.prune() == 1
    with pytest.raises(ControlServiceError):
        service.get(wid, principal=ADMIN)
    assert service.audit(wid, principal=ADMIN)
    assert "short-lived" not in repr(service.audit(wid, principal=ADMIN))


def test_real_session_requires_confirmation_and_delivery_port(ws):
    service, _, real = ws
    real.context.return_value = [{"summary": "脱敏真实上下文"}]
    real.generate.return_value = {"reply": "预览内容", "context": [], "model_calls": []}
    real.deliver.return_value = {"state": "queued", "receipt_id": "delivery_1"}
    wid = create(service, mode="real_session", session_id="session_1")["workspace_id"]
    preview = asyncio.run(service.preview(wid, expected_version=0, principal=ADMIN, request_id="req_preview"))
    real.deliver.assert_not_awaited()
    with pytest.raises(ControlServiceError):
        asyncio.run(service.send(wid, expected_version=preview["version"], confirmation_token="wrong", principal=ADMIN,
            request_id="req_bad", idempotency_key="once"))
    result = asyncio.run(service.send(wid, expected_version=preview["version"], confirmation_token=preview["confirmation_token"], principal=ADMIN,
        request_id="req_send", idempotency_key="once"))
    assert result["receipt"]["state"] == "queued"
    assert "prompt" not in preview["artifact"]
    assert real.deliver.await_count == 1

def test_idempotency_key_cannot_hide_different_send_request(ws):
    service, _, _ = ws
    wid = create(service)["workspace_id"]
    preview = asyncio.run(service.preview(wid, expected_version=0, principal=ADMIN, request_id="req_preview"))
    kwargs = {"expected_version": preview["version"], "confirmation_token": preview["confirmation_token"],
        "principal": ADMIN, "request_id": "req_send", "idempotency_key": "once"}
    asyncio.run(service.send(wid, **kwargs))
    kwargs["confirmation_token"] = "different"
    with pytest.raises(ControlServiceError) as error:
        asyncio.run(service.send(wid, **kwargs))
    assert error.value.code == "idempotency_conflict"


def test_provider_failure_after_real_send_is_not_retried(ws):
    service, _, real = ws
    real.context.return_value = []
    real.generate.return_value = {"reply": "preview"}
    real.deliver.side_effect = TimeoutError("private details")
    wid = create(service, mode="real_session", session_id="session_1")["workspace_id"]
    preview = asyncio.run(service.preview(wid, expected_version=0, principal=ADMIN, request_id="req_preview"))
    kwargs = {"expected_version": preview["version"], "confirmation_token": preview["confirmation_token"],
        "principal": ADMIN, "request_id": "req_send", "idempotency_key": "once"}
    with pytest.raises(ControlServiceError) as error:
        asyncio.run(service.send(wid, **kwargs))
    assert error.value.code == "workspace_send_unknown"
    assert asyncio.run(service.send(wid, **kwargs))["receipt"]["state"] == "unknown"
    real.deliver.assert_awaited_once()


def test_expiry_physically_removes_plaintext_and_audit_rejects_arbitrary_text(ws):
    service, _, _ = ws
    with pytest.raises(ControlServiceError):
        service.create(WorkspaceSettings(), principal=ADMIN, request_id="Bearer credential")
    service.clock = lambda: 1000
    wid = create(service)["workspace_id"]
    marker = "unique-expiring-private-content-134"
    service.message(wid, marker, expected_version=0, principal=ADMIN, request_id="req_text")
    assert marker.encode() in service.path.read_bytes()
    service.clock = lambda: 1000 + service.ttl_seconds + 1
    service.prune()
    assert marker.encode() not in service.path.read_bytes()


def test_busy_workspace_cannot_be_mutated_while_generating(ws):
    service, generator, _ = ws
    wid = create(service)["workspace_id"]
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        async def generating(_scope):
            started.set()
            await release.wait()
            return {"reply": "done"}
        generator.side_effect = generating
        task = asyncio.create_task(service.preview(wid, expected_version=0, principal=ADMIN, request_id="req_preview"))
        await started.wait()
        with pytest.raises(ControlServiceError) as error:
            service.reset(wid, expected_version=1, principal=ADMIN, request_id="req_reset")
        assert error.value.code == "workspace_busy"
        release.set()
        await task
    asyncio.run(scenario())

def test_workspace_preserves_expected_resource_errors(ws):
    service, generator, _ = ws
    generator.side_effect = ControlServiceError("resource_not_found", "资料未登记。", 404)
    wid = create(service)["workspace_id"]
    with pytest.raises(ControlServiceError) as error:
        asyncio.run(service.preview(wid, expected_version=0, principal=ADMIN, request_id="req_resource"))
    assert error.value.code == "resource_not_found" and error.value.status_code == 404
    assert service.get(wid, principal=ADMIN)["status"] == "idle"


def test_create_uses_configured_persona_only_when_request_omits_selection(tmp_path):
    service = WorkspaceService(tmp_path / "defaults.sqlite3", default_persona_profile_id="configured")
    assert create(service)["settings"]["persona_profile_id"] == "configured"
    assert create(service, persona_profile_id="explicit")["settings"]["persona_profile_id"] == "explicit"
