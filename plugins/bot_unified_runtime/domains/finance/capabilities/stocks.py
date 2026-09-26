"""个股行情能力（bot.stocks，Task 4 全局审计 + C 方向增量 2026-09-13）。

触发面：公司别名 / 「股价|股票价格|市值」及繁体「股價|個股」/ 英文
stock|stocks（词边界，大小写不敏感）；「行情」裸词仍归全球股指能力
（bot.market），两者互不抢路由。未点名公司时输出九家科技巨头面板卡。

数据来自 ``domains.finance.data.stock_data``：现价 / OHLCV / KDJ / 市值各自独立拉取、
独立降级（source/as_of/status/delayed 四件套见契约）。**非上市公司
（OpenAI/Anthropic/字节跳动等，见 NON_PUBLIC_EQUITIES 注册表）分支不触
任何行情外呼**，只给有来源的公开估值/财报口径说明。

渲染接线：卡片 payload 用 bridge.render_finance_card_html 的
sections/rows 契约；趋势折线走 ``domains.finance.data.finance_chart.line_chart_svg``（多日收盘）；
**箱形图**（多日收盘分布 / 多股日收益分布）走 ``domains.finance.data.finance_chart.box_plot_svg``
——单日 OHLC 在数据层 build_boxplot_from_ohlcv 的 min-5 样本门被拒绝，
绝不把单日 K 线画成箱形图。渲染失败一律回退纯文本。
"""

from __future__ import annotations

import hashlib
import random
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
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import user_copy
from plugins.bot_unified_runtime.domains.core.contracts.finance import (
    EquityQuote,
    FinanceDataStatus,
    KDJSnapshot,
    MarketCap,
    OHLCVSeries,
)
from plugins.bot_unified_runtime.domains.finance.data.stock_data import (
    NON_PUBLIC_EQUITIES,
    compute_kdj,
    fetch_market_cap,
    fetch_stock_ohlcv,
    fetch_stock_quote,
    format_stock_brief,
    resolve_company_query,
)
from plugins.bot_unified_runtime.domains.render.bot_avatar import bot_avatar_uri

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

# 审查 Q-01：数据源失败文案统一入 user_copy 池（守岸人语气轮换），不再硬编码。
def _empty_panel_text() -> str:
    return random.choice(user_copy.DATASOURCE_FAILURE_TEMPLATES).format(reason="美股行情暂时拉不到")


# ==================== logo 本地缓存（金融 Phase-1，2026-09-13） ====================
# clearbit logo（https://logo.clearbit.com/<domain>）按域名落盘缓存：文件名
# =sha256(域名小写)（任务口径），路径 data/stock_logos/（经 runtime_paths 解析
# 到 Runtime 数据根）。命中缓存不再下载；下载失败/非 PNG 返回 ""。
# F2（2026-09-14 素材本地化）：payload 组装侧（build_stocks_card_payload）
# 只落本地 file URI，全败诚实省略 logo 字段，不再把远程 URL 塞给渲染期
# Chromium；``_apply_cached_logo`` 保留为外部/历史 payload 的兼容兜底。
# 缓存目录缺自身清理——logo 域名集固定（9 家注册表），增长有界。
# 2026-09-13 实测：logo.clearbit.com 本机不可达（URLError），Google s2 favicon
# （PNG，sz=128）可达 → 作为第二源（同样过 PNG magic 校验），两源都失败才放弃。
_LOGO_CACHE_DIR_REL = "data/stock_logos"
_LOGO_MAX_BYTES = 2 * 1024 * 1024  # clearbit/s2 PNG 实测量级远小于此，防御上限
_LOGO_SOURCES: tuple[str, ...] = (
    "https://logo.clearbit.com/{domain}",
    "https://www.google.com/s2/favicons?domain={domain}&sz=128",
)


def _logo_cache_dir() -> Path:
    """缓存目录：data/stock_logos 经 runtime_paths 重映射到 Runtime 数据根。"""
    from scripts.runtime_paths import runtime_path

    return Path(runtime_path(_LOGO_CACHE_DIR_REL))


def _download_logo_bytes(domain: str, timeout: float) -> bytes:
    """按源序下载 logo 字节；非 PNG 或全部失败抛 ParseHttpError/ValueError。"""
    from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
        ParseHttpError,
        http_get,
    )

    last_error: Exception | None = None
    for template in _LOGO_SOURCES:
        try:
            _final, payload = http_get(
                template.format(domain=domain),
                timeout=max(1.0, float(timeout)),
                max_bytes=_LOGO_MAX_BYTES,
            )
        except ParseHttpError as exc:
            last_error = exc
            continue
        if payload.startswith(b"\x89PNG"):
            return payload
        last_error = ParseHttpError("logo source returned non-PNG payload")
    raise last_error if last_error is not None else ParseHttpError("no logo source")


