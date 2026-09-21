"""审查 B-07 回归：OneBot v11 sender.level（QQ 群等级）摄取 + 用户画像分区渲染。

约束：
- 等级只作用户画像/上下文展示，不参与权限（权限仍由 RoleSettings 按 sender_id 决定）；
- 等级缺失（缺属性/None/0/空串/空白）一律不渲染该行（宁缺毋滥）。
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from plugins.bot_unified_runtime import _incoming_from_nonebot_event
from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    IncomingMessage,
    SessionType,
)


class _FakeOnebotEvent:
    # module 指向 onebot.v11 才会走 QQ 摄取分支（telegram/mail 各有独立路径）。
    __module__ = "nonebot.adapters.onebot.v11.event"

    def __init__(self, sender: Any) -> None:
        self.sender = sender

    def get_plaintext(self) -> str:
        return "你好"

    def get_session_id(self) -> str:
        return "group_999"

    def get_user_id(self) -> str:
        return "u1"

    def is_tome(self) -> bool:
        return False


def _ingest(sender: Any) -> IncomingMessage:
    return _incoming_from_nonebot_event(_FakeOnebotEvent(sender), bot_id="bot-1")


def test_sender_level_ingested_as_str() -> None:
    # NapCat 时期实测 level 可能是 int；摄取层统一 str 化。
    incoming = _ingest(SimpleNamespace(level=42))
    assert incoming.sender_level == "42"


def test_sender_level_str_value_passes_through_stripped() -> None:
    incoming = _ingest(SimpleNamespace(level="  42 "))
    assert incoming.sender_level == "42"


def test_sender_level_missing_yields_none() -> None:
    # 缺属性 / None / 空串 / 空白：一律 None（容缺省空，照 group_title 先例）。
    senders = (
        None,
        SimpleNamespace(),
        SimpleNamespace(level=None),
        SimpleNamespace(level=""),
        SimpleNamespace(level="   "),
    )
    for sender in senders:
        incoming = _ingest(sender)
        assert incoming.sender_level is None, repr(sender)


def test_sender_level_zero_treated_as_absent() -> None:
    # `or ""` 链让 0 与缺失同语义：等级 0 无展示意义（宁缺毋滥）。
    incoming = _ingest(SimpleNamespace(level=0))
    assert incoming.sender_level is None


class _ProfileNoteCaptureProvider:
    """代理 NullCharacterContextProvider，捕获传入 build_context 的画像分区文本。"""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.profile_notes: list[str] = []

    def build_context(self, *args: Any, **kwargs: Any) -> Any:
        self.profile_notes.append(str(kwargs.get("sender_profile_note", "")))
        return self._inner.build_context(*args, **kwargs)


def _run_capability(sender_level: str | None) -> str:
    """驱动 chat capability 走完整上下文组装，返回捕获的画像分区文本。"""
    from plugins.bot_unified_runtime.capabilities.chat import build_chat_capability
    from plugins.bot_unified_runtime.character.providers import (
        NullCharacterContextProvider,
    )
    from plugins.bot_unified_runtime.llm import StaticLLMProvider

    capture = _ProfileNoteCaptureProvider(NullCharacterContextProvider())
    cap = build_chat_capability(capture, StaticLLMProvider(text="你好。"))
    msg = IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="b",
        session_id="group:g",
        session_type=SessionType.GROUP,
        sender_id="u1",
        group_id="g",
        plain_text="你好",
        mentions_bot=True,
        sender_level=sender_level,
    )
    decision = BotDecision(
        request_id=msg.request_id,
        should_respond=True,
        mode="chat",
        trigger="mention",
        capability_id="bot.chat",
        target_scope=SessionType.GROUP,
        context_budget=12000,
        decision_reason="test",
        max_messages=0,
    )
    cap(msg, decision)
    assert capture.profile_notes, "build_context 未被调用"
    return capture.profile_notes[0]


def test_profile_note_renders_level_when_present() -> None:
    note = _run_capability("42")
    assert "等级=42" in note
    # 既有画像维度不因新增等级项而丢失。
    assert "群头衔=" in note
    assert "群名称=" in note


def test_profile_note_omits_level_when_absent() -> None:
    note = _run_capability(None)
    assert "等级=" not in note
