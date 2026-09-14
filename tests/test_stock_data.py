"""美股科技巨头行情数据层回归测试（全部离线，HTTP 均打桩）。

夹具取自真实探针（2026-09-12 curl 实测）：
- 东方财富 push2 ``ulist.np/get`` 美股批量快照（NVDA 行为真实截取，
  其余 8 只按同一字段形状补全成完整可解析形状）；
- push2his ``stock/kline/get`` 日 K（列序 f51..f56 = 日期,开,收,高,低,量，
  是「开收高低量」，不是 OHLC 顺序）。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from plugins.bot_unified_runtime.capabilities import user_copy
from plugins.bot_unified_runtime.contracts.finance import PricePoint, StockQuote
from plugins.bot_unified_runtime.sources import stock_data
from plugins.bot_unified_runtime.sources.stock_data import (
    fetch_stock_history,
    fetch_stock_quotes,
    format_stock_line,
    format_stocks_brief,
    is_openai_query,
    reset_stock_cache,
    reset_stock_history_cache,
    resolve_stock_symbols,
)

# ---------------------------------------------------------------------------
# 真实探针夹具
# ---------------------------------------------------------------------------

# 真实响应（push2 ulist.np/get，fltt=2）：NVDA 行为 2026-09-12 真实截取，
# 其余 8 只按同一字段形状补全（f2最新价 f3涨跌% f4涨跌额 f5量 f12代码
# f13市场号 f14中文名 f15高 f16低 f17开 f18昨收 f20总市值）。
EM_STOCK_FIXTURE: dict = {
    "rc": 0,
    "data": {
        "total": 9,
        "diff": [
            {
                "f2": 218.29,
                "f3": -0.03,
                "f4": -0.07,
                "f5": 89060140,
                "f6": 19550721280.0,
                "f12": "NVDA",
                "f13": 105,
                "f14": "英伟达",
                "f15": 222.0,
                "f16": 218.15,
                "f17": 221.235,
                "f18": 218.36,
                "f20": 5260789000000,
            },
            {
                "f2": 245.12,
                "f3": 1.85,
                "f4": 4.45,
                "f5": 42310000,
                "f6": 10250000000.0,
                "f12": "AMD",
                "f13": 105,
                "f14": "超威半导体",
                "f15": 246.0,
                "f16": 240.1,
                "f17": 241.0,
                "f18": 240.67,
                "f20": 397000000000,
            },
            {
                "f2": 40.15,
                "f3": -1.2,
                "f4": -0.49,
                "f5": 55100000,
                "f6": 2200000000.0,
                "f12": "INTC",
                "f13": 105,
                "f14": "英特尔",
                "f15": 40.9,
                "f16": 39.8,
                "f17": 40.6,
                "f18": 40.64,
                "f20": 173000000000,
            },
            {
                "f2": 262.5,
                "f3": 0.62,
                "f4": 1.62,
                "f5": 38900000,
                "f6": 10100000000.0,
                "f12": "AAPL",
                "f13": 105,
                "f14": "苹果",
                "f15": 263.0,
                "f16": 260.5,
                "f17": 261.0,
                "f18": 260.88,
                "f20": 3890000000000,
            },
            {
                "f2": 505.3,
                "f3": -0.45,
                "f4": -2.29,
                "f5": 21100000,
                "f6": 10700000000.0,
                "f12": "MSFT",
                "f13": 105,
                "f14": "微软",
                "f15": 509.0,
                "f16": 504.1,
                "f17": 508.0,
                "f18": 507.59,
                "f20": 3760000000000,
            },
            {
                "f2": 245.9,
                "f3": 0.31,
                "f4": 0.76,
                "f5": 25400000,
                "f6": 6200000000.0,
                "f12": "GOOGL",
                "f13": 105,
                "f14": "谷歌-A",
                "f15": 246.5,
                "f16": 244.2,
                "f17": 245.0,
                "f18": 245.14,
                "f20": 2980000000000,
            },
            {
                "f2": 232.4,
                "f3": -0.88,
                "f4": -2.06,
                "f5": 31200000,
                "f6": 7300000000.0,
                "f12": "AMZN",
                "f13": 105,
                "f14": "亚马逊",
                "f15": 235.0,
                "f16": 231.9,
                "f17": 234.6,
                "f18": 234.46,
                "f20": 2460000000000,
            },
            {
                "f2": 715.6,
                "f3": 0.24,
                "f4": 1.71,
                "f5": 9800000,
                "f6": 7000000000.0,
                "f12": "META",
                "f13": 105,
                "f14": "Meta Platforms Inc-A",
                "f15": 718.0,
                "f16": 712.3,
                "f17": 714.0,
                "f18": 713.89,
                "f20": 1810000000000,
            },
            {
                "f2": 288.75,
                "f3": 0.52,
                "f4": 1.49,
                "f5": 14300000,
                "f6": 4100000000.0,
                "f12": "TSM",
                "f13": 106,
                "f14": "台积电",
                "f15": 289.5,
                "f16": 286.8,
                "f17": 287.3,
                "f18": 287.26,
                "f20": 1490000000000,
            },
        ],
    },
}

# 真实响应（push2his stock/kline/get）：末行为 2026-09-12 真实截取。
KLINE_FIXTURE: dict = {
    "data": {
        "code": "NVDA",
        "market": 105,
        "name": "英伟达",
        "klines": [
            "2026-09-03,220.000,219.500,221.200,218.900,75123456",
            "2026-09-04,219.600,221.100,221.800,219.000,68000000",
            "2026-09-08,221.500,224.000,224.500,221.000,70123456",
            "2026-09-09,225.025,223.420,225.930,223.210,82955478",
        ],
    }
}

# 缺数/坏行夹具：f2="-"、缺 f2、f3="-" 的行必须整行丢弃；f4/高低缺失容忍为 None。
BROKEN_STOCK_FIXTURE: dict = {
    "data": {
        "diff": [
            {"f2": "-", "f3": -0.5, "f12": "NVDA", "f14": "英伟达"},
            {"f3": 1.0, "f12": "AMD", "f14": "超威半导体"},
            {"f2": 100.0, "f3": "-", "f12": "INTC", "f14": "英特尔"},
            {"f2": 218.29, "f3": -0.03, "f4": None, "f12": "AAPL", "f14": "苹果"},
            {"f2": 505.3, "f3": -0.45, "f12": "MSFT", "f14": "微软"},
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
    reset_stock_cache()
    reset_stock_history_cache()
    yield
    reset_stock_cache()
    reset_stock_history_cache()


# ---------------------------------------------------------------------------
# 快照解析：真实夹具 / 缺数跳过 / 失败降级
# ---------------------------------------------------------------------------


def test_parse_quotes_from_real_fixture(_clean_cache, monkeypatch) -> None:
    monkeypatch.setattr(stock_data, "_fetch_payload", lambda secids, timeout: EM_STOCK_FIXTURE)
    quotes = fetch_stock_quotes()
    assert len(quotes) == 9
    # 宇宙表顺序：NVDA 打头，TSM 收尾。
    assert [q.symbol for q in quotes] == [
        "NVDA", "AMD", "INTC", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSM",
    ]
    nvda = quotes[0]
    assert nvda.close == 218.29
    assert nvda.change_percent == -0.03
    assert nvda.change == -0.07
    assert nvda.open == 221.235
    assert nvda.high == 222.0
    assert nvda.low == 218.15
    assert nvda.previous_close == 218.36
    assert nvda.volume == 89060140.0
    assert nvda.market_cap == 5260789000000.0
    assert nvda.display_name == "英伟达"
    assert nvda.market == "NASDAQ"
    assert nvda.currency == "USD"
    assert nvda.source == "eastmoney"
    assert nvda.delayed is True
    assert nvda.timestamp  # 抓取时间非空
    assert nvda.history == ()
    # TSM 的市场号 f13=106 → NYSE。
    tsm = quotes[-1]
    assert tsm.symbol == "TSM"
    assert tsm.market == "NYSE"
    assert tsm.display_name == "台积电"


def test_quote_rows_with_missing_values_skipped(_clean_cache, monkeypatch) -> None:
    monkeypatch.setattr(stock_data, "_fetch_payload", lambda secids, timeout: BROKEN_STOCK_FIXTURE)
    quotes = fetch_stock_quotes()
    # f2="-"、缺 f2、f3="-" 的行整行丢弃；f4 缺失只影响涨跌额（None 可容忍）。
    assert [q.symbol for q in quotes] == ["AAPL", "MSFT"]
    assert quotes[0].change is None
    assert quotes[0].close == 218.29
    assert quotes[1].high is None
    assert quotes[1].low is None


def test_fetch_failure_returns_empty_never_raises(_clean_cache, monkeypatch) -> None:
    def _boom(secids: str, timeout: float) -> dict:
        raise OSError("network down")

    monkeypatch.setattr(stock_data, "_fetch_payload", _boom)
    assert fetch_stock_quotes() == []
    # 非法载荷（非 dict / 缺 data）同样安全降级。
    monkeypatch.setattr(stock_data, "_fetch_payload", lambda secids, timeout: None)
    assert fetch_stock_quotes() == []
    monkeypatch.setattr(stock_data, "_fetch_payload", lambda secids, timeout: {"data": None})
    assert fetch_stock_quotes() == []


def test_fetch_stock_quotes_subset_keeps_universe_order(_clean_cache, monkeypatch) -> None:
    calls: list[str] = []

    def _fake(secids: str, timeout: float) -> dict:
        calls.append(secids)
        return EM_STOCK_FIXTURE

    monkeypatch.setattr(stock_data, "_fetch_payload", _fake)
    quotes = fetch_stock_quotes(symbols=["TSM", "NVDA"])
    # 请求顺序不影响返回：始终按宇宙表顺序。
    assert [q.symbol for q in quotes] == ["NVDA", "TSM"]
    # 未知 symbol 过滤后为空 / 空入参 → 直接空列表，不发起外呼。
    assert fetch_stock_quotes(symbols=["FAKE"]) == []
    assert fetch_stock_quotes(symbols=[]) == []
    assert len(calls) == 1


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
        return EM_STOCK_FIXTURE

    monkeypatch.setattr(stock_data.time, "monotonic", clock)
    monkeypatch.setattr(stock_data, "_fetch_payload", _fake)

    assert len(fetch_stock_quotes(cache_seconds=60)) == 9
    clock.now = 1030.0  # TTL 内 → 子集请求也命中缓存，不再外呼。
    subset = fetch_stock_quotes(symbols=["AAPL"], cache_seconds=60)
    assert [q.symbol for q in subset] == ["AAPL"]
    assert len(calls) == 1
    clock.now = 1061.0  # TTL 过期 → 重新拉取。
    assert len(fetch_stock_quotes(cache_seconds=60)) == 9
    assert len(calls) == 2
    clock.now = 1122.0  # 再次过期 → 这次外呼失败 → 返回空且不缓存。
    assert fetch_stock_quotes(cache_seconds=60) == []
    assert len(calls) == 3
    # 失败未污染缓存：立即重试成功并重建缓存。
    assert len(fetch_stock_quotes(cache_seconds=60)) == 9
    assert len(calls) == 4
    clock.now = 1170.0  # TTL 内（48s）→ 命中缓存，不再外呼。
    assert len(fetch_stock_quotes(cache_seconds=60)) == 9
    assert len(calls) == 4
    reset_stock_cache()


# ---------------------------------------------------------------------------
# 日 K：列序（开收高低量）/ days 截断 / 未知 symbol / 失败降级
# ---------------------------------------------------------------------------


def test_fetch_stock_history_column_order(_clean_cache, monkeypatch) -> None:
    monkeypatch.setattr(stock_data, "_fetch_kline_payload", lambda ticker, days, timeout: KLINE_FIXTURE)
    points = fetch_stock_history("NVDA")
    assert len(points) == 4
    # 真实行 "2026-09-09,225.025,223.420,225.930,223.210,82955478"：
    # 列序是 日期,开,收,高,低,量。
    assert points[-1] == PricePoint(
        date="2026-09-09",
        open=225.025,
        high=225.930,
        low=223.210,
        close=223.420,
        volume=82955478.0,
    )
    assert points[0].date == "2026-09-03"
    assert points[0].close == 219.500


def test_fetch_stock_history_tolerates_missing_volume(_clean_cache, monkeypatch) -> None:
    broken_kline = {
        "data": {
            "klines": [
                "2026-09-09,225.025,223.420,225.930,223.210,-",  # 量缺数 → None
                "2026-09-10,224.0,223.0,224.5,222.5",  # 只有 5 列 → 量 None
                "2026-09-11,bad,row",  # 列数不足 → 整行丢弃
            ]
        }
    }
    monkeypatch.setattr(stock_data, "_fetch_kline_payload", lambda ticker, days, timeout: broken_kline)
    points = fetch_stock_history("NVDA")
    assert [p.date for p in points] == ["2026-09-09", "2026-09-10"]
    assert points[0].volume is None
    assert points[1].volume is None


def test_fetch_stock_history_days_truncation(_clean_cache, monkeypatch) -> None:
    monkeypatch.setattr(stock_data, "_fetch_kline_payload", lambda ticker, days, timeout: KLINE_FIXTURE)
    points = fetch_stock_history("NVDA", days=2)
    # 截断保留最近的 N 根。
    assert [p.date for p in points] == ["2026-09-08", "2026-09-09"]
    assert len(fetch_stock_history("NVDA", days=30)) == 4


def test_fetch_stock_history_unknown_symbol_skips_network(_clean_cache, monkeypatch) -> None:
    calls: list[str] = []

    def _spy(ticker: str, days: int, timeout: float) -> dict:
        calls.append(ticker)
        return KLINE_FIXTURE

    monkeypatch.setattr(stock_data, "_fetch_kline_payload", _spy)
    assert fetch_stock_history("OPENAI") == ()
    assert fetch_stock_history("") == ()
    assert calls == []


def test_fetch_stock_history_failure_returns_empty_and_not_cached(
    _clean_cache, monkeypatch
) -> None:
    calls: list[int] = []

    def _flaky(ticker: str, days: int, timeout: float) -> dict:
        calls.append(1)
        raise OSError("kline down")

    monkeypatch.setattr(stock_data, "_fetch_kline_payload", _flaky)
    assert fetch_stock_history("NVDA") == ()
    # 失败未缓存：换上正常桩立即重试就能拉到。
    monkeypatch.setattr(stock_data, "_fetch_kline_payload", lambda ticker, days, timeout: KLINE_FIXTURE)
    assert len(fetch_stock_history("NVDA")) == 4
    assert len(calls) == 1


def test_fetch_stock_history_cache_ttl(_clean_cache, monkeypatch) -> None:
    clock = _Clock()
    calls: list[int] = []

    def _fake(ticker: str, days: int, timeout: float) -> dict:
        calls.append(1)
        return KLINE_FIXTURE

    monkeypatch.setattr(stock_data.time, "monotonic", clock)
    monkeypatch.setattr(stock_data, "_fetch_kline_payload", _fake)
    assert len(fetch_stock_history("NVDA", cache_seconds=600)) == 4
    clock.now = 1300.0  # TTL 内 → 命中缓存。
    assert len(fetch_stock_history("NVDA", cache_seconds=600)) == 4
    assert len(calls) == 1
    clock.now = 1601.0  # 过期 → 重拉。
    assert len(fetch_stock_history("NVDA", cache_seconds=600)) == 4
    assert len(calls) == 2
    reset_stock_history_cache()


# ---------------------------------------------------------------------------
# 代码解析 / OpenAI 非上市公司兜底
# ---------------------------------------------------------------------------


def test_stock_universe_shape() -> None:
    assert len(stock_data._STOCK_UNIVERSE) == 9
    tsm = [row for row in stock_data._STOCK_UNIVERSE if row[1] == "TSM"]
    assert tsm == [("106.TSM", "TSM", "台积电", "NYSE", "USD")]
    nvda = [row for row in stock_data._STOCK_UNIVERSE if row[1] == "NVDA"]
    assert nvda == [("105.NVDA", "NVDA", "英伟达", "NASDAQ", "USD")]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("英伟达涨了吗", ["NVDA"]),
        ("nvda 业绩怎么样", ["NVDA"]),
        ("amd 财报出了", ["AMD"]),
        ("苹果和微软哪个好", ["AAPL", "MSFT"]),
        ("台积电 ADR 走势", ["TSM"]),
        ("英伟达和amd都涨了", ["NVDA", "AMD"]),  # CJK 相邻英文也能命中
        ("买点INTC", ["INTC"]),  # CJK 紧贴代码
        ("看看meta", ["META"]),
        ("NVDAX 不该命中", []),
        ("今天天气不错", []),
        ("美股行情", []),
    ],
)
def test_resolve_stock_symbols_matrix(text: str, expected: list[str]) -> None:
    assert resolve_stock_symbols(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        # 词边界回归（评审 B2）：ASCII 别名不得做纯子串误命中。
        ("metaverse 是什么", None),  # "meta" 不命中 "metaverse"
        ("metadata 解析", None),  # "meta" 不命中 "metadata"
        ("聊聊amd64架构", None),  # "amd" 不命中 "amd64"（后随数字）
        # 独立词照常命中。
        ("meta 股价", "META"),
        ("amd 股价", "AMD"),
        ("看看AMD行情", "AMD"),  # CJK 相邻也算词边界
        ("openai 值多少钱", "OPENAI"),
        # 中文别名保持子串语义。
        ("英伟达股价多少", "NVDA"),
        ("帮我看看超威", "AMD"),
        ("今天天气如何", None),
    ],
)
def test_resolve_company_query_word_boundary(text: str, expected: str | None) -> None:
    """resolve_company_query 与 resolve_stock_symbols 同一套词边界口径：
    ASCII 别名走词边界（防 metadata 误中 meta），中文别名保持子串。"""
    assert stock_data.resolve_company_query(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("OpenAI 值多少钱", True),
        ("openai 最新估值", True),
        ("OPENAI", True),
        ("开放AI", False),
        ("苹果发布会", False),
    ],
)
def test_is_openai_query(text: str, expected: bool) -> None:
    assert is_openai_query(text) is expected


def test_openai_non_public_record() -> None:
    record = stock_data._OPENAI_RECORD
    assert record.name == "OpenAI"
    assert record.symbol == ""  # 无公开代码
    assert "openai" in record.aliases
    assert record.reason  # 说明非空
    assert "非上市" in record.reason
    # 唯一口径：官方融资公告（2026-03-31）投后 8520 亿美元，与
    # NON_PUBLIC_EQUITIES 的 provenance 记录一致，禁止第二套数字。
    assert "8520" in record.valuation_text
    assert record.valuation_source == "OpenAI 官方融资公告（2026-03-31）"
    assert record.valuation_date == "2026-03"
    provenance = stock_data.NON_PUBLIC_EQUITIES["OPENAI"]
    assert provenance.valuation_usd == 852_000_000_000.0
    assert provenance.valuation_as_of.isoformat() == "2026-03-31"


# ---------------------------------------------------------------------------
# 文案格式化：🔴涨🟢跌⚪平 / 带符号百分比 / 涨跌额括注 / 市值人性化
# ---------------------------------------------------------------------------


def _nvda_quote() -> StockQuote:
    return StockQuote(
        symbol="NVDA",
        display_name="英伟达",
        market="NASDAQ",
        currency="USD",
        timestamp="2026-09-12 10:00:00",
        source="eastmoney",
        delayed=True,
        open=221.235,
        high=222.0,
        low=218.15,
        close=218.29,
        previous_close=218.36,
        change=-0.07,
        change_percent=-0.03,
        volume=89060140.0,
        market_cap=5260789000000.0,
    )


def test_format_stock_line_down_with_market_cap() -> None:
    assert format_stock_line(_nvda_quote()) == (
        "🟢 英伟达 218.29 -0.03%（-0.07）· 市值 5.26万亿美元"
    )


def test_format_stock_line_up_and_flat() -> None:
    up = StockQuote(
        symbol="AMD",
        display_name="超威半导体",
        market="NASDAQ",
        currency="USD",
        timestamp="t",
        source="eastmoney",
        delayed=True,
        close=245.12,
        change=4.45,
        change_percent=1.85,
    )
    assert format_stock_line(up) == "🔴 超威半导体 245.12 +1.85%（+4.45）"
    flat = StockQuote(
        symbol="INTC",
        display_name="英特尔",
        market="NASDAQ",
        currency="USD",
        timestamp="t",
        source="eastmoney",
        delayed=True,
        close=40.15,
        change=0.0,
        change_percent=0.0,
    )
    assert format_stock_line(flat) == "⚪ 英特尔 40.15 0.00%（0.00）"


def test_format_stock_line_without_change_and_cap() -> None:
    minimal = StockQuote(
        symbol="AAPL",
        display_name="苹果",
        market="NASDAQ",
        currency="USD",
        timestamp="t",
        source="eastmoney",
        delayed=True,
        close=262.5,
    )
    # 涨跌缺失不伪造 0.00%，诚实显示占位符。
    assert format_stock_line(minimal) == "⚪ 苹果 -"


def test_format_stocks_brief_and_empty_degrades() -> None:
    text = format_stocks_brief([_nvda_quote()])
    assert text.splitlines()[0] == "美股科技巨头速览"
    assert "🟢 英伟达 218.29 -0.03%（-0.07）· 市值 5.26万亿美元" in text
    # 审查 Q-01：入 user_copy 池轮换（原固定「美股行情暂时拉不到，晚点再试试？」）。
    assert format_stocks_brief([]) in {
        template.format(reason="美股行情暂时拉不到")
        for template in user_copy.DATASOURCE_FAILURE_TEMPLATES
    }
