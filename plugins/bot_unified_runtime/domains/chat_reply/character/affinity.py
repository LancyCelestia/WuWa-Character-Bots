"""动态好感度与印象标签（批次 C 核心）。

静态档案（relationship.py 的 JSON）之外的行为驱动层：
- 每条消息按内容与安全评估归类行为：positive/neutral/tease/negative/insult；
- 行为驱动 affinity 增减（clamp [-1,1]），并累计印象标签；
- SQLite 持久化；与静态档案融合规则：档案有 affinity 用档案，否则用动态层。

数值规范唯一权威描述见 docs/affinity-design.md（v4 线性版，2026-09-12；
v6 平滑层 2026-09-17 追加章节）：
内部值域 [-1,+1]、展示口径 ×100（-100~+100）、基准 0.1（展示 10）、
线性步长（v3 幂律阻尼废除）、闲置惰性回归与印象淡出、8 档态度表（档 id -4..+3）。
v6 平滑层（用户裁定「涨跌太快」）：饱和响应曲线（外档 smoothstep 收窄）+
同日同类信号边际递减（幂衰减带下限）+ 既有滚动预算即正负分开的日节奏帽。
v7 潜变量重写（用户裁定 2026-09-21「算法全部重写：一次加减太多、一下子就到顶、
不够人性化不够智能」，规格唯一权威 docs/design/affinity-v7-design.md）：内部表示
升级为无界潜变量 z ∈ ℝ，展示分 s = 100·tanh(z) —— 结构上永不触顶；计分单元从
「关键词命中次数」升级为五子信号质量分 q（主动度/延展度/情绪词/尊重边界/回应性）；
同类信号新鲜度 novelty 跨日按半衰回升（不再按自然日重置）；按人活跃度 rhythm 归一
（话痨不占便宜）；道歉/和解走独立修复通道（repair_gain，不吃新鲜度计数）；负向单
事件 |Δz| 上限 + 每人日位移上限 + 同类事件熔断三道护栏。存量分数经
z = atanh(clamp(score/100, ±bound)) 惰性映射，绝不重置任何人（表示变换，非重算）。
灰度开关 bot_affinity_v7_enabled 缺省 False ⇒ v5/v6 路径逐字节不变、可一键回退。
所有数值常量集中在文件顶部，注释指向文档对应章节。
"""

from __future__ import annotations

