"""音乐榜单来源注册表；本地点歌榜由 MusicRequestStore 提供。

B6（2026-09-12）真实榜单 source（端点均经只读探测验证，解析测试全离线 mock）：

- 网易云热歌榜/飙升榜：GET music.163.com/api/playlist/detail?id=<toplist 歌单 id>
  （实测 200，顶层键为 ``result``，tracks 含 id/name/artists/album.picUrl/duration 毫秒）。
- QQ 音乐热歌榜：POST u.y.qq.com/cgi-bin/musicu.fcg
  ``musicToplist.ToplistInfoServer``/``GetDetail``（实测 200，song[] 含
  rank/songId/title/singerName/albumMid；无 songMid、无时长）。
- 酷狗飙升榜/电音榜：GET mobilecdn.kugou.com/api/v3/rank/song?rankid=<id>
  （实测 200，info[] 含 sort/hash/songname/authors/album_sizable_cover/duration 秒；
  rank/list 确认 6666=飙升榜、33160=电音榜）。
- 酷我 / Apple Music / Spotify：匿名不可达，注册为 ``unavailable`` 占位并如实标注
  原因，``fetch_snapshot`` 抛 :class:`ChartSourceUnavailableError`，绝不伪造数据。
"""
from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any, Protocol

from plugins.bot_unified_runtime.domains.core.contracts.music import (
    MusicChartEntry,
    MusicChartSnapshot,
)
from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
    http_get_json,
    http_post_json,
)


class MusicChartSource(Protocol):
    source_id: str
    category: str

    async def fetch_snapshot(self, ctx: Any) -> MusicChartSnapshot:
        ...


class ChartSourceUnavailableError(RuntimeError):
    """榜单源已知不可达（配置缺失或平台接口下线），不重试。"""

    def __init__(self, source_id: str, reason: str) -> None:
        super().__init__(f"chart source {source_id} unavailable: {reason}")
        self.source_id = source_id
        self.reason = reason


class UnavailableChartSource:
    """不可达榜单源的诚实占位：只登记元信息，fetch 一律抛错。"""

    status = "unavailable"

    def __init__(self, source_id: str, platform: str, category: str, reason: str) -> None:
        self.source_id = source_id
        self.platform = platform
        self.category = category
        self.unavailability_reason = reason

    async def fetch_snapshot(self, ctx: Any) -> MusicChartSnapshot:
        raise ChartSourceUnavailableError(self.source_id, self.unavailability_reason)


class _HTTPChartSource:
    """真实榜单 source 基类：同步 HTTP 放线程池，解析为纯函数便于离线测试。"""

    platform = ""
    status = "real"
    unavailability_reason = ""
    limit = 100

    def __init__(self, *, source_id: str, category: str, chart_id: str, region: str = "cn") -> None:
        self.source_id = source_id
        self.category = category
        self.chart_id = str(chart_id)
        self.region = region

    # -- 子类实现 -----------------------------------------------------------

    def _fetch_payload(self, cookie: str) -> Any:
        raise NotImplementedError

    def _parse_entries(self, payload: Any) -> tuple[list, str]:
        """返回 (entries, period)；解析为纯函数，测试直接注入真实裁剪 fixture。"""
        raise NotImplementedError

    # -- 快照 ---------------------------------------------------------------

    def _snapshot(self, entries: list, period: str = "") -> MusicChartSnapshot:
        fetched_at = datetime.now(timezone.utc)
        return MusicChartSnapshot(
            snapshot_id=f"{self.source_id}:{int(fetched_at.timestamp())}",
            source_id=self.source_id,
            platform=self.platform,
            category=self.category,
            region=self.region,
            source_type="platform_toplist",
            fetched_at=fetched_at,
            period=period,
            entries=entries,
        )

    async def fetch_snapshot(self, ctx: Any) -> MusicChartSnapshot:
        cookie = str((ctx or {}).get("cookie_header", "") or "")
        payload = await asyncio.to_thread(self._fetch_payload, cookie)
        entries, period = self._parse_entries(payload)
        return self._snapshot(entries, period=period)


# ---------- 网易云（toplist 以歌单形式下发）----------


