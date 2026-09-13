"""全球股指行情能力（bot.market）：`行情`/`大盘`/`股指`/`全球股市` 触发。

数据来自 ``sources.market_data``（东方财富 push2 免费接口，免 key，60s 进程内
缓存，失败降级）。文本里出现 美股/港股/A股/日经/纳斯达克 等明确市场词时只
展示对应指数，未命中任何指数的过滤词回退全部。

触发面刻意收窄：文本长度受限、不带链接（带链接是链接解析的活）、命中
房价/基金/币圈等非股市"行情"词时让路，避免抢路由。
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
from plugins.bot_unified_runtime.output.bot_avatar import bot_avatar_uri
from plugins.bot_unified_runtime.sources.market_data import (
    IndexQuote,
    fetch_index_quotes,
    fetch_index_trend,
    format_market_brief,
    group_quotes,
)

# 触发词：全球股市 > 股指/大盘/股市/行情（行情放最后避免误伤面过大时漏判）。
# 「大盤」为繁体变体（2026-09-13 多语言触发覆盖）；语境守卫 _STOCK_HINT_RE
# 同步收录（评审 P1-2，繁体非股市守卫才不失效）。
# 英文 market/markets/stock market（词边界，T-Spec T1.2）同表触发；
# 「stock market」与 stocks 让路对由 base_router 优先级裁定（market 41 先于 42）。
_MARKET_TRIGGER_RE = re.compile(
    r"(全球股市|股指|大盘|大盤|股市|行情"
    # 全拼/缩写（T-Spec T1.5/T1.6）：全拼同覆盖繁体同音（大盤/股價类）；
    # 缩写 hq/dp/gs 查重无跨能力冲突（gz 与 affinity「规则」冲突故不上）。
    # 本正则无 IGNORECASE，按 RF 波先例用 [A-Za-z0-9] 全字母数字区间边界。
    r"|(?<![A-Za-z0-9])(?:quanqiugushi|guzhi|dapan|gushi|hangqing|hq|dp|gs)(?![A-Za-z0-9])"
    r"|(?<![a-z0-9])(?:stock\s+)?markets?(?![a-z0-9]))"
)
# 非股市的"行情"（房价/基金/币圈/显卡/期货/油价/金价等商品价格）：命中且无
# 股/大盘/股指/指数词时不触发（触发劫持③修复：油价/金价行情让路 chat，
# tests/test_market_exclusion_guard.py 回归锁）。
# 繁体变体（房價/顯卡/期貨/匯率/油價/金價…）与 大盤 语境词为多语言覆盖（评审 P1-2）。
# 英文 labor/job/housing market（就业/楼市语境）为 T1.2 英文 market 触发的配套守卫。
_NON_STOCK_RE = re.compile(
    r"(房价|基金|币圈|加密|显卡|期货|汇率"
    r"|油价|金价|银价|铜价|煤价|电价|菜价|石油|黄金"
    r"|房價|幣圈|顯卡|期貨|匯率|油價|金價|銀價|銅價|石油|黃金"
    r"|labor market|labour market|job market|housing market)"
)
_STOCK_HINT_RE = re.compile(r"(股|大盘|大盤|指数)")

_URL_HINT_RE = re.compile(r"https?://", re.IGNORECASE)
_MAX_TRIGGER_LEN = 32

_EMPTY_DEGRADED_TEXT = "行情数据暂时拉不到，晚点再试试？"

# 明确市场词 → 指数 secid（多个词命中取并集；空 = 全部指数）。
_MARKET_FILTERS: tuple[tuple[str, frozenset[str]], ...] = (
    ("A股", frozenset({"1.000001", "0.399001", "0.399006"})),
    ("B股", frozenset({"1.000003", "0.399003"})),
    ("上证B", frozenset({"1.000003"})),
    ("深证B", frozenset({"0.399003"})),
    ("美股", frozenset({"100.DJIA", "100.SPX", "100.NDX"})),
    ("港股", frozenset({"100.HSI"})),
    ("恒生", frozenset({"100.HSI"})),
    ("日经", frozenset({"100.N225"})),
    ("纳斯达克", frozenset({"100.NDX"})),
    ("纳指", frozenset({"100.NDX"})),
    ("道琼斯", frozenset({"100.DJIA"})),
    ("道指", frozenset({"100.DJIA"})),
    ("标普", frozenset({"100.SPX"})),
    ("韩", frozenset({"100.KS11"})),
    ("新加坡", frozenset({"100.STI"})),
    ("印度", frozenset({"100.SENSEX"})),
    ("台湾", frozenset({"100.TWII"})),
    ("台股", frozenset({"100.TWII"})),
    ("英国", frozenset({"100.FTSE"})),
    ("富时", frozenset({"100.FTSE"})),
    ("法国", frozenset({"100.FCHI"})),
    ("德国", frozenset({"100.GDAXI"})),
    ("莫斯科", frozenset({"100.IMOEX"})),
    ("俄罗斯", frozenset({"100.IMOEX"})),
)


def market_filter_secids(text: str) -> frozenset[str]:
    """提取文本中的明确市场词，返回目标指数 secid 集合；空 = 不过滤。"""
    matched: set[str] = set()
    for keyword, secids in _MARKET_FILTERS:
        if keyword in text:
            matched.update(secids)
    return frozenset(matched)


def _format_change_abs(change_abs: float | None) -> str:
    """涨跌额带符号文本（卡上名称/点位旁展示）；缺数据返回空串不伪造。"""
    if change_abs is None:
        return ""
    if change_abs > 0:
        return f"+{change_abs:.2f}"
    return f"{change_abs:.2f}"


def is_market_command(text: str) -> bool:
    """行情触发判定：短文本、无链接、命中触发词且不撞非股市语境。"""
    stripped = (text or "").strip()
    if not stripped or len(stripped) > _MAX_TRIGGER_LEN:
        return False
    if _URL_HINT_RE.search(stripped):
        return False
    if not _MARKET_TRIGGER_RE.search(stripped):
        return False
    # 非股市语境（房价/基金/币圈…）且无股/大盘/指数词 → 让路。
    return not (
        _NON_STOCK_RE.search(stripped) and not _STOCK_HINT_RE.search(stripped)
    )


# ==================== 金融 Phase-1 扩容（2026-09-13）：商品/国债/北向 ==========
# 三条新能力闭包与 is_*_command 纯谓词。接线（base_router/echo）归主会话；
# 本文件只提供可独立离线测试的构件。数据源：
# - 商品：sources.commodities_data（东财外盘主力连续，LME 无源用 COMEX 铜）；
# - 国债：sources.bond_data（东财 datacenter RPTA_WEB_TREASURYYIELD，1Y 无源
#   诚实不接，利差=上游直供 10Y−2Y）；
# - 北向：sources.market_data.fetch_northbound_flows（2024-08 起无净买入口径，
#   只报成交总额等仍在披露字段）。
# 三者共用既有渲染契约（render_finance_card_html sections/rows），模板零改动。

# 评审 A13-I1：IGNORECASE 让 Gold/Crude Oil 等大写形态命中（golden 仍被边界
# 拒）；A13-M1：黄金/原油后置 (?!基金) 语境排除，基金类查询不误触商品卡。
_COMMODITY_TRIGGER_RE = re.compile(
    r"(黄金(?!基金)|金价|原油(?!基金)|油价|白银|银价|铜价|大宗商品"
    r"|黃金|金價|白銀|銀價|油價|銅價"
    r"|(?<![a-z0-9])(?:gold|silver|(?:crude\s+)?oil|commodit(?:y|ies))(?![a-z0-9])"
    # 全拼路由（T-Spec T1.5 对齐，2026-09-14 A34 终审遗留③）：与英文分支同款
    # 双侧 [a-z0-9] 词边界（IGNORECASE 下大写邻字同被拦，golden/xhuangjin 类
    # 近形胶合拒）；huangjin/yuanyou 与中文 黄金/原油 同款 (?!基金) 后置排除。
    # 弃用（逐词评估，宁缺勿滥）：hj/by/yj 缩写（帮助面未注册且滑稽/毕业/
    # 意见类聊天高频缩写撞车）；yinyuan（姻缘 高频同音，且 原油=yuanyou 非
    # yinyuan）；youtong（幼童 同音，无对应触发词）；tongjia/yinjia（帮助面
    # A39 未注册拼音，路由会造成反向失配）。
    r"|(?<![a-z0-9])(?:huangjin(?![a-z0-9])(?!基金)"
    r"|jinjia|baiyin|youjia|yuanyou)(?![a-z0-9]))",
    re.IGNORECASE,
)
_BOND_TRIGGER_RE = re.compile(
    r"(国债收益率|国债|债券收益率|期限利差|收益率曲线|中美国债|國債|債券收益率"
    # 全拼路由（T-Spec T1.5 对齐）：guozhai 双侧全字母数字边界（本正则无
    # IGNORECASE，沿用 market 拼音分支 [A-Za-z0-9] 先例，hguozhai/guozhai123
    # 类胶合拒）。弃用：xianqicha（echo A39 侧残缺拼形——期限利差应为
    # xianqilicha，本席禁改 echo，路由残缺形属误导，待 echo 侧勘误后对齐）；
    # shouyilv（收益率全拼过长弃）；gz（与 affinity「规则」冲突，既有裁定）。
    r"|(?<![A-Za-z0-9])guozhai(?![A-Za-z0-9]))"
)
_NORTHBOUND_TRIGGER_RE = re.compile(
    r"(北向资金|北上资金|北向|沪股通|深股通|北向資金|北上資金|滬股通|深股通"
    # 全拼路由（T-Spec T1.5 对齐）：与 A39 帮助面注册逐词对齐（beixiang/
    # hugutong/shengutong 三词均已注册），双侧全字母数字边界。
    # 弃用：dagutong（无对应触发词，简报原文疑为笔误）；beishangzijin
    # （帮助面未注册，裸拼场景罕见）。
    r"|(?<![A-Za-z0-9])(?:beixiang|hugutong|shengutong)(?![A-Za-z0-9]))"
)


def is_commodity_command(text: str) -> bool:
    """商品触发判定（黄金/原油/白银/铜价等）：短文本、无链接、命中触发词。"""
    stripped = (text or "").strip()
    if not stripped or len(stripped) > _MAX_TRIGGER_LEN:
        return False
    if _URL_HINT_RE.search(stripped):
        return False
    return bool(_COMMODITY_TRIGGER_RE.search(stripped))


def is_bond_command(text: str) -> bool:
    """国债收益率触发判定：短文本、无链接、命中触发词。"""
    stripped = (text or "").strip()
    if not stripped or len(stripped) > _MAX_TRIGGER_LEN:
        return False
    if _URL_HINT_RE.search(stripped):
        return False
    return bool(_BOND_TRIGGER_RE.search(stripped))


def is_northbound_command(text: str) -> bool:
    """北向资金触发判定：短文本、无链接、命中触发词。"""
    stripped = (text or "").strip()
    if not stripped or len(stripped) > _MAX_TRIGGER_LEN:
        return False
    if _URL_HINT_RE.search(stripped):
        return False
    return bool(_NORTHBOUND_TRIGGER_RE.search(stripped))


def _card_common_payload(config: Any | None, feature_label: str) -> dict[str, Any]:
    """三张新卡共用的页脚字段（与 market/stocks 能力同源口径）。"""
    import time as _time

    return {
        "updated_at": _time.strftime("%Y-%m-%d %H:%M:%S"),
        "bot_name": (
            str(getattr(config, "bot_persona_display_name", "") or "").strip()
            or "守岸人"
        ),
        "bot_avatar_url": str(bot_avatar_uri(config)),
        "feature_label": feature_label,
    }


def _render_finance_sections_card(
    render_backend: Any | None,
    payload: dict[str, Any],
    card_dir: str,
    prefix: str,
) -> str:
    """sections/rows 契约 → 釉瑚金融卡 PNG；后端缺失/失败返回空串回退文本。"""
    if render_backend is None or not getattr(render_backend, "available", False):
        return ""
    try:
        import hashlib
        from pathlib import Path

        from plugins.bot_unified_runtime.output.card_render.bridge import (
            render_finance_card_html,
        )
        from plugins.bot_unified_runtime.runtime.cache_policy import prune_prefixed

        png = render_backend.render_card(
            {
                "html": render_finance_card_html(payload),
                "viewport": {"width": 1160, "height": 1400},
                "device_scale_factor": 2,
                "wait_ms": 0,
            }
        )
        if not isinstance(png, bytes) or not png:
            return ""
        rows = [
            row
            for section in payload.get("sections", [])
            if isinstance(section, dict)
            for row in section.get("rows", [])
            if isinstance(row, dict)
        ]
        digest = hashlib.sha1(
            (prefix + "|" + "|".join(str(row.get("value", "")) for row in rows))
            .encode()
        ).hexdigest()[:12]
        target = Path(card_dir or "data/cards")
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"{prefix}_{digest}.png"
        path.write_bytes(png)
        try:
            prune_prefixed(target, prefix, keep=120)
        except Exception:  # noqa: S110, BLE001 - 配额清理失败不影响出图。
            pass
        return str(path)
    except Exception:  # noqa: BLE001 - 渲染失败回退纯文本。
        return ""


def _trend_svg_safe(closes: tuple[float, ...]) -> str:
    """多日收盘 → 折线 SVG；失败空串回退（与 stocks 能力同款兜底）。"""
    if not closes or len(closes) < 2:
        return ""
    try:
        from plugins.bot_unified_runtime.sources.finance_chart import line_chart_svg

        return line_chart_svg(closes).svg
    except Exception:  # noqa: BLE001 - 折线失败静默回退文案。
        return ""


def build_commodities_capability(
    config: Any | None = None, *, render_backend: Any | None = None
) -> Any:
    """商品行情能力闭包（bot.commodities）：黄金/白银/铜/原油现价+30日走势。"""
    from plugins.bot_unified_runtime.sources.commodities_data import (
        LME_NOTE,
        fetch_commodity_quotes,
        fetch_commodity_trend,
        format_commodities_brief,
        format_price,
        group_commodity_quotes,
    )

    def capability(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        timeout = float(getattr(config, "bot_market_timeout_seconds", 6.0) or 6.0)
        quotes = fetch_commodity_quotes(
            timeout_seconds=timeout,
            cache_seconds=float(
                getattr(config, "bot_market_cache_seconds", 60.0) or 60.0
            ),
        )
        if not quotes:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.commodities",
                kind="text",
                body="大宗商品行情暂时拉不到，晚点再试试？",
                audit_tags=["capability:commodities", "commodities:fetch_failed"],
            )
        # 走势折线（10min TTL 在数据侧）；并行拉取，失败静默缺席。
        from concurrent.futures import ThreadPoolExecutor

        trends: dict[str, tuple[float, ...]] = {}
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                quote.code: pool.submit(
                    fetch_commodity_trend, quote.code, timeout_seconds=timeout
                )
                for quote in quotes
            }
            for code, future in futures.items():
                try:
                    trends[code] = future.result(timeout=timeout + 2.0)
                except Exception:  # noqa: BLE001 - 单商品折线失败静默缺席。
                    trends[code] = ()
        sections: list[dict[str, Any]] = []
        for group_name, rows in group_commodity_quotes(quotes).items():
            sections.append(
                {
                    "name": group_name,
                    "rows": [
                        {
                            "label": quote.name,
                            "value": format_price(quote.price),
                            "delta": (
                                f"+{quote.change_pct:.2f}%"
                                if quote.change_pct > 0
                                else f"{quote.change_pct:.2f}%"
                            ),
                            "cls": (
                                "up"
                                if quote.change_pct > 0
                                else ("down" if quote.change_pct < 0 else "flat")
                            ),
                            "sub": quote.unit,
                            "trend_svg": _trend_svg_safe(trends.get(quote.code) or ()),
                            "trend_note": (
                                "" if trends.get(quote.code) else "暂无历史走势数据"
                            ),
                        }
                        for quote in rows
                    ],
                }
            )
        payload = {
            "title": "大宗商品速览",
            "subtitle": "红涨绿跌 · 折线为近 30 个交易日收盘",
            "badge": "延迟行情",
            "sections": sections,
            "source_note": "数据源：东方财富（外盘主力连续）",
            "delayed_note": LME_NOTE,
            **_card_common_payload(config, "商品行情"),
        }
        card = _render_finance_sections_card(
            render_backend,
            payload,
            str(getattr(config, "bot_card_render_dir", "data/cards") or "data/cards"),
            "commodities",
        )
        body = format_commodities_brief(quotes)
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.commodities",
            kind="mixed" if card else "text",
            title="大宗商品速览",
            body=body,
            images=[{"file": card}] if card else [],
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=[
                "capability:commodities",
                f"commodities_quotes:{len(quotes)}",
                "card_rendered" if card else "text_only",
            ],
        )

    return capability


def build_bond_capability(
    config: Any | None = None, *, render_backend: Any | None = None
) -> Any:
    """国债收益率能力闭包（bot.bond）：中美国债 2/5/10/30 年 + 10Y−2Y 利差。"""
    from plugins.bot_unified_runtime.sources.bond_data import (
        fetch_bond_yields,
        format_bond_brief,
    )

    def _yield_rows(points: Any, spread: float | None, spread_label: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for point in points:
            rows.append(
                {
                    "label": point.label,
                    "value": "暂无" if point.value is None else f"{point.value:.3f}%",
                    "delta": "",
                    "cls": "flat",
                    "sub": "",
                    "trend_svg": "",
                }
            )
        rows.append(
            {
                "label": spread_label,
                "value": "暂无" if spread is None else f"{spread:+.3f}%",
                "delta": "",
                "cls": "flat",
                "sub": "",
                "trend_svg": "",
            }
        )
        return rows

    def capability(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        timeout = float(getattr(config, "bot_market_timeout_seconds", 6.0) or 6.0)
        snapshot = fetch_bond_yields(timeout_seconds=timeout)
        if snapshot.status != "ok":
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.bond",
                kind="text",
                body=format_bond_brief(snapshot),
                audit_tags=["capability:bonds", "bonds:fetch_failed"],
            )
        sections = [
            {
                "name": "中国国债（收益率 · 收盘口径）",
                "rows": _yield_rows(snapshot.cn, snapshot.cn_spread_10y2y, "10Y−2Y 期限利差"),
            },
            {
                "name": "美国国债（收益率 · 收盘口径）",
                "rows": _yield_rows(snapshot.us, snapshot.us_spread_10y2y, "10Y−2Y 期限利差"),
            },
        ]
        payload = {
            "title": "中美国债收益率速览",
            "subtitle": (
                f"交易日 {snapshot.as_of_date}" if snapshot.as_of_date else "交易日未知"
            ),
            "badge": "延迟数据",
            "sections": sections,
            "source_note": "数据源：东方财富数据中心",
            "delayed_note": "1 年期暂无稳定免费源，不展示；利差为 10Y−2Y 口径",
            **_card_common_payload(config, "国债收益率"),
        }
        card = _render_finance_sections_card(
            render_backend,
            payload,
            str(getattr(config, "bot_card_render_dir", "data/cards") or "data/cards"),
            "bonds",
        )
        body = format_bond_brief(snapshot)
        audit = [
            "capability:bonds",
            "bonds:ok" if not snapshot.missing else "bonds:degraded",
            "card_rendered" if card else "text_only",
        ]
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.bond",
            kind="mixed" if card else "text",
            title="中美国债收益率速览",
            body=body,
            images=[{"file": card}] if card else [],
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=audit,
        )

    return capability


def build_northbound_capability(
    config: Any | None = None, *, render_backend: Any | None = None
) -> Any:
    """北向资金能力闭包（bot.northbound）：沪深股通当日成交总额（无净买入口径）。"""
    from plugins.bot_unified_runtime.sources.market_data import (
        fetch_northbound_flows,
        format_northbound_brief,
    )

    def capability(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        timeout = float(getattr(config, "bot_market_timeout_seconds", 6.0) or 6.0)
        flows = fetch_northbound_flows(timeout_seconds=timeout)
        if not flows:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.northbound",
                kind="text",
                body="北向资金数据暂时拉不到，晚点再试试？",
                audit_tags=["capability:northbound", "northbound:fetch_failed"],
            )
        main_rows: list[dict[str, Any]] = []
        context_rows: list[dict[str, Any]] = []
        for flow in flows:
            main_rows.append(
                {
                    "label": flow.name,
                    "value": (
                        f"{flow.deal_amt_yi:,.2f} 亿元"
                        if flow.deal_amt_yi is not None
                        else "暂无"
                    ),
                    "delta": "",
                    "cls": "flat",
                    "sub": (
                        f"当日成交总额 · {flow.deal_num:,} 笔"
                        if flow.deal_num is not None
                        else "当日成交总额"
                    ),
                    "trend_svg": "",
                }
            )
            if flow.index_close is not None:
                pct = (
                    f"{flow.index_change_pct:+.2f}%"
                    if flow.index_change_pct is not None
                    else ""
                )
                cls = (
                    "up"
                    if (flow.index_change_pct or 0.0) > 0
                    else ("down" if (flow.index_change_pct or 0.0) < 0 else "flat")
                )
                context_rows.append(
                    {
                        "label": f"{flow.name}参考 · {flow.index_name}",
                        "value": f"{flow.index_close:.2f}",
                        "delta": pct,
                        "cls": cls,
                        "sub": "",
                        "trend_svg": "",
                    }
                )
            if flow.lead_stock:
                pct = (
                    f"{flow.lead_stock_pct:+.2f}%"
                    if flow.lead_stock_pct is not None
                    else ""
                )
                cls = (
                    "up"
                    if (flow.lead_stock_pct or 0.0) > 0
                    else ("down" if (flow.lead_stock_pct or 0.0) < 0 else "flat")
                )
                context_rows.append(
                    {
                        "label": f"{flow.name}领涨股",
                        "value": flow.lead_stock,
                        "delta": pct,
                        "cls": cls,
                        "sub": "",
                        "trend_svg": "",
                    }
                )
        sections: list[dict[str, Any]] = [
            {"name": "沪深股通（当日成交）", "rows": main_rows}
        ]
        if context_rows:
            sections.append({"name": "参考", "rows": context_rows})
        trade_dates = sorted({flow.trade_date for flow in flows})
        payload = {
            "title": "北向资金速览",
            "subtitle": (
                f"交易日 {trade_dates[-1]}" if trade_dates else "交易日未知"
            ),
            "badge": "收盘披露",
            "sections": sections,
            "source_note": "数据源：东方财富数据中心",
            "delayed_note": "2024-08 起不再披露北向当日净买入，本卡不含净买入口径",
            **_card_common_payload(config, "北向资金"),
        }
        card = _render_finance_sections_card(
            render_backend,
            payload,
            str(getattr(config, "bot_card_render_dir", "data/cards") or "data/cards"),
            "northbound",
        )
        body = format_northbound_brief(flows)
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.northbound",
            kind="mixed" if card else "text",
            title="北向资金速览",
            body=body,
            images=[{"file": card}] if card else [],
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=[
                "capability:northbound",
                f"northbound_channels:{len(flows)}",
                "card_rendered" if card else "text_only",
            ],
        )

    return capability


def build_market_capability(
    config: Any | None = None, *, render_backend: Any | None = None
) -> Any:
    """构建行情能力闭包；超时/缓存时长可由配置覆盖。"""
    import hashlib
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path

    def _fetch_trends(quotes: list[IndexQuote], timeout: float) -> dict[str, tuple[float, ...]]:
        """并行拉取各指数 30 日收盘（10min 缓存在 market_data 侧）；失败空序列。"""
        trends: dict[str, tuple[float, ...]] = {}
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {
                quote.code: pool.submit(
                    fetch_index_trend, quote.code, timeout_seconds=timeout
                )
                for quote in quotes
            }
            for code, future in futures.items():
                try:
                    trends[code] = future.result(timeout=timeout + 2.0)
                except Exception:  # noqa: BLE001 - 单指数折线失败静默缺席。
                    trends[code] = ()
        return trends

    def _render_card(
        quotes: list[IndexQuote],
        trends: dict[str, tuple[float, ...]],
        card_dir: str,
        subtitle: str,
        crosscheck_note: str = "",
    ) -> str:
        """釉瑚股指卡 PNG（分组网格+折线）；后端缺失/失败返回空串回退文本。"""
        if render_backend is None or not getattr(render_backend, "available", False):
            return ""
        import time as _time

        try:
            from plugins.bot_unified_runtime.output.card_render.bridge import (
                render_market_card_html,
            )

            payload = {
                "subtitle": subtitle,
                "groups": [
                    {
                        "name": group_name,
                        "rows": [
                            {
                                "name": quote.name,
                                "price": f"{quote.price:.2f}",
                                "pct": (
                                    f"+{quote.change_pct:.2f}%"
                                    if quote.change_pct > 0
                                    else f"{quote.change_pct:.2f}%"
                                ),
                                "change_pct": quote.change_pct,
                                "change": (
                                    _format_change_abs(quote.change_abs)
                                ),
                                # Task 4 增量：行级 provenance（机器可读，
                                # 与上方 *_note 展示文案互补；bridge 未知键忽略）。
                                "source": quote.source,
                                "status": quote.status,
                                "delayed": quote.delayed,
                                "trend": list(trends.get(quote.code) or ()),
                                # MOEX 无历史 K 线源（东财 100.IMOEX 不存在）：
                                # 卡上明确标注缺口，不伪造折线（2026-09-12 裁定）。
                                "trend_note": (
                                    "暂无历史走势数据"
                                    if quote.code == "100.IMOEX"
                                    and not trends.get(quote.code)
                                    else ""
                                ),
                            }
                            for quote in group_rows
                        ],
                    }
                    for group_name, group_rows in group_quotes(quotes).items()
                ],
                "source_note": "数据源：东方财富 · MOEX ISS（俄罗斯）",
                "updated_at": _time.strftime("%Y-%m-%d %H:%M:%S"),
                "delayed_note": "部分海外指数行情可能有延迟",
                # 多源交叉查验声明（腾讯 qt.gtimg.cn；通道不可用为空串=不声明）。
                "crosscheck_note": crosscheck_note,
                # Task 4 增量：机器可读状态与数据时点（unix 秒，取各行最新；
                # bridge 未知键忽略，finance_card 接线时直接可用）。
                "status": "ok",
                "as_of": max((quote.as_of or 0.0) for quote in quotes) if quotes else None,
                "bot_name": str(
                    getattr(config, "bot_persona_display_name", "") or ""
                ).strip()
                or "守岸人",
                "bot_avatar_url": str(
                    bot_avatar_uri(config)
                ),
                "feature_label": "全球股指",
            }
            png = render_backend.render_card(
                {
                    "html": render_market_card_html(payload),
                    "viewport": {"width": 1160, "height": 1400},
                    "device_scale_factor": 2,
                    "wait_ms": 0,
                }
            )
            if not isinstance(png, bytes) or not png:
                return ""
            digest = hashlib.sha1(
                ("market|" + "|".join(f"{q.code}:{q.price}" for q in quotes)).encode()
            ).hexdigest()[:12]
            target = Path(card_dir or "data/cards")
            target.mkdir(parents=True, exist_ok=True)
            path = target / f"market_{digest}.png"
            path.write_bytes(png)
            try:
                from plugins.bot_unified_runtime.runtime.cache_policy import (
                    prune_prefixed,
                )

                prune_prefixed(target, "market", keep=120)
            except Exception:  # noqa: S110, BLE001 - 配额清理失败不影响本次出图。
                pass
            return str(path)
        except Exception:  # noqa: BLE001 - 渲染失败回退纯文本。
            return ""

    def capability(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        timeout = float(getattr(config, "bot_market_timeout_seconds", 6.0) or 6.0)
        quotes: list[IndexQuote] = fetch_index_quotes(
            timeout_seconds=timeout,
            cache_seconds=float(
                getattr(config, "bot_market_cache_seconds", 60.0) or 60.0
            ),
        )
        if not quotes:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.market",
                kind="text",
                body=_EMPTY_DEGRADED_TEXT,
                audit_tags=["capability:market", "market:fetch_failed"],
            )
        wanted = market_filter_secids(message.plain_text)
        shown = [quote for quote in quotes if not wanted or quote.code in wanted]
        if not shown:
            # 过滤词没命中任何指数（如「A股大盘行情」里的生僻组合）→ 回退全部。
            shown = quotes
        subtitle = "红涨绿跌 · 折线为近 30 个交易日收盘"
        trends = _fetch_trends(shown, timeout)
        # 多源交叉查验（腾讯）：best-effort，通道不可用为空串=不声明。
        from plugins.bot_unified_runtime.sources.market_crosscheck import (
            crosscheck_quotes,
            format_crosscheck_note,
        )

        cross_note = format_crosscheck_note(
            crosscheck_quotes(shown, timeout_seconds=min(timeout, 4.0))
        )
        card = _render_card(
            shown,
            trends,
            str(getattr(config, "bot_card_render_dir", "data/cards") or "data/cards"),
            subtitle,
            cross_note,
        )
        body = format_market_brief(shown)
        if cross_note:
            body = f"{body}\n{cross_note}"
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.market",
            kind="mixed" if card else "text",
            title="全球股指速览",
            body=body,
            images=[{"file": card}] if card else [],
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=[
                "capability:market",
                f"market_quotes:{len(shown)}",
                "market:crosscheck" if cross_note else "market:crosscheck_unavailable",
                "card_rendered" if card else "text_only",
            ],
        )

    return capability
