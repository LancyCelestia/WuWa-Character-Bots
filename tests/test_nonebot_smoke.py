from __future__ import annotations

import importlib
from types import SimpleNamespace

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime import smoke


def test_nonebot_smoke_reports_plugin_metadata_and_config_summary(tmp_path):
    persona_file = tmp_path / "shorekeeper.md"
    persona_file.write_text("守岸人来自黑海岸。", encoding="utf-8")
    missing_knowledge = tmp_path / "missing-knowledge.md"

    def importer(name: str):
        if name in {"nonebot", "nonebot.adapters.onebot.v11"}:
            return SimpleNamespace(__name__=name)
        return importlib.import_module(name)

    result = smoke.run_nonebot_smoke(
        Config(
            bot_persona_profile_id="shorekeeper",
            bot_persona_display_name="守岸人",
            bot_persona_files=[str(persona_file)],
            bot_knowledge_files=[str(missing_knowledge)],
            bot_runtime_enabled=False,
            bot_memory_enabled=True,
            bot_memory_db_path=str(tmp_path / "memory.sqlite3"),
            bot_history_enabled=True,
            bot_history_db_path=str(tmp_path / "history.sqlite3"),
            bot_diagnostics_enabled=True,
            bot_diagnostics_db_path=str(tmp_path / "diagnostics.sqlite3"),
            bot_diagnostics_max_items=25,
            bot_audit_enabled=True,
            bot_audit_db_path=str(tmp_path / "audit.sqlite3"),
            bot_audit_max_items=35,
            bot_receipts_enabled=True,
            bot_receipts_db_path=str(tmp_path / "receipts.sqlite3"),
            bot_receipts_max_items=45,
            bot_send_queue_enabled=True,
            bot_send_queue_db_path=str(tmp_path / "send_queue.sqlite3"),
            bot_send_queue_max_items=55,
            bot_send_queue_max_attempts=4,
            bot_send_queue_retry_base_seconds=8,
            bot_send_queue_retry_max_seconds=80,
            bot_send_queue_worker_enabled=True,
            bot_send_queue_worker_interval_seconds=11,
            bot_send_queue_worker_batch_size=5,
            bot_emotion_enabled=True,
            bot_emotion_max_signals=3,
            bot_rate_limit_enabled=True,
            bot_rate_limit_window_seconds=30,
            bot_rate_limit_chat_global_max_requests=40,
            bot_rate_limit_chat_session_max_requests=7,
            bot_rate_limit_chat_sender_max_requests=5,
            bot_rate_limit_target_min_interval_seconds=2,
            bot_rate_limit_bypass_roles=["admin", "trusted"],
            bot_rate_limit_db_path=str(tmp_path / "rate_limit.sqlite3"),
            bot_quiet_hours_enabled=True,
            bot_quiet_hours_start="22:30",
            bot_quiet_hours_end="08:15",
            bot_quiet_hours_timezone="UTC",
            bot_quiet_hours_session_types=["group", "private"],
            bot_quiet_hours_bypass_roles=["admin", "trusted"],
            bot_admin_user_ids=["10001"],
            bot_enterprise_user_ids=["20001", "20002"],
            bot_trusted_user_ids=["30001"],
            bot_blocked_user_ids=["40001"],
            bot_chat_provider="openai_compatible",
            bot_chat_model="model-for-smoke",
            bot_chat_api_key="sk-live-secret",
        ),
        importer=importer,
    )

    assert result["ok"] is True
    assert result["nonebot_import"] == "ok"
    assert result["onebot_adapter_import"] == "ok"
    assert result["plugin_import"] == "ok"
    assert result["plugin_name"] == "Bot Unified Runtime"
    assert result["onebot_supported"] is True
    assert result["persona_profile_id"] == "shorekeeper"
    assert result["persona_files"] == 1
    assert result["persona_missing"] == 0
    assert result["knowledge_files"] == 1
    assert result["knowledge_missing"] == 1
    assert result["runtime_enabled"] is False
    assert result["memory_enabled"] is True
    assert result["memory_db"] == "set"
    assert result["history_enabled"] is True
    assert result["history_db"] == "set"
    assert result["history_max_turns"] == 6
    assert result["history_max_items"] == 1000
    assert result["diagnostics_enabled"] is True
    assert result["diagnostics_db"] == "set"
    assert result["diagnostics_max_items"] == 25
    assert result["audit_enabled"] is True
    assert result["audit_store"] == "sqlite"
    assert result["audit_db"] == "set"
    assert result["audit_max_items"] == 35
    assert result["receipts_enabled"] is True
    assert result["receipts_store"] == "sqlite"
    assert result["receipts_db"] == "set"
    assert result["receipts_max_items"] == 45
    assert result["send_queue_enabled"] is True
    assert result["send_queue_store"] == "sqlite"
    assert result["send_queue_db"] == "set"
    assert result["send_queue_max_items"] == 55
    assert result["send_queue_max_attempts"] == 4
    assert result["send_queue_retry_base_seconds"] == 8
    assert result["send_queue_retry_max_seconds"] == 80
    assert result["send_queue_worker_enabled"] is True
    assert result["send_queue_worker_interval_seconds"] == 11
    assert result["send_queue_worker_batch_size"] == 5
    assert result["emotion_enabled"] is True
    assert result["emotion_max_signals"] == 3
    assert result["rate_limit_enabled"] is True
    assert result["rate_limit_window_seconds"] == 30
    assert result["rate_limit_chat_global_max_requests"] == 40
    assert result["rate_limit_chat_session_max_requests"] == 7
    assert result["rate_limit_chat_sender_max_requests"] == 5
    assert result["rate_limit_target_min_interval_seconds"] == 2
    assert result["rate_limit_bypass_roles"] == "admin,trusted"
    assert result["rate_limit_store"] == "sqlite"
    assert result["rate_limit_db"] == "set"
    assert result["quiet_hours_enabled"] is True
    assert result["quiet_hours_start"] == "22:30"
    assert result["quiet_hours_end"] == "08:15"
    assert result["quiet_hours_timezone"] == "UTC"
    assert result["quiet_hours_session_types"] == "group,private"
    assert result["quiet_hours_bypass_roles"] == "admin,trusted"
    assert result["admin_users"] == 1
    assert result["enterprise_users"] == 2
    assert result["trusted_users"] == 1
    assert result["blocked_users"] == 1
    assert result["chat_provider"] == "openai_compatible"
    assert result["chat_model"] == "model-for-smoke"
    assert result["chat_api_key"] == "set"
    assert result["ready_for_real_llm"] is False
    assert result["llm_readiness_status"] == "blocked"
    assert "knowledge_file_missing" in result["llm_readiness_reasons"]
    assert result["llm_fix_hints"] == [
        "BOT_KNOWLEDGE_FILES=<optional_existing_md_txt_docx_paths>",
    ]
    assert "sk-live-secret" not in result["public_message"]
    assert "sk-live-secret" not in result["private_debug"]
    assert str(tmp_path / "audit.sqlite3") not in result["public_message"]
    assert str(tmp_path / "receipts.sqlite3") not in result["public_message"]
    assert str(tmp_path / "send_queue.sqlite3") not in result["public_message"]


