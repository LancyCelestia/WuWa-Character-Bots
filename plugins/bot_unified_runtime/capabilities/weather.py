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
    SendPolicy,
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

# 审计 E2-7：触发收窄。任何「天气」开头的自然句（如日常感慨「天气真好」）
# 此前都会路由并外呼两次再回错误提示。查询词需像地名：长度受限、不以常见
# 口语感叹词开头、不以语气助词/标点收尾。注意词表避开真实城市前缀：
# 太原/太仓（太）、那曲（那）、哈尔滨（哈）等不能被词首过滤误杀。
_WEATHER_QUERY_MAX_LEN = 20
_WEATHER_COLLOQUIAL_RE = re.compile(
    r"^(?:真是|真的|真好|太好|好热|好冷|好差|好闷|好棒|挺|超|这么|那么|"
    r"今天|昨天|明天|后天|最近|感觉|要是|如果|因为|所以|但是|可是|还是|"
    r"不错|不好|简直|可算|终于|怎么样|怎样|如何|啥|什么|为什么|"
    r"咦|哇|哇塞|唉|哎|哎呀|哦|嗯)"
)
_WEATHER_TAIL_PARTICLE_RE = re.compile(r"[的了了吗呢吧呀啊嘛哦哟唻啦~～！？?！。，,、…\s]$")
_WEATHER_UNROUTABLE_QUERIES = frozenset(
    {"真好", "不错", "怎么样", "怎样", "咋样", "如何", "预报", "热", "冷", "热死了", "冷死了"}
)


def _plausible_weather_query(query: str) -> bool:
    """查询词预校验：过滤纯口语感叹，放行真实城市形态。"""
    text = str(query or "").strip()
    if not text or len(text) > _WEATHER_QUERY_MAX_LEN:
        return False
    if text in _WEATHER_UNROUTABLE_QUERIES:
        return False
    if _WEATHER_COLLOQUIAL_RE.match(text):
        return False
    return not _WEATHER_TAIL_PARTICLE_RE.search(text)


def is_weather_command(text: str) -> bool:
    match = _WEATHER_RE.match(text.strip())
    if match is None:
        return False
    return _plausible_weather_query(match.group("query"))


def is_district_command(text: str) -> bool:
    return _DISTRICT_RE.match(text.strip()) is not None


def build_weather_capability(
    config: Any | None = None, *, render_backend: Any | None = None
) -> Any:
    proxy = str(getattr(config, "bot_download_proxy", "") or "") if config else ""

    def _render_weather_card(query: str, report: str, source: str) -> str:
        """天气报告合成 Mica 卡图；后端不可用或失败返回空串。"""
        if render_backend is None or not getattr(render_backend, "available", False):
            return ""
        try:
            from plugins.bot_unified_runtime.capabilities.content_parser import (
                render_card_png,
            )
            from plugins.bot_unified_runtime.contracts import build_parsed_content

            item = build_parsed_content(
                platform="weather",
                item_id=query,
                item_kind="weather",
                title=f"{query} · 天气",
                author_name={"nmc": "中国气象局 NMC", "open-meteo": "Open-Meteo"}.get(
                    source, "气象预报"
                ),
                summary=report[:1200],
                parse_depth="deep",
            )
            payload = render_card_png(
                render_backend,
                item,
                config=config,
                card_dir=str(getattr(config, "bot_card_render_dir", "data/cards") or "data/cards"),
            )
        except Exception:  # noqa: BLE001 - 渲染失败回退纯文本报告。
            return ""
        return str(payload.get("file") or "") if isinstance(payload, dict) else ""

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
        if not match or not _plausible_weather_query(match.group("query")):
            # 路由误捕（plain_text 可能被引用/上下文拼接污染，或纯口语感叹）：
            # 不回复用法说明骚扰用户，静默跳过。明确想查天气的用户会说
            # 「天气 <城市>」。
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.weather",
                kind="text",
                body="",
                audit_tags=["weather", "missing_query_silent"],
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
                session_scope = str(
                    getattr(getattr(message, "session_type", None), "value", "private")
                )
                if session_scope != "private":
                    # 审计 E2-7：群聊查不到城市时静默（审计后不回复），不再向
                    # 全群刷「没有查到」错误提示；私聊保留明确报错。
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.weather",
                        kind="text",
                        body="",
                        send_policy=SendPolicy.SILENT_AUDIT,
                        audit_tags=["weather", "weather_not_found_silent"],
                    )
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
        card = _render_weather_card(query, report, source)
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.weather",
            kind="mixed" if card else "text",
            title="天气",
            body=report,
            images=[{"file": card}] if card else [],
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=[
                "weather",
                f"weather_source:{source}",
                f"weather_query:{query[:20]}",
                "card_rendered" if card else "text_only",
            ],
        )

    return capability
