"""V2.1 S5 Usage/Billing Service 回归（A14 计费席）。

合同：docs/design/backend-v2-product-extensions.md §1（数据模型/算法/算例/
预算）。全离线（tmp_path SQLite，无网络、无 NoneBot 运行时）。

覆盖映射（任务书 V21-BILL-001/002/003）：
- 实体严格性：NaN/负值/缺字段/不支持单位/浮点拒绝/extra=forbid；
- 语义：inclusive/exclusive、缓存交叠负数 usage_inconsistent（禁 max(0)）、
  includes_read 未验证拒绝自动结算、total 不二次累计、渠道 unknown；
- 确定性算例①-④（§1.2，虚拟测试价）：0.00249 / 0.01249 / 0.01 /
  0.018+0.08 / partial 不出假总价；
- 价格：跨生效边界（半开区间）、缺缓存价不回退（除非显式规则）；
- 结算：幂等、重复回调去重、退款/调整（历史不可覆盖）、取消后收费、
  重试费用归原 operation；
- 预算：SQLite 事务 CAS 扣占、并发不超卖；
- 聚合：混合币种分币汇总、月账重算一致、排行榜合计与账本一致；
- 迁移：旧 cost_milli 保精度与来源、不得用今价重算、幂等。
"""

from __future__ import annotations

import datetime
import sqlite3
from decimal import Decimal
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.billing_entities import (
    BudgetExceededError,
    ChargeLine,
    PriceComponent,
    PriceRevision,
    PriceUnavailableError,
    Settlement,
    UnsupportedSemanticsError,
    UsageAttempt,
    UsageBillingError,
    UsageInconsistentError,
    UsageQuantity,
    money_str,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.billing_pricing import (
    PriceBook,
    normalize_channel,
    normalize_usage,
    quote_usage,
    resolve_price,
)

UTC = datetime.timezone.utc
T0 = datetime.datetime(2026, 9, 10, 0, 0, 0, tzinfo=UTC)
T1 = datetime.datetime(2026, 9, 15, 0, 0, 0, tzinfo=UTC)
T2 = datetime.datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)


def _price(
    *,
    version: int = 1,
    components: list[PriceComponent] | None = None,
    composition: str = "additive",
    effective_from: datetime.datetime = T0,
    effective_to: datetime.datetime | None = None,
    cache_price_follows_input: bool = False,
    price_id: str = "price-m1",
    model: str = "m1",
    channel: str = "",
    currency: str = "CNY",
) -> PriceRevision:
    return PriceRevision(
        price_id=price_id,
        version=version,
        provider="p1",
        channel=channel,
        model=model,
        effective_from=effective_from,
        effective_to=effective_to,
        currency=currency,
        composition=composition,  # type: ignore[arg-type]
        components=components
        or [
            PriceComponent(metric="input_tokens", unit_price=Decimal(2)),
            PriceComponent(metric="output_tokens", unit_price=Decimal(8)),
            PriceComponent(metric="cache_create_tokens", unit_price=Decimal("2.5")),
            PriceComponent(metric="cache_read_tokens", unit_price=Decimal("0.2")),
        ],
        cache_price_follows_input=cache_price_follows_input,
        source="test-fixture",
        reviewed_by="tester",
    )


def _quote_inclusive_example(price: PriceRevision):
    """算例①原语：输入1000含创建100/读取200、输出100（OpenAI 语义）。"""
    snapshot = normalize_usage(
        "openai_chat_v1",
        {
            "prompt_tokens": 1000,
            "completion_tokens": 100,
            "total_tokens": 1100,
            "cache_creation_input_tokens": 100,
            "cache_read_input_tokens": 200,
        },
        task_kind="chat",
    )
    return snapshot, quote_usage(snapshot, price, attempt_id="att-1")


# ==================== 实体严格性（NaN/负值/缺字段/单位/浮点） ====================


class TestEntityStrictness:
    def test_nan_decimal_rejected(self) -> None:
        # pydantic allow_inf_nan=False 先行拦截（finite_number），实体校验兜底。
        with pytest.raises(ValueError, match="finite"):
            UsageQuantity(metric="input_tokens", value=Decimal("NaN"), unit="tokens",
                          status="measured")

    def test_nan_float_rejected(self) -> None:
        with pytest.raises(ValueError):
            UsageQuantity(metric="input_tokens", value=float("nan"), unit="tokens",
                          status="measured")

    def test_negative_quantity_rejected_at_entity(self) -> None:
        with pytest.raises(ValueError, match="非负"):
            UsageQuantity(metric="input_tokens", value=Decimal(-5), unit="tokens",
                          status="measured")

    def test_missing_value_with_measured_rejected(self) -> None:
        with pytest.raises(ValueError, match="未知不是 0"):
            UsageQuantity(metric="input_tokens", unit="tokens", status="measured")

    def test_unknown_with_value_rejected(self) -> None:
        with pytest.raises(ValueError, match="必须为 null"):
            UsageQuantity(metric="input_tokens", value=Decimal(5), unit="tokens",
                          status="unknown")

    def test_unsupported_unit_for_metric_rejected(self) -> None:
        with pytest.raises(ValueError, match="单位"):
            UsageQuantity(metric="input_tokens", value=Decimal(5), unit="grams",
                          status="measured")

    def test_unsupported_metric_rejected(self) -> None:
        with pytest.raises(ValueError, match="不支持的计量"):
            UsageQuantity(metric="grams", value=Decimal(5), unit="grams",
                          status="measured")

    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(ValueError):
            UsageQuantity(metric="input_tokens", value=Decimal(5), unit="tokens",
                          status="measured", mystery=1)

    def test_money_float_rejected(self) -> None:
        with pytest.raises(ValueError, match="浮点"):
            PriceComponent(metric="input_tokens", unit_price=0.5)  # type: ignore[arg-type]

    def test_naive_datetime_rejected(self) -> None:
        with pytest.raises(ValueError, match="时区"):
            UsageAttempt(
                attempt_id="a1", operation_id="op1", provider="p1", channel="c1",
                model="m1", owner="u1",
                # naive datetime 为有意负样本（实体必须拒绝无时区时间）
                started_at=datetime.datetime(2026, 9, 10),  # noqa: DTZ001
            )

    def test_money_serialization_plain_not_scientific(self) -> None:
        tiny = ChargeLine(
            line_id="l1", attempt_id="a1", metric="input_tokens", unit="tokens",
            quantity=Decimal(1), unit_price=Decimal("0.01"), denominator=Decimal(10**6),
            amount=Decimal("0.00000001"), currency="CNY",
        )
        assert money_str(tiny.amount) == "0.00000001"
        payload = tiny.model_dump(mode="json")
        assert payload["amount"] == "0.00000001"

    def test_settlement_partial_requires_unknown_metrics(self) -> None:
        with pytest.raises(ValueError, match="unknown_metrics"):
            Settlement(
                settlement_id="s1", attempt_id="a1", status="partial",
                currency="CNY", total_amount=None, created_at=T2,
            )

    def test_settlement_partial_forbids_total(self) -> None:
        with pytest.raises(ValueError, match="不出假总价"):
            Settlement(
                settlement_id="s1", attempt_id="a1", status="partial",
                currency="CNY", total_amount=Decimal("0.5"),
                unknown_metrics=["cache_read_tokens:price"], created_at=T2,
            )


