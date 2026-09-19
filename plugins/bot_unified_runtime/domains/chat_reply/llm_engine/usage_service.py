"""Usage/Billing Service 核心语义（后端 V2.1 W5 席 / S5，离线层）。

合同：``docs/design/backend-v2-product-extensions.md`` §1 全节（数据模型/
算法/算例/预算与接口）。复用既有 ``llm/ledger.py`` 账本，不建平行账本；
本模块只做语义层：归一化、定价、报价、结算、预算预留、聚合与
UsageAttempt ←→ 账本行双向映射（不迁移表、不改写历史）。

核心正确性红线（§1.1/§1.2）：
- 金额一律 :class:`~decimal.Decimal`，出参字符串化，**禁浮点金额**；
- inclusive 语义下 ``ordinary_input = input − cache_create − cache_read``，
  差值负数抛 ``usage_inconsistent``，**禁止 max(0) 掩盖异常**；
- 缓存 Token 是输入子集，不得二次累计进 total；Token 总数优先 provider
  报告，只有适配器确认各项集合不重叠时才推导；
- 缺缓存用量只能报价区间或 partial；缺缓存价格不得默认等于普通价，
  除非价格规则显式声明（``cache_price_follows_input``）；
- 不支持的语义组合（如 inclusive 且缓存已知非零且 includes_read 非 False）
  拒绝自动结算；
- 免费但实际已知为 0 与未知严格区分（``measured(0)`` ≠ ``unknown``）；
  只有服务真实报告 Token 才填 Token，否则 not_applicable / unknown，
  不得按字符伪造精确 Token；
- channel 被 AxonHub 隐藏时保存 ``unknown``，不拿模型名冒充渠道；
- 预算通过 SQLite 事务 CAS 扣占，并发不超卖；未登记授权预算不猜充值额；
  取消只标 ``cancel_requested`` 保留可能已产生的费用。

本层不做：REST 路由 / SSE / 价格导入脚本 / 真实 provider 调用（后续席位）。
"""

from __future__ import annotations

import datetime
import math
import sqlite3
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Any

from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.ledger import (
    LLMCallDraft,
)

# ==================== 常量与错误 ====================

# 计量（§1.1 UsageQuantity.metric 枚举）。
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
ALL_METRICS: tuple[str, ...] = TOKEN_METRICS + NON_TOKEN_METRICS

# usage_status 四态（§1.1）：免费但实际已知为 0 与未知区分。
QUANTITY_STATUSES: tuple[str, ...] = (
    "measured",
    "estimated",
    "unknown",
    "not_applicable",
)

# 输入语义与缓存包含关系（§1.1：必须记录的字段）。
INPUT_SEMANTICS_VALUES: tuple[str, ...] = (
    "inclusive_cache",
    "exclusive_cache",
    "unknown",
)

# 计费组成（§1.2）：按次费是否叠加 Token 费由价格规则决定。
COMPOSITIONS: tuple[str, ...] = ("additive", "exclusive", "tiered")

# Settlement 状态（§1.1：reserved/estimated/settled/partial/unknown/refunded）。
SETTLEMENT_STATUSES: tuple[str, ...] = (
    "reserved",
    "estimated",
    "settled",
    "partial",
    "unknown",
    "refunded",
)

# channel 缺失时的诚实占位：不拿模型名冒充渠道（§1.1）。
CHANNEL_UNKNOWN = "unknown"

# 各计量默认单位；金额出参一律十进制字符串。
_METRIC_UNITS: dict[str, str] = {
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

# 非 Token 任务族：Token 数量对这类任务天然不适用（provider 不报 Token），
# 未报告时标 not_applicable 而不是 unknown（§1.1：不得按字符伪造精确 Token）。
_NON_TOKEN_TASK_KINDS: dict[str, tuple[str, ...]] = {
    "tts": ("characters", "audio_seconds", "requests"),
    "image": ("images", "requests"),
    "image_generation": ("images", "requests"),
    "asr": ("audio_seconds", "requests"),
}

# 金额量化精度：微额精度保留到 1e-12 元（确定性算例远在其上）。
_MONEY_QUANT = Decimal("0.000000000001")
# 预算账本内部定点单位：微元（1e-6 元），SQLite 侧纯整数 CAS。
_MICROS = Decimal(1_000_000)

# 原始用量键别名 → 归一计量。
_DEFAULT_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "input_tokens": ("prompt_tokens",),
    "output_tokens": ("completion_tokens",),
    "cache_create_tokens": ("cache_creation_tokens", "cache_write_tokens"),
    "cache_read_tokens": ("cached_tokens",),
}

# 只允许缓存两类计量做「缓存价=普通输入价」的显式回退，绝不波及 output 等。
_CACHE_FALLBACK_METRICS = ("cache_create_tokens", "cache_read_tokens")


class UsageBillingError(Exception):
    """计费语义层错误基类：携带集中注册错误码（§10）。"""

    code = "usage_billing_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class UsageInconsistentError(UsageBillingError):
    """``usage_inconsistent``（502）：用量数据语义不一致（差值负数、负数/NaN 等）。"""

    code = "usage_inconsistent"


class UnsupportedSemanticsError(UsageInconsistentError):
    """不支持的语义/组成组合：拒绝自动结算（§1.1），不放行也不掩盖。"""


class PriceUnavailableError(UsageBillingError):
    """``price_unavailable``（503）：价格缺失且无已授权保守上限（§1.3）。"""

    code = "price_unavailable"


class SettlementImmutableError(UsageBillingError):
    """历史结算不可覆盖（§1.1 Settlement）。"""

    code = "settlement_immutable"


class ReservationNotFoundError(UsageBillingError):
    """预算预留单不存在或状态不允许该操作。"""

    code = "reservation_not_found"


# ==================== 基础换算 ====================


def _to_decimal(value: object, *, what: str) -> Decimal:
    """任意标量 → 精确 Decimal；bool/NaN/inf/负数/非数值一律拒绝。"""
    if isinstance(value, bool):
        raise UsageInconsistentError(f"{what}: 布尔不是合法数值")
    if isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, int):
        parsed = Decimal(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise UsageInconsistentError(f"{what}: 非有限浮点（NaN/inf）")
        parsed = Decimal(str(value))
    elif isinstance(value, str):
        try:
            parsed = Decimal(value.strip())
        except (ArithmeticError, ValueError) as exc:
            raise UsageInconsistentError(f"{what}: 无法解析为数值") from exc
    else:
        raise UsageInconsistentError(f"{what}: 不支持的数值类型 {type(value)!r}")
    if not parsed.is_finite():
        raise UsageInconsistentError(f"{what}: 数值非有限")
    if parsed < 0:
        raise UsageInconsistentError(f"{what}: 数值为负")
    return parsed


def _quantity_value(metric: str, value: object) -> int | Decimal:
    """原始用量值 → 精确数量：整数量收 int，其余 Decimal（provider 数据语义校验）。"""
    parsed = _to_decimal(value, what=f"usage[{metric}]")
    if parsed == parsed.to_integral_value():
        return int(parsed)
    return parsed


def _money(amount: Decimal) -> Decimal:
    """金额统一量化：1e-12 元、half-up，保证合计确定性。"""
    return amount.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)


