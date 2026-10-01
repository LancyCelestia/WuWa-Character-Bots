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
import urllib.request
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
    subtitle_path: str = ""  # CC 字幕文件（srt/vtt）；平台无字幕为空。用户裁定：有字幕必存""


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
    """音频档位（用户裁定 2026-09-12）：杜比全景声 > Hi-Res（无损）> 普通高码率。

    同级内按码率/采样率高者优先。
    """
    acodec = str(fmt.get("acodec") or "").lower()
    dolby = 1 if any(h in acodec for h in _ATMOS_HINTS) else 0
    lossless = 1 if acodec in _LOSSLESS_CODECS else 0
    return dolby, lossless, float(fmt.get("abr") or 0.0), int(fmt.get("asr") or 0)


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

    视频顺序（用户裁定 2026-09-12：杜比视界 > HDR > 8K > 4K > 2K >
    1080P60 > 1080P高码率 > 1080P）：动态范围（杜比视界 > HDR > SDR）
    → 分辨率 → 帧率 → 码率；
    音频顺序（用户裁定）：杜比全景声 > Hi-Res（无损）→ 码率/采样率。
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
            _dynamic_range_tier(f),
            int(f.get("height") or 0),
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


class RejectedUrlError(Exception):
    """URL 被下载护栏拒绝（SSRF / 协议 / 内网地址）。

    异常族口径（W4 记账，别留给下一个人重新踩）：本类**不是** ``URLError``／
    ``OSError`` 的子类，所以「只 ``except URLError``」的消费方兜不住它。今天两条
    消化路径都在场，因此不改族（改＝``str(exc)`` 形态随之变化，而这段文本正是要
    进群卡的拒绝原因）：

    - 入口调用点（``download``/``probe``/``eat``/``ssrf_guard``/渲染 ``_orb_route``）
      一律 ``except RejectedUrlError`` 自己吞掉，转成既有的降级形态。
    - 连接层钉定件（``build_pinning_handlers``）把异常从 ``http_open`` 里抛出，
      经 ``opener.open`` 抵达消费方的 broad ``except Exception``——实测两条腿都
      收得住：解析链转 ``ParseHttpError``，``credential_health`` 探针转
      ``network_error`` 报告。⇒ **装配面铺到新的 except 面窄的腿之前，先复核那条腿
      的 except 子句**（这条复核义务也写进 ``build_pinning_handlers`` 的装配清单）。
    """


# 内网与保留网段黑名单（评审 H6）：/bot download 对普通用户开放，若不做地址
# 过滤，任意成员都能让 bot 以自身主机身份请求 http://127.0.0.1:<port>/ 或
# 云元数据地址，形成内网端口扫描 + 云凭据窃取面。这里按「字面量 + DNS 解析」
# 双重判定，避免攻击者用域名指向 127.0.0.1 绕过。
_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "ip6-localhost",
        "ip6-loopback",
        "metadata",
        "metadata.google.internal",
        "metadata.goog",
    }
)
_BLOCKED_NETWORKS = (
    "0.0.0.0/8",
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.0.0.0/24",
    "192.0.2.0/24",
    "192.88.99.0/24",
    "192.168.0.0/16",
    "198.18.0.0/15",
    "198.51.100.0/24",
    "203.0.113.0/24",
    "224.0.0.0/4",
    "240.0.0.0/4",
    "255.255.255.255/32",
    "::/128",
    "::1/128",
    "::ffff:0:0/96",
    "64:ff9b::/96",
    "100::/64",
    "2001:db8::/32",
    "fc00::/7",
    "fe80::/10",
    "ff00::/8",
)
_ALLOWED_SCHEMES = frozenset({"http", "https"})


