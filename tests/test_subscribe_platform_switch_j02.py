"""审查 J-02：订阅 per-platform 开关（用户「所有子模块可开关」硬要求）。

覆盖四条验收：
①关闭平台 add 显式人话拒绝；②开启平台照常；③默认全开=现状零变化；
④轮询侧跳过（不 claim、不计失败）。add 与轮询共用
subscription_platform_enabled 单点判定，防两处语义漂移。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from plugins.bot_unified_runtime.capabilities.subscribe_v2 import (
    build_subscribe_capability_v2,
)
from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.core.contracts.subscription import (
    SubscriptionFetchResult,
    SubscriptionTarget,
)
from plugins.bot_unified_runtime.domains.subscribe.store.subscription_scheduler import (
    SubscriptionScheduler,
)
from plugins.bot_unified_runtime.domains.subscribe.store.subscription_store_v2 import (
    SubscriptionStoreV2,
    subscription_platform_enabled,
)
from plugins.bot_unified_runtime.sources.subscription_runtime_v2 import (
    build_subscription_runtime_v2,
)

_NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)


def _config(db_path: str, **extra: object) -> SimpleNamespace:
    return SimpleNamespace(
        bot_subscribe_db_path=db_path,
        bot_subscribe_global_concurrency=2,
        bot_subscribe_platform_concurrency=1,
        bot_subscribe_min_interval_seconds=0,
        bot_subscribe_lease_seconds=30,
        bot_subscribe_retry_base_seconds=1,
        bot_subscribe_retry_cap_seconds=10,
        bot_admin_user_ids=["admin"],
        **extra,
    )


def _message(text: str, *, sender_id: str = "admin") -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id=f"private:{sender_id}",
        session_type=SessionType.PRIVATE,
        sender_id=sender_id,
        plain_text=text,
    )


# ---- ① 关闭平台 add 显式拒绝 ----


def test_add_rejected_when_platform_disabled(tmp_path) -> None:
    config = _config(
        str(tmp_path / "subscriptions.sqlite3"),
        bot_subscribe_platform_bilibili=False,
    )
    runtime = build_subscription_runtime_v2(config)
    capability = build_subscribe_capability_v2(
        store=runtime["store"], adapters=runtime["adapters"], config=config
    )

    denied = capability(
        _message("订阅 add https://space.bilibili.com/12345"), None
    )
    assert "该平台订阅暂未开放" in denied.body
    assert "bilibili" in denied.body
    assert "subscribe_platform_disabled" in denied.audit_tags
    # 拒绝不落任何订阅行。
    assert runtime["store"].list_targets() == []
    runtime["store"].close()


def test_add_rejected_for_netease_music_platform(tmp_path) -> None:
    # music adapter 以 provider 名 netease 落 target.platform，键名须对齐。
    config = _config(
        str(tmp_path / "subscriptions.sqlite3"),
        bot_subscribe_platform_netease=False,
    )
    runtime = build_subscription_runtime_v2(config)
    capability = build_subscribe_capability_v2(
        store=runtime["store"], adapters=runtime["adapters"], config=config
    )

    denied = capability(
        _message("订阅 add https://music.163.com/playlist?id=123"), None
    )
    assert "该平台订阅暂未开放" in denied.body
    assert "netease" in denied.body
    assert runtime["store"].list_targets() == []
    runtime["store"].close()


# ---- ② 开启平台照常 ----


def test_add_works_when_platform_explicitly_enabled(tmp_path) -> None:
    config = _config(
        str(tmp_path / "subscriptions.sqlite3"),
        bot_subscribe_platform_bilibili=True,
        bot_subscribe_platform_youtube=True,
    )
    runtime = build_subscription_runtime_v2(config)
    capability = build_subscribe_capability_v2(
        store=runtime["store"], adapters=runtime["adapters"], config=config
    )

    added = capability(
        _message("订阅 add https://www.youtube.com/channel/UC1"), None
    )
    assert "订阅已添加" in added.body
    assert runtime["store"].get_target("youtube:channel:UC1") is not None
    runtime["store"].close()


# ---- ③ 默认全开=现状零变化 ----


def test_default_all_platforms_open_zero_change(tmp_path) -> None:
    # config 不带任何 platform 键（等价旧配置文件）：所有平台照常可订。
    config = _config(str(tmp_path / "subscriptions.sqlite3"))
    runtime = build_subscription_runtime_v2(config)
    capability = build_subscribe_capability_v2(
        store=runtime["store"], adapters=runtime["adapters"], config=config
    )

    for raw in (
        "订阅 add https://space.bilibili.com/1",
        "订阅 add https://www.youtube.com/channel/UC2",
        "订阅 add https://music.163.com/playlist?id=3",
    ):
        assert "订阅已添加" in capability(_message(raw), None).body
    assert len(runtime["store"].list_targets()) == 3
    runtime["store"].close()


def test_helper_defaults_open_for_unknown_and_blank() -> None:
    config = SimpleNamespace(bot_subscribe_platform_bilibili=False)
    # 未登记平台（已摘除的 twitter、未来新平台）一律开放：开关只关闸不扩面。
    assert subscription_platform_enabled(config, "twitter") is True
    # 空平台标识不拦（防御性）。
    assert subscription_platform_enabled(config, "") is True
    assert subscription_platform_enabled(config, None) is True
    # 标识大小写/首尾空白归一。
    assert subscription_platform_enabled(config, " Bilibili ") is False
    # config 完全缺键视为开放。
    assert subscription_platform_enabled(SimpleNamespace(), "bilibili") is True


# ---- ④ 轮询侧跳过 ----


class _CountingAdapter:
    platform = "bilibili"
    target_kinds = frozenset({"up"})

    def __init__(self) -> None:
        self.calls = 0

    async def fetch_incremental(
        self, target: SubscriptionTarget, cursors: dict, context: dict
    ) -> SubscriptionFetchResult:
        self.calls += 1
        return SubscriptionFetchResult(items=[])


def _poll_target(now: datetime, *, target_id: str = "bilibili:up:42") -> SubscriptionTarget:
    return SubscriptionTarget(
        id=target_id,
        platform="bilibili",
        target_kind="up",
        target_key="42",
        baseline_initialized=True,
        base_interval_seconds=300,
        jitter_ratio=0.20,
        next_poll_at=now,
        created_at=now,
        updated_at=now,
    )


def test_poll_skips_disabled_platform_without_claim_or_failure(tmp_path) -> None:
    store = SubscriptionStoreV2(str(tmp_path / "subscriptions.sqlite3"))
    adapter = _CountingAdapter()
    target = _poll_target(_NOW)
    store.upsert_target(target)
    scheduler = SubscriptionScheduler(
        store,
        [adapter],
        random_fn=lambda: 0.5,
        clock=lambda: _NOW,
        platform_enabled=lambda platform: platform != "bilibili",
    )

    events = asyncio.run(scheduler.poll_due_once(now=_NOW))
    assert events == []
    assert adapter.calls == 0
    saved = store.get_target(target.id)
    assert saved is not None
    # 未 claim、未记失败：next_poll_at/健康态原样（重开开关即恢复轮询）。
    assert saved.next_poll_at == _NOW
    assert saved.failure_count == 0
    store.close()


def test_poll_still_runs_for_enabled_platform(tmp_path) -> None:
    store = SubscriptionStoreV2(str(tmp_path / "subscriptions.sqlite3"))
    adapter = _CountingAdapter()
    target = _poll_target(_NOW)
    store.upsert_target(target)
    scheduler = SubscriptionScheduler(
        store,
        [adapter],
        random_fn=lambda: 0.5,
        clock=lambda: _NOW,
        platform_enabled=lambda platform: platform == "bilibili",
    )

    asyncio.run(scheduler.poll_due_once(now=_NOW))
    assert adapter.calls == 1
    store.close()


def test_scheduler_defaults_to_all_open_when_gate_absent(tmp_path) -> None:
    # 不传 platform_enabled（等价未装配开关的调用方）：现状零变化。
    store = SubscriptionStoreV2(str(tmp_path / "subscriptions.sqlite3"))
    adapter = _CountingAdapter()
    target = _poll_target(_NOW)
    store.upsert_target(target)
    scheduler = SubscriptionScheduler(
        store,
        [adapter],
        random_fn=lambda: 0.5,
        clock=lambda: _NOW,
    )

    asyncio.run(scheduler.poll_due_once(now=_NOW))
    assert adapter.calls == 1
    store.close()


def test_runtime_wires_config_gate_end_to_end(tmp_path) -> None:
    # 装配层把 config 的平台开关接进 scheduler：关 bilibili 后轮询跳过，
    # 不 claim 不计失败——与 add 侧同源判定（subscription_platform_enabled）。
    config = _config(
        str(tmp_path / "subscriptions.sqlite3"),
        bot_subscribe_platform_bilibili=False,
    )
    runtime = build_subscription_runtime_v2(config)
    store: SubscriptionStoreV2 = runtime["store"]
    target = _poll_target(_NOW, target_id="bilibili:up:7")
    store.upsert_target(target)

    events = asyncio.run(runtime["scheduler"].poll_due_once(now=_NOW))
    assert events == []
    saved = store.get_target("bilibili:up:7")
    assert saved is not None and saved.failure_count == 0
    assert saved.next_poll_at == _NOW
    store.close()
