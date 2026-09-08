from __future__ import annotations

import asyncio
import hashlib
import logging
import shutil
import subprocess
import tempfile
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    DeliveryReceipt,
    OperationalIssue,
    ReceiptState,
    SendRequest,
    new_debug_id,
)
from plugins.bot_unified_runtime.runtime.deadline import (
    DeadlineExceeded,
    apply_request_deadline,
)
from plugins.bot_unified_runtime.sender.timeout import resolve_transport_timeout

logger = logging.getLogger(__name__)

# Telegram sendPhoto 上限 10MB；sendVoice/sendAudio 走分片上传留出安全余量。
_TG_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_TG_MAX_AUDIO_BYTES = 45 * 1024 * 1024
_TG_VOICE_CACHE_DIR = Path(tempfile.gettempdir()) / "bot_tg_voice"


def _telegram_media_parts(content_ref: Any) -> list[dict[str, Any]]:
    parts = content_ref.get("parts", []) if isinstance(content_ref, dict) else []
    if not isinstance(parts, list):
        return []
    return [part for part in parts if isinstance(part, dict)]


def _telegram_photo_reference(parts: list[dict[str, Any]]) -> str:
    """选可发图源：远程直链优先，其次存在的本地渲染卡（适配器原生读本地转 multipart）。"""
    for part in parts:
        if part.get("type") != "image":
            continue
        candidate = str(part.get("file") or part.get("url") or "").strip()
        if not candidate:
            continue
        if candidate.startswith(("http://", "https://")):
            return candidate
        try:
            local = Path(candidate)
            if local.is_file() and 0 < local.stat().st_size <= _TG_MAX_UPLOAD_BYTES:
                return candidate
        except OSError:
            continue
    return ""


def _voice_cache_path(key: str) -> Path:
    digest = hashlib.md5(key.encode("utf-8")).hexdigest()
    return _TG_VOICE_CACHE_DIR / f"{digest}.ogg"


def _convert_audio_to_ogg(source: Path, target: Path) -> bool:
    """sendVoice 仅接受 OGG/OPUS，mp3/flac 直发会被 Telegram 拒收，须 ffmpeg 转码。"""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    try:
        completed = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(source),
                "-vn",
                "-c:a",
                "libopus",
                "-b:a",
                "64k",
                str(target),
            ],
            capture_output=True,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0 and target.is_file() and target.stat().st_size > 0


async def _download_voice_source(url: str, target: Path) -> Path | None:
    try:
        import httpx
    except ImportError:  # pragma: no cover - httpx 随 nonebot 必装
        return None
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0), follow_redirects=True
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.content
        if not payload or len(payload) > _TG_MAX_AUDIO_BYTES:
            return None
        _TG_VOICE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        return target
    except Exception:  # noqa: BLE001 - 下载失败时降级为直链 audio，不阻断发送
        return None


async def _prepare_telegram_voice(raw_ref: str) -> tuple[str, str]:
    """归一化语音源，返回 (引用, 模式)；模式 ∈ {"voice", "audio", "none"}。

    不合规源先经 ffmpeg 落地转 OGG/OPUS；转换不可用时降级 sendAudio
    （mp3 附件仍可直接播放），保证点歌语音在 Telegram 上必有出口。
    """
    ref = (raw_ref or "").strip()
    if not ref:
        return "", "none"
    if ref.startswith(("http://", "https://")):
        if ref.lower().split("?", 1)[0].endswith((".ogg", ".oga")):
            return ref, "voice"
        source = await _download_voice_source(ref, _voice_cache_path(f"{ref}.src"))
        if source is None:
            return ref, "audio"
        target = _voice_cache_path(ref)
        if target.is_file() and target.stat().st_size > 0:
            return str(target), "voice"
        converted = await asyncio.to_thread(_convert_audio_to_ogg, source, target)
        return (str(target), "voice") if converted else (ref, "audio")
    try:
        local = Path(ref)
        if not local.is_file() or not 0 < local.stat().st_size <= _TG_MAX_AUDIO_BYTES:
            return "", "none"
    except OSError:
        return "", "none"
    if local.suffix.lower() in {".ogg", ".oga"}:
        return ref, "voice"
    target = _voice_cache_path(ref)
    if target.is_file() and target.stat().st_size > 0:
        return str(target), "voice"
    converted = await asyncio.to_thread(_convert_audio_to_ogg, local, target)
    return (str(target), "voice") if converted else (ref, "audio")


