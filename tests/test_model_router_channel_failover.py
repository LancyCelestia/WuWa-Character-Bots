"""同模型多渠道候选集 + 跨渠道 failover + 计费归因（2026-09-13 账单批）。

用户裁定：指定「单个渠道入口」或「模型 ID 入口」时，同一模型名的全部
渠道构成候选集——首选渠道失败自动切同模型下一渠道（用户无感），计费
归因到实际服务的渠道。本文件锁定：

① 渠道 id 入口连通同模型兄弟渠道（兄弟渠道先于其他模型）；
② 模型名聚合渠道不再重复出现在尾部自动队列（旧实现兄弟渠道被试两次）；
③ 影子并发（hedged）赢家的渠道/价格归因（旧实现 _last_channel_id 跳过
   全部 hedged 记号，渠道与价格双双归因落空）；
④ failover 拨转后账本行 provider_id/价格 = 实际服务渠道。

全部离线（假 provider / 假 sink）。
"""

from __future__ import annotations

import time
from typing import Any

from plugins.bot_unified_runtime.llm.ledger import LLMCallDraft
from plugins.bot_unified_runtime.llm.model_router import ModelRouter, ModelSpec
from plugins.bot_unified_runtime.llm.providers import (
    LLMProviderError,
    LLMReply,
)


class FakeProvider:
    def __init__(
        self,
        model_id: str,
        failures: dict[str, str],
        calls: list[str],
    ) -> None:
        self.model_id = model_id
        self.failures = failures
        self.calls = calls

    def generate(
        self, messages: list[dict[str, str]], **kwargs: object
    ) -> LLMReply:
        self.calls.append(self.model_id)
        error_kind = self.failures.get(self.model_id)
        if error_kind:
            raise LLMProviderError(error_kind, error_kind=error_kind)
        return LLMReply(
            text=f"ok:{self.model_id}",
            provider="fake",
            model=self.model_id,
            raw_usage={
                "prompt_tokens": 1_000_000,
                "completion_tokens": 1_000_000,
                "total_tokens": 2_000_000,
                "finish_reason": "stop",
            },
        )


class SinkRecorder:
    """CallRecordSink 测试桩：截留 draft 供断言（绝不抛）。"""

    def __init__(self) -> None:
        self.drafts: list[LLMCallDraft] = []

    def submit(self, draft: LLMCallDraft) -> None:
        self.drafts.append(draft)


def _spec(
    model_id: str,
    priority: int,
    *,
    model: str = "",
    price_in: float | None = None,
    price_out: float | None = None,
) -> ModelSpec:
    return ModelSpec(
        model_id=model_id,
        model=model or model_id,
        base_url="https://example.test/v1",
        api_key="key",
        tags=("fast",),
        priority=priority,
        price_in=price_in,
        price_out=price_out,
    )


def _router(
    specs: dict[str, ModelSpec],
    failures: dict[str, str],
    calls: list[str],
    *,
    sink: SinkRecorder | None = None,
) -> ModelRouter:
    return ModelRouter(
        specs,
        provider_factory=lambda spec: FakeProvider(
            spec.model_id, failures, calls
        ),
        call_record_sink=sink,
    )


# ==================== ① 渠道 id 入口 → 同模型兄弟渠道候选集 ====================


def test_channel_id_override_expands_same_model_siblings_first() -> None:
    """指定渠道 id：该渠道首位，同模型兄弟渠道紧随，其他模型殿后。"""
    calls: list[str] = []
    router = _router(
        {
            "ch-a": _spec("ch-a", 1, model="grok-4.6", price_in=6.0, price_out=18.0),
            "ch-b": _spec("ch-b", 5, model="grok-4.6", price_in=0.32, price_out=0.96),
            "other": _spec("other", 2, model="glm-9"),
        },
        {"ch-a": "timeout"},
        calls,
    )

    ids = router.route_ids(message_text="", override="ch-a")
    assert ids == ["ch-a", "ch-b", "other"]

    # 首选渠道失败 → 同模型下一渠道接住（用户无感），不跳去其他模型。
    reply = router.generate(
        [{"role": "user", "content": "hi"}], override="ch-a"
    )
    assert reply.text == "ok:ch-b"
    assert calls == ["ch-a", "ch-b"]
    assert router.last_attempts == ["ch-a:timeout", "ch-b:success"]


