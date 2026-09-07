from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from plugins.bot_unified_runtime.contracts.subscription import (
    ContentReference,
    SubscriptionFetchResult,
    SubscriptionTarget,
)
from plugins.bot_unified_runtime.sources.subscription_runtime_v2 import (
    build_subscription_runtime_v2,
)


def test_runtime_factory_injects_outbox_delivery_callback(tmp_path) -> None:
    now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    config = type(
        "Config",
        (),
        {
            "bot_subscribe_db_path": str(tmp_path / "subscriptions.sqlite3"),
            "bot_subscribe_global_concurrency": 1,
            "bot_subscribe_platform_concurrency": 1,
            "bot_subscribe_min_interval_seconds": 0,
            "bot_subscribe_lease_seconds": 30,
            "bot_subscribe_retry_base_seconds": 1,
            "bot_subscribe_retry_cap_seconds": 10,
        },
    )()
    received: list[str] = []

    async def deliver(event) -> bool:
        received.append(event.event_id)
        return True

    runtime = build_subscription_runtime_v2(config, delivery_fn=deliver)
    target = SubscriptionTarget(
        id="test:channel:1",
        platform="test",
        target_kind="channel",
        target_key="1",
        baseline_initialized=True,
        created_at=now,
        updated_at=now,
    )
    runtime["store"].upsert_target(target)
    runtime["store"].save_fetch_result(
        target,
        SubscriptionFetchResult(
            items=[ContentReference(item_id="1", item_kind="post", url="https://x/1")]
        ),
        baseline=False,
    )

    assert asyncio.run(runtime["scheduler"].deliver_outbox_once()) == 1
    assert received == ["test:channel:1:post:1"]
    assert runtime["store"].outbox_state("test:channel:1:post:1") == "sent"
    runtime["store"].close()