def _as_decimal(value: Decimal | str) -> Decimal:
    """``__post_init__`` 归一后的字段类型层面仍是 ``Decimal | str``：统一收窄。"""
    return value if isinstance(value, Decimal) else Decimal(value)


def _plain(amount: Decimal) -> str:
    """金额 → 无尾零十进制字符串（科学计数法兜底转定点，禁浮点）。"""
    normalized = amount.normalize()
    exponent = normalized.as_tuple().exponent
    if isinstance(exponent, int) and exponent > 0:
        normalized = normalized.quantize(Decimal(1))
    return str(normalized)


def money_str(amount: Decimal | None) -> str | None:
    """金额出参字符串化（十进制字符串，禁浮点）；None 透传（未知不是 0）。"""
    return None if amount is None else _plain(_money(amount))


def _to_micros(amount: Decimal, *, what: str) -> int:
    """预算金额 → 微元整数；向上取整（预留从紧，防舍入超卖）。"""
    parsed = _to_decimal(amount, what=what)
    return int((parsed * _MICROS).quantize(Decimal(1), rounding=ROUND_CEILING))


def _from_micros(micros: int) -> Decimal:
    return Decimal(micros) / _MICROS


def _parse_instant(value: object, *, what: str) -> datetime.datetime:
    """datetime 或 ISO 字符串 → aware datetime（naive 拒绝，避免时区歧义）。"""
    if isinstance(value, datetime.datetime):
        if value.tzinfo is None:
            raise UsageBillingError(f"{what}: naive datetime 缺时区")
        return value
    if isinstance(value, str) and value:
        parsed = datetime.datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise UsageBillingError(f"{what}: ISO 时间缺时区偏移")
        return parsed
    raise UsageBillingError(f"{what}: 无法解析为时间点")


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# ==================== 数据结构 ====================


@dataclass(frozen=True)
class UsageQuantity:
    """单项用量（§1.1）：value 为有限非负数或 None；status 四态。

    结构性非法值（负数/NaN/inf/布尔）抛 ``ValueError``——构造即程序员错误；
    provider 原始数据的语义校验走 :func:`normalize_usage`（usage_inconsistent）。
    """

    metric: str
    value: int | Decimal | None = None
    unit: str = ""
    status: str = "unknown"
    source: str = ""
    tier: str = ""  # 缓存价格档（如 5m/1h），provider 真实档位。

    def __post_init__(self) -> None:
        if self.metric not in ALL_METRICS:
            raise ValueError(f"未知计量 {self.metric!r}")
        if self.status not in QUANTITY_STATUSES:
            raise ValueError(f"非法 usage_status {self.status!r}")
        if self.value is None:
            if self.status in ("measured", "estimated"):
                raise ValueError("value=None 时 status 不得为 measured/estimated")
            return
        if self.status == "not_applicable":
            raise ValueError("value 有值时 status 不得为 not_applicable")
        if isinstance(self.value, bool) or not isinstance(
            self.value, (int, float, Decimal)
        ):
            raise TypeError(f"usage[{self.metric}]: 不支持的数值类型")
        num = (
            self.value
            if isinstance(self.value, Decimal)
            else Decimal(str(self.value))
        )
        if not num.is_finite() or num < 0:
            raise ValueError(f"usage[{self.metric}]: 必须是有限非负数")
        canonical: int | Decimal = (
            int(num) if num == num.to_integral_value() else num
        )
        object.__setattr__(self, "value", canonical)
        if not self.unit:
            object.__setattr__(self, "unit", _METRIC_UNITS[self.metric])


@dataclass(frozen=True)
class UsageSnapshot:
    """归一化用量快照：全计量覆盖 + 输入语义登记（§1.1）。"""

    quantities: Mapping[str, UsageQuantity]
    input_semantics: str = "unknown"
    cache_creation_includes_read: bool | str = "unknown"
    raw_schema_version: str = "v1"
    provider_schema_version: str = ""
    task_kind: str = ""

    def __post_init__(self) -> None:
        if self.input_semantics not in INPUT_SEMANTICS_VALUES:
            raise ValueError(f"非法 input_semantics {self.input_semantics!r}")
        if self.cache_creation_includes_read not in (True, False, "unknown"):
            raise ValueError(
                "cache_creation_includes_read 只允许 True/False/'unknown'"
            )

    def quantity(self, metric: str) -> UsageQuantity:
        """取计量；缺项返回 unknown（不得冒充 0）。"""
        found = self.quantities.get(metric)
        if found is not None:
            return found
        return UsageQuantity(metric, None, status="unknown")


@dataclass(frozen=True)
class PriceComponent:
    """单计量价格项：单价（每 denominator 个计量单位）+ 分母。"""

    metric: str
    unit_price: Decimal | str
    denominator: int = 1
    cache_tier: str = ""

    def __post_init__(self) -> None:
        if self.metric not in ALL_METRICS:
            raise ValueError(f"未知计量 {self.metric!r}")
        object.__setattr__(
            self,
            "unit_price",
            _to_decimal(self.unit_price, what=f"price[{self.metric}]"),
        )
        if int(self.denominator) < 1:
            raise ValueError(f"price[{self.metric}]: 分母必须 ≥1")
        object.__setattr__(self, "denominator", int(self.denominator))

    @property
    def price(self) -> Decimal:
        return self.unit_price  # type: ignore[return-value]


@dataclass(frozen=True)
class PriceRevision:
    """价格版本（§1.1 PriceRevision）：生效窗口 + 币种 + 计量分母 + 计费组成。

    - ``effective_to=None`` 表示开口（至今有效）；窗口为 ``from ≤ t < to``（to 开区间）；
    - ``cache_price_follows_input=True`` 是「缓存价=普通输入价」的**显式**声明，
      缺省 False——缺缓存价格绝不默认回退普通价（§1.2）；
    - ``tax_included`` 显式记录税费/折扣语义（最终 provider 账单优先）。
    """

    price_id: str
    version: str
    provider: str
    channel: str
    model: str
    currency: str
    effective_from: datetime.datetime | str
    effective_to: datetime.datetime | str | None = None
    rates: Mapping[str, PriceComponent] = field(default_factory=dict)
    composition: str = "additive"
    per_request_price: Decimal | str | None = None
    token_denominator: int = 1_000_000
    rounding: str = "half_up_12dp"
    cache_price_follows_input: bool = False
    tax_included: bool | None = None
    adapter_version: str = ""
    source: str = ""
    approved_by: str = ""

    def __post_init__(self) -> None:
        if self.composition not in COMPOSITIONS:
            raise ValueError(f"非法 composition {self.composition!r}")
        object.__setattr__(
            self,
            "effective_from",
            _parse_instant(self.effective_from, what="effective_from"),
        )
        if self.effective_to is not None:
            object.__setattr__(
                self,
                "effective_to",
                _parse_instant(self.effective_to, what="effective_to"),
            )
        if self.per_request_price is not None:
            object.__setattr__(
                self,
                "per_request_price",
                _to_decimal(self.per_request_price, what="per_request_price"),
            )
        for component in self.rates.values():
            if not isinstance(component, PriceComponent):  # 防呆：拒绝裸数值。
                raise TypeError("rates 值必须是 PriceComponent")

    def component(self, metric: str, tier: str = "") -> PriceComponent | None:
        """取计量价格：优先命中缓存档，回退无档基础价。"""
        found = self.rates.get(metric)
        if found is None:
            return None
        if tier and found.cache_tier != tier:
            tiered = next(
                (
                    c
                    for c in self.rates.values()
                    if c.metric == metric and c.cache_tier == tier
                ),
                None,
            )
            if tiered is not None:
                return tiered
        return found

    def denominator_for(self, metric: str) -> int:
        found = self.rates.get(metric)
        if found is not None:
            return found.denominator
        return int(self.token_denominator) if metric in TOKEN_METRICS else 1


