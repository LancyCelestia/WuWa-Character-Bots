from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from plugins.bot_unified_runtime.contracts import (
    SubscriptionCursorV2,
    SubscriptionTarget,
)
from plugins.bot_unified_runtime.domains.subscribe.adapters.music_v2 import (
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
    # 实测 2026-09-12：仅 /api/artist/{id} 路径形态可用（?id= 恒 404）。
    requested_urls: list[str] = []

    def fake_get_json(url: str, **kwargs):
        requested_urls.append(url)
        return {
            "artist": {"name": "歌手"},
            "hotSongs": [
                {"id": 3, "name": "新歌", "ar": [{"id": 5, "name": "歌手"}], "dt": 240000},
                {"id": 2, "name": "已见", "ar": [], "dt": 230000},
            ],
        }

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.domains.subscribe.adapters.music_v2.http_get_json",
        fake_get_json,
    )
    result = asyncio.run(
        MusicSubscriptionAdapterV2().fetch_incremental(
            _target("artist", "7"),
            {"artist": SubscriptionCursorV2(target_id="x", stream="artist", last_item_id="2", updated_at=_NOW)},
            {},
        )
    )
    assert requested_urls and requested_urls[0].startswith("https://music.163.com/api/artist/7")
    assert [item.item_id for item in result.items] == ["3"]
    # 新歌条目带歌手/时长（ar/dt 键与详情形态等价）。
    fields = result.items[0].source_payload
    assert fields["artist_names"] == ["歌手"]
    assert fields["duration_ms"] == 240000
    assert fields["text"] == "歌手：歌手"


def test_netease_album_source_returns_tracks(monkeypatch) -> None:
    # 实测 2026-09-12：仅 /api/album/{id} 路径形态可用（?id= 恒 404）。
    requested_urls: list[str] = []

    def fake_get_json(url: str, **kwargs):
        requested_urls.append(url)
        return {
            "album": {
                "name": "专辑",
                "songs": [
                    {
                        "id": 9,
                        "name": "曲目",
                        "al": {"id": 1, "name": "专辑", "picUrl": "http://p1.music.126.net/x/9.jpg"},
                    }
                ],
            }
        }

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.domains.subscribe.adapters.music_v2.http_get_json",
        fake_get_json,
    )
    result = asyncio.run(
        MusicSubscriptionAdapterV2().fetch_incremental(_target("album", "8"), {}, {})
    )
    assert requested_urls[0].startswith("https://music.163.com/api/album/8")
    assert result.items[0].item_id == "9"
    assert result.items[0].item_kind == "music_track"
    assert result.items[0].source_payload["artwork_url"] == "http://p1.music.126.net/x/9.jpg"
