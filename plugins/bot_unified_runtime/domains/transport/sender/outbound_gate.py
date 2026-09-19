"""中央出站防风暴闸（B4-spec §1）——主动投递触达发送队列的唯一中央件。

为什么存在：现役主动投递（提醒 / cookie 到期 / 群摘要 / 日常助理 / 校园转发 /
错误卡补发）全绕开入站门禁——静默与限流长在 `policy/` 入站侧，transport 侧零
命中；唯一的风暴门在未接线的日程 v2 引擎里。本件把「出站侧静默 + 每主体限流 +
去重键规范」收成一处，紧急信息域（`domains/emergency*`）只允许经
`submit_active_push` 触达 `SendQueue.submit`。

设计硬约束（与规格同口径，勿在下游软化）：

- **缺省=现状字节级不动**：`enabled=False` 时直通裸 `submit(send_request)`，零
  判定、零 store 读写、零审计（`OutboundGateSettings.enabled` 缺省 False 是本件
  唯一硬约束）。
- **三门判定顺序**：静默窗 → 每主体限流 → dedupe 键规范，第一个给出结论的门即
  赢。滑窗计数在三门之前**读一次**（纯观测），这样 store 故障的 fail-open 才能在
  静默窗内同样成立（T4 方向锁：闸自身生病绝不允许变成丢消息）。
- **顺延用队列原生 `deliver_after`**（`queue.py` 的 submit 形参），不造第二张
  delay 表；队列实现不认该形参（InMemory 形态）时退化为裸 submit 并挂
  `outbound_gate_degraded`——宁可早发也不丢。
- **不另建去重账**：幂等在队列 `ON CONFLICT(dedupe_key)` 侧，本件只强制键规范。
- **静默窗唯一事实源**：窗设置与 HH:MM 解析全部复用
  `domains/chat_reply/policy/quiet_hours.py`（本文件不写任何时刻字符串解析、
  不造第二套窗判定语义）。
- **不复用日程 v2 引擎实例**（未接线 + schema 深耦合日程语义），只收编其决策
  词汇（allow/defer）与队列原语——见 B4-spec §5 的 G5 裁决。
- 日志与审计零正文：主体一律以 `sha256[:12]` 出现。

时钟 / 设置 / store / 审计 / 告警出口全部装配期注入（离线确定性测试；限流阈值
支持热改，不复刻台账#3「SQLite 限流不支持热改」旧坑）。
"""
from __future__ import annotations

import hashlib
import inspect
import logging
import sqlite3
import threading
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo

from pydantic import Field

from plugins.bot_unified_runtime.domains.chat_reply.policy.quiet_hours import (
    QuietHoursSettings,
    _parse_hhmm,
    build_quiet_hours_settings,
)
from plugins.bot_unified_runtime.domains.core.contracts import (
    AuditRecord,
    DeliveryReceipt,
    OperationalIssue,
    ReceiptState,
    SendRequest,
)
from plugins.bot_unified_runtime.domains.core.contracts.runtime import StrictBaseModel

__all__ = [
    "ActivePushOutcome",
    "OutboundGate",
    "OutboundGateSettings",
    "OutboundGateVerdict",
    "SQLiteOutboundSendStore",
    "build_outbound_gate",
    "build_outbound_gate_settings",
    "dedupe_key_shape_ok",
    "submit_active_push",
]

_logger = logging.getLogger(__name__)

# 稳定机读短语（进审计/日志/告警，禁含正文）。
REASON_DISABLED = "disabled"
REASON_ALLOWED = "allowed"
REASON_QUIET = "quiet_hours"
REASON_RATE_MINUTE = "rate_limit_per_minute"
REASON_RATE_HOUR = "rate_limit_per_hour"
REASON_DEDUPE_SHAPE = "dedupe_key_shape"
REASON_STORE_DEGRADED = "store_unavailable_fail_open"
REASON_RECORD_DEGRADED = "send_count_write_failed"
REASON_QUEUE_NO_DELIVER_AFTER = "queue_without_deliver_after"

