"""转发聊天记录回归：入站放行 + 回执解析容忍度（评审：转发无回应根因）。

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_forward_message_ingest.py -q

根因：合并转发消息的 plain_text **为空**，且转发段既不属于视觉段也不属于音频段
→ 路由判 IGNORE → chat handler 不触发 → 抓转发正文的代码（在 handler 内部）
永远跑不到。表现为"转发聊天记录给 bot 毫无回应"，且日志无痕（旧实现把
get_forward_msg 的异常全吞掉）。
"""
from __future__ import annotations

import asyncio

from plugins.bot_unified_runtime import (
    FORWARD_SEGMENT_TYPES,
    _forward_message_text,
    _forward_message_text_sync,
    contains_audio_message_segments,
    contains_forward_message_segments,
    contains_visual_message_segments,
)

# ------------------------------------------------------------------ 入站放行


def test_forward_segment_is_detected() -> None:
    assert contains_forward_message_segments([{"type": "forward", "data": {"id": "x"}}]) is True


def test_forward_segment_aliases_detected() -> None:
    for kind in ("chat_history", "messages"):
        assert contains_forward_message_segments([{"type": kind, "data": {}}]) is True, kind


def test_forward_is_not_visual_or_audio() -> None:
    """转发段必须与视觉/音频区分——否则门禁逻辑会把语义混在一起。"""
    segments = [{"type": "forward", "data": {"id": "x"}}]
    assert contains_visual_message_segments(segments) is False
    assert contains_audio_message_segments(segments) is False


def test_non_forward_segments_not_flagged() -> None:
    for segments in ([], None, [{"type": "text", "data": {"text": "hi"}}]):
        assert contains_forward_message_segments(segments) is False


def test_forward_segment_types_cover_known_forms() -> None:
    assert {"forward", "chat_history", "messages"} <= set(FORWARD_SEGMENT_TYPES)


# --------------------------------------------------------------- 回执解析


def test_parse_canonical_shape() -> None:
    """标准形态：messages[*].message[*].data.text，并带上发送者昵称。"""
    payload = {
        "messages": [
            {
                "sender": {"nickname": "甲"},
                "message": [
                    {"type": "text", "data": {"text": "第一句"}},
                    {"type": "text", "data": {"text": "第二句"}},
                ],
            }
        ]
    }
    text = _forward_message_text_sync(payload)
    assert "甲" in text
    assert "第一句" in text and "第二句" in text


def test_parse_data_wrapper_shape() -> None:
    """有些实现把业务数据包在 data 里。"""
    payload = {"data": {"messages": [{"sender": {"card": "乙"}, "message": [
        {"type": "text", "data": {"text": "在吗"}}]}]}}
    assert "在吗" in _forward_message_text_sync(payload)


def test_parse_sender_card_preferred_over_nickname() -> None:
    payload = {"messages": [{"sender": {"card": "群名片", "nickname": "昵称"},
                             "message": [{"type": "text", "data": {"text": "x"}}]}]}
    assert "群名片" in _forward_message_text_sync(payload)


def test_parse_media_labels_kept() -> None:
    """转发里的图片/语音/视频至少要留下标签，不能整段丢。"""
    payload = {
        "messages": [
            {
                "sender": {"nickname": "丙"},
                "message": [
                    {"type": "image", "data": {}},
                    {"type": "record", "data": {}},
                    {"type": "video", "data": {}},
                ],
            }
        ]
    }
    text = _forward_message_text_sync(payload)
    assert "[图片]" in text and "[语音]" in text and "[视频]" in text


def test_parse_returns_empty_on_unknown_shape() -> None:
    for payload in (None, {}, [], {"messages": "not-a-list"}, {"unexpected": 1}):
        assert _forward_message_text_sync(payload) == ""


# ------------------------------------------------------------- 异步 + 可观测


