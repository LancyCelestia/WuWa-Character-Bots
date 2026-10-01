"""S-FIX-FIN-RESIL 行为锁（2026-09-27，全部离线）。

覆盖三票（评审报告 ``.superpowers/sdd/2026-09-27-fullload/SEAT-ATK-FIN.md``）：

* **FIN-R1（V-retry，MEDIUM）**：金融链路的层间重试相乘（G2 外层 ×2 ×
  瞬断 ×3 × 429 已由链接层尊重 Retry-After）+ 线程池 ``with`` 退出无条件
  join，可让慢源把有界聊天 worker 钉死分钟级。修法＝每命令一条端到端网络
  预算（复用 ``chat_reply/runtime/deadline.DeadlineBudget``，不另造计时框架）
  + 429 不跨层重试 + 退避睡眠受预算门控 + 预算内收束、非加入式池退出。
* **FIN-N1（V-numfmt，LOW）**：``json.loads`` 认 NaN/Infinity 字面量，
  ``float()`` 也认，非有限值可一路进卡片数字槽。修法＝数据边界统一
  ``math.isfinite`` 闸（五处 ``_as_float`` + MOEX CLOSE + 腾讯核验行），
  非有限 ⇒ None ⇒ 既有「暂无数据」诚实通道（None≠0 红线不动）。
* **FIN-I1（V-inject 残留，LOW）**：个股 ``f14``、北向 ``LEAD_STOCKS_NAME``
  等远端自由文本入展示字段前在数据边界做控制字符清洗 + 长度钳制。

纪律：反向锁＝预算内正常返回逐字节不变（30 日折线功能完好）；预算耗尽/
非有限值/脏文本一律走既有降级通道，绝不造数、绝不缓存失败、绝不抛穿会话
链路。所有网络出口 monkeypatch 单点拦截，``time.sleep`` 替换为记录器，
测试零真实外呼、零真实退避等待。
"""

from __future__ import annotations

import math
import time
from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.deadline import (
    DeadlineBudget,
)
from plugins.bot_unified_runtime.domains.finance.capabilities import market as mkt
from plugins.bot_unified_runtime.domains.finance.data import (
    bond_data,
    commodities_data,
    fx_data,
    market_crosscheck,
    market_data,
    stock_data,
)
from plugins.bot_unified_runtime.domains.finance.data.market_data import IndexQuote
from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
    ParseHttpError,
)

# ============================================================================
# 夹具
# ============================================================================


def _reset_all_caches() -> None:
    market_data.reset_market_cache()
    market_data.reset_market_trend_cache()
    market_data.reset_northbound_cache()
    stock_data.reset_stock_cache()
    stock_data.reset_stock_history_cache()
    commodities_data.reset_commodities_cache()
    commodities_data.reset_commodities_trend_cache()
    bond_data.reset_bond_cache()
    fx_data.reset_fx_cache()
    market_crosscheck.reset_crosscheck_cache()


@pytest.fixture(autouse=True)
def _clean_caches() -> Any:
    _reset_all_caches()
    yield
    _reset_all_caches()


@pytest.fixture()
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """time.sleep → 记录器：断言退避次数/时长，且测试永不真实等待。"""
    recorded: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda seconds: recorded.append(float(seconds)))
    return recorded


def _expired_budget() -> DeadlineBudget:
    """已耗尽的预算（用 started_at 造，零等待、确定性）。"""
    return DeadlineBudget(1.0, started_at=time.monotonic() - 5.0)


def _fresh_budget() -> DeadlineBudget:
    return DeadlineBudget(60.0)


def _counter(calls: list[str], name: str, result: Any = None):
    def _fn(*_args: Any, **_kwargs: Any) -> Any:
        calls.append(name)
        return {} if result is None else result

    return _fn


