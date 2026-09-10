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
    format_market_brief,
)

# 触发词：全球股市 > 股指/大盘/股市/行情（行情放最后避免误伤面过大时漏判）。
_MARKET_TRIGGER_RE = re.compile(r"(全球股市|股指|大盘|股市|行情)")
# 非股市的"行情"（房价/基金/币圈/显卡/期货）：命中且无股/大盘/股指/指数词时不触发。
_NON_STOCK_RE = re.compile(r"(房价|基金|币圈|加密|显卡|期货|汇率)")
_STOCK_HINT_RE = re.compile(r"(股|大盘|指数)")

_URL_HINT_RE = re.compile(r"https?://", re.IGNORECASE)
_MAX_TRIGGER_LEN = 32

_EMPTY_DEGRADED_TEXT = "行情数据暂时拉不到，晚点再试试？"

# 明确市场词 → 指数 secid（多个词命中取并集；空 = 全部指数）。
_MARKET_FILTERS: tuple[tuple[str, frozenset[str]], ...] = (
    ("A股", frozenset({"1.000001", "0.399001", "0.399006"})),
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
)


def market_filter_secids(text: str) -> frozenset[str]:
    """提取文本中的明确市场词，返回目标指数 secid 集合；空 = 不过滤。"""
    matched: set[str] = set()
    for keyword, secids in _MARKET_FILTERS:
        if keyword in text:
            matched.update(secids)
    return frozenset(matched)


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


def build_market_capability(config: Any | None = None) -> Any:
    """构建行情能力闭包；超时/缓存时长可由配置覆盖。"""

    def capability(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        quotes: list[IndexQuote] = fetch_index_quotes(
            timeout_seconds=float(
                getattr(config, "bot_market_timeout_seconds", 6.0) or 6.0
            ),
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
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.market",
            kind="text",
            title="全球股指速览",
            body=format_market_brief(shown),
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=["capability:market", f"market_quotes:{len(shown)}"],
        )

    return capability
