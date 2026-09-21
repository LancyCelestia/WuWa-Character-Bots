"""B8：订阅目标显式运行期元数据（如 X rest_id）落库回归。

- 存储层：subscription_target_metadata 键级 upsert / 读取 / 级联删除，
  重启（新 store 实例）后可读；
- 调度层：adapter 在 fetch 中注入 target.payload 的元数据落库，
  下一轮回灌给 adapter；失败轮不落库。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from plugins.bot_unified_runtime.domains.core.contracts.subscription import (
    ContentReference,
    SubscriptionFetchResult,
    SubscriptionTarget,
)
from plugins.bot_unified_runtime.domains.subscribe.store.subscription_scheduler import (
    SubscriptionScheduler,
)
from plugins.bot_unified_runtime.domains.subscribe.store.subscription_store_v2 import (
    SubscriptionStoreV2,
)

_NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)


def _target(*, payload: dict[str, Any] | None = None) -> SubscriptionTarget:
    return SubscriptionTarget(
        id="twitter:user:shk",
        platform="twitter",
        target_kind="user",
        target_key="shk",
        target_payload=payload or {},
        base_interval_seconds=300,
        jitter_ratio=0.0,
        next_poll_at=_NOW,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _upsert_target_for(store: SubscriptionStoreV2, target_id: str) -> None:
    """元数据表对 subscription_targets 有 FK 约束：写元数据前先落目标行。"""
    store.upsert_target(_target().model_copy(update={"id": target_id}))


# ==================== 存储层 ====================


def test_metadata_roundtrip_and_key_level_upsert(tmp_path) -> None:
    store = SubscriptionStoreV2(str(tmp_path / "subscriptions.sqlite3"))
    _upsert_target_for(store, "twitter:user:shk")
    assert store.get_target_metadata("twitter:user:shk") == {}

    store.set_target_metadata("twitter:user:shk", {"rest_id": "123"})
    store.set_target_metadata("twitter:user:shk", {"rest_id": "456", "tier": "gold"})

    assert store.get_target_metadata("twitter:user:shk") == {
        "rest_id": "456",
        "tier": "gold",
    }


def test_metadata_preserves_json_value_types(tmp_path) -> None:
    store = SubscriptionStoreV2(str(tmp_path / "subscriptions.sqlite3"))
    _upsert_target_for(store, "t:1")
    payload = {"count": 3, "flags": [1, "a"], "nested": {"k": True}}
    store.set_target_metadata("t:1", payload)
    assert store.get_target_metadata("t:1") == payload


def test_metadata_empty_dict_is_noop(tmp_path) -> None:
    store = SubscriptionStoreV2(str(tmp_path / "subscriptions.sqlite3"))
    store.set_target_metadata("t:1", {})
    assert store.get_target_metadata("t:1") == {}


def test_metadata_cascades_on_target_delete(tmp_path) -> None:
    store = SubscriptionStoreV2(str(tmp_path / "subscriptions.sqlite3"))
    store.upsert_target(_target())
    store.set_target_metadata("twitter:user:shk", {"rest_id": "123"})
    assert store.delete_target("twitter:user:shk") is True
    assert store.get_target_metadata("twitter:user:shk") == {}


def test_metadata_survives_store_restart(tmp_path) -> None:
    db_path = str(tmp_path / "subscriptions.sqlite3")
    first = SubscriptionStoreV2(db_path)
    first.upsert_target(_target())
    first.set_target_metadata("twitter:user:shk", {"rest_id": "123"})
    first.close()

    second = SubscriptionStoreV2(db_path)
    try:
        assert second.get_target_metadata("twitter:user:shk") == {"rest_id": "123"}
    finally:
        second.close()


# ==================== 调度层：落库与回灌 ====================


class _RestIdAdapter:
    """模拟 X adapter：首轮解析出 rest_id 注入 payload，之后只读。"""

    platform = "twitter"
    target_kinds = frozenset({"user"})

    def __init__(self) -> None:
        self.calls = 0
        self.seen_payloads: list[dict[str, Any]] = []
        self.fail_next = False

    async def fetch_incremental(self, target, cursors, context):
        self.calls += 1
        self.seen_payloads.append(dict(target.target_payload))
        if self.fail_next:
            return SubscriptionFetchResult(
                health_state="degraded",
                error_code="network_error",
                retryable=True,
            )
        if "rest_id" not in target.target_payload:
            target.target_payload["rest_id"] = "999"
        return SubscriptionFetchResult(
            items=[
                ContentReference(
                    item_id=f"tweet-{self.calls}",
                    item_kind="tweet",
                    url="https://x.com/shk/status/1",
                )
            ],
        )


def _make_scheduler(store: SubscriptionStoreV2, adapter: _RestIdAdapter):
    return SubscriptionScheduler(
        store,
        [adapter],
        random_fn=lambda: 0.5,
        clock=lambda: _NOW,
    )


def test_scheduler_persists_metadata_injected_by_adapter(tmp_path) -> None:
    store = SubscriptionStoreV2(str(tmp_path / "subscriptions.sqlite3"))
    store.upsert_target(_target())
    adapter = _RestIdAdapter()
    scheduler = _make_scheduler(store, adapter)

    assert asyncio.run(scheduler.poll_due_once(now=_NOW)) == []
    assert store.get_target_metadata("twitter:user:shk") == {"rest_id": "999"}


def test_scheduler_feeds_metadata_back_on_next_poll(tmp_path) -> None:
    store = SubscriptionStoreV2(str(tmp_path / "subscriptions.sqlite3"))
    store.upsert_target(_target())
    adapter = _RestIdAdapter()
    scheduler = _make_scheduler(store, adapter)

    asyncio.run(scheduler.poll_due_once(now=_NOW))
    # 下一轮：adapter 收到的 payload 应含回灌的 rest_id（模拟重启后首轮）。
    baselined = store.get_target("twitter:user:shk")
    assert baselined is not None
    store.upsert_target(baselined.model_copy(update={"next_poll_at": _NOW}))
    asyncio.run(scheduler.poll_due_once(now=_NOW))

    assert adapter.seen_payloads[1].get("rest_id") == "999"
    # 元数据稳定后不再变化。
    assert store.get_target_metadata("twitter:user:shk") == {"rest_id": "999"}


def test_scheduler_does_not_persist_metadata_on_failed_poll(tmp_path) -> None:
    store = SubscriptionStoreV2(str(tmp_path / "subscriptions.sqlite3"))
    store.upsert_target(_target())
    adapter = _RestIdAdapter()
    adapter.fail_next = True
    scheduler = _make_scheduler(store, adapter)

    asyncio.run(scheduler.poll_due_once(now=_NOW))

    assert store.get_target_metadata("twitter:user:shk") == {}
