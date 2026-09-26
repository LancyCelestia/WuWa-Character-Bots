"""短期隔离工作区与确认发送服务；HTTP 不接触数据库或生产对象。

sandbox_generator 只接收独立工作区值对象。real_adapter 为装配时注入的受控
上下文/生成/出站端口，deliver 必须重新执行 Policy/Review 并入 SendQueue。
本服务不导入或创建生产记忆、好感、定时任务、模型客户端或平台发送器。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import secrets
import sqlite3
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..domains.ops.audit.logger import redact_private_debug
from ..domains.render.plain_text import redact_local_secrets
from .auth import Principal
from .services import ControlServiceError


class ModelParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, strict=True, ge=1, le=131072)
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"] | None = None


class WorkspaceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    mode: Literal["sandbox", "real_session"] = "sandbox"
    session_id: str | None = Field(default=None, max_length=128, pattern=r"^[A-Za-z0-9_.:@-]+$")
    persona_profile_id: str = Field(default="shorekeeper", min_length=1, max_length=128)
    world_profile_id: str | None = Field(default=None, max_length=128)
    worldbook_ids: tuple[str, ...] = Field(default=(), max_length=20)
    reference_ids: tuple[str, ...] = Field(default=(), max_length=20)
    knowledge_base_ids: tuple[str, ...] = Field(default=(), max_length=20)
    memory_policy: Literal["none", "workspace", "approved_readonly"] = "none"
    provider_id: str = Field(default="", max_length=128)
    channel_id: str | None = Field(default=None, max_length=128)
    model_id: str = Field(default="", max_length=128)
    model_parameters: ModelParameters = Field(default_factory=ModelParameters)
    persist_memory: bool = Field(default=False, strict=True)
    allow_external_tools: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def isolation(self) -> WorkspaceSettings:
        if self.mode == "sandbox" and (self.session_id is not None or self.memory_policy == "approved_readonly"):
            raise ValueError("Sandbox cannot use production session or memory")
        if self.mode == "real_session" and not self.session_id:
            raise ValueError("Real session requires explicit session id")
        if self.allow_external_tools:
            raise ValueError("External tools require a separately registered isolated adapter")
        if self.persist_memory and self.memory_policy != "workspace":
            raise ValueError("Only workspace-scoped memory writes are supported")
        # 选择器是稳定ID，不是路径、URL、凭证或自由文本指令。
        ids = [self.persona_profile_id, self.world_profile_id, self.provider_id,
               self.channel_id, self.model_id, *self.worldbook_ids, *self.reference_ids, *self.knowledge_base_ids]
        if any(value and not re.fullmatch(r"[A-Za-z0-9_.:@/-]{1,128}", value) for value in ids):
            raise ValueError("Invalid resource identifier")
        return self


class RealWorkspaceAdapter(Protocol):
    async def context(self, session_id: str) -> list[dict[str, Any]]: ...
    async def generate(self, scope: dict[str, Any]) -> dict[str, Any]: ...
    async def deliver(self, scope: dict[str, Any]) -> dict[str, Any]: ...


Generator = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def _safe(value: Any) -> Any:
    """只允许JSON内容；复用项目脱敏器，不持久化凭证、文件路径和异常。"""
    if isinstance(value, str):
        return redact_private_debug(redact_local_secrets(value))
    if isinstance(value, list):
        return [_safe(item) for item in value[:200]]
    if isinstance(value, dict):
        return {key: _safe(item) for key, item in value.items()
                if key in {"reply", "prompt", "context", "model_calls", "summary", "role", "content",
                           "model_id", "provider_id", "channel_id", "input_tokens", "output_tokens", "latency_ms", "status"}}
    if value is None or type(value) in (bool, int, float):
        return value
    raise ValueError("Non-JSON artifact")


class WorkspaceService:
    def __init__(self, path: str | Path, *, sandbox_generator: Generator | None = None,
                 real_adapter: RealWorkspaceAdapter | None = None, clock: Callable[[], float] = time.time,
                 ttl_seconds: int = 86400, timeout_seconds: float = 120.0,
                 default_persona_profile_id: str = "shorekeeper") -> None:
        if not str(path).strip() or str(path) == ":memory:":
            raise ValueError("Explicit isolated database path required")
        if not 60 <= ttl_seconds <= 86400 or not 0 < timeout_seconds <= 300:
            raise ValueError("Invalid workspace retention or timeout")
        self.default_persona_profile_id = WorkspaceSettings(persona_profile_id=default_persona_profile_id).persona_profile_id
        self.path = Path(path)
        self.sandbox_generator, self.real_adapter = sandbox_generator, real_adapter
        self.clock, self.ttl_seconds, self.timeout_seconds = clock, ttl_seconds, timeout_seconds
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS cp_workspaces (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, version INTEGER NOT NULL,
                    expires_at REAL NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS cp_workspace_audit (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id TEXT NOT NULL,
                    owner TEXT NOT NULL, request_id TEXT NOT NULL, operation TEXT NOT NULL,
                    version INTEGER NOT NULL, occurred_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS cp_workspace_sends (
                    workspace_id TEXT NOT NULL, idem TEXT NOT NULL, preview_id TEXT NOT NULL,
                    receipt TEXT NOT NULL, request_digest TEXT NOT NULL DEFAULT '', PRIMARY KEY(workspace_id, idem));
            """)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        try:
            conn = sqlite3.connect(self.path, timeout=2)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA secure_delete=ON")
            try:
                conn.execute("BEGIN IMMEDIATE")
                yield conn
                conn.commit()
            finally:
                conn.close()
        except (OSError, sqlite3.Error) as exc:
            raise ControlServiceError("workspace_store_unavailable", "工作区存储不可用。", 503) from exc

    @staticmethod
    def _authorize(principal: Principal) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.:@-]{1,128}", principal.subject):
            raise ControlServiceError("validation_error", "身份标识无效。", 422)
        if "super_admin" not in principal.roles:
            raise ControlServiceError("forbidden", "工作区内容仅允许超管访问。", 403)

    def _load(self, conn: sqlite3.Connection, wid: str, principal: Principal) -> dict[str, Any]:
        self._authorize(principal)
        row = conn.execute("SELECT data FROM cp_workspaces WHERE id=? AND owner=? AND expires_at>?",
                           (wid, principal.subject, self.clock())).fetchone()
        if row is None:
            raise ControlServiceError("workspace_not_found", "工作区不存在或已过期。", 404)
        return json.loads(row["data"])

    @staticmethod
    def _check(data: dict[str, Any], expected_version: int) -> None:
        if type(expected_version) is not int or expected_version < 0:
            raise ControlServiceError("validation_error", "版本无效。", 422)
        if data["version"] != expected_version:
            raise ControlServiceError("version_conflict", "工作区已变化，请刷新后重试。", 409)
        if data["status"] != "idle":
            raise ControlServiceError("workspace_busy", "工作区操作尚未结束。", 409)

    def _audit(self, conn: sqlite3.Connection, data: dict[str, Any], request_id: str, operation: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.:@-]{1,128}", request_id):
            raise ControlServiceError("validation_error", "请求标识无效。", 422)
        conn.execute("INSERT INTO cp_workspace_audit(workspace_id,owner,request_id,operation,version,occurred_at) VALUES (?,?,?,?,?,?)",
                     (data["workspace_id"], data["created_by"], request_id, operation, data["version"], self.clock()))

    def _save(self, conn: sqlite3.Connection, data: dict[str, Any], request_id: str, operation: str) -> None:
        data["version"] += 1
        serialized = json.dumps(data, ensure_ascii=False, allow_nan=False)
        if len(serialized.encode()) > 512000:
            raise ControlServiceError("workspace_limit", "工作区内容超出限制，请重置或创建新工作区。", 413)
        conn.execute("UPDATE cp_workspaces SET version=?,data=? WHERE id=?",
                     (data["version"], serialized, data["workspace_id"]))
        self._audit(conn, data, request_id, operation)

    @staticmethod
    def _public(data: dict[str, Any]) -> dict[str, Any]:
        return {key: data[key] for key in ("workspace_id", "test_session_id", "created_by", "settings", "version", "status", "expires_at")}

    def create(self, settings: WorkspaceSettings, *, principal: Principal, request_id: str) -> dict[str, Any]:
        self._authorize(principal)
        if "persona_profile_id" not in settings.model_fields_set:
            settings = settings.model_copy(update={"persona_profile_id": self.default_persona_profile_id})
        if settings.mode == "real_session" and self.real_adapter is None:
            raise ControlServiceError("real_session_unavailable", "生产会话适配器尚未装配。", 503)
        self.prune()
        with self._connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM cp_workspaces WHERE owner=?", (principal.subject,)).fetchone()[0]
            if count >= 20:
                raise ControlServiceError("workspace_limit", "工作区数量达到上限。", 429)
            data = {"workspace_id": "ws_" + uuid4().hex, "test_session_id": "test_" + uuid4().hex,
                    "created_by": principal.subject, "settings": settings.model_dump(mode="json"),
                    "version": 0, "status": "idle", "expires_at": self.clock() + self.ttl_seconds,
                    "messages": [], "preview": None}
            conn.execute("INSERT INTO cp_workspaces VALUES (?,?,?,?,?)", (data["workspace_id"], principal.subject, 0, data["expires_at"], json.dumps(data)))
            self._audit(conn, data, request_id, "created")
            return self._public(data)

    def get(self, wid: str, *, principal: Principal) -> dict[str, Any]:
        with self._connection() as conn:
            return self._public(self._load(conn, wid, principal))

    def list(self, *, principal: Principal) -> tuple[dict[str, Any], ...]:
        self._authorize(principal)
        with self._connection() as conn:
            return tuple(self._public(json.loads(row[0])) for row in conn.execute(
                "SELECT data FROM cp_workspaces WHERE owner=? AND expires_at>? ORDER BY id LIMIT 20", (principal.subject, self.clock())))

    def messages(self, wid: str, *, principal: Principal) -> tuple[dict[str, Any], ...]:
        with self._connection() as conn:
            return tuple(self._load(conn, wid, principal)["messages"])

    def message(self, wid: str, content: str, *, expected_version: int, principal: Principal, request_id: str) -> dict[str, Any]:
        if type(content) is not str or not content.strip() or len(content) > 16000:
            raise ControlServiceError("validation_error", "消息必须为非空文本，且不超过16000字符。", 422)
        with self._connection() as conn:
            data = self._load(conn, wid, principal)
            self._check(data, expected_version)
            if len(data["messages"]) >= 100 or len(json.dumps(data["messages"]).encode()) + len(content.encode()) * 6 > 192000:
                raise ControlServiceError("workspace_limit", "对话轮次已达上限。", 429)
            data["messages"].append({"role": "user", "content": _safe(content)})
            data["preview"] = None
            self._save(conn, data, request_id, "message_added")
            return self._public(data)

    def reset(self, wid: str, *, expected_version: int, principal: Principal, request_id: str) -> dict[str, Any]:
        with self._connection() as conn:
            data = self._load(conn, wid, principal)
            self._check(data, expected_version)
            data["messages"], data["preview"] = [], None
            self._save(conn, data, request_id, "reset")
            return self._public(data)

    def delete(self, wid: str, *, expected_version: int, principal: Principal, request_id: str) -> dict[str, Any]:
        with self._connection() as conn:
            data = self._load(conn, wid, principal)
            self._check(data, expected_version)
            self._audit(conn, data, request_id, "deleted")
            conn.execute("DELETE FROM cp_workspace_sends WHERE workspace_id=?", (wid,))
            conn.execute("DELETE FROM cp_workspaces WHERE id=?", (wid,))
            return {"workspace_id": wid, "deleted": True}

    def audit(self, wid: str, *, principal: Principal) -> tuple[dict[str, Any], ...]:
        self._authorize(principal)
        with self._connection() as conn:
            return tuple(dict(row) for row in conn.execute("SELECT * FROM cp_workspace_audit WHERE workspace_id=? AND owner=? ORDER BY sequence LIMIT 500", (wid, principal.subject)))

    def prune(self) -> int:
        with self._connection() as conn:
            conn.execute("DELETE FROM cp_workspace_sends WHERE workspace_id IN (SELECT id FROM cp_workspaces WHERE expires_at<=?)", (self.clock(),))
            return conn.execute("DELETE FROM cp_workspaces WHERE expires_at<=?", (self.clock(),)).rowcount

    def _claim(self, wid: str, principal: Principal, version: int, request_id: str) -> dict[str, Any]:
        with self._connection() as conn:
            data = self._load(conn, wid, principal)
            self._check(data, version)
            data["status"], data["preview"] = "generating", None
            self._save(conn, data, request_id, "preview_started")
            return data

    def _finish_preview(self, wid: str, principal: Principal, version: int, request_id: str,
                        artifact: dict[str, Any] | None, token: str) -> dict[str, Any]:
        with self._connection() as conn:
            data = self._load(conn, wid, principal)
            if data["version"] != version:
                raise ControlServiceError("version_conflict", "生成期间工作区已变化。", 409)
            data["status"] = "idle"
            if artifact is not None:
                data["preview"] = {"id": "preview_" + uuid4().hex, "artifact": artifact,
                    "token_hash": hashlib.sha256(token.encode()).hexdigest(), "expires_at": self.clock() + 300}
            self._save(conn, data, request_id, "preview_ready" if artifact is not None else "preview_failed")
            return {**self._public(data), "artifact": artifact, "confirmation_token": token}

    async def preview(self, wid: str, *, expected_version: int, principal: Principal, request_id: str) -> dict[str, Any]:
        metadata = await asyncio.to_thread(self.get, wid, principal=principal)
        real = metadata["settings"]["mode"] == "real_session"
        if (real and self.real_adapter is None) or (not real and self.sandbox_generator is None):
            raise ControlServiceError("workspace_generator_unavailable", "工作区生成适配器尚未装配。", 503)
        data = await asyncio.to_thread(self._claim, wid, principal, expected_version, request_id)
        async def generate() -> dict[str, Any]:
            scope = {"test_session_id": data["test_session_id"], "settings": data["settings"], "messages": data["messages"]}
            if real:
                assert self.real_adapter is not None
                scope["context"] = _safe(await self.real_adapter.context(data["settings"]["session_id"]))
                return await self.real_adapter.generate(scope)
            assert self.sandbox_generator is not None
            return await self.sandbox_generator(scope)
        try:
            raw = await asyncio.wait_for(generate(), timeout=self.timeout_seconds)
            if type(raw) is not dict or type(raw.get("reply")) is not str or len(raw["reply"]) > 32000:
                raise ValueError("Invalid preview artifact")
            artifact = _safe(raw)
            if real:
                artifact.pop("prompt", None)
            if len(json.dumps(artifact, allow_nan=False).encode()) > 128000:
                raise ValueError("Preview exceeds budget")
        except (Exception, asyncio.CancelledError) as exc:
            await asyncio.shield(asyncio.to_thread(self._finish_preview, wid, principal, data["version"], request_id, None, ""))
            if isinstance(exc, asyncio.CancelledError):
                raise
            if isinstance(exc, ControlServiceError):
                raise
            raise ControlServiceError("workspace_generation_failed", "工作区生成失败，未触发真实发送。", 502) from exc
        return await asyncio.to_thread(self._finish_preview, wid, principal, data["version"], request_id, artifact, secrets.token_urlsafe(32))

    def _begin_send(self, wid: str, principal: Principal, expected_version: int, token: str, request_id: str, idem: str) -> tuple[dict[str, Any], bool]:
        if type(idem) is not str or not re.fullmatch(r"[A-Za-z0-9_.:@-]{1,128}", idem):
            raise ControlServiceError("validation_error", "幂等标识无效。", 422)
        if type(token) is not str or len(token) > 128 or type(expected_version) is not int:
            raise ControlServiceError("validation_error", "确认参数无效。", 422)
        digest = hashlib.sha256((str(expected_version) + ":" + token).encode()).hexdigest()
        with self._connection() as conn:
            data = self._load(conn, wid, principal)
            old = conn.execute("SELECT receipt,request_digest FROM cp_workspace_sends WHERE workspace_id=? AND idem=?", (wid, idem)).fetchone()
            if old is not None:
                if not secrets.compare_digest(old["request_digest"], digest):
                    raise ControlServiceError("idempotency_conflict", "幂等标识已用于不同的发送请求。", 409)
                return {**self._public(data), "receipt": json.loads(old[0])}, False
            self._check(data, expected_version)
            preview = data["preview"]
            if not preview or preview["expires_at"] <= self.clock() or type(token) is not str or not secrets.compare_digest(hashlib.sha256(token.encode()).hexdigest(), preview["token_hash"]):
                raise ControlServiceError("confirmation_required", "预览确认无效或已过期。", 409)
            # v21r2 S9：真实发送端口未装配时在**消费确认之前**诚实拒绝——
            # 不烧确认令牌、不插回执（同幂等键重试仍走同一路径），四列如实登记。
            if data["settings"]["mode"] == "real_session" and getattr(self.real_adapter, "deliver", None) is None:
                raise ControlServiceError("not_wired", "真实发送端口尚未装配，本次未发送、确认仍有效。", 503)
            data["status"] = "sending"
            preview["token_hash"] = ""  # 接受后不可再次消费确认。
            receipt = {"state": "pending", "receipt_id": "send_" + uuid4().hex}
            conn.execute("INSERT INTO cp_workspace_sends VALUES (?,?,?,?,?)", (wid, idem, preview["id"], json.dumps(receipt), digest))
            self._save(conn, data, request_id, "send_accepted")
            return {**data, "receipt": receipt}, True

    def _finish_send(self, wid: str, principal: Principal, request_id: str, idem: str, receipt: dict[str, Any]) -> dict[str, Any]:
        with self._connection() as conn:
            data = self._load(conn, wid, principal)
            if receipt["state"] in ("queued", "simulated"):
                data["messages"].append({"role": "assistant", "content": data["preview"]["artifact"]["reply"]})
            data["preview"], data["status"] = None, "idle"
            conn.execute("UPDATE cp_workspace_sends SET receipt=? WHERE workspace_id=? AND idem=?", (json.dumps(receipt), wid, idem))
            self._save(conn, data, request_id, "send_" + receipt["state"])
            return {**self._public(data), "receipt": receipt}

    async def send(self, wid: str, *, expected_version: int, confirmation_token: str, principal: Principal,
                   request_id: str, idempotency_key: str) -> dict[str, Any]:
        data, accepted = await asyncio.to_thread(self._begin_send, wid, principal, expected_version, confirmation_token, request_id, idempotency_key)
        if not accepted:
            return data
        receipt = data["receipt"]
        try:
            if data["settings"]["mode"] == "sandbox":
                receipt["state"] = "simulated"
            else:
                if self.real_adapter is None:
                    raise RuntimeError("Missing delivery adapter")
                raw = await asyncio.wait_for(self.real_adapter.deliver({
                    "session_id": data["settings"]["session_id"], "reply": data["preview"]["artifact"]["reply"],
                    "request_id": request_id, "delivery_id": receipt["receipt_id"], "principal": principal,
                }), timeout=self.timeout_seconds)
                if type(raw) is not dict or raw.get("state") not in ("queued", "rejected"):
                    raise ValueError("Invalid SendQueue receipt")
                receipt["state"] = raw["state"]
        except (Exception, asyncio.CancelledError) as exc:
            receipt["state"] = "unknown"
            await asyncio.shield(asyncio.to_thread(self._finish_send, wid, principal, request_id, idempotency_key, receipt))
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise ControlServiceError("workspace_send_unknown", "发送结果未知，请按回执核查，勿重新发送。", 503) from exc
        return await asyncio.to_thread(self._finish_send, wid, principal, request_id, idempotency_key, receipt)
