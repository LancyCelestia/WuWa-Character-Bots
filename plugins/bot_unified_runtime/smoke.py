from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger, redact_private_debug
from plugins.bot_unified_runtime.capabilities.chat import (
    build_chat_capability,
    build_chat_prompt_with_diagnostics,
)
from plugins.bot_unified_runtime.character import build_character_context_provider
from plugins.bot_unified_runtime.character.source_summary import (
    build_safe_context_source_summary,
)
from plugins.bot_unified_runtime.character.vector_knowledge import (
    OpenAICompatibleEmbeddingProvider,
    SqliteVectorKnowledgeStore,
)
from plugins.bot_unified_runtime.config import Config, translate_env_keys
from plugins.bot_unified_runtime.config_readiness import (
    diagnostic_llm_max_tokens,
    diagnostic_llm_temperature,
    llm_generation_parameter_errors,
    openai_compatible_preflight_errors,
    persona_context_preflight_errors,
    run_config_smoke,
    safe_openai_endpoint_url,
)
from plugins.bot_unified_runtime.config_readiness import (
    has_real_api_key as _has_real_api_key,
)
from plugins.bot_unified_runtime.contracts import (
    AuditRecord,
    DeliveryReceipt,
    IncomingMessage,
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    RiskLevel,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.diagnostics import (
    build_diagnostic_audit_tags,
    build_diagnostic_why_summary,
    infer_bool_tag,
    infer_history_skip_reason,
    infer_int_tag,
    infer_llm_error_kind,
    infer_llm_preflight_reasons,
    infer_prompt_truncated_sections,
    infer_quiet_hours_blocked,
    infer_rate_limit_blocked,
    infer_rate_limit_reason,
    infer_review_block_reason,
    infer_text_tag,
)
from plugins.bot_unified_runtime.llm import (
    LLMProvider,
    LLMProviderError,
    OpenAICompatibleLLMProvider,
    StaticLLMProvider,
    public_llm_error_message,
    safe_llm_finish_reason,
)
from plugins.bot_unified_runtime.llm.model_router import build_model_router
from plugins.bot_unified_runtime.policy import (
    PolicySettings,
    build_quiet_hours_checker,
    build_rate_limiter,
    build_reply_budget_settings,
    build_role_settings,
    decide_reply_budget,
    evaluate_policy,
)
from plugins.bot_unified_runtime.runtime import RuntimePipeline
from plugins.bot_unified_runtime.security import (
    InjectionCheckInput,
    check_prompt_injection,
)
from plugins.bot_unified_runtime.sender import (
    InMemoryReceiptRepository,
    InMemorySendQueue,
    SQLiteSendRequestQueue,
    drain_send_queue_once,
)
from plugins.bot_unified_runtime.sender.onebot import (
    build_onebot_message_segments,
    send_onebot_v11,
)

_STARTUP_SMOKE_PREFIX = "__BOT_STARTUP_SMOKE__"
_STARTUP_SMOKE_CHILD_CODE = r"""
from __future__ import annotations

import json
import sys

PREFIX = "__BOT_STARTUP_SMOKE__"

result = {
    "ok": False,
    "error_kind": "startup_failed",
    "nonebot_initialized": False,
    "onebot_adapter_registered": False,
    "plugin_loaded": False,
    "plugin_name": "",
    "onebot_supported": False,
    "matcher_count": 0,
    "matcher_priorities": {},
    "scheduler_access": "not_checked",
    "scheduler_jobs": [],
    "server_started": False,
    "napcat_connected": False,
    "real_transport_used": False,
}

try:
    import nonebot
    from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

    env_file = sys.argv[1] if len(sys.argv) > 1 else None
    init_kwargs = {
        "driver": "~fastapi",
        "host": "127.0.0.1",
        "port": 8088,
        "log_level": "ERROR",
    }
    if env_file:
        init_kwargs["_env_file"] = env_file

    nonebot.init(**init_kwargs)
    result["nonebot_initialized"] = True

    driver = nonebot.get_driver()
    driver.register_adapter(OneBotV11Adapter)
    result["onebot_adapter_registered"] = True

    plugin = nonebot.load_plugin("plugins.bot_unified_runtime")
    result["plugin_loaded"] = plugin is not None
    if plugin is not None and plugin.metadata is not None:
        result["plugin_name"] = str(getattr(plugin.metadata, "name", ""))
        supported_adapters = getattr(plugin.metadata, "supported_adapters", set())
        if isinstance(supported_adapters, (set, frozenset, list, tuple)):
            result["onebot_supported"] = "~onebot.v11" in {
                str(item) for item in supported_adapters
            }

    from nonebot.matcher import matchers

    result["matcher_priorities"] = {
        str(priority): len(matchers_at_priority)
        for priority, matchers_at_priority in matchers.items()
        if matchers_at_priority
    }
    result["matcher_count"] = sum(result["matcher_priorities"].values())

    try:
        from nonebot_plugin_apscheduler import scheduler

        result["scheduler_access"] = "ok"
        result["scheduler_jobs"] = [job.id for job in scheduler.get_jobs()]
    except Exception as exc:  # noqa: BLE001
        result["scheduler_access"] = "missing"
        result["scheduler_error_type"] = type(exc).__name__

    result["ok"] = (
        result["nonebot_initialized"]
        and result["onebot_adapter_registered"]
        and result["plugin_loaded"]
        and result["onebot_supported"]
        and result["matcher_count"] >= 3
    )
    result["error_kind"] = "none" if result["ok"] else "startup_incomplete"
except Exception as exc:  # noqa: BLE001
    result["error_kind"] = "startup_failed"
    result["error_type"] = type(exc).__name__
    result["error_message"] = str(exc)

print(PREFIX + json.dumps(result, ensure_ascii=False, sort_keys=True))
raise SystemExit(0 if result["ok"] else 1)
"""


def load_smoke_config(env_file: str | Path | None = None) -> Config:
    path = _resolve_smoke_env_file(env_file)
    values: dict[str, str] = {}
    if path.exists():
        for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip().lower()] = value.strip().strip('"').strip("'")
    # 注入进程环境（不覆盖已存在的变量），使模型注册表里的
    # env:BOT_API_KEY_* 引用在 smoke/控制台路径与 NoneBot dotenv 行为一致。
    import os

    for key, value in values.items():
        os.environ.setdefault(key.upper(), value)
    return Config.model_validate(translate_env_keys(values))


def _resolve_smoke_env_file(env_file: str | Path | None) -> Path:
    if env_file is not None:
        return Path(env_file)
    # 两级回退：先看当前工作目录（允许本地覆盖与测试注入），
    # 再看项目根（保证从任意目录运行都能找到配置）。
    cwd_dotenv = Path(".env")
    if cwd_dotenv.exists():
        return cwd_dotenv
    project_root = Path(__file__).resolve().parents[2]
    project_dotenv = project_root / ".env"
    if project_dotenv.exists():
        return project_dotenv
    return project_root / ".env.example"


def run_chat_smoke(
    config: Config,
    *,
    message_text: str = "你好，守岸人。",
    llm_provider: LLMProvider | None = None,
) -> dict[str, Any]:
    readiness = run_config_smoke(config)
    audit_logger = InMemoryAuditLogger()
    send_queue = InMemorySendQueue(audit_logger=audit_logger)
    pipeline = RuntimePipeline(
        send_queue=send_queue,
        audit_logger=audit_logger,
        reply_budget_settings=build_reply_budget_settings(config),
        role_settings=build_role_settings(config),
        group_command_prefix=config.bot_runtime_group_command_prefix,
        rate_limiter=build_rate_limiter(config),
        quiet_hours_checker=build_quiet_hours_checker(config),
    )
    provider = llm_provider or (
        OpenAICompatibleLLMProvider(
            api_key=config.bot_chat_api_key,
            model=config.bot_chat_model,
            base_url=config.bot_chat_base_url,
            timeout_seconds=config.bot_chat_timeout_seconds,
        )
        if config.bot_chat_provider == "openai_compatible"
        else StaticLLMProvider()
    )
    capability = build_chat_capability(
        character_provider=build_character_context_provider(config),
        llm_provider=provider,
        # 仅当由 config 自行构建真实 provider 时启用模型路由；
        # 测试注入的自定义 provider 与 static 离线配置保持原语义。
        model_router=(
            build_model_router(config)
            if llm_provider is None and config.bot_chat_provider == "openai_compatible"
            else None
        ),
        temperature=config.bot_chat_temperature,
        max_tokens=config.bot_chat_max_tokens,
        context_preflight_errors=persona_context_preflight_errors(config),
        llm_preflight_errors=llm_generation_parameter_errors(config),
        output_max_chars_per_message=config.bot_reply_max_chars_per_message,
    )
    message = IncomingMessage(
        platform="console",
        adapter="dev-smoke",
        bot_id="bot-smoke",
        session_id="private:smoke",
        session_type=SessionType.PRIVATE,
        sender_id="smoke-user",
        plain_text=message_text,
        raw_segments=[{"type": "text", "data": {"text": message_text}}],
        mentions_bot=True,
    )
    receipt = pipeline.handle(message, capability, capability_id="bot.chat")
    sent_request = next(
        (
            request
            for request in reversed(send_queue.sent_requests)
            if request.request_id == message.request_id
        ),
        None,
    )
    audit_events = [record.event for record in audit_logger.list_records(message.request_id)]
    audit_tags = sent_request.audit_tags if sent_request else []
    llm_status = "ok"
    if config.bot_chat_provider == "static":
        llm_status = "not_configured"
    if "llm_error" in audit_tags:
        llm_status = "error"
    llm_error_kind = infer_llm_error_kind(audit_tags)
    llm_finish_reason = infer_text_tag(audit_tags, "llm_finish_reason")
    routed_model = next(
        (
            tag.removeprefix("model:").strip()
            for tag in audit_tags
            if tag.startswith("model:")
        ),
        "",
    )

    return {
        "request_id": message.request_id,
        "receipt_state": receipt.state.value,
        "receipt_message": receipt.public_message,
        "capability_id": sent_request.capability_id if sent_request else "bot.chat",
        "persona_profile_id": sent_request.persona_profile_id if sent_request else "",
        "reply_text": sent_request.content.text_fallback if sent_request else "",
        "reply_preview_chars": len(
            (sent_request.content.text_fallback if sent_request else "")[:120]
        ),
        "reply_text_hidden": True,
        "audit_events": audit_events,
        "audit_tags": audit_tags,
        "llm_status": llm_status,
        "llm_error_kind": llm_error_kind,
        "llm_finish_reason": llm_finish_reason,
        "llm_provider": config.bot_chat_provider,
        "llm_model": routed_model or config.bot_chat_model,
        "ready_for_real_llm": readiness["ready_for_real_llm"],
        "llm_readiness_status": readiness["llm_readiness_status"],
        "llm_readiness_reasons": readiness["llm_readiness_reasons"],
        "llm_fix_hints": readiness["llm_fix_hints"],
        "llm_next_action": readiness["llm_next_action"],
        "debug_id": receipt.debug_id,
    }


def chat_smoke_exit_code(config: Config, result: dict[str, Any]) -> int:
    if (
        config.bot_chat_provider == "openai_compatible"
        and result.get("llm_status") == "error"
    ):
        return 1
    return 0


def run_dialogue_smoke(
    config: Config,
    *,
    message_text: str = "你好，守岸人。",
    llm_provider: LLMProvider | None = None,
) -> dict[str, Any]:
    config_result = run_config_smoke(config)
    context_result = run_context_smoke(config, message_text=message_text)
    if config_result["llm_readiness_status"] == "blocked":
        return _build_dialogue_result(
            config=config,
            config_result=config_result,
            context_result=context_result,
            chat_result=_dialogue_not_called_chat_result(config),
            chat_pipeline_ok=False,
            dialogue_status="blocked",
            next_action="fix_config",
            ok=False,
        )

    chat_result = run_chat_smoke(
        config,
        message_text=message_text,
        llm_provider=llm_provider,
    )
    chat_pipeline_ok = (
        chat_result["receipt_state"] == ReceiptState.SENT.value
        and chat_result["capability_id"] == "bot.chat"
    )
    real_provider_error = (
        config.bot_chat_provider == "openai_compatible"
        and chat_result["llm_status"] == "error"
    )
    ok = bool(context_result["ok"]) and chat_pipeline_ok and not real_provider_error
    next_action = _dialogue_next_action(
        context_ok=bool(context_result["ok"]),
        chat_pipeline_ok=chat_pipeline_ok,
        real_provider_error=real_provider_error,
        ready_for_real_llm=bool(config_result["ready_for_real_llm"]),
    )
    if not ok:
        dialogue_status = "blocked"
    elif config_result["ready_for_real_llm"] and chat_result["llm_status"] == "ok":
        dialogue_status = "ready"
    else:
        dialogue_status = "local_only"

    return _build_dialogue_result(
        config=config,
        config_result=config_result,
        context_result=context_result,
        chat_result=chat_result,
        chat_pipeline_ok=chat_pipeline_ok,
        dialogue_status=dialogue_status,
        next_action=next_action,
        ok=ok,
    )


def _dialogue_not_called_chat_result(config: Config) -> dict[str, Any]:
    return {
        "receipt_state": "not_created",
        "capability_id": "bot.chat",
        "reply_preview_chars": 0,
        "llm_status": "not_called",
        "llm_error_kind": "config_missing",
        "llm_finish_reason": "",
        "llm_provider": config.bot_chat_provider,
        "llm_model": config.bot_chat_model,
        "audit_tags": [],
        "audit_events": [],
    }


def _build_dialogue_result(
    *,
    config: Config,
    config_result: dict[str, Any],
    context_result: dict[str, Any],
    chat_result: dict[str, Any],
    chat_pipeline_ok: bool,
    dialogue_status: str,
    next_action: str,
    ok: bool,
) -> dict[str, Any]:
    return {
        "ok": ok,
        "dialogue_status": dialogue_status,
        "next_action": next_action,
        "error_kind": "none" if ok else next_action,
        "public_message": _dialogue_public_message(
            dialogue_status=dialogue_status,
            next_action=next_action,
        ),
        "context_ok": bool(context_result["ok"]),
        "context_error_kind": context_result["error_kind"],
        "persona_profile_id": context_result["persona_profile_id"],
        "persona_display_name": context_result["persona_display_name"],
        "persona_source_refs": context_result["persona_source_refs"],
        "knowledge_source_refs": context_result["knowledge_source_refs"],
        "knowledge_chunks": context_result["knowledge_chunks"],
        "memory_facts": context_result["memory_facts"],
        "history_turns": context_result["history_turns"],
        "emotion_signals": context_result["emotion_signals"],
        "emotion_labels": context_result["emotion_labels"],
        "prompt_messages": context_result["prompt_messages"],
        "prompt_total_chars": context_result["prompt_total_chars"],
        "prompt_budget_remaining": context_result["prompt_budget_remaining"],
        "prompt_clipped": context_result["prompt_clipped"],
        "prompt_user_clipped": context_result["prompt_user_clipped"],
        "prompt_truncated_sections": context_result["prompt_truncated_sections"],
        "context_budget": context_result["context_budget"],
        "max_messages": context_result["max_messages"],
        "risk_level": context_result["risk_level"],
        "chat_pipeline_ok": chat_pipeline_ok,
        "receipt_state": chat_result["receipt_state"],
        "capability_id": chat_result["capability_id"],
        "reply_preview_chars": chat_result["reply_preview_chars"],
        "reply_text_hidden": True,
        "llm_status": chat_result["llm_status"],
        "llm_error_kind": chat_result["llm_error_kind"],
        "llm_finish_reason": chat_result["llm_finish_reason"],
        "llm_provider": chat_result["llm_provider"],
        "llm_model": chat_result["llm_model"],
        "ready_for_real_llm": config_result["ready_for_real_llm"],
        "llm_readiness_status": config_result["llm_readiness_status"],
        "llm_next_action": config_result["llm_next_action"],
        "llm_readiness_reasons": config_result["llm_readiness_reasons"],
        "llm_fix_hints": config_result["llm_fix_hints"],
        "audit_tags": chat_result["audit_tags"],
        "audit_events": chat_result["audit_events"],
        "real_transport_used": False,
        "napcat_connected": False,
    }


def _dialogue_next_action(
    *,
    context_ok: bool,
    chat_pipeline_ok: bool,
    real_provider_error: bool,
    ready_for_real_llm: bool,
) -> str:
    if not context_ok:
        return "fix_context"
    if not chat_pipeline_ok:
        return "fix_chat_pipeline"
    if real_provider_error:
        return "fix_llm_provider"
    if not ready_for_real_llm:
        return "configure_real_llm"
    return "nonebot_smoke"


