from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from plugins.bot_unified_runtime.audit import AuditRepository, redact_private_debug
from plugins.bot_unified_runtime.capabilities.chat import (
    ChatPromptDiagnostics,
    build_chat_prompt_with_diagnostics,
)
from plugins.bot_unified_runtime.character import (
    ConversationHistoryStore,
    build_character_context_provider,
)
from plugins.bot_unified_runtime.character.source_summary import (
    build_safe_context_source_summary,
)
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import (
    AuditRecord,
    CapabilityResult,
    ContextBundle,
    DeliveryReceipt,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
    SendPolicy,
    SessionType,
    new_request_id,
)
from plugins.bot_unified_runtime.diagnostics import DiagnosticsStore, RuntimeDiagnostic
from plugins.bot_unified_runtime.llm import (
    LLMProvider,
    LLMProviderError,
    OpenAICompatibleLLMProvider,
    public_llm_error_message,
    safe_llm_finish_reason,
)
from plugins.bot_unified_runtime.policy import build_reply_budget_settings, decide_reply_budget
from plugins.bot_unified_runtime.policy.roles import ROLE_ORDER, build_role_settings
from plugins.bot_unified_runtime.runtime import RuntimeControlState
from plugins.bot_unified_runtime.security import InjectionCheckInput, check_prompt_injection
from plugins.bot_unified_runtime.sender import ReceiptRepository, SendQueue
from plugins.bot_unified_runtime.config_readiness import (
    diagnostic_llm_max_tokens,
    diagnostic_llm_temperature,
    has_real_api_key,
    openai_compatible_preflight_errors,
    run_config_smoke,
    safe_openai_endpoint_url,
)

_DENIED_BODY = "只有管理员可以查看运行时排障记录。"


def build_receipt_query_result(
    receipt_repository: ReceiptRepository,
    *,
    request_id: str | None = None,
    actor_roles: list[str],
    query: str,
) -> CapabilityResult:
    normalized_query = query.strip()
    if not _is_admin(actor_roles):
        return _debug_result(
            capability_id="bot.receipt",
            title="发送回执",
            body=_DENIED_BODY,
            request_id=request_id,
            audit_tags=["debug_query", "receipt_query", "debug_denied"],
        )
    if not normalized_query:
        return _debug_result(
            capability_id="bot.receipt",
            title="发送回执",
            body="用法：/bot receipt <request_id|debug_id>",
            request_id=request_id,
            audit_tags=["debug_query", "receipt_query", "debug_usage"],
        )
    receipt = receipt_repository.find(normalized_query)
    if receipt is None:
        return _debug_result(
            capability_id="bot.receipt",
            title="发送回执",
            body=f"未找到发送回执：{_safe_token(normalized_query)}",
            request_id=request_id,
            audit_tags=["debug_query", "receipt_query", "debug_not_found"],
        )
    return _debug_result(
        capability_id="bot.receipt",
        title="发送回执",
        body=_format_receipt(receipt),
        request_id=request_id,
        audit_tags=["debug_query", "receipt_query"],
    )


def build_audit_query_result(
    audit_repository: AuditRepository,
    *,
    request_id: str | None = None,
    actor_roles: list[str],
    query: str,
) -> CapabilityResult:
    normalized_query = query.strip()
    if not _is_admin(actor_roles):
        return _debug_result(
            capability_id="bot.audit",
            title="审计事件",
            body=_DENIED_BODY,
            request_id=request_id,
            audit_tags=["debug_query", "audit_query", "debug_denied"],
        )
    if not normalized_query:
        return _debug_result(
            capability_id="bot.audit",
            title="审计事件",
            body="用法：/bot audit <request_id>",
            request_id=request_id,
            audit_tags=["debug_query", "audit_query", "debug_usage"],
        )
    records = audit_repository.list_records(normalized_query)
    if not records:
        return _debug_result(
            capability_id="bot.audit",
            title="审计事件",
            body=f"未找到审计事件：{_safe_token(normalized_query)}",
            request_id=request_id,
            audit_tags=["debug_query", "audit_query", "debug_not_found"],
        )
    return _debug_result(
        capability_id="bot.audit",
        title="审计事件",
        body=_format_audit_records(normalized_query, records),
        request_id=request_id,
        audit_tags=["debug_query", "audit_query"],
    )


def build_recent_query_result(
    diagnostics_store: DiagnosticsStore,
    receipt_repository: ReceiptRepository,
    audit_repository: AuditRepository,
    *,
    request_id: str | None = None,
    actor_roles: list[str],
    query: str,
) -> CapabilityResult:
    if not _is_admin(actor_roles):
        return _debug_result(
            capability_id="bot.recent",
            title="最近排障",
            body=_DENIED_BODY,
            request_id=request_id,
            audit_tags=["debug_query", "recent_query", "debug_denied"],
        )
    limit = _parse_limit(query)
    diagnostics = diagnostics_store.list_recent(limit)
    receipts = list(reversed(receipt_repository.list_receipts()))[:limit]
    audits = list(reversed(audit_repository.list_records()))[:limit]
    body = "\n".join(
        [
            f"最近排障摘要：limit={limit}",
            _format_recent_diagnostics(diagnostics),
            _format_recent_receipts(receipts),
            _format_recent_audits(audits),
        ]
    )
    return _debug_result(
        capability_id="bot.recent",
        title="最近排障",
        body=body,
        request_id=request_id,
        audit_tags=["debug_query", "recent_query"],
    )


def build_queue_query_result(
    send_queue: SendQueue,
    config: Config,
    *,
    request_id: str | None = None,
    actor_roles: list[str],
) -> CapabilityResult:
    if not _is_admin(actor_roles):
        return _debug_result(
            capability_id="bot.queue",
            title="发送队列",
            body=_DENIED_BODY,
            request_id=request_id,
            audit_tags=["debug_query", "queue_query", "debug_denied"],
        )

    return _debug_result(
        capability_id="bot.queue",
        title="发送队列",
        body=_format_queue_diagnostic(send_queue.safe_summary(), config),
        request_id=request_id,
        audit_tags=["debug_query", "queue_query"],
    )


def build_roles_query_result(
    config: Config,
    *,
    request_id: str | None = None,
    actor_roles: list[str],
) -> CapabilityResult:
    if not _is_admin(actor_roles):
        return _debug_result(
            capability_id="bot.roles",
            title="权限规则",
            body=_DENIED_BODY,
            request_id=request_id,
            audit_tags=["debug_query", "roles_query", "debug_denied"],
        )

    return _debug_result(
        capability_id="bot.roles",
        title="权限规则",
        body=_format_roles_diagnostic(config),
        request_id=request_id,
        audit_tags=["debug_query", "roles_query"],
    )


def build_persona_query_result(
    config: Config,
    *,
    request_id: str | None = None,
    actor_roles: list[str],
) -> CapabilityResult:
    if not _is_admin(actor_roles):
        return _debug_result(
            capability_id="bot.persona",
            title="人格自检",
            body=_DENIED_BODY,
            request_id=request_id,
            audit_tags=["debug_query", "persona_query", "debug_denied"],
        )

    from plugins.bot_unified_runtime.smoke import run_persona_smoke

    result = run_persona_smoke(config)
    return _debug_result(
        capability_id="bot.persona",
        title="人格自检",
        body=_format_persona_diagnostic(result),
        request_id=request_id,
        audit_tags=[
            "debug_query",
            "persona_query",
            "persona_ok" if result["ok"] else "persona_error",
        ],
    )


