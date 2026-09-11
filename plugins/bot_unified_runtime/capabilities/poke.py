"""Low-noise OneBot poke reactions; independent implementation."""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# 戳一戳冷却登记 LRU 上限：防群/会话数增长导致 _last 慢泄漏（审计 #30）。
_POKE_LAST_CAP = 4096


@dataclass
class PokeLimiter:
    clock: Callable[[], float]
    _last: OrderedDict[tuple[str, str], float] = field(default_factory=OrderedDict)
    def accept(self, event: Any, bot_id: str, enabled: bool, cooldown: float, group_cooldown: float, probability: float = 1.0) -> bool:
        if not enabled or str(getattr(event, "target_id", "")) != str(bot_id): return False
        import hashlib
        group = str(getattr(event, "group_id", "") or "private")
        sender = str(getattr(event, "user_id", "") or "unknown")
        now = self.clock()
        if now - self._last.get((group, sender), -1e9) < max(0.0, cooldown): return False
        if now - self._last.get((group, "*"), -1e9) < max(0.0, group_cooldown): return False
        if probability < 1.0:
            digest = int(hashlib.sha256(f"{group}:{sender}:{int(now // max(1.0, group_cooldown))}".encode()).hexdigest()[:8],16) / 0xFFFFFFFF
            if digest > probability: return False
        for key in ((group, sender), (group, "*")):
            self._last[key] = now
            self._last.move_to_end(key)
        while len(self._last) > _POKE_LAST_CAP:
            self._last.popitem(last=False)
        return True

def build_poke_text(*, group: bool, nickname: str = "") -> str:
    if group:
        return f"{nickname}，我收到你的轻轻一碰了。岸边的潮声还在，不必一直戳我。"
    return "我收到你的轻轻一碰了。嗯，我在这里。"
