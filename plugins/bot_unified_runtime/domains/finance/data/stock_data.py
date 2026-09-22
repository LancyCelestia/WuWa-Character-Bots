"""上市科技公司行情数据源（Task 4 全局审计 + 快查批量链路）。

上游复用 ``market_data.py`` 已验证的东财接口族（免 key）。**以下字段均为
2026-09-12 主代理本机 curl 实测核验（verified）**：

- 现价/市值：``GET push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&secids=...``
  包络（``data.diff`` 列表）。个股 secid 前缀 **105=NASDAQ / 106=NYSE 实测
  可用**；``f2``=最新价 / ``f3``=涨跌% / ``f4``=涨跌额 / ``f5``=成交量 /
  ``f12``=代码 / ``f13``=市场号 / ``f14``=中文名 / ``f15``=最高 /
  ``f16``=最低 / ``f17``=开盘 / ``f18``=昨收 / **``f20``=总市值（美元，
  NVDA 实测 5260789000000 ≈ 5.26 万亿美元）**。同接口族的 ``f116`` 惯用法
  实测无值，已废弃并以 f20 为准。缺失/非法一律 ``status=unavailable`` +
  note，绝不返回 0。
- K 线：``GET push2his.eastmoney.com/api/qt/stock/kline/get``，
  ``fields2=f51,f52,f53,f54,f55,f56`` 列序实测为
  **「日期,开,收,高,低,量」（是「开收高低量」，不是 OHLC 顺序）**，真实行
  ``"2026-09-09,225.025,223.420,225.930,223.210,82955478"``。解析防御式，
  坏行逐行跳过并降级 ``status=degraded``，全部失败则 ``unavailable``。

**非上市公司红线**：OpenAI（``NON_PUBLIC_EQUITIES`` 注册表）绝不外呼行情
接口、绝不生成 OHLC/股价；只提供「有来源的公开估值 + 时点 + 说明」。
估值来源：OpenAI 官方融资公告（2026-03，投后 8520 亿美元，1220 亿承诺资金），
见 https://openai.com/index/accelerating-the-next-phase-ai/ 。

**H-02/H-03 扩容批（2026-09-14 市场与个股覆盖审查）**：

- 注册表扩容：新增 A 股 9 家（secid 前缀 1=沪 / 0=深）+ 港股 8 家
  （前缀 116=港）。证据分级：push2 ulist **实测返回真实行情行**（茅台/
  招行/宁德/比亚迪/腾讯/阿里/美团/小米/港交所）；其余为 searchapi
  suggest **QuoteID 实证**（东财搜索报价库 canonical 键）+ 同前缀家族
  格式自证。A+H 双重上市公司只注册 A 股一侧（防同别名双 ticker 抢注）。
  A股/港股走单股 provenance 链路；快查批量面板（``_STOCK_UNIVERSE``）
  维持 9 家美股不变（面板文案「美股科技巨头」语义不动）。
- 币种：CompanyRef 新增 ``currency``（USD/CNY/HKD），现价/K 线/市值
  快照的 currency 跟随上市币种；纯文本快报（``format_stock_brief``）
  币种文案自适应（美元/元/港元）。**非美元市值的卡面展示暂缺**：市值行
  币种标注能力在能力层硬编码「亿美元」，非美元市值直接上卡会错标币种
  （7-8 倍失真）——按「不能如实标注的字段不上卡」置 None（见
  ``fetch_market_cap``），待能力层支持后回填。
- H-03 裁定：f47/f48/f84/f85（成交量/成交额/流通股/总股本）从未真机
  实测、单位口径可能差 100 倍（手↔股）——**置 None 不上卡**，代码留
  「待实测回填」标记（见 ``_parse_quote``）。

**图表语义**：折线（趋势）只吃 ``OHLCVSeries``（多日收盘序列）；箱形图
（分布）只吃 ≥``min_samples`` 天的多日数值——单日 OHLC 不是分布，
``boxplot_stats`` 样本不足时返回 ``(None, "insufficient_data")``。

任何网络/解析失败一律走状态对象或空值（绝不向上抛异常，绝不伪造数字）；
快查批量链路成功才进进程内 TTL 缓存，失败不缓存便于立即重试。
"""

from __future__ import annotations

import math
import random
import re
import time
import urllib.parse
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

# 审查 Q-01：user_copy 为零依赖纯常量池，sources 跨层引用不构成装配环。
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import user_copy
from plugins.bot_unified_runtime.domains.core.contracts.finance import (
    BoxPlotStats,
    EquityQuote,
    FinanceDataStatus,
    KDJSnapshot,
    MarketCap,
    NonPublicCompany,
    NonPublicEquityNote,
    OHLCVBar,
    OHLCVSeries,
    PricePoint,
    StockQuote,
    status_or_unknown,
)
from plugins.bot_unified_runtime.domains.finance.data.market_data import (
    empty_backoff_sleep,
    retry_on_empty_enabled,
)
from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
    ParseHttpError,
    http_get_json,
)


def _network_retry(fetch, *, attempts: int = 3):
    """瞬时网络故障退避重试（vis3 2026-09-13 实测：push2his 会 RemoteDisconnected
    掉线——「暂无历史走势」与 ParseHttpError 的共同根因）。ParseHttpError/
    ConnectionError/TimeoutError 各退避重试，其他异常原样抛。"""
    last_exc: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            return fetch()
        except (ParseHttpError, ConnectionError, TimeoutError) as exc:
            last_exc = exc
            if attempt + 1 >= attempts:
                raise
            empty_backoff_sleep()
    raise last_exc if last_exc is not None else RuntimeError("unreachable")  # pragma: no cover

# ==================== 公司注册表（显式 ticker，可扩展） ====================


@dataclass(frozen=True)
class CompanyRef:
    """一家上市公司的注册信息（ticker 显式，secid 可在实测后修正）。

    H-02（2026-09-14）：新增 ``currency``——上市币种（USD/CNY/HKD），
    现价/K 线/市值快照与文本快报的币种口径单一事实来源。
    """

    ticker: str
    name: str
    display: str
    secid: str  # 东财 secid：105=NASDAQ（惯例，未实测）
    exchange: str
    aliases: tuple[str, ...] = ()
    # vis3（2026-09-13 用户裁定）：股市卡 accent 跟上市公司 logo 代表色相近；
    # logo 走 logo.clearbit.com/<domain>（keyless 稳定直链），失败回退首字母徽章。
    brand_color: str = ""
    logo_domain: str = ""
    currency: str = "USD"  # 上市币种；非美元字段见 fetch_market_cap 诚实门


_LISTED_COMPANIES: tuple[CompanyRef, ...] = (
    CompanyRef(
        ticker="NVDA",
        name="NVIDIA",
        display="英伟达",
        secid="105.NVDA",
        exchange="NASDAQ",
        aliases=("英伟达", "nvda", "nvidia"),
        brand_color="#76b900",
        logo_domain="nvidia.com",
    ),
    CompanyRef(
        ticker="AMD",
        name="AMD",
        display="超威半导体",
        secid="105.AMD",
        exchange="NASDAQ",
        aliases=("amd", "超威", "超威半导体"),
        brand_color="#ed1c24",
        logo_domain="amd.com",
    ),
    CompanyRef(
        ticker="INTC",
        name="Intel",
        display="英特尔",
        secid="105.INTC",
        exchange="NASDAQ",
        aliases=("英特尔", "intc", "intel"),
        brand_color="#0068b5",
        logo_domain="intel.com",
    ),
    CompanyRef(
        ticker="AAPL",
        name="Apple",
        display="苹果",
        secid="105.AAPL",
        exchange="NASDAQ",
        aliases=("苹果", "aapl", "apple"),
        brand_color="#1d1d1f",
        logo_domain="apple.com",
    ),
    CompanyRef(
        ticker="MSFT",
        name="Microsoft",
        display="微软",
        secid="105.MSFT",
        exchange="NASDAQ",
        aliases=("微软", "msft", "microsoft"),
        brand_color="#00a4ef",
        logo_domain="microsoft.com",
    ),
    CompanyRef(
        ticker="GOOGL",
        name="Alphabet",
        display="谷歌-A",
        secid="105.GOOGL",
        exchange="NASDAQ",
        aliases=("谷歌", "googl", "alphabet", "google"),
        brand_color="#4285f4",
        logo_domain="google.com",
    ),
    CompanyRef(
        ticker="AMZN",
        name="Amazon",
        display="亚马逊",
        secid="105.AMZN",
        exchange="NASDAQ",
        aliases=("亚马逊", "amzn", "amazon"),
        brand_color="#ff9900",
        logo_domain="amazon.com",
    ),
    CompanyRef(
        ticker="META",
        name="Meta Platforms",
        display="Meta Platforms Inc-A",
        secid="105.META",
        exchange="NASDAQ",
        aliases=("meta", "meta platforms"),
        brand_color="#0081fb",
        logo_domain="meta.com",
    ),
    CompanyRef(
        ticker="TSM",
        name="TSMC",
        display="台积电",
        secid="106.TSM",
        exchange="NYSE",
        aliases=("台积电", "tsm", "tsmc", "台湾积体电路"),
        brand_color="#c8102e",
        logo_domain="tsmc.com",
    ),
)

