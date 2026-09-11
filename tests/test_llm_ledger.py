"""B5 M1 计费账本回归：三表 DDL、LedgerService 落库、router 出口记账挂钩。

规格：docs/design/llm-billing-ledger.md（M1 范围）。
- 一行 = 一次 ModelRouter.generate()（成功或最终失败各一行）；
- sink 注入优先；开关（Config 字段缺失 / env 缺失）默认关；
- 计费故障（sink 抛错）绝不阻塞聊天。
"""

from __future__ import annotations

import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest

import plugins.bot_unified_runtime.llm.ledger as ledger_module
from plugins.bot_unified_runtime.llm.ledger import (
    LedgerService,
    LLMCallDraft,
    build_call_draft,
    emit_call_record,
    get_ledger_service,
    ledger_enabled,
    redact_error_summary,
    resolve_call_record_sink,
)
from plugins.bot_unified_runtime.llm.model_router import ModelRouter, ModelSpec
from plugins.bot_unified_runtime.llm.providers import LLMProviderError, LLMReply

EXPECTED_TABLES = {"llm_call_records", "llm_usage_daily", "balance_snapshots"}


@pytest.fixture(autouse=True)
def _clean_billing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """隔离账本开关环境变量：默认态测试不受本机环境污染。"""
    monkeypatch.delenv("BOT_LLM_BILLING_ENABLED", raising=False)


def _stub_writer() -> threading.Thread:
    """未启动的桩线程：LedgerService 不起后台写线程，flush 全同步。"""
    return threading.Thread(target=lambda: None)


def _service(tmp_path, **kwargs: object) -> LedgerService:
    return LedgerService(
        str(tmp_path / "ledger.sqlite3"), writer_thread=_stub_writer(), **kwargs
    )


def _table_names(db_path: str) -> set[str]:
    with sqlite3.connect(db_path) as con:
        rows = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    return {str(row[0]) for row in rows}


def _fetch_row(db_path: str) -> sqlite3.Row:
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        return con.execute("SELECT * FROM llm_call_records").fetchone()


def _wal_mode(db_path: str) -> str:
    with sqlite3.connect(db_path) as con:
        return str(con.execute("PRAGMA journal_mode").fetchone()[0]).lower()


# ==================== DDL ====================


def test_schema_creates_three_tables_idempotent(tmp_path) -> None:
    db_path = str(tmp_path / "ledger.sqlite3")
    service = _service(tmp_path)
    service.flush()
    assert EXPECTED_TABLES <= _table_names(db_path)
    # 二次建表（新实例同库）幂等，不动已有数据。
    service.close()
    second = LedgerService(db_path, writer_thread=_stub_writer())
    second.flush()
    assert EXPECTED_TABLES <= _table_names(db_path)
    second.close()


def test_schema_wal_first(tmp_path) -> None:
    service = _service(tmp_path)
    service.flush()
    assert _wal_mode(service.db_path) == "wal"
    service.close()


# ==================== 落库行口径 ====================


def test_success_draft_roundtrip(tmp_path) -> None:
    service = _service(tmp_path)
    draft = build_call_draft(
        request_id="req-1",
        call_seq=2,
        session_id="group-123",
        capability="bot.chat",
        started_at="2026-09-12T10:00:00.000+08:00",
        completed_at="2026-09-12T10:00:01.200+08:00",
        duration_ms=1200,
        provider_id="ch-a",
        model_id="ch-a",
        actual_model="deepseek-v4-flash",
        effort="low",
        routing_group="qian",
        usage={
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "cache_read_tokens": 30,
            "cache_write_tokens": 5,
            "finish_reason": "stop",
        },
        attempts=["ch-a:success"],
        status="success",
    )
    service.submit(draft)
    assert service.flush() == 1
    row = _fetch_row(service.db_path)
    assert row["request_id"] == "req-1"
    assert row["call_seq"] == 2
    assert row["session_id"] == "group-123"
    assert row["capability"] == "bot.chat"
    assert row["status"] == "success"
    assert row["attempts_json"] == '["ch-a:success"]'
    assert row["attempts_count"] == 1
    assert row["prompt_tokens"] == 100
    assert row["completion_tokens"] == 20
    assert row["total_tokens"] == 120
    assert row["cache_read_tokens"] == 30
    assert row["cache_creation_tokens"] == 5  # cache_write_tokens → creation 列
    assert row["finish_reason"] == "stop"
    # M1 无 PricingService：cost 全 NULL、unpriced 如实标记（未知不是 0）。
    assert row["input_cost_milli"] is None
    assert row["total_cost_milli"] is None
    assert row["pricing_source"] == "unknown"
    assert row["unpriced"] == 1
    assert row["source"] == "router"
    service.close()


