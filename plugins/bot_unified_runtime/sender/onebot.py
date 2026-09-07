from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Protocol

from plugins.bot_unified_runtime.contracts import (
    DeliveryReceipt,
    OperationalIssue,
    ReceiptState,
    SendRequest,
    SessionType,
    new_debug_id,
)
from plugins.bot_unified_runtime.runtime.deadline import (
    DeadlineExceeded,
    apply_request_deadline,
)
from plugins.bot_unified_runtime.sender.timeout import resolve_transport_timeout

ONEBOT_V11_TRANSPORT = "onebot.v11"
logger = logging.getLogger(__name__)
# 网络抖动 / NapCat 重连窗口内的瞬时异常：短退避内联重试，3 次尝试后才报发送失败。
_ONEBOT_SEND_RETRY_DELAYS = (0.8, 1.6)
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
    # Compatibility helper retained for internal callers; operational details
    # must never be exposed in a public receipt.
    return ""


def _onebot_issue(
    kind: str,
    *,
    retryable: bool,
    debug_id: str,
    attempts: int = 1,
) -> OperationalIssue:
    return OperationalIssue(
        stage="onebot",
        kind=kind,
        retryable=retryable,
        debug_id=debug_id,
        safe_summary=kind,
        attempts=max(1, attempts),
    )


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


class _NonRetryableActionError(Exception):
    pass


async def _send_file_parts(bot: OneBotV11Bot, request: SendRequest, parts: list[dict[str, Any]]) -> Any:
    """Files require upload APIs, not unsupported CQ:file. Never retry a bundle
    after any side effect: a later failure must not resend a delivered file.
    """
    result: Any = None
    for part in parts:
        if part.get("type") != "file":
            continue
        path = Path(str(part.get("file") or ""))
        if not path.is_file():
            raise _NonRetryableActionError("missing_file")
        params: dict[str, Any] = {"file": str(path.resolve()), "name": str(part.get("name") or path.name)}
        if request.target_scope is SessionType.GROUP:
            api = "upload_group_file"
            params["group_id"] = _coerce_onebot_id(request.target_id)
        elif request.target_scope is SessionType.PRIVATE:
            api = "upload_private_file"
            params["user_id"] = _coerce_onebot_id(request.target_id)
        else:
            raise _NonRetryableActionError("unsupported_file_target")
        method = getattr(bot, api, None)
        try:
            if callable(method):
                result = await method(**params)
            else:
                call_api = getattr(bot, "call_api", None)
                if not callable(call_api):
                    raise _NonRetryableActionError("upload_api_unavailable")
                result = await call_api(api, **params)
            if not _onebot_result_is_success(result):
                raise _NonRetryableActionError("upload_rejected")
        except _NonRetryableActionError:
            raise
        except Exception as exc:
            logger.warning("onebot upload call failed type=%s detail=%s", type(exc).__name__, str(exc)[:120])
            raise _NonRetryableActionError("upload_failed_or_unknown") from exc
    # The short caption is sent only after every upload succeeded.
    text = request.content.text_fallback
    if text:
        try:
            if request.target_scope is SessionType.GROUP:
                result = await bot.send_group_msg(group_id=_coerce_onebot_id(request.target_id), message=[_text_segment(text)])
            else:
                result = await bot.send_private_msg(user_id=_coerce_onebot_id(request.target_id), message=[_text_segment(text)])
        except Exception as exc:
            raise _NonRetryableActionError("caption_failed_after_upload") from exc
    return result


