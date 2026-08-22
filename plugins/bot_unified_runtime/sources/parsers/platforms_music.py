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

from plugins.bot_unified_runtime.sources.parsers.http_util import (
    ParseHttpError,
    http_get_json,
    http_get_text,
    http_post_json,
    resolve_short_link,
)
from plugins.bot_unified_runtime.sources.parsers.types import PlatformParse

_SONG_ID_RE = re.compile(r"[?&/#]id=(\d+)")
_163CN_RE = re.compile(r"163cn\.tv|163cn\.com")


# ---------- 网易云 ----------

def _netease_audio_url(song_id: str, *, cookie_header: str = "") -> str:
    """网易云音频直链：优先 enhance/player/url（登录态可拿 VIP 试听），
    兜底 outer/url 直链。拿不到返回空串。"""
    if cookie_header:
        try:
            payload = http_get_json(
                "https://music.163.com/api/song/enhance/player/url"
                f"?ids=[{song_id}]&br=320000",
                referer="https://music.163.com/",
                cookie=cookie_header,
            )
            data = ((payload or {}).get("data") or []) or []
            if data and data[0].get("url"):
                return str(data[0]["url"])
        except ParseHttpError:
            pass
    return f"https://music.163.com/song/media/outer/url?id={song_id}.mp3"


def _netease_song_detail(song_id: str, *, cookie_header: str = "") -> PlatformParse:
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
        # 老接口对失效/下架歌曲返回 name:null。
        raise ParseHttpError(f"netease: song {song_id} unavailable")
    artists = "、".join(item.get("name", "") for item in (song.get("artists") or []))
    album = (song.get("album") or {}).get("name", "")
    cover = (song.get("album") or {}).get("picUrl", "")
    title = song.get("name", "")
    return PlatformParse(
        platform="netease",
        item_id=str(song_id),
        item_kind="music",
        title=str(title),
        author_name=artists,
        summary=f"专辑：{album}" if album else "",
        cover_url=str(cover),
        audio_url=_netease_audio_url(song_id, cookie_header=cookie_header),
        canonical_url=f"https://music.163.com/song?id={song_id}",
        parse_depth="deep",
    )


def parse_netease_music(url: str, *, cookie_header: str = "") -> PlatformParse:
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


def search_netease_music(query: str, *, cookie_header: str = "") -> PlatformParse | None:
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


def parse_qqmusic(url: str, *, cookie_header: str = "") -> PlatformParse:
    match = re.search(r"songDetail/([0-9A-Za-z]+)", url)
    if match:
        mid = match.group(1)
        audio_url = _qqmusic_vkey_url(mid, cookie_header=cookie_header)
        return PlatformParse(
            platform="qqmusic",
            item_id=mid,
            item_kind="music",
            title=f"QQ 音乐歌曲 {mid}",
            summary="（QQ 音乐详情需要登录态，这里只给跳转卡片）",
            audio_url=audio_url,
            canonical_url=f"https://y.qq.com/n/ryqq/songDetail/{mid}",
            parse_depth="deep" if audio_url else "shallow",
            stats={"music_card": {"type": "qq", "id": mid}},
        )
    raise ParseHttpError(f"qqmusic: no song mid in {url}")


def search_qqmusic(query: str, *, cookie_header: str = "") -> PlatformParse | None:
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
    return PlatformParse(
        platform="qqmusic",
        item_id=mid,
        item_kind="music",
        title=str(song.get("songname") or song.get("name") or ""),
        author_name=singers,
        summary=f"专辑：{song.get('albumname') or ''}",
        audio_url=audio_url,
        canonical_url=f"https://y.qq.com/n/ryqq/songDetail/{mid}",
        parse_depth="deep" if audio_url else "shallow",
        stats={"music_card": {"type": "qq", "id": mid}},
    )


# ---------- 酷我 / 酷狗 ----------

def parse_kuwo(url: str, *, cookie_header: str = "") -> PlatformParse:
    match = re.search(r"playDetail/(\d+)", url)
    if not match:
        raise ParseHttpError(f"kuwo: no rid in {url}")
    rid = match.group(1)
    # 官方接口匿名 403，只能跳转卡片。
    return PlatformParse(
        platform="kuwo",
        item_id=rid,
        item_kind="music",
        title=f"酷我音乐歌曲 {rid}",
        summary="（酷我官方接口已收紧，这里只给跳转链接）",
        canonical_url=f"https://www.kuwo.cn/playDetail/{rid}",
        parse_depth="shallow",
    )


