"""渠道健康 v2 回归：EWMA 动态测量、老库迁移、ema 路由排序（动态切换）、
慢渠道阈值解析、自适应超时、影子并发（hedged request）无损无感切换、
env 镜像条目不遮蔽 .env（Task4 跨文件 follow-up）。

影子并发用可控假 provider（Event + sleep 控制时序）断言 winner 时序与
记账；时间断言全部留足裕量（事件同步为主、耗时比大小为辅），避免 flaky。
"""

from __future__ import annotations

import ast
import inspect
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import plugins.bot_unified_runtime.domains.chat_reply.llm_engine.channel_health as channel_health_module
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.channel_health import (
    PER_HOP_TIMEOUT_FLOOR_SECONDS,
    ChannelHealthStore,
    filter_healthy_candidates,
    resolve_slow_ema_ms,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router import (
    ModelRouter,
    ModelSpec,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
    LLMProviderError,
    LLMReply,
)


def _store(tmp_path) -> ChannelHealthStore:
    return ChannelHealthStore(tmp_path / "health-v2.sqlite3")


@pytest.fixture
def health_on(tmp_path, monkeypatch):
    """开启健康层（env 主路径）并把全局 store 指向临时库。"""
    store = ChannelHealthStore(tmp_path / "h-global.sqlite3")
    monkeypatch.setenv("BOT_CHANNEL_HEALTH_ENABLED", "1")
    monkeypatch.delenv("BOT_CHANNEL_HEALTH_LATENCY_FIRST", raising=False)
    monkeypatch.delenv("BOT_CHANNEL_HEALTH_DB", raising=False)
    monkeypatch.setattr(channel_health_module, "_GLOBAL_STORE", store)
    return store


# ==================== 1. EWMA 动态测量 ====================

def test_ewma_first_sample_direct_then_smoothing(tmp_path) -> None:
    store = _store(tmp_path)
    store.record_success("a", 1000)
    snap = store.snapshot("a")
    assert snap["ema_ms"] == 1000  # 首测直取
    assert snap["latency_ms"] == 1000  # 最近一次照旧
    assert snap["samples"] == 1
    store.record_success("a", 2000)
    snap = store.snapshot("a")
    # ema = round(0.3*2000 + 0.7*1000) = 1300；latency 仍是最近一次。
    assert snap["ema_ms"] == 1300
    assert snap["latency_ms"] == 2000
    assert snap["samples"] == 2
    store.record_success("a", 2000)
    # 第二次平滑更新数学断言：round(0.3*2000 + 0.7*1300) = 1510。
    assert store.snapshot("a")["ema_ms"] == 1510
    assert store.snapshot("a")["samples"] == 3


def test_ewma_failure_does_not_touch_ema(tmp_path) -> None:
    store = _store(tmp_path)
    store.record_success("a", 1000)
    store.record_failure("a", "HTTP 429: rate limited")
    snap = store.snapshot("a")
    assert snap["ema_ms"] == 1000  # 失败不动 ema
    assert snap["samples"] == 1
    assert snap["latency_ms"] == 1000  # 失败也不动最近一次


def test_ema_latencies_filters_state_and_null(tmp_path) -> None:
    store = _store(tmp_path)
    store.record_success("measured", 120)
    store.record_failure("no-ema", "err")  # 单次失败：state=ok，但无 ema
    store.record_failure("down", "err")
    store.record_failure("down", "err")  # 两次：temporarily_unavailable
    assert store.ema_latencies() == {"measured": 120}


def test_old_schema_upgrades_losslessly(tmp_path) -> None:
    """老库（无 ema_ms/samples 列）打开后新列存在且旧数据可读。"""
    db = tmp_path / "legacy.sqlite3"
    con = sqlite3.connect(db)
    con.execute(
        """
        CREATE TABLE channel_health (
            model_id TEXT PRIMARY KEY,
            state TEXT NOT NULL,
            consecutive_fails INTEGER NOT NULL DEFAULT 0,
            latency_ms INTEGER,
            last_error TEXT DEFAULT '',
            last_probe_at TEXT DEFAULT '',
            last_ok_at TEXT DEFAULT '',
            updated_at TEXT DEFAULT ''
        )
        """
    )
    con.execute(
        "INSERT INTO channel_health"
        " (model_id, state, consecutive_fails, latency_ms, last_error,"
        "  last_probe_at, last_ok_at, updated_at)"
        " VALUES ('legacy', 'ok', 0, 123, '', '', '', '')"
    )
    con.commit()
    con.close()
    store = ChannelHealthStore(db)
    snap = store.snapshot("legacy")
    assert snap["latency_ms"] == 123  # 旧数据无损
    assert snap["ema_ms"] is None
    assert snap["samples"] == 0
    store.record_success("legacy", 200)  # 升级后立即可记账
    assert store.ema_latencies() == {"legacy": 200}


def test_resolve_slow_ema_ms_config_env_default(monkeypatch) -> None:
    monkeypatch.delenv("BOT_CHANNEL_SLOW_EMA_MS", raising=False)
    assert resolve_slow_ema_ms(SimpleNamespace(bot_channel_slow_ema_ms=8000)) == 8000
    assert resolve_slow_ema_ms(None) == 15000  # 默认
    monkeypatch.setenv("BOT_CHANNEL_SLOW_EMA_MS", "9000")
    assert resolve_slow_ema_ms(None) == 9000  # env 兜底
    assert resolve_slow_ema_ms(SimpleNamespace(bot_channel_slow_ema_ms=7000)) == 7000


# ==================== 2. 动态切换：路由排序用 EWMA ====================

def _spec(model_id: str, priority: int, **extra: object) -> ModelSpec:
    return ModelSpec(
        model_id=model_id,
        model=str(extra.pop("model", model_id)),
        base_url="https://example.test/v1",
        api_key="k",
        tags=("fast",),
        priority=priority,
        **extra,
    )


def _router(
    specs: list[ModelSpec],
    factory,
    *,
    credential_config=None,
    dynamic_registry=None,
    timeout_seconds: float = 30.0,
    max_failover_seconds: float = 0.0,
) -> ModelRouter:
    return ModelRouter(
        {spec.model_id: spec for spec in specs},
        provider_factory=factory,
        credential_config=credential_config,
        dynamic_registry=dynamic_registry,
        timeout_seconds=timeout_seconds,
        max_failover_seconds=max_failover_seconds,
    )


def test_channels_for_model_orders_by_ema_not_last_sample(
    tmp_path, monkeypatch
) -> None:
    store = ChannelHealthStore(tmp_path / "h.sqlite3")
    monkeypatch.setenv("BOT_CHANNEL_HEALTH_ENABLED", "1")
    monkeypatch.setattr(channel_health_module, "_GLOBAL_STORE", store)
    # A：最近一次 100（单样本，ema=100）；B：两次后 last=50 但 ema=225。
    store.record_success("by-ema-fast", 100)
    store.record_success("by-last-fast", 300)
    store.record_success("by-last-fast", 50)
    assert store.snapshot("by-last-fast")["ema_ms"] == 225
    assert store.snapshot("by-last-fast")["latency_ms"] == 50
    router = _router(
        [
            _spec("by-ema-fast", 1, model="gemini-x"),
            _spec("by-last-fast", 2, model="gemini-x"),
            _spec("unmeasured", 3, model="gemini-x"),
        ],
        lambda spec: None,
    )
    # 按最近一次排序 B(50) 在前；按 ema 排序 A(100) 在前 → v2 用 ema。
    assert router.channels_for_model("gemini-x") == [
        "by-ema-fast",
        "by-last-fast",
        "unmeasured",
    ]


def test_channels_for_model_ema_disabled_falls_back_price(tmp_path, monkeypatch) -> None:
    store = ChannelHealthStore(tmp_path / "h.sqlite3")
    store.record_success("pricey", 100)
    store.record_success("cheap", 900)
    router = _router(
        [
            _spec("pricey", 1, model="m-shared", price_in=3.0, price_out=9.0),
            _spec("cheap", 2, model="m-shared", price_in=0.3, price_out=0.9),
        ],
        lambda spec: None,
    )
    monkeypatch.setattr(channel_health_module, "_GLOBAL_STORE", store)
    monkeypatch.setenv("BOT_CHANNEL_HEALTH_ENABLED", "1")
    monkeypatch.setenv("BOT_CHANNEL_HEALTH_LATENCY_FIRST", "0")
    # 钉住 legacy 价格序语义（v21r2 R1 缺省 bot_chat_strict_priority=true
    # 改为注册表优先级主键，见 test_llm_route_priority_v21r2.py）。
    monkeypatch.setenv("BOT_CHAT_STRICT_PRIORITY", "0")
    # 延迟择优关 → 价格均值序（cheap 0.6 < pricey 6.0），ema 不参与。
    assert router.channels_for_model("m-shared") == ["cheap", "pricey"]


# ==================== 3. 自适应超时 ====================

class TimeoutCaptureProvider:
    """记录每次调用收到的 timeout_seconds，然后成功。"""

    def __init__(self, model_id: str, captured: list[float]) -> None:
        self.model_id = model_id
        self.captured = captured

    def generate(self, messages: list[dict[str, str]], **kwargs: object) -> LLMReply:
        timeout = kwargs.get("timeout_seconds")
        if isinstance(timeout, (int, float)):
            self.captured.append(float(timeout))
        return LLMReply(text=f"ok:{self.model_id}", provider="fake", model=self.model_id)


def _capture_router(captured: list[float], credential_config) -> ModelRouter:
    """基座超时取生产键缺省（`bot_chat_timeout_seconds`），**不取 30**。

    收紧只在「钳制结果 ≠ 原值」时才注入 `timeout_seconds`（v1 语义）。地板
    （`PER_HOP_TIMEOUT_FLOOR_SECONDS`，台账 #80 前=8s、后=30s）若与基座相等，
    两枚参数会同时落到"不注入＝[]"——锁就失去区分度。基座高于地板才量得出方向。
    """
    from plugins.bot_unified_runtime.config import Config

    hop_base = float(Config.model_fields["bot_chat_timeout_seconds"].default)
    return _router(
        [_spec("ch-a", 1), _spec("ch-b", 2)],
        lambda spec: TimeoutCaptureProvider(spec.model_id, captured),
        credential_config=credential_config,
        timeout_seconds=hop_base,
    )


@pytest.mark.parametrize(
    ("ema_ms", "expected"),
    [
        # ema×3 远低地板 ⇒ 结果由**地板**决定（地板取真身，本文件不另抄秒数）⇒ 注入
        (1000, [PER_HOP_TIMEOUT_FLOOR_SECONDS]),
        # ema×3=60 高于基座 ⇒ min 回落原值 ⇒ 不注入（v1 语义）
        (20000, []),
    ],
)
def test_adaptive_timeout_tightens_by_ema(
    tmp_path, monkeypatch, health_on, ema_ms, expected
) -> None:
    store = channel_health_module._GLOBAL_STORE
    store.record_success("ch-a", ema_ms)
    captured: list[float] = []
    router = _capture_router(
        captured, SimpleNamespace(bot_channel_adaptive_timeout=True)
    )
    reply = router.generate([{"role": "user", "content": "hi"}], override="ch-a")
    assert reply.text == "ok:ch-a"
    assert captured == expected


def test_adaptive_timeout_switch_off_keeps_original(health_on) -> None:
    store = channel_health_module._GLOBAL_STORE
    store.record_success("ch-a", 1000)
    captured: list[float] = []
    router = _capture_router(
        captured, SimpleNamespace(bot_channel_adaptive_timeout=False)
    )
    reply = router.generate([{"role": "user", "content": "hi"}], override="ch-a")
    assert reply.text == "ok:ch-a"
    assert captured == []  # 开关关 → 不注入收紧后的 timeout（provider 用自身默认）


def test_adaptive_timeout_unknown_channel_untouched(health_on) -> None:
    captured: list[float] = []
    router = _capture_router(
        captured, SimpleNamespace(bot_channel_adaptive_timeout=True)
    )
    reply = router.generate([{"role": "user", "content": "hi"}], override="ch-b")
    assert reply.text == "ok:ch-b"
    assert captured == []  # 无 ema 数据 → 不收紧


# ==================== 4. 影子并发（hedged request） ====================

class ScriptedProvider:
    """可控时序假 provider：Event 同步 + 可控延迟/成败。

    started 事件在进入 generate 时置位（供时序断言），完成时置 done。
    """

    def __init__(
        self,
        model_id: str,
        delay: float,
        behavior: object,  # True=成功；字符串=以该 error_kind 失败
        started: dict[str, threading.Event],
        done: dict[str, threading.Event],
        call_starts: list[tuple[str, float]],
    ) -> None:
        self.model_id = model_id
        self.delay = delay
        self.behavior = behavior
        self.started = started
        self.done = done
        self.call_starts = call_starts

    def generate(self, messages: list[dict[str, str]], **kwargs: object) -> LLMReply:
        self.started[self.model_id].set()
        self.call_starts.append((self.model_id, time.monotonic()))
        if self.delay > 0:
            time.sleep(self.delay)
        self.done[self.model_id].set()
        if isinstance(self.behavior, str):
            raise LLMProviderError(self.behavior, error_kind=self.behavior)
        return LLMReply(
            text=f"ok:{self.model_id}", provider="fake", model=self.model_id
        )


def _hedge_router(
    plans: dict[str, tuple[float, object]],
    *,
    enabled: bool = True,
    hedge_delay: float = 0.3,
    timeout_seconds: float = 30.0,
    max_failover_seconds: float = 0.0,
) -> tuple[ModelRouter, dict[str, threading.Event], dict[str, threading.Event], list[tuple[str, float]]]:
    started = {mid: threading.Event() for mid in plans}
    done = {mid: threading.Event() for mid in plans}
    call_starts: list[tuple[str, float]] = []

    def factory(spec: ModelSpec) -> ScriptedProvider:
        delay, behavior = plans[spec.model_id]
        return ScriptedProvider(
            spec.model_id, delay, behavior, started, done, call_starts
        )

    config = SimpleNamespace(
        bot_chat_hedged_requests_enabled=enabled,
        bot_chat_hedge_delay_seconds=hedge_delay,
        bot_chat_hedge_max_candidates=2,
    )
    router = _router(
        [_spec(mid, index + 1) for index, mid in enumerate(plans)],
        factory,
        credential_config=config,
        timeout_seconds=timeout_seconds,
        max_failover_seconds=max_failover_seconds,
    )
    return router, started, done, call_starts


def _wait_for(store: ChannelHealthStore, model_id: str, timeout: float = 4.0) -> None:
    """等待落选 daemon 线程的健康记账落地（事件化轮询，不裸比时间）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if model_id in store.ema_latencies():
            return
        time.sleep(0.05)
    pytest.fail(f"落选线程 {model_id} 的健康记账超时未落地")


def test_hedge_slow_first_fast_second_wins(health_on) -> None:
    store = channel_health_module._GLOBAL_STORE
    router, started, _done, call_starts = _hedge_router(
        {"slow": (1.0, True), "fast": (0.02, True)}, hedge_delay=0.3
    )
    began = time.monotonic()
    reply = router.generate([{"role": "user", "content": "hi"}])
    elapsed = time.monotonic() - began

    assert reply.text == "ok:fast"  # 先到先得
    assert elapsed < 0.9  # 总耗时≈hedge_delay+fast，不等慢者
    assert started["slow"].is_set() and started["fast"].is_set()
    slow_start = next(t for mid, t in call_starts if mid == "slow")
    fast_start = next(t for mid, t in call_starts if mid == "fast")
    assert fast_start - slow_start >= 0.15  # 次候选在 hedge_delay 后才发起
    assert "hedged:fast:winner" in router.last_attempts
    assert "hedged:slow:loser" in router.last_attempts
    # winner 记账即时；慢者被弃但最终也记账（数据不浪费）。
    assert "fast" in store.ema_latencies()
    _wait_for(store, "slow")
    assert "slow" in store.ema_latencies()


def test_hedge_first_fails_fast_switches_immediately(health_on) -> None:
    """① 提前失败：不等 hedge_delay（30s）立即转移次候选。"""
    router, _started, _done, _calls = _hedge_router(
        {"first": (0.03, "timeout"), "second": (0.05, True)}, hedge_delay=30.0
    )
    began = time.monotonic()
    reply = router.generate([{"role": "user", "content": "hi"}])
    assert time.monotonic() - began < 5.0  # 真串行等 delay 会是 30s+
    assert reply.text == "ok:second"
    assert router.last_attempts == ["hedged:second:winner", "hedged:first:loser"]


def test_hedge_all_shadow_fail_falls_back_to_normal_failover(health_on) -> None:
    router, _started, _done, call_starts = _hedge_router(
        {
            "s1": (0.02, "timeout"),
            "s2": (0.02, "rate_limited"),
            "s3": (0.02, True),
        },
        hedge_delay=0.3,
    )
    reply = router.generate([{"role": "user", "content": "hi"}])
    assert reply.text == "ok:s3"  # 影子全败 → 沿候选列表正常转移
    assert "hedged:s1:loser" in router.last_attempts
    assert "hedged:s2:loser" in router.last_attempts
    assert "s3:success" in router.last_attempts
    assert [mid for mid, _t in call_starts] == ["s1", "s2", "s3"]


def test_hedge_disabled_runs_serial(health_on) -> None:
    router, _started, _done, call_starts = _hedge_router(
        {"first": (0.25, "timeout"), "second": (0.25, True)},
        enabled=False,
        hedge_delay=0.3,
    )
    began = time.monotonic()
    reply = router.generate([{"role": "user", "content": "hi"}])
    elapsed = time.monotonic() - began
    assert reply.text == "ok:second"
    assert elapsed >= 0.45  # 串行和（0.25+0.25），无并发
    assert [mid for mid, _t in call_starts] == ["first", "second"]
    assert router.last_attempts == ["first:timeout", "second:success"]  # 无 hedged 记号


def test_hedge_skipped_for_fast_mode(health_on) -> None:
    router, _started, _done, call_starts = _hedge_router(
        {"first": (0.25, "timeout"), "second": (0.25, True)}, hedge_delay=0.3
    )
    began = time.monotonic()
    reply = router.generate(
        [{"role": "user", "content": "hi"}], fast_mode=True
    )
    assert time.monotonic() - began >= 0.45  # fast_mode 串行，不影子
    assert reply.text == "ok:second"
    assert [mid for mid, _t in call_starts] == ["first", "second"]
    assert all(not mark.startswith("hedged:") for mark in router.last_attempts)


def test_hedge_respects_failover_budget(health_on) -> None:
    """整体 failover deadline 在影子路径同样生效：不烧满慢者超时。"""
    router, _started, _done, _calls = _hedge_router(
        {"slow1": (2.0, True), "slow2": (2.0, True)},
        hedge_delay=0.05,
        max_failover_seconds=0.3,
    )
    began = time.monotonic()
    with pytest.raises(LLMProviderError):
        router.generate([{"role": "user", "content": "hi"}])
    assert time.monotonic() - began < 1.5  # 预算 0.3s 生效，不等 2s 慢者
    assert "failover:deadline" in router.last_attempts


def test_hedge_single_candidate_stays_serial(health_on) -> None:
    """候选 <2 不影子：单候选直接走原路径。"""
    router, _started, _done, _calls = _hedge_router({"solo": (0.02, True)})
    reply = router.generate([{"role": "user", "content": "hi"}])
    assert reply.text == "ok:solo"
    assert router.last_attempts == ["solo:success"]


# ==================== 5. env 镜像条目不遮蔽 .env（追加需求） ====================

def _fresh_base_specs() -> dict[str, ModelSpec]:
    return {
        "env-a": ModelSpec(
            model_id="env-a",
            model="gemini-fresh",
            base_url="https://fresh.example/v1",
            api_key="sk-fresh-plain",
            api_keys=("sk-fresh-plain",),
            tags=("fast",),
            priority=5,
        ),
        "env-b": ModelSpec(
            model_id="env-b",
            model="glm-fresh",
            base_url="https://fresh.example/v1",
            api_key="sk-b",
            api_keys=("sk-b",),
            tags=("strong",),
            priority=6,
        ),
    }


def test_mirror_entry_does_not_shadow_env_content() -> None:
    """改 .env 侧 model 后，runtime 旧镜像条目不遮蔽新鲜内容字段。"""
    dynamic = {
        "env-a": {
            "model": "gemini-STALE",
            "base_url": "http://stale.example/v1",
            "api_key": "sk-stale",
            "priority": 1,
            "source": "env",
        }
    }
    router = _router(
        list(_fresh_base_specs().values()),
        lambda spec: None,
        dynamic_registry=lambda: dynamic,
    )
    router._refresh_dynamic_registry()
    spec = router.specs["env-a"]
    assert spec.model == "gemini-fresh"  # 内容以 .env 为新鲜值
    assert spec.base_url == "https://fresh.example/v1"
    assert spec.api_key == "sk-fresh-plain"
    # runtime 侧 priority 仍然生效（合并后重稠密化，比较相对序）：
    # env-a 镜像 priority=1 → 排到 env-b（priority=2 稠密化后）之前。
    assert spec.priority < router.specs["env-b"].priority


def test_mirror_entry_respects_admin_override_fields() -> None:
    dynamic = {
        "env-a": {
            "model": "gemini-STALE",
            "base_url": "http://admin.example/v1",
            "api_key": "sk-stale",
            "priority": 2,
            "source": "env",
            "override_fields": ["base_url"],  # 管理员明确改过的字段以 runtime 为准
        },
        # env-b 镜像 priority=1：为相对序断言提供参照（env-a 被管理员移到第 2 位）。
        "env-b": {
            "model": "glm-STALE",
            "base_url": "http://stale.example/v1",
            "priority": 1,
            "source": "env",
        },
    }
    router = _router(
        list(_fresh_base_specs().values()),
        lambda spec: None,
        dynamic_registry=lambda: dynamic,
    )
    router._refresh_dynamic_registry()
    spec = router.specs["env-a"]
    assert spec.base_url == "http://admin.example/v1"  # override 生效
    assert spec.model == "gemini-fresh"  # 其余内容仍以 .env 为准
    # runtime priority=2 → 稠密化后排到 env-b 之后。
    assert spec.priority > router.specs["env-b"].priority


def test_mirror_entry_of_removed_env_id_is_dropped() -> None:
    dynamic = {
        "gone": {"model": "x", "base_url": "http://x/v1", "source": "env", "priority": 1},
        "env-a": {
            "model": "gemini-STALE",
            "base_url": "http://stale.example/v1",
            "priority": 1,
            "source": "env",
        },
    }
    router = _router(
        list(_fresh_base_specs().values()),
        lambda spec: None,
        dynamic_registry=lambda: dynamic,
    )
    router._refresh_dynamic_registry()
    assert "gone" not in router.specs  # .env 已删除 → 旧镜像不复活
    assert "env-a" in router.specs


def test_pure_runtime_entry_still_overrides_wholly() -> None:
    dynamic = {
        "custom": {
            "model": "custom-model",
            "base_url": "http://custom.example/v1",
            "api_key": "sk-custom",
            "priority": 1,
        }
    }
    router = _router(
        list(_fresh_base_specs().values()),
        lambda spec: None,
        dynamic_registry=lambda: dynamic,
    )
    router._refresh_dynamic_registry()
    spec = router.specs["custom"]
    assert spec.model == "custom-model"  # 管理员 add 的自定义模型整体生效
    assert spec.api_key == "sk-custom"


# ==================== 6. 巡检报告慢渠道评级 ====================

def test_health_report_marks_slow_by_ema() -> None:
    from plugins.bot_unified_runtime.domains.ops.admin.runtime_admin import (
        _format_channel_health_report,
    )

    report = [
        {
            "model_id": "slow-ish",
            "state": "ok",
            "consecutive_fails": 0,
            "latency_ms": 4000,  # 最近一次看着「快」
            "ema_ms": 16000,  # 平滑值超阈 → 偏慢
            "samples": 5,
            "last_error": "",
            "last_ok_at": "",
        },
        {
            "model_id": "quick",
            "state": "ok",
            "consecutive_fails": 0,
            "latency_ms": 3000,
            "ema_ms": 2800,
            "samples": 3,
            "last_error": "",
            "last_ok_at": "",
        },
    ]
    text = _format_channel_health_report(report, slow_ema_ms=15000)
    assert "平滑 16000ms" in text
    assert "响应 4000ms" in text
    slow_line = next(line for line in text.splitlines() if "slow-ish" in line)
    quick_line = next(line for line in text.splitlines() if "quick" in line)
    assert "偏慢" in slow_line  # ema 超阈改标偏慢（覆盖最近一次的「快」）
    assert "快" in quick_line
    # 排序按平滑值：quick（2800）在前。
    assert text.index("quick") < text.index("slow-ish")


def test_health_report_grade_uses_ema_for_normal_band() -> None:
    from plugins.bot_unified_runtime.domains.ops.admin.runtime_admin import (
        _format_channel_health_report,
    )

    report = [
        {
            "model_id": "spiky",
            "state": "ok",
            "consecutive_fails": 0,
            "latency_ms": 800,  # 最近一次很快
            "ema_ms": 9000,  # 平滑值落在「正常」档
            "samples": 9,
            "last_error": "",
            "last_ok_at": "",
        },
    ]
    text = _format_channel_health_report(report, slow_ema_ms=15000)
    line = next(line for line in text.splitlines() if "spiky" in line)
    assert "正常" in line  # 评级用 ema（9000 → 正常），不是最近一次（快）
    assert "平滑 9000ms" in text


# ==================== 7. 延迟无用功删除波（2026-10-12）：逐字段对照 + 形状锁 ====================
#
# 背景（本席现算复核，300 样本 P50，只读探针 %TEMP%/cb-lat/probe_legs.py）：
#   ① get_channel_health_store() 每次全重算 resolve_default_db_path()：1583µs/次，
#      每消息 ≥4 次（判域/贴纸/路由过滤/健康记账）——重算结果只用来打一句
#      永远不会打的 warning；
#   ② filter_healthy_candidates 逐候选现连：40 候选 22255µs、83 候选 40476µs
#      （其中 sqlite3.connect 单次开连 142µs）；
#   ③ is_available 一条 8 列 _row 之后再补一条 SELECT last_probe_at：两趟；
#   ④ ema_latencies 332µs / cooling_ids 427µs / record_success 现连 10090µs。
# 本波只删**往返**：判据真身收敂成一枚 _decide_available，连接收成 queue 同形状的
# 一条常驻连接。任何超时天花板都不在改动面内（天花板锁在
# tests/test_chat_timeout_floor.py::test_channel_health_refactor_kept_every_timeout_ceiling）。
#
# 对照写法照本仓既有做法：改前形状（逐枚 is_available，各走自己的 PK 直查）与改后
# 形状（availability_map 一条批查询）跑在**同一个 store 对象**上——同一份行状态，
# 逐字段才可比（同 debug_id 之类要比就必须同源的道理）。

_AVAIL_IDS = [
    "absent-from-table",
    "ok-row",
    "unavail-empty-probe",
    "unavail-null-probe",
    "unavail-old-probe",
    "unavail-recent-probe",
    "unavail-mid-window-probe",
    "unavail-unparseable-probe",
]

#: 「这一路现在能不能走」的语义**独立陈述**（不读实现、不查库）。
#: 判据语义被动一下（例如 age 比较方向反了、放行条件丢了）这条腿必红。
_AVAIL_EXPECTED = {
    "absent-from-table": True,  # 行缺席 → 放行
    "ok-row": True,  # state != temporarily_unavailable → 放行
    "unavail-empty-probe": True,  # last_probe_at = '' → 放行
    "unavail-null-probe": True,  # last_probe_at = NULL → 放行
    "unavail-old-probe": True,  # 3600s ≥ 重探间隔 1800s → 到点放行一次
    "unavail-recent-probe": False,  # 5s < 1800s → 拦
    "unavail-mid-window-probe": False,  # 1200s < 1800s → 贴窗内仍拦
    "unavail-unparseable-probe": True,  # fromisoformat ValueError → 放行
}


def _ago(seconds: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat(
        timespec="seconds"
    )


def _availability_store(tmp_path) -> ChannelHealthStore:
    """覆盖全部判定分支的库（两条腿共用**这一个** store 对象）。

    行先用公开口 record_success / record_failure 造出来（state 走真身路径），
    再把 last_probe_at 钉成判定要的时刻——写走 store 自己的常驻连接，
    免「另一条连接写过、常驻连接读不到」这种基线混淆。
    """
    store = ChannelHealthStore(tmp_path / "avail-parity.sqlite3")
    store.record_success("ok-row", 300)
    for model_id in (
        "unavail-empty-probe",
        "unavail-null-probe",
        "unavail-old-probe",
        "unavail-recent-probe",
        "unavail-mid-window-probe",
        "unavail-unparseable-probe",
    ):
        store.record_failure(model_id, "kind=timeout")
        store.record_failure(model_id, "kind=timeout")
    probes = {
        "unavail-empty-probe": "",
        "unavail-null-probe": None,
        "unavail-old-probe": _ago(3600),
        "unavail-recent-probe": _ago(5),
        "unavail-mid-window-probe": _ago(1200),
        "unavail-unparseable-probe": "not-a-timestamp",
    }
    with store._lock:  # 在册测试样式（本仓 affinity 系件同法直取私有件）
        con = store._shared_connection()
        for model_id, raw in probes.items():
            con.execute(
                "UPDATE channel_health SET last_probe_at = ? WHERE model_id = ?",
                (raw, model_id),
            )
        con.commit()
    return store


def test_batch_leg_equals_per_candidate_leg_field_by_field(tmp_path) -> None:
    """改后批查询腿 == 改前单候选腿 == 语义独立陈述（三者逐字段同值）。"""
    store = _availability_store(tmp_path)
    per_candidate = {mid: store.is_available(mid) for mid in _AVAIL_IDS}
    batch = store.availability_map(_AVAIL_IDS)
    assert batch == per_candidate, "批查询腿与单候选腿逐字段不等 ⇒ 判据被分了家"
    assert batch == _AVAIL_EXPECTED, "两条腿一起偏离独立陈述 ⇒ 判据语义被动过"
    # 候选顺序无关、重复 id 不改变结果（旧形状按枚判，同样与顺序无关）。
    assert store.availability_map(list(reversed(_AVAIL_IDS))) == _AVAIL_EXPECTED
    assert store.availability_map([*_AVAIL_IDS, "unavail-recent-probe"]) == _AVAIL_EXPECTED

    ids = [*_AVAIL_IDS, "unavail-recent-probe"]  # 含重复，钉住队列形状
    legacy_line = [mid for mid in ids if store.is_available(mid)] or ids  # 改前那一行原样
    assert filter_healthy_candidates(ids, store) == legacy_line
    assert "unavail-recent-probe" not in filter_healthy_candidates(ids, store)
    # 全军覆没仍放行原列表（防全瘫语义没被批查询改动）。
    assert filter_healthy_candidates(["unavail-recent-probe"], store) == ["unavail-recent-probe"]


def test_naive_probe_timestamp_raises_on_both_legs_alike(tmp_path) -> None:
    """naive 时间戳两腿都抛 TypeError（改前也不接，只 except ValueError）。

    这条不是多余：补个 except Exception 「顺手」就能把它变成放行，那是第二套判据。
    旧实现抛到路由侧 _health_filter_candidates 的 except Exception，收敛成原列表放行。
    """
    store = _availability_store(tmp_path)
    with store._lock:
        store._shared_connection().execute(
            "UPDATE channel_health SET last_probe_at = ? WHERE model_id = ?",
            ("2026-01-01T00:00:00", "unavail-recent-probe"),
        )
        store._shared_connection().commit()
    with pytest.raises(TypeError):
        store.is_available("unavail-recent-probe")
    with pytest.raises(TypeError):
        store.availability_map(["unavail-recent-probe"])


def test_cooling_ids_expected_set_field_by_field(tmp_path) -> None:
    """冷却判定的**独立陈述**：方向被动一下（until > now 写成 until < now）必红。"""
    store = ChannelHealthStore(tmp_path / "cooling-parity.sqlite3")
    store.record_success("never-cooled", 100)
    store.record_failure("cooling-future", "kind=timeout", cooldown_seconds=3600.0)
    with store._lock:  # 在册测试样式：直取私有件钉判定输入
        con = store._shared_connection()
        for model_id, raw in (
            ("cooling-explicit-past", _ago(3600)),  # 真·已过期（旧形状里靠方向判定排除）
            ("cooling-empty", ""),
            ("cooling-null", None),
            ("cooling-junk", "not-a-timestamp"),
            (
                "cooling-naive-future",
                (datetime.now(timezone.utc) + timedelta(seconds=3600))
                .replace(tzinfo=None)
                .isoformat(),
            ),
        ):
            con.execute(
                "INSERT INTO channel_health (model_id, state, consecutive_fails, cooldown_until)"
                " VALUES (?, 'ok', 0, ?)",
                (model_id, raw),
            )
        con.commit()
    # 期望集独立写死：只有「未来」的两枚在冷却（naive 形态按 UTC 读＝既有语义，
    # 与 is_available 那条不接 naive 的腿**故意不同**，两处判据本来就不同）。
    assert store.cooling_ids() == {"cooling-future", "cooling-naive-future"}
    # EWMA 与冷却的既有语义逐字段钉住（本波没碰数学与写侧判据，只删往返）。
    store.record_success("ewma-parity", 1000)
    store.record_failure("ewma-parity", "kind=timeout", cooldown_seconds=60.0)
    assert store.snapshot("ewma-parity")["ema_ms"] == 1000  # 失败不动平滑值
    assert store.snapshot("ewma-parity")["samples"] == 1
    assert "ewma-parity" in store.cooling_ids()  # 60s 冷却确实写进去了
    store.record_success("ewma-parity", 2000)
    assert store.snapshot("ewma-parity")["ema_ms"] == 1300  # round(0.3*2000+0.7*1000)
    assert store.snapshot("ewma-parity")["samples"] == 2
    assert store.ema_latencies()["ewma-parity"] == 1300
    assert "ewma-parity" not in store.cooling_ids()  # 成功清冷却（既有语义）


class _CountingSqlite:
    """替掉 channel_health 模块里的 sqlite3 名字，只数 connect（其余属性透传）。"""

    def __init__(self) -> None:
        self.connects = 0

    def connect(self, *args: object, **kwargs: object) -> sqlite3.Connection:
        self.connects += 1
        return sqlite3.connect(*args, **kwargs)  # type: ignore[arg-type]

    def __getattr__(self, name: str) -> object:
        return getattr(sqlite3, name)


def test_health_legs_never_open_a_connection_per_candidate(tmp_path, monkeypatch) -> None:
    """形状锁①（运行期计数）：批查询腿与单候选腿的 connect 次数必须为 0。

    钉的坏形＝「每候选一次 sqlite3.connect」（实测 40 候选 22.3ms 的真凶）。
    预热后 store 的常驻连接已在，任何业务调用再开连＝坏形回来了。
    """
    store = _availability_store(tmp_path)
    ids = [*_AVAIL_IDS, *[f"ch-{i}" for i in range(40)]]
    store.availability_map(ids)  # 预热：让常驻连接先建好

    counter = _CountingSqlite()
    monkeypatch.setattr(channel_health_module, "sqlite3", counter)
    channel_health_module.filter_healthy_candidates(ids, store)
    assert counter.connects == 0, f"批查询腿现连 {counter.connects} 次：每候选一次 sqlite3.connect 回来了"
    for model_id in ids:
        store.is_available(model_id)
    assert counter.connects == 0, f"单候选腿现连 {counter.connects} 次"
    store.ema_latencies()
    store.cooling_ids()
    store.latencies()
    store.unavailable_ids()
    store.report()
    store.snapshot("ok-row")
    store.record_success("ch-0", 500)
    store.record_failure("ch-1", "kind=timeout", cooldown_seconds=30.0)
    assert counter.connects == 0, (
        f"健康记账腿现连 {counter.connects} 次：读侧全收敂到常驻连接，写侧同理"
    )


def test_store_opens_at_most_one_connection_for_its_whole_life(tmp_path, monkeypatch) -> None:
    """形状锁②（生命周期上界）：一枚 store 从头到尾 connect 次数 ≤ 1（queue 同形）。"""
    counter = _CountingSqlite()
    monkeypatch.setattr(channel_health_module, "sqlite3", counter)
    store = ChannelHealthStore(tmp_path / "one-conn.sqlite3")
    ids = [f"ch-{i}" for i in range(40)]
    for _ in range(3):
        channel_health_module.filter_healthy_candidates(ids, store)
        store.record_success("ch-0", 400)
        store.ema_latencies()
        store.cooling_ids()
        store.snapshot("ch-0")
    assert counter.connects == 1, (
        f"store 生命周期内 connect 了 {counter.connects} 次（应为 1：_init_schema 那次）"
        "——>1 说明有腿回到现连，==0 说明常驻连接被谁提前建过"
    )


class _CountingStore:
    """鸭子类型 store：数 filter 这一波到底调了哪条腿、各调了几次。"""

    def __init__(self, store: ChannelHealthStore) -> None:
        self._store = store
        self.is_available_calls: list[str] = []
        self.availability_map_calls = 0

    def is_available(self, model_id: str) -> bool:
        self.is_available_calls.append(model_id)
        return self._store.is_available(model_id)

    def availability_map(self, model_ids: list[str]) -> dict[str, bool]:
        self.availability_map_calls += 1
        return self._store.availability_map(model_ids)


def test_filter_uses_one_batch_query_not_the_per_candidate_leg(tmp_path) -> None:
    """形状锁③（调用计数）：候选队列只走一条批查询，is_available 一次都不许被调。

    「每候选调一次 is_available」正是 ② 那 22.3ms 的形状本身——把它钉成计数判据，
    将来谁「顺手」改回按枚问就当场红。
    """
    store = _availability_store(tmp_path)
    spy = _CountingStore(store)
    ids = [*_AVAIL_IDS, "ch-0", "ch-1"]
    got = filter_healthy_candidates(ids, spy)
    assert spy.availability_map_calls == 1
    assert spy.is_available_calls == [], (
        f"候选队列又按枚走单候选腿了（{len(spy.is_available_calls)} 次）："
        "实测 40 候选现连形状 22.3ms，这条腿只该留给「按枚问一路」的管理面"
    )
    assert got == [mid for mid in ids if _AVAIL_EXPECTED.get(mid, True)]


def _ancestor_chain(tree: ast.AST, target: ast.AST) -> list[ast.AST]:
    parent_of: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent_of[child] = node
    chain: list[ast.AST] = []
    current = parent_of.get(target)
    while current is not None:
        chain.append(current)
        current = parent_of.get(current)
    return chain


def _channel_health_source() -> tuple[str, ast.Module]:
    path = inspect.getsourcefile(channel_health_module)
    assert path, "拿不到 channel_health 源码路径"
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    return source, ast.parse(source)


def test_channel_health_has_single_connection_primitive_outside_any_loop() -> None:
    """形状锁④（AST）：sqlite3.connect 全模块只许一处、住 _connect 里、且只在
    _shared_connection 被调——「另立一套连接管理真身」与「循环里现连」两头一起钉死。
    """
    source, tree = _channel_health_source()

    def is_sqlite_connect(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "connect"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "sqlite3"
        )

    connects = [n for n in ast.walk(tree) if is_sqlite_connect(n)]
    assert len(connects) == 1, (
        f"sqlite3.connect 出现 {len(connects)} 处（应为 1）：连接真身只能有一枚，"
        "第二枚就是 queue.py::_shared_connection 之外另立的连接管理"
    )
    chain = _ancestor_chain(tree, connects[0])
    owners = [n.name for n in chain if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert owners and owners[0] == "_connect", f"建连必须住在 _connect 里，实际在 {owners}"
    assert not any(
        isinstance(n, (ast.For, ast.AsyncFor, ast.comprehension)) for n in chain
    ), "建连落在循环/推导式里＝每候选一条连接那个坏形的 AST 形状"

    primitive_calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "_connect"
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "self"
    ]
    assert primitive_calls, "_connect 这枚原语没被任何地方调用＝它是死码不是真身"
    for call in primitive_calls:
        owners = [
            n.name
            for n in _ancestor_chain(tree, call)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        assert owners and owners[0] == "_shared_connection", (
            f"self._connect() 被 {owners} 直接调了：绕过常驻连接的取用口就是第二套连接管理"
        )

    # 判据真身只剩一枚：重探间隔的 AST 引用只许「定义 1 + 判定 1」（走 AST 而非文本
    # 计数——docstring 里提名字不该把锁吃红）。
    retry_names = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Name) and n.id == "_RETRY_INTERVAL_SECONDS"
    ]
    assert len(retry_names) == 2, (
        f"_RETRY_INTERVAL_SECONDS 在代码里出现 {len(retry_names)} 处（应为定义 1＋判定 1）："
        "第三处＝判据被抄了一份，一处改一处不改就是逐字段不等的成因"
    )
    assert (
        source.count("def _decide_available") == 1
    ), "_decide_available 必须有且只有一枚真身"
    # 候选队列这一条函数体里既不许建连、也不许再按枚走单候选腿——走 AST，
    # 免得日后一句 docstring 提到名字就把锁吃红（文本计数踩过的坑）。
    filter_fn = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "filter_healthy_candidates"
    )
    filter_attrs = [n.attr for n in ast.walk(filter_fn) if isinstance(n, ast.Attribute)]
    assert "is_available" not in filter_attrs, (
        f"候选队列又按枚走单候选腿了（属性引用={filter_attrs}）："
        "每候选一次查询的坏形换了形状回来，实测 40 候选 22.3ms 就是这么来的"
    )
    assert not any(
        is_sqlite_connect(n) for n in ast.walk(filter_fn)
    ), "filter_healthy_candidates 里出现建连＝坏形换了个入口回来"
    assert "availability_map" in filter_attrs, (
        f"候选队列没走批查询腿（属性引用={filter_attrs}）：绕回按枚判＝本波删掉的无用功复活"
    )
