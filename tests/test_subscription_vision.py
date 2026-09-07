"""订阅推送 vision 增强 helper（describe_subscription_item）。"""

from __future__ import annotations

from typing import Any

from plugins.bot_unified_runtime.sources.vision_describe import (
    describe_subscription_item,
)


class _FakeProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def generate(self, messages: Any, **kwargs: Any) -> Any:
        self.calls.append({"messages": messages, **kwargs})
        return type(
            "R",
            (),
            {"text": "角色：初音未来（VOCALOID）/文字：无/画面：葱色双马尾歌姬"},
        )()


def test_subscription_vision_requires_provider_and_images() -> None:
    payload = {"media": [{"url": "https://img.test/1.jpg"}]}
    assert describe_subscription_item(None, payload) == ""
    assert describe_subscription_item(_FakeProvider(), {}) == ""
    assert describe_subscription_item(_FakeProvider(), {"media": "oops"}) == ""


def test_subscription_vision_describes_first_media_url() -> None:
    provider = _FakeProvider()
    text = describe_subscription_item(
        provider,
        {
            "title": "新作品",
            "media": [
                {
                    "url": "https://img.test/1.jpg",
                    "preview_image_url": "https://img.test/p1.jpg",
                },
                {"url": "not-a-url"},
            ],
        },
    )
    assert text.startswith("角色：")
    sent = provider.calls[0]
    image_parts = [
        part
        for part in sent["messages"][1]["content"]
        if part.get("type") == "image_url"
    ]
    assert [part["image_url"]["url"] for part in image_parts] == [
        "https://img.test/p1.jpg"
    ]


def test_subscription_vision_falls_back_to_cover_key() -> None:
    provider = _FakeProvider()
    text = describe_subscription_item(provider, {"cover": "https://img.test/cover.jpg"})
    assert text
