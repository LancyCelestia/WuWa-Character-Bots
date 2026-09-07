from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from plugins.bot_unified_runtime.contracts.subscription import (
    ContentReference,
    SubscriptionFetchResult,
    SubscriptionTarget,
)
from plugins.bot_unified_runtime.sources.subscription_scheduler import (
    PlatformThrottle,
    SubscriptionScheduler,
)
from plugins.bot_unified_runtime.sources.subscription_store_v2 import (
    SubscriptionStoreV2,
)

_NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def _target(*, baseline: bool = False, next_poll_at: datetime = _NOW) -> SubscriptionTarget:
    return SubscriptionTarget(
        id="test:channel:1",
        platform="test",
        target_kind="channel",
        target_key="1",
        baseline_initialized=baseline,
        base_interval_seconds=300,
        jitter_ratio=0.20,
        next_poll_at=next_poll_at,
        created_at=_NOW,
        updated_at=_NOW,
    )


class _Adapter:
    platform = "test"
    target_kinds = frozenset({"channel"})

    def __init__(self) -> None:
        self.calls = 0

    async def fetch_incremental(self, target, cursors, context):
        self.calls += 1
        return SubscriptionFetchResult(
            items=[
                ContentReference(
                    item_id=f"v{self.calls}",
                    item_kind="video",
                    url=f"https://example.test/v{self.calls}",
                )
            ],
        )


class _RateLimitedAdapter(_Adapter):
    async def fetch_incremental(self, target, cursors, context):
        return SubscriptionFetchResult(
            health_state="rate_limited",
            error_code="rate_limited",
            retryable=True,
            retry_after_seconds=900,
        )


def test_next_poll_at_stays_within_target_jitter_window() -> None:
    scheduler = SubscriptionScheduler(store=None, adapters=[])
    early = scheduler.next_poll_at(_target(), now=_NOW, random_value=0.0)
    late = scheduler.next_poll_at(_target(), now=_NOW, random_value=1.0)
    assert _NOW + timedelta(seconds=240) <= early <= _NOW + timedelta(seconds=360)
    assert _NOW + timedelta(seconds=240) <= late <= _NOW + timedelta(seconds=360)
    assert early < late


def test_first_poll_baselines_and_second_poll_emits_new_event(tmp_path) -> None:
    store = SubscriptionStoreV2(str(tmp_path / "subscriptions.sqlite3"))
    adapter = _Adapter()
    target = _target()
    store.upsert_target(target)
    scheduler = SubscriptionScheduler(
        store,
        [adapter],
        random_fn=lambda: 0.5,
        clock=lambda: _NOW,
    )

    assert asyncio.run(scheduler.poll_due_once(now=_NOW)) == []
    baselined = store.get_target(target.id)
    assert baselined is not None and baselined.baseline_initialized is True

    store.upsert_target(baselined.model_copy(update={"next_poll_at": _NOW}))
    events = asyncio.run(scheduler.poll_due_once(now=_NOW))
    assert len(events) == 1
    assert events[0].item.item_id == "v2"


def test_retry_after_takes_precedence_over_exponential_backoff(tmp_path) -> None:
    store = SubscriptionStoreV2(str(tmp_path / "subscriptions.sqlite3"))
    target = _target(baseline=True)
    store.upsert_target(target)
    scheduler = SubscriptionScheduler(
        store,
        [_RateLimitedAdapter()],
        random_fn=lambda: 0.5,
        clock=lambda: _NOW,
    )

    assert asyncio.run(scheduler.poll_due_once(now=_NOW)) == []
    saved = store.get_target(target.id)
    assert saved is not None
    assert saved.backoff_until == _NOW + timedelta(seconds=900)
    assert saved.health_state == "rate_limited"


def test_platform_throttle_limits_same_platform_concurrency() -> None:
    throttle = PlatformThrottle(
        per_platform_limit=1,
        global_limit=2,
        min_interval_seconds=0,
    )
    active = 0
    maximum = 0

    async def operation() -> None:
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0)
        active -= 1

    async def run() -> None:
        await asyncio.gather(
            *(throttle.run("test", operation) for _ in range(5))
        )

    asyncio.run(run())
    assert maximum == 1
