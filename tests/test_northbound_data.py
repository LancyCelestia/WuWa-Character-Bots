"""北向资金数据源回归（金融 Phase-1 扩容 2026-09-13，全离线）。

锁定 sources/market_data.py 北向段：
1. 解析：001=沪股通/003=深股通、DEAL_AMT 百万元→亿元（/100）、笔数、领涨股、
   对应指数收盘；无 net 字段（2024-08 起无净买入口径，结构性不造数）；
2. 双通道独立降级：单通道真异常不拖垮另一通道且不重试；
3. G2 纪律：空响应退避重试 1 次、双空零缓存；
4. 文案：只报仍在披露口径，显式说明净买入不再披露。
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest

from plugins.bot_unified_runtime.capabilities import user_copy
from plugins.bot_unified_runtime.domains.finance.data import market_data
from plugins.bot_unified_runtime.domains.finance.data.market_data import (
    NorthboundFlow,
    fetch_northbound_flows,
    format_northbound_brief,
    reset_northbound_cache,
)

# 2026-09-11 实测行（探针逐字段抄录；DEAL_AMT=142256.09 百万 = 1422.5609 亿）。
_ROW_001: dict = {
    "MUTUAL_TYPE": "001",
    "TRADE_DATE": "2026-09-11 00:00:00",
    "FUND_INFLOW": None,
    "NET_DEAL_AMT": None,
    "QUOTA_BALANCE": None,
    "ACCUM_DEAL_AMT": None,
    "BUY_AMT": None,
    "SELL_AMT": None,
    "LEAD_STOCKS_CODE": "600876.SH",
    "LEAD_STOCKS_NAME": "凯盛新能",
    "LS_CHANGE_RATE": 9.99,
    "INDEX_CLOSE_PRICE": 3888.11,
    "INDEX_CHANGE_RATE": -1.18,
    "HOLD_MARKET_CAP": None,
    "DEAL_AMT": 142256.09,
    "DEAL_NUM": 7114374,
}
_ROW_003: dict = {
    "MUTUAL_TYPE": "003",
    "TRADE_DATE": "2026-09-11 00:00:00",
    "DEAL_AMT": 149063.55,
    "DEAL_NUM": 7523378,
    "LEAD_STOCKS_NAME": "远望谷",
    "LS_CHANGE_RATE": 9.99,
    "INDEX_CLOSE_PRICE": 13471.26,
    "INDEX_CHANGE_RATE": -1.08,
}


def _payload(row: dict) -> dict:
    return {"result": {"pages": 1, "data": [row]}}


@pytest.fixture()
def _clean_cache() -> Iterator[None]:
    reset_northbound_cache()
    yield
    reset_northbound_cache()


@pytest.fixture()
def _sleeps(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[float]]:
    recorded: list[float] = []

    def _record(seconds: float) -> None:
        recorded.append(float(seconds))

    monkeypatch.setattr(time, "sleep", _record)
    yield recorded


def _patch_channels(
    monkeypatch: pytest.MonkeyPatch, outcomes: dict[str, object], calls: list[str]
) -> None:
    def _fake(mutual_type: str, timeout_seconds: float):
        calls.append(mutual_type)
        outcome = outcomes.get(mutual_type, {})
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(market_data, "_fetch_northbound_channel", _fake)


def test_fetch_success_parses_both_channels(
    _clean_cache, _sleeps, monkeypatch
) -> None:
    calls: list[str] = []
    _patch_channels(
        monkeypatch,
        {"001": _payload(_ROW_001), "003": _payload(_ROW_003)},
        calls,
    )
    flows = fetch_northbound_flows()
    assert [f.name for f in flows] == ["沪股通", "深股通"]
    assert [f.mutual_type for f in flows] == ["001", "003"]
    sh, sz = flows
    assert sh.trade_date == "2026-09-11"
    assert sh.deal_amt_yi == pytest.approx(1422.5609)  # 百万元 → 亿元 /100
    assert sh.deal_num == 7114374
    assert sh.lead_stock == "凯盛新能" and sh.lead_stock_pct == 9.99
    assert sh.index_name == "上证指数" and sh.index_close == 3888.11
    assert sz.deal_amt_yi == pytest.approx(1490.6355)
    # 诚实结构：快照不存在净买入字段（该口径 2024-08 起无公开数据）。
    assert all(not hasattr(f, "net_amount") for f in flows)
    assert all(f.delayed and f.status == "ok" for f in flows)
    # TTL 命中：第二次调用零外呼。
    assert len(fetch_northbound_flows()) == 2
    assert len(calls) == 2


def test_fetch_url_payload_targets_mutual_type(
    _clean_cache, _sleeps, monkeypatch
) -> None:
    urls: list[str] = []
    real = market_data._fetch_northbound_channel

    def _capture(mutual_type: str, timeout_seconds: float):
        urls.append(market_data._NORTHBOUND_URL.format(mutual_type=mutual_type))
        return real(mutual_type, timeout_seconds)

    def _fake_json(url: str, **kwargs: object):
        return {"result": {"data": [dict(_ROW_001 if "001" in url else _ROW_003)]}}

    monkeypatch.setattr(market_data, "_fetch_northbound_channel", _capture)
    monkeypatch.setattr(market_data, "http_get_json", _fake_json)
    flows = fetch_northbound_flows()
    assert len(flows) == 2
    assert len(urls) == 2
    assert any("MUTUAL_TYPE%3D%22001%22" in url for url in urls)
    assert any("MUTUAL_TYPE%3D%22003%22" in url for url in urls)
    assert all("reportName=RPT_MUTUAL_DEAL_HISTORY" in url for url in urls)
    assert all("sortColumns=TRADE_DATE" in url for url in urls)


def test_fetch_empty_then_data_two_calls_per_channel(
    _clean_cache, _sleeps, monkeypatch
) -> None:
    from plugins.bot_unified_runtime.domains.finance.data.market_data import (
        _RETRY_BACKOFF_SECONDS,
    )

    outcomes: dict[str, list] = {
        "001": [_payload({}), _payload(_ROW_001)],  # 空 → 退避重试 → 有行
        "003": [_payload(_ROW_003)],
    }
    calls: list[str] = []

    def _fake(mutual_type: str, timeout_seconds: float):
        calls.append(mutual_type)
        outcome = outcomes[mutual_type].pop(0)
        return outcome

    monkeypatch.setattr(market_data, "_fetch_northbound_channel", _fake)
    flows = fetch_northbound_flows()
    assert [f.name for f in flows] == ["沪股通", "深股通"]  # 001 重试后成功、003 直接成功
    assert calls.count("001") == 2  # 空响应 → 至多 1 次重试
    assert calls.count("003") == 1
    assert _sleeps == [_RETRY_BACKOFF_SECONDS]  # 退避恰好 1 次


def test_fetch_channel_exception_no_retry_independent_degrade(
    _clean_cache, _sleeps, monkeypatch
) -> None:
    calls: list[str] = []
    _patch_channels(
        monkeypatch,
        {"001": OSError("network down"), "003": _payload(_ROW_003)},
        calls,
    )
    flows = fetch_northbound_flows()
    assert [f.name for f in flows] == ["深股通"]  # 单通道失败不拖垮另一通道
    assert calls.count("001") == 1  # 真异常不重试
    assert calls.count("003") == 1
    assert _sleeps == []


def test_fetch_double_empty_degrades_without_cache(
    _clean_cache, _sleeps, monkeypatch
) -> None:
    calls: list[str] = []
    _patch_channels(monkeypatch, {"001": _payload({}), "003": _payload({})}, calls)
    assert fetch_northbound_flows() == []
    assert len(calls) == 4  # 2 通道 × (1 + 1 重试)
    assert fetch_northbound_flows() == []  # 零缓存：重新外呼
    assert len(calls) == 8


def test_parse_row_without_trade_date_is_skipped(_clean_cache) -> None:
    flow = market_data._parse_northbound_flow(
        "001", "沪股通", "上证指数", {"DEAL_AMT": 1.0}, fetched_at=1.0
    )
    assert flow is None  # 缺交易日的行不造


def test_brief_reports_disclosed_only_and_honest_note(_clean_cache) -> None:
    flows = [
        NorthboundFlow(
            name="沪股通",
            mutual_type="001",
            trade_date="2026-09-11",
            deal_amt_yi=1422.5609,
            deal_num=7114374,
            lead_stock="凯盛新能",
            lead_stock_pct=9.99,
            index_name="上证指数",
            index_close=3888.11,
            index_change_pct=-1.18,
        )
    ]
    brief = format_northbound_brief(flows)
    assert "沪股通 当日成交总额 1,422.56 亿元（7,114,374 笔）" in brief
    assert "北向资金速览" in brief
    assert "不再披露北向当日净买入" in brief  # 口径诚实说明
    # 审查 Q-01：入 user_copy 池轮换（原固定「北向资金数据暂时拉不到，晚点再试试？」）。
    assert format_northbound_brief([]) in {
        template.format(reason="北向资金数据暂时拉不到")
        for template in user_copy.DATASOURCE_FAILURE_TEMPLATES
    }
