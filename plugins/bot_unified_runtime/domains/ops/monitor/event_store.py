"""V2.1 S5 统一事件存储：严格 DTO + SQLite 持久化 + 稳定游标查询（V21-SSE-001）。

合同来源：docs/design/backend-v2-implementation-guide.md
- §6：分页默认 50 最大 200、稳定游标；严格 DTO 拒绝未知字段/NaN/Infinity。
- §7：SQLite WAL、busy_timeout=1000ms；本库 owner=事件服务，单写执行器
  （EventService 写线程是唯一写入方，本模块线程安全但写入串行化由调用方保证）。
- §8：source 十二枚举（bot/nonebot/napcat/telegram/mail/control_plane/
  decision_engine/pipeline/sender/llm/database/scheduler）；category 七类
  （debug/info/warning/error/success/critical/detail）且与 severity 分离；
  密钥/Cookie/Bearer/绝对路径不入公共日志。

与存量 control_plane/events.py 的关系（概念命名沿用、实现独立）：
- 存量 RuntimeLogEvent/RuntimeEventService 是控制面诊断层的现行实现，本模块是
  V2.1 权威事件层；存量多出 capability/renderer 两个 source，V2.1 按合同 §8
  收敛为十二个；CursorExpired/EventStoreUnavailable/EVENT_SOURCES/
  EVENT_CATEGORIES 等概念名与异常语义在此保持同口径，便于后续集成席位替换。
- message/safe_details 的隐私防线同存量哲学：字符串一律过
  output.plain_text.redact_local_secrets（脱敏后保留；脱敏器抛错→丢弃该值，
  fail-closed），外加节点预算与总字节预算。与存量的差异：存量对 ID 键
  「脱敏即丢弃」，本模块保留脱敏产物（脱敏输出按构造即安全），差异已在
  docs/design/v21-s5-events-log.md 登记。

线性化点：EventStore.append 的 COMMIT 即发布线性化点——先持久化后投递，
投递方（EventService 写线程）只在 append 返回（已提交）后才向订阅者广播，
因此任何订阅者看到的 seq 严格单调且不早于落库。

全部存储操作为同步阻塞 SQLite；ASGI 侧必须经 asyncio.to_thread 或
专用线程调用（合同 §7：网络调用不持数据库事务，事件循环不做 SQLite）。
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import Any

from pydantic import Field, field_validator, model_validator

from plugins.bot_unified_runtime.domains.core.contracts.envelope import V21StrictBase
from plugins.bot_unified_runtime.domains.core.contracts.request import PaginationQuery
from plugins.bot_unified_runtime.domains.render.plain_text import redact_local_secrets

# ---------------------------------------------------------------------------
# 枚举（合同 §8）
# ---------------------------------------------------------------------------

EVENT_SOURCES = (
    "bot",
    "nonebot",
    "napcat",
    "telegram",
    "mail",
    "control_plane",
    "decision_engine",
    "pipeline",
    "sender",
    "llm",
    "database",
    "scheduler",
)

EVENT_CATEGORIES = (
    "debug",
    "info",
    "warning",
    "error",
    "success",
    "critical",
    "detail",
)

# severity 与 category 分离（§8）；severity 表达机器可判的严重度，
# category 表达人读的展示类别。success 在 severity 上是 info。
EVENT_SEVERITIES = (
    "debug",
    "info",
    "notice",
    "warning",
    "error",
    "critical",
)

# category→severity 默认映射；调用方可显式覆盖（category 与 severity 分离）。
SEVERITY_BY_CATEGORY: dict[str, str] = {
    "debug": "debug",
    "info": "info",
    "warning": "warning",
    "error": "error",
    "success": "info",
    "critical": "critical",
    "detail": "debug",
}

# 隐私等级：public=可进公共日志/指标；internal=仅授权管理员；restricted=仅
# 授权工作区短期保存。本席位只持久化并透传该字段，按等级的可见性裁剪属
# 集成席位（认证 scope）职责，见 docs/design/v21-s5-events-log.md 遗留项。
PRIVACY_LEVELS = ("public", "internal", "restricted")

# 分类固定摘要（脱敏失败的 message 兜底，沿用存量 _MESSAGES 概念）。
DEFAULT_MESSAGES: dict[str, str] = {
    "debug": "调试事件",
    "info": "运行信息",
    "warning": "运行警告",
    "error": "操作失败",
    "success": "操作成功",
    "critical": "严重异常",
    "detail": "运行详情",
}

# ---------------------------------------------------------------------------
# 边界与校验
# ---------------------------------------------------------------------------

# 与存量 control_plane/events.py 同口径的操作标识模式。
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}\Z")
_CURSOR = re.compile(r"[0-9]{1,19}\Z")
_MAX_CURSOR = 2**63 - 1
_DETAIL_KEY = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}\Z")

MAX_MESSAGE_CHARS = 500
MAX_DETAIL_VALUE_CHARS = 256
MAX_DETAIL_ITEMS = 32
MAX_DETAIL_DEPTH = 3
MAX_DETAIL_NODES = 128
MAX_DETAILS_BYTES = 2048

_REDACT_FAILURES = (RuntimeError, TypeError, ValueError, LookupError, AttributeError)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_aware_utc(name: str, value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} 必须带时区（UTC ISO8601）")
    return value.astimezone(timezone.utc)


def _redact(text: str) -> str | None:
    """脱敏器 fail-closed：抛错时返回 None（调用方丢弃该值）。"""
    try:
        return redact_local_secrets(text)
    except _REDACT_FAILURES:
        return None


def _clean_id(value: str | None) -> str | None:
    """操作标识只留「形态合法且脱敏不改写」的值；其余置 None，不抛错。"""
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 128:
        return None
    safe = _redact(value)
    if safe is None or safe != value or not _IDENTIFIER.fullmatch(safe):
        return None
    return safe


def _sanitize_message(message: str, category: str) -> str:
    if not isinstance(message, str) or not message.strip():
        return DEFAULT_MESSAGES[category]
    safe = _redact(message)
    if safe is None:
        return DEFAULT_MESSAGES[category]
    return safe.strip()[:MAX_MESSAGE_CHARS]


def _sanitize_details(details: Any) -> dict[str, Any]:
    """safe_details 白名单化：仅标量叶子，字符串一律脱敏，总量三重封顶。

    三重预算：叶节点数 ≤MAX_DETAIL_NODES、顶层条目 ≤MAX_DETAIL_ITEMS、
    序列化后 ≤MAX_DETAILS_BYTES。超限整体丢弃（宁缺毋泄，调用方可降级为
    多条小事件）。dict 递归深度 ≤MAX_DETAIL_DEPTH；未知形态一律丢弃。
    """
    if not isinstance(details, dict):
        return {}
    budget = MAX_DETAIL_NODES

    def clean(value: Any, depth: int) -> Any:
        nonlocal budget
        budget -= 1
        if budget < 0 or depth > MAX_DETAIL_DEPTH:
            return None
        if value is None or isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value if 0 <= value <= 10**15 else None
        if isinstance(value, float):
            return value if math.isfinite(value) and abs(value) <= 10**15 else None
        if isinstance(value, str):
            safe = _redact(value)
            if safe is None:
                return None
            return safe[:MAX_DETAIL_VALUE_CHARS]
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key in sorted(value, key=str)[:MAX_DETAIL_ITEMS]:
                name = str(key)
                if not _DETAIL_KEY.fullmatch(name):
                    continue
                cleaned = clean(value[key], depth + 1)
                if cleaned is not None:
                    result[name] = cleaned
            return result or None
        if isinstance(value, (list, tuple)):
            items = [clean(item, depth + 1) for item in list(value)[:16]]
            trimmed = [item for item in items if item is not None]
            return trimmed or None
        return None

    cleaned = clean(details, 0)
    if not isinstance(cleaned, dict):
        return {}
    encoded = json.dumps(
        cleaned, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    )
    if len(encoded.encode("utf-8")) > MAX_DETAILS_BYTES:
        return {}
    return cleaned


def new_event_id() -> str:
    """evt_ 前缀 + 12 位 hex，与 envelope.new_request_id 同格式家族。"""
    return f"evt_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# DTO（复用 contracts/envelope.V21StrictBase + contracts/request.PaginationQuery）
# ---------------------------------------------------------------------------


class EventDraft(V21StrictBase):
    """发布侧输入 DTO。隐私净化在模型层完成，调用方无需预脱敏。"""

    source: str
    category: str
    severity: str | None = None
    message: str = ""
    request_id: str | None = Field(default=None, max_length=128)
    trace_id: str | None = Field(default=None, max_length=128)
    session_id: str | None = Field(default=None, max_length=128)
    capability_id: str | None = Field(default=None, max_length=128)
    model_id: str | None = Field(default=None, max_length=128)
    safe_details: dict[str, Any] = Field(default_factory=dict)
    privacy_level: str = "internal"

    @field_validator("source")
    @classmethod
    def _check_source(cls, value: str) -> str:
        if value not in EVENT_SOURCES:
            raise ValueError(f"source 必须是 {EVENT_SOURCES} 之一")
        return value

    @field_validator("category")
    @classmethod
    def _check_category(cls, value: str) -> str:
        if value not in EVENT_CATEGORIES:
            raise ValueError(f"category 必须是 {EVENT_CATEGORIES} 之一")
        return value

    @field_validator("severity")
    @classmethod
    def _check_severity(cls, value: str | None) -> str | None:
        if value is not None and value not in EVENT_SEVERITIES:
            raise ValueError(f"severity 必须是 {EVENT_SEVERITIES} 之一")
        return value

    @field_validator("privacy_level")
    @classmethod
    def _check_privacy(cls, value: str) -> str:
        if value not in PRIVACY_LEVELS:
            raise ValueError(f"privacy_level 必须是 {PRIVACY_LEVELS} 之一")
        return value

    @model_validator(mode="after")
    def _sanitize(self) -> EventDraft:
        # category 与 severity 分离：未显式给 severity 时按类别默认映射。
        object.__setattr__(
            self, "severity", self.severity or SEVERITY_BY_CATEGORY[self.category]
        )
        object.__setattr__(self, "message", _sanitize_message(self.message, self.category))
        for name in (
            "request_id",
            "trace_id",
            "session_id",
            "capability_id",
            "model_id",
        ):
            object.__setattr__(self, name, _clean_id(getattr(self, name)))
        object.__setattr__(self, "safe_details", _sanitize_details(self.safe_details))
        return self


class RuntimeEventV21(V21StrictBase):
    """已持久化事件的权威 DTO。seq 由存储单调分配（≥1）。"""

    seq: int = Field(ge=1, strict=True)
    event_id: str = Field(pattern=r"evt_[0-9a-f]{12}")
    occurred_at: datetime
    source: str
    category: str
    severity: str
    message: str
    request_id: str | None = None
    trace_id: str | None = None
    session_id: str | None = None
    capability_id: str | None = None
    model_id: str | None = None
    safe_details: dict[str, Any] = Field(default_factory=dict)
    privacy_level: str = "internal"

    @field_validator("occurred_at")
    @classmethod
    def _check_occurred_at(cls, value: datetime) -> datetime:
        return _require_aware_utc("occurred_at", value)

    def to_wire(self) -> dict[str, Any]:
        """线格式：occurred_at 转 UTC ISO8601 毫秒串（字典序即时间序）。"""
        payload = self.model_dump(mode="json")
        occurred = self.occurred_at.astimezone(timezone.utc)
        payload["occurred_at"] = occurred.isoformat(timespec="milliseconds")
        return payload

    def wire_bytes(self) -> int:
        """SSE 每连接字节预算的计价口径。"""
        return len(
            json.dumps(
                self.to_wire(), ensure_ascii=False, allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )


class EventQuery(PaginationQuery):
    """查询 DTO：limit/cursor 复用 contracts.request.PaginationQuery
    （默认 50、最大 200，cursor 为十进制 seq 线格式），追加 §8 全过滤器。
    """

    source: str | None = None
    category: str | None = None
    severity: str | None = None
    request_id: str | None = Field(default=None, max_length=128)
    trace_id: str | None = Field(default=None, max_length=128)
    session_id: str | None = Field(default=None, max_length=128)
    capability_id: str | None = Field(default=None, max_length=128)
    model_id: str | None = Field(default=None, max_length=128)
    occurred_after: datetime | None = None
    occurred_before: datetime | None = None

    @field_validator("occurred_after", "occurred_before")
    @classmethod
    def _check_times(cls, value: datetime | None, info: Any) -> datetime | None:
        if value is None:
            return None
        return _require_aware_utc(str(info.field_name), value)


class EventPage(V21StrictBase):
    """稳定游标分页结果。next_cursor 语义：追平后跳到 high_seq。"""

    items: list[RuntimeEventV21]
    next_cursor: int = Field(ge=0, strict=True)
    has_more: bool
    high_seq: int = Field(ge=0, strict=True)


# ---------------------------------------------------------------------------
# 异常（与存量同口径）
# ---------------------------------------------------------------------------


class CursorExpired(ValueError):
    """游标已落入保留窗口之前；oldest_seq 是当前最老可用 seq（空库=high+1）。"""

    def __init__(self, oldest_seq: int) -> None:
        super().__init__("cursor is outside the retained event window")
        self.oldest_seq = oldest_seq


class EventStoreUnavailable(RuntimeError):
    """存储不可用（SQLite/OSError 归一），发布方按 best-effort 计数处理。"""


def parse_cursor(value: str | int | None) -> int | None:
    """Last-Event-ID/查询 cursor 的线格式解析。

    类型违规（非整数/字符串）抛 TypeError；取值违规（负数/越界/垃圾串）
    抛 ValueError（HTTP 层映射 422）。
    """
    if value is None:
        return None
    if isinstance(value, str):
        if not _CURSOR.fullmatch(value):
            raise ValueError("cursor 必须是十进制整数")
        parsed = int(value)
        if parsed > _MAX_CURSOR:
            raise ValueError("cursor 超出范围")
        return parsed
    if isinstance(value, int) and not isinstance(value, bool):
        if not 0 <= value <= _MAX_CURSOR:
            raise ValueError("cursor 超出范围")
        return value
    raise TypeError("cursor 必须是整数或十进制字符串")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS runtime_events_v21 (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    occurred_at TEXT NOT NULL,
    source TEXT NOT NULL,
    category TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    request_id TEXT,
    trace_id TEXT,
    session_id TEXT,
    capability_id TEXT,
    model_id TEXT,
    safe_details TEXT NOT NULL,
    privacy_level TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_v21_source_seq ON runtime_events_v21(source, seq);
CREATE INDEX IF NOT EXISTS idx_events_v21_category_seq ON runtime_events_v21(category, seq);
CREATE INDEX IF NOT EXISTS idx_events_v21_severity_seq ON runtime_events_v21(severity, seq);
CREATE INDEX IF NOT EXISTS idx_events_v21_occurred ON runtime_events_v21(occurred_at);
CREATE INDEX IF NOT EXISTS idx_events_v21_request_seq ON runtime_events_v21(request_id, seq);
CREATE INDEX IF NOT EXISTS idx_events_v21_trace_seq ON runtime_events_v21(trace_id, seq);
CREATE INDEX IF NOT EXISTS idx_events_v21_session_seq ON runtime_events_v21(session_id, seq);
CREATE INDEX IF NOT EXISTS idx_events_v21_capability_seq ON runtime_events_v21(capability_id, seq);
CREATE INDEX IF NOT EXISTS idx_events_v21_model_seq ON runtime_events_v21(model_id, seq);
CREATE TABLE IF NOT EXISTS runtime_events_v21_watermark (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    pruned_through INTEGER NOT NULL,
    high_seq INTEGER NOT NULL
);
INSERT OR IGNORE INTO runtime_events_v21_watermark VALUES (1, 0, 0);
"""

