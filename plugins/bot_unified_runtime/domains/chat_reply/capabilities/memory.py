from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    PrivacyLevel,
    RiskLevel,
    SendPolicy,
    new_request_id,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.memory import (
    MEMORY_SENSITIVITIES,
    SQLiteMemoryRepository,
    build_fact_id,
    normalize_memory_sensitivity,
)
from plugins.bot_unified_runtime.domains.core.session_keys import (
    is_group_session_key,
)

# ---- 读侧中央入口（S-T-MEM-4，需求 11）-------------------------------------
#
# 为什么需要这一节：记忆总线开着时**新抽取只写 ``memory_entries_v21``**（写腿见
# ``memory_bus_v2.MemoryBus.absorb``），而仓里有三处在读旧表 ``memory_facts`` 的
# 消费面——命令面 ``记忆 list``、WebUI 记忆图谱、记忆隐私清洗。它们各自裸写
# ``SELECT ... FROM memory_facts``，开闸当天集体看不见新记录。
#
# 硬要求②「读侧判定走一个中央入口，不许三处各写一遍 if」的落法：
# - **「谁在用总线／写到哪张表」这个判定本席一次也不写**。它唯一的真身是
#   ``memory_bus_v2.build_memory_bus``/``settings_from_config``（开关
#   ``bot_memory_bus_enabled``），命令面只经由 ``SQLiteMemoryRepository(bus=…)``
#   这一个既有入口委托给它（该仓储的 docstring 自己写明「开关只在装配层判，
#   传了则写/删/读三面统一走总线」）。
# - 批量/管理侧（图谱、清洗）要的**不是**「读哪张表」的裁决，而是「这个库里物理
#   存在哪些记忆表、每行是什么形状」。本节的 ``iter_stored_memory_rows`` 就是
#   这**唯一一处**投影：它零配置读取、零开关判定，只按 ``sqlite_master`` 与
#   ``PRAGMA table_info`` 如实列举，墓碑行按真身口径一律排除（真身
#   ``MemoryStoreV21.list_entries`` 同判据：「恢复/复活也压不住」）。图谱与清洗
#   都调它，不各写一遍。
# - 「两表同库」是本节成立的前提，也是真身自己的口径（``build_memory_bus_for_writer``
#   的 docstring：召回侧与写入侧共用 ``bot_memory_db_path`` 的单一 store 连接，
#   「两条路永远看的是同一张表」）。由 ``tests/test_memory_read_side.py`` 现算锁死。
#
# 残余（不粉饰）：本函数应住在装配层 ``character/memory.py``（与
# ``legacy_explicit_reader_for`` 同层），本席文件面之外；搬动是纯搬迁——一处
# 定义、两个 import 点，无第二副本。移交主代理。

MEMORY_LEGACY_TABLE = "memory_facts"
MEMORY_BUS_TABLE = "memory_entries_v21"
MEMORY_TOMBSTONE_TABLE = "memory_tombstones_v21"

#: 状态 ``active`` 才是「会被读回」的行（真身召回口 ``list_bus_candidates`` 只取它）。
MEMORY_CURRENT_STATUS = "active"

#: 凭证级条目永不进任何**读侧回显**（命令面列表 / WebUI 图谱标签）。写侧另有同名
#: 红线（``memory_bus_v2.recall`` 的 ``credentialed`` 丢弃分支），两处判据同源与否
#: 由 ``tests/test_memory_read_side.py`` 现算比对，本席不另立第三套词表。
ECHO_UNSAFE_SENSITIVITIES = frozenset({"credentialed"})

_MINIMUM_TABLE_COLUMNS: Mapping[str, frozenset[str]] = {
    MEMORY_LEGACY_TABLE: frozenset({"fact_id", "subject_user_id", "text"}),
    MEMORY_BUS_TABLE: frozenset({"memory_id", "owner_id", "text"}),
}