def build_runtime_control_result(
    runtime_control: RuntimeControlState,
    *,
    request_id: str | None = None,
    actor_roles: list[str],
    command: str,
    actor_id: str,
) -> CapabilityResult:
    if not _is_admin(actor_roles):
        return _debug_result(
            capability_id="bot.control",
            title="运行时控制",
            body=_DENIED_BODY,
            request_id=request_id,
            audit_tags=["debug_query", "runtime_control", "debug_denied"],
        )

    normalized_command = command.strip().lower()
    if normalized_command == "pause":
        runtime_control.pause(actor_id=actor_id)
        return _debug_result(
            capability_id="bot.control",
            title="运行时控制",
            body=_format_runtime_control_state(
                runtime_control,
                headline="运行时已暂停。",
            ),
            request_id=request_id,
            audit_tags=["debug_query", "runtime_control", "runtime_pause"],
        )
    if normalized_command == "resume":
        runtime_control.resume(actor_id=actor_id)
        return _debug_result(
            capability_id="bot.control",
            title="运行时控制",
            body=_format_runtime_control_state(
                runtime_control,
                headline="运行时已恢复。",
            ),
            request_id=request_id,
            audit_tags=["debug_query", "runtime_control", "runtime_resume"],
        )

    return _debug_result(
        capability_id="bot.control",
        title="运行时控制",
        body="用法：/bot pause 或 /bot resume",
        request_id=request_id,
        audit_tags=["debug_query", "runtime_control", "debug_usage"],
    )


def build_history_clear_result(
    history_store: ConversationHistoryStore,
    *,
    request_id: str | None = None,
    actor_roles: list[str],
    platform: str,
    adapter: str,
    bot_id: str,
    session_id: str,
    sender_id: str,
) -> CapabilityResult:
    if not _is_admin(actor_roles):
        return _debug_result(
            capability_id="bot.history",
            title="最近对话历史",
            body=_DENIED_BODY,
            request_id=request_id,
            audit_tags=["debug_query", "history_clear", "debug_denied"],
        )

    try:
        cleared_turns = history_store.clear_scope(
            platform=platform,
            adapter=adapter,
            bot_id=bot_id,
            session_id=session_id,
            sender_id=sender_id,
        )
    except Exception:  # noqa: BLE001 - keep diagnostics safe and actionable.
        return _debug_result(
            capability_id="bot.history",
            title="最近对话历史",
            body=(
                "最近对话历史清理失败：请检查历史库配置是否可写。\n"
                "说明：不会展示数据库路径、会话 ID、用户 ID 或历史正文。"
            ),
            request_id=request_id,
            audit_tags=["debug_query", "history_clear", "debug_error"],
        )

    return _debug_result(
        capability_id="bot.history",
        title="最近对话历史",
        body="\n".join(
            [
                "最近对话历史已清理。",
                "说明：只清理当前会话、当前发送者、当前机器人实例的最近对话；不影响长期记忆。",
                f"cleared_turns={_safe_int(cleared_turns)}",
            ]
        ),
        request_id=request_id,
        audit_tags=["debug_query", "history_clear"],
    )


def build_context_query_result(
    config: Config,
    *,
    request_id: str | None = None,
    actor_roles: list[str],
    sender_id: str,
    session_id: str,
    query: str,
    session_type: SessionType = SessionType.PRIVATE,
    platform: str = "unknown",
    adapter: str = "unknown",
    bot_id: str = "unknown",
) -> CapabilityResult:
    if not _is_admin(actor_roles):
        return _debug_result(
            capability_id="bot.context",
            title="上下文诊断",
            body=_DENIED_BODY,
            request_id=request_id,
            audit_tags=["debug_query", "context_query", "debug_denied"],
        )

    normalized_query = query.strip() or "你好，守岸人。"
    message = IncomingMessage(
        request_id=request_id or new_request_id("context"),
        platform=platform,
        adapter=adapter,
        bot_id=bot_id,
        session_id=session_id,
        session_type=session_type,
        sender_id=sender_id,
        plain_text=normalized_query,
        raw_segments=[{"type": "text", "data": {"text": normalized_query}}],
        mentions_bot=True,
    )
    try:
        injection_check = check_prompt_injection(
            InjectionCheckInput(
                request_id=message.request_id,
                source_type="user_message",
                plain_text=message.plain_text,
                target_stage="context_diagnostic",
                risk_level=message.risk_level,
                privacy_level=message.privacy_level or PrivacyLevel.PERSONAL,
            )
        )
        budget_message = message.model_copy(
            update={
                "plain_text": injection_check.sanitized_text,
                "risk_level": injection_check.risk_level,
            }
        )
        reply_budget = decide_reply_budget(
            budget_message,
            "bot.chat",
            build_reply_budget_settings(config),
        )
        context = build_character_context_provider(config).build_context(
            request_id=message.request_id,
            sender_id=message.sender_id,
            session_id=message.session_id,
            query_text=injection_check.sanitized_text,
            platform=message.platform,
            adapter=message.adapter,
            bot_id=message.bot_id,
        )
        context = context.model_copy(
            update={
                "context_budget": reply_budget.context_budget,
                "current_message": injection_check.sanitized_text,
                "risk_level": injection_check.risk_level,
                "tone": context.tone.model_copy(
                    update={"message_count_limit": reply_budget.max_messages}
                ),
            }
        )
        prompt_messages, prompt_diagnostics = build_chat_prompt_with_diagnostics(context)
    except Exception as exc:  # noqa: BLE001 - diagnostics must return actionable text.
        return _debug_result(
            capability_id="bot.context",
            title="上下文诊断",
            body=(
                "上下文诊断失败：人格、知识、记忆、最近对话或 prompt 构造出现错误。\n"
                f"error={_safe_message(type(exc).__name__)}"
            ),
            request_id=message.request_id,
            audit_tags=["debug_query", "context_query", "debug_error"],
        )

    body = _format_context_summary(
        config=config,
        context=context,
        prompt_messages=prompt_messages,
        prompt_diagnostics=prompt_diagnostics,
        reply_budget_reason=reply_budget.reason,
        risk_level=injection_check.risk_level,
    )
    return _debug_result(
        capability_id="bot.context",
        title="上下文诊断",
        body=body,
        request_id=message.request_id,
        audit_tags=["debug_query", "context_query"],
    )


def build_config_query_result(
    config: Config,
    *,
    request_id: str | None = None,
    actor_roles: list[str],
) -> CapabilityResult:
    if not _is_admin(actor_roles):
        return _debug_result(
            capability_id="bot.config",
            title="配置体检",
            body=_DENIED_BODY,
            request_id=request_id,
            audit_tags=["debug_query", "config_query", "debug_denied"],
        )

    result = run_config_smoke(config)
    return _debug_result(
        capability_id="bot.config",
        title="配置体检",
        body=_format_config_diagnostic(result),
        request_id=request_id,
        audit_tags=[
            "debug_query",
            "config_query",
            "config_ok" if result["ok"] else "config_error",
        ],
    )


