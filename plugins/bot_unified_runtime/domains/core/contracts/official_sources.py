"""官方源登记册（三源硬门的数据载体，2026-10-13 用户立规）。

背景（AGENTS 规则 12「三源硬门」）：**任何对外 web 数值须 ≥3 个官方/权威渠道
佐证**；凑不满 3 源者不得出卡/出数。本模块是这条死规的**唯一登记处**——
把「每个值维由哪几条腿提供」写成数据，让门禁可机械执法、让卡面可标注口径。

设计纪律：
- **只登记，不取数**：本模块零网络、零副作用，纯常量与纯函数；
- **同机构多入口只算一源**：``source_org`` 是**机构**标识，不是 URL 域名——
  东财的三个接口 = 1 源；同机构多域名不得靠并列充数；
- **凑不满 3 源 ⇒ ``ready=False``**：调用方据此**拒绝出数**（不是「标注一下
  照出」），这是硬门与软提示的分界；
- 腿的「实测状态」由调用方传入或离线核实，本模块不联网自证。
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "OFFICIAL_SOURCES",
    "Leg",
    "SourceSpec",
    "check_value",
    "describe_blockers",
    "ready_values",
    "shortfall_values",
]

# 三源硬门的最小独立源数（用户 2026-10-13 立规）。
MIN_INDEPENDENT_SOURCES = 3


@dataclass(frozen=True)
class Leg:
    """一条取值腿：某机构的一个入口。

    ``org`` 是**机构标识**（判独立性的唯一依据）；同 org 的多个入口在
    计数里只算一源——这是「不拿同机构并列充数」的机械保证。
    """

    org: str
    endpoint: str
    verified: bool = False
    note: str = ""


@dataclass(frozen=True)
class SourceSpec:
    """一个值维的取值方案与其三源达成度。"""

    value: str
    legs: tuple[Leg, ...] = ()
    tolerance: str = ""
    note: str = ""
    # 结构性缺口：该值天生凑不满三源（如净买入已停披），显式登记而非假装能补。
    structurally_capped: bool = False

    @property
    def independent_orgs(self) -> tuple[str, ...]:
        """按机构去重后的源清单（保序）。"""
        seen: dict[str, None] = {}
        for leg in self.legs:
            seen.setdefault(leg.org, None)
        return tuple(seen)

    @property
    def source_count(self) -> int:
        return len(self.independent_orgs)

    @property
    def verified_orgs(self) -> tuple[str, ...]:
        """**已实测**的独立机构（只有实测过的腿才算数）。"""
        seen: dict[str, None] = {}
        for leg in self.legs:
            if leg.verified:
                seen.setdefault(leg.org, None)
        return tuple(seen)

    @property
    def ready(self) -> bool:
        """三源硬门判定：**实测通过**的独立机构 ≥ 3 才准出数。"""
        return len(self.verified_orgs) >= MIN_INDEPENDENT_SOURCES


def _e(org: str, endpoint: str, verified: bool, note: str = "") -> Leg:
    return Leg(org=org, endpoint=endpoint, verified=verified, note=note)


# ==================== 登记册真身 ====================
# 说明：verified 以本仓 2026-10-12/13 两轮实测记录为准（源矩阵研究件＋复核席）。
# 未实测的一律 False——**不实测不算数**，宁缺不编。
OFFICIAL_SOURCES: tuple[SourceSpec, ...] = (
    SourceSpec(
        value="全球股指点位/涨跌幅",
        tolerance="价格相对差 ≤0.5% 且 涨跌幅差 ≤0.2pp（快照有时差）",
        legs=(
            _e("东方财富", "push2.eastmoney.com/api/qt/ulist.np/get", True),
            _e("腾讯", "qt.gtimg.cn/q=", True),
            _e("新浪", "hq.sinajs.cn/list=（须 Referer）", True),
            _e("MOEX ISS", "iss.moex.com/iss/…/securities/IMOEX.json", True,
               note="仅俄罗斯指数腿"),
        ),
        note="主链已在卡面亮「三源（东财/腾讯/新浪）交叉核验」，缺腿自动降级为「双源」",
    ),
    SourceSpec(
        value="指数全成分股涨跌幅分布",
        tolerance="横截面同日口径；成分表变动按 10 分钟缓存",
        legs=(
            _e("东方财富", "datacenter-web…/RPT_INDEX_COMPONENT＋quoteColumns=f2,f3", True,
               note="唯一可直接出数的腿（分页 500/页）"),
            _e("中证指数", "oss-ch.csindex.com.cn/…/autofile/cons/{code}cons.xls", False,
               note="2026-10-13 实测 200／67KB，**真成分表**（含「成份券代码」表头＋中兴通讯/TCL科技等真名）；"
                    "但为 OLE2 二进制 XLS，venv 无 xlrd、openpyxl 按后缀拒收 ⇒ **可下载不可轻解析**，"
                    "引依赖或自写 BIFF 解析器代价过大（ponytail）；补此腿须先裁决是否引 xlrd"),
            _e("上海证券交易所", "query.sse.com.cn/commonQuery.do?sqlId=…GPLB_GP_…", False,
               note="2026-10-13 实测 200／58KB JSON（A_STOCK_CODE 可抽），但 total=2520 ⇒ **全市场股票列表，非成分表**，"
                    "口径不符，不构成该值独立腿"),
            _e("新浪财经", "vip.stock.finance.sina.com.cn/corp/go.php/vII_NewestComponent/indexid/000300.phtml", False,
               note="2026-10-13 实测 200／32KB（GBK），但**分页仅 40 条**，远不足 300 成分 ⇒ 不构成完整腿"),
        ),
        note="⚠ 现仅东财一腿可出数 ⇒ 按三源硬门**该值不得出卡**；三条候选腿的实测结论已写明，勿重复试同批端点",
    ),
    SourceSpec(
        value="汇率中间价",
        tolerance="中间价口径：同一发布时点比对，差 >0.01 即标注",
        legs=(
            _e("中国外汇交易中心", "chinamoney.com.cn/ags/ms/cm-u-bk-ccpr/CcprHisNew", True),
            _e("东方财富", "push2…（既有 fx 链路）", True),
            _e("腾讯", "qt.gtimg.cn（外汇口）", True),
        ),
        note="拟由 CFETS 官方口升为第一腿",
    ),
    SourceSpec(
        value="互联互通成交额",
        tolerance="只比成交额口径；⚠ 净买入 2024-08 起停披露",
        legs=(
            _e("东方财富", "datacenter-web…/RPT_MUTUAL_DEAL_HISTORY", True),
            _e("香港交易所", "hkex.com.hk/Mutual-Market/Stock-Connect（sc_lang=zh-HK）", False,
               note="2026-10-13 实测：**页面 200／400KB 可达**（真「滬港通及深港通」页），"
                    "但为 HTML 呈现页、无稳定机读口（JSON 口 getequityquote 403）⇒ "
                    "须做页面解析或改走官方月报；未接解析 ⇒ 尚不计为可用腿"),
        ),
        note="净买入结构性停披 ⇒ 该维结构性受限；成交额口径仍差 1 条腿",
        structurally_capped=True,
    ),
    SourceSpec(
        value="宏观 CPI / PMI",
        tolerance="同比口径；季度/月度对齐发布期",
        legs=(
            _e("东方财富", "datacenter-web…/RPT_ECONOMY_CPI / RPT_ECONOMY_PMI", True),
            _e("国家统计局", "data.stats.gov.cn/easyquery.htm（须 Referer/会话）", False,
               note="2026-10-13 实测：主页 200，但 easyquery 数据口带 Referer 仍 **403** "
                    "⇒ 官方第二腿需另寻入口（如 stat 年报/公报页）"),
            _e("世界银行", "api.worldbank.org/v2/…", True, note="年度口径，非月频"),
        ),
    ),
    SourceSpec(
        value="美债收益率曲线",
        tolerance="同一交易日收盘口径",
        legs=(
            _e("美国财政部", "home.treasury.gov/…/interest-rates/pages/xml", True),
            _e("FRED", "fred.stlouisfed.org/graph/fredgraph.csv", True),
            _e("美联储", "federalreserve.gov/releases/h15/", True),
        ),
        note="国际腿直连可达（2026-10-12 复核纠正过「须经代理」的旧结论）",
    ),
    SourceSpec(
        value="天气实况/预报/预警",
        tolerance="同一站点同一时次；时间戳差 >1h 即标注",
        legs=(
            _e("中央气象台", "nmc.cn/rest/province / typhoon.nmc.cn", True),
            _e("中国天气网", "d1.weather.com.cn/sk_2d（须 Referer）", True),
            _e("香港天文台", "data.weather.gov.hk/weatherAPI/opendata/weather.php", True),
            _e("NWS", "api.weather.gov/…", True),
            _e("DWD", "opendata.dwd.de（MOSMIX 含中国站）", True),
        ),
        note="数值预报另有 GFS/IFS/ICON/GEM 四家（见源矩阵研究件）",
    ),
)


def check_value(value: str) -> SourceSpec | None:
    """按值名取方案；未知值返回 None（调用方须显式处理，不许默认放行）。"""
    for spec in OFFICIAL_SOURCES:
        if spec.value == value:
            return spec
    return None


def ready_values() -> tuple[str, ...]:
    """已达三源硬门（≥3 实测独立机构）的值维。"""
    return tuple(spec.value for spec in OFFICIAL_SOURCES if spec.ready)


def shortfall_values() -> tuple[str, ...]:
    """未达硬门的值维——**这些一律不得出数**。"""
    return tuple(spec.value for spec in OFFICIAL_SOURCES if not spec.ready)


def describe_blockers(value: str) -> str:
    """缺口说明（给卡面/面板/告警用）：说清「差几条腿、差在哪」。

    未知值不返回空串而是明说未登记——静默空串会让调用方以为「已达标」。
    """
    spec = check_value(value)
    if spec is None:
        return f"「{value}」未在官方源登记册登记，按三源硬门不得出数"
    if spec.ready:
        return (
            f"「{value}」已达标：实测独立源 {spec.source_count} 家"
            f"（{'/'.join(spec.verified_orgs)}）"
        )
    need = MIN_INDEPENDENT_SOURCES - len(spec.verified_orgs)
    unverified = [
        f"{leg.org}（未实测）" for leg in spec.legs if not leg.verified
    ]
    tail = f"；待补：{'、'.join(unverified)}" if unverified else ""
    capped = "；⚠ 该维结构性受限（见 note）" if spec.structurally_capped else ""
    return (
        f"「{value}」未达三源硬门：实测独立源 "
        f"{len(spec.verified_orgs)}/{MIN_INDEPENDENT_SOURCES}，还差 {need} 条{tail}{capped}"
    )
