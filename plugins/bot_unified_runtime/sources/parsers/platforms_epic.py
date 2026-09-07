"""Epic 游戏商城链接解析（/p/{slug} 商品页）。

站点是 Cloudflare 保护的 SPA，匿名请求直接 403，必须带 epic 组 cookie
（store.epicgames.com 的 cf_clearance / EPIC_* 会话，来自 Netscape cookie
文件；cf_clearance 与导出时的 IP+UA 绑定，换环境可能失效 → 自动降级）。

数据源（一次页面请求，两个内嵌结构，全部实测）：

- ``<script type="application/ld+json" id="_schemaOrgMarkup-Product">``：
  schema.org Product —— 名称/简介/发行商/发售日期/各版本价格；
- ``window.__REACT_QUERY_INITIAL_QUERIES__``：react-query 预取缓存，
  ``getCatalogOffer`` 查询的 ``Catalog.catalogOffer`` 节点有开发者、
  类型标签、fmtPrice 格式化价格、prePurchase（预售）等。
- og meta 作为兜底标题源。

旧 catalog REST 服务（store-content / catalog-public-service）已实测 404，
不再使用。Cookie 值只进请求头，绝不进日志/异常/输出。
"""

from __future__ import annotations

import functools
import json
import os
import re
import time
from pathlib import Path