def build_readiness_query_result(
    config: Config,
    *,
    request_id: str | None = None,
    actor_roles: list[str],
    importer: Callable[[str], Any] | None = None,
    command_resolver: Callable[[str], str | None] | None = None,
    runtime_control: RuntimeControlState | None = None,
) -> CapabilityResult:
    if not _is_admin(actor_roles):
        return _debug_result(
            capability_id="bot.readiness",
            title="统一就绪度",
            body=_DENIED_BODY,
            request_id=request_id,
            audit_tags=["debug_query", "readiness_query", "debug_denied"],
        )

    from plugins.bot_unified_runtime.smoke import run_readiness_smoke

    result = run_readiness_smoke(
        config,
        importer=importer,
        command_resolver=command_resolver,
    )
    result = {
        **result,
        "runtime_control": runtime_control or RuntimeControlState(),
    }
    return _debug_result(
        capability_id="bot.readiness",
        title="统一就绪度",
        body=_format_readiness_diagnostic(result),
        request_id=request_id,
        audit_tags=[
            "debug_query",
            "readiness_query",
            "readiness_ok" if result["ok"] else "readiness_error",
        ],
    )


def build_dialogue_query_result(
    config: Config,
    *,
    request_id: str | None = None,
    actor_roles: list[str],
    query: str,
    llm_provider: LLMProvider | None = None,
) -> CapabilityResult:
    if not _is_admin(actor_roles):
        return _debug_result(
            capability_id="bot.dialogue",
            title="对话验收",
            body=_DENIED_BODY,
            request_id=request_id,
            audit_tags=["debug_query", "dialogue_query", "debug_denied"],
        )

    from plugins.bot_unified_runtime.smoke import run_dialogue_smoke

    result = run_dialogue_smoke(
        config,
        message_text=query.strip() or "你好，守岸人。",
        llm_provider=llm_provider,
    )
    return _debug_result(
        capability_id="bot.dialogue",
        title="对话验收",
        body=_format_dialogue_diagnostic(result),
        request_id=request_id,
        audit_tags=[
            "debug_query",
            "dialogue_query",
            "dialogue_ok" if result["ok"] else "dialogue_error",
        ],
    )


def build_llm_query_result(
    config: Config,
    *,
    request_id: str | None = None,
    actor_roles: list[str],
    llm_provider: LLMProvider | None = None,
) -> CapabilityResult:
    if not _is_admin(actor_roles):
        return _debug_result(
            capability_id="bot.llm",
            title="LLM 诊断",
            body=_DENIED_BODY,
            request_id=request_id,
            audit_tags=["debug_query", "llm_query", "debug_denied"],
        )

    result = _run_llm_diagnostic(config, llm_provider=llm_provider)
    return _debug_result(
        capability_id="bot.llm",
        title="LLM 诊断",
        body=_format_llm_diagnostic(result),
        request_id=request_id,
        audit_tags=["debug_query", "llm_query", f"llm_diag:{result['error_kind']}"],
    )


def build_llm_setup_query_result(
    config: Config,
    *,
    request_id: str | None = None,
    actor_roles: list[str],
) -> CapabilityResult:
    if not _is_admin(actor_roles):
        return _debug_result(
            capability_id="bot.setup.llm",
            title="LLM 接入清单",
            body=_DENIED_BODY,
            request_id=request_id,
            audit_tags=["debug_query", "llm_setup_query", "debug_denied"],
        )

    from plugins.bot_unified_runtime.smoke import run_llm_setup

    result = run_llm_setup(config)
    return _debug_result(
        capability_id="bot.setup.llm",
        title="LLM 接入清单",
        body=_format_llm_setup_diagnostic(result),
        request_id=request_id,
        audit_tags=[
            "debug_query",
            "llm_setup_query",
            "llm_setup_ok" if result["ok"] else "llm_setup_error",
        ],
    )


def _debug_result(
    *,
    capability_id: str,
    title: str,
    body: str,
    request_id: str | None,
    audit_tags: list[str],
) -> CapabilityResult:
    return CapabilityResult(
        request_id=request_id or new_request_id("debug"),
        capability_id=capability_id,
        kind="text",
        title=title,
        body=body,
        risk_level=RiskLevel.LOW,
        privacy_level=PrivacyLevel.PERSONAL,
        send_policy=SendPolicy.IMMEDIATE,
        audit_tags=audit_tags,
    )


def _run_llm_diagnostic(
    config: Config,
    *,
    llm_provider: LLMProvider | None = None,
) -> dict[str, object]:
    readiness = run_config_smoke(config)
    provider_name = config.bot_chat_provider
    endpoint_url = safe_openai_endpoint_url(config.bot_chat_base_url)
    has_real_api_key_value = has_real_api_key(config.bot_chat_api_key)
    base_result: dict[str, object] = {
        "ok": False,
        "provider": provider_name,
        "model": config.bot_chat_model,
        "endpoint_url": endpoint_url,
        "api_key": "set" if has_real_api_key_value else "missing",
        "diagnostic_temperature": diagnostic_llm_temperature(config),
        "diagnostic_max_tokens": diagnostic_llm_max_tokens(config),
        "timeout_seconds": config.bot_chat_timeout_seconds,
        "ready_for_real_llm": readiness["ready_for_real_llm"],
        "llm_readiness_status": readiness["llm_readiness_status"],
        "llm_next_action": readiness["llm_next_action"],
        "llm_readiness_reasons": readiness["llm_readiness_reasons"],
        "llm_fix_hints": readiness["llm_fix_hints"],
        "error_kind": "none",
        "reply_preview_chars": 0,
        "usage_total_tokens": 0,
        "llm_finish_reason": "",
        "public_message": "",
    }

    if provider_name != "openai_compatible":
        return {
            **base_result,
            "error_kind": "provider_not_configured",
            "public_message": "当前 provider 不是真实模型连接。",
        }

    provider_config_errors = openai_compatible_preflight_errors(config)
    if provider_config_errors:
        return {
            **base_result,
            "error_kind": "config_missing",
            "public_message": _format_llm_preflight_missing_message(
                provider_config_errors
            ),
        }

    provider = llm_provider or OpenAICompatibleLLMProvider(
        api_key=config.bot_chat_api_key,
        model=config.bot_chat_model,
        base_url=config.bot_chat_base_url,
        timeout_seconds=config.bot_chat_timeout_seconds,
    )
    messages = [
        {
            "role": "system",
            "content": "你是本地 LLM 连接诊断请求。只需要用一句中文回复连接正常，不要请求工具，不要输出密钥。",
        },
        {"role": "user", "content": "请回复：诊断连接正常。"},
    ]
    try:
        reply = provider.generate(
            messages,
            model=config.bot_chat_model,
            temperature=diagnostic_llm_temperature(config),
            max_tokens=diagnostic_llm_max_tokens(config),
        )
    except LLMProviderError as exc:
        error_kind = exc.error_kind
        return {
            **base_result,
            "error_kind": error_kind,
            "public_message": public_llm_error_message(error_kind),
        }
    except Exception:
        return {
            **base_result,
            "error_kind": "provider_error",
            "public_message": public_llm_error_message("provider_error"),
        }

    usage_total_tokens = 0
    raw_total_tokens = reply.raw_usage.get("total_tokens")
    if isinstance(raw_total_tokens, int):
        usage_total_tokens = raw_total_tokens
    finish_reason = safe_llm_finish_reason(reply.raw_usage.get("finish_reason"))
    return {
        **base_result,
        "ok": True,
        "error_kind": "none",
        "reply_preview_chars": len(reply.text[:120]),
        "usage_total_tokens": usage_total_tokens,
        "llm_finish_reason": finish_reason,
        "public_message": "LLM 诊断通过。",
    }


