"""V2.1 S5 计费实体层（严格 Pydantic DTO + 错误码 + 金额纪律）。

合同：``docs/design/backend-v2-product-extensions.md`` §1.1（数据模型）、
§1.2（金额 Decimal 纪律）。复用既有 ``llm/ledger.py`` 账本（只读适配，
见 billing_service），不建平行账本；本模块是纯实体层。

设计约束（对齐 contracts/envelope.py 的严格风格）：
- 叶子模块：只依赖 pydantic + 标准库，**不 import 本包任何模块**
  （``contracts/__init__`` 会经 character 链拉起重依赖；``V21StrictBase``
  属有意的最小复制，收敛到单一来源属后续装配席位——与 envelope.py 同例）。
- ``extra="forbid"`` 拒绝未知字段；``allow_inf_nan=False`` 拒绝 NaN/Infinity；
  时间字段强制带时区并归一到 UTC。
- **金额纪律（§1.2）**：金额/价格一律 :class:`~decimal.Decimal`；序列化恒为
  十进制普通记数字符串（禁科学计数法、禁浮点）；入参为 ``float`` 的金额/
  价格字段直接拒绝——金额不允许经浮点中转。行级金额量化到 1e-9（nano，
  ``微额精度``：1 token × 0.01/百万 = 0.00000001 不塌缩为 0）。
- **未知 ≠ 零**：``measured(0)``（免费但实际已知为 0）与 ``unknown``（缺失）
  严格区分；value=None 当且仅当 status ∈ {unknown, not_applicable}。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import (
    ROUND_CEILING,
    ROUND_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    Decimal,
    InvalidOperation,
)
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

# ==================== 计量与状态枚举（§1.1） ====================

TOKEN_METRICS: tuple[str, ...] = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cache_create_tokens",
    "cache_read_tokens",
)
NON_TOKEN_METRICS: tuple[str, ...] = (
    "characters",
    "audio_seconds",
    "images",
    "requests",
)
ALL_METRICS: frozenset[str] = frozenset(TOKEN_METRICS + NON_TOKEN_METRICS)

#: metric → 计量单位（接口不能省略单位让调用方猜，§9.1）。
METRIC_UNITS: dict[str, str] = {
    "input_tokens": "tokens",
    "output_tokens": "tokens",
    "total_tokens": "tokens",
    "cache_create_tokens": "tokens",
    "cache_read_tokens": "tokens",
    "characters": "characters",
    "audio_seconds": "seconds",
    "images": "images",
    "requests": "requests",
}

QuantityStatus = Literal["measured", "estimated", "unknown", "not_applicable"]

QUANTITY_STATUSES: tuple[str, ...] = ("measured", "estimated", "unknown", "not_applicable")

#: 输入语义（§1.1：必须记录 input_semantics 与 cache_creation_includes_read）。
InputSemantics = Literal["inclusive_cache", "exclusive_cache", "unknown"]
INPUT_SEMANTICS_VALUES: tuple[str, ...] = ("inclusive_cache", "exclusive_cache", "unknown")

#: 计费组成（§1.2）：按次费是否叠加 Token 费由价格规则决定。
Composition = Literal["additive", "exclusive", "tiered"]
COMPOSITIONS: tuple[str, ...] = ("additive", "exclusive", "tiered")

#: Settlement 状态（§1.1）。
SettlementStatus = Literal[
    "reserved", "estimated", "settled", "partial", "unknown", "refunded"
]
SETTLEMENT_STATUSES: tuple[str, ...] = (
    "reserved",
    "estimated",
    "settled",
    "partial",
    "unknown",
    "refunded",
)

AttemptOutcome = Literal["succeeded", "failed", "timeout", "cancelled", "unknown"]

TaskKind = Literal["chat", "tts", "image", "other"]

RoundingMode = Literal["half_up", "half_even", "ceiling", "floor"]
_ROUNDING_MAP = {
    "half_up": ROUND_HALF_UP,
    "half_even": ROUND_HALF_EVEN,
    "ceiling": ROUND_CEILING,
    "floor": ROUND_DOWN,
}

#: 行级金额量化精度：1e-9（nano）。微额（如 1 token × 0.01/1M = 1e-8）
#: 在此精度下不塌缩为 0；账本旧 cost_milli（1e-3）是其真子集。
AMOUNT_EXPONENT = Decimal("0.000000001")

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")

# 总数推导来源：优先 provider 报告；仅在适配器确认集合不重叠时推导。
TOTAL_SOURCES: tuple[str, ...] = ("provider", "derived_non_overlapping", "unknown")


# ==================== 错误（§10 补充错误集中注册口径） ====================


class UsageBillingError(Exception):
    """计费域错误基类；``code`` 与 §10 错误注册表对齐。"""

    def __init__(self, message: str, *, code: str = "billing_error") -> None:
        super().__init__(message)
        self.code = code


class UsageInconsistentError(UsageBillingError):
    """用量自相矛盾（如 inclusive 下 create+read > input）。

    §1.2：差值负数返回 ``usage_inconsistent``，**不能 max(0) 掩盖异常**。
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, code="usage_inconsistent")


