"""点歌能力（bot.music）：『点歌 <关键词>』按平台顺序搜索并渲染。

- 纯接口搜索，不调用 LLM；每个平台拿第一名，失败自动换下一个。
- 输出模式可切换：card=卡片（默认）、voice=语音、audio=音频文件、link=链接。
- 模式通过 `点歌模式 <音频|语音|链接|卡片>` 设置，管理员专用。
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

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


def _music_card_parts(item: Any) -> list[dict]:
    stats = getattr(item, "stats", None) or {}
    if not isinstance(stats, dict):
        return []
    music_card = stats.get("music_card")
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
    """按部件组合组装 OneBot 媒体部分：voice/file/card。"""
    parts = parse_music_mode_spec(mode) or DEFAULT_PARTS
    out: list[dict] = []
    if item.audio_url and (("voice" in parts) or ("file" in parts)):
        local_path = (
            audio_downloader(item.audio_url)
            if audio_downloader is not None
            else None
        )
        if "voice" in parts:
            out.append({"type": "record", "file": str(local_path) if local_path else item.audio_url})
        if "file" in parts:
            out.append({"type": "file", "file": str(local_path) if local_path else item.audio_url})
    if "card" in parts:
        out.extend(_music_card_parts(item))
    return out


def _media_parts_from_item(item: Any) -> list[dict]:
    """兼容内容解析能力：默认卡片+语音+链接。"""
    return _media_parts_for_mode(item, "card+voice+link")


def _render_music_body(item: Any, mode: str) -> str:
    parts = parse_music_mode_spec(mode) or DEFAULT_PARTS
    lines = [f"♪ {item.title}"]
    if item.author_name:
        lines.append(f"歌手：{item.author_name}")
    if item.summary:
        lines.append(item.summary)
    if "link" in parts and item.canonical_url:
        lines.append(f"链接：{item.canonical_url}")
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


def build_music_capability(
    config: Any | None = None,
    *,
    providers: list[Any] | None = None,
    default_mode: str = "card+voice+link",
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
    mode = normalize_music_mode(str(default_mode)) or _canonical_mode(DEFAULT_PARTS)

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
            parts = parse_music_mode_spec(mode) or DEFAULT_PARTS
            has_music_card = bool(_music_card_parts(item))
            images = (
                [{"file": item.cover_url}]
                if "card" in parts and not has_music_card and item.cover_url
                else []
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