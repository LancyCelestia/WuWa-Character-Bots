"""限流补回终局的「耗尽说明」接线（聊天体验波 2026-10-02）。

补回把被拦的那句重放到尽头仍没回上（``redrive_count`` 用尽 ``max_attempts``）
时，对「欠一句回复」的 directed request 落一句说明——文案池
``RATE_LIMIT_EXHAUSTED_NOTICE_POOL`` 的现役唯一消费者在此，每会话节流防刷。

零动作面（逐字节回旧静默）：补回未耗尽 / 非密度拒因 / 非 directed /
``redrive_settings`` 未装配 / 同步 handle。
"""

from __future__ import annotations

import asyncio

import pytest

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    ReceiptState,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.policy.rate_limit import (
    RATE_LIMIT_EXHAUSTED_NOTICE_POOL,
    RateLimitDecision,
    RedriveSettings,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.pipeline import (
    AsyncCapabilityCallable,
    RuntimePipeline,
)


class _AlwaysDenyLimiter:
    """恒拦（太密类）：专测补回耗尽面，不掺「重放成功」的分支。"""

    def __init__(self, reason: str = "sender_min_interval", retry_after: int = 1) -> None:
        self.reason = reason
        self.retry_after = retry_after
        self.calls = 0

    def check_and_record(self, message: object, capability_id: str, **kwargs: object):
        self.calls += 1
        return RateLimitDecision(
            allowed=False,
            reason=self.reason,
            retry_after_seconds=self.retry_after,
        )


class _NullAudit:
    def __init__(self) -> None:
        self.records: list = []

    def append(self, record: object) -> None:
        self.records.append(record)


class _SpyQueue:
    """只记 submit：被拦路径上这是 send_queue 的唯一读点。"""

    def __init__(self) -> None:
        self.requests: list = []

    def submit(self, request: object) -> None:
        self.requests.append(request)


def _capability() -> AsyncCapabilityCallable:
    async def capability(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        return CapabilityResult(request_id=message.request_id, kind="text", body="ok")

    return capability


def _message(
    *,
    session_id: str = "group_10_u1",
    session_type: SessionType = SessionType.GROUP,
    sender_id: str = "u1",
    group_id: str | None = "10",
    mentions_bot: bool = True,
    redrive_count: int = 0,
) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot_v11",
        bot_id="3958874605",
        session_id=session_id,
        session_type=session_type,
        sender_id=sender_id,
        group_id=group_id,
        plain_text="守岸人 在吗",
        mentions_bot=mentions_bot,
        redrive_count=redrive_count,
    )


def _pipeline(limiter: object, queue: object, **kwargs: object) -> RuntimePipeline:
    return RuntimePipeline(
        send_queue=queue,  # type: ignore[arg-type]
        audit_logger=_NullAudit(),  # type: ignore[arg-type]
        rate_limiter=limiter,  # type: ignore[arg-type]
        redrive_settings=RedriveSettings(max_attempts=2, max_wait_seconds=5.0),
        **kwargs,  # type: ignore[arg-type]
    )


def _cancel_redrive_tasks(pipeline: RuntimePipeline) -> None:
    for task in list(pipeline._redrive_tasks):
        task.cancel()


@pytest.mark.asyncio
async def test_exhausted_directed_request_gets_one_pool_notice() -> None:
    """补回次数已用尽 + 群内点名 ⇒ 恰好一句说明，正文出自在册文案池。"""
    limiter = _AlwaysDenyLimiter()
    queue = _SpyQueue()
    pipeline = _pipeline(limiter, queue)
    message = _message(redrive_count=2)  # == max_attempts：补回已到尽头
    receipt = await pipeline.handle_async(message, _capability(), capability_id="bot.chat")
    assert receipt.state is ReceiptState.BLOCKED
    assert len(queue.requests) == 1, "耗尽说明要么不发、只发一句，不许连发"
    notice = queue.requests[0]
    assert notice.content.text_fallback in RATE_LIMIT_EXHAUSTED_NOTICE_POOL
    assert notice.target_id == "10"
    events = [record.event for record in pipeline.audit_logger.records]
    assert "rate_limit_exhausted_notice" in events


@pytest.mark.asyncio
async def test_notice_is_throttled_per_session() -> None:
    """同一会话连撞耗尽只说一句；别的会话各欠各的、不受牵连。"""
    limiter = _AlwaysDenyLimiter()
    queue = _SpyQueue()
    pipeline = _pipeline(limiter, queue)
    first = _message(redrive_count=2)
    second = _message(redrive_count=2, sender_id="u1b", session_id="group_10_u1b")
    other_session = _message(
        redrive_count=2,
        session_type=SessionType.PRIVATE,
        sender_id="u2",
        group_id=None,
        session_id="private_u2",
        mentions_bot=False,
    )
    await pipeline.handle_async(first, _capability(), capability_id="bot.chat")
    await pipeline.handle_async(second, _capability(), capability_id="bot.chat")
    await pipeline.handle_async(other_session, _capability(), capability_id="bot.chat")
    assert len(queue.requests) == 2, "同会话节流失效或把别的会话也压住了"


@pytest.mark.asyncio
async def test_notice_waits_until_the_attempt_budget_is_spent() -> None:
    """预算没用完 ⇒ 不提前开口：重放两轮都仍被拦之后才说明。"""
    limiter = _AlwaysDenyLimiter(retry_after=1)
    queue = _SpyQueue()
    pipeline = _pipeline(limiter, queue)
    message = _message(redrive_count=0)
    receipt = await pipeline.handle_async(message, _capability(), capability_id="bot.chat")
    assert receipt.state is ReceiptState.BLOCKED
    assert queue.requests == [], "补回还有预算就抢着说明＝把「会补」说成「没答上」"
    await asyncio.sleep(3.0)  # 两次 1s 重放都仍被拦 ⇒ 到尽头了
    assert limiter.calls == 3, "补回重放没有按预算跑满"
    assert len(queue.requests) == 1
    _cancel_redrive_tasks(pipeline)


@pytest.mark.asyncio
async def test_unmentioned_group_chatter_exhausted_stays_silent() -> None:
    """没 @ 的群闲聊不欠回复（09-25 裁定）：耗尽也不说明，说明＝放大刷屏。"""
    limiter = _AlwaysDenyLimiter()
    queue = _SpyQueue()
    pipeline = _pipeline(limiter, queue)
    message = _message(mentions_bot=False, redrive_count=2)
    await pipeline.handle_async(message, _capability(), capability_id="bot.chat")
    assert queue.requests == []


@pytest.mark.asyncio
async def test_non_density_reason_exhausted_stays_silent() -> None:
    """安静时间不在补回名册里，也不在说明名册里——两本账同源。"""
    limiter = _AlwaysDenyLimiter(reason="quiet_hours")
    queue = _SpyQueue()
    pipeline = _pipeline(limiter, queue)
    message = _message(redrive_count=2)
    await pipeline.handle_async(message, _capability(), capability_id="bot.chat")
    assert queue.requests == []


@pytest.mark.asyncio
async def test_no_redrive_settings_means_no_notice() -> None:
    """补回整体未装配（键关部署）⇒ 零动作，与改前逐字节一致。"""
    limiter = _AlwaysDenyLimiter()
    queue = _SpyQueue()
    pipeline = RuntimePipeline(
        send_queue=queue,  # type: ignore[arg-type]
        audit_logger=_NullAudit(),  # type: ignore[arg-type]
        rate_limiter=limiter,  # type: ignore[arg-type]
    )
    message = _message(redrive_count=99)
    await pipeline.handle_async(message, _capability(), capability_id="bot.chat")
    assert queue.requests == []
