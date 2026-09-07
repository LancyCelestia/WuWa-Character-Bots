"""Steam 链接解析：商店页 / 社区游戏 hub / 个人资料 / 市场商品。

数据源（全部实测匿名可用，无需登录态）：

- 商店页：``store.steampowered.com/api/appdetails``（``cc=cn&l=schinese``
  拿简中 + CNY 定价）+ ``appreviews``（评测数/好评率）；
- 社区游戏 hub：页面 og meta（标题形如 ``Steam 社区 :: 游戏名``）；
- 个人资料：``/profiles/{id}/?xml=1`` 公开 XML（昵称/头像/在线状态），
  HTML og 兜底；``/profiles/{id}/home`` 匿名访问会被重定向到登录页，
  因此统一按个人资料卡处理；
- 市场商品：listing 页 og（物品名/物品图）+ ``priceoverview`` 接口
  （CNY 参考价 / 24h 成交量）。

Cookie：steam 组（steamcommunity.com / steampowered.com）带 steamLoginSecure。
注册层若未提供 ``cookie_header``，则自行从 Netscape cookie 文件加载
（cookies.py 白名单未覆盖 steam，这里做兜底；值只进请求头，绝不外泄）。
商店定价接口刻意匿名请求：带登录态会按账号区服返回外币价格。
"""

from __future__ import annotations

