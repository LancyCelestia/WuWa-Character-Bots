"""API v1 传输协议；不泄露请求正文、凭证或内部异常。"""
from __future__ import annotations

import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from ..features import FeatureDescriptor, FeatureState

request_id_context: ContextVar[str | None] = ContextVar("cp_request_id", default=None)


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex}"


def new_trace_id() -> str:
    return f"trace_{uuid.uuid4().hex}"


def envelope(
    data: Any,
    *,
    request_id: str | None = None,
    trace_id: str | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """统一信封（v21r2 S9 增补：meta.trace_id，additive——不破坏既有键）。"""
    return {
        "data": data,
        "error": error,
        "meta": {
            "request_id": request_id or request_id_context.get() or new_request_id(),
            "trace_id": trace_id or new_trace_id(),
            "schema_version": "v1",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        },
    }


class FeatureChangePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(strict=True, ge=0)
    expected_revision: int | None = Field(default=None, strict=True, ge=0)


class FeaturePreviewPayload(FeatureChangePayload):
    enabled: bool | None = Field(strict=True)


T = TypeVar("T")


class ResponseMeta(BaseModel):
    request_id: str
    trace_id: str = ""
    schema_version: Literal["v1"] = "v1"
    generated_at: str


class ErrorInfo(BaseModel):
    code: str
    message: str
    debug_id: str
    request_id: str
    retryable: bool
    field_errors: list[dict[str, Any]] = Field(default_factory=list)


class ApiEnvelope(BaseModel, Generic[T]):
    data: T | None
    error: ErrorInfo | None = None
    meta: ResponseMeta


class FeatureItem(BaseModel):
    descriptor: FeatureDescriptor
    state: FeatureState


class FeatureList(BaseModel):
    items: list[FeatureItem]


class FeatureTreeItem(FeatureItem):
    children: list[FeatureTreeItem]


class FeatureTree(BaseModel):
    items: list[FeatureTreeItem]


class FeatureMutationResult(BaseModel):
    state: FeatureState
    audit_id: str
    affected: list[FeatureState] = Field(default_factory=list)


class FeaturePreviewResult(BaseModel):
    state: FeatureState
    affected: list[FeatureState]
    affected_ids: list[str]


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ApiEnvelope[Any], "description": "统一错误响应"}
    for code in (400, 401, 403, 404, 409, 410, 422, 429, 500, 503)
}


class ConfigResetPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(strict=True, ge=0)


class ConfigValuePayload(ConfigResetPayload):
    value: Any


class ResourceMeasurement(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    value: int | float | None
    status: Literal["ok", "unknown"]
    reason: Literal["warming_up", "counter_reset", "source_unavailable", "not_connected"] | None
    unit: Literal["seconds", "percent_one_core", "bytes", "count"]


class ResourceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    pid: int
    process_role: Literal["bot_host", "control_plane_host"]
    captured_at: str
    sampling: Literal["on_demand"]
    minimum_interval_seconds: float
    measurements: dict[str, ResourceMeasurement]
    cpu_time_seconds: float | None
    cpu_time_seconds_status: Literal["ok", "unknown"]
    cpu_time_seconds_reason: str | None
    cpu_percent: float | None
    cpu_percent_status: Literal["ok", "unknown"]
    cpu_percent_reason: str | None
    memory_bytes: int | None
    memory_bytes_status: Literal["ok", "unknown"]
    memory_bytes_reason: str | None

class ActionParametersPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parameters: dict[str, Any] = Field(default_factory=dict)
    expected_version: int = Field(strict=True, ge=0)


class ActionExecutePayload(ActionParametersPayload):
    confirmation_token: str | None = Field(default=None, strict=True, min_length=1, max_length=128)
    idempotency_key: str = Field(strict=True, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
