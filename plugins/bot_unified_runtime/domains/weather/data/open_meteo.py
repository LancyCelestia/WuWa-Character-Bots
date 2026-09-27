"""Open-Meteo 全球天气兜底（海外/街道级，免 key）。

- geocoding: https://geocoding-api.open-meteo.com/v1/search?name={city}&language=zh&count=1
- forecast:  https://api.open-meteo.com/v1/forecast?latitude=&longitude=&current=temperature_2m,weather_code,wind_speed_10m,relative_humidity_2m&daily=temperature_2m_max,temperature_2m_min,weather_code&timezone=auto&forecast_days=2

NMC 查不到（海外城市/乡镇街道级）时由能力层调用本模块兜底。
"""

from __future__ import annotations

import math
from typing import Any

from plugins.bot_unified_runtime.domains.finance.data.market_data import (
    sanitize_remote_text,
)
from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
    http_get_json,
)

_WEATHER_CODE_ZH: dict[int, str] = {
    0: "晴", 1: "大致晴", 2: "多云", 3: "阴",
    45: "雾", 48: "雾凇",
    51: "毛毛雨", 53: "毛毛雨", 55: "浓毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "强冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "阵雨", 81: "中阵雨", 82: "强阵雨",
    85: "阵雪", 86: "强阵雪",
    95: "雷暴", 96: "雷暴伴冰雹", 99: "强雷暴伴冰雹",
}

# 中文城市名 → 英文标准名（open-meteo geocoding 的 zh 库覆盖不全，
# 「华沙/维也纳」等常查不到；先 zh 后 en 两次尝试）。F18 2026-09-12。
_ZH_EN_CITY_ALIASES: dict[str, str] = {
    "东京": "Tokyo", "华沙": "Warsaw", "莫斯科": "Moscow", "圣彼得堡": "Saint Petersburg",
    "伦敦": "London", "巴黎": "Paris", "柏林": "Berlin", "罗马": "Rome",
    "马德里": "Madrid", "巴塞罗那": "Barcelona", "阿姆斯特丹": "Amsterdam",
    "维也纳": "Vienna", "布拉格": "Prague", "布达佩斯": "Budapest",
    "斯德哥尔摩": "Stockholm", "奥斯陆": "Oslo", "哥本哈根": "Copenhagen",
    "赫尔辛基": "Helsinki", "都柏林": "Dublin", "里斯本": "Lisbon",
    "雅典": "Athens", "苏黎世": "Zurich", "日内瓦": "Geneva",
    "纽约": "New York", "洛杉矶": "Los Angeles", "旧金山": "San Francisco",
    "芝加哥": "Chicago", "多伦多": "Toronto", "温哥华": "Vancouver",
    "墨西哥城": "Mexico City", "圣保罗": "Sao Paulo", "里约热内卢": "Rio de Janeiro",
    "布宜诺斯艾利斯": "Buenos Aires", "利马": "Lima", "开罗": "Cairo",
    "迪拜": "Dubai", "利雅得": "Riyadh", "伊斯坦布尔": "Istanbul",
    "曼谷": "Bangkok", "河内": "Hanoi", "胡志明市": "Ho Chi Minh City",
    "金边": "Phnom Penh", "仰光": "Yangon", "吉隆坡": "Kuala Lumpur",
    "新加坡市": "Singapore", "雅加达": "Jakarta", "马尼拉": "Manila",
    "首尔": "Seoul", "釜山": "Busan", "平壤": "Pyongyang",
    "乌兰巴托": "Ulaanbaatar", "堪培拉": "Canberra", "悉尼": "Sydney",
    "墨尔本": "Melbourne", "奥克兰": "Auckland", "惠灵顿": "Wellington",
    "约翰内斯堡": "Johannesburg", "内罗毕": "Nairobi", "拉各斯": "Lagos",
    "基辅": "Kyiv", "明斯克": "Minsk", "贝尔格莱德": "Belgrade",
}


def _describe(code: object) -> str:
    # S-FIX-WXDATA F-B（2026-09-27，S-ATK-DATA F-B）：旧写法 `code or -1` 把
    # falsy 的 0（晴——最高频码）坍缩成 -1 判「未知」。改为只挡 None。
    if code is None:
        return "未知"
    try:
        return _WEATHER_CODE_ZH.get(int(str(code).strip()), "未知")
    except (TypeError, ValueError):
        return "未知"


def _fmt_num(value: object) -> str:
    """S-FIX-WXDATA F-A：上游数值字段类型闸——非有限数值一律「—」，
    拒绝把 "25\\n注入" / NaN 之类的字符串直插报文（换行会凭空撑爆行骨架）。"""
    try:
        num = float(str(value).strip())
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(num):
        return "—"
    return str(value).strip()