def test_channel_id_override_siblings_order_follows_price() -> None:
    """兄弟渠道顺序沿用 channels_for_model 的价格序（缺价垫底）。"""
    calls: list[str] = []
    router = _router(
        {
            "ch-a": _spec("ch-a", 1, model="gemini-x", price_in=4.5, price_out=22.5),
            "ch-b": _spec("ch-b", 2, model="gemini-x", price_in=0.3, price_out=1.5),
            "other": _spec("other", 3, model="glm-9"),
        },
        {},
        calls,
    )
    ids = router.route_ids(message_text="", override="ch-a")
    assert ids == ["ch-a", "ch-b", "other"]


def test_channel_id_override_without_siblings_keeps_old_shape() -> None:
    """同模型无兄弟渠道：候选集 = 该渠道 + 其他模型（旧行为不回归）。"""
    calls: list[str] = []
    router = _router(
        {
            "solo": _spec("solo", 1, model="unique-model"),
            "other": _spec("other", 2, model="glm-9"),
        },
        {"solo": "timeout"},
        calls,
    )
    ids = router.route_ids(message_text="", override="solo")
    assert ids == ["solo", "other"]
    reply = router.generate([{"role": "user", "content": "hi"}], override="solo")
    assert reply.text == "ok:other"


# ==================== ② 模型名聚合去重（兄弟渠道只试一次） ====================


def test_model_name_override_does_not_retry_sibling_in_tail() -> None:
    calls: list[str] = []
    router = _router(
        {
            "ch-a": _spec("ch-a", 2, model="shared-model", price_in=6.0, price_out=18.0),
            "ch-b": _spec("ch-b", 5, model="shared-model", price_in=0.32, price_out=0.96),
            "other": _spec("other", 3, model="glm-9"),
        },
        {"ch-a": "timeout", "ch-b": "timeout"},
        calls,
    )

    reply = router.generate(
        [{"role": "user", "content": "hi"}], override="shared-model"
    )

    # 旧实现尾部自动队列里 ch-b 会再出现一次（同一渠道被试两次）。
    # 聚合分支按价格序：ch-b 均价低排在前。
    assert calls == ["ch-b", "ch-a", "other"]
    assert router.last_attempts.count("ch-b:timeout") == 1
    assert reply.text == "ok:other"


# ==================== ③ hedged 赢家渠道归因 ====================


def test_last_channel_id_parses_hedged_winner_mark() -> None:
    parse = ModelRouter._last_channel_id
    # 赢家记号无论先后都归因赢家（旧实现返回空串）。
    assert parse(["hedged:ch-a:winner", "hedged:ch-b:loser"]) == "ch-a"
    assert parse(["hedged:ch-b:loser", "hedged:ch-a:winner"]) == "ch-a"
    # 影子全败后串行路径接管：归因最后串行触达渠道。
    assert parse(["hedged:ch-a:loser", "hedged:ch-b:loser", "other:timeout"]) == "other"
    # 纯非渠道标记 / 纯 loser：诚实空串（attempts_json 留全轨迹可溯）。
    assert parse(["failover:deadline"]) == ""
    assert parse(["hedged:ch-a:loser", "hedged:ch-b:loser"]) == ""
    # 串行记号照旧。
    assert parse(["a:timeout", "b:success"]) == "b"


def test_hedged_winner_attribution_reaches_call_record() -> None:
    """出口记账从 reply.attempts 的 hedged 赢家记号解析渠道与价格。"""
    sink = SinkRecorder()
    calls: list[str] = []
    router = _router(
        {
            "ch-a": _spec("ch-a", 1, model="gemini-x", price_in=4.5, price_out=22.5),
            "ch-b": _spec("ch-b", 2, model="gemini-x", price_in=0.3, price_out=1.5),
        },
        {},
        calls,
        sink=sink,
    )
    reply = LLMReply(
        text="ok",
        provider="fake",
        model="gemini-x",
        raw_usage={
            "prompt_tokens": 1_000_000,
            "completion_tokens": 1_000_000,
            "total_tokens": 2_000_000,
        },
    )
    reply.attempts = ["hedged:ch-b:winner", "hedged:ch-a:loser"]
    router._emit_call_record(
        request_id="req-hedged",
        call_seq=1,
        session_id="s",
        capability="chat",
        started_at="2026-09-13T12:00:00.000+08:00",
        started_mono=time.monotonic(),
        reply=reply,
        error=None,
        global_effort="",
        complex_task=False,
    )

    assert len(sink.drafts) == 1
    draft = sink.drafts[0]
    # 归因实际服务的赢家渠道（ch-b 便宜先回），不是首选 ch-a，也不是空。
    assert draft.provider_id == "ch-b"
    assert draft.model_id == "ch-b"
    assert draft.actual_model == "gemini-x"
    # 价格按赢家渠道计价：in 0.3 + out 1.5（元/1M）× 各 1M tokens
    # = 1.8 元 = 1800 毫厘。
    assert draft.pricing_source == "channel_spec"
    assert draft.input_cost_milli == 300
    assert draft.output_cost_milli == 1_500
    assert draft.total_cost_milli == 1_800


