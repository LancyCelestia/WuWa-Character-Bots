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
（话痨不占便宜）；道歉/和解走独立修复通道（repair_gain，不吃新鲜度计数）；单事
件 |Δz| 上限（正负同帽，A-1 裁定 2026-09-26）+ 每人滚动 24h 位移上限（旧自然日
桶作废）+ 同类事件熔断三道护栏。存量分数经
z = atanh(clamp(score/100, ±bound)) 惰性映射，绝不重置任何人（表示变换，非重算）。
灰度开关 bot_affinity_v7_enabled 缺省 False ⇒ v5/v6 路径逐字节不变、可一键回退。
v8 边际递减 + 长尾（用户裁定 2026-09-27「好感度算法升级：边际递减 + 长尾效应」，
规格基线 docs/affinity-design.md v8 章节）：①边际递减——z 路径每步增量乘系数
γ(|z|) = half/(half+|z|) ∈ (0,1]（half = z_hard，即旧 ±98.5 硬界点改为半衰减
参考点；|z| 越大步进越小，正负对称），好感度越高、每分增益边际越小；②长尾——
更新处原 ±z_hard 硬截断改为浮点表示域护栏 atanh(0.999999)≈7.254，展示分严格
落在 (−99.9999, +99.9999) 内：曲线永不触顶、也永不因贴界冻结，增长持续减速。
γ≤1 保证单事件帽与滚动 24h 位移帽三道护栏界外无变化；存量惰性映射
（clamp ±0.985）逐字不动，零迁移零重置。
跨版本不变量（需求项 13 + 裁定 D3，2026-09-25 S-T-AFFIN-GUARD 席）：「禁瞬间巨变」
对**今天真在跑的 v5/v6 路**与 v7 路同尺成立——两路各自的位移界（v5/v6 滚动预算 /
v7 三道护栏 + tanh 域）之外，`delta_override` 与 `observe_points(points)` 这两个
「权威信号入口」经唯一消毒口 `coerce_override_delta` 收口：非有限脏值（NaN/±inf）
一律计 0（本次不动分、不落增量日志、不占冷却），落库前另有 `affinity_after_move`
末道闸兜住任何非有限残差。根因形态：`min/max` 对 NaN 的比较恒 False，
`min(z_hard, z+nan)` 会返回 z_hard 本身——一发脏 override 即可把展示分顶到
±98.5（v7 路实测）或触发 NOT NULL 拒绑异常（v5 路实测）。机器锁：
tests/test_affinity_no_instant_swing_all_versions.py（含牙齿自证）。
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
# 展示面有界化（「你对守岸人」读数，2026-10-03 席面）：sentiment_for 是衰减计数
# 比值，一条辱骂就能把裸比值砸下几十展示分——照裸值出卡等于给单条消息刷屏攻击
# 开直通车。修法只动**展示值**：滚动 24h 窗内相对窗口峰值的下行幅度 ≤ 本常量
# （展示分）；上行不限（回暖即时可见），内部真值与好感档位零触碰。量级对齐
# 好感展示面的既有日额度纪律（v8 日额度 0.04z ≈ 每日数展示分，同一把「一天挪
# 不了几分」的尺）。数值规范零触碰（docs/affinity-design.md 为唯一权威）：
# 本段只新增「展示读数判据」，不改任何好感度数值/步长/回归/半衰常量。
_SENTIMENT_DISPLAY_DAILY_DROP_CAP = 4.0
#: 展示落账表名（同库寄生，家规＝CREATE IF NOT EXISTS、禁 DROP；>48h 行写入时 prune）。
SENTIMENT_DISPLAY_LOG_TABLE = "sentiment_display_log"

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
_V7_DEFAULT_NEGATIVE_EVENT_CAP_Z = 0.10  # 单事件 |Δz| 上限（A-1 裁定后正负同额，键名历史见 V7Settings）
_V7_DEFAULT_DAILY_MOVE_CAP_Z = 0.04     # 滚动 24h 总位移上限 |ΣΔz|（2026-10-03 用户裁定消除双源：v7/v8 共键同值，与 config.py/.env 对齐；A-1 裁定：旧「本地自然日」窗形作废）
_V7_DEFAULT_FUSE_DAILY_EVENTS = 25      # 同类信号每日熔断事件数（超出不再计分）
_V7_DEFAULT_REPAIR_GAIN = 1.4           # 修复通道（道歉/和解）步长加成
_V7_DEFAULT_Z_HARD_BOUND = 0.985        # v8 起语义变迁：由「tanh 饱和域硬边界（展示 ±98.5）」
                                        # 改为 v8 边际递减 γ 的半衰减参考点（half=z_hard，
                                        # |z|=half 处步进恰为半额）。更新处不再按此截断，
                                        # 仅存量惰性映射仍按此钳位（零迁移口径不变）。
# v8（2026-09-27「边际递减 + 长尾」）：长尾表示域护栏——z 更新只保留浮点表示
# 域兜底 atanh(0.999999)≈7.2538，展示分严格落于 (−99.9999, +99.9999)。此域远
# 宽于 8 档态度表的最高档界（|s|>97 区间），档位判定与既有单事件帽/滚动位移帽
# （γ≤1 使其上界逐点收紧、从不放宽）均不受影响。非第 13 枚配置键——护栏尺度
# 仍以在册 12 键为唯一调节面（本值为模块常量，同 _V7_NOVELTY_FLOOR 先例）。
_V8_DISPLAY_DOMAIN_BOUND = 0.999999
_V8_Z_REPR_DOMAIN = math.atanh(_V8_DISPLAY_DOMAIN_BOUND)
# novelty 下限（席位修正量，设计稿 §二 数学不自洽的对账，见 WP7 日志 C-1）：
# 0.90^n 在持续互动稳态（日均 10 句好话 n≈303）会指数归零、把关系永久冻结在
# ~36 分，令设计自证的「要到 80 分需要以周为月的持续高质量互动」不成立。
# 下限 0.02 使持续高质量互动以 ≈0.6 分/天 缓涨（数月达 80+），同时
# 「每天 10 句好话 ×10 天 ≈ 30~40 分」的验收场景 1 逐字成立（实测模拟 34-37）。
# 非第 13 枚配置键——护栏尺度仍以在册 12 键为唯一调节面。
_V7_NOVELTY_FLOOR = 0.02
# rhythm 活跃度 EMA 半衰（天）：设计 §2.2「近 28 天日均互动轮次」。
_V7_RHYTHM_HALFLIFE_DAYS = 28.0

# ---- v8 第二腿常量（S-FIX-AFF-ALGO 席，2026-09-27 任务 #28：边际递减 + 长尾的
# 结构界形态；规格 docs/affinity-design.md §C.2/§C.4/§C.5.1/§C.7）----
# 每轮一个凸组合冲量：|δ_z| ≤ κ 由构造给出（Σ|w|=1 归一化），不是事后 if-list；
# 缺省灰度关死（enabled=False ⇒ v5/v6/v7 路径逐字节不变，与 v7 同一家规）。
_V8_DEFAULT_IMPULSE_CAP_Z = 0.02       # κ：每轮最大位移（§C.2，展示最坏 2.0 分/轮）
_V8_DEFAULT_DAILY_MOVE_CAP_Z = 0.04    # 日额度沿用 bot_affinity_daily_move_cap_z 键，v8 缺省 0.04（§C.7）
_V8_DEFAULT_AMBIENT_HALFLIFE_DAYS = 28.0  # āmbient 质量基线 EMA 半衰（§C.2 之 φ_q 去基线）
_V8_DEFAULT_BAND_MIN = 2.60            # 善意底保护带·新人端（≈全谱，fail-open 端；§C.4 散文语义）
_V8_DEFAULT_BAND_MAX = 0.55            # 善意底保护带· saturation 端（一年以上关系最多回落到峰值减此带）
_V8_DEFAULT_BAND_SATURATE_DAYS = 365.0 # 保护带随相处时长的饱和天数
# 换形裁定（2026-09-28 S-FIX-AFF-ALGO 协调指令）：band 由线性折线改为
# **凸递减半衰形态**——saturate_days 语义 =「离底线收敛到 1/2^FOLDS 跨度所需的
# 天数」，带半衰 τ_band = saturate_days / FOLDS（缺省 365/3）。纯指数无折点，
# 与 ambient/γ 同一长尾家族；FOLDS 是形状换算常数、非第 14 枚配置键。
_V8_BAND_SATURATE_FOLDS = 3.0
_V8_DEFAULT_TIER_BLEND_EDGE = 0.25     # 档内 λ 混合边缘（§C.5.1：λ∈[edge,1−edge] 单档原句）
# 六信号权重缺省：φ_q/φ_t/φ_r/φ_x/φ_a/φ_c。Σ=1.00；φ_c 的额度从 φ_q 的 0.40 中出
# （w1_eff=0.30、wc=0.10，§C.2 权重纪律「不新增第 7 个自由度」）。
_V8_DEFAULT_IMPULSE_WEIGHTS: tuple[float, float, float, float, float, float] = (
    0.30, 0.25, 0.15, 0.10, 0.10, 0.10,
)
# 事件质量分入 āmbient 的 EMA 步长（半衰之外的"每次见面各信一半"，确定性常数）。
_V8_AMBIENT_EMA_ALPHA = 0.5
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


def _finite_float_or(raw: Any, default: float) -> float:
    """把任意来源值洗成**有限** float，洗不出来（None / 非数文本 / NaN / ±inf）回退 default。

    为什么必须连 NaN 与 ±inf 一起拦：`min`/`max` 对 NaN 的比较恒 False，
    `max(-b, min(b, nan))` 会**静默产出 +b**——一条脏行因此被读成"独一份"顶格好感，
    这正是本模块结构上要杜绝的"瞬间巨变"；±inf 同型（且会顺着 `new_z - z` 反噬成
    -inf 写进增量日志）。数值规范零触碰：合法有限值逐字节恒等返回。
    """
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return float(default)
    if math.isnan(value) or math.isinf(value):  # NaN / ±inf
        return float(default)
    return value


def coerce_affinity_fraction(raw: Any, *, default: float = _AFFINITY_BASE) -> float:
    """库内 `affinity` 列（内部展示值 ∈ [-1,1]）的唯一消毒读口。

    旧形态是两处裸 `float(row["affinity"])`：脏值当场抛 TypeError/ValueError，
    而 `snapshot()` 是每轮对话的 prompt 注入面、`_observe()` 在入站链路上——
    一行脏数据等于把整条聊天链路打挂。本口判据：非数→default、NaN/±inf→default、
    合法有限值（含越界的 1.375 这类历史脏形）原样透传，由下游既有钳位处理，
    故正常行的行为逐字节不变（守恒锁 test_v7_legacy_rows_conserve_scores 不破）。
    """
    return _finite_float_or(raw, default)


