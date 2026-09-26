"""控制面 app 工厂与独立 uvicorn 启动（B4 M1 §3.2/§10）。

仅在 :mod:`__init__` 惰性导出时才被导入——控制面关闭态零导入副作用。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from . import ControlPlaneSettings, control_plane_settings, is_loopback_host
from .api import ControlPlaneError, error_body, new_debug_id
from .api.health import build_health_router, build_healthz_router
from .api.protocol import envelope, new_request_id, request_id_context
from .api.v1 import build_v1_router
from .audit import ControlPlaneAuditStore
from .auth import BearerAuthenticator, Principal
from .factory import _path, build_feature_service
from .services import ControlServiceError, FeatureControlService

logger = logging.getLogger(__name__)

_PUBLIC_CONFIRM_FILENAME = "control_plane_public.confirmed"

_PLATFORM_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


def _apply_platform_log_level(level: str) -> bool:
    """V21-risk-4：平台路由 /logs/level 的真实 setter（root logger）。

    与 _default_action 的 logging.level 同语义；不支持的级别（loguru 专属的
    success/detail 等）返回 False，由平台路由如实上报 applied=false（V21-risk-3
    契约：setter 自报失败不得假称已应用）。
    """
    upper = str(level).upper()
    if upper not in _PLATFORM_LOG_LEVELS:
        return False
    logging.getLogger().setLevel(upper)
    return True


def _split_host_port(value: str, *, default_port: int | None) -> tuple[str, int] | None:
    """解析 ``host[:port]`` 为 ``(小写 host, int 端口)``；畸形返回 None。

    取舍（审查 P-01，收紧优先）：
    - host 不区分大小写（RFC 9110），统一小写后比较；端口按整数值比较
      （前导零等价——DNS rebinding 防护关注 host 归属，端口数值化不扩面）；
    - IPv6 字面量必须带方括号（裸 ``::1`` 无歧义解析方式，一律拒）；
    - 省端口时：白名单条目继承 ``default_port``（控制面端口），请求 Host
      头传 ``default_port=None`` 严格拒绝——服务监听非默认端口时，合规
      客户端（浏览器/curl/HTTP 库）必带端口，缺端口即异常信号，不做
      80/443 默认端口推断。
    """
    text = value.strip()
    if not text:
        return None
    port_part = ""
    if text.startswith("["):
        host, sep, rest = text[1:].partition("]")
        if not sep:
            return None
        if rest and not rest.startswith(":"):
            return None
        port_part = rest[1:] if rest else ""
    else:
        host, sep, tail = text.partition(":")
        if ":" in tail:  # 多冒号：非 bracket 写法一律畸形。
            return None
        if sep:
            port_part = tail
    host = host.strip().lower()
    if not host:
        return None
    port_part = port_part.strip()
    if not port_part:
        return None if default_port is None else (host, default_port)
    if not port_part.isdigit():
        return None
    port = int(port_part)
    if not 1 <= port <= 65535:
        return None
    return host, port


def _build_host_allowlist(settings: ControlPlaneSettings) -> frozenset[str]:
    """构建 Host 白名单（§8.2 防DNS rebinding，审查 P-01）。

    默认条目 = ``127.0.0.1:{port}``、``localhost:{port}``（端口跟随
    control_plane_settings().port，杜绝硬编码漂移），始终存在且不可经
    配置关闭；配置扩展条目（settings.host_allowlist，host:port 或省
    端口的 host）只增不减；非法条目跳过并告警（白名单只授予不剥夺，
    跳过不弱化防护，fail-closed）。
    """
    entries = {f"127.0.0.1:{settings.port}", f"localhost:{settings.port}"}
    for raw in settings.host_allowlist:
        parsed = _split_host_port(raw, default_port=settings.port)
        if parsed is None:
            logger.warning("控制面 Host 白名单忽略非法条目：%r", raw)
            continue
        entries.add(f"{parsed[0]}:{parsed[1]}")
    return frozenset(entries)


def _host_header_allowed(raw_host: str, allowlist: frozenset[str]) -> bool:
    """请求 Host 头严格匹配：缺端口/畸形一律 False（见 _split_host_port）。"""
    parsed = _split_host_port(raw_host, default_port=None)
    if parsed is None:
        return False
    host, port = parsed
    return f"{host}:{port}" in allowlist


def _auth_dependency(auth: BearerAuthenticator, provisioned: bool):
    """``/admin/api/v1/*`` 统一认证依赖（B4 §5.1：失败限速检查 → 认证）。"""

    async def dependency(request: Request) -> Principal:
        if not provisioned:
            # 未配置 token：除 /healthz 外一律 503（防裸奔，B4 §5.1）。
            raise ControlPlaneError(
                503,
                "control_plane_not_provisioned",
                "控制面未配置管理令牌（BOT_CONTROL_PLANE_TOKEN_SHA256 为空）。",
            )
        source = auth.source_key_of(request)
        retry_after = auth.failure_blocked(source)
        if retry_after > 0:
            raise ControlPlaneError(
                429,
                "rate_limited",
                "认证失败次数过多，请稍后重试。",
                headers={"Retry-After": str(int(retry_after))},
            )
        principal = await auth.authenticate(request)
        if principal is None:
            auth.register_failure(source)
            raise ControlPlaneError(401, "unauthorized", "缺少或无效的 Bearer 凭据。")
        request.state.cp_subject = principal.subject
        return principal

    return dependency


def _v1_read_dependency(auth: BearerAuthenticator, super_auth: BearerAuthenticator):
    """同一 v1 读接口接受只读令牌或超管令牌，共享失败限速。"""

    async def dependency(request: Request) -> Principal:
        if not auth.provisioned and not super_auth.provisioned:
            raise ControlPlaneError(
                503, "control_plane_not_provisioned", "控制面未配置管理令牌。"
            )
        source = auth.source_key_of(request)
        retry_after = auth.failure_blocked(source)
        if retry_after > 0:
            raise ControlPlaneError(
                429,
                "rate_limited",
                "认证失败次数过多，请稍后重试。",
                headers={"Retry-After": str(int(retry_after))},
            )
        principal = await auth.authenticate(request) if auth.provisioned else None
        if principal is None and super_auth.provisioned:
            principal = await super_auth.authenticate(request)
            if principal is not None:
                principal = Principal("bearer-super-admin", ("super_admin", "admin"))
        if principal is None:
            auth.register_failure(source)
            raise ControlPlaneError(401, "unauthorized", "缺少或无效的 Bearer 凭据。")
        request.state.cp_subject = principal.subject
        return principal

    return dependency


def _super_admin_dependency(auth: BearerAuthenticator, provisioned: bool):
    """Write dependency for the future WebUI: a distinct super-admin token."""

    async def dependency(request: Request) -> Principal:
        if not provisioned:
            raise ControlPlaneError(
                503, "control_plane_not_provisioned", "控制面未配置管理令牌。"
            )
        source = auth.source_key_of(request)
        retry_after = auth.failure_blocked(source)
        if retry_after > 0:
            raise ControlPlaneError(
                429,
                "rate_limited",
                "认证失败次数过多，请稍后重试。",
                headers={"Retry-After": str(int(retry_after))},
            )
        principal = await auth.authenticate(request)
        if principal is None:
            auth.register_failure(source)
            raise ControlPlaneError(403, "forbidden", "此操作需要 super_admin 权限。")
        principal.roles = ("super_admin", "admin")
        principal.subject = "bearer-super-admin"
        request.state.cp_subject = principal.subject
        return principal

    return dependency


def create_control_plane_app(
    config: object | None = None,
    *,
    channel_health_store: Any | None = None,
    audit_store: ControlPlaneAuditStore | None = None,
    started_at: datetime | str | None = None,
    feature_service: FeatureControlService | None = None,
    event_service: Any | None = None,
    settings_store: Any | None = None,
    config_service: Any | None = None,
    metrics_service: Any | None = None,
    resource_service: Any | None = None,
    stats_service: Any | None = None,
    webui_dist_dir: str | None = None,
    runtime_attached: bool = False,
    action_service: Any | None = None,
    workspace_service: Any | None = None,
    send_queue: Any | None = None,
    runtime_state_probe: Callable[[], bool] | None = None,
) -> FastAPI:
    """组装控制面 FastAPI app（M1：healthz + health + status 最小面）。

    工厂不监听端口；按已配置存储初始化schema，事件writer在lifespan启动。
    store单例经参数注入（B4 §3.1规则1）。启动与否由调用方的
    总开关把关（serve() 或未来 bot on_startup 接线处的
    ``control_plane_enabled()``）。

    V21-risk-4 注入面：
    - ``send_queue``：宿主进程的发送队列实例，注入后 queue.pause/resume/drain
      才有真实作用对象（未注入如实 degraded）；
    - ``runtime_state_probe``：零参可调用，返回 SnowLuma/OneBot 实时连接态。
      napcat.status 只信该探针的现查结果；``runtime_attached`` 仅是装配期
      「app 位于 bot 宿主进程」事实，不再充当连接声明（探针缺省=如实未连接）。
    """
    settings: ControlPlaneSettings = control_plane_settings(config)
    if audit_store is None:
        from .audit import resolve_default_ledger_db_path

        audit_store = ControlPlaneAuditStore(resolve_default_ledger_db_path())
    if channel_health_store is None:
        channel_health_store = _try_channel_health_store(config)
    if started_at is None:
        started_at = datetime.now().astimezone()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        bus = getattr(application.state, "event_bus", None)
        collector = getattr(application.state, "log_collector", None)
        if bus is not None:
            bus.start()
        workspace = getattr(application.state, "workspace_service", None)

        async def prune_workspaces():
            while True:
                try:
                    await asyncio.to_thread(workspace.prune)
                except ControlServiceError:
                    logger.warning("workspace retention cleanup unavailable")
                await asyncio.sleep(60)

        cleanup = (
            asyncio.create_task(prune_workspaces()) if workspace is not None else None
        )
        try:
            if collector is not None:
                collector.start()
            yield
        finally:
            if cleanup is not None:
                cleanup.cancel()
                await asyncio.gather(cleanup, return_exceptions=True)
            if collector is not None:
                collector.close()
            if bus is not None:
                await asyncio.to_thread(bus.close)

    app = FastAPI(
        title="ChatBot Control Plane",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,  # 不暴露 API 文档面（阶段 1 最小暴露）。
    )
    app.state.settings = settings
    app.state.started_at = started_at
    app.state.authenticator = auth = BearerAuthenticator(settings.token_sha256)
    super_auth = BearerAuthenticator(settings.super_admin_token_sha256)
    if (
        super_auth.provisioned
        and settings.super_admin_token_sha256.lower() == settings.token_sha256.lower()
    ):
        logger.error(
            "control plane requires distinct read and super-admin tokens; writes disabled"
        )
        super_auth = BearerAuthenticator("")
    app.state.super_admin_authenticator = super_auth
    provisioned = auth.provisioned

    timezone_name = str(getattr(config, "bot_timezone", "") or "")

    app.include_router(build_healthz_router())
    app.include_router(
        build_health_router(
            channel_health_store=channel_health_store,
            audit_store=audit_store,
            started_at=started_at,
            timezone_name=timezone_name,
        ),
        dependencies=[Depends(_auth_dependency(auth, provisioned))],
    )

    if settings_store is None:
        from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
            RuntimeSettingsStore,
            build_runtime_settings_store,
        )

        if getattr(config, "bot_control_plane_config_db", None):
            settings_store = build_runtime_settings_store(config)
        else:
            settings_path = getattr(config, "bot_runtime_settings_file", None)
            settings_store = (
                RuntimeSettingsStore(settings_path) if settings_path else None
            )
    if (
        config_service is None
        and settings_store is not None
        and settings_store.config_backend is not None
    ):
        from .config_service import ConfigControlService

        config_service = ConfigControlService(
            config, settings_store.config_backend, runtime_settings=settings_store
        )
    app.state.config_service = config_service

    events_path = getattr(config, "bot_control_plane_events_db", None)
    if event_service is None and events_path:
        from .events import RuntimeEventService

        event_service = RuntimeEventService(_path(str(events_path)))
    app.state.event_bus = None
    app.state.log_collector = None
    if event_service is not None:
        from .api.events import build_event_router
        from .events import RuntimeEventBus

        app.state.event_bus = RuntimeEventBus(event_service)
        if runtime_attached:
            from .log_collectors import ProcessLogCollector

            app.state.log_collector = ProcessLogCollector(
                app.state.event_bus,
                nonebot_logger=__import__("nonebot.log", fromlist=["logger"]).logger,
            )
        app.include_router(
            build_event_router(
                event_service,
                _v1_read_dependency(auth, super_auth),
                collector=app.state.log_collector,
            )
        )

    if metrics_service is None:
        from ..llm.ledger import resolve_default_db_path
        from .metrics import LedgerMetricsService

        metrics_service = LedgerMetricsService(resolve_default_db_path())
    if resource_service is None:
        from .resources import ResourceMetricsService

        resource_service = ResourceMetricsService(runtime_attached=runtime_attached)
    app.state.resource_service = resource_service
    if stats_service is None:
        from .webui_stats import build_default_stats_service

        stats_service = build_default_stats_service(config)
    app.state.stats_service = stats_service
    app.state.send_queue = send_queue
    feature_service = feature_service or build_feature_service(config)
    app.state.feature_service = feature_service
    if workspace_service is None:
        from .factory import build_workspace_service

        workspace_service = build_workspace_service(config)
    app.state.workspace_service = workspace_service
    if action_service is None:
        from .actions import ControlActionDescriptor, ControlActionService

        async def _default_action(parameters: dict[str, Any]) -> dict[str, Any]:
            action_id = str(parameters.pop("_action_id", ""))
            if action_id == "logging.level":
                level = str(parameters.get("level", "INFO")).upper()
                if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
                    return {"status": "failed", "details": {"error": "invalid_level"}}
                logging.getLogger().setLevel(level)
                return {"status": "ok", "details": {"level": level}}
            if action_id == "resources.refresh":
                snapshot = app.state.resource_service.snapshot()
                return {"status": "ok", "details": {"resource_snapshot": snapshot}}
            if action_id == "diagnostics.snapshot":
                return {
                    "status": "ok",
                    "details": {
                        "control_plane": "running",
                        "runtime_attached": runtime_attached,
                    },
                }
            if action_id == "runtime.reload":
                if settings_store is not None:
                    settings_store.list_overrides()
                return {"status": "ok", "details": {"reloaded": True}}
            if action_id in {"queue.pause", "queue.resume", "queue.drain"}:
                queue = getattr(app.state, "send_queue", None)
                method = getattr(queue, action_id.removeprefix("queue."), None)
                if callable(method):
                    result = method()
                    if asyncio.iscoroutine(result):
                        result = await result
                    return {
                        "status": "ok",
                        "details": {
                            "queue": result if isinstance(result, dict) else action_id
                        },
                    }
                return {
                    "status": "degraded",
                    "details": {"execution": "send_queue_not_connected"},
                }
            if action_id == "napcat.status":
                # V21-risk-4：连接态只信实时探针现查；runtime_attached 是装配期
                # 标量，不得冒充连接声明。探针缺省=如实未连接（不装样子）。
                if runtime_state_probe is None:
                    return {
                        "status": "ok",
                        "details": {
                            "connected": False,
                            "source": "probe_not_configured",
                        },
                    }
                try:
                    connected = bool(runtime_state_probe())
                except Exception:  # noqa: BLE001 - 探测失败如实降级，不拖垮控制面。
                    return {
                        "status": "degraded",
                        "details": {"connected": False, "source": "probe_error"},
                    }
                return {
                    "status": "ok",
                    "details": {
                        "connected": connected,
                        "source": "runtime_probe",
                    },
                }
            return {
                "status": "degraded",
                "details": {
                    "state": "registered",
                    "execution": "adapter_not_connected",
                },
            }

        action_path = _path(
            str(
                getattr(config, "bot_control_plane_actions_db", None)
                or "data/control_plane_actions.sqlite3"
            )
        )
        action_ids = (
            "runtime.reload",
            "runtime.safe_restart",
            "adapter.reconnect",
            "napcat.status",
            "queue.pause",
            "queue.resume",
            "queue.drain",
            "logging.level",
            "resources.refresh",
            "llm.routes.reload",
            "knowledge.reindex",
            "memory.maintenance",
            "diagnostics.snapshot",
        )

        def _handler_for(action_id: str):
            async def handler(parameters: dict[str, Any]) -> dict[str, Any]:
                return await _default_action(parameters | {"_action_id": action_id})

            return handler

        action_service = ControlActionService(
            action_path,
            registrations=tuple(
                (ControlActionDescriptor(action_id, action_id), _handler_for(action_id))
                for action_id in action_ids
            ),
        )
    app.state.action_service = action_service
    from .platform import PlatformStore

    platform_path = getattr(config, "bot_control_plane_platform_db", None) or ":memory:"
    app.state.platform_store = PlatformStore(
        _path(str(platform_path)) if platform_path != ":memory:" else platform_path
    )
    from .api.platform import build_platform_router

    app.include_router(
        build_platform_router(
            store=app.state.platform_store,
            read_dependency=_v1_read_dependency(auth, super_auth),
            write_dependency=_super_admin_dependency(
                super_auth, super_auth.provisioned
            ),
            prefix="/api/v1",
            # V21-risk-4：config 不传则 /api/v1/media/analyze 恒 503
            # media_config_unavailable（哪怕 app 层有完整 config）。
            config=config,
            log_level_setter=_apply_platform_log_level,
        )
    )
    # V2.1 S12：占卜/运势 REST 段（未配置持久化路径 = facade None = 503 诚实位，
    # 与 actions/config 服务缺装配同一前例；平台路由先例=独立 build_*_router）。
    from ..domains.divination.api.facet import build_divination_facade_from_config
    from ..domains.divination.routes import build_divination_router

    divination_facade = build_divination_facade_from_config(config)
    app.state.divination_facade = divination_facade
    app.include_router(
        build_divination_router(
            facade=divination_facade,
            read_dependency=_v1_read_dependency(auth, super_auth),
            audit_store=audit_store,
        )
    )
    app.include_router(
        build_v1_router(
            feature_service=feature_service,
            event_service=event_service,
            log_collector=app.state.log_collector,
            action_service=action_service,
            workspace_service=workspace_service,
            config=config,
            settings_store=settings_store,
            config_service=config_service,
            metrics_service=metrics_service,
            resource_service=resource_service,
            runtime_attached=runtime_attached,
            read_dependency=_v1_read_dependency(auth, super_auth),
            write_dependency=_super_admin_dependency(
                super_auth, super_auth.provisioned
            ),
            channel_health_store=channel_health_store,
            event_bus=app.state.event_bus,
        )
    )

    from .api.webui import build_ui_router, build_webui_stats_router

    app.include_router(
        build_webui_stats_router(
            stats=stats_service,
            metrics_service=metrics_service,
            channel_health_store=channel_health_store,
            read_dependency=_v1_read_dependency(auth, super_auth),
        )
    )
    app.include_router(build_ui_router(dist_dir=webui_dist_dir))
    # WebUI Phase B：知识目录 / 插件目录 / 记忆图谱（只读，缺源=信封内
    # source_unavailable 如实降级，服务层均不写任何生产库）。
    from .api.webui_ext import (
        build_webui_knowledge_router,
        build_webui_memory_router,
        build_webui_plugins_router,
    )
    from .webui_knowledge import build_default_knowledge_service
    from .webui_memory_graph import build_default_memory_graph_service
    from .webui_plugins import build_default_plugins_service

    app.state.knowledge_service = build_default_knowledge_service(config)

    def _plugins_action_registry() -> tuple[tuple[str, str], ...]:
        # /actions 注册表轻投影（id+label，零 DB）；外部注入的服务若未提供
        # registry_pairs（旧形状），按空注册表如实处理（config_actions 全空表）。
        getter = getattr(action_service, "registry_pairs", None)
        return getter() if callable(getter) else ()

    app.state.plugins_service = build_default_plugins_service(
        config,
        feature_service=feature_service,
        action_registry=_plugins_action_registry,
    )
    app.state.memory_graph_service = build_default_memory_graph_service(config)
    app.include_router(
        build_webui_knowledge_router(
            knowledge=app.state.knowledge_service,
            read_dependency=_v1_read_dependency(auth, super_auth),
        )
    )
    app.include_router(
        build_webui_plugins_router(
            plugins=app.state.plugins_service,
            read_dependency=_v1_read_dependency(auth, super_auth),
        )
    )
    app.include_router(
        build_webui_memory_router(
            memory_graph=app.state.memory_graph_service,
            read_dependency=_v1_read_dependency(auth, super_auth),
        )
    )

    def error_response(
        request: Request,
        status: int,
        code: str,
        message: str,
        headers: Mapping[str, str] | None = None,
    ) -> JSONResponse:
        debug_id = new_debug_id()
        request.state.cp_debug_id = debug_id
        request.state.cp_error_code = code
        body = error_body(code, debug_id, message)
        response_headers = dict(headers or {})
        if request.url.path == "/api/v1" or request.url.path.startswith("/api/v1/"):
            request_id = (
                getattr(request.state, "cp_request_id", None) or new_request_id()
            )
            body["error"].update(
                request_id=request_id, retryable=status in (429, 503), field_errors=[]
            )
            body = envelope(None, request_id=request_id, error=body["error"])
            response_headers["X-Request-ID"] = request_id
            response_headers["Cache-Control"] = "no-store"
        return JSONResponse(status_code=status, content=body, headers=response_headers)

    @app.exception_handler(ControlServiceError)
    async def _handle_service_error(
        request: Request, exc: ControlServiceError
    ) -> JSONResponse:
        return error_response(request, exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # 不使用 errors()/body 的 input/ctx，避免把凭证与用户内容回显。
        return error_response(request, 422, "validation_error", "请求参数未通过校验。")

    @app.exception_handler(HTTPException)
    async def _handle_http_error(request: Request, exc: HTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(
            exc.status_code, "http_error"
        )
        return error_response(
            request, exc.status_code, code, "请求的资源或操作不可用。", exc.headers
        )

    @app.exception_handler(ControlPlaneError)
    async def _handle_control_plane_error(
        request: Request, exc: ControlPlaneError
    ) -> JSONResponse:
        return error_response(
            request, exc.status_code, exc.code, exc.message, exc.headers
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # 不记录未经脱敏的异常内容；关联 id 足以定位受控诊断。
        logger.error(
            "control plane internal error (request_id=%s, type=%s)",
            getattr(request.state, "cp_request_id", "unknown"),
            type(exc).__name__,
        )
        return error_response(request, 500, "internal_error", "控制面内部错误。")

    # Host 白名单（§8.2 防DNS rebinding，审查 P-01）。Bearer 只防“无凭据”，
    # 防不了浏览器同源策略被绕过：恶意网页可驱动受害者浏览器向
    # 127.0.0.1:{port} 发跨域请求（简单请求不因 CORS 预检被拦），故必须在
    # 认证之前按 Host 头硬拒。注册顺序在本文件审计中间件之前（Starlette
    # 后注册者在最外层）→ 审计在外、本层在内：/admin/api/v1/* 上被拒的
    # 请求仍留 400 审计痕，便于取证。
    host_allowlist = _build_host_allowlist(settings)

    @app.middleware("http")
    async def _host_guard_middleware(request: Request, call_next):
        host_headers = [
            value for name, value in request.scope["headers"] if name == b"host"
        ]
        # Host 头必须恰好一个：多值/重复即拒（请求走私与 rebinding 向量）。
        allowed = len(host_headers) == 1 and _host_header_allowed(
            host_headers[0].decode("latin-1"), host_allowlist
        )
        if not allowed:
            debug_id = new_debug_id()
            request.state.cp_debug_id = debug_id
            request.state.cp_error_code = "host_not_allowed"
            # 异常 Host 原文只进服务端日志（repr 防控制字符注入），不回显。
            logger.warning(
                "control plane 拒绝 Host 头（P-01 DNS rebinding 防护，%s）：%r",
                debug_id,
                host_headers,
            )
            return error_response(
                request, 400, "host_not_allowed", "Host 头未通过白名单校验。"
            )
        return await call_next(request)

    @app.middleware("http")
    async def _audit_middleware(request: Request, call_next):
        response = await call_next(request)
        # M1 审计范围：/admin/api/v1/*（/healthz 探针不审计）。
        if request.url.path.startswith(("/admin/api/v1/", "/api/v1/")):
            try:
                subject = str(getattr(request.state, "cp_subject", "") or "anonymous")
                bytes_out = 0
                raw_length = response.headers.get("content-length")
                if raw_length and raw_length.isdigit():
                    bytes_out = int(raw_length)
                if app.state.event_bus is not None:
                    from .events import RuntimeLogEvent

                    app.state.event_bus.publish(
                        RuntimeLogEvent(
                            source="control_plane",
                            category="success"
                            if response.status_code < 400
                            else "warning",
                            details={
                                "request_id": getattr(
                                    request.state, "cp_request_id", ""
                                ),
                                "status": response.status_code,
                            },
                        )
                    )
                audit_store.record(
                    subject=subject,
                    source="local",
                    method=request.method,
                    path=request.url.path,
                    query=str(request.url.query or ""),
                    status_code=response.status_code,
                    bytes_out=bytes_out,
                    debug_id=str(getattr(request.state, "cp_debug_id", "") or ""),
                    detail=str(getattr(request.state, "cp_error_code", "") or ""),
                )
            except Exception:
                logger.debug("control plane audit middleware failed", exc_info=True)
        return response

    @app.middleware("http")
    async def _request_context_middleware(request: Request, call_next):
        # 忽略客户端提供的 ID，避免日志注入/请求冒充。
        request_id = new_request_id()
        request.state.cp_request_id = request_id
        token = request_id_context.set(request_id)
        try:
            response = await call_next(request)
            if request.url.path == "/api/v1" or request.url.path.startswith("/api/v1/"):
                response.headers["X-Request-ID"] = request_id
                response.headers["Cache-Control"] = "no-store"
            return response
        finally:
            request_id_context.reset(token)

    return app


def _try_channel_health_store(config: object | None) -> Any | None:
    """尽力解析渠道健康单例；失败不阻塞控制面启动（status/models 回空集）。"""
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.channel_health import (
            get_channel_health_store,
        )

        return get_channel_health_store()
    except Exception:
        logger.debug(
            "channel health store unavailable for control plane", exc_info=True
        )
        return None


def _public_confirmation_file() -> str:
    """公网绑定确认文件路径（B4 §9.7，放 Runtime 配置/数据目录）。"""
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[3]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    try:
        from scripts.runtime_paths import runtime_data_dir

        return str(runtime_data_dir() / _PUBLIC_CONFIRM_FILENAME)
    except Exception:  # noqa: BLE001 - 解析失败退回源码树相对路径。
        return f"data/{_PUBLIC_CONFIRM_FILENAME}"


def serve(config: object | None = None) -> int:
    """独立 uvicorn 入口（``python -m ...control_plane``）。

    - 总开关关闭（默认）→ 不启动，返回 0；
    - host 非 loopback 且无 ``control_plane_public.confirmed`` 确认文件 →
      拒绝启动（B4 §9.7，防误绑 0.0.0.0），返回 2。
    """
    settings = control_plane_settings(config)
    if not settings.enabled:
        logger.warning(
            "控制面处于关闭状态（BOT_CONTROL_PLANE_ENABLED 未开启），不启动。"
        )
        return 0
    if not is_loopback_host(settings.host):
        confirmation = _public_confirmation_file()
        confirmed = False
        try:
            from pathlib import Path

            path = Path(confirmation)
            confirmed = path.is_file() and bool(
                path.read_text(encoding="utf-8").strip()
            )
        except OSError:
            confirmed = False
        if not confirmed:
            logger.error(
                "拒绝绑定非环回地址 %s：%s 不存在或为空（B4 §9.7 公网显式开启开关）。",
                settings.host,
                confirmation,
            )
            return 2
    app = create_control_plane_app(config)
    import uvicorn

    logger.info(
        "控制面启动：http://%s:%d（/healthz 探针；/admin/api/v1 需 Bearer）",
        settings.host,
        settings.port,
    )
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="warning")
    return 0
