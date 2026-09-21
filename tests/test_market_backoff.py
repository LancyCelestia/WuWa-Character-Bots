"""东财空响应受控重试回归（G2 修复，2026-09-13，全部离线）。

东财限流表现为 HTTP 200 但业务体为空（空 JSON/缺行，无错误码），与真异常
（网络错/非 200 → ParseHttpError）不同，值得退避后再试一次。本文件锁定
三源（market_data / stock_data / fx_data）东财取数的统一纪律：

- 空响应 → 至多 1 次重试，退避 0.6s（time.sleep 单点，全程被 patch）；
- 双空 → 现有诚实降级（空列表/空元组）且不进任何缓存（零缓存纪律）；
- 开关关（BOT_MARKET_RETRY_ON_EMPTY=0）→ 行为与既往逐字节一致（调 1 次）；
- 真异常（网络错/非 200）→ 绝不重试（调 1 次）。

全部离线：网络出口 monkeypatch 单点拦截；time.sleep 替换为记录器，
测试永不真实等待。重试开关解析链（driver config → env → 默认）中，
单元测试环境 nonebot 未初始化自动短路到 env 层，monkeypatch.setenv 即可
确定性地控制开关。
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest

from plugins.bot_unified_runtime.domains.finance.data import (
    fx_data,
    market_data,
    stock_data,
)
from plugins.bot_unified_runtime.domains.finance.data.market_data import (
    _RETRY_BACKOFF_SECONDS,
    retry_on_empty_enabled,
)

# ---------------------------------------------------------------------------
# 最小可解析夹具（东财 fltt=2 字段口径，与既有测试文件同款形状）
# ---------------------------------------------------------------------------

# ulist 批量快照：单行即可触发「有数据」。
_MARKET_ROW: dict = {
    "data": {
        "diff": [
            {"f2": 3934.4, "f3": -0.43, "f4": -17.11, "f12": "000001", "f14": "上证指数"}
        ]
    }
}
_STOCK_ROW: dict = {
    "data": {
        "diff": [
            {"f2": 218.29, "f3": -0.03, "f4": -0.07, "f12": "NVDA", "f14": "英伟达"}
        ]
    }
}
_FX_ROW: dict = {
    "data": {
        "diff": [
            {
                "f2": 6.7081,
                "f3": -0.1,
                "f4": -0.0066,
                "f12": "USDCNH",
                "f14": "美元兑离岸人民币",
            }
        ]
    }
}
# kline：指数走势 fields2=f51,f53 → "日期,收盘"；个股 f51..f56 → 日期,开,收,高,低,量。
_MARKET_TREND: dict = {
    "data": {"klines": ["2026-09-11,3934.40", "2026-09-12,3950.00"]}
}
_STOCK_KLINE: dict = {
    "data": {"klines": ["2026-09-11,218.0,218.29,219.0,217.5,89060140"]}
}
# 空 JSON：限流时 HTTP 200 的真实形态（缺行同口径，解析后皆为空）。
_EMPTY: dict = {}


# ---------------------------------------------------------------------------
# 夹具：缓存清空 + sleep 记录器（永不真实等待）
# ---------------------------------------------------------------------------


@pytest.fixture()
def _clean_caches() -> Iterator[None]:
    market_data.reset_market_cache()
    market_data.reset_market_trend_cache()
    stock_data.reset_stock_cache()
    stock_data.reset_stock_history_cache()
    fx_data.reset_fx_cache()
    yield
    market_data.reset_market_cache()
    market_data.reset_market_trend_cache()
    stock_data.reset_stock_cache()
    stock_data.reset_stock_history_cache()
    fx_data.reset_fx_cache()


@pytest.fixture()
def _sleeps(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[float]]:
    """把 time.sleep 替换为记录器：断言退避次数与时长，且零真实等待。"""
    recorded: list[float] = []

    def _record(seconds: float) -> None:
        recorded.append(float(seconds))

    monkeypatch.setattr(time, "sleep", _record)
    yield recorded


# ---------------------------------------------------------------------------
# 开关解析链（config → env → 默认；单测环境 driver 未初始化短路到 env）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, True),
        ("", True),
        ("0", False),
        ("false", False),
        ("False", False),
        ("no", False),
        ("off", False),
        ("1", True),
        ("true", True),
        ("yes", True),
        ("on", True),
        ("garbage", True),
    ],
)
def test_retry_switch_env_semantics(
    monkeypatch: pytest.MonkeyPatch, raw: str | None, expected: bool
) -> None:
    if raw is None:
        monkeypatch.delenv("BOT_MARKET_RETRY_ON_EMPTY", raising=False)
    else:
        monkeypatch.setenv("BOT_MARKET_RETRY_ON_EMPTY", raw)
    assert retry_on_empty_enabled() is expected


# ---------------------------------------------------------------------------
# market_data：指数快照批量 ulist + 指数走势 kline
# ---------------------------------------------------------------------------


def test_market_index_quotes_empty_then_data_two_calls(
    _clean_caches, _sleeps, monkeypatch
) -> None:
    payloads: list[dict] = [dict(_EMPTY), dict(_MARKET_ROW)]
    calls: list[str] = []

    def _fake(secids: str, timeout: float) -> dict:
        calls.append(secids)
        return payloads.pop(0)

    monkeypatch.setattr(market_data, "_fetch_payload", _fake)
    monkeypatch.setattr(market_data, "_fetch_moex_quote", lambda timeout: None)
    quotes = market_data.fetch_index_quotes()
    assert len(calls) == 2  # 空响应 → 至多 1 次重试
    assert len(quotes) == 1
    assert quotes[0].code == "1.000001"
    assert _sleeps == [_RETRY_BACKOFF_SECONDS]  # 退避恰好 1 次、0.6s


def test_market_index_quotes_double_empty_degrades_without_cache(
    _clean_caches, _sleeps, monkeypatch
) -> None:
    calls: list[str] = []

    def _fake(secids: str, timeout: float) -> dict:
        calls.append(secids)
        return dict(_EMPTY)

    monkeypatch.setattr(market_data, "_fetch_payload", _fake)
    monkeypatch.setattr(market_data, "_fetch_moex_quote", lambda timeout: None)
    assert market_data.fetch_index_quotes() == []  # 现有诚实降级不变
    assert len(calls) == 2
    assert _sleeps == [_RETRY_BACKOFF_SECONDS]
    # 零缓存：紧接的第二次调用重新外呼（失败不缓存纪律不因重试而破坏）。
    assert market_data.fetch_index_quotes() == []
    assert len(calls) == 4


def test_market_index_quotes_retry_disabled_single_call(
    _clean_caches, _sleeps, monkeypatch
) -> None:
    monkeypatch.setenv("BOT_MARKET_RETRY_ON_EMPTY", "0")
    calls: list[str] = []

    def _fake(secids: str, timeout: float) -> dict:
        calls.append(secids)
        return dict(_EMPTY)

    monkeypatch.setattr(market_data, "_fetch_payload", _fake)
    monkeypatch.setattr(market_data, "_fetch_moex_quote", lambda timeout: None)
    assert market_data.fetch_index_quotes() == []
    assert len(calls) == 1  # 开关关：与既往行为逐字节一致
    assert _sleeps == []


def test_market_index_quotes_exception_no_retry(
    _clean_caches, _sleeps, monkeypatch
) -> None:
    calls: list[str] = []

    def _boom(secids: str, timeout: float) -> dict:
        calls.append(secids)
        raise OSError("network down")

    monkeypatch.setattr(market_data, "_fetch_payload", _boom)
    monkeypatch.setattr(market_data, "_fetch_moex_quote", lambda timeout: None)
    assert market_data.fetch_index_quotes() == []
    assert len(calls) == 1  # 真异常（网络错）不重试
    assert _sleeps == []


def test_market_index_trend_empty_then_data_two_calls(
    _clean_caches, _sleeps, monkeypatch
) -> None:
    payloads: list[dict] = [dict(_EMPTY), dict(_MARKET_TREND)]
    calls: list[str] = []

    def _fake(url: str, **kwargs: object) -> dict:
        calls.append(url)
        return payloads.pop(0)

    monkeypatch.setattr(market_data, "http_get_json", _fake)
    closes = market_data.fetch_index_trend("1.000001")
    assert len(calls) == 2
    assert closes == (3934.40, 3950.00)
    assert _sleeps == [_RETRY_BACKOFF_SECONDS]


def test_market_index_trend_double_empty_no_cache(
    _clean_caches, _sleeps, monkeypatch
) -> None:
    calls: list[str] = []

    def _fake(url: str, **kwargs: object) -> dict:
        calls.append(url)
        return dict(_EMPTY)

    monkeypatch.setattr(market_data, "http_get_json", _fake)
    assert market_data.fetch_index_trend("1.000001") == ()
    assert len(calls) == 2
    assert market_data.fetch_index_trend("1.000001") == ()  # 未被钉进 10 分钟缓存
    assert len(calls) == 4


# ---------------------------------------------------------------------------
# stock_data：批量快照 / 单只快照（缺行）/ 日 K
# ---------------------------------------------------------------------------


def test_stock_quotes_empty_then_data_two_calls(
    _clean_caches, _sleeps, monkeypatch
) -> None:
    payloads: list[dict] = [dict(_EMPTY), dict(_STOCK_ROW)]
    calls: list[str] = []

    def _fake(secids: str, timeout: float) -> dict:
        calls.append(secids)
        return payloads.pop(0)

    monkeypatch.setattr(stock_data, "_fetch_payload", _fake)
    quotes = stock_data.fetch_stock_quotes()
    assert len(calls) == 2
    assert [q.symbol for q in quotes] == ["NVDA"]
    assert _sleeps == [_RETRY_BACKOFF_SECONDS]


def test_stock_quotes_double_empty_no_cache(
    _clean_caches, _sleeps, monkeypatch
) -> None:
    calls: list[str] = []

    def _fake(secids: str, timeout: float) -> dict:
        calls.append(secids)
        return dict(_EMPTY)

    monkeypatch.setattr(stock_data, "_fetch_payload", _fake)
    assert stock_data.fetch_stock_quotes() == []
    assert len(calls) == 2
    assert stock_data.fetch_stock_quotes() == []
    assert len(calls) == 4  # 双空零缓存：每次调用都真的重新外呼


def test_stock_quotes_retry_disabled_single_call(
    _clean_caches, _sleeps, monkeypatch
) -> None:
    monkeypatch.setenv("BOT_MARKET_RETRY_ON_EMPTY", "0")
    calls: list[str] = []

    def _fake(secids: str, timeout: float) -> dict:
        calls.append(secids)
        return dict(_EMPTY)

    monkeypatch.setattr(stock_data, "_fetch_payload", _fake)
    assert stock_data.fetch_stock_quotes() == []
    assert len(calls) == 1
    assert _sleeps == []


def test_stock_quotes_exception_single_call(
    _clean_caches, _sleeps, monkeypatch
) -> None:
    calls: list[str] = []

    def _boom(secids: str, timeout: float) -> dict:
        calls.append(secids)
        raise OSError("network down")

    monkeypatch.setattr(stock_data, "_fetch_payload", _boom)
    assert stock_data.fetch_stock_quotes() == []
    assert len(calls) == 1
    assert _sleeps == []


def test_stock_quote_missing_row_then_data_two_calls(
    _clean_caches, _sleeps, monkeypatch
) -> None:
    """单 secid 请求的「缺行」同样是空响应签名：退避重试一次。"""
    payloads: list[dict] = [dict(_EMPTY), dict(_STOCK_ROW)]
    calls: list[str] = []

    def _fake(ticker: str, timeout: float) -> dict:
        calls.append(ticker)
        return payloads.pop(0)

    monkeypatch.setattr(stock_data, "_fetch_quote_payload", _fake)
    quote = stock_data.fetch_stock_quote("NVDA")
    assert len(calls) == 2
    assert quote.price is not None
    assert quote.status.value == "ok"


def test_stock_history_empty_then_data_two_calls(
    _clean_caches, _sleeps, monkeypatch
) -> None:
    payloads: list[dict] = [dict(_EMPTY), dict(_STOCK_KLINE)]
    calls: list[str] = []

    def _fake(ticker: str, days: int, timeout: float) -> dict:
        calls.append(ticker)
        return payloads.pop(0)

    monkeypatch.setattr(stock_data, "_fetch_kline_payload", _fake)
    points = stock_data.fetch_stock_history("NVDA")
    assert len(calls) == 2
    assert len(points) == 1
    assert _sleeps == [_RETRY_BACKOFF_SECONDS]


def test_stock_history_double_empty_no_cache(
    _clean_caches, _sleeps, monkeypatch
) -> None:
    calls: list[str] = []

    def _fake(ticker: str, days: int, timeout: float) -> dict:
        calls.append(ticker)
        return dict(_EMPTY)

    monkeypatch.setattr(stock_data, "_fetch_kline_payload", _fake)
    assert stock_data.fetch_stock_history("NVDA") == ()
    assert len(calls) == 2
    assert stock_data.fetch_stock_history("NVDA") == ()
    assert len(calls) == 4


# ---------------------------------------------------------------------------
# fx_data：东财批量 ulist（仅东财主源；er-api 快照链路不在本文件重试范围）
# ---------------------------------------------------------------------------


def test_fx_rates_empty_then_data_two_calls(
    _clean_caches, _sleeps, monkeypatch
) -> None:
    payloads: list[dict] = [dict(_EMPTY), dict(_FX_ROW)]
    calls: list[str] = []

    def _fake(secids: str, timeout: float) -> dict:
        calls.append(secids)
        return payloads.pop(0)

    monkeypatch.setattr(fx_data, "_fetch_payload", _fake)
    rates = fx_data.fetch_fx_rates()
    assert len(calls) == 2
    assert [f"{r.base_currency}/{r.quote_currency}" for r in rates] == ["USD/CNY"]
    assert _sleeps == [_RETRY_BACKOFF_SECONDS]


def test_fx_rates_double_empty_no_cache(
    _clean_caches, _sleeps, monkeypatch
) -> None:
    calls: list[str] = []

    def _fake(secids: str, timeout: float) -> dict:
        calls.append(secids)
        return dict(_EMPTY)

    monkeypatch.setattr(fx_data, "_fetch_payload", _fake)
    assert fx_data.fetch_fx_rates() == []
    assert len(calls) == 2
    assert fx_data.fetch_fx_rates() == []
    assert len(calls) == 4


def test_fx_rates_retry_disabled_single_call(
    _clean_caches, _sleeps, monkeypatch
) -> None:
    monkeypatch.setenv("BOT_MARKET_RETRY_ON_EMPTY", "0")
    calls: list[str] = []

    def _fake(secids: str, timeout: float) -> dict:
        calls.append(secids)
        return dict(_EMPTY)

    monkeypatch.setattr(fx_data, "_fetch_payload", _fake)
    assert fx_data.fetch_fx_rates() == []
    assert len(calls) == 1
    assert _sleeps == []


def test_fx_rates_exception_single_call(
    _clean_caches, _sleeps, monkeypatch
) -> None:
    calls: list[str] = []

    def _boom(secids: str, timeout: float) -> dict:
        calls.append(secids)
        raise OSError("network down")

    monkeypatch.setattr(fx_data, "_fetch_payload", _boom)
    assert fx_data.fetch_fx_rates() == []
    assert len(calls) == 1
    assert _sleeps == []
