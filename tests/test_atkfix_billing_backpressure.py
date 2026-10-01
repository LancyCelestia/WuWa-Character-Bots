"""S-FIX-BILLING F-3 修复锁：归因「慢而成功」反压账本写吞吐（SEAT-ATK-BILLING.md）。

旧链路三个洞叠成静默丢账：
1. PG 反查同步钉在写线程每批前，**永不抛出** ⇒ 外层 try 永远接不到异常；
2. resolver 熔断只数**连续**异常且一次成功清零 ⇒ 「慢而成功」永不 trip；
3. 吞吐 < 入账速率 ⇒ 队列满丢最旧，丢者只留一行不带身份的日志 ⇒ 无面可看。

修法与锁：
- 写线程让路（弃归因不弃账）：``_attribution_should_yield``（纯决策：积压 ∨
  归因耗时 EWMA 超预算）命中 ⇒ 本批不查、键行标第四态 ``skipped``、
  计数留痕，行照常落库——契约「账本写失败不阻塞回复」的反向半边
  「归因故障不丢账行」在此钉死；让路期 EWMA 衰减 ⇒ 自动回位。
- 熔断加时长维度：异常与 elapsed ≥ timeout×0.8 的慢成功都进 600s 滚动窗，
  攒 3 个坏事件即静默；慢成功 trip **不**置 last_error（否则
  make_batch_lookup 把查成功的批改写成 unavailable＝假事实）。
- 丢行必须留痕且能浮面：queue-full 日志带被丢记录身份三元组，计数经
  ``peek_ledger_service()``（只读、绝不按需建库）投给 ``/bot model usage``
  的账本健康行。

全部离线：假时钟（monkeypatch 模块级 ``time``），不起线程（_stub_writer），
不连网不连库。
"""

from __future__ import annotations

