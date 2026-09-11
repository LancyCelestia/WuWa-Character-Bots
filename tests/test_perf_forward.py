"""合并转发抓取超时可配化回归：Config 默认值 + _forward_message_text 超时注入。

全部离线：不触网，只验证超时参数的传递路径（wait_for 收到注入的 timeout）。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest


def test_forward_timeout_config_default() -> None:
    """Config 默认提供 bot_forward_fetch_timeout_seconds=5.0。"""
    from plugins.bot_unified_runtime.config import Config

    assert Config().bot_forward_fetch_timeout_seconds == 5.0


def test_forward_message_text_uses_configured_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_forward_message_text 接受 timeout_seconds 关键字并传给 wait_for。"""
    import plugins.bot_unified_runtime as m

    captured: dict[str, object] = {}

    async def fake_wait_for(awaitable, timeout=None):
        captured["timeout"] = timeout
        return await awaitable

    async def fake_call_api(api: str, **kwargs):
        captured["api"] = api
        # 非 dict 结果会让函数返回空串；本测试只关心 timeout 的传递。
        return SimpleNamespace()

    monkeypatch.setattr(m, "_forward_segment_id", lambda event: "123")
    monkeypatch.setattr(m.asyncio, "wait_for", fake_wait_for)

    fake_bot = SimpleNamespace(call_api=fake_call_api)
    text = asyncio.run(
        m._forward_message_text(fake_bot, SimpleNamespace(), timeout_seconds=3.5)
    )

    assert captured["timeout"] == 3.5
    assert captured["api"] == "get_forward_msg"
    assert text == ""