@pytest.fixture()
def zero_network(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """把金融数据层**全部**网络出口换成计数器（返回空载荷）。

    任何一次外呼都会在 ``calls`` 里留痕——「预算耗尽 ⇒ 零网络调用」由此可证。
    """
    calls: list[str] = []

    def patch(target: Any, attribute: str, result: Any = None) -> None:
        monkeypatch.setattr(target, attribute, _counter(calls, attribute, result))

    patch(market_data, "_fetch_payload")
    patch(market_data, "http_get_json")
    patch(market_data, "_fetch_northbound_channel")
    patch(commodities_data, "_fetch_payload")
    patch(commodities_data, "http_get_json")
    patch(bond_data, "_fetch_payload")
    patch(fx_data, "_fetch_payload")
    patch(stock_data, "_fetch_payload")
    patch(stock_data, "_fetch_quote_payload")
    patch(stock_data, "_fetch_kline_payload")
    monkeypatch.setattr(
        market_crosscheck,
        "_fetch_tencent_snapshot",
        _counter(calls, "_fetch_tencent_snapshot", {}),
    )
    # MOEX 备选现价源（与上面同名出口不同的单点）。
    # 注意：这里不能用 _counter——它的「空载荷」是 {}，而 ``_fetch_moex_quote``
    # 的合同是 ``IndexQuote | None``；返回 {} 会把假字典当真实行情 append 进
    # 结果（S-FIX-FIN-RESIL-R2 接续修正：夹具违约投毒，不是生产代码错）。
    def _moex_absent(*_args: Any, **_kwargs: Any) -> None:
        calls.append("_fetch_moex_quote")

    monkeypatch.setattr(market_data, "_fetch_moex_quote", _moex_absent)
    return calls


_INDEX_QUOTES = [
    IndexQuote("上证指数", "1.000001", 3888.11, -1.18, -46.29),
    IndexQuote("道琼斯", "100.DJIA", 52573.29, 0.98, 509.19),
]


# ============================================================================
# FIN-R1 ①：预算真身复用中央件，不另造第二套计时框架
# ============================================================================


def test_finance_budget_reuses_deadline_central_piece() -> None:
    budget = market_data.new_network_budget()
    assert isinstance(budget, DeadlineBudget)
    # 复用而非新框架：类型定义仍在 chat_reply.runtime.deadline。
    assert type(budget).__module__.endswith("chat_reply.runtime.deadline")
    assert budget.enabled and budget.total_seconds > 0
    assert not market_data.budget_expired(budget)
    assert market_data.budget_expired(_expired_budget())
    # 未配置（None）⇒ 不拦截（既有调用方行为零变化）。
    assert not market_data.budget_expired(None)
    assert market_data.budget_allows_retry(None)


# ============================================================================
# FIN-R1 ②：429 不跨层重试；退避睡眠受预算门控
# ============================================================================


def _http_429() -> ParseHttpError:
    return ParseHttpError("限流", status_code=429, retry_after_seconds=60)


@pytest.mark.parametrize(
    ("module", "helper"),
    [
        (market_data, "_retry_transient"),
        (commodities_data, "_retry_transient"),
        (stock_data, "_network_retry"),
    ],
)
def test_429_never_retried_across_layers(
    module: Any, helper: str, sleeps: list[float]
) -> None:
    """429 已由链接层（http_util）在单调用内尊重 Retry-After 并重试到位。

    数据层再叠一层就是把 60s 睡眠按层相乘（G2×2 × 瞬断×3 × 60s）——本票根因。
    锁：数据层遇 429 立即上抛，恰好 1 次调用、0 次退避睡眠。
    """
    calls: list[int] = []

    def _fetch() -> Any:
        calls.append(1)
        raise _http_429()

    with pytest.raises(ParseHttpError):
        getattr(module, helper)(_fetch, budget=_fresh_budget())
    assert len(calls) == 1
    assert sleeps == []


def test_transient_failure_still_retries_within_budget(sleeps: list[float]) -> None:
    """反向锁：非 429 瞬断（H-04 通道）在预算内照旧退避重试 3 次。"""
    calls: list[int] = []

    def _fetch() -> Any:
        calls.append(1)
        raise ConnectionError("RemoteDisconnected")

    with pytest.raises(ConnectionError):
        market_data._retry_transient(_fetch, budget=_fresh_budget())
    assert len(calls) == 3
    assert sleeps == [market_data._RETRY_BACKOFF_SECONDS] * 2


def test_backoff_skipped_when_budget_has_no_room(sleeps: list[float]) -> None:
    """剩余预算放不下一次退避 ⇒ 弃剩余重试（不烧调用线程的墙钟）。"""
    calls: list[int] = []

    def _fetch() -> Any:
        calls.append(1)
        raise ConnectionError("RemoteDisconnected")

    tight = DeadlineBudget(market_data._RETRY_BACKOFF_SECONDS / 2.0)
    with pytest.raises(ConnectionError):
        market_data._retry_transient(_fetch, budget=tight)
    assert len(calls) == 1
    assert sleeps == []


def test_g2_empty_response_not_retried_when_budget_tight(
    monkeypatch: pytest.MonkeyPatch, zero_network: list[str], sleeps: list[float]
) -> None:
    """G2 外层（空响应重试）同受预算门控：紧预算 ⇒ 1 次外呼、0 次睡眠。"""
    tight = DeadlineBudget(market_data._RETRY_BACKOFF_SECONDS / 2.0)
    assert market_data.fetch_index_quotes(
        timeout_seconds=1.0, cache_seconds=0.0, budget=tight
    ) == []
    assert zero_network.count("_fetch_payload") == 1
    assert sleeps == []


# ============================================================================
# FIN-R1 ③：线程池退出非阻塞（慢源不再钉死有界聊天 worker）
# ============================================================================


def test_gather_within_budget_does_not_join_slow_future() -> None:
    """预算内收已完成项、未完成如实缺席，且**不等慢 future 跑完**。

    旧结构（``with ThreadPoolExecutor`` + 逐个 ``future.result(timeout)``）在
    退出时无条件 join ⇒ 慢源把 worker 钉满整段睡眠；这里慢项睡 2s，预算
    0.2s，必须在预算附近返回（慢线程稍后自行收尾，其结果已被放弃）。
    """

    def _fetch(key: str) -> tuple[float, ...]:
        if key == "slow":
            time.sleep(2.0)
        return (1.0, 2.0)

    started = time.monotonic()
    raw = market_data.gather_within_budget(
        _fetch, ["fast", "slow"], budget=DeadlineBudget(0.2), max_workers=2
    )
    elapsed = time.monotonic() - started
    assert raw["fast"] == (1.0, 2.0)
    assert raw["slow"] is None  # 缺席＝卡面「暂无数据」，不是 0、不是编造
    assert elapsed < 1.0, f"池退出仍在 join 慢 future（{elapsed:.2f}s）"


def test_gather_within_budget_records_failures_as_absence() -> None:
    def _fetch(key: str) -> Any:
        if key == "bad":
            raise OSError("boom")
        return (3.0,)

    raw = market_data.gather_within_budget(
        _fetch, ["ok", "bad"], budget=_fresh_budget(), max_workers=2
    )
    assert raw == {"ok": (3.0,), "bad": None}


# ============================================================================
# FIN-R1 ④：预算耗尽 ⇒ 零外呼 + 既有诚实降级（逐取数入口）
# ============================================================================


_EXPIRED_CASES: list[tuple[str, Any, Any]] = [
    (
        "market.fetch_index_quotes",
        lambda b: market_data.fetch_index_quotes(
            timeout_seconds=1.0, cache_seconds=0.0, budget=b
        ),
        lambda r: r == [],
    ),
    (
        "market.fetch_index_trend(eastmoney)",
        lambda b: market_data.fetch_index_trend("1.000001", timeout_seconds=1.0, budget=b),
        lambda r: r == (),
    ),
    (
        "market.fetch_index_trend(moex)",
        lambda b: market_data.fetch_index_trend(
            market_data._MOEX_SECID, timeout_seconds=1.0, budget=b
        ),
        lambda r: r == (),
    ),
    (
        "market.fetch_northbound_flows",
        lambda b: market_data.fetch_northbound_flows(timeout_seconds=1.0, budget=b),
        lambda r: r == [],
    ),
    (
        "commodities.fetch_commodity_quotes",
        lambda b: commodities_data.fetch_commodity_quotes(timeout_seconds=1.0, budget=b),
        lambda r: r == [],
    ),
    (
        "commodities.fetch_commodity_trend",
        lambda b: commodities_data.fetch_commodity_trend(
            "101.GC00Y", timeout_seconds=1.0, budget=b
        ),
        lambda r: r == (),
    ),
    (
        "bond.fetch_bond_yields",
        lambda b: bond_data.fetch_bond_yields(timeout_seconds=1.0, budget=b),
        lambda r: r.status == "unavailable" and "预算" in r.note,
    ),
    (
        "fx.fetch_fx_rates",
        lambda b: fx_data.fetch_fx_rates(timeout_seconds=1.0, budget=b),
        lambda r: r == [],
    ),
    (
        "stock.fetch_stock_quote",
        lambda b: stock_data.fetch_stock_quote("AAPL", timeout_seconds=1.0, budget=b),
        lambda r: r.price is None and r.status == "unavailable" and "预算" in r.note,
    ),
    (
        "stock.fetch_stock_ohlcv",
        lambda b: stock_data.fetch_stock_ohlcv("AAPL", timeout_seconds=1.0, budget=b),
        lambda r: not r.bars and r.status == "unavailable",
    ),
    (
        "stock.fetch_market_cap",
        lambda b: stock_data.fetch_market_cap("AAPL", timeout_seconds=1.0, budget=b),
        lambda r: r.value is None and r.status == "unavailable",
    ),
    (
        "stock.fetch_stock_quotes",
        lambda b: stock_data.fetch_stock_quotes(timeout_seconds=1.0, budget=b),
        lambda r: r == [],
    ),
    (
        "stock.fetch_stock_history",
        lambda b: stock_data.fetch_stock_history("NVDA", timeout_seconds=1.0, budget=b),
        lambda r: r == (),
    ),
    (
        "crosscheck.crosscheck_quotes",
        lambda b: market_crosscheck.crosscheck_quotes(
            _INDEX_QUOTES, timeout_seconds=1.0, budget=b
        ),
        lambda r: r.checked == 0,
    ),
]


@pytest.mark.parametrize(
    ("entry", "invoke", "honest"),
    _EXPIRED_CASES,
    ids=[case[0] for case in _EXPIRED_CASES],
)
def test_expired_budget_makes_zero_network_calls(
    entry: str, invoke: Any, honest: Any, zero_network: list[str]
) -> None:
    """端到端预算已尽 ⇒ 一条网络调用都不发，结果走既有诚实降级。"""
    result = invoke(_expired_budget())
    assert honest(result), f"{entry} 未走诚实降级：{result!r}"
    assert zero_network == [], f"{entry} 预算耗尽后仍发起了外呼：{zero_network}"


def test_budget_abandonment_is_not_cached(
    monkeypatch: pytest.MonkeyPatch, zero_network: list[str]
) -> None:
    """「失败不缓存」红线：预算耗尽的缺席不进 TTL 缓存，下轮命令自然重试。"""
    assert market_data.fetch_index_quotes(
        timeout_seconds=1.0, cache_seconds=60.0, budget=_expired_budget()
    ) == []
    assert zero_network == []
    # 换成可用载荷 + 新预算：必须真的外呼并拿到数据（没有被空结果钉死）。
    monkeypatch.setattr(
        market_data,
        "_fetch_payload",
        lambda *_a, **_k: {
            "data": {
                "diff": [
                    {"f12": "000001", "f2": 3888.11, "f3": -1.18, "f4": -46.29, "f14": "上证指数"}
                ]
            }
        },
    )
    quotes = market_data.fetch_index_quotes(timeout_seconds=1.0, cache_seconds=60.0)
    assert [quote.code for quote in quotes] == ["1.000001"]


def test_default_budget_is_per_call_and_unaffected(
    monkeypatch: pytest.MonkeyPatch, zero_network: list[str], sleeps: list[float]
) -> None:
    """反向锁：不传 budget 的既有调用方逐字节不变——正常数据照常返回。"""
    monkeypatch.setattr(
        market_data,
        "_fetch_payload",
        lambda *_a, **_k: {
            "data": {
                "diff": [
                    {"f12": "000001", "f2": 3888.11, "f3": -1.18, "f4": -46.29, "f14": "上证指数"}
                ]
            }
        },
    )
    monkeypatch.setattr(market_data, "_fetch_moex_quote", lambda *_a, **_k: None)
    quotes = market_data.fetch_index_quotes(timeout_seconds=1.0, cache_seconds=0.0)
    assert len(quotes) == 1
    assert quotes[0].name == "上证指数" and quotes[0].price == 3888.11
    assert sleeps == []  # 成功路径零退避


def test_thirty_day_trend_line_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    """反向锁（功能未被预算/闸门打掉）：30 个 finite 收盘点全部保留。"""
    rows = [f"2026-08-{day:02d},{3000.0 + day}" for day in range(1, 31)]
    monkeypatch.setattr(
        market_data, "http_get_json", lambda *_a, **_k: {"data": {"klines": rows}}
    )
    closes = market_data.fetch_index_trend("1.000001", timeout_seconds=1.0)
    assert len(closes) == 30
    assert closes[0] == 3001.0 and closes[-1] == 3030.0


# ============================================================================
# FIN-R1 ⑤：能力层接线——一条命令共用一条预算，面板走预算内收束
# ============================================================================


def _make_message(text: str = "行情") -> IncomingMessage:
    return IncomingMessage(
        request_id="req-seat-fix-fin-resil",
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id="group:g1",
        session_type=SessionType.GROUP,
        sender_id="u1",
        plain_text=text,
    )


def _make_decision() -> BotDecision:
    return BotDecision(
        request_id="req-seat-fix-fin-resil",
        should_respond=True,
        mode="command",
        trigger="行情",
        capability_id="bot.market",
        target_scope=SessionType.GROUP,
        decision_reason="test",
    )


def test_market_capability_shares_one_budget_across_layers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """现价 + 走势面板 + 交叉核验共用同一预算对象，且面板经预算内收束取数。"""
    seen: dict[str, Any] = {}

    def fake_quotes(**kwargs: Any) -> list[IndexQuote]:
        seen["quotes_budget"] = kwargs.get("budget")
        return list(_INDEX_QUOTES)

    def fake_trend(secid: str, timeout_seconds: float = 6.0) -> tuple[float, ...]:
        return (3900.0, 3888.11)

    def fake_gather(fetch, keys, *, budget=None, max_workers=6):  # type: ignore[no-untyped-def]
        seen["gather_budget"] = budget
        seen["gather_workers"] = max_workers
        return {key: fetch(key) for key in keys}

    def fake_crosscheck(quotes, *, timeout_seconds=4.0, budget=None):  # type: ignore[no-untyped-def]
        seen["crosscheck_budget"] = budget
        return market_crosscheck.CrossCheckResult(0, 0, ())

    monkeypatch.setattr(mkt, "fetch_index_quotes", fake_quotes)
    monkeypatch.setattr(mkt, "fetch_index_trend", fake_trend)
    monkeypatch.setattr(mkt, "gather_within_budget", fake_gather)
    monkeypatch.setattr(market_crosscheck, "crosscheck_quotes", fake_crosscheck)

    result = mkt.build_market_capability(None, render_backend=None)(
        _make_message(), _make_decision()
    )
    budget = seen["quotes_budget"]
    assert isinstance(budget, DeadlineBudget)
    assert seen["gather_budget"] is budget
    assert seen["crosscheck_budget"] is budget
    assert result.audit_tags  # 能力照常出结果（降级不等于报错）


def test_market_capability_has_no_unconditional_join_pool() -> None:
    """形态锁：金融能力层不再用 ``with ThreadPoolExecutor`` 无条件 join 退出。"""
    import pathlib

    text = pathlib.Path(mkt.__file__).read_text(encoding="utf-8")
    assert "with ThreadPoolExecutor" not in text
    assert "gather_within_budget" in text


# ============================================================================
# FIN-N1：数据边界统一 isfinite 闸
# ============================================================================

_NON_FINITE = ["nan", "NaN", "infinity", "-Infinity", "inf", "-inf", float("nan"), float("inf"), -float("inf")]


@pytest.mark.parametrize(
    "module",
    [market_data, stock_data, commodities_data, bond_data, fx_data],
    ids=["market", "stock", "commodities", "bond", "fx"],
)
def test_as_float_rejects_non_finite(module: Any) -> None:
    """五处 ``_as_float``：非有限值一律 None（＝既有「暂无数据」通道）。"""
    for raw in _NON_FINITE:
        assert module._as_float(raw) is None, f"{module.__name__} 放行了 {raw!r}"
    # 有限值照常（None≠0 与缺数语义不变）。
    assert module._as_float("1.5") == 1.5
    assert module._as_float(2) == 2.0
    assert module._as_float(None) is None
    assert module._as_float(True) is None
    assert module._as_float("") is None


def test_index_quote_nan_price_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    """json.loads 认 NaN 字面量：非有限现价 ⇒ 该指数整行缺席，不造 0。"""
    monkeypatch.setattr(
        market_data,
        "_fetch_payload",
        lambda *_a, **_k: {
            "data": {
                "diff": [{"f12": "000001", "f2": float("nan"), "f3": -1.18, "f4": -46.29, "f14": "上证指数"}]
            }
        },
    )
    monkeypatch.setattr(market_data, "_fetch_moex_quote", lambda *_a, **_k: None)
    assert market_data.fetch_index_quotes(timeout_seconds=1.0, cache_seconds=0.0) == []


def test_index_trend_non_finite_points_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    """东财 klines 里的 NaN/Infinity 收盘不得进折线（→ _spark_points/ SVG y 槽）。"""
    monkeypatch.setattr(
        market_data,
        "http_get_json",
        lambda *_a, **_k: {
            "data": {
                "klines": [
                    "2026-09-10,3900.00",
                    "2026-09-11,NaN",
                    "2026-09-12,Infinity",
                    "2026-09-13,3934.40",
                ]
            }
        },
    )
    closes = market_data.fetch_index_trend("1.000001", timeout_seconds=1.0)
    assert closes == (3900.0, 3934.4)
    assert all(math.isfinite(value) for value in closes)


def test_moex_trend_non_finite_close_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    """MOEX CLOSE 列改走 _as_float（原裸 ``float()``）：非有限值逐行跳过。"""
    payload = {
        "history.cursor": {"columns": ["TOTAL"], "data": [[42]]},
        "history": {
            "columns": ["TRADEDATE", "CLOSE"],
            "data": [
                ["2026-09-10", 2600.0],
                ["2026-09-11", float("nan")],
                ["2026-09-12", float("inf")],
                ["2026-09-13", "Infinity"],
                ["2026-09-14", 2610.5],
            ],
        },
    }
    monkeypatch.setattr(market_data, "http_get_json", lambda *_a, **_k: payload)
    closes = market_data.fetch_index_trend(market_data._MOEX_SECID, timeout_seconds=1.0)
    assert closes == (2600.0, 2610.5)


def test_moex_trend_bad_rows_skipped_without_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """脏行（非列表/短行）逐行跳过，仍取到可用收盘（坏行跳过纪律不变）。"""
    payload = {
        "history.cursor": {"columns": ["TOTAL"], "data": [[42]]},
        "history": {
            "columns": ["TRADEDATE", "CLOSE"],
            "data": ["not-a-row", ["2026-09-10"], ["2026-09-11", 2600.0]],
        },
    }
    monkeypatch.setattr(market_data, "http_get_json", lambda *_a, **_k: payload)
    assert market_data.fetch_index_trend(market_data._MOEX_SECID, timeout_seconds=1.0) == (
        2600.0,
    )


def test_commodity_trend_non_finite_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        commodities_data,
        "http_get_json",
        lambda *_a, **_k: {"data": {"klines": ["2026-09-11,NaN", "2026-09-12,120.5"]}},
    )
    assert commodities_data.fetch_commodity_trend("101.GC00Y", timeout_seconds=1.0) == (
        120.5,
    )


