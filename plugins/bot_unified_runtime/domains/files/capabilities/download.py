"""视频下载能力（bot.download）：`/bot download <链接>`。

- 用 yt-dlp 下载到 data/downloads/（git 忽略），并做媒体分析。
- 结果：文字摘要（标题/大小/分辨率/时长/画面与音频品质标注）+ 视频文件段。
- 下载失败优雅降级为文字（原因只说类型，不泄露堆栈与 cookie）。

落点门（席 B1，2026-10-02，P3.9 的一半）：本能力拿到的 ``outcome.path`` /
``outcome.subtitle_path`` 是**远端元数据拼出来的名字**（``%(id)s.%(ext)s``，装配点
``domains/files/sources/downloader.py:944`` 与就地拼名那腿 :958-961 都没消毒），
而这两个串随后既进正文回显、又进 ``video.file`` 交协议端**读字节**——一把没消毒的
落点名就是一枚「任意文件读 + 外发」原语（同族事故账＝E02 席的本地路径域门）。
判据**不在此新建**：折算与包含判定整柄转调 ``domains/media/path_gate``（容器门唯一
真身），过门后只用**折算后的路径**去做 IO 与回显（判定与执行不许两说），拒门只点名
原因代号、绝不回显路径原文。另一半（装配点消毒）的施工图在
``patches/B1-TTS-CACHE-OUTTMPL-20261002.md``——那两枚文件属别席，本席只出提案。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
)
from plugins.bot_unified_runtime.domains.files.sources.downloader import MediaDownloader
from plugins.bot_unified_runtime.domains.link_parse.parsers import extract_http_urls
from plugins.bot_unified_runtime.domains.media import path_gate
from plugins.bot_unified_runtime.domains.render.plain_text import redact_local_secrets

_COMMAND_RE = re.compile(
    r"^(?:/bot\s+)?(?:下载|download)\s+(?P<url>https?://\S+)$",
    re.IGNORECASE,
)

logger = logging.getLogger(__name__)


def extract_download_url(text: str) -> str | None:
    match = _COMMAND_RE.match(text.strip())
    if match:
        return match.group("url")
    urls = extract_http_urls(text)
    return urls[0] if urls else None


def _download_failure_reason(error: str) -> str:
    """把下载器的原始错误串归为一句用户能懂的中文原因（细节只进日志）。"""
    text = str(error or "")
    if any(key in text for key in ("超时", "网络", "连接", "登录态")):
        return "网络或链接访问不稳定"
    if any(key in text for key in ("拒绝", "权限", "403", "401", "forbidden")):
        return "对方站点拒绝了这次请求"
    if any(key in text for key in ("不支持", "unsupported", "无法提取", "返回空结果")):
        return "这个链接暂时不支持下载"
    return "下载过程中出了点问题"


def _download_container_root(downloader: Any | None) -> Path | None:
    """下载容器根＝**下载器自己那枚** ``download_dir``（本处不重算落点）。

    装配点 ``__init__.py`` 已按 ``config.bot_download_dir`` 构造它，而该键住在
    ``PATH_SCALAR_REMAPPED_FIELDS`` 名册里 ⇒ 拿到的是折进 Runtime 的绝对路径。
    能力层再算一遍＝第二个真值来源（换根时两说）。读不出＝``None``，
    由容器门的「零登记根即拒」那一腿兜成 fail-closed，不在这里猜目录。
    """
    text = str(getattr(downloader, "download_dir", "") or "").strip()
    return Path(text) if text else None


def _gate_artifact(ref: str, root: Path | None) -> str:
    """回传/读字节**之前**过一遍容器门真身；返回折算后的路径，拒门即抛。

    转调而非抄判据（``path_gate.contain_within`` 是「折算后还在登记根内」的唯一
    判据，含 NUL/设备前缀/编码穿越/ADS/保留名那几格形态检查）。空串原样返回空串：
    「没有这个部件」与「这个部件想去外面」是两件事，必须分开记账。
    """
    if not str(ref or "").strip():
        return ""
    resolved = path_gate.contain_within(str(ref), [root] if root is not None else [])
    return str(resolved)


def _artifact_refused_result(message: IncomingMessage, code: str) -> CapabilityResult:
    """落点被容器门拒掉时的降级文本（只给代号，绝不回显路径原文）。"""
    return CapabilityResult(
        request_id=message.request_id,
        capability_id="bot.download",
        kind="text",
        body=(
            "这次没下载成功：下载件的落点对不上，就先不把文件发出来了。"
            "可以稍后重发，或换个链接。"
        ),
        audit_tags=["download", "artifact_refused_by_container_gate", f"gate_code={code}"],
        risk_level=RiskLevel.LOW,
        privacy_level=PrivacyLevel.PUBLIC,
    )


def _subtitle_plain_text(path: str, *, max_chars: int = 4000) -> str:
    """srt/vtt → 纯文本（剥 WEBVTT 头/序号/时间轴行），供视频追问直接引用。

    用户裁定 2026-09-12：有字幕必存；文本直接进 meta 比"抽帧+识图+语音
    转文字"便宜两个数量级且零幻听。解析失败返回空串，绝不抛。
    """
    if not path:
        return ""
    try:
        raw = Path(path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    lines: list[str] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        text = line.strip()
        if (
            not text
            or text == "WEBVTT"
            or text.isdigit()  # srt 序号
            or "-->" in text  # 时间轴
            or text.startswith(("NOTE", "STYLE", "Kind:", "Language:"))
        ):
            continue
        if text in seen:
            continue  # 滚动字幕里整行重复的极常见
        seen.add(text)
        lines.append(text)
        if sum(len(item) for item in lines) >= max_chars:
            break
    return "\n".join(lines)[: max_chars + 200]


def build_download_capability(
    config: Any | None = None,
    *,
    downloader: MediaDownloader | None = None,
) -> Any:
    if downloader is None and config is not None:
        downloader = MediaDownloader(
            cookies_file=str(getattr(config, "bot_cookies_file", "") or ""),
            proxy=str(getattr(config, "bot_download_proxy", "") or ""),
            download_dir=str(
                getattr(config, "bot_download_dir", "data/downloads") or "data/downloads"
            ),
            max_bytes=int(getattr(config, "bot_download_max_bytes", 1073741824)),
            max_height=int(getattr(config, "bot_download_max_height", 0)),
            timeout_seconds=int(getattr(config, "bot_download_timeout_seconds", 120)),
            concurrency=int(getattr(config, "bot_download_concurrency", 8) or 8),
            aria2_enabled=bool(getattr(config, "bot_download_aria2_enabled", True)),
        )
    if downloader is None:
        downloader = MediaDownloader()

    def capability(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        url = extract_download_url(message.plain_text)
        if not url:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.download",
                kind="text",
                body="用法：/bot download <视频链接>（B站/油管/推特/小红书/抖音投稿视频）",
                audit_tags=["download", "missing_url"],
            )
        if not downloader.available():
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.download",
                kind="text",
                body="下载器组件（yt-dlp）还没装好，这次下不了。让管理员在 Runtime venv 里补装后重发链接。",
                audit_tags=["download", "ytdlp_missing"],
            )
        outcome = downloader.download(url)
        if outcome.error:
            # 原始错误串（常为英文/内部细节）只进日志；用户侧只给分类后的中文原因。
            logger.warning("download failed: %s (url=%s)", outcome.error, url)
            # 审查 F-03（收窄口径）：失败文案回显「原链接」，可能带 URL userinfo
            # 凭据形态，出站前统一打码；此处是系统生成的失败通知文本，聊天回复
            # 链不经此处，零改动。
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.download",
                kind="text",
                body=redact_local_secrets(
                    f"这次没下载成功：{_download_failure_reason(outcome.error)}。"
                    "可以稍后重发，或换个链接。\n"
                    f"原链接：{url}"
                ),
                audit_tags=["download", "download_failed"],
            )
        analysis = outcome.analysis
        # 落点门（文件头记账）：正文回显与 video.file 都只准用**过门后**的形态，
        # 字幕文本也在过门之后才读——否则「把容器外一枚真名的字节念进群里」这条路
        # 一个字符都不用改就还在。门只转调真身，判据零副本。
        container = _download_container_root(downloader)
        try:
            media_file = _gate_artifact(outcome.path, container)
            subtitle_file = _gate_artifact(outcome.subtitle_path, container)
        except path_gate.PathEscapeError as exc:
            logger.warning(
                "download artifact refused by container gate request_id=%s code=%s",
                message.request_id,
                exc.code,
            )
            return _artifact_refused_result(message, exc.code)
        subtitle_text = _subtitle_plain_text(subtitle_file)
        lines = ["下载完成 ✓"]
        if analysis:
            lines.append(f"标题：{analysis.title[:120]}")
            lines.extend(analysis.summary_lines())
            if analysis.hdr:
                lines.append(f"画面：{analysis.hdr}")
        lines.append(f"文件：{media_file}")
        if subtitle_file:
            lines.append(f"字幕已保存：{subtitle_file}")
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.download",
            kind="mixed",
            title=analysis.title if analysis else "下载完成",
            body="\n".join(lines),
            video=[
                {
                    "file": media_file,
                    # meta 随视频段透传到发送点：发送成功后据此登记 bot_sent 媒体档案。
                    # subtitle_text=CC 字幕纯文本：追问链路直接引用（用户裁定有字幕必存）。
                    "meta": {
                        "platform": "",
                        "canonical_url": url,
                        "title": (analysis.title if analysis else "")[:200],
                        "subtitle_text": subtitle_text,
                        "subtitle_file": subtitle_file,
                    },
                }
            ],
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=[
                "download",
                f"download_size:{analysis.filesize_bytes if analysis else 0}",
            ],
        )

    return capability
