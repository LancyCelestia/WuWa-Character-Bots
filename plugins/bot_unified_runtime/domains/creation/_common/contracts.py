"""creation 生成域共用契约层：任务状态机 / 取消语义 / 计量 / 资产引用 / 错误目录。

`reserved: 依赖外部 provider 配置，未实现`。本模块是 v21r2-reorg-plan.md §9.1
「任务状态机与 asset 交付共用件」的协议草案，只定义 Pydantic 严格 DTO、协议
常量、枚举与纯函数——零框架、零网络、零线程、零配置读取，可被 importlib
直载探针独立验证（V21-CORE-001 纪律；v21r2-reorg-plan.md §9.4 reserved 契约
形态 lint）。

合同锚点：
- docs/design/v21r2-reorg-plan.md §9.1（creation 域字段级契约草案）
- docs/design/backend-v2-implementation-guide.md §6（严格 DTO 拒未知字段/NaN/
  Infinity）、§7 L198（cancel_requested ≠ cancelled）、§11（L256 TTS/L258 绘图）
- docs/design/backend-v2-product-extensions.md §1（L16 字段表/L23 多单位计费/
  L29 Decimal 禁浮点/L49 确定性算例/L56 多图按实结算/L58 取消保留费用）

与 llm/billing_entities.py 的关系：那边是 V2.1 计费权威实现（已落地段）；
本模块按扩展 §1 语义为 creation 域定义**预留态**计量 DTO——Token 指标在
creation 域永远不得伪造（provider 真报才可携带，否则 not_applicable/unknown，
不得按字符/图片数倒推精确 Token）。字段命名与不变量有意对齐 billing_entities，
收敛到单一来源属激活期席位工作（§10 W-PA 后续波）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

# ---------------------------------------------------------------------------
# 严格基类（对齐 contracts/envelope.py V21StrictBase 口径）
# ---------------------------------------------------------------------------


class CreationContractBase(BaseModel):
    """creation 域契约严格基类：禁未知字段、禁 NaN/Infinity。

    extra="forbid" 即 §6「未支持参数 422 unsupported_parameter 不静默丢弃」的
    DTO 层机器形态；allow_inf_nan=False 拒 NaN/Infinity。
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def _require_aware_utc(name: str, value: datetime) -> datetime:
    """拒绝 naive datetime；aware 值一律归一到 UTC。"""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} 必须带时区（UTC ISO8601）")
    return value.astimezone(timezone.utc)


def _decimal_no_float(value: object) -> object:
    """金额/计量 value 禁浮点入参（扩展 §1 L29：Decimal 序列化，禁 float）。"""
    if isinstance(value, float):
        raise ValueError(  # noqa: TRY004 - pydantic v2 校验器抛 ValueError 才转 ValidationError
            "金额/计量值禁止浮点入参（用 Decimal 或字符串十进制）"
        )
    return value