class NeteaseChartSource(_HTTPChartSource):
    platform = "netease"

    def _fetch_payload(self, cookie: str) -> Any:
        return http_get_json(
            f"https://music.163.com/api/playlist/detail?id={self.chart_id}&limit={self.limit}",
            referer="https://music.163.com/",
            cookie=cookie,
            timeout=10.0,
        )

    def _parse_entries(self, payload: Any) -> tuple[list, str]:
        payload = payload if isinstance(payload, dict) else {}
        # 实测顶层键为 result（2026-09-12）；兼容旧客户端曾下发的 playlist 键。
        playlist = payload.get("result") or payload.get("playlist") or {}
        tracks = playlist.get("tracks") if isinstance(playlist, dict) else None
        tracks = tracks if isinstance(tracks, list) else []
        entries: list = []
        for track in tracks[: self.limit]:
            if not isinstance(track, dict):
                continue
            track_id = str(track.get("id") or "").strip()
            title = str(track.get("name") or "").strip()
            if not track_id or not title:
                continue
            raw_artists = track.get("artists") or track.get("ar") or []
            artist_names = [
                str(item.get("name") or "").strip()
                for item in raw_artists
                if isinstance(item, dict)
            ]
            album = track.get("album") or track.get("al") or {}
            album = album if isinstance(album, dict) else {}
            duration = track.get("duration") or track.get("dt")
            entries.append(
                _chart_entry(
                    provider_track_id=track_id,
                    rank=len(entries) + 1,
                    title=title,
                    artist_names=[name for name in artist_names if name],
                    album_name=str(album.get("name") or ""),
                    artwork_url=str(album.get("picUrl") or ""),
                    duration_ms=duration,
                    url=f"https://music.163.com/song?id={track_id}",
                )
            )
        return entries, ""


# ---------- QQ 音乐 ----------


class QQMusicChartSource(_HTTPChartSource):
    platform = "qqmusic"
    _API = "https://u.y.qq.com/cgi-bin/musicu.fcg"
    _COVER_TPL = "https://y.gtimg.cn/music/photo_new/T002R500x500M000{mid}.jpg"

    def _fetch_payload(self, cookie: str) -> Any:
        body = {
            "req_1": {
                "module": "musicToplist.ToplistInfoServer",
                "method": "GetDetail",
                "param": {
                    "topId": int(self.chart_id),
                    "offset": 0,
                    "num": self.limit,
                },
            }
        }
        return http_post_json(
            self._API,
            body,
            referer="https://y.qq.com/",
            cookie=cookie,
            timeout=10.0,
        )

    def _parse_entries(self, payload: Any) -> tuple[list, str]:
        payload = payload if isinstance(payload, dict) else {}
        data = ((payload.get("req_1") or {}).get("data") or {}).get("data") or {}
        songs = data.get("song") if isinstance(data, dict) else None
        songs = songs if isinstance(songs, list) else []
        entries: list = []
        for song in songs[: self.limit]:
            if not isinstance(song, dict):
                continue
            song_id = str(song.get("songId") or "").strip()
            title = str(song.get("title") or "").strip()
            if not song_id or not title:
                continue
            singer_names = [
                part.strip()
                for part in str(song.get("singerName") or "").split("/")
                if part.strip()
            ]
            album_mid = str(song.get("albumMid") or "").strip()
            artwork = str(song.get("cover") or "").strip() or (
                self._COVER_TPL.format(mid=album_mid) if album_mid else ""
            )
            entries.append(
                _chart_entry(
                    provider_track_id=song_id,
                    rank=len(entries) + 1,
                    title=title,
                    artist_names=singer_names,
                    album_name=str(song.get("albumName") or ""),
                    artwork_url=artwork,
                    # GetDetail 不下发时长（实测无 interval 字段）：诚实留空。
                    duration_ms=None,
                    url=f"https://i.y.qq.com/v8/playsong.html?songid={song_id}",
                )
            )
        period = str(data.get("period") or "") if isinstance(data, dict) else ""
        return entries, period


# ---------- 酷狗 ----------


class KugouChartSource(_HTTPChartSource):
    platform = "kugou"

    def _fetch_payload(self, cookie: str) -> Any:
        return http_get_json(
            f"http://mobilecdn.kugou.com/api/v3/rank/song"
            f"?rankid={self.chart_id}&page=1&pagesize={self.limit}&format=json",
            referer="https://www.kugou.com/",
            timeout=10.0,
        )

    def _parse_entries(self, payload: Any) -> tuple[list, str]:
        payload = payload if isinstance(payload, dict) else {}
        data = payload.get("data") or {}
        rows = data.get("info") if isinstance(data, dict) else None
        rows = rows if isinstance(rows, list) else []
        entries: list = []
        for row in rows[: self.limit]:
            if not isinstance(row, dict):
                continue
            file_hash = str(row.get("hash") or "").strip()
            title = str(row.get("songname") or row.get("filename") or "").strip()
            if not file_hash or not title:
                continue
            artist_names = [
                str(item.get("author_name") or "").strip()
                for item in (row.get("authors") or [])
                if isinstance(item, dict)
            ]
            # album_sizable_cover 是 {size} 模板，占位不替换必裂图。
            cover = str(row.get("album_sizable_cover") or "").replace("{size}", "480")
            duration_seconds = row.get("duration")
            duration_ms = (
                int(duration_seconds) * 1000
                if isinstance(duration_seconds, (int, float)) and duration_seconds >= 0
                else None
            )
            entries.append(
                _chart_entry(
                    provider_track_id=file_hash,
                    rank=len(entries) + 1,
                    title=title,
                    artist_names=[name for name in artist_names if name],
                    album_name=str(row.get("remark") or ""),
                    artwork_url=cover,
                    duration_ms=duration_ms,
                    url=f"https://www.kugou.com/song/#hash={file_hash}",
                )
            )
        # 接口未下发榜单期号：不把 timestamp 伪造成 period。
        return entries, ""


