"""DecisionTrace（B2 阶段 0）：决策全程可解释的记录载体与落点。

规格：docs/design/central-decision-engine.md §2.3.2——决策链每一环落一行
stage 记录（stage/kind/allowed/reason/ms）。存储形态（SQLite 独立表 vs 并入
RuntimeDiagnostic）属规格开放问题 Q5，本阶段不做形态裁决，但按审查 P-03
补上最小消费者：影子分歧在进程内有界 deque（热缓冲）之外，异步落一份到
``runtime_data_dir()/decision_trace.sqlite3``（本模块为新文件属主；建表
幂等；容量上限裁剪），供 ``/bot decision`` 管理员查询跨重启读取。
"""

from __future__ import annotations

import json
import logging
import queue
import sqlite3
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

# 审查 P-03：落盘库文件名（属主=decision.trace 模块；db-owners 台账登记
# 由批次收尾统一处理）。放 runtime_data_dir 而非源码树 data/，与全项目
# 「运行数据不进源码树」口径一致。
DEFAULT_TRACE_DB_FILENAME = "decision_trace.sqlite3"

# 落盘容量上限（行）：影子诊断是小行宽结构数据，5 万行≈几十 MB 量级；
# 超上限按 id 裁剪最旧行（SQLite 只增会无界膨胀，长驻进程必须有界）。
MAX_PERSISTED_ROWS = 50_000


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_trace_id() -> str:
    return f"dt_{uuid.uuid4().hex[:12]}"


@dataclass(frozen=True)
class DecisionStageRow:
    """决策链单环记录（规格 §2.3.2：stage/kind/allowed/reason/ms）。

    ``allowed=None`` 表示影子模式下该环不实际裁决（如幂等/门禁），移交
    现行 RuntimePipeline 判定；``kind`` 为该环产出或经过的动作类别。
    """

    stage: str
    kind: str
    allowed: bool | None
    reason: str = ""
    ms: float = 0.0


@dataclass(frozen=True)
class DecisionTrace:
    """一次引擎裁决的完整影子记录（只记不发；不含任何发送路径）。"""

    trace_id: str
    request_id: str
    mode: str
    origin: str
    plan_action: str = ""
    plan_capability_id: str = ""
    plan_reason: str = ""
    route_kind: str = ""
    route_priority: int | None = None
    legacy_capability_id: str = ""
    agree: bool | None = None
    compare_note: str = ""
    elapsed_ms: float = 0.0
    error: str = ""
    stages: tuple[DecisionStageRow, ...] = ()
    created_at: datetime = field(default_factory=_utc_now)


class DecisionTraceSink(Protocol):
    def record(self, trace: DecisionTrace) -> None: ...


