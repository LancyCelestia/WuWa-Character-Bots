from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from plugins.bot_unified_runtime.contracts.subscription import (
    ContentReference,
    SubscriptionFetchResult,
    SubscriptionTarget,
)
from plugins.bot_unified_runtime.sources.subscription_scheduler import (
    SubscriptionScheduler,
)
from plugins.bot_unified_runtime.sources.subscription_store_v2 import (
    SubscriptionStoreV2,
)

_NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def _store_with_event(tmp_path) -> SubscriptionStoreV2:
    store = SubscriptionStoreV2(str(tmp_path / "subscriptions.sqlite3"))
    target = SubscriptionTarget(
        id="test:channel:1",
        platform="test",
        target_kind="channel",
        target_key="1",
        baseline_initialized=True,
        created_at=_NOW,
        updated_at=_NOW,
    )
    store.upsert_target(target)
    store.save_fetch_result(
        target,
        SubscriptionFetchResult(
            items=[ContentReference(item_id="v1", item_kind="video", url="https://x/v1")]
        ),
        baseline=False,
    )
    return store


def test_outbox_without_delivery_callback_is_not_marked_sent(tmp_path) -> None:
    store = _store_with_event(tmp_path)
    scheduler = SubscriptionScheduler(store, [])

    assert asyncio.run(scheduler.deliver_outbox_once()) == 0
    row = store.outbox_state("test:channel:1:video:v1")
    assert row == "retry"


def test_outbox_is_marked_sent_only_after_callback_success(tmp_path) -> None:
    store = _store_with_event(tmp_path)
    delivered: list[str] = []

    async def deliver(event) -> bool:
        delivered.append(event.event_id)
        return True

    scheduler = SubscriptionScheduler(store, [], delivery_fn=deliver)
    assert asyncio.run(scheduler.deliver_outbox_once()) == 1
    assert delivered == ["test:channel:1:video:v1"]
    assert store.outbox_state("test:channel:1:video:v1") == "sent"
