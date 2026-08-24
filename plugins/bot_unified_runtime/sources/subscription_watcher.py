"""订阅 watcher：把 store + 平台 adapters 组合成可调度的轮询函数。

- ``tick()``：逐个启用且可拉取的 spec 调用 fetch_latest，新条目去重后产出
  PushCandidate（digest 订阅改为写入 digest_pending，不产即时候选）。
- ``live_tick()``：按平台对 LIVE_POLL=True 的 adapter 批量调用
  fetch_live_statuses。
- ``flush_digests()``：弹出各 spec 的待发日报并合成 digest_due 候选。
"""
from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from plugins.bot_unified_runtime.contracts.subscription import (
    NormalizedSubscriptionItem,
    PushCandidate,
    SubscriptionSpec,
)

_SKIP_HEALTH_STATES = frozenset({"unsupported", "paused"})


def _backoff_active(backoff_until: str | None, now: float) -> bool:
    """返回 True 表示尚未到可重试时间（仍在退避期内）。"""
    if not backoff_until:
        return False
    try:
        parsed = datetime.fromisoformat(backoff_until)
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp() > now


def build_subscription_watcher(
    store: Any,
    adapters: list[Any],
    ctx_factory: Callable[..., dict[str, Any]],
    max_items_per_tick: int | None = None,
) -> Any:
    by_platform: dict[str, Any] = {}
    for adapter in adapters:
        platform = getattr(adapter, "platform", "")
        if platform and platform not in by_platform:
            by_platform[platform] = adapter

    def _make_ctx(platform: str) -> dict[str, Any]:
        try:
            return ctx_factory(platform)
        except TypeError:
            return ctx_factory()

    def _failure_backoff(spec: SubscriptionSpec) -> int:
        return min(600 * max(0, int(spec.failure_count or 0)), 1800)

    async def tick() -> list[PushCandidate]:
        candidates: list[PushCandidate] = []
        now = time.time()
        limit = (
            max(0, int(max_items_per_tick))
            if max_items_per_tick is not None
            else None
        )
        for spec in store.list_specs():
            if not spec.enabled:
                continue
            if spec.health_state in _SKIP_HEALTH_STATES:
                continue
            if _backoff_active(spec.backoff_until, now):
                continue
            adapter = by_platform.get(spec.platform)
            if adapter is None:
                store.set_spec_health(
                    spec.id, "unsupported", f"no adapter for {spec.platform}"
                )
                continue

            ctx = _make_ctx(spec.platform)
            cursor = store.get_cursor(spec.id)
            try:
                result = await adapter.fetch_latest(spec, cursor, ctx)
            except Exception:  # noqa: BLE001 - 适配器抓取异常按失败退避处理。
                store.record_failure(
                    spec.id, backoff_seconds=_failure_backoff(spec)
                )
                continue
            if result is None or (not result.items and result.error):
                store.record_failure(
                    spec.id, backoff_seconds=_failure_backoff(spec)
                )
                continue

            truncated = False
            produced = 0
            for item in result.items:
                if store.already_pushed(spec.id, item.item_id, item.kind):
                    continue
                if limit is not None and produced >= limit:
                    truncated = True
                    break
                if spec.digest_enabled:
                    store.add_digest_pending(
                        spec.id,
                        item.item_id,
                        item.title,
                        item.url,
                        item.summary,
                    )
                else:
                    candidates.append(
                        PushCandidate(
                            spec_id=spec.id, item=item, reason="new_item"
                        )
                    )
                store.mark_pushed(spec.id, item.item_id, item.kind)
                produced += 1

            if truncated:
                # 有剩余条目未处理时保留旧游标，下一次轮询继续补齐。
                continue

            if result.new_cursor is not None:
                store.save_cursor(result.new_cursor)
            healthy_state = str(result.health_state or "healthy")
            store.set_spec_health(spec.id, healthy_state, "")
            if spec.failure_count or spec.backoff_until:
                store.upsert_spec(
                    spec.model_copy(
                        update={
                            "failure_count": 0,
                            "backoff_until": None,
                            "health_state": healthy_state,
                        }
                    )
                )
        return candidates

    async def live_tick() -> list[PushCandidate]:
        grouped: dict[str, tuple[Any, list[SubscriptionSpec]]] = {}
        for spec in store.list_specs():
            if not spec.enabled:
                continue
            adapter = by_platform.get(spec.platform)
            if adapter is None or not getattr(adapter, "LIVE_POLL", False):
                continue
            fetcher = getattr(adapter, "fetch_live_statuses", None)
            if not callable(fetcher):
                continue
            grouped.setdefault(spec.platform, (adapter, []))[1].append(spec)

        candidates: list[PushCandidate] = []
        for platform, (adapter, specs) in grouped.items():
            ctx = _make_ctx(platform)
            result = await adapter.fetch_live_statuses(specs, ctx)
            if result:
                candidates.extend(result)
        return candidates

    async def flush_digests() -> list[PushCandidate]:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        candidates: list[PushCandidate] = []
        for spec in store.list_specs():
            rows = store.pop_digest_pending(spec.id)
            if not rows:
                continue
            summary = "\n".join(
                f"《{row['title']}》 {row['url']}" for row in rows
            )
            item = NormalizedSubscriptionItem(
                item_id=f"digest-{today}",
                kind="digest",
                title=f"{spec.target_name} 订阅日报",
                summary=summary,
            )
            candidates.append(
                PushCandidate(spec_id=spec.id, item=item, reason="digest_due")
            )
        return candidates

    return SimpleNamespace(tick=tick, live_tick=live_tick, flush_digests=flush_digests)
