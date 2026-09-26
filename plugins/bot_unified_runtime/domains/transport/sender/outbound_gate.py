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
  键规范（前缀 + 段数 + 逐段字符集 + 日期段形态）的**唯一实现**在
  `domains/emergency_info/service/dedupe.py:is_emergency_dedupe_key`，本文件的
  `dedupe_key_shape_ok` 是委托口——两侧一套规则，改键形只改那一处。
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
from plugins.bot_unified_runtime.domains.core.moment_parsing import parse_moment
from plugins.bot_unified_runtime.domains.emergency_info.service.dedupe import (
    EMERGENCY_DEDUPE_PREFIX,
    active_push_key_shape_ok,
    is_emergency_dedupe_key,
    wash_active_push_key,
)
from plugins.bot_unified_runtime.domains.render.plain_text import (
    redact_local_secrets,
)

__all__ = [
    "KIND_GATE_TTL_EXPIRED",
    "KIND_GATE_TTL_INVALID",
    "TTL_STATE_ABSENT",
    "TTL_STATE_ACTIVE",
    "TTL_STATE_EXPIRED",
    "TTL_STATE_INVALID",
    "TTL_STATE_OFF",
    "ActivePushOutcome",
    "OutboundGate",
    "OutboundGateSettings",
    "OutboundGateVerdict",
    "SQLiteOutboundSendStore",
    "build_outbound_gate",
    "build_outbound_gate_settings",
    "dedupe_key_shape_ok",
    "effective_gate_enabled",
    "parse_gate_ttl",
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
# 设置读不到/类型不对 ⇒ 行为恒等于「关闭」，而配置面看起来仍是开着的。必须能报出来。
KIND_SETTINGS_UNREADABLE = "outbound_gate_settings_unreadable"
# TTL（`enabled_until`）到期 / 读不懂 ⇒ 两者都必须**响亮**，不许静默当「没配」。
# 到期＝用户裁定的「临时开关自己下班」；读不懂＝闸门看起来开着而实际关着（同 I-3 病）。
KIND_GATE_TTL_EXPIRED = "outbound_gate_ttl_expired"
KIND_GATE_TTL_INVALID = "outbound_gate_ttl_invalid"
GATE_STAGE = "outbound_gate"
AUDIT_STAGE = "sender"  # 与 queue._append_sender_audit 同族口
AUDIT_TRANSPORT = "outbound_gate"
DEDUPE_NAMESPACE = EMERGENCY_DEDUPE_PREFIX
KEY_SEPARATOR = ":"
# 键规范的字面量与正则**只在** `domains/emergency_info/service/dedupe.py` 写一次
# （LOCK-AUDIT GAP-1 收口：闸侧原先自带一套只查前缀、段数与空段的宽松谓词——
# HEAD 实证旧谓词亦查 `segments[0] != DEDUPE_NAMESPACE`，缺的是逐段字符集与日期段
# 形态——与紧急域两套规则并存 ⇒ 脏键一边判合规一边判违规，过闸后队列按整串存两行
# ＝重复发送）。
# 本处只留词汇别名，`dedupe_key_shape_ok` 委托过去；禁止在这里重新定义规则。
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
    """闸的设置面（B4-spec §1.5 + 2026-09-25 开闸 A 案的 TTL 腿）。

    七枚全部落 `config.py:307-320`（旧版写「不落 config.py」已过时，照实更正；第七枚
    TTL 于 2026-09-25 由席 S260 补上，同批接上投影与判据 ⇒ 本字段不再是「在册未执法」）。
    前六枚 `build_outbound_gate_settings` 按 `getattr` 口径读取（键未落地即取此处缺省，
    本件不因配置面缺键而崩）；**第七枚相反**——读不到必抛（见 `_project_enabled_until`），
    因为它的缺省语义是「无到期」，把「读不到」折成缺省＝造一个不会自己下班的开关。

    `enabled_until` 是**第七枚**（TTL，ISO-8601 时刻字面量）：到期即等同
    `enabled=False` 并响亮留一行记录，不需要谁记得回来手工关掉。缺省空串＝**无
    TTL**，有效开启逐字节等于 `enabled` 本身（防「新键一上就改变现网」）。
    """

    enabled: bool = False
    quiet_defer_enabled: bool = True
    urgent_severities: list[str] = Field(default_factory=lambda: list(DEFAULT_URGENT_SEVERITIES))
    max_per_target_per_minute: int = 2
    max_per_target_per_hour: int = 6
    db_path: str = "data/outbound_gate.sqlite3"
    enabled_until: str = ""


# --------------------------------------------------------- TTL：有效开启的唯一判据
# 状态词（进日志/告警 `safe_summary`，不进 verdict.reason——见 `effective_gate_enabled`）。
TTL_STATE_OFF = "gate_off"          # enabled=False，TTL  irrelevant
TTL_STATE_ABSENT = "ttl_absent"     # enabled=True 且未配 TTL ⇒ 长期开（今天的形状）
TTL_STATE_ACTIVE = "ttl_active"     # enabled=True 且尚未到期
TTL_STATE_EXPIRED = "ttl_expired"   # 过点 ⇒ 等同关闸（本席要的那条自失效）
TTL_STATE_INVALID = "ttl_invalid"   # 读不懂 ⇒ fail-closed 等同关闸（宁关不猜）

_TTL_BAD_STATES = frozenset({TTL_STATE_EXPIRED, TTL_STATE_INVALID})


def parse_gate_ttl(value: object) -> datetime | None:
    """把 `enabled_until` 字面量解析成 aware UTC 时刻；空值 ⇒ None（无 TTL）。

    **解析本身不在此处**：ISO-8601 时刻的唯一真身是
    `domains/core/moment_parsing.parse_moment`（G5 单一事实源锁
    `test_gate_reuses_quiet_hours_single_source` 执法——闸侧禁自造时刻解析，
    也禁「禁了自造却无处可走」）。本函数只保留**闸自己的**那半句语义：
    「没配 TTL」是闸的判断，不是解析器的判断——`None` 与空白串在这里折成
    「无 TTL」，其余输入（含写错的垃圾值）整个交给真身。

    真身解不出即抛 `MomentParseError`（`ValueError` 子类），由
    `effective_gate_enabled` 折成 `TTL_STATE_INVALID`（fail-closed）。本席**不猜**：
    「2026-13-45」既不按「没配」放行（那会让一枚写错的 TTL 变成永久开关，正是用户
    明确否决的债），也不按「已过期」处理（那会让人以为到期才关的）。
    """
    if value is None:
        return None
    if not isinstance(value, datetime) and not str(value).strip():
        return None
    return parse_moment(value, field="outbound_gate.enabled_until")


def effective_gate_enabled(
    settings: OutboundGateSettings,
    now: datetime,
) -> tuple[bool, str]:
    """闸此刻**是否**执法，以及为什么（`(bool, 状态词)`，纯函数、零副作用）。

    **为什么必须只在这里判**：`enabled` 的读点在闸内只有 `OutboundGate.effective_enabled`
    一处（`OutboundGate.enabled` 与 `decide` 都经它），TTL 绝不在调用方各判一遍——
    每多一个读点就多一条「配置面看着开着、实际关着」的裂缝（本件立项时抓到的正是
    `emergency_info/service/push.py` 原先自己读了一次 `settings.enabled` 那一形）。
    副作用（告警）不在这里做：本函数保持纯，边沿告警在 `OutboundGate._note_ttl_state`。
    """
    if not settings.enabled:
        return False, TTL_STATE_OFF
    raw = settings.enabled_until
    if not str(raw or "").strip():
        return True, TTL_STATE_ABSENT
    try:
        until = parse_gate_ttl(raw)
    except (TypeError, ValueError):
        return False, TTL_STATE_INVALID
    if until is None:  # 理论不可达（空串已在上面拦掉），保底按无 TTL 走。
        return True, TTL_STATE_ABSENT
    if _utc(now) >= until:
        return False, TTL_STATE_EXPIRED
    return True, TTL_STATE_ACTIVE


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
    dedupe_key: str,
    *,
    family: str = DEDUPE_FAMILY_ONCE,
    namespace: str = DEDUPE_NAMESPACE,
) -> bool:
    """E5 §4.3 键规范：`{命名空间}:{...段}[:{date_key}]`，缺省命名空间仍是 `emg`。

    `family="daily"`（按日重投族）必须带 date_key 段。段字符集、日期段形态、前缀等值
    三条规则都在闸侧拦，重复投递的幂等仍归队列 `ON CONFLICT`。

    `namespace` 由**投递方申报**（2026-09-22 统一波新增）：闸的客源从「只有紧急域」
    扩到提醒 / cookie 到期 / 群摘要 / 日常助理四族后，硬要求前缀 `emg` 会把这四族在
    开闸态逐条判 skip＝静默丢消息（R-CENTRAL C-1）。缺省值取 `DEDUPE_NAMESPACE`，因此
    **不传该参的调用（紧急域全部现役调用点）行为逐字节不变**。申报值只用于「与键首段
    等值比对」，规则本体仍不在此定义。

    **本函数是委托口，不是实现**：规则本体唯一出处 =
    `domains/emergency_info/service/dedupe.py`（紧急族 `is_emergency_dedupe_key`，
    其余族 `active_push_key_shape_ok`，同一套 `_SEGMENT_RE`/`_DATE_KEY_RE`；B4 规格
    §1.3-3 的键形在那里定义）。此前两侧各写一套、闸侧漏查段字符集与前缀之外的
    形态（LOCK-AUDIT GAP-1 注毒 G10：删掉前缀校验 59 条全绿），真实后果不是漏报而是
    **重发**——脏键与干净键在队列里各存一行。改规则只改那一处，别在这里加分支；
    `tests/test_outbound_gate.py::test_dedupe_predicates_share_one_implementation`
    用 AST 拦「闸侧重新长出第二套正则/前缀字面量」。
    """
    require_date_key = family == DEDUPE_FAMILY_DAILY
    if namespace == DEDUPE_NAMESPACE:
        return is_emergency_dedupe_key(
            dedupe_key, require_date_key=require_date_key
        )
    return active_push_key_shape_ok(
        dedupe_key, namespace=namespace, require_date_key=require_date_key
    )


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
        # 设置读不到的告警闩（进程内一次性，读成功即清；见 `_note_settings_unreadable`）。
        self._settings_issue_reported = False
        # TTL 坏沿的告警闩（进程内边沿态：None=当前不在坏沿；值=已报过的那个坏沿状态词）。
        # 与上面那枚同哲学：边沿报一次、回到好沿清账，绝不自造时间节流。
        self._ttl_issue_state_reported: str | None = None

    # ------------------------------------------------------------------ 设置
    @property
    def settings(self) -> OutboundGateSettings:
        """当前闸设置（callable 时每次判定实时求值；求值失败=回退缺省关闭 + 报一次）。"""
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
            self._note_settings_unreadable()
            return OutboundGateSettings()
        if isinstance(resolved, OutboundGateSettings):
            self._note_settings_readable()
            return resolved
        # 求值成功但类型不对（装配接错线、中间层把对象吃掉）＝与读不到同病：按缺省关闭。
        _logger.error(
            "outbound_gate settings_type_mismatch action=allow got=%s",
            type(resolved).__name__,
        )
        self._note_settings_unreadable()
        return OutboundGateSettings()

    def _note_settings_unreadable(self) -> None:
        """「配了等于没配」必须冒到告警口（R-CENTRAL I-3，台账 #47 同型病）。

        只报一次：设置求值发生在**每次判定之前**，逐条播报会自己造出一股告警风暴；
        一旦某次求值成功即清账，坏→好→坏 会再报一次（否则一次性静音＝更糟）。
        """
        with self._lock:
            if self._settings_issue_reported:
                return
            self._settings_issue_reported = True
        self.note_issue(
            OperationalIssue(
                stage=GATE_STAGE,
                kind=KIND_SETTINGS_UNREADABLE,
                retryable=True,
                safe_summary="reason=settings_unreadable fallback=disabled",
            )
        )

    def _note_settings_readable(self) -> None:
        with self._lock:
            self._settings_issue_reported = False

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
        """闸此刻是否执法（**含 TTL**；判据唯一出口见 `effective_gate_enabled`）。"""
        return self.effective_enabled()[0]

    def effective_enabled(
        self,
        settings: OutboundGateSettings | None = None,
        now: datetime | None = None,
    ) -> tuple[bool, str]:
        """`(是否执法, TTL 状态词)`——本闸**唯一**的 enabled 判据出口（TTL 边沿在此报）。

        `decide` 与 `enabled` 都走这里，绝不在调用方各判一遍 TTL：每多一个读点就多
        一条「配置面看着开着、实际关着」的裂缝（#49「在册未执法」那族的本症）。
        """
        current = _utc(now or self.clock())
        resolved = self.settings if settings is None else settings
        enabled, state = effective_gate_enabled(resolved, current)
        self._note_ttl_state(state, resolved)
        return enabled, state

    def _note_ttl_state(self, state: str, settings: OutboundGateSettings) -> None:
        """到期沿 / 不可解析沿各出**一枚**运营告警（边沿闩，不造第二套节流）。

        - 闩的口径抄本件既有的 `_note_settings_unreadable`：同一坏沿只报一次、
          回到非坏沿即清账（坏→好→坏 再报一次）。**没有**时间窗——投递折叠与抑制
          归中央 `AdminAlertSuppression`（300s，`ops/monitor/alerts.py`），本件再叠
          一层时间闸＝第二套节流（简报明禁）。
        - 两枚 kind 都走 `note_issue`（既有唯一告警出口）。现网装配尚未给本闸注入
          `issue_sink` ⇒ 同时在**边沿**留一行 WARNING，让"闸看起来开着而实际关着"
          在只看日志时也可归因（旧形：sink=None 时 `note_issue` 连日志都不留）。
        - 日志零正文：TTL 原值只以长度 + `sha256[:12]` 出现；解得出来的时刻才可原样打印
          （它已由 `parse_moment` 归一，且来自管理员配置而非用户内容）。
        """
        if state not in _TTL_BAD_STATES:
            with self._lock:
                if self._ttl_issue_state_reported is not None:
                    self._ttl_issue_state_reported = None
            return
        with self._lock:
            if self._ttl_issue_state_reported == state:
                return
            self._ttl_issue_state_reported = state
        raw = str(settings.enabled_until or "")
        if state == TTL_STATE_EXPIRED:
            kind = KIND_GATE_TTL_EXPIRED
            detail = f"until={_format_moment(parse_gate_ttl(raw))}"
        else:
            kind = KIND_GATE_TTL_INVALID
            detail = f"until_len={len(raw)} until_hash={_subject_hash(raw)}"
        _logger.warning(
            "outbound_gate ttl_state=%s %s action=gate_closed verdict=disabled_passthrough",
            state,
            detail,
        )
        self.note_issue(
            OperationalIssue(
                stage=GATE_STAGE,
                kind=kind,
                retryable=False,
                safe_summary=f"reason={state} {detail}",
            )
        )

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
        dedupe_namespace: str = DEDUPE_NAMESPACE,
    ) -> OutboundGateVerdict:
        """过三道门给出结论（不触队列；`submit_active_push` 与装配侧共用）。

        `reason=disabled` 表示关闭态直通（**含 TTL 到期/读不懂而关**——见
        `effective_gate_enabled`：那两种形态与 `enabled=False` 同形，都是 passthrough）。
        其余为三门之一给出的 allow/defer/skip。
        `dedupe_namespace` 缺省 `emg`＝紧急域口径逐字节不变，其余主动投递族须申报
        自己那一族（见 `dedupe_key_shape_ok`）。
        """
        current = _utc(now or self.clock())
        settings = self.settings
        # 唯一判据出口：裸 `settings.enabled` 不再是这里的条件（TTL 在册未执法的本症，
        # #49「在册未执法」族）。关态一律走既有 REASON_DISABLED 词，语义=直通裸 submit。
        gate_on, _ttl_state = self.effective_enabled(settings, current)
        if not gate_on:
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

        if not dedupe_key_shape_ok(
            send_request.dedupe_key,
            family=dedupe_family,
            namespace=dedupe_namespace,
        ):
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