import logging
import sqlite3
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import plugins.bot_unified_runtime.domains.chat_reply.llm_engine.ledger as ledger_module
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine import (
    axonhub_attribution,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.axonhub_attribution import (
    AttributionResolver,
    make_batch_lookup,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.ledger import (
    ATTRIBUTION_MISS,
    ATTRIBUTION_SKIPPED,
    ATTRIBUTION_UNAVAILABLE,
    LedgerService,
    LLMCallDraft,
    build_call_draft,
    peek_ledger_service,
)


@pytest.fixture(autouse=True)
def _clean_billing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BOT_LLM_BILLING_ENABLED", raising=False)


def _stub_writer() -> threading.Thread:
    return threading.Thread(target=lambda: None)


def _fetch_row(db_path: str) -> sqlite3.Row:
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        return con.execute("SELECT * FROM llm_call_records").fetchone()


def _keyed_draft(request_id: str = "req-k", remote: str = "wid-1") -> LLMCallDraft:
    return build_call_draft(
        request_id=request_id,
        started_at="2026-09-28T10:00:00.000+08:00",
        completed_at="2026-09-28T10:00:01.000+08:00",
        model_id="axon-gemini-38-flash",
        actual_model="gemini-3.8-flash",
        usage={"prompt_tokens": 3, "completion_tokens": 66, "total_tokens": 69},
        attempts=["axon-gemini-38-flash:success"],
        status="success",
        remote_request_id=remote,
    )


class _Clock:
    """假时钟：只在测试显式推进时走表——慢查询的时长是注入的，不是睡出来的。"""

    def __init__(self) -> None:
        self.t = 10_000.0

    def monotonic(self) -> float:
        return self.t

    def namespace(self) -> SimpleNamespace:
        return SimpleNamespace(monotonic=self.monotonic)


# ==================== 让路决策（纯函数面） ====================


def test_should_yield_pure_decision() -> None:
    service = LedgerService(
        ":memory:", writer_thread=_stub_writer(), flush_batch_size=50,
        flush_interval_seconds=2.0,
    )
    try:
        # 积压判据：队列里攒满一整批 ⇒ 先保吞吐。
        assert service._attribution_should_yield(50) is True
        assert service._attribution_should_yield(49) is False
        # 时长判据：EWMA 到预算 ⇒ 让路；预算 0 ⇒ 该臂整体关闭。
        service._attribution_ewma_seconds = 2.0  # 预算 = flush_interval × 1.0
        assert service._attribution_should_yield(0) is True
        service._attribution_ewma_seconds = 1.99
        assert service._attribution_should_yield(0) is False
        service.attribution_budget_seconds = 0.0
        service._attribution_ewma_seconds = 9_999.0
        assert service._attribution_should_yield(0) is False
    finally:
        service.close()


# ==================== 让路执行面（写线程） ====================


def test_yield_writes_rows_marks_skipped_and_never_calls_lookup(tmp_path) -> None:
    """弃归因不弃账：让路批必须**照常落库**、状态第四态、计数与留痕齐。"""
    calls: list[list[str]] = []

    def lookup(ids):
        calls.append(list(ids))
        return {}

    service = LedgerService(
        str(tmp_path / "ledger.sqlite3"),
        writer_thread=_stub_writer(),
        flush_interval_seconds=0.05,  # 预算 = 0.05s
        attribution_lookup=lookup,
    )
    service._attribution_ewma_seconds = 10.0  # 超预算 ⇒ 让路
    service.submit(_keyed_draft())
    assert service.flush() == 1, "让路批一行都不许少"
    assert calls == [], "让路批绝不发反查"
    row = _fetch_row(service.db_path)
    assert row["attribution_status"] == ATTRIBUTION_SKIPPED
    assert row["attribution_status"] not in (
        ATTRIBUTION_UNAVAILABLE, ATTRIBUTION_MISS
    ), "「没去查」≠「查不了」≠「查了没有」，第四态不许混写"
    assert service.attribution_skipped_count == 1
    assert service._attribution_ewma_seconds == pytest.approx(5.0), (
        "让路期 EWMA 指数衰减（0.5），否则一次慢查询永久钉死归因"
    )
    service.close()


def test_measured_slow_lookup_feeds_ewma_and_recovery(tmp_path, monkeypatch) -> None:
    """EWMA 由实测反查时长喂入：慢→让路→衰减→回位，全链自动，无人工复位。"""
    clock = _Clock()
    monkeypatch.setattr(ledger_module, "time", clock.namespace())
    calls: list[list[str]] = []

    def slow_lookup(ids):
        calls.append(list(ids))
        clock.t += 5.0  # 每次反查真实耗时 5s（假时钟注入）
        return {}

    service = LedgerService(
        str(tmp_path / "ledger.sqlite3"),
        writer_thread=_stub_writer(),
        attribution_lookup=slow_lookup,
        attribution_budget_seconds=1.0,
    )
    # 第 1 批：ewma 0 < 预算 ⇒ 查。查完 ewma = 0×0.5 + 5×0.5 = 2.5 ≥ 预算。
    service.submit(_keyed_draft("r1", "w1"))
    service.flush()
    assert len(calls) == 1
    assert service._attribution_ewma_seconds == pytest.approx(2.5)
    # 第 2 批：ewma 超预算 ⇒ 让路（不查、衰减到 1.25，仍超）。
    service.submit(_keyed_draft("r2", "w2"))
    service.flush()
    assert len(calls) == 1, "超预算批不得再查"
    assert service._attribution_ewma_seconds == pytest.approx(1.25)
    # 第 3 批：仍超 ⇒ 再让路，衰减到 0.625 < 预算。
    service.submit(_keyed_draft("r3", "w3"))
    service.flush()
    assert service.attribution_skipped_count == 2
    # 第 4 批：回到预算内 ⇒ 归因自动回位，重新开查。
    service.submit(_keyed_draft("r4", "w4"))
    service.flush()
    assert len(calls) == 2, "EWMA 衰减回预算内必须自动恢复归因"
    # 四批全落库，一行不丢。
    with sqlite3.connect(service.db_path) as con:
        assert con.execute("SELECT COUNT(*) FROM llm_call_records").fetchone()[0] == 4
    service.close()


def test_no_key_no_lookup_unaffected(tmp_path) -> None:
    """无关联键的批完全不进让路判定（行为与未启用归因逐字节一致）。"""
    calls: list[list[str]] = []

    def lookup(ids):
        calls.append(list(ids))
        return {}

    service = LedgerService(
        str(tmp_path / "ledger.sqlite3"),
        writer_thread=_stub_writer(),
        flush_interval_seconds=0.05,
        attribution_lookup=lookup,
    )
    service._attribution_ewma_seconds = 99.0
    draft = _keyed_draft(remote="")  # 无键
    service.submit(draft)
    assert service.flush() == 1
    assert calls == []
    assert service.attribution_skipped_count == 0
    assert _fetch_row(service.db_path)["attribution_status"] == ""
    service.close()


# ==================== 丢行留痕与告警面 ====================


def test_queue_full_drop_logs_identity_and_counts(tmp_path, caplog) -> None:
    service = LedgerService(
        str(tmp_path / "ledger.sqlite3"),
        writer_thread=_stub_writer(),
        max_pending=1,
    )
    try:
        with caplog.at_level(
            logging.WARNING,
            logger="plugins.bot_unified_runtime.domains.chat_reply.llm_engine.ledger",
        ):
            service.submit(_keyed_draft("req-old", "w-old"))
            service.submit(_keyed_draft("req-new", "w-new"))
        assert service.dropped_count == 1
        message = "\n".join(r.getMessage() for r in caplog.records)
        # 丢的是哪一发，日志里必须点名到可以归因的身份三元组。
        assert "req-old" in message
        assert "axon-gemini-38-flash" in message
        assert "2026-09-28T10:00:01.000+08:00" in message
        assert "total dropped=1" in message
    finally:
        service.close()


def test_peek_never_constructs(monkeypatch) -> None:
    """健康面只准探测：peek 不得按需建库/起写线程（读数不是写数）。"""
    monkeypatch.setattr(ledger_module, "_GLOBAL_SERVICE", None)
    assert peek_ledger_service() is None
    sentinel = object()
    monkeypatch.setattr(ledger_module, "_GLOBAL_SERVICE", sentinel)
    assert peek_ledger_service() is sentinel


def test_usage_surface_shows_ledger_health(tmp_path, monkeypatch) -> None:
    """告警面第一消费者：计数非零 ⇒ /bot model usage 尾行浮出健康摘要。"""
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
        RuntimeSettingsStore,
    )
    from plugins.bot_unified_runtime.domains.ops.admin.runtime_admin import (
        _handle_model_command,
    )

    db_path = str(tmp_path / "ledger.sqlite3")
    LedgerService(db_path, writer_thread=_stub_writer()).close()  # 建空库
    monkeypatch.setattr(
        ledger_module, "resolve_default_db_path", lambda: db_path
    )
    monkeypatch.setattr(
        ledger_module,
        "_GLOBAL_SERVICE",
        SimpleNamespace(
            dropped_count=2,
            write_error_count=1,
            attribution_error_count=3,
            attribution_skipped_count=4,
        ),
    )

    def _temp_dir() -> Path:
        return Path(tempfile.mkdtemp(prefix="atkfix-bp-"))

    store = RuntimeSettingsStore(_temp_dir() / "settings.json", allow_no_gate=True)
    config = SimpleNamespace(
        bot_llm_billing_enabled=True,
        bot_model_registry={},
        bot_model_presets={},
        bot_chat_model="main",
        bot_model_auto_route=True,
        bot_model_priority_groups=[],
        bot_model_prices={},
    )
    usage_store = SimpleNamespace(
        aggregate_llm_usage_range=lambda start, end: {
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            "cache_read_tokens": 0, "cache_write_tokens": 0,
            "cost_milli": 0, "calls": 0, "by_model": {}, "unpriced_calls": 0,
        }
    )
    result = _handle_model_command(
        store, config, ["usage", "2026-09-28"], usage_store=usage_store
    )
    assert "账本健康：丢行 2，写失败 1，归因故障 3，归因让路 4" in result


def test_usage_surface_silent_when_health_zero(tmp_path, monkeypatch) -> None:
    """计数全零（健康态）⇒ 不加噪声行——告警面只在有事时出声。"""
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
        RuntimeSettingsStore,
    )
    from plugins.bot_unified_runtime.domains.ops.admin.runtime_admin import (
        _handle_model_command,
    )

    db_path = str(tmp_path / "ledger.sqlite3")
    LedgerService(db_path, writer_thread=_stub_writer()).close()
    monkeypatch.setattr(ledger_module, "resolve_default_db_path", lambda: db_path)
    monkeypatch.setattr(
        ledger_module,
        "_GLOBAL_SERVICE",
        SimpleNamespace(
            dropped_count=0,
            write_error_count=0,
            attribution_error_count=0,
            attribution_skipped_count=0,
        ),
    )

    def _temp_dir() -> Path:
        return Path(tempfile.mkdtemp(prefix="atkfix-bp-"))

    store = RuntimeSettingsStore(_temp_dir() / "settings.json", allow_no_gate=True)
    config = SimpleNamespace(
        bot_llm_billing_enabled=True,
        bot_model_registry={},
        bot_model_presets={},
        bot_chat_model="main",
        bot_model_auto_route=True,
        bot_model_priority_groups=[],
        bot_model_prices={},
    )
    usage_store = SimpleNamespace(
        aggregate_llm_usage_range=lambda start, end: {
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            "cache_read_tokens": 0, "cache_write_tokens": 0,
            "cost_milli": 0, "calls": 0, "by_model": {}, "unpriced_calls": 0,
        }
    )
    result = _handle_model_command(
        store, config, ["usage", "2026-09-28"], usage_store=usage_store
    )
    assert "账本健康" not in result


