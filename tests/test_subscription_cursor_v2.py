from __future__ import annotations

from datetime import datetime, timezone

from plugins.bot_unified_runtime.contracts.subscription import (
    SubscriptionCursorV2,
    SubscriptionFetchResult,
    SubscriptionTarget,
)
from plugins.bot_unified_runtime.sources.subscription_store_v2 import (
    SubscriptionStoreV2,
)


def test_v2_store_round_trips_v2_cursor_with_timezone(tmp_path) -> None:
    now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    store = SubscriptionStoreV2(str(tmp_path / "subscriptions.sqlite3"))
    target = SubscriptionTarget(
        id="youtube:channel:UC1",
        platform="youtube",
        target_kind="channel",
        target_key="UC1",
        created_at=now,
        updated_at=now,
    )
    store.upsert_target(target)
    cursor = SubscriptionCursorV2(
        target_id=target.id,
        stream="channel",
        last_item_id="v1",
        last_timestamp=now,
        updated_at=now,
    )
    store.save_fetch_result(
        target,
        SubscriptionFetchResult(cursors=[cursor]),
        baseline=True,
    )
    restored = store.get_cursors(target.id)
    assert isinstance(restored["channel"], SubscriptionCursorV2)
    assert restored["channel"].last_item_id == "v1"
    assert restored["channel"].last_timestamp == now