def _geocode(city: str, *, timeout: float, proxy: str) -> list[dict[str, Any]] | None:
    """geocoding 查询；返回候选列表（可能为空）或 None（网络失败）。"""
    try:
        geo = http_get_json(
            "https://geocoding-api.open-meteo.com/v1/search?"
            + _urlencode_safe({"name": city, "language": "zh", "count": "10"}),
            timeout=timeout,
            proxy=proxy,
        )
    except Exception:  # noqa: BLE001 - 全球源网络失败按未找到降级。
        return None
    if not isinstance(geo, dict):
        return None
    results = geo.get("results")
    return results if isinstance(results, list) else []


def open_meteo_query(city: str, *, timeout: float = 10.0, proxy: str = "") -> dict[str, Any] | None:
    """全球城市天气；返回结构化结果或 None（城市找不到/接口失败）。

    F18 修复：候选 count=10 后按人口降序取最优——此前 count=1 时 API 随便
    回一个同名小村庄（「东京」命中华东小镇）；中文查不到时用中英别名表
    换英文标准名重试一次（华沙/维也纳等 zh 库缺失城市）。
    """
    results = _geocode(city, timeout=timeout, proxy=proxy)
    if results is None:
        return None
    if not results:
        alias = _ZH_EN_CITY_ALIASES.get((city or "").strip())
        if alias:
            results = _geocode(alias, timeout=timeout, proxy=proxy) or []
    if not results:
        return None
    # 同名地名优先人口最多的重要城市；同名且人口相近时精确名优先。
    exact = (city or "").strip()
    results = sorted(
        results,
        key=lambda r: (
            1 if str(r.get("name") or "").strip() == exact else 0,
            int(r.get("population") or 0),
        ),
        reverse=True,
    )
    place = results[0]
    lat = place.get("latitude")
    lon = place.get("longitude")
    if lat is None or lon is None:
        return None
    try:
        forecast = http_get_json(
            "https://api.open-meteo.com/v1/forecast?"
            + _urlencode_safe(
                {
                    "latitude": str(lat),
                    "longitude": str(lon),
                    "current": "temperature_2m,weather_code,wind_speed_10m,relative_humidity_2m",
                    "daily": ("temperature_2m_max,temperature_2m_min,weather_code"),
                    "timezone": "auto",
                    "forecast_days": "2",
                }
            ),
            timeout=timeout,
            proxy=proxy,
        )
    except Exception:  # noqa: BLE001 - 全球源网络失败按未找到降级。
        return None
    if not isinstance(forecast, dict) or not forecast.get("current"):
        return None
    current = forecast.get("current") or {}
    daily = forecast.get("daily") or {}
    # S-FIX-WXDATA F-A（S-ATK-DATA）：地名/行政区/国家是上游自由文本，进正文与
    # prompt 前过中央清洗尺（复用金融腿 sanitize_remote_text，禁第二套尺）；
    # 数值字段一律过 _fmt_num 类型闸，防 "…\n…" 撑爆报文行骨架与 NaN 直通。
    name = sanitize_remote_text(place.get("name")) or (city or "")
    region_parts = [
        sanitize_remote_text(place.get(k))
        for k in ("admin1", "country")
        if place.get(k)
    ]
    location_label = "，".join([name, *region_parts])
    lines = [
        f"📍 {location_label}",
        (
            f"当前：{_describe(current.get('weather_code'))}，"
            f"{_fmt_num(current.get('temperature_2m'))}°C，"
            f"湿度 {_fmt_num(current.get('relative_humidity_2m'))}%，"
            f"风速 {_fmt_num(current.get('wind_speed_10m'))}km/h"
        ),
    ]
    max_t = (daily.get("temperature_2m_max") or [None, None])
    min_t = (daily.get("temperature_2m_min") or [None, None])
    codes = (daily.get("weather_code") or [None, None])
    if len(max_t) >= 2:
        lines.append(
            f"今天 {_fmt_num(min_t[0])}~{_fmt_num(max_t[0])}°C {_describe(codes[0] if codes else None)}；"
            f"明天 {_fmt_num(min_t[1])}~{_fmt_num(max_t[1])}°C {_describe(codes[1] if len(codes) > 1 else None)}"
        )
    return {
        "report": "\n".join(lines),
        "location": location_label,
        "latitude": lat,
        "longitude": lon,
        "source": "open-meteo",
    }


def _urlencode_safe(params: dict[str, str]) -> str:
    import urllib.parse

    return urllib.parse.urlencode(params)


def format_open_meteo(result: dict[str, Any]) -> str:
    return str(result.get("report") or "")
