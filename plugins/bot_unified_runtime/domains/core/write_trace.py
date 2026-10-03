"""写路径留痕（2026-10-02 席 D2）：回答「这条写腿到底被调用过没有、成了没有」。

病根（用户报「数据库也没有更新」时的现算困境）：三枚库（``control_plane_config`` /
``reply_policy`` / ``persona_quirks``）的**盘上主文件 mtime 根本不是「有人拨过开关」的证据**：

* WAL 库的提交先落 ``-wal`` 伴生件，主文件只在 checkpoint 时才动。生产实测
  ``reply_policy.sqlite3`` 主文件停在 10-01 01:18，而 ``-wal`` 停在 10-01 18:22、表里
  ``max(updated_at)='2026-10-01T10:22:02+00:00'``（UTC＝18:22 本地，17:50 那次重启之后）：
  写一直在发生，只读 mtime 的人判成停更。``persona_quirks`` 同形（主文件 01:18、``-wal``
  与 ``max(created_at)`` 都在 10-02 00:43）。
* 覆盖册是 ``journal_mode=delete``（主文件 mtime 会随任何一笔提交而动），但它**同库还住着
  别人的账**：``safetyexec_consent`` / ``safetyexec_change_audit``（同意门与变更账，
  ``consent.py`` 就在这枚文件上建表并 UPDATE 状态），``config_instances`` 的封口写也算一笔
  ——现算复跑（仓外副本）：``import_legacy`` 无可导入键时**动了 mtime、审计行 0 条**，
  而真写一笔 ``set_override`` 才既动 mtime 又出 ``config_audit`` 行。
  ⇒ 「主文件 mtime 停在 10-01 01:38」既不能证明拨过开关，也不能证明没拨过，
  **唯一的账是 ``config_audit``**（它最后一行是 09-27 的 v14）。

第三件事才是本案唯一真正的「该写没写」：``reply_policy.person_imagery_usage`` 生产表形状是
旧的 ``(person_key, family, used_at)``，代码写的是 ``(person_key, families, updated_at)``
（``CREATE TABLE IF NOT EXISTS`` 对已存在的表一枚列都不动）⇒ 两条腿每次 ``OperationalError``
都被 fail-open 吞掉，盘上 0 行、日志零痕 ⇒「该写没写」和「没东西可写」长得一模一样。

家规：

1. **只记读数，不改行为**。留痕不许把 fail-open 换成阻断——写失败照旧返回「本轮没写成」，
   只是必须留下 ``failed`` 那一格；异常照旧原样抛（调用方语义逐字节不变），只是抛之前先记账。
2. **一次逻辑调用一条痕**，记在公开写口的边界上，不在内部辅助函数里重复计（否则一本账两个数）。
3. **detail 只准放短标签**（错误类型名、形状名、计数），绝不放用户正文、路径、密钥——
   本读数会被运维面与测试读走，泄漏面按 AGENTS 规则 3 收口。
4. ``record`` **永不抛**：留痕自身坏了不许把写路径带走（那才是真的阻断聊天）。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

#: 四种结局，全集封闭（新增一档要同批改 ``tests/test_store_write_trace_d2.py`` 的静态门）。
OUTCOME_OK: Final[str] = "ok"            # 真的落库了
OUTCOME_NOOP: Final[str] = "noop"        # 调用发生了，但按语义什么都不该写（去重命中/本来没有这行）
OUTCOME_REFUSED: Final[str] = "refused"  # 被门/白名单/冻结键拒了，一笔都没落
OUTCOME_FAILED: Final[str] = "failed"    # 存储层炸了（异常被吞或被重抛都算这一档）
OUTCOMES: Final[frozenset[str]] = frozenset(
    {OUTCOME_OK, OUTCOME_NOOP, OUTCOME_REFUSED, OUTCOME_FAILED}
)

_DETAIL_MAX_CHARS: Final[int] = 120
_TRACE_DEFAULT_CAPACITY: Final[int] = 64


def _utc_stamp(moment: datetime | None = None) -> str:
    """留痕时刻一律带偏移（台账 #6★：UTC 混用是老坑，裸串不许进账）。"""
    current = moment or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat(timespec="seconds")


def _safe_detail(value: object) -> str:
    """短标签消毒：折行、限长；认不出的形态一律空串（宁可不记，不可泄漏）。"""
    if value is None:
        return ""
    text = " ".join(str(value).split())
    return text[:_DETAIL_MAX_CHARS]


@dataclass(frozen=True)
class WriteTraceEntry:
    """一次写路径调用的读数（不含任何正文，只有 store/op/结局/短标签/时刻）。"""

    store: str
    op: str
    outcome: str
    detail: str
    at: str

    def as_dict(self) -> dict[str, str]:
        return {
            "store": self.store,
            "op": self.op,
            "outcome": self.outcome,
            "detail": self.detail,
            "at": self.at,
        }


