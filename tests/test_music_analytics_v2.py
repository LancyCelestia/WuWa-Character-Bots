from __future__ import annotations

from datetime import datetime, timedelta, timezone

from plugins.bot_unified_runtime.contracts.music import (
    MusicContributor,
    MusicRequestEvent,
    MusicTrack,
)
from plugins.bot_unified_runtime.sources.music_request_store import MusicRequestStore


def _track(
    *,
    provider: str = "netease",
    provider_track_id: str = "n-1",
    isrc: str | None = "CN-TEST-1",
    title: str = "测试歌曲",
    artist: str = "测试歌手",
) -> MusicTrack:
    return MusicTrack(
        provider=provider,
        provider_track_id=provider_track_id,
        title=title,
        isrc=isrc,
        duration_ms=180_000,
        contributors=[MusicContributor(name=artist, roles=["performer"])],
    )


def test_successful_music_request_is_idempotent_and_ranked(tmp_path) -> None:
    store = MusicRequestStore(str(tmp_path / "music_analytics.sqlite3"))
    now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    canonical_id = store.upsert_track(_track())
    event = MusicRequestEvent(
        request_id="request-1",
        canonical_track_id=canonical_id,
        provider="netease",
        provider_track_id="n-1",
        session_scope="private",
        requested_at=now,
    )

    assert store.record_successful_request(event) is True
    assert store.record_successful_request(event) is False
    ranking = store.request_ranking(period="day", now=now + timedelta(minutes=1))
    assert len(ranking) == 1
    assert ranking[0].canonical_track_id == canonical_id
    assert ranking[0].request_count == 1


def test_same_isrc_from_two_providers_shares_canonical_id(tmp_path) -> None:
    store = MusicRequestStore(str(tmp_path / "music_analytics.sqlite3"))
    first = store.upsert_track(_track(provider="netease", provider_track_id="n-1"))
    second = store.upsert_track(_track(provider="qqmusic", provider_track_id="q-1"))
    assert first == second


def test_day_week_year_windows_are_half_open(tmp_path) -> None:
    store = MusicRequestStore(str(tmp_path / "music_analytics.sqlite3"))
    now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    canonical_id = store.upsert_track(_track())
    for request_id, requested_at in (
        ("day", now - timedelta(hours=1)),
        ("week", now - timedelta(days=2)),
        ("year", now - timedelta(days=40)),
        ("outside", now - timedelta(days=366)),
    ):
        store.record_successful_request(
            MusicRequestEvent(
                request_id=request_id,
                canonical_track_id=canonical_id,
                provider="netease",
                provider_track_id="n-1",
                session_scope="private",
                requested_at=requested_at,
            )
        )

    assert store.request_ranking(period="day", now=now)[0].request_count == 1
    assert store.request_ranking(period="week", now=now)[0].request_count == 2
    assert store.request_ranking(period="year", now=now)[0].request_count == 3