# ------------------------------------------------------- 唯一出口的统一正文打码
# AGENTS 铁律 3：一切出站文本必须过 `redact_local_secrets`（盘符路径 / `BOT_XXX=`
# / `sk-` / JWT / Bearer / 裸键值对 / URL userinfo）。能力回复路在
# `domains/render/renderer.py` 的唯一成形口有咽喉；经本出口的各族（提醒 /
# cookie 到期 / 群摘要 / 日常助理 / 等待回执 / 紧急信息）却在能力层各自拼好正文
# 再交进来，**不经 renderer** ⇒ 本出口是它们正文能被同一把尺洗到的唯一汇合点。
# 尺只有一把＝`redact_local_secrets` 真身（其自身幂等：替换产物不再被任一形态
# 命中，见 plain_text.py 头注），不起第二把。键名策略镜像 renderer 侧咽喉
# （人读文本键逐条洗、`file`/`url`/`content_sha256` 等字节定位符不动）——抄的是
# 策略不是代码：那个文件是本窗未入库的在飞件，跨文件 import 私有符号会被一次
# 改名打断整个出口；两把「策略」日后漂移由本文件测试件的同尺断言逼出来。
#
# 为何只洗文本键、不递归全部字符串叶子：`_LOCAL_PATH_RE` 同时命中 `C:/...` 斜杠
# 形态 ⇒ 把 `file:///C:/...` 这类媒体引用洗成占位符 = 图片/音频/文件段整条发不
# 出去，「为安全把功能打断」是本仓否决的交换（renderer 咽喉头注同向）。文本叶子
# 全洗还必误伤 `audit` 之外的结构字符串，作用域收到文本键是唯一两头都站得住的
# 切法。`messages`/`nodes`（合并转发）形态今天没有任何主动投递族构造
# （现算见 §调用方表），且该形态只在 renderer 成形口产出、出厂即已洗 ⇒ 不扩。
#
# 为何就地改写而非 model_copy 换新对象（顺序判定，另一半见函数内注释）：
# 提醒族的 `or request` 兜底与回执族的内联投递在出口返回后**继续用调用方手里的
# 请求对象**发正文——出口内部只换副本，那两条路的正文就永远没被洗（「入列被洗、
# 出队漏洗」与本波否决过的「本地测通、上线丢」同型）。就地改写让队列落库行、
# 闸观测与调用方内联投递看到的是同一份且唯一一份洗过的正文；零命中时一字段不
# 动、一赋值不发 ⇒ 现役行为与调用方引用逐字节同形。
_OUTBOUND_BODY_TEXT_KEYS = frozenset({"text", "caption", "prompt", "alt", "title"})