@dataclass(frozen=True)
class ChargeLine:
    """费用行（§1.1 ChargeLine）：单价/金额一律 Decimal，出参字符串化。"""

    line_id: str
    metric: str
    quantity: int | Decimal | None
    unit: str
    unit_price: str | None
    denominator: int
    price_revision: str
    amount: str | None
    currency: str
    status: str  # known / unknown / not_applicable
    billing_group: str = "default"
    cache_tier: str = ""


@dataclass(frozen=True)
class UsageQuote:
    """报价结果：``final`` = 可自动结算；``partial`` = total 未知（只报已知部分）。

    - ``total_amount``：仅在 final 时给出最终总价；partial 恒为 None
      （绝不能展示「最终总价 0.00245」式伪造）；
    - ``known_amount``：已知费用行合计（partial 时与未知项分开列示）；
    - ``amount_lower_bound/upper_bound``：缺缓存用量时的报价区间（§1.2）。
    """

    lines: tuple[ChargeLine, ...]
    currency: str
    status: str  # final / partial
    known_amount: Decimal | None
    total_amount: Decimal | None
    unknown_items: tuple[str, ...] = ()
    amount_lower_bound: Decimal | None = None
    amount_upper_bound: Decimal | None = None


@dataclass
class Settlement:
    """结算（§1.1 Settlement）：已知金额 + 未知项；历史结算不可覆盖。"""

    attempt_id: str
    status: str
    currency: str
    known_amount: str | None
    total_amount: str | None
    lines: tuple[ChargeLine, ...] = ()
    unknown_items: tuple[str, ...] = ()
    created_at: str = ""

    def __post_init__(self) -> None:
        if self.status not in SETTLEMENT_STATUSES:
            raise ValueError(f"非法 settlement status {self.status!r}")
        if not self.created_at:
            self.created_at = _now_iso()


@dataclass
class UsageAttempt:
    """一次 provider 尝试（§1.1 UsageAttempt）+ 快照/结算挂载。"""

    operation_id: str
    attempt_id: str
    provider_request_id: str = ""
    provider: str = ""
    channel: str = ""
    model: str = ""
    task_kind: str = ""
    owner: str = ""
    scope: str = ""
    trace_id: str = ""
    started_at: str = ""
    finished_at: str = ""
    outcome: str = ""
    usage_status: str = "unknown"
    raw_usage_schema_version: str = "v1"
    snapshot: UsageSnapshot | None = None
    settlement: Settlement | None = None
    price_version: str = ""
    legacy_cost_milli: Mapping[str, int | None] = field(default_factory=dict)


# ==================== normalize_usage ====================


def normalize_usage(
    provider_schema: Mapping[str, Any] | None,
    raw: Mapping[str, Any] | None,
) -> UsageSnapshot:
    """provider 原始用量 → 归一化快照（§1.2 接口 1）。

    - 别名键归一：prompt_tokens→input_tokens、completion_tokens→output_tokens、
      cache_write_tokens/cache_creation_tokens→cache_create_tokens、
      cached_tokens→cache_read_tokens；
    - Token 总数优先 provider 报告（source=provider_reported）；只有适配器
      确认各项集合不重叠（``components_disjoint=True``）且输入/输出均已测得
      时才推导 total（source=derived_sum）；缓存 Token 绝不二次累计；
    - 非 Token 任务族（tts/image/asr）未报告 Token → not_applicable；
      其余未报告 → unknown；
    - 负数/NaN/inf/布尔等非法原值 → ``usage_inconsistent``。
    """
    schema = dict(provider_schema or {})
    raw_map = dict(raw or {})
    semantics = str(schema.get("input_semantics", "unknown"))
    if semantics not in INPUT_SEMANTICS_VALUES:
        raise ValueError(f"非法 input_semantics {semantics!r}")
    includes_read = schema.get("cache_creation_includes_read", "unknown")
    if includes_read not in (True, False, "unknown"):
        raise ValueError("cache_creation_includes_read 只允许 True/False/'unknown'")
    task_kind = str(schema.get("task_kind", "") or "")
    aliases: Mapping[str, tuple[str, ...]] = (
        schema.get("key_aliases") or _DEFAULT_KEY_ALIASES
    )

    quantities: dict[str, UsageQuantity] = {}
    relevant = _NON_TOKEN_TASK_KINDS.get(task_kind)
    for metric in ALL_METRICS:
        value = raw_map.get(metric)
        if value is None:
            for alias in aliases.get(metric, ()):  # 归一别名键。
                if raw_map.get(alias) is not None:
                    value = raw_map[alias]
                    break
        if value is not None:
            quantities[metric] = UsageQuantity(
                metric,
                _quantity_value(metric, value),
                status="measured",
                source="provider_reported",
                tier=str(raw_map.get("_cache_tier", "") or ""),
            )
            continue
        # 未报告：按任务族判定 not_applicable / unknown。
        if metric in TOKEN_METRICS and relevant is not None or (
            metric in NON_TOKEN_METRICS
            and relevant is not None
            and metric not in relevant
        ):
            quantities[metric] = UsageQuantity(metric, None, status="not_applicable")
        else:
            quantities[metric] = UsageQuantity(metric, None, status="unknown")

    # total 推导：优先 provider 报告；只在适配器确认互斥时推导 input+output
    # （缓存 Token 是输入子集，绝不二次累计——total=1100 而不是 1400）。
    if quantities["total_tokens"].value is None:
        q_in = quantities["input_tokens"]
        q_out = quantities["output_tokens"]
        if (
            schema.get("components_disjoint") is True
            and q_in.value is not None
            and q_out.value is not None
        ):
            quantities["total_tokens"] = UsageQuantity(
                "total_tokens",
                int(q_in.value) + int(q_out.value),
                status="measured",
                source="derived_sum",
            )

    return UsageSnapshot(
        quantities=quantities,
        input_semantics=semantics,
        cache_creation_includes_read=includes_read,  # type: ignore[arg-type]
        raw_schema_version=str(schema.get("raw_schema_version", "v1")),
        provider_schema_version=str(schema.get("provider_schema_version", "")),
        task_kind=task_kind,
    )


