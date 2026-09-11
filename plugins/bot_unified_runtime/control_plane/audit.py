"""控制面审计（B4 §8.5）：``control_plane_audit`` 表写入器。

- 与 B5 账本同库不同表（B4 §8.5 推荐口径，减少连接数），默认
  ``data/llm_billing.sqlite3``（经 runtime_paths 重映射到 Runtime 数据根）。
- SQLite 惯例与 ``sender/queue.py`` 同源：WAL 先行、进程内单连接 + 锁、
  ``_ensure_schema_once``。
- ``query``/``detail`` 入库前一律过 ``redact_private_debug`` 并剔除
  token/secret 型 query 参数值；写入失败只打日志，绝不影响响应。
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
from typing import Any

logger = logging.getLogger(__name__)

# query 串中敏感参数值剔除（B4 §8.5：query 已脱敏；B4 §5.1 明令 token
# 不允许出现在 URL/query——双保险，防编排失误）。
_SENSITIVE_QUERY_RE = re.compile(
    r"(?i)(token|secret|key|password|authorization|credential)=([^&]*)"
)
_REDACTED_QUERY = r"\1=[redacted]"


def redact_query(query: str) -> str:
    """query 串脱敏：敏感参数值打码 + 复用 redact_private_debug。"""
    text = _SENSITIVE_QUERY_RE.sub(_REDACTED_QUERY, str(query or ""))
    if not text:
        return ""
    try:
        from plugins.bot_unified_runtime.audit.logger import redact_private_debug

        return redact_private_debug(text)
    except Exception:  # noqa: BLE001 - 脱敏模块不可用时保留正则结果。
        return text


def redact_error_for_dto(value: object, limit: int = 200) -> str:
    """DTO 白名单字段的脱敏短文本（如 status/models 的 last_error）。"""
    text = str(value or "")
    if not text:
        return ""
    try:
        from plugins.bot_unified_runtime.audit.logger import redact_private_debug

        text = redact_private_debug(text)
    except Exception:  # 脱敏模块不可用时保留原文截断。
        logger.debug("control plane redact helper unavailable", exc_info=True)
    return text[: max(0, int(limit))]


def resolve_default_ledger_db_path() -> str:
    """控制面审计默认库路径（与 B5 账本同库）；channel_health 同法重映射。"""
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[3]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    try:
        from scripts.runtime_paths import runtime_path

        return str(runtime_path("data/llm_billing.sqlite3"))
    except Exception:  # noqa: BLE001 - 解析失败退回相对路径。
        return "data/llm_billing.sqlite3"


class ControlPlaneAuditStore:
    """``control_plane_audit`` 表写入器（写入失败静默计数）。"""

    def __init__(self, db_path: str) -> None:
        self.db_path = str(db_path)
        self.write_error_count = 0
        self._lock = threading.RLock()
        self._connection: sqlite3.Connection | None = None
        self._schema_ready = False

    def record(
        self,
        *,
        subject: str,
        source: str,
        method: str,
        path: str,
        query: str = "",
        status_code: int,
        bytes_out: int = 0,
        debug_id: str = "",
        detail: str = "",
    ) -> None:
        """写一条审计记录；吞掉一切异常（审计故障不影响请求）。"""
        try:
            self._record(
                subject=str(subject or "anonymous")[:120],
                source=str(source or "local")[:20],
                method=str(method or "")[:10],
                path=str(path or "")[:500],
                query=redact_query(query)[:500],
                status_code=int(status_code),
                bytes_out=max(0, int(bytes_out)),
                debug_id=str(debug_id or "")[:64],
                detail=str(detail or "")[:500],
            )
        except Exception:
            self.write_error_count += 1
            logger.debug("control plane audit write failed", exc_info=True)

    def _record(self, **values: Any) -> None:
        with self._lock:
            self._ensure_schema_once()
            connection = self._shared_connection()
            connection.execute(
                """
                INSERT INTO control_plane_audit (
                    ts, subject, source, method, path, query,
                    status_code, bytes_out, debug_id, detail
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _now_iso(),
                    values["subject"],
                    values["source"],
                    values["method"],
                    values["path"],
                    values["query"],
                    values["status_code"],
                    values["bytes_out"],
                    values["debug_id"],
                    values["detail"],
                ),
            )
            connection.commit()

    def ping(self) -> bool:
        """可达性探针（/health 用）。"""
        try:
            with self._lock:
                self._ensure_schema_once()
                self._shared_connection().execute("SELECT 1")
            return True
        except sqlite3.Error:
            return False

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                try:
                    self._connection.close()
                except sqlite3.Error:
                    pass
                self._connection = None
                self._schema_ready = False

    # ---- SQLite 惯例（同 sender/queue.py） ----

    def _shared_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            connection = sqlite3.connect(
                self.db_path, timeout=5.0, check_same_thread=False
            )
            connection.row_factory = sqlite3.Row
            self._connection = connection
        return self._connection

    def _ensure_schema_once(self) -> None:
        if self._schema_ready:
            return
        self._ensure_schema()
        self._schema_ready = True

    def _ensure_schema(self) -> None:
        import pathlib

        pathlib.Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        connection = self._shared_connection()
        try:
            connection.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error:
            pass  # 不支持 WAL 时降级默认 journal，不致命。
        connection.execute(_DDL)
        connection.execute("CREATE INDEX IF NOT EXISTS idx_cp_audit_ts ON control_plane_audit (ts)")
        connection.commit()


# DDL 与 docs/design/control-plane-api.md §8.5 逐字段对齐。
_DDL = """
CREATE TABLE IF NOT EXISTS control_plane_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    subject TEXT NOT NULL,
    source TEXT NOT NULL,
    method TEXT NOT NULL,
    path TEXT NOT NULL,
    query TEXT NOT NULL DEFAULT '',
    status_code INTEGER NOT NULL,
    bytes_out INTEGER NOT NULL DEFAULT 0,
    debug_id TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT ''
)
"""


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now().astimezone().isoformat(timespec="milliseconds")
