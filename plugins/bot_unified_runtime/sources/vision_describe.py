"""图片/表情包/视频识别（VLM）：角色识别 + 文字转写 + 画面简述。

聊天链路在消息携带图片（image/mface 段，QQ 与 Telegram 通用）或视频（video 段）
时调用本模块，把媒体内容转成紧凑的文字描述注入当前消息上下文，让人格模型
"看懂"媒体再回应。

图片来源优先级：NapCat 落盘的本机路径（file:// 或绝对路径，直读字节转
base64 data URL）→ http URL 原样透传。NTQQ 的签名 URL 对部分境外 VLM
不可达且会过期，本机字节是最可靠来源。GIF 动图取首帧重编为 JPEG（主流
OpenAI 兼容接口不收 image/gif）；超大图经 PIL 缩到 2048px JPEG，控制在
VLM 的 base64 体积上限内。

识别模型来自 ``BOT_VISION_MODEL_REGISTRY``（OpenAI 兼容多模态接口），支持两种
写法：``id -> 条目``（单模型）与 ``id -> [条目, ...]``（一个供应商挂多个模型，
按条目内 priority 轮询）。运行时注册表（``/bot model vision add ...``）合并于
其上且即时生效；调用失败按优先级转移到下一个候选（最多 3 个）。未启用或未
配置时整条链路零开销跳过，识别失败不阻断聊天。
"""

from __future__ import annotations

import base64
import logging
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from plugins.bot_unified_runtime.llm import (
    LLMProviderError,
    OpenAICompatibleLLMProvider,
)

logger = logging.getLogger(__name__)

_VISION_SYSTEM_PROMPT = (
    "你是图片识别器，为聊天机器人解读用户发来的图片、表情包或照片。"
    "严格按以下三行格式输出，不要输出任何其他内容：\n"
    "角色：<角色名（出处作品名）>；出自真人影视或现实照片则写“非动漫游戏角色”。"
    "无法确定时写“不确定”，并在同行给出最可能的候选与判断依据\n"
    "文字：<逐字转写图中出现的全部文字，保持原文不翻译不改写；没有文字写“无”>\n"
    "画面：<一句话描述画面内容与情绪>"
)
_VIDEO_SYSTEM_PROMPT = (
    "你是视频内容识别器，为聊天机器人解读用户发来的视频（已按时间顺序抽帧）。"
    "严格按以下三行格式输出，不要输出任何其他内容：\n"
    "内容：<一两句话概括视频主体与发生了什么>\n"
    "文字：<画面/字幕中出现的关键文字，逐字转写；没有写“无”>\n"
    "细节：<值得回应的显著细节、动作或情绪>"
)
_IMAGE_SEGMENT_TYPES = {"image", "mface"}
_VIDEO_SEGMENT_TYPES = {"video"}
_DEFAULT_MAX_IMAGES = 2
_DEFAULT_MAX_CHARS = 500
_MAX_VISION_FAILOVER_ATTEMPTS = 3
# base64 后约 4.8MB，主流 OpenAI 兼容 VLM（含 GLM-4V 5MB 限制）均可收。
_MAX_DIRECT_IMAGE_BYTES = 3_500_000
# 本地图输入上限：超过 8MB（约 _MAX_DIRECT_IMAGE_BYTES 的两倍余量，留给
# PIL 缩边重编路径）不再尝试转 data URL/PIL 重编，直接走既有降级（跳过
# 该图），避免超大文件整读进内存或生成超限请求体。
_MAX_LOCAL_IMAGE_INPUT_BYTES = 8_000_000
_PIL_MAX_SIDE = 2048
_SUFFIX_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}


def _local_path_from_value(value: str) -> Path | None:
    """file:// 前缀或本机绝对路径 → 已存在的文件；其余（含裸文件名）返回 None。"""
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith("file:"):
        parsed = urlparse(text)
        path = unquote(parsed.path or "")
        if not path:
            return None
        candidate = Path(path)
        # Windows 上 file:///C:/x 解析出 /C:/x，需剥掉盘符前的斜杠。
        if candidate.drive == "" and re.match(r"^/[A-Za-z]:[/\\]", path):
            candidate = Path(path[1:])
    else:
        if "://" in text:
            return None
        candidate = Path(text)
    try:
        if candidate.is_file():
            return candidate
    except OSError:
        return None
    return None


