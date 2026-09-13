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
                    getattr(config, "bot_persona_avatar_url", "") or ""
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
