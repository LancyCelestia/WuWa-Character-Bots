"""视频理解编排器：画面抽帧(VLM) + 音轨转写(ASR) + CC 字幕/元数据 → 材料式视频简报。

设计纪律（成本优先）：
- 一次分析只发一次 VLM 请求；CC 字幕与元数据作为文本上下文随同一次调用送入，不额外花钱。
- 已有平台 CC 字幕时默认跳过 ASR（字幕已含语言信息，音频转写是纯增量成本）。
- 简报是"材料"不是答案：给人格模型的事实底稿，出声永远由人格模型完成。
- 简报缓存由调用方（character/media_registry）负责，本模块无状态。
- 原生视频直传（video_url content part，仅部分 OpenAI 兼容供应商支持）默认关闭，
  开启且失败时自动回退抽帧路径。
- 任何单信号失败都降级继续，全部失败返回空文本简报，绝不抛异常。
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.llm import LLMProviderError
from plugins.bot_unified_runtime.sources.vision_describe import (
    _clip,
    _encode_image_bytes,
    _extract_video_frames,
    _local_path_from_value,
)

logger = logging.getLogger(__name__)

_VIDEO_BRIEF_SYSTEM_PROMPT = (
    "你是视频理解器，为聊天机器人解读用户发来的视频：画面已按时间顺序抽成关键帧，"
    "标题/UP主/平台等元数据、平台 CC 字幕与声音转写作为文本线索一并提供。"
    "严格按以下四行格式输出，不要输出任何其他内容：\n"
    "内容：<一两句话概括视频主体与发生了什么>\n"
    "画面文字：<画面/字幕中出现的关键文字，逐字转写；没有写“无”>\n"
    "声音：<依据声音转写与字幕概括说话、音乐等声音信息；没有任何声音材料时写“未分析”>\n"
    "细节：<值得回应的显著细节、动作或情绪>"
)
_MAX_TEXT_CONTEXT_CHARS = 1500
# 超大音频上传徒增超时风险；与 transcribe 的预算一致。
_MAX_AUDIO_BYTES = 20_000_000
_VIDEO_SUFFIX_MIME = {
    ".mp4": "video/mp4",
    ".m4v": "video/x-m4v",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
    ".flv": "video/x-flv",
}


@dataclass
class VideoBrief:
    """视频简报：text 为空表示全部信号缺失，调用方应走失败话术。"""

    text: str
    signals: dict[str, bool]


# 自然语言深挖意图（不依赖 /bot 命令）：仔细看/没看懂/详细讲讲 等。
_DEEP_VIDEO_REQUEST_PATTERN = re.compile(
    r"(仔细|详细|深入|深度|认真)(地)?(看|讲|说|分析|解读|聊|研究|挖)"
    r"|再(看|讲|说)一(遍|次|下)"
    r"|没看懂|没看清|没听清"
    r"|具体(说说|讲讲|解释)"
    r"|展开(说说|讲)"
)


def detect_deep_video_request(text: str) -> bool:
    """识别自然语言的深挖意图；命中且媒体上下文可得时触发重分析（更多帧/全音频）。"""
    return bool(text) and bool(_DEEP_VIDEO_REQUEST_PATTERN.search(text))


def _find_ffmpeg_locate() -> str:
    from plugins.bot_unified_runtime.sources.downloader import _find_ffmpeg

    return _find_ffmpeg()


def _duration_from_stderr(raw: bytes) -> float:
    """从 ffmpeg stderr 解析媒体时长；解析失败返回 0（视为不可知，不报截断）。"""
    match = re.search(
        r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)",
        raw.decode("utf-8", errors="replace"),
    )
    if not match:
        return 0.0
    hours, minutes, seconds = (float(part) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def _extract_audio_clip(
    source: str,
    work_dir: str,
    max_seconds: float,
    *,
    truncated_out: list[bool] | None = None,
) -> tuple[bytes, str] | None:
    """视频 → 16kHz 单声道 mp3 音轨字节（-t 限长）；ffmpeg 缺失/失败返回 None。

    参考 transcribe._prepare_audio 的转码写法，输入换成视频并加 -t 时长上限；
    是否发生截断通过同一次 ffmpeg 输出的 Duration 探测，写回 truncated_out。
    """
    ffmpeg = _find_ffmpeg_locate()
    if not ffmpeg:
        logger.info("video audio clip skipped: ffmpeg not found")
        return None
    out_mp3 = Path(work_dir) / "video_audio.mp3"
    timeout = max(30.0, min(300.0, max_seconds * 2.0))
    try:
        result = subprocess.run(
            [
                ffmpeg,
                "-nostdin",
                "-y",
                "-i",
                source,
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-t",
                f"{max_seconds:.2f}",
                "-qscale:a",
                "4",
                str(out_mp3),
            ],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if truncated_out is not None:
        truncated_out[0] = _duration_from_stderr(result.stderr) > max_seconds + 0.5
    try:
        if out_mp3.is_file() and 0 < out_mp3.stat().st_size <= _MAX_AUDIO_BYTES:
            return out_mp3.read_bytes(), out_mp3.name
    except OSError:
        return None
    return None


def _native_video_content_part(source: str, max_mb: float) -> dict[str, Any] | None:
    """本机视频文件 → base64 video_url content part；不合条件返回 None。

    仅当来源是本机存在的文件且体积 ≤ max_mb 时才构造；http URL、缺失或
    超限文件一律返回 None，由调用方走抽帧路径。
    """
    path = _local_path_from_value(source)
    if path is None:
        return None
    try:
        if path.stat().st_size > int(max_mb * 1024 * 1024):
            logger.info("video native input skipped: file too large")
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if not data:
        return None
    mime = _VIDEO_SUFFIX_MIME.get(path.suffix.lower(), "application/octet-stream")
    return {
        "type": "video_url",
        "video_url": {"url": _encode_image_bytes(data, mime)},
    }


def _text_context_part(
    query: str,
    metadata: str,
    subtitle: str,
    asr_text: str,
) -> dict[str, Any]:
    """把问题/元数据/CC 字幕/ASR 转写拼成一段带小节标题的 text part。"""
    lines = ["用户附带了一个视频，下面是文本线索；画面见随后的关键帧。"]
    if query:
        lines.append(f"用户随视频的问题：{_clip(query, 200)}")
    if metadata:
        lines.append(f"[基本信息]\n{metadata}")
    if subtitle:
        lines.append(f"[平台字幕]\n{_clip(subtitle, _MAX_TEXT_CONTEXT_CHARS)}")
    if asr_text:
        lines.append(f"[声音转写]\n{_clip(asr_text, _MAX_TEXT_CONTEXT_CHARS)}")
    if len(lines) == 1:
        lines.append("（没有文本线索）")
    return {"type": "text", "text": "\n\n".join(lines)}


def _call_vision(vision_provider: Any, content: list[dict[str, Any]]) -> str:
    """单次 VLM 融合调用；LLMProviderError 与任意异常都吞掉，返回空串。"""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _VIDEO_BRIEF_SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]
    try:
        reply = vision_provider.generate(messages, temperature=0.1, max_tokens=500)
    except LLMProviderError as exc:
        logger.warning(
            "video brief vision failed kind=%s attempts=%s",
            exc.error_kind,
            getattr(vision_provider, "last_attempts", []),
        )
        return ""
    except Exception:  # 识别失败降级为无画面信号。
        logger.exception("video brief vision failed")
        return ""
    return str(getattr(reply, "text", "") or "").strip()


def _collect_future(future: Any, remaining: Any) -> Any:
    """按剩余预算收集 worker 结果；超时/异常一律按失败（None）处理。"""
    if future is None:
        return None
    try:
        return future.result(timeout=max(0.05, remaining()))
    except FuturesTimeoutError:
        logger.warning("video brief worker timed out; signal dropped")
        return None
    except Exception as exc:  # noqa: BLE001 - worker 自身已兜底，这里防御未来改动。
        logger.warning("video brief worker failed type=%s", type(exc).__name__)
        return None


def _compose_video_brief(
    *,
    metadata: str,
    asr_text: str,
    subtitle: str,
    vlm_text: str,
    asr_max_seconds: float,
    audio_truncated: bool,
    max_chars: int,
) -> str:
    """按固定小节顺序合成材料式简报；空信号小节不出现，总长裁到 max_chars。"""
    sections = ["[视频档案]"]
    if metadata:
        sections.append(f"基本信息：{metadata}")
    if asr_text:
        sections.append(f"声音转写：{asr_text}")
    if subtitle:
        sections.append(f"字幕摘录：{subtitle}")
    if vlm_text:
        sections.append(f"画面识别：{vlm_text}")
    if asr_text and audio_truncated:
        sections.append(
            f"覆盖说明：音频超出 {asr_max_seconds:g} 秒上限，仅转写了开头部分。"
        )
    return _clip("\n".join(sections), max_chars)


def build_video_brief(
    config: object,
    *,
    vision_provider: Any = None,
    asr_provider: Any = None,
    video_source: str = "",
    subtitle_text: str = "",
    metadata_text: str = "",
    question: str = "",
    frame_loader: Any = None,
    audio_extractor: Any = None,
    deadline_seconds: float | None = None,
    deep: bool = False,
) -> VideoBrief:
    """四路信号 → 材料式视频简报；任何失败降级继续，全部失败返回空文本。"""
    max_frames = max(1, int(getattr(config, "bot_video_max_frames", 6) or 6))
    asr_max_seconds = max(
        1.0, float(getattr(config, "bot_video_asr_max_seconds", 600) or 600)
    )
    skip_asr_with_subtitle = bool(
        getattr(config, "bot_video_skip_asr_with_subtitle", True)
    )
    max_chars = max(80, int(getattr(config, "bot_video_brief_max_chars", 1200) or 1200))
    native_input = bool(getattr(config, "bot_video_native_input", False))
    native_max_mb = max(
        0.1, float(getattr(config, "bot_video_native_max_mb", 20) or 20)
    )
    asr_timeout = float(getattr(config, "bot_asr_timeout_seconds", 20.0) or 20.0)
    if deadline_seconds is not None:
        deadline = max(1.0, float(deadline_seconds))
    else:
        deadline = max(
            1.0,
            float(getattr(config, "bot_video_brief_deadline_seconds", 75.0) or 75.0),
        )
    if deep:
        # 深挖档：更多帧、音频上限放宽到完整时长、无视"有字幕跳过 ASR"。
        max_frames = max(
            max_frames, max(1, int(getattr(config, "bot_video_deep_frames", 16) or 16))
        )
        asr_max_seconds = max(
            asr_max_seconds,
            max(
                1.0,
                float(
                    getattr(config, "bot_video_deep_asr_max_seconds", 1800) or 1800
                ),
            ),
        )
        skip_asr_with_subtitle = False
        deadline = max(
            deadline,
            max(
                1.0,
                float(
                    getattr(config, "bot_video_deep_deadline_seconds", 150.0)
                    or 150.0
                ),
            ),
        )

    source = str(video_source or "").strip()
    subtitle = str(subtitle_text or "").strip()
    metadata = str(metadata_text or "").strip()
    query = str(question or "").strip()

    signals: dict[str, bool] = {
        "frames": False,
        "asr": False,
        "subtitle": bool(subtitle),
        "metadata": bool(metadata),
        "native_video": False,
    }
    if not source and not subtitle and not metadata:
        return VideoBrief("", signals)

    started = time.monotonic()

    def remaining() -> float:
        return deadline - (time.monotonic() - started)

    audio_truncated = [False]

    def run_frames() -> list[Path]:
        out_dir = Path(work_dir) / "frames"
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            if frame_loader is not None:
                loaded = frame_loader(source, max_frames, str(out_dir))
                return [Path(item) for item in (loaded or [])]
            return _extract_video_frames(source, max_frames, str(out_dir))
        except Exception as exc:  # noqa: BLE001 - 抽帧失败按无画面处理。
            logger.warning("video brief frames failed type=%s", type(exc).__name__)
            return []

    def run_asr() -> str:
        truncated: list[bool] = [False]

        def default_clipper(
            src: str, work: str, seconds: float
        ) -> tuple[bytes, str] | None:
            return _extract_audio_clip(src, work, seconds, truncated_out=truncated)

        clipper = audio_extractor or default_clipper
        try:
            prepared = clipper(source, str(work_dir), asr_max_seconds)
        except Exception as exc:  # noqa: BLE001 - 抽音轨失败按无声音处理。
            logger.warning("video brief audio clip failed type=%s", type(exc).__name__)
            return ""
        if prepared is None:
            logger.info("video brief asr skipped: audio track unavailable")
            return ""
        audio_bytes, filename = prepared
        # 长音频需要更久的转写窗口：按上限时长缩放（600s→150s），但不低于
        # 语音消息的配置超时；单次尝试封顶不超过整体 deadline，防止
        # 编排器已放弃后 worker 仍按 150s×3 次故障转移白烧转写费。
        asr_call_timeout = max(
            asr_timeout, min(150.0, asr_max_seconds * 0.25, deadline)
        )
        try:
            text = asr_provider.generate(
                audio_bytes,
                filename,
                timeout_seconds=asr_call_timeout,
                deadline_monotonic=time.monotonic() + remaining(),
            )
        except LLMProviderError as exc:
            logger.warning(
                "video brief asr failed kind=%s attempts=%s",
                exc.error_kind,
                getattr(asr_provider, "last_attempts", []),
            )
            return ""
        except Exception:  # 转写失败按无声音处理。
            logger.exception("video brief asr failed")
            return ""
        text = str(text or "").strip()
        if not text:
            logger.info("video brief asr skipped: empty transcription")
            return ""
        audio_truncated[0] = truncated[0]
        return text

    asr_text = ""
    vlm_text = ""
    work_dir = ""
    frames_future = None
    asr_future = None
    pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bot-video-brief")
    try:
        work_dir = tempfile.mkdtemp(prefix="bot_video_brief_")
        native_part: dict[str, Any] | None = None
        if native_input and vision_provider is not None:
            native_part = _native_video_content_part(source, native_max_mb)
        frames_future = None
        if vision_provider is not None and source and native_part is None:
            frames_future = pool.submit(run_frames)
        asr_future = None
        if (
            asr_provider is not None
            and source
            and not (subtitle and skip_asr_with_subtitle)
        ):
            asr_future = pool.submit(run_asr)
        asr_text = _collect_future(asr_future, remaining) or ""
        signals["asr"] = bool(asr_text)
        if native_part is not None:
            content: list[dict[str, Any]] = [
                _text_context_part(query, metadata, subtitle, asr_text),
                native_part,
            ]
            vlm_text = _call_vision(vision_provider, content)
            if vlm_text:
                signals["native_video"] = True
            else:
                # 原生直传失败：回退抽帧路径再试一次。
                frames_future = pool.submit(run_frames)
        if not vlm_text:
            frame_paths = _collect_future(frames_future, remaining) or []
            content = [_text_context_part(query, metadata, subtitle, asr_text)]
            for frame in frame_paths:
                try:
                    data = frame.read_bytes()
                except OSError:
                    continue
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": _encode_image_bytes(data, "image/jpeg")
                        },
                    }
                )
            if len(content) > 1:
                vlm_text = _call_vision(vision_provider, content)
                signals["frames"] = bool(vlm_text)
    except Exception:  # 编排器兜底：任何意外降级为空简报，绝不抛异常。
        logger.exception("video brief build failed")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
        if work_dir:
            pending = [
                future
                for future in (frames_future, asr_future)
                if future is not None and not future.done()
            ]
            if not pending:
                shutil.rmtree(work_dir, ignore_errors=True)
            else:
                # deadline 打断时 worker 还握着目录句柄（Windows 上立即
                # rmtree 必残留）：交守护线程等 worker 收尾后再清。
                def _reap(futures: list[Any], dir_path: str) -> None:
                    for future in futures:
                        try:
                            future.result(timeout=900.0)
                        except Exception:  # noqa: BLE001, S110 - 清理路径，结果无所谓。
                            pass
                    shutil.rmtree(dir_path, ignore_errors=True)

                threading.Thread(
                    target=_reap,
                    args=(pending, work_dir),
                    daemon=True,
                    name="bot-video-brief-reap",
                ).start()

    if not any(signals.values()):
        return VideoBrief("", signals)
    text = _compose_video_brief(
        metadata=metadata,
        asr_text=asr_text,
        subtitle=subtitle,
        vlm_text=vlm_text,
        asr_max_seconds=asr_max_seconds,
        audio_truncated=audio_truncated[0],
        max_chars=max_chars,
    )
    return VideoBrief(text, signals)