def test_unknown_tokens_stay_null_not_zero(tmp_path) -> None:
    service = _service(tmp_path)
    draft = build_call_draft(
        request_id="req-2",
        started_at="2026-09-12T10:00:00.000+08:00",
        completed_at="2026-09-12T10:00:01.000+08:00",
        model_id="ch-a",
        usage={},
        attempts=["ch-a:success"],
        status="success",
    )
    service.submit(draft)
    service.flush()
    row = _fetch_row(service.db_path)
    for column in (
        "prompt_tokens",
        "cache_creation_tokens",
        "cache_read_tokens",
        "completion_tokens",
        "total_tokens",
    ):
        assert row[column] is None, column
    assert row["unpriced"] == 0  # 无 token 消耗就无所谓未计价。
    service.close()


def test_failed_draft_fields(tmp_path) -> None:
    service = _service(tmp_path)
    draft = build_call_draft(
        request_id="req-3",
        started_at="2026-09-12T10:00:00.000+08:00",
        completed_at="2026-09-12T10:00:02.000+08:00",
        duration_ms=2000,
        model_id="ch-a",
        attempts=["ch-a:rate_limited", "failover:deadline"],
        status="deadline",
        error_kind="timeout",
        error_summary="LLM failover budget exhausted before any candidate answered",
    )
    service.submit(draft)
    service.flush()
    row = _fetch_row(service.db_path)
    assert row["status"] == "deadline"
    assert row["error_kind"] == "timeout"
    assert row["prompt_tokens"] is None
    assert row["unpriced"] == 0
    service.close()


def test_error_summary_redacted_and_truncated(tmp_path) -> None:
    redacted = redact_error_summary("boom api_key=supersecret123 at line 1")
    assert "supersecret123" not in redacted
    assert "[redacted]" in redacted
    assert len(redact_error_summary("x" * 999)) <= 200


def test_queue_overflow_drops_oldest(tmp_path) -> None:
    service = _service(tmp_path, max_pending=2)
    for index in range(4):
        service.submit(
            build_call_draft(
                request_id=f"req-{index}",
                started_at="2026-09-12T10:00:00.000+08:00",
                completed_at="2026-09-12T10:00:00.000+08:00",
                model_id="ch-a",
                status="success",
            )
        )
    assert service.dropped_count == 2  # 丢弃最旧两条
    assert service.flush() == 2  # 只落最新两条
    with sqlite3.connect(service.db_path) as con:
        ids = [
            str(row[0])
            for row in con.execute("SELECT request_id FROM llm_call_records ORDER BY id")
        ]
    assert ids == ["req-2", "req-3"]
    service.close()


def test_background_writer_flushes(tmp_path) -> None:
    service = LedgerService(str(tmp_path / "ledger.sqlite3"))  # 真实后台线程
    service.submit(
        build_call_draft(
            request_id="bg-1",
            started_at="2026-09-12T10:00:00.000+08:00",
            completed_at="2026-09-12T10:00:00.000+08:00",
            model_id="ch-a",
            status="success",
        )
    )
    deadline = time.monotonic() + 5.0
    rows = 0
    while time.monotonic() < deadline:
        with sqlite3.connect(service.db_path) as con:
            rows = int(
                con.execute("SELECT COUNT(*) FROM llm_call_records").fetchone()[0]
            )
        if rows >= 1:
            break
        time.sleep(0.05)
    service.close()
    assert rows == 1


# ==================== 开关与 sink 解析 ====================


def test_ledger_enabled_default_off() -> None:
    assert ledger_enabled(None) is False
    assert ledger_enabled(SimpleNamespace()) is False
    assert ledger_enabled(SimpleNamespace(bot_llm_billing_enabled=False)) is False


def test_ledger_enabled_config_then_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert (
        ledger_enabled(SimpleNamespace(bot_llm_billing_enabled=True)) is True
    )  # Config 字段主路径
    monkeypatch.setenv("BOT_LLM_BILLING_ENABLED", "true")
    assert ledger_enabled(SimpleNamespace()) is True  # env 兜底
    monkeypatch.setenv("BOT_LLM_BILLING_ENABLED", "not-a-flag")
    assert ledger_enabled(SimpleNamespace()) is False  # 非法值按默认关


def test_resolve_sink_prefers_injection_even_when_disabled() -> None:
    sink = SimpleNamespace()
    assert resolve_call_record_sink(sink, SimpleNamespace()) is sink


