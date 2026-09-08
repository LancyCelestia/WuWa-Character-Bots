"""群聊复读检测（批次 C：群公共状态的第一个落地件）。

短时间内多名不同用户发送完全相同（或去标点后相同）的文本 → 判定为复读，
提供一句吐槽回应（如"怎么一个个都当复读机"）。规则极简、零模型调用：
- 窗口内（默认 60s）同群同文本出现 ≥ 阈值（默认 3 个）不同发送者 → 触发一次；
- 每个文本只吐槽一次，冷却期内不重复触发；
- 机器人自己发的消息不参与计数（由调用方过滤）。
"""

from __future__ import annotations

import re
import threading
import time
from collections import deque
from typing import Any

_PUNCT_RE = re.compile(r"[\s，。！？!?.,~～@＠]+$|^[＠@]\S+\s+")


def _normalize(text: str) -> str:
    return _PUNCT_RE.sub("", (text or "").strip())


class ParrotDetector:
    """多人复读检测器；detect() 返回吐槽文本或 None。"""

    def __init__(
        self,
        *,
        window_seconds: float = 60.0,
        threshold: int = 3,
        cooldown_seconds: float = 300.0,
        max_entries: int = 512,
        clock: Any = time.monotonic,
    ) -> None:
        self.window_seconds = max(5.0, float(window_seconds))
        self.threshold = max(2, int(threshold))
        self.cooldown_seconds = max(0.0, float(cooldown_seconds))
        self.max_entries = max(16, int(max_entries))
        self._clock = clock
        self._lock = threading.Lock()
        # (session_id, normalized_text) -> deque[ (monotonic, sender_id) ]
        self._seen: dict[tuple[str, str], deque[tuple[float, str]]] = {}
        # (session_id, normalized_text) -> 上次吐槽时刻
        self._last_teased: dict[tuple[str, str], float] = {}

    def detect(
        self,
        *,
        session_id: str,
        sender_id: str,
        text: str,
        is_bot_self: bool = False,
    ) -> str | None:
        key_text = _normalize(text)
        if is_bot_self or not key_text or len(key_text) > 120:
            return None
        key = (session_id, key_text)
        now = float(self._clock())
        with self._lock:
            last = self._last_teased.get(key)
            if last is not None and now - last < self.cooldown_seconds:
                return None
            bucket = self._seen.setdefault(key, deque())
            bucket.append((now, sender_id))
            while bucket and now - bucket[0][0] > self.window_seconds:
                bucket.popleft()
            senders = {sender for _ts, sender in bucket}
            if len(senders) < self.threshold:
                self._gc(now)
                return None
            self._last_teased[key] = now
            bucket.clear()
            self._gc(now)
            return "怎么一个个都当复读机，我耳朵要起茧了。要不要我说点不一样的？"

    def _gc(self, now: float) -> None:
        # 满量时优先清理早已过期的桶与冷却记录，控制内存。
        if len(self._seen) <= self.max_entries:
            return
        for key in [k for k, bucket in self._seen.items() if not bucket or now - bucket[-1][0] > self.window_seconds * 2]:
            self._seen.pop(key, None)
        for key in [k for k, ts in self._last_teased.items() if now - ts > self.cooldown_seconds * 2]:
            self._last_teased.pop(key, None)
        while len(self._seen) > self.max_entries:
            self._seen.pop(next(iter(self._seen)), None)
