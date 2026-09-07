"""解析结果视频直发（交接 §2.9 item 1）：直链 → 下载 → 视频段随卡发送。"""

from __future__ import annotations

from types import SimpleNamespace

from plugins.bot_unified_runtime.capabilities.content_parser import (
    build_content_capability,
)
from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.contracts.media import ParserRule, build_parsed_content
from plugins.bot_unified_runtime.sources.downloader import (
    DownloadOutcome,
    MediaAnalysis,
)
from plugins.bot_unified_runtime.sources.registry import ParserRegistry


def _message(text: str) -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id="private:u1",
        session_type=SessionType.PRIVATE,
        sender_id="u1",
        plain_text=text,
    )


def _registry(parse_fn) -> dict:
    registry = ParserRegistry()
    registry.register(
        ParserRule(
            parser_id="xiaohongshu",
            source_id="小红书",
            url_patterns=[r"xiaohongshu\.com"],
            priority=1,
        )
    )
    return {"registry": registry, "parsers": {"xiaohongshu": parse_fn}}


def _video_item(*, direct_url: str = "https://sns-video/v.mp4") -> object:
    return build_parsed_content(
        platform="xiaohongshu",
        item_id="note1",
        item_kind="video",
        title="视频笔记",
        canonical_url="https://www.xiaohongshu.com/explore/note1",
        detail={
            "images": ["https://xhs/p1.jpg"],
            "video": {"url": direct_url, "width": 1280, "height": 720},
        },
    )


class _FakeDownloader:
    def __init__(
        self,
        outcome: DownloadOutcome,
        *,
        available: bool = True,
    ) -> None:
        self._outcome = outcome
        self._available = available
        self.downloaded_urls: list[str] = []

    def available(self) -> bool:
        return self._available

    def download(self, url: str) -> DownloadOutcome:
        self.downloaded_urls.append(url)
        return self._outcome

    def probe(self, url: str) -> MediaAnalysis:
        return MediaAnalysis()


def _config(*, auto_send: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        bot_media_analyze_enabled=True,
        bot_content_video_auto_send=auto_send,
    )


def _run(
    item: object,
    *,
    auto_send: bool = True,
    outcome: DownloadOutcome | None = None,
    available: bool = True,
) -> tuple[object, _FakeDownloader]:
    downloader = _FakeDownloader(
        outcome
        or DownloadOutcome(
            path=r"C:\tmp\video.mp4",
            analysis=MediaAnalysis(filesize_bytes=1048576),
        ),
        available=available,
    )
    capability = build_content_capability(
        _config(auto_send=auto_send),
        registry=_registry(lambda url: item),
        downloader=downloader,
    )
    result = capability(
        _message("https://www.xiaohongshu.com/explore/note1"),
        None,
    )
    return result, downloader


def test_direct_video_auto_send_attaches_video_segment() -> None:
    result, downloader = _run(_video_item())
    assert result.video == [{"file": r"C:\tmp\video.mp4"}]
    assert downloader.downloaded_urls == ["https://sns-video/v.mp4"]
    assert "视频已发送 ✓（1.0MB）" in result.body
    assert "video_auto_sent" in result.audit_tags


def test_auto_send_disabled_keeps_download_hint() -> None:
    result, downloader = _run(_video_item(), auto_send=False)
    assert result.video == []
    assert downloader.downloaded_urls == []
    assert "下载：" in result.body


def test_download_failure_falls_back_to_hint() -> None:
    failed = DownloadOutcome(path="", analysis=None, error="视频过大（超过 1GB 上限）")
    result, downloader = _run(_video_item(), outcome=failed)
    assert result.video == []
    assert downloader.downloaded_urls == ["https://sns-video/v.mp4"]
    assert "下载：/bot download https://sns-video/v.mp4" in result.body


def test_no_direct_url_does_not_trigger_download() -> None:
    result, downloader = _run(_video_item(direct_url=""))
    assert result.video == []
    assert downloader.downloaded_urls == []


def test_ytdlp_unavailable_does_not_trigger_download() -> None:
    result, downloader = _run(_video_item(), available=False)
    assert result.video == []
    assert downloader.downloaded_urls == []


def test_non_video_item_does_not_trigger_download() -> None:
    note = build_parsed_content(
        platform="xiaohongshu",
        item_id="note2",
        item_kind="note",
        title="图文笔记",
        canonical_url="https://www.xiaohongshu.com/explore/note2",
        detail={"images": ["https://xhs/p1.jpg", "https://xhs/p2.jpg"]},
    )
    result, downloader = _run(note)
    assert result.video == []
    assert downloader.downloaded_urls == []
