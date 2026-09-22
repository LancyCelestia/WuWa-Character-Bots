"""大宗商品数据源回归（金融 Phase-1 扩容 2026-09-13，全离线）。

锁定 sources/commodities_data.py 的四条纪律（与 market/fx/stock 同款）：
1. 批量快照：宇宙表顺序解析 + 缺行跳过 + URL 载荷含全部 secid；
2. G2 空响应重试：空→退避重试 1 次（0.6s 单点）、双空诚实降级且零缓存、
   真异常不重试、开关关（BOT_MARKET_RETRY_ON_EMPTY=0）只调 1 次；
3. 走势：push2his 瞬断（ParseHttpError）按 vis3 语义退避重试、空不缓存；
4. 覆盖表诚实登记：LME 铜/Brent 无源显式 unavailable，绝不冒充。
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest

from plugins.bot_unified_runtime.capabilities import user_copy
from plugins.bot_unified_runtime.domains.finance.data import commodities_data
from plugins.bot_unified_runtime.domains.finance.data.commodities_data import (
    commodity_availability,
    fetch_commodity_quotes,
    fetch_commodity_trend,
    format_commodities_brief,
    format_commodity_line,
    group_commodity_quotes,
    reset_commodities_cache,
    reset_commodities_trend_cache,
)
from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
    ParseHttpError,
)

# 实测字段口径（2026-09-13 ulist 探针值）：GC 4390/-0.39/-17.3、SI 65.02、
# HG 6.557（三位精度量级）、CL 99.99/-2.43/-2.49。
_PAYLOAD: dict = {
    "data": {
        "diff": [
            {"f2": 4390.0, "f3": -0.39, "f4": -17.3, "f12": "GC00Y", "f13": 101, "f14": "COMEX黄金"},
            {"f2": 65.02, "f3": 0.14, "f4": 0.093, "f12": "SI00Y", "f13": 101, "f14": "COMEX白银"},
            {"f2": 6.557, "f3": 0.15, "f4": 0.0095, "f12": "HG00Y", "f13": 101, "f14": "COMEX铜"},
            {"f2": 99.99, "f3": -2.43, "f4": -2.49, "f12": "CL00Y", "f13": 102, "f14": "NYMEX原油"},
        ]
    }
}
_EMPTY: dict = {}
_TREND: dict = {
    "data": {"klines": ["2026-09-10,4400.1", "2026-09-11,4390.0"]}
}


@pytest.fixture()
def _clean_caches() -> Iterator[None]:
    reset_commodities_cache()
    reset_commodities_trend_cache()
    yield
    reset_commodities_cache()
    reset_commodities_trend_cache()


@pytest.fixture()
def _sleeps(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[float]]:
    recorded: list[float] = []

    def _record(seconds: float) -> None:
        recorded.append(float(seconds))

    monkeypatch.setattr(time, "sleep", _record)
    yield recorded


# ---------------------------------------------------------------------------
# 解析与格式（纯离线）
# ---------------------------------------------------------------------------


def test_parse_quotes_universe_order_and_fields(_clean_caches) -> None:
    quotes = commodities_data._parse_quotes(_PAYLOAD)
    assert [q.code for q in quotes] == ["101.GC00Y", "101.SI00Y", "101.HG00Y", "102.CL00Y"]
    assert [q.name for q in quotes] == ["COMEX黄金", "COMEX白银", "COMEX铜", "NYMEX原油"]
    assert quotes[0].price == 4390.0 and quotes[0].change_pct == -0.39
    assert quotes[0].change_abs == -17.3
    assert quotes[0].unit == "美元/金衡盎司" and quotes[0].group == "贵金属"
    assert quotes[2].unit == "美元/磅" and quotes[2].group == "基本金属"
    assert quotes[3].unit == "美元/桶" and quotes[3].group == "能源"
    assert all(q.source == "eastmoney" and q.delayed for q in quotes)


def test_parse_quotes_skips_missing_row(_clean_caches) -> None:
    payload = {"data": {"diff": [_PAYLOAD["data"]["diff"][0]]}}
    quotes = commodities_data._parse_quotes(payload)
    assert [q.code for q in quotes] == ["101.GC00Y"]  # 缺行跳过，不造数


def test_format_line_and_groups_and_brief(_clean_caches) -> None:
    quotes = commodities_data._parse_quotes(_PAYLOAD)
    line = format_commodity_line(quotes[0])
    assert line.startswith("🟢 COMEX黄金 4390.00 -0.39%")  # 红涨绿跌：跌=绿
    line_cu = format_commodity_line(quotes[2])
    assert "6.557" in line_cu  # 低价量级三位精度
    grouped = group_commodity_quotes(quotes)
    assert list(grouped) == ["贵金属", "基本金属", "能源"]
    brief = format_commodities_brief(quotes)
    assert "大宗商品速览" in brief and "COMEX" in brief
    assert "LME 无稳定免费公开源" in brief  # 替代口径显式说明
    # 审查 Q-01：降级文案入 user_copy 池轮换，断言 ∈ 池渲染集合（原固定「……晚点再试试？」）。
    assert format_commodities_brief([]) in {
        template.format(reason="大宗商品行情暂时拉不到")
        for template in user_copy.DATASOURCE_FAILURE_TEMPLATES
    }


def test_availability_honest_lme_and_brent(_clean_caches) -> None:
    table = commodity_availability()
    assert table["COMEX黄金"] == "eastmoney:101.GC00Y"
    assert table["LME铜"].startswith("unavailable:")
    assert table["Brent原油"].startswith("unavailable:")


# ---------------------------------------------------------------------------
# 批量快照：G2 重试纪律 + URL 载荷
# ---------------------------------------------------------------------------


def test_quotes_success_and_url_payload(_clean_caches, _sleeps, monkeypatch) -> None:
    calls: list[str] = []

    def _fake(secids: str, timeout: float) -> dict:
        calls.append(secids)
        return dict(_PAYLOAD)

    monkeypatch.setattr(commodities_data, "_fetch_payload", _fake)
    quotes = fetch_commodity_quotes()
    assert [q.code for q in quotes] == [c for c, *_ in commodities_data._COMMODITY_UNIVERSE]
    assert calls == ["101.GC00Y,101.SI00Y,101.HG00Y,102.CL00Y"]  # 单次批量外呼
    assert _sleeps == []
    # TTL 命中：第二次调用零外呼。
    assert len(fetch_commodity_quotes()) == 4
    assert len(calls) == 1


def test_quotes_empty_then_data_two_calls(_clean_caches, _sleeps, monkeypatch) -> None:
    from plugins.bot_unified_runtime.domains.finance.data.market_data import (
        _RETRY_BACKOFF_SECONDS,
    )

    payloads: list[dict] = [dict(_EMPTY), dict(_PAYLOAD)]
    calls: list[str] = []

    def _fake(secids: str, timeout: float) -> dict:
        calls.append(secids)
        return payloads.pop(0)

    monkeypatch.setattr(commodities_data, "_fetch_payload", _fake)
    quotes = fetch_commodity_quotes()
    assert len(calls) == 2  # 空响应 → 至多 1 次重试
    assert len(quotes) == 4
    assert _sleeps == [_RETRY_BACKOFF_SECONDS]


def test_quotes_double_empty_degrades_without_cache(
    _clean_caches, _sleeps, monkeypatch
) -> None:
    calls: list[str] = []

    def _fake(secids: str, timeout: float) -> dict:
        calls.append(secids)
        return dict(_EMPTY)

    monkeypatch.setattr(commodities_data, "_fetch_payload", _fake)
    assert fetch_commodity_quotes() == []
    assert len(calls) == 2
    assert fetch_commodity_quotes() == []  # 零缓存：重新外呼
    assert len(calls) == 4


def test_quotes_exception_no_retry(_clean_caches, _sleeps, monkeypatch) -> None:
    calls: list[str] = []

    def _boom(secids: str, timeout: float) -> dict:
        calls.append(secids)
        raise OSError("network down")

    monkeypatch.setattr(commodities_data, "_fetch_payload", _boom)
    assert fetch_commodity_quotes() == []
    assert len(calls) == 1  # 真异常不重试
    assert _sleeps == []


def test_quotes_retry_disabled_single_call(
    _clean_caches, _sleeps, monkeypatch
) -> None:
    monkeypatch.setenv("BOT_MARKET_RETRY_ON_EMPTY", "0")
    calls: list[str] = []

    def _fake(secids: str, timeout: float) -> dict:
        calls.append(secids)
        return dict(_EMPTY)

    monkeypatch.setattr(commodities_data, "_fetch_payload", _fake)
    assert fetch_commodity_quotes() == []
    assert len(calls) == 1
    assert _sleeps == []


# ---------------------------------------------------------------------------
# 走势：瞬断重试（vis3 语义）+ 空响应 G2 + 零缓存
# ---------------------------------------------------------------------------


def test_trend_transient_disconnect_retried_then_success(
    _clean_caches, _sleeps, monkeypatch
) -> None:
    from plugins.bot_unified_runtime.domains.finance.data.market_data import (
        _RETRY_BACKOFF_SECONDS,
    )

    outcomes: list = [ParseHttpError("GET failed: RemoteDisconnected"), dict(_TREND)]
    calls: list[str] = []

    def _fake(url: str, **kwargs: object):
        calls.append(url)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(commodities_data, "http_get_json", _fake)
    closes = fetch_commodity_trend("101.GC00Y")
    assert closes == (4400.1, 4390.0)
    assert len(calls) == 2  # 瞬断退避重试 1 次即成功
    assert _sleeps == [_RETRY_BACKOFF_SECONDS]
    # URL 载荷：kline 接口带 end=20500101（2026-09-13 接口变更坑）与 secid。
    assert "secid=101.GC00Y" in calls[0] and "end=20500101" in calls[0]


def test_trend_double_empty_no_cache(_clean_caches, _sleeps, monkeypatch) -> None:
    calls: list[str] = []

    def _fake(url: str, **kwargs: object):
        calls.append(url)
        return dict(_EMPTY)

    monkeypatch.setattr(commodities_data, "http_get_json", _fake)
    assert fetch_commodity_trend("101.GC00Y") == ()
    assert len(calls) == 2
    assert fetch_commodity_trend("101.GC00Y") == ()  # 空/失败不缓存
    assert len(calls) == 4


def test_trend_exception_no_retry(_clean_caches, _sleeps, monkeypatch) -> None:
    calls: list[str] = []

    def _boom(url: str, **kwargs: object):
        calls.append(url)
        raise OSError("down")

    monkeypatch.setattr(commodities_data, "http_get_json", _boom)
    assert fetch_commodity_trend("101.GC00Y") == ()
    assert len(calls) == 1
    assert _sleeps == []