from plugins.bot_unified_runtime.contracts.media import (
    ParsedContent,
    build_parsed_content,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import (
    ParseHttpError,
    http_get_text,
)

# 大陆直连 Epic 商城被 Cloudflare 拦（匿名 403），失败走代理兜底。
_FALLBACK_PROXY = "http://127.0.0.1:7890"

_EPIC_COOKIE_DOMAINS = ("epicgames.com", "unrealengine.com")
_COOKIES_ENV = "BOT_COOKIES_FILE"
_RUNTIME_DATA_ENV = "BOT_RUNTIME_DATA_DIR"

_PAGE_URL = "https://store.epicgames.com/zh-CN/p/{slug}"

_LDJSON_RE = re.compile(
    r'<script[^>]+id="_schemaOrgMarkup-Product"[^>]*>(.*?)</script>', re.DOTALL
)
_REACT_QUERY_RE = re.compile(r"window\.__REACT_QUERY_INITIAL_QUERIES__\s*=\s*")

# Epic 价格小数位：部分币种无最小货币单位。
_CURRENCY_ZERO_DECIMALS = {"JPY": "JP¥", "KRW": "₩", "VND": "₫", "CLP": "CLP$", "HUF": "Ft"}
_CURRENCY_SYMBOLS = {"CNY": "¥", "USD": "US$", "EUR": "€", "GBP": "£", "TWD": "NT$", "HKD": "HK$"}


# ---------------------------------------------------------------------------
# Cookie 兜底加载（cookies.py 白名单没有 epic；值只进请求头，绝不外泄）。
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
        if raw == "data":
            candidates.append(runtime_root)
        elif raw.startswith("data/"):
            candidates.append(runtime_root / raw[5:])
        else:
            candidates.append(runtime_root / path)
    project_root = Path(__file__).resolve().parents[4]
    candidates.append(project_root / path)
    candidates.append(project_root.parent / "ChatBot_Runtime" / "data" / "platform_cookies.txt")
    return candidates


@functools.lru_cache(maxsize=1)
def _load_epic_cookie_entries() -> tuple[tuple[str, str, str, str, int], ...]:
    """(domain, name, value, path, expires) 五元组；失败返回空（走 og/直接抛错）。"""
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


def epic_cookie_header(host: str = "store.epicgames.com") -> str:
    """按主机拼 epic 组 cookie 头（同名 cookie 取更具体路径/更新的值）。"""
    matched: dict[str, tuple[str, int, str]] = {}
    order: list[str] = []
    for domain, name, value, path, expires in _load_epic_cookie_entries():
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
# 页面抓取：带 cookie 直连 → 带 cookie 代理。
# ---------------------------------------------------------------------------


def _fetch_page_html(url: str, *, cookie_header: str, proxy: str) -> str:
    attempts = [proxy] if proxy else ["", _FALLBACK_PROXY]
    last: Exception | None = None
    for attempt in attempts:
        try:
            _, text = http_get_text(
                url,
                timeout=15,
                referer="https://store.epicgames.com/",
                cookie=cookie_header,
                proxy=attempt,
            )
            if "cf-error" in text[:2000].lower() or (
                "<title>Attention Required" in text
            ):
                raise ParseHttpError("epic: cloudflare challenge page")
            return text
        except ParseHttpError as exc:
            last = exc
    raise last or ParseHttpError(f"GET {url} failed")


# ---------------------------------------------------------------------------
# ld+json Product
# ---------------------------------------------------------------------------


def _ldjson_product(html_text: str) -> dict | None:
    match = _LDJSON_RE.search(html_text or "")
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except (ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _base_offer(ld: dict, slug: str) -> dict | None:
    """AggregateOffer.offers 里找 URL 命中页面 slug 的标准版；否则取第一个。"""
    offers_root = ld.get("offers")
    candidates: list[dict] = []
    if isinstance(offers_root, dict):
        raw = offers_root.get("offers")
        if isinstance(raw, list):
            candidates = [o for o in raw if isinstance(o, dict)]
    elif isinstance(offers_root, list):
        candidates = [o for o in offers_root if isinstance(o, dict)]
    if not candidates:
        return None
    for offer in candidates:
        offer_url = str(offer.get("url") or "")
        if offer_url.rstrip("/").endswith(f"/p/{slug}") or offer_url == f"/p/{slug}":
            return offer
    return candidates[0]


def _epic_format_price(amount: object, currency: str, decimals: int | None) -> str:
    try:
        value = int(str(amount))
    except (TypeError, ValueError):
        return ""
    if currency in _CURRENCY_ZERO_DECIMALS:
        symbol = _CURRENCY_ZERO_DECIMALS[currency]
        return f"{symbol}{value:,}"
    places = 2 if decimals is None else decimals
    symbol = _CURRENCY_SYMBOLS.get(currency, f"{currency} ")
    return f"{symbol}{value / (10**places):,.{places}f}"


# ---------------------------------------------------------------------------
# react-query 缓存里的 catalogOffer 节点
# ---------------------------------------------------------------------------


def _react_query_catalog_offers(html_text: str) -> list[dict]:
    """从 __REACT_QUERY_INITIAL_QUERIES__ 收集 Catalog.catalogOffer 节点。"""
    match = _REACT_QUERY_RE.search(html_text or "")
    if not match:
        return []
    start = match.end()
    end = html_text.find("</script>", start)
    if end < 0:
        return []
    try:
        payload, _ = json.JSONDecoder().raw_decode(html_text[start:end].strip())
    except (ValueError, TypeError):
        return []
    queries = payload.get("queries") if isinstance(payload, dict) else None
    if not isinstance(queries, list):
        return []
    offers: list[dict] = []
    for query in queries:
        if not isinstance(query, dict):
            continue
        state = query.get("state")
        data = state.get("data") if isinstance(state, dict) else None
        catalog = data.get("Catalog") if isinstance(data, dict) else None
        offer = catalog.get("catalogOffer") if isinstance(catalog, dict) else None
        if isinstance(offer, dict) and str(offer.get("title") or "").strip():
            offers.append(offer)
    return offers


def _offer_total_price(offer: dict) -> dict:
    price = offer.get("price")
    total = price.get("totalPrice") if isinstance(price, dict) else None
    return total if isinstance(total, dict) else {}


def _price_stats(offer: dict, *, base_ld_offer: dict | None) -> dict:
    """定价 → stats。有折扣拆 原价/折扣价/折扣；否则给 价格。"""
    stats: dict = {}
    total = _offer_total_price(offer)
    currency = str(total.get("currencyCode") or "")
    fmt = total.get("fmtPrice")
    if not isinstance(fmt, dict):
        fmt = {}
    decimals = total.get("currencyInfo", {}).get("decimals") if isinstance(
        total.get("currencyInfo"), dict
    ) else None
    original_price = total.get("originalPrice")
    discount_price = total.get("discountPrice")
    if isinstance(original_price, int) and isinstance(discount_price, int) and original_price > 0:
        if discount_price < original_price:
            stats["原价"] = str(fmt.get("originalPrice") or "").strip() or _epic_format_price(
                original_price, currency, decimals
            )
            stats["折扣价"] = str(fmt.get("discountPrice") or "").strip() or _epic_format_price(
                discount_price, currency, decimals
            )
            percent = round((original_price - discount_price) * 100 / original_price)
            if percent:
                stats["折扣"] = f"-{percent}%"
            return stats
        stats["价格"] = str(fmt.get("discountPrice") or fmt.get("originalPrice") or "").strip() or (
            _epic_format_price(discount_price, currency, decimals)
        )
        return stats
    # react-query 节点缺失时退回 ld+json 的 Offer.priceSpecification。
    spec = (base_ld_offer or {}).get("priceSpecification")
    spec_price = spec.get("price") if isinstance(spec, dict) else None
    spec_currency = str((spec or {}).get("priceCurrency") or "")
    if isinstance(spec_price, (int, float)) and spec_price > 0:
        stats["价格"] = _epic_format_price(
            int(spec_price), spec_currency, 0 if spec_currency in _CURRENCY_ZERO_DECIMALS else None
        )
    return stats


def _epic_item_detail(
    offer: dict,
    *,
    ld: dict | None,
    all_offers: list[dict],
    slug: str,
) -> dict:
    detail: dict = {}
    developer = str(offer.get("developerDisplayName") or "").strip()
    publisher = str(offer.get("publisherDisplayName") or "").strip()
    if not developer and ld:
        brand = ld.get("brand")
        developer = str(brand.get("name") or "").strip() if isinstance(brand, dict) else ""
    if not publisher and ld:
        publisher = str(ld.get("publisher") or "").strip()
    if developer:
        detail["开发商"] = developer
    if publisher and publisher != developer:
        detail["发行商"] = publisher
    tags = offer.get("tags")
    if isinstance(tags, list):
        genre_names = [
            str(t.get("name") or "").strip()
            for t in tags
            if isinstance(t, dict) and str(t.get("groupName") or "") == "genre"
        ]
        genre_names = [name for name in genre_names if name]
        if genre_names:
            detail["类型"] = "、".join(genre_names)
    if len(all_offers) > 1:
        edition_titles = []
        seen: set[str] = set()
        for candidate in all_offers:
            if not isinstance(candidate, dict):
                continue
            title = str(candidate.get("title") or candidate.get("name") or "").strip()
            if title and title not in seen:
                seen.add(title)
                edition_titles.append(title)
        if len(edition_titles) > 1:
            detail["版本"] = " / ".join(edition_titles[:4]) + (" 等" if len(edition_titles) > 4 else "")
    detail["offer_id"] = str(offer.get("id") or "").strip()
    detail["url_slug"] = str(offer.get("urlSlug") or "").strip() or slug
    return {key: value for key, value in detail.items() if value}


def _release_date_text(offer: dict, ld: dict | None) -> str:
    raw = (
        str(offer.get("pcReleaseDate") or offer.get("releaseDate") or "").strip()
        or (str(ld.get("datePublished") or "").strip() if ld else "")
    )
    return raw[:10]


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def parse_epic(url: str, *, cookie_header: str = "", proxy: str = "") -> ParsedContent:
    """Epic 商城商品页：ld+json + react-query 预取缓存深解析，og 兜底。"""
    match = re.search(r"store\.epicgames\.com/(?:[a-z]{2}-[A-Z]{2}/)?p/([0-9A-Za-z\-]+)", url)
    if not match:
        # bundles / 老版 /product/ 等页面没有对应解析器，og 兜底。
        return _og_fallback(url, cookie_header=cookie_header, proxy=proxy)
    slug = match.group(1)

    if not cookie_header:
        cookie_header = epic_cookie_header()
    html_text = _fetch_page_html(
        _PAGE_URL.format(slug=slug), cookie_header=cookie_header, proxy=proxy
    )

    ld = _ldjson_product(html_text)
    catalog_offers = _react_query_catalog_offers(html_text)
    base_ld_offer = _base_offer(ld, slug) if ld else None
    raw_og_title = _og_title_fallback(html_text, keep_prefix=True)

    title = ""
    summary = ""
    if ld and str(ld.get("name") or "").strip():
        title = str(ld["name"]).strip()
        offer_desc = str((base_ld_offer or {}).get("description") or "").strip()
        if not offer_desc:
            offer_desc = str(ld.get("description") or "").strip()
        if offer_desc:
            summary = offer_desc[:200] + ("…" if len(offer_desc) > 200 else "")
    if not title:
        title = _og_title_fallback(html_text)
    if not title:
        raise ParseHttpError("epic: no product title in page")
    if not summary:
        summary = _og_desc_fallback(html_text)

    # 基准 catalogOffer：标题与 ld+json 产品名一致的标准版；否则第一个。
    base_offer: dict = {}
    for offer in catalog_offers:
        if str(offer.get("title") or "").strip() == title:
            base_offer = offer
            break
    if not base_offer and catalog_offers:
        base_offer = catalog_offers[0]

    stats = _price_stats(
        base_offer if base_offer else {}, base_ld_offer=base_ld_offer
    )
    release_date = _release_date_text(base_offer, ld)
    if release_date:
        stats["发布时间"] = release_date

    all_ld_offers: list[dict] = []
    if base_ld_offer and isinstance(ld, dict):
        raw_offers = (ld.get("offers") or {}).get("offers") if isinstance(
            ld.get("offers"), dict
        ) else None
        if isinstance(raw_offers, list):
            all_ld_offers = [o for o in raw_offers if isinstance(o, dict)]

    # 版本名优先用 ld+json（带"标准/豪华"后缀），react-query 只有一个节点时补不了。
    detail = _epic_item_detail(
        base_offer,
        ld=ld,
        all_offers=all_ld_offers if len(all_ld_offers) > 1 else catalog_offers,
        slug=slug,
    )
    pre_purchase = bool(base_offer.get("prePurchase")) or raw_og_title.startswith("预购")

    cover = _og_image_fallback(html_text) or str((ld or {}).get("image") or "")
    canonical = str((ld or {}).get("url") or "").strip() or f"https://store.epicgames.com/p/{slug}"

    return build_parsed_content(
        platform="epic",
        item_id=slug,
        item_kind="game",
        title=title,
        author_name=str(base_offer.get("publisherDisplayName") or (ld or {}).get("publisher") or ""),
        summary=summary,
        cover_url=cover,
        canonical_url=canonical,
        stats=stats,
        parse_depth="deep",
        page_type="store_page",
        badge="预购" if pre_purchase else "",
        detail=detail,
    )


def _og_title_fallback(html_text: str, *, keep_prefix: bool = False) -> str:
    match = re.search(
        r"<meta[^>]+property=[\"']og:title[\"'][^>]*content=[\"']([^\"']+)",
        html_text or "",
        re.IGNORECASE,
    )
    if not match:
        return ""
    # og:title 形如 "预购 鬼武者 Way of the Sword - Epic游戏商城"，去掉站名后缀。
    raw = match.group(1).strip()
    for suffix in (" - Epic游戏商城", " - Epic Games Store"):
        if raw.endswith(suffix):
            raw = raw[: -len(suffix)].strip()
    if not keep_prefix:
        raw = re.sub(r"^预购\s*", "", raw)
    return raw


def _og_desc_fallback(html_text: str) -> str:
    match = re.search(
        r"<meta[^>]+property=[\"']og:description[\"'][^>]*content=[\"']([^\"']+)",
        html_text or "",
        re.IGNORECASE,
    )
    if not match:
        return ""
    summary = match.group(1).strip()
    return summary[:200] + "…" if len(summary) > 200 else summary


def _og_image_fallback(html_text: str) -> str:
    match = re.search(
        r"<meta[^>]+property=[\"']og:image[\"'][^>]*content=[\"']([^\"']+)",
        html_text or "",
        re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""


def _og_fallback(url: str, *, cookie_header: str, proxy: str) -> ParsedContent:
    """非 /p/ 商品页（bundles、老链接等）og 兜底。"""
    if not cookie_header:
        cookie_header = epic_cookie_header()
    last: Exception | None = None
    for attempt in ([proxy] if proxy else ["", _FALLBACK_PROXY]):
        try:
            _, text = http_get_text(
                url,
                timeout=15,
                referer="https://store.epicgames.com/",
                cookie=cookie_header,
                proxy=attempt,
            )
            title = _og_title_fallback(text)
            if title:
                return build_parsed_content(
                    platform="epic",
                    item_id="",
                    item_kind="page",
                    title=title,
                    summary=_og_desc_fallback(text),
                    cover_url=_og_image_fallback(text),
                    canonical_url=url,
                    parse_depth="shallow",
                )
        except ParseHttpError as exc:
            last = exc
    raise last or ParseHttpError(f"epic: no og data for {url}")