def _scrub_outbound_str(value: str) -> str:
    return redact_local_secrets(value) if value else value


def _scrub_ref_dict(value: Any) -> tuple[Any, bool]:
    """洗一个部件/条目 dict 的人读文本键；返回 (结果, 是否改写)，未改写回原对象。"""
    if not isinstance(value, dict):
        return value, False
    cleaned: dict[str, Any] | None = None
    for key in _OUTBOUND_BODY_TEXT_KEYS:
        item = value.get(key)
        if isinstance(item, str) and item:
            scrubbed = _scrub_outbound_str(item)
            if scrubbed != item:
                if cleaned is None:
                    cleaned = dict(value)
                cleaned[key] = scrubbed
    if cleaned is None:
        return value, False
    return cleaned, True


def _scrub_content_ref(ref: Any) -> tuple[Any, bool]:
    """`text` 单条、`chunks` 逐条、`parts` 逐部件的文本键；其余键原样透传。

    零命中时返回**原 dict 同一对象**（调用方据此不赋值，逐字节同形）。
    """
    if not isinstance(ref, dict):
        return ref, False
    cleaned: dict[str, Any] | None = None
    text = ref.get("text")
    if isinstance(text, str) and text:
        scrubbed = _scrub_outbound_str(text)
        if scrubbed != text:
            cleaned = dict(ref)
            cleaned["text"] = scrubbed
    chunks = ref.get("chunks")
    if isinstance(chunks, list):
        new_chunks: list[Any] | None = None
        for index, chunk in enumerate(chunks):
            if isinstance(chunk, str) and chunk:
                scrubbed = _scrub_outbound_str(chunk)
                if scrubbed != chunk:
                    if new_chunks is None:
                        new_chunks = list(chunks)
                    new_chunks[index] = scrubbed
        if new_chunks is not None:
            if cleaned is None:
                cleaned = dict(ref)
            cleaned["chunks"] = new_chunks
    parts = ref.get("parts")
    if isinstance(parts, list):
        new_parts: list[Any] | None = None
        for index, part in enumerate(parts):
            scrubbed_part, part_changed = _scrub_ref_dict(part)
            if part_changed:
                if new_parts is None:
                    new_parts = list(parts)
                new_parts[index] = scrubbed_part
        if new_parts is not None:
            if cleaned is None:
                cleaned = dict(ref)
            cleaned["parts"] = new_parts
    if cleaned is None:
        return ref, False
    return cleaned, True


