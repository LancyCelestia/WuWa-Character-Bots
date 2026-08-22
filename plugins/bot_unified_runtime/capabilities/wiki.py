"""维基百科查询能力（bot.wiki）：`维基 <词条>` / `wiki <词条>`。

纯 MediaWiki 公开 API（免 key），结果走统一流水线；失败返回提示而非
异常。默认中文维基（zh），可用配置切换语言。
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
from plugins.bot_unified_runtime.sources.mediawiki import wiki_lookup

_COMMAND_RE = re.compile(r"^(?:维基|wiki|维基百科)\s*(?P<query>.+)$", re.IGNORECASE)


def is_wiki_command(text: str) -> bool:
    return _COMMAND_RE.match(text.strip()) is not None


def extract_wiki_query(text: str) -> str:
    match = _COMMAND_RE.match(text.strip())
    if not match:
        raise ValueError("not a wiki command")
    query = match.group("query").strip()
    if not query:
        raise ValueError("empty wiki query")
    return query


def build_wiki_capability(config: Any | None = None) -> Any:
    lang = str(getattr(config, "bot_wiki_lang", "zh") or "zh") if config else "zh"
    proxy = str(getattr(config, "bot_download_proxy", "") or "") if config else ""

    def capability(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        try:
            query = extract_wiki_query(message.plain_text)
        except ValueError:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.wiki",
                kind="text",
                body="用法：维基 <词条>，例如『维基 鸣潮』",
                audit_tags=["wiki", "missing_query"],
            )
        result = wiki_lookup(query, lang=lang, proxy=proxy)
        if result is None:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.wiki",
                kind="text",
                body=f"没有在{lang}维基上找到『{query}』，换个写法试试？",
                audit_tags=["wiki", "not_found"],
            )
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.wiki",
            kind="text",
            title="维基百科",
            body=result,
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=["wiki", f"wiki_lang:{lang}", f"wiki_query:{query[:20]}"],
        )

    return capability
