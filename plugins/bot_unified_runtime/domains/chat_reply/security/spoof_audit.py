"""显示伪装消毒的**取证台账**（ANTIATTACK P2-d · 用户需求 17，席位 ATK-P2D，2026-09-29）。

登记件 `attack_surface.find_visual_spoof_controls` 出信号、处置口
`injection.render_safe_display_name` 与本页 `display_guard` 动手，但「动过哪一条」
此前只存在于返回值里，事后无法回答「那段时间谁的名片被洗过」。本件补那一句。

三条硬口径（AGENTS 规则 11 注入处置令的直接应用）：
- **不存原文**：条目只留 `fingerprint`（输入串的 sha256 前 16 位）+ 字节数 + 命中标签
  + 是否改变。原样留存「被消毒的载荷」等于把载荷再播一次，`grep` 一次就二次传播；
- **有界**：环形队列 `maxlen`，热路径 O(1)，内存不涨；运行数据面零写入
  （不落 SQLite、不落 `ChatBot_Runtime/`，规则 2/4），进程内可查、由 `drain()` 取走；
- **观察者可选**：`set_observer()` 让装配点（root / 运维告警）自行接出去，
  本件不主动 import 任何重量级运行时——那样会把这条叶子腿拖进装配环。

判据零副本：本件不认识任何码点，标签全部由调用方（处置口）传入。
"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Final

__all__ = [
    "MAX_ENTRIES",
    "drain",
    "fingerprint",
    "record",
    "reset",
    "set_observer",
    "snapshot",
]

LOGGER = logging.getLogger(__name__)

#: 环形台账容量：够覆盖一次排障窗口（「刚才那条名片是谁洗的」），又不吃内存。
MAX_ENTRIES: Final[int] = 256

_lock = threading.Lock()
_ring: deque[dict[str, object]] = deque(maxlen=MAX_ENTRIES)
_observer: Callable[[Mapping[str, object]], None] | None = None


def fingerprint(text: str) -> str:
    """输入串的 sha256 前 16 位（人读定位用，**不是**载荷本体）。"""
    return hashlib.sha256(str(text or "").encode("utf-8", "surrogatepass")).hexdigest()[:16]


def record(
    *,
    surface: str,
    original: str,
    result: str,
    tags: Sequence[str] = (),
) -> dict[str, object]:
    """记一条「这条串被消毒过」。干净串（未改变且零信号）**不记账**——热路径零成本。

    条目字段固定：`ts_utc` / `surface`（落点标签，调用方给的字符串）/ `tags`
    （处置口传来的判据标签，本件不解释其含义）/ `fingerprint` / `bytes_before`
    / `bytes_after` / `changed`。任何字段都**不含原文片段**。
    """
    raw = str(original or "")
    cleaned = str(result or "")
    tag_tuple = tuple(str(tag) for tag in tags)
    entry: dict[str, object] = {
        "ts_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "surface": str(surface or "unknown"),
        "tags": tag_tuple,
        "fingerprint": fingerprint(raw),
        "bytes_before": len(raw.encode("utf-8", "surrogatepass")),
        "bytes_after": len(cleaned.encode("utf-8", "surrogatepass")),
        "changed": raw != cleaned,
    }
    if not tag_tuple and raw == cleaned:
        return entry  # 未触发信号也未改写 ⇒ 不进环形账（仍返回条目，方便调用方判等）
    with _lock:
        _ring.append(entry)
    observer = _observer
    if observer is not None:
        try:
            observer(entry)
        except Exception:  # 取证接出去坏了也不许拖垮显示面（本件永不抛）
            LOGGER.debug("spoof_audit observer failed (surface=%s)", entry["surface"], exc_info=True)
    return entry


def snapshot() -> tuple[dict[str, object], ...]:
    """当前环形账快照（ newest last）。"""
    with _lock:
        return tuple(dict(item) for item in _ring)


def drain() -> tuple[dict[str, object], ...]:
    """取走并清空（运维/测试用）。"""
    with _lock:
        items = tuple(dict(item) for item in _ring)
        _ring.clear()
    return items


def reset() -> None:
    """清空环形账与观察者（只给测试用；生产不许调）。"""
    global _observer
    with _lock:
        _ring.clear()
        _observer = None


def set_observer(callback: Callable[[Mapping[str, object]], None] | None) -> None:
    """装配点接出处（root / 运维告警）。传 None 取消。本件不自带任何出站通路。"""
    global _observer
    with _lock:
        _observer = callback
