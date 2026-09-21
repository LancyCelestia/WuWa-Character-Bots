"""S9 席：模型控制 REST 全量（/api/v1/llm/*）离线回归。

覆盖：envelope+trace、RBAC 越权拒绝、凭证只回 fingerprint 不回明文、
R1 严格优先级与 INTIMATE 钉一只读投影、preview 零副作用、dry 校验、
live 诚实 503 not_configured、config preview+apply（复用 ConfigControlService）、
cache reload 作用域诚实性。全离线：健康库注入 tmp，monkeypatch 全局单例。
"""
from __future__ import annotations

import hashlib
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from plugins.bot_unified_runtime.control_plane import create_control_plane_app
from plugins.bot_unified_runtime.control_plane.audit import ControlPlaneAuditStore
from plugins.bot_unified_runtime.control_plane.auth import hash_token
from plugins.bot_unified_runtime.control_plane.llm_admin import LLMControlService
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.channel_health import (
    ChannelHealthStore,
)

ADMIN = {"Authorization": "Bearer s9-admin"}
ROOT = {"Authorization": "Bearer s9-root"}

SECRET_LITERAL = "s9-literal-secret-key-9a8b"
SECRET_GROK = "s9-env-grok-secret-c1d2"
SECRET_DS = "s9-env-ds-secret-e3f4"

REGISTRY: dict[str, dict[str, Any]] = {
    "axon-grok": {"model": "grok-4.6", "base_url": "https://axon.example/v1?api_key=must_not_leak",
                  "api_key": "env:S9_TEST_GROK_KEY", "priority": 10, "tags": ["strong"], "effort": "medium"},
    "axon-gemini": {"model": "gemini-3.8-flash", "base_url": "https://axon.example/v1",
                    "api_key": SECRET_LITERAL, "priority": 20},
    "qian-gemini": {"model": "gemini-3.8-flash", "base_url": "https://qian.example/v1",
                    "api_key": "", "priority": 30},
    "qian-ds": {"model": "deepseek-v4.1-flash", "base_url": "https://qian.example/v1",
                "api_key": "env:S9_TEST_DS_KEY", "priority": 40},
}


def _config(tmp_path) -> SimpleNamespace:
    return SimpleNamespace(
        bot_control_plane_enabled=True,
        bot_control_plane_token_sha256=hash_token("s9-admin"),
        bot_control_plane_super_admin_token_sha256=hash_token("s9-root"),
        bot_runtime_settings_dir=str(tmp_path / "settings"),
        bot_control_plane_config_db=str(tmp_path / "config.sqlite3"),
        bot_runtime_settings_file=str(tmp_path / "settings.json"),
        bot_control_plane_features_file=str(tmp_path / "features.json"),
        bot_control_plane_workspaces_db=str(tmp_path / "workspaces.sqlite3"),
        bot_timezone="UTC",
        bot_model_registry=REGISTRY,
        bot_chat_model="gemini-3.8-flash",
        bot_chat_api_key="s9-main-key",
        bot_chat_base_url="https://main.example/v1",
        bot_chat_timeout_seconds=30.0,
        bot_chat_failover_max_seconds=300.0,
        bot_chat_failover_min_hop_seconds=3.0,
        bot_chat_strict_priority=True,
        bot_chat_max_input_tokens=131072,
        bot_chat_max_output_tokens=65536,
        bot_model_priority_groups=[],
        bot_content_route_enabled=True,
        bot_content_route_model="grok-4.6",
        bot_content_route_order="grok-4.6,gemini-3.8-flash",
        bot_channel_health_enabled=True,
        bot_channel_health_latency_first=False,
    )


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("S9_TEST_GROK_KEY", SECRET_GROK)
    monkeypatch.setenv("S9_TEST_DS_KEY", SECRET_DS)