def test_stock_quote_nan_price_is_unavailable_not_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        stock_data,
        "_fetch_quote_payload",
        lambda *_a, **_k: {
            "data": {"diff": [{"f12": "AAPL", "f2": float("nan"), "f3": 1.0, "f4": 2.0, "f14": "苹果"}]}
        },
    )
    quote = stock_data.fetch_stock_quote("AAPL", timeout_seconds=1.0)
    assert quote.price is None  # 绝不塌成 0.0
    assert quote.status == "unavailable"


def test_crosscheck_non_finite_row_stays_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    """腾讯核验行里的 NaN ⇒ 整行丢弃（核验缺席＝不声明，绝不进差异文案）。"""
    body = 'v_s_sh000001="1~上证指数~000001~NaN~0.00~NaN~1~2";'.encode("gbk")
    monkeypatch.setattr(
        market_crosscheck, "http_get", lambda url, **_kw: (url, body)
    )
    assert market_crosscheck._fetch_tencent_snapshot(("s_sh000001",), 2.0) == {}


def test_fx_cross_rate_non_finite_returns_none() -> None:
    assert fx_data.cross_rate_from_usd({"EUR": 0.9, "JPY": float("inf")}, "EUR", "JPY") is None
    assert fx_data.cross_rate_from_usd({"EUR": 0.9, "JPY": float("nan")}, "EUR", "JPY") is None
    assert fx_data.cross_rate_from_usd({"EUR": 0.0, "JPY": 150.0}, "EUR", "JPY") is None
    assert fx_data.cross_rate_from_usd(
        {"EUR": 0.9, "JPY": 150.0}, "EUR", "JPY"
    ) == pytest.approx(150.0 / 0.9)


