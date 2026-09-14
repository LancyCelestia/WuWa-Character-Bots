"""动态好感度与印象标签（批次 C 核心）。

静态档案（relationship.py 的 JSON）之外的行为驱动层：
- 每条消息按内容与安全评估归类行为：positive/neutral/tease/negative/insult；
- 行为驱动 affinity 增减（clamp [-1,1]），并累计印象标签；
- SQLite 持久化；与静态档案融合规则：档案有 affinity 用档案，否则用动态层。

数值规范唯一权威描述见 docs/affinity-design.md（v4 线性版，2026-09-12）：
内部值域 [-1,+1]、展示口径 ×100（-100~+100）、基准 0.1（展示 10）、
线性步长（v3 幂律阻尼废除）、闲置惰性回归与印象淡出、8 档态度表（档 id -4..+3）。
所有数值常量集中在文件顶部，注释指向该文档对应章节。
"""

from __future__ import annotations

import calendar
import hashlib
import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

# 正向：否定前缀（不/没/别）紧邻时不算——「我不喜欢你这样说」不得加分。
_POSITIVE_RE = re.compile(
    r"(谢谢|感谢|辛苦了|太棒了|厉害|好棒|(?<![不没别])喜欢你|陪你|陪我|抱抱|晚安|早安)",
    re.IGNORECASE,
)
# 负向（抱怨）：不收裸「傻/蠢/没用/无聊」单字（成语/叠词/求陪伴误捕，见 docs §2 注）。
_NEGATIVE_RE = re.compile(r"(烦死了|别烦我|真差劲|太差劲|真没用)", re.IGNORECASE)
# 辱骂级（与安全硬类别同档，扣分更重）：先于抱怨判定。
_INSULT_RE = re.compile(
    r"(傻瓜|傻逼|蠢货|蠢蛋|闭嘴|(?:^|[^\瓜烂])滚(?![烂瓜烫])"
    r"|(?:真|好|太|那么|超)[蠢傻](?!萌))",
    re.IGNORECASE,
)

# 印象标签：行为累计达标即打标，注入 prompt 供人格参考（不外显为标签词）。
_IMPRESSION_RULES: tuple[tuple[str, int, str], ...] = (
    ("positive", 3, "友善"),
    ("positive", 10, "老朋友"),
    ("negative", 3, "爱抱怨"),
    ("insult", 2, "口无遮拦"),
    ("tease", 3, "爱戏弄"),
)
_TEASE_RE = re.compile(r"(哈哈|笑死|逗你|骗你的|捉弄|整蛊)", re.IGNORECASE)

# ---- 小名自学（被动感知用，__init__ 每消息调用）----
# 触发词前的紧邻否定由 lookbehind 挡（「别叫我/不要喊我/千万别叫我」）；
# 「谁叫我」「别、叫我」这类隔着疑问词或顿号的否定 lookbehind 够不着，
# 由命中点前 6 字的否定语境复核兜住。谁分支不允许顿号隔断（「那个谁，以后叫我」仍算教名）。
_NICKNAME_LEARN_RE = re.compile(
    r"(?<!别)(?<!不要)(?<!不许)(?<!不准)"
    r"(?:你可以叫我|以后叫我|就叫我|叫我|喊我)\s*([\u4e00-\u9fa5A-Za-z0-9]{1,12}?)"
    r"(?:吧|就好|就可以了|就行|哦|呀|~|！|!|。|\s|$)"
)
_NICKNAME_NEGATION_CONTEXT_RE = re.compile(
    r"(?:(?:千万别|不要|不许|不准|千万|别)[、，,~～\s]*|谁\s*)"
    r"[^、，,。.!！?？~～\s]{0,2}$"
)
# 后缀语气词回溯成名字的防御：「叫我就好」会捕获「就好」，全数拒绝。
_NICKNAME_SUFFIX_PARTICLES = frozenset({"吧", "就好", "就可以了", "就行", "哦", "呀"})


def extract_learned_nickname(text: str) -> str | None:
    """提取用户主动授予的小名；否定语境（「别/不要/谁…叫我X」）返回 None。

    捕获为非贪婪：语气词（吧/哦/呀）走后缀分支，不粘进名字；
    「叫我就好/叫我就行」这类无名字的收尾话术，回溯会把语气词当名字，同样拒绝。
    """
    match = _NICKNAME_LEARN_RE.search(text)
    if not match:
        return None
    prefix = text[max(0, match.start() - 6) : match.start()]
    if _NICKNAME_NEGATION_CONTEXT_RE.search(prefix):
        return None
    learned = match.group(1).strip()
    if not learned or learned in _NICKNAME_SUFFIX_PARTICLES:
        return None
    return learned

