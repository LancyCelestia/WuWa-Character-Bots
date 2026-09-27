"""审查 J-03/J-04 订阅推送可靠性回归。

- J-04：deliver_outbox_once 先投递后 mark_outbox_sent，两写之间崩溃/超时
  （含 claim 回收 sending>300s 陈旧行的重投）会重复推送。修法 = 目的地级
  幂等：store 增设 (event_id, destination_key) 成功台账，投递前查重、
  成功后台账先行于 sent 标记。
- J-03：state='dead' 死信此前全仓无告警无重投入口。修法 = 转移时产生
  runtime/alerts 告警（OperationalIssue + AdminAlertSuppression，300s
  抑制键含订阅 id 与目的地）+ store 级幂等 requeue_dead 重投方法。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import OperationalIssue
from plugins.bot_unified_runtime.domains.core.contracts.subscription import (
    ContentReference,
    SubscriptionDestinationV2,
    SubscriptionFetchResult,
    SubscriptionTarget,
)
from plugins.bot_unified_runtime.domains.subscribe.store.subscription_scheduler import (
    SubscriptionScheduler,
)
from plugins.bot_unified_runtime.domains.subscribe.store.subscription_store_v2 import (
    SubscriptionStoreV2,
    _event_id_for,
)

_EVENT_ID = _event_id_for("test:channel:1", "video", "v1")


def _seed_target_with_destination(store: SubscriptionStoreV2) -> str:
    """建目标 + 一个群目的地 + 一条待发事件，返回 event_id。"""
    target = SubscriptionTarget(
        id="test:channel:1",
        platform="test",
        target_kind="channel",
        target_key="1",
        baseline_initialized=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    store.upsert_target(target)
    store.add_destination(
        SubscriptionDestinationV2(
            target_id=target.id,
            transport="onebot.v11",
            scope="group",
            destination_id="12345",
        )
    )
    events = store.save_fetch_result(
        target,
        SubscriptionFetchResult(
            items=[ContentReference(item_id="v1", item_kind="video", url="https://x/v1")]
        ),
        baseline=False,
    )
    assert [event.event_id for event in events] == [_EVENT_ID]
    return _EVENT_ID


def _seed_extra_event(store: SubscriptionStoreV2, item_id: str) -> str:
    target = store.get_target("test:channel:1")
    assert target is not None
    events = store.save_fetch_result(
        target,
        SubscriptionFetchResult(
            items=[ContentReference(item_id=item_id, item_kind="video", url=f"https://x/{item_id}")]
        ),
        baseline=False,
    )
    assert len(events) == 1
    return events[0].event_id


class _CrashedAfterDeliveryStore(SubscriptionStoreV2):
    """模拟「投递成功之后、两处标记落库之前」进程崩溃：sent/retry 标记
    全部抛错，事件状态停在 sending（真实进程死亡时 finally 兜底也不会跑）。"""

    def mark_outbox_sent(self, event_id: str, sent_at: datetime) -> None:
        raise RuntimeError("simulated crash after delivery")

    def mark_outbox_retry(self, event_id: str, next_attempt_at: datetime) -> None:
        raise RuntimeError("simulated crash after delivery")


class _FlakyMarkSentStore(SubscriptionStoreV2):
    """只在第一次 mark_outbox_sent 抛错（模拟单次标记失败/抖动）。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fail_sent_first = True

    def mark_outbox_sent(self, event_id: str, sent_at: datetime) -> None:
        if self.fail_sent_first:
            self.fail_sent_first = False
            raise RuntimeError("simulated mark failure")
        super().mark_outbox_sent(event_id, sent_at)


