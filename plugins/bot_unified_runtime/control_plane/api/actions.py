"""白名单动作 HTTP 适配；状态、确认、权限、审计由服务层负责。"""
# ruff: noqa: B008
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from ..actions import ControlActionService
from ..api import ControlPlaneError
from ..auth import Principal
from .protocol import (
    ActionExecutePayload,
    ActionParametersPayload,
    ConfigResetPayload,
    envelope,
)


def build_actions_router(*, service: ControlActionService | None, read_dependency: Any, write_dependency: Any) -> APIRouter:
    router = APIRouter()

    def require_service() -> ControlActionService:
        if service is None:
            raise ControlPlaneError(503, "actions_unavailable", "控制动作服务尚未装配。")
        return service

    @router.get("/actions")
    def catalog(principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        return envelope({"items": require_service().catalog()})

    # 静态路径必须位于 /actions/{action_id} 之前。
    @router.get("/actions/runs")
    def runs(limit: int = Query(default=50, ge=1, le=500), principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        return envelope({"items": require_service().runs(limit=limit)})

    @router.get("/actions/runs/{run_id}")
    def run(run_id: str, principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        return envelope(require_service().run(run_id))

    @router.post("/actions/runs/{run_id}/cancel")
    async def cancel(run_id: str, payload: ConfigResetPayload, principal: Principal = Depends(write_dependency)) -> dict[str, Any]:
        return envelope(await require_service().cancel(run_id, expected_version=payload.expected_version, principal=principal))

    @router.get("/actions/{action_id}")
    def detail(action_id: str, principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        return envelope(require_service().detail(action_id))

    @router.post("/actions/{action_id}/preview")
    def preview(action_id: str, payload: ActionParametersPayload, principal: Principal = Depends(write_dependency)) -> dict[str, Any]:
        return envelope(require_service().preview(action_id, parameters=payload.parameters,
            expected_version=payload.expected_version, principal=principal))

    @router.post("/actions/{action_id}/execute")
    async def execute(action_id: str, payload: ActionExecutePayload, request: Request, principal: Principal = Depends(write_dependency)) -> dict[str, Any]:
        return envelope(await require_service().execute(action_id, parameters=payload.parameters,
            expected_version=payload.expected_version, principal=principal,
            request_id=request.state.cp_request_id, idempotency_key=payload.idempotency_key,
            confirmation_token=payload.confirmation_token))

    return router
