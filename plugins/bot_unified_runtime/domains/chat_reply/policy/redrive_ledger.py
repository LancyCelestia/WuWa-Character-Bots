"""补回排队账本——同人同轮被拦的多条消息不得约在同一刻醒来互撞。

背景（2026-09-25 用户裁定第 2 项，复现全在
`tests/test_policy_queue_not_drop.py` 头注）：同人连发 5 条 @bot，45 秒点名
间隔会拦下后 4 条；不排队时它们的补回位全落在同一解禁瞬间——头一条通过时把
冷却钟重新拨走，其余在同一瞬间**全部再被拦**，而补回额度（`max_attempts=1`）
恰好用光 ⇒ 依旧静默丢弃。本账本把"谁已经排了补回"告诉判定侧：新的排队位
一律排到"上一条已排队回位 + 一个最小间隔"之后。

三个访问点（全带锁：pipeline 在线程池与事件循环上并发调用 check_and_record）：

- **写**在 `check_and_record` 的 `sender_min_interval` 拒绝分支
  （`rate_limit.py` 的两个后端共用同一本账；键形与冷却桶键同源）；
- **读**在 `redrive_wait_seconds`——仍只判不排程（排程归 pipeline），
  按 `decision.debug_id` 精确匹配，别人造的决定永远读不到账本值；
- **消耗**在带 `redrive_count≥1` 的消息通过间隔门那一刻：弹出最早成熟的
  预留并把它的回位时刻交还调用方拨冷却钟（迟到补回不起幽灵槽——
  `test_stale_slot_never_inflates_a_later_question` 锁死"占完即销"）。

内存有界：过期条目（回位+间隔已落墙钟之后）随写路径清除；跨 600 秒做一次
全量清扫；键数硬顶，洪泛发送者不能把账本撑大。账本是**进程寿命**的——补回
任务本身就是 asyncio 任务、随进程死亡，跨重启不需要（也没法）持久化。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

# 单键最多记多少条预留：排队深度超过 16 的同人连发已远超"补得起"的
# max_wait 面（45s 间隔 × 16 = 12 分钟），旧的自然丢，只保最新。
_MAX_ENTRIES_PER_KEY = 16
# 键数硬顶：发送者洪泛下的兜底 eviction（见 reserve_slot 内注释）。
_MAX_KEYS = 4096
# 全量清扫间隔（秒）：只被写路径驱动；长期无写的键由写路径过期过滤兜住。
_SWEEP_INTERVAL_SECONDS = 600.0


@dataclass(frozen=True)
class SlotReservation:
    """一条已排队的补回预留。"""

    debug_id: str      # 产生这条记录的拒绝 decision.debug_id（读侧精确匹配）
    slot: float        # 回位时刻（墙钟 epoch 秒）
    wait: float        # 报给调用方的等待秒数（已含排队偏移）
    interval: float    # 排队写入时的最小间隔（队列步进与新鲜度边界同一个量）
    base_wait: float   # 判定侧报的原始剩余秒数（未含排队偏移，留作审计）
    created_at: float  # 入队时刻（epoch 秒，与 slot 同钟）


_lock = threading.Lock()
_entries: dict[str, list[SlotReservation]] = {}
_last_sweep = time.monotonic()


def reset_redrive_ledger() -> None:
    """清空账本（用例边界专用；生产不调用）。"""
    global _last_sweep
    with _lock:
        _entries.clear()
        _last_sweep = time.monotonic()


def _fresh(entries: list[SlotReservation], now: float) -> list[SlotReservation]:
    """保留仍可能影响未来判定的条目：回位+间隔还没彻底过去的。"""
    return [entry for entry in entries if entry.slot + entry.interval > now]


def _sweep_locked(now: float) -> None:
    """全量清扫（低频、写路径顺带）：过期条目与过期键一起扔。"""
    for key in list(_entries.keys()):
        kept = _fresh(_entries.get(key, []), now)
        if kept:
            _entries[key] = kept
        else:
            _entries.pop(key, None)


def reserve_slot(
    key: str,
    *,
    debug_id: str,
    now: float,
    base_wait: float,
    interval_seconds: float,
) -> None:
    """为这次拒绝排一个补回位，排在上一条新鲜预留的回位 + 一个最小间隔之后。

    排队用 wait 累计（不是 slot 平移）：两条被拦消息的到达本身差零点几秒，
    slot 平移会把这点让位吃进间隔里（`waits[1]-waits[0]` 就短于一个间隔，
    后一条睡醒照样撞前一条拨走的冷却钟）——按 wait 累计保证**回位之间的
    实际间距 ≥ 一个完整间隔再多加到达差**，宁远勿撞。
    """
    global _last_sweep
    interval = max(0.0, float(interval_seconds))
    with _lock:
        if time.monotonic() - _last_sweep >= _SWEEP_INTERVAL_SECONDS:
            _last_sweep = time.monotonic()
            _sweep_locked(now)
        entries = _fresh(_entries.get(key, []), now)
        previous = entries[-1] if entries else None
        wait = max(float(base_wait), 1.0)
        if previous is not None:
            wait = max(wait, previous.wait + interval)
        entries.append(
            SlotReservation(
                debug_id=debug_id,
                slot=float(now) + wait,
                wait=wait,
                interval=interval,
                base_wait=float(base_wait),
                created_at=float(now),
            )
        )
        if len(entries) > _MAX_ENTRIES_PER_KEY:
            entries = entries[-_MAX_ENTRIES_PER_KEY:]
        if key not in _entries and len(_entries) >= _MAX_KEYS:
            # 键数触顶：踢掉"最早一条预留最陈旧"的键——牺牲长期无流量的
            # 排队偏移，保住当前活跃发送者的互撞防护（洪泛攻击面兜底）。
            oldest_key = min(
                _entries,
                key=lambda item: _entries[item][0].created_at if _entries[item] else 0.0,
            )
            _entries.pop(oldest_key, None)
        _entries[key] = entries


def reserved_wait_for(key: str, *, debug_id: str) -> float | None:
    """查这次拒绝（按 debug_id 认领）排队后排了几秒；查不到返回 None。

    只读——不动账、不判过期（过期条目由写路径负责清）；是否补、补多久
    的 max_wait 门在调用方（`redrive_wait_seconds`）。
    """
    with _lock:
        for entry in reversed(_entries.get(key, [])):
            if entry.debug_id == debug_id:
                return entry.wait
    return None


def consume_earliest_matured(key: str, *, now: float) -> float | None:
    """补回到访放行时消耗一条预留：弹出最早成熟的条目，回其回位时刻。

    "成熟"= slot ≤ now + interval ——允许比账本回位**早**至多一个间隔
    （浮点/取整会让 pipeline 的睡眠比报值差之毫厘），再晚的属队列后排、
    不许误占。返回的 slot 可能 > now（test_stale 的提前醒来）：调用方要
    把冷却钟拨到 max(now, slot)，"占坑即销"一步完成。
    """
    with _lock:
        entries = _entries.get(key)
        if not entries:
            return None
        for index, entry in enumerate(entries):
            if entry.slot <= now + entry.interval:
                entries.pop(index)
                if not entries:
                    _entries.pop(key, None)
                return entry.slot
    return None