# ============================================================================
# FIN-I1：远端自由文本在数据边界清洗 + 钳制
# ============================================================================


def test_sanitize_remote_text_shape() -> None:
    cleaned = market_data.sanitize_remote_text("腾\x00讯\n控股  集团\x1b[31m")
    assert all(ch.isprintable() for ch in cleaned)
    assert "\n" not in cleaned and "\x00" not in cleaned
    assert cleaned.startswith("腾 讯 控股")

    long_text = market_data.sanitize_remote_text("A" * 200)
    assert len(long_text) == market_data._REMOTE_TEXT_MAX_CHARS
    assert long_text.endswith("…")

    assert market_data.sanitize_remote_text(None) == ""
    assert market_data.sanitize_remote_text("   ") == ""


def test_stock_f14_name_cleaned_and_clamped_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    junk = "苹\x00果" + "\n\t" + "X" * 100
    monkeypatch.setattr(
        stock_data,
        "_fetch_quote_payload",
        lambda *_a, **_k: {
            "data": {"diff": [{"f12": "AAPL", "f2": 200.0, "f3": 1.0, "f4": 2.0, "f14": junk}]}
        },
    )
    quote = stock_data.fetch_stock_quote("AAPL", timeout_seconds=1.0)
    assert quote.price == 200.0  # 数值字段不受影响
    assert len(quote.name) <= market_data._REMOTE_TEXT_MAX_CHARS
    assert all(ch.isprintable() for ch in quote.name)


