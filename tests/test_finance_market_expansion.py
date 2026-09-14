"""H-01/H-02/H-03/H-04/H-07 金融扩容批回归（2026-09-14 市场与个股覆盖审查）。

五条审查项的诚实边界全部离线锁定（网络出口 monkeypatch 单点拦截；sleep 单点替换）：

- H-01 澳门/迪拜/阿联酋：真机实证「确实无源」（push2 探测 100.DFMGI 等
  全部无效 + searchapi suggest「迪拜/阿布扎比/Dubai/DFMGI」零报价）→
  INDEX_UNAVAILABLE 显式登记 + 卡面/文本「暂无」注记；ETF 语义候选
  （105.UAE）只进 PENDING_INDEX_CANDIDATES 不上卡；
- H-02 A股/港股注册表（9+8 家）：secid 前缀形态自证（1=沪/0=深/116=港）+
  中文名 display + 上市币种 currency；A+H 双重上市只注册 A 股一侧；
  快查批量面板宇宙维持 9 家美股不变；
- H-03 f47/f48/f84/f85（成交量/成交额/流通股/总股本）未实测 → 一律
  None 不上卡（哪怕上游返回了数字也不消费），留待实测回填标记；
- H-04 fetch_index_trend 瞬断重试（ParseHttpError 两败三成 fake）；
- H-07 触发词「有源才补」：无源市场不加触发词/过滤词；新公司别名走
  既有股票语境门（resolve + 语境共现），面板兜底不指错公司。

诚实铁律：绝不编数据——本文件所有夹具形态均取自 2026-09-14 真机探测的
真实响应（116.00700 腾讯 430.6 / 1.600519 茅台 1277.96 等）。
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.capabilities import user_copy
from plugins.bot_unified_runtime.capabilities.market import market_filter_secids
from plugins.bot_unified_runtime.contracts.finance import FinanceDataStatus as Status
from plugins.bot_unified_runtime.sources import market_data, stock_data
from plugins.bot_unified_runtime.sources.market_data import (
    INDEX_UNAVAILABLE,
    PENDING_INDEX_CANDIDATES,
    format_market_brief,
    reset_market_trend_cache,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import ParseHttpError
from plugins.bot_unified_runtime.sources.stock_data import (
    CompanyRef,
    fetch_market_cap,
    fetch_stock_quote,
    format_stock_brief,
    list_cn_hk_companies,
    list_listed_companies,
    resolve_company_query,
)

# ---------------------------------------------------------------------------
# 夹具（真实探测响应的字段形态；fltt=2 小数口径）
# ---------------------------------------------------------------------------

# 2026-09-14 push2 实测：116.00700 → f2=430.6 f3=0.51 f14=腾讯控股；
# 另注入 f47/f48/f84/f85 验证 H-03「上游给了也不消费」。
TENCENT_QUOTE_FIXTURE: dict = {
    "rc": 0,
    "data": {
        "diff": [
            {
                "f2": 430.6,
                "f3": 0.51,
                "f4": 2.2,
                "f12": "00700",
                "f14": "腾讯控股",
                "f47": 12_345_600.0,
                "f48": 5_318_346_000.0,
                "f84": 9_400_000_000.0,
                "f85": 9_400_000_000.0,
            },
        ],
    },
}

# 2026-09-14 push2 实测：1.600519 → f2=1277.96 f14=贵州茅台。
MOUTAI_QUOTE_FIXTURE: dict = {
    "rc": 0,
    "data": {
        "diff": [
            {"f2": 1277.96, "f3": 0.22, "f4": 2.8, "f12": "600519", "f14": "贵州茅台"},
        ],
    },
}

# f20 市值跟随上市币种（推定口径）：腾讯 f20≈3.7e12（港元量级）。
TENCENT_CAP_FIXTURE: dict = {
    "data": {"diff": [{"f2": 430.6, "f12": "00700", "f14": "腾讯控股", "f20": 3.7e12}]},
}

# 指数走势 kline（fields2=f51,f53 → "日期,收盘"，既有实测口径）。
_TREND_FIXTURE: dict = {
    "data": {"klines": ["2026-09-11,3934.40", "2026-09-12,3950.00"]}
}


@pytest.fixture()
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[float]]:
    """退避单点替换为记录器（永不真实等待）。"""
    recorded: list[float] = []

    def _record(seconds: float = 0.0) -> None:
        recorded.append(float(seconds))

    monkeypatch.setattr(market_data, "empty_backoff_sleep", _record)
    monkeypatch.setattr(stock_data, "empty_backoff_sleep", _record)
    yield recorded


# ---------------------------------------------------------------------------
# H-01：无源市场显式登记（绝不造数）
# ---------------------------------------------------------------------------


class TestH01IndexUnavailable:
    def test_three_no_source_markets_registered(self) -> None:
        names = {name for name, _reason in INDEX_UNAVAILABLE}
        # 三个市场全部定性「确实无源」，理由必须非空（可解释性契约）。
        assert names == {"迪拜", "阿联酋", "澳门"}
        assert all(reason.strip() for _name, reason in INDEX_UNAVAILABLE)

    def test_no_source_markets_never_enter_universe(self) -> None:
        # 无源市场绝不混进指数宇宙表（宇宙表维持 18 席，防「造一个指数」）。
        universe_names = {name for _s, name, _g in market_data._INDEX_UNIVERSE}
        assert len(market_data._INDEX_UNIVERSE) == 18
        assert not universe_names & {"迪拜", "阿联酋", "澳门"}

    def test_pending_candidates_never_on_card(self) -> None:
        # 待真机验证候选清单：只登记不上卡（105.UAE 为 ETF，语义≠股指）。
        universe_codes = {secid for secid, _n, _g in market_data._INDEX_UNIVERSE}
        for secid, name, reason in PENDING_INDEX_CANDIDATES:
            assert secid not in universe_codes, secid
            assert reason.strip(), name

    def test_brief_appends_unavailable_note(self) -> None:
        quotes = [
            market_data.IndexQuote("上证指数", "1.000001", 3934.4, -0.43, -17.11),
        ]
        text = format_market_brief(quotes)
        assert "暂无数据源" in text
        assert "迪拜" in text and "阿联酋" in text and "澳门" in text

    def test_brief_empty_still_degrades_without_note(self) -> None:
        # 全失败走既有降级文案（没有行情就没有注记区，不空转）。
        # 审查 Q-01：入 user_copy 池轮换（原固定「行情数据暂时拉不到，晚点再试试？」）。
        assert format_market_brief([]) in {
            template.format(reason="行情数据暂时拉不到")
            for template in user_copy.DATASOURCE_FAILURE_TEMPLATES
        }


# ---------------------------------------------------------------------------
# H-02：A股/港股个股注册表（secid 形态自证 + 中文名 + 币种）
# ---------------------------------------------------------------------------

_CN_HK_SECID_RES: tuple[tuple[str, re.Pattern[str]], ...] = (
    # A股：1=沪（600/601/603/688）/ 0=深（000/002/300），6 位数字。
    ("CNY", re.compile(r"^[01]\.\d{6}$")),
    # 港股：116=港交所，5 位数字（00700 形态）。
    ("HKD", re.compile(r"^116\.\d{5}$")),
)


class TestH02Registry:
    def test_counts_within_audit_window(self) -> None:
        cn = [r for r in list_cn_hk_companies() if r.currency == "CNY"]
        hk = [r for r in list_cn_hk_companies() if r.currency == "HKD"]
        assert 8 <= len(cn) <= 12
        assert 8 <= len(hk) <= 12

    def test_secid_format_self_certification(self) -> None:
        """secid 形态自证：从既有 9 家（105/106 前缀）同源外推的家族格式。"""
        for ref in list_cn_hk_companies():
            for currency, pattern in _CN_HK_SECID_RES:
                if ref.currency == currency:
                    assert pattern.match(ref.secid), ref
                    break
            else:
                raise AssertionError(f"未知币种注册：{ref.ticker} {ref.currency}")

    def test_chinese_display_brand_logo_present(self) -> None:
        for ref in list_cn_hk_companies():
            assert ref.display, ref.ticker
            assert re.search(r"[\u4e00-\u9fff]", ref.display), ref.display
            # vis3 品牌色/logo 域名照既有 9 家美股模式（H-02 交付要求）。
            assert ref.brand_color.startswith("#"), ref.ticker
            assert "." in ref.logo_domain, ref.ticker

    def test_ticker_unique_across_merged_registry(self) -> None:
        tickers = [ref.ticker for ref in list_listed_companies()]
        assert len(tickers) == len(set(tickers))
        # 合并注册表 = 美股 9 + A股/港股 17。
        assert len(list_listed_companies()) == 26

    def test_alias_resolution_matrix(self) -> None:
        # 中文名/惯用缩写/裸代码 → ticker（解析层；触发另有语境门）。
        cases = {
            "茅台股价": "600519",
            "贵州茅台市值": "600519",
            "宁德时代股价": "300750",
            "比亚迪股价": "002594",
            "招商银行股价": "600036",
            "招行股价": "600036",
            "中国平安股价": "601318",
            "建设银行股价": "601939",
            "建行 市值": "601939",
            "五粮液股价": "000858",
            "紫金矿业股价": "601899",
            "中芯国际股价": "688981",
            "腾讯控股股价": "00700",
            "腾讯 股价": "00700",
            "阿里巴巴股价": "09988",
            "美团行情": "03690",
            "小米集团股价": "01810",
            "港交所市值": "00388",
            "京东集团股价": "09618",
            "网易股价": "09999",
            "友邦保险股价": "01299",
        }
        for text, expected in cases.items():
            assert resolve_company_query(text) == expected, text

    def test_dual_listing_h_side_never_registered(self) -> None:
        # A+H 双重上市只注册 A 股一侧：H 侧 secid/ticker 一律不存在
        # （防同别名双 ticker 在 _BY_ALIAS 静默互相覆盖）。
        registered_secids = {ref.secid for ref in list_listed_companies()}
        registered_tickers = {ref.ticker for ref in list_listed_companies()}
        for secid, name, reason in stock_data._PENDING_STOCK_CANDIDATES:
            assert secid not in registered_secids, name
            assert reason.strip()
        for h_ticker in ("02318", "02899", "00981", "00939", "01211"):
            assert h_ticker not in registered_tickers

    def test_panel_universe_stays_us_only(self) -> None:
        # 快查批量面板维持 9 家美股：文案「美股科技巨头」语义不动，
        # A股/港股只走单股 provenance 链路（H-02 裁定）。
        assert len(stock_data._STOCK_UNIVERSE) == 9
        assert all(
            secid.startswith(("105.", "106.")) for secid, *_rest in stock_data._STOCK_UNIVERSE
        )


class TestH02QuoteAndBrief:
    def test_hk_quote_currency_and_chinese_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            stock_data,
            "_fetch_quote_payload",
            lambda ticker, timeout: dict(TENCENT_QUOTE_FIXTURE),
        )
        quote = fetch_stock_quote("00700")
        assert quote.price == 430.6
        assert quote.currency == "HKD"  # 上市币种，不再硬编码 USD
        assert quote.name == "腾讯控股"
        assert quote.exchange == "HKEX"
        assert quote.status is Status.OK

    def test_h03_unmeasured_fields_not_consumed_even_when_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """H-03 锁：上游返回 f47/f48/f84/f85 也不消费（口径未实测）。"""
        monkeypatch.setattr(
            stock_data,
            "_fetch_quote_payload",
            lambda ticker, timeout: dict(TENCENT_QUOTE_FIXTURE),
        )
        quote = fetch_stock_quote("00700")
        assert quote.volume is None
        assert quote.amount is None
        assert quote.float_shares is None
        assert quote.total_shares is None

    def test_h03_us_stocks_equally_gated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """H-03 面向全部上市公司（含 9 家美股），不只 new listings。"""
        monkeypatch.setattr(
            stock_data,
            "_fetch_quote_payload",
            lambda ticker, timeout: dict(TENCENT_QUOTE_FIXTURE),
        )
        quote = fetch_stock_quote("NVDA")
        assert quote.volume is None and quote.amount is None
        assert quote.float_shares is None and quote.total_shares is None
        assert quote.currency == "USD"  # 美股币种回归不变

    def test_unregistered_candidate_honest_degradation(self) -> None:
        """候选清单 ticker 未注册 → 显式 UNAVAILABLE，绝不外呼/造数。"""
        quote = fetch_stock_quote("01211")  # 比亚迪股份(H)：刻意不注册
        assert quote.price is None
        assert quote.status is Status.UNAVAILABLE
        assert "未注册" in quote.note

    def test_non_usd_market_cap_honest_gate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """非美元市值先不上卡（卡面币种标注未就绪，错标=7-8 倍失真）。"""
        monkeypatch.setattr(
            stock_data,
            "_fetch_quote_payload",
            lambda ticker, timeout: dict(TENCENT_CAP_FIXTURE),
        )
        cap = fetch_market_cap("00700")
        assert cap.value is None  # 数值被诚实门扣下，不进卡面
        assert cap.currency == "HKD"
        assert cap.status is Status.DEGRADED
        assert "待回填" in cap.note

    def test_usd_market_cap_unaffected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """美股市值路径零回归（f20 实测字段照常上卡）。"""
        monkeypatch.setattr(
            stock_data,
            "_fetch_quote_payload",
            lambda ticker, timeout: {
                "data": {"diff": [{"f2": 218.29, "f12": "NVDA", "f20": 4.5e12}]}
            },
        )
        cap = fetch_market_cap("NVDA")
        assert cap.value == 4.5e12
        assert cap.status is Status.OK

    def test_brief_currency_wording_adapts(self) -> None:
        from plugins.bot_unified_runtime.contracts.finance import EquityQuote

        ref = stock_data._COMPANY_BY_TICKER["600519"]
        quote = EquityQuote(
            ticker="600519",
            name="贵州茅台",
            exchange="SSE",
            currency=ref.currency,
            price=1277.96,
            change_pct=0.22,
            source="eastmoney",
            as_of=None,
            status=Status.OK,
            delayed=True,
        )
        text = format_stock_brief(quote, None, None, None)
        assert "现价 1277.96 元" in text  # CNY 惯用「元」，不再写「美元」
        assert "现价 1277.96 美元" not in text

    def test_brief_usd_wording_regression(self) -> None:
        from datetime import datetime, timezone

        from plugins.bot_unified_runtime.contracts.finance import EquityQuote, MarketCap

        quote = EquityQuote(
            ticker="NVDA",
            name="英伟达",
            exchange="NASDAQ",
            currency="USD",
            price=184.95,
            change_pct=-0.38,
            source="eastmoney",
            as_of=datetime.now(tz=timezone.utc),
            status=Status.OK,
            delayed=True,
        )
        cap = MarketCap(ticker="NVDA", value=4.5e12, currency="USD")
        text = format_stock_brief(quote, None, None, cap)
        assert "现价 184.95 美元" in text
        assert "4.50 万亿美元" in text  # 美股市值文案逐字节回归

    def test_brief_non_usd_cap_gap_explained(self) -> None:
        from plugins.bot_unified_runtime.contracts.finance import (
            EquityQuote,
            MarketCap,
        )

        quote = EquityQuote(
            ticker="00700",
            name="腾讯控股",
            exchange="HKEX",
            currency="HKD",
            price=430.6,
            change_pct=0.51,
            source="eastmoney",
            as_of=None,
            status=Status.OK,
            delayed=True,
        )
        cap = MarketCap(
            ticker="00700",
            value=None,
            currency="HKD",
            status=Status.DEGRADED,
            note="市值为上市币种（HKD）口径，币种标注能力未就绪，先不上卡（待回填）",
        )
        text = format_stock_brief(quote, None, None, cap)
        assert "总市值暂缺" in text and "待回填" in text


# ---------------------------------------------------------------------------
# H-04：fetch_index_trend 瞬断重试（与 commodities_data 同款语义）
# ---------------------------------------------------------------------------


class TestH04TrendTransientRetry:
    def _reset(self) -> None:
        reset_market_trend_cache()
        market_data.reset_market_cache()

    def test_two_transient_failures_then_success(self, monkeypatch, _no_sleep) -> None:
        """瞬断两败三成：ParseHttpError×2 → 第 3 次成功（恰 3 次外呼）。"""
        calls: list[str] = []
        payloads: list[object] = [
            ParseHttpError("boom 1"),
            ParseHttpError("boom 2"),
            dict(_TREND_FIXTURE),
        ]

        def _fake(url: str, **kwargs: object):
            calls.append(url)
            item = payloads.pop(0)
            if isinstance(item, ParseHttpError):
                raise item
            return item

        monkeypatch.setattr(market_data, "http_get_json", _fake)
        self._reset()
        closes = market_data.fetch_index_trend("1.000001")
        assert closes == (3934.40, 3950.00)
        assert len(calls) == 3
        # 两次瞬断各退避一次（empty_backoff_sleep 单点，被 _no_sleep 记录）。
        assert len(_no_sleep) == 2

    def test_persistent_transient_failure_stays_silent(
        self, monkeypatch, _no_sleep
    ) -> None:
        """持续瞬断 → _retry_transient 3 次后放弃，外层静默缺席（空元组）。"""
        calls: list[str] = []

        def _fake(url: str, **kwargs: object):
            calls.append(url)
            raise ParseHttpError("boom")

        monkeypatch.setattr(market_data, "http_get_json", _fake)
        self._reset()
        assert market_data.fetch_index_trend("1.000001") == ()
        assert len(calls) == 3  # 至多 3 次，绝不无限重试
        assert market_data.fetch_index_trend("1.000001") == ()  # 失败不缓存
        assert len(calls) == 6

    def test_non_transient_exception_no_retry(self, monkeypatch, _no_sleep) -> None:
        """真异常（OSError）不重试：_retry_transient 只接瞬断三族。"""
        calls: list[str] = []

        def _fake(url: str, **kwargs: object):
            calls.append(url)
            raise OSError("network down")

        monkeypatch.setattr(market_data, "http_get_json", _fake)
        self._reset()
        assert market_data.fetch_index_trend("1.000001") == ()
        assert len(calls) == 1
        assert _no_sleep == []  # 非瞬断不退避


# ---------------------------------------------------------------------------
# H-07：触发词同步（有源才补 → 无源不补；新公司走既有语境门）
# ---------------------------------------------------------------------------


def _cfg(**overrides):
    base = {
        "bot_market_enabled": True,
        "bot_stocks_enabled": True,
        "bot_fx_enabled": True,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestH07Triggers:
    @pytest.mark.parametrize("text", ["迪拜行情", "阿联酋行情", "澳门行情"])
    def test_no_source_markets_get_no_filters(self, text: str) -> None:
        # 「有源才补」：三市场确实无源（H-01）→ 不加过滤词/触发词，
        # 谓词层命中属「行情」泛触发的既有语义，但绝不指向具体假指数。
        assert market_filter_secids(text) == frozenset()

    @pytest.mark.parametrize("text", ["迪拜行情", "阿联酋行情", "澳门行情"])
    def test_no_source_market_queries_route_market(self, text: str) -> None:
        from plugins.bot_unified_runtime.runtime.base_router import (
            RouteKind,
            classify_message_route,
        )

        decision = classify_message_route(text, config=_cfg())
        assert decision.kind is RouteKind.MARKET

    @pytest.mark.parametrize(
        "text",
        ["茅台股价", "腾讯控股市值", "美团股价", "小米集团股价", "港交所市值"],
    )
    def test_new_companies_ride_existing_context_gate(self, text: str) -> None:
        from plugins.bot_unified_runtime.capabilities.stocks import is_stocks_command
        from plugins.bot_unified_runtime.runtime.base_router import (
            RouteKind,
            classify_message_route,
        )

        assert is_stocks_command(text) is True
        decision = classify_message_route(text, config=_cfg())
        assert decision.kind is RouteKind.STOCKS

    @pytest.mark.parametrize(
        "text",
        [
            "我想喝茅台",  # 别名无股票语境 → 不触发（T1.7 防劫持）
            "小米手机真好用",
            "平安夜快乐",
        ],
    )
    def test_bare_aliases_still_yield_to_chat(self, text: str) -> None:
        from plugins.bot_unified_runtime.capabilities.stocks import is_stocks_command

        assert is_stocks_command(text) is False

    def test_holding_company_market_substring_fix(self) -> None:
        """H-02 配套修（(?<!控)股市）：「X控股+市值」不再拼出伪「股市」。

        「腾讯控股市值」里 控股|市值 相邻会拼出「股市」子串，把个股查询
        劫持到股指面板（H-02 新增 控股 系公司名后才可达）；真「股市」语境
        （股市股价/全球股市/A股市场行情）零回归。
        """
        from plugins.bot_unified_runtime.capabilities.market import is_market_command

        assert is_market_command("腾讯控股市值") is False
        assert is_market_command("股市股价") is True  # 既有真命令对照
        assert is_market_command("全球股市") is True
        assert is_market_command("A股市场行情") is True

    def test_ambiguous_names_never_resolve_wrong_company(self) -> None:
        # 平安银行(000001)/宁德(地名) 均未注册 → 解析层 None（路由走面板
        # 兜底而非指错公司）；「平安」「宁德」刻意不入别名表。
        assert resolve_company_query("平安银行股价") is None
        assert resolve_company_query("宁德天气预报") is None
        assert stock_data._COMPANY_BY_TICKER.get("000001.SZ") is None


# ---------------------------------------------------------------------------
# 防回归：CompanyRef 契约与既有美股注册零漂移
# ---------------------------------------------------------------------------


def test_company_ref_currency_defaults_usd() -> None:
    """旧注册字段零漂移：currency 缺省 USD（9 家美股不受 H-02 影响）。"""
    ref = CompanyRef(
        ticker="X", name="X", display="X", secid="105.X", exchange="NASDAQ"
    )
    assert ref.currency == "USD"


def test_us_registry_entries_unchanged() -> None:
    tickers = {ref.ticker for ref in stock_data._LISTED_COMPANIES}
    assert tickers == {
        "NVDA", "AMD", "INTC", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSM",
    }
