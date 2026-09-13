"""P2-1 订阅存储 async 门面回归（性能分诊 q2-hotspot-triage.md P2-1）。

订阅轮询/投递调度器（subscription_scheduler）此前在 event loop 上直接执行
SubscriptionStoreV2 的同步 SQLite。修复约定：

1. 存储层同步实现保持不动（被工作线程执行，线程安全由既有 ``_lock`` 保证）；
2. 对外新增 ``*_async`` 门面，内部一律 ``asyncio.to_thread`` 下放；
3. 调度器只经门面访问存储，行为零变化（同输入同输出同落库）。

本文件验证：
- async 门面读写与同步实现同一落库结果（经同步 API 回读校验）；
- 门面与调度器触达的存储同步段均不在 event loop 线程上（线程 id 断言）。
"""
from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from plugins.bot_unified_runtime.contracts.subscription import (
    ContentReference,
    SubscriptionCursorV2,
    SubscriptionDestinationV2,
    SubscriptionFetchResult,
    SubscriptionOutboxEvent,
    SubscriptionTarget,
)
from plugins.bot_unified_runtime.sources.subscription_scheduler import (
    SubscriptionScheduler,
)
from plugins.bot_unified_runtime.sources.subscription_store_v2 import (
    SubscriptionStoreV2,
)

_NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)

# 调度器正常路径（含成功投递、失败重试、失败 adapter）应触达的存储同步方法
# 全集；用于断言这些同步段都不在 loop 线程上执行。
_SCHEDULER_TOUCHED = {
    "list_targets",
    "claim_due_target",
    "get_cursors",
    "get_target_metadata",
    "save_fetch_result",
    "release_target",
    "record_failure",
    "claim_outbox",
    "mark_outbox_sent",
    "mark_outbox_retry",
}


