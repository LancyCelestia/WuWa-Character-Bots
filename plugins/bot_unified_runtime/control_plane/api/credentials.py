"""Credential API exposes metadata and confirmed writes, never secret reads."""
# ruff: noqa: B008
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..auth import Principal
from ..services import ControlServiceError
from .protocol import envelope


class CredentialChange(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    action: Literal["replace", "delete"]
    value: str = Field(default="", max_length=65536, repr=False)
    kind: Literal["cookie", "api_key", "oauth_token"] = "api_key"
    domain: str = Field(default="", max_length=256)
    expires_at: str = Field(default="", max_length=64)
    expected_version: int = Field(strict=True, ge=0)
    confirmation_token: str | None = Field(default=None, max_length=128, repr=False)

    @model_validator(mode="after")
    def nonempty_replacement(self):
        if self.action == "replace" and not self.value:
            raise ValueError("replacement requires a value")
        if self.action == "delete" and (self.value or self.expected_version == 0):
            raise ValueError("delete requires an existing version and no value")
        return self


def build_credentials_router(*, service: Any, dependency: Any) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    def require_service():
        if service is None:
            raise ControlServiceError("credentials_unavailable", "加密凭据存储尚未装配。", 503)
        return service

    @router.get("/credentials")
    def refs(principal: Principal = Depends(dependency)):
        return envelope(require_service().refs(principal))

    @router.post("/credentials/{ref_id}/preview")
    def preview(ref_id: str, payload: CredentialChange, principal: Principal = Depends(dependency)):
        return envelope(require_service().preview(ref_id, payload.model_dump(exclude={"confirmation_token"}), principal))

    @router.post("/credentials/{ref_id}/apply")
    def apply(ref_id: str, payload: CredentialChange, principal: Principal = Depends(dependency)):
        return envelope(require_service().apply(ref_id, payload.model_dump(exclude={"confirmation_token"}), payload.confirmation_token, principal))

    return router
