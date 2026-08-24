from __future__ import annotations

from datetime import datetime, timedelta, timezone

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    ReceiptState,
    SessionType,
)
from plugins.bot_unified_runtime.runtime import RuntimePipeline
from plugins.bot_unified_runtime.sender import InMemorySendQueue


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


def make_message(
    text: str,
    *,
    sender_id: str = "42",
    roles: list[str] | None = None,
    session_type: SessionType = SessionType.PRIVATE,
    group_id: str | None = None,
) -> IncomingMessage:
    session_id = f"private:{sender_id}"
    if session_type is SessionType.GROUP:
        session_id = f"group:{group_id or '10001'}"
    return IncomingMessage(
        platform="qq",
        adapter="onebot.v11",
        bot_id="10000",
        session_id=session_id,
        session_type=session_type,
        sender_id=sender_id,
        group_id=group_id,
        plain_text=text,
        raw_segments=[{"type": "text", "data": {"text": text}}],
        mentions_bot=True,
        sender_roles=roles or ["user"],
    )


def make_chat_capability(calls: list[str]):
    def capability(message: IncomingMessage, decision) -> CapabilityResult:
        calls.append(message.plain_text)
        return CapabilityResult(
            request_id=message.request_id,
            capability_id=decision.capability_id,
            kind="text",
            title="守岸人的回复",
            body=f"收到：{message.plain_text}",
            audit_tags=decision.audit_tags,
        )

    return capability


def make_pipeline(rate_limiter) -> tuple[RuntimePipeline, InMemoryAuditLogger, InMemorySendQueue]:
    audit = InMemoryAuditLogger()
    queue = InMemorySendQueue(audit_logger=audit)
    return (
        RuntimePipeline(
            send_queue=queue,
            audit_logger=audit,
            rate_limiter=rate_limiter,
        ),
        audit,
        queue,
    )


def test_chat_rate_limiter_blocks_before_llm_capability_after_session_window_is_exceeded():
    from plugins.bot_unified_runtime.policy import (
        InMemoryRateLimiter,
        RateLimitSettings,
    )

    clock = MutableClock()
    pipeline, audit, queue = make_pipeline(
        InMemoryRateLimiter(
            RateLimitSettings(
                window_seconds=60,
                chat_session_max_requests=2,
                chat_sender_max_requests=99,
            ),
            clock=clock,
        )
    )
    calls: list[str] = []
    capability = make_chat_capability(calls)

    first = pipeline.handle(make_message("第一句"), capability, capability_id="bot.chat")
    second = pipeline.handle(make_message("第二句"), capability, capability_id="bot.chat")
    third = pipeline.handle(make_message("第三句"), capability, capability_id="bot.chat")

    assert first.state is ReceiptState.SENT
    assert second.state is ReceiptState.SENT
    assert third.state is ReceiptState.BLOCKED
    assert calls == ["第一句", "第二句"]
    assert len(queue.sent_requests) == 2
    records = audit.list_records(third.request_id)
    assert records[-1].stage == "policy"
    assert records[-1].event == "rate_limited"
    assert "session_window_exceeded" in records[-1].private_debug
    assert "42" not in records[-1].private_debug


def test_chat_rate_limiter_counts_deep_help_budget_before_model_call():
    from plugins.bot_unified_runtime.policy import (
        InMemoryRateLimiter,
        RateLimitSettings,
    )

    pipeline, _audit, queue = make_pipeline(
        InMemoryRateLimiter(
            RateLimitSettings(
                window_seconds=60,
                chat_session_max_requests=4,
                chat_sender_max_requests=99,
            )
        )
    )
    calls: list[str] = []
    capability = make_chat_capability(calls)

    first = pipeline.handle(
        make_message("请你一步一步教我怎么配置 NoneBot 和 NapCat"),
        capability,
        capability_id="bot.chat",
    )
    second = pipeline.handle(
        make_message("请你一步一步教我怎么排查 LLM 配置"),
        capability,
        capability_id="bot.chat",
    )

    assert first.state is ReceiptState.SENT
    assert second.state is ReceiptState.BLOCKED
    assert calls == ["请你一步一步教我怎么配置 NoneBot 和 NapCat"]
    assert len(queue.sent_requests) == 1


