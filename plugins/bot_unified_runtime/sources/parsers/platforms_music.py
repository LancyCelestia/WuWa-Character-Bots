"""音乐平台：链接解析 + 点歌搜索（网易云 / QQ / 酷我 / 酷狗 / Spotify / Apple）。

设计原则（参考调研报告 research/音乐点歌接口调研报告.md）：

- 只用「匿名可用」的官方接口拿信息与试听；需要登录/签名的平台
  只做浅层解析（标题+封面+跳转链接），绝不伪造凭据。
- 音频 URL 一律作为可选项：拿不到就发信息卡，不报错。
- Apple iTunes Search 完全公开（含 30s 试听直链）；网易云走官方
  song/detail + outer/url 兜底；酷狗 playInfo 试拿 URL（可能为空）。
"""

from __future__ import annotations

import re
import urllib.parse
from datetime import date

from plugins.bot_unified_runtime.contracts.media import (
    ParsedContent,
    build_parsed_content,
)
from plugins.bot_unified_runtime.contracts.music import (
    MusicAlbumRef,
    MusicContributor,
    MusicEngagement,
    MusicTrack,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import (
    ParseHttpError,
    http_get_json,
    http_get_text,
    http_post_json,
    resolve_short_link,
)

_SONG_ID_RE = re.compile(r"[?&/#]id=(\d+)")
_163CN_RE = re.compile(r"163cn\.tv|163cn\.com")


def _optional_date(value: object) -> date | None:
    text = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


def _music_track(
    *,
    provider: str,
    track_id: str,
    title: str,
    artists: list[dict] | None = None,
    album_id: object = None,
    album_name: str = "",
    artwork_url: str = "",
    duration_ms: object = None,
    release_date: object = None,
    genres: list[str] | None = None,
    explicit: bool | None = None,
    aliases: list[str] | None = None,
    audio_url: str = "",
    extra: dict | None = None,
    engagement: MusicEngagement | None = None,
) -> MusicTrack:
    contributors = [
        MusicContributor(
            person_id=str(item.get("id")) if item.get("id") is not None else None,
            name=str(item.get("name") or ""),
            roles=["performer"],
        )
        for item in (artists or [])
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]
    duration = (
        int(duration_ms)
        if isinstance(duration_ms, (int, float)) and duration_ms >= 0
        else None
    )
    return MusicTrack(
        provider=provider,
        provider_track_id=track_id,
        title=title,
        aliases=[str(value) for value in (aliases or []) if str(value).strip()],
        contributors=contributors,
        album=(
            MusicAlbumRef(
                provider_album_id=str(album_id) if album_id is not None else None,
                name=album_name,
                artwork_url=artwork_url or None,
            )
            if album_name or album_id is not None or artwork_url
            else None
        ),
        artwork_url=artwork_url or None,
        duration_ms=duration,
        release_date=_optional_date(release_date),
        genres=[str(value) for value in (genres or []) if str(value).strip()],
        explicit=explicit,
        audio_url=audio_url or None,
        platform_extra=dict(extra or {}),
        engagement=engagement or MusicEngagement(),
        limitations=(
            {"engagement.favorite_count": "provider_not_exposed"}
            if not extra or "favorite_count" not in extra
            else {}
        ),
    )


# ---------- 网易云 ----------

def _netease_audio_url(song_id: str, *, cookie_header: str = "") -> str:
    """网易云音频直链：优先 enhance/player/url（登录态可拿 VIP 试听），
    兜底 outer/url 直链。拿不到返回空串。"""
    if cookie_header:
        # 优先最高码率（999000=Hi-Res），拿不到再退 320kbps。
        for bitrate in ("999000", "320000"):
            try:
                payload = http_get_json(
                    "https://music.163.com/api/song/enhance/player/url"
                    f"?ids=[{song_id}]&br={bitrate}",
                    referer="https://music.163.com/",
                    cookie=cookie_header,
                )
                data = ((payload or {}).get("data") or []) or []
                if data and data[0].get("url"):
                    return str(data[0]["url"])
            except ParseHttpError:
                pass
    return f"https://music.163.com/song/media/outer/url?id={song_id}.mp3"


def _netease_song_comments(
    song_id: str, *, cookie_header: str = ""
) -> int | None:
    """读取网易云公开评论总数；接口失败时返回 None，不伪造为 0。"""
    try:
        payload = http_get_json(
            "https://music.163.com/api/v1/resource/comments/"
            f"R_SO_4_{song_id}?limit=1&offset=0",
            referer="https://music.163.com/",
            cookie=cookie_header,
        )
    except ParseHttpError:
        return None
    total = (payload or {}).get("total") if isinstance(payload, dict) else None
    return int(total) if isinstance(total, (int, float)) and total >= 0 else None


def _netease_lyric(
    song_id: str, *, cookie_header: str = ""
) -> dict[str, str]:
    try:
        payload = http_get_json(
            f"https://music.163.com/api/song/lyric?id={song_id}&lv=1&kv=1&tv=-1",
            referer="https://music.163.com/",
            cookie=cookie_header,
        )
    except ParseHttpError:
        return {}
    lyrics: dict[str, str] = {}
    for key, source_key in (("original", "lrc"), ("translated", "tlyric")):
        value = (payload or {}).get(source_key) if isinstance(payload, dict) else None
        text = value.get("lyric") if isinstance(value, dict) else ""
        if text:
            lyrics[key] = str(text)
    return lyrics


def _netease_song_detail(song_id: str, *, cookie_header: str = "") -> ParsedContent:
    payload = http_get_json(
        f"https://music.163.com/api/song/detail?ids=[{song_id}]",
        referer="https://music.163.com/",
        cookie=cookie_header,
    )
    songs = (payload or {}).get("songs") or []
    if not songs:
        raise ParseHttpError("netease song/detail returned no song")
    song = songs[0]
    if not song.get("name"):
        raise ParseHttpError(f"netease: song {song_id} unavailable")

    raw_artists = song.get("artists") or song.get("ar") or []
    contributors = [
        MusicContributor(
            person_id=str(item.get("id")) if item.get("id") is not None else None,
            name=str(item.get("name") or ""),
            roles=["performer"],
        )
        for item in raw_artists
        if isinstance(item, dict) and item.get("name")
    ]
    album_data = song.get("album") or song.get("al") or {}
    album_name = str(album_data.get("name") or "")
    cover = str(album_data.get("picUrl") or album_data.get("pic_str") or "")
    aliases = [str(value) for value in (song.get("alias") or []) if str(value).strip()]
    duration = song.get("dt") or song.get("duration")
    duration_ms = int(duration) if isinstance(duration, (int, float)) and duration >= 0 else None
    comment_count = _netease_song_comments(song_id, cookie_header=cookie_header)
    engagement = MusicEngagement(
        comment_count=comment_count,
        popularity=(
            int(song["pop"])
            if isinstance(song.get("pop"), (int, float)) and song["pop"] >= 0
            else None
        ),
    )
    limitations = {}
    if engagement.favorite_count is None:
        limitations["engagement.favorite_count"] = "provider_not_exposed"
    track = _music_track(
        provider="netease",
        track_id=str(song_id),
        title=str(song["name"]),
        artists=raw_artists,
        album_id=album_data.get("id"),
        album_name=album_name,
        artwork_url=cover,
        duration_ms=duration_ms,
        aliases=aliases,
        audio_url=_netease_audio_url(song_id, cookie_header=cookie_header),
        extra={"comment_count": comment_count, "popularity": engagement.popularity},
        engagement=engagement,
    ).model_copy(update={"lyrics": _netease_lyric(song_id, cookie_header=cookie_header)})
    artists = "、".join(item.name for item in contributors)
    return build_parsed_content(
        platform="netease",
        item_id=str(song_id),
        item_kind="music",
        title=track.title,
        author_name=artists,
        summary=f"专辑：{album_name}" if album_name else "",
        cover_url=cover,
        audio_url=track.audio_url or "",
        canonical_url=f"https://music.163.com/song?id={song_id}",
        parse_depth="deep",
        music=track,
    )


def parse_netease_music(url: str, *, cookie_header: str = "") -> ParsedContent:
    final_url = url
    if _163CN_RE.search(url):
        final_url = resolve_short_link(url)
    match = _SONG_ID_RE.search(final_url)
    if match:
        return _netease_song_detail(match.group(1), cookie_header=cookie_header)
    raise ParseHttpError(f"netease: no song id in {final_url}")


# 翻唱/改编等非原唱关键词（用于点歌排序：同名时优先原唱）。
_COVER_HINTS = (
    "翻唱",
    "cover",
    "remix",
    "深情版",
    "dj",
    "伴奏",
    "纯音乐",
    "钢琴",
    "吉他",
    "改编",
    "live",
    "现场",
)


def _looks_cover(song: dict) -> bool:
    album = str((song.get("album") or {}).get("name") or "").lower()
    name = str(song.get("name") or "").lower()
    return any(hint in album or hint in name for hint in _COVER_HINTS)


def search_netease_music(query: str, *, cookie_header: str = "") -> ParsedContent | None:
    """点歌搜索：官方旧搜索接口（匿名可用）。

    老接口排序与官网不同（翻唱会排前面），这里多拉几条：
    同名精确匹配优先，其次非翻唱结果，最后才取第一名。
    """
    encoded = urllib.parse.quote(query)
    payload = http_get_json(
        f"https://music.163.com/api/search/get/web?s={encoded}&type=1&limit=15&offset=0",
        referer="https://music.163.com/",
        cookie=cookie_header,
    )
    songs = ((payload or {}).get("result") or {}).get("songs") or []
    if not songs:
        return None
    exact = [song for song in songs if str(song.get("name", "")).strip() == query.strip()]
    pool = exact or songs
    picked = next((song for song in pool if not _looks_cover(song)), pool[0])
    return _netease_song_detail(str(picked["id"]), cookie_header=cookie_header)


# ---------- QQ 音乐 ----------

def _qqmusic_vkey_url(song_mid: str, *, cookie_header: str = "") -> str:
    """QQ 音乐音频直链：CgiGetVkey。匿名已被收紧（purl 空），
    带登录 cookie（psrf_musickey 等）才有机会出链；失败返回空串。"""
    if not cookie_header:
        return ""
    body = {
        "req_1": {
            "module": "vkey.GetVkeyServer",
            "method": "CgiGetVkey",
            "param": {
                "filename": [f"M500{song_mid}.mp3"],
                "guid": "10000",
                "songmid": [song_mid],
                "songtype": [0],
                "uin": "0",
                "loginflag": 1,
                "platform": "20",
            },
        },
        "loginUin": "0",
        "comm": {"uin": "0", "format": "json", "ct": 24, "cv": 0},
    }
    try:
        payload = http_post_json(
            "https://u.y.qq.com/cgi-bin/musicu.fcg",
            body,
            referer="https://y.qq.com/",
            cookie=cookie_header,
        )
    except ParseHttpError:
        return ""
    data = ((payload or {}).get("req_1") or {}).get("data") or {}
    sips = data.get("sip") or []
    purl = ((data.get("midurlinfo") or []) or [{}])[0].get("purl") or ""
    if not sips or not purl:
        return ""
    return f"{sips[0]}{purl}"


def parse_qqmusic(url: str, *, cookie_header: str = "") -> ParsedContent:
    match = re.search(r"songDetail/([0-9A-Za-z]+)", url)
    if match:
        mid = match.group(1)
        audio_url = _qqmusic_vkey_url(mid, cookie_header=cookie_header)
        track = _music_track(
            provider="qqmusic",
            track_id=mid,
            title=f"QQ 音乐歌曲 {mid}",
            audio_url=audio_url,
        )
        return build_parsed_content(
            platform="qqmusic",
            item_id=mid,
            item_kind="music",
            title=track.title,
            summary="（QQ 音乐详情需要登录态，这里只给跳转卡片）",
            audio_url=audio_url,
            canonical_url=f"https://y.qq.com/n/ryqq/songDetail/{mid}",
            parse_depth="deep" if audio_url else "shallow",
            stats={"music_card": {"type": "qq", "id": mid}},
            music=track,
        )
    raise ParseHttpError(f"qqmusic: no song mid in {url}")


def search_qqmusic(query: str, *, cookie_header: str = "") -> ParsedContent | None:
    encoded = urllib.parse.quote(query)
    payload = http_get_json(
        "https://c.y.qq.com/soso/fcgi-bin/client_search_cp"
        f"?w={encoded}&format=json&p=1&n=1&aggr=1&cr=1&new_json=1",
        referer="https://y.qq.com/",
        cookie=cookie_header,
    )
    songs = (
        ((payload or {}).get("data") or {}).get("song") or {}
    ).get("list") or []
    if not songs:
        return None
    song = songs[0]
    singers = "、".join(item.get("name", "") for item in (song.get("singer") or []))
    mid = str(song.get("mid") or "")
    audio_url = _qqmusic_vkey_url(mid, cookie_header=cookie_header)
    track = _music_track(
        provider="qqmusic",
        track_id=mid,
        title=str(song.get("songname") or song.get("name") or ""),
        artists=song.get("singer") or [],
        album_id=song.get("albumid"),
        album_name=str(song.get("albumname") or ""),
        artwork_url=str(song.get("album_pic") or song.get("album_pic300") or ""),
        duration_ms=(
            int(song["interval"]) * 1000
            if isinstance(song.get("interval"), (int, float))
            and song["interval"] >= 0
            else None
        ),
        audio_url=audio_url,
    )
    return build_parsed_content(
        platform="qqmusic",
        item_id=mid,
        item_kind="music",
        title=track.title,
        author_name=singers,
        summary=f"专辑：{track.album.name if track.album else ''}",
        audio_url=audio_url,
        canonical_url=f"https://y.qq.com/n/ryqq/songDetail/{mid}",
        parse_depth="deep" if audio_url else "shallow",
        stats={"music_card": {"type": "qq", "id": mid}},
        music=track,
    )


# ---------- 酷我 / 酷狗 ----------

# 网页详情页两种路径：camelCase playDetail 与 snake_case play_detail。
_KUWO_RID_RE = re.compile(r"play_?[Dd]etail/(\d+)")


def _kuwo_music_info(rid: str) -> dict | None:
    """酷我 mob 接口：wapi.kuwo.cn musicInfo（匿名可用，无需 cookie）。
    歌名/歌手/专辑/封面从这里拿；失败（含下架）返回 None，上层退回跳转卡片。"""
    try:
        payload = http_get_json(
            f"https://wapi.kuwo.cn/api/www/music/musicInfo?mid={rid}&httpsStatus=1",
            referer="https://www.kuwo.cn/",
            timeout=8,
        )
    except ParseHttpError:
        return None
    if not isinstance(payload, dict) or payload.get("code") != 200:
        return None
    data = payload.get("data")
    return data if isinstance(data, dict) else None


def _kuwo_audio_url(rid: str) -> str:
    """酷我音频直链：antiserver convert_url（匿名可用，付费歌也给试听直链）。
    失败返回空串。"""
    try:
        _, text = http_get_text(
            "https://antiserver.kuwo.cn/anti.s"
            f"?type=convert_url&rid={rid}&format=mp3&response=url",
            timeout=8,
        )
    except ParseHttpError:
        return ""
    url = text.strip().strip('"')
    return url if url.startswith("http") else ""


def parse_kuwo(url: str, *, cookie_header: str = "") -> ParsedContent:
    match = _KUWO_RID_RE.search(url)
    if not match:
        raise ParseHttpError(f"kuwo: no rid in {url}")
    rid = match.group(1)
    info = _kuwo_music_info(rid) or {}
    title = str((info or {}).get("name") or "")
    if not title:
        # mob 接口拿不到时退回跳转卡片（与旧行为一致）。
        return build_parsed_content(
            platform="kuwo",
            item_id=rid,
            item_kind="music",
            title=f"酷我音乐歌曲 {rid}",
            summary="（酷我官方接口已收紧，这里只给跳转链接）",
            canonical_url=f"https://www.kuwo.cn/playDetail/{rid}",
            parse_depth="shallow",
        )
    album = str(info.get("album") or "")
    return build_parsed_content(
        platform="kuwo",
        item_id=rid,
        item_kind="music",
        title=title,
        author_name=str(info.get("artist") or ""),
        summary=f"专辑：{album}" if album else "",
        cover_url=str(info.get("pic") or info.get("albumpic") or ""),
        audio_url=_kuwo_audio_url(rid),
        canonical_url=f"https://www.kuwo.cn/playDetail/{rid}",
        parse_depth="deep",
    )


def search_kuwo(query: str, *, cookie_header: str = "") -> ParsedContent | None:
    # 官方搜索匿名 403；用公开聚合接口（第三方，仅信息+直链，失败返回 None）。
    encoded = urllib.parse.quote(query)
    try:
        payload = http_get_json(
            f"https://api.suyanw.cn/api/kw.php?msg={encoded}&n=1",
            timeout=8,
        )
    except ParseHttpError:
        return None
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list) or not data:
        return None
    item = data[0]
    return build_parsed_content(
        platform="kuwo",
        item_id=str(item.get("rid") or item.get("songid") or ""),
        item_kind="music",
        title=str(item.get("name") or item.get("song") or ""),
        author_name=str(item.get("author") or item.get("singer") or ""),
        audio_url=str(item.get("url") or ""),
        canonical_url=str(item.get("link") or ""),
        parse_depth="shallow",
    )


