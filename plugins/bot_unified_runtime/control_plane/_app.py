"""控制面 app 工厂与独立 uvicorn 启动（B4 M1 §3.2/§10）。

仅在 :mod:`__init__` 惰性导出时才被导入——控制面关闭态零导入副作用。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from . import ControlPlaneSettings, control_plane_settings, is_loopback_host
from .api import ControlPlaneError, error_body, new_debug_id
from .api.health import build_health_router, build_healthz_router
from .audit import ControlPlaneAuditStore
from .auth import BearerAuthenticator, Principal

logger = logging.getLogger(__name__)

_PUBLIC_CONFIRM_FILENAME = "control_plane_public.confirmed"


def _split_host_port(
    value: str, *, default_port: int | None
) -> tuple[str, int] | None:
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


def create_control_plane_app(
    config: object | None = None,
    *,
    channel_health_store: Any | None = None,
    audit_store: ControlPlaneAuditStore | None = None,
    started_at: datetime | str | None = None,
) -> FastAPI:
    """组装控制面 FastAPI app（M1：healthz + health + status 最小面）。

    纯工厂：不启动服务、不起线程、不写库（audit 表在首次写/health 探针时
    惰性建）；store 单例经参数注入（B4 §3.1 规则 1）。启动与否由调用方的
    总开关把关（serve() 或未来 bot on_startup 接线处的
    ``control_plane_enabled()``）。
    """
    settings: ControlPlaneSettings = control_plane_settings(config)
    if audit_store is None:
        from .audit import resolve_default_ledger_db_path

        audit_store = ControlPlaneAuditStore(resolve_default_ledger_db_path())
    if channel_health_store is None:
        channel_health_store = _try_channel_health_store(config)
    if started_at is None:
        started_at = datetime.now().astimezone()

    app = FastAPI(
        title="ChatBot Control Plane",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,  # 不暴露 API 文档面（阶段 1 最小暴露）。
    )
    app.state.settings = settings
    app.state.started_at = started_at
    app.state.authenticator = auth = BearerAuthenticator(settings.token_sha256)
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

    @app.exception_handler(ControlPlaneError)
    async def _handle_control_plane_error(
        request: Request, exc: ControlPlaneError
    ) -> JSONResponse:
        debug_id = new_debug_id()
        request.state.cp_debug_id = debug_id
        request.state.cp_error_code = exc.code
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, debug_id, exc.message),
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # B4 §4：错误响应永不回 str(exc)；异常细节只进服务端日志。
        debug_id = new_debug_id()
        request.state.cp_debug_id = debug_id
        request.state.cp_error_code = "internal_error"
        logger.error("control plane internal error (%s)", debug_id, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=error_body("internal_error", debug_id, "控制面内部错误。"),
        )

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
            value
            for name, value in request.scope["headers"]
            if name == b"host"
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
            return JSONResponse(
                status_code=400,
                content=error_body(
                    "host_not_allowed", debug_id, "Host 头未通过白名单校验。"
                ),
            )
        return await call_next(request)

    @app.middleware("http")
    async def _audit_middleware(request: Request, call_next):
        response = await call_next(request)
        # M1 审计范围：/admin/api/v1/*（/healthz 探针不审计）。
        if request.url.path.startswith("/admin/api/v1"):
            try:
                subject = str(getattr(request.state, "cp_subject", "") or "anonymous")
                bytes_out = 0
                raw_length = response.headers.get("content-length")
                if raw_length and raw_length.isdigit():
                    bytes_out = int(raw_length)
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

    return app


def _try_channel_health_store(config: object | None) -> Any | None:
    """尽力解析渠道健康单例；失败不阻塞控制面启动（status/models 回空集）。"""
    try:
        from plugins.bot_unified_runtime.llm.channel_health import (
            get_channel_health_store,
        )

        return get_channel_health_store()
    except Exception:
        logger.debug("channel health store unavailable for control plane", exc_info=True)
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
