"""B2 阶段 0（中央决策引擎骨架 + shadow 比对模式）回归测试。

规格：docs/design/central-decision-engine.md 迁移路径阶段 0。验收要点：
引擎与现行 matcher 并存；shadow 只记不发；互斥组/幂等/静默路径有单测；
对外行为逐字节不变。
"""

from __future__ import annotations

import asyncio

import pytest

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.decision import Dispatcher
from plugins.bot_unified_runtime.decision.engine import (
    BYPASS_ABILITIES,
    MUTUAL_GROUP_BYPASS,
    MUTUAL_GROUP_ROUTE,
    ActionKind,
    ActionResolver,
    CentralDecisionEngine,
    DecisionContext,
)
from plugins.bot_unified_runtime.decision.ingress import OneBotSource
from plugins.bot_unified_runtime.decision.shadow import (
    LEGACY_MODE,
    SHADOW_MODE,
    compare_with_legacy,
    is_shadow_active,
    normalize_decision_mode,
    reset_shared_state_for_tests,
    resolve_decision_mode,
)
from plugins.bot_unified_runtime.decision.trace import (
    InMemoryDecisionTraceSink,
    get_decision_trace_sink,
    set_decision_trace_sink,
)
from plugins.bot_unified_runtime.runtime.base_router import clear_route_decision_cache
from plugins.bot_unified_runtime.runtime.pipeline import RuntimePipeline
from plugins.bot_unified_runtime.sender import InMemorySendQueue


@pytest.fixture(autouse=True)
def _clean_decision_state(monkeypatch):
    monkeypatch.delenv("BOT_DECISION_ENGINE_MODE", raising=False)
    reset_shared_state_for_tests()
    clear_route_decision_cache()
    yield
    reset_shared_state_for_tests()
    set_decision_trace_sink(InMemoryDecisionTraceSink())


def _message(text: str = "", *, segments: list[dict] | None = None, session: str = "group:1") -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="nonebot",
        bot_id="bot",
        session_id=session,
        session_type=SessionType.GROUP,
        sender_id="42",
        group_id="1",
        plain_text=text,
        raw_segments=segments if segments is not None else ([{"type": "text", "data": {"text": text}}] if text else []),
    )


def _engine() -> CentralDecisionEngine:
    return CentralDecisionEngine()


# -------------------- 互斥组 --------------------


def test_mutual_group_first_hit_wins_within_group() -> None:
    resolver = ActionResolver()
    trace_id = "dt_test"
    low = resolver.plan_for_route(
        _route_stub("bot.chat", "chat", 50), trace_id=trace_id
    )
    high = resolver.plan_for_route(
        _route_stub("bot.music", "music", 41), trace_id=trace_id
    )
    winner = resolver.resolve([low, high])
    # 同组（route）内 priority 数值最小者（先命中者）胜。
    assert winner.capability_id == "bot.music"
    assert winner.mutual_group == MUTUAL_GROUP_ROUTE
    assert not winner.allow_parallel


def _route_stub(capability_id: str, kind: str, priority: int):
    from plugins.bot_unified_runtime.runtime.base_router import RouteDecision, RouteKind

    return RouteDecision(RouteKind(kind), capability_id, priority, f"{kind} rule")


def test_mutual_group_bypass_never_terminates() -> None:
    resolver = ActionResolver()
    trace_id = "dt_test"
    bypass = resolver.plan_for_bypass("bot.meme_absorb", trace_id=trace_id)
    assert bypass is not None and bypass.allow_parallel
    assert bypass.action is ActionKind.PASSIVE_ABSORB
    assert bypass.mutual_group == MUTUAL_GROUP_BYPASS
    route_plan = resolver.plan_for_route(
        _route_stub("bot.chat", "chat", 50), trace_id=trace_id
    )
    # 旁路型命中不终结决策：最终 plan 仍来自常规路由。
    winner = resolver.resolve([bypass, route_plan])
    assert winner is route_plan


def test_mutual_group_all_bypass_returns_single_plan() -> None:
    resolver = ActionResolver()
    first = resolver.plan_for_bypass("bot.dirty_guard", trace_id="dt_x")
    second = resolver.plan_for_bypass("bot.meme_absorb", trace_id="dt_x")
    winner = resolver.resolve([first, second])
    assert winner is first  # 单事件单 plan：取优先级最高（数值最小）者。


