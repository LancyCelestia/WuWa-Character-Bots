"""当前环境信息层：本地时间、日期、节气、节日、天气。

- 时间/日期：用 ``zoneinfo`` 按配置时区计算，属于可信信息。
- 节气：用通用天文近似公式计算 24 节气日期（21 世纪系数表）。
- 节日：内置 2026 年常用节日表（农历节日为近似换算、仅 2026 成立不跨年
  复用，公历固定节日逐年复用；允许后续用 ``BOT_HOLIDAYS_FILE`` 覆盖）。
- 天气：``WeatherProvider`` 接口 + 默认空实现；配置坐标后可用
  ``OpenMeteoWeatherProvider``（免费、无需 API key）按 TTL 缓存。
  天气属于外部事实，可能不可用或过期，prompt 会明确提示不要编造。

所有信息以 ``TemporalContext`` 进入 ``ContextBundle``，不决定发送、
不写长期记忆、不能覆盖权限与审计。
"""

from __future__ import annotations

import functools
import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
    _MAX_RESPONSE_BYTES,
    _shared_http_client,
)
from plugins.bot_unified_runtime.domains.core.contracts.character import TemporalContext

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

# 节日表年份维度（V2.1 风险 7 修复，2026-09-17）：节日分两类——
# 公历固定节日逐年复用；农历节日（近似换算）只对表内年份（2026）成立，
# 绝不跨年复用（2027 春节实为 02-06，套用 2026 表会把 2027-02-17 错报
# 成春节）。``BOT_HOLIDAYS_FILE`` 覆盖表仍为 (MM-DD, 名称) 形态，按表
# 原样匹配（年份语义由表作者负责）。
_GREGORIAN_HOLIDAYS: tuple[tuple[str, str], ...] = (
    ("01-01", "元旦"),
    ("02-14", "情人节"),
    ("03-08", "妇女节"),
    ("04-05", "清明节"),
    ("05-01", "劳动节"),
    ("06-01", "儿童节"),
    ("10-01", "国庆节"),
    ("12-24", "平安夜"),
    ("12-25", "圣诞节"),
)

# 农历节日（2026 年近似换算）：仅 2026 成立。
_LUNAR_HOLIDAYS_2026: tuple[tuple[str, str], ...] = (
    ("02-16", "除夕"),
    ("02-17", "春节"),
    ("03-03", "元宵节"),
    ("06-19", "端午节"),
    ("08-19", "七夕"),
    ("09-25", "中秋节"),
    ("10-18", "重阳节"),
)

DEFAULT_HOLIDAYS_2026: tuple[tuple[str, str], ...] = (
    _LUNAR_HOLIDAYS_2026 + _GREGORIAN_HOLIDAYS
)
_DEFAULT_HOLIDAY_TABLE_YEAR = 2026

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
    """返回 ``day`` 当天节日名，无则返回空字符串。

    默认表带年份维度：农历节日（近似换算）只在表内年份（2026）成立，
    其余年份仅复用公历固定节日——绝不把 2026 农历日期套到别的年份。
    显式注入 ``table`` 时按表原样匹配（保持既有调用方语义）。
    """
    if table is None and day.year != _DEFAULT_HOLIDAY_TABLE_YEAR:
        table = _GREGORIAN_HOLIDAYS
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


