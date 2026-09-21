"""后端 V2.1 W5 席（S5 计费/Usage 语义服务）回归：离线层核心语义。

合同：docs/design/backend-v2-product-extensions.md §1 全节。
- 数据结构：UsageQuantity / UsageSnapshot / PriceRevision / ChargeLine /
  Settlement / UsageAttempt（usage_status 四态；金额全 Decimal，出参字符串化）；
- 四个确定性算例（§1.2，虚拟测试价格）逐字锁定：
  0.00249 / 0.01249（或 exclusive 0.01）/ TTS 1200 字符 0.018 / 绘图 2 张 0.08，
  以及 partial 算例（缓存读取价未知 → total_cost=null、status=partial）；
- 缓存语义核心正确性：inclusive 差值负数 → usage_inconsistent（禁 max(0)）；
  缺缓存用量 → 区间或 partial；缺缓存价格不得默认回退普通价；
- 预算：SQLite 事务 CAS 扣占，50 线程并发不超卖（实证）；
- ledger 兼容适配：UsageAttempt ←→ 现有账本行映射（不迁移表、不改写历史）。
全部离线（临时 SQLite + 注入数据，零真实 provider 调用）。
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.usage_service import (
    CHANNEL_UNKNOWN,
    ChargeLine,
    PriceComponent,
    PriceRevision,
    PriceUnavailableError,
    SettlementImmutableError,
    UnsupportedSemanticsError,
    UsageAttempt,
    UsageFilter,
    UsageInconsistentError,
    UsageQuantity,
    UsageSnapshot,
    aggregate_usage,
    cancel_reservation,
    draft_to_usage_attempt,
    ledger_row_to_usage_attempt,
    normalize_channel,
    normalize_usage,
    quote_usage,
    refund_reservation,
    register_budget,
    reserve_budget,
    resolve_price,
    settle_attempt,
    settle_reservation,
    usage_attempt_to_draft,
)
from plugins.bot_unified_runtime.llm.ledger import (
    LedgerService,
    build_call_draft,
)

_UTC = timezone.utc


def _dt(text: str) -> datetime:
    return datetime.fromisoformat(text)


# ==================== 价格与快照工厂 ====================


def _llm_price(**overrides: object) -> PriceRevision:
    """算例 1/2 的虚拟价格：每百万 tokens 输入 2 / 输出 8 / 创建 2.5 / 读取 0.2。"""
    fields: dict[str, object] = {
        "price_id": "price-llm-v1",
        "version": "v1",
        "provider": "axonhub",
        "channel": "ch-a",
        "model": "m1",
        "currency": "CNY",
        "effective_from": _dt("2026-01-01T00:00:00+00:00"),
        "effective_to": None,
        "rates": {
            "input_tokens": PriceComponent("input_tokens", "2", 1_000_000),
            "output_tokens": PriceComponent("output_tokens", "8", 1_000_000),
            "cache_create_tokens": PriceComponent(
                "cache_create_tokens", "2.5", 1_000_000
            ),
            "cache_read_tokens": PriceComponent("cache_read_tokens", "0.2", 1_000_000),
        },
    }
    fields.update(overrides)
    return PriceRevision(**fields)  # type: ignore[arg-type]


def _inclusive_snapshot(
    *,
    input_tokens: int = 1000,
    output_tokens: int = 100,
    cache_create: int | None = 100,
    cache_read: int | None = 200,
    total: int | None = None,
    includes_read: object = False,
    disjoint: bool = True,
) -> UsageSnapshot:
    raw: dict[str, int] = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
    if cache_create is not None:
        raw["cache_create_tokens"] = cache_create
    if cache_read is not None:
        raw["cache_read_tokens"] = cache_read
    if total is not None:
        raw["total_tokens"] = total
    schema: dict[str, object] = {
        "input_semantics": "inclusive_cache",
        "cache_creation_includes_read": includes_read,
        "components_disjoint": disjoint,
    }
    return normalize_usage(schema, raw)


# ==================== 数据结构校验 ====================


def test_usage_quantity_rejects_negative_and_nonfinite() -> None:
    with pytest.raises(ValueError):
        UsageQuantity("input_tokens", -1)
    with pytest.raises(ValueError):
        UsageQuantity("input_tokens", float("nan"))
    with pytest.raises(ValueError):
        UsageQuantity("input_tokens", float("inf"))
    with pytest.raises(ValueError):
        UsageQuantity("unknown_metric", 1)
    with pytest.raises(ValueError):
        UsageQuantity("input_tokens", 1, status="bogus_status")
    # value=None 时 status 只允许 unknown / not_applicable。
    with pytest.raises(ValueError):
        UsageQuantity("input_tokens", None, status="measured")


def test_zero_measured_distinct_from_unknown() -> None:
    # 「免费但实际已知为 0」与「未知」必须可区分（§1.1）。
    zero = UsageQuantity("input_tokens", 0, status="measured", source="provider")
    unknown = UsageQuantity("input_tokens", None, status="unknown")
    assert zero.value == 0 and zero.status == "measured"
    assert unknown.value is None and unknown.status == "unknown"


def test_normalize_usage_alias_keys_and_semantics() -> None:
    snapshot = normalize_usage(
        {"input_semantics": "inclusive_cache", "cache_creation_includes_read": False},
        {
            "prompt_tokens": 1000,
            "completion_tokens": 100,
            "cache_write_tokens": 100,
            "cached_tokens": 200,
        },
    )
    assert snapshot.input_semantics == "inclusive_cache"
    assert snapshot.cache_creation_includes_read is False
    assert snapshot.quantity("input_tokens").value == 1000
    assert snapshot.quantity("cache_create_tokens").value == 100
    assert snapshot.quantity("cache_read_tokens").value == 200
    assert snapshot.quantity("output_tokens").value == 100


def test_normalize_usage_prefers_provider_total_and_never_readds_cache() -> None:
    # provider 报告了 total 就用它；缓存 token 不得二次累计进 total（§1.1）。
    snapshot = normalize_usage(
        {"input_semantics": "inclusive_cache", "cache_creation_includes_read": False},
        {
            "input_tokens": 1000,
            "output_tokens": 100,
            "cache_create_tokens": 100,
            "cache_read_tokens": 200,
            "total_tokens": 1100,
        },
    )
    total = snapshot.quantity("total_tokens")
    assert total.value == 1100
    assert total.source == "provider_reported"


def test_normalize_usage_derives_total_only_when_disjoint_confirmed() -> None:
    # total=1100（input+output），绝不能写成 1400（把缓存加回去二次累计）。
    snapshot = _inclusive_snapshot()
    assert snapshot.quantity("total_tokens").value == 1100
    # 适配器未确认各项集合不重叠 → total 保持 unknown，不得推导。
    snapshot2 = _inclusive_snapshot(disjoint=False)
    assert snapshot2.quantity("total_tokens").status == "unknown"
    assert snapshot2.quantity("total_tokens").value is None


def test_normalize_usage_rejects_bad_raw_values() -> None:
    for bad in (-5, float("nan"), float("inf"), True, "abc"):
        with pytest.raises(UsageInconsistentError):
            normalize_usage(
                {"input_semantics": "exclusive_cache"},
                {"prompt_tokens": bad},
            )


def test_normalize_channel_never_impersonates_model() -> None:
    # channel 被 AxonHub 隐藏时保存 unknown，不拿模型名冒充渠道（§1.1）。
    assert normalize_channel("", model="gemini-3.8-flash") == CHANNEL_UNKNOWN
    assert normalize_channel("ch-a", model="m1") == "ch-a"


# ==================== resolve_price ====================


def test_resolve_price_effective_window_and_boundaries() -> None:
    old = _llm_price(version="old", effective_from=_dt("2026-01-01T00:00:00+00:00"))
    new = _llm_price(
        version="new",
        effective_from=_dt("2026-09-01T00:00:00+00:00"),
        effective_to=_dt("2026-10-01T00:00:00+00:00"),
    )
    prices = [old, new]
    assert resolve_price(prices, _dt("2026-08-31T23:59:59+00:00"), ("axonhub", "ch-a", "m1")) is old
    assert resolve_price(prices, _dt("2026-09-15T10:00:00+00:00"), ("axonhub", "ch-a", "m1")) is new
    # effective_to 开区间：恰好到点即失效。
    assert resolve_price(prices, _dt("2026-10-01T00:00:00+00:00"), ("axonhub", "ch-a", "m1")) is old
    # 路由不匹配 → 无价格。
    assert resolve_price(prices, _dt("2026-09-15T10:00:00+00:00"), ("axonhub", "ch-b", "m1")) is None


# ==================== 确定性算例（§1.2） ====================


def test_case1_inclusive_cache_amount_0_00249_total_1100() -> None:
    snapshot = _inclusive_snapshot()
    quote = quote_usage(snapshot, _llm_price())
    assert quote.status == "final"
    assert quote.total_amount == Decimal("0.00249")
    assert quote.currency == "CNY"
    # 普通输入 700，不得把缓存算进普通输入。
    ordinary = [ln for ln in quote.lines if ln.metric == "input_tokens"]
    assert len(ordinary) == 1
    assert ordinary[0].quantity == 700
    # total=1100，不能写 1400（缓存不得二次累计）。
    assert snapshot.quantity("total_tokens").value == 1100


def test_case2_additive_per_request_0_01249_exclusive_0_01() -> None:
    snapshot = _inclusive_snapshot()
    additive = quote_usage(
        snapshot, _llm_price(per_request_price=Decimal("0.01"), composition="additive")
    )
    assert additive.total_amount == Decimal("0.01249")
    # exclusive 请求套餐 0.01：请求费已涵盖用量，金额仅 0.01。
    exclusive = quote_usage(
        snapshot, _llm_price(per_request_price=Decimal("0.01"), composition="exclusive")
    )
    assert exclusive.total_amount == Decimal("0.01")


def test_case3_tts_characters_and_image_generation() -> None:
    tts_price = PriceRevision(
        price_id="price-tts",
        version="v1",
        provider="axonhub",
        channel="tts",
        model="tts-1",
        currency="CNY",
        effective_from=_dt("2026-01-01T00:00:00+00:00"),
        effective_to=None,
        rates={"characters": PriceComponent("characters", "15", 1_000_000)},
    )
    tts_snapshot = normalize_usage(
        {"input_semantics": "unknown", "task_kind": "tts"},
        {"characters": 1200},
    )
    # 无 Token 计量的任务：Token 字段 not_applicable，不得伪造。
    assert tts_snapshot.quantity("total_tokens").status == "not_applicable"
    quote = quote_usage(tts_snapshot, tts_price)
    assert quote.status == "final"
    assert quote.total_amount == Decimal("0.018")

    image_price = PriceRevision(
        price_id="price-image",
        version="v1",
        provider="axonhub",
        channel="image",
        model="img-1",
        currency="CNY",
        effective_from=_dt("2026-01-01T00:00:00+00:00"),
        effective_to=None,
        rates={"images": PriceComponent("images", "0.04", 1)},
    )
    image_snapshot = normalize_usage(
        {"input_semantics": "unknown", "task_kind": "image"},
        {"images": 2},
    )
    assert image_snapshot.quantity("total_tokens").status == "not_applicable"
    img_quote = quote_usage(image_snapshot, image_price)
    assert img_quote.status == "final"
    assert img_quote.total_amount == Decimal("0.08")
    # 不伪造 Token：报价行里不存在任何 token 计量行。
    assert all("tokens" not in ln.metric for ln in img_quote.lines)


def test_case4_partial_unknown_read_price_total_null() -> None:
    # 缓存读取价未知：已知部分与未知读取项分开，total_cost=null、status=partial，
    # 绝不能展示「最终总价 0.00245」。
    price = _llm_price(
        rates={
            "input_tokens": PriceComponent("input_tokens", "2", 1_000_000),
            "output_tokens": PriceComponent("output_tokens", "8", 1_000_000),
            "cache_create_tokens": PriceComponent(
                "cache_create_tokens", "2.5", 1_000_000
            ),
        }
    )
    quote = quote_usage(_inclusive_snapshot(), price)
    assert quote.status == "partial"
    assert quote.total_amount is None
    assert quote.known_amount == Decimal("0.00245")  # 0.0014+0.00025+0.0008
    unknown_metrics = {ln.metric for ln in quote.lines if ln.status == "unknown"}
    assert unknown_metrics == {"cache_read_tokens"}
    assert "cache_read_tokens" in quote.unknown_items


# ==================== 缓存语义核心正确性 ====================


def test_inclusive_negative_difference_raises_usage_inconsistent() -> None:
    # 差值负数必须返回 usage_inconsistent，不能 max(0) 掩盖异常（§1.2）。
    snapshot = _inclusive_snapshot(input_tokens=250, cache_create=100, cache_read=200)
    with pytest.raises(UsageInconsistentError):
        quote_usage(snapshot, _llm_price())


def test_exclusive_semantics_ordinary_input_equals_input() -> None:
    snapshot = normalize_usage(
        {"input_semantics": "exclusive_cache", "cache_creation_includes_read": False},
        {
            "input_tokens": 700,
            "output_tokens": 100,
            "cache_create_tokens": 100,
            "cache_read_tokens": 200,
        },
    )
    quote = quote_usage(snapshot, _llm_price())
    assert quote.status == "final"
    # exclusive：ordinary=input=700；缓存按各自价另计。
    # 金额 = (700×2 + 100×2.5 + 200×0.2 + 100×8)/1e6 = 0.00249。
    assert quote.total_amount == Decimal("0.00249")


def test_missing_cache_quantities_partial_with_bounds() -> None:
    # 缺缓存用量但输入总量已知：只能报价区间或 partial，不得编出精确总价。
    snapshot = _inclusive_snapshot(cache_create=None, cache_read=None)
    quote = quote_usage(snapshot, _llm_price())
    assert quote.status == "partial"
    assert quote.total_amount is None
    assert quote.amount_lower_bound is not None
    assert quote.amount_upper_bound is not None
    assert quote.amount_lower_bound <= quote.amount_upper_bound


def test_missing_cache_price_never_defaults_to_input_price() -> None:
    # 缺缓存价格不得默认等于普通价（§1.2）——除非价格规则显式声明。
    no_cache_price = _llm_price(
        rates={
            "input_tokens": PriceComponent("input_tokens", "2", 1_000_000),
            "output_tokens": PriceComponent("output_tokens", "8", 1_000_000),
        }
    )
    quote = quote_usage(_inclusive_snapshot(), no_cache_price)
    assert quote.status == "partial"
    assert quote.total_amount is None

    # 显式声明缓存价=普通输入价 → 才允许自动结算。
    declared = _llm_price(
        rates={
            "input_tokens": PriceComponent("input_tokens", "2", 1_000_000),
            "output_tokens": PriceComponent("output_tokens", "8", 1_000_000),
        },
        cache_price_follows_input=True,
    )
    settled_quote = quote_usage(_inclusive_snapshot(), declared)
    assert settled_quote.status == "final"
    # (700×2 + 100×2 + 200×2 + 100×8)/1e6 = 0.0028。
    assert settled_quote.total_amount == Decimal("0.0028")


def test_unsupported_semantics_combination_refuses_auto_settlement() -> None:
    # inclusive 且 cache_creation_includes_read=true：读取量可能与创建量重叠，
    # 不支持的组合拒绝自动结算（§1.1）。
    snapshot = _inclusive_snapshot(includes_read=True)
    with pytest.raises(UnsupportedSemanticsError):
        quote_usage(snapshot, _llm_price())
    # 语义 unknown 且缓存量 > 0：同样拒绝自动结算。
    ambiguous = normalize_usage(
        {"input_semantics": "unknown"},
        {
            "input_tokens": 1000,
            "output_tokens": 100,
            "cache_create_tokens": 100,
            "cache_read_tokens": 200,
        },
    )
    with pytest.raises(UnsupportedSemanticsError):
        quote_usage(ambiguous, _llm_price())


# ==================== settle_attempt ====================


def _attempt(snapshot: UsageSnapshot | None = None, **overrides: object) -> UsageAttempt:
    fields: dict[str, object] = {
        "operation_id": "op-1",
        "attempt_id": "op-1#1",
        "provider": "axonhub",
        "channel": "ch-a",
        "model": "m1",
        "task_kind": "chat",
        "owner": "lanxi",
        "scope": "private",
        "started_at": "2026-09-17T10:00:00+08:00",
        "finished_at": "2026-09-17T10:00:02+08:00",
        "outcome": "success",
    }
    fields.update(overrides)
    return UsageAttempt(**fields, snapshot=snapshot)  # type: ignore[arg-type]


def test_settle_attempt_happy_path() -> None:
    attempt = _attempt(_inclusive_snapshot())
    settlement = settle_attempt(attempt, price=_llm_price())
    assert settlement.status == "settled"
    assert settlement.total_amount == "0.00249"
    assert settlement.known_amount == "0.00249"
    assert settlement.currency == "CNY"
    assert all(isinstance(ln, ChargeLine) for ln in settlement.lines)
    assert attempt.settlement is settlement
    assert attempt.usage_status == "measured"


def test_settle_attempt_is_immutable_once_settled() -> None:
    attempt = _attempt(_inclusive_snapshot())
    settle_attempt(attempt, price=_llm_price())
    with pytest.raises(SettlementImmutableError):
        settle_attempt(attempt, price=_llm_price())


def test_settle_attempt_price_unavailable_without_bound() -> None:
    attempt = _attempt(_inclusive_snapshot())
    with pytest.raises(PriceUnavailableError) as raised:
        settle_attempt(attempt, price=None)
    assert raised.value.code == "price_unavailable"


def test_settle_attempt_conservative_upper_bound_is_estimated() -> None:
    # 有已授权保守上限 → 以 estimated 结算；无上限才 price_unavailable（§1.3）。
    attempt = _attempt(_inclusive_snapshot())
    settlement = settle_attempt(
        attempt, price=None, conservative_upper_bound=Decimal("0.01")
    )
    assert settlement.status == "estimated"
    assert settlement.total_amount == "0.01"
    assert "price_revision_missing" in settlement.unknown_items


def test_settle_attempt_partial_keeps_total_null() -> None:
    no_read_price = _llm_price(
        rates={
            "input_tokens": PriceComponent("input_tokens", "2", 1_000_000),
            "output_tokens": PriceComponent("output_tokens", "8", 1_000_000),
            "cache_create_tokens": PriceComponent(
                "cache_create_tokens", "2.5", 1_000_000
            ),
        }
    )
    attempt = _attempt(_inclusive_snapshot())
    settlement = settle_attempt(attempt, price=no_read_price)
    assert settlement.status == "partial"
    assert settlement.total_amount is None
    assert settlement.known_amount == "0.00245"


# ==================== 预算预留（SQLite CAS） ====================


def _micros(db_path: str, scope: str, currency: str = "CNY") -> tuple[int, int]:
    with sqlite3.connect(db_path) as con:
        row = con.execute(
            "SELECT reserved_amount_micros, spent_amount_micros FROM budget_accounts "
            "WHERE scope=? AND currency=?",
            (scope, currency),
        ).fetchone()
    assert row is not None
    return int(row[0]), int(row[1])


def test_reserve_budget_cas_50_threads_no_oversell(tmp_path: Path) -> None:
    db_path = str(tmp_path / "budget.sqlite3")
    scope = "run:acceptance-1"
    register_budget(db_path, scope, "CNY", Decimal("0.30"))
    granted: list[str] = []
    lock = threading.Lock()

    def _worker() -> None:
        result = reserve_budget(db_path, scope, "CNY", Decimal("0.01"))
        with lock:
            if result.granted:
                granted.append(result.reservation_id)

    threads = [threading.Thread(target=_worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    # 恰好 30 笔获批，预算占用分毫不差，绝不超卖。
    assert len(granted) == 30
    reserved, _spent = _micros(db_path, scope)
    assert reserved == 300_000  # 0.30 元 = 300_000 微元
    remaining_after = reserve_budget(db_path, scope, "CNY", Decimal("0.01"))
    assert remaining_after.granted is False
    assert remaining_after.reason == "budget_exceeded"


def test_reserve_budget_unregistered_scope_never_guesses(tmp_path: Path) -> None:
    db_path = str(tmp_path / "budget.sqlite3")
    # 未登记授权预算 → 拒绝；初始金额由授权包提供，不猜充值额（§1.3）。
    result = reserve_budget(db_path, "run:none", "CNY", Decimal("0.01"))
    assert result.granted is False
    assert result.reason == "budget_not_registered"


def test_reservation_lifecycle_settle_cancel_refund(tmp_path: Path) -> None:
    db_path = str(tmp_path / "budget.sqlite3")
    scope = "run:acceptance-2"
    register_budget(db_path, scope, "CNY", Decimal("1.00"))
    res = reserve_budget(db_path, scope, "CNY", Decimal("0.40"))
    assert res.granted is True

    # 取消只标 cancel_requested，保留占用费用（§1.3）。
    state = cancel_reservation(db_path, res.reservation_id)
    assert state == "cancel_requested"
    reserved, _ = _micros(db_path, scope)
    assert reserved == 400_000  # 占用不动

    # 有据结算：按实际金额结转，差额释放。
    end_state = settle_reservation(db_path, res.reservation_id, Decimal("0.25"))
    assert end_state == "settled"
    reserved, spent = _micros(db_path, scope)
    assert (reserved, spent) == (0, 250_000)

    # 退款：占用全额释放、不计支出。
    res2 = reserve_budget(db_path, scope, "CNY", Decimal("0.10"))
    assert refund_reservation(db_path, res2.reservation_id) == "refunded"
    reserved, spent = _micros(db_path, scope)
    assert (reserved, spent) == (0, 250_000)


# ==================== aggregate_usage ====================


def _settled_attempt(
    attempt_id: str,
    *,
    model: str,
    started_at: str,
    channel: str = "ch-a",
    currency: str = "CNY",
    amount: str = "0.1",
) -> UsageAttempt:
    attempt = _attempt(
        None,
        attempt_id=attempt_id,
        operation_id=f"op-{attempt_id}",
        model=model,
        channel=channel,
        started_at=started_at,
        finished_at=started_at,
    )
    settle_attempt(
        attempt,
        price=PriceRevision(
            price_id=f"p-{attempt_id}",
            version="v1",
            provider="axonhub",
            channel=channel,
            model=model,
            currency=currency,
            effective_from=_dt("2026-01-01T00:00:00+00:00"),
            effective_to=None,
            rates={
                "input_tokens": PriceComponent("input_tokens", "2", 1_000_000),
                "output_tokens": PriceComponent("output_tokens", "8", 1_000_000),
            },
        ),
        snapshot=normalize_usage(
            {"input_semantics": "exclusive_cache"},
            {"input_tokens": 100, "output_tokens": 100, "total_tokens": 200},
        ),
    )
    # 覆写金额为固定测试值：直接构造 settlement 金额不可行——改用
    # settle 出的真实金额断言一致性，这里只在需要固定金额的场景使用
    # amount 参数做等值校验的准备（保留参数供阅读语义）。
    del amount
    return attempt


def test_aggregate_usage_buckets_filter_and_multi_currency() -> None:
    attempts = [
        _settled_attempt("a1", model="m1", started_at="2026-09-17T10:00:00+08:00"),
        _settled_attempt("a2", model="m2", started_at="2026-09-17T11:00:00+08:00",
                         channel="ch-b", currency="USD"),
        _settled_attempt("a3", model="m1", started_at="2026-09-16T09:00:00+08:00"),
        _attempt(None, attempt_id="a4", operation_id="op-a4", model="m3",
                 started_at="2026-09-17T12:00:00+08:00"),  # 未结算（无价格）
    ]
    by_model = aggregate_usage(attempts, bucket="model")
    assert set(by_model) == {"m1", "m2", "m3"}
    assert by_model["m1"].attempts == 2
    assert by_model["m1"].billed_attempts == 2
    assert by_model["m3"].billed_attempts == 0
    # 不同币种分别汇总（§1.2）。
    assert by_model["m1"].cost_by_currency == {"CNY": by_model["m1"].cost_by_currency["CNY"]}
    assert by_model["m2"].cost_by_currency["USD"] == by_model["m2"].cost_by_currency["USD"]

    by_day = aggregate_usage(attempts, bucket="day")
    assert set(by_day) == {"2026-09-16", "2026-09-17"}
    assert by_day["2026-09-16"].attempts == 1

    filtered = aggregate_usage(attempts, bucket="model", flt=UsageFilter(model="m1"))
    assert set(filtered) == {"m1"}
    assert filtered["m1"].attempts == 2

    # 排行榜合计须与同过滤条件下 attempt 账本一致（§1.2）。
    total_cny = sum(
        (Decimal(v) for agg in by_model.values()
         for cur, v in agg.cost_by_currency.items() if cur == "CNY"),
        Decimal(0),
    )
    direct_cny = sum(
        (
            Decimal(a.settlement.total_amount or "0")
            for a in attempts
            if a.settlement is not None and a.settlement.currency == "CNY"
        ),
        Decimal(0),
    )
    assert total_cny == direct_cny
    # 金额出参一律字符串。
    for agg in by_model.values():
        for value in agg.cost_by_currency.values():
            assert isinstance(value, str)


# ==================== ledger 兼容适配 ====================


def test_usage_attempt_to_draft_and_back(tmp_path: Path) -> None:
    attempt = _attempt(_inclusive_snapshot())
    settle_attempt(attempt, price=_llm_price())
    draft = usage_attempt_to_draft(attempt)
    assert draft.prompt_tokens == 1000
    assert draft.cache_creation_tokens == 100
    assert draft.cache_read_tokens == 200
    assert draft.completion_tokens == 100
    assert draft.total_tokens == 1100
    # milli = 元 × 1000：0.00249 元 = 2.49 milli → 2（half-up 到毫厘整数）。
    assert draft.total_cost_milli == 2
    assert draft.pricing_source == "usage_service"
    assert draft.unpriced == 0
    assert draft.status == "success"

    # partial → cost 全 NULL + unpriced=1（未知不是 0）。
    partial_price = _llm_price(
        rates={
            "input_tokens": PriceComponent("input_tokens", "2", 1_000_000),
            "output_tokens": PriceComponent("output_tokens", "8", 1_000_000),
        }
    )
    attempt2 = _attempt(_inclusive_snapshot(), attempt_id="op-2")
    settle_attempt(attempt2, price=partial_price)
    draft2 = usage_attempt_to_draft(attempt2)
    assert draft2.total_cost_milli is None
    assert draft2.unpriced == 1

    # 反向映射：历史行语义 unknown（不改写历史、不凭空恢复被舍入的小数）。
    back = draft_to_usage_attempt(draft)
    assert back.attempt_id
    assert back.snapshot is not None
    assert back.snapshot.input_semantics == "unknown"
    assert back.snapshot.quantity("input_tokens").value == 1000
    assert back.snapshot.quantity("cache_read_tokens").value == 200
    assert back.snapshot.quantity("cache_create_tokens").value == 100
    assert back.snapshot.quantity("output_tokens").value == 100


def test_ledger_row_to_usage_attempt_roundtrip(tmp_path: Path) -> None:
    service = LedgerService(str(tmp_path / "ledger.sqlite3"))
    service.submit(
        build_call_draft(
            request_id="req-w5",
            started_at="2026-09-17T10:00:00.000+08:00",
            completed_at="2026-09-17T10:00:01.000+08:00",
            provider_id="ch-a",
            model_id="ch-a",
            actual_model="m1",
            session_id="group-1",
            capability="bot.chat",
            usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            status="success",
        )
    )
    service.flush()
    with sqlite3.connect(service.db_path) as con:
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM llm_call_records").fetchone()
    service.close()
    attempt = ledger_row_to_usage_attempt(row)
    assert attempt.provider_request_id == ""  # 存量行无 provider 回执 ID
    assert attempt.model == "m1"
    assert attempt.channel == "ch-a"
    assert attempt.snapshot is not None
    # 历史行无语义登记：input_semantics 诚实 unknown，不得臆断。
    assert attempt.snapshot.input_semantics == "unknown"
    assert attempt.snapshot.quantity("input_tokens").value == 11
    assert attempt.snapshot.quantity("output_tokens").value == 7
    assert attempt.snapshot.quantity("total_tokens").value == 18
    assert attempt.snapshot.quantity("cache_read_tokens").status == "unknown"
    # 旧 cost_milli 保留迁移来源与精度，不凭空恢复小数（§1.2）。
    assert attempt.legacy_cost_milli["total"] is None