# ==================== H-02（2026-09-14 审查）：A股/港股个股注册表 ==========
# 证据分级（诚实铁律：无实据不上卡）：
# - 【push2 实测】= 2026-09-14 本机真机 curl/venv 实探，ulist.np 返回真实
#   行情行（f12/f14/f2 与注册信息逐一比对）：600519/600036/300750/002594、
#   00700/09988/03690/01810/00388；
# - 【suggest 实证】= searchapi suggest 返回 QuoteID（东财搜索报价库的
#   canonical 报价键）与本表 secid 逐一相符：601318/601939/000858/601899/
#   688981、09618/09999/01299。
# 快查批量面板（_STOCK_UNIVERSE）不扩：面板文案「美股科技巨头」语义不动，
# A股/港股一律走单股 provenance 链路（resolve → quote/ohlcv/cap）。
#
# A+H 双重上市公司只注册 A 股一侧（防同别名双 ticker 在 _BY_ALIAS 里静默
# 互相覆盖=数据事故）：中国平安(02318)/紫金矿业(02899)/中芯国际(00981)/
# 建设银行(00939)/比亚迪股份(01211) 的 H 侧刻意不注册，进
# ``_PENDING_STOCK_CANDIDATES`` 留档。
#
# 别名劫持审计（T-Spec T1.7 同款纪律）：不带「平安」（平安银行 000001 是
# 另一家公司、平安夜是日常词）；「宁德」不带（是地名）；「招商」「建行」
# 仅在全称无歧义时收录缩写（招行/建行为无歧义惯用缩写）。
_CN_HK_LISTED_COMPANIES: tuple[CompanyRef, ...] = (
    # ---- A 股（CNY；secid 前缀 1=上交所 / 0=深交所）----
    CompanyRef(
        ticker="600519",
        name="Kweichow Moutai",
        display="贵州茅台",
        secid="1.600519",  # push2 实测：f12=600519 f14=贵州茅台
        exchange="SSE",
        aliases=("贵州茅台", "茅台", "600519"),
        brand_color="#b01f24",
        logo_domain="moutai.com.cn",
        currency="CNY",
    ),
    CompanyRef(
        ticker="300750",
        name="CATL",
        display="宁德时代",
        secid="0.300750",  # push2 实测：f12=300750 f14=宁德时代
        exchange="SZSE",
        aliases=("宁德时代", "300750"),
        brand_color="#003c7d",
        logo_domain="catl.com",
        currency="CNY",
    ),
    CompanyRef(
        ticker="002594",
        name="BYD",
        display="比亚迪",
        secid="0.002594",  # push2 实测：f12=002594 f14=比亚迪
        exchange="SZSE",
        aliases=("比亚迪", "002594"),
        brand_color="#c7000b",
        logo_domain="byd.com",
        currency="CNY",
    ),
    CompanyRef(
        ticker="600036",
        name="China Merchants Bank",
        display="招商银行",
        secid="1.600036",  # push2 实测：f12=600036 f14=招商银行
        exchange="SSE",
        aliases=("招商银行", "招行", "600036"),
        brand_color="#d22630",
        logo_domain="cmbchina.com",
        currency="CNY",
    ),
    CompanyRef(
        ticker="601318",
        name="Ping An Insurance",
        display="中国平安",
        secid="1.601318",  # suggest 实证：QuoteID=1.601318
        exchange="SSE",
        aliases=("中国平安", "601318"),
        brand_color="#f08300",
        logo_domain="pingan.com",
        currency="CNY",
    ),
    CompanyRef(
        ticker="601939",
        name="China Construction Bank",
        display="建设银行",
        secid="1.601939",  # suggest 实证：QuoteID=1.601939
        exchange="SSE",
        aliases=("建设银行", "建行", "601939"),
        brand_color="#0066b3",
        logo_domain="ccb.com",
        currency="CNY",
    ),
    CompanyRef(
        ticker="000858",
        name="Wuliangye",
        display="五粮液",
        secid="0.000858",  # suggest 实证：QuoteID=0.000858
        exchange="SZSE",
        aliases=("五粮液", "000858"),
        brand_color="#8b1a1a",
        logo_domain="wuliangye.com.cn",
        currency="CNY",
    ),
    CompanyRef(
        ticker="601899",
        name="Zijin Mining",
        display="紫金矿业",
        secid="1.601899",  # suggest 实证：QuoteID=1.601899
        exchange="SSE",
        aliases=("紫金矿业", "紫金", "601899"),
        brand_color="#a6192e",
        logo_domain="zjky.cn",
        currency="CNY",
    ),
    CompanyRef(
        ticker="688981",
        name="SMIC",
        display="中芯国际",
        secid="1.688981",  # suggest 实证：QuoteID=1.688981（科创板）
        exchange="SSE",
        aliases=("中芯国际", "中芯", "688981"),
        brand_color="#005e7d",
        logo_domain="smics.com",
        currency="CNY",
    ),
    # ---- 港股（HKD；secid 前缀 116=港交所）----
    CompanyRef(
        ticker="00700",
        name="Tencent",
        display="腾讯控股",
        secid="116.00700",  # push2 实测：f12=00700 f14=腾讯控股；kline 亦实测
        exchange="HKEX",
        aliases=("腾讯控股", "腾讯", "00700"),
        brand_color="#0052d9",
        logo_domain="tencent.com",
        currency="HKD",
    ),
    CompanyRef(
        ticker="09988",
        name="Alibaba Group",
        display="阿里巴巴",
        secid="116.09988",  # push2 实测：f12=09988 f14=阿里巴巴-W
        exchange="HKEX",
        aliases=("阿里巴巴", "阿里", "09988"),
        brand_color="#ff6a00",
        logo_domain="alibaba.com",
        currency="HKD",
    ),
    CompanyRef(
        ticker="03690",
        name="Meituan",
        display="美团",
        secid="116.03690",  # push2 实测：f12=03690 f14=美团-W
        exchange="HKEX",
        aliases=("美团", "03690"),
        brand_color="#ffc300",
        logo_domain="meituan.com",
        currency="HKD",
    ),
    CompanyRef(
        ticker="01810",
        name="Xiaomi Group",
        display="小米集团",
        secid="116.01810",  # push2 实测：f12=01810 f14=小米集团-W
        exchange="HKEX",
        aliases=("小米集团", "小米", "01810"),
        brand_color="#ff6900",
        logo_domain="mi.com",
        currency="HKD",
    ),
    CompanyRef(
        ticker="00388",
        name="HKEX",
        display="香港交易所",
        secid="116.00388",  # push2 实测：f12=00388 f14=香港交易所
        exchange="HKEX",
        aliases=("香港交易所", "港交所", "00388"),
        brand_color="#1c3f94",
        logo_domain="hkex.com.hk",
        currency="HKD",
    ),
    CompanyRef(
        ticker="09618",
        name="JD.com",
        display="京东集团",
        secid="116.09618",  # suggest 实证：QuoteID=116.09618（京东集团-SW）
        exchange="HKEX",
        aliases=("京东集团", "京东", "09618"),
        brand_color="#e1251b",
        logo_domain="jd.com",
        currency="HKD",
    ),
    CompanyRef(
        ticker="09999",
        name="NetEase",
        display="网易",
        secid="116.09999",  # suggest 实证：QuoteID=116.09999
        exchange="HKEX",
        aliases=("网易", "09999"),
        brand_color="#d43c33",
        logo_domain="163.com",
        currency="HKD",
    ),
    CompanyRef(
        ticker="01299",
        name="AIA Group",
        display="友邦保险",
        secid="116.01299",  # suggest 实证：QuoteID=116.01299
        exchange="HKEX",
        aliases=("友邦保险", "友邦", "01299"),
        brand_color="#d31145",
        logo_domain="aia.com",
        currency="HKD",
    ),
)

