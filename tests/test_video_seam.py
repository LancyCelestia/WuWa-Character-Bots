"""视频接缝组合测试：handler 预处理（video_pipeline）× 能力层（chat）。

此前 P1-1 类洞在两套单测里各自绿灯：handler 单测只测反查+ack，能力层单测
只测消费 reply_video_path——没人验证"handler 塞进的文件真的被能力层吃掉"。
这里用 asyncio.run 把两段真实代码串起来锁死接缝：
- handler 反查产物（reply_video_path）原样交到能力层，能力层现场分析并经
  咽喉（`guard_secondhand_text`）注入视频档案转述块，档案以 reply_id 为锚登记
  （user_sent）；
- 档案缓存命中时两端一致：handler 零 ack 零反查，能力层直接吃缓存简报；
- 再导出路径（runtime._prepare_video_understanding_message）与定义处同一
  函数对象，节流状态随定义处模块走（patch 必须打在 video_pipeline）。
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

import plugins.bot_unified_runtime as runtime
from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    ContextBundle,
    IncomingMessage,
    MemoryRetrievalResult,
    PersonaProfile,
    RetrievalResult,
    SessionType,
    ToneProfile,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import (
    chat as chat_module,
)
from plugins.bot_unified_runtime.domains.media.ingest import video_understanding as vu
from plugins.bot_unified_runtime.domains.media.video import video_pipeline


class _FakeRegistry:
    """最小档案库替身：默认全部未命中，可带缓存档案。"""

    def __init__(self, asset: SimpleNamespace | None = None) -> None:
        self._asset = asset
        self.registered: list[object] = []
        self.updated_briefs: list[tuple[str, str, str]] = []

    def lookup_by_message_id(self, message_id: str) -> SimpleNamespace | None:
        return self._asset

    def register(self, record: object) -> str:
        self.registered.append(record)
        return "media-new"

    def update_brief(self, media_id: str, brief_text: str, brief_signals: str) -> None:
        self.updated_briefs.append((media_id, brief_text, brief_signals))


class _Bot:
    async def call_api(self, action: str, **params: object):
        return {"message": [{"type": "video", "data": {"url": "https://v.example/a.mp4"}}]}


class _ContextProvider:
    def build_context(self, **kwargs: object) -> ContextBundle:
        request_id = str(kwargs["request_id"])
        return ContextBundle(
            request_id=request_id,
            persona=PersonaProfile(
                profile_id="p",
                version="1",
                display_name="守岸人",
                identity="测试人格",
            ),
            tone=ToneProfile(profile_id="p", mode="chat"),
            memory_results=MemoryRetrievalResult(request_id=request_id),
            knowledge_results=RetrievalResult(request_id=request_id),
            current_message=str(kwargs["query_text"]),
            sender_id=str(kwargs["sender_id"]),
            session_id=str(kwargs["session_id"]),
        )


def _user_text(messages: list[dict[str, str]]) -> str:
    """FIX2：RP 席文风 system 消息追加到 messages 末位后，user 消息不再恒居
    [-1]——按 role 聚合 user 内容作断言靶位，简报注入语义本身不变。"""
    return "\n".join(
        str(item.get("content", "")) for item in messages if item.get("role") == "user"
    )


class _CaptureLLM:
    def __init__(self) -> None:
        self.messages: list[list[dict[str, str]]] = []

    def generate(self, messages: list[dict[str, str]], **kwargs: object):
        self.messages.append(messages)
        return SimpleNamespace(
            text="这视频里是一只猫哦。",
            tool_calls=None,
            raw_usage={},
            usage={},
            finish_reason="stop",
            provider="fake",
            model="fake",
            confidence=1.0,
        )


def _message(**overrides: object) -> IncomingMessage:
    values: dict[str, object] = {
        "platform": "qq",
        "adapter": "nonebot",
        "bot_id": "bot",
        "session_id": "g1",
        "session_type": SessionType.GROUP,
        "sender_id": "u1",
        "plain_text": "这视频里是什么",
        "raw_segments": [],
        "message_id": "M-in",
        "mentions_bot": True,
        "reply_to_message_id": "M-ext",
    }
    values.update(overrides)
    return IncomingMessage(**values)  # type: ignore[arg-type]


def _decision() -> BotDecision:
    return BotDecision(
        request_id="r1",
        should_respond=True,
        mode="chat",
        trigger="mention",
        capability_id="bot.chat",
        target_scope=SessionType.GROUP,
        decision_reason="test",
    )


@pytest.fixture(autouse=True)
def _fresh_throttle() -> None:
    # 节流表随定义处模块走：原地表清空（不换绑），runtime 再导出与定义处保持同源。
    video_pipeline._VIDEO_ACK_THROTTLE.clear()


def _stub_brief(
    monkeypatch: pytest.MonkeyPatch,
    *,
    text: str = "画面：猫。",
) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    def fake_build(config: object, **kwargs: object) -> SimpleNamespace:
        calls.append({"config": config, **kwargs})
        return SimpleNamespace(text=text, signals={"frames": True})

    monkeypatch.setattr(vu, "build_video_brief", fake_build)
    return calls


def _inject_fetch(
    monkeypatch: pytest.MonkeyPatch, clip: Path
) -> None:
    """把 handler 的适配器反查换成"直接拿到 tmp_path 下真实小文件"。"""

    async def fake_fetch(bot: object, message_id: str, cfg: object) -> str:
        return str(clip)

    monkeypatch.setattr(video_pipeline, "_fetch_reply_video_file", fake_fetch)


def test_handler_fetch_feeds_capability_analysis(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """P1-1 接缝：handler 反查到的文件被能力层消费（分析+注入+建档）。"""
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    clip = tmp_path / "fetched_reply.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    _inject_fetch(monkeypatch, clip)
    registry = _FakeRegistry()  # 档案未命中：逼出 handler 反查 + 能力层现场分析

    sent: list[str] = []

    async def send(text: str) -> None:
        sent.append(text)

    prepared = asyncio.run(
        video_pipeline._prepare_video_understanding_message(
            _Bot(),
            _message(),
            send,
            config=SimpleNamespace(
                bot_video_understanding_enabled=True,
                bot_video_progress_ack_enabled=True,
                bot_video_progress_ack_cooldown_seconds=60,
                bot_download_dir=downloads,
            ),
            runtime_settings=None,
            media_registry=registry,
            media_providers_ready=True,
        )
    )
    assert prepared.reply_video_path == str(clip)  # handler 把文件挂上了消息
    assert sent == [video_pipeline._VIDEO_ACK_TEXT]  # 且对用户说了"稍等"

    # 同一条（handler 加工后的）消息进能力层：文件必须真的被消费。
    calls = _stub_brief(monkeypatch)
    llm = _CaptureLLM()
    capability = chat_module.build_chat_capability(
        character_provider=_ContextProvider(),
        llm_provider=llm,
        media_registry=registry,
        video_understanding_enabled=True,
    )
    capability(prepared, _decision())
    assert calls and calls[0]["video_source"] == str(clip)
    user_prompt = _user_text(llm.messages[0])
    assert "以下是视频档案" in user_prompt  # 2026-09-27 M-02 收口：断言靶改咽喉产物特征
    assert "画面：猫。" in user_prompt
    assert registry.registered and registry.updated_briefs  # 以 reply_id 为锚建档


def test_cached_brief_hit_agrees_on_both_sides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """档案缓存命中：handler 零 ack 零反查，能力层直接注入缓存简报、零分析。"""

    async def forbidden_fetch(bot: object, message_id: str, cfg: object) -> str:
        raise AssertionError("缓存命中时 handler 不得反查适配器")

    monkeypatch.setattr(video_pipeline, "_fetch_reply_video_file", forbidden_fetch)
    asset = SimpleNamespace(
        media_id="media-ext",
        chat_message_id="M-ext",
        session_id="g1",
        source_kind="user_sent",
        platform="qq",
        item_id="",
        canonical_url="",
        title="外部视频",
        creator_name="",
        duration_ms=None,
        local_path="",
        subtitle_text="",
        brief_text="画面：猫。",
        brief_signals="",
    )
    registry = _FakeRegistry(asset)

    sent: list[str] = []

    async def send(text: str) -> None:
        sent.append(text)

    prepared = asyncio.run(
        video_pipeline._prepare_video_understanding_message(
            _Bot(),
            _message(),
            send,
            config=SimpleNamespace(
                bot_video_understanding_enabled=True,
                bot_video_progress_ack_enabled=True,
                bot_video_progress_ack_cooldown_seconds=60,
                bot_download_dir=tmp_path / "downloads",
            ),
            runtime_settings=None,
            media_registry=registry,
            media_providers_ready=True,
        )
    )
    assert sent == []  # 缓存命中：不"稍等"，直接答
    assert prepared.reply_video_path == ""  # 也没反查出文件

    calls = _stub_brief(monkeypatch)
    llm = _CaptureLLM()
    capability = chat_module.build_chat_capability(
        character_provider=_ContextProvider(),
        llm_provider=llm,
        media_registry=registry,
        video_understanding_enabled=True,
    )
    capability(prepared, _decision())
    assert calls == []  # 能力层同样零现场分析
    assert "以下是视频档案" in _user_text(llm.messages[0])
    assert "画面：猫。" in _user_text(llm.messages[0])


def test_reexport_path_shares_definition_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """旧访问路径（runtime.*）与定义处同一函数对象/同一节流表，且照常工作。"""
    clip = tmp_path / "fetched_reply.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    _inject_fetch(monkeypatch, clip)
    assert (
        runtime._prepare_video_understanding_message
        is video_pipeline._prepare_video_understanding_message
    )
    assert runtime._VIDEO_ACK_THROTTLE is video_pipeline._VIDEO_ACK_THROTTLE

    sent: list[str] = []

    async def send(text: str) -> None:
        sent.append(text)

    config = SimpleNamespace(
        bot_video_understanding_enabled=True,
        bot_video_progress_ack_enabled=True,
        bot_video_progress_ack_cooldown_seconds=60,
        bot_download_dir=tmp_path / "downloads",
    )

    async def two_rounds() -> None:
        await runtime._prepare_video_understanding_message(
            _Bot(), _message(), send, config=config, runtime_settings=None,
            media_registry=None, media_providers_ready=True,
        )
        await runtime._prepare_video_understanding_message(
            _Bot(), _message(), send, config=config, runtime_settings=None,
            media_registry=None, media_providers_ready=True,
        )

    asyncio.run(two_rounds())
    # 同会话第二条被 video_pipeline 模块级节流表压住：只应有一条 ack。
    assert sent == [video_pipeline._VIDEO_ACK_TEXT]
