from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from plugins.bot_unified_runtime.domains.core.contracts.subscription import (
    SubscriptionTarget,
)
from plugins.bot_unified_runtime.domains.subscribe.adapters.music_v2 import (
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


def test_music_adapter_rejects_removed_platform_with_explicit_notice() -> None:
    # 新旧行为对照（审查 J-06）：旧行为=spotify 注册在注册表里、resolve 成功，
    # fetch 恒 unsupported——订阅成功却永远收不到推送也无提示；新行为=
    # resolve 直接拒绝并给出人话提示（说明仍可订的网易云），不再注册成功。
    adapter = MusicSubscriptionAdapterV2()
    with pytest.raises(ValueError) as excinfo:
        asyncio.run(adapter.resolve_target("spotify:artist:abc", {}))
    message = str(excinfo.value)
    assert "Spotify" in message
    assert "网易云" in message


def test_music_adapter_unsupported_fetch_stays_structured_for_direct_targets() -> None:
    # 防御路径：直构目标绕过 resolve 时仍返回结构化 unsupported，不允许
    # 静默空结果（注册面已摘除，生产调度不会再把此类平台路由到本 adapter）。
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
    assert result.retryable is False
