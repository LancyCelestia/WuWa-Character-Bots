"""V21-DISPATCH-001 统一出站面接线回归（v21r2 DSP 席）。

覆盖：
- ``OutboundSideEffectExecutor``：OutboundIntent → cancel 前置闸 → 准入复验 →
  许可租约线性化 → Transport 固定映射（绝不拼 API 名）→ ``bot.call_api``
  通道本体 → 用毕释放；
- 幂等/租约语义：同键在途二次申请拒绝（DuplicateClaim）、用毕释放后可重入、
  取消在途不假成功（cancel_requested / 门面 review_blocked 均零平台调用）、
  未注册 transport / 未登记平台诚实拒绝；
- 门面接线：PokeInteractionService / ReactionService 真实 route→review→send
  周期（trace_id 贯通、回执落 status）；
- decision Dispatcher 阶段 1：shadow 绝不发送 / engine_only 执行 / 未绑定
  显式 outbound_not_bound / 多意图聚合（dispatched/blocked/partial）。

全离线 mock，不触网、不写源码树。
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugins.bot_unified_runtime.control_plane.dispatcher import (
    OutboundSideEffectExecutor,
    PokeInteractionService,
    SideEffectReceipt,
    build_interaction_dispatcher,
)
from plugins.bot_unified_runtime.domains.core.decision.dispatcher import (
    Dispatcher as DecisionDispatcher,
)
from plugins.bot_unified_runtime.domains.core.decision.outbound import (
    OutboundIntent,
    OutboundOperation,
    OutboundPart,
    OutboundTarget,
    build_default_transport_registry,
    derive_dedupe_key,
)
from plugins.bot_unified_runtime.domains.meme.reactions.engine import (
    react_telegram_message,
    react_to_message,
)


class FakeBot:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.fail = fail

    async def call_api(self, api: str, **kwargs):
        self.calls.append((api, kwargs))
        if self.fail:
            raise RuntimeError("platform rejected")


def _executor(**kwargs: Any) -> OutboundSideEffectExecutor:
    kwargs.setdefault("transport_registry", build_default_transport_registry())
    return OutboundSideEffectExecutor(**kwargs)


def _poke_intent(
    *,
    platform: str = "qq",
    session_type: str = "group",
    key: str = "evt1",
    cancel_requested: bool = False,
    expires_at: datetime | None = None,
) -> OutboundIntent:
    api_params = (
        {"group_id": 111, "user_id": 222}
        if session_type == "group"
        else {"user_id": 222}
    )
    return OutboundIntent(
        operation=OutboundOperation.POKE,
        target=OutboundTarget(
            platform=platform,
            session_type=session_type,
            target_id="111" if session_type == "group" else "222",
            bot_id="bot-1",
            adapter="onebot" if platform == "qq" else platform,
        ),
        parts=[
            OutboundPart(
                part_id=f"poke-back:{key}",
                kind="poke",
                content_ref={"api_params": api_params},
            )
        ],
        feature_id="bot.plugin.poke.poke_back",
        policy_revision="legacy-poke-v2",
        dedupe_key=derive_dedupe_key(platform, key, "direct"),
        trace_id=f"t-{key}",
        cancel_requested=cancel_requested,
        expires_at=expires_at,
    )


# ------------------------------------------------- 执行器：固定映射与回执


def test_executor_delivers_group_poke_via_registered_method() -> None:
    bot = FakeBot()
    receipt = asyncio.run(_executor().execute(_poke_intent(), bot=bot))
    assert receipt.delivered is True
    assert receipt.status == "delivered"
    assert receipt.method == "group_poke"
    assert bot.calls == [("group_poke", {"group_id": 111, "user_id": 222})]


def test_executor_delivers_private_poke_via_friend_poke() -> None:
    bot = FakeBot()
    receipt = asyncio.run(
        _executor().execute(_poke_intent(session_type="private"), bot=bot)
    )
    assert receipt.delivered is True
    assert bot.calls == [("friend_poke", {"user_id": 222})]


def test_executor_platform_failure_is_honest_receipt_not_raise() -> None:
    bot = FakeBot(fail=True)
    receipt = asyncio.run(_executor().execute(_poke_intent(key="evt-fail"), bot=bot))
    assert receipt.delivered is False
    assert receipt.status == "failed"
    assert receipt.reason == "RuntimeError"
    assert len(bot.calls) == 1  # 调用确实发生过（回执不撒谎）


def test_executor_without_bot_reports_no_channel() -> None:
    receipt = asyncio.run(_executor().execute(_poke_intent(key="evt-nobot")))
    assert receipt.delivered is False
    assert receipt.status == "no_channel"


# ------------------------------------------------- 幂等/租约语义


def test_duplicate_inflight_claim_rejected_then_reentrant_after_release() -> None:
    """同键二次申请拒绝（在途线性化点）；租约用毕释放后同键可重入
    （顺序性重复事件——用户连续戳两下——天然放行，不误伤）。"""
    ex = _executor()
    bot = FakeBot()
    intent = _poke_intent(key="evt-dup")
    # 在途占位（模拟同键并发第二个事件）：二次申请被拒，零平台调用。
    token = ex.lease.acquire(intent.dedupe_key, holder="other-worker")
    receipt = asyncio.run(ex.execute(intent, bot=bot))
    assert receipt.delivered is False
    assert receipt.status == "duplicate_claim"
    assert "other-worker" in receipt.reason
    assert bot.calls == []
    # 释放后重入：走完全链成功（租约无泄漏）。
    ex.lease.release(token)
    assert ex.lease.inflight_keys() == []
    receipt = asyncio.run(ex.execute(intent, bot=bot))
    assert receipt.delivered is True
    assert ex.lease.inflight_keys() == []  # 用毕即还


def test_cancel_requested_intent_never_sends_and_never_reports_success() -> None:
    """取消在途不假成功：带取消标记的意图零平台调用、零 delivered。"""
    bot = FakeBot()
    receipt = asyncio.run(
        _executor().execute(_poke_intent(key="evt-cancel", cancel_requested=True), bot=bot)
    )
    assert receipt.delivered is False
    assert receipt.status == "cancelled"
    assert bot.calls == []


def test_expired_intent_denied_by_admission_gate() -> None:
    bot = FakeBot()
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    receipt = asyncio.run(
        _executor().execute(_poke_intent(key="evt-expired", expires_at=past), bot=bot)
    )
    assert receipt.delivered is False
    assert receipt.status == "admission_denied"
    assert receipt.reason.startswith("expiry")
    assert bot.calls == []


def test_unregistered_transport_is_honest_telegram_poke() -> None:
    """TG POKE 有意不注册（平台无此通道）→ 显式 unregistered_transport。"""
    bot = FakeBot()
    receipt = asyncio.run(
        _executor().execute(_poke_intent(platform="telegram", key="evt-tg"), bot=bot)
    )
    assert receipt.delivered is False
    assert receipt.status == "unregistered_transport"
    assert bot.calls == []


def test_unknown_platform_never_synthetically_dispatched() -> None:
    bot = FakeBot()
    receipt = asyncio.run(
        _executor().execute(_poke_intent(platform="wizard", key="evt-wiz"), bot=bot)
    )
    assert receipt.delivered is False
    assert receipt.status == "unregistered_platform"
    assert bot.calls == []


# ------------------------------------------------- 门面接线（poke/reaction）


def test_poke_interaction_service_full_dispatch_cycle() -> None:
    """PokeInteractionService 真实 route→review→send：trace 贯通 + 回执落 status。"""
    bot = FakeBot()

    def _route(payload: dict[str, Any]):
        return _poke_intent(key=f"svc-{payload.get('seq', 0)}")

    service = PokeInteractionService(
        dispatch=build_interaction_dispatcher(_executor(), route_intent=_route)
    )
    result = asyncio.run(service.handle({"bot": bot, "seq": 1}))
    assert result.status == "delivered"
    assert result.trace_id
    assert bot.calls == [("group_poke", {"group_id": 111, "user_id": 222})]


def test_poke_interaction_service_review_blocks_cancel_marked() -> None:
    """门面 review 拦截带取消标记的意图（review_blocked，绝不触达平台）。"""
    bot = FakeBot()
    service = PokeInteractionService(
        dispatch=build_interaction_dispatcher(
            _executor(), route_intent=lambda _payload: _poke_intent(cancel_requested=True),
        )
    )
    result = asyncio.run(service.handle({"bot": bot}))
    assert result.status == "review_blocked"
    assert bot.calls == []


def test_react_to_message_routes_through_unified_outbound() -> None:
    bot = FakeBot()
    assert asyncio.run(react_to_message(bot, message_id=98765, emoji_id=13)) is True
    # 参数 coercion 与旧直连逐字节一致：message_id int / emoji_id str。
    assert bot.calls == [("set_msg_emoji_like", {"message_id": 98765, "emoji_id": "13"})]


def test_react_to_message_platform_rejection_stays_silent_false() -> None:
    bot = FakeBot(fail=True)
    assert asyncio.run(react_to_message(bot, message_id=5, emoji_id=13)) is False


def test_react_to_message_blank_id_short_circuits() -> None:
    bot = FakeBot()
    assert asyncio.run(react_to_message(bot, message_id="", emoji_id=13)) is False
    assert bot.calls == []


def test_react_telegram_message_routes_through_unified_outbound() -> None:
    bot = FakeBot()
    ok = asyncio.run(
        react_telegram_message(bot, chat_id=-100123, message_id="42", emoji="👍")
    )
    assert ok is True
    api, kwargs = bot.calls[0]
    assert api == "set_message_reaction"
    assert kwargs == {
        "chat_id": -100123,
        "message_id": 42,
        "reaction": [{"type": "emoji", "emoji": "👍"}],
        "is_big": False,
    }


# ------------------------------------------------- decision Dispatcher 阶段 1


class _ScriptedExecutor:
    def __init__(self, receipts: list[SideEffectReceipt]) -> None:
        self.receipts = list(receipts)
        self.seen: list[str] = []

    async def execute(self, intent: OutboundIntent, *, bot: Any = None) -> SideEffectReceipt:
        self.seen.append(intent.dedupe_key)
        return self.receipts.pop(0)


def _ok() -> SideEffectReceipt:
    return SideEffectReceipt(True, "delivered")


def _bad() -> SideEffectReceipt:
    return SideEffectReceipt(False, "failed", reason="RuntimeError")


def test_decision_dispatcher_shadow_mode_never_sends() -> None:
    """shadow/未知语境只记录绝不发送（阶段 0 语义在阶段 1 保持）。"""
    intent = _poke_intent(key="evt-shadow")
    scripted = _ScriptedExecutor([_ok()])
    dispatcher = DecisionDispatcher(
        engine=object(), pipeline=object(), outbound_executor=scripted,
    )
    for ctx in (SimpleNamespace(mode="shadow"), object(), None):
        outcome = asyncio.run(
            dispatcher.dispatch(SimpleNamespace(outbound_intents=[intent]), ctx)
        )
        assert outcome.status == "shadow_recorded"
        assert "not sent" in outcome.detail
    assert scripted.seen == []


def test_decision_dispatcher_engine_only_executes_outbound_intents() -> None:
    intent = _poke_intent(key="evt-engine")
    scripted = _ScriptedExecutor([_ok()])
    dispatcher = DecisionDispatcher(
        engine=object(), pipeline=object(), outbound_executor=scripted,
    )
    outcome = asyncio.run(
        dispatcher.dispatch(
            SimpleNamespace(outbound_intents=[intent]), SimpleNamespace(mode="engine_only"),
        )
    )
    assert outcome.status == "dispatched"
    assert scripted.seen == [intent.dedupe_key]


def test_decision_dispatcher_engine_only_without_executor_refuses_half_send() -> None:
    dispatcher = DecisionDispatcher(engine=object(), pipeline=object())
    outcome = asyncio.run(
        dispatcher.dispatch(
            SimpleNamespace(outbound_intents=[_poke_intent(key="evt-noexec")]),
            SimpleNamespace(mode="engine_only"),
        )
    )
    assert outcome.status == "outbound_not_bound"


def test_decision_dispatcher_aggregates_mixed_receipts() -> None:
    i1, i2, i3 = (_poke_intent(key=f"evt-m{i}") for i in range(3))
    scripted = _ScriptedExecutor([_ok(), _bad(), _ok()])
    dispatcher = DecisionDispatcher(
        engine=object(), pipeline=object(), outbound_executor=scripted,
    )
    outcome = asyncio.run(
        dispatcher.dispatch(
            SimpleNamespace(outbound_intents=[i1, i2, i3]),
            SimpleNamespace(mode="engine_only"),
        )
    )
    assert outcome.status == "partial"

    scripted = _ScriptedExecutor([_bad(), _bad()])
    dispatcher = DecisionDispatcher(
        engine=object(), pipeline=object(), outbound_executor=scripted,
    )
    outcome = asyncio.run(
        dispatcher.dispatch(
            SimpleNamespace(outbound_intents=[i1, i2]), SimpleNamespace(mode="engine_only"),
        )
    )
    assert outcome.status == "blocked"


def test_decision_dispatcher_non_intent_objects_filtered() -> None:
    """outbound_intents 中混入非 OutboundIntent 对象一律过滤（严格 DTO 面）。"""
    scripted = _ScriptedExecutor([])
    dispatcher = DecisionDispatcher(
        engine=object(), pipeline=object(), outbound_executor=scripted,
    )
    outcome = asyncio.run(
        dispatcher.dispatch(
            SimpleNamespace(outbound_intents=["not-an-intent", 42]),
            SimpleNamespace(mode="engine_only"),
        )
    )
    assert outcome.status == "no_outbound"
    assert scripted.seen == []
