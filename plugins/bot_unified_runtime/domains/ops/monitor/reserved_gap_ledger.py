"""「预留位缺位已向运维露头」的跨进程账本（中央观测层，2026-09-28）。

补的洞：`domains/creation/reserved_health_alert.py` 的一次性门 `_not_configured_fired`
只活在**进程内存**里。它的语义本身没错（「每个进程实例报一次」，文案 09-28 已改准），
错在现网的重启频率：2026-09-28 当天约 10 次重启 ⇒ 同一件「不是故障」的缺位报了约 7 波，
每波 2 个收件人 ×（文本 + 诊断卡）＝4 条，合计约 28 条出站私聊。

为什么把持久化放在这一层而不是 creation 域：
- creation 域按教义是**纯协议壳**（`test_v21_creation_skeleton.py::
  test_reserved_modules_forbidden_imports` 禁 sqlite3/threading/asyncio/open 等），
  它不该自己碰盘；本件与 `result_unknown.ResultUnknownLedger` 同层、同手法，
  「抑制窗 + 台账 TTL」本来就是运维告警层的职责（AGENTS 第四部分「运维告警」行）。
- 也**不**做成 `AdminAlertSuppression` 的跨进程版：全仓 `retryable=False` 有 42 处
  （含 `tts_no_ref_audio`、占卜失败这类真故障），一旦中央按「不可重试」哑掉跨进程
  重报，就会把真告警一起藏起来——该线口径是「陈旧不粘滞、宁可晚到不可静默丢件」。
  所以本账本只由**调用方显式注入**给需要它的那一枚 kind 使用。

失败口径＝**fail-open 偏向多报**：读盘任何异常都当作「没报过」，宁可多敲一次运维，
也绝不因为账本坏了就让缺位永久隐身（同 `flush_not_configured_issue` 的既有纪律）。
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

#: 露头后的静默窗（秒）。现网一天约 10 次重启 ⇒ 同一无配状态一天至多敲一次，
#: 而不是 7 波；超过窗口仍未有人处理，则再敲一次（缺位不许永久隐身）。
DEFAULT_REPORT_TTL_SECONDS = 86400.0

#: 账本里最多留多少枚键，防无上限增长（通道集合反复变动时的兜底）。
_MAX_KEYS = 64


class ReservedGapLedger:
    """线程安全的本地 JSON 露头账本；只记「键 + 时刻」，不记任何正文或凭据。"""

    def __init__(
        self,
        path: str | Path,
        *,
        ttl_seconds: float = DEFAULT_REPORT_TTL_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = Path(path)
        self.ttl_seconds = max(60.0, float(ttl_seconds))
        self._clock = clock
        self._lock = threading.Lock()

    # -- 读 ---------------------------------------------------------------

    def already_reported(self, key: str) -> bool:
        """窗口内是否已成功露过头。读不动盘 ⇒ False（宁可多报，不许静默隐身）。"""
        if not key:
            return False
        reported_at = self._read().get(key)
        if not isinstance(reported_at, (int, float)):
            return False
        return (self._clock() - float(reported_at)) < self.ttl_seconds

    def _read(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, TypeError):
            return {}
        entries = raw.get("entries") if isinstance(raw, dict) else None
        return entries if isinstance(entries, dict) else {}

    # -- 写 ---------------------------------------------------------------

    def mark_reported(self, key: str) -> None:
        """记一次成功露头（原子落盘：临时文件 + replace，避免半截 JSON）。"""
        if not key:
            return
        with self._lock:
            entries = self._read()
            entries[key] = self._clock()
            if len(entries) > _MAX_KEYS:
                # 只保最新的若干枚：旧键掉出窗口本来也等价于过期。
                entries = dict(
                    sorted(entries.items(), key=lambda kv: float(kv[1] or 0.0))[
                        -_MAX_KEYS:
                    ]
                )
            self._write(entries)

    def _write(self, entries: dict[str, Any]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(f"{self.path.name}.tmp-{os.getpid()}")
            tmp.write_text(
                json.dumps({"entries": entries}, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(tmp, self.path)
        except (OSError, TypeError, ValueError):
            return  # 写不动盘 ⇒ 与无账本同形（下轮再报），绝不让告警链冒泡。

    def forget(self, key: str | None = None) -> None:
        """清账（配置补齐后主动撤回沉默，或测试隔离用）。``None``＝整本清空。"""
        with self._lock:
            entries = {} if key is None else {
                k: v for k, v in self._read().items() if k != key
            }
            self._write(entries)


def gap_key(stage: str, kind: str, channels: tuple[str, ...] | list[str]) -> str:
    """账本键：``stage/kind:通道集合``。

    通道集合参与键名 ⇒ 「绘画接上了、语音还空着」这类状态变化会算作新的缺位、
    重新露头（陈旧不粘滞）；全部通道都补齐时调用方不再写键，旧键随窗口自然过期。
    """
    return f"{stage}/{kind}:{','.join(sorted(str(item) for item in channels))}"
