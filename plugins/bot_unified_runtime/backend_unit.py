"""One-shot backend execution unit for the core reply pipeline."""

from __future__ import annotations

import argparse
import contextlib
import inspect
import io
import json
import re
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.capabilities.chat import build_chat_capability
from plugins.bot_unified_runtime.character import build_character_context_provider
from plugins.bot_unified_runtime.character.history import (
    InMemoryConversationHistoryStore,
)
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.config_readiness import (
    llm_generation_parameter_errors,
    persona_context_preflight_errors,
)
from plugins.bot_unified_runtime.console_chat import (
    _reconfigure_stdio,
    load_smoke_config,
)
from plugins.bot_unified_runtime.contracts import (
    IncomingMessage,
    ReceiptState,
    SessionType,
)
from plugins.bot_unified_runtime.llm import (
    OpenAICompatibleLLMProvider,
    StaticLLMProvider,
)
from plugins.bot_unified_runtime.llm.model_router import build_model_router
from plugins.bot_unified_runtime.policy import (
    build_quiet_hours_checker,
    build_rate_limiter,
    build_reply_budget_settings,
    build_role_settings,
)
from plugins.bot_unified_runtime.runtime.pipeline import RuntimePipeline
from plugins.bot_unified_runtime.runtime.settings import RuntimeSettingsStore
from plugins.bot_unified_runtime.sender import InMemorySendQueue
from plugins.bot_unified_runtime.sources.web_search import build_web_search_provider


def _build_llm_provider(config: Config) -> Any:
    if config.bot_chat_provider == "openai_compatible":
        return OpenAICompatibleLLMProvider(
            api_key=config.bot_chat_api_key,
            model=config.bot_chat_model,
            base_url=config.bot_chat_base_url,
            timeout_seconds=config.bot_chat_timeout_seconds,
            proxy=config.bot_download_proxy,
        )
    return StaticLLMProvider(model=config.bot_chat_model)


def _build_runtime(config: Config) -> tuple[RuntimePipeline, Any]:
    audit_logger = InMemoryAuditLogger()
    send_queue = InMemorySendQueue(audit_logger=audit_logger)
    runtime_settings = RuntimeSettingsStore()
    pipeline = RuntimePipeline(
        send_queue=send_queue,
        audit_logger=audit_logger,
        reply_budget_settings=build_reply_budget_settings(config),
        role_settings=build_role_settings(config),
        group_command_prefix=config.bot_runtime_group_command_prefix,
        runtime_enabled=config.bot_runtime_enabled,
        rate_limiter=build_rate_limiter(config),
        quiet_hours_checker=build_quiet_hours_checker(config),
        forward_min_chars=config.bot_render_forward_min_chars,
        forward_max_nodes=config.bot_render_forward_max_nodes,
        forward_node_chars=config.bot_render_forward_node_chars,
    )
    capability_kwargs: dict[str, Any] = {
        "character_provider": build_character_context_provider(
            config,
            conversation_history_provider=InMemoryConversationHistoryStore(),
            runtime_settings=runtime_settings,
        ),
        "llm_provider": _build_llm_provider(config),
        "web_search_provider": build_web_search_provider(config),
        "web_max_results": int(getattr(config, "bot_web_search_max_results", 20) or 20),
        "web_page_proxy": str(getattr(config, "bot_download_proxy", "") or ""),
        "web_page_timeout_seconds": float(
            getattr(config, "bot_web_search_timeout_seconds", 6.0) or 6.0
        ),
        "web_page_max_chars": int(
            getattr(config, "bot_web_search_fetch_max_chars", 3000) or 3000
        ),
        "runtime_settings": runtime_settings,
        "model_router": (
            build_model_router(config)
            if config.bot_chat_provider == "openai_compatible"
            else None
        ),
        "reply_detail": config.bot_reply_detail,
        "temperature": config.bot_chat_temperature,
        "max_tokens": config.bot_chat_max_tokens,
        "model": config.bot_chat_model,
        "context_preflight_errors": persona_context_preflight_errors(config),
        "llm_preflight_errors": llm_generation_parameter_errors(config),
        "output_max_chars_per_message": config.bot_reply_max_chars_per_message,
    }
    supported = inspect.signature(build_chat_capability).parameters
    optional_values = {
        "request_budget_seconds": float(
            getattr(config, "bot_request_budget_seconds", 0.0) or 0.0
        ),
        "web_search_enabled": bool(
            getattr(config, "bot_web_search_enabled", False)
        ),
        "web_search_admin_notice": bool(
            getattr(config, "bot_web_search_admin_notice", False)
        ),
        "fast_mode": bool(getattr(config, "bot_chat_fast_mode", False)),
        "fast_max_tokens": int(
            getattr(config, "bot_chat_fast_max_tokens", config.bot_chat_max_tokens)
            or config.bot_chat_max_tokens
        ),
        "fast_max_candidates": int(
            getattr(config, "bot_chat_fast_max_candidates", 0) or 0
        ),
        "fast_context_budget": int(
            getattr(config, "bot_chat_fast_context_budget", 2400) or 2400
        ),
        "fast_web_max_queries": int(
            getattr(config, "bot_chat_fast_web_max_queries", 1) or 1
        ),
        "fast_skip_web_pages": bool(
            getattr(config, "bot_chat_fast_skip_web_pages", True)
        ),
    }
    capability_kwargs.update(
        {
            key: value
            for key, value in optional_values.items()
            if key in supported
        }
    )
    capability = build_chat_capability(**capability_kwargs)
    return pipeline, capability


