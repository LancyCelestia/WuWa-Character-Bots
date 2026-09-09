from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from plugins.bot_unified_runtime.contracts.subscription import (
    SubscriptionFetchResult,
    SubscriptionTarget,
)
from plugins.bot_unified_runtime.sources.subscriptions.social_v2 import (
    BilibiliSubscriptionAdapterV2,
    PixivSubscriptionAdapterV2,
    TelegramSubscriptionAdapterV2,
    TwitterSubscriptionAdapterV2,
    WeiboSubscriptionAdapterV2,
    XiaohongshuSubscriptionAdapterV2,
    YouTubeSubscriptionAdapterV2,
)


def test_required_adapters_declare_platform_and_target_kinds() -> None:
    adapters = [
        BilibiliSubscriptionAdapterV2(),
        XiaohongshuSubscriptionAdapterV2(),
        YouTubeSubscriptionAdapterV2(),
        TwitterSubscriptionAdapterV2(),
        TelegramSubscriptionAdapterV2(),
        PixivSubscriptionAdapterV2(),
        WeiboSubscriptionAdapterV2(),
    ]
    assert {adapter.platform for adapter in adapters} == {
        "bilibili",
        "xiaohongshu",
        "youtube",
        "twitter",
        "telegram",
        "pixiv",
        "weibo",
    }
    assert all(adapter.target_kinds for adapter in adapters)


@pytest.mark.parametrize(
    ("adapter", "raw", "kind", "key"),
    [
        (YouTubeSubscriptionAdapterV2(), "https://www.youtube.com/channel/UC1", "channel", "UC1"),
        (YouTubeSubscriptionAdapterV2(), "https://www.youtube.com/playlist?list=PL1", "playlist", "PL1"),
        (TwitterSubscriptionAdapterV2(), "https://x.com/alice", "creator", "alice"),
        (TelegramSubscriptionAdapterV2(), "https://t.me/s/example", "public_channel", "example"),
        (PixivSubscriptionAdapterV2(), "https://www.pixiv.net/users/42", "creator", "42"),
        (WeiboSubscriptionAdapterV2(), "https://weibo.com/u/42", "creator", "42"),
        (XiaohongshuSubscriptionAdapterV2(), "https://www.xiaohongshu.com/user/profile/u1", "creator", "u1"),
        (BilibiliSubscriptionAdapterV2(), "https://space.bilibili.com/42", "creator", "42"),
    ],
)
def test_required_adapter_resolves_public_target(adapter, raw, kind, key) -> None:
    now = datetime.now(timezone.utc)
    target = asyncio.run(adapter.resolve_target(raw, {"now": now}))
    assert isinstance(target, SubscriptionTarget)
    assert target.target_kind == kind
    assert target.target_key == key


def test_telegram_rejects_private_invite_link() -> None:
    with pytest.raises(ValueError, match="公开"):
        asyncio.run(
            TelegramSubscriptionAdapterV2().resolve_target(
                "https://t.me/+private", {}
            )
        )


def test_youtube_handle_resolves_to_real_channel_id(monkeypatch) -> None:
    from plugins.bot_unified_runtime.sources.subscriptions import social_v2

    def fake_get_text(url: str, **kwargs):
        assert url == "https://www.youtube.com/@3blue1brown"
        assert kwargs.get("proxy") == "" and kwargs.get("timeout") == 10.0
        return url, '<script>"externalId":"UCabc123_-"</script>'

    monkeypatch.setattr(social_v2, "http_get_text", fake_get_text)
    target = asyncio.run(
        YouTubeSubscriptionAdapterV2().resolve_target(
            "https://www.youtube.com/@3blue1brown", {}
        )
    )
    assert target.target_kind == "channel"
    assert target.target_key == "UCabc123_-"


def test_youtube_handle_channel_path_pattern_fallback_in_body(monkeypatch) -> None:
    from plugins.bot_unified_runtime.sources.subscriptions import social_v2

    monkeypatch.setattr(
        social_v2,
        "http_get_text",
        lambda url, **kwargs: (url, '<a href="/channel/UCxyz456">c</a>'),
    )
    target = asyncio.run(
        YouTubeSubscriptionAdapterV2().resolve_target(
            "https://www.youtube.com/@foo", {}
        )
    )
    assert target.target_kind == "channel"
    assert target.target_key == "UCxyz456"


def test_youtube_handle_resolution_failure_falls_back_to_handle(monkeypatch) -> None:
    from plugins.bot_unified_runtime.sources.subscriptions import social_v2

    def boom(url: str, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(social_v2, "http_get_text", boom)
    target = asyncio.run(
        YouTubeSubscriptionAdapterV2().resolve_target(
            "https://www.youtube.com/@3blue1brown", {}
        )
    )
    assert target.target_kind == "channel"
    assert target.target_key == "3blue1brown"


def test_adapter_client_failure_returns_structured_result() -> None:
    target = SubscriptionTarget(
        id="twitter:creator:alice",
        platform="twitter",
        target_kind="creator",
        target_key="alice",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    result = asyncio.run(
        TwitterSubscriptionAdapterV2().fetch_incremental(target, {}, {})
    )
    assert isinstance(result, SubscriptionFetchResult)
    assert result.error_code == "auth_required"