# 逻辑字段名 → 表内列名；缺列按 ``_FIELD_DEFAULTS`` 如实补（老库可能没有
# sensitivity/scope/status 这些后加的列，缺就当成缺，不猜值）。
_LEGACY_FIELDS = {
    "row_id": "fact_id",
    "subject_user_id": "subject_user_id",
    "session_id": "session_id",
    "kind": "memory_kind",
    "text": "text",
    "sensitivity": "sensitivity",
    "status": "",
    "created_at": "created_at",
    "updated_at": "updated_at",
}
_BUS_FIELDS = {
    "row_id": "memory_id",
    "subject_user_id": "owner_id",
    "session_id": "session_id",
    "kind": "kind",
    "text": "text",
    "sensitivity": "sensitivity",
    "status": "status",
    "created_at": "created_at",
    "updated_at": "updated_at",
}
_TABLE_FIELDS = {
    MEMORY_LEGACY_TABLE: _LEGACY_FIELDS,
    MEMORY_BUS_TABLE: _BUS_FIELDS,
}
_FIELD_DEFAULTS = {"session_id": "", "kind": "fact", "sensitivity": "personal", "status": "active"}


@dataclass(frozen=True)
class StoredMemoryRow:
    """一张记忆表里的一行，投影成消费面要的统一形状（含来源表名，可判别可审计）。"""

    row_id: str
    subject_user_id: str
    session_id: str
    kind: str
    text: str
    sensitivity: str
    status: str
    created_at: str
    updated_at: str
    store_table: str

    @property
    def is_from_bus(self) -> bool:
        return self.store_table == MEMORY_BUS_TABLE


def _table_names(connection: sqlite3.Connection) -> set[str]:
    """库里的表名集合（``Row`` 与普通元组都按第 0 列取，不依赖 row_factory）。"""
    return {
        str(record[0])
        for record in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }


def memory_store_tables(connection: sqlite3.Connection) -> frozenset[str]:
    """本库里**物理存在**的记忆表（不含墓碑表/隔离表）。零配置读取。"""
    names = _table_names(connection)
    return frozenset(table for table in _TABLE_FIELDS if table in names)


def memory_tables_with_columns(
    connection: sqlite3.Connection,
    *,
    minimum_columns: Mapping[str, frozenset[str]] | None = None,
) -> frozenset[str]:
    """「这张表在、而且列齐到本消费面渲染得起」——判定只写这一处。

    缺列的表整张跳过，绝不拿默认值糊出一行来（糊出来就是造数）。空表但列齐仍算
    可渲染（返回该表名、行数为 0），否则「记忆库还没写过东西」会被误报成不可读。
    """
    required = {
        table: columns for table, columns in (minimum_columns or _MINIMUM_TABLE_COLUMNS).items()
        if table in _TABLE_FIELDS
    }
    tables: set[str] = set()
    for table in sorted(required):
        if table not in _table_names(connection):
            continue
        present = {str(record[1]) for record in connection.execute(f"PRAGMA table_info({table})")}
        if required[table] <= present:
            tables.add(table)
    return frozenset(tables)


def _row_from_record(
    table: str, fields: Mapping[str, str], values: Mapping[str, object], present: set[str]
) -> StoredMemoryRow:
    """一行 → ``StoredMemoryRow``；缺列按 ``_FIELD_DEFAULTS`` 如实补，不猜值。

    空串的归一**只**发生在 sensitivity 一处，且与真身同判据
    （``memory_bus_v2.recall`` 里是 ``row.get("sensitivity") or "personal"``、
    旧仓储 ``retrieve`` 里是 ``row["sensitivity"] or "personal"``）——
    ``status`` 一律原样给，空状态不当成 active（那是伪造可见性）。
    """

    def read(name: str) -> str:
        column = fields[name]
        if not column or column not in present:
            return _FIELD_DEFAULTS.get(name, "")
        raw = values.get(column)
        if raw is None:
            return _FIELD_DEFAULTS.get(name, "") if name == "sensitivity" else ""
        return str(raw) or _FIELD_DEFAULTS.get(name, "")

    return StoredMemoryRow(
        row_id=read("row_id"),
        subject_user_id=read("subject_user_id"),
        session_id=read("session_id"),
        kind=read("kind"),
        text=read("text"),
        sensitivity=read("sensitivity"),
        status=read("status"),
        created_at=read("created_at"),
        updated_at=read("updated_at"),
        store_table=table,
    )