def coerce_optional_float(raw: Any) -> float | None:
    """可空实数列（`z_latent` / `first_impression`）的唯一消毒读口。

    返回 None 的语义就是"这一格没有可用值"——与列本身为 NULL 时**完全同一条路**：
    `z_latent` 走 §三.1 惰性补齐（按 affinity 列现推，绝不重置），`first_impression`
    走"未定盘"（建档窗口继续收集）。旧形态是 `if raw is not None: float(raw)`——
    NULL 挡住了，非数文本与 NaN/±inf 没挡住，当场抛进 `_observe`（入站链路）。
    """
    if raw is None:
        return None
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def coerce_override_delta(raw: Any) -> float | None:
    """`delta_override`（权威信号）的唯一消毒口（需求项 13 + 裁定 D3）。

    None＝调用方本来就带自然行为分，原样透传；非有限脏值（NaN/±inf/非数文本）
    ⇒ 0.0＝**本次不计分**——与「预算耗尽记 0」既有语义同族：计数器/标签照常，
    不落增量日志、不占冷却坑。绝不沿用旧形态：NaN 顺流进 `min/max` 比较链
    （NaN 的一切比较恒 False）会静默产出错误的钳制结果——v7 路 `min(z_hard,
    z+nan)` 返回 z_hard 本身（一发顶到 +98.5），v5 路把 NaN 绑进 NOT NULL 的
    delta 列当场 IntegrityError。合法有限值逐字节恒等返回 ⇒ 任何人的现存
    分数与既有行为零变化。
    """
    if raw is None:
        return None
    return _finite_float_or(raw, 0.0)


def affinity_after_move(current: float, delta: float) -> float:
    """落库前的末道闸：`clamp(current + delta, ±1)`，且**非有限残差 ⇒ 原地不动**。

    对合法输入与旧式 `max(-1.0, min(1.0, current + delta))` 逐字节等价（含边界
    钳位）；只有当上游某道消毒被绕开、和式仍非有限时，本闸才改变结果——此时
    诚实的行为是"这一发没发生"（保持 current），而不是让 NaN 的比较陷阱把
    钳制翻成 ±1（= 展示 ±100 的瞬间巨变）或把脏值写进库里。
    """
    moved = float(current) + float(delta)
    if not math.isfinite(moved):
        return max(-1.0, min(1.0, float(current)))
    return max(-1.0, min(1.0, moved))


def v7_z_to_display_fraction(z: float) -> float:
    """v7 §2.1 映射：潜变量 z → 内部展示值 a=tanh(z)（×100 仍走 normalize_legacy_points）。"""
    return math.tanh(_finite_float_or(z, 0.0))


def v7_display_fraction_to_z(
    affinity: Any, bound: Any = _V7_DEFAULT_Z_HARD_BOUND
) -> float:
    """v7 §三.1 惰性迁移映射：z = atanh(clamp(score/100 内部值, −bound, +bound))。

    存量 ±1 极端值被钳到 ±atanh(bound)（±98.5 展示分）——设计写明的域上界，
    其余值逐点守恒（atanh 单调），绝不重置任何人。

    本函数是全模块唯一"分数量纲 → z 量纲"的入口，故三态在此一次收口（T-AFF-1）：
    ① `bound` 自身先钳进 [0.5, 0.999999] ⇒ `atanh` 的定义域**结构上永不触边**
    （旧形态：调用方直传 bound=1.0 会当场 `ValueError: math domain error`）；
    ② 非数输入（None/文本）与 ③ NaN/±inf 一律按基数档 `default=_AFFINITY_BASE` 处理
    （= 友善基准 10 分），**不抛、不产 ±inf、也不钳成顶格 +98.5**——与
    :func:`coerce_affinity_fraction` 同一口径，两条读库路径不会给出两个答案。
    """
    safe_bound = min(0.999999, max(0.5, _finite_float_or(bound, _V7_DEFAULT_Z_HARD_BOUND)))
    value = _finite_float_or(affinity, _AFFINITY_BASE)
    return math.atanh(max(-safe_bound, min(safe_bound, value)))


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


def v8_marginal_gain(z: Any, half_z: Any) -> float:
    """v8（2026-09-27「边际递减 + 长尾」）边际递减系数 γ(|z|) = half/(half+|z|)。

    γ ∈ (0, 1]、只依赖 |z|（正负对称）、随 |z| 严格单调递减：|z|=half 处恰为
    半额步进，越高（或越低）每一分增益的边际越小。half 取 z_hard（旧 ±98.5
    硬界点改为半衰减参考点），经配置键 bot_affinity_v7_z_hard_bound 在册可调。
    γ≤1 是护栏不变量的锚：单事件帽与滚动 24h 位移帽作用于 γ 缩放后的增量，
    其界外上界只收紧、从不放宽——「禁瞬间剧烈加/减」在任何档位恒成立。
    消毒口径与邻居纯函数一致：非有限入参经 `_finite_float_or` 归 0；
    half≤0（脏配置/误用）⇒ γ≡1.0，退化为 v7 原行为而非停机或巨变。
    """
    z_value = _finite_float_or(z, 0.0)
    half = _finite_float_or(half_z, 0.0)
    if half <= 0.0:
        return 1.0
    return half / (half + abs(z_value))


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
    # negative_event_cap_z：键名历史含义是「只钳负向」——2026-09-26 A-1 裁定起
    # **语义已扩到双向**（单事件 |Δz| 上限，正负同额，override 面与普通计分面同尺）。
    # 为什么不新增一枚 `positive_event_cap_z`：①她的裁定要的是「正向单事件帽与负向
    # 对称起步」，不对称缺省没有任何在册需求，多一枚旋钮=多一条可被单独调松的泄口
    # （`v7_structural_guard_report` 逐枚体检护栏，两枚帽还得各写各的越界点名）；
    # ②`bot_affinity_negative_event_cap_z` 已四处同生（config/catalog/.env.example/
    # env 现读口），换名或加名都要动那三面共享件，为语义扩展付键迁移的代价不值；
    # ③本模块「少旋钮、单一真身」家规（缺省值以本 dataclass 为单一事实源）。
    negative_event_cap_z: float = _V7_DEFAULT_NEGATIVE_EVENT_CAP_Z
    # daily_move_cap_z：窗形=滚动 24h（从 affinity_delta_log 现读），不再是本地自然日桶。
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
        """Z_HARD = atanh(z_hard_bound)：v8 起为边际递减 γ 的半衰减参考点（half）。

        v7 原语义是更新处的硬截断界；v8（2026-09-27「边际递减 + 长尾」）把更新处
        的截断换成 `_V8_Z_REPR_DOMAIN` 表示域护栏，本值改为 `v8_marginal_gain` 的
        half 入参（|z|=half 处步进恰为半额），同时仍是存量惰性映射的钳位界
        （零迁移口径）。消毒口不变：界钳制与 `v7_display_fraction_to_z` 同一条
        （[0.5, 0.999999]）+ 同一个非抛式消毒口——它能抛/能产出 inf 的那天，
        γ 与映射两路都会变成"瞬间巨变"的现场而不是防线。
        """
        bound = min(0.999999, max(0.5, _finite_float_or(self.z_hard_bound, _V7_DEFAULT_Z_HARD_BOUND)))
        return math.atanh(bound)

    def novelty_tau_days_for(self, behavior: str) -> float:
        tier = _V7_DECAY_TIER_FOR_BEHAVIOR.get(behavior, "seasonal")
        try:
            value = float(self.decay_tau_days.get(tier, self.novelty_halo_days))
        except (TypeError, ValueError, AttributeError):
            value = float(self.novelty_halo_days)
        return max(0.5, value)


def coerce_json_list(raw: Any) -> list[Any]:
    """JSON 列表列（`impression_tags` / `profile_notes` / `first_signals`）消毒读口。

    与分数列同一条判据：这些列的读点也在**每轮对话**的 `snapshot()`/`_observe()`
    上，一行 `'['` 就能把入站链路打断。解析失败或形状不是 list ⇒ 空表，
    语义 = "该维度没有记录"，与列本就为 `'[]'` 时同形。
    """
    try:
        data = json.loads(str(raw or "[]"))
    except (ValueError, TypeError):
        return []
    return data if isinstance(data, list) else []


def coerce_json_mapping(raw: Any) -> dict[str, Any]:
    """JSON 字典列（`day_counters` / `impression_tag_times`）消毒读口，同 `coerce_json_list`。"""
    try:
        data = json.loads(str(raw or "{}"))
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def coerce_int(raw: Any, default: int = 0) -> int:
    """整数列（各计数与 `counter_day_index`）消毒读口；非数回退 default，绝不抛。

    合法整数逐字节恒等（`int(x)` 对 int 是恒等），故既有回归口径零变化。
    """
    value = _finite_float_or(raw, float(default))
    try:
        return int(value)
    except (OverflowError, ValueError):  # pragma: no cover - ±inf 已在上一行挡掉
        return int(default)


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


def _v7_warn_once(
    key: str,
    detail: str,
    *,
    problem: str = "非法",
    outcome: str = "按代码缺省执行",
    family: str = "v7",
) -> None:
    """配置面点名口（进程内每键只报一次，避免每条消息刷日志）。

    `problem`/`outcome` 单独成参，是因为并非所有点名都以"取值非法 → 回退缺省"收场：
    需求项 13 的位移上限越界只点名、不改值（值本身合法，越界的是它带来的结构性
    性质）。两个参数都取旧措辞为缺省，既有五个调用点的输出逐字节不变。
    `family` 同理：缺省 "v7" 保持既有日志逐字节不变，v8 点名族传 "v8"。
    """
    with _V7_WARNED_LOCK:
        first = key not in _V7_WARNED_KEYS
        if first:
            _V7_WARNED_KEYS.add(key)
    if first:
        import logging

        logging.getLogger(__name__).warning(
            "好感度 %s 配置键 %s %s（%s），%s", family, key, problem, detail, outcome
        )


def _v7_env_value(field_name: str, default: Any, *, family: str = "v7") -> Any:
    """无 config 句柄时的逐调用 env 现读（生产 .env 经 nonebot 装载进环境）。

    字段名即 env 名大写（``bot_affinity_v7_enabled`` ⇄ ``BOT_AFFINITY_V7_ENABLED``，
    与 translate_env_keys 的双向口径一致）。v8 复用本读口（同一 env 装载事实，
    禁第二通路），`family` 只影响点名归属。
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
            _v7_warn_once(field_name, f"数值解析失败：{raw!r}", family=family)
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

    settings = V7Settings(
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
    # T-AFF-1（需求项 13）：位移护栏一旦被调到"一次就能跨两档"的量级，本模块的
    # 逐档性就不再成立——**点名一次，但不静默改值**（配置面是该尺的唯一真身，
    # 代码偷偷夹回来等于造第二真身）。缺省 0.10/0.04（登记常量现值）远低于临界
    # atanh(0.25)≈0.2554，
    # 故此分支在现网与全部在册测试形态下都不触发；判据见 v7_structural_guard_report。
    if not (report := v7_structural_guard_report(settings))["ok"]:
        _v7_warn_once(
            "v7_move_cap_beyond_one_tier",
            "位移上限越过单档临界值，档号可能一次跳档："
            f"{report['caps']}（临界 cap<={report['one_tier_ceiling_z']:.4f}）"
            f"→ 最大跨档 {report['max_tier_step']}",
            problem="取值过松（数值本身合法）",
            outcome="仅点名、不静默改值——配置面是这把尺的唯一真身",
        )
    return settings


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
    修复通道对正向 ×repair_gain；单事件 |Δz| ≤ negative_event_cap_z
    （A-1 裁定：正负同帽——修复 ×1.4 加成后同样被帽咬住，键名历史含义已扩到双向）。"""
    delta = settings.base_step * q * novelty * rhythm * mood * impression
    if repair and delta > 0.0:
        delta *= settings.repair_gain
    if delta < 0.0:
        delta = max(delta, -settings.negative_event_cap_z)
    elif delta > 0.0:
        delta = min(delta, settings.negative_event_cap_z)
    return delta


