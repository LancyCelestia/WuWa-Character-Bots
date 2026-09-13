"""时间点记忆→主动提醒（reminders）：记住用户"几点要做什么"，到点温柔督促。

设计（对应需求"用户表示中午12点要写作业，机器人应在12点温柔地督促"）：
- 双轨解析：①显式命令/自然语言含「提醒/叫我」+ 时间表达 → 确定性正则解析
  （低误报）；②进阶轨留接口（LLM 轮末抽取同 memory_extract 模式）。
- 存储与投递解耦：本模块只管 SQLite 与解析；到点投递由 __init__ 的
  每分钟调度任务构造 SendRequest 走统一发送队列（语气由人格文案承担）。
- 绝不打扰失控：单会话待办上限、过期治理（迟到 >30 分钟顺延、
  >24h 作废）、取消可用。
- 时区口径（2026-09-13 修复）：全链路统一**进程本地时区**（naive 视为
  本地，aware 一律转本地再比较/落库）。到点判定用 aware datetime 的
  时刻比较，**禁止 ISO 字符串字典序比较**——旧实现拿 ``+08:00`` 存储
  串与 ``datetime.now(UTC)`` 串直接比字典序，跨时区早/晚触发 8 小时，
  且离线错过后的补投递没有过期检查（凌晨的提醒下午才"到时间了"）。
"""

from __future__ import annotations

import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha1
from pathlib import Path

_REMIND_SIGNAL_RE = re.compile(r"提醒|叫我|记得叫|記得叫")
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
    r"(\d{1,2})\s*[点點時时:：]\s*(\d{1,2})?\s*分?"
)
_PERIOD_ONLY_RE = re.compile(r"(今天|明天|后天|今晚|今早|明晚)?\s*(凌晨|早上|上午|中午|下午|傍晚|晚上)(?![点點時时:：\d])")
_REL_MINUTES_RE = re.compile(r"(\d{1,3})\s*分钟后")
_REL_HOURS_RE = re.compile(r"(\d{1,2})\s*(?:个)?小时后")
_REL_HALF_HOUR_RE = re.compile(r"半(?:个)?小时后")
_CLEAN_RE = re.compile(r"提醒我?|叫我|记得叫|記得叫|一下|吧|哦|呀|啊|，|,|。|！|!|？|\?")

# 迟到投递容忍窗：到点后 30 分钟内仍照常投递（跨过投递巡检间隙）；
# 超过则视为"离线错过"，不再原样补投（见 ReminderStore.due）。
LATE_DELIVERY_GRACE = timedelta(minutes=30)


def _local_now() -> datetime:
    """统一本地时区口径的"现在"（aware、进程本地时区）。

    2026-09-13 六域批起「现在」一律经 runtime/timesync（联网授时）校正：
    未绑定配置/校准失败/未启用时回退系统钟，语义与原实现完全一致；
    绝不改系统钟，只在校正过的时刻上做比较。惰性导入防 runtime 包
    __init__（pipeline）与能力层形成导入环。
    """
    from plugins.bot_unified_runtime.runtime import timesync

    return timesync.now()


def _as_local(moment: datetime) -> datetime:
    """naive 视为本地时间；aware 转本地时区。全模块唯一的时刻归一口径。"""
    return moment.astimezone()


def _parse_stored_moment(raw: str) -> datetime | None:
    """存储串 -> 本地 aware 时刻；解析失败返回 None（按过期治理）。"""
    try:
        moment = datetime.fromisoformat(str(raw or "").strip())
    except ValueError:
        return None
    return _as_local(moment)


