"""森空岛（www.skland.com）链接解析。

- 文章页（``/article?id={id}``）：纯前端 SPA，页面只有壳（37KB，无 og meta，
  title 固定为站名）；公开 API 探查不可得（web-api.skland.com 存活但端点
  未公开、懒加载 bundle 里无静态可提取的文章详情路径），诚实降级为入口卡，
  不伪造内容。
- 板块页（``/game/{gameCode}``）：同样为动态渲染，按游戏代码给命名入口卡。
"""

from __future__ import annotations

import re

from plugins.bot_unified_runtime.contracts.media import (
    ParsedContent,
    build_parsed_content,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_generic import (
    _og_scrape,
)

_ARTICLE_ID_RE = re.compile(r"skland\.com/article\?[^\s]*?\bid=(\d+)")
_GAME_CODE_RE = re.compile(r"skland\.com/game/([a-zA-Z0-9_-]+)")

# 游戏代码 → 显示名（未知代码原样展示）。
_SKLAND_GAME_NAMES = {
    "arknights": "明日方舟",
    "endfield": "明日方舟：终末地",
    "popucom": "PopuCom",
    "arknights1516": "明日方舟（国际服）",
}


def _skland_game_display(game_code: str) -> str:
    return _SKLAND_GAME_NAMES.get(game_code.lower(), game_code)


def _skland_article_card(url: str, article_id: str) -> ParsedContent:
    """文章入口卡：SPA + 无公开接口，诚实降级（浅层）。"""
    return build_parsed_content(
        platform="skland",
        item_id=article_id,
        item_kind="article",
        title=f"森空岛文章 #{article_id}",
        summary="（森空岛文章页为前端渲染，且详情接口未公开，机器人拿不到"
        "标题/正文与互动数据；点开链接即可查看原帖）",
        canonical_url=url,
        parse_depth="shallow",
        page_type="article",
        badge="森空岛",
    )


def _skland_channel_card(url: str, game_code: str) -> ParsedContent:
    """板块页入口卡。"""
    display = _skland_game_display(game_code)
    return build_parsed_content(
        platform="skland",
        item_id=game_code,
        item_kind="forum",
        title=f"森空岛·{display}板块",
        summary="（板块页为前端渲染列表，机器人拿不到帖子列表；"
        "想看哪篇帖子，请把帖子链接发我）",
        canonical_url=url,
        parse_depth="shallow",
        page_type="forum",
        badge="板块",
    )


def parse_skland(url: str, *, cookie_header: str = "", proxy: str = "") -> ParsedContent:
    """森空岛入口：文章 / 板块页分流；无公开数据时诚实浅卡。

    备注：公开 API 探查结论（2026-08 实测）——页面为纯 SPA 壳且无 og meta；
    ``web-api.skland.com`` 存活但文章端点未公开（/web/v1/article/detail 等
    均为 404），懒加载 bundle 中无法静态提取详情路径。官方公开端点后，
    在 ``_ARTICLE_ID_RE`` 分支补全深解析即可。
    """
    article_match = _ARTICLE_ID_RE.search(url)
    if article_match:
        return _skland_article_card(url, article_match.group(1))
    game_match = _GAME_CODE_RE.search(url)
    if game_match:
        return _skland_channel_card(url, game_match.group(1))
    # 其余路径（用户主页等）：og 尽力而为，失败给静态卡。
    try:
        return _og_scrape(
            url,
            platform="skland",
            item_kind="page",
            cookie_header=cookie_header,
            proxy=proxy,
        )
    except Exception:  # noqa: BLE001
        return build_parsed_content(
            platform="skland",
            item_id="",
            item_kind="page",
            title="森空岛页面",
            summary="（该页面无法直接提取内容，点开链接查看）",
            canonical_url=url,
            parse_depth="shallow",
        )
