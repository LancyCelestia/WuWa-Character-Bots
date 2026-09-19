"""V2.1 S12 抽签持久层：DrawStore（占卜统一服务的存储半边）。

合同来源：docs/design/backend-v2-product-extensions.md §3（V21-DIVINATION-001）。

- 库路径经 ``scripts.runtime_paths`` 重映射（``data/`` 前缀 → ChatBot_Runtime），
  与 notes_store/media_registry 同一惯例；绝对路径原样透传（tmp_path 可测）。
- PRAGMA：journal_mode=WAL、busy_timeout=1000ms、synchronous=NORMAL；
  每操作独立连接（campus_store/schedule_store 同风格），跨进程由
  ``BEGIN IMMEDIATE`` + busy_timeout 串行化，跨线程天然安全。
- 幂等三键：
  - ``draw_id`` PRIMARY KEY（结果标识，重试不变）；
  - ``idempotency_key`` UNIQUE（客户端幂等键，同键并发只建一次——
    先查后插 + 唯一索引兜底，竞态输者读回赢者的行）；
  - ``(kind, dedupe_key)`` 部分唯一索引（fortune 的 day_key 唯一——
    同日跨会话/跨幂等键/重启/密钥轮换都命中既有行不重抽）。
- 配额：塔罗随机抽取的每日上限与冷却在 ``persist_draw_once`` 的同一
  ``BEGIN IMMEDIATE`` 写锁事务内判定（并发不超卖）；命中 → ``rate_limited``
  （contracts/errors.py 已注册码）。运势不入配额（每日一次幂等 + 重读不限）。
- 本模块只依赖标准库，零网络零第三方；错误码全部取自 contracts/errors.py
  注册表（本席只用 rate_limited，域校验码在 runtime 服务半边抛出）。
"""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_TAROT_COOLDOWN_SECONDS",
    "DEFAULT_TAROT_DAILY_LIMIT",
    "DrawError",
    "DrawRecord",
    "DrawStore",
    "QuotaPolicy",
]

# 合同 §3.2 默认配额：每主体塔罗冷却 60 秒、每天 20 次（workspace 独立）。
DEFAULT_TAROT_COOLDOWN_SECONDS = 60
DEFAULT_TAROT_DAILY_LIMIT = 20


class DrawError(Exception):
    """抽签持久层/域错误；``code`` 必须是 contracts/errors.py 已注册码。"""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code


@dataclass(frozen=True)
class QuotaPolicy:
    """塔罗随机抽取配额（按 principal+bot+workspace+local_day 判定）。"""

    cooldown_seconds: int = DEFAULT_TAROT_COOLDOWN_SECONDS
    daily_limit: int = DEFAULT_TAROT_DAILY_LIMIT