# ---- 角色爱称映射（审查 O-07，2026-09-14）：只理解、不学舌 ----
# 玩家之间通行的「角色爱称」（社区共识外号），供理解层把用户消息里的爱称
# 对应回角色名（如「我抽了个龙哥」→ 忌炎）。边界：bot **绝不**主动用爱称
# 称呼用户或角色——那是人格语气域，禁入。
# 条目纪律（与 glossary 种子同规）：只收社区共识且无争议、来源可查证的
# 条目（萌娘百科「鸣潮/用语与梗」共鸣者称呼表，2026-09 核对；忌炎=龙哥
# 另有 B站/萌娘百科角色词条互证）；不确定/易变的宁缺毋滥（如散华=三花
# 这类未见于权威梗表的谐音写法不收）；「老公/老婆」类泛称依玩家各自
# 抽卡结果而定，无法静态唯一对应角色，一律不收。
_CHARACTER_AFFECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "忌炎": ("龙哥",),            # 青龙大招+夜归军将军身份，社区通行
    "安可": ("羊咩",),            # 身旁绵羊玩偶黑咩/白咩
    "鉴心": ("小道士",),
    "凌阳": ("芝士雪豹",),        # 雪豹叫声病毒梗的社区移植
    "今汐": ("小汐子",),
    "长离": ("离妃",),
    "吟霖": ("女特务",),          # 治安署巡尉→间谍身份的社区称呼
    "椿": ("大傻椿",),            # 「大傻春你要干什么」谐音+线下布偶装呆萌名场面
    "丹瑾": ("小西王",),
    "卡提希娅": ("小卡", "大卡"),  # 大卡=芙露德莉斯同体状态
    "坎特蕾拉": ("水母姐", "家主大人"),
    "布兰特": ("船长",),
    "露帕": ("小狼",),
}
# 爱称→角色 反查索引（导入期一次性构建；键全局唯一性由测试锁死防静默覆盖）。
_AFFECTION_ALIAS_INDEX: dict[str, str] = {
    alias: character
    for character, aliases in _CHARACTER_AFFECTION_ALIASES.items()
    for alias in aliases
}


def resolve_affection_alias(word: str) -> str | None:
    """角色爱称反查：社区爱称 → 角色名；非爱称返回 None。

    用途边界（审查 O-07）：只做「理解」——供上下文接线把用户消息里的爱称
    对应回角色名；不做「学舌」——返回值只作理解辅助，禁止进生成侧话术。
    **上下文接线待批**：理解层消费挂点（chat 上下文注入/摄取层）不在本次
    改动域内，本函数先以纯查询形态交付；后续接线须保持与
    extract_learned_nickname 零互抢——「叫我X」是本人称谓学习，其语义
    优先，爱称解析只服务第三人称/抽卡语境的角色指代。
    """
    normalized = (word or "").strip()
    if not normalized:
        return None
    return _AFFECTION_ALIAS_INDEX.get(normalized)

# ---- 数值化常量（规范唯一权威：docs/affinity-design.md）----
_AFFINITY_BASE = 0.1            # §1 基准 0.1（展示 10 = ×100）：初始好感=回归收敛目标
AFFINITY_BASE = _AFFINITY_BASE  # 公开只读别名（providers 等模块判断“非默认记录”用）
_DAY_SECONDS = 86400
# §2 因子表：步长全程线性（v3 幂律阻尼废除）。v5（用户裁定 2026-09-12 实弹反馈④）：
# 固定「一次加几减几」口径废除，实际步长 = 基准因子 × 多因素连续调制——
#   f1 说话温度（文本里善意/恶意词的密度，同一行为内部再分级）
#   f2 相处时长（认识越久信任越稳，正向变化略增；对新面孔保守）
#   f3 第一印象（由最初几次互动的善恶构成定一次，±30%；随长期相处权重衰减趋 1，
#      ——只影响速度、永不影响态度档位，任何用户都不会被区别对待）
#   f4 当天基础状态（bot 心情 valence 派生，由调用方注入）
#   m  个人节奏（uid 确定性派生，±15%，非歧视：只是每个人的「相处节奏」不同）
_BEHAVIOR_DELTA = {"positive": 0.02, "neutral": 0.0, "tease": -0.01, "negative": -0.05, "insult": -0.10}
# §2 每日有效次数上限（UTC 自然日）：同行为超出后 delta 记 0，计数器与标签照常累计。
_DAILY_EFFECTIVE_CAPS: dict[str, int] = {"positive": 10, "tease": 5, "negative": 8, "insult": 8}
# §2 v5 多因素调制幅度（全部 clamp 在界内，合成步长永不过猛）。
_POLITE_RE = re.compile(r"(请|麻烦|辛苦|劳驾|有劳|费心)", re.IGNORECASE)
_HARSH_RE = re.compile(r"(滚|闭嘴|废物|恶心|烦|傻|蠢|别来)", re.IGNORECASE)
# f2 相处时长：认识 1 年 → 满增 15%（log 缓增，前期敏感后期平缓）。
_COMPANION_MAX_BONUS = 0.15
_COMPANION_SATURATION_DAYS = 365.0
# f3 第一印象：最初 3 次有效互动定盘，±30% 调制；interaction_count 每翻倍，
# 偏差权重 ×0.5（约 80 次互动后基本归零）——长期相处抹平第一眼。
_FIRST_IMPRESSION_WINDOW = 3
_FIRST_IMPRESSION_MAX_SHIFT = 0.30
_FIRST_IMPRESSION_DECAY_BASE = 80.0
# f4 当天基础状态：bot 心情 valence ∈ [-1,1] → ±15%（调用方注入，缺省 1.0）。
_STATE_MAX_SHIFT = 0.15
# §3 惰性回归（时间减退）：写路径检查闲置天数，≥7 天起每天向基准 0.1（10 分）
# 回归 0.01，不超过剩余距离；时间源走注入 clock；updated_at 解析失败视为同日不衰减。
_IDLE_REGRESSION_START_DAYS = 7
_IDLE_REGRESSION_PER_DAY = 0.01
# §3 印象淡出（记忆减弱）半衰期（天）：辱骂 15、其余负面/正面 30；全部淡出回基准 10。
_SENTIMENT_HALF_LIFE_DAYS = {"positive": 30.0, "negative": 30.0, "insult": 15.0}
# G-11 印象标签年龄淡出（审查 G-11，2026-09-15）：标签此前一次性打标永久保留、
# 无淡出，数月前的陈旧标签会永久污染画像。修法对齐 §3 半衰惯例——沿用半衰期
# 常量 ×2 作为标签注入有效龄（半衰一次记忆减半，两次后视为「印象已淡」）：
# 口无遮拦（insult）30 天，其余（正面/抱怨/戏弄）60 天；tease 无独立半衰档，
# 归入「其余负面」口径。超龄标签不再注入（snapshot() 出口过滤），但保留在库
# 可溯、不物理删；标签时间戳 = 最近一次同类行为时间（observe 滚动刷新），
# 持续被同类行为强化的印象不超龄，长期不复现的印象自然淡出。
# 数值规范零触碰（docs/affinity-design.md 为唯一权威）：本段只新增「标签注入
# 判据」，不改任何好感度数值/步长/回归/半衰常量。
_TAG_EXPIRY_HALF_LIVES = 2.0
_TAG_EXPIRY_DAYS: dict[str, float] = {
    tag: _SENTIMENT_HALF_LIFE_DAYS.get(watch, _SENTIMENT_HALF_LIFE_DAYS["negative"])
    * _TAG_EXPIRY_HALF_LIVES
    for watch, _threshold, tag in _IMPRESSION_RULES
}
# 规则表之外的未知标签（防御）：按「其余负面」档淡出，宁可淡出不永久滞留。
_DEFAULT_TAG_EXPIRY_DAYS = _SENTIMENT_HALF_LIFE_DAYS["negative"] * _TAG_EXPIRY_HALF_LIVES
# 榜卡展示折算：闲置分数向基数衰减的半衰期（天），只影响展示，不落库。
_LEADERBOARD_DECAY_HALF_LIFE_DAYS = 30.0


