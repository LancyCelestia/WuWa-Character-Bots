"""动图抽帧提示：拼条必须被声明为动图，否则模型只能按静图作答。"""

from __future__ import annotations

from typing import Any

from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
    build_direct_vision_messages,
)
from plugins.bot_unified_runtime.domains.media.ingest.vision_describe import (
    describe_images_with_status,
)


class _FakeProvider:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    def generate(self, messages: list[dict[str, Any]], **_: Any) -> Any:
        self.messages = messages

        class _Reply:
            text = "角色：不确定\n文字：无\n画面：三帧并排"

        return _Reply()


def _texts(message: dict[str, Any]) -> list[str]:
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [str(part.get("text", "")) for part in content if part.get("type") == "text"]


def test_direct_vision_marks_animation_filmstrip() -> None:
    messages = build_direct_vision_messages(
        [{"role": "user", "content": "原问题"}],
        query_text="这个动图里依次出现了哪几个字母？",
        image_urls=["data:image/jpeg;base64,AAAA"],
        animation_hint=True,
    )
    joined = "\n".join(_texts(messages[-1]))
    assert "动图抽帧" in joined
    assert "从左到右" in joined


def test_direct_vision_without_hint_stays_silent() -> None:
    messages = build_direct_vision_messages(
        [{"role": "user", "content": "原问题"}],
        query_text="图里写了什么？",
        image_urls=["data:image/jpeg;base64,AAAA"],
    )
    assert "动图抽帧" not in "\n".join(_texts(messages[-1]))


def test_describe_images_marks_animation_filmstrip() -> None:
    provider = _FakeProvider()
    text, kind = describe_images_with_status(
        provider,
        image_urls=["data:image/jpeg;base64,AAAA"],
        query_text="这个动图里有什么？",
        animation_hint=True,
    )
    assert kind == "ok"
    assert text
    user = [m for m in provider.messages if m.get("role") == "user"][-1]
    assert "动图抽帧" in "\n".join(_texts(user))