def _kugou_get_song_info(file_hash: str, *, cookie_header: str = "") -> dict:
    """酷狗现有链路：m.kugou.com getSongInfo（按文件 hash 拿信息+直链）。"""
    payload = http_get_json(
        f"http://m.kugou.com/app/i/getSongInfo.php?cmd=playInfo&hash={file_hash}",
        referer="https://www.kugou.com/",
        cookie=cookie_header,
    )
    return payload if isinstance(payload, dict) else {}


def _kugou_play_url(file_hash: str, *, cookie_header: str = "") -> str:
    try:
        payload = _kugou_get_song_info(file_hash, cookie_header=cookie_header)
    except ParseHttpError:
        return ""
    return str(payload.get("url") or "")


def parse_kugou(url: str, *, cookie_header: str = "") -> ParsedContent:
    match = re.search(r"hash=([0-9A-Fa-f]{16,})", url)
    if not match:
        raise ParseHttpError(f"kugou: no file hash in {url}")
    file_hash = match.group(1)
    payload = _kugou_get_song_info(file_hash, cookie_header=cookie_header)
    audio_url = str(payload.get("url") or "")
    return build_parsed_content(
        platform="kugou",
        item_id=file_hash,
        item_kind="music",
        title=str(payload.get("songName") or ""),
        author_name=str(payload.get("singerName") or ""),
        summary=f"专辑：{payload.get('album_name') or ''}",
        cover_url=str(payload.get("imgUrl") or ""),
        audio_url=audio_url,
        canonical_url=f"https://www.kugou.com/song/#hash={file_hash}",
        parse_depth="deep",
    )