def local_logo_uri(domain: str, *, timeout: float = 6.0, download: bool = True) -> str:
    """域名 → 本地缓存 logo 的 file URI；未命中且允许时下载落盘。

    源序：本地缓存（零网络）→ clearbit → Google s2，下载成功即入缓存
    （下次零网络）。任何失败返回空串（绝不抛）——logo 只影响观感，不能
    影响行情主链路；payload 组装侧全败则诚实省略 logo 字段（F2 起），
    ``download=False`` 只查缓存不出网（离线路径）。
    """
    clean = (domain or "").strip().lower()
    if not clean or "/" in clean or "." not in clean:
        return ""
    try:
        cache_dir = _logo_cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(clean.encode("utf-8")).hexdigest()
        target = cache_dir / f"{digest}.png"
        if target.exists() and target.stat().st_size > 0:
            return target.as_uri()
        if not download:
            return ""
        payload = _download_logo_bytes(clean, timeout)
        target.write_bytes(payload)
        return target.as_uri()
    except Exception:  # noqa: BLE001 - 下载失败静默，回退远程 URL。
        return ""


def _apply_cached_logo(payload: dict[str, Any]) -> None:
    """渲染前把 clearbit 远程 URL 换成本地缓存 URI（失败保持远程，原兜底）。"""
    url = str(payload.get("logo_url") or "")
    if not url.startswith("https://logo.clearbit.com/"):
        return
    domain = url.rsplit("/", 1)[-1]
    local = local_logo_uri(domain)
    if local:
        payload["logo_url"] = local


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
        from plugins.bot_unified_runtime.domains.finance.data.finance_chart import (
            line_chart_svg,
        )

        return line_chart_svg(closes).svg
    except Exception:  # noqa: BLE001 - 折线失败静默回退文案。
        return ""


