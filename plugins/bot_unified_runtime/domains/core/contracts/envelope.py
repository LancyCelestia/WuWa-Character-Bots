"""V2.1 统一响应 envelope：严格 DTO + 线格式构建器（S2 协议席）。

合同来源：docs/design/backend-v2-implementation-guide.md §6——

    {"data":{},"error":null,
     "meta":{"request_id":"req_...","trace_id":"trace_...",
             "schema_version":"v1","generated_at":"UTC ISO8601"}}

设计约束（V21-CORE-001）：
- 本模块是「叶子中的叶子」：只依赖 pydantic + 标准库，零框架、零网络、零线程、
  零配置文件读取，可被 importlib 直载探针独立验证。因此不 import 本包内任何
  模块（contracts/runtime.py 会经 message_context 反向拉起父包 __init__）。
- ID 生成与 runtime.py 的 new_request_id/new_debug_id 同格式（<前缀>_<12位hex>），
  属有意的最小复制以保叶子纯净；收敛到单一来源属后续装配席位的工作。
- 与 control_plane/api/protocol.py 的旧 envelope 的关系：那边是存量实现
  （meta 缺 trace_id、错误体缺 trace_id、无错误注册表），本模块是 V2.1 权威
  契约源；旧侧适配属后续席位，不在本模块内做兼容 hack。
- 严格性：extra="forbid" 拒绝未知字段；allow_inf_nan=False 拒绝 NaN/Infinity；
  generated_at 强制带时区并归一到 UTC。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Generic, Literal, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION: Literal["v1"] = "v1"

T = TypeVar("T")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def new_request_id() -> str:
    return _new_id("req")


def new_trace_id() -> str:
    return _new_id("trace")


def new_debug_id() -> str:
    return _new_id("dbg")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_aware(name: str, value: datetime) -> datetime:
    """拒绝 naive datetime；aware 值一律归一到 UTC。"""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} 必须带时区（UTC ISO8601）")
    return value.astimezone(timezone.utc)


class V21StrictBase(BaseModel):
    """V2.1 契约严格基类：禁未知字段、禁 NaN/Infinity。

    与 contracts/runtime.py 的 StrictBaseModel 相比多了 allow_inf_nan=False；
    叶子纯净要求下不继承那边，收敛属后续席位。
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ResponseMeta(V21StrictBase):
    """envelope.meta：schema_version 锁死 v1；generated_at 强制 UTC。"""

    request_id: str = Field(min_length=1, max_length=128)
    trace_id: str = Field(min_length=1, max_length=128)
    schema_version: Literal["v1"] = SCHEMA_VERSION
    generated_at: datetime = Field(default_factory=_utc_now)

    @field_validator("request_id", "trace_id")
    @classmethod
    def require_non_blank_ids(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("request_id/trace_id 不能为空白")
        return normalized

    @field_validator("generated_at")
    @classmethod
    def require_aware_generated_at(cls, value: datetime) -> datetime:
        return _require_aware("generated_at", value)


class FieldError(V21StrictBase):
    """字段级错误：只回字段与可读原因，不回显原始入参值（防泄露）。"""

    field: str = Field(min_length=1, max_length=256)
    message: str = Field(min_length=1, max_length=512)


class ErrorBody(V21StrictBase):
    """envelope.error 契约体（§6）：恰七键，缺一不可、多一不容。"""

    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=512)
    request_id: str = Field(min_length=1, max_length=128)
    trace_id: str = Field(min_length=1, max_length=128)
    debug_id: str = Field(min_length=1, max_length=128)
    retryable: bool
    field_errors: list[FieldError] = Field(default_factory=list)


class ApiEnvelope(V21StrictBase, Generic[T]):
    """统一响应信封。data 载荷自身也必须是严格 DTO——信封的 extra=forbid
    只守顶层三键，data 内部的 NaN/未知键由载荷类型负责。"""

    data: T | None
    error: ErrorBody | None = None
    meta: ResponseMeta


class RetryHint(V21StrictBase):
    """429 族（rate_limited/capacity_exceeded/budget_exceeded）的 data 载荷：
    按 §6 以 retry_after 提示稍后重试；float 字段验证 NaN/Inf 拒绝。"""

    retry_after_seconds: float = Field(ge=0)


def build_meta(
    request_id: str | None = None, trace_id: str | None = None
) -> ResponseMeta:
    return ResponseMeta(
        request_id=request_id or new_request_id(),
        trace_id=trace_id or new_trace_id(),
    )


def success_envelope(
    data: Any = None,
    *,
    request_id: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """成功响应线格式（与 §6 示例逐键对齐）。显式传入的 ID 原样传播。"""
    meta = build_meta(request_id, trace_id)
    return {
        "data": data,
        "error": None,
        "meta": {
            "request_id": meta.request_id,
            "trace_id": meta.trace_id,
            "schema_version": meta.schema_version,
            "generated_at": meta.generated_at.isoformat(timespec="milliseconds"),
        },
    }
