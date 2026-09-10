"""审计修复 D 组（LLM 模型路由与渠道健康域）离线回归。

覆盖：D1 健康开关同源、D2 route_ids 按模型名聚合可达、D3 注册表合并
语义（已落地逻辑的防回归）、D5 巡检在飞互斥、D6 attempts 随调用携带
不串号、D9 失败话术顺序轮换、D10 工具循环累计 raw_usage。全部离线，
网络与 provider 均为假实现。
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

import plugins.bot_unified_runtime.llm.channel_health as channel_health_module
from plugins.bot_unified_runtime.llm.channel_health import (
    ChannelHealthStore,
    channel_health_enabled,
    channel_health_latency_first,
    probe_entry,
)
from plugins.bot_unified_runtime.llm.model_router import ModelRouter, ModelSpec
from plugins.bot_unified_runtime.llm.providers import LLMProviderError, LLMReply

_HEALTH_ENV_FLAGS = (
    "BOT_CHANNEL_HEALTH_ENABLED",
    "BOT_CHANNEL_HEALTH_LATENCY_FIRST",
)


def _clear_health_env(monkeypatch) -> None:
    for name in _HEALTH_ENV_FLAGS:
        monkeypatch.delenv(name, raising=False)


def _bare_router(
    specs: dict[str, dict],
    *,
    fallback_spec=None,
    credential_config=None,
) -> ModelRouter:
    """构造最小 router（与 test_channel_health 相同手法）：只设 route 路径
    需要的属性，健康开关走 config=None → env 兜底。"""
    built = {
        model_id: SimpleNamespace(
            model_id=model_id,
            model=item["model"],
            base_url=item.get("base_url", ""),
            api_key="k",
            api_keys=("k",),
            tags=("fast",),
            aliases=item.get("aliases", ()),
            priority=item.get("priority", 100),
            routing_group="",
            effort="",
            price_in=item.get("price_in"),
            price_out=item.get("price_out"),
        )
        for model_id, item in specs.items()
    }
    router = ModelRouter.__new__(ModelRouter)
    router.specs = built
    router._fallback_spec = fallback_spec
    router._priority_groups_cb = None
    if credential_config is not None:
        router._credential_config = credential_config
    return router


# ==================== D2：route_ids 按模型名聚合可达 ====================

def test_route_ids_exact_id_hit_routes_single_channel(monkeypatch) -> None:
    _clear_health_env(monkeypatch)
    router = _bare_router(
        {
            "a": {"model": "same-model", "priority": 1},
            "b": {"model": "same-model", "priority": 2},
        }
    )
    ids = router.route_ids(message_text="", override="a")
    assert ids[0] == "a"  # 精确命中注册条目 id：单渠道路由
    assert "b" in ids  # 其余候选仍作故障转移兜底
    assert ids.count("a") == 1


def test_route_ids_unknown_model_name_aggregates_by_price(monkeypatch) -> None:
    _clear_health_env(monkeypatch)
    router = _bare_router(
        {
            "expensive": {"model": "gemini-x", "priority": 1, "price_in": 3.0, "price_out": 15.0},
            "cheap": {"model": "gemini-x", "priority": 5, "price_in": 0.3, "price_out": 1.5},
            "other": {"model": "glm-9", "priority": 2},
        }
    )
    ids = router.route_ids(message_text="", override="gemini-x")
    # 聚合分支按价格升序（D2 修复前该分支因 _spec_for 恒合成 fallback 而不可达）
    assert ids[0] == "cheap"
    assert ids[1] == "expensive"
    assert "other" in ids  # 聚合后仍接自动路由兜底


def test_route_ids_fully_unknown_name_uses_fallback_spec(monkeypatch) -> None:
    _clear_health_env(monkeypatch)
    fallback = ModelSpec(
        model_id="default",
        model="fallback-model",
        base_url="https://main.test/v1",
        api_key="main-key",
        tags=("strong",),
        priority=1,
    )
    router = _bare_router({"a": {"model": "m1"}}, fallback_spec=fallback)
    ids = router.route_ids(message_text="", override="totally-unknown-model")
    assert ids[0] == "totally-unknown-model"  # 旧版「直接给模型名」兼容保留
    assert "a" in ids


def test_route_ids_fully_unknown_without_fallback_falls_back_to_auto(monkeypatch) -> None:
    _clear_health_env(monkeypatch)
    router = _bare_router({"a": {"model": "m1"}})
    ids = router.route_ids(message_text="", override="totally-unknown-model")
    assert ids == ["a"]


# ==================== D6：attempts 随调用携带，并发不串号 ====================

class _FirstCallFailsProvider:
    """first 渠道：第 1 次调用（线程 A）失败，第 2 次（线程 B）成功。"""

    def __init__(
        self,
        model_id: str,
        calls: list[str],
        *,
        entered_first: threading.Event,
        release_first: threading.Event,
        second_done: threading.Event,
    ) -> None:
        self.model_id = model_id
        self.calls = calls
        self._lock = threading.Lock()
        self._invocations = 0
        self._entered_first = entered_first
        self._release_first = release_first
        self._second_done = second_done

    def generate(self, messages, **kwargs):
        with self._lock:
            self._invocations += 1
            invocation = self._invocations
        self.calls.append(f"{self.model_id}#{invocation}")
        if invocation == 1:
            self._entered_first.set()
            self._release_first.wait(5)
            raise LLMProviderError("timeout", error_kind="timeout")
        self._second_done.set()
        return LLMReply(text="ok-first", provider="fake", model=self.model_id)


class _SecondProvider:
    """second 渠道：等线程 B 完成后再返回，保证 A 的第二次尝试与 B 收尾重叠。"""

    def __init__(self, model_id: str, calls: list[str], second_done: threading.Event) -> None:
        self.model_id = model_id
        self.calls = calls
        self._second_done = second_done

    def generate(self, messages, **kwargs):
        self._second_done.wait(5)
        self.calls.append(f"{self.model_id}:done")
        return LLMReply(text="ok-second", provider="fake", model=self.model_id)


def test_concurrent_generate_attempts_do_not_cross_contaminate(monkeypatch) -> None:
    _clear_health_env(monkeypatch)
    calls: list[str] = []
    entered_first = threading.Event()
    release_first = threading.Event()
    second_done = threading.Event()

    def factory(spec: ModelSpec):
        if spec.model_id == "first":
            return _FirstCallFailsProvider(
                "first",
                calls,
                entered_first=entered_first,
                release_first=release_first,
                second_done=second_done,
            )
        return _SecondProvider("second", calls, second_done)

    router = ModelRouter(
        {
            "first": ModelSpec(
                model_id="first", model="first", base_url="https://x.test/v1",
                api_key="k", tags=("fast",), priority=1,
            ),
            "second": ModelSpec(
                model_id="second", model="second", base_url="https://x.test/v1",
                api_key="k", tags=("fast",), priority=2,
            ),
        },
        provider_factory=factory,
    )

    boxes: dict[str, dict[str, object]] = {"a": {}, "b": {}}

    def run(slot: str) -> None:
        try:
            reply = router.generate(
                [{"role": "user", "content": "hi"}], message_text="hi"
            )
            boxes[slot]["reply"] = reply
        except LLMProviderError as exc:  # pragma: no cover - 本设计下不应发生
            boxes[slot]["error"] = exc

    thread_a = threading.Thread(target=run, args=("a",))
    thread_a.start()
    assert entered_first.wait(5)  # A 已进入 first 的第一次调用并暂停
    thread_b = threading.Thread(target=run, args=("b",))
    thread_b.start()
    # 给 B 一点时间完成（B 在 first 的第 2 次调用直接成功）。
    assert second_done.wait(5)
    release_first.set()  # 放行 A 的失败 → A 故障转移到 second
    thread_a.join(5)
    thread_b.join(5)
    assert not thread_a.is_alive() and not thread_b.is_alive()

    reply_a: LLMReply = boxes["a"]["reply"]  # type: ignore[assignment]
    reply_b: LLMReply = boxes["b"]["reply"]  # type: ignore[assignment]
    # 各自的 attempts 只含本次调用的轨迹（旧共享列表实现下两者都会读到
    # 混入对方记号的同一条污染列表）。
    assert reply_a.attempts == ["first:timeout", "second:success"]
    assert reply_b.attempts == ["first:success"]

    # 异常路径同样携带本次 attempts。
    def always_fail(spec: ModelSpec):
        return _AlwaysFailProvider(spec.model_id)

    failing_router = ModelRouter(
        {
            "only": ModelSpec(
                model_id="only", model="only", base_url="https://x.test/v1",
                api_key="k", tags=("fast",), priority=1,
            ),
        },
        provider_factory=always_fail,
    )
    with pytest.raises(LLMProviderError) as exc_info:
        failing_router.generate(
            [{"role": "user", "content": "hi"}], message_text="hi"
        )
    assert exc_info.value.attempts == ["only:timeout"]


class _AlwaysFailProvider:
    def __init__(self, model_id: str) -> None:
        self.model_id = model_id

    def generate(self, messages, **kwargs):
        raise LLMProviderError("timeout", error_kind="timeout")


# ==================== D1：健康开关与巡检侧同源 ====================

def test_health_enabled_flag_reads_config_first(monkeypatch) -> None:
    _clear_health_env(monkeypatch)
    # config 缺字段且 env 未设 → 默认关
    assert channel_health_enabled(None) is False
    # config 明确值生效（生产 .env-only 部署的主路径）
    assert channel_health_enabled(SimpleNamespace(bot_channel_health_enabled=False)) is False
    assert channel_health_enabled(SimpleNamespace(bot_channel_health_enabled=True)) is True
    # env 兜底（裸脚本/测试路径）
    monkeypatch.setenv("BOT_CHANNEL_HEALTH_ENABLED", "1")
    assert channel_health_enabled(None) is True
    # Config 主路径优先于 env：绝不两处各读各的
    monkeypatch.setenv("BOT_CHANNEL_HEALTH_ENABLED", "0")
    assert channel_health_enabled(SimpleNamespace(bot_channel_health_enabled=True)) is True
    assert channel_health_enabled(SimpleNamespace(bot_channel_health_enabled=False)) is False


def test_latency_first_flag_reads_config_first(monkeypatch) -> None:
    _clear_health_env(monkeypatch)
    assert channel_health_latency_first(None) is True  # 默认开
    assert channel_health_latency_first(SimpleNamespace(bot_channel_health_latency_first=False)) is False
    monkeypatch.setenv("BOT_CHANNEL_HEALTH_LATENCY_FIRST", "0")
    assert channel_health_latency_first(None) is False
    monkeypatch.setenv("BOT_CHANNEL_HEALTH_LATENCY_FIRST", "0")
    assert channel_health_latency_first(SimpleNamespace(bot_channel_health_latency_first=True)) is True


class _TimeoutProvider:
    def __init__(self, model_id: str, calls: list[str]) -> None:
        self.model_id = model_id
        self.calls = calls

    def generate(self, messages, **kwargs):
        self.calls.append(self.model_id)
        raise LLMProviderError("timeout", error_kind="timeout")


def test_generate_health_recording_follows_config(monkeypatch, tmp_path) -> None:
    _clear_health_env(monkeypatch)
    store = ChannelHealthStore(tmp_path / "h.sqlite3")
    monkeypatch.setattr(channel_health_module, "_GLOBAL_STORE", store)
    calls: list[str] = []

    def make_router(credential_config):
        return ModelRouter(
            {
                "m": ModelSpec(
                    model_id="m", model="m", base_url="https://x.test/v1",
                    api_key="k", tags=("fast",), priority=1,
                ),
            },
            provider_factory=lambda spec: _TimeoutProvider(spec.model_id, calls),
            credential_config=credential_config,
        )

    # 健康层关（config 明确关闭，模拟旧 env-only 误判场景的反面）→ 不写库。
    router_off = make_router(SimpleNamespace(bot_channel_health_enabled=False))
    with pytest.raises(LLMProviderError):
        router_off.generate([{"role": "user", "content": "hi"}], message_text="hi")
    assert store.snapshot("m") is None

    # 健康层开（config 主路径）→ 真实失败计入连续失败。
    router_on = make_router(SimpleNamespace(bot_channel_health_enabled=True))
    with pytest.raises(LLMProviderError):
        router_on.generate([{"role": "user", "content": "hi"}], message_text="hi")
    snapshot = store.snapshot("m")
    assert snapshot is not None
    assert snapshot["consecutive_fails"] == 1


# ==================== D5：巡检在飞互斥 ====================

def test_probe_all_rejects_second_run_while_in_flight(monkeypatch, tmp_path) -> None:
    store = ChannelHealthStore(tmp_path / "probe.sqlite3")
    entered = threading.Event()
    release = threading.Event()
    probed: list[str] = []

    def fake_probe_entry(spec, **kwargs):
        probed.append(spec.model_id)
        entered.set()
        release.wait(5)
        return True, 42, ""

    monkeypatch.setattr(channel_health_module, "probe_entry", fake_probe_entry)
    config = SimpleNamespace(
        bot_channel_probe_threads=2,
        bot_channel_probe_jitter_seconds=0,
    )
    specs_a = {
        "a": SimpleNamespace(model_id="a", model="m", base_url="http://x.test", api_key="k"),
    }
    specs_b = {
        "b": SimpleNamespace(model_id="b", model="m", base_url="http://x.test", api_key="k"),
    }
    result: dict[str, object] = {}

    def background() -> None:
        result["summary"] = channel_health_module.probe_all(
            config, specs_a, store, mode="manual"
        )

    worker = threading.Thread(target=background)
    try:
        worker.start()
        assert entered.wait(5)  # 第一路巡检已在飞
        busy = channel_health_module.probe_all(config, specs_b, store, mode="manual")
        assert busy["busy"] is True
        assert busy["probed"] == 0
        assert busy["detail"] == {}
        # 第二路没有发起任何真实探测（specs_b 的渠道 b 未被触碰）。
        assert probed == ["a"]
    finally:
        release.set()
        worker.join(5)
    summary = result["summary"]
    assert summary["ok"] == 1  # 第一路正常完成
    assert channel_health_module.probe_in_flight() is False


# ==================== D8：probe_entry 密钥解析链（顺带回归） ====================

def test_probe_entry_prefers_override_then_env(monkeypatch) -> None:
    monkeypatch.delenv("BOT_PROBE_KEY", raising=False)

    # base_url 指向本机关闭端口：不触外网、连接立即被拒。
    spec = SimpleNamespace(
        model_id="a", model="m", base_url="http://127.0.0.1:9",
        api_key="env:BOT_PROBE_KEY",
    )
    ok, _latency, error = probe_entry(spec, timeout_seconds=0.1)
    assert ok is False
    assert error.startswith("no_api_key")

    # override（probe_all 预解析结果）优先生效：走到了真实 HTTP 分支（连接失败）。
    ok2, _latency2, error2 = probe_entry(
        spec, timeout_seconds=0.1, api_key_override="resolved-key"
    )
    assert ok2 is False
    assert "no_api_key" not in error2


# ==================== D4：单例库路径单一解析 ====================

def test_get_store_singleton_ignores_mismatched_path(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(channel_health_module, "_GLOBAL_STORE", None)
    first = channel_health_module.get_channel_health_store(str(tmp_path / "a.sqlite3"))
    second = channel_health_module.get_channel_health_store(str(tmp_path / "b.sqlite3"))
    assert second is first  # 首次调用固定库位置，后续不一致路径只告警不换库


# ==================== D9：失败话术顺序轮换 ====================

def test_persona_failure_message_rotates_without_repeat() -> None:
    from plugins.bot_unified_runtime.capabilities.chat import (
        _FAILURE_MESSAGE_CURSOR,
        _PERSONA_FAILURE_MESSAGES,
        persona_failure_message,
    )

    session = "auditfix-d9"
    _FAILURE_MESSAGE_CURSOR.pop(session, None)
    try:
        first_round = [
            persona_failure_message(session)
            for _ in range(len(_PERSONA_FAILURE_MESSAGES))
        ]
        assert len(set(first_round)) == len(first_round)  # 一整轮零重复
        assert set(first_round) == set(_PERSONA_FAILURE_MESSAGES)
        second_round = [
            persona_failure_message(session)
            for _ in range(len(_PERSONA_FAILURE_MESSAGES))
        ]
        assert len(set(second_round)) == len(second_round)  # 第二轮同样零重复
        # 纯顺序轮换：12 条走完游标回到 0，第二轮与第一轮完全一致。
        assert second_round == first_round
    finally:
        _FAILURE_MESSAGE_CURSOR.pop(session, None)


# ==================== D10：工具循环累计 raw_usage ====================

class _ToolLoopProvider:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return LLMReply(
                text="",
                provider="fake",
                model="m",
                raw_usage={
                    "prompt_tokens": 10,
                    "completion_tokens": 2,
                    "total_tokens": 12,
                    "finish_reason": "tool_calls",
                },
                tool_calls=[
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "web_search", "arguments": "{\"query\": \"x\"}"},
                    }
                ],
            )
        return LLMReply(
            text="final",
            provider="fake",
            model="m",
            raw_usage={
                "prompt_tokens": 100,
                "completion_tokens": 7,
                "total_tokens": 107,
                "finish_reason": "stop",
            },
        )


def test_tool_loop_accumulates_raw_usage_across_rounds() -> None:
    from plugins.bot_unified_runtime.capabilities.chat import _generate_with_tool_loop

    provider = _ToolLoopProvider()
    reply = _generate_with_tool_loop(
        llm_provider=provider,
        model_router=None,
        messages=[{"role": "user", "content": "hi"}],
        message_text="hi",
        override="",
        tools=[{"type": "function", "function": {"name": "web_search"}}],
        llm_options={},
    )
    assert reply.text == "final"
    assert provider.calls == 2
    # 中间轮计费不再被覆盖丢弃：两轮 usage 累计。
    assert reply.raw_usage["prompt_tokens"] == 110
    assert reply.raw_usage["completion_tokens"] == 9
    assert reply.raw_usage["total_tokens"] == 119
    assert reply.raw_usage["finish_reason"] == "stop"  # 非数值字段最后一轮为准


# ==================== D3：注册表合并语义防回归（已落地逻辑） ====================

def test_merge_registry_entries_env_source_stays_live() -> None:
    from plugins.bot_unified_runtime.capabilities.runtime_admin import (
        _merge_registry_entries,
    )

    env = {
        "m1": {
            "model": "new-model-name",
            "base_url": "http://new.test/v1",
            "api_key": "env:NEW_KEY",
            "priority": 1,
        }
    }
    runtime_override = {
        "m1": {
            "model": "old-model-name",
            "base_url": "http://old.test/v1",
            "api_key": "old-plain-key",
            "priority": 3,
            "source": "env",
            "override_fields": ["effort"],
            "effort": "high",
        }
    }
    merged = _merge_registry_entries(env, runtime_override)
    # 内容字段以 .env 实时值为准（改 .env 的密钥轮换不被旧副本遮蔽）。
    assert merged["m1"]["model"] == "new-model-name"
    assert merged["m1"]["base_url"] == "http://new.test/v1"
    assert merged["m1"]["api_key"] == "env:NEW_KEY"
    # 管理员拥有的字段取运行时副本。
    assert merged["m1"]["priority"] == 3
    assert merged["m1"]["effort"] == "high"
    # .env 已删除的条目不再被旧运行时副本遮蔽。
    assert _merge_registry_entries({}, runtime_override) == {}


def test_merge_registry_entries_unmarked_legacy_snapshot_migrates_to_env_fresh() -> None:
    """B-14 迁移：旧格式（无 source 标记）的存量快照不再整体遮蔽 .env。

    .env 同名条目仍在 → 内容字段以 .env 实时值为准，仅 priority 取快照；
    .env 已删除 → 按纯运行时条目原样保留（与镜像条目的失效语义区分）。
    """
    from plugins.bot_unified_runtime.capabilities.runtime_admin import (
        _merge_registry_entries,
    )

    env = {"m1": {"model": "env-model", "base_url": "http://env.test/v1", "priority": 1}}
    legacy_snapshot = {
        "m1": {"model": "snapshot-model", "base_url": "http://snapshot.test/v1", "priority": 9}
    }
    merged = _merge_registry_entries(env, legacy_snapshot)
    assert merged["m1"]["model"] == "env-model"
    assert merged["m1"]["base_url"] == "http://env.test/v1"
    assert merged["m1"]["priority"] == 9
    # .env 已删除的旧快照按纯运行时条目原样保留。
    assert _merge_registry_entries({}, legacy_snapshot) == legacy_snapshot
