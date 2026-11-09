"""W6（2026-10-14）：VisualSpec 布局 HTTP 段（`/api/v1/visual`）。

薄投影：业务全在 `control_plane.visual_layouts`；本模块只做参数校验、权限
依赖、envelope 与错误码映射。**不读任何无 owner 路径、零文件/网络 IO。**

- 写面（save/reset/preview）只吃 `write_dependency`；读面（catalog/layout）只吃
  `read_dependency`（与既有 `api/actions.py` 同范式）。
- 预览 HTML 只来自生产 renderer（`VisualLayoutService.preview`）——**绝不回显
  用户原始 HTML**；sandbox iframe 展示由前端负责，本层不信用户 HTML。
- 载荷 `extra="forbid"`：多一个键即 422，不静默吞字段。

父会话负责在 `_app.py` 挂载本 router（`build_visual_router(...)`）。
"""

# ruff: noqa: B008
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from ..api import ControlPlaneError
from ..auth import Principal
from ..visual_layouts import (
    LayoutScope,
    VisualLayoutError,
    VisualLayoutResetPayload,
    VisualLayoutSavePayload,
    VisualLayoutService,
    VisualPreviewPayload,
    VisualThemePayload,
    VisualThemeRollbackPayload,
)
from .protocol import ERROR_RESPONSES, envelope


def build_visual_router(
    *,
    service: VisualLayoutService | None,
    read_dependency: Any,
    write_dependency: Any,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/visual", responses=ERROR_RESPONSES)

    def require_service() -> VisualLayoutService:
        if service is None:
            raise ControlPlaneError(
                503, "visual_unavailable", "可视化布局服务尚未装配（未配置存储路径）。"
            )
        return service

    def project(exc: VisualLayoutError) -> ControlPlaneError:
        return ControlPlaneError(exc.status_code, exc.code, exc.message)

    def scope_from_query(platform: str, instance: str, group: str, card: str) -> LayoutScope:
        try:
            return LayoutScope(
                platform=platform, instance=instance, group=group, card=card
            )
        except ValueError as exc:
            raise ControlPlaneError(422, "validation_error", "作用域参数不合法。") from exc

    @router.get("/catalog")
    def catalog(principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        return envelope(require_service().catalog())

    @router.get("/layout")
    def read_layout(
        platform: str = Query(min_length=1, max_length=64),
        instance: str = Query(default="", max_length=64),
        group: str = Query(default="", max_length=64),
        card: str = Query(default="", max_length=64),
        principal: Principal = Depends(read_dependency),
    ) -> dict[str, Any]:
        scope = scope_from_query(platform, instance, group, card)
        return envelope(require_service().read(scope))

    @router.post("/layout")
    def save_layout(
        payload: VisualLayoutSavePayload,
        principal: Principal = Depends(write_dependency),
    ) -> dict[str, Any]:
        try:
            data = require_service().save(
                payload.scope,
                payload.spec,
                expected_version=payload.expected_version,
                actor=principal.subject,
                fragments=payload.fragments,
            )
        except VisualLayoutError as exc:
            raise project(exc) from exc
        return envelope(data)

    @router.post("/layout/reset")
    def reset_layout(
        payload: VisualLayoutResetPayload,
        principal: Principal = Depends(write_dependency),
    ) -> dict[str, Any]:
        try:
            data = require_service().reset(
                payload.scope,
                expected_version=payload.expected_version,
                actor=principal.subject,
            )
        except VisualLayoutError as exc:
            raise project(exc) from exc
        return envelope(data)

    @router.post("/preview")
    def preview_layout(
        payload: VisualPreviewPayload,
        principal: Principal = Depends(write_dependency),
    ) -> dict[str, Any]:
        return envelope(
            require_service().preview(payload.spec, payload.sample, payload.fragments)
        )

    # ---- 全局视觉覆盖（W12 R4，用户裁定 A+B+C）：同一条 visual 通道 ----------
    @router.get("/theme")
    def read_theme(principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        service_ = require_service()
        data = service_.theme_read()
        data["history"] = service_.theme_history(20)
        return envelope(data)

    @router.post("/theme")
    def save_theme(
        payload: VisualThemePayload,
        principal: Principal = Depends(write_dependency),
    ) -> dict[str, Any]:
        try:
            data = require_service().theme_save(
                payload.overrides,
                expected_version=payload.expected_version,
                actor=principal.subject,
            )
        except VisualLayoutError as exc:
            raise project(exc) from exc
        return envelope(data)

    @router.post("/theme/rollback")
    def rollback_theme(
        payload: VisualThemeRollbackPayload,
        principal: Principal = Depends(write_dependency),
    ) -> dict[str, Any]:
        try:
            data = require_service().theme_rollback(
                expected_version=payload.expected_version, actor=principal.subject
            )
        except VisualLayoutError as exc:
            raise project(exc) from exc
        return envelope(data)

    return router
