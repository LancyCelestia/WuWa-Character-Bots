"""订阅推送 vision 增强 helper（describe_subscription_item）。"""

from __future__ import annotations

from typing import Any

from plugins.bot_unified_runtime.domains.media.ingest import vision_describe as V
from plugins.bot_unified_runtime.domains.media.ingest.vision_describe import (
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


def test_subscription_vision_describes_first_media_url(monkeypatch) -> None:
    # F-2 口径跟随（席位 S-ATKFIX-SSRF1）：假域名 img.test 在咽喉=解析失败=拒绝→丢图；
    # 本测锁「预览图优先+只挂一张」的消息形态，下载腿替成瞬时失败形态（保留原 URL）。
    monkeypatch.setattr(V, "_download_image_bytes", lambda url, **kw: None)
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


def test_subscription_vision_falls_back_to_cover_key(monkeypatch) -> None:
    # F-2 口径跟随：同上，替下载腿锁「无 media 时取 cover」分支。
    monkeypatch.setattr(V, "_download_image_bytes", lambda url, **kw: None)
    provider = _FakeProvider()
    text = describe_subscription_item(provider, {"cover": "https://img.test/cover.jpg"})
    assert text
