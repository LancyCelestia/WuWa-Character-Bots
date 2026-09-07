from __future__ import annotations

from pathlib import Path

from plugins.bot_unified_runtime import _log_runtime_event
from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.sources.runtime_event_log import RuntimeEventLog


def test_runtime_boundary_log_excludes_message_body(tmp_path: Path) -> None:
    log = RuntimeEventLog(tmp_path / "runtime.log")
    message = IncomingMessage(
        platform="telegram",
        adapter="telegram",
        bot_id="bot-1",
        session_id="private_1",
        session_type=SessionType.PRIVATE,
        sender_id="user-1",
        plain_text="secret user message",
    )

    _log_runtime_event(
        log,
        "INFO",
        "incoming_normalized",
        message=message,
        capability_id="bot.chat",
    )

    line = (tmp_path / "runtime.log").read_text(encoding="utf-8")
    assert message.request_id in line
    assert "telegram" in line
    assert "bot.chat" in line
    assert "secret user message" not in line


def test_runtime_log_aggregates_llm_usage_once_per_request(tmp_path: Path) -> None:
    log = RuntimeEventLog(tmp_path / "runtime.log")
    date_text = log._ts()[:10]
    for _ in range(2):
        log.info(
            "transport_receipt",
            request_id="req-1",
            model="terra",
            prompt_tokens=10,
            completion_tokens=4,
            total_tokens=14,
        )
    log.info(
        "transport_receipt",
        request_id="req-2",
        model="luna",
        prompt_tokens=3,
        completion_tokens=2,
        total_tokens=5,
    )

    usage = log.aggregate_llm_usage(date_text)
    assert usage["prompt_tokens"] == 13
    assert usage["completion_tokens"] == 6
    assert usage["total_tokens"] == 19
    assert usage["by_model"] == {"terra": 14, "luna": 5}