def search_kuwo(query: str, *, cookie_header: str = "") -> PlatformParse | None:
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
    return PlatformParse(
        platform="kuwo",
        item_id=str(item.get("rid") or item.get("songid") or ""),
        item_kind="music",
        title=str(item.get("name") or item.get("song") or ""),
        author_name=str(item.get("author") or item.get("singer") or ""),
        audio_url=str(item.get("url") or ""),
        canonical_url=str(item.get("link") or ""),
        parse_depth="shallow",
    )


def _kugou_play_url(file_hash: str, *, cookie_header: str = "") -> str:
    try:
        payload = http_get_json(
            f"http://m.kugou.com/app/i/getSongInfo.php?cmd=playInfo&hash={file_hash}",
            referer="https://www.kugou.com/",
            cookie=cookie_header,
        )
    except ParseHttpError:
        return ""
    return str(payload.get("url") or "")


def parse_kugou(url: str, *, cookie_header: str = "") -> PlatformParse:
    match = re.search(r"hash=([0-9A-Fa-f]{16,})", url)
    if not match:
        raise ParseHttpError(f"kugou: no file hash in {url}")
    file_hash = match.group(1)
    payload = http_get_json(
        f"http://m.kugou.com/app/i/getSongInfo.php?cmd=playInfo&hash={file_hash}",
        referer="https://www.kugou.com/",
        cookie=cookie_header,
    )
    audio_url = str(payload.get("url") or "")
    return PlatformParse(
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


def search_kugou(query: str, *, cookie_header: str = "") -> PlatformParse | None:
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
    return PlatformParse(
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


def parse_apple_music(url: str) -> PlatformParse:
    match = re.search(r"[?&]i=(\d+)", url)
    if not match:
        raise ParseHttpError(f"apple music: no track id in {url}")
    track = _itunes_lookup(match.group(1))
    return PlatformParse(
        platform="apple_music",
        item_id=str(track.get("trackId") or match.group(1)),
        item_kind="music",
        title=str(track.get("trackName") or ""),
        author_name=str(track.get("artistName") or ""),
        summary=f"专辑：{track.get('collectionName') or ''}",
        cover_url=str(track.get("artworkUrl100") or "").replace("100x100", "300x300"),
        audio_url=str(track.get("previewUrl") or ""),
        canonical_url=str(track.get("trackViewUrl") or url),
        parse_depth="deep",
    )


def search_apple_music(query: str) -> PlatformParse | None:
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
            return PlatformParse(
                platform="apple_music",
                item_id=str(track.get("trackId") or ""),
                item_kind="music",
                title=str(track.get("trackName") or ""),
                author_name=str(track.get("artistName") or ""),
                summary=f"专辑：{track.get('collectionName') or ''}（30 秒试听）",
                cover_url=str(track.get("artworkUrl100") or "").replace("100x100", "300x300"),
                audio_url=str(track.get("previewUrl") or ""),
                canonical_url=str(track.get("trackViewUrl") or ""),
                parse_depth="deep",
            )
    return None


def parse_spotify(url: str, *, cookie_header: str = "", proxy: str = "") -> PlatformParse:
    match = re.search(r"spotify\.com/(track|album)/([0-9A-Za-z]+)", url)
    if not match:
        raise ParseHttpError(f"spotify: no track id in {url}")
    kind, item_id = match.group(1), match.group(2)
    try:
        final_url, payload = http_get_text(
            f"https://open.spotify.com/oembed?url={urllib.parse.quote(url)}",
            timeout=8,
            proxy=proxy,
        )
        import json

        data = json.loads(payload)
        title = str(data.get("title") or "")
    except Exception:  # noqa: BLE001 - oEmbed 拿不到就降级成链接卡。
        title = f"Spotify {kind} {item_id}"
    return PlatformParse(
        platform="spotify",
        item_id=item_id,
        item_kind="music",
        title=title,
        summary="（Spotify 大陆不可直连，仅信息卡）",
        canonical_url=url,
        parse_depth="shallow",
    )


def search_spotify(query: str) -> PlatformParse | None:
    # 需要注册 client credentials，默认不做搜索，返回 None 由其他平台兜底。
    return None
