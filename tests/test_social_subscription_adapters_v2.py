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
        # J-01 改写：twitter 行从「无凭证也解析成功」参数表撤出，改由下方
        # 两个专属测试分别锁定「无 cookie 显式拒绝」与「有 cookie 正常解析」。
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


def test_twitter_resolve_without_x_cookie_is_rejected_explicitly() -> None:
    # 审查 J-01：无 X cookie 时推特链接/冒号形态一律显式拒绝，不再
    # 「订阅成功但轮询恒 auth_required、永不推送」的静默路径（范式
    # 对齐 J-06 音乐订阅诚实化）。提示须指名推特并给出恢复条件。
    for raw in ("https://x.com/alice", "https://twitter.com/alice", "twitter:creator:alice"):
        with pytest.raises(ValueError) as excinfo:
            asyncio.run(TwitterSubscriptionAdapterV2().resolve_target(raw, {}))
        message = str(excinfo.value)
        assert "推特" in message
        assert "cookie" in message
        assert "/bot cookie import" in message


def test_twitter_resolve_with_x_cookie_still_resolves() -> None:
    # J-01 恢复条件锁：ctx 显式带 X cookie（与 fetch 门同判据）时照常
    # 解析——配置 X cookie 后订阅面自动恢复，无需改码。
    now = datetime.now(timezone.utc)
    target = asyncio.run(
        TwitterSubscriptionAdapterV2().resolve_target(
            "https://x.com/alice",
            {"now": now, "cookie_header": "auth_token=t; ct0=c"},
        )
    )
    assert isinstance(target, SubscriptionTarget)
    assert target.target_kind == "creator"
    assert target.target_key == "alice"


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
