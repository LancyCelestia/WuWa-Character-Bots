"""V2 subscription scheduling with jitter, throttling and retry state."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any, TypeVar

from plugins.bot_unified_runtime.contracts.subscription import (
    SubscriptionAdapter,
    SubscriptionFetchResult,
    SubscriptionOutboxEvent,
    SubscriptionTarget,
)
from plugins.bot_unified_runtime.sources.subscription_store_v2 import (
    SubscriptionStoreV2,
)

_LOGGER = logging.getLogger(__name__)

T = TypeVar("T")


class PlatformThrottle:
    def __init__(
        self,
        *,
        per_platform_limit: int = 1,
        global_limit: int = 3,
        min_interval_seconds: float = 1.0,
    ) -> None:
        self._global = asyncio.Semaphore(max(1, int(global_limit)))
        self._platform: dict[str, asyncio.Semaphore] = {}
        self._platform_limit = max(1, int(per_platform_limit))
        self._min_interval = max(0.0, float(min_interval_seconds))
        self._last_request: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def run(self, platform: str, operation: Callable[[], Awaitable[T]]) -> T:
        name = str(platform or "unknown")
        async with self._global:
            async with self._lock:
                semaphore = self._platform.setdefault(
                    name, asyncio.Semaphore(self._platform_limit)
                )
            async with semaphore:
                # 等最小间隔时不得持全局锁：否则所有平台被串行化，
                # global_limit 并发形同虚设。锁内只读状态/占位，锁外 sleep。
                while True:
                    async with self._lock:
                        elapsed = time.monotonic() - self._last_request.get(name, 0.0)
                        wait_for = max(0.0, self._min_interval - elapsed)
                        if not wait_for:
                            self._last_request[name] = time.monotonic()
                            break
                    await asyncio.sleep(wait_for)
                return await operation()


class SubscriptionScheduler:
    def __init__(
        self,
        store: SubscriptionStoreV2 | None,
        adapters: list[SubscriptionAdapter],
        *,
        random_fn: Callable[[], float] | None = None,
        clock: Callable[[], datetime] | None = None,
        lease_seconds: int = 120,
        retry_base_seconds: int = 60,
        retry_cap_seconds: int = 1800,
        throttle: PlatformThrottle | None = None,
        delivery_fn: Callable[[SubscriptionOutboxEvent], Awaitable[bool]] | None = None,
        context_factory: Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        self.store = store
        self._adapters: dict[str, SubscriptionAdapter] = {}
        for adapter in adapters:
            platform = str(getattr(adapter, "platform", ""))
            self._adapters[platform] = adapter
            for alias in getattr(adapter, "supported_platforms", ()):
                self._adapters[str(alias)] = adapter
        self._random = random_fn or random.random
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lease_seconds = max(1, int(lease_seconds))
        self._retry_base = max(1, int(retry_base_seconds))
        self._retry_cap = max(self._retry_base, int(retry_cap_seconds))
        self._throttle = throttle or PlatformThrottle()
        self._delivery_fn = delivery_fn
        self._context_factory = context_factory or (lambda _platform: {})

    def next_poll_at(
        self,
        target: SubscriptionTarget,
        *,
        now: datetime,
        random_value: float,
    ) -> datetime:
        interval = max(1, int(target.base_interval_seconds))
        ratio = min(1.0, max(0.0, float(target.jitter_ratio)))
        digest = hashlib.blake2b(target.id.encode("utf-8"), digest_size=8).digest()
        stable_phase = int.from_bytes(digest, "big") % interval
        cycle_jitter = (min(1.0, max(0.0, random_value)) * 2.0 - 1.0) * interval * ratio
        delay = max(1.0, interval + cycle_jitter)
        # Keep the phase as a deterministic sub-second tie-breaker so the
        # configured jitter window remains mathematically bounded.
        phase_nudge = stable_phase / max(interval, 1) / 1000.0
        delay = max(1.0, delay + phase_nudge)
        lower = max(1.0, interval * (1.0 - ratio))
        upper = max(lower, interval * (1.0 + ratio))
        delay = min(upper, max(lower, delay))
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc) + timedelta(seconds=delay)

    def _retry_at(self, now: datetime, failure_count: int, retry_after: int | None) -> datetime:
        if retry_after is not None:
            return now + timedelta(seconds=max(1, int(retry_after)))
        ceiling = min(self._retry_cap, self._retry_base * (2 ** max(0, failure_count)))
        jitter = self._random() * ceiling
        return now + timedelta(seconds=max(1, int(jitter)))

    async def poll_due_once(self, *, now: datetime | None = None) -> list[SubscriptionOutboxEvent]:
        if self.store is None:
            return []
        current = now or self._clock()
        events: list[SubscriptionOutboxEvent] = []
        for target in self.store.list_targets(due_before=current):
            if not self.store.claim_due_target(target.id, current, self._lease_seconds):
                continue
            adapter = self._adapters.get(target.platform)
            settled = False
            try:
                if adapter is None:
                    self.store.record_failure(target.id, "unsupported", retry_at=self._retry_at(current, target.failure_count, None))
                    settled = True
                    continue
                cursors = self.store.get_cursors(target.id)
                async def fetch(
                    selected_adapter: SubscriptionAdapter = adapter,
                    selected_target: SubscriptionTarget = target,
                    selected_cursors: dict[str, Any] = cursors,
                ) -> SubscriptionFetchResult:
                    context = dict(
                        self._context_factory(selected_target.platform) or {}
                    )
                    context["now"] = current
                    return await selected_adapter.fetch_incremental(
                        selected_target, selected_cursors, context
                    )

                result: SubscriptionFetchResult = await self._throttle.run(
                    target.platform, fetch
                )
                if result.error_code:
                    retry_at = self._retry_at(current, target.failure_count, result.retry_after_seconds)
                    self.store.record_failure(target.id, result.error_code, retry_at=retry_at)
                    settled = True
                    continue
                new_events = self.store.save_fetch_result(
                    target,
                    result,
                    baseline=not target.baseline_initialized,
                )
                events.extend(new_events)
                next_poll = self.next_poll_at(
                    target, now=current, random_value=self._random()
                )
                self.store.release_target(target.id, next_poll_at=next_poll)
                settled = True
            except Exception:
                # 收窄为 Exception：KeyError/sqlite3.Error/ET.ParseError 等
                # 逃逸异常此前会中断整轮轮询，且租约被过期 next_poll_at 释放
                # 导致退避失效、该目标每周期重复失败。
                _LOGGER.warning("subscription poll failed for %s", target.id, exc_info=True)
                retry_at = self._retry_at(current, target.failure_count, None)
                try:
                    self.store.record_failure(target.id, "network_error", retry_at=retry_at)
                    settled = True
                except Exception:
                    _LOGGER.warning(
                        "subscription failure accounting failed for %s",
                        target.id,
                        exc_info=True,
                    )
            finally:
                if not settled:
                    # 兜底：record_failure/release 正常路径都未走到（如记账分支
                    # 自身再抛异常）时只释放租约，不回写 next_poll_at——回写过
                    # 期的 next_poll_at 会让退避失效并立即重轮询同一目标。
                    try:
                        self.store.release_target_lease(target.id)
                    except Exception:
                        _LOGGER.warning(
                            "subscription lease fallback release failed for %s",
                            target.id,
                            exc_info=True,
                        )
        return events

    async def deliver_outbox_once(self, *, limit: int = 20) -> int:
        if self.store is None:
            return 0
        events = self.store.claim_outbox(self._clock(), limit)
        if self._delivery_fn is None:
            for event in events:
                self.store.mark_outbox_retry(
                    event.event_id,
                    self._clock() + timedelta(seconds=self._retry_base),
                )
            return 0
        delivered = 0
        settled: set[str] = set()
        try:
            for event in events:
                try:
                    success = await self._delivery_fn(event)
                except Exception:  # noqa: BLE001 - 单事件投递失败转重试，不弃队。
                    success = False
                if success:
                    self.store.mark_outbox_sent(event.event_id, self._clock())
                    delivered += 1
                else:
                    self.store.mark_outbox_retry(
                        event.event_id,
                        self._clock() + timedelta(seconds=self._retry_base),
                    )
                settled.add(event.event_id)
        finally:
            # 兜底：mark_* 自身抛异常或任务被取消时，已 claim 但仍滞留
            # state='sending' 的事件必须落回 retry，否则 claim 只捞
            # pending/retry，推送会静默丢失且重启不自愈。
            for event in events:
                if event.event_id in settled:
                    continue
                try:
                    if self.store.outbox_state(event.event_id) != "sending":
                        continue
                    self.store.mark_outbox_retry(
                        event.event_id,
                        self._clock() + timedelta(seconds=self._retry_base),
                    )
                except Exception:
                    _LOGGER.warning(
                        "outbox fallback retry failed for %s",
                        event.event_id,
                        exc_info=True,
                    )
        return delivered
