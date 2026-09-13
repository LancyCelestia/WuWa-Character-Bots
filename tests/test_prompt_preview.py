from __future__ import annotations

from pathlib import Path

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.runtime.prompt_preview import build_prompt_preview


def test_prompt_preview_builds_without_calling_llm(tmp_path: Path):
    result = build_prompt_preview(
        "请介绍一下你自己",
        config=Config(
            bot_chat_provider="static",
            bot_chat_model="static",
            bot_persona_files=[],
            bot_knowledge_files=[],
            # 台账 #1：空串会回退 repo 根 data/，必须指向 tmp_path。
            bot_runtime_data_dir=str(tmp_path),
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