def _read_body_limited(response: httpx.Response, limit: int) -> bytes:
    """限长流式读取响应体（读法对齐 ``llm.providers._read_stream_limited``）。

    超限抛异常，由调用方既有失败分支处理，不无界占用内存。
    """
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > limit:
            raise ValueError("weather response exceeds size limit")
        chunks.append(chunk)
    return b"".join(chunks)


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
        http_client_factory: Callable[[], httpx.Client] | None = None,
    ) -> None:
        self.latitude = float(latitude)
        self.longitude = float(longitude)
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.cache_seconds = max(60, int(cache_seconds))
        self._cache: _WeatherSnapshot | None = None
        # 后台刷新去重：同一时刻只允许一个刷新线程在跑。
        self._refresh_lock = threading.Lock()
        # 传输层（管线检视 #7 收尾）：默认复用 llm.providers 的进程级
        # 单例 httpx.Client（无代理概念，走空代理键），连接池复用免去
        # 每次调用的 TCP+TLS 握手税；import 方向已核实——llm 不反向
        # 依赖 character，无循环导入。测试可注入 MockTransport 客户端工厂。
        self._http_client_factory = http_client_factory or _shared_http_client

    def current_weather(self, request_id: str) -> str:
        snapshot = self._fetch_snapshot()
        if snapshot is None:
            return ""
        return snapshot.summary

    def _fetch_snapshot(self) -> _WeatherSnapshot | None:
        now = time.monotonic()
        cached = self._cache
        if cached is not None and now - cached.fetched_at <= self.cache_seconds:
            return cached
        if cached is not None:
            # 缓存过期：同步拉取（8s 超时）会卡住过期后的第一条消息。
            # 先返回旧值（可能略旧，天气是可选上下文），由后台守护线程刷新。
            self._refresh_in_background()
            return cached
        # 无旧值才同步拉一次；之后走缓存/后台刷新路径。
        return self._fetch_remote(now)

    def _refresh_in_background(self) -> None:
        if not self._refresh_lock.acquire(blocking=False):
            return  # 已有刷新在跑，不重复起线程。

        def _run() -> None:
            try:
                self._fetch_remote(time.monotonic())
            except Exception:
                logging.getLogger(__name__).debug(
                    "weather background refresh failed", exc_info=True
                )
            finally:
                self._refresh_lock.release()

        threading.Thread(target=_run, name="bot-weather-refresh", daemon=True).start()

    def _fetch_remote(self, now: float) -> _WeatherSnapshot | None:
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={self.latitude}&longitude={self.longitude}"
            "&current=temperature_2m,apparent_temperature,relative_humidity_2m,weather_code"
            "&timezone=auto&forecast_days=1"
        )
        try:
            with self._http_client_factory().stream(
                "GET", url, timeout=self.timeout_seconds
            ) as response:
                # 非 2xx 走既有失败分支（返回过期缓存），不解析错误体。
                if not 200 <= response.status_code < 300:
                    raise ValueError(f"weather HTTP status {response.status_code}")
                # 响应体限长（对齐 providers 的 8MB 口径）：读到上限即拒，
                # 超限异常落进下方既有失败分支，不静默吞成空数据。
                payload = json.loads(
                    _read_body_limited(response, _MAX_RESPONSE_BYTES).decode("utf-8")
                )
        except Exception:  # noqa: BLE001 - 网络失败时返回过期缓存（如果有），天气是可选信息，不抛错。
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
        # 未注入自定义表时保持 None 语义（内部仍保留内置表做公开字段），
        # snapshot 经 holiday_of 按年份选内置表——农历节日不跨年复用。
        self._holiday_table_is_default = holiday_table is None
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
            holiday=holiday_of(
                now, None if self._holiday_table_is_default else self.holiday_table
            ),
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


# ---------------------------------------------------------------------------
# 第 10 项（2026-09-25）：【当前时间】分区扩面 + 系统自述。
#
# 全部是**呈现层现算**的只读函数，不进 TemporalContext 契约（那是
# domains/core/contracts 的件，加字段=改契约）；调用方只有 chat.py 的分区装配。
# 历法换算唯一真身在 ``domains/divination/data/multi_calendar.py``——本件只调
# 用、零第二套（饶迥/儒略历差/伊斯兰历都不在这重算一遍）。
# ---------------------------------------------------------------------------

_UTC_OFFSET_MINUTES_FLOOR = -12 * 60
_UTC_OFFSET_MINUTES_CEIL = 14 * 60


