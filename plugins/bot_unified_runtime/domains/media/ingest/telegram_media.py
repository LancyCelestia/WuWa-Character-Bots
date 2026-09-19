"""Telegram file_id → 媒体字节解析（评审会话 §1.3 已知残余修复）。

TG 的 photo/sticker/animation/video_note/voice/audio 段只带 file_id（适配器
入站形态是 ``data.file = file_id``，非 URL 非路径），vision_describe 的
``extract_image_urls`` 与 transcribe 的 ``extract_audio_source`` 都解析不出
来源，模型只能看到"[图片]/[语音]"标签。本模块把 file_id 经 Bot API
``get_file`` 解析为 file_path，再下载字节：

1. ``file_path`` 已是完整 URL → 直接下载（自定义 api server 可能返回该形态）；
2. 否则拼 ``{api_server}/file/bot<token>/<file_path>`` 下载（Telegram 官方
   下载硬上限 20MB，超限返回 None）；
3. 任何失败（get_file 异常/下载异常/超限/空 token）→ None + debug 日志，
   **绝不抛异常**，token 绝不进日志（异常消息可能携带完整 URL，故只记
   异常类型名与状态码）。

``enrich_telegram_file_segments`` 是摄取层（``__init__.py`` 主聊天 handler）
的单点接线：把下载成功的字节落到临时文件并写回段 ``data.file``，vision/ASR
的既有"本机路径"链路即可直接消费；失败保持段原样，既有"标签降级"行为
完全不变。file_id → file_path 结果带 5 分钟 TTL 缓存，防同一 file_id 反复
get_file；字节不缓存（临时文件即一次性交付物，到期清理）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Telegram Bot API 文件下载硬上限：file/bot<token> 端点最多回 20MB。
DEFAULT_MAX_FILE_BYTES = 20 * 1024 * 1024
_DEFAULT_TIMEOUT_SECONDS = 10.0
_DEFAULT_API_BASE = "https://api.telegram.org/"

# file_id → file_path 短 TTL 缓存：同一条消息的富化与后续消费点只该发一次
# get_file；file_path 本身不含 token，缓存无泄密面。字节一律不缓存。
_FILE_PATH_TTL_SECONDS = 300.0
_FILE_PATH_CACHE_CAP = 256
_FILE_PATH_CACHE: dict[str, tuple[float, str]] = {}
_FILE_PATH_CACHE_ORDER: list[str] = []

# 需要"落字节"的 TG 媒体段类型（与 message_context 标签、vision 的
# _IMAGE_SEGMENT_TYPES、ASR 的 _RECORD_SEGMENT_TYPES 对齐）。TG 的 video
# 段走独立视频理解管线，document 不在本次范围，均不含在内。
TELEGRAM_FILE_ID_SEGMENT_TYPES = frozenset(
    {"photo", "sticker", "animation", "video_note", "voice", "audio"}
)

# file_path 无后缀时的兜底后缀（TG 官方 file_path 几乎总带后缀）。
_TYPE_DEFAULT_SUFFIX = {
    "photo": ".jpg",
    "sticker": ".webp",
    "animation": ".mp4",
    "video_note": ".mp4",
    "voice": ".oga",
    "audio": ".mp3",
}


class _DownloadStatusError(RuntimeError):
    """非 200 下载回执；消息只含状态码，绝不携带 URL（含 token）。"""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"telegram file download status {status_code}")
        self.status_code = status_code


def _bot_token(bot: Any) -> str:
    """bot 令牌：bot_config.token → 适配器 telegram_bots 按 id 匹配 → env。"""
    token = str(
        getattr(getattr(bot, "bot_config", None), "token", "") or ""
    ).strip()
    if token:
        return token
    self_id = str(getattr(bot, "self_id", "") or "").strip()
    adapter_config = getattr(getattr(bot, "adapter", None), "adapter_config", None)
    for entry in getattr(adapter_config, "telegram_bots", None) or []:
        candidate = str(getattr(entry, "token", "") or "").strip()
        if not candidate:
            continue
        # token 形如 "<bot_id>:<secret>"；无 self_id 可比对时取第一个非空项。
        if not self_id or candidate.split(":", 1)[0] == self_id:
            return candidate
    return str(os.environ.get("TELEGRAM_BOT_TOKEN", "") or "").strip()


def _download_proxy(bot: Any) -> str:
    """代理取值：TELEGRAM_PROXY → 适配器 telegram_proxy → BOT_DOWNLOAD_PROXY。

    nonebot 全局 Config 允许额外键，运行时配置 bot_download_proxy 会落在
    adapter.config 上，一并纳入（以实际可得者为准）。
    """
    proxy = str(os.environ.get("TELEGRAM_PROXY", "") or "").strip()
    if proxy:
        return proxy
    adapter = getattr(bot, "adapter", None)
    proxy = str(getattr(getattr(adapter, "adapter_config", None), "proxy", "") or "").strip()
    if proxy:
        return proxy
    proxy = str(os.environ.get("BOT_DOWNLOAD_PROXY", "") or "").strip()
    if proxy:
        return proxy
    return str(getattr(getattr(adapter, "config", None), "bot_download_proxy", "") or "").strip()


def _file_download_url(bot: Any, file_path: str) -> str | None:
    """file_path → 下载 URL；已是完整 URL 原样返回；无 token 返回 None。"""
    if file_path.startswith(("http://", "https://")):
        return file_path
    token = _bot_token(bot)
    if not token:
        return None
    base = str(
        getattr(getattr(bot, "bot_config", None), "api_server", "") or ""
    ).strip() or _DEFAULT_API_BASE
    return f"{base.rstrip('/')}/file/bot{token}/{file_path.lstrip('/')}"


async def _resolve_file_path(bot: Any, file_id: str, *, timeout: float) -> str:
    """file_id → Bot API file_path（带短 TTL 缓存）；失败抛异常由调用方兜底。"""
    now = time.monotonic()
    cached = _FILE_PATH_CACHE.get(file_id)
    if cached is not None and now - cached[0] < _FILE_PATH_TTL_SECONDS:
        return cached[1]
    file_obj = await asyncio.wait_for(
        bot.call_api("get_file", file_id=file_id), timeout=timeout
    )
    file_path = str(getattr(file_obj, "file_path", "") or "").strip()
    if not file_path:
        raise ValueError("get_file returned empty file_path")
    _FILE_PATH_CACHE[file_id] = (now, file_path)
    _FILE_PATH_CACHE_ORDER.append(file_id)
    while len(_FILE_PATH_CACHE_ORDER) > _FILE_PATH_CACHE_CAP:
        evicted = _FILE_PATH_CACHE_ORDER.pop(0)
        _FILE_PATH_CACHE.pop(evicted, None)
    return file_path


def _build_download_client(**kwargs: Any) -> httpx.AsyncClient:
    """下载客户端构造缝（测试经此注入 MockTransport，不发真请求）。"""
    return httpx.AsyncClient(**kwargs)


async def _download_bytes(
    url: str,
    *,
    max_bytes: int,
    timeout: float,
    proxy: str = "",
) -> bytes | None:
    """流式下载并限读；超限/空体返回 None，网络异常向上抛（调用方兜底）。"""
    client_kwargs: dict[str, Any] = {
        "timeout": httpx.Timeout(timeout, connect=min(8.0, timeout)),
        "follow_redirects": True,
    }
    if proxy:
        # httpx 0.28+ 只认 proxy 单数参数（与 transcribe.py 一致）。
        client_kwargs["proxy"] = proxy
    chunks: list[bytes] = []
    size = 0
    async with _build_download_client(**client_kwargs) as client, client.stream(
        "GET", url
    ) as response:
            if response.status_code != 200:
                raise _DownloadStatusError(response.status_code)
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > max_bytes:
                    logger.debug(
                        "telegram media too large bytes>=%s limit=%s", size, max_bytes
                    )
                    return None
                chunks.append(chunk)
    if not chunks:
        return None
    return b"".join(chunks)


async def resolve_telegram_file_bytes(
    bot: Any,
    file_id: str,
    *,
    max_bytes: int = DEFAULT_MAX_FILE_BYTES,
    timeout: float = _DEFAULT_TIMEOUT_SECONDS,
) -> bytes | None:
    """file_id → 媒体字节；任何失败返回 None，绝不抛异常，token 绝不进日志。

    链路：Bot API ``get_file(file_id)`` → ``file.file_path`` → 已是完整 URL
    直接下载，否则拼 ``{api_server}/file/bot<token>/<file_path>``。20MB 为
    Telegram Bot API 下载硬上限，超限返回 None。
    """
    file_id = str(file_id or "").strip()
    if not file_id or not callable(getattr(bot, "call_api", None)):
        return None
    try:
        file_path = await _resolve_file_path(bot, file_id, timeout=timeout)
        url = _file_download_url(bot, file_path)
    except asyncio.TimeoutError:
        logger.debug(
            "telegram get_file timed out timeout=%.1fs file_id_prefix=%s",
            timeout,
            file_id[:8],
        )
        return None
    except Exception as exc:  # noqa: BLE001 - get_file 失败按无媒体处理。
        logger.debug(
            "telegram get_file failed kind=%s file_id_prefix=%s",
            type(exc).__name__,
            file_id[:8],
        )
        return None
    if not url:
        logger.debug(
            "telegram media download skipped: no bot token file_id_prefix=%s",
            file_id[:8],
        )
        return None
    try:
        return await _download_bytes(
            url, max_bytes=max_bytes, timeout=timeout, proxy=_download_proxy(bot)
        )
    except _DownloadStatusError as exc:
        logger.debug(
            "telegram media download failed status=%s", exc.status_code
        )
        return None
    except Exception as exc:  # noqa: BLE001 - 下载/超时异常按无媒体处理。
        # 异常消息可能内嵌含 token 的 URL，只记类型名。
        logger.debug("telegram media download failed kind=%s", type(exc).__name__)
        return None


def _unlink_quietly(path: str) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:  # 清理失败留待系统临时目录兜底。
        return


def _schedule_temp_cleanup(path: str, delay_seconds: float) -> None:
    """延迟删除临时媒体文件：消费点（vision/ASR 编排）在秒级内读完即弃。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # 无事件循环（理论不可达，富化是异步链路）→ 不排程。
        return
    loop.call_later(max(1.0, float(delay_seconds)), _unlink_quietly, path)


