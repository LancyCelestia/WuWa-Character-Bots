"""所有者授权口令（owner consent）控制面通道的行为锁。

钉的是什么
----
WebUI 想改 R1/R2 键时，安全门会出同意工单并要求「主人在私聊亲批」。控制面没有
入站消息，因此本仓新增一条**显式 opt-in** 的第二把钥匙：部署同时配置
`bot_control_plane_owner_secret` 与 `bot_control_plane_allow_owner_consent=true`，
调用方在请求头带 `X-Owner-Consent`。服务层收到该布尔后才构造「主人亲批」消息，
仍然走 `SettingsWriteGate.approve` 的全部既有判据（短码/私聊/防自批/一次性/TTL）。

锁：
① 不带口令 ⇒ 照旧 409 consent_required，零落库；
② 带口令 ⇒ 当场批准并同参重试，值落地、同意账 consumed、变更流水 applied；
③ 错口令 ⇒ 403 owner_consent_invalid，且一字节不动；
④ 部署未显式开启 ⇒ 即使给了正确口令也不生效（缺省安全姿态不变）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from plugins.bot_unified_runtime.control_plane import create_control_plane_app
from plugins.bot_unified_runtime.control_plane.audit import ControlPlaneAuditStore
from plugins.bot_unified_runtime.control_plane.auth import Principal, hash_token
from plugins.bot_unified_runtime.control_plane.config_service import (
    ConfigControlService,
)
from plugins.bot_unified_runtime.control_plane.services import ControlServiceError
from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
    build_instance_settings_manager,
)
from plugins.bot_unified_runtime.domains.core.safety_exec.consent import (
    CHANGE_APPLIED,
    CHANGE_TABLE,
    CONSENT_TABLE,
)

R2_KEY = "BOT_CHAT_TEMPERATURE"
R2_VALUE = 0.7
OWNER_ID = "3865067623"
OWNER_SECRET = "owner-secret-for-tests"
ADMIN = Principal("bearer-super-admin", ("super_admin", "admin"))


def _config(tmp_path: Path, *, allow_owner: bool = True, with_owner: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        bot_chat_temperature=0.5,
        bot_transport_timeout_seconds=8.0,
        bot_memory_extract_timeout_seconds=60.0,
        bot_runtime_settings_dir=str(tmp_path / "settings"),
        bot_control_plane_config_db=str(tmp_path / "cp_config.sqlite3"),
        bot_safetyexec_enabled=True,
        bot_super_admin_user_ids=[OWNER_ID] if with_owner else [],
        bot_control_plane_owner_secret=OWNER_SECRET,
        bot_control_plane_allow_owner_consent=allow_owner,
    )


def _wired(tmp_path: Path) -> tuple[Any, ConfigControlService]:
    config = _config(tmp_path)
    manager = build_instance_settings_manager(config)
    store = manager.get("default")
    backend = store.config_backend
    assert backend is not None
    return store, ConfigControlService(config, backend, runtime_settings=store)


def _states(store: Any, table: str) -> list[str]:
    try:
        with sqlite3.connect(Path(str(store.config_backend.path))) as conn:
            return [str(row[0]) for row in conn.execute(f"SELECT state FROM {table}")]
    except sqlite3.Error:
        return []


def test_owner_consent_lands_r2_write_in_one_call(tmp_path: Path) -> None:
    store, service = _wired(tmp_path)
    assert service.set(
        R2_KEY, R2_VALUE, principal=ADMIN, expected_version=0,
        request_id="owner-consent-1", owner_consent=True,
    )["value"] == R2_VALUE
    assert store.config_backend.snapshot().overrides[R2_KEY] == R2_VALUE
    assert CONSENT_TABLE and _states(store, CONSENT_TABLE).count("consumed") == 1
    assert CHANGE_APPLIED in _states(store, CHANGE_TABLE)
    assert store.safety_gate.pending_tickets() == []


def test_owner_consent_off_still_issues_ticket(tmp_path: Path) -> None:
    store, service = _wired(tmp_path)
    with pytest.raises(ControlServiceError) as exc:
        service.set(R2_KEY, R2_VALUE, principal=ADMIN, expected_version=0,
                    request_id="owner-consent-2")
    assert exc.value.code == "consent_required"
    assert store.config_backend.snapshot().overrides == {}
    assert _states(store, CONSENT_TABLE).count("pending") == 1


def _app(tmp_path: Path, *, allow_owner: bool = True) -> tuple[Any, Any, Any]:
    admin_token = "owner-admin-token"
    root_token = "owner-root-token"
    config = SimpleNamespace(
        bot_control_plane_enabled=True,
        bot_control_plane_token_sha256=hash_token(admin_token),
        bot_control_plane_super_admin_token_sha256=hash_token(root_token),
        bot_runtime_settings_dir=str(tmp_path / "settings"),
        bot_control_plane_config_db=str(tmp_path / "config.sqlite3"),
        bot_runtime_settings_file=str(tmp_path / "settings.json"),
        bot_control_plane_features_file=str(tmp_path / "features.json"),
        bot_timezone="UTC",
        bot_safetyexec_enabled=True,
        bot_chat_temperature=0.5,
        bot_super_admin_user_ids=[OWNER_ID],
        bot_control_plane_owner_secret=OWNER_SECRET,
        bot_control_plane_allow_owner_consent=allow_owner,
    )
    app = create_control_plane_app(
        config, audit_store=ControlPlaneAuditStore(str(tmp_path / "audit.sqlite3")),
        channel_health_store=object(), allow_direct_config_write=True,
    )
    return app, admin_token, root_token


def test_http_owner_consent_lands_and_bad_secret_is_403(tmp_path: Path) -> None:
    app, admin_token, root_token = _app(tmp_path)
    auth = {"Authorization": f"Bearer {root_token}"}
    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        bad = client.post(
            f"/api/v1/config/{R2_KEY}/set",
            headers={**auth, "Idempotency-Key": "owner-consent-bad", "X-Owner-Consent": "wrong"},
            json={"expected_version": 0, "value": R2_VALUE},
        )
        assert bad.status_code == 403
        assert bad.json()["error"]["code"] == "owner_consent_invalid"

        good = client.post(
            f"/api/v1/config/{R2_KEY}/set",
            headers={**auth, "Idempotency-Key": "owner-consent-good", "X-Owner-Consent": OWNER_SECRET},
            json={"expected_version": 0, "value": R2_VALUE},
        )
        assert good.status_code in (200, 202), good.text
        read = client.get(f"/api/v1/config/{R2_KEY}", headers={"Authorization": f"Bearer {admin_token}"})
        assert read.json()["data"]["value"] == R2_VALUE


def test_http_owner_consent_disabled_is_ignored(tmp_path: Path) -> None:
    app, _admin_token, root_token = _app(tmp_path, allow_owner=False)
    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        refused = client.post(
            f"/api/v1/config/{R2_KEY}/set",
            headers={
                "Authorization": f"Bearer {root_token}",
                "Idempotency-Key": "owner-consent-disabled",
                "X-Owner-Consent": OWNER_SECRET,
            },
            json={"expected_version": 0, "value": R2_VALUE},
        )
        assert refused.status_code == 409
        assert refused.json()["error"]["code"] == "consent_required"