def _kugou_mixsong_file_hash(mix_hash: str, *, cookie_header: str = "") -> str:
    """mixsong 短 hash → 32 位文件 hash：抓 mixsong 详情页提取（页面内嵌 JSON）。"""
    _, html = http_get_text(
        f"https://www.kugou.com/mixsong/{mix_hash}.html",
        referer="https://www.kugou.com/",
        cookie=cookie_header,
    )
    match = re.search(r'hash["\']?\s*[:=]\s*["\']?([0-9A-Fa-f]{32})', html)
    if not match:
        raise ParseHttpError(f"kugou: no file hash on mixsong page {mix_hash}")
    return match.group(1)


def parse_kugou_mixsong(url: str, *, cookie_header: str = "") -> ParsedContent:
    """酷狗 mixsong 详情页（/mixsong/{hash}.html）：页面提取文件 hash 后
    复用 m.kugou.com getSongInfo 现有链路拿歌名/歌手/封面/直链。"""
    match = re.search(r"mixsong/([0-9A-Za-z]+)", url)
    if not match:
        raise ParseHttpError(f"kugou: no mixsong hash in {url}")
    mix_hash = match.group(1)
    file_hash = _kugou_mixsong_file_hash(mix_hash, cookie_header=cookie_header)
    payload = _kugou_get_song_info(file_hash, cookie_header=cookie_header)
    if not payload.get("songName"):
        raise ParseHttpError(f"kugou: mixsong {mix_hash} unavailable")
    cover = str(payload.get("album_img") or payload.get("imgUrl") or "")
    return build_parsed_content(
        platform="kugou",
        item_id=file_hash,
        item_kind="music",
        title=str(payload.get("songName") or ""),
        author_name=str(payload.get("author_name") or payload.get("singerName") or ""),
        cover_url=cover.replace("{size}", "480"),
        audio_url=str(payload.get("url") or ""),
        canonical_url=f"https://www.kugou.com/mixsong/{mix_hash}.html",
        parse_depth="deep",
    )


