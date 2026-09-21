"""审查 J-01 回归：推特订阅注册面诚实化（范式对齐 J-06 音乐订阅）。

缺陷（A 方审计 J-01）：/订阅 add 推特链接/twitter:xxx 无 X cookie 也照常
落库，但轮询侧 fetch 需要 X 登录凭证（auth_token+ct0），缺凭证恒
auth_required——订阅成功却永远收不到推送、无任何提示。

现行为：无 X cookie 时 add 显式拒绝（守岸人语气提示，含恢复条件），零
落库；恢复条件与注册面登记见 social_v2.TwitterSubscriptionAdapterV2
docstring——给 bot 配置 X cookie（/bot cookie import twitter）即自动恢复，
无需改码。存量推特订阅不删数据，轮询按现状 record_failure 退避。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.capabilities.subscribe_v2 import (
    build_subscribe_capability_v2,
)
from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.core.contracts.subscription import (
    SubscriptionTarget,
)
from plugins.bot_unified_runtime.sources.subscription_runtime_v2 import (
    build_subscription_runtime_v2,
)
from plugins.bot_unified_runtime.sources.subscriptions.social_v2 import (
    ADAPTERS as SOCIAL_ADAPTERS,
)
from plugins.bot_unified_runtime.sources.subscriptions.social_v2 import (
    TwitterSubscriptionAdapterV2,
)

# 与轮询 fetch 门同判据的 X cookie 最小形态（测试用，值为占位非真实凭证）。
_COOKIE_HEADER = "auth_token=test-token; ct0=test-ct0"


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


def _runtime(tmp_path, *, cookies_txt: str | None = None):
    config = SimpleNamespace(
        bot_subscribe_db_path=str(tmp_path / "subscriptions.sqlite3"),
        bot_subscribe_global_concurrency=2,
        bot_subscribe_platform_concurrency=1,
        bot_subscribe_min_interval_seconds=0,
        bot_subscribe_lease_seconds=30,
        bot_subscribe_retry_base_seconds=1,
        bot_subscribe_retry_cap_seconds=10,
        bot_admin_user_ids=["admin"],
        bot_cookies_file="",
    )
    if cookies_txt is not None:
        cookie_file = tmp_path / "cookies.txt"
        cookie_file.write_text(cookies_txt, encoding="utf-8")
        config.bot_cookies_file = str(cookie_file)
    runtime = build_subscription_runtime_v2(config)
    capability = build_subscribe_capability_v2(
        store=runtime["store"], adapters=runtime["adapters"], config=config
    )
    return runtime, capability


def _twitter_cookie_txt() -> str:
    # Netscape 格式（/bot cookie import 同款写入形态）；域名取 twitter 白
    # 名单内的 .x.com，expires=2100 年永不过期。
    return (
        ".x.com\tTRUE\t/\tTRUE\t4102444800\tauth_token\ttest-token\n"
        ".x.com\tTRUE\t/\tTRUE\t4102444800\tct0\ttest-ct0\n"
    )


def test_registry_keeps_twitter_registered_and_last_in_social() -> None:
    # 注册面登记：twitter 仍在 ADAPTERS（识别面保留、提示可达），且在
    # social 段内置于末位——/订阅 add 解析循环以最后一个 adapter 的
    # ValueError 作为用户提示，推特提示必须尽量靠后才不被覆盖。
    # 合成序已改为 [*music, *social]（J-01 接线）：推特专属提示可出面。
    assert SOCIAL_ADAPTERS[-1].platform == "twitter"
    platforms = [adapter.platform for adapter in SOCIAL_ADAPTERS]
    assert len(platforms) == len(set(platforms))
    assert {
        "bilibili",
        "xiaohongshu",
        "youtube",
        "telegram",
        "pixiv",
        "weibo",
    } <= set(platforms)


@pytest.mark.parametrize(
    "raw",
    [
        "https://x.com/alice",
        "https://twitter.com/alice",
        "twitter:creator:alice",
    ],
)
def test_subscribe_add_twitter_never_succeeds_silently(tmp_path, raw: str) -> None:
    # 端到端（真实生产装配 build_subscription_runtime_v2 → /订阅 add）：
    # 无 X cookie 时推特目标一律拒绝（subscribe_target_invalid），且零
    # 落库——旧行为=「订阅已添加」落库后永不推送也无提示（J-01 核心
    # 诚实性缺陷），该不变量与本提示文案解耦，先锁死。
    runtime, capability = _runtime(tmp_path)
    reply = capability(_message(f"订阅 add {raw}"), None)
    assert "订阅已添加" not in reply.body
    assert reply.audit_tags == ["subscribe_target_invalid"]
    assert runtime["store"].list_targets() == []
    runtime["store"].close()


@pytest.mark.parametrize(
    "raw",
    [
        "https://x.com/alice",
        "twitter:creator:alice",
    ],
)
def test_subscribe_add_twitter_explicit_notice_surfacing(tmp_path, raw: str) -> None:
    # 出面锁（域外接线后生效）：拒绝回执必须是推特专属人话提示（指名
    # 推特+cookie 恢复条件），而不是末位平台的泛化「无法识别」。
    runtime, capability = _runtime(tmp_path)
    reply = capability(_message(f"订阅 add {raw}"), None)
    assert "推特" in reply.body
    assert "cookie" in reply.body
    assert "/bot cookie import" in reply.body
    assert "还没接通" in reply.body
    assert "订阅已添加" not in reply.body
    assert reply.audit_tags == ["subscribe_target_invalid"]
    assert runtime["store"].list_targets() == []
    runtime["store"].close()


def test_subscribe_add_twitter_recovers_with_x_cookie(tmp_path) -> None:
    # 恢复条件锁（docstring 承诺的可兑现性）：给 bot 配置 X cookie
    # （cookies.txt 的 twitter 段，与 /bot cookie import 同源同格式）后，
    # 同一条推特链接无需改码即可订阅成功落库。
    runtime, capability = _runtime(tmp_path, cookies_txt=_twitter_cookie_txt())
    reply = capability(_message("订阅 add https://x.com/alice"), None)
    assert "订阅已添加" in reply.body
    target = runtime["store"].get_target("twitter:creator:alice")
    assert target is not None
    assert target.platform == "twitter"
    assert target.target_kind == "creator"
    assert target.target_key == "alice"
    runtime["store"].close()


def test_subscribe_add_other_platforms_unaffected_by_twitter_gate(tmp_path) -> None:
    # 摘除面不得误伤兄弟平台：twitter 移到 ADAPTERS 末位后，其余平台
    # 的链接解析与落库行为零变化（以微博为代表；网易云由 J-06 测试锁定）。
    runtime, capability = _runtime(tmp_path)
    reply = capability(_message("订阅 add https://weibo.com/u/42"), None)
    assert "订阅已添加" in reply.body
    assert runtime["store"].get_target("weibo:creator:42") is not None
    runtime["store"].close()


def test_existing_twitter_record_keeps_recording_failure(tmp_path) -> None:
    # 存量处置锁（J-01③）：库里已存的推特订阅不删数据、不静默成功——
    # 无凭证期间轮询照常 record_failure（health_state=auth_required、
    # failure_count 递增、退避重试），零产出事件。
    runtime, _capability = _runtime(tmp_path)
    now = datetime.now(timezone.utc)
    runtime["store"].upsert_target(SubscriptionTarget(
        id="twitter:creator:legacy",
        platform="twitter",
        target_kind="creator",
        target_key="legacy",
        created_at=now,
        updated_at=now,
    ))
    events = asyncio.run(runtime["scheduler"].poll_due_once())
    assert events == []
    target = runtime["store"].get_target("twitter:creator:legacy")
    assert target is not None, "存量订阅不得被删除"
    assert target.health_state == "auth_required"
    assert target.failure_count == 1
    assert target.next_poll_at is not None, "失败后必须进入退避重试"
    runtime["store"].close()


def test_twitter_adapter_fetch_gate_unchanged_for_direct_targets() -> None:
    # 防御路径现状锁：直构目标（绕过注册面）走 fetch 时仍受 cookie 门
    # 约束返回结构化 auth_required（不静默空结果），与 J-06「直构目标
    # 保留结构化拒绝」同口径。
    now = datetime.now(timezone.utc)
    target = SubscriptionTarget(
        id="twitter:creator:alice",
        platform="twitter",
        target_kind="creator",
        target_key="alice",
        created_at=now,
        updated_at=now,
    )
    result = asyncio.run(
        TwitterSubscriptionAdapterV2().fetch_incremental(target, {}, {})
    )
    assert result.health_state == "auth_required"
    assert result.error_code == "auth_required"
    assert result.retryable is False
