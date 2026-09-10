"""视频理解预处理管线：反查视频文件、进度提示（ack）、bot 发出视频的档案登记。

从插件 ``__init__`` 整体搬出的媒体运行时簇；``__init__`` 再导出同名符号，
旧访问路径（``runtime._prepare_video_understanding_message`` 等）保持可用。
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.contracts import DeliveryReceipt, SendRequest


def _runtime_scripts_path(value: str):
    from scripts.runtime_paths import runtime_path

    return runtime_path(value)


_MEDIA_RUNTIME_SINGLETON: dict[str, Any] = {}
_VIDEO_ACK_TEXT = "这个视频我看看，稍等一下…"
_VIDEO_ACK_THROTTLE: dict[str, float] = {}


def _get_media_registry() -> Any:
    return _MEDIA_RUNTIME_SINGLETON.get("registry")


def _video_understanding_enabled_now(config: Any, runtime_settings: Any | None) -> bool:
    enabled = bool(getattr(config, "bot_video_understanding_enabled", False))
    if runtime_settings is not None:
        try:
            enabled = bool(
                runtime_settings.get_or("BOT_VIDEO_UNDERSTANDING_ENABLED", enabled)
            )
        except (KeyError, OSError, TypeError, ValueError):
            pass
    return enabled


def _provider_enabled(provider: Any) -> bool:
    """provider 是否真的可用：读 runtime 开关（BOT_VISION/BOT_ASR_ENABLED），防"应了却不答"。"""
    try:
        return bool(provider.is_enabled())
    except Exception:  # noqa: BLE001 - 开关读取失败按可用处理。
        return True


def _local_file_usable(path: str) -> bool:
    if not path:
        return False
    try:
        return Path(path).is_file()
    except OSError:
        return False


async def _fetch_reply_video_file(bot: Any, message_id: str, config: Any) -> str:
    """按消息 id 向适配器反查视频文件（NapCat get_msg → video 段 file/url）。

    仅在媒体档案未命中时调用；拿到落盘路径直接用，只有 url 时下载到下载缓存
    目录（fetched/ 子目录）。适配器不支持/失败一律返回空串，绝不阻断主链路。
    """
    try:
        if str(message_id).isdigit():
            payload = await bot.call_api("get_msg", message_id=int(message_id))
        else:
            payload = await bot.call_api("get_msg", message_id=message_id)
    except Exception:  # noqa: BLE001 - 非 NapCat 实现或消息已失效：静默降级。
        return ""
    segments = payload.get("message") if isinstance(payload, dict) else None
    if not isinstance(segments, list):
        return ""
    from plugins.bot_unified_runtime.sources.vision_describe import (
        _local_path_from_value,
    )

    for segment in segments:
        if not isinstance(segment, dict):
            continue
        if str(segment.get("type", "")).lower() != "video":
            continue
        data = segment.get("data") or {}
        if not isinstance(data, dict):
            continue
        for key in ("file", "path"):
            local = _local_path_from_value(str(data.get(key) or ""))
            if local is not None:
                return str(local)
        url = str(data.get("url") or "")
        if url.startswith("http"):
            from plugins.bot_unified_runtime.sources.transcribe import _download_audio

            dest_dir = (
                Path(_runtime_scripts_path(
                    str(getattr(config, "bot_download_dir", "data/downloads") or "data/downloads")
                ))
                / "fetched"
            )
            try:
                dest_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                return ""
            dest = dest_dir / f"reply_{str(message_id)[-16:]}.mp4"
            # 同步 httpx 下载放进线程：直接 await 会把整个事件循环冻住 30s。
            downloaded = await asyncio.to_thread(_download_audio, url, dest, 30.0)
            if downloaded is not None:
                return str(downloaded)
    return ""


async def _prepare_video_understanding_message(
    bot: Any,
    message: Any,
    matcher_send: Callable[[str], Any],
    *,
    config: Any,
    runtime_settings: Any | None,
    media_registry: Any | None,
    media_providers_ready: bool = True,
) -> Any:
    """视频理解预处理（handler 异步上下文专用）：

    1. 回复引用的视频档案未命中时，向适配器反查视频文件填进
       ``reply_video_path``（适配器 API 只能在事件循环里调，能力层保持同步）；
    2. 确认要现场分析（无缓存简报）时给会话发一条进度提示，按会话节流。
    ack 三重把关防"应了却不答"：有活可干（will_analyze）、有信号来源
    （provider 或既有档案）、本轮确实会回复（mentions_bot）。
    档案缓存命中则原样返回，不反查、不打扰。
    """
    if not _video_understanding_enabled_now(config, runtime_settings):
        return message
    if not getattr(message, "mentions_bot", False):
        # 不会回复的消息（受限群无点名、纯闲聊视频）不反查也不 ack：
        # 白下载视频 + 白等分析是最伤信任的组合。
        return message
    reply_id = str(message.reply_to_message_id or "")
    record = None
    if reply_id and media_registry is not None:
        try:
            record = media_registry.lookup_by_message_id(reply_id)
        except Exception:  # noqa: BLE001 - 档案库读失败按未命中处理。
            record = None
        if record is not None and str(getattr(record, "brief_text", "") or "").strip():
            return message
    fetched = ""
    if reply_id and (
        record is None or not _local_file_usable(str(getattr(record, "local_path", "") or ""))
    ):
        fetched = await _fetch_reply_video_file(bot, reply_id, config)
        if fetched:
            message = message.model_copy(update={"reply_video_path": fetched})
    has_video_segment = any(
        str(segment.get("type", "")).lower() == "video"
        for segment in (message.raw_segments or [])
    )
    # 档案即使没有本地文件，字幕/标题也能合成文本简报——都算"有活可干"。
    record_has_material = record is not None and (
        _local_file_usable(str(getattr(record, "local_path", "") or ""))
        or bool(str(getattr(record, "subtitle_text", "") or "").strip())
        or bool(str(getattr(record, "title", "") or "").strip())
    )
    will_analyze = has_video_segment or bool(fetched) or record_has_material
    if not will_analyze:
        # 自然语言深挖请求（"再仔细看看"）即使缓存命中也要重新分析：同样值得 ack。
        try:
            from plugins.bot_unified_runtime.sources.video_understanding import (
                detect_deep_video_request,
            )

            will_analyze = (
                (has_video_segment or record is not None)
                and detect_deep_video_request(str(message.plain_text or ""))
            )
        except Exception:  # noqa: BLE001 - 深挖探测失败按无深挖处理。
            will_analyze = False
    has_signal_source = bool(media_providers_ready) or record is not None
    if (
        not will_analyze
        or not has_signal_source
        or not getattr(message, "mentions_bot", False)
        or not bool(getattr(config, "bot_video_progress_ack_enabled", True))
    ):
        return message
    now = time.monotonic()
    cooldown = float(
        getattr(config, "bot_video_progress_ack_cooldown_seconds", 60) or 60
    )
    last = _VIDEO_ACK_THROTTLE.get(str(message.session_id), 0.0)
    if now - last < cooldown:
        return message
    # 已知档案带标题时点出标题，让"稍等"有对象；未知/无标题走通用文案。
    ack_text = _VIDEO_ACK_TEXT
    if record is not None:
        title = str(getattr(record, "title", "") or "").strip()
        if title:
            ack_text = f"我看看《{title}》，稍等…"
    try:
        value = matcher_send(ack_text)
        if inspect.isawaitable(value):
            await value
    except Exception:  # noqa: BLE001 - 进度提示失败不影响回答。
        logging.getLogger(__name__).debug("video progress ack send failed")
        return message
    # 发送成功才占坑：失败不惩罚该会话的后续追问。
    _VIDEO_ACK_THROTTLE[str(message.session_id)] = now
    while len(_VIDEO_ACK_THROTTLE) > 512:
        _VIDEO_ACK_THROTTLE.pop(next(iter(_VIDEO_ACK_THROTTLE)))
    return message


def _register_bot_sent_video_assets(
    send_request: SendRequest, receipt: DeliveryReceipt
) -> None:
    """机器人发出的视频（解析直发 / 下载命令）→ 媒体档案 bot_sent 登记。

    锚点 = 发送回执的 provider_message_id：用户回复这条消息提问时按
    message_id 命中档案，复用或现场生成感知简报。登记失败只记日志。
    """
    if receipt.state.value != "sent" or not receipt.provider_message_id:
        return
    registry = _get_media_registry()
    if registry is None:
        return
    parts = (send_request.content.content_ref or {}).get("parts") or []
    for part in parts:
        if not isinstance(part, dict) or str(part.get("type", "")).lower() != "video":
            continue
        meta = part.get("meta")
        if not isinstance(meta, dict):
            continue
        duration_ms = meta.get("duration_ms")
        try:
            from plugins.bot_unified_runtime.character.media_registry import (
                MediaAssetRecord,
            )

            registry.register(
                MediaAssetRecord(
                    media_id=uuid.uuid4().hex,
                    chat_message_id=str(receipt.provider_message_id),
                    session_id=str(send_request.session_id or ""),
                    source_kind="bot_sent",
                    platform=str(meta.get("platform") or ""),
                    item_id=str(meta.get("item_id") or ""),
                    canonical_url=str(meta.get("canonical_url") or ""),
                    title=str(meta.get("title") or "")[:200],
                    creator_name=str(meta.get("creator_name") or ""),
                    duration_ms=(
                        duration_ms if isinstance(duration_ms, int) and duration_ms > 0 else None
                    ),
                    local_path=str(part.get("file") or part.get("url") or ""),
                    subtitle_text=str(meta.get("subtitle_text") or "")[:3000],
                )
            )
        except Exception as exc:  # noqa: BLE001 - 档案登记失败不影响投递结果。
            logging.getLogger(__name__).warning(
                "media registry bot_sent register failed type=%s", type(exc).__name__
            )
