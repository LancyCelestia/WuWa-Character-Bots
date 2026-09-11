"""时间点记忆→主动提醒（reminders）：记住用户"几点要做什么"，到点温柔督促。

设计（对应需求"用户表示中午12点要写作业，机器人应在12点温柔地督促"）：
- 双轨解析：①显式命令/自然语言含「提醒/叫我」+ 时间表达 → 确定性正则解析
  （低误报）；②进阶轨留接口（LLM 轮末抽取同 memory_extract 模式）。
- 存储与投递解耦：本模块只管 SQLite 与解析；到点投递由 __init__ 的
  每分钟调度任务构造 SendRequest 走统一发送队列（语气由人格文案承担）。
- 绝不打扰失控：单会话待办上限、过期 24h 自动作废、取消可用。
"""

from __future__ import annotations

import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha1
from pathlib import Path

_REMIND_SIGNAL_RE = re.compile(r"提醒|叫我|记得叫")
_PERIOD_DEFAULTS: dict[str, tuple[int, int]] = {
    "凌晨": (5, 0),
    "早上": (8, 0),
    "上午": (9, 0),
    "中午": (12, 0),
    "下午": (15, 0),
    "傍晚": (18, 0),
    "晚上": (20, 0),
    "今晚": (20, 0),
}
_DAY_OFFSETS = {"今天": 0, "今晚": 0, "今早": 0, "明天": 1, "明晚": 1, "后天": 2}

_ABS_TIME_RE = re.compile(
    r"(今天|明天|后天|今晚|今早|明晚)?\s*(凌晨|早上|上午|中午|下午|傍晚|晚上)?\s*"
    r"(\d{1,2})\s*[点時时:：]\s*(\d{1,2})?\s*分?"
)
_PERIOD_ONLY_RE = re.compile(r"(今天|明天|后天|今晚|今早|明晚)?\s*(凌晨|早上|上午|中午|下午|傍晚|晚上)(?![点時时:：\d])")
_REL_MINUTES_RE = re.compile(r"(\d{1,3})\s*分钟后")
_REL_HOURS_RE = re.compile(r"(\d{1,2})\s*(?:个)?小时后")
_REL_HALF_HOUR_RE = re.compile(r"半(?:个)?小时后")
_CLEAN_RE = re.compile(r"提醒我?|叫我|记得叫|一下|吧|哦|呀|啊|，|,|。|！|!|？|\?")


@dataclass(frozen=True)
class Reminder:
    reminder_id: str
    session_key: str
    sender_id: str
    target_scope: str
    target_id: str
    adapter: str
    bot_id: str
    remind_at: str
    text: str
    status: str
    created_at: str


@dataclass(frozen=True)
class ReminderIntent:
    remind_at: datetime
    text: str
    label: str


def parse_reminder_intent(text: str, *, now: datetime | None = None) -> ReminderIntent | None:
    """解析「X点提醒我/叫我做Y」。无提醒信号或无时间表达 → None。"""
    raw = (text or "").strip()
    if not raw or not _REMIND_SIGNAL_RE.search(raw):
        return None
    current = now or datetime.now().astimezone()

    target: datetime | None = None
    match = _REL_HALF_HOUR_RE.search(raw)
    if match:
        target = current + timedelta(minutes=30)
    if target is None:
        match = _REL_MINUTES_RE.search(raw)
        if match:
            target = current + timedelta(minutes=int(match.group(1)))
    if target is None:
        match = _REL_HOURS_RE.search(raw)
        if match:
            target = current + timedelta(hours=int(match.group(1)))
    if target is None:
        match = _ABS_TIME_RE.search(raw)
        if match:
            day_word, period, hour_text, minute_text = match.groups()
            hour = int(hour_text)
            minute = int(minute_text) if minute_text else 0
            if period in {"下午", "傍晚", "晚上"} and hour < 12:
                hour += 12
            if period == "凌晨" and hour == 12:
                hour = 0
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                return None
            day_offset = _DAY_OFFSETS.get(day_word or "", 0)
            candidate = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
            candidate += timedelta(days=day_offset)
            if day_word is None and candidate <= current:
                candidate += timedelta(days=1)  # 无明确日词且已过点 → 顺延明天
            target = candidate
    if target is None:
        match = _PERIOD_ONLY_RE.search(raw)
        if match:
            day_word, period = match.groups()
            hour, minute = _PERIOD_DEFAULTS[period]
            day_offset = _DAY_OFFSETS.get(day_word or "", 0)
            candidate = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
            candidate += timedelta(days=day_offset)
            if day_word is None and candidate <= current:
                candidate += timedelta(days=1)
            target = candidate
    if target is None or target <= current:
        return None

    content = _CLEAN_RE.sub(" ", raw)
    content = re.sub(r"\s+", " ", content).strip(" ，,。！!？?、")
    if not content:
        content = "你之前在等的那件事"
    return ReminderIntent(remind_at=target, text=content[:120], label=_format_when(target, current))


def _format_when(target: datetime, current: datetime) -> str:
    delta_days = (target.date() - current.date()).days
    day_label = {0: "今天", 1: "明天", 2: "后天"}.get(delta_days, "那一天")
    return f"{day_label} {target.hour:02d}:{target.minute:02d}"


def build_reminder_text(reminder: Reminder) -> str:
    """到点督促的文案（守岸人语气，温柔不啰嗦）。"""
    return (
        "（远处的海浪声）……到时间了。\n"
        f"你之前说过的：{reminder.text}。\n"
        "我就守在这里。慢一点也没关系，记得去做。"
    )