def _adapter_name(bot: Any) -> str:
    adapter = getattr(bot, "adapter", None)
    get_name = getattr(adapter, "get_name", None)
    if callable(get_name):
        return str(get_name())
    return str(getattr(adapter, "name", ""))


def _provider_message_id(result: Any) -> str | None:
    if isinstance(result, dict):
        value = result.get("message_id") or result.get("id")
    else:
        value = getattr(result, "message_id", None) or getattr(result, "id", None)
    return str(value) if value is not None else None


def _build_mail_reply_message(bot: Any, event: Any, text: str) -> EmailMessage:
    bot_info = getattr(bot, "bot_info", None)
    sender_id = str(getattr(bot_info, "id", "") or getattr(bot, "self_id", "")).strip()
    sender_name = str(getattr(bot_info, "name", "") or "").strip()
    recipient = str(getattr(getattr(event, "sender", None), "id", "")).strip()
    subject = str(getattr(event, "subject", "") or "").strip()
    message_id = str(getattr(event, "id", "") or "").strip()
    if not sender_id or not recipient:
        raise ValueError("mail reply requires sender and recipient addresses")
    message = EmailMessage()
    message["From"] = formataddr((sender_name, sender_id)) if sender_name else sender_id
    message["To"] = recipient
    message["Subject"] = f"Re: {subject}" if subject else "Re:"
    if message_id:
        message["In-Reply-To"] = message_id
        message["References"] = message_id
    message.set_content(text)
    return message