class InMemoryDecisionTraceSink:
    """有界进程内 sink：供 shadow 比对与测试检查；超出容量丢最旧。"""

    def __init__(self, max_entries: int = 1024) -> None:
        self._max_entries = max(1, int(max_entries))
        self._lock = threading.Lock()
        self._entries: deque[DecisionTrace] = deque(maxlen=self._max_entries)

    def record(self, trace: DecisionTrace) -> None:
        with self._lock:
            self._entries.append(trace)

    def snapshot(self) -> list[DecisionTrace]:
        with self._lock:
            return list(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


_DEFAULT_QUEUE_MAX = 4096
_DEFAULT_BATCH_LIMIT = 64


class SqliteDecisionTraceSink:
    """审查 P-03 最小消费者：热缓冲（deque 语义零变化）+ 异步 SQLite 落盘。

    - 热缓冲：内部持有一个 :class:`InMemoryDecisionTraceSink`，``record /
      snapshot / clear / __len__`` 全部原样委托——存量 deque 语义（有界、
      超限丢最旧、锁保护）逐字节保留。
    - 落盘：record 先进热缓冲（同步、纯内存），再把条目交给专用单写线程
      攒批写 SQLite。record 本身绝不做磁盘 IO（shadow 挂钩在 pipeline 热
      路径上）；写失败只降级为不落盘（fail-open），绝不反噬主链路。
    - 生命周期：连接与线程都在首次 record 时才惰性创建（导入零 IO，测试
      不落文件）；``close()`` 供测试与优雅停机排空。

    SQLite 单写线程 + WAL（与 AddressingPreferenceStore 等既有 store 同款
    惯例）；查询走独立短连接（WAL 下读写不互斥）。
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        max_entries: int = 1024,
    ) -> None:
        self._memory = InMemoryDecisionTraceSink(max_entries)
        self._db_path_override = Path(db_path) if db_path is not None else None
        self._queue: queue.Queue[DecisionTrace | None] = queue.Queue(
            maxsize=_DEFAULT_QUEUE_MAX
        )
        self._cond = threading.Condition()
        self._pending = 0
        self._stopped = False
        self._worker: threading.Thread | None = None
        self._conn: sqlite3.Connection | None = None
        self._failure_logged = False
        # 队列打穿计数：put 失败即丢（fail-open），只留计数不阻塞热路径。
        self.dropped = 0

    # ---------- 热缓冲：与 InMemoryDecisionTraceSink 同签名同语义 ----------

    def record(self, trace: DecisionTrace) -> None:
        self._memory.record(trace)  # 先保热缓冲：存量 deque 语义零变化。
        with self._cond:
            if self._stopped:
                return
        self._ensure_worker()
        try:
            self._queue.put_nowait(trace)
        except queue.Full:
            # 有界队列打穿（写入线程卡死/洪峰）：丢弃并计数，绝不阻塞。
            self.dropped += 1
            return
        with self._cond:
            self._pending += 1

    def snapshot(self) -> list[DecisionTrace]:
        return self._memory.snapshot()

    def clear(self) -> None:
        # 只清热缓冲；SQLite 是追加式审计痕迹，不随热缓冲清空（查询口径
        # 见 recent()）。与旧 InMemory sink 的 clear 语义在 deque 侧一致。
        self._memory.clear()

    def __len__(self) -> int:
        return len(self._memory)

    # ---------- 落盘 ----------

    def _resolve_db_path(self) -> Path:
        if self._db_path_override is not None:
            return self._db_path_override
        # 惰性解析：默认落 runtime_data_dir（Bot 运行数据根），不进源码树。
        from scripts.runtime_paths import runtime_data_dir

        return runtime_data_dir() / DEFAULT_TRACE_DB_FILENAME

    def _ensure_worker(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        with self._cond:
            if self._worker is not None and self._worker.is_alive():
                return
            if self._stopped:
                return
            self._worker = threading.Thread(
                target=self._run_worker,
                name="decision-trace-writer",
                daemon=True,  # 影子诊断非关键数据：停机时随进程终止，不阻退出。
            )
            self._worker.start()

    def _run_worker(self) -> None:
        batch: list[DecisionTrace | None] = []
        while True:
            try:
                item = self._queue.get()
            except Exception:  # noqa: BLE001 - 解释器关停期队列可能失效。
                return
            batch = [item]
            while len(batch) < _DEFAULT_BATCH_LIMIT:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            stopped = batch[-1] is None
            to_write = [t for t in batch if t is not None]
            if to_write:
                self._write_batch(to_write)
            with self._cond:
                self._pending -= len(batch)
                if self._pending <= 0:
                    self._pending = 0
                    self._cond.notify_all()
            if stopped:
                return

    def _write_batch(self, batch: list[DecisionTrace]) -> None:
        if self._conn is None:
            try:
                path = self._resolve_db_path()
                path.parent.mkdir(parents=True, exist_ok=True)
                self._conn = sqlite3.connect(path, check_same_thread=False)
                # WAL 先于 DDL（项目惯例）：读写不互斥，查询侧可开短连接。
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._ensure_schema(self._conn)
            except sqlite3.Error as exc:
                self._log_failure_once("open", exc)
                self._conn = None
                return
        rows = [_trace_to_row(trace) for trace in batch]
        try:
            with self._conn:
                self._conn.executemany(
                    "INSERT INTO decision_trace ("
                    "trace_id, request_id, mode, origin, plan_action,"
                    " plan_capability_id, plan_reason, route_kind,"
                    " route_priority, legacy_capability_id, agree,"
                    " compare_note, elapsed_ms, error, stages_json, created_at"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    rows,
                )
                # 容量裁剪：只保留最近 MAX_PERSISTED_ROWS 行（按 id 最旧先删）。
                self._conn.execute(
                    "DELETE FROM decision_trace WHERE id <="
                    " (SELECT COALESCE(MAX(id), 0) FROM decision_trace) - ?",
                    (MAX_PERSISTED_ROWS,),
                )
        except sqlite3.Error as exc:
            self._log_failure_once("write", exc)

    @staticmethod
    def _ensure_schema(conn: sqlite3.Connection) -> None:
        # 建表幂等（审查 P-03）：重启/升级重复执行零副作用。
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS decision_trace (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id TEXT NOT NULL DEFAULT '',
                request_id TEXT NOT NULL DEFAULT '',
                mode TEXT NOT NULL DEFAULT '',
                origin TEXT NOT NULL DEFAULT '',
                plan_action TEXT NOT NULL DEFAULT '',
                plan_capability_id TEXT NOT NULL DEFAULT '',
                plan_reason TEXT NOT NULL DEFAULT '',
                route_kind TEXT NOT NULL DEFAULT '',
                route_priority INTEGER,
                legacy_capability_id TEXT NOT NULL DEFAULT '',
                agree INTEGER,
                compare_note TEXT NOT NULL DEFAULT '',
                elapsed_ms REAL NOT NULL DEFAULT 0.0,
                error TEXT NOT NULL DEFAULT '',
                stages_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT ''
            )
            """
        )

    def _log_failure_once(self, phase: str, exc: Exception) -> None:
        if not self._failure_logged:
            self._failure_logged = True
            logger.warning(
                "decision trace persist failed (phase=%s, fail-open): %s",
                phase,
                exc,
            )

    # ---------- 查询 / 生命周期 ----------

    def recent(self, limit: int) -> list[DecisionTrace]:
        """读最近 N 条（新→旧）；库缺失/为空时回落热缓冲（同口径排序）。

        供 ``/bot decision`` 管理员查询：值在落盘侧持久（跨重启），热缓冲
        只是短程补充。解析失败的行跳过，不让单行脏数据炸掉整个查询。
        """
        limit = max(1, int(limit))
        path = self._db_path_override
        if path is None:
            try:
                path = self._resolve_db_path()
            except Exception:  # noqa: BLE001 - 路径解析失败回落热缓冲。
                path = None
        if path is not None and path.exists():
            try:
                # 只读 URI 连接（as_uri 保证 Windows 盘符/特殊字符被正确编码）：
                # 查询侧绝不创建文件，库缺失时走热缓冲回落。
                with sqlite3.connect(
                    path.resolve().as_uri() + "?mode=ro", uri=True
                ) as conn:
                    rows = conn.execute(
                        "SELECT * FROM decision_trace ORDER BY id DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
                traces = [_row_to_trace(row) for row in rows]
                return [trace for trace in traces if trace is not None]
            except sqlite3.Error:
                return self._recent_from_memory(limit)
        return self._recent_from_memory(limit)

    def _recent_from_memory(self, limit: int) -> list[DecisionTrace]:
        return list(reversed(self._memory.snapshot()))[:limit]

    def flush(self, timeout: float = 5.0) -> bool:
        """等待在飞条目全部落盘（测试与优雅停机用）；超时返回 False。"""
        with self._cond:
            if self._pending <= 0:
                return True
            return self._cond.wait_for(lambda: self._pending <= 0, timeout=timeout)

    def close(self, timeout: float = 5.0) -> None:
        """停写并排空在飞条目；之后 record 仍保热缓冲但不再落盘。"""
        with self._cond:
            self._stopped = True
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        worker = self._worker
        if worker is not None:
            worker.join(timeout=timeout)
        conn = self._conn
        self._conn = None
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass


def _trace_to_row(trace: DecisionTrace) -> tuple:
    """DecisionTrace → SQLite 行元组；stages 序列化为 JSON（结构自描述）。"""
    stages_json = json.dumps(
        [
            {
                "stage": stage.stage,
                "kind": stage.kind,
                "allowed": stage.allowed,
                "reason": stage.reason,
                "ms": stage.ms,
            }
            for stage in trace.stages
        ],
        ensure_ascii=False,
    )
    return (
        trace.trace_id,
        trace.request_id,
        trace.mode,
        trace.origin,
        trace.plan_action,
        trace.plan_capability_id,
        trace.plan_reason,
        trace.route_kind,
        trace.route_priority,
        trace.legacy_capability_id,
        None if trace.agree is None else (1 if trace.agree else 0),
        trace.compare_note,
        trace.elapsed_ms,
        trace.error,
        stages_json,
        trace.created_at.isoformat(),
    )


_ROW_FIELDS = (
    "id", "trace_id", "request_id", "mode", "origin", "plan_action",
    "plan_capability_id", "plan_reason", "route_kind", "route_priority",
    "legacy_capability_id", "agree", "compare_note", "elapsed_ms", "error",
    "stages_json", "created_at",
)


def _row_to_trace(row: tuple) -> DecisionTrace | None:
    """SQLite 行 → DecisionTrace；结构不符/解析失败返回 None（调用方跳过）。"""
    try:
        record = dict(zip(_ROW_FIELDS, row))
        stages = tuple(
            DecisionStageRow(
                stage=str(item.get("stage", "")),
                kind=str(item.get("kind", "")),
                allowed=item.get("allowed"),
                reason=str(item.get("reason", "")),
                ms=float(item.get("ms", 0.0)),
            )
            for item in json.loads(str(record.get("stages_json") or "[]"))
            if isinstance(item, dict)
        )
        agree_raw = record.get("agree")
        created_raw = str(record.get("created_at") or "")
        created = (
            datetime.fromisoformat(created_raw)
            if created_raw
            else datetime.now(timezone.utc)
        )
        return DecisionTrace(
            trace_id=str(record.get("trace_id") or ""),
            request_id=str(record.get("request_id") or ""),
            mode=str(record.get("mode") or ""),
            origin=str(record.get("origin") or ""),
            plan_action=str(record.get("plan_action") or ""),
            plan_capability_id=str(record.get("plan_capability_id") or ""),
            plan_reason=str(record.get("plan_reason") or ""),
            route_kind=str(record.get("route_kind") or ""),
            route_priority=(
                int(record["route_priority"])
                if record.get("route_priority") is not None
                else None
            ),
            legacy_capability_id=str(record.get("legacy_capability_id") or ""),
            agree=None if agree_raw is None else bool(agree_raw),
            compare_note=str(record.get("compare_note") or ""),
            elapsed_ms=float(record.get("elapsed_ms") or 0.0),
            error=str(record.get("error") or ""),
            stages=stages,
            created_at=created,
        )
    except (ValueError, TypeError):
        return None


_default_sink: DecisionTraceSink = SqliteDecisionTraceSink()


def get_decision_trace_sink() -> DecisionTraceSink:
    """默认 trace 落点（P-03 起=热缓冲+SQLite 异步落盘；可整体替换）。"""
    return _default_sink


def set_decision_trace_sink(sink: DecisionTraceSink) -> None:
    global _default_sink
    _default_sink = sink
