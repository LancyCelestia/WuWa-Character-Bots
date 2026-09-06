"""Auditable, redacted PromptArtifact storage and execution gating."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

_SECRET_KEY_RE = re.compile(
    r"(?i)(api[_-]?key|authorization|bearer|token|cookie|password|secret)"
)
_SECRET_VALUE_RE = re.compile(
    r"(?i)(?:authorization\s*[:=]\s*(?:bearer\s+)?|bearer\s+|api[_-]?key\s*[:=]\s*)[^\s,;]+"
)
_OPENAI_KEY_RE = re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9][A-Za-z0-9_-]{8,}")
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


class PromptExecutionMode(StrEnum):
    EXECUTE = "execute"
    PREVIEW = "preview"
    APPROVED = "approved"


@dataclass(frozen=True)
class PromptArtifact:
    artifact_id: str
    request_id: str
    created_at: str
    prompt_sha256: str
    messages_redacted: list[dict[str, Any]]
    tool_ids: list[str]
    llm_options_safe: dict[str, Any]
    path: str | None


class PromptAuditStore:
    def __init__(
        self,
        directory: str | Path | None,
        *,
        max_chars: int = 12000,
        include_messages: bool = True,
    ) -> None:
        self.directory = Path(directory).expanduser() if directory else None
        self.max_chars = max(200, int(max_chars))
        self.include_messages = bool(include_messages)

    def write(
        self,
        *,
        request_id: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        llm_options: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> PromptArtifact:
        redacted_messages = self._redact_messages(messages)
        safe_options = self._redact_mapping(llm_options)
        tool_ids = self._tool_ids(tools)
        digest_payload = {
            "messages": redacted_messages,
            "tools": self._redact_value(tools),
            "llm_options": safe_options,
        }
        prompt_sha256 = hashlib.sha256(
            json.dumps(
                digest_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        artifact_id = f"prompt_{prompt_sha256[:16]}"
        artifact = PromptArtifact(
            artifact_id=artifact_id,
            request_id=str(request_id),
            created_at=datetime.now(UTC).isoformat(),
            prompt_sha256=prompt_sha256,
            messages_redacted=redacted_messages,
            tool_ids=tool_ids,
            llm_options_safe=safe_options,
            path=None,
        )
        payload = {
            "artifact_id": artifact.artifact_id,
            "request_id": artifact.request_id,
            "created_at": artifact.created_at,
            "prompt_sha256": artifact.prompt_sha256,
            "messages_redacted": artifact.messages_redacted
            if self.include_messages
            else [],
            "tool_ids": artifact.tool_ids,
            "llm_options_safe": artifact.llm_options_safe,
            "metadata": self._redact_mapping(metadata or {}),
        }
        path = self._write_atomic(request_id, prompt_sha256, payload)
        return PromptArtifact(
            **{
                **artifact.__dict__,
                "path": str(path) if path is not None else None,
            }
        )

    def _write_atomic(
        self,
        request_id: str,
        digest: str,
        payload: dict[str, Any],
    ) -> Path | None:
        if self.directory is None:
            return None
        self.directory.mkdir(parents=True, exist_ok=True)
        safe_request = _SAFE_NAME_RE.sub("_", str(request_id)).strip("._") or "request"
        target = self.directory / f"{safe_request}_{digest[:16]}.json"
        fd, temporary = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=self.directory,
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return target

    def _redact_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for message in messages:
            value = self._redact_value(message)
            result.append(value if isinstance(value, dict) else {"content": value})
        return result

    def _redact_mapping(self, value: dict[str, Any]) -> dict[str, Any]:
        result = self._redact_value(value)
        return result if isinstance(result, dict) else {}

    def _redact_value(self, value: Any, *, key: str = "") -> Any:
        if _SECRET_KEY_RE.search(key):
            return "[redacted]"
        if isinstance(value, dict):
            return {
                str(item_key): self._redact_value(item_value, key=str(item_key))
                for item_key, item_value in value.items()
            }
        if isinstance(value, list):
            return [self._redact_value(item, key=key) for item in value]
        if isinstance(value, tuple):
            return [self._redact_value(item, key=key) for item in value]
        if isinstance(value, str):
            redacted = _SECRET_VALUE_RE.sub("[redacted]", value)
            redacted = _OPENAI_KEY_RE.sub("sk-[redacted]", redacted)
            return redacted[: self.max_chars]
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return str(value)[: self.max_chars]

    @staticmethod
    def _tool_ids(tools: list[dict[str, Any]]) -> list[str]:
        ids: list[str] = []
        for tool in tools:
            function = tool.get("function") if isinstance(tool, dict) else None
            name = function.get("name") if isinstance(function, dict) else None
            if name and str(name) not in ids:
                ids.append(str(name))
        return ids


class PromptExecutionGate:
    def decide(
        self,
        artifact: PromptArtifact,
        mode: PromptExecutionMode | str,
        approved_digest: str = "",
    ) -> str:
        selected = PromptExecutionMode(str(mode))
        if selected is PromptExecutionMode.PREVIEW:
            return "preview"
        if selected is PromptExecutionMode.APPROVED:
            return (
                "execute"
                if str(approved_digest).strip() == artifact.prompt_sha256
                else "blocked"
            )
        return "execute"