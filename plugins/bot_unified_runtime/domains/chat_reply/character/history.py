from __future__ import annotations

import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from plugins.bot_unified_runtime.contracts import (
    ConversationHistoryResult,
    ConversationTurn,
    PrivacyLevel,
)

# H8 防线一（写入侧脱敏）：管理员会按官方用法输入 `/bot model add … key=<明文>`
# （capabilities/runtime_admin.py 的用法文案主动引导明文），而命令原文此前会
# **不加处理**写进 conversation_turns，随后被拼进 system prompt 发给当轮路由到
# 的任意模型供应商 —— 直接违反「密钥永不入库不入聊天」硬约束。
# 这里在落库前遮蔽赋值形态的密钥；`env:变量名` 这类间接引用保持可读，避免把
# 正常配置记录改得不可辨认。
_HISTORY_SECRET_RE = re.compile(
    r"(?i)(\b[a-z0-9_]*(?:key|token|secret|password|passwd|authkey|credential|"
    r"cookie|session[_-]?id)[a-z0-9_]*\s*[:=]\s*)"
    r"(?!env:)([^\s,;]+)"
)
_HISTORY_BEARER_RE = re.compile(r"(?i)(\bbearer\s+)([A-Za-z0-9._\-]{8,})")
_HISTORY_SK_RE = re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9][A-Za-z0-9_\-]{8,}")
# 平台 Cookie 罐的关键名（`/bot cookie import weibo SUB=…` 这类命令的原文里
# 是裸 `名称=值`，不含 token/key 之类字样，上面的通用规则抓不到）。
_HISTORY_COOKIE_KEY_RE = re.compile(
    r"(?i)\b(SESSDATA|SESSDATA_|bili_jct|DedeUserID|SUBP|SUB|ALF|SSOLoginState|"
    r"web_session|sessionid|sessionid_ss|d_c0|z_c0|auth_token|ct0|kuaishou\.[a-z0-9_]+)"
    r"\s*=\s*([^\s;]+)"
)


def redact_history_text(text: str) -> str:
    """遮蔽对话历史里的明文凭据（H8）。``env:`` 间接引用保持原样。"""
    value = _HISTORY_SECRET_RE.sub(lambda m: f"{m.group(1)}[redacted]", text or "")
    value = _HISTORY_BEARER_RE.sub(lambda m: f"{m.group(1)}[redacted]", value)
    value = _HISTORY_SK_RE.sub("sk-[redacted]", value)
    return _HISTORY_COOKIE_KEY_RE.sub(lambda m: f"{m.group(1)}=[redacted]", value)


@dataclass(frozen=True)
class HistoryWindowTurn:
    """时间窗召回的一行记录（多说话人，带 sender_id）。

    与 contracts.ConversationTurn 分开：时间窗总结需要区分同一会话里的
    不同说话人，而既有 ConversationTurn 无 sender 字段且契约文件保持
    不动，此处新增 dataclass 保证既有读取面零破坏。
    """

    sender_id: str
    role: str
    text: str
    created_at: str


def _epoch_to_iso(epoch: float) -> str:
    return datetime.fromtimestamp(float(epoch), tz=UTC).isoformat()


def _parse_epoch(created_at: str) -> float | None:
    """把 ISO 时间串解析成 epoch；解析失败返回 None（由调用方兜底）。"""
    try:
        value = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.timestamp()


class ConversationHistoryProvider(Protocol):
    def retrieve(
        self,
        *,
        request_id: str,
        platform: str,
        adapter: str,
        bot_id: str,
        session_id: str,
        sender_id: str,
        max_turns: int,
        max_chars: int,
    ) -> ConversationHistoryResult:
        raise NotImplementedError


class ConversationHistoryRecorder(Protocol):
    def append_turn(
        self,
        *,
        request_id: str,
        platform: str,
        adapter: str,
        bot_id: str,
        session_id: str,
        sender_id: str,
        role: str,
        text: str,
        kind: str = "chat",
    ) -> None:
        raise NotImplementedError


class ConversationHistoryCleaner(Protocol):
    def clear_scope(
        self,
        *,
        platform: str,
        adapter: str,
        bot_id: str,
        session_id: str,
        sender_id: str,
    ) -> int:
        raise NotImplementedError


class ConversationHistoryStore(
    ConversationHistoryProvider,
    ConversationHistoryRecorder,
    ConversationHistoryCleaner,
    Protocol,
):
    pass