def test_chat_rate_limiter_prunes_old_window_entries():
    from plugins.bot_unified_runtime.policy import (
        InMemoryRateLimiter,
        RateLimitSettings,
    )

    clock = MutableClock()
    pipeline, _audit, queue = make_pipeline(
        InMemoryRateLimiter(
            RateLimitSettings(
                window_seconds=10,
                chat_session_max_requests=1,
                chat_sender_max_requests=1,
            ),
            clock=clock,
        )
    )
    calls: list[str] = []
    capability = make_chat_capability(calls)

    first = pipeline.handle(make_message("第一句"), capability, capability_id="bot.chat")
    blocked = pipeline.handle(make_message("第二句"), capability, capability_id="bot.chat")
    clock.advance(11)
    allowed_after_window = pipeline.handle(
        make_message("第三句"),
        capability,
        capability_id="bot.chat",
    )

    assert first.state is ReceiptState.SENT
    assert blocked.state is ReceiptState.BLOCKED
    assert allowed_after_window.state is ReceiptState.SENT
    assert calls == ["第一句", "第三句"]
    assert len(queue.sent_requests) == 2


def test_chat_rate_limiter_can_bypass_admin_role():
    from plugins.bot_unified_runtime.policy import (
        InMemoryRateLimiter,
        RateLimitSettings,
    )

    pipeline, _audit, queue = make_pipeline(
        InMemoryRateLimiter(
            RateLimitSettings(
                window_seconds=60,
                chat_session_max_requests=1,
                chat_sender_max_requests=1,
                bypass_roles=["admin"],
            )
        )
    )
    calls: list[str] = []
    capability = make_chat_capability(calls)

    first = pipeline.handle(
        make_message("管理员第一句", roles=["user", "admin"]),
        capability,
        capability_id="bot.chat",
    )
    second = pipeline.handle(
        make_message("管理员第二句", roles=["user", "admin"]),
        capability,
        capability_id="bot.chat",
    )

    assert first.state is ReceiptState.SENT
    assert second.state is ReceiptState.SENT
    assert calls == ["管理员第一句", "管理员第二句"]
    assert len(queue.sent_requests) == 2


def test_chat_rate_limiter_blocks_global_quota_before_model_call():
    from plugins.bot_unified_runtime.policy import (
        InMemoryRateLimiter,
        RateLimitSettings,
    )

    pipeline, audit, queue = make_pipeline(
        InMemoryRateLimiter(
            RateLimitSettings(
                window_seconds=60,
                chat_global_max_requests=2,
                chat_session_max_requests=99,
                chat_sender_max_requests=99,
            )
        )
    )
    calls: list[str] = []
    capability = make_chat_capability(calls)

    first = pipeline.handle(
        make_message("第一句", sender_id="1"),
        capability,
        capability_id="bot.chat",
    )
    second = pipeline.handle(
        make_message("第二句", sender_id="2"),
        capability,
        capability_id="bot.chat",
    )
    third = pipeline.handle(
        make_message("第三句", sender_id="3"),
        capability,
        capability_id="bot.chat",
    )

    assert first.state is ReceiptState.SENT
    assert second.state is ReceiptState.SENT
    assert third.state is ReceiptState.BLOCKED
    assert calls == ["第一句", "第二句"]
    assert len(queue.sent_requests) == 2
    [record] = audit.list_records(third.request_id)
    assert record.event == "rate_limited"
    assert "global_window_exceeded" in record.private_debug
    assert "sender_id" not in record.private_debug


def test_chat_rate_limiter_blocks_target_min_interval_across_group_senders():
    from plugins.bot_unified_runtime.policy import (
        InMemoryRateLimiter,
        RateLimitSettings,
    )

    clock = MutableClock()
    pipeline, audit, queue = make_pipeline(
        InMemoryRateLimiter(
            RateLimitSettings(
                window_seconds=60,
                chat_global_max_requests=99,
                chat_session_max_requests=99,
                chat_sender_max_requests=99,
                target_min_interval_seconds=10,
            ),
            clock=clock,
        )
    )
    calls: list[str] = []
    capability = make_chat_capability(calls)

    first = pipeline.handle(
        make_message(
            "第一句",
            sender_id="1",
            session_type=SessionType.GROUP,
            group_id="10001",
        ),
        capability,
        capability_id="bot.chat",
    )
    blocked = pipeline.handle(
        make_message(
            "第二句",
            sender_id="2",
            session_type=SessionType.GROUP,
            group_id="10001",
        ),
        capability,
        capability_id="bot.chat",
    )
    clock.advance(11)
    allowed_after_interval = pipeline.handle(
        make_message(
            "第三句",
            sender_id="3",
            session_type=SessionType.GROUP,
            group_id="10001",
        ),
        capability,
        capability_id="bot.chat",
    )

    assert first.state is ReceiptState.SENT
    assert blocked.state is ReceiptState.BLOCKED
    assert allowed_after_interval.state is ReceiptState.SENT
    assert calls == ["第一句", "第三句"]
    assert len(queue.sent_requests) == 2
    [record] = audit.list_records(blocked.request_id)
    assert record.event == "rate_limited"
    assert "target_min_interval" in record.private_debug
    assert "10001" not in record.private_debug


