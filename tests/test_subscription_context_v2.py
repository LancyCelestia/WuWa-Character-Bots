from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from plugins.bot_unified_runtime.contracts.subscription import (
    SubscriptionFetchResult,
    SubscriptionTarget,
)
from plugins.bot_unified_runtime.sources.subscription_scheduler import (
    SubscriptionScheduler,
)
from plugins.bot_unified_runtime.sources.subscription_store_v2 import (
    SubscriptionStoreV2,
)


class _ContextAdapter:
    platform = "test"
    target_kinds = frozenset({"channel"})

    def __init__(self) -> None:
        self.context = None

    async def fetch_incremental(self, target, cursors, context):
        self.context = context
        return SubscriptionFetchResult()


def test_scheduler_passes_platform_context_to_adapter(tmp_path) -> None:
    now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    store = SubscriptionStoreV2(str(tmp_path / "subscriptions.sqlite3"))
    target = SubscriptionTarget(
        id="test:channel:1",
        platform="test",
        target_kind="channel",
        target_key="1",
        next_poll_at=now,
        created_at=now,
        updated_at=now,
    )
    store.upsert_target(target)
    adapter = _ContextAdapter()
    scheduler = SubscriptionScheduler(
        store,
        [adapter],
        context_factory=lambda platform: {
            "cookie_header": "cookie-value",
            "proxy": "http://proxy",
            "timeout_seconds": 7,
        },
        clock=lambda: now,
    )

    asyncio.run(scheduler.poll_due_once(now=now))

    assert adapter.context == {
        "cookie_header": "cookie-value",
        "proxy": "http://proxy",
        "timeout_seconds": 7,
        "now": now,
    }
