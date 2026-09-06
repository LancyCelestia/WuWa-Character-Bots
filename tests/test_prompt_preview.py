from __future__ import annotations

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.runtime.prompt_preview import build_prompt_preview


def test_prompt_preview_builds_without_calling_llm():
    result = build_prompt_preview(
        "请介绍一下你自己",
        config=Config(
            bot_chat_provider="static",
            bot_chat_model="static",
            bot_persona_files=[],
            bot_knowledge_files=[],
            bot_runtime_data_dir="",
            bot_prompt_audit_dir="",
        ),
    )

    assert result["ok"] is True
    assert result["llm_called"] is False
    assert result["messages"]
    assert result["messages"][0]["role"] == "system"
    assert result["messages"][1]["role"] == "user"
    assert result["prompt_sha256"]
    assert result["artifact_path"] is None
