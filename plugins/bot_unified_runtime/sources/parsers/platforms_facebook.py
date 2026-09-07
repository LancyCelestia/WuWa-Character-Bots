"""Facebook 公开页 og 兜底解析（主页 / 分享帖 / 分享视频 / Reel）。

大陆直连 facebook.com 不通（连接失败或 400）；即走代理。匿名（未登录）
请求默认被重定向到登录页，只有爬虫 UA 能拿到服务端渲染的 og meta ——
实测用 ``facebookexternalhit`` UA + 代理可以稳定拿到 og:title /
og:description / og:image / og:url（分享链接还会在 og:url 里给出规范
落地页，如 share/p → 实际帖子 URL）。

全部字段来自 og 兜底，属于浅解析；任何一步都拿不到时给「链接已保留」
的 blocked 降级卡，不伪造内容。无可用登录 cookie（导出里没有 facebook
组），不伪装成登录用户。
"""

from __future__ import annotations

import html
import re

from plugins.bot_unified_runtime.contracts.media import (
    ParsedContent,
    build_parsed_content,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import (
    ParseHttpError,
    http_get_text,
)

# 大陆直连失败后兜底代理（与 epic/steam 模块同一出口）。
_FALLBACK_PROXY = "http://127.0.0.1:7890"

# 匿名可拿 og 的唯一姿势：声明为 FB 自己的爬虫（页面本身是公开内容）。
_FB_CRAWLER_UA = "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)"

_OG_TITLE_RE = re.compile(
    r"<meta[^>]+property=[\"']og:title[\"'][^>]*content=[\"']([^\"']+)", re.IGNORECASE
)
_OG_DESC_RE = re.compile(
    r"<meta[^>]+property=[\"']og:description[\"'][^>]*content=[\"']([^\"']+)", re.IGNORECASE
)
_OG_IMAGE_RE = re.compile(
    r"<meta[^>]+property=[\"']og:image[\"'][^>]*content=[\"']([^\"']+)", re.IGNORECASE
)
_OG_URL_RE = re.compile(
    r"<meta[^>]+property=[\"']og:url[\"'][^>]*content=[\"']([^\"']+)", re.IGNORECASE
)
_TITLE_TAG_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

# 未登录可见的登录墙壳页 og 特征（真实内容页不会长这样）。
_LOGIN_TITLE_EXACT = {"facebook", "log into facebook", "log in or sign up"}
_LOGIN_DESC_HINTS = (
    "到 facebook 查看",
    "log in to facebook",
    "see posts, photos and more",
    "join facebook",
    "加入 facebook，",
)


def _is_login_wall(og_title: str, og_desc: str) -> bool:
    lowered_title = og_title.strip().lower()
    if lowered_title in _LOGIN_TITLE_EXACT or "登录或注册" in og_title:
        return True
    lowered_desc = og_desc.strip().lower()
    return any(hint in lowered_desc for hint in _LOGIN_DESC_HINTS)


def _kind_of(url: str) -> str:
    """按路径猜内容类型：share/r·reel·watch → 视频，share/p·posts → 帖子，其余主页。"""
    lowered = url.lower()
    if "/share/r/" in lowered or "/reel/" in lowered or "/watch" in lowered or "/share/v/" in lowered:
        return "video"
    if "/share/p/" in lowered or "/posts/" in lowered or "/share/f/" in lowered or "/permalink/" in lowered:
        return "post"
    return "page"


def _fetch_og_html(url: str, *, proxy: str, timeout: float = 15.0) -> tuple[str, str]:
    """直连 → 代理依次尝试，返回 (最终 URL, HTML)；都失败抛 ParseHttpError。"""
    attempts = [proxy] if proxy else ["", _FALLBACK_PROXY]
    last: Exception | None = None
    for attempt in attempts:
        try:
            final_url, text = http_get_text(
                url, timeout=timeout, user_agent=_FB_CRAWLER_UA, proxy=attempt
            )
            if "<title" not in text and "og:" not in text:
                raise ParseHttpError("facebook: response without meta")
            return final_url, text
        except ParseHttpError as exc:
            last = exc
    raise last or ParseHttpError(f"GET {url} failed")


def _clean(raw: str) -> str:
    """og meta 值：解码 HTML 实体（FB 输出全是 &#x...; 数字实体）并压平空白。"""
    return re.sub(r"\s+", " ", html.unescape(raw or "")).strip()


def _meta_value(text: str, regex: re.Pattern[str]) -> str:
    match = regex.search(text or "")
    return match.group(1) if match else ""


def _title_tag(text: str) -> str:
    match = _TITLE_TAG_RE.search(text or "")
    if not match:
        return ""
    return _clean(match.group(1))


def _parse_count(raw: str) -> str:
    """'146,645' / '1.8万' → 原样规整为可展示字符串；无数字返回空。"""
    match = re.search(r"[\d][\d,.]*\s*[万亿]?", raw)
    return match.group(0).strip() if match else ""


def _stats_from_page_desc(desc: str) -> dict:
    """主页 og:description 形如 '鸣潮. 146,645 次赞 · 54,825 人在谈论.' → 指标。"""
    stats: dict = {}
    like_match = re.search(r"([\d,.]+\s*万?)\s*次赞", desc)
    if like_match:
        stats["点赞"] = _parse_count(like_match.group(1))
    talk_match = re.search(r"([\d,.]+\s*万?)\s*人在谈论", desc)
    if talk_match:
        stats["讨论"] = _parse_count(talk_match.group(1))
    return stats


def _stats_from_video_title(title: str) -> dict:
    """Reel og:title 形如 '1.8万次播放 · 644 个心情 | …' → 指标。"""
    stats: dict = {}
    play_match = re.search(r"([\d,.]+\s*万?)\s*次播放", title)
    if play_match:
        stats["播放"] = _parse_count(play_match.group(1))
    like_match = re.search(r"([\d,.]+\s*万?)\s*个(?:心情|赞)", title)
    if like_match:
        stats["心情"] = _parse_count(like_match.group(1))
    return stats


def _strip_title_noise(title: str) -> str:
    """标题去尾部 '| Facebook'；Reel 标题去尾部 ' | 页面名'。"""
    cleaned = title.strip()
    cleaned = re.sub(r"\s*\|\s*Facebook\s*$", "", cleaned)
    return cleaned


def _author_from_title_suffix(title: str) -> str:
    """"正文… | 鸣潮" → "鸣潮"（Reel/帖子标题尾部挂页面名）。"""
    parts = title.rsplit(" | ", 1)
    if len(parts) == 2 and 1 <= len(parts[1].strip()) <= 60:
        return parts[1].strip()
    return ""


def _facebook_card(
    url: str,
    final_url: str,
    *,
    kind: str,
    og_title: str,
    og_desc: str,
    og_image: str,
    og_url: str,
    title_tag: str,
) -> ParsedContent:
    canonical = _clean(og_url) or final_url or url
    stats: dict = {}
    if kind == "page":
        page_name = _clean(og_title)
        stats.update(_stats_from_page_desc(og_desc))
        # 主页描述首段是重复页名，去掉。
        summary = og_desc
        if page_name and summary.startswith(page_name):
            summary = summary[len(page_name):].lstrip(". ").strip()
        return build_parsed_content(
            platform="facebook",
            item_id="",
            item_kind="page",
            title=page_name or "Facebook 主页",
            author_name=page_name,
            summary=summary,
            cover_url=_clean(og_image),
            canonical_url=canonical,
            stats=stats,
            parse_depth="shallow",
            page_type="public_page",
        )
    if kind == "video":
        stats.update(_stats_from_video_title(og_title))
        # 标题优先用 <title>（og:title 前半是播放/心情统计噪音）。
        content_title = _strip_title_noise(title_tag) if title_tag else ""
        if not content_title:
            content_title = og_title.rsplit(" | ", 1)[0].strip() or "Facebook 视频"
        author = _author_from_title_suffix(content_title)
        if author:
            # Reel 标题尾部挂着页面名（"… | 鸣潮"），已提取为作者，从标题去掉。
            content_title = content_title[: content_title.rfind(" | ")].strip()
        return build_parsed_content(
            platform="facebook",
            item_id="",
            item_kind="video",
            title=content_title or "Facebook 视频",
            author_name=author,
            summary=og_desc,
            cover_url=_clean(og_image),
            canonical_url=canonical,
            stats=stats,
            parse_depth="shallow",
            page_type="share_video",
        )
    # 帖子：og:title 是主页名，<title> 是 "主页名 - 正文…"。
    author = _clean(og_title)
    content_title = _strip_title_noise(title_tag) if title_tag else ""
    if content_title.startswith(author + " - "):
        content_title = content_title[len(author) + 3 :].strip()
    elif content_title.startswith(author):
        content_title = content_title[len(author):].lstrip(" -").strip()
    return build_parsed_content(
        platform="facebook",
        item_id="",
        item_kind="post",
        title=content_title or author or "Facebook 帖子",
        author_name=author,
        summary=og_desc,
        cover_url=_clean(og_image),
        canonical_url=canonical,
        stats=stats,
        parse_depth="shallow",
        page_type="share_post",
    )


def parse_facebook(url: str, *, cookie_header: str = "", proxy: str = "") -> ParsedContent:
    """Facebook 公开链接：爬虫 UA og 解析；完全失败给「链接已保留」降级卡。"""
    kind = _kind_of(url)
    try:
        final_url, text = _fetch_og_html(url, proxy=proxy)
    except ParseHttpError:
        return build_parsed_content(
            platform="facebook",
            item_id="",
            item_kind=kind,
            title="Facebook 链接",
            summary="（Facebook 页面被登录墙/网络拦截，当前拿不到标题与预览；"
            "已保留原链接，点开即可查看）",
            canonical_url=url,
            parse_depth="blocked",
        )
    og_title = _clean(_meta_value(text, _OG_TITLE_RE))
    if not og_title:
        og_title = _title_tag(text)
    og_desc = _clean(_meta_value(text, _OG_DESC_RE))
    if not og_title or _is_login_wall(og_title, og_desc):
        # 爬虫 UA 也没拿到 og（内容不公开/登录墙）：诚实降级。
        return build_parsed_content(
            platform="facebook",
            item_id="",
            item_kind=kind,
            title="Facebook 链接",
            summary="（该内容未公开或被登录墙拦截，拿不到标题与预览；"
            "已保留原链接，点开即可查看）",
            canonical_url=url,
            parse_depth="blocked",
        )
    return _facebook_card(
        url,
        final_url,
        kind=kind,
        og_title=og_title,
        og_desc=og_desc,
        og_image=_meta_value(text, _OG_IMAGE_RE),
        og_url=_meta_value(text, _OG_URL_RE),
        title_tag=_title_tag(text),
    )
