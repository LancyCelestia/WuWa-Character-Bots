"""个股行情能力（bot.stocks，Task 4 全局审计 + C 方向增量 2026-09-13）。

触发面：公司别名 / 「股价|股票价格|市值」及繁体「股價|個股」/ 英文
stock|stocks（词边界，大小写不敏感）；「行情」裸词仍归全球股指能力
（bot.market），两者互不抢路由。未点名公司时输出九家科技巨头面板卡。

数据来自 ``sources.stock_data``：现价 / OHLCV / KDJ / 市值各自独立拉取、
独立降级（source/as_of/status/delayed 四件套见契约）。**非上市公司
（OpenAI/Anthropic/字节跳动等，见 NON_PUBLIC_EQUITIES 注册表）分支不触
任何行情外呼**，只给有来源的公开估值/财报口径说明。

渲染接线：卡片 payload 用 bridge.render_finance_card_html 的
sections/rows 契约；趋势折线走 ``finance_chart.line_chart_svg``（多日收盘）；
**箱形图**（多日收盘分布 / 多股日收益分布）走 ``finance_chart.box_plot_svg``
——单日 OHLC 在数据层 build_boxplot_from_ohlcv 的 min-5 样本门被拒绝，
绝不把单日 K 线画成箱形图。渲染失败一律回退纯文本。
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
)
from plugins.bot_unified_runtime.contracts.finance import (
    EquityQuote,
    FinanceDataStatus,
    KDJSnapshot,
    MarketCap,
    OHLCVSeries,
)
from plugins.bot_unified_runtime.sources.stock_data import (
    NON_PUBLIC_EQUITIES,
    compute_kdj,
    fetch_market_cap,
    fetch_stock_ohlcv,
    fetch_stock_quote,
    format_stock_brief,
    resolve_company_query,
)

_URL_HINT_RE = re.compile(r"https?://", re.IGNORECASE)
_MAX_TRIGGER_LEN = 32

# 「股价」是股票语境的兜底词；公司别名由 resolve_company_query 处理。
# 繁体（股價/個股）与英文（stock/stocks 词边界）为 2026-09-13 多语言覆盖。
# 评审 P1-1（2026-09-13）：STOCKS 是先于 chat 的确定性命令，「我想吃苹果」
# 「谷歌地图」这类纯别名聊天不得劫持——别名命中必须有股票语境词相伴；
# 非上市公司（openai/anthropic）同样需语境共现（T1.7 防劫持②，2026-09-12）。
_STOCK_HINT_RE = re.compile(
    r"(股价|股票价格|股價|個股|股票"
    # 全拼/缩写（T-Spec T1.5/T1.6）：全拼同覆盖繁体同音（股價/個股）；
    # 缩写仅 gj 查重无冲突（gp=怪癖/sz=四柱·设置/gg=聊天俚语 均让，
    # 见 fix-py1-report.md 放弃清单）。无 IGNORECASE → [A-Za-z0-9] 边界。
    r"|(?<![A-Za-z0-9])(?:gupiaojiage|gupiao|gujia|gegu|gj)(?![A-Za-z0-9]))"
)
_STOCK_CONTEXT_RE = re.compile(r"(股|市值|行情|价格|涨|跌)")
_ENGLISH_STOCK_RE = re.compile(r"\bstocks?\b", re.IGNORECASE)
_ENGLISH_CONTEXT_RE = re.compile(r"\b(price|market|quote|tech|us)\b", re.IGNORECASE)
_NON_PUBLIC_KEYS = frozenset(k.lower() for k in NON_PUBLIC_EQUITIES)
# T-Spec T1.7 防劫持（2026-09-12 探针②）：问答/求建议句式一律让路 chat/
# moegirl——用户要的是回答或建议，不是行情面板；先于 hint/豁免/ticker 全部
# 路径否决（「股票被套了怎么办」「openai是什么」类）。
_CHAT_QUESTION_RE = re.compile(
    r"(是什么|是什么意思|咋用|怎么用|哪家强|哪家好|怎么办|咋办"
    r"|被套|套牢|割肉|解套)"
)
# 防劫持②：非上市公司豁免词（openai/anthropic…）不再是裸子串即触发，
# 必须与股价语境词共现（估值/上市/财报/融资保住「openai 估值」类真命令）。
_NON_PUBLIC_CONTEXT_RE = re.compile(
    r"(股价|股價|股票|行情|市值|k线|k線|涨|跌|漲"
    r"|估值|上市|ipo|财报|財報|融资|融資|值多少钱)",
    re.IGNORECASE,
)

_EMPTY_PANEL_TEXT = "美股行情暂时拉不到，晚点再试试？"


def is_stocks_command(text: str) -> bool:
    """个股触发判定：短文本、无链接、显式股票词，或公司别名+股票语境。

    语境约束（评审 P1-1）：纯公司别名出现在日常聊天（「我想吃苹果」
    「谷歌地图好用吗」）不触发；非上市公司别名（openai 估值类查询）需股价
    语境词共现（T1.7 防劫持②，2026-09-12）；问答/求建议句式一律让路。
    """
    stripped = (text or "").strip()
    if not stripped or len(stripped) > _MAX_TRIGGER_LEN:
        return False
    if _URL_HINT_RE.search(stripped):
        return False
    lowered = stripped.lower()
    # T-Spec T1.2：裸英文短命令 stock/stocks 精确命中 → 九巨头面板；
    # 精确等值天然防子串（stockholm 等不触发），长句仍走下方语境判定。
    if lowered in {"stock", "stocks"}:
        return True
    # T-Spec T1.7 防劫持②：问答/求建议句式（X是什么/咋用/哪家强/被套了
    # 怎么办）先于一切触发路径否决，落 chat/moegirl_question。
    if _CHAT_QUESTION_RE.search(stripped):
        return False
    if _STOCK_HINT_RE.search(stripped):
        return True
    non_public_hit = any(key in lowered for key in _NON_PUBLIC_KEYS)
    if non_public_hit and _NON_PUBLIC_CONTEXT_RE.search(lowered):
        return True
    if _ENGLISH_STOCK_RE.search(stripped) and _ENGLISH_CONTEXT_RE.search(stripped):
        return True
    ticker = resolve_company_query(stripped)
    return ticker is not None and bool(_STOCK_CONTEXT_RE.search(stripped))


def _safe_kdj(bars: Any) -> KDJSnapshot | None:
    """KDJ 计算的兜底壳：任何异常都不阻塞能力（返回 None 走暂缺文案）。"""
    try:
        return compute_kdj(bars) if bars else None
    except Exception:  # noqa: BLE001 - 指标失败不影响主行情展示。
        return None


def _trend_svg(closes: tuple[float, ...]) -> str:
    """多日收盘 → 走势折线 SVG（finance_chart 纯计算）；失败空串回退。"""
    try:
        from plugins.bot_unified_runtime.sources.finance_chart import line_chart_svg

        return line_chart_svg(closes).svg
    except Exception:  # noqa: BLE001 - 折线失败静默回退文案。
        return ""


def _box_section(closes_by_label: list[tuple[str, tuple[float, ...]]]) -> dict[str, Any] | None:
    """箱形图区块（分布语义）：每列 ≥4 个有效数值才成箱，不足跳过。

    输入必须是多日序列（收盘分布 / 日收益分布），单日 OHLC 不合法——
    该语义门由数据层 build_boxplot_from_ohlcv 与 finance_chart 共同锁定。
    """
    from plugins.bot_unified_runtime.sources.finance_chart import box_plot_svg

    series = [closes for _label, closes in closes_by_label if len(closes) >= 4]
    if not series:
        return None
    labels = [
        label for label, closes in closes_by_label if len(closes) >= 4
    ]
    chart = box_plot_svg(series, labels=labels)
    if chart.status != "ok" or not chart.svg:
        return None
    span_text = " ~ ".join(
        f"{min(closes):.1f}-{max(closes):.1f}"
        for _label, closes in closes_by_label
        if len(closes) >= 4
    )
    return {
        "name": "分布（箱形图：多日序列，非单日 K 线）",
        "rows": [
            {
                "label": " / ".join(labels),
                "value": span_text,
                "cls": "flat",
                "sub": chart.note or "min/Q1/中位/Q3/max 与 1.5×IQR 须线",
                "trend_svg": chart.svg,
            }
        ],
    }


def build_stocks_card_payload(
    quote: EquityQuote,
    series: OHLCVSeries | None,
    kdj: KDJSnapshot | None,
    cap: MarketCap | None,
) -> dict[str, Any]:
    """组装 finance_card（render_finance_card_html）payload。

    图表语义：trend_svg 只放多日收盘折线（趋势）；箱形图区块放多日收盘
    分布（≥5 根才成箱）；缺数据行/块直接省略，不伪造 0。
    """
    ref_display = quote.name or quote.ticker
    main_rows: list[dict[str, Any]] = []
    if quote.price is not None:
        pct_text = (
            f"{quote.change_pct:+.2f}%" if quote.change_pct is not None else ""
        )
        cls = (
            "down"
            if (quote.change_pct or 0.0) < 0
            else ("up" if (quote.change_pct or 0.0) > 0 else "flat")
        )
        sub_parts: list[str] = []
        if series is not None and series.bars:
            last = series.bars[-1]
            sub_parts.append(
                f"最新 {last.trade_date.isoformat()}：开 {last.open:.2f} / "
                f"高 {last.high:.2f} / 低 {last.low:.2f}"
            )
        main_rows.append(
            {
                "label": f"{ref_display}（{quote.ticker}）",
                "value": f"{quote.price:.2f}",
                "delta": pct_text,
                "cls": cls,
                "sub": " · ".join(sub_parts),
                "trend_svg": _trend_svg(series.closes) if series is not None else "",
                "trend_note": "" if series is not None and series.bars else "暂无历史走势数据",
            }
        )
    else:
        main_rows.append(
            {
                "label": f"{ref_display}（{quote.ticker}）",
                "value": "暂无",
                "delta": "",
                "cls": "flat",
                "sub": quote.note or "上游失败，先不瞎猜数字",
                "trend_svg": "",
                "trend_note": "暂无历史走势数据",
            }
        )
    indicator_rows: list[dict[str, Any]] = []
    if kdj is not None:
        indicator_rows.append(
            {
                "label": f"KDJ({kdj.period})",
                "value": f"{kdj.k:.2f} / {kdj.d:.2f} / {kdj.j:.2f}",
                "cls": "flat",
            }
        )
    if cap is not None and cap.value is not None:
        value_yi = cap.value / 1e8
        cap_text = (
            f"≈ {value_yi / 10_000:.2f} 万亿美元"
            if value_yi >= 10_000
            else f"≈ {value_yi:,.0f} 亿美元"
        )
        indicator_rows.append({"label": "总市值", "value": cap_text, "cls": "flat"})
    sections: list[dict[str, Any]] = [{"name": "个股行情", "rows": main_rows}]
    if indicator_rows:
        sections.append({"name": "指标与市值", "rows": indicator_rows})
    if series is not None and len(series.closes) >= 5:
        box = _box_section([(quote.ticker, series.closes)])
        if box is not None:
            sections.append(box)
    stamp = (
        quote.as_of.strftime("%Y-%m-%d %H:%M UTC")
        if quote.as_of is not None
        else "时间未知"
    )
    return {
        "title": f"{quote.ticker} 行情速览",
        "subtitle": f"状态 {quote.status.value} · {stamp}",
        "badge": "延迟行情" if quote.delayed else "实时",
        "sections": sections,
        "source_note": f"数据源：{quote.source or 'eastmoney'}",
        "delayed_note": "免费行情源为延迟口径",
        "feature_label": "个股行情",
    }


def build_stocks_capability(config: Any | None = None, *, render_backend: Any | None = None) -> Any:
    """构建个股能力闭包；文本全离线可测（fetch 函数可整体 monkeypatch）。

    render_backend 就绪时出釉瑚金融卡（render_finance_card_html 契约），
    失败/缺后端一律回退纯文本——与 market 能力的渲染模式同构。
    """

    def _render_card(
        payload: dict[str, Any], quotes: EquityQuote, card_dir: str
    ) -> str:
        if render_backend is None or not getattr(render_backend, "available", False):
            return ""
        try:
            from plugins.bot_unified_runtime.output.card_render.bridge import (
                render_finance_card_html,
            )
            from plugins.bot_unified_runtime.runtime.cache_policy import prune_prefixed

            payload = dict(payload)
            payload["bot_name"] = str(
                getattr(config, "bot_persona_display_name", "") or ""
            ).strip() or "守岸人"
            payload["bot_avatar_url"] = str(
                getattr(config, "bot_persona_avatar_url", "") or ""
            )
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
            digest = hashlib.sha1(
                f"stocks|{quotes.ticker}|{quotes.price}".encode()
            ).hexdigest()[:12]
            target = Path(card_dir or "data/cards")
            target.mkdir(parents=True, exist_ok=True)
            path = target / f"stocks_{digest}.png"
            path.write_bytes(png)
            try:
                prune_prefixed(target, "stocks", keep=120)
            except Exception:  # noqa: S110, BLE001 - 配额清理失败不影响出图。
                pass
            return str(path)
        except Exception:  # noqa: BLE001 - 渲染失败回退纯文本。
            return ""

    def _render_panel_card(payload: dict[str, Any], card_dir: str) -> str:
        """九家面板卡 PNG（digest 与个股卡区分）；失败回退空串。"""
        if render_backend is None or not getattr(render_backend, "available", False):
            return ""
        try:
            from plugins.bot_unified_runtime.output.card_render.bridge import (
                render_finance_card_html,
            )
            from plugins.bot_unified_runtime.runtime.cache_policy import prune_prefixed

            payload = dict(payload)
            payload["bot_name"] = str(
                getattr(config, "bot_persona_display_name", "") or ""
            ).strip() or "守岸人"
            payload["bot_avatar_url"] = str(
                getattr(config, "bot_persona_avatar_url", "") or ""
            )
            png = render_backend.render_card(
                {
                    "html": render_finance_card_html(payload),
                    "viewport": {"width": 1160, "height": 1600},
                    "device_scale_factor": 2,
                    "wait_ms": 0,
                }
            )
            if not isinstance(png, bytes) or not png:
                return ""
            rows = payload.get("sections", [{}])[0].get("rows", []) if payload.get("sections") else []
            digest = hashlib.sha1(
                ("stocks-panel|" + "|".join(str(row.get("value", "")) for row in rows))
                .encode()
            ).hexdigest()[:12]
            target = Path(card_dir or "data/cards")
            target.mkdir(parents=True, exist_ok=True)
            path = target / f"stocks_panel_{digest}.png"
            path.write_bytes(png)
            try:
                prune_prefixed(target, "stocks", keep=120)
            except Exception:  # noqa: S110, BLE001 - 配额清理失败不影响出图。
                pass
            return str(path)
        except Exception:  # noqa: BLE001 - 渲染失败回退纯文本。
            return ""

    def _panel_capability(
        message: IncomingMessage, card_dir: str
    ) -> CapabilityResult:
        """未点名公司（「美股股价」/「stocks」）→ 九家科技巨头面板卡。

        行情批量一调、日 K 并行拉取；卡上每股一行（趋势折线）+ 多股日收益
        分布箱形图；纯文字回退为面板 brief。失败降级与个股路径同构。
        """
        import time as _time
        from concurrent.futures import ThreadPoolExecutor

        from plugins.bot_unified_runtime.sources.stock_data import (
            fetch_stock_history,
            fetch_stock_quotes,
            format_stocks_brief,
            resolve_stock_symbols,
        )

        quotes = fetch_stock_quotes()
        if not quotes:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.stocks",
                kind="text",
                body=_EMPTY_PANEL_TEXT,
                audit_tags=["capability:stocks", "stocks:fetch_failed"],
            )
        wanted = resolve_stock_symbols(message.plain_text)
        shown = (
            [quote for quote in quotes if quote.symbol in wanted]
            if wanted
            else quotes
        )
        if not shown:
            shown = quotes

        histories: dict[str, tuple[float, ...]] = {}

        def _history(symbol: str):
            # fetch_stock_history 带 10 分钟 TTL（评审 P2-2：九家面板是
            # 高频命令，不能用无缓存的 provenance 链每次各打 9 个外呼）。
            points = fetch_stock_history(symbol, days=30)
            return symbol, tuple(point.close for point in points)

        with ThreadPoolExecutor(max_workers=6) as pool:
            for symbol, closes in pool.map(
                _history, [quote.symbol for quote in shown]
            ):
                histories[symbol] = closes

        rows: list[dict[str, Any]] = []
        returns_by_symbol: list[tuple[str, tuple[float, ...]]] = []
        for quote in shown:
            closes = histories.get(quote.symbol) or ()
            if len(closes) >= 5:
                from plugins.bot_unified_runtime.sources.finance_chart import (
                    daily_returns,
                )

                returns = daily_returns(closes)
                if len(returns) >= 4:
                    returns_by_symbol.append((quote.symbol, returns))
            rows.append(
                {
                    "label": f"{quote.display_name} {quote.symbol}",
                    "value": f"{quote.close:.2f}" if quote.close else "暂无",
                    "delta": (
                        f"+{quote.change_percent:.2f}%"
                        if (quote.change_percent or 0.0) > 0
                        else f"{quote.change_percent or 0.0:.2f}%"
                    ),
                    "cls": (
                        "up"
                        if (quote.change_percent or 0.0) > 0
                        else (
                            "down"
                            if (quote.change_percent or 0.0) < 0
                            else "flat"
                        )
                    ),
                    "sub": f"{quote.market} · {quote.currency}",
                    "trend_svg": _trend_svg(closes),
                    "trend_note": "" if closes else "暂无历史走势数据",
                }
            )
        sections: list[dict[str, Any]] = [
            {"name": "科技巨头面板（美股）", "rows": rows}
        ]
        if returns_by_symbol:
            box = _box_section(returns_by_symbol)
            if box is not None:
                sections.append(box)
        payload = {
            "title": "科技巨头股价",
            "subtitle": "红涨绿跌 · 折线为近 30 个交易日收盘 · 箱形图为日收益分布",
            "sections": sections,
            "source_note": "数据源：东方财富（美股）",
            "updated_at": _time.strftime("%Y-%m-%d %H:%M:%S"),
            "delayed_note": "美股行情可能有延迟",
            "feature_label": "股价",
        }
        card = _render_panel_card(payload, card_dir)
        body = format_stocks_brief(shown)
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.stocks",
            kind="mixed" if card else "text",
            title="科技巨头股价",
            body=body,
            images=[{"file": card}] if card else [],
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=[
                "capability:stocks",
                f"stocks_panel:{len(shown)}",
                "card_rendered" if card else "text_only",
            ],
        )

    def capability(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        text = message.plain_text
        if is_stocks_command(text) and resolve_company_query(text) is None:
            # 未点名公司 → 九家面板（含箱形图），不再只回提示语。
            return _panel_capability(
                message,
                str(getattr(config, "bot_card_render_dir", "data/cards") or "data/cards"),
            )
        ticker = resolve_company_query(text)
        if ticker is None:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.stocks",
                kind="text",
                body=(
                    "想看哪家公司？目前支持：英伟达（NVDA）、AMD、英特尔（INTC）、"
                    "苹果（AAPL）、微软（MSFT）、谷歌（GOOGL）、亚马逊（AMZN）、"
                    "Meta（META）、台积电（TSM）；OpenAI/Anthropic/字节跳动未上市，"
                    "可以问它们的估值。或发「美股股价」看九家面板。"
                ),
                audit_tags=["capability:stocks", "stocks:no_ticker"],
            )
        if ticker in NON_PUBLIC_EQUITIES:
            # 非上市公司红线：不触行情外呼，只给有来源的估值/财报口径说明。
            body = format_stock_brief(
                EquityQuote(
                    ticker=ticker,
                    name=NON_PUBLIC_EQUITIES[ticker].name,
                    status=FinanceDataStatus.NON_PUBLIC,
                    source="",
                    as_of=None,
                    delayed=True,
                    note="非上市公司无股价",
                ),
                None,
                None,
                None,
            )
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.stocks",
                kind="text",
                body=body,
                risk_level=RiskLevel.LOW,
                privacy_level=PrivacyLevel.PUBLIC,
                audit_tags=[
                    "capability:stocks",
                    "stocks:non_public",
                    f"stocks:non_public:{ticker}",
                ],
            )
        quote: EquityQuote = fetch_stock_quote(ticker)
        series: OHLCVSeries | None = None
        cap: MarketCap | None = None
        kdj: KDJSnapshot | None = None
        try:
            series = fetch_stock_ohlcv(ticker)
            cap = fetch_market_cap(ticker)
            kdj = _safe_kdj(series.bars)
        except Exception:  # noqa: S110, BLE001 - 附属数据失败不拖垮现价展示。
            pass
        body = format_stock_brief(quote, series, kdj, cap)
        if quote.price is None and quote.status is not FinanceDataStatus.NON_PUBLIC:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.stocks",
                kind="text",
                body=body,
                audit_tags=[
                    "capability:stocks",
                    "stocks:fetch_failed",
                    f"stocks:status:{quote.status.value}",
                ],
            )
        card = ""
        if quote.price is not None:
            payload = build_stocks_card_payload(quote, series, kdj, cap)
            card = _render_card(
                payload,
                quote,
                str(
                    getattr(config, "bot_card_render_dir", "data/cards") or "data/cards"
                ),
            )
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.stocks",
            kind="mixed" if card else "text",
            title=f"{ticker} 行情速览",
            body=body,
            images=[{"file": card}] if card else [],
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=[
                "capability:stocks",
                f"stocks:ticker:{ticker}",
                f"stocks:status:{quote.status.value}",
                "card_rendered" if card else "text_only",
            ],
        )

    return capability
