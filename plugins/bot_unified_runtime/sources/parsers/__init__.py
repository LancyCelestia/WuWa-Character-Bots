"""平台解析器注册表：链接识别规则 + 解析函数 + 点歌搜索提供方。

用法（能力层）：::

    registry = build_content_parser_registry(config)
    match = registry["registry"].match(source_input)[0]
    item = registry["parsers"][match.parser_id](url)
"""

from __future__ import annotations

import re
from typing import Any, Callable

from plugins.bot_unified_runtime.contracts.media import ParserRule, SourceInput
from plugins.bot_unified_runtime.sources.parsers.platforms_bilibili import (
    PlatformParse,
    parse_bilibili,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_generic import (
    parse_douyin,
    parse_kurobbs,
    parse_miyoushe,
    parse_skland,
    parse_twitter_x,
    parse_xiaoheihe,
    parse_xiaohongshu,
    parse_youtube,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_music import (
    parse_apple_music,
    parse_kugou,
    parse_kuwo,
    parse_netease_music,
    parse_qqmusic,
    parse_spotify,
    search_apple_music,
    search_kugou,
    search_kuwo,
    search_netease_music,
    search_qqmusic,
    search_spotify,
)
from plugins.bot_unified_runtime.sources.registry import ParserRegistry

_HTTP_URL_RE = re.compile(r"https?://[^\s<>\"'（）()【】\[\]{}]+")

ParseFn = Callable[[str], PlatformParse]

# parser_id → (平台显示名, 链接正则, 解析函数, 优先级)
_PLATFORM_RULES: list[tuple[str, str, list[str], ParseFn, int]] = [
    (
        "bilibili",
        "B站",
        [r"bilibili\.com/video/(BV[0-9A-Za-z]{10}|av\d+)", r"b23\.tv/[0-9A-Za-z]+", r"bili2233\.cn/[0-9A-Za-z]+"],
        parse_bilibili,
        10,
    ),
    (
        "douyin",
        "抖音",
        [r"v\.douyin\.com/[0-9A-Za-z]+/", r"douyin\.com/video/\d+"],
        parse_douyin,
        20,
    ),
    (
        "xiaohongshu",
        "小红书",
        [r"xhslink\.com/[0-9A-Za-z]+", r"xiaohongshu\.com/explore/[0-9a-f]+"],
        parse_xiaohongshu,
        21,
    ),
    (
        "youtube",
        "油管",
        [r"youtube\.com/watch\?v=[\w-]+", r"youtu\.be/[\w-]+", r"youtube\.com/shorts/[\w-]+"],
        parse_youtube,
        22,
    ),
    (
        "twitter",
        "推特",
        [r"(twitter|x)\.com/[^/]+/status/\d+"],
        parse_twitter_x,
        23,
    ),
    (
        "xiaoheihe",
        "小黑盒",
        [r"xiaoheihe\.cn/v3/bbs/app/[^\s]+", r"api\.xiaoheihe\.cn/v3/bbs/app/api/web_view\?[^\s]*link_id=\d+"],
        parse_xiaoheihe,
        24,
    ),
    (
        "miyoushe",
        "米游社",
        [r"miyoushe\.com/[^\s]+article/[^\s]+", r"m\.bbs\.miyoushe\.com/[^\s]+"],
        parse_miyoushe,
        25,
    ),
    (
        "skland",
        "森空岛",
        [r"skland\.com/article/[^\s]+"],
        parse_skland,
        26,
    ),
    (
        "kurobbs",
        "库街区",
        [r"kurobbs\.com/[^\s]+"],
        parse_kurobbs,
        27,
    ),
    (
        "netease_music",
        "网易云音乐",
        [r"music\.163\.com/(#/)?(song|album|playlist|djradio)\?[^\s]*id=\d+", r"163cn\.tv/[0-9A-Za-z]+"],
        parse_netease_music,
        30,
    ),
    (
        "qqmusic",
        "QQ音乐",
        [r"y\.qq\.com/n/ryqq/(songDetail|song)/[0-9A-Za-z]+", r"i\.y\.qq\.com/v8/playsong\.html\?[^\s]*songmid=[0-9A-Za-z]+"],
        parse_qqmusic,
        31,
    ),
    (
        "kuwo",
        "酷我音乐",
        [r"kuwo\.cn/playDetail/\d+"],
        parse_kuwo,
        32,
    ),
    (
        "kugou",
        "酷狗音乐",
        [r"kugou\.com/song/#hash=[0-9A-Fa-f]{16,}", r"t3\.kugou\.com/song\.html\?id=\d+"],
        parse_kugou,
        33,
    ),
    (
        "apple_music",
        "Apple Music",
        [r"music\.apple\.com/[a-z]{2}/(album|song)/[^?\s]+\?i=\d+"],
        parse_apple_music,
        34,
    ),
    (
        "spotify",
        "Spotify",
        [r"open\.spotify\.com/(track|album)/[0-9A-Za-z]+"],
        parse_spotify,
        35,
    ),
]

# 点歌搜索提供方（按顺序尝试，失败自动换下一个）。
_MUSIC_SEARCH_PROVIDERS: list[tuple[str, str, Callable[[str], PlatformParse | None]]] = [
    ("netease_music", "网易云", search_netease_music),
    ("apple_music", "Apple Music", search_apple_music),
    ("kugou", "酷狗", search_kugou),
    ("qqmusic", "QQ音乐", search_qqmusic),
    ("kuwo", "酷我", search_kuwo),
    ("spotify", "Spotify", search_spotify),
]


def extract_http_urls(text: str) -> list[str]:
    """从消息文本提取 http(s) 链接（含中文括号内链接）。"""
    candidates: list[str] = []
    for match in _HTTP_URL_RE.findall(text or ""):
        raw = match
        while raw and raw[-1] in ".,;:!?，。；：！？":
            raw = raw[:-1]
        if raw not in candidates:
            candidates.append(raw)
    return candidates


def platform_rules() -> list[tuple[str, str, list[str], ParseFn, int]]:
    return [*_PLATFORM_RULES]


def build_content_parser_registry(
    enabled_platforms: list[str] | None = None,
) -> dict[str, Any]:
    """构建链接解析注册表。

    ``enabled_platforms`` 为空 = 全部启用；否则只启用名单内平台。
    """
    allowed = {str(name).strip().lower() for name in (enabled_platforms or [])}
    registry = ParserRegistry()
    parsers: dict[str, ParseFn] = {}
    for parser_id, display_name, patterns, parse_fn, priority in _PLATFORM_RULES:
        if allowed and parser_id not in allowed:
            continue
        registry.register(
            ParserRule(
                parser_id=parser_id,
                source_id=display_name,
                url_patterns=patterns,
                priority=priority,
            )
        )
        parsers[parser_id] = parse_fn
    return {"registry": registry, "parsers": parsers}


def music_search_providers(
    enabled_platforms: list[str] | None = None,
) -> list[tuple[str, str, Callable[[str], PlatformParse | None]]]:
    """点歌搜索提供方（按配置过滤并保持顺序）。"""
    allowed = {str(name).strip().lower() for name in (enabled_platforms or [])}
    if not allowed:
        return [*_MUSIC_SEARCH_PROVIDERS]
    return [
        (parser_id, display_name, search_fn)
        for parser_id, display_name, search_fn in _MUSIC_SEARCH_PROVIDERS
        if parser_id in allowed
    ]


def build_source_input(text: str, *, request_id: str = "parser") -> SourceInput:
    return SourceInput(
        request_id=request_id,
        session_id="",
        capability_id="bot.content",
        raw_text=text,
        urls=extract_http_urls(text),
    )
