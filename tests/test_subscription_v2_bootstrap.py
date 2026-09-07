from __future__ import annotations

from types import SimpleNamespace

from plugins.bot_unified_runtime.sources.subscription_runtime_v2 import (
    register_subscription_runtime_v2,
)


class _Scheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, object]] = []

    def add_job(self, func, trigger, **kwargs):
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})


def test_v2_bootstrap_registers_only_v2_subscription_jobs(tmp_path) -> None:
    scheduler = _Scheduler()
    config = SimpleNamespace(
        bot_subscribe_db_path=str(tmp_path / "subscriptions.sqlite3"),
        bot_subscribe_global_concurrency=2,
        bot_subscribe_platform_concurrency=1,
        bot_subscribe_min_interval_seconds=0,
        bot_subscribe_lease_seconds=30,
        bot_subscribe_retry_base_seconds=1,
        bot_subscribe_retry_cap_seconds=10,
        bot_subscribe_poll_interval_seconds=300,
        bot_subscribe_outbox_interval_seconds=15,
    )

    runtime = register_subscription_runtime_v2(scheduler, config)

    assert {job["id"] for job in scheduler.jobs} == {
        "sub_v2_watch",
        "sub_v2_outbox",
    }
    assert runtime["store"].db_path.endswith("subscriptions.sqlite3")
    runtime["store"].close()