@pytest.fixture
def api(tmp_path, env, monkeypatch):
    store = ChannelHealthStore(str(tmp_path / "health.sqlite3"))
    # 路由管线（_health_filter_candidates/_demote_cooling_candidates）经
    # channel_health.get_channel_health_store() 取单例；测试重定向到 tmp 库，
    # 绝不触碰 Runtime。
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.domains.chat_reply.llm_engine.channel_health.get_channel_health_store",
        lambda db_path="": store,
    )
    cfg = _config(tmp_path)
    app = create_control_plane_app(
        cfg, channel_health_store=store,
        audit_store=ControlPlaneAuditStore(str(tmp_path / "audit.sqlite3")),
    )
    app.state.channel_health_store = store
    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        yield client, store


def _envelope_ok(payload: dict) -> None:
    assert payload["error"] is None
    assert payload["meta"]["schema_version"] == "v1"
    assert payload["meta"]["request_id"].startswith("req_")
    assert payload["meta"]["trace_id"].startswith("trace_")


def test_provider_channel_model_lists_and_fingerprint_never_leak_secrets(api):
    client, _store = api
    providers = client.get("/api/v1/llm/providers", headers=ADMIN)
    assert providers.status_code == 200
    _envelope_ok(providers.json())
    items = providers.json()["data"]["items"]
    origins = {item["origin"] for item in items}
    # 主配置兜底（main.example）也构成一个 provider 投影。
    assert {"https://axon.example", "https://qian.example", "https://main.example"} <= origins

    detail = client.get(f"/api/v1/llm/providers/{items[0]['provider_id']}", headers=ADMIN)
    assert detail.status_code == 200
    missing = client.get("/api/v1/llm/providers/prov-does-not-exist", headers=ADMIN)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "resource_not_found"

    channels = client.get("/api/v1/llm/channels", headers=ADMIN)
    assert channels.status_code == 200
    rows = {row["channel_id"]: row for row in channels.json()["data"]["items"]}
    assert {"axon-grok", "axon-gemini", "qian-gemini", "qian-ds"} <= set(rows)
    assert rows["axon-gemini"]["credential"]["state"] == "configured"
    assert rows["axon-gemini"]["credential"]["fingerprint"] == hashlib.sha256(SECRET_LITERAL.encode()).hexdigest()[:12]
    assert rows["qian-gemini"]["credential"] == {"state": "missing", "fingerprint": None, "key_count": 0}
    # 注册表 priority 经 normalize_priority_entries 稠密化为 1..N（排序语义不变）。
    assert rows["axon-grok"]["priority"] == 1
    assert rows["axon-grok"]["effort_override"] == "medium"
    # base_url 只回 origin：query 里的 api_key 形态永不出现。
    assert rows["axon-grok"]["origin"] == "https://axon.example"

    models = client.get("/api/v1/llm/models", headers=ADMIN)
    assert models.status_code == 200
    by_model = {item["model"]: item for item in models.json()["data"]["items"]}
    gemini = by_model["gemini-3.8-flash"]
    ordered = [row["channel_id"] for row in gemini["channels"]]
    # 严格注册表优先级投影；主配置兜底（default, priority 2000）垫底。
    assert ordered[:2] == ["axon-gemini", "qian-gemini"]
    assert ordered[-1] == "default"
    assert gemini["effort"]["baseline"] == "low" and gemini["effort"]["max"] == "high"

    # 明文密钥/env 名永不出现在任何 llm 响应里。
    for path in ("/llm/providers", "/llm/channels", "/llm/models", "/llm/routes", "/llm/health"):
        body = client.get(f"/api/v1{path}", headers=ADMIN).text
        for secret in (SECRET_LITERAL, SECRET_GROK, SECRET_DS, "must_not_leak", "env:S9_TEST"):
            assert secret not in body
        assert '"api_key"' not in body


