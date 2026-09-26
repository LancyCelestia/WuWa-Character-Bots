"""贴纸发送史 + 隔离墓碑（goal-12 半 A/C 的中央硬机制）。

为什么收在这里
--------------
三条贴纸发送腿（``/偷表情``、回复后情绪表情包、戳一戳表情包形态）在生产里
**全部汇到同一个函数** ``MemeLibraryStore.weighted_pick``（根装配文件的 poke 腿
``_pick_poke_meme`` 也只是转调它）。把「同一张贴纸绝不发第二次」做在这个咽喉上，
= 一条机制管三腿，且不需要任何调用点配合（漏接一个新调用点也不会破功）。
反过来，若把记账写进各个能力层，就是三份副本 + 一个必然被绕过的洞。

身份 = 内容哈希
---------------
表情库主键是 md5，但**文件名会变**（``{md5}.{ext}``，ext 由 Content-Type 猜），
而跨库/改名/重新入库后仍是同一张图。发送史一律用 sha256 全长小写 hex，
算法只认中央件 ``domains/media/digest.py::media_digest``（蓝图 §3.1：本件
**禁止**自拼 ``hashlib.sha256``；截短是消费侧的事，这里不截）。

两层账、一张表
--------------
``meme_sends(scope, content_sha256, sent_at, reason)``，主键 ``(scope, content_sha256)``：
（``reason`` 列 S-STICKER-FINAL 增：选这张的归因代号串，旧行经 ALTER-if-missing
落空串——旧行为不记归因，如实留白。）

* **保留作用域** ``"*"``（:data:`GLOBAL_SCOPE`）= 「这个 bot 一共发过哪些贴纸」。
  缺省参与每一次判定 ⇒ 满足「同一张贴纸绝不发第二次」的字面要求。
* **每会话/每群作用域** = 调用方给的 ``scope``（会话键）。同一张图在两个不同
  会话各记一行，判定取并集。

判定口径：**只要任一作用域里有这一行，就不再选它**；因此「窗口」与「保留期」
是唯一的复开旋钮——两者都放宽到不裁时，历史即永久有效。缺省
``window=20000``（≥ 表情库上限 ``bot_meme_library_max_files`` 的缺省值，
等于「整个库轮一遍之前不重样」）、``retention_days=0``（**不按年龄裁剪**）。

隔离墓碑
--------
``meme_quarantine(content_sha256, reason, quarantined_at)``：只增不删的证据表。
NSFW 命中删除阈值时，旧实现只 ``store.remove(md5)``——文件与行都没了，
**同图再被发一次就会原样复活**（重新入库、重新打标、重新可发送）。
墓碑补的就是这一格：命中即永久拒收（``absorb`` 侧先查，见
``shorekeeper_absorb.py``）。隔离语义参照 ``scripts/clean_food_gallery.py``
（文件可回捞、判定不落地就不动、证据不抹）；差别是本表是**内容级**永久账，
不是按日期的一次性目录。
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.domains.media.digest import (
    media_digest,
    media_digest_file,
)

#: 保留作用域：所有调用方共享的「全局发过」账本。
GLOBAL_SCOPE = "*"

#: 每作用域滚动窗口（行）。缺省取 **20000**，与表情库按量上限
#: ``bot_meme_library_max_files`` 的缺省值同数 ⇒ 语义正好是「整个库轮一遍之前
#: 不重样」。刻意做成模块常量而不是配置键：本波没有一处能诚实声称的现读点，
#: 一枚没人读的键就是死键（config-catalog C-09 已定罪形态）。要升成配置面时，
#: 先把读点接上再改这里。
DEFAULT_WINDOW = 20000
#: 按龄保留期（天）。**0 = 不按年龄裁剪** ⇒ 「同一张贴纸绝不发第二次」不随时间
#: 松动；仍在线以外的账由 ``prune(live_hashes=…)``（库里已删的图）负责收。
DEFAULT_RETENTION_DAYS = 0

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meme_sends (
    scope TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    sent_at REAL NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (scope, content_sha256)
);
CREATE INDEX IF NOT EXISTS idx_meme_sends_scope_time ON meme_sends(scope, sent_at);
CREATE INDEX IF NOT EXISTS idx_meme_sends_time ON meme_sends(sent_at);
CREATE TABLE IF NOT EXISTS meme_quarantine (
    content_sha256 TEXT PRIMARY KEY,
    reason TEXT NOT NULL DEFAULT '',
    quarantined_at REAL NOT NULL
);
"""