def _ip_is_blocked(ip_text: str) -> bool:
    import ipaddress

    try:
        address = ipaddress.ip_address(ip_text)
    except ValueError:
        return True
    # IPv4-mapped IPv6（::ffff:127.0.0.1）要按映射后的 v4 判定。
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if any(
        address in ipaddress.ip_network(network, strict=False)
        for network in _BLOCKED_NETWORKS
    ):
        return True
    return bool(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def check_download_url(url: str) -> None:
    """下载入口护栏：非法协议 / 内网 / 保留地址一律拒绝（抛 RejectedUrlError）。

    判据本体＝``check_download_url_resolved``（本文件唯一一份 SSRF 判定），本函数
    是它的薄封装、只丢回一个「过 / 不过」。覆盖度、已知残余与「解析失败=拒绝」
    语义一律见 ``check_download_url_resolved`` 的说明；rebinding 面的收口见
    ``build_pinning_handlers``。
    """
    check_download_url_resolved(url)


def check_download_url_resolved(url: str) -> frozenset[str]:
    """SSRF 咽喉本体：判定 + 把「判定过的那些 IP」原样交回去（解析钉定用）。

    为什么要交回 IP（INCIDENT-20260930 第五节 · 缺口④）：判完即弃 ⇒ 真正的连接
    由后面的 ``socket.create_connection`` **再解一次** DNS，两次解析之间域名可以
    翻面（DNS rebinding：判定那次是公网、连接那次指进 127.0.0.1 / 元数据地址），
    入口护栏的全部判据当场形同虚设。把这一次解析结果交给连接层
    （见 ``build_pinning_handlers``），「判定」与「连接」共用同一次解析，窗口归零。

    覆盖度与已知残余：
    - 协议白名单只放 http/https（挡 file://、ftp://、gopher:// 等）。
    - 主机名先查黑名单（localhost/metadata.*），再对**所有** DNS 解析结果做
      内网判定（不只看第一个，避免多 A 记录轮询绕过）。
    - 本文件内的咽喉调用点只有一处（``_url_rejection_reason``），``download()`` 与
      ``probe()`` 共享同一闸门；跨模块消费方见 ``ssrf_guard``（解析链）、
      ``media_archive``/``notes``/``eat``/``file_gateway``（各自下载口）。
    - 装配面口径（W4）：上面这套「判定 → 同一册地址」的闭环**只在装了钉定件的腿**
      成立，全树装配清单见 ``build_pinning_handlers`` docstring（在册锁比对），
      未装的腿今天的窗口仍旧是「入口判一次、连接再解一次」的老形态。
    - 已知残余：yt-dlp 自己会跟随播放列表/清单里的子 URL，且另有独立的重定向
      解析路径，本函数只在入口校验一次；彻底收敛需在 yt-dlp 侧挂连接级钩子
      （登记为后续项，不在本次修复范围）。
    """
    from urllib.parse import urlsplit

    candidate = (url or "").strip()
    if not candidate:
        raise RejectedUrlError("地址为空")
    parts = urlsplit(candidate)
    scheme = (parts.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise RejectedUrlError(f"只支持 http/https 链接（收到 {scheme or '空协议'}）")
    host = (parts.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise RejectedUrlError("地址缺少主机名")
    if host in _BLOCKED_HOSTNAMES or host.endswith(".localhost"):
        raise RejectedUrlError("该地址指向本机，已拒绝")
    # 字面量 IP：直接判定，不做 DNS（交回同一枚字面量供连接层钉定）。
    import ipaddress

    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if _ip_is_blocked(host):
            raise RejectedUrlError("该地址属于内网/保留网段，已拒绝")
        return frozenset({host})
    # 域名：解析全部结果，任一落在内网即拒绝。
    import socket

    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if scheme == "https" else 80))
    except OSError as exc:
        raise RejectedUrlError(f"域名无法解析：{type(exc).__name__}") from exc
    resolved = {str(info[4][0]) for info in infos if info[4]}
    if not resolved:
        raise RejectedUrlError("域名未解析出任何地址")
    for address in resolved:
        if _ip_is_blocked(address):
            raise RejectedUrlError("该域名解析到内网/保留网段，已拒绝")
    return frozenset(resolved)


def _url_rejection_reason(url: str) -> str | None:
    """SSRF 咽喉的**唯一调用点**（评审 H6 / 审计 D1-F1）：放行 ``None``，拒绝返回原因文本。

    咽喉此前只挂在 ``download()`` 上，同文件 ``probe()`` 从未挂——同族两份语义、
    弱的那份有人用（``content_parser`` 把页面派生 URL 直送 ``probe()``）。
    现在 ``download()`` 与 ``probe()`` 共用本函数，两个入口不存在各自的校验分支。

    不新增异常类型、不回显 URL：拒绝原因（固定文案，不含地址）交调用方按
    既有形态消化——``download()`` 走 ``DownloadOutcome(error=...)``，
    ``probe()`` 走既有 ``RuntimeError`` 降级。签名 URL/cookie 一律不进消息与日志
    （同 ``_SafeMediaLogger`` 纪律）。
    """
    try:
        check_download_url(url)
    except RejectedUrlError as exc:
        logger.warning("media url rejected by SSRF guard: %s", exc)
        return str(exc)
    return None


# ---------------------------------------------------------------------------
# 解析钉定（连接层咽喉）：治 DNS rebinding 的「判后即弃」（缺口④）
#
# 形态＝http.client 留出的官方接缝：``HTTPConnection.__init__`` 里
# ``self._create_connection = socket.create_connection``（stdlib 注释明确写着
# 「stored as an instance variable to allow unit tests to replace it」）。
# 我们只在实例层把它换成「拿判定过的那册 IP 去连」（主钉 + 同一次解析的其余地址
# 可回退，多 A 记录兜底不丢），**不动** self.host：
# Host 头、TLS SNI（``server_hostname=self.host``）与证书主机名校验全部原样。
#
# 红线（台账 #71★）：代理在场时一律不钉。钉死目标 IP ＝绕过 Clash，
# 那是刚修好的通路；且代理在场时本机根本不解析目标域，判定的语义也不成立。
# 缺省 ``ProxyHandler``（读环境＝trust_env 回落，temporal 天气依赖它）同样
# 由 ``build_pinning_handlers`` 保持不动——本件只装连接类，不装代理件。
# 全树「哪些腿真的装了这套件」＝``build_pinning_handlers`` 的装配清单 +
# ``test_downloader_connect_pin.py`` 的在册比对锁（别按「本体存在」记账收口）。
# ---------------------------------------------------------------------------


def _pick_pinned_addresses(resolved: frozenset[str]) -> tuple[str, ...]:
    """把判定过的地址册排成「主钉 + 同一次解析的其余地址可回退」的连接序。

    为什么是**一册**而不是**一枚**（W4 收口，2026-10-01）：旧版只返回排序后的第一枚，
    等于把 ``socket.create_connection`` 自带的「多 A 记录轮询兜底」一并钉掉了——
    CDN 有一枚死 IP 时今日会换下一枚，只钉一枚就变成硬失败。现在主钉仍是第一位，
    同一次解析（同一册子，判定过的）其余地址按序可回退：rebinding 窗口照样归零
    （连接层一个域名字符都不看），CDN 自愈能力也不丢。
    排序与优先级：IPv4 先于 IPv6（双栈机器上「解析到 v6 但本机无 v6 路由」是常态
    故障源），组内按稳定字典序 ⇒ 同一册子每次排出同一序（可复现，不把下载/取图
    变成掷硬币）。
    """
    v4 = sorted(address for address in resolved if ":" not in address)
    v6 = sorted(address for address in resolved if ":" in address)
    return tuple(v4 + v6)


def _connect_target_is_proxied(req: Any) -> bool:
    """这次连接是不是「交给代理去建」（代理在场 ⇒ 不钉、不自己解析）。

    urllib 的 ``ProxyHandler`` 在 ``http_open`` 之前就把 ``req.host`` 换成了代理
    netloc（https over CONNECT 另记 ``req._tunnel_host``），而 ``req.full_url``
    始终是原始目标——两者主机名不等即是代理通路。判不清（空主机名等畸形形态）
    一律按「代理在场」处理：宁可不钉，交回 urllib 原路，行为与今天逐字节一致。
    """
    from urllib.parse import urlsplit

    connect_host = ""
    if getattr(req, "host", None):
        try:
            connect_host = (urlsplit(f"//{req.host}").hostname or "").lower()
        except ValueError:
            connect_host = ""
    try:
        origin_host = (urlsplit(req.full_url).hostname or "").lower()
    except ValueError:
        origin_host = ""
    if getattr(req, "_tunnel_host", None):
        return True
    if not connect_host or not origin_host:
        return True
    return connect_host != origin_host


def _pinned_connection_class(base: type, ips: tuple[str, ...]) -> Any:
    """造「只连判定过的那册 IP」的连接类（闭包捕获 IP，域名不再进 socket）。

    返回类型刻意是 ``Any`` 而不是 ``type``：这里造的是运行期动态子类，mypy 无从
    核对它是否满足 stdlib ``AbstractHTTPHandler.do_open`` 的 ``_HTTPConnectionProtocol``
    ——那把尺只约束「可调用形态」，声明成 ``type`` 会在两个 ``do_open`` 调用点
    报假红（typecheck 门由绿转红的正是这里）。动态件按定义是 Any，桩一次即可，
    **不用** ``# type: ignore``（ignore 会让这行以后彻底失能）。

    回退语义：按 ``ips`` 序逐个试，前一枚 ``OSError``（拒绝/超时/不可达）才换下一枚，
    全败则抛最后一次的异常——与 ``socket.create_connection`` 对多地址的做法同形。
    候选册来自**同一次**已判定的解析，回退不引入新的 DNS 查询、也就不开 rebinding 窗口。
    """
    import socket

    default_timeout = getattr(socket, "_GLOBAL_DEFAULT_TIMEOUT", None)

    def _create_pinned(address, timeout=default_timeout, source_address=None):
        port = address[1] if len(address) > 1 else 0
        last_error: OSError | None = None
        for ip in ips:
            try:
                return socket.create_connection(
                    (ip, port), timeout=timeout, source_address=source_address
                )
            except OSError as exc:  # 死 IP / 端口拒绝：换同一次解析的下一枚候选。
                last_error = exc
        # 全册皆败：抛最后一次的真实异常（超时/拒绝语义原样保留，不伪造原因）。
        # ``ips`` 永不为空（咽喉判定过才交回），``or`` 分支只让类型收敛、不吞信息。
        raise last_error or OSError("解析钉定无可用地址")

    class _PinnedConnection(base):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._pinned_ips = ips
            self._create_connection = _create_pinned

    return _PinnedConnection


def _pinned_connection_class_for(req: Any, base: type) -> Any | None:
    """连接时刻现判现钉：判定与连接共用这一次解析（rebinding 窗口归零）。

    返回 ``None`` ＝「本请求不钉」（代理在场 / 形态判不清），调用方交回
    urllib 原处理器，行为与今天一致。拒绝仍旧抛 ``RejectedUrlError``——
    与入口咽喉同一个异常族，消费方既有的 ``except`` 即降级通路。
    """
    if _connect_target_is_proxied(req):
        return None
    resolved = check_download_url_resolved(req.full_url)
    return _pinned_connection_class(base, _pick_pinned_addresses(resolved))


class _PinningHTTPHandler(urllib.request.HTTPHandler):
    """http 腿钉定件。"""

    def http_open(self, req: urllib.request.Request):  # type: ignore[override]
        import http.client

        connection_class = _pinned_connection_class_for(req, http.client.HTTPConnection)
        if connection_class is None:
            return super().http_open(req)
        return self.do_open(connection_class, req)


class _PinningHTTPSHandler(urllib.request.HTTPSHandler):
    """https 腿钉定件：ssl context 照旧透传（证书校验一点不松）。"""

    # 运行时真身：stdlib ``HTTPSHandler.__init__`` 里 ``self._context = context``
    # （context 缺省＝``ssl._create_default_https_context()``，verify_mode=CERT_REQUIRED
    # + check_hostname=True）。typeshed 不给私有成员立账 ⇒ 纯类型桩噪声，
    # 这里显式声明一次把属性登记进类型面，**不** 用 ``# type: ignore``。
    _context: Any

    def https_open(self, req: urllib.request.Request):  # type: ignore[override]
        import http.client

        connection_class = _pinned_connection_class_for(req, http.client.HTTPSConnection)
        if connection_class is None:
            return super().https_open(req)
        return self.do_open(connection_class, req, context=self._context)


def build_pinning_handlers() -> list[Any]:
    """连接层钉定 handler 对（http / https）。

    装配形态（唯一正确用法，护栏与钉定各管一件事、互不替代）::

        opener = urllib.request.build_opener(
            _GuardedShortLinkRedirectHandler(),  # 逐跳落点不许是内网
            *build_pinning_handlers(),           # 判定与连接共用同一次解析
        )

    ``build_opener`` 按 ``isinstance`` 去重，本对件会顶掉缺省 ``HTTPHandler`` /
    ``HTTPSHandler``（只此一条 http 链，不存在第二套通路）；缺省 ``ProxyHandler``
    不在此列——代理语义（含环境回落）一律不动。

    🔴 装配面现状（**缺口④只算「本体已修」，全树铺开未做**，W4 2026-10-01 现算）：
    本函数的调用点全树**只有一处**，装配清单以 ``tests/test_downloader_connect_pin.py
    ::test_pinning_assembly_roster_is_the_recorded_one`` 逐模块现算比对（清单漂了就红，
    防止台账把「本体存在」读成「缺口已收口」）：

    - **在装**：``domains/food/capabilities/eat.py`` 的 ``_guarded_image_opener``
      （菜品封面取图腿，缺口②）。
    - **未装（如实登记，勿宣称收口）**：
      ① ``link_parse/parsers/http_util._build_opener``——解析链全部出站咽喉。
        实测装上即撞 **3 枚跨席锁**（``test_auditfix_parsers
        ::test_resolve_short_link_via_local_redirect_server`` 与
        ``test_credential_health_probe_throat`` 两枚跨 host 剥凭证锁）：那三把尺拿
        ``127.0.0.1``/``localhost`` 真监听器当「两个 host」的替身，而钉定件在建连前
        就会把本机目标拒掉（判据正确、测试替身不兼容）。修法归属＝解析链席位，
        要连着改那三把尺的替身形（改端口打桩或显式豁免本机探测），不是本席能顺手
        合并进来的写面。
      ② ``media/ingest/vision_describe`` / ``media/capabilities/media_archive`` /
        ``meme/sources/meme_library_listener``（httpx 腿，形态另算）——W5 写面。
      ③ ``notes`` 图片腿、``render_backends._ORB_FETCH_OPENER``（渲染热路径的每图
        多解析取舍，见该件 docstring 自陈）、中央 ``download()``/``probe()``
        （yt-dlp 自带传输层，urllib 件挂不上去，要钉得走 yt-dlp 侧钩子）。
    - **装的时候两件易踩的坑**（给后续席）：
      a) 目标腿若自带 ``HTTPSHandler(context=...)``（如 ``http_util`` 的
         ``verify_ssl=False`` 支），**先加的赢**（``OpenerDirector`` 按
         ``handler_order``/装配序取第一个 ``https_open``）——钉定件必须
         ``_PinningHTTPSHandler(context=同一个 ctx)`` 形态顶上去，否则要么丢钉、
         要么悄悄把「不校验证书」改回「校验」＝行为漂移。
      b) 生产进程若在 Clash 档（``getproxies()`` 有值），``_connect_target_is_proxied``
         一律判「代理在场」⇒ 钉定**静默不生效**（红线，故意如此）。所以「装了」≠
         「在钉」，验收要按当轮代理态现算，别拿一次通过当永久。
    """
    import http.client

    handlers: list[Any] = [_PinningHTTPHandler()]
    if hasattr(http.client, "HTTPSConnection"):
        handlers.append(_PinningHTTPSHandler())
    return handlers


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
        concurrency: int = 8,
        aria2_enabled: bool = True,
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
        # 下载并发（用户实测单连接串行太慢）：分片流（HLS）用 yt-dlp 原生
        # concurrent_fragment_downloads；单文件大流（B站 DASH m4s）用
        # http_chunk_size Range 分块并行。装了 aria2c 时整体委托 aria2
        # 多连接（-x16），--file-allocation=none 免预分配、内存占用极小。
        self.concurrency = max(1, int(concurrency))
        self.aria2_path = ""
        if aria2_enabled:
            import shutil

            self.aria2_path = shutil.which("aria2c") or ""
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
        if not skip_download:
            # 多连接提速（300Mbps 带宽实测单连接吃不满）：
            # - 分片流（HLS/DASH 清单）并发 N 片；
            # - 单文件流按 16MB 一块 Range 并行拉取（aria2 未装时也生效）；
            # - 装有 aria2c 时 http(s) 整体委托 aria2（16 连接，免预分配，
            #   内存占用≈连接数×块缓存，远低于 yt-dlp 常驻缓冲）。
            opts["concurrent_fragment_downloads"] = self.concurrency
            opts["http_chunk_size"] = 16 * 1024 * 1024
            if self.aria2_path:
                opts["external_downloader"] = {"default": "aria2c"}
                opts["external_downloader_args"] = {
                    "aria2c": [
                        f"-x{min(16, self.concurrency * 2)}",
                        f"-s{min(16, self.concurrency * 2)}",
                        "-k1M",
                        "-j1",
                        "--file-allocation=none",
                        "--console-log-level=warn",
                        "--summary-interval=0",
                    ]
                }
        return opts

    def probe(self, url: str) -> MediaAnalysis:
        if not self.available():
            raise RuntimeError("yt-dlp 未安装，无法做媒体分析")
        # SSRF 咽喉（审计 D1-F1）：probe 与 download 同源校验。probe 的 URL 并非
        # 只有用户贴入的 candidate——content_parser 送的是页面派生地址
        # （audio_url/canonical_url，源头是第三方响应体），同样必须过闸门。
        reason = _url_rejection_reason(url)
        if reason is not None:
            raise RuntimeError(f"媒体分析被拒绝：{reason}")
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
        # CC 字幕随片抓取（用户裁定 2026-09-12：只要有字幕必须保存）——
        # 手动 CC 优先、自动字幕兜底；追问链路直接用文本，比语音转文字
        # 便宜且零幻听。压制进视频不做：重编码数分钟 CPU+损画质，
        # 且 QQ 播放器不渲染软字幕轨，收益为零。
        subs_opts = {
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["zh-Hans", "zh-CN", "zh", "zh-TW", "en", "-live_chat"],
            "subtitlesformat": "srt/vtt/best",
        }
        opts.update(
            {
                "outtmpl": str(self.download_dir / "%(id)s.%(ext)s"),
                "format": fmt,
                "max_filesize": self.max_bytes,
                **subs_opts,
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
            subtitle_path = self._locate_subtitle_file(info, prepared or path)
            return DownloadOutcome(
                path=path, analysis=analysis, subtitle_path=subtitle_path
            )

    def _locate_subtitle_file(self, info: dict, media_path: str) -> str:
        """下载后定位落盘的 CC 字幕（zh 优先）；无字幕返回空串。

        yt-dlp 落盘名 = 媒体主名 + 语言码 + .srt/.vtt；优先级 zh-Hans >
        zh-CN > zh > zh-TW > en，同级 srt 优于 vtt（追问链路更好解析）。
        """
        try:
            stem = Path(media_path or "").stem or str(info.get("id") or "")
            if not stem:
                return ""
            candidates = sorted(self.download_dir.glob(f"{stem}*"))
            best = ""
            best_rank = (-1, -1)
            lang_rank = {"zh-Hans": 5, "zh-CN": 4, "zh": 3, "zh-TW": 2, "en": 1}
            for candidate in candidates:
                if candidate.suffix.lower() not in {".srt", ".vtt"}:
                    continue
                name = candidate.name.lower()
                rank = 0
                for lang, value in lang_rank.items():
                    if lang.lower() in name:
                        rank = max(rank, value)
                if rank == 0:
                    continue
                ext_rank = 1 if candidate.suffix.lower() == ".srt" else 0
                score = (rank, ext_rank)
                if score > best_rank:
                    best_rank = score
                    best = str(candidate)
            return best
        except Exception:  # noqa: BLE001 - 字幕定位失败不影响下载结果。
            return ""

    def download(self, url: str) -> DownloadOutcome:
        if not self.available():
            return DownloadOutcome(error="yt-dlp 未安装，无法下载")
        # SSRF 固定闸门（评审 H6）：/bot download 对普通用户开放，下载前先拒掉
        # 非 http(s) 协议与内网/保留地址。咽喉调用点收敛在 _url_rejection_reason，
        # 与 probe() 同源（不再一处有一处无）。
        reason = _url_rejection_reason(url)
        if reason is not None:
            return DownloadOutcome(error=f"下载被拒绝：{reason}")
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
                            from plugins.bot_unified_runtime.domains.chat_reply.runtime.cache_policy import (
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