def normalize_channel(observed: str, *, model: str = "") -> str:
    """渠道归一：被 AxonHub 隐藏（空）时保存 unknown，不拿模型名冒充渠道。"""
    text = str(observed or "").strip()
    if text:
        return text
    return CHANNEL_UNKNOWN


# ==================== resolve_price ====================


def resolve_price(
    prices: Iterable[PriceRevision],
    attempt_started_at: datetime.datetime | str,
    route: tuple[str, str, str] | Mapping[str, str],
) -> PriceRevision | None:
    """按生效窗口与路由解析价格版本（§1.2 接口 2）；无命中返回 None。

    - 路由三元组 ``(provider, channel, model)``；价格侧空字符串视为通配；
    - 命中多条时：更具体（非通配字段多）优先，同具体度取 ``effective_from`` 最新；
    - 生效窗口 ``from ≤ t < to``（to 开区间，跨生效边界确定性）。
    """
    at = _parse_instant(attempt_started_at, what="attempt_started_at")
    if isinstance(route, Mapping):
        triple = (
            str(route.get("provider", "")),
            str(route.get("channel", "")),
            str(route.get("model", "")),
        )
    else:
        parts = tuple(str(part) for part in route)
        if len(parts) != 3:
            raise ValueError("route 必须是 (provider, channel, model) 三元组")
        triple = parts
    best: tuple[int, datetime.datetime, PriceRevision] | None = None
    for revision in prices:
        if revision.provider not in ("", triple[0]):
            continue
        if revision.channel not in ("", triple[1]):
            continue
        if revision.model not in ("", triple[2]):
            continue
        if revision.effective_from > at:  # type: ignore[operator]
            continue
        if revision.effective_to is not None and at >= revision.effective_to:  # type: ignore[operator]
            continue
        specificity = sum(
            1 for f in (revision.provider, revision.channel, revision.model) if f
        )
        key = (specificity, revision.effective_from)  # type: ignore[assignment]
        if best is None or key > (best[0], best[1]):
            best = (specificity, revision.effective_from, revision)  # type: ignore[assignment]
    if best is None:
        return None
    return best[2]


# ==================== quote_usage ====================


def quote_usage(
    snapshot: UsageSnapshot, price: PriceRevision | None
) -> UsageQuote:
    """用量 × 价格 → 报价（§1.2 算法）。金额 Decimal，total 仅在 final 时给出。

    inclusive（且 includes_read=False）：
        ``ordinary_input = input − cache_create − cache_read``，负数抛
        ``usage_inconsistent``；exclusive：``ordinary_input = input``。
    缓存用量缺失 → 区间 + partial；缓存价格缺失 → 已知行与未知行分开 + partial
    （除非价格规则显式 ``cache_price_follows_input``）。
    """
    if price is None:
        raise PriceUnavailableError("价格缺失且无保守上限，无法报价")
    if price.composition == "tiered":
        raise UnsupportedSemanticsError(
            "tiered 计费组成暂不支持自动结算（离线层 v1）"
        )

    if price.composition == "exclusive":
        # exclusive 请求套餐：请求费已涵盖用量（金额仅请求费，§1.2 算例 2）。
        if price.per_request_price is None:
            raise PriceUnavailableError("exclusive 组成缺按次价格，无法报价")
        amount = _money(_as_decimal(price.per_request_price))
        line = ChargeLine(
            line_id="requests",
            metric="requests",
            quantity=1,
            unit=_METRIC_UNITS["requests"],
            unit_price=_plain(_as_decimal(price.per_request_price)),
            denominator=1,
            price_revision=price.version,
            amount=_plain(amount),
            currency=price.currency,
            status="known",
            billing_group="request_plan",
        )
        return UsageQuote(
            lines=(line,),
            currency=price.currency,
            status="final",
            known_amount=amount,
            total_amount=amount,
        )

    # ---- additive：逐计量行叠加 ----
    q_in = snapshot.quantity("input_tokens")
    q_out = snapshot.quantity("output_tokens")
    q_create = snapshot.quantity("cache_create_tokens")
    q_read = snapshot.quantity("cache_read_tokens")
    semantics = snapshot.input_semantics
    includes_read = snapshot.cache_creation_includes_read

    cache_known_all = q_create.value is not None and q_read.value is not None
    cache_all_zero = (
        cache_known_all and int(q_create.value) == 0 and int(q_read.value) == 0  # type: ignore[arg-type]
    )

    # 不支持组合拒绝自动结算（§1.1）：inclusive 且缓存已知非零而
    # includes_read 非 False（读取量可能与创建量交叠、读取价归属不明）；
    # 语义 unknown 且缓存已知非零（输入口径不明）。
    refuse = (
        (semantics == "inclusive_cache" and includes_read in (True, "unknown"))
        or semantics == "unknown"
    ) and cache_known_all and not cache_all_zero
    if refuse:
        raise UnsupportedSemanticsError(
            f"input_semantics={semantics} 且 cache_creation_includes_read="
            f"{includes_read!r} 的组合拒绝自动结算（缓存交叠风险）"
        )

    token_section_active = any(
        q.status != "not_applicable" for q in (q_in, q_out, q_create, q_read)
    )

    lines: list[ChargeLine] = []
    unknown_items: list[str] = []

    def _add_known(
        metric: str,
        qty: int | Decimal,
        component: PriceComponent,
        *,
        tier: str = "",
        billing_group: str = "default",
    ) -> None:
        amount = _money(Decimal(qty) * component.price / Decimal(component.denominator))
        lines.append(
            ChargeLine(
                line_id=metric if not tier else f"{metric}@{tier}",
                metric=metric,
                quantity=qty,
                unit=_METRIC_UNITS[metric],
                unit_price=_plain(component.price),
                denominator=component.denominator,
                price_revision=price.version,
                amount=_plain(amount),
                currency=price.currency,
                status="known",
                billing_group=billing_group,
                cache_tier=component.cache_tier,
            )
        )

    def _add_unknown(metric: str, qty: int | Decimal, *, tier: str = "") -> None:
        # 缺价：未知行 + partial，绝不默认回退普通价（§1.2）。
        lines.append(
            ChargeLine(
                line_id=metric,
                metric=metric,
                quantity=qty,
                unit=_METRIC_UNITS[metric],
                unit_price=None,
                denominator=price.denominator_for(metric),
                price_revision=price.version,
                amount=None,
                currency=price.currency,
                status="unknown",
                cache_tier=tier,
            )
        )
        unknown_items.append(metric)

    def _price_line(metric: str, qty: int | Decimal, *, tier: str = "") -> None:
        component = price.component(metric, tier)
        if (
            component is None
            and metric in _CACHE_FALLBACK_METRICS
            and price.cache_price_follows_input
        ):
            # 显式声明的缓存价回退：只允许缓存两类计量，绝不波及其他。
            component = price.component("input_tokens")
        if component is None:
            _add_unknown(metric, qty, tier=tier)
        else:
            _add_known(metric, qty, component, tier=tier)

    ordinary_known = False
    ordinary = 0
    cache_usage_missing = False
    if token_section_active and q_in.value is not None:
        if semantics == "inclusive_cache":
            if cache_known_all:
                ordinary = int(q_in.value) - int(q_create.value) - int(q_read.value)  # type: ignore[arg-type]
                if ordinary < 0:
                    # 差值负数必须报 usage_inconsistent，禁 max(0) 掩盖（§1.2）。
                    raise UsageInconsistentError(
                        "usage_inconsistent: ordinary_input = input − cache_create"
                        f" − cache_read = {ordinary} < 0"
                    )
                ordinary_known = True
            else:
                cache_usage_missing = True  # 缓存用量缺失 → 区间/partial。
        elif semantics == "exclusive_cache":
            ordinary = int(q_in.value)  # exclusive：ordinary=input。
            ordinary_known = True
        else:  # unknown 且缓存全零（非零已在拒绝段拦下）→ 按无缓存处理。
            ordinary = int(q_in.value)
            ordinary_known = True

    if ordinary_known:
        _price_line("input_tokens", ordinary)
        if q_create.value is not None and int(q_create.value) > 0:
            _price_line("cache_create_tokens", q_create.value, tier=q_create.tier)  # type: ignore[arg-type]
        if q_read.value is not None and int(q_read.value) > 0:
            _price_line("cache_read_tokens", q_read.value, tier=q_read.tier)  # type: ignore[arg-type]
    if cache_usage_missing:
        unknown_items.append("cache_usage_missing")
    if token_section_active and q_out.value is not None:
        _price_line("output_tokens", q_out.value)
    elif token_section_active and q_out.value is None:
        unknown_items.append("output_tokens")

    # 非 Token 计量（TTS 字符 / 音频秒 / 图片张数）：只有真实报告才计价。
    for metric in ("characters", "audio_seconds", "images"):
        q = snapshot.quantity(metric)
        if q.value is not None:
            _price_line(metric, q.value)

    # 按次费（additive = 与用量费叠加）：请求次数真实报告优先，缺省按 1 次/attempt。
    if price.per_request_price is not None:
        q_req = snapshot.quantity("requests")
        count = int(q_req.value) if q_req.value is not None else 1
        amount = _money(Decimal(count) * _as_decimal(price.per_request_price))
        lines.append(
            ChargeLine(
                line_id="requests",
                metric="requests",
                quantity=count,
                unit=_METRIC_UNITS["requests"],
                unit_price=_plain(_as_decimal(price.per_request_price)),
                denominator=1,
                price_revision=price.version,
                amount=_plain(amount),
                currency=price.currency,
                status="known",
                billing_group="per_request",
            )
        )

    known_lines = [ln for ln in lines if ln.status == "known"]
    known_amount: Decimal | None = None
    known_amounts = [Decimal(ln.amount) for ln in known_lines if ln.amount is not None]
    if known_amounts:
        known_amount = _money(sum(known_amounts, Decimal(0)))

    if not unknown_items:
        return UsageQuote(
            lines=tuple(lines),
            currency=price.currency,
            status="final",
            known_amount=known_amount,
            total_amount=known_amount,
        )

    # partial：绝不伪造最终总价；缺缓存用量时给报价区间（下界=已知行，
    # 上界=整段输入按可用最高缓存/输入单价计，保守）。
    lower: Decimal | None = None
    upper: Decimal | None = None
    if cache_usage_missing and q_in.value is not None:
        input_side_rates = [
            c.price
            for m in ("input_tokens", "cache_create_tokens", "cache_read_tokens")
            if (c := price.component(m)) is not None
        ]
        base = known_amount if known_amount is not None else Decimal(0)
        lower = _money(base)
        upper = lower
        if input_side_rates:
            upper = _money(
                base
                + Decimal(int(q_in.value))
                * max(input_side_rates)
                / Decimal(price.denominator_for("input_tokens"))
            )
    return UsageQuote(
        lines=tuple(lines),
        currency=price.currency,
        status="partial",
        known_amount=known_amount,
        total_amount=None,
        unknown_items=tuple(dict.fromkeys(unknown_items)),
        amount_lower_bound=lower,
        amount_upper_bound=upper,
    )