def test_crash_between_delivery_and_mark_does_not_redeliver_after_restart(tmp_path) -> None:
    """J-04 ①：投递成功后标记前崩溃 → 重启回收 sending 行重投前查重命中，
    不重复推送。"""
    crashed = _CrashedAfterDeliveryStore(str(tmp_path / "subscriptions.sqlite3"))
    event_id = _seed_target_with_destination(crashed)
    delivered_first: list[str] = []

    async def deliver_first(event: Any) -> bool:
        delivered_first.append(event.event_id)
        return True

    clock = {"now": datetime.now(timezone.utc)}
    crashed_scheduler = SubscriptionScheduler(
        crashed,
        [],
        delivery_fn=deliver_first,
        clock=lambda: clock["now"],
    )
    # 第一次投递：delivery_fn 成功、成功台账落库，随后 sent/retry 标记双双
    # 抛错（模拟崩溃）→ 异常冒泡、事件滞留 sending。
    with pytest.raises(RuntimeError, match="simulated crash"):
        asyncio.run(crashed_scheduler.deliver_outbox_once())
    assert delivered_first == [event_id]

    # “重启”：同一 DB 上全新 store/scheduler。崩溃时刻台账已先于标记落库。
    store = SubscriptionStoreV2(str(tmp_path / "subscriptions.sqlite3"))
    assert store.outbox_state(event_id) == "sending"
    assert store.outbox_undelivered_destinations(event_id, ["1"]) == []

    # 时钟推进 400s（> sending 300s 陈旧阈值）→ claim 回收 sending 行，
    # 重投前查重命中 → 不再调用 delivery_fn，只补 sent 标记。
    clock["now"] = clock["now"] + timedelta(seconds=400)
    delivered_second: list[str] = []

    async def deliver_second(event: Any) -> bool:
        delivered_second.append(event.event_id)
        return True

    scheduler = SubscriptionScheduler(
        store,
        [],
        delivery_fn=deliver_second,
        clock=lambda: clock["now"],
    )
    assert asyncio.run(scheduler.deliver_outbox_once()) == 1
    assert delivered_second == []  # 重投零推送
    assert store.outbox_state(event_id) == "sent"


def test_mark_sent_failure_falls_back_then_dedupes_on_next_tick(tmp_path) -> None:
    """J-04 补充：mark_outbox_sent 单次失败时 finally 兜底转 retry，下一轮
    投递前查重命中，delivery_fn 全程只被调用一次。"""
    store = _FlakyMarkSentStore(str(tmp_path / "subscriptions.sqlite3"))
    event_id = _seed_target_with_destination(store)
    delivered: list[str] = []

    async def deliver(event: Any) -> bool:
        delivered.append(event.event_id)
        return True

    clock = {"now": datetime.now(timezone.utc)}
    scheduler = SubscriptionScheduler(
        store,
        [],
        delivery_fn=deliver,
        clock=lambda: clock["now"],
        retry_base_seconds=1,
    )
    with pytest.raises(RuntimeError, match="simulated mark failure"):
        asyncio.run(scheduler.deliver_outbox_once())
    # 兜底路径可用（mark_outbox_retry 未坏）→ 事件转 retry 而非滞留 sending。
    assert store.outbox_state(event_id) == "retry"

    clock["now"] = clock["now"] + timedelta(seconds=2)
    assert asyncio.run(scheduler.deliver_outbox_once()) == 1
    assert delivered == [event_id]  # 恰好一次
    assert store.outbox_state(event_id) == "sent"


def test_normal_delivery_path_unchanged(tmp_path) -> None:
    """J-04 ②：正常路径零变化——delivery_fn 恰一次、sent 标记一次、台账
    只记启用目的地，事件终态后不再被投递。"""
    store = SubscriptionStoreV2(str(tmp_path / "subscriptions.sqlite3"))
    event_id = _seed_target_with_destination(store)
    store.add_destination(
        SubscriptionDestinationV2(
            target_id="test:channel:1",
            transport="onebot.v11",
            scope="private",
            destination_id="67890",
        )
    )
    store.set_destination_enabled(2, False)  # 私聊目的地已停用
    delivered: list[str] = []

    async def deliver(event: Any) -> bool:
        delivered.append(event.event_id)
        return True

    scheduler = SubscriptionScheduler(store, [], delivery_fn=deliver)
    assert asyncio.run(scheduler.deliver_outbox_once()) == 1
    assert delivered == [event_id]
    assert store.outbox_state(event_id) == "sent"
    # 台账只含启用目的地（rowid 1）；停用的 rowid 2 不在册。
    assert store.outbox_undelivered_destinations(event_id, ["1"]) == []
    assert store.outbox_undelivered_destinations(event_id, ["1", "2"]) == ["2"]
    # 终态事件不再被 claim/投递。
    assert asyncio.run(scheduler.deliver_outbox_once()) == 0
    assert delivered == [event_id]


