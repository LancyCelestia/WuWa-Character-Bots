"""文件审计日志（JSONL，脱敏，自动轮转）。

配合内存/SQLite 审计仓库使用：``TeeAuditRepository`` 把每条脱敏
审计记录追加到 JSONL 文件，超过 ``max_bytes`` 时重命名为 ``*.old``
后重开，保留最近两代文件。文件放在 ``data/``（git 忽略），适合
不开数据库时也能 ``tail`` 排查。

配置：``BOT_AUDIT_LOG_FILE``（例如 ``data/bot_audit.jsonl``）、
``BOT_AUDIT_LOG_MAX_BYTES``（默认 2MB）。
"""

from __future__ import annotations

import json
from pathlib import Path

from plugins.bot_unified_runtime.audit import (
    AuditRepository,
    redact_private_debug,
)
from plugins.bot_unified_runtime.contracts import AuditRecord


class FileAuditLog:
    def __init__(self, path: str | Path, *, max_bytes: int = 2 * 1024 * 1024) -> None:
        self.path = Path(path).expanduser()
        self.max_bytes = max(64 * 1024, int(max_bytes))

    def append(self, record: AuditRecord) -> None:
        safe_record = record.model_copy(
            update={"private_debug": redact_private_debug(record.private_debug)}
        )
        line = safe_record.model_dump_json()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size >= self.max_bytes:
                old_path = self.path.with_suffix(self.path.suffix + ".old")
                try:
                    old_path.unlink()
                except OSError:
                    pass
                self.path.rename(old_path)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.write("\n")
        except OSError:
            # 文件日志失败不能打断业务；审计主仓库仍然在写。
            return

    def read_recent(self, limit: int = 20) -> list[dict[str, str]]:
        if not self.path.exists():
            return []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()[-limit:]
        except OSError:
            return []
        records: list[dict[str, str]] = []
        for line in lines:
            try:
                payload = json.loads(line)
            except ValueError:
                continue
            if isinstance(payload, dict):
                records.append({str(k): str(v) for k, v in payload.items()})
        return records


class TeeAuditRepository:
    """主审计仓库 + 文件日志双写。"""

    def __init__(self, primary: AuditRepository, file_log: FileAuditLog) -> None:
        self.primary = primary
        self.file_log = file_log

    def append(self, record: AuditRecord) -> AuditRecord:
        self.file_log.append(record)
        return self.primary.append(record)

    def list_records(self, request_id: str | None = None) -> list[AuditRecord]:
        return self.primary.list_records(request_id)


def build_audit_with_file_log(
    primary: AuditRepository,
    log_file: str = "",
    *,
    max_bytes: int = 2 * 1024 * 1024,
) -> AuditRepository:
    path = (log_file or "").strip()
    if not path:
        return primary
    return TeeAuditRepository(primary, FileAuditLog(path, max_bytes=max_bytes))
