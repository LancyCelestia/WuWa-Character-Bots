from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from plugins.bot_unified_runtime.contracts.subscription import (
    ContentReference,
    SubscriptionFetchResult,
    SubscriptionTarget,
)
from plugins.bot_unified_runtime.sources.subscription_migration import (
    prepare_subscription_database,
)
from plugins.bot_unified_runtime.sources.subscription_store_v2 import (
    SubscriptionStoreV2,
)


def _target(now: datetime, *, baseline: bool = False) -> SubscriptionTarget:
    return SubscriptionTarget(
        id="youtube:channel:UC1",
        platform="youtube",
        target_kind="channel",
        target_key="UC1",
        baseline_initialized=baseline,
        next_poll_at=now,
        created_at=now,
        updated_at=now,
    )


def test_old_subscription_database_is_renamed_without_overwriting_backup(tmp_path) -> None:
    primary = tmp_path / "subscriptions.sqlite3"
    backup = tmp_path / "subscriptions_old.sqlite3"
    connection = sqlite3.connect(primary)
    connection.execute("CREATE TABLE subscriptions(id TEXT)")
    connection.commit()
    connection.close()

    assert prepare_subscription_database(str(primary)) == str(primary)
    assert backup.exists()
    assert primary.exists()


def test_existing_old_backup_stops_without_mutating_either_file(tmp_path) -> None:
    primary = tmp_path / "subscriptions.sqlite3"
    backup = tmp_path / "subscriptions_old.sqlite3"
    connection = sqlite3.connect(primary)
    connection.execute("CREATE TABLE subscriptions(id TEXT)")
    connection.commit()
    connection.close()
    backup.write_bytes(b"preserve")

    with pytest.raises(RuntimeError, match="subscriptions_old.sqlite3"):
        prepare_subscription_database(str(primary))
    assert primary.exists()
    assert backup.read_bytes() == b"preserve"


def test_v2_store_deduplicates_seen_items_and_outbox(tmp_path) -> None:
    now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    store = SubscriptionStoreV2(str(tmp_path / "subscriptions.sqlite3"))
    target = _target(now, baseline=True)
    store.upsert_target(target)
    result = SubscriptionFetchResult(
        items=[ContentReference(item_id="v1", item_kind="video", url="https://youtu.be/v1")]
    )

    first = store.save_fetch_result(target, result, baseline=False)
    second = store.save_fetch_result(target, result, baseline=False)

    assert len(first) == 1
    assert second == []


def test_v2_store_baseline_does_not_emit_outbox(tmp_path) -> None:
    now = datetime.now(timezone.utc)
    store = SubscriptionStoreV2(str(tmp_path / "subscriptions.sqlite3"))
    target = _target(now, baseline=False)
    store.upsert_target(target)
    result = SubscriptionFetchResult(
        items=[ContentReference(item_id="v1", item_kind="video", url="https://youtu.be/v1")]
    )

    assert store.save_fetch_result(target, result, baseline=True) == []
    saved = store.get_target(target.id)
    assert saved is not None
    assert saved.baseline_initialized is True
