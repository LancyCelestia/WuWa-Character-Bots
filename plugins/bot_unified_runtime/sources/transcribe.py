"""语音消息转写（ASR）：record 段 → ffmpeg 转 mp3 → OpenAI 兼容转写接口。

聊天链路在消息携带语音（record 段，NapCat 提供）且 BOT_ASR_ENABLED 时调用
本模块，把语音转成文字作为不可信上下文注入当前消息，让人格模型"听懂"
语音再回应。

音频来源优先级：NapCat 落盘的本机路径（file:// 或绝对路径）→ http URL
下载。QQ 语音原始格式多为 silk/amr，浏览器与转写接口都不认，统一经
ffmpeg 转成 16kHz 单声道 mp3（体积小、兼容面最广）；ffmpeg 失败时若原
文件本就是 mp3/wav 则直读原字节，否则放弃。

转写模型来自 ``BOT_ASR_MODEL_REGISTRY``（OpenAI 兼容 /audio/transcriptions，
如 bigmodel glm-asr、whisper 系中转），registry 格式与 vision 相同：
``id -> 条目``（单模型）与 ``id -> [条目, ...]``（按条目内 priority 轮询），
支持 ``env:VAR`` 引用密钥。调用失败按优先级转移到下一个候选（最多 3 个）。
未启用或未配置时整条链路零开销跳过，转写失败不阻断聊天。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.llm import LLMProviderError
from plugins.bot_unified_runtime.sources.vision_describe import _local_path_from_value

logger = logging.getLogger(__name__)

_RECORD_SEGMENT_TYPES = {"record"}
_MAX_ASR_FAILOVER_ATTEMPTS = 3
# 超大音频上传徒增超时风险；20MB 足够容纳数分钟语音。
_MAX_AUDIO_BYTES = 20_000_000
_FALLBACK_SUFFIXES = {".mp3", ".wav"}
_SUFFIX_MIME = {".mp3": "audio/mpeg", ".wav": "audio/wav"}


def _find_ffmpeg_locate() -> str:
    from plugins.bot_unified_runtime.sources.downloader import _find_ffmpeg

    return _find_ffmpeg()


def extract_audio_source(raw_segments: list[dict[str, Any]] | None) -> str | None:
    """取第一个可解析的语音段来源：转码产物/本机路径优先，其次 http URL。

    NapCat 的 record 段可能同时携带会过期的 url 与落盘 file 路径，
    落盘字节最可靠；handler 侧经 get_record 预转码的 mp3 存于
    transcoded_path（SILK 裸流 ffmpeg 解不了），作为最高优先级。
    """
    for segment in raw_segments or []:
        if not isinstance(segment, dict):
            continue
        if str(segment.get("type", "")).lower() not in _RECORD_SEGMENT_TYPES:
            continue
        data = segment.get("data") or {}
        if not isinstance(data, dict):
            continue
        http_url = ""
        for key in ("transcoded_path", "file", "path", "url"):
            value = str(data.get(key) or "").strip()
            if not value:
                continue
            if value.startswith("http"):
                if not http_url:
                    http_url = value
                continue
            local = _local_path_from_value(value)
            if local is not None:
                return str(local)
        if http_url:
            return http_url
    return None


def _flatten_asr_entries(
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


class DynamicASRProvider:
    """ASR 动态提供器：env 注册表 + 运行时注册表合并，按优先级故障转移。"""

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
        self._providers: dict[tuple[str, str, str], tuple[str, str, str]] = {}
        self.last_attempts: list[str] = []

    def is_enabled(self) -> bool:
        if self._settings_store is not None:
            try:
                return bool(
                    self._settings_store.get_or(
                        "BOT_ASR_ENABLED",
                        bool(getattr(self._config, "bot_asr_enabled", False)),
                    )
                )
            except (KeyError, OSError, TypeError, ValueError):  # 开关读取失败回退 .env 值。
                logger.debug("asr enabled flag read failed; falling back to env")
        return bool(getattr(self._config, "bot_asr_enabled", False))

    def _merged_entries(self) -> dict[str, dict[str, Any]]:
        merged = _flatten_asr_entries(
            getattr(self._config, "bot_asr_model_registry", None),
            resolve_key=True,
            config=self._config,
        )
        if self._dynamic_registry is not None:
            try:
                dynamic = self._dynamic_registry() or {}
            except Exception:  # noqa: BLE001 - 运行时注册表读取失败沿用 env。
                dynamic = {}
            merged.update(
                _flatten_asr_entries(dynamic, resolve_key=True, config=self._config)
            )
        return merged

    def _provider_for(self, entry: dict[str, Any]) -> tuple[str, str, str] | None:
        """归一化出 (model, base_url, api_key) 三元组并按指纹缓存；缺失返回 None。"""
        api_key = str(entry.get("api_key", "")).strip()
        model = str(entry.get("model", "")).strip()
        base_url = str(entry.get("base_url", "")).strip()
        if not api_key or not model or not base_url:
            return None
        fingerprint = (model, base_url, api_key)
        return self._providers.setdefault(fingerprint, fingerprint)

    def generate(
        self,
        audio_bytes: bytes,
        filename: str,
        *,
        timeout_seconds: float,
        deadline_monotonic: float | None = None,
    ) -> str:
        import httpx

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
        deadline = float(timeout_seconds or 20.0) * 2
        mime = _SUFFIX_MIME.get(Path(filename).suffix.lower(), "audio/mpeg")
        last_error: LLMProviderError | None = None
        for entry_id, entry in candidates[:_MAX_ASR_FAILOVER_ATTEMPTS]:
            if last_error is not None and (time.monotonic() - started) > deadline:
                self.last_attempts.append("asr:deadline")
                break
            if (
                deadline_monotonic is not None
                and time.monotonic() + timeout_seconds > deadline_monotonic
            ):
                # 编排器的整体预算已不足以容纳本次尝试：不再发起点转写请求，
                # 避免编排器放弃后 worker 仍在白烧费用。
                self.last_attempts.append(f"{entry_id}:deadline")
                continue
            candidate = self._provider_for(entry)
            if candidate is None:
                last_error = LLMProviderError(
                    f"asr model {entry_id} is missing key/model/base_url",
                    error_kind="config_missing",
                )
                self.last_attempts.append(f"{entry_id}:config_missing")
                continue
            model, base_url, api_key = candidate
            request_kwargs: dict[str, Any] = {}
            proxy = str(getattr(self._config, "bot_download_proxy", "") or "")
            if proxy:
                # httpx 0.28+ 只认 proxy 单数参数。
                request_kwargs["proxy"] = proxy
            try:
                response = httpx.post(
                    f"{base_url.rstrip('/')}/audio/transcriptions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    files={"file": (filename, audio_bytes, mime)},
                    data={"model": model, "response_format": "json"},
                    timeout=timeout_seconds,
                    **request_kwargs,
                )
                response.raise_for_status()
                text = str(response.json().get("text", "") or "").strip()
            except httpx.HTTPStatusError as exc:
                kind = _classify_status_code(exc.response.status_code)
                last_error = LLMProviderError(
                    f"asr model {entry_id} http {exc.response.status_code}",
                    error_kind=kind,
                )
                self.last_attempts.append(f"{entry_id}:{kind}")
                continue
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = LLMProviderError(
                    f"asr model {entry_id} network error: {type(exc).__name__}",
                    error_kind="network",
                )
                self.last_attempts.append(f"{entry_id}:network")
                continue
            except Exception as exc:  # noqa: BLE001 - 未分类异常统一为可转移错误。
                last_error = LLMProviderError(
                    f"asr model {entry_id} failed: {type(exc).__name__}",
                    error_kind="unknown",
                )
                self.last_attempts.append(f"{entry_id}:unknown")
                continue
            self.last_attempts.append(f"{entry_id}:success")
            return text
        if last_error is not None:
            raise last_error
        raise LLMProviderError(
            "no asr model available",
            error_kind="provider_not_configured",
        )


def _classify_status_code(status: int) -> str:
    if status in (401, 403):
        return "auth"
    if status == 429:
        return "rate_limited"
    if status >= 500:
        return "server"
    return "unknown"


def build_asr_provider(
    config: object,
    *,
    dynamic_registry: Any = None,
    settings_store: Any = None,
) -> DynamicASRProvider | None:
    """组装动态 ASR provider；注册表完全为空时返回 None（零开销跳过）。

    开关（BOT_ASR_ENABLED）在每次调用时读取，支持运行时热切换。
    """
    has_env = bool(_flatten_asr_entries(
        getattr(config, "bot_asr_model_registry", None)
    ))
    has_dynamic = False
    if dynamic_registry is not None:
        try:
            has_dynamic = bool(_flatten_asr_entries(dynamic_registry() or {}))
        except Exception:  # noqa: BLE001 - 注册表读取失败按空处理。
            has_dynamic = False
    if not has_env and not has_dynamic:
        return None
    return DynamicASRProvider(
        config,
        dynamic_registry=dynamic_registry,
        settings_store=settings_store,
    )


def _download_audio(source: str, dest: Path, timeout_seconds: float) -> Path | None:
    """http 拉取语音到 work_dir；失败/超 20MB 返回 None。

    client.stream 逐块累计限读（对齐 meme_library_listener）：不在内存里
    整读 response.content 后才检查大小，恶意/异常大文件超限即弃。
    """
    import httpx

    client_kwargs: dict[str, Any] = {
        "timeout": httpx.Timeout(timeout_seconds, connect=min(8.0, timeout_seconds)),
        "follow_redirects": True,
        "headers": {"User-Agent": "Mozilla/5.0"},
    }
    try:
        with httpx.Client(**client_kwargs) as client, client.stream(
            "GET", source
        ) as response:
            if response.status_code != 200:
                return None
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > _MAX_AUDIO_BYTES:
                    logger.info(
                        "asr skipped: audio download too large bytes>=%s", size
                    )
                    return None
                chunks.append(chunk)
            if not chunks:
                return None
            dest.write_bytes(b"".join(chunks))
    except Exception:  # noqa: BLE001 - 下载异常静默返回 None。
        return None
    return dest


def _prepare_audio(
    source: str,
    work_dir: str,
    *,
    timeout_seconds: float,
) -> tuple[bytes, str] | None:
    """任意来源语音 → 16kHz 单声道 mp3 字节；任何失败返回 None。

    ffmpeg 直转失败（silk/amr 等裸流常见）时，若原文件后缀已是 mp3/wav
    就直接读原字节，否则放弃。产物超过 20MB 视为异常输入，返回 None。
    """
    path: Path | None = None
    if not source.startswith("http"):
        path = _local_path_from_value(source)
    else:
        suffix = Path(source.split("?", 1)[0]).suffix.lower() or ".bin"
        path = _download_audio(source, Path(work_dir) / f"src{suffix}", timeout_seconds)
    if path is None:
        return None
    ffmpeg = _find_ffmpeg_locate()
    out_mp3 = Path(work_dir) / "audio.mp3"
    if ffmpeg:
        try:
            subprocess.run(
                [
                    ffmpeg,
                    "-nostdin",
                    "-y",
                    "-i",
                    str(path),
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-qscale:a",
                    "4",
                    str(out_mp3),
                ],
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            pass
    if out_mp3.is_file() and out_mp3.stat().st_size > 0:
        candidate, name = out_mp3, "audio.mp3"
    elif path.suffix.lower() in _FALLBACK_SUFFIXES:
        # ffmpeg 缺失或直转失败：mp3/wav 本就是转写接口认识的格式，直读原字节。
        candidate, name = path, path.name or f"audio{path.suffix.lower()}"
    else:
        return None
    try:
        if not candidate.is_file() or candidate.stat().st_size <= 0:
            return None
        if candidate.stat().st_size > _MAX_AUDIO_BYTES:
            logger.info("asr skipped: audio too large bytes=%s", candidate.stat().st_size)
            return None
        return candidate.read_bytes(), name
    except OSError:
        return None


def _clip(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return f"{value[: max_chars - 1]}…"


def transcribe_audio(
    provider: Any,
    *,
    audio_source: str,
    timeout_seconds: float = 20.0,
    max_chars: int = 300,
) -> str:
    """语音 → 文本的完整链路；任何失败返回空串，绝不阻断主回复。"""
    if provider is None or not audio_source:
        return ""
    work_dir = tempfile.mkdtemp(prefix="bot_asr_")
    try:
        prepared = _prepare_audio(
            audio_source,
            work_dir,
            timeout_seconds=timeout_seconds,
        )
        if prepared is None:
            logger.info("asr skipped: audio source unusable type=%s", type(audio_source).__name__)
            return ""
        audio_bytes, filename = prepared
        try:
            text = provider.generate(
                audio_bytes,
                filename,
                timeout_seconds=timeout_seconds,
            )
        except LLMProviderError as exc:
            logger.warning(
                "asr transcribe failed kind=%s attempts=%s",
                exc.error_kind,
                getattr(provider, "last_attempts", []),
            )
            return ""
        except Exception:  # 转写失败不阻断聊天。
            logger.exception("asr transcribe failed")
            return ""
        if not text:
            return ""
        return _clip(text, max(80, int(max_chars)))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