def _redact_active_push_body(send_request: SendRequest) -> None:
    """在唯一出口对出站正文过一次统一打码；零命中＝不碰任何字段。

    逐字段 `getattr` 宽容读取（缺字段＝该格跳过）：现役生产件里 `content` 必为
    `RenderedOutput`（pydantic 必填两格），读不到只可能是 duck-typed 测试替身
    （`test_active_push_entry_teeth` 的 SimpleNamespace 活性锚）——本出口对闸
    自身生病的方向锁是「绝不丢消息」，一把尺把鸭子形打断属同罪。
    """
    content = getattr(send_request, "content", None)
    if content is None:
        return
    fallback = getattr(content, "text_fallback", None)
    scrubbed_fallback = (
        _scrub_outbound_str(fallback) if isinstance(fallback, str) else fallback
    )
    fallback_changed = (
        isinstance(scrubbed_fallback, str) and scrubbed_fallback != fallback
    )
    scrubbed_ref, ref_changed = _scrub_content_ref(getattr(content, "content_ref", None))
    if not fallback_changed and not ref_changed:
        return
    # 观测（与键形 wash 的 warning 同型）：真触发必留一行，零正文——只报长度差，
    # 「打了码却无痕」与本波否决过的静默降级同罪。
    _logger.warning(
        "outbound_gate body_redacted capability_id=%s request_id=%s"
        " fallback_before_len=%d fallback_after_len=%d content_ref_changed=%s",
        getattr(send_request, "capability_id", "?"),
        getattr(send_request, "request_id", "?"),
        len(fallback) if isinstance(fallback, str) else -1,
        len(scrubbed_fallback) if isinstance(scrubbed_fallback, str) else -1,
        ref_changed,
    )
    if fallback_changed:
        content.text_fallback = scrubbed_fallback
    if ref_changed:
        content.content_ref = scrubbed_ref


