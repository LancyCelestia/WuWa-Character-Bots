from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from plugins.bot_unified_runtime.contracts import (
    SubscriptionCursorV2,
    SubscriptionTarget,
)
from plugins.bot_unified_runtime.sources.subscriptions.music_v2 import (
    MusicSubscriptionAdapterV2,
)

_NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def _target(kind: str, key: str) -> SubscriptionTarget:
    return SubscriptionTarget(
        id=f"netease:{kind}:{key}",
        platform="netease",
        target_kind=kind,
        target_key=key,
        created_at=_NOW,
        updated_at=_NOW,
    )


def test_netease_artist_source_returns_incremental_songs(monkeypatch) -> None:
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.subscriptions.music_v2.http_get_json",
        lambda url, **kwargs: {
            "artist": {"name": "歌手"},
            "hotSongs": [{"id": 3, "name": "新歌"}, {"id": 2, "name": "已见"}],
        },
    )
    result = asyncio.run(
        MusicSubscriptionAdapterV2().fetch_incremental(
            _target("artist", "7"),
            {"artist": SubscriptionCursorV2(target_id="x", stream="artist", last_item_id="2", updated_at=_NOW)},
            {},
        )
    )
    assert [item.item_id for item in result.items] == ["3"]


def test_netease_album_source_returns_tracks(monkeypatch) -> None:
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.subscriptions.music_v2.http_get_json",
        lambda url, **kwargs: {"album": {"name": "专辑", "songs": [{"id": 9, "name": "曲目"}]}},
    )
    result = asyncio.run(
        MusicSubscriptionAdapterV2().fetch_incremental(_target("album", "8"), {}, {})
    )
    assert result.items[0].item_id == "9"
    assert result.items[0].item_kind == "music_track"