# ============================================================================
# ---- v8 第二腿：每轮凸组合冲量 + 善意底 + 带内混合（规格：docs/affinity-design.md
# §C.2/§C.3/§C.4/§C.5.1/§C.7；S-FIX-AFF-ALGO 席 2026-09-27）----
# 与第一腿（γ 边际递减 + 长尾表示域，commit b2a2267 已落 v7 路径）互补：本腿把
# 「界」从"事后 if-list"迁到"数学构造"——Σ|w_i|=1 归一 ⇒ |u|≤1 ⇒ |δ_z|≤κ，
# 删掉任何事后 clamp 都不破坏此界（设计 §F 每轮界判据的牙齿）。
# 灰度：bot_affinity_v8_enabled 缺省 False ⇒ v5/v6/v7 路径逐字节不变、可一键回退。
# 键登记现状（2026-10-03 本席复核后更新，原「四处待补」注释已过期）：config.py
# 字段已全部登记（config.py:381-394，含善意带三键 + 日额度），.env.example 亦已
# 登记（:1146 起）；RESTART_REQUIRED_KEYS / 命令 catalog 尚未收录 v8 键——v8 面
# 走逐调用现读口，本就不设热改面，未收录即「不可热改」，语义安全；拨闸形态 =
# 环境变量 + 重启（与 v7 同路）。
# ============================================================================

_V8_CONFIG_FIELDS: tuple[tuple[str, Any], ...] = (
    ("bot_affinity_v8_enabled", False),
    ("bot_affinity_v8_impulse_cap_z", _V8_DEFAULT_IMPULSE_CAP_Z),
    ("bot_affinity_v8_impulse_weights", ""),
    ("bot_affinity_v8_ambient_centering", True),
    ("bot_affinity_v8_ambient_halflife_days", _V8_DEFAULT_AMBIENT_HALFLIFE_DAYS),
    # 善意带三键 env 名按 2026-09-28 S-FIX-AFF-ALGO 裁定：BOT_AFFINITY_GOODWILL_BAND_*
    # （不带 V8 段——她是按「好感度面」配置的，不是按算法代数配置的）。
    ("bot_affinity_goodwill_band_min", _V8_DEFAULT_BAND_MIN),
    ("bot_affinity_goodwill_band_max", _V8_DEFAULT_BAND_MAX),
    ("bot_affinity_goodwill_band_saturate_days", _V8_DEFAULT_BAND_SATURATE_DAYS),
    ("bot_affinity_v8_tier_blend_band", _V8_DEFAULT_TIER_BLEND_EDGE),
    # 日额度沿用在册键（§C.7：枚数以四处登记后现算为准）；2026-10-03 用户裁定消除
    # 双源：v8 缺省与 v7 缺省同为 0.04（_V8/_V7_DEFAULT_DAILY_MOVE_CAP_Z 两常量同值），
    # env 显式给了就同吃一值——两路各自的缺省是"没配置时"的答案。
    ("bot_affinity_daily_move_cap_z", _V8_DEFAULT_DAILY_MOVE_CAP_Z),
)


def v8_normalize_weights(raw: Any) -> tuple[float, ...] | None:
    """§C.2 权重纪律：六信号权重解析 + `Σ|w_i| = 1` 构造归一（越界⇒整体归一化）。

    接受 list/tuple（六位）或 dict（w1..w6）。非数/长度错/全零 ⇒ None（调用方
    回退代码缺省并点名）；Σ|w|≠1 **不拒绝**——就地归一（归一是构造性界源，
    拒绝反而丢掉"越界即整体归一化 + 点名"的在册语义）。
    """
    try:
        data = json.loads(str(raw)) if isinstance(raw, str) else raw
        if isinstance(data, dict):
            seq = [float(data[f"w{i}"]) for i in range(1, 7)]
        elif isinstance(data, (list, tuple)) and len(data) == 6:
            seq = [float(x) for x in data]
        else:
            return None
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None
    if any(not math.isfinite(x) for x in seq):
        return None
    total = sum(abs(x) for x in seq)
    if total <= 0.0:
        return None
    if abs(total - 1.0) > 1e-9:
        seq = [x / total for x in seq]
    # 不四舍五入：round(x,6) 会把 Σ|w|=1 的构造界撬成 1±1e-6·6，|u|≤1 的
    # 数学界（引理 1）要求逐元素全精度保留——展示层要干净数字另在 dump 处取整。
    return tuple(seq)


def v8_impulse(
    phis: tuple[float, float, float, float, float, float],
    weights: tuple[float, ...],
) -> float:
    """§C.2 凸组合冲量 u = Σ w_i·φ_i ∈ [−1, +1]（引理 1 的构造面）。

    φ 顺序：q 互动质量 / t 情感温度 / r 尊重边界 / x 敌意伤害 / a 修复意图 /
    c 在场连续性。判入先各钳 [−1,1]（φ 值域是规格的，钳它＝消毒不是新机制）；
    权重再归一一次（幂等——resolve 已归一，此口防直调用带生权重）。
    **界来自数学**：|u| ≤ Σ|w_i|·max|φ_i| ≤ 1，与命中多少信号、是否 repair 无关；
    删掉归一化此行测试必红（tests/test_aff_algo_v8_core.py 注毒自证）。
    """
    try:
        phi = [max(-1.0, min(1.0, _finite_float_or(x, 0.0))) for x in phis]
    except TypeError:
        return 0.0
    weights = v8_normalize_weights(weights) or _V8_DEFAULT_IMPULSE_WEIGHTS
    if len(weights) != 6:
        weights = _V8_DEFAULT_IMPULSE_WEIGHTS
    return sum(w * p for w, p in zip(weights, phi))


def v8_ambient_update(
    ambient: float,
    ambient_at: float,
    now: float,
    q: float,
    *,
    halflife_days: float,
    alpha: float = _V8_AMBIENT_EMA_ALPHA,
) -> tuple[float, float]:
    """āmbient（本人质量基线 EMA，§C.2 之 φ_q 去环境基线）的一步转移。

    两段式，全为长尾形态服务：
    1) 时间半衰：先按 `ambient · 0.5^(Δt/τ)` 向 0（无信号=印象回归中性）衰减——
       长期无互动的读数形状即此：单调、指数、半衰期=τ、渐近不过冲、无折点；
    2) 事件 EMA：再以固定步长 α 向本次 q 收拢 `a ← (1−α)·a + α·q`。
    返回值钳 [−1,1]（q 值域 [−1,1]，凸组合保持）；脏入参经 _finite_float_or 归口。
    """
    a = _finite_float_or(ambient, 0.0)
    at = _finite_float_or(ambient_at, 0.0)
    t = _finite_float_or(now, 0.0)
    tau = max(0.5, _finite_float_or(halflife_days, _V8_DEFAULT_AMBIENT_HALFLIFE_DAYS))
    if t > at:
        a *= 0.5 ** ((t - at) / (tau * _DAY_SECONDS))
    step = max(0.0, min(1.0, _finite_float_or(alpha, _V8_AMBIENT_EMA_ALPHA)))
    a = (1.0 - step) * a + step * _finite_float_or(q, 0.0)
    return max(-1.0, min(1.0, a)), t


def v8_quality_centered(q: float, ambient: float) -> float:
    """φ_q = (q − āmbient) / (1 − |āmbient|)，钳 [−1,1]（§C.2 表第 1 行）。

    去环境基线后，"一贯敷衍"与"一贯真诚"的期望冲量都归 0 附近——低质量闲聊
    不再复利（设计 §C.2「为什么低质量闲聊不再复利」）。分母下限 1e-6：
    |āmbient|→1 的贴边脏态不放大爆冲（分子同向趋零，比值仍有界）。
    """
    value = _finite_float_or(q, 0.0)
    a = max(-1.0, min(1.0, _finite_float_or(ambient, 0.0)))
    den = max(1e-6, 1.0 - abs(a))
    return max(-1.0, min(1.0, (value - a) / den))