def test_nonebot_smoke_fails_when_onebot_adapter_is_missing():
    def importer(name: str):
        if name == "nonebot":
            return SimpleNamespace(__name__=name)
        if name == "nonebot.adapters.onebot.v11":
            raise ImportError("adapter missing api_key=sk-live-secret")
        return importlib.import_module(name)

    result = smoke.run_nonebot_smoke(
        Config(bot_chat_api_key="sk-live-secret"),
        importer=importer,
    )

    assert result["ok"] is False
    assert result["nonebot_import"] == "ok"
    assert result["onebot_adapter_import"] == "missing"
    assert result["plugin_import"] == "ok"
    assert result["error_kind"] == "dependency_missing"
    assert "sk-live-secret" not in result["public_message"]
    assert "api_key=[redacted]" in result["private_debug"]


def test_nonebot_smoke_cli_prints_runtime_switch(monkeypatch, capsys, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("BOT_RUNTIME_ENABLED=false\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["smoke.py", "nonebot"])

    def importer(name: str):
        if name in {"nonebot", "nonebot.adapters.onebot.v11"}:
            return SimpleNamespace(__name__=name)
        return importlib.import_module(name)

    exit_code = smoke.main(importer=importer)
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "runtime_enabled=false" in output
    assert "rate_limit_enabled=true" in output
    assert "rate_limit_store=memory" in output
    assert "rate_limit_chat_global_max_requests=60" in output
    assert "rate_limit_target_min_interval_seconds=0" in output
    assert "quiet_hours_enabled=false" in output
    assert "quiet_hours_session_types=group" in output
    assert "audit_store=memory" in output
    assert "receipts_store=memory" in output
    assert "send_queue_enabled=false" in output
    assert "send_queue_store=memory" in output
    assert "send_queue_db=missing" in output
    assert "send_queue_worker_enabled=false" in output
    assert "send_queue_worker_interval_seconds=30" in output
    assert "send_queue_worker_batch_size=20" in output
    assert "ready_for_real_llm=false" in output
    assert "llm_readiness_status=blocked" in output
    assert "llm_readiness_reasons=persona_files_empty,provider_not_real,knowledge_files_empty" in output
    assert (
        "llm_fix_hints=BOT_PERSONA_FILES=<existing_md_txt_docx_paths>"
    ) in output


def test_nonebot_startup_smoke_parses_child_result_and_redacts_secret(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("BOT_CHAT_API_KEY=sk-live-secret\n", encoding="utf-8")

    def runner(_env_path, _timeout_seconds):
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "NoneBot is initializing...\n"
                '__BOT_STARTUP_SMOKE__{"ok":true,'
                '"nonebot_initialized":true,'
                '"onebot_adapter_registered":true,'
                '"plugin_loaded":true,'
                '"plugin_name":"Bot Unified Runtime",'
                '"onebot_supported":true,'
                '"matcher_count":3,'
                '"matcher_priorities":{"20":1,"21":1,"50":1},'
                '"scheduler_access":"ok",'
                '"scheduler_jobs":["bot_send_queue_worker"],'
                '"server_started":false,'
                '"napcat_connected":false,'
                '"real_transport_used":false}'
            ),
            stderr="debug api_key=sk-live-secret",
        )

    result = smoke.run_nonebot_startup_smoke(
        Config(
            bot_chat_api_key="sk-live-secret",
            bot_send_queue_worker_enabled=True,
        ),
        env_file=env_file,
        runner=runner,
    )

    assert result["ok"] is True
    assert result["error_kind"] == "none"
    assert result["nonebot_initialized"] is True
    assert result["onebot_adapter_registered"] is True
    assert result["plugin_loaded"] is True
    assert result["plugin_name"] == "Bot Unified Runtime"
    assert result["onebot_supported"] is True
    assert result["matcher_count"] == 3
    assert result["matcher_priorities"] == "20:1,21:1,50:1"
    assert result["scheduler_access"] == "ok"
    assert result["scheduler_jobs"] == 1
    assert result["send_queue_worker_registered"] is True
    assert result["server_started"] is False
    assert result["napcat_connected"] is False
    assert result["real_transport_used"] is False
    assert result["chat_api_key"] == "set"
    assert "sk-live-secret" not in result["public_message"]
    assert "sk-live-secret" not in result["private_debug"]
    assert "api_key=[redacted]" in result["private_debug"]


def test_nonebot_startup_smoke_reports_child_failure_without_leaking_secret(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("BOT_CHAT_API_KEY=sk-live-secret\n", encoding="utf-8")

    def runner(_env_path, _timeout_seconds):
        return SimpleNamespace(
            returncode=1,
            stdout='__BOT_STARTUP_SMOKE__{"ok":false,"error_kind":"startup_failed"}',
            stderr="Authorization: Bearer sk-live-secret",
        )

    result = smoke.run_nonebot_startup_smoke(
        Config(bot_chat_api_key="sk-live-secret"),
        env_file=env_file,
        runner=runner,
    )

    assert result["ok"] is False
    assert result["error_kind"] == "startup_failed"
    assert "sk-live-secret" not in result["public_message"]
    assert "sk-live-secret" not in result["private_debug"]
    assert "Bearer [redacted]" in result["private_debug"]


def test_nonebot_startup_smoke_cli_prints_safe_summary(monkeypatch, capsys, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("BOT_CHAT_API_KEY=sk-live-secret\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["smoke.py", "startup"])

    def runner(_env_path, _timeout_seconds):
        return SimpleNamespace(
            returncode=0,
            stdout=(
                '__BOT_STARTUP_SMOKE__{"ok":true,'
                '"nonebot_initialized":true,'
                '"onebot_adapter_registered":true,'
                '"plugin_loaded":true,'
                '"plugin_name":"Bot Unified Runtime",'
                '"onebot_supported":true,'
                '"matcher_count":3,'
                '"matcher_priorities":{"20":1,"21":1,"50":1},'
                '"scheduler_access":"ok",'
                '"scheduler_jobs":[],'
                '"server_started":false,'
                '"napcat_connected":false,'
                '"real_transport_used":false}'
            ),
            stderr="",
        )

    exit_code = smoke.main(runner=runner)
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "nonebot_initialized=true" in output
    assert "onebot_adapter_registered=true" in output
    assert "plugin_loaded=true" in output
    assert "matcher_count=3" in output
    assert "matcher_priorities=20:1,21:1,50:1" in output
    assert "server_started=false" in output
    assert "napcat_connected=false" in output
    assert "real_transport_used=false" in output
    assert "sk-live-secret" not in output


def test_transport_smoke_validates_onebot_segments_and_fake_transport_safely():
    result = smoke.run_transport_smoke(Config())

    assert result["ok"] is True
    assert result["transport_adapter_import"] == "ok"
    assert result["segment_text"] is True
    assert result["segment_image"] is True
    assert result["segment_json"] is True
    assert result["segment_mixed"] is True
    assert result["segment_fallback"] is True
    assert result["forward_api"] is True
    assert result["private_receipt_state"] == "sent"
    assert result["group_receipt_state"] == "sent"
    assert result["forward_receipt_state"] == "sent"
    assert result["retryable_receipt_state"] == "failed_retryable"
    assert result["final_receipt_state"] == "failed_final"
    assert result["fake_private_calls"] == 3
    assert result["fake_group_calls"] == 1
    assert result["fake_group_forward_calls"] == 1
    assert result["provider_message_id_recorded"] is True
    assert result["retcode_classification"] is True
    assert result["real_transport_used"] is False
    assert result["napcat_connected"] is False
    assert result["server_started"] is False
    assert result["public_message"]

    serialized = repr(result)
    assert "secret-target" not in serialized
    assert "不应出现在 transport-smoke 摘要里的正文" not in serialized
    assert "transport-smoke-provider-message-id" not in serialized


def test_online_transport_smoke_inspects_online_bots_without_sending():
    class FakeOneBot:
        self_id = "123456789"

        def __init__(self) -> None:
            self.private_calls = 0
            self.group_calls = 0

        async def send_private_msg(self, **_kwargs):
            self.private_calls += 1
            raise AssertionError("online transport smoke must not send private messages")

        async def send_group_msg(self, **_kwargs):
            self.group_calls += 1
            raise AssertionError("online transport smoke must not send group messages")

    fake_bot = FakeOneBot()

    result = smoke.run_online_transport_smoke(
        Config(bot_runtime_enabled=True),
        bot_provider=lambda: {
            "123456789": fake_bot,
            "console-secret-bot": SimpleNamespace(self_id="console-secret-bot"),
        },
    )

    assert result["ok"] is True
    assert result["online_bots_count"] == 2
    assert result["onebot_bots_count"] == 1
    assert result["send_capable"] is True
    assert result["runtime_enabled"] is True
    assert result["server_started"] is False
    assert result["napcat_connected"] is False
    assert result["real_transport_used"] is False
    assert fake_bot.private_calls == 0
    assert fake_bot.group_calls == 0
    assert result["public_message"]

    serialized = repr(result)
    assert "123456789" not in serialized
    assert "console-secret-bot" not in serialized