def search_kugou(query: str, *, cookie_header: str = "") -> ParsedContent | None:
    encoded = urllib.parse.quote(query)
    payload = http_get_json(
        f"http://msearchcdn.kugou.com/api/v3/search/song?plat=0&keyword={encoded}"
        "&tagtype=全部&pagesize=1&version=9108",
        referer="https://www.kugou.com/",
        cookie=cookie_header,
    )
    items = ((payload or {}).get("data") or {}).get("info") or []
    if not items:
        return None
    item = items[0]
    file_hash = str(item.get("hash") or "")
    return build_parsed_content(
        platform="kugou",
        item_id=file_hash,
        item_kind="music",
        title=str(item.get("songname") or ""),
        author_name=str(item.get("singername") or ""),
        summary=f"专辑：{item.get('album_name') or ''}",
        cover_url=f"https://imge.kugou.com/stdmusic/{item.get('album_id')}.jpg"
        if item.get("album_id")
        else "",
        audio_url=_kugou_play_url(file_hash, cookie_header=cookie_header),
        canonical_url=f"https://www.kugou.com/song/#hash={file_hash}",
        parse_depth="deep",
    )


# ---------- Apple Music / Spotify ----------

def _itunes_lookup(track_id: str) -> dict:
    """iTunes lookup：曲目可能在特定区商店缺失，按 大陆→美国→全球 顺序回退。"""
    for country in ("cn", "us", ""):
        suffix = f"&country={country}" if country else ""
        try:
            payload = http_get_json(
                f"https://itunes.apple.com/lookup?id={track_id}{suffix}"
            )
        except ParseHttpError:
            continue
        results = (payload or {}).get("results") or []
        if results:
            return results[0]
    raise ParseHttpError(f"itunes lookup: no track for {track_id}")


