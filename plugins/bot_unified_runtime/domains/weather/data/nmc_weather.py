"""中国气象局（NMC）天气查询（适配自 nonebot-plugin-nmcweather 的思路）。

- 数据源：https://www.nmc.cn/rest/weather?stationid={code}&_={ts}（免 key）
- 城市码表：随包内置 qx.json（2527 个区县，34 个省级行政区）
- 全部同步实现，走项目统一 http_util（含超时与错误包装）。
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.domains.finance.data.market_data import (
    sanitize_remote_text,
)
from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
    ParseHttpError,
    http_get_json,
)

_QX_PATH = Path(__file__).parent.parent / "assets" / "qx.json"


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
    # S-FIX-WXDATA F-A（S-ATK-DATA F-A）：数值字段同样要有类型闸——上游回
    # "37<script>" / "1\n伪造行" 时旧写法直接 format 进群聊正文与 prompt。
    try:
        if not math.isfinite(float(str(value).strip())):
            return "❓"
    except (TypeError, ValueError):
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
        # S-FIX-WXSSL M1（2026-09-27）：历史注释「nmc.cn 证书链不完整」经
        # runtime venv 实测证伪（默认上下文 TLS 握手 + JSON 拉取均通过），
        # 撤销 verify_ssl=False。天气/预警正文会原样进群聊与提示词，裸 TLS
        # 通道可被 MITM 伪造；生产路径必须走证书验证（缺省即验证，勿再传
        # verify_ssl=False，tests/test_weather_tls_verification.py 上锁）。
        payload = http_get_json(url, proxy=proxy, timeout=timeout)
    except ParseHttpError:
        return None
    # S-FIX-ATK-WXEMG T1（2026-09-27 审计 SEAT-ATK-WEATHER）：`http_get_json` 返回
    # **任意** JSON 类型（顶层数组/字符串/整数都出得来，见 http_util.py:402），
    # 畸形/改版响应必须在建报文字段之前走既有失败面 `return None`——让调用方的
    # 降级链（Open-Meteo 全球兜底→诚实播报查不到）继续跑；旧写法
    # `((payload or {}).get(...) or {})` 对 list/str 直接抛 AttributeError，
    # 冲出 capability 吃「内部错误回执」，把整条兜底链烧掉。锁：
    # tests/test_weather_nmc_malformed_json_degrade.py。
    data = payload.get("data") if isinstance(payload, dict) else None
    real = data.get("real") if isinstance(data, dict) else None
    if not isinstance(real, dict) or not real:
        return None

    def _subdict(key: str) -> dict[str, Any]:
        value = real.get(key)
        return value if isinstance(value, dict) else {}

    station = _subdict("station")
    weather = _subdict("weather")
    wind = _subdict("wind")
    sunrise_sunset = _subdict("sunriseSunset")

    def known(value: Any) -> bool:
        return str(value).strip() not in {"9999", "9999.0", ""}

    def known_text(value: Any) -> str:
        # S-FIX-WXDATA F-A（S-ATK-DATA F-A）：站名/天气/风向/发布时间等上游
        # 自由文本进群聊正文与 prompt 前过中央清洗尺（复用金融腿
        # sanitize_remote_text，禁第二套尺）——换行/控制符折叠为单行，
        # 注入文字只准留在自己行内，不得凭空多出「发布时间/【…天气】」样式行。
        return sanitize_remote_text(value) or "❓"

    lines = [
        f"【{sanitize_remote_text(station.get('province'))}{sanitize_remote_text(station.get('city'))}天气】",
        f"🕒 发布时间：{known_text(real.get('publish_time')) if known(real.get('publish_time')) else '❓'}",
        f"🌤 当前天气：{known_text(weather.get('info')) if known(weather.get('info')) else '❓'}",
        (
            f"🌡 温度：{_format_value(weather.get('temperature'), '{}℃')}"
            f"（体感 {_format_value(weather.get('feelst'), '{}℃')}）"
        ),
        f"📈 温差：{_format_value(weather.get('temperatureDiff'), '{}℃')}",
        f"💧 湿度：{_format_value(weather.get('humidity'), '{}%')}",
        (
            f"🌬 风力：{known_text(wind.get('direct')) if known(wind.get('direct')) else '❓'}"
            f"{known_text(wind.get('power')) if known(wind.get('power')) else '❓'}"
            f"（{_format_value(wind.get('speed'), '{}m/s')}）"
        ),
        f"☔ 降水量：{_format_value(weather.get('rain'), '{}mm')}",
        f"📊 舒适度：{_comfort_desc(weather.get('icomfort'))}",
        f"🌅 日出：{known_text(sunrise_sunset.get('sunrise')) if known(sunrise_sunset.get('sunrise')) else '❓'}",
        f"🌇 日落：{known_text(sunrise_sunset.get('sunset')) if known(sunrise_sunset.get('sunset')) else '❓'}",
    ]
    return "\n".join(lines)


def nmc_weather_query(
    query: str,
    *,
    proxy: str = "",
    timeout: float | None = None,
) -> str | None:
    """`天气 <城市>` / `天气 <省>-<市>` → 天气报告；失败返回 None。

    S-FIX-WX-T6：可选 `timeout` 透传给 `fetch_nmc_weather`；不传（None）＝旧行为
    （吃 fetch_nmc_weather 自身缺省 10.0），装配处实传 `bot_weather_timeout_seconds`
    后超时才真正受配置支配。
    """
    query = query.strip()
    parts = [part.strip() for part in query.split("-") if part.strip()]
    stationid: str | None = None
    if len(parts) >= 2:
        stationid = find_city_code(parts[0], parts[1])
    if not stationid:
        stationid = search_city_code(query)
    if not stationid:
        return None
    if timeout is None:
        return fetch_nmc_weather(stationid, proxy=proxy)
    return fetch_nmc_weather(stationid, proxy=proxy, timeout=timeout)
