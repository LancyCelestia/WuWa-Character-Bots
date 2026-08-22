"""中国气象局（NMC）天气查询（适配自 nonebot-plugin-nmcweather 的思路）。

- 数据源：https://www.nmc.cn/rest/weather?stationid={code}&_={ts}（免 key）
- 城市码表：随包内置 qx.json（2527 个区县，34 个省级行政区）
- 全部同步实现，走项目统一 http_util（含超时与错误包装）。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.sources.parsers.http_util import (
    ParseHttpError,
    http_get_json,
)

_QX_PATH = Path(__file__).parent / "data" / "qx.json"


def _load_city_database() -> list[dict[str, str]]:
    try:
        return json.loads(_QX_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


_CITY_DATABASE: list[dict[str, str]] = _load_city_database()


def search_city_code(keyword: str) -> str | None:
    """全局模糊搜索城市代码：全称优先，其次前缀。"""
    keyword = keyword.strip()
    if not keyword:
        return None
    for item in _CITY_DATABASE:
        if keyword == item["city"]:
            return item["code"]
    for item in _CITY_DATABASE:
        if item["city"].startswith(keyword):
            return item["code"]
    return None


def find_city_code(province: str, city: str) -> str | None:
    """「省份-城市」两级模糊匹配（支持简称）。"""
    province = province.strip()
    city = city.strip()
    matched_provinces = [
        item
        for item in _CITY_DATABASE
        if province in item["province"] or item["province"].startswith(province)
    ]
    if not matched_provinces:
        return None
    for item in matched_provinces:
        if city == item["city"] or item["city"].startswith(city):
            return item["code"]
    return None


def list_districts(province: str) -> dict[str, Any]:
    """省份下的全部区县名称。"""
    province = province.strip()
    matched = list(
        {
            item["province"]: None
            for item in _CITY_DATABASE
            if province in item["province"]
        }.keys()
    )
    if not matched:
        return {"province": "", "districts": []}
    target = max(matched, key=len)
    districts = [
        item["city"]
        for item in _CITY_DATABASE
        if item["province"] == target
    ]
    return {"province": target, "districts": districts}


def _format_value(value: Any, pattern: str) -> str:
    if str(value).strip() in {"9999", "9999.0", ""}:
        return "❓"
    try:
        return pattern.format(value)
    except (ValueError, KeyError):
        return "❓"


def _comfort_desc(level: Any) -> str:
    try:
        level_int = int(level)
    except (TypeError, ValueError):
        level_int = 9999
    mapping = {
        -4: "很冷，极不适应",
        -3: "冷，很不舒适",
        -2: "凉，不舒适",
        -1: "凉爽，较舒适",
        0: "舒适，最可接受",
        1: "温暖，较舒适",
        2: "暖，不舒适",
        3: "热，很不舒适",
        4: "很热，极不适应",
    }
    return mapping.get(level_int, "未知")


def fetch_nmc_weather(stationid: str, *, proxy: str = "", timeout: float = 10.0) -> str | None:
    """拉取并格式化 NMC 天气；失败返回 None。"""
    url = f"https://www.nmc.cn/rest/weather?stationid={stationid}&_={int(time.time() * 1000)}"
    try:
        # nmc.cn 证书链不完整，python 标准库校验失败，这里关闭校验
        # （数据为公开天气信息，非敏感）。
        payload = http_get_json(url, proxy=proxy, timeout=timeout, verify_ssl=False)
    except ParseHttpError:
        return None
    real = ((payload or {}).get("data") or {}).get("real") or {}
    if not real:
        return None
    station = real.get("station") or {}
    weather = real.get("weather") or {}
    wind = real.get("wind") or {}
    sunrise_sunset = real.get("sunriseSunset") or {}

    def known(value: Any) -> bool:
        return str(value).strip() not in {"9999", "9999.0", ""}

    lines = [
        f"【{station.get('province', '')}{station.get('city', '')}天气】",
        f"🕒 发布时间：{real.get('publish_time') if known(real.get('publish_time')) else '❓'}",
        f"🌤 当前天气：{weather.get('info') if known(weather.get('info')) else '❓'}",
        f"🌡 温度：{_format_value(weather.get('temperature'), '{}℃')}"
        f"（体感 {_format_value(weather.get('feelst'), '{}℃')}）",
        f"📈 温差：{_format_value(weather.get('temperatureDiff'), '{}℃')}",
        f"💧 湿度：{_format_value(weather.get('humidity'), '{}%')}",
        f"🌬 风力：{wind.get('direct') if known(wind.get('direct')) else '❓'}"
        f"{wind.get('power') if known(wind.get('power')) else '❓'}"
        f"（{_format_value(wind.get('speed'), '{}m/s')}）",
        f"☔ 降水量：{_format_value(weather.get('rain'), '{}mm')}",
        f"📊 舒适度：{_comfort_desc(weather.get('icomfort'))}",
        f"🌅 日出：{sunrise_sunset.get('sunrise') if known(sunrise_sunset.get('sunrise')) else '❓'}",
        f"🌇 日落：{sunrise_sunset.get('sunset') if known(sunrise_sunset.get('sunset')) else '❓'}",
    ]
    return "\n".join(lines)


def nmc_weather_query(
    query: str,
    *,
    proxy: str = "",
) -> str | None:
    """`天气 <城市>` / `天气 <省>-<市>` → 天气报告；失败返回 None。"""
    query = query.strip()
    parts = [part.strip() for part in query.split("-") if part.strip()]
    stationid: str | None = None
    if len(parts) >= 2:
        stationid = find_city_code(parts[0], parts[1])
    if not stationid:
        stationid = search_city_code(query)
    if not stationid:
        return None
    return fetch_nmc_weather(stationid, proxy=proxy)
