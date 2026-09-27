"""ATK-SUB-3（S-ATK-SUBSCRIBE）：订阅 outbox `event_id` 裸冒号拼接非单射 ⇒ 静默丢。

复现报告 §ATK-SUB-3 探针 A：三元组 (kind="video", id="a:b") 与 (kind="video:a", id="b")
在 seen 表（三元组主键）判为两个新条目，但拼出的 event_id 逐字节相同 ⇒ 第二条被
`INSERT OR IGNORE` 静默吞掉——永久不推送、不重试、不告警。修法＝event_id 改为对
三元组的规范化单射摘要（json 规范形 + blake2b），任何不同三元组必得不同 event_id。
"""

from __future__ import annotations

from plugins.bot_unified_runtime.contracts import (
    ContentReference,
    SubscriptionFetchResult,
)
from plugins.bot_unified_runtime.domains.subscribe.store.subscription_store_v2 import (
    SubscriptionStoreV2,
)
from tests.test_auditfix_subscriptions_capabilities import _target  # 复用既有夹具


def _outbox_count(store: SubscriptionStoreV2) -> int:
    connection = store._get_connection()
    with connection:
        row = connection.execute("SELECT COUNT(*) FROM subscription_outbox").fetchone()
    return int(row[0])


def test_colliding_triples_get_distinct_outbox_rows(tmp_path) -> None:
    store = SubscriptionStoreV2(str(tmp_path / "subscriptions.sqlite3"))
    target = _target("probe:creator:collide")
    store.upsert_target(target)
    assert store.save_fetch_result(
        target,
        SubscriptionFetchResult(
            items=[ContentReference(item_id="x", item_kind="video", url="u0")]
        ),
        baseline=True,
    ) == []
    first = store.save_fetch_result(
        target,
        SubscriptionFetchResult(
            items=[ContentReference(item_id="a:b", item_kind="video", url="u1")]
        ),
        baseline=False,
    )
    second = store.save_fetch_result(
        target,
        SubscriptionFetchResult(
            items=[ContentReference(item_id="b", item_kind="video:a", url="u2")]
        ),
        baseline=False,
    )
    # 两条都被判为新事件（seen 三元组口径）。
    assert len(first) == 1 and len(second) == 1
    assert first[0].event_id != second[0].event_id, "不同三元组撞了同一个 event_id（静默丢前兆）"
    assert _outbox_count(store) == 2, "outbox 被 OR IGNORE 吞行＝永久静默丢"
    seen = store._get_connection().execute(
        "SELECT COUNT(*) FROM subscription_seen_items"
    ).fetchone()
    assert int(seen[0]) == 3
    store.close()


def test_event_id_is_deterministic_and_single_source(tmp_path) -> None:
    store = SubscriptionStoreV2(str(tmp_path / "subscriptions.sqlite3"))
    target = _target("probe:creator:det")
    store.upsert_target(target)
    store.save_fetch_result(
        target,
        SubscriptionFetchResult(items=[ContentReference(item_id="1", item_kind="video", url="u")]),
        baseline=True,
    )
    events = store.save_fetch_result(
        target,
        SubscriptionFetchResult(items=[ContentReference(item_id="2", item_kind="video", url="v")]),
        baseline=False,
    )
    assert len(events) == 1
    assert events[0].event_id.startswith("sub-")
    assert ":" not in events[0].event_id  # 不再把未校验的远端段直拼进主键
    store.close()