def v8_continuity(
    last_day_start: float | None,
    streak_days: int,
    now_day_start: float,
) -> tuple[int, float]:
    """φ_c 在场连续性（§C.2 表第 6 行）：**每天只计一次**、`min(1, 连续天数/7)`。

    返回 `(新连续天数, φ_c)`。判据按本地日界（与 day_counters 同口径，由调用方
    传入当日零点时间戳）：同日重复 ⇒ (原样, 0)（当天已计过）；隔一日 ⇒ +1；
    断档更久或脏历史 ⇒ 重置为 1。到场有分量、刷条数没分量——唯一稳定为正的
    分量按**天**计，这是「陪伴」的数值形状。
    """
    prev = last_day_start
    if prev is None or not math.isfinite(_finite_float_or(prev, float("nan"))):
        n = 1
    else:
        diff_days = int((now_day_start - float(prev)) // _DAY_SECONDS)
        if diff_days == 0:
            return max(1, coerce_int(streak_days, 1)), 0.0
        n = coerce_int(streak_days, 0) + 1 if diff_days == 1 else 1
    return n, min(1.0, n / 7.0)


def v8_goodwill_band(
    days: float | None,
    *,
    band_min: float = _V8_DEFAULT_BAND_MIN,
    band_max: float = _V8_DEFAULT_BAND_MAX,
    saturate_days: float = _V8_DEFAULT_BAND_SATURATE_DAYS,
) -> float:
    """§C.4 保护带 band(days)：BAND_MIN → BAND_MAX 的**凸递减半衰形态**。

    ``band(days) = band_max + (band_min − band_max) · 2^(−days / τ_band)``,
    ``τ_band = saturate_days / _V8_BAND_SATURATE_FOLDS``（缺省 365/3 ≈ 121.7 天）。
    形态判据（本席数值锁 tests/test_affinity_v8_band.py）：
    - 凸递减、无折点：纯指数曲线（非分段），二阶差分恒 >0、一阶差分单调趋零；
      线性斜坡在饱和点有斜率断口，2026-09-28 协调裁定换为此形态——与
      ambient 半衰（0.5^(Δt/28d)）、γ 边际递减同属一个长尾家族；
    - band(0)=band_min=2.60：≈全谱，起点不是惩罚（新人可一路回到初识）；
    - days→∞ 渐近 band_max=0.55 且**恒 > band_max**：老关系的底线只可逼近、
      不可击穿，「处得越久，峰值越不可回吐」；band(saturate) 收敛到距底线
      1/8 跨度内（fail-tight，无需钳位截断即单调）；
    - `days` 取不到（created_at 解析失败）⇒ 回 band_min（fail-open 到旧行为）。
    ⚠ 设计 §C.4 首行公式与自身散文正反两读、且给的是线性形；本函数取
    散文义 + 2026-09-28 凸形裁定，勘误与换形已在交付日志登记
    （契约标识符 BAND_MIN/BAND_MAX/BAND_SATURATE_DAYS 不改名）。
    """
    lo = max(0.0, _finite_float_or(band_min, _V8_DEFAULT_BAND_MIN))
    hi = max(0.0, _finite_float_or(band_max, _V8_DEFAULT_BAND_MAX))
    # 配置倒挂（底线高于起点）⇒ 按无保护处理，绝不产生负带宽度的反向曲线。
    hi = min(hi, lo)
    sat = max(1.0, _finite_float_or(saturate_days, _V8_DEFAULT_BAND_SATURATE_DAYS))
    if days is None or not math.isfinite(_finite_float_or(days, float("nan"))):
        return lo
    d = max(0.0, float(days))
    half_life = sat / _V8_BAND_SATURATE_FOLDS
    return hi + (lo - hi) * 0.5 ** (d / half_life)


def v8_goodwill_anchor(anchor_prev: float | None, z_new: float, band: float) -> float:
    """§C.4 善意底：anchor ← max(anchor_prev, z_new − band)（单调不减），
    落点 z = max(z_new, anchor)。只抬下界、绝不改写既有 z——「这段关系曾经到过
    的地方」越久越不可被回吐（推论 4）。脏 anchor_prev ⇒ 视作无历史（现推）。
    """
    candidate = _finite_float_or(z_new, 0.0) - max(0.0, _finite_float_or(band, 0.0))
    prev = coerce_optional_float(anchor_prev)
    return candidate if prev is None else max(prev, candidate)


@dataclass(frozen=True)
class V8Settings:
    """v8 生效参数的逐调用快照（冻结视图，缺省=代码单一事实源；§C.7）."""

    enabled: bool = False
    impulse_cap_z: float = _V8_DEFAULT_IMPULSE_CAP_Z
    daily_move_cap_z: float = _V8_DEFAULT_DAILY_MOVE_CAP_Z
    ambient_centering: bool = True
    ambient_halflife_days: float = _V8_DEFAULT_AMBIENT_HALFLIFE_DAYS
    goodwill_band_min: float = _V8_DEFAULT_BAND_MIN
    goodwill_band_max: float = _V8_DEFAULT_BAND_MAX
    goodwill_band_saturate_days: float = _V8_DEFAULT_BAND_SATURATE_DAYS
    tier_blend_edge: float = _V8_DEFAULT_TIER_BLEND_EDGE
    impulse_weights: tuple[float, float, float, float, float, float] = (
        _V8_DEFAULT_IMPULSE_WEIGHTS  # type: ignore[assignment]
    )

    def band_for(self, days: float | None) -> float:
        return v8_goodwill_band(
            days,
            band_min=self.goodwill_band_min,
            band_max=self.goodwill_band_max,
            saturate_days=self.goodwill_band_saturate_days,
        )


def resolve_v8_settings(config: Any) -> V8Settings:
    """逐调用现读 v8 增量键（家规同 resolve_v7_settings：config 缺句柄 ⇒ env 现读）。

    非法值 ⇒ 代码缺省 + 每键每进程点名一次；尺度类做域钳制。结构性护栏：
    κ、日额度任一被调到"能一次跨档/一天跨档"的量级 ⇒ 点名（复用 v7 的逐档判据
    v7_max_tier_step_for_z_cap，档宽真身同一把尺），不改值——配置面是唯一真身。
    """
    source = config() if callable(config) else config

    def value_of(field_name: str, default: Any) -> Any:
        if source is None:
            return _v7_env_value(field_name, default, family="v8")
        raw = getattr(source, field_name, None)
        if raw is None:
            return _v7_env_value(field_name, default, family="v8")
        return raw

    def positive_float(field_name: str, default: float) -> float:
        try:
            value = float(value_of(field_name, default))
        except (TypeError, ValueError):
            _v7_warn_once(field_name, "非数值", family="v8")
            return default
        if value <= 0.0 or not math.isfinite(value):
            return default
        return value

    weights_raw = value_of("bot_affinity_v8_impulse_weights", "")
    weights: tuple[float, ...] | None = None
    if str(weights_raw or "").strip():
        weights = v8_normalize_weights(weights_raw)
        if weights is None:
            _v7_warn_once("bot_affinity_v8_impulse_weights", f"JSON 非法：{weights_raw!r}", family="v8")
    if isinstance(weights_raw, (list, tuple, dict)) and weights is not None:
        # 非字符串输入给了 Σ|w|≠1 的生权重：已在构造函数归一——点名一次留痕。
        _v7_warn_once(
            "bot_affinity_v8_impulse_weights",
            "Σ|w|≠1，已按构造整体归一",
            problem="越界",
            outcome="归一后执行（构造界不破坏）",
            family="v8",
        )

    settings = V8Settings(
        enabled=_v7_coerce_bool(value_of("bot_affinity_v8_enabled", False), False),
        impulse_cap_z=min(0.25, positive_float(
            "bot_affinity_v8_impulse_cap_z", _V8_DEFAULT_IMPULSE_CAP_Z)),
        daily_move_cap_z=min(0.5, positive_float(
            "bot_affinity_daily_move_cap_z", _V8_DEFAULT_DAILY_MOVE_CAP_Z)),
        ambient_centering=_v7_coerce_bool(
            value_of("bot_affinity_v8_ambient_centering", True), True),
        ambient_halflife_days=max(0.5, positive_float(
            "bot_affinity_v8_ambient_halflife_days", _V8_DEFAULT_AMBIENT_HALFLIFE_DAYS)),
        goodwill_band_min=positive_float(
            "bot_affinity_goodwill_band_min", _V8_DEFAULT_BAND_MIN),
        goodwill_band_max=positive_float(
            "bot_affinity_goodwill_band_max", _V8_DEFAULT_BAND_MAX),
        goodwill_band_saturate_days=max(1.0, positive_float(
            "bot_affinity_goodwill_band_saturate_days", _V8_DEFAULT_BAND_SATURATE_DAYS)),
        tier_blend_edge=min(0.45, max(0.05, positive_float(
            "bot_affinity_v8_tier_blend_band", _V8_DEFAULT_TIER_BLEND_EDGE))),
        impulse_weights=(
            tuple(weights) if weights is not None and len(weights) == 6  # type: ignore[arg-type]
            else _V8_DEFAULT_IMPULSE_WEIGHTS
        ),
    )
    # 逐档性体检（缺省 κ=0.02/D=0.04 远低于临界，现网与在册测试形态零触发）：
    # 越界只点名、不改值——与 v7 的 T-AFF-1 同一哲学、同一判据函数。
    caps = {
        "impulse_cap_z": settings.impulse_cap_z,
        "daily_move_cap_z": settings.daily_move_cap_z,
    }
    if any(v7_max_tier_step_for_z_cap(value) > 1 for value in caps.values()):
        _v7_warn_once(
            "v8_move_cap_beyond_one_tier",
            f"位移上限越过单档临界值，档号可能一次跳档：{caps}"
            f"（临界 cap<={_V7_ONE_TIER_Z_CEILING:.4f}）",
            problem="取值过松（数值本身合法）",
            outcome="仅点名、不静默改值——配置面是这把尺的唯一真身",
            family="v8",
        )
    return settings


def _v8_sentiment_phi(text: str) -> float:
    """φ_t 情感温度：_POSITIVE_RE/_NEGATIVE_RE/_INSULT_RE 命中密度折符号（§C.2 表
    第 2 行）。辱骂双权（与 sentiment 半衰口径同向）。值域 (−1,1)：分母恒比
    分子绝对值大 1，结构上到不了 ±1——但接口仍按 φ∈[−1,1] 登记，无副作用。
    词表全用既有真身正则，禁自建词表（§C.2 之 φ_r 纪律同源）。
    """
    value = text or ""
    pos = len(_POSITIVE_RE.findall(value))
    neg = len(_NEGATIVE_RE.findall(value))
    inso = len(_INSULT_RE.findall(value))
    return (pos - neg - 2 * inso) / (pos + neg + 2 * inso + 1)


def _v8_respect_phi(text: str, behavior: str) -> float:
    """φ_r 尊重边界（§C.2 表第 3 行）：礼貌词 +0.5；越界/敌意 −。
    tease 的越界判定**只读上游归类**（classify_behavior 把 excessive_intimacy/
    persona_breaking 归成 tease，本函数不建第二套 R-18 词表）。
    """
    if behavior == "insult":
        return -1.0
    if behavior in {"negative", "tease"}:
        return -0.5
    if _POLITE_RE.search(text or ""):
        return 0.5
    return 0.0


def _v8_hostility_phi(behavior: str) -> float:
    """φ_x 敌意伤害（§C.2 表第 4 行，值域 [−1,0]）：仅 insult 家族计负贡献。
    reason_code 门控（quoted_abuse/product_criticism 等非关系证据⇒不该进这里）
    的接线在生产被动感知入口（root __init__，非本席文件域，见交付日志「等他席」）；
    门未接前，行为归类沿用既有 safety_category 准入，与今天同源。
    """
    return -1.0 if behavior == "insult" else 0.0


def _v8_repair_phi(text: str, behavior: str) -> float:
    """φ_a 修复意图（§C.2 表第 5 行）：道歉/和解⇒1，否则 0。
    它不再放大步长（v7 的 repair_gain ×1.4 在 v8 退役为 u 的一个正分量），
    修复的"快"体现在足额吃 κ、而不越任何界（推论 3 之三）。"""
    return 1.0 if _v7_is_repair(text, behavior) else 0.0


def _v8_load_state(raw: str | None) -> dict[str, Any]:
    """解析 v8_state JSON（坏数据重置空态，绝不抛——家规同 _v7_load_state）。

    形态：{"amb":[值, 时刻], "pres":[上次在场日零点, 连续天数], "recent":[指纹…]}。
    在场历史另存 **updated_at 同款 UTC 串** 不必——用 epoch 秒即可（本地日界由
    调用方按 localtime 折算后传入）。
    """
    try:
        data = json.loads(str(raw or "{}"))
    except (ValueError, TypeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    amb = [0.0, 0.0]
    raw_amb = data.get("amb")
    if isinstance(raw_amb, (list, tuple)) and len(raw_amb) == 2:
        value = coerce_optional_float(raw_amb[0])
        at = coerce_optional_float(raw_amb[1])
        if value is not None and at is not None:
            amb = [max(-1.0, min(1.0, value)), max(0.0, at)]
    pres: list[Any] = [None, 0]
    raw_pres = data.get("pres")
    if isinstance(raw_pres, (list, tuple)) and len(raw_pres) == 2:
        pres = [coerce_optional_float(raw_pres[0]), coerce_int(raw_pres[1], 0)]
    recent = [str(x) for x in data.get("recent", []) if isinstance(x, str)][-_V8_RECENT_WINDOW:]
    return {"amb": amb, "pres": pres, "recent": recent}


def _v8_dump_state(state: dict[str, Any]) -> str:
    amb = state["amb"]
    pres = state["pres"]
    return json.dumps(
        {
            "amb": [round(float(amb[0]), 6), float(amb[1])],
            "pres": [pres[0], int(pres[1])],
            "recent": state["recent"][-_V8_RECENT_WINDOW:],
        },
        ensure_ascii=False,
    )



_V7_RECENT_WINDOW = 8  # 延展度复读检测的近期文本指纹数（有界，防状态无限增长）
# v8 复读指纹窗口沿用 v7 真身常量（禁第二尺；规则 10——引用不抄数）。
_V8_RECENT_WINDOW = _V7_RECENT_WINDOW


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
    # day：A-1 起只携带熔断计数（"i" 日界 + "c" 计数）；旧行的 "s"（自然日
    # 位移额度）在此被静默丢弃——位移额度唯一真身改读 delta_log 滚动 24h，
    # 存量 state 无需迁移（零搬运，读口宽容）。
    day: dict[str, Any] = {"i": -1, "c": {}}
    raw_day = data.get("day")
    if isinstance(raw_day, dict):
        try:
            raw_counts = raw_day.get("c")
            day = {
                "i": int(raw_day.get("i", -1)),
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
                "c": dict(state["day"]["c"]),
            },
            "recent": state["recent"][-_V7_RECENT_WINDOW:],
        },
        ensure_ascii=False,
    )