# ==================== resolver 熔断：时长维度 ====================


def _make_resolver(fetch, timeout: float) -> AttributionResolver:
    return AttributionResolver(
        dsn={"host": "h"}, timeout_seconds=timeout, fetch=fetch
    )


def test_breaker_trips_on_alternating_failures(tmp_path, monkeypatch) -> None:
    """旧洞：一次成功清零 ⇒ fail/success/fail/success/fail 永不 trip。

    滚动窗后 3 个坏事件（异常）在 600s 内即可 trip，成功不冲抵在案故障。
    """
    clock = _Clock()
    monkeypatch.setattr(axonhub_attribution, "time", clock.namespace())
    boom = SimpleNamespace(n=0)

    def flaky(ids):
        boom.n += 1
        if boom.n % 2 == 1:
            raise RuntimeError("pg down")
        return []

    resolver = _make_resolver(flaky, timeout=1.0)
    assert resolver.lookup(["a"]) == {}  # fail 1
    assert resolver.lookup(["a"]) == {}  # success（不该清零）
    assert resolver.lookup(["a"]) == {}  # fail 2
    assert resolver.lookup(["a"]) == {}  # success
    resolver.last_error = ""
    assert resolver.lookup(["a"]) == {}  # fail 3 ⇒ trip
    assert resolver._circuit_open_until > clock.t
    calls_before = boom.n
    assert resolver.lookup(["a"]) == {}
    assert resolver.last_error == "circuit_open", "静默期内不再撞库"
    assert boom.n == calls_before, "trip 后绝不发真查询"


