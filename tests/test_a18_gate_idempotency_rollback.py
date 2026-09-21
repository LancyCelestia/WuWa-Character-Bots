"""审查 A-18 回归：门禁前置于幂等 claim + 能力失败回滚限流额度。

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_a18_gate_idempotency_rollback.py -q

两件事（审查 A-18）：
1. 幂等 claim 从 handle 入口移到 _prepare 全部门禁（黑白名单/安静时间/限流）
   判定之后——被拦事件不消耗幂等键，用户重发同一条被拦消息仍可达能力；
   重复投递（claim 失败）同时回滚本次 check_and_record 记账，与旧
   claim-first 行为在「重复事件不消耗额度」上保持一致。
2. 能力异常（非用户内容问题）时回滚本次限流记账：限流器新增可选 rollback
   API（故意不进 Protocol——测试桩与第三方实现只保证 check_and_record，
   pipeline 用 getattr 探测、缺失即跳过，fail-open）。

A-04 衔接（686b69c，不可回退）：R3 同人点名最小间隔在限流器内部先于
interactive_bypass 早退、仅群聊点名生效。rollback 按 reason 镜像写路径：
interactive_bypass / role_bypass / emotion_exempt 三类放行型 reason 只回滚
R3 sender_interval 记账（这些路径在 scoped 桶记账之前早退/分流），allowed
才回滚全桶；限流拦截静默策略（2026-09-12 实弹裁定）不变。
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    SendPolicy,
)
from plugins.bot_unified_runtime.domains.chat_reply.policy.rate_limit import (
    InMemoryRateLimiter,
    RateLimitSettings,
    SQLiteRateLimiter,
)
from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
    BotDecision,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.runtime.event_idempotency import EventIdempotencyTable
from plugins.bot_unified_runtime.runtime.pipeline import RuntimePipeline
from plugins.bot_unified_runtime.sender import InMemorySendQueue


@pytest.fixture(autouse=True)
def _isolated_error_renderer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # 本模块测限流/幂等回滚；错误卡仍走真实编排/写入，只替换昂贵渲染边界。
    from plugins.bot_unified_runtime.domains.ops.monitor import error_report

    render = error_report.render_error_card_png
    backend = SimpleNamespace(render_card=lambda payload: b"isolated-test-png")
    monkeypatch.setattr(error_report, "render_error_card_png",
                        lambda report, **kwargs: render(report, backend=backend, card_dir=str(tmp_path)))
    yield
    # 禁止后台任务跨测试；必须在撤销路径/后端替身前排空。
    error_report.flush_pending_card_renders(timeout=10.0)


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 14, 9, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


def _msg(
    message_id: str = "m-1",
    *,
    session_type: SessionType = SessionType.PRIVATE,
    sender_id: str = "u1",
    mentions_bot: bool = True,
    text: str = "你好",
    sender_roles: list[str] | None = None,
) -> IncomingMessage:
    is_group = session_type is SessionType.GROUP
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id="group_123" if is_group else f"private:{sender_id}",
        session_type=session_type,
        sender_id=sender_id,
        group_id="123" if is_group else None,
        plain_text=text,
        mentions_bot=mentions_bot,
        message_id=message_id,
        sender_roles=sender_roles if sender_roles is not None else ["user"],
    )


class _QuietGate:
    """安静时间桩：blocked 可翻转，模拟「被拦后解除、用户重发」。"""

    def __init__(self) -> None:
        self.blocked = False

    def check(self, message: IncomingMessage, capability_id: str):
        if not self.blocked:
            return SimpleNamespace(
                allowed=True,
                reason="disabled",
                audit_tags=["quiet_hours:disabled"],
                debug_id="q-ok",
            )
        return SimpleNamespace(
            allowed=False,
            reason="quiet_hours",
            audit_tags=["quiet_hours:blocked"],
            debug_id="q-blocked",
        )


def _window_caps(**overrides: object) -> dict:
    # 抬高不被测的窗口帽，聚焦被测行为（与 test_policy_sender_interval 同法）。
    caps: dict = {
        "chat_global_max_requests": 10_000,
        "chat_session_max_requests": 10_000,
        "chat_sender_max_requests": 10_000,
    }
    caps.update(overrides)
    return caps


def _pipeline(
    limiter: InMemoryRateLimiter | SQLiteRateLimiter,
    *,
    table: EventIdempotencyTable | None = None,
    quiet: _QuietGate | None = None,
) -> RuntimePipeline:
    audit = InMemoryAuditLogger()
    return RuntimePipeline(
        send_queue=InMemorySendQueue(audit_logger=audit),
        audit_logger=audit,
        rate_limiter=limiter,
        quiet_hours_checker=quiet if quiet is not None else _QuietGate(),
        idempotency_table=table,
    )


def _ok_capability(calls: list[str]):
    def _run(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        calls.append(message.message_id or "")
        return CapabilityResult(
            request_id=message.request_id,
            capability_id=decision.capability_id,
            kind="text",
            title="",
            summary="",
            body="回复",
            send_policy=SendPolicy.SILENT_AUDIT,
        )

    return _run


def _boom_capability(calls: list[str]):
    def _run(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        calls.append(message.message_id or "")
        raise RuntimeError("capability exploded")

    return _run


# ==================== ① 被拦事件不消耗幂等键 ====================


def test_quiet_hours_blocked_event_does_not_consume_idempotency_key() -> None:
    """安静时间拦截后解除，同一事件重发必须可达能力（键未被拦截消耗）。"""
    quiet = _QuietGate()
    quiet.blocked = True
    pipeline = _pipeline(InMemoryRateLimiter(), table=EventIdempotencyTable(), quiet=quiet)
    calls: list[str] = []
    message = _msg("m-1")

    first = pipeline.handle(message, _ok_capability(calls), "bot.chat")
    assert calls == []
    assert first.state.value == "blocked"
    # 安静时间拦截一律静默（2026-09-16 起与限流同款），提示语不再进群。
    assert first.public_message == ""

    quiet.blocked = False
    resent = pipeline.handle(message, _ok_capability(calls), "bot.chat")
    # 旧序（handle 先 claim）：此处会拿到「该事件已处理过」的 duplicate 回执。
    assert calls == ["m-1"]
    assert resent.state.value == "skipped"
    assert "重复" not in (resent.public_message or "")


def test_rate_limited_event_does_not_consume_idempotency_key() -> None:
    """限流拦截静默（public_message=""）不占键；窗口滚过后重发可达能力。"""
    clock = _Clock()
    limiter = InMemoryRateLimiter(
        RateLimitSettings(**_window_caps(chat_sender_max_requests=1)),
        clock=clock,
    )
    pipeline = _pipeline(limiter, table=EventIdempotencyTable())
    calls: list[str] = []

    first = pipeline.handle(_msg("m-1"), _ok_capability(calls), "bot.chat")
    assert calls == ["m-1"]
    assert first.state.value == "skipped"

    blocked = pipeline.handle(_msg("m-2"), _ok_capability(calls), "bot.chat")
    assert calls == ["m-1"]
    assert blocked.state.value == "blocked"
    # 限流拦截一律静默（2026-09-12 实弹裁定），且不是 duplicate 文案。
    assert blocked.public_message == ""

    clock.advance(seconds=61)
    resent = pipeline.handle(_msg("m-2"), _ok_capability(calls), "bot.chat")
    assert calls == ["m-1", "m-2"]
    assert resent.state.value == "skipped"


# ==================== ② 能力失败回滚额度（管线层） ====================


def test_capability_failure_rolls_back_inmemory_quota() -> None:
    """能力异常后同 sender 的下一条消息不被 sender 窗误拦（额度已回滚）。"""
    clock = _Clock()
    limiter = InMemoryRateLimiter(
        RateLimitSettings(**_window_caps(chat_sender_max_requests=1)),
        clock=clock,
    )
    pipeline = _pipeline(limiter)
    calls: list[str] = []

    failed = pipeline.handle(_msg("m-1"), _boom_capability(calls), "bot.chat")
    assert failed.state.value == "failed_final"

    followup = pipeline.handle(_msg("m-2"), _ok_capability(calls), "bot.chat")
    # 无回滚时 m-2 会命中 sender_window_exceeded（静默 blocked）。
    assert calls == ["m-1", "m-2"]
    assert followup.state.value == "skipped"


def test_capability_failure_rolls_back_sqlite_quota(tmp_path: Path) -> None:
    """SQLite 限流器同语义：能力异常回滚记账。"""
    clock = _Clock()
    limiter = SQLiteRateLimiter(
        tmp_path / "rate_limit.db",
        RateLimitSettings(**_window_caps(chat_sender_max_requests=1)),
        clock=clock,
    )
    pipeline = _pipeline(limiter)
    calls: list[str] = []

    failed = pipeline.handle(_msg("m-1"), _boom_capability(calls), "bot.chat")
    assert failed.state.value == "failed_final"

    followup = pipeline.handle(_msg("m-2"), _ok_capability(calls), "bot.chat")
    assert calls == ["m-1", "m-2"]
    assert followup.state.value == "skipped"


def test_capability_failure_rolls_back_r3_mention_cooldown() -> None:
    """A-04 衔接：群点名（interactive 路径）失败后 45s 冷却随记账回滚。

    pipeline 对「群聊 @bot」传 interactive=True，限流器 reason=interactive_bypass
    但 R3 sender_interval 已记账——回滚必须覆盖，否则能力失败后用户 45s 内
    的正常点名被 sender_min_interval 误拦（A-04 防护方向不能反打自己人）。
    """
    clock = _Clock()
    limiter = InMemoryRateLimiter(RateLimitSettings(**_window_caps()), clock=clock)
    pipeline = _pipeline(limiter)
    calls: list[str] = []

    failed = pipeline.handle(
        _msg("m-1", session_type=SessionType.GROUP), _boom_capability(calls), "bot.chat"
    )
    assert failed.state.value == "failed_final"

    resent = pipeline.handle(
        _msg("m-2", session_type=SessionType.GROUP), _ok_capability(calls), "bot.chat"
    )
    assert calls == ["m-1", "m-2"]
    assert resent.state.value == "skipped"


def test_duplicate_delivery_rolls_back_its_own_record() -> None:
    """重复投递（claim 失败）回滚本次记账：重复事件不白耗额度。

    旧 claim-first 序下重复事件发生在记账之前；新序记账在前，必须补回滚
    才能保持「重复投递零额度消耗」的旧语义。
    """
    clock = _Clock()
    limiter = InMemoryRateLimiter(
        RateLimitSettings(**_window_caps(chat_sender_max_requests=2)),
        clock=clock,
    )
    pipeline = _pipeline(limiter, table=EventIdempotencyTable())
    calls: list[str] = []

    first = pipeline.handle(_msg("m-1"), _ok_capability(calls), "bot.chat")
    assert first.state.value == "skipped"
    duplicate = pipeline.handle(_msg("m-1"), _ok_capability(calls), "bot.chat")
    assert calls == ["m-1"]
    assert "重复" in (duplicate.public_message or "")

    # sender 帽=2：首条占 1，重复投递若不回滚再占 1，第三条将 2+1>2 被拦。
    third = pipeline.handle(_msg("m-2"), _ok_capability(calls), "bot.chat")
    assert calls == ["m-1", "m-2"]
    assert third.state.value == "skipped"


# ==================== 限流器 rollback 单元（InMemory） ====================


def test_memory_rollback_allowed_restores_all_written_buckets() -> None:
    """allowed 全桶回滚：scoped/R3/群窗口/target 逐桶镜像 check 写路径。"""
    clock = _Clock()
    limiter = InMemoryRateLimiter(
        RateLimitSettings(
            **_window_caps(
                chat_sender_max_requests=1,
                target_min_interval_seconds=30,
                group_hourly_max_requests=2,
                group_minute_max_requests=1,
            )
        ),
        clock=clock,
    )
    message = _msg("m-1", session_type=SessionType.GROUP)
    # interactive=False 才能走到 allowed 全桶记账（interactive=True 会在 R3
    # 记账后于 interactive_bypass 早退）；R3 记账只看群聊+点名，与 interactive 无关。
    decision = limiter.check_and_record(message, "bot.chat", amount=1, interactive=False)
    assert decision.allowed is True
    assert decision.reason == "allowed"

    limiter.rollback(message, "bot.chat", amount=1, reason="allowed")

    # R3 点名冷却已回滚：45s 内同 sender 再点名放行。
    again = limiter.check_and_record(message, "bot.chat", amount=1, interactive=False)
    assert again.allowed is True
    # 群分钟窗帽=1：若群窗口未回滚，此处会 group_minute_exceeded。
    assert again.reason == "allowed"


def test_memory_rollback_interactive_bypass_pops_r3_record() -> None:
    clock = _Clock()
    limiter = InMemoryRateLimiter(RateLimitSettings(**_window_caps()), clock=clock)
    message = _msg("m-1", session_type=SessionType.GROUP)
    decision = limiter.check_and_record(message, "bot.chat", interactive=True)
    assert (decision.allowed, decision.reason) == (True, "interactive_bypass")

    limiter.rollback(message, "bot.chat", reason="interactive_bypass")

    followup = limiter.check_and_record(message, "bot.chat", interactive=True)
    assert followup.allowed is True
    assert followup.reason == "interactive_bypass"  # 未被残留记账判 45s 冷却


def test_memory_rollback_role_bypass_pops_r3_record() -> None:
    """A-04 序缺口锁定：role_bypass 早退前 R3 已记账，回滚必须覆盖。"""
    clock = _Clock()
    limiter = InMemoryRateLimiter(
        RateLimitSettings(**_window_caps(bypass_roles=["admin"])), clock=clock
    )
    message = _msg("m-1", session_type=SessionType.GROUP, sender_roles=["admin"])
    decision = limiter.check_and_record(message, "bot.chat", interactive=False)
    assert (decision.allowed, decision.reason) == (True, "role_bypass")

    limiter.rollback(message, "bot.chat", reason="role_bypass")

    followup = limiter.check_and_record(
        message, "bot.chat", interactive=True
    )
    assert followup.allowed is True
    assert followup.reason == "interactive_bypass"  # R3 记账未残留


def test_memory_rollback_blocked_reason_is_noop() -> None:
    """拦截型 reason 零记账，rollback 必须空转（不多退他人额度）。"""
    clock = _Clock()
    limiter = InMemoryRateLimiter(
        RateLimitSettings(**_window_caps(chat_sender_max_requests=1)), clock=clock
    )
    assert limiter.check_and_record(_msg("m-1"), "bot.chat").allowed is True
    blocked = limiter.check_and_record(_msg("m-2"), "bot.chat")
    assert (blocked.allowed, blocked.reason) == (False, "sender_window_exceeded")

    limiter.rollback(_msg("m-2"), "bot.chat", reason="sender_window_exceeded")

    # m-1 的记账原样保留：m-3 仍被拦（rollback 没有误删/误放）。
    still_blocked = limiter.check_and_record(_msg("m-3"), "bot.chat")
    assert (still_blocked.allowed, still_blocked.reason) == (
        False,
        "sender_window_exceeded",
    )


def test_memory_rollback_proactive_allowed_pops_proactive_bucket() -> None:
    clock = _Clock()
    limiter = InMemoryRateLimiter(RateLimitSettings(**_window_caps()), clock=clock)
    message = _msg("m-1", session_type=SessionType.GROUP)
    first = limiter.check_and_record(message, "bot.chat", proactive=True)
    assert (first.allowed, first.reason) == (True, "proactive_allowed")
    # 主动冷却 90s：未回滚时紧接的第二次主动回复会被 proactive_cooldown 拦。
    second = limiter.check_and_record(message, "bot.chat", proactive=True)
    assert (second.allowed, second.reason) == (False, "proactive_cooldown")

    limiter.rollback(message, "bot.chat", reason="proactive_allowed")

    third = limiter.check_and_record(message, "bot.chat", proactive=True)
    assert (third.allowed, third.reason) == (True, "proactive_allowed")


# ==================== 限流器 rollback 单元（SQLite） ====================


def test_sqlite_rollback_allowed_restores_quota(tmp_path: Path) -> None:
    clock = _Clock()
    limiter = SQLiteRateLimiter(
        tmp_path / "rate_limit.db",
        RateLimitSettings(**_window_caps(chat_sender_max_requests=1)),
        clock=clock,
    )
    assert limiter.check_and_record(_msg("m-1"), "bot.chat").allowed is True

    limiter.rollback(_msg("m-1"), "bot.chat", amount=1, reason="allowed")

    followup = limiter.check_and_record(_msg("m-2"), "bot.chat")
    assert (followup.allowed, followup.reason) == (True, "allowed")


def test_sqlite_rollback_interactive_bypass_pops_r3_record(tmp_path: Path) -> None:
    clock = _Clock()
    limiter = SQLiteRateLimiter(
        tmp_path / "rate_limit.db",
        RateLimitSettings(**_window_caps()),
        clock=clock,
    )
    message = _msg("m-1", session_type=SessionType.GROUP)
    decision = limiter.check_and_record(message, "bot.chat", interactive=True)
    assert (decision.allowed, decision.reason) == (True, "interactive_bypass")

    limiter.rollback(message, "bot.chat", reason="interactive_bypass")

    followup = limiter.check_and_record(message, "bot.chat", interactive=True)
    assert followup.allowed is True
    assert followup.reason == "interactive_bypass"


def test_sqlite_rollback_role_bypass_pops_r3_record(tmp_path: Path) -> None:
    clock = _Clock()
    limiter = SQLiteRateLimiter(
        tmp_path / "rate_limit.db",
        RateLimitSettings(**_window_caps(bypass_roles=["admin"])),
        clock=clock,
    )
    message = _msg("m-1", session_type=SessionType.GROUP, sender_roles=["admin"])
    decision = limiter.check_and_record(message, "bot.chat", interactive=False)
    assert (decision.allowed, decision.reason) == (True, "role_bypass")

    limiter.rollback(message, "bot.chat", reason="role_bypass")

    followup = limiter.check_and_record(message, "bot.chat", interactive=True)
    assert followup.allowed is True
    assert followup.reason == "interactive_bypass"


def test_sqlite_rollback_blocked_reason_is_noop(tmp_path: Path) -> None:
    clock = _Clock()
    limiter = SQLiteRateLimiter(
        tmp_path / "rate_limit.db",
        RateLimitSettings(**_window_caps(chat_sender_max_requests=1)),
        clock=clock,
    )
    assert limiter.check_and_record(_msg("m-1"), "bot.chat").allowed is True
    blocked = limiter.check_and_record(_msg("m-2"), "bot.chat")
    assert (blocked.allowed, blocked.reason) == (False, "sender_window_exceeded")

    limiter.rollback(_msg("m-2"), "bot.chat", reason="sender_window_exceeded")

    still_blocked = limiter.check_and_record(_msg("m-3"), "bot.chat")
    assert (still_blocked.allowed, still_blocked.reason) == (
        False,
        "sender_window_exceeded",
    )


def test_sqlite_rollback_proactive_allowed_pops_proactive_bucket(tmp_path: Path) -> None:
    clock = _Clock()
    limiter = SQLiteRateLimiter(
        tmp_path / "rate_limit.db",
        RateLimitSettings(**_window_caps()),
        clock=clock,
    )
    message = _msg("m-1", session_type=SessionType.GROUP)
    assert limiter.check_and_record(message, "bot.chat", proactive=True).allowed is True
    second = limiter.check_and_record(message, "bot.chat", proactive=True)
    assert (second.allowed, second.reason) == (False, "proactive_cooldown")

    limiter.rollback(message, "bot.chat", reason="proactive_allowed")

    third = limiter.check_and_record(message, "bot.chat", proactive=True)
    assert (third.allowed, third.reason) == (True, "proactive_allowed")