# ---- §4 档位表：线性 8 档，每档宽 25，档0=友善含基准 10；边界左闭右开（最高档含 +100）。
# 展示区间 = internal × 100；档 id -4..+3（v3 曾返回具名 id close/friendly/polite/distant，
# v4 改为整数档 id——向后兼容点，调用方以 providers.py 的 familiarity 映射为准）。
# 本表同时是**全树八档态度文案的唯一真身**（docs/affinity-design.md §4）：展示面
# （capabilities/affinity.py 算法卡档位表）一律由 attitude_tiers() 投影生成，不许再抄一份
# ——抄一份就会各自改词（友善档与独一份档曾实测分叉）。
# 常驻锁：tests/test_affinity_tier_single_source.py（副本再现=红 / 真身被删=红）。
_ATTITUDE_TIERS: tuple[tuple[int, str, str], ...] = (
    (-4, "初识", "初见不久的人：礼貌、克制、有问必答但不寒暄"),
    (-3, "生疏", "生疏的人：话少一截，依旧体面温和"),
    (-2, "微凉", "语气稍淡，不冷不热，就事论事"),
    (-1, "稍淡", "略淡于平时，但保持基本温柔"),
    (0, "友善（基准）", "温和、有陪伴感，记得对方的偏好"),
    (1, "亲近", "更主动的关心，记得对方说过的事"),
    (2, "挚友", "直接而温暖，可以用给对方起的小名"),
    # §4 文档原文这一格带「——依旧守全部安全边界」（docs/affinity-design.md §4 +3 行）：
    # 注入面曾漏抄半句，令展示面独自改词，现按文档补回，两面对最高档边界描述从此同句。
    (3, "独一份", "最珍视的人：全然温柔的陪伴——依旧守全部安全边界"),
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
_TIER_MIN_ID, _TIER_MAX_ID = _ATTITUDE_TIERS[0][0], _ATTITUDE_TIERS[-1][0]
_TIER_WIDTH_DISPLAY = 25.0  # §4 每档宽 25 展示分（档界由本常量算出，展示面不得自报区间）
_TIER_DISPLAY_FLOOR, _TIER_DISPLAY_CEILING = -100.0, 100.0  # §1 展示口径两端


def attitude_tiers() -> tuple[tuple[int, str, str], ...]:
    """§4 八档态度真身（档 id、档位名、态度指令全文），按档序 -4..+3。

    展示层唯一的取数口：算法卡的档位表从这里投影（含区间边界），
    除本函数出口外，全树不得再出现第二份八档态度句（常驻锁见
    tests/test_affinity_tier_single_source.py）。
    """
    return _ATTITUDE_TIERS


def tier_display_range(tier_id: int) -> str:
    """§4 档位的展示区间串（如 `[-100, -75)`、`[+75, +100]`）。

    边界左闭右开、最高档含 +100；0 不带正号（历史展示口径逐字节保持）。
    """
    if not _TIER_MIN_ID <= tier_id <= _TIER_MAX_ID:
        raise ValueError(f"未知档位 id：{tier_id}（合法区间 {_TIER_MIN_ID}..{_TIER_MAX_ID}）")
    low = int(_TIER_DISPLAY_FLOOR + _TIER_WIDTH_DISPLAY * (tier_id - _TIER_MIN_ID))
    high = int(low + _TIER_WIDTH_DISPLAY)

    def bound(value: int) -> str:
        return "0" if value == 0 else f"{value:+d}"

    closer = "]" if tier_id == _TIER_MAX_ID else ")"
    return f"[{bound(low)}, {bound(high)}{closer}"


def tier_for_affinity(affinity: float) -> int:
    """§4 档 id（-4..+3）：展示分 floor(display/25) 后 clamp，边界左闭右开、最高档含 +100。

    向后兼容标注：v3 返回具名 id（close/friendly/polite/distant），v4 起为整数档 id。
    """
    display = float(affinity) * 100.0
    return max(_TIER_MIN_ID, min(_TIER_MAX_ID, int(display // _TIER_WIDTH_DISPLAY)))


# ---- T-AFF-1（需求项 13）：「瞬间巨变结构性不可能」的**可计算判据** -------------
# 需求 13 的验收语义不是"步长调小了"，而是"**跨档只能逐档**"。这条性质可以从
# 两处真身**派生**出来，不必手写常数：
#   ① 档宽 = `_TIER_WIDTH_DISPLAY`（本文件 §4，八档各宽 25 展示分）；
#   ② 位移上界 = v7 两道护栏 `daily_move_cap_z` / `negative_event_cap_z`。
# `|Δz| ≤ cap` 时**展示分**位移的全局最坏值：g(a)=tanh(a)−tanh(a−δ) 的唯一驻点在
# 区间中点（sech² 关于 0 严格偶且单峰 ⇒ a=δ/2），故上确界在**跨原点的对称区间**
# 上取到，= `2·100·tanh(cap/2)`。旧口径 `100·tanh(cap)` 会低估（cap=0.12 时
# 11.943 < 真实 11.979）——S-T-AFF-1 的 10^4 fuzz 实测单事件 11.958 分撞穿旧上界
# （差分证据见 tests/test_affinity_no_instant_swing.py 交卷记录），判据函数低估
# 上界＝机器锁自身有洞，故此处按真确界修正。
# 于是"一天/一次至多变一档" ⟺ `2·100·tanh(cap/2) < 档宽` ⟺ `cap < 2·atanh(档宽/200)`
# ≈ 0.25067；执法判据 `v7_max_tier_step_for_z_cap` 直接对修正后的界取 ceil，恒正确。
# `_V7_ONE_TIER_Z_CEILING = atanh(档宽/100) ≈ 0.2554` 是旧推导语义的在册锚点，
# 被 tests/test_affinity_v7_structural_locks.py 以 1e-15 钉死数值（跨席锁面，
# 本波不动它）；两数相差 0.0047z、仅出现在越界点名文案的"临界"字样里，
# 逐档性判定本身不吃该常数（吃的是 ceil）。
_V7_ONE_TIER_Z_CEILING = math.atanh(_TIER_WIDTH_DISPLAY / 100.0)


def v7_display_move_for_z_cap(cap_z: float) -> float:
    """`|Δz| ≤ cap_z` 时展示分位移的**全局最坏值**（=200·tanh(cap/2)，跨 0 对称区间取到）。"""
    delta = max(0.0, _finite_float_or(cap_z, 0.0))
    return 200.0 * math.tanh(delta / 2.0)


def v7_max_tier_step_for_z_cap(cap_z: float) -> int:
    """`|Δz| ≤ cap_z` 时档号的**最大可能变化**（跨档界数为 `ceil(最坏位移/档宽)`）。

    返回 1 = "至多挪一档"，即需求项 13 要的结构性质；返回 ≥2 表示该上限已松到
    可以一次跳档。非有限输入按 0 处理（保守：不宣称安全，也不虚报危险——0 档）。
    """
    span = v7_display_move_for_z_cap(cap_z)
    if span <= 0.0:
        return 0
    return math.ceil(span / _TIER_WIDTH_DISPLAY)


def v7_structural_guard_report(settings: V7Settings) -> dict[str, Any]:
    """两道位移护栏的"逐档性"体检结果（只读派生量，不改任何数值口径）。

    用于 `resolve_v7_settings` 的越界点名与本席的机器锁：`ok=True` 意味着
    **任何**信号序列下、任意单日与单次调用的档号变化都被数学上限制在 1 以内。
    """
    caps = {
        "daily_move_cap_z": _finite_float_or(settings.daily_move_cap_z, 0.0),
        "negative_event_cap_z": _finite_float_or(settings.negative_event_cap_z, 0.0),
    }
    steps = {name: v7_max_tier_step_for_z_cap(value) for name, value in caps.items()}
    return {
        "caps": caps,
        "worst_display_move": {n: v7_display_move_for_z_cap(v) for n, v in caps.items()},
        "max_tier_step": steps,
        "one_tier_ceiling_z": _V7_ONE_TIER_Z_CEILING,
        "ok": all(step <= 1 for step in steps.values()),
    }


_LINEAR_TRANSITION_BAND_DISPLAY = 6.0  # 展示分距档界 ±6 分内视为线性过渡带


def linear_transition_for_affinity(
    affinity: float, *, v8: V8Settings | None = None
) -> str:
    """v4.1 线性态度（用户裁定：不得在档位门槛上生硬跳变）。

    距档位边界 ±6 展示分内时，返回一句"正处在向邻档自然过渡"的措辞，
    由 providers 拼进态度注入，使门槛两侧语气衔接为连续渐变；
    区间中部返回空串。极值档没有更外侧的邻档，返回空串。
    v8 带内混合（§C.5.1）启用时本函数恒返空串——过渡措辞已并入
    attitude_for_affinity 的混合真身，两套过渡机制不并存（禁第二真身）；
    v8 缺省关 ⇒ 行为逐字节如旧。
    """
    settings = v8 if v8 is not None else resolve_v8_settings(None)
    if settings.enabled:
        return ""
    display = max(_TIER_DISPLAY_FLOOR, min(_TIER_DISPLAY_CEILING, float(affinity) * 100.0))
    tier = tier_for_affinity(affinity)
    lo = _TIER_DISPLAY_FLOOR + _TIER_WIDTH_DISPLAY * (tier - _TIER_MIN_ID)
    hi = lo + _TIER_WIDTH_DISPLAY
    cur = _TIER_BY_ID[tier][0]
    if display - lo <= _LINEAR_TRANSITION_BAND_DISPLAY and tier - 1 >= _TIER_MIN_ID:
        prev_name = _TIER_BY_ID[tier - 1][0]
        return f"（此刻你们之间的氛围，正处在从「{prev_name}」流向「{cur}」的自然过渡里，语气顺势而为即可）"
    if hi - display <= _LINEAR_TRANSITION_BAND_DISPLAY and tier + 1 <= _TIER_MAX_ID:
        next_name = _TIER_BY_ID[tier + 1][0]
        return f"（此刻你们之间的氛围，正处在从「{cur}」流向「{next_name}」的自然过渡里，语气顺势而为即可）"
    return ""


def tier_blend_instruction(
    affinity: float, *, v8: V8Settings | None = None
) -> tuple[str, str]:
    """§C.5.1 带内混合：按带内位置 λ 决定「单档原句」或「相邻两档原句运行时拼接」。

    返回 `(档名, 基调正文)`。λ ∈ [edge, 1−edge] ⇒ 本档原句（中段照旧）；
    否则 ⇒ 「从「A」流向「B」」+ A 原句 + B 原句——只用 `_ATTITUDE_TIERS` 真身
    原句运行时拼接，**不新造/不改写句子、源码里不出现第二份副本**（单源锁
    tests/test_affinity_tier_single_source.py 的 AST/文本判据不受影响）。
    极值档只缺一个方向的邻档，缺侧不混。本函数与 v8 关态的
    attitude_for_affinity 输出零耦合（v8 关 ⇒ 不走这里）。
    """
    settings = v8 if v8 is not None else resolve_v8_settings(None)
    display = max(_TIER_DISPLAY_FLOOR, min(_TIER_DISPLAY_CEILING, float(affinity) * 100.0))
    tier = tier_for_affinity(display / 100.0)
    name, instruction = _TIER_BY_ID[tier]
    lo = _TIER_DISPLAY_FLOOR + _TIER_WIDTH_DISPLAY * (tier - _TIER_MIN_ID)
    lam = (display - lo) / _TIER_WIDTH_DISPLAY
    edge = settings.tier_blend_edge
    other_id: int | None = None
    if lam < edge:
        other_id = tier - 1
    elif lam > 1.0 - edge:
        other_id = tier + 1
    if other_id is None or not (_TIER_MIN_ID <= other_id <= _TIER_MAX_ID) or not settings.enabled:
        return name, instruction
    other_name, other_instruction = _TIER_BY_ID[other_id]
    if other_id < tier:
        a_name, a_text, b_name, b_text = other_name, other_instruction, name, instruction
    else:
        a_name, a_text, b_name, b_text = name, instruction, other_name, other_instruction
    blended = (
        f"此刻正处在从「{a_name}」流向「{b_name}」的自然过渡里——"
        f"「{a_name}」的基调：{a_text}；「{b_name}」的基调：{b_text}，语气顺势而为即可"
    )
    return name, blended


def tier_name_for_affinity(affinity: float) -> str:
    """§4 档位名称（初识/生疏/微凉/稍淡/友善/亲近/挚友/独一份），展示层共用。"""
    return _TIER_BY_ID[tier_for_affinity(affinity)][0]


def attitude_for_affinity(affinity: float, *, v8: V8Settings | None = None) -> str:
    """§4 完整态度文本：档位基调 + 四条态度红线（每档共同遵守，注入 prompt 全文）。

    v8 带内混合（§C.5.1，缺省关）：启用时基调正文改走 tier_blend_instruction——
    档内连续、边界两侧不再各拿一整份不同的指令全文；红线四条款原样、任何模式
    都带（红线文本零触碰）。v8 关 ⇒ 输出与本函数历史形态逐字节相同。
    """
    settings = v8 if v8 is not None else resolve_v8_settings(None)
    if settings.enabled:
        name, body = tier_blend_instruction(affinity, v8=settings)
    else:
        _name, body = _TIER_BY_ID[tier_for_affinity(affinity)]
        name = _name
    red_lines = "；".join(
        f"（{index}）{line}" for index, line in enumerate(_TIER_RED_LINES, start=1)
    )
    return f"对当前用户的态度（档位「{name}」）：{body}。共同态度红线：{red_lines}。"


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
                # v8 第二腿（规格 §C.4/§C.1）：goodwill_anchor 为长情锚点（历史
                # 最高水位减保护带，只升不降，REAL 可空——NULL=尚未播种，首次
                # v8 写入时按当前 z 现推，绝不重置存量）；v8_state 为环境均值/
                # 出场连续性/近期指纹的 JSON 载体。家规 ALTER-if-missing 同上，
                # 禁 DROP 禁重建；v8 关态两列零读写（懒建零漂移）。
                ("goodwill_anchor", "REAL"),
                ("v8_state", "TEXT NOT NULL DEFAULT '{}'"),
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
            # 展示面有界化落账表（「你对守岸人」读数的滚动 24h 单向下行限幅）。
            # 与算法真值/增量预算（affinity_delta_log）零共享——单位是展示分不是 z，
            # 混进增量日志会污染滚动位移预算的口径。时间戳用 epoch REAL（与
            # affinity_delta_log.applied_at 同形），窗口查询走数值比较。
            connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {SENTIMENT_DISPLAY_LOG_TABLE} (
                    sender_id TEXT NOT NULL,
                    shown_at REAL NOT NULL,
                    display_value REAL NOT NULL
                )
                """
            )
            connection.execute(
                f"CREATE INDEX IF NOT EXISTS idx_sentiment_display_log_sender_time"
                f" ON {SENTIMENT_DISPLAY_LOG_TABLE} (sender_id, shown_at)"
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
        S-T-AFFIN-GUARD：points 先过一次 `_finite_float_or`（脏值 ⇒ 0＝不动分）。
        旧形态 `max(-100, min(100, nan)) == 100.0` 把 NaN 读成**顶格授权**、
        恰好打满当日全部增益额度（fail-open；触发面=BOT_POKE_AFFINITY_DELTA
        写成非数——poke 侧 `grant=min(nan, …)` 原样流到这里）。
        返回更新后的 affinity。
        """
        bounded_points = max(-100.0, min(100.0, _finite_float_or(points, 0.0)))
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

        S-T-AFFIN-GUARD（需求项 13 + 裁定 D3）：入口与聚合读行各过一次
        `_finite_float_or`——门面 `coerce_override_delta` 之外的第二道，判据同一条：
        非有限值 ⇒ 0（本次不计分）。NaN 顺 `min/max` 比较链（一切比较恒 False）
        会把钳制翻成顶格或把脏值绑进 NOT NULL 列，两种都不是"保守"。
        """
        delta = _finite_float_or(delta, 0.0)
        if delta == 0.0:
            return 0.0
        window_6h_start = now - 6 * 3600.0
        window_24h_start = now - _DAY_SECONDS
        loss_6h = loss_24h = gain_24h = gain_source_24h = 0.0
        last_applied_at: float | None = None
        for row in connection.execute(
            "SELECT applied_at, delta, source FROM affinity_delta_log"
            " WHERE sender_id = ? AND bot_id = ? AND applied_at >= ?"
            # 单位纪律：v7/v8 行以 z 为单位记账，与本函数的分口径预算不可混用，
            # 显式排除（先例：v7；v8 第二腿沿用同一隔离——锁 tests/test_aff_algo_v8_bounds.py）。
            " AND COALESCE(source, '') NOT IN ('v7', 'v8')",
            (sender_id, bot_id, window_24h_start),
        ):
            applied = _finite_float_or(row["delta"], 0.0)
            applied_at = _finite_float_or(row["applied_at"], 0.0)
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
        单事件 |Δz|≤negative_event_cap_z（正负同帽，A-1 裁定；override 与
        普通计分面同尺，在 v7_raw_delta_z 与 override 分支各钳一次）、
        总位移 |ΣΔz|≤daily_move_cap_z（**滚动 24h**、从 affinity_delta_log 现读、
        正负共享同额——2026-09-26 A-1 裁定把旧「本地自然日桶」换形，
        跨午夜清零的排程路结构性消失）、
        同类信号日熔断 fuse_daily_events（超出不再计分、不喂新鲜度；日桶保留，
        要不要一并滚动见交付日志 §6 建议项）。
        冷却门沿用 _INTERACTION_COOLDOWN_SECONDS（去刷分语义不变）；
        零增量不落日志不占冷却（v5 同律）。override 按 z 域直用（管理员/poke
        权威信号语义不变，不喂新鲜度计数、不吃质量分），仍受单事件帽、
        滚动 24h 位移额度与 v8 表示域护栏。v8 边际递减：两分支汇流后 raw 先乘
        γ(|z|)=z_hard/(z_hard+|z|)（帽后、额度前，界外上界只收紧），更新处
        不再按 ±z_hard 截断（长尾，见 §v8 注释）。
        """
        state = _v7_load_state(state_json)
        # 活跃 EMA：所有抵达本体的事件都计入（rhythm 归一的"日均互动轮次"底数）。
        ema_value, ema_at = state["ema"]
        if now > ema_at:
            ema_value *= 0.5 ** ((now - ema_at) / (_V7_RHYTHM_HALFLIFE_DAYS * _DAY_SECONDS))
        ema_value += 1.0
        daily_rate = ema_value * math.log(2.0) / _V7_RHYTHM_HALFLIFE_DAYS
        # 当日结构：A-1 起只剩熔断计数一职（位移额度改滚动 24h 现读日志，
        # state 不再携带 day["s"]——旧形态"自然日清零"正是"午夜两侧各吃满一次"
        # 的排程路；"i"/"c" 保留是刻意的：熔断语义按日，她的裁定未动这一格）。
        day = state["day"]
        if int(day.get("i", -1)) != day_index:
            day = {"i": day_index, "c": {}}
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
            # 脏行读回按「刚计过分」处理（冻结=保守不放行），与 v5 路聚合读行同判据。
            and now - _finite_float_or(last_applied_at, now) < _INTERACTION_COOLDOWN_SECONDS
        ):
            return done(0.0, z)

        digest = hashlib.sha1((text or "").strip().encode("utf-8")).hexdigest()[:12]
        if delta_override is not None:
            # 权威信号：z 域直用，**单事件帽双向**（A-1 裁定）——旧形态只钳负向，
            # 正向"直穿到当日剩余额度"，一发 override 最多吃满全日 0.12z（≈11.98
            # 展示分），配合日桶还能午夜两侧各吃一轮。现正向同样被
            # negative_event_cap_z（语义已扩双向）咬到 0.10z。不喂新鲜度（v5
            # override "不喂新鲜度"语义保持；旧注"不占每日额度"与代码不符——
            # override 落同一张 delta 日志、吃同一份滚动额度，本行按实况改口）。
            # S-T-AFFIN-GUARD：执法体内的第二道消毒——门面被绕开（直调本体的
            # 在册锁与未来调用方）时，非有限 override 同样 ⇒ 0.0＝本次不动。
            # 旧形态 `float(delta_override)` 放行 NaN：`min(z_hard, z+nan)` 因
            # NaN 比较恒 False 返回 z_hard ⇒ 一发顶到 ±98.5（实测 +88.4 分）。
            raw = _finite_float_or(delta_override, 0.0)
            raw = max(-v7.negative_event_cap_z, min(v7.negative_event_cap_z, raw))
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
        # v8 边际递减（用户裁定 2026-09-27）：当前高度 z 处的步进乘
        # γ(|z|)=half/(half+|z|)（half=z_hard）。放在单事件帽**之后**、位移护栏
        # **之前**：帽咬过再缩放 ⇒ |raw|≤cap×γ≤cap，两道护栏的界外上界只收紧、
        # 从不放宽——override 通道同受此缩放（两分支在此汇流）。γ 只依赖 |z|，
        # 正负对称：高层减速双向成立，涨不到顶也跌不到底。
        raw *= v8_marginal_gain(z, v7.z_hard)
        # 位移护栏（A-1 裁定 2026-09-26）：**滚动 24h、现读 affinity_delta_log**，
        # 不再用 state 的 day["s"] 自然日桶——旧窗形"跨午夜即清零"可被排程成
        # 午夜两侧各吃满一轮额度（两发 60–120s 内跨档的路）。v7 行历来以
        # source='v7' 落该表（本函数末尾），>48h 才 prune，24h 窗恒完整；
        # 与 v5 路 `_clamp_delta_to_rolling_budget` 的"纯时间窗、重启与跨午夜
        # 均不重置"同一哲学，两路各读各的 source 族、互不吃对方额度（单位不同：
        # v5 行是分口径、v7 行是 z 口径，混读即串币制——v5 侧排除 'v7' 的既有
        # 判据是对称的另一半）。非有限脏行按**额度用满**处理：宁冻结不放行，
        # "脏值少算⇒放行更多"是保守判据的反面（SQLite 把 NaN 存成 NULL，
        # NULL>=窗界为假⇒该行进不了窗，与 v5 路同形，属既成边界如实记录）。
        moved_24h = 0.0
        budget_dirty = False
        for row in connection.execute(
            "SELECT delta FROM affinity_delta_log"
            " WHERE sender_id = ? AND bot_id = ? AND applied_at >= ? AND source = 'v7'",
            (sender_id, bot_id, now - _DAY_SECONDS),
        ):
            try:
                magnitude = abs(float(row["delta"]))
            except (TypeError, ValueError):
                magnitude = float("inf")
            if math.isfinite(magnitude):
                moved_24h += magnitude
            else:
                budget_dirty = True
        remaining = (
            0.0 if budget_dirty else max(0.0, v7.daily_move_cap_z - moved_24h)
        )
        if raw == 0.0 or remaining <= 0.0:
            return done(0.0, z)
        applied = min(raw, remaining) if raw > 0.0 else -min(-raw, remaining)
        # v8 长尾（2026-09-27）：此处**不再按 ±z_hard 截断**——旧形态在 |z| 逼近
        # atanh(0.985) 时贴界冻结（增量被整段丢弃、applied 归 0），既是"到顶"也
        # 是另一种"瞬间归零"。现只保留浮点表示域护栏 atanh(0.999999)：展示分
        # 严格落于 (−99.9999, +99.9999)，增长由 γ 持续减速、但永不触顶、永不
        # 冻结。域界仍是消毒口：非有限入参早在上游归 0，z+applied 越界只为
        # NaN 比较陷阱的兜底（max/min 对 NaN 恒 False 时返回域界一侧的形态在
        # 此已不可能出现——applied/raw 均经 _finite_float_or 归口）。
        new_z = max(-_V8_Z_REPR_DOMAIN, min(_V8_Z_REPR_DOMAIN, z + applied))
        applied = new_z - z
        if applied == 0.0:
            # 已贴表示域界（±99.9999 展示分外才可能到这里）：不占位移额度不落日志。
            return done(0.0, z)
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

    def _v8_delta(
        self,
        connection: sqlite3.Connection,
        sender_id: str,
        bot_id: str,
        behavior: str,
        z: float,
        *,
        v8: V8Settings,
        state_json: str,
        now: float,
        text: str,
        gap_seconds: float | None,
        delta_override: float | None,
        anchor_prev: float | None,
        companion_days: float | None,
        responded_to_question: bool | None,
        gamma_half_z: float,
        day_counters: dict[str, int],
        source_event_id: str,
    ) -> tuple[float, float, str, float]:
        """v8 第二腿 §C.2/§C.4 更新体（同锁同事务内调用；缺省关，永不到达）。

        返回 ``(applied_Δz, final_z, v8_state_json, new_anchor)``。界由数学给：
        冲量 u = Σw_iφ_i 经 `Σ|w_i|=1` 构造归一 ⇒ |u|≤1 ⇒ |δ_z|≤κ——**不是 if
        列表**，注毒删除归一化行测试必红（tests/test_aff_algo_v8_core.py）。

        六分量 φ（§C.2 表）：q 去环境基线互动质量 / t 情感温度 / r 尊重边界 /
        x 敌意伤害 / a 修复意图 / c 在场连续性（每天只计一次）。修复不再放大
        步长（推论 3 之三：快=足额吃 κ，不越任何界）。γ 边际递减沿用第一腿
        同一把尺（half=z_hard 在册键，禁第二尺），置于 κ 帽后、位移额度前。

        护栏形制：交互冷却门（v5/v7 同语义）；滚动 24h 位移额度 D 现读日志、
        z 口径同族（'v7' 行同为 z 单位——flag 切换当日合读更保守，只收紧不放宽；
        v5 分口径行绝不计入）；**不设日熔断/兜底帽**——κ·24h 数学上 ≤ 0.04z/日，
        与 25 次熔断同量级的"堆次数"路径已被额度封死（登记于交付日志）。
        override：z 域直用、钳 ±κ（权威信号在 v8 下仍是单事件有界语义），
        不喂任何状态面（amb/pres/recent 原样）。善意底 anchor 单调不减、
        落点 z=max(new_z, anchor)——只抬下界，绝不改写既有高度（推论 4）；
        额度只约束事件冲量，底座的回升不占额度（其值 ≤ 历史峰值，无新高度
        可堆）。终值仍过 `_V8_Z_REPR_DOMAIN` 表示域护栏（长尾不触顶）。
        """
        state = _v8_load_state(state_json)

        def done(applied: float, final_z: float, anchor: float) -> tuple[float, float, str, float]:
            return applied, final_z, _v8_dump_state(state), anchor

        band = v8.band_for(companion_days)
        # anchor 播种（fail-safe：列 NULL ⇒ 以当前高度现推，绝不重置存量语义）。
        anchor_base = v8_goodwill_anchor(anchor_prev, z, band)

        # 冷却门（与 v5/v7 同语义：距上次实际计分 <60s 记 0，不阻塞回复）。
        last_row = connection.execute(
            "SELECT MAX(applied_at) FROM affinity_delta_log WHERE sender_id = ? AND bot_id = ?",
            (sender_id, bot_id),
        ).fetchone()
        last_applied_at = last_row[0] if last_row is not None else None
        if (
            last_applied_at is not None
            and now - _finite_float_or(last_applied_at, now) < _INTERACTION_COOLDOWN_SECONDS
        ):
            return done(0.0, z, anchor_base)

        if delta_override is not None:
            # 权威信号：消毒→钳 ±κ→不喂状态（v7 override 语义的 v8 对应物）。
            raw = _finite_float_or(delta_override, 0.0)
            raw = max(-v8.impulse_cap_z, min(v8.impulse_cap_z, raw))
        else:
            if behavior == "refusal":
                # 拒答≠信号（V2.1 §2.2 零计分族同源）：不喂任何分量、不动状态。
                return done(0.0, z, anchor_base)
            digest = hashlib.sha1((text or "").strip().encode("utf-8")).hexdigest()[:12]
            repeated = bool(digest) and digest in state["recent"]
            q = v7_quality_score(
                text,
                behavior=behavior,
                gap_seconds=gap_seconds,
                repeated_recently=repeated,
                responded_to_question=responded_to_question,
            )
            # 在场连续性先记账（"到场"本身即事实，与消息质量无关；每天只计一次）。
            lt = time.localtime(now)
            day_start = now - (lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec)
            prev_day_start, streak = state["pres"]
            streak, phi_c = v8_continuity(prev_day_start, streak, day_start)
            if prev_day_start != day_start:
                state["pres"] = [day_start, streak]
            # āmbient：先按时间半衰到"现在"得基线 → φ_q 去基线 → 再以本次 q 收拢。
            amb_value, amb_at = state["amb"]
            decayed = amb_value * 0.5 ** (
                max(0.0, now - amb_at) / (v8.ambient_halflife_days * _DAY_SECONDS)
            )
            phi_q = (
                v8_quality_centered(q, decayed)
                if v8.ambient_centering
                else max(-1.0, min(1.0, q))
            )
            if q == 0.0:
                # 零质量事件不喂 EMA（敷衍不该把基线猛拽向 0——那是每消息一步的
                # 隐式大功率），只留复读指纹。v7 的 q==0 早退在 v8 同形。
                if digest:
                    state["recent"] = (state["recent"] + [digest])[-_V8_RECENT_WINDOW:]
                return done(0.0, z, anchor_base)
            state["amb"] = [
                v8_ambient_update(amb_value, amb_at, now, q, halflife_days=v8.ambient_halflife_days)[0],
                now,
            ]
            u = v8_impulse(
                (
                    phi_q,
                    _v8_sentiment_phi(text),
                    _v8_respect_phi(text, behavior),
                    _v8_hostility_phi(behavior),
                    _v8_repair_phi(text, behavior),
                    phi_c,
                ),
                v8.impulse_weights,
            )
            raw = v8.impulse_cap_z * u
            used = int(day_counters.get(behavior, 0))
            day_counters[behavior] = used + 1  # 观测一致性（v7 同律；兜底帽本身不设，见 docstring）
        # γ 边际递减（第一腿同一函数、同一半衰减参考点——两路汇流处只收紧不放宽）。
        raw *= v8_marginal_gain(z, gamma_half_z)
        if raw == 0.0:
            return done(0.0, z, anchor_base)
        # 滚动 24h 位移额度（z 口径；脏行按额度用满冻结，v7 同判据）。
        moved_24h = 0.0
        budget_dirty = False
        for row in connection.execute(
            "SELECT delta FROM affinity_delta_log"
            " WHERE sender_id = ? AND bot_id = ? AND applied_at >= ?"
            " AND source IN ('v7', 'v8')",
            (sender_id, bot_id, now - _DAY_SECONDS),
        ):
            try:
                magnitude = abs(float(row["delta"]))
            except (TypeError, ValueError):
                magnitude = float("inf")
            if math.isfinite(magnitude):
                moved_24h += magnitude
            else:
                budget_dirty = True
        remaining = 0.0 if budget_dirty else max(0.0, v8.daily_move_cap_z - moved_24h)
        if remaining <= 0.0:
            return done(0.0, z, anchor_base)
        applied = min(raw, remaining) if raw > 0.0 else -min(-raw, remaining)
        new_z = max(-_V8_Z_REPR_DOMAIN, min(_V8_Z_REPR_DOMAIN, z + applied))
        # 善意底（§C.4）：落点不低于 anchor（单调不减的历史水位），只抬不下压。
        anchor = max(anchor_base, v8_goodwill_anchor(anchor_prev, new_z, band))
        final_z = min(max(new_z, anchor), _V8_Z_REPR_DOMAIN)
        applied = final_z - z
        if applied == 0.0:
            return done(0.0, z, anchor_base)
        if delta_override is None and digest:
            state["recent"] = (state["recent"] + [digest])[-_V8_RECENT_WINDOW:]
        connection.execute(
            "DELETE FROM affinity_delta_log WHERE applied_at < ?",
            (now - _BUDGET_LOG_RETENTION_SECONDS,),
        )
        connection.execute(
            "INSERT INTO affinity_delta_log"
            " (sender_id, bot_id, applied_at, delta, source, source_event_id, z_after)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sender_id, bot_id, now, applied, "v8", source_event_id, final_z),
        )
        return done(applied, final_z, anchor)

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
        # 需求项 13 + 裁定 D3：权威信号入口一次消毒（v5/v6 与 v7 两条路共用），
        # 非有限 delta_override ⇒ 0.0（本次不计分）。执法体内部另有同判据的第二道。
        delta_override = coerce_override_delta(delta_override)
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
                    return (
                        coerce_affinity_fraction(existing["affinity"])
                        if existing is not None
                        else _AFFINITY_BASE
                    )
            row = connection.execute(
                "SELECT affinity, interaction_count, positive_count, negative_count, tease_count, insult_count,"
                " nickname, impression_tags, impression_tag_times, profile_notes,"
                " counter_day_index, day_counters, updated_at,"
                " last_positive_at, last_negative_at, last_insult_at,"
                " first_signals, first_impression, created_at, z_latent, v7_state,"
                " goodwill_anchor, v8_state"
                " FROM user_affinity WHERE sender_id = ?",
                (sender_id,),
            ).fetchone()
            z_keep: float | None = None
            v7_state_keep = "{}"
            anchor_keep: float | None = None
            v8_state_keep = "{}"
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
                # T-AFF-1：本 else 分支是**每轮对话**都会走的入站读口，旧形态在这里
                # 有 9 处裸 `int()` / `json.loads()`——一行脏数据（NULL 计数、`'['`
                # 截断的标签列、非数的日索引）就把整条聊天链路打成异常，且症状是
                # "某人从此再也发不出消息"，最难归因。全部改走消毒读口，合法值恒等。
                affinity = coerce_affinity_fraction(row["affinity"])
                counters = {
                    "positive": coerce_int(row["positive_count"]),
                    "negative": coerce_int(row["negative_count"]),
                    "tease": coerce_int(row["tease_count"]),
                    "insult": coerce_int(row["insult_count"]),
                }
                tags = coerce_json_list(row["impression_tags"])
                # G-11：标签打标时间（存量行可能缺条目，快照侧回退 updated_at 锚点）
                tag_times = coerce_json_mapping(row["impression_tag_times"])
                nickname = str(row["nickname"] or "")
                notes = coerce_json_list(row["profile_notes"])
                interactions = coerce_int(row["interaction_count"])
                last_seen = {
                    "positive": row["last_positive_at"],
                    "negative": row["last_negative_at"],
                    "insult": row["last_insult_at"],
                }
                first_signals = [
                    _finite_float_or(item, 0.0) for item in coerce_json_list(row["first_signals"])
                ]
                first_impression = coerce_optional_float(row["first_impression"])
                created_at = str(row["created_at"] or row["updated_at"] or now_text)
                # 每日计数仅当日有效；跨日自动清零（row_day != day_index 视为新的一天）。
                row_day = coerce_int(row["counter_day_index"], -1)
                day_counters = (
                    {
                        str(key): max(0, coerce_int(value))
                        for key, value in coerce_json_mapping(row["day_counters"]).items()
                    }
                    if row_day == day_index
                    else {}
                )
                # v7 列透传（v7-off 路径不得丢态：flag 来回切换可续跑）。
                # T-AFF-1：脏 z（非数/NaN/±inf）一律当"尚未派生"→ 由 affinity 列现推，
                # 绝不带着非有限值进入 `new_z - z`（那会算出 -inf 位移并写进增量日志）。
                z_keep = coerce_optional_float(row["z_latent"])
                v7_state_keep = str(row["v7_state"] or "{}")
                # v8 列透传（v8-off 路径零读写漂移：值原样带回 INSERT，不丢态）。
                anchor_keep = coerce_optional_float(row["goodwill_anchor"])
                v8_state_keep = str(row["v8_state"] or "{}")
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
            v8 = resolve_v8_settings(self._config_ref)
            if v8.enabled:
                # ---- v8 第二腿路径（§C.2 冲量 + §C.4 善意底；优先序 v8>v7>v5/v6，
                # v8 是 v7 表示面的超集：同一 z 域、同一 γ、多一套有界冲量执法体）----
                # z 惰性派生与 v7 同律（列 NULL 现推、flag 切换期漂移以 affinity 重推），
                # 唯一差别是派生钳位取 v8 长尾表示域（0.999999），不回吞历史高度。
                z_now = (
                    z_keep
                    if z_keep is not None
                    else v7_display_fraction_to_z(affinity, _V8_DISPLAY_DOMAIN_BOUND)
                )
                if z_keep is not None and abs(affinity - v7_z_to_display_fraction(z_keep)) > 1e-9:
                    z_now = v7_display_fraction_to_z(affinity, _V8_DISPLAY_DOMAIN_BOUND)
                prev_updated = _parse_utc(str(row["updated_at"])) if row is not None else None
                gap_seconds = max(0.0, now - prev_updated) if prev_updated is not None else None
                delta, z_now, v8_state_keep, anchor_keep = self._v8_delta(
                    connection,
                    sender_id,
                    bot_id,
                    behavior,
                    z_now,
                    v8=v8,
                    state_json=v8_state_keep,
                    now=now,
                    text=text,
                    gap_seconds=gap_seconds,
                    delta_override=delta_override,
                    anchor_prev=anchor_keep,
                    companion_days=companion_days,
                    responded_to_question=responded_to_question,
                    gamma_half_z=v7.z_hard,
                    day_counters=day_counters,
                    source_event_id=source_event_id or "",
                )
                z_keep = z_now
                affinity = v7_z_to_display_fraction(z_now)
                delta = 0.0
            elif v7.enabled:
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
            # S-T-AFFIN-GUARD：改走 affinity_after_move——合法输入逐字节等价，
            # 唯一差别是非有限残差时保持原地（末道闸，绝不把 NaN/顶格写进库）。
            affinity = affinity_after_move(affinity, delta)
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
                     first_signals, first_impression, created_at, z_latent, v7_state,
                     goodwill_anchor, v8_state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    anchor_keep,
                    v8_state_keep,
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
            affinity = coerce_affinity_fraction(row["affinity"])
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
            coerce_int(row["positive_count"]), row["last_positive_at"],
            _SENTIMENT_HALF_LIFE_DAYS["positive"],
        )
        eff_negative = _decayed(
            coerce_int(row["negative_count"]), row["last_negative_at"],
            _SENTIMENT_HALF_LIFE_DAYS["negative"],
        )
        eff_insult = _decayed(
            coerce_int(row["insult_count"]), row["last_insult_at"],
            _SENTIMENT_HALF_LIFE_DAYS["insult"],
        )
        denom = eff_positive + eff_negative + 2 * eff_insult
        if denom < 0.1:
            return 0.1  # 历史信号全部淡出：回到默认
        return eff_positive / denom

    def bound_sentiment_display(
        self,
        sender_id: str,
        raw_display: float,
        *,
        cap_per_day: float = _SENTIMENT_DISPLAY_DAILY_DROP_CAP,
    ) -> float:
        """「你对守岸人」展示读数的**单向限幅**（展示面纪律；真值/档位零触碰）。

        ``raw_display``＝``sentiment_for(sender_id) × 100`` 的展示分（0~100）。
        裸比值是衰减计数比，一条辱骂就能砸下几十分——展示面照裸值出卡，等于给
        「一条消息挪动数十展示分」的刷屏攻击开直通车。本方法只约束**展示值**：

        - 滚动 24h 窗（epoch REAL 数值比较，同 ``affinity_delta_log`` 形态）内，
          展示值相对「窗口峰值」（含此前已展示过的值）的下行幅度 ≤ ``cap_per_day``
          展示分；**上行不限**——好感回暖即时可见，单向尺只拦砸盘不拦回温。
        - ``sentiment_for`` 内部真值、好感档位、注入面 attitude 全部零改动；
          ``ALGORITHM_TEXT`` 的定性纪律不破（限幅量不外显、不展示固定加减数值）。
        - 落账表 ``sentiment_display_log`` 与增量预算表零共享（单位是展示分不是
          z，混账会污染滚动位移预算）；>48h 行写入时 prune；同值不重复落行。
        - 任何形状/存储故障 **fail-open 回裸值**：展示限幅是礼仪不是必需品，
          绝不许它把查询命令搞挂。
        """
        raw = _finite_float_or(raw_display, float("nan"))
        if not math.isfinite(raw):
            return raw_display
        cap = _finite_float_or(cap_per_day, float("nan"))
        key = str(sender_id or "").strip()
        if not key or not math.isfinite(cap) or cap <= 0:
            return raw_display
        now = float(self._clock())
        try:
            with self._lock, self._connect() as connection:
                window_rows = connection.execute(
                    f"SELECT display_value FROM {SENTIMENT_DISPLAY_LOG_TABLE}"
                    " WHERE sender_id = ? AND shown_at > ?",
                    (key, now - _DAY_SECONDS),
                ).fetchall()
                peak = raw
                for row in window_rows:
                    value = _finite_float_or(row["display_value"], float("nan"))
                    if math.isfinite(value):
                        peak = max(peak, value)
                shown = max(raw, peak - cap)
                connection.execute(
                    f"DELETE FROM {SENTIMENT_DISPLAY_LOG_TABLE} WHERE shown_at < ?",
                    (now - 2 * _DAY_SECONDS,),
                )
                latest = connection.execute(
                    f"SELECT display_value FROM {SENTIMENT_DISPLAY_LOG_TABLE}"
                    " WHERE sender_id = ? ORDER BY shown_at DESC LIMIT 1",
                    (key,),
                ).fetchone()
                latest_value = (
                    _finite_float_or(latest["display_value"], float("nan"))
                    if latest is not None
                    else float("nan")
                )
                if not math.isfinite(latest_value) or abs(latest_value - shown) > 1e-9:
                    connection.execute(
                        f"INSERT INTO {SENTIMENT_DISPLAY_LOG_TABLE}"
                        " (sender_id, shown_at, display_value) VALUES (?, ?, ?)",
                        (key, now, shown),
                    )
        except Exception:  # noqa: BLE001 - 展示面故障不外抛：回裸值，查询照常。
            return raw_display
        return shown

    def snapshot(self, sender_id: str) -> dict[str, Any]:
        """读取好感度与印象；无记录返回中性默认。只读，不触发惰性回归。

        态度文本带 store 的 v8 快照（2026-09-28 收编补线）：config 面开 v8 时
        注入面走带内混合，与写路径同一把尺；v8 关 ⇒ 输出逐字节如旧。
        """
        v8 = resolve_v8_settings(self._config_ref)
        if not sender_id:
            return {
                "affinity": _AFFINITY_BASE,
                "tags": [],
                "nickname": "",
                "profile_notes": [],
                "tier": tier_for_affinity(_AFFINITY_BASE),
                "attitude": attitude_for_affinity(_AFFINITY_BASE, v8=v8),
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
                "attitude": attitude_for_affinity(_AFFINITY_BASE, v8=v8),
            }
        affinity = coerce_affinity_fraction(row["affinity"])
        # G-11 注入判据（审查 G-11，2026-09-15）：超龄标签不再注入，库内保留可溯。
        # providers（prompt 注入）、好感度卡、指令回显等全部消费 snapshot()，
        # 过滤在本出口一次闭环；数值规范零触碰（docs/affinity-design.md 为权威）。
        fresh_tags = _filter_fresh_impression_tags(
            [str(t) for t in coerce_json_list(row["impression_tags"])],
            coerce_json_mapping(row["impression_tag_times"]),
            now=float(self._clock()),
            anchor=_parse_utc(str(row["updated_at"])),
        )
        return {
            "affinity": affinity,
            "nickname": str(row["nickname"] or ""),
            "tags": fresh_tags,
            "profile_notes": [str(n) for n in coerce_json_list(row["profile_notes"])],
            "tier": tier_for_affinity(affinity),
            "attitude": attitude_for_affinity(affinity, v8=v8),
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
            "first_impression": coerce_optional_float(row["first_impression"]),
            "interaction_count": coerce_int(row["interaction_count"]),
            "known_days": round(known_days, 1),
        }

    def learn_profile(self, sender_id: str, text: str) -> list[str]:
        """从自述提取画像事实并合并入 profile_notes（去重，上限 12 条）。

        写侧消毒（ATK-AFFINITY 票②·2026-09-28 收编）：每条 fact 落库前过
        ``security/memory_sanitize.pre_write_sanitize``——与记忆腿
        （``store_extracted_memories``）、反思事实腿（``save_facts``）同一道闸、
        同一口径：硬红线命中 ⇒ 该条拒存；内部边界标记 ⇒ 全角化；干净文本
        逐字节不变。返回值同为消毒后文本，杜绝原文经返回口旁路再入 prompt。
        懒导入断环（memory_sanitize 顶层 import character 层组件，家规同
        reflection._sanitize_fact_text）。
        """
        facts = extract_profile_facts(text)
        if not facts or not sender_id:
            return []
        from plugins.bot_unified_runtime.domains.chat_reply.security.memory_sanitize import (
            pre_write_sanitize,
        )

        safe_facts: list[str] = []
        for fact in facts:
            body = pre_write_sanitize(str(fact))
            if body is None or not body.strip():
                continue
            safe_facts.append(body)
        if not safe_facts:
            return []
        now_text = _format_utc(float(self._clock()))
        merged: list[str] = []
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT profile_notes FROM user_affinity WHERE sender_id = ?",
                (sender_id,),
            ).fetchone()
            existing = coerce_json_list(row["profile_notes"]) if row else []
            merged = [str(f) for f in existing]
            for fact in safe_facts:
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
        return safe_facts

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