# 待上卡候选清单（H-02 纪律：只登记、不注册、不外呼）。
# - 已探明 secid 本轮未纳入（控制单批审计面）；
# - A+H 双重上市的 H 侧（同公司已注册 A 股，注册会造成别名抢注）。
# (secid, 名称, 不注册的原因)
_PENDING_STOCK_CANDIDATES: tuple[tuple[str, str, str], ...] = (
    ("1.600900", "长江电力", "已探明 secid，本轮未纳入（扩容候选）"),
    ("0.300059", "东方财富", "已探明 secid，本轮未纳入（别名与数据源名易混，待评估）"),
    ("116.02318", "中国平安(H)", "A+H 双重上市：已注册 A 股 601318"),
    ("116.02899", "紫金矿业(H)", "A+H 双重上市：已注册 A 股 601899"),
    ("116.00981", "中芯国际(H)", "A+H 双重上市：已注册 A 股 688981"),
    ("116.00939", "建设银行(H)", "A+H 双重上市：已注册 A 股 601939"),
    ("116.01211", "比亚迪股份(H)", "A+H 双重上市：已注册 A 股 002594"),
)

# 非上市公司：只登记有公开来源的估值说明，绝不接入行情链路。
# 口径说明（2026-09-13 用户裁定「AI/科技未上市企业用官方披露代表金融数据」）：
# 未上市公司无公开财报义务，登记值按来源分级标注——官方公告 > 公开报道；
# 绝不使用无法溯源的数字。
_OPENAI_VALUATION_SOURCE = (
    "OpenAI 官方融资公告（2026-03-31）：新一轮融资承诺资金 1220 亿美元、"
    "投后估值 8520 亿美元。来源 https://openai.com/index/accelerating-the-next-phase-ai/"
)
_ANTHROPIC_VALUATION_SOURCE = (
    "Anthropic 官方公告（2025-09，F 轮融资 130 亿美元，投后估值 1830 亿美元）。"
    "来源 https://www.anthropic.com/news/anthropic-raises-series-f-at-usd183b-post-money-valuation"
)
_BYTEDANCE_VALUATION_SOURCE = (
    "公开报道（2024-12 员工股回购定价，对应估值约 3000 亿美元；字节跳动未上市、"
    "不发布官方财报，此为回购定价口径，非官方披露）"
)

NON_PUBLIC_EQUITIES: dict[str, NonPublicEquityNote] = {
    "OPENAI": NonPublicEquityNote(
        key="OPENAI",
        name="OpenAI",
        status=FinanceDataStatus.NON_PUBLIC,
        statement="OpenAI 目前未上市，没有股票价格/成交量可查。",
        valuation_usd=852_000_000_000.0,
        valuation_as_of=date(2026, 3, 31),
        valuation_source=_OPENAI_VALUATION_SOURCE,
        note="只提供有来源的公开估值，不提供股价/OHLC。",
    ),
    "ANTHROPIC": NonPublicEquityNote(
        key="ANTHROPIC",
        name="Anthropic",
        status=FinanceDataStatus.NON_PUBLIC,
        statement="Anthropic 目前未上市，没有股票价格/成交量可查。",
        valuation_usd=183_000_000_000.0,
        valuation_as_of=date(2025, 9, 2),
        valuation_source=_ANTHROPIC_VALUATION_SOURCE,
        note="官方融资公告口径；不提供股价/OHLC。",
    ),
    "BYTEDANCE": NonPublicEquityNote(
        key="BYTEDANCE",
        name="字节跳动 ByteDance",
        status=FinanceDataStatus.NON_PUBLIC,
        statement="字节跳动目前未上市，没有股票价格/成交量可查。",
        valuation_usd=300_000_000_000.0,
        valuation_as_of=date(2024, 12, 31),
        valuation_source=_BYTEDANCE_VALUATION_SOURCE,
        note="回购定价的公开报道口径（非官方财报）；不提供股价/OHLC。",
    ),
}

_BY_ALIAS: dict[str, str] = {}
_ALL_LISTED_COMPANIES: tuple[CompanyRef, ...] = (
    _LISTED_COMPANIES + _CN_HK_LISTED_COMPANIES
)
for _ref in _ALL_LISTED_COMPANIES:
    _BY_ALIAS[_ref.ticker.lower()] = _ref.ticker
    for _alias in _ref.aliases:
        _BY_ALIAS[_alias.lower()] = _ref.ticker
for _key in NON_PUBLIC_EQUITIES:
    _BY_ALIAS[_key.lower()] = _key
# 非上市公司中文/惯用别名（2026-09-13 注册表扩充）。
_BY_ALIAS.update(
    {
        "open ai": "OPENAI",
        "anthropic ai": "ANTHROPIC",
        "字节跳动": "BYTEDANCE",
        "字节": "BYTEDANCE",
        "bytedance": "BYTEDANCE",
    }
)

_COMPANY_BY_TICKER: dict[str, CompanyRef] = {
    ref.ticker: ref for ref in _ALL_LISTED_COMPANIES
}


def list_listed_companies() -> tuple[CompanyRef, ...]:
    """当前注册的全部上市公司（美股 9 + A股/港股 17，H-02 扩容后）。"""
    return _ALL_LISTED_COMPANIES


def list_cn_hk_companies() -> tuple[CompanyRef, ...]:
    """A股/港股注册切片（H-02；快查批量面板不含这些公司）。"""
    return _CN_HK_LISTED_COMPANIES


def find_company_ref(ticker: str) -> CompanyRef | None:
    """按 ticker 查注册信息；未注册返回 None。"""
    return _COMPANY_BY_TICKER.get(ticker.strip().upper())


def resolve_company_query(text: str) -> str | None:
    """从用户文本解析公司意图；命中返回 ticker（含非上市公司 key）。

    ASCII 别名走词边界匹配（复用 ``_alias_hit``，防 "metadata" 误中 "meta"，
    与 ``resolve_stock_symbols`` 同一套口径）；中文别名保持子串语义。
    """
    lowered = (text or "").lower().strip()
    if not lowered or len(lowered) > 64:
        return None
    # 长别名优先，避免未来出现互为前缀的别名时误命中。
    for alias in sorted(_BY_ALIAS, key=len, reverse=True):
        if _alias_hit(alias, lowered):
            return _BY_ALIAS[alias]
    return None


# ==================== 网络出口（测试 monkeypatch 单点拦截） ====================

_QUOTE_URL = (
    "https://push2.eastmoney.com/api/qt/ulist.np/get"
    "?fltt=2&secids={secid}&fields=f2,f3,f4,f12,f14,f20,f47,f48,f84,f85"
)
_KLINE_URL = (
    "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    "?secid={secid}&fields1=f1&fields2=f51,f52,f53,f54,f55,f56"
    "&klt=101&fqt=1&lmt={days}&end=20500101"
)

_MAX_PAYLOAD_BYTES = 1024 * 1024
_SOURCE_QUOTE = "eastmoney"
_SOURCE_KLINE = "eastmoney_kline"


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _secid_for(ticker: str) -> str:
    """已注册公司取注册 secid；未注册原样返回（防御，正常不走到）。"""
    ref = _COMPANY_BY_TICKER.get(ticker)
    return ref.secid if ref is not None else ticker


def _fetch_quote_payload(ticker: str, timeout: float) -> Any:
    """现价+市值单点网络出口（含 f20 总市值；实测字段，缺失安全降级）。"""
    return http_get_json(
        _QUOTE_URL.format(secid=urllib.parse.quote(_secid_for(ticker))),
        timeout=max(1.0, float(timeout)),
        max_bytes=_MAX_PAYLOAD_BYTES,
    )


def _fetch_kline_payload(ticker: str, days: int, timeout: float) -> Any:
    """K 线单点网络出口：测试 monkeypatch 本函数即可拦截全部外呼。"""
    return http_get_json(
        _KLINE_URL.format(
            secid=urllib.parse.quote(_secid_for(ticker)), days=max(1, int(days))
        ),
        timeout=max(1.0, float(timeout)),
        max_bytes=_MAX_PAYLOAD_BYTES,
    )


# ==================== 解析（防御式；缺字段走状态不造数） ====================


