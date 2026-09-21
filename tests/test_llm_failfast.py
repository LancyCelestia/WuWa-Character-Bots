"""v21r5 LLM 链级 fail-fast + config_missing 重复冷却（A 席）回归。

背景（2026-09-19 实警）：全网故障时 failover 链遍历全部渠道 × 每跳 ~20s 读
超时，最长烧满 BOT_CHAT_FAILOVER_MAX_SECONDS=300s 才给降级回复（实警
15:02 chain=15 跳全败 kind=network）。修复语义：

1. 链级 fail-fast：单次 generate() 调用链内连续 ≥5 跳网络类失败
   （network/timeout；4xx/auth/server/rate_limited/provider_error 打断
   连续计数；config_missing 中性）→ 中止剩余候选链，raise last_error 走
   既有失败面（能力层产出私聊五池话术 / 群聊 A-19 降级池的用户可见回复）。
2. config_missing 重复冷却：同渠道进程生命周期累计 ≥3 次 → 按既有 cooldown
   机制降速（10× bot_chat_channel_cooldown_seconds，缺省 90s → 900s），
   前 2 次不冷却（「配置问题≠渠道不可用」语义保留）。

测试全离线（FakeProvider 模式照抄 test_model_router_failover.py）。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.channel_health import (
    demote_cooling_candidates,
    get_channel_health_store,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router import (
    ModelRouter,
    ModelSpec,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
    LLMProviderError,
    LLMReply,
)

# ==================== channel_health 单例每测复位（A50 同款手法） ====================


@pytest.fixture(autouse=True)
def _reset_channel_health_singleton(tmp_path, monkeypatch):
    """每个测试前复位 channel_health 进程级单例并隔离到 tmp_path 独立库。

    手法与 test_model_router_failover.py 同源：全新空 store 替换
    ``_GLOBAL_STORE``（monkeypatch 自动还原）+ resolve_default_db_path 钉
    tmp_path + 两个开关环境变量显式钉 0（本文件缺省 = 健康层关闭；
    config_missing 冷却用例内自行 setenv 开启）。
    """
    import plugins.bot_unified_runtime.domains.chat_reply.llm_engine.channel_health as channel_health_module

    db_path = str(tmp_path / "channel_health.sqlite3")
    monkeypatch.setattr(
        channel_health_module,
        "_GLOBAL_STORE",
        channel_health_module.ChannelHealthStore(db_path),
    )
    monkeypatch.setattr(
        channel_health_module, "resolve_default_db_path", lambda: db_path
    )
    monkeypatch.setenv("BOT_CHANNEL_HEALTH_ENABLED", "0")
    monkeypatch.setenv("BOT_CHANNEL_HEALTH_LATENCY_FIRST", "0")


class FakeProvider:
    def __init__(self, model_id: str, failures: dict[str, str], calls: list[str]) -> None:
        self.model_id = model_id
        self.failures = failures
        self.calls = calls

    def generate(self, messages: list[dict[str, str]], **kwargs: object) -> LLMReply:
        self.calls.append(self.model_id)
        error_kind = self.failures.get(self.model_id)
        if error_kind:
            raise LLMProviderError(error_kind, error_kind=error_kind)
        return LLMReply(text=f"ok:{self.model_id}", provider="fake", model=self.model_id)


def _router(
    specs: dict[str, ModelSpec], failures: dict[str, str], calls: list[str]
) -> ModelRouter:
    return ModelRouter(
        specs,
        provider_factory=lambda spec: FakeProvider(spec.model_id, failures, calls),
    )


def _spec(model_id: str, priority: int, *, api_key: str = "key") -> ModelSpec:
    return ModelSpec(
        model_id=model_id,
        model=model_id,
        base_url="https://example.test/v1",
        api_key=api_key,
        tags=("fast",),
        priority=priority,
    )


def _chain_specs(names: list[str], *, keyless: set[str] | None = None) -> dict[str, ModelSpec]:
    keyless = keyless or set()
    return {
        name: _spec(name, index + 1, api_key="" if name in keyless else "key")
        for index, name in enumerate(names)
    }


def _generate(router: ModelRouter) -> LLMReply:
    return router.generate([{"role": "user", "content": "hello"}], message_text="hello")


# ==================== ① 链级 fail-fast ====================


def test_five_consecutive_network_failures_abort_chain() -> None:
    """连续 5 跳 timeout → 中止剩余链并 raise（能力层失败面据此产出降级回复）。

    后续本可成功的渠道（f/g）绝不被拨号——这正是全网故障时的早停语义。
    """
    calls: list[str] = []
    names = ["a", "b", "c", "d", "e", "f", "g"]
    router = _router(
        _chain_specs(names),
        {"a": "timeout", "b": "timeout", "c": "timeout", "d": "timeout", "e": "timeout"},
        calls,
    )

    with pytest.raises(LLMProviderError) as raised:
        _generate(router)

    assert raised.value.error_kind == "timeout"
    assert calls == ["a", "b", "c", "d", "e"]
    assert router.last_attempts == [
        "a:timeout",
        "b:timeout",
        "c:timeout",
        "d:timeout",
        "e:timeout",
        "failover:failfast_network",
    ]
    assert raised.value.attempts == router.last_attempts


def test_network_and_timeout_kinds_count_jointly() -> None:
    """network 与 timeout 同属网络类，混合出现也累计（connect 类归 network）。"""
    calls: list[str] = []
    router = _router(
        _chain_specs(["a", "b", "c", "d", "e", "f"]),
        {"a": "network", "b": "timeout", "c": "network", "d": "timeout", "e": "timeout"},
        calls,
    )

    with pytest.raises(LLMProviderError) as raised:
        _generate(router)

    assert raised.value.error_kind == "timeout"
    assert calls == ["a", "b", "c", "d", "e"]
    assert router.last_attempts[-1] == "failover:failfast_network"


def test_below_threshold_network_failures_still_fail_over() -> None:
    """4 连跳网络失败（<5）→ 不触发 fail-fast，第 5 渠道正常接管。"""
    calls: list[str] = []
    router = _router(
        _chain_specs(["a", "b", "c", "d", "e"]),
        {"a": "timeout", "b": "network", "c": "timeout", "d": "timeout"},
        calls,
    )

    reply = _generate(router)

    assert reply.text == "ok:e"
    assert calls == ["a", "b", "c", "d", "e"]
    assert "failover:failfast_network" not in router.last_attempts


def test_non_network_failure_breaks_consecutive_streak() -> None:
    """4 连跳网络失败 + auth（服务端可达=网络通）→ 计数打断，链继续走完。"""
    calls: list[str] = []
    router = _router(
        _chain_specs(["a", "b", "c", "d", "e", "f", "g", "h"]),
        {
            "a": "timeout",
            "b": "timeout",
            "c": "timeout",
            "d": "timeout",
            "e": "auth",
            "f": "timeout",
            "g": "timeout",
        },
        calls,
    )

    reply = _generate(router)

    assert reply.text == "ok:h"
    assert calls == ["a", "b", "c", "d", "e", "f", "g", "h"]
    assert router.last_attempts[-1] == "h:success"


def test_config_missing_is_neutral_to_network_streak() -> None:
    """config_missing 未碰网络：既不累加也不打断连续网络失败计数。

    a-c 网络失败（3）→ d config_missing（中性）→ e-f 网络失败（4、5）
    → 达阈值中止；g 不被拨号。
    """
    calls: list[str] = []
    router = _router(
        _chain_specs(["a", "b", "c", "d", "e", "f", "g"], keyless={"d"}),
        {"a": "timeout", "b": "timeout", "c": "timeout", "e": "timeout", "f": "timeout"},
        calls,
    )

    with pytest.raises(LLMProviderError) as raised:
        _generate(router)

    assert raised.value.error_kind == "timeout"
    assert calls == ["a", "b", "c", "e", "f"]
    assert router.last_attempts == [
        "a:timeout",
        "b:timeout",
        "c:timeout",
        "d:config_missing",
        "e:timeout",
        "f:timeout",
        "failover:failfast_network",
    ]


# ==================== ③ 单渠道失败不影响后续渠道正常 failover ====================


def test_single_channel_network_failure_fails_over_to_next() -> None:
    """单渠道网络失败 → 下一渠道正常接管（fail-fast 不改变小规模故障行为）。"""
    calls: list[str] = []
    router = _router(
        _chain_specs(["first", "second"]),
        {"first": "network"},
        calls,
    )

    reply = _generate(router)

    assert reply.text == "ok:second"
    assert calls == ["first", "second"]
    assert router.last_attempts == ["first:network", "second:success"]


# ==================== ② config_missing 重复冷却 ====================


def test_config_missing_repeated_cooldown_after_third_occurrence(tmp_path, monkeypatch) -> None:
    """同渠道 config_missing：前 2 次不冷却，第 3 次按 10× 常规冷却降速。"""
    monkeypatch.setenv("BOT_CHANNEL_HEALTH_ENABLED", "1")
    monkeypatch.setenv("BOT_CHAT_CHANNEL_COOLDOWN_SECONDS", "90")
    store = get_channel_health_store()
    calls: list[str] = []
    router = _router(
        _chain_specs(["bad", "good"], keyless={"bad"}),
        {},
        calls,
    )

    for _ in range(2):
        reply = _generate(router)
        assert reply.text == "ok:good"
    # 前 2 次：绝不冷却（「配置问题≠渠道不可用」），健康行也不写。
    assert store.cooling_ids() == set()
    assert store.snapshot("bad") is None

    # 第 3 次：累计达阈值 → 加长冷却（10×90s=900s）落地。
    reply = _generate(router)
    assert reply.text == "ok:good"
    assert router.last_attempts == ["bad:config_missing", "good:success"]
    assert "bad" in store.cooling_ids()
    row = store.snapshot("bad")
    assert row is not None
    assert "config_missing_repeated" in row["last_error"]
    until = datetime.fromisoformat(row["cooldown_until"])
    duration = (until - datetime.now(timezone.utc)).total_seconds()
    assert 850 < duration <= 950, f"cooldown should be ~900s, got {duration}"

    # 冷却中的渠道在候选队列里被降级到队尾（既有 demote 语义，不剔除）。
    assert demote_cooling_candidates(["bad", "good"], store) == (["good", "bad"], ["bad"])

    # 第 4 次：计数继续累计，冷却顺延（滚动窗口），渠道仍不剔除。
    reply = _generate(router)
    assert reply.text == "ok:good"
    assert "bad" in store.cooling_ids()


def test_config_missing_cooldown_inert_when_health_layer_disabled(monkeypatch) -> None:
    """健康层关闭（生产缺省口径）时整体空转：零计数、零冷却、零写库。"""
    monkeypatch.setenv("BOT_CHANNEL_HEALTH_ENABLED", "0")
    store = get_channel_health_store()
    calls: list[str] = []
    router = _router(
        _chain_specs(["bad", "good"], keyless={"bad"}),
        {},
        calls,
    )

    for _ in range(3):
        reply = _generate(router)
        assert reply.text == "ok:good"

    assert store.cooling_ids() == set()
    assert store.snapshot("bad") is None
    # 计数器也零足迹（helper 在开关判断后直接返回）。
    assert store._config_missing_counts == {}
    # config_missing 不构造 provider：bad 只留记号，真实拨号只有 good。
    assert calls == ["good", "good", "good"]
    assert router.last_attempts == ["bad:config_missing", "good:success"]