class UnsupportedSemanticsError(UsageBillingError):
    """不支持的语义组合（§1.1：拒绝自动结算，转人工/对账路径）。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="unsupported_usage_semantics")


class PriceUnavailableError(UsageBillingError):
    """价格缺失且无已授权保守上限（§1.3：付费任务返回 price_unavailable，
    不以 unknown 绕过预算）。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="price_unavailable")


class SettlementImmutableError(UsageBillingError):
    """历史结算不可覆盖（§1.1：调整走追加 revision，不改写已结算行）。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="settlement_immutable")


class BudgetExceededError(UsageBillingError):
    """预算不足（§10：budget_exceeded 429）。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="budget_exceeded")


class BudgetNotFoundError(UsageBillingError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="budget_not_found")


# ==================== 基础设施 ====================


def _require_aware(name: str, value: datetime) -> datetime:
    """拒绝 naive datetime；aware 值一律归一到 UTC。"""
    if not isinstance(value, datetime):
        # ValueError 而非 TypeError：pydantic 校验链只包装 ValueError 为
        # ValidationError（TRY004 在此域刻意不适用）。
        raise ValueError(f"{name} 必须是 datetime")  # noqa: TRY004
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} 必须带时区（UTC ISO8601）")
    return value.astimezone(timezone.utc)