# ==================== 归一化语义 ====================


class TestNormalizeUsage:
    def test_openai_inclusive_semantics_default(self) -> None:
        snapshot = normalize_usage(
            "openai_chat_v1",
            {"prompt_tokens": 1000, "completion_tokens": 100},
        )
        assert snapshot.input_semantics == "inclusive_cache"
        assert snapshot.cache_creation_includes_read is False
        assert snapshot.value("input_tokens") == Decimal(1000)
        # 缓存字段缺失 = unknown（≠ 0）
        assert snapshot.quantity("cache_read_tokens") is not None
        assert snapshot.quantity("cache_read_tokens").status == "unknown"
        assert snapshot.value("cache_read_tokens") is None

    def test_anthropic_exclusive_derives_total_only_when_confirmed(self) -> None:
        snapshot = normalize_usage(
            "anthropic_messages_v1",
            {
                "input_tokens": 800,
                "completion_tokens": 100,
                "cache_creation_input_tokens": 100,
                "cache_read_input_tokens": 200,
            },
        )
        assert snapshot.input_semantics == "exclusive_cache"
        # 适配器确认 exclusive（集合不重叠）→ 允许推导 total。
        assert snapshot.total_source == "derived_non_overlapping"
        assert snapshot.value("total_tokens") == Decimal(1100)
        assert snapshot.quantity("total_tokens").status == "estimated"

    def test_inclusive_never_derives_total(self) -> None:
        snapshot = normalize_usage(
            "openai_chat_v1",
            {"prompt_tokens": 1000, "completion_tokens": 100},  # 无 total
        )
        assert snapshot.total_source == "unknown"
        assert snapshot.quantity("total_tokens").status == "unknown"

    def test_provider_reported_total_wins(self) -> None:
        snapshot = normalize_usage(
            "anthropic_messages_v1",
            {"input_tokens": 800, "completion_tokens": 100, "total_tokens": 999},
        )
        assert snapshot.total_source == "provider"
        assert snapshot.value("total_tokens") == Decimal(999)

    def test_invalid_negative_usage_degrades_to_unknown_not_zero(self) -> None:
        snapshot = normalize_usage(
            "openai_chat_v1", {"prompt_tokens": -5, "completion_tokens": 100}
        )
        assert snapshot.value("input_tokens") is None
        assert snapshot.quantity("input_tokens").status == "unknown"

    def test_tts_tokens_not_applicable(self) -> None:
        snapshot = normalize_usage("tts_v1", {"characters": 1200}, task_kind="tts")
        assert snapshot.quantity("input_tokens").status == "not_applicable"
        assert snapshot.value("characters") == Decimal(1200)

    def test_tts_with_real_reported_tokens_keeps_measured(self) -> None:
        snapshot = normalize_usage(
            "tts_v1", {"characters": 1200, "prompt_tokens": 30}, task_kind="tts"
        )
        assert snapshot.value("input_tokens") == Decimal(30)
        assert snapshot.quantity("input_tokens").status == "measured"

    def test_channel_hidden_stays_unknown_never_model_name(self) -> None:
        assert normalize_channel(None, model="m1") == "unknown"
        assert normalize_channel("", model="m1") == "unknown"
        assert normalize_channel("unknown", model="m1") == "unknown"
        assert normalize_channel("axon-c1", model="m1") == "axon-c1"


# ==================== 确定性算例（§1.2，虚拟测试价） ====================


