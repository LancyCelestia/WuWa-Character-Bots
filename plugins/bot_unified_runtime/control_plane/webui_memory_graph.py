"""WebUI 记忆图谱只读服务（GET /api/v1/memory/graph）。

数据源与口径（全部只读，URI mode=ro + PRAGMA query_only，绝不写生产库）：

- ``history`` ← 对话史 SQLite（``conversation_turns``）：窗口内 turns 聚合
  出 人物×会话发言边（speaks_in）、群聊-会话 hosts 边（session id 按
  OneBot 约定 ``group_<gid>_<uid>`` 解析群号）；
- ``memory`` ← 长期记忆 SQLite：经**唯一**读侧入口
  ``capabilities/memory.current_memory_rows`` 取「这个库里物理存在的记忆表」
  （旧 ``memory_facts`` 与总线 ``memory_entries_v21`` 同在一个库文件里），人物-
  记忆归属边（about），窗口按 updated_at（缺省回退 created_at）；本件**不判总线
  开关**——开关唯一的真身在装配层，这里只如实列举存储里有什么；
- ``quirks`` ← 小习惯 SQLite（``persona_quirks``，仅 active）：规则节点；
  user 作用域（scope_key=人物）连人物-规则边（learned_rule），global 条目
  无人物归属事实 → 只给节点不硬造边；窗口按 created_at；
- 已学昵称 ← ``user_affinity.nickname``（≠空）：rule 节点 + nickname 边
  （昵称是当前态，不做窗口过滤）；
- ``affinity`` ← ``user_affinity.affinity``：人物节点 weight（当前态）。

图谱语义：窗口 ∈ {24h,7d,30d,all}；节点按 (度数降序, id 升序) 确定性
排序后按 max_nodes（≤200，默认 120）封顶，截断如实 truncated:true +
nodes_total（stats 恒为截断前总量，不因截断撒谎）。库缺失 = 该源标记
missing、对应 stats 0；全部缺失 = source_unavailable/all_sources_missing，
一律 200 信封内如实降级，不崩、不造数。标签按 affinity/board 先例直接
显值（WebUI 管理面板，Bearer 后台，2026-09-15 用户裁定）。
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.domains.chat_reply.capabilities.memory import (
    MEMORY_BUS_TABLE,
    MEMORY_LEGACY_TABLE,
    current_memory_rows,
    echo_safe_rows,
    memory_tables_with_columns,
)

from .factory import _path

__all__ = [
    "MemoryGraphService",
    "build_default_memory_graph_service",
]

_BUSY_TIMEOUT_SECONDS = 0.2
_QUERY_TIMEOUT_SECONDS = 1.0
_WINDOWS = {"24h": 86_400, "7d": 7 * 86_400, "30d": 30 * 86_400, "all": None}
_DEFAULT_MAX_NODES = 120
_MAX_NODES_CAP = 200
_LABEL_MAX_CHARS = 80

_HISTORY_COLUMNS = frozenset({"session_id", "sender_id", "created_at"})
_MEMORY_COLUMNS = frozenset(
    {"fact_id", "subject_user_id", "text", "created_at", "updated_at"}
)
#: 总线表的「渲染得起」列集：与 ``_MEMORY_COLUMNS`` 一一对应（memory_id→fact_id、
#: owner_id→subject_user_id），少任一列这张表整张跳过，不拿默认值糊一行。
_BUS_MEMORY_COLUMNS = frozenset(
    {"memory_id", "owner_id", "text", "created_at", "updated_at"}
)
_GRAPH_MINIMUM_COLUMNS = {
    MEMORY_LEGACY_TABLE: _MEMORY_COLUMNS,
    MEMORY_BUS_TABLE: _BUS_MEMORY_COLUMNS,
}
_QUIRK_COLUMNS = frozenset(
    {"quirk_id", "quirk_text", "status", "created_at", "scope_kind", "scope_key"}
)
_AFFINITY_COLUMNS = frozenset({"sender_id", "affinity", "nickname"})

_ZERO_STATS: dict[str, int] = {
    "persons": 0,
    "groups": 0,
    "conversations": 0,
    "long_term_memories": 0,
    "learned_rules": 0,
    "speaker_count": 0,
}


def _failure(status: str, reason: str, data: dict[str, Any] | None) -> dict[str, Any]:
    return {"status": status, "reason": reason, "data": data}


def _parse_utc(value: object) -> datetime | None:
    """ISO 文本 → aware UTC；无时区/畸形 = None（webui_stats 同款口径）。"""
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        return None
    if stamp.tzinfo is None:
        return None
    return stamp.astimezone(timezone.utc)


def _read_only_connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        path.as_uri() + "?mode=ro", uri=True, timeout=_BUSY_TIMEOUT_SECONDS
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA trusted_schema = OFF")
    return connection


def _table_ready(connection: sqlite3.Connection, table: str, columns: frozenset[str]) -> bool:
    tables = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    if table not in tables:
        return False
    actual = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
    return columns <= actual


def _in_window(stamp: datetime | None, cutoff: datetime | None) -> bool:
    """窗口判定：stamp 不可解析 → 仅 window=all 收录（不猜时间）。"""
    if cutoff is None:
        return True
    return stamp is not None and stamp >= cutoff


class MemoryGraphService:
    """记忆图谱聚合（对话史 + 长期记忆 + 小习惯/昵称 + 好感权重）。"""

    def __init__(
        self,
        *,
        history_db_path: str | Path,
        memory_db_path: str | Path,
        quirks_db_path: str | Path,
        affinity_db_path: str | Path,
    ) -> None:
        self._history_db_path = str(history_db_path or "")
        self._memory_db_path = str(memory_db_path or "")
        self._quirks_db_path = str(quirks_db_path or "")
        self._affinity_db_path = str(affinity_db_path or "")

    # -- 对外 ---------------------------------------------------------------

    def graph(self, window: str = "24h", max_nodes: int = _DEFAULT_MAX_NODES) -> dict[str, Any]:
        if not isinstance(window, str) or window not in _WINDOWS:
            return _failure("invalid_request", "invalid_window", None)
        if type(max_nodes) is not int or not 1 <= max_nodes <= _MAX_NODES_CAP:
            return _failure("invalid_request", "invalid_max_nodes", None)
        deadline = time.monotonic() + _QUERY_TIMEOUT_SECONDS
        window_seconds = _WINDOWS[window]
        cutoff = (
            None
            if window_seconds is None
            else datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
        )
        sources: dict[str, str] = {
            "history": "missing",
            "memory": "missing",
            "quirks": "missing",
            "affinity": "missing",
        }
        turns: list[tuple[str, str]] = []  # (session_id, sender_id) 窗口内
        facts: list[tuple[str, str, str]] = []  # (fact_id, subject, text)
        quirks: list[tuple[str, str, str, str]] = []  # (id, text, scope_kind, scope_key)
        affinity: dict[str, tuple[float | None, str]] = {}  # sender -> (值, 昵称)

        status, turn_rows = self._read_turns(cutoff)
        sources["history"] = status
        if turn_rows:
            turns = turn_rows
        status, fact_rows = self._read_facts(cutoff)
        sources["memory"] = status
        if fact_rows:
            facts = fact_rows
        status, quirk_rows = self._read_quirks(cutoff)
        sources["quirks"] = status
        if quirk_rows:
            quirks = quirk_rows
        status, affinity_rows = self._read_affinity()
        sources["affinity"] = status
        if affinity_rows:
            affinity = affinity_rows
        if time.monotonic() >= deadline:
            # 超预算：不产出半张图，如实整图不可用（不造部分结果）。
            return _failure(
                "source_unavailable",
                "query_budget_exceeded",
                self._empty_payload(window, max_nodes, sources),
            )
        return self._assemble(window=window, max_nodes=max_nodes, sources=sources,
                              turns=turns, facts=facts, quirks=quirks, affinity=affinity)

    # -- 各源只读 -----------------------------------------------------------

    def _read_turns(
        self, cutoff: datetime | None
    ) -> tuple[str, list[tuple[str, str]]]:
        if not self._history_db_path:
            return "missing", []
        try:
            path = Path(self._history_db_path).resolve()
            if not path.is_file():
                return "missing", []
            with closing(_read_only_connect(path)) as connection:
                connection.execute("BEGIN")
                if not _table_ready(connection, "conversation_turns", _HISTORY_COLUMNS):
                    return "unreadable", []
                rows: list[tuple[str, str]] = []
                for row in connection.execute(
                    "SELECT session_id, sender_id, created_at FROM conversation_turns"
                ):
                    if not _in_window(_parse_utc(row["created_at"]), cutoff):
                        continue
                    session = str(row["session_id"] or "")
                    sender = str(row["sender_id"] or "")
                    if session and sender:
                        rows.append((session, sender))
                return "ok", rows
        except (sqlite3.Error, OSError, ValueError, TypeError):
            return "unreadable", []

    def _read_facts(
        self, cutoff: datetime | None
    ) -> tuple[str, list[tuple[str, str, str]]]:
        if not self._memory_db_path:
            return "missing", []
        try:
            path = Path(self._memory_db_path).resolve()
            if not path.is_file():
                return "missing", []
            with closing(_read_only_connect(path)) as connection:
                connection.execute("BEGIN")
                # 记忆行只经由**一个**中央入口取（capabilities/memory 的读侧投影）：
                # 库里物理存在哪几张记忆表就看哪几张，本件不判总线开关、不写
                # 「if 开则读 v21」——那个判定唯一的真身在装配层，图谱是只读消费面。
                # 关态（只有 memory_facts 的库）逐字节等价于旧实现：同一张表、同一
                # 列集要求、同一时间戳回退口径；旧实现「表缺列 ⇒ unreadable」也原样
                # 保留（没有任何一张可渲染的记忆表时如实 unreadable，不造空图）。
                if not memory_tables_with_columns(
                    connection, minimum_columns=_GRAPH_MINIMUM_COLUMNS
                ):
                    return "unreadable", []
                out: list[tuple[str, str, str]] = []
                for row in echo_safe_rows(
                    current_memory_rows(connection, minimum_columns=_GRAPH_MINIMUM_COLUMNS)
                ):
                    stamp = _parse_utc(row.updated_at) or _parse_utc(row.created_at)
                    if not _in_window(stamp, cutoff):
                        continue
                    if row.row_id and row.subject_user_id:
                        out.append((row.row_id, row.subject_user_id, row.text))
                return "ok", out
        except (sqlite3.Error, OSError, ValueError, TypeError):
            return "unreadable", []

    def _read_quirks(
        self, cutoff: datetime | None
    ) -> tuple[str, list[tuple[str, str, str, str]]]:
        if not self._quirks_db_path:
            return "missing", []
        try:
            path = Path(self._quirks_db_path).resolve()
            if not path.is_file():
                return "missing", []
            with closing(_read_only_connect(path)) as connection:
                connection.execute("BEGIN")
                if not _table_ready(connection, "persona_quirks", _QUIRK_COLUMNS):
                    return "unreadable", []
                rows: list[tuple[str, str, str, str]] = []
                for row in connection.execute(
                    "SELECT quirk_id, quirk_text, status, created_at, scope_kind,"
                    " scope_key FROM persona_quirks"
                ):
                    if str(row["status"] or "") != "active":
                        continue
                    if not _in_window(_parse_utc(row["created_at"]), cutoff):
                        continue
                    quirk_id = str(row["quirk_id"] or "")
                    if quirk_id:
                        rows.append(
                            (
                                quirk_id,
                                str(row["quirk_text"] or ""),
                                str(row["scope_kind"] or "global"),
                                str(row["scope_key"] or ""),
                            )
                        )
                return "ok", rows
        except (sqlite3.Error, OSError, ValueError, TypeError):
            return "unreadable", []

    def _read_affinity(
        self,
    ) -> tuple[str, dict[str, tuple[float | None, str]]]:
        """当前态（好感值/已学昵称），不做窗口过滤。"""
        if not self._affinity_db_path:
            return "missing", {}
        try:
            path = Path(self._affinity_db_path).resolve()
            if not path.is_file():
                return "missing", {}
            with closing(_read_only_connect(path)) as connection:
                connection.execute("BEGIN")
                if not _table_ready(connection, "user_affinity", _AFFINITY_COLUMNS):
                    return "unreadable", {}
                rows: dict[str, tuple[float | None, str]] = {}
                for row in connection.execute(
                    "SELECT sender_id, affinity, nickname FROM user_affinity"
                ):
                    sender = str(row["sender_id"] or "")
                    if not sender:
                        continue
                    try:
                        value = (
                            float(row["affinity"]) if row["affinity"] is not None else None
                        )
                    except (TypeError, ValueError):
                        value = None
                    rows[sender] = (value, str(row["nickname"] or ""))
                return "ok", rows
        except (sqlite3.Error, OSError, ValueError, TypeError):
            return "unreadable", {}

    # -- 装配 ---------------------------------------------------------------

    def _empty_payload(self, window: str, max_nodes: int, sources: dict[str, str]) -> dict[str, Any]:
        return {
            "window": window,
            "max_nodes": max_nodes,
            "truncated": False,
            "nodes_total": 0,
            "stats": dict(_ZERO_STATS),
            "nodes": [],
            "edges": [],
            "sources": sources,
        }

    def _assemble(
        self,
        *,
        window: str,
        max_nodes: int,
        sources: dict[str, str],
        turns: list[tuple[str, str]],
        facts: list[tuple[str, str, str]],
        quirks: list[tuple[str, str, str, str]],
        affinity: dict[str, tuple[float | None, str]],
    ) -> dict[str, Any]:
        persons: dict[str, dict[str, Any]] = {}
        conversations: dict[str, int] = {}
        groups: dict[str, int] = {}

        for session, sender in turns:
            person = persons.setdefault(sender, {"turns": 0, "affinity": None, "nickname": ""})
            person["turns"] += 1
            conversations[session] = conversations.get(session, 0) + 1
            gid = self._group_of_session(session)
            if gid is not None:
                groups[gid] = groups.get(gid, 0) + 1
        # hosts 边：每会话一条，权重=该会话窗口内 turns 数。
        host_weights: dict[tuple[str, str], int] = {}
        for session, count in conversations.items():
            gid = self._group_of_session(session)
            if gid is not None:
                host_weights[(gid, session)] = count
        group_hosts = [(gid, session, n) for (gid, session), n in sorted(host_weights.items())]

        for sender, (value, nickname) in affinity.items():
            person = persons.setdefault(sender, {"turns": 0, "affinity": None, "nickname": ""})
            person["affinity"] = value
            person["nickname"] = nickname

        speaker_count = sum(1 for person in persons.values() if person["turns"] > 0)
        learned_rules = len(quirks) + sum(
            1 for person in affinity.values() if person[1].strip()
        )

        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []

        def add_edge(source: str, target: str, kind: str, weight: int) -> None:
            edges.append({"source": source, "target": target, "kind": kind, "weight": weight})

        for sender in sorted(persons):
            person = persons[sender]
            weight = person["affinity"]
            nodes.append(
                {
                    "id": f"person:{sender}",
                    "type": "person",
                    "label": person["nickname"] or sender,
                    "weight": round(weight, 4) if weight is not None else None,
                }
            )
        for gid in sorted(groups):
            nodes.append(
                {
                    "id": f"group:{gid}",
                    "type": "group",
                    "label": f"群 {gid}",
                    "weight": groups[gid],
                }
            )
        for session in sorted(conversations):
            nodes.append(
                {
                    "id": f"conv:{session}",
                    "type": "conversation",
                    "label": session,
                    "weight": conversations[session],
                }
            )
        for fact_id, subject, text in sorted(facts):
            nodes.append(
                {
                    "id": f"memory:{fact_id}",
                    "type": "memory",
                    "label": text.strip()[:_LABEL_MAX_CHARS],
                    "weight": 1,
                }
            )
        for quirk_id, quirk_text, _kind, _key in sorted(quirks):
            nodes.append(
                {
                    "id": f"rule:quirk:{quirk_id}",
                    "type": "rule",
                    "label": quirk_text.strip()[:_LABEL_MAX_CHARS],
                    "weight": 1,
                }
            )
        for sender in sorted(affinity):
            nickname = affinity[sender][1].strip()
            if nickname:
                nodes.append(
                    {
                        "id": f"rule:nick:{sender}",
                        "type": "rule",
                        "label": f"已学昵称：{nickname}",
                        "weight": 1,
                    }
                )

        person_turns: dict[str, dict[str, int]] = {}
        for session, sender in turns:
            bucket = person_turns.setdefault(sender, {})
            bucket[session] = bucket.get(session, 0) + 1
        for sender in sorted(person_turns):
            for session in sorted(person_turns[sender]):
                add_edge(
                    f"person:{sender}",
                    f"conv:{session}",
                    "speaks_in",
                    person_turns[sender][session],
                )
        for gid, session, weight in group_hosts:
            add_edge(f"group:{gid}", f"conv:{session}", "hosts", weight)
        for fact_id, subject, _text in sorted(facts):
            add_edge(f"person:{subject}", f"memory:{fact_id}", "about", 1)
        for quirk_id, _text, kind, key in sorted(quirks):
            # user 作用域（scope_key=人物）才有归属事实；global 不硬造边。
            if kind == "user" and key in persons:
                add_edge(f"person:{key}", f"rule:quirk:{quirk_id}", "learned_rule", 1)
        for sender in sorted(affinity):
            if affinity[sender][1].strip():
                add_edge(f"person:{sender}", f"rule:nick:{sender}", "nickname", 1)

        degrees: dict[str, int] = {}
        for edge in edges:
            degrees[edge["source"]] = degrees.get(edge["source"], 0) + 1
            degrees[edge["target"]] = degrees.get(edge["target"], 0) + 1
        nodes.sort(key=lambda node: (-degrees.get(node["id"], 0), node["id"]))
        edges.sort(key=lambda edge: (edge["source"], edge["target"], edge["kind"]))

        nodes_total = len(nodes)
        truncated = nodes_total > max_nodes
        if truncated:
            kept = {node["id"] for node in nodes[:max_nodes]}
            nodes = nodes[:max_nodes]
            edges = [
                edge
                for edge in edges
                if edge["source"] in kept and edge["target"] in kept
            ]

        any_ok = any(status == "ok" for status in sources.values())
        payload = {
            "window": window,
            "max_nodes": max_nodes,
            "truncated": truncated,
            "nodes_total": nodes_total,
            "stats": {
                "persons": len(persons),
                "groups": len(groups),
                "conversations": len(conversations),
                "long_term_memories": len(facts),
                "learned_rules": learned_rules,
                "speaker_count": speaker_count,
            },
            "nodes": nodes,
            "edges": edges,
            "sources": sources,
        }
        if any_ok:
            return {"status": "ok", "source": "memory_graph", "data": payload}
        return _failure("source_unavailable", "all_sources_missing", payload)

    @staticmethod
    def _group_of_session(session: str) -> str | None:
        """OneBot 约定 ``group_<gid>_<uid>`` → gid；约定外（私聊等）None。"""
        parts = session.split("_")
        if len(parts) == 3 and parts[0] == "group" and parts[1].isdigit():
            return parts[1]
        return None


def build_default_memory_graph_service(config: object | None) -> MemoryGraphService:
    """按 config 解析默认库路径（与 _app 默认装配同一套 runtime 重映射）。"""

    def resolve(attr: str) -> str:
        raw = str(getattr(config, attr, "") or "").strip()
        return str(_path(raw)) if raw else ""

    return MemoryGraphService(
        history_db_path=resolve("bot_history_db_path"),
        memory_db_path=resolve("bot_memory_db_path"),
        quirks_db_path=resolve("bot_quirks_db_path"),
        affinity_db_path=resolve("bot_affinity_db_path"),
    )
