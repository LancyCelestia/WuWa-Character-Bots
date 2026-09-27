"""SUB-2（S-ATK-SUBSCRIBE ATK-SUB-1）：投递台账必须**逐目的地**落笔。

旧契约：`_deliver_v2_event` 返回单个 bool（`sent_any and all_success`），scheduler 只在
`if success:` 时把**全部**启用目的地一次性写进台账 ⇒ 10002 那个群一失败，10001 已经
收到的群**没有台账**，整事件转 retry 后每轮再推一遍（最多 5 遍＝双发实锤，审计探针
CONFIRMED 逐字在 log）。

本锁的四条腿：
- 逐目地语义：delivery_fn 交回 `[(key, ok), ...]` ⇒ 只有 ok 的落台账，事件判据＝
  「无未覆盖目的地」（与查重口 `outbox_undelivered_destinations` 闭环）；
- 全成：列表全 True ⇒ 直接 sent；
- **向后兼容**：仍交回裸 bool 的旧实现不得瞬断（根腿未改前生产就是这条形态）；
- register 透传：`register_subscription_runtime_v2` 必须把 `dead_letter_sink` 递给
  构造口（`29f2cf6` 已把 build/store 侧备好，就差 register 这两行）。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from plugins.bot_unified_runtime.domains.core.contracts.subscription import (
    ContentReference,
    SubscriptionDestinationV2,
    SubscriptionFetchResult,
    SubscriptionTarget,
)
from plugins.bot_unified_runtime.domains.subscribe.store.subscription_runtime_v2 import (
    register_subscription_runtime_v2,
)
from plugins.bot_unified_runtime.domains.subscribe.store.subscription_scheduler import (
    SubscriptionScheduler,
)
from plugins.bot_unified_runtime.domains.subscribe.store.subscription_store_v2 import (
    SubscriptionStoreV2,
    _event_id_for,
)

_NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def _runtime(tmp_path, make_fn: Any) -> tuple[SubscriptionStoreV2, str]:
    """建 订阅目标＋两枚启用目的地＋一条 outbox 事件，跑一轮投递。

    `make_fn(keys)` 收**真实目的地键**（行主键由库自增分配，测试不许自己编 id，
    否则查重口永远对不上＝假红）。
    """
    store = SubscriptionStoreV2(str(tmp_path / "subs.sqlite3"))
    target = SubscriptionTarget(
        id="t:channel:1",
        platform="t",
        target_kind="channel",
        target_key="1",
        baseline_initialized=True,
        created_at=_NOW,
        updated_at=_NOW,
    )
    store.upsert_target(target)
    for slot in ("one", "two"):
        store.add_destination(
            SubscriptionDestinationV2(
                target_id=target.id,
                transport="onebot",
                scope="group",
                destination_id=f"g-{slot}",
                enabled=True,
            )
        )
    keys = [d.id for d in store.list_destinations(target.id) if d.enabled]
    assert len(keys) == 2, f"目的地行没建起来（{keys}）＝夹具失效"
    store.save_fetch_result(
        target,
        SubscriptionFetchResult(
            items=[ContentReference(item_id="v1", item_kind="video", url="https://x/v1")]
        ),
        baseline=False,
    )
    scheduler = SubscriptionScheduler(store, [], delivery_fn=make_fn(keys))
    asyncio.run(scheduler.deliver_outbox_once())
    return store, _event_id_for(target.id, "video", "v1")


def _keys_of(store: SubscriptionStoreV2) -> list[str]:
    return [d.id for d in store.list_destinations("t:channel:1") if d.enabled]


class _StubScheduler:
    """只接 `add_job` 的调度器替身（register 会挂两个 job）。"""

    def __init__(self) -> None:
        self.jobs: list[str] = []

    def add_job(self, _fn: Any, *_a: Any, id: str = "", **_kw: Any) -> None:
        self.jobs.append(id)

    def shutdown(self, *_a: Any, **_kw: Any) -> None:
        return None


def test_partial_success_writes_ledger_only_for_delivered(tmp_path) -> None:
    """一半成功一半失败：已送达那半**必须**当场落账，事件不得整体判成已发。"""
    seen: list[str] = []

    def make(keys: list[str]):
        async def deliver(event) -> list[tuple[str, bool]]:
            seen.append(event.event_id)
            return [(keys[0], True), (keys[1], False)]

        return deliver

    store, event_id = _runtime(tmp_path, make)
    keys = _keys_of(store)
    assert seen, "delivery_fn 根本没被调用＝锁空跑"
    assert store.outbox_state(event_id) == "retry", (
        f"仍有未覆盖目的地却判成 {store.outbox_state(event_id)}"
    )
    assert store.outbox_undelivered_destinations(event_id, keys) == [keys[1]], (
        "逐目的地台账没落：已成功的目的地也没记账 ⇒ 下一轮双发"
    )


def test_full_list_success_marks_sent(tmp_path) -> None:
    def make(keys: list[str]):
        async def deliver(event) -> list[tuple[str, bool]]:
            return [(k, True) for k in keys]

        return deliver

    store, event_id = _runtime(tmp_path, make)
    assert store.outbox_state(event_id) == "sent"
    assert store.outbox_undelivered_destinations(event_id, _keys_of(store)) == []


def test_legacy_bool_contract_still_works(tmp_path) -> None:
    """兼容腿：旧实现返回裸 True ⇒ 语义与既往逐字节同（全量落账＋sent）。"""

    def make(keys: list[str]):
        async def deliver(event) -> bool:
            return True

        return deliver

    store, event_id = _runtime(tmp_path, make)
    assert store.outbox_state(event_id) == "sent"
    assert store.outbox_undelivered_destinations(event_id, _keys_of(store)) == []


def test_legacy_bool_false_retries_without_ledger(tmp_path) -> None:
    def make(keys: list[str]):
        async def deliver(event) -> bool:
            return False

        return deliver

    store, event_id = _runtime(tmp_path, make)
    assert store.outbox_state(event_id) == "retry"
    assert store.outbox_undelivered_destinations(event_id, _keys_of(store)) == _keys_of(store)


def test_register_threads_dead_letter_sink_to_store(tmp_path) -> None:
    """register 侧两行没接：`29f2cf6` 把 build/store 备好了，装配现场仍拿不到 sink。"""
    captured: list[Any] = []
    config = type(
        "Config",
        (),
        {
            "bot_subscribe_db_path": str(tmp_path / "reg.sqlite3"),
            "bot_subscribe_poll_interval_seconds": 300,
            "bot_subscribe_outbox_interval_seconds": 15,
        },
    )()
    runtime = register_subscription_runtime_v2(
        scheduler=_StubScheduler(),
        config=config,
        context_factory=lambda platform: {},
        dead_letter_sink=captured.append,
    )
    sink = runtime["store"]._dead_letter_sink
    assert callable(sink), "sink 没透传到 store（register 少两行 ⇒ 死信永远只有 WARNING）"
    sink("probe-issue")
    assert captured == ["probe-issue"], "接了但不通气"
