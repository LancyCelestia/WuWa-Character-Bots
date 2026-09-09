"""渠道健康 v2 回归：EWMA 动态测量、老库迁移、ema 路由排序（动态切换）、
慢渠道阈值解析、自适应超时、影子并发（hedged request）无损无感切换、
env 镜像条目不遮蔽 .env（Task4 跨文件 follow-up）。

影子并发用可控假 provider（Event + sleep 控制时序）断言 winner 时序与
记账；时间断言全部留足裕量（事件同步为主、耗时比大小为辅），避免 flaky。
"""

from __future__ import annotations

import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest

import plugins.bot_unified_runtime.llm.channel_health as channel_health_module
from plugins.bot_unified_runtime.llm.channel_health import (
    ChannelHealthStore,
    resolve_slow_ema_ms,
)
from plugins.bot_unified_runtime.llm.model_router import ModelRouter, ModelSpec
from plugins.bot_unified_runtime.llm.providers import LLMProviderError, LLMReply


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
    return _router(
        [_spec("ch-a", 1), _spec("ch-b", 2)],
        lambda spec: TimeoutCaptureProvider(spec.model_id, captured),
        credential_config=credential_config,
    )


@pytest.mark.parametrize(
    ("ema_ms", "expected"),
    [
        (1000, [8.0]),  # max(8, 1*3)=8 < 30 → 收紧到 8s（显式注入 timeout）
        (20000, []),  # max(8, 20*3)=60 > 30 → 收紧结果=原值 → 不注入（v1 语义）
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
    from plugins.bot_unified_runtime.capabilities.runtime_admin import (
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
    from plugins.bot_unified_runtime.capabilities.runtime_admin import (
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
