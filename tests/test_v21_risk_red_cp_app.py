"""V2.1 风险域 4 回归（control_plane/_app.py 装配与注入面）。

历史（A5 取证席 RED → v21r2 RK4 席收口）：
- 局部 ``_path`` 导入地雷与 platform 路由注册崩：已由并行批修复，两条装配
  测试转正为常驻回归；
- config/log_level_setter 注入缺口：工厂现把 config 直传平台路由
  （/api/v1/media/analyze 不再恒 503 media_config_unavailable）；
- SendQueue 注入缺口：工厂增 ``send_queue`` 形参，注入后 queue.* 动作有
  真实作用对象（未注入如实 degraded）；
- runtime_attached 冻结谎报：napcat.status 只信 ``runtime_state_probe``
  实时探针现查；装配期标量不再冒充连接声明。
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from plugins.bot_unified_runtime.control_plane import create_control_plane_app
from plugins.bot_unified_runtime.control_plane.audit import ControlPlaneAuditStore
from plugins.bot_unified_runtime.control_plane.auth import hash_token

ROOT = {"Authorization": "Bearer root-test-token"}


def _config(tmp_path: Path, **extra: object) -> SimpleNamespace:
    return SimpleNamespace(
        bot_control_plane_enabled=True,
        bot_control_plane_token_sha256=hash_token("read-test-token"),
        bot_control_plane_super_admin_token_sha256=hash_token("root-test-token"),
        bot_runtime_settings_dir=str(tmp_path / "settings"),
        bot_control_plane_config_db=str(tmp_path / "config.sqlite3"),
        bot_runtime_settings_file=str(tmp_path / "settings.json"),
        bot_control_plane_features_file=str(tmp_path / "features.json"),
        bot_timezone="UTC",
        **extra,
    )


def _build(tmp_path: Path, **extra: object) -> Any:
    return create_control_plane_app(
        _config(tmp_path, **extra),
        audit_store=ControlPlaneAuditStore(str(tmp_path / "audit.sqlite3")),
        channel_health_store=object(),
    )


def _app_with(tmp_path: Path, config: object, **factory: object) -> Any:
    return create_control_plane_app(
        config,
        audit_store=ControlPlaneAuditStore(str(tmp_path / "audit.sqlite3")),
        channel_health_store=object(),
        **factory,
    )


def _default_action_handler(app: Any, action_id: str) -> Any:
    """取默认装配的动作 handler（闭包在 _app 内，经注册表取用）。"""
    registry = app.state.action_service._registry
    return registry[action_id][1]


def test_risk4_default_app_creation_survives_without_events_db(tmp_path: Path) -> None:
    app = _build(tmp_path)
    assert getattr(app, "routes", None)


def test_risk4_app_creation_survives_with_events_db(tmp_path: Path) -> None:
    app = _build(
        tmp_path,
        bot_control_plane_events_db=str(tmp_path / "events.sqlite3"),
        bot_control_plane_actions_db=str(tmp_path / "actions.sqlite3"),
        bot_control_plane_platform_db=str(tmp_path / "platform.sqlite3"),
    )
    assert getattr(app, "routes", None)


# ---------------------------------------------------------------------------
# V21-risk-4 · SendQueue 注入（原 RED 转正）
# ---------------------------------------------------------------------------


def test_risk4_queue_runtime_ports_injectable() -> None:
    params = inspect.signature(create_control_plane_app).parameters
    assert any("queue" in name or "ports" in name for name in params), (
        f"工厂形参里没有 SendQueue/RuntimePorts 注入点：{list(params)}"
    )


def test_risk4_send_queue_injection_reaches_queue_actions(tmp_path: Path) -> None:
    class _StubQueue:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def pause(self) -> dict[str, str]:
            self.calls.append("pause")
            return {"state": "paused"}

    queue = _StubQueue()
    app = _app_with(
        tmp_path,
        _config(
            tmp_path,
            bot_control_plane_actions_db=str(tmp_path / "actions.sqlite3"),
        ),
        send_queue=queue,
    )
    assert app.state.send_queue is queue

    handler = _default_action_handler(app, "queue.pause")
    result = asyncio.run(handler({}))
    assert result["status"] == "ok"
    assert result["details"]["queue"] == {"state": "paused"}
    assert queue.calls == ["pause"]


def test_risk4_queue_actions_degrade_honestly_without_injection(
    tmp_path: Path,
) -> None:
    app = _build(
        tmp_path,
        bot_control_plane_actions_db=str(tmp_path / "actions.sqlite3"),
    )
    handler = _default_action_handler(app, "queue.resume")
    result = asyncio.run(handler({}))
    assert result == {
        "status": "degraded",
        "details": {"execution": "send_queue_not_connected"},
    }


# ---------------------------------------------------------------------------
# V21-risk-4 · napcat.status 实时探针（原冻结标量 RED 改钉 handler 语义）
# ---------------------------------------------------------------------------


def test_risk4_napcat_status_no_probe_reports_disconnected_despite_attached(
    tmp_path: Path,
) -> None:
    # runtime_attached=True（装配期事实）+ 无探针 → 不得冒充已连接。
    app = _app_with(
        tmp_path,
        _config(
            tmp_path,
            bot_control_plane_actions_db=str(tmp_path / "actions.sqlite3"),
        ),
        runtime_attached=True,
    )
    handler = _default_action_handler(app, "napcat.status")
    result = asyncio.run(handler({}))
    assert result == {
        "status": "ok",
        "details": {"connected": False, "source": "probe_not_configured"},
    }


def test_risk4_napcat_status_probe_reports_live_connection(tmp_path: Path) -> None:
    app = _app_with(
        tmp_path,
        _config(
            tmp_path,
            bot_control_plane_actions_db=str(tmp_path / "actions.sqlite3"),
        ),
        runtime_attached=True,
        runtime_state_probe=lambda: True,
    )
    handler = _default_action_handler(app, "napcat.status")
    result = asyncio.run(handler({}))
    assert result == {
        "status": "ok",
        "details": {"connected": True, "source": "runtime_probe"},
    }

    app2 = _app_with(
        tmp_path, _config(tmp_path), runtime_state_probe=lambda: False
    )
    result2 = asyncio.run(_default_action_handler(app2, "napcat.status")({}))
    assert result2["details"]["connected"] is False


def test_risk4_napcat_status_probe_failure_fails_open(tmp_path: Path) -> None:
    def _boom() -> bool:
        raise RuntimeError("probe exploded")

    app = _app_with(
        tmp_path,
        _config(
            tmp_path,
            bot_control_plane_actions_db=str(tmp_path / "actions.sqlite3"),
        ),
        runtime_state_probe=_boom,
    )
    handler = _default_action_handler(app, "napcat.status")
    result = asyncio.run(handler({}))
    assert result == {
        "status": "degraded",
        "details": {"connected": False, "source": "probe_error"},
    }


# ---------------------------------------------------------------------------
# V21-risk-4 · config/log_level_setter 注入（平台路由）
# ---------------------------------------------------------------------------


def test_risk4_media_analyze_receives_injected_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """config 直传平台路由：/api/v1/media/analyze 不再恒 503 media_config_unavailable。"""
    captured: dict[str, Any] = {}

    def _fake_builder(cfg: object, **_: object) -> object:
        captured["config"] = cfg
        return object()

    def _fake_describe(
        provider: object, *, image_urls: list[str], query_text: str = "", **_: object
    ) -> str:
        return "fake-vision-text"

    canonical = (
        "plugins.bot_unified_runtime.domains.media.ingest.vision_describe"
    )
    monkeypatch.setattr(f"{canonical}.build_vision_provider", _fake_builder)
    monkeypatch.setattr(f"{canonical}.describe_images", _fake_describe)

    cfg = _config(tmp_path)
    app = _app_with(tmp_path, cfg)
    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        resp = client.post(
            "/api/v1/media/analyze",
            headers=ROOT,
            json={
                "kind": "image",
                "image_urls": ["data:image/png;base64,AAAA"],
                "query": "test",
            },
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["kind"] == "image"
    assert data["text"] == "fake-vision-text"
    assert captured["config"] is cfg


def test_risk4_platform_log_level_setter_wired(tmp_path: Path) -> None:
    """log_level_setter 已装配：标准级别真应用，非标准级如实 applied=false。"""
    import logging

    from fastapi import FastAPI

    from plugins.bot_unified_runtime.control_plane.api.platform import (
        build_platform_router,
    )

    router = build_platform_router(
        store=type("S", (), {})(),  # 仅 /logs/level 路由不触 store。
        read_dependency=lambda: None,
        write_dependency=lambda: None,
        log_level_setter=_import_app_level_setter(),
    )
    app = FastAPI()
    app.include_router(router)
    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        ok = client.post(
            "/logs/level", json={"level": "warning"}
        ).json()["data"]
        rejected = client.post(
            "/logs/level", json={"level": "detail"}
        ).json()["data"]
    assert ok == {"level": "warning", "applied": True}
    assert logging.getLogger().level == logging.WARNING
    assert rejected == {
        "level": "detail",
        "applied": False,
        "reason": "setter_reported_failure",
    }
    logging.getLogger().setLevel(logging.NOTSET)


def _import_app_level_setter() -> Any:
    from plugins.bot_unified_runtime.control_plane._app import (
        _apply_platform_log_level,
    )

    return _apply_platform_log_level


# ---------------------------------------------------------------------------
# 相邻缺陷台账（RK4 取证新增 → v21r4 RK5 席转正）：动作结果明细消毒阻断
# 已修：actions.py 改动作域专用消毒 _sanitize_action_details（布尔/数值/
# 标识符/嵌套结构放行，凭证形键名与自由文本仍丢弃），不再借道事件白名单。
# 本测试转正为常驻回归。
# ---------------------------------------------------------------------------


def test_risk4_action_details_survive_to_client(tmp_path: Path) -> None:
    app = _build(
        tmp_path,
        bot_control_plane_events_db=str(tmp_path / "events.sqlite3"),
        bot_control_plane_actions_db=str(tmp_path / "actions.sqlite3"),
    )
    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        preview = client.post(
            "/api/v1/actions/napcat.status/preview",
            headers=ROOT,
            json={"expected_version": 0},
        ).json()["data"]
        run = client.post(
            "/api/v1/actions/napcat.status/execute",
            headers=ROOT,
            json={
                "expected_version": 0,
                "parameters": {},
                "idempotency_key": "napcat-1",
                "confirmation_token": preview["confirmation_token"],
            },
        ).json()
        details = _find_key(run, "details")
        assert details and "connected" in details, (
            f"动作结果细节被消毒层丢弃：{run}"
        )


def _find_key(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for value in obj.values():
            found = _find_key(value, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_key(value, key)
            if found is not None:
                return found
    return None