class TestDeterministicExamples:
    def test_example_1_inclusive_ordinary_700_amount_0_00249_total_1100(self) -> None:
        """①输入1000含创建100/读取200输出100；价 2/8/2.5/0.2 每百万。"""
        price = _price()
        snapshot, quote = _quote_inclusive_example(price)
        assert snapshot.input_semantics == "inclusive_cache"
        # ordinary_input = 1000 − 100 − 200 = 700（禁 max(0) 掩盖，此处为正）
        input_line = next(ln for ln in quote.lines if ln.metric == "input_tokens")
        assert input_line.quantity == Decimal(700)
        # 金额 = (700×2 + 100×2.5 + 200×0.2 + 100×8)/1e6 = 0.00249
        assert quote.total_amount == Decimal("0.00249")
        assert quote.status == "ok"
        # total=1100（provider 报告），不能写 1400（缓存不二次累计）
        assert snapshot.value("total_tokens") == Decimal(1100)
        assert snapshot.total_source == "provider"

    def test_example_2a_additive_per_request_0_01249(self) -> None:
        price = _price(
            components=[
                PriceComponent(metric="input_tokens", unit_price=Decimal(2)),
                PriceComponent(metric="output_tokens", unit_price=Decimal(8)),
                PriceComponent(metric="cache_create_tokens", unit_price=Decimal("2.5")),
                PriceComponent(metric="cache_read_tokens", unit_price=Decimal("0.2")),
                PriceComponent(metric="requests", unit_price=Decimal("0.01"),
                               denominator=Decimal(1)),
            ]
        )
        _, quote = _quote_inclusive_example(price)
        assert quote.total_amount == Decimal("0.01249")
        requests_line = next(ln for ln in quote.lines if ln.metric == "requests")
        assert requests_line.amount == Decimal("0.01")

    def test_example_2b_exclusive_package_only_0_01(self) -> None:
        price = _price(
            composition="exclusive",
            components=[
                PriceComponent(metric="requests", unit_price=Decimal("0.01"),
                               denominator=Decimal(1)),
            ],
        )
        _snapshot, quote = _quote_inclusive_example(price)
        assert quote.total_amount == Decimal("0.01")
        assert quote.status == "ok"
        billed = [ln for ln in quote.lines if ln.status == "billed"]
        assert [ln.metric for ln in billed] == ["requests"]
        token_lines = [ln for ln in quote.lines if ln.metric.endswith("_tokens")]
        assert token_lines and all(ln.amount == Decimal(0) for ln in token_lines)

    def test_example_3_tts_characters_and_image_units(self) -> None:
        tts_price = _price(
            price_id="price-tts",
            model="tts-1",
            components=[PriceComponent(metric="characters", unit_price=Decimal(15))],
        )
        tts_snap = normalize_usage("tts_v1", {"characters": 1200}, task_kind="tts")
        tts_quote = quote_usage(tts_snap, tts_price, attempt_id="att-tts")
        assert tts_quote.total_amount == Decimal("0.018")
        assert tts_snap.quantity("input_tokens").status == "not_applicable"
        # 不伪造 Token：无任何 token 计费行
        assert not [ln for ln in tts_quote.lines if ln.metric.endswith("_tokens")
                    and ln.status == "billed"]

        img_price = _price(
            price_id="price-img",
            model="img-1",
            components=[PriceComponent(metric="images", unit_price=Decimal("0.04"),
                                       denominator=Decimal(1))],
        )
        img_snap = normalize_usage("image_v1", {"images": 2}, task_kind="image")
        img_quote = quote_usage(img_snap, img_price, attempt_id="att-img")
        assert img_quote.total_amount == Decimal("0.08")
        assert img_snap.quantity("input_tokens").status == "not_applicable"

    def test_example_4_unknown_cache_read_price_partial_no_fake_total(self) -> None:
        """④缓存读取价未知：total_cost=null + partial；已知部分 0.00245。"""
        price = _price(
            components=[
                PriceComponent(metric="input_tokens", unit_price=Decimal(2)),
                PriceComponent(metric="output_tokens", unit_price=Decimal(8)),
                PriceComponent(metric="cache_create_tokens", unit_price=Decimal("2.5")),
                # cache_read_tokens 组件缺失；未声明 follows-input 规则
            ],
        )
        assert price.cache_price_follows_input is False
        _, quote = _quote_inclusive_example(price)
        assert quote.status == "partial"
        assert quote.total_amount is None  # 不出假总价
        # 已知部分 = 700×2 + 100×2.5 + 100×8 = 0.00245（读取项单列）
        assert quote.known_amount == Decimal("0.00245")
        assert any("cache_read_tokens" in m for m in quote.unknown_metrics)
        read_line = next(ln for ln in quote.lines if ln.metric == "cache_read_tokens")
        assert read_line.amount is None
        assert read_line.status == "unpriced_unknown_price"
        assert read_line.quantity == Decimal(200)


# ==================== 语义门与负数交叠 ====================


class TestSemanticsGates:
    def test_inclusive_overlap_negative_raises_usage_inconsistent(self) -> None:
        """缓存交叠：input 200 < create 100 + read 200 → usage_inconsistent，
        禁止 max(0) 掩盖。"""
        snapshot = normalize_usage(
            "openai_chat_v1",
            {
                "prompt_tokens": 200,
                "completion_tokens": 50,
                "cache_creation_input_tokens": 100,
                "cache_read_input_tokens": 200,
            },
        )
        with pytest.raises(UsageInconsistentError) as excinfo:
            quote_usage(snapshot, _price(), attempt_id="att-neg")
        assert excinfo.value.code == "usage_inconsistent"
        assert "max(0)" in str(excinfo.value)

    def test_inclusive_with_unverified_includes_read_refuses_auto_settlement(self) -> None:
        for includes_read in (True, None):
            snapshot = normalize_usage(
                "axonhub_v1",
                {
                    "input_tokens": 1000,
                    "output_tokens": 100,
                    "cache_create_tokens": 100,
                    "cache_read_tokens": 200,
                    "input_semantics": "inclusive_cache",
                    "cache_creation_includes_read": includes_read,
                },
            )
            with pytest.raises(UnsupportedSemanticsError):
                quote_usage(snapshot, _price(), attempt_id="att-gate")

    def test_inclusive_with_explicitly_exclusive_read_passes(self) -> None:
        snapshot = normalize_usage(
            "axonhub_v1",
            {
                "input_tokens": 1000,
                "output_tokens": 100,
                "cache_create_tokens": 100,
                "cache_read_tokens": 200,
                "input_semantics": "inclusive_cache",
                "cache_creation_includes_read": False,
            },
        )
        quote = quote_usage(snapshot, _price(), attempt_id="att-ok")
        assert quote.total_amount == Decimal("0.00249")

    def test_exclusive_semantics_bills_full_input(self) -> None:
        """exclusive 语义下 ordinary_input = input_tokens（不扣缓存）。"""
        snapshot = normalize_usage(
            "anthropic_messages_v1",
            {
                "input_tokens": 700,
                "completion_tokens": 100,
                "cache_creation_input_tokens": 100,
                "cache_read_input_tokens": 200,
            },
        )
        price = _price()
        quote = quote_usage(snapshot, price, attempt_id="att-ex")
        input_line = next(ln for ln in quote.lines if ln.metric == "input_tokens")
        assert input_line.quantity == Decimal(700)
        # (700×2 + 100×2.5 + 200×0.2 + 100×8)/1e6 = 0.00249（同公式）
        assert quote.total_amount == Decimal("0.00249")

    def test_unknown_semantics_missing_cache_usage_partial_with_interval(self) -> None:
        """缺缓存用量但输入总量已知 → partial 报区间，不出假总价。"""
        snapshot = normalize_usage(
            "generic_v1", {"prompt_tokens": 1000, "completion_tokens": 100}
        )
        quote = quote_usage(snapshot, _price(), attempt_id="att-interval")
        assert quote.status == "partial"
        assert quote.total_amount is None
        assert quote.amount_low is not None and quote.amount_high is not None
        assert quote.amount_low <= quote.amount_high
        # 上界 = 全输入按输入价 + 输出 = 0.0028（保守）
        assert quote.amount_high == Decimal("0.0028")
        assert quote.known_amount == Decimal("0.0028")