def _format_llm_preflight_missing_message(errors: list[str]) -> str:
    label_map = {
        "openai_api_key_missing": "API key",
        "openai_model_missing": "model",
        "openai_base_url_missing": "base_url",
        "openai_base_url_invalid": "base_url",
        "openai_base_url_unsafe": "base_url",
        "openai_temperature_invalid": "temperature",
        "openai_max_tokens_invalid": "max_tokens",
        "openai_timeout_seconds_invalid": "timeout_seconds",
    }
    labels = [label_map[error] for error in errors if error in label_map]
    joined = "、".join(labels) if labels else "必要参数"
    return f"openai_compatible provider 配置不完整，缺少 {joined}。"


def _format_readiness_diagnostic(result: dict[str, Any]) -> str:
    runtime_control = result.get("runtime_control")
    if not isinstance(runtime_control, RuntimeControlState):
        runtime_control = RuntimeControlState()
    return "\n".join(
        [
            "统一就绪度：",
            "说明：仅管理员可用；不调用真实 LLM，不连接 NapCat，不发送 QQ，只展示安全摘要。",
            f"ok={str(bool(result['ok'])).lower()}",
            f"readiness_status={_safe_token(str(result['readiness_status']))}",
            f"next_action={_safe_token(str(result['next_action']))}",
            f"recommended_commands={_safe_csv(str(result['recommended_commands']))}",
            f"runtime_soft_paused={str(runtime_control.paused).lower()}",
            f"runtime_soft_pause_reason={_safe_token(runtime_control.reason)}",
            (
                "runtime_soft_pause_updated_by="
                f"{_safe_token(runtime_control.updated_by_state)}"
            ),
            (
                "ready_for_local_dialogue="
                f"{str(bool(result['ready_for_local_dialogue'])).lower()}"
            ),
            f"ready_for_real_llm={str(bool(result['ready_for_real_llm'])).lower()}",
            (
                "real_llm_probe_performed="
                f"{str(bool(result['real_llm_probe_performed'])).lower()}"
            ),
            f"doctor_ok={str(bool(result['doctor_ok'])).lower()}",
            (
                "ready_for_local_llm_smoke="
                f"{str(bool(result['ready_for_local_llm_smoke'])).lower()}"
            ),
            (
                "ready_for_nonebot_run="
                f"{str(bool(result['ready_for_nonebot_run'])).lower()}"
            ),
            f"nonebot_ok={str(bool(result['nonebot_ok'])).lower()}",
            f"transport_ok={str(bool(result['transport_ok'])).lower()}",
            f"config_ok={str(bool(result['config_ok'])).lower()}",
            f"config_errors={_format_list_field(result.get('config_errors', []))}",
            f"config_warnings={_format_list_field(result.get('config_warnings', []))}",
            f"context_ok={str(bool(result['context_ok'])).lower()}",
            f"context_error_kind={_safe_token(str(result['context_error_kind']))}",
            f"context_chars={_safe_int(result['context_prompt_total_chars'])}",
            (
                "context_clipped="
                f"{str(bool(result['context_prompt_clipped'])).lower()}"
            ),
            f"chat_pipeline_ok={str(bool(result['chat_pipeline_ok'])).lower()}",
            f"chat_pipeline_mode={_safe_token(str(result['chat_pipeline_mode']))}",
            f"chat_receipt_state={_safe_token(str(result['chat_receipt_state']))}",
            f"chat_reply_preview_chars={_safe_int(result['chat_reply_preview_chars'])}",
            f"llm_finish_reason={_safe_token(str(result.get('llm_finish_reason') or '-'))}",
            f"llm_readiness_status={_safe_token(str(result['llm_readiness_status']))}",
            f"llm_next_action={_safe_token(str(result['llm_next_action']))}",
            (
                "llm_readiness_reasons="
                f"{_format_list_field(result.get('llm_readiness_reasons', []))}"
            ),
            f"llm_fix_hints={_format_list_field(result.get('llm_fix_hints', []))}",
            f"persona_strength_status={_safe_token(str(result['persona_strength_status']))}",
            f"knowledge_readable={_safe_int(result['knowledge_readable'])}",
            f"provider={_safe_token(str(result['provider']))}",
            f"model={_safe_token(str(result['model']))}",
            f"chat_api_key={_safe_token(str(result['chat_api_key']))}",
            f"public_message={_safe_message(str(result['public_message']))}",
        ]
    )


def _format_dialogue_diagnostic(result: dict[str, Any]) -> str:
    return "\n".join(
        [
            "对话验收：",
            (
                "说明：仅管理员可用；执行一轮本地对话 pipeline，可能短调用已配置的真实 LLM；"
                "不连接新的 NapCat，不发送业务对话正文，不展示完整回复、prompt、用户原文或知识原文。"
            ),
            f"ok={str(bool(result['ok'])).lower()}",
            f"dialogue_status={_safe_token(str(result['dialogue_status']))}",
            f"next_action={_safe_token(str(result['next_action']))}",
            f"context_ok={str(bool(result['context_ok'])).lower()}",
            f"context_error_kind={_safe_token(str(result['context_error_kind']))}",
            f"chat_pipeline_ok={str(bool(result['chat_pipeline_ok'])).lower()}",
            f"receipt_state={_safe_token(str(result['receipt_state']))}",
            f"capability_id={_safe_token(str(result['capability_id']))}",
            f"persona_profile_id={_safe_token(str(result['persona_profile_id']))}",
            f"persona_display_name={_safe_token(str(result['persona_display_name']))}",
            f"persona_source_refs={_safe_csv(str(result['persona_source_refs']))}",
            f"knowledge_source_refs={_safe_csv(str(result['knowledge_source_refs']))}",
            f"knowledge_chunks={_safe_int(result['knowledge_chunks'])}",
            f"memory_facts={_safe_int(result['memory_facts'])}",
            f"history_turns={_safe_int(result['history_turns'])}",
            f"emotion_signals={_safe_int(result['emotion_signals'])}",
            f"emotion_labels={_safe_token(str(result['emotion_labels']))}",
            f"prompt_messages={_safe_int(result['prompt_messages'])}",
            f"prompt_total_chars={_safe_int(result['prompt_total_chars'])}",
            f"prompt_budget_remaining={_safe_int(result['prompt_budget_remaining'])}",
            f"prompt_clipped={str(bool(result['prompt_clipped'])).lower()}",
            f"prompt_truncated_sections={_safe_token(str(result['prompt_truncated_sections']))}",
            f"context_budget={_safe_int(result['context_budget'])}",
            f"max_messages={_safe_int(result['max_messages'])}",
            f"risk_level={_safe_token(str(result['risk_level']))}",
            f"llm_status={_safe_token(str(result['llm_status']))}",
            f"llm_error_kind={_safe_token(str(result.get('llm_error_kind') or '-'))}",
            f"llm_finish_reason={_safe_token(str(result.get('llm_finish_reason') or '-'))}",
            f"llm_provider={_safe_token(str(result['llm_provider']))}",
            f"llm_model={_safe_token(str(result['llm_model']))}",
            f"ready_for_real_llm={str(bool(result['ready_for_real_llm'])).lower()}",
            f"llm_readiness_status={_safe_token(str(result['llm_readiness_status']))}",
            f"llm_next_action={_safe_token(str(result['llm_next_action']))}",
            (
                "llm_readiness_reasons="
                f"{_format_list_field(result.get('llm_readiness_reasons', []))}"
            ),
            f"llm_fix_hints={_format_list_field(result.get('llm_fix_hints', []))}",
            f"reply_preview_chars={_safe_int(result['reply_preview_chars'])}",
            f"reply_text_hidden={str(bool(result['reply_text_hidden'])).lower()}",
            f"real_transport_used={str(bool(result['real_transport_used'])).lower()}",
            f"napcat_connected={str(bool(result['napcat_connected'])).lower()}",
            f"public_message={_safe_message(str(result['public_message']))}",
        ]
    )