def _encode_image_bytes(data: bytes, mime: str) -> str:
    return "data:" + mime + ";base64," + base64.b64encode(data).decode("ascii")


def _pil_normalize(path: Path, *, first_frame_only: bool) -> str | None:
    """经 PIL 重编图片：GIF 取首帧转 PNG，超大图缩边转 JPEG；失败返回 None。"""
    from io import BytesIO

    try:
        from PIL import Image

        with Image.open(path) as image:
            return _pil_normalize_image(image, first_frame_only=first_frame_only)
    except Exception:  # noqa: BLE001 - 媒体重编失败按无图处理。
        return None


def _pil_normalize_image(image: Any, *, first_frame_only: bool) -> str | None:
    """PIL 重编的 Image 对象核心（供本机路径与远程字节两路复用）。"""
    from io import BytesIO

    try:
        if first_frame_only:
            image.seek(0)
        frame = image.convert("RGB")
        if max(frame.size) > _PIL_MAX_SIDE:
            frame.thumbnail((_PIL_MAX_SIDE, _PIL_MAX_SIDE))
        buffer = BytesIO()
        frame.save(buffer, format="JPEG", quality=85)
    except Exception:  # noqa: BLE001 - 媒体重编失败按无图处理。
        return None
    return _encode_image_bytes(buffer.getvalue(), "image/jpeg")


def _gif_filmstrip_data_url(path: Path) -> str | None:
    """动图抽 ≤3 帧拼成横向长条（单图预算内表达运动过程）；失败返回 None。"""
    from io import BytesIO

    try:
        from PIL import Image

        with Image.open(path) as image:
            return _gif_strip_from_image(image)
    except Exception:  # noqa: BLE001 - 拼条失败按无图处理。
        return None


def _gif_strip_from_image(image: Any) -> str | None:
    """动图拼条的 Image 对象核心（供本机路径与远程字节两路复用）。"""
    from io import BytesIO

    try:
        from PIL import Image

        frame_count = int(getattr(image, "n_frames", 1) or 1)
        if frame_count <= 1:
            return _pil_normalize_image(image, first_frame_only=True)
        picks = sorted({
            min(frame_count - 1, round(index * (frame_count - 1) / 2))
            for index in range(3)
        })
        tiles: list = []
        for frame_index in picks:
            image.seek(frame_index)
            tile = image.convert("RGB")
            tile.thumbnail((512, 256))
            tiles.append(tile)
        height = min(tile.height for tile in tiles)
        tiles = [
            tile.resize((max(1, round(tile.width * height / tile.height)), height))
            for tile in tiles
        ]
        strip = Image.new(
            "RGB",
            (sum(tile.width for tile in tiles) + 4 * (len(tiles) - 1), height),
            (255, 255, 255),
        )
        offset = 0
        for tile in tiles:
            strip.paste(tile, (offset, 0))
            offset += tile.width + 4
        buffer = BytesIO()
        strip.save(buffer, format="JPEG", quality=85)
    except Exception:  # noqa: BLE001 - 拼条失败按无图处理。
        return None
    return _encode_image_bytes(buffer.getvalue(), "image/jpeg")


def _image_file_to_data_url(file_ref: str) -> str | None:
    """本机图片文件 → data URL；GIF 取首帧，超大/未知格式经 PIL 重编。"""
    path = _local_path_from_value(file_ref)
    if path is None:
        return None
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size > _MAX_LOCAL_IMAGE_INPUT_BYTES:
        logger.debug(
            "vision: local image too large for data url bytes=%s name=%s",
            size,
            path.name,
        )
        return None
    suffix = path.suffix.lower()
    if suffix == ".gif":
        return _gif_filmstrip_data_url(path) or _pil_normalize(
            path, first_frame_only=True
        )
    try:
        if size <= _MAX_DIRECT_IMAGE_BYTES and suffix in _SUFFIX_MIME:
            return _encode_image_bytes(path.read_bytes(), _SUFFIX_MIME[suffix])
    except OSError:
        return None
    return _pil_normalize(path, first_frame_only=False)


# ---------- 远程图片 bot 侧转 data URL（直传与 OCR 双分支共用） ----------
# QQ 多媒体签名 URL（multimedia.nt.qq.com.cn / gchat.qpic.cn）对第三方 AI
# 服务商不可达：直传分支原样透传 URL 时模型侧取不到图，OCR 分支同样依赖
# 服务商侧抓取——两条分支一起瞎。必须 bot 侧先下载转 data URL 再进请求体。

