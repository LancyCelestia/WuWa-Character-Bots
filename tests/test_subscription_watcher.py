"""订阅 watcher 测试：假 adapter，全程不发网络。

同样不用 pytest tmp_path，改用 data/ 下随机 sqlite 路径。
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import uuid

import pytest

from plugins.bot_unified_runtime.contracts.subscription import (
    NormalizedSubscriptionItem,
    PushCandidate,
    SourceFetchResult,
    SubscriptionCursor,
    SubscriptionDestination,
    SubscriptionSpec,
)
from plugins.bot_unified_runtime.sources.subscription_store import SubscriptionStore
from plugins.bot_unified_runtime.sources.subscription_watcher import (
    build_subscription_watcher,
)


def _remove_db_files(path: str) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        candidate = path + suffix
        try:
            os.remove(candidate)
        except FileNotFoundError:
            pass


@pytest.fixture
def db_path():
    path = os.path.join("data", f"test_subscription_watcher_{uuid.uuid4().hex}.sqlite3")
    try:
        yield path
    finally:
        _remove_db_files(path)


def _make_spec(**overrides):
    values = {
        "id": "bilibili:user:123",
        "platform": "bilibili",
        "target_kind": "user",
        "target_id": "123",
        "target_name": "测试UP",
        "destinations": [SubscriptionDestination(scope="private", target_id="42")],
        "created_by": "42",
    }
    values.update(overrides)
    return SubscriptionSpec(**values)


def _make_item(item_id: str, title: str, *, kind: str = "video") -> NormalizedSubscriptionItem:
    return NormalizedSubscriptionItem(
        item_id=item_id,
        kind=kind,
        title=title,
        url=f"https://example.com/{item_id}",
        published_at="2026-08-22T00:00:00+00:00",
    )


class FakeAdapter:
    platform = "bilibili"
    target_kinds = ("user",)
    LIVE_POLL = False

    def __init__(self, items=(), live_candidates=()):
        self.items = list(items)
        self.live_candidates = list(live_candidates)
        self.fetch_calls = 0
        self.contexts = []
        self.live_specs = None

    def resolve_target(self, url: str) -> dict:
        return {
            "platform": self.platform,
            "target_kind": self.target_kinds[0],
            "target_id": url.rsplit("/", 1)[-1],
            "target_name": "测试UP",
        }

    async def fetch_latest(self, spec, cursor, ctx):
        self.fetch_calls += 1
        self.contexts.append((spec.platform, ctx))
        last_item_id = self.items[-1].item_id if self.items else ""
        return SourceFetchResult(
            items=[*self.items],
            new_cursor=SubscriptionCursor(
                spec_id=spec.id,
                last_item_id=last_item_id,
                last_success_at="2026-08-22T01:00:00+00:00",
            ),
            health_state="healthy",
            error="",
        )

    async def fetch_live_statuses(self, specs, ctx):
        self.live_specs = list(specs)
        self.contexts.append(("live", ctx))
        return [*self.live_candidates]


class FailingAdapter(FakeAdapter):
    async def fetch_latest(self, spec, cursor, ctx):
        self.fetch_calls += 1
        raise RuntimeError("boom")


def _ctx_factory(platform: str = "") -> dict:
    return {"cookie_header": f"cookie-{platform}", "proxy": "http://127.0.0.1:7890"}


def test_tick_emits_new_items_then_deduplicates(db_path):
    store = SubscriptionStore(db_path)
    spec = _make_spec()
    store.upsert_spec(spec)
    adapter = FakeAdapter([_make_item("item-a", "视频A"), _make_item("item-b", "视频B")])
    watcher = build_subscription_watcher(store, [adapter], _ctx_factory)

    first = asyncio.run(watcher.tick())
    assert [candidate.item.item_id for candidate in first] == ["item-a", "item-b"]
    assert all(candidate.reason == "new_item" for candidate in first)
    assert all(candidate.spec_id == spec.id for candidate in first)

    second = asyncio.run(watcher.tick())
    assert second == []
    assert adapter.fetch_calls == 2
    assert [platform for platform, _ctx in adapter.contexts] == ["bilibili", "bilibili"]
    assert adapter.contexts[0][1]["cookie_header"] == "cookie-bilibili"
    assert adapter.contexts[0][1]["proxy"] == "http://127.0.0.1:7890"

    cursor = store.get_cursor(spec.id)
    assert cursor.last_item_id == "item-b"
    store.close()


def test_tick_records_failure_and_respects_backoff(db_path):
    store = SubscriptionStore(db_path)
    spec = _make_spec()
    store.upsert_spec(spec)
    adapter = FailingAdapter()
    watcher = build_subscription_watcher(store, [adapter], _ctx_factory)

    assert asyncio.run(watcher.tick()) == []
    assert store.get_spec(spec.id).failure_count == 1

    # 第一次退避 600*1 秒，第二次 tick 会执行并再次失败，退避升级。
    assert asyncio.run(watcher.tick()) == []
    after_second = store.get_spec(spec.id)
    assert after_second.failure_count == 2
    assert after_second.backoff_until is not None

    # 退避期内 watcher 不再调用 adapter。
    assert asyncio.run(watcher.tick()) == []
    assert adapter.fetch_calls == 2

    cursor = store.get_cursor(spec.id)
    assert cursor.failure_count == 2
    assert cursor.last_failure_at
    store.close()


def test_digest_spec_defers_until_flush(db_path):
    store = SubscriptionStore(db_path)
    spec = _make_spec(digest_enabled=True)
    store.upsert_spec(spec)
    adapter = FakeAdapter([_make_item("item-d", "标题一")])
    watcher = build_subscription_watcher(store, [adapter], _ctx_factory)

    # 日报订阅不产即时候选，且条目已去重标记，避免重复进入日报。
    assert asyncio.run(watcher.tick()) == []
    assert asyncio.run(watcher.tick()) == []
    connection = sqlite3.connect(db_path)
    try:
        count = connection.execute(
            "SELECT COUNT(*) FROM digest_pending WHERE spec_id = ?", (spec.id,)
        ).fetchone()[0]
    finally:
        connection.close()
    assert count == 1

    flushed = asyncio.run(watcher.flush_digests())
    assert len(flushed) == 1
    candidate = flushed[0]
    assert candidate.spec_id == spec.id
    assert candidate.reason == "digest_due"
    assert candidate.item.item_id.startswith("digest-")
    assert candidate.item.title == "测试UP 订阅日报"
    assert "《标题一》" in candidate.item.summary
    assert "https://example.com/item-d" in candidate.item.summary

    assert asyncio.run(watcher.flush_digests()) == []
    connection = sqlite3.connect(db_path)
    try:
        count = connection.execute(
            "SELECT COUNT(*) FROM digest_pending WHERE spec_id = ?", (spec.id,)
        ).fetchone()[0]
    finally:
        connection.close()
    assert count == 0
    store.close()


def test_live_tick_calls_live_adapter_with_its_specs(db_path):
    store = SubscriptionStore(db_path)
    store.upsert_spec(_make_spec(id="bilibili:user:1", target_id="1"))
    store.upsert_spec(_make_spec(id="bilibili:user:2", target_id="2"))
    candidate = PushCandidate(
        spec_id="bilibili:user:1",
        item=_make_item("live-1", "开播了", kind="live"),
        reason="live_started",
    )
    adapter = FakeAdapter(live_candidates=[candidate])
    adapter.LIVE_POLL = True
    watcher = build_subscription_watcher(store, [adapter], _ctx_factory)

    candidates = asyncio.run(watcher.live_tick())
    assert candidates == [candidate]
    assert [spec.id for spec in adapter.live_specs] == [
        "bilibili:user:1",
        "bilibili:user:2",
    ]
    store.close()
