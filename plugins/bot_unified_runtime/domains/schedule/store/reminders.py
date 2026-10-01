"""时间点记忆→主动提醒（reminders）：记住用户"几点要做什么"，到点温柔督促。

设计（对应需求"用户表示中午12点要写作业，机器人应在12点温柔地督促"）：
- 双轨解析：①显式命令/自然语言含「提醒/叫我」+ 时间表达 → 确定性正则解析
  （低误报）；②进阶轨留接口（LLM 轮末抽取同 memory_extract 模式）。
- 存储与投递解耦：本模块只管 SQLite 与解析；到点投递由 __init__ 的
  每分钟调度任务构造 SendRequest 走统一发送队列（语气由人格文案承担）。
- 绝不打扰失控：单会话待办上限、过期治理（迟到 >30 分钟顺延、
  >24h 作废）、取消可用。
- 治理不静默（A-05，2026-09-15）：顺延/作废各按会话折成至多一句守岸人
  短句回执，随 ``due()`` 的既有投递路径主动送达（见
  ``_build_governance_receipts``）。
- 时区口径（2026-09-13 修复，2026-09-17 V2.1 风险 7 再修）：全链路统一
  **配置时区**（``config.bot_timezone``，IANA 名；缺省与 config.py 一致）。
  naive 输入按配置时区解释，aware 一律换算到配置时区再比较/落库——
  墙钟推算（"明天9点"）与到点判定不再依赖进程本地时区，UTC 服务器上
  不再错位。装配期经 ``build_reminder_store`` → ``configure_reminder_timezone``
  绑定真实配置。到点判定用 aware datetime 的时刻比较，**禁止 ISO 字符串
  字典序比较**——旧实现拿 ``+08:00`` 存储串与 ``datetime.now(UTC)`` 串直接
  比字典序，跨时区早/晚触发 8 小时，且离线错过后的补投递没有过期检查
  （凌晨的提醒下午才"到时间了"）。
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from hashlib import sha1
from pathlib import Path
from zoneinfo import ZoneInfo

_REMIND_SIGNAL_RE = re.compile(r"提醒|叫我|记得叫|記得叫")

logger = logging.getLogger(__name__)

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
# 「明早」= 次日（LEDGER-b：缺席时「明早8点」按裸「8点」解析，上午场景
# 错记今天）；带具体时刻保持次日上午语义（时段词缺省不加 12）。
_DAY_OFFSETS = {"今天": 0, "今晚": 0, "今早": 0, "明天": 1, "明晚": 1, "明早": 1, "后天": 2}

_ABS_TIME_RE = re.compile(
    r"(今天|明天|后天|今晚|今早|明晚|明早)?\s*(凌晨|早上|上午|中午|下午|傍晚|晚上)?\s*"
    r"(\d{1,2})\s*[点點時时:：]\s*(?:(\d{1,2})\s*分?|(半))?"
)
_PERIOD_ONLY_RE = re.compile(r"(今天|明天|后天|今晚|今早|明晚|明早)?\s*(凌晨|早上|上午|中午|下午|傍晚|晚上)(?![点點時时:：\d])")
_REL_MINUTES_RE = re.compile(r"(\d{1,3})\s*分钟后")
_REL_HOURS_RE = re.compile(r"(\d{1,2})\s*(?:个)?小时后")
_REL_HALF_HOUR_RE = re.compile(r"半(?:个)?小时后")
_CLEAN_RE = re.compile(r"提醒我?|叫我|记得叫|記得叫|一下|吧|哦|呀|啊|，|,|。|！|!|？|\?")

# 迟到投递容忍窗：到点后 30 分钟内仍照常投递（跨过投递巡检间隙）；
# 超过则视为"离线错过"，不再原样补投（见 ReminderStore.due）。
LATE_DELIVERY_GRACE = timedelta(minutes=30)

# A2 修复席（2026-09-27）：per-sender 待办子闸缺省——同一会话内单人挂账
# 上限。会话总量闸（``ReminderStore._max_pending``，缺省 20）保留原样，
# 本值由能力层显式以 ``max_pending_for_sender`` 传入 ``add``/``add_checked``
# 生效；不传（直构 store 的抽取腿/测试夹具等调用面）维持既有行为。
# 刻意**不新增 config 键**；要配置化走提案，不在此处改口径。
MAX_PENDING_PER_SENDER = 5


def _local_now() -> datetime:
    """统一本地时区口径的"现在"（aware、进程本地时区）。

    2026-09-13 六域批起「现在」一律经 timesync（联网授时，v21r2 W10 起真身
    domains/schedule/timesync/）校正：
    未绑定配置/校准失败/未启用时回退系统钟，语义与原实现完全一致；
    绝不改系统钟，只在校正过的时刻上做比较。惰性导入防 runtime 包
    __init__（pipeline）与能力层形成导入环。
    """
    from plugins.bot_unified_runtime.domains.schedule.timesync import timesync

    return timesync.now()


def _as_local(moment: datetime) -> datetime:
    """naive 视为配置时区；aware 换算到配置时区。全模块唯一的时刻归一口径。

    V2.1 风险 7 修复（2026-09-17）：旧实现 ``moment.astimezone()`` 落在
    进程本地时区、从不读 ``config.bot_timezone``，UTC 服务器上"明天9点"
    的墙钟推算可差一整天；现统一走配置时区（与 TemporalProvider 的
    本地时间口径一致）。
    """
    if moment.tzinfo is None:
        return moment.replace(tzinfo=_bot_zone())
    return moment.astimezone(_bot_zone())


# 配置时区绑定（缺省与 config.bot_timezone 缺省一致）：进程级可重绑定，
# 装配期由 ``build_reminder_store`` 调 ``configure_reminder_timezone`` 写入。
# str 读无锁安全（CPython 原子名绑定）；绑定失败保持原值不炸提醒链。
_DEFAULT_BOT_TIMEZONE = "Asia/Hong_Kong"
_TZ_NAME: str = _DEFAULT_BOT_TIMEZONE
_TZ_LOCK = threading.Lock()


def configure_reminder_timezone(tz_name: str) -> None:
    """绑定提醒链路的配置时区（IANA 名；装配期调用，幂等可重复）。

    传入空串（测试用局部 config 缺字段）不改动当前绑定；名字解析失败
    同样保持原值——pydantic 已校验生产配置，这里只防垃圾串毒化缺省。
    """
    global _TZ_NAME
    candidate = str(tz_name or "").strip()
    if not candidate:
        return
    try:
        ZoneInfo(candidate)
    except Exception:  # noqa: BLE001 - 非法时区名保持原绑定，提醒链绝不因时区崩。
        return
    with _TZ_LOCK:
        _TZ_NAME = candidate


def _bot_zone() -> tzinfo:
    """当前生效的配置时区；解析失败退回进程本地时区（绝不让提醒链崩）。"""
    try:
        return ZoneInfo(_TZ_NAME)
    except Exception:  # noqa: BLE001 - 同上：时区不可用是环境病态，按本地兜底。
        local = datetime.now().astimezone().tzinfo
        return local if local is not None else timezone.utc


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


# ---------------------------------------------------------------------------
# 治理回执（A-05，2026-09-15）：顺延/作废不再静默——due() 把本轮被治理的
# 提醒按会话折成至多一句守岸人短句，合成带 ``gov-`` 前缀 id 的回执
# Reminder 搭既有投递路径主动送达（调度器内联投递，不改 __init__ 契约）。
# 节流哲学：同会话一次治理扫描至多一条（群聊多条错过也不刷屏）；每条被
# 治理提醒只进一次归集，回执天然不重复。送达侧照常 mark_done，对回执 id
# 是无害空操作，绝不动真提醒的待办状态。模板池形态对齐
# capabilities/user_copy.py 的池惯例；选句走本模块 A-13 的确定性散列
# （零随机）。
# ---------------------------------------------------------------------------
_GOVERNANCE_RECEIPT_ID_PREFIX = "gov-"

# {items}=顺延/作废事项串；mixed 另有 {dropped}=作废事项串。
_GOVERNANCE_RECEIPT_TEMPLATES: dict[str, tuple[str, ...]] = {
    "postponed": (
        (
            "（潮声轻轻）你不在的时候，「{items}」到了时间，"
            "我没能在对的一刻叫你。\n"
            "我把它挪到了明天同一个时刻——到点我会再提醒你一次。"
        ),
        (
            "……「{items}」到点的时候你不在。\n"
            "迟到的催促太生硬了，先把它放到明天同一个时间。"
            "我记着，到点再来叫你。"
        ),
    ),
    "expired": (
        (
            "（翻了翻清单）「{items}」隔得太久了，大概已经不需要我催。\n"
            "我先替你放下——要是还想续上，再跟我说一声就好。"
        ),
        (
            "「{items}」等了一天也没等到人，我想它多半已经过去了。\n"
            "替你从待办里放下；要是其实还没有，再告诉我一遍时间就好。"
        ),
    ),
    "mixed": (
        (
            "（潮声很轻）你不在的时候，「{items}」错过了时间，"
            "我把它挪到了明天同一个时刻。\n"
            "另有「{dropped}」隔得太久，我猜已经不用我催，先替你放下。"
        ),
    ),
}

_RECEIPT_ITEM_MAX_CHARS = 30
_RECEIPT_MAX_ITEMS = 3


def _receipt_items_label(texts: list[str]) -> str:
    """回执里的事项串：「A」「B」……超 3 件折叠为「等 N 件」，单件截断。"""
    labels: list[str] = []
    for text in texts[:_RECEIPT_MAX_ITEMS]:
        clipped = str(text or "").strip()[:_RECEIPT_ITEM_MAX_CHARS]
        if len(clipped) < len(str(text or "").strip()):
            clipped += "…"
        labels.append(f"「{clipped}」")
    if len(texts) > _RECEIPT_MAX_ITEMS:
        labels.append(f"等 {len(texts)} 件")
    return "".join(labels)


@dataclass
class _GovernedSession:
    """一次 due() 轮次里某会话被治理提醒的归集（回执的路由与成句素材）。"""

    reminder: Reminder  # 任一条被治理提醒（回执沿用其路由字段）
    postponed: list[str] = field(default_factory=list)
    expired: list[str] = field(default_factory=list)


def _build_governance_receipts(
    governed: dict[str, _GovernedSession], *, current: datetime
) -> list[Reminder]:
    """把本轮治理结果折成每会话至多一条回执提醒（守岸人语气短句）。

    回执是合成的 ``Reminder``：id 带 ``gov-`` 前缀（真 id 是 sha1 十六进
    制，永不撞前缀），``build_reminder_text`` 对它原样放行。投递失败时
    回执不重发（治理动作本身已在库内落定，回执只是告知，best-effort）。
    """
    receipts: list[Reminder] = []
    for session_key, info in governed.items():
        if info.postponed and info.expired:
            kind = "mixed"
            body = _pick_template_variant(
                _GOVERNANCE_RECEIPT_TEMPLATES["mixed"], "", seed=session_key
            ).format(
                items=_receipt_items_label(info.postponed),
                dropped=_receipt_items_label(info.expired),
            )
        elif info.postponed:
            kind = "postponed"
            body = _pick_template_variant(
                _GOVERNANCE_RECEIPT_TEMPLATES["postponed"], "", seed=session_key
            ).format(items=_receipt_items_label(info.postponed))
        else:
            kind = "expired"
            body = _pick_template_variant(
                _GOVERNANCE_RECEIPT_TEMPLATES["expired"], "", seed=session_key
            ).format(items=_receipt_items_label(info.expired))
        created = datetime.now(UTC).isoformat()
        digest = sha1(
            f"{session_key}:{kind}:{body}:{created}".encode()
        ).hexdigest()[:12]
        source = info.reminder
        receipts.append(
            Reminder(
                reminder_id=f"{_GOVERNANCE_RECEIPT_ID_PREFIX}{digest}",
                session_key=session_key,
                sender_id=source.sender_id,
                target_scope=source.target_scope,
                target_id=source.target_id,
                adapter=source.adapter,
                bot_id=source.bot_id,
                remind_at=_as_local(current).isoformat(),
                text=body,
                status="receipt",
                created_at=created,
            )
        )
    return receipts


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


def configured_timezone() -> str:
    """当前生效的配置时区名（提醒/日程链路唯一时源；V2.1 风险 7 口径的公开读点）。

    日程板（schedule_board）建 plan 时用它当 plan.timezone，保证「她说『明天8点』」
    的墙钟推算、条目落库时区与到点判定同一把尺，不再各绑各的。
    """
    return _TZ_NAME


def _first_time_target(raw: str, current: datetime) -> datetime | None:
    """时间表达级联解析（相对分钟/小时 → 绝对「X点Y分」→ 时段词），返回目标时刻或 None。

    2026-09-26 第 20 项波：本函数由 ``parse_reminder_intent`` 的级联体**逐字抽出**
    （分支顺序、下午/晚间 +12h 语义、REM-EVE 日词档、边界与顺延规则一字未动），
    提醒与自然语言日程共用这唯一一份解析器——日程侧禁第二解析器（AGENTS 无第二真身）。
    ``raw`` 为整句原文，``current`` 必须已是配置时区 aware（调用方负责）。
    """
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
            day_word, period, hour_text, minute_text, half = match.groups()
            hour = int(hour_text)
            # 「7点半」= 7:30（审查 A-09：旧正则没有「半」分支，会落到 7:00）。
            minute = 30 if half else (int(minute_text) if minute_text else 0)
            if period in {"下午", "傍晚", "晚上"} and hour < 12:
                hour += 12
            if period == "凌晨" and hour == 12:
                hour = 0
            # 「今晚/明晚」日词自带晚间档（REM-EVE）：无时段词且显式时刻
            # 落在 1-11 点时按口语归 20 点档——「明晚8点」= 次日 20:00，
            # 与「明天晚上8点」同解。保守边界：显式 ≥12 时辰不改字面
            # （「晚上20点」「明晚12点」按用户写法），只记日志。
            if not period and day_word in {"今晚", "明晚"}:
                if 1 <= hour <= 11:
                    logger.info(
                        "reminder parse: %s%d点无时段词，按晚间语义 +12h", day_word, hour
                    )
                    hour += 12
                else:
                    logger.info(
                        "reminder parse: %s%d点保持字面（显式 ≥12 时辰不调整）",
                        day_word,
                        hour,
                    )
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
    return target


def parse_time_target(text: str, *, now: datetime | None = None) -> datetime | None:
    """公开口：任意句子 → 第一个可解析的**未来**时刻（配置时区 aware）；解不出 → None。

    与 ``parse_reminder_intent`` 共享同一份级联（``_first_time_target``，零第二解析器），
    差别只在**不要求提醒信号词**且不清洗正文——日程板用它把「明天8点有课」的
    时间点解出来，正文另由 span 剥离完成（复用同一批编译正则，见 schedule_board）。
    已过点的表达（无日词且今天该时刻已过）按级联既有语义顺延到明天，恒返回未来时刻。
    """
    raw = (text or "").strip()
    if not raw:
        return None
    current = _as_local(_local_now() if now is None else now)
    target = _first_time_target(raw, current)
    if target is None or target <= current:
        return None
    return _as_local(target)


def parse_reminder_intent(text: str, *, now: datetime | None = None) -> ReminderIntent | None:
    """解析「X点提醒我/叫我做Y」。无提醒信号或无时间表达 → None。

    ``now`` 缺省=配置时区当前时刻（经 timesync 校正）；naive 按配置时区
    解释；aware 注入（含 UTC）一律先换算到**配置时区**再做墙钟推算
    （"X点"= 配置时区的 X 点整，V2.1 风险 7 修复：跨时区部署不再按
    注入时刻/进程本地时区推错一天）。结果统一以配置时区落库，后续
    比较一律走时刻（instant）语义。

    2026-09-26 波：级联计算收进 ``_first_time_target``（唯一解析器，与日程共用），
    本函数行为逐字节不变（提醒全家桶既有测试为回归锁）。
    """
    raw = (text or "").strip()
    if not raw or not _REMIND_SIGNAL_RE.search(raw):
        return None
    current = _as_local(_local_now() if now is None else now)

    target = _first_time_target(raw, current)
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

    @property
    def max_pending(self) -> int:
        """单会话待办上限（公开只读，供能力层文案与测试引用）。"""
        return self._max_pending

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
        max_pending_for_sender: int | None = None,
    ) -> Reminder | None:
        """带配额判定的新增（兼容口）：只回结果对象，配额理由见
        ``add_checked``。行为与 A-07 一致：超限拒绝、绝不静默挤掉最旧一条。"""
        reminder, _reason = self.add_checked(
            session_key=session_key, sender_id=sender_id, target_scope=target_scope,
            target_id=target_id, adapter=adapter, bot_id=bot_id,
            remind_at=remind_at, text=text,
            max_pending_for_sender=max_pending_for_sender,
        )
        return reminder

    def add_checked(
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
        max_pending_for_sender: int | None = None,
    ) -> tuple[Reminder | None, str]:
        """两层配额判定的新增，返回 ``(reminder, reason)``。

        ``reason`` ∈ ``{"", "session_full", "sender_full"}``（""=成功）。
        会话总量闸（``self._max_pending``）优先于 per-sender 子闸
        （``max_pending_for_sender``，A2）：两层同时踩满时报 session_full——
        此时取消本人一条也仍挤不进，先报更大的闸更可行动。子闸不传即不判
        （直构调用面行为不变）。COUNT→INSERT 同在 ``self._lock`` 临界区，
        两层判定都无进程内竞态。
        """
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
                # 审查 A-07：超限不再静默删最旧的一条（用户以为都记着，其实
                # 丢了）——改为拒绝新增并返回 None，由能力层提示用户先取消。
                return None, "session_full"
            if max_pending_for_sender is not None:
                # A2 子闸：群会话共享配额下，单成员连发不同正文可占满整组
                # 预算（24h 正文去重键含正文，逐条换词即绕过）。per-sender
                # 计数封住这条 DoS-by-design 面。
                sender_pending = self._conn.execute(
                    "SELECT COUNT(*) FROM reminders"
                    " WHERE session_key = ? AND sender_id = ? AND status = 'pending'",
                    (session_key, sender_id),
                ).fetchone()[0]
                if int(sender_pending or 0) >= max(1, int(max_pending_for_sender)):
                    return None, "sender_full"
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
        ), ""

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
        - 治理回执（A-05）：顺延/作废各按会话折成至多一句守岸人短句，
          以 ``gov-`` 前缀合成 Reminder 附在返回值尾部，搭既有投递路径
          主动告知；真提醒与回执按 id 前缀即可区分。
        """
        current = _as_local(now) if now is not None else _as_local(_local_now())
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
        governed: dict[str, _GovernedSession] = {}
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
                governed.setdefault(
                    reminder.session_key, _GovernedSession(reminder)
                ).expired.append(reminder.text)
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
                governed.setdefault(
                    reminder.session_key, _GovernedSession(reminder)
                ).postponed.append(reminder.text)
            else:
                expired.append(reminder.reminder_id)
                governed.setdefault(
                    reminder.session_key, _GovernedSession(reminder)
                ).expired.append(reminder.text)
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
        return delivered + _build_governance_receipts(governed, current=current)

    def mark_done(self, reminder_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE reminders SET status = 'done' WHERE reminder_id = ?",
                (reminder_id,),
            )

    def list_pending(
        self,
        session_key: str,
        *,
        limit: int = 10,
        sender_id: str | None = None,
    ) -> list[Reminder]:
        """会话待办清单。``sender_id`` 传入时只列该归属人（A2 隐私面：
        群内列表/取消按本人归属查询）；None=整会话，私聊与管理面照旧。"""
        sql = (
            "SELECT reminder_id, session_key, sender_id, target_scope, target_id,"
            " adapter, bot_id, remind_at, text, status, created_at"
            " FROM reminders WHERE session_key = ? AND status = 'pending'"
        )
        params: list[object] = [session_key]
        if sender_id is not None:
            sql += " AND sender_id = ?"
            params.append(sender_id)
        sql += " ORDER BY remind_at ASC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, tuple(params)).fetchall()
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
    from plugins.bot_unified_runtime.domains.schedule.timesync import timesync

    # 提醒链路的"现在"统一经 timesync：真实配置绑定于此（含每分钟调度
    # 任务），字段缺失（测试局部 config）时 timesync 保持禁用零联网。
    timesync.configure_from(config)
    # 时区口径绑定（V2.1 风险 7）：_as_local/墙钟推算统一走 config.bot_timezone；
    # 字段缺失时保持当前绑定（进程级只绑定一次，缺省= config 缺省值）。
    configure_reminder_timezone(str(getattr(config, "bot_timezone", "") or ""))
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
# 审查 A-13（2026-09-14 收口）：字面收进模块级模板常量表
# （分型 → 变体元组），只挪位置不改任何文案字面（分型批测试已逐字锁定）；
# 同型多变体时按 persona 口径稳定选一，单变体行为与历史完全一致。
_REMINDER_TEXT_TEMPLATES: dict[str, tuple[str, ...]] = {
    "medicine": (
        (
            "……到时间了，该吃药了。\n"
            "你之前说过的：{text}。\n"
            "喝口水，慢慢来。身体的事，不能总交给以后。我陪着你。"
        ),
    ),
    "appointment": (
        (
            "（频率轻轻响了一声，像钟摆）时间到了。\n"
            "你之前说过的：{text}。\n"
            "这一件有时间在前面等着，别让它等太久。去吧，我守在这里。"
        ),
    ),
    "shopping": (
        (
            "到点了。\n"
            "你之前说过的：{text}。\n"
            "要带走的东西，别落在世界的另一头。回来的时候，海还在这边。"
        ),
    ),
    "todo": (
        (
            "（潮声很轻）到时间了。\n"
            "你之前说过的：{text}。\n"
            "一步一步来就好，不着急。我守在这里。"
        ),
    ),
    "custom": (
        (
            "（远处的海浪声）……到时间了。\n"
            "你之前说过的：{text}。\n"
            "我就守在这里。慢一点也没关系，记得去做。"
        ),
    ),
}


