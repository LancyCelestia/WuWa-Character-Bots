"""Build a redacted prompt preview without invoking an LLM."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.capabilities.chat import (
    build_chat_prompt_with_diagnostics,
)
from plugins.bot_unified_runtime.character import build_character_context_provider
from plugins.bot_unified_runtime.character.history import (
    InMemoryConversationHistoryStore,
)
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.console_chat import load_smoke_config
from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.runtime.prompt_audit import PromptAuditStore
from plugins.bot_unified_runtime.runtime.settings import RuntimeSettingsStore


def build_prompt_preview(
    message_text: str,
    *,
    config: Config,
    write_artifact: bool = False,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    text = str(message_text or "").strip()
    if not text:
        raise ValueError("message_text must not be blank")
    preview_config = config.model_copy(
        update={
            "bot_history_enabled": False,
            "bot_memory_enabled": False,
            "bot_embedding_enabled": False,
            "bot_embedding_local_enabled": False,
            "bot_web_search_enabled": False,
            "bot_runtime_settings_dir": "",
        }
    )
    provider = build_character_context_provider(
        preview_config,
        conversation_history_provider=InMemoryConversationHistoryStore(),
        runtime_settings=RuntimeSettingsStore(),
    )
    message = IncomingMessage(
        platform="console",
        adapter="prompt-preview",
        bot_id="prompt-preview",
        session_id="private:prompt-preview",
        session_type=SessionType.PRIVATE,
        sender_id="prompt-preview-user",
        plain_text=text,
        raw_segments=[{"type": "text", "data": {"text": text}}],
        mentions_bot=True,
    )
    context = provider.build_context(
        request_id=message.request_id,
        sender_id=message.sender_id,
        session_id=message.session_id,
        query_text=text,
        platform=message.platform,
        adapter=message.adapter,
        bot_id=message.bot_id,
    )
    messages, diagnostics = build_chat_prompt_with_diagnostics(context)
    target_dir = output_dir
    if target_dir is None:
        target_dir = getattr(preview_config, "bot_prompt_audit_dir", "") or None
    store = PromptAuditStore(
        target_dir if write_artifact else None,
        max_chars=int(getattr(preview_config, "bot_prompt_audit_max_chars", 12000) or 12000),
        include_messages=True,
    )
    artifact = store.write(
        request_id=message.request_id,
        messages=messages,
        tools=[],
        llm_options={"model": preview_config.bot_chat_model},
        metadata={
            "mode": "preview",
            "persona_profile_id": preview_config.bot_persona_profile_id,
            "persona_files": list(preview_config.bot_persona_files),
            "knowledge_files": list(preview_config.bot_knowledge_files),
            "llm_called": False,
        },
    )
    return {
        "ok": True,
        "llm_called": False,
        "request_id": message.request_id,
        "prompt_sha256": artifact.prompt_sha256,
        "artifact_path": artifact.path,
        "messages": artifact.messages_redacted,
        "tool_ids": artifact.tool_ids,
        "diagnostics": {
            "system_prompt_chars": diagnostics.system_prompt_chars,
            "user_prompt_chars": diagnostics.user_prompt_chars,
            "total_prompt_chars": diagnostics.total_prompt_chars,
            "truncated_sections": list(diagnostics.truncated_sections),
            "knowledge_chunks": len(context.knowledge_results.chunks),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a redacted prompt preview without calling LLM")
    parser.add_argument("--message", required=True)
    parser.add_argument("--env", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    config = load_smoke_config(args.env)
    result = build_prompt_preview(
        args.message,
        config=config,
        write_artifact=args.write,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())