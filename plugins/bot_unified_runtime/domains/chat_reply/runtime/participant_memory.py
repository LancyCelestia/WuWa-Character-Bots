"""参与者记忆读数（bot.group_info 参与者腿的取数件，2026-09-26 S-T-GRP-2）。

用户裁定 **参与者按记忆算**：「这个会话里有谁」报的是**我记下的说过话的人**，
不是协议层群成员名单。两条理由都在判据里立着：

- 隐私与防刷屏：本仓早已拒绝整列名单（`group_info._TG_NO_ROSTER_LINE`、
  该文件头「成员名单不整列（隐私+防刷屏）」）；
- 能力面真值：QQ 侧逐成员状态在本协议端动作册里并不可靠（权威是 SnowLuma 189 枚
  ``ACTION_REGISTRY``，不是愿望）。

所以取数只走机器人**自己的会话记忆**：``conversation_turns``（历史库，owner 是
``character/history.py``）里真实落过的发言行。本件**只读**——以 SQLite URI
``mode=ro`` 打开，库不存在就是打不开、直接判「读不出」，绝不建库、绝不写一行
（守住「运行数据不可删/不可动」铁律，也顺带保证任何路径都不改生产库）。

跨库只读投影的在册先例 = ``character/shared_group.py:_fetch_group_rows``：
它直接开 ``conversation_turns`` 做群级聚合（该表 owner 同样是 history.py）。
本件照同一形态走，并照它的两处防御：``PRAGMA table_info`` 容缺 ``kind`` 列、
LIKE/前缀口径来自中央件而非自造。

键口径（**必须走 `domains/core/session_keys.py`，禁止手拼 ``group_<gid>_<uid>``**）：

- 群作用域：前缀 = ``group_session_prefix(group_id)``（= ``group_<gid>_``，尾下划线
  天然是段分隔符，不会把 ``group_1234_`` 串进 ``group_123_`` 的窗口）。
  生产库实测形态 ``group_598564701_1824432453``，Telegram 的 thread 形
  ``group_<cid>_thread<t>_<uid>`` 也落进同一前缀（同一会话的正确语义）。
- 私聊/邮件作用域：session_id **等值**。这里刻意**不**用前缀：OneBot 私聊键是裸
  uid（实测 ``3865067623``），前缀匹配会让 ``386506762`` 吞掉 ``3865067623``——
  那是把别人的私聊算进本会话，属隐私事故，不是模糊匹配的小优化。

三态判据（本件存在的核心理由，别让它们糊成一坨）：

- ``STATE_OK`` 记到人了；
- ``STATE_EMPTY`` 库能开、表在、窗口扫了、**确实一行发言都没有** ⇒
  这叫「我这儿还没有人说过话的记录」；
- ``STATE_UNAVAILABLE`` 库缺/打不开/表缺/SQL 出错 ⇒ 这叫「读不出来」，
  **绝不许**被渲染成「这个群没有人」（本仓对「把『我不知道』写成『它没有』」
  有常驻禁令，见 commits ``cd0068c`` / ``21bdabf``）。

名字取数口径：``conversation_turns`` 不存显示名（DDL 里没这列，实测表只有 10 列），
所以名字从 ``group_affinity.display_name`` 取——那是**在册的唯一「本群这人叫什么」
记录位**（owner ``character/affinity.py``:1447，写入点根 ``__init__.py:8414`` 喂的
正是摄取层唯一源 ``IncomingMessage.sender_display_name``）。本件不新开第三份名字账，
也**不**读 ``leaderboard()`` 的 ``score``/``tier``（个人评分不该在群里的参与者清单上
出现）。取不到名字就照实说取不到，绝不拿用户号顶上。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from plugins.bot_unified_runtime.domains.core.session_keys import (
    group_session_prefix,
    normalize_session_key,
    parse_session_key,
)

# 三态（渲染层按态分句，绝不由本件替它下「没有」的结论）。
STATE_OK: Final[str] = "ok"
STATE_EMPTY: Final[str] = "empty"
STATE_UNAVAILABLE: Final[str] = "unavailable"

# 不可用原因的机器标签（只进审计，不进用户正文；正文由能力层说人话）。
REASON_DB_MISSING: Final[str] = "participant_db_missing"
REASON_DB_DISABLED: Final[str] = "participant_history_disabled"
REASON_TABLE_MISSING: Final[str] = "participant_table_missing"
REASON_SQL_ERROR: Final[str] = "participant_sql_error"
REASON_BAD_SCOPE: Final[str] = "participant_scope_invalid"

#: 一次最多扫多少条历史行。**窗口是有界的**，扫满即如实说「只翻到最近这么多条」——
#: 无界全表扫在生产库（实测数千行、随天增长）上是把「谁说过话」变成一次卡顿，
#: 而有界不声明就是谎报「这就是所有人」。两者都要防。
ROW_WINDOW_DEFAULT: Final[int] = 4000

_HISTORY_TABLE = "conversation_turns"
_AFFINITY_NAME_TABLE = "group_affinity"


@dataclass(frozen=True)
class ParticipantScope:
    """一次读取的作用域：群=前缀窗口，其余=会话键等值。

    ``group_id`` 非空 ⇒ 群作用域（名字从 ``group_affinity`` 取）；
    空 ⇒ 私聊/邮件/控制台作用域（等值键，名字由调用方用自带事实补）。
    """

    match: str  # "prefix" | "exact"
    key: str
    group_id: str = ""

    @property
    def is_group(self) -> bool:
        return self.match == "prefix" and bool(self.group_id)


@dataclass(frozen=True)
class ParticipantRecord:
    """一个被我记下说过话的人。

    ``turns``/``last_seen`` 取自语义明确的列聚合：``turns`` = 该人在本窗口内
    ``role='user'`` 的行数（机器人自己的回复 ``role='assistant'`` 不计入——那不是
    「这个人说过话」的证据），``last_seen`` = 这些行里最新的 ``created_at`` 原文
    （UTC ISO 串，落库口径见 history.py，渲染层不做时区换算以免编造本地时刻）。
    """

    sender_id: str
    display_name: str
    turns: int
    last_seen: str


@dataclass(frozen=True)
class ParticipantMemory:
    """一次读数（三态 + 窗口诚实声明）。"""

    state: str
    records: tuple[ParticipantRecord, ...] = ()
    #: 本窗口内**去重后的说话人数**（= len(records)；截断展示时的守恒基准，
    #: 渲染层用它算「另有 N 位未列出」，N 必须是实算不是猜）。
    total_speakers: int = 0
    reason: str = ""
    #: 扫到窗口上限仍未收口 ⇒ True（渲染层必须显式声明「只翻了最近 N 条记录」）。
    window_exhausted: bool = False
    row_window: int = ROW_WINDOW_DEFAULT


def group_participant_scope(group_id: Any) -> ParticipantScope | None:
    """群作用域（前缀由中央件构造，非法/空群号返回 None＝无作用域，不猜键）。

    返回 None 时调用方**绝不**能退化成「整表扫」（那会把别的群算进来）。
    """
    prefix = group_session_prefix(group_id)
    if not prefix:
        return None
    parsed = parse_session_key(prefix + "probe")
    if not parsed.is_group:  # 中央件判定兜底：半截/夹空白的脏键不给群身份。
        return None
    return ParticipantScope(match="prefix", key=prefix, group_id=parsed.group_id)


def session_participant_scope(session_id: Any) -> ParticipantScope | None:
    """会话等值作用域（私聊/邮件/控制台；键先走中央件归一再等值）。"""
    key = normalize_session_key(session_id)
    if not key:
        return None
    return ParticipantScope(match="exact", key=key)


def _read_only_uri(path: Path) -> str:
    """SQLite 只读 URI（打不开就是打不开，绝不用默认形态建出空库来）。"""
    return f"{path.resolve().as_uri()}?mode=ro"


@contextmanager
def _open_read_only(path: Path) -> Iterator[sqlite3.Connection]:
    """只读连接，**出口必关**。

    这枚坑本仓咬过不止一次（WIRE-SUB 台账：sqlite3 的 ``with conn`` 只 commit
    不 close，轮询式读会按调用数累积句柄，Windows 上表现为库文件删不掉）。
    本件每次读都开一条连接，所以更得显式收尾——用 ``with conn`` 就是给自己埋雷。
    """
    connection = sqlite3.connect(_read_only_uri(path), uri=True)
    try:
        yield connection
    finally:
        connection.close()


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _kind_filter(connection: sqlite3.Connection) -> str:
    """``kind`` 列可能不在（旧库未 ALTER）——照 shared_group 的容缺形态处理。

    过滤掉 ``kind='command'``/``'system'``：命令轮次（查天气、/bot status 一类）
    与系统行不是「这个人在群里说了话」的证据；留 ``chat``（含旧库 NULL）。
    """
    return (
        "AND (kind IS NULL OR kind = 'chat')"
        if "kind" in _columns(connection, _HISTORY_TABLE)
        else ""
    )


class HistoryParticipantReader:
    """参与者读数：历史库数说话人 + 好感库取群内名字（两处都只读）。

    ``history_db_path`` 空 ⇒ 直接 ``STATE_UNAVAILABLE``（配置没开历史记忆就是没账
    可查，**不等于**「这屋里没人」）。``affinity_db_path`` 只影响名字取否：取不到
    不影响「谁说过话」这件事本身，所以它坏了只降级成「没记下名字」，不谎报全态。
    """

    def __init__(
        self,
        *,
        history_db_path: str | Path = "",
        affinity_db_path: str | Path = "",
        row_window: int = ROW_WINDOW_DEFAULT,
    ) -> None:
        # 空串必须在这里就判掉：``Path("")`` 会变成 ``Path(".")``，而**路径对象恒为真**
        # ——直接 ``if not Path(...)` 的写法永远不成立，「配置没开记忆」那一态就会被
        # 挤到「库文件不在」上去（两态一混，运维看审计就找错方向）。
        raw_history = str(history_db_path or "").strip()
        raw_affinity = str(affinity_db_path or "").strip()
        self._history_path: Path | None = Path(raw_history) if raw_history else None
        self._affinity_path: Path | None = Path(raw_affinity) if raw_affinity else None
        self._row_window = max(1, int(row_window))

    # -- 对外唯一入口 -----------------------------------------------------
    def read(self, scope: ParticipantScope | None) -> ParticipantMemory:
        if scope is None or not scope.key:
            return ParticipantMemory(
                state=STATE_UNAVAILABLE,
                reason=REASON_BAD_SCOPE,
                row_window=self._row_window,
            )
        if self._history_path is None:
            # 配置没开历史记忆＝这台机器压根没有账本可查，与「账本在但读不出」是两件事，
            # 审计面必须分得开（前者运维要去看开关，后者要去看库文件）。
            return ParticipantMemory(
                state=STATE_UNAVAILABLE,
                reason=REASON_DB_DISABLED,
                row_window=self._row_window,
            )
        if not self._history_path.is_file():
            return ParticipantMemory(
                state=STATE_UNAVAILABLE,
                reason=REASON_DB_MISSING,
                row_window=self._row_window,
            )
        try:
            rows, scanned_at_cap = self._fetch_speakers(scope)
        except sqlite3.Error:
            # 表不存在与 SQL 出错都归「读不出」——它们都无权声称「没人」。
            return ParticipantMemory(
                state=STATE_UNAVAILABLE,
                reason=REASON_TABLE_MISSING
                if not self._table_present()
                else REASON_SQL_ERROR,
                row_window=self._row_window,
            )
        names = self._group_names(scope) if scope.is_group else {}
        records = tuple(
            ParticipantRecord(
                sender_id=record.sender_id,
                display_name=(names.get(record.sender_id) or "").strip(),
                turns=record.turns,
                last_seen=record.last_seen,
            )
            for record in rows
        )
        return ParticipantMemory(
            state=STATE_OK if records else STATE_EMPTY,
            records=records,
            total_speakers=len(records),
            window_exhausted=scanned_at_cap,
            row_window=self._row_window,
        )

    # -- 内部 --------------------------------------------------------------
    def _table_present(self) -> bool:
        path = self._history_path
        if path is None:
            return False
        try:
            with _open_read_only(path) as connection:
                return _table_exists(connection, _HISTORY_TABLE)
        except sqlite3.Error:
            return False

    def _fetch_speakers(self, scope: ParticipantScope) -> tuple[list[ParticipantRecord], bool]:
        """按作用域取「说过话的人」，返回 (按最近发言倒序的记录, 是否扫到窗口上限)。

        窗口与聚合分两步：**先按原始行**截窗（``LIMIT row_window + 1``，多取一行
        只为了知道「后面还有没有」），再在 Python 侧按人聚合。
        刻意不在 SQL 里 GROUP BY：那条 SQL 的 ``LIMIT`` 会先被聚合改写，
        「distinct 说话人数 ≥ row_window+1」根本不是「扫到行上限」的意思——
        窗口声明就成了假话。多取的那一行在判完上限后丢掉，只扫 row_window 行。
        """
        path = self._history_path
        if path is None:  # read() 已先判过；这一句只把类型收口，不新增行为。
            raise sqlite3.Error("history db path is not configured")
        with _open_read_only(path) as connection:
            if not _table_exists(connection, _HISTORY_TABLE):
                raise sqlite3.Error(f"{_HISTORY_TABLE} missing")
            kind_filter = _kind_filter(connection)
            where = (
                "substr(session_id, 1, ?) = ?"
                if scope.match == "prefix"
                else "session_id = ?"
            )
            params: list[Any] = (
                [len(scope.key), scope.key] if scope.match == "prefix" else [scope.key]
            )
            # substr 等值而不是 LIKE：LIKE 的 ``_`` 是单字符通配，需要额外转义
            # （转义器住在 shared_group.py 私有条目里，抄一份就是第二真身）；
            # substr 前缀比较没有通配语义，天然安全且与中央构造器逐字同构。
            #
            # role='user' 是这条读数的语义脊梁：本表也存机器人自己的回复
            # （role='assistant'，生产库实测两值齐），把 bot 算进「这个会话里的
            # 人」是答非所问，而且会让一个从没人说话的群报出「1 位」。
            sql = (
                "SELECT sender_id, created_at FROM conversation_turns"
                f"  WHERE {where} AND role = 'user' {kind_filter}"
                "  ORDER BY created_at DESC, rowid DESC LIMIT ?"
            )
            raw = connection.execute(
                sql, [*params, self._row_window + 1]
            ).fetchall()
        capped = len(raw) > self._row_window
        rows = raw[: self._row_window]
        grouped: dict[str, list[Any]] = {}
        for row in rows:  # 已按时间倒序：每人首见即最新，直接留第一次的 created_at。
            sender = str(row[0] or "")
            if not sender:
                continue
            bucket = grouped.setdefault(sender, [0, ""])
            bucket[0] += 1
            if not bucket[1]:
                bucket[1] = str(row[1] or "")
        records = sorted(
            (
                (last_seen, sender, turns)
                for sender, (turns, last_seen) in grouped.items()
            ),
            key=lambda item: (item[0], ),
            reverse=True,
        )
        return (
            [
                ParticipantRecord(
                    sender_id=sender,
                    display_name="",
                    turns=int(turns),
                    last_seen=last_seen,
                )
                for last_seen, sender, turns in records
            ],
            capped,
        )

    def _group_names(self, scope: ParticipantScope) -> dict[str, str]:
        """群内名字：``group_affinity.display_name``（唯一在册记录位，只读）。"""
        path = self._affinity_path
        if path is None or not path.is_file():
            return {}
        try:
            with _open_read_only(path) as connection:
                if not _table_exists(connection, _AFFINITY_NAME_TABLE):
                    return {}
                if "display_name" not in _columns(connection, _AFFINITY_NAME_TABLE):
                    return {}
                return {
                    str(row[0]): str(row[1] or "")
                    for row in connection.execute(
                        "SELECT sender_id, display_name FROM group_affinity"
                        " WHERE group_id = ?",
                        (scope.group_id,),
                    ).fetchall()
                }
        except sqlite3.Error:
            return {}


def build_participant_reader(config: Any) -> HistoryParticipantReader | None:
    """按配置造读数件；历史记忆没开就返回 ``None``（＝无账可查，不是「没人」）。

    门与写侧同源：``bot_history_enabled`` ∧ ``bot_history_db_path``——
    ``character/history.py:build_conversation_history_provider`` 用的正是这两枚，
    读侧放宽或收窄都会造成「写得进读不出」的第二套口径。
    路径字段在 ``config`` 里已过 ``path_fields`` 重映射（config.py:1563），
    所以这里不再二次解析。
    """
    enabled = bool(getattr(config, "bot_history_enabled", False))
    db_path = str(getattr(config, "bot_history_db_path", "") or "").strip()
    if not enabled or not db_path:
        return None
    affinity_path = str(getattr(config, "bot_affinity_db_path", "") or "").strip()
    return HistoryParticipantReader(
        history_db_path=db_path,
        affinity_db_path=affinity_path,
    )
