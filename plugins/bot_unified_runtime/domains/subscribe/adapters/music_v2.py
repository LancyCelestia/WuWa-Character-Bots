"""音乐动态订阅 V2：统一目标解析和可注入 provider 客户端。

网易云匿名端点（2026-09-12 只读探测验证）：
- playlist: GET /api/playlist/detail?id=…（顶层键 ``result``）
- album:    GET /api/album/{id}（路径形态；?id= 404。匿名探测遇 -462 风控，
            带登录 Cookie 的环境可用，取不到时返回零条目不伪造）
- artist:   GET /api/artist/{id}（路径形态；?id= 404）
- public_user: GET /api/user/playlist?uid=…（参数名 uid；传 id 返回 400）

注册面摘除登记（审查 J-06，2026-09-14）：
- 摘除平台：qqmusic / kuwo / kugou / apple_music / spotify（仅保留 netease）。
- 摘除原因：这五个平台此前注册在 supported_platforms 与 resolve_target 里，
  ``/订阅 add`` 能成功落库，但 fetch_incremental 无实现、恒返回 unsupported
  ——用户订了却永远收不到推送也无任何提示（诚实性缺陷）。生产装配为
  ``MusicSubscriptionAdapterV2()``（不注入 clients），仅 netease 有内置 fetch；
  其中 kuwo/kugou/apple_music 无 URL 模式、仅冒号形态可达，同样恒 unsupported，
  属同款缺陷一并摘除。
- 现行为：摘除平台的链接/冒号形态仍保留识别，resolve 时抛「暂不支持」人话
  提示（说明仍可订的网易云），不再静默注册成功。
- 恢复条件：为对应平台补齐 fetch 实现后，把平台加回 supported_platforms、
  resolve_target 的 provider 集合与 URL 模式，并同步本登记与回归测试。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from plugins.bot_unified_runtime.domains.core.contracts.subscription import (
    ContentReference,
    SubscriptionCursorV2,
    SubscriptionFetchResult,
    SubscriptionTarget,
)
from plugins.bot_unified_runtime.domains.subscribe.adapters.social_v2 import (
    _reached_cursor,
)
from plugins.bot_unified_runtime.domains.subscribe.adapters.target_notice import (
    SubscriptionTargetNotice,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import (
    ParseHttpError,
    http_get_json,
)

# 审查 J-06：摘除平台保留名字映射，resolve 时给出指名道姓的「暂不支持」提示。
_REMOVED_PLATFORM_LABELS = {
    "qqmusic": "QQ音乐",
    "kuwo": "酷我音乐",
    "kugou": "酷狗音乐",
    "apple_music": "Apple Music",
    "spotify": "Spotify",
}
# 摘除平台的链接形态仍保留识别（判断先于 netease 模式之前无冲突：
# 两类模式互不重叠），让 /订阅 add 拿到显式提示而不是「无法识别」。
_REMOVED_URL_PATTERNS = (
    (r"y\.qq\.com/.*/playlist/\w+", "qqmusic"),
    (r"open\.spotify\.com/(?:artist|album|playlist)/[0-9A-Za-z]+", "spotify"),
)


def _removed_platform_message(label: str) -> str:
    return (
        f"{label}的音乐订阅还没接上拉取，订了也一直收不到更新，就先不开放了。"
        "现在能订的是网易云（netease）：歌单、专辑、歌手、用户歌单链接都可以，"
        "换条网易云的链接再来一次吧。"
    )


class MusicSubscriptionAdapterV2:
    platform = "music"
    # 审查 J-06：注册面只保留有真实 fetch 实现的平台（netease），
    # 杜绝「订阅成功但永远无推送」的恒不可用注册。
    supported_platforms = frozenset({"netease"})
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
            # 审查 J-06：摘除平台在冒号形态下显式报「暂不支持」，不再注册成功。
            if provider in _REMOVED_PLATFORM_LABELS and kind in self.target_kinds and key:
                raise SubscriptionTargetNotice(
                    _removed_platform_message(_REMOVED_PLATFORM_LABELS[provider])
                )
            if provider in self.supported_platforms and kind in self.target_kinds and key:
                return self._make_target(provider, kind, key, raw)
        # 审查 J-06：摘除平台的链接形态给出人话提示而非「无法识别」。
        for pattern, provider in _REMOVED_URL_PATTERNS:
            if re.search(pattern, raw, re.IGNORECASE):
                raise SubscriptionTargetNotice(
                    _removed_platform_message(_REMOVED_PLATFORM_LABELS[provider])
                )
        patterns = (
            (r"music\.163\.com/(?:#/)?playlist\?[^\s]*id=(\d+)", "netease", "playlist"),
            (r"music\.163\.com/(?:#/)?artist\?[^\s]*id=(\d+)", "netease", "artist"),
        )
        for pattern, provider, kind in patterns:
            match = re.search(pattern, raw, re.IGNORECASE)
            if not match:
                continue
            return self._make_target(provider, kind, match.group(1), raw)
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
        # 审查 J-06：注册面对齐后正常路径不会走到这里——保留兜底为防御
        # 路径（误注册/直构目标仍返回结构化 unsupported，不允许静默空结果）。
        return SubscriptionFetchResult(
            health_state="unsupported",
            error_code="unsupported",
            retryable=False,
        )


ADAPTERS = [MusicSubscriptionAdapterV2()]