def test_resolve_sink_none_when_disabled() -> None:
    assert resolve_call_record_sink(None, SimpleNamespace()) is None


def test_resolve_sink_global_singleton_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = SimpleNamespace(db_path="stub-path")
    monkeypatch.setattr(ledger_module, "_GLOBAL_SERVICE", stub)
    resolved = resolve_call_record_sink(
        None, SimpleNamespace(bot_llm_billing_enabled=True)
    )
    assert resolved is stub


def test_get_ledger_service_reuses_same_db(tmp_path) -> None:
    stub = SimpleNamespace(db_path=str(tmp_path / "ledger.sqlite3"))
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(ledger_module, "_GLOBAL_SERVICE", stub)
        assert get_ledger_service(str(tmp_path / "ledger.sqlite3")) is stub
    finally:
        monkeypatch.undo()


def test_emit_call_record_swallows_sink_errors() -> None:
    class ExplodingSink:
        def submit(self, draft: LLMCallDraft) -> None:
            raise RuntimeError("ledger down")

    draft = build_call_draft(status="success")
    # 不抛出即通过：计费故障绝不阻塞聊天（§4.1.2）。
    emit_call_record(sink=ExplodingSink(), config=None, draft=draft)


def test_emit_call_record_noop_when_disabled() -> None:
    called: list[LLMCallDraft] = []

    class RecordingSink:
        def submit(self, draft: LLMCallDraft) -> None:
            called.append(draft)

    emit_call_record(
        sink=None, config=SimpleNamespace(), draft=build_call_draft(status="success")
    )
    assert called == []
    emit_call_record(
        sink=RecordingSink(),
        config=SimpleNamespace(),
        draft=build_call_draft(status="success"),
    )
    assert len(called) == 1  # 注入优先，不受开关影响


# ==================== router 出口挂钩 ====================


class _FakeProvider:
    """按渠道注入失败的假 provider；记录收到的 kwargs 以防账本参数泄漏。"""

    def __init__(
        self,
        model_id: str,
        error_kind: str,
        seen_kwargs: list[dict[str, object]],
    ) -> None:
        self.model_id = model_id
        self.error_kind = error_kind
        self.seen_kwargs = seen_kwargs

    def generate(
        self, messages: list[dict[str, str]], **kwargs: object
    ) -> LLMReply:
        self.seen_kwargs.append(dict(kwargs))
        if self.error_kind:
            raise LLMProviderError(
                f"model {self.model_id} {self.error_kind}",
                error_kind=self.error_kind,
            )
        return LLMReply(
            text=f"ok:{self.model_id}",
            provider="fake",
            model="deepseek-v4-flash",  # 实际上游模型名（actual_model 语义）
            raw_usage={
                "prompt_tokens": 11,
                "completion_tokens": 7,
                "total_tokens": 18,
                "cache_read_tokens": 4,
                "finish_reason": "stop",
            },
        )


def _spec(model_id: str, priority: int) -> ModelSpec:
    return ModelSpec(
        model_id=model_id,
        model="deepseek-v4-flash",
        base_url="https://example.test/v1",
        api_key="key",
        tags=("fast",),
        priority=priority,
        routing_group="qian",
    )


def _router(
    specs: dict[str, ModelSpec],
    failures: dict[str, str],
    sink: object,
    seen_kwargs: list[dict[str, object]] | None = None,
) -> ModelRouter:
    seen = seen_kwargs if seen_kwargs is not None else []
    return ModelRouter(
        specs,
        provider_factory=lambda spec: _FakeProvider(
            spec.model_id, failures.get(spec.model_id, ""), seen
        ),
        call_record_sink=sink,
    )


def test_router_success_emits_single_record() -> None:
    drafts: list[LLMCallDraft] = []

    class CollectingSink:
        def submit(self, draft: LLMCallDraft) -> None:
            drafts.append(draft)

    seen_kwargs: list[dict[str, object]] = []
    router = _router(
        {"ch-a": _spec("ch-a", 1)},
        {},
        CollectingSink(),
        seen_kwargs,
    )
    reply = router.generate(
        [{"role": "user", "content": "hello"}],
        message_text="hello",
        request_id="req-9",
        call_seq=3,
        session_id="group-1",
        capability="bot.chat",
        temperature=0.5,
    )
    assert reply.text == "ok:ch-a"
    assert len(drafts) == 1  # 一行 = 一次 generate()
    draft = drafts[0]
    assert draft.request_id == "req-9"
    assert draft.call_seq == 3
    assert draft.session_id == "group-1"
    assert draft.capability == "bot.chat"
    assert draft.status == "success"
    assert draft.model_id == "ch-a"
    assert draft.provider_id == "ch-a"
    assert draft.actual_model == "deepseek-v4-flash"
    assert draft.routing_group == "qian"
    assert draft.effort == "low"  # deepseek 家族基线档
    assert draft.attempts == reply.attempts == ["ch-a:success"]
    assert draft.prompt_tokens == 11
    assert draft.completion_tokens == 7
    assert draft.total_tokens == 18
    assert draft.cache_read_tokens == 4
    assert draft.unpriced == 1
    assert draft.finish_reason == "stop"
    assert draft.started_at and draft.completed_at
    assert draft.duration_ms is not None and draft.duration_ms >= 0
    # 账本作用域 kwargs 绝不透传给 provider（reasoning_effort 是路由侧
    # 解析出的家族基线档，temperature 原样透传）。
    assert seen_kwargs == [{"temperature": 0.5, "reasoning_effort": "low"}]