_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
_MAX_REMOTE_IMAGE_BYTES = _MAX_LOCAL_IMAGE_INPUT_BYTES
_REMOTE_DOWNLOAD_TIMEOUT = 10.0
# FIFO 缓存：同一张图多轮追问/双分支复用不重复下载。
_REMOTE_DATA_URL_CACHE: dict[str, str] = {}
_REMOTE_DATA_URL_CACHE_ORDER: list[str] = []
_REMOTE_DATA_URL_CACHE_CAP = 32


def _download_image_bytes(
    url: str,
    *,
    max_bytes: int = _MAX_REMOTE_IMAGE_BYTES,
) -> bytes | None:
    request = urllib.request.Request(url, headers={"User-Agent": _DESKTOP_UA})
    host = urlparse(url).hostname or ""
    try:
        with urllib.request.urlopen(request, timeout=_REMOTE_DOWNLOAD_TIMEOUT) as response:  # noqa: S110
            payload = response.read(max_bytes + 1)
    except Exception as exc:  # noqa: BLE001 - 下载失败降级保留原 URL 并留诊断。
        logger.warning(
            "vision: remote image download failed host=%s err=%s", host, exc
        )
        return None
    if len(payload) > max_bytes:
        logger.warning(
            "vision: remote image too large bytes=%s host=%s", len(payload), host
        )
        return None
    return payload


def _image_bytes_to_data_url(data: bytes) -> str | None:
    """图片字节 → data URL：GIF/动图抽帧条，其余缩边 JPEG；失败返回 None。"""
    from io import BytesIO

    try:
        from PIL import Image

        with Image.open(BytesIO(data)) as image:
            if (image.format or "").lower() == "gif":
                strip = _gif_strip_from_image(image)
                if strip:
                    return strip
                return _pil_normalize_image(image, first_frame_only=True)
            return _pil_normalize_image(image, first_frame_only=False)
    except Exception:  # noqa: BLE001 - 解码失败按无图处理。
        return None


def prepare_vision_image_urls(
    urls: list[str],
    *,
    limit: int = _DEFAULT_MAX_IMAGES,
) -> list[str]:
    """把远程 http 图片 URL 转成 data URL（bot 侧下载）；本地/data URL 原样。

    失败时保留原 URL 兜底（个别服务商侧或许能取到），并已留 warning 日志。
    """
    prepared: list[str] = []
    for url in (urls or [])[: max(1, limit)]:
        if not url.startswith("http"):
            prepared.append(url)
            continue
        cached = _REMOTE_DATA_URL_CACHE.get(url)
        if cached:
            prepared.append(cached)
            continue
        data = _download_image_bytes(url)
        converted = _image_bytes_to_data_url(data) if data else None
        if converted is None:
            prepared.append(url)
            continue
        _REMOTE_DATA_URL_CACHE[url] = converted
        _REMOTE_DATA_URL_CACHE_ORDER.append(url)
        while len(_REMOTE_DATA_URL_CACHE_ORDER) > _REMOTE_DATA_URL_CACHE_CAP:
            evicted = _REMOTE_DATA_URL_CACHE_ORDER.pop(0)
            _REMOTE_DATA_URL_CACHE.pop(evicted, None)
        prepared.append(converted)
    return prepared


def extract_image_urls(raw_segments: list[dict[str, Any]] | None) -> list[str]:
    """从消息原始段提取图片源：本机路径（file://、绝对路径）转 data URL，http URL 透传。

    image 与 mface（QQ 表情包）都算；GIF 取首帧。解析不了的段静默跳过。
    """
    urls: list[str] = []
    for segment in raw_segments or []:
        if not isinstance(segment, dict):
            continue
        if str(segment.get("type", "")).lower() not in _IMAGE_SEGMENT_TYPES:
            continue
        data = segment.get("data") or {}
        if not isinstance(data, dict):
            continue
        candidates = [
            str(data.get(key) or "").strip() for key in ("url", "file", "path")
        ]
        local_url = ""
        http_url = ""
        for candidate in candidates:
            if not candidate:
                continue
            if candidate.startswith("http") and not http_url:
                http_url = candidate
                continue
            if not local_url:
                local_url = _image_file_to_data_url(candidate) or ""
        resolved = local_url or http_url
        if resolved and resolved not in urls:
            urls.append(resolved)
    return urls


