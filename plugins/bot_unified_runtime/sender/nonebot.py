from __future__ import annotations

import asyncio
import logging
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
    if not text:
        return DeliveryReceipt(
            request_id=send_request.request_id,
            state=ReceiptState.SKIPPED,
            transport=transport,
            public_message="",
        )

    async def _send() -> Any:
        parts = send_request.content.content_ref.get("parts", [])
        files = [p for p in parts if isinstance(p, dict) and p.get("type") == "file"] if isinstance(parts, list) else []
        if files:
            if adapter_name != "telegram":
                raise RuntimeError("file attachments unsupported by this adapter")
            for part in files:
                path = Path(str(part.get("file") or ""))
                if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
                    raise ValueError("invalid generated attachment")
                result = await bot.send_document(chat_id=send_request.target_id,
                    document=(path.name, path.read_bytes()), caption=text[:1000])
                if not _provider_message_id(result):
                    raise RuntimeError("telegram attachment receipt missing")
            return result
        # Telegram 支持图文同发：有图片时用 send_photo + caption（文字作说明）。
        if adapter_name == "telegram":
            images = [
                p
                for p in (parts if isinstance(parts, list) else [])
                if isinstance(p, dict) and p.get("type") == "image"
            ]
            photo_url = ""
            for image in images:
                candidate = str(image.get("file") or image.get("url") or "")
                if candidate.startswith(("http://", "https://")):
                    photo_url = candidate
                    break
            send_photo = getattr(bot, "send_photo", None)
            if photo_url and callable(send_photo):
                chat_id = send_request.target_id
                return await send_photo(
                    chat_id=chat_id, photo=photo_url, caption=text[:1024]
                )
        if event is None:
            send_to = getattr(bot, "send_to", None)
            if not callable(send_to):
                raise RuntimeError("adapter does not expose send_to")
            return await send_to(send_request.target_id, text)
        if adapter_name == "mail":
            send_mail = getattr(bot, "send_mail", None)
            if not callable(send_mail):
                raise RuntimeError("mail adapter does not expose send_mail")
            return await send_mail(_build_mail_reply_message(bot, event, text))
        return await bot.send(event, text, **kwargs)

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
