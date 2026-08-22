"""视频下载能力（bot.download）：`/bot download <链接>`。

- 用 yt-dlp 下载到 data/downloads/（git 忽略），并做媒体分析。
- 结果：文字摘要（标题/大小/分辨率/时长/画面与音频品质标注）+ 视频文件段。
- 下载失败优雅降级为文字（原因只说类型，不泄露堆栈与 cookie）。
"""

from __future__ import annotations

import re
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
)
from plugins.bot_unified_runtime.sources.downloader import MediaDownloader
from plugins.bot_unified_runtime.sources.parsers import extract_http_urls

_COMMAND_RE = re.compile(
    r"^(?:/bot\s+)?(?:下载|download)\s+(?P<url>https?://\S+)$",
    re.IGNORECASE,
)


def is_download_command(text: str) -> bool:
    return _COMMAND_RE.match(text.strip()) is not None


def extract_download_url(text: str) -> str | None:
    match = _COMMAND_RE.match(text.strip())
    if match:
        return match.group("url")
    urls = extract_http_urls(text)
    return urls[0] if urls else None


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
            max_bytes=int(getattr(config, "bot_download_max_bytes", 200 * 1048576)),
            max_height=int(getattr(config, "bot_download_max_height", 1080)),
            timeout_seconds=int(getattr(config, "bot_download_timeout_seconds", 120)),
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
                body="yt-dlp 未安装，无法下载。请先安装依赖。",
                audit_tags=["download", "ytdlp_missing"],
            )
        outcome = downloader.download(url)
        if outcome.error:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.download",
                kind="text",
                body=f"下载失败：{outcome.error}\n原链接：{url}",
                audit_tags=["download", "download_failed"],
            )
        analysis = outcome.analysis
        lines = ["下载完成 ✓"]
        if analysis:
            lines.append(f"标题：{analysis.title[:120]}")
            lines.extend(analysis.summary_lines())
            if analysis.hdr:
                lines.append(f"画面：{analysis.hdr}")
        lines.append(f"文件：{outcome.path}")
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.download",
            kind="mixed",
            title=analysis.title if analysis else "下载完成",
            body="\n".join(lines),
            video=[{"file": outcome.path}],
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=[
                "download",
                f"download_size:{analysis.filesize_bytes if analysis else 0}",
            ],
        )

    return capability