def _next_occurrence(remind_at: datetime, current: datetime) -> datetime:
    """错过的提醒顺延到「下一个同一时刻」（通常即明天同一时刻）。

    以 now 所在日期的同一墙钟时刻为候选；若该时刻已过（如 23:00 的提醒
    23:45 才被捡起），顺延一天。统一本地时区口径。
    """
    wall = _as_local(remind_at)
    base = _as_local(current)
    candidate = base.replace(
        hour=wall.hour, minute=wall.minute, second=wall.second, microsecond=0
    )
    if candidate <= base:
        candidate += timedelta(days=1)
    return candidate


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
    """解析「X点提醒我/叫我做Y」。无提醒信号或无时间表达 → None。

    ``now`` 缺省=本地当前时刻；naive 视为本地；aware 注入沿用其时区做墙钟
    推算（"X点"= 该时刻所在时区的 X 点整）。结果统一转**本地时区**落库，
    后续比较一律走时刻（instant）语义。
    """
    raw = (text or "").strip()
    if not raw or not _REMIND_SIGNAL_RE.search(raw):
        return None
    if now is None:
        current = _local_now()
    elif now.tzinfo is None:
        current = _as_local(now)  # naive 视为本地时间。
    else:
        current = now

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
    return ReminderIntent(
        remind_at=_as_local(target), text=content[:120], label=_format_when(target, current)
    )


def _format_when(target: datetime, current: datetime) -> str:
    delta_days = (target.date() - current.date()).days
    day_label = {0: "今天", 1: "明天", 2: "后天"}.get(delta_days, "那一天")
    return f"{day_label} {target.hour:02d}:{target.minute:02d}"


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
        # 落库统一本地时区口径（naive 视为本地），后续到点判定做时刻比较。
        stored_at = _as_local(remind_at)
        reminder_id = sha1(
            f"{session_key}:{stored_at.isoformat()}:{text}:{created}".encode()
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
                 bot_id, stored_at.isoformat(), text, created),
            )
        return Reminder(
            reminder_id=reminder_id, session_key=session_key, sender_id=sender_id,
            target_scope=target_scope, target_id=target_id, adapter=adapter,
            bot_id=bot_id, remind_at=stored_at.isoformat(), text=text,
            status="pending", created_at=created,
        )

    def due(self, *, now: datetime | None = None, grace_hours: int = 24) -> list[Reminder]:
        """到点提醒 + 过期治理（2026-09-13 修复早/晚触发与无检查补投递）。

        - 时刻比较：存储串（可能混有时区偏移）一律先解析成 aware datetime
          再比较，不再做 ISO 字符串字典序比较（旧实现 +08:00 存储串 vs
          UTC now 串，会晚 8 小时触发、且让过期判定同样错档）。
        - 迟到 ≤ ``LATE_DELIVERY_GRACE``（30 分钟）→ 照常投递（跨过巡检
          间隙的正常情况）。
        - 迟到 > 30 分钟但未超 ``grace_hours`` → **不顺延原样补投**：离线
          错过几个小时的提醒，"到时间了"此时是误导（事情多半已做或窗口
          已过），用户需要的也不是迟到的催促——顺延到下一个同一时刻再
          温柔提醒，宁可晚一天也不在错误的时间点打扰。
        - 迟到超 ``grace_hours``（默认 24h）→ 标记 expired 作废。
        """
        current = _as_local(now) if now is not None else _local_now()
        grace = timedelta(hours=max(1, int(grace_hours)))
        with self._lock:
            rows = self._conn.execute(
                "SELECT reminder_id, session_key, sender_id, target_scope, target_id,"
                " adapter, bot_id, remind_at, text, status, created_at"
                " FROM reminders WHERE status = 'pending'"
                " ORDER BY remind_at ASC LIMIT 200",
            ).fetchall()
        delivered: list[Reminder] = []
        postponed: list[tuple[str, str]] = []
        expired: list[str] = []
        for row in rows:
            reminder = Reminder(
                reminder_id=str(row[0]), session_key=str(row[1]), sender_id=str(row[2]),
                target_scope=str(row[3]), target_id=str(row[4]), adapter=str(row[5]),
                bot_id=str(row[6]), remind_at=str(row[7]), text=str(row[8]),
                status=str(row[9]), created_at=str(row[10]),
            )
            remind_at = _parse_stored_moment(reminder.remind_at)
            if remind_at is None:
                # 历史脏数据（解析不出时刻）无法判定到点，按过期治理。
                expired.append(reminder.reminder_id)
                continue
            late = current - remind_at
            if late <= timedelta(0):
                continue  # 还没到点（含未来提醒）。
            if late <= LATE_DELIVERY_GRACE:
                delivered.append(reminder)
            elif late <= grace:
                postponed.append(
                    (reminder.reminder_id, _next_occurrence(remind_at, current).isoformat())
                )
            else:
                expired.append(reminder.reminder_id)
        if postponed or expired:
            with self._lock, self._conn:
                for reminder_id, next_at in postponed:
                    self._conn.execute(
                        "UPDATE reminders SET remind_at = ?"
                        " WHERE reminder_id = ? AND status = 'pending'",
                        (next_at, reminder_id),
                    )
                for reminder_id in expired:
                    self._conn.execute(
                        "UPDATE reminders SET status = 'expired'"
                        " WHERE reminder_id = ? AND status = 'pending'",
                        (reminder_id,),
                    )
        return delivered

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
    from plugins.bot_unified_runtime.runtime import timesync

    # 提醒链路的"现在"统一经 timesync：真实配置绑定于此（含每分钟调度
    # 任务），字段缺失（测试局部 config）时 timesync 保持禁用零联网。
    timesync.configure_from(config)
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