def _format_llm_diagnostic(result: dict[str, object]) -> str:
    return "\n".join(
        [
            "LLM 诊断：",
            "说明：仅管理员可用；短调用只用于连接诊断，不发送外部聊天消息，不展示密钥。",
            f"ok={str(bool(result['ok'])).lower()}",
            f"ready_for_real_llm={str(bool(result['ready_for_real_llm'])).lower()}",
            f"llm_readiness_status={_safe_token(str(result['llm_readiness_status']))}",
            f"llm_next_action={_safe_token(str(result['llm_next_action']))}",
            (
                "llm_readiness_reasons="
                f"{_format_list_field(result.get('llm_readiness_reasons', []))}"
            ),
            f"llm_fix_hints={_format_list_field(result.get('llm_fix_hints', []))}",
            f"provider={_safe_token(str(result['provider']))}",
            f"model={_safe_token(str(result['model']))}",
            f"endpoint_url={_safe_token(str(result['endpoint_url']))}",
            f"api_key={_safe_token(str(result['api_key']))}",
            f"error_kind={_safe_token(str(result['error_kind']))}",
            f"diagnostic_temperature={_safe_number(result['diagnostic_temperature'])}",
            f"diagnostic_max_tokens={_safe_int(result['diagnostic_max_tokens'])}",
            f"timeout_seconds={_safe_number(result['timeout_seconds'])}",
            f"reply_preview_chars={_safe_int(result['reply_preview_chars'])}",
            f"usage_total_tokens={_safe_int(result['usage_total_tokens'])}",
            f"llm_finish_reason={_safe_token(str(result['llm_finish_reason']))}",
            f"public_message={_safe_message(str(result['public_message']))}",
        ]
    )


def _format_llm_setup_diagnostic(result: dict[str, object]) -> str:
    return "\n".join(
        [
            "LLM 接入清单：",
            (
                "说明：仅管理员可用；只读检查真实 LLM 接入步骤，不写 .env，"
                "不调用真实 LLM，不连接 NapCat，不发送 QQ，不展示密钥、路径、prompt 或人格正文。"
            ),
            f"ok={str(bool(result['ok'])).lower()}",
            f"llm_setup_status={_safe_token(str(result['llm_setup_status']))}",
            f"ready_for_real_llm={str(bool(result['ready_for_real_llm'])).lower()}",
            (
                "llm_readiness_status="
                f"{_safe_token(str(result['llm_readiness_status']))}"
            ),
            f"llm_next_action={_safe_token(str(result['llm_next_action']))}",
            (
                "llm_readiness_reasons="
                f"{_format_list_field(result.get('llm_readiness_reasons', []))}"
            ),
            f"llm_fix_hints={_format_list_field(result.get('llm_fix_hints', []))}",
            f"required_env_keys={_format_list_field(result.get('required_env_keys', []))}",
            (
                "missing_or_placeholder_env_keys="
                f"{_format_list_field(result.get('missing_or_placeholder_env_keys', []))}"
            ),
            (
                "safe_env_template="
                f"{_format_semicolon_list(result.get('safe_env_template', []))}"
            ),
            f"next_commands={_format_semicolon_list(result.get('next_commands', []))}",
            f"manual_steps={_format_semicolon_list(result.get('manual_steps', []))}",
            (
                "real_llm_probe_performed="
                f"{str(bool(result['real_llm_probe_performed'])).lower()}"
            ),
            f"napcat_connected={str(bool(result['napcat_connected'])).lower()}",
            f"message_sent={str(bool(result['message_sent'])).lower()}",
            f"writes_env={str(bool(result['writes_env'])).lower()}",
            f"secrets_hidden={str(bool(result['secrets_hidden'])).lower()}",
            f"error_kind={_safe_token(str(result['error_kind']))}",
            f"public_message={_safe_message(str(result['public_message']))}",
        ]
    )


def _format_semicolon_list(value: object) -> str:
    if not isinstance(value, list):
        return "-"
    cleaned = [_safe_token(str(item)) for item in value if str(item).strip()]
    return ";".join(cleaned) if cleaned else "-"


def _format_persona_diagnostic(result: dict[str, object]) -> str:
    return "\n".join(
        [
            "人格自检：",
            (
                "说明：仅管理员可用；不调用 LLM，不连接 NapCat，不发送外部业务消息，"
                "不展示人格正文、知识正文、本机路径或密钥。"
            ),
            f"ok={str(bool(result['ok'])).lower()}",
            f"persona_status={_safe_token(str(result['persona_status']))}",
            f"persona_next_action={_safe_token(str(result['persona_next_action']))}",
            f"persona_profile_id={_safe_token(str(result['persona_profile_id']))}",
            f"persona_display_name={_safe_token(str(result['persona_display_name']))}",
            f"persona_version={_safe_token(str(result['persona_version']))}",
            f"persona_files={_safe_int(result['persona_files'])}",
            f"persona_missing={_safe_int(result['persona_missing'])}",
            f"persona_unsupported={_safe_int(result['persona_unsupported'])}",
            f"persona_readable={_safe_int(result['persona_readable'])}",
            f"persona_empty={_safe_int(result['persona_empty'])}",
            f"persona_unreadable={_safe_int(result['persona_unreadable'])}",
            f"persona_total_chars={_safe_int(result['persona_total_chars'])}",
            f"persona_meaningful_lines={_safe_int(result['persona_meaningful_lines'])}",
            (
                "persona_strength_status="
                f"{_safe_token(str(result['persona_strength_status']))}"
            ),
            f"persona_source_refs={_safe_csv(str(result['persona_source_refs']))}",
            f"knowledge_source_refs={_safe_csv(str(result['knowledge_source_refs']))}",
            f"knowledge_files={_safe_int(result['knowledge_files'])}",
            f"knowledge_readable={_safe_int(result['knowledge_readable'])}",
            f"knowledge_chunks={_safe_int(result['knowledge_chunks'])}",
            f"style_rules={_safe_int(result['style_rules'])}",
            f"role_boundaries={_safe_int(result['role_boundaries'])}",
            f"forbidden_behaviors={_safe_int(result['forbidden_behaviors'])}",
            f"tone_mode={_safe_token(str(result['tone_mode']))}",
            f"tone_voice={_safe_token(str(result['tone_voice']))}",
            f"tone_warmth={_safe_number(result['tone_warmth'])}",
            f"tone_directness={_safe_number(result['tone_directness'])}",
            f"tone_message_count_limit={_safe_int(result['tone_message_count_limit'])}",
            f"memory_enabled={str(bool(result['memory_enabled'])).lower()}",
            f"history_enabled={str(bool(result['history_enabled'])).lower()}",
            f"emotion_enabled={str(bool(result['emotion_enabled'])).lower()}",
            f"errors={_format_list_field(result.get('errors', []))}",
            f"warnings={_format_list_field(result.get('warnings', []))}",
            (
                "llm_readiness_status="
                f"{_safe_token(str(result['llm_readiness_status']))}"
            ),
            f"llm_next_action={_safe_token(str(result['llm_next_action']))}",
            (
                "llm_readiness_reasons="
                f"{_format_list_field(result.get('llm_readiness_reasons', []))}"
            ),
            f"llm_fix_hints={_format_list_field(result.get('llm_fix_hints', []))}",
            (
                "real_llm_probe_performed="
                f"{str(bool(result['real_llm_probe_performed'])).lower()}"
            ),
            f"real_transport_used={str(bool(result['real_transport_used'])).lower()}",
            f"napcat_connected={str(bool(result['napcat_connected'])).lower()}",
            f"error_kind={_safe_token(str(result['error_kind']))}",
            f"public_message={_safe_message(str(result['public_message']))}",
        ]
    )


