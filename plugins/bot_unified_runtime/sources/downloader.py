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

import copy
import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.cookiejar import Cookie
from pathlib import Path
from typing import Any

try:
    import yt_dlp
except Exception:  # noqa: BLE001 - 可选依赖，缺失时功能降级。
    yt_dlp = None  # type: ignore[assignment]

_LOSSLESS_CODECS = {"flac", "alac", "wavpack", "ape", "wav", "aiff", "dsf", "dff"}
_ATMOS_HINTS = ("atmos", "ec-3", "eac3", "ac-4", "joc")
_DV_HINTS = ("dolby vision", "dvhe", "dvh1")
logger = logging.getLogger(__name__)


class _SafeMediaLogger:
    """yt-dlp may include signed URLs and credentials even with quiet=True."""

    def debug(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        pass

    def error(self, message: str) -> None:
        # The caller reports a sanitized operational error; do not print raw logs.
        pass


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


def _dynamic_range_tier(fmt: dict) -> int:
    """画面动态范围档位：3=杜比视界 > 2=HDR > 1=SDR。"""
    dynamic = str(fmt.get("dynamic_range") or "").upper()
    vcodec = str(fmt.get("vcodec") or "").lower()
    note = str(fmt.get("format_note") or "").lower()
    if "DOLBY" in dynamic or "dolby vision" in note or any(h in vcodec for h in _DV_HINTS):
        return 3
    if (dynamic and dynamic != "SDR") or "hdr" in note:
        return 2
    return 1


def _audio_rank(fmt: dict) -> tuple[int, int, float, int]:
    """音频档位：Hi-Res（无损）> 杜比全景声 > 普通；同级码率/采样率高者优先。"""
    acodec = str(fmt.get("acodec") or "").lower()
    lossless = 1 if acodec in _LOSSLESS_CODECS else 0
    dolby = 1 if any(h in acodec for h in _ATMOS_HINTS) else 0
    return lossless, dolby, float(fmt.get("abr") or 0.0), int(fmt.get("asr") or 0)


def _fmt_size(fmt: dict, duration_seconds: float) -> int:
    """格式大小：filesize 优先，缺失时用 总码率×时长 估算（未知返回 0）。"""
    size = fmt.get("filesize") or fmt.get("filesize_approx") or 0
    if size:
        return int(size)
    tbr = float(fmt.get("tbr") or 0.0)
    if tbr > 0 and duration_seconds > 0:
        return int(tbr * 1000 / 8 * duration_seconds)
    return 0


def select_media_streams(
    formats: list[dict],
    *,
    duration_seconds: float = 0.0,
    height_cap: int = 0,
    max_bytes: int = 0,
) -> tuple[dict | None, dict | None, str]:
    """按用户画质要求选流（纯函数，可离线测试）。

    视频顺序：最高分辨率 → 动态范围（杜比视界 > HDR > SDR）→ 帧率 → 码率；
    音频顺序：Hi-Res（无损）→ 杜比全景声 → 码率/采样率。
    音视频组合超过 max_bytes 时回退到小于上限的最高画质组合；
    全部超限返回 (None, None, "over_limit")，不悄悄下载低画质。
    """
    videos = [
        f
        for f in formats or []
        if f.get("vcodec") not in (None, "none") and f.get("height")
    ]
    audios = [
        f for f in formats or [] if f.get("acodec") not in (None, "none")
    ]
    if height_cap > 0 and videos:
        capped = [v for v in videos if int(v.get("height") or 0) <= height_cap]
        videos = capped or videos
    videos.sort(
        key=lambda f: (
            int(f.get("height") or 0),
            _dynamic_range_tier(f),
            float(f.get("fps") or 0.0),
            float(f.get("tbr") or 0.0),
        ),
        reverse=True,
    )
    audios.sort(key=_audio_rank, reverse=True)

    def _within_limit(candidate: dict, other_size: int) -> bool:
        if max_bytes <= 0:
            return True
        size = _fmt_size(candidate, duration_seconds)
        if size <= 0:
            # 大小完全未知时放行（不因元数据缺失拒下载）。
            return True
        return size + other_size <= max_bytes

    best_audio = audios[0] if audios else None
    if not videos:
        if best_audio is None:
            return None, None, "no_streams"
        if _within_limit(best_audio, 0):
            return None, best_audio, ""
        for audio in audios[1:]:
            if _within_limit(audio, 0):
                return None, audio, "audio_downgraded"
        return None, None, "over_limit"
    if best_audio is None:
        for video in videos:
            if _within_limit(video, 0):
                return video, None, ""
        return None, None, "over_limit"
    audio_size = _fmt_size(best_audio, duration_seconds)
    for video in videos:
        if _within_limit(video, audio_size):
            return video, best_audio, ""
    for video in videos:
        for audio in audios[1:]:
            if _within_limit(video, _fmt_size(audio, duration_seconds)):
                return video, audio, "audio_downgraded"
    return None, None, "over_limit"


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
        if not audio_quality and any(hint in joined for hint in _ATMOS_HINTS):
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
        max_bytes: int = 1073741824,
        max_height: int = 0,
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

    def _cookie_snapshot(self) -> tuple[Cookie, ...]:
        """Normalize an export in memory; never hand the original file to yt-dlp.

        The exporter flag controls domain scope; repair only its dot spelling.
        Bad rows are dropped individually, including malformed HttpOnly rows.
        Log counts once per file revision, never paths, cookie names or values.
        """
        if not self.cookies_file:
            return ()
        path = Path(self.cookies_file)
        try:
            stat = path.stat()
            fingerprint = (str(path), stat.st_mtime_ns, stat.st_size)
        except OSError:
            fingerprint = (str(path), -1, -1)
        if getattr(self, "_cookies_fingerprint", None) == fingerprint:
            return self._cached_cookies
        self._cookies_fingerprint = fingerprint
        self._cached_cookies: tuple[Cookie, ...] = ()
        repaired = skipped = 0
        cookies: list[Cookie] = []
        try:
            if fingerprint[2] < 0 or fingerprint[2] > 8 * 1024 * 1024:
                raise OSError("cookie file unavailable or too large")
            content = path.read_text(encoding="utf-8-sig")
            for line in content.splitlines():
                http_only = line.startswith("#HttpOnly_")
                if http_only:
                    line = line[len("#HttpOnly_"):]
                elif not line.strip() or line.startswith("#"):
                    continue
                fields = line.split("\t")
                if len(fields) != 7:
                    skipped += 1
                    continue
                domain, scope, cookie_path, secure, expiry, name, value = fields
                if (scope not in {"TRUE", "FALSE"} or secure not in {"TRUE", "FALSE"}
                        or not name or not cookie_path.startswith("/")
                        or not domain.strip(".") or any(c.isspace() for c in domain)
                        or any(c in domain for c in "/:@\\")):
                    skipped += 1
                    continue
                try:
                    expires = int(expiry) if expiry else 0
                    if expires < 0:
                        raise ValueError("negative expiry")
                except ValueError:
                    skipped += 1
                    continue
                scoped = scope == "TRUE"
                normalized_domain = ("." if scoped else "") + domain.lstrip(".")
                repaired += int(normalized_domain != domain)
                cookies.append(Cookie(
                    version=0, name=name, value=value, port=None, port_specified=False,
                    domain=normalized_domain, domain_specified=scoped, domain_initial_dot=scoped,
                    path=cookie_path, path_specified=True, secure=secure == "TRUE",
                    expires=expires or None, discard=not expires, comment=None, comment_url=None,
                    rest={"HttpOnly": ""} if http_only else {}, rfc2109=False,
                ))
            self._cached_cookies = tuple(cookies)
        except (OSError, UnicodeError):
            skipped += 1
        self.cookie_status = {"accepted": len(cookies), "normalized": repaired, "skipped": skipped}
        if repaired or skipped:
            logger.info("cookie import: accepted=%d normalized=%d skipped=%d; source unchanged",
                        len(cookies), repaired, skipped)
        return self._cached_cookies

    @contextmanager
    def _youtube_dl(self, opts: dict):
        with yt_dlp.YoutubeDL(opts) as ydl:
            # Build the jar using yt-dlp's own class, with no on-disk filename.
            from yt_dlp.cookies import YoutubeDLCookieJar
            jar = YoutubeDLCookieJar()
            for cookie in self._cookie_snapshot():
                jar.set_cookie(copy.copy(cookie))
            ydl.cookiejar = jar
            yield ydl

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
        opts["logger"] = _SafeMediaLogger()
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
            try:
                with self._youtube_dl(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if info is None:
                        raise RuntimeError("yt-dlp 返回空元数据")
                    if info.get("_type") == "playlist" and info.get("entries"):
                        info = info["entries"][0] or info
                    return _analysis_from_info(info)
            except Exception as exc:  # noqa: BLE001 - never leak URL tokens or cookies.
                raise RuntimeError(f"媒体分析失败（{type(exc).__name__}），请检查网络或登录态。") from None


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
            # 按画质/音质优先级显式选流；组合超上限时回退到 <上限 的最高画质，
            # 全部超限则诚实报错，不悄悄下载低画质。
            probe_opts = self._base_opts(skip_download=True)
            with self._youtube_dl(probe_opts) as probe_ydl:
                probe_info = probe_ydl.extract_info(url, download=False)
            if isinstance(probe_info, dict):
                if probe_info.get("_type") == "playlist" and probe_info.get("entries"):
                    probe_info = probe_info["entries"][0] or probe_info
                video_fmt, audio_fmt, selection_note = select_media_streams(
                    probe_info.get("formats") or [],
                    duration_seconds=float(probe_info.get("duration") or 0.0),
                    height_cap=cap,
                    max_bytes=self.max_bytes,
                )
                if video_fmt is None and audio_fmt is None:
                    return DownloadOutcome(
                        error=(
                            "所有画质组合均超过下载大小上限"
                            if selection_note == "over_limit"
                            else "上游未返回可下载媒体流"
                        )
                    )
                parts = []
                if video_fmt is not None and video_fmt.get("format_id"):
                    parts.append(str(video_fmt["format_id"]))
                if (
                    audio_fmt is not None
                    and audio_fmt.get("format_id")
                    and audio_fmt.get("format_id") != (video_fmt or {}).get("format_id")
                ):
                    parts.append(str(audio_fmt["format_id"]))
                if parts:
                    fmt = "+".join(parts) + f"/{fmt}"
        opts.update(
            {
                "outtmpl": str(self.download_dir / "%(id)s.%(ext)s"),
                "format": fmt,
                "max_filesize": self.max_bytes,
                **merge,
            }
        )
        with self._youtube_dl(opts) as ydl:
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
                            from plugins.bot_unified_runtime.runtime.cache_policy import (
                                enforce_quota,
                            )

                            enforce_quota(
                                self.download_dir,
                                max_bytes=self.cache_max_bytes,
                                max_age_days=self.cache_max_age_days,
                            )
                        except Exception:  # noqa: BLE001, S110 - 配额清理失败不影响下载结果。
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
                            last_error = f"媒体下载失败（{type(inner).__name__}），请检查网络或登录态。"
                            continue
                    last_error = f"媒体下载失败（{type(exc).__name__}），请检查网络或登录态。"
            return DownloadOutcome(error=last_error)
