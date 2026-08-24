"""链接解析能力（bot.content）：识别消息里的平台链接并渲染信息卡。

不调用 LLM：纯规则匹配 + 平台解析 + 文本/图片渲染。
解析失败优雅降级：原链接 + 简短说明，绝不中断流水线。
"""

from __future__ import annotations

from typing import Any

from plugins.bot_unified_runtime.capabilities.music import _media_parts_from_item
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


def _clean_summary(summary: str) -> str:
    """简介只保留博主原始简介：剔除时长/发布时间等元数据行。"""
    kept: list[str] = []
    for raw_line in (summary or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        upper_head = line.split("：", 1)[0].split(":", 1)[0].strip()
        if upper_head == "简介":
            content = ""
            if "：" in line:
                content = line.split("：", 1)[1]
            elif ":" in line:
                content = line.split(":", 1)[1]
            content = content.strip()
            if content:
                kept.append(content)
            continue
        if upper_head in {"时长", "视频时长", "发布时间", "时间", "上传时间"}:
            continue
        kept.append(line)
    return "\n".join(kept)


def _render_parse_body(
    item: Any,
    *,
    media_params: list[str] | None = None,
) -> str:
    """标题/作者/数据/简介/媒体参数分区渲染，区块之间保留空行。"""
    lines: list[str] = []
    lines.append(f"【标题】{item.title}")
    if item.author_name:
        lines.append(f"【作者】{item.author_name}")
    stats = {
        str(label): value
        for label, value in (item.stats or {}).items()
        if not isinstance(value, (dict, list))
    }
    publish_time = stats.pop("发布时间", None) or stats.pop("时间", None)
    stats.pop("时长", None)
    stats.pop("视频时长", None)
    stats_bits = [f"{label} {value}" for label, value in stats.items()]
    if stats_bits:
        lines.append("")
        lines.append("【数据】" + " · ".join(stats_bits))
    if publish_time:
        lines.append("")
        lines.append(f"【发布】{publish_time}")
    if item.summary:
        clean_summary = _clean_summary(item.summary)
        if clean_summary:
            lines.append("")
            lines.append("【简介】")
            lines.append(clean_summary)
    if media_params:
        lines.append("")
        lines.append("【媒体参数】")
        for line in media_params:
            lines.append(f"  · {line}" if line else "")
    if item.canonical_url:
        lines.append("")
        lines.append(f"【链接】{item.canonical_url}")
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
    playwright_backend: Any | None = None,
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
                playwright_backend=playwright_backend,
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
            render_universal_card_html,
        )

        try:
            platform = str(getattr(item, "platform", "") or "").strip().lower()
            universal_platforms = {
                "bilibili", "xiaohongshu", "xhs", "youtube", "twitter", "x",
                "pixiv", "lofter", "allcpp", "cpp",
                "netease", "ncm", "qqmusic", "kugou", "kuwo", "apple_music",
                "spotify",
            }
            use_universal = bool(
                getattr(item, "page_type", "")
                or getattr(item, "badge", "")
                or getattr(item, "detail", None)
            ) or platform in universal_platforms
            bot_name = (
                str(getattr(config, "bot_persona_display_name", "") or "").strip()
                or "守岸人"
            )
            bot_avatar_url = str(
                getattr(config, "bot_persona_avatar_url", "") or ""
            ).strip()
            if use_universal:
                payload = card_payload_from_parse(item)
                payload["bot_name"] = bot_name
                payload["bot_avatar_url"] = bot_avatar_url
                html_text = render_universal_card_html(payload)
                render_payload = {
                    "html": html_text,
                    "viewport": {"width": 1440, "height": 960},
                    "device_scale_factor": 2,
                }
            else:
                payload = card_payload_from_parse(item)
                payload["stats"] = {
                    label: value
                    for label, value in payload["stats"].items()
                    if not isinstance(value, (dict, list))
                }
                html_text = render_media_card_html(payload)
                render_payload = {"html": html_text}
            png = render_backend.render_card(render_payload)
            if not png:
                return None
            import hashlib
            from pathlib import Path

            target_dir = Path(card_dir)
            target_dir.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha1(
                (item.canonical_url or item.title or item.item_id).encode("utf-8")
            ).hexdigest()[:12]
            path = target_dir / f"card_{digest}.png"
            path.write_bytes(png)
            try:
                from plugins.bot_unified_runtime.runtime.cache_policy import (
                    enforce_quota,
                )

                enforce_quota(
                    target_dir,
                    max_bytes=int(getattr(config, "bot_card_cache_max_bytes", 0) or 0),
                )
            except Exception:  # noqa: S110, BLE001 - 缓存配额清理失败不影响主链路。
                pass
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
        media_params: list[str] = []
        video_like = item.item_kind in {"video", "live"} or (
            item.item_kind == "dynamic"
            and "/video/" in (item.canonical_url or "")
        )
        music_like = item.item_kind in {"song", "audio"} or bool(
            getattr(item, "audio_url", "")
        )
        if analyze_media and (video_like or music_like) and downloader is not None:
            try:
                if music_like:
                    probe_url = getattr(item, "audio_url", "") or candidate
                    analysis = downloader.probe(probe_url)
                    channels_text = f"{analysis.channels}声道"
                    if analysis.channels == 2:
                        channels_text = "双声道"
                    elif analysis.channels == 1:
                        channels_text = "单声道"
                    audio_lines = []
                    if analysis.audio_bitrate_kbps:
                        audio_lines.append(
                            f"码率：{analysis.audio_bitrate_kbps:.0f}kbps"
                        )
                    audio_lines.append(f"格式：{analysis.acodec or analysis.ext or '-'}")
                    if analysis.channels:
                        audio_lines.append(f"声道：{channels_text}")
                    # Hi-Res / 杜比全景声：有才写，没有就隐藏。
                    if analysis.audio_quality:
                        audio_lines.append(f"音质：{analysis.audio_quality}")
                    media_params = audio_lines
                else:
                    probe_url = (
                        item.canonical_url
                        if "/video/" in (item.canonical_url or "")
                        else candidate
                    )
                    analysis = downloader.probe(probe_url)
                    video_lines = [
                        f"分辨率：{analysis.resolution()}",
                    ]
                    if analysis.fps:
                        video_lines.append(f"帧率：{analysis.fps:.0f}fps")
                    video_lines.append(f"时长：{analysis.duration_text()}")
                    if analysis.video_bitrate_kbps:
                        video_lines.append(
                            f"视频码率：{analysis.video_bitrate_kbps / 1000:.1f}Mbps"
                        )
                    # HDR / 杜比视界：有才写，没有就隐藏。
                    if analysis.hdr:
                        video_lines.append(f"画面动态范围：{analysis.hdr}")
                    size_text = (
                        f"视频大小：{analysis.filesize_bytes / 1048576:.1f}MB"
                        if analysis.filesize_bytes
                        else "视频大小：流媒体（无固定大小）"
                    )
                    video_lines.append(size_text)
                    audio_lines = []
                    if analysis.audio_bitrate_kbps:
                        audio_lines.append(
                            f"音频码率：{analysis.audio_bitrate_kbps:.0f}kbps"
                        )
                    audio_lines.append(
                        f"音频格式：{analysis.acodec or '-'}"
                    )
                    if analysis.channels:
                        channels_text = f"{analysis.channels}声道"
                        if analysis.channels == 2:
                            channels_text = "双声道"
                        elif analysis.channels == 1:
                            channels_text = "单声道"
                        audio_lines.append(f"声道：{channels_text}")
                    if analysis.audio_quality:
                        audio_lines.append(f"音质：{analysis.audio_quality}")
                    media_params = video_lines
                    if audio_lines:
                        media_params = [*video_lines, "", *audio_lines]
                    media_lines = [f"下载：/bot download {probe_url}"]
            except Exception:  # noqa: BLE001 - 分析失败不影响卡片。
                media_lines = []
        body = _render_parse_body(
            item,
            media_params=media_params,
        )
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
            except Exception:  # noqa: S110, BLE001 - 历史失败不影响主链路。
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