def extract_video_source(raw_segments: list[dict[str, Any]] | None) -> str | None:
    """取第一个可解析的视频段来源：本机路径优先，其次 http URL。"""
    for segment in raw_segments or []:
        if not isinstance(segment, dict):
            continue
        if str(segment.get("type", "")).lower() not in _VIDEO_SEGMENT_TYPES:
            continue
        data = segment.get("data") or {}
        if not isinstance(data, dict):
            continue
        for key in ("url", "file", "path"):
            value = str(data.get(key) or "").strip()
            if not value:
                continue
            if value.startswith("http"):
                return value
            local = _local_path_from_value(value)
            if local is not None:
                return str(local)
    return None


def _find_ffmpeg_locate() -> str:
    from plugins.bot_unified_runtime.sources.downloader import _find_ffmpeg

    return _find_ffmpeg()


def _http_input_opts(source: str) -> list[str]:
    """http 视频源加桌面 UA（QQ 视频直链对 ffmpeg 默认 UA 返回 403，实测）。"""
    if str(source or "").startswith("http"):
        return ["-user_agent", _DESKTOP_UA]
    return []


def _probe_video_duration(ffmpeg: str, source: str, timeout_seconds: float) -> float:
    """用 ffmpeg -i 的 stderr 解析时长；解析失败返回 0（调用方给默认窗口）。"""
    try:
        result = subprocess.run(
            [ffmpeg, "-nostdin", *_http_input_opts(source), "-i", source],
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return 0.0
    match = re.search(
        r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)",
        result.stderr.decode("utf-8", errors="replace"),
    )
    if not match:
        return 0.0
    hours, minutes, seconds = (float(part) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def _extract_video_frames(
    video_source: str,
    count: int,
    out_dir: str,
    timeout_seconds: float = 30.0,
) -> list[Path]:
    """ffmpeg 均匀抽帧落盘为 JPEG；ffmpeg 缺失或失败返回空列表。"""
    ffmpeg = _find_ffmpeg_locate()
    if not ffmpeg:
        logger.info("video frames skipped: ffmpeg not found")
        return []
    duration = _probe_video_duration(ffmpeg, video_source, timeout_seconds)
    # 时长未知时按 10s 窗口抽帧，保证短视频仍然均匀、长视频至少覆盖开头。
    fps = count / (duration if duration > 0 else 10.0)
    command = [
        ffmpeg,
        "-nostdin",
        "-y",
        *_http_input_opts(video_source),
        "-i",
        video_source,
        "-vf",
        f"fps={fps:.5f},scale=854:-2",
        "-frames:v",
        str(count),
        "-qscale:v",
        "3",
        str(Path(out_dir) / "frame_%03d.jpg"),
    ]
    try:
        subprocess.run(
            command,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("video frame extraction failed type=%s", type(exc).__name__)
        return []
    return sorted(Path(out_dir).glob("frame_*.jpg"))[:count]


def _flatten_vision_entries(
    registry: Any,
    *,
    resolve_key: bool = False,
    config: object = None,
) -> dict[str, dict[str, Any]]:
    """把注册表统一展平成 id -> 条目；id 支持单条目或条目列表。

    列表形态按 ``id#序号`` 展开；resolve_key 时把 env: 引用解析成真实密钥。
    """
    from plugins.bot_unified_runtime.llm.model_router import _resolve_api_key

    flattened: dict[str, dict[str, Any]] = {}
    if not isinstance(registry, dict):
        return flattened
    for group_id, value in registry.items():
        group = str(group_id)
        items = value if isinstance(value, list) else [value]
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            model = str(item.get("model", "")).strip()
            base_url = str(item.get("base_url", "")).strip()
            if not model or not base_url:
                continue
            entry_id = f"{group}#{index}" if isinstance(value, list) else group
            entry = dict(item)
            if resolve_key:
                entry["api_key"] = _resolve_api_key(
                    str(entry.get("api_key", "")), config
                )
            flattened[entry_id] = entry
    return flattened


class DynamicVisionProvider:
    """视觉模型动态提供器：env 注册表 + 运行时注册表合并，按优先级故障转移。"""

    def __init__(
        self,
        config: object,
        *,
        dynamic_registry: Any = None,
        settings_store: Any = None,
    ) -> None:
        self._config = config
        self._dynamic_registry = dynamic_registry
        self._settings_store = settings_store
        self._providers: dict[tuple[str, str, str], Any] = {}
        self.last_attempts: list[str] = []

    def is_enabled(self) -> bool:
        if self._settings_store is not None:
            try:
                return bool(
                    self._settings_store.get_or(
                        "BOT_VISION_ENABLED",
                        bool(getattr(self._config, "bot_vision_enabled", False)),
                    )
                )
            except (KeyError, OSError, TypeError, ValueError):  # 开关读取失败回退 .env 值。
                logger.debug("vision enabled flag read failed; falling back to env")
        return bool(getattr(self._config, "bot_vision_enabled", False))

    def _merged_entries(self) -> dict[str, dict[str, Any]]:
        merged = _flatten_vision_entries(
            getattr(self._config, "bot_vision_model_registry", None),
            resolve_key=True,
            config=self._config,
        )
        if self._dynamic_registry is not None:
            try:
                dynamic = self._dynamic_registry() or {}
            except Exception:  # noqa: BLE001 - 运行时注册表读取失败沿用 env。
                dynamic = {}
            merged.update(
                _flatten_vision_entries(dynamic, resolve_key=True, config=self._config)
            )
        return merged

    def _provider_for(self, entry_id: str, entry: dict[str, Any]) -> Any | None:
        api_key = str(entry.get("api_key", "")).strip()
        model = str(entry.get("model", "")).strip()
        base_url = str(entry.get("base_url", "")).strip()
        if not api_key or not model or not base_url:
            return None
        fingerprint = (model, base_url, api_key)
        if fingerprint not in self._providers:
            self._providers[fingerprint] = OpenAICompatibleLLMProvider(
                api_key=api_key,
                model=model,
                base_url=base_url,
                proxy=str(getattr(self._config, "bot_download_proxy", "") or ""),
                timeout_seconds=float(
                    getattr(self._config, "bot_vision_timeout_seconds", 20.0) or 20.0
                ),
            )
        return self._providers[fingerprint]

    def generate(self, messages: list[dict[str, Any]], **kwargs: object) -> Any:
        self.last_attempts = []
        candidates = sorted(
            self._merged_entries().items(),
            key=lambda kv: (
                kv[1].get("priority", 100)
                if isinstance(kv[1].get("priority", 100), int)
                else 100,
                kv[0],
            ),
        )
        started = time.monotonic()
        deadline = float(
            getattr(self._config, "bot_vision_timeout_seconds", 20.0) or 20.0
        ) * 2
        last_error: LLMProviderError | None = None
        for entry_id, entry in candidates[:_MAX_VISION_FAILOVER_ATTEMPTS]:
            if last_error is not None and (time.monotonic() - started) > deadline:
                self.last_attempts.append("vision:deadline")
                break
            provider = self._provider_for(entry_id, entry)
            if provider is None:
                last_error = LLMProviderError(
                    f"vision model {entry_id} is missing key/model/base_url",
                    error_kind="config_missing",
                )
                self.last_attempts.append(f"{entry_id}:config_missing")
                continue
            try:
                reply = provider.generate(messages, **kwargs)
            except LLMProviderError as exc:
                last_error = exc
                self.last_attempts.append(f"{entry_id}:{exc.error_kind}")
                continue
            except Exception as exc:  # noqa: BLE001 - 未分类异常统一为可转移错误。
                last_error = LLMProviderError(
                    f"vision model {entry_id} failed: {type(exc).__name__}",
                    error_kind="provider_error",
                )
                self.last_attempts.append(f"{entry_id}:provider_error")
                continue
            self.last_attempts.append(f"{entry_id}:success")
            return reply
        if last_error is not None:
            raise last_error
        raise LLMProviderError(
            "no vision model available",
            error_kind="provider_not_configured",
        )


def build_vision_provider(
    config: object,
    *,
    dynamic_registry: Any = None,
    settings_store: Any = None,
) -> DynamicVisionProvider | None:
    """组装动态视觉 provider；注册表完全为空时返回 None（零开销跳过）。

    开关（BOT_VISION_ENABLED）在每次调用时读取，支持运行时热切换。
    """
    has_env = bool(_flatten_vision_entries(
        getattr(config, "bot_vision_model_registry", None)
    ))
    has_dynamic = False
    if dynamic_registry is not None:
        try:
            has_dynamic = bool(_flatten_vision_entries(dynamic_registry() or {}))
        except Exception:  # noqa: BLE001 - 注册表读取失败按空处理。
            has_dynamic = False
    if not has_env and not has_dynamic:
        return None
    return DynamicVisionProvider(
        config,
        dynamic_registry=dynamic_registry,
        settings_store=settings_store,
    )


def _clip(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return f"{value[: max_chars - 1]}…"


def describe_images(
    provider: Any,
    *,
    image_urls: list[str],
    query_text: str = "",
    max_images: int = _DEFAULT_MAX_IMAGES,
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> str:
    """调用视觉模型输出紧凑识别结果；任何失败返回空串，绝不阻断主回复。"""
    if provider is None or not image_urls:
        return ""
    limit = max(1, int(max_images))
    # QQ 多媒体签名 URL 服务商侧取不到：bot 侧先下载转 data URL（见 §14.6.4）。
    image_urls = prepare_vision_image_urls(list(image_urls), limit=limit)
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "用户附带了图片。用户随图消息："
                f"{_clip(query_text, 200) or '（无文字）'}"
            ),
        }
    ]
    for url in image_urls[:limit]:
        content.append({"type": "image_url", "image_url": {"url": url}})
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _VISION_SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]
    try:
        reply = provider.generate(messages, temperature=0.1, max_tokens=400)
    except LLMProviderError as exc:
        logger.warning(
            "vision describe failed kind=%s attempts=%s",
            exc.error_kind,
            getattr(provider, "last_attempts", []),
        )
        return ""
    except Exception:
        logger.exception("vision describe failed")
        return ""
    text = str(getattr(reply, "text", "") or "").strip()
    if not text:
        return ""
    return _clip(text, max(80, int(max_chars)))