def test_health_aggregation_and_routes_policy(api):
    client, store = api
    health = client.get("/api/v1/llm/health", headers=ADMIN).json()["data"]
    assert health["status"] == "ok"
    assert health["health_layer_enabled"] is True
    assert health["source"] == "channel_health_store"

    store.record_failure("qian-ds", "kind=timeout", cooldown_seconds=90)
    store.record_failure("qian-ds", "kind=timeout", cooldown_seconds=90)
    store.record_failure("qian-ds", "kind=timeout", cooldown_seconds=90)
    health = client.get("/api/v1/llm/health", headers=ADMIN).json()["data"]
    assert health["status"] == "degraded"
    assert "qian-ds" in health["cooling_ids"]
    assert "qian-ds" in health["unavailable_ids"]

    routes = client.get("/api/v1/llm/routes", headers=ADMIN).json()["data"]
    assert routes["policy"]["strict_priority"] is True
    assert routes["policy"]["failover_max_seconds"] == 300.0
    assert routes["policy"]["max_output_tokens"] == 65536
    gemini = next(item for item in routes["routes"] if item["model"] == "gemini-3.8-flash")
    channel_ids = [row["channel_id"] for row in gemini["channels"]]
    assert channel_ids[:2] == ["axon-gemini", "qian-gemini"] and channel_ids[-1] == "default"


def test_routes_preview_projection_is_readonly(api):
    client, store = api

    auto = client.post("/api/v1/llm/routes/preview", headers=ADMIN, json={}).json()["data"]
    ids = [row["model_id"] for row in auto["candidates"]]
    assert ids[0] == "axon-grok"  # priority 10 首发
    assert "default" not in ids  # manual 兜底不进自动队列
    assert ids[1] == "axon-gemini"
    assert auto["mode"] == "auto"

    # 健康过滤投影：qian-ds 三败转暂不可用 → 从候选剔除并呈现在 health_filtered。
    for _ in range(3):
        store.record_failure("qian-ds", "kind=timeout", cooldown_seconds=90)
    named = client.post("/api/v1/llm/routes/preview", headers=ADMIN,
                        json={"model": "gemini-3.8-flash"}).json()["data"]
    named_ids = [row["model_id"] for row in named["candidates"]]
    assert named_ids[:2] == ["axon-gemini", "qian-gemini"]  # 模型名聚合按严格优先级
    assert "qian-ds" in named["health_filtered_ids"]
    assert "qian-ds" not in named_ids
    assert any("explicit override" in note for note in named["notes"])

    intimate = client.post("/api/v1/llm/routes/preview", headers=ADMIN,
                           json={"session_key": "group:123", "message_text": "anything",
                                 "simulate_intimate": True}).json()["data"]
    assert intimate["intimate_simulated"] is True
    assert intimate["state_source"] == "simulated"
    assert intimate["candidates"][0]["model_id"] == "axon-grok"
    assert intimate["notes"] == []  # grok 本就第一，无回落

    # 熔断冷却中的 grok：投影给出钉一守卫放行回落 + demoted 呈现。
    store.record_failure("axon-grok", "kind=timeout", cooldown_seconds=90)
    before = store.snapshot("axon-grok")
    fallback = client.post("/api/v1/llm/routes/preview", headers=ADMIN,
                           json={"session_key": "group:123", "simulate_intimate": True}).json()["data"]
    assert "axon-grok" in fallback["demoted_ids"]
    assert fallback["candidates"][0]["model_id"] != "axon-grok"
    assert any("intimate_grok_fallback" in note for note in fallback["notes"])

    # 零副作用：preview 前后健康行原样（不写样本、不翻状态）。
    after = store.snapshot("axon-grok")
    assert before == after


