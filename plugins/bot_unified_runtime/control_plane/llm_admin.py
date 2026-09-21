"""模型控制只读投影服务（核心要求 §十一；V21-ROUTE-001）。

HTTP 无关；对 ``llm/model_router.py`` / ``llm/channel_health.py`` **只读消费**：
注册表装配复用 build_model_registry/_preset_specs/_main_fallback_spec，候选序
投影复用 ModelRouter.route_ids/channels_for_model 与 _health_filter_candidates →
_demote_cooling_candidates → INTIMATE grok 钉一守卫的同一管线顺序
（model_router._generate_impl:1875-1909），本层不复制、不修改任何排序语义。

诚实边界（不在响应里假装）：
- 凭证只回 fingerprint（SHA-256 前 12 hex）+ 状态 + 密钥数，永不回明文或 env 名；
- routes/preview 是投影：会话滞回状态活在 bot 进程，控制面跨进程不可读，
  ``simulate_intimate`` 是显式模拟而非真实会话态；
- models/{id}/test 的 live（真实调用）端口本轮不实装，返回 503 not_configured；
- cache/reload 只重建控制面进程内投影缓存，bot 进程内路由缓存须经
  ``llm.routes.reload`` 动作（/api/v1/actions/...）才生效。
"""
from __future__ import annotations

import hashlib
import threading
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from .services import ControlServiceError

# 本轮不实装的诚实错误码（合同点名；contracts/errors.py 41 码之外，见席位日志）。
CODE_NOT_CONFIGURED = "not_configured"
LLM_CONFIG_PREFIXES = ("bot_chat_", "bot_model_", "bot_llm_", "bot_content_route_")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def credential_fingerprint(value: str) -> str:
    """凭证指纹：SHA-256 前 12 hex；空值返回空串。永不回明文。"""
    text = str(value or "")
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _safe_base_url(value: str) -> str:
    """base_url 只回 scheme+host+port，剥 query/fragment（防 URL 带密）。"""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parts = urlsplit(text)
        origin = f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else parts.netloc or text
        return origin.rstrip("/")
    except ValueError:
        return "<unparseable>"