# ==================== 价格解析与边界 ====================


class TestPriceResolution:
    def test_price_crosses_effective_boundary_half_open(self) -> None:
        book = PriceBook()
        old = _price(version=1, effective_from=T0, effective_to=T1)
        new = _price(
            version=2,
            effective_from=T1,
            components=[
                PriceComponent(metric="input_tokens", unit_price=Decimal(4)),
                PriceComponent(metric="output_tokens", unit_price=Decimal(8)),
                PriceComponent(metric="cache_create_tokens", unit_price=Decimal("2.5")),
                PriceComponent(metric="cache_read_tokens", unit_price=Decimal("0.2")),
            ],
        )
        book.add(old)
        book.add(new)
        just_before = T1 - datetime.timedelta(seconds=1)
        assert resolve_price(book, just_before, provider="p1", channel="c1",
                             model="m1").version == 1
        # 半开区间：边界时刻属于新版本
        assert resolve_price(book, T1, provider="p1", channel="c1",
                             model="m1").version == 2

    def test_no_coverage_raises_price_unavailable(self) -> None:
        book = PriceBook()
        book.add(_price(version=1, effective_from=T1))
        with pytest.raises(PriceUnavailableError) as excinfo:
            resolve_price(book, T0, provider="p1", channel="c1", model="m1")
        assert excinfo.value.code == "price_unavailable"

    def test_channel_specific_beats_wildcard(self) -> None:
        book = PriceBook()
        book.add(_price(version=1, channel=""))
        book.add(_price(version=1, channel="c1", price_id="price-c1"))
        resolved = resolve_price(book, T0, provider="p1", channel="c1", model="m1")
        assert resolved.price_id == "price-c1"

    def test_missing_cache_price_must_not_default_to_input_price(self) -> None:
        """缺缓存价不得默认等于普通价（除非 provider 规则显式声明）。"""
        no_read = _price(
            components=[
                PriceComponent(metric="input_tokens", unit_price=Decimal(2)),
                PriceComponent(metric="output_tokens", unit_price=Decimal(8)),
            ],
        )
        snapshot = normalize_usage(
            "openai_chat_v1",
            {
                "prompt_tokens": 1000,
                "completion_tokens": 100,
                "cache_read_input_tokens": 200,
            },
        )
        quote = quote_usage(snapshot, no_read, attempt_id="att-nofb")
        assert quote.status == "partial"
        read_line = next(ln for ln in quote.lines if ln.metric == "cache_read_tokens")
        # 不按 input 价回退：金额 None，单列未知
        assert read_line.amount is None
        assert read_line.unit_price is None

    def test_explicit_follows_input_rule_is_honored_and_labeled(self) -> None:
        follows = _price(
            cache_price_follows_input=True,
            components=[
                PriceComponent(metric="input_tokens", unit_price=Decimal(2)),
                PriceComponent(metric="output_tokens", unit_price=Decimal(8)),
            ],
        )
        snapshot = normalize_usage(
            "openai_chat_v1",
            {
                "prompt_tokens": 1000,
                "completion_tokens": 100,
                "cache_read_input_tokens": 200,
                "cache_creation_input_tokens": 100,
            },
        )
        quote = quote_usage(snapshot, follows, attempt_id="att-fb")
        # 显式规则：ordinary 700 + create 100 + read 200 = 1000 全按 2，
        # 输出 100×8 → (1000×2 + 800)/1e6 = 0.0028（总量不变，缓存只影响分解）
        assert quote.status == "ok"
        assert quote.total_amount == Decimal("0.0028")
        read_line = next(ln for ln in quote.lines if ln.metric == "cache_read_tokens")
        assert read_line.price_source == "follows_input_rule"


# ==================== 服务层：结算 / 预算 / 聚合 / 迁移 ====================

import threading