def test_bypass_registry_matches_spec_abilities() -> None:
    assert set(BYPASS_ABILITIES) == {"bot.meme_absorb", "bot.dirty_guard"}
    assert all(spec.allow_parallel for spec in BYPASS_ABILITIES.values())
    assert BYPASS_ABILITIES["bot.meme_absorb"].priority == 10
    assert BYPASS_ABILITIES["bot.dirty_guard"].priority == 3


# -------------------- 静默 / 路由路径 --------------------


def test_silent_plan_for_empty_message() -> None:
    plan, stages = _engine().decide_with_trace(DecisionContext(message=_message("")))
    assert plan.action is ActionKind.SILENT
    assert "空消息" in plan.reason
    kinds = [stage.stage for stage in stages]
    assert kinds == [
        "notice_gate",
        "mute_gate",
        "idempotency_gate",
        "router",
        "audience_gate",
        "action_resolver",
    ]


def test_route_command_produces_reply_plan() -> None:
    plan, _ = _engine().decide_with_trace(
        DecisionContext(message=_message("/bot status"))
    )
    assert plan.action is ActionKind.REPLY_TEXT
    assert plan.capability_id == "bot.status"
    assert plan.priority == 11


def test_router_models_media_chat_bypass() -> None:
    image_only = _message("", segments=[{"type": "image", "data": {"file": "x.jpg"}}])
    plan, _ = _engine().decide_with_trace(DecisionContext(message=image_only))
    assert plan.action is ActionKind.REPLY_TEXT
    assert plan.capability_id == "bot.chat"
    # 非 IGNORE 路由优先于媒体旁路：显式命令不被图片改写。
    mixed = _message("/bot status", segments=[
        {"type": "text", "data": {"text": "/bot status"}},
        {"type": "image", "data": {"file": "x.jpg"}},
    ])
    plan, _ = _engine().decide_with_trace(DecisionContext(message=mixed))
    assert plan.capability_id == "bot.status"


def test_router_models_effective_text_content_route() -> None:
    with_url = _message(
        "看这个 https://example.com/a", segments=[
            {"type": "text", "data": {"text": "看这个 https://example.com/a"}}
        ]
    )
    plan, _ = _engine().decide_with_trace(DecisionContext(message=with_url))
    assert plan.capability_id == "bot.content"


# -------------------- 幂等：引擎不 claim --------------------


def test_engine_never_claims_idempotency_table() -> None:
    claims: list[str] = []

    class ProbeTable:
        def claim(self, key: str, *, capability_id: str) -> bool:
            claims.append(key)
            return True

    engine = CentralDecisionEngine()
    context = DecisionContext(message=_message("你好"), config=ProbeTable())
    # 引擎契约（规格 §2.3.4）：幂等由 pipeline 独占，context 上任何对象都不被
    # 当作幂等表消费。
    engine.decide(context)
    engine.decide(context)
    assert claims == []


def test_shadow_idempotency_gate_deferred_to_pipeline() -> None:
    sink = InMemoryDecisionTraceSink()
    set_decision_trace_sink(sink)
    engine = CentralDecisionEngine()
    _plan, stages = engine.decide_with_trace(DecisionContext(message=_message("hi")))
    idempotency_rows = [row for row in stages if row.stage == "idempotency_gate"]
    assert len(idempotency_rows) == 1
    assert idempotency_rows[0].allowed is None
    assert "claim" in idempotency_rows[0].reason


# -------------------- shadow 只记不发 --------------------


class _FakeAudit:
    def append(self, record) -> None:
        return


def _capability(message, decision) -> CapabilityResult:
    return CapabilityResult(
        request_id=message.request_id,
        capability_id=decision.capability_id,
        kind="text",
        body="好的。",
    )


def _receipt_fingerprint(receipt) -> tuple:
    return (receipt.state.value, receipt.transport, receipt.public_message)


