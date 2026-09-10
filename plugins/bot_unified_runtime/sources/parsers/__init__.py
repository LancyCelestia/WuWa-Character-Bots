"""平台解析器注册表：链接识别规则 + 解析函数 + 点歌搜索提供方。

用法（能力层）：::

    registry = build_content_parser_registry(config)
    match = registry["registry"].match(source_input)[0]
    item = registry["parsers"][match.parser_id](url)
"""

from __future__ import annotations

import functools
import re
from collections.abc import Callable
from typing import Any

from plugins.bot_unified_runtime.contracts.media import (
    ParserRule,
    SourceInput,
    build_parsed_content,
)
from plugins.bot_unified_runtime.sources.parsers.cookies import (
    PlatformCookieProvider,
    build_platform_cookie_provider,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_acfun import parse_acfun
from plugins.bot_unified_runtime.sources.parsers.platforms_allcpp import parse_allcpp
from plugins.bot_unified_runtime.sources.parsers.platforms_bilibili import (
    ParsedContent,
    parse_bilibili,
    parse_bilibili_show,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_bilibili_goods import (
    parse_bilibili_goods,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_community import (
    parse_5eplay,
    parse_coolapk,
    parse_ds163,
    parse_hupu,
    parse_wmpvp,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_discourse import (
    parse_linuxdo,
    parse_zlb,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_douban import parse_douban
from plugins.bot_unified_runtime.sources.parsers.platforms_epic import parse_epic
from plugins.bot_unified_runtime.sources.parsers.platforms_facebook import (
    parse_facebook,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_generic import (
    parse_douyin,
    parse_pixiv_contest,
    parse_pixiv_novel,
    parse_pixiv_novel_series,
    parse_pixiv_ranking,
    parse_pixiv_user,
    parse_twitter_x,
    parse_xiaohongshu,
    parse_youtube,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_github import parse_github
from plugins.bot_unified_runtime.sources.parsers.platforms_huajia import parse_huajia
from plugins.bot_unified_runtime.sources.parsers.platforms_kuaishou import (
    parse_kuaishou,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_kurobbs import (
    parse_kurobbs as parse_kurobbs_v2,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_lofter import parse_lofter
from plugins.bot_unified_runtime.sources.parsers.platforms_media_share import (
    parse_buff,
    parse_doubao,
    parse_illu,
    parse_qsmusic,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_mihuashi import (
    parse_mihuashi as parse_mihuashi_v2,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_miyoushe import (
    parse_miyoushe as parse_miyoushe_deep,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_moegirl import parse_moegirl
from plugins.bot_unified_runtime.sources.parsers.platforms_music import (
    netease_song_detail_by_id,
    parse_apple_music,
    parse_kugou,
    parse_kugou_mixsong,
    parse_kuwo,
    parse_netease_music,
    parse_qqmusic,
    parse_spotify,
    search_apple_music,
    search_kugou,
    search_kugou_candidates,
    search_netease_music,
    search_netease_music_candidates,
    search_qqmusic,
    search_qqmusic_candidates,
    search_spotify,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_pixiv import parse_pixiv
from plugins.bot_unified_runtime.sources.parsers.platforms_skland import (
    parse_skland as parse_skland_deep,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_steam import parse_steam
from plugins.bot_unified_runtime.sources.parsers.platforms_taptap import parse_taptap
from plugins.bot_unified_runtime.sources.parsers.platforms_telegram import (
    parse_telegram,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_weibo import parse_weibo
from plugins.bot_unified_runtime.sources.parsers.platforms_xiaoheihe import (
    parse_xiaoheihe as parse_xiaoheihe_v2,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_zhihu import parse_zhihu
from plugins.bot_unified_runtime.sources.registry import ParserRegistry

_HTTP_URL_RE = re.compile(r"https?://[^\s<>\"'（）()【】\[\]{}]+")

ParseFn = Callable[[str], ParsedContent]

# parser_id → (平台显示名, 链接正则, 解析函数, 优先级)
_PLATFORM_RULES: list[tuple[str, str, list[str], ParseFn, int]] = [
    (
        "bilibili",
        "B站",
        [
            r"bilibili\.com/video/(BV[0-9A-Za-z]{10}|av\d+)",
            r"bilibili\.com/list/watchlater/\?[^\s]*bvid=BV[0-9A-Za-z]{10}",
            r"b23\.tv/[0-9A-Za-z]+",
            r"bili2233\.cn/[0-9A-Za-z]+",
            r"live\.bilibili\.com/\d+",
            r"space\.bilibili\.com/\d+",
            r"bilibili\.com/opus/\d+",
            r"bilibili\.com/bangumi/play/(ss|ep)\d+",
            r"space\.bilibili\.com/\d+/channel/seriesdetail",
            r"space\.bilibili\.com/\d+/lists",
            r"bilibili\.com/list/ml\d+",
        r"t\.bilibili\.com/\d+",
        r"bilibili\.com/dynamic/\d+",
        r"b23\.tv/[\w-]+",
        r"bili2233\.cn/[\w-]+",
        r"bilibili\.com/[^\s]+",
        ],
        parse_bilibili,
        10,
    ),
    (
        "bilibili_goods",
        "B站商品",
        [
            r"mall\.bilibili\.com/[^\s]+",
            r"show\.bilibili\.com/platform/detail\.html\?[^\s]*id=\d+",
            r"bilibili\.com/h5/mall[^\s]*",
        ],
        parse_bilibili_goods,
        11,
    ),
    (
        "steam",
        "Steam",
        [
            r"store\.steampowered\.com/app/\d+[^\s]*",
            r"steamcommunity\.com/app/\d+[^\s]*",
            r"steamcommunity\.com/(profiles|id)/[^/\s]+[^\s]*",
            r"steamcommunity\.com/market/listings/[^\s]+",
        ],
        parse_steam,
        12,
    ),
    (
        "epic",
        "Epic",
        [r"store\.epicgames\.com/(p|bundles)/[^\s]+"],
        parse_epic,
        12,
    ),
    (
        "facebook",
        "Facebook",
        [
            r"facebook\.com/share/(p|r|v)/[0-9A-Za-z]+",
            r"facebook\.com/(reel|watch)/[^\s]+",
            r"facebook\.com/[^\s]+",
        ],
        parse_facebook,
        12,
    ),
    (
        "github",
        "GitHub",
        [
            r"github\.com/[0-9A-Za-z][0-9A-Za-z-]{0,38}/[0-9A-Za-z_.-]+(?:/[^\s]*)?",
        ],
        parse_github,
        12,
    ),
    (
        "moegirl",
        "萌娘百科",
        [r"mzh\.moegirl\.org\.cn/[^\s]+", r"zh\.moegirl\.org\.cn/[^\s]+"],
        parse_moegirl,
        12,
    ),
    (
        "weibo",
        "微博",
        [
            r"weibo\.com/\d+/[0-9A-Za-z]+",
            r"weibo\.com/u/\d+",
            r"weibo\.cn/[^\s]+",
        ],
        parse_weibo,
        12,
    ),
    (
        "zhihu",
        "知乎",
        [
            r"zhihu\.com/question/\d+/answer/\d+",
            r"zhuanlan\.zhihu\.com/p/\d+",
        ],
        parse_zhihu,
        12,
    ),
    (
        "douban",
        "豆瓣",
        [r"douban\.com/group/topic/\d+"],
        parse_douban,
        12,
    ),
    (
        "taptap",
        "TapTap",
        [
            r"taptap\.(?:cn|io)/moment/\d+",
            r"taptap\.(?:cn|io)/video/\d+",
        ],
        parse_taptap,
        12,
    ),
    (
        "linuxdo",
        "linux.do",
        [r"linux\.do/t/(?:topic/)?\d+"],
        parse_linuxdo,
        12,
    ),
    (
        "zlb",
        "ZLB",
        [r"zlb\.ink/t/(?:topic/)?\d+"],
        parse_zlb,
        12,
    ),
    (
        "coolapk",
        "酷安",
        [r"coolapk(?:1s)?\.com/feed/\d+"],
        parse_coolapk,
        12,
    ),
    (
        "hupu",
        "虎扑",
        [
            r"bbs\.hupu\.com/\d+\.html",
            r"m\.hupu\.com/bbs(?:-share)?/\d+",
            r"hupu\.com/\d+\.html",
        ],
        parse_hupu,
        12,
    ),
    (
        "wmpvp",
        "完美对战",
        [r"wmpvp\.com/community-(?:pc)?[Dd]etail\.html\?[^\s]*id=\d+"],
        parse_wmpvp,
        12,
    ),
    (
        "5eplay",
        "5E对战",
        [r"5eplay\.com/forum/(?:share/)?\d+"],
        parse_5eplay,
        12,
    ),
    (
        "ds163",
        "网易大道",
        [r"ds\.163\.com/(?:article|feed)/[A-Za-z0-9]+"],
        parse_ds163,
        12,
    ),
    (
        "qsmusic",
        "汽水音乐",
        [r"qishui\.douyin\.com/s/[A-Za-z0-9]+"],
        parse_qsmusic,
        12,
    ),
    (
        "doubao",
        "豆包",
        [r"doubao\.com/video-sharing\?[^\s]*share_id=\d+"],
        parse_doubao,
        12,
    ),
    (
        "illu",
        "米画师",
        [r"illund\.com/share\.html[^\s]*"],
        parse_illu,
        12,
    ),
    (
        "buff",
        "BUFF饰品",
        [r"buff\.163\.com/[^\s]+"],
        parse_buff,
        12,
    ),
    (
        "kuaishou",
        "快手",
        [
            r"kuaishou\.com/short-video/[^\s]+",
            r"live\.kuaishou\.com/u/[^\s]+",
            r"v\.kuaishou\.com/[0-9A-Za-z]+",
        ],
        parse_kuaishou,
        12,
    ),
    (
        "acfun",
        "AcFun",
        [
            r"acfun\.cn/v/ac\d+",
            r"acfun\.cn/bangumi/aa\d+",
            r"live\.acfun\.cn/live/\d+",
            r"acfun\.cn/a/ac\d+",
        ],
        parse_acfun,
        12,
    ),
    (
        "bilibili_show",
        "B站会员购",
        [r"show\.bilibili\.com/platform/detail\.html\?[^\s]*id=\d+"],
        parse_bilibili_show,
        10,
    ),
    (
        "biligame",
        "B站游戏中心",
        [r"biligame\.com/detail/\?[^\s]*id=\d+"],
        parse_bilibili,
        10,
    ),
    (
        "douyin",
        "抖音",
        [
            r"v\.douyin\.com/[0-9A-Za-z]+/",
            r"douyin\.com/video/\d+",
            r"douyin\.com/jingxuan\?[^\s]*modal_id=\d+",
        ],
        parse_douyin,
        20,
    ),
    (
        "xiaohongshu",
        "小红书",
        [r"xhslink\.com/[0-9A-Za-z]+", r"xiaohongshu\.com/(?:explore|discovery/item)/[0-9a-fA-F]+", r"xiaohongshu\.com/search_result/[0-9a-f]+", r"xiaohongshu\.com/user/profile/[0-9a-zA-Z]+"],
        parse_xiaohongshu,
        21,
    ),
    (
        "youtube",
        "油管/油管音乐",
        [
            r"youtube\.com/watch\?v=[\w-]+",
            r"youtu\.be/[\w-]+",
            r"youtube\.com/shorts/[\w-]+",
            r"youtube\.com/playlist\?list=[\w-]+",
            r"youtube\.com/post/[\w-]+",
            r"music\.youtube\.com/watch\?v=[\w-]+",
            r"music\.youtube\.com/playlist\?list=[\w-]+",
        ],
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
        [
            r"xiaoheihe\.cn/app/(?:topic/link|bbs/link|topic/game)/[^\s]+",
            r"xiaoheihe\.cn/v3/bbs/app/[^\s]+",
            r"api\.xiaoheihe\.cn/v3/bbs/app/api/web_view\?[^\s]*link_id=\d+",
        ],
        parse_xiaoheihe_v2,
        24,
    ),
    (
        "miyoushe",
        "米游社",
        [
            r"miyoushe\.com/[^\s]*article/\d+",
            r"miyoushe\.com/[^\s]+/home/\d+",
            r"m\.bbs\.miyoushe\.com/[^\s]+",
        ],
        parse_miyoushe_deep,
        24,
    ),
    (
        "skland",
        "森空岛",
        [
            r"skland\.com/article\?[^\s]*id=\d+",
            r"skland\.com/game/[^\s]+",
            r"skland\.com/article/[^\s]+",
        ],
        parse_skland_deep,
        25,
    ),
    (
        "kurobbs",
        "库街区",
        [r"kurobbs\.com/[^\s]+"],
        parse_kurobbs_v2,
        27,
    ),
    (
        "pixiv",
        "Pixiv",
        [r"pixiv\.net/artworks/\d+"],
        parse_pixiv,
        28,
    ),
    (
        "pixiv_novel",
        "Pixiv小说",
        [r"pixiv\.net/novel/show\.php\?[^\s]*id=\d+"],
        parse_pixiv_novel,
        28,
    ),
    (
        "pixiv_series",
        "Pixiv小说系列",
        [r"pixiv\.net/novel/series/\d+"],
        parse_pixiv_novel_series,
        28,
    ),
    (
        "pixiv_user",
        "Pixiv用户",
        [r"pixiv\.net/users/\d+"],
        parse_pixiv_user,
        28,
    ),
    (
        "pixiv_contest",
        "Pixiv大赛",
        [r"pixiv\.net/contest/[^\s]+"],
        parse_pixiv_contest,
        28,
    ),
    (
        "pixiv_ranking",
        "Pixiv排行榜",
        [r"pixiv\.net/ranking\.php[^\s]*"],
        parse_pixiv_ranking,
        28,
    ),
    (
        "lofter",
        "LOFTER",
        [r"lofter\.com/(post/[^\s]+|lpost/[^\s]+|tag/[^\s]+|trend[^\s]*|selection[^\s]*|theme/[^\s]+)"],
        parse_lofter,
        28,
    ),
    (
        "allcpp",
        "无差别同人站",
        [r"allcpp\.cn/allcpp/event/[^\s]+"],
        parse_allcpp,
        29,
    ),
    (
        "mihuashi",
        "米画师",
        [r"mihuashi\.com/(profiles|projects|stalls|artworks)/[^\s]+"],
        parse_mihuashi_v2,
        29,
    ),
    (
        "huajia",
        "网易画加",
        [r"huajia\.163\.com/main/[^\s]+"],
        parse_huajia,
        29,
    ),
    (
        "telegram",
        "Telegram",
        [r"t\.me/(?:s/)?[A-Za-z0-9_]{4,}/\d+", r"telegram\.me/[A-Za-z0-9_]{4,}/\d+"],
        parse_telegram,
        30,
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
        [r"y\.qq\.com/n/ryqq(_v2)?/(songDetail|song)/[0-9A-Za-z]+", r"i\.y\.qq\.com/v8/playsong\.html\?[^\s]*songmid=[0-9A-Za-z]+"],
        parse_qqmusic,
        31,
    ),
    (
        "kuwo",
        "酷我音乐",
        [r"kuwo\.cn/play_?[Dd]etail/\d+"],
        parse_kuwo,
        32,
    ),
    (
        "kugou",
        "酷狗音乐",
        [r"kugou\.com/song/#hash=[0-9A-Fa-f]{16,}", r"t3\.kugou\.com/song\.html\?id=\d+"],
        parse_kugou,
        32,
    ),
    (
        "kugou_mixsong",
        "酷狗音乐",
        [r"kugou\.com/mixsong/[0-9A-Za-z]+"],
        parse_kugou_mixsong,
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
_MUSIC_SEARCH_PROVIDERS: list[tuple[str, str, Callable[[str], ParsedContent | None]]] = [
    ("netease_music", "网易云", search_netease_music),
    ("apple_music", "Apple Music", search_apple_music),
    ("kugou", "酷狗", search_kugou),
    ("qqmusic", "QQ音乐", search_qqmusic),
    # 酷我/Spotify 搜索退役（09-10 决断）：酷我 r.s 官方接口服务端劣化返回非 JSON、
    # suyanw 聚合改为 GBK 文本编号列表（无 rid/直链，无法构建可播放结果，实测两者
    # 均恒 None=静默死代码）；Spotify 搜索本就是恒 None 占位。链接解析 parse_kuwo
    # 保留（wapi musicInfo 匿名可用）。
    ("spotify", "Spotify", search_spotify),
]

# parser_id → Cookie 提供方的平台键（无 cookie 需求的平台不在此列）。
_PARSER_COOKIE_PLATFORM: dict[str, str] = {
    "bilibili": "bilibili",
    "bilibili_goods": "bilibili",
    "douyin": "douyin",
    "xiaohongshu": "xiaohongshu",
    "youtube": "youtube",
    "twitter": "twitter",
    "miyoushe": "miyoushe",
    "skland": "skland",
    "kurobbs": "kurobbs",
    "weibo": "weibo",
    "kuaishou": "kuaishou",
    "acfun": "acfun",
    "moegirl": "moegirl",
    "xiaoheihe": "xiaoheihe",
    "netease_music": "netease",
    "qqmusic": "qqmusic",
    "kuwo": "kuwo",
    "kugou": "kugou",
}


def _bind_cookie(fn: Any, cookie_header: str) -> Any:
    if not cookie_header:
        return fn
    return functools.partial(fn, cookie_header=cookie_header)


def _bind_proxy(fn: Any, proxy: str) -> Any:
    if not proxy:
        return fn
    return functools.partial(fn, proxy=proxy)


# 需要走代理的海外平台（大陆直连被墙）。
_PARSER_PROXY_PLATFORM = frozenset(
    {
        "youtube",
        "twitter",
        "spotify",
        "pixiv",
        "pixiv_novel",
        "pixiv_series",
        "pixiv_user",
        "pixiv_contest",
        "pixiv_ranking",
        "facebook",
    }
)


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


# 群门禁的 URL 支持判定（policy._has_supported_url）每条群消息都会以全默认
# 参数调一次本函数：几十个 ParserRule 对象 + 正则重编译，纯浪费。全默认参数
# 的返回值只用于 URL 模式匹配（不消费绑了 Cookie 的解析函数），缓存为进程级
# 单例零行为差异；带参调用（真实解析路径，注入 Cookie/代理/Playwright）不受影响。
_DEFAULT_REGISTRY_BUNDLE: dict[str, Any] | None = None


def build_content_parser_registry(
    enabled_platforms: list[str] | None = None,
    cookie_provider: PlatformCookieProvider | None = None,
    proxy: str = "",
    playwright_backend: Any | None = None,
) -> dict[str, Any]:
    """构建链接解析注册表。

    ``enabled_platforms`` 为空 = 全部启用；否则只启用名单内平台。
    ``cookie_provider`` 提供平台 Cookie 头（无则匿名解析）。
    ``proxy`` 给油管/推特/Spotify 等海外平台绑定 HTTP 代理。
    """
    global _DEFAULT_REGISTRY_BUNDLE
    if (
        enabled_platforms is None
        and cookie_provider is None
        and not proxy
        and playwright_backend is None
    ):
        cached = _DEFAULT_REGISTRY_BUNDLE
        if cached is not None:
            return cached
    allowed = {str(name).strip().lower() for name in (enabled_platforms or [])}
    cookies = cookie_provider or PlatformCookieProvider()
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
        bound = parse_fn
        cookie_platform = _PARSER_COOKIE_PLATFORM.get(parser_id, "")
        if cookie_platform:
            bound = _bind_cookie(
                bound, cookies.cookie_header(cookie_platform)
            )
        if parser_id in _PARSER_PROXY_PLATFORM and proxy:
            bound = _bind_proxy(bound, proxy)
        if parser_id in {"xiaohongshu", "kurobbs"} and playwright_backend is not None:
            bound = functools.partial(bound, playwright_backend=playwright_backend)  # type: ignore[call-arg]
        parsers[parser_id] = bound
    bundle = {"registry": registry, "parsers": parsers}
    if (
        enabled_platforms is None
        and cookie_provider is None
        and not proxy
        and playwright_backend is None
    ):
        _DEFAULT_REGISTRY_BUNDLE = bundle
    return bundle


def music_candidate_providers(
    cookie_provider: PlatformCookieProvider | None = None,
) -> dict[
    str,
    tuple[
        Callable[[str], list[dict[str, str]]],
        Callable[..., ParsedContent | None],
    ],
]:
    """多候选点歌提供方：平台 id -> (候选列表函数, 候选详情函数)。

    详情函数签名：detail_fn(candidate: dict, *, query: str) -> ParsedContent | None。
    网易云按 song_id 取详情；QQ/酷狗/酷我直接从候选 dict 构建（列表阶段已带
    hash/mid 等关键 ID）。
    """
    cookies = cookie_provider or PlatformCookieProvider()

    def _netease_detail(candidate: dict, *, query: str = "") -> ParsedContent | None:
        return _bind_cookie(netease_song_detail_by_id, cookies.cookie_header(_PARSER_COOKIE_PLATFORM.get("netease_music", "")))(
            str(candidate.get("provider_track_id") or "")
        )

    def _qq_detail(candidate: dict, *, query: str = "") -> ParsedContent | None:
        # QQ 音频直链依赖登录 vkey，此处按候选信息构建卡片与链接；
        # 音频/语音模式在 QQ 平台本来就受登录门槛约束。
        from plugins.bot_unified_runtime.sources.parsers.platforms_music import (
            _qqmusic_cover,
        )

        return build_parsed_content(
            platform="qqmusic",
            item_id=str(candidate.get("provider_track_id") or ""),
            item_kind="music",
            title=str(candidate.get("name") or ""),
            author_name=str(candidate.get("artist") or ""),
            cover_url=_qqmusic_cover(candidate.get("album_mid")),
        )

    def _kugou_detail(candidate: dict, *, query: str = "") -> ParsedContent | None:
        # 酷狗按 hash 复用 getSongInfo 现有链路：标题/封面/试听直链一次拿全，
        # 不再退回无图无声的候选构建（审计 P1#8）。
        from plugins.bot_unified_runtime.sources.parsers.platforms_music import (
            parse_kugou,
        )

        file_hash = str(candidate.get("provider_track_id") or "")
        if not file_hash:
            return None
        try:
            return parse_kugou(
                f"https://www.kugou.com/song/#hash={file_hash}",
                cookie_header=cookies.cookie_header(_PARSER_COOKIE_PLATFORM.get("kugou", "")),
            )
        except Exception:  # noqa: BLE001 - 详情失败回退候选构建。
            return build_parsed_content(
                platform="kugou",
                item_id=file_hash,
                item_kind="music",
                title=str(candidate.get("name") or ""),
                author_name=str(candidate.get("artist") or ""),
            )

    def _bound(platform: str, fn: Callable) -> Callable:
        return _bind_cookie(fn, cookies.cookie_header(_PARSER_COOKIE_PLATFORM.get(platform, "")))

    return {
        "netease_music": (
            _bound("netease_music", search_netease_music_candidates),
            _netease_detail,
        ),
        "qqmusic": (
            _bound("qqmusic", search_qqmusic_candidates),
            _qq_detail,
        ),
        "kugou": (_bound("kugou", search_kugou_candidates), _kugou_detail),
    }


def music_search_providers(
    enabled_platforms: list[str] | None = None,
    cookie_provider: PlatformCookieProvider | None = None,
) -> list[tuple[str, str, Callable[[str], ParsedContent | None]]]:
    """点歌搜索提供方（按配置过滤并保持顺序，按平台绑定 Cookie）。"""
    allowed = {str(name).strip().lower() for name in (enabled_platforms or [])}
    cookies = cookie_provider or PlatformCookieProvider()
    providers = _MUSIC_SEARCH_PROVIDERS
    if allowed:
        providers = [
            (parser_id, display_name, search_fn)
            for parser_id, display_name, search_fn in providers
            if parser_id in allowed
        ]
    return [
        (
            parser_id,
            display_name,
            _bind_cookie(
                search_fn,
                cookies.cookie_header(_PARSER_COOKIE_PLATFORM.get(parser_id, "")),
            ),
        )
        for parser_id, display_name, search_fn in providers
    ]


def build_cookie_provider(config: object | None) -> PlatformCookieProvider:
    """从配置构建 Cookie 提供方（BOT_COOKIES_FILE → Netscape cookies.txt）。"""
    if config is None:
        return PlatformCookieProvider()
    path = getattr(config, "bot_cookies_file", "") or ""
    return build_platform_cookie_provider(path or None)


def build_source_input(text: str, *, request_id: str = "parser") -> SourceInput:
    return SourceInput(
        request_id=request_id,
        session_id="",
        capability_id="bot.content",
        raw_text=text,
        urls=extract_http_urls(text),
    )