class V21BillingBase:
    """严格配置基类（pydantic 混入式：子类继承 BaseModel + 本类）。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def _check_decimal_finite(field: str, value: Decimal) -> Decimal:
    if not value.is_finite():
        raise ValueError(f"{field} 必须是有限十进制数（拒绝 NaN/Infinity）")
    return value


def _reject_float(field: str, value: object) -> None:
    """金额纪律：float 入参直接拒绝（金额不允许经浮点中转）。"""
    if isinstance(value, float):
        # ValueError（非 TypeError）：需经 pydantic 包装为 ValidationError。
        raise ValueError(  # noqa: TRY004
            f"{field} 不接受浮点入参（金额一律 Decimal/str/int）"
        )


def _money_before(value: object) -> object:
    """mode=before 金额守卫：pydantic 会在 after 校验前把 float 转 Decimal，
    浮点拒绝必须在 before 阶段做。None 直通（Optional 字段）。"""
    if value is None:
        return None
    _reject_float("money field", value)
    return value


def parse_decimal(value: object, *, what: str) -> Decimal:
    """宽松转 Decimal（str/int/Decimal）；float 拒绝；非法抛 ValueError。"""
    _reject_float(what, value)
    if isinstance(value, Decimal):
        return _check_decimal_finite(what, value)
    if isinstance(value, int) and not isinstance(value, bool):
        return Decimal(value)
    if isinstance(value, str):
        try:
            return _check_decimal_finite(what, Decimal(value.strip()))
        except InvalidOperation as exc:
            raise ValueError(f"{what} 不是合法十进制数: {value!r}") from exc
    raise ValueError(f"{what} 类型不支持: {type(value).__name__}")


def quantize_amount(value: Decimal, mode: RoundingMode = "half_up") -> Decimal:
    """金额量化到 nano（1e-9），规则来自 PriceRevision.rounding。"""
    return value.quantize(AMOUNT_EXPONENT, rounding=_ROUNDING_MAP[mode])


def money_str(value: Decimal | None) -> str | None:
    """Decimal → 十进制普通记数字符串（**禁科学计数法**：1e-8 → "0.00000001"）。

    format(v, "f") 恒为定点表示；None 原样返回（未知不是 0）。
    """
    if value is None:
        return None
    return format(value, "f")


def amount_to_micros(value: Decimal, *, what: str) -> int:
    """Decimal → 微元整数（预算 CAS 算术用；超精度拒绝而非静默舍入）。"""
    _check_decimal_finite(what, value)
    scaled = value * Decimal(1_000_000)
    if scaled != scaled.to_integral_value():
        raise ValueError(f"{what} 精度超过微元（1e-6），预算口径拒绝: {value}")
    return int(scaled)


def micros_to_amount(micros: int) -> Decimal:
    return Decimal(micros) / Decimal(1_000_000)


# ==================== 用量实体（§1.1） ====================


class UsageQuantity(V21BillingBase, BaseModel):
    """单一计量：metric+value+unit+status+source。

    不变量：``value is None`` ⇔ ``status ∈ {unknown, not_applicable}``；
    measured/estimated 必须携带有限非负 value（§1.1：value 为有限非负数或
    null）。``cache_tier`` 仅对缓存创建指标有意义（5m/1h 等价格档）。
    """

    metric: str = Field(min_length=1, max_length=64)
    value: Decimal | None = None
    unit: str = Field(min_length=1, max_length=32)
    status: QuantityStatus
    source: str = Field(default="", max_length=128)
    cache_tier: str = Field(default="", max_length=32)

    @field_validator("metric")
    @classmethod
    def _metric_known(cls, value: str) -> str:
        if value not in ALL_METRICS:
            raise ValueError(
                f"不支持的计量: {value!r}（合法集合: {sorted(ALL_METRICS)}）"
            )
        return value

    @field_validator("unit")
    @classmethod
    def _unit_canonical(cls, value: str, info) -> str:
        metric = str(info.data.get("metric", ""))
        expected = METRIC_UNITS.get(metric)
        if expected is not None and value != expected:
            raise ValueError(f"metric={metric} 的单位必须是 {expected!r}，收到 {value!r}")
        return value

    @field_validator("value", mode="before")
    @classmethod
    def _value_no_float(cls, value: object) -> object:
        return _money_before(value)

    @field_validator("value")
    @classmethod
    def _value_finite_nonneg(cls, value: Decimal | None, info) -> Decimal | None:
        if value is None:
            return None
        _reject_float(f"quantities[{info.data.get('metric')}].value", value)
        _check_decimal_finite("value", value)
        if value < 0:
            raise ValueError("value 必须非负（负数差值属 usage_inconsistent，"
                             "由报价层显式报错，禁止以负数量入库）")
        return value

    @model_validator(mode="after")
    def _status_value_consistent(self) -> UsageQuantity:
        if self.status in ("unknown", "not_applicable"):
            if self.value is not None:
                raise ValueError(
                    f"status={self.status} 时 value 必须为 null（未知/不适用"
                    "不得携带数量）"
                )
        else:
            if self.value is None:
                raise ValueError(f"status={self.status} 必须携带 value（未知不是 0）")
        if self.cache_tier and self.metric != "cache_create_tokens":
            raise ValueError("cache_tier 仅支持 cache_create_tokens 指标")
        return self

    @field_serializer("value", when_used="always")
    def _ser_value(self, value: Decimal | None) -> str | None:
        return money_str(value)


class UsageSnapshot(V21BillingBase, BaseModel):
    """normalize_usage 的输出：一次 attempt 的归一化用量视图。

    - ``quantities``：metric → UsageQuantity（缺省指标不建键或 status=unknown）。
    - ``input_semantics`` / ``cache_creation_includes_read``：§1.1 必记录字段；
      includes_read 三态用 ``bool | None``（None=unknown）。
    - ``total_source``：total_tokens 的来源——provider 报告优先；仅在适配器
      确认各项集合不重叠（exclusive）时推导；inclusive 语义下**绝不推导**
      （缓存是输入子集，推导必然二次累计）。
    - ``blocked_reason``：不支持的语义组合在此登记（报价层据此拒绝自动结算）。
    """

    task_kind: TaskKind = "chat"
    input_semantics: InputSemantics = "unknown"
    cache_creation_includes_read: bool | None = None
    quantities: dict[str, UsageQuantity] = Field(default_factory=dict)
    total_source: Literal["provider", "derived_non_overlapping", "unknown"] = "unknown"
    provider_schema: str = Field(default="unknown", max_length=64)
    raw_usage_schema_version: str = Field(default="unknown", max_length=64)
    blocked_reason: str = ""

    def quantity(self, metric: str) -> UsageQuantity | None:
        return self.quantities.get(metric)

    def value(self, metric: str) -> Decimal | None:
        qty = self.quantities.get(metric)
        return None if qty is None else qty.value


# ==================== 价格实体（§1.1） ====================


class PriceComponent(V21BillingBase, BaseModel):
    """单计量价格：unit_price / denominator（计量分母，默认每百万）。

    ``tier`` 用于缓存创建多档（5m/1h）；``bracket_up_to`` 仅在
    composition=tiered 的阶梯计价中有意义（含上界，None=不封顶）。
    """

    metric: str
    tier: str = ""
    unit_price: Decimal
    denominator: Decimal = Decimal(1_000_000)
    bracket_up_to: Decimal | None = None

    @field_validator("metric")
    @classmethod
    def _metric_known(cls, value: str) -> str:
        if value not in ALL_METRICS:
            raise ValueError(f"不支持的计价计量: {value!r}")
        return value

    @field_validator("unit_price", "denominator", "bracket_up_to", mode="before")
    @classmethod
    def _no_float_before(cls, value: object) -> object:
        return _money_before(value)

    @field_validator("unit_price", "denominator", "bracket_up_to")
    @classmethod
    def _finite(cls, value: Decimal | None, info) -> Decimal | None:
        if value is None:
            return None
        _reject_float(f"price_component.{info.field_name}", value)
        return _check_decimal_finite(info.field_name, value)

    @model_validator(mode="after")
    def _positive(self) -> PriceComponent:
        if self.unit_price < 0:
            raise ValueError("unit_price 必须非负")
        if self.denominator <= 0:
            raise ValueError("denominator（计量分母）必须为正")
        return self

    @field_serializer("unit_price", "denominator", "bracket_up_to", when_used="always")
    def _ser(self, value: Decimal | None) -> str | None:
        return money_str(value)


class PriceRevision(V21BillingBase, BaseModel):
    """价格版本（§1.1）：跨生效边界按 attempt_started_at 解析，半开区间
    ``[effective_from, effective_to)``。

    - ``cache_price_follows_input``：**唯一**允许"缺缓存价回退普通输入价"的
      通道——必须来自 provider 价格规则的显式声明；缺省 False（§1.2：
      缺缓存价格不得默认等于普通价）。旧 ledger 的静默回退不在此推广。
    - ``tax_note``：税费/折扣语义显式记录（§1.2），最终 provider 账单优先。
    """

    price_id: str = Field(min_length=1, max_length=128)
    version: int = Field(ge=1)
    provider: str = Field(min_length=1, max_length=128)
    channel: str = Field(max_length=128)  # "" / "unknown" = 渠道无关
    model: str = Field(min_length=1, max_length=128)  # "*" = 模型无关
    effective_from: datetime
    effective_to: datetime | None = None
    currency: str = Field(min_length=3, max_length=3)
    composition: Composition = "additive"
    components: list[PriceComponent] = Field(default_factory=list)
    rounding: RoundingMode = "half_up"
    cache_price_follows_input: bool = False
    tax_note: str = Field(default="", max_length=256)
    adapter_version: str = Field(default="", max_length=64)
    source: str = Field(default="", max_length=128)
    reviewed_by: str = Field(default="", max_length=128)

    @field_validator("effective_from", "effective_to")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _require_aware("effective", value)

    @field_validator("currency")
    @classmethod
    def _currency_iso(cls, value: str) -> str:
        if not _CURRENCY_RE.match(value):
            raise ValueError(f"currency 必须是 ISO-4217 三字母大写: {value!r}")
        return value

    @model_validator(mode="after")
    def _window_and_components(self) -> PriceRevision:
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to 必须晚于 effective_from")
        seen: set[tuple[str, str]] = set()
        for comp in self.components:
            key = (comp.metric, comp.tier)
            if key in seen:
                raise ValueError(f"重复的价格组成: metric={comp.metric} tier={comp.tier!r}")
            seen.add(key)
        if not self.components:
            raise ValueError("PriceRevision 至少需要一个价格组成")
        return self

    def component(self, metric: str, tier: str = "") -> PriceComponent | None:
        for comp in self.components:
            if comp.metric == metric and comp.tier == tier:
                return comp
        return None

    def covers(self, at: datetime) -> bool:
        """半开区间 [from, to)；边界时刻属于新版本。"""
        if at < self.effective_from:
            return False
        return self.effective_to is None or at < self.effective_to

    @field_serializer("effective_from", "effective_to", when_used="always")
    def _ser_time(self, value: datetime | None) -> str | None:
        return None if value is None else value.isoformat(timespec="milliseconds")


# ==================== 账单实体（§1.1） ====================


class ChargeLine(V21BillingBase, BaseModel):
    """账单行：一次结算内单计量的金额构成。

    - ``amount=None`` + ``status="unpriced_unknown_price"``：该计量有用量但
      无价格（且不允许回退）——**不出假总价**（§1.2 算例④）。
    - 负金额仅允许出现在 refunded/adjustment 行（退款/调整），普通行非负。
    - ``price_source="follows_input_rule"``：价格经 provider 显式回退规则
      取得（区别于旧账本的静默回退）。
    """

    line_id: str = Field(min_length=1, max_length=128)
    attempt_id: str = Field(min_length=1, max_length=128)
    metric: str
    tier: str = ""
    quantity: Decimal | None = None
    unit: str = Field(min_length=1, max_length=32)
    unit_price: Decimal | None = None
    denominator: Decimal | None = None
    price_id: str = Field(default="", max_length=128)
    price_version: int | None = None
    price_source: Literal["listed", "follows_input_rule", "none"] = "listed"
    amount: Decimal | None = None
    currency: str = Field(min_length=3, max_length=3)
    status: Literal[
        "billed",
        "not_billed",
        "unpriced_unknown_price",
        "unknown_usage",
        "refunded",
        "adjustment",
    ] = "billed"
    billing_group: str = Field(default="", max_length=128)

    @field_validator("quantity", "amount", "unit_price", "denominator", mode="before")
    @classmethod
    def _no_float_before(cls, value: object) -> object:
        return _money_before(value)

    @field_validator("quantity", "amount", "unit_price", "denominator")
    @classmethod
    def _finite(cls, value: Decimal | None, info) -> Decimal | None:
        if value is None:
            return None
        _reject_float(f"charge_line.{info.field_name}", value)
        return _check_decimal_finite(info.field_name, value)

    @field_validator("currency")
    @classmethod
    def _currency_iso(cls, value: str) -> str:
        if not _CURRENCY_RE.match(value):
            raise ValueError(f"currency 必须是 ISO-4217 三字母大写: {value!r}")
        return value

    @model_validator(mode="after")
    def _sign_rules(self) -> ChargeLine:
        negative_allowed = self.status in ("refunded", "adjustment")
        if self.amount is not None and self.amount < 0 and not negative_allowed:
            raise ValueError("普通账单行金额必须非负（负数仅限退款/调整行）")
        if self.amount is not None and self.quantity is not None and self.amount < 0 \
                and not negative_allowed:
            raise ValueError("账单行数量与金额必须非负")
        if self.quantity is not None and self.quantity < 0:
            raise ValueError("账单行数量必须非负")
        return self

    @field_serializer("quantity", "amount", "unit_price", "denominator", when_used="always")
    def _ser(self, value: Decimal | None) -> str | None:
        return money_str(value)


class UsageQuote(V21BillingBase, BaseModel):
    """quote_usage 输出：结算前的确定性报价视图。

    - ``status``：``ok`` 全计量可结；``partial`` 有未知计量/未知价格
      （total_amount=None，只给 known_amount 与可选区间）；``refused`` 语义
      组合不支持（拒绝自动结算）。
    - ``amount_low/high``：缺缓存用量但输入总量已知时的报价区间（§1.2），
      仅在可给出有界估计时非 None。
    """

    attempt_id: str = Field(min_length=1, max_length=128)
    currency: str = Field(min_length=3, max_length=3)
    status: Literal["ok", "partial", "refused"] = "ok"
    composition: Composition = "additive"
    price_id: str = Field(default="", max_length=128)
    price_version: int | None = None
    lines: list[ChargeLine] = Field(default_factory=list)
    total_amount: Decimal | None = None
    known_amount: Decimal = Decimal(0)
    amount_low: Decimal | None = None
    amount_high: Decimal | None = None
    unknown_metrics: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @field_validator("known_amount", "total_amount", "amount_low", "amount_high",
                     mode="before")
    @classmethod
    def _no_float_before(cls, value: object) -> object:
        return _money_before(value)

    @field_validator("known_amount")
    @classmethod
    def _known_finite(cls, value: Decimal, info) -> Decimal:
        _reject_float("quote.known_amount", value)
        return _check_decimal_finite("known_amount", value)

    @model_validator(mode="after")
    def _status_consistency(self) -> UsageQuote:
        if self.status == "refused":
            return self
        if self.total_amount is not None and self.total_amount < 0:
            raise ValueError("报价总额必须非负")
        if self.status == "partial" and self.total_amount is not None:
            raise ValueError("partial 报价不得给出 total_amount（不出假总价）")
        return self

    @field_serializer("total_amount", "known_amount", "amount_low", "amount_high",
                      when_used="always")
    def _ser(self, value: Decimal | None) -> str | None:
        return money_str(value)


class Settlement(V21BillingBase, BaseModel):
    """结算（§1.1）：reserved/estimated/settled/partial/unknown/refunded。

    **不可覆盖历史结算**：已落库结算行只读；修正/退款一律追加新 revision
    （``revision`` 递增、``prev_settlement_id`` 回链），原始行逐字节保留。
    不变量：``total_amount is None`` ⇔ ``status ∈ {partial, unknown}``；
    ``settled`` 时 total_amount == sum(billed 行金额)。
    """

    settlement_id: str = Field(min_length=1, max_length=128)
    attempt_id: str = Field(min_length=1, max_length=128)
    operation_id: str = Field(default="", max_length=128)
    revision: int = Field(default=1, ge=1)
    status: SettlementStatus
    currency: str = Field(min_length=3, max_length=3)
    total_amount: Decimal | None = None
    known_amount: Decimal = Decimal(0)
    unknown_metrics: list[str] = Field(default_factory=list)
    lines: list[ChargeLine] = Field(default_factory=list)
    invoice_ref: str = Field(default="", max_length=256)
    prev_settlement_id: str | None = None
    adjustment_id: str | None = None
    reservation_id: str | None = None
    note: str = Field(default="", max_length=512)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _aware_created(cls, value: datetime) -> datetime:
        return _require_aware("created_at", value)

    @field_validator("currency")
    @classmethod
    def _currency_iso(cls, value: str) -> str:
        if not _CURRENCY_RE.match(value):
            raise ValueError(f"currency 必须是 ISO-4217 三字母大写: {value!r}")
        return value

    @field_validator("known_amount", "total_amount", mode="before")
    @classmethod
    def _no_float_before(cls, value: object) -> object:
        return _money_before(value)

    @field_validator("known_amount", "total_amount")
    @classmethod
    def _finite(cls, value: Decimal | None, info) -> Decimal | None:
        if value is None:
            return None
        _reject_float(f"settlement.{info.field_name}", value)
        return _check_decimal_finite(info.field_name, value)

    @model_validator(mode="after")
    def _status_consistency(self) -> Settlement:
        if self.status in ("partial", "unknown"):
            if self.total_amount is not None:
                raise ValueError(
                    f"status={self.status} 时 total_amount 必须为 null（不出假总价）"
                )
        else:
            if self.total_amount is None and self.status not in ("reserved",):
                raise ValueError(f"status={self.status} 必须携带 total_amount")
        if self.total_amount is not None and self.total_amount < 0:
            raise ValueError("结算总额必须非负")
        if self.status == "partial" and not self.unknown_metrics:
            raise ValueError("partial 结算必须登记 unknown_metrics")
        return self

    @field_serializer("total_amount", "known_amount", when_used="always")
    def _ser(self, value: Decimal | None) -> str | None:
        return money_str(value)

    @field_serializer("created_at", when_used="always")
    def _ser_time(self, value: datetime) -> str:
        return value.isoformat(timespec="milliseconds")


# ==================== 尝试与聚合（§1.1/§1.3） ====================


class UsageAttempt(V21BillingBase, BaseModel):
    """一次 provider 尝试（§1.1 必含字段全集）。

    - ``operation`` 表述用户一次任务；failover 重试产生同 operation 的多个
      attempt，费用归原 operation（§1.3：不能只统计最后成功模型）。
    - ``channel``：被 AxonHub 隐藏时保存 ``"unknown"``，**不拿模型名冒充
      渠道**（由服务层 normalize_channel 保证）。
    - ``outcome`` 含 cancelled：取消只标 cancel_requested（结算层），已产生
      费用照常入账。
    """

    attempt_id: str = Field(min_length=1, max_length=128)
    operation_id: str = Field(min_length=1, max_length=128)
    provider_request_id: str = Field(default="", max_length=256)
    provider: str = Field(min_length=1, max_length=128)
    channel: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=128)
    task_kind: TaskKind = "chat"
    owner: str = Field(min_length=1, max_length=128)
    scope: str = Field(default="", max_length=128)
    trace_id: str = Field(default="", max_length=128)
    test_run_id: str = Field(default="", max_length=128)
    started_at: datetime
    finished_at: datetime | None = None
    outcome: AttemptOutcome = "unknown"
    usage_status: QuantityStatus = "unknown"
    input_semantics: InputSemantics = "unknown"
    cache_creation_includes_read: bool | None = None
    raw_usage_schema_version: str = Field(default="unknown", max_length=64)
    quantities: list[UsageQuantity] = Field(default_factory=list)
    source_event_key: str = Field(default="", max_length=256)

    @field_validator("started_at", "finished_at")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _require_aware("attempt 时间", value)

    @model_validator(mode="after")
    def _time_order(self) -> UsageAttempt:
        if self.finished_at is not None and self.finished_at < self.started_at:
            raise ValueError("finished_at 不得早于 started_at")
        return self

    @field_serializer("started_at", "finished_at", when_used="always")
    def _ser_time(self, value: datetime | None) -> str | None:
        return None if value is None else value.isoformat(timespec="milliseconds")


class AttemptCounts(V21BillingBase, BaseModel):
    """次数分记（§1.3）：requested/submitted/succeeded/billed_requests。

    ``billed_requests=None`` = 账单未知（存在未知结局的 attempt）；
    **不得用成功数代替计费次数**。
    """

    requested: int = Field(default=0, ge=0)
    submitted: int = Field(default=0, ge=0)
    succeeded: int = Field(default=0, ge=0)
    billed_requests: int | None = Field(default=None, ge=0)


class AggregatedUsage(V21BillingBase, BaseModel):
    """aggregate_usage 输出行：按 bucket 维度聚合的用量/金额/次数。

    ``amounts`` 按币种分别汇总（§1.2：不同币种分别汇总，换汇展示必须带
    汇率来源与估算标记——本层不做换汇，币种键各自独立）。
    """

    bucket: str = Field(default="total", max_length=64)
    key: str = Field(default="", max_length=256)
    counts: AttemptCounts = Field(default_factory=AttemptCounts)
    metric_totals: dict[str, Decimal] = Field(default_factory=dict)
    amounts: dict[str, Decimal] = Field(default_factory=dict)  # currency → amount
    unpriced_attempts: int = Field(default=0, ge=0)
    unknown_attempts: int = Field(default=0, ge=0)

    @field_serializer("metric_totals", "amounts", when_used="always")
    def _ser_maps(self, value: dict[str, Decimal]) -> dict[str, str]:
        return {k: money_str(v) or "0" for k, v in value.items()}


__all__ = [
    "ALL_METRICS",
    "AMOUNT_EXPONENT",
    "COMPOSITIONS",
    "INPUT_SEMANTICS_VALUES",
    "METRIC_UNITS",
    "NON_TOKEN_METRICS",
    "QUANTITY_STATUSES",
    "TOKEN_METRICS",
    "TOTAL_SOURCES",
    "AggregatedUsage",
    "AttemptCounts",
    "AttemptOutcome",
    "BudgetExceededError",
    "BudgetNotFoundError",
    "ChargeLine",
    "Composition",
    "InputSemantics",
    "PriceComponent",
    "PriceRevision",
    "PriceUnavailableError",
    "QuantityStatus",
    "RoundingMode",
    "Settlement",
    "SettlementImmutableError",
    "SettlementStatus",
    "TaskKind",
    "UnsupportedSemanticsError",
    "UsageAttempt",
    "UsageBillingError",
    "UsageInconsistentError",
    "UsageQuantity",
    "UsageQuote",
    "UsageSnapshot",
    "V21BillingBase",
    "amount_to_micros",
    "micros_to_amount",
    "money_str",
    "parse_decimal",
    "quantize_amount",
]