class _FakeBot:
    def __init__(self, result=None, *, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    async def call_api(self, api: str, **payload):
        self.calls.append((api, payload))
        if self.error is not None:
            raise self.error
        return self.result


class _Event:
    def __init__(self, segments) -> None:
        self._segments = segments

    def get_message(self):
        return self._segments


def test_async_fetch_uses_get_forward_msg_with_segment_id() -> None:
    bot = _FakeBot({"messages": [{"sender": {"nickname": "甲"},
                                  "message": [{"type": "text", "data": {"text": "hi"}}]}]})
    event = _Event([{"type": "forward", "data": {"id": "FWD-1"}}])
    text = asyncio.run(_forward_message_text(bot, event))
    assert "hi" in text
    assert bot.calls == [("get_forward_msg", {"message_id": "FWD-1"})]


def test_async_fetch_no_segment_means_no_api_call() -> None:
    """非转发消息不得触发 get_forward_msg（NapCat 时期普通 id 会被拒绝）。"""
    bot = _FakeBot({})
    event = _Event([{"type": "text", "data": {"text": "普通消息"}}])
    assert asyncio.run(_forward_message_text(bot, event)) == ""
    assert bot.calls == []


def test_async_fetch_survives_api_error() -> None:
    """上游报错必须降级为空串（不抛），否则整条消息处理会被打断。"""
    bot = _FakeBot(error=RuntimeError("get_forward_msg rejected"))
    event = _Event([{"type": "forward", "data": {"id": "FWD-2"}}])
    assert asyncio.run(_forward_message_text(bot, event)) == ""


def test_async_fetch_reports_empty_payload(caplog) -> None:
    """回执解析不出正文时要留 warning（旧实现静默无痕，是本次排查困难的根因）。"""
    import logging

    bot = _FakeBot({"unexpected": True})
    event = _Event([{"type": "forward", "data": {"id": "FWD-3"}}])
    with caplog.at_level(logging.WARNING):
        assert asyncio.run(_forward_message_text(bot, event)) == ""
    assert any("no text" in record.message for record in caplog.records)


# ------------------------------------------------- 多层嵌套转发递归展开
# 2026-09-18 核心链路排查：旧实现 `nested_ids[:4]` 只展开**一层**，且对更深层
# 不再递归——"转发里再转发"的聊天记录内容整段丢失（用户实测「递归子记录
# 读不了」）。下列用例锁定新的递归语义：按深度展开 + 环引用终止。


class _RoutedBot:
    """按 message_id 返回不同回执的假 bot（多层嵌套场景专用）。"""

    def __init__(self, routes: dict) -> None:
        self.routes = routes
        self.calls: list[tuple[str, dict]] = []

    async def call_api(self, api: str, **payload):
        self.calls.append((api, payload))
        return self.routes.get(str(payload.get("message_id")), {})


def _fwd_message(nested_id: str, text: str = "") -> list[dict]:
    segments: list[dict] = []
    if text:
        segments.append({"type": "text", "data": {"text": text}})
    if nested_id:
        segments.append({"type": "forward", "data": {"id": nested_id}})
    return segments


def test_async_fetch_expands_deeply_nested_forwards() -> None:
    """三层嵌套转发必须逐层展开（旧实现只到第一层，深层内容丢失）。"""
    routes = {
        "L1": {"messages": [{"sender": {"nickname": "甲"}, "message": _fwd_message("L2", "第一层")}]},
        "L2": {"messages": [{"sender": {"nickname": "乙"}, "message": _fwd_message("L3", "第二层")}]},
        "L3": {"messages": [{"sender": {"nickname": "丙"}, "message": _fwd_message("", "第三层")}]},
    }
    bot = _RoutedBot(routes)
    event = _Event([{"type": "forward", "data": {"id": "L1"}}])
    text = asyncio.run(_forward_message_text(bot, event))
    assert "第一层" in text
    assert "第二层" in text, "嵌套第二层必须展开"
    assert "第三层" in text, "嵌套第三层必须展开（旧实现止于第一层）"
    assert [call[1]["message_id"] for call in bot.calls] == ["L1", "L2", "L3"]


def test_async_fetch_terminates_on_forward_cycle() -> None:
    """A→B→A 互引必须被去重拦住，不得无限递归。"""
    routes = {
        "A": {"messages": [{"sender": {}, "message": _fwd_message("B")}]},
        "B": {"messages": [{"sender": {}, "message": _fwd_message("A")}]},
    }
    bot = _RoutedBot(routes)
    event = _Event([{"type": "forward", "data": {"id": "A"}}])
    asyncio.run(_forward_message_text(bot, event))
    # 起点 A + 子节点 B；B 指向的 A 已见，必须终止（不产生第 3 次调用）。
    assert [call[1]["message_id"] for call in bot.calls] == ["A", "B"]
