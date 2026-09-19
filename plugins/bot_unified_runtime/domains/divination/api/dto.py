"""V2.1 S12 占卜 REST 请求 DTO（严格字形；框架无关）。

合同来源：backend-v2-product-extensions.md §3.2 + implementation-guide §6
（Pydantic 严格 DTO 拒绝未知字段与 NaN/Infinity；principal/身份/时刻绝不入载荷）。

- ``idempotency_key`` 不入载荷：REST 面走 ``Idempotency-Key`` 头（§6 惯例），
  由路由层并入 :class:`~...service.divination_service.DrawRequest`。
- ``kind`` 不入别名字形载荷：``fortune/daily``、``tarot/draw`` 端点在路由层预置。
- ``bazi/preview`` 为只读投影：无幂等键、无持久化；年月日时分 + 时区只负责
  定位时刻，算法面（东八区节气锚定）由 ``data/ganzhi.bazi_chart`` 负责，本层
  不重写任何历法计算。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from plugins.bot_unified_runtime.domains.core.contracts.request import (
    IDEMPOTENCY_KEY_PATTERN,
)

__all__ = [
    "DEFAULT_TIMEZONE_ID",
    "DEFAULT_WORKSPACE_ID",
    "BaziPreviewPayload",
    "DivinationDrawPayload",
    "FortuneDailyPayload",
    "TarotDrawPayload",
    "validate_idempotency_key",
]

# REST 便利缺省（控制面调用方多为本机管理工具；显式传值永远优先）。
DEFAULT_TIMEZONE_ID = "Asia/Shanghai"
DEFAULT_WORKSPACE_ID = "default"

# 与 DrawRequest 同一口径：幂等键字符集校验（头传入后并成 DrawRequest 前）。
_IDEMPOTENCY_KEY_MAX = 128


class _StrictPayload(BaseModel):
    """严格 DTO 基类：拒未知字段、拒 NaN/Infinity。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def validate_idempotency_key(value: str) -> str:
    """幂等键头校验：空/超长/非法字符 → ``validation_error`` 语义的 ValueError。

    路由层把它翻译成 422 envelope；字符集与 DrawRequest 的
    ``IDEMPOTENCY_KEY_PATTERN`` 完全一致，保证并入服务契约后零二次拒斥。
    """
    import re

    key = str(value or "").strip()
    if not key or len(key) > _IDEMPOTENCY_KEY_MAX or not re.match(
        IDEMPOTENCY_KEY_PATTERN, key
    ):
        raise ValueError("Idempotency-Key 缺失或格式非法")
    return key


class DivinationDrawPayload(_StrictPayload):
    """POST /divination/draws 请求体（通用字形；别名端点用子集字形）。"""

    kind: Literal["tarot", "fortune"]
    spread_id: str | None = Field(default=None, max_length=64)
    question: str = Field(default="", max_length=500)
    timezone_id: str = Field(
        default=DEFAULT_TIMEZONE_ID, min_length=1, max_length=64
    )
    workspace_id: str = Field(
        default=DEFAULT_WORKSPACE_ID, min_length=1, max_length=128
    )

    @field_validator("timezone_id")
    @classmethod
    def require_loadable_zone(cls, value: str) -> str:
        from zoneinfo import ZoneInfo

        try:
            ZoneInfo(value)
        except Exception as exc:
            raise ValueError(f"未知时区：{value!r}") from exc
        return value

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str) -> str:
        return value.strip()


class FortuneDailyPayload(_StrictPayload):
    """POST /divination/fortune/daily 请求体（kind 预置 fortune）。"""

    question: str = Field(default="", max_length=500)
    timezone_id: str = Field(
        default=DEFAULT_TIMEZONE_ID, min_length=1, max_length=64
    )
    workspace_id: str = Field(
        default=DEFAULT_WORKSPACE_ID, min_length=1, max_length=128
    )

    @field_validator("timezone_id")
    @classmethod
    def require_loadable_zone(cls, value: str) -> str:
        from zoneinfo import ZoneInfo

        try:
            ZoneInfo(value)
        except Exception as exc:
            raise ValueError(f"未知时区：{value!r}") from exc
        return value

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str) -> str:
        return value.strip()


class TarotDrawPayload(_StrictPayload):
    """POST /divination/tarot/draw 请求体（kind 预置 tarot）。"""

    spread_id: str | None = Field(default=None, max_length=64)
    question: str = Field(default="", max_length=500)
    timezone_id: str = Field(
        default=DEFAULT_TIMEZONE_ID, min_length=1, max_length=64
    )
    workspace_id: str = Field(
        default=DEFAULT_WORKSPACE_ID, min_length=1, max_length=128
    )

    @field_validator("timezone_id")
    @classmethod
    def require_loadable_zone(cls, value: str) -> str:
        from zoneinfo import ZoneInfo

        try:
            ZoneInfo(value)
        except Exception as exc:
            raise ValueError(f"未知时区：{value!r}") from exc
        return value

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str) -> str:
        return value.strip()


class BaziPreviewPayload(_StrictPayload):
    """POST /divination/bazi/preview 请求体（只读投影，零持久化）。"""

    year: int = Field(ge=1, le=9999, strict=True)
    month: int = Field(ge=1, le=12, strict=True)
    day: int = Field(ge=1, le=31, strict=True)
    hour: int = Field(ge=0, le=23, strict=True)
    minute: int = Field(default=0, ge=0, le=59, strict=True)
    timezone_id: str = Field(
        default=DEFAULT_TIMEZONE_ID, min_length=1, max_length=64
    )

    @field_validator("timezone_id")
    @classmethod
    def require_loadable_zone(cls, value: str) -> str:
        from zoneinfo import ZoneInfo

        try:
            ZoneInfo(value)
        except Exception as exc:
            raise ValueError(f"未知时区：{value!r}") from exc
        return value
