"""点歌能力（bot.music）：『点歌 <关键词>』按平台顺序搜索并渲染。

- 纯接口搜索，不调用 LLM；每个平台拿第一名，失败自动换下一个。
- 输出模式可切换：card=卡片（默认）、voice=语音、audio=音频文件、link=链接。
- 模式通过 `点歌模式 <音频|语音|链接|卡片>` 设置，管理员专用。
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Callable

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
    SendPolicy,
    new_request_id,
)
from plugins.bot_unified_runtime.sources.parsers import (
    build_cookie_provider,
    music_search_providers,
)

_COMMAND_RE = re.compile(r"^[/!！]?点歌\s*(?P<query>.+)$")
_MODE_COMMAND_RE = re.compile(
    r"^[/!！]?点歌模式(?:\s+(?P<mode>.+))?$", re.IGNORECASE
)

_MODE_ALIASES = {
    "audio": "audio",
    "file": "audio",
    "音频": "audio",
    "音频文件": "audio",
    "voice": "voice",
    "语音": "voice",
    "link": "link",
    "链接": "link",
    "card": "card",
    "卡片": "card",
    "default": "card",
    "默认": "card",
}
_MODE_LABELS = {
    "audio": "发送音频文件",
    "voice": "发语音",
    "link": "发链接",
    "card": "发卡片",
}


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


def is_music_mode_command(text: str) -> bool:
    return _MODE_COMMAND_RE.match(text.strip()) is not None


def normalize_music_mode(value: str) -> str | None:
    return _MODE_ALIASES.get((value or "").strip().lower())


def extract_music_mode(text: str) -> str | None:
    match = _MODE_COMMAND_RE.match(text.strip())
    if not match:
        return None
    raw = (match.group("mode") or "").strip()
    if not raw:
        return None
    return normalize_music_mode(raw)


def _music_card_parts(item: Any) -> list[dict]:
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


def _media_parts_for_mode(
    item: Any,
    mode: str,
    audio_downloader: Callable[[str], str | None] | None = None,
) -> list[dict]:
    """按输出模式组装 OneBot 媒体部分。"""
    normalized = normalize_music_mode(mode) or "card"
    if normalized == "link":
        return []
    if normalized == "audio":
        if item.audio_url and audio_downloader is not None:
            local_path = audio_downloader(item.audio_url)
            if local_path:
                return [{"type": "file", "file": str(local_path)}]
        if item.audio_url:
            return [{"type": "record", "file": item.audio_url}]
        return _music_card_parts(item)
    # voice / card / default：优先语音直链，其次平台音乐卡片。
    if item.audio_url:
        return [{"type": "record", "file": item.audio_url}]
    return _music_card_parts(item)



def _media_parts_from_item(item: Any) -> list[dict]:
    """兼容内容解析能力：按默认卡片模式取媒体部分。"""
    return _media_parts_for_mode(item, "card")


def _render_music_body(item: Any, mode: str) -> str:
    normalized = normalize_music_mode(mode) or "card"
    lines = [f"♪ {item.title}"]
    if item.author_name:
        lines.append(f"歌手：{item.author_name}")
    if normalized == "link":
        if item.canonical_url:
            lines.append(f"链接：{item.canonical_url}")
        return "\n".join(lines)
    if item.summary:
        lines.append(item.summary)
    parts = _media_parts_for_mode(item, normalized)
    if parts:
        first_type = parts[0].get("type")
        if first_type == "file":
            lines.append("（已下载音频文件，随后发送；失败则只有文字和链接）")
        elif first_type == "record":
            lines.append("（语音片段随后发出，没声音说明试听链接被平台拦了）")
        else:
            lines.append("（已附带平台音乐卡片）")
    if item.canonical_url:
        lines.append(f"链接：{item.canonical_url}")
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
            return str(path)
        except Exception:  # noqa: BLE001
            return None

    return download


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
        current = store.get("BOT_MUSIC_MODE", config) if store is not None else "card"
        current = normalize_music_mode(str(current)) or "card"
        return CapabilityResult(
            request_id=request_id,
            capability_id="bot.music_mode",
            kind="text",
            title="点歌模式",
            body=(
                f"当前点歌模式：{_MODE_LABELS[current]}。\n"
                "用法：点歌模式 <音频|语音|链接|卡片>"
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
            body="可选模式：音频 / 语音 / 链接 / 卡片。",
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
        body=f"点歌模式已设为：{_MODE_LABELS[normalized]}。",
        risk_level=RiskLevel.LOW,
        privacy_level=PrivacyLevel.PERSONAL,
        send_policy=SendPolicy.IMMEDIATE,
        audit_tags=["music_mode", f"music_mode:{normalized}"],
    )


def build_music_capability(
    config: Any | None = None,
    *,
    providers: list[Any] | None = None,
    default_mode: str = "card",
    audio_downloader: Callable[[str], str | None] | None = None,
) -> Any:
    """构建 bot.music 能力；providers 为空时按 config 平台名单构建。"""
    if providers is None:
        platforms = getattr(config, "bot_music_platforms", []) or [] if config else []
        providers = music_search_providers(
            platforms or None,
            cookie_provider=build_cookie_provider(config) if config else None,
        )
    if audio_downloader is None:
        audio_downloader = _default_audio_downloader(config)
    mode = normalize_music_mode(str(default_mode)) or "card"

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
            body = _render_music_body(item, mode)
            audio = _media_parts_for_mode(item, mode, audio_downloader=audio_downloader)
            images = [] if mode == "link" else (
                [{"file": item.cover_url}] if item.cover_url else []
            )
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.music",
                kind="mixed" if (audio or images) else "text",
                title=item.title,
                body=body,
                url=item.canonical_url or None,
                images=images,
                audio=audio,
                risk_level=RiskLevel.LOW,
                privacy_level=PrivacyLevel.PUBLIC,
                audit_tags=[
                    "music_request",
                    f"music_source:{parser_id}",
                    f"music_mode:{mode}",
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