def test_rate_limit_settings_are_loaded_from_config_parameters():
    from plugins.bot_unified_runtime.config import Config
    from plugins.bot_unified_runtime.policy import build_rate_limit_settings

    settings = build_rate_limit_settings(
        Config(
            bot_rate_limit_enabled=False,
            bot_rate_limit_window_seconds=30,
            bot_rate_limit_chat_global_max_requests=20,
            bot_rate_limit_chat_session_max_requests=7,
            bot_rate_limit_chat_sender_max_requests=5,
            bot_rate_limit_target_min_interval_seconds=3,
            bot_rate_limit_bypass_roles=["admin", "trusted"],
        )
    )

    assert settings.enabled is False
    assert settings.window_seconds == 30
    assert settings.chat_global_max_requests == 20
    assert settings.chat_session_max_requests == 7
    assert settings.chat_sender_max_requests == 5
    assert settings.target_min_interval_seconds == 3
    assert settings.bypass_roles == ["admin", "trusted"]


def test_sqlite_rate_limiter_persists_window_across_instances(tmp_path):
    from plugins.bot_unified_runtime.policy import RateLimitSettings, SQLiteRateLimiter

    clock = MutableClock()
    db_path = tmp_path / "nested" / "rate_limit.sqlite3"
    settings = RateLimitSettings(
        window_seconds=60,
        chat_session_max_requests=1,
        chat_sender_max_requests=99,
    )
    first = SQLiteRateLimiter(db_path, settings=settings, clock=clock)
    second = SQLiteRateLimiter(db_path, settings=settings, clock=clock)
    message = make_message("第一句")

    allowed = first.check_and_record(message, "bot.chat", amount=1)
    blocked = second.check_and_record(message, "bot.chat", amount=1)
    clock.advance(61)
    allowed_after_window = second.check_and_record(message, "bot.chat", amount=1)

    assert db_path.exists()
    assert allowed.allowed is True
    assert blocked.allowed is False
    assert blocked.reason == "session_window_exceeded"
    assert allowed_after_window.allowed is True


def test_sqlite_rate_limiter_persists_target_min_interval_across_instances(tmp_path):
    from plugins.bot_unified_runtime.policy import RateLimitSettings, SQLiteRateLimiter

    clock = MutableClock()
    db_path = tmp_path / "nested" / "rate_limit.sqlite3"
    settings = RateLimitSettings(
        window_seconds=60,
        chat_global_max_requests=99,
        chat_session_max_requests=99,
        chat_sender_max_requests=99,
        target_min_interval_seconds=10,
    )
    first = SQLiteRateLimiter(db_path, settings=settings, clock=clock)
    second = SQLiteRateLimiter(db_path, settings=settings, clock=clock)
    message = make_message(
        "第一句",
        sender_id="1",
        session_type=SessionType.GROUP,
        group_id="10001",
    )
    next_message = make_message(
        "第二句",
        sender_id="2",
        session_type=SessionType.GROUP,
        group_id="10001",
    )

    allowed = first.check_and_record(message, "bot.chat", amount=1)
    blocked = second.check_and_record(next_message, "bot.chat", amount=1)
    clock.advance(11)
    allowed_after_interval = second.check_and_record(next_message, "bot.chat", amount=1)

    assert db_path.exists()
    assert allowed.allowed is True
    assert blocked.allowed is False
    assert blocked.reason == "target_min_interval"
    assert blocked.retry_after_seconds == 10
    assert allowed_after_interval.allowed is True


def test_build_rate_limiter_uses_sqlite_only_when_db_path_is_configured(tmp_path):
    from plugins.bot_unified_runtime.config import Config
    from plugins.bot_unified_runtime.policy import (
        InMemoryRateLimiter,
        SQLiteRateLimiter,
        build_rate_limiter,
    )

    sqlite_limiter = build_rate_limiter(
        Config(bot_rate_limit_db_path=str(tmp_path / "rate_limit.sqlite3"))
    )
    memory_limiter = build_rate_limiter(Config(bot_rate_limit_db_path=""))

    assert isinstance(sqlite_limiter, SQLiteRateLimiter)
    assert isinstance(memory_limiter, InMemoryRateLimiter)