#: ``meme_sends.reason`` 的迁移（goal-12 二段，S-STICKER-FINAL）：「选它的理由」
#: 必须落盘才算可归因——门面算出四因（本命/口味/心情/主题）却只在内存里存在，
#: 等于「算了不落盘＝没做」（先例：``phases_ms`` 算了没进诊断标签，见 #50）。
#: 家规与 ``affinity`` 三列、紧急域坐标两列同型：ALTER-if-missing，不 DROP 不清空。
_SENDS_REASON_MIGRATION = (
    "reason",
    "ALTER TABLE meme_sends ADD COLUMN reason TEXT NOT NULL DEFAULT ''",
)

#: 理由串的最大长度（进审计，不进用户文案；截断只在构造侧做）。
REASON_MAX_CHARS = 200


def sanitize_reason(value: object) -> str:
    """归因串卫生化：压成单行、限长、去控制字符。**不承载用户原文**。

    构造侧的纪律写在 ``meme_selection.attribution_for``：只允许词表代号 /
    档号 / 分值进入本串（用户昵称、聊天原文一律不进）。这里做最后一道形态卫生，
    即便调用方递来脏值也不会把换行/超长文本写进账本。
    """
    text = " ".join(str(value or "").split())
    if not text:
        return ""
    cleaned = "".join(ch for ch in text if ch.isprintable())
    return cleaned[:REASON_MAX_CHARS]


def normalize_scope(value: object) -> str:
    """会话键 → 账本作用域键：去空白、压成单行、限长，空值落保留字 global。

    绝不抛异常：作用域来自事件字段（群号/用户号/平台前缀），坏输入应当退回
    保留作用域（更严格的去重面），而不是让一次发图变成整条链路异常。
    """
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return GLOBAL_SCOPE
    return text[:180]


def scope_keys(scope: str | None = None) -> tuple[str, ...]:
    """判定/记账用的作用域元组：``(GLOBAL_SCOPE, 会话作用域)``，去重有序。"""
    resolved = normalize_scope(scope)
    return tuple(dict.fromkeys([GLOBAL_SCOPE, resolved]))


def content_sha256_of_bytes(data: bytes) -> str:
    """字节 → 内容身份（走中央摘要件，不在本件复制算法）。"""
    return media_digest(bytes(data))


def content_sha256_of_path(path: str | Path) -> str | None:
    """文件 → 内容身份；读不到返回 ``None``（缺即缺，调用方决定降级）。"""
    return media_digest_file(path)