def _format_config_diagnostic(result: dict[str, object]) -> str:
    errors = _format_list_field(result.get("errors", []))
    warnings = _format_list_field(result.get("warnings", []))
    return "\n".join(
        [
            "配置体检：",
            "说明：仅管理员可用；不调用 LLM，不启动 NapCat，不发送外部消息，只展示安全摘要。",
            f"ok={str(bool(result['ok'])).lower()}",
            f"ready_for_real_llm={str(bool(result['ready_for_real_llm'])).lower()}",
            f"llm_readiness_status={_safe_token(str(result['llm_readiness_status']))}",
            f"llm_next_action={_safe_token(str(result['llm_next_action']))}",
            (
                "llm_readiness_reasons="
                f"{_format_list_field(result.get('llm_readiness_reasons', []))}"
            ),
            f"llm_fix_hints={_format_list_field(result.get('llm_fix_hints', []))}",
            f"errors={errors}",
            f"warnings={warnings}",
            f"error_count={_safe_int(result['error_count'])}",
            f"warning_count={_safe_int(result['warning_count'])}",
            f"runtime_enabled={str(bool(result['runtime_enabled'])).lower()}",
            f"chat_enabled={str(bool(result['chat_enabled'])).lower()}",
            f"persona_profile_id={_safe_token(str(result['persona_profile_id']))}",
            f"persona_display_name={_safe_token(str(result['persona_display_name']))}",
            f"persona_files={_safe_int(result['persona_files'])}",
            f"persona_missing={_safe_int(result['persona_missing'])}",
            f"persona_unsupported={_safe_int(result['persona_unsupported'])}",
            f"persona_readable={_safe_int(result['persona_readable'])}",
            f"persona_empty={_safe_int(result['persona_empty'])}",
            f"persona_unreadable={_safe_int(result['persona_unreadable'])}",
            f"persona_total_chars={_safe_int(result['persona_total_chars'])}",
            f"persona_meaningful_lines={_safe_int(result['persona_meaningful_lines'])}",
            f"persona_strength_status={_safe_token(str(result['persona_strength_status']))}",
            f"knowledge_files={_safe_int(result['knowledge_files'])}",
            f"knowledge_missing={_safe_int(result['knowledge_missing'])}",
            f"knowledge_unsupported={_safe_int(result['knowledge_unsupported'])}",
            f"knowledge_readable={_safe_int(result['knowledge_readable'])}",
            f"knowledge_empty={_safe_int(result['knowledge_empty'])}",
            f"knowledge_unreadable={_safe_int(result['knowledge_unreadable'])}",
            f"knowledge_total_chars={_safe_int(result['knowledge_total_chars'])}",
            f"knowledge_meaningful_lines={_safe_int(result['knowledge_meaningful_lines'])}",
            f"memory_enabled={str(bool(result['memory_enabled'])).lower()}",
            f"history_enabled={str(bool(result['history_enabled'])).lower()}",
            f"history_max_items={_safe_int(result['history_max_items'])}",
            f"emotion_enabled={str(bool(result['emotion_enabled'])).lower()}",
            f"rate_limit_enabled={str(bool(result['rate_limit_enabled'])).lower()}",
            f"rate_limit_store={_safe_token(str(result['rate_limit_store']))}",
            f"rate_limit_db={_safe_token(str(result['rate_limit_db']))}",
            f"rate_limit_window_seconds={_safe_int(result['rate_limit_window_seconds'])}",
            (
                "rate_limit_chat_global_max_requests="
                f"{_safe_int(result['rate_limit_chat_global_max_requests'])}"
            ),
            (
                "rate_limit_chat_session_max_requests="
                f"{_safe_int(result['rate_limit_chat_session_max_requests'])}"
            ),
            (
                "rate_limit_chat_sender_max_requests="
                f"{_safe_int(result['rate_limit_chat_sender_max_requests'])}"
            ),
            (
                "rate_limit_target_min_interval_seconds="
                f"{_safe_int(result['rate_limit_target_min_interval_seconds'])}"
            ),
            f"rate_limit_bypass_roles={_safe_csv(str(result['rate_limit_bypass_roles']))}",
            f"quiet_hours_enabled={str(bool(result['quiet_hours_enabled'])).lower()}",
            f"quiet_hours_start={_safe_token(str(result['quiet_hours_start']))}",
            f"quiet_hours_end={_safe_token(str(result['quiet_hours_end']))}",
            f"quiet_hours_timezone={_safe_token(str(result['quiet_hours_timezone']))}",
            f"quiet_hours_session_types={_safe_csv(str(result['quiet_hours_session_types']))}",
            f"quiet_hours_bypass_roles={_safe_csv(str(result['quiet_hours_bypass_roles']))}",
            f"diagnostics_enabled={str(bool(result['diagnostics_enabled'])).lower()}",
            f"audit_enabled={str(bool(result['audit_enabled'])).lower()}",
            f"receipts_enabled={str(bool(result['receipts_enabled'])).lower()}",
            f"send_queue_enabled={str(bool(result['send_queue_enabled'])).lower()}",
            f"send_queue_store={_safe_token(str(result['send_queue_store']))}",
            f"send_queue_db={_safe_token(str(result['send_queue_db']))}",
            f"send_queue_max_items={_safe_int(result['send_queue_max_items'])}",
            f"send_queue_max_attempts={_safe_int(result['send_queue_max_attempts'])}",
            (
                "send_queue_retry_base_seconds="
                f"{_safe_int(result['send_queue_retry_base_seconds'])}"
            ),
            (
                "send_queue_retry_max_seconds="
                f"{_safe_int(result['send_queue_retry_max_seconds'])}"
            ),
            (
                "send_queue_worker_enabled="
                f"{str(bool(result['send_queue_worker_enabled'])).lower()}"
            ),
            (
                "send_queue_worker_interval_seconds="
                f"{_safe_int(result['send_queue_worker_interval_seconds'])}"
            ),
            (
                "send_queue_worker_batch_size="
                f"{_safe_int(result['send_queue_worker_batch_size'])}"
            ),
            f"chat_provider={_safe_token(str(result['chat_provider']))}",
            f"chat_model={_safe_token(str(result['chat_model']))}",
            f"chat_api_key={_safe_token(str(result['chat_api_key']))}",
            f"endpoint_url={_safe_token(str(result['endpoint_url']))}",
            f"chat_temperature={_safe_number(result['chat_temperature'])}",
            f"chat_max_tokens={_safe_int(result['chat_max_tokens'])}",
            f"timeout_seconds={_safe_number(result['timeout_seconds'])}",
            f"public_message={_safe_message(str(result['public_message']))}",
        ]
    )


