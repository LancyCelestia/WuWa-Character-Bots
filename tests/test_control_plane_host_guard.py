"""P-01 控制面 Host 白名单（DNS rebinding 防护）回归。

设计：docs/design/control-plane-api.md §8.2「拒绝 Host 头不在白名单的请求」。
覆盖：白名单放行 / 非白名单 400（不泄露信息）/ 畸形 Host（缺端口、多值、
裸 IPv6、大小写与端口归一）/ Bearer 认证路径不受影响 / 白名单经
config·env 扩展 / 端口跟随控制面配置（无 8742 硬编码）/ 拒绝留审计痕。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from plugins.bot_unified_runtime.control_plane import (
    control_plane_settings,
    create_control_plane_app,
)
from plugins.bot_unified_runtime.control_plane._app import (
    _build_host_allowlist,
    _host_header_allowed,
    _split_host_port,
)
from plugins.bot_unified_runtime.control_plane.audit import ControlPlaneAuditStore
from plugins.bot_unified_runtime.control_plane.auth import hash_token

TOKEN = "unit-test-token"
BASE_URL = "http://127.0.0.1:8742"


@pytest.fixture(autouse=True)
def _clean_cp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """隔离控制面环境变量：断言不受本机环境污染。"""
    for name in (
        "BOT_CONTROL_PLANE_ENABLED",
        "BOT_CONTROL_PLANE_HOST",
        "BOT_CONTROL_PLANE_PORT",
        "BOT_CONTROL_PLANE_TOKEN_SHA256",
        "BOT_CONTROL_PLANE_HOST_ALLOWLIST",
    ):
        monkeypatch.delenv(name, raising=False)


class FakeChannelHealthStore:
    def report(self) -> list[dict[str, object]]:
        return []


def _config(**extra: object) -> SimpleNamespace:
    return SimpleNamespace(bot_control_plane_token_sha256=hash_token(TOKEN), **extra)


def _client(tmp_path, config: SimpleNamespace | None = None) -> TestClient:
    app = create_control_plane_app(
        config if config is not None else _config(),
        channel_health_store=FakeChannelHealthStore(),
        audit_store=ControlPlaneAuditStore(str(tmp_path / "cp.sqlite3")),
        started_at=datetime.now().astimezone(),
    )
    return TestClient(app, base_url=BASE_URL)


# ==================== ① 白名单 Host 放行 ====================


def test_whitelisted_hosts_pass(tmp_path) -> None:
    with _client(tmp_path) as client:
        assert client.get("/healthz", headers={"Host": "127.0.0.1:8742"}).status_code == 200
        assert client.get("/healthz", headers={"Host": "localhost:8742"}).status_code == 200


def test_host_case_insensitive(tmp_path) -> None:
    # RFC 9110：host 大小写不敏感 → 归一小写后匹配（端口原样数值比较）。
    with _client(tmp_path) as client:
        assert client.get("/healthz", headers={"Host": "LOCALHOST:8742"}).status_code == 200
        assert client.get("/healthz", headers={"Host": "127.0.0.1:8742"}).status_code == 200


# ==================== ② 非白名单 Host 拒绝 400（不泄露信息） ====================


def test_foreign_host_rejected_400(tmp_path) -> None:
    with _client(tmp_path) as client:
        for host in ("evil.example.com", "evil.example.com:8742", "localhost.evil.com"):
            response = client.get(
                "/admin/api/v1/health",
                headers={"Host": host, "Authorization": f"Bearer {TOKEN}"},
            )
            assert response.status_code == 400, host
        body = response.json()["error"]
        assert body["code"] == "host_not_allowed"
        assert "evil" not in body["message"]  # 不回显攻击 Host（不泄露信息）
        assert "Traceback" not in body["message"]


def test_rebinding_bypass_blocked_even_with_valid_token(tmp_path) -> None:
    # DNS rebinding 的核心断言：即便带合法 Bearer，Host 不对也进不去。
    with _client(tmp_path) as client:
        response = client.get(
            "/admin/api/v1/status/models",
            headers={"Host": "evil.example.com:8742", "Authorization": f"Bearer {TOKEN}"},
        )
    assert response.status_code == 400


# ==================== ③ 畸形 Host：严格拒绝与归一化取舍 ====================


def test_host_without_port_rejected(tmp_path) -> None:
    # 取舍：监听非默认端口时合规客户端必带端口；缺端口不做 80/443 推断。
    with _client(tmp_path) as client:
        assert client.get("/healthz", headers={"Host": "127.0.0.1"}).status_code == 400
        assert client.get("/healthz", headers={"Host": "localhost"}).status_code == 400


def test_multiple_host_headers_rejected(tmp_path) -> None:
    # 重复/多值 Host = 走私与 rebinding 向量：恰好一个才放行。
    with _client(tmp_path) as client:
        response = client.get(
            "/healthz",
            headers=[
                (b"host", b"127.0.0.1:8742"),
                (b"host", b"evil.example.com"),
            ],
        )
    assert response.status_code == 400


def test_malformed_host_forms_rejected(tmp_path) -> None:
    with _client(tmp_path) as client:
        for host in (
            "127.0.0.1:",  # 空端口 → 缺端口语义，拒
            "[::1",  # 未闭合 IPv6 bracket
            "[::1]x",  # bracket 后非 :port
            "::1:8742",  # 裸 IPv6（无 bracket，歧义）
            "127.0.0.1:0",  # 端口越界
            "127.0.0.1:99999",  # 端口越界
            "127.0.0.1:8742x",  # 非数字端口
            "127.0.0.1:87.42",  # 非数字端口
            ":8742",  # 空 host
        ):
            assert client.get("/healthz", headers={"Host": host}).status_code == 400, host


def test_host_port_normalized_as_integer(tmp_path) -> None:
    # 取舍：端口按整数值比较（前导零等价），host 大小写归一。
    with _client(tmp_path) as client:
        assert client.get("/healthz", headers={"Host": "127.0.0.1:08742"}).status_code == 200


def test_split_host_port_units() -> None:
    assert _split_host_port("LOCALHost:8742", default_port=None) == ("localhost", 8742)
    assert _split_host_port("[::1]:8742", default_port=None) == ("::1", 8742)
    assert _split_host_port("[::1]", default_port=9999) == ("::1", 9999)
    assert _split_host_port("gw.example", default_port=9999) == ("gw.example", 9999)
    # default_port=None（请求 Host 头路径）：缺端口/畸形一律 None。
    assert _split_host_port("127.0.0.1", default_port=None) is None
    assert _split_host_port("", default_port=8742) is None


# ==================== ④ Bearer 认证路径不受影响 ====================


def test_bearer_flow_unaffected_by_guard(tmp_path) -> None:
    with _client(tmp_path) as client:
        missing = client.get("/admin/api/v1/health")
        wrong = client.get(
            "/admin/api/v1/health",
            headers={"Authorization": "Bearer wrong-token"},
        )
        ok = client.get(
            "/admin/api/v1/health",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
    assert missing.status_code == 401  # 白名单 Host 之下：无 token 仍 401
    assert wrong.status_code == 401
    assert ok.status_code == 200
    assert ok.json()["ok"] is True


# ==================== 白名单扩展（config / env）与端口跟随 ====================


def test_allowlist_extended_via_config(tmp_path) -> None:
    config = _config(
        bot_control_plane_host_allowlist="gw.example.internal:8742, 127.0.0.1:9999"
    )
    with _client(tmp_path, config) as client:
        assert client.get("/healthz", headers={"Host": "gw.example.internal:8742"}).status_code == 200
        # 省端口的条目继承控制面端口。
        assert client.get("/healthz", headers={"Host": "127.0.0.1:9999"}).status_code == 200
        # 扩展是“只增不减”：默认条目与攻击 Host 语义不变。
        assert client.get("/healthz", headers={"Host": "localhost:8742"}).status_code == 200
        assert client.get("/healthz", headers={"Host": "evil.example.com"}).status_code == 400


def test_allowlist_extended_via_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("BOT_CONTROL_PLANE_HOST_ALLOWLIST", "gw.example.internal")
    config = SimpleNamespace()  # 无 config 字段 → env 兜底生效
    with _client(tmp_path, config) as client:
        assert client.get("/healthz", headers={"Host": "gw.example.internal:8742"}).status_code == 200


def test_settings_host_allowlist_resolution(monkeypatch) -> None:
    # 字段缺失 → 空元组（默认白名单在 app 侧叠加，不进 settings）。
    assert control_plane_settings(SimpleNamespace()).host_allowlist == ()
    # config str / list 两种形态。
    assert control_plane_settings(
        SimpleNamespace(bot_control_plane_host_allowlist="a.example:1, b.example")
    ).host_allowlist == ("a.example:1", "b.example")
    assert control_plane_settings(
        SimpleNamespace(bot_control_plane_host_allowlist=["c.example:2", " d.example "])
    ).host_allowlist == ("c.example:2", "d.example")
    # env 兜底；config 字段优先于 env。
    monkeypatch.setenv("BOT_CONTROL_PLANE_HOST_ALLOWLIST", "env.example:3")
    assert control_plane_settings(SimpleNamespace()).host_allowlist == ("env.example:3",)
    assert control_plane_settings(
        SimpleNamespace(bot_control_plane_host_allowlist="cfg.example:4")
    ).host_allowlist == ("cfg.example:4",)


def test_port_follows_settings_not_hardcoded(tmp_path) -> None:
    # 端口 9999 时：默认 8742 条目失效，9999 条目放行（无硬编码漂移）。
    config = SimpleNamespace(
        bot_control_plane_token_sha256=hash_token(TOKEN),
        bot_control_plane_port="9999",
    )
    with _client(tmp_path, config) as client:
        assert client.get("/healthz", headers={"Host": "127.0.0.1:8742"}).status_code == 400
        assert client.get("/healthz", headers={"Host": "127.0.0.1:9999"}).status_code == 200
        assert client.get("/healthz", headers={"Host": "localhost:9999"}).status_code == 200


def test_invalid_allowlist_entries_fail_closed(tmp_path) -> None:
    # 非法条目跳过（白名单只授予不剥夺），默认防护不弱化。
    config = _config(bot_control_plane_host_allowlist="bad host!!, :x:, a:b:c")
    with _client(tmp_path, config) as client:
        assert client.get("/healthz", headers={"Host": "127.0.0.1:8742"}).status_code == 200
        assert client.get("/healthz", headers={"Host": "a:b:c"}).status_code == 400


def test_build_host_allowlist_defaults_and_extras() -> None:
    from plugins.bot_unified_runtime.control_plane import ControlPlaneSettings

    settings = ControlPlaneSettings(port=8742, host_allowlist=("GW.example",))
    assert _build_host_allowlist(settings) == frozenset(
        {"127.0.0.1:8742", "localhost:8742", "gw.example:8742"}
    )
    assert _host_header_allowed("gw.example:8742", _build_host_allowlist(settings))
    assert not _host_header_allowed("gw.example", _build_host_allowlist(settings))


# ==================== 拒绝请求留审计痕（外层审计 × 内层守卫） ====================


def test_rejected_host_audited_with_400(tmp_path) -> None:
    db_path = str(tmp_path / "cp.sqlite3")
    app = create_control_plane_app(
        _config(),
        channel_health_store=FakeChannelHealthStore(),
        audit_store=ControlPlaneAuditStore(db_path),
        started_at=datetime.now().astimezone(),
    )
    with TestClient(app, base_url=BASE_URL) as client:
        client.get(
            "/admin/api/v1/health",
            headers={"Host": "evil.example.com", "Authorization": f"Bearer {TOKEN}"},
        )
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM control_plane_audit").fetchone()
    assert row is not None
    assert row["status_code"] == 400
    assert row["detail"] == "host_not_allowed"
    assert row["subject"] == "anonymous"