def _run_pipeline_once(mode: str, monkeypatch):
    monkeypatch.setenv("BOT_DECISION_ENGINE_MODE", mode)
    reset_shared_state_for_tests()
    audit = _FakeAudit()
    queue = InMemorySendQueue(audit_logger=audit)
    pipeline = RuntimePipeline(send_queue=queue, audit_logger=audit)
    receipts = []

    async def _run() -> None:
        receipt = await pipeline.handle_async(
            _message("今天天气怎么样"), _capability, capability_id="bot.chat"
        )
        receipts.append(receipt)

    asyncio.run(_run())
    return receipts[0], queue


def test_shadow_mode_records_trace_and_keeps_behavior(monkeypatch) -> None:
    legacy_receipt, legacy_queue = _run_pipeline_once(LEGACY_MODE, monkeypatch)
    assert len(get_decision_trace_sink().snapshot()) == 0  # legacy 不写 trace

    shadow_receipt, shadow_queue = _run_pipeline_once(SHADOW_MODE, monkeypatch)
    traces = get_decision_trace_sink().snapshot()
    assert len(traces) == 1
    trace = traces[0]
    assert trace.mode == SHADOW_MODE
    assert trace.origin == "pipeline_hook"
    assert trace.legacy_capability_id == "bot.chat"
    assert trace.agree is True
    assert trace.error == ""
    assert trace.plan_action == ActionKind.REPLY_TEXT.value
    assert trace.plan_capability_id == "bot.chat"
    assert trace.elapsed_ms >= 0.0
    # 零行为变化：回执逐字段一致；影子不产生任何额外队列条目。
    assert _receipt_fingerprint(shadow_receipt) == _receipt_fingerprint(legacy_receipt)
    assert len(shadow_queue.sent_requests) == len(legacy_queue.sent_requests)


def test_shadow_compares_route_divergence_honestly(monkeypatch) -> None:
    sink = InMemoryDecisionTraceSink()
    set_decision_trace_sink(sink)
    monkeypatch.setenv("BOT_DECISION_ENGINE_MODE", SHADOW_MODE)
    reset_shared_state_for_tests()
    audit = _FakeAudit()
    pipeline = RuntimePipeline(
        send_queue=InMemorySendQueue(audit_logger=audit), audit_logger=audit
    )
    # 链接文本被旧路径当作 chat 处理而引擎按 CONTENT（p=46 先于 chat）裁决：
    # 影子必须如实记 agree=False，不隐藏分歧。
    asyncio.run(
        pipeline.handle_async(
            _message("看这个 https://example.com/a"), _capability, capability_id="bot.chat"
        )
    )
    traces = sink.snapshot()
    assert traces[0].plan_action == ActionKind.REPLY_TEXT.value
    assert traces[0].plan_capability_id == "bot.content"
    assert traces[0].agree is False


def test_compare_unmodeled_legacy_capability_is_incomparable() -> None:
    engine = CentralDecisionEngine()
    plan = engine.decide(DecisionContext(message=_message("hello there")))
    agree, note = compare_with_legacy(plan, "bot.group_policy")
    assert plan.action is ActionKind.REPLY_TEXT  # "hello there" 落 chat（默认开关）
    assert agree is None
    assert note.startswith("unmodeled_legacy_capability")


def test_natural_command_compares_via_target_capability() -> None:
    from plugins.bot_unified_runtime.runtime.base_router import (
        RouteDecision,
        RouteKind,
    )

    route = RouteDecision(
        RouteKind.NATURAL_COMMAND,
        "bot.natural_command",
        45,
        "自然语言命令（意图：天气查询）",
        target_capability_id="bot.weather",
    )
    plan = ActionResolver().plan_for_route(route, trace_id="dt_t")
    agree, _note = compare_with_legacy(plan, "bot.weather")
    assert agree is True
    miss, _note = compare_with_legacy(plan, "bot.chat")
    assert miss is False


# -------------------- 模式解析 --------------------


def test_mode_resolution_defaults_to_legacy(monkeypatch) -> None:
    monkeypatch.delenv("BOT_DECISION_ENGINE_MODE", raising=False)
    assert resolve_decision_mode() == LEGACY_MODE
    assert is_shadow_active() is False