def _format_context_summary(
    *,
    config: Config,
    context: ContextBundle,
    prompt_messages: list[dict[str, str]],
    prompt_diagnostics: ChatPromptDiagnostics,
    reply_budget_reason: str,
    risk_level: RiskLevel,
) -> str:
    persona = context.persona
    knowledge_chunks = context.knowledge_results.chunks
    knowledge_sources = {chunk.source_id for chunk in knowledge_chunks}
    source_summary = build_safe_context_source_summary(config, context)
    emotion_labels = ",".join(
        signal.emotion_label for signal in context.emotion_signals
    ) or "-"
    system_prompt = prompt_messages[0]["content"] if prompt_messages else ""
    user_prompt = prompt_messages[1]["content"] if len(prompt_messages) > 1 else ""
    lines = [
        "上下文诊断：",
        "说明：不调用 LLM，不发送外部消息；只展示安全摘要。",
        f"persona_profile_id={_safe_token(persona.profile_id)}",
        f"persona_display_name={_safe_token(persona.display_name)}",
        f"persona_version={_safe_token(persona.version)}",
        f"persona_source_refs={_safe_csv(source_summary['persona_source_refs'])}",
        f"knowledge_source_refs={_safe_csv(source_summary['knowledge_source_refs'])}",
        f"style_rules={len(persona.style_rules)}",
        f"role_boundaries={len(persona.role_boundaries)}",
        f"forbidden_behaviors={len(persona.forbidden_behaviors)}",
        f"knowledge_chunks={len(knowledge_chunks)}",
        f"knowledge_sources={len(knowledge_sources)}",
        f"memory_facts={len(context.memory_results.facts)}",
        f"history_turns={len(context.conversation_history.turns)}",
        f"emotion_signals={len(context.emotion_signals)}",
        f"emotion_labels={_safe_token(emotion_labels)}",
        f"reply_budget_reason={_safe_token(reply_budget_reason)}",
        f"max_messages={context.tone.message_count_limit}",
        f"context_budget={context.context_budget}",
        f"risk_level={risk_level.value}",
        f"prompt_messages={len(prompt_messages)}",
        f"system_prompt_chars={len(system_prompt)}",
        f"prompt_original_user_chars={prompt_diagnostics.original_user_prompt_chars}",
        f"prompt_user_budget={prompt_diagnostics.user_prompt_budget}",
        f"user_prompt_chars={len(user_prompt)}",
        f"prompt_total_chars={prompt_diagnostics.total_prompt_chars}",
        f"prompt_budget_remaining={prompt_diagnostics.budget_remaining}",
        f"prompt_clipped={str(prompt_diagnostics.clipped_to_context_budget).lower()}",
        f"prompt_user_clipped={str(prompt_diagnostics.user_message_clipped).lower()}",
        f"prompt_truncated_sections={_safe_section_list(prompt_diagnostics.truncated_sections)}",
        f"prompt_section_budgets={_format_section_numbers(prompt_diagnostics.section_budgets)}",
        f"prompt_section_chars={_format_section_numbers(prompt_diagnostics.section_chars)}",
        f"chat_provider={_safe_token(config.bot_chat_provider)}",
        f"chat_model={_safe_token(config.bot_chat_model)}",
    ]
    return "\n".join(lines)


def _format_queue_diagnostic(summary: dict[str, int], config: Config) -> str:
    enabled = bool(config.bot_send_queue_enabled)
    store = "sqlite" if enabled and config.bot_send_queue_db_path else "memory"
    db_state = "set" if config.bot_send_queue_db_path else "missing"
    return "\n".join(
        [
            "发送队列：",
            "说明：仅管理员可用；只展示安全计数，不展示目标、正文、dedupe_key 或数据库真实路径。",
            f"enabled={str(enabled).lower()}",
            f"store={store}",
            f"db={db_state}",
            f"queued={_safe_int(summary.get('queued', 0))}",
            f"failed_retryable={_safe_int(summary.get('failed_retryable', 0))}",
            f"failed_final={_safe_int(summary.get('failed_final', 0))}",
            f"sent={_safe_int(summary.get('sent', 0))}",
            f"skipped={_safe_int(summary.get('skipped', 0))}",
            f"processing={_safe_int(summary.get('processing', 0))}",
            f"max_items={_safe_int(config.bot_send_queue_max_items)}",
            f"max_attempts={_safe_int(config.bot_send_queue_max_attempts)}",
            f"retry_base_seconds={_safe_int(config.bot_send_queue_retry_base_seconds)}",
            f"retry_max_seconds={_safe_int(config.bot_send_queue_retry_max_seconds)}",
        ]
    )


def _format_roles_diagnostic(config: Config) -> str:
    role_counts = build_role_settings(config).counts()
    admin_commands = ",".join(
        [
            "/bot why",
            "/bot receipt",
            "/bot audit",
            "/bot recent",
            "/bot queue",
            "/bot context",
            "/bot llm",
            "/bot setup llm",
            "/bot config",
            "/bot readiness",
            "/bot dialogue",
            "/bot roles",
            "/bot persona",
            "/bot history clear",
            "/bot pause",
            "/bot resume",
        ]
    )
    return "\n".join(
        [
            "权限规则：",
            "说明：仅管理员可用；不调用 LLM，不连接 NapCat，不发送外部业务消息，只展示规则和计数。",
            f"role_order={_safe_csv(','.join(ROLE_ORDER))}",
            f"admin_users={_safe_int(role_counts.get('admin', 0))}",
            f"enterprise_users={_safe_int(role_counts.get('enterprise', 0))}",
            f"trusted_users={_safe_int(role_counts.get('trusted', 0))}",
            f"blocked_users={_safe_int(role_counts.get('blocked', 0))}",
            "blocked_policy=policy_stage_block_before_llm",
            "user_role=default_role_for_all_senders",
            "admin_role=can_run_admin_diagnostics_and_bypass_default_rate_quiet_rules",
            "enterprise_role=reserved_for_future_high_trust_business_rules",
            "trusted_role=reserved_for_future_low_risk_bypass_or_feature_rules",
            f"rate_limit_bypass_roles={_safe_csv(','.join(config.bot_rate_limit_bypass_roles))}",
            f"quiet_hours_bypass_roles={_safe_csv(','.join(config.bot_quiet_hours_bypass_roles))}",
            f"group_command_prefix={_safe_token(config.bot_runtime_group_command_prefix)}",
            "id_input_formats=json_array,comma,semicolon",
            "role_source=BOT_ADMIN_USER_IDS,BOT_ENTERPRISE_USER_IDS,BOT_TRUSTED_USER_IDS,BOT_BLOCKED_USER_IDS",
            f"admin_commands={_safe_csv(admin_commands)}",
            "ids_hidden=true",
        ]
    )


def _format_runtime_control_state(
    runtime_control: RuntimeControlState,
    *,
    headline: str,
) -> str:
    return "\n".join(
        [
            headline,
            "说明：普通聊天、自动发送预览和非排障能力会被暂停；管理员诊断、status 和 resume 仍可用。",
            f"runtime_paused={str(runtime_control.paused).lower()}",
            f"reason={_safe_token(runtime_control.reason)}",
            f"updated_by={_safe_token(runtime_control.updated_by_state)}",
        ]
    )