def submit_active_push(
    send_queue: Any,
    send_request: SendRequest,
    gate: OutboundGate,
    *,
    now: datetime | None = None,
    dedupe_family: str = DEDUPE_FAMILY_ONCE,
    dedupe_namespace: str = DEDUPE_NAMESPACE,
) -> ActivePushOutcome:
    """主动投递的唯一中央入口（规格 §1.2 签名）。

    `dedupe_family="daily"` 声明该推送属按日重投族 ⇒ 键必须带 date_key 段；
    `dedupe_namespace` 声明该族的键首段（缺省 `emg`=紧急域现役口径不变，其余族须
    自报，见 `dedupe_key_shape_ok`）。
    关闭态与三门全过都走裸 `submit(request)`（零关键字=与现状同形）；顺延走
    `submit(request, deliver_after=...)`；拒绝不触队列，只出自造 SKIPPED 回执。
    正文在函数**最前**过一次 `redact_local_secrets`（AGENTS 铁律 3 的主动投递腿，
    作用域与理由见 `_redact_active_push_body` 头注；闸关否与打码无关——开关＝
    可以把安全关掉，禁做）。
    """
    # 顺序判定：打码排在键形 wash / gate.decide / audit / submit **之前**、入口
    # 第一站。①三道门的判据全部只消费结构字段（dedupe/cooldown 键、priority、
    # session/target、risk/privacy 等级），从不读人读正文 ⇒ 打码在数学上不可能
    # 改变任何门判；②队列落库行、闸观测与调用方内联投递（提醒 `or request`
    # 兜底、回执 `_submit_progress_ack` 直发）此后看到的必须是**同一份**远端将
    # 真正收到的文本——观测面若拿打码前文本，日志/审计就可能出现「投递洗了、
    # 审计仍带盘符与 key 形态」的第二真身；③就地改写而非副本（见上方头注），
    # 否则内联投递两条腿漏洗。
    _redact_active_push_body(send_request)
    current = _utc(now or gate.clock())
    # 键形在这唯一出口规范一次：闸只在**开闸态**执法键形，脏键整条判 skip＝静默丢；
    # 关闭态是 passthrough 照发 ⇒ 「本地测通、上线丢」（本波同型三次：紧急域 `nmc:A1`、
    # 等待回执、群摘要/日常助理两族，见 `dedupe.py:active_push_key_segment` 头注）。
    # 已合法的键逐字节不变 ⇒ 现役各族行为零变化；真被改写必留一行 warning，不静默。
    canonical_key = wash_active_push_key(send_request.dedupe_key)
    if canonical_key != send_request.dedupe_key:
        _logger.warning(
            "outbound_gate dedupe_key_normalized capability_id=%s dedupe_family=%s"
            " before_len=%d after_len=%d after_hash=%s",
            send_request.capability_id,
            dedupe_family,
            len(send_request.dedupe_key),
            len(canonical_key),
            _subject_hash(canonical_key),
        )
        send_request = send_request.model_copy(update={"dedupe_key": canonical_key})
    verdict = gate.decide(
        send_request,
        now=current,
        dedupe_family=dedupe_family,
        dedupe_namespace=dedupe_namespace,
    )
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
_TTL_UNSET = object()

