"""库街区（www.kurobbs.com）链接解析。

- 帖子（``/mc/post/{postId}``）：``POST https://api.kurobbs.com/forum/core/detail``
  （表单 ``postId=``，需登录态 ``token`` 请求头）。token 过期/缺失时诚实降级浅卡。
- WIKI（``wiki.kurobbs.com``）：页面带通用 og/description，走 og 浅解析。
- 社区页面是纯 SPA 空壳（无 SSR、无 per-item og），深解析失败时保留入口浅卡。

实测（2026-08）：匿名请求返回 ``code 220 访问令牌不能为空``；携带文件中的
``user_token`` 返回 ``code 220 登录已过期，请重新登录`` —— 即当前 Cookie
不足，需要重新导出新鲜的 ``user_token`` 才能拿到帖子正文。
"""

from __future__ import annotations

import gzip
import json
import re
import ssl
from typing import Any
from urllib import parse as urlparse
from urllib import request as urlrequest

from plugins.bot_unified_runtime.contracts.media import (
    ParsedContent,
    build_parsed_content,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import (
    DEFAULT_USER_AGENT,
    ParseHttpError,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_generic import (
    _format_epoch,
    _og_scrape,
    _spa_link_card,
)

_KURO_DETAIL_API = "https://api.kurobbs.com/forum/core/detail"
_KURO_POST_RE = re.compile(r"kurobbs\.com/mc/post/(\d+)")
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _kuro_token(cookie_header: str) -> str:
    for chunk in (cookie_header or "").split(";"):
        pair = chunk.strip()
        if pair.startswith("user_token="):
            return pair.split("=", 1)[1].strip()
    return ""


def _kuro_post_detail(post_id: str, *, cookie_header: str) -> dict:
    """POST forum/core/detail（token 请求头），返回 data；失败抛 ParseHttpError。

    接口要求登录态 ``token`` 请求头（匿名返回 220「访问令牌不能为空」）；
    token 过期时返回 220「登录已过期」，由上层降级浅卡。
    """
    token = _kuro_token(cookie_header)
    if not token:
        raise ParseHttpError("kurobbs: no user_token cookie")
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept-Encoding": "gzip",
        "Referer": "https://www.kurobbs.com/",
        "token": token,
    }
    request = urlrequest.Request(
        _KURO_DETAIL_API,
        data=urlparse.urlencode({"postId": post_id}).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlrequest.build_opener(
            urlrequest.HTTPSHandler(context=ssl._create_unverified_context())
        ).open(request, timeout=12) as response:
            payload = response.read()
            if response.headers.get("Content-Encoding", "").lower() == "gzip":
                payload = gzip.decompress(payload)
        body = json.loads(payload.decode("utf-8", errors="replace"))
    except Exception as exc:
        raise ParseHttpError(f"kurobbs detail failed: {type(exc).__name__}") from exc
    if not isinstance(body, dict) or body.get("code") != 200:
        raise ParseHttpError(f"kurobbs detail api code={body.get('code') if isinstance(body, dict) else '?'}")
    data = body.get("data")
    if not isinstance(data, dict) or not data:
        raise ParseHttpError("kurobbs detail empty data")
    return data


def _kuro_cookie_pairs(cookie_header: str) -> list[dict]:
    """Cookie 头 → Playwright add_cookies 需要的 name/value/domain 列表。"""
    pairs: list[dict] = []
    for chunk in (cookie_header or "").split(";"):
        pair = chunk.strip()
        if "=" not in pair:
            continue
        name, value = pair.split("=", 1)
        if name.strip():
            pairs.append(
                {"name": name.strip(), "value": value.strip(), "domain": ".kurobbs.com", "path": "/"}
            )
    return pairs


def _kuro_post_detail_via_playwright(
    url: str,
    *,
    cookie_header: str,
    playwright_backend: Any,
) -> dict:
    """直连被网关签名风控时，用真实浏览器打开帖子页截获 core/detail 响应。"""
    payloads = playwright_backend.capture_json(
        url,
        cookies=_kuro_cookie_pairs(cookie_header),
        json_filter="core/detail",
        timeout_ms=30000,
    )
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        data = payload.get("data")
        if payload.get("code") == 200 and isinstance(data, dict) and data:
            return data
    raise ParseHttpError("kurobbs playwright capture: no detail payload")


def _strip_html(value: object, limit: int = 300) -> str:
    text = _HTML_TAG_RE.sub("", str(value or "").replace("<br/>", "\n").replace("<br>", "\n"))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[:limit] + "…"
    return text


def _kuro_post_card(
    url: str,
    post_id: str,
    *,
    cookie_header: str,
    playwright_backend: Any | None = None,
) -> ParsedContent:
    """帖子深解析：直连 API，被风控时回退 Playwright 真实浏览器截获。"""
    try:
        data = _kuro_post_detail(post_id, cookie_header=cookie_header)
    except ParseHttpError:
        if playwright_backend is None:
            raise
        data = _kuro_post_detail_via_playwright(
            url, cookie_header=cookie_header, playwright_backend=playwright_backend
        )
    post = data.get("post") or data.get("detail") or data
    if not isinstance(post, dict):
        post = {}
    title = str(post.get("title") or post.get("postTitle") or "").strip()
    if not title:
        raise ParseHttpError("kurobbs post missing title")
    content = _strip_html(post.get("content") or post.get("postContent"))
    stats: dict = {}
    for key, label in (
        ("likeNum", "点赞"),
        ("replyNum", "回复"),
        ("viewNum", "浏览"),
        ("collectNum", "收藏"),
        ("shareNum", "分享"),
    ):
        value = post.get(key)
        if isinstance(value, (int, float)) and value > 0:
            stats[label] = int(value)
    publish_time = _format_epoch(post.get("createAt") or post.get("createTime"))
    if publish_time:
        stats["发布时间"] = publish_time
    user = post.get("user") or {}
    author_detail: dict = {}
    if isinstance(user, dict):
        if user.get("userId"):
            author_detail["uuid"] = str(user["userId"])
        if user.get("userAvatar"):
            author_detail["avatar"] = str(user["userAvatar"])
    return build_parsed_content(
        platform="kurobbs",
        item_id=post_id,
        item_kind="post",
        title=title,
        author_name=str(user.get("userName") or "") if isinstance(user, dict) else "",
        summary="\n".join(filter(None, [f"发布时间：{publish_time}" if publish_time else "", content])),
        canonical_url=url,
        stats=stats,
        parse_depth="deep",
        page_type="post",
        badge="库街区",
        detail={"author": author_detail} if author_detail else {},
    )


def _kuro_post_dom_card(url: str, post_id: str) -> ParsedContent:
    """Playwright 渲染帖子页后从 DOM 提取正文（detail API 有网关签名风控）。

    实测（2026-08）：帖子页对未登录浏览器也会 hydration 渲染全文，
    doc.title 为「帖子标题 - 库街区」，``[class*=content]`` 含互动数、
    标题、发布时间与正文全文。
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_context().new_page()
            page.goto(url, wait_until="networkidle", timeout=45000)
            page.wait_for_timeout(2000)
            title = page.title().split(" - 库街区")[0].strip() or f"库街区帖子 {post_id}"
            content_el = page.query_selector("[class*=content]")
            raw = (
                content_el.inner_text()
                if content_el is not None
                else page.inner_text("body")
            ).strip()
        finally:
            browser.close()
    lines = [line.strip() for line in raw.split("\n") if line.strip()]
    # 头部无标签互动数字序列（如「44 4195 215」）不进正文，避免误导。
    body_lines = [line for line in lines if not re.fullmatch(r"[\d\s]+", line)]
    body_text = "\n".join(body_lines)
    if len(body_text) > 400:
        body_text = body_text[:400] + "…"
    if not body_text:
        raise ParseHttpError("kurobbs dom: no rendered text")
    return build_parsed_content(
        platform="kurobbs",
        item_id=post_id,
        item_kind="post",
        title=title[:60],
        summary=body_text,
        canonical_url=url,
        parse_depth="deep",
        page_type="post",
        badge="库街区",
    )


def _kuro_shallow_card(url: str, post_id: str, *, note: str) -> ParsedContent:
    return build_parsed_content(
        platform="kurobbs",
        item_id=post_id,
        item_kind="post",
        title=f"库街区帖子 {post_id}" if post_id else "库街区帖子",
        summary=note,
        canonical_url=url,
        parse_depth="shallow",
        page_type="post",
        badge="库街区",
    )


def parse_kurobbs(
    url: str,
    *,
    cookie_header: str = "",
    proxy: str = "",
    playwright_backend: Any | None = None,
) -> ParsedContent:
    """库街区入口：帖子深解析（直连→Playwright 截获）→ og → 静态浅卡。"""
    post_match = _KURO_POST_RE.search(url)
    if post_match:
        post_id = post_match.group(1)
        item: ParsedContent | None
        try:
            item = _kuro_post_card(
                url,
                post_id,
                cookie_header=cookie_header,
                playwright_backend=playwright_backend,
            )
        except Exception:  # noqa: BLE001 - API 通道失败转 DOM 渲染提取。
            item = None
        if item is None:
            try:
                item = _kuro_post_dom_card(url, post_id)
            except Exception:  # noqa: BLE001 - 渲染提取也失败给静态浅卡。
                item = None
        if item is not None:
            return item
        return _kuro_shallow_card(
            url,
            post_id,
            note="（帖子页为动态渲染且当前 Cookie 的 user_token 已过期，"
            "机器人拿不到正文；已保留原链接，点开即可查看，"
            "或更新 platform_cookies.txt 中的 kurobbs user_token 后重试）",
        )
    if "wiki.kurobbs.com" in url:
        try:
            return _og_scrape(
                url,
                platform="kurobbs",
                item_kind="wiki",
                cookie_header=cookie_header,
                proxy=proxy,
            )
        except ParseHttpError:
            return _spa_link_card(url, platform="kurobbs", item_kind="wiki", label="库街区WIKI")
    return _spa_link_card(url, platform="kurobbs", item_kind="page", label="库街区")
