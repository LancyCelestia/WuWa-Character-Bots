from pathlib import Path

from plugins.bot_unified_runtime import smoke
from plugins.bot_unified_runtime.config import Config


def test_llm_setup_summarizes_safe_env_steps_without_writing_or_calling_network(tmp_path):
    persona_file = tmp_path / "shorekeeper.md"
    persona_file.write_text("守岸人来自黑海岸。\n说话温柔克制。", encoding="utf-8")

    result = smoke.run_llm_setup(
        Config(
            bot_persona_files=[str(persona_file)],
            bot_chat_provider="static",
            bot_chat_model="static",
        )
    )

    assert result["ok"] is True
    assert result["llm_setup_status"] == "needs_env_edit"
    assert result["llm_next_action"] == "configure_real_llm"
    assert result["ready_for_real_llm"] is False
    assert result["real_llm_probe_performed"] is False
    assert result["napcat_connected"] is False
    assert result["message_sent"] is False
    assert result["writes_env"] is False
    assert result["secrets_hidden"] is True
    assert result["required_env_keys"] == [
        "BOT_CHAT_PROVIDER",
        "BOT_CHAT_MODEL",
        "BOT_CHAT_API_KEY",
        "BOT_CHAT_BASE_URL",
        "BOT_CHAT_TEMPERATURE",
        "BOT_CHAT_MAX_TOKENS",
        "BOT_CHAT_TIMEOUT_SECONDS",
    ]
    assert result["safe_env_template"] == [
        "BOT_CHAT_PROVIDER=openai_compatible",
        "BOT_CHAT_MODEL=<model_name>",
        "BOT_CHAT_API_KEY=<real_api_key>",
        "BOT_CHAT_BASE_URL=<openai_compatible_base_url>",
        "BOT_CHAT_TEMPERATURE=0.7",
        "BOT_CHAT_MAX_TOKENS=512",
        "BOT_CHAT_TIMEOUT_SECONDS=30",
    ]
    assert result["next_commands"] == [
        "powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 config-smoke",
        "powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 persona-smoke",
        "powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 llm-smoke",
        "powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 dialogue-smoke",
        "powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 nonebot-smoke",
    ]
    assert "真实 LLM" in result["public_message"]
    assert str(tmp_path) not in repr(result)


def test_llm_setup_reports_blocked_config_and_missing_safe_keys(tmp_path):
    persona_file = tmp_path / "shorekeeper.md"
    persona_file.write_text("守岸人来自黑海岸。\n说话温柔克制。", encoding="utf-8")

    result = smoke.run_llm_setup(
        Config(
            bot_persona_files=[str(persona_file)],
            bot_chat_provider="openai_compatible",
            bot_chat_model="your-model-name",
            bot_chat_api_key="sk-live-secret",
            bot_chat_base_url="",
        )
    )

    assert result["ok"] is False
    assert result["llm_setup_status"] == "blocked"
    assert result["llm_next_action"] == "fix_config"
    assert result["missing_or_placeholder_env_keys"] == [
        "BOT_CHAT_MODEL",
        "BOT_CHAT_BASE_URL",
    ]
    assert result["llm_readiness_reasons"] == [
        "openai_model_missing",
        "openai_base_url_missing",
        "knowledge_files_empty",
    ]
    assert "BOT_CHAT_MODEL=<model_name>" in result["llm_fix_hints"]
    assert "BOT_CHAT_BASE_URL=<openai_compatible_base_url>" in result["llm_fix_hints"]
    assert "sk-live-secret" not in repr(result)
    assert str(tmp_path) not in repr(result)


def test_llm_setup_ready_config_points_to_llm_smoke_before_dialogue(tmp_path):
    persona_file = tmp_path / "shorekeeper.md"
    persona_file.write_text("守岸人来自黑海岸。\n说话温柔克制。", encoding="utf-8")
    knowledge_file = tmp_path / "bot.md"
    knowledge_file.write_text("守岸人会守望漂泊者。", encoding="utf-8")

    result = smoke.run_llm_setup(
        Config(
            bot_persona_files=[str(persona_file)],
            bot_knowledge_files=[str(knowledge_file)],
            bot_chat_provider="openai_compatible",
            bot_chat_model="diag-model",
            bot_chat_api_key="sk-live-secret",
            bot_chat_base_url="https://llm.example/v1",
        )
    )

    assert result["ok"] is True
    assert result["llm_setup_status"] == "ready_for_probe"
    assert result["llm_next_action"] == "llm_smoke"
    assert result["ready_for_real_llm"] is True
    assert result["missing_or_placeholder_env_keys"] == []
    assert result["llm_readiness_reasons"] == []
    assert result["next_commands"][0].endswith("llm-smoke")
    assert result["next_commands"][1].endswith("dialogue-smoke")
    assert "sk-live-secret" not in repr(result)


def test_llm_setup_cli_prints_safe_summary(monkeypatch, capsys, tmp_path):
    persona_file = tmp_path / "shorekeeper.md"
    persona_file.write_text("守岸人来自黑海岸。\n说话温柔克制。", encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                f"BOT_PERSONA_FILES={persona_file.as_posix()}",
                "BOT_CHAT_PROVIDER=static",
                "BOT_CHAT_MODEL=static",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["smoke.py", "llm-setup"])

    exit_code = smoke.main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "llm_setup_status=needs_env_edit" in output
    assert "llm_next_action=configure_real_llm" in output
    assert "ready_for_real_llm=false" in output
    assert "real_llm_probe_performed=false" in output
    assert "napcat_connected=false" in output
    assert "message_sent=false" in output
    assert "writes_env=false" in output
    assert "secrets_hidden=true" in output
    assert "required_env_keys=BOT_CHAT_PROVIDER,BOT_CHAT_MODEL" in output
    assert "safe_env_template=BOT_CHAT_PROVIDER=openai_compatible;" in output
    assert "BOT_CHAT_API_KEY=<real_api_key>" in output
    assert "next_commands=powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 config-smoke;" in output
    assert str(tmp_path) not in output


def test_dev_script_exposes_llm_setup_task():
    text = Path("scripts/dev.ps1").read_text(encoding="utf-8-sig")

    assert '"llm-setup"' in text
    assert "Invoke-LlmSetup" in text
    assert "plugins.bot_unified_runtime.smoke" in text
    assert '"llm-setup"' in text