def test_stock_f14_missing_falls_back_to_registry_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        stock_data,
        "_fetch_quote_payload",
        lambda *_a, **_k: {
            "data": {"diff": [{"f12": "AAPL", "f2": 200.0, "f3": 1.0, "f4": 2.0, "f14": "\x00\x01 \n"}]}
        },
    )
    quote = stock_data.fetch_stock_quote("AAPL", timeout_seconds=1.0)
    assert quote.name == stock_data._COMPANY_BY_TICKER["AAPL"].display  # 注册表名兜底


def test_northbound_lead_stock_cleaned_and_clamped() -> None:
    row = {
        "TRADE_DATE": "2026-09-26",
        "DEAL_AMT": 1000.0,
        "DEAL_NUM": 10.0,
        "LEAD_STOCKS_NAME": "某\x0b股" + "Y" * 100,
        "LS_CHANGE_RATE": 1.23,
        "INDEX_CLOSE_PRICE": 3000.0,
        "INDEX_CHANGE_RATE": 0.1,
    }
    flow = market_data._parse_northbound_flow("1", "沪股通", "上证指数", row, 0.0)
    assert flow is not None
    assert len(flow.lead_stock) <= market_data._REMOTE_TEXT_MAX_CHARS
    assert all(ch.isprintable() for ch in flow.lead_stock)
    assert flow.deal_amt_yi == 10.0  # 数值口径不变


