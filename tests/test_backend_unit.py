from __future__ import annotations

import json

from plugins.bot_unified_runtime.backend_unit import run_backend_unit
from plugins.bot_unified_runtime.config import Config


def test_backend_unit_runs_offline_chat_pipeline():
    result = run_backend_unit(
        "请用一句话说明你能做什么",
        config=Config(
            bot_chat_provider="static",
            bot_chat_model="static",
            bot_persona_files=[],
            bot_knowledge_files=[],
            bot_memory_enabled=False,
            bot_history_enabled=False,
            bot_audit_log_file="",
            bot_runtime_data_dir="",
        ),
    )

    assert result["ok"] is True
    assert result["receipt_state"] == "sent"
    assert result["capability_id"] == "bot.chat"
    assert result["reply"]
    assert "sent" in result["audit_events"]
    assert result["knowledge_chunks"] == 0
    assert result["web_search_used"] is False
    json.dumps(result, ensure_ascii=False)