"""今日快报能力（bot.news）：`快报/早报/晚报/今日热点/科技新闻/AI新闻` 触发。

数据来自 ``sources.news_feeds``（国内可达 RSS 聚合，进程内 10 分钟 TTL
缓存，单源失败静默跳过）。触发面刻意收窄：

- 只认显式触发词：快报 / 早报 / 晚报 / 今日热点 / 类目词×新闻|快报
  （科技新闻、AI新闻、AI快报、财经新闻、财经快报、国际新闻）；
- 裸「新闻」**不**触发——那是联网搜索链路的地盘（question_intent 的
  ``_CURRENT_REQUEST_RE`` 含裸 `新闻`，剥走会互相打架）；
- 短文本（≤32 字）、无链接（带链接是链接解析的活）；「搜索/搜一下/
  查一下/找新闻/联网/上网」等明确搜索意图时让路。

类目从同一句话提取：财经→finance、国际→world、科技/AI/人工智能→tech、
其余→mix（跨类目轮转）。
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
from plugins.bot_unified_runtime.sources.news_feeds import (
    CATEGORY_LABELS,
    fetch_headlines,
    format_news_brief,
)

# 显式触发词：复合词在前仅便于阅读；「新闻」单独出现不算触发。
_NEWS_TRIGGER_RE = re.compile(
    r"(今日热点|科技新闻|AI新闻|AI快报|财经新闻|财经快报|国际新闻|快报|早报|晚报)",
    re.IGNORECASE,
)
# 明确联网搜索意图 → 让路（与 question_intent._EXPLICIT_SEARCH_RE 同向）。
_SEARCH_INTENT_RE = re.compile(r"(搜索|搜一下|查一下|检索|找新闻|联网|上网)")
_URL_HINT_RE = re.compile(r"https?://", re.IGNORECASE)
_MAX_TRIGGER_LEN = 32

# 类目提示词 → 类目键（AI 用「紧邻 新闻/快报」匹配，避免英文单词误伤）。
_AI_HINT_RE = re.compile(r"((?:ai|人工智能)\s*(?:新闻|快报)|人工智能)", re.IGNORECASE)

_EMPTY_DEGRADED_TEXT = "快报暂时拉不到，稍后再试试？"


def extract_news_category(text: str) -> str:
    """从触发文本提取类目；无类目提示词时回退 mix（跨类目轮转）。"""
    stripped = (text or "").strip()
    if "财经" in stripped:
        return "finance"
    if "国际" in stripped:
        return "world"
    if "科技" in stripped or _AI_HINT_RE.search(stripped):
        return "tech"
    return "mix"


def is_news_command(text: str) -> bool:
    """快报触发判定：短文本、无链接、显式触发词、不撞搜索意图。"""
    stripped = (text or "").strip()
    if not stripped or len(stripped) > _MAX_TRIGGER_LEN:
        return False
    if _URL_HINT_RE.search(stripped):
        return False
    if not _NEWS_TRIGGER_RE.search(stripped):
        return False
    return not _SEARCH_INTENT_RE.search(stripped)


def build_news_capability(config: Any | None = None) -> Any:
    """构建快报能力闭包；超时/缓存时长/条数可由配置覆盖。

    ``bot_news_enabled`` 开关由基层路由（base_router news_match）检查，
    这里只负责把抓取结果装进 CapabilityResult；抓取为空时给降级文案，
    绝不阻塞会话。
    """

    def capability(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        category = extract_news_category(message.plain_text)
        label = CATEGORY_LABELS.get(category, CATEGORY_LABELS["mix"])
        items = fetch_headlines(
            category,
            timeout_seconds=float(
                getattr(config, "bot_news_timeout_seconds", 6.0) or 6.0
            ),
            cache_seconds=float(
                getattr(config, "bot_news_cache_seconds", 600.0) or 600.0
            ),
            max_items=int(getattr(config, "bot_news_max_items", 8) or 8),
        )
        if not items:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.news",
                kind="text",
                body=_EMPTY_DEGRADED_TEXT,
                audit_tags=["capability:news", "news:fetch_failed"],
            )
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.news",
            kind="text",
            title=f"今日快报 · {label}",
            body=format_news_brief(items, label),
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=[
                "capability:news",
                f"news_items:{len(items)}",
                f"news_category:{category}",
            ],
        )

    return capability
