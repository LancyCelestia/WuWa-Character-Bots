"""构造订阅 V2 后端运行时。"""
from __future__ import annotations

from typing import Any

from plugins.bot_unified_runtime.domains.subscribe.adapters import (
    build_subscription_registry_v2,
)
from plugins.bot_unified_runtime.domains.subscribe.store.subscription_scheduler import (
    PlatformThrottle,
    SubscriptionScheduler,
)
from plugins.bot_unified_runtime.domains.subscribe.store.subscription_store_v2 import (
    SubscriptionStoreV2,
    subscription_platform_enabled,
)


def register_subscription_runtime_v2(
    scheduler: Any,
    config: Any,
    *,
    delivery_fn: Any | None = None,
    context_factory: Any | None = None,
    dead_letter_sink: Any | None = None,
) -> dict[str, Any]:
    runtime = build_subscription_runtime_v2(
        config,
        delivery_fn=delivery_fn,
        context_factory=context_factory,
        # SUB-2 装配链补齐：`29f2cf6` 已把 build/store 两侧备好，就差 register
        # 这一行透传——生产走 register 时 sink 仍会在这里断掉。
        dead_letter_sink=dead_letter_sink,
    )

    async def poll_job() -> None:
        await runtime["scheduler"].poll_due_once()

    async def outbox_job() -> None:
        await runtime["scheduler"].deliver_outbox_once(
            limit=int(getattr(config, "bot_subscribe_max_items_per_tick", 20) or 20)
        )

    scheduler.add_job(
        poll_job,
        "interval",
        seconds=max(1, int(getattr(config, "bot_subscribe_poll_interval_seconds", 300))),
        id="sub_v2_watch",
        coalesce=True,
        max_instances=1,
        replace_existing=True,
    )
    scheduler.add_job(
        outbox_job,
        "interval",
        seconds=max(1, int(getattr(config, "bot_subscribe_outbox_interval_seconds", 15) or 15)),
        id="sub_v2_outbox",
        coalesce=True,
        max_instances=1,
        replace_existing=True,
        misfire_grace_time=30,
    )
    return runtime


def build_subscription_runtime_v2(
    config: Any,
    *,
    delivery_fn: Any | None = None,
    context_factory: Any | None = None,
    dead_letter_sink: Any | None = None,
) -> dict[str, Any]:
    """按配置构造独立 V2 Store、adapter 列表和调度器。"""
    if context_factory is None:
        from plugins.bot_unified_runtime.domains.link_parse.parsers import (
            build_cookie_provider,
        )

        cookie_provider = build_cookie_provider(config)
        proxy = str(getattr(config, "bot_download_proxy", "") or "")
        timeout = float(getattr(config, "bot_fetch_timeout_seconds", 10.0) or 10.0)

        def context_factory(platform: str) -> dict[str, Any]:
            return {
                "cookie_header": cookie_provider.cookie_header(platform),
                "proxy": proxy,
                "timeout_seconds": timeout,
            }

    db_path = str(
        getattr(config, "bot_subscribe_db_path", "data/subscriptions.sqlite3")
        or "data/subscriptions.sqlite3"
    )
    # SUB-1（S-ATK-SUBSCRIBE，2026-09-27）：旧写法裸 SubscriptionStoreV2(db_path)
    # ⇒ ①四枚 bot_subscription_* 键写了也不生效（store 的 config 覆盖腿永空）、
    # ②死信只有一行 WARNING、管理员通道永空。生产 .env 现算零枚这四键 ⇒ 接上
    # config 为行为中性（键值 0/缺省仍回退模块常量）；sink 由装配现场注入，
    # 缺省 None 保持旧降级形态（根接线一行走 root 批）。
    store = SubscriptionStoreV2(db_path, config=config, dead_letter_sink=dead_letter_sink)
    adapters = build_subscription_registry_v2()
    throttle = PlatformThrottle(
        per_platform_limit=int(
            getattr(config, "bot_subscribe_platform_concurrency", 1) or 1
        ),
        global_limit=int(
            getattr(config, "bot_subscribe_global_concurrency", 3) or 3
        ),
        min_interval_seconds=float(
            getattr(config, "bot_subscribe_min_interval_seconds", 1.0) or 0
        ),
    )
    scheduler = SubscriptionScheduler(
        store,
        adapters,
        lease_seconds=int(getattr(config, "bot_subscribe_lease_seconds", 120) or 120),
        retry_base_seconds=int(
            getattr(config, "bot_subscribe_retry_base_seconds", 60) or 60
        ),
        retry_cap_seconds=int(
            getattr(config, "bot_subscribe_retry_cap_seconds", 1800) or 1800
        ),
        throttle=throttle,
        delivery_fn=delivery_fn,
        context_factory=context_factory,
        # 审查 J-02：per-platform 开关注入轮询侧（add 侧在 capability 内
        # 直接调同一 helper）。gate 每轮评估时读 config 属性，但 config
        # 实例进程启动时固定——改键需重启生效，与全库 config 口径一致。
        platform_enabled=lambda platform: subscription_platform_enabled(
            config, platform
        ),
    )
    return {"store": store, "adapters": adapters, "scheduler": scheduler}
