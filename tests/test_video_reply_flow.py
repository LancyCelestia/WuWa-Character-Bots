"""视频追问链路回归（能力级）：回复引用视频 → 档案简报注入 + 人格守则 + 档案登记。

锁定行为：
- 回复已知档案（有缓存简报）→ 简报注入 user 消息、媒体应对守则进 system、档案被 touch；
- 回复已知档案（无简报）且 handler 反查到视频文件 → 现场分析并 update_brief 回写；
- 当前消息自带视频 → 编排器分析 + 注册 user_sent 档案（锚点=本条消息 id）；
- 总开关关闭 → 不触达媒体档案，走旧 describe_video 行为；
- 回复未知的视频且无反查文件 → 不注入、不登记；
- 模糊追问（配置开启 + 文本提到视频）→ 命中会话内最近档案。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

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


class _FakeRegistry:
    """SQLiteMediaRegistry 的最小行为替身：记录调用供断言。"""

    def __init__(self, assets: list[SimpleNamespace] | None = None) -> None:
        self.assets = {asset.chat_message_id: asset for asset in (assets or [])}
        self.registered: list[SimpleNamespace] = []
        self.updated_briefs: list[tuple[str, str, str]] = []
        self.touched: list[str] = []

    def register(self, record: SimpleNamespace) -> str:
        self.registered.append(record)
        self.assets[record.chat_message_id] = record
        return record.media_id

    def lookup_by_message_id(self, message_id: str) -> SimpleNamespace | None:
        asset = self.assets.get(message_id)
        if asset is not None:
            self.touched.append(message_id)
        return asset

    def lookup_recent_in_session(
        self, session_id: str, *, within_seconds: int
    ) -> SimpleNamespace | None:
        for asset in self.assets.values():
            if asset.session_id == session_id:
                self.touched.append(asset.chat_message_id)
                return asset
        return None

    def update_brief(self, media_id: str, brief_text: str, brief_signals: str) -> None:
        self.updated_briefs.append((media_id, brief_text, brief_signals))

    def touch(self, media_id: str) -> None:
        self.touched.append(media_id)


def _asset(message_id: str, **overrides: object) -> SimpleNamespace:
    values = {
        "media_id": f"media-{message_id}",
        "chat_message_id": message_id,
        "session_id": "g1",
        "source_kind": "bot_sent",
        "platform": "bilibili",
        "item_id": "BV1",
        "canonical_url": "https://b23.tv/BV1",
        "title": "测试视频",
        "creator_name": "UP主",
        "duration_ms": 12_000,
        "local_path": "",
        "subtitle_text": "大家好欢迎收看",
        "brief_text": "",
        "brief_signals": "",
        "created_at": 0,
        "last_accessed_at": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


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
        "message_id": "M2",
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
def _fresh_media_state(monkeypatch: pytest.MonkeyPatch) -> None:
    # 模糊注入/深挖节流是模块级状态：每个测试换空表，互不残留。
    monkeypatch.setattr(chat_module, "_FUZZY_INJECTION_AT", {})
    monkeypatch.setattr(chat_module, "_DEEP_REANALYSIS_AT", {})


def _stub_brief(
    monkeypatch: pytest.MonkeyPatch,
    *,
    text: str = "画面：猫跳上桌。",
) -> list[dict[str, object]]:
    """把编排器换成桩，记录调用参数；返回调用记录列表。"""
    calls: list[dict[str, object]] = []

    def fake_build(config: object, **kwargs: object) -> SimpleNamespace:
        calls.append({"config": config, **kwargs})
        return SimpleNamespace(text=text, signals={"frames": True})

    monkeypatch.setattr(vu, "build_video_brief", fake_build)
    return calls


def _run(
    registry: _FakeRegistry | None,
    llm: _CaptureLLM,
    message: IncomingMessage,
    *,
    vision_provider: object | None = None,
    media_config: object | None = None,
    enabled: bool = True,
):
    capability = chat_module.build_chat_capability(
        character_provider=_ContextProvider(),
        llm_provider=llm,
        media_registry=registry,
        video_understanding_enabled=enabled,
        vision_provider=vision_provider,
        media_config=media_config,
    )
    return capability(message, _decision())


def _user_text(messages: list[dict[str, str]]) -> str:
    """FIX2：RP 席文风 system 消息追加到 messages 末位后，user 消息不再恒居
    [-1]——按 role 聚合 user 内容作断言靶位，简报注入语义本身不变。"""
    return "\n".join(
        str(item.get("content", "")) for item in messages if item.get("role") == "user"
    )


# SECTEXT-GUARD 波（台账 #58★）后，「视频档案」这块边界标签的真身写手是**中央二手
# 咽喉**：chat.py 视频腿调 guard_secondhand_text(video_brief_text,
# source_label='视频档案')，由 injection._SECONDHAND_LEAD_TEMPLATE 拼出引导句。
# 帽字 `[视频档案]` 只由简报合成器 video_understanding.build_video_brief 首行自写，
# 而本档用 _stub_brief／_asset(brief_text=...) 把合成器整颗换成桩，桩文本天然缺帽
# ⇒ 旧靶 `[视频档案` 量的是替身的手拼，不是生产的那条腿（HEAD 起 7 枚红）。
# 重锚到咽喉自己的不变量：引导句里嵌着 source_label，一句同时锁住
# ①简报确实注入 ②确实过中央件 ③标签归谁写。正例与反例共用本常量——
# 反例若仍锚旧帽字，那条断言会在简报真的注入时也恒绿（静丢牙）。
_VIDEO_GUARD_LEAD = "以下是视频档案的转述内容"


def _all_user_text(calls: list[list[dict[str, str]]]) -> str:
    """整轮聚合：一轮回复会触发**多次** generate（复核／改写二遍），反例腿只看
    messages[0] 会漏掉"简报只在后面某遍溜进来"这一形——凡判"不该注入"就全本轮看。"""
    return "\n".join(_user_text(call) for call in calls)


def test_reply_known_asset_with_cached_brief_injects_and_touches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _stub_brief(monkeypatch)
    registry = _FakeRegistry([_asset("M1", brief_text="画面：猫跳上桌。")])
    llm = _CaptureLLM()
    result = _run(registry, llm, _message(reply_to_message_id="M1"))
    user_text = _user_text(llm.messages[0])
    system_prompt = llm.messages[0][0]["content"]
    assert _VIDEO_GUARD_LEAD in user_text
    assert "猫跳上桌" in user_text
    assert "媒体应对守则" in system_prompt
    assert registry.touched == ["M1"]
    assert calls == []  # 命中缓存：编排器零调用
    assert result.audit_tags  # 正常产出回复

def test_reply_known_asset_without_brief_analyzes_and_updates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clip = tmp_path / "reply.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    calls = _stub_brief(monkeypatch)
    registry = _FakeRegistry([_asset("M1")])
    llm = _CaptureLLM()
    _run(
        registry,
        llm,
        _message(reply_to_message_id="M1", reply_video_path=str(clip)),
    )
    assert calls, "无缓存简报时必须现场分析"
    assert calls[0]["video_source"] == str(clip)
    assert calls[0]["subtitle_text"] == "大家好欢迎收看"
    assert "测试视频" in str(calls[0]["metadata_text"])
    assert registry.updated_briefs and registry.updated_briefs[0][0] == "media-M1"
    assert _VIDEO_GUARD_LEAD in _user_text(llm.messages[0])


def test_current_video_message_analyzes_and_registers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    calls = _stub_brief(monkeypatch)
    registry = _FakeRegistry()
    llm = _CaptureLLM()
    _run(
        registry,
        llm,
        _message(
            raw_segments=[{"type": "video", "data": {"file": str(clip)}}],
        ),
    )
    assert calls and calls[0]["video_source"] == str(clip)
    assert len(registry.registered) == 1
    record = registry.registered[0]
    assert record.source_kind == "user_sent"
    assert record.chat_message_id == "M2"
    assert record.local_path == str(clip)
    assert registry.updated_briefs and registry.updated_briefs[0][0] == record.media_id
    assert _VIDEO_GUARD_LEAD in _user_text(llm.messages[0])


def test_disabled_switch_keeps_legacy_and_registry_untouched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    calls = _stub_brief(monkeypatch)
    monkeypatch.setattr(chat_module, "describe_video", lambda *a, **k: "")
    registry = _FakeRegistry([_asset("M1", brief_text="画面：缓存简报。")])
    llm = _CaptureLLM()
    _run(
        registry,
        llm,
        _message(reply_to_message_id="M1"),
        enabled=False,
    )
    assert calls == []
    assert registry.touched == []
    assert _VIDEO_GUARD_LEAD not in _all_user_text(llm.messages)


def test_reply_unknown_video_without_fetch_does_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _stub_brief(monkeypatch)
    registry = _FakeRegistry()
    llm = _CaptureLLM()
    _run(registry, llm, _message(reply_to_message_id="M9"))
    assert calls == []
    assert registry.registered == []
    assert _VIDEO_GUARD_LEAD not in _all_user_text(llm.messages)


def test_fuzzy_followup_uses_recent_asset_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_brief(monkeypatch)
    registry = _FakeRegistry([_asset("M0", brief_text="画面：早前视频。")])
    llm = _CaptureLLM()
    cfg = SimpleNamespace(bot_video_fuzzy_followup=True)
    _run(
        registry,
        llm,
        _message(plain_text="刚才那个视频讲了什么"),
        media_config=cfg,
    )
    assert _VIDEO_GUARD_LEAD in _user_text(llm.messages[0])
    assert registry.touched


def test_deep_request_reanalyzes_cached_brief(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    calls = _stub_brief(monkeypatch)
    registry = _FakeRegistry(
        [_asset("M1", brief_text="旧简报。", local_path=str(clip))]
    )
    llm = _CaptureLLM()
    _run(
        registry,
        llm,
        _message(plain_text="再仔细看看这个视频", reply_to_message_id="M1"),
    )
    assert calls and calls[0].get("deep") is True
    assert registry.updated_briefs
    assert _VIDEO_GUARD_LEAD in _user_text(llm.messages[0])


def test_fuzzy_deictic_reference_triggers(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_brief(monkeypatch)
    registry = _FakeRegistry([_asset("M0", brief_text="画面：早前视频。")])
    llm = _CaptureLLM()
    _run(
        registry,
        llm,
        _message(plain_text="刚才那个讲了什么"),
        media_config=SimpleNamespace(bot_video_fuzzy_followup=True),
    )
    assert _VIDEO_GUARD_LEAD in _user_text(llm.messages[0])


def test_fuzzy_injection_rate_limited_within_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 模糊注入每会话一个窗口只发生一次：窗口内的后续指代不再背简报。
    _stub_brief(monkeypatch)
    registry = _FakeRegistry([_asset("M0", brief_text="画面：早前视频。")])
    llm = _CaptureLLM()
    cfg = SimpleNamespace(bot_video_fuzzy_followup=True)
    _run(
        registry,
        llm,
        _message(plain_text="刚才那个讲了什么"),
        media_config=cfg,
    )
    # 一轮回复可能触发**多次** generate（复核／改写二遍），_CaptureLLM 按调用追加：
    # 旧写法拿 llm.messages[1] 当"第二条消息"，实际量到的是**第一轮自己的第二遍**，
    # 而它确实带着简报——旧靶 `[视频档案` 从不出现所以恒绿，把索引错位盖住了。
    # 现按轮次切界，并对**本轮全部** generate 调用下判据（简报要么整轮都在、
    # 要么整轮都不在，逐遍不一致同样是缺陷）。
    first_run_end = len(llm.messages)
    second = _run(
        registry,
        llm,
        _message(plain_text="开头唱的什么歌"),
        media_config=cfg,
    )
    first_run = llm.messages[:first_run_end]
    second_run = llm.messages[first_run_end:]
    assert first_run and second_run
    assert all(_VIDEO_GUARD_LEAD in _user_text(m) for m in first_run)
    assert all(_VIDEO_GUARD_LEAD not in _user_text(m) for m in second_run)
    assert second.audit_tags  # 第二条正常回复，只是不背简报
