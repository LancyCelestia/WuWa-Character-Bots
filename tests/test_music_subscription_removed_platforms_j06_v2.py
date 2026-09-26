"""审查 J-06 回归：音乐订阅注册面摘除「注册成功但恒 unsupported」平台。

摘除原因与恢复条件见 sources/subscriptions/music_v2.py 模块 docstring：
qqmusic/kuwo/kugou/apple_music/spotify 此前可订阅成功落库，但
fetch_incremental 无实现、恒返回 unsupported——用户订了永远收不到推送
也无提示。摘除后 /订阅 add 必须得到显式「暂不支持」提示且零落库。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.subscribe.adapters.music_v2 import (
    ADAPTERS as MUSIC_ADAPTERS,
)
from plugins.bot_unified_runtime.domains.subscribe.adapters.music_v2 import (
    MusicSubscriptionAdapterV2,
)
from plugins.bot_unified_runtime.domains.subscribe.capabilities.subscribe_v2 import (
    build_subscribe_capability_v2,
)
from plugins.bot_unified_runtime.domains.subscribe.store.subscription_runtime_v2 import (
    build_subscription_runtime_v2,
)

# 与 music_v2._REMOVED_PLATFORM_LABELS 同口径（注册面摘除清单）。
_REMOVED_PLATFORMS = ("qqmusic", "kuwo", "kugou", "apple_music", "spotify")


def _message(text: str) -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id="private:admin",
        session_type=SessionType.PRIVATE,
        sender_id="admin",
        plain_text=text,
    )


def _runtime(tmp_path):
    config = SimpleNamespace(
        bot_subscribe_db_path=str(tmp_path / "subscriptions.sqlite3"),
        bot_subscribe_global_concurrency=2,
        bot_subscribe_platform_concurrency=1,
        bot_subscribe_min_interval_seconds=0,
        bot_subscribe_lease_seconds=30,
        bot_subscribe_retry_base_seconds=1,
        bot_subscribe_retry_cap_seconds=10,
        bot_admin_user_ids=["admin"],
    )
    runtime = build_subscription_runtime_v2(config)
    capability = build_subscribe_capability_v2(
        store=runtime["store"], adapters=runtime["adapters"], config=config
    )
    return runtime, capability


def test_registry_keeps_only_fetchable_platforms() -> None:
    # 注册表不得再包含「注册成功但 fetch 恒 unsupported」的平台（J-06①②）。
    adapter = MUSIC_ADAPTERS[0]
    assert adapter.supported_platforms == frozenset({"netease"})
    for platform in _REMOVED_PLATFORMS:
        assert platform not in adapter.supported_platforms


@pytest.mark.parametrize(
    "raw",
    [
        "https://y.qq.com/n/ryqq/playlist/3D4nABo0BpeQxXKVz2xXxw",
        "https://open.spotify.com/artist/0TnOYIS61iLestQ7pQQKLp",
        "qqmusic:playlist:3D4nABo0BpeQxXKVz2xXxw",
        "spotify:artist:0TnOYIS61iLestQ7pQQKLp",
        "kuwo:playlist:123",
        "kugou:playlist:abc",
        "apple_music:playlist:xyz",
    ],
)
def test_removed_platforms_rejected_with_explicit_notice(raw: str) -> None:
    # 五个摘除平台（链接形态+冒号形态）resolve 一律显式拒绝，提示指名
    # 平台并说明仍可订的网易云（J-06①）。
    with pytest.raises(ValueError) as excinfo:
        asyncio.run(MusicSubscriptionAdapterV2().resolve_target(raw, {}))
    message = str(excinfo.value)
    assert "还没接上" in message
    assert "网易云" in message


def test_subscribe_add_qqmusic_link_gets_notice_not_success(tmp_path) -> None:
    # 端到端（真实生产装配的 /订阅 add 路径）：qqmusic 链接得到「暂不支持」
    # 人话提示，且没有任何订阅落库（旧行为=订阅成功后无声无息）。
    runtime, capability = _runtime(tmp_path)
    reply = capability(
        _message("订阅 add https://y.qq.com/n/ryqq/playlist/3D4nABo0BpeQxXKVz2xXxw"),
        None,
    )
    assert "还没接上" in reply.body
    assert "网易云" in reply.body
    assert reply.audit_tags == ["subscribe_target_invalid"]
    assert runtime["store"].list_targets() == []
    runtime["store"].close()


def test_subscribe_add_netease_still_works(tmp_path) -> None:
    # 摘除不得误伤既有可用面：网易云歌单订阅照常成功落库。
    runtime, capability = _runtime(tmp_path)
    reply = capability(
        _message("订阅 add https://music.163.com/playlist?id=123"), None
    )
    assert "订阅已添加" in reply.body
    assert runtime["store"].get_target("netease:playlist:123") is not None
    runtime["store"].close()
