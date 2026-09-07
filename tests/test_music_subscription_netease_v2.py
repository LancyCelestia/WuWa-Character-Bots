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
    payload = {
        "playlist": {
            "name": "歌单",
            "tracks": [
                {"id": 3, "name": "新歌"},
                {"id": 2, "name": "已见"},
                {"id": 1, "name": "更旧"},
            ],
        }
    }

    def fake_get_json(url: str, **kwargs):
        assert "/api/playlist/detail" in url
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
    assert [item.item_id for item in result.items] == ["3"]
    assert result.cursors[0].last_item_id == "3"


def test_netease_adapter_reports_unknown_provider_as_unsupported() -> None:
    target = _target("artist", "1").model_copy(update={"platform": "unknown"})
    result = asyncio.run(
        MusicSubscriptionAdapterV2().fetch_incremental(target, {}, {})
    )
    assert result.error_code == "unsupported"
