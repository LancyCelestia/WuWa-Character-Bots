from __future__ import annotations

import json
from pathlib import Path

from plugins.bot_unified_runtime.backend_unit import run_backend_unit
from plugins.bot_unified_runtime.config import Config


def test_backend_unit_runs_offline_chat_pipeline(tmp_path: Path):
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
            # 台账 #1：空串会回退 repo 根 data/，必须指向 tmp_path。
            bot_runtime_data_dir=str(tmp_path),
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