def test_breaker_trips_on_slow_successes_without_swallowing_data(
    monkeypatch,
) -> None:
    """「慢而成功」进熔断窗，但成功批的数据一个字段都不能被改坏。"""
    clock = _Clock()
    monkeypatch.setattr(axonhub_attribution, "time", clock.namespace())
    rows = [{"external_id": "w1", "channel_name": "chan-A", "total_cost": 0.001}]

    def slow(ids):
        clock.t += 0.9  # timeout=1.0 ⇒ elapsed 0.9 ≥ 0.8 ⇒ 慢成功事件
        return list(rows)

    resolver = _make_resolver(slow, timeout=1.0)
    found = resolver.lookup(["w1"])
    assert found and found["w1"].gateway_channel == "chan-A", "慢但查到了"
    assert resolver.last_error == "", "慢成功不得置障（否则批被改写成 unavailable）"
    resolver.lookup(["w1"])
    resolver.last_error = ""
    found3 = resolver.lookup(["w1"])  # 第 3 个慢事件 ⇒ trip
    assert found3 and found3["w1"].gateway_channel == "chan-A"
    assert resolver._circuit_open_until > clock.t
    assert resolver.last_error == ""
    # 静默期内 make_batch_lookup 才回 None（真·没查成）。
    batch = make_batch_lookup(resolver)
    assert batch(["w1"]) is None


