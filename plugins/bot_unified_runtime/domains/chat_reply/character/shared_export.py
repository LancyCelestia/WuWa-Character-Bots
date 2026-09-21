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
from plugins.bot_unified_runtime.domains.core.contracts.runtime import StrictBaseModel
from plugins.bot_unified_runtime.domains.core.session_keys import (
    GROUP_SESSION_PREFIX,
    LEGACY_GROUP_SCHEME,
    is_group_session_key,
)

# 群键口径（2026-09-21 D3-1 根修，与 F4 席 shared_group.py 同源）：本文件此前
# 两处都按冒号形 ``group:<群号>`` 认群，而 conversation_turns.session_id 由摄取层
# NoneBot get_session_id() 产出＝下划线形 ``group_<群号>_<发送者>`` ⇒
# ①``include_private=False`` 的 SQL 过滤恒 0 行（群导出静默空转）、
# ②逐行分类把真群行判成 private（群记录以 PERSONAL 级出库，语义反向）。
# 判据与两枚前缀一律取自中央件 domains/core/session_keys，本文件禁持第三份字面量。
# ⚠ LIKE 转义：``_`` 在 LIKE 里是单字符通配符，不转义则前缀 ``group_`` 会误吞
# ``groupX...`` 形行（先例=shared_group.py:_like_prefix_pattern 与其回归锁）。
# 该转义器目前在本域有两份逐字实现（shared_group / 本件），收编进 session_keys
# 是登记在案的整改项（docs/audit-20260921.md），此处不再抄第三份。
_LIKE_ESCAPE_CHAR = "!"


def _like_prefix_pattern(prefix: str) -> str:
    """前缀 → LIKE 模式：转义 ``!``/``%``/``_`` 再追通配 ``%``。"""
    escaped = (
        prefix.replace(_LIKE_ESCAPE_CHAR, _LIKE_ESCAPE_CHAR * 2)
        .replace("%", f"{_LIKE_ESCAPE_CHAR}%")
        .replace("_", f"{_LIKE_ESCAPE_CHAR}_")
    )
    return f"{escaped}%"


# 群行 SQL 过滤片段（两形并列：权威下划线形 ∪ 历史/合成冒号形，与
# is_group_session_key 的判据覆盖面等价；前缀取自中央件字面值，无注入面）。
_GROUP_LIKE_CLAUSES = " OR ".join(
    f"session_id LIKE '{_like_prefix_pattern(prefix)}' ESCAPE '{_LIKE_ESCAPE_CHAR}'"
    for prefix in (GROUP_SESSION_PREFIX, LEGACY_GROUP_SCHEME)
)
_GROUP_SCOPE_SQL = f"AND ({_GROUP_LIKE_CLAUSES})"


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
                    else _GROUP_SCOPE_SQL
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
            session_kind = "group" if is_group_session_key(session_id) else "private"
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