# ==================== ④ failover 拨转计费归因实际服务渠道 ====================


def test_failover_bills_the_channel_that_actually_served() -> None:
    """首选贵渠道失败 → 次选便宜渠道服务 → 账本按便宜渠道计价。"""
    sink = SinkRecorder()
    calls: list[str] = []
    router = _router(
        {
            "ch-a": _spec("ch-a", 1, model="grok-4.6", price_in=6.0, price_out=18.0),
            "ch-b": _spec("ch-b", 5, model="grok-4.6", price_in=0.32, price_out=0.96),
        },
        {"ch-a": "timeout"},
        calls,
        sink=sink,
    )

    reply = router.generate(
        [{"role": "user", "content": "hi"}],
        override="ch-a",
        request_id="req-1",
        session_id="sess",
        capability="chat",
    )

    assert reply.text == "ok:ch-b"
    assert len(sink.drafts) == 1
    draft = sink.drafts[0]
    assert draft.request_id == "req-1"
    assert draft.provider_id == "ch-b"
    assert draft.model_id == "ch-b"
    assert draft.status == "success"
    # 渠道价随实际服务渠道：0.32 + 0.96（元/1M）× 各 1M tokens
    # = 1.28 元 = 1280 毫厘。
    assert draft.pricing_source == "channel_spec"
    assert draft.input_cost_milli == 320
    assert draft.output_cost_milli == 960
    assert draft.total_cost_milli == 1_280
    # 拨转轨迹保留：attempts 可追溯首选渠道的失败。
    assert draft.attempts == ["ch-a:timeout", "ch-b:success"]
    assert draft.attempts_json.count("ch-a") == 1


def test_failed_call_attributes_last_touched_channel() -> None:
    """全部渠道失败的最终失败行也带渠道轨迹（归因最后触达渠道）。"""
    sink = SinkRecorder()
    calls: list[str] = []
    router = _router(
        {
            "ch-a": _spec("ch-a", 1, model="shared", price_in=1.0, price_out=2.0),
            "ch-b": _spec("ch-b", 2, model="shared", price_in=1.0, price_out=2.0),
        },
        {"ch-a": "timeout", "ch-b": "timeout"},
        calls,
        sink=sink,
    )

    try:
        router.generate([{"role": "user", "content": "hi"}], override="ch-a")
    except LLMProviderError:
        pass
    else:  # pragma: no cover - 断言失败路径
        raise AssertionError("expected LLMProviderError")

    assert len(sink.drafts) == 1
    draft = sink.drafts[0]
    assert draft.status == "provider_failed"
    assert draft.provider_id == "ch-b"  # 最后触达渠道
    # 失败行无 token 消耗：按渠道价公式得 0（既有口径：无消耗即无费用）。
    assert draft.total_cost_milli == 0
    assert draft.attempts == ["ch-a:timeout", "ch-b:timeout"]


def test_registry_price_fallbacks_for_cache_rates() -> None:
    """缓存价缺省回退 price_in（账本计价口径随渠道透传）。"""
    sink = SinkRecorder()
    calls: list[str] = []
    router = _router(
        {
            "only": _spec(
                "only",
                1,
                model="m",
                price_in=2.0,
                price_out=6.0,
            ),
        },
        {},
        calls,
        sink=sink,
    )
    router.generate(
        [{"role": "user", "content": "hi"}],
        override="only",
        request_id="req-cache",
    )
    draft: LLMCallDraft = sink.drafts[0]
    # 缓存价字段不落 draft（账本行无此列）；口径体现在计价结果：
    # 1M in × 2.0 + 1M out × 6.0 = 8 元（缓存价缺省回退 price_in，
    # 本调用无缓存 token，计价不变）。
    assert draft.total_cost_milli == 8_000
    extra: dict[str, Any] = {
        "pricing_source": draft.pricing_source,
        "unpriced": draft.unpriced,
    }
    assert extra == {"pricing_source": "channel_spec", "unpriced": 0}
