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

# ---- 数值化常量（规范唯一权威：docs/affinity-design.md v4 线性版）----
_AFFINITY_BASE = 0.1            # §1 基准 0.1（展示 10 = ×100）：初始好感=回归收敛目标
AFFINITY_BASE = _AFFINITY_BASE  # 公开只读别名（providers 等模块判断“非默认记录”用）
_DAY_SECONDS = 86400
# §2 因子表：步长全程线性（v3 的幂律阻尼 γ 已废除），乘法因子只剩个人系数。
_BEHAVIOR_DELTA = {"positive": 0.02, "neutral": 0.0, "tease": -0.01, "negative": -0.05, "insult": -0.10}
# §2 每日有效次数上限（UTC 自然日）：同行为超出后 delta 记 0，计数器与标签照常累计。
_DAILY_EFFECTIVE_CAPS: dict[str, int] = {"positive": 10, "tease": 5, "negative": 8, "insult": 8}
# §3 惰性回归（时间减退）：写路径检查闲置天数，≥7 天起每天向基准 0.1（10 分）
# 回归 0.01，不超过剩余距离；时间源走注入 clock；updated_at 解析失败视为同日不衰减。
_IDLE_REGRESSION_START_DAYS = 7
_IDLE_REGRESSION_PER_DAY = 0.01
# §3 印象淡出（记忆减弱）半衰期（天）：辱骂 15、其余负面/正面 30；全部淡出回基准 10。
_SENTIMENT_HALF_LIFE_DAYS = {"positive": 30.0, "negative": 30.0, "insult": 15.0}
# 榜卡展示折算：闲置分数向基数衰减的半衰期（天），只影响展示，不落库。
_LEADERBOARD_DECAY_HALF_LIFE_DAYS = 30.0


def per_user_factor(sender_id: str) -> float:
    """因人而异的确定性步长系数（±15%）：同一 sender 恒定，跨重启不变。"""
    if not sender_id:
        return 1.0
    digest = hashlib.sha1(str(sender_id).encode("utf-8")).hexdigest()
    return 0.85 + 0.3 * (int(digest[:8], 16) % 1000) / 999


def effective_delta(
    sender_id: str,
    behavior: str,
    affinity: float,
    *,
    delta_override: float | None = None,
) -> float:
    """一次行为在当前状态下的精确增减（docs §2 v4：线性步长 × 个人系数）。

    v4 无阻尼：步长不再随当前分靠近极值缩小（v3 的 _damping 幂律已废除），
    全程 = 因子表 delta × m(uid)；override 为权威信号不乘系数（仅 clamp）。
    """
    if delta_override is not None:
        return float(delta_override)
    return _BEHAVIOR_DELTA.get(behavior, 0.0) * per_user_factor(sender_id)

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
        "被冒犯时只温和表明立场（“这样的话我会难过的”量级），绝不坚决抵抗或反击"
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
    ) -> float:
        """记录一次行为并更新好感度；返回更新后的 affinity。"""
        if not sender_id:
            return _AFFINITY_BASE
        now = float(self._clock())
        now_text = _format_utc(now)
        # 每日上限按进程本地时区自然日（bot_timezone），对用户体感即「北京时间每日重置」。
        day_index = int(time.strftime("%Y%m%d", time.localtime(now)))
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT affinity, interaction_count, positive_count, negative_count, tease_count, insult_count,"
                " nickname, impression_tags, profile_notes, counter_day_index, day_counters, updated_at,"
                " last_positive_at, last_negative_at, last_insult_at"
                " FROM user_affinity WHERE sender_id = ?",
                (sender_id,),
            ).fetchone()
            if row is None:
                affinity = _AFFINITY_BASE
                counters = {"positive": 0, "negative": 0, "tease": 0, "insult": 0}
                tags: list[str] = []
                nickname = ""
                notes: list[str] = []
                day_counters: dict[str, int] = {}
                interactions = 0
                last_seen: dict[str, str | None] = {"positive": None, "negative": None, "insult": None}
            else:
                affinity = float(row["affinity"])
                counters = {
                    "positive": int(row["positive_count"]),
                    "negative": int(row["negative_count"]),
                    "tease": int(row["tease_count"]),
                    "insult": int(row["insult_count"]),
                }
                tags = json.loads(str(row["impression_tags"] or "[]"))
                nickname = str(row["nickname"] or "")
                notes = json.loads(str(row["profile_notes"] or "[]"))
                interactions = int(row["interaction_count"])
                last_seen = {
                    "positive": row["last_positive_at"],
                    "negative": row["last_negative_at"],
                    "insult": row["last_insult_at"],
                }
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
            # §2 v4：实际步长 = 因子表 × 个人系数 m(uid)，线性、无幂律阻尼。
            if delta_override is not None:
                delta = float(delta_override)
            else:
                cap = _DAILY_EFFECTIVE_CAPS.get(behavior)
                used = int(day_counters.get(behavior, 0))
                if cap is not None and used >= cap:
                    delta = 0.0
                else:
                    delta = effective_delta(sender_id, behavior, affinity)
                day_counters[behavior] = used + 1
            # §1 v4：写入路径全部 clamp 到 [-1, +1]（存量 [0,1] 旧值恒等沿用，无迁移）。
            affinity = max(-1.0, min(1.0, affinity + delta))
            if behavior in counters:
                counters[behavior] += 1
            if behavior in last_seen:
                last_seen[behavior] = now_text
            for watch, threshold, tag in _IMPRESSION_RULES:
                if watch in counters and counters[watch] >= threshold and tag not in tags:
                    tags.append(tag)
            connection.execute(
                """
                INSERT OR REPLACE INTO user_affinity
                    (sender_id, affinity, interaction_count, positive_count, negative_count,
                     tease_count, insult_count, nickname, impression_tags, profile_notes,
                     counter_day_index, day_counters, updated_at,
                     last_positive_at, last_negative_at, last_insult_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    json.dumps(notes, ensure_ascii=False),
                    day_index,
                    json.dumps(day_counters, ensure_ascii=False),
                    now_text,
                    last_seen["positive"],
                    last_seen["negative"],
                    last_seen["insult"],
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
                "SELECT affinity, nickname, impression_tags, profile_notes FROM user_affinity WHERE sender_id = ?",
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
        return {
            "affinity": affinity,
            "nickname": str(row["nickname"] or ""),
            "tags": json.loads(str(row["impression_tags"] or "[]")),
            "profile_notes": json.loads(str(row["profile_notes"] or "[]")),
            "tier": tier_for_affinity(affinity),
            "attitude": attitude_for_affinity(affinity),
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