class LLMControlService:
    """把 R1 路由注册表+渠道健康投影成 WebUI 可读的模型控制面。"""

    def __init__(
        self,
        config: object | None,
        *,
        channel_health_store: Any | None = None,
        config_service: Any | None = None,
        event_bus: Any | None = None,
        clock: Any = None,
    ) -> None:
        self.config = config
        self.channel_health_store = channel_health_store
        self.config_service = config_service
        self.event_bus = event_bus
        self._clock = clock or time.time
        self._lock = threading.Lock()
        self._router_cache: tuple[int, Any] | None = None
        self.rebuilt_at: str | None = None
        self.reload_count = 0

    # ---------- 注册表装配（只读复用 model_router 装配语义） ----------

    def _load_router(self) -> Any:
        from ..llm.model_router import (
            ModelRouter,
            _main_fallback_spec,
            _preset_specs,
            build_model_registry,
        )

        config = self.config
        registry = build_model_registry(config) if config is not None else {}
        main = _main_fallback_spec(config) if config is not None else None
        specs: dict[str, Any] = dict(registry)
        for name, spec in (_preset_specs(config) if config is not None else {}).items():
            specs.setdefault(name, spec)
        if main is not None:
            if registry:
                from dataclasses import replace

                main = replace(main, tags=("manual",), priority=2000)
            specs.setdefault(main.model_id, main)
        groups_cb = None
        if config is not None and getattr(config, "bot_model_priority_groups", None):
            groups_cb = lambda: getattr(config, "bot_model_priority_groups", [])
        return ModelRouter(
            specs,
            fallback_spec=main,
            timeout_seconds=float(getattr(config, "bot_chat_timeout_seconds", 30.0) or 30.0) if config is not None else 30.0,
            max_failover_seconds=float(getattr(config, "bot_chat_failover_max_seconds", 0.0) or 0.0) if config is not None else 0.0,
            priority_groups=groups_cb,
            credential_config=config,
        )

    def _router(self) -> Any:
        # 缓存失效只由 reload() 驱动：注册表动态面（dynamic_registry）属 bot
        # 进程，控制面投影不追踪；响应里以 rebuilt_at 标注投影时刻。
        with self._lock:
            if self._router_cache is None:
                self._router_cache = (self.reload_count, self._load_router())
                self.rebuilt_at = _utc_now_iso()
            return self._router_cache[1]

    def reload(self) -> dict[str, Any]:
        """重建控制面进程内投影缓存（不触碰 bot 进程内路由缓存——诚实标注）。"""
        with self._lock:
            self.reload_count += 1
            self._router_cache = (self.reload_count, self._load_router())
            self.rebuilt_at = _utc_now_iso()
            size = len(getattr(self._router_cache[1], "specs", {}) or {})
        self._emit("llm_cache_reloaded")
        return {
            "reloaded": True, "scope": "control_plane_projection_cache",
            "registry_size": size, "rebuilt_at": self.rebuilt_at,
            "note": "bot 进程内路由缓存需经 llm.routes.reload 动作生效",
        }

    def _specs(self) -> dict[str, Any]:
        return dict(getattr(self._router(), "specs", {}) or {})

    # ---------- 健康库（可注入；不可用时诚实 unknown） ----------

    def _health(self):
        store = self.channel_health_store
        if store is None:
            try:
                from ..llm.channel_health import get_channel_health_store

                store = get_channel_health_store()
            except Exception:  # noqa: BLE001 - 健康层不可用按 unknown 投影。
                return None
        for name in ("snapshot", "cooling_ids", "unavailable_ids", "ema_latencies"):
            if not callable(getattr(store, name, None)):
                return None
        return store

    def _channel_health_row(self, model_id: str) -> dict[str, Any]:
        store = self._health()
        row = store.snapshot(model_id) if store is not None else None
        if not row:
            return {"state": "unknown", "reason": "no_sample" if store is not None else "source_unavailable",
                    "ema_ms": None, "samples": 0, "consecutive_fails": 0,
                    "cooldown_active": False, "last_ok_at": None}
        return {
            "state": str(row.get("state") or "unknown"),
            "ema_ms": row.get("ema_ms"),
            "samples": int(row.get("samples") or 0),
            "consecutive_fails": int(row.get("consecutive_fails") or 0),
            "cooldown_active": bool(store is not None and model_id in store.cooling_ids()),
            "last_ok_at": row.get("last_ok_at") or None,
        }

    # ---------- provider / channel / model 投影 ----------

    @staticmethod
    def _provider_id(spec: Any) -> str:
        origin = _safe_base_url(spec.base_url) or "unknown-origin"
        return "prov-" + hashlib.sha256(origin.encode("utf-8")).hexdigest()[:10]

    def providers(self) -> tuple[dict[str, Any], ...]:
        grouped: dict[str, dict[str, Any]] = {}
        for spec in self._specs().values():
            origin = _safe_base_url(spec.base_url) or "unknown-origin"
            pid = self._provider_id(spec)
            entry = grouped.setdefault(pid, {
                "provider_id": pid, "label": origin, "origin": origin,
                "channel_ids": [], "models": [], "credentials_configured": 0, "channels": 0,
            })
            entry["channel_ids"].append(spec.model_id)
            if spec.model not in entry["models"]:
                entry["models"].append(spec.model)
            keys = spec.all_api_keys()
            entry["channels"] += 1
            entry["credentials_configured"] += 1 if keys else 0
        for entry in grouped.values():
            entry["channel_ids"].sort()
            entry["models"].sort()
        return tuple(sorted(grouped.values(), key=lambda item: item["provider_id"]))

    def channels(self) -> tuple[dict[str, Any], ...]:
        from ..llm.model_router import model_family

        items = []
        for spec in sorted(self._specs().values(), key=lambda s: (s.priority, s.model_id)):
            keys = spec.all_api_keys()
            items.append({
                "channel_id": spec.model_id,
                "model": spec.model,
                "model_family": model_family(spec.model),
                "provider_id": self._provider_id(spec),
                "origin": _safe_base_url(spec.base_url),
                "priority": spec.priority,
                "tags": list(spec.tags),
                "routing_group": spec.routing_group,
                "effort_override": spec.effort or "",
                "auto_routable": "manual" not in spec.tags,
                "health": self._channel_health_row(spec.model_id),
                "credential": {
                    "state": "configured" if keys else "missing",
                    "fingerprint": credential_fingerprint(keys[0]) if keys else None,
                    "key_count": len(keys),
                },
                "price_per_m": {k: v for k, v in (
                    ("input", spec.price_in), ("output", spec.price_out),
                    ("cache_read", spec.price_cache_read), ("cache_creation", spec.price_cache_creation),
                ) if v is not None} or None,
                "price_per_call": spec.price_per_call,
            })
        return tuple(items)

    def models(self) -> tuple[dict[str, Any], ...]:
        from ..llm.model_router import (
            FAMILY_EFFORT_TIERS,
            baseline_effort,
            default_effort,
            model_family,
        )

        specs = self._specs()
        grouped: dict[str, list[Any]] = {}
        for spec in specs.values():
            grouped.setdefault(spec.model, []).append(spec)
        items = []
        for name, members in sorted(grouped.items()):
            ordered_ids = self._router().channels_for_model(name)
            by_id = {spec.model_id: spec for spec in members}
            channel_rows = []
            for cid in ordered_ids or sorted(by_id):
                spec = by_id[cid]
                channel_rows.append({
                    "channel_id": cid, "priority": spec.priority,
                    "health_state": self._channel_health_row(cid)["state"],
                    "price_per_m_input": spec.price_in, "price_per_m_output": spec.price_out,
                })
            prices_in = [s.price_in for s in members if s.price_in is not None]
            prices_out = [s.price_out for s in members if s.price_out is not None]
            family = model_family(name)
            items.append({
                "model": name,
                "model_id": name,
                "family": family,
                "channel_count": len(members),
                "channels": channel_rows,
                "priority": min(spec.priority for spec in members),
                "auto_routable": any("manual" not in spec.tags for spec in members),
                "effort": {
                    "baseline": baseline_effort(name),
                    "max": default_effort(name),
                    "family_tiers": list(FAMILY_EFFORT_TIERS.get(family, ())),
                    "overrides": {spec.model_id: spec.effort for spec in members if spec.effort},
                },
                "price_range_per_m": {
                    "input": [min(prices_in), max(prices_in)] if prices_in else None,
                    "output": [min(prices_out), max(prices_out)] if prices_out else None,
                },
            })
        return tuple(items)

    # ---------- 详情 ----------

    def provider(self, provider_id: str) -> dict[str, Any] | None:
        for item in self.providers():
            if item["provider_id"] == provider_id:
                channels = [row for row in self.channels() if row["provider_id"] == provider_id]
                return {**item, "channels": channels}
        return None

    def channel(self, channel_id: str) -> dict[str, Any] | None:
        for item in self.channels():
            if item["channel_id"] == channel_id:
                return item
        return None

    def model(self, model_id: str) -> dict[str, Any] | None:
        for item in self.models():
            if item["model_id"] == model_id:
                return item
        # 兼容按注册条目 id 查模型：条目 id → 所属模型聚合。
        spec = self._specs().get(model_id)
        if spec is not None:
            return next((item for item in self.models() if item["model"] == spec.model), None)
        return None

    # ---------- health / routes ----------

    def health_view(self) -> dict[str, Any]:
        from ..llm.channel_health import (
            channel_health_enabled,
            channel_health_latency_first,
        )

        store = self._health()
        enabled = bool(channel_health_enabled(self.config)) if self.config is not None else False
        cooling = sorted(store.cooling_ids()) if store is not None and enabled else []
        unavailable = sorted(store.unavailable_ids()) if store is not None and enabled else []
        states = [self._channel_health_row(spec.model_id)["state"] for spec in self._specs().values()]
        totals = {key: states.count(key) for key in ("ok", "unavailable", "unknown") if states.count(key)}
        if not enabled:
            status = "disabled"
        elif unavailable or cooling:
            status = "degraded"
        else:
            status = "ok"
        return {
            "status": status,
            "health_layer_enabled": enabled,
            "latency_first": bool(channel_health_latency_first(self.config)) if self.config is not None else False,
            "totals": totals,
            "cooling_ids": cooling,
            "unavailable_ids": unavailable,
            "source": "channel_health_store" if store is not None and enabled else ("disabled" if not enabled else "source_unavailable"),
            "generated_at": _utc_now_iso(),
        }

    def routes_view(self) -> dict[str, Any]:
        from ..llm.channel_health import (
            channel_health_enabled,
            channel_health_latency_first,
        )

        config = self.config
        router = self._router()
        active_name, group_order = ("", [])
        try:
            active_name, group_order = router._active_group_order()
        except Exception:  # noqa: BLE001 - 分组读取失败投影为未配置。
            active_name, group_order = ("", [])
        models = []
        for item in self.models():
            if not item["auto_routable"]:
                continue
            models.append({"model": item["model"], "channels": item["channels"]})
        return {
            "policy": {
                "strict_priority": bool(getattr(config, "bot_chat_strict_priority", True)) if config is not None else True,
                "latency_first": bool(channel_health_latency_first(config)) if config is not None else False,
                "health_layer_enabled": bool(channel_health_enabled(config)) if config is not None else False,
                "failover_max_seconds": float(getattr(config, "bot_chat_failover_max_seconds", 0.0) or 0.0) if config is not None else 0.0,
                "failover_min_hop_seconds": float(getattr(config, "bot_chat_failover_min_hop_seconds", 3.0) or 3.0) if config is not None else 3.0,
                "timeout_seconds": float(getattr(config, "bot_chat_timeout_seconds", 30.0) or 30.0) if config is not None else 30.0,
                "max_input_tokens": int(getattr(config, "bot_chat_max_input_tokens", 0) or 0) if config is not None else 0,
                "max_output_tokens": int(getattr(config, "bot_chat_max_output_tokens", 0) or 0) if config is not None else 0,
                "priority_groups": {"count": len(getattr(config, "bot_model_priority_groups", []) or []) if config is not None else 0,
                                    "active_name": active_name, "active_order": group_order},
            },
            "routes": models,
        }

    # ---------- routes/preview（R1 管线只读投影） ----------

    def preview_routes(
        self,
        *,
        override: str = "",
        model: str = "",
        session_key: str = "",
        message_text: str = "",
        simulate_intimate: bool = False,
    ) -> dict[str, Any]:
        from ..llm.model_router import (
            _demote_cooling_candidates,
            _health_filter_candidates,
            model_family,
        )

        router = self._router()
        content_cb = self._simulate_content_cb(simulate_intimate)
        saved_cb = getattr(router, "_content_route_cb", None)
        # override（渠道/条目 id）与 model（模型名聚合）都走 route_ids 的显式
        # 指定分支；语义=显式指定不受内容路由摆布（notes 里如实标注）。
        effective_override = str(override or model or "").strip()
        try:
            router._content_route_cb = content_cb
            routed_ids = router.route_ids(
                message_text=str(message_text or ""),
                override=effective_override,
                session_key=str(session_key or ""),
            )
        finally:
            router._content_route_cb = saved_cb
        candidates = _health_filter_candidates(routed_ids, self.config)
        health_filtered = [cid for cid in routed_ids if cid not in set(candidates)]
        candidates, demoted = _demote_cooling_candidates(candidates, self.config)
        specs = self._specs()
        notes: list[str] = []
        if effective_override:
            notes.append("explicit override：内容路由不影响显式指定（route_ids 语义）")
        if simulate_intimate:
            grok_ids = {
                cid for cid in routed_ids
                if (spec := specs.get(cid)) is not None and model_family(spec.model) == "grok"
            }
            if grok_ids and candidates and candidates[0] not in grok_ids:
                notes.append("intimate_grok_fallback：grok 熔断冷却/健康不可用，临时回落（钉一守卫放行）")
        rows = []
        for cid in candidates:
            spec = specs.get(cid)
            health = self._channel_health_row(cid)
            rows.append({
                "model_id": cid,
                "model": spec.model if spec is not None else cid,
                "priority": spec.priority if spec is not None else None,
                "health_state": health["state"],
                "ema_ms": health["ema_ms"],
                "cooldown_active": health["cooldown_active"],
            })
        return {
            "input": {"override": override or None, "model": model or None,
                      "session_key": session_key or None,
                      "simulate_intimate": bool(simulate_intimate)},
            "mode": "override" if override else ("model" if model else "auto"),
            "intimate_simulated": bool(simulate_intimate),
            "state_source": "simulated" if simulate_intimate else
                ("not_available_cross_process" if session_key else "none"),
            "demoted_ids": demoted,
            "health_filtered_ids": health_filtered,
            "notes": notes,
            "candidates": rows,
            "generated_at": _utc_now_iso(),
        }

    def _simulate_content_cb(self, simulate_intimate: bool):
        """构造只读模拟 verdict 回调（投影 content_route.route_verdict 的
        INTIMATE head_models 推导，content_route.py:288-296；不触碰真实会话态）。"""
        if not simulate_intimate:
            return None
        config = self.config
        route_model = str(getattr(config, "bot_content_route_model", "grok-4.6") or "grok-4.6").strip()
        order = [
            piece.strip()
            for piece in str(getattr(config, "bot_content_route_order", "") or "").split(",")
            if piece.strip()
        ]
        head: list[str] = []
        seen: set[str] = set()
        for name in [route_model, *[n for n in order if n != route_model]]:
            if name and name not in seen:
                seen.add(name)
                head.append(name)
        verdict = {"mode": "intimate", "head_models": head}

        def cb(session_key: str, text: str) -> dict[str, Any]:
            return dict(verdict)

        return cb

    # ---------- 单模型 dry 校验（不联网） ----------

    def test_model(self, model_id: str, *, mode: str = "dry") -> dict[str, Any]:
        specs = self._specs()
        spec = specs.get(model_id)
        if spec is None:
            # 按模型名聚合解析：任一渠道存在即可校验。
            members = [s for s in specs.values() if s.model.lower() == str(model_id).strip().lower()]
            spec = min(members, key=lambda s: (s.priority, s.model_id), default=None)
        if spec is None:
            raise ControlServiceError("resource_not_found", "要找的模型不存在。", 404)
        keys = spec.all_api_keys()
        checks = [
            {"name": "registered", "state": "ok", "detail": spec.model_id},
            {"name": "model_name", "state": "ok" if spec.model else "failed", "detail": spec.model or "missing"},
            {"name": "base_url", "state": "ok" if spec.base_url else "failed", "detail": _safe_base_url(spec.base_url) or "missing"},
            {"name": "credential", "state": "ok" if keys else "failed",
             "detail": f"fingerprint={credential_fingerprint(keys[0]) if keys else '-'} keys={len(keys)}"},
            {"name": "effort", "state": "ok", "detail": spec.effort or "baseline"},
        ]
        status = "ok" if all(item["state"] == "ok" for item in checks) else "degraded"
        return {
            "model_id": spec.model_id, "model": spec.model, "mode": mode,
            "status": status, "checks": checks,
            "health": self._channel_health_row(spec.model_id),
            "note": "dry 仅校验注册与参数，不产生网络调用" if mode == "dry" else "",
        }

    # ---------- LLM 配置面（复用 ConfigControlService 语义） ----------

    @staticmethod
    def _llm_key(key: str) -> str:
        lowered = str(key or "").strip().lower()
        if not lowered.startswith(LLM_CONFIG_PREFIXES):
            raise ControlServiceError("unsupported_parameter", "该配置键不属于模型控制面。", 422)
        return lowered

    def config_preview(self, changes: list[dict[str, Any]], *, principal: Any,
                       expected_version: int, request_id: str) -> dict[str, Any]:
        service = self.config_service
        if service is None:
            raise ControlServiceError("config_store_unavailable", "配置控制服务尚未装配。", 503)
        projected = []
        for change in changes:
            key = self._llm_key(str(change.get("key", "")))
            row = service.preview(key, change.get("value"), principal=principal,
                                  expected_version=expected_version, request_id=request_id)
            projected.append(row)
        return {"items": projected, "applied": False, "version": expected_version}

    def config_apply(self, changes: list[dict[str, Any]], *, principal: Any,
                     expected_version: int, request_id: str) -> dict[str, Any]:
        service = self.config_service
        if service is None:
            raise ControlServiceError("config_store_unavailable", "配置控制服务尚未装配。", 503)
        normalized = [(self._llm_key(str(change.get("key", ""))), change.get("value")) for change in changes]
        applied = []
        version = expected_version
        try:
            for key, value in normalized:
                row = service.set(key, value, principal=principal, expected_version=version, request_id=request_id)
                version = int(row.get("version", version))
                applied.append(row)
        except ControlServiceError as exc:
            self._emit("llm_config_apply_failed", category="warning", error_code=exc.code)
            raise
        self._emit("llm_config_applied")
        return {"items": applied, "applied": True, "version": version}

    # ---------- 审计事件 ----------

    def _emit(self, operation: str, *, category: str = "success", error_code: str = "") -> None:
        """发控制面审计事件；RuntimeLogEvent details 是低基数白名单模式
        （events.py DETAIL_KEYS），语义载荷走 status/error_code 两个白名单键，
        计数与明细由 HTTP 响应与 ControlPlaneAuditStore（subject/method/path）承载。"""
        bus = self.event_bus
        if bus is None or not callable(getattr(bus, "publish", None)):
            return
        details: dict[str, Any] = {"status": operation}
        if error_code:
            details["error_code"] = error_code
        try:
            from .events import RuntimeLogEvent

            bus.publish(RuntimeLogEvent(source="control_plane", category=category,
                                        message="llm_control", details=details))
        except Exception:  # noqa: BLE001 - 审计事件失败不阻塞主响应。
            return