def utc_offset_label(timezone_name: str) -> str:
    """时区名 → 「UTC±hh:mm」；时区认不出来回空串（不硬凑 +00:00）。"""
    try:
        offset = datetime.now(ZoneInfo(timezone_name)).utcoffset()
    except Exception:  # noqa: BLE001 - 坏时区名（tz 库缺失等）只丢这一小段读出
        return ""
    if offset is None:
        return ""
    minutes = int(offset.total_seconds() // 60)
    if not _UTC_OFFSET_MINUTES_FLOOR <= minutes <= _UTC_OFFSET_MINUTES_CEIL:
        return ""
    sign = "+" if minutes >= 0 else "-"
    absolute = abs(minutes)
    return f"UTC{sign}{absolute // 60:02d}:{absolute % 60:02d}"


def clock_sync_readout() -> str:
    """校时状态一行（复用 timesync 共享实例的公开属性，绝不触发联网）。

    读的是装配期 ``configure_from`` 绑定好的那把进程内共享校时器：
    ``enabled``/``offset_seconds`` 都是带锁的属性读，不碰 ``now()``（那会按
    节奏发起 SNTP）。拿不到共享实例（未绑定/模块搬家）回诚实短语，
    绝不谎称「已校时」。
    """
    try:
        from plugins.bot_unified_runtime.domains.schedule.timesync import (
            timesync as _timesync,
        )

        shared = getattr(_timesync, "_SHARED", None)
    except Exception:  # noqa: BLE001 - 校时模块不可用只是少一行读出
        return ""
    if shared is None:
        return "校时器未绑定，读的是系统钟"
    if not shared.enabled:
        return "SNTP 校时未启用，读的是系统钟"
    offset = shared.offset_seconds
    if offset is None:
        return "SNTP 校时已启用、本进程还没成功校准（暂读系统钟）"
    return f"SNTP 校时在线（当前偏移 {offset * 1000:+.0f} 毫秒）"


@functools.lru_cache(maxsize=512)
def _compact_calendar_lines_cached(year: int, month: int, day: int) -> tuple[str, ...]:
    """五历紧凑读出（每天一份，缓存）。

    **只装配、零第二套换算**：年月日全部调 ``multi_calendar`` 的原函数
    （农历/伊斯兰历/饶迥/藏历年名/儒略历同日换算），这里不重算任何天文量。
    为什么用紧凑版而不是 ``rich_calendar_lines``：那套明细（含节气位置/闰月说明/
    精度边界长句 ≈2500 字）每天每条消息都灌进 system prompt 会把既有分区
    挤出预算（共享锁 ``test_runtime_sections_use_compact_labels_in_order``
    当场红就是证据），且"历史上的今天"卡才是它的主场。被追问细节时模型
    有分区里的锚点+可让超管跑命令面全量。
    """
    from plugins.bot_unified_runtime.domains.divination.data.multi_calendar import (
        format_lunar_date,
        hijri_from_gregorian,
        julian_from_gregorian,
        julian_gregorian_offset,
        rabjung_year,
        tibetan_year_name,
    )

    year_h, month_h, day_h = hijri_from_gregorian(year, month, day)
    cycle, year_in_cycle = rabjung_year(year)
    julian_day = julian_from_gregorian(year, month, day)
    offset = julian_gregorian_offset(year, month, day)
    return (
        f"农历：{format_lunar_date(year, month, day)[len('农历'):]}；干支纪年以农历正月初一换年",
        f"伊斯兰历约{year_h}年{month_h}月{day_h}日（历表推算，与月相观测可差 ±1 天）",
        (
            f"藏历：饶迥第{cycle}轮第{year_in_cycle}年（{tibetan_year_name(year)}）；"
            # 「历法面每面只准一种措辞」锁（test_self_info_reaches_prompt）按字面
            # 计数，本行行内复读面名会被判成第二套口径；边界句留在同一行内，
            # 「月/日」承前省略主语即指本行历法，语义零损失。
            "月/日与洛萨无历表源，不推算"
        ),
        (
            f"东正教历（儒略历计）：同一天=儒略历{julian_day.year}-{julian_day.month:02d}-"
            f"{julian_day.day:02d}（今两历差{offset}天）"
        ),
    )


#: 系统钟与「所报时刻」相差多少秒以内算同一次取数（分区每轮现算，正常相差 1 分钟内；
#: 留 10 分钟余量给排队与线程池积压，超出即视为历史上下文，不许再拿今天的钟比日子）。
_MOMENTS_SAME_READING_SECONDS = 600.0


def _day_divergence_note(temporal: object, day: date, timezone_name: str) -> str:
    """四把钟跨日时点名的一行提示；同日或拿不到时刻 ⇒ 空串。

    为什么要这一行：历法面（农历/伊斯兰历/藏历/儒略历）按**东八区日界**取日，
    分区首行报的是配置时区的墙钟，而台账 #6 记着 cron/调度走系统本地钟——
    三把钟跨日时模型会把「今天」说错一天，且错得很有信心。

    口径：时刻从 ``TemporalContext`` 自己的字符串还原（``now_local`` 只到分），
    **不在这里再读一次配置时区钟**（同一瞬间的两个读数会自己跟自己打架）。
    系统钟只在「与所报时刻大致同一次取数」的窗口内参与比较：超窗说明这是
    补投/回放的历史上下文，拿今天的系统钟去断言"那天系统本地是另一天"当场就是假话
    （self_calendar 席位在 smoke 里实抓到过这一型）。
    """
    now_text = str(getattr(temporal, "now_local", "") or "").strip()
    if not timezone_name or not now_text:
        return ""
    try:
        hour, minute = (int(part) for part in now_text.split(":")[:2])
        moment = datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZoneInfo(timezone_name))
    except Exception:  # noqa: BLE001 - 时刻文本或时区名不可用：少这一行，历法面照出
        return ""
    try:
        from plugins.bot_unified_runtime.domains.ops.self_calendar.moments import (
            resolve_moments,
            system_clock_now,
        )

        system_now = system_clock_now()
        same_reading = (
            abs((system_now - moment).total_seconds()) <= _MOMENTS_SAME_READING_SECONDS
        )
        snapshot = resolve_moments(
            moment,
            timezone_name=timezone_name,
            system_now=system_now if same_reading else None,
        )
    except Exception:  # noqa: BLE001 - 跨日提示炸了不许把「现在几点」带走
        return ""
    return snapshot.day_divergence_note