# ---------------------------------------------------------------------------
# 用途分型 + 差异化语气（2026-09-13 六域批）：按关键词把提醒分成
# 吃药/约会出行/购物/待办/自定义五型，到点投递文案按型切换。语气基准取
# personas/shorekeeper（温柔、克制、海与星的意象、不生硬不 AI 味）。
# ---------------------------------------------------------------------------

REMINDER_KINDS: tuple[str, ...] = (
    "medicine", "appointment", "shopping", "todo", "custom",
)

# 分型关键词（有序，先命中先得；顺序即优先级：健康 > 时间约束 > 采购 > 日常）。
_KIND_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "medicine",
        ("吃药", "服药", "用药", "吃药了", "药", "输液", "打针", "复诊", "体检", "滴眼药"),
    ),
    (
        "appointment",
        (
            "开会", "会议", "上课", "下课", "考试", "面试", "约会", "见面", "出门",
            "出发", "赶车", "赶飞机", "赶船", "航班", "登机", "火车", "高铁", "飞机",
            "上班", "下班", "交表", "截止", "交付", "直播", "网课", "接送",
        ),
    ),
    (
        "shopping",
        ("买", "购物", "下单", "抢购", "秒杀", "快递", "取件", "外卖", "囤", "缴费"),
    ),
    (
        "todo",
        ("写", "做", "复习", "预习", "背", "练", "刷", "锻炼", "运动", "跑步",
         "喝水", "休息", "睡觉", "起床", "收衣服", "晾衣服", "洗澡"),
    ),
)


def classify_reminder_kind(text: str) -> str:
    """按关键词给提醒事项分型（确定性、零依赖；自定义兜底）。"""
    content = str(text or "")
    for kind, keywords in _KIND_KEYWORDS:
        for word in keywords:
            if word in content:
                return kind
    return "custom"


# 到点投递文案：按型切换（守岸人语气；结构与既有默认保持同族——
# 到点信号 + 事项复述 + 温柔的收尾）。custom 沿用历史默认文案。
_KIND_DELIVERY_TEXTS: dict[str, str] = {
    "medicine": (
        "……到时间了，该吃药了。\n"
        "你之前说过的：{text}。\n"
        "喝口水，慢慢来。身体的事，不能总交给以后。我陪着你。"
    ),
    "appointment": (
        "（频率轻轻响了一声，像钟摆）时间到了。\n"
        "你之前说过的：{text}。\n"
        "这一件有时间在前面等着，别让它等太久。去吧，我守在这里。"
    ),
    "shopping": (
        "到点了。\n"
        "你之前说过的：{text}。\n"
        "要带走的东西，别落在世界的另一头。回来的时候，海还在这边。"
    ),
    "todo": (
        "（潮声很轻）到时间了。\n"
        "你之前说过的：{text}。\n"
        "一步一步来就好，不着急。我守在这里。"
    ),
}


def build_reminder_text(reminder: Reminder) -> str:
    """到点督促的文案（守岸人语气，温柔不啰嗦；按用途分型切换）。"""
    text = str(reminder.text or "")
    template = _KIND_DELIVERY_TEXTS.get(
        classify_reminder_kind(text),
        "（远处的海浪声）……到时间了。\n"
        "你之前说过的：{text}。\n"
        "我就守在这里。慢一点也没关系，记得去做。",
    )
    return template.format(text=text)