def _dialogue_public_message(*, dialogue_status: str, next_action: str) -> str:
    if dialogue_status == "ready":
        return "对话验收通过：人格上下文、真实 LLM 回复和本地发送链路均可用，下一步跑 nonebot-smoke。"
    if dialogue_status == "local_only":
        return "对话验收通过：本地人格对话链路可用，下一步配置真实 LLM。"
    if next_action == "fix_context":
        return "对话验收未通过：请先修复人格、记忆、知识或 prompt 上下文构造。"
    if next_action == "fix_chat_pipeline":
        return "对话验收未通过：请先修复基础聊天 pipeline。"
    if next_action == "fix_llm_provider":
        return "对话验收未通过：真实 LLM 调用失败，请先查看 llm_error_kind 并运行 llm-smoke。"
    return "对话验收未通过：请按 next_action 继续排障。"


def dialogue_smoke_exit_code(config: Config, result: dict[str, Any]) -> int:
    if (
        config.bot_chat_provider == "openai_compatible"
        and result.get("llm_status") == "error"
    ):
        return 1
    return 0 if result.get("ok") else 1


def run_why_smoke(
    config: Config,
    *,
    message_text: str = "你好，守岸人。",
    session_type: SessionType = SessionType.PRIVATE,
    mentions_bot: bool = True,
    sender_id: str = "smoke-user",
    group_id: str | None = None,
    llm_provider: LLMProvider | None = None,
) -> dict[str, Any]:
    readiness = run_config_smoke(config)
    capability_id = "bot.chat"
    audit_logger = InMemoryAuditLogger()
    send_queue = InMemorySendQueue(audit_logger=audit_logger)
    reply_budget_settings = build_reply_budget_settings(config)
    role_settings = build_role_settings(config)
    pipeline = RuntimePipeline(
        send_queue=send_queue,
        audit_logger=audit_logger,
        reply_budget_settings=reply_budget_settings,
        role_settings=role_settings,
        group_command_prefix=config.bot_runtime_group_command_prefix,
        runtime_enabled=config.bot_runtime_enabled,
        rate_limiter=build_rate_limiter(config),
        quiet_hours_checker=build_quiet_hours_checker(config),
    )
    provider = llm_provider or _build_llm_provider(config)
    capability = build_chat_capability(
        character_provider=build_character_context_provider(config),
        llm_provider=provider,
        temperature=config.bot_chat_temperature,
        max_tokens=config.bot_chat_max_tokens,
        context_preflight_errors=persona_context_preflight_errors(config),
        llm_preflight_errors=llm_generation_parameter_errors(config),
        output_max_chars_per_message=config.bot_reply_max_chars_per_message,
    )
    session_id = (
        f"group:{group_id or 'smoke-group'}"
        if session_type is SessionType.GROUP
        else "private:smoke"
    )
    message = IncomingMessage(
        platform="console",
        adapter="dev-smoke",
        bot_id="bot-smoke",
        session_id=session_id,
        session_type=session_type,
        sender_id=sender_id,
        group_id=group_id,
        plain_text=message_text,
        raw_segments=[{"type": "text", "data": {"text": message_text}}],
        mentions_bot=mentions_bot,
    )
    message = message.model_copy(
        update={"sender_roles": role_settings.resolve_roles(message)}
    )
    policy = evaluate_policy(
        message,
        capability_id,
        settings=PolicySettings(
            group_command_prefix=config.bot_runtime_group_command_prefix
        ),
    )
    reply_budget = (
        decide_reply_budget(message, capability_id, settings=reply_budget_settings)
        if policy.allowed and config.bot_runtime_enabled
        else None
    )
    receipt = pipeline.handle(message, capability, capability_id=capability_id)
    sent_request = next(
        (
            request
            for request in reversed(send_queue.sent_requests)
            if request.request_id == message.request_id
        ),
        None,
    )
    audit_records = audit_logger.list_records(message.request_id)
    if sent_request and _why_smoke_should_record_history_skip(sent_request):
        audit_logger.append(
            AuditRecord(
                request_id=message.request_id,
                session_id=message.session_id,
                capability_id=sent_request.capability_id,
                stage="history",
                event="history_record_skipped",
                severity=RiskLevel.MEDIUM,
                public_message="对话历史未记录：输入含提示注入风险。",
                private_debug="reason=prompt_injection",
            )
        )
        audit_records = audit_logger.list_records(message.request_id)
    audit_events = [record.event for record in audit_records]
    audit_tags = build_diagnostic_audit_tags(
        policy_audit_tags=policy.audit_tags,
        send_request=sent_request,
        audit_records=audit_records,
    )
    rate_limit_blocked = infer_rate_limit_blocked(audit_records)
    rate_limit_reason = infer_rate_limit_reason(audit_records)
    quiet_hours_blocked = infer_quiet_hours_blocked(audit_records)
    effective_policy_allowed = (
        policy.allowed
        and config.bot_runtime_enabled
        and not rate_limit_blocked
        and not quiet_hours_blocked
    )
    effective_policy_reason = policy.reason
    if not config.bot_runtime_enabled:
        effective_policy_reason = "runtime_disabled"
    elif rate_limit_blocked:
        effective_policy_reason = "rate_limited"
    elif quiet_hours_blocked:
        effective_policy_reason = "quiet_hours"
        reply_budget = None
    llm_status = "not_run"
    if sent_request:
        llm_status = "not_configured" if config.bot_chat_provider == "static" else "ok"
        if "llm_error" in sent_request.audit_tags:
            llm_status = "error"

    max_messages = reply_budget.max_messages if reply_budget else 0
    context_budget = reply_budget.context_budget if reply_budget else 0
    reply_budget_reason = reply_budget.reason if reply_budget else ""
    llm_error_kind = infer_llm_error_kind(audit_tags)
    llm_finish_reason = infer_text_tag(audit_tags, "llm_finish_reason")
    llm_preflight_reasons = infer_llm_preflight_reasons(audit_tags)
    prompt_truncated_sections = infer_prompt_truncated_sections(audit_tags)
    prompt_user_clipped = infer_bool_tag(audit_tags, "prompt_user_clipped")
    history_skip_reason = infer_history_skip_reason(audit_records)
    why_summary = build_diagnostic_why_summary(
        runtime_enabled=config.bot_runtime_enabled,
        policy_allowed=effective_policy_allowed,
        policy_reason=effective_policy_reason,
        session_type=session_type,
        mentions_bot=mentions_bot,
        group_command_prefix=config.bot_runtime_group_command_prefix,
        max_messages=max_messages,
        reply_budget_reason=reply_budget_reason,
        send_request_created=sent_request is not None,
        receipt_state=receipt.state.value,
        review_block_reason=infer_review_block_reason(audit_records),
        output_trimmed="llm_output_trimmed" in audit_tags,
        llm_error_kind=llm_error_kind,
        llm_preflight_reasons=llm_preflight_reasons,
        rate_limit_reason=rate_limit_reason,
        prompt_user_clipped=prompt_user_clipped,
        history_skip_reason=history_skip_reason,
    )

    return {
        "ok": True,
        "request_id": message.request_id,
        "debug_id": receipt.debug_id,
        "capability_id": capability_id,
        "session_type": message.session_type.value,
        "mentions_bot": message.mentions_bot,
        "policy_allowed": effective_policy_allowed,
        "policy_reason": effective_policy_reason,
        "actor_roles": policy.actor_roles,
        "risk_level": policy.risk_level.value,
        "privacy_level": policy.privacy_level.value,
        "cooldown_key": policy.cooldown_key,
        "policy_audit_tags": policy.audit_tags,
        "reply_budget_reason": reply_budget_reason,
        "max_messages": max_messages,
        "context_budget": context_budget,
        "reply_budget_audit_tags": reply_budget.audit_tags if reply_budget else [],
        "prompt_messages": infer_int_tag(audit_tags, "prompt_messages"),
        "system_prompt_chars": infer_int_tag(audit_tags, "prompt_system_chars"),
        "user_prompt_chars": infer_int_tag(audit_tags, "prompt_user_chars"),
        "prompt_total_chars": infer_int_tag(audit_tags, "prompt_total_chars"),
        "prompt_budget_remaining": infer_int_tag(audit_tags, "prompt_budget_remaining"),
        "prompt_clipped": infer_bool_tag(audit_tags, "prompt_clipped"),
        "prompt_user_clipped": prompt_user_clipped,
        "prompt_truncated_sections": ",".join(prompt_truncated_sections),
        "knowledge_chunks": infer_int_tag(audit_tags, "context_knowledge_chunks"),
        "memory_facts": infer_int_tag(audit_tags, "context_memory_facts"),
        "history_turns": infer_int_tag(audit_tags, "context_history_turns"),
        "emotion_signals": infer_int_tag(audit_tags, "context_emotion_signals"),
        "llm_status": llm_status,
        "llm_error_kind": llm_error_kind,
        "llm_finish_reason": llm_finish_reason,
        "llm_provider": config.bot_chat_provider,
        "llm_model": config.bot_chat_model,
        "ready_for_real_llm": readiness["ready_for_real_llm"],
        "llm_readiness_status": readiness["llm_readiness_status"],
        "llm_readiness_reasons": readiness["llm_readiness_reasons"],
        "llm_fix_hints": readiness["llm_fix_hints"],
        "llm_next_action": readiness["llm_next_action"],
        "llm_usage_prompt_tokens": infer_int_tag(audit_tags, "llm_usage_prompt_tokens"),
        "llm_usage_completion_tokens": infer_int_tag(
            audit_tags,
            "llm_usage_completion_tokens",
        ),
        "llm_usage_total_tokens": infer_int_tag(audit_tags, "llm_usage_total_tokens"),
        "send_request_created": sent_request is not None,
        "receipt_state": receipt.state.value,
        "receipt_message": receipt.public_message,
        "audit_events": audit_events,
        "audit_tags": audit_tags,
        "why_summary": why_summary,
    }


def _why_smoke_should_record_history_skip(send_request: SendRequest) -> bool:
    return any(tag.startswith("prompt_injection") for tag in send_request.audit_tags)


def _build_why_summary(
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
) -> str:
    if not runtime_enabled:
        return "统一运行时已暂停，所以不会进入能力链路，也不会发送消息。"
    if not policy_allowed:
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
    if not send_request_created:
        return f"策略允许，但后续链路没有创建发送请求；最终回执为 {receipt_state}。"
    if reply_budget_reason:
        return (
            f"策略允许回复；回复预算原因是 {reply_budget_reason}，"
            f"最多回复 {max_messages} 条；已创建 SendRequest。"
        )
    mention_text = "已提及机器人" if mentions_bot else "未提及机器人"
    return f"策略允许回复，{mention_text}，已创建 SendRequest。"