from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.billing_entities import (
    BudgetNotFoundError,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.billing_service import (
    BillingService,
    UsageFilter,
)


def _service(tmp_path, name: str = "billing.sqlite3") -> BillingService:
    return BillingService(str(tmp_path / name))


def _attempt(
    attempt_id: str = "att-svc",
    operation_id: str = "op1",
    *,
    raw: dict[str, Any] | None = None,
    schema: str = "openai_chat_v1",
    model: str = "m1",
    channel: str = "c1",
    outcome: str = "succeeded",
    owner: str = "u1",
    started_at: datetime.datetime = T1,
) -> UsageAttempt:
    snapshot = normalize_usage(schema, raw or {
        "prompt_tokens": 1000,
        "completion_tokens": 100,
        "total_tokens": 1100,
        "cache_creation_input_tokens": 100,
        "cache_read_input_tokens": 200,
    })
    return UsageAttempt(
        attempt_id=attempt_id, operation_id=operation_id,
        provider="p1", channel=channel, model=model, task_kind=snapshot.task_kind,
        owner=owner, started_at=started_at, outcome=outcome,  # type: ignore[arg-type]
        usage_status="measured",
        input_semantics=snapshot.input_semantics,
        cache_creation_includes_read=snapshot.cache_creation_includes_read,
        raw_usage_schema_version=snapshot.raw_usage_schema_version,
        quantities=list(snapshot.quantities.values()),
    )


class _FakeLedgerSink:
    """CallRecordSink 协议桩：记录 submit 的 draft。"""

    def __init__(self) -> None:
        self.drafts: list[Any] = []

    def submit(self, draft: Any) -> None:
        self.drafts.append(draft)


class TestSettlementFlow:
    def test_settle_inclusive_example_amount_and_idempotency(self, tmp_path) -> None:
        service = _service(tmp_path)
        service.register_price(_price())
        service.record_attempt(_attempt("att-a"))
        settlement = service.settle_attempt("att-a")
        assert settlement.status == "settled"
        assert settlement.total_amount == Decimal("0.00249")
        assert settlement.currency == "CNY"
        # 幂等：重复结算返回同一行（revision 1），不产生新账
        again = service.settle_attempt("att-a")
        assert again.settlement_id == settlement.settlement_id
        assert again.revision == 1

    def test_settle_without_price_raises_price_unavailable(self, tmp_path) -> None:
        service = _service(tmp_path)
        service.record_attempt(_attempt("att-b"))
        with pytest.raises(PriceUnavailableError):
            service.settle_attempt("att-b")

    def test_partial_settlement_total_none_but_known_kept(self, tmp_path) -> None:
        """算例④服务级：缺读取价 → partial，total=null，known=0.00245。"""
        service = _service(tmp_path)
        service.register_price(_price(components=[
            PriceComponent(metric="input_tokens", unit_price=Decimal(2)),
            PriceComponent(metric="output_tokens", unit_price=Decimal(8)),
            PriceComponent(metric="cache_create_tokens", unit_price=Decimal("2.5")),
        ]))
        service.record_attempt(_attempt("att-c"))
        settlement = service.settle_attempt("att-c")
        assert settlement.status == "partial"
        assert settlement.total_amount is None
        assert settlement.known_amount == Decimal("0.00245")
        assert any("cache_read_tokens" in m for m in settlement.unknown_metrics)

    def test_duplicate_callback_deduped_by_attempt_and_event_key(self, tmp_path) -> None:
        service = _service(tmp_path)
        service.register_price(_price())
        first = service.record_attempt(
            _attempt("att-d"), source_event_key="evt:1")
        duplicate = service.record_attempt(
            _attempt("att-d"), source_event_key="evt:1")
        assert first.duplicated is False
        assert duplicate.duplicated is True
        service.settle_attempt("att-d")
        # 重复回调不产生新结算
        with sqlite3.connect(service.db_path) as con:
            count = con.execute(
                "SELECT COUNT(*) FROM billing_settlements WHERE attempt_id='att-d'"
            ).fetchone()[0]
        assert count == 1

    def test_cancelled_attempt_can_still_be_billed(self, tmp_path) -> None:
        """取消后收费：取消只标状态，不阻止已产生费用入账（§1.3）。"""
        service = _service(tmp_path)
        service.register_price(_price())
        service.record_attempt(_attempt("att-e", outcome="cancelled"))
        settlement = service.settle_attempt("att-e")
        assert settlement.status == "settled"
        assert settlement.total_amount == Decimal("0.00249")
        rows = service.aggregate_usage(UsageFilter())
        assert rows[0].amounts["CNY"] == Decimal("0.00249")

    def test_retry_cost_attributed_to_original_operation(self, tmp_path) -> None:
        """重试汇总：failover 两 attempt 费用归原 operation（不只算成功模型）。"""
        service = _service(tmp_path)
        service.register_price(_price())  # m1
        service.register_price(_price(
            price_id="price-m2", model="m2",
            components=[PriceComponent(metric="input_tokens", unit_price=Decimal(10)),
                        PriceComponent(metric="output_tokens", unit_price=Decimal(10))],
        ))
        service.record_attempt(_attempt("att-r1", "op-retry", model="m1",
                                        outcome="failed"))
        service.record_attempt(_attempt(
            "att-r2", "op-retry", model="m2",
            raw={"prompt_tokens": 500, "completion_tokens": 50},
            schema="openai_chat_v1", outcome="succeeded"))
        service.settle_attempt("att-r1")   # 700×2+100×2.5+200×0.2+100×8 /1e6 = 0.00249
        service.settle_attempt("att-r2")   # (500×10+50×10)/1e6 = 0.0055
        op_rows = service.aggregate_usage(UsageFilter(operation_id="op-retry"))
        assert op_rows[0].amounts["CNY"] == Decimal("0.00799")  # 0.00249+0.0055
        assert op_rows[0].counts.submitted == 2
        assert op_rows[0].counts.succeeded == 1
        # 分模型排行各归各行（失败 attempt 的费用不消失）
        model_rows = service.aggregate_usage(UsageFilter(operation_id="op-retry"),
                                             bucket="model")
        by_model = {r.key: r.amounts["CNY"] for r in model_rows}
        assert by_model == {"m1": Decimal("0.00249"), "m2": Decimal("0.0055")}

    def test_refund_appends_revision_original_untouched(self, tmp_path) -> None:
        """退款：追加 revision、净额为 0、历史行不可覆盖。"""
        service = _service(tmp_path)
        service.register_price(_price())
        service.record_attempt(_attempt("att-f"))
        v1 = service.settle_attempt("att-f")
        v2 = service.adjust_charge(
            v1.settlement_id, reason="provider 全额退款", actor="admin-a", refund=True)
        assert v2.revision == 2
        assert v2.status == "refunded"
        assert v2.total_amount == Decimal(0)
        assert v2.prev_settlement_id == v1.settlement_id
        # 原始 revision 1 逐字节保留
        refetched = service.get_settlement(v1.settlement_id)
        assert refetched.total_amount == Decimal("0.00249")
        assert refetched.status == "settled"
        # 聚合净额为 0（最新 revision 的 total）
        rows = service.aggregate_usage(UsageFilter())
        assert rows[0].amounts["CNY"] == Decimal(0)

    def test_adjustment_delta_appended_and_net_updated(self, tmp_path) -> None:
        service = _service(tmp_path)
        service.register_price(_price())
        service.record_attempt(_attempt("att-g"))
        v1 = service.settle_attempt("att-g")
        v2 = service.adjust_charge(
            v1.settlement_id,
            deltas={"output_tokens": Decimal("-0.0008")},
            reason="provider 误报输出，核实修正", actor="admin-b")
        assert v2.total_amount == Decimal("0.00169")
        assert v2.status == "settled"
        # 非法计量名拒绝
        with pytest.raises(UsageBillingError, match="调整计量不合法"):
            service.adjust_charge(v1.settlement_id,
                                  deltas={"bogus_metric": Decimal(1)},
                                  reason="x", actor="a")

    def test_over_refund_rejected(self, tmp_path) -> None:
        service = _service(tmp_path)
        service.register_price(_price())
        service.record_attempt(_attempt("att-h"))
        v1 = service.settle_attempt("att-h")
        with pytest.raises(UsageBillingError, match="净额为负"):
            service.adjust_charge(
                v1.settlement_id,
                deltas={"output_tokens": Decimal(-999)},
                reason="超额退款", actor="admin-c")


class TestBudgetReservation:
    def test_reserve_consume_release_flow(self, tmp_path) -> None:
        service = _service(tmp_path)
        service.ensure_budget(scope_kind="principal", scope_key="u1",
                              currency="CNY", limit="0.01")
        rsv = service.reserve_budget(scope_kind="principal", scope_key="u1",
                                     currency="CNY", amount="0.00249",
                                     attempt_id="att-i")
        state = service.budget_state(rsv.budget_id)
        assert state["reserved_micros"] == 2490
        assert state["available_micros"] == 10000 - 2490
        service.consume_reservation(rsv.reservation_id, "0.00249")
        state = service.budget_state(rsv.budget_id)
        assert state["used_micros"] == 2490
        assert state["reserved_micros"] == 0

    def test_reserve_without_envelope_rejected_not_guessed(self, tmp_path) -> None:
        """未登记授权预算 → budget_not_found（不猜充值额，§1.3）。"""
        service = _service(tmp_path)
        with pytest.raises(BudgetNotFoundError):
            service.reserve_budget(scope_kind="principal", scope_key="ghost",
                                   currency="CNY", amount="0.01")

    def test_concurrent_reservation_never_oversells(self, tmp_path) -> None:
        """并发预留：8 线程 × 300μ 争 1000μ 上限 → 恰 3 成，不超卖。

        金额口径：预算 CAS 以微元（1e-6）整数运算，Decimal("0.001")=1000μ。
        """
        limit = Decimal("0.001")     # 1000μ
        per_take = Decimal("0.0003")  # 300μ
        db = str(tmp_path / "race.sqlite3")
        BillingService(db).ensure_budget(scope_kind="test", scope_key="run",
                                         currency="CNY", limit=limit)
        # 两个独立服务实例（独立连接）共库并发，验证 SQLite 层事务 CAS。
        services = [BillingService(db), BillingService(db)]
        barrier = threading.Barrier(8)
        results: list[str] = []
        lock = threading.Lock()

        def take(i: int) -> None:
            service = services[i % 2]
            barrier.wait()
            try:
                service.reserve_budget(scope_kind="test", scope_key="run",
                                       currency="CNY", amount=per_take,
                                       reservation_id=f"rsv-{i}")
                with lock:
                    results.append("ok")
            except BudgetExceededError:
                with lock:
                    results.append("exceeded")

        threads = [threading.Thread(target=take, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert results.count("ok") == 3
        assert results.count("exceeded") == 5
        state = BillingService(db).budget_state("budget:test:run:CNY")
        assert state["reserved_micros"] == 900  # ≤ limit：不超卖

    def test_settle_partial_keeps_reservation_held_until_reconciled(self, tmp_path) -> None:
        """部分可结（缺读取价）：预留**保持挂起**等对账（UNKNOWN 不立即释放
        预算，§1.3）；对账未计费证据 → 释放。"""
        service = _service(tmp_path)
        service.register_price(_price(components=[
            PriceComponent(metric="input_tokens", unit_price=Decimal(2)),
            PriceComponent(metric="output_tokens", unit_price=Decimal(8)),
            PriceComponent(metric="cache_create_tokens", unit_price=Decimal("2.5")),
        ]))
        service.ensure_budget(scope_kind="principal", scope_key="u1",
                              currency="CNY", limit="1")
        rsv = service.reserve_budget(scope_kind="principal", scope_key="u1",
                                     currency="CNY", amount="0.003",
                                     attempt_id="att-j")
        service.record_attempt(_attempt("att-j"))
        settlement = service.settle_attempt("att-j", reservation_id=rsv.reservation_id)
        assert settlement.status == "partial"
        state = service.budget_state(rsv.budget_id)
        assert state["reserved_micros"] == 3000  # 挂起未释放
        assert state["used_micros"] == 0
        released = service.reconcile_unknown("att-j", evidence={"billed": False})
        assert released.status == "released_no_charge"
        state = service.budget_state(rsv.budget_id)
        assert state["reserved_micros"] == 0

    def test_reconcile_unknown_with_invoice_settles(self, tmp_path) -> None:
        service = _service(tmp_path)
        service.register_price(_price())
        service.record_attempt(_attempt("att-k", outcome="unknown"))
        result = service.reconcile_unknown("att-k")  # 无证据 → 挂账告警
        assert result.status == "still_unknown"
        assert result.alert is True
        result2 = service.reconcile_unknown(
            "att-k", evidence={"invoice_ref": "INV-1"})
        assert result2.status == "settled"
        settlement = service.get_settlement(result2.settlement_id)
        assert settlement.invoice_ref == "INV-1"
        assert settlement.total_amount == Decimal("0.00249")


class TestAggregation:
    def test_mixed_currencies_summed_separately(self, tmp_path) -> None:
        service = _service(tmp_path)
        service.register_price(_price())
        service.register_price(_price(
            price_id="price-usd", model="m-usd", currency="USD",
            components=[PriceComponent(metric="requests", unit_price=Decimal(1),
                                       denominator=Decimal(1))],
            composition="exclusive",
        ))
        service.record_attempt(_attempt("att-m1"))  # CNY 0.00249
        service.record_attempt(_attempt("att-m2", model="m-usd",
                                        raw={"requests": 1},
                                        schema="generic_v1"))
        service.settle_attempt("att-m1")
        service.settle_attempt("att-m2")
        rows = service.aggregate_usage(UsageFilter())
        # 不同币种分别汇总（不做换汇）
        assert rows[0].amounts["CNY"] == Decimal("0.00249")
        assert rows[0].amounts["USD"] == Decimal(1)

    def test_monthly_recompute_consistent_and_deterministic(self, tmp_path) -> None:
        """月账重算一致：日桶合计 == 总计；两次聚合一致（无浮点漂移）。"""
        service = _service(tmp_path)
        service.register_price(_price())
        days = [datetime.datetime(2026, 9, d, 8, 0, tzinfo=UTC)
                for d in (10, 15, 16, 30)]
        for i, day in enumerate(days):
            service.record_attempt(_attempt(f"att-day-{i}", f"op-{i}",
                                            started_at=day))
            service.settle_attempt(f"att-day-{i}")
        daily = service.aggregate_usage(UsageFilter(), bucket="day")
        monthly = service.aggregate_usage(UsageFilter())
        daily_sum = sum((r.amounts["CNY"] for r in daily), Decimal(0))
        assert daily_sum == monthly[0].amounts["CNY"] == Decimal("0.00249") * 4
        # 重算一致性：同一数据重跑结果完全一致（Decimal 精确）
        daily_again = service.aggregate_usage(UsageFilter(), bucket="day")
        assert [r.amounts for r in daily_again] == [r.amounts for r in daily]
        assert [r.metric_totals for r in daily_again] == \
            [r.metric_totals for r in daily]

    def test_rankings_consistent_with_attempt_ledger(self, tmp_path) -> None:
        """排行榜合计 == 同过滤条件 attempt 账本合计。"""
        service = _service(tmp_path)
        service.register_price(_price())
        service.register_price(_price(
            price_id="price-m2", model="m2",
            components=[PriceComponent(metric="input_tokens", unit_price=Decimal(5)),
                        PriceComponent(metric="output_tokens", unit_price=Decimal(5))],
        ))
        fixtures = [
            ("att-x1", "op1", "m1", None),
            # m2 价不含缓存组件：用无缓存字段的 raw → 按全输入精确计价
            ("att-x2", "op1", "m2", {"prompt_tokens": 1000, "completion_tokens": 100}),
            ("att-x3", "op2", "m1", None),
            ("att-x4", "op3", "m2", {"prompt_tokens": 1000, "completion_tokens": 100}),
        ]
        for att, op, model, raw in fixtures:
            service.record_attempt(_attempt(att, op, model=model, raw=raw))
            service.settle_attempt(att)
        total = service.aggregate_usage(UsageFilter())[0].amounts["CNY"]
        by_model = service.aggregate_usage(UsageFilter(), bucket="model")
        by_operation = service.aggregate_usage(UsageFilter(), bucket="operation")
        assert sum((r.amounts["CNY"] for r in by_model), Decimal(0)) == total
        assert sum((r.amounts["CNY"] for r in by_operation), Decimal(0)) == total
        ledger_total = Decimal("0.00249") * 2 + Decimal("0.0055") * 2
        assert total == ledger_total

    def test_billed_requests_null_when_bill_unknown(self, tmp_path) -> None:
        service = _service(tmp_path)
        service.register_price(_price())
        service.record_attempt(_attempt("att-bill1", outcome="succeeded"))
        service.settle_attempt("att-bill1")
        service.record_attempt(_attempt("att-bill2", outcome="unknown"))
        rows = service.aggregate_usage(UsageFilter())
        assert rows[0].counts.requested == 2
        assert rows[0].counts.succeeded == 1
        # 账单未知 → billed_requests=null（不用成功数 1 顶替）
        assert rows[0].counts.billed_requests is None


class TestLedgerAdaptation:
    def test_settle_emits_call_record_draft_to_sink(self, tmp_path) -> None:
        """ledger 只读复用适配点：结算经 CallRecordSink 协议回写观测面。"""
        service = _service(tmp_path)
        sink = _FakeLedgerSink()
        service.attach_ledger_sink(sink)
        service.register_price(_price())
        service.record_attempt(_attempt("att-l"))
        service.settle_attempt("att-l")
        assert len(sink.drafts) == 1
        draft = sink.drafts[0]
        # provider 报告原值透传（旧账本"prompt 含缓存"扣减逻辑归 ledger 口径）
        assert draft.prompt_tokens == 1000
        assert draft.cache_creation_tokens == 100
        assert draft.cache_read_tokens == 200
        assert draft.completion_tokens == 100
        assert draft.total_tokens == 1100
        # 毫厘粒度显式量化：0.00249 元 → 2 milli（旧账本精度差异如实降级）
        assert draft.total_cost_milli == 2
        assert draft.pricing_source == "billing_v21"

    def test_migrate_legacy_ledger_preserves_milli_and_source(self, tmp_path) -> None:
        """旧账本迁移：cost_milli 保精度与来源；不重算；幂等。"""
        ledger_db = str(tmp_path / "ledger.sqlite3")
        with sqlite3.connect(ledger_db) as con:
            con.executescript("""
                CREATE TABLE llm_call_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL, call_seq INTEGER NOT NULL DEFAULT 1,
                    session_id TEXT NOT NULL DEFAULT '',
                    capability TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL, completed_at TEXT NOT NULL,
                    provider_id TEXT NOT NULL DEFAULT '',
                    model_id TEXT NOT NULL DEFAULT '',
                    actual_model TEXT NOT NULL DEFAULT '',
                    prompt_tokens INTEGER, cache_creation_tokens INTEGER,
                    cache_read_tokens INTEGER, completion_tokens INTEGER,
                    total_tokens INTEGER,
                    input_cost_milli INTEGER, cache_read_cost_milli INTEGER,
                    output_cost_milli INTEGER, total_cost_milli INTEGER,
                    currency TEXT NOT NULL DEFAULT 'CNY',
                    pricing_source TEXT NOT NULL DEFAULT 'unknown',
                    unpriced INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL, schema_ver INTEGER NOT NULL DEFAULT 1
                );
                INSERT INTO llm_call_records (
                    request_id, started_at, completed_at, provider_id, model_id,
                    actual_model, prompt_tokens, cache_creation_tokens,
                    cache_read_tokens, completion_tokens, total_tokens,
                    input_cost_milli, cache_read_cost_milli, output_cost_milli,
                    total_cost_milli, currency, pricing_source, status
                ) VALUES (
                    'req-legacy-1', '2026-09-10T08:00:00.000+00:00',
                    '2026-09-10T08:00:02.000+00:00', 'p1', 'ch-m1', 'm1',
                    1000, 100, 200, 100, 1100, 1, 0, 1, 2, 'CNY',
                    'channel_spec', 'success'
                );
                INSERT INTO llm_call_records (
                    request_id, started_at, completed_at, provider_id, model_id,
                    actual_model, prompt_tokens, completion_tokens, total_tokens,
                    total_cost_milli, currency, pricing_source, unpriced, status
                ) VALUES (
                    'req-legacy-2', '2026-09-11T08:00:00.000+00:00',
                    '2026-09-11T08:00:01.000+00:00', 'p1', 'ch-m1', 'm1',
                    500, 50, 550, NULL, 'CNY', 'unknown', 1, 'success'
                );
            """)
        service = _service(tmp_path)
        report = service.migrate_ledger_records(ledger_db)
        assert report.imported == 2
        assert report.unpriced == 1
        # 毫厘精度如实保留：total_cost_milli=2 → 0.002（不凭空恢复 0.00249）
        settlement = service.latest_settlement("legacy-req-legacy-1-1")
        assert settlement.total_amount == Decimal("0.002")
        assert settlement.status == "settled"
        assert settlement.invoice_ref.startswith("legacy:llm_call_records:")
        assert "cost_milli" in settlement.note
        # 未计价行 → unknown（未知不是 0）
        unknown_settlement = service.latest_settlement("legacy-req-legacy-2-1")
        assert unknown_settlement.status == "unknown"
        assert unknown_settlement.total_amount is None
        # 幂等：重跑只跳过
        report2 = service.migrate_ledger_records(ledger_db)
        assert report2.imported == 0
        assert report2.skipped_duplicated == 2

    def test_migrated_history_never_repriced_with_today_prices(self, tmp_path) -> None:
        """历史数据不得用今价重算：事后登记同模型新价，迁移行金额不变。"""
        ledger_db = str(tmp_path / "ledger2.sqlite3")
        with sqlite3.connect(ledger_db) as con:
            con.executescript("""
                CREATE TABLE llm_call_records (
                    id INTEGER PRIMARY KEY, request_id TEXT, call_seq INTEGER,
                    session_id TEXT, capability TEXT,
                    started_at TEXT, completed_at TEXT,
                    provider_id TEXT, model_id TEXT, actual_model TEXT,
                    prompt_tokens INTEGER, cache_creation_tokens INTEGER,
                    cache_read_tokens INTEGER, completion_tokens INTEGER,
                    total_tokens INTEGER,
                    input_cost_milli INTEGER, cache_read_cost_milli INTEGER,
                    output_cost_milli INTEGER, total_cost_milli INTEGER,
                    currency TEXT, pricing_source TEXT, unpriced INTEGER,
                    status TEXT, schema_ver INTEGER
                );
                INSERT INTO llm_call_records (
                    request_id, call_seq, started_at, completed_at,
                    provider_id, model_id, actual_model,
                    prompt_tokens, completion_tokens, total_tokens,
                    input_cost_milli, total_cost_milli,
                    currency, pricing_source, unpriced, status, schema_ver
                ) VALUES (
                    'req-old', 1, '2026-09-10T08:00:00.000+00:00',
                    '2026-09-10T08:00:01.000+00:00', 'p1', 'ch-m1', 'm1',
                    1000, 100, 1100, 5, 6, 'CNY', 'channel_spec', 0, 'success', 1
                );
            """)
        service = _service(tmp_path)
        service.migrate_ledger_records(ledger_db)
        # 事后登记同一窗口的"今价"（10 倍）——迁移行不得被重算
        service.register_price(_price(
            version=99,
            components=[PriceComponent(metric="input_tokens", unit_price=Decimal(20)),
                        PriceComponent(metric="output_tokens", unit_price=Decimal(80))],
        ))
        settlement = service.latest_settlement("legacy-req-old-1")
        assert settlement.total_amount == Decimal("0.006")  # 保持 6 milli
        assert settlement.revision == 1
        rows = service.aggregate_usage(UsageFilter())
        assert rows[0].amounts["CNY"] == Decimal("0.006")

    def test_price_registry_persisted_across_restart(self, tmp_path) -> None:
        """价格登记落库：服务重启（新实例同库）后仍可解析结算。"""
        db = str(tmp_path / "persist.sqlite3")
        service = BillingService(db)
        service.register_price(_price())
        service.record_attempt(_attempt("att-p"))
        revived = BillingService(db)
        settlement = revived.settle_attempt("att-p")
        assert settlement.total_amount == Decimal("0.00249")