class ReminderStore:
    """SQLite 待办提醒 store（WAL 先于 DDL；单连接 + threading.Lock）。"""

    def __init__(self, path: str | Path, *, max_pending_per_session: int = 20) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._max_pending = max(1, int(max_pending_per_session))
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reminders (
                    reminder_id TEXT PRIMARY KEY,
                    session_key TEXT NOT NULL,
                    sender_id TEXT NOT NULL DEFAULT '',
                    target_scope TEXT NOT NULL DEFAULT 'group',
                    target_id TEXT NOT NULL DEFAULT '',
                    adapter TEXT NOT NULL DEFAULT '',
                    bot_id TEXT NOT NULL DEFAULT '',
                    remind_at TEXT NOT NULL,
                    text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(status, remind_at)"
            )

    def add(
        self,
        *,
        session_key: str,
        sender_id: str,
        target_scope: str,
        target_id: str,
        adapter: str,
        bot_id: str,
        remind_at: datetime,
        text: str,
    ) -> Reminder:
        created = datetime.now(UTC).isoformat()
        reminder_id = sha1(
            f"{session_key}:{remind_at.isoformat()}:{text}:{created}".encode("utf-8")
        ).hexdigest()[:12]
        with self._lock, self._conn:
            pending = self._conn.execute(
                "SELECT COUNT(*) FROM reminders WHERE session_key = ? AND status = 'pending'",
                (session_key,),
            ).fetchone()[0]
            if int(pending or 0) >= self._max_pending:
                self._conn.execute(
                    "DELETE FROM reminders WHERE reminder_id = ("
                    " SELECT reminder_id FROM reminders WHERE session_key = ?"
                    " AND status = 'pending' ORDER BY remind_at ASC LIMIT 1)",
                    (session_key,),
                )
            self._conn.execute(
                "INSERT INTO reminders (reminder_id, session_key, sender_id, target_scope,"
                " target_id, adapter, bot_id, remind_at, text, status, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
                (reminder_id, session_key, sender_id, target_scope, target_id, adapter,
                 bot_id, remind_at.isoformat(), text, created),
            )
        return Reminder(
            reminder_id=reminder_id, session_key=session_key, sender_id=sender_id,
            target_scope=target_scope, target_id=target_id, adapter=adapter,
            bot_id=bot_id, remind_at=remind_at.isoformat(), text=text,
            status="pending", created_at=created,
        )

    def due(self, *, now: datetime | None = None, grace_hours: int = 24) -> list[Reminder]:
        current = now or datetime.now(UTC)
        floor = (current - timedelta(hours=grace_hours)).isoformat()
        with self._lock:
            rows = self._conn.execute(
                "SELECT reminder_id, session_key, sender_id, target_scope, target_id,"
                " adapter, bot_id, remind_at, text, status, created_at"
                " FROM reminders WHERE status = 'pending' AND remind_at <= ?"
                " ORDER BY remind_at ASC LIMIT 20",
                (current.isoformat(),),
            ).fetchall()
            expired = self._conn.execute(
                "SELECT COUNT(*) FROM reminders WHERE status = 'pending' AND remind_at < ?",
                (floor,),
            ).fetchone()[0]
        if expired:
            with self._lock, self._conn:
                self._conn.execute(
                    "UPDATE reminders SET status = 'expired'"
                    " WHERE status = 'pending' AND remind_at < ?",
                    (floor,),
                )
        return [
            Reminder(
                reminder_id=str(row[0]), session_key=str(row[1]), sender_id=str(row[2]),
                target_scope=str(row[3]), target_id=str(row[4]), adapter=str(row[5]),
                bot_id=str(row[6]), remind_at=str(row[7]), text=str(row[8]),
                status=str(row[9]), created_at=str(row[10]),
            )
            for row in rows
        ]

    def mark_done(self, reminder_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE reminders SET status = 'done' WHERE reminder_id = ?",
                (reminder_id,),
            )

    def list_pending(self, session_key: str, *, limit: int = 10) -> list[Reminder]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT reminder_id, session_key, sender_id, target_scope, target_id,"
                " adapter, bot_id, remind_at, text, status, created_at"
                " FROM reminders WHERE session_key = ? AND status = 'pending'"
                " ORDER BY remind_at ASC LIMIT ?",
                (session_key, limit),
            ).fetchall()
        return [
            Reminder(
                reminder_id=str(row[0]), session_key=str(row[1]), sender_id=str(row[2]),
                target_scope=str(row[3]), target_id=str(row[4]), adapter=str(row[5]),
                bot_id=str(row[6]), remind_at=str(row[7]), text=str(row[8]),
                status=str(row[9]), created_at=str(row[10]),
            )
            for row in rows
        ]

    def cancel(self, reminder_id: str) -> bool:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "UPDATE reminders SET status = 'cancelled'"
                " WHERE reminder_id = ? AND status = 'pending'",
                (reminder_id,),
            )
        return bool(cursor.rowcount)

    def close(self) -> None:
        self._conn.close()


_STORES: dict[str, ReminderStore] = {}
_STORES_LOCK = threading.Lock()


def build_reminder_store(config: object) -> ReminderStore:
    """进程级共享提醒 store（能力与每分钟调度任务共用，避免连接泄漏）。"""
    from plugins.bot_unified_runtime.character.providers import build_runtime_data_path

    db_path = str(
        build_runtime_data_path(
            config, str(getattr(config, "bot_reminder_db_path", "data/reminders.sqlite3"))
        )
    )
    with _STORES_LOCK:
        store = _STORES.get(db_path)
        if store is None:
            store = ReminderStore(db_path)
            _STORES[db_path] = store
        return store