def run_context_smoke(
    config: Config,
    *,
    message_text: str = "你好，守岸人。",
) -> dict[str, Any]:
    message = IncomingMessage(
        platform="console",
        adapter="dev-smoke",
        bot_id="bot-smoke",
        session_id="private:smoke",
        session_type=SessionType.PRIVATE,
        sender_id="smoke-user",
        plain_text=message_text,
        raw_segments=[{"type": "text", "data": {"text": message_text}}],
        mentions_bot=True,
    )
    try:
        injection_check = check_prompt_injection(
            InjectionCheckInput(
                request_id=message.request_id,
                source_type="user_message",
                plain_text=message.plain_text,
                target_stage="generation",
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
    except Exception as exc:  # noqa: BLE001 - local smoke must turn context errors into diagnostics.
        return {
            "ok": False,
            "error_kind": "context_error",
            "public_message": "上下文诊断失败：人格、知识、记忆或 prompt 构造出现错误。",
            "private_debug": _redact_smoke_debug(str(exc), config.bot_chat_api_key),
            "request_id": message.request_id,
            "persona_profile_id": config.bot_persona_profile_id,
            "persona_display_name": config.bot_persona_display_name,
            "persona_identity_preview": "",
            "persona_source_refs": "-",
            "knowledge_source_refs": "-",
            "style_rules": 0,
            "role_boundaries": 0,
            "forbidden_behaviors": 0,
            "knowledge_chunks": 0,
            "memory_facts": 0,
            "history_turns": 0,
            "emotion_signals": 0,
            "emotion_labels": "",
            "prompt_messages": 0,
            "system_prompt_chars": 0,
            "prompt_original_user_chars": 0,
            "prompt_user_budget": 0,
            "user_prompt_chars": 0,
            "prompt_total_chars": 0,
            "prompt_budget_remaining": 0,
            "prompt_clipped": False,
            "prompt_user_clipped": False,
            "prompt_truncated_sections": "",
            "prompt_section_budgets": {},
            "prompt_section_chars": {},
            "context_budget": 0,
            "max_messages": 0,
            "risk_level": message.risk_level.value,
            "system_prompt_preview": "",
        }

    system_prompt = prompt_messages[0]["content"] if prompt_messages else ""
    user_prompt = prompt_messages[1]["content"] if len(prompt_messages) > 1 else ""
    source_summary = build_safe_context_source_summary(config, context)
    return {
        "ok": True,
        "error_kind": "none",
        "public_message": "上下文诊断通过：已构造人格/记忆/知识/prompt 摘要，未调用 LLM，也未发送消息。",
        "private_debug": "",
        "request_id": message.request_id,
        "persona_profile_id": context.persona.profile_id,
        "persona_display_name": context.persona.display_name,
        "persona_identity_preview": context.persona.identity[:120],
        "persona_source_refs": source_summary["persona_source_refs"],
        "knowledge_source_refs": source_summary["knowledge_source_refs"],
        "style_rules": len(context.persona.style_rules),
        "role_boundaries": len(context.persona.role_boundaries),
        "forbidden_behaviors": len(context.persona.forbidden_behaviors),
        "knowledge_chunks": len(context.knowledge_results.chunks),
        "memory_facts": len(context.memory_results.facts),
        "history_turns": len(context.conversation_history.turns),
        "emotion_signals": len(context.emotion_signals),
        "emotion_labels": ",".join(
            signal.emotion_label for signal in context.emotion_signals
        ),
        "prompt_messages": len(prompt_messages),
        "system_prompt_chars": len(system_prompt),
        "prompt_original_user_chars": prompt_diagnostics.original_user_prompt_chars,
        "prompt_user_budget": prompt_diagnostics.user_prompt_budget,
        "user_prompt_chars": len(user_prompt),
        "prompt_total_chars": prompt_diagnostics.total_prompt_chars,
        "prompt_budget_remaining": prompt_diagnostics.budget_remaining,
        "prompt_clipped": prompt_diagnostics.clipped_to_context_budget,
        "prompt_user_clipped": prompt_diagnostics.user_message_clipped,
        "prompt_truncated_sections": ",".join(prompt_diagnostics.truncated_sections),
        "prompt_section_budgets": prompt_diagnostics.section_budgets,
        "prompt_section_chars": prompt_diagnostics.section_chars,
        "context_budget": context.context_budget,
        "max_messages": context.tone.message_count_limit,
        "risk_level": context.risk_level.value,
        "system_prompt_preview": "",
    }


def run_persona_smoke(config: Config) -> dict[str, Any]:
    config_result = run_config_smoke(config)
    persona_status = _persona_status_from_config(config_result)
    persona_next_action = _persona_next_action(persona_status)
    base_result: dict[str, Any] = {
        "ok": persona_status in {"ok", "weak"},
        "persona_status": persona_status,
        "persona_next_action": persona_next_action,
        "error_kind": "none" if persona_status in {"ok", "weak"} else persona_next_action,
        "public_message": _persona_public_message(persona_status),
        "persona_profile_id": config_result["persona_profile_id"],
        "persona_display_name": config_result["persona_display_name"],
        "persona_version": config.bot_persona_version,
        "persona_files": config_result["persona_files"],
        "persona_missing": config_result["persona_missing"],
        "persona_unsupported": config_result["persona_unsupported"],
        "persona_readable": config_result["persona_readable"],
        "persona_empty": config_result["persona_empty"],
        "persona_unreadable": config_result["persona_unreadable"],
        "persona_total_chars": config_result["persona_total_chars"],
        "persona_meaningful_lines": config_result["persona_meaningful_lines"],
        "persona_strength_status": config_result["persona_strength_status"],
        "persona_source_refs": "-",
        "knowledge_source_refs": "-",
        "knowledge_files": config_result["knowledge_files"],
        "knowledge_readable": config_result["knowledge_readable"],
        "knowledge_chunks": 0,
        "style_rules": 0,
        "role_boundaries": 0,
        "forbidden_behaviors": 0,
        "tone_mode": config.bot_tone_mode,
        "tone_voice": config.bot_tone_voice,
        "tone_warmth": config.bot_tone_warmth,
        "tone_directness": config.bot_tone_directness,
        "tone_message_count_limit": config.bot_tone_message_count_limit,
        "memory_enabled": config.bot_memory_enabled,
        "history_enabled": config.bot_history_enabled,
        "emotion_enabled": config.bot_emotion_enabled,
        "errors": config_result["errors"],
        "warnings": config_result["warnings"],
        "llm_readiness_status": config_result["llm_readiness_status"],
        "llm_next_action": config_result["llm_next_action"],
        "llm_readiness_reasons": config_result["llm_readiness_reasons"],
        "llm_fix_hints": config_result["llm_fix_hints"],
        "real_llm_probe_performed": False,
        "real_transport_used": False,
        "napcat_connected": False,
        "private_debug": "",
    }
    if persona_status == "blocked" or config_result["error_count"]:
        return base_result

    request_id = "persona-smoke"
    try:
        context = build_character_context_provider(config).build_context(
            request_id=request_id,
            sender_id="smoke-user",
            session_id="private:smoke",
            query_text="persona_smoke_probe",
            platform="console",
            adapter="dev-smoke",
            bot_id="bot-smoke",
        )
    except Exception as exc:  # noqa: BLE001 - persona smoke must stay safe and actionable.
        return {
            **base_result,
            "ok": False,
            "persona_status": "blocked",
            "persona_next_action": "fix_context_sources",
            "error_kind": "context_error",
            "public_message": "人格自检未通过：人格、知识、记忆或历史来源读取失败。",
            "private_debug": _redact_smoke_debug(str(exc), config.bot_chat_api_key),
        }

    source_summary = build_safe_context_source_summary(config, context)
    return {
        **base_result,
        "persona_source_refs": source_summary["persona_source_refs"],
        "knowledge_source_refs": source_summary["knowledge_source_refs"],
        "knowledge_chunks": len(context.knowledge_results.chunks),
        "style_rules": len(context.persona.style_rules),
        "role_boundaries": len(context.persona.role_boundaries),
        "forbidden_behaviors": len(context.persona.forbidden_behaviors),
        "tone_mode": context.tone.mode,
        "tone_voice": context.tone.voice,
        "tone_warmth": context.tone.warmth,
        "tone_directness": context.tone.directness,
        "tone_message_count_limit": context.tone.message_count_limit,
    }


def _persona_status_from_config(config_result: dict[str, Any]) -> str:
    persona_errors = {
        "persona_files_empty",
        "persona_file_missing",
        "persona_file_unsupported",
        "persona_file_unreadable",
        "persona_file_empty",
    }
    errors = set(config_result.get("errors", []))
    if errors & persona_errors:
        return "blocked"
    if config_result.get("persona_strength_status") == "weak":
        return "weak"
    return "ok"


def _persona_next_action(persona_status: str) -> str:
    if persona_status == "blocked":
        return "fix_persona_files"
    if persona_status == "weak":
        return "improve_persona_material"
    return "dialogue_smoke"


def _persona_public_message(persona_status: str) -> str:
    if persona_status == "ok":
        return "人格自检通过：人格材料、语气参数和安全来源摘要已就绪；未调用 LLM，也未发送消息。"
    if persona_status == "weak":
        return "人格自检通过但材料偏薄：建议补充身份、边界、语气和禁止行为后再接真实 LLM。"
    return "人格自检未通过：请先修复 BOT_PERSONA_FILES 指向的可读取人格材料。"


def _build_llm_provider(config: Config) -> LLMProvider:
    if config.bot_chat_provider == "openai_compatible":
        return OpenAICompatibleLLMProvider(
            api_key=config.bot_chat_api_key,
            model=config.bot_chat_model,
            base_url=config.bot_chat_base_url,
            timeout_seconds=config.bot_chat_timeout_seconds,
        )
    return StaticLLMProvider(model=config.bot_chat_model)


def _redact_smoke_debug(value: str, *secrets: str) -> str:
    redacted = redact_private_debug(value)
    redacted = re.sub(
        r"(?i)\b(api[_-]?key|authorization|bearer)\s*=\s*\S+",
        lambda match: f"{match.group(1)}=[redacted]",
        redacted,
    )
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[redacted]")
    return redacted


def _format_smoke_section_numbers(values: object) -> str:
    if not isinstance(values, dict):
        return ""
    items = [
        f"{key!s}:{int(value)}"
        for key, value in sorted(values.items())
        if isinstance(value, int)
    ]
    return ",".join(items)


def _queue_smoke_send_request(
    *,
    request_id: str,
    target_id: str,
    dedupe_key: str,
) -> SendRequest:
    text = "不应出现在 queue-smoke 摘要里的正文。"
    rendered = RenderedOutput(
        request_id=request_id,
        content_type="text",
        content_ref={"text": text},
        text_fallback=text,
        privacy_level=PrivacyLevel.PERSONAL,
    )
    return SendRequest(
        request_id=request_id,
        session_id=f"private:{target_id}",
        target_scope=SessionType.PRIVATE,
        target_id=target_id,
        origin_message_id="queue-smoke-origin",
        capability_id="bot.chat",
        content=rendered,
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key=dedupe_key,
        cooldown_key=f"bot.chat:private:{target_id}",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="shorekeeper",
        audit_tags=["policy", "queue_smoke"],
    )


def run_queue_smoke(
    config: Config,
    *,
    db_path: str | Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if db_path is None:
        with TemporaryDirectory(prefix="bot-queue-smoke-") as temp_dir:
            return run_queue_smoke(
                config,
                db_path=Path(temp_dir) / "send_queue.sqlite3",
                now=now,
            )

    current_time = now or datetime.now(UTC)
    audit_logger = InMemoryAuditLogger()
    receipt_repository = InMemoryReceiptRepository()
    queue = SQLiteSendRequestQueue(
        db_path,
        audit_logger=audit_logger,
        max_items=config.bot_send_queue_max_items,
        max_attempts=config.bot_send_queue_max_attempts,
        retry_base_seconds=config.bot_send_queue_retry_base_seconds,
        retry_max_seconds=config.bot_send_queue_retry_max_seconds,
    )
    success_request = _queue_smoke_send_request(
        request_id="queue_smoke_success",
        target_id="secret-target-success",
        dedupe_key="queue-smoke-success-dedupe",
    )
    retry_request = _queue_smoke_send_request(
        request_id="queue_smoke_retryable",
        target_id="secret-target-retryable",
        dedupe_key="queue-smoke-retryable-dedupe",
    )
    queue.submit(success_request, now=current_time)
    queue.submit(retry_request, now=current_time + timedelta(seconds=1))

    async def fake_transport(send_request: SendRequest) -> DeliveryReceipt:
        if send_request.request_id == success_request.request_id:
            return DeliveryReceipt(
                request_id=send_request.request_id,
                state=ReceiptState.SENT,
                transport="fake_transport",
                provider_message_id="queue-smoke-provider-message-id",
                public_message="fake sent",
            )
        return DeliveryReceipt(
            request_id=send_request.request_id,
            state=ReceiptState.FAILED_RETRYABLE,
            transport="fake_transport",
            public_message="fake retryable failure",
        )

    worker_result = asyncio.run(
        drain_send_queue_once(
            queue,
            fake_transport,
            receipt_repository=receipt_repository,
            audit_logger=audit_logger,
            now=current_time + timedelta(seconds=2),
            limit=20,
        )
    )
    summary = queue.safe_summary()
    return {
        "ok": True,
        "checked": worker_result.checked,
        "delivered": worker_result.delivered,
        "retryable_failed": worker_result.retryable_failed,
        "final_failed": worker_result.final_failed,
        "skipped": worker_result.skipped,
        "receipt_record_failed": worker_result.receipt_record_failed,
        "queued": summary[ReceiptState.QUEUED.value],
        "sent": summary[ReceiptState.SENT.value],
        "failed_retryable": summary[ReceiptState.FAILED_RETRYABLE.value],
        "failed_final": summary[ReceiptState.FAILED_FINAL.value],
        "skipped_in_queue": summary[ReceiptState.SKIPPED.value],
        "processing": summary.get("processing", 0),
        "receipts_recorded": len(receipt_repository.list_receipts()),
        "audit_events": len(audit_logger.list_records()),
        "transport": "fake_transport",
        "real_transport_used": False,
        "public_message": (
            "发送队列本地 worker 诊断通过：已使用临时 SQLite 队列和 fake transport，"
            "未连接 NapCat，也未发送真实 QQ 消息。"
        ),
    }


def _transport_smoke_send_request(
    *,
    request_id: str,
    target_scope: SessionType = SessionType.PRIVATE,
    target_id: str = "secret-target",
    content_type: str = "text",
    content_ref: dict[str, Any] | None = None,
    allow_forward: bool = False,
) -> SendRequest:
    text = "不应出现在 transport-smoke 摘要里的正文。"
    rendered = RenderedOutput(
        request_id=request_id,
        content_type=content_type,
        content_ref=content_ref or {"text": text},
        text_fallback=text,
        privacy_level=PrivacyLevel.PERSONAL,
    )
    return SendRequest(
        request_id=request_id,
        session_id=f"{target_scope.value}:{target_id}",
        target_scope=target_scope,
        target_id=target_id,
        origin_message_id="transport-smoke-origin",
        capability_id="bot.chat",
        content=rendered,
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key=f"transport-smoke:{request_id}",
        cooldown_key=f"bot.chat:{target_scope.value}",
        privacy_level=PrivacyLevel.PERSONAL,
        allow_forward=allow_forward,
        persona_profile_id="shorekeeper",
        audit_tags=["policy", "transport_smoke"],
    )


def run_transport_smoke(config: Config) -> dict[str, Any]:
    runtime_enabled = config.bot_runtime_enabled
    adapter_import = "missing"
    private_debug = ""
    try:
        importlib.import_module("plugins.bot_unified_runtime.sender.onebot")
        adapter_import = "ok"
    except Exception as exc:  # noqa: BLE001 - smoke must report dependency failures.
        private_debug = _redact_smoke_debug(str(exc), config.bot_chat_api_key)

    text_segments = build_onebot_message_segments(
        _transport_smoke_send_request(request_id="transport_smoke_text")
    )
    image_segments = build_onebot_message_segments(
        _transport_smoke_send_request(
            request_id="transport_smoke_image",
            content_type="image",
            content_ref={"file": "file:///safe-local-card.png"},
        )
    )
    json_segments = build_onebot_message_segments(
        _transport_smoke_send_request(
            request_id="transport_smoke_json",
            content_type="card",
            content_ref={"onebot_json": {"app": "demo", "desc": "card"}},
        )
    )
    mixed_segments = build_onebot_message_segments(
        _transport_smoke_send_request(
            request_id="transport_smoke_mixed",
            content_type="mixed",
            content_ref={
                "parts": [
                    {"type": "text", "text": "safe text part"},
                    {"type": "image", "file": "file:///safe-mixed-card.png"},
                    {"type": "card", "onebot_json": {"app": "demo"}},
                ]
            },
        )
    )
    fallback_segments = build_onebot_message_segments(
        _transport_smoke_send_request(
            request_id="transport_smoke_fallback",
            content_type="forward",
            content_ref={"nodes": [{"content": "unsupported"}]},
        )
    )

    class FakeOneBot:
        def __init__(self) -> None:
            self.private_calls = 0
            self.group_calls = 0
            self.group_forward_calls = 0
            self.next_private_response: dict[str, Any] | None = None

        async def send_private_msg(self, **_kwargs: Any) -> dict[str, Any]:
            self.private_calls += 1
            if self.next_private_response is not None:
                return self.next_private_response
            return {"message_id": "transport-smoke-provider-message-id-private"}

        async def send_group_msg(self, **_kwargs: Any) -> dict[str, str]:
            self.group_calls += 1
            return {"message_id": "transport-smoke-provider-message-id-group"}

        async def send_group_forward_msg(self, **_kwargs: Any) -> dict[str, Any]:
            self.group_forward_calls += 1
            return {
                "status": "ok",
                "retcode": 0,
                "data": {"message_id": "transport-smoke-provider-message-id-forward"},
            }

    fake_bot = FakeOneBot()
    private_receipt = asyncio.run(
        send_onebot_v11(
            fake_bot,
            _transport_smoke_send_request(
                request_id="transport_smoke_private",
                target_scope=SessionType.PRIVATE,
                target_id="secret-target-private",
            ),
        )
    )
    group_receipt = asyncio.run(
        send_onebot_v11(
            fake_bot,
            _transport_smoke_send_request(
                request_id="transport_smoke_group",
                target_scope=SessionType.GROUP,
                target_id="secret-target-group",
            ),
        )
    )
    forward_receipt = asyncio.run(
        send_onebot_v11(
            fake_bot,
            _transport_smoke_send_request(
                request_id="transport_smoke_forward",
                target_scope=SessionType.GROUP,
                target_id="secret-target-forward",
                content_type="forward",
                content_ref={
                    "messages": [
                        {
                            "type": "node",
                            "data": {
                                "name": "safe",
                                "uin": "10000",
                                "content": "safe forward smoke node",
                            },
                        }
                    ]
                },
                allow_forward=True,
            ),
        )
    )
    fake_bot.next_private_response = {
        "status": "failed",
        "retcode": 100,
        "message": "network timeout token=transport-smoke-secret",
    }
    retryable_receipt = asyncio.run(
        send_onebot_v11(
            fake_bot,
            _transport_smoke_send_request(
                request_id="transport_smoke_retryable_retcode",
                target_scope=SessionType.PRIVATE,
                target_id="secret-target-retryable",
            ),
        )
    )
    fake_bot.next_private_response = {
        "status": "failed",
        "retcode": 1403,
        "wording": "permission denied cookie=transport-smoke-secret",
    }
    final_receipt = asyncio.run(
        send_onebot_v11(
            fake_bot,
            _transport_smoke_send_request(
                request_id="transport_smoke_final_retcode",
                target_scope=SessionType.PRIVATE,
                target_id="secret-target-final",
            ),
        )
    )

    segment_text = text_segments == [
        {"type": "text", "data": {"text": "不应出现在 transport-smoke 摘要里的正文。"}}
    ]
    segment_image = len(image_segments) == 1 and image_segments[0]["type"] == "image"
    segment_json = len(json_segments) == 1 and json_segments[0]["type"] == "json"
    segment_mixed = [segment["type"] for segment in mixed_segments] == [
        "text",
        "image",
        "json",
    ]
    segment_fallback = (
        len(fallback_segments) == 1 and fallback_segments[0]["type"] == "text"
    )
    provider_message_id_recorded = bool(
        private_receipt.provider_message_id
        and group_receipt.provider_message_id
        and forward_receipt.provider_message_id
    )
    forward_api = (
        forward_receipt.state is ReceiptState.SENT
        and fake_bot.group_forward_calls == 1
    )
    retcode_classification = (
        retryable_receipt.state is ReceiptState.FAILED_RETRYABLE
        and final_receipt.state is ReceiptState.FAILED_FINAL
        and "transport-smoke-secret" not in retryable_receipt.public_message
        and "transport-smoke-secret" not in final_receipt.public_message
    )
    ok = (
        adapter_import == "ok"
        and segment_text
        and segment_image
        and segment_json
        and segment_mixed
        and segment_fallback
        and private_receipt.state is ReceiptState.SENT
        and group_receipt.state is ReceiptState.SENT
        and forward_api
        and fake_bot.private_calls == 3
        and fake_bot.group_calls == 1
        and provider_message_id_recorded
        and retcode_classification
    )

    return {
        "ok": ok,
        "error_kind": "none" if ok else "transport_smoke_failed",
        "transport_adapter_import": adapter_import,
        "segment_text": segment_text,
        "segment_image": segment_image,
        "segment_json": segment_json,
        "segment_mixed": segment_mixed,
        "segment_fallback": segment_fallback,
        "forward_api": forward_api,
        "private_receipt_state": private_receipt.state.value,
        "group_receipt_state": group_receipt.state.value,
        "forward_receipt_state": forward_receipt.state.value,
        "retryable_receipt_state": retryable_receipt.state.value,
        "final_receipt_state": final_receipt.state.value,
        "fake_private_calls": fake_bot.private_calls,
        "fake_group_calls": fake_bot.group_calls,
        "fake_group_forward_calls": fake_bot.group_forward_calls,
        "provider_message_id_recorded": provider_message_id_recorded,
        "retcode_classification": retcode_classification,
        "runtime_enabled": runtime_enabled,
        "server_started": False,
        "napcat_connected": False,
        "real_transport_used": False,
        "public_message": (
            "OneBot/NapCat transport 本地诊断通过：已验证 text/image/json/mixed/"
            "fallback 消息段、合并转发扩展 API、fake bot 投递边界和 retcode 失败分类；"
            "未连接 NapCat，也未发送真实 QQ 消息。"
            if ok
            else "OneBot/NapCat transport 本地诊断未通过：请检查依赖或消息段构建边界。"
        ),
        "private_debug": private_debug,
    }


def _default_online_bot_provider() -> Mapping[str, Any]:
    from nonebot import get_bots

    return get_bots()


def _iter_online_bots(raw_bots: object) -> list[Any]:
    if isinstance(raw_bots, Mapping):
        return list(raw_bots.values())
    if isinstance(raw_bots, (list, tuple, set, frozenset)):
        return list(raw_bots)
    if raw_bots is None:
        return []
    return [raw_bots]


def _is_onebot_send_capable(bot: object) -> bool:
    return callable(getattr(bot, "send_private_msg", None)) or callable(
        getattr(bot, "send_group_msg", None)
    )


def run_online_transport_smoke(
    config: Config,
    *,
    bot_provider: Callable[[], object] | None = None,
) -> dict[str, Any]:
    runtime_enabled = config.bot_runtime_enabled
    active_bot_provider = bot_provider or _default_online_bot_provider
    bot_provider_state = "ok"
    private_debug = ""

    try:
        bots = _iter_online_bots(active_bot_provider())
    except Exception as exc:  # noqa: BLE001 - smoke must explain runtime state.
        debug_text = str(exc)
        private_debug = _redact_smoke_debug(debug_text, config.bot_chat_api_key)
        if "NoneBot has not been initialized" in debug_text:
            bot_provider_state = "nonebot_not_initialized"
        elif isinstance(exc, ImportError):
            bot_provider_state = "dependency_missing"
        else:
            bot_provider_state = "provider_error"
        bots = []

    online_bots_count = len(bots)
    onebot_bots_count = sum(1 for bot in bots if _is_onebot_send_capable(bot))
    send_capable = onebot_bots_count > 0
    provider_ok = bot_provider_state in {"ok", "nonebot_not_initialized"}
    ok = provider_ok

    if send_capable:
        public_message = (
            "在线 transport 只读诊断完成：已发现具备 OneBot 风格发送方法的在线 bot；"
            "本诊断没有调用发送 API，也没有发送 QQ 消息。"
        )
    elif bot_provider_state == "nonebot_not_initialized":
        public_message = (
            "在线 transport 只读诊断完成：当前命令未处在已初始化的 NoneBot 运行态，"
            "所以没有在线 bot 可检查；本诊断没有连接 NapCat，也没有发送 QQ 消息。"
        )
    elif provider_ok:
        public_message = (
            "在线 transport 只读诊断完成：当前没有发现具备 OneBot 风格发送方法的在线 bot；"
            "本诊断没有调用发送 API，也没有发送 QQ 消息。"
        )
    else:
        public_message = (
            "在线 transport 只读诊断未完成：读取 NoneBot 在线 bot 状态失败，"
            "请先检查运行依赖或是否处在真实 NoneBot 运行态。"
        )

    return {
        "ok": ok,
        "error_kind": "none" if ok else bot_provider_state,
        "bot_provider_state": bot_provider_state,
        "online_bots_count": online_bots_count,
        "onebot_bots_count": onebot_bots_count,
        "send_capable": send_capable,
        "runtime_enabled": runtime_enabled,
        "server_started": False,
        "napcat_connected": False,
        "real_transport_used": False,
        "public_message": public_message,
        "private_debug": private_debug,
    }


def run_llm_smoke(
    config: Config,
    *,
    llm_provider: LLMProvider | None = None,
) -> dict[str, Any]:
    readiness = run_config_smoke(config)
    provider_name = config.bot_chat_provider
    model = config.bot_chat_model
    has_real_api_key = _has_real_api_key(config.bot_chat_api_key)
    api_key_state = "set" if has_real_api_key else "missing"
    endpoint_url = safe_openai_endpoint_url(config.bot_chat_base_url)

    base_result: dict[str, Any] = {
        "ok": False,
        "provider": provider_name,
        "model": model,
        "base_url": endpoint_url.removesuffix("/chat/completions"),
        "endpoint_url": endpoint_url,
        "api_key": api_key_state,
        "diagnostic_temperature": diagnostic_llm_temperature(config),
        "diagnostic_max_tokens": diagnostic_llm_max_tokens(config),
        "timeout_seconds": config.bot_chat_timeout_seconds,
        "ready_for_real_llm": readiness["ready_for_real_llm"],
        "llm_readiness_status": readiness["llm_readiness_status"],
        "llm_next_action": readiness["llm_next_action"],
        "llm_readiness_reasons": readiness["llm_readiness_reasons"],
        "llm_fix_hints": readiness["llm_fix_hints"],
        "error_kind": "",
        "public_message": "",
        "private_debug": "",
        "reply_preview": "",
        "usage": {},
        "llm_finish_reason": "",
    }

    if provider_name != "openai_compatible":
        return {
            **base_result,
            "error_kind": "provider_not_configured",
            "public_message": "LLM 诊断未执行：当前 provider 不是真实模型连接，请配置 BOT_CHAT_PROVIDER=openai_compatible。",
            "private_debug": f"bot_chat_provider={provider_name}",
        }

    provider_config_errors = openai_compatible_preflight_errors(config)
    if provider_config_errors:
        return {
            **base_result,
            "error_kind": "config_missing",
            "public_message": _format_llm_preflight_missing_message(
                provider_config_errors
            ),
            "private_debug": (
                "provider_config_errors=" + ",".join(provider_config_errors)
            ),
        }

    provider = llm_provider or _build_llm_provider(config)
    messages = [
        {
            "role": "system",
            "content": "你是本地 LLM 连接诊断请求。只需要用一句中文回复连接正常，不要请求工具，不要输出密钥。",
        },
        {
            "role": "user",
            "content": "请回复：诊断连接正常。",
        },
    ]

    try:
        reply = provider.generate(
            messages,
            model=model,
            temperature=diagnostic_llm_temperature(config),
            max_tokens=diagnostic_llm_max_tokens(config),
        )
    except LLMProviderError as exc:
        error_kind = exc.error_kind
        return {
            **base_result,
            "error_kind": error_kind,
            "public_message": public_llm_error_message(error_kind),
            "private_debug": _redact_smoke_debug(str(exc), config.bot_chat_api_key),
        }
    except Exception as exc:  # noqa: BLE001 - 诊断接口的非预期异常统一转为 provider_error 返回。
        return {
            **base_result,
            "error_kind": "provider_error",
            "public_message": public_llm_error_message("provider_error"),
            "private_debug": _redact_smoke_debug(repr(exc), config.bot_chat_api_key),
        }

    return {
        **base_result,
        "ok": True,
        "error_kind": "none",
        "public_message": "LLM 诊断通过。",
        "reply_preview": reply.text[:120],
        "usage": reply.raw_usage,
        "llm_finish_reason": safe_llm_finish_reason(
            reply.raw_usage.get("finish_reason")
        ),
    }


def run_llm_setup(config: Config) -> dict[str, Any]:
    readiness = run_config_smoke(config)
    llm_readiness_status = str(readiness["llm_readiness_status"])
    if llm_readiness_status == "ready":
        setup_status = "ready_for_probe"
    elif llm_readiness_status == "blocked":
        setup_status = "blocked"
    else:
        setup_status = "needs_env_edit"

    required_env_keys = [
        "BOT_CHAT_PROVIDER",
        "BOT_CHAT_MODEL",
        "BOT_CHAT_API_KEY",
        "BOT_CHAT_BASE_URL",
        "BOT_CHAT_TEMPERATURE",
        "BOT_CHAT_MAX_TOKENS",
        "BOT_CHAT_TIMEOUT_SECONDS",
    ]
    safe_env_template = [
        "BOT_CHAT_PROVIDER=openai_compatible",
        "BOT_CHAT_MODEL=<model_name>",
        "BOT_CHAT_API_KEY=<real_api_key>",
        "BOT_CHAT_BASE_URL=<openai_compatible_base_url>",
        "BOT_CHAT_TEMPERATURE=0.7",
        "BOT_CHAT_MAX_TOKENS=512",
        "BOT_CHAT_TIMEOUT_SECONDS=30",
    ]
    return {
        "ok": setup_status != "blocked",
        "llm_setup_status": setup_status,
        "ready_for_real_llm": readiness["ready_for_real_llm"],
        "llm_readiness_status": readiness["llm_readiness_status"],
        "llm_next_action": readiness["llm_next_action"],
        "llm_readiness_reasons": readiness["llm_readiness_reasons"],
        "llm_fix_hints": readiness["llm_fix_hints"],
        "required_env_keys": required_env_keys,
        "missing_or_placeholder_env_keys": _llm_setup_missing_env_keys(
            readiness["llm_readiness_reasons"]
        ),
        "safe_env_template": safe_env_template,
        "next_commands": _llm_setup_next_commands(setup_status),
        "manual_steps": _llm_setup_manual_steps(setup_status),
        "real_llm_probe_performed": False,
        "napcat_connected": False,
        "message_sent": False,
        "writes_env": False,
        "secrets_hidden": True,
        "public_message": _llm_setup_public_message(setup_status),
        "error_kind": "none" if setup_status != "blocked" else "fix_config",
    }


def _llm_setup_missing_env_keys(reasons: list[str]) -> list[str]:
    key_by_reason = {
        "provider_not_real": "BOT_CHAT_PROVIDER",
        "chat_provider_unsupported": "BOT_CHAT_PROVIDER",
        "openai_model_missing": "BOT_CHAT_MODEL",
        "openai_api_key_missing": "BOT_CHAT_API_KEY",
        "openai_base_url_missing": "BOT_CHAT_BASE_URL",
        "openai_base_url_invalid": "BOT_CHAT_BASE_URL",
        "openai_base_url_unsafe": "BOT_CHAT_BASE_URL",
        "openai_temperature_invalid": "BOT_CHAT_TEMPERATURE",
        "openai_max_tokens_invalid": "BOT_CHAT_MAX_TOKENS",
        "openai_timeout_seconds_invalid": "BOT_CHAT_TIMEOUT_SECONDS",
    }
    missing: list[str] = []
    seen: set[str] = set()
    for reason in reasons:
        key = key_by_reason.get(reason)
        if key is None or key in seen:
            continue
        seen.add(key)
        missing.append(key)
    return missing


def _llm_setup_next_commands(setup_status: str) -> list[str]:
    prefix = "powershell -ExecutionPolicy Bypass -File scripts/dev.ps1"
    if setup_status == "ready_for_probe":
        tasks = ["llm-smoke", "dialogue-smoke", "nonebot-smoke", "startup-smoke"]
    else:
        tasks = [
            "config-smoke",
            "persona-smoke",
            "llm-smoke",
            "dialogue-smoke",
            "nonebot-smoke",
        ]
    return [f"{prefix} {task}" for task in tasks]


def _llm_setup_manual_steps(setup_status: str) -> list[str]:
    if setup_status == "ready_for_probe":
        return [
            "确认当前 .env 已使用真实 OpenAI-compatible provider 配置。",
            "先运行 llm-smoke 做一次短连接诊断。",
            "再运行 dialogue-smoke 验证人格对话链路。",
        ]
    if setup_status == "blocked":
        return [
            "先按 llm_fix_hints 修复阻断配置。",
            "不要把 API key 写进聊天消息或文档正文。",
            "修复后重新运行 llm-setup 或 config-smoke。",
        ]
    return [
        "复制安全占位模板到 .env 并替换模型服务配置。",
        "API key 只放在 BOT_CHAT_API_KEY，不要放进 base_url。",
        "配置后先跑 config-smoke，再跑 llm-smoke。",
    ]


def _llm_setup_public_message(setup_status: str) -> str:
    if setup_status == "ready_for_probe":
        return "真实 LLM 配置看起来已具备；下一步先运行 llm-smoke 做短连接诊断。"
    if setup_status == "blocked":
        return "真实 LLM 接入被配置问题阻断；请先按 llm_fix_hints 修复。"
    return "真实 LLM 尚未接入；请按 safe_env_template 填写 .env 后再验证。"


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
    return f"LLM 诊断未执行：openai_compatible provider 配置不完整，缺少 {joined}。"


def _import_state(
    module_name: str,
    importer: Callable[[str], Any],
    *,
    api_key: str = "",
    allow_nonebot_not_initialized: bool = False,
) -> tuple[str, Any | None, str]:
    try:
        module = importer(module_name)
    except ValueError as exc:
        if allow_nonebot_not_initialized and "not been initialized" in str(exc):
            return "ok", None, ""
        return "missing", None, _redact_smoke_debug(str(exc), api_key)
    except Exception as exc:  # noqa: BLE001 - smoke diagnostics must report import failures.
        return "missing", None, _redact_smoke_debug(str(exc), api_key)
    return "ok", module, ""


def _missing_path_count(paths: list[str]) -> int:
    return sum(1 for item in paths if item and not Path(item).exists())


def run_nonebot_smoke(
    config: Config,
    *,
    importer: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    active_importer = importer or importlib.import_module
    debug_parts: list[str] = []

    nonebot_state, _, nonebot_debug = _import_state(
        "nonebot",
        active_importer,
        api_key=config.bot_chat_api_key,
    )
    if nonebot_debug:
        debug_parts.append(f"nonebot={nonebot_debug}")

    adapter_state, _, adapter_debug = _import_state(
        "nonebot.adapters.onebot.v11",
        active_importer,
        api_key=config.bot_chat_api_key,
    )
    if adapter_debug:
        debug_parts.append(f"onebot_adapter={adapter_debug}")

    plugin_state, plugin_module, plugin_debug = _import_state(
        "plugins.bot_unified_runtime",
        active_importer,
        api_key=config.bot_chat_api_key,
    )
    if plugin_debug:
        debug_parts.append(f"plugin={plugin_debug}")

    plugin_meta = getattr(plugin_module, "__plugin_meta__", None) if plugin_module else None
    plugin_name = str(getattr(plugin_meta, "name", "")) if plugin_meta else ""
    supported_adapters_value: object = (
        getattr(plugin_meta, "supported_adapters", set()) if plugin_meta else set()
    )
    if isinstance(supported_adapters_value, (set, frozenset, list, tuple)):
        supported_adapters = {str(item) for item in supported_adapters_value}
    else:
        supported_adapters = set()
    onebot_supported = "~onebot.v11" in supported_adapters

    dependency_ok = nonebot_state == "ok" and adapter_state == "ok" and plugin_state == "ok"
    ok = dependency_ok and onebot_supported
    if ok:
        error_kind = "none"
        public_message = "NoneBot 本地加载诊断通过。"
    elif not dependency_ok:
        error_kind = "dependency_missing"
        public_message = "NoneBot 本地加载诊断未通过：依赖或插件导入失败，请先检查安装环境。"
    else:
        error_kind = "plugin_metadata_invalid"
        public_message = "NoneBot 本地加载诊断未通过：插件 metadata 缺少 OneBot V11 支持声明。"

    readiness = run_config_smoke(config)
    return {
        "ok": ok,
        "error_kind": error_kind,
        "public_message": public_message,
        "private_debug": "; ".join(debug_parts),
        "nonebot_import": nonebot_state,
        "onebot_adapter_import": adapter_state,
        "plugin_import": plugin_state,
        "plugin_name": plugin_name,
        "onebot_supported": onebot_supported,
        "persona_profile_id": config.bot_persona_profile_id,
        "persona_display_name": config.bot_persona_display_name,
        "persona_files": len(config.bot_persona_files),
        "persona_missing": _missing_path_count(config.bot_persona_files),
        "knowledge_files": len(config.bot_knowledge_files),
        "knowledge_missing": _missing_path_count(config.bot_knowledge_files),
        "runtime_enabled": config.bot_runtime_enabled,
        "memory_enabled": config.bot_memory_enabled,
        "memory_db": "set" if config.bot_memory_db_path else "missing",
        "history_enabled": config.bot_history_enabled,
        "history_db": "set" if config.bot_history_db_path else "missing",
        "history_max_turns": config.bot_history_max_turns,
        "history_max_items": config.bot_history_max_items,
        "diagnostics_enabled": config.bot_diagnostics_enabled,
        "diagnostics_db": "set" if config.bot_diagnostics_db_path else "missing",
        "diagnostics_max_items": config.bot_diagnostics_max_items,
        "audit_enabled": config.bot_audit_enabled,
        "audit_store": "sqlite"
        if config.bot_audit_enabled and config.bot_audit_db_path
        else "memory",
        "audit_db": "set" if config.bot_audit_db_path else "missing",
        "audit_max_items": config.bot_audit_max_items,
        "receipts_enabled": config.bot_receipts_enabled,
        "receipts_store": "sqlite"
        if config.bot_receipts_enabled and config.bot_receipts_db_path
        else "memory",
        "receipts_db": "set" if config.bot_receipts_db_path else "missing",
        "receipts_max_items": config.bot_receipts_max_items,
        "send_queue_enabled": config.bot_send_queue_enabled,
        "send_queue_store": (
            "sqlite"
            if config.bot_send_queue_enabled and config.bot_send_queue_db_path
            else "memory"
        ),
        "send_queue_db": "set" if config.bot_send_queue_db_path else "missing",
        "send_queue_max_items": config.bot_send_queue_max_items,
        "send_queue_max_attempts": config.bot_send_queue_max_attempts,
        "send_queue_retry_base_seconds": config.bot_send_queue_retry_base_seconds,
        "send_queue_retry_max_seconds": config.bot_send_queue_retry_max_seconds,
        "send_queue_worker_enabled": config.bot_send_queue_worker_enabled,
        "send_queue_worker_interval_seconds": (
            config.bot_send_queue_worker_interval_seconds
        ),
        "send_queue_worker_batch_size": config.bot_send_queue_worker_batch_size,
        "emotion_enabled": config.bot_emotion_enabled,
        "emotion_max_signals": config.bot_emotion_max_signals,
        "rate_limit_enabled": config.bot_rate_limit_enabled,
        "rate_limit_window_seconds": config.bot_rate_limit_window_seconds,
        "rate_limit_chat_global_max_requests": (
            config.bot_rate_limit_chat_global_max_requests
        ),
        "rate_limit_chat_session_max_requests": (
            config.bot_rate_limit_chat_session_max_requests
        ),
        "rate_limit_chat_sender_max_requests": (
            config.bot_rate_limit_chat_sender_max_requests
        ),
        "rate_limit_target_min_interval_seconds": (
            config.bot_rate_limit_target_min_interval_seconds
        ),
        "rate_limit_bypass_roles": ",".join(config.bot_rate_limit_bypass_roles),
        "rate_limit_store": "sqlite" if config.bot_rate_limit_db_path else "memory",
        "rate_limit_db": "set" if config.bot_rate_limit_db_path else "missing",
        "quiet_hours_enabled": config.bot_quiet_hours_enabled,
        "quiet_hours_start": config.bot_quiet_hours_start,
        "quiet_hours_end": config.bot_quiet_hours_end,
        "quiet_hours_timezone": config.bot_quiet_hours_timezone,
        "quiet_hours_session_types": ",".join(config.bot_quiet_hours_session_types),
        "quiet_hours_bypass_roles": ",".join(config.bot_quiet_hours_bypass_roles),
        "admin_users": len(config.bot_admin_user_ids),
        "enterprise_users": len(config.bot_enterprise_user_ids),
        "trusted_users": len(config.bot_trusted_user_ids),
        "blocked_users": len(config.bot_blocked_user_ids),
        "chat_enabled": config.bot_chat_enabled,
        "chat_provider": config.bot_chat_provider,
        "chat_model": config.bot_chat_model,
        "chat_api_key": "set" if _has_real_api_key(config.bot_chat_api_key) else "missing",
        "ready_for_real_llm": readiness["ready_for_real_llm"],
        "llm_readiness_status": readiness["llm_readiness_status"],
        "llm_readiness_reasons": readiness["llm_readiness_reasons"],
        "llm_fix_hints": readiness["llm_fix_hints"],
        "llm_next_action": readiness["llm_next_action"],
    }


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_startup_runner(
    env_file: str | Path,
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _STARTUP_SMOKE_CHILD_CODE, str(env_file)],
        cwd=_project_root(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        check=False,
    )


def _extract_startup_child_result(stdout: str) -> dict[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        if line.startswith(_STARTUP_SMOKE_PREFIX):
            payload = line.removeprefix(_STARTUP_SMOKE_PREFIX)
            parsed = json.loads(payload)
            return parsed if isinstance(parsed, dict) else None
    return None


def _format_matcher_priorities(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    items: list[tuple[int, str, int]] = []
    for raw_key, raw_count in value.items():
        if not isinstance(raw_count, int):
            continue
        key_text = str(raw_key)
        sort_key = int(key_text) if key_text.isdigit() else 999999
        items.append((sort_key, key_text, raw_count))
    return ",".join(f"{key}:{count}" for _, key, count in sorted(items))


def run_nonebot_startup_smoke(
    config: Config,
    *,
    env_file: str | Path | None = None,
    timeout_seconds: int = 15,
    runner: Callable[[str | Path, int], Any] | None = None,
) -> dict[str, Any]:
    resolved_env_file = _resolve_smoke_env_file(env_file)
    active_runner = runner or _default_startup_runner
    base_result: dict[str, Any] = {
        "ok": False,
        "error_kind": "startup_failed",
        "public_message": "NoneBot 启动干跑未通过：插件初始化或 handler 注册失败。",
        "private_debug": "",
        "nonebot_initialized": False,
        "onebot_adapter_registered": False,
        "plugin_loaded": False,
        "plugin_name": "",
        "onebot_supported": False,
        "matcher_count": 0,
        "matcher_priorities": "",
        "scheduler_access": "not_checked",
        "scheduler_jobs": 0,
        "send_queue_worker_registered": False,
        "server_started": False,
        "napcat_connected": False,
        "real_transport_used": False,
        "runtime_enabled": config.bot_runtime_enabled,
        "send_queue_worker_enabled": config.bot_send_queue_worker_enabled,
        "chat_provider": config.bot_chat_provider,
        "chat_model": config.bot_chat_model,
        "chat_api_key": "set"
        if _has_real_api_key(config.bot_chat_api_key)
        else "missing",
    }

    try:
        completed = active_runner(resolved_env_file, timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        timeout_debug = "\n".join(
            str(part)
            for part in (getattr(exc, "stdout", ""), getattr(exc, "stderr", ""))
            if part
        )
        return {
            **base_result,
            "error_kind": "startup_timeout",
            "public_message": "NoneBot 启动干跑超时：初始化未在限定时间内完成。",
            "private_debug": _redact_smoke_debug(
                timeout_debug or str(exc),
                config.bot_chat_api_key,
            ),
        }
    except Exception as exc:  # noqa: BLE001 - smoke must report runner failures safely.
        return {
            **base_result,
            "error_kind": "startup_runner_error",
            "public_message": "NoneBot 启动干跑未执行：本地诊断子进程启动失败。",
            "private_debug": _redact_smoke_debug(str(exc), config.bot_chat_api_key),
        }

    stdout = str(getattr(completed, "stdout", "") or "")
    stderr = str(getattr(completed, "stderr", "") or "")
    private_debug = _redact_smoke_debug(
        "\n".join(part for part in (stdout, stderr) if part),
        config.bot_chat_api_key,
    )

    try:
        child_result = _extract_startup_child_result(stdout)
    except Exception as exc:  # noqa: BLE001 - malformed JSON should become diagnostics.
        return {
            **base_result,
            "error_kind": "startup_result_invalid",
            "public_message": "NoneBot 启动干跑未通过：子进程诊断结果格式无效。",
            "private_debug": _redact_smoke_debug(
                f"{private_debug}\n{type(exc).__name__}: {exc}",
                config.bot_chat_api_key,
            ),
        }

    if child_result is None:
        return {
            **base_result,
            "error_kind": "startup_result_missing",
            "public_message": "NoneBot 启动干跑未通过：没有收到结构化诊断结果。",
            "private_debug": private_debug,
        }

    scheduler_jobs_value = child_result.get("scheduler_jobs", [])
    scheduler_jobs = (
        [str(item) for item in scheduler_jobs_value]
        if isinstance(scheduler_jobs_value, list)
        else []
    )
    child_ok = bool(child_result.get("ok")) and int(getattr(completed, "returncode", 1)) == 0
    error_kind = str(child_result.get("error_kind") or "startup_failed")
    ok = child_ok

    return {
        **base_result,
        "ok": ok,
        "error_kind": "none" if ok else error_kind,
        "public_message": (
            "NoneBot 启动干跑通过：已初始化、加载统一运行时插件并注册 handler；"
            "未启动长驻服务，未连接 NapCat，也未发送真实消息。"
            if ok
            else "NoneBot 启动干跑未通过：插件初始化或 handler 注册失败。"
        ),
        "private_debug": private_debug,
        "nonebot_initialized": bool(child_result.get("nonebot_initialized")),
        "onebot_adapter_registered": bool(
            child_result.get("onebot_adapter_registered")
        ),
        "plugin_loaded": bool(child_result.get("plugin_loaded")),
        "plugin_name": str(child_result.get("plugin_name") or ""),
        "onebot_supported": bool(child_result.get("onebot_supported")),
        "matcher_count": int(child_result.get("matcher_count") or 0),
        "matcher_priorities": _format_matcher_priorities(
            child_result.get("matcher_priorities")
        ),
        "scheduler_access": str(child_result.get("scheduler_access") or "not_checked"),
        "scheduler_jobs": len(scheduler_jobs),
        "send_queue_worker_registered": "bot_send_queue_worker" in scheduler_jobs,
        "server_started": bool(child_result.get("server_started")),
        "napcat_connected": bool(child_result.get("napcat_connected")),
        "real_transport_used": bool(child_result.get("real_transport_used")),
    }


def run_environment_doctor(
    config: Config,
    *,
    importer: Callable[[str], Any] | None = None,
    command_resolver: Callable[[str], str | None] | None = None,
    python_executable: str | None = None,
    python_version: str | None = None,
) -> dict[str, Any]:
    active_importer = importer or importlib.import_module
    active_command_resolver = command_resolver or shutil.which
    debug_parts: list[str] = []

    python_path = python_executable or sys.executable
    python_version_value = python_version or sys.version.split()[0]

    nonebot_state, _, nonebot_debug = _import_state(
        "nonebot",
        active_importer,
        api_key=config.bot_chat_api_key,
    )
    if nonebot_debug:
        debug_parts.append(f"nonebot={nonebot_debug}")

    adapter_state, _, adapter_debug = _import_state(
        "nonebot.adapters.onebot.v11",
        active_importer,
        api_key=config.bot_chat_api_key,
    )
    if adapter_debug:
        debug_parts.append(f"onebot_adapter={adapter_debug}")

    apscheduler_state, _, apscheduler_debug = _import_state(
        "nonebot_plugin_apscheduler",
        active_importer,
        api_key=config.bot_chat_api_key,
        allow_nonebot_not_initialized=True,
    )
    if apscheduler_debug:
        debug_parts.append(f"apscheduler={apscheduler_debug}")

    plugin_state, _, plugin_debug = _import_state(
        "plugins.bot_unified_runtime",
        active_importer,
        api_key=config.bot_chat_api_key,
    )
    if plugin_debug:
        debug_parts.append(f"plugin={plugin_debug}")

    nb_cli_path = active_command_resolver("nb")
    nb_cli_state = "ok" if nb_cli_path else "missing"
    ready_for_local_llm_smoke = plugin_state == "ok"
    ready_for_nonebot_run = (
        nonebot_state == "ok"
        and adapter_state == "ok"
        and apscheduler_state == "ok"
        and plugin_state == "ok"
        and nb_cli_state == "ok"
    )
    ok = ready_for_nonebot_run
    install_hint = (
        ""
        if ok
        else "powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 install"
    )

    return {
        "ok": ok,
        "error_kind": "none" if ok else "dependency_missing",
        "public_message": (
            "本地运行环境诊断通过。"
            if ok
            else "本地运行环境诊断未通过：请先安装或修复 NoneBot 运行依赖。"
        ),
        "private_debug": "; ".join(debug_parts),
        "python_executable": python_path,
        "python_version": python_version_value,
        "nonebot_import": nonebot_state,
        "onebot_adapter_import": adapter_state,
        "apscheduler_import": apscheduler_state,
        "plugin_import": plugin_state,
        "nb_cli": nb_cli_state,
        "ready_for_local_llm_smoke": ready_for_local_llm_smoke,
        "ready_for_nonebot_run": ready_for_nonebot_run,
        "install_hint": install_hint,
        "chat_provider": config.bot_chat_provider,
        "chat_model": config.bot_chat_model,
        "chat_api_key": "set" if _has_real_api_key(config.bot_chat_api_key) else "missing",
    }


def run_readiness_smoke(
    config: Config,
    *,
    message_text: str = "你好，守岸人。",
    importer: Callable[[str], Any] | None = None,
    command_resolver: Callable[[str], str | None] | None = None,
) -> dict[str, Any]:
    doctor = run_environment_doctor(
        config,
        importer=importer,
        command_resolver=command_resolver,
    )
    config_result = run_config_smoke(config)
    context_result = run_context_smoke(config, message_text=message_text)
    local_probe_config = config.model_copy(
        update={
            "bot_chat_provider": "static",
            "bot_chat_model": "static",
            "bot_chat_api_key": "",
        }
    )
    chat_result = run_chat_smoke(
        local_probe_config,
        message_text=message_text,
        llm_provider=StaticLLMProvider(model="static"),
    )
    nonebot_result = run_nonebot_smoke(config, importer=importer)
    transport_result = run_transport_smoke(config)
    nonebot_ok = bool(nonebot_result["ok"])
    transport_ok = bool(transport_result["ok"])

    chat_pipeline_ok = (
        chat_result["receipt_state"] == ReceiptState.SENT.value
        and chat_result["capability_id"] == "bot.chat"
    )
    ready_for_local_dialogue = (
        bool(doctor["ready_for_local_llm_smoke"])
        and bool(config_result["ok"])
        and bool(context_result["ok"])
        and chat_pipeline_ok
        and nonebot_ok
        and transport_ok
    )
    next_action = _readiness_next_action(
        doctor=doctor,
        config_result=config_result,
        context_result=context_result,
        chat_pipeline_ok=chat_pipeline_ok,
        nonebot_ok=nonebot_ok,
        transport_ok=transport_ok,
    )
    if not ready_for_local_dialogue:
        readiness_status = "blocked"
    elif config_result["ready_for_real_llm"]:
        readiness_status = "ready"
    else:
        readiness_status = "local_only"

    return {
        "ok": ready_for_local_dialogue,
        "readiness_status": readiness_status,
        "next_action": next_action,
        "recommended_commands": _readiness_recommended_commands(next_action),
        "error_kind": "none" if ready_for_local_dialogue else next_action,
        "public_message": _readiness_public_message(
            readiness_status=readiness_status,
            next_action=next_action,
        ),
        "ready_for_local_dialogue": ready_for_local_dialogue,
        "ready_for_real_llm": bool(config_result["ready_for_real_llm"]),
        "real_llm_probe_performed": False,
        "doctor_ok": bool(doctor["ok"]),
        "ready_for_local_llm_smoke": bool(doctor["ready_for_local_llm_smoke"]),
        "ready_for_nonebot_run": bool(doctor["ready_for_nonebot_run"]),
        "nonebot_ok": nonebot_ok,
        "transport_ok": transport_ok,
        "config_ok": bool(config_result["ok"]),
        "config_errors": config_result["errors"],
        "config_warnings": config_result["warnings"],
        "context_ok": bool(context_result["ok"]),
        "context_error_kind": context_result["error_kind"],
        "context_prompt_total_chars": context_result["prompt_total_chars"],
        "context_prompt_clipped": bool(context_result["prompt_clipped"]),
        "chat_pipeline_ok": chat_pipeline_ok,
        "chat_pipeline_mode": "local_static_probe",
        "chat_receipt_state": chat_result["receipt_state"],
        "chat_reply_preview_chars": chat_result["reply_preview_chars"],
        "llm_finish_reason": chat_result["llm_finish_reason"],
        "llm_readiness_status": config_result["llm_readiness_status"],
        "llm_next_action": config_result["llm_next_action"],
        "llm_readiness_reasons": config_result["llm_readiness_reasons"],
        "llm_fix_hints": config_result["llm_fix_hints"],
        "persona_strength_status": config_result["persona_strength_status"],
        "knowledge_readable": config_result["knowledge_readable"],
        "provider": config_result["chat_provider"],
        "model": config_result["chat_model"],
        "chat_api_key": config_result["chat_api_key"],
    }


def _readiness_next_action(
    *,
    doctor: dict[str, Any],
    config_result: dict[str, Any],
    context_result: dict[str, Any],
    chat_pipeline_ok: bool,
    nonebot_ok: bool,
    transport_ok: bool,
) -> str:
    if not doctor["ready_for_local_llm_smoke"]:
        return "fix_python_environment"
    if not config_result["ok"]:
        return "fix_config"
    if not context_result["ok"]:
        return "fix_context"
    if not chat_pipeline_ok:
        return "fix_chat_pipeline"
    if not nonebot_ok:
        return "fix_nonebot"
    if not transport_ok:
        return "fix_transport"
    if not config_result["ready_for_real_llm"]:
        return "configure_real_llm"
    return "llm_smoke"


def _readiness_recommended_commands(next_action: str) -> str:
    if next_action == "fix_python_environment":
        return "doctor,install"
    if next_action == "fix_config":
        return "config-smoke"
    if next_action == "fix_context":
        return "context-smoke"
    if next_action == "fix_chat_pipeline":
        return "chat-smoke,why-smoke"
    if next_action == "fix_nonebot":
        return "nonebot-smoke,doctor,install"
    if next_action == "fix_transport":
        return "transport-smoke,nonebot-smoke"
    if next_action == "configure_real_llm":
        return "config-smoke,context-smoke,chat-smoke,llm-smoke"
    if next_action == "llm_smoke":
        return "llm-smoke,nonebot-smoke,startup-smoke,transport-smoke"
    return "doctor,config-smoke,chat-smoke"


def _readiness_public_message(*, readiness_status: str, next_action: str) -> str:
    if readiness_status == "ready":
        return "统一 readiness 通过：本地对话链路和真实 LLM 关键配置已具备，下一步运行 llm-smoke。"
    if readiness_status == "local_only":
        return "统一 readiness 通过：本地基础对话链路可用，下一步配置真实 LLM。"
    if next_action == "fix_python_environment":
        return "统一 readiness 未通过：请先修复 Python/NoneBot 本地环境。"
    if next_action == "fix_config":
        return "统一 readiness 未通过：请先修复人格、知识或 LLM 配置。"
    if next_action == "fix_context":
        return "统一 readiness 未通过：请先修复人格、记忆、知识或 prompt 上下文构造。"
    if next_action == "fix_chat_pipeline":
        return "统一 readiness 未通过：请先修复本地基础聊天 pipeline。"
    return "统一 readiness 未通过：请按 recommended_commands 继续排障。"



def run_embedding_smoke(config: Config) -> dict[str, Any]:
    """用配置的 OpenAI-compatible embeddings 服务做一次 2 条文本的连通测试。"""
    model = str(getattr(config, "bot_embedding_model", "") or "").strip()
    base_url = str(getattr(config, "bot_embedding_base_url", "") or "").strip()
    api_key = str(getattr(config, "bot_embedding_api_key", "") or "").strip()
    enabled = bool(getattr(config, "bot_embedding_enabled", False))
    dimensions = int(getattr(config, "bot_embedding_dimensions", 1024) or 1024)
    timeout = float(getattr(config, "bot_embedding_timeout_seconds", 15.0) or 15.0)
    local_enabled = bool(getattr(config, "bot_embedding_local_enabled", True))
    local_models = str(
        getattr(config, "bot_embedding_local_models", "") or ""
    ).strip()
    local_base_url = str(
        getattr(config, "bot_embedding_local_base_url", "") or ""
    ).strip()
    local_timeout = float(
        getattr(config, "bot_embedding_local_timeout_seconds", 60.0) or 60.0
    )
    result: dict[str, Any] = {
        "ok": False,
        "enabled": enabled,
        "model": model,
        "base_url": base_url,
        "api_key_set": bool(api_key),
        "dimensions": dimensions,
        "local_enabled": local_enabled,
        "local_models": local_models,
        "local_base_url": local_base_url,
        "active_base_url": "",
        "active_model": "",
        "dimension_count": 0,
        "api_status": 0,
        "api_error": "",
        "error_kind": "disabled",
        "public_message": "",
    }
    if not enabled:
        result["public_message"] = (
            "向量知识库未启用：把 .env 中 BOT_EMBEDDING_ENABLED 改为 true 后重试。"
        )
        return result
    local_configured = bool(local_enabled and local_models and local_base_url)
    remote_configured = bool(model and base_url and api_key)
    if not (local_configured or remote_configured):
        result["error_kind"] = "config_missing"
        result["public_message"] = (
            "缺少配置：至少需要本地链 BOT_EMBEDDING_LOCAL_MODELS/BASE_URL，"
            "或远程链 BOT_EMBEDDING_MODEL/BASE_URL/API_KEY。"
        )
        return result
    provider = OpenAICompatibleEmbeddingProvider(
        base_url=base_url,
        model=model,
        api_key=api_key,
        timeout_seconds=timeout,
        dimensions=dimensions,
        local_base_url=local_base_url,
        local_models=local_models,
        local_enabled=local_enabled,
        local_timeout_seconds=local_timeout,
    )
    try:
        vectors = provider.embed_texts(["守岸人是谁", "鸣潮 库街区"])
    except Exception as exc:  # noqa: BLE001 - 烟测统一转安全文本。
        result["error_kind"] = "exception"
        result["public_message"] = f"调用异常：{type(exc).__name__}"
        return result
    if isinstance(vectors, list) and len(vectors) == 2 and vectors[0]:
        result["ok"] = True
        result["dimension_count"] = len(vectors[0])
        result["active_base_url"] = str(getattr(provider, "active_base_url", "") or "")
        result["active_model"] = str(getattr(provider, "active_model", "") or "")
        result["error_kind"] = "none"
        result["public_message"] = (
            f"嵌入成功：{result['active_base_url']} / {result['active_model']}，"
            "返回维度与配置一致。"
        )
        return result
    messages: list[str] = []
    status = 0
    try:
        import httpx

        for chain in provider.chains:
            try:
                response = httpx.post(
                    f"{chain.base_url}/embeddings",
                    headers=(
                        {"Authorization": f"Bearer {chain.api_key}"}
                        if chain.api_key
                        else {}
                    ),
                    json={"model": chain.models[0], "input": ["测试"]},
                    timeout=chain.timeout_seconds,
                )
                status = response.status_code
                payload = response.json() if response.content else {}
                error = payload.get("error") if isinstance(payload, dict) else None
                error_text = error if isinstance(error, dict) else {}
                message = str(error_text.get("message") or "").strip()[:160]
                messages.append(
                    f"{chain.base_url}: HTTP {response.status_code}"
                    + (f" {message}" if message else "")
                )
            except Exception as exc:  # noqa: BLE001
                messages.append(f"{chain.base_url}: {type(exc).__name__}")
    except Exception:  # noqa: BLE001, S110 - 所有嵌入端点失败后汇总调用方错误并降级返回，无须额外日志。
        pass
    result["api_status"] = status
    result["api_error"] = " | ".join(messages)[:400]
    result["error_kind"] = "api_error"
    result["public_message"] = (
        "所有嵌入端点都失败：" + (result["api_error"] or "未知错误")
    )
    return result


def run_knowledge_sync(config: Config) -> dict[str, Any]:
    """把 BOT_KNOWLEDGE_FILES 切片并批量向量化写入本地 SQLite（预建库）。"""
    model = str(getattr(config, "bot_embedding_model", "") or "").strip()
    base_url = str(getattr(config, "bot_embedding_base_url", "") or "").strip()
    api_key = str(getattr(config, "bot_embedding_api_key", "") or "").strip()
    local_enabled = bool(getattr(config, "bot_embedding_local_enabled", True))
    local_models = str(
        getattr(config, "bot_embedding_local_models", "") or ""
    ).strip()
    local_base_url = str(
        getattr(config, "bot_embedding_local_base_url", "") or ""
    ).strip()
    db_path = str(
        getattr(config, "bot_knowledge_db_path", "data/knowledge_embeddings.sqlite3")
        or "data/knowledge_embeddings.sqlite3"
    )
    files = [
        Path(path).expanduser()
        for path in (getattr(config, "bot_knowledge_files", []) or [])
    ]
    result: dict[str, Any] = {
        "ok": False,
        "model": model,
        "base_url": base_url,
        "api_key_set": bool(api_key),
        "local_enabled": local_enabled,
        "local_models": local_models,
        "local_base_url": local_base_url,
        "active_base_url": "",
        "active_model": "",
        "db_path": db_path,
        "files": len(files),
        "total_before": 0,
        "embedded_before": 0,
        "pending": 0,
        "done": 0,
        "total_after": 0,
        "embedded_after": 0,
        "error_kind": "none",
        "public_message": "",
    }
    local_configured = bool(local_enabled and local_models and local_base_url)
    remote_configured = bool(model and base_url and api_key)
    if not (local_configured or remote_configured):
        result["error_kind"] = "config_missing"
        result["public_message"] = (
            "缺少配置：至少需要本地链 BOT_EMBEDDING_LOCAL_MODELS/BASE_URL，"
            "或远程链 BOT_EMBEDDING_MODEL/BASE_URL/API_KEY。"
        )
        return result
    provider = OpenAICompatibleEmbeddingProvider(
        base_url=base_url,
        model=model,
        api_key=api_key,
        timeout_seconds=float(
            getattr(config, "bot_embedding_timeout_seconds", 15.0) or 15.0
        ),
        dimensions=int(getattr(config, "bot_embedding_dimensions", 1024) or 1024),
        local_base_url=local_base_url,
        local_models=local_models,
        local_enabled=local_enabled,
        local_timeout_seconds=float(
            getattr(config, "bot_embedding_local_timeout_seconds", 60.0) or 60.0
        ),
    )
    try:
        store = SqliteVectorKnowledgeStore(
            db_path=db_path,
            embed_provider=provider,
            chunk_chars=int(getattr(config, "bot_knowledge_chunk_chars", 900) or 900),
            top_k=int(getattr(config, "bot_knowledge_top_k", 4) or 4),
            signature=getattr(provider, "signature", ""),
            auto_reset=True,
        )
        before = store.stats()
        result["total_before"] = int(before["total"])
        result["embedded_before"] = int(before["embedded"])
        done, pending = store.embed_pending(
            files,
            on_progress=lambda done, total: print(
                f"progress embedded={done}/{total} percent={done*100//total if total else 0}%",
                flush=True,
            ),
        )
        after = store.stats()
        result["pending"] = int(pending)
        result["done"] = int(done)
        result["total_after"] = int(after["total"])
        result["embedded_after"] = int(after["embedded"])
        ann: dict[str, Any] = {"built": False, "reason": "not_attempted"}
        if after["embedded"] > 0:
            try:
                ann = store.build_ann_index()
            except Exception as exc:  # noqa: BLE001
                ann = {"built": False, "reason": f"{type(exc).__name__}"}
        result["ann_index_built"] = bool(ann.get("built"))
        result["ann_vectors"] = int(ann.get("vectors", 0) or 0)
        result["ann_reason"] = str(ann.get("reason", ""))
    except Exception as exc:  # noqa: BLE001
        result["error_kind"] = "exception"
        result["public_message"] = f"预建库异常：{type(exc).__name__}"
        return result
    result["active_base_url"] = getattr(provider, "active_base_url", "")
    result["active_model"] = getattr(provider, "active_model", "")
    if done < pending:
        result["error_kind"] = "partial"
        result["public_message"] = (
            f"只完成 {done}/{pending} 行向量化，请检查 API Key/额度/限流后重跑"
            "（已完成的会跳过，可断点续跑）。"
        )
        return result
    result["ok"] = True
    result["public_message"] = (
        f"预建库完成：共 {result['total_after']} 行，全部已向量化"
        f"（{result['active_base_url']} / {result['active_model']}）；"
        f"HNSW 索引：{result['ann_index_built']}。"
    )
    return result


def main(
    *,
    importer: Callable[[str], Any] | None = None,
    command_resolver: Callable[[str], str | None] | None = None,
    runner: Callable[[str | Path, int], Any] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description="Bot unified runtime local smoke checks")
    parser.add_argument(
        "task",
        nargs="?",
        choices=(
            "chat",
            "context",
            "why",
            "config",
            "llm",
            "llm-setup",
            "nonebot",
            "startup",
            "queue",
            "transport",
            "online-transport",
            "doctor",
            "readiness",
            "dialogue",
            "persona",
            "embedding",
            "knowledge-sync",
        ),
        default="chat",
        help="Smoke task to run.",
    )
    parser.add_argument(
        "--message",
        default=None,
        help="Custom message text for chat/context/why smoke diagnostics.",
    )
    parser.add_argument(
        "--session-type",
        choices=("private", "group"),
        default="private",
        help="Session type for why smoke diagnostics.",
    )
    parser.add_argument(
        "--mentions-bot",
        choices=("true", "false"),
        default="true",
        help="Whether the diagnostic message mentions the bot.",
    )
    parser.add_argument(
        "--sender-id",
        default="smoke-user",
        help="Sender id for why smoke diagnostics.",
    )
    parser.add_argument(
        "--group-id",
        default=None,
        help="Group id for group why smoke diagnostics.",
    )
    args = parser.parse_args()

    config_path = _resolve_smoke_env_file(None)
    config = load_smoke_config(config_path)
    if args.task == "llm-setup":
        result = run_llm_setup(config)
        print(f"ok={str(result['ok']).lower()}")
        print(f"llm_setup_status={result['llm_setup_status']}")
        print(f"ready_for_real_llm={str(result['ready_for_real_llm']).lower()}")
        print(f"llm_readiness_status={result['llm_readiness_status']}")
        print(f"llm_next_action={result['llm_next_action']}")
        print(
            "llm_readiness_reasons="
            f"{','.join(result['llm_readiness_reasons'])}"
        )
        print(f"llm_fix_hints={','.join(result['llm_fix_hints'])}")
        print(f"required_env_keys={','.join(result['required_env_keys'])}")
        print(
            "missing_or_placeholder_env_keys="
            f"{','.join(result['missing_or_placeholder_env_keys'])}"
        )
        print(f"safe_env_template={';'.join(result['safe_env_template'])}")
        print(f"next_commands={';'.join(result['next_commands'])}")
        print(f"manual_steps={';'.join(result['manual_steps'])}")
        print(
            "real_llm_probe_performed="
            f"{str(result['real_llm_probe_performed']).lower()}"
        )
        print(f"napcat_connected={str(result['napcat_connected']).lower()}")
        print(f"message_sent={str(result['message_sent']).lower()}")
        print(f"writes_env={str(result['writes_env']).lower()}")
        print(f"secrets_hidden={str(result['secrets_hidden']).lower()}")
        print(f"error_kind={result['error_kind']}")
        print(f"public_message={result['public_message']}")
        return 0 if result["ok"] else 1

    if args.task == "persona":
        result = run_persona_smoke(config)
        print(f"ok={str(result['ok']).lower()}")
        print(f"persona_status={result['persona_status']}")
        print(f"persona_next_action={result['persona_next_action']}")
        print(f"persona_profile_id={result['persona_profile_id']}")
        print(f"persona_display_name={result['persona_display_name']}")
        print(f"persona_version={result['persona_version']}")
        print(f"persona_files={result['persona_files']}")
        print(f"persona_missing={result['persona_missing']}")
        print(f"persona_unsupported={result['persona_unsupported']}")
        print(f"persona_readable={result['persona_readable']}")
        print(f"persona_empty={result['persona_empty']}")
        print(f"persona_unreadable={result['persona_unreadable']}")
        print(f"persona_total_chars={result['persona_total_chars']}")
        print(f"persona_meaningful_lines={result['persona_meaningful_lines']}")
        print(f"persona_strength_status={result['persona_strength_status']}")
        print(f"persona_source_refs={result['persona_source_refs']}")
        print(f"knowledge_source_refs={result['knowledge_source_refs']}")
        print(f"knowledge_files={result['knowledge_files']}")
        print(f"knowledge_readable={result['knowledge_readable']}")
        print(f"knowledge_chunks={result['knowledge_chunks']}")
        print(f"style_rules={result['style_rules']}")
        print(f"role_boundaries={result['role_boundaries']}")
        print(f"forbidden_behaviors={result['forbidden_behaviors']}")
        print(f"tone_mode={result['tone_mode']}")
        print(f"tone_voice={result['tone_voice']}")
        print(f"tone_warmth={result['tone_warmth']}")
        print(f"tone_directness={result['tone_directness']}")
        print(f"tone_message_count_limit={result['tone_message_count_limit']}")
        print(f"memory_enabled={str(result['memory_enabled']).lower()}")
        print(f"history_enabled={str(result['history_enabled']).lower()}")
        print(f"emotion_enabled={str(result['emotion_enabled']).lower()}")
        print(f"errors={','.join(result['errors'])}")
        print(f"warnings={','.join(result['warnings'])}")
        print(f"llm_readiness_status={result['llm_readiness_status']}")
        print(f"llm_next_action={result['llm_next_action']}")
        print(
            "llm_readiness_reasons="
            f"{','.join(result['llm_readiness_reasons'])}"
        )
        print(f"llm_fix_hints={','.join(result['llm_fix_hints'])}")
        print(
            "real_llm_probe_performed="
            f"{str(result['real_llm_probe_performed']).lower()}"
        )
        print(f"real_transport_used={str(result['real_transport_used']).lower()}")
        print(f"napcat_connected={str(result['napcat_connected']).lower()}")
        print(f"error_kind={result['error_kind']}")
        print(f"public_message={result['public_message']}")
        return 0 if result["ok"] else 1

    if args.task == "doctor":
        result = run_environment_doctor(
            config,
            importer=importer,
            command_resolver=command_resolver,
        )
        print(f"ok={str(result['ok']).lower()}")
        print(f"python_executable={result['python_executable']}")
        print(f"python_version={result['python_version']}")
        print(f"nonebot_import={result['nonebot_import']}")
        print(f"onebot_adapter_import={result['onebot_adapter_import']}")
        print(f"apscheduler_import={result['apscheduler_import']}")
        print(f"plugin_import={result['plugin_import']}")
        print(f"nb_cli={result['nb_cli']}")
        print(
            "ready_for_local_llm_smoke="
            f"{str(result['ready_for_local_llm_smoke']).lower()}"
        )
        print(
            "ready_for_nonebot_run="
            f"{str(result['ready_for_nonebot_run']).lower()}"
        )
        print(f"chat_provider={result['chat_provider']}")
        print(f"chat_model={result['chat_model']}")
        print(f"chat_api_key={result['chat_api_key']}")
        print(f"error_kind={result['error_kind']}")
        print(f"install_hint={result['install_hint']}")
        print(f"public_message={result['public_message']}")
        return 0 if result["ok"] else 1

    if args.task == "dialogue":
        result = run_dialogue_smoke(
            config,
            message_text=args.message or "你好，守岸人。",
        )
        print(f"ok={str(result['ok']).lower()}")
        print(f"dialogue_status={result['dialogue_status']}")
        print(f"next_action={result['next_action']}")
        print(f"context_ok={str(result['context_ok']).lower()}")
        print(f"context_error_kind={result['context_error_kind']}")
        print(f"persona_profile_id={result['persona_profile_id']}")
        print(f"persona_display_name={result['persona_display_name']}")
        print(f"persona_source_refs={result['persona_source_refs']}")
        print(f"knowledge_source_refs={result['knowledge_source_refs']}")
        print(f"knowledge_chunks={result['knowledge_chunks']}")
        print(f"memory_facts={result['memory_facts']}")
        print(f"history_turns={result['history_turns']}")
        print(f"emotion_signals={result['emotion_signals']}")
        print(f"emotion_labels={result['emotion_labels']}")
        print(f"prompt_messages={result['prompt_messages']}")
        print(f"prompt_total_chars={result['prompt_total_chars']}")
        print(f"prompt_budget_remaining={result['prompt_budget_remaining']}")
        print(f"prompt_clipped={str(result['prompt_clipped']).lower()}")
        print(f"prompt_user_clipped={str(result['prompt_user_clipped']).lower()}")
        print(f"prompt_truncated_sections={result['prompt_truncated_sections']}")
        print(f"context_budget={result['context_budget']}")
        print(f"max_messages={result['max_messages']}")
        print(f"risk_level={result['risk_level']}")
        print(f"chat_pipeline_ok={str(result['chat_pipeline_ok']).lower()}")
        print(f"receipt_state={result['receipt_state']}")
        print(f"capability_id={result['capability_id']}")
        print(f"reply_preview_chars={result['reply_preview_chars']}")
        print(f"reply_text_hidden={str(result['reply_text_hidden']).lower()}")
        print(f"llm_status={result['llm_status']}")
        print(f"llm_error_kind={result['llm_error_kind']}")
        print(f"llm_finish_reason={result['llm_finish_reason']}")
        print(f"llm_provider={result['llm_provider']}")
        print(f"llm_model={result['llm_model']}")
        print(f"ready_for_real_llm={str(result['ready_for_real_llm']).lower()}")
        print(f"llm_readiness_status={result['llm_readiness_status']}")
        print(f"llm_next_action={result['llm_next_action']}")
        print(
            "llm_readiness_reasons="
            f"{','.join(result['llm_readiness_reasons'])}"
        )
        print(f"llm_fix_hints={','.join(result['llm_fix_hints'])}")
        print(f"real_transport_used={str(result['real_transport_used']).lower()}")
        print(f"napcat_connected={str(result['napcat_connected']).lower()}")
        if result["audit_tags"]:
            print(f"audit_tags={','.join(result['audit_tags'])}")
        if result["audit_events"]:
            print(f"audit_events={','.join(result['audit_events'])}")
        print(f"error_kind={result['error_kind']}")
        print(f"public_message={result['public_message']}")
        return dialogue_smoke_exit_code(config, result)

    if args.task == "readiness":
        result = run_readiness_smoke(
            config,
            message_text=args.message or "你好，守岸人。",
            importer=importer,
            command_resolver=command_resolver,
        )
        print(f"ok={str(result['ok']).lower()}")
        print(f"readiness_status={result['readiness_status']}")
        print(f"next_action={result['next_action']}")
        print(f"recommended_commands={result['recommended_commands']}")
        print(
            "ready_for_local_dialogue="
            f"{str(result['ready_for_local_dialogue']).lower()}"
        )
        print(f"ready_for_real_llm={str(result['ready_for_real_llm']).lower()}")
        print(
            "real_llm_probe_performed="
            f"{str(result['real_llm_probe_performed']).lower()}"
        )
        print(f"doctor_ok={str(result['doctor_ok']).lower()}")
        print(
            "ready_for_local_llm_smoke="
            f"{str(result['ready_for_local_llm_smoke']).lower()}"
        )
        print(
            "ready_for_nonebot_run="
            f"{str(result['ready_for_nonebot_run']).lower()}"
        )
        print(f"nonebot_ok={str(result['nonebot_ok']).lower()}")
        print(f"transport_ok={str(result['transport_ok']).lower()}")
        print(f"config_ok={str(result['config_ok']).lower()}")
        print(f"config_errors={','.join(result['config_errors'])}")
        print(f"config_warnings={','.join(result['config_warnings'])}")
        print(f"context_ok={str(result['context_ok']).lower()}")
        print(f"context_error_kind={result['context_error_kind']}")
        print(f"context_prompt_total_chars={result['context_prompt_total_chars']}")
        print(f"context_prompt_clipped={str(result['context_prompt_clipped']).lower()}")
        print(f"chat_pipeline_ok={str(result['chat_pipeline_ok']).lower()}")
        print(f"chat_pipeline_mode={result['chat_pipeline_mode']}")
        print(f"chat_receipt_state={result['chat_receipt_state']}")
        print(f"chat_reply_preview_chars={result['chat_reply_preview_chars']}")
        print(f"llm_finish_reason={result['llm_finish_reason']}")
        print(f"llm_readiness_status={result['llm_readiness_status']}")
        print(f"llm_next_action={result['llm_next_action']}")
        print(
            "llm_readiness_reasons="
            f"{','.join(result['llm_readiness_reasons'])}"
        )
        print(f"llm_fix_hints={','.join(result['llm_fix_hints'])}")
        print(f"persona_strength_status={result['persona_strength_status']}")
        print(f"knowledge_readable={result['knowledge_readable']}")
        print(f"provider={result['provider']}")
        print(f"model={result['model']}")
        print(f"chat_api_key={result['chat_api_key']}")
        print(f"error_kind={result['error_kind']}")
        print(f"public_message={result['public_message']}")
        return 0 if result["ok"] else 1

    if args.task == "embedding":
        result = run_embedding_smoke(config)
        print(f"ok={str(result['ok']).lower()}")
        print(f"enabled={str(result['enabled']).lower()}")
        print(f"model={result['model']}")
        print(f"base_url={result['base_url']}")
        print(f"api_key_set={str(result['api_key_set']).lower()}")
        print(f"dimensions={result['dimensions']}")
        print(f"local_enabled={str(result['local_enabled']).lower()}")
        print(f"local_models={result['local_models']}")
        print(f"local_base_url={result['local_base_url']}")
        print(f"active_base_url={result['active_base_url']}")
        print(f"active_model={result['active_model']}")
        print(f"dimension_count={result['dimension_count']}")
        print(f"api_status={result['api_status']}")
        print(f"api_error={result['api_error']}")
        print(f"error_kind={result['error_kind']}")
        print(f"public_message={result['public_message']}")
        return 0 if result["ok"] else 1

    if args.task == "knowledge-sync":
        result = run_knowledge_sync(config)
        print(f"ok={str(result['ok']).lower()}")
        print(f"model={result['model']}")
        print(f"base_url={result['base_url']}")
        print(f"api_key_set={str(result['api_key_set']).lower()}")
        print(f"local_enabled={str(result['local_enabled']).lower()}")
        print(f"local_models={result['local_models']}")
        print(f"local_base_url={result['local_base_url']}")
        print(f"active_base_url={result['active_base_url']}")
        print(f"active_model={result['active_model']}")
        print(f"db_path={result['db_path']}")
        print(f"files={result['files']}")
        print(f"total_before={result['total_before']}")
        print(f"embedded_before={result['embedded_before']}")
        print(f"pending={result['pending']}")
        print(f"done={result['done']}")
        print(f"total_after={result['total_after']}")
        print(f"embedded_after={result['embedded_after']}")
        print(f"error_kind={result['error_kind']}")
        print(f"public_message={result['public_message']}")
        return 0 if result["ok"] else 1

    if args.task == "config":
        result = run_config_smoke(config, env_path=config_path)
        print(f"ok={str(result['ok']).lower()}")
        print(f"ready_for_real_llm={str(result['ready_for_real_llm']).lower()}")
        print(f"llm_readiness_status={result['llm_readiness_status']}")
        print(f"llm_next_action={result['llm_next_action']}")
        print(
            "llm_readiness_reasons="
            f"{','.join(result['llm_readiness_reasons'])}"
        )
        print(f"llm_fix_hints={','.join(result['llm_fix_hints'])}")
        print(f"env_file={result['env_file']}")
        print(f"errors={','.join(result['errors'])}")
        print(f"warnings={','.join(result['warnings'])}")
        print(f"error_count={result['error_count']}")
        print(f"warning_count={result['warning_count']}")
        print(f"runtime_enabled={str(result['runtime_enabled']).lower()}")
        print(f"chat_enabled={str(result['chat_enabled']).lower()}")
        print(f"persona_profile_id={result['persona_profile_id']}")
        print(f"persona_display_name={result['persona_display_name']}")
        print(f"persona_files={result['persona_files']}")
        print(f"persona_missing={result['persona_missing']}")
        print(f"persona_unsupported={result['persona_unsupported']}")
        print(f"persona_readable={result['persona_readable']}")
        print(f"persona_empty={result['persona_empty']}")
        print(f"persona_unreadable={result['persona_unreadable']}")
        print(f"persona_total_chars={result['persona_total_chars']}")
        print(f"persona_meaningful_lines={result['persona_meaningful_lines']}")
        print(f"persona_strength_status={result['persona_strength_status']}")
        print(f"knowledge_files={result['knowledge_files']}")
        print(f"knowledge_missing={result['knowledge_missing']}")
        print(f"knowledge_unsupported={result['knowledge_unsupported']}")
        print(f"knowledge_readable={result['knowledge_readable']}")
        print(f"knowledge_empty={result['knowledge_empty']}")
        print(f"knowledge_unreadable={result['knowledge_unreadable']}")
        print(f"knowledge_total_chars={result['knowledge_total_chars']}")
        print(f"knowledge_meaningful_lines={result['knowledge_meaningful_lines']}")
        print(f"memory_enabled={str(result['memory_enabled']).lower()}")
        print(f"history_enabled={str(result['history_enabled']).lower()}")
        print(f"emotion_enabled={str(result['emotion_enabled']).lower()}")
        print(f"rate_limit_enabled={str(result['rate_limit_enabled']).lower()}")
        print(f"rate_limit_store={result['rate_limit_store']}")
        print(f"rate_limit_db={result['rate_limit_db']}")
        print(f"rate_limit_window_seconds={result['rate_limit_window_seconds']}")
        print(
            "rate_limit_chat_global_max_requests="
            f"{result['rate_limit_chat_global_max_requests']}"
        )
        print(
            "rate_limit_chat_session_max_requests="
            f"{result['rate_limit_chat_session_max_requests']}"
        )
        print(
            "rate_limit_chat_sender_max_requests="
            f"{result['rate_limit_chat_sender_max_requests']}"
        )
        print(
            "rate_limit_target_min_interval_seconds="
            f"{result['rate_limit_target_min_interval_seconds']}"
        )
        print(f"rate_limit_bypass_roles={result['rate_limit_bypass_roles']}")
        print(f"quiet_hours_enabled={str(result['quiet_hours_enabled']).lower()}")
        print(f"quiet_hours_start={result['quiet_hours_start']}")
        print(f"quiet_hours_end={result['quiet_hours_end']}")
        print(f"quiet_hours_timezone={result['quiet_hours_timezone']}")
        print(f"quiet_hours_session_types={result['quiet_hours_session_types']}")
        print(f"quiet_hours_bypass_roles={result['quiet_hours_bypass_roles']}")
        print(f"history_max_items={result['history_max_items']}")
        print(f"diagnostics_enabled={str(result['diagnostics_enabled']).lower()}")
        print(f"audit_enabled={str(result['audit_enabled']).lower()}")
        print(f"receipts_enabled={str(result['receipts_enabled']).lower()}")
        print(f"send_queue_enabled={str(result['send_queue_enabled']).lower()}")
        print(f"send_queue_store={result['send_queue_store']}")
        print(f"send_queue_db={result['send_queue_db']}")
        print(f"send_queue_max_items={result['send_queue_max_items']}")
        print(f"send_queue_max_attempts={result['send_queue_max_attempts']}")
        print(
            "send_queue_retry_base_seconds="
            f"{result['send_queue_retry_base_seconds']}"
        )
        print(
            "send_queue_retry_max_seconds="
            f"{result['send_queue_retry_max_seconds']}"
        )
        print(
            "send_queue_worker_enabled="
            f"{str(result['send_queue_worker_enabled']).lower()}"
        )
        print(
            "send_queue_worker_interval_seconds="
            f"{result['send_queue_worker_interval_seconds']}"
        )
        print(
            "send_queue_worker_batch_size="
            f"{result['send_queue_worker_batch_size']}"
        )
        print(f"chat_provider={result['chat_provider']}")
        print(f"chat_model={result['chat_model']}")
        print(f"chat_api_key={result['chat_api_key']}")
        print(f"endpoint_url={result['endpoint_url']}")
        print(f"chat_temperature={result['chat_temperature']}")
        print(f"chat_max_tokens={result['chat_max_tokens']}")
        print(f"timeout_seconds={result['timeout_seconds']}")
        print(f"public_message={result['public_message']}")
        return 0 if result["ok"] else 1

    if args.task == "context":
        result = run_context_smoke(
            config,
            message_text=args.message or "你好，守岸人。",
        )
        print(f"ok={str(result['ok']).lower()}")
        print(f"persona_profile_id={result['persona_profile_id']}")
        print(f"persona_display_name={result['persona_display_name']}")
        print(f"persona_source_refs={result['persona_source_refs']}")
        print(f"knowledge_source_refs={result['knowledge_source_refs']}")
        print(f"style_rules={result['style_rules']}")
        print(f"role_boundaries={result['role_boundaries']}")
        print(f"forbidden_behaviors={result['forbidden_behaviors']}")
        print(f"knowledge_chunks={result['knowledge_chunks']}")
        print(f"memory_facts={result['memory_facts']}")
        print(f"history_turns={result['history_turns']}")
        print(f"emotion_signals={result['emotion_signals']}")
        print(f"emotion_labels={result['emotion_labels']}")
        print(f"prompt_messages={result['prompt_messages']}")
        print(f"system_prompt_chars={result['system_prompt_chars']}")
        print(f"prompt_original_user_chars={result['prompt_original_user_chars']}")
        print(f"prompt_user_budget={result['prompt_user_budget']}")
        print(f"user_prompt_chars={result['user_prompt_chars']}")
        print(f"prompt_total_chars={result['prompt_total_chars']}")
        print(f"prompt_budget_remaining={result['prompt_budget_remaining']}")
        print(f"prompt_clipped={str(result['prompt_clipped']).lower()}")
        print(f"prompt_user_clipped={str(result['prompt_user_clipped']).lower()}")
        print(f"prompt_truncated_sections={result['prompt_truncated_sections']}")
        print(
            "prompt_section_budgets="
            f"{_format_smoke_section_numbers(result['prompt_section_budgets'])}"
        )
        print(
            "prompt_section_chars="
            f"{_format_smoke_section_numbers(result['prompt_section_chars'])}"
        )
        print(f"context_budget={result['context_budget']}")
        print(f"max_messages={result['max_messages']}")
        print(f"risk_level={result['risk_level']}")
        print(f"error_kind={result['error_kind']}")
        print(f"public_message={result['public_message']}")
        if result["system_prompt_preview"]:
            print(f"system_prompt_preview={result['system_prompt_preview']}")
        return 0 if result["ok"] else 1

    if args.task == "why":
        result = run_why_smoke(
            config,
            message_text=args.message or "你好，守岸人。",
            session_type=SessionType(args.session_type),
            mentions_bot=args.mentions_bot == "true",
            sender_id=args.sender_id,
            group_id=args.group_id,
        )
        print(f"ok={str(result['ok']).lower()}")
        print(f"request_id={result['request_id']}")
        print(f"debug_id={result['debug_id']}")
        print(f"capability_id={result['capability_id']}")
        print(f"session_type={result['session_type']}")
        print(f"mentions_bot={str(result['mentions_bot']).lower()}")
        print(f"policy_allowed={str(result['policy_allowed']).lower()}")
        print(f"policy_reason={result['policy_reason']}")
        print(f"actor_roles={','.join(result['actor_roles'])}")
        print(f"risk_level={result['risk_level']}")
        print(f"privacy_level={result['privacy_level']}")
        print(f"reply_budget_reason={result['reply_budget_reason']}")
        print(f"max_messages={result['max_messages']}")
        print(f"context_budget={result['context_budget']}")
        print(f"prompt_messages={result['prompt_messages']}")
        print(f"system_prompt_chars={result['system_prompt_chars']}")
        print(f"user_prompt_chars={result['user_prompt_chars']}")
        print(f"prompt_total_chars={result['prompt_total_chars']}")
        print(f"prompt_budget_remaining={result['prompt_budget_remaining']}")
        print(f"prompt_clipped={str(result['prompt_clipped']).lower()}")
        print(f"prompt_user_clipped={str(result['prompt_user_clipped']).lower()}")
        print(f"prompt_truncated_sections={result['prompt_truncated_sections']}")
        print(f"knowledge_chunks={result['knowledge_chunks']}")
        print(f"memory_facts={result['memory_facts']}")
        print(f"history_turns={result['history_turns']}")
        print(f"emotion_signals={result['emotion_signals']}")
        print(f"llm_status={result['llm_status']}")
        print(f"llm_error_kind={result['llm_error_kind']}")
        print(f"llm_finish_reason={result['llm_finish_reason']}")
        print(f"llm_provider={result['llm_provider']}")
        print(f"llm_model={result['llm_model']}")
        print(f"ready_for_real_llm={str(result['ready_for_real_llm']).lower()}")
        print(f"llm_readiness_status={result['llm_readiness_status']}")
        print(f"llm_next_action={result['llm_next_action']}")
        print(
            "llm_readiness_reasons="
            f"{','.join(result['llm_readiness_reasons'])}"
        )
        print(f"llm_usage_prompt_tokens={result['llm_usage_prompt_tokens']}")
        print(f"llm_usage_completion_tokens={result['llm_usage_completion_tokens']}")
        print(f"llm_usage_total_tokens={result['llm_usage_total_tokens']}")
        print(f"send_request_created={str(result['send_request_created']).lower()}")
        print(f"receipt_state={result['receipt_state']}")
        if result["audit_tags"]:
            print(f"audit_tags={','.join(result['audit_tags'])}")
        if result["audit_events"]:
            print(f"audit_events={','.join(result['audit_events'])}")
        print(f"why_summary={result['why_summary']}")
        return 0 if result["ok"] else 1

    if args.task == "queue":
        result = run_queue_smoke(config)
        print(f"ok={str(result['ok']).lower()}")
        print(f"checked={result['checked']}")
        print(f"delivered={result['delivered']}")
        print(f"retryable_failed={result['retryable_failed']}")
        print(f"final_failed={result['final_failed']}")
        print(f"skipped={result['skipped']}")
        print(f"receipt_record_failed={result['receipt_record_failed']}")
        print(f"queued={result['queued']}")
        print(f"sent={result['sent']}")
        print(f"failed_retryable={result['failed_retryable']}")
        print(f"failed_final={result['failed_final']}")
        print(f"skipped_in_queue={result['skipped_in_queue']}")
        print(f"processing={result['processing']}")
        print(f"receipts_recorded={result['receipts_recorded']}")
        print(f"audit_events={result['audit_events']}")
        print(f"transport={result['transport']}")
        print(f"real_transport_used={str(result['real_transport_used']).lower()}")
        print(f"public_message={result['public_message']}")
        return 0 if result["ok"] else 1

    if args.task == "transport":
        result = run_transport_smoke(config)
        print(f"ok={str(result['ok']).lower()}")
        print(f"transport_adapter_import={result['transport_adapter_import']}")
        print(f"segment_text={str(result['segment_text']).lower()}")
        print(f"segment_image={str(result['segment_image']).lower()}")
        print(f"segment_json={str(result['segment_json']).lower()}")
        print(f"segment_mixed={str(result['segment_mixed']).lower()}")
        print(f"segment_fallback={str(result['segment_fallback']).lower()}")
        print(f"forward_api={str(result['forward_api']).lower()}")
        print(f"private_receipt_state={result['private_receipt_state']}")
        print(f"group_receipt_state={result['group_receipt_state']}")
        print(f"forward_receipt_state={result['forward_receipt_state']}")
        print(f"retryable_receipt_state={result['retryable_receipt_state']}")
        print(f"final_receipt_state={result['final_receipt_state']}")
        print(f"fake_private_calls={result['fake_private_calls']}")
        print(f"fake_group_calls={result['fake_group_calls']}")
        print(f"fake_group_forward_calls={result['fake_group_forward_calls']}")
        print(
            "provider_message_id_recorded="
            f"{str(result['provider_message_id_recorded']).lower()}"
        )
        print(
            "retcode_classification="
            f"{str(result['retcode_classification']).lower()}"
        )
        print(f"server_started={str(result['server_started']).lower()}")
        print(f"napcat_connected={str(result['napcat_connected']).lower()}")
        print(f"real_transport_used={str(result['real_transport_used']).lower()}")
        print(f"runtime_enabled={str(result['runtime_enabled']).lower()}")
        print(f"error_kind={result['error_kind']}")
        print(f"public_message={result['public_message']}")
        return 0 if result["ok"] else 1

    if args.task == "online-transport":
        result = run_online_transport_smoke(config)
        print(f"ok={str(result['ok']).lower()}")
        print(f"bot_provider_state={result['bot_provider_state']}")
        print(f"online_bots_count={result['online_bots_count']}")
        print(f"onebot_bots_count={result['onebot_bots_count']}")
        print(f"send_capable={str(result['send_capable']).lower()}")
        print(f"server_started={str(result['server_started']).lower()}")
        print(f"napcat_connected={str(result['napcat_connected']).lower()}")
        print(f"real_transport_used={str(result['real_transport_used']).lower()}")
        print(f"runtime_enabled={str(result['runtime_enabled']).lower()}")
        print(f"error_kind={result['error_kind']}")
        print(f"public_message={result['public_message']}")
        return 0 if result["ok"] else 1

    if args.task == "startup":
        result = run_nonebot_startup_smoke(
            config,
            env_file=config_path,
            runner=runner,
        )
        print(f"ok={str(result['ok']).lower()}")
        print(
            "nonebot_initialized="
            f"{str(result['nonebot_initialized']).lower()}"
        )
        print(
            "onebot_adapter_registered="
            f"{str(result['onebot_adapter_registered']).lower()}"
        )
        print(f"plugin_loaded={str(result['plugin_loaded']).lower()}")
        print(f"plugin_name={result['plugin_name']}")
        print(f"onebot_supported={str(result['onebot_supported']).lower()}")
        print(f"matcher_count={result['matcher_count']}")
        print(f"matcher_priorities={result['matcher_priorities']}")
        print(f"scheduler_access={result['scheduler_access']}")
        print(f"scheduler_jobs={result['scheduler_jobs']}")
        print(
            "send_queue_worker_registered="
            f"{str(result['send_queue_worker_registered']).lower()}"
        )
        print(f"server_started={str(result['server_started']).lower()}")
        print(f"napcat_connected={str(result['napcat_connected']).lower()}")
        print(f"real_transport_used={str(result['real_transport_used']).lower()}")
        print(f"runtime_enabled={str(result['runtime_enabled']).lower()}")
        print(
            "send_queue_worker_enabled="
            f"{str(result['send_queue_worker_enabled']).lower()}"
        )
        print(f"chat_provider={result['chat_provider']}")
        print(f"chat_model={result['chat_model']}")
        print(f"chat_api_key={result['chat_api_key']}")
        print(f"error_kind={result['error_kind']}")
        print(f"public_message={result['public_message']}")
        return 0 if result["ok"] else 1

    if args.task == "nonebot":
        result = run_nonebot_smoke(config, importer=importer)
        print(f"ok={str(result['ok']).lower()}")
        print(f"nonebot_import={result['nonebot_import']}")
        print(f"onebot_adapter_import={result['onebot_adapter_import']}")
        print(f"plugin_import={result['plugin_import']}")
        print(f"plugin_name={result['plugin_name']}")
        print(f"onebot_supported={str(result['onebot_supported']).lower()}")
        print(f"persona_profile_id={result['persona_profile_id']}")
        print(f"persona_files={result['persona_files']}")
        print(f"persona_missing={result['persona_missing']}")
        print(f"knowledge_files={result['knowledge_files']}")
        print(f"knowledge_missing={result['knowledge_missing']}")
        print(f"runtime_enabled={str(result['runtime_enabled']).lower()}")
        print(f"memory_enabled={str(result['memory_enabled']).lower()}")
        print(f"memory_db={result['memory_db']}")
        print(f"history_enabled={str(result['history_enabled']).lower()}")
        print(f"history_db={result['history_db']}")
        print(f"history_max_turns={result['history_max_turns']}")
        print(f"history_max_items={result['history_max_items']}")
        print(f"diagnostics_enabled={str(result['diagnostics_enabled']).lower()}")
        print(f"diagnostics_db={result['diagnostics_db']}")
        print(f"diagnostics_max_items={result['diagnostics_max_items']}")
        print(f"audit_enabled={str(result['audit_enabled']).lower()}")
        print(f"audit_store={result['audit_store']}")
        print(f"audit_db={result['audit_db']}")
        print(f"audit_max_items={result['audit_max_items']}")
        print(f"receipts_enabled={str(result['receipts_enabled']).lower()}")
        print(f"receipts_store={result['receipts_store']}")
        print(f"receipts_db={result['receipts_db']}")
        print(f"receipts_max_items={result['receipts_max_items']}")
        print(f"send_queue_enabled={str(result['send_queue_enabled']).lower()}")
        print(f"send_queue_store={result['send_queue_store']}")
        print(f"send_queue_db={result['send_queue_db']}")
        print(f"send_queue_max_items={result['send_queue_max_items']}")
        print(f"send_queue_max_attempts={result['send_queue_max_attempts']}")
        print(
            "send_queue_retry_base_seconds="
            f"{result['send_queue_retry_base_seconds']}"
        )
        print(
            "send_queue_retry_max_seconds="
            f"{result['send_queue_retry_max_seconds']}"
        )
        print(
            "send_queue_worker_enabled="
            f"{str(result['send_queue_worker_enabled']).lower()}"
        )
        print(
            "send_queue_worker_interval_seconds="
            f"{result['send_queue_worker_interval_seconds']}"
        )
        print(
            "send_queue_worker_batch_size="
            f"{result['send_queue_worker_batch_size']}"
        )
        print(f"emotion_enabled={str(result['emotion_enabled']).lower()}")
        print(f"emotion_max_signals={result['emotion_max_signals']}")
        print(f"rate_limit_enabled={str(result['rate_limit_enabled']).lower()}")
        print(f"rate_limit_store={result['rate_limit_store']}")
        print(f"rate_limit_db={result['rate_limit_db']}")
        print(f"rate_limit_window_seconds={result['rate_limit_window_seconds']}")
        print(
            "rate_limit_chat_global_max_requests="
            f"{result['rate_limit_chat_global_max_requests']}"
        )
        print(
            "rate_limit_chat_session_max_requests="
            f"{result['rate_limit_chat_session_max_requests']}"
        )
        print(
            "rate_limit_chat_sender_max_requests="
            f"{result['rate_limit_chat_sender_max_requests']}"
        )
        print(
            "rate_limit_target_min_interval_seconds="
            f"{result['rate_limit_target_min_interval_seconds']}"
        )
        print(f"rate_limit_bypass_roles={result['rate_limit_bypass_roles']}")
        print(f"quiet_hours_enabled={str(result['quiet_hours_enabled']).lower()}")
        print(f"quiet_hours_start={result['quiet_hours_start']}")
        print(f"quiet_hours_end={result['quiet_hours_end']}")
        print(f"quiet_hours_timezone={result['quiet_hours_timezone']}")
        print(f"quiet_hours_session_types={result['quiet_hours_session_types']}")
        print(f"quiet_hours_bypass_roles={result['quiet_hours_bypass_roles']}")
        print(f"admin_users={result['admin_users']}")
        print(f"enterprise_users={result['enterprise_users']}")
        print(f"trusted_users={result['trusted_users']}")
        print(f"blocked_users={result['blocked_users']}")
        print(f"chat_enabled={str(result['chat_enabled']).lower()}")
        print(f"chat_provider={result['chat_provider']}")
        print(f"chat_model={result['chat_model']}")
        print(f"chat_api_key={result['chat_api_key']}")
        print(f"ready_for_real_llm={str(result['ready_for_real_llm']).lower()}")
        print(f"llm_readiness_status={result['llm_readiness_status']}")
        print(f"llm_next_action={result['llm_next_action']}")
        print(
            "llm_readiness_reasons="
            f"{','.join(result['llm_readiness_reasons'])}"
        )
        print(f"llm_fix_hints={','.join(result['llm_fix_hints'])}")
        print(f"error_kind={result['error_kind']}")
        print(f"public_message={result['public_message']}")
        return 0 if result["ok"] else 1

    if args.task == "llm":
        result = run_llm_smoke(config)
        print(f"ok={str(result['ok']).lower()}")
        print(f"provider={result['provider']}")
        print(f"model={result['model']}")
        print(f"base_url={result['base_url']}")
        print(f"endpoint_url={result['endpoint_url']}")
        print(f"api_key={result['api_key']}")
        print(f"diagnostic_temperature={result['diagnostic_temperature']}")
        print(f"diagnostic_max_tokens={result['diagnostic_max_tokens']}")
        print(f"timeout_seconds={result['timeout_seconds']}")
        print(f"ready_for_real_llm={str(result['ready_for_real_llm']).lower()}")
        print(f"llm_readiness_status={result['llm_readiness_status']}")
        print(f"llm_next_action={result['llm_next_action']}")
        print(
            "llm_readiness_reasons="
            f"{','.join(result['llm_readiness_reasons'])}"
        )
        print(f"llm_fix_hints={','.join(result['llm_fix_hints'])}")
        print(f"error_kind={result['error_kind']}")
        print(f"llm_finish_reason={result['llm_finish_reason']}")
        print(f"public_message={result['public_message']}")
        if result["reply_preview"]:
            print(f"reply_preview={result['reply_preview']}")
        return 0 if result["ok"] else 1

    result = run_chat_smoke(
        config,
        message_text=args.message or "你好，守岸人。",
    )
    print(f"receipt_state={result['receipt_state']}")
    print(f"persona_profile_id={result['persona_profile_id']}")
    print(f"capability_id={result['capability_id']}")
    print(f"llm_status={result['llm_status']}")
    print(f"llm_error_kind={result['llm_error_kind']}")
    print(f"llm_finish_reason={result['llm_finish_reason']}")
    print(f"llm_provider={result['llm_provider']}")
    print(f"llm_model={result['llm_model']}")
    print(f"ready_for_real_llm={str(result['ready_for_real_llm']).lower()}")
    print(f"llm_readiness_status={result['llm_readiness_status']}")
    print(f"llm_next_action={result['llm_next_action']}")
    print(
        "llm_readiness_reasons="
        f"{','.join(result['llm_readiness_reasons'])}"
    )
    print(f"reply_preview_chars={result['reply_preview_chars']}")
    print(f"reply_text_hidden={str(result['reply_text_hidden']).lower()}")
    if result["audit_tags"]:
        print(f"audit_tags={','.join(result['audit_tags'])}")
    print(f"audit_events={','.join(result['audit_events'])}")
    return chat_smoke_exit_code(config, result)


if __name__ == "__main__":
    raise SystemExit(main())
