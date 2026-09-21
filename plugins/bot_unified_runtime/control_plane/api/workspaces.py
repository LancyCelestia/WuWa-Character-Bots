"""隔离工作区API，原文接口仅超管拥有者可读。"""
# ruff: noqa: B008
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from ..api import ControlPlaneError
from ..auth import Principal
from ..workspaces import WorkspaceService, WorkspaceSettings
from .protocol import ApiEnvelope, ConfigResetPayload, envelope


class WorkspaceMessagePayload(ConfigResetPayload):
    content: str = Field(strict=True, min_length=1, max_length=16000)


class WorkspaceSendPayload(ConfigResetPayload):
    confirmation_token: str = Field(strict=True, min_length=1, max_length=128)
    idempotency_key: str = Field(strict=True, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:@-]+$")


class WorkspaceMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str
    test_session_id: str
    created_by: str
    settings: WorkspaceSettings
    version: int
    status: str
    expires_at: float


def build_workspaces_router(*, service: WorkspaceService | None, dependency: Any) -> APIRouter:
    router = APIRouter()

    def require_service() -> WorkspaceService:
        if service is None:
            raise ControlPlaneError(503, "workspace_unavailable", "隔离工作区服务尚未装配。")
        return service

    @router.get("/workspaces")
    def listing(principal: Principal = Depends(dependency)) -> dict[str, Any]:
        return envelope({"items": require_service().list(principal=principal)})

    @router.post("/workspaces", response_model=ApiEnvelope[WorkspaceMetadata])
    def create(payload: WorkspaceSettings, request: Request, principal: Principal = Depends(dependency)) -> dict[str, Any]:
        return envelope(require_service().create(payload, principal=principal, request_id=request.state.cp_request_id))

    @router.get("/workspaces/{workspace_id}", response_model=ApiEnvelope[WorkspaceMetadata])
    def detail(workspace_id: str, principal: Principal = Depends(dependency)) -> dict[str, Any]:
        return envelope(require_service().get(workspace_id, principal=principal))

    @router.delete("/workspaces/{workspace_id}")
    def delete(workspace_id: str, request: Request, expected_version: int = Query(ge=0), principal: Principal = Depends(dependency)) -> dict[str, Any]:
        return envelope(require_service().delete(workspace_id, expected_version=expected_version,
            principal=principal, request_id=request.state.cp_request_id))

    @router.get("/workspaces/{workspace_id}/messages")
    def messages(workspace_id: str, principal: Principal = Depends(dependency)) -> dict[str, Any]:
        return envelope({"items": require_service().messages(workspace_id, principal=principal)})

    @router.post("/workspaces/{workspace_id}/messages", response_model=ApiEnvelope[WorkspaceMetadata])
    def message(workspace_id: str, payload: WorkspaceMessagePayload, request: Request, principal: Principal = Depends(dependency)) -> dict[str, Any]:
        return envelope(require_service().message(workspace_id, payload.content, expected_version=payload.expected_version,
            principal=principal, request_id=request.state.cp_request_id))

    @router.post("/workspaces/{workspace_id}/reset", response_model=ApiEnvelope[WorkspaceMetadata])
    def reset(workspace_id: str, payload: ConfigResetPayload, request: Request, principal: Principal = Depends(dependency)) -> dict[str, Any]:
        return envelope(require_service().reset(workspace_id, expected_version=payload.expected_version,
            principal=principal, request_id=request.state.cp_request_id))

    @router.post("/workspaces/{workspace_id}/preview")
    async def preview(workspace_id: str, payload: ConfigResetPayload, request: Request, principal: Principal = Depends(dependency)) -> dict[str, Any]:
        return envelope(await require_service().preview(workspace_id, expected_version=payload.expected_version,
            principal=principal, request_id=request.state.cp_request_id))

    @router.post("/workspaces/{workspace_id}/send")
    async def send(workspace_id: str, payload: WorkspaceSendPayload, request: Request, principal: Principal = Depends(dependency)) -> dict[str, Any]:
        return envelope(await require_service().send(workspace_id, expected_version=payload.expected_version,
            principal=principal, request_id=request.state.cp_request_id,
            confirmation_token=payload.confirmation_token, idempotency_key=payload.idempotency_key))

    @router.get("/workspaces/{workspace_id}/audit")
    def audit(workspace_id: str, principal: Principal = Depends(dependency)) -> dict[str, Any]:
        return envelope({"items": require_service().audit(workspace_id, principal=principal)})

    return router