def _chart_entry(
    *,
    provider_track_id: str,
    rank: int,
    title: str,
    artist_names: list[str],
    album_name: str,
    artwork_url: str,
    duration_ms: int | None,
    url: str,
) -> MusicChartEntry:
    return MusicChartEntry(
        provider_track_id=provider_track_id,
        rank=rank,
        title=title,
        artist_names=artist_names,
        album_name=album_name,
        artwork_url=artwork_url or "",
        duration_ms=duration_ms,
        url=url,
    )


# ---------- 默认注册表 ----------

_KUWO_UNAVAILABLE_REASON = (
    "匿名榜单接口不可用：wapi.kuwo.cn bang songList HTTP 404、"
    "kbangserver 403（2026-09-12 实测）；现网榜单需签名/登录态，项目未配置"
)
_APPLE_UNAVAILABLE_REASON = (
    "iTunes RSS topsongs 已停止下发条目：feed 元数据仍返回 200 但 entry 为空"
    "（2026-09-12 实测 limit=5 entries=0）；MusicKit API 需开发者 token，项目未配置"
)
_SPOTIFY_UNAVAILABLE_REASON = (
    "Spotify 榜单（featured playlists/chart）需 OAuth client credentials，"
    "项目未配置；与点歌搜索 search_spotify 返回 None 的兜底策略一致"
)


def build_default_music_chart_registry() -> MusicChartRegistry:
    """真实可拉通的榜单（≥2，实测 2026-09-12）+ 不可达平台的诚实占位。"""
    return MusicChartRegistry(
        [
            NeteaseChartSource(source_id="netease-hot", category="热歌", chart_id="3778678"),
            NeteaseChartSource(source_id="netease-soaring", category="飙升", chart_id="19723756"),
            QQMusicChartSource(source_id="qqmusic-hot", category="热歌", chart_id="26"),
            KugouChartSource(source_id="kugou-soaring", category="飙升", chart_id="6666"),
            KugouChartSource(source_id="kugou-electronic", category="电音", chart_id="33160"),
            UnavailableChartSource("kuwo-soaring", "kuwo", "飙升", _KUWO_UNAVAILABLE_REASON),
            UnavailableChartSource(
                "apple-music-top", "apple_music", "热歌", _APPLE_UNAVAILABLE_REASON
            ),
            UnavailableChartSource("spotify-top", "spotify", "热歌", _SPOTIFY_UNAVAILABLE_REASON),
        ]
    )


class MusicChartRegistry:
    def __init__(self, sources: Iterable[MusicChartSource] | None = None) -> None:
        self._sources: dict[str, MusicChartSource] = {}
        for source in sources or ():
            self.register(source)

    def register(self, source: MusicChartSource) -> None:
        source_id = str(getattr(source, "source_id", "") or "").strip()
        if not source_id:
            raise ValueError("chart source_id must be non-blank")
        if source_id in self._sources:
            raise ValueError(f"duplicate chart source: {source_id}")
        self._sources[source_id] = source

    def list_sources(self, *, category: str | None = None) -> list[MusicChartSource]:
        sources = list(self._sources.values())
        if category is not None:
            sources = [source for source in sources if source.category == category]
        return sources

    def describe_sources(self, *, category: str | None = None) -> list[dict[str, str]]:
        """每个 source 的注册状态：real/unavailable + 不可达原因（诚实披露）。"""
        described: list[dict[str, str]] = []
        for source in self.list_sources(category=category):
            described.append(
                {
                    "source_id": str(source.source_id),
                    "platform": str(getattr(source, "platform", "") or ""),
                    "category": str(source.category),
                    "chart_id": str(getattr(source, "chart_id", "") or ""),
                    "status": str(getattr(source, "status", "real") or "real"),
                    "unavailability_reason": str(
                        getattr(source, "unavailability_reason", "") or ""
                    ),
                }
            )
        return described

    async def refresh(self, source_id: str, ctx: Any) -> MusicChartSnapshot:
        source = self._sources.get(str(source_id))
        if source is None:
            raise KeyError(f"unknown chart source: {source_id}")
        snapshot = await source.fetch_snapshot(ctx)
        if not isinstance(snapshot, MusicChartSnapshot):
            raise TypeError("chart source must return MusicChartSnapshot")
        return snapshot
