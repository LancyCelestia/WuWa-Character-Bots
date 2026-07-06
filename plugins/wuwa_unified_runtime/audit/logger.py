from __future__ import annotations

from typing import Protocol

from plugins.wuwa_unified_runtime.contracts import AuditRecord

_SENSITIVE_MARKERS = ("token=", "cookie=", "authkey=", "password=", "secret=")


class AuditRepository(Protocol):
    def append(self, record: AuditRecord) -> AuditRecord:
        raise NotImplementedError

    def list_records(self, request_id: str | None = None) -> list[AuditRecord]:
        raise NotImplementedError


def redact_private_debug(value: str) -> str:
    redacted = value
    for marker in _SENSITIVE_MARKERS:
        lower = redacted.lower()
        index = lower.find(marker)
        if index >= 0:
            end = redacted.find(" ", index)
            if end < 0:
                end = len(redacted)
            redacted = f"{redacted[:index]}{marker}[redacted]{redacted[end:]}"
    return redacted


class InMemoryAuditLogger:
    def __init__(self) -> None:
        self._records: list[AuditRecord] = []

    def append(self, record: AuditRecord) -> AuditRecord:
        safe_record = record.model_copy(
            update={"private_debug": redact_private_debug(record.private_debug)}
        )
        self._records.append(safe_record)
        return safe_record

    def list_records(self, request_id: str | None = None) -> list[AuditRecord]:
        if request_id is None:
            return list(self._records)
        return [record for record in self._records if record.request_id == request_id]
