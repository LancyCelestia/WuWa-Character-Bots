"""入站事件幂等表（交接 P0.4：同事件重复投递去重）。

OneBot/SnowLuma 断线重连可能重放同一事件；同一 (adapter, bot_id, message_id)
被同一能力处理两次会造成重复回复。提供两种后端，同一 claim 接口：
- EventIdempotencyTable：进程内 TTL 去重，重启即失效；
- SqliteEventIdempotencyTable：SQLite 持久化，跨重启仍拦截重放事件。

共同语义：
- 键 = adapter | bot_id | message_id（无 message_id 的事件走下方「兜底键」）；
- 同一键对同一 capability_id 只放行一次；不同能力互不影响（多 matcher 合法共存）；
- TTL 过期与容量上限自动回收。

兜底键（席 N1 2026-10-02，P3.10）——旧语义「无稳定 message_id ⇒ 返回空串 ⇒ 调用方
跳过去重」把整族 NoticeEvent（戳一戳 / 表情回应 / 群增减 / 管理员变动）留在幂等面之外：
SnowLuma 断线重连重放同一条 notice 时，统一管线出口 `_send_parts_through_unified_pipeline`
（根 `__init__.py:6052`，调用点 :7046 戳一戳话术、:7163 入群话术）会**照第二遍发**，
而且拦它的门本来就该在管线上，不在各能力自己那。现在按事件形态分三档：

1. **正身键**（有 message_id）：形制 `adapter|bot_id|message_id` 不变，但**逐段过中央
   洗段口** `dedupe.py:active_push_key_segment`（读侧谓词 `is_legal_segment`，段集
   `^[A-Za-z0-9_.-]{1,120}$`，同时禁 `:` 与 `|`）。理由：分隔符 `|` 不是段内合法字符，
   不洗则 `message_id="a|b"` 与 `bot_id="a"` + `message_id="b"` 拼出同一枚键 ⇒ 两条
   不同事件共用一个幂等桶＝静默吞第二条。mail 侧 Message-ID 由**发件方**的邮件服务器
   决定（`<…@…>`），是可控文本，这一族今天就在雷区里。QQ/OneBot 纯数字 id 洗完
   逐字节不变 ⇒ 现役生产键零迁移。
2. **兜底键**（无 message_id **且无正文**＝NoticeEvent 族）：
   `efn|adapter|bot_id|session_id|sender_id|<时间桶>`。时间桶宽取
   `bot_poke_private_cooldown_seconds` 的缺省值 30.0（`config.py:1165`，执行点
   `capabilities/poke.py:57` 的 `(group, sender)` 冷却）——取同一个数是判据不是巧合：
   这条兜底能吞下的「同一人 30 秒内的第二发」，本来就是那条冷却吃掉的次数，因此
   **不新造**「连戳两下只回一下」这种误伤。等值关系由
   `tests/test_event_idempotency.py::test_fallback_bucket_width_matches_poke_cooldown_default`
   钉住，两处不许各自漂移。
3. **仍然返回空串**（无 message_id 但**有正文**）：这类是合成/自造投递轮
   （订阅推送 `__init__.py:5125`、历史上的今天 `:2103`、控制台输入）。它们的幂等真身是
   **出站侧** `SendRequest.dedupe_key` + 队列 `ON CONFLICT` （台账 #46／`dedupe.py` 头注
   「幂等唯一执行点」），在入站再按「同会话同文本」建一把尺＝给正常对话里
   「同一句话连发两遍」判重复，那是把用户的话吞掉。所以这一档不建键，只由
   `event_dedupe_gap_reason()` 把「缺的是哪一枚事实」说出来，让盲区可查、不再静默。

残余（如实登记，见 patches/N1-NOTICE-ROLES-MAIL-20261002.md）：notice 事件真正的唯一性
在 OneBot 原生载荷里（`notice_type` + `time`），而 `IncomingMessage` 没带这两枚，
`_incoming_from_nonebot_event`（根 `__init__.py`，本席禁写面）于是只能退化成
「身份 + 时间桶」。补齐它需要契约加字段＝控制席的批，不在本席自决范围内。
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections import OrderedDict
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.domains.emergency_info.service.dedupe import (
    active_push_key_segment,
    is_legal_segment,
)

#: 事件键的分段符。`:` 被出站闸当段分隔符（台账 #46★），本键虽不经那道闸，
#: 也一律避开；`|` 只在本处作连接符，段内出现即由洗段口改掉。
_KEY_SEPARATOR = "|"
#: 兜底键命名空间（与正身键的 adapter 段取值域不相交：adapter 只会是
#: onebot/nonebot/telegram/mail 及其写法变体，永远不会是 `efn`）。
_FALLBACK_NAMESPACE = "efn"
#: 兜底时间桶宽（秒）。真身＝`config.py bot_poke_private_cooldown_seconds` 缺省值，
#: 由测试钉住等值，不许在此手改成一个凭感觉的数。
FALLBACK_BUCKET_SECONDS = 30.0


def _key_segment(value: object) -> str:
    """一个参与量 → 合法键段（洗段真身唯一住 `dedupe.py`，本处不写第二套正则）。"""
    return active_push_key_segment(value)


def _joined_key(segments: tuple[object, ...]) -> str:
    key = _KEY_SEPARATOR.join(_key_segment(segment) for segment in segments)
    # 构造侧自检：洗完仍非法（理论上不该发生，`active_push_key_segment` 保证合法或
    # 摘要兜底）⇒ 宁可不拦，也不发一枚会被下游按段歧义解释的键。
    if not all(is_legal_segment(part) for part in key.split(_KEY_SEPARATOR)):
        return ""
    return key


def _text_of(message: Any, name: str) -> str:
    return str(getattr(message, name, "") or "").strip()


def _identity_bucket(message: Any, bucket_seconds: float) -> str | None:
    """时间桶序号；取不到可用时间事实返回 None（⇒ 不建键，绝不拿半截身份吞事件）。"""
    moment = getattr(message, "timestamp", None)
    if isinstance(moment, datetime):
        epoch_seconds = moment.timestamp()
    elif isinstance(moment, (int, float)):
        epoch_seconds = float(moment)
    else:
        return None
    if epoch_seconds <= 0:
        return None
    width = max(1.0, float(bucket_seconds))
    return str(int(epoch_seconds // width))


def build_event_dedupe_key(
    message: Any, *, bucket_seconds: float = FALLBACK_BUCKET_SECONDS
) -> str:
    """构造事件去重键；三档形制见模块头注。返回空串＝这一轮不拦（并可用
    `event_dedupe_gap_reason()` 问出为什么不拦）。"""
    adapter = _text_of(message, "adapter").lower()
    bot_id = _text_of(message, "bot_id")
    message_id = _text_of(message, "message_id")
    if message_id:
        return _joined_key((adapter, bot_id, message_id))
    fallback = build_notice_fallback_key(message, bucket_seconds=bucket_seconds)
    if fallback:
        return fallback
    return ""


def build_notice_fallback_key(
    message: Any, *, bucket_seconds: float = FALLBACK_BUCKET_SECONDS
) -> str:
    """兜底键（第二档）：无 message_id 且无正文的 NoticeEvent 族。

    参与量缺一枚即返回空串：`adapter`/`bot_id`/`session_id`/`sender_id` 少任何一枚，
    键就退化成「按会话/按全平台合并」，那会把不同人的事件吞进同一个桶——宁可不拦。
    """
    adapter = _text_of(message, "adapter").lower()
    bot_id = _text_of(message, "bot_id")
    if _text_of(message, "message_id") or _text_of(message, "plain_text"):
        # 有 message_id 走正身键；有正文而无 message_id＝合成轮，幂等真身在出站队列。
        return ""
    session_id = _text_of(message, "session_id")
    sender_id = _text_of(message, "sender_id")
    if not (adapter and bot_id and session_id and sender_id):
        return ""
    bucket = _identity_bucket(message, bucket_seconds)
    if bucket is None:
        return ""
    return _joined_key((_FALLBACK_NAMESPACE, adapter, bot_id, session_id, sender_id, bucket))


def event_dedupe_gap_reason(message: Any) -> str:
    """为什么这一轮建不出键（把「静默跳过去重」变成可审计的一句话）。

    只读、不判定、不产决策；返回值是稳定枚举串，供日志与巡检对齐口径。
    """
    if _text_of(message, "message_id"):
        return "none"
    if build_notice_fallback_key(message):
        return "none"
    if _text_of(message, "plain_text"):
        return "synthetic_turn_without_message_id"
    for name, label in (
        ("adapter", "missing_adapter"),
        ("bot_id", "missing_bot_id"),
        ("session_id", "missing_session_id"),
        ("sender_id", "missing_sender_id"),
    ):
        if not _text_of(message, name):
            return label
    if _identity_bucket(message, FALLBACK_BUCKET_SECONDS) is None:
        return "missing_event_timestamp"
    return "unknown"


class EventIdempotencyTable:
    """进程内 TTL 幂等表：claim() 返回 True 表示首次出现（放行处理）。"""

    def __init__(
        self,
        *,
        ttl_seconds: float = 3600.0,
        max_entries: int = 4096,
        clock: Any = time.monotonic,
    ) -> None:
        self.ttl_seconds = max(1.0, float(ttl_seconds))
        self.max_entries = max(1, int(max_entries))
        self._clock = clock
        self._lock = threading.Lock()
        # key -> (capability_id, last_seen_monotonic)
        self._entries: OrderedDict[str, tuple[str, float]] = OrderedDict()

    def claim(self, key: str, *, capability_id: str) -> bool:
        if not key:
            return True
        now = float(self._clock())
        with self._lock:
            self._evict_expired(now)
            previous = self._entries.get(key)
            if previous is not None and previous[0] == capability_id:
                # 重复事件：刷新时间戳并拒绝。
                self._entries.move_to_end(key)
                self._entries[key] = (previous[0], now)
                return False
            self._entries[key] = (capability_id, now)
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
            return True

    def _evict_expired(self, now: float) -> None:
        cutoff = now - self.ttl_seconds
        while self._entries:
            _, (_, seen_at) = next(iter(self._entries.items()))
            if seen_at >= cutoff:
                break
            self._entries.popitem(last=False)

    def __len__(self) -> int:
        with self._lock:
            self._evict_expired(float(self._clock()))
            return len(self._entries)


class SqliteEventIdempotencyTable:
    """SQLite 持久化幂等表：与 EventIdempotencyTable 同接口，跨重启拦截重放。

    时间戳用 wall clock（time.time()）存储，重启后 TTL 判定仍然成立；
    写路径串行化在本进程锁内，跨进程依赖 SQLite 自身文件锁兜底。
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        ttl_seconds: float = 3600.0,
        max_entries: int = 4096,
        clock: Any = time.time,
    ) -> None:
        self.db_path = Path(db_path)
        self.ttl_seconds = max(1.0, float(ttl_seconds))
        self.max_entries = max(1, int(max_entries))
        self._clock = clock
        self._lock = threading.Lock()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS event_idempotency (
                    event_key TEXT NOT NULL,
                    capability_id TEXT NOT NULL,
                    claimed_at_unix REAL NOT NULL,
                    PRIMARY KEY (event_key, capability_id)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_event_idempotency_claimed_at
                ON event_idempotency (claimed_at_unix)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=5.0)
        return connection

    def claim(self, key: str, *, capability_id: str) -> bool:
        if not key:
            return True
        now = float(self._clock())
        cutoff = now - self.ttl_seconds
        with self._lock:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    "DELETE FROM event_idempotency WHERE claimed_at_unix < ?",
                    (cutoff,),
                )
                existing = connection.execute(
                    """
                    SELECT 1 FROM event_idempotency
                    WHERE event_key = ? AND capability_id = ?
                    """,
                    (key, capability_id),
                ).fetchone()
                if existing is not None:
                    # 重复事件：刷新时间戳并拒绝。
                    connection.execute(
                        """
                        UPDATE event_idempotency SET claimed_at_unix = ?
                        WHERE event_key = ? AND capability_id = ?
                        """,
                        (now, key, capability_id),
                    )
                    return False
                connection.execute(
                    """
                    INSERT INTO event_idempotency
                        (event_key, capability_id, claimed_at_unix)
                    VALUES (?, ?, ?)
                    """,
                    (key, capability_id, now),
                )
                self._prune(connection, cutoff)
            return True

    def _prune(self, connection: sqlite3.Connection, cutoff: float) -> None:
        connection.execute(
            "DELETE FROM event_idempotency WHERE claimed_at_unix < ?",
            (cutoff,),
        )
        overflow = connection.execute(
            "SELECT COUNT(*) FROM event_idempotency"
        ).fetchone()[0] - self.max_entries
        if overflow > 0:
            connection.execute(
                """
                DELETE FROM event_idempotency WHERE rowid IN (
                    SELECT rowid FROM event_idempotency
                    ORDER BY claimed_at_unix ASC, rowid ASC LIMIT ?
                )
                """,
                (overflow,),
            )

    def __len__(self) -> int:
        with self._lock:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    "DELETE FROM event_idempotency WHERE claimed_at_unix < ?",
                    (float(self._clock()) - self.ttl_seconds,),
                )
                count = connection.execute(
                    "SELECT COUNT(*) FROM event_idempotency"
                ).fetchone()[0]
            return int(count)


def build_event_idempotency_table(
    *,
    enabled: bool,
    db_path: str | Path | None,
    ttl_seconds: float,
    max_entries: int,
) -> EventIdempotencyTable | SqliteEventIdempotencyTable | None:
    """按配置选择后端：disabled=None；db_path 非空→SQLite；否则进程内。"""
    if not enabled:
        return None
    if db_path and str(db_path).strip():
        return SqliteEventIdempotencyTable(
            db_path,
            ttl_seconds=ttl_seconds,
            max_entries=max_entries,
        )
    return EventIdempotencyTable(ttl_seconds=ttl_seconds, max_entries=max_entries)
