"""white2 触发补强回归：纯文本 @ 与"回复机器人发过的视频"都算硬点名。

锁定行为：
- 复制/手打的纯文本 "@昵称"（非平台 at 段）= 硬点名，white2 放行；
- 普通问句（无 @）不受影响，软点名仍被 white2 拒绝；
- 小名停用词不因 @ 形式误触发（"@什么"不算点名）；
- 回复的消息若是机器人自己发过的视频（媒体档案 bot_sent 锚点命中），
  即使没有 @ 也算硬点名；回复别人的视频不算。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import plugins.bot_unified_runtime as runtime
from plugins.bot_unified_runtime.policy.gate import PolicySettings, evaluate_policy


@pytest.fixture(autouse=True)
def _mention_terms(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime, "_RUNTIME_MENTION_TERMS", ["守岸人"])
    monkeypatch.setattr(
        runtime,
        "_AFFINITY_NICKNAMES_CACHE",
        ["岸宝", "小岸同学", "我的蒙娜丽莎"],
    )


def test_text_at_mention_detected() -> None:
    assert runtime._detect_text_at_mention("@守岸人 这个视频里是什么") is True
    assert runtime._detect_text_at_mention("帮我问下@守岸人在吗") is True


def test_text_at_mention_supports_affinity_nickname() -> None:
    assert runtime._detect_text_at_mention("@岸宝 看看这个") is True
    assert runtime._detect_text_at_mention("@小岸同学 帮个忙") is True
    assert runtime._detect_text_at_mention("@我的蒙娜丽莎 在吗") is True


def test_text_at_mention_ignores_non_bot_targets() -> None:
    assert runtime._detect_text_at_mention("@路人甲 你好") is False
    assert runtime._detect_text_at_mention("邮箱 user@example.com 里有验证码") is False


def test_text_at_mention_requires_at_symbol() -> None:
    assert runtime._detect_text_at_mention("守岸人 这个视频里是什么") is False
    assert runtime._detect_text_at_mention("这是什么") is False


def test_text_at_mention_respects_nickname_stopwords() -> None:
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(runtime, "_AFFINITY_NICKNAMES_CACHE", ["什么"])
        assert runtime._detect_text_at_mention("@什么") is False
    finally:
        monkeypatch.undo()


class _FakeEvent(SimpleNamespace):
    """type().__module__ 落在本测试模块（不含 .mail/.telegram）→ 按 OneBot 归一化。"""


def _event(
    text: str,
    *,
    reply_id: str | None = None,
    tome: bool = False,
) -> SimpleNamespace:
    return _FakeEvent(
        get_plaintext=lambda: text,
        get_session_id=lambda: "group_999",
        message_id="M-in",
        group_id=999,
        get_user_id=lambda: "u1",
        reply_to=None,
        reply_to_message_id=reply_id,
        is_tome=lambda: tome,
    )


class _FakeRegistry:
    def __init__(self, asset: SimpleNamespace | None) -> None:
        self._asset = asset

    def lookup_by_message_id(self, message_id: str) -> SimpleNamespace | None:
        return self._asset


def _classify(text: str, *, reply_id: str | None = None, tome: bool = False):
    return runtime._incoming_from_nonebot_event(
        bot_id="bot-1",
        event=_event(text, reply_id=reply_id, tome=tome),
        segments=[{"type": "text", "data": {"text": text}}],
    )


def test_classify_text_at_mention_is_hard() -> None:
    message = _classify("@守岸人 这是什么")
    assert message.mentions_bot is True
    assert message.name_mention_only is False


def test_classify_plain_name_mention_is_true_call() -> None:
    """策展人格昵称（守岸人）= 真点名：等同 @，white2 严格群也叫应。

    2026-09-11 语义分层前的旧行为是保持软触发（name_mention_only=True），
    导致群里叫「岸宝」「守岸人」bot 不应答——已改为硬点名。
    """
    message = _classify("守岸人 这是什么")
    assert message.mentions_bot is True
    assert message.name_mention_only is False


def test_classify_reply_to_bot_sent_video_is_hard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        runtime._MEDIA_RUNTIME_SINGLETON,
        "registry",
        _FakeRegistry(SimpleNamespace(source_kind="bot_sent")),
    )
    message = _classify("这视频里是什么", reply_id="M-bot-video")
    assert message.mentions_bot is True
    assert message.name_mention_only is False


def test_classify_reply_to_user_sent_video_not_hard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        runtime._MEDIA_RUNTIME_SINGLETON,
        "registry",
        _FakeRegistry(SimpleNamespace(source_kind="user_sent")),
    )
    message = _classify("这视频里是什么", reply_id="M-user-video")
    assert message.mentions_bot is False


def test_white2_gate_allows_reply_to_bot_video_without_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        runtime._MEDIA_RUNTIME_SINGLETON,
        "registry",
        _FakeRegistry(SimpleNamespace(source_kind="bot_sent")),
    )
    message = _classify("这视频里是什么", reply_id="M-bot-video")
    settings = PolicySettings(group_white2=frozenset({"group:999"}))
    decision = evaluate_policy(message, "bot.chat", settings)
    assert decision.allowed is True


def test_text_at_mention_rejects_noun_extension(monkeypatch: pytest.MonkeyPatch) -> None:
    # 昵称后接名词性扩展（后援会/酱）不是在叫我。
    monkeypatch.setattr(runtime, "_AFFINITY_NICKNAMES_CACHE", ["守岸人", "岸宝"])
    assert runtime._detect_text_at_mention("@守岸人后援会今天成立") is False
    assert runtime._detect_text_at_mention("@岸宝酱好可爱") is False
    assert runtime._detect_text_at_mention("@守岸人在吗") is True