KIND_DEGRADED = "outbound_gate_degraded"
KIND_STORM = "outbound_gate_storm"
GATE_STAGE = "outbound_gate"
AUDIT_STAGE = "sender"  # 与 queue._append_sender_audit 同族口
AUDIT_TRANSPORT = "outbound_gate"
DEDUPE_NAMESPACE = "emg"
KEY_SEPARATOR = ":"
DEDUPE_FAMILY_ONCE = "once"
DEDUPE_FAMILY_DAILY = "daily"
# 同一主体连续顺延到这条即视为「上游在轰闸」（只报一次，放行清账）。
STORM_CONSECUTIVE_DEFERS = 3
_MINUTE_WINDOW_SECONDS = 60
_HOUR_WINDOW_SECONDS = 3600
# 计数行保留期：最长窗（小时）的一倍，随每次落账顺手剪。
_RETENTION_SECONDS = 2 * _HOUR_WINDOW_SECONDS

# `SendRequest.priority` 即 D-3 紧急等级的载体（P0..P3）。闸只认「在不在穿静默
# 白名单里」，非该形态的取值一律按非紧急保守顺延（绝不在深夜抢发）。
DEFAULT_URGENT_SEVERITIES = ("P0", "P1")


class OutboundGateSettings(StrictBaseModel):
    """闸的六项设置（B4-spec §1.5）。

    本件不落 `config.py`（该面禁改）：`build_outbound_gate_settings` 以 `getattr`
    口径读取，六键未落地时即取此处缺省=关闭，故本席可独立交付与验收。
    """

    enabled: bool = False
    quiet_defer_enabled: bool = True
    urgent_severities: list[str] = Field(default_factory=lambda: list(DEFAULT_URGENT_SEVERITIES))
    max_per_target_per_minute: int = 2
    max_per_target_per_hour: int = 6
    db_path: str = "data/outbound_gate.sqlite3"


class OutboundGateVerdict(StrictBaseModel):
    """三道门给出的结论（规格 §1.2 原文字段；第四态非法）。"""

    action: Literal["allow", "defer", "skip"]
    reason: str
    deliver_after: datetime | None = None
    audit_tags: list[str] = Field(default_factory=list)


class ActivePushOutcome(StrictBaseModel):
    """`submit_active_push` 的返回：结论 + 队列回执（skip 时为闸自造的 SKIPPED）。"""

    verdict: OutboundGateVerdict
    receipt: DeliveryReceipt | None = None


GateSettingsSource = OutboundGateSettings | Callable[[], OutboundGateSettings]
QuietSettingsSource = QuietHoursSettings | Callable[[], QuietHoursSettings]


class SendStore(Protocol):
    """滑窗计数 store 的最小面（假 store 可直接注入做确定性测试）。"""

    def count_sends(self, subject_key: str, *, since_utc: datetime) -> int: ...

    def record_send(self, subject_key: str, *, now_utc: datetime) -> None: ...

    def prune(self, *, before_utc: datetime) -> int: ...


_SCHEMA = """
CREATE TABLE IF NOT EXISTS outbound_gate_sends (
    seq           INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_key   TEXT NOT NULL,
    sent_at_epoch REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_outbound_gate_subject_time
    ON outbound_gate_sends (subject_key, sent_at_epoch);
"""


