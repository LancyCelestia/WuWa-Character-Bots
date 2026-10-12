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
    "LEG_PROBES",
    "LEG_PROBE_EMPTY_MARKERS",
    "LEG_PROBE_HEADERS",
    "MIN_INDEPENDENT_SOURCES",
    "OFFICIAL_SOURCES",
    "Leg",
    "SourceSpec",
    "check_value",
    "describe_blockers",
    "probe_empty_markers",
    "probe_headers_for",
    "probe_url_for",
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
            _e("中国外汇交易中心", "chinamoney.com.cn/ags/ms/cm-u-bk-ccpr/CcprHisNew", True,
               note="2026-10-13 smoke 200/725B（真中间价历史）"),
            _e("东方财富", "push2.eastmoney.com/api/qt/ulist.np/get（secids=133.USDCNH,119.USDCNY）", True,
               note="2026-10-13 smoke 200/169B **有数**（该端点会瞬时断连，重试即通——smoke 已带重试）"),
            _e("新浪财经", "hq.sinajs.cn/list=fx_susdcny（须 Referer）", True,
               note="2026-10-13 smoke 200/222B（人民币中间价行情串）——独立于 CFETS/东财的第三腿"),
            _e("腾讯", "qt.gtimg.cn（外汇口：**未找到可用符号**）", False,
               note="2026-10-13 实测：`q=USDCNY` 返 `v_pv_none_match=\"1\"`＝**空响应**（HTTP 200 但零数据）"
                    "⇒ 如实降为未验。此例暴露 smoke 曾把「200 + 非空字节」误判为绿，已加空响应哨兵"),
        ),
        note="三腿齐（CFETS 官方 / 东财 / 新浪），CFETS 为第一腿；腾讯外汇口暂无机器可调符号",
    ),
    SourceSpec(
        value="互联互通成交额",
        tolerance="只比成交额口径；⚠ 净买入 2024-08 起停披露",
        legs=(
            _e("东方财富", "datacenter-web…/RPT_MUTUAL_DEAL_HISTORY", True),
            _e("香港交易所", "hkex.com.hk/Mutual-Market/Stock-Connect（sc_lang=zh-HK）", False,
               note="2026-10-13 smoke **200/400KB**（真「滬港通及深港通」页）；HTML 呈现页、无稳定机读口 ⇒ 须页面解析"),
            _e("上海证券交易所", "query.sse.com.cn/commonQuery.do?sqlId=COMMON_SSE_SJ_HGT_ZJLX", False,
               note="2026-10-13 实测：试 5 个 sqlId（HGT_ZJLX/JYMX、GGT_ZJLX、HGTZJ、HKEX_ZJLX）**全部** "
                    "`pageHelp.data=null`（HTTP 200 空壳）⇒ 该腿对本值维**无数据**，降为未验。"
                    "教训：空壳 200 曾被误判为绿，已加空响应哨兵"),
        ),
        note="净买入结构性停披 ⇒ 该维结构性受限；成交额口径**仅 2 条可用腿**"
             "（东财机读 / 港交所页面须解析）⇒ 未达 3 源硬门，**不得出数，须显式标注缺口**",
        structurally_capped=True,
    ),
    SourceSpec(
        value="宏观 CPI / PMI",
        tolerance="同比口径；季度/月度对齐发布期",
        legs=(
            _e("东方财富", "datacenter-web…/RPT_ECONOMY_CPI / RPT_ECONOMY_PMI", True),
            _e("国家统计局", "stats.gov.cn/sj/zxfb/（官网发布页；easyquery API 恒 403）", True,
               note="2026-10-13 smoke：**官网发布页 200/73KB 可达**；API 口带 Referer 仍 403 ⇒ 走页面解析。"
                    "第三腿成立（独立于东财/世界银行）"),
            _e("世界银行", "api.worldbank.org/v2/…", True, note="年度口径，非月频"),
        ),
        note="三腿齐：东财（月频）/ 国家统计局（官方发布页）/ 世界银行（年度口径）——口径差异须在卡面标注",
    ),
    SourceSpec(
        value="美债收益率曲线",
        tolerance="同一交易日收盘口径",
        legs=(
            _e("美国财政部", "home.treasury.gov/…/interest-rates（XML 或 CSV）", True,
               note="2026-10-13 smoke：CSV 200/15905B（逐期限、日频，含 10 Yr）"),
            _e("美联储", "federalreserve.gov/releases/h15/", True,
               note="2026-10-13 smoke 200/60KB"),
            _e("国际清算银行", "stats.bis.org/api/v2/…/BIS/WS_LONG_CPI（US 长端利率）", True,
               note="2026-10-13 smoke 200/51KB CSV——独立第三腿；⚠ **月频**口径，与日频腿比对须标注频率差"),
            _e("FRED", "fred.stlouisfed.org/graph/fredgraph.csv", False,
               note="2026-10-13 实测：直连与代理**均 3×20s 超时**（本机不可达）；且 FRED 属圣路易斯联储，"
                    "与「美联储」同机构族 ⇒ 即便可达也不宜充作独立源"),
        ),
        note="三腿齐（美国财政部日频 / 美联储 H15 / BIS 月频）；FRED 本机不可达且同族，不计独立源",
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


# ==================== 可实调探针（smoke 用） ====================
# 登记册只答「谁提供这个值」；本表答「怎么实调它」——smoke 脚本按此发真请求。
# 键＝(值维, 机构)，与 OFFICIAL_SOURCES 的腿一一对应；值＝可直接 GET 的完整 URL。
# 空串/缺键 ⇒ 该腿暂无机器可调入口（如仅人工页面），smoke 会如实记为「无探针」。
# ⚠ 探针只用于**可达性 smoke**（HTTP 码/延迟/字节数），不解析业务字段；
#   业务解析在各能力自己的取数层，两者不混。
LEG_PROBES: dict[tuple[str, str], str] = {
    # —— 全球股指 ——
    ("全球股指点位/涨跌幅", "东方财富"): (
        "https://push2.eastmoney.com/api/qt/ulist.np/get"
        "?secids=1.000001,100.DJIA&fields=f12,f14,f2,f3&fltt=2&invt=2"
    ),
    ("全球股指点位/涨跌幅", "腾讯"): "https://qt.gtimg.cn/q=sh000001,usDJI",
    ("全球股指点位/涨跌幅", "新浪"): "https://hq.sinajs.cn/list=s_sh000001",
    ("全球股指点位/涨跌幅", "MOEX ISS"): (
        "https://iss.moex.com/iss/engines/stock/markets/index/boards/SNDX"
        "/securities/IMOEX.json?iss.meta=off"
    ),
    # —— 指数全成分 ——
    ("指数全成分股涨跌幅分布", "东方财富"): (
        "https://datacenter-web.eastmoney.com/api/data/v1/get"
        "?reportName=RPT_INDEX_COMPONENT&columns=SECURITY_CODE&quoteColumns=f2,f3"
        "&filter=(INDEX_CODE%3D%22000300%22)&pageNumber=1&pageSize=500"
        "&source=WEB&client=WEB"
    ),
    ("指数全成分股涨跌幅分布", "中证指数"): (
        "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file"
        "/autofile/cons/000300cons.xls"
    ),
    ("指数全成分股涨跌幅分布", "上海证券交易所"): (
        "https://query.sse.com.cn/commonQuery.do"
        "?sqlId=COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L&isPagination=true"
        "&pageHelp.pageSize=5&pageHelp.pageNo=1"
    ),
    ("指数全成分股涨跌幅分布", "新浪财经"): (
        "https://vip.stock.finance.sina.com.cn/corp/go.php/vII_NewestComponent"
        "/indexid/000300.phtml"
    ),
    # —— 汇率中间价 ——
    ("汇率中间价", "中国外汇交易中心"): (
        "https://www.chinamoney.com.cn/ags/ms/cm-u-bk-ccpr/CcprHisNew"
        "?startDate=2026-10-01&endDate=2026-10-13&currency=USD/CNY&pageSize=5"
    ),
    ("汇率中间价", "东方财富"): (
        "https://push2.eastmoney.com/api/qt/ulist.np/get"
        "?secids=133.USDCNH,119.USDCNY&fields=f12,f14,f2,f3&fltt=2&invt=2"
    ),
    ("汇率中间价", "新浪财经"): "https://hq.sinajs.cn/list=fx_susdcny",
    # 腾讯外汇口无可用符号（实测返 v_pv_none_match）⇒ 不给探针，smoke 如实记「无探针」。
    # —— 互联互通 ——
    ("互联互通成交额", "东方财富"): (
        "https://datacenter-web.eastmoney.com/api/data/v1/get"
        "?reportName=RPT_MUTUAL_DEAL_HISTORY&columns=ALL"
        "&pageNumber=1&pageSize=2&source=WEB&client=WEB"
    ),
    ("互联互通成交额", "香港交易所"): (
        "https://www.hkex.com.hk/Mutual-Market/Stock-Connect?sc_lang=zh-HK"
    ),
    ("互联互通成交额", "上海证券交易所"): (
        "https://query.sse.com.cn/commonQuery.do?sqlId=COMMON_SSE_SJ_HGT_ZJLX"
        "&isPagination=true&pageHelp.pageSize=5&pageHelp.pageNo=1"
    ),
    # —— 宏观 ——
    ("宏观 CPI / PMI", "东方财富"): (
        "https://datacenter-web.eastmoney.com/api/data/v1/get"
        "?reportName=RPT_ECONOMY_CPI&columns=ALL&pageNumber=1&pageSize=2"
        "&source=WEB&client=WEB"
    ),
    ("宏观 CPI / PMI", "国家统计局"): "https://www.stats.gov.cn/sj/zxfb/",
    ("宏观 CPI / PMI", "世界银行"): (
        "https://api.worldbank.org/v2/country/CN/indicator/NY.GDP.MKTP.CD"
        "?format=json&per_page=2"
    ),
    # —— 美债 ——
    ("美债收益率曲线", "美国财政部"): (
        "https://home.treasury.gov/resource-center/data-chart-center/interest-rates"
        "/daily-treasury-rates.csv/2026/all?type=daily_treasury_yield_curve"
        "&field_tdr_date_value=2026&page&_format=csv"
    ),
    ("美债收益率曲线", "国际清算银行"): (
        "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_LONG_CPI/1.0/M.US.771?format=csv"
    ),
    ("美债收益率曲线", "FRED"): "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10",
    ("美债收益率曲线", "美联储"): "https://www.federalreserve.gov/releases/h15/",
    # —— 天气 ——
    ("天气实况/预报/预警", "中央气象台"): "http://www.nmc.cn/rest/province/all",
    ("天气实况/预报/预警", "中国天气网"): "http://www.weather.com.cn/data/sk/101010100.html",
    ("天气实况/预报/预警", "香港天文台"): (
        "https://data.weather.gov.hk/weatherAPI/opendata/weather.php"
        "?dataType=rhrread&lang=en"
    ),
    ("天气实况/预报/预警", "NWS"): "https://api.weather.gov/alerts/active?area=MD",
    ("天气实况/预报/预警", "DWD"): (
        "https://opendata.dwd.de/weather/local_forecasts/mos/MOSMIX_L"
        "/single_stations/54511/kml/MOSMIX_L_LATEST_54511.kmz"
    ),
}

# 需要额外请求头才能实调的腿（如新浪必须带 Referer，否则 403）。
LEG_PROBE_HEADERS: dict[tuple[str, str], dict[str, str]] = {
    ("全球股指点位/涨跌幅", "新浪"): {"Referer": "https://finance.sina.com.cn"},
    ("指数全成分股涨跌幅分布", "上海证券交易所"): {"Referer": "https://www.sse.com.cn/"},
    ("指数全成分股涨跌幅分布", "中证指数"): {"Referer": "https://www.csindex.com.cn/"},
    ("汇率中间价", "新浪财经"): {"Referer": "https://finance.sina.com.cn"},
    ("指数全成分股涨跌幅分布", "新浪财经"): {"Referer": "https://finance.sina.com.cn"},
    ("互联互通成交额", "上海证券交易所"): {"Referer": "https://www.sse.com.cn/"},
    ("宏观 CPI / PMI", "国家统计局"): {"Referer": "https://www.stats.gov.cn/"},
}


def probe_url_for(value: str, org: str) -> str:
    """取该腿的实调探针 URL；无探针返回空串（smoke 如实记「无探针」）。"""
    return LEG_PROBES.get((value, org), "")


# ==================== 空响应哨兵（smoke 判绿的追加条件） ====================
# 为什么要它（2026-10-13 实测教训）：smoke 原本只判「HTTP 200 且字节数 > 0」，
# 但**端点可以 200 却零数据**——腾讯外汇口 `q=USDCNY` 返 `v_pv_none_match="1";`（21B）
# 就被误判成绿。下列标记一旦命中，即便 200 也判「空响应」＝不算腿。
LEG_PROBE_EMPTY_MARKERS: tuple[str, ...] = (
    "v_pv_none_match",          # 腾讯：无此代码/无数据
    '"data":null',              # 东财/上交所：secid 或 sqlId 无效（上交所空壳的可靠标记）
    '"result":null',            # 东财：报表/查询无结果
    "报表配置不存在",              # 东财：reportName 写错
)


def probe_empty_markers(value: str, org: str) -> tuple[str, ...]:
    """取该腿的空响应标记（缺省用全局表）。"""
    return LEG_PROBE_EMPTY_MARKERS


def probe_headers_for(value: str, org: str) -> dict[str, str]:
    """取该腿实调所需的额外请求头（缺省空 dict）。"""
    return dict(LEG_PROBE_HEADERS.get((value, org), {}))


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
