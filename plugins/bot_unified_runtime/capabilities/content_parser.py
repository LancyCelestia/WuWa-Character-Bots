"""链接解析能力（bot.content）：识别消息里的平台链接并渲染信息卡。

不调用 LLM：纯规则匹配 + 平台解析 + 文本/图片渲染。
解析失败优雅降级：原链接 + 简短说明，绝不中断流水线。
"""

from __future__ import annotations

from typing import Any

from plugins.bot_unified_runtime.capabilities.music import (
    _media_parts_from_item,
    music_audio_url,
    music_cover_url,
)
from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
    SendPolicy,
)
from plugins.bot_unified_runtime.contracts.media import build_parsed_content
from plugins.bot_unified_runtime.sources.parsers import (
    build_content_parser_registry,
    build_cookie_provider,
    build_source_input,
)
from plugins.bot_unified_runtime.sources.parsers.context import (
    FetchContext,
    ParseFailure,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import ParseHttpError
from plugins.bot_unified_runtime.sources.parsers.types import ParsedContent


def parse_matched_url(
    urls: list[str],
    parse_fn: Any,
    context: FetchContext,
) -> Any:
    """解析已经由规则选中的 URL；一次调用解析器，不做网络探测。"""
    if not urls:
        raise ValueError("no URL candidates")
    return parse_fn(urls[0], context)


def _clean_summary(summary: str) -> str:
    """简介区清洗：剔除时长/发布时间等元数据行；保留解析器的空行分段
    （AI 总结、热门评论与原始简介之间的视觉分隔），连续空行折叠为一行。"""
    kept: list[str] = []
    for raw_line in (summary or "").splitlines():
        line = raw_line.strip()
        if not line:
            if kept and kept[-1] != "":
                kept.append("")
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
        if upper_head in {"时长", "视频时长", "发布时间", "时间", "上传时间", "分区"}:
            continue
        kept.append(line)
    while kept and kept[0] == "":
        kept.pop(0)
    while kept and kept[-1] == "":
        kept.pop()
    return "\n".join(kept)


_ENGAGEMENT_LABELS: list[tuple[str, str]] = [
    ("view_count", "播放"),
    ("play_count", "播放"),
    ("like_count", "点赞"),
    ("heart_count", "爱心"),
    ("favorite_count", "收藏"),
    ("bookmark_count", "收藏"),
    ("comment_count", "评论"),
    ("share_count", "分享"),
    ("repost_count", "转发"),
    ("quote_count", "引用"),
    ("danmaku_count", "弹幕"),
    ("coin_count", "投币"),
]

# 文本输出里属于内部元数据、不进入公开数据行的键（与卡片侧 _KNOWN_STAT_KEYS 对齐）。
_INTERNAL_STAT_KEYS = frozenset(
    {
        "时长", "视频时长", "duration", "duration_seconds", "pubdate",
        "发布时间", "时间", "上传时间",
        "AV", "av", "avid", "AV号", "BVID", "bvid",
    }
)


def _engagement_text_bits(engagement: Any) -> list[str]:
    """互动数据 → 文本行位（统一字段 + platform_extra 标量透传）。"""
    bits: list[str] = []
    seen_labels: set[str] = set()
    for field, label in _ENGAGEMENT_LABELS:
        value = getattr(engagement, field, None)
        if value is None or isinstance(value, bool):
            continue
        if label == "播放" and "播放" in seen_labels:
            continue
        seen_labels.add(label)
        bits.append(f"{label} {value}")
    for key, value in (getattr(engagement, "platform_extra", None) or {}).items():
        if isinstance(value, (dict, list)) or value is None:
            continue
        if key in _INTERNAL_STAT_KEYS:
            continue
        bits.append(f"{key} {value}")
    return bits


def _format_publish_time(value: Any) -> str:
    """发布时间 → 'YYYY-MM-DD HH:MM:SS'（本地时区，精确到秒）；失败返回空串。"""
    if value is None:
        return ""
    try:
        if getattr(value, "tzinfo", None) is None:
            return value.strftime("%Y-%m-%d %H:%M:%S")  # type: ignore[union-attr]
        return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")  # type: ignore[union-attr]
    except (AttributeError, ValueError, OSError):
        return str(value)


def _render_parse_body(
    item: Any,
    *,
    media_params: list[str] | None = None,
    include_media_params: bool = True,
) -> str:
    """标题/作者/数据/发布/简介/链接分区渲染（纯嵌套模型读取），区块保留空行。"""
    identity = item.identity
    content = item.content
    creator = item.creator
    engagement = item.engagement
    lines: list[str] = []
    lines.append(f"【标题】{content.title if content else ''}")
    if creator is not None and creator.name:
        lines.append(f"【作者】{creator.name}")
    stats_bits = _engagement_text_bits(engagement)
    if stats_bits:
        lines.append("")
        lines.append("【数据】" + " · ".join(stats_bits))
    if content is not None and content.published_at is not None:
        lines.append("")
        lines.append(f"【发布】{_format_publish_time(content.published_at)}")
    if content is not None:
        clean_summary = _clean_summary(content.summary or content.body)
        if clean_summary:
            lines.append("")
            lines.append("【简介】")
            lines.append(clean_summary)
    if include_media_params and media_params:
        lines.append("")
        lines.append("【媒体参数】")
        for line in media_params:
            if line:
                lines.append(f"  · {line}")
    if identity is not None and identity.canonical_url:
        lines.append("")
        lines.append(f"【链接】{identity.canonical_url}")
    return "\n".join(lines)


def _is_private_admin(message: IncomingMessage) -> bool:
    """Media probe details are operational/admin data, never group-card content."""
    session_type = getattr(getattr(message, "session_type", None), "value", "")
    roles = {str(role).strip().lower() for role in getattr(message, "sender_roles", [])}
    return session_type == "private" and "admin" in roles


def _content_failure_result(
    message: IncomingMessage,
    *,
    body: str,
    audit_tags: list[str],
) -> CapabilityResult:
    """Keep supported-link diagnostics private; public groups remain quiet on failure."""
    if getattr(getattr(message, "session_type", None), "value", "") == "group":
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.content",
            kind="text",
            body="",
            send_policy=SendPolicy.SILENT_AUDIT,
            audit_tags=[*audit_tags, "silent_group_parse_failure"],
        )
    return CapabilityResult(
        request_id=message.request_id,
        capability_id="bot.content",
        kind="text",
        body=body,
        audit_tags=audit_tags,
    )


