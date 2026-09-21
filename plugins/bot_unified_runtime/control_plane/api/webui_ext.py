"""WebUI Phase B HTTP 投影：知识目录 / 插件目录 / 记忆图谱（只读）。

与既有 webui 统计端点同一套惯例：统一信封、``_v1_read_dependency`` 双
令牌、参数非法 → 422（固定错误码）、数据源缺失 → 200 信封内
``source_unavailable`` 如实降级。服务层校验参数；本层只做信封与错误码
映射，OpenAPI 注册与 Host 白名单等中间件语义由 app 工厂统一覆盖。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from ..api import ControlPlaneError
from ..auth import Principal
from .protocol import ERROR_RESPONSES, envelope

# ruff: noqa: B008


def _payload(result: dict[str, Any], error_code: str) -> dict[str, Any]:
    """服务层结果投影：invalid_request → 422，其余（含 source_unavailable）原样。"""
    if result.get("status") == "invalid_request":
        raise ControlPlaneError(422, error_code, "查询参数无效。")
    return result


def build_webui_knowledge_router(
    *,
    knowledge: Any,
    read_dependency: Any,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", responses=ERROR_RESPONSES)

    @router.get("/knowledge/collections")
    def knowledge_collections(
        principal: Principal = Depends(read_dependency),
    ) -> dict[str, Any]:
        del principal
        return envelope(_payload(knowledge.collections(), "knowledge_invalid_query"))

    @router.get("/knowledge/terms")
    def knowledge_terms(
        principal: Principal = Depends(read_dependency),
        collection: str = Query(default=""),
        q: str = Query(default="", max_length=200),
        page: int = Query(default=1),
        page_size: int = Query(default=20),
    ) -> dict[str, Any]:
        del principal
        result = knowledge.terms(collection, q=q, page=page, page_size=page_size)
        return envelope(_payload(result, "knowledge_invalid_query"))

    return router


def build_webui_plugins_router(
    *,
    plugins: Any,
    read_dependency: Any,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", responses=ERROR_RESPONSES)

    @router.get("/plugins")
    def plugins_catalog(
        principal: Principal = Depends(read_dependency),
    ) -> dict[str, Any]:
        del principal
        return envelope(_payload(plugins.plugins_catalog(), "plugins_invalid_query"))

    return router


def build_webui_memory_router(
    *,
    memory_graph: Any,
    read_dependency: Any,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", responses=ERROR_RESPONSES)

    # 端点函数名不得与闭包捕获的服务参数同名（避免作用域遮蔽）。
    @router.get("/memory/graph", operation_id="memory_graph_api_v1_memory_graph_get")
    def memory_graph_view(
        principal: Principal = Depends(read_dependency),
        window: str = Query(default="24h"),
        max_nodes: int = Query(default=120),
    ) -> dict[str, Any]:
        del principal
        result = memory_graph.graph(window=window, max_nodes=max_nodes)
        return envelope(_payload(result, "memory_graph_invalid_query"))

    return router
