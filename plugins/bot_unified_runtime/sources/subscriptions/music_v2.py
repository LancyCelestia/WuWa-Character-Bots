"""音乐动态订阅 V2：统一目标解析和可注入 provider 客户端。

网易云匿名端点（2026-09-12 只读探测验证）：
- playlist: GET /api/playlist/detail?id=…（顶层键 ``result``）
- album:    GET /api/album/{id}（路径形态；?id= 404。匿名探测遇 -462 风控，
            带登录 Cookie 的环境可用，取不到时返回零条目不伪造）
- artist:   GET /api/artist/{id}（路径形态；?id= 404）
- public_user: GET /api/user/playlist?uid=…（参数名 uid；传 id 返回 400）
"""
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
from plugins.bot_unified_runtime.sources.subscriptions.social_v2 import (
    _reached_cursor,
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

    @staticmethod
    def _netease_track_payload(track: dict) -> dict[str, Any]:
        """把曲目元数据展开进 source_payload：title/歌手/封面/时长（可获取即填）。

        text 键被推送渲染消费（`[订阅] … 更新《title》：url` 下一行），
        其余字段按 ParsedContent 契约语义命名，供卡片/审计读取。
        """
        payload: dict[str, Any] = {"title": str(track.get("name") or "")}
        raw_artists = track.get("artists") or track.get("ar") or []
        artist_names = [
            str(item.get("name") or "").strip()
            for item in (raw_artists if isinstance(raw_artists, list) else [])
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
        if artist_names:
            payload["artist_names"] = artist_names
            payload["text"] = f"歌手：{'、'.join(artist_names)}"
        album = track.get("album") or track.get("al") or {}
        artwork = (
            str(album.get("picUrl") or "").strip()
            if isinstance(album, dict)
            else ""
        )
        if artwork:
            payload["artwork_url"] = artwork
        duration = track.get("duration") or track.get("dt")
        if isinstance(duration, (int, float)) and duration >= 0:
            payload["duration_ms"] = int(duration)
        return payload

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
                    endpoint = (
                        "https://music.163.com/api/playlist/detail"
                        f"?id={target.target_key}&limit=50"
                    )
                elif target.target_kind == "album":
                    # 实测 2026-09-12：/api/album?id= 返回 404，仅路径形态可用。
                    endpoint = f"https://music.163.com/api/album/{target.target_key}"
                elif target.target_kind == "artist":
                    # 实测 2026-09-12：/api/artist?id= 返回 404，仅路径形态可用。
                    endpoint = f"https://music.163.com/api/artist/{target.target_key}"
                else:
                    # 实测 2026-09-12：参数名是 uid，传 id 返回 400。
                    endpoint = (
                        "https://music.163.com/api/user/playlist"
                        f"?uid={target.target_key}&limit=50"
                    )
                payload = http_get_json(
                    endpoint,
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
                # 实测 2026-09-12：/api/playlist/detail 顶层键为 result（旧代码
                # 读 playlist 键恒为空，等于所有网易云歌单订阅静默零条目）。
                owner = payload.get("result") or payload.get("playlist") if isinstance(payload, dict) else None
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
                # 审计 E2-4：网易云曲目 id 为数值，删除旧曲目后不再重复整页。
                if _reached_cursor(item_id, previous):
                    break
                items.append(ContentReference(
                    item_id=item_id,
                    item_kind="music_track",
                    url=f"https://music.163.com/song?id={item_id}",
                    source_payload=self._netease_track_payload(track),
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
