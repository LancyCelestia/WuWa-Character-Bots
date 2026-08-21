from __future__ import annotations

from datetime import datetime, timezone

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.config_readiness import run_config_smoke
from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    ReceiptState,
    RiskLevel,
    SessionType,
)
from plugins.bot_unified_runtime.policy import (
    QuietHoursChecker,
    QuietHoursSettings,
    build_quiet_hours_checker,
    build_quiet_hours_settings,
)
from plugins.bot_unified_runtime.runtime import RuntimePipeline
from plugins.bot_unified_runtime.sender import InMemorySendQueue


def make_message(
    *,
    session_type: SessionType = SessionType.GROUP,
    roles: list[str] | None = None,
) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot.v11",
        bot_id="10000",
        session_id="group:10001"
        if session_type is SessionType.GROUP
        else "private:42",
        session_type=session_type,
        sender_id="42",
        group_id="10001" if session_type is SessionType.GROUP else None,
        plain_text="守岸人你好",
        raw_segments=[{"type": "text", "data": {"text": "守岸人你好"}}],
        mentions_bot=True,
        sender_roles=roles or ["user"],
    )


def fixed_utc(hour: int, minute: int = 0):
    return lambda: datetime(2026, 7, 8, hour, minute, tzinfo=timezone.utc)


def test_quiet_hours_blocks_group_chat_during_overnight_window():
    checker = QuietHoursChecker(
        QuietHoursSettings(
            enabled=True,
            start_time="23:00",
            end_time="07:00",
            timezone_name="UTC",
            session_types=["group"],
        ),
        clock=fixed_utc(23, 30),
    )

    decision = checker.check(make_message(), "bot.chat")

    assert decision.allowed is False
    assert decision.reason == "quiet_hours"
    assert "quiet_hours:blocked" in decision.audit_tags


def test_quiet_hours_allows_group_chat_outside_window():
    checker = QuietHoursChecker(
        QuietHoursSettings(
            enabled=True,
            start_time="23:00",
            end_time="07:00",
            timezone_name="UTC",
            session_types=["group"],
        ),
        clock=fixed_utc(12),
    )

    decision = checker.check(make_message(), "bot.chat")

    assert decision.allowed is True
    assert decision.reason == "outside_quiet_hours"
    assert decision.audit_tags == ["quiet_hours:ok"]


def test_quiet_hours_default_scope_does_not_block_private_direct_help():
    checker = QuietHoursChecker(
        QuietHoursSettings(
            enabled=True,
            start_time="23:00",
            end_time="07:00",
            timezone_name="UTC",
        ),
        clock=fixed_utc(23, 30),
    )

    decision = checker.check(make_message(session_type=SessionType.PRIVATE), "bot.chat")

    assert decision.allowed is True
    assert decision.reason == "session_type_excluded"
    assert decision.audit_tags == ["quiet_hours:session_excluded"]


def test_quiet_hours_allows_bypass_role():
    checker = QuietHoursChecker(
        QuietHoursSettings(
            enabled=True,
            start_time="23:00",
            end_time="07:00",
            timezone_name="UTC",
            session_types=["group"],
            bypass_roles=["admin"],
        ),
        clock=fixed_utc(23, 30),
    )

    decision = checker.check(make_message(roles=["user", "admin"]), "bot.chat")

    assert decision.allowed is True
    assert decision.reason == "role_bypass"
    assert decision.audit_tags == ["quiet_hours:bypass_role"]


def test_pipeline_blocks_quiet_hours_before_capability_runs():
    audit = InMemoryAuditLogger()
    queue = InMemorySendQueue(audit_logger=audit)
    checker = QuietHoursChecker(
        QuietHoursSettings(
            enabled=True,
            start_time="23:00",
            end_time="07:00",
            timezone_name="UTC",
            session_types=["group"],
        ),
        clock=fixed_utc(23, 30),
    )
    pipeline = RuntimePipeline(
        send_queue=queue,
        audit_logger=audit,
        quiet_hours_checker=checker,
    )
    called = False

    def capability(message, decision):
        nonlocal called
        called = True
        return CapabilityResult(
            request_id=message.request_id,
            capability_id=decision.capability_id,
            kind="text",
            body="should not run",
            risk_level=RiskLevel.LOW,
        )

    receipt = pipeline.handle(make_message(), capability, capability_id="bot.chat")

    assert receipt.state is ReceiptState.BLOCKED
    assert receipt.transport == "policy"
    assert "安静时间" in receipt.public_message
    assert called is False
    assert queue.sent_requests == []
    [record] = audit.list_records(receipt.request_id)
    assert record.stage == "policy"
    assert record.event == "quiet_hours_blocked"
    assert "quiet_hours" in record.private_debug


def test_quiet_hours_config_builder_and_smoke_summary():
    config = Config(
        bot_quiet_hours_enabled=True,
        bot_quiet_hours_start="22:30",
        bot_quiet_hours_end="08:15",
        bot_quiet_hours_timezone="UTC",
        bot_quiet_hours_session_types="group;private",
        bot_quiet_hours_bypass_roles="admin,trusted",
    )

    settings = build_quiet_hours_settings(config)
    checker = build_quiet_hours_checker(config)
    result = run_config_smoke(config)

    assert settings.enabled is True
    assert settings.start_time == "22:30"
    assert settings.end_time == "08:15"
    assert settings.timezone_name == "UTC"
    assert settings.session_types == ["group", "private"]
    assert settings.bypass_roles == ["admin", "trusted"]
    assert checker.settings == settings
    assert result["quiet_hours_enabled"] is True
    assert result["quiet_hours_start"] == "22:30"
    assert result["quiet_hours_end"] == "08:15"
    assert result["quiet_hours_timezone"] == "UTC"
    assert result["quiet_hours_session_types"] == "group,private"
    assert result["quiet_hours_bypass_roles"] == "admin,trusted"