class NullConversationHistoryProvider:
    def append_turn(
        self,
        *,
        request_id: str,
        platform: str,
        adapter: str,
        bot_id: str,
        session_id: str,
        sender_id: str,
        role: str,
        text: str,
        kind: str = "chat",
    ) -> None:
        return None

    def retrieve(
        self,
        *,
        request_id: str,
        platform: str,
        adapter: str,
        bot_id: str,
        session_id: str,
        sender_id: str,
        max_turns: int,
        max_chars: int,
    ) -> ConversationHistoryResult:
        return ConversationHistoryResult(request_id=request_id)

    def retrieve_window(
        self,
        *,
        platform: str,
        adapter: str,
        bot_id: str,
        session_id: str,
        since_epoch: float,
        until_epoch: float,
        max_turns: int,
        max_chars: int,
        exclude_request_id: str = "",
    ) -> list[HistoryWindowTurn]:
        return []

    def clear_scope(
        self,
        *,
        platform: str,
        adapter: str,
        bot_id: str,
        session_id: str,
        sender_id: str,
    ) -> int:
        return 0


class InMemoryConversationHistoryStore:
    """进程内最近对话历史：给控制台 REPL 等本地入口提供多轮连续性。

    重启即清空，不落盘；仅用于测试体验，真实机器人仍用
    SQLiteConversationHistoryRepository。
    """

    def __init__(self, *, max_turns: int = 40) -> None:
        self.max_turns = max(1, int(max_turns))
        self._turns: list[ConversationTurn] = []

    def append_turn(
        self,
        *,
        request_id: str,
        platform: str,
        adapter: str,
        bot_id: str,
        session_id: str,
        sender_id: str,
        role: str,
        text: str,
        kind: str = "chat",
    ) -> None:
        clean_text = redact_history_text(text.strip())
        if not clean_text:
            return
        self._turns.append(
            ConversationTurn(
                role=role,
                text=clean_text,
                created_at=datetime.now(UTC).isoformat(),
            )
        )
        if len(self._turns) > self.max_turns:
            self._turns = self._turns[-self.max_turns :]

    def retrieve(
        self,
        *,
        request_id: str,
        platform: str,
        adapter: str,
        bot_id: str,
        session_id: str,
        sender_id: str,
        max_turns: int,
        max_chars: int,
    ) -> ConversationHistoryResult:
        selected: list[ConversationTurn] = []
        chars_used = 0
        for turn in reversed(self._turns):
            if len(selected) >= max_turns:
                break
            remaining = max_chars - chars_used
            if remaining <= 0:
                break
            text = _clip_text(turn.text, remaining)
            selected.append(
                ConversationTurn(
                    role=turn.role,
                    text=text,
                    created_at=turn.created_at,
                )
            )
            chars_used += len(text)
        selected.reverse()
        return ConversationHistoryResult(
            request_id=request_id,
            turns=selected,
            privacy_level=PrivacyLevel.PERSONAL,
        )

    def retrieve_window(
        self,
        *,
        platform: str,
        adapter: str,
        bot_id: str,
        session_id: str,
        since_epoch: float,
        until_epoch: float,
        max_turns: int,
        max_chars: int,
        exclude_request_id: str = "",
    ) -> list[HistoryWindowTurn]:
        """内存版时间窗召回（控制台/测试用）；该存储不区分说话人，sender 留空。"""
        if max_turns <= 0 or max_chars <= 0:
            return []
        selected: list[HistoryWindowTurn] = []
        chars_used = 0
        for turn in reversed(self._turns):
            turn_epoch = _parse_epoch(turn.created_at)
            if turn_epoch is None or not (since_epoch <= turn_epoch <= until_epoch):
                continue
            if len(selected) >= max_turns:
                break
            remaining = max_chars - chars_used
            if remaining <= 0:
                break
            text = _clip_text(turn.text, remaining)
            chars_used += len(text)
            selected.append(
                HistoryWindowTurn(
                    sender_id="",
                    role=turn.role,
                    text=text,
                    created_at=turn.created_at,
                )
            )
        selected.reverse()
        return selected

    def clear_scope(
        self,
        *,
        platform: str,
        adapter: str,
        bot_id: str,
        session_id: str,
        sender_id: str,
    ) -> int:
        cleared = len(self._turns)
        self._turns = []
        return cleared