def per_user_factor(sender_id: str) -> float:
    """因人而异的确定性节奏系数（±15%）：同一 sender 恒定，跨重启不变。

    非歧视声明（用户裁定）：这只让每个人的相处节奏略有差异（如同现实里
    每段关系都有自己的步调），态度档位、红线、回应方式对所有用户完全一致。
    """
    if not sender_id:
        return 1.0
    digest = hashlib.sha1(str(sender_id).encode("utf-8")).hexdigest()
    return 0.85 + 0.3 * (int(digest[:8], 16) % 1000) / 999


def pleasantness_factor(text: str, behavior: str) -> float:
    """f1 说话温度（≥0.7, ≤1.5）：同一行为内部按用词密度再分级。

    「谢谢！麻烦你啦，真是太棒了」比单个「谢了」更暖；
    连串恶言比一句抱怨更伤。中性话不调制。
    """
    value = text or ""
    if behavior == "positive":
        warm = len(_POSITIVE_RE.findall(value))
        polite = len(_POLITE_RE.findall(value))
        return max(0.7, min(1.4, 1.0 + 0.12 * max(0, warm - 1) + 0.06 * polite))
    if behavior in {"negative", "insult"}:
        harsh = len(_NEGATIVE_RE.findall(value)) + len(_INSULT_RE.findall(value))
        return max(0.7, min(1.5, 1.0 + 0.15 * max(0, harsh - 1)))
    if behavior == "tease":
        return 0.9
    return 1.0


def companionship_factor(days: float) -> float:
    """f2 相处时长（1.0~1.15）：认识越久，正向积累越稳；当日/新面孔 = 1.0。

    只放大不缩小（负面行为不吃时长红利——老朋友骂人同样伤人）。
    """
    if days <= 0:
        return 1.0
    ratio = min(1.0, days / _COMPANION_SATURATION_DAYS)
    return 1.0 + _COMPANION_MAX_BONUS * ratio


def first_impression_factor(
    first_impression: float | None, interaction_count: int
) -> float:
    """f3 第一印象（0.7~1.3 → 随相处趋 1.0）：最初互动的善恶定一次盘。

    first_impression ∈ [-1, +1]（None=信号不足，不调制）。好印象：好话
    来得更快；差印象：需要更多努力。偏差随互动次数指数衰减——相处本身
    会抹平第一眼，任何人都有长期等价的机会（反歧视护栏）。
    """
    if first_impression is None:
        return 1.0
    decay = 0.5 ** (max(0, interaction_count) / _FIRST_IMPRESSION_DECAY_BASE)
    shift = _FIRST_IMPRESSION_MAX_SHIFT * max(-1.0, min(1.0, first_impression)) * decay
    return 1.0 + shift


def state_factor_from_valence(valence: float) -> float:
    """f4 当天基础状态（0.85~1.15）：bot 心情 valence ∈ [-1,1] 线性映射。"""
    return 1.0 + _STATE_MAX_SHIFT * max(-1.0, min(1.0, float(valence)))


def effective_delta(
    sender_id: str,
    behavior: str,
    affinity: float,
    *,
    delta_override: float | None = None,
    text: str = "",
    first_impression: float | None = None,
    interaction_count: int = 0,
    companion_days: float = 0.0,
    mood_valence: float | None = None,
) -> float:
    """一次行为在当前状态下的综合步长（docs §2 v5：多因素线性调制）。

    实际步长 = 基准因子表 × f1 说话温度 × f2 相处时长 × f3 第一印象
    × f4 当日状态 × m(uid)，全程无阻尼、无固定「加几减几」口径；
    override 为权威信号直用（其余因子不参与，仅 clamp）。
    """
    if delta_override is not None:
        return float(delta_override)
    base = _BEHAVIOR_DELTA.get(behavior, 0.0)
    if base == 0.0:
        return 0.0
    state = (
        1.0 if mood_valence is None else state_factor_from_valence(mood_valence)
    )
    factor = (
        pleasantness_factor(text, behavior)
        * companionship_factor(companion_days)
        * first_impression_factor(first_impression, interaction_count)
        * state
        * per_user_factor(sender_id)
    )
    # 负向行为不吃 f2 时长红利（f2 ≥ 1 恒放大）——对负面取倒数会加重惩罚，
    # 与"相处时间不该加倍惩罚老朋友"的本意相悖，这里对 negative/insult 只保留 f2=1。
    if base < 0:
        factor = factor / companionship_factor(companion_days)
    return base * factor

