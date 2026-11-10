"""Versioned control-plane resources for the future WebUI.

This module is intentionally a thin HTTP projection.  It does not expose
Runtime SQLite files, environment values, or internal Python objects.
"""
# ruff: noqa: B008

from __future__ import annotations

import hmac
from copy import deepcopy
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response

from ..api import ControlPlaneError
from ..auth import Principal
from ..features import FeatureState
from ..resources import ResourceMetricsService
from ..services import FeatureControlService
from .protocol import (
    ERROR_RESPONSES,
    ApiEnvelope,
    ConfigValuePayload,
    ConfigWriteResetPayload,
    ConfigWriteValuePayload,
    FeatureChangePayload,
    FeatureItem,
    FeatureList,
    FeatureMutationResult,
    FeaturePreviewPayload,
    FeaturePreviewResult,
    FeatureTree,
    ResourceSnapshot,
    envelope,
)

_ok = envelope


def build_v1_router(
    *,
    feature_service: FeatureControlService,
    config: object | None,
    settings_store: Any | None,
    config_service: Any | None = None,
    metrics_service: Any | None = None,
    resource_service: ResourceMetricsService | None = None,
    runtime_attached: bool = False,
    config_command_gateway: Any | None = None,
    allow_direct_config_write: bool | None = None,
    read_dependency: Any,
    write_dependency: Any,
    event_log: Any | None = None,
    event_service: Any | None = None,
    log_collector: Any | None = None,
    action_service: Any | None = None,
    workspace_service: Any | None = None,
    channel_health_store: Any | None = None,
    event_bus: Any | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", responses=ERROR_RESPONSES)
    resources_service = resource_service or ResourceMetricsService(runtime_attached=runtime_attached)

    @router.get("/protocol")
    def protocol_manifest(principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        return _ok({
            "schema_version": "v1", "openapi_path": "/api/v1/openapi.json",
            "runtime_binding": "live" if runtime_attached else "storage_only",
            "services": {
                "features": {"available": True, "graph_cas": feature_service.graph_cas_enabled, "coverage": "routes_internal_commands_and_explicit_subfeatures", "subfeatures_complete": False, "subfeature_catalog_kind": "sub_feature", "execution_snapshot": "per_event", "reload_drain": False},
                "config": {"available": config_service is not None},
                "events": {"available": event_service is not None, "transport": "sse", "console_collectors": "process_summaries" if log_collector is not None and log_collector.active else "not_connected"},
                "metrics": {"available": metrics_service is not None, "coverage": "ledger_only"},
                "resources": {"available": True, "sampling": "on_demand", "coverage": "current_process", "history": True},
                "workspaces": {"available": workspace_service is not None,
                    "sandbox_generation": workspace_service is not None and workspace_service.sandbox_generator is not None,
                    "default_persona_profile_id": workspace_service.default_persona_profile_id if workspace_service is not None else None,
                    "real_session": workspace_service is not None and workspace_service.real_adapter is not None}, "traces": {"available": False},
                "actions": {"available": action_service is not None}, "persona_versions": {"available": False},
            },
        })

    @router.get("/openapi.json")
    def openapi_schema(request: Request, principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        schema = deepcopy(request.app.openapi())
        schema.setdefault("components", {}).setdefault("securitySchemes", {})["ControlPlaneBearer"] = {
            "type": "http", "scheme": "bearer",
            "description": "Authorization header only; writes require a distinct super-admin token.",
        }
        for path, operations in schema["paths"].items():
            if path.startswith("/api/v1/"):
                for method, operation in operations.items():
                    if method in {"get", "post", "put", "patch", "delete"}:
                        operation["security"] = [{"ControlPlaneBearer": []}]
        return _ok(schema)

    @router.get("/features", response_model=ApiEnvelope[FeatureList])
    def list_features(
        principal: Principal = Depends(read_dependency),
        kind: str | None = Query(default=None),
        enabled: bool | None = Query(default=None),
        search: str = Query(default="", max_length=200),
    ) -> dict[str, Any]:
        return _ok({"items": feature_service.list_features(kind=kind, enabled=enabled, search=search)})

    @router.get("/features/tree", response_model=ApiEnvelope[FeatureTree])
    def feature_tree(principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        return _ok({"items": feature_service.tree()})

    @router.get("/features/{feature_id}", response_model=ApiEnvelope[FeatureItem])
    def feature_detail(feature_id: str, principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        return _ok(feature_service.detail(feature_id))

    @router.get("/features/{feature_id}/children", response_model=ApiEnvelope[FeatureList])
    def feature_children(feature_id: str, principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        return _ok({"items": feature_service.children(feature_id)})

    @router.get("/features/{feature_id}/state", response_model=ApiEnvelope[FeatureState])
    def feature_state(feature_id: str, principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        return _ok(feature_service.detail(feature_id)["state"])

    @router.post("/features/{feature_id}/preview", response_model=ApiEnvelope[FeaturePreviewResult])
    def preview_feature(feature_id: str, payload: FeaturePreviewPayload, request: Request, principal: Principal = Depends(write_dependency)) -> dict[str, Any]:
        return _ok(feature_service.change(feature_id, payload.enabled, principal=principal, expected_version=payload.expected_version, expected_revision=payload.expected_revision, preview=True))

    def change_feature(feature_id: str, enabled: bool | None, payload: FeatureChangePayload, principal: Principal, request: Request) -> dict[str, Any]:
        return _ok(feature_service.change(feature_id, enabled, principal=principal, expected_version=payload.expected_version, expected_revision=payload.expected_revision, request_id=request.state.cp_request_id))

    @router.post("/features/{feature_id}/enable", response_model=ApiEnvelope[FeatureMutationResult])
    def enable_feature(feature_id: str, payload: FeatureChangePayload, request: Request, principal: Principal = Depends(write_dependency)) -> dict[str, Any]:
        return change_feature(feature_id, True, payload, principal, request)

    @router.post("/features/{feature_id}/disable", response_model=ApiEnvelope[FeatureMutationResult])
    def disable_feature(feature_id: str, payload: FeatureChangePayload, request: Request, principal: Principal = Depends(write_dependency)) -> dict[str, Any]:
        return change_feature(feature_id, False, payload, principal, request)

    @router.post("/features/{feature_id}/reset", response_model=ApiEnvelope[FeatureMutationResult])
    def reset_feature(feature_id: str, payload: FeatureChangePayload, request: Request, principal: Principal = Depends(write_dependency)) -> dict[str, Any]:
        return change_feature(feature_id, None, payload, principal, request)

    @router.get("/features/{feature_id}/audit")
    def feature_audit(feature_id: str, principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        return _ok({"items": list(feature_service.audit(feature_id))})

    def require_config_service():
        if config_service is None:
            raise ControlPlaneError(503, "config_store_unavailable", "配置控制服务尚未装配。")
        return config_service

    def require_command_gateway():
        if config_command_gateway is None:
            raise ControlPlaneError(503, "config_command_gateway_unavailable", "配置命令面尚未装配。")
        return config_command_gateway

    def _filtered(method: str, fallback: str, principal: Principal, **kwargs: Any) -> Any:
        """HTTP 读面优先走主体过滤版本；服务未提供该方法时退回旧全量（直呼兼容）。

        🔴 回落**只直呼旧签名**、绝不把 ``principal`` 塞过去：``schema()``/``list()``/
        ``changes()`` 都不吃主体参数，塞过去就是 ``TypeError``——2026-11 那场
        ``/config``、``/config/schema``、``/config/catalog``、``/config/changes``
        四端点恒 500 的真根因。过滤方法的真身在 ``ConfigControlService``
        （``catalog`` / ``list_for_principal`` / ``changes_for_principal``）。
        """
        service = require_config_service()
        filtered = getattr(service, method, None)
        if callable(filtered):
            return filtered(principal=principal, **kwargs)
        return getattr(service, fallback)()

    @router.get("/config")
    def list_config(principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        return _ok({"items": _filtered("list_for_principal", "list", principal)})

    @router.get("/config/schema")
    def config_schema(principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        return _ok({"items": _filtered("list_for_principal", "schema", principal)})

    @router.get("/config/catalog")
    def config_catalog(principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        return _ok({"items": _filtered("catalog", "schema", principal=principal)})

    @router.get("/config/changes")
    def config_changes(principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        return _ok({"items": _filtered("changes_for_principal", "changes", principal=principal)})

    @router.get("/config/commands")
    def list_config_commands(principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        return _ok({"items": require_command_gateway().list_own(principal=principal)})

    @router.get("/config/commands/{command_id}")
    def get_config_command(command_id: str, principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        return _ok(require_command_gateway().status(principal=principal, command_id=command_id))

    @router.get("/config/{key}")
    def get_config(key: str, principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        service = require_config_service()
        getter = getattr(service, "get_for_principal", None)
        if callable(getter):
            # 直读单键也走主体过滤：看不见的键 404，堵「按名枚举读危险键」的绕路。
            return _ok(getter(principal=principal, key=key))
        return _ok(service.get(key))

    @router.post("/config/{key}/preview")
    def preview_config(key: str, payload: ConfigValuePayload, request: Request, principal: Principal = Depends(write_dependency)) -> dict[str, Any]:
        return _ok(require_config_service().preview(key, payload.value, principal=principal, expected_version=payload.expected_version, request_id=request.state.cp_request_id))

    def _idempotency_key(request: Request) -> str:
        # 命令面的幂等键走独立请求头：重试要复用同一串才叫幂等（request_id 每次不同）。
        return str(request.headers.get("idempotency-key", "") or "").strip()

    def _owner_consent_granted(request: Request) -> bool:
        """校验独立的「所有者授权口令」请求头。

        与 Bearer API token 是**两把不同的钥匙**：API token 不能替自己批准写入，
        只有部署显式打开 `bot_control_plane_allow_owner_consent` 且持独立 secret
        的调用方才拿得到这条通道。缺省关闭时本函数恒 False（行为与旧版一致）。
        """
        if config is None:
            return False
        if not bool(getattr(config, "bot_control_plane_allow_owner_consent", False)):
            return False
        expected = str(getattr(config, "bot_control_plane_owner_secret", "") or "")
        presented = str(request.headers.get("x-owner-consent", "") or "")
        if not expected or not presented:
            return False
        if not hmac.compare_digest(presented, expected):
            raise ControlPlaneError(403, "owner_consent_invalid", "所有者授权口令不正确。")
        return True

    def _submit_command(key: str, payload: Any, request: Request, principal: Principal, response: Any, *, reset: bool, owner_consent: bool = False) -> dict[str, Any]:
        idempotency_key = _idempotency_key(request)
        if not idempotency_key:
            raise ControlPlaneError(422, "config_command_idempotency_required", "命令面写操作必须带 Idempotency-Key 请求头。")
        gateway = require_command_gateway()
        dto = gateway.submit(
            principal=principal, key=key, value=None if reset else payload.value,
            reset=reset, expected_version=payload.expected_version,
            idempotency_key=idempotency_key, scope=str(getattr(payload, "session_key", "") or ""),
            owner_consent=owner_consent,
        )
        response.status_code = 202
        return _ok(dto)

    def _require_legacy_write_allowed() -> None:
        # 缺执行方/批准通路 ⇒ **禁直写**（用户最高口径：缺执行方/批准通路禁止落库）。
        # 只有两条**明确信任**的腿放行：① 父 app 显式 `allow_direct_config_write=True`；
        # ② 同进程 `runtime_attached=True`（Bot 宿主内旧腿）。缺省 `None`（未表态）**不再**
        # 自动直写——独立控制面必须走命令面（缺门 fail-closed，操作包 A 段）。
        if allow_direct_config_write is not True and not runtime_attached:
            raise ControlPlaneError(
                503, "config_write_requires_command_gateway",
                "独立控制面不允许直写配置，请经命令面提交或由 Bot 进程执行。",
            )

    @router.post("/config/{key}/set")
    def set_config(key: str, payload: ConfigWriteValuePayload, request: Request, response: Response, principal: Principal = Depends(write_dependency)) -> dict[str, Any]:
        owner_consent = _owner_consent_granted(request)
        if config_command_gateway is not None:
            return _submit_command(key, payload, request, principal, response, reset=False, owner_consent=owner_consent)
        _require_legacy_write_allowed()
        return _ok(require_config_service().set(key, payload.value, principal=principal, expected_version=payload.expected_version, request_id=request.state.cp_request_id, session_key=payload.session_key, owner_consent=owner_consent))

    @router.post("/config/{key}/reset")
    def reset_config(key: str, payload: ConfigWriteResetPayload, request: Request, response: Response, principal: Principal = Depends(write_dependency)) -> dict[str, Any]:
        owner_consent = _owner_consent_granted(request)
        if config_command_gateway is not None:
            return _submit_command(key, payload, request, principal, response, reset=True, owner_consent=owner_consent)
        _require_legacy_write_allowed()
        return _ok(require_config_service().reset(key, principal=principal, expected_version=payload.expected_version, request_id=request.state.cp_request_id, session_key=payload.session_key, owner_consent=owner_consent))

    if event_service is None:
        @router.get("/logs")
        def logs(limit: int = Query(default=50, ge=1, le=500), level: str = Query(default="INFO"), principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
            del principal
            if event_log is None:
                raise ControlPlaneError(503, "logs_unavailable", "日志采集器尚未接入。")
            rows = event_log.read_recent(limit=limit, min_level=level)
            return _ok({"items": rows, "source": "runtime_event_log"})
    
        @router.get("/logs/sources")
        def log_sources(principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
            del principal
            return _ok({"items": ["bot", "nonebot", "snowluma", "control_plane", "decision_engine", "pipeline", "sender", "llm", "database", "scheduler"]})

    from .actions import build_actions_router
    router.include_router(build_actions_router(service=action_service,
        read_dependency=read_dependency, write_dependency=write_dependency))

    @router.get("/metrics/resources/history")
    def resource_history(principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        del principal
        return _ok(resources_service.history())

    @router.get("/metrics/resources", response_model=ApiEnvelope[ResourceSnapshot])
    def resources(principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        del principal
        return _ok(resources_service.snapshot())

    def metrics_data(method: str, **kwargs: Any) -> dict[str, Any]:
        if metrics_service is None:
            return {"status": "source_unavailable", "reason": "not_connected", "data": None}
        result = getattr(metrics_service, method)(**kwargs)
        if result["status"] == "invalid_request":
            raise ControlPlaneError(422, "metrics_invalid_query", "指标查询参数无效。")
        return result

    @router.get("/metrics/overview")
    def metrics_overview(principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        return _ok({"resources": resources_service.snapshot(), "usage": metrics_data("overview")})

    @router.get("/metrics/models")
    def metrics_models(limit: int = Query(default=100, ge=1, le=100), principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        return _ok(metrics_data("models", limit=limit))

    @router.get("/metrics/sessions")
    def metrics_sessions(limit: int = Query(default=100, ge=1, le=100), principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        return _ok(metrics_data("sessions", limit=limit))

    @router.get("/metrics/tokens")
    def metrics_tokens(principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        return _ok(metrics_data("overview"))

    @router.get("/metrics/trends")
    def metrics_trends(bucket: str = Query(default="hour"), limit: int = Query(default=100, ge=1, le=100), principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        return _ok(metrics_data("trends", bucket=bucket, limit=limit))

    # 显式 operation_id：本 stub 与 platform.py 真数据 /api/v1/traces 同路径
    # 同方法（platform 路由先注册），不区分会撞出 Duplicate Operation ID
    # 并在 openapi schema 里覆写真端点（2026-09-18 RK5 席清零）。
    @router.get("/traces", operation_id="traces_stub_api_v1_traces_get")
    def traces(principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        del principal
        raise ControlPlaneError(503, "traces_unavailable", "调用轨迹数据源尚未接入。")

    from ..llm_admin import LLMControlService
    from .llm import build_llm_router

    llm_service = LLMControlService(
        config,
        channel_health_store=channel_health_store,
        config_service=config_service,
        event_bus=event_bus,
    )
    router.include_router(build_llm_router(
        service=llm_service, read_dependency=read_dependency, write_dependency=write_dependency))
    from plugins.bot_unified_runtime.domains.creation.image.routes import (
        build_image_router,
    )
    from plugins.bot_unified_runtime.domains.creation.tts.routes import build_tts_router

    from .workspaces import build_workspaces_router
    router.include_router(build_workspaces_router(service=workspace_service, dependency=write_dependency))
    # 语音合成 job 走中央能力缝（P4-C4）：本路由体内唯一执行出口是 default_invoker()，
    # 禁直调 creation/media 两侧真身——第二通路即账面假绿（tests/test_control_plane_tts_api.py 执法）。
    router.include_router(build_tts_router(
        config=config, read_dependency=read_dependency, write_dependency=write_dependency))
    # AI 绘图 job 走**同一条**中央能力缝（S262 面③ A 案，照语音同构）：唯一执行出口仍是
    # default_invoker()，禁直调 image/engine_provider 或 provider_factory——第二通路即账面
    # 假绿（tests/test_control_plane_image_api.py 执法）。缺 provider ⇒ 诚实 503 可见。
    router.include_router(build_image_router(
        config=config, read_dependency=read_dependency, write_dependency=write_dependency))

    return router