class SQLiteConversationHistoryRepository:
    def __init__(self, db_path: str | Path, *, max_items: int = 1000) -> None:
        self.db_path = Path(db_path)
        self.max_items = max(1, int(max_items))
        # 每次 append 都重跑建表 DDL 是纯浪费：进程内建一次即可。
        self._schema_ready = False
        # 冷启动时事件循环与 offload 线程可能并发首写：无锁会双跑 ALTER。
        self._schema_lock = threading.Lock()

    def _ensure_schema_once(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            self._ensure_schema()
            self._schema_ready = True

    def append_turn(
        self,
        *,
        request_id: str,
        platform: str,
        adapter: str,
        bot_id: str,
        session_id: str,
        sender_id: str,
        role: str,
        text: str,
        kind: str = "chat",
    ) -> None:
        clean_text = redact_history_text(text.strip())
        if not clean_text:
            return
        self._ensure_schema_once()
        safe_kind = kind if kind in {"chat", "command", "system"} else "chat"
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO conversation_turns (
                    request_id,
                    platform,
                    adapter,
                    bot_id,
                    session_id,
                    sender_id,
                    role,
                    text,
                    created_at,
                    kind
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    platform,
                    adapter,
                    bot_id,
                    session_id,
                    sender_id,
                    role,
                    clean_text,
                    now,
                    safe_kind,
                ),
            )
            self._prune_scope(
                connection,
                platform=platform,
                adapter=adapter,
                bot_id=bot_id,
                session_id=session_id,
                sender_id=sender_id,
            )

    def retrieve(
        self,
        *,
        request_id: str,
        platform: str,
        adapter: str,
        bot_id: str,
        session_id: str,
        sender_id: str,
        max_turns: int,
        max_chars: int,
    ) -> ConversationHistoryResult:
        if max_turns <= 0 or max_chars <= 0:
            return ConversationHistoryResult(request_id=request_id)
        self._ensure_schema_once()
        rows = self._fetch_rows(
            platform=platform,
            adapter=adapter,
            bot_id=bot_id,
            session_id=session_id,
            sender_id=sender_id,
            limit=max_turns + 2,
        )
        # 排除本轮消息自身（控制台/某些入口在生成前就落库了当前轮），
        # 避免把"刚才说的话"当作历史喂回去。
        rows = [row for row in rows if str(row["request_id"]) != request_id]
        rows = rows[:max_turns]
        selected: list[ConversationTurn] = []
        chars_used = 0
        for row in rows:
            remaining = max_chars - chars_used
            if remaining <= 0:
                break
            text = str(row["text"])
            if len(text) > remaining:
                text = _clip_text(text, remaining)
            selected.append(
                ConversationTurn(
                    role=str(row["role"]),
                    text=text,
                    created_at=str(row["created_at"]),
                )
            )
            chars_used += len(text)
        return ConversationHistoryResult(
            request_id=request_id,
            turns=list(reversed(selected)),
            privacy_level=PrivacyLevel.PERSONAL,
        )

    def retrieve_window(
        self,
        *,
        platform: str,
        adapter: str,
        bot_id: str,
        session_id: str,
        since_epoch: float,
        until_epoch: float,
        max_turns: int,
        max_chars: int,
        exclude_request_id: str = "",
    ) -> list[HistoryWindowTurn]:
        """按 created_at 时间窗召回多说话人记录（时间窗总结用）。

        created_at 落库为 UTC ISO 串且全部出自同一 `datetime.now(UTC).isoformat()`
        格式，字典序即时间序，故 SQL 里与同格式 ISO 边界做 `>= / <=` 字符串
        比较（epoch 数值直接比 TEXT 会因 SQLite 类型序全部错判）；Python 侧
        再按解析出的 epoch 复核一遍，异构时间串（他方写入）也不漏。输出按
        时间升序、从最新往回收，受 max_turns / max_chars 双预算钳制；命令
        轮次与 exclude_request_id 命中的当前轮照旧排除。
        """
        if max_turns <= 0 or max_chars <= 0:
            return []
        self._ensure_schema_once()
        selected: list[HistoryWindowTurn] = []
        chars_used = 0
        with self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT request_id, sender_id, role, text, created_at
                FROM conversation_turns
                WHERE platform = ?
                  AND adapter = ?
                  AND bot_id = ?
                  AND session_id = ?
                  AND kind != 'command'
                  AND created_at >= ?
                  AND created_at <= ?
                ORDER BY created_at DESC, rowid DESC
                """,
                (
                    platform,
                    adapter,
                    bot_id,
                    session_id,
                    _epoch_to_iso(since_epoch),
                    _epoch_to_iso(until_epoch),
                ),
            )
            for row in cursor:  # 惰性逐行：预算耗尽即停，不做全量 fetch。
                if str(row["request_id"]) == exclude_request_id:
                    continue
                row_epoch = _parse_epoch(str(row["created_at"]))
                if row_epoch is not None and not (
                    since_epoch <= row_epoch <= until_epoch
                ):
                    continue
                remaining = max_chars - chars_used
                if remaining <= 0:
                    break
                text = str(row["text"])
                if len(text) > remaining:
                    text = _clip_text(text, remaining)
                chars_used += len(text)
                selected.append(
                    HistoryWindowTurn(
                        sender_id=str(row["sender_id"]),
                        role=str(row["role"]),
                        text=text,
                        created_at=str(row["created_at"]),
                    )
                )
                if len(selected) >= max_turns:
                    break
        selected.reverse()
        return selected

    def clear_scope(
        self,
        *,
        platform: str,
        adapter: str,
        bot_id: str,
        session_id: str,
        sender_id: str,
    ) -> int:
        self._ensure_schema_once()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM conversation_turns
                WHERE platform = ?
                  AND adapter = ?
                  AND bot_id = ?
                  AND session_id = ?
                  AND sender_id = ?
                """,
                (platform, adapter, bot_id, session_id, sender_id),
            )
            return max(0, cursor.rowcount)

    def _fetch_rows(
        self,
        *,
        platform: str,
        adapter: str,
        bot_id: str,
        session_id: str,
        sender_id: str,
        limit: int,
    ) -> list[sqlite3.Row]:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT request_id, role, text, created_at
                FROM conversation_turns
                WHERE platform = ?
                  AND adapter = ?
                  AND bot_id = ?
                  AND session_id = ?
                  AND sender_id = ?
                  -- H8 防线二：命令轮次不进上下文。用户侧命令原文（例如
                  -- /bot model add … key=…）会经 providers → chat 拼进 system
                  -- prompt 并外发给模型供应商；这里把 kind='command' 整体挡在
                  -- 召回之外（防线一在写入侧做脱敏，见 _redact_history_text）。
                  AND kind != 'command'
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (platform, adapter, bot_id, session_id, sender_id, limit),
            )
            return list(cursor.fetchall())

    def _prune_scope(
        self,
        connection: sqlite3.Connection,
        *,
        platform: str,
        adapter: str,
        bot_id: str,
        session_id: str,
        sender_id: str,
    ) -> None:
        connection.execute(
            """
            DELETE FROM conversation_turns
            WHERE platform = ?
              AND adapter = ?
              AND bot_id = ?
              AND session_id = ?
              AND sender_id = ?
              AND rowid NOT IN (
                  SELECT rowid
                  FROM conversation_turns
                  WHERE platform = ?
                    AND adapter = ?
                    AND bot_id = ?
                    AND session_id = ?
                    AND sender_id = ?
                  ORDER BY created_at DESC, rowid DESC
                  LIMIT ?
              )
            """,
            (
                platform,
                adapter,
                bot_id,
                session_id,
                sender_id,
                platform,
                adapter,
                bot_id,
                session_id,
                sender_id,
                self.max_items,
            ),
        )

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_turns (
                    request_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    adapter TEXT NOT NULL,
                    bot_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            # 兼容旧表：补充 kind 列，区分 LLM 人设回复（chat）与
            # 命令/被动回复（command），供群共享摘要过滤使用。
            columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(conversation_turns)"
                ).fetchall()
            }
            if "kind" not in columns:
                connection.execute(
                    "ALTER TABLE conversation_turns "
                    "ADD COLUMN kind TEXT NOT NULL DEFAULT 'chat'"
                )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_conversation_turns_scope_time
                ON conversation_turns (
                    platform,
                    adapter,
                    bot_id,
                    session_id,
                    sender_id,
                    created_at
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection


def build_conversation_history_provider(config: object) -> ConversationHistoryStore:
    enabled = bool(getattr(config, "bot_history_enabled", False))
    db_path = str(getattr(config, "bot_history_db_path", "")).strip()
    max_items = int(getattr(config, "bot_history_max_items", 1000))
    if not enabled or not db_path:
        return NullConversationHistoryProvider()
    return SQLiteConversationHistoryRepository(db_path, max_items=max_items)


def _clip_text(value: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(value) <= max_chars:
        return value
    if max_chars <= 1:
        return "…"
    return f"{value[: max_chars - 1]}…"