import functools
import html
import os
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.contracts.media import (
    ParsedContent,
    build_parsed_content,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import (
    ParseHttpError,
    http_get_json,
    http_get_text,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_generic import _og_scrape

# 大陆直连 Steam 通常可达；直连失败再走默认代理兜底。
_FALLBACK_PROXY = "http://127.0.0.1:7890"

_STEAM_COOKIE_DOMAINS = ("steamcommunity.com", "steampowered.com")
_COOKIES_ENV = "BOT_COOKIES_FILE"
_RUNTIME_DATA_ENV = "BOT_RUNTIME_DATA_DIR"

_MARKET_TITLE_SUFFIXES = (" - Steam 社区市场", " - Steam Community Market")

_APPDETAILS_URL = "https://store.steampowered.com/api/appdetails?appids={appid}&l=schinese&cc=cn"
_APPREVIEWS_URL = (
    "https://store.steampowered.com/appreviews/{appid}"
    "?json=1&language=all&purchase_type=all&num_per_page=0"
)
_PRICE_OVERVIEW_URL = (
    "https://steamcommunity.com/market/priceoverview/"
    "?appid={appid}&currency=23&market_hash_name={name}"
)

# 识别不了的 appdetails type 统一按游戏展示。
_KNOWN_APP_TYPES = {"game", "dlc", "demo", "music", "video", "hardware", "bundle", "application"}


# ---------------------------------------------------------------------------
# Cookie 兜底加载（cookies.py 白名单没有 steam，这里自读 Netscape 文件）。
# 安全规则：值只用于请求头；任何日志/异常/返回都不包含 cookie 值。
# ---------------------------------------------------------------------------


def _cookie_file_candidates() -> list[Path]:
    raw = os.getenv(_COOKIES_ENV, "").strip() or "data/platform_cookies.txt"
    raw = raw.replace("\\", "/")
    path = Path(raw).expanduser()
    candidates: list[Path] = []
    if path.is_absolute():
        candidates.append(path)
        return candidates
    runtime = os.getenv(_RUNTIME_DATA_ENV, "").strip()
    if runtime:
        runtime_root = Path(runtime).expanduser()
        normalized = raw
        if normalized == "data":
            candidates.append(runtime_root)
        elif normalized.startswith("data/"):
            candidates.append(runtime_root / normalized[5:])
        else:
            candidates.append(runtime_root / path)
    project_root = Path(__file__).resolve().parents[4]
    candidates.append(project_root / path)
    # .env 未注入环境变量时（独立脚本场景），再试兄弟 Runtime 目录。
    candidates.append(project_root.parent / "ChatBot_Runtime" / "data" / "platform_cookies.txt")
    return candidates


@functools.lru_cache(maxsize=1)
def _load_steam_cookie_entries() -> tuple[tuple[str, str, str, str, int], ...]:
    """返回 (domain, name, value, path, expires) 五元组；失败返回空（匿名降级）。"""
    for candidate in _cookie_file_candidates():
        try:
            if not candidate.is_file():
                continue
            entries: list[tuple[str, str, str, str, int]] = []
            now = int(time.time())
            with open(candidate, "r", encoding="utf-8", errors="replace") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t")
                    if len(parts) < 7:
                        continue
                    domain, _, cookie_path, _, expires_raw, name, value = parts[:7]
                    if not name.strip() or not value:
                        continue
                    try:
                        expires = int(expires_raw)
                    except ValueError:
                        expires = 0
                    if expires and expires <= now:
                        continue
                    entries.append((domain, name, value, cookie_path or "/", expires))
            if entries:
                return tuple(entries)
        except OSError:
            continue
    return ()


def steam_cookie_header(host: str = "steamcommunity.com") -> str:
    """按主机匹配 steam 组 cookie 头；注册层已给 cookie_header 时不会走到这里。

    同名 cookie 取更具体路径/更新的值（与 cookies.py 的取舍一致）。
    """
    matched: dict[str, tuple[str, int, str]] = {}
    order: list[str] = []
    for domain, name, value, path, expires in _load_steam_cookie_entries():
        if not (host == domain or host.endswith(f".{domain}")):
            continue
        existing = matched.get(name)
        if existing is None:
            order.append(name)
            matched[name] = (path, expires, value)
        elif (len(path), expires) >= (len(existing[0]), existing[1]):
            matched[name] = (path, expires, value)
    return "; ".join(f"{name}={matched[name][2]}" for name in order)


# ---------------------------------------------------------------------------
# 请求封装：直连失败自动换代理重试。
# ---------------------------------------------------------------------------


def _proxy_attempts(proxy: str) -> list[str]:
    if proxy:
        return [proxy]
    return ["", _FALLBACK_PROXY]


def _get_text_dual(
    url: str,
    *,
    proxy: str = "",
    cookie: str = "",
    referer: str = "",
    timeout: float = 12.0,
) -> tuple[str, str]:
    last: Exception | None = None
    for attempt in _proxy_attempts(proxy):
        try:
            return http_get_text(
                url, timeout=timeout, referer=referer, cookie=cookie, proxy=attempt
            )
        except ParseHttpError as exc:
            last = exc
    raise last or ParseHttpError(f"GET {url} failed")


def _get_json_dual(url: str, *, proxy: str = "", timeout: float = 12.0) -> Any:
    last: Exception | None = None
    for attempt in _proxy_attempts(proxy):
        try:
            return http_get_json(url, timeout=timeout, proxy=attempt)
        except ParseHttpError as exc:
            last = exc
    raise last or ParseHttpError(f"GET {url} failed")


def _unescape(value: str) -> str:
    return html.unescape(value or "").strip()


def _clean_title(raw: str) -> str:
    """og/title 通用清洗：解码 HTML 实体并去首尾空白。"""
    return _unescape(raw)


def _split_steam_title(raw: str) -> str:
    """'Steam 社区 :: XXX' / 'Steam Community :: XXX' → 'XXX'。"""
    text = _clean_title(raw)
    for prefix in ("Steam 社区 :: ", "Steam Community :: "):
        if text.startswith(prefix):
            return text[len(prefix):].strip()
    return text


def _market_item_name(raw_title: str) -> str:
    """'梦魇武器箱 - Steam 社区市场' → '梦魇武器箱'。"""
    text = _clean_title(raw_title)
    for suffix in _MARKET_TITLE_SUFFIXES:
        if text.endswith(suffix):
            return text[: -len(suffix)].strip()
    return text


# ---------------------------------------------------------------------------
# 商店页
# ---------------------------------------------------------------------------


def _fmt_cent(value: object, currency: str) -> str:
    """appdetails 的 initial/final 是分；没有 formatted 兜底时拼一个。"""
    try:
        cents = int(str(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""
    major = cents / 100
    symbol = {"CNY": "¥ ", "USD": "US$ ", "EUR": "€ "}.get(currency, f"{currency} ")
    return f"{symbol}{major:,.2f}"


def _steam_store_card(
    appid: str,
    data: dict,
    url: str,
    *,
    proxy: str = "",
) -> ParsedContent:
    """appdetails data → 深度商店卡；评测接口失败只丢增强行。"""
    stats: dict = {}
    detail: dict = {}
    summary = str(data.get("short_description") or "").strip()

    price = data.get("price_overview")
    if isinstance(price, dict):
        currency = str(price.get("currency") or "CNY")
        original = str(price.get("initial_formatted") or "").strip() or _fmt_cent(
            price.get("initial"), currency
        )
        final = str(price.get("final_formatted") or "").strip() or _fmt_cent(
            price.get("final"), currency
        )
        discount = price.get("discount_percent")
        if isinstance(discount, (int, float)) and discount:
            if original:
                stats["原价"] = original
            stats["折扣价"] = final
            stats["折扣"] = f"-{int(discount)}%"
        else:
            stats["价格"] = final
    elif data.get("is_free"):
        stats["价格"] = "免费"

    release = data.get("release_date") or {}
    if isinstance(release, dict):
        date_text = str(release.get("date") or "").strip()
        if date_text:
            stats["发布时间"] = date_text
        if release.get("coming_soon"):
            detail["发售状态"] = "即将推出"

    review_score_desc = ""
    try:
        payload = _get_json_dual(
            _APPREVIEWS_URL.format(appid=appid), proxy=proxy, timeout=10
        )
        summary_info = (payload or {}).get("query_summary") or {}
        total_reviews = summary_info.get("total_reviews")
        total_positive = summary_info.get("total_positive")
        review_score_desc = str(summary_info.get("review_score_desc") or "").strip()
        if isinstance(total_reviews, int) and total_reviews > 0:
            stats["评测数"] = total_reviews
            if isinstance(total_positive, int) and total_positive > 0:
                stats["好评率"] = f"{round(total_positive * 100 / total_reviews)}%"
        if review_score_desc:
            detail["评测结论"] = review_score_desc
    except ParseHttpError:
        pass

    developers = [str(x) for x in (data.get("developers") or []) if str(x).strip()]
    publishers = [str(x) for x in (data.get("publishers") or []) if str(x).strip()]
    if developers:
        detail["开发商"] = "、".join(developers)
    if publishers and publishers != developers:
        detail["发行商"] = "、".join(publishers)
    genres = [
        str(g.get("description") or "").strip()
        for g in (data.get("genres") or [])
        if isinstance(g, dict) and str(g.get("description") or "").strip()
    ]
    if genres:
        detail["类型"] = "、".join(genres)

    app_type = str(data.get("type") or "").strip().lower()
    item_kind = app_type if app_type in _KNOWN_APP_TYPES else "game"

    screenshots = data.get("screenshots") or []
    screenshot = ""
    if isinstance(screenshots, list) and screenshots:
        first = screenshots[0]
        if isinstance(first, dict):
            screenshot = str(first.get("path_full") or "")
    if screenshot:
        detail["截图"] = screenshot

    return build_parsed_content(
        platform="steam",
        item_id=appid,
        item_kind=item_kind,
        title=str(data.get("name") or f"Steam 商店 #{appid}"),
        author_name=developers[0] if developers else "",
        summary=summary,
        cover_url=str(data.get("header_image") or ""),
        canonical_url=url,
        stats=stats,
        parse_depth="deep",
        page_type="store_page",
        badge="即将推出" if detail.get("发售状态") else "",
        detail=detail,
    )


def _parse_steam_store(url: str, *, proxy: str) -> ParsedContent:
    match = re.search(r"store\.steampowered\.com/app/(\d+)", url)
    if not match:
        raise ParseHttpError("steam: no appid in store url")
    appid = match.group(1)
    try:
        payload = _get_json_dual(_APPDETAILS_URL.format(appid=appid), proxy=proxy)
        app = (payload or {}).get(appid) or {}
        if app.get("success") and isinstance(app.get("data"), dict):
            data = app["data"]
            if str(data.get("name") or "").strip():
                return _steam_store_card(appid, data, url, proxy=proxy)
    except ParseHttpError:
        pass
    return _og_scrape(
        url,
        platform="steam",
        item_kind="game",
        note="（商店接口不可用，浅层解析）",
        referer="https://store.steampowered.com/",
        proxy=proxy,
    )


# ---------------------------------------------------------------------------
# 社区游戏 hub
# ---------------------------------------------------------------------------


def _parse_steam_hub(url: str, *, cookie_header: str, proxy: str) -> ParsedContent:
    match = re.search(r"steamcommunity\.com/app/(\d+)", url)
    appid = match.group(1) if match else ""
    _, text = _get_text_dual(
        url, cookie=cookie_header, referer="https://steamcommunity.com/", proxy=proxy
    )
    title = _split_steam_title(_og_title_of(text) or _title_tag_of(text))
    if not title:
        raise ParseHttpError("steam: no title on community hub page")
    summary = _og_desc_of(text)
    # og:description 常以游戏名开头（"XXX - 这是一款…"），去重。
    if summary.startswith(title + " - "):
        summary = summary[len(title) + 3 :].strip()
    return build_parsed_content(
        platform="steam",
        item_id=appid,
        item_kind="game_hub",
        title=title,
        summary=summary,
        cover_url=_og_image_of(text),
        canonical_url=url,
        parse_depth="shallow",
        page_type="community_hub",
        badge="Steam 社区",
    )


# ---------------------------------------------------------------------------
# 个人资料（含 /home 动态页：匿名下重定向到登录页，按资料卡处理）
# ---------------------------------------------------------------------------


_PROFILE_PATH_RE = re.compile(r"steamcommunity\.com/(profiles|id)/([0-9A-Za-z_-]+)")


def _profile_card(
    url: str,
    nickname: str,
    *,
    steam_id: str = "",
    avatar: str = "",
    online_state: str = "",
    member_since: str = "",
    location: str = "",
    privacy: str = "",
) -> ParsedContent:
    detail: dict = {}
    if steam_id:
        detail["steam_id"] = steam_id
    if member_since:
        detail["加入时间"] = member_since
    if location:
        detail["所在地"] = location
    if privacy:
        detail["资料可见性"] = privacy
    stats: dict = {}
    if online_state:
        stats["状态"] = "在线" if online_state.lower() in ("online", "in-game") else "离线"
        if online_state.lower() == "in-game":
            stats["状态"] = "游戏中"
    title = nickname or "Steam 用户"
    summary = "（Steam 个人资料卡；动态列表需要登录后才能查看）"
    return build_parsed_content(
        platform="steam",
        item_id=steam_id,
        item_kind="user",
        title=title,
        author_name=nickname,
        summary=summary,
        cover_url=avatar,
        canonical_url=url,
        stats=stats,
        parse_depth="shallow",
        page_type="profile",
        badge="Steam 个人",
        detail=detail,
    )


def _steam_profile_from_xml(xml_text: str, url: str) -> ParsedContent | None:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    fields = {child.tag: (child.text or "").strip() for child in root}
    nickname = fields.get("steamID") or ""
    if not nickname:
        return None
    return _profile_card(
        url,
        nickname,
        steam_id=fields.get("steamID64") or "",
        avatar=fields.get("avatarFull") or fields.get("avatarMedium") or "",
        online_state=fields.get("onlineState") or "",
        member_since=fields.get("memberSince") or "",
        location=fields.get("location") or "",
        privacy=fields.get("privacyState") or "",
    )


def _parse_steam_profile(url: str, *, cookie_header: str, proxy: str) -> ParsedContent:
    match = _PROFILE_PATH_RE.search(url)
    if not match:
        raise ParseHttpError("steam: no steamid in profile url")
    profile_url = f"https://steamcommunity.com/{match.group(1)}/{match.group(2)}/"
    # ?xml=1 匿名可用（公开资料），比 HTML og 更干净；失败回退 og。
    try:
        _, xml_text = _get_text_dual(
            profile_url + "?xml=1", referer="https://steamcommunity.com/", proxy=proxy
        )
        item = _steam_profile_from_xml(xml_text, profile_url)
        if item is not None:
            return item
    except ParseHttpError:
        pass
    try:
        return _og_scrape(
            profile_url,
            platform="steam",
            item_kind="user",
            note="（Steam 个人资料浅卡；动态列表需登录态）",
            referer="https://steamcommunity.com/",
            cookie_header=cookie_header,
            proxy=proxy,
        )
    except ParseHttpError:
        # og 也拿不到（资料私密/注销）：至少把标题栏昵称给出来。
        return _profile_card(profile_url, f"Steam 用户 {match.group(2)}", steam_id=match.group(2))


# ---------------------------------------------------------------------------
# 市场商品
# ---------------------------------------------------------------------------


_MARKET_LISTING_RE = re.compile(r"steamcommunity\.com/market/listings/(\d+)/([^/?#\s]+)")


def _parse_steam_market(url: str, *, cookie_header: str, proxy: str) -> ParsedContent:
    match = _MARKET_LISTING_RE.search(url)
    if not match:
        raise ParseHttpError("steam: no market listing in url")
    appid, hash_name = match.group(1), urllib.parse.unquote(match.group(2))
    listing_url = f"https://steamcommunity.com/market/listings/{appid}/{match.group(2)}"

    _, text = _get_text_dual(
        listing_url,
        cookie=cookie_header,
        referer="https://steamcommunity.com/market/",
        proxy=proxy,
    )
    raw_title = _og_title_of(text) or _title_tag_of(text)
    item_name = _market_item_name(raw_title) if raw_title else ""
    if not item_name:
        raise ParseHttpError("steam: no title on market listing page")
    summary_lines = [f"Steam 社区市场物品，游戏 AppID {appid}。"]

    detail: dict = {"market_hash_name": hash_name, "appid": appid}
    # 游戏名：appdetails 匿名可查（730 → Counter-Strike 2 等）；失败跳过。
    game_name = ""
    try:
        payload = _get_json_dual(
            _APPDETAILS_URL.format(appid=appid), proxy=proxy, timeout=10
        )
        app = (payload or {}).get(appid) or {}
        if app.get("success") and isinstance(app.get("data"), dict):
            game_name = str((app["data"] or {}).get("name") or "").strip()
    except ParseHttpError:
        pass
    if game_name:
        detail["游戏"] = game_name
        summary_lines[0] = f"Steam 社区市场物品，游戏《{game_name}》。"

    stats: dict = {}
    try:
        price_payload = _get_json_dual(
            _PRICE_OVERVIEW_URL.format(appid=appid, name=urllib.parse.quote(hash_name)),
            proxy=proxy,
            timeout=10,
        )
        if isinstance(price_payload, dict) and price_payload.get("success"):
            lowest = str(price_payload.get("lowest_price") or "").strip()
            median = str(price_payload.get("median_price") or "").strip()
            volume = str(price_payload.get("volume") or "").strip()
            price_text = lowest or median
            if price_text:
                stats["参考价"] = price_text
            if median and lowest and median != lowest:
                detail["中位价"] = median
            if volume:
                stats["24h成交"] = volume
    except ParseHttpError:
        pass

    return build_parsed_content(
        platform="steam",
        item_id=hash_name,
        item_kind="market_item",
        title=item_name,
        summary="\n".join(summary_lines),
        cover_url=_og_image_of(text),
        canonical_url=listing_url,
        stats=stats,
        parse_depth="shallow",
        page_type="market_listing",
        badge="Steam 市场",
        detail=detail,
    )


# ---------------------------------------------------------------------------
# og / title 小工具（独立于 generic 的实体解码，处理数字实体）
# ---------------------------------------------------------------------------


def _og_title_of(text: str) -> str:
    match = re.search(
        r"<meta[^>]+property=[\"']og:title[\"'][^>]*content=[\"']([^\"']+)",
        text or "",
        re.IGNORECASE,
    )
    if not match:
        match = re.search(
            r"<meta[^>]+content=[\"']([^\"']+)[\"'][^>]*property=[\"']og:title[\"']",
            text or "",
            re.IGNORECASE,
        )
    return match.group(1) if match else ""


def _og_image_of(text: str) -> str:
    match = re.search(
        r"<meta[^>]+property=[\"']og:image[\"'][^>]*content=[\"']([^\"']+)",
        text or "",
        re.IGNORECASE,
    )
    return match.group(1) if match else ""


def _og_desc_of(text: str) -> str:
    match = re.search(
        r"<meta[^>]+property=[\"']og:description[\"'][^>]*content=[\"']([^\"']+)",
        text or "",
        re.IGNORECASE,
    )
    if not match:
        return ""
    summary = _unescape(match.group(1))
    return summary[:200] + "…" if len(summary) > 200 else summary


def _title_tag_of(text: str) -> str:
    match = re.search(r"<title[^>]*>([^<]+)</title>", text or "", re.IGNORECASE)
    return match.group(1) if match else ""


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def parse_steam(url: str, *, cookie_header: str = "", proxy: str = "") -> ParsedContent:
    """Steam 链接入口：商店页 / 社区 hub / 个人资料 / 市场，其余 og 兜底。"""
    if not cookie_header:
        cookie_header = steam_cookie_header()
    if "store.steampowered.com/app/" in url:
        return _parse_steam_store(url, proxy=proxy)
    if "steamcommunity.com/market/listings/" in url:
        return _parse_steam_market(url, cookie_header=cookie_header, proxy=proxy)
    if re.search(r"steamcommunity\.com/(profiles|id)/", url):
        return _parse_steam_profile(url, cookie_header=cookie_header, proxy=proxy)
    if re.search(r"steamcommunity\.com/app/\d+", url):
        return _parse_steam_hub(url, cookie_header=cookie_header, proxy=proxy)
    # 其余 steamcommunity / steampowered 页面（创意工坊、公告、group 等）og 兜底。
    return _og_scrape(
        url,
        platform="steam",
        item_kind="page",
        referer="https://steamcommunity.com/",
        cookie_header=cookie_header,
        proxy=proxy,
    )