def time_partition_extras(temporal: object) -> list[str]:
    """【当前时间】分区的补充行：时区+UTC 偏移+校时状态+五历紧凑读出+跨日提示。

    fail-open：任何一块算不出来就少那一块，首行时刻文本由调用方保留——
    历法面炸了不许把「现在几点」一起带走。
    """
    lines: list[str] = []
    timezone_name = str(getattr(temporal, "timezone", "") or "").strip()
    bits: list[str] = []
    if timezone_name:
        bits.append(f"时区 {timezone_name}")
        offset_label = utc_offset_label(timezone_name)
        if offset_label:
            bits.append(offset_label)
    clock = clock_sync_readout()
    if clock:
        bits.append(f"授时：{clock}")
    if bits:
        lines.append("；".join(bits) + "。")
    try:
        day = date.fromisoformat(str(getattr(temporal, "date_local", "") or ""))
        lines += list(_compact_calendar_lines_cached(day.year, day.month, day.day))
    except Exception:  # noqa: BLE001 - 历法面降级：少这几行，命令与对话都照常
        return lines
    note = _day_divergence_note(temporal, day, timezone_name)
    if note:
        lines.append(note)
    return lines


# 更新历史缓存：git log 是 subprocess（数十毫秒级），聊天每条消息都扫一遍
# 纯属浪费；10 分钟保质期在分区里以「截至」字样如实标注，不装作现读。
_GIT_TTL_SECONDS = 600.0
_GIT_LOCK = threading.Lock()
_GIT_CACHE: dict[str, Any] = {"lines": (), "monotonic": 0.0, "filled": False}


def _repo_root() -> Path | None:
    """向上找带 ``.git`` 的目录当仓库根（首版按固定 parents[4] 数层，数错一层
    就恒回 None ⇒ 更新历史整块静默缺席且测试照样绿——walk 找锚点比数层稳）。
    打包部署/子目录拷贝没有 .git 时诚实回 None，调用方省略该块。"""
    here = Path(__file__).resolve()
    for parent in here.parents[:8]:
        if (parent / ".git").exists():
            return parent
    return None


def recent_update_lines(limit: int = 6) -> list[str]:
    """更新历史 = 最近 limit 条 commit 标题（`git log` 现读，fail-open 整块省略）。

    WHY 只读标题：commit subject 是给人看的一句话，正文可能带密钥形态；
    每条再过一遍 ``redact_local_secrets`` 双保险。``encoding`` 必须显式钉
    utf-8——台账 #47 的教训：不钉 encoding 时按本仓铁律
    ``PYTHONIOENCODING=utf-8`` 直跑会 GBK 解码崩。git 不可用/超时/非零
    退出 ⇒ 回空列表，调用方**省略整块**而不是编一段"暂无更新"。
    """
    now = time.monotonic()
    with _GIT_LOCK:
        if _GIT_CACHE["filled"] and now - float(_GIT_CACHE["monotonic"]) <= _GIT_TTL_SECONDS:
            return list(_GIT_CACHE["lines"])
    lines: list[str] = []
    root = _repo_root()
    if root is not None:
        try:
            import subprocess

            proc = subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "log",
                    "--no-color",
                    "--decorate=off",
                    f"-n{max(1, int(limit))}",
                    "--pretty=format:%h %s",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3.0,
                check=False,
            )
            if proc.returncode == 0:
                from plugins.bot_unified_runtime.domains.render.plain_text import (
                    redact_local_secrets,
                )

                lines = [
                    redact_local_secrets(" ".join(raw.split()))
                    for raw in proc.stdout.splitlines()
                    if raw.strip()
                ]
        except Exception:  # noqa: BLE001 - git 不可用/超时：更新历史整块诚实缺席
            lines = []
    with _GIT_LOCK:
        _GIT_CACHE["lines"] = tuple(lines)
        _GIT_CACHE["monotonic"] = time.monotonic()
        _GIT_CACHE["filled"] = True
    return list(lines)


