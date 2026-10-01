"""金融数据能力离线回归（Task 4 / 全局审计）：契约 + 股票/汇率数据源 + 能力文本。

全部离线 fixture 驱动；网络集成测试按环境变量 ``BOT_FINANCE_NET_TESTS=1``
选择性启用（默认跳过，绝不阻塞离线全量）。

夹具结构说明（诚实边界）：
- 东财 ``push2his``/``push2`` 的**响应包络**（``data.klines`` / ``data.diff``）
  与个股 OHLCV 字段 ``f51``..``f56``（日期,开,收,高,低,量）、市值 ``f20``
  均已由主代理 2026-09-12 curl 实测核验（真实行
  ``"2026-09-09,225.025,223.420,225.930,223.210,82955478"``；
  旧惯用法 f116 实测无值已废弃）；
- 汇率备选源 ``open.er-api.com`` 在主代理环境实测不可达，快照链路测试
  全部 fixture 化；东财主源（快查链路）secid 133/119/120 已实测。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import date

import pytest
from pydantic import ValidationError

from plugins.bot_unified_runtime.domains.core.contracts.finance import (
    BoxPlotStats,
    CurrencyQuote,
    EquityQuote,
    FinanceDataStatus,
    FxRateSnapshot,
    KDJSnapshot,
    MarketCap,
    NonPublicEquityNote,
    OHLCVBar,
    OHLCVSeries,
)
from plugins.bot_unified_runtime.domains.finance.data import (
    fx_data,
    market_data,
    stock_data,
)
from plugins.bot_unified_runtime.domains.finance.data.stock_data import (
    compute_kdj,
    fetch_market_cap,
    fetch_stock_ohlcv,
    fetch_stock_quote,
    openai_equity_note,
    resolve_company_query,
)

_NET_REQUIRED = os.environ.get("BOT_FINANCE_NET_TESTS", "") != "1"
skip_network = pytest.mark.skipif(
    _NET_REQUIRED, reason="网络集成测试默认跳过（BOT_FINANCE_NET_TESTS=1 启用）"
)

# ---------------------------------------------------------------------------
# 夹具：东财 kline（个股 OHLCV，包络同 fetch_index_trend 已验证结构）
# ---------------------------------------------------------------------------

NVDA_KLINE_FIXTURE: dict = {
    "rc": 0,
    "data": {
        "name": "英伟达",
        "code": "NVDA",
        "klines": [
            "2026-09-02,175.10,178.20,179.00,174.50,22100000",
            "2026-09-03,178.40,177.90,180.20,176.00,19800000",
            "2026-09-04,177.95,181.30,182.10,177.40,21200000",
            "2026-09-05,181.55,185.60,186.20,181.00,26400000",
            "2026-09-08,185.70,184.95,187.30,183.80,23100000",
        ],
    },
}

# 混入坏行：open 非法 / 列数不足 / 整行垃圾 → 逐行跳过而非整体失败。
NVDA_KLINE_PARTIAL_FIXTURE: dict = {
    "data": {
        "klines": [
            "2026-09-02,175.10,178.20,179.00,174.50,22100000",
            "2026-09-03,-,177.90,180.20,176.00,19800000",
            "2026-09-04,177.95,181.30",
            "garbage-row",
            "2026-09-05,181.55,185.60,186.20,181.00,26400000",
        ],
    }
}

NVDA_QUOTE_FIXTURE: dict = {
    "rc": 0,
    "data": {
        "diff": [
            {"f2": 184.95, "f3": -0.38, "f4": -0.70, "f12": "NVDA", "f14": "英伟达"},
        ],
    },
}

NVDA_MARKET_CAP_FIXTURE: dict = {
    "data": {
        "diff": [
            {"f2": 184.95, "f12": "NVDA", "f20": 4500000000000},
        ],
    },
}

MARKET_CAP_MISSING_FIXTURE: dict = {
    "data": {"diff": [{"f2": 184.95, "f12": "NVDA", "f20": "-"}]},
}

# KDJ 手算基准（period=9，RSV=(C-L9)/(H9-L9)*100，K/D 各 1/3 平滑，J=3K-2D）：
# 前 9 根窗口 H=125/L=100/C=124 → RSV=96；K9=65.3333 D9=55.1111 J9=85.7778；
# 第 10 根窗口 H=126/L=101/C=122 → RSV=84；K10=71.5556 D10=60.5926 J10=93.4815。
KDJ_BARS: tuple[OHLCVBar, ...] = tuple(
    OHLCVBar(
        trade_date=date(2026, 8, 26 + offset // 3),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1_000_000,
    )
    for offset, (open_, high, low, close) in enumerate(
        [
            (105.0, 110.0, 100.0, 105.0),
            (107.0, 112.0, 101.0, 108.0),
            (107.5, 111.0, 102.0, 106.0),
            (108.0, 115.0, 104.0, 112.0),
            (112.5, 118.0, 108.0, 116.0),
            (115.5, 119.0, 110.0, 114.0),
            (114.5, 120.0, 111.0, 118.0),
            (118.5, 122.0, 113.0, 120.0),
            (121.0, 125.0, 118.0, 124.0),
            (123.5, 126.0, 119.0, 122.0),
        ]
    )
)

# ---------------------------------------------------------------------------
# 夹具：汇率（open.er-api.com 风格；结构未实测，fixture 锁行为）
# ---------------------------------------------------------------------------

FX_SNAPSHOT_FIXTURE: dict = {
    "result": "success",
    "base_code": "USD",
    "time_last_update_utc": "Fri, 12 Sep 2026 00:00:00 +0000",
    "rates": {
        "USD": 1.0,
        "EUR": 0.85,
        "GBP": 0.73,
        "JPY": 148.5,
        "KRW": 1345.0,
        "TWD": 31.2,
        "CNY": 7.15,
        "HKD": 7.8,
        "SGD": 1.34,
        "MOP": 8.04,
        "AED": 3.67,
        # 2026-10-02 席位 F1：SUPPORTED_CURRENCIES 补 RUB/CHF/CAD/AUD 后，
        # 本夹具必须同步给出这四枚，否则「上游全量返回」这条腿会被误判成
        # DEGRADED。**形状值，非真实报价**（本节头注：结构未实测，fixture 锁行为）。
        "RUB": 92.4,
        "CHF": 0.885,
        "CAD": 1.365,
        "AUD": 1.52,
    },
}

FX_PARTIAL_FIXTURE: dict = {
    "result": "success",
    "base_code": "USD",
    "time_last_update_utc": "Fri, 12 Sep 2026 00:00:00 +0000",
    "rates": {"USD": 1.0, "EUR": 0.85, "CNY": 7.15, "JPY": 148.5},
}


@pytest.fixture()
def _clean_stock_state() -> Iterator[None]:
    yield
    # 预留：若后续加进程内缓存，在此统一 reset。


# ---------------------------------------------------------------------------
# contracts/finance.py：字段语义与校验
# ---------------------------------------------------------------------------


class TestFinanceContracts:
    def test_ohlcv_bar_accepts_valid_row(self) -> None:
        bar = OHLCVBar(
            trade_date=date(2026, 9, 8),
            open=185.70,
            high=187.30,
            low=183.80,
            close=184.95,
            volume=23100000,
        )
        assert bar.close == 184.95
        assert bar.volume == 23100000

    def test_ohlcv_bar_rejects_inverted_range(self) -> None:
        with pytest.raises(ValidationError):
            OHLCVBar(
                trade_date=date(2026, 9, 8),
                open=185.0,
                high=180.0,  # high < low，非法
                low=183.0,
                close=184.0,
                volume=1,
            )

    def test_ohlcv_bar_rejects_negative_volume(self) -> None:
        with pytest.raises(ValidationError):
            OHLCVBar(
                trade_date=date(2026, 9, 8),
                open=1.0,
                high=2.0,
                low=0.5,
                close=1.5,
                volume=-1,
            )

    def test_market_cap_missing_value_is_none_not_zero(self) -> None:
        cap = MarketCap(
            ticker="NVDA",
            value=None,
            currency="USD",
            as_of=None,
            source="eastmoney",
            status=FinanceDataStatus.UNAVAILABLE,
            note="上游字段缺失",
        )
        assert cap.value is None
        assert cap.status is FinanceDataStatus.UNAVAILABLE

    def test_market_cap_rejects_negative_value(self) -> None:
        with pytest.raises(ValidationError):
            MarketCap(
                ticker="NVDA",
                value=-5.0,
                currency="USD",
                as_of=None,
                source="eastmoney",
                status=FinanceDataStatus.OK,
            )

    def test_currency_quote_validators(self) -> None:
        quote = CurrencyQuote(
            base_currency="USD",
            quote_currency="CNY",
            rate=7.15,
            rate_type="mid",
            as_of=None,
            source="open.er-api.com",
            status=FinanceDataStatus.OK,
            delayed=True,
        )
        assert quote.rate > 0
        # 小写短码归一为大写（与 ticker 行为一致），不视为非法。
        normalized = CurrencyQuote(
            base_currency="usd",
            quote_currency="cny",
            rate=7.15,
            rate_type="mid",
            as_of=None,
            source="x",
            status=FinanceDataStatus.OK,
        )
        assert normalized.base_currency == "USD"
        assert normalized.quote_currency == "CNY"
        with pytest.raises(ValidationError):
            CurrencyQuote(
                base_currency="US",  # 非 3 字母，非法
                quote_currency="CNY",
                rate=7.15,
                rate_type="mid",
                as_of=None,
                source="x",
                status=FinanceDataStatus.OK,
            )
        with pytest.raises(ValidationError):
            CurrencyQuote(
                base_currency="USD",
                quote_currency="CNY",
                rate=0.0,  # 汇率必须 > 0，绝不伪造 0
                rate_type="mid",
                as_of=None,
                source="x",
                status=FinanceDataStatus.OK,
            )

    def test_boxplot_stats_ordering_enforced(self) -> None:
        stats = BoxPlotStats(
            label="NVDA 近8日收盘分布",
            n=8,
            minimum=1.0,
            q1=2.75,
            median=4.5,
            q3=6.25,
            maximum=8.0,
        )
        assert stats.q1 <= stats.median <= stats.q3
        with pytest.raises(ValidationError):
            BoxPlotStats(
                label="坏数据",
                n=3,
                minimum=5.0,
                q1=1.0,  # q1 < min 非法
                median=2.0,
                q3=3.0,
                maximum=4.0,
            )

    def test_non_public_note_has_no_price_fields(self) -> None:
        note = openai_equity_note()
        assert note.status is FinanceDataStatus.NON_PUBLIC
        assert note.valuation_usd and note.valuation_usd > 0
        assert note.valuation_as_of is not None
        # 来源声明必须非空（有出处的公开估值，不接受无来源数字）。
        assert note.valuation_source.strip()
        assert "openai.com" in note.valuation_source
        # 结构性红线：该契约上不存在任何价格/OHLC 字段。
        for forbidden in ("price", "open", "high", "low", "close", "volume", "ohlc"):
            assert not hasattr(note, forbidden), forbidden


# ---------------------------------------------------------------------------
# sources/stock_data.py：解析 / KDJ / 箱形图 / 非上市
# ---------------------------------------------------------------------------


class TestStockData:
    def test_registry_has_explicit_tickers(self) -> None:
        tickers = {ref.ticker for ref in stock_data.list_listed_companies()}
        assert {"NVDA", "AMD", "INTC"} <= tickers
        for ref in stock_data.list_listed_companies():
            assert ref.ticker == ref.ticker.upper()
            assert ref.secid, "每个注册公司必须有显式 secid"

    @pytest.mark.parametrize(
        "text,ticker",
        [
            ("英伟达股价多少", "NVDA"),
            ("看看NVDA", "NVDA"),
            ("nvda 行情", "NVDA"),
            ("AMD 股价", "AMD"),
            ("超威 股价", "AMD"),
            ("英特尔股价", "INTC"),
            ("intc", "INTC"),
            ("openai 股价", "OPENAI"),
            ("OpenAI 值多少钱", "OPENAI"),
            ("今天天气如何", None),
            ("行情", None),
        ],
    )
    def test_resolve_company_query(self, text: str, ticker: str | None) -> None:
        assert resolve_company_query(text) == ticker

    def test_ohlcv_parsed_from_fixture(self, _clean_stock_state, monkeypatch) -> None:
        monkeypatch.setattr(
            stock_data, "_fetch_kline_payload", lambda ticker, days, timeout: dict(NVDA_KLINE_FIXTURE)
        )
        series = fetch_stock_ohlcv("NVDA")
        assert series.ticker == "NVDA"
        assert series.status is FinanceDataStatus.OK
        assert len(series.bars) == 5
        first = series.bars[0]
        assert first.trade_date == date(2026, 9, 2)
        assert first.open == 175.10
        assert first.close == 178.20
        assert first.high == 179.00
        assert first.low == 174.50
        assert first.volume == 22100000
        assert series.closes[-1] == 184.95
        assert series.source == "eastmoney_kline"
        assert series.delayed is True

    def test_ohlcv_partial_rows_degrade_not_fail(
        self, _clean_stock_state, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            stock_data,
            "_fetch_kline_payload",
            lambda ticker, days, timeout: dict(NVDA_KLINE_PARTIAL_FIXTURE),
        )
        series = fetch_stock_ohlcv("NVDA")
        # 坏行逐行跳过，好行保留，状态降级而非报错。
        assert len(series.bars) == 2
        assert series.status is FinanceDataStatus.DEGRADED

    def test_ohlcv_network_failure_explains(
        self, _clean_stock_state, monkeypatch
    ) -> None:
        def _boom(ticker: str, days: int, timeout: float) -> dict:
            raise OSError("network down")

        monkeypatch.setattr(stock_data, "_fetch_kline_payload", _boom)
        series = fetch_stock_ohlcv("NVDA")
        assert series.bars == []
        assert series.status is FinanceDataStatus.UNAVAILABLE
        assert series.note.strip(), "失败必须带可解释说明"

    def test_ohlcv_non_public_ticker_never_fabricates(
        self, _clean_stock_state, monkeypatch
    ) -> None:
        def _must_not_call(ticker: str, days: int, timeout: float) -> dict:
            raise AssertionError("非上市公司绝不允许外呼行情接口")

        monkeypatch.setattr(stock_data, "_fetch_kline_payload", _must_not_call)
        series = fetch_stock_ohlcv("OPENAI")
        assert series.bars == []
        assert series.status is FinanceDataStatus.NON_PUBLIC

    def test_quote_parsed_from_fixture(self, _clean_stock_state, monkeypatch) -> None:
        monkeypatch.setattr(
            stock_data, "_fetch_quote_payload", lambda ticker, timeout: dict(NVDA_QUOTE_FIXTURE)
        )
        quote = fetch_stock_quote("NVDA")
        assert quote.price == 184.95
        assert quote.change_pct == -0.38
        assert quote.change_abs == -0.70
        assert quote.currency == "USD"
        assert quote.delayed is True
        assert quote.status is FinanceDataStatus.OK

    def test_quote_failure_explains(self, _clean_stock_state, monkeypatch) -> None:
        def _boom(ticker: str, timeout: float) -> dict:
            raise OSError("down")

        monkeypatch.setattr(stock_data, "_fetch_quote_payload", _boom)
        quote = fetch_stock_quote("NVDA")
        assert quote.price is None
        assert quote.status is FinanceDataStatus.UNAVAILABLE

    def test_market_cap_parsed_and_missing_safe(
        self, _clean_stock_state, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            stock_data,
            "_fetch_quote_payload",
            lambda ticker, timeout: dict(NVDA_MARKET_CAP_FIXTURE),
        )
        cap = fetch_market_cap("NVDA")
        assert cap.value == 4_500_000_000_000
        assert cap.currency == "USD"

        monkeypatch.setattr(
            stock_data,
            "_fetch_quote_payload",
            lambda ticker, timeout: dict(MARKET_CAP_MISSING_FIXTURE),
        )
        missing = fetch_market_cap("NVDA")
        # 字段缺失 → 明确状态，绝不伪造 0。
        assert missing.value is None
        assert missing.status is FinanceDataStatus.UNAVAILABLE

    def test_kdj_matches_hand_computed_values(self) -> None:
        snapshot = compute_kdj(KDJ_BARS, period=9)
        assert snapshot is not None
        assert snapshot.trade_date == date(2026, 8, 29)  # 最后一根的日期
        assert snapshot.k == pytest.approx(71.5556, abs=1e-3)
        assert snapshot.d == pytest.approx(60.5926, abs=1e-3)
        assert snapshot.j == pytest.approx(93.4815, abs=1e-3)
        assert snapshot.period == 9

    def test_kdj_insufficient_data_returns_none(self) -> None:
        assert compute_kdj(KDJ_BARS[:8], period=9) is None

    def test_kdj_flat_window_neutral_not_zero(self) -> None:
        flat = tuple(
            OHLCVBar(
                trade_date=date(2026, 9, 1 + offset),
                open=100.0,
                high=100.0,
                low=100.0,
                close=100.0,
                volume=1,
            )
            for offset in range(9)
        )
        snapshot = compute_kdj(flat, period=9)
        assert snapshot is not None
        # 数学上恒 50（浮点累积有 1e-14 量级噪声）。
        assert snapshot.k == pytest.approx(50.0, abs=1e-9)
        assert snapshot.d == pytest.approx(50.0, abs=1e-9)
        assert snapshot.j == pytest.approx(50.0, abs=1e-9)

    def test_boxplot_five_number_summary(self) -> None:
        stats, status = stock_data.boxplot_stats(
            [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0], label="8日收盘"
        )
        assert status == "ok"
        assert stats is not None
        assert stats.n == 8
        assert stats.minimum == 1.0
        assert stats.q1 == pytest.approx(2.75)  # type-7 线性插值
        assert stats.median == pytest.approx(4.5)
        assert stats.q3 == pytest.approx(6.25)
        assert stats.maximum == 8.0

    def test_boxplot_rejects_single_day_ohlc_as_distribution(self) -> None:
        # 图表语义红线：单日 OHLC 不是分布，绝不能画成箱形图。
        single_day = KDJ_BARS[-1]
        stats, status = stock_data.boxplot_stats(
            [single_day.close], label="单日", min_samples=5
        )
        assert stats is None
        assert status == "insufficient_data"
        # 多日 OHLC 序列按日收盘取分布：单根序列同样拒绝。
        from plugins.bot_unified_runtime.domains.finance.data.stock_data import (
            build_boxplot_from_ohlcv,
        )

        stats2, status2 = build_boxplot_from_ohlcv(_series(bars=KDJ_BARS[:1]))
        assert stats2 is None
        assert status2 == "insufficient_data"
        stats3, status3 = build_boxplot_from_ohlcv(_series(bars=KDJ_BARS))
        assert stats3 is not None
        assert status3 == "ok"
        assert stats3.n == 10

    def test_openai_note_is_sourced_and_dated(self) -> None:
        note = openai_equity_note()
        assert isinstance(note, NonPublicEquityNote)
        assert note.valuation_usd == pytest.approx(852e9)
        assert note.valuation_as_of == date(2026, 3, 31)
        assert note.statement.strip()

    def test_secid_registry_values(self) -> None:
        # 上市科技公司用明确 ticker + secid（105=NASDAQ 东财惯例）。
        ref = stock_data.find_company_ref("NVDA")
        assert ref is not None
        assert ref.secid == "105.NVDA"
        assert ref.exchange == "NASDAQ"


# ---------------------------------------------------------------------------
# sources/fx_data.py：快照解析 / 缺币解释 / 交叉汇率
# ---------------------------------------------------------------------------


class TestFxData:
    def test_supported_currencies_cover_required_set(self) -> None:
        assert set(fx_data.SUPPORTED_CURRENCIES) >= {
            "USD", "EUR", "GBP", "JPY", "KRW", "TWD", "CNY", "HKD", "SGD", "MOP", "AED",
        }
        # 席位 F1（2026-10-02）：用户点名的 11 币必须全部在册（含待验的四枚——
        # 在册≠有源，三态由 fx_currency_availability() 逐枚表态，门② 执法）。
        assert set(fx_data.SUPPORTED_CURRENCIES) >= set(fx_data.REQUIRED_CURRENCIES)
        assert fx_data.BASE_CURRENCY == "USD"

    def test_snapshot_parsed_from_fixture(self, monkeypatch) -> None:
        monkeypatch.setattr(
            fx_data, "_fetch_fx_payload", lambda base, timeout: dict(FX_SNAPSHOT_FIXTURE)
        )
        snapshot = fx_data.fetch_fx_snapshot()
        assert snapshot.base_currency == "USD"
        assert snapshot.status is FinanceDataStatus.OK
        rates = {q.quote_currency: q.rate for q in snapshot.quotes}
        assert rates["CNY"] == 7.15
        assert rates["JPY"] == 148.5
        assert rates["MOP"] == 8.04
        assert snapshot.missing_currencies == []
        assert snapshot.as_of is not None
        assert snapshot.delayed is True
        for quote in snapshot.quotes:
            assert quote.rate_type == "mid"  # 官方中间价/参考价语义

    def test_snapshot_partial_explains_missing(self, monkeypatch) -> None:
        monkeypatch.setattr(
            fx_data, "_fetch_fx_payload", lambda base, timeout: dict(FX_PARTIAL_FIXTURE)
        )
        snapshot = fx_data.fetch_fx_snapshot()
        rates = {q.quote_currency for q in snapshot.quotes}
        # 基准 USD 自身不成对；上游给了 EUR/CNY/JPY 三个。
        assert rates == {"EUR", "CNY", "JPY"}
        # 缺的币种显式列出（MOP/TWD/…），而不是悄悄消失或补 0。
        assert "MOP" in snapshot.missing_currencies
        assert "TWD" in snapshot.missing_currencies
        assert snapshot.status is FinanceDataStatus.DEGRADED

    def test_snapshot_failure_unavailable(self, monkeypatch) -> None:
        def _boom(base: str, timeout: float) -> dict:
            raise OSError("down")

        monkeypatch.setattr(fx_data, "_fetch_fx_payload", _boom)
        snapshot = fx_data.fetch_fx_snapshot()
        assert snapshot.quotes == []
        assert snapshot.status is FinanceDataStatus.UNAVAILABLE
        assert snapshot.note.strip()
        all_targets = set(fx_data.SUPPORTED_CURRENCIES) - {"USD"}
        assert all_targets <= set(snapshot.missing_currencies)

    def test_cross_rate_from_usd_table(self) -> None:
        table = {"USD": 1.0, "EUR": 0.9, "CNY": 7.2, "JPY": 150.0}
        assert fx_data.cross_rate_from_usd(table, "EUR", "CNY") == pytest.approx(8.0)
        assert fx_data.cross_rate_from_usd(table, "USD", "JPY") == pytest.approx(150.0)
        assert fx_data.cross_rate_from_usd(table, "CHF", "CNY") is None
        assert fx_data.cross_rate_from_usd({}, "USD", "CNY") is None

    def test_format_fx_brief_shows_base_and_status(self, monkeypatch) -> None:
        monkeypatch.setattr(
            fx_data, "_fetch_fx_payload", lambda base, timeout: dict(FX_SNAPSHOT_FIXTURE)
        )
        text = fx_data.format_fx_snapshot_brief(fx_data.fetch_fx_snapshot())
        assert "USD" in text
        assert "CNY" in text
        assert "中间价" in text
        assert "延迟" in text

    def test_format_fx_brief_lists_missing(self, monkeypatch) -> None:
        monkeypatch.setattr(
            fx_data, "_fetch_fx_payload", lambda base, timeout: dict(FX_PARTIAL_FIXTURE)
        )
        text = fx_data.format_fx_snapshot_brief(fx_data.fetch_fx_snapshot())
        assert "MOP" in text and "暂无" in text


# ---------------------------------------------------------------------------
# capabilities：stocks / fx 文本能力（离线，fetch 打桩）
# ---------------------------------------------------------------------------


def _make_message(text: str):
    from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType

    return IncomingMessage(
        request_id="req-fin-test",
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id="group:g1",
        session_type=SessionType.GROUP,
        sender_id="u1",
        plain_text=text,
    )


def _make_decision(capability_id: str):
    from plugins.bot_unified_runtime.contracts import BotDecision, SessionType

    return BotDecision(
        request_id="req-fin-test",
        should_respond=True,
        mode="command",
        trigger="test",
        capability_id=capability_id,
        target_scope=SessionType.GROUP,
        decision_reason="test",
    )


class TestStocksCapability:
    def test_stock_query_full_numbers_visible(self, monkeypatch, tmp_path) -> None:
        # 运行数据根隔离：缺省会回退源码树 data/（AGENTS.md 规则 2/6），显式指到 tmp。
        monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(tmp_path))
        from plugins.bot_unified_runtime.domains.finance.capabilities import (
            stocks as stocks_cap,
        )

        monkeypatch.setattr(stocks_cap, "fetch_stock_quote", lambda ticker: _quote())
        monkeypatch.setattr(stocks_cap, "fetch_stock_ohlcv", lambda ticker: _series())
        monkeypatch.setattr(stocks_cap, "compute_kdj", lambda bars, period=9: _kdj())
        monkeypatch.setattr(stocks_cap, "fetch_market_cap", lambda ticker: _cap())
        capability = stocks_cap.build_stocks_capability()
        result = capability(_make_message("英伟达股价"), _make_decision("bot.stocks"))
        assert result.capability_id == "bot.stocks"
        assert result.kind == "text"
        assert "英伟达" in result.body
        assert "184.95" in result.body  # 现价数字可见
        assert "71.56" in result.body  # K 值
        assert "4.50" in result.body  # 市值（万亿美元）
        assert "延迟" in result.body
        assert "capability:stocks" in result.audit_tags

    def test_stock_query_data_unavailable_explains(self, monkeypatch) -> None:
        from plugins.bot_unified_runtime.domains.core.contracts.finance import (
            EquityQuote,
            FinanceDataStatus,
        )
        from plugins.bot_unified_runtime.domains.finance.capabilities import (
            stocks as stocks_cap,
        )

        monkeypatch.setattr(
            stocks_cap,
            "fetch_stock_quote",
            lambda ticker: EquityQuote(
                ticker="NVDA",
                name="英伟达",
                exchange="NASDAQ",
                currency="USD",
                price=None,
                change_pct=None,
                change_abs=None,
                source="eastmoney",
                as_of=None,
                status=FinanceDataStatus.UNAVAILABLE,
                delayed=True,
                note="上游失败",
            ),
        )
        monkeypatch.setattr(
            stocks_cap, "fetch_stock_ohlcv", lambda ticker: _series(status=FinanceDataStatus.UNAVAILABLE, bars=())
        )
        monkeypatch.setattr(
            stocks_cap,
            "compute_kdj",
            lambda bars, period=9: None,
        )
        monkeypatch.setattr(stocks_cap, "fetch_market_cap", lambda ticker: _cap(value=None))
        capability = stocks_cap.build_stocks_capability()
        result = capability(_make_message("NVDA 股价"), _make_decision("bot.stocks"))
        assert "暂无" in result.body
        assert "184.95" not in result.body  # 不显示旧值/伪造数字

    def test_openai_query_returns_valuation_never_prices(self, monkeypatch) -> None:
        from plugins.bot_unified_runtime.domains.finance.capabilities import (
            stocks as stocks_cap,
        )

        def _must_not_call(*args: object, **kwargs: object) -> None:
            raise AssertionError("OpenAI 查询绝不允许触发行情外呼")

        monkeypatch.setattr(stocks_cap, "fetch_stock_quote", _must_not_call)
        monkeypatch.setattr(stocks_cap, "fetch_stock_ohlcv", _must_not_call)
        monkeypatch.setattr(stocks_cap, "fetch_market_cap", _must_not_call)
        capability = stocks_cap.build_stocks_capability()
        result = capability(_make_message("openai 股价"), _make_decision("bot.stocks"))
        assert "未上市" in result.body
        assert "8520" in result.body  # 亿美元口径
        assert "2026" in result.body  # 估值时点
        assert "stocks:non_public" in result.audit_tags

    def test_unrelated_text_not_triggered(self) -> None:
        from plugins.bot_unified_runtime.domains.finance.capabilities import (
            stocks as stocks_cap,
        )

        assert stocks_cap.is_stocks_command("英伟达股价") is True
        assert stocks_cap.is_stocks_command("今天天气如何") is False
        assert stocks_cap.is_stocks_command("") is False

    def test_card_payload_shape_matches_bridge_contract(self) -> None:
        from plugins.bot_unified_runtime.domains.finance.capabilities import (
            stocks as stocks_cap,
        )

        payload = stocks_cap.build_stocks_card_payload(_quote(), _series(), _kdj(), _cap())
        assert payload["title"] == "英伟达（NVDA · NASDAQ）行情速览"  # vis3：标题官方中文名
        assert payload["badge"] == "延迟行情"
        names = [s["name"] for s in payload["sections"]]
        assert "个股行情" in names
        assert "指标与市值" in names
        main = payload["sections"][0]["rows"][0]
        assert main["value"] == "184.95"
        assert main["cls"] == "down"
        assert main["delta"] == "-0.38%"
        # 折线只由多日收盘生成（趋势语义）；有 K 线时必有 SVG。
        assert main["trend_svg"].startswith("<svg")
        # sub 是最新交易日 OHLC 概览，数字可见（不是状态占位符）。
        assert "开 123.50" in main["sub"]

    def test_card_payload_without_data_shows_status_not_zero(self) -> None:
        from plugins.bot_unified_runtime.domains.core.contracts.finance import (
            FinanceDataStatus,
        )
        from plugins.bot_unified_runtime.domains.finance.capabilities import (
            stocks as stocks_cap,
        )

        empty_quote = EquityQuote(
            ticker="NVDA",
            name="英伟达",
            exchange="NASDAQ",
            currency="USD",
            price=None,
            change_pct=None,
            change_abs=None,
            source="eastmoney",
            as_of=None,
            status=FinanceDataStatus.UNAVAILABLE,
            delayed=True,
            note="上游失败",
        )
        payload = stocks_cap.build_stocks_card_payload(
            empty_quote,
            _series(status=FinanceDataStatus.UNAVAILABLE, bars=()),
            None,
            _cap(value=None),
        )
        main = payload["sections"][0]["rows"][0]
        assert main["value"] == "暂无"
        assert main["trend_svg"] == ""  # 缺数据不出折线，绝不画空图/零线
        assert "上游失败" in main["sub"]
        # 指标/市值缺数据 → 整块省略，而不是补 0。
        assert len(payload["sections"]) == 1

    def test_render_backend_wiring_produces_png(self, monkeypatch, tmp_path) -> None:
        """渲染链路冒烟：fake 后端 + 真 render_finance_card_html（离线 jinja）。"""
        # 运行数据根隔离：缺省会回退源码树 data/（AGENTS.md 规则 2/6），显式指到 tmp。
        monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(tmp_path))
        from types import SimpleNamespace

        from plugins.bot_unified_runtime.domains.finance.capabilities import (
            stocks as stocks_cap,
        )

        captured: dict[str, object] = {}

        def fake_render_card(spec: dict) -> bytes:
            captured["html"] = spec["html"]
            return b"fake-png-bytes"

        backend = SimpleNamespace(available=True, render_card=fake_render_card)
        config = SimpleNamespace(bot_card_render_dir=str(tmp_path))
        monkeypatch.setattr(stocks_cap, "fetch_stock_quote", lambda ticker: _quote())
        monkeypatch.setattr(stocks_cap, "fetch_stock_ohlcv", lambda ticker: _series())
        monkeypatch.setattr(stocks_cap, "compute_kdj", lambda bars, period=9: _kdj())
        monkeypatch.setattr(stocks_cap, "fetch_market_cap", lambda ticker: _cap())
        capability = stocks_cap.build_stocks_capability(config, render_backend=backend)
        result = capability(_make_message("英伟达股价"), _make_decision("bot.stocks"))
        assert result.kind == "mixed"
        assert result.images and result.images[0]["file"].endswith(".png")
        assert (tmp_path / result.images[0]["file"]).read_bytes() == b"fake-png-bytes"
        html = str(captured["html"])
        # 卡上真实数字可见（指数/个股数字必须可见这条 AC 对卡同样成立）。
        assert "184.95" in html
        assert "英伟达" in html
        assert "KDJ(9)" in html


class TestFxCapability:
    def test_pair_query_shows_rate_and_delayed_note(self, monkeypatch) -> None:
        from plugins.bot_unified_runtime.domains.finance.capabilities import (
            fx as fx_cap,
        )

        monkeypatch.setattr(
            "plugins.bot_unified_runtime.domains.finance.data.fx_data.fetch_fx_rates",
            lambda timeout_seconds=6.0, cache_seconds=60.0: _fx_rates(),
        )
        capability = fx_cap.build_fx_capability()
        result = capability(_make_message("美元兑人民币"), _make_decision("bot.fx"))
        assert result.capability_id == "bot.fx"
        assert "6.7081" in result.body
        assert "eastmoney" in result.body
        assert "fx:pair:USD/CNY" in result.audit_tags

    def test_fx_failure_degrades(self, monkeypatch) -> None:
        from plugins.bot_unified_runtime.domains.finance.capabilities import (
            fx as fx_cap,
        )

        monkeypatch.setattr(
            "plugins.bot_unified_runtime.domains.finance.data.fx_data.fetch_fx_rates",
            lambda timeout_seconds=6.0, cache_seconds=60.0: [],
        )
        capability = fx_cap.build_fx_capability()
        result = capability(_make_message("汇率"), _make_decision("bot.fx"))
        assert "暂时拉不到" in result.body
        assert "fx:fetch_failed" in result.audit_tags

    def test_fx_trigger_matrix(self) -> None:
        from plugins.bot_unified_runtime.domains.finance.capabilities import (
            fx as fx_cap,
        )

        assert fx_cap.is_fx_command("美元汇率") is True
        assert fx_cap.is_fx_command("人民币兑美元 汇率") is True
        assert fx_cap.is_fx_command("行情") is False
        assert fx_cap.is_fx_command("房价行情") is False

    def test_fx_card_payload_shape(self) -> None:
        from plugins.bot_unified_runtime.domains.finance.capabilities import (
            fx as fx_cap,
        )

        payload = fx_cap.build_fx_card_payload(_fx_rates(), "")
        assert payload["title"] == "汇率速览"
        section = payload["sections"][0]
        pairs = {row["label"]: row["value"] for row in section["rows"]}
        assert pairs["USD/CNY"] == "6.7081"
        assert pairs["JPY/CNY"] == "4.3614"
        # 无缺币 → 无「暂无数据」行。
        assert all(row["label"] != "暂无数据" for row in section["rows"])
        # 汇率无可用日 K（实测）→ 每行诚实标注走势缺口，不伪造折线。
        assert all(
            row.get("trend_note") == "暂无历史走势数据"
            for row in section["rows"]
            if row["label"] != "暂无数据"
        )

    def test_fx_card_payload_lists_missing(self) -> None:
        from plugins.bot_unified_runtime.domains.finance.capabilities import (
            fx as fx_cap,
        )

        payload = fx_cap.build_fx_card_payload(
            _fx_rates(), "USD/TWD、USD/MOP、USD/AED"
        )
        rows = payload["sections"][0]["rows"]
        missing_row = next(row for row in rows if row["label"] == "暂无数据")
        assert "MOP" in missing_row["value"]


# ---------------------------------------------------------------------------
# market 增量：指数 provenance（source/delayed/as_of）
# ---------------------------------------------------------------------------


EM_MINI_FIXTURE: dict = {
    "data": {
        "diff": [
            {"f2": 3934.4, "f3": -0.43, "f4": -17.11, "f12": "000001", "f14": "上证指数"},
        ],
    }
}

MOEX_FIXTURE: dict = {
    "marketdata": {
        "columns": ["SECID", "BOARDID", "LASTVALUE", "CURRENTVALUE", "LASTCHANGE", "LASTCHANGEPRC"],
        "data": [["IMOEX", "SNDX", 2308.93, 2281.04, -27.89, -1.21]],
    }
}


class TestMarketProvenance:
    def test_index_quotes_carry_source_delayed_as_of(self, monkeypatch) -> None:
        monkeypatch.setattr(market_data, "_fetch_moex_quote", lambda timeout: None)
        monkeypatch.setattr(
            market_data, "_fetch_payload", lambda secids, timeout: dict(EM_MINI_FIXTURE)
        )
        market_data.reset_market_cache()
        quotes = market_data.fetch_index_quotes()
        market_data.reset_market_cache()
        assert len(quotes) == 1
        quote = quotes[0]
        assert quote.source == "eastmoney"
        assert quote.delayed is True
        assert quote.as_of is not None  # 数据时间戳（unix 秒）

    def test_moex_quote_marked_separate_source(self, monkeypatch) -> None:
        monkeypatch.setattr(
            market_data, "http_get_json", lambda *a, **k: dict(MOEX_FIXTURE)
        )
        quote = market_data._fetch_moex_quote(6.0)
        assert quote is not None
        assert quote.source == "moex_iss"
        assert quote.delayed is True

    def test_field_missing_rows_still_skipped(self, monkeypatch) -> None:
        broken = {"data": {"diff": [{"f2": "-", "f3": 1.0, "f12": "000001"}]}}
        monkeypatch.setattr(market_data, "_fetch_moex_quote", lambda timeout: None)
        monkeypatch.setattr(market_data, "_fetch_payload", lambda secids, timeout: broken)
        market_data.reset_market_cache()
        quotes = market_data.fetch_index_quotes()
        market_data.reset_market_cache()
        assert quotes == []  # 缺字段安全跳过，不造数


# ---------------------------------------------------------------------------
# 网络集成（默认跳过；BOT_FINANCE_NET_TESTS=1 才跑）
# ---------------------------------------------------------------------------


@skip_network
class TestNetworkIntegration:
    def test_live_eastmoney_ohlcv(self) -> None:
        series = fetch_stock_ohlcv("NVDA", timeout_seconds=8.0)
        if series.status is FinanceDataStatus.UNAVAILABLE:
            pytest.skip("上游不可达（沙箱/网络受限），不作为失败")
        assert series.bars, "可达环境下应有真实 K 线"

    def test_live_fx_snapshot(self) -> None:
        snapshot = fx_data.fetch_fx_snapshot(timeout_seconds=8.0)
        if snapshot.status is FinanceDataStatus.UNAVAILABLE:
            pytest.skip("上游不可达（沙箱/网络受限），不作为失败")
        assert snapshot.quotes


# ---------------------------------------------------------------------------
# 测试辅助：能力层打桩用的最小合法对象（普通工厂函数）
# ---------------------------------------------------------------------------


def _quote() -> EquityQuote:
    return EquityQuote(
        ticker="NVDA",
        name="英伟达",
        exchange="NASDAQ",
        currency="USD",
        price=184.95,
        change_pct=-0.38,
        change_abs=-0.70,
        source="eastmoney",
        as_of=None,
        status=FinanceDataStatus.OK,
        delayed=True,
        note="",
    )


def _series(
    status: FinanceDataStatus | None = None,
    bars: tuple[OHLCVBar, ...] | list[OHLCVBar] | None = None,
) -> OHLCVSeries:
    return OHLCVSeries(
        ticker="NVDA",
        name="英伟达",
        currency="USD",
        bars=list(bars if bars is not None else KDJ_BARS),
        source="eastmoney_kline",
        as_of=None,
        status=status or FinanceDataStatus.OK,
        delayed=True,
        note="",
    )


def _kdj() -> KDJSnapshot:
    return KDJSnapshot(
        trade_date=date(2026, 8, 28),
        k=71.555556,
        d=60.592593,
        j=93.481481,
        period=9,
    )


def _cap(value: float | None = 4_500_000_000_000.0) -> MarketCap:
    return MarketCap(
        ticker="NVDA",
        value=value,
        currency="USD",
        as_of=None,
        source="eastmoney",
        status=FinanceDataStatus.OK if value is not None else FinanceDataStatus.UNAVAILABLE,
        note="" if value is not None else "上游字段缺失",
    )


def _fx_snapshot() -> FxRateSnapshot:
    return fx_data.build_snapshot_from_payload(dict(FX_SNAPSHOT_FIXTURE))


# ---------------------------------------------------------------------------
# capabilities：fx 表达面与卡片胶水（C 方向整合追加，离线，fetch 打桩）
# ---------------------------------------------------------------------------


def _fx_rates():
    from plugins.bot_unified_runtime.domains.core.contracts.finance import FxRate

    return [
        FxRate(
            base_currency="USD",
            quote_currency="CNY",
            rate=6.7081,
            timestamp="2026-09-12 20:00:00",
            rate_type="spot",
        ),
        FxRate(
            base_currency="JPY",
            quote_currency="CNY",
            rate=4.3614,
            unit_base=100.0,
            timestamp="2026-09-12 20:00:00",
            rate_type="parity",
        ),
    ]


class TestFxCapabilitySurface:
    def test_pair_query_converts_with_source_note(self, monkeypatch) -> None:
        from plugins.bot_unified_runtime.domains.finance.capabilities import (
            fx as fx_cap,
        )

        monkeypatch.setattr(
            "plugins.bot_unified_runtime.domains.finance.data.fx_data.fetch_fx_rates",
            lambda timeout_seconds=6.0, cache_seconds=60.0: _fx_rates(),
        )
        assert fx_cap.is_fx_command("美元兑人民币")
        capability = fx_cap.build_fx_capability()
        result = capability(_make_message("美元兑人民币"), _make_decision("bot.fx"))
        assert result.kind == "text"
        assert "6.7081" in result.body
        assert "fx:pair:USD/CNY" in result.audit_tags

    def test_amount_conversion_uses_unit_base(self, monkeypatch) -> None:
        from plugins.bot_unified_runtime.domains.finance.capabilities import (
            fx as fx_cap,
        )

        monkeypatch.setattr(
            "plugins.bot_unified_runtime.domains.finance.data.fx_data.fetch_fx_rates",
            lambda timeout_seconds=6.0, cache_seconds=60.0: _fx_rates(),
        )
        assert fx_cap.is_fx_command("100日元换多少人民币")
        capability = fx_cap.build_fx_capability()
        result = capability(
            _make_message("100日元换多少人民币"), _make_decision("bot.fx")
        )
        # 100 日元中间价口径：unit_base=100 → 100/100 × 4.3614 = 4.36。
        assert "4.36" in result.body
        assert "parity" in result.body
        # 评审 P0-1 回归：参考行必须按 unit_base 折算（1 JPY = 0.043614 CNY），
        # 绝不允许出现「1 JPY = 4.3614 CNY」这种 100 倍错误展示。
        assert "1 JPY = 0.043614 CNY" in result.body
        assert "1 JPY = 4.3614" not in result.body

    def test_unavailable_pair_honest_no_fake_number(self, monkeypatch) -> None:
        from plugins.bot_unified_runtime.domains.finance.capabilities import (
            fx as fx_cap,
        )

        monkeypatch.setattr(
            "plugins.bot_unified_runtime.domains.finance.data.fx_data.fetch_fx_rates",
            lambda timeout_seconds=6.0, cache_seconds=60.0: _fx_rates(),
        )
        capability = fx_cap.build_fx_capability()
        result = capability(_make_message("美元兑新台币"), _make_decision("bot.fx"))
        assert "暂无数据" in result.body
        assert "fx:pair_unavailable" in result.audit_tags

    def test_panel_renders_card_with_gap_notes(self, monkeypatch, tmp_path) -> None:
        from plugins.bot_unified_runtime.domains.finance.capabilities import (
            fx as fx_cap,
        )

        monkeypatch.setattr(
            "plugins.bot_unified_runtime.domains.finance.data.fx_data.fetch_fx_rates",
            lambda timeout_seconds=6.0, cache_seconds=60.0: _fx_rates(),
        )
        captured: dict = {}

        class _Backend:
            name = "fake"
            available = True

            def render_card(self, payload):
                captured.update(payload)
                return b"fake-png"

        config = type("Config", (), {"bot_card_render_dir": str(tmp_path)})()
        capability = fx_cap.build_fx_capability(config, render_backend=_Backend())
        result = capability(_make_message("汇率"), _make_decision("bot.fx"))
        assert result.kind == "mixed"
        assert "card_rendered" in result.audit_tags
        assert "主要货币汇率速览" in result.body
        html_text = captured["html"]
        # 无源币种显式列出；汇率无日 K → 走势缺口诚实标注。
        assert "USD/TWD" in html_text
        assert "暂无历史走势数据" in html_text
        assert any(p.name.startswith("fx_") for p in tmp_path.iterdir())

    def test_fetch_failed_degrades_text(self, monkeypatch) -> None:
        from plugins.bot_unified_runtime.domains.finance.capabilities import (
            fx as fx_cap,
        )

        monkeypatch.setattr(
            "plugins.bot_unified_runtime.domains.finance.data.fx_data.fetch_fx_rates",
            lambda timeout_seconds=6.0, cache_seconds=60.0: [],
        )
        capability = fx_cap.build_fx_capability()
        result = capability(_make_message("汇率"), _make_decision("bot.fx"))
        assert result.kind == "text"
        assert "fx:fetch_failed" in result.audit_tags
        assert "拉不到" in result.body

    def test_trigger_guards(self) -> None:
        from plugins.bot_unified_runtime.domains.finance.capabilities import (
            fx as fx_cap,
        )
        from plugins.bot_unified_runtime.domains.finance.capabilities import (
            stocks as stocks_cap,
        )

        assert fx_cap.is_fx_command("USD/CNY")
        assert fx_cap.is_fx_command("日元汇率")
        assert fx_cap.is_fx_command("美元换算")  # 换算 + 币名
        # 评审 P1-1：裸「换算」与日常聊天不得劫持。
        assert not fx_cap.is_fx_command("单位换算")
        assert not fx_cap.is_fx_command("长度换算公式")
        assert not stocks_cap.is_stocks_command("我想吃苹果")
        assert not stocks_cap.is_stocks_command("谷歌地图好用吗")
        assert not stocks_cap.is_stocks_command("这个手机市值多少")
        assert not stocks_cap.is_stocks_command("I bought some stock")
        # 语境相伴的公司别名照常触发。
        assert stocks_cap.is_stocks_command("meta 股价")
        assert stocks_cap.is_stocks_command("看看AMD行情")
        assert stocks_cap.is_stocks_command("openai 值多少钱")  # 非上市豁免语境
        assert not fx_cap.is_fx_command("看看股价和汇率表")  # 股票语境让路
        assert not fx_cap.is_fx_command("https://x.com/usd/cny")  # 带链接不抢
        assert not fx_cap.is_fx_command("积分兑换话术")  # 非汇率语境


# ---------------------------------------------------------------------------
# C 方向增量（2026-09-13）：MOEX 真走势 / kline end 回归 / 非上市注册表 /
# 个股箱形图与九家面板 / 触发词多语言覆盖
# ---------------------------------------------------------------------------


class TestMoexTrend:
    def _moex_payloads(self):
        cursor = {
            "history.cursor": {
                "columns": ["INDEX", "TOTAL", "PAGESIZE"],
                "data": [[0, 7252, 100]],
            }
        }
        columns = ["BOARDID", "SECID", "TRADEDATE", "CLOSE"]
        tail_rows = [
            ["SNDX", "IMOEX", f"2026-08-{d:02d}", 2281.0 + i]
            for i, d in enumerate(range(1, 31))
        ]
        tail = {"history": {"columns": columns, "data": tail_rows}}
        return [cursor, tail]

    def test_moex_trend_from_history_tail(self, monkeypatch):
        from plugins.bot_unified_runtime.domains.finance.data import market_data

        payloads = self._moex_payloads()
        captured: list[str] = []

        def _fake(url, **kwargs):
            captured.append(url)
            return payloads.pop(0)

        monkeypatch.setattr(market_data, "http_get_json", _fake)
        market_data.reset_market_trend_cache()
        closes = market_data.fetch_index_trend("100.IMOEX")
        assert len(closes) == 30
        assert closes[-1] == 2310.0
        assert "start=0" in captured[0]
        assert "start=7222" in captured[1]  # TOTAL-30 尾部窗口

    def test_moex_trend_failure_isolated(self, monkeypatch):
        from plugins.bot_unified_runtime.domains.finance.data import market_data

        def _boom(url, **kwargs):
            raise OSError("down")

        monkeypatch.setattr(market_data, "http_get_json", _boom)
        market_data.reset_market_trend_cache()
        assert market_data.fetch_index_trend("100.IMOEX") == ()


def test_stock_history_url_carries_end_param(monkeypatch):
    """个股 kline 同样必须带 end 参数（与指数侧同一上游行为变更）。"""
    from plugins.bot_unified_runtime.domains.finance.data import stock_data

    captured: dict = {}

    def _fake(url, *args, **kwargs):
        captured["url"] = url
        return {"data": {"klines": ["2026-09-11,218.29,218.29,218.29,218.29,1000"]}}

    monkeypatch.setattr(stock_data, "http_get_json", _fake)
    stock_data.reset_stock_history_cache()
    points = stock_data.fetch_stock_history("NVDA", days=5)
    assert len(points) == 1
    assert "end=20500101" in captured["url"]


class TestNonPublicRegistry:
    def test_ai_and_tech_unlisted_covered(self):
        from plugins.bot_unified_runtime.domains.finance.data.stock_data import (
            NON_PUBLIC_EQUITIES,
        )

        for key in ("OPENAI", "ANTHROPIC", "BYTEDANCE"):
            note = NON_PUBLIC_EQUITIES[key]
            assert note.status.value == "non_public"
            assert note.valuation_usd and note.valuation_usd > 0
            assert note.valuation_source  # 有来源声明
            assert note.valuation_as_of is not None

    def test_alias_resolution_and_capability_text(self, monkeypatch):
        from plugins.bot_unified_runtime.domains.finance.capabilities import (
            stocks as stocks_cap,
        )
        from plugins.bot_unified_runtime.domains.finance.data.stock_data import (
            resolve_company_query,
        )

        assert resolve_company_query("anthropic 值多少钱") == "ANTHROPIC"
        assert resolve_company_query("字节跳动估值") == "BYTEDANCE"
        capability = stocks_cap.build_stocks_capability()
        result = capability(_make_message("字节跳动估值"), _make_decision("bot.stocks"))
        assert result.kind == "text"
        assert "未上市" in result.body
        assert "stocks:non_public:BYTEDANCE" in result.audit_tags


def _ohlcv_series(symbol: str, days: int = 30):
    """构造 N 根合成日 K（收盘 100+i），供箱形图/折线用。"""
    from datetime import date, timedelta

    from plugins.bot_unified_runtime.domains.core.contracts.finance import (
        OHLCVBar,
        OHLCVSeries,
    )

    base = date(2026, 8, 1)
    bars = [
        OHLCVBar(
            trade_date=base + timedelta(days=i),
            open=100.0 + i,
            high=101.0 + i,
            low=99.0 + i,
            close=100.0 + i,
            volume=1000.0,
        )
        for i in range(days)
    ]
    return OHLCVSeries(
        ticker=symbol,
        name=symbol,
        currency="USD",
        bars=bars,
        source="eastmoney_kline",
        status=FinanceDataStatus.OK,
        delayed=True,
    )


class TestStocksPanelAndBox:
    def _panel_quotes(self):
        from plugins.bot_unified_runtime.domains.core.contracts.finance import (
            StockQuote,
        )

        return [
            StockQuote(
                symbol="NVDA",
                display_name="英伟达",
                market="NASDAQ",
                currency="USD",
                timestamp="2026-09-13 01:00:00",
                source="eastmoney",
                delayed=True,
                open=220.0,
                high=222.0,
                low=217.0,
                close=218.29,
                previous_close=218.36,
                change=-0.07,
                change_percent=-0.03,
                volume=89_060_140.0,
                market_cap=5.26e12,
            ),
            StockQuote(
                symbol="AMD",
                display_name="超威半导体",
                market="NASDAQ",
                currency="USD",
                timestamp="2026-09-13 01:00:00",
                source="eastmoney",
                delayed=True,
                open=510.0,
                high=521.0,
                low=501.0,
                close=516.13,
                previous_close=503.6,
                change=12.53,
                change_percent=2.49,
                volume=19_026_155.0,
                market_cap=8.4e11,
            ),
        ]

    def test_triggers_multilingual(self):
        from plugins.bot_unified_runtime.domains.finance.capabilities import (
            fx as fx_cap,
        )
        from plugins.bot_unified_runtime.domains.finance.capabilities import (
            stocks as stocks_cap,
        )

        # 繁体
        assert stocks_cap.is_stocks_command("台積電股價")
        assert stocks_cap.is_stocks_command("個股")
        assert fx_cap.is_fx_command("匯率")
        assert fx_cap.is_fx_command("美元兌人民幣")
        # 英文（词边界）
        assert stocks_cap.is_stocks_command("tech stocks")
        assert stocks_cap.is_stocks_command("NVDA stock price")
        assert fx_cap.is_fx_command("usd cny exchange rate")
        # 不误伤
        assert not stocks_cap.is_stocks_command("stockholm is nice")
        assert not fx_cap.is_fx_command("fix it please")

    def test_panel_card_with_box_plot(self, monkeypatch, tmp_path):
        from plugins.bot_unified_runtime.domains.finance.capabilities import (
            stocks as stocks_cap,
        )

        monkeypatch.setattr(
            "plugins.bot_unified_runtime.domains.finance.data.stock_data.fetch_stock_quotes",
            lambda symbols=None, timeout_seconds=6.0, cache_seconds=60.0: self._panel_quotes(),
        )
        from plugins.bot_unified_runtime.domains.core.contracts.finance import (
            PricePoint,
        )

        monkeypatch.setattr(
            "plugins.bot_unified_runtime.domains.finance.data.stock_data.fetch_stock_history",
            lambda symbol, days=30, timeout_seconds=6.0: tuple(
                PricePoint(
                    date=bar.trade_date,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                )
                for bar in _ohlcv_series(symbol).bars
            ),
        )
        captured: dict = {}

        class _Backend:
            name = "fake"
            available = True

            def render_card(self, payload):
                captured.update(payload)
                return b"png"

        config = type("Config", (), {"bot_card_render_dir": str(tmp_path)})()
        capability = stocks_cap.build_stocks_capability(config, render_backend=_Backend())
        result = capability(_make_message("美股股价"), _make_decision("bot.stocks"))
        assert result.kind == "mixed"
        html_text = captured["html"]
        assert "科技巨头面板" in html_text
        assert "箱形图" in html_text
        assert "<svg" in html_text  # 折线 + 箱形都进了卡
        assert "polyline" in html_text

    def test_single_stock_card_includes_distribution_box(self, monkeypatch):
        from plugins.bot_unified_runtime.domains.core.contracts.finance import (
            EquityQuote,
            FinanceDataStatus,
        )
        from plugins.bot_unified_runtime.domains.finance.capabilities import (
            stocks as stocks_cap,
        )

        quote = EquityQuote(
            ticker="NVDA",
            name="英伟达",
            exchange="NASDAQ",
            currency="USD",
            price=218.29,
            change_pct=-0.03,
            change_abs=-0.07,
            source="eastmoney",
            status=FinanceDataStatus.OK,
            delayed=True,
        )
        series = _ohlcv_series("NVDA")
        payload = stocks_cap.build_stocks_card_payload(quote, series, None, None)
        names = [section["name"] for section in payload["sections"]]
        assert any("箱形图" in name for name in names)

    def test_single_day_ohlcv_rejected_from_box(self):
        """语义门：单日 K 线（<5 根）不得画成箱形图。"""
        from plugins.bot_unified_runtime.domains.core.contracts.finance import (
            EquityQuote,
            FinanceDataStatus,
        )
        from plugins.bot_unified_runtime.domains.finance.capabilities import (
            stocks as stocks_cap,
        )

        quote = EquityQuote(
            ticker="NVDA",
            name="英伟达",
            currency="USD",
            price=218.29,
            source="eastmoney",
            status=FinanceDataStatus.OK,
            delayed=True,
        )
        payload = stocks_cap.build_stocks_card_payload(
            quote, _ohlcv_series("NVDA", days=3), None, None
        )
        assert not any("箱形图" in section["name"] for section in payload["sections"])
