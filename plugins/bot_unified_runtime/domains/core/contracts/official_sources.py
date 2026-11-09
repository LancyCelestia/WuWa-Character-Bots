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

from dataclasses import dataclass

__all__ = [
    "LEG_PROBES",
    "LEG_PROBE_EMPTY_MARKERS",
    "LEG_PROBE_EMPTY_MARKERS_BY_LEG",
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
        tolerance="横截面同日口径；成分表变动按 10 分钟缓存；同批分布 n/均值/中位差 ≤0.05pp",
        legs=(
            _e("东方财富", "datacenter-web…/RPT_INDEX_COMPONENT＋quoteColumns=f2,f3", True,
               note="成分表＋每只涨跌幅一次拿齐（分页 500/页）；2026-10-13 实测 200／14.5KB"),
            _e("腾讯", "qt.gtimg.cn/q=（对东财成分代码批量取涨跌幅）", True,
               note="2026-10-13 实测 200／GBK，~0.2s；同批 50/200/500/800 只**全回无截断**；"
                    "涨跌幅＝全格式行字段 32；与东财逐只一致、同批 n/均值/中位一致"
                    "（见 market_data.crosscheck_member_distribution）"),
            _e("新浪", "hq.sinajs.cn/list=（须 Referer；对东财成分代码批量取涨跌幅）", True,
               note="2026-10-13 实测 200／GB18030，~0.2s；同批全回；涨跌幅＝(现价−昨收)/昨收；"
                    "同批分布与东财一致（中位差 ≤0.01pp）。⚠ 同机构 vip.stock 成分页分页仅 40 条"
                    "（已弃，不构成完整腿），本腿走 hq 批量口"),
            _e("中证指数", "oss-ch.csindex.com.cn/…/autofile/cons/{code}cons.xls", False,
               note="2026-10-13 实测 200／67KB，**只提供成分名单（无涨跌幅）** ⇒ 不构成「涨跌幅"
                    "分布」的独立取值腿（名单可由指数编制方佐证，但不计入本值维源数）"),
            _e("上海证券交易所", "query.sse.com.cn/commonQuery.do?sqlId=…GPLB_GP_…", False,
               note="2026-10-13 实测 200／58KB JSON（A_STOCK_CODE 可抽），但 total=2520 ⇒ **全市场股票列表，非成分表**，"
                    "口径不符，不构成该值独立腿"),
        ),
        note="三腿齐：东财（成分表＋涨跌幅一次拿齐）／腾讯／新浪（对同一批成分各自批量取涨跌幅，"
             "同量分布一致性核验）；中证只给名单、上交所是全市场列表，均不计入源数",
    ),
    SourceSpec(
        value="汇率中间价",
        tolerance=(
            "⚠ **口径分列**（2026-10-13 二轮实测后订正）：中间价＝**定盘价**，由中国人民银行"
            "受权中国外汇交易中心于每个交易日约 9:15 公布**同一个价**；央行（受权发布公告）／"
            "国家外汇管理局（统计数据列）／CFETS（发布方）三家各自官网发布的是**同一发布的三个"
            "官方渠道，不是三次独立测量**——三家同日数值必须**逐位相等**，不相等即发布异常须标注。"
            "**即期/离岸报价不是定盘**（另立值维「人民币即期汇率」），不得拿来把中间价凑源数"
        ),
        legs=(
            _e("中国外汇交易中心", "chinamoney.com.cn/ags/ms/cm-u-bk-ccpr/CcprHisNew", True,
               note="2026-10-13 实测 200/767B：USD/CNY 定盘 6.7298（**发布方**）。"
                    "⚠ 与央行/外汇局是**同一发布的三个渠道**，非三次独立测量"),
            _e("中国人民银行", "pbc.gov.cn/zhengcehuobisi/125207/125217/125925/index.html", True,
               note="2026-10-13 实测：公告列表页 200/43KB（**带 Referer**；真身＝列表里当日公告"
                    "详情页 `/zhengcehuobisi/125207/125217/125925/{id}/index.html`）；当日公告正文"
                    "200/28.6KB 含「1美元对人民币6.7298元」——与 CFETS 定盘**逐位相等**"),
            _e("国家外汇管理局", "safe.gov.cn/AppStructured/hlw/RMBQuery.do", True,
               note="2026-10-13 实测：列页 `safe/rmbhlzjj/index.html` 200/16KB 只是 **iframe 外壳**"
                    "（无数据行）；真数据在 iframe 指向的 `AppStructured/hlw/RMBQuery.do`，"
                    "GET/POST 带 `startDate/endDate/queryYN=true` → 结果表 200/14KB，美元列 **672.98**"
                    "（=6.7298×100，与 CFETS **逐位相等**）⇒ **解析出真值，非只看 200**"),
            _e("腾讯", "qt.gtimg.cn（外汇口：**未找到可用符号**）", False,
               note="2026-10-13 实测：`q=USDCNY` 返 `v_pv_none_match=\"1\"`＝**空响应**（HTTP 200 但零数据）"
                    "⇒ 如实降为未验。此例暴露 smoke 曾把「200 + 非空字节」误判为绿，已加空响应哨兵"),
        ),
        note="⚠ **口径诚实**：中间价定盘现由**同一发布的三个官方渠道**（央行/外汇局/CFETS）提供"
             "**同一个价** ⇒ 达三源硬门；但**不是三次独立测量**（三渠道同日数值必须相等，是同一价的"
             "三处镜像）。即期/离岸报价另立值维「人民币即期汇率」，**不并入本维源数**",
    ),
    SourceSpec(
        value="人民币即期汇率",
        tolerance=(
            "同一交易日同时刻**现货**口径；**在岸**（CFETS USD/CNY 询价、新浪 fx_susdcny）与"
            "**离岸**（东财 USDCNH）并列，容差 |差| ≤ 0.02（离岸/在岸点差）——超容差即点名分歧，"
            "**绝不取平均**。⚠ 即期 ≠ 中间价定盘（另立「汇率中间价」维），两维不得互相凑源数"
        ),
        legs=(
            _e("中国外汇交易中心", "chinamoney.com.cn/r/cms/www/chinamoney/data/fx/rfx-sp-quot.json", True,
               note="2026-10-13 实测 200/2374B：USD/CNY 买 6.6940／卖 6.6943（实时询价行情，"
                    "约 5s 刷新）。真身＝外汇市场行情页 `chinese/mkdatapfx/` 片段 "
                    "`r/cms/chinese/chinamoney/html/fx/rfx-sp-quot-cn.html` 里的 "
                    "`DURL + 'fx/rfx-sp-quot.json'`（DURL=/r/cms/www/chinamoney/data/）"),
            _e("东方财富", "push2.eastmoney.com/api/qt/ulist.np/get（secids=133.USDCNH,119.USDCNY）", True,
               note="2026-10-13 实测 200/171B：USDCNH **6.6944**（离岸即期）。⚠ 本批只回 USDCNH 一行"
                    "（119.USDCNY 未回）；该端点会瞬时断连，重试即通"),
            _e("新浪财经", "hq.sinajs.cn/list=fx_susdcny（须 Referer）", True,
               note="2026-10-13 实测 200/222B（**须 Referer**，否则 403）：USD/CNY **6.6940**（在岸即期）"),
        ),
        note="三腿齐：CFETS 即期（在岸询价）/ 东财 USDCNH（离岸）/ 新浪 fx_susdcny（在岸）——"
             "同一交易日同量，可真独立比对（2026-10-13 三方 6.6940/6.6944/6.6940，差 ≤0.0004）；"
             "⚠ 与「汇率中间价」定盘**不是同一个量**，两维分列、互不凑数",
    ),
    SourceSpec(
        value="互联互通成交额",
        tolerance="只比成交额口径；⚠ 净买入 2024-08 起停披露；单位统一换算亿元",
        legs=(
            _e("东方财富", "datacenter-web…/RPT_MUTUAL_DEAL_HISTORY", True,
               note="2026-10-13 smoke 200/952B 有数（MUTUAL_TYPE 001/002/003/004 逐段；DEAL_AMT 单位百万元）"),
            _e("香港交易所", "hkex.com.hk/chi/csm/DailyStat/data_tab_daily_YYYYMMDDc.js", True,
               note="2026-10-13 复核实测 **200/9766B 纯 JSON**（`tabData = [ … ];` 去前后缀即 JSON）——"
                    "四段全覆盖（SSE/SZSE × North/South）；北向 RMB mil、南向 HKD mil；**约 7 个月滚动**。"
                    "真身＝统计页隐藏字段 hidCSMDailyStatJsonPathChi；此前误判为「HTML 页须解析」"),
            _e("上海证券交易所", "query.sse.com.cn/commonSoaQuery.do?sqlId=FW_HGTZL_HGTSCSJ_HGTCJGK_MRTJ", True,
               note="2026-10-13 复核实测 **200/687B 真数据**（`totalAmount` 亿元；沪股通）。"
                    "🔴 **必带 `Referer: https://www.sse.com.cn/`**——不带则 97B "
                    "`{\"success\":\"false\",\"errorType\":\"ExceptionInterceptor\"}`。"
                    "此前判「空壳」的真因＝**用错 host（commonQuery→commonSoaQuery）＋少 Referer**。"
                    "港股通(沪) 另有 `ggt/getQuatationInfo.do`（`TOTAL_AMOUNT`）"),
            _e("深圳证券交易所", "szse.cn/api/report/ShowReport/data?CATALOGID=SGT_SGTJYRB", True,
               note="2026-10-13 复核实测 200/1095B JSON（深股通「当日交易总额（亿元人民币）」）；"
                    "港股通(深) 用 CATALOGID=SGT_GGTJYRB。真身＝深港通页隐藏字段 data-s-catalog-id"),
        ),
        note="净买入结构性停披 ⇒ 该维结构性受限；成交额口径**四段均 ≥3 家独立机构**"
             "（沪股通：东财/港交所/上交所；深股通：东财/港交所/深交所；港股通沪/深 同理）。"
             "2026-10-13 三方逐日数值完全吻合（沪股通 1227.807 三方一致、深股通 1391.02、"
             "港股通沪 442.46、港股通深 267.53）",
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
    ("指数全成分股涨跌幅分布", "腾讯"): (
        "https://qt.gtimg.cn/q=sh600000,sz000001,sh601318"
    ),
    ("指数全成分股涨跌幅分布", "新浪"): (
        "https://hq.sinajs.cn/list=sh600000,sz000001,sh601318"
    ),
    # —— 汇率中间价（定盘：同一发布的三个官方渠道）——
    ("汇率中间价", "中国外汇交易中心"): (
        "https://www.chinamoney.com.cn/ags/ms/cm-u-bk-ccpr/CcprHisNew"
        "?startDate=2026-10-01&endDate=2026-10-13&currency=USD/CNY&pageSize=5"
    ),
    ("汇率中间价", "中国人民银行"): (
        "http://www.pbc.gov.cn/zhengcehuobisi/125207/125217/125925/index.html"
    ),
    ("汇率中间价", "国家外汇管理局"): (
        "https://www.safe.gov.cn/AppStructured/hlw/RMBQuery.do"
        "?startDate=2026-10-13&endDate=2026-10-13&queryYN=true"
    ),
    # 腾讯外汇口无可用符号（实测返 v_pv_none_match）⇒ 不给探针，smoke 如实记「无探针」。
    # —— 人民币即期汇率（现货：在岸/离岸同量三腿）——
    ("人民币即期汇率", "中国外汇交易中心"): (
        "https://www.chinamoney.com.cn/r/cms/www/chinamoney/data/fx/rfx-sp-quot.json"
    ),
    ("人民币即期汇率", "东方财富"): (
        "https://push2.eastmoney.com/api/qt/ulist.np/get"
        "?secids=133.USDCNH,119.USDCNY&fields=f12,f14,f2,f3&fltt=2&invt=2"
    ),
    ("人民币即期汇率", "新浪财经"): "https://hq.sinajs.cn/list=fx_susdcny",
    # —— 互联互通 ——
    ("互联互通成交额", "东方财富"): (
        "https://datacenter-web.eastmoney.com/api/data/v1/get"
        "?reportName=RPT_MUTUAL_DEAL_HISTORY&columns=ALL"
        "&pageNumber=1&pageSize=2&source=WEB&client=WEB"
    ),
    ("互联互通成交额", "香港交易所"): (
        "https://www.hkex.com.hk/chi/csm/DailyStat/data_tab_daily_20261013c.js"
    ),
    ("互联互通成交额", "上海证券交易所"): (
        "https://query.sse.com.cn/commonSoaQuery.do"
        "?sqlId=FW_HGTZL_HGTSCSJ_HGTCJGK_MRTJ&tradeDate=20261013"
    ),
    ("互联互通成交额", "深圳证券交易所"): (
        "https://www.szse.cn/api/report/ShowReport/data"
        "?SHOWTYPE=JSON&CATALOGID=SGT_SGTJYRB&TABKEY=tab1&txtDate=2026-10-13"
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
    ("汇率中间价", "中国人民银行"): {"Referer": "http://www.pbc.gov.cn/"},
    ("汇率中间价", "国家外汇管理局"): {"Referer": "https://www.safe.gov.cn/"},
    ("汇率中间价", "中国外汇交易中心"): {"Referer": "https://www.chinamoney.com.cn/"},
    ("人民币即期汇率", "新浪财经"): {"Referer": "https://finance.sina.com.cn"},
    ("人民币即期汇率", "中国外汇交易中心"): {"Referer": "https://www.chinamoney.com.cn/"},
    ("指数全成分股涨跌幅分布", "新浪"): {"Referer": "https://finance.sina.com.cn"},
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
#
# ⚠ 两条口径（2026-10-13 AI 审查后收紧）：
#  1) 标记一律写**去空格**形；smoke 比对前先 `re.sub(r"\s+", "", body)` —— 否则
#     `"data": null`（带空格）会漏判成假绿。
#  2) **不设 `<html`／`actionErrors` 一类标记**：港交所/统计局的腿本来就是 HTML
#     页面、上交所正常响应也带 `actionErrors: []`，加进去会误伤合法腿。
LEG_PROBE_EMPTY_MARKERS: tuple[str, ...] = (
    "v_pv_none_match",          # 腾讯：无此代码/无数据
    '"data":null',              # 东财/上交所：secid 或 sqlId 无效（上交所空壳的可靠标记）
    '"result":null',            # 东财：报表/查询无结果
    "报表配置不存在",              # 东财：reportName 写错
)

#: 按腿覆写：值为该腿专属标记（缺省回落到 LEG_PROBE_EMPTY_MARKERS）。
#: HTML 腿（港交所/统计局/中国天气网）天然含 JSON 片段与脚本，故**只挂它自己的**
#: 空页标记，不套 JSON 标记。
LEG_PROBE_EMPTY_MARKERS_BY_LEG: dict[tuple[str, str], tuple[str, ...]] = {
    ("宏观 CPI / PMI", "国家统计局"): (),          # HTML 发布页：无可判空标记，只判可达
    ("天气实况/预报/预警", "中国天气网"): (),        # 小 HTML 片段：同上
    ("互联互通成交额", "上海证券交易所"): ("ExceptionInterceptor",),  # 缺 Referer 时的 97B 错误壳
}


def probe_empty_markers(value: str, org: str) -> tuple[str, ...]:
    """取该腿的空响应标记（按腿覆写优先，缺省全局表）。"""
    return LEG_PROBE_EMPTY_MARKERS_BY_LEG.get((value, org), LEG_PROBE_EMPTY_MARKERS)


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
            f"「{value}」已达标：实测独立源 {len(spec.verified_orgs)} 家"
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
