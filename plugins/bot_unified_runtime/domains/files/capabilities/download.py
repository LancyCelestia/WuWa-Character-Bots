"""视频下载能力（bot.download）：`/bot download <链接>`。

- 用 yt-dlp 下载到 data/downloads/（git 忽略），并做媒体分析。
- 结果：文字摘要（标题/大小/分辨率/时长/画面与音频品质标注）+ 视频文件段。
- 下载失败优雅降级为文字（原因只说类型，不泄露堆栈与 cookie）。
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
from plugins.bot_unified_runtime.output.plain_text import redact_local_secrets
from plugins.bot_unified_runtime.sources.parsers import extract_http_urls

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
        subtitle_text = _subtitle_plain_text(outcome.subtitle_path)
        lines = ["下载完成 ✓"]
        if analysis:
            lines.append(f"标题：{analysis.title[:120]}")
            lines.extend(analysis.summary_lines())
            if analysis.hdr:
                lines.append(f"画面：{analysis.hdr}")
        lines.append(f"文件：{outcome.path}")
        if outcome.subtitle_path:
            lines.append(f"字幕已保存：{outcome.subtitle_path}")
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.download",
            kind="mixed",
            title=analysis.title if analysis else "下载完成",
            body="\n".join(lines),
            video=[
                {
                    "file": outcome.path,
                    # meta 随视频段透传到发送点：发送成功后据此登记 bot_sent 媒体档案。
                    # subtitle_text=CC 字幕纯文本：追问链路直接引用（用户裁定有字幕必存）。
                    "meta": {
                        "platform": "",
                        "canonical_url": url,
                        "title": (analysis.title if analysis else "")[:200],
                        "subtitle_text": subtitle_text,
                        "subtitle_file": outcome.subtitle_path,
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
