"""控制面写腿的 session_key 透传（需求 18②，席位 S-FILESAFE，2026-09-28）。

钉的是「R1＝原会话内确认」这一判据在控制面渠道**能不能被满足**：

- 旧形态：`ConfigControlService._guarded_apply` 硬写 ``session_key=""``。
  那句注释的理由（控制面没有入站会话）在判据层成立 —— ``consent.py`` 的同会话门写的是
  ``and row.source_session_key``，空串＝这张卡不声明来源会话、判据不启用。
  但硬写空串同时把「调用方其实知道会话」那一格也钉死了：R1 因此在控制面渠道
  整体退化成 R2 式跨会话批。
- 新形态：API 载荷可申报 `session_key`，服务层透传到门。
  **只收紧不放宽**：填了会话，批准必须真出现在那个会话里；填错只会批不下来。

四枚锁：① 申报值确实到了 `guarded_write`；② 不申报＝逐字节旧行为（空串）；
③ HTTP 腿把载荷里的 session_key 交出去（不是吞掉）；④ 注毒自证：把透传摘掉，
锁①必须红——证明绿的是这条透传，不是别处。
"""

from __future__ import annotations

from pathlib import Path
from types import MethodType, SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from plugins.bot_unified_runtime.control_plane import create_control_plane_app
from plugins.bot_unified_runtime.control_plane.audit import ControlPlaneAuditStore
from plugins.bot_unified_runtime.control_plane.auth import Principal, hash_token
from plugins.bot_unified_runtime.control_plane.config_service import (
    ConfigControlService,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
    build_instance_settings_manager,
)

ADMIN = Principal("bearer-super-admin", ("super_admin", "admin"))
KEY = "BOT_CHAT_TEMPERATURE"
VALUE = 0.7
SESSION = "group_1888_555"


def _config(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        bot_chat_temperature=0.5,
        bot_transport_timeout_seconds=8.0,
        bot_memory_extract_timeout_seconds=60.0,
        bot_runtime_settings_dir=str(tmp_path / "settings"),
        bot_control_plane_config_db=str(tmp_path / "cp_config.sqlite3"),
        bot_safetyexec_enabled=True,
    )


class _RecordingGate:
    """假门：记下 kwargs，并直接执行 apply（这笔到底落不落脚本不参与判据）。"""

    enabled = True

    def __init__(self) -> None:
        self.seen: list[dict[str, Any]] = []

    def guarded_write(self, **kwargs: Any) -> Any:
        self.seen.append(kwargs)
        apply_call = kwargs.get("apply")
        return apply_call() if callable(apply_call) else None


def _service(tmp_path: Path) -> tuple[ConfigControlService, _RecordingGate]:
    config = _config(tmp_path)
    store = build_instance_settings_manager(config).get("default")
    backend = store.config_backend
    assert backend is not None, "前提不成立：要的是挂着 SQL backend 的形态"
    service = ConfigControlService(config, backend, runtime_settings=store)
    gate = _RecordingGate()
    service._consent_gate = lambda: gate  # type: ignore[method-assign]
    return service, gate


def test_declared_session_reaches_the_gate(tmp_path: Path) -> None:
    service, gate = _service(tmp_path)

    service.set(KEY, VALUE, principal=ADMIN, expected_version=0,
                request_id="t7-1", session_key=SESSION)

    assert gate.seen, "门一次都没被问到：写腿绕过了同意门"
    assert gate.seen[0]["session_key"] == SESSION
    assert gate.seen[0]["key"] == KEY


def test_reset_carries_the_session_too(tmp_path: Path) -> None:
    service, gate = _service(tmp_path)

    service.set(KEY, VALUE, principal=ADMIN, expected_version=0,
                request_id="t7-2", session_key=SESSION)
    service.reset(KEY, principal=ADMIN, expected_version=1,
                  request_id="t7-3", session_key=SESSION)

    assert [row["session_key"] for row in gate.seen] == [SESSION, SESSION]
    assert gate.seen[-1]["restore_default"] is True


def test_absent_session_stays_empty_byte_for_byte(tmp_path: Path) -> None:
    """不申报＝旧行为逐字节保持：空串交进去，同会话判据对该渠道不启用。"""
    service, gate = _service(tmp_path)

    service.set(KEY, VALUE, principal=ADMIN, expected_version=0, request_id="t7-4")

    assert gate.seen[0]["session_key"] == ""


