from plugins.wuwa_unified_runtime.config import Config
from plugins.wuwa_unified_runtime.console_chat import run_once
from plugins.wuwa_unified_runtime.contracts import ReceiptState


def test_console_run_once_static_provider_sends_safely():
    config = Config(
        wuwa_persona_profile_id="shorekeeper",
        wuwa_persona_display_name="守岸人",
    )

    receipt = run_once(config, "你好，守岸人。")

    assert receipt.state is ReceiptState.SENT


def test_console_run_once_missing_persona_files_uses_safe_fallback():
    config = Config(wuwa_persona_profile_id="shorekeeper")

    receipt = run_once(config, "你好。")

    assert receipt.state is ReceiptState.SENT


def test_console_run_once_records_memory_history(tmp_path):
    from plugins.wuwa_unified_runtime.character.history import (
        InMemoryConversationHistoryStore,
    )

    store = InMemoryConversationHistoryStore()
    config = Config(wuwa_persona_profile_id="shorekeeper")

    receipt = run_once(config, "第一句话。", history_store=store)

    assert receipt.state is ReceiptState.SENT
    turns = store.retrieve(
        request_id="req_turns",
        platform="console",
        adapter="console-repl",
        bot_id="console-bot",
        session_id="console:repl",
        sender_id="console-user",
        max_turns=10,
        max_chars=2000,
    )
    assert any(turn.role == "user" for turn in turns.turns)
    assert any(turn.role == "assistant" for turn in turns.turns)


def test_console_capsys_output_contains_reply(capsys):
    config = Config(wuwa_persona_profile_id="shorekeeper")

    run_once(config, "你好。")

    captured = capsys.readouterr()
    assert captured.out.strip()


def test_console_run_once_blocked_message_returns_non_sent_state():
    config = Config(
        wuwa_persona_profile_id="shorekeeper",
        wuwa_runtime_enabled=False,
    )

    receipt = run_once(config, "你好。")

    assert receipt.state is ReceiptState.BLOCKED