def test_model_test_dry_validates_and_live_is_honest(api):
    client, _store = api
    dry = client.post("/api/v1/llm/models/axon-grok/test", headers=ADMIN, json={"mode": "dry"})
    assert dry.status_code == 200
    data = dry.json()["data"]
    assert data["mode"] == "dry" and data["status"] == "ok"
    assert any(check["name"] == "credential" and "fingerprint=" in check["detail"] for check in data["checks"])
    assert SECRET_GROK not in dry.text

    degraded = client.post("/api/v1/llm/models/qian-gemini/test", headers=ADMIN, json={"mode": "dry"})
    assert degraded.json()["data"]["status"] == "degraded"

    unknown = client.post("/api/v1/llm/models/no-such-model/test", headers=ADMIN, json={"mode": "dry"})
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "resource_not_found"

    denied = client.post("/api/v1/llm/models/axon-grok/test", headers=ADMIN, json={"mode": "live", "confirm": True})
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "permission_denied"

    unconfirmed = client.post("/api/v1/llm/models/axon-grok/test", headers=ROOT, json={"mode": "live"})
    assert unconfirmed.status_code == 409
    assert unconfirmed.json()["error"]["code"] == "confirmation_required"

    live = client.post("/api/v1/llm/models/axon-grok/test", headers=ROOT, json={"mode": "live", "confirm": True})
    assert live.status_code == 503
    assert live.json()["error"]["code"] == "not_configured"


def test_llm_config_preview_apply_and_reload_rbac(api):
    client, _store = api
    version = client.get("/api/v1/config", headers=ADMIN).json()["data"]["items"][0]["version"]

    preview = client.post("/api/v1/llm/config/preview", headers=ROOT, json={
        "expected_version": version,
        "changes": [{"key": "BOT_CHAT_TEMPERATURE", "value": "0.7"}],
    })
    assert preview.status_code == 200
    body = preview.json()["data"]
    assert body["applied"] is False
    assert body["items"][0]["value"] == 0.7
    # 预览不落盘：版本不变。
    assert client.get("/api/v1/config", headers=ADMIN).json()["data"]["items"][0]["version"] == version

    denied = client.post("/api/v1/llm/config/apply", headers=ADMIN, json={
        "expected_version": version, "changes": [{"key": "BOT_CHAT_TEMPERATURE", "value": "0.7"}]})
    assert denied.status_code == 403  # 读令牌越权写

    outside = client.post("/api/v1/llm/config/apply", headers=ROOT, json={
        "expected_version": version, "changes": [{"key": "BOT_QUIET_HOURS_ENABLED", "value": True}]})
    assert outside.status_code == 422
    assert outside.json()["error"]["code"] == "unsupported_parameter"  # 非 LLM 键不归本面

    applied = client.post("/api/v1/llm/config/apply", headers=ROOT, json={
        "expected_version": version,
        "changes": [{"key": "BOT_CHAT_TEMPERATURE", "value": "0.7"},
                    {"key": "BOT_CHAT_MAX_TOKENS", "value": "512"}],
    })
    assert applied.status_code == 200
    result = applied.json()["data"]
    assert result["applied"] is True and len(result["items"]) == 2
    assert result["version"] == version + 2  # 逐键 CAS 链式推进
    row = client.get("/api/v1/config/BOT_CHAT_TEMPERATURE", headers=ADMIN).json()["data"]
    assert row["state"] == "override" and row["value"] == 0.7

    reload_denied = client.post("/api/v1/llm/cache/reload", headers=ADMIN)
    assert reload_denied.status_code == 403
    reload = client.post("/api/v1/llm/cache/reload", headers=ROOT)
    assert reload.status_code == 200
    data = reload.json()["data"]
    assert data["reloaded"] is True and data["registry_size"] >= 4
    assert "llm.routes.reload" in data["note"]  # 作用域诚实：bot 进程需另行动作


def test_service_emits_audit_event_and_fingerprint_helper(tmp_path, env):
    published: list[Any] = []

    class Bus:
        def publish(self, event: Any) -> None:
            published.append(event)

    service = LLMControlService(_config(tmp_path), channel_health_store=ChannelHealthStore(str(tmp_path / "h.sqlite3")),
                                event_bus=Bus())
    result = service.reload()
    assert result["reloaded"] is True
    assert len(published) == 1
    assert published[0].source == "control_plane"
    assert published[0].category == "success"
    assert published[0].details["status"] == "llm_cache_reloaded"

    from plugins.bot_unified_runtime.control_plane.llm_admin import (
        credential_fingerprint,
    )
    assert credential_fingerprint("") == ""
    assert credential_fingerprint("abc") == hashlib.sha256(b"abc").hexdigest()[:12]