def test_router_failover_success_is_one_record() -> None:
    drafts: list[LLMCallDraft] = []

    class CollectingSink:
        def submit(self, draft: LLMCallDraft) -> None:
            drafts.append(draft)

    router = _router(
        {"ch-a": _spec("ch-a", 1), "ch-b": _spec("ch-b", 2)},
        {"ch-a": "rate_limited"},
        CollectingSink(),
    )
    reply = router.generate([{"role": "user", "content": "hi"}], message_text="hi")
    assert reply.text == "ok:ch-b"  # 胜出渠道 ch-b 的假回复
    assert len(drafts) == 1
    assert drafts[0].status == "success"
    assert drafts[0].attempts == ["ch-a:rate_limited", "ch-b:success"]
    assert drafts[0].model_id == "ch-b"  # 胜出渠道


def test_router_final_failure_is_one_record() -> None:
    drafts: list[LLMCallDraft] = []

    class CollectingSink:
        def submit(self, draft: LLMCallDraft) -> None:
            drafts.append(draft)

    router = _router(
        {"ch-a": _spec("ch-a", 1), "ch-b": _spec("ch-b", 2)},
        {"ch-a": "rate_limited", "ch-b": "timeout"},
        CollectingSink(),
    )
    with pytest.raises(LLMProviderError) as raised:
        router.generate([{"role": "user", "content": "hi"}], message_text="hi")
    assert len(drafts) == 1
    draft = drafts[0]
    assert draft.status == "provider_failed"
    assert draft.error_kind == "timeout"  # 最后一个错误
    assert draft.attempts == ["ch-a:rate_limited", "ch-b:timeout"]
    assert draft.model_id == "ch-b"
    assert draft.prompt_tokens is None
    assert draft.unpriced == 0
    assert raised.value.attempts == draft.attempts


def test_router_deadline_status_mapping() -> None:
    drafts: list[LLMCallDraft] = []

    class CollectingSink:
        def submit(self, draft: LLMCallDraft) -> None:
            drafts.append(draft)

    router = _router({"ch-a": _spec("ch-a", 1)}, {}, CollectingSink())
    with pytest.raises(LLMProviderError) as raised:
        router.generate(
            [{"role": "user", "content": "hi"}],
            message_text="hi",
            deadline_monotonic=time.monotonic() - 1.0,  # 预算已耗尽
        )
    assert raised.value.error_kind == "timeout"
    assert len(drafts) == 1
    assert drafts[0].status == "deadline"  # failover:deadline → deadline
    assert "failover:deadline" in drafts[0].attempts


def test_router_sink_failure_does_not_block_chat() -> None:
    class ExplodingSink:
        def submit(self, draft: LLMCallDraft) -> None:
            raise RuntimeError("ledger down")

    router = _router({"ch-a": _spec("ch-a", 1)}, {}, ExplodingSink())
    reply = router.generate([{"role": "user", "content": "hi"}], message_text="hi")
    assert reply.text == "ok:ch-a"  # 聊天不受影响


def test_router_default_off_records_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    drafts: list[LLMCallDraft] = []

    class CollectingSink:
        def submit(self, draft: LLMCallDraft) -> None:
            drafts.append(draft)

    router = _router({"ch-a": _spec("ch-a", 1)}, {}, None)
    reply = router.generate([{"role": "user", "content": "hi"}], message_text="hi")
    assert reply.text == "ok:ch-a"
    assert drafts == []


def test_router_fork_carries_sink() -> None:
    sink = SimpleNamespace()
    router = _router({"ch-a": _spec("ch-a", 1)}, {}, sink)
    assert router.fork()._call_record_sink is sink