def parse_apple_music(url: str) -> ParsedContent:
    match = re.search(r"[?&]i=(\d+)", url)
    if not match:
        raise ParseHttpError(f"apple music: no track id in {url}")
    track = _itunes_lookup(match.group(1))
    provider_track = _music_track(
        provider="apple_music",
        track_id=str(track.get("trackId") or match.group(1)),
        title=str(track.get("trackName") or ""),
        artists=[{"name": str(track.get("artistName") or "")}],
        album_id=track.get("collectionId"),
        album_name=str(track.get("collectionName") or ""),
        artwork_url=str(track.get("artworkUrl100") or "").replace("100x100", "300x300"),
        duration_ms=track.get("trackTimeMillis"),
        release_date=track.get("releaseDate"),
        genres=[str(track.get("primaryGenreName") or "")],
        explicit=track.get("trackExplicitness") == "explicit"
        if track.get("trackExplicitness") is not None
        else track.get("isExplicit"),
        audio_url=str(track.get("previewUrl") or ""),
    )
    return build_parsed_content(
        platform="apple_music",
        item_id=provider_track.provider_track_id,
        item_kind="music",
        title=provider_track.title,
        author_name=str(track.get("artistName") or ""),
        summary=f"专辑：{track.get('collectionName') or ''}",
        cover_url=provider_track.artwork_url or "",
        audio_url=provider_track.audio_url or "",
        canonical_url=str(track.get("trackViewUrl") or url),
        parse_depth="deep",
        music=provider_track,
    )