# ---- §4 档位表：线性 8 档，每档宽 25，档0=友善含基准 10；边界左闭右开（最高档含 +100）。
# 展示区间 = internal × 100；档 id -4..+3（v3 曾返回具名 id close/friendly/polite/distant，
# v4 改为整数档 id——向后兼容点，调用方以 providers.py 的 familiarity 映射为准）。
_ATTITUDE_TIERS: tuple[tuple[int, str, str], ...] = (
    (-4, "初识", "初见不久的人：礼貌、克制、有问必答但不寒暄"),
    (-3, "生疏", "生疏的人：话少一截，依旧体面温和"),
    (-2, "微凉", "语气稍淡，不冷不热，就事论事"),
    (-1, "稍淡", "略淡于平时，但保持基本温柔"),
    (0, "友善（基准）", "温和、有陪伴感，记得对方的偏好"),
    (1, "亲近", "更主动的关心，记得对方说过的事"),
    (2, "挚友", "直接而温暖，可以用给对方起的小名"),
    (3, "独一份", "最珍视的人：全然温柔的陪伴"),
)
# §4 态度红线：每一档共同遵守，写死进注入文本（attitude_for_affinity 全文携带）。
_TIER_RED_LINES: tuple[str, ...] = (
    (
        "任何档位都不强硬、不粗鲁、不攻击、不辱骂、不贬低、不谴责；"
        "被冒犯时只温和表明边界（类似“这句靠得太近了，我们先到这好吗”的量级，"
        "不指责、不让对方愧疚），绝不坚决抵抗或反击"
    ),
    "负向档位只是“距离感”：不表现出任何敌意；最低档也是“礼貌的初见”，不是敌视",
    "最高档也不越界：亲近不等于亲密关系升级，绝不出现性、R-18、引导上床类内容",
    "任何档位都不辱骂、不冷暴力弃聊",
)
_TIER_BY_ID: dict[int, tuple[str, str]] = {tier_id: (name, instruction) for tier_id, name, instruction in _ATTITUDE_TIERS}