def iter_stored_memory_rows(
    connection: sqlite3.Connection,
    *,
    minimum_columns: Mapping[str, frozenset[str]] | None = None,
) -> list[StoredMemoryRow]:
    """列举库里每张记忆表的每一行（墓碑行按真身口径排除，其余一律如实给）。

    ``minimum_columns`` 只用来放宽/收紧「某表列齐不齐、能不能渲染」，缺列的表整张
    跳过而不是拿默认值糊出一行——图谱用严格集（要有时间戳才能窗口过滤），清洗用
    宽松集（缺列也照样得扫，隐私清扫不因表形降级）。
    """
    required = minimum_columns or _MINIMUM_TABLE_COLUMNS
    renderable = memory_tables_with_columns(connection, minimum_columns=required)
    names = _table_names(connection)
    tombstones_ready = MEMORY_TOMBSTONE_TABLE in names
    rows: list[StoredMemoryRow] = []
    for table in sorted(renderable):
        fields = _TABLE_FIELDS[table]
        present = {str(record[1]) for record in connection.execute(f"PRAGMA table_info({table})")}
        wanted = sorted({column for column in fields.values() if column and column in present})
        columns = ", ".join(wanted)
        # 表名/列名全部来自本模块常量表，不经任何外部输入（图谱侧另有 mode=ro +
        # PRAGMA query_only 双保险）；ORDER BY rowid 只为确定性，消费面自己再排序。
        select_sql = f"SELECT {columns} FROM {table} ORDER BY rowid ASC"
        if table == MEMORY_BUS_TABLE and tombstones_ready:
            select_sql = (
                f"SELECT {columns} FROM {table} WHERE NOT EXISTS ("
                f"SELECT 1 FROM {MEMORY_TOMBSTONE_TABLE} t"
                f" WHERE t.memory_id = {table}.memory_id"
                ") ORDER BY rowid ASC"
            )
        for record in connection.execute(select_sql):
            # 按整数下标取值：Row 与默认元组两种 row_factory 都成立，不依赖调用方设置。
            values = {name: record[index] for index, name in enumerate(wanted)}
            row = _row_from_record(table, fields, values, present)
            if not row.row_id:
                continue
            rows.append(row)
    return rows


def is_current_memory_row(row: StoredMemoryRow) -> bool:
    """「这一行今天还算数吗」——只认 active（旧表行没有状态列，按 active 呈现）。"""
    return row.status == MEMORY_CURRENT_STATUS


def current_memory_rows(
    connection: sqlite3.Connection,
    *,
    minimum_columns: Mapping[str, frozenset[str]] | None = None,
) -> list[StoredMemoryRow]:
    return [row for row in iter_stored_memory_rows(connection, minimum_columns=minimum_columns) if is_current_memory_row(row)]


def is_echo_safe_sensitivity(value: str) -> bool:
    """读侧回显闸：凭证级条目不得出现在任何回显里（命令面列表 / 图谱标签）。"""
    return str(value or "").strip().casefold() not in ECHO_UNSAFE_SENSITIVITIES


def echo_safe_rows(rows: Sequence[StoredMemoryRow]) -> list[StoredMemoryRow]:
    return [row for row in rows if is_echo_safe_sensitivity(row.sensitivity)]


