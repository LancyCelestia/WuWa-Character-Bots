"""链接解析能力（bot.content）：识别消息里的平台链接并渲染信息卡。

不调用 LLM：纯规则匹配 + 平台解析 + 文本/图片渲染。
解析失败优雅降级：原链接 + 简短说明，绝不中断流水线。
"""

from __future__ import annotations

from typing import Any

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
)
from plugins.bot_unified_runtime.sources.parsers import (
    build_content_parser_registry,
    build_cookie_provider,
    build_source_input,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import ParseHttpError
from plugins.bot_unified_runtime.capabilities.music import _media_parts_from_item


def _render_parse_body(item: Any) -> str:
    lines: list[str] = []
    kind_labels = {
        "video": "视频",
        "music": "音乐",
        "note": "笔记",
        "post": "帖子",
        "article": "文章",
        "tweet": "推文",
        "search": "搜索",
        "live": "直播间",
        "user": "UP主主页",
        "collection": "收藏夹",
        "dynamic": "动态",
        "bangumi": "番剧",
        "playlist": "播放列表",
        "illust": "插画",
        "event": "活动",
        "tag": "标签",
        "theme": "主题",
        "page": "页面",
        "painter": "画师主页",
        "project": "企划",
        "stall": "摊宣",
        "artwork": "作品",
        "goods": "约稿商品",
        "work": "作品",
    }
    kind_label = kind_labels.get(item.item_kind, item.item_kind or "内容")
    lines.append(f"【{kind_label}】{item.title}")
    if item.author_name:
        lines.append(f"作者：{item.author_name}")
    stats_bits = [
        f"{label} {value}"
        for label, value in (item.stats or {}).items()
        if not isinstance(value, (dict, list))
    ]
    if stats_bits:
        lines.append(" · ".join(stats_bits))
    if item.summary:
        lines.append(item.summary)
    if item.canonical_url:
        lines.append(f"链接：{item.canonical_url}")
    return "\n".join(lines)


def build_content_capability(
    config: Any | None = None,
    *,
    registry: Any | None = None,
    enabled_platforms: list[str] | None = None,
) -> Any:
    """构建 bot.content 能力。

    ``registry`` 为空时用 config 的平台名单构建。
    """
    if registry is None:
        if config is None:
            built = build_content_parser_registry(enabled_platforms)
        else:
            platforms = getattr(config, "bot_content_parse_platforms", []) or []
            built = build_content_parser_registry(
                platforms or enabled_platforms or None,
                cookie_provider=build_cookie_provider(config),
            )
    else:
        built = registry
    parser_registry = built["registry"]
    parsers: dict[str, Any] = built["parsers"]

    def capability(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        source_input = build_source_input(
            message.plain_text,
            request_id=message.request_id,
        )
        matches = parser_registry.match(source_input)
        if not matches:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.content",
                kind="text",
                body="没有识别到支持的链接。",
                audit_tags=["content_parse", "no_link_match"],
            )
        match = matches[0]
        parse_fn = parsers.get(match.parser_id)
        if parse_fn is None:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.content",
                kind="text",
                body="这个平台的解析器还没有接入。",
                audit_tags=["content_parse", f"platform:{match.parser_id}", "parser_missing"],
            )
        # 选一条真正属于该平台的 URL。
        candidate = ""
        for url in source_input.urls:
            try:
                item = parse_fn(url)
                candidate = url
                break
            except (ParseHttpError, ValueError):
                continue
        if not candidate:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.content",
                kind="text",
                body="链接解析失败，先把原链接放在这里，晚点我再试试：\n"
                + (source_input.urls[0] if source_input.urls else message.plain_text),
                audit_tags=["content_parse", f"platform:{match.parser_id}", "parse_failed"],
            )
        try:
            item = parse_fn(candidate)
        except (ParseHttpError, ValueError):
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.content",
                kind="text",
                body="链接解析失败，先把原链接放在这里，晚点我再试试：\n" + candidate,
                audit_tags=["content_parse", f"platform:{match.parser_id}", "parse_failed"],
            )
        body = _render_parse_body(item)
        result = CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.content",
            kind="mixed",
            title=item.title,
            body=body,
            url=item.canonical_url or candidate,
            images=[{"file": item.cover_url}] if item.cover_url else [],
            audio=_media_parts_from_item(item),
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=[
                "content_parse",
                f"platform:{match.parser_id}",
                f"parse_depth:{item.parse_depth}",
                f"item_kind:{item.item_kind}",
            ],
        )
        return result

    return capability
