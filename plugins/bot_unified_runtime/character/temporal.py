"""当前环境信息层：本地时间、日期、节气、节日、天气。

- 时间/日期：用 ``zoneinfo`` 按配置时区计算，属于可信信息。
- 节气：用通用天文近似公式计算 24 节气日期（21 世纪系数表）。
- 节日：内置 2026 年常用节日表（农历节日为近似换算，允许后续用
  ``BOT_HOLIDAYS_FILE`` 覆盖）。
- 天气：``WeatherProvider`` 接口 + 默认空实现；配置坐标后可用
  ``OpenMeteoWeatherProvider``（免费、无需 API key）按 TTL 缓存。
  天气属于外部事实，可能不可用或过期，prompt 会明确提示不要编造。

所有信息以 ``TemporalContext`` 进入 ``ContextBundle``，不决定发送、
不写长期记忆、不能覆盖权限与审计。
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from plugins.bot_unified_runtime.contracts.character import TemporalContext

WEEKDAY_NAMES = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")

# 21 世纪 24 节气近似公式系数（日 = int(y*0.2422 + C) - int((y-1)/4)）。
_SOLAR_TERMS: tuple[tuple[str, int, float], ...] = (
    ("小寒", 1, 5.4055),
    ("大寒", 1, 20.12),
    ("立春", 2, 3.87),
    ("雨水", 2, 18.73),
    ("惊蛰", 3, 5.63),
    ("春分", 3, 20.646),
    ("清明", 4, 4.81),
    ("谷雨", 4, 20.1),
    ("立夏", 5, 5.52),
    ("小满", 5, 21.04),
    ("芒种", 6, 5.678),
    ("夏至", 6, 21.37),
    ("小暑", 7, 7.108),
    ("大暑", 7, 22.83),
    ("立秋", 8, 7.5),
    ("处暑", 8, 23.13),
    ("白露", 9, 7.646),
    ("秋分", 9, 23.042),
    ("寒露", 10, 8.318),
    ("霜降", 10, 23.438),
    ("立冬", 11, 7.438),
    ("小雪", 11, 22.36),
    ("大雪", 12, 7.18),
    ("冬至", 12, 21.94),
)

# 2026 年节日表（农历节日为近似换算，日期可能随农历年差异变化）。
DEFAULT_HOLIDAYS_2026: tuple[tuple[str, str], ...] = (
    ("01-01", "元旦"),
    ("02-14", "情人节"),
    ("02-16", "除夕"),
    ("02-17", "春节"),
    ("03-03", "元宵节"),
    ("03-08", "妇女节"),
    ("04-05", "清明节"),
    ("05-01", "劳动节"),
    ("06-01", "儿童节"),
    ("06-19", "端午节"),
    ("08-19", "七夕"),
    ("09-25", "中秋节"),
    ("10-01", "国庆节"),
    ("10-18", "重阳节"),
    ("12-24", "平安夜"),
    ("12-25", "圣诞节"),
)

_WEATHER_CODES: dict[int, str] = {
    0: "晴",
    1: "大致晴朗",
    2: "多云",
    3: "阴",
    45: "有雾",
    48: "雾凇",
    51: "毛毛雨",
    53: "小雨",
    55: "雨",
    56: "冻毛毛雨",
    57: "冻雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "雪粒",
    80: "阵雨",
    81: "阵雨",
    82: "强阵雨",
    85: "阵雪",
    86: "强阵雪",
    95: "雷雨",
    96: "雷雨伴冰雹",
    99: "强雷雨伴冰雹",
}


def solar_term_of(day: datetime) -> str:
    """返回 ``day`` 当天对应的节气名，无则返回空字符串。"""
    year = day.year
    for name, month, coefficient in _SOLAR_TERMS:
        term_day = int(year * 0.2422 + coefficient) - int((year - 1) / 4)
        if day.month == month and day.day == term_day:
            return name
    return ""


def holiday_of(day: datetime, table: tuple[tuple[str, str], ...] | None = None) -> str:
    """返回 ``day`` 当天节日名，无则返回空字符串。"""
    entries = table if table is not None else DEFAULT_HOLIDAYS_2026
    month_day = f"{day.month:02d}-{day.day:02d}"
    for date_key, name in entries:
        if date_key == month_day:
            return name
    return ""


def load_holiday_table(path: str | Path | None) -> tuple[tuple[str, str], ...] | None:
    """从 JSON 文件加载节日表：[["MM-DD", "名称"], ...]；失败返回 None。"""
    if not path:
        return None
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, list):
        return None
    entries: list[tuple[str, str]] = []
    for item in payload:
        if (
            isinstance(item, list)
            and len(item) >= 2
            and all(isinstance(part, str) for part in item[:2])
        ):
            entries.append((item[0], item[1]))
    return tuple(entries) if entries else None


class WeatherProvider(Protocol):
    def current_weather(self, request_id: str) -> str:
        """返回当前天气的中文摘要；不可用时返回空字符串。"""


class NullWeatherProvider:
    def current_weather(self, request_id: str) -> str:
        return ""


@dataclass(frozen=True)
class _WeatherSnapshot:
    summary: str
    fetched_at: float
    source: str = "open-meteo"


class OpenMeteoWeatherProvider:
    """Open-Meteo 免费天气接口（无需 API key）。

    按 ``cache_seconds`` 缓存快照；网络失败时返回缓存的过期快照，
    都没有时返回空字符串，绝不阻塞对话。
    """

    def __init__(
        self,
        *,
        latitude: float,
        longitude: float,
        timeout_seconds: float = 8.0,
        cache_seconds: int = 1800,
    ) -> None:
        self.latitude = float(latitude)
        self.longitude = float(longitude)
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.cache_seconds = max(60, int(cache_seconds))
        self._cache: _WeatherSnapshot | None = None

    def current_weather(self, request_id: str) -> str:
        snapshot = self._fetch_snapshot()
        if snapshot is None:
            return ""
        return snapshot.summary

    def _fetch_snapshot(self) -> _WeatherSnapshot | None:
        now = time.monotonic()
        if self._cache is not None and now - self._cache.fetched_at <= self.cache_seconds:
            return self._cache
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={self.latitude}&longitude={self.longitude}"
            "&current=temperature_2m,apparent_temperature,relative_humidity_2m,weather_code"
            "&timezone=auto&forecast_days=1"
        )
        try:
            with urllib.request.urlopen(url, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            # 网络失败时返回过期缓存（如果有），天气是可选信息，不抛错。
            return self._cache
        current = payload.get("current") if isinstance(payload, dict) else None
        if not isinstance(current, dict):
            return self._cache
        temperature = current.get("temperature_2m")
        apparent = current.get("apparent_temperature")
        humidity = current.get("relative_humidity_2m")
        weather_code = current.get("weather_code")
        parts: list[str] = []
        if isinstance(temperature, (int, float)):
            parts.append(f"气温 {temperature:.0f}°C")
        if isinstance(apparent, (int, float)) and apparent != temperature:
            parts.append(f"体感 {apparent:.0f}°C")
        if isinstance(weather_code, int):
            parts.append(_WEATHER_CODES.get(weather_code, f"天气代码 {weather_code}"))
        if isinstance(humidity, (int, float)):
            parts.append(f"湿度 {humidity:.0f}%")
        if not parts:
            return self._cache
        snapshot = _WeatherSnapshot(
            summary="，".join(parts),
            fetched_at=now,
        )
        self._cache = snapshot
        return snapshot


class RuleBasedTemporalProvider:
    """组合时间/节气/节日/天气的默认实现。"""

    def __init__(
        self,
        *,
        timezone: str = "Asia/Hong_Kong",
        weather_provider: WeatherProvider | None = None,
        holiday_table: tuple[tuple[str, str], ...] | None = None,
    ) -> None:
        self.timezone = timezone
        self.weather_provider = weather_provider or NullWeatherProvider()
        self.holiday_table = holiday_table or DEFAULT_HOLIDAYS_2026

    def snapshot(self, request_id: str) -> TemporalContext:
        try:
            zone = ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError:
            zone = ZoneInfo("UTC")
        now = datetime.now(zone)
        weather_summary = self.weather_provider.current_weather(request_id).strip()
        return TemporalContext(
            request_id=request_id,
            now_local=now.strftime("%H:%M"),
            date_local=now.strftime("%Y-%m-%d"),
            weekday=WEEKDAY_NAMES[now.weekday()],
            timezone=str(zone),
            solar_term=solar_term_of(now),
            holiday=holiday_of(now, self.holiday_table),
            weather_summary=weather_summary,
            weather_ok=bool(weather_summary),
            weather_source="open-meteo" if weather_summary else "",
        )


def build_temporal_provider(config: object) -> RuleBasedTemporalProvider:
    """按配置构造环境信息 provider。"""
    timezone = str(getattr(config, "bot_timezone", "Asia/Hong_Kong")).strip() or (
        "Asia/Hong_Kong"
    )
    weather_enabled = bool(getattr(config, "bot_weather_enabled", False))
    latitude = float(getattr(config, "bot_weather_latitude", 0.0) or 0.0)
    longitude = float(getattr(config, "bot_weather_longitude", 0.0) or 0.0)
    weather_provider: WeatherProvider = NullWeatherProvider()
    if weather_enabled and latitude != 0.0 and longitude != 0.0:
        weather_provider = OpenMeteoWeatherProvider(
            latitude=latitude,
            longitude=longitude,
            timeout_seconds=float(getattr(config, "bot_weather_timeout_seconds", 8.0)),
            cache_seconds=int(getattr(config, "bot_weather_cache_seconds", 1800)),
        )
    holiday_table = load_holiday_table(getattr(config, "bot_holidays_file", ""))
    return RuleBasedTemporalProvider(
        timezone=timezone,
        weather_provider=weather_provider,
        holiday_table=holiday_table,
    )