def describe_video(
    provider: Any,
    *,
    video_source: str,
    query_text: str = "",
    frames: int = 4,
    max_chars: int = _DEFAULT_MAX_CHARS,
    timeout_seconds: float = 30.0,
) -> str:
    """视频抽帧 → 单次 VLM 调用输出紧凑摘要；任何失败返回空串，绝不阻断主回复。"""
    if provider is None or not video_source:
        return ""
    frame_dir = tempfile.mkdtemp(prefix="bot_video_frames_")
    try:
        frame_paths = _extract_video_frames(
            video_source,
            max(1, int(frames)),
            frame_dir,
            timeout_seconds,
        )
        if not frame_paths:
            return ""
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    "用户附带了一个视频（以下为按时间顺序抽取的关键帧）。"
                    f"用户随视频消息：{_clip(query_text, 200) or '（无文字）'}"
                ),
            }
        ]
        for frame in frame_paths:
            try:
                data = frame.read_bytes()
            except OSError:
                continue
            content.append(
                {"type": "image_url", "image_url": {"url": _encode_image_bytes(data, "image/jpeg")}}
            )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _VIDEO_SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ]
        try:
            reply = provider.generate(messages, temperature=0.1, max_tokens=500)
        except LLMProviderError as exc:
            logger.warning(
                "vision video describe failed kind=%s attempts=%s",
                exc.error_kind,
                getattr(provider, "last_attempts", []),
            )
            return ""
        except Exception:  # 识别失败不阻断聊天。
            logger.exception("vision video describe failed")
            return ""
        text = str(getattr(reply, "text", "") or "").strip()
        if not text:
            return ""
        return _clip(text, max(80, int(max_chars)))
    finally:
        shutil.rmtree(frame_dir, ignore_errors=True)


def describe_subscription_item(
    provider: Any,
    payload: dict[str, Any],
    *,
    max_images: int = 1,
    max_chars: int = 200,
) -> str:
    """订阅推送的 vision 增强：无文本条目补一行图片描述；任何失败返回空串。

    调用方负责按 BOT_VISION_ENABLED 等开关决定是否传入 provider。
    """
    if provider is None or not isinstance(payload, dict):
        return ""
    urls: list[str] = []
    for media in payload.get("media") or []:
        if isinstance(media, dict):
            url = str(media.get("preview_image_url") or media.get("url") or "")
            if url.startswith("http"):
                urls.append(url)
    if not urls:
        for key in ("cover", "image", "thumbnail"):
            url = str(payload.get(key) or "")
            if url.startswith("http"):
                urls.append(url)
    if not urls:
        return ""
    return describe_images(
        provider,
        image_urls=urls,
        query_text=str(payload.get("title") or ""),
        max_images=max_images,
        max_chars=max_chars,
    )