def route_memory_command(
    command_text: str,
    *,
    sender_id: str,
    session_id: str,
    db_path: str | Path,
    request_id: str | None = None,
    bus: object | None = None,
) -> CapabilityResult:
    """记忆命令面。``bus`` 由装配层给（根 ``__init__`` 经唯一判定口
    ``build_memory_bus_for_writer(config)``）——**本函数不读配置、不判开关**，
    ``bus=None`` 即逐字节旧行为；开态读/写/删三面统一由
    ``SQLiteMemoryRepository(bus=…)`` 委托给总线。
    """
    normalized = command_text.strip()
    if not db_path:
        return _memory_result(
            body="记忆功能还没打开。让管理员在 .env 里设 BOT_MEMORY_ENABLED=true 与 BOT_MEMORY_DB_PATH，重启后生效，再用 /bot status 确认。",
            request_id=request_id,
        )
    if normalized == "memory list":
        if is_group_session_key(session_id):
            return _list_memory(
                sender_id=sender_id,
                session_id=session_id,
                db_path=db_path,
                request_id=request_id,
                allowed_sensitivities={"public", "group"},
                bus=bus,
            )
        return _list_memory(
            sender_id=sender_id,
            session_id=session_id,
            db_path=db_path,
            request_id=request_id,
            allowed_sensitivities=None,
            bus=bus,
        )
    if normalized.startswith("memory add "):
        parsed_add = _parse_add_args(normalized.removeprefix("memory add ").strip())
        if parsed_add.error:
            return _memory_result(body=parsed_add.error, request_id=request_id)
        return _add_memory(
            text=parsed_add.text,
            sensitivity=parsed_add.sensitivity,
            sender_id=sender_id,
            session_id=session_id,
            db_path=db_path,
            request_id=request_id,
            bus=bus,
        )
    if normalized.startswith("memory delete "):
        fact_id = normalized.removeprefix("memory delete ").strip()
        return _delete_memory(
            fact_id=fact_id,
            sender_id=sender_id,
            session_id=session_id,
            db_path=db_path,
            request_id=request_id,
            bus=bus,
        )
    return _memory_result(
        body="用法：/bot memory add <内容>；/bot memory list；/bot memory delete <fact_id>",
        request_id=request_id,
    )


def is_memory_command_text(command_text: str) -> bool:
    return command_text.strip().startswith("memory")


# 群/私聊判定曾有本地副本 ``_is_group_session``，判据是 ``startswith("group:")``——
# 而真实摄取键是 NoneBot ``get_session_id()`` 的 ``group_<gid>_<uid>``（冒号形只活在
# 出站 SendRequest 与合成/smoke 路径）。判据与键形错配 ⇒ 群聊恒判私聊 ⇒ 个人敏感度
# 记忆被列进群聊。FIX5 起判据单一事实源 = domains/core/session_keys.py。


def _add_memory(
    *,
    text: str,
    sensitivity: str,
    sender_id: str,
    session_id: str,
    db_path: str | Path,
    request_id: str | None,
    bus: object | None = None,
) -> CapabilityResult:
    if not text:
        return _memory_result(body="记忆内容不能为空。", request_id=request_id)
    # ⚠ 回显与后续 delete 一律用**落库返回的真 id**，绝不再自算
    # （S-T-MEM-1 §陆②-bis 点名的缺陷）：总线按槽位合并，同一条偏好再说一次回到
    # 既有那行的 id（``mb_xxx``），而 ``build_fact_id`` 造的是 ``fact_xxx``——
    # 自算出来的那个 id 在库里根本不存在，``记忆 delete`` 会永远删不掉。
    # 旧路径 ``upsert_fact`` 原样返回入参 id ⇒ 关态回显逐字节不变。
    stored_id = SQLiteMemoryRepository(db_path, bus=bus).upsert_fact(
        fact_id=build_fact_id(sender_id, session_id, text),
        subject_user_id=sender_id,
        session_id=session_id,
        memory_kind="manual",
        text=text,
        confidence=1.0,
        source="manual_command",
        sensitivity=sensitivity,
    )
    return _memory_result(
        body=f"已记住：{text}\nfact_id={stored_id}\nsensitivity={sensitivity}",
        request_id=request_id,
    )