def _decimal_finite_nonneg(name: str, value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    try:
        is_finite = value.is_finite()
    except InvalidOperation:  # pragma: no cover - Decimal 构造期已拦
        is_finite = False
    if not is_finite:
        raise ValueError(f"{name} 必须是有限十进制数（拒 NaN/Infinity）")
    if value < 0:
        raise ValueError(f"{name} 必须非负")
    return value


# ---------------------------------------------------------------------------
# 任务状态机与取消语义（§9.1.1 任务状态机段；TTS/绘图共用，§9.1.2 同款）
# ---------------------------------------------------------------------------


class CreationJobState(str, Enum):
    """生成任务状态机：pending→admitted→running→succeeded/failed/cancelled/unknown。

    语义锚点（指南 §7 L198、§11 L256/L258）：
    - ``cancel_requested`` 是请求标记不是状态——``CancelRequest`` 受理只记标记，
      终态仍须等到 succeeded/failed/cancelled/unknown 之一；
    - ``unknown``：已受理但结果未知的任务**不盲重合成/重发**，对账走独立
      reconcile 面，状态机内 unknown 无出边（不得复活）；
    - 取消保留可能已产生的费用（扩展 §1 L58）。
    """

    PENDING = "pending"
    ADMITTED = "admitted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


JOB_STATES: frozenset[str] = frozenset(state.value for state in CreationJobState)

TERMINAL_JOB_STATES: frozenset[CreationJobState] = frozenset(
    {
        CreationJobState.SUCCEEDED,
        CreationJobState.FAILED,
        CreationJobState.CANCELLED,
        CreationJobState.UNKNOWN,
    }
)

ALLOWED_JOB_TRANSITIONS: dict[CreationJobState, frozenset[CreationJobState]] = {
    CreationJobState.PENDING: frozenset(
        {CreationJobState.ADMITTED, CreationJobState.FAILED, CreationJobState.CANCELLED}
    ),
    CreationJobState.ADMITTED: frozenset(
        {CreationJobState.RUNNING, CreationJobState.FAILED, CreationJobState.CANCELLED}
    ),
    CreationJobState.RUNNING: frozenset(
        {
            CreationJobState.SUCCEEDED,
            CreationJobState.FAILED,
            CreationJobState.CANCELLED,
            CreationJobState.UNKNOWN,
        }
    ),
    CreationJobState.SUCCEEDED: frozenset(),
    CreationJobState.FAILED: frozenset(),
    CreationJobState.CANCELLED: frozenset(),
    CreationJobState.UNKNOWN: frozenset(),
}

#: 取消语义常量（指南 §7 L198；扩展 §1 L58）。
CANCEL_REQUESTED_IS_NOT_A_STATE = True
CANCEL_MAY_KEEP_COST = True
UNKNOWN_NEVER_AUTO_REDISPATCH = True


def can_transition(current: CreationJobState, target: CreationJobState) -> bool:
    """纯函数：状态迁移合法性（终态无出边；unknown 不复活）。"""
    return target in ALLOWED_JOB_TRANSITIONS[current]


class CancelRequest(CreationContractBase):
    """取消请求：只申请（cancel_requested），不承诺即时 cancelled。"""

    job_id: str = Field(min_length=1, max_length=128)
    requested_by: str = Field(min_length=1, max_length=128)
    reason: str = Field(default="", max_length=512)
    requested_at: datetime

    @field_validator("requested_at")
    @classmethod
    def _aware_requested_at(cls, value: datetime) -> datetime:
        return _require_aware_utc("requested_at", value)


# ---------------------------------------------------------------------------
# 计量 DTO（扩展 §1 L16/L23：多单位计费；Token 不伪造）
# ---------------------------------------------------------------------------

QuantityStatus = Literal["measured", "estimated", "unknown", "not_applicable"]

#: creation 域允许的计量（非 Token）：TTS 取 characters/audio_seconds/requests
#: 子集，绘图取 images/requests 子集（扩展 §1 L23）。
CREATION_METRICS: frozenset[str] = frozenset(
    {"characters", "audio_seconds", "images", "requests"}
)

#: metric → 计量单位（接口不能省略单位让调用方猜）。
CREATION_METRIC_UNITS: dict[str, str] = {
    "characters": "characters",
    "audio_seconds": "seconds",
    "images": "images",
    "requests": "requests",
}

#: Token 指标名：creation 域用量 DTO 内出现即拒绝（防止按字符/图片伪造）。
TOKEN_METRIC_NAMES: frozenset[str] = frozenset(
    {
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cache_create_tokens",
        "cache_read_tokens",
    }
)


class UsageLine(CreationContractBase):
    """单一计量行：metric+value+unit+status(+tier)。

    不变量（扩展 §1 L16）：``value is None`` ⇔ ``status ∈ {unknown,
    not_applicable}``；measured/estimated 必须携带有限非负 Decimal。
    ``resolution_tier`` 仅绘图分辨率档独立计费有意义（扩展 §1 L23）。
    """

    metric: str = Field(min_length=1, max_length=64)
    value: Decimal | None = None
    unit: str = Field(min_length=1, max_length=32)
    status: QuantityStatus
    source: str = Field(default="", max_length=128)
    resolution_tier: str = Field(default="", max_length=64)

    @field_validator("metric")
    @classmethod
    def _metric_is_creation(cls, value: str) -> str:
        if value in TOKEN_METRIC_NAMES:
            raise ValueError(
                f"creation 域用量禁止 Token 指标 {value!r}（不伪造 Token；"
                "Token 仅 provider 真报时由账本层携带）"
            )
        if value not in CREATION_METRICS:
            raise ValueError(
                f"不支持的计量: {value!r}（合法集合: {sorted(CREATION_METRICS)}）"
            )
        return value

    @field_validator("unit")
    @classmethod
    def _unit_canonical(cls, value: str, info: ValidationInfo) -> str:
        metric = str(info.data.get("metric", ""))
        expected = CREATION_METRIC_UNITS.get(metric)
        if expected is not None and value != expected:
            raise ValueError(f"metric={metric} 的单位必须是 {expected!r}，收到 {value!r}")
        return value

    @field_validator("value", mode="before")
    @classmethod
    def _value_no_float(cls, value: object) -> object:
        return _decimal_no_float(value)

    @field_validator("value")
    @classmethod
    def _value_finite_nonneg(cls, value: Decimal | None, info: ValidationInfo) -> Decimal | None:
        return _decimal_finite_nonneg(f"quantities[{info.data.get('metric')}].value", value)

    @model_validator(mode="after")
    def _status_value_consistent(self) -> UsageLine:
        if self.status in ("unknown", "not_applicable"):
            if self.value is not None:
                raise ValueError(f"status={self.status} 时 value 必须为 null（未知/不适用不得携带数量）")
        else:
            if self.value is None:
                raise ValueError(f"status={self.status} 必须携带 value（未知不是 0）")
        if self.resolution_tier and self.metric != "images":
            raise ValueError("resolution_tier 仅支持 images 指标（分辨率档独立计费）")
        return self


class CostAmount(CreationContractBase):
    """金额：Decimal + ISO 币种，禁浮点（扩展 §1 L29）。"""

    amount: Decimal
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")

    @field_validator("amount", mode="before")
    @classmethod
    def _amount_no_float(cls, value: object) -> object:
        return _decimal_no_float(value)

    @field_validator("amount")
    @classmethod
    def _amount_finite_nonneg(cls, value: Decimal) -> Decimal | None:
        return _decimal_finite_nonneg("cost.amount", value)


# ---------------------------------------------------------------------------
# 资产引用（V21-FILE-002 面：API 用 asset_id，非服务器路径；指南 §11 L254）
# ---------------------------------------------------------------------------

ASSET_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
#: 绘图输入分辨率上限：≤20MP（指南 §11 L258）。
IMAGE_MAX_INPUT_PIXELS = 20_000_000


class AssetRef(CreationContractBase):
    """受管资产引用：只收 asset_id，拒服务器路径/URL/穿越形态。

    输入图获取走 DownloadBroker（对齐 SEARCH-002 面），不接任意 URL 抓取
    （指南 §11 L258）；``pixel_count`` 由资产元数据带入，超 20MP 拒绝。
    """

    asset_id: str = Field(min_length=1, max_length=128, pattern=ASSET_ID_PATTERN)
    pixel_count: int | None = Field(default=None, ge=1, le=IMAGE_MAX_INPUT_PIXELS)

    @field_validator("asset_id")
    @classmethod
    def _reject_path_like(cls, value: str) -> str:
        if ".." in value or "/" in value or "\\" in value or "://" in value:
            raise ValueError("asset_id 必须是注册表资产标识，不得含路径/URL/穿越形态")
        return value


# ---------------------------------------------------------------------------
# 错误目录（§6 单一注册源；扩展 §10 L311 集中注册——creation 域切片）
# ---------------------------------------------------------------------------

CreationErrorCode = Literal[
    "unsupported_parameter",
    "dependency_unavailable",
    "price_unavailable",
    "budget_exceeded",
]

#: code → HTTP 状态（§9.1.1 参数校验与错误码段）。
CREATION_ERROR_CATALOG: dict[CreationErrorCode, int] = {
    "unsupported_parameter": 422,
    "dependency_unavailable": 503,
    "price_unavailable": 503,
    "budget_exceeded": 429,
}


__all__ = [
    "ALLOWED_JOB_TRANSITIONS",
    "ASSET_ID_PATTERN",
    "CANCEL_MAY_KEEP_COST",
    "CANCEL_REQUESTED_IS_NOT_A_STATE",
    "CREATION_ERROR_CATALOG",
    "CREATION_METRICS",
    "CREATION_METRIC_UNITS",
    "IMAGE_MAX_INPUT_PIXELS",
    "JOB_STATES",
    "TERMINAL_JOB_STATES",
    "TOKEN_METRIC_NAMES",
    "UNKNOWN_NEVER_AUTO_REDISPATCH",
    "AssetRef",
    "CancelRequest",
    "CostAmount",
    "CreationContractBase",
    "CreationErrorCode",
    "CreationJobState",
    "QuantityStatus",
    "UsageLine",
    "_require_aware_utc",
    "can_transition",
]