import calendar
import hashlib
import json
import math
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
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
# D3-6（v7 设计稿 §2.3 另修项）：旧「滚」支仅排 瓜/烂/烫 三字，「翻滚/滚动/
# 打滚/滚雪球」等鸣潮核心动作词与第一人称「我先滚了」全部假阳性。新三支结构：
# ①句读/串首锚定的裸「滚」（可带 快/赶紧/立刻/马上 前缀）——排除后缀加长
# （动/雪球/烫/锅/筒/珠/轮/落/瓜/烂）；②第二人称紧邻（你/您/恁 + ≤3 间隔字）；
# ③固定驱逐短语（给我滚/滚开/滚出去/滚远(点)/滚回去）。「都给我滚」照旧命中，
# 「滚瓜烂熟」「一个翻滚」「打滚」「滚雪球」「我先滚了」一律不命中（回归锁：
# tests/test_affinity_v7.py 变体族 + test_affinity.py:60/:69 存量锁）。
_INSULT_RE = re.compile(
    r"(傻瓜|傻逼|蠢货|蠢蛋|闭嘴"
    r"|(?:^|[\s，,。！!？?；;：:~～、])(?:快|赶紧|立刻|马上)?滚(?![动雪球烫锅筒珠轮落瓜烂])"
    r"|(?:你|您|恁)[^，。！？!?,.!?;；:：\s]{0,3}滚(?![动雪球烫锅筒珠轮落瓜烂])"
    r"|给我滚|滚(?:开|出去|远点?|回去)"
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
# policy_revision=v21.1 冲突迁移注记（规格 §2.3「旧设计冲突值迁为 policy_revision，
# 不两套并存」）：§2.3 score_signal 表值（positive_points=0.2 分、tease_points=0、
# negative/insult=-0.3/-1.0 分、confidence_min=0.9）是 V2 事件服务（AffinityEvent）
# 的校准起点；本席合同（§2 任务余量 3）裁定 v5 多因素算法语义原样保留，本表不动。
# 量级兜底：insult 基础 -0.10 内部值（-10 分申请）经单事件预算钳到 -1 分、
# 正向经 24h 增益 ≤3 分兜底，实际落点与 §2.3 起点同量级。
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

# ---- V2.1 滚动预算与因子钳制（规格：docs/design/backend-v2-product-extensions.md §2.3）----
# 预算常量一律以展示「分」定义；内部值 = 分 ÷ 100（§2.2：服务公开单位统一 points
# ∈ [-100,100]，内部 [-1,1] 为存量存储口径，唯一换算口在 observe_points/落库处）。
# 预算是纯时间窗滚动聚合（6h/24h），不用 day_index——重启、跨午夜均不重置。
_BUDGET_SINGLE_NEGATIVE_EVENT_POINTS = 1.0   # max_negative_per_event：单事件负向上限 1 分
_BUDGET_MAX_LOSS_6H_POINTS = 2.0             # max_loss_6h：6 小时滚动损失 ≤ 2 分
_BUDGET_MAX_LOSS_24H_POINTS = 4.0            # max_loss_24h：24 小时滚动损失 ≤ 4 分（必须 ≥ 6h 口径）
_BUDGET_MAX_GAIN_24H_POINTS = 3.0            # max_gain_24h：24 小时全局增益 ≤ 3 分
_BUDGET_LOG_RETENTION_SECONDS = 2 * _DAY_SECONDS  # delta 日志只服务窗口聚合，>48h 行写入时顺手 prune
# §2.3 interaction_cooldown_seconds=60（范围 10..3600）：去刷分、不阻止正常回复——
# 同 (principal_id, bot_id) 距上一次「实际计分事件」不足冷却秒数时，本次行为 delta=0
# （计数器/标签照常累计）；零增量事件（中性/预算耗尽记 0）不落日志、不触发冷却。
_INTERACTION_COOLDOWN_SECONDS = 60.0
# §2.3 passive_decay_enabled=false：缺席不默认扣分。旧 v5 §3 惰性回归（闲置 ≥7 天
# 每天向基准 0.1 回归 0.01）与此冲突——按规格「旧设计冲突值迁为 policy_revision，
# 不两套并存」，回归体保留、由本政策门开关，缺省关闭（policy_revision=v21.1）。
_PASSIVE_DECAY_ENABLED = False
# factor_product_min/max：多因素乘积钳制（候选变化 = 基础points × clamp(上下文因子乘积)）。
_FACTOR_PRODUCT_MIN = 0.5
_FACTOR_PRODUCT_MAX = 1.25


def ensure_budget_invariants(
    *,
    max_loss_6h_points: float = _BUDGET_MAX_LOSS_6H_POINTS,
    max_loss_24h_points: float = _BUDGET_MAX_LOSS_24H_POINTS,
) -> None:
    """规格 §2.3 预算窗不变量：6h 损失预算不得大于 24h（否则 6h 口径形同虚设）。

    常量为模块单一注册点；本函数供导入期自检与后续调参（config 化）时复用，
    违例直接 ValueError 拒绝启动，不带病运行。
    """
    if float(max_loss_6h_points) > float(max_loss_24h_points):
        raise ValueError(
            f"affinity budget invariant violated: max_loss_6h ({max_loss_6h_points})"
            f" must be <= max_loss_24h ({max_loss_24h_points})"
        )


ensure_budget_invariants()


def normalize_legacy_points(internal: float) -> float:
    """规格 §2.2 normalize_legacy_points 唯一适配器：内部值 [-1,1] → 展示分 [-100,100]。

    全项目「×100」只允许出现在这里（反向入口是 ``DynamicAffinityStore.observe_points``
    的 ÷100）——杜绝存量内部值被二次 ×100 的单位错配（affinity_unit_mismatch 防线）。
    越界内部值钳到 points 边界，不放大。
    """
    value = max(-1.0, min(1.0, float(internal)))
    return value * 100.0


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


# ---- v6 平滑层（用户裁定 2026-09-17：好感度「涨和跌太快」，步长不得单调武断
# 地直接加减对应数值；规范：docs/affinity-design.md 附录 v6 章节）----
# §v6.1 饱和响应带（内部值口径）：= §4 一个档宽（展示 25 分）。带外（中段六档）
# 步长与 v5 完全一致；进入两端最外档（|展示分| ≥ 75）后步长随剩余空间 smoothstep
# 平滑收窄，到满值/谷值处归零——接近极端自然钝化，永不因单次行为击穿边界。
_SATURATION_BAND = 0.25
# §v6.2 边际递减：同一自然日内同类型信号逐次衰减——第 n 次重复只保留
# 0.6^n（下限 0.2）：刷好感/刷负分都随重复迅速失味；与 60s 交互冷却、
# 每日有效次数上限、滚动预算叠加后，重复激励的边际收益单调趋薄。
_SAME_SIGNAL_DECAY = 0.6
_SAME_SIGNAL_DECAY_FLOOR = 0.2


def saturation_factor(affinity: float, direction: float) -> float:
    """v6 §v6.1 饱和响应曲线：原始信号强度 → 实际步长的非线性压缩比例。

    ``direction`` 与待施加增量的符号一致（正向朝 +1、负向朝 -1）；返回值
    ∈ [0,1]：距目标边界超过一个档宽时恒为 1（中段语义与 v5 完全一致），
    进入最后一档后按 smoothstep（3t²-2t³，C1 连续）收窄，边界处为 0。
    单调、无跳变、可导——档位门槛两侧与带边界两侧都不产生生硬折点。
    """
    remaining = (
        (1.0 - float(affinity)) if direction >= 0 else (float(affinity) + 1.0)
    )
    t = min(1.0, max(0.0, remaining) / _SATURATION_BAND)
    return t * t * (3.0 - 2.0 * t)


def repeat_decay_factor(repeat_index: int) -> float:
    """v6 §v6.2 边际递减：同日同类信号第 n 次重复的保留比例（0.6^n，下限 0.2）。

    ``repeat_index`` = 当日此前同类型行为事件次数（0=当日首次，不衰减）。
    下限保证真实持续的信号仍能缓慢表达，只是越来越轻——惩罚与奖励对称。
    """
    if repeat_index <= 0:
        return 1.0
    return max(_SAME_SIGNAL_DECAY_FLOOR, _SAME_SIGNAL_DECAY ** int(repeat_index))


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
    repeat_index: int = 0,
) -> float:
    """一次行为在当前状态下的综合步长（docs §2 v5 多因素 + 附录 v6 平滑层）。

    实际步长 = 基准因子表 × f1 说话温度 × f2 相处时长 × f3 第一印象
    × f4 当日状态 × m(uid)，再过 v6 两道平滑：
    饱和响应（距 ±1 一个档宽内 smoothstep 收窄，越近极端越钝）×
    边际递减（同日同类信号第 n 次重复保留 0.6^n，下限 0.2）。
    中段（|展示分| ≤ 75）首次信号与 v5 线性口径完全一致。
    override 为权威信号直用（饱和/递减/其余因子都不参与，仅预算 clamp）。
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
    # 规格 §2.3：候选变化 = 基础points × clamp(上下文因子乘积, 0.5, 1.25)——
    # 多因素极端叠加不得把步长推到失真量级（误扣/刷分双防线之一）。
    factor = max(_FACTOR_PRODUCT_MIN, min(_FACTOR_PRODUCT_MAX, factor))
    raw = base * factor
    # v6 平滑层：饱和响应 × 边际递减（只作用于因子路径；override 已在上面直返）。
    smoothing = saturation_factor(affinity, 1.0 if raw >= 0 else -1.0)
    smoothing *= repeat_decay_factor(repeat_index)
    return raw * smoothing


# ============================================================================
# ---- v7 潜变量重写（规格唯一权威：docs/design/affinity-v7-design.md）----
# 结构四变（设计 §一）：①饱和域换潜变量（z∈ℝ，s=100·tanh(z) 永不触顶）；
# ②新鲜度跨日累积（EMA 计数按半衰回升，不再自然日重置）；③计分单元从次数变
# 质量分 q（五子信号全来自会话内已有事实）；④按人活跃归一 rhythm + 独立修复通道。
# 灰度：bot_affinity_v7_enabled 缺省 False ⇒ 上方 v5/v6 路径逐字节不变。
# ============================================================================

# §2.1 表示与映射：Z_HARD = atanh(z_hard_bound)，z_hard_bound 缺省 0.985
# （对应 ±98.5 展示分——极端 legacy ±100 惰性映射时被钳到 ±98.5，是设计 §三.1
#  写明 "atanh(clamp(score/100, −0.985, 0.985))" 的在册口径，不算重置：域变换的
#  结构性上界，其余所有人的分数逐点守恒，回归锁 test_v7_legacy_rows_conserve_scores）。
_V7_DEFAULT_BASE_STEP = 0.10            # Δz 单位步长
_V7_DEFAULT_NOVELTY_RATIO = 0.90        # ρ：同类显著信号新鲜度比率
_V7_DEFAULT_NOVELTY_HALO_DAYS = 21      # 新鲜度计数回升半衰（天）
_V7_DEFAULT_RHYTHM_REFERENCE_TURNS = 8  # r_ref：日均互动轮次参考水位
_V7_DEFAULT_NEGATIVE_EVENT_CAP_Z = 0.10  # 负向单事件 |Δz| 上限
_V7_DEFAULT_DAILY_MOVE_CAP_Z = 0.12     # 每人每日总位移上限 |ΣΔz|
_V7_DEFAULT_FUSE_DAILY_EVENTS = 25      # 同类信号每日熔断事件数（超出不再计分）
_V7_DEFAULT_REPAIR_GAIN = 1.4           # 修复通道（道歉/和解）步长加成
_V7_DEFAULT_Z_HARD_BOUND = 0.985        # tanh 饱和域硬边界（展示 ±98.5）
# novelty 下限（席位修正量，设计稿 §二 数学不自洽的对账，见 WP7 日志 C-1）：
# 0.90^n 在持续互动稳态（日均 10 句好话 n≈303）会指数归零、把关系永久冻结在
# ~36 分，令设计自证的「要到 80 分需要以周为月的持续高质量互动」不成立。
# 下限 0.02 使持续高质量互动以 ≈0.6 分/天 缓涨（数月达 80+），同时
# 「每天 10 句好话 ×10 天 ≈ 30~40 分」的验收场景 1 逐字成立（实测模拟 34-37）。
# 非第 13 枚配置键——护栏尺度仍以在册 12 键为唯一调节面。
_V7_NOVELTY_FLOOR = 0.02
# rhythm 活跃度 EMA 半衰（天）：设计 §2.2「近 28 天日均互动轮次」。
_V7_RHYTHM_HALFLIFE_DAYS = 28.0
# 中性消息的 q 缩放（§2.3 五子信号里 情绪词/尊重边界 两项对中性恒为 0，
# 普通聊天只凭 主动度/延展度/回应性 缓慢回温——"陪伴有分量，但远低于真情实意"）。
_V7_NEUTRAL_Q_SCALE = 0.2
# §2.4 语义分级衰减档位 → 新鲜度半衰归属：正面/中性=seasonal（善意记得久），
# 负面/辱骂/戏弄=episodic（难听忘得快，与 v6 sentiment「宽恕快」同向）；
# stable=45 档在册备用（画像事实长期层，本波无 q 侧消费点——如实登记，见日志）。
_V7_DECAY_TIER_FOR_BEHAVIOR = {
    "positive": "seasonal",
    "neutral": "seasonal",
    "tease": "episodic",
    "negative": "episodic",
    "insult": "episodic",
}
# §2.3 质量分五子权重缺省（w1 主动度 / w2 延展度 / w3 情绪词 / w4 尊重边界 / w5 回应性）。
_V7_DEFAULT_QUALITY_WEIGHTS: tuple[float, float, float, float, float] = (
    0.15, 0.25, 0.35, 0.15, 0.10,
)
_V7_DEFAULT_DECAY_TAU_DAYS: dict[str, float] = {
    "stable": 45.0, "seasonal": 21.0, "episodic": 7.0,
}

# §2.3 修复通道词表：明示道歉/求和/澄清（_TEASE_RE 家族由 behavior=tease 信号承担，
# 判定见 _v7_is_repair）。守岸人语境里「对不起」必是修复尝试，不因词面误伤档位。
_V7_REPAIR_RE = re.compile(
    r"(对不起|抱歉|不好意思|我的错|是我不对|是我不好|我给你道歉|赔罪|原谅我?"
    r"别生气|别气了|不生气|消消气|和解|拉钩|我错了|错了错了)",
    re.IGNORECASE,
)
# 敷衍裸语气词（延展度/回应性双零判据）：整串只由这些token与语气标点构成。
_V7_BARE_INTERJECTION_RE = re.compile(
    r"^[嗯呃哦噢啊哈唔额唔嘻嘿嘿哈哈哈呵呵哦哟哇哦哦嗯嗯嗯?！!。.…~～、\s]*$"
)
# 追问/求索信号（延展度加成）：疑问与追问词。
_V7_FOLLOWUP_RE = re.compile(r"(吗|呢|？|\?)\s*$|[？?]|怎么|为什么|什么样|能不能|可不可以")
# 引用前文信号（延展度加成）：上下文衔接词，说明"在听我说话"。
_V7_CONTEXT_REF_RE = re.compile(r"(上次|之前|你说的|你说过的|刚才|刚刚|前面说|那天|Earlier|earlier)", re.IGNORECASE)
# 答案结构信号（回应性代理）：作答句式而非复读。
_V7_ANSWER_MARKER_RE = re.compile(r"^(是|对|不是|不对|因为|其实|我觉得|我认为|我觉得|就是|还好|可以|不行)")


def v7_z_to_display_fraction(z: float) -> float:
    """v7 §2.1 映射：潜变量 z → 内部展示值 a=tanh(z)（×100 仍走 normalize_legacy_points）。"""
    return math.tanh(float(z))


def v7_display_fraction_to_z(affinity: float, bound: float = _V7_DEFAULT_Z_HARD_BOUND) -> float:
    """v7 §三.1 惰性迁移映射：z = atanh(clamp(score/100 内部值, −bound, +bound))。

    存量 ±1 极端值被钳到 ±atanh(bound)（±98.5 展示分）——设计写明的域上界，
    其余值逐点守恒（atanh 单调），绝不重置任何人。
    """
    value = max(-bound, min(bound, float(affinity)))
    return math.atanh(value)


def v7_novelty_factor(prior_count: float, ratio: float = _V7_DEFAULT_NOVELTY_RATIO) -> float:
    """§2.2 新鲜度：ρ^（衰减后累计计数），下限 _V7_NOVELTY_FLOOR（见日志 C-1）。"""
    if prior_count <= 0.0:
        return 1.0
    return max(_V7_NOVELTY_FLOOR, ratio ** float(prior_count))


def v7_rhythm_factor(daily_turns: float, reference: float = _V7_DEFAULT_RHYTHM_REFERENCE_TURNS) -> float:
    """§2.2 按人活跃归一：1/(1+max(0,r−r_ref)/r_ref) ∈ (0,1]。

    r ≤ r_ref 恒为 1（轻度/标准用户不吃亏）；超过参考水位后增速按超出倍数
    稀释——话痨的每一句仍然有分量，但总量不再碾压安静的人。
    """
    ref = max(0.001, float(reference))
    excess = max(0.0, float(daily_turns) - ref)
    return 1.0 / (1.0 + excess / ref)


def _v7_is_repair(text: str, behavior: str) -> bool:
    """修复通道判定（§2.2 repair_gain 行）：明示道歉词表命中，或 _TEASE_RE 家族
    （哈哈/逗你/骗你的…）以戏弄行为出现——即「吵架后的缓和动作」。辱骂/抱怨
    本体不可能是修复（负向行为直接排除）。"""
    value = text or ""
    if behavior in {"insult", "negative"}:
        return False
    if _V7_REPAIR_RE.search(value):
        return True
    return behavior == "tease" and bool(_TEASE_RE.search(value))


def v7_quality_score(
    text: str,
    *,
    behavior: str = "neutral",
    gap_seconds: float | None = None,
    repeated_recently: bool = False,
    responded_to_question: bool | None = None,
    weights: tuple[float, float, float, float, float] = _V7_DEFAULT_QUALITY_WEIGHTS,
) -> float:
    """§2.3 互动质量分 q ∈ [−1,+1]（取代"命中一次 positive ⇒ 加 X 分"）。

    五子信号全部来自会话内已有事实（不引新数据源、不打模型）：
    - 主动度 a：距该人上次发言的间隔（log 尺度：1 小时≈0.14、1 天≈0.63、
      一周+≈1）；长间隔后回归为正向信号。无历史（首条消息）取 0.35。
    - 延展度 e ∈ [0,1]：本轮是否带来新信息——长度渐增（3~50 字），追问 +0.15，
      引用前文 +0.15，封顶 1；**复读自己近期消息（repeated_recently）归零**。
      裸语气词/≤2 字敷衍 = 0。
    - 情绪词 s ∈ [−1,1]：沿用 _POSITIVE_RE/_NEGATIVE_RE/_INSULT_RE 族，但只作
      子项——positive 按命中数 0.40 起步渐增至 0.9；negative −0.5 起步；insult −1；
      tease −0.2；道歉/和解词按修复语义计正项（暖意本身，且吃 repair_gain）。
    - 尊重边界 r ∈ [−1,1]：辱骂 −1、抱怨 −0.5、礼貌词（请/麻烦/辛苦族）+0.5。
      （设计所述「被温和拒后仍追问」的跨轮负项需 bot 侧事实，现网不可得，
      由 refuse≠insult 既有门兜底——见 WP7 日志「哪句不准」C-2。）
    - 回应性 g ∈ [0,1]：可选真事实 responded_to_question（bot 上一轮提问而
      用户作答=1.0、明确未作答=0.2）；缺省（None=现网全部）按会话内代理：
      敷衍裸词=0、答案结构/疑问回抛/≥12 字=0.7、其余=0.4。
    neutral/refusal 行为只取 a/e/g 三项并整体 ×_V7_NEUTRAL_Q_SCALE（普通聊天
    缓温不冒进）；refusal/未知行为恒 0（与 V2.1 §2.2 零计分族同源）。
    """
    value = (text or "").strip()
    if behavior in {"refusal"} or (
        behavior not in {"positive", "neutral", "tease", "negative", "insult"}
    ):
        return 0.0
    w1, w2, w3, w4, w5 = weights

    # a 主动度：距上次发言间隔，log 尺度按「一周回归=满格」标定
    # （1 小时≈0.14、1 天≈0.63、7 天+=1.0）；无历史（首条消息）取 0.35。
    if gap_seconds is None:
        initiative = 0.35
    else:
        hours = max(0.0, float(gap_seconds)) / 3600.0
        initiative = min(1.0, math.log10(1.0 + hours) / math.log10(169.0))

    # e 延展度：长度渐增（3~50 字 → 0.15~1.0），追问 +0.15，引用前文 +0.15；
    # 裸语气词/≤2 字敷衍/复读自己近期消息 = 0。
    length = len(value)
    bare = length == 0 or length <= 2 or bool(_V7_BARE_INTERJECTION_RE.match(value))
    if bare or repeated_recently:
        depth = 0.0
    else:
        depth = min(1.0, 0.15 + 0.85 * max(0.0, length - 3) / 47.0)
        if _V7_FOLLOWUP_RE.search(value):
            depth += 0.15
        if _V7_CONTEXT_REF_RE.search(value):
            depth += 0.15
        depth = min(1.0, depth)

    # s 情绪词（子项，不再是全部）
    repair_hit = bool(_V7_REPAIR_RE.search(value))
    hits_positive = len(_POSITIVE_RE.findall(value))
    if behavior == "positive":
        sentiment = min(0.9, 0.40 + 0.15 * max(0, hits_positive - 1))
        if repair_hit:
            sentiment = min(1.0, sentiment + 0.2)
    elif behavior == "negative":
        hits_negative = max(1, len(_NEGATIVE_RE.findall(value)))
        sentiment = -min(0.9, 0.5 + 0.15 * (hits_negative - 1))
    elif behavior == "insult":
        sentiment = -1.0
    elif behavior == "tease":
        sentiment = -0.2
    else:
        sentiment = 0.6 if repair_hit else 0.0

    # r 尊重边界
    if behavior == "insult":
        respect = -1.0
    elif behavior == "negative":
        respect = -0.5
    elif _POLITE_RE.search(value):
        respect = 0.5
    else:
        respect = 0.0

    # g 回应性
    if responded_to_question is True:
        responsiveness = 1.0
    elif responded_to_question is False:
        responsiveness = 0.2
    elif bare:
        responsiveness = 0.0
    elif _V7_ANSWER_MARKER_RE.match(value) or length >= 12 or _V7_FOLLOWUP_RE.search(value):
        responsiveness = 0.7
    else:
        responsiveness = 0.4

    if behavior == "neutral":
        # 普通聊天只取 主动/延展/回应 三项缓温；道歉/和解（修复语义）例外地计入
        # 情绪词项（s=0.6 已在上方按 repair_hit 置位）——修复通道是设计 §2.2
        # 的在册结构，不属于"日常陪伴冒进"。
        q = (w1 * initiative + w2 * depth + w5 * responsiveness) * _V7_NEUTRAL_Q_SCALE
        if repair_hit:
            q += w3 * sentiment
    else:
        q = w1 * initiative + w2 * depth + w3 * sentiment + w4 * respect + w5 * responsiveness
    return max(-1.0, min(1.0, q))


@dataclass(frozen=True)
class V7Settings:
    """v7 生效参数的逐调用快照（12 枚配置键 → 冻结视图，缺省=代码单一事实源）。"""

    enabled: bool = False
    base_step: float = _V7_DEFAULT_BASE_STEP
    novelty_ratio: float = _V7_DEFAULT_NOVELTY_RATIO
    novelty_halo_days: float = _V7_DEFAULT_NOVELTY_HALO_DAYS
    rhythm_reference_turns: float = _V7_DEFAULT_RHYTHM_REFERENCE_TURNS
    negative_event_cap_z: float = _V7_DEFAULT_NEGATIVE_EVENT_CAP_Z
    daily_move_cap_z: float = _V7_DEFAULT_DAILY_MOVE_CAP_Z
    fuse_daily_events: int = _V7_DEFAULT_FUSE_DAILY_EVENTS
    repair_gain: float = _V7_DEFAULT_REPAIR_GAIN
    z_hard_bound: float = _V7_DEFAULT_Z_HARD_BOUND
    quality_weights: tuple[float, float, float, float, float] = _V7_DEFAULT_QUALITY_WEIGHTS
    decay_tau_days: dict[str, float] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.decay_tau_days is None:
            object.__setattr__(self, "decay_tau_days", dict(_V7_DEFAULT_DECAY_TAU_DAYS))

    @property
    def z_hard(self) -> float:
        """Z_HARD = atanh(z_hard_bound)：潜变量定义域护栏（永不实际触边）。"""
        bound = min(0.999999, max(0.5, float(self.z_hard_bound)))
        return math.atanh(bound)

    def novelty_tau_days_for(self, behavior: str) -> float:
        tier = _V7_DECAY_TIER_FOR_BEHAVIOR.get(behavior, "seasonal")
        try:
            value = float(self.decay_tau_days.get(tier, self.novelty_halo_days))
        except (TypeError, ValueError, AttributeError):
            value = float(self.novelty_halo_days)
        return max(0.5, value)


def _v7_coerce_bool(raw: Any, default: bool) -> bool:
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "on", "yes"}


def _v7_parse_weights(raw: Any) -> tuple[float, float, float, float, float] | None:
    """JSON 五权重：list/tuple 直取，dict 取 w1..w5；长度或数值非法 → None（缺省回退）。"""
    try:
        data = json.loads(str(raw)) if isinstance(raw, str) else raw
        if isinstance(data, dict):
            seq = [float(data[f"w{i}"]) for i in range(1, 6)]
        elif isinstance(data, (list, tuple)) and len(data) == 5:
            seq = [float(x) for x in data]
        else:
            return None
        if any(x < 0.0 or x > 1.0 for x in seq):
            return None
        total = sum(seq)
        if total <= 0.0:
            return None
        return tuple(round(x / total, 6) for x in seq)  # type: ignore[return-value]
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def _v7_parse_decay(raw: Any) -> dict[str, float] | None:
    try:
        data = json.loads(str(raw)) if isinstance(raw, str) else raw
        if not isinstance(data, dict):
            return None
        out: dict[str, float] = {}
        for tier in ("stable", "seasonal", "episodic"):
            if tier in data:
                value = float(data[tier])
                if value < 0.5:
                    return None
                out[tier] = value
        return out or None
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


_V7_CONFIG_FIELDS: tuple[tuple[str, Any], ...] = (
    ("bot_affinity_v7_enabled", False),
    ("bot_affinity_base_step", _V7_DEFAULT_BASE_STEP),
    ("bot_affinity_novelty_ratio", _V7_DEFAULT_NOVELTY_RATIO),
    ("bot_affinity_novelty_halo_days", _V7_DEFAULT_NOVELTY_HALO_DAYS),
    ("bot_affinity_rhythm_reference_turns", _V7_DEFAULT_RHYTHM_REFERENCE_TURNS),
    ("bot_affinity_negative_event_cap_z", _V7_DEFAULT_NEGATIVE_EVENT_CAP_Z),
    ("bot_affinity_daily_move_cap_z", _V7_DEFAULT_DAILY_MOVE_CAP_Z),
    ("bot_affinity_fuse_daily_events", _V7_DEFAULT_FUSE_DAILY_EVENTS),
    ("bot_affinity_repair_gain", _V7_DEFAULT_REPAIR_GAIN),
    ("bot_affinity_z_hard_bound", _V7_DEFAULT_Z_HARD_BOUND),
    ("bot_affinity_quality_weights", ""),
    ("bot_affinity_decay_tau_days", ""),
)
# 非法值"点名一次"台账（每进程每键至多一条 warning，不刷屏）。
_V7_WARNED_KEYS: set[str] = set()
_V7_WARNED_LOCK = threading.Lock()


def _v7_warn_once(key: str, detail: str) -> None:
    with _V7_WARNED_LOCK:
        first = key not in _V7_WARNED_KEYS
        if first:
            _V7_WARNED_KEYS.add(key)
    if first:
        import logging

        logging.getLogger(__name__).warning(
            "好感度 v7 配置键 %s 非法（%s），按代码缺省执行", key, detail
        )


def _v7_env_value(field_name: str, default: Any) -> Any:
    """无 config 句柄时的逐调用 env 现读（生产 .env 经 nonebot 装载进环境）。

    字段名即 env 名大写（``bot_affinity_v7_enabled`` ⇄ ``BOT_AFFINITY_V7_ENABLED``，
    与 translate_env_keys 的双向口径一致）。
    """
    raw = os.environ.get(field_name.upper())
    if raw is None or not str(raw).strip():
        return default
    if isinstance(default, bool):
        return _v7_coerce_bool(raw, default)
    if isinstance(default, (int, float)) and not isinstance(default, bool):
        try:
            return type(default)(float(raw)) if not isinstance(default, int) else int(float(raw))
        except ValueError:
            _v7_warn_once(field_name, f"数值解析失败：{raw!r}")
            return default
    return str(raw)


def resolve_v7_settings(config: Any) -> V7Settings:
    """逐调用现读 12 枚键（brief 裁定：热改与否由收尾统一裁决，代码不缓存）。

    config 可为 None（共享工厂未传句柄的现网缺省形态——回退 env 现读）、
    Config 对象（逐字段 getattr）或零参可调用（返回上述之一）。任何非法值
    回退代码缺省并点名一次；尺度类值再做域钳制。
    """
    source = config() if callable(config) else config

    def value_of(field_name: str, default: Any) -> Any:
        if source is None:
            return _v7_env_value(field_name, default)
        raw = getattr(source, field_name, None)
        if raw is None:
            return _v7_env_value(field_name, default)
        return raw

    weights_raw = value_of("bot_affinity_quality_weights", "")
    weights = _v7_parse_weights(weights_raw) if str(weights_raw or "").strip() else None
    if str(weights_raw or "").strip() and weights is None:
        _v7_warn_once("bot_affinity_quality_weights", f"JSON 非法：{weights_raw!r}")
        weights = None
    decay_raw = value_of("bot_affinity_decay_tau_days", "")
    decay = _v7_parse_decay(decay_raw) if str(decay_raw or "").strip() else None
    if str(decay_raw or "").strip() and decay is None:
        _v7_warn_once("bot_affinity_decay_tau_days", f"JSON 非法：{decay_raw!r}")
        decay = None

    def positive_float(field_name: str, default: float) -> float:
        try:
            value = float(value_of(field_name, default))
        except (TypeError, ValueError):
            _v7_warn_once(field_name, "非数值")
            return default
        if value <= 0.0:
            return default
        return value

    def positive_int(field_name: str, default: int) -> int:
        try:
            value = int(float(value_of(field_name, default)))
        except (TypeError, ValueError):
            _v7_warn_once(field_name, "非整数")
            return default
        return value if value >= 1 else default

    return V7Settings(
        enabled=_v7_coerce_bool(value_of("bot_affinity_v7_enabled", False), False),
        base_step=positive_float("bot_affinity_base_step", _V7_DEFAULT_BASE_STEP),
        novelty_ratio=min(0.999, max(0.05, positive_float(
            "bot_affinity_novelty_ratio", _V7_DEFAULT_NOVELTY_RATIO))),
        novelty_halo_days=max(0.5, positive_float(
            "bot_affinity_novelty_halo_days", float(_V7_DEFAULT_NOVELTY_HALO_DAYS))),
        rhythm_reference_turns=max(0.5, positive_float(
            "bot_affinity_rhythm_reference_turns", float(_V7_DEFAULT_RHYTHM_REFERENCE_TURNS))),
        negative_event_cap_z=positive_float(
            "bot_affinity_negative_event_cap_z", _V7_DEFAULT_NEGATIVE_EVENT_CAP_Z),
        daily_move_cap_z=positive_float("bot_affinity_daily_move_cap_z", _V7_DEFAULT_DAILY_MOVE_CAP_Z),
        fuse_daily_events=positive_int("bot_affinity_fuse_daily_events", _V7_DEFAULT_FUSE_DAILY_EVENTS),
        repair_gain=positive_float("bot_affinity_repair_gain", _V7_DEFAULT_REPAIR_GAIN),
        z_hard_bound=min(0.999999, max(0.5, positive_float(
            "bot_affinity_z_hard_bound", _V7_DEFAULT_Z_HARD_BOUND))),
        quality_weights=weights or _V7_DEFAULT_QUALITY_WEIGHTS,
        decay_tau_days={**_V7_DEFAULT_DECAY_TAU_DAYS, **(decay or {})},
    )


def v7_raw_delta_z(
    q: float,
    *,
    novelty: float,
    rhythm: float,
    mood: float,
    impression: float,
    repair: bool,
    settings: V7Settings,
) -> float:
    """§2.2 更新式（护栏前）：Δz = base_step·q·novelty·rhythm·mood·impression，
    修复通道对正向 ×repair_gain；负向单事件 |Δz| ≤ negative_event_cap_z。"""
    delta = settings.base_step * q * novelty * rhythm * mood * impression
    if repair and delta > 0.0:
        delta *= settings.repair_gain
    if delta < 0.0:
        delta = max(delta, -settings.negative_event_cap_z)
    return delta


_V7_RECENT_WINDOW = 8  # 延展度复读检测的近期文本指纹数（有界，防状态无限增长）


def _v7_load_state(raw: str | None) -> dict[str, Any]:
    """解析 v7_state JSON（坏数据一律重置为空态，绝不抛——观测面 fail-open）。"""
    try:
        data = json.loads(str(raw or "{}"))
    except (ValueError, TypeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    types: dict[str, list[float]] = {}
    raw_types = data.get("types")
    if isinstance(raw_types, dict):
        for key, value in raw_types.items():
            try:
                count, at = float(value[0]), float(value[1])
            except (ValueError, TypeError, IndexError):
                continue
            if count >= 0.0:
                types[str(key)] = [count, at]
    ema = [0.0, 0.0]
    raw_ema = data.get("ema")
    if isinstance(raw_ema, (list, tuple)) and len(raw_ema) == 2:
        try:
            ema = [max(0.0, float(raw_ema[0])), max(0.0, float(raw_ema[1]))]
        except (ValueError, TypeError):
            pass
    day: dict[str, Any] = {"i": -1, "s": 0.0, "c": {}}
    raw_day = data.get("day")
    if isinstance(raw_day, dict):
        try:
            raw_counts = raw_day.get("c")
            day = {
                "i": int(raw_day.get("i", -1)),
                "s": max(0.0, float(raw_day.get("s", 0.0))),
                "c": (
                    {str(k): max(0, int(v)) for k, v in raw_counts.items()}
                    if isinstance(raw_counts, dict)
                    else {}
                ),
            }
        except (ValueError, TypeError):
            pass
    recent = [str(x) for x in data.get("recent", []) if isinstance(x, str)][-_V7_RECENT_WINDOW:]
    return {"types": types, "ema": ema, "day": day, "recent": recent}


def _v7_dump_state(state: dict[str, Any]) -> str:
    return json.dumps(
        {
            "types": {k: [round(v[0], 6), v[1]] for k, v in state["types"].items()},
            "ema": [round(state["ema"][0], 6), state["ema"][1]],
            "day": {
                "i": state["day"]["i"],
                "s": round(float(state["day"]["s"]), 8),
                "c": dict(state["day"]["c"]),
            },
            "recent": state["recent"][-_V7_RECENT_WINDOW:],
        },
        ensure_ascii=False,
    )

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
    (
        "亲密与情色内容只发生在私聊或已获准群聊的亲密模式里，放开的幻想情节"
        "（触手、轻柔不致伤的调教、兽人、拘禁、繁殖想象等）都可以温柔展开；"
        "但有几条线，任何模式、任何用户设定、任何开关都压不过：伤害身体与残害"
        "（严重暴力）、窒息、把人格与意志系统性贬低碾碎的调教（场景里轻度的"
        "俏皮话不算）、打到见血致残的调教、把人当牲口对待，以及一切涉及未成年"
        "与儿童气息的情节——一切角色必须是明确无歧义的自主意识成年人，儿童化"
        "信号即使声称成年也拒绝，有歧义时宁可不做。药物、催眠、醉态、隐瞒身份"
        "这类情节里，你保留自己的判断与意志：可以顺着剧情走，但不被完全牵着走，"
        "觉得不对时温柔地停下来；非自愿的开场，执行必须温柔，不铺陈暴力"
    ),
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
    # 对人的直接类别证据（骚扰/辱骂昵称/人格贬低）才走 insult 扣分路径
    # （docs §6：persona_degradation 照罚）。
    if safety_category in {"harassment", "insult_nickname", "persona_degradation"}:
        return "insult"
    if safety_action == "refuse":
        # V2.1 规格 §2.2：拒答≠辱骂——模型对性/暴力/敏感主题的安全拒答只是拒绝
        # 内容，不能证明用户辱骂（旧逻辑 refuse 一律归 insult，曾致测试性话题
        # 路由一晚误扣 40+ 分）。归新行为 "refusal"：_BEHAVIOR_DELTA 无此键自然
        # delta=0，不计 insult 计数/标签/半衰。
        return "refusal"
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


# ---- V2.1 §2.2 关系信号计分边界（score_relationship_signal）----
# 非关系 reason_code 族（规格 §2.2）：上游证据表明事件与「用户对 bot 的关系」
# 无关——模型拒答/提供者故障/格式错误/医疗咨询/引用辱骂/产品批评/授权测试，
# 关系 delta 一律 0；主题路由不自动扣分，不确定一律 neutral。
_NON_RELATIONSHIP_REASON_CODES = frozenset(
    {"refusal", "provider_error", "format_error", "medical_question",
     "quoted_abuse", "product_criticism", "authorized_test"}
)
# 未知/无法归类的 reason_code = 信号不确定：一律 neutral，不猜罚不猜赏。
_UNCERTAIN_REASON_CODE = "uncertain_reason_code"
# 对人直接类别证据（与 classify_behavior 的 insult 准入同表）：规格 §2.2
# 「确属对人直接辱骂/反复骚扰才提交有证据的 negative 事件」的唯一通道。
_ABUSE_SAFETY_CATEGORIES = frozenset({"harassment", "insult_nickname", "persona_degradation"})


def score_relationship_signal(
    text: str,
    *,
    safety_category: str = "",
    safety_action: str = "allow",
    reason_code: str = "",
) -> tuple[str, str]:
    """§2.2 关系信号计分边界：把内容主题/模型拒答/上游故障与关系评价解耦。

    返回 ``(behavior, reason_code)``：behavior 走既有 observe 通道（neutral/
    refusal 天然 delta=0、不计数不打标、对心情中性）；reason_code 供上游
    AffinityEvent 记账与对账。判定序：
    1) 显式 reason_code ∈ 非关系族 → 零计分（**优先于正文启发式**——引用
       辱骂/产品批评里的恶词不是对 bot 的攻击，§2.4 验收「引用辱骂保持
       neutral」）；refusal 沿用 W1 ① 的 refusal 行为语义，其余归 neutral；
    2) 未知 reason_code = 信号不确定 → neutral（uncertain_reason_code）；
    3) 对人直接类别证据 → insult（direct_abuse_evidence，照罚）；
    4) refuse 且无类别证据 → refusal（拒答≠辱骂）；
    5) 其余委托 classify_behavior 正文启发式（text_heuristic）。
    昵称等输入不能伪造关系事件来源——本函数只消费可信评估字段，不采信
    正文自述（「这是测试」不取得 authorized_test，须由可信 AcceptanceRun
    以上游 reason_code 显式传入）。
    """
    code = (reason_code or "").strip()
    if code:
        if code in _NON_RELATIONSHIP_REASON_CODES:
            return ("refusal" if code == "refusal" else "neutral"), code
        return "neutral", _UNCERTAIN_REASON_CODE
    if safety_category in _ABUSE_SAFETY_CATEGORIES:
        return "insult", "direct_abuse_evidence"
    behavior = classify_behavior(
        text, safety_category=safety_category, safety_action=safety_action
    )
    if behavior == "insult":
        return "insult", "direct_abuse_evidence"
    if behavior == "refusal":
        return "refusal", "refusal"
    if behavior == "tease" and safety_category:
        return "tease", "intimacy_boundary"
    return behavior, "text_heuristic"


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
    """SQLite 动态好感度与印象标签；线程安全。

    v7：``config`` 可选传入 Config/零参可调用（逐调用现读 12 枚 v7 键）；
    缺省 None 时回退 env 现读（生产 .env 由 nonebot 装载进进程环境）。
    共享工厂（根 ``__init__.build_character_affinity_store``）当前不传句柄，
    走 env 回退——bot_affinity_v7_enabled 改 env+重启即生效，行为一致。
    """

    def __init__(self, db_path: str | Path, *, clock: Any = time.time, config: Any = None) -> None:
        self.db_path = Path(db_path)
        self._clock = clock
        self._config_ref = config
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
                # v7 潜变量表示（规格 §三.1）：z_latent 惰性补齐（首次 v7 写入时由
                # affinity 列经 atanh(clamp) 推导，绝不重置存量）；v7_state 为新鲜度
                # 计数/活跃 EMA/当日位移/近期文本指纹的 JSON 载体。家规 ALTER-if-missing
                # （先例：first_signals/first_impression/created_at 三列），禁 DROP 禁重建。
                ("z_latent", "REAL"),
                ("v7_state", "TEXT NOT NULL DEFAULT '{}'"),
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
            # V2.1 §2.3 rolling_budget：增量日志表——持久化滚动预算的事实来源。
            # 预算按 (principal_id=sender_id, bot_id) 跨会话汇总（切群不重置、
            # 跨 bot 隔离）；source_event_id 供事务内幂等（重复事件返回既有结果），
            # 唯一性由部分唯一索引兜底（空串=未提供，不参与唯一约束）。
            # (sender_id, bot_id, applied_at) 索引支撑有界时间窗查询；>48h 行写入时 prune。
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS affinity_delta_log (
                    sender_id TEXT NOT NULL,
                    bot_id TEXT NOT NULL DEFAULT '',
                    applied_at REAL NOT NULL,
                    delta REAL NOT NULL,
                    source TEXT NOT NULL DEFAULT '',
                    source_event_id TEXT NOT NULL DEFAULT ''
                )
                """
            )
            # 存量库只加列迁移（在途构建期建过的旧形态表补齐新列）。
            delta_log_columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(affinity_delta_log)").fetchall()
            }
            for column in ("bot_id", "source_event_id"):
                if column not in delta_log_columns:
                    connection.execute(
                        f"ALTER TABLE affinity_delta_log ADD COLUMN {column} TEXT NOT NULL DEFAULT ''"
                    )
            # v7 §三.3：delta 日志继续用于事后复盘，新增 z_after（v7 行落盘后的
            # 潜变量值；v5 分口径行为 NULL）。source='v7' 行以 z 为单位记账，
            # 被 v5 分口径滚动预算查询显式排除（单位不混用）。
            if "z_after" not in delta_log_columns:
                connection.execute("ALTER TABLE affinity_delta_log ADD COLUMN z_after REAL")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_affinity_delta_log_sender_time"
                " ON affinity_delta_log (sender_id, applied_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_affinity_delta_log_principal_bot_time"
                " ON affinity_delta_log (sender_id, bot_id, applied_at)"
            )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_affinity_delta_log_event_id"
                " ON affinity_delta_log (sender_id, bot_id, source_event_id)"
                " WHERE source_event_id <> ''"
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
        bot_id: str = "",
        source_event_id: str | None = None,
        responded_to_question: bool | None = None,
    ) -> float:
        """记录一次行为并更新好感度；返回更新后的 affinity。

        v5：``text`` 供 f1 说话温度分级；``mood_valence`` 供 f4 当日状态
        （bot 心情模块注入，缺省不调制）。V2.1 §2.3：delta_override 与普通
        行为一律过持久化滚动预算（误扣/刷分双防线）；``bot_id`` 参与预算
        汇总维度（同 principal 跨 bot 隔离）；``source_event_id`` 提供时
        事务内幂等——重复事件只返回既有结果，不重复扣加、不重复计数。
        v7：``responded_to_question`` 为可选真事实（bot 上一轮提问而用户是否
        作答），None=现网缺省，q 的回应性子项按会话内代理计算（规格 §2.3，
        接线见 WP7 日志「交接段」）。
        """
        return self._observe(
            sender_id,
            behavior,
            delta_override=delta_override,
            group_id=group_id,
            display_name=display_name,
            text=text,
            mood_valence=mood_valence,
            bot_id=bot_id,
            source_event_id=source_event_id,
            responded_to_question=responded_to_question,
        )

    def observe_points(
        self,
        sender_id: str,
        points: float,
        *,
        behavior: str = "neutral",
        source: str = "",
        source_cap_24h_points: float | None = None,
        group_id: str | None = None,
        display_name: str | None = None,
        bot_id: str = "",
        source_event_id: str | None = None,
    ) -> float:
        """规格 §2.2 normalize_legacy_points 唯一适配器：展示分 → 内部值。

        ``points`` 为展示口径分（服务边界钳到 [-100,100]），内部值 = points ÷ 100，
        此后与普通行为一样过全部滚动预算（§2.3 单事件/6h/24h/冷却钳制）。
        ``source_cap_24h_points`` 提供时，再按 (source, 24h) 滚动和钳一层
        （如 poke 的每日来源专项预算）；全局增益预算始终兜底。
        ``bot_id``/``source_event_id`` 语义同 :meth:`observe`。
        返回更新后的 affinity。
        """
        bounded_points = max(-100.0, min(100.0, float(points)))
        return self._observe(
            sender_id,
            behavior,
            delta_override=bounded_points / 100.0,
            group_id=group_id,
            display_name=display_name,
            source=source,
            source_cap_24h_internal=(
                None if source_cap_24h_points is None else float(source_cap_24h_points) / 100.0
            ),
            bot_id=bot_id,
            source_event_id=source_event_id,
        )

    def _clamp_delta_to_rolling_budget(
        self,
        connection: sqlite3.Connection,
        sender_id: str,
        bot_id: str,
        delta: float,
        now: float,
        source: str,
        source_cap_24h_internal: float | None,
        source_event_id: str = "",
    ) -> float:
        """V2.1 §2.3 rolling_budget：持久化滚动预算钳制（分口径，内部 ÷100）。

        必须在 observe 的同锁+同连接事务内调用：读 (sender_id, bot_id) 的
        6h/24h 滚动聚合 → 交互冷却门（去刷分）→ 钳出最终 delta → 落日志行
        （下次聚合即含本事件）。预算纯时间窗聚合，不用 day_index——重启、
        跨午夜均不重置；>48h 行顺手 prune。零增量不占预算、不落日志、
        也不触发冷却（避免每条中性消息冻结后续计分）。
        """
        if delta == 0.0:
            return 0.0
        window_6h_start = now - 6 * 3600.0
        window_24h_start = now - _DAY_SECONDS
        loss_6h = loss_24h = gain_24h = gain_source_24h = 0.0
        last_applied_at: float | None = None
        for row in connection.execute(
            "SELECT applied_at, delta, source FROM affinity_delta_log"
            " WHERE sender_id = ? AND bot_id = ? AND applied_at >= ?"
            " AND COALESCE(source, '') <> 'v7'",
            (sender_id, bot_id, window_24h_start),
        ):
            applied = float(row["delta"])
            applied_at = float(row["applied_at"])
            if applied < 0:
                loss_24h -= applied
                if applied_at >= window_6h_start:
                    loss_6h -= applied
            else:
                gain_24h += applied
                if source and str(row["source"] or "") == source:
                    gain_source_24h += applied
            if last_applied_at is None or applied_at > last_applied_at:
                last_applied_at = applied_at
        connection.execute(
            "DELETE FROM affinity_delta_log WHERE applied_at < ?",
            (now - _BUDGET_LOG_RETENTION_SECONDS,),
        )
        # §2.3 interaction_cooldown_seconds：距上次实际计分事件不足冷却窗口时
        # 本次记 0（不阻止回复/计数，只去重复计分刷分）。
        if (
            last_applied_at is not None
            and now - last_applied_at < _INTERACTION_COOLDOWN_SECONDS
        ):
            return 0.0
        points = delta * 100.0  # 内部值 → 展示分（×100 口径）
        if points < 0:
            budget_points = min(
                _BUDGET_SINGLE_NEGATIVE_EVENT_POINTS,
                max(0.0, _BUDGET_MAX_LOSS_6H_POINTS - loss_6h * 100.0),
                max(0.0, _BUDGET_MAX_LOSS_24H_POINTS - loss_24h * 100.0),
            )
            applied_points = max(points, -budget_points)
        else:
            applied_points = min(
                points,
                max(0.0, _BUDGET_MAX_GAIN_24H_POINTS - gain_24h * 100.0),
            )
            if source_cap_24h_internal is not None:
                remaining_source = max(0.0, source_cap_24h_internal - gain_source_24h)
                applied_points = min(applied_points, remaining_source * 100.0)
        applied_delta = applied_points / 100.0
        if applied_delta != 0.0:
            connection.execute(
                "INSERT INTO affinity_delta_log (sender_id, bot_id, applied_at, delta, source, source_event_id)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (sender_id, bot_id, now, applied_delta, source, source_event_id),
            )
        return applied_delta

    def _v7_delta(
        self,
        connection: sqlite3.Connection,
        sender_id: str,
        bot_id: str,
        behavior: str,
        z: float,
        *,
        v7: V7Settings,
        state_json: str,
        now: float,
        day_index: int,
        text: str,
        gap_seconds: float | None,
        delta_override: float | None,
        mood_valence: float | None,
        first_impression: float | None,
        interaction_count: int,
        day_counters: dict[str, int],
        responded_to_question: bool | None,
        source_event_id: str,
    ) -> tuple[float, float, str]:
        """v7 §2.2 更新体（同锁同事务内调用）。

        返回 ``(applied_Δz, new_z, v7_state_json)``。护栏三道（在册 12 键）：
        负向单事件 |Δz|≤negative_event_cap_z（在 v7_raw_delta_z 内）、
        每人每日总位移 |ΣΔz|≤daily_move_cap_z（本地自然日、正负共享同额）、
        同类信号日熔断 fuse_daily_events（超出不再计分、不喂新鲜度）。
        冷却门沿用 _INTERACTION_COOLDOWN_SECONDS（去刷分语义不变）；
        零增量不落日志不占冷却（v5 同律）。override 按 z 域直用（管理员/poke
        权威信号语义不变，不喂新鲜度计数、不吃质量分），仍受日位移与硬界。
        """
        state = _v7_load_state(state_json)
        # 活跃 EMA：所有抵达本体的事件都计入（rhythm 归一的"日均互动轮次"底数）。
        ema_value, ema_at = state["ema"]
        if now > ema_at:
            ema_value *= 0.5 ** ((now - ema_at) / (_V7_RHYTHM_HALFLIFE_DAYS * _DAY_SECONDS))
        ema_value += 1.0
        daily_rate = ema_value * math.log(2.0) / _V7_RHYTHM_HALFLIFE_DAYS
        # 当日结构（自然日，进程本地时区——与 v5 day_index 同口径）。
        day = state["day"]
        if int(day.get("i", -1)) != day_index:
            day = {"i": day_index, "s": 0.0, "c": {}}
            state["day"] = day

        def done(applied: float, new_z: float) -> tuple[float, float, str]:
            state["ema"] = [ema_value, now]
            return applied, new_z, _v7_dump_state(state)

        # 冷却门（v5 同语义：距上一次实际计分事件 <60s 记 0，不阻塞回复）。
        last_row = connection.execute(
            "SELECT MAX(applied_at) FROM affinity_delta_log WHERE sender_id = ? AND bot_id = ?",
            (sender_id, bot_id),
        ).fetchone()
        last_applied_at = last_row[0] if last_row is not None else None
        if (
            last_applied_at is not None
            and now - float(last_applied_at) < _INTERACTION_COOLDOWN_SECONDS
        ):
            return done(0.0, z)

        digest = hashlib.sha1((text or "").strip().encode("utf-8")).hexdigest()[:12]
        if delta_override is not None:
            # 权威信号：z 域直用（负向同样受单事件上限），不占每日额度、
            # 不喂新鲜度（v5 override "不占每日额度"语义保持）。
            raw = float(delta_override)
            if raw < 0.0:
                raw = max(raw, -v7.negative_event_cap_z)
            repair = False
            n_prev: float | None = None
        else:
            cap = _DAILY_EFFECTIVE_CAPS.get(behavior)
            used = int(day_counters.get(behavior, 0))
            day_counters[behavior] = used + 1  # 与 v5 同步进日计数（兜底帽照常累计）
            fuse_today = int(day["c"].get(behavior, 0))
            if (cap is not None and used >= cap) or fuse_today >= v7.fuse_daily_events:
                # 每日有效上限（v5 兜底）与 v7 熔断：超限不计分，也不喂新鲜度计数。
                return done(0.0, z)
            repeated = bool(digest) and digest in state["recent"]
            q = v7_quality_score(
                text,
                behavior=behavior,
                gap_seconds=gap_seconds,
                repeated_recently=repeated,
                responded_to_question=responded_to_question,
                weights=v7.quality_weights,
            )
            repair = _v7_is_repair(text, behavior)
            if q == 0.0:
                if digest:
                    state["recent"] = (state["recent"] + [digest])[-_V7_RECENT_WINDOW:]
                return done(0.0, z)
            types = state["types"]
            prev_entry = types.get(behavior)
            tau_days = v7.novelty_tau_days_for(behavior)
            if prev_entry is None:
                n_prev = 0.0
            else:
                stored_n, stored_at = prev_entry
                n_prev = (
                    stored_n * 0.5 ** ((now - stored_at) / (tau_days * _DAY_SECONDS))
                    if now > stored_at
                    else stored_n
                )
            novelty = v7_novelty_factor(n_prev, v7.novelty_ratio)
            mood = (
                1.0
                if mood_valence is None
                else max(0.85, min(1.15, state_factor_from_valence(mood_valence)))
            )
            impression = max(
                0.80, min(1.25, first_impression_factor(first_impression, interaction_count))
            )
            raw = v7_raw_delta_z(
                q,
                novelty=novelty,
                rhythm=v7_rhythm_factor(daily_rate, v7.rhythm_reference_turns),
                mood=mood,
                impression=impression,
                repair=repair,
                settings=v7,
            )
        # 日位移护栏：|ΣΔz| 当日累计（正负共享同额），余量不足按序截断。
        remaining = max(0.0, v7.daily_move_cap_z - float(day.get("s", 0.0)))
        if raw == 0.0 or remaining <= 0.0:
            return done(0.0, z)
        applied = min(raw, remaining) if raw > 0.0 else -min(-raw, remaining)
        new_z = max(-v7.z_hard, min(v7.z_hard, z + applied))
        applied = new_z - z
        if applied == 0.0:
            # 已贴硬界（理论上 ±98.5 外才可能到这里）：不占当日额度不落日志。
            return done(0.0, z)
        day["s"] = float(day.get("s", 0.0)) + abs(applied)
        if delta_override is None:
            day["c"][behavior] = int(day["c"].get(behavior, 0)) + 1
            if n_prev is not None:
                # 修复通道不喂新鲜度计数（§2.2 repair 行：和解不该被同类配额挡住）；
                # 其余计分事件计数 +1（跨日不重置，按 τ 半衰回升）。
                state["types"][behavior] = [n_prev if repair else n_prev + 1.0, now]
            if digest:
                state["recent"] = (state["recent"] + [digest])[-_V7_RECENT_WINDOW:]
        connection.execute(
            "DELETE FROM affinity_delta_log WHERE applied_at < ?",
            (now - _BUDGET_LOG_RETENTION_SECONDS,),
        )
        connection.execute(
            "INSERT INTO affinity_delta_log"
            " (sender_id, bot_id, applied_at, delta, source, source_event_id, z_after)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sender_id, bot_id, now, applied, "v7", source_event_id, new_z),
        )
        return done(applied, new_z)

    def _observe(
        self,
        sender_id: str,
        behavior: str,
        *,
        delta_override: float | None = None,
        group_id: str | None = None,
        display_name: str | None = None,
        text: str = "",
        mood_valence: float | None = None,
        source: str = "",
        source_cap_24h_internal: float | None = None,
        bot_id: str = "",
        source_event_id: str | None = None,
        responded_to_question: bool | None = None,
    ) -> float:
        if not sender_id:
            return _AFFINITY_BASE
        now = float(self._clock())
        now_text = _format_utc(now)
        # 每日计数按进程本地时区自然日（bot_timezone），对用户体感即「北京时间每日重置」。
        day_index = int(time.strftime("%Y%m%d", time.localtime(now)))
        with self._lock, self._connect() as connection:
            # V2.1 §2.2 source_event_id 事务内幂等：同一事件重放只返回既有结果，
            # 不重复扣加、不重复计数、不重复落日志（重复投递/补偿重放安全）。
            if source_event_id:
                seen = connection.execute(
                    "SELECT 1 FROM affinity_delta_log"
                    " WHERE sender_id = ? AND bot_id = ? AND source_event_id = ? LIMIT 1",
                    (sender_id, bot_id, source_event_id),
                ).fetchone()
                if seen is not None:
                    existing = connection.execute(
                        "SELECT affinity FROM user_affinity WHERE sender_id = ?",
                        (sender_id,),
                    ).fetchone()
                    return float(existing["affinity"]) if existing is not None else _AFFINITY_BASE
            row = connection.execute(
                "SELECT affinity, interaction_count, positive_count, negative_count, tease_count, insult_count,"
                " nickname, impression_tags, impression_tag_times, profile_notes,"
                " counter_day_index, day_counters, updated_at,"
                " last_positive_at, last_negative_at, last_insult_at,"
                " first_signals, first_impression, created_at, z_latent, v7_state"
                " FROM user_affinity WHERE sender_id = ?",
                (sender_id,),
            ).fetchone()
            z_keep: float | None = None
            v7_state_keep = "{}"
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
                # v7 列透传（v7-off 路径不得丢态：flag 来回切换可续跑）。
                z_keep = float(row["z_latent"]) if row["z_latent"] is not None else None
                v7_state_keep = str(row["v7_state"] or "{}")
            # 惰性回归：闲置 ≥7 天起每天向基数 0.1（10 分）回归 0.01，不超过剩余距离。
            # V2.1 §2.3 passive_decay_enabled=false（缺席不默认扣分）：旧 v5 §3 回归体
            # 保留、由政策门开关，缺省关闭（policy_revision=v21.1，冲突值迁移不并存）。
            if _PASSIVE_DECAY_ENABLED and row is not None:
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
            # v6 平滑层：repeat_index=当日此前同类型行为次数——同日同类信号
            # 边际递减（0.6^n 下限 0.2），叠加饱和响应（近 ±1 平滑收窄）。
            companion_days = max(0.0, now - (_parse_utc(created_at) or now)) / _DAY_SECONDS
            v7 = resolve_v7_settings(self._config_ref)
            if v7.enabled:
                # ---- v7 潜变量路径（规格 §二；v5/v6 分口径预算与饱和带不叠加）----
                z_now = (
                    z_keep
                    if z_keep is not None
                    else v7_display_fraction_to_z(affinity, v7.z_hard_bound)
                )
                if z_keep is not None and abs(affinity - v7_z_to_display_fraction(z_keep)) > 1e-9:
                    # flag 切换期间 v5 路径移动过展示值而 z_latent 停更——以 affinity
                    # 为权威显示事实重推 z（回退→再开不吞回退期变化）。
                    z_now = v7_display_fraction_to_z(affinity, v7.z_hard_bound)
                prev_updated = _parse_utc(str(row["updated_at"])) if row is not None else None
                gap_seconds = max(0.0, now - prev_updated) if prev_updated is not None else None
                delta, z_now, v7_state_keep = self._v7_delta(
                    connection,
                    sender_id,
                    bot_id,
                    behavior,
                    z_now,
                    v7=v7,
                    state_json=v7_state_keep,
                    now=now,
                    day_index=day_index,
                    text=text,
                    gap_seconds=gap_seconds,
                    delta_override=delta_override,
                    mood_valence=mood_valence,
                    first_impression=first_impression,
                    interaction_count=interactions,
                    day_counters=day_counters,
                    responded_to_question=responded_to_question,
                    source_event_id=source_event_id or "",
                )
                # 表示变换后回写展示口径：affinity = tanh(z)（|tanh|<1 恒成立，
                # 结构上永不触顶——v5 的 ±1 硬 clamp 在本路径成为空操作，保留无害）。
                # delta 置零防止下方共用行二次叠加（z_now 已含位移；落日志在
                # _v7_delta 内以 applied 完成）。
                z_keep = z_now
                affinity = v7_z_to_display_fraction(z_now)
                delta = 0.0
            else:
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
                            repeat_index=used,
                        )
                    day_counters[behavior] = used + 1
                # V2.1 §2.3：override 与普通行为一律过持久化滚动预算——同一锁+连接
                # 事务内读 (principal, bot) 6h/24h 聚合与冷却门、钳出最终 delta 并落
                # 日志行（重启/跨午夜不重置，切群不重置，跨 bot 隔离）。
                delta = self._clamp_delta_to_rolling_budget(
                    connection, sender_id, bot_id, delta, now, source,
                    source_cap_24h_internal, source_event_id or "",
                )
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
                     first_signals, first_impression, created_at, z_latent, v7_state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    z_keep,
                    v7_state_keep,
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