def _write_temp_file(payload: bytes, suffix: str) -> Path:
    handle, name = tempfile.mkstemp(prefix="bot_tg_media_", suffix=suffix)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
    except OSError:
        _unlink_quietly(name)
        raise
    return Path(name)


def _media_suffix(segment_type: str, file_path: str) -> str:
    suffix = Path(file_path.split("?", 1)[0]).suffix.lower()
    return suffix or _TYPE_DEFAULT_SUFFIX.get(segment_type, ".bin")


def _segment_file_id(data: dict[str, Any]) -> str:
    """TG 段的 file_id：适配器入站放在 data.file；保留 data.file_id 兼容。"""
    return str(data.get("file_id") or data.get("file") or "").strip()


def _segment_already_resolvable(data: dict[str, Any]) -> bool:
    """段已有可用来源（url/path/transcoded_path/本机文件）→ 不碰。"""
    if any(str(data.get(key) or "").strip() for key in ("url", "path", "transcoded_path")):
        return True
    file_value = str(data.get("file") or "").strip()
    if file_value.startswith(("http://", "https://")):
        return True
    try:
        return Path(file_value).is_file() if file_value else False
    except OSError:  # 路径探测失败按"无来源"处理。
        return False


async def enrich_telegram_file_segments(
    bot: Any,
    event: Any,
    segments: list[dict[str, Any]] | None,
    *,
    max_bytes: int = DEFAULT_MAX_FILE_BYTES,
    timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    temp_ttl_seconds: float = 600.0,
) -> None:
    """摄取层单点富化：TG 媒体段 file_id → 字节落临时文件 → 写回 data.file。

    仅对 Telegram 事件生效；只处理"只有 file_id、没有任何可用来源"的媒体段。
    成功后段 ``data.file`` 指向本机临时文件（原 file_id 保留在 data.file_id），
    vision_describe/transcribe 的既有本机路径链路即可直接消费；任何失败保持
    段原样，既有"标签降级"行为完全不变。本函数绝不抛异常。
    """
    if event is None or ".telegram" not in type(event).__module__.lower():
        return
    for segment in segments or []:
        if not isinstance(segment, dict):
            continue
        segment_type = str(segment.get("type", "")).strip().lower()
        if segment_type not in TELEGRAM_FILE_ID_SEGMENT_TYPES:
            continue
        data = segment.get("data")
        if not isinstance(data, dict) or _segment_already_resolvable(data):
            continue
        file_id = _segment_file_id(data)
        if not file_id:
            continue
        try:
            file_path = await _resolve_file_path(bot, file_id, timeout=timeout)
            url = _file_download_url(bot, file_path)
            if not url:
                logger.debug(
                    "telegram media enrich skipped: no token file_id_prefix=%s",
                    file_id[:8],
                )
                continue
            payload = await _download_bytes(
                url,
                max_bytes=max_bytes,
                timeout=timeout,
                proxy=_download_proxy(bot),
            )
            if not payload:
                continue
            path = _write_temp_file(payload, _media_suffix(segment_type, file_path))
            data["file_id"] = file_id
            data["file"] = str(path)
            _schedule_temp_cleanup(str(path), temp_ttl_seconds)
        except Exception as exc:  # noqa: BLE001 - 单段失败不影响其余段与主链路。
            logger.debug(
                "telegram media enrich failed seg=%s kind=%s",
                segment_type,
                type(exc).__name__,
            )
            continue