async def send_nonebot_message(
    bot: Any,
    event: Any,
    send_request: SendRequest,
    *,
    timeout_seconds: float | None = None,
) -> DeliveryReceipt:
    """Send a rendered text response through Telegram or Mail safely.

    Rich OneBot output keeps using its dedicated sender. Telegram uses the
    adapter-native ``Bot.send`` API; Mail builds a standards-compliant reply
    message directly because the adapter's default From header is rejected by
    some SMTP servers.
    """

    adapter_name = _adapter_name(bot).strip().lower()
    if adapter_name == "telegram":
        transport = "telegram"
        kwargs: dict[str, object] = {}
    elif adapter_name == "mail":
        transport = "mail.smtp"
        kwargs = {"reply": True}
    elif adapter_name == "console":
        transport = "console"
        kwargs = {}
    else:
        debug_id = new_debug_id()
        return DeliveryReceipt(
            request_id=send_request.request_id,
            state=ReceiptState.FAILED_FINAL,
            transport=adapter_name or "nonebot",
            public_message="",
            debug_id=debug_id,
            operational_issue=OperationalIssue(
                stage="runtime",
                kind="unsupported_adapter",
                retryable=False,
                safe_summary="unsupported_adapter",
                debug_id=debug_id,
            ),
        )

    text = str(send_request.content.text_fallback or "").strip()
    media_parts = _telegram_media_parts(send_request.content.content_ref)
    has_tg_media = adapter_name == "telegram" and any(
        part.get("type") in {"image", "record", "voice", "file", "video"}
        for part in media_parts
    )
    if not text and not has_tg_media:
        return DeliveryReceipt(
            request_id=send_request.request_id,
            state=ReceiptState.SKIPPED,
            transport=transport,
            public_message="",
        )

    async def _send() -> Any:
        parts = media_parts
        # remaining 取代闭包 text：caption 随图发出后置空，避免同一段正文重复发送。
        remaining = text
        files = [part for part in parts if part.get("type") == "file"]
        if files:
            if adapter_name != "telegram":
                raise RuntimeError("file attachments unsupported by this adapter")
            result: Any = None
            for part in files:
                path = Path(str(part.get("file") or ""))
                if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
                    raise ValueError("invalid generated attachment")
                result = await bot.send_document(chat_id=send_request.target_id,
                    document=(path.name, path.read_bytes()), caption=remaining[:1000])
                if not _provider_message_id(result):
                    raise RuntimeError("telegram attachment receipt missing")
            return result
        result = None
        if adapter_name == "telegram":
            # 图文同发：远程直链或本地渲染卡均可作 photo（适配器原生 multipart）。
            photo_ref = _telegram_photo_reference(parts)
            send_photo = getattr(bot, "send_photo", None)
            if photo_ref and callable(send_photo):
                try:
                    if len(remaining) <= 1024:
                        result = await send_photo(
                            chat_id=send_request.target_id,
                            photo=photo_ref,
                            caption=remaining or None,
                        )
                        remaining = ""
                    else:
                        # 超长正文塞 caption 会被 Telegram 截断：图先发，文字单独成条。
                        await send_photo(
                            chat_id=send_request.target_id, photo=photo_ref
                        )
                except Exception:  # noqa: BLE001 - 图片失败降级为纯文本，避免重试重发已成功内容
                    logger.warning(
                        "telegram photo send failed request_id=%s",
                        send_request.request_id,
                    )
            # 语音/音频：sendVoice 仅认 OGG/OPUS，其余经 ffmpeg 转换或降级 audio。
            for part in parts:
                if part.get("type") not in {"record", "voice"}:
                    continue
                voice_ref, voice_mode = await _prepare_telegram_voice(
                    str(part.get("file") or part.get("url") or "")
                )
                if voice_mode == "voice":
                    send_voice = getattr(bot, "send_voice", None)
                    if callable(send_voice):
                        result = await send_voice(
                            chat_id=send_request.target_id, voice=voice_ref
                        )
                elif voice_mode == "audio":
                    send_audio = getattr(bot, "send_audio", None)
                    if callable(send_audio):
                        result = await send_audio(
                            chat_id=send_request.target_id, audio=voice_ref
                        )
            if result is not None and not remaining:
                return result
            if result is None and not remaining and parts:
                raise ValueError("telegram media part is not sendable")
        if event is None:
            send_to = getattr(bot, "send_to", None)
            if not callable(send_to):
                raise RuntimeError("adapter does not expose send_to")
            return await send_to(send_request.target_id, remaining)
        if adapter_name == "mail":
            send_mail = getattr(bot, "send_mail", None)
            if not callable(send_mail):
                raise RuntimeError("mail adapter does not expose send_mail")
            return await send_mail(_build_mail_reply_message(bot, event, remaining))
        return await bot.send(event, remaining, **kwargs)

    timeout = resolve_transport_timeout(timeout_seconds)
    try:
        timeout = apply_request_deadline(
            timeout, getattr(send_request, "deadline_monotonic", None)
        )
    except DeadlineExceeded:
        debug_id = new_debug_id()
        deadline_stage = transport.split(".", 1)[0]
        return DeliveryReceipt(
            request_id=send_request.request_id,
            state=ReceiptState.FAILED_FINAL,
            transport=transport,
            public_message="",
            debug_id=debug_id,
            operational_issue=OperationalIssue(
                stage=deadline_stage
                if deadline_stage in {"telegram", "mail"}
                else "runtime",
                kind="deadline_exceeded",
                retryable=False,
                safe_summary="deadline_exceeded",
                debug_id=debug_id,
            ),
        )
    try:
        result = await asyncio.wait_for(_send(), timeout=timeout)
    except asyncio.TimeoutError:
        debug_id = new_debug_id()
        return DeliveryReceipt(
            request_id=send_request.request_id,
            state=ReceiptState.FAILED_FINAL,
            transport=transport,
            public_message="",
            debug_id=debug_id,
            operational_issue=OperationalIssue(
                stage=transport.split(".", 1)[0]
                if transport.split(".", 1)[0] in {"telegram", "mail"}
                else "runtime",
                kind="result_unknown",
                retryable=False,
                safe_summary="result_unknown",
                debug_id=debug_id,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - adapter errors become typed receipts.
        logger.warning(
            "nonebot transport send failed type=%s request_id=%s transport=%s",
            type(exc).__name__,
            send_request.request_id,
            transport,
        )
        debug_id = new_debug_id()
        stage = transport.split(".", 1)[0]
        return DeliveryReceipt(
            request_id=send_request.request_id,
            state=ReceiptState.FAILED_RETRYABLE,
            transport=transport,
            public_message="",
            debug_id=debug_id,
            operational_issue=OperationalIssue(
                stage=stage if stage in {"telegram", "mail"} else "runtime",
                kind="send_exception",
                retryable=True,
                safe_summary="send_exception",
                debug_id=debug_id,
            ),
        )

    return DeliveryReceipt(
        request_id=send_request.request_id,
        state=ReceiptState.SENT,
        transport=transport,
        provider_message_id=_provider_message_id(result),
        public_message="sent",
    )