def test_fast_successes_do_not_accumulate_and_window_prunes(monkeypatch) -> None:
    """快成功零记分；600s 窗外旧故障自然过期——让路/熔断都不许冤枉健康期。"""
    clock = _Clock()
    monkeypatch.setattr(axonhub_attribution, "time", clock.namespace())
    state = SimpleNamespace(raise_next=False, n=0)

    def fetch(ids):
        state.n += 1
        if state.raise_next:
            raise RuntimeError("flaky")
        return []

    resolver = _make_resolver(fetch, timeout=1.0)
    state.raise_next = True
    resolver.lookup(["a"])  # fail 1
    state.raise_next = False
    for _ in range(5):
        resolver.lookup(["a"])  # 快成功：不记分也不冲抵
    assert len(resolver._circuit_events) == 1
    assert resolver._circuit_open_until == 0.0
    clock.t += axonhub_attribution._CIRCUIT_EVENT_WINDOW_SECONDS + 1.0
    state.raise_next = True
    resolver.lookup(["a"])  # 窗外：旧 fail 已过期，现在只有 1 事件
    assert len(resolver._circuit_events) == 1
    assert resolver._circuit_open_until == 0.0, "过期故障不得与新故障凑票"


def test_cooldown_expires_and_lookup_resumes(monkeypatch) -> None:
    clock = _Clock()
    monkeypatch.setattr(axonhub_attribution, "time", clock.namespace())
    state = SimpleNamespace(raise_next=True, n=0)

    def fetch(ids):
        state.n += 1
        if state.raise_next:
            raise RuntimeError("down")
        return []

    resolver = _make_resolver(fetch, timeout=1.0)
    for _ in range(3):
        resolver.lookup(["a"])
    assert resolver._circuit_open_until > clock.t
    opens = state.n
    resolver.lookup(["a"])
    assert state.n == opens  # 静默中
    clock.t += axonhub_attribution._CIRCUIT_COOLDOWN_SECONDS + 1.0
    state.raise_next = False
    resolver.lookup(["a"])
    assert state.n == opens + 1, "冷却期满必须放一次真探测回去"


def test_breaker_keeps_triple_failure_trip_semantics(monkeypatch) -> None:
    """既有裁量保持：3 连异常 trip、单发异常不 trip（与旧口径共同的底线）。"""
    clock = _Clock()
    monkeypatch.setattr(axonhub_attribution, "time", clock.namespace())

    def boom(ids):
        raise RuntimeError("no route")

    resolver = _make_resolver(boom, timeout=0.5)
    resolver.lookup(["a"])
    assert resolver._circuit_open_until == 0.0
    resolver.lookup(["a"])
    assert resolver._circuit_open_until == 0.0
    resolver.lookup(["a"])
    assert resolver._circuit_open_until > clock.t
    # trip 时 last_error 是真异常（fail 与慢成功的留痕方式不同）。
    assert resolver.last_error.startswith("RuntimeError")