# ==================== settle_attempt ====================


def settle_attempt(
    attempt: UsageAttempt,
    *,
    price: PriceRevision | None = None,
    snapshot: UsageSnapshot | None = None,
    conservative_upper_bound: Decimal | str | None = None,
) -> Settlement:
    """attempt 级结算（§1.2 接口）：报价 → ChargeLine + Settlement 挂载。

    - 已有结算的 attempt 拒绝重算（不可覆盖历史结算）；
    - 价格缺失且无保守上限 → ``price_unavailable``（不以 unknown 绕过预算）；
    - 有已授权保守上限 → ``estimated`` 结算；
    - ``usage_status``：全部相关计量已测 = measured；全未知 = unknown；其余 estimated。
    """
    if attempt.settlement is not None:
        raise SettlementImmutableError(
            f"attempt {attempt.attempt_id} 已有结算"
            f"（{attempt.settlement.status}），不可覆盖"
        )
    snap = snapshot if snapshot is not None else attempt.snapshot
    if snap is None:
        settlement = Settlement(
            attempt_id=attempt.attempt_id,
            status="unknown",
            currency="",
            known_amount=None,
            total_amount=None,
            unknown_items=("usage_missing",),
        )
        attempt.usage_status = "unknown"
        attempt.settlement = settlement
        return settlement

    if price is None:
        if conservative_upper_bound is None:
            raise PriceUnavailableError(
                "price_unavailable: 价格缺失且无已授权保守上限，付费任务拒绝受理"
            )
        bound = _money(
            _to_decimal(conservative_upper_bound, what="conservative_upper_bound")
        )
        settlement = Settlement(
            attempt_id=attempt.attempt_id,
            status="estimated",
            currency="",
            known_amount=money_str(bound),
            total_amount=money_str(bound),
            unknown_items=("price_revision_missing",),
        )
        if attempt.usage_status == "unknown":
            attempt.usage_status = "estimated"
        attempt.settlement = settlement
        return settlement

    quote = quote_usage(snap, price)
    lines = tuple(
        ChargeLine(
            line_id=f"{attempt.attempt_id}:{index + 1}:{ln.metric}",
            metric=ln.metric,
            quantity=ln.quantity,
            unit=ln.unit,
            unit_price=ln.unit_price,
            denominator=ln.denominator,
            price_revision=ln.price_revision,
            amount=ln.amount,
            currency=ln.currency,
            status=ln.status,
            billing_group=ln.billing_group,
            cache_tier=ln.cache_tier,
        )
        for index, ln in enumerate(quote.lines)
    )
    status = "settled" if quote.status == "final" else "partial"
    settlement = Settlement(
        attempt_id=attempt.attempt_id,
        status=status,
        currency=quote.currency,
        known_amount=money_str(quote.known_amount),
        total_amount=money_str(quote.total_amount),
        lines=lines,
        unknown_items=tuple(quote.unknown_items),
    )
    attempt.usage_status = _derive_usage_status(snap)
    attempt.settlement = settlement
    attempt.price_version = price.version
    return settlement