def test_dead_transition_emits_alert_with_subscription_and_destination(tmp_path) -> None:
    """J-03 ③：dead 转移经 fake sink 产生告警，stage/kind 含订阅 id 与
    目的地；同订阅同目的地 300s 抑制窗口内不重复告警。"""
    sink: list[OperationalIssue] = []
    store = SubscriptionStoreV2(
        str(tmp_path / "subscriptions.sqlite3"),
        outbox_max_attempts=1,
        dead_letter_sink=sink.append,
    )
    event_id = _seed_target_with_destination(store)
    now = datetime.now(timezone.utc)

    claimed = store.claim_outbox(now, limit=5)
    assert [event.event_id for event in claimed] == [event_id]
    store.mark_outbox_retry(event_id, now + timedelta(seconds=1))
    assert store.outbox_state(event_id) == "dead"
    assert len(sink) == 1
    issue = sink[0]
    assert issue.stage == "subscription_outbox_dead"
    assert "test:channel:1" in issue.kind  # 订阅 id
    assert "group:12345" in issue.kind  # 目的地（scope:destination_id）
    assert issue.debug_id == event_id
    assert issue.retryable is False

    # 同订阅同目的地第二条事件转死信：抑制窗口内不再重复告警。
    second_id = _seed_extra_event(store, "v2")
    claimed_second = store.claim_outbox(now + timedelta(seconds=2), limit=5)
    assert [event.event_id for event in claimed_second] == [second_id]
    store.mark_outbox_retry(second_id, now + timedelta(seconds=3))
    assert store.outbox_state(second_id) == "dead"
    assert len(sink) == 1  # 被抑制


def test_dead_alert_sink_failure_never_breaks_retry_accounting(tmp_path) -> None:
    """J-03：sink 故障只记日志，死信转移与重试记账不受影响。"""

    def broken_sink(issue: OperationalIssue) -> None:
        raise RuntimeError("sink down")

    store = SubscriptionStoreV2(
        str(tmp_path / "subscriptions.sqlite3"),
        outbox_max_attempts=1,
        dead_letter_sink=broken_sink,
    )
    event_id = _seed_target_with_destination(store)
    now = datetime.now(timezone.utc)
    store.claim_outbox(now, limit=5)
    store.mark_outbox_retry(event_id, now + timedelta(seconds=1))  # 不抛
    assert store.outbox_state(event_id) == "dead"


def test_requeue_dead_is_idempotent_and_restores_full_retry_budget(tmp_path) -> None:
    """J-03 ④：requeue_dead 幂等（两次调用不双份），state 回 pending、
    attempts 清零、立即可被 claim，且重获完整重试预算。"""
    store = SubscriptionStoreV2(
        str(tmp_path / "subscriptions.sqlite3"),
        outbox_max_attempts=2,
        dead_letter_sink=lambda issue: None,
    )
    event_id = _seed_target_with_destination(store)
    now = datetime.now(timezone.utc)
    # 两轮失败（attempts 1→2）耗尽预算转 dead。
    store.claim_outbox(now, limit=5)
    store.mark_outbox_retry(event_id, now + timedelta(seconds=1))
    assert store.outbox_state(event_id) == "retry"
    store.claim_outbox(now + timedelta(seconds=1), limit=5)
    store.mark_outbox_retry(event_id, now + timedelta(seconds=2))
    assert store.outbox_state(event_id) == "dead"

    assert store.requeue_dead(event_id, now=now + timedelta(seconds=2)) is True
    assert store.outbox_state(event_id) == "pending"
    with store._lock:
        row = (
            store._get_connection()
            .execute(
                "SELECT attempts, next_attempt_at FROM subscription_outbox WHERE event_id = ?",
                (event_id,),
            )
            .fetchone()
        )
    assert row is not None
    assert int(row["attempts"]) == 0  # attempt 清零

    # 立即可被 claim；再次失败时因预算已重置转 retry 而非 dead。
    claimed = store.claim_outbox(now + timedelta(seconds=3), limit=5)
    assert [event.event_id for event in claimed] == [event_id]
    store.mark_outbox_retry(event_id, now + timedelta(seconds=4))
    assert store.outbox_state(event_id) == "retry"

    # 幂等：对非 dead 行是 no-op，重复调用不产生第二份副作用。
    assert store.requeue_dead(event_id) is False
    assert store.outbox_state(event_id) == "retry"
    assert store.requeue_dead("missing:event") is False

    # async 门面同样可用：再驱动一条事件两轮失败到 dead 后经门面重投。
    second_id = _seed_extra_event(store, "v2")
    store.claim_outbox(now + timedelta(seconds=5), limit=5)
    store.mark_outbox_retry(second_id, now + timedelta(seconds=6))
    store.claim_outbox(now + timedelta(seconds=7), limit=5)
    store.mark_outbox_retry(second_id, now + timedelta(seconds=8))
    assert store.outbox_state(second_id) == "dead"
    assert asyncio.run(store.requeue_dead_async(second_id)) is True
    assert store.outbox_state(second_id) == "pending"