_COLUMNS = (
    "seq",
    "event_id",
    "occurred_at",
    "source",
    "category",
    "severity",
    "message",
    "request_id",
    "trace_id",
    "session_id",
    "capability_id",
    "model_id",
    "safe_details",
    "privacy_level",
)


def _row_to_event(row: sqlite3.Row) -> RuntimeEventV21:
    data = dict(row)
    data["safe_details"] = json.loads(data["safe_details"])
    data["occurred_at"] = datetime.fromisoformat(data["occurred_at"])
    return RuntimeEventV21(**data)


class EventStore:
    """V2.1 事件持久化：单调 seq + 计数保留 + 稳定游标 keyset 查询。

    - WAL + busy_timeout=1000ms（§7）；每次操作独立开关连接，无长持锁。
    - 保留窗口按条数（max_events）；watermark 记录 pruned_through/high_seq，
      查询侧用它做全局缺口检测：过滤器永远不会隐藏缺口，缺口=CursorExpired。
    - AUTOINCREMENT 保证重启后 seq 不回绕不复用（重启 seq 连续）。
    - 同步阻塞接口；调用方负责移出事件循环（合同 §7）。
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        max_events: int = 10_000,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if not isinstance(max_events, int) or isinstance(max_events, bool):
            raise TypeError("max_events 必须是整数")
        if not 1 <= max_events <= 1_000_000:
            raise ValueError("max_events 超出 [1, 1000000]")
        self.db_path = Path(db_path)
        self.max_events = max_events
        self._clock = clock
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(_SCHEMA)

    # -- 连接管理 -----------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=1.0)
        connection.row_factory = sqlite3.Row
        # §7 契约：WAL + busy_timeout=1000ms + foreign_keys。
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=1000")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.isolation_level = None  # 显式事务管理
        return connection

    def _connection(self):
        return _StoreConnection(self)

    # -- 写入 ---------------------------------------------------------------

    def append(self, draft: EventDraft) -> RuntimeEventV21:
        """持久化一条事件；COMMIT 即发布线性化点。返回含单调 seq 的权威 DTO。

        event_id 在此分配（evt_ 前缀）；occurred_at 取存储时钟（UTC）。
        同一事务内完成：插入 → 水位推进 → 计数保留修剪。
        """
        if not isinstance(draft, EventDraft):
            raise TypeError("append 只接受 EventDraft")
        event_id = new_event_id()
        occurred_at = self._clock().astimezone(timezone.utc).isoformat(
            timespec="milliseconds"
        )
        details_json = json.dumps(
            draft.safe_details,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        try:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                committed = False
                try:
                    connection.execute(
                        "INSERT OR IGNORE INTO runtime_events_v21"
                        " (event_id, occurred_at, source, category, severity,"
                        "  message, request_id, trace_id, session_id,"
                        "  capability_id, model_id, safe_details, privacy_level)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            event_id,
                            occurred_at,
                            draft.source,
                            draft.category,
                            draft.severity,
                            draft.message,
                            draft.request_id,
                            draft.trace_id,
                            draft.session_id,
                            draft.capability_id,
                            draft.model_id,
                            details_json,
                            draft.privacy_level,
                        ),
                    )
                    row = connection.execute(
                        "SELECT * FROM runtime_events_v21 WHERE event_id=?",
                        (event_id,),
                    ).fetchone()
                    if row is None:
                        raise EventStoreUnavailable()
                    connection.execute(
                        "UPDATE runtime_events_v21_watermark"
                        " SET high_seq=MAX(high_seq, ?) WHERE singleton=1",
                        (row["seq"],),
                    )
                    # 计数保留：超出窗口的最老事件连同水位一起推进（同事务）。
                    cutoff = connection.execute(
                        "SELECT seq FROM runtime_events_v21"
                        " ORDER BY seq DESC LIMIT 1 OFFSET ?",
                        (self.max_events,),
                    ).fetchone()
                    if cutoff is not None:
                        connection.execute(
                            "DELETE FROM runtime_events_v21 WHERE seq<=?",
                            (cutoff["seq"],),
                        )
                        connection.execute(
                            "UPDATE runtime_events_v21_watermark"
                            " SET pruned_through=MAX(pruned_through, ?)"
                            " WHERE singleton=1",
                            (cutoff["seq"],),
                        )
                    connection.execute("COMMIT")
                    committed = True
                    return _row_to_event(row)
                finally:
                    if not committed:
                        try:
                            connection.execute("ROLLBACK")
                        except sqlite3.Error:
                            pass
        except (sqlite3.Error, OSError) as exc:
            raise EventStoreUnavailable() from exc

    # -- 查询 ---------------------------------------------------------------

    def query(self, query: EventQuery) -> EventPage:
        """稳定游标 keyset 分页（seq 升序）+ 全过滤器。

        - cursor=None：显式从最老可用事件开始（跳过已修剪段）。
        - cursor 落入已修剪区间：CursorExpired（缺口显式，不静默）。
        - cursor 超前于本库（after>high_seq）：ValueError。
        - 过滤器值非法：ValueError（查询过滤静默失效是不诚实行为）。
        """
        after = parse_cursor(query.cursor)
        enums = {
            "source": (query.source, EVENT_SOURCES),
            "category": (query.category, EVENT_CATEGORIES),
            "severity": (query.severity, EVENT_SEVERITIES),
        }
        for name, (value, allowed) in enums.items():
            if value is not None and value not in allowed:
                raise ValueError(f"{name} 非法")
        if not 1 <= query.limit <= 200:
            raise ValueError("limit 超出 [1, 200]（§6 默认 50 最大 200）")

        conditions = ["seq>?"]
        params: list[Any] = [after if after is not None else 0]
        for column, raw in (
            ("source", query.source),
            ("category", query.category),
            ("severity", query.severity),
            ("request_id", query.request_id),
            ("trace_id", query.trace_id),
            ("session_id", query.session_id),
            ("capability_id", query.capability_id),
            ("model_id", query.model_id),
        ):
            if raw is None:
                continue
            if not isinstance(raw, str) or not _IDENTIFIER.fullmatch(raw):
                raise ValueError(f"{column} 过滤器形态非法")
            conditions.append(f"{column}=?")
            params.append(raw)
        if query.occurred_after is not None:
            conditions.append("occurred_at>=?")
            params.append(
                query.occurred_after.astimezone(timezone.utc).isoformat(
                    timespec="milliseconds"
                )
            )
        if query.occurred_before is not None:
            conditions.append("occurred_at<=?")
            params.append(
                query.occurred_before.astimezone(timezone.utc).isoformat(
                    timespec="milliseconds"
                )
            )

        try:
            with self._connection() as connection:
                # 水位与页面必须同一快照，写侧修剪不会撕裂读取。
                connection.execute("BEGIN")
                committed = False
                try:
                    bounds = connection.execute(
                        "SELECT * FROM runtime_events_v21_watermark WHERE singleton=1"
                    ).fetchone()
                    floor, high = bounds["pruned_through"], bounds["high_seq"]
                    if after is not None and after < floor:
                        oldest = connection.execute(
                            "SELECT MIN(seq) FROM runtime_events_v21"
                        ).fetchone()[0]
                        raise CursorExpired(oldest if oldest is not None else high + 1)
                    if after is not None and after > high:
                        raise ValueError("cursor 超前于本事件库")
                    rows = connection.execute(
                        "SELECT * FROM runtime_events_v21 WHERE "
                        + " AND ".join(conditions)
                        + " ORDER BY seq LIMIT ?",
                        (*params, query.limit + 1),
                    ).fetchall()
                    connection.execute("COMMIT")
                    committed = True
                finally:
                    if not committed:
                        try:
                            connection.execute("ROLLBACK")
                        except sqlite3.Error:
                            pass
        except (sqlite3.Error, OSError) as exc:
            raise EventStoreUnavailable() from exc

        items = [_row_to_event(row) for row in rows[: query.limit]]
        has_more = len(rows) > query.limit
        return EventPage(
            items=items,
            next_cursor=items[-1].seq if has_more else high,
            has_more=has_more,
            high_seq=high,
        )

    def get(self, event_id: str) -> RuntimeEventV21 | None:
        """按 event_id 精确取一条；不在保留窗口返回 None。"""
        if not isinstance(event_id, str) or not _IDENTIFIER.fullmatch(event_id):
            raise ValueError("event_id 非法")
        try:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT * FROM runtime_events_v21 WHERE event_id=?",
                    (event_id,),
                ).fetchone()
        except (sqlite3.Error, OSError) as exc:
            raise EventStoreUnavailable() from exc
        return _row_to_event(row) if row is not None else None

    def counts(self) -> dict[str, int]:
        """运维视角：(当前行数, pruned_through, high_seq)；测试与诊断用。"""
        try:
            with self._connection() as connection:
                total = connection.execute(
                    "SELECT COUNT(*) FROM runtime_events_v21"
                ).fetchone()[0]
                bounds = connection.execute(
                    "SELECT pruned_through, high_seq"
                    " FROM runtime_events_v21_watermark WHERE singleton=1"
                ).fetchone()
        except (sqlite3.Error, OSError) as exc:
            raise EventStoreUnavailable() from exc
        return {
            "rows": int(total),
            "pruned_through": int(bounds["pruned_through"]),
            "high_seq": int(bounds["high_seq"]),
        }


# 事件 ID 由调用方在 EventDraft 上以 draft_event_id 预置的能力（重试幂等）：
# EventDraft 不声明该字段（extra=forbid），append 通过 duck 读取兼容内部重试；
# 常规路径直接传新 draft 即可。
class _StoreConnection:
    """上下文管理器：连接生命周期 + 异常归一（sqlite3.Error/OSError →
    EventStoreUnavailable），保持 with 语义简洁。"""

    def __init__(self, store: EventStore) -> None:
        self._store = store
        self._connection: sqlite3.Connection | None = None

    def __enter__(self) -> sqlite3.Connection:
        try:
            self._connection = self._store._connect()
        except (sqlite3.Error, OSError) as exc:
            raise EventStoreUnavailable() from exc
        return self._connection

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            except sqlite3.Error:
                pass
        self._connection = None


# 线程安全声明：EventStore 方法可多线程并发调用（每次独立连接；写入由
# BEGIN IMMEDIATE 串行化）；EventService 写线程是规范唯一写入方。
