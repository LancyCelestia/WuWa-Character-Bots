"""订阅 SQLite 存储测试。

本机系统 TEMP 的 pytest tmp 目录 ACL 损坏，因此不使用 tmp_path，
改为在仓库 data/ 下创建随机临时 sqlite 路径，测试结束自动清理。
"""
from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime

import pytest

from plugins.bot_unified_runtime.contracts.subscription import (
    SubscriptionCursor,
    SubscriptionDestination,
    SubscriptionSpec,
)
from plugins.bot_unified_runtime.sources.subscription_store import SubscriptionStore


def _remove_db_files(path: str) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        candidate = path + suffix
        try:
            os.remove(candidate)
        except FileNotFoundError:
            pass


@pytest.fixture
def db_path():
    path = os.path.join("data", f"test_subscription_store_{uuid.uuid4().hex}.sqlite3")
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


def test_upsert_list_get_delete_roundtrip(db_path):
    store = SubscriptionStore(db_path)
    spec = _make_spec()

    store.upsert_spec(spec)
    assert store.list_specs() == [spec]
    assert store.get_spec(spec.id) == spec
    assert store.get_spec("missing") is None

    assert store.delete_spec(spec.id) is True
    assert store.get_spec(spec.id) is None
    assert store.delete_spec(spec.id) is False
    store.close()


def test_enabled_and_health_updates(db_path):
    store = SubscriptionStore(db_path)
    spec = _make_spec()
    store.upsert_spec(spec)

    assert store.set_spec_enabled(spec.id, False) is True
    assert store.get_spec(spec.id).enabled is False

    store.set_spec_health(spec.id, "degraded", "fetch failed")
    assert store.get_spec(spec.id).health_state == "degraded"

    store.set_spec_enabled(spec.id, True)
    assert store.get_spec(spec.id).enabled is True
    store.close()


def test_destinations_json_roundtrip(db_path):
    store = SubscriptionStore(db_path)
    destinations = [
        SubscriptionDestination(scope="private", target_id="42"),
        SubscriptionDestination(scope="group", target_id="10001"),
    ]
    spec = _make_spec(destinations=destinations)
    store.upsert_spec(spec)

    loaded = store.get_spec(spec.id)
    assert loaded is not None
    assert loaded.destinations == destinations
    assert all(isinstance(item, SubscriptionDestination) for item in loaded.destinations)
    store.close()


def test_mark_pushed_is_idempotent(db_path):
    store = SubscriptionStore(db_path)
    spec = _make_spec()
    store.upsert_spec(spec)

    assert store.already_pushed(spec.id, "item-1", "video") is False
    store.mark_pushed(spec.id, "item-1", "video")
    store.mark_pushed(spec.id, "item-1", "video")
    assert store.already_pushed(spec.id, "item-1", "video") is True

    connection = sqlite3.connect(db_path)
    try:
        count = connection.execute(
            "SELECT COUNT(*) FROM push_log "
            "WHERE spec_id = ? AND item_id = ? AND kind = ?",
            (spec.id, "item-1", "video"),
        ).fetchone()[0]
        row = connection.execute(
            "SELECT pushed_at FROM push_log "
            "WHERE spec_id = ? AND item_id = ? AND kind = ?",
            (spec.id, "item-1", "video"),
        ).fetchone()
    finally:
        connection.close()
    assert count == 1
    assert row is not None and row[0]
    store.close()


def test_digest_pending_write_and_pop(db_path):
    store = SubscriptionStore(db_path)
    spec = _make_spec()
    store.upsert_spec(spec)

    store.add_digest_pending(spec.id, "item-1", "标题一", "https://a.example", "摘要一")
    store.add_digest_pending(spec.id, "item-2", "标题二", "https://b.example", "摘要二")
    # 同一条目重复写入应幂等去重。
    store.add_digest_pending(spec.id, "item-1", "标题一", "https://a.example", "摘要一")

    connection = sqlite3.connect(db_path)
    try:
        count = connection.execute(
            "SELECT COUNT(*) FROM digest_pending WHERE spec_id = ?",
            (spec.id,),
        ).fetchone()[0]
    finally:
        connection.close()
    assert count == 2

    popped = store.pop_digest_pending(spec.id)
    assert {row["item_id"] for row in popped} == {"item-1", "item-2"}
    assert all(row["spec_id"] == spec.id for row in popped)
    assert all(row["title"] for row in popped)
    assert all(row["url"] for row in popped)
    assert store.pop_digest_pending(spec.id) == []
    store.close()


def test_cursor_save_and_get_roundtrip(db_path):
    store = SubscriptionStore(db_path)
    cursor = SubscriptionCursor(
        spec_id="bilibili:user:123",
        last_item_id="latest-id",
        last_timestamp="2026-08-22T00:00:00+00:00",
        cursor_payload={"offset": 3},
        failure_count=2,
        backoff_until=None,
        last_success_at="2026-08-21T00:00:00+00:00",
        last_failure_at="2026-08-20T00:00:00+00:00",
    )

    store.save_cursor(cursor)
    assert store.get_cursor(cursor.spec_id) == cursor
    assert store.get_cursor("missing") is None
    store.close()


def test_record_failure_escalates_backoff(db_path):
    store = SubscriptionStore(db_path)
    spec = _make_spec()
    store.upsert_spec(spec)

    store.record_failure(spec.id, backoff_seconds=600)
    spec_after_first = store.get_spec(spec.id)
    cursor_after_first = store.get_cursor(spec.id)
    assert spec_after_first.failure_count == 1
    assert cursor_after_first.failure_count == 1
    assert cursor_after_first.last_failure_at
    first_backoff = datetime.fromisoformat(cursor_after_first.backoff_until)

    store.record_failure(spec.id, backoff_seconds=1200)
    spec_after_second = store.get_spec(spec.id)
    cursor_after_second = store.get_cursor(spec.id)
    assert spec_after_second.failure_count == 2
    assert cursor_after_second.failure_count == 2
    second_backoff = datetime.fromisoformat(cursor_after_second.backoff_until)
    assert second_backoff > first_backoff
    store.close()
