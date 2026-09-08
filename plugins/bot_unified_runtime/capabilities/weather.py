"""中文天气查询能力（bot.weather）：`天气 <城市>` / `查天气 <城市>`。

数据源：中国气象局 NMC（免 key，内置 2527 个区县码表），
支持 `天气 北京`、`天气 河北-大城`；另支持 `支持区县 <省>` 列区县。
"""

from __future__ import annotations

import re
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
)
from plugins.bot_unified_runtime.sources.nmc_weather import (
    list_districts,
    nmc_weather_query,
)
from plugins.bot_unified_runtime.sources.open_meteo import (
    format_open_meteo,
    open_meteo_query,
)

_WEATHER_RE = re.compile(r"^[/!！]?(?:天气|查天气|天氣|查天氣|weather)\s*(?P<query>.+)$")
_DISTRICT_RE = re.compile(r"^[/!！]?(?:支持区县|查询区县|可查区县)\s*(?P<province>.+)$")


def is_weather_command(text: str) -> bool:
    return _WEATHER_RE.match(text.strip()) is not None


def is_district_command(text: str) -> bool:
    return _DISTRICT_RE.match(text.strip()) is not None


def build_weather_capability(config: Any | None = None) -> Any:
    proxy = str(getattr(config, "bot_download_proxy", "") or "") if config else ""

    def capability(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        text = message.plain_text.strip()
        district_match = _DISTRICT_RE.match(text)
        if district_match:
            province = district_match.group("province").strip()
            result = list_districts(province)
            if not result["districts"]:
                return CapabilityResult(
                    request_id=message.request_id,
                    capability_id="bot.weather",
                    kind="text",
                    body=f"未找到省份『{province}』或该省下无区县数据。",
                    audit_tags=["weather", "districts_not_found"],
                )
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.weather",
                kind="text",
                title="可查区县",
                body=f"📌 {result['province']} 全部区县（{len(result['districts'])} 个）：\n"
                + "、".join(result["districts"]),
                risk_level=RiskLevel.LOW,
                privacy_level=PrivacyLevel.PUBLIC,
                audit_tags=["weather", f"weather_districts:{len(result['districts'])}"],
            )
        match = _WEATHER_RE.match(text)
        if not match:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.weather",
                kind="text",
                body="用法：天气 <城市>，例如『天气 北京』；同省同名可用『天气 河北-大城』。",
                audit_tags=["weather", "missing_query"],
            )
        query = match.group("query").strip()
        report = nmc_weather_query(query, proxy=proxy)
        source = "nmc"
        if report is None:
            # 海外城市/中国乡镇街道级：NMC 城市库查不到时用 Open-Meteo 全球兜底
            # （点位级精度，覆盖乡镇/村庄/社区与全部海外地区，免 key）。
            try:
                global_result = open_meteo_query(query, proxy=proxy)
            except Exception:  # noqa: BLE001 - 全球源失败按未找到降级。
                global_result = None
            if global_result is None:
                return CapabilityResult(
                    request_id=message.request_id,
                    capability_id="bot.weather",
                    kind="text",
                    body=f"没有查到『{query}』的天气（城市名没找到或接口失败），"
                    "试试『天气 省份-城市』；海外城市直接输入城市名即可。",
                    audit_tags=["weather", "weather_not_found"],
                )
            report = format_open_meteo(global_result)
            source = "open-meteo"
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.weather",
            kind="text",
            title="天气",
            body=report,
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=["weather", f"weather_source:{source}", f"weather_query:{query[:20]}"],
        )

    return capability
