from __future__ import annotations

from pathlib import Path

from plugins.bot_unified_runtime.character.memory import (
    MEMORY_SENSITIVITIES,
    SQLiteMemoryRepository,
    build_fact_id,
    normalize_memory_sensitivity,
)
from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    PrivacyLevel,
    RiskLevel,
    SendPolicy,
    new_request_id,
)


def route_memory_command(
    command_text: str,
    *,
    sender_id: str,
    session_id: str,
    db_path: str | Path,
    request_id: str | None = None,
) -> CapabilityResult:
    normalized = command_text.strip()
    if not db_path:
        return _memory_result(
            body="记忆数据库未配置：请先设置 BOT_MEMORY_ENABLED=true 和 BOT_MEMORY_DB_PATH。",
            request_id=request_id,
        )
    if normalized == "memory list":
        if _is_group_session(session_id):
            return _list_memory(
                sender_id=sender_id,
                session_id=session_id,
                db_path=db_path,
                request_id=request_id,
                allowed_sensitivities={"public", "group"},
            )
        return _list_memory(
            sender_id=sender_id,
            session_id=session_id,
            db_path=db_path,
            request_id=request_id,
            allowed_sensitivities=None,
        )
    if normalized.startswith("memory add "):
        parsed_add = _parse_add_args(normalized.removeprefix("memory add ").strip())
        if parsed_add.error:
            return _memory_result(body=parsed_add.error, request_id=request_id)
        return _add_memory(
            text=parsed_add.text,
            sensitivity=parsed_add.sensitivity,
            sender_id=sender_id,
            session_id=session_id,
            db_path=db_path,
            request_id=request_id,
        )
    if normalized.startswith("memory delete "):
        fact_id = normalized.removeprefix("memory delete ").strip()
        return _delete_memory(
            fact_id=fact_id,
            sender_id=sender_id,
            session_id=session_id,
            db_path=db_path,
            request_id=request_id,
        )
    return _memory_result(
        body="用法：/bot memory add <内容>；/bot memory list；/bot memory delete <fact_id>",
        request_id=request_id,
    )


def is_memory_command_text(command_text: str) -> bool:
    return command_text.strip().startswith("memory")


def _is_group_session(session_id: str) -> bool:
    return session_id.strip().lower().startswith("group:")


def _add_memory(
    *,
    text: str,
    sensitivity: str,
    sender_id: str,
    session_id: str,
    db_path: str | Path,
    request_id: str | None,
) -> CapabilityResult:
    if not text:
        return _memory_result(body="记忆内容不能为空。", request_id=request_id)
    fact_id = build_fact_id(sender_id, session_id, text)
    SQLiteMemoryRepository(db_path).upsert_fact(
        fact_id=fact_id,
        subject_user_id=sender_id,
        session_id=session_id,
        memory_kind="manual",
        text=text,
        confidence=1.0,
        source="manual_command",
        sensitivity=sensitivity,
    )
    return _memory_result(
        body=f"已记住：{text}\nfact_id={fact_id}\nsensitivity={sensitivity}",
        request_id=request_id,
    )


def _list_memory(
    *,
    sender_id: str,
    session_id: str,
    db_path: str | Path,
    request_id: str | None,
    allowed_sensitivities: set[str] | None,
) -> CapabilityResult:
    memory = SQLiteMemoryRepository(db_path).retrieve(
        request_id=request_id or new_request_id("memory"),
        requester_id=sender_id,
        subject_user_id=sender_id,
        session_id=session_id,
        query_text="",
        max_items=20,
        max_chars=2000,
    )
    facts = [
        fact
        for fact in memory.facts
        if allowed_sensitivities is None
        or fact.get("sensitivity", "personal") in allowed_sensitivities
    ]
    if not facts:
        if allowed_sensitivities is not None:
            return _memory_result(
                body="群聊中没有可公开查看的记忆；请在私聊中查看个人记忆。",
                request_id=memory.request_id,
            )
        return _memory_result(body="当前会话还没有可用记忆。", request_id=memory.request_id)
    lines = ["当前记忆："]
    lines.extend(
        f"- {fact['fact_id']}（sensitivity={fact.get('sensitivity', 'personal')}）：{fact['text']}"
        for fact in facts
    )
    return _memory_result(body="\n".join(lines), request_id=memory.request_id)


def _delete_memory(
    *,
    fact_id: str,
    sender_id: str,
    session_id: str,
    db_path: str | Path,
    request_id: str | None,
) -> CapabilityResult:
    if not fact_id:
        return _memory_result(body="请提供要删除的 fact_id。", request_id=request_id)
    deleted = SQLiteMemoryRepository(db_path).delete_fact(
        fact_id=fact_id,
        subject_user_id=sender_id,
        session_id=session_id,
    )
    if deleted:
        return _memory_result(body=f"已删除记忆：{fact_id}", request_id=request_id)
    return _memory_result(body=f"未找到可删除的记忆：{fact_id}", request_id=request_id)


def _memory_result(body: str, request_id: str | None = None) -> CapabilityResult:
    return CapabilityResult(
        request_id=request_id or new_request_id("memory"),
        capability_id="bot.memory",
        kind="text",
        title="记忆管理",
        body=body,
        risk_level=RiskLevel.LOW,
        privacy_level=PrivacyLevel.PERSONAL,
        send_policy=SendPolicy.IMMEDIATE,
        audit_tags=["memory_command"],
    )


class _ParsedAddArgs:
    def __init__(self, *, text: str, sensitivity: str, error: str = "") -> None:
        self.text = text
        self.sensitivity = sensitivity
        self.error = error


def _parse_add_args(raw_text: str) -> _ParsedAddArgs:
    sensitivity = "personal"
    text = raw_text
    prefix = "--sensitivity="
    if text.startswith(prefix):
        first, _, rest = text.partition(" ")
        try:
            sensitivity = normalize_memory_sensitivity(first.removeprefix(prefix))
        except ValueError:
            allowed = ", ".join(sorted(MEMORY_SENSITIVITIES))
            return _ParsedAddArgs(
                text="",
                sensitivity="personal",
                error=f"sensitivity 参数无效；可用值：{allowed}。",
            )
        text = rest.strip()
    return _ParsedAddArgs(text=text.strip(), sensitivity=sensitivity)
