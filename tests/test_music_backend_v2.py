from __future__ import annotations

from datetime import datetime, timezone

from plugins.bot_unified_runtime.contracts.music import (
    MusicContributor,
    MusicRequestEvent,
    MusicTrack,
)
from plugins.bot_unified_runtime.sources.music_normalization import (
    canonical_key,
    music_fingerprint,
)


def _track(
    *,
    provider: str = "netease",
    provider_track_id: str = "1",
    title: str = "同名",
    artist: str = "甲",
    duration_ms: int = 180_000,
    isrc: str | None = None,
) -> MusicTrack:
    return MusicTrack(
        provider=provider,
        provider_track_id=provider_track_id,
        title=title,
        contributors=[MusicContributor(name=artist, roles=["performer"])],
        duration_ms=duration_ms,
        isrc=isrc,
    )


def test_music_contributor_roles_are_not_flattened() -> None:
    track = MusicTrack(
        provider="netease",
        provider_track_id="1",
        title="歌",
        contributors=[
            MusicContributor(name="演唱者", roles=["performer"]),
            MusicContributor(name="创作者", roles=["lyricist", "composer"]),
        ],
    )
    assert track.contributors[1].roles == ["lyricist", "composer"]


def test_canonical_key_prefers_normalized_isrc() -> None:
    assert canonical_key(_track(isrc="cn-ab-1")) == "isrc:CN-AB-1"


def test_same_title_by_different_artists_has_different_fingerprint() -> None:
    assert music_fingerprint(_track(artist="甲")) != music_fingerprint(
        _track(provider="qqmusic", provider_track_id="2", artist="乙")
    )


def test_music_request_event_contains_no_raw_query() -> None:
    event = MusicRequestEvent(
        request_id="req-1",
        canonical_track_id="isrc:X",
        provider="netease",
        provider_track_id="1",
        session_scope="private",
        requested_at=datetime.now(timezone.utc),
    )
    assert "query" not in event.model_dump()
