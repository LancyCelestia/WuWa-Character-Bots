"""全球汇率数据层回归测试（全部离线，HTTP 均打桩）。

夹具取自真实探针（2026-09-12 curl 实测）：
- 东方财富 push2 ``ulist.np/get`` 外汇批量快照（USDCNH/USDCNYC/JPYCNYC
  三行为真实截取，其余按同一字段形状补全成完整可解析形状）；
- 119（直盘现货）/120（人民币中间价）/133（离岸人民币）板块的 FX 日 K
  实测全部为空 → ``FxRate.history`` 恒为空元组，本层不提供 FX 历史。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.capabilities import user_copy
from plugins.bot_unified_runtime.domains.core.contracts.finance import FxRate
from plugins.bot_unified_runtime.domains.finance.data import fx_data
from plugins.bot_unified_runtime.domains.finance.data.fx_data import (
    FX_UNAVAILABLE_PAIRS,
    fetch_fx_rates,
    format_fx_brief,
    format_fx_rate_line,
    fx_pair_availability,
    parse_fx_query,
    reset_fx_cache,
    resolve_fx_pair,
    wants_major_rates,
)

# ---------------------------------------------------------------------------
# 真实探针夹具
# ---------------------------------------------------------------------------

# 真实响应（push2 ulist.np/get，fltt=2）：f2汇率 f3涨跌% f4涨跌额
# f12代码 f13市场号 f14名称 f18昨收。USDCNH/USDCNYC/JPYCNYC 为真实截取。
# 注意：USDCNYC（中间价）只是 USD/CNY 的备用语义，不在宇宙表主源里，
# 出现在响应中也不应产生重复的 USD/CNY 结果。
FX_FIXTURE: dict = {
    "rc": 0,
    "data": {
        "total": 11,
        "diff": [
            {
                "f2": 6.7081,
                "f3": -0.1,
                "f4": -0.0066,
                "f12": "USDCNH",
                "f13": 133,
                "f14": "美元兑离岸人民币",
                "f18": 6.7147,
            },
            {
                "f2": 6.7743,
                "f3": 0.0,
                "f4": 0.0,
                "f12": "USDCNYC",
                "f13": 120,
                "f14": "美元人民币中间价",
                "f18": 6.7743,
            },
            {
                "f2": 7.9525,
                "f3": 0.15,
                "f4": 0.0119,
                "f12": "EURCNYC",
                "f13": 120,
                "f14": "欧元人民币中间价",
                "f18": 7.9406,
            },
            {
                "f2": 4.3614,
                "f3": -0.2,
                "f4": -0.0088,
                "f12": "JPYCNYC",
                "f13": 120,
                "f14": "100日元人民币中间价",
                "f18": 4.3702,
            },
            {
                "f2": 0.8685,
                "f3": -0.05,
                "f4": -0.0004,
                "f12": "HKDCNYC",
                "f13": 120,
                "f14": "港币人民币中间价",
                "f18": 0.8689,
            },
            {
                "f2": 155.2,
                "f3": 0.35,
                "f4": 0.54,
                "f12": "USDJPY",
                "f13": 119,
                "f14": "美元兑日元",
                "f18": 154.66,
            },
            {
                "f2": 1.0842,
                "f3": -0.12,
                "f4": -0.0013,
                "f12": "EURUSD",
                "f13": 119,
                "f14": "欧元兑美元",
                "f18": 1.0855,
            },
            {
                "f2": 1.312,
                "f3": 0.08,
                "f4": 0.001,
                "f12": "GBPUSD",
                "f13": 119,
                "f14": "英镑兑美元",
                "f18": 1.311,
            },
            {
                "f2": 1445.5,
                "f3": -0.4,
                "f4": -5.8,
                "f12": "USDKRW",
                "f13": 119,
                "f14": "美元兑韩元",
                "f18": 1451.3,
            },
            {
                "f2": 7.7812,
                "f3": -0.02,
                "f4": -0.0016,
                "f12": "USDHKD",
                "f13": 119,
                "f14": "美元兑港币",
                "f18": 7.7828,
            },
            {
                "f2": 1.2905,
                "f3": 0.1,
                "f4": 0.0013,
                "f12": "USDSGD",
                "f13": 119,
                "f14": "美元兑新加坡元",
                "f18": 1.2892,
            },
        ],
    },
}

# 缺数夹具：f2="-" 的行整行丢弃；正常行不受影响。
BROKEN_FX_FIXTURE: dict = {
    "data": {
        "diff": [
            {"f2": "-", "f3": -0.1, "f12": "USDCNH", "f14": "美元兑离岸人民币"},
            {"f2": 4.3614, "f3": -0.2, "f12": "JPYCNYC", "f14": "100日元人民币中间价"},
        ]
    }
}


class _Clock:
    """可控单调时钟：fetch TTL 测试用，避免依赖真实睡眠。"""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture()
def _clean_cache() -> Iterator[None]:
    reset_fx_cache()
    yield
    reset_fx_cache()


# ---------------------------------------------------------------------------
# 快照解析：真实夹具 / 宇宙顺序 / 失败降级
# ---------------------------------------------------------------------------


def test_parse_fx_rates_from_real_fixture(_clean_cache, monkeypatch) -> None:
    monkeypatch.setattr(fx_data, "_fetch_payload", lambda secids, timeout: FX_FIXTURE)
    rates = fetch_fx_rates()
    universe_pairs = [pair for pair, *_rest in fx_data._FX_PAIR_UNIVERSE]
    assert [f"{r.base_currency}/{r.quote_currency}" for r in rates] == universe_pairs
    by_pair = {f"{r.base_currency}/{r.quote_currency}": r for r in rates}
    # 主源：133.USDCNH 现货，而非 120.USDCNYC 中间价（备用语义）。
    usdcny = by_pair["USD/CNY"]
    assert usdcny.rate == 6.7081
    assert usdcny.rate_type == "spot"
    assert usdcny.unit_base == 1.0
    assert by_pair["JPY/CNY"].rate == 4.3614
    assert by_pair["JPY/CNY"].unit_base == 100.0  # 100日元中间价
    assert by_pair["JPY/CNY"].rate_type == "parity"
    assert by_pair["EUR/CNY"].rate_type == "parity"
    assert by_pair["EUR/CNY"].rate == 7.9525
    assert by_pair["HKD/CNY"].rate_type == "parity"
    assert by_pair["USD/JPY"].rate == 155.2
    assert by_pair["USD/JPY"].rate_type == "spot"
    assert by_pair["USD/HKD"].rate == 7.7812
    assert by_pair["GBP/USD"].rate == 1.312
    # 通用字段：来源 / 延迟标注 / 历史（FX 日 K 实测无数据，恒为空）。
    for rate in rates:
        assert rate.source == "eastmoney"
        assert rate.delayed is True
        assert rate.history == ()
        assert rate.timestamp  # 抓取时间非空


def test_parse_fx_rates_skips_missing_rows(_clean_cache, monkeypatch) -> None:
    monkeypatch.setattr(fx_data, "_fetch_payload", lambda secids, timeout: BROKEN_FX_FIXTURE)
    rates = fetch_fx_rates()
    assert [f"{r.base_currency}/{r.quote_currency}" for r in rates] == ["JPY/CNY"]


def test_fetch_failure_returns_empty_never_raises(_clean_cache, monkeypatch) -> None:
    def _boom(secids: str, timeout: float) -> dict:
        raise OSError("network down")

    monkeypatch.setattr(fx_data, "_fetch_payload", _boom)
    assert fetch_fx_rates() == []
    # 非法载荷（非 dict / 缺 data）同样安全降级。
    monkeypatch.setattr(fx_data, "_fetch_payload", lambda secids, timeout: None)
    assert fetch_fx_rates() == []
    monkeypatch.setattr(fx_data, "_fetch_payload", lambda secids, timeout: {"data": None})
    assert fetch_fx_rates() == []


def test_single_batch_call_dedups_secids(_clean_cache, monkeypatch) -> None:
    calls: list[str] = []

    def _fake(secids: str, timeout: float) -> dict:
        calls.append(secids)
        return FX_FIXTURE

    monkeypatch.setattr(fx_data, "_fetch_payload", _fake)
    assert len(fetch_fx_rates()) == len(fx_data._FX_PAIR_UNIVERSE)
    assert len(calls) == 1  # 全部货币对一次批量外呼。
    secid_list = calls[0].split(",")
    assert len(secid_list) == len(set(secid_list))  # secid 去重，无重复。


def test_fetch_fx_rates_subset_keeps_universe_order(_clean_cache, monkeypatch) -> None:
    monkeypatch.setattr(fx_data, "_fetch_payload", lambda secids, timeout: FX_FIXTURE)
    rates = fetch_fx_rates(pair_keys=["USD/JPY", "USD/CNY"])
    assert [f"{r.base_currency}/{r.quote_currency}" for r in rates] == ["USD/CNY", "USD/JPY"]
    assert fetch_fx_rates(pair_keys=["AAA/BBB"]) == []
    assert fetch_fx_rates(pair_keys=[]) == []


# ---------------------------------------------------------------------------
# 缓存：命中不二次外呼、失败不缓存、TTL 过期重拉
# ---------------------------------------------------------------------------


def test_cache_hit_expiry_and_failure_not_cached(_clean_cache, monkeypatch) -> None:
    clock = _Clock()
    calls: list[int] = []

    def _fake(secids: str, timeout: float) -> dict:
        calls.append(1)
        if len(calls) == 3:
            raise OSError("transient blip")
        return FX_FIXTURE

    monkeypatch.setattr(fx_data.time, "monotonic", clock)
    monkeypatch.setattr(fx_data, "_fetch_payload", _fake)

    assert len(fetch_fx_rates(cache_seconds=60)) == 10
    clock.now = 1030.0  # TTL 内 → 子集请求也命中缓存，不再外呼。
    subset = fetch_fx_rates(pair_keys=["JPY/CNY"], cache_seconds=60)
    assert [f"{r.base_currency}/{r.quote_currency}" for r in subset] == ["JPY/CNY"]
    assert len(calls) == 1
    clock.now = 1061.0  # TTL 过期 → 重新拉取。
    assert len(fetch_fx_rates(cache_seconds=60)) == 10
    assert len(calls) == 2
    clock.now = 1122.0  # 再次过期 → 这次外呼失败 → 返回空且不缓存。
    assert fetch_fx_rates(cache_seconds=60) == []
    assert len(calls) == 3
    # 失败未污染缓存：立即重试成功并重建缓存。
    assert len(fetch_fx_rates(cache_seconds=60)) == 10
    assert len(calls) == 4
    clock.now = 1170.0  # TTL 内（48s）→ 命中缓存，不再外呼。
    assert len(fetch_fx_rates(cache_seconds=60)) == 10
    assert len(calls) == 4
    reset_fx_cache()


# ---------------------------------------------------------------------------
# 货币对覆盖表 / 反向解析 / 查询解析
# ---------------------------------------------------------------------------


def test_fx_unavailable_pairs_constant() -> None:
    assert FX_UNAVAILABLE_PAIRS == ("USD/TWD", "USD/MOP", "USD/AED")


def test_fx_pair_availability_table() -> None:
    table = fx_pair_availability()
    assert table["USD/CNY"] == "eastmoney:133.USDCNH spot"
    assert table["JPY/CNY"] == "eastmoney:120.JPYCNYC parity"
    assert table["USD/JPY"] == "eastmoney:119.USDJPY spot"
    assert table["USD/TWD"] == "unavailable: 东财无该货币对行情"
    assert table["USD/MOP"] == "unavailable: 东财无该货币对行情"
    assert table["USD/AED"] == "unavailable: 东财无该货币对行情"
    assert set(table) == (
        {pair for pair, *_rest in fx_data._FX_PAIR_UNIVERSE} | set(FX_UNAVAILABLE_PAIRS)
    )


def test_parity_alternates_documented() -> None:
    # 中间价备用语义：主源（133/119）优先，中间价 secid 仅作为备用记录。
    assert fx_data._FX_PARITY_ALTERNATES == {
        "USD/CNY": "120.USDCNYC",
        "EUR/CNY": "120.EURCNYC",
        "JPY/CNY": "120.JPYCNYC",
        "HKD/CNY": "120.HKDCNYC",
    }


@pytest.mark.parametrize(
    "base,quote,expected",
    [
        ("USD", "CNY", ("USD/CNY", False)),
        ("cny", "usd", ("USD/CNY", True)),  # 反向命中 → 调用方取 1/rate 标 derived
        ("EUR", "USD", ("EUR/USD", False)),
        ("USD", "EUR", ("EUR/USD", True)),
        ("USD", "JPY", ("USD/JPY", False)),
    ],
)
def test_resolve_fx_pair_direct_and_reverse(
    base: str, quote: str, expected: tuple[str, bool]
) -> None:
    assert resolve_fx_pair(base, quote) == expected


@pytest.mark.parametrize(
    "base,quote",
    [
        ("USD", "TWD"),  # 无源货币对不在宇宙表
        ("XYZ", "ABC"),
        ("", ""),
    ],
)
def test_resolve_fx_pair_unknown_returns_none(base: str, quote: str) -> None:
    assert resolve_fx_pair(base, quote) is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("美元兑人民币", ("USD", "CNY", 1.0)),
        ("USD/CNY", ("USD", "CNY", 1.0)),
        ("usd/cny", ("USD", "CNY", 1.0)),
        ("100日元换多少人民币", ("JPY", "CNY", 100.0)),
        ("美元汇率", ("USD", "CNY", 1.0)),  # 单查默认兑人民币
        ("日元汇率", ("JPY", "CNY", 1.0)),
        ("美金汇率", ("USD", "CNY", 1.0)),
        ("韩元汇率", ("KRW", "CNY", 1.0)),
        ("新台币汇率", ("TWD", "CNY", 1.0)),  # 无源货币对也要能解析出来
        ("台币汇率", ("TWD", "CNY", 1.0)),
        ("迪拉姆汇率", ("AED", "CNY", 1.0)),
        ("新加坡元汇率", ("SGD", "CNY", 1.0)),
        ("欧元换人民币", ("EUR", "CNY", 1.0)),
        ("美元兑港币", ("USD", "HKD", 1.0)),
        ("1000美元能换多少日元", ("USD", "JPY", 1000.0)),
        ("人民币汇率", None),  # 基准=报价 无意义 → None
        ("汇率", None),  # 纯汇率 → 能力层走主要货币面板
        ("主要货币有哪些", None),
        ("今天天气怎么样", None),
        ("", None),
    ],
)
def test_parse_fx_query_matrix(text: str, expected: tuple[str, str, float] | None) -> None:
    assert parse_fx_query(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("汇率", True),
        ("主要货币", True),
        ("美元汇率", True),
        ("今天天气怎么样", False),
        ("", False),
    ],
)
def test_wants_major_rates(text: str, expected: bool) -> None:
    assert wants_major_rates(text) is expected


# ---------------------------------------------------------------------------
# 文案格式化：金额换算（含 unit_base 折算）/ 降级文案
# ---------------------------------------------------------------------------


def test_format_fx_rate_line_unit_base_conversion() -> None:
    jpy = FxRate(
        base_currency="JPY",
        quote_currency="CNY",
        rate=4.3614,
        unit_base=100.0,
        timestamp="t",
        source="eastmoney",
        rate_type="parity",
    )
    # 100日元中间价 4.3614 → 100日元 ≈ 4.36 人民币。
    assert format_fx_rate_line(jpy, amount=100.0) == "100日元 ≈ 4.36 人民币"
    usd = FxRate(
        base_currency="USD",
        quote_currency="CNY",
        rate=6.7081,
        timestamp="t",
        source="eastmoney",
        rate_type="spot",
    )
    assert format_fx_rate_line(usd) == "1美元 ≈ 6.71 人民币"
    usdjpy = FxRate(
        base_currency="USD",
        quote_currency="JPY",
        rate=155.2,
        timestamp="t",
        source="eastmoney",
        rate_type="spot",
    )
    assert format_fx_rate_line(usdjpy, amount=1000.0) == "1000美元 ≈ 155200.00 日元"


def test_format_fx_brief_and_empty_degrades(monkeypatch) -> None:
    monkeypatch.setattr(fx_data, "_fetch_payload", lambda secids, timeout: FX_FIXTURE)
    reset_fx_cache()
    rates = fetch_fx_rates()
    reset_fx_cache()
    text = format_fx_brief(rates)
    assert text.splitlines()[0] == "主要货币汇率速览"
    assert "1美元 ≈ 6.71 人民币" in text
    assert "100日元 ≈ 4.36 人民币" in text  # brief 按 unit_base 折算展示
    # 审查 Q-01：入 user_copy 池轮换（原固定「汇率数据暂时拉不到，晚点再试试？」）。
    assert format_fx_brief([]) in {
        template.format(reason="汇率数据暂时拉不到")
        for template in user_copy.DATASOURCE_FAILURE_TEMPLATES
    }
