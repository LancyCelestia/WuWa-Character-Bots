"""动态好感度与印象标签（批次 C 核心）。

静态档案（relationship.py 的 JSON）之外的行为驱动层：
- 每条消息按内容与安全评估归类行为：positive/neutral/negative/insult；
- 行为驱动 affinity 增减（clamp [0,1]），并累计印象标签；
- SQLite 持久化；与静态档案融合规则：档案有 affinity 用档案，否则用动态层。

态度分档（注入 prompt 的一句话）：
- >=0.75 亲近：更直接的关心，可用对方小名；
- >=0.45 友善：温和有陪伴感；
- >=0.25 客气：礼貌但有距离；
- <0.25 严厉：简短、有分寸的疏离——始终保持人格，绝不人身攻击。
"""

from __future__ import annotations

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

_BEHAVIOR_DELTA = {"positive": 0.02, "neutral": 0.0, "tease": -0.01, "negative": -0.05, "insult": -0.10}
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


def attitude_for_affinity(affinity: float) -> str:
    for threshold, attitude in _ATTITUDE_TIERS:
        if affinity >= threshold:
            return attitude
    return _ATTITUDE_TIERS[-1][1]




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
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_affinity (
                    sender_id TEXT PRIMARY KEY,
                    affinity REAL NOT NULL DEFAULT 0.5,
                    interaction_count INTEGER NOT NULL DEFAULT 0,
                    positive_count INTEGER NOT NULL DEFAULT 0,
                    negative_count INTEGER NOT NULL DEFAULT 0,
                    tease_count INTEGER NOT NULL DEFAULT 0,
                    insult_count INTEGER NOT NULL DEFAULT 0,
                    nickname TEXT NOT NULL DEFAULT '',
                    impression_tags TEXT NOT NULL DEFAULT '[]',
                    profile_notes TEXT NOT NULL DEFAULT '[]',
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(user_affinity)").fetchall()
            }
            if "profile_notes" not in columns:
                connection.execute(
                    "ALTER TABLE user_affinity ADD COLUMN profile_notes TEXT NOT NULL DEFAULT '[]'"
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        return connection

    def observe(
        self,
        sender_id: str,
        behavior: str,
        *,
        delta_override: float | None = None,
    ) -> float:
        """记录一次行为并更新好感度；返回更新后的 affinity。"""
        if not sender_id:
            return 0.5
        delta = _BEHAVIOR_DELTA.get(behavior, 0.0) if delta_override is None else delta_override
        now_text = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT affinity, interaction_count, positive_count, negative_count, tease_count, insult_count, impression_tags"
                " FROM user_affinity WHERE sender_id = ?",
                (sender_id,),
            ).fetchone()
            if row is None:
                affinity = max(0.0, min(1.0, 0.5 + delta))
                counters = {"positive": 0, "negative": 0, "tease": 0, "insult": 0}
                tags: list[str] = []
            else:
                affinity = max(0.0, min(1.0, float(row["affinity"]) + delta))
                counters = {
                    "positive": int(row["positive_count"]),
                    "negative": int(row["negative_count"]),
                    "tease": int(row["tease_count"]),
                    "insult": int(row["insult_count"]),
                }
                tags = json.loads(str(row["impression_tags"] or "[]"))
            if behavior in counters:
                counters[behavior] += 1
            for watch, threshold, tag in _IMPRESSION_RULES:
                if watch in counters and counters[watch] >= threshold and tag not in tags:
                    tags.append(tag)
            connection.execute(
                """
                INSERT OR REPLACE INTO user_affinity
                    (sender_id, affinity, interaction_count, positive_count, negative_count, tease_count, insult_count, nickname, impression_tags, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT nickname FROM user_affinity WHERE sender_id = ?), ''), ?, ?)
                """,
                (
                    sender_id,
                    affinity,
                    (int(row["interaction_count"]) + 1) if row else 1,
                    counters["positive"],
                    counters["negative"],
                    counters["tease"],
                    counters["insult"],
                    sender_id,
                    json.dumps(tags, ensure_ascii=False),
                    now_text,
                ),
            )
            return affinity

    def snapshot(self, sender_id: str) -> dict[str, Any]:
        """读取好感度与印象；无记录返回中性默认。"""
        if not sender_id:
            return {"affinity": 0.5, "tags": [], "nickname": "", "attitude": attitude_for_affinity(0.5)}
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT affinity, nickname, impression_tags FROM user_affinity WHERE sender_id = ?",
                (sender_id,),
            ).fetchone()
        if row is None:
            return {"affinity": 0.5, "tags": [], "nickname": "", "attitude": attitude_for_affinity(0.5)}
        return {
            "affinity": float(row["affinity"]),
            "nickname": str(row["nickname"] or ""),
            "tags": json.loads(str(row["impression_tags"] or "[]")),
            "attitude": attitude_for_affinity(float(row["affinity"])),
        }

    def learn_profile(self, sender_id: str, text: str) -> list[str]:
        """从自述提取画像事实并合并入 profile_notes（去重，上限 12 条）。"""
        facts = extract_profile_facts(text)
        if not facts or not sender_id:
            return []
        now_text = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
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
                "INSERT OR IGNORE INTO user_affinity (sender_id, affinity, updated_at) VALUES (?, 0.5, ?)",
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
                "INSERT OR IGNORE INTO user_affinity (sender_id, affinity, updated_at) VALUES (?, 0.5, ?)",
                (sender_id, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
            )
            connection.execute(
                "UPDATE user_affinity SET nickname = ? WHERE sender_id = ?",
                (nickname.strip()[:32], sender_id),
            )
