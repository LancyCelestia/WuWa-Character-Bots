"""音乐动态订阅 V2：统一目标解析和可注入 provider 客户端。"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from plugins.bot_unified_runtime.contracts.subscription import (
    ContentReference,
    SubscriptionCursorV2,
    SubscriptionFetchResult,
    SubscriptionTarget,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import (
    ParseHttpError,
    http_get_json,
)


class MusicSubscriptionAdapterV2:
    platform = "music"
    supported_platforms = frozenset(
        {"netease", "qqmusic", "kuwo", "kugou", "apple_music", "spotify"}
    )
    target_kinds = frozenset({"artist", "album", "playlist", "public_user"})

    def __init__(self, clients: dict[str, Any] | None = None) -> None:
        self.clients = dict(clients or {})

    @staticmethod
    def _make_target(provider: str, kind: str, key: str, raw: str) -> SubscriptionTarget:
        now = datetime.now(timezone.utc)
        return SubscriptionTarget(
            id=f"{provider}:{kind}:{key}",
            platform=provider,
            target_kind=kind,
            target_key=key,
            display_name=key,
            target_payload={"raw": raw},
            created_at=now,
            updated_at=now,
        )

    async def resolve_target(self, raw_target: str, ctx: dict[str, Any]) -> SubscriptionTarget:
        raw = str(raw_target or "").strip()
        if ":" in raw and not raw.startswith("http"):
            provider, kind, key = (raw.split(":", 2) + [""])[:3]
            if provider in {"netease", "qqmusic", "kuwo", "kugou", "apple_music", "spotify"} and kind in self.target_kinds and key:
                return self._make_target(provider, kind, key, raw)
        patterns = (
            (r"music\.163\.com/(?:#/)?playlist\?[^\s]*id=(\d+)", "netease", "playlist"),
            (r"music\.163\.com/(?:#/)?artist\?[^\s]*id=(\d+)", "netease", "artist"),
            (r"y\.qq\.com/.*/playlist/(\w+)", "qqmusic", "playlist"),
            (r"open\.spotify\.com/(artist|album|playlist)/([0-9A-Za-z]+)", "spotify", "path"),
        )
        for pattern, provider, kind in patterns:
            match = re.search(pattern, raw, re.IGNORECASE)
            if not match:
                continue
            if kind == "path":
                resolved_kind, key = match.group(1), match.group(2)
            else:
                resolved_kind, key = kind, match.group(1)
            return self._make_target(provider, resolved_kind, key, raw)
        raise ValueError("无法识别的音乐订阅目标")

    async def fetch_incremental(self, target, cursors, context):
        client = self.clients.get(target.platform)
        if client is not None:
            result = client.fetch_incremental(target, cursors, context)
            if hasattr(result, "__await__"):
                result = await result
            if not isinstance(result, SubscriptionFetchResult):
                raise TypeError("music provider client must return SubscriptionFetchResult")
            return result
        if target.platform == "netease" and target.target_kind in {"playlist", "album", "artist", "public_user"}:
            try:
                if target.target_kind == "playlist":
                    endpoint = "https://music.163.com/api/playlist/detail"
                elif target.target_kind == "album":
                    endpoint = "https://music.163.com/api/album"
                elif target.target_kind == "artist":
                    endpoint = "https://music.163.com/api/artist"
                else:
                    endpoint = "https://music.163.com/api/user/playlist"
                payload = http_get_json(
                    f"{endpoint}?id={target.target_key}&limit=50",
                    timeout=float((context or {}).get("timeout_seconds", 10.0) or 10.0),
                    cookie=str((context or {}).get("cookie_header", "") or ""),
                    proxy=str((context or {}).get("proxy", "") or ""),
                    referer="https://music.163.com/",
                )
            except ParseHttpError:
                return SubscriptionFetchResult(
                    health_state="degraded", error_code="network_error", retryable=True
                )
            if target.target_kind == "playlist":
                owner = payload.get("playlist") if isinstance(payload, dict) else None
                tracks = owner.get("tracks") if isinstance(owner, dict) else []
            elif target.target_kind == "album":
                owner = payload.get("album") if isinstance(payload, dict) else None
                tracks = owner.get("songs") if isinstance(owner, dict) else []
            elif target.target_kind == "artist":
                tracks = payload.get("hotSongs") if isinstance(payload, dict) else []
            else:
                tracks = payload.get("playlist") if isinstance(payload, dict) else []
            tracks = tracks if isinstance(tracks, list) else []
            stream = target.target_kind
            cursor = cursors.get(stream) if cursors else None
            previous = str(getattr(cursor, "last_item_id", "") or "")
            items: list[ContentReference] = []
            for track in tracks:
                if not isinstance(track, dict):
                    continue
                item_id = str(track.get("id") or "")
                if not item_id:
                    continue
                if item_id == previous:
                    break
                items.append(ContentReference(
                    item_id=item_id,
                    item_kind="music_track",
                    url=f"https://music.163.com/song?id={item_id}",
                    source_payload={"title": str(track.get("name") or "")},
                ))
            latest = items[0].item_id if items else previous
            return SubscriptionFetchResult(
                items=items,
                cursors=[SubscriptionCursorV2(
                    target_id=target.id,
                    stream=stream,
                    last_item_id=latest,
                    updated_at=datetime.now(timezone.utc),
                )],
            )
        return SubscriptionFetchResult(
            health_state="unsupported",
            error_code="unsupported",
            retryable=False,
        )


ADAPTERS = [MusicSubscriptionAdapterV2()]
