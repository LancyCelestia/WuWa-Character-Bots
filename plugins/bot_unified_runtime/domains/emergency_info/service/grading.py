"""规则定级（产品裁定 D-6：`grade()` 是无网络、无 LLM 的纯函数）。

判定序的唯一权威是 `docs/design/emergency-alert-taxonomy-20260921.md` §四/§五，
本文件照它落地，序位不可调换：

```
grading_candidates(item, now, rules):
  0) item.expires_at <= now           → 无候选（过期不得冒充紧急，D-2 兜底）
  1) category = alert_taxonomy.category_of_item(item)   # 库里 id 优先，否则别名表现算
  2) quake 族：有震级 → 震级/深度/境内境外分档（唯一档，直接返回）
                无震级 → 只认源侧官方色（GDACS Red/Orange 那条路），种类词与关键词一律不参与
  3) 其余族：源侧 color_label（族内合法才计）
              ∪ 标题/正文里的族内合法色词
              ∪ 影响面硬事实关键词（缺省表 + 注入表，同样族内合法才计）
grade(item, ...) = 取候选最高档；空集落 FALLBACK_LEVEL=P3（蓝，诚实不上抬）
```

六条设计要点：

1. **等级唯一**：返回值只能是本域单一枚举 `EmergencyLevel` 的四枚之一（D-3），
   不返回 None、不抛「定级失败」——定不出档就落最低档 P3（蓝），
   因为「判不出更严重」在事实层面就等于「按最低档对待」，
   而「源都没给」在采集侧已由 `build_emergency_item` 拦下（D-1）。
2. **颜色优先于种类词，且三条腿一律族内合法才计**：「暴雨蓝色预警」＝蓝档；
   「航班延误」出现在只有橙/红两档的国际灾害事件上＝错配噪声，不得造出黄档
   （T8 补的关键词腿闸，REV-WP3 判定 6-2；锁在
   `tests/test_emergency_grading_family_legality.py`）。旧实现把种类词
   （`暴雨`/`台风`/`地震`…）塞进关键词表并与颜色取最高档，等于凭空把蓝抬成橙、
   把 M0.6 南极微震抬成红，是穿窗误报的根因（审计 E6-N1）。现在种类词**整体退出**
   关键词表（由 `tests/test_emergency_info_taxonomy.py::
   test_default_keyword_table_contains_no_category_words` 锁死），残留关键词只描述
   「已经造成的后果 / 已经下达的强制动作」。
3. **地震只吃数、不吃字**：`earthquake_level()` 是 §五 分档表的唯一落点（本域代理规则，
   **不是官方烈度色**——ICL/USGS 不给烈度与颜色，多少级算红是产品裁定，改数只改这一处）。
   无震级数值 ⇒ 该路径不出候选，绝不用「地震」二字顶替一个数。
4. **时钟注入**：`now` 为必填参数，模块内**不得**出现 `datetime.now()`；唯一用到的时间
   规则是「已过期条目不得升档」。方向性由 AST 纯净锁 + 过期降档锁共同钉死。
5. **不读配置、不发网络**：族级地板与境内矩形都取自同域纯数据件 `alert_taxonomy`
   （规格 §九：本次只把它加进允许 import 前缀，两条纯度判据不变）；
   `bot_emergency_info_quiet_breach_levels` 那枚键由装配侧经
   `may_breach_quiet_window_intersects_floor(source_levels=…)` 注入（S-FIX-QUIET-T3
   取交腿；键未落 config.py 前 root 不传值，`None`＝现状族级地板），本模块不 import config。
6. **规则表可注入**：`rules` 参数让管理侧/评审席替换**关键词**表而不动代码；注入表
   只影响第 3 步的关键词腿（quake 族与颜色腿按源侧事实走，不受词表摆布）。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from plugins.bot_unified_runtime.domains.emergency_info.contracts import (
    LEVEL_COLOR_LABEL,
    EmergencyItem,
    EmergencyLevel,
    as_utc,
    highest_level,
    level_from_color_label,
)
from plugins.bot_unified_runtime.domains.emergency_info.service import (
    alert_taxonomy as _taxonomy,
)

#: 一条规则都命中时的缺省档（最低档=蓝；诚实不上抬）。
FALLBACK_LEVEL = EmergencyLevel.P3

#: 由高到低的等级序（降一档运算唯一取用口，禁各处再抄一份顺序表）。
_LEVELS_DESC: tuple[EmergencyLevel, ...] = (
    EmergencyLevel.P0,
    EmergencyLevel.P1,
    EmergencyLevel.P2,
    EmergencyLevel.P3,
)


@dataclass(frozen=True)
class GradingRule:
    """一档关键词族规则：命中任一关键词即提出对应等级候选。"""

    level: EmergencyLevel
    keywords: tuple[str, ...]
    note: str


# 缺省规则表（规格 §四 那张表的逐字落地；评审可替换，但换完要过同一把种类词锁）。
# 刻意只留「已经造成的后果 / 已经下达的强制动作」：预警**种类名**一律不进这张表，
# 认种类是 `alert_taxonomy` 的活、定档是颜色与震级的活，三者不得互相顶替。
DEFAULT_GRADING_RULES: tuple[GradingRule, ...] = (
    GradingRule(
        EmergencyLevel.P0,
        (
            "特别重大",
            "特大",
            "紧急疏散",
            "撤离",
            "转移安置",
            "停课",
            "停运",
            "溃坝",
            "决堤",
            "死亡",
            "遇难",
            "失联",
            "洪峰",
            "爆炸",
        ),
        "人命与强制处置已下达类：红色档",
    ),
    GradingRule(
        EmergencyLevel.P1,
        (
            "重大",
            "泄漏",
            "泄露",
            "停水",
            "停电",
            "交通中断",
            "封路",
        ),
        "公共服务与交通中断类：橙色档",
    ),
    GradingRule(
        EmergencyLevel.P2,
        ("积水", "管制", "延误", "道路封闭"),
        "影响较轻但需知悉类：黄色档",
    ),
)

# ---------------------------------------------------------------- 地震分档（§五）

#: 低于此震级一律蓝档，**且不被任何关键词抬档**（规格 §五：信息级速报不叫醒人）。
EARTHQUAKE_INFO_MAX_MAGNITUDE = 3.0
#: 震源深度超过此值（km）降一档，只降一档不降两档（深源面波能量衰减，同为产品裁定）。
EARTHQUAKE_DEEP_THRESHOLD_KM = 100.0

#: 境内分档表（`M >= 门槛` 由高到低取第一档命中；表尾之外即蓝档）。
_INLAND_MAGNITUDE_TIERS: tuple[tuple[float, EmergencyLevel], ...] = (
    (6.5, EmergencyLevel.P0),
    (5.0, EmergencyLevel.P1),
    (4.0, EmergencyLevel.P2),
)
#: 境外分档表：**结构上出不了红**（不为本半球外的震级半夜叫醒一屋子人）。
_OVERSEAS_MAGNITUDE_TIERS: tuple[tuple[float, EmergencyLevel], ...] = (
    (8.0, EmergencyLevel.P1),
    (6.5, EmergencyLevel.P2),
)


def is_china_inland(
    latitude: float | None, longitude: float | None
) -> bool:
    """震中是否落在境内矩形（四至唯一真身＝`alert_taxonomy.CHINA_INLAND_RECT` 镜像）。

    缺任一半坐标 ⇒ 判不出境内境外 ⇒ 返回 False 按**境外**处理（保守不上抬，§五）。
    本函数与 `earthquake_level()` 都不读墙钟、不读配置、不发网络（D-6）。
    """
    if latitude is None or longitude is None:
        return False
    min_lat, min_lon, max_lat, max_lon = _taxonomy.CHINA_INLAND_RECT
    return min_lat <= float(latitude) <= max_lat and min_lon <= float(longitude) <= max_lon


def _down_one_step(level: EmergencyLevel) -> EmergencyLevel:
    """降一档；已在最低档就停住（不降两档、不降出枚举）。"""
    index = _LEVELS_DESC.index(level)
    return _LEVELS_DESC[min(index + 1, len(_LEVELS_DESC) - 1)]


def earthquake_level(
    magnitude: float | None,
    *,
    depth_km: float | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> EmergencyLevel:
    """§五 地震分档表（**本域代理规则，不是官方烈度色**）的唯一落点。

    输入只有三枚源侧事实：震级、震源深度、震中坐标。三者拿不到就按「没有这个事实」
    处理（无震级 ⇒ 最低档；无坐标 ⇒ 按境外），绝不用标题里有没有「地震」二字顶替。
    """
    if magnitude is None:
        return FALLBACK_LEVEL
    value = float(magnitude)
    if value < EARTHQUAKE_INFO_MAX_MAGNITUDE:
        return FALLBACK_LEVEL
    tiers = (
        _INLAND_MAGNITUDE_TIERS
        if is_china_inland(latitude, longitude)
        else _OVERSEAS_MAGNITUDE_TIERS
    )
    level = FALLBACK_LEVEL
    for floor, candidate in tiers:
        if value >= floor:
            level = candidate
            break
    if depth_km is not None and float(depth_km) > EARTHQUAKE_DEEP_THRESHOLD_KM:
        level = _down_one_step(level)
    return level


def matched_levels(
    text: str, rules: Sequence[GradingRule] = DEFAULT_GRADING_RULES
) -> list[EmergencyLevel]:
    """规则表命中的候选等级列表（保持传入规则序，供调试与审计回显）。"""
    haystack = str(text or "")
    if not haystack:
        return []
    hits: list[EmergencyLevel] = []
    for rule in rules:
        if any(keyword and keyword in haystack for keyword in rule.keywords):
            hits.append(rule.level)
    return hits


def color_levels_in_text(
    text: str,
) -> list[EmergencyLevel]:
    """正文里出现的预警颜色词也计候选（气象预警的颜色词本就长在标题里）。

    族内合法性由调用方判（`_legal_color_levels`）：`global_disaster` 族结构上只有
    橙/红，从一段外文标题里认出「蓝色」是噪声而不是档位（规格 §三/§四）。
    """
    haystack = str(text or "")
    return [
        level
        for level, label in LEVEL_COLOR_LABEL.items()
        if label and label in haystack
    ]


def _legal_color_levels(category_id: str) -> frozenset[EmergencyLevel]:
    """该条目所在族的合法色档 → 等级集合（换算唯一出口＝注册表 `levels_of_tiers`）。"""
    return frozenset(
        _taxonomy.levels_of_tiers(_taxonomy.color_tiers_for(category_id))
    )


def grading_candidates(
    item: EmergencyItem,
    *,
    now: datetime,
    rules: Sequence[GradingRule] = DEFAULT_GRADING_RULES,
) -> list[EmergencyLevel]:
    """按 §四 判定序逐条列出「哪些判据提出了哪些档」——定级的**调试/复算出口**。

    诚实定位（T8，2026-09-22；此前写作「可审计面」）：本函数是 `grade()` 的唯一
    判据真身（`grade` 就是吃本函数的结果），所以对同一条 item 重放本函数即可复算
    「为什么是这一档」；但**候选列表本身没有任何生产消费方**——落库回写只存最终档
    与类别（`store.set_level`），聊天诊断面（`domains/ops/smoke`）不在采集 job 的
    路径上，线上没有一份「当轮候选」的留痕可查。要把它升格成真正的审计面，须另行
    授权接进既有落库/诊断出口（禁新建第三条审计通路）。
    **不含兜底档**：空列表＝「什么判据都没中」，`grade()` 据此落 P3，
    这样「已判为蓝」与「判不出所以按蓝对待」在复算面上仍是两件事。
    """
    current = as_utc(now)
    if item.expires_at is not None and item.expires_at <= current:
        return []
    category_id = _taxonomy.category_of_item(item)
    family = _taxonomy.family_for(category_id)
    source_level = level_from_color_label(item.color_label)
    legal = _legal_color_levels(category_id)

    if family.family_id == _taxonomy.QUAKE_FAMILY_ID:
        if item.magnitude is not None:
            # 震级/深度/坐标三枚事实 ⇒ 唯一档，颜色与关键词都不参与（§四 2、§五）。
            return [
                earthquake_level(
                    item.magnitude,
                    depth_km=item.depth_km,
                    latitude=item.latitude,
                    longitude=item.longitude,
                )
            ]
        # 无震级 ⇒ 只允许**源侧官方色**出档（GDACS 的 Red/Orange 那条路留着）；
        # 标题里的色词与种类词一律不计——速报正文写什么都有可能，数才是事实。
        if source_level is not None and source_level in legal:
            return [source_level]
        return []

    candidates: list[EmergencyLevel] = []
    if source_level is not None and source_level in legal:
        candidates.append(source_level)
    text = f"{item.title}\n{item.body}"
    candidates.extend(
        level for level in color_levels_in_text(text) if level in legal
    )
    # 关键词腿同两色腿一律族内合法才计（T8，2026-09-22，REV-WP3 判定 6-2）：
    # 族结构上出不了的档 ⇒ 关键词再硬也是错配，按噪声丢弃；注入表同闸。
    candidates.extend(
        level for level in matched_levels(text, rules) if level in legal
    )
    return candidates


def grade(
    item: EmergencyItem,
    *,
    now: datetime,
    rules: Sequence[GradingRule] = DEFAULT_GRADING_RULES,
) -> EmergencyLevel:
    """纯规则定级：候选取最高档，一条判据都不中则落 P3（`grading_candidates` 的投影）。

    已过期条目（`expires_at <= now`）无候选 ⇒ 必然 `FALLBACK_LEVEL`，
    这是 D-2「仅 P0/P1 穿安静时间」的兜底防线：陈旧信息不得冒充紧急。
    """
    candidates = grading_candidates(item, now=now, rules=rules)
    if not candidates:
        return FALLBACK_LEVEL
    return highest_level(candidates)


def may_breach_quiet_window(
    item: EmergencyItem,
    level: EmergencyLevel | None,
    *,
    allowed_levels: Sequence[str] | None = None,
) -> bool:
    """这条定级结果够不够格在 00:00–06:00 静默窗内叫醒人。

    判据真身在 `alert_taxonomy`（族级地板＝该族「真正的高档」），本函数只做两件事：
    ①把「条目」换算成类别（`category_of_item`，唯一识别口，禁第二份词表）；
    ②接受显式 `allowed_levels` 覆盖（用户把穿窗等级配窄/配宽时用，语义=**只看这张表**，
    不再查族级地板；空表⇒一切都不许穿窗＝配窄了只能更安静）。

    `allowed_levels=None` ⇒ 走族级地板（现网缺省）。装配侧的源级表**不走本函数的
    显式腿**（那会架空族级地板），而是经
    `may_breach_quiet_window_intersects_floor(source_levels=…)` 取交；本函数的
    「只看这张表」语义保留给显式要求表意分离的调用侧与既有锁件。
    未定级一律 False（D-1：不猜）。
    """
    if level is None:
        return False
    if allowed_levels is not None:
        wanted = {str(raw).strip().upper() for raw in allowed_levels if str(raw).strip()}
        return level.value in wanted
    return _taxonomy.may_breach_quiet_window(_taxonomy.category_of_item(item), level)


def may_breach_quiet_window_intersects_floor(
    item: EmergencyItem,
    level: EmergencyLevel | None,
    *,
    source_levels: Sequence[str] | None = None,
) -> bool:
    """「源级表 ∩ 族级地板」合成判据（S-FIX-QUIET-T3，主代理裁定语义）。

    某族在静默窗内**可穿窗的等级集合** = 源级配置表 ∩ 该族族级地板
    （`alert_taxonomy.wake_levels`）。与 `may_breach_quiet_window(allowed_levels=…)`
    的「只看这张表」显式覆盖语义**不同**——那一直径会把族级地板架空
    （如 `global_disaster` 只认红档的族被 P1 穿窗＝静默窗行为变更），故装配侧
    的源级表一律走本合成分支：

    - `source_levels=None` ⇒ 直接返回族级地板结论（**逐字节等于现状**，缺省族级＝红/橙）；
    - 显式表（含空表）⇒ 先过族级地板、再要求在源级表内——源级表**只收窄、不放宽**；
      空表⇒一切不穿窗（配窄了只能更安静，与 D-8「门一寸不松」同向）；
    - 未定级一律 False（D-1：不猜）。

    归一化口径与 `may_breach_quiet_window` 的显式腿逐字相同（strip+upper、丢空串），
    不建第二份词表。
    """
    if level is None:
        return False
    if not _taxonomy.may_breach_quiet_window(_taxonomy.category_of_item(item), level):
        return False
    if source_levels is None:
        return True
    wanted = {str(raw).strip().upper() for raw in source_levels if str(raw).strip()}
    return level.value in wanted


__all__ = [
    "DEFAULT_GRADING_RULES",
    "EARTHQUAKE_DEEP_THRESHOLD_KM",
    "EARTHQUAKE_INFO_MAX_MAGNITUDE",
    "FALLBACK_LEVEL",
    "GradingRule",
    "color_levels_in_text",
    "earthquake_level",
    "grade",
    "grading_candidates",
    "is_china_inland",
    "matched_levels",
    # 包装（非第二实现）：穿安静时间窗的判据真身在 `alert_taxonomy`，
    # 本模块是规则层的对外名（`push.py` 与测试都按 `grading.*` 取用）。
    "may_breach_quiet_window",
    # 装配侧唯一合法入口（源级表只收窄、族级地板恒在场）。
    "may_breach_quiet_window_intersects_floor",
]