def clear_update_history_cache_for_tests() -> None:
    """测试专用：清空更新历史缓存。"""
    with _GIT_LOCK:
        _GIT_CACHE["lines"] = ()
        _GIT_CACHE["monotonic"] = 0.0
        _GIT_CACHE["filled"] = False


def system_readout_lines() -> list[str]:
    """系统自述（软件框架/适配器/插件版本 + 更新历史），逐行脱敏。

    版本事实源唯一：调 ``host_status._runtime_versions()``——它本身又是
    ``error_report._version_pairs`` 的收编口（诊断卡同源）。本件不 import
    error_report 拼第二套，跨包私有函数复用在这里是**有意的**：那枚函数
    就是为"喂给别的呈现面"存在的（host_status 已这么用，锁在
    tests/test_host_status.py）。git 构建行（含短哈希）就在 ``_version_pairs``
    的「构建」行里，随块带出，不再单列。
    """
    lines: list[str] = []
    try:
        from plugins.bot_unified_runtime.domains.ops.monitor import host_status

        pairs = host_status._runtime_versions()
    except Exception:  # noqa: BLE001 - 版本面拿不到就少这一段，不猜版本号
        pairs = []
    if pairs:
        from plugins.bot_unified_runtime.domains.render.plain_text import (
            redact_local_secrets,
        )

        lines += [f"{label}：{redact_local_secrets(value)}" for label, value in pairs]
    commits = recent_update_lines()
    if commits:
        lines.append(f"更新历史（最近提交，截至取样 {time.strftime('%H:%M')}）：")
        lines += [f"- {subject}" for subject in commits]
    return lines


#: 功能自述一行的字数地板：超出即按**主题边界**收口并显式报未列出的条数。
#: 地板而非天花板——声明源长到一定程度时宁可少列并说清少了多少，也不静默截断。
_CAPABILITY_INDEX_MAX_CHARS = 900


def capability_index_lines(*, is_admin: bool = True) -> list[str]:
    """功能自述（需求 10「你能做什么」）：主题名从帮助注册表的权威声明源现算。

    口径：
    - 唯一来源 = ``capability_registry.HELP_TOPIC_DECLARATIONS``（与 ``/bot help``
      的 topic 数以同一条声明源为准）。这里**只列主题名**，逐参数说明仍归
      ``/bot help <主题>`` 与 ``docs/command-catalog.md``——复制一份正文就是这个
      项目反复踩的「第二真身」账。
    - 可见性吃声明源的 ``admin_only``：非管理员既看不到管理类主题，也拿不到
      包含它们的计数（否则等于把管理面泄露成一句「我有 40 项功能」）。
    - 计数是**本次列出的条数**，不是全量常量；被地板收口时补一行「另有 N 项未列出」。
    - 失败：声明源 import 不到、或取到的形状不可用 ⇒ 整块不出。宁可不报，
      也不报一份手抄的旧清单（副本正是这个项目反复踩的第二真身账）。
    """
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.runtime.capability_registry import (
            HELP_TOPIC_DECLARATIONS,
        )

        topics = [
            str(decl.topic).strip()
            for decl in HELP_TOPIC_DECLARATIONS
            if is_admin or not decl.admin_only
        ]
    except Exception:  # noqa: BLE001 - 取数口炸了就整块缺席，不猜功能清单
        return []

    topics = [topic for topic in topics if topic]
    if not topics:
        return []

    listed: list[str] = []
    used = 0
    for topic in topics:
        projected = used + len(topic) + (1 if listed else 0)
        if projected > _CAPABILITY_INDEX_MAX_CHARS:
            break
        listed.append(topic)
        used = projected
    omitted = len(topics) - len(listed)
    header = f"我能做的事（本会话可见 {len(listed)} 项，按帮助注册表现算）："
    lines = [header + "、".join(listed)]
    if omitted:
        lines.append(f"另有 {omitted} 项未在此列出（全表说「/bot commands」）。")
    lines.append(
        "上面只有主题名：看全表说「/bot commands」，看某项的具体用法说「/bot help <主题>」，"
        "别凭主题名编命令。"
    )
    return lines

