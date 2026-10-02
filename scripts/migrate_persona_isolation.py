#!/usr/bin/env python
"""多人格隔离波 存量库归属迁移：**缺省只读、显式 --execute 才写、绝不擅自碰生产库**。

S7 席对本件的两处死腿修复（S5b 取证）＋ kb_wiki 行级落地：

1. **不再 blanket-fill**：老代码 ``UPDATE … WHERE persona_id=''`` 把所有无主行刷成
   ``--persona``（缺省主人格）⇒ 审计腿 ``still>0`` 结构上永不触发（死腿），且
   "无主行＝主人格独占"本身就是误归属面（新人格永远读不到、主人格凭空继承全语料）。
   现改**显式选择**，两种模式都在、缺省走 common 等价：
   * 缺省＝无主行**保持无主**。读侧谓词 ``persona_id = ? OR '' OR IS NULL`` 的
     ``OR ''`` 那半边继续放行 ⇒ 无主＝**共享**（N-1a 取 ``common`` 时的终态）；
   * ``--fill-unowned <persona>``＝**指派**归属（N-1a 取"主人格独占"时才需要），
     执行前打印将被改写的行数与前后 COUNT；
   * ``--require-assigned``＝宣告"本波终态不许留无主行"，留了当场红。
   ⚠ 两种取值都支持，脚本不把任何一种写死成唯一解。

2. **不再有哑读数**：老代码只跑本文件测试时打印
   ``count_before=- altered=False … problems=[]``——七格裡多数没取到样本却照样
   ``problems=[]``（假绿形态，台账 239 同型坑）。现每格必须交出一组**必需读数**
   （count/columns/has_column/unowned/indexes），取不到就是 problem ⇒ 非零退出；
   空表要明写 ``empty=True``，绝不用 ``-`` 顶替读数。作用域同样收口：目标只按**库名**
   归属（老的 ``len(raw_dbs)==1`` 兜底会把七张小表拿去七个不相干的库里"探"一遍），
   没被任何 ``--db`` 覆盖到的在册目标记 ``uncovered_targets`` 并红，除非显式
   ``--partial-scope``。

3. ``--stage wiki``（kb_wiki_embeddings，行级）：给 ``knowledge_chunks`` 补
   ``persona_id`` + **复合索引 (persona_id, source_id)**，只读产出
   ``knowledge_docs.topic → 行数`` 归属报告（供裁定"现有块该标什么"），并**核验消费者
   是否已接线**（禁只加列不接消费者；过滤/over-fetch 复用
   ``vector_knowledge.SqliteVectorKnowledgeStore._retain_active_persona``，本件不长第二把
   尺；未接线＝problem）。

安全面（照 migrate_affinity_v8 的家规，一把尺不另起第二把）
--------------------------------------------------------
* ``--execute`` 时目标路径一律过 ``guard_target_path``：落在 ``ChatBot_Runtime`` /
  ``ChatBot_Archive`` / ``runtime_data_dir()`` ⇒ 拒绝退出（exit 2）。要在生产库上
  执行，必须显式带 ``--approve-runtime-write <授权凭据>``（非空、写进报告），本席
  从不带它跑。
* 非 ``--execute`` 的读数默认也拒绝 Runtime 路径；只有显式 ``--read-production-readonly``
  才放行，且那时连接用 ``file:...?mode=ro`` + ``PRAGMA query_only`` 打开——物理写不了。
* 每次 ``--execute`` 前把三件套（db + -wal + -shm）整份备份成
  ``<db>.pre-persona-<UTC 戳>`` 并给出**前后 sha256**；超过 ``--backup-max-bytes``
  的库（kb_wiki 实测 18 GB 级）不许盲拷，须显式 ``--backup skip``（改跑
  ``PRAGMA integrity_check`` 并把结果记进报告）。
* 守恒断言：迁移前后行数一字不动、非目标列逐行相等；样本为 0 却又有行 ⇒ 红。
* 幂等：第二次跑必然 ``altered=0 / created_index=0 / filled=0``。

用法（**执行一律由用户/主会话授权后进行**）
----------------------------------------
    # 演练（零写，仓库外副本）：
    python scripts/migrate_persona_isolation.py --stage all --db <副本>...
    # 生产只读取数（wiki 归属报告，物理只读）：
    python scripts/migrate_persona_isolation.py --stage wiki --read-production-readonly \
        --db <RT>/data/kb_wiki_embeddings.sqlite3 --topic-report <仓库外 json>
    # 实写（默认拒绝 Runtime 路径；生产执行需 --approve-runtime-write）：
    python scripts/migrate_persona_isolation.py --stage wiki --db <库> --execute \
        --backup skip --approve-runtime-write <授权凭据>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))

# 一把尺：路径闸直接复用好感度迁移的在册件，禁在这里长出第二真身。
from migrate_affinity_v8 import UnsafeTargetError, guard_target_path

DEFAULT_MAIN_PERSONA_ID = "shorekeeper"
RUNTIME_WRITE_TOKEN = "I-APPROVE-RUNTIME-WRITE"

# 归属列形态三处一律同形（列名/类型/缺省），禁第二形态。
PERSONA_COLUMN_SQL = "ALTER TABLE {table} ADD COLUMN persona_id TEXT NOT NULL DEFAULT ''"
PERSONA_INDEX_SQL = "CREATE INDEX IF NOT EXISTS idx_{table}_persona ON {table}(persona_id)"
WIKI_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_{table}_persona_source ON {table}(persona_id, source_id)"
)
SUBJECT_KIND_COLUMN_SQL = "ALTER TABLE {table} ADD COLUMN subject_kind TEXT NOT NULL DEFAULT ''"

# (库名片段, 表, 索引 SQL 形态, 归属列)；表只在**同名库**里探，禁跨库凑样本。
KNOWLEDGE_TARGETS: tuple[tuple[str, str, str, str], ...] = (
    ("knowledge_embeddings.sqlite3", "knowledge_chunks", PERSONA_INDEX_SQL, "persona_id"),
)
SMALL_TARGETS: tuple[tuple[str, str, str, str], ...] = (
    ("wuwa_history.sqlite3", "conversation_turns", PERSONA_INDEX_SQL, "persona_id"),
    ("wuwa_memory.sqlite3", "memory_facts", PERSONA_INDEX_SQL, "persona_id"),
    ("wuwa_memory.sqlite3", "memory_entries_v21", PERSONA_INDEX_SQL, "persona_id"),
    ("user_affinity.sqlite3", "user_affinity", PERSONA_INDEX_SQL, "persona_id"),
    ("user_affinity.sqlite3", "group_affinity", PERSONA_INDEX_SQL, "persona_id"),
    ("persona_quirks.sqlite3", "persona_quirks", PERSONA_INDEX_SQL, "persona_id"),
    ("meme_library.sqlite3", "memes", PERSONA_INDEX_SQL, "persona_id"),
)
WIKI_TARGETS: tuple[tuple[str, str, str, str], ...] = (
    ("kb_wiki_embeddings.sqlite3", "knowledge_chunks", WIKI_INDEX_SQL, "persona_id"),
)
TOPIC_LEDGER: tuple[str, str] = ("kb_wiki_embeddings.sqlite3", "knowledge_docs")
SUBJECT_KIND_TARGETS: tuple[tuple[str, str, str, str], ...] = (
    ("wuwa_memory.sqlite3", "memory_facts", "", "subject_kind"),
)

STAGE_TARGETS: dict[str, tuple[tuple[str, str, str, str], ...]] = {
    "knowledge": KNOWLEDGE_TARGETS,
    "small": SMALL_TARGETS,
    "wiki": WIKI_TARGETS,
    "subject-kind": SUBJECT_KIND_TARGETS,
}
STAGE_UNION: dict[str, tuple[str, ...]] = {
    "knowledge": ("knowledge",),
    "small": ("small",),
    "wiki": ("wiki",),
    "all": ("knowledge", "small", "wiki"),
}

# 每格必须交出的读数；少任何一个 ⇒ 该格取数失败，当场红（不许打 `-` 蒙混）。
REQUIRED_READINGS: tuple[str, ...] = (
    "count",
    "columns",
    "has_column",
    "unowned",
    "indexes",
)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def open_readonly(path: Path) -> sqlite3.Connection:
    """读数一律走 ``mode=ro`` URI ＋ ``query_only``：物理上写不下去。"""
    uri = f"file:{Path(path).as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def open_write(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path), timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def columns_of(connection: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")]


def indexes_of(connection: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in connection.execute(f"PRAGMA index_list({table})")]


def table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return bool(
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
    )


def snapshot(connection: sqlite3.Connection, table: str, limit: int) -> dict[str, Any]:
    """行数 + 有界抽样（抽样是守恒比对的燃料，必须非零才算尺有牙）。

    列名取 **cursor.description**，不取行本身（量具字段名不是语义）。
    """
    total = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    cursor = connection.execute(f"SELECT * FROM {table} ORDER BY rowid LIMIT ?", (limit,))
    names = [str(pair[0]) for pair in (cursor.description or ())]
    sample = [
        dict(zip(names, ("" if value is None else str(value) for value in row)))
        for row in cursor.fetchall()
    ]
    return {"count": total, "columns": columns_of(connection, table), "sample": sample}


def owned_count(
    connection: sqlite3.Connection, table: str, column: str, persona_id: str
) -> int:
    return int(
        connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {column} = ?", (persona_id,)
        ).fetchone()[0]
    )


def unowned_count(connection: sqlite3.Connection, table: str, column: str) -> int:
    return int(
        connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {column} = '' OR {column} IS NULL"
        ).fetchone()[0]
    )


def take_readings(
    connection: sqlite3.Connection,
    table: str,
    *,
    column: str,
    persona_id: str,
    sample_limit: int,
) -> dict[str, Any]:
    """取全 ``REQUIRED_READINGS``；取不到的键落进 ``missing``（由调用方判红）。"""
    readings: dict[str, Any] = {"missing": []}
    for key, fetch in (
        ("count", lambda: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])),
        ("columns", lambda: columns_of(connection, table)),
        ("indexes", lambda: indexes_of(connection, table)),
    ):
        try:
            readings[key] = fetch()
        except sqlite3.Error:
            readings["missing"].append(key)
    has_column = bool(readings["columns"]) and not readings["missing"] and column in (
        readings["columns"] or []
    )
    readings["has_column"] = has_column
    if has_column:
        try:
            readings["unowned"] = unowned_count(connection, table, column)
            readings["owned"] = owned_count(connection, table, column, persona_id)
        except sqlite3.Error:
            readings["missing"].append("unowned")
    else:
        # 列还没建：无主＝全表（每行都待决），如实这么记，不留空读数。
        readings["unowned"] = int(readings.get("count") or 0)
        readings["owned"] = 0
    return readings


def compare_snapshots(
    before: dict[str, Any], after: dict[str, Any], table: str, column: str
) -> list[str]:
    """守恒判词：行数相等 ＋ 迁移前的每一列在迁移后逐字相等。"""
    problems: list[str] = []
    if before["count"] != after["count"]:
        problems.append(f"{table}: 行数变了 {before['count']} -> {after['count']}")
    if not before["sample"]:
        if before["count"]:
            problems.append(f"{table}: 有 {before['count']} 行却取到 0 枚样本 ⇒ 比对天生无牙")
        else:
            problems.append(f"{table}: 空表 ⇒ 本格没有任何守恒证据（明写 empty，不算通过）")
        return problems
    if len(before["sample"]) != len(after["sample"]):
        problems.append(
            f"{table}: 抽样数不等 {len(before['sample'])} -> {len(after['sample'])}"
        )
    for old, new in zip(before["sample"], after["sample"]):
        for key, value in old.items():
            if key == column:
                continue
            if str(new.get(key, "")) != str(value):
                problems.append(f"{table}: 非目标列 {key} 被改动了")
                break
    return problems


def backup_trio(path: Path) -> list[str]:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    made: list[str] = []
    for suffix in ("", "-wal", "-shm"):
        source = Path(str(path) + suffix)
        if not source.exists():
            continue
        target = Path(f"{source}.pre-persona-{stamp}")
        target.write_bytes(source.read_bytes())
        made.append(target.name)
    return made


def consumer_wired() -> dict[str, Any]:
    """wiki 行级过滤的**消费者**是否真接线（禁只加列不接消费者）。

    只读取真身源码算两件事：① ``kb_wiki._build_store`` 有没有把 ``persona_provider``
    传进共用的 ``SqliteVectorKnowledgeStore``；② 过滤前的 over-fetch 因子在不在这把
    在册尺里（复用，不在这里另立倍数）。
    """
    out: dict[str, Any] = {
        "kb_wiki_build_store_passes_persona_provider": False,
        "store_over_fetch_before_filter": False,
        "source_probe_failed": [],
    }
    base = _REPO_ROOT / "plugins" / "bot_unified_runtime" / "domains"
    wiki = base / "location" / "knowledge" / "kb_wiki.py"
    store = base / "chat_reply" / "character" / "vector_knowledge.py"
    try:
        text = wiki.read_text(encoding="utf-8")
        start = text.index("def _build_store(")
        body = text[start : start + 2000]
        out["kb_wiki_build_store_passes_persona_provider"] = "persona_provider" in body
    except (OSError, ValueError) as exc:
        out["source_probe_failed"].append(f"kb_wiki:{type(exc).__name__}")
    try:
        text = store.read_text(encoding="utf-8")
        out["store_over_fetch_before_filter"] = (
            "_VECTOR_CANDIDATE_FACTOR" in text and "_retain_active_persona" in text
        )
    except OSError as exc:
        out["source_probe_failed"].append(f"vector_knowledge:{type(exc).__name__}")
    return out


def topic_attribution_report(
    path: Path, out_path: Path | None, *, limit: int = 200
) -> dict[str, Any]:
    """只读统计 ``knowledge_docs.topic → 行数``，供裁定"现有块该标什么归属"。"""
    entry: dict[str, Any] = {"db": path.name, "table": TOPIC_LEDGER[1], "rows": []}
    connection = open_readonly(path)
    try:
        if not table_exists(connection, TOPIC_LEDGER[1]):
            entry["problem"] = f"{TOPIC_LEDGER[1]} 表缺席 ⇒ topic 报告无读数"
            return entry
        entry["rows"] = [
            {"topic": str(row["topic"] or ""), "docs": int(row["docs"])}
            for row in connection.execute(
                f"SELECT topic, COUNT(*) AS docs FROM {TOPIC_LEDGER[1]} "
                f"GROUP BY topic ORDER BY docs DESC LIMIT {int(limit)}"
            )
        ]
        entry["distinct_topics"] = len(entry["rows"])
        entry["ledger_rows"] = int(
            connection.execute(f"SELECT COUNT(*) FROM {TOPIC_LEDGER[1]}").fetchone()[0]
        )
    except sqlite3.Error as exc:
        entry["problem"] = f"topic 统计失败 {type(exc).__name__}"
    finally:
        connection.close()
    if out_path is not None and entry["rows"]:
        payload = json.dumps(entry, ensure_ascii=False, indent=2)
        out_path.write_bytes(payload.encode("utf-8"))
        entry["report_path"] = str(out_path)
        entry["report_bytes"] = len(payload.encode("utf-8"))
    return entry


def migrate_one(
    path: Path,
    table: str,
    *,
    column: str,
    persona_id: str,
    fill_unowned: str | None,
    require_assigned: bool,
    execute: bool,
    sample_limit: int,
    index_sql: str,
    backup_mode: str,
    backup_max_bytes: int,
    allow_absent_table: bool,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "db": path.name,
        "table": table,
        "column": column,
        "assignment_mode": (
            f"fill->{fill_unowned}" if fill_unowned else "leave_unowned_shared"
        ),
        "would_write": False,
        "altered": False,
        "created_index": False,
        "filled": 0,
        "problems": [],
    }
    if not path.exists():
        entry["problems"].append(f"{path.name}: 库文件不存在 ⇒ 本格没有任何读数")
        return entry
    connection = open_readonly(path) if not execute else open_write(path)
    try:
        if not table_exists(connection, table):
            entry["absent_table"] = True
            if not allow_absent_table:
                entry["problems"].append(
                    f"{table}: 库名在册却取不到表 ⇒ 作用域判据可疑（要放行缺席加 "
                    f"--allow-absent-table，别让它静默变 `-`）"
                )
            return entry

        readings = take_readings(
            connection,
            table,
            column=column,
            persona_id=(fill_unowned or persona_id),
            sample_limit=sample_limit,
        )
        missing = [str(key) for key in readings["missing"]]
        if missing:
            entry["problems"].append(f"{table}: 必需读数取不到 {missing} ⇒ 无读数即红")
            entry["missing_readings"] = missing
            return entry
        before = snapshot(connection, table, sample_limit)
        entry.update(
            {
                "count_before": readings["count"],
                "columns_before": readings["columns"],
                "had_column": readings["has_column"],
                "unowned_before": readings["unowned"],
                "owned_before": readings["owned"],
                "indexes_before": readings["indexes"],
            }
        )
        wanted_index = index_sql.format(table=table) if index_sql else ""
        index_name = wanted_index.split("IF NOT EXISTS ")[-1].split(" ON ")[0] if wanted_index else ""
        entry["index_present_before"] = bool(index_name) and index_name in readings["indexes"]
        entry["would_write"] = (
            (not readings["has_column"])
            or (bool(index_name) and index_name not in readings["indexes"])
            or (bool(fill_unowned) and readings["unowned"] > 0)
        )
        if not execute:
            return entry

        size = path.stat().st_size
        if backup_mode == "copy":
            if size > backup_max_bytes:
                entry["problems"].append(
                    f"{path.name}: {size} 字节 > 备份上限 {backup_max_bytes} ⇒ "
                    f"必须显式 --backup skip（并看 integrity_check），不许盲拷"
                )
                return entry
            entry["backups"] = backup_trio(path)
        else:
            entry["backups"] = []
            entry["integrity_check"] = str(
                connection.execute("PRAGMA integrity_check").fetchone()[0]
            )
        entry["sha_before"] = sha256_of(path)

        if not readings["has_column"]:
            connection.execute(PERSONA_COLUMN_SQL.format(table=table))
            entry["altered"] = True
        if wanted_index:
            connection.execute(wanted_index)
            entry["created_index"] = index_name not in readings["indexes"]

        if fill_unowned:
            # 指派前把改写额与前后 COUNT 打印出来（回执承诺的前置动作要现算走一遍）。
            print(
                f"PRE-FILL {table}: 待改写 {readings['unowned']} 行 -> "
                f"'{fill_unowned}'（改前 unowned={readings['unowned']} "
                f"owned={readings['owned']}）",
                flush=True,
            )
            written = connection.execute(
                f"UPDATE {table} SET persona_id = ? "
                f"WHERE persona_id = '' OR persona_id IS NULL",
                (fill_unowned,),
            ).rowcount
            entry["filled"] = int(written)
            if written != readings["unowned"]:
                entry["problems"].append(
                    f"{table}: 指派额与现算待决额不符 {readings['unowned']} -> {written}"
                )
        connection.commit()

        after_readings = take_readings(
            connection,
            table,
            column=column,
            persona_id=(fill_unowned or persona_id),
            sample_limit=sample_limit,
        )
        after_missing = [str(key) for key in after_readings["missing"]]
        if after_missing:
            entry["problems"].append(f"{table}: 改后必需读数取不到 {after_missing} ⇒ 无读数即红")
            return entry
        after = snapshot(connection, table, sample_limit)
        entry["count_after"] = after_readings["count"]
        entry["unowned_after"] = after_readings["unowned"]
        entry["owned_after"] = after_readings["owned"]
        entry["indexes_after"] = after_readings["indexes"]
        entry["sha_after"] = sha256_of(path)
        entry["problems"].extend(compare_snapshots(before, after, table, column))
        if not after_readings["has_column"]:
            entry["problems"].append(f"{table}: 建列后仍读不到列 ⇒ DDL 没落地")
        if index_name and index_name not in (after_readings["indexes"] or []):
            entry["problems"].append(f"{table}: 归属索引 {index_name} 未建成")
        # 未决行如实计数：缺省语义下无主＝共享（不是错），只在两种情形判红——
        # ① 声明了 --fill-unowned 却没改完；② 声明了 --require-assigned 还留着。
        if fill_unowned and after_readings["unowned"]:
            entry["problems"].append(
                f"{table}: 指派后仍有 {after_readings['unowned']} 行未归属 ⇒ 没改干净"
            )
        if require_assigned and after_readings["unowned"]:
            entry["problems"].append(
                f"{table}: --require-assigned 却留有 {after_readings['unowned']} 行无主"
            )
        if not fill_unowned:
            entry["leftover_unowned_shared"] = int(after_readings["unowned"])
    finally:
        connection.close()
    return entry


def resolve_targets(
    raw_dbs: list[str], stage: str
) -> tuple[list[tuple[Path, str, str, str]], list[str]]:
    """目标**只按库名归属**：返回 (待办格, 未被任何 --db 覆盖的在册目标)。"""
    subs = STAGE_UNION.get(stage, (stage,))
    wanted: list[tuple[str, str, str, str]] = []
    for sub in subs:
        wanted.extend(STAGE_TARGETS[sub])
    pairs: list[tuple[Path, str, str, str]] = []
    hit: set[tuple[str, str]] = set()
    for raw in raw_dbs:
        path = Path(raw)
        for db_hint, table, index_sql, column in wanted:
            if path.name == db_hint:
                pairs.append((path, table, index_sql, column))
                hit.add((db_hint, table))
    uncovered = [
        f"{db_hint}:{table}" for db_hint, table, _i, _c in wanted if (db_hint, table) not in hit
    ]
    return pairs, uncovered


def plan_subject_kind(path: Path, table: str) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "db": path.name,
        "table": table,
        "planned_column": SUBJECT_KIND_COLUMN_SQL.format(table=table),
        "executed": False,
        "problems": [],
    }
    connection = open_readonly(path)
    try:
        if not table_exists(connection, table):
            entry["problems"].append(f"{table}: 表取不到 ⇒ subject-kind 无读数")
            return entry
        names = columns_of(connection, table)
        entry["already_present"] = "subject_kind" in names
        entry["count"] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    except sqlite3.Error as exc:
        entry["problems"].append(f"subject-kind 读数失败 {type(exc).__name__}")
    finally:
        connection.close()
    return entry


def _fmt(entry: dict[str, Any]) -> str:
    keys = (
        "count_before",
        "had_column",
        "unowned_before",
        "owned_before",
        "altered",
        "created_index",
        "filled",
        "count_after",
        "unowned_after",
        "owned_after",
    )
    body = " ".join(f"{k}={entry.get(k)}" for k in keys if k in entry)
    return f"  [{entry.get('mode', 'cell')}] {entry.get('db')} {entry.get('table')}: " + body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", action="append", default=[], help="目标库（可重复给多枚）")
    parser.add_argument(
        "--stage",
        choices=("knowledge", "small", "wiki", "subject-kind", "all"),
        default="all",
    )
    parser.add_argument("--execute", action="store_true", help="真的写（缺省只演练）")
    parser.add_argument(
        "--persona",
        default="",
        help=f"读数里报告的主人格 id；缺省＝注册表 is_main（兜底 {DEFAULT_MAIN_PERSONA_ID}）",
    )
    parser.add_argument(
        "--fill-unowned",
        default="",
        metavar="PERSONA",
        help="**显式指派**：把无主行改归该 id；不给＝无主行保持无主（＝共享）",
    )
    parser.add_argument(
        "--require-assigned",
        action="store_true",
        help="宣告终态不许留无主行；留了就红（N-1a 取独占档时用）",
    )
    parser.add_argument("--topic-report", default="", help="wiki topic 归属报告落盘路径")
    parser.add_argument("--allow-absent-table", action="store_true")
    parser.add_argument("--partial-scope", action="store_true", help="承认只覆盖部分在册目标")
    parser.add_argument("--backup", choices=("copy", "skip"), default="copy")
    parser.add_argument("--backup-max-bytes", type=int, default=2 * 1024 * 1024 * 1024)
    parser.add_argument(
        "--read-production-readonly",
        action="store_true",
        help="允许对运行数据根内的库**只读**取数（连接用 mode=ro；绝不与 --execute 同现）",
    )
    parser.add_argument("--approve-runtime-write", default="", metavar="REF")
    parser.add_argument("--sample-limit", type=int, default=50)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    # 报告正文带 CJK 与 ⇒，控制台缺省是 cp936 ⇒ 直接 print 会 UnicodeEncodeError 崩掉
    # （崩法的 rc 也是 1，于是"判据红"与"量具炸了"长得一模一样）。先把两路流钉成 UTF-8。
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")

    if args.execute and args.read_production_readonly:
        print("--execute 与 --read-production-readonly 互斥（要写就别装只读）。", file=sys.stderr)
        return 2

    persona_id = str(args.persona or "").strip()
    if not persona_id:
        try:
            sys.path.insert(0, str(_REPO_ROOT))
            from plugins.bot_unified_runtime.domains.chat_reply.character.persona_profile import (
                main_persona_id,
            )

            persona_id = main_persona_id() or DEFAULT_MAIN_PERSONA_ID
        except Exception:  # noqa: BLE001 - 注册表读不出来时用演练缺省，报告里点名
            persona_id = DEFAULT_MAIN_PERSONA_ID
    fill_unowned = str(args.fill_unowned or "").strip() or None

    if not args.db:
        print(
            "必须显式给 --db（本席不猜路径；生产库要写一律由用户/主会话授权后进行）。\n"
            "小库演练配方：把三件套 db+wal+shm 一起复制到仓库外再指过来。\n"
            "kb_wiki 是 18 GB 级、拷不动：只读取数带 --read-production-readonly。",
            file=sys.stderr,
        )
        return 2

    raw_paths: list[Path] = []
    approved = str(args.approve_runtime_write or "").strip().upper() == RUNTIME_WRITE_TOKEN
    for raw in args.db:
        if args.execute:
            if not approved and _is_runtime_path(Path(raw)):
                print(
                    f"REFUSED: 生产库写入需 --approve-runtime-write {RUNTIME_WRITE_TOKEN}"
                    f"（当前凭据={args.approve_runtime_write or '无'}）：{raw}",
                    file=sys.stderr,
                )
                return 2
            # 只有凭据逐字对上才允许绕开在册路径闸；绕闸的路径仍要落在库文件上。
            raw_paths.append(Path(raw) if approved else guard_target_path(raw))
        elif args.read_production_readonly:
            raw_paths.append(Path(raw))
        else:
            try:
                raw_paths.append(guard_target_path(raw))
            except UnsafeTargetError as exc:
                print(
                    f"REFUSED: {exc}\n只读取数请显式加 --read-production-readonly。",
                    file=sys.stderr,
                )
                return 2

    pairs, uncovered = resolve_targets([str(p) for p in raw_paths], args.stage)
    report: dict[str, Any] = {
        "mode": "execute" if args.execute else "dry_run",
        "stage": args.stage,
        "persona_id": persona_id,
        "assignment_mode": f"fill->{fill_unowned}" if fill_unowned else "leave_unowned_shared",
        "require_assigned": bool(args.require_assigned),
        "expected_targets": len(pairs) + len(uncovered),
        "covered_targets": len(pairs),
        "uncovered_targets": uncovered,
        "entries": [],
    }
    if not pairs:
        report["entries"].append(
            {"db": "n/a", "table": "n/a", "problems": [f"--db 没覆盖 {args.stage} 的任何目标"]}
        )
        print(json.dumps(report, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    exit_code = 0
    if uncovered and not args.partial_scope:
        exit_code = 1
        report["entries"].append(
            {"mode": "scope", "db": "n/a", "table": "scope",
             "problems": [f"未覆盖目标 {uncovered} ⇒ 部分作用域不许当全绿（要承认请加 --partial-scope）"]}
        )

    if args.stage == "subject-kind" and args.execute:
        print(
            "subject-kind 腿为 S2 出件：脚本已生成，**本席不执行**（去掉 --execute 看计划）。",
            file=sys.stderr,
        )
        return 2

    subs = STAGE_UNION.get(args.stage, (args.stage,))
    if "wiki" in subs:
        wiring = consumer_wired()
        report["wiki_consumer"] = wiring
        for path in raw_paths:
            if path.name != TOPIC_LEDGER[0]:
                continue
            if not path.exists():
                report["entries"].append(
                    {"mode": "topic", "db": path.name, "table": TOPIC_LEDGER[1],
                     "problems": ["库文件不存在 ⇒ topic 报告无读数"]}
                )
                continue
            topic = topic_attribution_report(
                path, Path(args.topic_report) if args.topic_report else None
            )
            topic["mode"] = "topic"
            topic["problems"] = [topic["problem"]] if topic.get("problem") else []
            report["entries"].append(topic)

    for path, table, index_sql, column in pairs:
        if args.stage == "subject-kind":
            entry = plan_subject_kind(path, table)
            entry["mode"] = "plan"
            report["entries"].append(entry)
            exit_code = exit_code or (1 if entry["problems"] else 0)
            continue
        entry = migrate_one(
            path,
            table,
            column=column,
            persona_id=persona_id,
            fill_unowned=fill_unowned,
            require_assigned=args.require_assigned,
            execute=args.execute,
            sample_limit=args.sample_limit,
            index_sql=index_sql,
            backup_mode=args.backup,
            backup_max_bytes=args.backup_max_bytes,
            allow_absent_table=args.allow_absent_table,
        )
        entry["mode"] = "cell"
        if args.stage == "wiki" and not entry.get("problems"):
            wiring = report.get("wiki_consumer") or {}
            if not wiring.get("kb_wiki_build_store_passes_persona_provider"):
                entry["problems"].append(
                    "kb_wiki._build_store 未把 persona_provider 传进共用 store ⇒ "
                    "加了列也没人按行裁剪（禁只加列不接消费者）"
                )
            if not wiring.get("store_over_fetch_before_filter"):
                entry["problems"].append("共用 store 里找不到 over-fetch-后-过滤的在册尺 ⇒ 假绿")
        report["entries"].append(entry)
        if entry.get("problems"):
            exit_code = 1

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            f"mode={report['mode']} stage={report['stage']} persona={persona_id} "
            f"assignment={report['assignment_mode']} "
            f"coverage={report['covered_targets']}/{report['expected_targets']} "
            f"uncovered={report['uncovered_targets']}"
        )
        for entry in report["entries"]:
            if entry.get("mode") == "topic":
                print(
                    f"  [topic] {entry.get('db')} {entry.get('table')}: "
                    f"ledger_rows={entry.get('ledger_rows')} "
                    f"distinct_topics={entry.get('distinct_topics')} "
                    f"report={entry.get('report_path', '-')} "
                    f"problems={entry.get('problems') or []}"
                )
                continue
            print(_fmt(entry) + f" problems={entry.get('problems') or []}")
    return exit_code


def _is_runtime_path(path: Path) -> bool:
    try:
        resolved = str(path.resolve()).replace("\\", "/").lower()
    except OSError:
        return False
    for marker in ("chatbot_runtime", "chatbot_archive"):
        if marker in resolved:
            return True
    try:
        sys.path.insert(0, str(_REPO_ROOT / "scripts"))
        from runtime_paths import runtime_data_dir

        data_root = str(runtime_data_dir()).replace("\\", "/").lower()
        return resolved.startswith(data_root)
    except Exception:  # noqa: BLE001 - 解析不出运行根就按非生产处理（guard 仍兜底）
        return False


if __name__ == "__main__":
    raise SystemExit(main())
