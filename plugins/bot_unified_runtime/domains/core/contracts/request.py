"""V2.1 请求侧严格 DTO：分页/版本守卫/幂等/确认/主体（S2 协议席）。

合同来源：docs/design/backend-v2-implementation-guide.md §6——
- 分页默认 50 最大 200，稳定游标；
- 写入 expected_version，创建为 0（CAS）；
- 有副作用 POST 使用 Idempotency-Key，同键不同摘要 409；
- 确认 token 绑定 actor/目标/版本/摘要，120s、一次消费；
- principal 只能由认证注入，客户端载荷出现 principal 属协议违规。

设计约束（V21-CORE-001）：本模块只依赖 pydantic + 标准库，零框架、零网络、
零线程、零配置文件读取，不 import 本包内任何模块（可被直载探针独立验证）。
字段模式与 control_plane/api/protocol.py 既有载荷保持同口径（idempotency key
正则、expected_version 语义），避免第二套冲突概念。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# §6：确认 token 生命周期 120s。
CONFIRMATION_TTL_SECONDS = 120

# 与既有 control_plane 载荷同口径的幂等键形态。
IDEMPOTENCY_KEY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$"
SHA256_PATTERN = r"^[0-9a-f]{64}$"


class V21RequestBase(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def _require_aware(name: str, value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} 必须带时区（UTC ISO8601）")
    return value.astimezone(timezone.utc)


class PaginationQuery(V21RequestBase):
    """稳定游标分页：默认 50，最大 200（§6）。"""

    limit: int = Field(default=50, ge=1, le=200, strict=True)
    cursor: str | None = Field(default=None, min_length=1, max_length=256)


class WriteExpectation(V21RequestBase):
    """写入版本守卫：expected_version 乐观锁，创建固定为 0。"""

    expected_version: int = Field(ge=0, strict=True)


class IdempotencyRef(V21RequestBase):
    """副作用写请求的幂等引用：同键不同摘要必须在服务端判 409 idempotency_conflict。"""

    key: str = Field(
        min_length=1, max_length=128, pattern=IDEMPOTENCY_KEY_PATTERN
    )
    payload_sha256: str = Field(pattern=SHA256_PATTERN)


class ConfirmationRef(V21RequestBase):
    """确认 token 的绑定事实：actor/目标/版本/内容摘要 + 120s 生命周期。

    「一次消费」与撤销由运行时状态掌管，DTO 只承载绑定与窗口事实。
    """

    token: str = Field(min_length=1, max_length=128)
    actor: str = Field(min_length=1, max_length=128)
    target: str = Field(min_length=1, max_length=256)
    expected_version: int = Field(ge=0, strict=True)
    content_sha256: str = Field(pattern=SHA256_PATTERN)
    issued_at: datetime
    expires_at: datetime

    @field_validator("issued_at", "expires_at")
    @classmethod
    def require_aware_times(cls, value: datetime, info: Any) -> datetime:
        return _require_aware(str(info.field_name), value)

    @model_validator(mode="after")
    def require_valid_window(self) -> ConfirmationRef:
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at 必须晚于 issued_at")
        ttl_seconds = (self.expires_at - self.issued_at).total_seconds()
        if ttl_seconds > CONFIRMATION_TTL_SECONDS:
            raise ValueError(
                f"确认窗口不得超过 {CONFIRMATION_TTL_SECONDS}s，实际 {ttl_seconds:g}s"
            )
        return self


class PrincipalRef(V21RequestBase):
    """认证主体投影。

    安全约定：principal 只能由认证层构造后注入上下文；接入层必须剥除客户端
    载荷中的同名字段（extra=forbid 只能挡住未知键，挡不住「被信任的注入」）。
    """

    subject: str = Field(min_length=1, max_length=128)
    roles: list[str] = Field(min_length=1)
    scopes: list[str] = Field(default_factory=list)
    auth_source: Literal["authenticated", "compat_service"] = "authenticated"

    @field_validator("subject", "roles")
    @classmethod
    def require_non_blank(cls, value: Any, info: Any) -> Any:
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                raise ValueError(f"{info.field_name} 不能为空白")
            return normalized
        if isinstance(value, list):
            items = [item.strip() for item in value if str(item).strip()]
            if not items:
                raise ValueError(f"{info.field_name} 不能为空列表")
            return items
        return value


__all__ = [
    "CONFIRMATION_TTL_SECONDS",
    "ConfirmationRef",
    "IdempotencyRef",
    "PaginationQuery",
    "PrincipalRef",
    "V21RequestBase",
    "WriteExpectation",
]