# 「同族其余六枚」的名字只用来做一件事：**区分**「这根本不是一份闸配置」与
# 「闸配置落后一步」。零键对象（`SimpleNamespace()`，本件与测试里的常态缺省形状）
# 走静默缺省=关闭，与逐字节现状同形（`test_empty_config_projects_defaults_and_passes_through`
# 钉着）；而同族键在场、唯独 TTL 键不在＝投影面/Config 与代码脱节，**必须响亮**：
# 静默把它当「无到期」，正是用户明确否决的那笔人工回滚债（一枚临时开关变永久开关）。
# 抛出后由 `OutboundGate.settings` 的既有兜底接住＝回退缺省关闭 + 冒
# `KIND_SETTINGS_UNREADABLE`（同 I-3 病同一个出口，不另造第二种告警）。
_GATE_SIBLING_KEYS_WITHOUT_TTL: tuple[str, ...] = (
    "bot_outbound_gate_enabled",
    "bot_outbound_gate_quiet_defer_enabled",
    "bot_outbound_gate_urgent_severities",
    "bot_outbound_gate_max_per_target_per_minute",
    "bot_outbound_gate_max_per_target_per_hour",
    "bot_outbound_gate_db_path",
)


def _project_enabled_until(config: object) -> str:
    """投影 TTL 字面量（闸侧唯一读点）。**读不到不许折成「无到期」**，见上表注释。"""
    raw = getattr(config, "bot_outbound_gate_enabled_until", _TTL_UNSET)
    if raw is _TTL_UNSET or raw is None:
        if any(hasattr(config, key) for key in _GATE_SIBLING_KEYS_WITHOUT_TTL):
            raise LookupError(
                "config 面缺 bot_outbound_gate_enabled_until（同族六键在而 TTL 键不在）"
                "：投影面落后一步，静默按「无到期」会把临时开关洗成永久开关"
            )
        return ""
    return str(raw).strip()


def build_outbound_gate_settings(config: object) -> OutboundGateSettings:
    """从 Config 投影闸设置（七枚 `bot_outbound_gate_*` 键；真身 `config.py:307-320`）。

    六枚既有键沿用 `getattr(缺省)` 口径（键未落地即取本件缺省，不阻塞装配）。
    第七枚 TTL 例外：它**必须**经 `_project_enabled_until` 走「同族在而它不在⇒抛」的
    判据——它的缺省语义是「无到期＝长期开」，把「读不到」当成缺省就是造一个不会自己
    下班的开关（用户 2026-09-25 裁定「开，A+B」的 B 半句）。
    """
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
        enabled_until=_project_enabled_until(config),
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