def _box_section(closes_by_label: list[tuple[str, tuple[float, ...]]]) -> dict[str, Any] | None:
    """箱形图区块（分布语义）：每列 ≥4 个有效数值才成箱，不足跳过。

    输入必须是多日序列（收盘分布 / 日收益分布），单日 OHLC 不合法——
    该语义门由数据层 build_boxplot_from_ohlcv 与 finance_chart 共同锁定。
    """
    from plugins.bot_unified_runtime.domains.finance.data.finance_chart import (
        box_plot_svg,
    )

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
    ref: Any | None = None,
) -> dict[str, Any]:
    """组装 finance_card（render_finance_card_html）payload。

    图表语义：trend_svg 只放多日收盘折线（趋势）；箱形图区块放多日收盘
    分布（≥5 根才成箱）；缺数据行/块直接省略，不伪造 0。
    vis3（2026-09-13 指标完善）：标题官方中文名、accent 跟公司 logo 代表色、
    成交量/成交额/流通股/总股本入指标区；「状态 OK」debug 字样出卡。
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
    # vis3 指标完善：成交量（今日）/成交额/流通股/总股本——缺数据诚实省略。
    if quote.volume is not None:
        vol_text = (
            f"{quote.volume / 1e8:.2f} 亿股"
            if quote.volume >= 1e8
            else f"{quote.volume / 1e4:,.0f} 万股"
        )
        avg5 = (
            sum(b.volume or 0 for b in series.bars[-5:]) / 5
            if series is not None and len(series.bars) >= 5
            and all(b.volume is not None for b in series.bars[-5:])
            else None
        )
        if avg5:
            vol_text += (
                f"（近5日均 {avg5 / 1e8:.2f} 亿股）"
                if avg5 >= 1e8
                else f"（近5日均 {avg5 / 1e4:,.0f} 万股）"
            )
        indicator_rows.append({"label": "成交量", "value": vol_text, "cls": "flat"})
    if quote.amount is not None:
        amt_text = (
            f"≈ {quote.amount / 1e8:,.2f} 亿美元"
            if quote.amount >= 1e8
            else f"{quote.amount:,.0f} 美元"
        )
        indicator_rows.append({"label": "成交额", "value": amt_text, "cls": "flat"})
    if quote.float_shares is not None:
        fs_text = (
            f"{quote.float_shares / 1e8:.2f} 亿股"
            if quote.float_shares >= 1e8
            else f"{quote.float_shares / 1e4:,.0f} 万股"
        )
        indicator_rows.append({"label": "流通股", "value": fs_text, "cls": "flat"})
    if quote.total_shares is not None:
        ts_text = (
            f"{quote.total_shares / 1e8:.2f} 亿股"
            if quote.total_shares >= 1e8
            else f"{quote.total_shares / 1e4:,.0f} 万股"
        )
        indicator_rows.append({"label": "总股本", "value": ts_text, "cls": "flat"})
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
    # vis3（2026-09-13 用户裁定）：标题用官方中文名；"状态 OK"是 debug 信息
    # 不进卡面（保留在文本回执与审计）；公司 logo + logo 代表色 accent。
    logo_domain = str(getattr(ref, "logo_domain", "") or "") if ref is not None else ""
    brand_color = str(getattr(ref, "brand_color", "") or "") if ref is not None else ""
    title_name = quote.name or ref_display or quote.ticker
    payload = {
        "title": f"{title_name}（{quote.ticker} · {quote.exchange or '美股'}）行情速览",
        "subtitle": stamp,
        "badge": "延迟行情" if quote.delayed else "实时",
        "sections": sections,
        "source_note": f"数据源：{quote.source or 'eastmoney'}",
        "delayed_note": "免费行情源为延迟口径",
        "feature_label": "个股行情",
    }
    if logo_domain:
        # F2（2026-09-14 素材本地化，治 clearbit 死源兜底）：payload 只落
        # 本地 file URI——缓存命中零网络；未命中经 clearbit→Google s2 补
        # 下载（local_logo_uri 既有机制，成功即入缓存，下次零网络）；两源
        # 全败诚实省略 logo 字段，卡片不出 logo，绝不再让 Chromium 渲染期
        # 回源 logo.clearbit.com 死域名（networkidle 8s 页超时根因）。
        local_logo = local_logo_uri(logo_domain)
        if local_logo:
            payload["logo_url"] = local_logo
    if brand_color:
        payload["platform_color"] = brand_color
    return payload


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
            from plugins.bot_unified_runtime.domains.chat_reply.runtime.cache_policy import (
                prune_prefixed,
            )
            from plugins.bot_unified_runtime.domains.render.card_render.bridge import (
                render_finance_card_html,
            )

            payload = dict(payload)
            _apply_cached_logo(payload)
            payload["bot_name"] = str(
                getattr(config, "bot_persona_display_name", "") or ""
            ).strip() or "守岸人"
            payload["bot_avatar_url"] = str(
                bot_avatar_uri(config)
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
            from plugins.bot_unified_runtime.domains.chat_reply.runtime.cache_policy import (
                prune_prefixed,
            )
            from plugins.bot_unified_runtime.domains.render.card_render.bridge import (
                render_finance_card_html,
            )

            payload = dict(payload)
            payload["bot_name"] = str(
                getattr(config, "bot_persona_display_name", "") or ""
            ).strip() or "守岸人"
            payload["bot_avatar_url"] = str(
                bot_avatar_uri(config)
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

        from plugins.bot_unified_runtime.domains.finance.data.stock_data import (
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
                body=_empty_panel_text(),
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
                from plugins.bot_unified_runtime.domains.finance.data.finance_chart import (
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
                    "想看哪家公司？美股支持：英伟达（NVDA）、AMD、英特尔（INTC）、"
                    "苹果（AAPL）、微软（MSFT）、谷歌（GOOGL）、亚马逊（AMZN）、"
                    "Meta（META）、台积电（TSM）；A股：贵州茅台、宁德时代、比亚迪、"
                    "招商银行、中国平安、建设银行、五粮液、紫金矿业、中芯国际；"
                    "港股：腾讯控股、阿里巴巴、美团、小米集团、香港交易所、京东集团、"
                    "网易、友邦保险；OpenAI/Anthropic/字节跳动未上市，可以问它们的"
                    "估值。或发「美股股价」看九家面板。"
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
            from plugins.bot_unified_runtime.domains.finance.data.stock_data import (
                _COMPANY_BY_TICKER,
            )

            payload = build_stocks_card_payload(
                quote, series, kdj, cap,
                ref=_COMPANY_BY_TICKER.get(quote.ticker),
            )
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


def warm_logo_cache(
    domains: list[str] | None = None, *, timeout: float = 6.0
) -> list[str]:
    """幂等预热：注册域名 logo 逐个补缓存，返回仍失败的域名清单（不抛）。

    ``domains=None`` 时取上市公司注册表全量（去重排序，当前 9 家）。命中
    缓存的域名零网络直接跳过，因此可重复执行；失败域名只记录不阻塞——
    后续真实查询会各自懒加载补缓存。CLI 入口见文件末尾 ``__main__``。
    """
    if domains is None:
        from plugins.bot_unified_runtime.domains.finance.data.stock_data import (
            list_listed_companies,
        )

        domains = sorted(
            {
                str(getattr(ref, "logo_domain", "") or "").strip().lower()
                for ref in list_listed_companies()
            }
            - {""},
        )
    failed: list[str] = []
    for domain in domains:
        # local_logo_uri 自带「缓存命中零网络 → clearbit → s2」全链，
        # 失败内部吞异常返回空串——这里只收集失败名单。
        if not local_logo_uri(domain, timeout=timeout):
            failed.append(domain)
    return failed


if __name__ == "__main__":
    # CLI 预热（工作区根执行）：
    #   python -m plugins.bot_unified_runtime.domains.finance.capabilities.stocks
    _failed = warm_logo_cache()
    if _failed:
        print(
            f"logo 预热：{len(_failed)} 家失败（不阻塞，查询时自动补）："
            + "、".join(_failed)
        )
    else:
        print("logo 预热：全部命中本地缓存（data/stock_logos，零网络）")
