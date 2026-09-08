"""点歌能力（bot.music）：『点歌 <关键词>』按平台顺序搜索并渲染。

- 纯接口搜索，不调用 LLM；每个平台拿第一名，失败自动换下一个。
- 输出模式可切换：card=卡片（默认）、voice=语音、audio=音频文件、link=链接。
- 模式通过 `点歌模式 <音频|语音|链接|卡片>` 设置，管理员专用。
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    MusicContributor,
    MusicRequestEvent,
    MusicTrack,
    PrivacyLevel,
    RiskLevel,
    SendPolicy,
    new_request_id,
)
from plugins.bot_unified_runtime.sources.parsers import (
    build_cookie_provider,
    music_search_providers,
)

_LOGGER = logging.getLogger(__name__)

_COMMAND_RE = re.compile(
    r"^[/!！]?(?:点歌|點歌|music|song)\s*(?P<query>.+)$", re.IGNORECASE
)
_MODE_COMMAND_RE = re.compile(
    r"^[/!！]?(?:点歌模式|點歌模式|music mode|music-mode|song mode)"
    r"(?:\s+(?P<mode>.+))?$",
    re.IGNORECASE,
)

# 输出部件：card=平台音乐卡片（无卡信息则封面图），voice=语音，
# file=音频文件，link=文本链接。
_MODE_PART_ALIASES = {
    "card": "card", "musiccard": "card", "卡片": "card", "音樂卡片": "card", "音乐卡片": "card",
    "voice": "voice", "语音": "voice", "語音": "voice", "record": "voice",
    "audio": "file", "file": "file", "音频": "file", "音频文件": "file",
    "音頻": "file", "音訊": "file", "音訊檔案": "file", "音檔": "file",
    "link": "link", "链接": "link", "連結": "link", "鏈接": "link", "url": "link",
}
PART_LABELS = {
    "card": "卡片",
    "voice": "语音",
    "file": "音频文件",
    "link": "链接",
}
ALL_PARTS = frozenset({"card", "voice", "link"})
# 兼容旧值：旧“card”= 卡片 + 语音 + 链接。
DEFAULT_PARTS = frozenset({"card", "voice", "link"})
_MODE_SPLIT_RE = re.compile(r"[\s+＋&,，、/]|and|plus|和|与|跟|加|及", re.IGNORECASE)


def parse_music_mode_spec(value: str) -> frozenset[str] | None:
    """把“卡片和语音 / card+voice / 只发链接”解析成部件集合；非法返回 None。"""
    raw = (value or "").strip().lower()
    if not raw:
        return None
    raw = raw.replace("只发", "").replace("仅发", "").replace("只", "").replace("仅", "")
    raw = raw.replace("发送", "").replace("输出", "").replace("用", "")
    tokens = [token for token in _MODE_SPLIT_RE.split(raw) if token]
    if not tokens:
        return None
    parts: set[str] = set()
    for token in tokens:
        if token in {"全部", "所有", "all", "everything"}:
            parts |= ALL_PARTS
            continue
        part = _MODE_PART_ALIASES.get(token)
        if part is None:
            return None
        parts.add(part)
    return frozenset(parts) if parts else None


def _canonical_mode(parts: frozenset[str]) -> str:
    return "+".join(sorted(parts))


def normalize_music_mode(value: str) -> str | None:
    """归一化模式字符串；兼容旧单值（card/voice/audio/link）。"""
    raw = (value or "").strip()
    if not raw:
        return None
    parts = parse_music_mode_spec(raw)
    if parts is None:
        # 旧英文/中文单值兼容
        legacy = {
            "audio": {"file"}, "音频": {"file"}, "voice": {"voice"}, "语音": {"voice"},
            "link": {"link"}, "链接": {"link"}, "card": DEFAULT_PARTS, "卡片": DEFAULT_PARTS,
            "default": DEFAULT_PARTS, "默认": DEFAULT_PARTS,
        }
        parts = cast(frozenset[str] | None, legacy.get(raw.lower()))
    if parts is None:
        return None
    return _canonical_mode(parts)


def is_music_command(text: str) -> bool:
    match = _COMMAND_RE.match(text.strip())
    if match is None:
        return False
    query = (match.group("query") or "").strip()
    # “点歌 只发卡片”这类是模式设置，不是点歌。
    if parse_music_mode_spec(query) is not None:
        return False
    return bool(query)


def extract_music_query(text: str) -> str:
    match = _COMMAND_RE.match(text.strip())
    if not match:
        raise ValueError("not a music command")
    query = match.group("query").strip()
    if not query:
        raise ValueError("empty music query")
    return query


def is_music_mode_command(text: str) -> bool:
    return _MODE_COMMAND_RE.match(text.strip()) is not None


def extract_music_mode(text: str) -> str | None:
    match = _MODE_COMMAND_RE.match(text.strip())
    if not match:
        return None
    raw = (match.group("mode") or "").strip()
    if not raw:
        return None
    return normalize_music_mode(raw)


def _music_track_from_item(item: Any, provider: str) -> MusicTrack:
    existing = getattr(item, "music", None)
    if isinstance(existing, MusicTrack):
        return existing
    artist_names = [
        value.strip()
        for value in str(getattr(item, "author_name", "") or "").split("、")
        if value.strip()
    ]
    return MusicTrack(
        provider=provider,
        provider_track_id=str(getattr(item, "item_id", "") or getattr(item, "title", "")),
        title=str(getattr(item, "title", "") or "未知歌曲"),
        contributors=[
            MusicContributor(name=name, roles=["performer"])
            for name in artist_names
        ],
        artwork_url=str(getattr(item, "cover_url", "") or "") or None,
        audio_url=str(getattr(item, "audio_url", "") or "") or None,
    )


def _record_music_request(
    store: Any,
    message: IncomingMessage,
    item: Any,
    provider: str,
) -> None:
    if store is None:
        return
    track = _music_track_from_item(item, provider)
    canonical_id = store.upsert_track(track)
    scope = getattr(getattr(message, "session_type", None), "value", "unknown")
    store.record_successful_request(
        MusicRequestEvent(
            request_id=message.request_id,
            canonical_track_id=canonical_id,
            provider=track.provider,
            provider_track_id=track.provider_track_id,
            session_scope=str(scope),
            requested_at=datetime.now(timezone.utc),
        )
    )


def _music_card_parts(item: Any) -> list[dict]:
    engagement = getattr(item, "engagement", None)
    extras = getattr(engagement, "platform_extra", None) or {}
    music_card = extras.get("music_card")
    if isinstance(music_card, dict) and music_card.get("type") and music_card.get("id"):
        return [
            {
                "type": "music",
                "music_type": str(music_card["type"]),
                "music_id": str(music_card["id"]),
            }
        ]
    return []


def music_audio_url(item: Any) -> str:
    """音频直链：music.audio_url 优先，其次媒体 audio 资产。"""
    if item.music is not None and item.music.audio_url:
        return str(item.music.audio_url)
    audio_asset = next(
        (asset for asset in (item.media or []) if asset.asset_type == "audio"),
        None,
    )
    return str(audio_asset.url or "") if audio_asset is not None else ""


def music_cover_url(item: Any) -> str:
    """封面直链：解析器指定封面优先，其次首张图片资产。"""
    from plugins.bot_unified_runtime.contracts.media import parsed_cover_url

    return parsed_cover_url(item)


def _media_parts_for_mode(
    item: Any,
    mode: str,
    audio_downloader: Callable[[str], str | None] | None = None,
) -> list[dict]:
    """按部件组合组装 OneBot 媒体部分：voice/file/card。"""
    parts = parse_music_mode_spec(mode) or DEFAULT_PARTS
    out: list[dict] = []
    audio_url = music_audio_url(item)
    if audio_url and (("voice" in parts) or ("file" in parts)):
        local_path = (
            audio_downloader(audio_url)
            if audio_downloader is not None
            else None
        )
        if "voice" in parts:
            out.append({"type": "record", "file": str(local_path) if local_path else audio_url})
        if "file" in parts:
            out.append({"type": "file", "file": str(local_path) if local_path else audio_url})
    if "card" in parts:
        out.extend(_music_card_parts(item))
    return out


def _media_parts_from_item(item: Any) -> list[dict]:
    """兼容内容解析能力：默认卡片+语音+链接。"""
    return _media_parts_for_mode(item, "card+voice+link")


def _render_music_body(item: Any, mode: str) -> str:
    parts = parse_music_mode_spec(mode) or DEFAULT_PARTS
    identity = item.identity
    content = item.content
    creator = item.creator
    lines = [f"♪ {content.title if content else ''}"]
    if creator is not None and creator.name:
        lines.append(f"歌手：{creator.name}")
    if content is not None and content.summary:
        lines.append(content.summary)
    if "link" in parts and identity is not None and identity.canonical_url:
        lines.append(f"链接：{identity.canonical_url}")
    if "file" in parts:
        lines.append("（音频文件随后发送；下载失败则只有文字）")
    elif "voice" in parts:
        lines.append("（语音片段随后发出，没声音说明试听链接被平台拦了）")
    if "card" in parts and not _music_card_parts(item):
        lines.append("（该平台未提供音乐卡片，已用封面替代）")
    return "\n".join(lines)


def _default_audio_downloader(config: Any | None = None) -> Callable[[str], str | None]:
    """把试听直链下载到 data/music/；失败返回 None，不抛异常。"""
    target_dir = Path(
        str(getattr(config, "bot_music_dir", "") or "data/music")
    ).expanduser()
    max_bytes = int(getattr(config, "bot_download_max_bytes", 209715200) or 0)
    timeout_seconds = float(getattr(config, "bot_download_timeout_seconds", 60) or 60)
    proxy = str(getattr(config, "bot_download_proxy", "") or "")
    cookie_header = ""
    if config is not None:
        try:
            cookie_header = build_cookie_provider(config).cookie_header("netease_music")
        except Exception:  # noqa: BLE001
            cookie_header = ""

    def download(url: str) -> str | None:
        if not url:
            return None
        try:
            import httpx
        except Exception:  # noqa: BLE001
            return None
        try:
            headers = {"user-agent": "Mozilla/5.0"} if not cookie_header else {
                "user-agent": "Mozilla/5.0",
                "cookie": cookie_header,
            }
            kwargs: dict[str, Any] = {
                "headers": headers,
                "follow_redirects": True,
                "timeout": timeout_seconds,
            }
            if proxy:
                kwargs["proxy"] = proxy
            response = httpx.get(url, **kwargs)
            response.raise_for_status()
            payload = response.content
            if max_bytes > 0 and len(payload) > max_bytes:
                return None
            target_dir.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
            suffix = ".mp3"
            content_type = response.headers.get("content-type", "")
            if "m4a" in content_type:
                suffix = ".m4a"
            elif "flac" in content_type:
                suffix = ".flac"
            path = target_dir / f"song_{digest}{suffix}"
            path.write_bytes(payload)
            try:
                from plugins.bot_unified_runtime.runtime.cache_policy import (
                    enforce_quota,
                )

                enforce_quota(
                    target_dir,
                    max_bytes=int(getattr(config, "bot_music_cache_max_bytes", 0) or 0),
                )
            except Exception:  # noqa: S110, BLE001 - 缓存配额清理失败不影响主链路。
                pass
            return str(path)
        except Exception:  # noqa: BLE001
            return None

    return download


def _mode_labels_text(mode: str) -> str:
    parts = parse_music_mode_spec(mode) or DEFAULT_PARTS
    return "、".join(PART_LABELS[part] for part in sorted(parts))


def build_music_mode_result(
    store: Any,
    config: Any,
    *,
    mode: str | None,
    actor_roles: list[str],
    request_id: str | None = None,
) -> CapabilityResult:
    """读取/设置 `BOT_MUSIC_MODE`；只允许管理员修改。"""
    request_id = request_id or new_request_id("music_mode")
    normalized_roles = {str(role).strip().lower() for role in (actor_roles or [])}
    if "admin" not in normalized_roles:
        return CapabilityResult(
            request_id=request_id,
            capability_id="bot.music_mode",
            kind="text",
            title="点歌模式",
            body="只有管理员才能修改点歌输出模式。",
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PERSONAL,
            send_policy=SendPolicy.IMMEDIATE,
            audit_tags=["music_mode", "music_mode_denied"],
        )
    if not mode:
        current = store.get("BOT_MUSIC_MODE", config) if store is not None else "card+voice+link"
        current = normalize_music_mode(str(current)) or "card+voice+link"
        if current == "card":
            # 兼容旧版本单值“card”：历史上等于 卡片+语音+链接。
            current = _canonical_mode(DEFAULT_PARTS)
        return CapabilityResult(
            request_id=request_id,
            capability_id="bot.music_mode",
            kind="text",
            title="点歌模式",
            body=(
                f"当前点歌模式：{_mode_labels_text(current)}。\n"
                "用法：点歌模式 <卡片|语音|音频文件|链接 的任意组合>\n"
                "例如：点歌模式 卡片和语音 / 点歌模式 只发链接 / "
                "music mode card+link"
            ),
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PERSONAL,
            send_policy=SendPolicy.IMMEDIATE,
            audit_tags=["music_mode", f"music_mode:{current}"],
        )
    normalized = normalize_music_mode(mode)
    if normalized is None:
        return CapabilityResult(
            request_id=request_id,
            capability_id="bot.music_mode",
            kind="text",
            title="点歌模式",
            body="可选部件：卡片 / 语音 / 音频文件 / 链接，可任意组合。",
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PERSONAL,
            send_policy=SendPolicy.IMMEDIATE,
            audit_tags=["music_mode", "music_mode_invalid"],
        )
    if store is not None:
        store.set_override("BOT_MUSIC_MODE", normalized)
    return CapabilityResult(
        request_id=request_id,
        capability_id="bot.music_mode",
        kind="text",
        title="点歌模式",
        body=f"点歌模式已设为：{_mode_labels_text(normalized)}。",
        risk_level=RiskLevel.LOW,
        privacy_level=PrivacyLevel.PERSONAL,
        send_policy=SendPolicy.IMMEDIATE,
        audit_tags=["music_mode", f"music_mode:{normalized}"],
    )


# 多候选点歌（借鉴 multincm 编号选择交互）：会话 -> (过期时刻, provider_id, 候选列表)。
_CANDIDATE_SESSIONS: dict[str, tuple[float, str, list[dict[str, str]]]] = {}
_CANDIDATE_MAX_SESSIONS = 256


def clear_music_candidate_sessions() -> None:
    """清空多候选点歌会话状态（测试与运维用）。"""
    _CANDIDATE_SESSIONS.clear()


def _prune_candidate_sessions(now: float) -> None:
    expired = [key for key, (expires, _pid, _c) in _CANDIDATE_SESSIONS.items() if expires <= now]
    for key in expired:
        _CANDIDATE_SESSIONS.pop(key, None)
    while len(_CANDIDATE_SESSIONS) > _CANDIDATE_MAX_SESSIONS:
        oldest = next(iter(_CANDIDATE_SESSIONS))
        _CANDIDATE_SESSIONS.pop(oldest, None)


def build_music_capability(
    config: Any | None = None,
    *,
    providers: list[Any] | None = None,
    default_mode: str = "card+voice+link",
    audio_downloader: Callable[[str], str | None] | None = None,
    request_store: Any | None = None,
    candidate_providers: dict[str, tuple[Callable[..., Any], Callable[..., Any]]] | None = None,
    clock: Callable[[], float] | None = None,
) -> Any:
    """构建 bot.music 能力；providers 为空时按 config 平台名单构建。

    candidate_providers：平台 id -> (候选列表函数, 按 ID 详情函数)。
    启用后（BOT_MUSIC_CANDIDATES_ENABLED）同名歧义返回编号列表，
    用户回复『点歌 <编号>』在有效期内完成二次选择。
    """
    if providers is None:
        platforms = getattr(config, "bot_music_platforms", []) or [] if config else []
        providers = music_search_providers(
            platforms or None,
            cookie_provider=build_cookie_provider(config) if config else None,
        )
    if audio_downloader is None:
        audio_downloader = _default_audio_downloader(config)
    mode = normalize_music_mode(str(default_mode)) or _canonical_mode(DEFAULT_PARTS)
    candidates_enabled = bool(getattr(config, "bot_music_candidates_enabled", False)) and bool(
        candidate_providers
    )
    candidates_ttl = max(
        30.0, float(getattr(config, "bot_music_candidates_ttl_seconds", 300) or 300)
    )
    candidates_limit = max(2, int(getattr(config, "bot_music_candidates_limit", 5) or 5))
    now = clock or time.monotonic

    def _render_hit(
        item: Any,
        parser_id: str,
        message: IncomingMessage,
        extra_tags: list[str],
    ) -> CapabilityResult:
        try:
            _record_music_request(request_store, message, item, parser_id)
        except Exception:
            _LOGGER.debug("music analytics write failed", exc_info=True)
        body = _render_music_body(item, mode)
        audio = _media_parts_for_mode(item, mode, audio_downloader=audio_downloader)
        parts = parse_music_mode_spec(mode) or DEFAULT_PARTS
        has_music_card = bool(_music_card_parts(item))
        cover_url = music_cover_url(item)
        images = (
            [{"file": cover_url}]
            if "card" in parts and not has_music_card and cover_url
            else []
        )
        identity = item.identity
        content = item.content
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.music",
            kind="mixed" if (audio or images) else "text",
            title=content.title if content else "",
            body=body,
            url=(identity.canonical_url if identity else "") or None,
            images=images,
            audio=audio,
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=[
                "music_request",
                f"music_source:{parser_id}",
                f"music_mode:{mode}",
                *extra_tags,
            ],
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
        session_key = f"{message.session_type.value}:{message.session_id}"
        # 二次选择路径：『点歌 <编号>』命中未过期的候选列表。
        if candidates_enabled and query.isdigit():
            _prune_candidate_sessions(now())
            stored = _CANDIDATE_SESSIONS.get(session_key)
            if stored is not None:
                _expires, parser_id, cands = stored
                index = int(query) - 1
                if 0 <= index < len(cands):
                    picked = cands[index]
                    detail_fn = candidate_providers[parser_id][1]  # type: ignore[index]
                    try:
                        # detail_fn 接收完整候选 dict（部分平台可直接从候选构建），
                        # 并附带原查询词以便需要重搜的平台使用。
                        item = detail_fn(picked, query=query)
                    except Exception:  # noqa: BLE001 - 详情失败按未找到降级。
                        item = None
                    if item is not None:
                        _CANDIDATE_SESSIONS.pop(session_key, None)
                        return _render_hit(
                            item,
                            parser_id,
                            message,
                            [f"query:{query[:20]}", "music_candidate_pick"],
                        )
        for parser_id, display_name, search_fn in providers:
            candidate_pair = (candidate_providers or {}).get(parser_id)
            # 编号选择意图（无会话/已过期）不再触发新候选列表，直接走普通搜索。
            if candidates_enabled and not query.isdigit() and candidate_pair is not None:
                list_fn, _detail_fn = candidate_pair
                try:
                    cands = list_fn(query)[:candidates_limit]
                except Exception:  # noqa: BLE001 - 候选失败回退普通单结果路径。
                    cands = []
                exact_hits = [
                    cand
                    for cand in cands
                    if cand.get("name", "").strip() == query.strip()
                ]
                if len(cands) >= 2 and not exact_hits:
                    lines = [
                        f"{index}. {cand['name']}"
                        + (f" - {cand['artist']}" if cand.get("artist") else "")
                        for index, cand in enumerate(cands, start=1)
                    ]
                    _CANDIDATE_SESSIONS[session_key] = (
                        now() + candidates_ttl,
                        parser_id,
                        cands,
                    )
                    _prune_candidate_sessions(now())
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.music",
                        kind="text",
                        body=(
                            f"为你找到多首「{query}」相关歌曲，回复编号直接点：\n"
                            + "\n".join(lines)
                            + f"\n（{int(candidates_ttl)} 秒内有效）"
                        ),
                        audit_tags=[
                            "music_request",
                            f"music_source:{parser_id}",
                            f"music_mode:{mode}",
                            f"query:{query[:20]}",
                            "music_candidates",
                        ],
                    )
            try:
                item = search_fn(query)
            except Exception:  # noqa: BLE001 - 单平台失败换下一个。
                item = None
            if item is None:
                continue
            return _render_hit(item, parser_id, message, [f"query:{query[:20]}"])
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.music",
            kind="text",
            body=f"没有找到『{query}』，换个关键词或歌手名再试试？",
            audit_tags=["music_request", "music_not_found"],
        )

    return capability