def _pick_template_variant(
    variants: tuple[str, ...], persona_profile_id: str, seed: str
) -> str:
    """多变体时按 (persona, seed) 稳定散列取模选一（确定性、零随机）；
    单变体恒取首个——当前各型均为单变体，persona 缺省时行为不变。"""
    if len(variants) == 1:
        return variants[0]
    digest = sha1(f"{persona_profile_id}\x00{seed}".encode()).digest()
    return variants[digest[0] % len(variants)]


def build_reminder_text(reminder: Reminder, *, persona_profile_id: str = "") -> str:
    """到点督促的文案（守岸人语气，温柔不啰嗦；按用途分型选模板）。

    persona_profile_id 为可选选型键（A-13 收口：此前它只在 SendRequest
    透传、未参与文案分型）：同型多变体时参与稳定散列选变体；缺省空串
    退化为「恒取首个变体」，文案字面与既有完全一致。
    """
    if reminder.reminder_id.startswith(_GOVERNANCE_RECEIPT_ID_PREFIX):
        # A-05 治理回执：文案在 due() 里已按池成句，原样放行——绝不套
        # 分型模板（回执事项里带「吃药」等关键词也不许被误包装）。
        return reminder.text
    text = str(reminder.text or "")
    kind = classify_reminder_kind(text)
    variants = _REMINDER_TEXT_TEMPLATES.get(kind) or _REMINDER_TEXT_TEMPLATES["custom"]
    template = _pick_template_variant(variants, persona_profile_id, seed=text)
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
# 审查 A-10：唯一候选也要"够像"才许直接勾。0.667（「买牛奶」vs「买酸奶」
# 编辑距离 1）这类"有点像"过去会被当成命中直接勾掉——用户说牛奶我们勾了
# 酸奶。低于此线的唯一候选改判 ``uncertain``，由能力层追问一句「是这件吗」。
# 包含关系日常短词不受影响：「作业」vs「写作业」= 0.7+0.3×(2/4) = 0.85 ≥ 0.8。
SINGLE_CONFIRM_SCORE = 0.8


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
    single_confirm_score: float = SINGLE_CONFIRM_SCORE,
) -> tuple[str, list[int]]:
    """勾选裁决：返回 (outcome, 索引列表)。

    - ``"hit"``：唯一最高分（或与次高分差距 ≥ ambiguity_margin）且分数
      达到 ``single_confirm_score``——够像，直接勾；
    - ``"uncertain"``：唯一过线候选但分数低于 ``single_confirm_score``
      （审查 A-10：唯一候选只是"有点像"时不算数，索引给该候选，能力层
      追问「是这件吗」，回肯定词才勾）；
    - ``"ambiguous"``：并列高分（差距 < margin），索引给前 3 个；
    - ``"miss"``：无人过线。
    """
    ranked = match_todo_candidates(query, names, min_score=min_score)
    if not ranked:
        return "miss", []
    best_score = ranked[0][1]
    tied = [index for index, score in ranked if best_score - score <= ambiguity_margin]
    if len(tied) == 1:
        if best_score < single_confirm_score:
            return "uncertain", tied
        return "hit", tied
    return "ambiguous", tied[:3]
