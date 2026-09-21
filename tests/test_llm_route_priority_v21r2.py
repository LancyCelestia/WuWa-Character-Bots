"""v21r2 R1 回归：严格注册表优先级、失败渠道冷却降级、INTIMATE grok 钉第一、
链预算止损、llm 告警折叠聚合。全离线（假 provider/假时钟），零真实网络/模型调用。

用户令（2026-09-17）：
- 渠道排序永远按注册表优先级处理；EWMA 只作同级 tiebreak（或配置键默认关）。
- 近期失败渠道短期熔断冷却：冷却期内不排前排（降级不剔除），重启不丢。
- 链预算感知：剩余预算不足以再跳时提前止损。
- INTIMATE 态 grok-4.6 钉死第一、影子并发跳过；任何重排不得把 grok 挤下
  第一（除非 grok 熔断冷却中——此时必须留「临时回落」日志）。
- 告警：300s 抑制聚合内 llm 多 kind 折叠，chain detail 压缩，信息不丢。
"""

from __future__ import annotations

import logging
import time
from types import SimpleNamespace

import pytest

import plugins.bot_unified_runtime.domains.chat_reply.llm_engine.channel_health as channel_health_module
from plugins.bot_unified_runtime.contracts import OperationalIssue, SessionType
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.channel_health import (
    ChannelHealthStore,
    demote_cooling_candidates,
    resolve_channel_cooldown_seconds,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router import (
    ModelRouter,
    ModelSpec,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
    LLMProviderError,
    LLMReply,
)
from plugins.bot_unified_runtime.domains.ops.monitor.alerts import (
    AdminAlertSuppression,
    build_operational_alert_text,
)

# ==================== 隔离与夹具 ====================


@pytest.fixture(autouse=True)
def _isolate_health_layer(tmp_path, monkeypatch):
    """健康层开（冷却依赖它）+ 全局单例钉到临时库 + 开关环境清场。

    A50 同款纪律：_GLOBAL_STORE 每测替换、db 路径钉 tmp_path；严格优先级与
    延迟择优默认值由各用例自行控制（本文件缺省=严格开/延迟关）。
    """
    db_path = str(tmp_path / "channel_health_v21r2.sqlite3")
    monkeypatch.setattr(
        channel_health_module,
        "_GLOBAL_STORE",
        channel_health_module.ChannelHealthStore(db_path),
    )
    monkeypatch.setattr(
        channel_health_module, "resolve_default_db_path", lambda: db_path
    )
    monkeypatch.setenv("BOT_CHANNEL_HEALTH_ENABLED", "1")
    monkeypatch.delenv("BOT_CHANNEL_HEALTH_LATENCY_FIRST", raising=False)
    monkeypatch.delenv("BOT_CHAT_STRICT_PRIORITY", raising=False)
    monkeypatch.delenv("BOT_CHAT_CHANNEL_COOLDOWN_SECONDS", raising=False)
    monkeypatch.delenv("BOT_CHAT_FAILOVER_MIN_HOP_SECONDS", raising=False)
    return db_path


class FakeProvider:
    """确定性假 provider：按渠道剧本成败，记录调用序与收到超时。"""

    def __init__(
        self,
        model_id: str,
        failures: dict[str, str],
        calls: list[str],
        timeouts: list[float] | None = None,
    ) -> None:
        self.model_id = model_id
        self.failures = failures
        self.calls = calls
        self.timeouts = timeouts if timeouts is not None else []

    def generate(self, messages: list[dict[str, str]], **kwargs: object) -> LLMReply:
        self.calls.append(self.model_id)
        timeout = kwargs.get("timeout_seconds")
        if isinstance(timeout, (int, float)):
            self.timeouts.append(float(timeout))
        error_kind = self.failures.get(self.model_id)
        if error_kind:
            raise LLMProviderError(error_kind, error_kind=error_kind)
        return LLMReply(text=f"ok:{self.model_id}", provider="fake", model=self.model_id)


def _spec(model_id: str, priority: int, *, model: str = "", **extra: object) -> ModelSpec:
    return ModelSpec(
        model_id=model_id,
        model=model or model_id,
        base_url="https://example.test/v1",
        api_key="k",
        tags=("fast",),
        priority=priority,
        **extra,
    )


def _router(
    specs: list[ModelSpec],
    failures: dict[str, str] | None = None,
    *,
    calls: list[str] | None = None,
    credential_config: object | None = None,
    content_route_cb: object | None = None,
    max_failover_seconds: float = 0.0,
    priority_groups: object | None = None,
) -> ModelRouter:
    calls = calls if calls is not None else []

    def factory(spec: ModelSpec) -> FakeProvider:
        return FakeProvider(spec.model_id, failures or {}, calls)

    return ModelRouter(
        {spec.model_id: spec for spec in specs},
        provider_factory=factory,
        credential_config=credential_config,
        content_route_cb=content_route_cb,  # type: ignore[arg-type]
        max_failover_seconds=max_failover_seconds,
        priority_groups=priority_groups,  # type: ignore[arg-type]
    )


# ==================== 1. 严格注册表优先级 ====================


def test_ewma_fast_low_priority_cannot_overtake(tmp_path, monkeypatch) -> None:
    """EWMA 再快也只作同级 tiebreak：低优先级渠道不得反超高优先级（用户令 b）。"""
    store = channel_health_module._GLOBAL_STORE
    store.record_success("slow-prio1", 20000)
    store.record_success("fast-prio2", 100)
    monkeypatch.setenv("BOT_CHANNEL_HEALTH_LATENCY_FIRST", "1")
    router = _router(
        [
            _spec("slow-prio1", 1, model="gemini-x"),
            _spec("fast-prio2", 2, model="gemini-x"),
        ]
    )
    assert router.channels_for_model("gemini-x") == ["slow-prio1", "fast-prio2"]


def test_ewma_tiebreaks_within_same_priority(tmp_path, monkeypatch) -> None:
    """同优先级内 EWMA 择快（tiebreak 语义的正向面）。"""
    store = channel_health_module._GLOBAL_STORE
    store.record_success("a-prio1-slow", 300)
    store.record_success("b-prio1-fast", 100)
    monkeypatch.setenv("BOT_CHANNEL_HEALTH_LATENCY_FIRST", "1")
    router = _router(
        [
            _spec("a-prio1-slow", 1, model="gemini-x"),
            _spec("b-prio1-fast", 1, model="gemini-x"),
        ]
    )
    assert router.channels_for_model("gemini-x") == ["b-prio1-fast", "a-prio1-slow"]


def test_price_is_tiebreak_not_primary_key(tmp_path, monkeypatch) -> None:
    """严格优先级缺省开：便宜的低优先级渠道不得反超贵的首选渠道。"""
    router = _router(
        [
            _spec("pricey-prio1", 1, model="m-x", price_in=9.0, price_out=9.0),
            _spec("cheap-prio2", 2, model="m-x", price_in=0.3, price_out=0.3),
        ]
    )
    assert router.channels_for_model("m-x") == ["pricey-prio1", "cheap-prio2"]
    # 显式关（legacy 逃生门）→ 恢复价格优先旧行为。
    monkeypatch.setenv("BOT_CHAT_STRICT_PRIORITY", "0")
    assert router.channels_for_model("m-x") == ["cheap-prio2", "pricey-prio1"]


# ==================== 2. 失败渠道冷却降级 ====================


def test_failed_channel_demoted_to_tail_on_next_request(tmp_path) -> None:
    """首跳失败（健康层未判 unavailable）→ 冷却降级：下一请求不再让它首发。"""
    store = channel_health_module._GLOBAL_STORE
    calls: list[str] = []
    config = SimpleNamespace(bot_chat_channel_cooldown_seconds=5.0)
    router = _router(
        [_spec("first", 1), _spec("second", 2)],
        {"first": "timeout"},
        calls=calls,
        credential_config=config,
    )
    reply = router.generate([{"role": "user", "content": "hi"}], message_text="hi")
    assert reply.text == "ok:second"
    assert store.cooling_ids() == {"first"}  # 冷却已落库
    # 下一请求：first 被降级到队尾，second 首发且直接成功（链缩短=1 跳）。
    calls.clear()
    reply2 = router.generate([{"role": "user", "content": "hi"}], message_text="hi")
    assert reply2.text == "ok:second"
    assert calls == ["second"]
    assert router.last_attempts == ["second:success"]


def test_cooldown_expiry_restores_priority_order(tmp_path) -> None:
    """冷却到期 → 渠道回归原优先级位（降级是暂时的，不剔除）。"""
    store = channel_health_module._GLOBAL_STORE
    store.record_failure("first", "kind=timeout", cooldown_seconds=0.3)
    assert store.cooling_ids() == {"first"}
    time.sleep(0.4)  # 留足裕量越过 0.3s 冷却窗
    assert store.cooling_ids() == set()


def test_success_clears_cooldown(tmp_path) -> None:
    store = channel_health_module._GLOBAL_STORE
    store.record_failure("ch", "kind=timeout", cooldown_seconds=300)
    assert store.cooling_ids() == {"ch"}
    store.record_success("ch", 100)
    assert store.cooling_ids() == set()


def test_all_cooling_keeps_original_order(tmp_path) -> None:
    """全部冷却 = 原序放行（防全瘫，与 filter_healthy_candidates 同哲学）。"""
    store = channel_health_module._GLOBAL_STORE
    store.record_failure("a", "err", cooldown_seconds=300)
    store.record_failure("b", "err", cooldown_seconds=300)
    ordered, demoted = demote_cooling_candidates(["a", "b"], store)
    assert ordered == ["a", "b"]
    assert demoted == []


def test_cooldown_persists_across_store_reopen(tmp_path) -> None:
    """冷却落 SQLite：重启（重开库）不丢。"""
    db = tmp_path / "cooldown.sqlite3"
    store = ChannelHealthStore(db)
    store.record_failure("ch-a", "kind=timeout", cooldown_seconds=300)
    reopened = ChannelHealthStore(db)
    assert reopened.cooling_ids() == {"ch-a"}
    snap = reopened.snapshot("ch-a")
    assert snap is not None and snap["cooldown_until"]


def test_resolve_channel_cooldown_seconds_config_env_default(monkeypatch) -> None:
    assert resolve_channel_cooldown_seconds(None) == 90.0  # 缺省
    monkeypatch.setenv("BOT_CHAT_CHANNEL_COOLDOWN_SECONDS", "45")
    assert resolve_channel_cooldown_seconds(None) == 45.0  # env 兜底
    assert (
        resolve_channel_cooldown_seconds(SimpleNamespace(bot_chat_channel_cooldown_seconds=12))
        == 12.0
    )  # config 主路径


# ==================== 3. INTIMATE grok 钉第一 ====================


def _intimate_cb(head_models: list[str]) -> object:
    def _cb(session_key: str, message_text: str) -> dict[str, object]:
        return {"mode": "intimate", "head_models": head_models}

    return _cb


_GROK_GEMINI_SPECS = [
    _spec("grok-ch", 1, model="grok-4.6"),
    _spec("gem-ch", 2, model="gemini-3.8-flash"),
]


def test_intimate_pins_grok_first_and_skips_shadow(tmp_path) -> None:
    """INTIMATE：grok 钉第一；影子并发跳过（attempts 无 hedged 记号）。"""
    calls: list[str] = []
    config = SimpleNamespace(
        bot_chat_hedged_requests_enabled=True,
        bot_chat_hedge_delay_seconds=0.01,
        bot_chat_hedge_max_candidates=2,
    )
    router = _router(
        list(_GROK_GEMINI_SPECS),
        calls=calls,
        credential_config=config,
        content_route_cb=_intimate_cb(["grok-4.6"]),
    )
    reply = router.generate(
        [{"role": "user", "content": "hi"}], message_text="hi", session_id="private:1"
    )
    assert reply.text == "ok:grok-ch"
    assert calls == ["grok-ch"]
    assert router.last_attempts == ["grok-ch:success"]
    assert all(not mark.startswith("hedged:") for mark in router.last_attempts)


def test_intimate_grok_cooldown_falls_back_with_log(tmp_path, caplog) -> None:
    """grok 熔断冷却中 → 允许临时回落，但必须留「临时回落」日志（用户令 e）。"""
    store = channel_health_module._GLOBAL_STORE
    calls: list[str] = []
    config = SimpleNamespace(bot_chat_channel_cooldown_seconds=300.0)
    router = _router(
        list(_GROK_GEMINI_SPECS),
        {"grok-ch": "timeout"},
        calls=calls,
        credential_config=config,
        content_route_cb=_intimate_cb(["grok-4.6"]),
    )
    with caplog.at_level(logging.WARNING, logger="plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router"):
        first = router.generate(
            [{"role": "user", "content": "hi"}], message_text="hi", session_id="private:1"
        )
    assert first.text == "ok:gem-ch"  # 首轮：grok 失败 → 按链转移到 gem
    assert store.cooling_ids() == {"grok-ch"}
    calls.clear()
    with caplog.at_level(logging.WARNING, logger="plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router"):
        second = router.generate(
            [{"role": "user", "content": "hi"}], message_text="hi", session_id="private:1"
        )
    # 下一请求：grok 冷却中被降级 → gem 首发成功，且日志标注临时回落。
    assert second.text == "ok:gem-ch"
    assert calls == ["gem-ch"]
    assert router.last_attempts == ["gem-ch:success"]
    assert any("临时回落" in record.getMessage() for record in caplog.records)


def test_fork_preserves_content_route_cb(tmp_path) -> None:
    """fork 继承内容路由回调（旧实现丢失 → 分叉路由退化默认链）。"""
    cb = _intimate_cb(["grok-4.6"])
    router = _router(list(_GROK_GEMINI_SPECS), content_route_cb=cb)
    assert router.fork()._content_route_cb is cb


# ==================== 4. 链预算止损 ====================


def test_budget_stop_loss_skips_doomed_final_hops(tmp_path) -> None:
    """剩余预算不足一跳（缺省 <3s）且已有真实尝试 → 提前止损不再残秒尝试。"""
    calls: list[str] = []
    router = _router(
        [_spec("c1", 1), _spec("c2", 2), _spec("c3", 3)],
        {"c1": "timeout", "c2": "timeout", "c3": "timeout"},
        calls=calls,
        max_failover_seconds=0.5,
    )
    with pytest.raises(LLMProviderError):
        router.generate([{"role": "user", "content": "hi"}], message_text="hi")
    assert calls == ["c1"]  # c2/c3 的残秒尝试被止损拦下
    assert router.last_attempts == ["c1:timeout", "failover:deadline"]


def test_budget_stop_loss_disabled_tries_all(tmp_path, monkeypatch) -> None:
    """止损关（0）→ 旧行为：预算内逐跳试完。"""
    monkeypatch.delenv("BOT_CHAT_FAILOVER_MIN_HOP_SECONDS", raising=False)
    calls: list[str] = []
    router = _router(
        [_spec("c1", 1), _spec("c2", 2), _spec("c3", 3)],
        {"c1": "timeout", "c2": "timeout", "c3": "timeout"},
        calls=calls,
        credential_config=SimpleNamespace(bot_chat_failover_min_hop_seconds=0.0),
        max_failover_seconds=0.5,
    )
    with pytest.raises(LLMProviderError):
        router.generate([{"role": "user", "content": "hi"}], message_text="hi")
    assert calls == ["c1", "c2", "c3"]


def test_stop_loss_never_blocks_first_attempt(tmp_path) -> None:
    """首跳豁免：预算再小，第一个候选也必须拿到机会（deadline 透传语义）。"""
    calls: list[str] = []
    timeouts: list[float] = []
    router = ModelRouter(
        {"solo": _spec("solo", 1)},
        provider_factory=lambda spec: FakeProvider(
            spec.model_id, {}, calls, timeouts
        ),
        max_failover_seconds=0.05,
    )
    reply = router.generate([{"role": "user", "content": "hi"}], message_text="hi")
    assert reply.text == "ok:solo"
    assert 0 < timeouts[0] <= 0.05


# ==================== 5. 告警折叠聚合与 chain 压缩 ====================


def _issue(kind: str, safe_summary: str = "", stage: str = "llm") -> OperationalIssue:
    return OperationalIssue(
        stage=stage,
        kind=kind,
        retryable=True,
        attempts=3,
        safe_summary=safe_summary,
    )


def _target() -> object:
    from plugins.bot_unified_runtime.domains.ops.monitor.alerts import AdminTarget

    return AdminTarget(adapter="onebot", bot_id="bot-1", target_id="10000")


def test_llm_kind_folding_suppresses_across_kinds() -> None:
    """窗口内不同 llm kind 折叠进同一抑制槽；到期放行时 kinds 清单随行带出。"""
    now = {"t": 1000.0}

    def clock() -> float:
        return now["t"]

    suppression = AdminAlertSuppression(window_seconds=300.0, clock=clock)
    target = _target()
    kw = {
        "source_adapter": "onebot",
        "source_bot": "bot-1",
        "target": target,
    }
    allowed1, _ = suppression.allow_issue(_issue("network"), **kw)  # type: ignore[arg-type]
    assert allowed1
    allowed2, suppressed2 = suppression.allow_issue(_issue("timeout"), **kw)  # type: ignore[arg-type]
    assert not allowed2 and suppressed2 == 1  # 跨 kind 折叠抑制
    now["t"] += 301.0
    allowed3, suppressed3 = suppression.allow_issue(_issue("deadline"), **kw)  # type: ignore[arg-type]
    assert allowed3 and suppressed3 == 1  # 上一窗口被抑制 1 条（timeout），计数不丢
    kinds = suppression.last_report_kinds_for_issue(_issue("deadline"), **kw)  # type: ignore[arg-type]
    assert kinds == ["network", "timeout", "deadline"]


def test_non_llm_stages_keep_per_kind_suppression() -> None:
    """非 llm stage 维持旧的按 kind 独立抑制槽（行为面不外溢）。"""
    now = {"t": 1000.0}
    suppression = AdminAlertSuppression(window_seconds=300.0, clock=lambda: now["t"])
    kw = {
        "source_adapter": "onebot",
        "source_bot": "bot-1",
        "target": _target(),
    }
    assert suppression.allow_issue(_issue("k1", stage="sender"), **kw)[0]  # type: ignore[arg-type]
    assert suppression.allow_issue(_issue("k2", stage="sender"), **kw)[0]  # type: ignore[arg-type]


def test_chain_detail_compression() -> None:
    """chain detail 压缩：`network chain=17 last=x` → `chain=17跳全败 last=x`。"""
    text = build_operational_alert_text(
        _issue("network", "network chain=17 last=umi-claude-sonnet-5"),
        source_adapter="onebot",
        source_bot="bot-1",
        session_type=SessionType.PRIVATE,
    )
    assert "chain=17跳全败 last=umi-claude-sonnet-5" in text
    # 非 llm stage 不改写。
    plain = build_operational_alert_text(
        _issue("k", "sender chain=2", stage="sender"),
        source_adapter="onebot",
        source_bot="bot-1",
        session_type=SessionType.PRIVATE,
    )
    assert "detail=sender chain=2" in plain
    # llm 无 chain 记号原样保留（防误伤既有口径）。
    intact = build_operational_alert_text(
        _issue("timeout", "upstream_timeout"),
        source_adapter="onebot",
        source_bot="bot-1",
        session_type=SessionType.PRIVATE,
    )
    assert "detail=upstream_timeout" in intact


def test_folded_kinds_rendered_into_alert_text() -> None:
    text = build_operational_alert_text(
        _issue("deadline"),
        source_adapter="onebot",
        source_bot="bot-1",
        session_type=SessionType.PRIVATE,
        folded_kinds=["network", "timeout", "deadline"],
    )
    assert "llm_kinds=[network|timeout|deadline]" in text
    # 单 kind / 空清单不渲染该段。
    single = build_operational_alert_text(
        _issue("network"),
        source_adapter="onebot",
        source_bot="bot-1",
        session_type=SessionType.PRIVATE,
        folded_kinds=["network"],
    )
    assert "llm_kinds=" not in single


# ==================== 6. R7 移交①：时段分组 order 收模型名 ====================


def _group_specs() -> list[ModelSpec]:
    return [
        _spec("gem-ch-b", 5, model="gemini-3.8-flash"),
        _spec("grok-ch", 8, model="grok-4.6"),
        _spec("gem-ch-a", 3, model="gemini-3.8-flash"),
        _spec("terra-ch", 10, model="gpt-5.6-terra"),
    ]


def test_priority_group_order_accepts_model_names() -> None:
    """R7 移交①修复：BOT_MODEL_PRIORITY_GROUPS order 收模型名（生产口径）。

    生产注册表 id 形如 axon-gemini-38f、.env 写真模型名 gemini-3.8-flash——
    旧实现只按渠道 id 匹配恒 no-op；修复后名称条目展开为该模型全部渠道
    （组内渠道序沿注册表 (priority, model_id)），分组只重排模型先后。
    """
    router = _router(
        _group_specs(),
        priority_groups=lambda: [{"name": "全天", "order": ["grok-4.6", "gpt-5.6-terra"]}],
    )
    ids = router._auto_route_ids("hi")
    # 头部 = grok 组（grok-ch）→ terra 组（terra-ch）；未提及的 gemini 组
    # 保持注册表序垫底（gem-ch-a prio3 在 gem-ch-b prio5 前）。
    assert ids == ["grok-ch", "terra-ch", "gem-ch-a", "gem-ch-b"]


def test_priority_group_order_still_accepts_channel_ids() -> None:
    """旧口径（渠道 id）不回归：id 条目照常头插。"""
    router = _router(
        _group_specs(),
        priority_groups=lambda: [{"name": "全天", "order": ["terra-ch"]}],
    )
    assert router._auto_route_ids("hi") == [
        "terra-ch",
        "gem-ch-a",
        "gem-ch-b",
        "grok-ch",
    ]


def test_priority_group_order_mixed_and_dedup() -> None:
    """混排 id+名称、名称展开去重：同名渠道不重复入队。"""
    router = _router(
        _group_specs(),
        priority_groups=lambda: [
            {"name": "全天", "order": ["gpt-5.6-terra", "terra-ch", "gemini-3.8-flash"]}
        ],
    )
    ids = router._auto_route_ids("hi")
    assert ids == ["terra-ch", "gem-ch-a", "gem-ch-b", "grok-ch"]


def test_priority_group_unknown_entries_ignored() -> None:
    """未知条目（既非 id 也非名称）忽略；空 head 保持注册表原序。"""
    router = _router(
        _group_specs(),
        priority_groups=lambda: [{"name": "全天", "order": ["no-such-model"]}],
    )
    assert router._auto_route_ids("hi") == ["gem-ch-a", "gem-ch-b", "grok-ch", "terra-ch"]