def tier_for_affinity(affinity: float) -> int:
    """§4 档 id（-4..+3）：展示分 floor(display/25) 后 clamp，边界左闭右开、最高档含 +100。

    向后兼容标注：v3 返回具名 id（close/friendly/polite/distant），v4 起为整数档 id。
    """
    display = float(affinity) * 100.0
    return max(-4, min(3, int(display // 25)))


_LINEAR_TRANSITION_BAND_DISPLAY = 6.0  # 展示分距档界 ±6 分内视为线性过渡带


def linear_transition_for_affinity(affinity: float) -> str:
    """v4.1 线性态度（用户裁定：不得在档位门槛上生硬跳变）。

    距档位边界 ±6 展示分内时，返回一句"正处在向邻档自然过渡"的措辞，
    由 providers 拼进态度注入，使门槛两侧语气衔接为连续渐变；
    区间中部返回空串。极值档没有更外侧的邻档，返回空串。
    """
    display = max(-100.0, min(100.0, float(affinity) * 100.0))
    tier = tier_for_affinity(affinity)
    lo = -100.0 + 25.0 * (tier + 4)
    hi = lo + 25.0
    cur = _TIER_BY_ID[tier][0]
    if display - lo <= _LINEAR_TRANSITION_BAND_DISPLAY and tier - 1 >= -4:
        prev_name = _TIER_BY_ID[tier - 1][0]
        return f"（此刻你们之间的氛围，正处在从「{prev_name}」流向「{cur}」的自然过渡里，语气顺势而为即可）"
    if hi - display <= _LINEAR_TRANSITION_BAND_DISPLAY and tier + 1 <= 3:
        next_name = _TIER_BY_ID[tier + 1][0]
        return f"（此刻你们之间的氛围，正处在从「{cur}」流向「{next_name}」的自然过渡里，语气顺势而为即可）"
    return ""


def tier_name_for_affinity(affinity: float) -> str:
    """§4 档位名称（初识/生疏/微凉/稍淡/友善/亲近/挚友/独一份），展示层共用。"""
    return _TIER_BY_ID[tier_for_affinity(affinity)][0]


def attitude_for_affinity(affinity: float) -> str:
    """§4 完整态度文本：档位基调 + 四条态度红线（每档共同遵守，注入 prompt 全文）。"""
    name, instruction = _TIER_BY_ID[tier_for_affinity(affinity)]
    red_lines = "；".join(
        f"（{index}）{line}" for index, line in enumerate(_TIER_RED_LINES, start=1)
    )
    return f"对当前用户的态度（档位「{name}」）：{instruction}。共同态度红线：{red_lines}。"


def classify_behavior(text: str, *, safety_category: str = "", safety_action: str = "allow") -> str:
    if safety_category in {"harassment", "insult_nickname", "persona_degradation"} or safety_action == "refuse":
        # §2 insult 行含人格贬低类（docs §6）：persona_degradation 照走 insult 扣分路径。
        return "insult"
    if safety_category in {"excessive_intimacy", "persona_breaking"}:
        return "tease"
    value = text or ""
    if _POSITIVE_RE.search(value):
        return "positive"
    if _TEASE_RE.search(value):
        return "tease"
    if _INSULT_RE.search(value):
        return "insult"
    if _NEGATIVE_RE.search(value):
        return "negative"
    return "neutral"


def _format_utc(timestamp: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(timestamp))


def _parse_utc(text: str | None) -> float | None:
    if not text:
        return None
    try:
        return float(calendar.timegm(time.strptime(text, "%Y-%m-%dT%H:%M:%SZ")))
    except (ValueError, TypeError):
        return None


def _filter_fresh_impression_tags(
    tags: list[Any],
    tag_times: dict[Any, Any],
    *,
    now: float,
    anchor: float | None,
) -> list[str]:
    """G-11：过滤超龄印象标签——超龄者不再注入，库内保留可溯（不物理删）。

    标签年龄锚点：``tag_times`` 显式打标时间优先；存量行缺失条目时回退行级
    ``updated_at``（最后互动时间）——活跃用户的既有标签不因迁移误伤，长期
    沉寂行的陈旧标签按最后互动龄淡出。两个锚点都缺失/解析失败时视同当日
    （不超龄），与 §3 惰性回归「updated_at 解析失败视为同日不衰减」的容错
    口径一致。
    """
    fresh: list[str] = []
    for raw in tags:
        tag = str(raw)
        explicit = _parse_utc(str(tag_times.get(tag) or ""))
        earned_at = explicit if explicit is not None else anchor
        if earned_at is None:
            fresh.append(tag)
            continue
        age_days = max(0.0, now - earned_at) / _DAY_SECONDS
        if age_days <= _TAG_EXPIRY_DAYS.get(tag, _DEFAULT_TAG_EXPIRY_DAYS):
            fresh.append(tag)
    return fresh


_PROFILE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"我(?:来自|是|住在)(?:[^，。！!\s]{2,12})"),
    re.compile(r"我今年\s*\d{1,3}\s*岁"),
    re.compile(r"我(?:最近|这几天)(?:在|正在)(?:[^，。！!\s]{2,20})"),
    re.compile(r"我(?:喜欢|爱|擅长|在玩|在追)(?:[^，。！!\s]{2,20})"),
)


def extract_profile_facts(text: str) -> list[str]:
    """从用户自述中提取画像事实（身份/来自/年龄/近况/爱好），去重封顶。"""
    value = (text or "").strip()
    if not value:
        return []
    facts: list[str] = []
    for pattern in _PROFILE_PATTERNS:
        for match in pattern.finditer(value):
            fact = match.group(0).strip()
            if fact and fact not in facts:
                facts.append(fact)
    return facts[:4]


class DynamicAffinityStore:
    """SQLite 动态好感度与印象标签；线程安全。"""

    def __init__(self, db_path: str | Path, *, clock: Any = time.time) -> None:
        self.db_path = Path(db_path)
        self._clock = clock
        self._lock = threading.Lock()
        # 进程内复用单一连接：每条聊天消息 observe/snapshot 各一次，SQLite
        # 连接建立偏贵；全部操作已在 self._lock 下串行，check_same_thread=False
        # 允许事件循环与 offload 线程池跨线程共用同一连接。
        self._connection: sqlite3.Connection | None = None
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_affinity (
                    sender_id TEXT PRIMARY KEY,
                    affinity REAL NOT NULL DEFAULT 0.1,
                    interaction_count INTEGER NOT NULL DEFAULT 0,
                    positive_count INTEGER NOT NULL DEFAULT 0,
                    negative_count INTEGER NOT NULL DEFAULT 0,
                    tease_count INTEGER NOT NULL DEFAULT 0,
                    insult_count INTEGER NOT NULL DEFAULT 0,
                    nickname TEXT NOT NULL DEFAULT '',
                    impression_tags TEXT NOT NULL DEFAULT '[]',
                    impression_tag_times TEXT NOT NULL DEFAULT '{}',
                    profile_notes TEXT NOT NULL DEFAULT '[]',
                    counter_day_index INTEGER NOT NULL DEFAULT -1,
                    day_counters TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(user_affinity)").fetchall()
            }
            # 存量库只加列迁移（沿用 profile_notes 先例）。
            for column, ddl in (
                ("profile_notes", "TEXT NOT NULL DEFAULT '[]'"),
                ("counter_day_index", "INTEGER NOT NULL DEFAULT -1"),
                ("day_counters", "TEXT NOT NULL DEFAULT '{}'"),
                ("last_positive_at", "TEXT"),
                ("last_negative_at", "TEXT"),
                ("last_insult_at", "TEXT"),
                # v5 多因素：第一印象（建档窗口内收集的善恶信号 + 定盘值）与认识时间。
                ("first_signals", "TEXT NOT NULL DEFAULT '[]'"),
                ("first_impression", "REAL"),
                ("created_at", "TEXT"),
                # G-11 印象标签年龄淡出：标签名→最近打标时间（ISO8601 JSON 对象）。
                # impression_tags 本体保持纯标签名列表不变（库内全量保留可溯）；
                # 存量行缺时间戳条目时快照侧回退行级 updated_at 锚点，无需数据迁移。
                ("impression_tag_times", "TEXT NOT NULL DEFAULT '{}'"),
            ):
                if column not in columns:
                    connection.execute(f"ALTER TABLE user_affinity ADD COLUMN {column} {ddl}")
            # WAL：被动感知与查询卡渲染多线程并发读写，降低事件循环阻塞窗口。
            connection.execute("PRAGMA journal_mode=WAL")
            # 群镜像表（好感榜）：主表仍每用户一行；镜像行由 observe 同事务写，
            # 数值与主行恒等（docs/affinity-design.md §9.3）。
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS group_affinity (
                    group_id TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    display_name TEXT NOT NULL DEFAULT '',
                    affinity REAL NOT NULL DEFAULT 0.1,
                    interaction_count INTEGER NOT NULL DEFAULT 0,
                    positive_count INTEGER NOT NULL DEFAULT 0,
                    negative_count INTEGER NOT NULL DEFAULT 0,
                    tease_count INTEGER NOT NULL DEFAULT 0,
                    insult_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (group_id, sender_id)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        if self._connection is None:
            connection = sqlite3.connect(
                self.db_path, timeout=5.0, check_same_thread=False
            )
            connection.row_factory = sqlite3.Row
            self._connection = connection
        return self._connection

    def observe(
        self,
        sender_id: str,
        behavior: str,
        *,
        delta_override: float | None = None,
        group_id: str | None = None,
        display_name: str | None = None,
        text: str = "",
        mood_valence: float | None = None,
    ) -> float:
        """记录一次行为并更新好感度；返回更新后的 affinity。

        v5：``text`` 供 f1 说话温度分级；``mood_valence`` 供 f4 当日状态
        （bot 心情模块注入，缺省不调制）。
        """
        if not sender_id:
            return _AFFINITY_BASE
        now = float(self._clock())
        now_text = _format_utc(now)
        # 每日计数按进程本地时区自然日（bot_timezone），对用户体感即「北京时间每日重置」。
        day_index = int(time.strftime("%Y%m%d", time.localtime(now)))
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT affinity, interaction_count, positive_count, negative_count, tease_count, insult_count,"
                " nickname, impression_tags, impression_tag_times, profile_notes,"
                " counter_day_index, day_counters, updated_at,"
                " last_positive_at, last_negative_at, last_insult_at,"
                " first_signals, first_impression, created_at"
                " FROM user_affinity WHERE sender_id = ?",
                (sender_id,),
            ).fetchone()
            if row is None:
                affinity = _AFFINITY_BASE
                counters = {"positive": 0, "negative": 0, "tease": 0, "insult": 0}
                tags: list[str] = []
                tag_times: dict[Any, Any] = {}
                nickname = ""
                notes: list[str] = []
                day_counters: dict[str, int] = {}
                interactions = 0
                last_seen: dict[str, str | None] = {"positive": None, "negative": None, "insult": None}
                first_signals: list[float] = []
                first_impression: float | None = None
                created_at = now_text
            else:
                affinity = float(row["affinity"])
                counters = {
                    "positive": int(row["positive_count"]),
                    "negative": int(row["negative_count"]),
                    "tease": int(row["tease_count"]),
                    "insult": int(row["insult_count"]),
                }
                tags = json.loads(str(row["impression_tags"] or "[]"))
                # G-11：标签打标时间（存量行可能缺条目，快照侧回退 updated_at 锚点）
                tag_times = json.loads(str(row["impression_tag_times"] or "{}"))
                nickname = str(row["nickname"] or "")
                notes = json.loads(str(row["profile_notes"] or "[]"))
                interactions = int(row["interaction_count"])
                last_seen = {
                    "positive": row["last_positive_at"],
                    "negative": row["last_negative_at"],
                    "insult": row["last_insult_at"],
                }
                first_signals = json.loads(str(row["first_signals"] or "[]"))
                first_impression = (
                    float(row["first_impression"])
                    if row["first_impression"] is not None
                    else None
                )
                created_at = str(row["created_at"] or row["updated_at"] or now_text)
                # 每日计数仅当日有效；跨日自动清零（row_day != day_index 视为新的一天）。
                row_day = int(row["counter_day_index"] if row["counter_day_index"] is not None else -1)
                day_counters = (
                    json.loads(str(row["day_counters"] or "{}")) if row_day == day_index else {}
                )
            # 惰性回归：闲置 ≥7 天起每天向基数 0.1（10 分）回归 0.01，不超过剩余距离。
            if row is not None:
                prev = _parse_utc(str(row["updated_at"]))
                if prev is not None:
                    idle_days = int(max(0.0, now - prev) // _DAY_SECONDS)
                    if idle_days >= _IDLE_REGRESSION_START_DAYS:
                        gap = _AFFINITY_BASE - affinity
                        shift = min(idle_days * _IDLE_REGRESSION_PER_DAY, abs(gap))
                        affinity += shift if gap > 0 else -shift
            # delta：每日上限内全额、超限记 0；override 视为权威信号直用且不占每日额度。
            # §2 v5：实际步长 = 基准因子 × f1 说话温度 × f2 相处时长 × f3 第一印象
            # × f4 当日状态 × m(uid)，多因素连续调制，无固定加减数值。
            companion_days = max(0.0, now - (_parse_utc(created_at) or now)) / _DAY_SECONDS
            if delta_override is not None:
                delta = float(delta_override)
            else:
                cap = _DAILY_EFFECTIVE_CAPS.get(behavior)
                used = int(day_counters.get(behavior, 0))
                if cap is not None and used >= cap:
                    delta = 0.0
                else:
                    delta = effective_delta(
                        sender_id,
                        behavior,
                        affinity,
                        text=text,
                        first_impression=first_impression,
                        interaction_count=interactions,
                        companion_days=companion_days,
                        mood_valence=mood_valence,
                    )
                day_counters[behavior] = used + 1
            # §1 v4：写入路径全部 clamp 到 [-1, +1]（存量 [0,1] 旧值恒等沿用，无迁移）。
            affinity = max(-1.0, min(1.0, affinity + delta))
            if behavior in counters:
                counters[behavior] += 1
            if behavior in last_seen:
                last_seen[behavior] = now_text
            # v5 第一印象：建档窗口内累积善恶信号，攒够一次定盘（此后不再改动）。
            if first_impression is None:
                first_signals.append(
                    {"positive": 1.0, "neutral": 0.0, "tease": -0.25, "negative": -0.75, "insult": -1.0}.get(
                        behavior, 0.0
                    )
                )
                if len(first_signals) >= _FIRST_IMPRESSION_WINDOW:
                    first_impression = max(
                        -1.0, min(1.0, sum(first_signals) / len(first_signals))
                    )
            for watch, threshold, tag in _IMPRESSION_RULES:
                if watch in counters and counters[watch] >= threshold and tag not in tags:
                    tags.append(tag)
                # G-11 滚动强化打标：现行为命中该标签类别且计数达标时刷新打标
                # 时间——标签年龄 = 最近一次同类行为时间，持续强化的印象不超龄，
                # 不再复现的印象按 §3 半衰口径 ×2 超龄淡出（snapshot 出口过滤，
                # 库内保留可溯）。中性消息不得给其它标签续命（behavior 精确匹配）。
                # 数值规范零触碰：只加时间戳判据，不改计数/阈值/步长。
                if behavior == watch and watch in counters and counters[watch] >= threshold:
                    tag_times[tag] = now_text
            connection.execute(
                """
                INSERT OR REPLACE INTO user_affinity
                    (sender_id, affinity, interaction_count, positive_count, negative_count,
                     tease_count, insult_count, nickname, impression_tags, impression_tag_times,
                     profile_notes, counter_day_index, day_counters, updated_at,
                     last_positive_at, last_negative_at, last_insult_at,
                     first_signals, first_impression, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sender_id,
                    affinity,
                    interactions + 1,
                    counters["positive"],
                    counters["negative"],
                    counters["tease"],
                    counters["insult"],
                    nickname,
                    json.dumps(tags, ensure_ascii=False),
                    json.dumps(tag_times, ensure_ascii=False),
                    json.dumps(notes, ensure_ascii=False),
                    day_index,
                    json.dumps(day_counters, ensure_ascii=False),
                    now_text,
                    last_seen["positive"],
                    last_seen["negative"],
                    last_seen["insult"],
                    json.dumps(first_signals if first_impression is None else [], ensure_ascii=False),
                    first_impression,
                    created_at,
                ),
            )
            # 群镜像：带 group_id 时写该群；不带时同步该用户已镜像的全部群，
            # 保证镜像行与主行数值恒等（排行榜因此无需再查主表）。
            mirror_targets = [group_id] if group_id else [
                str(row[0])
                for row in connection.execute(
                    "SELECT group_id FROM group_affinity WHERE sender_id = ?", (sender_id,)
                ).fetchall()
            ]
            for target_group in mirror_targets:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO group_affinity
                        (group_id, sender_id, display_name, affinity, interaction_count,
                         positive_count, negative_count, tease_count, insult_count, updated_at)
                    VALUES (?, ?, COALESCE(NULLIF(?, ''), (
                               SELECT display_name FROM group_affinity
                               WHERE group_id = ? AND sender_id = ?)), ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        target_group,
                        sender_id,
                        (display_name or "").strip()[:32],
                        target_group,
                        sender_id,
                        affinity,
                        interactions + 1,
                        counters["positive"],
                        counters["negative"],
                        counters["tease"],
                        counters["insult"],
                        now_text,
                    ),
                )
            return affinity

    def leaderboard(self, group_id: str, *, limit: int = 60) -> list[dict[str, Any]]:
        """群好感榜：按印象好感度降序（互动次数、sender_id 兜底），score=0-100。

        闲置行做展示层折算（按半衰期向基数衰减，不落库）——半年不说话的
        人不再顶着历史高分挂在榜上；真实值以 snapshot 为准。
        """
        if not group_id:
            return []
        now = float(self._clock())
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT sender_id, display_name, affinity, interaction_count, updated_at FROM group_affinity"
                " WHERE group_id = ? ORDER BY affinity DESC, interaction_count DESC, sender_id ASC"
                " LIMIT ?",
                (group_id, max(1, int(limit))),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            affinity = float(row["affinity"])
            prev = _parse_utc(str(row["updated_at"]))
            idle_days = max(0.0, now - prev) / _DAY_SECONDS if prev is not None else 0.0
            # 展示层折算：闲置按半衰期向基数收敛（30 天减半），真实值不变、不落库。
            shown = _AFFINITY_BASE + (affinity - _AFFINITY_BASE) * 0.5 ** (
                idle_days / _LEADERBOARD_DECAY_HALF_LIFE_DAYS
            )
            result.append(
                {
                    "sender_id": str(row["sender_id"]),
                    "display_name": str(row["display_name"] or ""),
                    "affinity": affinity,
                    "score": round(shown * 100.0, 1),
                    "tier": tier_for_affinity(affinity),
                }
            )
        return result

    def sentiment_for(self, sender_id: str) -> float:
        """用户对机器人的表达倾向（加权正向占比 0-1；零信号默认 0.1，与初始好感一致）。

        positive / (positive + negative + 2×insult)，各计数按差异化半衰期指数
        衰减（辱骂 15 天、其余 30 天——宽恕快、忘善意慢）；全部淡出回到默认。
        从说出口的话估算的表达比例，不是对内心的测量（docs §9.1）。
        """
        if not sender_id:
            return 0.1
        now = float(self._clock())
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT positive_count, negative_count, insult_count,"
                " last_positive_at, last_negative_at, last_insult_at FROM user_affinity"
                " WHERE sender_id = ?",
                (sender_id,),
            ).fetchone()
        if row is None:
            return 0.1

        def _decayed(count: int, ts: str | None, half_life_days: float) -> float:
            age_days = 0.0
            parsed = _parse_utc(ts)
            if parsed is not None:
                age_days = max(0.0, now - parsed) / _DAY_SECONDS
            return max(0, count) * 0.5 ** (age_days / half_life_days)

        eff_positive = _decayed(
            int(row["positive_count"]), row["last_positive_at"],
            _SENTIMENT_HALF_LIFE_DAYS["positive"],
        )
        eff_negative = _decayed(
            int(row["negative_count"]), row["last_negative_at"],
            _SENTIMENT_HALF_LIFE_DAYS["negative"],
        )
        eff_insult = _decayed(
            int(row["insult_count"]), row["last_insult_at"],
            _SENTIMENT_HALF_LIFE_DAYS["insult"],
        )
        denom = eff_positive + eff_negative + 2 * eff_insult
        if denom < 0.1:
            return 0.1  # 历史信号全部淡出：回到默认
        return eff_positive / denom

    def snapshot(self, sender_id: str) -> dict[str, Any]:
        """读取好感度与印象；无记录返回中性默认。只读，不触发惰性回归。"""
        if not sender_id:
            return {
                "affinity": _AFFINITY_BASE,
                "tags": [],
                "nickname": "",
                "profile_notes": [],
                "tier": tier_for_affinity(_AFFINITY_BASE),
                "attitude": attitude_for_affinity(_AFFINITY_BASE),
            }
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT affinity, nickname, impression_tags, impression_tag_times, profile_notes, updated_at"
                " FROM user_affinity WHERE sender_id = ?",
                (sender_id,),
            ).fetchone()
        if row is None:
            return {
                "affinity": _AFFINITY_BASE,
                "tags": [],
                "nickname": "",
                "profile_notes": [],
                "tier": tier_for_affinity(_AFFINITY_BASE),
                "attitude": attitude_for_affinity(_AFFINITY_BASE),
            }
        affinity = float(row["affinity"])
        # G-11 注入判据（审查 G-11，2026-09-15）：超龄标签不再注入，库内保留可溯。
        # providers（prompt 注入）、好感度卡、指令回显等全部消费 snapshot()，
        # 过滤在本出口一次闭环；数值规范零触碰（docs/affinity-design.md 为权威）。
        fresh_tags = _filter_fresh_impression_tags(
            [str(t) for t in json.loads(str(row["impression_tags"] or "[]"))],
            json.loads(str(row["impression_tag_times"] or "{}")),
            now=float(self._clock()),
            anchor=_parse_utc(str(row["updated_at"])),
        )
        return {
            "affinity": affinity,
            "nickname": str(row["nickname"] or ""),
            "tags": fresh_tags,
            "profile_notes": json.loads(str(row["profile_notes"] or "[]")),
            "tier": tier_for_affinity(affinity),
            "attitude": attitude_for_affinity(affinity),
        }

    def factor_profile(self, sender_id: str) -> dict[str, Any]:
        """v5 因子画像（展示层定性描述用）：第一印象/互动次数/认识天数。"""
        empty = {"first_impression": None, "interaction_count": 0, "known_days": 0.0}
        if not sender_id:
            return empty
        now = float(self._clock())
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT first_impression, interaction_count, created_at, updated_at"
                " FROM user_affinity WHERE sender_id = ?",
                (sender_id,),
            ).fetchone()
        if row is None:
            return empty
        created = _parse_utc(str(row["created_at"] or row["updated_at"] or ""))
        known_days = max(0.0, now - created) / _DAY_SECONDS if created is not None else 0.0
        return {
            "first_impression": (
                float(row["first_impression"])
                if row["first_impression"] is not None
                else None
            ),
            "interaction_count": int(row["interaction_count"]),
            "known_days": round(known_days, 1),
        }

    def learn_profile(self, sender_id: str, text: str) -> list[str]:
        """从自述提取画像事实并合并入 profile_notes（去重，上限 12 条）。"""
        facts = extract_profile_facts(text)
        if not facts or not sender_id:
            return []
        now_text = _format_utc(float(self._clock()))
        merged: list[str] = []
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT profile_notes FROM user_affinity WHERE sender_id = ?",
                (sender_id,),
            ).fetchone()
            existing = json.loads(str(row["profile_notes"] or "[]")) if row else []
            merged = [str(f) for f in existing]
            for fact in facts:
                if fact not in merged:
                    merged.append(fact)
            merged = merged[-12:]
            connection.execute(
                "INSERT OR IGNORE INTO user_affinity (sender_id, affinity, updated_at) VALUES (?, 0.1, ?)",
                (sender_id, now_text),
            )
            connection.execute(
                "UPDATE user_affinity SET profile_notes = ?, updated_at = ? WHERE sender_id = ?",
                (json.dumps(merged, ensure_ascii=False), now_text, sender_id),
            )
        return facts

    def set_nickname(self, sender_id: str, nickname: str) -> None:
        """管理员/本人设置用户小名；写入后 prompt 可用小名称呼。"""
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO user_affinity (sender_id, affinity, updated_at) VALUES (?, 0.1, ?)",
                (sender_id, _format_utc(float(self._clock()))),
            )
            connection.execute(
                "UPDATE user_affinity SET nickname = ? WHERE sender_id = ?",
                (nickname.strip()[:32], sender_id),
            )
