from __future__ import annotations

from types import SimpleNamespace

from plugins.bot_unified_runtime.sources.subscription_runtime_v2 import (
    build_subscription_runtime_v2,
)


def test_subscription_runtime_v2_constructs_new_store_and_adapters(tmp_path) -> None:
    config = SimpleNamespace(
        bot_subscribe_db_path=str(tmp_path / "subscriptions.sqlite3"),
        bot_subscribe_global_concurrency=2,
        bot_subscribe_platform_concurrency=1,
        bot_subscribe_min_interval_seconds=0,
        bot_subscribe_lease_seconds=30,
        bot_subscribe_retry_base_seconds=1,
        bot_subscribe_retry_cap_seconds=10,
    )
    runtime = build_subscription_runtime_v2(config)
    assert runtime["store"].db_path.endswith("subscriptions.sqlite3")
    assert {adapter.platform for adapter in runtime["adapters"]} >= {
        "bilibili",
        "xiaohongshu",
        "youtube",
        "twitter",
        "telegram",
        "pixiv",
        "weibo",
    }
    assert runtime["scheduler"].store is runtime["store"]
    runtime["store"].close()