class SQLiteOutboundSendStore:
    """每主体滑窗计数（单表；确定性计数样板同日程引擎 send_log）。

    连接**惰性建立**：库路径不可用时构造不得抛——故障一律留给闸的 fail-open 分支
    处理（闸生病不许丢消息）。计数与落账因此允许向外抛 `sqlite3.Error`。
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    @property
    def db_path(self) -> str:
        return self._db_path

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            connection = sqlite3.connect(
                self._db_path, check_same_thread=False, isolation_level=None
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA busy_timeout=1000")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.executescript(_SCHEMA)
            self._conn = connection
        return self._conn

    def count_sends(self, subject_key: str, *, since_utc: datetime) -> int:
        with self._lock:
            row = self._connection().execute(
                "SELECT COUNT(*) AS n FROM outbound_gate_sends"
                " WHERE subject_key = ? AND sent_at_epoch >= ?",
                (subject_key, _epoch(since_utc)),
            ).fetchone()
        return int(row["n"])

    def record_send(self, subject_key: str, *, now_utc: datetime) -> None:
        with self._lock:
            self._connection().execute(
                "INSERT INTO outbound_gate_sends (subject_key, sent_at_epoch) VALUES (?, ?)",
                (subject_key, _epoch(now_utc)),
            )

    def prune(self, *, before_utc: datetime) -> int:
        with self._lock:
            cursor = self._connection().execute(
                "DELETE FROM outbound_gate_sends WHERE sent_at_epoch < ?",
                (_epoch(before_utc),),
            )
        return int(cursor.rowcount or 0)

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None


# --------------------------------------------------------------- 纯函数小工具
def _epoch(value: datetime) -> float:
    return value.astimezone(timezone.utc).timestamp()


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _format_moment(value: datetime | None) -> str:
    if value is None:
        return "none"
    return _utc(value).astimezone(timezone.utc).isoformat().replace(" ", "T")


def _subject_of(send_request: SendRequest) -> str:
    scope = getattr(send_request.target_scope, "value", None) or str(
        send_request.target_scope
    )
    return f"{scope}{KEY_SEPARATOR}{send_request.target_id}"


def _subject_hash(subject_key: str) -> str:
    return hashlib.sha256(subject_key.encode("utf-8")).hexdigest()[:12]


def _severity_of(send_request: SendRequest) -> str:
    return str(send_request.priority or "").strip().upper()


def _is_urgent(send_request: SendRequest, urgent_severities: list[str]) -> bool:
    allowed = {
        str(value).strip().upper() for value in urgent_severities if str(value).strip()
    }
    return _severity_of(send_request) in allowed


def dedupe_key_shape_ok(
    dedupe_key: str, *, family: str = DEDUPE_FAMILY_ONCE
) -> bool:
    """E5 §4.3 键规范：`emg:{channel}:{item_id}:{target_id}[:{date_key}]`。

    `family="daily"`（按日重投族）必须带 date_key 段，即恰好五段；一次性族四段
    或五段皆可。段数与空段在闸侧拦，重复投递的幂等仍归队列 `ON CONFLICT`。
    """
    segments = dedupe_key.split(KEY_SEPARATOR)
    if any(not segment.strip() for segment in segments):
        return False
    if segments[0] != DEDUPE_NAMESPACE:
        return False
    allowed_counts = (5,) if family == DEDUPE_FAMILY_DAILY else (4, 5)
    return len(segments) in allowed_counts


def _issue(kind: str, *, reason: str, subject_key: str) -> OperationalIssue:
    return OperationalIssue(
        stage=GATE_STAGE,
        kind=kind,
        retryable=False,
        safe_summary=f"reason={reason} subject={_subject_hash(subject_key)}",
    )


def _skipped_receipt(send_request: SendRequest, reason: str) -> DeliveryReceipt:
    """未触队列时的同形态回执（`queue.py` skipped 分支先例）。"""
    return DeliveryReceipt(
        request_id=send_request.request_id,
        state=ReceiptState.SKIPPED,
        transport=AUDIT_TRANSPORT,
        public_message="" if send_request.operational_issue is not None else reason,
        operational_issue=send_request.operational_issue,
    )


class OutboundGate:
    """出站防风暴闸实例（装配期构建；设置/时钟/store/审计/告警口全部可注入）。"""

    def __init__(
        self,
        settings: GateSettingsSource | None = None,
        *,
        quiet_settings: QuietSettingsSource | None = None,
        store: SendStore | None = None,
        clock: Callable[[], datetime] | None = None,
        audit_logger: Any = None,
        issue_sink: Callable[[OperationalIssue], None] | None = None,
    ) -> None:
        self._settings_source = settings
        self._quiet_source = quiet_settings
        self._store: SendStore | None = store
        self._injected_store = store is not None
        self._store_path: str | None = None
        self._clock = clock if clock is not None else (lambda: datetime.now(timezone.utc))
        self._audit_logger = audit_logger
        self._issue_sink = issue_sink
        self._lock = threading.Lock()
        # 连击顺延台账（进程内观测；判定不依赖它，故无需持久化）。
        self._consecutive_defers: dict[str, int] = {}

    # ------------------------------------------------------------------ 设置
    @property
    def settings(self) -> OutboundGateSettings:
        """当前闸设置（callable 时每次判定实时求值；求值失败=回退缺省关闭）。"""
        source = self._settings_source
        if source is None:
            return OutboundGateSettings()
        if isinstance(source, OutboundGateSettings):
            return source
        try:
            resolved = source()
        except Exception:  # 读不到设置按缺省（关闭），绝不拦投。
            _logger.exception(
                "outbound_gate settings_failure action=allow fallback=disabled"
            )
            return OutboundGateSettings()
        return resolved if isinstance(resolved, OutboundGateSettings) else OutboundGateSettings()

    @property
    def quiet(self) -> QuietHoursSettings:
        """静默窗设置（缺省=未启用；唯一事实源在 policy/quiet_hours）。"""
        source = self._quiet_source
        if source is None:
            return QuietHoursSettings()
        if isinstance(source, QuietHoursSettings):
            return source
        try:
            resolved = source()
        except Exception:  # 同 quiet_hours 口径：回退默认不误拦。
            _logger.exception("outbound_gate quiet_settings_failure fallback=default")
            return QuietHoursSettings()
        return resolved if isinstance(resolved, QuietHoursSettings) else QuietHoursSettings()

    @property
    def enabled(self) -> bool:
        return self.settings.enabled

    def clock(self) -> datetime:
        """注入时钟的当前时刻（缺省 UTC now）。"""
        return _utc(self._clock())

    # ---------------------------------------------------------------- store
    def _resolve_store(self) -> SendStore:
        """注入的 store 优先；否则按当前 db_path 惰性建 SQLite store（改径即重建）。"""
        if self._injected_store and self._store is not None:
            return self._store
        path = str(self.settings.db_path)
        if self._store is None or self._store_path != path:
            if isinstance(self._store, SQLiteOutboundSendStore):
                self._store.close()
            self._store = SQLiteOutboundSendStore(path)
            self._store_path = path
        return self._store

    def close(self) -> None:
        """只关自己惰性建的 store（注入进来的归调用方所有）。"""
        store = self._store
        if isinstance(store, SQLiteOutboundSendStore) and not self._injected_store:
            store.close()

    def window_count(self, subject_key: str, now: datetime) -> int:
        """60s 窗内该主体已投条数（观测/日志用；store 病时抛给调用侧兜住）。"""
        return self._count_within(subject_key, _utc(now), _MINUTE_WINDOW_SECONDS)

    def _count_within(self, subject_key: str, now: datetime, window_seconds: int) -> int:
        return self._resolve_store().count_sends(
            subject_key, since_utc=now - timedelta(seconds=window_seconds)
        )

    def record_send(self, subject_key: str, now: datetime) -> bool:
        """落一笔放行计数（顺手剪过期）。失败=已记日志，返回 False 由调用侧降级。"""
        try:
            store = self._resolve_store()
            store.record_send(subject_key, now_utc=now)
            store.prune(before_utc=now - timedelta(seconds=_RETENTION_SECONDS))
        except Exception:  # 计数写失败不拦投递。
            _logger.warning(
                "outbound_gate record_failure subject_key_hash=%s",
                _subject_hash(subject_key),
                exc_info=True,
            )
            return False
        return True

    # ------------------------------------------------------------ 观测出口
    def note_issue(self, issue: OperationalIssue) -> None:
        """告警出口：注入 sink 优先；sink 生病只留日志（观测不得炸投递链路）。"""
        sink = self._issue_sink
        if sink is None:
            return
        try:
            sink(issue)
        except Exception:  # 告警口生病只留日志。
            _logger.warning(
                "outbound_gate issue_sink_failure kind=%s", issue.kind, exc_info=True
            )

    def note_verdict(self, subject_key: str, *, deferred: bool) -> None:
        """连击账：顺延累计、放行清零。第 N 连击报一次 `outbound_gate_storm`。"""
        with self._lock:
            if not deferred:
                self._consecutive_defers.pop(subject_key, None)
                return
            streak = self._consecutive_defers.get(subject_key, 0) + 1
            self._consecutive_defers[subject_key] = streak
        if streak != STORM_CONSECUTIVE_DEFERS:
            return
        _logger.warning(
            "outbound_gate storm subject_key_hash=%s consecutive_defers=%d",
            _subject_hash(subject_key),
            streak,
        )
        self.note_issue(
            OperationalIssue(
                stage=GATE_STAGE,
                kind=KIND_STORM,
                retryable=False,
                safe_summary=(f"consecutive_defers={streak} subject={_subject_hash(subject_key)}"),
            )
        )

    def audit(
        self,
        send_request: SendRequest,
        verdict: OutboundGateVerdict,
        *,
        subject_key: str,
        window_count: int,
    ) -> None:
        """每次放行/顺延/拒绝各记一条闸审计（spec §1.4，同族口 `_append_sender_audit`）。"""
        auditor = self._audit_logger
        if auditor is None:
            return
        try:
            auditor.append(
                AuditRecord(
                    request_id=send_request.request_id,
                    session_id=send_request.session_id,
                    capability_id=send_request.capability_id,
                    stage=AUDIT_STAGE,
                    event=f"outbound_gate_{verdict.action}",
                    severity=send_request.content.risk_level,
                    public_message=verdict.reason,
                    private_debug=(
                        f"action={verdict.action} reason={verdict.reason}"
                        f" subject={_subject_hash(subject_key)}"
                        f" window_count={int(window_count)}"
                        f" deliver_after={_format_moment(verdict.deliver_after)}"
                    ),
                )
            )
        except Exception:  # 审计失败不得影响投递。
            _logger.warning(
                "outbound_gate audit_failure request_id=%s",
                send_request.request_id,
                exc_info=True,
            )

    # ------------------------------------------------------------------ 判定
    def decide(
        self,
        send_request: SendRequest,
        *,
        now: datetime | None = None,
        dedupe_family: str = DEDUPE_FAMILY_ONCE,
    ) -> OutboundGateVerdict:
        """过三道门给出结论（不触队列；`submit_active_push` 与装配侧共用）。

        `reason=disabled` 表示关闭态直通；其余为三门之一给出的 allow/defer/skip。
        """
        current = _utc(now or self.clock())
        settings = self.settings
        if not settings.enabled:
            return OutboundGateVerdict(action="allow", reason=REASON_DISABLED)

        subject_key = _subject_of(send_request)
        # fail-open 触点前置：滑窗计数先读一次（纯观测）。store 生病 ⇒ 直接放行，
        # 否则「静默窗内 store 挂」会先被顺延拦掉，闸的故障永远看不见（T4）。
        try:
            minute_count = self._count_within(subject_key, current, _MINUTE_WINDOW_SECONDS)
            hour_count = self._count_within(subject_key, current, _HOUR_WINDOW_SECONDS)
        except Exception:  # 方向锁：闸故障绝不变成丢消息。
            _logger.exception(
                "outbound_gate store_failure action=allow request_id=%s"
                " capability_id=%s subject_key_hash=%s",
                send_request.request_id,
                send_request.capability_id,
                _subject_hash(subject_key),
            )
            self.note_issue(
                _issue(KIND_DEGRADED, reason=REASON_STORE_DEGRADED, subject_key=subject_key)
            )
            return OutboundGateVerdict(action="allow", reason=REASON_STORE_DEGRADED)

        if settings.quiet_defer_enabled:
            quiet_verdict = self._quiet_verdict(send_request, settings, current)
            if quiet_verdict is not None:
                self.note_verdict(subject_key, deferred=True)
                return quiet_verdict

        if (
            settings.max_per_target_per_minute > 0
            and minute_count >= settings.max_per_target_per_minute
        ):
            verdict = OutboundGateVerdict(
                action="defer",
                reason=REASON_RATE_MINUTE,
                deliver_after=current + timedelta(seconds=_MINUTE_WINDOW_SECONDS),
                audit_tags=[f"outbound_gate:{REASON_RATE_MINUTE}"],
            )
            self.note_verdict(subject_key, deferred=True)
            return verdict
        if (
            settings.max_per_target_per_hour > 0
            and hour_count >= settings.max_per_target_per_hour
        ):
            verdict = OutboundGateVerdict(
                action="defer",
                reason=REASON_RATE_HOUR,
                deliver_after=current + timedelta(seconds=_HOUR_WINDOW_SECONDS),
                audit_tags=[f"outbound_gate:{REASON_RATE_HOUR}"],
            )
            self.note_verdict(subject_key, deferred=True)
            return verdict

        if not dedupe_key_shape_ok(send_request.dedupe_key, family=dedupe_family):
            return OutboundGateVerdict(
                action="skip",
                reason=REASON_DEDUPE_SHAPE,
                audit_tags=[f"outbound_gate:{REASON_DEDUPE_SHAPE}"],
            )
        return OutboundGateVerdict(action="allow", reason=REASON_ALLOWED)

    def _quiet_verdict(
        self,
        send_request: SendRequest,
        settings: OutboundGateSettings,
        now: datetime,
    ) -> OutboundGateVerdict | None:
        """第一道门：静默窗内非紧急 ⇒ 顺延到窗尾（D-2：仅白名单等级穿窗）。

        窗判定与 `quiet_hours._is_in_quiet_hours` 同一比较式、同一 start/end/tz
        事实源；窗尾时刻是本闸独有的「顺延到何时」算术，故只复用解析。
        """
        quiet = self.quiet
        if not quiet.enabled:
            return None
        scope = getattr(send_request.target_scope, "value", None) or str(
            send_request.target_scope
        )
        if scope not in {str(value).strip().lower() for value in quiet.session_types}:
            return None
        try:
            zone = ZoneInfo(quiet.timezone_name)
            start = _parse_hhmm(quiet.start_time)
            end = _parse_hhmm(quiet.end_time)
        except Exception:  # 设置读不通按不在窗内（不误拦）。
            _logger.exception(
                "outbound_gate quiet_window_invalid action=allow request_id=%s",
                send_request.request_id,
            )
            return None
        local_now = now.astimezone(zone)
        local_time = local_now.time()
        if start == end:
            in_window = True
        elif start < end:
            in_window = start <= local_time < end
        else:
            in_window = local_time >= start or local_time < end
        if not in_window or _is_urgent(send_request, settings.urgent_severities):
            return None
        quiet_end_local = local_now.replace(
            hour=end.hour, minute=end.minute, second=0, microsecond=0
        )
        if quiet_end_local <= local_now:
            quiet_end_local += timedelta(days=1)
        return OutboundGateVerdict(
            action="defer",
            reason=REASON_QUIET,
            deliver_after=quiet_end_local.astimezone(timezone.utc),
            audit_tags=[
                "outbound_gate:quiet_hours",
                f"outbound_gate:session:{scope}",
                f"outbound_gate:severity:{_severity_of(send_request) or 'none'}",
            ],
        )


# ------------------------------------------------------------- 唯一公开入口
def _submit(
    send_queue: Any,
    send_request: SendRequest,
    deliver_after: datetime | None,
) -> tuple[DeliveryReceipt, bool]:
    """触达队列；返回 `(回执, 是否因队列不认 deliver_after 而退化成裸调用)`。

    `deliver_after` 只有 SQLite 队列支持（`queue.py` submit 形参），InMemory 形态
    没有延迟概念——内省签名后按裸 submit 退化，绝不让顺延参数把消息吞掉。
    """
    submit = send_queue.submit
    if deliver_after is None:
        return submit(send_request), False
    if _accepts_keyword(submit, "deliver_after"):
        return submit(send_request, deliver_after=deliver_after), False
    return submit(send_request), True


def _accepts_keyword(func: Callable[..., Any], name: str) -> bool:
    try:
        parameters = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return False
    return name in parameters or any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
    )


def submit_active_push(
    send_queue: Any,
    send_request: SendRequest,
    gate: OutboundGate,
    *,
    now: datetime | None = None,
    dedupe_family: str = DEDUPE_FAMILY_ONCE,
) -> ActivePushOutcome:
    """主动投递的唯一中央入口（规格 §1.2 签名）。

    `dedupe_family="daily"` 声明该推送属按日重投族 ⇒ 键必须带 date_key 段。
    关闭态与三门全过都走裸 `submit(request)`（零关键字=与现状同形）；顺延走
    `submit(request, deliver_after=...)`；拒绝不触队列，只出自造 SKIPPED 回执。
    """
    current = _utc(now or gate.clock())
    verdict = gate.decide(send_request, now=current, dedupe_family=dedupe_family)
    subject_key = _subject_of(send_request)
    passthrough = verdict.reason == REASON_DISABLED  # 关闭态：零 store 触点、零审计
    degraded_reason: str | None = None
    # decide 里已 note_issue 的降级（store 病）只补回执注记，不重复播报。
    silent_issue_reason = REASON_STORE_DEGRADED if verdict.reason == REASON_STORE_DEGRADED else None
    # 日志/审计里的 window_count=判定时刻该主体 60s 窗内已投条数（不含本次）。
    window_count = 0
    if not passthrough:
        try:
            window_count = gate.window_count(subject_key, current)
        except Exception:
            # 该计数只服务观测字段，生病按 0 记（绝不因此影响投递）。
            _logger.debug("outbound_gate window_count_unavailable", exc_info=True)
            window_count = 0

    if verdict.action == "skip":
        receipt: DeliveryReceipt | None = _skipped_receipt(send_request, verdict.reason)
    else:
        if (
            verdict.action == "allow"
            and verdict.reason == REASON_ALLOWED
            and not gate.record_send(subject_key, current)
        ):
            degraded_reason = REASON_RECORD_DEGRADED
        receipt, fell_back = _submit(send_queue, send_request, verdict.deliver_after)
        if fell_back:
            degraded_reason = REASON_QUEUE_NO_DELIVER_AFTER
        if verdict.action == "allow":
            # 放行即清连击账（顺延连击在 decide 里累计，此处只清）。
            gate.note_verdict(subject_key, deferred=False)

    issue: OperationalIssue | None = None
    if degraded_reason is not None:
        issue = _issue(
            KIND_DEGRADED, reason=degraded_reason, subject_key=subject_key
        )
        gate.note_issue(issue)
    elif silent_issue_reason is not None:
        issue = _issue(
            KIND_DEGRADED, reason=silent_issue_reason, subject_key=subject_key
        )
    if receipt is not None and issue is not None and receipt.operational_issue is None:
        # 回执已有的 issue 属请求级事实，优先保留；闸的降级注记只在空时挂上。
        receipt = receipt.model_copy(update={"operational_issue": issue})

    _logger.info(
        "outbound_gate action=%s reason=%s request_id=%s capability_id=%s"
        " subject_key_hash=%s window_count=%d deliver_after=%s",
        verdict.action,
        verdict.reason,
        send_request.request_id,
        send_request.capability_id,
        _subject_hash(subject_key),
        window_count,
        _format_moment(verdict.deliver_after),
    )
    if not passthrough:
        gate.audit(
            send_request,
            verdict,
            subject_key=subject_key,
            window_count=window_count,
        )
    return ActivePushOutcome(verdict=verdict, receipt=receipt)


# --------------------------------------------------------------- 装配期构造
def build_outbound_gate_settings(config: object) -> OutboundGateSettings:
    """从 Config 投影闸设置（`getattr` 口径=六键未落地即取缺省，不阻塞本席交付）。"""
    return OutboundGateSettings(
        enabled=bool(getattr(config, "bot_outbound_gate_enabled", False)),
        quiet_defer_enabled=bool(
            getattr(config, "bot_outbound_gate_quiet_defer_enabled", True)
        ),
        urgent_severities=list(
            getattr(
                config,
                "bot_outbound_gate_urgent_severities",
                list(DEFAULT_URGENT_SEVERITIES),
            )
        ),
        max_per_target_per_minute=int(
            getattr(config, "bot_outbound_gate_max_per_target_per_minute", 2)
        ),
        max_per_target_per_hour=int(
            getattr(config, "bot_outbound_gate_max_per_target_per_hour", 6)
        ),
        db_path=str(
            getattr(config, "bot_outbound_gate_db_path", "data/outbound_gate.sqlite3")
        ),
    )


def build_outbound_gate(
    config: object,
    *,
    audit_logger: Any = None,
    clock: Callable[[], datetime] | None = None,
    store: SendStore | None = None,
    issue_sink: Callable[[OperationalIssue], None] | None = None,
    settings_provider: Callable[[], OutboundGateSettings] | None = None,
    quiet_settings_provider: Callable[[], QuietHoursSettings] | None = None,
) -> OutboundGate:
    """装配期构造（缺省=关闭，直通现状）。

    两路设置都以 callable 注入 ⇒ 热改即时反映（静默面先例
    `policy/quiet_hours.py`；限流阈值两键同样支持热改）。
    """
    return OutboundGate(
        settings_provider
        if settings_provider is not None
        else (lambda: build_outbound_gate_settings(config)),
        quiet_settings=quiet_settings_provider
        if quiet_settings_provider is not None
        else (lambda: build_quiet_hours_settings(config)),
        store=store,
        clock=clock,
        audit_logger=audit_logger,
        issue_sink=issue_sink,
    )
