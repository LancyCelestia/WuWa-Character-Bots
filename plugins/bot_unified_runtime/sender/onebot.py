from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from plugins.bot_unified_runtime.audit import redact_private_debug
from plugins.bot_unified_runtime.contracts import (
    DeliveryReceipt,
    ReceiptState,
    SendRequest,
    SessionType,
    new_debug_id,
)

ONEBOT_V11_TRANSPORT = "onebot.v11"
OneBotMessageSegment = dict[str, Any]
_FORWARD_API_UNAVAILABLE = object()


class OneBotV11Bot(Protocol):
    async def send_private_msg(
        self,
        *,
        user_id: int | str,
        message: list[OneBotMessageSegment],
    ) -> Any: ...

    async def send_group_msg(
        self,
        *,
        group_id: int | str,
        message: list[OneBotMessageSegment],
    ) -> Any: ...


def _coerce_onebot_id(value: str) -> int | str:
    stripped = value.strip()
    if stripped.isdecimal():
        return int(stripped)
    return stripped


def _extract_message_id(result: Any) -> str | None:
    if isinstance(result, dict):
        message_id = result.get("message_id")
        if message_id is not None:
            return str(message_id)
        data = result.get("data")
        if isinstance(data, dict):
            nested_message_id = data.get("message_id")
            if nested_message_id is not None:
                return str(nested_message_id)
    message_id = getattr(result, "message_id", None)
    if message_id is not None:
        return str(message_id)
    return None


def _extract_onebot_retcode(result: Any) -> int | None:
    if isinstance(result, dict):
        raw_retcode = result.get("retcode")
    else:
        raw_retcode = getattr(result, "retcode", None)
    if isinstance(raw_retcode, int):
        return raw_retcode
    if isinstance(raw_retcode, str) and raw_retcode.strip().lstrip("-").isdigit():
        return int(raw_retcode)
    return None


def _extract_onebot_status(result: Any) -> str:
    if isinstance(result, dict):
        raw_status = result.get("status")
    else:
        raw_status = getattr(result, "status", None)
    return _string_value(raw_status).strip().lower()


def _onebot_result_is_success(result: Any) -> bool:
    status = _extract_onebot_status(result)
    retcode = _extract_onebot_retcode(result)
    if status in {"failed", "fail", "error"}:
        return False
    return retcode is None or retcode == 0


def _is_final_failure_retcode(retcode: int | None) -> bool:
    if retcode is None:
        return False
    return retcode in {403, 404, 1003, 1200, 1201, 1401, 1403, 1404}


def _safe_onebot_failure_message(result: Any, debug_id: str) -> str:
    retcode = _extract_onebot_retcode(result)
    status = _extract_onebot_status(result)
    parts = ["OneBot V11 发送失败"]
    if retcode is not None:
        parts.append(f"retcode={retcode}")
    if status:
        parts.append(f"status={status}")
    parts.append(f"debug_id={debug_id}")
    return "，".join(parts)


def build_onebot_message_segments(send_request: SendRequest) -> list[OneBotMessageSegment]:
    content = send_request.content
    segments = _segments_from_rendered_output(
        content_type=content.content_type,
        content_ref=content.content_ref,
        text_fallback=content.text_fallback,
    )
    return segments or [_text_segment(content.text_fallback)]


def _forward_messages(send_request: SendRequest) -> list[OneBotMessageSegment]:
    if send_request.content.content_type.strip().lower() != "forward":
        return []
    if not send_request.allow_forward:
        return []
    raw_messages = send_request.content.content_ref.get("messages")
    if raw_messages is None:
        raw_messages = send_request.content.content_ref.get("nodes")
    if not isinstance(raw_messages, list):
        return []
    return [message for message in raw_messages if isinstance(message, dict)]


def _segments_from_rendered_output(
    *,
    content_type: str,
    content_ref: dict[str, Any],
    text_fallback: str,
) -> list[OneBotMessageSegment]:
    normalized_type = content_type.strip().lower()
    if normalized_type == "text":
        return [_text_segment(_string_value(content_ref.get("text")) or text_fallback)]
    if normalized_type == "image":
        image_segment = _image_segment(content_ref)
        return [image_segment] if image_segment else [_text_segment(text_fallback)]
    if normalized_type == "card":
        card_segment = _json_card_segment(content_ref)
        return [card_segment] if card_segment else [_text_segment(text_fallback)]
    if normalized_type == "mixed":
        return _mixed_segments(content_ref, text_fallback=text_fallback)
    return [_text_segment(text_fallback)]