def search_apple_music(query: str) -> ParsedContent | None:
    encoded = urllib.parse.quote(query)
    # 中文曲目在大陆商店缺失时回退美国商店。
    for country in ("cn", "us"):
        payload = http_get_json(
            "https://itunes.apple.com/search"
            f"?term={encoded}&country={country}&media=music&entity=song&limit=1"
        )
        results = (payload or {}).get("results") or []
        if results:
            track = results[0]
            provider_track = _music_track(
                provider="apple_music",
                track_id=str(track.get("trackId") or ""),
                title=str(track.get("trackName") or ""),
                artists=[{"name": str(track.get("artistName") or "")}],
                album_id=track.get("collectionId"),
                album_name=str(track.get("collectionName") or ""),
                artwork_url=str(track.get("artworkUrl100") or "").replace("100x100", "300x300"),
                duration_ms=track.get("trackTimeMillis"),
                release_date=track.get("releaseDate"),
                genres=[str(track.get("primaryGenreName") or "")],
                explicit=track.get("trackExplicitness") == "explicit"
                if track.get("trackExplicitness") is not None
                else track.get("isExplicit"),
                audio_url=str(track.get("previewUrl") or ""),
            )
            return build_parsed_content(
                platform="apple_music",
                item_id=provider_track.provider_track_id,
                item_kind="music",
                title=provider_track.title,
                author_name=str(track.get("artistName") or ""),
                summary=f"专辑：{track.get('collectionName') or ''}（30 秒试听）",
                cover_url=provider_track.artwork_url or "",
                audio_url=provider_track.audio_url or "",
                canonical_url=str(track.get("trackViewUrl") or ""),
                parse_depth="deep",
                music=provider_track,
            )
    return None


def parse_spotify(url: str, *, cookie_header: str = "", proxy: str = "") -> ParsedContent:
    match = re.search(r"spotify\.com/(track|album)/([0-9A-Za-z]+)", url)
    if not match:
        raise ParseHttpError(f"spotify: no track id in {url}")
    kind, item_id = match.group(1), match.group(2)
    try:
        _, payload = http_get_text(
            f"https://open.spotify.com/oembed?url={urllib.parse.quote(url)}",
            timeout=8,
            proxy=proxy,
        )
        import json

        data = json.loads(payload)
        title = str(data.get("title") or "")
    except Exception:  # noqa: BLE001 - oEmbed 拿不到就降级成链接卡。
        title = f"Spotify {kind} {item_id}"
    return build_parsed_content(
        platform="spotify",
        item_id=item_id,
        item_kind="music",
        title=title,
        summary="（Spotify 大陆不可直连，仅信息卡）",
        canonical_url=url,
        parse_depth="shallow",
    )


def search_spotify(query: str) -> ParsedContent | None:
    # 需要注册 client credentials，默认不做搜索，返回 None 由其他平台兜底。
    return None
