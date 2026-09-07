from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from plugins.bot_unified_runtime.contracts import (
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
from plugins.bot_unified_runtime.sources.subscriptions.music_v2 import (
    MusicSubscriptionAdapterV2,
)


class _NetEaseClient:
    async def fetch_incremental(self, target, cursors, context):
        return SubscriptionFetchResult(
            items=[
                ContentReference(
                    item_id="song-1",
                    item_kind="music_track",
                    url="https://music.163.com/song?id=song-1",
                )
            ]
        )


def test_music_provider_target_is_routed_to_music_adapter(tmp_path) -> None:
    now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    store = SubscriptionStoreV2(str(tmp_path / "subscriptions.sqlite3"))
    target = SubscriptionTarget(
        id="netease:playlist:1",
        platform="netease",
        target_kind="playlist",
        target_key="1",
        baseline_initialized=True,
        next_poll_at=now,
        created_at=now,
        updated_at=now,
    )
    store.upsert_target(target)
    adapter = MusicSubscriptionAdapterV2(clients={"netease": _NetEaseClient()})
    scheduler = SubscriptionScheduler(store, [adapter], clock=lambda: now)

    events = asyncio.run(scheduler.poll_due_once(now=now))

    assert len(events) == 1
    assert events[0].item.item_id == "song-1"