def _list_memory(
    *,
    sender_id: str,
    session_id: str,
    db_path: str | Path,
    request_id: str | None,
    allowed_sensitivities: set[str] | None,
    bus: object | None = None,
) -> CapabilityResult:
    memory = SQLiteMemoryRepository(db_path, bus=bus).retrieve(
        request_id=request_id or new_request_id("memory"),
        requester_id=sender_id,
        subject_user_id=sender_id,
        session_id=session_id,
        query_text="",
        max_items=20,
        max_chars=2000,
    )
    facts = [
        fact
        for fact in memory.facts
        if (
            # 读侧回显红线：凭证级条目**任何**场景都不列出来（含本人私聊）。
            # 关态这也是一处收紧——旧代码在私聊把 sensitivity='credentialed' 的行
            # 原样回显给命令发起者。收紧是有意的，登记在席位报告里。
            is_echo_safe_sensitivity(str(fact.get("sensitivity", "personal")))
            and (
                allowed_sensitivities is None
                or str(fact.get("sensitivity", "personal")) in allowed_sensitivities
            )
        )
    ]
    if not facts:
        if allowed_sensitivities is not None:
            return _memory_result(
                body="群聊中没有可公开查看的记忆；请在私聊中查看个人记忆。",
                request_id=memory.request_id,
            )
        return _memory_result(body="当前会话还没有可用记忆。", request_id=memory.request_id)
    lines = ["当前记忆："]
    lines.extend(
        f"- {fact['fact_id']}（sensitivity={fact.get('sensitivity', 'personal')}）：{fact['text']}"
        for fact in facts
    )
    return _memory_result(body="\n".join(lines), request_id=memory.request_id)


def _delete_memory(
    *,
    fact_id: str,
    sender_id: str,
    session_id: str,
    db_path: str | Path,
    request_id: str | None,
    bus: object | None = None,
) -> CapabilityResult:
    if not fact_id:
        return _memory_result(body="请提供要删除的 fact_id。", request_id=request_id)
    # 归属校验在委托的两层里各有一次：旧路径 SQL 带 ``subject_user_id = ?``，
    # 总线路径 ``MemoryBus.forget`` 先比 ``entry.owner_id`` 才落墓碑——本层不再
    # 自造第三套判据，只保证「删不掉就说删不掉」，不假装删除成功。
    deleted = SQLiteMemoryRepository(db_path, bus=bus).delete_fact(
        fact_id=fact_id,
        subject_user_id=sender_id,
        session_id=session_id,
    )
    if deleted:
        return _memory_result(body=f"已删除记忆：{fact_id}", request_id=request_id)
    return _memory_result(body=f"未找到可删除的记忆：{fact_id}", request_id=request_id)


def _memory_result(body: str, request_id: str | None = None) -> CapabilityResult:
    return CapabilityResult(
        request_id=request_id or new_request_id("memory"),
        capability_id="bot.memory",
        kind="text",
        title="记忆管理",
        body=body,
        risk_level=RiskLevel.LOW,
        privacy_level=PrivacyLevel.PERSONAL,
        send_policy=SendPolicy.IMMEDIATE,
        audit_tags=["memory_command"],
    )


class _ParsedAddArgs:
    def __init__(self, *, text: str, sensitivity: str, error: str = "") -> None:
        self.text = text
        self.sensitivity = sensitivity
        self.error = error


def _parse_add_args(raw_text: str) -> _ParsedAddArgs:
    sensitivity = "personal"
    text = raw_text
    prefix = "--sensitivity="
    if text.startswith(prefix):
        first, _, rest = text.partition(" ")
        try:
            sensitivity = normalize_memory_sensitivity(first.removeprefix(prefix))
        except ValueError:
            allowed = ", ".join(sorted(MEMORY_SENSITIVITIES))
            return _ParsedAddArgs(
                text="",
                sensitivity="personal",
                error=f"sensitivity 参数无效；可用值：{allowed}。",
            )
        text = rest.strip()
    return _ParsedAddArgs(text=text.strip(), sensitivity=sensitivity)
