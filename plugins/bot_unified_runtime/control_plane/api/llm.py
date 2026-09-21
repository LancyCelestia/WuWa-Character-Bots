"""模型控制 REST 全量（核心要求 §十一；V21-ROUTE-001）。

投影层零业务逻辑：候选序/健康/优先级语义全部来自
``control_plane.llm_admin.LLMControlService``（只读消费 R1 路由语义）。

RBAC：读=admin+（v1 读依赖）；写（config/preview+apply、cache/reload）=super_admin
（v1 写依赖）；models/{id}/test 的 dry=读、live=内部超管门+显式确认门，且本轮
真实调用端口不实装——诚实 503 ``not_configured``。
"""
# ruff: noqa: B008
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from ..auth import Principal
from ..llm_admin import CODE_NOT_CONFIGURED, LLMControlService
from ..services import ControlServiceError
from . import ControlPlaneError
from .protocol import envelope

_KEY_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*$"


class ConfigChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(strict=True, min_length=1, max_length=128, pattern=_KEY_PATTERN)
    value: Any = None


class LLMConfigPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(strict=True, ge=0)
    changes: list[ConfigChange] = Field(strict=True, min_length=1, max_length=20)


class LLMRoutePreviewPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    override: str | None = Field(default=None, max_length=128)
    model: str | None = Field(default=None, max_length=128)
    session_key: str | None = Field(default=None, max_length=128, pattern=r"^[A-Za-z0-9_.:@-]*$")
    message_text: str | None = Field(default=None, max_length=8000)
    simulate_intimate: bool = Field(default=False, strict=True)


class LLMModelTestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["dry", "live"] = "dry"
    confirm: bool = Field(default=False, strict=True)


def _http_error(exc: ControlServiceError) -> ControlPlaneError:
    return ControlPlaneError(exc.status_code, exc.code, exc.message)


def build_llm_router(
    *,
    service: LLMControlService | None,
    read_dependency: Any,
    write_dependency: Any,
) -> APIRouter:
    router = APIRouter()

    def require_service() -> LLMControlService:
        if service is None:
            raise ControlPlaneError(503, "llm_control_unavailable", "模型控制服务尚未装配。")
        return service

    @router.get("/llm/providers")
    def providers(principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        return envelope({"items": list(require_service().providers())})

    @router.get("/llm/providers/{provider_id}")
    def provider_detail(provider_id: str, principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        item = require_service().provider(provider_id)
        if item is None:
            raise ControlPlaneError(404, "resource_not_found", "要找的供应商不存在。")
        return envelope(item)

    @router.get("/llm/channels")
    def channels(principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        return envelope({"items": list(require_service().channels())})

    @router.get("/llm/channels/{channel_id}")
    def channel_detail(channel_id: str, principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        item = require_service().channel(channel_id)
        if item is None:
            raise ControlPlaneError(404, "resource_not_found", "要找的渠道不存在。")
        return envelope(item)

    @router.get("/llm/models")
    def models(principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        return envelope({"items": list(require_service().models())})

    @router.get("/llm/models/{model_id}")
    def model_detail(model_id: str, principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        item = require_service().model(model_id)
        if item is None:
            raise ControlPlaneError(404, "resource_not_found", "要找的模型不存在。")
        return envelope(item)

    @router.get("/llm/health")
    def health(principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        return envelope(require_service().health_view())

    @router.get("/llm/routes")
    def routes(principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        return envelope(require_service().routes_view())

    @router.post("/llm/routes/preview")
    def routes_preview(payload: LLMRoutePreviewPayload, principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        # 只读投影：不写健康库、不产生模型调用、不触碰会话滞回状态。
        result = require_service().preview_routes(
            override=payload.override or "", model=payload.model or "",
            session_key=payload.session_key or "", message_text=payload.message_text or "",
            simulate_intimate=payload.simulate_intimate,
        )
        return envelope(result)

    @router.post("/llm/models/{model_id}/test")
    def test_model(model_id: str, payload: LLMModelTestPayload, principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        service = require_service()
        if payload.mode == "live":
            if "super_admin" not in principal.roles:
                raise ControlPlaneError(403, "permission_denied", "此操作需要 super_admin 权限。")
            if not payload.confirm:
                raise ControlPlaneError(409, "confirmation_required", "真实调用测试需要显式确认才能继续。")
            # 本轮不实装真实调用端口：诚实 503，不假装测试成功。
            raise ControlPlaneError(
                503, CODE_NOT_CONFIGURED,
                "单模型真实调用端口尚未装配，本轮仅支持 dry 校验。",
            )
        try:
            return envelope(service.test_model(model_id, mode=payload.mode))
        except ControlServiceError as exc:
            raise _http_error(exc) from None

    @router.post("/llm/config/preview")
    def config_preview(payload: LLMConfigPayload, request: Request, principal: Principal = Depends(write_dependency)) -> dict[str, Any]:
        try:
            return envelope(require_service().config_preview(
                [change.model_dump() for change in payload.changes],
                principal=principal, expected_version=payload.expected_version,
                request_id=str(getattr(request.state, "cp_request_id", "") or "")))
        except ControlServiceError as exc:
            raise _http_error(exc) from None

    @router.post("/llm/config/apply")
    def config_apply(payload: LLMConfigPayload, request: Request, principal: Principal = Depends(write_dependency)) -> dict[str, Any]:
        try:
            return envelope(require_service().config_apply(
                [change.model_dump() for change in payload.changes],
                principal=principal, expected_version=payload.expected_version,
                request_id=str(getattr(request.state, "cp_request_id", "") or "")))
        except ControlServiceError as exc:
            raise _http_error(exc) from None

    @router.post("/llm/cache/reload")
    def cache_reload(request: Request, principal: Principal = Depends(write_dependency)) -> dict[str, Any]:
        del request
        return envelope(require_service().reload())

    return router
