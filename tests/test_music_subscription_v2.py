from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from plugins.bot_unified_runtime.contracts.subscription import SubscriptionTarget
from plugins.bot_unified_runtime.sources.subscriptions.music_v2 import (
    MusicSubscriptionAdapterV2,
)


def test_music_adapter_resolves_netease_playlist_and_artist() -> None:
    adapter = MusicSubscriptionAdapterV2()
    playlist = asyncio.run(
        adapter.resolve_target("https://music.163.com/playlist?id=123", {})
    )
    artist = asyncio.run(adapter.resolve_target("netease:artist:456", {}))
    assert isinstance(playlist, SubscriptionTarget)
    assert playlist.target_kind == "playlist"
    assert playlist.target_key == "123"
    assert artist.target_kind == "artist"
    assert artist.target_key == "456"


def test_music_adapter_unsupported_provider_returns_structured_result() -> None:
    target = SubscriptionTarget(
        id="spotify:artist:abc",
        platform="spotify",
        target_kind="artist",
        target_key="abc",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    result = asyncio.run(
        MusicSubscriptionAdapterV2().fetch_incremental(target, {}, {})
    )
    assert result.error_code == "unsupported"
