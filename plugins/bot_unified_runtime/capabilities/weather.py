"""中文天气查询能力（bot.weather）：`天气 <城市>` / `查天气 <城市>`。

数据源：中国气象局 NMC（免 key，内置 2527 个区县码表），
支持 `天气 北京`、`天气 河北-大城`；另支持 `支持区县 <省>` 列区县。
"""

from __future__ import annotations

import re
import time
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
    find_city_code,
    list_districts,
    nmc_weather_query,
    search_city_code,
)
from plugins.bot_unified_runtime.sources.open_meteo import (
    format_open_meteo,
    open_meteo_query,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import (
    ParseHttpError,
    http_get_json,
)

_WEATHER_RE = re.compile(r"^[/!！]?(?:天气|查天气|天氣|查天氣|weather)\s*(?P<query>.+)$")
_DISTRICT_RE = re.compile(r"^[/!！]?(?:支持区县|查询区县|可查区县)\s*(?P<province>.+)$")

# ---------------------------------------------------------------- 主通道重试
# NMC rest/weather 主接口本身存活（2026-09-12 复测：curl 与项目链路 10/10
# 站点 200 全量数据，无 cookie 墙；`data:""` 是无/无效 stationid 的固定响应）。
# 真实缺陷是单次尝试：实测约 1/8 概率瞬时超时/空 data，一旦命中即静默降级
# Open-Meteo、预警支路随之跳过。故对「码表命中」的查询加一次快速重试；
# 码表未命中（海外/乡镇）不重试不外呼，保持 Open-Meteo 快速兜底路径。
_NMC_RETRY_ATTEMPTS = 2
_NMC_RETRY_BACKOFF_SECONDS = 0.5


def _nmc_query_with_retry(query: str, *, proxy: str) -> str | None:
    """NMC 主通道：城市在码表内但拉取失败（超时/空 data）时重试一次。

    码表未命中直接返回 None（调用方走 Open-Meteo 全球兜底，不空耗延迟）。
    """
    parts = [part.strip() for part in str(query or "").split("-") if part.strip()]
    in_db = bool(
        (len(parts) >= 2 and find_city_code(parts[0], parts[1])) or search_city_code(query)
    )
    if not in_db:
        return None
    report: str | None = None
    for attempt in range(_NMC_RETRY_ATTEMPTS):
        report = nmc_weather_query(query, proxy=proxy)
        if report is not None:
            return report
        if attempt + 1 < _NMC_RETRY_ATTEMPTS:
            time.sleep(_NMC_RETRY_BACKOFF_SECONDS)
    return report


# ---------------------------------------------------------------- 预警支路
# NMC 全国预警在报清单（免 key；2026-09-12 curl 实测 200，单页 pageSize=300
# 即可取全量当日预警）。条目：alertid/issuetime/title/url/pic，颜色与类型
# 均含在 title（如「…气象台发布大雾橙色预警信号」）。
_NMC_FIND_ALARM_URL = "https://www.nmc.cn/rest/findAlarm?pageNo=1&pageSize=300"
_ALARM_COLOR_RANK = {"蓝色": 1, "黄色": 2, "橙色": 3, "红色": 4}
_ALARM_MAX_SHOWN = 5

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


def parse_alert_title(title: str) -> tuple[str, str]:
    """从预警标题提取 (类型, 颜色)；缺失回退空串。

    例：「辽宁省锦州市黑山县气象台发布大雾橙色预警信号」→ ("大雾", "橙色")。
    """
    text = str(title or "").strip()
    color = ""
    for name in _ALARM_COLOR_RANK:
        if name in text:
            color = name
            break
    kind = ""
    if "发布" in text:
        segment = text.split("发布", 1)[1]
        for suffix in ("预警信号", "预警"):
            if suffix in segment:
                # 「发布大雾橙色预警信号」：先把颜色词剔出类型段。
                kind = segment.split(suffix, 1)[0]
                for name in _ALARM_COLOR_RANK:
                    kind = kind.replace(name, "")
                kind = kind.strip("（）() 　")
                break
    return kind, color


def fetch_city_alerts(
    query: str, *, proxy: str = "", timeout: float = 8.0
) -> list[dict[str, str]]:
    """NMC 预警支路：按查询词过滤全国在报预警。

    查询词按「省-市」拆 token，要求全部 token 命中 title（如「河北-大城」
    需同时含「河北」「大城」，避免「大城」误中他省同名）；接口不可达、
    响应异常或无命中一律返回 []（调用方静默），绝不抛出。
    """
    tokens = [part.strip() for part in str(query or "").split("-") if part.strip()]
    if not tokens:
        return []
    try:
        payload = http_get_json(
            _NMC_FIND_ALARM_URL, proxy=proxy, timeout=timeout, verify_ssl=False
        )
    except (ParseHttpError, ValueError, OSError):
        return []
    entries = ((((payload or {}).get("data") or {}).get("page") or {}).get("list")) or []
    hits: list[dict[str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or "").strip()
        if not title or not all(token in title for token in tokens):
            continue
        kind, color = parse_alert_title(title)
        url = str(entry.get("url") or "").strip()
        hits.append(
            {
                "title": title,
                "kind": kind,
                "color": color,
                "issued": str(entry.get("issuetime") or "").strip(),
                "url": f"https://www.nmc.cn{url}" if url.startswith("/") else url,
            }
        )
    # 高等级（红>橙>黄>蓝）排前；同级保持 NMC 原序（新发布在前）。
    hits.sort(key=lambda item: _ALARM_COLOR_RANK.get(item["color"], 0), reverse=True)
    return hits


def format_city_alerts(alerts: list[dict[str, str]]) -> str:
    """预警条目 → 附在天气报告后的文本段；空列表返回空串。"""
    if not alerts:
        return ""
    shown = alerts[:_ALARM_MAX_SHOWN]
    lines = [f"⚠️ 气象预警（NMC 当前在报 {len(alerts)} 条）"]
    for item in shown:
        kind_part = f"{item['kind']}预警" if item["kind"] else "预警"
        label = f"{item['color']}{kind_part}" if item["color"] else kind_part
        lines.append(f"• {label}｜发布 {item['issued'] or '时间未知'}")
        lines.append(f"  {item['title']}")
    if len(alerts) > len(shown):
        lines.append(f"（其余 {len(alerts) - len(shown)} 条略）")
    return "\n".join(lines)


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
        report = _nmc_query_with_retry(query, proxy=proxy)
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
        # 预警支路：仅 NMC 城市命中时附带（Open-Meteo 海外/乡镇无预警语义）。
        # 接口不可达/无预警时 fetch_city_alerts 返回空，静默不加段。
        alerts: list[dict[str, str]] = []
        if source == "nmc":
            try:
                alerts = fetch_city_alerts(query, proxy=proxy)
            except Exception:  # noqa: BLE001 - 预警支路失败不影响天气主报告。
                alerts = []
            if alerts:
                report = f"{report}\n\n{format_city_alerts(alerts)}"
        card = _render_weather_card(query, report, source)
        audit_tags = [
            "weather",
            f"weather_source:{source}",
            f"weather_query:{query[:20]}",
            "card_rendered" if card else "text_only",
        ]
        if alerts:
            audit_tags.append(f"weather_alerts:{len(alerts)}")
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.weather",
            kind="mixed" if card else "text",
            title="天气",
            body=report,
            images=[{"file": card}] if card else [],
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=audit_tags,
        )

    return capability
