"""公共会话记录导出接口（预留平台共享用）。

用途：未来做一个平台，让多个机器人共享**脱敏后的公共会话记录**。
本模块先把接口和本地实现做好，平台接入时只需实现同一 Protocol。

脱敏规则（保守）：
- 不导出 sender_id / bot_id / session_id / request_id 原值；
- 只导出群会话与（可选）私聊的人格化对话（kind=chat），
  命令/被动回复（kind=command）一律排除；
- 文本经审计级脱敏（token/cookie/key 打码）并截断到固定长度。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Protocol

from plugins.bot_unified_runtime.audit import redact_private_debug
from plugins.bot_unified_runtime.contracts import PrivacyLevel
from plugins.bot_unified_runtime.contracts.runtime import StrictBaseModel


class SharedConversationRecord(StrictBaseModel):
    record_id: str
    created_at: str
    session_kind: str  # group | private
    role: str  # user | assistant
    redacted_text: str
    privacy_level: PrivacyLevel = PrivacyLevel.GROUP


class SharedConversationExportProvider(Protocol):
    def export(
        self,
        *,
        limit: int = 100,
        since_iso: str = "",
        after_record_id: str = "",
    ) -> list[SharedConversationRecord]:
        """导出脱敏公共会话记录；``after_record_id`` 用作增量游标。"""


class NullSharedConversationExportProvider:
    def export(
        self,
        *,
        limit: int = 100,
        since_iso: str = "",
        after_record_id: str = "",
    ) -> list[SharedConversationRecord]:
        return []


class SQLiteSharedConversationExporter:
    def __init__(
        self,
        db_path: str | Path,
        *,
        include_private: bool = False,
        max_chars: int = 200,
    ) -> None:
        self.db_path = Path(db_path)
        self.include_private = bool(include_private)
        self.max_chars = max(60, int(max_chars))

    def export(
        self,
        *,
        limit: int = 100,
        since_iso: str = "",
        after_record_id: str = "",
    ) -> list[SharedConversationRecord]:
        if not self.db_path.exists():
            return []
        try:
            with sqlite3.connect(self.db_path) as connection:
                connection.row_factory = sqlite3.Row
                columns = {
                    str(row["name"])
                    for row in connection.execute(
                        "PRAGMA table_info(conversation_turns)"
                    ).fetchall()
                }
                kind_filter = (
                    "AND (kind IS NULL OR kind = 'chat')"
                    if "kind" in columns
                    else ""
                )
                private_filter = (
                    ""
                    if self.include_private
                    else "AND session_id LIKE 'group:%'"
                )
                since_filter = "AND created_at >= ?" if since_iso else ""
                cursor_filter = ""
                if after_record_id:
                    try:
                        cursor_rowid = int(
                            str(after_record_id).removeprefix("turn_")
                        )
                        cursor_filter = "AND rowid < ?"
                    except ValueError:
                        cursor_filter = ""
                parameters: list[object] = []
                if since_iso:
                    parameters.append(since_iso)
                if cursor_filter:
                    parameters.append(cursor_rowid)
                parameters.append(max(1, min(500, int(limit))))
                cursor = connection.execute(
                    f"""
                    SELECT rowid, created_at, session_id, role, text
                    FROM conversation_turns
                    WHERE 1 = 1
                      {private_filter}
                      {kind_filter}
                      {since_filter}
                      {cursor_filter}
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT ?
                    """,
                    parameters,
                )
                rows = list(cursor.fetchall())
        except sqlite3.Error:
            return []
        records: list[SharedConversationRecord] = []
        for row in rows:
            session_id = str(row["session_id"])
            session_kind = "group" if session_id.startswith("group:") else "private"
            text = str(row["text"])
            redacted = redact_private_debug(text)
            if len(redacted) > self.max_chars:
                redacted = f"{redacted[: self.max_chars - 1]}…"
            records.append(
                SharedConversationRecord(
                    record_id=f"turn_{row['rowid']}",
                    created_at=str(row["created_at"]),
                    session_kind=session_kind,
                    role=str(row["role"]),
                    redacted_text=redacted,
                    privacy_level=(
                        PrivacyLevel.GROUP
                        if session_kind == "group"
                        else PrivacyLevel.PERSONAL
                    ),
                )
            )
        return records


def build_shared_conversation_export_provider(
    config: object,
) -> SharedConversationExportProvider:
    enabled = bool(getattr(config, "bot_shared_export_enabled", False))
    db_path = str(getattr(config, "bot_history_db_path", "")).strip()
    if not enabled or not db_path:
        return NullSharedConversationExportProvider()
    return SQLiteSharedConversationExporter(
        db_path,
        include_private=bool(
            getattr(config, "bot_shared_export_include_private", False)
        ),
        max_chars=int(getattr(config, "bot_shared_export_max_chars", 200)),
    )
