"""动态好感度与印象标签（批次 C 核心）。

静态档案（relationship.py 的 JSON）之外的行为驱动层：
- 每条消息按内容与安全评估归类行为：positive/neutral/negative/insult；
- 行为驱动 affinity 增减（clamp [0,1]），并累计印象标签；
- SQLite 持久化；与静态档案融合规则：档案有 affinity 用档案，否则用动态层。

数值规范唯一权威描述见 docs/affinity-design.md（基数/因子表/每日上限/惰性回归/档位）。
态度分档（注入 prompt 的一句话）：
- >=0.75 亲近：更直接的关心，可用对方小名；
- >=0.45 友善：温和有陪伴感；
- >=0.25 客气：礼貌但有距离；
- <0.25 严厉：简短、有分寸的疏离——始终保持人格，绝不人身攻击。
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

_POSITIVE_RE = re.compile(r"(谢谢|感谢|辛苦了|太棒了|厉害|好棒|喜欢你|陪你|抱抱|晚安|早安)", re.IGNORECASE)
_NEGATIVE_RE = re.compile(r"(烦死了|别烦我|无聊|真差劲|没用|傻|蠢|闭嘴|滚)", re.IGNORECASE)

# 印象标签：行为累计达标即打标，注入 prompt 供人格参考（不外显为标签词）。
_IMPRESSION_RULES: tuple[tuple[str, int, str], ...] = (
    ("positive", 3, "友善"),
    ("positive", 10, "老朋友"),
    ("negative", 3, "爱抱怨"),
    ("insult", 2, "口无遮拦"),
    ("tease", 3, "爱戏弄"),
)
_TEASE_RE = re.compile(r"(哈哈|笑死|逗你|骗你的|捉弄|整蛊)", re.IGNORECASE)

# ---- 数值化常量（规范见 docs/affinity-design.md §2/§3，v3）----
_AFFINITY_BASE = 0.1            # 初始好感 10（展示 0-100 = ×100）
AFFINITY_BASE = _AFFINITY_BASE  # 公开只读别名（providers 等模块判断“非默认记录”用）
_DAY_SECONDS = 86400
_BEHAVIOR_DELTA = {"positive": 0.02, "neutral": 0.0, "tease": -0.01, "negative": -0.05, "insult": -0.10}
# 每日有效次数上限（UTC 自然日）：同行为超出后 delta 记 0，计数器与标签照常累计。
_DAILY_EFFECTIVE_CAPS: dict[str, int] = {"positive": 10, "tease": 5, "negative": 8, "insult": 8}
# 幂律步长衰减（log-log 线性）：距极值 <0.1（即 <10 分）时步长按 (d/0.1)^γ 缩小。
_DAMPING_RANGE = 0.1
_DAMPING_EXPONENT = 1.0
# 惰性回归：写路径检查闲置天数，≥7 天起每天向基数回归 0.01，不超过剩余距离；读路径无副作用。
_IDLE_REGRESSION_START_DAYS = 7
_IDLE_REGRESSION_PER_DAY = 0.01


def per_user_factor(sender_id: str) -> float:
    """因人而异的确定性步长系数（±15%）：同一 sender 恒定，跨重启不变。"""
    if not sender_id:
        return 1.0
    digest = hashlib.sha1(str(sender_id).encode("utf-8")).hexdigest()
    return 0.85 + 0.3 * (int(digest[:8], 16) % 1000) / 999


def _damping(affinity: float) -> float:
    """靠近极值步长幂律衰减：x∈[0.1,0.9] 全额；d=min(x,1-x)<0.1 时按 (d/0.1)^γ 缩小。"""
    d = min(affinity, 1.0 - affinity)
    if d >= _DAMPING_RANGE:
        return 1.0
    return (d / _DAMPING_RANGE) ** _DAMPING_EXPONENT


def effective_delta(
    sender_id: str,
    behavior: str,
    affinity: float,
    *,
    delta_override: float | None = None,
) -> float:
    """一次行为在当前状态下的精确增减（含衰减与个人系数；override 为权威信号不衰减）。"""
    if delta_override is not None:
        return float(delta_override)
    return _BEHAVIOR_DELTA.get(behavior, 0.0) * _damping(affinity) * per_user_factor(sender_id)

_ATTITUDE_TIERS: tuple[tuple[float, str], ...] = (
    (0.75, "亲近：更直接的关心与陪伴，可以用你给对方起的小名称呼"),
    (0.45, "友善：温和有陪伴感，记得对方的偏好"),
    (0.25, "客气：礼貌但有距离，不假装熟识"),
    (0.00, "严厉：简短、有分寸的疏离；保持人格与体面，绝不辱骂或人身攻击"),
)


def classify_behavior(text: str, *, safety_category: str = "", safety_action: str = "allow") -> str:
    if safety_category in {"harassment", "insult_nickname"} or safety_action == "refuse":
        return "insult"
    if safety_category in {"excessive_intimacy", "persona_breaking"}:
        return "tease"
    value = text or ""
    if _POSITIVE_RE.search(value):
        return "positive"
    if _TEASE_RE.search(value):
        return "tease"
    if _NEGATIVE_RE.search(value):
        return "negative"
    return "neutral"


def tier_for_affinity(affinity: float) -> str:
    """档位 id（左闭右开，边界值归上一档）：close/friendly/polite/distant。"""
    if affinity >= 0.75:
        return "close"
    if affinity >= 0.45:
        return "friendly"
    if affinity >= 0.25:
        return "polite"
    return "distant"


def attitude_for_affinity(affinity: float) -> str:
    for threshold, attitude in _ATTITUDE_TIERS:
        if affinity >= threshold:
            return attitude
    return _ATTITUDE_TIERS[-1][1]


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
            ):
                if column not in columns:
                    connection.execute(f"ALTER TABLE user_affinity ADD COLUMN {column} {ddl}")
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
        day_index = int(now // _DAY_SECONDS)
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT affinity, interaction_count, positive_count, negative_count, tease_count, insult_count,"
                " nickname, impression_tags, profile_notes, counter_day_index, day_counters, updated_at"
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
            # 实际步长 = 因子表 × 幂律衰减 g(当前分) × 个人系数 m(uid)（docs §3 v3）。
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
            affinity = max(0.0, min(1.0, affinity + delta))
            if behavior in counters:
                counters[behavior] += 1
            for watch, threshold, tag in _IMPRESSION_RULES:
                if watch in counters and counters[watch] >= threshold and tag not in tags:
                    tags.append(tag)
            connection.execute(
                """
                INSERT OR REPLACE INTO user_affinity
                    (sender_id, affinity, interaction_count, positive_count, negative_count,
                     tease_count, insult_count, nickname, impression_tags, profile_notes,
                     counter_day_index, day_counters, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        """群好感榜：按印象好感度降序（互动次数、sender_id 兜底），score=0-100。"""
        if not group_id:
            return []
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT sender_id, display_name, affinity, interaction_count FROM group_affinity"
                " WHERE group_id = ? ORDER BY affinity DESC, interaction_count DESC, sender_id ASC"
                " LIMIT ?",
                (group_id, max(1, int(limit))),
            ).fetchall()
        return [
            {
                "sender_id": str(row["sender_id"]),
                "display_name": str(row["display_name"] or ""),
                "affinity": float(row["affinity"]),
                "score": round(float(row["affinity"]) * 100.0, 1),
                "tier": tier_for_affinity(float(row["affinity"])),
            }
            for row in rows
        ]

    def sentiment_for(self, sender_id: str) -> float:
        """用户对机器人的表达倾向（加权正向占比 0-1；零信号默认 0.1，与初始好感一致）。

        positive / (positive + negative + 2×insult)——从说出口的话估算的
        表达比例，不是对内心的测量（docs/affinity-design.md §9.1）。
        """
        if not sender_id:
            return 0.1
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT positive_count, negative_count, insult_count FROM user_affinity"
                " WHERE sender_id = ?",
                (sender_id,),
            ).fetchone()
        if row is None:
            return 0.1
        positive = max(0, int(row["positive_count"]))
        negative = max(0, int(row["negative_count"]))
        insult = max(0, int(row["insult_count"]))
        denom = positive + negative + 2 * insult
        if denom <= 0:
            return 0.1
        return positive / denom

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