def _mixed_segments(
    content_ref: dict[str, Any],
    *,
    text_fallback: str,
) -> list[OneBotMessageSegment]:
    parts = content_ref.get("parts")
    if not isinstance(parts, list):
        return [_text_segment(text_fallback)]
    segments: list[OneBotMessageSegment] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        segment = _segment_from_mixed_part(part)
        if segment is not None:
            segments.append(segment)
    return segments or [_text_segment(text_fallback)]


def _segment_from_mixed_part(part: dict[str, Any]) -> OneBotMessageSegment | None:
    part_type = _string_value(part.get("type")).strip().lower()
    if part_type == "text":
        text = _string_value(part.get("text")) or _string_value(part.get("content"))
        return _text_segment(text) if text else None
    if part_type == "image":
        return _image_segment(part)
    if part_type == "card":
        return _json_card_segment(part)
    if part_type == "record":
        file_ref = _string_value(part.get("file")) or _string_value(part.get("url"))
        if not file_ref:
            return None
        file_ref = _resolve_local_file_ref(file_ref)
        return {"type": "record", "data": {"file": file_ref}}
    if part_type == "video":
        file_ref = _string_value(part.get("file")) or _string_value(part.get("url"))
        if not file_ref:
            return None
        file_ref = _resolve_local_file_ref(file_ref)
        data: dict[str, Any] = {"file": file_ref}
        for key in ("cover", "thumb"):
            if part.get(key):
                data[key] = _string_value(part.get(key))
        return {"type": "video", "data": data}
    if part_type == "file":
        file_ref = _string_value(part.get("file")) or _string_value(part.get("url"))
        if not file_ref:
            return None
        file_ref = _resolve_local_file_ref(file_ref)
        return {"type": "file", "data": {"file": file_ref}}
    if part_type == "music":
        # CQ:music 卡片：{"type":"qq","id":"..."} 或 {"type":"163","id":"..."}
        music_type = _string_value(part.get("music_type"))
        music_id = _string_value(part.get("music_id"))
        if music_type and music_id:
            return {"type": "music", "data": {"type": music_type, "id": music_id}}
        return None
    return None


def _text_segment(text: str) -> OneBotMessageSegment:
    return {"type": "text", "data": {"text": text}}


def _resolve_local_file_ref(file_ref: str) -> str:
    if not file_ref:
        return file_ref
    if file_ref.startswith(("http://", "https://", "file://", "base64://", "data:")):
        return file_ref
    path = Path(file_ref)
    if path.exists():
        return str(path.resolve())
    return file_ref


def _image_segment(content_ref: dict[str, Any]) -> OneBotMessageSegment | None:
    file_ref = (
        _string_value(content_ref.get("file"))
        or _string_value(content_ref.get("url"))
        or _string_value(content_ref.get("path"))
    )
    if not file_ref:
        return None
    file_ref = _resolve_local_file_ref(file_ref)
    data: dict[str, Any] = {"file": file_ref}
    for key in ("cache", "proxy", "timeout"):
        if key in content_ref and isinstance(content_ref[key], (bool, int, str)):
            data[key] = content_ref[key]
    return {"type": "image", "data": data}


def _json_card_segment(content_ref: dict[str, Any]) -> OneBotMessageSegment | None:
    raw_payload = (
        content_ref.get("onebot_json")
        if "onebot_json" in content_ref
        else content_ref.get("json")
    )
    if raw_payload is None:
        raw_payload = content_ref.get("data")
    if isinstance(raw_payload, (dict, list)):
        payload = json.dumps(raw_payload, ensure_ascii=False)
    else:
        payload = _string_value(raw_payload)
    if not payload:
        return None
    return {"type": "json", "data": {"data": payload}}


def _string_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