def _as_float(value: Any) -> float | None:
    """fltt=2 下正常值是小数；停牌/缺数可能是 "-" 或缺失。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _first_diff_row(payload: Any) -> dict[str, Any] | None:
    """ulist 包络取第一行 diff（单 secid 请求只会有 0/1 行）。"""
    data = payload.get("data") if isinstance(payload, dict) else None
    diff = data.get("diff") if isinstance(data, dict) else None
    if isinstance(diff, list) and diff and isinstance(diff[0], dict):
        return diff[0]
    return None


def _parse_date(text: str) -> date | None:
    try:
        return date.fromisoformat(text.strip()[:10])
    except (ValueError, AttributeError):
        return None


def _parse_quote(
    ticker: str, ref: CompanyRef | None, payload: Any
) -> EquityQuote:
    """解析现价行；name/价格缺失走 UNAVAILABLE + note，绝不造 0。"""
    # 币种跟随上市币种（H-02）：美股 USD / A股 CNY / 港股 HKD。
    currency = ref.currency if ref is not None else "USD"
    row = _first_diff_row(payload) or {}
    price = _as_float(row.get("f2")) if row else None
    change_pct = _as_float(row.get("f3")) if row else None
    if price is None:
        return EquityQuote(
            ticker=ticker,
            name=ref.display if ref else "",
            exchange=ref.exchange if ref else "",
            currency=currency,
            price=None,
            change_pct=change_pct,
            change_abs=None,
            source=_SOURCE_QUOTE,
            as_of=_now_utc(),
            status=FinanceDataStatus.UNAVAILABLE,
            delayed=True,
            note="上游未返回可用现价（字段缺失或停牌）",
        )
    # H-03（2026-09-14 审查裁定）：f47/f48/f84/f85（成交量/成交额/流通股/
    # 总股本）从未真机实测、单位口径可能差 100 倍（f47 疑似「手」需 ×100，
    # f84/f85 疑似「股」）——**未实测字段不上卡，一律置 None**。待实测回填
    # 标记：真机核验 push2 字段单位后在此恢复映射（诚实优先于功能保持）。
    return EquityQuote(
        ticker=ticker,
        name=str(row.get("f14") or (ref.display if ref else "") or ""),
        exchange=ref.exchange if ref else "",
        currency=currency,
        price=price,
        change_pct=change_pct,
        change_abs=_as_float(row.get("f4")),
        volume=None,  # TODO(H-03 待实测回填): f47 成交量（手→股 ×100 未核验）
        amount=None,  # TODO(H-03 待实测回填): f48 成交额（币种/单位未核验）
        float_shares=None,  # TODO(H-03 待实测回填): f85 流通股
        total_shares=None,  # TODO(H-03 待实测回填): f84 总股本
        source=_SOURCE_QUOTE,
        as_of=_now_utc(),
        status=FinanceDataStatus.OK,
        delayed=True,
        note="",
    )


def _parse_klines(payload: Any, ref: CompanyRef | None) -> OHLCVSeries:
    """解析 K 线行；坏行逐行跳过（degraded），全失败 unavailable。"""
    ticker = ref.ticker if ref else "UNKNOWN"
    display = ref.display if ref else ""
    data = payload.get("data") if isinstance(payload, dict) else None
    raw_rows = data.get("klines") if isinstance(data, dict) else None
    bars: list[OHLCVBar] = []
    if isinstance(raw_rows, list):
        for raw in raw_rows:
            parts = str(raw).split(",")
            # fields2=f51,f52,f53,f54,f55,f56 → 日期,开,收,高,低,量（惯例，
            # f51/f53 已验证；f52/f54/f55/f56 未实测，逐字段防御）。
            if len(parts) < 5:
                continue
            trade_date = _parse_date(parts[0])
            open_ = _as_float(parts[1])
            close = _as_float(parts[2])
            high = _as_float(parts[3])
            low = _as_float(parts[4])
            volume = _as_float(parts[5]) if len(parts) >= 6 else None
            if (
                trade_date is None
                or open_ is None
                or close is None
                or high is None
                or low is None
            ):
                continue
            try:
                bars.append(
                    OHLCVBar(
                        trade_date=trade_date,
                        open=open_,
                        high=high,
                        low=low,
                        close=close,
                        volume=volume,
                    )
                )
            except Exception:  # noqa: S112, BLE001 - 单行校验失败即跳过该行。
                continue
    if not bars:
        return OHLCVSeries(
            ticker=ticker,
            name=display,
            currency=ref.currency if ref is not None else "USD",
            bars=[],
            source=_SOURCE_KLINE,
            as_of=_now_utc(),
            status=FinanceDataStatus.UNAVAILABLE,
            delayed=True,
            note="上游未返回可用 K 线（网络失败或字段全缺失）",
        )
    status = (
        FinanceDataStatus.OK
        if isinstance(raw_rows, list) and len(bars) == len(raw_rows)
        else FinanceDataStatus.DEGRADED
    )
    return OHLCVSeries(
        ticker=ticker,
        name=display,
        currency=ref.currency if ref is not None else "USD",
        bars=bars,
        source=_SOURCE_KLINE,
        as_of=_now_utc(),
        status=status,
        delayed=True,
        note="" if status is FinanceDataStatus.OK else "部分 K 线行字段缺失已跳过",
    )


def _non_public_series(ticker: str) -> OHLCVSeries:
    note = NON_PUBLIC_EQUITIES.get(ticker)
    return OHLCVSeries(
        ticker=ticker,
        name=note.name if note else ticker,
        currency="USD",
        bars=[],
        source="",
        as_of=_now_utc(),
        status=FinanceDataStatus.NON_PUBLIC,
        delayed=True,
        note="非上市公司无公开行情",
    )


def _non_public_quote(ticker: str) -> EquityQuote:
    note = NON_PUBLIC_EQUITIES.get(ticker)
    return EquityQuote(
        ticker=ticker,
        name=note.name if note else ticker,
        currency="USD",
        source="",
        as_of=_now_utc(),
        status=FinanceDataStatus.NON_PUBLIC,
        delayed=True,
        note="非上市公司无股价",
    )


# ==================== 对外抓取入口（绝不抛异常） ====================


def fetch_stock_quote(ticker: str, timeout_seconds: float = 6.0) -> EquityQuote:
    """上市股票现价快照；失败走 UNAVAILABLE 状态，绝不抛异常。"""
    normalized = (ticker or "").strip().upper()
    ref = _COMPANY_BY_TICKER.get(normalized)
    if normalized in NON_PUBLIC_EQUITIES:
        return _non_public_quote(normalized)
    if ref is None:
        return EquityQuote(
            ticker=normalized or "UNKNOWN",
            source="",
            status=FinanceDataStatus.UNAVAILABLE,
            note="未注册的公司（注册表见 list_listed_companies）",
        )
    # G2：单 secid 请求整行缺失（缺行）= 限流空响应签名 → 退避重试一次；
    # 行在但字段缺失（停牌等）不重试，照旧按字段缺失降级；真异常不重试。
    attempts = 2 if retry_on_empty_enabled() else 1
    for attempt in range(attempts):
        try:
            payload = _network_retry(lambda: _fetch_quote_payload(normalized, timeout_seconds))
        except Exception as exc:  # noqa: BLE001 - 行情失败静默降级。
            return EquityQuote(
                ticker=normalized,
                name=ref.display,
                exchange=ref.exchange,
                currency=ref.currency,
                price=None,
                source=_SOURCE_QUOTE,
                as_of=_now_utc(),
                status=FinanceDataStatus.UNAVAILABLE,
                delayed=True,
                note=f"行情拉取失败：{type(exc).__name__}",
            )
        if _first_diff_row(payload) is not None or attempt + 1 >= attempts:
            return _parse_quote(normalized, ref, payload)
        empty_backoff_sleep()
    raise AssertionError("unreachable")  # pragma: no cover - 末次必返回


def fetch_stock_ohlcv(
    ticker: str, days: int = 90, timeout_seconds: float = 6.0
) -> OHLCVSeries:
    """上市股票近 N 日 K 线（旧→新）；失败/非上市走状态对象，绝不抛异常。"""
    normalized = (ticker or "").strip().upper()
    ref = _COMPANY_BY_TICKER.get(normalized)
    if normalized in NON_PUBLIC_EQUITIES:
        return _non_public_series(normalized)
    if ref is None:
        return OHLCVSeries(
            ticker=normalized or "UNKNOWN",
            source="",
            status=FinanceDataStatus.UNAVAILABLE,
            note="未注册的公司（注册表见 list_listed_companies）",
        )
    # G2：空 klines（空 JSON/缺行）退避后至多重试 1 次；真异常不重试；
    # 仍空走既有 UNAVAILABLE 状态对象。
    attempts = 2 if retry_on_empty_enabled() else 1
    for attempt in range(attempts):
        try:
            payload = _network_retry(lambda: _fetch_kline_payload(normalized, days, timeout_seconds))
            series = _parse_klines(payload, ref)
        except Exception as exc:  # noqa: BLE001
            return OHLCVSeries(
                ticker=normalized,
                name=ref.display,
                currency="USD",
                bars=[],
                source=_SOURCE_KLINE,
                as_of=_now_utc(),
                status=FinanceDataStatus.UNAVAILABLE,
                delayed=True,
                note=f"K 线拉取失败：{type(exc).__name__}",
            )
        if series.bars or attempt + 1 >= attempts:
            return series
        empty_backoff_sleep()
    raise AssertionError("unreachable")  # pragma: no cover - 末次必返回


def fetch_market_cap(ticker: str, timeout_seconds: float = 6.0) -> MarketCap:
    """总市值快照；f20 缺失/非法 → value=None + UNAVAILABLE（绝不 0）。"""
    normalized = (ticker or "").strip().upper()
    ref = _COMPANY_BY_TICKER.get(normalized)
    if normalized in NON_PUBLIC_EQUITIES:
        note = NON_PUBLIC_EQUITIES[normalized]
        return MarketCap(
            ticker=normalized,
            value=note.valuation_usd,
            currency="USD",
            as_of=None,
            source="公开披露",
            status=FinanceDataStatus.NON_PUBLIC,
            note="非上市公司：仅公开估值（见 openai_equity_note），非市值",
        )
    if ref is None:
        return MarketCap(
            ticker=normalized or "UNKNOWN",
            value=None,
            source="",
            status=FinanceDataStatus.UNAVAILABLE,
            note="未注册的公司",
        )
    # H-02 诚实门（2026-09-14）：非美元上市（A股 CNY / 港股 HKD）的 f20
    # 市值跟随上市币种，而卡面/文本的市值行币种标注能力硬编码「亿美元」
    # （能力层属并行代理域，本席不可触碰）——直接放行会把人民币/港元市值
    # 错标成美元（7-8 倍失真）。按「不能如实标注的字段不上卡」（H-03 同款
    # 纪律）：置 None + DEGRADED + 待回填标记；能力层支持币种标注后删除
    # 本分支即恢复。
    if ref.currency != "USD":
        return MarketCap(
            ticker=normalized,
            value=None,
            currency=ref.currency,
            source=_SOURCE_QUOTE,
            as_of=_now_utc(),
            status=FinanceDataStatus.DEGRADED,
            note=(
                f"市值为上市币种（{ref.currency}）口径，币种标注能力未就绪，"
                "先不上卡（待回填）"
            ),
        )
    # G2：缺行=限流空响应签名 → 退避重试一次；行在但 f20 缺失不重试；
    # 真异常不重试。
    attempts = 2 if retry_on_empty_enabled() else 1
    for attempt in range(attempts):
        try:
            payload = _network_retry(lambda: _fetch_quote_payload(normalized, timeout_seconds))
        except Exception as exc:  # noqa: BLE001
            return MarketCap(
                ticker=normalized,
                value=None,
                currency="USD",
                source=_SOURCE_QUOTE,
                as_of=_now_utc(),
                status=FinanceDataStatus.UNAVAILABLE,
                note=f"市值拉取失败：{type(exc).__name__}",
            )
        if _first_diff_row(payload) is not None or attempt + 1 >= attempts:
            row = _first_diff_row(payload)
            value = _as_float(row.get("f20")) if row else None
            if value is None:
                return MarketCap(
                    ticker=normalized,
                    value=None,
                    currency="USD",
                    source=_SOURCE_QUOTE,
                    as_of=_now_utc(),
                    status=FinanceDataStatus.UNAVAILABLE,
                    note="上游未返回总市值字段（f20 实测字段，缺失即如实降级）",
                )
            return MarketCap(
                ticker=normalized,
                value=value,
                currency="USD",
                source=_SOURCE_QUOTE,
                as_of=_now_utc(),
                status=FinanceDataStatus.OK,
                note="",
            )
        empty_backoff_sleep()
    raise AssertionError("unreachable")  # pragma: no cover - 末次必返回


# ==================== 指标计算（纯函数，离线可验证） ====================

# 币种展示口径（H-02）：现价单位与市值单位分开——现价 CNY 惯用「元」，
# 市值 CNY 惯用「亿/万亿人民币」；未知币种原样展示（绝不默认成美元）。
_CURRENCY_PRICE_UNITS: dict[str, str] = {"USD": "美元", "CNY": "元", "HKD": "港元"}
_CURRENCY_CAP_UNITS: dict[str, str] = {"USD": "美元", "CNY": "人民币", "HKD": "港元"}


def _price_unit(currency: str) -> str:
    """现价单位词；未登记币种用 ISO 代码本身（不冒充美元）。"""
    code = (currency or "").strip().upper()
    return _CURRENCY_PRICE_UNITS.get(code, code or "USD")


def _cap_unit(currency: str) -> str:
    """市值单位词；未登记币种用 ISO 代码本身（不冒充美元）。"""
    code = (currency or "").strip().upper()
    return _CURRENCY_CAP_UNITS.get(code, code or "USD")


def compute_kdj(
    bars: list[OHLCVBar] | tuple[OHLCVBar, ...], period: int = 9
) -> KDJSnapshot | None:
    """由多日 K 线计算 KDJ（经典 1/3 平滑；窗口不足返回 None）。

    RSV = (C - L_n) / (H_n - L_n) * 100；窗口内高低相等（一字板）时 RSV=50
    （中性，不放大信号）。K_t = 2/3·K_{t-1} + 1/3·RSV，D 同理平滑 K，
    J = 3K - 2D；初值 K_0 = D_0 = 50。
    """
    rows = list(bars)
    if period < 1 or len(rows) < period:
        return None
    k_prev, d_prev = 50.0, 50.0
    k = d = 50.0
    for index in range(period - 1, len(rows)):
        window = rows[index - period + 1 : index + 1]
        high_n = max(bar.high for bar in window)
        low_n = min(bar.low for bar in window)
        close = window[-1].close
        rsv = 50.0 if high_n == low_n else (close - low_n) / (high_n - low_n) * 100.0
        k = (2.0 / 3.0) * k_prev + (1.0 / 3.0) * rsv
        d = (2.0 / 3.0) * d_prev + (1.0 / 3.0) * k
        k_prev, d_prev = k, d
    last = rows[-1]
    return KDJSnapshot(
        trade_date=last.trade_date, k=k, d=d, j=3.0 * k - 2.0 * d, period=period
    )


# ==================== 技术指标 II：MACD / RSI / WR / CCI（审查 H-08） ====================
# 审查 H-08（2026-09-15）：个股行情此前只有 KDJ，缺 MACD/RSI/WR/CCI。
# 本段全部纯本地计算（标准公式、零第三方依赖——本模块未导入 pandas，
# 故纯 Python 实现并与手算基准对拍，见 tests/test_stock_technical_indicators.py）。
# 入参与 compute_kdj 同形态（OHLCV 序列）；窗口不足一律返回 None——
# 宁缺毋滥，绝不造数。快照类型暂驻本模块（contracts/finance.py 属并行
# 会话文件域不可触碰）；字段形态与 KDJSnapshot 对齐（trade_date + 数值
# + 周期），后续若收编入 contracts 只需平移类型定义，计算零改动。


@dataclass(frozen=True)
class MACDSnapshot:
    """MACD 快照（审查 H-08）；柱线用中国行情软件口径 hist = 2×(DIF−DEA)。"""

    dif: float
    dea: float
    hist: float
    trade_date: date | None = None
    fast_period: int = 12
    slow_period: int = 26
    signal_period: int = 9


@dataclass(frozen=True)
class RSISnapshot:
    """RSI（Wilder 平滑）快照（审查 H-08）。"""

    value: float
    trade_date: date | None = None
    period: int = 14


@dataclass(frozen=True)
class WRSnapshot:
    """威廉指标快照（审查 H-08）；0~100 展示口径（越低越贴近超买）。"""

    value: float
    trade_date: date | None = None
    period: int = 14


@dataclass(frozen=True)
class CCISnapshot:
    """CCI 顺势指标快照（审查 H-08）。"""

    value: float
    trade_date: date | None = None
    period: int = 20


def _ema_sma_seeded(values: Sequence[float], period: int) -> list[float]:
    """SMA 种子的 EMA 序列（自第 period 个点起，首值 = 前 period 点算术均值）。

    东财/通达信等中国行情软件与教科书一致的口径：EMA 首值取 SMA 种子，
    之后 EMA_t = EMA_{t-1} + (2/(period+1))·(x_t − EMA_{t-1})。
    长度不足 period 时返回空列表（由调用方走 None 门）。
    """
    if period < 1 or len(values) < period:
        return []
    alpha = 2.0 / (period + 1.0)
    ema = sum(values[:period]) / period
    out = [ema]
    for value in values[period:]:
        ema += alpha * (value - ema)
        out.append(ema)
    return out


def compute_macd(
    bars: list[OHLCVBar] | tuple[OHLCVBar, ...],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> MACDSnapshot | None:
    """MACD（12/26/9 标准 EMA 口径；窗口不足返回 None，审查 H-08）。

    DIF = EMA_fast − EMA_slow；DEA = DIF 的 EMA(signal)（同 SMA 种子）；
    柱 hist = 2×(DIF−DEA)（中国行情软件口径，与东财/通达信展示对齐）。
    最少需要 slow + signal − 1 根 K 线（默认 26+9−1=34）：EMA_slow 首个
    有效值在第 slow 根，DIF 从此起算，DEA 再需 signal 个 DIF 值。
    """
    closes = [bar.close for bar in bars]
    if fast < 1 or slow <= fast or signal < 1 or len(closes) < slow + signal - 1:
        return None
    ema_fast = _ema_sma_seeded(closes, fast)
    ema_slow = _ema_sma_seeded(closes, slow)
    # 长度门已保证 ema_slow 非空；两序列按尾部对齐（DIF 自第 slow 根起有效）。
    dif_tail = [f - s for f, s in zip(ema_fast[-len(ema_slow) :], ema_slow)]
    dea_tail = _ema_sma_seeded(dif_tail, signal)
    if not dea_tail:
        return None  # pragma: no cover - 长度门已排除，防御分支
    dif = dif_tail[-1]
    dea = dea_tail[-1]
    return MACDSnapshot(
        dif=dif,
        dea=dea,
        hist=2.0 * (dif - dea),
        trade_date=bars[-1].trade_date,
        fast_period=fast,
        slow_period=slow,
        signal_period=signal,
    )


def compute_rsi(
    bars: list[OHLCVBar] | tuple[OHLCVBar, ...], period: int = 14
) -> RSISnapshot | None:
    """RSI（Wilder 1978 平滑口径；窗口不足返回 None，审查 H-08）。

    首个均值 = 前 period 个涨/跌幅的简单平均；之后
    avgGain_t = (avgGain_{t-1}×(period−1) + gain_t) / period（avgLoss 同理）。
    RSI = 100 − 100/(1 + avgGain/avgLoss)；avgLoss=0 且 avgGain>0 → 100；
    全平（两者皆 0）→ 50 中性（与 KDJ 一字板 RSV=50 同纪律，不造极值）。
    需要 period+1 根 K 线（差分出 period 个逐日涨跌）。
    """
    closes = [bar.close for bar in bars]
    if period < 1 or len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(delta, 0.0) for delta in deltas]
    losses = [max(-delta, 0.0) for delta in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0.0:
        value = 100.0 if avg_gain > 0.0 else 50.0
    else:
        value = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return RSISnapshot(
        value=value, trade_date=bars[-1].trade_date, period=period
    )


def compute_wr(
    bars: list[OHLCVBar] | tuple[OHLCVBar, ...], period: int = 14
) -> WRSnapshot | None:
    """威廉指标 WR（中国行情软件 0~100 口径；窗口不足返回 None，审查 H-08）。

    WR = (H_n − C) / (H_n − L_n) × 100：值越低收盘越贴近窗口高点（偏超买），
    越高越贴近低点（偏超卖）。与拉里·威廉斯原始 −0~−100 口径差一个符号，
    此处跟随东财/通达信展示习惯（与 KDJ/RSI 同属 0~100 语义族）。
    窗口高低相等（一字板）→ 50 中性，不造极值。
    """
    rows = list(bars)
    if period < 1 or len(rows) < period:
        return None
    window = rows[-period:]
    high_n = max(bar.high for bar in window)
    low_n = min(bar.low for bar in window)
    close = window[-1].close
    value = (
        50.0
        if high_n == low_n
        else (high_n - close) / (high_n - low_n) * 100.0
    )
    return WRSnapshot(
        value=value, trade_date=rows[-1].trade_date, period=period
    )


def compute_cci(
    bars: list[OHLCVBar] | tuple[OHLCVBar, ...], period: int = 20
) -> CCISnapshot | None:
    """CCI 顺势指标（Donald Lambert 标准口径；窗口不足返回 None，审查 H-08）。

    TP = (H+L+C)/3；CCI = (TP − MA(TP, n)) / (0.015 × MD)，
    MD = 窗口内 |TP − MA| 的均值。MD=0（全窗口 TP 恒定，一字板族）→ 0
    （分母为零不可除，取中性 0，不造 ±∞）。
    """
    rows = list(bars)
    if period < 1 or len(rows) < period:
        return None
    window = rows[-period:]
    tps = [(bar.high + bar.low + bar.close) / 3.0 for bar in window]
    ma_tp = sum(tps) / period
    md = sum(abs(tp - ma_tp) for tp in tps) / period
    value = 0.0 if md == 0.0 else (tps[-1] - ma_tp) / (0.015 * md)
    return CCISnapshot(
        value=value, trade_date=rows[-1].trade_date, period=period
    )


def compute_all_technical_indicators(
    bars: list[OHLCVBar] | tuple[OHLCVBar, ...],
) -> tuple[
    MACDSnapshot | None,
    RSISnapshot | None,
    WRSnapshot | None,
    CCISnapshot | None,
]:
    """一次算齐 MACD/RSI/WR/CCI（审查 H-08）；每个独立判窗口，不足各自 None。

    卡面/brief 接线统一走本函数，保证四指标口径单一事实来源。
    """
    return (
        compute_macd(bars),
        compute_rsi(bars),
        compute_wr(bars),
        compute_cci(bars),
    )


# 箱形图最少样本：多日分布才有意义；单日 OHLC 不是分布。
MIN_BOXPLOT_SAMPLES = 5


def _quartile_type7(sorted_values: list[float], q: float) -> float:
    """type-7 线性插值分位数（numpy 默认 / Excel QUARTILE.INC 口径）。"""
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction


def boxplot_stats(
    values: list[float] | tuple[float, ...],
    label: str = "",
    min_samples: int = MIN_BOXPLOT_SAMPLES,
) -> tuple[BoxPlotStats | None, str]:
    """五数概括；样本不足返回 ``(None, "insufficient_data")``，绝不造分布。

    返回 (stats, status)：status ∈ ok / insufficient_data / invalid_input。
    """
    try:
        cleaned = [float(v) for v in values]
    except (TypeError, ValueError):
        return None, "invalid_input"
    cleaned = [v for v in cleaned if not math.isnan(v)]  # 去 NaN
    if not cleaned:
        return None, "invalid_input"
    if len(cleaned) < max(1, int(min_samples)):
        return None, "insufficient_data"
    ordered = sorted(cleaned)
    stats = BoxPlotStats(
        label=label,
        n=len(ordered),
        minimum=ordered[0],
        q1=_quartile_type7(ordered, 0.25),
        median=_quartile_type7(ordered, 0.50),
        q3=_quartile_type7(ordered, 0.75),
        maximum=ordered[-1],
    )
    return stats, "ok"


def build_boxplot_from_ohlcv(
    series: OHLCVSeries,
    *,
    field: str = "close",
    min_samples: int = MIN_BOXPLOT_SAMPLES,
) -> tuple[BoxPlotStats | None, str]:
    """多日 K 线 → 按日取一个数值（默认收盘）的分布五数。

    图表语义守门：样本数 < min_samples（含单日 OHLC）一律拒绝，
    返回 (None, "insufficient_data")——单日 K 线绝不能画成箱形图。
    """
    rows = list(series.bars) if series is not None else []
    if field == "close":
        values: list[float] = [bar.close for bar in rows]
    elif field == "open":
        values = [bar.open for bar in rows]
    elif field == "high":
        values = [bar.high for bar in rows]
    elif field == "low":
        values = [bar.low for bar in rows]
    else:
        return None, "invalid_input"
    label = f"{series.ticker} 近{len(values)}日{field}分布" if rows else ""
    return boxplot_stats(values, label=label, min_samples=min_samples)


# ==================== 非上市公司（OpenAI）说明 ====================


def openai_equity_note() -> NonPublicEquityNote:
    """OpenAI 非上市说明（有来源的公开估值；结构性无任何价格字段）。"""
    return NON_PUBLIC_EQUITIES["OPENAI"].model_copy()


def format_stock_brief(
    quote: EquityQuote,
    series: OHLCVSeries | None,
    kdj: KDJSnapshot | None,
    cap: MarketCap | None,
) -> str:
    """股票查询的纯文本快报；任何一块缺数据都给明确状态而非编数字。"""
    ref = _COMPANY_BY_TICKER.get(quote.ticker)
    display = ref.display if ref else (quote.name or quote.ticker)
    suffix = f" · {quote.exchange}" if quote.exchange else ""
    header = f"{display}（{quote.ticker}{suffix}）"
    if quote.status is FinanceDataStatus.NON_PUBLIC:
        note = NON_PUBLIC_EQUITIES.get(quote.ticker)
        if note is None:
            return f"{header}：未上市公司，无股价可查。"
        valuation = ""
        if note.valuation_usd is not None and note.valuation_as_of is not None:
            value_yi = note.valuation_usd / 1e8
            valuation = (
                f"最近公开估值：约 {value_yi:.0f} 亿美元"
                f"（{note.valuation_as_of.year} 年 {note.valuation_as_of.month} 月）"
            )
        return (
            f"{header}\n{note.statement}\n{valuation}\n来源：{note.valuation_source}"
        ).strip()
    if quote.price is None or quote.status is FinanceDataStatus.UNAVAILABLE:
        reason = quote.note or "上游失败"
        return f"{header}：暂无可用行情（{reason}），先不瞎猜数字。"
    lines = [header]
    pct_text = (
        f"{quote.change_pct:+.2f}%" if quote.change_pct is not None else "涨跌幅未知"
    )
    # H-02：币种文案自适应（美元/元/港元），跟随上市币种，不再硬编码美元。
    line = f"现价 {quote.price:.2f} {_price_unit(quote.currency)} {pct_text}"
    if quote.change_abs is not None:
        line += f"（{quote.change_abs:+.2f}）"
    lines.append(line)
    if series is not None and series.bars:
        last = series.bars[-1]
        lines.append(
            f"最新交易日 {last.trade_date.isoformat()}："
            f"开 {last.open:.2f} / 高 {last.high:.2f} / 低 {last.low:.2f}"
        )
        lines.append(f"近 {len(series.bars)} 个交易日收盘序列可用（趋势见折线）")
    elif series is not None and series.status is FinanceDataStatus.UNAVAILABLE:
        lines.append("历史 K 线暂缺（数据源失败）")
    if kdj is not None:
        lines.append(
            f"KDJ({kdj.period})：K {kdj.k:.2f} / D {kdj.d:.2f} / J {kdj.j:.2f}"
        )
    else:
        lines.append("KDJ 暂缺（交易日不足 9 天，不算）")
    # 审查 H-08：MACD/RSI/WR/CCI 纯本地补齐——非空才展示（宁缺毋滥）。
    # 与 KDJ「暂缺也报状态」不同：新指标窗口不足时 None 静默跳过，
    # 不占版面也不给半截数字；单股链路默认拉 90 根（截 60），四指标
    # 常态齐全，只有极端缺数时才整体消失。
    if series is not None and series.bars:
        macd, rsi, wr, cci = compute_all_technical_indicators(series.bars)
        if macd is not None:
            lines.append(
                f"MACD({macd.fast_period},{macd.slow_period},"
                f"{macd.signal_period})：DIF {macd.dif:+.4f} / "
                f"DEA {macd.dea:+.4f} / 柱 {macd.hist:+.4f}"
            )
        if rsi is not None:
            lines.append(f"RSI({rsi.period})：{rsi.value:.2f}")
        if wr is not None:
            lines.append(f"WR({wr.period})：{wr.value:.2f}")
        if cci is not None:
            lines.append(f"CCI({cci.period})：{cci.value:+.2f}")
    if cap is not None and cap.value is not None:
        value_yi = cap.value / 1e8
        unit = _cap_unit(cap.currency)
        if value_yi >= 10_000:
            lines.append(f"总市值 ≈ {value_yi / 10_000:.2f} 万亿{unit}")
        else:
            lines.append(f"总市值 ≈ {value_yi:,.0f} 亿{unit}")
    else:
        # H-02：市值缺失原因如实透出（含非美元市值「待回填」诚实门）。
        reason = (cap.note if cap is not None else "") or "上游字段缺失"
        lines.append(f"总市值暂缺（{reason}）")
    stamp = quote.as_of.strftime("%Y-%m-%d %H:%M UTC") if quote.as_of else "时间未知"
    lines.append(f"数据源 东财行情（延迟行情）· {stamp} · 状态 {status_or_unknown(quote.status).value}")
    return "\n".join(lines)


# ==================== 快查批量链路（9 家科技巨头，原任务 API） ====================

# 宇宙表 (secid, symbol, 中文名, market, 货币)，顺序即展示顺序；secid 与
# 注册表 _LISTED_COMPANIES 同源（2026-09-12 实测 105=NASDAQ / 106=NYSE）。
# H-02（2026-09-14）：面板宇宙刻意维持 9 家美股不变——面板文案「美股科技
# 巨头」语义不动；A股/港股（_CN_HK_LISTED_COMPANIES）只走单股链路。
_STOCK_UNIVERSE: tuple[tuple[str, str, str, str, str], ...] = tuple(
    (ref.secid, ref.ticker, ref.display, ref.exchange, "USD")
    for ref in _LISTED_COMPANIES
)

# 批量快照：一次 ulist 拉全部 9 只（实测字段集，含 f20 总市值）。
_QUOTES_URL = (
    "https://push2.eastmoney.com/api/qt/ulist.np/get"
    "?fltt=2&secids={secids}"
    "&fields=f2,f3,f4,f5,f12,f13,f14,f15,f16,f17,f18,f20"
)

_QUOTE_CACHE_TTL_DEFAULT_SECONDS = 60.0
_QUOTE_CACHE: tuple[float, tuple[StockQuote, ...]] | None = None

# K 线最多取 60 根（kline 接口 lmt=60），history 截断在客户端完成。
_MAX_HISTORY_POINTS = 60
_HISTORY_CACHE_TTL_SECONDS = 600.0
_HISTORY_CACHE: dict[str, tuple[float, tuple[PricePoint, ...]]] = {}

# 红涨绿跌（A 股配色习惯），横盘白点；与 market_data 同一套标记。
_MARK_UP = "🔴"
_MARK_DOWN = "🟢"
_MARK_FLAT = "⚪"

# 审查 Q-01：数据源失败文案统一入 user_copy 池（守岸人语气轮换），不再硬编码。
def _empty_stocks_text() -> str:
    return random.choice(user_copy.DATASOURCE_FAILURE_TEMPLATES).format(reason="美股行情暂时拉不到")

# OpenAI 非上市静态记录（快查链路；provenance 链路见 NON_PUBLIC_EQUITIES）。
# 主代理裁定（2026-09-13）：两条链路共用同一权威口径——官方融资公告
# 2026-03-31 投后 8520 亿美元；不得再出现第二套估值数字。
_OPENAI_RECORD = NonPublicCompany(
    name="OpenAI",
    aliases=("openai",),
    symbol="",
    reason="OpenAI 是非上市公司，无公开交易所股票代码，不存在公开的开盘/收盘/最高/最低行情",
    valuation_text="官方融资公告投后估值 8520 亿美元（2026-03-31，静态记录，非实时行情）",
    valuation_source="OpenAI 官方融资公告（2026-03-31）",
    valuation_date="2026-03",
)

# ticker 词边界：\b 在 CJK 相邻时失效（中文也算 \w），
# 改用「两侧非 ASCII 字母数字」负向断言，语义仍是词边界且对中文友好。
_TICKER_TOKEN_RES: dict[str, re.Pattern[str]] = {
    ref.ticker: re.compile(
        rf"(?<![A-Za-z0-9]){re.escape(ref.ticker)}(?![A-Za-z0-9])", re.IGNORECASE
    )
    for ref in _LISTED_COMPANIES
}


def reset_stock_cache() -> None:
    """清空快照进程内缓存（测试与运维手动刷新用）。"""
    global _QUOTE_CACHE
    _QUOTE_CACHE = None


def reset_stock_history_cache() -> None:
    """清空日 K 进程内缓存（测试用）。"""
    _HISTORY_CACHE.clear()


def is_openai_query(text: str) -> bool:
    """判断文本是否在问 OpenAI（小写包含 "openai"，大小写不敏感）。"""
    return "openai" in (text or "").lower()


def _alias_hit(alias: str, lowered: str) -> bool:
    """别名命中：ASCII 别名走词边界正则（防 metadata 误中 meta），
    中文别名走子串。"""
    if alias.isascii():
        pattern = _TICKER_TOKEN_RES.get(alias.upper())
        if pattern is not None:
            return bool(pattern.search(lowered))
        return bool(
            re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", lowered)
        )
    return alias in lowered


def resolve_stock_symbols(text: str) -> list[str]:
    """从文本解析命中的股票 symbol 列表（按宇宙表顺序，大小写不敏感）。

    匹配规则：ticker 词边界（两侧非 ASCII 字母数字）或中文名/别名子串；
    无命中返回空列表，绝不抛异常。
    """
    if not text:
        return []
    lowered = text.lower()
    hits: list[str] = []
    for ref in _LISTED_COMPANIES:
        token = _TICKER_TOKEN_RES[ref.ticker]
        if token.search(text) or token.search(lowered):
            hits.append(ref.ticker)
            continue
        if ref.display in text or any(_alias_hit(a, lowered) for a in ref.aliases):
            hits.append(ref.ticker)
    return hits


def _fetch_payload(secids: str, timeout_seconds: float) -> Any:
    """批量快照单点网络出口：测试 monkeypatch 本函数即可拦截全部外呼。"""
    return http_get_json(
        _QUOTES_URL.format(secids=secids),
        timeout=max(1.0, float(timeout_seconds)),
        max_bytes=_MAX_PAYLOAD_BYTES,
    )


def _parse_quotes(payload: Any, timestamp: str) -> list[StockQuote]:
    """按宇宙表顺序解析批量响应；缺行/f2 或 f3 非数的股票跳过，
    其余字段缺失容忍为 None（fltt=2 下停牌常为 "-"）。"""
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    diff = data.get("diff") if isinstance(data, dict) else None
    if not isinstance(diff, list):
        return []
    by_symbol: dict[str, dict[str, Any]] = {}
    for row in diff:
        if isinstance(row, dict):
            symbol = str(row.get("f12") or "").strip().upper()
            if symbol:
                by_symbol[symbol] = row
    quotes: list[StockQuote] = []
    for _secid, symbol, display, market, currency in _STOCK_UNIVERSE:
        row = by_symbol.get(symbol)
        if row is None:
            continue
        close = _as_float(row.get("f2"))
        change_percent = _as_float(row.get("f3"))
        if close is None or change_percent is None:
            continue
        quotes.append(
            StockQuote(
                symbol=symbol,
                display_name=display,
                market=market,
                currency=currency,
                timestamp=timestamp,
                source=_SOURCE_QUOTE,
                delayed=True,  # 美股免费行情可能有延迟，诚实标注
                open=_as_float(row.get("f17")),
                high=_as_float(row.get("f15")),
                low=_as_float(row.get("f16")),
                close=close,
                previous_close=_as_float(row.get("f18")),
                change=_as_float(row.get("f4")),
                change_percent=change_percent,
                volume=_as_float(row.get("f5")),
                market_cap=_as_float(row.get("f20")),
                history=(),
            )
        )
    return quotes


def _fetch_all_quotes(
    timeout_seconds: float, cache_seconds: float
) -> list[StockQuote]:
    """拉全量 9 只快照；成功才进 TTL 缓存，失败返回 [] 且不缓存。"""
    global _QUOTE_CACHE
    now = time.monotonic()
    cached = _QUOTE_CACHE
    if cached is not None and now - cached[0] <= max(0.0, float(cache_seconds)):
        return list(cached[1])
    secids = ",".join(secid for secid, *_rest in _STOCK_UNIVERSE)
    # G2：东财限流=HTTP 200 空响应（空 JSON/缺行）→ 退避后至多重试 1 次；
    # 真异常（网络错/非 200）不重试；仍空照旧不缓存。
    attempts = 2 if retry_on_empty_enabled() else 1
    quotes: list[StockQuote] = []
    for attempt in range(attempts):
        try:
            payload = _fetch_payload(secids, max(1.0, float(timeout_seconds)))
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            quotes = _parse_quotes(payload, timestamp)
        except Exception:  # noqa: BLE001 - 行情失败静默降级，不阻塞会话链路。
            quotes = []
            break  # 真异常不重试。
        if quotes or attempt + 1 >= attempts:
            break
        empty_backoff_sleep()
    if quotes:
        _QUOTE_CACHE = (now, tuple(quotes))
    return quotes


def fetch_stock_quotes(
    symbols: Sequence[str] | None = None,
    timeout_seconds: float = 6.0,
    cache_seconds: float = _QUOTE_CACHE_TTL_DEFAULT_SECONDS,
) -> list[StockQuote]:
    """批量拉取科技巨头快照；失败返回 []，绝不抛异常。

    ``symbols=None`` 拉全部 9 只；给列表则按宇宙表顺序过滤子集
    （单次批量外呼 + 进程内 TTL 缓存，默认 60s；失败不缓存，下次立即重试）。
    """
    wanted: set[str] | None = None
    if symbols is not None:
        wanted = {str(s).strip().upper() for s in symbols if str(s).strip()}
        if not wanted:
            return []
    all_quotes = _fetch_all_quotes(timeout_seconds, cache_seconds)
    if wanted is None:
        return all_quotes
    return [q for q in all_quotes if q.symbol in wanted]


def _parse_history_points(payload: Any) -> tuple[PricePoint, ...]:
    """解析日 K；列序实测为 日期,开,收,高,低,量（「开收高低量」），
    坏行逐行跳过，最多保留最近 60 根。"""
    data = payload.get("data") if isinstance(payload, dict) else None
    rows = data.get("klines") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return ()
    points: list[PricePoint] = []
    for row in rows:
        parts = str(row).split(",")
        if len(parts) < 5:
            continue
        date_text = parts[0].strip()
        open_ = _as_float(parts[1])
        close = _as_float(parts[2])
        high = _as_float(parts[3])
        low = _as_float(parts[4])
        if not date_text or open_ is None or close is None or high is None or low is None:
            continue
        points.append(
            PricePoint(
                date=date_text,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=_as_float(parts[5]) if len(parts) >= 6 else None,
            )
        )
    return tuple(points[-_MAX_HISTORY_POINTS:])


def fetch_stock_history(
    symbol: str,
    days: int = 30,
    timeout_seconds: float = 6.0,
    cache_seconds: float = _HISTORY_CACHE_TTL_SECONDS,
) -> tuple[PricePoint, ...]:
    """单只股票近 N 根日 K（旧→新）；失败/未知 symbol 返回 ()，绝不抛。

    复用 K 线单点网络出口（lmt 固定 60），days 截断在客户端完成；
    进程内 TTL 缓存默认 10 分钟，失败/空结果不缓存（立即重试）。
    """
    normalized = (symbol or "").strip().upper()
    if normalized not in _COMPANY_BY_TICKER:
        return ()
    now = time.monotonic()
    cached = _HISTORY_CACHE.get(normalized)
    if cached is not None and now - cached[0] <= max(1.0, float(cache_seconds)):
        points = cached[1]
    else:
        points = ()
        # G2：空 klines（空 JSON/缺行）退避后至多重试 1 次；真异常不重试；
        # 仍空不缓存（空结果不缓存纪律不变）。
        attempts = 2 if retry_on_empty_enabled() else 1
        for attempt in range(attempts):
            try:
                payload = _network_retry(lambda: _fetch_kline_payload(
                    normalized, _MAX_HISTORY_POINTS, max(1.0, float(timeout_seconds))
                ))
                points = _parse_history_points(payload)
            except Exception:  # noqa: BLE001 - K 线失败静默缺席。
                return ()
            if points or attempt + 1 >= attempts:
                break
            empty_backoff_sleep()
        if points:
            # 空结果不缓存（2026-09-13 实测 kline 接口对缺 end 参数返回空，
            # 失败/空缓存会把缺口钉死 10 分钟；仓库纪律=失败不缓存）。
            _HISTORY_CACHE[normalized] = (now, points)
    if days and int(days) > 0:
        points = points[-int(days):]
    return points


def _format_market_cap(cap_usd: float) -> str:
    """市值人性化：≥1 万亿美元显示「X.XX万亿美元」，否则「X 亿美元」。"""
    if cap_usd >= 1e12:
        return f"{cap_usd / 1e12:.2f}万亿美元"
    return f"{cap_usd / 1e8:.0f}亿美元"


def format_stock_line(quote: StockQuote) -> str:
    """单行行情：`🟢 英伟达 218.29 -0.03%（-0.07）· 市值 5.26万亿美元`。

    🔴涨🟢跌⚪平；百分比带符号；涨跌额括注；市值缺失则整段省略。
    """
    close = quote.close
    pct = quote.change_percent
    if close is None or pct is None:
        return f"{_MARK_FLAT} {quote.display_name} -"
    if pct > 0:
        mark = _MARK_UP
    elif pct < 0:
        mark = _MARK_DOWN
    else:
        mark = _MARK_FLAT
    signed_pct = f"+{pct:.2f}%" if pct > 0 else f"{pct:.2f}%"
    line = f"{mark} {quote.display_name} {close:.2f} {signed_pct}"
    if quote.change is not None:
        change_text = (
            f"+{quote.change:.2f}" if quote.change > 0 else f"{quote.change:.2f}"
        )
        line = f"{line}（{change_text}）"
    if quote.market_cap is not None:
        line = f"{line}· 市值 {_format_market_cap(quote.market_cap)}"
    return line


def format_stocks_brief(quotes: Sequence[StockQuote]) -> str:
    """科技巨头速览纯文本；空结果给降级文案。"""
    if not quotes:
        return _empty_stocks_text()
    lines = ["美股科技巨头速览"]
    lines.extend(format_stock_line(quote) for quote in quotes)
    return "\n".join(lines)