class WriteTrace:
    """进程内环形账：每枚 store 一份，运维面与测试读它，盘上真身仍由 DB 自己扛。

    为什么是环形而不是全量：本账的用途是「刚才那次调用有没有落痕」，不是历史审计库；
    历史审计各有正身（覆盖册住 ``config_audit``、策略与怪癖住各自的行）。上限按
    现算取「一次会话轮里最多几条写」的十倍以上：策略 2 条 + 意象账 1 条 + 怪癖 1 条
    一轮最多 4 条，64 格够回溯十几轮，且每条约 200 字节 ⇒ 单账本 ≤ 16KB，无界风险为零。
    """

    def __init__(
        self,
        store: str,
        *,
        capacity: int = _TRACE_DEFAULT_CAPACITY,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = _safe_detail(store) or "unnamed"
        self._capacity = max(8, int(capacity))
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()
        self._entries: list[WriteTraceEntry] = []
        self._totals: dict[str, int] = {outcome: 0 for outcome in OUTCOMES}
        self._ops: dict[str, dict[str, int]] = {}

    def record(self, op: str, outcome: str, detail: object = "") -> WriteTraceEntry:
        """记一笔；``outcome`` 不在册时折算成 ``failed``（记错档也是账目缺陷，不许静默吞）。"""
        safe_outcome = outcome if outcome in OUTCOMES else OUTCOME_FAILED
        entry = WriteTraceEntry(
            store=self.store,
            op=_safe_detail(op) or "unknown",
            outcome=safe_outcome,
            detail=_safe_detail(detail),
            at=_utc_stamp(self._clock()),
        )
        try:
            with self._lock:
                self._entries.append(entry)
                if len(self._entries) > self._capacity:
                    del self._entries[: len(self._entries) - self._capacity]
                self._totals[safe_outcome] += 1
                per_op = self._ops.setdefault(entry.op, {outcome_name: 0 for outcome_name in OUTCOMES})
                per_op[safe_outcome] += 1
        except Exception:  # noqa: BLE001,S110 - fail-open（家规 4）：留痕自身坏了绝不许把写路径带走；刻意吞异常且不加日志，record 返回值与调用方语义逐字节不变
            pass
        return entry

    # ---- 读数 ----

    def counts(self) -> dict[str, int]:
        """按结局的累计计数（含 ``total``）；这是「写路径被调用过没有」的第一读数。"""
        with self._lock:
            snapshot = dict(self._totals)
        snapshot["total"] = sum(snapshot.values())
        return snapshot

    def by_op(self) -> dict[str, dict[str, int]]:
        with self._lock:
            return {op: dict(counts) for op, counts in self._ops.items()}

    def entries(self, *, last: int | None = None) -> tuple[WriteTraceEntry, ...]:
        with self._lock:
            items = tuple(self._entries)
        return items[-last:] if last and last > 0 else items

    def last(self, op: str = "") -> WriteTraceEntry | None:
        """最近一笔（``op`` 给定时只看那一腿）；从没调用过 ⇒ None＝诚实缺席。"""
        wanted = _safe_detail(op)
        for entry in reversed(self.entries()):
            if not wanted or entry.op == wanted:
                return entry
        return None

    def snapshot(self, *, last: int = 5) -> dict[str, Any]:
        """一屏可读的现算读数（运维/工单/测试都取这一个形状，避免第二本账各写各的）。"""
        return {
            "store": self.store,
            "counts": self.counts(),
            "by_op": self.by_op(),
            "recent": [entry.as_dict() for entry in self.entries(last=last)],
        }


def disk_write_state(path: str | Path) -> dict[str, Any]:
    """**纯 stat** 的盘上读数：主文件 mtime 与 WAL 伴生件谁更新，据此判「停更」是不是假象。

    刻意不开 SQLite 连接：以 ``mode=ro`` 打开 WAL 库会触发 wal-index 重建、可能落 ``-shm``
    ⇒ 排查动作本身变成对生产数据根的写入。这里只看文件时间与大小，零副作用。
    """
    target = Path(path)
    result: dict[str, Any] = {
        "path_name": target.name,
        "present": False,
        "main_mtime": "",
        "main_bytes": 0,
        "wal_present": False,
        "wal_mtime": "",
        "wal_bytes": 0,
        "shm_present": False,
        "verdict": "absent",
    }
    try:
        main_stat = target.stat()
    except OSError:
        return result
    result["present"] = True
    result["main_bytes"] = int(main_stat.st_size)
    result["main_mtime"] = _utc_stamp(datetime.fromtimestamp(main_stat.st_mtime, tz=timezone.utc))
    wal = target.with_name(target.name + "-wal")
    shm = target.with_name(target.name + "-shm")
    wal_stat = None
    try:
        wal_stat = wal.stat()
        result["wal_present"] = True
        result["wal_bytes"] = int(wal_stat.st_size)
        result["wal_mtime"] = _utc_stamp(
            datetime.fromtimestamp(wal_stat.st_mtime, tz=timezone.utc)
        )
    except OSError:
        pass
    try:
        result["shm_present"] = shm.exists()
    except OSError:
        result["shm_present"] = False
    if not result["wal_present"]:
        # 无伴生件＝要么回滚日志库（主文件 mtime 就是提交时刻，但仍会被"只构造不写"
        # 的启动事务摸新），要么 WAL 已被 checkpoint 且连接已干净关闭。两种都不能单看 mtime。
        result["verdict"] = "no_sidecar_mtime_ambiguous"
    elif wal_stat is not None and wal_stat.st_mtime > main_stat.st_mtime:
        result["verdict"] = "wal_ahead_main_mtime_is_not_staleness"
    elif result["wal_bytes"] == 0:
        result["verdict"] = "wal_empty_checkpointed"
    else:
        result["verdict"] = "wal_present_not_ahead"
    return result


__all__ = [
    "OUTCOMES",
    "OUTCOME_FAILED",
    "OUTCOME_NOOP",
    "OUTCOME_OK",
    "OUTCOME_REFUSED",
    "WriteTrace",
    "WriteTraceEntry",
    "disk_write_state",
]
