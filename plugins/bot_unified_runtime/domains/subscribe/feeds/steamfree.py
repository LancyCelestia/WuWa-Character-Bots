"""Steam 免费游戏（限免 100% 折扣）数据源：商店 featured categories 接口。

`https://store.steampowered.com/api/featuredcategories/?l=schinese&cc=cn`
的 ``specials.items`` 里 ``discount_percent == 100`` 即当前免费领取的游戏。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from plugins.bot_unified_runtime.sources.parsers.http_util import http_get_json

_STEAM_FEATURED_API = "https://store.steampowered.com/api/featuredcategories/"


def fetch_steam_free_games(
    *, proxy: str = "", timeout: float = 12.0, limit: int = 6
) -> list[dict[str, Any]]:
    """拉取 Steam 当前 100% 折扣（免费领）游戏列表；失败抛异常由调用方降级。"""
    payload = http_get_json(
        _STEAM_FEATURED_API + "?l=schinese&cc=cn", proxy=proxy, timeout=timeout
    )
    specials = (payload or {}).get("specials") or {}
    games: list[dict[str, Any]] = []
    now = datetime.now().astimezone()
    for item in specials.get("items") or []:
        if item.get("discount_percent") != 100:
            continue
        title = str(item.get("name") or "").strip()
        if not title:
            continue
        end_ts = item.get("discount_end_date") or 0
        end = ""
        if isinstance(end_ts, (int, float)) and end_ts > 0:
            end_dt = datetime.fromtimestamp(end_ts).astimezone()
            end = end_dt.strftime("%m-%d %H:%M")
            if now > end_dt:
                continue  # 已结束的限免不展示
        games.append(
            {
                "title": title,
                "status": "免费中",
                "start": "",
                "end": end,
                "url": f"https://store.steampowered.com/app/{item.get('id')}",
                "source": "Steam",
                "image": str(item.get("header_image") or ""),
            }
        )
        if len(games) >= max(1, limit):
            break
    return games