class MemeSendHistoryStore:
    """贴纸发送史：按 (作用域, 内容哈希) 记账，提供原子「占坑」与两层裁剪。

    每操作独立连接（与 :class:`ReactionStore` 同风格），出口必关（``sqlite3`` 的
    ``with conn`` 只 commit 不 close，SQLite 句柄会按调用数累积——紧急域订阅波
    已踩过一次，见台账 #46）。写路径全部走 ``threading.Lock``：占坑必须在锁内
    完成「查全局 + 插各作用域」两步，否则并发两条腿会同时选中同一张贴纸。
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        window: int = DEFAULT_WINDOW,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        clock: Any = time.time,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.window = max(0, int(window))
        self.retention_days = max(0, int(retention_days))
        self._clock = clock
        self._lock = threading.Lock()
        with self._connect() as connection:
            connection.executescript(_SCHEMA)
            columns = {
                str(row["name"]) for row in connection.execute("PRAGMA table_info(meme_sends)")
            }
            if _SENDS_REASON_MIGRATION[0] not in columns:
                # 旧表补列（生产发送史在 09-26 重启波已按旧三列建表，行数可能为
                # 零或存量——ALTER-if-missing 两头都吃得下：空表补列、有行则旧行
                # reason 落缺省空串（诚实：旧行为本就不记归因）。
                connection.execute(_SENDS_REASON_MIGRATION[1])

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.db_path), timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    # ------------------------------------------------------------------ 判定

    def is_sent(self, content_sha256: str, *, scope: str | None = None) -> bool:
        """该哈希是否已在任一相关作用域发过（含全局保留作用域）。"""
        safe = str(content_sha256 or "").strip().lower()
        if not safe:
            # 身份不明 = 不放行（宁可不发，也不发一张无法记账的图造成重复）。
            return True
        scopes = scope_keys(scope)
        marks = ",".join("?" for _ in scopes)
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT 1 FROM meme_sends WHERE content_sha256=? AND scope IN ({marks}) LIMIT 1",
                (safe, *scopes),
            ).fetchone()
        return row is not None

    def sent_hashes(self, *, scope: str | None = None) -> frozenset[str]:
        """该作用域（含全局）已发过的全部哈希，供批量过滤/审计。"""
        scopes = scope_keys(scope)
        marks = ",".join("?" for _ in scopes)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT DISTINCT content_sha256 FROM meme_sends WHERE scope IN ({marks})",
                scopes,
            ).fetchall()
        return frozenset(str(row["content_sha256"]) for row in rows)

    # ------------------------------------------------------------------ 记账

    def try_claim(
        self,
        content_sha256: str,
        *,
        scope: str | None = None,
        at: float | None = None,
        reason: str = "",
    ) -> bool:
        """原子占坑：没发过就登记并返回 True；发过（含并发对手先占）返回 False。

        「查 + 插」在同一把锁与同一事务里，所以两个线程同时盯上同一张图时
        只有一个能拿到坑——这是「绝不重发」在并发下的真正保证（缺了锁就是
        两次 ``is_sent`` 都 False、然后各发一次）。

        ``reason``（S-STICKER-FINAL）：选这张的**归因串**（哪个情绪档/哪个标签
        命中/好感档，由 ``meme_selection.attribution_for`` 构造，只含词表代号与
        分值，不含用户原文）。同一事务写入各作用域行；不传即空串（旧调用点行为
        逐字节不变）。事后「你刚为什么发这张」就从这里查。
        """
        safe = str(content_sha256 or "").strip().lower()
        if not safe:
            return False
        moment = float(at if at is not None else self._clock())
        note = sanitize_reason(reason)
        with self._lock, self._connect() as connection:
            scopes = scope_keys(scope)
            marks = ",".join("?" for _ in scopes)
            existing = connection.execute(
                f"SELECT 1 FROM meme_sends WHERE content_sha256=? AND scope IN ({marks}) LIMIT 1",
                (safe, *scopes),
            ).fetchone()
            if existing is not None:
                return False
            connection.executemany(
                "INSERT OR IGNORE INTO meme_sends (scope, content_sha256, sent_at, reason)"
                " VALUES (?, ?, ?, ?)",
                [(one, safe, moment, note) for one in scopes],
            )
        return True

    def record(
        self,
        content_sha256: str,
        *,
        scope: str | None = None,
        at: float | None = None,
        reason: str = "",
    ) -> None:
        """无条件补记（幂等）：给「已由别处确认发出」的路径补账，不返回判定。

        ``reason``：见 :meth:`try_claim`；已有行不覆盖（补记语义=幂等，
        首记的理由就是当时的事实，后来者不重写历史）。
        """
        safe = str(content_sha256 or "").strip().lower()
        if not safe:
            return
        moment = float(at if at is not None else self._clock())
        note = sanitize_reason(reason)
        with self._lock, self._connect() as connection:
            connection.executemany(
                "INSERT OR IGNORE INTO meme_sends (scope, content_sha256, sent_at, reason)"
                " VALUES (?, ?, ?, ?)",
                [(one, safe, moment, note) for one in scope_keys(scope)],
            )

    def last_reason(self, content_sha256: str) -> str:
        """这张（内容哈希）最近一次发送记的归因串（任一作用域，含全局）。"""
        safe = str(content_sha256 or "").strip().lower()
        if not safe:
            return ""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT reason FROM meme_sends WHERE content_sha256=? ORDER BY sent_at DESC LIMIT 1",
                (safe,),
            ).fetchone()
        return str(row["reason"]) if row is not None else ""

    def recent_sends(self, *, limit: int = 10) -> list[dict[str, Any]]:
        """最近的发送（全局视角，按时间倒序）：``{content_sha256, reason, sent_at}``。

        同一张图在多作用域各有一行时按内容哈希去重保最新——这是「刚发了什么、
        为什么发它」的查询面；不含文件名与用户原文（键=内容哈希，理由=代号串）。
        """
        cap = max(0, int(limit))
        if cap == 0:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT content_sha256, reason, sent_at FROM meme_sends
                ORDER BY sent_at DESC LIMIT ?
                """,
                (cap * 4 + 8,),
            ).fetchall()
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            sha = str(row["content_sha256"])
            if sha in seen:
                continue
            seen.add(sha)
            out.append(
                {
                    "content_sha256": sha,
                    "reason": str(row["reason"] or ""),
                    "sent_at": float(row["sent_at"]),
                }
            )
            if len(out) >= cap:
                break
        return out

    def forget_scope(self, scope: str | None) -> int:
        """清空某一**具名**作用域（全局保留作用域不可清）；返回删除行数。

        超管说「这批重发也无妨」时唯一入口。绝不清 ``GLOBAL_SCOPE``：那会把
        「绝不重发」的字面承诺一起抹掉，需要的话得走 :meth:`reset_all`（显式）。
        """
        resolved = normalize_scope(scope)
        if resolved == GLOBAL_SCOPE:
            return 0
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM meme_sends WHERE scope=?", (resolved,))
            return int(cursor.rowcount or 0)

    # ------------------------------------------------------------------ 裁剪

    def prune(self, *, live_hashes: Iterable[str] | None = None) -> dict[str, int]:
        """两层裁剪：①过期（``retention_days>0`` 才生效）②每作用域滚动窗口。

        库外哈希（贴纸已从表情库删除、不可能再被选中）一并裁掉，防止账本
        只随历史单调膨胀；``live_hashes=None`` 时**不**做这一层（调用方没给
        真相源就别自作主张删证据）。窗口按 ``sent_at`` 留最新 ``window`` 行。
        """
        removed = {"expired": 0, "overflow": 0, "dead": 0}
        with self._lock, self._connect() as connection:
            if self.retention_days > 0:
                cutoff = float(self._clock()) - self.retention_days * 86400.0
                cursor = connection.execute(
                    "DELETE FROM meme_sends WHERE sent_at < ?", (cutoff,)
                )
                removed["expired"] = int(cursor.rowcount or 0)
            if self.window > 0:
                rows = connection.execute("SELECT DISTINCT scope FROM meme_sends").fetchall()
                for row in rows:
                    scope = str(row["scope"])
                    cursor = connection.execute(
                        """
                        DELETE FROM meme_sends
                        WHERE scope=? AND content_sha256 NOT IN (
                            SELECT content_sha256 FROM meme_sends WHERE scope=?
                            ORDER BY sent_at DESC LIMIT ?
                        )
                        """,
                        (scope, scope, self.window),
                    )
                    removed["overflow"] += int(cursor.rowcount or 0)
            if live_hashes is not None:
                keep = {
                    str(item or "").strip().lower()
                    for item in live_hashes
                    if str(item or "").strip()
                }
                rows = connection.execute(
                    "SELECT scope, content_sha256 FROM meme_sends"
                ).fetchall()
                dead = [
                    (str(row["scope"]), str(row["content_sha256"]))
                    for row in rows
                    if str(row["content_sha256"]) not in keep
                ]
                for scope, sha in dead:
                    connection.execute(
                        "DELETE FROM meme_sends WHERE scope=? AND content_sha256=?",
                        (scope, sha),
                    )
                removed["dead"] = len(dead)
        return removed

    def stats(self, *, scope: str | None = None) -> dict[str, Any]:
        scopes = scope_keys(scope)
        marks = ",".join("?" for _ in scopes)
        with self._connect() as connection:
            scoped = int(
                connection.execute(
                    f"SELECT COUNT(*) AS c FROM meme_sends WHERE scope IN ({marks})", scopes
                ).fetchone()["c"]
            )
            total = int(connection.execute("SELECT COUNT(*) AS c FROM meme_sends").fetchone()["c"])
            global_rows = int(
                connection.execute(
                    "SELECT COUNT(*) AS c FROM meme_sends WHERE scope=?", (GLOBAL_SCOPE,)
                ).fetchone()["c"]
            )
        return {
            "scoped_rows": scoped,
            "total_rows": total,
            "global_sent": global_rows,
            "window": self.window,
            "retention_days": self.retention_days,
        }