def _reply_text(send_queue: Any, request_id: str) -> str:
    for request in reversed(getattr(send_queue, "sent_requests", [])):
        if request.request_id != request_id:
            continue
        content_ref = request.content.content_ref
        text = content_ref.get("text") or request.content.text_fallback
        return str(text or "").strip()
    return ""


def _tag_int(tags: list[str], prefix: str) -> int:
    for tag in tags:
        if tag.startswith(prefix):
            value = tag.removeprefix(prefix)
            if value.isdigit():
                return int(value)
    return 0


def _safe_tags(tags: list[str]) -> list[str]:
    secret_markers = re.compile(r"(?i)(key|token|cookie|secret|password|authorization)")
    return [tag for tag in tags if not secret_markers.search(tag)]


def run_backend_unit(
    message_text: str,
    *,
    env_file: str | Path | None = None,
    provider: str = "static",
    enable_web_search: bool = False,
    config: Config | None = None,
) -> dict[str, Any]:
    """Run one message through the core backend chain and return a safe report."""
    text = str(message_text or "").strip()
    if not text:
        raise ValueError("message_text must not be blank")
    if provider not in {"static", "openai_compatible"}:
        raise ValueError("provider must be static or openai_compatible")

    base_config = config or load_smoke_config(env_file)
    runtime_config = base_config.model_copy(
        update={
            "bot_chat_provider": provider,
            "bot_chat_model": "static" if provider == "static" else base_config.bot_chat_model,
            "bot_web_search_enabled": bool(enable_web_search),
            "bot_audit_log_file": "",
            "bot_history_enabled": False,
            "bot_memory_enabled": False,
            "bot_embedding_enabled": False,
            "bot_embedding_local_enabled": False,
            "bot_knowledge_db_path": "",
            "bot_runtime_settings_dir": "",
        }
    )
    pipeline, capability = _build_runtime(runtime_config)
    message = IncomingMessage(
        platform="console",
        adapter="backend-unit",
        bot_id="backend-unit",
        session_id="private:backend-unit",
        session_type=SessionType.PRIVATE,
        sender_id="backend-unit-user",
        sender_display_name="Backend Unit",
        plain_text=text,
        raw_segments=[{"type": "text", "data": {"text": text}}],
        mentions_bot=True,
    )

    with contextlib.redirect_stdout(io.StringIO()):
        receipt = pipeline.handle(message, capability, capability_id="bot.chat")

    send_request = next(
        (
            request
            for request in reversed(getattr(pipeline.send_queue, "sent_requests", []))
            if request.request_id == message.request_id
        ),
        None,
    )
    audit_records = pipeline.audit_logger.list_records(message.request_id)
    audit_events = [record.event for record in audit_records]
    audit_tags = _safe_tags(list(getattr(send_request, "audit_tags", [])))
    reply = _reply_text(pipeline.send_queue, message.request_id)
    knowledge_chunks = _tag_int(audit_tags, "context_knowledge_chunks:")
    web_search_used = "web_search:used" in audit_tags
    ok = receipt.state is ReceiptState.SENT and bool(reply)

    return {
        "ok": ok,
        "request_id": message.request_id,
        "receipt_state": receipt.state.value,
        "capability_id": "bot.chat",
        "reply": reply,
        "public_message": receipt.public_message,
        "provider": provider,
        "model": runtime_config.bot_chat_model,
        "knowledge_chunks": knowledge_chunks,
        "web_search_used": web_search_used,
        "audit_events": audit_events,
        "audit_tags": audit_tags,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One-shot backend core execution unit")
    parser.add_argument("--message", required=True, help="Message text for one backend execution")
    parser.add_argument("--env", default=None, help="Environment file; defaults to .env / .env.example")
    parser.add_argument(
        "--provider",
        choices=("static", "openai_compatible"),
        default="static",
        help="LLM provider; static is offline and the default",
    )
    parser.add_argument(
        "--web-search",
        action="store_true",
        help="Enable configured web search for eligible real-time questions",
    )
    args = parser.parse_args(argv)
    _reconfigure_stdio()
    try:
        result = run_backend_unit(
            args.message,
            env_file=args.env,
            provider=args.provider,
            enable_web_search=args.web_search,
        )
    except Exception as exc:  # noqa: BLE001 - CLI reports a safe operational error.
        print(json.dumps({"ok": False, "error_kind": type(exc).__name__}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
