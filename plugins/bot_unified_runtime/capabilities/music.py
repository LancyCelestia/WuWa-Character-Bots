"""点歌能力（bot.music）：『点歌 <关键词>』按平台顺序搜索并渲染。

- 纯接口搜索，不调用 LLM；每个平台拿第一名，失败自动换下一个。
- 输出：文字信息卡 + 可选语音片段（record 直链，拿不到就纯文本）。
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
from plugins.bot_unified_runtime.sources.parsers import (
    build_cookie_provider,
    music_search_providers,
)

_COMMAND_RE = re.compile(r"^[/!！]?点歌\s*(?P<query>.+)$")


def is_music_command(text: str) -> bool:
    return _COMMAND_RE.match(text.strip()) is not None


def extract_music_query(text: str) -> str:
    match = _COMMAND_RE.match(text.strip())
    if not match:
        raise ValueError("not a music command")
    query = match.group("query").strip()
    if not query:
        raise ValueError("empty music query")
    return query


def _media_parts_from_item(item: Any) -> list[dict]:
    """从解析结果组装媒体部分：优先语音直链，其次 QQ 音乐卡片。"""
    if item.audio_url:
        return [{"type": "record", "file": item.audio_url}]
    music_card = (item.stats or {}).get("music_card")
    if isinstance(music_card, dict) and music_card.get("type") and music_card.get("id"):
        return [
            {
                "type": "music",
                "music_type": str(music_card["type"]),
                "music_id": str(music_card["id"]),
            }
        ]
    return []


def _render_music_body(item: Any) -> str:
    lines = [f"♪ {item.title}"]
    if item.author_name:
        lines.append(f"歌手：{item.author_name}")
    if item.summary:
        lines.append(item.summary)
    parts = _media_parts_from_item(item)
    if parts:
        if parts[0]["type"] == "record":
            lines.append("（语音片段随后发出，没声音说明试听链接被平台拦了）")
        else:
            lines.append("（已附带平台音乐卡片）")
    if item.canonical_url:
        lines.append(f"链接：{item.canonical_url}")
    return "\n".join(lines)


def build_music_capability(
    config: Any | None = None,
    *,
    providers: list[Any] | None = None,
) -> Any:
    """构建 bot.music 能力；providers 为空时按 config 平台名单构建。"""
    if providers is None:
        platforms = getattr(config, "bot_music_platforms", []) or [] if config else []
        providers = music_search_providers(
            platforms or None,
            cookie_provider=build_cookie_provider(config) if config else None,
        )

    def capability(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        try:
            query = extract_music_query(message.plain_text)
        except ValueError:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.music",
                kind="text",
                body="用法：点歌 <歌名或关键词>，例如『点歌 晴天』。",
                audit_tags=["music_request", "missing_query"],
            )
        for parser_id, display_name, search_fn in providers:
            try:
                item = search_fn(query)
            except Exception:  # noqa: BLE001 - 单平台失败换下一个。
                item = None
            if item is None:
                continue
            body = _render_music_body(item)
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.music",
                kind="mixed",
                title=item.title,
                body=body,
                url=item.canonical_url or None,
                images=[{"file": item.cover_url}] if item.cover_url else [],
                audio=_media_parts_from_item(item),
                risk_level=RiskLevel.LOW,
                privacy_level=PrivacyLevel.PUBLIC,
                audit_tags=[
                    "music_request",
                    f"music_source:{parser_id}",
                    f"query:{query[:20]}",
                ],
            )
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.music",
            kind="text",
            body=f"没有找到『{query}』，换个关键词或歌手名再试试？",
            audit_tags=["music_request", "music_not_found"],
        )

    return capability
