"""Open-Meteo 全球天气兜底（海外/街道级，免 key）。

- geocoding: https://geocoding-api.open-meteo.com/v1/search?name={city}&language=zh&count=1
- forecast:  https://api.open-meteo.com/v1/forecast?latitude=&longitude=&current=temperature_2m,weather_code,wind_speed_10m,relative_humidity_2m&daily=temperature_2m_max,temperature_2m_min,weather_code&timezone=auto&forecast_days=2

NMC 查不到（海外城市/乡镇街道级）时由能力层调用本模块兜底。
"""

from __future__ import annotations

from typing import Any

from plugins.bot_unified_runtime.sources.parsers.http_util import http_get_json

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


def _describe(code: object) -> str:
    try:
        return _WEATHER_CODE_ZH.get(int(str(code or -1)), "未知")
    except (TypeError, ValueError):
        return "未知"


def open_meteo_query(city: str, *, timeout: float = 10.0, proxy: str = "") -> dict[str, Any] | None:
    """全球城市天气；返回结构化结果或 None（城市找不到/接口失败）。"""
    try:
        geo = http_get_json(
            "https://geocoding-api.open-meteo.com/v1/search?"
            + _urlencode_safe({"name": city, "language": "zh", "count": "1"}),
            timeout=timeout,
            proxy=proxy,
        )
    except Exception:  # noqa: BLE001 - 全球源网络失败按未找到降级。
        return None
    results = (geo or {}).get("results") if isinstance(geo, dict) else None
    if not results:
        return None
    # 同名地名可能命中小村庄（如四川"高雄"）：优先人口最多的重要城市。
    results = sorted(
        results,
        key=lambda r: (int(r.get("population") or 0)),
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
        )
    except Exception:  # noqa: BLE001 - 全球源网络失败按未找到降级。
        return None
    if not isinstance(forecast, dict) or not forecast.get("current"):
        return None
    current = forecast.get("current") or {}
    daily = forecast.get("daily") or {}
    name = str(place.get("name") or city)
    region_parts = [
        str(place.get(k) or "")
        for k in ("admin1", "country")
        if place.get(k)
    ]
    location_label = "，".join([name, *region_parts])
    lines = [
        f"📍 {location_label}",
        (
            f"当前：{_describe(current.get('weather_code'))}，"
            f"{current.get('temperature_2m')}°C，"
            f"湿度 {current.get('relative_humidity_2m')}%，"
            f"风速 {current.get('wind_speed_10m')}km/h"
        ),
    ]
    max_t = (daily.get("temperature_2m_max") or [None, None])
    min_t = (daily.get("temperature_2m_min") or [None, None])
    codes = (daily.get("weather_code") or [None, None])
    if len(max_t) >= 2:
        lines.append(
            f"今天 {min_t[0]}~{max_t[0]}°C {_describe(codes[0] if codes else None)}；"
            f"明天 {min_t[1]}~{max_t[1]}°C {_describe(codes[1] if len(codes) > 1 else None)}"
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