# ---------------------------------------------------------------------------
# 自然语言勾选的模糊匹配（含勾选对象=未完成提醒 + 笔记待办，见
# capabilities/reminder.py）：包含 + 编辑距离，纯 stdlib、确定性。
# ---------------------------------------------------------------------------

_MATCH_STRIP_RE = re.compile(
    r"[\s，,。！!？?、~～·…\-—_()（）\[\]【】「」『』\"'“”‘’:：;；]+"
)


def normalize_for_match(text: str) -> str:
    """匹配归一：去标点空白 + casefold（中文主体不受影响）。"""
    return _MATCH_STRIP_RE.sub("", str(text or "")).casefold()


def _levenshtein(a: str, b: str, *, cap: int | None = None) -> int:
    """编辑距离（两行滚动 DP；``cap`` 供提前止损，超限返回 cap+1）。"""
    if a == b:
        return 0
    if cap is not None and abs(len(a) - len(b)) > cap:
        return cap + 1
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        row_min = i
        for j, char_b in enumerate(b, start=1):
            cost = 0 if char_a == char_b else 1
            # 经典三源：删除（上）+1、插入（左）+1、替换/相等（左上）+cost。
            # 相等字符的 0 代价必须落在对角线（2026-09-13 勾选回归修复：
            # 原 cost 误加在 previous[j]，对角线恒 +1，"交报告/交周报"
            # 真距离 2 被算成 3，近失提示整条消失）。
            value = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
            current.append(value)
            row_min = min(row_min, value)
        if cap is not None and row_min > cap:
            return cap + 1
        previous = current
    return previous[-1]


def match_similarity(query: str, name: str) -> float:
    """「事项名 vs 待办名」相似度（0~1）：

    - 完全一致 = 1.0；
    - 包含关系（短在长内）= 0.7 + 0.3 × 短/长（"作业" vs "写作业" ≈ 0.9）；
    - 其余按编辑距离比例打分（命中阈值以下自然落空）。
    """
    q = normalize_for_match(query)
    n = normalize_for_match(name)
    if not q or not n:
        return 0.0
    if q == n:
        return 1.0
    if q in n or n in q:
        shorter, longer = (q, n) if len(q) <= len(n) else (n, q)
        return 0.7 + 0.3 * (len(shorter) / len(longer))
    distance = _levenshtein(q, n)
    ratio = 1.0 - distance / max(len(q), len(n))
    return max(0.0, ratio)


MATCH_MIN_SCORE = 0.45
AMBIGUITY_MARGIN = 0.05
NEAR_MISS_FLOOR = 0.3


def match_todo_candidates(
    query: str, names: list[str], *, min_score: float = MATCH_MIN_SCORE
) -> list[tuple[int, float]]:
    """query 对候选名的相似度评分（降序；低于阈值剔除）。"""
    scored = [
        (index, match_similarity(query, name))
        for index, name in enumerate(names)
        if str(name or "").strip()
    ]
    return sorted(
        (item for item in scored if item[1] >= min_score),
        key=lambda item: (-item[1], item[0]),
    )


def resolve_todo_match(
    query: str,
    names: list[str],
    *,
    min_score: float = MATCH_MIN_SCORE,
    ambiguity_margin: float = AMBIGUITY_MARGIN,
) -> tuple[str, list[int]]:
    """勾选裁决：返回 (outcome, 索引列表)。

    - ``"hit"``：唯一最高分（或与次高分差距 ≥ ambiguity_margin）；
    - ``"ambiguous"``：并列高分（差距 < margin），索引给前 3 个；
    - ``"miss"``：无人过线。
    """
    ranked = match_todo_candidates(query, names, min_score=min_score)
    if not ranked:
        return "miss", []
    best_score = ranked[0][1]
    tied = [index for index, score in ranked if best_score - score <= ambiguity_margin]
    if len(tied) == 1:
        return "hit", tied
    return "ambiguous", tied[:3]
