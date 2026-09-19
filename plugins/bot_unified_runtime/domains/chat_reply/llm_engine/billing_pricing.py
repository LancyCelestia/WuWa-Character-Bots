"""V2.1 S5 计费语义与定价层：normalize_usage / resolve_price / quote_usage。

合同：``docs/design/backend-v2-product-extensions.md`` §1.1/§1.2。
只做纯语义（无 IO、无线程、无 DB）；存储/预算/结算在 billing_service。

核心正确性红线（§1.2 逐条落地）：
- inclusive 且已验证缓存类别互斥（includes_read=False）时::

      ordinary_input = input − cache_create − cache_read

  差值负数抛 ``usage_inconsistent``，**禁止 max(0) 掩盖异常**；
- exclusive 语义下 ``ordinary_input = input_tokens``；
- 缓存 Token 是输入子集，**不叠加进 total 二次累计**；Token 总数优先
  provider 报告，只有适配器确认不重叠（exclusive）时才推导；
- 缺缓存用量但输入总量已知 → 只能报价区间或 partial（不出假总价）；
- 缺缓存价格 → **不得默认等于普通价**，除非 provider 规则显式声明
  （``PriceRevision.cache_price_follows_input``——旧账本的静默回退
  不在此推广到新链路）；
- inclusive 且 includes_read ∈ {True, unknown} 且缓存量已知非零 →
  拒绝自动结算（``unsupported_usage_semantics``）；
- TTS/绘图的 Token 字段 = not_applicable（除非 provider 真实报告），
  **不得按字符伪造精确 Token**。

金额一律 Decimal（序列化为十进制普通记数字符串）；价格跨生效边界按
``attempt_started_at`` 解析（半开区间）。
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.billing_entities import (
    ChargeLine,
    PriceComponent,
    PriceRevision,
    PriceUnavailableError,
    UnsupportedSemanticsError,
    UsageInconsistentError,
    UsageQuantity,
    UsageQuote,
    UsageSnapshot,
    quantize_amount,
)

UTC = datetime.timezone.utc

# ==================== provider schema 适配注册表 ====================

#: 各 provider usage schema 的默认语义（可被 raw 显式字段覆盖）。
#: - openai：prompt_tokens **包含** cached_tokens（缓存读取是输入子集）；
#:   OpenAI 不暴露"缓存创建"概念，创建量缺失。
#: - anthropic：input_tokens 与 cache_creation/read_input_tokens **互斥并列**
#:   （exclusive），创建不含读取。
#: - axonhub/generic：透传面未知 → unknown，不得臆断。
SCHEMA_SEMANTICS: dict[str, dict[str, Any]] = {
    "openai_chat_v1": {"input_semantics": "inclusive_cache", "includes_read": False},
    "anthropic_messages_v1": {"input_semantics": "exclusive_cache", "includes_read": False},
    "axonhub_v1": {"input_semantics": "unknown", "includes_read": None},
    "tts_v1": {"input_semantics": "unknown", "includes_read": None},
    "image_v1": {"input_semantics": "unknown", "includes_read": None},
    "generic_v1": {"input_semantics": "unknown", "includes_read": None},
}

# raw → 归一化 metric 的键别名表（首个命中优先）。
_RAW_ALIASES: dict[str, tuple[str, ...]] = {
    "input_tokens": ("input_tokens", "prompt_tokens"),
    "output_tokens": ("output_tokens", "completion_tokens"),
    "total_tokens": ("total_tokens",),
    "cache_create_tokens": (
        "cache_create_tokens",
        "cache_write_tokens",
        "cache_creation_input_tokens",
    ),
    "cache_read_tokens": ("cache_read_tokens", "cached_tokens", "cache_read_input_tokens"),
    "characters": ("characters", "character_count"),
    "audio_seconds": ("audio_seconds", "seconds"),
    "images": ("images", "image_count"),
    "requests": ("requests", "request_count"),
}

_TOKEN_METRICS = frozenset(
    {"input_tokens", "output_tokens", "total_tokens", "cache_create_tokens", "cache_read_tokens"}
)


def normalize_channel(observed: object, *, model: str = "") -> str:
    """渠道归一（§1.1）：被 AxonHub 隐藏时保存 ``"unknown"``。

    **不拿模型名冒充渠道**：observed 为空/None/"unknown" 一律 "unknown"，
    即使 model 有值。
    """
    text = str(observed or "").strip()
    if not text or text.lower() == "unknown":
        return "unknown"
    return text[:128]


def normalize_usage(
    provider_schema: str,
    raw: Mapping[str, Any] | None,
    *,
    task_kind: str = "chat",
    raw_usage_schema_version: str = "unknown",
) -> UsageSnapshot:
    """provider 原始 usage → UsageSnapshot（缺失 ≠ 零；真报告才填）。

    - 数值字段仅接受有限非负 int/str（float 拒绝——用量也不经浮点中转）；
      非法/负值字段按缺失处理并登记 unknown（不静默造 0）。
    - Token 字段（total/input/...）在 tts/image 任务下默认 not_applicable，
      除非 provider 真实报告了该字段。
    - ``input_semantics`` / ``cache_creation_includes_read``：raw 显式值优先，
      否则按 SCHEMA_SEMANTICS 默认。
    """
    raw = dict(raw) if isinstance(raw, Mapping) else {}
    semantics = SCHEMA_SEMANTICS.get(provider_schema, SCHEMA_SEMANTICS["generic_v1"])
    if task_kind not in ("chat", "tts", "image", "other"):
        raise ValueError(f"未知 task_kind: {task_kind!r}")

    quantities: dict[str, UsageQuantity] = {}
    invalid: list[str] = []

    def _to_count(value: object) -> Decimal | None:
        """有限非负数值 → Decimal；float/负数/NaN → None（登记 invalid）。"""
        if isinstance(value, (bool, float)):
            invalid.append(str(value))
            return None
        if isinstance(value, int):
            if value < 0:
                invalid.append(str(value))
                return None
            return Decimal(value)
        if isinstance(value, str):
            try:
                parsed = Decimal(value.strip())
            except Exception:  # noqa: BLE001 - 非法文本按缺失处理
                invalid.append(str(value))
                return None
            if not parsed.is_finite() or parsed < 0:
                invalid.append(str(value))
                return None
            return parsed
        if isinstance(value, Decimal):
            if not value.is_finite() or value < 0:
                invalid.append(str(value))
                return None
            return value
        invalid.append(str(value))
        return None

    for metric, aliases in _RAW_ALIASES.items():
        raw_value: object = None
        found = False
        for alias in aliases:
            if alias in raw and raw[alias] is not None:
                raw_value = raw[alias]
                found = True
                break
        is_token_metric = metric in _TOKEN_METRICS
        if not found:
            if is_token_metric and task_kind in ("tts", "image"):
                # Token 与本任务无关（除非真报告）——不按字符伪造 Token。
                quantities[metric] = UsageQuantity(
                    metric=metric, unit="tokens", status="not_applicable",
                    source="task_kind",
                )
            else:
                quantities[metric] = UsageQuantity(
                    metric=metric,
                    unit="tokens" if is_token_metric else _unit_of(metric),
                    status="unknown",
                    source="missing",
                )
            continue
        parsed = _to_count(raw_value)
        if parsed is None:
            quantities[metric] = UsageQuantity(
                metric=metric,
                unit="tokens" if is_token_metric else _unit_of(metric),
                status="unknown",
                source=f"invalid:{provider_schema}",
            )
            continue
        quantities[metric] = UsageQuantity(
            metric=metric,
            value=parsed,
            unit="tokens" if is_token_metric else _unit_of(metric),
            status="measured",
            source="provider",
        )

    # 缓存创建分档（cache_tiers: {"5m": n, "1h": n}）→ 带 cache_tier 的数量。
    tiers_raw = raw.get("cache_tiers")
    if isinstance(tiers_raw, Mapping):
        for tier_key, tier_value in tiers_raw.items():
            parsed = _to_count(tier_value)
            if parsed is None:
                continue
            quantities[f"cache_create_tokens#{tier_key}"] = UsageQuantity(
                metric="cache_create_tokens",
                value=parsed,
                unit="tokens",
                status="measured",
                source="provider",
                cache_tier=str(tier_key)[:32],
            )

    input_semantics = str(raw.get("input_semantics") or semantics["input_semantics"])
    if input_semantics not in ("inclusive_cache", "exclusive_cache", "unknown"):
        input_semantics = "unknown"
    includes_read_raw = raw.get("cache_creation_includes_read", semantics["includes_read"])
    includes_read: bool | None
    if isinstance(includes_read_raw, bool):
        includes_read = includes_read_raw
    elif isinstance(includes_read_raw, str) and includes_read_raw.lower() in ("true", "false"):
        includes_read = includes_read_raw.lower() == "true"
    else:
        includes_read = None

    snapshot = UsageSnapshot(
        task_kind=task_kind,  # type: ignore[arg-type]
        input_semantics=input_semantics,  # type: ignore[arg-type]
        cache_creation_includes_read=includes_read,
        quantities=quantities,
        provider_schema=provider_schema[:64],
        raw_usage_schema_version=raw_usage_schema_version[:64],
    )
    _resolve_total(snapshot)
    if invalid:
        snapshot.blocked_reason = ""  # 非法字段已降级 unknown，不阻断结算；
        snapshot.raw_usage_schema_version = snapshot.raw_usage_schema_version or "invalid"
    return snapshot


def _unit_of(metric: str) -> str:
    from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.billing_entities import (
        METRIC_UNITS,
    )

    return METRIC_UNITS.get(metric, "tokens")


def _resolve_total(snapshot: UsageSnapshot) -> None:
    """total_tokens 三规则（§1.1）：provider 报告优先 → exclusive 且各项已知
    才推导 → 否则 unknown（inclusive 绝不推导，防缓存二次累计）。"""
    total = snapshot.quantity("total_tokens")
    if total is not None and total.status == "measured":
        snapshot.total_source = "provider"
        return
    if snapshot.input_semantics != "exclusive_cache":
        snapshot.total_source = "unknown"
        return
    input_v = snapshot.value("input_tokens")
    create_v = snapshot.value("cache_create_tokens")
    read_v = snapshot.value("cache_read_tokens")
    if input_v is None or create_v is None or read_v is None:
        snapshot.total_source = "unknown"
        return
    derived = input_v + create_v + read_v
    snapshot.quantities["total_tokens"] = UsageQuantity(
        metric="total_tokens",
        value=derived,
        unit="tokens",
        status="estimated",
        source="derived_non_overlapping",
    )
    snapshot.total_source = "derived_non_overlapping"


# ==================== 价格簿与解析 ====================


class PriceBook:
    """PriceRevision 注册与解析；跨生效边界按 attempt_started_at（半开区间）。

    同一 (provider, channel, model) 多版本并存时取 ``version`` 最高者；
    匹配顺序：channel 精确 → channel 通配（"" / "unknown" / "*"）；
    model 精确 → "*"。无命中抛 ``price_unavailable``。
    """

    def __init__(self) -> None:
        self._revisions: list[PriceRevision] = []

    def add(self, revision: PriceRevision) -> PriceRevision:
        self._revisions.append(revision)
        return revision

    def revisions(self) -> tuple[PriceRevision, ...]:
        return tuple(self._revisions)

    def resolve(
        self,
        at: datetime.datetime,
        *,
        provider: str,
        channel: str,
        model: str,
    ) -> PriceRevision:
        candidates = [
            rev
            for rev in self._revisions
            if rev.provider in (provider, "*")
            and rev.covers(at)
            and self._channel_match(rev.channel, channel)
            and rev.model in (model, "*")
        ]
        if not candidates:
            raise PriceUnavailableError(
                f"无覆盖 {at.isoformat()} 的价格: provider={provider} "
                f"channel={channel} model={model}"
            )
        # 版本最高优先；同版本取更精确匹配（channel/model 精确 > 通配）；
        # 仍并列取后注册者（稳定、确定）。
        def _specificity(rev: PriceRevision) -> tuple[int, int, int]:
            return (
                rev.version,
                1 if rev.channel == channel else 0,
                1 if rev.model == model else 0,
            )

        return max(candidates, key=_specificity)

    @staticmethod
    def _channel_match(pattern: str, channel: str) -> bool:
        if pattern in ("", "unknown", "*"):
            return True
        return pattern == channel


def resolve_price(
    book: PriceBook,
    at: datetime.datetime,
    *,
    provider: str,
    channel: str,
    model: str,
) -> PriceRevision:
    """§1.2 接口形态：resolve_price(attempt_started_at, route)。"""
    return book.resolve(at, provider=provider, channel=channel, model=model)


# ==================== 报价（核心语义） ====================


def quote_usage(
    snapshot: UsageSnapshot,
    price: PriceRevision,
    *,
    attempt_id: str,
    line_seq_start: int = 1,
) -> UsageQuote:
    """用量 × 价格版本 → UsageQuote（确定性；金额 Decimal 禁浮点）。

    语义门（§1.1/§1.2）：
    - inclusive + includes_read=True/unknown 且缓存量已知非零 → 拒绝自动结算；
    - inclusive + 互斥：ordinary = input − create − read，负数 →
      ``usage_inconsistent``（禁 max(0)）；
    - exclusive：ordinary = input；
    - unknown 语义或缓存用量缺失 → partial / 区间，不出假总价。
    """
    lines: list[ChargeLine] = []
    unknown_metrics: list[str] = []
    notes: list[str] = []
    composition = price.composition
    currency = price.currency

    def _line(
        metric: str,
        qty: Decimal | None,
        comp: PriceComponent | None,
        *,
        tier: str = "",
        status: str = "billed",
        price_source: str = "listed",
    ) -> ChargeLine:
        from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.billing_entities import (
            METRIC_UNITS,
        )

        amount: Decimal | None = None
        if status == "billed" and comp is not None and qty is not None:
            amount = quantize_amount(
                qty * comp.unit_price / comp.denominator, price.rounding
            )
        elif status == "not_billed":
            # 套餐已涵盖（exclusive）：明确记 0，与"未知价（None）"区分。
            amount = Decimal(0)
        return ChargeLine(
            line_id=f"line-{attempt_id}-{line_seq_start + len(lines)}",
            attempt_id=attempt_id,
            metric=metric,
            tier=tier,
            quantity=qty,
            unit=METRIC_UNITS.get(metric, "tokens"),
            unit_price=comp.unit_price if comp is not None else None,
            denominator=comp.denominator if comp is not None else None,
            price_id=price.price_id,
            price_version=price.version,
            price_source=price_source,  # type: ignore[arg-type]
            amount=amount,
            currency=currency,
            status=status,  # type: ignore[arg-type]
            billing_group="token" if metric.endswith("_tokens") else metric,
        )

    # ---- 语义门与 ordinary_input 推导 ----
    # Token 适用性门：TTS/绘图下 Token 指标为 not_applicable（§1.1 不伪造
    # Token），整族（input/cache/output）不参与计价与 unknown 登记。
    _in_q = snapshot.quantity("input_tokens")
    _out_q = snapshot.quantity("output_tokens")
    token_applicable = not (
        (_in_q is not None and _in_q.status == "not_applicable")
        or (_out_q is not None and _out_q.status == "not_applicable")
    )
    input_qty = snapshot.value("input_tokens")
    create_qty = snapshot.value("cache_create_tokens")
    read_qty = snapshot.value("cache_read_tokens")
    output_qty = snapshot.value("output_tokens")
    semantics = snapshot.input_semantics
    includes_read = snapshot.cache_creation_includes_read

    cache_relevant = token_applicable and task_uses_cache(price)
    ordinary: Decimal | None
    partial_usage = False
    if token_applicable:
        cache_known_nonzero = any(
            q is not None and q > 0 for q in (create_qty, read_qty)
        )
        if semantics == "inclusive_cache" and cache_known_nonzero \
                and includes_read is not False:
            # 未验证互斥：ordinary 推导可能双重扣减 → 拒绝自动结算（§1.1）。
            raise UnsupportedSemanticsError(
                "inclusive_cache 且 cache_creation_includes_read="
                f"{includes_read} 且缓存量非零：语义组合未验证，拒绝自动结算"
            )
    if not token_applicable:
        ordinary = None
    elif semantics == "exclusive_cache":
        ordinary = input_qty
    elif semantics == "inclusive_cache":
        if input_qty is None:
            ordinary = None
            partial_usage = True
        elif create_qty is None or read_qty is None:
            if cache_relevant:
                # 缓存价与输入价不同且用量缺失 → 无法精确拆分：
                # partial + 区间（§1.2，不出假总价）。
                ordinary = None
                partial_usage = True
            else:
                # 缓存不单独计价 → 按全输入计价即精确（拆分不影响金额）。
                ordinary = input_qty
                notes.append("缓存用量未报告且本套餐不单独计缓存价：按全输入计价")
        else:
            ordinary = input_qty - create_qty - read_qty
            if ordinary < 0:
                raise UsageInconsistentError(
                    "usage_inconsistent: inclusive 下 input("
                    f"{input_qty}) − create({create_qty}) − read({read_qty}) "
                    f"= {ordinary} < 0；禁止 max(0) 掩盖异常"
                )
    else:  # unknown
        ordinary = input_qty
        partial_usage = True
        if create_qty is None:
            unknown_metrics.append("cache_create_tokens:usage")
        if read_qty is None:
            unknown_metrics.append("cache_read_tokens:usage")
        notes.append("input_semantics=unknown：ordinary 按全输入保守计，结算为 partial/估算")

    # ---- 组行 ----
    token_lines_billed = True
    if composition == "exclusive":
        # 请求套餐已涵盖 Token 费：Token 行记数量、不计费（amount=0，
        # status=not_billed），金额仅按次费。
        token_lines_billed = False

    input_comp = price.component("input_tokens")
    create_comp = price.component("cache_create_tokens")
    read_comp = price.component("cache_read_tokens")
    output_comp = price.component("output_tokens")
    requests_comp = price.component("requests")
    chars_comp = price.component("characters")
    audio_comp = price.component("audio_seconds")
    images_comp = price.component("images")

    unpriced = False

    def _resolve_cached_price(
        metric: str, comp: PriceComponent | None
    ) -> tuple[PriceComponent | None, str]:
        """缺缓存价：**默认不回退**；仅 provider 显式规则允许（§1.2）。"""
        if comp is not None:
            return comp, "listed"
        if metric in ("cache_create_tokens", "cache_read_tokens") and (
            price.cache_price_follows_input
        ):
            fallback = price.component("input_tokens")
            if fallback is not None:
                return fallback, "follows_input_rule"
        return None, "none"

    if ordinary is not None and token_lines_billed:
        eff_comp, eff_source = _resolve_cached_price("input_tokens", input_comp)
        if eff_comp is None:
            lines.append(_line("input_tokens", ordinary, None, status="unpriced_unknown_price"))
            unknown_metrics.append("input_tokens:price")
            unpriced = True
        else:
            lines.append(_line("input_tokens", ordinary, eff_comp, price_source=eff_source))
    elif ordinary is not None:
        lines.append(_line("input_tokens", ordinary, None, status="not_billed"))

    # 缓存创建：支持多档（tier）；无分档数据时走无档价。
    tier_quantities = {
        q.cache_tier: q.value
        for q in snapshot.quantities.values()
        if q.metric == "cache_create_tokens" and q.cache_tier and q.value is not None
    }
    create_line_emitted = False
    if create_qty is not None and token_lines_billed:
        if tier_quantities and len(tier_quantities) > 1:
            remaining = create_qty
            for tier_key in sorted(tier_quantities):
                tier_qty = tier_quantities[tier_key] or Decimal(0)
                tier_comp = price.component("cache_create_tokens", tier_key) or create_comp
                eff_comp, eff_source = _resolve_cached_price("cache_create_tokens", tier_comp)
                if eff_comp is None:
                    lines.append(_line("cache_create_tokens", tier_qty, None,
                                       tier=tier_key, status="unpriced_unknown_price"))
                    unknown_metrics.append(f"cache_create_tokens#{tier_key}:price")
                    unpriced = True
                else:
                    lines.append(_line("cache_create_tokens", tier_qty, eff_comp,
                                       tier=tier_key, price_source=eff_source))
                remaining -= tier_qty
            if remaining > 0:
                lines.append(_line("cache_create_tokens", remaining, None,
                                   status="unknown_usage"))
                unknown_metrics.append(f"cache_create_tokens#{''}:tier")
                unpriced = True
        else:
            eff_comp, eff_source = _resolve_cached_price("cache_create_tokens", create_comp)
            if eff_comp is None:
                lines.append(_line("cache_create_tokens", create_qty, None,
                                   status="unpriced_unknown_price"))
                unknown_metrics.append("cache_create_tokens:price")
                unpriced = True
            else:
                lines.append(_line("cache_create_tokens", create_qty, eff_comp,
                                   price_source=eff_source))
        create_line_emitted = True
    elif create_qty is None and not create_line_emitted and token_lines_billed \
            and token_applicable:
        if cache_relevant and semantics in ("inclusive_cache", "exclusive_cache"):
            unknown_metrics.append("cache_create_tokens:usage")
            partial_usage = True

    if read_qty is not None and token_lines_billed:
        eff_comp, eff_source = _resolve_cached_price("cache_read_tokens", read_comp)
        if eff_comp is None:
            lines.append(_line("cache_read_tokens", read_qty, None,
                               status="unpriced_unknown_price"))
            unknown_metrics.append("cache_read_tokens:price")
            unpriced = True
        else:
            lines.append(_line("cache_read_tokens", read_qty, eff_comp,
                               price_source=eff_source))
    elif read_qty is None and token_lines_billed and token_applicable:
        if cache_relevant and semantics in ("inclusive_cache", "exclusive_cache"):
            unknown_metrics.append("cache_read_tokens:usage")
            partial_usage = True

    if not token_applicable:
        pass  # TTS/绘图：Token 族不适用，不登记 unknown（§1.1 不伪造 Token）
    elif output_qty is not None:
        if token_lines_billed:
            if output_comp is None:
                lines.append(_line("output_tokens", output_qty, None,
                                   status="unpriced_unknown_price"))
                unknown_metrics.append("output_tokens:price")
                unpriced = True
            else:
                lines.append(_line("output_tokens", output_qty, output_comp))
        else:
            lines.append(_line("output_tokens", output_qty, None, status="not_billed"))
    else:
        unknown_metrics.append("output_tokens:usage")
        partial_usage = True

    # ---- 非 Token 计量（TTS 字符/秒、图片、按次）----
    def _non_token(metric: str, qty: Decimal | None, comp: PriceComponent | None) -> None:
        nonlocal unpriced, partial_usage
        if qty is None:
            if comp is not None:
                unknown_metrics.append(f"{metric}:usage")
                partial_usage = True
            return
        if comp is None:
            return  # 该计量本套餐不涉及（非缺失，不标 unknown）
        amount = quantize_amount(qty * comp.unit_price / comp.denominator, price.rounding)
        lines.append(
            ChargeLine(
                line_id=f"line-{attempt_id}-{line_seq_start + len(lines)}",
                attempt_id=attempt_id,
                metric=metric,
                unit=_unit_of(metric),
                quantity=qty,
                unit_price=comp.unit_price,
                denominator=comp.denominator,
                price_id=price.price_id,
                price_version=price.version,
                amount=amount,
                currency=currency,
                status="billed",
                billing_group=metric,
            )
        )

    _non_token("characters", snapshot.value("characters"), chars_comp)
    _non_token("audio_seconds", snapshot.value("audio_seconds"), audio_comp)
    _non_token("images", snapshot.value("images"), images_comp)

    requests_qty = snapshot.value("requests")
    if requests_comp is not None:
        if requests_qty is None:
            requests_qty = Decimal(1)
            notes.append("requests 未报告：按单请求估算（status=estimated）")
        if composition == "exclusive":
            amount = quantize_amount(
                requests_qty * requests_comp.unit_price / requests_comp.denominator,
                price.rounding,
            )
            lines.append(
                ChargeLine(
                    line_id=f"line-{attempt_id}-{line_seq_start + len(lines)}",
                    attempt_id=attempt_id,
                    metric="requests",
                    unit=_unit_of("requests"),
                    quantity=requests_qty,
                    unit_price=requests_comp.unit_price,
                    denominator=requests_comp.denominator,
                    price_id=price.price_id,
                    price_version=price.version,
                    amount=amount,
                    currency=currency,
                    status="billed",
                    billing_group="requests",
                )
            )
        else:  # additive / tiered：按次费叠加
            _non_token("requests", requests_qty, requests_comp)

    # ---- 汇总（不出假总价）----
    known = sum((ln.amount for ln in lines if ln.amount is not None), Decimal(0))
    known = quantize_amount(known, price.rounding)
    if unpriced or partial_usage:
        low, high = _usage_interval(snapshot, price)
        return UsageQuote(
            attempt_id=attempt_id,
            currency=currency,
            status="partial",
            composition=composition,
            price_id=price.price_id,
            price_version=price.version,
            lines=lines,
            total_amount=None,
            known_amount=known,
            amount_low=low,
            amount_high=high,
            unknown_metrics=sorted(set(unknown_metrics)),
            notes=notes,
        )
    total = quantize_amount(sum((ln.amount for ln in lines if ln.amount is not None), Decimal(0)), price.rounding)
    return UsageQuote(
        attempt_id=attempt_id,
        currency=currency,
        status="ok",
        composition=composition,
        price_id=price.price_id,
        price_version=price.version,
        lines=lines,
        total_amount=total,
        known_amount=total,
        unknown_metrics=[],
        notes=notes,
    )


def task_uses_cache(price: PriceRevision) -> bool:
    """该价格版本是否涉及缓存计价（有缓存组成或显式回退规则）。"""
    return (
        price.component("cache_create_tokens") is not None
        or price.component("cache_read_tokens") is not None
        or price.cache_price_follows_input
    )


def _usage_interval(
    snapshot: UsageSnapshot, price: PriceRevision
) -> tuple[Decimal | None, Decimal | None]:
    """缺缓存用量但输入总量已知时的报价区间（§1.2）。

    - 上界：全部输入按输入价（缓存若有也应更便宜，输入价是保守上界）+ 输出；
    - 下界：输出 + 输入按已知最低缓存价（若有缓存价定义），否则等于上界。
    仅在 input/output 用量已知时给出；否则 (None, None)。
    """
    input_qty = snapshot.value("input_tokens")
    output_qty = snapshot.value("output_tokens")
    output_comp = price.component("output_tokens")
    input_comp = price.component("input_tokens")
    if input_qty is None or input_comp is None:
        return None, None
    upper = input_qty * input_comp.unit_price / input_comp.denominator
    if output_qty is not None and output_comp is not None:
        upper += output_qty * output_comp.unit_price / output_comp.denominator
    lower = Decimal(0)
    if output_qty is not None and output_comp is not None:
        lower += output_qty * output_comp.unit_price / output_comp.denominator
    read_comp = price.component("cache_read_tokens")
    if read_comp is not None and read_comp.unit_price < input_comp.unit_price:
        lower += input_qty * read_comp.unit_price / read_comp.denominator
    else:
        lower += upper - (output_qty * output_comp.unit_price / output_comp.denominator if output_qty is not None and output_comp is not None else Decimal(0))
    return (
        quantize_amount(lower, price.rounding),
        quantize_amount(upper, price.rounding),
    )


__all__ = [
    "SCHEMA_SEMANTICS",
    "PriceBook",
    "normalize_channel",
    "normalize_usage",
    "quote_usage",
    "resolve_price",
    "task_uses_cache",
]