# ============================================================================
# S-FIX-FIN-RESIL-R2 接续补口（2026-09-27 本席）：只补上文未覆盖的方向，
# 三票其余锁沿用前席原文，不重复施工。
# ============================================================================


def test_fx_snapshot_infinite_rate_recorded_missing() -> None:
    """N1 补口：er-api 快照口径 ``Infinity`` 能过 ``>0`` 闸但过不了有限闸。

    ``json.loads`` 默认接受 Infinity 字面量，裸 ``rate > 0`` 挡不住 inf——
    本票在 ``build_snapshot_from_payload`` 边界补 ``math.isfinite`` 闸，
    非有限汇率记入 missing_currencies（缺数如实点名，绝不进汇率表）。
    """
    payload = {"rates": {"EUR": float("inf"), "JPY": float("nan"), "GBP": 0.8}}
    snapshot = fx_data.build_snapshot_from_payload(
        payload, targets=("EUR", "JPY", "GBP")
    )
    by_code = {quote.quote_currency: quote.rate for quote in snapshot.quotes}
    assert "EUR" not in by_code and "EUR" in snapshot.missing_currencies
    assert "JPY" not in by_code and "JPY" in snapshot.missing_currencies
    assert by_code["GBP"] == 0.8  # 正常值不误伤


def test_truncation_notice_only_for_real_truncation() -> None:
    """I1 反向锁：没截过的串绝不许带省略号（谎报的镜像形态）。

    恰好到上限＝原样保留、无省略号；截断标注只属于真被截断的串。
    """
    exact = market_data.sanitize_remote_text("A" * market_data._REMOTE_TEXT_MAX_CHARS)
    assert not exact.endswith("…")
    assert len(exact) == market_data._REMOTE_TEXT_MAX_CHARS
    assert market_data.sanitize_remote_text("英伟达") == "英伟达"
