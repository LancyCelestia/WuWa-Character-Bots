"""WebUI Phase A HTTP 投影：只读统计端点 + ``/ui`` 静态壳挂载。

- ``/api/v1/stats/calls|tokens|latency``、``/api/v1/affinity/board``：只读
  聚合，走统一信封与既有 v1 读依赖（只读令牌或超管令牌、失败限速、503
  not_provisioned 同款语义）；参数校验在服务层，``invalid_request`` 映射
  422 ``stats_invalid_query``；数据源缺失沿用 metrics 先例以 200 信封内
  ``status=source_unavailable`` 如实降级，不假装修好了数据。
- ``/ui``：产物入口。已构建 → 307 跳 ``/ui/``；未构建 → 404 ``ui_not_built``
  诚实体，不造假页面。``/ui/`` 返回 index（text/html、no-store），
  ``/ui/assets/*`` 由 :func:`mount_webui_assets` 在应用层挂载真实服务静态资源。
  壳内不含任何数据，数据面全部经上方认证端点；本路由与 /healthz 同级不挂
  Bearer，但 Host 白名单等全局中间件语义不变。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Query
from fastapi.responses import FileResponse, RedirectResponse, Response
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles

from ..api import ControlPlaneError
from ..auth import Principal
from ..webui_stats import (
    WebUIStatsBundle,
    latency_view,
    resolve_webui_index,
)
from .protocol import ERROR_RESPONSES, envelope

# ruff: noqa: B008

# WebUI 资源子树（应用层 Mount，不走 APIRouter.mount 的 include_router 传播）。
_UI_ENTRY_PATH = "/ui"
_UI_ASSETS_MOUNT_PATH = "/ui/assets"

# 带哈希资产名（vite ``[name]-[hash][ext]``）：末段 ``-`` + ≥8 位
# [0-9A-Za-z_] 且含数字/大写，避免把 ``my-app-name.js`` 误判成哈希件。
_HASHED_ASSET_RE = re.compile(r"-[0-9A-Za-z_]{8,}\.[0-9A-Za-z]+$")

_ASSET_IMMUTABLE_CACHE = "public, max-age=31536000, immutable"
_ASSET_NO_STORE_CACHE = "no-store"

# 服务端 CSP：与 ``webui/index.html`` 的 meta CSP 最小对齐（default/style/img/
# font/connect 同形），但 script-src 收紧为 'self'——多文件产物外链脚本，不再
# 依赖单文件内联；frame-ancestors 只能由响应头生效（meta 里无效）。
_UI_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self'; "
    "connect-src 'self' http://127.0.0.1:* http://localhost:*; "
    "frame-ancestors 'none'"
)


def is_ui_path(path: str) -> bool:
    """``/ui`` 与 ``/ui/...`` 子树判定（不含 ``/uix`` 这类前缀碰撞）。"""
    return path == _UI_ENTRY_PATH or path.startswith(_UI_ENTRY_PATH + "/")


def is_hashed_asset(path: str) -> bool:
    """资产名是否带构建哈希（决定可长缓存）；纯启发式，非 manifest 驱动。"""
    name = path.rsplit("/", 1)[-1]
    match = _HASHED_ASSET_RE.search(name)
    if match is None:
        return False
    return any(ch.isdigit() or ch.isupper() for ch in match.group(0))


def apply_ui_response_headers(response: Response, path: str) -> None:
    """UI 响应头边界：CSP/XFO/nosniff 仅挂 /ui 子树；资产按哈希区分缓存。

    不碰 /api、webhook、Host 鉴权，也不新增 CORS——缓存头只写在资源子树，
    与 v1 的全局 ``Cache-Control: no-store``（仅 /api/v1）互不冲突。
    """
    response.headers.setdefault("Content-Security-Policy", _UI_CSP)
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    if path.startswith(_UI_ASSETS_MOUNT_PATH + "/"):
        # 404 不给一年缓存：只有真正命中（<400）的带哈希资产才 immutable。
        if response.status_code < 400 and is_hashed_asset(path):
            response.headers["Cache-Control"] = _ASSET_IMMUTABLE_CACHE
        else:
            response.headers["Cache-Control"] = _ASSET_NO_STORE_CACHE


def resolve_webui_assets_dir(dist_dir: str | Path | None = None) -> Path:
    """资产根 = 与 ``resolve_webui_index`` 同一基准目录下的 ``assets`` 子树。

    构建后直接复用 index 所在目录；未构建时按同一默认基准推导（默认基准与
    ``resolve_webui_index`` 一致），不复制其存在性判定。
    """
    index = resolve_webui_index(dist_dir)
    if index is not None:
        return index.parent / "assets"
    base = (
        Path(dist_dir)
        if dist_dir
        else Path(__file__).resolve().parents[4] / "webui" / "dist"
    )
    return base / "assets"


class _OptionalStaticFiles(StaticFiles):
    """产物缺席＝如实 404（不升 500），且**资产根不得越出产物根**。

    ``check_dir=False`` 只免**构造期**检查；Starlette ``StaticFiles.__call__``
    （staticfiles.py:93）在首个请求仍 ``await check_config()``，目录缺失时抛
    ``RuntimeError``（:201）⇒ 冒到通用 500 处理器、目录路径写进服务端日志。
    这里只把那一次检查收成 no-op：后续 ``lookup_path`` 对缺件/非目录一律
    FileNotFoundError/NotADirectoryError → 404（沿用 StaticFiles 既有行为）。

    🔴 第二牙（运行时查表）：StaticFiles 把 ``directory`` ``realpath`` 之后当作
    合法根——``dist/assets`` 若是指向产物根**之外**的链接/挂载，外部非空文件
    照样能被服务。故每个请求先自证资产根是产物根的**严格子目录**，否则 404
    （不回显路径）：``assets.resolve() == dist.resolve()`` 也**不放行**——那等于
    把产物根散件（如 ``dist/secret.txt``）一起纳入 ``/ui/assets/*`` 服务面。
    """

    def __init__(self, *, dist_root: str | Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._dist_root = Path(dist_root)

    async def check_config(self) -> None:
        return None

    async def get_response(self, path: str, scope: Any) -> Response:
        try:
            assets_root = Path(self.directory or "").resolve()
            dist_root = self._dist_root.resolve()
            # 严格子目录：等值（assets 指到 dist 本身）与越界一律拒。
            root_ok = assets_root != dist_root and assets_root.is_relative_to(dist_root)
        except OSError:
            root_ok = False
        if not root_ok:
            raise HTTPException(status_code=404)
        return await super().get_response(path, scope)


def mount_webui_assets(app: FastAPI, dist_dir: str | Path | None = None) -> None:
    """应用层挂载 ``/ui/assets/*``（``APIRouter.mount`` 不经 include_router 传播）。

    ``check_dir=False`` + :class:`_OptionalStaticFiles`：产物未构建也不在构造期
    抛异常、首个请求也不升 500，缺目录逐请求如实 404；``StaticFiles`` 默认
    ``follow_symlink=False`` + 解析后包含性校验，路径遍历与符号链接不得越出
    资产根；``html=False``（默认）⇒ 未知资产 404、不回退 index；只挂 assets
    子树，产物根其他文件不暴露。``dist_root`` 交给子类做**运行时**资产根越界
    自查（``dist/assets`` 被换成指向产物根外的链接时拒服务）。
    """
    assets_dir = resolve_webui_assets_dir(dist_dir)
    app.mount(
        _UI_ASSETS_MOUNT_PATH,
        _OptionalStaticFiles(
            directory=str(assets_dir),
            dist_root=str(assets_dir.parent),
            check_dir=False,
        ),
        name="webui-assets",
    )


def _stats_payload(result: dict[str, Any]) -> dict[str, Any]:
    """服务层结果投影：invalid_request → 422，其余（含 source_unavailable）原样。"""
    if result.get("status") == "invalid_request":
        raise ControlPlaneError(422, "stats_invalid_query", "统计查询参数无效。")
    return result


def build_webui_stats_router(
    *,
    stats: WebUIStatsBundle,
    metrics_service: Any | None,
    channel_health_store: Any | None,
    read_dependency: Any,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", responses=ERROR_RESPONSES)

    @router.get("/stats/calls")
    def stats_calls(
        principal: Principal = Depends(read_dependency),
        window: str = Query(default="24h"),
        bucket: str = Query(default="hour"),
        limit: int = Query(default=10),
    ) -> dict[str, Any]:
        del principal
        result = stats.calls.calls(window=window, bucket=bucket, limit=limit)
        return envelope(_stats_payload(result))

    @router.get("/stats/tokens")
    def stats_tokens(
        principal: Principal = Depends(read_dependency),
        window: str = Query(default="24h"),
        limit: int = Query(default=20),
    ) -> dict[str, Any]:
        del principal
        if metrics_service is None or not hasattr(metrics_service, "token_families"):
            result: dict[str, Any] = {
                "status": "source_unavailable",
                "reason": "not_connected",
                "data": None,
            }
        else:
            result = metrics_service.token_families(window=window, limit=limit)
        return envelope(_stats_payload(result))

    @router.get("/stats/latency")
    def stats_latency(
        principal: Principal = Depends(read_dependency),
    ) -> dict[str, Any]:
        del principal
        return envelope(latency_view(channel_health_store))

    @router.get("/affinity/board")
    def affinity_board(
        principal: Principal = Depends(read_dependency),
        limit: int = Query(default=50),
        order: str = Query(default="desc"),
    ) -> dict[str, Any]:
        del principal
        result = stats.affinity.board(limit=limit, order=order)
        return envelope(_stats_payload(result))

    return router


def build_ui_router(dist_dir: str | Path | None = None) -> APIRouter:
    router = APIRouter()

    def _index_or_404() -> Path:
        index = resolve_webui_index(dist_dir)
        if index is None:
            raise ControlPlaneError(
                404,
                "ui_not_built",
                "WebUI 静态产物尚未构建（webui/dist/index.html 不存在）。",
            )
        return index

    @router.get("/ui")
    def ui_entry() -> Response:
        # 有产物 → 统一到带尾斜杠的 /ui/，让 index 里的相对引用有稳定基准；
        # 无产物 → 仍是诚实的 404，不跳到空壳。
        _index_or_404()
        return RedirectResponse(url="/ui/", status_code=307)

    @router.get("/ui/")
    def ui_index() -> Response:
        return FileResponse(
            _index_or_404(),
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    return router
