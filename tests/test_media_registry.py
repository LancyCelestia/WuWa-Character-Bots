"""媒体档案库（media_registry）回归：注册复用、反查、TTL/FIFO 剪枝。

锁定“媒体记忆缺失不阻断聊天”的存储语义：写路径失败吞掉、读路径未命中 None；
时间字段全部显式构造（不 mock 时钟）驱动窗口与剪枝断言。
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.character.media_registry import (
    MediaAssetRecord,
    SQLiteMediaRegistry,
    build_media_registry,
)


def _record(**overrides: object) -> MediaAssetRecord:
    base: dict[str, object] = {
        "media_id": "",
        "chat_message_id": "m-1",
        "session_id": "session-a",
        "source_kind": "bot_sent",
        "platform": "bilibili",
        "item_id": "BV1xx",
        "canonical_url": "https://b23.tv/BV1xx",
        "title": "标题",
        "creator_name": "UP 主",
        "duration_ms": 90_000,
        "local_path": "C:/media/a.mp4",
        "subtitle_text": "CC 字幕",
        "brief_text": "",
        "brief_signals": "",
    }
    base.update(overrides)
    return MediaAssetRecord(**base)  # type: ignore[arg-type]


def _last_accessed(db_path: Path, media_id: str) -> int:
    connection = sqlite3.connect(str(db_path))
    try:
        row = connection.execute(
            "SELECT last_accessed_at FROM media_assets WHERE media_id = ?",
            (media_id,),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    return int(row[0])


def test_register_roundtrip_full_fields(tmp_path: Path) -> None:
    now = int(time.time())
    registry = SQLiteMediaRegistry(tmp_path / "registry.sqlite3")
    record = _record(created_at=now - 10, last_accessed_at=now - 5)
    media_id = registry.register(record)
    assert media_id
    loaded = registry.lookup_by_message_id("m-1")
    assert loaded == record.model_copy(update={"media_id": media_id})
    # duration_ms 为 None 也要能完整存取。
    registry.register(
        _record(
            chat_message_id="m-2",
            duration_ms=None,
            created_at=now,
            last_accessed_at=now,
        )
    )
    loaded_none = registry.lookup_by_message_id("m-2")
    assert loaded_none is not None
    assert loaded_none.duration_ms is None
    registry.close()


def test_register_duplicate_updates_in_place_and_reuses_media_id(
    tmp_path: Path,
) -> None:
    now = int(time.time())
    db_path = tmp_path / "registry.sqlite3"
    registry = SQLiteMediaRegistry(db_path)
    first_id = registry.register(
        _record(title="原标题", duration_ms=None, created_at=now - 60, last_accessed_at=now - 60)
    )
    # 同 (chat_message_id, session_id) 再次注册：原位更新，media_id 复用。
    second_id = registry.register(
        _record(
            title="",
            local_path="C:/media/b.mp4",
            subtitle_text="新字幕",
            duration_ms=12_345,
            created_at=now,
            last_accessed_at=now,
        )
    )
    assert second_id == first_id
    loaded = registry.lookup_by_message_id("m-1")
    assert loaded is not None
    assert loaded.title == "原标题"  # 空字段不覆盖既有值
    assert loaded.local_path == "C:/media/b.mp4"
    assert loaded.subtitle_text == "新字幕"
    assert loaded.duration_ms == 12_345  # 非 None 才覆盖
    connection = sqlite3.connect(str(db_path))
    try:
        (count,) = connection.execute(
            "SELECT COUNT(*) FROM media_assets"
        ).fetchone()
    finally:
        connection.close()
    assert count == 1
    registry.close()


def test_lookup_by_message_id_miss_returns_none(tmp_path: Path) -> None:
    registry = SQLiteMediaRegistry(tmp_path / "registry.sqlite3")
    assert registry.lookup_by_message_id("missing") is None
    registry.register(_record())
    assert registry.lookup_by_message_id("other-message") is None
    registry.close()


def test_lookup_recent_in_session_window_latest_and_isolation(
    tmp_path: Path,
) -> None:
    now = int(time.time())
    registry = SQLiteMediaRegistry(tmp_path / "registry.sqlite3")
    registry.register(
        _record(chat_message_id="old", created_at=now - 100, last_accessed_at=now - 100)
    )
    registry.register(
        _record(chat_message_id="new", created_at=now - 10, last_accessed_at=now - 10)
    )
    registry.register(
        _record(
            chat_message_id="other-session",
            session_id="session-b",
            created_at=now - 5,
            last_accessed_at=now - 5,
        )
    )
    # 窗口放宽时取该会话 created_at 最新的一条。
    wide = registry.lookup_recent_in_session("session-a", within_seconds=200)
    assert wide is not None
    assert wide.chat_message_id == "new"
    # 收窄窗口：now-10 在 50s 内、now-100 在外。
    inside = registry.lookup_recent_in_session("session-a", within_seconds=50)
    assert inside is not None
    assert inside.chat_message_id == "new"
    # 窗口外不算。
    assert registry.lookup_recent_in_session("session-a", within_seconds=5) is None
    # 跨会话隔离：查不到别会话的，也查不到不存在的会话。
    other = registry.lookup_recent_in_session("session-b", within_seconds=50)
    assert other is not None
    assert other.chat_message_id == "other-session"
    assert registry.lookup_recent_in_session("session-c", within_seconds=1000) is None
    registry.close()


def test_lookup_hit_and_touch_refresh_last_accessed(tmp_path: Path) -> None:
    now = int(time.time())
    db_path = tmp_path / "registry.sqlite3"
    registry = SQLiteMediaRegistry(db_path)
    media_id = registry.register(
        _record(created_at=now - 30, last_accessed_at=now - 30)
    )
    registry.lookup_by_message_id("m-1")  # 命中即 touch
    assert _last_accessed(db_path, media_id) >= now
    registry.touch(media_id)
    assert _last_accessed(db_path, media_id) >= now
    registry.touch("no-such-id")  # 未命中不报错
    registry.close()


def test_update_brief_persists(tmp_path: Path) -> None:
    registry = SQLiteMediaRegistry(tmp_path / "registry.sqlite3")
    media_id = registry.register(_record())
    registry.update_brief(media_id, "感知简报文本", '{"frames": true, "asr": false}')
    loaded = registry.lookup_by_message_id("m-1")
    assert loaded is not None
    assert loaded.brief_text == "感知简报文本"
    assert loaded.brief_signals == '{"frames": true, "asr": false}'
    registry.update_brief("no-such-id", "x", "{}")  # 未命中不报错
    registry.close()


def test_prune_ttl_expires_stale_rows(tmp_path: Path) -> None:
    now = int(time.time())
    registry = SQLiteMediaRegistry(tmp_path / "registry.sqlite3", ttl_seconds=1000)
    # last_accessed_at 显式构造为“注册时还新鲜、剪枝时刻已过期”的旧值，
    # 避免写入瞬间的顺带剪枝先把它删掉（不 mock 时钟）。
    registry.register(
        _record(chat_message_id="stale", created_at=now - 500, last_accessed_at=now - 500)
    )
    registry.register(
        _record(chat_message_id="fresh", created_at=now, last_accessed_at=now)
    )
    removed = registry.prune(now=now + 600)
    assert removed == 1
    assert registry.lookup_by_message_id("stale") is None
    assert registry.lookup_by_message_id("fresh") is not None
    registry.close()


def test_prune_fifo_keeps_newest_within_max_rows(tmp_path: Path) -> None:
    now = int(time.time())
    registry = SQLiteMediaRegistry(tmp_path / "registry.sqlite3", max_rows=3)
    for index in range(5):
        registry.register(
            _record(
                chat_message_id=f"m-{index}",
                created_at=1000 + index,  # created_at 定新旧次序
                last_accessed_at=now,  # last_accessed 保持新鲜，隔离 TTL 影响
            )
        )
    # 写入时顺带剪枝：created_at 最旧的两条（m-0、m-1）已被 FIFO 掉。
    assert registry.lookup_by_message_id("m-0") is None
    assert registry.lookup_by_message_id("m-1") is None
    for index in (2, 3, 4):
        assert registry.lookup_by_message_id(f"m-{index}") is not None
    assert registry.prune() == 0
    registry.close()


def test_build_media_registry_none_config_uses_default_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(tmp_path / "runtime-data"))
    registry = build_media_registry(None, max_rows=7)
    assert isinstance(registry, SQLiteMediaRegistry)
    assert registry.max_rows == 7
    assert registry.ttl_seconds == 604800
    media_id = registry.register(_record())
    assert media_id
    assert registry.lookup_by_message_id("m-1") is not None
    registry.close()
    assert (tmp_path / "runtime-data" / "media_registry.sqlite3").exists()