async def _dispatch_onebot_send(
    bot: OneBotV11Bot,
    send_request: SendRequest,
) -> Any | DeliveryReceipt:
    """执行一次发送：返回 OneBot API 结果，或不可重试的 BLOCKED 回执。"""
    parts = send_request.content.content_ref.get("parts", [])
    if isinstance(parts, list) and any(isinstance(p, dict) and p.get("type") == "file" for p in parts):
        return await _send_file_parts(bot, send_request, parts)
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
                debug_id = new_debug_id()
                return DeliveryReceipt(
                    request_id=send_request.request_id,
                    state=ReceiptState.BLOCKED,
                    transport=ONEBOT_V11_TRANSPORT,
                    public_message="",
                    debug_id=debug_id,
                    operational_issue=_onebot_issue(
                        "unsupported_target",
                        retryable=False,
                        debug_id=debug_id,
                    ),
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
            debug_id = new_debug_id()
            return DeliveryReceipt(
                request_id=send_request.request_id,
                state=ReceiptState.BLOCKED,
                transport=ONEBOT_V11_TRANSPORT,
                public_message="",
                debug_id=debug_id,
                operational_issue=_onebot_issue(
                    "unsupported_target",
                    retryable=False,
                    debug_id=debug_id,
                ),
            )
    return result


async def send_onebot_v11(
    bot: OneBotV11Bot,
    send_request: SendRequest,
    *,
    timeout_seconds: float | None = None,
) -> DeliveryReceipt:
    result: Any = None
    last_error: Exception | None = None
    timeout = resolve_transport_timeout(timeout_seconds)
    try:
        timeout = apply_request_deadline(
            timeout, getattr(send_request, "deadline_monotonic", None)
        )
    except DeadlineExceeded:
        debug_id = new_debug_id()
        logger.warning(
            "onebot send skipped after request deadline request_id=%s debug_id=%s",
            send_request.request_id,
            debug_id,
        )
        return DeliveryReceipt(
            request_id=send_request.request_id,
            state=ReceiptState.FAILED_FINAL,
            transport=ONEBOT_V11_TRANSPORT,
            public_message="",
            debug_id=debug_id,
            operational_issue=_onebot_issue(
                "deadline_exceeded",
                retryable=False,
                debug_id=debug_id,
            ),
        )
    for attempt in range(len(_ONEBOT_SEND_RETRY_DELAYS) + 1):
        try:
            dispatch = _dispatch_onebot_send(bot, send_request)
            dispatched = await asyncio.wait_for(dispatch, timeout=timeout)
            if isinstance(dispatched, DeliveryReceipt):
                return dispatched
            result = dispatched
            last_error = None
            break
        except asyncio.CancelledError:
            raise
        except _NonRetryableActionError as exc:
            debug_id = new_debug_id()
            logger.warning("onebot file delivery stopped kind=%s request_id=%s", str(exc), send_request.request_id)
            return DeliveryReceipt(request_id=send_request.request_id, state=ReceiptState.FAILED_FINAL,
                transport=ONEBOT_V11_TRANSPORT, public_message="", debug_id=debug_id,
                operational_issue=_onebot_issue(str(exc)[:48] or "file_delivery_failed_or_unknown", retryable=False, debug_id=debug_id))
        except asyncio.TimeoutError:
            debug_id = new_debug_id()
            logger.warning(
                "onebot send timed out request_id=%s debug_id=%s",
                send_request.request_id,
                debug_id,
            )
            return DeliveryReceipt(
                request_id=send_request.request_id,
                state=ReceiptState.FAILED_FINAL,
                transport=ONEBOT_V11_TRANSPORT,
                public_message="",
                debug_id=debug_id,
                operational_issue=_onebot_issue(
                    "result_unknown",
                    retryable=False,
                    debug_id=debug_id,
                    attempts=attempt + 1,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - 重试耗尽后统一转为可重试失败回执。
            last_error = exc
            if attempt < len(_ONEBOT_SEND_RETRY_DELAYS):
                await asyncio.sleep(_ONEBOT_SEND_RETRY_DELAYS[attempt])
    if last_error is not None:
        debug_id = new_debug_id()
        logger.warning(
            "onebot send failed after retries type=%s debug_id=%s",
            type(last_error).__name__,
            debug_id,
        )
        return DeliveryReceipt(
            request_id=send_request.request_id,
            state=ReceiptState.FAILED_RETRYABLE,
            transport=ONEBOT_V11_TRANSPORT,
            public_message="",
            debug_id=debug_id,
            provider_message_id=None,
            operational_issue=_onebot_issue(
                "send_exception",
                retryable=True,
                debug_id=debug_id,
                attempts=len(_ONEBOT_SEND_RETRY_DELAYS) + 1,
            ),
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
            public_message="",
            debug_id=debug_id,
            operational_issue=_onebot_issue(
                "retcode_failure",
                retryable=state is ReceiptState.FAILED_RETRYABLE,
                debug_id=debug_id,
            ),
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

