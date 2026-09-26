"""白名单动作服务：事务受理、CAS、单次确认、幂等、受控异步执行和脱敏审计。

本模块不导入 shell/进程控制器/任意 SQL 接口。注册只允许启动装配时注入
显式异步 handler；HTTP 参数永远不是代码、路径或 SnowLuma API 名。
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import math
import re
import secrets
import sqlite3
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from plugins.bot_unified_runtime.domains.ops.audit.logger import redact_private_debug
from plugins.bot_unified_runtime.domains.render.plain_text import redact_local_secrets

from .auth import Principal
from .services import ControlServiceError

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}\Z")
Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

# 动作域专用消毒：明细由装配期可信 handler 产出，按值形态放行（布尔/有限
# 数值/标识符形短串/嵌套结构），与事件面 RuntimeLogEvent 的已知键白名单
# （events._safe_details）解耦。凭证形键名整键丢弃；自由文本/URL/路径/异常
# 正文经脱敏复核，未变更且形如标识符才保留；脱敏栈异常视为污染（fail closed）。
_ACTION_KEY_DENY = re.compile(
    r"token|secret|password|passphrase|cookie|authorization|credential|api_?key",
    re.IGNORECASE,
)


def _redact(text: str) -> str:
    # 与 events._redact 同口径：脱敏失败宁可整值丢弃，不落原文。
    try:
        return redact_local_secrets(redact_private_debug(text))
    except (RuntimeError, TypeError, ValueError, LookupError, AttributeError):
        return ""


def _sanitize_action_details(details: Any) -> dict[str, Any]:
    budget = 256

    def clean(value: Any, depth: int = 0) -> Any:
        nonlocal budget
        budget -= 1
        if budget < 0 or depth > 4:
            return None
        if value is None or type(value) is bool:
            return value
        if type(value) in (int, float):
            return value if math.isfinite(value) and 0 <= value <= 10**15 else None
        if type(value) is str:
            safe = _redact(value)
            return safe if safe == value and _IDENTIFIER.fullmatch(safe) else None
        if type(value) is dict:
            result: dict[str, Any] = {}
            for name, raw in sorted(
                (str(key), item) for key, item in value.items()
            )[:32]:
                if _ACTION_KEY_DENY.search(name):
                    continue
                safe = clean(raw, depth + 1)
                if safe is not None:
                    result[name] = safe
            return result or None
        if type(value) in (list, tuple):
            items = [clean(item, depth + 1) for item in list(value)[:32]]
            return [item for item in items if item is not None] or None
        return None

    if type(details) is not dict:
        return {}
    cleaned = clean(details)
    return cleaned if type(cleaned) is dict else {}


@dataclass(frozen=True)
class ControlActionDescriptor:
    id: str
    label: str
    confirmation_required: bool = True
    timeout_seconds: float = 10.0
    cancel_supported: bool = True
    rollback_supported: bool = False

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.id) or not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 300:
            raise ValueError("Invalid action descriptor")
        if self.rollback_supported:
            raise ValueError("Rollback adapter is not implemented")

    def to_dict(self) -> dict[str, Any]:
        return {"action_id": self.id, "label": self.label,
                "required_roles": ["super_admin"], "timeout_seconds": self.timeout_seconds,
                "confirmation_required": self.confirmation_required,
                "cancel_supported": self.cancel_supported, "rollback_supported": False,
                "parameter_schema": {"type": "object", "properties": {}, "additionalProperties": False},
                "audit_fields": ["actor", "request_id", "run_id", "state", "version"],
                "privacy_policy": "structured_summary_only"}


class ControlActionService:
    def __init__(self, path: str | Path, *, registrations: tuple[tuple[ControlActionDescriptor, Handler], ...],
                 feature_allowed: Callable[[str], bool] | None = None, clock: Callable[[], float] = time.time) -> None:
        if not str(path).strip() or str(path) == ":memory:":
            raise ValueError("Explicit action database path required")
        self.path = Path(path)
        self.registrations = registrations
        self._registry = {descriptor.id: (descriptor, handler) for descriptor, handler in registrations}
        if len(self._registry) != len(registrations) or any(not inspect.iscoroutinefunction(handler) for _, handler in registrations):
            raise ValueError("Actions require unique ids and async handlers")
        self.feature_allowed = feature_allowed or (lambda _: True)
        self.clock = clock
        self._tasks: dict[str, asyncio.Task] = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection(write=True) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS cp_action_runs (
                    run_id TEXT PRIMARY KEY, action_id TEXT NOT NULL, actor TEXT NOT NULL,
                    request_id TEXT NOT NULL, idem TEXT NOT NULL, digest TEXT NOT NULL,
                    version INTEGER NOT NULL, state TEXT NOT NULL, result_json TEXT,
                    error_code TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    UNIQUE(actor, idem));
                CREATE INDEX IF NOT EXISTS cp_action_version ON cp_action_runs(action_id, version);
                CREATE TABLE IF NOT EXISTS cp_action_confirmations (
                    token_hash TEXT PRIMARY KEY, actor TEXT NOT NULL, action_id TEXT NOT NULL,
                    version INTEGER NOT NULL, digest TEXT NOT NULL, expires_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS cp_action_audit (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                    actor TEXT NOT NULL, request_id TEXT NOT NULL, state TEXT NOT NULL,
                    version INTEGER NOT NULL, occurred_at REAL NOT NULL);
            """)

    @contextmanager
    def _connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        try:
            conn = sqlite3.connect(self.path, timeout=2.0)
            conn.row_factory = sqlite3.Row
            try:
                if write:
                    conn.execute("BEGIN IMMEDIATE")
                yield conn
                if write:
                    conn.commit()
            finally:
                conn.close()
        except (sqlite3.Error, OSError) as exc:
            raise ControlServiceError("action_store_unavailable", "动作审计存储不可用，不能执行操作。", 503) from exc

    def _descriptor(self, action_id: str) -> ControlActionDescriptor:
        if action_id not in self._registry:
            raise ControlServiceError("action_not_found", "动作未登记。", 404)
        return self._registry[action_id][0]

    @staticmethod
    def _version(conn: sqlite3.Connection, action_id: str) -> int:
        return conn.execute("SELECT COALESCE(MAX(version), 0) FROM cp_action_runs WHERE action_id=?", (action_id,)).fetchone()[0]

    def detail(self, action_id: str) -> dict[str, Any]:
        descriptor = self._descriptor(action_id)
        with self._connection() as conn:
            return {**descriptor.to_dict(), "version": self._version(conn, action_id), "available": True}

    def catalog(self) -> tuple[dict[str, Any], ...]:
        return tuple(self.detail(key) for key in sorted(self._registry))

    def registry_pairs(self) -> tuple[tuple[str, str], ...]:
        """只读注册表投影 ``(action_id, label)``（零 DB 访问）。

        供 WebUI 插件目录映射条目 ``config_actions``：目录面只需要 id+名，
        不需要每动作的版本号/角色/超时（那是 ``catalog()`` 的 DB 职责）。
        """
        return tuple(sorted((key, self._registry[key][0].label) for key in self._registry))

    def _validate(self, action_id: str, parameters: Any, expected_version: int, principal: Principal) -> str:
        if "super_admin" not in principal.roles:
            raise ControlServiceError("forbidden", "仅超管可以执行控制动作。", 403)
        self._descriptor(action_id)
        if type(expected_version) is not int or expected_version < 0 or type(parameters) is not dict or parameters:
            raise ControlServiceError("validation_error", "参数或版本无效；该动作不接受额外参数。", 422)
        if not _IDENTIFIER.fullmatch(principal.subject):
            raise ControlServiceError("validation_error", "操作人标识无效。", 422)
        if not self.feature_allowed(action_id):
            raise ControlServiceError("feature_disabled", "控制动作已停用。", 409)
        return hashlib.sha256((action_id + ":{}").encode()).hexdigest()

    def preview(self, action_id: str, *, parameters: dict[str, Any], expected_version: int, principal: Principal) -> dict[str, Any]:
        digest = self._validate(action_id, parameters, expected_version, principal)
        token = secrets.token_urlsafe(32)
        with self._connection(write=True) as conn:
            if self._version(conn, action_id) != expected_version:
                raise ControlServiceError("version_conflict", "动作版本已变化，请重新预览。", 409)
            now = self.clock()
            conn.execute("DELETE FROM cp_action_confirmations WHERE expires_at<=?", (now,))
            # 一个身份/动作只保留最新确认，避免预览刷库无限增长。
            conn.execute("DELETE FROM cp_action_confirmations WHERE actor=? AND action_id=?", (principal.subject, action_id))
            conn.execute("INSERT INTO cp_action_confirmations VALUES (?,?,?,?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), principal.subject, action_id, expected_version, digest, now + 300))
        return {"action_id": action_id, "expected_version": expected_version, "confirmation_token": token, "expires_in_seconds": 300, "preview_only": True}

    @staticmethod
    def _public(row: sqlite3.Row) -> dict[str, Any]:
        data = {key: row[key] for key in ("run_id", "action_id", "actor", "request_id", "version", "state", "error_code", "created_at", "updated_at")}
        data["result"] = json.loads(row["result_json"]) if row["result_json"] is not None else None
        return data

    def runs(self, *, limit: int = 50) -> tuple[dict[str, Any], ...]:
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ControlServiceError("validation_error", "分页数量无效。", 422)
        with self._connection() as conn:
            return tuple(self._public(row) for row in conn.execute("SELECT * FROM cp_action_runs ORDER BY created_at DESC, run_id DESC LIMIT ?", (limit,)))

    def run(self, run_id: str) -> dict[str, Any]:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM cp_action_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise ControlServiceError("action_run_not_found", "执行记录不存在。", 404)
            return self._public(row)

    def audit(self, run_id: str) -> tuple[dict[str, Any], ...]:
        with self._connection() as conn:
            return tuple(dict(row) for row in conn.execute("SELECT * FROM cp_action_audit WHERE run_id=? ORDER BY sequence", (run_id,)))

    def _audit(self, conn: sqlite3.Connection, run_id: str, state: str) -> None:
        conn.execute("""INSERT INTO cp_action_audit(run_id,actor,request_id,state,version,occurred_at)
            SELECT run_id,actor,request_id,?,version,? FROM cp_action_runs WHERE run_id=?""", (state, self.clock(), run_id))

    def _begin(self, action_id: str, parameters: dict[str, Any], expected_version: int, principal: Principal,
               request_id: str, idempotency_key: str, confirmation_token: str | None) -> tuple[dict[str, Any], bool]:
        digest = self._validate(action_id, parameters, expected_version, principal)
        if not all(type(value) is str and _IDENTIFIER.fullmatch(value) for value in (request_id, idempotency_key)):
            raise ControlServiceError("validation_error", "请求或幂等标识无效。", 422)
        with self._connection(write=True) as conn:
            old = conn.execute("SELECT * FROM cp_action_runs WHERE actor=? AND idem=?", (principal.subject, idempotency_key)).fetchone()
            if old is not None:
                if old["digest"] != digest:
                    raise ControlServiceError("idempotency_conflict", "幂等标识已用于其他操作。", 409)
                return self._public(old), False
            if conn.execute("SELECT COUNT(*) FROM cp_action_runs WHERE state IN ('running','unknown')").fetchone()[0] >= 16:
                raise ControlServiceError("action_capacity", "动作并发已达上限。", 429)
            if self._version(conn, action_id) != expected_version:
                raise ControlServiceError("version_conflict", "动作版本已变化，请重新预览。", 409)
            if conn.execute("SELECT 1 FROM cp_action_runs WHERE action_id=? AND state IN ('running','unknown') LIMIT 1", (action_id,)).fetchone():
                raise ControlServiceError("action_busy", "动作仍在执行或结果未知，禁止重复执行。", 409)
            if self._descriptor(action_id).confirmation_required:
                if type(confirmation_token) is not str or len(confirmation_token) > 128:
                    raise ControlServiceError("confirmation_required", "需要有效的预览确认。", 409)
                deleted = conn.execute("DELETE FROM cp_action_confirmations WHERE token_hash=? AND actor=? AND action_id=? AND version=? AND digest=? AND expires_at>?", (hashlib.sha256(confirmation_token.encode()).hexdigest(), principal.subject, action_id, expected_version, digest, self.clock()))
                if deleted.rowcount != 1:
                    raise ControlServiceError("confirmation_required", "确认已过期或不匹配，请重新预览。", 409)
            run_id = "run_" + uuid4().hex
            now = self.clock()
            conn.execute("INSERT INTO cp_action_runs VALUES (?,?,?,?,?,?,?,'running',NULL,NULL,?,?)", (run_id, action_id, principal.subject, request_id, idempotency_key, digest, expected_version + 1, now, now))
            self._audit(conn, run_id, "running")
            row = conn.execute("SELECT * FROM cp_action_runs WHERE run_id=?", (run_id,)).fetchone()
            return self._public(row), True

    def _finish(self, run_id: str, state: str, result: dict[str, Any] | None, error_code: str | None) -> dict[str, Any]:
        with self._connection(write=True) as conn:
            conn.execute("UPDATE cp_action_runs SET state=?,result_json=?,error_code=?,updated_at=? WHERE run_id=?", (state, json.dumps(result) if result is not None else None, error_code, self.clock(), run_id))
            self._audit(conn, run_id, state)
            row = conn.execute("SELECT * FROM cp_action_runs WHERE run_id=?", (run_id,)).fetchone()
            return self._public(row)

    async def execute(self, action_id: str, *, parameters: dict[str, Any], expected_version: int, principal: Principal,
                      request_id: str, idempotency_key: str, confirmation_token: str | None = None) -> dict[str, Any]:
        row, accepted = await asyncio.to_thread(self._begin, action_id, parameters, expected_version, principal, request_id, idempotency_key, confirmation_token)
        if not accepted:
            return row
        descriptor, handler = self._registry[action_id]
        run_id = row["run_id"]
        async def invoke() -> dict[str, Any]:
            return await handler(dict(parameters))
        task: asyncio.Task[dict[str, Any]] = asyncio.create_task(invoke(), name="action-" + run_id)
        self._tasks[run_id] = task
        result = None
        error_code = None
        try:
            _, pending = await asyncio.wait({task}, timeout=descriptor.timeout_seconds)
            if pending:
                task.cancel()
                _, pending = await asyncio.wait({task}, timeout=0.1)
                state = "unknown" if pending else "timed_out"
                error_code = "action_outcome_unknown" if pending else "action_timeout"
            elif task.cancelled():
                state, error_code = "cancelled", "action_cancelled"
            else:
                raw = task.result()
                if type(raw) is not dict or raw.get("status") not in ("ok", "degraded"):
                    raise ValueError("Invalid action output")
                # 动作域专用消毒：结构化明细可达客户端，凭证形键名与任意
                # URL/路径/凭证/异常正文仍永不持久化。
                result = {"status": raw["status"], "details": _sanitize_action_details(raw.get("details", {}))}
                state = "succeeded"
        except asyncio.CancelledError:
            task.cancel()
            await asyncio.shield(asyncio.to_thread(self._finish, run_id, "unknown", None, "action_interrupted"))
            raise
        except Exception:  # noqa: BLE001 - 不回显动作异常；保留明确失败和审计。
            state, error_code = "failed", "action_failed"
        finally:
            if task.done():
                if not task.cancelled():
                    task.exception()  # 收回已结束任务异常，避免裸 task 警告。
                self._tasks.pop(run_id, None)
            else:
                task.add_done_callback(lambda finished: self._release(run_id, finished))
        return await asyncio.to_thread(self._finish, run_id, state, result, error_code)

    def _release(self, run_id: str, task: asyncio.Task) -> None:
        if not task.cancelled():
            task.exception()
        self._tasks.pop(run_id, None)

    async def cancel(self, run_id: str, *, expected_version: int, principal: Principal) -> dict[str, Any]:
        if "super_admin" not in principal.roles:
            raise ControlServiceError("forbidden", "仅超管可以取消动作。", 403)
        row = await asyncio.to_thread(self.run, run_id)
        if type(expected_version) is not int or expected_version != row["version"]:
            raise ControlServiceError("version_conflict", "执行版本已变化。", 409)
        task = self._tasks.get(run_id)
        if row["state"] != "running" or task is None or task.done() or not self._descriptor(row["action_id"]).cancel_supported:
            raise ControlServiceError("action_not_cancellable", "动作不可取消或不由当前执行器持有。", 409)
        # 只请求协作取消，不强杀线程/进程；最终结果由 execute 记录。
        task.cancel()
        return {"run_id": run_id, "cancel_requested": True}
