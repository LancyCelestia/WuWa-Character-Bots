from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from plugins.bot_unified_runtime.contracts.subscription import (
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


def test_netease_playlist_returns_only_tracks_after_cursor(monkeypatch) -> None:
    # 实测 2026-09-12：/api/playlist/detail 顶层键为 result（不是 playlist——
    # 旧代码读错键导致所有网易云歌单订阅静默零条目，B6 修复）。
    payload = {
        "code": 200,
        "result": {
            "name": "歌单",
            "trackCount": 3,
            "tracks": [
                {
                    "id": 3,
                    "name": "新歌",
                    "artists": [{"id": 9, "name": "歌手甲"}],
                    "album": {"id": 11, "name": "专辑甲", "picUrl": "http://p1.music.126.net/x/1.jpg"},
                    "duration": 210000,
                },
                {"id": 2, "name": "已见", "artists": [], "album": {}, "duration": 200000},
                {"id": 1, "name": "更旧", "artists": [], "album": {}, "duration": 190000},
            ],
        },
    }
    requested_urls: list[str] = []

    def fake_get_json(url: str, **kwargs):
        requested_urls.append(url)
        return payload

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.subscriptions.music_v2.http_get_json",
        fake_get_json,
    )
    result = asyncio.run(
        MusicSubscriptionAdapterV2().fetch_incremental(
            _target("playlist", "10"),
            {
                "playlist": SubscriptionCursorV2(
                    target_id="netease:playlist:10",
                    stream="playlist",
                    last_item_id="2",
                    updated_at=_NOW,
                )
            },
            {"cookie_header": "", "proxy": ""},
        )
    )
    assert "api/playlist/detail?id=10" in requested_urls[0]
    assert [item.item_id for item in result.items] == ["3"]
    assert result.cursors[0].last_item_id == "3"
    # 字段补全：歌手/封面/时长随条目下发，text 供推送渲染消费。
    fields = result.items[0].source_payload
    assert fields["title"] == "新歌"
    assert fields["artist_names"] == ["歌手甲"]
    assert fields["artwork_url"] == "http://p1.music.126.net/x/1.jpg"
    assert fields["duration_ms"] == 210000
    assert fields["text"] == "歌手：歌手甲"


def test_netease_adapter_reports_unknown_provider_as_unsupported() -> None:
    target = _target("artist", "1").model_copy(update={"platform": "unknown"})
    result = asyncio.run(
        MusicSubscriptionAdapterV2().fetch_incremental(target, {}, {})
    )
    assert result.error_code == "unsupported"
