from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
from typing import Iterable
from typing import Protocol

from pydantic import Field

from plugins.bot_unified_runtime.config_readiness import run_config_smoke
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import (
    AuditRecord,
    CapabilityResult,
    DeliveryReceipt,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.contracts.runtime import StrictBaseModel
from plugins.bot_unified_runtime.policy import (
    PolicySettings,
    build_reply_budget_settings,
    build_role_settings,
    decide_reply_budget,
    evaluate_policy,
)


class RuntimeDiagnostic(StrictBaseModel):
    request_id: str
    debug_id: str
    session_id: str
    capability_id: str
    session_type: str
    policy_allowed: bool
    policy_reason: str
    actor_roles: list[str] = Field(default_factory=list)
    risk_level: str
    privacy_level: str
    reply_budget_reason: str = ""
    max_messages: int = 0
    context_budget: int = 0
    prompt_messages: int = 0
    system_prompt_chars: int = 0
    user_prompt_chars: int = 0
    prompt_total_chars: int = 0
    prompt_budget_remaining: int = 0
    prompt_clipped: bool = False
    prompt_truncated_sections: list[str] = Field(default_factory=list)
    knowledge_chunks: int = 0
    memory_facts: int = 0
    history_turns: int = 0
    emotion_signals: int = 0
    llm_status: str = "not_run"
    llm_error_kind: str = ""
    llm_provider: str = ""
    llm_model: str = ""
    ready_for_real_llm: bool = False
    llm_readiness_status: str = ""
    llm_readiness_reasons: list[str] = Field(default_factory=list)
    llm_usage_prompt_tokens: int = 0
    llm_usage_completion_tokens: int = 0
    llm_usage_total_tokens: int = 0
    send_request_created: bool = False
    receipt_state: str
    receipt_message: str
    audit_events: list[str] = Field(default_factory=list)
    audit_tags: list[str] = Field(default_factory=list)
    why_summary: str


class DiagnosticsStore(Protocol):
    def record(self, diagnostic: RuntimeDiagnostic) -> RuntimeDiagnostic:
        raise NotImplementedError

    def latest(self, *, session_id: str | None = None) -> RuntimeDiagnostic | None:
        raise NotImplementedError

    def find(self, token: str) -> RuntimeDiagnostic | None:
        raise NotImplementedError

    def list_recent(self, limit: int = 5) -> list[RuntimeDiagnostic]:
        raise NotImplementedError


class RecentDiagnosticsStore:
    def __init__(self, max_items: int = 100) -> None:
        self._items: deque[RuntimeDiagnostic] = deque(maxlen=max_items)

    def record(self, diagnostic: RuntimeDiagnostic) -> RuntimeDiagnostic:
        self._items.append(diagnostic)
        return diagnostic

    def latest(self, *, session_id: str | None = None) -> RuntimeDiagnostic | None:
        for item in reversed(self._items):
            if session_id is None or item.session_id == session_id:
                return item
        return None

    def find(self, token: str) -> RuntimeDiagnostic | None:
        normalized = token.strip()
        if not normalized:
            return None
        for item in reversed(self._items):
            if item.request_id == normalized or item.debug_id == normalized:
                return item
        return None

    def list_recent(self, limit: int = 5) -> list[RuntimeDiagnostic]:
        safe_limit = _safe_recent_limit(limit)
        return list(reversed(self._items))[:safe_limit]


class SQLiteDiagnosticsRepository:
    def __init__(self, db_path: str | Path, max_items: int = 100) -> None:
        self.db_path = Path(db_path)
        self.max_items = max(1, int(max_items))

    def record(self, diagnostic: RuntimeDiagnostic) -> RuntimeDiagnostic:
        self._ensure_schema()
        created_at = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runtime_diagnostics (
                    request_id,
                    debug_id,
                    session_id,
                    capability_id,
                    session_type,
                    policy_allowed,
                    policy_reason,
                    actor_roles,
                    risk_level,
                    privacy_level,
                    reply_budget_reason,
                    max_messages,
                    context_budget,
                    prompt_messages,
                    system_prompt_chars,
                    user_prompt_chars,
                    prompt_total_chars,
                    prompt_budget_remaining,
                    prompt_clipped,
                    prompt_truncated_sections,
                    knowledge_chunks,
                    memory_facts,
                    history_turns,
                    emotion_signals,
                    llm_status,
                    llm_error_kind,
                    llm_provider,
                    llm_model,
                    ready_for_real_llm,
                    llm_readiness_status,
                    llm_readiness_reasons,
                    llm_usage_prompt_tokens,
                    llm_usage_completion_tokens,
                    llm_usage_total_tokens,
                    send_request_created,
                    receipt_state,
                    receipt_message,
                    audit_events,
                    audit_tags,
                    why_summary,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(request_id) DO UPDATE SET
                    debug_id=excluded.debug_id,
                    session_id=excluded.session_id,
                    capability_id=excluded.capability_id,
                    session_type=excluded.session_type,
                    policy_allowed=excluded.policy_allowed,
                    policy_reason=excluded.policy_reason,
                    actor_roles=excluded.actor_roles,
                    risk_level=excluded.risk_level,
                    privacy_level=excluded.privacy_level,
                    reply_budget_reason=excluded.reply_budget_reason,
                    max_messages=excluded.max_messages,
                    context_budget=excluded.context_budget,
                    prompt_messages=excluded.prompt_messages,
                    system_prompt_chars=excluded.system_prompt_chars,
                    user_prompt_chars=excluded.user_prompt_chars,
                    prompt_total_chars=excluded.prompt_total_chars,
                    prompt_budget_remaining=excluded.prompt_budget_remaining,
                    prompt_clipped=excluded.prompt_clipped,
                    prompt_truncated_sections=excluded.prompt_truncated_sections,
                    knowledge_chunks=excluded.knowledge_chunks,
                    memory_facts=excluded.memory_facts,
                    history_turns=excluded.history_turns,
                    emotion_signals=excluded.emotion_signals,
                    llm_status=excluded.llm_status,
                    llm_error_kind=excluded.llm_error_kind,
                    llm_provider=excluded.llm_provider,
                    llm_model=excluded.llm_model,
                    ready_for_real_llm=excluded.ready_for_real_llm,
                    llm_readiness_status=excluded.llm_readiness_status,
                    llm_readiness_reasons=excluded.llm_readiness_reasons,
                    llm_usage_prompt_tokens=excluded.llm_usage_prompt_tokens,
                    llm_usage_completion_tokens=excluded.llm_usage_completion_tokens,
                    llm_usage_total_tokens=excluded.llm_usage_total_tokens,
                    send_request_created=excluded.send_request_created,
                    receipt_state=excluded.receipt_state,
                    receipt_message=excluded.receipt_message,
                    audit_events=excluded.audit_events,
                    audit_tags=excluded.audit_tags,
                    why_summary=excluded.why_summary,
                    created_at=excluded.created_at
                """,
                self._to_row_values(diagnostic, created_at),
            )
            self._prune(connection)
        return diagnostic

    def latest(self, *, session_id: str | None = None) -> RuntimeDiagnostic | None:
        self._ensure_schema()
        with self._connect() as connection:
            if session_id is None:
                cursor = connection.execute(
                    """
                    SELECT *
                    FROM runtime_diagnostics
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT 1
                    """
                )
            else:
                cursor = connection.execute(
                    """
                    SELECT *
                    FROM runtime_diagnostics
                    WHERE session_id = ?
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT 1
                    """,
                    (session_id,),
                )
            row = cursor.fetchone()
        return self._from_row(row) if row is not None else None

    def find(self, token: str) -> RuntimeDiagnostic | None:
        normalized = token.strip()
        if not normalized:
            return None
        self._ensure_schema()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT *
                FROM runtime_diagnostics
                WHERE request_id = ? OR debug_id = ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT 1
                """,
                (normalized, normalized),
            )
            row = cursor.fetchone()
        return self._from_row(row) if row is not None else None

    def list_recent(self, limit: int = 5) -> list[RuntimeDiagnostic]:
        safe_limit = _safe_recent_limit(limit)
        self._ensure_schema()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT *
                FROM runtime_diagnostics
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (safe_limit,),
            )
            return [self._from_row(row) for row in cursor.fetchall()]

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_diagnostics (
                    request_id TEXT PRIMARY KEY,
                    debug_id TEXT NOT NULL UNIQUE,
                    session_id TEXT NOT NULL,
                    capability_id TEXT NOT NULL,
                    session_type TEXT NOT NULL,
                    policy_allowed INTEGER NOT NULL,
                    policy_reason TEXT NOT NULL,
                    actor_roles TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    privacy_level TEXT NOT NULL,
                    reply_budget_reason TEXT NOT NULL,
                    max_messages INTEGER NOT NULL,
                    context_budget INTEGER NOT NULL,
                    prompt_messages INTEGER NOT NULL DEFAULT 0,
                    system_prompt_chars INTEGER NOT NULL DEFAULT 0,
                    user_prompt_chars INTEGER NOT NULL DEFAULT 0,
                    prompt_total_chars INTEGER NOT NULL DEFAULT 0,
                    prompt_budget_remaining INTEGER NOT NULL DEFAULT 0,
                    prompt_clipped INTEGER NOT NULL DEFAULT 0,
                    prompt_truncated_sections TEXT NOT NULL DEFAULT '[]',
                    knowledge_chunks INTEGER NOT NULL DEFAULT 0,
                    memory_facts INTEGER NOT NULL DEFAULT 0,
                    history_turns INTEGER NOT NULL DEFAULT 0,
                    emotion_signals INTEGER NOT NULL DEFAULT 0,
                    llm_status TEXT NOT NULL,
                    llm_error_kind TEXT NOT NULL DEFAULT '',
                    llm_provider TEXT NOT NULL,
                    llm_model TEXT NOT NULL,
                    ready_for_real_llm INTEGER NOT NULL DEFAULT 0,
                    llm_readiness_status TEXT NOT NULL DEFAULT '',
                    llm_readiness_reasons TEXT NOT NULL DEFAULT '[]',
                    llm_usage_prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    llm_usage_completion_tokens INTEGER NOT NULL DEFAULT 0,
                    llm_usage_total_tokens INTEGER NOT NULL DEFAULT 0,
                    send_request_created INTEGER NOT NULL,
                    receipt_state TEXT NOT NULL,
                    receipt_message TEXT NOT NULL,
                    audit_events TEXT NOT NULL,
                    audit_tags TEXT NOT NULL,
                    why_summary TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._ensure_column(
                connection,
                "runtime_diagnostics",
                "llm_error_kind",
                "TEXT NOT NULL DEFAULT ''",
            )
            for column, definition in {
                "prompt_messages": "INTEGER NOT NULL DEFAULT 0",
                "system_prompt_chars": "INTEGER NOT NULL DEFAULT 0",
                "user_prompt_chars": "INTEGER NOT NULL DEFAULT 0",
                "prompt_total_chars": "INTEGER NOT NULL DEFAULT 0",
                "prompt_budget_remaining": "INTEGER NOT NULL DEFAULT 0",
                "prompt_clipped": "INTEGER NOT NULL DEFAULT 0",
                "prompt_truncated_sections": "TEXT NOT NULL DEFAULT '[]'",
                "knowledge_chunks": "INTEGER NOT NULL DEFAULT 0",
                "memory_facts": "INTEGER NOT NULL DEFAULT 0",
                "history_turns": "INTEGER NOT NULL DEFAULT 0",
                "emotion_signals": "INTEGER NOT NULL DEFAULT 0",
                "llm_usage_prompt_tokens": "INTEGER NOT NULL DEFAULT 0",
                "llm_usage_completion_tokens": "INTEGER NOT NULL DEFAULT 0",
                "llm_usage_total_tokens": "INTEGER NOT NULL DEFAULT 0",
                "ready_for_real_llm": "INTEGER NOT NULL DEFAULT 0",
                "llm_readiness_status": "TEXT NOT NULL DEFAULT ''",
                "llm_readiness_reasons": "TEXT NOT NULL DEFAULT '[]'",
            }.items():
                self._ensure_column(connection, "runtime_diagnostics", column, definition)
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_runtime_diagnostics_session_time
                ON runtime_diagnostics (session_id, created_at)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _prune(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            DELETE FROM runtime_diagnostics
            WHERE request_id NOT IN (
                SELECT request_id
                FROM runtime_diagnostics
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
            )
            """,
            (self.max_items,),
        )

    def _to_row_values(
        self,
        diagnostic: RuntimeDiagnostic,
        created_at: str,
    ) -> tuple[object, ...]:
        return (
            diagnostic.request_id,
            diagnostic.debug_id,
            diagnostic.session_id,
            diagnostic.capability_id,
            diagnostic.session_type,
            int(diagnostic.policy_allowed),
            diagnostic.policy_reason,
            _dump_list(diagnostic.actor_roles),
            diagnostic.risk_level,
            diagnostic.privacy_level,
            diagnostic.reply_budget_reason,
            diagnostic.max_messages,
            diagnostic.context_budget,
            diagnostic.prompt_messages,
            diagnostic.system_prompt_chars,
            diagnostic.user_prompt_chars,
            diagnostic.prompt_total_chars,
            diagnostic.prompt_budget_remaining,
            int(diagnostic.prompt_clipped),
            _dump_list(diagnostic.prompt_truncated_sections),
            diagnostic.knowledge_chunks,
            diagnostic.memory_facts,
            diagnostic.history_turns,
            diagnostic.emotion_signals,
            diagnostic.llm_status,
            diagnostic.llm_error_kind,
            diagnostic.llm_provider,
            diagnostic.llm_model,
            int(diagnostic.ready_for_real_llm),
            diagnostic.llm_readiness_status,
            _dump_list(diagnostic.llm_readiness_reasons),
            diagnostic.llm_usage_prompt_tokens,
            diagnostic.llm_usage_completion_tokens,
            diagnostic.llm_usage_total_tokens,
            int(diagnostic.send_request_created),
            diagnostic.receipt_state,
            diagnostic.receipt_message,
            _dump_list(diagnostic.audit_events),
            _dump_list(diagnostic.audit_tags),
            diagnostic.why_summary,
            created_at,
        )

    def _from_row(self, row: sqlite3.Row) -> RuntimeDiagnostic:
        return RuntimeDiagnostic(
            request_id=str(row["request_id"]),
            debug_id=str(row["debug_id"]),
            session_id=str(row["session_id"]),
            capability_id=str(row["capability_id"]),
            session_type=str(row["session_type"]),
            policy_allowed=bool(row["policy_allowed"]),
            policy_reason=str(row["policy_reason"]),
            actor_roles=_load_list(str(row["actor_roles"])),
            risk_level=str(row["risk_level"]),
            privacy_level=str(row["privacy_level"]),
            reply_budget_reason=str(row["reply_budget_reason"]),
            max_messages=int(row["max_messages"]),
            context_budget=int(row["context_budget"]),
            prompt_messages=_row_int(row, "prompt_messages"),
            system_prompt_chars=_row_int(row, "system_prompt_chars"),
            user_prompt_chars=_row_int(row, "user_prompt_chars"),
            prompt_total_chars=_row_int(row, "prompt_total_chars"),
            prompt_budget_remaining=_row_int(row, "prompt_budget_remaining"),
            prompt_clipped=bool(_row_int(row, "prompt_clipped")),
            prompt_truncated_sections=_row_list(row, "prompt_truncated_sections"),
            knowledge_chunks=_row_int(row, "knowledge_chunks"),
            memory_facts=_row_int(row, "memory_facts"),
            history_turns=_row_int(row, "history_turns"),
            emotion_signals=_row_int(row, "emotion_signals"),
            llm_status=str(row["llm_status"]),
            llm_error_kind=str(row["llm_error_kind"])
            if "llm_error_kind" in row.keys()
            else "",
            llm_provider=str(row["llm_provider"]),
            llm_model=str(row["llm_model"]),
            ready_for_real_llm=bool(_row_int(row, "ready_for_real_llm")),
            llm_readiness_status=_row_text(row, "llm_readiness_status"),
            llm_readiness_reasons=_row_list(row, "llm_readiness_reasons"),
            llm_usage_prompt_tokens=_row_int(row, "llm_usage_prompt_tokens"),
            llm_usage_completion_tokens=_row_int(row, "llm_usage_completion_tokens"),
            llm_usage_total_tokens=_row_int(row, "llm_usage_total_tokens"),
            send_request_created=bool(row["send_request_created"]),
            receipt_state=str(row["receipt_state"]),
            receipt_message=str(row["receipt_message"]),
            audit_events=_load_list(str(row["audit_events"])),
            audit_tags=_load_list(str(row["audit_tags"])),
            why_summary=str(row["why_summary"]),
        )

    def _ensure_column(
        self,
        connection: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        cursor = connection.execute(f"PRAGMA table_info({table})")
        existing_columns = {str(row["name"]) for row in cursor.fetchall()}
        if column not in existing_columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def build_diagnostics_store(config: Config) -> DiagnosticsStore:
    enabled = bool(getattr(config, "bot_diagnostics_enabled", False))
    db_path = str(getattr(config, "bot_diagnostics_db_path", "")).strip()
    max_items = int(getattr(config, "bot_diagnostics_max_items", 100))
    if enabled and db_path:
        return SQLiteDiagnosticsRepository(db_path, max_items=max_items)
    return RecentDiagnosticsStore(max_items=max_items)


def build_runtime_diagnostic(
    config: Config,
    *,
    message: IncomingMessage,
    capability_id: str,
    receipt: DeliveryReceipt,
    send_request: SendRequest | None,
    audit_records: Iterable[AuditRecord],
) -> RuntimeDiagnostic:
    llm_readiness = run_config_smoke(config)
    audit_record_list = list(audit_records)
    role_settings = build_role_settings(config)
    message_with_roles = message.model_copy(
        update={"sender_roles": role_settings.resolve_roles(message)}
    )
    policy = evaluate_policy(
        message_with_roles,
        capability_id,
        settings=PolicySettings(
            group_command_prefix=config.bot_runtime_group_command_prefix
        ),
    )
    rate_limit_blocked = infer_rate_limit_blocked(audit_record_list)
    quiet_hours_blocked = infer_quiet_hours_blocked(audit_record_list)
    runtime_paused = infer_runtime_paused(audit_record_list)
    rate_limit_reason = infer_rate_limit_reason(audit_record_list)
    base_policy_allowed = policy.allowed and config.bot_runtime_enabled
    policy_allowed = (
        base_policy_allowed
        and not runtime_paused
        and not rate_limit_blocked
        and not quiet_hours_blocked
    )
    if not config.bot_runtime_enabled:
        policy_reason = "runtime_disabled"
    elif runtime_paused:
        policy_reason = "runtime_paused"
    elif rate_limit_blocked:
        policy_reason = "rate_limited"
    elif quiet_hours_blocked:
        policy_reason = "quiet_hours"
    else:
        policy_reason = policy.reason
    reply_budget = (
        decide_reply_budget(
            message_with_roles,
            capability_id,
            settings=build_reply_budget_settings(config),
        )
        if base_policy_allowed
        else None
    )
    audit_events = [record.event for record in audit_record_list]
    audit_tags = build_diagnostic_audit_tags(
        policy_audit_tags=policy.audit_tags,
        send_request=send_request,
        audit_records=audit_record_list,
    )
    llm_status = "not_run"
    if send_request:
        llm_status = "not_configured" if config.bot_chat_provider == "static" else "ok"
        if infer_context_error_kind(audit_tags):
            llm_status = "not_run"
        if "llm_error" in send_request.audit_tags:
            llm_status = "error"

    llm_error_kind = infer_llm_error_kind(audit_tags)
    context_error_kind = infer_context_error_kind(audit_tags)
    prompt_truncated_sections = infer_prompt_truncated_sections(audit_tags)
    review_block_reason = infer_review_block_reason(audit_record_list)
    history_skip_reason = infer_history_skip_reason(audit_record_list)
    prompt_user_clipped = infer_bool_tag(audit_tags, "prompt_user_clipped")
    llm_preflight_reasons = infer_llm_preflight_reasons(audit_tags)
    max_messages = reply_budget.max_messages if reply_budget else 0
    context_budget = reply_budget.context_budget if reply_budget else 0
    reply_budget_reason = reply_budget.reason if reply_budget else ""
    why_summary = build_diagnostic_why_summary(
        runtime_enabled=config.bot_runtime_enabled,
        policy_allowed=policy_allowed,
        policy_reason=policy_reason,
        session_type=message.session_type,
        mentions_bot=message.mentions_bot,
        group_command_prefix=config.bot_runtime_group_command_prefix,
        max_messages=max_messages,
        reply_budget_reason=reply_budget_reason,
        send_request_created=send_request is not None,
        receipt_state=receipt.state.value,
        review_block_reason=review_block_reason,
        output_trimmed="llm_output_trimmed" in audit_tags,
        llm_error_kind=llm_error_kind,
        context_error_kind=context_error_kind,
        llm_preflight_reasons=llm_preflight_reasons,
        rate_limit_reason=rate_limit_reason,
        prompt_user_clipped=prompt_user_clipped,
        history_skip_reason=history_skip_reason,
    )

    return RuntimeDiagnostic(
        request_id=message.request_id,
        debug_id=receipt.debug_id,
        session_id=message.session_id,
        capability_id=send_request.capability_id if send_request else capability_id,
        session_type=message.session_type.value,
        policy_allowed=policy_allowed,
        policy_reason=policy_reason,
        actor_roles=policy.actor_roles,
        risk_level=policy.risk_level.value,
        privacy_level=policy.privacy_level.value,
        reply_budget_reason=reply_budget_reason,
        max_messages=max_messages,
        context_budget=context_budget,
        prompt_messages=infer_int_tag(audit_tags, "prompt_messages"),
        system_prompt_chars=infer_int_tag(audit_tags, "prompt_system_chars"),
        user_prompt_chars=infer_int_tag(audit_tags, "prompt_user_chars"),
        prompt_total_chars=infer_int_tag(audit_tags, "prompt_total_chars"),
        prompt_budget_remaining=infer_int_tag(audit_tags, "prompt_budget_remaining"),
        prompt_clipped=infer_bool_tag(audit_tags, "prompt_clipped"),
        prompt_truncated_sections=prompt_truncated_sections,
        knowledge_chunks=infer_int_tag(audit_tags, "context_knowledge_chunks"),
        memory_facts=infer_int_tag(audit_tags, "context_memory_facts"),
        history_turns=infer_int_tag(audit_tags, "context_history_turns"),
        emotion_signals=infer_int_tag(audit_tags, "context_emotion_signals"),
        llm_status=llm_status,
        llm_error_kind=llm_error_kind,
        llm_provider=config.bot_chat_provider,
        llm_model=config.bot_chat_model,
        ready_for_real_llm=bool(llm_readiness["ready_for_real_llm"]),
        llm_readiness_status=str(llm_readiness["llm_readiness_status"]),
        llm_readiness_reasons=[
            str(reason) for reason in llm_readiness["llm_readiness_reasons"]
        ],
        llm_usage_prompt_tokens=infer_int_tag(audit_tags, "llm_usage_prompt_tokens"),
        llm_usage_completion_tokens=infer_int_tag(
            audit_tags,
            "llm_usage_completion_tokens",
        ),
        llm_usage_total_tokens=infer_int_tag(audit_tags, "llm_usage_total_tokens"),
        send_request_created=send_request is not None,
        receipt_state=receipt.state.value,
        receipt_message=receipt.public_message,
        audit_events=audit_events,
        audit_tags=audit_tags,
        why_summary=why_summary,
    )


def build_why_result(
    store: DiagnosticsStore,
    *,
    request_id: str,
    session_id: str,
    query: str = "",
) -> CapabilityResult:
    token = query.strip()
    diagnostic = store.find(token) if token else store.latest(session_id=session_id)
    if diagnostic is None:
        body = (
            "还没有可解释的最近运行记录。\n"
            "可以先和机器人说一句话，或使用 /bot why <request_id|debug_id> 查询指定记录。"
        )
    else:
        body = _format_why_body(diagnostic)
    return CapabilityResult(
        request_id=request_id,
        capability_id="bot.why",
        kind="text",
        body=body,
        risk_level=RiskLevel.LOW,
        privacy_level=PrivacyLevel.PERSONAL,
        audit_tags=["why", "diagnostic"],
    )


def _dump_list(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=False)


def _load_list(value: str) -> list[str]:
    loaded = json.loads(value)
    if not isinstance(loaded, list):
        return []
    return [str(item) for item in loaded]


def _row_int(row: sqlite3.Row, column: str) -> int:
    if column not in row.keys():
        return 0
    value = row[column]
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return 0


def _row_list(row: sqlite3.Row, column: str) -> list[str]:
    if column not in row.keys():
        return []
    try:
        return _load_list(str(row[column]))
    except (json.JSONDecodeError, TypeError):
        return []


def _row_text(row: sqlite3.Row, column: str) -> str:
    if column not in row.keys():
        return ""
    return str(row[column])


def _safe_recent_limit(limit: int) -> int:
    return min(20, max(1, int(limit)))


def _format_why_body(diagnostic: RuntimeDiagnostic) -> str:
    send_request_state = "created" if diagnostic.send_request_created else "not_created"
    audit_tags = ",".join(diagnostic.audit_tags) if diagnostic.audit_tags else "-"
    audit_events = ",".join(diagnostic.audit_events) if diagnostic.audit_events else "-"
    actor_roles = ",".join(diagnostic.actor_roles) if diagnostic.actor_roles else "-"
    llm_finish_reason = infer_text_tag(diagnostic.audit_tags, "llm_finish_reason")
    lines = [
        "最近一次运行时诊断",
        f"请求：{diagnostic.request_id}",
        f"debug_id：{diagnostic.debug_id}",
        f"能力：{diagnostic.capability_id}",
        f"会话：{diagnostic.session_type}",
        f"角色：{actor_roles}",
        f"策略：{diagnostic.policy_reason}",
        f"回复预算：{diagnostic.reply_budget_reason or '-'}，最多 {diagnostic.max_messages} 条",
        f"上下文预算：{diagnostic.context_budget}",
        (
            "Prompt："
            f"messages={diagnostic.prompt_messages}，"
            f"system_chars={diagnostic.system_prompt_chars}，"
            f"user_chars={diagnostic.user_prompt_chars}，"
            f"total_chars={diagnostic.prompt_total_chars}，"
            f"remaining={diagnostic.prompt_budget_remaining}，"
            f"clipped={str(diagnostic.prompt_clipped).lower()}，"
            f"truncated={_format_sections(diagnostic.prompt_truncated_sections)}"
        ),
        (
            "上下文："
            f"knowledge={diagnostic.knowledge_chunks}，"
            f"memory={diagnostic.memory_facts}，"
            f"history={diagnostic.history_turns}，"
            f"emotion={diagnostic.emotion_signals}"
        ),
        f"LLM：{diagnostic.llm_status}，provider={diagnostic.llm_provider}，model={diagnostic.llm_model}",
        (
            f"LLM就绪：{diagnostic.llm_readiness_status or '-'}，"
            f"ready_for_real_llm={str(diagnostic.ready_for_real_llm).lower()}"
        ),
        f"LLM原因：{_format_reasons(diagnostic.llm_readiness_reasons)}",
    ]
    if diagnostic.llm_error_kind:
        lines.append(f"LLM 错误类型：{diagnostic.llm_error_kind}")
    if (
        diagnostic.llm_usage_prompt_tokens
        or diagnostic.llm_usage_completion_tokens
        or diagnostic.llm_usage_total_tokens
    ):
        lines.append(
            "Token："
            f"prompt={diagnostic.llm_usage_prompt_tokens}，"
            f"completion={diagnostic.llm_usage_completion_tokens}，"
            f"total={diagnostic.llm_usage_total_tokens}"
        )
    if llm_finish_reason:
        lines.append(f"LLM结束原因：{llm_finish_reason}")
    lines.extend(
        [
            f"发送请求：{send_request_state}",
            f"回执：{diagnostic.receipt_state}",
            f"审计事件：{audit_events}",
            f"审计标签：{audit_tags}",
            f"结论：{diagnostic.why_summary}",
        ]
    )
    return "\n".join(lines)


def build_diagnostic_why_summary(
    *,
    runtime_enabled: bool,
    policy_allowed: bool,
    policy_reason: str,
    session_type: SessionType,
    mentions_bot: bool,
    group_command_prefix: str,
    max_messages: int,
    reply_budget_reason: str,
    send_request_created: bool,
    receipt_state: str,
    review_block_reason: str = "",
    output_trimmed: bool = False,
    llm_error_kind: str = "",
    context_error_kind: str = "",
    llm_preflight_reasons: list[str] | None = None,
    rate_limit_reason: str = "",
    prompt_user_clipped: bool = False,
    history_skip_reason: str = "",
) -> str:
    prompt_clipping_note = (
        "当前用户消息过长，已按上下文预算裁剪；"
        if prompt_user_clipped
        else ""
    )
    history_skip_note = (
        "最近对话历史未记录，因为输入含提示注入风险；"
        if history_skip_reason == "prompt_injection"
        else ""
    )
    safe_llm_preflight_reasons = _safe_llm_preflight_reasons(
        llm_preflight_reasons or []
    )
    if not runtime_enabled:
        return "统一运行时已暂停，所以不会进入能力链路，也不会发送消息。"
    if not policy_allowed:
        if policy_reason == "runtime_paused":
            return "统一运行时已被管理员软暂停，已在能力执行前阻断。"
        if policy_reason == "rate_limited":
            if rate_limit_reason == "target_min_interval":
                return "命中目标最小回复间隔，已在调用 LLM 前阻断，避免对同一目标刷屏。"
            if rate_limit_reason == "global_window_exceeded":
                return "命中全局回复配额，已在调用 LLM 前阻断，避免机器人整体刷屏。"
            return "命中回复限速，已在调用 LLM 前阻断，避免刷屏。"
        if policy_reason == "quiet_hours":
            return "当前处于安静时间，已在调用 LLM 前阻断，避免夜间刷屏。"
        if policy_reason == "passive_group_message" and session_type is SessionType.GROUP:
            return (
                "群聊未提及机器人或命令前缀"
                f" {group_command_prefix}，所以只观察不回复。"
            )
        if policy_reason == "sender_blocked":
            return "发送者命中拉黑角色，所以在策略阶段阻断。"
        if policy_reason == "critical_input_risk":
            return "输入风险为 critical，所以在策略阶段阻断。"
        return f"策略阶段不允许回复：{policy_reason}。"
    if not send_request_created and review_block_reason == "persona_drift":
        return "策略允许，但输出审查发现人格漂移，已在 ReviewResult 阶段阻断，未创建 SendRequest。"
    if not send_request_created and review_block_reason == "unsafe_output_leakage":
        return "策略允许，但输出审查发现疑似内部上下文或密钥泄漏，已阻断发送。"
    if not send_request_created and review_block_reason == "review_blocked":
        return "策略允许，但输出未通过安全或隐私审查，已阻断发送。"
    if not send_request_created:
        return f"策略允许，但后续链路没有创建发送请求；最终回执为 {receipt_state}。"
    if context_error_kind:
        if reply_budget_reason:
            return (
                f"策略允许回复；回复预算原因是 {reply_budget_reason}，"
                f"最多回复 {max_messages} 条；{prompt_clipping_note}"
                "人格或知识上下文读取失败，已跳过 LLM，返回安全提示；"
                f"{history_skip_note}已创建 SendRequest。"
            )
        return (
            f"策略允许回复；{prompt_clipping_note}"
            "人格或知识上下文读取失败，已跳过 LLM，返回安全提示；"
            f"{history_skip_note}已创建 SendRequest。"
        )
    if llm_error_kind == "config_missing" and safe_llm_preflight_reasons:
        reason_text = ",".join(safe_llm_preflight_reasons)
        if reply_budget_reason:
            return (
                f"策略允许回复；回复预算原因是 {reply_budget_reason}，"
                f"最多回复 {max_messages} 条；{prompt_clipping_note}"
                "LLM 生成参数或配置非法，已在调用 provider 前阻断；"
                f"原因码：{reason_text}；{history_skip_note}"
                "已创建 SendRequest 返回安全失败提示。"
            )
        return (
            f"策略允许回复；{prompt_clipping_note}"
            "LLM 生成参数或配置非法，已在调用 provider 前阻断；"
            f"原因码：{reason_text}；{history_skip_note}"
            "已创建 SendRequest 返回安全失败提示。"
        )
    if llm_error_kind:
        if reply_budget_reason:
            return (
                f"策略允许回复；回复预算原因是 {reply_budget_reason}，"
                f"最多回复 {max_messages} 条；{prompt_clipping_note}LLM 调用失败，"
                f"错误类型是 {llm_error_kind}；{history_skip_note}"
                "已创建 SendRequest 返回安全失败提示。"
            )
        return (
            f"策略允许回复；{prompt_clipping_note}LLM 调用失败，"
            f"错误类型是 {llm_error_kind}；{history_skip_note}"
            "已创建 SendRequest 返回安全失败提示。"
        )
    if output_trimmed:
        kept_blocks = max(1, max_messages)
        if reply_budget_reason:
            return (
                f"策略允许回复；回复预算原因是 {reply_budget_reason}，"
                f"最多回复 {max_messages} 条；{prompt_clipping_note}模型输出超过预算，"
                f"已按回复预算收口，只保留前 {kept_blocks} 段；"
                f"{history_skip_note}已创建 SendRequest。"
            )
        return (
            f"策略允许回复；{prompt_clipping_note}模型输出超过预算，"
            f"已按回复预算收口，只保留前 {kept_blocks} 段；"
            f"{history_skip_note}已创建 SendRequest。"
        )
    if reply_budget_reason:
        return (
            f"策略允许回复；回复预算原因是 {reply_budget_reason}，"
            f"最多回复 {max_messages} 条；{prompt_clipping_note}"
            f"{history_skip_note}已创建 SendRequest。"
        )
    mention_text = "已提及机器人" if mentions_bot else "未提及机器人"
    return (
        f"策略允许回复，{mention_text}，{prompt_clipping_note}"
        f"{history_skip_note}已创建 SendRequest。"
    )


def build_diagnostic_audit_tags(
    *,
    policy_audit_tags: list[str],
    send_request: SendRequest | None,
    audit_records: Iterable[AuditRecord],
) -> list[str]:
    audit_record_list = list(audit_records)
    if send_request is not None:
        return _dedupe_tags(
            [
                *send_request.audit_tags,
                *_history_diagnostic_tags(audit_record_list),
            ]
        )
    return _dedupe_tags(
        [
            *policy_audit_tags,
            *_policy_diagnostic_tags(audit_record_list),
            *_review_diagnostic_tags(audit_record_list),
            *_history_diagnostic_tags(audit_record_list),
        ]
    )


def infer_rate_limit_blocked(audit_records: Iterable[AuditRecord]) -> bool:
    return any(
        record.stage == "policy" and record.event == "rate_limited"
        for record in audit_records
    )


def infer_runtime_paused(audit_records: Iterable[AuditRecord]) -> bool:
    return any(
        record.stage == "policy" and record.event == "runtime_paused"
        for record in audit_records
    )


def infer_rate_limit_reason(audit_records: Iterable[AuditRecord]) -> str:
    for record in audit_records:
        if record.stage != "policy" or record.event != "rate_limited":
            continue
        for part in record.private_debug.split(";"):
            key, separator, value = part.strip().partition("=")
            if separator and key == "reason" and _is_safe_reason(value):
                return value
    return ""


def infer_quiet_hours_blocked(audit_records: Iterable[AuditRecord]) -> bool:
    return any(
        record.stage == "policy" and record.event == "quiet_hours_blocked"
        for record in audit_records
    )


def infer_review_block_reason(audit_records: Iterable[AuditRecord]) -> str:
    tags = set(_review_diagnostic_tags(audit_records))
    if "persona_drift" in tags:
        return "persona_drift"
    if "unsafe_output_leakage" in tags:
        return "unsafe_output_leakage"
    if "review_blocked" in tags:
        return "review_blocked"
    return ""


def infer_history_skip_reason(audit_records: Iterable[AuditRecord]) -> str:
    for record in audit_records:
        if record.stage != "history" or record.event != "history_record_skipped":
            continue
        for part in record.private_debug.split(";"):
            key, separator, value = part.strip().partition("=")
            if separator and key == "reason" and _is_safe_reason(value):
                return value
    return ""


def infer_llm_error_kind(audit_tags: Iterable[str]) -> str:
    tag_list = list(audit_tags)
    for tag in tag_list:
        if tag.startswith("llm_error:"):
            error_kind = tag.removeprefix("llm_error:").strip()
            if error_kind:
                return error_kind
    if "llm_error" in set(tag_list):
        return "provider_error"
    return ""


def infer_context_error_kind(audit_tags: Iterable[str]) -> str:
    tag_list = list(audit_tags)
    for tag in tag_list:
        if not tag.startswith("context_error:"):
            continue
        error_kind = tag.removeprefix("context_error:").strip()
        if _is_safe_reason(error_kind):
            return error_kind
    if "context_error" in set(tag_list):
        return "provider_failed"
    return ""


def infer_llm_preflight_reasons(audit_tags: Iterable[str]) -> list[str]:
    reasons: list[str] = []
    for tag in audit_tags:
        if not tag.startswith("llm_preflight_error:"):
            continue
        reason = tag.removeprefix("llm_preflight_error:").strip()
        if _is_safe_llm_preflight_reason(reason) and reason not in reasons:
            reasons.append(reason)
    return reasons


def infer_int_tag(audit_tags: Iterable[str], key: str) -> int:
    prefix = f"{key}:"
    for tag in audit_tags:
        if not tag.startswith(prefix):
            continue
        value = tag.removeprefix(prefix).strip()
        if value.isdecimal():
            return int(value)
    return 0


def infer_bool_tag(audit_tags: Iterable[str], key: str) -> bool:
    prefix = f"{key}:"
    for tag in audit_tags:
        if tag.startswith(prefix):
            return tag.removeprefix(prefix).strip().lower() == "true"
    return False


def infer_text_tag(audit_tags: Iterable[str], key: str) -> str:
    prefix = f"{key}:"
    for tag in audit_tags:
        if not tag.startswith(prefix):
            continue
        value = tag.removeprefix(prefix).strip()
        if _is_safe_reason(value):
            return value
    return ""


def infer_prompt_truncated_sections(audit_tags: Iterable[str]) -> list[str]:
    prefix = "prompt_truncated_sections:"
    for tag in audit_tags:
        if not tag.startswith(prefix):
            continue
        raw_value = tag.removeprefix(prefix).strip()
        if not raw_value or raw_value == "-":
            return []
        return [
            section
            for section in raw_value.split("|")
            if _is_safe_section_name(section)
        ]
    return []


def _format_sections(values: list[str]) -> str:
    safe_values = [value for value in values if _is_safe_section_name(value)]
    return ",".join(safe_values) if safe_values else "-"


def _format_reasons(values: list[str]) -> str:
    safe_values = [value for value in values if _is_safe_reason(value)]
    return ",".join(safe_values) if safe_values else "-"


def _safe_llm_preflight_reasons(values: list[str]) -> list[str]:
    return [value for value in values if _is_safe_llm_preflight_reason(value)]


def _is_safe_llm_preflight_reason(value: str) -> bool:
    return value in {
        "openai_temperature_invalid",
        "openai_max_tokens_invalid",
        "openai_timeout_seconds_invalid",
    }


def _is_safe_section_name(value: str) -> bool:
    return bool(value) and all(
        char.isascii() and (char.isalnum() or char == "_")
        for char in value
    )


def _review_diagnostic_tags(audit_records: Iterable[AuditRecord]) -> list[str]:
    tags: list[str] = []
    for record in audit_records:
        if record.stage != "review":
            continue
        tags.append("review_blocked")
        private_debug = record.private_debug.lower()
        if "persona drift" in private_debug:
            tags.append("persona_drift")
        if "unsafe output leakage" in private_debug:
            tags.append("unsafe_output_leakage")
    return _dedupe_tags(tags)


def _policy_diagnostic_tags(audit_records: Iterable[AuditRecord]) -> list[str]:
    tags: list[str] = []
    for record in audit_records:
        if record.stage == "policy" and record.event == "rate_limited":
            tags.append("rate_limited")
            rate_limit_reason = infer_rate_limit_reason([record])
            if rate_limit_reason:
                tags.append(f"rate_limit:{rate_limit_reason}")
        if record.stage == "policy" and record.event == "quiet_hours_blocked":
            tags.append("quiet_hours_blocked")
    return _dedupe_tags(tags)


def _history_diagnostic_tags(audit_records: Iterable[AuditRecord]) -> list[str]:
    tags: list[str] = []
    for record in audit_records:
        if record.stage != "history" or record.event != "history_record_skipped":
            continue
        tags.append("history_record_skipped")
        reason = infer_history_skip_reason([record])
        if reason:
            tags.append(f"history_skip:{reason}")
    return _dedupe_tags(tags)


def _dedupe_tags(tags: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        if tag in seen:
            continue
        seen.add(tag)
        result.append(tag)
    return result


def _is_safe_reason(value: str) -> bool:
    return bool(value) and all(
        char.isascii() and (char.isalnum() or char == "_")
        for char in value
    )
