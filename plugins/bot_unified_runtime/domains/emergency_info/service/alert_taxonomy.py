"""预警种类**权威注册表**（WP3，2026-09-21 用户裁定 3.A「不够，要更完善」）。

本文件是「预警有哪些种类、各类属于哪一族、族内合法色档与色序、哪些族当前有源、
哪一档可以击穿静默窗」的**唯一真身**（规格件
`docs/design/emergency-alert-taxonomy-20260921.md` 与本表一一对应，代码从这里派生，
下游禁止再造第二份表：定级 `service/grading.py`、订阅 `service/subscriptions.py`、
投递 `service/push.py`、帮助文案（echo 侧由主会话按交接段落盘）四处一律 import 本件）。

三条纪律（都是本域烧过账的地方）：

1. **绝不编数**。每个类别的 `availability` 只承认**已在真夹具里实测出现**的源
   （`tests/fixtures/emergency_info/*`，逐件 sha256 见该目录 README）；
   源体系里"应该有"但样例里没出现的，一律标 `declared` 并在 `evidence` 里写清
   「未在 2026-09-20 样例中出现」；四个源根本供不出的（风暴潮/海浪/海冰/火山喷发/
   空间天气/渍涝/中小河流洪水/森林火险等级/草原火险）标 **`none`＝无源**，
   订阅这一类会当场被告知「订了也不会命中」，帮助文案与 catalog 同样如实说。
2. **不杜撰官方色档**。色档只按**族**声明，用途唯一＝①校验用户在订阅里能说的档
   （"红色以上"用在一个结构上不会出红色的族上＝报错）、②族内击穿静默窗的地板。
   逐类官方色档数（例如「高温无蓝色」「霾无红色」这类）本表**不作声明**——未取证；
   实际出档由**源侧给的颜色词**决定（NMC 标题里的颜色词是实测字段，见
   `sources/nmc_alarm.py:split_alarm_title`），源不给色就不定色（D-1）。
3. **色序与等级同一把尺**。四色与 `EmergencyLevel`（D-3 单一枚举）的对应唯一出自
   `contracts.LEVEL_COLOR_LABEL`（红=P0 橙=P1 黄=P2 蓝=P3），序位 `rank` 与气象预警
   `_ALARM_COLOR_RANK` 同尺度；地震族用户口径列作「红橙黄蓝」（由高到低），
   与气象族「蓝黄橙红」（由低到高）**是同一组四色的两种陈列序**，
   本表用 `tier_order` 显式记陈列序、用 `color_tiers` 统一记升序判据，两者不得混用。

`SOURCE_IDS`（合法源身份唯一集合）由本件承担「真身常量的镜像」职责，
漂移由 `tests/test_emergency_info_core.py` 的 AST 锁对 `sources/*.py` 的
`SOURCE_ID` 常量逐字核（同一 AST 手法已用于 weather 颜色表收编锁）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from plugins.bot_unified_runtime.domains.emergency_info.contracts import (
    LEVEL_COLOR_LABEL,
    EmergencyItem,
    EmergencyLevel,
    level_from_color_label,
)

# ---------------------------------------------------------------- 色词（唯一出处）

BLUE = LEVEL_COLOR_LABEL[EmergencyLevel.P3]  # "蓝色"
YELLOW = LEVEL_COLOR_LABEL[EmergencyLevel.P2]  # "黄色"
ORANGE = LEVEL_COLOR_LABEL[EmergencyLevel.P1]  # "橙色"
RED = LEVEL_COLOR_LABEL[EmergencyLevel.P0]  # "红色"

#: 升序四色（低→高）。族内 `color_tiers` 一律用它或其子集，禁各处手抄色列表。
FOUR_TIER_ASC: tuple[str, ...] = (BLUE, YELLOW, ORANGE, RED)
#: 陈列序（高→低）：气象口径「蓝黄橙红」反向即升序；地震预警常用「红橙黄蓝」。
FOUR_TIER_DESC: tuple[str, ...] = tuple(reversed(FOUR_TIER_ASC))


# ---------------------------------------------------------------- 族

@dataclass(frozen=True)
class AlertFamily:
    """一族预警：合法色档（升序）+ 陈列序 + 可击穿静默窗的等级地板。"""

    family_id: str
    label: str
    color_tiers: tuple[str, ...] = FOUR_TIER_ASC
    tier_order: tuple[str, ...] = FOUR_TIER_DESC
    #: 「真正的高档」＝族内允许穿 00:00–06:00 静默窗的等级集合（D-2 的族级细化）。
    wake_levels: frozenset[EmergencyLevel] = frozenset(
        {EmergencyLevel.P0, EmergencyLevel.P1}
    )
    note: str = ""


_FAMILIES: dict[str, AlertFamily] = {}


def _family(
    family_id: str,
    label: str,
    *,
    color_tiers: tuple[str, ...] = FOUR_TIER_ASC,
    tier_order: tuple[str, ...] = FOUR_TIER_DESC,
    wake_levels: frozenset[EmergencyLevel] = frozenset(
        {EmergencyLevel.P0, EmergencyLevel.P1}
    ),
    note: str = "",
) -> AlertFamily:
    spec = AlertFamily(
        family_id=family_id,
        label=label,
        color_tiers=color_tiers,
        tier_order=tier_order,
        wake_levels=wake_levels,
        note=note,
    )
    _FAMILIES[family_id] = spec
    return spec


# `global_disaster`（GDACS）是**唯一有色档收窄**的族：源侧只有 Red/Orange 两个
# 会被映射成颜色词（`sources/gdacs.py:54 ALERT_LEVEL_COLOR`，Green 故意为空），
# 所以这一族结构上出不了「蓝色/黄色」——订阅「蓝色以上」对它无意义，必须报错而不是放行。
_FAMILY_IDS = (
    _family("meteo", "气象灾害预警信号", note="用户列出的 14 类 + 强对流等衍生类"),
    _family("hydro", "洪涝与水文气象风险"),
    _family("geo", "地质灾害气象风险"),
    _family("fire", "森林草原火险与火灾"),
    _family("marine", "海洋与风暴潮类"),
    _family("space", "空间天气（地磁暴/太阳风暴）"),
    _family(
        "quake",
        "地震预警与速报",
        tier_order=(RED, ORANGE, YELLOW, BLUE),
        note="用户口径「地震预警常用红、橙、黄、蓝」——同一组四色的降序陈列",
    ),
    _family("volcano", "火山"),
    _family(
        "global_disaster",
        "国际灾害事件（GDACS 聚合）",
        color_tiers=(ORANGE, RED),
        tier_order=(RED, ORANGE),
        wake_levels=frozenset({EmergencyLevel.P0}),
        note="源侧只有 Red/Orange 会成色；Green 不映射（不猜档）。橙色档不穿静默窗："
        "全量 Green 背景聚合里「中等相关」不足以叫醒一群人",
    ),
)


def families() -> tuple[AlertFamily, ...]:
    return tuple(_FAMILIES.values())


def family_of(family_id: str) -> AlertFamily | None:
    return _FAMILIES.get(str(family_id or "").strip())


# ---------------------------------------------------------------- 类别

#: 可用性三态（唯一词汇表，帮助文案与 catalog 只能抄这三个字面）。
AVAIL_OBSERVED = "observed"  # 真夹具里实测出现过（可复跑：见 evidence 字段）
AVAIL_DECLARED = "declared"  # 源体系收录该类型，但本次样例未见实例
AVAIL_NONE = "none"  # **无源**：四个源都供不了，订阅了也不会命中


@dataclass(frozen=True)
class AlertCategory:
    """一类预警的稳定身份 + 别名 + 族 + 来源可用性 + NMC 类型码。"""

    category_id: str
    label: str
    family_id: str
    aliases: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    availability: str = AVAIL_NONE
    evidence: str = ""
    #: NMC `pic` 文件名里的四位类型码（`p{type:04d}{level:03d}.png`，真样例实测形态）
    nmc_signal_type: str = ""

    @property
    def is_sourced(self) -> bool:
        return bool(self.sources) and self.availability != AVAIL_NONE

    @property
    def family(self) -> AlertFamily:
        spec = _FAMILIES.get(self.family_id)
        if spec is None:  # pragma: no cover - 构造期由自检锁拦住
            raise KeyError(f"未知预警族：{self.family_id}")
        return spec


_CATEGORIES: dict[str, AlertCategory] = {}


def _category(
    category_id: str,
    label: str,
    family_id: str,
    *,
    aliases: Iterable[str] = (),
    sources: Iterable[str] = (),
    availability: str = AVAIL_NONE,
    evidence: str = "",
    nmc_signal_type: str = "",
) -> AlertCategory:
    spec = AlertCategory(
        category_id=category_id,
        label=label,
        family_id=family_id,
        aliases=tuple(dict.fromkeys(str(a).strip() for a in aliases if str(a).strip())),
        sources=tuple(dict.fromkeys(str(s).strip() for s in sources if str(s).strip())),
        availability=availability,
        evidence=evidence,
        nmc_signal_type=nmc_signal_type,
    )
    if spec.family_id not in _FAMILIES:  # 构造期即拦，不留到运行期 KeyError
        raise KeyError(f"类别 {category_id} 指向未注册的族 {spec.family_id}")
    _CATEGORIES[category_id] = spec
    return spec


# ============================ A. 气象灾害预警信号 14 类（用户逐名列出） ============
_category(
    "typhoon", "台风", "meteo",
    aliases=("台风", "热带气旋", "飓风", "typhoon"),
    sources=("nmc", "gdacs"), availability=AVAIL_DECLARED,
    evidence="NMC 预警类型体系收录，2026-09-20 真样例 300 条内未见实例；"
             "GDACS 真样例 eventtype=TC 实测 2 条（境外口径）",
)
_category(
    "rainstorm", "暴雨", "meteo",
    aliases=("暴雨", "特大暴雨", "强降雨", "短时强降水"),
    sources=("nmc",), availability=AVAIL_OBSERVED,
    evidence="真样例 nmc_findAlarm：kind=暴雨 37 条（蓝27/黄7/橙3）；pic 码 p0002003 等",
    nmc_signal_type="0002",
)
_category(
    "snowstorm", "暴雪", "meteo",
    aliases=("暴雪", "大雪", "强降雪"),
    sources=("nmc",), availability=AVAIL_DECLARED,
    evidence="NMC 预警类型体系收录，本次样例 300 条内未见实例（季节性强）",
)
_category(
    "cold_wave", "寒潮", "meteo",
    aliases=("寒潮", "强降温", "剧烈降温"),
    sources=("nmc",), availability=AVAIL_OBSERVED,
    evidence="真样例 kind=寒潮 8 条，全部蓝色（pic p0004004）",
    nmc_signal_type="0004",
)
_category(
    "gale", "大风", "meteo",
    aliases=("大风", "陆地大风", "强风"),
    sources=("nmc",), availability=AVAIL_OBSERVED,
    evidence="真样例 kind=大风 67 条（蓝65/黄2；pic p0007004/p0007003）",
    nmc_signal_type="0007",
)
_category(
    "dust_storm", "沙尘暴", "meteo",
    aliases=("沙尘暴", "强沙尘暴", "扬沙", "浮尘"),
    sources=("nmc",), availability=AVAIL_DECLARED,
    evidence="NMC 预警类型体系收录，本次样例内未见实例",
)
_category(
    "heatwave", "高温", "meteo",
    aliases=("高温", "酷热"),
    sources=("nmc",), availability=AVAIL_OBSERVED,
    evidence="真样例 kind=高温 37 条（黄36/橙1；pic p0003003/p0003002）",
    nmc_signal_type="0003",
)
_category(
    "drought", "干旱", "meteo",
    aliases=("干旱", "气象干旱", "秋伏旱"),
    sources=("nmc",), availability=AVAIL_DECLARED,
    evidence="NMC 预警类型体系收录，本次样例内未见实例",
)
_category(
    "lightning", "雷电", "meteo",
    aliases=("雷电", "雷暴", "打雷", "闪电"),
    sources=("nmc",), availability=AVAIL_OBSERVED,
    evidence="真样例 kind=雷电 80 条，全部黄色（pic p0012003）",
    nmc_signal_type="0012",
)
_category(
    "hail", "冰雹", "meteo",
    aliases=("冰雹", "雹灾"),
    sources=("nmc",), availability=AVAIL_OBSERVED,
    evidence="真样例 kind=冰雹 5 条（黄2/橙3；pic p0009002/p0009003）",
    nmc_signal_type="0009",
)
_category(
    "frost", "霜冻", "meteo",
    aliases=("霜冻", "霜害", "早霜", "晚霜"),
    sources=("nmc",), availability=AVAIL_OBSERVED,
    evidence="真样例 kind=霜冻 7 条，全部蓝色（pic p0013004）",
    nmc_signal_type="0013",
)
_category(
    "fog", "大雾", "meteo",
    aliases=("大雾", "浓雾", "强浓雾", "团雾", "雾"),
    sources=("nmc",), availability=AVAIL_OBSERVED,
    evidence="真样例 kind=大雾 35 条（黄34/橙1；pic p0005003/p0005002）",
    nmc_signal_type="0005",
)
_category(
    "haze", "霾", "meteo",
    aliases=("霾", "雾霾", "灰霾", "重霾"),
    sources=("nmc",), availability=AVAIL_DECLARED,
    evidence="NMC 预警类型体系收录，本次样例内未见实例",
)
_category(
    "road_ice", "道路结冰", "meteo",
    aliases=("道路结冰", "路面结冰", "积雪结冰"),
    sources=("nmc",), availability=AVAIL_OBSERVED,
    evidence="真样例 kind=道路结冰 1 条，黄色（pic p0011003）",
    nmc_signal_type="0011",
)

# ============================ B. 其他相关预警（用户逐名列出） ====================
_category(
    "severe_convection", "强对流天气", "meteo",
    aliases=("强对流", "强对流天气", "雷雨大风", "雷暴大风", "飑线"),
    sources=("nmc",), availability=AVAIL_OBSERVED,
    evidence="真样例实测三种形态：雷雨大风 10 条（黄，pic p0015003）、雷暴大风 6 条"
             "（蓝2黄4，pic p0042003/p0042004）；「强对流」本身作为总称在标题里可匹配",
    nmc_signal_type="0015",
)
_category(
    "sea_thunder_gale", "海上雷雨大风", "meteo",
    aliases=("海上雷雨大风", "海上大风"),
    sources=("nmc",), availability=AVAIL_OBSERVED,
    evidence="真样例 kind=海上雷雨大风 1 条，黄色（pic p0000003——类型码 0000 实测形态）",
    nmc_signal_type="0000",
)
_category(
    "geo_hazard_risk", "地质灾害气象风险", "geo",
    aliases=("地质灾害", "地质灾害气象风险", "山体滑坡", "滑坡", "泥石流", "崩塌"),
    sources=("nmc",), availability=AVAIL_OBSERVED,
    evidence="真样例 kind=地质灾害 5 条，全部黄色（pic p0021003）",
    nmc_signal_type="0021",
)
_category(
    "mountain_flood_risk", "山洪灾害气象风险", "hydro",
    aliases=("山洪灾害", "山洪", "山洪灾害气象"),
    sources=("nmc",), availability=AVAIL_OBSERVED,
    evidence="真样例 kind=山洪灾害 1 条，黄色（pic p0024003）",
    nmc_signal_type="0024",
)
_category(
    "river_flood", "中小河流洪水", "hydro",
    aliases=("中小河流洪水", "中小河流", "河流洪水"),
    sources=(), availability=AVAIL_NONE,
    evidence="**无源**：该预警由水利部与中国气象局联合发布，本域四源（nmc/icl/usgs/gdacs）"
             "端点里均无此通道；GDACS 的 FL 是「洪水事件」不是「中小河流洪水气象风险」，"
             "不接受伪映射",
)
_category(
    "waterlogging", "渍涝", "hydro",
    aliases=("渍涝", "内涝", "城市内涝", "农田渍涝"),
    sources=(), availability=AVAIL_NONE,
    evidence="**无源**：本域四源无该类型通道（NMC 2026-09-20 样例 14 种 kind 里没有）",
)
_category(
    "flood_event", "洪水（国际事件）", "global_disaster",
    aliases=("洪水", "洪灾"),
    sources=("gdacs",), availability=AVAIL_OBSERVED,
    evidence="真样例 gdacs_eventlist：eventtype=FL 实测 5 条（alertlevel 全 Green ⇒ 不映射颜色）",
)
_category(
    "forest_fire_risk", "森林火险", "fire",
    aliases=("森林火险", "森林火险等级", "森林（草原）火险"),
    sources=(), availability=AVAIL_NONE,
    evidence="**无源**：火险等级预报不在本域四源端点内（NMC 样例 kind 未见）；"
             "已发生的森林火灾事件另有 wildfire 类（GDACS WF 实测）",
)
_category(
    "grassland_fire_risk", "草原火险", "fire",
    aliases=("草原火险", "草原火灾风险"),
    sources=(), availability=AVAIL_NONE,
    evidence="**无源**：同上，本域四源无该通道",
)
_category(
    "wildfire", "森林草原火灾（国际事件）", "global_disaster",
    aliases=("野火", "林火", "草原火灾"),
    sources=("gdacs",), availability=AVAIL_OBSERVED,
    evidence="真样例 gdacs_eventlist：eventtype=WF 实测 84 条（alertlevel 全 Green）",
)
_category(
    "storm_surge", "风暴潮", "marine",
    aliases=("风暴潮",),
    sources=(), availability=AVAIL_NONE,
    evidence="**无源**：国家海洋预报台通道不在本域四源内（诚实不接，不做伪映射）",
)
_category(
    "ocean_wave", "海浪", "marine",
    aliases=("海浪", "大浪", "灾害性海浪"),
    sources=(), availability=AVAIL_NONE,
    evidence="**无源**：同上",
)
_category(
    "tsunami", "海啸", "marine",
    aliases=("海啸",),
    sources=(), availability=AVAIL_NONE,
    evidence="**无源**：GDACS 体系里有 TS 码，但 2026-09-20 真样例 101 条里没有一条，"
             "不据「体系里有」就宣称可用；国内海啸预警通道未接入",
)
_category(
    "sea_ice", "海冰", "marine",
    aliases=("海冰", "结冰"),
    sources=(), availability=AVAIL_NONE,
    evidence="**无源**：海洋预报通道未接入",
)
_category(
    "earthquake", "地震", "quake",
    aliases=("地震", "震情", "地震速报"),
    sources=("icl", "usgs", "gdacs"), availability=AVAIL_OBSERVED,
    evidence="真样例三源齐：icl_earlywarnings（magnitude 3.9/4.3 等）、"
             "usgs_all_hour（4 条）、gdacs_eventlist eventtype=EQ 实测 9 条",
)
_category(
    "volcanic_eruption", "火山喷发", "volcano",
    aliases=("火山", "火山喷发", "火山灰"),
    sources=(), availability=AVAIL_NONE,
    evidence="**无源**：GDACS 体系含 VO 码但真样例未见；本域无火山通道（不接就不说）",
)
_category(
    "space_weather", "空间天气", "space",
    aliases=("空间天气", "地磁暴", "太阳风暴", "磁暴", "太阳耀斑", "极光"),
    sources=(), availability=AVAIL_NONE,
    evidence="**无源**：国家空间天气监测预警中心通道不在本域四源内；"
             "NMC findAlarm 不发空间天气类",
)

#: 别名 → 类别的稳定倒排（长别名优先，防「雷雨大风」被「大风」抢先）。
_ALIAS_INDEX: dict[str, str] = {}
for _spec in _CATEGORIES.values():
    for _alias in (_spec.label, *_spec.aliases):
        _ALIAS_INDEX.setdefault(_alias, _spec.category_id)
_ALIASES_BY_LENGTH_DESC: tuple[str, ...] = tuple(
    sorted(_ALIAS_INDEX, key=lambda term: (-len(term), term))
)


# ---------------------------------------------------------------- 源身份真身镜像

#: 四个采集源真身 `SOURCE_ID` 的镜像（唯一用途＝校验 `auto_approve_sources` 之类的
#: 「填了不生效」面）。与 `sources/*.py` 常量的逐字相等由
#: `tests/test_emergency_info_core.py::test_taxonomy_source_ids_match_the_real_source_constants`
#: 用 AST 核（不在运行期 import sources，免得把 http/urllib 面拖进纯规则层）。
SOURCE_IDS: frozenset[str] = frozenset({"nmc", "icl", "usgs", "gdacs"})

#: 族 id 字面（下游只做比较，不重建表；拼错＝注册表里查不到＝测试红）。
QUAKE_FAMILY_ID = "quake"
METEO_FAMILY_ID = "meteo"
GLOBAL_DISASTER_FAMILY_ID = "global_disaster"

#: 高频引用点的类别 id 常量（采集侧/测试侧只认这两个字面，禁各处再抄字符串）。
EARTHQUAKE_CATEGORY_ID = "earthquake"
FLOOD_EVENT_CATEGORY_ID = "flood_event"

#: NMC `pic` 文件名四位类型码 → 类别（仅收录真样例实测到的码，未实测不编）。
#: 一个类别可能有多种图码（「强对流天气」在真样例里就有 0015 雷雨大风 与
#: 0042 雷暴大风 两种），主码写在类别的 `nmc_signal_type` 上、其余列在这里，
#: 两处都只收实测码；合并口唯一，下游一律读 `NMC_SIGNAL_TYPE_TO_CATEGORY`。
_NMC_EXTRA_SIGNAL_TYPES: dict[str, str] = {
    "0042": "severe_convection",
}

NMC_SIGNAL_TYPE_TO_CATEGORY: dict[str, str] = {
    **{
        spec.nmc_signal_type: spec.category_id
        for spec in _CATEGORIES.values()
        if spec.nmc_signal_type
    },
    **_NMC_EXTRA_SIGNAL_TYPES,
}
#: NMC 颜色序号（`p{type:04d}{level:03d}` 的末三位）——002 橙 / 003 黄 / 004 蓝 为实测，
#: 001（红）**未在本次样例中出现**，仍按 NMC 色序收录但由色词路径出档，不据图码猜红。
NMC_LEVEL_SUFFIX_TO_COLOR: dict[str, str] = {
    "001": RED,
    "002": ORANGE,
    "003": YELLOW,
    "004": BLUE,
}

#: 「中国境内」近似矩形：唯一真身在 `sources/open_data_quakes.py:CHINA_RECT`
#: （E11 §4 签名裁定的四至）。此处只作镜像供定级判「境内/境外」，
#: 漂移由 AST 锁 `test_taxonomy_china_rect_matches_the_quake_source` 拦住。
CHINA_INLAND_RECT: tuple[float, float, float, float] = (18.0, 73.0, 54.0, 135.0)


# ---------------------------------------------------------------- 查询口

def categories() -> tuple[AlertCategory, ...]:
    return tuple(_CATEGORIES.values())


def category(category_id: str) -> AlertCategory | None:
    return _CATEGORIES.get(str(category_id or "").strip())


def category_or_raise(category_id: str) -> AlertCategory:
    spec = category(category_id)
    if spec is None:
        raise KeyError(f"未知预警类别：{category_id}")
    return spec


def family_for(category_id: str) -> AlertFamily:
    spec = category(category_id)
    return spec.family if spec is not None else _FAMILIES["meteo"]


def label_of(category_id: str) -> str:
    spec = category(category_id)
    return spec.label if spec is not None else str(category_id or "")


def color_tiers_for(category_id: str) -> tuple[str, ...]:
    """该类别所在族的合法色档（升序）——订阅校验唯一依据。"""
    return family_for(category_id).color_tiers


def is_legal_color(category_id: str, color_label: str) -> bool:
    color = str(color_label or "").strip()
    return bool(color) and color in color_tiers_for(category_id)


def level_is_attainable(category_id: str, level: EmergencyLevel | None) -> bool:
    """该类别结构上能不能出这一档（GDACS 族出不了蓝/黄；其余四色族都能）。未定级＝否。"""
    if level is None:
        return False
    return level in levels_of_tiers(color_tiers_for(category_id))


def levels_of_tiers(tiers: Iterable[str]) -> tuple[EmergencyLevel, ...]:
    """色档（升序色词）→ 等级（升序），唯一换算口。"""
    out: list[EmergencyLevel] = []
    for tier in tiers:
        level = level_from_color_label(tier)
        if level is not None:
            out.append(level)
    return tuple(out)


def wake_levels(category_id: str) -> frozenset[EmergencyLevel]:
    """族内「真正的高档」＝允许击穿静默窗的等级集合（唯一判据）。"""
    return family_for(category_id).wake_levels


def may_breach_quiet_window(
    category_id: str, level: EmergencyLevel | None
) -> bool:
    """定级结果是否够格穿 00:00–06:00 静默窗（未定级一律否，D-1）。"""
    if level is None:
        return False
    return level in wake_levels(category_id)


def silence_breach_rules() -> tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...]:
    """显式击穿规则表（族 → 合法色档 / 可穿窗等级），供规格与文档逐字对照。"""
    return tuple(
        (
            spec.family_id,
            spec.label,
            spec.color_tiers,
            tuple(level.value for level in sorted(spec.wake_levels, key=lambda v: -v.rank)),
        )
        for spec in _FAMILIES.values()
    )


def resolve_category(
    text: str = "",
    *,
    source_id: str = "",
    source_kind: str = "",
    preset: str = "",
) -> str:
    """一段文本（+ 源侧类型码/源身份）→ 类别 id；认不出返回空串（不猜、不硬套）。

    判定序（写进规格 §四）：显式 `preset` → NMC 图码 → 别名长优先匹配 → 源身份兜底。
    """
    wanted = str(preset or "").strip()
    if wanted in _CATEGORIES:
        return wanted
    haystack = str(text or "")
    for term in _ALIASES_BY_LENGTH_DESC:
        if term and term in haystack:
            return _ALIAS_INDEX[term]
    kind = str(source_kind or "").strip().lower()
    if kind == "earthquake":
        return "earthquake"
    sid = str(source_id or "").strip().lower()
    if sid == "gdacs" and kind == "global_disaster":
        return ""  # GDACS 事件种类必须从 eventtype 中文名里认，认不出就是认不出
    return ""


def category_of_item(item: EmergencyItem) -> str:
    """条目 → 类别 id：库里已解析过的优先，否则按标题/正文现算（纯文本，零 IO）。"""
    preset = str(getattr(item, "category_id", "") or "").strip()
    text = " ".join(
        str(value or "") for value in (item.title, item.body, item.source_kind)
    )
    return resolve_category(
        text,
        source_id=str(item.source_id or ""),
        source_kind=str(item.source_kind or ""),
        preset=preset,
    )


def unsourced_categories() -> tuple[AlertCategory, ...]:
    """当前**无源**的类别（帮助文案/catalog 必须逐条说出来的那一份）。"""
    return tuple(spec for spec in _CATEGORIES.values() if not spec.is_sourced)


def availability_text(category_id: str) -> str:
    """一句人话的来源可用性（帮助/回显用；口径唯一，禁各处自写）。"""
    spec = category(category_id)
    if spec is None:
        return "未收录的类别"
    if not spec.is_sourced:
        return "无源（本域四源供不了，订阅了也不会命中）"
    if spec.availability == AVAIL_DECLARED:
        return f"有源（{'+'.join(spec.sources)}），但 2026-09-20 样例未见实例"
    return f"有源（{'+'.join(spec.sources)}），真样例实测"


def is_known_category(term: str) -> bool:
    """用户写的一个词是否命中注册表（订阅面区分「类别」与「开放词表杂词」）。"""
    token = str(term or "").strip()
    if token in _CATEGORIES:
        return True
    return bool(token) and token in _ALIAS_INDEX


def category_id_for_term(term: str) -> str:
    token = str(term or "").strip()
    if token in _CATEGORIES:
        return token
    return _ALIAS_INDEX.get(token, "")


def all_labels() -> tuple[str, ...]:
    """全部类别中文名（帮助文案用，顺序=注册顺序=用户列举顺序）。"""
    return tuple(spec.label for spec in _CATEGORIES.values())


def count_summary() -> dict[str, object]:
    """注册表规模统计（测试与文档逐字对照用，避免"看起来全"的口头宣称）。"""
    return {
        "categories": len(_CATEGORIES),
        "families": len(_FAMILIES),
        "sourced": sum(1 for spec in _CATEGORIES.values() if spec.is_sourced),
        "unsourced": sum(1 for spec in _CATEGORIES.values() if not spec.is_sourced),
        "observed": sum(
            1 for spec in _CATEGORIES.values()
            if spec.availability == AVAIL_OBSERVED
        ),
        "declared": sum(
            1 for spec in _CATEGORIES.values()
            if spec.availability == AVAIL_DECLARED
        ),
    }


__all__ = [
    "AVAIL_DECLARED",
    "AVAIL_NONE",
    "AVAIL_OBSERVED",
    "BLUE",
    "CHINA_INLAND_RECT",
    "EARTHQUAKE_CATEGORY_ID",
    "FLOOD_EVENT_CATEGORY_ID",
    "FOUR_TIER_ASC",
    "FOUR_TIER_DESC",
    "GLOBAL_DISASTER_FAMILY_ID",
    "METEO_FAMILY_ID",
    "NMC_LEVEL_SUFFIX_TO_COLOR",
    "NMC_SIGNAL_TYPE_TO_CATEGORY",
    "ORANGE",
    "RED",
    "SOURCE_IDS",
    "YELLOW",
    "AlertCategory",
    "AlertFamily",
    "all_labels",
    "availability_text",
    "categories",
    "category",
    "category_id_for_term",
    "category_of_item",
    "color_tiers_for",
    "family_for",
    "family_of",
    "is_known_category",
    "is_legal_color",
    "label_of",
    "level_is_attainable",
    "levels_of_tiers",
    "may_breach_quiet_window",
    "resolve_category",
    "silence_breach_rules",
    "unsourced_categories",
    "wake_levels",
]
