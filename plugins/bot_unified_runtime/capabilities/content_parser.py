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
    parse_history_store: Any | None = None,
    downloader: Any | None = None,
    render_backend: Any | None = None,
    card_dir: str = "data/cards",
) -> Any:
    """构建 bot.content 能力。

    ``registry`` 为空时用 config 的平台名单构建。
    ``parse_history_store`` 存在时记录每次成功解析。
    ``downloader`` 存在且媒体分析开启时，给视频类结果追加画质/音频分析。
    ``render_backend`` 可用时把信息卡渲染成 PNG 图片（首段发送）。
    """
    if registry is None:
        if config is None:
            built = build_content_parser_registry(enabled_platforms)
        else:
            platforms = getattr(config, "bot_content_parse_platforms", []) or []
            built = build_content_parser_registry(
                platforms or enabled_platforms or None,
                cookie_provider=build_cookie_provider(config),
                proxy=str(getattr(config, "bot_download_proxy", "") or ""),
            )
    else:
        built = registry
    parser_registry = built["registry"]
    parsers: dict[str, Any] = built["parsers"]
    analyze_media = bool(
        config is not None and getattr(config, "bot_media_analyze_enabled", True)
    )

    def _render_card_image(item: Any) -> dict | None:
        """把解析结果渲染成 PNG 信息卡；失败返回 None（文本兜底）。"""
        if render_backend is None or not getattr(render_backend, "available", False):
            return None
        from plugins.bot_unified_runtime.output.templates import (
            card_payload_from_parse,
            render_media_card_html,
        )

        try:
            payload = card_payload_from_parse(item)
            payload["stats"] = {
                label: value
                for label, value in payload["stats"].items()
                if not isinstance(value, (dict, list))
            }
            html_text = render_media_card_html(payload)
            png = render_backend.render_card({"html": html_text})
            if not png:
                return None
            from pathlib import Path
            import hashlib

            target_dir = Path(card_dir)
            target_dir.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha1(
                (item.canonical_url or item.title or item.item_id).encode("utf-8")
            ).hexdigest()[:12]
            path = target_dir / f"card_{digest}.png"
            path.write_bytes(png)
            return {"file": str(path)}
        except Exception:  # noqa: BLE001 - 卡片渲染失败不影响主链路。
            return None

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
        media_lines: list[str] = []
        if (
            analyze_media
            and item.item_kind in {"video", "live"}
            and downloader is not None
        ):
            try:
                analysis = downloader.probe(candidate)
                media_lines = [
                    "媒体信息：",
                    *[f"  {line}" for line in analysis.summary_lines()],
                    f"下载：/bot download {candidate}",
                ]
            except Exception:  # noqa: BLE001 - 分析失败不影响卡片。
                media_lines = []
        body = _render_parse_body(item)
        if media_lines:
            body = f"{body}\n" + "\n".join(media_lines)
        if parse_history_store is not None:
            try:
                parse_history_store.record(
                    request_id=message.request_id,
                    session_id=message.session_id,
                    sender_id=message.sender_id,
                    platform=match.parser_id,
                    item_id=item.item_id,
                    item_kind=item.item_kind,
                    title=item.title,
                    url=item.canonical_url or candidate,
                    parse_depth=item.parse_depth,
                    body_preview=body,
                )
            except Exception:  # noqa: BLE001 - 历史失败不影响主链路。
                pass
        card_image = _render_card_image(item)
        images: list[dict] = []
        if card_image is not None:
            images.append(card_image)
        elif item.cover_url:
            images.append({"file": item.cover_url})
        result = CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.content",
            kind="mixed",
            title=item.title,
            body=body,
            url=item.canonical_url or candidate,
            images=images,
            audio=_media_parts_from_item(item),
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=[
                "content_parse",
                f"platform:{match.parser_id}",
                f"parse_depth:{item.parse_depth}",
                f"item_kind:{item.item_kind}",
                *(["media_analyzed"] if media_lines else []),
                *(["card_rendered"] if card_image is not None else []),
            ],
        )
        return result

    return capability
