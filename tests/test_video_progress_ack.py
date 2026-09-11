"""视频分析进度提示（ack）的三重把关回归。

锁定行为（防"应了却不答"）：
- 确认要现场分析（自带视频/反查到文件/有档案待分析）才发 ack；
- 没有任何信号来源（vision/ASR provider 都没配且无既有档案）时不发 ack；
- 本轮不会回复（mentions_bot=False，如 white2 无点名的视频消息）时不发 ack；
- 档案缓存命中（有简报）时不发 ack、不反查；
- 同会话冷却窗口内不发第二条 ack；
- 档案带标题时 ack 点出标题（"我看看《标题》，稍等…"）。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import plugins.bot_unified_runtime as runtime
from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.runtime import video_pipeline


class _Bot:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def call_api(self, action: str, **params: object):
        self.calls.append((action, params))
        return {"message": []}


class _FakeRegistry:
    def __init__(self, asset: SimpleNamespace | None = None) -> None:
        self._asset = asset

    def lookup_by_message_id(self, message_id: str) -> SimpleNamespace | None:
        return self._asset


def _message(**overrides: object) -> IncomingMessage:
    values: dict[str, object] = {
        "platform": "qq",
        "adapter": "nonebot",
        "bot_id": "bot",
        "session_id": "g1",
        "session_type": SessionType.GROUP,
        "sender_id": "u1",
        "plain_text": "（用户发送了图片/表情包/视频，未附文字。）",
        "raw_segments": [{"type": "video", "data": {"file": "clip.mp4"}}],
        "message_id": "M-in",
        "mentions_bot": True,
    }
    values.update(overrides)
    return IncomingMessage(**values)  # type: ignore[arg-type]


def _config(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "bot_video_understanding_enabled": True,
        "bot_video_progress_ack_enabled": True,
        "bot_video_progress_ack_cooldown_seconds": 60,
        "bot_download_dir": "data/downloads",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _asset(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "media_id": "media-1",
        "chat_message_id": "M-bot",
        "session_id": "g1",
        "source_kind": "bot_sent",
        "platform": "bilibili",
        "item_id": "BV1",
        "canonical_url": "https://b23.tv/BV1",
        "title": "测试视频",
        "creator_name": "UP主",
        "duration_ms": 12_000,
        "local_path": "",
        "subtitle_text": "大家好",
        "brief_text": "",
        "brief_signals": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture(autouse=True)
def _fresh_throttle(monkeypatch: pytest.MonkeyPatch) -> None:
    # 节流表是模块级状态：每个测试换成空表，互不残留。
    # patch 目标必须是定义处（video_pipeline）：函数读的是自己模块的全局。
    monkeypatch.setattr(video_pipeline, "_VIDEO_ACK_THROTTLE", {})


def _run(
    message: IncomingMessage,
    monkeypatch: pytest.MonkeyPatch,
    *,
    registry: _FakeRegistry | None = None,
    providers_ready: bool = True,
    config: SimpleNamespace | None = None,
    fetch_result: str = "",
) -> list[str]:
    sent: list[str] = []

    async def send(text: str) -> None:
        sent.append(text)

    async def fake_fetch(bot: object, message_id: str, cfg: object) -> str:
        return fetch_result

    monkeypatch.setattr(video_pipeline, "_fetch_reply_video_file", fake_fetch)
    asyncio.run(
        runtime._prepare_video_understanding_message(
            _Bot(),
            message,
            send,
            config=config or _config(),
            runtime_settings=None,
            media_registry=registry,
            media_providers_ready=providers_ready,
        )
    )
    return sent


def test_ack_sent_for_video_with_mention_and_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = _run(_message(), monkeypatch)
    assert sent == [runtime._VIDEO_ACK_TEXT]


def test_no_ack_without_mention(monkeypatch: pytest.MonkeyPatch) -> None:
    # white2 类场景：视频消息但未点名 → 本轮不会回复，不许先应答。
    sent = _run(_message(mentions_bot=False), monkeypatch)
    assert sent == []


def test_no_ack_without_providers_and_without_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # vision/ASR 都没配置且无既有档案：分析了也出不来任何材料，不许空应答。
    sent = _run(_message(), monkeypatch, providers_ready=False)
    assert sent == []


def test_ack_sent_for_bot_sent_reply_with_file_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset = _asset(brief_text="")
    sent = _run(
        _message(
            raw_segments=[],
            plain_text="这视频里是什么",
            reply_to_message_id="M-bot",
        ),
        monkeypatch,
        registry=_FakeRegistry(asset),
        providers_ready=False,  # 档案里有字幕/元数据，无 provider 也能出文本简报
    )
    # 档案带标题：ack 点出标题而不是通用文案。
    assert sent == ["我看看《测试视频》，稍等…"]
    assert runtime._VIDEO_ACK_TEXT not in sent


def test_no_ack_on_cached_brief_hit_and_no_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset = _asset(brief_text="画面：猫。")
    registry = _FakeRegistry(asset)

    async def forbidden_fetch(bot: object, message_id: str, cfg: object) -> str:
        raise AssertionError("缓存命中时不得反查适配器")

    monkeypatch.setattr(video_pipeline, "_fetch_reply_video_file", forbidden_fetch)

    sent: list[str] = []

    async def send(text: str) -> None:
        sent.append(text)

    asyncio.run(
        runtime._prepare_video_understanding_message(
            _Bot(),
            _message(
                raw_segments=[],
                plain_text="这视频里是什么",
                reply_to_message_id="M-bot",
            ),
            send,
            config=_config(),
            runtime_settings=None,
            media_registry=registry,
            media_providers_ready=True,
        )
    )
    assert sent == []


def test_ack_cooldown_suppresses_second_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _run(_message(), monkeypatch)
    second = _run(_message(), monkeypatch)
    assert first == [runtime._VIDEO_ACK_TEXT]
    assert second == []


def test_no_ack_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _run(
        _message(),
        monkeypatch,
        config=_config(bot_video_progress_ack_enabled=False),
    )
    assert sent == []