@dataclass(frozen=True)
class DrawRecord:
    """一次抽签的持久形态（契约结果由服务层投影）。

    - fortune：``dedupe_key``=day_key、``fortune_grade`` 非空、``cards`` 为空。
    - tarot：``dedupe_key`` 为空串、``cards`` 为牌面序列
      （元素含 card_id/position_id/orientation 三键）。
    """

    draw_id: str
    kind: str
    principal_id: str
    bot_id: str
    workspace_id: str
    idempotency_key: str
    dedupe_key: str = ""
    spread_id: str = ""
    question: str = ""
    timezone_id: str = ""
    cards: tuple[dict[str, str], ...] = ()
    fortune_grade: str = ""
    algorithm_revision: str = ""
    deck_revision: str = ""
    key_id: str = ""
    seed_digest: str = ""
    trace_id: str = ""
    local_day: str = ""
    occurred_at: str = ""
    occurred_epoch: float = 0.0

    def cards_json(self) -> str:
        return json.dumps(list(self.cards), ensure_ascii=False, sort_keys=True)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS draws (
    draw_id            TEXT PRIMARY KEY,
    kind               TEXT NOT NULL,
    principal_id       TEXT NOT NULL,
    bot_id             TEXT NOT NULL,
    workspace_id       TEXT NOT NULL DEFAULT '',
    idempotency_key    TEXT NOT NULL,
    dedupe_key         TEXT NOT NULL DEFAULT '',
    spread_id          TEXT NOT NULL DEFAULT '',
    question           TEXT NOT NULL DEFAULT '',
    timezone_id        TEXT NOT NULL DEFAULT '',
    cards_json         TEXT NOT NULL DEFAULT '[]',
    fortune_grade      TEXT NOT NULL DEFAULT '',
    algorithm_revision TEXT NOT NULL DEFAULT '',
    deck_revision      TEXT NOT NULL DEFAULT '',
    key_id             TEXT NOT NULL DEFAULT '',
    seed_digest        TEXT NOT NULL DEFAULT '',
    trace_id           TEXT NOT NULL DEFAULT '',
    local_day          TEXT NOT NULL DEFAULT '',
    occurred_at        TEXT NOT NULL,
    occurred_epoch     REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_draws_idem ON draws(idempotency_key);
CREATE UNIQUE INDEX IF NOT EXISTS idx_draws_dedupe
    ON draws(kind, dedupe_key) WHERE dedupe_key <> '';
CREATE INDEX IF NOT EXISTS idx_draws_quota
    ON draws(kind, principal_id, bot_id, workspace_id, local_day);
"""

_COLUMNS = (
    "draw_id, kind, principal_id, bot_id, workspace_id, idempotency_key, "
    "dedupe_key, spread_id, question, timezone_id, cards_json, "
    "fortune_grade, algorithm_revision, deck_revision, key_id, seed_digest, "
    "trace_id, local_day, occurred_at, occurred_epoch"
)


def _epoch_of(moment: datetime) -> float:
    """aware 统一 UTC epoch（naive 视作 UTC），冷却比较不因时区漂移。"""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def _resolve_db_path(value: str | Path) -> Path:
    """data/... → 配置的 Runtime 数据根（复用 runtime_paths 规则）。"""
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    import sys

    project_root = Path(__file__).resolve().parents[3]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    try:
        from scripts.runtime_paths import runtime_path

        return runtime_path(str(value))
    except Exception:
        logger.warning(
            "runtime_path 解析失败，退回源码树 data/（value=%s）", value, exc_info=True
        )
        return project_root / path


def _record_from_row(row: sqlite3.Row) -> DrawRecord:
    try:
        cards_raw = json.loads(str(row["cards_json"]))
    except (TypeError, ValueError):
        cards_raw = []
    cards: tuple[dict[str, str], ...] = ()
    if isinstance(cards_raw, list):
        cards = tuple(item for item in cards_raw if isinstance(item, dict))
    return DrawRecord(
        draw_id=str(row["draw_id"]),
        kind=str(row["kind"]),
        principal_id=str(row["principal_id"]),
        bot_id=str(row["bot_id"]),
        workspace_id=str(row["workspace_id"]),
        idempotency_key=str(row["idempotency_key"]),
        dedupe_key=str(row["dedupe_key"]),
        spread_id=str(row["spread_id"]),
        question=str(row["question"]),
        timezone_id=str(row["timezone_id"]),
        cards=cards,
        fortune_grade=str(row["fortune_grade"]),
        algorithm_revision=str(row["algorithm_revision"]),
        deck_revision=str(row["deck_revision"]),
        key_id=str(row["key_id"]),
        seed_digest=str(row["seed_digest"]),
        trace_id=str(row["trace_id"]),
        local_day=str(row["local_day"]),
        occurred_at=str(row["occurred_at"]),
        occurred_epoch=float(row["occurred_epoch"]),
    )


def _insert_sql() -> str:
    columns = _COLUMNS.replace(" ", "").split(",")
    placeholders = ", ".join("?" for _ in columns)
    return f"INSERT INTO draws ({_COLUMNS}) VALUES ({placeholders})"


_SCHEMA_STATEMENTS: tuple[str, ...] = tuple(
    statement.strip()
    for statement in _SCHEMA.split(";")
    if statement.strip()
)


class DrawStore:
    """抽签库：draw_id/idempotency_key/day_key 三重幂等 + 事务内配额。"""

    # 并发建库退避（PRAGMA journal_mode 变更可能 SQLITE_BUSY 且不走 busy
    # handler；WAL 是文件头持久属性，首个成功初始化的连接设置后即全局生效）。
    _INIT_BACKOFF_SECONDS: tuple[float, ...] = (0.0, 0.05, 0.15, 0.3, 0.5)

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = _resolve_db_path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    def _connect(self) -> sqlite3.Connection:
        # isolation_level=None（自动提交）：写路径显式 BEGIN IMMEDIATE 串行化，
        # 配额判定与插入同一写锁事务（并发不超卖）；读路径免事务即时可见。
        # busy_timeout 必须最先设置（WAL 已由 _initialize_schema 持久化，
        # 连接期不再触碰 journal_mode，避开其不走 busy handler 的窗口）。
        connection = sqlite3.connect(
            str(self.db_path), timeout=10, isolation_level=None
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=1000")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _initialize_schema(self) -> None:
        """WAL + 建表：单个写事务内完成，忙时按退避序列重试。"""
        last_error: sqlite3.OperationalError | None = None
        for delay in self._INIT_BACKOFF_SECONDS:
            if delay:
                time.sleep(delay)
            connection = self._connect()
            try:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("BEGIN IMMEDIATE")
                for statement in _SCHEMA_STATEMENTS:
                    connection.execute(statement)
                connection.execute("COMMIT")
                return
            except sqlite3.OperationalError as exc:
                last_error = exc
                with contextlib.suppress(sqlite3.OperationalError):
                    connection.execute("ROLLBACK")
            finally:
                connection.close()
        assert last_error is not None  # 重试序列非空，必有一次失败记录
        raise last_error

    # ── 读面（重读不限，不改任何状态）────────────────────────────────────

    def get_draw(self, draw_id: str) -> DrawRecord | None:
        """按 draw_id 读既有抽取；无则 None。"""
        with contextlib.closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM draws WHERE draw_id = ?", (str(draw_id),)
            ).fetchone()
        return _record_from_row(row) if row is not None else None

    def find_by_idempotency_key(self, idempotency_key: str) -> DrawRecord | None:
        """按客户端幂等键读既有抽取；无则 None。"""
        with contextlib.closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM draws WHERE idempotency_key = ?",
                (str(idempotency_key),),
            ).fetchone()
        return _record_from_row(row) if row is not None else None

    def find_by_dedupe(self, kind: str, dedupe_key: str) -> DrawRecord | None:
        """按 (kind, dedupe_key) 读既有抽取（fortune 的 day_key 查找）。"""
        if not dedupe_key:
            return None
        with contextlib.closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM draws WHERE kind = ? AND dedupe_key = ?",
                (str(kind), str(dedupe_key)),
            ).fetchone()
        return _record_from_row(row) if row is not None else None

    # ── 写面（幂等 + 配额同事务）────────────────────────────────────────

    def persist_draw_once(
        self,
        record: DrawRecord,
        *,
        quota: QuotaPolicy | None = None,
    ) -> tuple[DrawRecord, bool]:
        """幂等写入一次抽取：同 idempotency_key/draw_id/day_key 并发只建一次。

        - 命中既有（三键任一）→ 返回 ``(既有行, False)``，不重抽不重计数。
        - ``quota`` 非空且 kind='tarot'：同一 (principal, bot, workspace) 的
          当日随机抽取计数与冷却在同一写锁事务内判定，超限 →
          ``DrawError("rate_limited")`` 并回滚（并发不超卖）。
        - 竞态败者（唯一索引冲突）读回赢者的行，语义与先查命中一致。
        """
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM draws WHERE draw_id = ? OR idempotency_key = ?",
                (str(record.draw_id), str(record.idempotency_key)),
            ).fetchone()
            if existing is None and record.dedupe_key:
                existing = connection.execute(
                    "SELECT * FROM draws WHERE kind = ? AND dedupe_key = ?",
                    (str(record.kind), str(record.dedupe_key)),
                ).fetchone()
            if existing is not None:
                connection.execute("COMMIT")
                return _record_from_row(existing), False
            self._enforce_quota(connection, record, quota)
            connection.execute(
                _insert_sql(),
                (
                    str(record.draw_id),
                    str(record.kind),
                    str(record.principal_id),
                    str(record.bot_id),
                    str(record.workspace_id),
                    str(record.idempotency_key),
                    str(record.dedupe_key),
                    str(record.spread_id),
                    str(record.question),
                    str(record.timezone_id),
                    record.cards_json(),
                    str(record.fortune_grade),
                    str(record.algorithm_revision),
                    str(record.deck_revision),
                    str(record.key_id),
                    str(record.seed_digest),
                    str(record.trace_id),
                    str(record.local_day),
                    str(record.occurred_at),
                    float(record.occurred_epoch),
                ),
            )
            row = connection.execute(
                "SELECT * FROM draws WHERE draw_id = ?", (str(record.draw_id),)
            ).fetchone()
            connection.execute("COMMIT")
            return _record_from_row(row), True
        except sqlite3.IntegrityError:
            # 并发下另一连接先插入同键：按幂等键/day_key/draw_id 读回既有行
            # （竞态败者的 draw_id 与赢者不同，必须以业务幂等键定位）。
            try:
                connection.execute("ROLLBACK")
            except sqlite3.OperationalError:  # pragma: no cover - 事务已结束
                pass
            row = connection.execute(
                "SELECT * FROM draws WHERE idempotency_key = ?",
                (str(record.idempotency_key),),
            ).fetchone()
            if row is None and record.dedupe_key:
                row = connection.execute(
                    "SELECT * FROM draws WHERE kind = ? AND dedupe_key = ?",
                    (str(record.kind), str(record.dedupe_key)),
                ).fetchone()
            if row is None:  # pragma: no cover - 唯一索引命中必有行
                raise
            return _record_from_row(row), False
        except DrawError:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.OperationalError:  # pragma: no cover - 事务已结束
                pass
            raise
        finally:
            connection.close()

    def _enforce_quota(
        self,
        connection: sqlite3.Connection,
        record: DrawRecord,
        quota: QuotaPolicy | None,
    ) -> None:
        """配额判定（调用方处于 BEGIN IMMEDIATE 写锁事务内）。"""
        if quota is None or record.kind != "tarot":
            return
        count_today = connection.execute(
            """
            SELECT COUNT(*) FROM draws
            WHERE kind = 'tarot' AND principal_id = ? AND bot_id = ?
              AND workspace_id = ? AND local_day = ?
            """,
            (
                str(record.principal_id),
                str(record.bot_id),
                str(record.workspace_id),
                str(record.local_day),
            ),
        ).fetchone()[0]
        if count_today >= max(0, int(quota.daily_limit)):
            raise DrawError("rate_limited", "今日塔罗抽取次数已用完")
        last = connection.execute(
            """
            SELECT MAX(occurred_epoch) FROM draws
            WHERE kind = 'tarot' AND principal_id = ? AND bot_id = ?
              AND workspace_id = ?
            """,
            (
                str(record.principal_id),
                str(record.bot_id),
                str(record.workspace_id),
            ),
        ).fetchone()[0]
        if last is not None:
            elapsed = float(record.occurred_epoch) - float(last)
            if elapsed < float(quota.cooldown_seconds):
                raise DrawError("rate_limited", "塔罗抽取冷却中")