def _format_receipt(receipt: DeliveryReceipt) -> str:
    lines = [
        "发送回执：",
        f"request_id={_safe_token(receipt.request_id)}",
        f"debug_id={_safe_token(receipt.debug_id)}",
        f"state={receipt.state.value}",
        f"transport={_safe_token(receipt.transport)}",
        f"retry_count={receipt.retry_count}",
        f"next_retry_at={receipt.next_retry_at.isoformat() if receipt.next_retry_at else 'none'}",
        f"public_message={_safe_message(receipt.public_message)}",
    ]
    return "\n".join(lines)


def _format_audit_records(query: str, records: list[AuditRecord]) -> str:
    lines = [f"审计事件：request_id={_safe_token(query)}"]
    for index, record in enumerate(records[:20], start=1):
        lines.append(
            "；".join(
                [
                    f"{index}. request_id={_safe_token(record.request_id)}",
                    f"stage={_safe_token(record.stage)}",
                    f"event={_safe_token(record.event)}",
                    f"severity={record.severity.value}",
                    f"public_message={_safe_message(record.public_message)}",
                ]
            )
        )
    if len(records) > 20:
        lines.append(f"还有 {len(records) - 20} 条未展示。")
    return "\n".join(lines)


def _format_recent_diagnostics(items: list[RuntimeDiagnostic]) -> str:
    if not items:
        return "最近运行诊断：无"
    lines = ["最近运行诊断："]
    for index, item in enumerate(items, start=1):
        lines.append(
            "；".join(
                [
                    f"{index}. request_id={_safe_token(item.request_id)}",
                    f"debug_id={_safe_token(item.debug_id)}",
                    f"capability={_safe_token(item.capability_id)}",
                    f"policy={_safe_token(item.policy_reason)}",
                    f"budget={_safe_token(item.reply_budget_reason or '-')}",
                    f"llm={_safe_token(item.llm_status)}",
                    f"llm_readiness={_safe_token(item.llm_readiness_status or '-')}",
                    (
                        "ready_for_real_llm="
                        f"{str(bool(item.ready_for_real_llm)).lower()}"
                    ),
                    (
                        "llm_reasons="
                        f"{_format_reason_codes(item.llm_readiness_reasons)}"
                    ),
                    f"diagnostic_tags={_format_diagnostic_tags(item.audit_tags)}",
                    f"receipt={_safe_token(item.receipt_state)}",
                ]
            )
        )
    return "\n".join(lines)


def _format_recent_receipts(items: list[DeliveryReceipt]) -> str:
    if not items:
        return "最近发送回执：无"
    lines = ["最近发送回执："]
    for index, item in enumerate(items, start=1):
        lines.append(
            "；".join(
                [
                    f"{index}. request_id={_safe_token(item.request_id)}",
                    f"debug_id={_safe_token(item.debug_id)}",
                    f"state={item.state.value}",
                    f"transport={_safe_token(item.transport)}",
                    f"retry_count={item.retry_count}",
                ]
            )
        )
    return "\n".join(lines)


def _format_recent_audits(items: list[AuditRecord]) -> str:
    if not items:
        return "最近审计事件：无"
    lines = ["最近审计事件："]
    for index, item in enumerate(items, start=1):
        lines.append(
            "；".join(
                [
                    f"{index}. request_id={_safe_token(item.request_id)}",
                    f"stage={_safe_token(item.stage)}",
                    f"event={_safe_token(item.event)}",
                    f"severity={item.severity.value}",
                    f"public_message={_safe_message(item.public_message, max_chars=120)}",
                ]
            )
        )
    return "\n".join(lines)


def _is_admin(actor_roles: list[str]) -> bool:
    return "admin" in {role.strip() for role in actor_roles}


def _safe_token(value: str) -> str:
    return _safe_message(value, max_chars=120)


def _safe_message(value: str, max_chars: int = 240) -> str:
    text = redact_private_debug(value).replace("\r", " ").replace("\n", " ").strip()
    for marker in (
        "provider_message_id",
        "target_id",
        "session_id",
        "private_debug",
    ):
        text = text.replace(marker, "[redacted_field]")
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 3]}..."


def _safe_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return 0


def _safe_number(value: object) -> str:
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, int):
        return str(max(0, value))
    if isinstance(value, float):
        if not math.isfinite(value):
            return "0"
        bounded = max(0.0, value)
        return str(int(bounded)) if bounded.is_integer() else str(bounded)
    if isinstance(value, str):
        stripped = value.strip()
        try:
            parsed = float(stripped)
        except ValueError:
            return "0"
        if not math.isfinite(parsed):
            return "0"
        bounded = max(0.0, parsed)
        return str(int(bounded)) if bounded.is_integer() else str(bounded)
    return "0"


def _format_list_field(value: object) -> str:
    if not isinstance(value, list):
        return "-"
    cleaned = [_safe_token(str(item)) for item in value if str(item).strip()]
    return ",".join(cleaned) if cleaned else "-"


def _format_reason_codes(value: object) -> str:
    if not isinstance(value, list):
        return "-"
    sensitive_literals = {
        "authorization",
        "bearer",
        "token",
        "cookie",
        "secret",
        "password",
    }
    cleaned: list[str] = []
    for item in value:
        token = str(item).strip().lower()
        if not token:
            continue
        if token in sensitive_literals:
            continue
        if not all(char.isascii() and (char.isalnum() or char == "_") for char in token):
            continue
        cleaned.append(_safe_token(token))
    return ",".join(cleaned) if cleaned else "-"


def _format_diagnostic_tags(value: object) -> str:
    if not isinstance(value, list):
        return "-"
    cleaned: list[str] = []
    for item in value:
        tag = str(item).strip().lower()
        if not _is_safe_diagnostic_tag(tag):
            continue
        cleaned.append(_safe_token(tag))
    return ",".join(cleaned) if cleaned else "-"


def _is_safe_diagnostic_tag(value: str) -> bool:
    if not value or len(value) > 120:
        return False
    if not all(
        char.isascii() and (char.isalnum() or char in {"_", ":", "-", "."})
        for char in value
    ):
        return False
    sensitive_segments = {"authorization", "bearer", "token", "cookie", "secret"}
    segments = [
        segment
        for chunk in value.replace("-", "_").replace(".", "_").split(":")
        for segment in chunk.split("_")
        if segment
    ]
    return not any(segment in sensitive_segments for segment in segments)


def _safe_csv(value: str) -> str:
    cleaned = [
        _safe_token(item.strip())
        for item in value.split(",")
        if item.strip()
    ]
    return ",".join(cleaned) if cleaned else "-"


def _safe_section_list(values: tuple[str, ...]) -> str:
    cleaned = [_safe_token(value) for value in values if value.strip()]
    return ",".join(cleaned) if cleaned else "-"


def _format_section_numbers(values: dict[str, int]) -> str:
    safe_items = [
        f"{_safe_token(str(key))}:{_safe_int(value)}"
        for key, value in sorted(values.items())
    ]
    return ",".join(safe_items) if safe_items else "-"


def _parse_limit(query: str) -> int:
    try:
        return min(20, max(1, int(query.strip() or "5")))
    except ValueError:
        return 5