def _derive_usage_status(snapshot: UsageSnapshot) -> str:
    """按任务相关计量推导 usage_status（非相关族 not_applicable 不拖累）。"""
    relevant: tuple[str, ...] = _NON_TOKEN_TASK_KINDS.get(
        snapshot.task_kind, TOKEN_METRICS
    )
    statuses = [snapshot.quantity(metric).status for metric in relevant]
    measured = sum(1 for s in statuses if s in ("measured", "estimated"))
    if measured == 0:
        return "unknown"
    if all(s in ("measured", "estimated", "not_applicable") for s in statuses):
        return "measured"
    return "estimated"


# ==================== 预算预留（SQLite 事务 CAS） ====================

_BUDGET_SCHEMA_SQL = (
    """
    CREATE TABLE IF NOT EXISTS budget_accounts (
        scope TEXT NOT NULL,
        currency TEXT NOT NULL,
        limit_amount_micros INTEGER NOT NULL,
        reserved_amount_micros INTEGER NOT NULL DEFAULT 0,
        spent_amount_micros INTEGER NOT NULL DEFAULT 0,
        version INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (scope, currency)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS budget_reservations (
        reservation_id TEXT PRIMARY KEY,
        scope TEXT NOT NULL,
        currency TEXT NOT NULL,
        amount_micros INTEGER NOT NULL,
        state TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    ("CREATE INDEX IF NOT EXISTS idx_budget_res_scope"
     " ON budget_reservations (scope, currency)"),
)


@dataclass(frozen=True)
class ReservationResult:
    """预留结果：granted=False 时 reason ∈ budget_exceeded / budget_not_registered。"""

    granted: bool
    reservation_id: str
    reason: str
    remaining: Decimal
    state: str = ""


def _budget_connection(db_path: str) -> sqlite3.Connection:
    import pathlib

    parent = pathlib.Path(db_path).parent
    parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=15.0, isolation_level=None)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=15000")
    return connection


def _ensure_budget_schema(connection: sqlite3.Connection) -> None:
    for statement in _BUDGET_SCHEMA_SQL:
        connection.execute(statement)


def register_budget(
    db_path: str, scope: str, currency: str, limit_amount: Decimal | str
) -> None:
    """登记授权预算上限（§1.3：初始金额由授权包提供，不猜充值额）。幂等覆盖。"""
    micros = _to_micros(Decimal(str(limit_amount)), what="limit_amount")
    connection = _budget_connection(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        _ensure_budget_schema(connection)
        connection.execute(
            """
            INSERT INTO budget_accounts (scope, currency, limit_amount_micros)
            VALUES (?, ?, ?)
            ON CONFLICT (scope, currency) DO UPDATE
            SET limit_amount_micros = excluded.limit_amount_micros,
                version = version + 1
            """,
            (str(scope), str(currency), micros),
        )
        connection.execute("COMMIT")
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def reserve_budget(
    db_path: str,
    scope: str,
    currency: str,
    amount: Decimal | str,
) -> ReservationResult:
    """事务内 CAS 扣占预算：``BEGIN IMMEDIATE`` 串行化写者 + 整数微元算术，
    并发调用不超卖；预算未登记 → 拒绝（不猜充值额，§1.3）。"""
    amount_micros = _to_micros(Decimal(str(amount)), what="reserve amount")
    connection = _budget_connection(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        _ensure_budget_schema(connection)
        row = connection.execute(
            """
            SELECT limit_amount_micros, reserved_amount_micros, spent_amount_micros
            FROM budget_accounts WHERE scope=? AND currency=?
            """,
            (str(scope), str(currency)),
        ).fetchone()
        if row is None:
            connection.execute("ROLLBACK")
            return ReservationResult(False, "", "budget_not_registered", Decimal(0))
        limit_micros, reserved_micros, spent_micros = (int(part) for part in row)
        available = limit_micros - reserved_micros - spent_micros
        if amount_micros > available:
            connection.execute("ROLLBACK")
            return ReservationResult(
                False, "", "budget_exceeded", _from_micros(max(0, available))
            )
        reservation_id = uuid.uuid4().hex
        connection.execute(
            """
            INSERT INTO budget_reservations
                (reservation_id, scope, currency, amount_micros, state, created_at)
            VALUES (?, ?, ?, ?, 'reserved', ?)
            """,
            (reservation_id, str(scope), str(currency), amount_micros, _now_iso()),
        )
        # 条件更新兜底（belt & braces）：guard 不过 = 并发竞争失败 → 回滚。
        cursor = connection.execute(
            """
            UPDATE budget_accounts
            SET reserved_amount_micros = reserved_amount_micros + ?,
                version = version + 1
            WHERE scope=? AND currency=?
              AND reserved_amount_micros + spent_amount_micros + ?
                  <= limit_amount_micros
            """,
            (amount_micros, str(scope), str(currency), amount_micros),
        )
        if cursor.rowcount != 1:
            connection.execute("ROLLBACK")
            return ReservationResult(
                False, "", "budget_exceeded", _from_micros(max(0, available))
            )
        connection.execute("COMMIT")
        return ReservationResult(
            True,
            reservation_id,
            "",
            _from_micros(available - amount_micros),
            state="reserved",
        )
    except BaseException:
        try:
            connection.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        connection.close()


def _reservation_scope_currency(
    connection: sqlite3.Connection, reservation_id: str
) -> tuple[str, str, int]:
    row = connection.execute(
        "SELECT scope, currency, amount_micros FROM budget_reservations"
        " WHERE reservation_id=?",
        (str(reservation_id),),
    ).fetchone()
    if row is None:
        raise ReservationNotFoundError(f"预留单不存在: {reservation_id}")
    return str(row[0]), str(row[1]), int(row[2])


def cancel_reservation(db_path: str, reservation_id: str) -> str:
    """取消只标 ``cancel_requested``，保留占用费用（§1.3：保留可能已产生费用）。"""
    connection = _budget_connection(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        _reservation_scope_currency(connection, reservation_id)
        connection.execute(
            "UPDATE budget_reservations SET state='cancel_requested'"
            " WHERE reservation_id=?",
            (str(reservation_id),),
        )
        connection.execute("COMMIT")
        return "cancel_requested"
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def settle_reservation(
    db_path: str, reservation_id: str, actual_amount: Decimal | str
) -> str:
    """按实际金额结转：占用转支出，差额释放（对账后有据再结算，§1.3）。"""
    actual_micros = _to_micros(Decimal(str(actual_amount)), what="settle amount")
    connection = _budget_connection(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        scope, currency, reserved_part = _reservation_scope_currency(
            connection, reservation_id
        )
        connection.execute(
            "UPDATE budget_reservations SET state='settled' WHERE reservation_id=?",
            (str(reservation_id),),
        )
        connection.execute(
            """
            UPDATE budget_accounts
            SET reserved_amount_micros = MAX(0, reserved_amount_micros - ?),
                spent_amount_micros = spent_amount_micros + ?,
                version = version + 1
            WHERE scope=? AND currency=?
            """,
            (reserved_part, actual_micros, scope, currency),
        )
        connection.execute("COMMIT")
        return "settled"
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def refund_reservation(db_path: str, reservation_id: str) -> str:
    """退款：占用全额释放、不计支出（Settlement.refunded 语义）。"""
    connection = _budget_connection(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        scope, currency, reserved_part = _reservation_scope_currency(
            connection, reservation_id
        )
        connection.execute(
            "UPDATE budget_reservations SET state='refunded' WHERE reservation_id=?",
            (str(reservation_id),),
        )
        connection.execute(
            """
            UPDATE budget_accounts
            SET reserved_amount_micros = MAX(0, reserved_amount_micros - ?),
                version = version + 1
            WHERE scope=? AND currency=?
            """,
            (reserved_part, scope, currency),
        )
        connection.execute("COMMIT")
        return "refunded"
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


# ==================== aggregate_usage ====================


@dataclass(frozen=True)
class UsageFilter:
    """聚合过滤（字段为空 = 不过滤）；时间窗用 started_at 的 ISO 前缀比较。"""

    model: str = ""
    channel: str = ""
    provider: str = ""
    task_kind: str = ""
    owner: str = ""
    outcome: str = ""
    started_from: str = ""
    started_to: str = ""


@dataclass(frozen=True)
class UsageAggregate:
    """聚合行：各币种分别汇总（§1.2），金额出参一律字符串。"""

    key: str
    attempts: int
    billed_attempts: int
    partial_attempts: int
    unknown_attempts: int
    tokens: Mapping[str, int]
    cost_by_currency: Mapping[str, str]


_AGGREGATE_BUCKETS: dict[str, str] = {
    "none": "",
    "day": "day",
    "model": "model",
    "channel": "channel",
    "provider": "provider",
    "task_kind": "task_kind",
    "owner": "owner",
    "outcome": "outcome",
}


def aggregate_usage(
    attempts: Iterable[UsageAttempt],
    *,
    bucket: str = "none",
    flt: UsageFilter | None = None,
) -> dict[str, UsageAggregate]:
    """按桶聚合用量与费用（§1.2 接口）：排行榜合计与同过滤 attempt 账本一致。"""
    if bucket not in _AGGREGATE_BUCKETS:
        raise ValueError(f"非法 bucket {bucket!r}，允许：{sorted(_AGGREGATE_BUCKETS)}")
    flt = flt or UsageFilter()
    groups: dict[str, dict[str, Any]] = {}

    def _bucket_key(attempt: UsageAttempt) -> str:
        if bucket == "none":
            return ""
        if bucket == "day":
            return str(attempt.started_at)[:10]
        return str(getattr(attempt, _AGGREGATE_BUCKETS[bucket]) or "")

    for attempt in attempts:
        if flt.model and attempt.model != flt.model:
            continue
        if flt.channel and attempt.channel != flt.channel:
            continue
        if flt.provider and attempt.provider != flt.provider:
            continue
        if flt.task_kind and attempt.task_kind != flt.task_kind:
            continue
        if flt.owner and attempt.owner != flt.owner:
            continue
        if flt.outcome and attempt.outcome != flt.outcome:
            continue
        if flt.started_from and str(attempt.started_at) < flt.started_from:
            continue
        if flt.started_to and str(attempt.started_at) > flt.started_to:
            continue

        key = _bucket_key(attempt)
        stat = groups.setdefault(
            key,
            {
                "attempts": 0,
                "billed": 0,
                "partial": 0,
                "unknown": 0,
                "tokens": {},
                "cost": {},
            },
        )
        stat["attempts"] += 1
        settlement = attempt.settlement
        if settlement is None or settlement.status == "unknown":
            stat["unknown"] += 1
        else:
            if settlement.known_amount is not None:
                stat["billed"] += 1
                currency = settlement.currency or "unknown_currency"
                stat["cost"][currency] = (
                    stat["cost"].get(currency, Decimal(0))
                    + Decimal(settlement.known_amount)
                )
            if settlement.status == "partial":
                stat["partial"] += 1
        snapshot = attempt.snapshot
        if snapshot is not None:
            for metric in TOKEN_METRICS:
                value = snapshot.quantity(metric).value
                if value is not None:
                    stat["tokens"][metric] = (
                        stat["tokens"].get(metric, 0) + int(value)
                    )

    result: dict[str, UsageAggregate] = {}
    for key in sorted(groups):
        stat = groups[key]
        result[key] = UsageAggregate(
            key=key,
            attempts=int(stat["attempts"]),
            billed_attempts=int(stat["billed"]),
            partial_attempts=int(stat["partial"]),
            unknown_attempts=int(stat["unknown"]),
            tokens=dict(stat["tokens"]),
            cost_by_currency={
                cur: _plain(_money(amount))
                for cur, amount in sorted(stat["cost"].items())
            },
        )
    return result


# ==================== ledger 兼容适配（不迁移表、不改写历史） ====================


def _milli(amount_text: str | None) -> int | None:
    """元字符串 → 毫厘整数（half-up），对齐既有 ``llm_call_records`` cost_milli 口径。"""
    if amount_text is None:
        return None
    value = (Decimal(amount_text) * 1000).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return int(value)


def usage_attempt_to_draft(attempt: UsageAttempt) -> LLMCallDraft:
    """UsageAttempt → 既有账本行草稿（写入侧适配；不迁移表、不改写历史）。

    - cost 桶沿用账本口径：``input_cost_milli`` 含缓存创建费；
    - partial/无结算 → cost 全 NULL + ``unpriced`` 如实标记（未知不是 0）；
    - ``pricing_source='usage_service'`` 标注来源，与 router 的
      ``channel_spec`` 区分。
    """
    snapshot = attempt.snapshot

    def _tokens(metric: str) -> int | None:
        if snapshot is None:
            return None
        value = snapshot.quantity(metric).value
        return None if value is None else int(value)

    settlement = attempt.settlement
    input_cost_milli: int | None = None
    cache_read_cost_milli: int | None = None
    output_cost_milli: int | None = None
    total_cost_milli: int | None = None
    pricing_source = "unknown"
    if settlement is not None and settlement.status in ("settled", "estimated"):
        by_metric: dict[str, Decimal] = {}
        for ln in settlement.lines:
            if ln.status == "known" and ln.amount is not None:
                by_metric[ln.metric] = (
                    by_metric.get(ln.metric, Decimal(0)) + Decimal(ln.amount)
                )
        ordinary = by_metric.get("input_tokens", Decimal(0))
        create = by_metric.get("cache_create_tokens", Decimal(0))
        input_cost_milli = _milli(str(_money(ordinary + create)))
        if "cache_read_tokens" in by_metric:
            cache_read_cost_milli = _milli(str(_money(by_metric["cache_read_tokens"])))
        if "output_tokens" in by_metric:
            output_cost_milli = _milli(str(_money(by_metric["output_tokens"])))
        known = Decimal(settlement.known_amount) if settlement.known_amount else Decimal(0)
        total_cost_milli = _milli(str(_money(known)))
        pricing_source = "usage_service"

    total_tokens = _tokens("total_tokens")
    unpriced = (
        1
        if (total_tokens is not None and total_tokens > 0 and total_cost_milli is None)
        else 0
    )
    call_seq = 1
    tail = attempt.attempt_id.rsplit("#", 1)
    if len(tail) == 2 and tail[1].isdigit():
        call_seq = int(tail[1])

    return LLMCallDraft(
        request_id=str(attempt.operation_id or ""),
        call_seq=call_seq,
        session_id="",  # UsageAttempt 无会话字段：诚实留空，不猜。
        capability=str(attempt.task_kind or ""),
        started_at=str(attempt.started_at or ""),
        completed_at=str(attempt.finished_at or ""),
        provider_id=str(attempt.channel or attempt.provider or ""),
        model_id=str(attempt.channel or attempt.provider or ""),
        actual_model=str(attempt.model or ""),
        routing_group="",
        prompt_tokens=_tokens("input_tokens"),
        cache_creation_tokens=_tokens("cache_create_tokens"),
        cache_read_tokens=_tokens("cache_read_tokens"),
        completion_tokens=_tokens("output_tokens"),
        total_tokens=total_tokens,
        input_cost_milli=input_cost_milli,
        cache_read_cost_milli=cache_read_cost_milli,
        output_cost_milli=output_cost_milli,
        total_cost_milli=total_cost_milli,
        currency=(settlement.currency if settlement is not None else "") or "CNY",
        pricing_source=pricing_source,
        unpriced=unpriced,
        attempts=[attempt.attempt_id],
        status=str(attempt.outcome or "unknown"),
        source="usage_service",
    )


def _snapshot_from_ledger_tokens(
    tokens: Mapping[str, int | None],
) -> UsageSnapshot:
    """历史账本行 → 快照：语义未登记 → 诚实 unknown，绝不臆断 inclusive/exclusive。"""
    mapping: Mapping[str, int | None] = {
        "input_tokens": tokens.get("input"),
        "output_tokens": tokens.get("output"),
        "total_tokens": tokens.get("total"),
        "cache_create_tokens": tokens.get("cache_create"),
        "cache_read_tokens": tokens.get("cache_read"),
    }
    quantities: dict[str, UsageQuantity] = {}
    for metric in ALL_METRICS:
        value = mapping.get(metric)
        if value is None:
            quantities[metric] = UsageQuantity(metric, None, status="unknown")
        else:
            quantities[metric] = UsageQuantity(
                metric, int(value), status="measured", source="ledger_row"
            )
    return UsageSnapshot(
        quantities=quantities,
        input_semantics="unknown",
        cache_creation_includes_read="unknown",
        raw_schema_version="ledger-v1",
    )


def draft_to_usage_attempt(draft: LLMCallDraft) -> UsageAttempt:
    """账本行草稿 → UsageAttempt（读取侧适配；旧 cost_milli 原样保留，
    不凭空恢复被舍入的小数，§1.2）。"""
    tokens = {
        "input": draft.prompt_tokens,
        "output": draft.completion_tokens,
        "total": draft.total_tokens,
        "cache_create": draft.cache_creation_tokens,
        "cache_read": draft.cache_read_tokens,
    }
    snapshot = _snapshot_from_ledger_tokens(tokens)
    measured = any(q.status == "measured" for q in snapshot.quantities.values())
    return UsageAttempt(
        operation_id=str(draft.request_id or ""),
        attempt_id=f"{draft.request_id}#{draft.call_seq}" if draft.request_id else "",
        provider=str(draft.provider_id or ""),
        channel=normalize_channel(draft.provider_id),
        model=str(draft.actual_model or draft.model_id or ""),
        task_kind=str(draft.capability or ""),
        started_at=str(draft.started_at or ""),
        finished_at=str(draft.completed_at or ""),
        outcome=str(draft.status or ""),
        usage_status="measured" if measured else "unknown",
        raw_usage_schema_version=f"ledger-v{int(draft.schema_ver)}",
        snapshot=snapshot,
        legacy_cost_milli={
            "input": draft.input_cost_milli,
            "cache_read": draft.cache_read_cost_milli,
            "output": draft.output_cost_milli,
            "total": draft.total_cost_milli,
        },
    )


def ledger_row_to_usage_attempt(row: Mapping[str, Any] | sqlite3.Row) -> UsageAttempt:
    """``llm_call_records`` 行（sqlite3.Row / dict）→ UsageAttempt。"""
    data = dict(row)
    tokens = {
        "input": data.get("prompt_tokens"),
        "output": data.get("completion_tokens"),
        "total": data.get("total_tokens"),
        "cache_create": data.get("cache_creation_tokens"),
        "cache_read": data.get("cache_read_tokens"),
    }
    snapshot = _snapshot_from_ledger_tokens(tokens)
    measured = any(q.status == "measured" for q in snapshot.quantities.values())
    attempt_id = str(data.get("request_id") or "")
    call_seq = int(data.get("call_seq") or 1)
    return UsageAttempt(
        operation_id=attempt_id,
        attempt_id=f"{attempt_id}#{call_seq}" if attempt_id else "",
        provider_request_id="",
        provider=str(data.get("provider_id") or ""),
        channel=normalize_channel(str(data.get("provider_id") or "")),
        model=str(data.get("actual_model") or data.get("model_id") or ""),
        task_kind=str(data.get("capability") or ""),
        started_at=str(data.get("started_at") or ""),
        finished_at=str(data.get("completed_at") or ""),
        outcome=str(data.get("status") or ""),
        usage_status="measured" if measured else "unknown",
        raw_usage_schema_version=f"ledger-v{int(data.get('schema_ver') or 1)}",
        snapshot=snapshot,
        legacy_cost_milli={
            "input": data.get("input_cost_milli"),
            "cache_read": data.get("cache_read_cost_milli"),
            "output": data.get("output_cost_milli"),
            "total": data.get("total_cost_milli"),
        },
    )


__all__ = [
    "ALL_METRICS",
    "CHANNEL_UNKNOWN",
    "COMPOSITIONS",
    "INPUT_SEMANTICS_VALUES",
    "QUANTITY_STATUSES",
    "SETTLEMENT_STATUSES",
    "TOKEN_METRICS",
    "ChargeLine",
    "PriceComponent",
    "PriceRevision",
    "PriceUnavailableError",
    "ReservationNotFoundError",
    "ReservationResult",
    "Settlement",
    "SettlementImmutableError",
    "UnsupportedSemanticsError",
    "UsageAggregate",
    "UsageAttempt",
    "UsageBillingError",
    "UsageFilter",
    "UsageInconsistentError",
    "UsageQuantity",
    "UsageSnapshot",
    "aggregate_usage",
    "cancel_reservation",
    "draft_to_usage_attempt",
    "ledger_row_to_usage_attempt",
    "money_str",
    "normalize_channel",
    "normalize_usage",
    "quote_usage",
    "refund_reservation",
    "register_budget",
    "reserve_budget",
    "resolve_price",
    "settle_attempt",
    "settle_reservation",
    "usage_attempt_to_draft",
]
