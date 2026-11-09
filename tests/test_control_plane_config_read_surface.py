"""A 组阻断缺陷（2026-11）：配置读面恒 500 / 超管令牌写腿 / 命令面装配。

三条真根因（侦察席已定位，本文件逐条锁死）：

1. ``api/v1.py`` 的 ``_filtered("catalog", "schema", principal=principal)`` 回落时把
   ``principal`` 塞给不吃该参数的旧方法 ⇒ ``TypeError`` ⇒ ``/config``、``/config/schema``、
   ``/config/catalog``、``/config/changes`` 四个读端点恒 500。
   前端契约（``webui/src/lib/config-presentation/types.ts``）却把
   ``GET /api/v1/config/catalog`` 当「当前值 / 版本 / can_write / 敏感标记」的唯一真身，
   并且点名 ``ConfigControlService.catalog`` 现算 ``can_write`` ⇒ 服务层缺的是
   ``catalog`` / ``list_for_principal`` / ``changes_for_principal`` 三个方法，不是把
   端点降级成空数据。

2. 所有写腿只认 ``BOT_CONTROL_PLANE_SUPER_ADMIN_TOKEN_SHA256``；管理令牌打写腿必须 403
   （前端要为此新增第三槽，本文件锁后端口径，前端在 ``api-client.test.ts`` 里锁）。

3. ``build_v1_router`` 不收 ``config_command_gateway`` 之外的东西，而
   ``create_control_plane_app`` **根本没有** ``config_command_gateway`` 形参
   （``standalone.py:129`` 传它＝装配期 TypeError），嵌入式更是不传 ⇒
   ``/api/v1/config/commands`` 永远 503。修复口径：形参补上并下传；嵌入式在没有
   外部网关时装配「宿主内直执行」网关（Bot 宿主自己就是执行方，不排队、不造假数据）。

不许把 500 吞成空数据：本文件的断言既看状态码，也看**行数与内容**。
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from plugins.bot_unified_runtime.control_plane import create_control_plane_app
from plugins.bot_unified_runtime.control_plane.audit import ControlPlaneAuditStore
from plugins.bot_unified_runtime.control_plane.auth import hash_token
from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
    RESTART_REQUIRED_KEYS,
    SETTABLE_KEYS,
)

ADMIN_TOKEN = "admin-token"
SUPER_TOKEN = "root-token"

#: 一枚确凿的热改白名单键（``SETTABLE_KEYS`` 真身里的第一格），以及一枚确凿的冻结键。
HOT_KEY = "BOT_CHAT_FAST_MODE"
FROZEN_KEY = "BOT_MESSAGE_MUTATION_ENABLED"


def _test_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="control-plane-config-surface-"))


def _config(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        bot_control_plane_enabled=True,
        bot_control_plane_token_sha256=hash_token(ADMIN_TOKEN),
        bot_control_plane_super_admin_token_sha256=hash_token(SUPER_TOKEN),
        bot_runtime_settings_dir=str(tmp_path / "settings"),
        bot_control_plane_config_db=str(tmp_path / "config.sqlite3"),
        bot_runtime_settings_file=str(tmp_path / "settings.json"),
        bot_control_plane_features_file=str(tmp_path / "features.json"),
        bot_timezone="UTC",
        bot_chat_fast_mode=False,
        bot_message_mutation_enabled=False,
    )


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _app(tmp_path: Path, **kwargs: Any):
    return create_control_plane_app(
        _config(tmp_path),
        audit_store=ControlPlaneAuditStore(str(tmp_path / "audit.sqlite3")),
        channel_health_store=object(),
        **kwargs,
    )


def test_config_read_surface_never_500s_and_returns_real_rows() -> None:
    """四个读端点全部 200，且返回**真实行**（不是被吞成空数组的假修复）。"""
    tmp_path = _test_dir()
    try:
        with TestClient(_app(tmp_path), base_url="http://127.0.0.1:8742") as client:
            for path in ("/api/v1/config", "/api/v1/config/schema", "/api/v1/config/catalog"):
                response = client.get(path, headers=_headers(ADMIN_TOKEN))
                assert response.status_code == 200, (path, response.status_code, response.text)
                body = response.json()
                assert body["error"] is None, (path, body.get("error"))
                items = body["data"]["items"]
                assert len(items) > 0, f"{path} 不得被吞成空数据"
                keys = {row["key"] for row in items}
                assert HOT_KEY in keys, f"{path} 少了白名单键 {HOT_KEY}"
                row = next(item for item in items if item["key"] == HOT_KEY)
                # 前端 LiveRow 契约：can_write 必须由后端现算（前端不猜）。
                assert "can_write" in row, (path, row)
                assert row["sensitive"] is False
                assert row["value"] is False

            changes = client.get("/api/v1/config/changes", headers=_headers(ADMIN_TOKEN))
            assert changes.status_code == 200, changes.text
            assert changes.json()["error"] is None
            assert isinstance(changes.json()["data"]["items"], list)
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_catalog_computes_can_write_from_role_and_whitelist() -> None:
    """``can_write`` ＝「在 SETTABLE_KEYS 且非冻结 且 主体是 super_admin」——三轴现算。"""
    tmp_path = _test_dir()
    try:
        with TestClient(_app(tmp_path), base_url="http://127.0.0.1:8742") as client:
            admin_items = client.get(
                "/api/v1/config/catalog", headers=_headers(ADMIN_TOKEN)
            ).json()["data"]["items"]
            admin_view = {row["key"]: row for row in admin_items}
            assert admin_view[HOT_KEY]["can_write"] is False, "管理令牌不能改配置"

            super_items = client.get(
                "/api/v1/config/catalog", headers=_headers(SUPER_TOKEN)
            ).json()["data"]["items"]
            super_view = {row["key"]: row for row in super_items}
            assert HOT_KEY in SETTABLE_KEYS
            assert super_view[HOT_KEY]["can_write"] is True, "超管 + 热改白名单才可写"

            # 冻结键（RESTART_REQUIRED_KEYS）即便超管也不可热改：不许画假开关。
            if FROZEN_KEY in RESTART_REQUIRED_KEYS:
                assert super_view[FROZEN_KEY]["can_write"] is False
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_only_super_admin_token_can_preview_a_write() -> None:
    """写腿只认超管令牌；管理令牌必须 403（前端第三槽的存在理由）。"""
    tmp_path = _test_dir()
    try:
        with TestClient(_app(tmp_path), base_url="http://127.0.0.1:8742") as client:
            denied = client.post(
                f"/api/v1/config/{HOT_KEY}/preview",
                headers=_headers(ADMIN_TOKEN),
                json={"value": True, "expected_version": 0},
            )
            assert denied.status_code == 403, denied.text
            assert denied.json()["error"]["code"] == "forbidden"

            allowed = client.post(
                f"/api/v1/config/{HOT_KEY}/preview",
                headers=_headers(SUPER_TOKEN),
                json={"value": True, "expected_version": 0},
            )
            assert allowed.status_code == 200, allowed.text
            assert allowed.json()["data"]["preview"] is True
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


class _FakeConfigService:
    """最小假配置服务：只记录写入调用，用来隔离「宿主内网关」的行为。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.backend = SimpleNamespace(
            snapshot=lambda: SimpleNamespace(version=0, overrides={})
        )

    def list_for_principal(self, principal: Any) -> list[dict[str, Any]]:
        return [{"key": HOT_KEY, "value": False, "version": 0, "can_write": True}]

    def catalog(self, principal: Any) -> list[dict[str, Any]]:
        return self.list_for_principal(principal)

    def schema(self) -> list[dict[str, Any]]:
        return self.list_for_principal(None)

    def changes_for_principal(self, principal: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    def get_for_principal(self, *, principal: Any, key: str) -> dict[str, Any]:
        return {"key": key, "value": False, "version": 0}

    def set(self, key: str, value: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("set", key, value))
        return {"key": key, "value": value, "version": 1, "state": "override"}

    def reset(self, key: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("reset", key))
        return {"key": key, "value": False, "version": 2, "state": "default"}

    def preview(self, key: str, value: Any = None, **kwargs: Any) -> dict[str, Any]:
        return {"key": key, "value": value, "version": 0, "preview": True}


def test_embedded_host_executes_config_writes_and_opens_command_surface() -> None:
    """嵌入式：``/config/commands`` 200（不再 503），写腿当场执行并回 applied 回执。

    宿主自己就是执行方 ⇒ 不排队（没有消费者会来取），也不造假数据：列表如实为空。
    """
    tmp_path = _test_dir()
    service = _FakeConfigService()
    try:
        with TestClient(
            _app(tmp_path, config_service=service, runtime_attached=True),
            base_url="http://127.0.0.1:8742",
        ) as client:
            listed = client.get("/api/v1/config/commands", headers=_headers(ADMIN_TOKEN))
            assert listed.status_code == 200, listed.text
            assert listed.json()["error"] is None
            assert listed.json()["data"]["items"] == [], "宿主内不排队：列表如实为空"

            written = client.post(
                f"/api/v1/config/{HOT_KEY}/set",
                headers={**_headers(SUPER_TOKEN), "Idempotency-Key": "idem-embedded-1"},
                json={"value": True, "expected_version": 0},
            )
            assert written.status_code == 202, written.text
            receipt = written.json()["data"]
            assert receipt["status"] == "applied", receipt
            assert receipt["version"] == 1
            assert service.calls == [("set", HOT_KEY, True)], "写腿必须真的落到服务层"

            # 命令面读单笔：宿主内没有排队的命令 ⇒ 诚实 404，不编造记录。
            missing = client.get("/api/v1/config/commands/nope", headers=_headers(ADMIN_TOKEN))
            assert missing.status_code == 404, missing.text
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


class _FakeGateway:
    def __init__(self) -> None:
        self.submitted: list[dict[str, Any]] = []

    def list_own(self, *, principal: Any, limit: int = 50) -> list[dict[str, Any]]:
        return [{"command_id": "c-1", "key": HOT_KEY, "status": "pending"}]

    def status(self, *, principal: Any, command_id: str) -> dict[str, Any]:
        if command_id != "c-1":
            raise RuntimeError("unexpected")
        return {"command_id": "c-1", "status": "pending"}

    def submit(self, **kwargs: Any) -> dict[str, Any]:
        self.submitted.append(kwargs)
        return {"command_id": "c-2", "status": "pending", "key": kwargs.get("key")}


def test_injected_command_gateway_is_accepted_and_used() -> None:
    """``create_control_plane_app(config_command_gateway=...)`` 必须收且下传。

    这一条同时锁 ``standalone.py:129`` 的装配路径：那个 kwarg 以前在
    ``create_control_plane_app`` 上不存在 ⇒ 独立面板默认工厂一调就 TypeError。
    """
    tmp_path = _test_dir()
    gateway = _FakeGateway()
    try:
        with TestClient(
            _app(
                tmp_path,
                runtime_attached=True,
                config_command_gateway=gateway,
                allow_direct_config_write=False,
                standalone=True,
            ),
            base_url="http://127.0.0.1:8742",
        ) as client:
            listed = client.get("/api/v1/config/commands", headers=_headers(ADMIN_TOKEN))
            assert listed.status_code == 200, listed.text
            assert listed.json()["data"]["items"][0]["command_id"] == "c-1"

            submitted = client.post(
                f"/api/v1/config/{HOT_KEY}/set",
                headers={**_headers(SUPER_TOKEN), "Idempotency-Key": "idem-injected-1"},
                json={"value": True, "expected_version": 0},
            )
            assert submitted.status_code == 202, submitted.text
            assert submitted.json()["data"]["command_id"] == "c-2"
            assert gateway.submitted and gateway.submitted[0]["idempotency_key"] == "idem-injected-1"
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)