def _target(
    target_id: str, *, platform: str = "test", baseline: bool = False
) -> SubscriptionTarget:
    return SubscriptionTarget(
        id=target_id,
        platform=platform,
        target_kind="channel",
        target_key=target_id,
        baseline_initialized=baseline,
        base_interval_seconds=300,
        jitter_ratio=0.0,
        next_poll_at=_NOW,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _result(target_id: str, *item_ids: str) -> SubscriptionFetchResult:
    return SubscriptionFetchResult(
        items=[
            ContentReference(
                item_id=item_id,
                item_kind="video",
                url=f"https://example.test/{item_id}",
            )
            for item_id in item_ids
        ],
        cursors=[
            SubscriptionCursorV2(
                target_id=target_id,
                stream="default",
                last_item_id=item_ids[-1] if item_ids else "",
                updated_at=_NOW,
            )
        ],
    )


class _OkAdapter:
    platform = "test"
    target_kinds = frozenset({"channel"})

    def __init__(self) -> None:
        self.calls = 0

    async def fetch_incremental(self, target, cursors, context):
        self.calls += 1
        return _result(target.id, f"v{self.calls}")


class _BrokenAdapter:
    platform = "bad"
    target_kinds = frozenset({"channel"})

    async def fetch_incremental(self, target, cursors, context):
        raise RuntimeError("adapter exploded")


class _ThreadSpyStore(SubscriptionStoreV2):
    """记录每个存储同步方法实际执行线程的探针。

    只重写同步方法：async 门面最终也会调到这里（在工作线程上），因此任何
    绕过门面、在 loop 线程直调同步存储的回归都会被抓到。
    """

    def __init__(self, db_path: str) -> None:
        super().__init__(db_path)
        self._spy_lock = threading.Lock()
        self.call_threads: dict[str, set[int]] = {}

    def _record(self, name: str) -> None:
        with self._spy_lock:
            self.call_threads.setdefault(name, set()).add(threading.get_ident())

    def list_targets(
        self, *, due_before: datetime | None = None
    ) -> list[SubscriptionTarget]:
        self._record("list_targets")
        return super().list_targets(due_before=due_before)

    def claim_due_target(
        self, target_id: str, now: datetime, lease_seconds: int
    ) -> bool:
        self._record("claim_due_target")
        return super().claim_due_target(target_id, now, lease_seconds)

    def get_cursors(self, target_id: str) -> dict[str, SubscriptionCursorV2]:
        self._record("get_cursors")
        return super().get_cursors(target_id)

    def get_target_metadata(self, target_id: str) -> dict[str, Any]:
        self._record("get_target_metadata")
        return super().get_target_metadata(target_id)

    def save_fetch_result(
        self,
        target: SubscriptionTarget,
        result: SubscriptionFetchResult,
        *,
        baseline: bool,
    ) -> list[SubscriptionOutboxEvent]:
        self._record("save_fetch_result")
        return super().save_fetch_result(target, result, baseline=baseline)

    def set_target_metadata(self, target_id: str, metadata: dict[str, Any]) -> None:
        self._record("set_target_metadata")
        return super().set_target_metadata(target_id, metadata)

    def release_target(self, target_id: str, *, next_poll_at: datetime) -> None:
        self._record("release_target")
        return super().release_target(target_id, next_poll_at=next_poll_at)

    def release_target_lease(self, target_id: str) -> None:
        self._record("release_target_lease")
        return super().release_target_lease(target_id)

    def record_failure(
        self, target_id: str, error_code: str, *, retry_at: datetime
    ) -> None:
        self._record("record_failure")
        return super().record_failure(target_id, error_code, retry_at=retry_at)

    def claim_outbox(self, now: datetime, limit: int) -> list[SubscriptionOutboxEvent]:
        self._record("claim_outbox")
        return super().claim_outbox(now, limit)

    def mark_outbox_sent(self, event_id: str, sent_at: datetime) -> None:
        self._record("mark_outbox_sent")
        return super().mark_outbox_sent(event_id, sent_at)

    def mark_outbox_retry(self, event_id: str, next_attempt_at: datetime) -> None:
        self._record("mark_outbox_retry")
        return super().mark_outbox_retry(event_id, next_attempt_at)

    def outbox_state(self, event_id: str) -> str | None:
        self._record("outbox_state")
        return super().outbox_state(event_id)


def test_async_facade_target_lifecycle_matches_sync_reads(tmp_path) -> None:
    """async 门面写入的目标/目的地/元数据/失败记账与同步 API 回读一致。"""
    store = SubscriptionStoreV2(str(tmp_path / "subscriptions.sqlite3"))

    async def scenario() -> None:
        await store.upsert_target_async(_target("test:channel:1"))
        await store.add_destination_async(
            SubscriptionDestinationV2(
                target_id="test:channel:1",
                transport="onebot.v11",
                scope="group",
                destination_id="12345",
            )
        )
        assert len(await store.list_targets_async()) == 1
        assert await store.claim_due_target_async("test:channel:1", _NOW, 60) is True
        assert await store.claim_due_target_async("test:channel:1", _NOW, 60) is False
        await store.release_target_async(
            "test:channel:1", next_poll_at=_NOW + timedelta(seconds=300)
        )
        await store.set_target_metadata_async("test:channel:1", {"rest_id": "x1"})
        assert await store.get_target_metadata_async("test:channel:1") == {
            "rest_id": "x1"
        }
        await store.record_failure_async(
            "test:channel:1", "rate_limited", retry_at=_NOW + timedelta(seconds=900)
        )
        await store.set_destination_enabled_async(1, False)
        assert await store.set_target_enabled_async("test:channel:1", False) is True

    asyncio.run(scenario())

    # 全部经同步 API 回读：async 门面与同步实现落同一 DB、同一行。
    target = store.get_target("test:channel:1")
    assert target is not None
    assert target.health_state == "rate_limited"
    assert target.failure_count == 1
    assert target.backoff_until == _NOW + timedelta(seconds=900)
    assert target.lease_until is None
    assert target.enabled is False
    destinations = store.list_destinations("test:channel:1")
    assert len(destinations) == 1 and destinations[0].enabled is False
    assert store.get_target_metadata("test:channel:1") == {"rest_id": "x1"}


def test_async_facade_save_fetch_result_and_outbox_flow(tmp_path) -> None:
    """save_fetch_result_async / claim_outbox_async 等与同步版产出一致。

    事件时间戳由 save_fetch_result 内部用真实时钟生成，因此 claim/mark
    的时间基准也取真实时钟（避免固定时刻与真实时刻的相对关系漂移）。
    """
    store = SubscriptionStoreV2(str(tmp_path / "subscriptions.sqlite3"))
    target = _target("test:channel:1")
    store.upsert_target(target)

    async def scenario() -> None:
        # 基线：items 落 seen、无 outbox 事件。
        baseline_events = await store.save_fetch_result_async(
            target, _result(target.id, "v1"), baseline=True
        )
        assert baseline_events == []
        # 新条目：产出 new_item 事件（与同步版同 event_id 同 payload 落库）。
        events = await store.save_fetch_result_async(
            target, _result(target.id, "v2"), baseline=False
        )
        assert [event.event_id for event in events] == ["test:channel:1:video:v2"]
        # 重复投喂同一条目：INSERT OR IGNORE 去重，不产生新事件。
        replay = await store.save_fetch_result_async(
            target, _result(target.id, "v2"), baseline=False
        )
        assert replay == []
        # 游标经同步 API 可回读。
        cursors = store.get_cursors(target.id)
        assert cursors["default"].last_item_id == "v2"

        base = datetime.now(timezone.utc)
        claimed = await store.claim_outbox_async(base + timedelta(seconds=1), limit=10)
        assert [event.event_id for event in claimed] == ["test:channel:1:video:v2"]
        assert all(event.state == "sending" for event in claimed)
        await store.mark_outbox_sent_async(
            claimed[0].event_id, base + timedelta(seconds=2)
        )
        assert await store.outbox_state_async(claimed[0].event_id) == "sent"

        # 重试路径：claim 后转 retry，到期可再次 claim。
        more = await store.save_fetch_result_async(
            target, _result(target.id, "v3"), baseline=False
        )
        assert [event.event_id for event in more] == ["test:channel:1:video:v3"]
        claimed_retry = await store.claim_outbox_async(
            base + timedelta(seconds=3), limit=10
        )
        assert [event.event_id for event in claimed_retry] == [
            "test:channel:1:video:v3"
        ]
        await store.mark_outbox_retry_async(
            claimed_retry[0].event_id, base + timedelta(seconds=60)
        )
        assert await store.outbox_state_async(claimed_retry[0].event_id) == "retry"
        assert await store.claim_outbox_async(base + timedelta(seconds=61), limit=10)

    asyncio.run(scenario())

    # 同步回读：outbox 终态落库正确（v3 已被到期 claim 领走 → sending）。
    with store._lock:
        rows = (
            store._get_connection()
            .execute(
                "SELECT event_id, state FROM subscription_outbox ORDER BY event_id"
            )
            .fetchall()
        )
    assert {str(row["event_id"]): str(row["state"]) for row in rows} == {
        "test:channel:1:video:v2": "sent",
        "test:channel:1:video:v3": "sending",
    }


def test_async_facade_executes_sync_segments_off_event_loop(tmp_path) -> None:
    """门面触达的存储同步段必须不在 loop 线程上执行（线程 id 断言）。"""
    store = _ThreadSpyStore(str(tmp_path / "subscriptions.sqlite3"))
    store.upsert_target(_target("test:channel:1", baseline=True))

    async def scenario() -> None:
        loop_ident = threading.get_ident()
        # 对照组：直接同步调用就在 loop 线程上（证明探针有效）。
        store.list_targets()
        assert loop_ident in store.call_threads["list_targets"]
        store.call_threads["list_targets"].clear()
        # 实验组：同一方法经 async 门面必须换线程执行。
        await store.list_targets_async()
        recorded = store.call_threads["list_targets"]
        assert recorded and loop_ident not in recorded
        await store.save_fetch_result_async(
            _target("test:channel:1"),
            _result("test:channel:1", "v9"),
            baseline=False,
        )
        recorded = store.call_threads["save_fetch_result"]
        assert recorded and loop_ident not in recorded
        await store.claim_outbox_async(_NOW, limit=5)
        recorded = store.call_threads["claim_outbox"]
        assert recorded and loop_ident not in recorded
        await store.release_target_lease_async("test:channel:1")
        recorded = store.call_threads["release_target_lease"]
        assert recorded and loop_ident not in recorded

    asyncio.run(scenario())


def test_scheduler_store_work_runs_off_event_loop(tmp_path) -> None:
    """调度器轮询/投递触达的全部存储同步段均不在 loop 线程上，且行为不变。"""
    store = _ThreadSpyStore(str(tmp_path / "subscriptions.sqlite3"))
    ok_adapter = _OkAdapter()
    store.upsert_target(_target("test:ok:1"))
    store.upsert_target(_target("test:ok:2"))
    store.upsert_target(_target("test:bad:1", platform="bad"))
    delivered: list[str] = []

    async def deliver(event) -> bool:
        delivered.append(event.event_id)
        return event.target_id == "test:ok:1"

    scheduler = SubscriptionScheduler(
        store,
        [ok_adapter, _BrokenAdapter()],
        random_fn=lambda: 0.5,
        # 投递阶段用真实时钟对齐 save_fetch_result 内部的真实时间戳；
        # 轮询阶段显式传 now=_NOW 保持调度数学确定。
        clock=lambda: datetime.now(timezone.utc),
        delivery_fn=deliver,
    )

    async def scenario() -> None:
        # 第一轮：ok 目标基线（无事件）；bad 目标抓取抛异常 → record_failure。
        assert await scheduler.poll_due_once(now=_NOW) == []
        # 重排两个 ok 目标的轮询时刻（固定时钟 + interval 300s，否则第二轮不到期）。
        for target_id in ("test:ok:1", "test:ok:2"):
            saved = store.get_target(target_id)
            assert saved is not None
            store.upsert_target(saved.model_copy(update={"next_poll_at": _NOW}))
        # 第二轮：ok 目标各产出一条新事件（共享 adapter 计数：v3 / v4）。
        events = await scheduler.poll_due_once(now=_NOW)
        assert [event.event_id for event in events] == [
            "test:ok:1:video:v3",
            "test:ok:2:video:v4",
        ]
        # 投递：一条成功（sent）、一条失败（转 retry）。
        assert await scheduler.deliver_outbox_once(limit=20) == 1

    asyncio.run(scenario())

    loop_ident = threading.get_ident()
    touched = set(store.call_threads)
    missing = _SCHEDULER_TOUCHED - touched
    assert not missing, f"scheduler paths did not touch: {sorted(missing)}"
    for name in _SCHEDULER_TOUCHED:
        assert loop_ident not in store.call_threads[name], (
            f"{name} executed on the event loop thread"
        )
    # 行为零变化：落库终态与旧同步实现完全一致。
    assert delivered == ["test:ok:1:video:v3", "test:ok:2:video:v4"]
    assert store.outbox_state("test:ok:1:video:v3") == "sent"
    assert store.outbox_state("test:ok:2:video:v4") == "retry"
    ok = store.get_target("test:ok:1")
    assert ok is not None and ok.baseline_initialized is True
    bad = store.get_target("test:bad:1")
    assert bad is not None
    assert bad.health_state == "network_error"
    assert bad.failure_count == 1
