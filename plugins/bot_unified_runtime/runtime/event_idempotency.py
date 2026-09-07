"""入站事件幂等表（交接 P0.4 前半：同事件重复投递去重）。

OneBot/NapCat 断线重连可能重放同一事件；同一 (adapter, bot_id, message_id)
被同一能力处理两次会造成重复回复。本表只做进程内 TTL 去重：
- 键 = adapter | bot_id | message_id（无 message_id 的事件不做去重，避免误伤）；
- 同一键对同一 capability_id 只放行一次；不同能力互不影响（多 matcher 合法共存）；
- TTL 过期与容量上限自动回收；重启后自然失效（跨重启持久化与
  result-unknown 恢复属 P0.4 后半，另行实施）。
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any


def build_event_dedupe_key(message: Any) -> str:
    """构造事件去重键；缺少稳定 message_id 时返回空串（调用方跳过去重）。"""
    message_id = str(getattr(message, "message_id", "") or "").strip()
    if not message_id:
        return ""
    adapter = str(getattr(message, "adapter", "") or "").strip().lower()
    bot_id = str(getattr(message, "bot_id", "") or "").strip()
    return f"{adapter}|{bot_id}|{message_id}"


class EventIdempotencyTable:
    """进程内 TTL 幂等表：claim() 返回 True 表示首次出现（放行处理）。"""

    def __init__(
        self,
        *,
        ttl_seconds: float = 3600.0,
        max_entries: int = 4096,
        clock: Any = time.monotonic,
    ) -> None:
        self.ttl_seconds = max(1.0, float(ttl_seconds))
        self.max_entries = max(1, int(max_entries))
        self._clock = clock
        self._lock = threading.Lock()
        # key -> (capability_id, last_seen_monotonic)
        self._entries: OrderedDict[str, tuple[str, float]] = OrderedDict()

    def claim(self, key: str, *, capability_id: str) -> bool:
        if not key:
            return True
        now = float(self._clock())
        with self._lock:
            self._evict_expired(now)
            previous = self._entries.get(key)
            if previous is not None and previous[0] == capability_id:
                # 重复事件：刷新时间戳并拒绝。
                self._entries.move_to_end(key)
                self._entries[key] = (previous[0], now)
                return False
            self._entries[key] = (capability_id, now)
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
            return True

    def _evict_expired(self, now: float) -> None:
        cutoff = now - self.ttl_seconds
        while self._entries:
            _, (_, seen_at) = next(iter(self._entries.items()))
            if seen_at >= cutoff:
                break
            self._entries.popitem(last=False)

    def __len__(self) -> int:
        with self._lock:
            self._evict_expired(float(self._clock()))
            return len(self._entries)
