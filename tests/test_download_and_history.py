from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    ReviewResult,
    ReviewAction,
    RiskLevel,
    RenderedOutput,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.capabilities.download import (
    build_download_capability,
    extract_download_url,
    is_download_command,
)
from plugins.bot_unified_runtime.output.renderer import render_reviewed_output
from plugins.bot_unified_runtime.sender.onebot import (
    _segment_from_mixed_part,
    build_onebot_message_segments,
)
from plugins.bot_unified_runtime.sources.downloader import (
    DownloadOutcome,
    MediaAnalysis,
    MediaDownloader,
    _analysis_from_info,
)
from plugins.bot_unified_runtime.sources.parse_history import (
    SQLiteParseHistoryStore,
    build_parse_history_result,
    build_parse_history_store,
)


def _message(text: str) -> IncomingMessage:
    return IncomingMessage(
        platform="test",
        adapter="test",
        bot_id="bot",
        session_id="s1",
        session_type=SessionType.PRIVATE,
        sender_id="u1",
        plain_text=text,
        raw_segments=[{"type": "text", "data": {"text": text}}],
        mentions_bot=True,
    )


def test_download_command_parsing():
    assert is_download_command("/bot download https://x.com/a")
    assert not is_download_command("https://x.com/a")
    assert extract_download_url("下载 https://x.com/a") == "https://x.com/a"


class FakeDownloader:
    def __init__(self, outcome: DownloadOutcome | None = None, available: bool = True):
        self.outcome = outcome
        self._available = available
        self.calls = 0

    def available(self) -> bool:
        return self._available

    def download(self, url: str) -> DownloadOutcome:
        self.calls += 1
        return self.outcome or DownloadOutcome(
            path="data/downloads/test.mp4",
            analysis=MediaAnalysis(title="测试视频", width=1920, height=1080, duration_seconds=90),
        )


def test_download_capability_success():
    downloader = FakeDownloader()
    capability = build_download_capability(downloader=downloader)

    result = capability(_message("/bot download https://x.com/a"), None)

    assert result.capability_id == "bot.download"
    assert result.video == [{"file": "data/downloads/test.mp4"}]
    assert "下载完成" in result.body
    assert "1920×1080" in result.body
    assert downloader.calls == 1


def test_download_capability_failure_is_text():
    downloader = FakeDownloader(outcome=DownloadOutcome(error="DownloadError: boom"))
    capability = build_download_capability(downloader=downloader)

    result = capability(_message("/bot download https://x.com/a"), None)

    assert result.video == []
    assert "下载失败" in result.body


def test_analysis_from_info_detects_hdr_and_hires():
    analysis = _analysis_from_info(
        {
            "title": "t",
            "duration": 60,
            "width": 3840,
            "height": 2160,
            "fps": 60,
            "vcodec": "av01",
            "acodec": "flac",
            "asr": 96000,
            "audio_channels": 2,
            "formats": [
                {"vcodec": "av01", "acodec": "none", "format_note": "2160p HDR"},
                {"vcodec": "none", "acodec": "flac", "asr": 96000},
            ],
        }
    )

    assert analysis.hdr == "HDR"
    assert analysis.audio_quality == "Hi-Res（无损）"
    assert analysis.resolution() == "3840×2160"


def test_analysis_from_info_detects_dolby():
    analysis = _analysis_from_info(
        {
            "title": "t",
            "vcodec": "dvhe.05",
            "acodec": "ec-3",
            "formats": [
                {"vcodec": "dvhe", "acodec": "none", "format_note": "Dolby Vision"},
                {"vcodec": "none", "acodec": "ec-3", "format_note": "Dolby Atmos"},
            ],
        }
    )

    assert analysis.hdr == "杜比视界"
    assert analysis.audio_quality == "疑似杜比全景声"


def test_parse_history_store_roundtrip(tmp_path):
    store = SQLiteParseHistoryStore(tmp_path / "parse.sqlite3", max_items=100)
    store.record(
        request_id="r1",
        platform="bilibili",
        item_kind="video",
        title="测试视频",
        url="https://www.bilibili.com/video/BV1",
        parse_depth="deep",
        body_preview="卡片正文",
    )

    entries = store.list_recent(limit=10)

    assert len(entries) == 1
    assert entries[0].title == "测试视频"
    assert entries[0].url.endswith("BV1")


def test_parse_history_query_result():
    from plugins.bot_unified_runtime.sources.parse_history import (
        InMemoryParseHistoryStore,
    )

    store = InMemoryParseHistoryStore()
    result = build_parse_history_result(store, request_id="r1", query="")
    assert "还没有解析记录" in result.body

    store.record(request_id="r2", platform="pixiv", title="画", url="https://pixiv/a")
    result = build_parse_history_result(store, request_id="r1", query="")
    assert "[pixiv] 画" in result.body


def test_renderer_passes_video_part():
    result = CapabilityResult(
        request_id="r1",
        capability_id="bot.download",
        kind="mixed",
        body="下载完成",
        video=[{"file": "C:/data/video.mp4"}],
    )
    review = ReviewResult(
        request_id="r1",
        approved=True,
        action=ReviewAction.ALLOW,
        risk_level=RiskLevel.LOW,
        privacy_level=PrivacyLevel.PUBLIC,
        reasons=[],
        safe_text="下载完成",
    )

    rendered = render_reviewed_output(result, review)

    assert rendered.content_type == "mixed"
    assert {"type": "video", "file": "C:/data/video.mp4"} in rendered.content_ref["parts"]


def test_onebot_video_segment():
    segment = _segment_from_mixed_part({"type": "video", "file": "C:/v.mp4"})
    assert segment == {"type": "video", "data": {"file": "C:/v.mp4"}}


def test_onebot_send_request_with_video():
    request = SendRequest(
        request_id="r1",
        session_id="s1",
        target_scope=SessionType.PRIVATE,
        target_id="u1",
        capability_id="bot.download",
        content=RenderedOutput(
            request_id="r1",
            content_type="mixed",
            content_ref={
                "parts": [
                    {"type": "video", "file": "C:/v.mp4"},
                    {"type": "text", "text": "下载完成"},
                ]
            },
            text_fallback="下载完成",
            size_estimate=8,
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
        ),
        send_policy="immediate",
        priority="normal",
        max_messages=1,
        dedupe_key="k",
        cooldown_key="k",
        privacy_level=PrivacyLevel.PUBLIC,
        persona_profile_id="shorekeeper",
    )
    segments = build_onebot_message_segments(request)
    assert segments[0]["type"] == "video"
    assert segments[1]["type"] == "text"


def test_parse_history_store_from_config(tmp_path):
    config = Config(
        bot_parse_history_enabled=True,
        bot_parse_history_db_path=str(tmp_path / "h.sqlite3"),
    )
    store = build_parse_history_store(config)
    store.record(request_id="r", platform="bilibili", title="t")
    assert len(store.list_recent(limit=5)) == 1

    offline = build_parse_history_store(
        Config(bot_parse_history_enabled=False)
    )
    offline.record(request_id="r2", platform="x", title="y")
    assert len(offline.list_recent(limit=5)) == 1  # 内存版仍可用，但不落盘
