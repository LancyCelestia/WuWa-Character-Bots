from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    SendPolicy,
    SessionType,
)
from plugins.bot_unified_runtime.contracts.runtime import IncomingMessage
from plugins.bot_unified_runtime.runtime.event_idempotency import (
    EventIdempotencyTable,
    build_event_dedupe_key,
)
from plugins.bot_unified_runtime.runtime.pipeline import RuntimePipeline
from plugins.bot_unified_runtime.sender import InMemorySendQueue


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _message(message_id: str = "m-1") -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id="private:u1",
        session_type=SessionType.PRIVATE,
        sender_id="u1",
        plain_text="你好",
        message_id=message_id,
    )


def test_dedupe_key_requires_stable_message_id() -> None:
    assert build_event_dedupe_key(_message("m-9")) == "onebot|10000|m-9"
    assert build_event_dedupe_key(_message(message_id="")) == ""


def test_table_blocks_same_capability_but_not_others() -> None:
    table = EventIdempotencyTable(clock=_FakeClock())
    key = "onebot|10000|m-1"

    assert table.claim(key, capability_id="bot.chat") is True
    assert table.claim(key, capability_id="bot.chat") is False
    # 不同能力处理同一事件是合法多 matcher 流程，必须放行。
    assert table.claim(key, capability_id="bot.wiki") is True


def test_table_ttl_expiry_allows_reclaim() -> None:
    clock = _FakeClock()
    table = EventIdempotencyTable(ttl_seconds=60.0, clock=clock)
    key = "onebot|10000|m-1"

    assert table.claim(key, capability_id="bot.chat") is True
    clock.advance(61.0)
    assert table.claim(key, capability_id="bot.chat") is True
    assert len(table) == 1


def test_table_capacity_evicts_oldest() -> None:
    table = EventIdempotencyTable(max_entries=2, clock=_FakeClock())
    assert table.claim("k1", capability_id="c") is True
    assert table.claim("k2", capability_id="c") is True
    assert table.claim("k3", capability_id="c") is True
    assert len(table) == 2
    # k1 被挤出后可重新 claim。
    assert table.claim("k1", capability_id="c") is True


def _pipeline_with_table(table: EventIdempotencyTable | None) -> RuntimePipeline:
    audit = InMemoryAuditLogger()
    return RuntimePipeline(
        send_queue=InMemorySendQueue(audit_logger=audit),
        audit_logger=audit,
        idempotency_table=table,
    )


def _capability_result(message: IncomingMessage) -> CapabilityResult:
    return CapabilityResult(
        request_id=message.request_id,
        capability_id="bot.chat",
        kind="text",
        body="回复",
        send_policy=SendPolicy.SILENT_AUDIT,
    )


def _message_with_request(message_id: str) -> IncomingMessage:
    return _message(message_id).model_copy(update={"request_id": "r"})


def _capability(capability_result: CapabilityResult):
    async def _run(_message: IncomingMessage, _decision: object) -> CapabilityResult:
        return capability_result

    return _run


@pytest.mark.asyncio
async def test_pipeline_drops_duplicate_event_when_table_enabled() -> None:
    table = EventIdempotencyTable(clock=_FakeClock())
    pipeline = _pipeline_with_table(table)
    message = _message_with_request("m-42")

    first = await pipeline.handle_async(message, _capability(_capability_result(message)), "bot.chat")
    second = await pipeline.handle_async(message, _capability(_capability_result(message)), "bot.chat")

    assert first.state.value == "skipped"
    assert second.state.value == "blocked"
    assert "重复" in (second.public_message or "")


@pytest.mark.asyncio
async def test_pipeline_without_table_never_blocks_duplicate() -> None:
    pipeline = _pipeline_with_table(None)
    message = _message_with_request("m-42")

    first = await pipeline.handle_async(message, _capability(_capability_result(message)), "bot.chat")
    second = await pipeline.handle_async(message, _capability(_capability_result(message)), "bot.chat")

    assert first.state.value == "skipped"
    assert second.state.value == "skipped"