async def send_onebot_v11(bot: OneBotV11Bot, send_request: SendRequest) -> DeliveryReceipt:
    try:
        if send_request.content.content_type.strip().lower() == "chunks":
            raw_chunks = send_request.content.content_ref.get("chunks")
            chunks = (
                [str(item).strip() for item in raw_chunks if str(item).strip()]
                if isinstance(raw_chunks, list)
                else []
            )
            if not chunks:
                chunks = [send_request.content.text_fallback]
            result = None
            for chunk in chunks:
                segment = _text_segment(chunk)
                if send_request.target_scope is SessionType.PRIVATE:
                    result = await bot.send_private_msg(
                        user_id=_coerce_onebot_id(send_request.target_id),
                        message=[segment],
                    )
                elif send_request.target_scope is SessionType.GROUP:
                    result = await bot.send_group_msg(
                        group_id=_coerce_onebot_id(send_request.target_id),
                        message=[segment],
                    )
                else:
                    return DeliveryReceipt(
                        request_id=send_request.request_id,
                        state=ReceiptState.BLOCKED,
                        transport=ONEBOT_V11_TRANSPORT,
                        public_message=f"OneBot V11 不支持目标类型：{send_request.target_scope.value}",
                    )
            if result is None:
                raise RuntimeError("chunk transport returned no result")
        else:
            forward_result = await _try_send_forward_message(bot, send_request)
            if forward_result is not _FORWARD_API_UNAVAILABLE:
                result = forward_result
            elif send_request.target_scope is SessionType.PRIVATE:
                result = await bot.send_private_msg(
                    user_id=_coerce_onebot_id(send_request.target_id),
                    message=build_onebot_message_segments(send_request),
                )
            elif send_request.target_scope is SessionType.GROUP:
                result = await bot.send_group_msg(
                    group_id=_coerce_onebot_id(send_request.target_id),
                    message=build_onebot_message_segments(send_request),
                )
            else:
                return DeliveryReceipt(
                    request_id=send_request.request_id,
                    state=ReceiptState.BLOCKED,
                    transport=ONEBOT_V11_TRANSPORT,
                    public_message=f"OneBot V11 不支持目标类型：{send_request.target_scope.value}",
                )
    except Exception:  # noqa: BLE001 - OneBot 发送异常统一转为可重试失败回执。
        debug_id = new_debug_id()
        return DeliveryReceipt(
            request_id=send_request.request_id,
            state=ReceiptState.FAILED_RETRYABLE,
            transport=ONEBOT_V11_TRANSPORT,
            public_message=f"OneBot V11 发送失败，debug_id={debug_id}",
            debug_id=debug_id,
            provider_message_id=None,
        )

    if not _onebot_result_is_success(result):
        debug_id = new_debug_id()
        retcode = _extract_onebot_retcode(result)
        state = (
            ReceiptState.FAILED_FINAL
            if _is_final_failure_retcode(retcode)
            else ReceiptState.FAILED_RETRYABLE
        )
        return DeliveryReceipt(
            request_id=send_request.request_id,
            state=state,
            transport=ONEBOT_V11_TRANSPORT,
            provider_message_id=None,
            public_message=redact_private_debug(
                _safe_onebot_failure_message(result, debug_id)
            ),
            debug_id=debug_id,
        )

    return DeliveryReceipt(
        request_id=send_request.request_id,
        state=ReceiptState.SENT,
        transport=ONEBOT_V11_TRANSPORT,
        provider_message_id=_extract_message_id(result),
        public_message="sent",
    )


async def _try_send_forward_message(
    bot: OneBotV11Bot,
    send_request: SendRequest,
) -> Any:
    messages = _forward_messages(send_request)
    if not messages:
        return _FORWARD_API_UNAVAILABLE

    if send_request.target_scope is SessionType.GROUP:
        payload = {
            "group_id": _coerce_onebot_id(send_request.target_id),
            "messages": messages,
        }
        return await _call_optional_onebot_api(
            bot,
            "send_group_forward_msg",
            payload,
        )
    if send_request.target_scope is SessionType.PRIVATE:
        payload = {
            "user_id": _coerce_onebot_id(send_request.target_id),
            "messages": messages,
        }
        return await _call_optional_onebot_api(
            bot,
            "send_private_forward_msg",
            payload,
        )
    return _FORWARD_API_UNAVAILABLE


async def _call_optional_onebot_api(
    bot: OneBotV11Bot,
    api_name: str,
    payload: dict[str, Any],
) -> Any:
    direct_method = getattr(bot, api_name, None)
    if callable(direct_method):
        return await direct_method(**payload)
    call_api = getattr(bot, "call_api", None)
    if callable(call_api):
        return await call_api(api_name, **payload)
    return _FORWARD_API_UNAVAILABLE

