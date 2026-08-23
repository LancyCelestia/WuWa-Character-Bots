"""视频下载与媒体分析（基于 yt-dlp，能力层专用）。

职责：
- ``probe``：不下载，取元数据并做媒体分析（分辨率/时长/HDR/杜比视界/
  音频码率/采样率/声道/Hi-Res/杜比全景声推断）。
- ``download``：下载到 ``data/downloads/``（git 忽略），带大小与格式上限。

Cookie：直接喂 Netscape 格式 cookies 文件（BOT_COOKIES_FILE），
yt-dlp 按域名自动匹配；代理走 BOT_DOWNLOAD_PROXY（大陆拉油管用）。

分析标签都是「尽力而为」的推断（来自 yt-dlp 元数据），文案带"疑似"
字样，不夸大。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yt_dlp
except Exception:  # noqa: BLE001 - 可选依赖，缺失时功能降级。
    yt_dlp = None  # type: ignore[assignment]

_LOSSLESS_CODECS = {"flac", "alac", "wavpack", "ape", "wav", "aiff", "dsf", "dff"}
_ATMOS_HINTS = ("atmos", "ec-3", "eac3", "ac-4", "joc")
_DV_HINTS = ("dolby vision", "dvhe", "dvh1")


@dataclass
class MediaAnalysis:
    """媒体分析结果（无文件时也返回）。"""

    title: str = ""
    duration_seconds: int = 0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    vcodec: str = ""
    acodec: str = ""
    audio_bitrate_kbps: float = 0.0
    video_bitrate_kbps: float = 0.0
    sample_rate: int = 0
    channels: int = 0
    filesize_bytes: int = 0
    ext: str = ""
    hdr: str = ""  # 空=否；例如 "HDR10" / "杜比视界"
    audio_quality: str = ""  # 空=普通；例如 "Hi-Res" / "杜比全景声"
    labels: dict = field(default_factory=dict)

    def resolution(self) -> str:
        if self.width and self.height:
            return f"{self.width}×{self.height}"
        return "-"

    def duration_text(self) -> str:
        seconds = max(0, self.duration_seconds)
        return f"{seconds // 60}分{seconds % 60}秒"

    def summary_lines(self) -> list[str]:
        lines = [f"分辨率：{self.resolution()}，时长：{self.duration_text()}"]
        if self.fps:
            lines.append(f"帧率：{self.fps:.0f}fps，编码：{self.vcodec or '-'}")
        if self.hdr:
            lines.append(f"画面动态范围：{self.hdr}")
        audio_parts = [f"音频：{self.acodec or '-'}"]
        if self.audio_bitrate_kbps:
            audio_parts.append(f"{self.audio_bitrate_kbps:.0f}kbps")
        if self.sample_rate:
            audio_parts.append(f"{self.sample_rate / 1000:.1f}kHz")
        if self.channels:
            audio_parts.append(f"{self.channels}声道")
        lines.append(" · ".join(audio_parts))
        if self.audio_quality:
            lines.append(f"音频品质标注：{self.audio_quality}")
        if self.filesize_bytes:
            lines.append(f"文件大小：{self.filesize_bytes / 1048576:.1f}MB")
        return lines


@dataclass
class DownloadOutcome:
    path: str = ""
    analysis: MediaAnalysis | None = None
    error: str = ""


def _detect_video_quality(formats: list[dict], *, codec: str) -> tuple[str, str]:
    """从格式列表推断 HDR / 杜比视界 / 杜比全景声 / Hi-Res（尽力而为）。"""
    hdr = ""
    audio_quality = ""
    for fmt in formats or []:
        note = str(fmt.get("format_note") or "").lower()
        vcodec = str(fmt.get("vcodec") or "").lower()
        acodec = str(fmt.get("acodec") or "").lower()
        joined = f"{vcodec} {acodec} {note}"
        if not hdr:
            if any(hint in joined for hint in _DV_HINTS):
                hdr = "杜比视界"
            elif vcodec.startswith(("vp9.2", "av01")) or "hdr" in note:
                hdr = "HDR"
        if not audio_quality:
            if any(hint in joined for hint in _ATMOS_HINTS):
                audio_quality = "疑似杜比全景声"
    # 主音频流判断 Hi-Res
    if codec.lower() in _LOSSLESS_CODECS:
        audio_quality = "Hi-Res（无损）"
    elif audio_quality == "":
        sample_rate = 0
        for fmt in formats or []:
            if fmt.get("acodec") not in (None, "none") and isinstance(fmt.get("asr"), (int, float)):
                sample_rate = max(sample_rate, int(fmt["asr"]))
        if sample_rate >= 88200:
            audio_quality = "疑似Hi-Res"
    return hdr, audio_quality


def _analysis_from_info(info: dict) -> MediaAnalysis:
    formats = info.get("formats") or []
    vcodec = str(info.get("vcodec") or "")
    acodec = str(info.get("acodec") or "")
    hdr, audio_quality = _detect_video_quality(formats, codec=acodec)
    filesize = info.get("filesize") or info.get("filesize_approx") or 0
    if not filesize and formats:
        filesize = max(
            (fmt.get("filesize") or fmt.get("filesize_approx") or 0)
            for fmt in formats
        )
    # 视频码率：优先 vbr；缺失时用总码率减音频码率估算。
    abr = float(info.get("abr") or 0.0)
    vbr = float(info.get("vbr") or 0.0)
    if not vbr:
        tbr = float(info.get("tbr") or 0.0)
        if tbr and abr:
            vbr = max(0.0, tbr - abr)
    # 文件大小未知时用 总码率×时长 估算（流媒体常用）。
    if not filesize and info.get("tbr") and info.get("duration"):
        try:
            filesize = int(float(info["tbr"]) * 1000 / 8 * float(info["duration"]))
        except (TypeError, ValueError):
            filesize = 0
    return MediaAnalysis(
        title=str(info.get("title") or ""),
        duration_seconds=int(info.get("duration") or 0),
        width=int(info.get("width") or 0),
        height=int(info.get("height") or 0),
        fps=float(info.get("fps") or 0.0),
        vcodec=vcodec,
        acodec=acodec,
        audio_bitrate_kbps=abr,
        video_bitrate_kbps=vbr,
        sample_rate=int(info.get("asr") or 0),
        channels=int(info.get("audio_channels") or 0),
        filesize_bytes=int(filesize or 0),
        ext=str(info.get("ext") or ""),
        hdr=hdr,
        audio_quality=audio_quality,
    )


def _find_ffmpeg(explicit_path: str = "") -> str:
    """定位 ffmpeg：显式配置 → PATH → winget 安装目录（Windows）。"""
    if explicit_path and Path(explicit_path).exists():
        return explicit_path
    import shutil

    found = shutil.which("ffmpeg")
    if found:
        return found
    import os

    winget_base = Path(
        os.environ.get("LOCALAPPDATA", "")
    ) / "Microsoft" / "WinGet" / "Packages"
    try:
        for candidate in winget_base.rglob("ffmpeg.exe"):
            return str(candidate)
    except OSError:
        return ""
    return ""


class MediaDownloader:
    """yt-dlp 封装：probe（元数据）+ download（落盘）。"""

    def __init__(
        self,
        *,
        cookies_file: str = "",
        proxy: str = "",
        download_dir: str = "data/downloads",
        max_bytes: int = 200 * 1048576,
        max_height: int = 1080,
        timeout_seconds: int = 120,
        ffmpeg_path: str = "",
        cache_max_bytes: int = 0,
        cache_max_age_days: int = 0,
    ) -> None:
        self.cookies_file = str(cookies_file or "")
        self.proxy = str(proxy or "")
        self.download_dir = Path(download_dir)
        self.max_bytes = int(max_bytes)
        self.max_height = int(max_height)
        self.timeout_seconds = int(timeout_seconds)
        self.ffmpeg_path = _find_ffmpeg(str(ffmpeg_path or ""))
        self.cache_max_bytes = int(cache_max_bytes)
        self.cache_max_age_days = int(cache_max_age_days)
        self._lock = threading.Lock()

    def available(self) -> bool:
        return yt_dlp is not None

    def _base_opts(self, *, skip_download: bool) -> dict:
        opts: dict[str, Any] = {
            "skip_download": skip_download,
            "quiet": True,
            "noprogress": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 30,
            "retries": 1,
        }
        if self.cookies_file and Path(self.cookies_file).exists():
            opts["cookiefile"] = self.cookies_file
        if self.proxy:
            opts["proxy"] = self.proxy
        if self.ffmpeg_path:
            opts["ffmpeg_location"] = self.ffmpeg_path
        return opts

    def probe(self, url: str) -> MediaAnalysis:
        if not self.available():
            raise RuntimeError("yt-dlp 未安装，无法做媒体分析")
        with self._lock:
            opts = self._base_opts(skip_download=True)
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info is None:
                    raise RuntimeError("yt-dlp 返回空元数据")
                if info.get("_type") == "playlist" and info.get("entries"):
                    info = info["entries"][0] or info
                return _analysis_from_info(info)

    def _download_once(
        self,
        url: str,
        *,
        single_file: bool = False,
        height_cap: int | None = None,
    ) -> DownloadOutcome:
        opts = self._base_opts(skip_download=False)
        cap = int(height_cap or 0)
        if single_file:
            # 无 ffmpeg 时的降级：只取单文件（音视频一体）。
            fmt = f"best[height<={cap}]/best" if cap else "best"
            merge = {}
        else:
            if cap:
                fmt = (
                    f"bestvideo[height<={cap}]+bestaudio/"
                    f"best[height<={cap}]/best"
                )
            else:
                # 优先最高画质（含 8K/Hi-Res），单文件受 max_filesize 约束。
                fmt = "bestvideo+bestaudio/best"
            merge = {"merge_output_format": "mp4"}
        opts.update(
            {
                "outtmpl": str(self.download_dir / "%(id)s.%(ext)s"),
                "format": fmt,
                "max_filesize": self.max_bytes,
                **merge,
            }
        )
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                return DownloadOutcome(error="yt-dlp 返回空结果")
            if info.get("_type") == "playlist" and info.get("entries"):
                info = info["entries"][0] or info
            analysis = _analysis_from_info(info)
            path = str(
                Path(self.download_dir)
                / f"{info.get('id', 'video')}.{info.get('ext') or 'mp4'}"
            )
            prepared = ydl.prepare_filename(info)
            if prepared and Path(prepared).exists():
                path = str(Path(prepared))
            if not Path(path).exists():
                merged = Path(str(prepared).rsplit(".", 1)[0] + ".mp4")
                if merged.exists():
                    path = str(merged)
            return DownloadOutcome(path=path, analysis=analysis)

    def download(self, url: str) -> DownloadOutcome:
        if not self.available():
            return DownloadOutcome(error="yt-dlp 未安装，无法下载")
        self.download_dir.mkdir(parents=True, exist_ok=True)
        # 画质阶梯：最高画质(8K/Hi-Res) → 2160 → 1440 → 1080 → 720，超 1GB 自动降级。
        caps: list[int | None]
        if self.max_height and self.max_height > 0:
            caps = [self.max_height]
        else:
            caps = [None, 2160, 1440, 1080, 720]
        last_error = "未知错误"
        with self._lock:
            for height_cap in caps:
                try:
                    outcome = self._download_once(url, height_cap=height_cap)
                    if outcome.path and Path(outcome.path).exists():
                        try:
                            from plugins.bot_unified_runtime.runtime.cache_policy import enforce_quota

                            enforce_quota(
                                self.download_dir,
                                max_bytes=self.cache_max_bytes,
                                max_age_days=self.cache_max_age_days,
                            )
                        except Exception:  # noqa: BLE001
                            pass
                        return outcome
                    last_error = outcome.error or last_error
                except Exception as exc:  # noqa: BLE001 - 画质失败降级。
                    message = str(exc)
                    if "ffmpeg" in message.lower() or "merge" in message.lower():
                        try:
                            return self._download_once(
                                url, single_file=True, height_cap=height_cap
                            )
                        except Exception as inner:  # noqa: BLE001
                            last_error = f"{type(inner).__name__}: {str(inner)[:160]}"
                            continue
                    last_error = f"{type(exc).__name__}: {str(exc)[:160]}"
            return DownloadOutcome(error=last_error)
