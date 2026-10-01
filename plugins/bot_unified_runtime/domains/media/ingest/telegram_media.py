"""Telegram file_id → 媒体字节解析（评审会话 §1.3 已知残余修复）。

TG 的 photo/sticker/animation/video_note/voice/audio/document 段只带 file_id
（适配器入站形态是 ``data.file = file_id``，非 URL 非路径；document 连文件名都不
给），vision_describe 的
``extract_image_urls`` 与 transcribe 的 ``extract_audio_source`` 都解析不出
来源，模型只能看到"[图片]/[语音]"标签。本模块把 file_id 经 Bot API
``get_file`` 解析为 file_path，再下载字节：

1. ``file_path`` 已是完整 URL → 直接下载（自定义 api server 可能返回该形态）；
2. 否则拼 ``{api_server}/file/bot<token>/<file_path>`` 下载（Telegram 官方
   下载硬上限 20MB，超限返回 None）；
3. 取字节链每一跳（入口与 30x 重定向落点）先过中央 SSRF 咽喉
   ``check_download_url``（经 httpx ``request`` 事件钩子逐跳复查，口径同
   同域 ``transcribe._download_audio`` 与短链链 ``_GuardedShortLinkRedirectHandler``，
   不造第二套 URL 判据）——URL 由 Telegram ``get_file`` 服务端返回、
   服务器可控，落点指内网/元数据即在建连前拒绝（攻击者复查 F-B/A-ING-2）；
4. 图像/视频段字节在落盘前过归档面 magic-bytes 真身 ``sniff_extension``
   （单一真身，TG 侧不另写判据表）：识别不出的容器点名降级、不落盘不喂
   vision；语音/音频容器（ogg/mp3）不在真身覆盖集内，为其自造签名表即
   第二真身——音频段 QC 属登记残余（审查 F-B/A-ING-2，照实挂账不假称已护）。
5. **document 段（需求 16①）与其它媒体段同一条摄取腿**：取字节、限额、逐跳
   咽喉全部继承，落盘后把段改成**根入站唯一认得的 file 段形状**
   （``type="file"`` + ``data.file`` + ``data.name``），读取仍归根入站
   ``read_supported_file`` 那一颗咽喉——本模块绝不自开第二条读文件通路。
   文档段**不过**图像/视频那道 magic-bytes QC（拿错尺子：docx 是 zip、
   ``.txt`` 无签名，一律会误杀合法文件），但名字必经显示伪装消毒：真身＝
   ``get_file`` 回的 ``file_path`` 末段（TG 入站段本身不带文件名），过与
   出站/落盘**同一条** ``file_gateway.sanitize_file_name``（Bidi 覆写/零宽
   插入/同形异码伪装在那一条咽喉里剥，判据住 ``core/safety_exec/attack_surface``，
   TG 侧零副本）。盘上落点是 ``mkstemp`` 生成的随机名，不含任何外部可控字符。
6. 任何失败（get_file 异常/下载异常/咽喉拒绝/QC 拒绝/超限/空 token）→
   None 或段原样（标签降级），**绝不抛异常**，token 绝不进日志（异常消息
   可能携带完整 URL，故只记异常类型名与状态码）。

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

from plugins.bot_unified_runtime.domains.media.archive.media_archive import (
    sniff_extension,
)

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
# 段走独立视频理解管线，不含在内。``document`` 于 2026-09-30 接进本集
# （需求 16①）：段富化后改成根入站认得的 file 段形状，落点见
# _DOCUMENT_TARGET_SEGMENT_TYPE 那一段的注释。
TELEGRAM_FILE_ID_SEGMENT_TYPES = frozenset(
    {"photo", "sticker", "animation", "video_note", "voice", "audio", "document"}
)

# 文档段的落点形状：根入站（``__init__.py`` 文件读腿）只认 ``type="file"`` +
# ``data.file``，读取一律走 ``domains/files/sources/file_reader.read_supported_file``
# 那一颗咽喉——TG 侧只落字节、只改段形，绝不 import 文件读取件（第二通路）。
_DOCUMENT_TARGET_SEGMENT_TYPE = "file"
# get_file 回的 file_path 没有可用末段时的诚实落点名（与邮件附件腿同一措辞）。
_DOCUMENT_FALLBACK_NAME = "附件"

# file_path 无后缀时的兜底后缀（TG 官方 file_path 几乎总带后缀）。
_TYPE_DEFAULT_SUFFIX = {
    "photo": ".jpg",
    "sticker": ".webp",
    "animation": ".mp4",
    "video_note": ".mp4",
    "voice": ".oga",
    "audio": ".mp3",
    "document": ".bin",
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


# file_id → 下载 URL 逐跳受护（攻击者复查 F-B/A-ING-2 修复，席位 S-FIX-TGMEDIA）：
# URL 由 Telegram get_file 服务端返回——服务器可控即等同用户可控，30x 落点
# 可指内网/云元数据。判据不造第二套：每跳发出前过中央咽喉 check_download_url
# （口径同 transcribe._download_audio 的 httpx request 事件钩子，钩子语义见
# _GuardedShortLinkRedirectHandler 先例——解析失败=拒绝，内网零连接）。
# 图像/视频段落盘前再过归档 magic-bytes 真身 sniff_extension（单一真身，
# 见 _QC_SEGMENT_TYPES 注释）；不合格字节点名降级，不落盘不喂下游。
# **document 刻意不入本集**（需求 16①，测试 ③ 的判据）：图像签名是拿错尺子——
# docx 是 zip、``.txt`` 无签名，照套会误杀合法文件。文档段的防线＝摄取腿本身
# （逐跳咽喉 + 限额）＋根入站那一颗读取咽喉，不在此另立一套内容判据。
_QC_SEGMENT_TYPES = frozenset({"photo", "sticker", "animation", "video_note"})


async def _download_bytes(
    url: str,
    *,
    max_bytes: int,
    timeout: float,
    proxy: str = "",
) -> bytes | None:
    """流式下载并限读；超限/空体返回 None，网络异常向上抛（调用方兜底）。

    咽喉拒绝同样向上抛（``RejectedUrlError``）——调用方按既有失败面点名
    降级，绝不吞成"下载成功"或静默混淆"瞬时失败"。
    """
    from plugins.bot_unified_runtime.domains.files.sources.downloader import (
        check_download_url,
    )

    async def _guard_hop(request: httpx.Request) -> None:
        # httpx 每一跳（初始请求 + 每个 30x 落点）在 transport 建连之前都会
        # 触发本钩子；命中内网/保留段/解析失败即抛，请求绝不发向内网。
        check_download_url(str(request.url))

    client_kwargs: dict[str, Any] = {
        "timeout": httpx.Timeout(timeout, connect=min(8.0, timeout)),
        "follow_redirects": True,
        "event_hooks": {"request": [_guard_hop]},
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
    except Exception as exc:  # noqa: BLE001 - 下载/超时/咽喉拒绝按无媒体处理。
        # 异常消息可能内嵌含 token 的 URL，只记类型名（咽喉拒绝即
        # kind=RejectedUrlError，点名可辨，与瞬时失败同层不混称成功）。
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


def _document_display_name(file_path: str) -> str:
    """文档段显示名：TG ``file_path`` 末段 + 与出站/落盘**同一条**消毒咽喉。

    TG 入站段不带文件名（适配器只给 ``data.file = file_id``），真身只能取自
    ``get_file`` 回的 ``file_path``；而那条串由 TG 服务器控制＝等同用户可控，
    肉眼形态可做伪装（Bidi 覆写把 ``.exe`` 显示成 ``.txt``、零宽插入拆开扩展名）。
    判据零副本：本口只调用 ``file_gateway.sanitize_file_name``（basename + 控制
    字符 + ``strip_display_controls``/``fold_name_disguise``，伪装码点表唯一真身在
    ``core/safety_exec/attack_surface``），与邮件附件腿用的是同一枚口。
    局部导入避开环（本件住 media 域，不新增对 transport 的模块级依赖）。
    只影响**显示形态**：盘上落点是 ``_write_temp_file`` 的 mkstemp 随机名，
    不含任何外部可控字符；Win32 保留设备名那一格归落盘咽喉
    （``restricted_runner``）判，本腿不落名盘、不重复判一次。
    """
    from plugins.bot_unified_runtime.domains.transport.sender.file_gateway import (
        sanitize_file_name,
    )

    tail = file_path.split("?", 1)[0]
    return sanitize_file_name(tail) or _DOCUMENT_FALLBACK_NAME


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

    ``document`` 段额外改段形为根入站认得的 file 段（``type="file"`` +
    ``data.name``，见 _DOCUMENT_TARGET_SEGMENT_TYPE 注释），文件正文仍由根入站
    的 ``read_supported_file`` 咽喉读取；图像/音频段的形状逐字节不变。
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
            # 落盘前 QC：复用归档面 magic-bytes 真身 sniff_extension（单一真身，
            # 禁在 TG 侧另写签名表）。识别不出的容器=伪装/非法字节——点名降级
            # （保持段原样→既有标签降级），不落临时文件、不喂 vision。
            # 语音/音频容器不在真身覆盖集内，为其自造签名即第二真身——
            # 登记残余（模块 docstring 第 4 条），照实挂账不假称已护。
            if segment_type in _QC_SEGMENT_TYPES and sniff_extension(payload) is None:
                logger.debug(
                    "telegram media qc rejected seg=%s name=unsupported_media_type "
                    "file_id_prefix=%s",
                    segment_type,
                    file_id[:8],
                )
                continue
            path = _write_temp_file(payload, _media_suffix(segment_type, file_path))
            data["file_id"] = file_id
            data["file"] = str(path)
            if segment_type == "document":
                # 需求 16①：文档段落点＝根入站唯一认得的 file 段形状（type="file"
                # + data.file + data.name）。字节已在本机暂存件里，读取交回根入站
                # 那颗 read_supported_file 咽喉——本腿不改读取语义、不开第二通路。
                # 名字过 _document_display_name（与出站/落盘同一条消毒），伪装形态
                # 在进提示词之前就被剥掉；失败路径保持段原样（既有标签降级不变）。
                data["name"] = _document_display_name(file_path)
                segment["type"] = _DOCUMENT_TARGET_SEGMENT_TYPE
            _schedule_temp_cleanup(str(path), temp_ttl_seconds)
        except Exception as exc:  # noqa: BLE001 - 单段失败不影响其余段与主链路。
            logger.debug(
                "telegram media enrich failed seg=%s kind=%s",
                segment_type,
                type(exc).__name__,
            )
            continue
