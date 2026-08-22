"""Epic 商城每周免费游戏（bot.epic）。

数据源：Epic 公开的免费促销接口（免 key）：
GET https://store-site-backend-static-ipv4.ak.epicgames.com/freeGamesPromotions
    ?locale=zh-CN&country=CN&allowCountries=CN
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from plugins.bot_unified_runtime.sources.parsers.http_util import (
    ParseHttpError,
    http_get_json,
)

_EPIC_API = (
    "https://store-site-backend-static-ipv4.ak.epicgames.com/freeGamesPromotions"
    "?locale=zh-CN&country=CN&allowCountries=CN"
)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def fetch_epic_free_games(*, proxy: str = "", timeout: float = 12.0) -> list[dict[str, Any]]:
    payload = http_get_json(_EPIC_API, proxy=proxy, timeout=timeout)
    elements = (
        ((payload or {}).get("data") or {})
        .get("Catalog", {})
        .get("searchStore", {})
        .get("elements")
        or []
    )
    games: list[dict[str, Any]] = []
    for element in elements:
        title = str(element.get("title") or "").strip()
        if not title:
            continue
        offers: list[Any] = []
        for group in (element.get("promotions") or {}).get("promotionalOffers") or []:
            for offer in group.get("promotionalOffers") or []:
                discount = (
                    (offer.get("discountSetting") or {}).get("discountPercentage")
                )
                if discount == 0:
                    offers.append(offer)
        if not offers:
            continue
        start = _parse_time((offers[0].get("startDate")))
        end = _parse_time((offers[0].get("endDate")))
        now = datetime.now().astimezone()
        status = "免费中"
        if start and end and (now < start or now > end):
            status = "限免已结束" if now > end else "即将免费"
        url = ""
        try:
            url = element.get("catalogNs", {}).get("mappings", [{}])[0].get("pageSlug", "")
            if url:
                url = f"https://store.epicgames.com/zh-CN/p/{url}"
        except Exception:  # noqa: BLE001
            url = ""
        games.append(
            {
                "title": title,
                "status": status,
                "start": start.strftime("%m-%d %H:%M") if start else "",
                "end": end.strftime("%m-%d %H:%M") if end else "",
                "url": url,
            }
        )
    return games


def format_epic_free_games(games: list[dict[str, Any]]) -> str:
    if not games:
        return "这周没有正在进行的免费游戏活动。"
    lines = ["Epic 本周免费游戏："]
    for game in games:
        line = f"- {game['title']}"
        if game["end"]:
            line += f"（截止 {game['end']}）"
        if game["url"]:
            line += f"\n  {game['url']}"
        lines.append(line)
    return "\n".join(lines)
