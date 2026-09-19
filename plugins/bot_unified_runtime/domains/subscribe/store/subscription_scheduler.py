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

from plugins.bot_unified_runtime.domains.core.contracts.subscription import (
    SubscriptionAdapter,
    SubscriptionFetchResult,
    SubscriptionOutboxEvent,
    SubscriptionTarget,
)
from plugins.bot_unified_runtime.domains.subscribe.store.subscription_store_v2 import (
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
        # 审查 J-02：per-platform 开关（platform → bool）。None=全开放
        # （现状零变化）；装配层传 subscription_platform_enabled 偏函数。
        platform_enabled: Callable[[str], bool] | None = None,
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
        self._platform_enabled = platform_enabled

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
        # P2-1：store 全部经 *_async 门面（asyncio.to_thread）访问，同步
        # SQLite 不再阻塞 event loop；语义与直调同步方法完全一致。
        for target in await self.store.list_targets_async(due_before=current):
            # 审查 J-02：per-platform 开关关闭的平台直接跳过轮询——在
            # claim 之前判定，不占租约、不计失败（已有订阅行保留，
            # 平台重开后下一轮自动恢复轮询）。与 add 侧拒绝共用
            # subscription_platform_enabled 的判定语义。
            if (
                self._platform_enabled is not None
                and not self._platform_enabled(target.platform)
            ):
                continue
            if not await self.store.claim_due_target_async(
                target.id, current, self._lease_seconds
            ):
                continue
            adapter = self._adapters.get(target.platform)
            settled = False
            try:
                if adapter is None:
                    await self.store.record_failure_async(
                        target.id,
                        "unsupported",
                        retry_at=self._retry_at(current, target.failure_count, None),
                    )
                    settled = True
                    continue
                cursors = await self.store.get_cursors_async(target.id)
                # 运行期元数据（如 X rest_id）回灌进 target_payload：adapter
                # 优先读 payload 里的解析产物，重启后无需重新解析。
                metadata = await self.store.get_target_metadata_async(target.id)
                if metadata:
                    target.target_payload = {**target.target_payload, **metadata}
                payload_before = dict(target.target_payload)

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
                    await self.store.record_failure_async(
                        target.id, result.error_code, retry_at=retry_at
                    )
                    settled = True
                    continue
                new_events = await self.store.save_fetch_result_async(
                    target,
                    result,
                    baseline=not target.baseline_initialized,
                )
                # fetch 中 adapter 注入 payload 的显式元数据（键值有变化的子集）
                # 落库，下一轮经 get_target_metadata 回灌（B8）。
                payload_delta = {
                    key: value
                    for key, value in target.target_payload.items()
                    if key not in payload_before or payload_before[key] != value
                }
                if payload_delta:
                    await self.store.set_target_metadata_async(target.id, payload_delta)
                events.extend(new_events)
                next_poll = self.next_poll_at(
                    target, now=current, random_value=self._random()
                )
                await self.store.release_target_async(target.id, next_poll_at=next_poll)
                settled = True
            except Exception:
                # 收窄为 Exception：KeyError/sqlite3.Error/ET.ParseError 等
                # 逃逸异常此前会中断整轮轮询，且租约被过期 next_poll_at 释放
                # 导致退避失效、该目标每周期重复失败。
                _LOGGER.warning("subscription poll failed for %s", target.id, exc_info=True)
                retry_at = self._retry_at(current, target.failure_count, None)
                try:
                    await self.store.record_failure_async(
                        target.id, "network_error", retry_at=retry_at
                    )
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
                        await self.store.release_target_lease_async(target.id)
                    except Exception:
                        _LOGGER.warning(
                            "subscription lease fallback release failed for %s",
                            target.id,
                            exc_info=True,
                        )
        return events

    async def _enabled_destination_keys(self, target_id: str) -> list[str]:
        """事件的当前启用目的地键（subscription_destinations 行 id）。

        仅供 J-04 幂等查重使用；真实投递仍完全由 delivery_fn 决定
        （生产实现在 __init__._deliver_v2_event，自行读取目的地列表）。
        """
        if self.store is None:
            return []
        destinations = await self.store.list_destinations_async(target_id)
        return [d.id for d in destinations if d.enabled and str(d.id)]

    async def deliver_outbox_once(self, *, limit: int = 20) -> int:
        if self.store is None:
            return 0
        events = await self.store.claim_outbox_async(self._clock(), limit)
        if self._delivery_fn is None:
            for event in events:
                await self.store.mark_outbox_retry_async(
                    event.event_id,
                    self._clock() + timedelta(seconds=self._retry_base),
                )
            return 0
        delivered = 0
        settled: set[str] = set()
        try:
            for event in events:
                # 审查 J-04：目的地级幂等——投递前查 (destination, outbox_id)
                # 是否已有成功台账。claim 回收的 sending>300s 陈旧行（进程在
                # 「投递成功之后、标记 sent 之前」崩溃/超时）重投前同样走本
                # 查重，命中即补标记、绝不二次调用 delivery_fn。
                try:
                    destination_keys = await self._enabled_destination_keys(
                        event.target_id
                    )
                    fully_covered = bool(destination_keys) and not (
                        await self.store.outbox_undelivered_destinations_async(
                            event.event_id, destination_keys
                        )
                    )
                except Exception:
                    # 查重链路故障按未覆盖处理（fail-open）：宁可在极端情况
                    # 下退化为旧行为的重复，不可静默丢推送。
                    _LOGGER.warning(
                        "outbox delivery dedup check failed for %s",
                        event.event_id,
                        exc_info=True,
                    )
                    destination_keys = []
                    fully_covered = False
                if fully_covered:
                    _LOGGER.debug(
                        "outbox event %s already delivered to all destinations, marking sent",
                        event.event_id,
                    )
                    await self.store.mark_outbox_sent_async(
                        event.event_id, self._clock()
                    )
                    delivered += 1
                    settled.add(event.event_id)
                    continue
                try:
                    success = await self._delivery_fn(event)
                except Exception:  # noqa: BLE001 - 单事件投递失败转重试，不弃队。
                    success = False
                if success:
                    sent_at = self._clock()
                    if destination_keys:
                        # 审查 J-04：成功台账必须先于 sent 标记落库——两写
                        # 之间崩溃/超时时，sent 未落但台账已落，重启回收重投
                        # 前查重命中，不重复推送。台账写失败只记日志（退化
                        # 为旧的 at-least-once 行为），不回滚已成功的投递。
                        try:
                            await self.store.record_outbox_deliveries_async(
                                event.event_id, destination_keys, sent_at=sent_at
                            )
                        except Exception:  # 台账失败不阻断标记，退化为旧 at-least-once 行为。
                            _LOGGER.warning(
                                "outbox delivery ledger write failed for %s",
                                event.event_id,
                                exc_info=True,
                            )
                    await self.store.mark_outbox_sent_async(event.event_id, sent_at)
                    delivered += 1
                else:
                    await self.store.mark_outbox_retry_async(
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
                    if await self.store.outbox_state_async(event.event_id) != "sending":
                        continue
                    await self.store.mark_outbox_retry_async(
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