class MemeQuarantineLedger:
    """内容级隔离墓碑：命中即永久拒收，同图重发也不复活（只增不删）。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.db_path), timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def contains(self, content_sha256: str) -> bool:
        safe = str(content_sha256 or "").strip().lower()
        if not safe:
            return False
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM meme_quarantine WHERE content_sha256=? LIMIT 1", (safe,)
            ).fetchone()
        return row is not None

    def add(self, content_sha256: str, *, reason: str = "", at: float | None = None) -> bool:
        """立碑（幂等）：已存在不覆盖首次证据，返回本次是否新立。"""
        safe = str(content_sha256 or "").strip().lower()
        if not safe:
            return False
        moment = float(at if at is not None else time.time())
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO meme_quarantine (content_sha256, reason, quarantined_at)"
                " VALUES (?, ?, ?)",
                (safe, " ".join(str(reason or "").split())[:120], moment),
            )
            return int(cursor.rowcount or 0) > 0

    def reasons(self, content_sha256: str) -> str:
        safe = str(content_sha256 or "").strip().lower()
        if not safe:
            return ""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT reason FROM meme_quarantine WHERE content_sha256=?", (safe,)
            ).fetchone()
        return str(row["reason"]) if row is not None else ""

    def count(self) -> int:
        with self._connect() as connection:
            return int(
                connection.execute("SELECT COUNT(*) AS c FROM meme_quarantine").fetchone()["c"]
            )


__all__ = [
    "DEFAULT_RETENTION_DAYS",
    "DEFAULT_WINDOW",
    "GLOBAL_SCOPE",
    "REASON_MAX_CHARS",
    "MemeQuarantineLedger",
    "MemeSendHistoryStore",
    "content_sha256_of_bytes",
    "content_sha256_of_path",
    "normalize_scope",
    "sanitize_reason",
    "scope_keys",
]
