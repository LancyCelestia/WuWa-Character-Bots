"""B 站商品（会员购 / 魔力赏市集）链接解析。

- 魔力赏市集（mall.bilibili.com）：用公开市集列表接口
  ``/mall-magic-c/internet/c2c/v2/list``（POST，需要登录 Cookie）按商品
  itemsId 翻页匹配商品字段；匹配不到或接口风控时回退页面 og 元信息。
- 会员购（show.bilibili.com/platform/detail.html?id=...）：直接 og 兜底。
- 以上均失败时返回浅层降级卡片，绝不抛异常，保证消息链路不中断。

接口响应参考（仅作为字段契约，代码为本项目自研）：
data.data[] 含 c2cItemsId / c2cItemsName / showPrice / showMarketPrice /
uid / uname / uface / detailDtoList[].name|img|marketPrice|itemsId。
"""

from __future__ import annotations

import re

from plugins.bot_unified_runtime.contracts.media import (
    ParsedContent,
    build_parsed_content,
    parsed_cover_url,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import (
    ParseHttpError,
    http_post_json,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_generic import _og_scrape

_C2C_LIST_API = "https://mall.bilibili.com/mall-magic-c/internet/c2c/v2/list"
_C2C_DETAIL_TEMPLATE = (
    "https://mall.bilibili.com/neul-next/index.html"
    "?page=magic-market_detail&noTitleBar=1&itemsId={items_id}"
)
_ITEMS_ID_RE = re.compile(r"[?&](?:itemsId|c2cItemsId|id)=(\d+)")
_MAX_LIST_PAGES = 5
_PRICE_FILTER = "0-100000001"  # 单位：分，覆盖 0~100 万元区间。
_DISCOUNT_FILTER = "0-101"


def _extract_items_id(url: str) -> str:
    match = _ITEMS_ID_RE.search(url)
    return match.group(1) if match else ""


def _list_request_payload(next_id: str | None) -> dict:
    return {
        "sortType": "TIME_DESC",
        "priceFilters": [_PRICE_FILTER],
        "discountFilters": [_DISCOUNT_FILTER],
        "categoryFilter": "",
        "nextId": next_id,
    }


def _first_detail_dto(item: dict) -> dict:
    detail_dtos = item.get("detailDtoList") or []
    if isinstance(detail_dtos, list) and detail_dtos and isinstance(detail_dtos[0], dict):
        return detail_dtos[0]
    return {}


def _goods_parse_from_item(item: dict, url: str) -> ParsedContent:
    """把市集列表返回的单条商品映射成 ParsedContent。"""
    detail_dto = _first_detail_dto(item)
    items_id = str(item.get("c2cItemsId") or item.get("itemsId") or "")
    title = (
        str(item.get("c2cItemsName") or "")
        or str(detail_dto.get("name") or "")
        or f"B站商品 {items_id}".strip()
    )
    cover = (
        str(detail_dto.get("img") or "")
        or str(item.get("c2cItemsImg") or "")
        or str(item.get("uface") or "")
    )
    show_price = item.get("showPrice")
    show_market_price = item.get("showMarketPrice") or detail_dto.get("marketPrice")
    if show_price is None:
        price_fen = item.get("price")
        show_price = round(float(price_fen) / 100, 2) if price_fen is not None else None

    seller = str(item.get("uname") or "")
    lines: list[str] = []
    if seller:
        lines.append(f"卖家：{seller}")
    intro = str(item.get("c2cItemsDesc") or detail_dto.get("desc") or "").strip()
    if intro:
        lines.append(intro)

    stats: dict = {}
    if show_price is not None:
        stats["价格"] = f"¥{show_price}"
    if show_market_price is not None and show_market_price not in ("", "0", 0):
        stats["原价"] = f"¥{show_market_price}"
    if seller:
        stats["卖家"] = seller

    return build_parsed_content(
        platform="bilibili",
        item_id=items_id,
        item_kind="goods",
        title=title,
        author_name=seller,
        summary="\n".join(lines),
        cover_url=cover,
        canonical_url=url,
        stats=stats,
        parse_depth="deep",
        page_type="goods",
        badge="商品",
        detail={
            "goods": {
                "price": show_price,
                "origin_price": show_market_price,
                "category": str(item.get("categoryName") or item.get("category") or ""),
                "brand": str(item.get("brandName") or item.get("brand") or ""),
                "cover": cover,
                "title": title,
                "intro": intro,
                "seller": seller,
                "seller_uid": str(item.get("uid") or ""),
                "seller_face": str(item.get("uface") or ""),
            }
        },
    )


def _c2c_goods_by_id(items_id: str, url: str, cookie_header: str) -> ParsedContent | None:
    """在魔力赏市集列表中按 itemsId 翻页查找商品（最多若干页）。"""
    next_id: str | None = None
    for _page in range(_MAX_LIST_PAGES):
        payload = _list_request_payload(next_id)
        response = http_post_json(
            _C2C_LIST_API,
            payload,
            timeout=10,
            referer="https://mall.bilibili.com/neul-next/index.html?page=magic-market_index",
            cookie=cookie_header,
        )
        data = response.get("data") if isinstance(response, dict) else None
        if not isinstance(data, dict):
            return None
        items = data.get("data") or []
        if not isinstance(items, list):
            return None
        for item in items:
            if not isinstance(item, dict):
                continue
            candidate = str(item.get("c2cItemsId") or item.get("itemsId") or "")
            if candidate == items_id:
                return _goods_parse_from_item(item, url)
        next_id = data.get("nextId")
        if not next_id:
            return None
    return None


def _og_goods(url: str, items_id: str, cookie_header: str) -> ParsedContent:
    shallow = _og_scrape(
        url,
        platform="bilibili",
        item_kind="goods",
        note="商品详情需登录态，以下为页面公开信息",
        referer="https://www.bilibili.com/",
        cookie_header=cookie_header,
    )
    identity = shallow.identity
    content = shallow.content
    goods = {
        "price": None,
        "origin_price": None,
        "category": "",
        "brand": "",
        "cover": parsed_cover_url(shallow),
        "title": content.title if content else "",
        "intro": content.summary if content else "",
    }
    return build_parsed_content(
        platform=identity.platform if identity else "bilibili",
        item_id=items_id,
        item_kind="goods",
        title=content.title if content else "",
        summary=content.summary if content else "",
        cover_url=parsed_cover_url(shallow),
        canonical_url=identity.canonical_url if identity else url,
        parse_depth=shallow.provenance.parse_depth if shallow.provenance else "shallow",
        page_type="goods",
        badge="商品",
        detail={"goods": goods},
    )


def _degraded_goods(url: str, items_id: str) -> ParsedContent:
    title = f"B站商品 {items_id}".strip() if items_id else "B站商品"
    return build_parsed_content(
        platform="bilibili",
        item_id=items_id,
        item_kind="goods",
        title=title,
        summary="商品详情需登录态或浏览器渲染，暂未获取完整数据。",
        canonical_url=url,
        parse_depth="shallow",
        page_type="goods",
        badge="商品",
    )


def parse_bilibili_goods(url: str, *, cookie_header: str = "") -> ParsedContent:
    """B 站商品链接解析：市集列表匹配 → og 兜底 → 浅层降级，不抛异常。"""
    items_id = _extract_items_id(url)
    try:
        if "mall.bilibili.com" in url and items_id:
            deep = _c2c_goods_by_id(items_id, url, cookie_header)
            if deep is not None:
                return deep
        try:
            return _og_goods(url, items_id, cookie_header)
        except ParseHttpError:
            pass
    except ParseHttpError:
        pass
    return _degraded_goods(url, items_id)