def test_http_leg_passes_the_payload_session(tmp_path: Path) -> None:
    """HTTP 腿不许把载荷里的 session_key 吞掉（吞掉＝判据永远接不上）。

    真装配真 POST：`create_control_plane_app` 没有 `token_store` 形参（旧夹具把它当
    注入口用＝夹具坏），鉴权按在册口径走 super-admin bearer token，见
    `test_control_plane_consent_throat.py` 同型先例。断言落在「服务层真收到了载荷
    里那个会话」上——不是 `assert SESSION` 那种废话（它会在透传坏掉时照样给绿账）。
    """
    service, gate = _service(tmp_path)
    read_token = "cp-session-threading-read"
    root_token = "cp-session-threading-root"
    app_config = SimpleNamespace(
        bot_control_plane_enabled=True,
        bot_control_plane_token_sha256=hash_token(read_token),
        bot_control_plane_super_admin_token_sha256=hash_token(root_token),
        bot_runtime_settings_dir=str(tmp_path / "settings"),
        bot_runtime_settings_file=str(tmp_path / "settings.json"),
        bot_control_plane_config_db=str(tmp_path / "cp_config.sqlite3"),
        bot_control_plane_features_file=str(tmp_path / "features.json"),
        bot_timezone="UTC",
        bot_safetyexec_enabled=True,
        bot_chat_temperature=0.5,
    )
    app = create_control_plane_app(
        app_config,
        audit_store=ControlPlaneAuditStore(str(tmp_path / "audit.sqlite3")),
        channel_health_store=object(),
        config_service=service,
    )

    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        landed = client.post(
            f"/api/v1/config/{KEY}/set",
            headers={"Authorization": f"Bearer {root_token}"},
            json={"expected_version": 0, "value": VALUE, "session_key": SESSION},
        )
        assert landed.status_code == 200, landed.text

    assert gate.seen, "HTTP 腿没问门：这笔写绕过了同意门"
    assert gate.seen[-1]["session_key"] == SESSION, "载荷里的 session_key 被吞掉了"


def test_route_source_threads_session_key() -> None:
    """路由层活性锁：`/config/{key}/set` 与 `/reset` 两个端点必须把 session_key 交出去。"""
    import ast

    source = Path(
        "plugins/bot_unified_runtime/control_plane/api/v1.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    wanted = {"config_service().set", "config_service().reset"}
    threaded: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        attr = getattr(func, "attr", "")
        if attr not in {"set", "reset"}:
            continue
        if not any(
            isinstance(kw, ast.keyword) and kw.arg == "session_key"
            for kw in node.keywords
        ):
            continue
        threaded.add(attr)
    assert {"set", "reset"} <= threaded, f"端点未透传 session_key：{sorted(wanted)} 缺 {sorted({'set','reset'} - threaded)}"


def test_service_signature_has_session_key() -> None:
    """服务层三条写入口的签名必须都吃 session_key（漏一条＝那条腿仍传空串）。"""
    import inspect

    for name in ("set", "reset", "_write", "_guarded_apply"):
        signature = inspect.signature(getattr(ConfigControlService, name))
        assert "session_key" in signature.parameters, f"{name} 不吃 session_key"


# ==================== 注毒自证 ====================


def test_poison_dropping_the_thread_turns_lock_red(tmp_path: Path) -> None:
    """把透传摘掉（回到硬写空串的旧形态），锁①的判据必须当场红。

    注毒走 `types.MethodType`：直接往实例字典塞裸函数时，`_write` 里的
    `self._guarded_apply(...)` 不经描述符协议、少传 `self`，炸的是「缺位置参数」的
    TypeError——红的是夹具接线，不是这条透传（毒在空跑）。摘掉之后必须**看得见**
    门收到空串，并且锁①原样复跑要失败。
    """
    service, gate = _service(tmp_path)
    real_guarded = ConfigControlService._guarded_apply

    def _hardcoded_empty(self: Any, **kwargs: Any) -> Any:
        kwargs["session_key"] = ""  # 旧形态：无论调用方给了什么都写死空串
        return real_guarded(self, **kwargs)

    service._guarded_apply = MethodType(_hardcoded_empty, service)
    service.set(KEY, VALUE, principal=ADMIN, expected_version=0,
                request_id="t7-5", session_key=SESSION)

    assert gate.seen, "注毒后门一次都没被问到：这笔写绕过了同意门，注毒在空跑"
    assert gate.seen[-1]["session_key"] == "", "摘掉透传后没落回旧形态（空串）"
    with pytest.raises(AssertionError):
        # 锁①的判据原样复跑：绿的必须是这条透传本身，不是别处。
        assert gate.seen[0]["session_key"] == SESSION