def _explicit_platform_hdr(item: Any) -> str:
    """Return only HDR asserted by platform metadata; never infer it from a probe."""
    video_asset = next(
        (asset for asset in (item.media or []) if asset.asset_type == "video"),
        None,
    )
    extras: dict = {}
    if item.content is not None:
        extras = dict(item.content.platform_extra or {})
    video_extras = extras.get("video")
    values: list[Any] = []
    if video_asset is not None:
        values.append(video_asset.dynamic_range)
    if isinstance(video_extras, dict):
        values.append(video_extras.get("hdr"))
        values.append(video_extras.get("dynamic_range"))
    values.append(extras.get("hdr"))
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value is True:
            return "HDR"
    return ""


# 订阅条目 kind → 通用卡 page_type：命中即走 Mica 分支，其余走通用分支。
_SUBSCRIPTION_PAGE_TYPES = {
    "video": "video",
    "dynamic": "dynamic",
    "note": "note",
    "post": "post",
}


def render_card_png(
    render_backend: Any,
    item: Any,
    *,
    config: Any,
    card_dir: str = "data/cards",
    bot_avatar_url: str = "",
) -> dict | None:
    """把解析结果渲染成 PNG 信息卡并写入 ``card_dir``；失败返回 None。

    模块级独立函数：bot.content 与订阅推送共用同一条卡片渲染管线，
    渲染失败一律返回 None，由调用方回退各自的文本输出。
    """
    if render_backend is None or not getattr(render_backend, "available", False):
        return None
    from plugins.bot_unified_runtime.output.templates import (
        card_payload_from_parse,
        render_media_card_html,
        render_universal_card_html,
    )

    try:
        identity = item.identity
        content = item.content
        platform = str((identity.platform if identity else "") or "").strip().lower()
        universal_platforms = {
            "bilibili", "xiaohongshu", "xhs", "douyin", "weibo", "youtube", "twitter", "x",
            "facebook", "instagram", "pixiv", "lofter", "allcpp", "cpp",
            "netease", "ncm", "qqmusic", "kugou", "kuwo", "apple_music",
            "spotify",
        }
        extras = dict(content.platform_extra or {}) if content else {}
        # 只按「扩展区块」判断通用卡：cover_url/images 只是媒体透传，
        # 不应单独把无 detail 的浅解析结果（如 Epic og 兜底）切到通用卡。
        use_universal = bool(
            extras.get("page_type")
            or extras.get("badge")
            or any(key not in {"cover_url", "images"} for key in extras)
        ) or platform in universal_platforms
        bot_name = (
            str(getattr(config, "bot_persona_display_name", "") or "").strip()
            or "守岸人"
        )
        resolved_bot_avatar_url = (
            str(bot_avatar_url or "").strip()
            or str(getattr(config, "bot_persona_avatar_url", "") or "").strip()
        )
        if use_universal:
            payload = card_payload_from_parse(item)
            payload["bot_name"] = bot_name
            payload["bot_avatar_url"] = resolved_bot_avatar_url
            html_text = render_universal_card_html(payload)
            # 整体 UI 缩放（bot_card_ui_scale，1.0=100%，1.25=125%）。
            # 语义同 Windows 显示缩放：card_width 传 1440px 原基准，模板把
            # shell 按缩放除窄再 zoom 放大回全宽——输出像素不变，元素等比变大。
            ui_scale = 1.0
            try:
                ui_scale = float(getattr(config, "bot_card_ui_scale", 1.0) or 1.0)
            except (TypeError, ValueError):
                ui_scale = 1.0
            ui_scale = max(0.5, min(2.0, ui_scale))
            render_payload = {
                "html": html_text,
                # Mica 分支外层有 28px 透明留白承载柔光阴影：1504 = 1440 + 56。
                "viewport": {"width": 1504, "height": 1000},
                "device_scale_factor": 2,
                "scale_factor": ui_scale,
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
        identity = item.identity
        digest_source = (
            (identity.canonical_url if identity else "")
            or (content.title if content else "")
            or (identity.item_id if identity else "")
        )
        digest = hashlib.sha1(digest_source.encode("utf-8")).hexdigest()[:12]
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


def subscription_item_to_parse(item: Any, spec: Any) -> ParsedContent:
    """把订阅条目转成 ParsedContent 形状，复用解析卡渲染管线。"""
    kind = str(getattr(item, "kind", "") or "")
    return build_parsed_content(
        platform=str(getattr(spec, "platform", "") or ""),
        item_id=str(getattr(item, "item_id", "") or ""),
        item_kind=kind,
        title=str(getattr(item, "title", "") or ""),
        author_name=str(getattr(item, "author_name", "") or ""),
        summary=str(getattr(item, "summary", "") or ""),
        cover_url=str(getattr(item, "cover_url", "") or ""),
        canonical_url=str(getattr(item, "url", "") or ""),
        stats=dict(getattr(item, "stats", {}) or {}),
        page_type=_SUBSCRIPTION_PAGE_TYPES.get(kind, ""),
    )


def render_subscription_push_card(
    render_backend: Any,
    candidate: Any,
    spec: Any,
    *,
    config: Any,
    card_dir: str = "data/cards",
) -> dict | None:
    """渲染订阅即时推送卡片；无 URL 或任何失败返回 None（回退纯文本）。"""
    item = getattr(candidate, "item", None)
    if item is None or not str(getattr(item, "url", "") or "").strip():
        return None
    return render_card_png(
        render_backend,
        subscription_item_to_parse(item, spec),
        config=config,
        card_dir=card_dir,
    )


def build_subscription_push_capability(
    text: str,
    images: list[dict[str, str]] | None = None,
) -> Any:
    """构造订阅推送能力：images 非空输出「卡片图+文本」，否则纯文本。"""

    def capability(message: IncomingMessage, _decision: BotDecision) -> CapabilityResult:
        payload_images = [{"type": "image", **image} for image in (images or [])]
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.subscribe",
            kind="mixed" if payload_images else "text",
            body=text,
            images=payload_images,
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=["subscription_push"],
        )

    return capability


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
    bot_avatar_url: str = "",
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
        return render_card_png(
            render_backend,
            item,
            config=config,
            card_dir=card_dir,
            bot_avatar_url=bot_avatar_url,
        )

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
                body="",
                send_policy=SendPolicy.SILENT_AUDIT,
                audit_tags=["content_parse", "no_link_match", "silent_unsupported_link"],
            )
        match = matches[0]
        parse_fn = parsers.get(match.parser_id)
        if parse_fn is None:
            return _content_failure_result(
                message,
                body="这个平台的解析器还没有接入。",
                audit_tags=["content_parse", f"platform:{match.parser_id}", "parser_missing"],
            )
        # URL 已由 ParserRegistry 按规则匹配；不再先调用 parser 探测，
        # 避免网络请求重复一次并降低平台风控概率。
        candidate = next(
            (
                url
                for url in source_input.urls
                if match.matched_keyword and match.matched_keyword in url
            ),
            source_input.urls[0] if source_input.urls else "",
        )
        if not candidate:
            return _content_failure_result(
                message,
                body="链接解析失败，先把原链接放在这里，晚点我再试试：\n"
                + (source_input.urls[0] if source_input.urls else message.plain_text),
                audit_tags=["content_parse", f"platform:{match.parser_id}", "parse_failed"],
            )
        try:
            item = parse_fn(candidate)
        except (ParseHttpError, ValueError, ParseFailure):
            return _content_failure_result(
                message,
                body="链接解析失败，先把原链接放在这里，晚点我再试试：\n" + candidate,
                audit_tags=["content_parse", f"platform:{match.parser_id}", "parse_failed"],
            )
        identity = item.identity
        content = item.content
        provenance = item.provenance
        item_kind = identity.item_kind if identity else "unknown"
        canonical_url = identity.canonical_url if identity else ""
        item_id = identity.item_id if identity else ""
        parse_depth = provenance.parse_depth if provenance else "deep"
        audio_url = music_audio_url(item)
        cover_url = music_cover_url(item)
        media_lines: list[str] = []
        media_params: list[str] = []
        has_direct_video = any(
            asset.asset_type == "video" and asset.url for asset in (item.media or [])
        )
        video_like = item_kind in {"video", "live"} or (
            item_kind == "dynamic" and "/video/" in canonical_url
        ) or has_direct_video
        music_like = item_kind in {"song", "audio"} or bool(audio_url)
        if analyze_media and (video_like or music_like) and downloader is not None:
            try:
                if music_like:
                    probe_url = audio_url or candidate
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
                    probe_url = canonical_url if "/video/" in canonical_url else candidate
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
                    # HDR is shown only when the platform explicitly provides it;
                    # probe-level codec inference is deliberately not user-facing.
                    if platform_hdr := _explicit_platform_hdr(item):
                        video_lines.append(f"画面动态范围：{platform_hdr}")
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
                        media_params = [*video_lines, *audio_lines]
                    media_lines = [f"下载：/bot download {probe_url}"]
            except Exception:  # noqa: BLE001 - 分析失败不影响卡片。
                media_lines = []
        # 视频直发：解析器给出视频直链（小红书 sns-video/Telegram 等）时自动
        # 下载并以视频段随卡片发送；失败/超限/缺 yt-dlp 一律静默降级，
        # 保留「下载：/bot download」提示，绝不阻断卡片。
        video_parts: list[dict] = []
        auto_send_enabled = bool(
            config is not None and getattr(config, "bot_content_video_auto_send", True)
        )
        if (
            video_like
            and not music_like
            and auto_send_enabled
            and downloader is not None
            and getattr(downloader, "available", lambda: False)()
        ):
            direct_video = next(
                (
                    asset
                    for asset in (item.media or [])
                    if asset.asset_type == "video" and asset.url
                ),
                None,
            )
            if direct_video is not None:
                try:
                    outcome = downloader.download(str(direct_video.url))
                    if outcome.error:
                        media_lines = [f"下载：/bot download {direct_video.url!s}"]
                    else:
                        video_parts = [{"file": outcome.path}]
                        size_mb = ""
                        if (
                            outcome.analysis is not None
                            and outcome.analysis.filesize_bytes
                        ):
                            size_mb = (
                                f"（{outcome.analysis.filesize_bytes / 1048576:.1f}MB）"
                            )
                        media_lines = [f"视频已发送 ✓{size_mb}"]
                except Exception:  # noqa: BLE001 - 直发失败不影响卡片。
                    video_parts = []
        body = _render_parse_body(
            item,
            media_params=media_params,
            include_media_params=_is_private_admin(message),
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
                    item_id=item_id,
                    item_kind=item_kind,
                    title=content.title if content else "",
                    url=canonical_url or candidate,
                    parse_depth=parse_depth,
                    body_preview=body,
                )
            except Exception:  # noqa: S110, BLE001 - 历史失败不影响主链路。
                pass
        card_image = _render_card_image(item)
        images: list[dict] = []
        if card_image is not None:
            images.append(card_image)
        elif cover_url:
            images.append({"file": cover_url})
        result = CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.content",
            kind="mixed",
            title=content.title if content else "",
            body=body,
            url=canonical_url or candidate,
            images=images,
            # CQ:music 签名卡在 NapCat 缺 musicSignUrl 时会拒签并中断整条
            # 消息（吞掉后续文本段）；解析卡图已含歌曲信息，这里只留语音/文件。
            audio=[
                part
                for part in _media_parts_from_item(item)
                if isinstance(part, dict) and part.get("type") != "music"
            ],
            video=video_parts,
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=[
                "content_parse",
                f"platform:{match.parser_id}",
                f"parse_depth:{parse_depth}",
                f"item_kind:{item_kind}",
                *(["media_analyzed"] if media_lines else []),
                *(["card_rendered"] if card_image is not None else []),
                *(["video_auto_sent"] if video_parts else []),
            ],
        )
        return result

    return capability
