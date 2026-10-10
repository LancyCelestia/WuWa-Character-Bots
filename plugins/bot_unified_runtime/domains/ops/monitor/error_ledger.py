"""线上报错的持久台账（W-7 收敛口，澜汐裁定 D-3 甲+乙 的「甲」腿）。

治的病（实算，不是猜）：告警链此前**零落盘**——`OperationalIssue` 只出文本与诊断卡，
`AdminAlertSuppression` 的抑制窗住在进程内存（dict + `time.monotonic`），重启即归零；
审计库按 `bot_audit_max_items` 剪枝，回溯窗实测只有几小时 ⇒ 隔夜复盘读的是被覆盖的
缓冲。于是「昨天那个报错」在三个地方都查不到，而每一处都"看起来正常"。

三条口径写死在这里：

1. **形状沿用既有台账，不另立 vocabulary**：构造签名、两阶段 TTL（先标 `expired`
   留排查窗、超 `purge_after_seconds` 才物理删）、`row_factory=sqlite3.Row`、
   线程锁与 `ReconcileSummary` 同族命名，一律照 `result_unknown.py` 的既有形状。
   第二套词汇＝第二本难查的账。
2. **一枚指纹一行，复发只 bump 计数**：`fingerprint = stage|kind|adapter|bot`
   （会话级字段取最新，不作合并键）。被抑制的那次也记账——这正是抑制窗吃掉的
   信息，本册存在的理由就是把它留住（投递侧的折叠规则不许反灌进台账，
   否则改一天折叠档，历史读数就跟着变）。
3. **纯本地 SQLite、fail-open 在调用方**：本模块**不吞异常**（真写不进去要让人
   看见），兜「一次磁盘故障不许带下水告警」的责任在 `alerts._record_issue_to_ledger`
   那一处唯一的咽喉里。只在这里 except 一遍、那里再 except 一遍＝两个地方都能
   静默，而静默的台账比没有台账更坏。

落点：Runtime 侧 `data/error_issue.sqlite3`（由根装配层经 `runtime_path` 传入，
源码树零数据，铁律 6）。不新增 `BOT_*` 配置键——与 `result_unknown` 同例：
那本账也没有键，路径在装配层构造。
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 默认一周：远宽于审计窗（小时级），又不至于让台账无限增长。
DEFAULT_EXPIRE_SECONDS = 604_800.0

# 指纹分隔符：用 `\x1f`（单元分隔符），报错键值里不可能出现，避免
# `stage="a|b"` 与 `stage="a", kind="b"` 撞成同一枚（拼接键的经典坑）。
_FINGERPRINT_SEP = "\x1f"

_ACTIVE = "active"
_EXPIRED = "expired"


def plain_value(value: Any) -> str:
    """枚举一律存 `.value`，别存 `str(enum)`。

    本机 3.12 实测 `str(SessionType.GROUP) == "SessionType.GROUP"`：把枚举裸交
    给按值判成员的谓词，对每个输入都回假 ⇒ 静默松开刚收紧的那一格。
    """
    if value is None:
        return ""
    inner = getattr(value, "value", None)
    if isinstance(inner, str):
        return inner.strip()
    return str(value).strip()


def issue_fingerprint(
    *,
    stage: Any,
    kind: Any,
    source_adapter: Any = "",
    source_bot: Any = "",
) -> str:
    """同一枚报错的稳定身份：``stage|kind|adapter|bot``（逐字段先归一再拼）。

    会话号、request_id、debug_id **不进键**：那会让每条复发都长出一行新账，
    而台账要回答的正是「这类问题这段时间 occurred 多少次」。
    """
    parts = (
        plain_value(stage).lower(),
        plain_value(kind).lower(),
        plain_value(source_adapter).lower(),
        plain_value(source_bot).lower(),
    )
    joined = _FINGERPRINT_SEP.join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class ReconcileSummary:
    """TTL 结果摘要；字段名与 ``result_unknown`` 同名册（pending/expired/purged）。"""

    pending: int = 0
    expired: int = 0
    purged: int = 0
    total: int = 0
    by_stage: dict[str, int] = field(default_factory=dict)


class ErrorIssueLedger:
    """报错台账；线程安全，纯本地 SQLite。"""

    def __init__(
        self,
        db_path: str | Path,
        *,
        expire_seconds: float = DEFAULT_EXPIRE_SECONDS,
        purge_after_seconds: float | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.db_path = Path(db_path)
        self.expire_seconds = max(60.0, float(expire_seconds))
        # 过期行先标 expired 留一个排查窗口，超 purge_after_seconds 才物理删除
        # （默认与 expire_seconds 相同），防台账随时间无上限增长。
        self.purge_after_seconds = (
            self.expire_seconds
            if purge_after_seconds is None
            else max(60.0, float(purge_after_seconds))
        )
        self._clock = clock
        self._lock = threading.Lock()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS error_issue (
                    fingerprint TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    severity TEXT NOT NULL DEFAULT '',
                    safe_summary TEXT NOT NULL DEFAULT '',
                    source_adapter TEXT NOT NULL DEFAULT '',
                    source_bot TEXT NOT NULL DEFAULT '',
                    session_type TEXT NOT NULL DEFAULT '',
                    session_id TEXT NOT NULL DEFAULT '',
                    capability_id TEXT NOT NULL DEFAULT '',
                    request_id TEXT NOT NULL DEFAULT '',
                    debug_id TEXT NOT NULL DEFAULT '',
                    attempts INTEGER NOT NULL DEFAULT 1,
                    elapsed_ms REAL,
                    hit_count INTEGER NOT NULL DEFAULT 1,
                    first_seen_at REAL NOT NULL,
                    last_seen_at REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    resolved_at REAL,
                    PRIMARY KEY (fingerprint)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_error_issue_status_last
                ON error_issue (status, last_seen_at)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        return connection

    def record(
        self,
        *,
        stage: Any,
        kind: Any,
        severity: Any = "",
        safe_summary: Any = "",
        source_adapter: Any = "",
        source_bot: Any = "",
        session_type: Any = "",
        session_id: Any = "",
        capability_id: Any = "",
        request_id: Any = "",
        debug_id: Any = "",
        attempts: Any = 1,
        elapsed_ms: Any = None,
    ) -> bool:
        """记一次报错；同指纹复发 ⇒ 一行、``hit_count`` 涨、``first_seen_at`` 保最早。

        返回 False 只有一种含义：**这条被拒了**（stage/kind 空白＝无法归因，
        与 ``OperationalIssue`` 自身的非空校验同口径）。写盘失败一律向上抛，
        由咽喉那唯一一处 fail-open 处置——本方法不静默。
        """
        stage_text = plain_value(stage)
        kind_text = plain_value(kind)
        if not stage_text or not kind_text:
            return False
        now = float(self._clock())
        fingerprint = issue_fingerprint(
            stage=stage_text,
            kind=kind_text,
            source_adapter=source_adapter,
            source_bot=source_bot,
        )
        try:
            attempts_value = int(attempts)
        except (TypeError, ValueError):
            attempts_value = 1
        elapsed_value = _optional_float(elapsed_ms)
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                """
                    INSERT INTO error_issue (
                        fingerprint, stage, kind, severity, safe_summary,
                        source_adapter, source_bot, session_type, session_id,
                        capability_id, request_id, debug_id, attempts, elapsed_ms,
                        hit_count, first_seen_at, last_seen_at, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                    ON CONFLICT(fingerprint) DO UPDATE SET
                        severity = excluded.severity,
                        safe_summary = excluded.safe_summary,
                        session_type = excluded.session_type,
                        session_id = excluded.session_id,
                        capability_id = excluded.capability_id,
                        request_id = excluded.request_id,
                        debug_id = excluded.debug_id,
                        attempts = excluded.attempts,
                        elapsed_ms = excluded.elapsed_ms,
                        hit_count = hit_count + 1,
                        first_seen_at = MIN(first_seen_at, excluded.first_seen_at),
                        last_seen_at = excluded.last_seen_at,
                        status = 'active',
                        resolved_at = NULL
                    """,
                (
                    fingerprint,
                    stage_text,
                    kind_text,
                    plain_value(severity),
                    plain_value(safe_summary),
                    plain_value(source_adapter),
                    plain_value(source_bot),
                    plain_value(session_type),
                    plain_value(session_id),
                    plain_value(capability_id),
                    plain_value(request_id),
                    plain_value(debug_id),
                    max(1, attempts_value),
                    elapsed_value,
                    now,
                    now,
                    _ACTIVE,
                ),
            )
        return True

    def recent(
        self,
        *,
        limit: int = 20,
        stage: str = "",
        kind: str = "",
        include_expired: bool = False,
    ) -> list[dict[str, Any]]:
        """按最近发生排序读台账单；默认**只给现役行**。

        默认口径不含 expired 是刻意的：把过期行混进"现役"读数，会让一次
        老故障冒充正在发生的故障。要看历史请显式 ``include_expired=True``。
        """
        clauses: list[str] = []
        params: list[Any] = []
        if not include_expired:
            clauses.append("status = ?")
            params.append(_ACTIVE)
        if stage:
            clauses.append("stage = ?")
            params.append(plain_value(stage))
        if kind:
            clauses.append("kind = ?")
            params.append(plain_value(kind))
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, int(limit)))
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM error_issue{where}
                ORDER BY last_seen_at DESC, rowid DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def reconcile(self, *, now: float | None = None) -> ReconcileSummary:
        """TTL 两段式：过 ``expire_seconds`` 标 expired，再过 purge 窗才删。

        顺带给出现役行的分档计数（``by_stage``），供自查面/卡面直接引用，
        省掉"读一遍再自己 group"的第二处实现。
        """
        moment = float(self._clock() if now is None else now)
        cutoff = moment - self.expire_seconds
        purge_cutoff = moment - self.purge_after_seconds
        with self._lock, closing(self._connect()) as connection, connection:
            expired = _count(
                connection.execute(
                    """
                    UPDATE error_issue SET status = ?, resolved_at = ?
                    WHERE status = ? AND last_seen_at < ?
                    """,
                    (_EXPIRED, moment, _ACTIVE, cutoff),
                )
            )
            purged = _count(
                connection.execute(
                    """
                    DELETE FROM error_issue
                    WHERE status = ?
                      AND COALESCE(resolved_at, last_seen_at) <= ?
                    """,
                    (_EXPIRED, purge_cutoff),
                )
            )
            rows = connection.execute(
                """
                SELECT stage, COUNT(*) AS n FROM error_issue
                WHERE status = ?
                GROUP BY stage
                """,
                (_ACTIVE,),
            ).fetchall()
            total = int(
                connection.execute("SELECT COUNT(*) AS n FROM error_issue").fetchone()["n"]
            )
        by_stage = {str(row["stage"]): int(row["n"]) for row in rows}
        return ReconcileSummary(
            pending=sum(by_stage.values()),
            expired=expired,
            purged=purged,
            total=total,
            by_stage=by_stage,
        )

    def purge_expired(self, *, now: float | None = None) -> int:
        """手动 TTL 清理（只删，不标）；返回删除数。"""
        moment = float(self._clock() if now is None else now)
        purge_cutoff = moment - self.purge_after_seconds
        with self._lock, closing(self._connect()) as connection, connection:
            return _count(
                connection.execute(
                    """
                    DELETE FROM error_issue
                    WHERE status = ?
                      AND COALESCE(resolved_at, last_seen_at) <= ?
                    """,
                    (_EXPIRED, purge_cutoff),
                )
            )


def _count(cursor: sqlite3.Cursor) -> int:
    rowcount = cursor.rowcount
    return rowcount if rowcount and rowcount > 0 else 0


def _optional_float(value: Any) -> float | None:
    """耗时留空态：`None`＝没测到，`0.0`＝测到了且很快。两者混成一个会把
    「时效性差」的读数列歪（本仓在别的表上吃过这个亏）。"""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