def test_mode_env_shadow_and_fail_closed(monkeypatch) -> None:
    monkeypatch.setenv("BOT_DECISION_ENGINE_MODE", "shadow")
    assert resolve_decision_mode() == SHADOW_MODE
    assert is_shadow_active() is True
    monkeypatch.setenv("BOT_DECISION_ENGINE_MODE", "engine_only")
    assert resolve_decision_mode() == LEGACY_MODE  # 阶段 0 一律回落
    monkeypatch.setenv("BOT_DECISION_ENGINE_MODE", "nonsense")
    assert normalize_decision_mode("nonsense") == LEGACY_MODE


def test_config_key_defaults_and_normalizes() -> None:
    from plugins.bot_unified_runtime.config import Config

    config = Config(bot_runtime_data_dir="data")
    assert config.bot_decision_engine_mode == "legacy_only"
    config = Config(bot_decision_engine_mode="SHADOW")
    assert config.bot_decision_engine_mode == "shadow"


# -------------------- 影子挂钩的健壮性 --------------------


def test_pipeline_survives_shadow_observer_crash(monkeypatch) -> None:
    import plugins.bot_unified_runtime.decision.shadow as shadow_module

    def _boom(message, capability_id):
        raise RuntimeError("shadow exploded")

    monkeypatch.setattr(shadow_module, "observe_pipeline_event", _boom)
    monkeypatch.setenv("BOT_DECISION_ENGINE_MODE", SHADOW_MODE)
    reset_shared_state_for_tests()
    audit = _FakeAudit()
    pipeline = RuntimePipeline(
        send_queue=InMemorySendQueue(audit_logger=audit), audit_logger=audit
    )
    # 观测器异常绝不能改变主链路结果（fail-open）。
    message = _message("hi").model_copy(update={"mentions_bot": True})
    receipt = pipeline.handle(message, _capability, capability_id="bot.chat")
    assert receipt.state.value == "sent"


def test_trace_sink_is_bounded() -> None:
    sink = InMemoryDecisionTraceSink(max_entries=3)
    from plugins.bot_unified_runtime.decision.trace import DecisionTrace

    for index in range(5):
        sink.record(
            DecisionTrace(trace_id=str(index), request_id=str(index), mode=SHADOW_MODE, origin="test")
        )
    assert [trace.trace_id for trace in sink.snapshot()] == ["2", "3", "4"]


# -------------------- 入口骨架与派发器守卫 --------------------


def test_onebot_source_kind_detection() -> None:
    class _OneBotMessage:
        __module__ = "nonebot.adapters.onebot.v11.event"

    class _OneBotNotice:
        __module__ = "nonebot.adapters.onebot.v11.event"

        def __init__(self) -> None:
            self.notice_type = "group_upload"

    class _TelegramMessage:
        __module__ = "nonebot.adapters.telegram.event"

    source = OneBotSource()
    assert source.can_handle(_OneBotMessage()) is True
    assert source.can_handle(_TelegramMessage()) is False
    assert source.kind(_OneBotNotice()) == "notice"
    assert source.kind(_OneBotMessage()) == "message"


def test_onebot_source_normalize_delegates_to_existing_normalizer() -> None:
    from plugins.bot_unified_runtime import _incoming_from_nonebot_event

    source = OneBotSource()

    class FakeEvent:
        __module__ = "nonebot.adapters.onebot.v11.event"

        def get_plaintext(self) -> str:
            return "你好"

        def get_session_id(self) -> str:
            return "12345"

        def get_user_id(self) -> str:
            return "12345"

        def is_tome(self) -> bool:
            return True

    message = source.normalize(FakeEvent(), bot_id="bot")
    expected = _incoming_from_nonebot_event(FakeEvent(), bot_id="bot")
    assert message is not None
    assert message.plain_text == expected.plain_text
    assert message.session_id == expected.session_id
    assert message.mentions_bot == expected.mentions_bot


def test_dispatcher_is_explicitly_disabled_in_phase1() -> None:
    import pytest as _pytest

    dispatcher = Dispatcher()
    plan = CentralDecisionEngine().decide(DecisionContext(message=_message("hi")))
    with _pytest.raises(NotImplementedError):
        asyncio.run(dispatcher.dispatch(plan, DecisionContext(message=_message("hi"))))
