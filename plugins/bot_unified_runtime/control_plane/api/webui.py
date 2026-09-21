"""WebUI Phase A HTTP 投影：只读统计端点 + ``/ui`` 静态壳挂载。

- ``/api/v1/stats/calls|tokens|latency``、``/api/v1/affinity/board``：只读
  聚合，走统一信封与既有 v1 读依赖（只读令牌或超管令牌、失败限速、503
  not_provisioned 同款语义）；参数校验在服务层，``invalid_request`` 映射
  422 ``stats_invalid_query``；数据源缺失沿用 metrics 先例以 200 信封内
  ``status=source_unavailable`` 如实降级，不假装修好了数据。
- ``/ui``：单文件静态壳（vite-plugin-singlefile 产物 ``webui/dist/index.html``）。
  壳内不含任何数据，数据面全部经上方认证端点；本路由与 /healthz 同级不挂
  Bearer，但 Host 白名单等全局中间件语义不变。产物未构建 → 404
  ``ui_not_built`` 诚实体，不造假页面。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, Response

from ..api import ControlPlaneError
from ..auth import Principal
from ..webui_stats import (
    WebUIStatsBundle,
    latency_view,
    resolve_webui_index,
)
from .protocol import ERROR_RESPONSES, envelope

# ruff: noqa: B008


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

    @router.get("/ui")
    def ui_index() -> Response:
        index = resolve_webui_index(dist_dir)
        if index is None:
            raise ControlPlaneError(
                404,
                "ui_not_built",
                "WebUI 静态产物尚未构建（webui/dist/index.html 不存在）。",
            )
        return FileResponse(
            index,
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    return router
