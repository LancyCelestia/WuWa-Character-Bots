"""V2.1 S5 统一事件服务回归（V21-SSE-001，合同 §6 SSE 段 + §8）。

全部离线：tmp_path 隔离 SQLite、注入 fake clock/sleep、原始 ASGI scope 直驱；
零网络、零 NoneBot 运行时、零源码树写入。

覆盖面（对应任务书十项 + 模型/存储基线）：
- 模型：严格 DTO 拒绝未知字段/非法枚举；隐私净化（密钥打码、非标量丢弃）
- 存储：单调 seq、稳定游标分页（默认 50 最大 200）、全过滤器、计数保留 +
  水位缺口检测（CursorExpired）、重启 seq 连续
- 发布：并发发布完整性、best-effort（队列满丢弃/写失败/生命周期拒绝计数）
- SSE：replay→live 无缝、Last-Event-ID 续传、重叠去重（订阅先于回放）、
  游标过期显式 resync、慢消费者有界断开+重连可续、心跳 fake clock、
  权限撤销 unsubscribed、ASGI 工厂（401/405/422/200 流内 resync）
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from plugins.bot_unified_runtime.domains.core.contracts.envelope import V21StrictBase
from plugins.bot_unified_runtime.domains.core.contracts.request import PaginationQuery
from plugins.bot_unified_runtime.domains.ops.monitor.event_service import (
    EventBroker,
    EventService,
    build_event_service,
    create_event_stream_app,
    event_stream,
)
from plugins.bot_unified_runtime.domains.ops.monitor.event_store import (
    DEFAULT_MESSAGES,
    EVENT_CATEGORIES,
    EVENT_SEVERITIES,
    EVENT_SOURCES,
    CursorExpired,
    EventDraft,
    EventQuery,
    EventStore,
    EventStoreUnavailable,
    RuntimeEventV21,
    parse_cursor,
)

UTC = timezone.utc


def make_draft(tag: int = 0, **overrides: Any) -> EventDraft:
    base: dict[str, Any] = {
        "source": "bot",
        "category": "info",
        "message": f"事件{tag}",
    }
    base.update(overrides)
    return EventDraft(**base)


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


class SteppingSleep:
    """注入 event_stream 的确定性 sleep：调用即推进 fake clock；可先挂闸门。"""

    def __init__(
        self,
        clock: FakeClock,
        *,
        step: float = 1.0,
        gate: asyncio.Event | None = None,
        on_first_entered: asyncio.Event | None = None,
    ) -> None:
        self.clock = clock
        self.step = step
        self.gate = gate
        self.on_first_entered = on_first_entered
        self.calls = 0

    async def __call__(self, seconds: float) -> None:
        self.calls += 1
        if self.on_first_entered is not None and self.calls == 1:
            self.on_first_entered.set()
        if self.gate is not None:
            await self.gate.wait()
            self.gate = None  # 只挡第一次
        self.clock.now += max(self.step, seconds)


class GatedQueryStore(EventStore):
    """第一次 query 阻塞在闸门：制造「订阅已建、回放未读」的重叠窗口。"""

    def __init__(self, db_path: Path, **kwargs: Any) -> None:
        super().__init__(db_path, **kwargs)
        self.gate = threading.Event()
        self.first_query_started = threading.Event()

    def query(self, query: EventQuery) -> Any:  # type: ignore[override]
        if not self.first_query_started.is_set():
            self.first_query_started.set()
            self.gate.wait(timeout=10)
        return super().query(query)


class GatedAppendStore(EventStore):
    """第一次 append 阻塞在闸门：占住写线程以测队列满丢弃。"""

    def __init__(self, db_path: Path, **kwargs: Any) -> None:
        super().__init__(db_path, **kwargs)
        self.gate = threading.Event()
        self.first_append_started = threading.Event()

    def append(self, draft: EventDraft) -> Any:  # type: ignore[override]
        if not self.first_append_started.is_set():
            self.first_append_started.set()
            self.gate.wait(timeout=10)
        return super().append(draft)


class FailingAppendStore(EventStore):
    def append(self, draft: EventDraft) -> Any:  # type: ignore[override]
        raise EventStoreUnavailable()


def parse_frame(frame: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    data_lines: list[str] = []
    for line in frame.splitlines():
        if line.startswith("id: "):
            result["id"] = int(line[4:])
        elif line.startswith("event: "):
            result["event"] = line[7:]
        elif line.startswith("data: "):
            data_lines.append(line[6:])
    if data_lines:
        result["data"] = json.loads("\n".join(data_lines))
    return result


async def next_frame(agen: Any, timeout: float = 5.0) -> str:
    return await asyncio.wait_for(agen.__anext__(), timeout)


async def drain_until(agen: Any, predicate: Any, limit: int = 100) -> list[str]:
    frames: list[str] = []
    for _ in range(limit):
        frames.append(await next_frame(agen))
        if predicate(frames):
            return frames
    raise AssertionError("未在限定帧数内满足条件")


# ---------------------------------------------------------------------------
# 模型与隐私净化
# ---------------------------------------------------------------------------


def test_event_sources_and_categories_match_contract() -> None:
    assert EVENT_SOURCES == (
        "bot", "nonebot", "napcat", "telegram", "mail", "control_plane",
        "decision_engine", "pipeline", "sender", "llm", "database", "scheduler",
    )
    assert EVENT_CATEGORIES == (
        "debug", "info", "warning", "error", "success", "critical", "detail",
    )
    assert set(EVENT_SEVERITIES) >= {"critical", "warning", "info"}


def test_event_model_strict_and_privacy_sanitizer(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.sqlite3")
    event = store.append(
        EventDraft(
            source="llm",
            category="error",
            message="调用失败 key=sk-abcdef1234567890",
            request_id="req_abc123",
            safe_details={
                "latency_ms": 123,
                "note": "token=BOT_SECRET_X=1",
                "junk": object(),
                "bad key!": 1,
            },
        )
    )
    # 密钥形态被打码；非标量值与非法键名被丢弃。
    assert "sk-abcdef1234567890" not in event.message
    assert event.safe_details["latency_ms"] == 123
    assert "junk" not in event.safe_details
    assert "bad key!" not in event.safe_details
    assert event.severity == "error"
    assert event.seq >= 1 and event.event_id.startswith("evt_")

    # category 与 severity 分离：success 类别可标 warning 严重度。
    mixed = store.append(
        EventDraft(source="bot", category="success", severity="warning")
    )
    assert mixed.category == "success" and mixed.severity == "warning"
    assert mixed.message == DEFAULT_MESSAGES["success"]

    # 未知字段 / 非法枚举一律拒绝。
    with pytest.raises(ValidationError):
        EventDraft(source="bot", category="info", unknown_field=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        EventDraft(source="nope", category="info")
    with pytest.raises(ValidationError):
        EventDraft(source="bot", category="nope")
    with pytest.raises(ValidationError):
        EventDraft(source="bot", category="info", severity="fatal")
    with pytest.raises(ValidationError):
        EventDraft(source="bot", category="info", privacy_level="secret")


def test_runtime_event_wire_format(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.sqlite3")
    event = store.append(make_draft(1))
    wire = event.to_wire()
    assert wire["seq"] == event.seq
    assert event.wire_bytes() > 0
    again = RuntimeEventV21.model_validate(json.loads(json.dumps(wire, ensure_ascii=False)))
    assert again == event
    # 严格基类复用自 contracts.envelope.V21StrictBase：extra=forbid。
    assert V21StrictBase.model_config["extra"] == "forbid"


# ---------------------------------------------------------------------------
# 存储与查询
# ---------------------------------------------------------------------------


def test_pagination_default_50_max_200_and_stable_cursor(tmp_path: Path) -> None:
    # DTO 复用 contracts.request.PaginationQuery：默认 50、最大 200（§6）。
    assert PaginationQuery().limit == 50
    assert issubclass(EventQuery, PaginationQuery)
    with pytest.raises(ValidationError):
        EventQuery(limit=201)
    with pytest.raises(ValidationError):
        EventQuery(limit=0)

    store = EventStore(tmp_path / "events.sqlite3")
    for i in range(120):
        store.append(make_draft(i, category="debug"))
    page1 = store.query(EventQuery(limit=50))
    assert [e.seq for e in page1.items] == list(range(1, 51))
    assert page1.has_more and page1.next_cursor == 50 and page1.high_seq == 120
    page2 = store.query(EventQuery(limit=50, cursor="50"))
    assert [e.seq for e in page2.items] == list(range(51, 101))
    page3 = store.query(EventQuery(limit=50, cursor=str(page2.next_cursor)))
    assert [e.seq for e in page3.items] == list(range(101, 121))
    assert not page3.has_more and page3.next_cursor == 120
    # 稳定游标：同一位置重复读取结果一致。
    again = store.query(EventQuery(limit=50, cursor="50"))
    assert [e.seq for e in again.items] == [e.seq for e in page2.items]
    with pytest.raises(ValueError):
        store.query(EventQuery(cursor="abc"))
    with pytest.raises(ValueError):
        store.query(EventQuery(cursor="999999"))  # 超前于本库


def test_query_all_filters(tmp_path: Path) -> None:
    ticks = iter(range(1000))
    base = datetime(2026, 9, 17, 12, 0, 0, tzinfo=UTC)

    def clock() -> datetime:
        return base + timedelta(seconds=next(ticks) * 10)

    store = EventStore(tmp_path / "events.sqlite3", clock=clock)
    store.append(make_draft(0, source="bot", category="error",
                            request_id="req_a", trace_id="trace_a",
                            session_id="sess_a", capability_id="cap_a",
                            model_id="model_a"))
    store.append(make_draft(1, source="llm", category="warning",
                            request_id="req_b", trace_id="trace_b",
                            session_id="sess_b", capability_id="cap_b",
                            model_id="model_b"))
    store.append(make_draft(2, source="sender", category="success",
                            severity="critical",
                            request_id="req_c", trace_id="trace_c",
                            session_id="sess_c", capability_id="cap_c",
                            model_id="model_c"))

    def only(**kwargs: Any) -> list[int]:
        return [e.seq for e in store.query(EventQuery(**kwargs)).items]

    assert only(source="llm") == [2]
    assert only(category="warning") == [2]
    assert only(severity="critical") == [3]
    assert only(request_id="req_b") == [2]
    assert only(trace_id="trace_c") == [3]
    assert only(session_id="sess_a") == [1]
    assert only(capability_id="cap_b") == [2]
    assert only(model_id="model_c") == [3]
    assert only(source="bot", category="error") == [1]
    # 时间过滤：aware datetime，归一 UTC 比较（三事件在 +0/+10/+20 秒）。
    assert only(occurred_after=base + timedelta(seconds=5)) == [2, 3]
    assert only(occurred_before=base + timedelta(seconds=15)) == [1, 2]
    assert only(occurred_after=base + timedelta(seconds=5),
                occurred_before=base + timedelta(seconds=15)) == [2]
    # 非法过滤器：ValueError，不静默失效。
    with pytest.raises(ValueError):
        only(source="hacker")
    with pytest.raises(ValueError):
        only(request_id="bad id with space")


def test_retention_watermark_and_cursor_expired(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.sqlite3", max_events=10)
    for i in range(30):
        store.append(make_draft(i))
    assert store.counts() == {"rows": 10, "pruned_through": 20, "high_seq": 30}
    with pytest.raises(CursorExpired) as exc_info:
        store.query(EventQuery(cursor="5"))
    assert exc_info.value.oldest_seq == 21  # 最老可用是 21
    # cursor=None = 显式从最老可用读；缺口显式不静默。
    page = store.query(EventQuery(limit=200))
    assert [e.seq for e in page.items] == list(range(21, 31))


def test_restart_seq_continuity(tmp_path: Path) -> None:
    path = tmp_path / "events.sqlite3"
    store1 = EventStore(path, max_events=100)
    for i in range(5):
        store1.append(make_draft(i))
    last_id = store1.query(EventQuery(limit=1, cursor="4")).items[0].event_id
    del store1
    store2 = EventStore(path, max_events=100)
    event = store2.append(make_draft(99))
    assert event.seq == 6  # AUTOINCREMENT + 水位：重启后 seq 不回绕不复用
    assert store2.get(last_id) is not None
    assert store2.get("evt_000000000000") is None
    with pytest.raises(ValueError):
        store2.get("../evil")


# ---------------------------------------------------------------------------
# 发布面：best-effort / 并发 / 故障
# ---------------------------------------------------------------------------


def test_concurrent_publish_completeness(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.sqlite3", max_events=10_000)
    service = EventService(store, queue_capacity=4096)
    service.start()
    errors: list[BaseException] = []

    def worker(tag: int) -> None:
        try:
            for i in range(25):
                assert service.publish(
                    make_draft(i, source="pipeline", message=f"t{tag}-{i}")
                )
        except BaseException as exc:  # noqa: BLE001 - 测试线程收集
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(tag,)) for tag in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert not errors
    assert service.flush(10)
    seqs: list[int] = []
    page = store.query(EventQuery(limit=200))
    while True:
        seqs.extend(e.seq for e in page.items)
        if not page.has_more:
            break
        page = store.query(EventQuery(limit=200, cursor=str(page.next_cursor)))
    assert len(seqs) == 100
    assert seqs == sorted(seqs) and len(set(seqs)) == 100  # 单调且无重
    assert service.written_count == 100
    assert service.dropped_count == 0 and service.write_error_count == 0
    service.close(5)


def test_storage_failure_best_effort_and_drop_counts(tmp_path: Path) -> None:
    # ① 写失败：publish 仍 True（已入队），失败只计数不阻塞不抛。
    service = EventService(FailingAppendStore(tmp_path / "f.sqlite3"))
    service.start()
    for i in range(3):
        assert service.publish(make_draft(i))
    assert service.flush(5)
    assert service.written_count == 0 and service.write_error_count == 3
    service.close(5)

    # ② 队列满：写线程被闸门占住，容量 2 → 第 4 条被丢弃并计数。
    gated = GatedAppendStore(tmp_path / "g.sqlite3")
    service = EventService(gated, queue_capacity=2)
    service.start()
    assert service.publish(make_draft(0))           # 被写线程取走，阻塞在 append
    assert gated.first_append_started.wait(5)
    assert service.publish(make_draft(1))
    assert service.publish(make_draft(2))
    assert service.publish(make_draft(3)) is False  # Full → best-effort 丢弃
    assert service.dropped_count == 1
    gated.gate.set()
    assert service.flush(5)
    assert service.written_count == 3 and service.dropped_count == 1
    service.close(5)

    # ③ 未启动/已关闭：生命周期拒绝，独立于队列满计数。
    stopped = EventService(EventStore(tmp_path / "s.sqlite3"))
    assert stopped.publish(make_draft(0)) is False
    assert stopped.rejected_count == 1
    stopped.start()
    stopped.close(5)
    assert stopped.publish(make_draft(1)) is False
    assert stopped.rejected_count == 2


def test_build_event_service_factory(tmp_path: Path) -> None:
    service = build_event_service(tmp_path / "f.sqlite3", max_events=100)
    try:
        assert service.is_running
        assert service.publish(make_draft(1))
        assert service.flush(5)
        assert service.store.counts()["rows"] == 1
    finally:
        service.close(5)


# ---------------------------------------------------------------------------
# SSE：回放/续传/去重/resync/慢消费/心跳/撤销
# ---------------------------------------------------------------------------


def test_sse_replay_then_live_seamless(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.sqlite3")
    service = EventService(store)
    service.start()
    for i in range(5):
        assert service.publish(make_draft(i))
    assert service.flush(5)

    async def scenario() -> list[str]:
        agen = event_stream(service, poll_interval=0.01)
        frames = await drain_until(
            agen, lambda fs: sum(f.startswith("id: ") for f in fs) >= 5
        )
        # 历史未收完时实时事件已提交 → 必须无缝接上，不重不漏。
        assert service.publish(make_draft(100, category="warning"))
        frames += await drain_until(agen, lambda fs: "事件100" in fs[-1])
        await agen.aclose()
        parsed = [parse_frame(f) for f in frames if f.startswith("id: ")]
        ids = [p["data"]["event_id"] for p in parsed]
        seqs = [p["id"] for p in parsed]
        assert seqs == sorted(set(seqs))
        return ids

    try:
        ids = asyncio.run(scenario())
    finally:
        service.close(5)
    assert len(ids) == 6 and len(set(ids)) == 6  # 无重复（至少一次+去重语义）


def test_sse_last_event_id_resume(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.sqlite3")
    service = EventService(store)
    service.start()
    for i in range(5):
        assert service.publish(make_draft(i))
    assert service.flush(5)

    async def scenario() -> list[int]:
        # Last-Event-ID='3' → 只从 seq 4 续传。
        agen = event_stream(service, last_event_id="3", poll_interval=0.01)
        frames = await drain_until(
            agen, lambda fs: sum(f.startswith("id: ") for f in fs) >= 2
        )
        await agen.aclose()
        return [parse_frame(f)["id"] for f in frames if f.startswith("id: ")]

    try:
        seqs = asyncio.run(scenario())
    finally:
        service.close(5)
    assert seqs == [4, 5]


def test_sse_overlap_dedupe_subscribe_before_replay(tmp_path: Path) -> None:
    """订阅先于回放：回放查询覆盖到缓冲里已有的 seq → 重叠段必须去重。"""
    store = GatedQueryStore(tmp_path / "events.sqlite3")
    service = EventService(store)
    service.start()
    for i in range(5):
        assert service.publish(make_draft(i))
    assert service.flush(5)

    def block_then_publish() -> None:
        # 在执行器线程里等第一次回放被挡住，随后发布 5..8 并落库，
        # 最后放行回放——事件同时在缓冲与回放窗口里，构成真实重叠。
        store.first_query_started.wait(5)
        for i in range(5, 8):
            assert service.publish(make_draft(i))
        service.flush(5)
        store.gate.set()

    async def scenario() -> list[int]:
        agen = event_stream(service, poll_interval=0.01)
        first_task = asyncio.create_task(agen.__anext__())
        await asyncio.to_thread(block_then_publish)
        first = await asyncio.wait_for(first_task, 5.0)
        frames = await drain_until(
            agen, lambda fs: sum(f.startswith("id: ") for f in fs) >= 7
        )
        await agen.aclose()
        parsed = [parse_frame(f) for f in [first, *frames] if f.startswith("id: ")]
        return [p["id"] for p in parsed]

    try:
        seqs = asyncio.run(scenario())
    finally:
        service.close(5)
    assert seqs == list(range(1, 9))  # 严格递增无重复：重叠的 5..8 只出现一次


def test_sse_cursor_expired_explicit_resync(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.sqlite3", max_events=10)
    service = EventService(store)
    service.start()
    for i in range(30):
        assert service.publish(make_draft(i))
    assert service.flush(5)

    async def scenario() -> list[str]:
        agen = event_stream(service, last_event_id="1", poll_interval=0.01)
        # resync 帧也带 id 前缀，这里只数 runtime_event 帧。
        frames = await drain_until(
            agen,
            lambda fs: sum("event: runtime_event" in f for f in fs) >= 3,
        )
        await agen.aclose()
        return frames

    try:
        frames = asyncio.run(scenario())
    finally:
        service.close(5)
    parsed = [parse_frame(f) for f in frames]
    resync = next(p for p in parsed if p.get("event") == "resync")
    assert resync["data"]["reason"] == "cursor_expired"
    assert resync["data"]["oldest_seq"] == 21
    assert resync["id"] == 21  # id 推进到重同步落点，客户端不会卡回过期游标
    assert "hint" in resync["data"]
    # resync 后从最老可用处继续回放（显式，不静默丢）。
    ids = [p["id"] for p in parsed if p.get("event") == "runtime_event"]
    assert ids == [21, 22, 23]


def test_sse_slow_consumer_bounded_then_resume(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.sqlite3")
    # 每连接缓冲 ≤128 事件：这里收窄到 2 条以构造确定性溢出。
    service = EventService(store, buffer_events=2, buffer_bytes=256 * 1024)
    service.start()
    for i in range(2):
        assert service.publish(make_draft(i))
    assert service.flush(5)
    gate = asyncio.Event()
    entered = asyncio.Event()

    async def scenario() -> list[str]:
        clock = FakeClock(0.0)
        sleep = SteppingSleep(clock, step=0.0, gate=gate, on_first_entered=entered)
        agen = event_stream(service, poll_interval=0.01, heartbeat_seconds=15.0,
                            clock=clock, sleep=sleep)
        frames: list[str] = []
        frames.append(await next_frame(agen))  # id: 1
        frames.append(await next_frame(agen))  # id: 2
        # 推进生成器到 idle sleep 内部（订阅缓冲此刻无人消费）。
        pending = asyncio.create_task(agen.__anext__())
        await asyncio.wait_for(entered.wait(), 5.0)
        # 突发 4 条 > 缓冲 2 → 溢出标记，超限丢弃计数。
        for i in range(2, 6):
            assert service.publish(make_draft(i))
        await asyncio.to_thread(service.flush, 5)
        assert service.broker.subscriber_count == 1
        gate.set()
        frames.append(await asyncio.wait_for(pending, 5.0))
        while True:
            frame = await next_frame(agen)
            frames.append(frame)
            if "slow_consumer" in frame:
                with pytest.raises(StopAsyncIteration):
                    await next_frame(agen)
                break
        await agen.aclose()
        return frames

    try:
        frames = asyncio.run(scenario())
    finally:
        service.close(5)
    resync = parse_frame([f for f in frames if "slow_consumer" in f][-1])
    assert resync["data"]["dropped_events"] == 2  # 缓冲拒绝了 2 条实时推送
    assert "Last-Event-ID" in resync["data"]["hint"]
    # 慢消费者断开：流在 resync 帧后终止；已持久化事件不假装丢失，
    # 可经 Last-Event-ID 重连补齐（至少一次）。
    ids = [parse_frame(f)["id"] for f in frames if f.startswith("id: ")]
    assert ids == [1, 2, 3, 4, 5, 6]

    # 重连续传：Last-Event-ID='4' 可完整补齐 5、6。
    async def resume() -> list[int]:
        agen = event_stream(service, last_event_id="4", poll_interval=0.01)
        got = await drain_until(
            agen, lambda fs: sum(f.startswith("id: ") for f in fs) >= 2
        )
        await agen.aclose()
        return [parse_frame(f)["id"] for f in got if f.startswith("id: ")]

    assert asyncio.run(resume()) == [5, 6]


def test_sse_heartbeat_fake_clock_and_revocation(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.sqlite3")
    service = EventService(store)
    service.start()
    assert service.publish(make_draft(0))
    assert service.flush(5)

    async def scenario() -> tuple[int, float]:
        clock = FakeClock(0.0)
        sleep = SteppingSleep(clock, step=1.0)
        agen = event_stream(service, poll_interval=1.0, heartbeat_seconds=15.0,
                            clock=clock, sleep=sleep)
        first = await next_frame(agen)
        assert first.startswith("id: 1")
        heartbeat = await next_frame(agen)  # 空闲 → 心跳
        assert heartbeat == ": heartbeat\n\n"
        await agen.aclose()
        return sleep.calls, clock.now

    try:
        calls, now = asyncio.run(scenario())
    finally:
        service.close(5)
    assert calls == 15  # 恰好 15s 空闲后才心跳（fake clock 确定性）
    assert now == 15.0

    # 权限撤销接口：keep_principal False → unsubscribed 帧并结束。
    async def revocation() -> list[str]:
        agen = event_stream(service, poll_interval=0.01, keep_principal=lambda: False)
        frames: list[str] = []
        with pytest.raises(StopAsyncIteration):
            while True:
                frames.append(await next_frame(agen))
        await agen.aclose()
        return frames

    frames = asyncio.run(revocation())
    assert any("unsubscribed" in f for f in frames)


def test_subscription_bytes_bound() -> None:
    big = RuntimeEventV21(
        seq=1, event_id="evt_" + "0" * 12,
        occurred_at=datetime.now(UTC), source="bot", category="info",
        severity="info", message="x" * 200,
    )
    small = big.model_copy(update={"seq": 2, "message": "y"})
    # 预算恰好容纳一条 big 事件：第二条必然触发字节上限。
    broker = EventBroker(buffer_events=100, buffer_bytes=big.wire_bytes() + 8)
    sub = broker.subscribe()
    sub.offer(big)
    assert not sub.overflowed
    sub.offer(small)
    assert sub.overflowed  # 字节上限触顶（≤256KiB 语义在收窄预算上同构）
    assert len(sub) == 1 and sub.dropped_in_buffer == 1
    drained = sub.drain()
    assert len(drained) == 1 and drained[0].seq == 1
    sub.close()
    assert broker.subscriber_count == 0


# ---------------------------------------------------------------------------
# ASGI 工厂
# ---------------------------------------------------------------------------


def _scope(method: str = "GET", headers: list[tuple[bytes, bytes]] | None = None,
           query: bytes = b"") -> dict[str, Any]:
    return {
        "type": "http",
        "method": method,
        "path": "/api/v1/logs/events/stream",
        "headers": headers or [],
        "query_string": query,
    }


def _never_receive() -> Any:
    async def receive() -> dict[str, str]:
        await asyncio.Event().wait()  # 永不返回
        return {}

    return receive


def test_asgi_factory_auth_errors_and_stream(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.sqlite3")
    service = EventService(store)
    service.start()
    assert service.publish(make_draft(1))
    assert service.flush(5)

    async def scenario() -> dict[str, Any]:
        results: dict[str, Any] = {}

        async def send(message: dict[str, Any]) -> None:
            sent.append(message)

        sent: list[dict[str, Any]] = []

        # ① 未认证 → 401；② 非 GET → 405；③ 游标语法垃圾 → 422。
        app = create_event_stream_app(service, auth=lambda scope, headers: None)
        await asyncio.wait_for(app(_scope(), _never_receive(), send), 5)
        results["auth"] = sent[0]["status"]
        sent.clear()
        plain_app = create_event_stream_app(service)
        await asyncio.wait_for(plain_app(_scope(method="POST"), _never_receive(), send), 5)
        results["method"] = sent[0]["status"]
        sent.clear()
        await asyncio.wait_for(
            plain_app(_scope(headers=[(b"last-event-id", b"abc")]),
                      _never_receive(), send),
            5,
        )
        results["cursor"] = sent[0]["status"]

        async def run_stream(scope: dict[str, Any], app: Any,
                             need_chunks: int) -> tuple[dict[str, Any], str]:
            chunks: list[bytes] = []
            stream_sent: list[dict[str, Any]] = []

            async def send2(message: dict[str, Any]) -> None:
                stream_sent.append(message)
                if message.get("type") == "http.response.body":
                    chunks.append(message["body"])

            task = asyncio.create_task(app(scope, _never_receive(), send2))
            try:
                for _ in range(300):
                    await asyncio.sleep(0.01)
                    if len(chunks) >= need_chunks:
                        break
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            return stream_sent[0], b"".join(chunks).decode()

        # ④ 游标超前（999999）→ 200 流内显式 resync（cursor_reset），非静默。
        start, text = await run_stream(
            _scope(headers=[(b"last-event-id", b"999999")]), plain_app, 2
        )
        results["ahead_start"] = start
        results["ahead_body"] = text

        # ⑤ 正常订阅：200 + text/event-stream + 帧流（source 过滤）。
        class NoSleep:
            async def __call__(self, seconds: float) -> None:
                await asyncio.sleep(0)

        start, text = await run_stream(
            _scope(query=b"source=bot"),
            create_event_stream_app(service, heartbeat_seconds=60.0,
                                    sleep=NoSleep()),
            1,
        )
        results["ok_start"] = start
        results["ok_body"] = text
        return results

    try:
        got = asyncio.run(scenario())
    finally:
        service.close(5)
    assert got["auth"] == 401
    assert got["method"] == 405
    assert got["cursor"] == 422
    # ④ 过期/超前游标不再是 HTTP 410：200 流内 resync（本席位合同差异）。
    assert got["ahead_start"]["status"] == 200
    assert "event: resync" in got["ahead_body"]
    assert "cursor_reset" in got["ahead_body"]
    # ⑤ 流头与帧。
    assert got["ok_start"]["status"] == 200
    headers = {
        k.decode().lower(): v.decode()
        for k, v in got["ok_start"]["headers"]
    }
    assert headers["content-type"].startswith("text/event-stream")
    assert "no-cache" in headers["cache-control"]
    assert headers["x-accel-buffering"] == "no"
    assert "id: 1" in got["ok_body"] and "runtime_event" in got["ok_body"]


def test_parse_cursor_forms() -> None:
    assert parse_cursor(None) is None
    assert parse_cursor("0") == 0
    assert parse_cursor(42) == 42
    with pytest.raises(ValueError):
        parse_cursor("-1")
    with pytest.raises(ValueError):
        parse_cursor("x")
    with pytest.raises(TypeError):
        parse_cursor(True)  # 类型违规 → TypeError；取值违规才是 ValueError
    with pytest.raises(TypeError):
        parse_cursor(3.5)
