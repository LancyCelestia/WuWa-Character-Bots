"""金融数据契约（Task 4 全局审计 + 快查批量链路）：股票 / 汇率 / 图表语义。

设计铁律（计划原文约束）：
- 每一条可展示的金融数据都带 ``source`` / ``as_of`` / ``status`` / ``delayed``
  四件套：外部源失败可解释（缺数据显示明确状态），绝不伪造 0 或旧值。
- **非上市公司红线**：``NonPublicEquityNote`` 上结构性不存在任何价格/OHLC
  字段——OpenAI 等非上市公司只允许「有来源的公开估值 + 时点 + 说明」。
- **图表语义**：``BoxPlotStats`` 只描述「多日分布五数概括」；单日 OHLC 不是
  分布，构造入口（stock_data.build_boxplot_from_ohlcv）按最少样本数拒绝，
  不足即 insufficient_data，绝不把单日 K 线画成箱形图。

术语约定：**本模块所有「K」均指 K 线（烛台 OHLCV）数据，不涉及 KDJ 等
技术指标**（KDJ 快照是独立契约 ``KDJSnapshot``）。

两条并行链路（契约不同名，勿混用）：
- **provenance 链路**（pydantic 四件套审计）：``EquityQuote``（原名单只
  StockQuote，2026-09-13 因快查链路同名冲突改名）/ ``OHLCVBar`` /
  ``OHLCVSeries`` / ``MarketCap`` / ``CurrencyQuote`` / ``FxRateSnapshot``；
- **快查批量链路**（frozen dataclass，零依赖）：``StockQuote``（9 家科技
  巨头批量快照）/ ``PricePoint``（单根日 K）/ ``NonPublicCompany``（非上市
  公司静态说明）/ ``FxRate``（货币对快照）。

实测已核验（2026-09-12 curl，主代理实机）：东财个股 secid 105.NASDAQ /
106.NYSE；市值字段 **f20**（NVDA 实测 5260789000000 ≈ 5.26 万亿美元，
同接口族的 f116 惯用法实测无值，已废弃）；K 线 ``fields2=f51..f56`` 列序为
「日期,开,收,高,低,量」（真实行 "2026-09-09,225.025,223.420,225.930,223.210,
82955478"）；外汇 secid 133/119/120 板块可用、FX 日 K 全空。

本模块只声明数据形状；网络访问在 ``sources/stock_data`` / ``sources/fx_data``。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

from pydantic import Field, field_validator, model_validator

from .runtime import StrictBaseModel


class FinanceDataStatus(str, Enum):
    """金融数据状态：展示层据此给「明确状态」而非编造数字。"""

    OK = "ok"
    DEGRADED = "degraded"  # 部分数据可得（坏行跳过/缺个别字段/缺个别币种）
    UNAVAILABLE = "unavailable"  # 上游失败/字段缺失，无可信数字
    NON_PUBLIC = "non_public"  # 非上市公司：无股价，仅公开估值说明
    UNKNOWN = "unknown"  # 来源/时点无法核实（未实测的新上游默认此态）


def status_or_unknown(value: FinanceDataStatus | str | None) -> FinanceDataStatus:
    """容错解析状态字串；无法识别一律落 unknown（不假装可信）。"""
    text = str(getattr(value, "value", value) or "").strip().lower()
    try:
        return FinanceDataStatus(text)
    except ValueError:
        return FinanceDataStatus.UNKNOWN


class _ProvenanceMixin(StrictBaseModel):
    """来源四件套：所有金融数据模型的公共审计字段。"""

    source: str = ""
    as_of: datetime | None = None
    status: FinanceDataStatus = FinanceDataStatus.UNKNOWN
    delayed: bool = True  # 免费行情默认延迟；非实时数据不允许标实时
    note: str = ""  # 人类可读的状态/失败说明（可解释性契约）


class EquityQuote(_ProvenanceMixin):
    """上市股票现价快照（provenance 链路）；price 缺失时为 None 且 status 说明原因。

    命名说明：原名 ``StockQuote``，2026-09-13 让位给快查批量链路的
    frozen dataclass ``StockQuote``（见文件尾部）而改名。
    """

    ticker: str
    name: str = ""
    exchange: str = ""
    currency: str = "USD"
    price: float | None = None
    change_pct: float | None = None
    change_abs: float | None = None

    @field_validator("ticker")
    @classmethod
    def _ticker_upper_nonblank(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("stock ticker must be non-blank")
        return normalized


class OHLCVBar(StrictBaseModel):
    """单日 K 线；high/low 上下界与成交量非负由校验器锁死。"""

    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None  # 上游缺量时 None，不造 0

    @field_validator("volume")
    @classmethod
    def _volume_non_negative(cls, value: float | None) -> float | None:
        if value is not None and value < 0:
            raise ValueError("volume must be non-negative")
        return value

    @model_validator(mode="after")
    def _range_consistent(self) -> OHLCVBar:
        if self.high < self.low:
            raise ValueError("high must be >= low")
        if not (self.low <= min(self.open, self.close) <= self.high):
            raise ValueError("open/close must stay within [low, high]")
        return self


class OHLCVSeries(_ProvenanceMixin):
    """多日 K 线序列（旧→新）；趋势折线的唯一合法输入。"""

    ticker: str
    name: str = ""
    currency: str = "USD"
    bars: list[OHLCVBar] = Field(default_factory=list)

    @property
    def closes(self) -> tuple[float, ...]:
        return tuple(bar.close for bar in self.bars)

    @field_validator("ticker")
    @classmethod
    def _ticker_upper_nonblank(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("stock ticker must be non-blank")
        return normalized


class MarketCap(_ProvenanceMixin):
    """总市值快照；上游字段缺失时 value=None（明确状态），绝不回 0。"""

    ticker: str
    value: float | None = None
    currency: str = "USD"

    @field_validator("value")
    @classmethod
    def _value_non_negative(cls, value: float | None) -> float | None:
        if value is not None and value < 0:
            raise ValueError("market cap must be non-negative")
        return value


class KDJSnapshot(StrictBaseModel):
    """KDJ 随机指标快照（基于多日 K 线计算，纯数学，离线可验证）。"""

    trade_date: date | None = None
    k: float
    d: float
    j: float
    period: int = 9


class CurrencyQuote(_ProvenanceMixin):
    """单个货币对的汇率；rate 必须 > 0（缺数走状态，不造 0）。"""

    base_currency: str
    quote_currency: str
    rate: float
    rate_type: str = "mid"  # mid=中间价 / reference=参考价 / last=最近成交

    @field_validator("base_currency", "quote_currency")
    @classmethod
    def _iso_code_upper(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("currency code must be a 3-letter ISO code")
        return normalized

    @field_validator("rate")
    @classmethod
    def _rate_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("fx rate must be positive (never fabricate 0)")
        return value


class FxRateSnapshot(_ProvenanceMixin):
    """一次汇率拉取的完整快照：拿到的 + 缺的都显式列出（可解释性）。"""

    base_currency: str
    quotes: list[CurrencyQuote] = Field(default_factory=list)
    missing_currencies: list[str] = Field(default_factory=list)


class BoxPlotStats(StrictBaseModel):
    """箱形图五数概括（min/Q1/median/Q3/max）——只描述多日分布。

    分位数算法：type-7 线性插值（numpy 默认 / Excel QUARTILE.INC 口径）。
    """

    label: str = ""
    n: int
    minimum: float
    q1: float
    median: float
    q3: float
    maximum: float

    @field_validator("n")
    @classmethod
    def _n_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("box plot needs at least one sample")
        return value

    @model_validator(mode="after")
    def _five_number_ordered(self) -> BoxPlotStats:
        if not (
            self.minimum <= self.q1 <= self.median <= self.q3 <= self.maximum
        ):
            raise ValueError("five-number summary must be non-decreasing")
        return self


class NonPublicEquityNote(StrictBaseModel):
    """非上市公司权益说明：只允许有来源的公开估值，结构性无价格字段。"""

    key: str
    name: str
    status: FinanceDataStatus = FinanceDataStatus.NON_PUBLIC
    statement: str = ""  # 给用户看的一句话说明（非上市，无股价可查）
    valuation_usd: float | None = None  # 最近公开披露的估值（美元）
    valuation_as_of: date | None = None  # 估值时点
    valuation_source: str = ""  # 来源声明（官方公告/公开报道），必须非空
    note: str = ""

    @field_validator("valuation_usd")
    @classmethod
    def _valuation_positive(cls, value: float | None) -> float | None:
        if value is not None and value <= 0:
            raise ValueError("valuation must be positive when present")
        return value


# ==================== 快查批量链路（frozen dataclass，零依赖） ====================


@dataclass(frozen=True)
class PricePoint:
    """单根日 K（烛台）：一天的开高收低与成交量（「K」指 K 线，非 KDJ）。"""

    date: str  # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


@dataclass(frozen=True)
class StockQuote:
    """单只股票的行情快照（快查批量链路，9 家科技巨头）。"""

    symbol: str
    display_name: str
    market: str  # 如 "NASDAQ"
    currency: str = "USD"
    timestamp: str = ""  # 抓取时间（服务器本地时间）
    source: str = "eastmoney"
    delayed: bool = True  # True=可能有延迟（美股免费行情非实时，诚实标注）
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    previous_close: float | None = None
    change: float | None = None
    change_percent: float | None = None
    volume: float | None = None
    market_cap: float | None = None  # 总市值（美元，f20 实测核验）
    history: tuple[PricePoint, ...] = ()


@dataclass(frozen=True)
class NonPublicCompany:
    """非上市公司的静态记录（非实时行情），用于「OpenAI 股价」类兜底回答。

    字段顺序说明：dataclass 要求无默认值字段在前，故 reason/valuation_source/
    valuation_date 提前；语义与计划原文一致（symbol=""=无公开代码，
    valuation_text 可空）。
    """

    name: str
    aliases: tuple[str, ...]
    reason: str
    valuation_source: str
    valuation_date: str
    symbol: str = ""  # 空=无公开交易所代码
    valuation_text: str = ""  # 可空：公开报道的估值说明


@dataclass(frozen=True)
class FxRate:
    """单个货币对的汇率快照（快查批量链路）。"""

    base_currency: str
    quote_currency: str
    rate: float
    unit_base: float = 1.0  # 中间价每 100 日元时为 100（120.JPYCNYC 口径）
    timestamp: str = ""
    source: str = "eastmoney"
    rate_type: str = "spot"  # "spot"（现货）| "parity"（中间价）| "derived"（换算）
    delayed: bool = True
    history: tuple[tuple[str, float], ...] = ()  # 东财 FX 日 K 实测全空，恒为 ()


__all__ = [
    "BoxPlotStats",
    "CurrencyQuote",
    "EquityQuote",
    "FinanceDataStatus",
    "FxRate",
    "FxRateSnapshot",
    "KDJSnapshot",
    "MarketCap",
    "NonPublicCompany",
    "NonPublicEquityNote",
    "OHLCVBar",
    "OHLCVSeries",
    "PricePoint",
    "StockQuote",
    "status_or_unknown",
]
