"""白名单动作：先持久化审计再执行，权限/CAS/确认/幂等不能绕过。"""
from __future__ import annotations

import asyncio
import importlib
from unittest.mock import AsyncMock

import pytest

from plugins.bot_unified_runtime.control_plane.auth import Principal
from plugins.bot_unified_runtime.control_plane.services import ControlServiceError

ADMIN = Principal("operator", ("super_admin",))


@pytest.fixture
def actions(tmp_path):
    module = importlib.import_module("plugins.bot_unified_runtime.control_plane.actions")
    handler = AsyncMock(return_value={"status": "ok", "details": {"token": "secret", "request_id": "req_safe"}})
    descriptor = module.ControlActionDescriptor("diagnostics.snapshot", "诊断快照", confirmation_required=True, timeout_seconds=0.1)
    service = module.ControlActionService(tmp_path / "actions.sqlite3", registrations=((descriptor, handler),))
    return service, handler


def preview(service, **kwargs):
    return service.preview("diagnostics.snapshot", parameters={}, expected_version=0, principal=ADMIN, **kwargs)


def execute(service, **kwargs):
    defaults = {"action_id": "diagnostics.snapshot", "parameters": {}, "expected_version": 0, "principal": ADMIN, "request_id": "req_1", "idempotency_key": "once"}
    defaults.update(kwargs)
    return asyncio.run(service.execute(**defaults))


def test_permissions_schema_and_unknown_actions_fail_before_execution(actions):
    service, handler = actions
    for kwargs, code in (({"principal": Principal("reader", ("admin",))}, "forbidden"), ({"action_id": "shell.exec"}, "action_not_found"), ({"parameters": {"command": "echo secret"}}, "validation_error"), ({"expected_version": True}, "validation_error")):
        with pytest.raises(ControlServiceError) as caught:
            execute(service, **kwargs)
        assert caught.value.code == code
    handler.assert_not_awaited()
    assert service.runs() == ()


def test_confirmation_is_bound_to_actor_version_and_consumed_once(actions):
    service, handler = actions
    token = preview(service)["confirmation_token"]
    with pytest.raises(ControlServiceError, match="确认"):
        execute(service, confirmation_token=token, principal=Principal("another", ("super_admin",)))
    result = execute(service, confirmation_token=token)
    assert result["state"] == "succeeded" and result["version"] == 1
    assert result["result"] == {"status": "ok", "details": {"request_id": "req_safe"}}
    assert "secret" not in repr(service.runs())
    duplicate = execute(service, confirmation_token=token)
    assert duplicate["run_id"] == result["run_id"]
    handler.assert_awaited_once()
    with pytest.raises(ControlServiceError) as caught:
        execute(service, confirmation_token=token, idempotency_key="again")
    assert caught.value.code == "version_conflict"
    assert [row["state"] for row in service.audit(result["run_id"])] == ["running", "succeeded"]


def test_confirmation_expires_and_version_conflict_never_executes(actions):
    service, handler = actions
    service.clock = lambda: 100.0
    token = preview(service)["confirmation_token"]
    service.clock = lambda: 1000.0
    with pytest.raises(ControlServiceError) as caught:
        execute(service, confirmation_token=token)
    assert caught.value.code == "confirmation_required"
    handler.assert_not_awaited()


def test_persistence_is_visible_to_second_service_instance(actions):
    service, _handler = actions
    token = preview(service)["confirmation_token"]
    result = execute(service, confirmation_token=token)
    peer = type(service)(service.path, registrations=service.registrations)
    assert peer.detail("diagnostics.snapshot")["version"] == 1
    assert peer.run(result["run_id"])["state"] == "succeeded"


def test_failure_and_timeout_are_audited_without_exception_text(actions):
    service, handler = actions
    handler.side_effect = OSError("Bearer secret C:/private/config")
    first = execute(service, confirmation_token=preview(service)["confirmation_token"])
    assert first["state"] == "failed" and first["error_code"] == "action_failed"
    assert "secret" not in repr(first)
    async def wait_forever(_params):
        await asyncio.Event().wait()
    handler.side_effect = wait_forever
    second_preview = service.preview("diagnostics.snapshot", parameters={}, expected_version=1, principal=ADMIN)
    second = execute(service, expected_version=1, idempotency_key="second", confirmation_token=second_preview["confirmation_token"])
    assert second["state"] == "timed_out"
    assert len(service.runs()) == 2


def test_feature_gate_denial_prevents_audit_run_and_handler(actions):
    service, handler = actions
    service.feature_allowed = lambda _action_id: False
    with pytest.raises(ControlServiceError) as caught:
        execute(service)
    assert caught.value.code == "feature_disabled"
    handler.assert_not_awaited()
    assert service.runs() == ()


def test_capacity_is_transactional_across_instances(tmp_path):
    module = importlib.import_module("plugins.bot_unified_runtime.control_plane.actions")
    handler = AsyncMock(return_value={"status": "ok"})
    registrations = tuple((module.ControlActionDescriptor(f"task.{i}", "Task", confirmation_required=False), handler) for i in range(17))
    service = module.ControlActionService(tmp_path / "capacity.sqlite3", registrations=registrations)
    # 模拟同库另一执行器已受理的运行任务，不依赖本实例 _tasks 缓存。
    for i in range(16):
        service._begin(f"task.{i}", {}, 0, ADMIN, "req_seed", f"seed_{i}", None)
    peer = module.ControlActionService(service.path, registrations=registrations)
    with pytest.raises(ControlServiceError) as caught:
        asyncio.run(peer.execute("task.16", parameters={}, expected_version=0, principal=ADMIN,
            request_id="req_overflow", idempotency_key="overflow"))
    assert caught.value.code == "action_capacity"
    handler.assert_not_awaited()
