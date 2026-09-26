"""记忆库清洗（防御强化）：从长时记忆清除硬线内容。

2026-09-20 内容政策收窄（用户裁定，v21r5 POLICY-RELAX 席）：清洗面收敛为
「六条硬线 + minors」——伤害身体/残害（含严重暴力）、窒息、系统级人格贬低、
未成年（含幼态歧义 fail-closed）、暴力 SM（致伤致残级）、非人化牲口式对待。
2026-09-20 CRIT-FIX-3 席：硬线族增补 ⓻排泄物（r18-taxonomy 3.4「维持禁」），
随共享注册表自动纳入清洗面；未成年词面补完（中文数字年龄/英文年龄形态/
儿童信号词/儿童言行不可 grounding/窗口 24）同波及本清洗面（单一来源）。
explicit 会话内已放开的亲密内容（软性 SM、触手、breeding 等授权记忆）与
普通侮辱、强制人格类文本**不再清洗**。词面与 content_safety 共享单一来源
（``HARD_LINE_SANITIZE_PATTERNS`` + ``minor_ambiguity_hit``）。

用户明确授权清除；为可审计不清空证据，匹配行先复制进 ``memory_quarantine``
隔离表（含命中类别、时间、来源表 ``source_table``），再从它所在的那张记忆表摘除。
读/摘两面都覆盖**库里物理存在的每张记忆表**（旧 ``memory_facts`` 与总线
``memory_entries_v21``），判定只走 ``capabilities/memory.iter_stored_memory_rows``
这一个中央入口——本件不读总线开关。支持 dry-run 只报告不删。

用法（须用 canonical 模块路径；旧 ``security/`` 下的同名件已是兼容垫片，
``python -m`` 打进垫片只会 import 完就静默退出、参数被吞，等于假成功）：
    python -m plugins.bot_unified_runtime.domains.chat_reply.security.memory_sanitize --dry-run
    python -m plugins.bot_unified_runtime.domains.chat_reply.security.memory_sanitize --apply
入口也可走 dev.ps1 -Task memory-sanitize。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from plugins.bot_unified_runtime.domains.chat_reply.capabilities.memory import (
    MEMORY_BUS_TABLE,
    MEMORY_LEGACY_TABLE,
    StoredMemoryRow,
    iter_stored_memory_rows,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.memory import (
    SQLiteMemoryRepository,
)

from .content_safety import (
    HARD_LINE_SANITIZE_PATTERNS,
    minor_ambiguity_hit,
    normalize_for_matching,
)

#: 清洗面的列集要求：只认「有主体、有正文」，其余列缺了照样扫（隐私清扫不因表形
#: 降级）。图谱那侧要时间戳才能做窗口过滤，用的是它自己的严格列集——差异由调用方
#: 传入列集表达，判定本身仍只有一处。
_SANITIZE_MINIMUM_COLUMNS = {
    MEMORY_LEGACY_TABLE: frozenset({"fact_id", "subject_user_id", "text"}),
    MEMORY_BUS_TABLE: frozenset({"memory_id", "owner_id", "text"}),
}


@dataclass(frozen=True)
class SanitizeReport:
    scanned: int
    quarantined: int
    by_category: dict[str, int]
    #: 每张记忆表各扫了多少行（旧库单表时该字段是 {"memory_facts": N}，
    #: 总线开库后能看出「命中的是哪张表」，审计不再靠猜）。
    by_table: dict[str, int] = field(default_factory=dict)

    def render(self, *, applied: bool) -> str:
        head = "记忆清洗（已执行）" if applied else "记忆清洗（dry-run 预览）"
        lines = [f"{head}：扫描 {self.scanned} 条，命中 {self.quarantined} 条"]
        for category, count in sorted(self.by_category.items()):
            lines.append(f"  - {category}: {count}")
        if self.quarantined == 0:
            lines.append("记忆库干净，无需处理。")
        # 只有真扫到两张表才多这一行——旧库（关态）的输出与今天逐字节一致。
        if len(self.by_table) > 1:
            detail = "、".join(f"{table} {count}" for table, count in sorted(self.by_table.items()))
            lines.append(f"  记忆表：{detail}")
        return "\n".join(lines)


def _match_category(text: str) -> str | None:
    # 匹配前统一归一化（NFKC/零宽/空白折叠），全角或夹零宽字符的变体
    # 也能命中既有规则；归一化文本只用于匹配，不写回任何存储。
    # 清洗面=六硬线+minors（含 minor_ambiguity fail-closed），其余不清洗。
    normalized = normalize_for_matching(text)
    for category, pattern in HARD_LINE_SANITIZE_PATTERNS:
        if pattern.search(normalized):
            return category
    if minor_ambiguity_hit(normalized):
        return "minor_ambiguity"
    return None


def _ensure_quarantine_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_quarantine (
            fact_id TEXT NOT NULL,
            subject_user_id TEXT NOT NULL,
            session_id TEXT NOT NULL DEFAULT '',
            memory_kind TEXT NOT NULL,
            text TEXT NOT NULL,
            category TEXT NOT NULL,
            quarantined_at TEXT NOT NULL,
            PRIMARY KEY (fact_id, quarantined_at)
        )
        """
    )
    # 家规：只增列、带 DEFAULT，绝不 UPDATE 任何行（affinity 三列 / shared_export
    # 坐标 / emergency level 回线的同款）。老库没有 source_table 时补上——隔离表
    # 从此说得清「这行是从哪张记忆表摘下来的」，审计不靠猜。
    columns = {
        str(record[1])
        for record in connection.execute("PRAGMA table_info(memory_quarantine)").fetchall()
    }
    if "source_table" not in columns:
        connection.execute(
            "ALTER TABLE memory_quarantine"
            f" ADD COLUMN source_table TEXT NOT NULL DEFAULT '{MEMORY_LEGACY_TABLE}'"
        )


def _forget_bus_rows(path: Path, rows: Sequence[StoredMemoryRow]) -> int:
    """让命中的总线行「永不复活」——**必须经总线**，不在别处另立一套遗忘语义。

    为什么不自己开 ``MemoryStoreV21`` 写：事实表唯一的写入口是
    ``MemoryBus.absorb/forget``（墓碑先行 → 撤投影 → 行翻 forgotten 三步与顺序都
    归它），本件若在别处重抄这三步就是第二真身——该约束有常驻 AST 锁执法
    （``tests/test_memory_bus_v2_write_leg.py
    ::test_only_the_bus_writes_the_v21_fact_table_in_production``）。
    ``shared_bus_store`` 按路径给单一连接，所以这里也不会对同一个库文件开出第二
    条连接去和 bot 抢锁。

    ⚠ 只在**真扫到总线行**时才走到这里：纯旧库跑一次清洗，不该顺手把总线那套表
    建出来（关态零副作用，由测试件锁死）。

    ``config=None`` 是有意的：``forget`` 不读任何总线设置（读设置的只有
    ``absorb``/``recall``），本件既不判也不读开关，因此不需要 config。
    """
    if not rows:
        return 0
    from plugins.bot_unified_runtime.domains.chat_reply.character.memory_bus_v2 import (
        MemoryBus,
    )
    from plugins.bot_unified_runtime.domains.chat_reply.character.memory_store_v21 import (
        MemoryStoreV21,
    )

    # 专连专关（不用 shared_bus_store）：那条缓存按路径常驻、本席这边关不掉，
    # Windows 上表现为库文件句柄一直挂着；清洗是一次性作业，开一条用完即关最干净。
    store = MemoryStoreV21(str(path))
    try:
        bus = MemoryBus(store, config=None)
        done = 0
        for row in rows:
            if bus.forget(
                memory_id=row.row_id,
                owner_id=row.subject_user_id,
                forgotten_by="memory_sanitize",
            ):
                done += 1
        return done
    finally:
        store.close()


def sanitize_memory_db(
    db_path: str | Path,
    *,
    apply: bool = False,
) -> SanitizeReport:
    """扫描库里**物理存在的每张记忆表**；apply=True 时先隔离再摘除命中行。

    读侧一律经唯一入口 ``capabilities/memory.iter_stored_memory_rows``——本件不判
    总线开关、不写「if 开则读 v21」那种第二套判定。为什么清洗面必须覆盖两张表而
    不是「当前那张」：总线开着时召回路径**仍然**会把旧表行按 explicit 并进打分
    （真身 ``MemoryBus._legacy_explicit_rows``，迁移未跑前旧行照样回得到她的嘴
    里），所以清洗的读集必须是「召回能读回的一切」的超集，否则红线内容换个表躺
    着就等于没清。旧表被写腿退役（迁移跑完、影子读下线）之后，这里自然只剩一张表
    可扫，无需改判据。
    """
    path = Path(db_path)
    if not path.exists():
        return SanitizeReport(scanned=0, quarantined=0, by_category={}, by_table={})
    by_category: dict[str, int] = {}
    by_table: dict[str, int] = {}
    scanned = 0
    now_text = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        # 宽松列集：缺 session_id / memory_kind / 时间戳的老表也得扫（隐私清扫不因
        # 表形降级），缺列在投影里如实为空串。
        rows = iter_stored_memory_rows(connection, minimum_columns=_SANITIZE_MINIMUM_COLUMNS)
        flagged: list[StoredMemoryRow] = []
        for row in rows:
            scanned += 1
            by_table[row.store_table] = by_table.get(row.store_table, 0) + 1
            category = _match_category(row.text or "")
            if category is None:
                continue
            by_category[category] = by_category.get(category, 0) + 1
            flagged.append(row)
        if flagged and apply:
            _ensure_quarantine_schema(connection)
            for row in flagged:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO memory_quarantine
                        (fact_id, subject_user_id, session_id, memory_kind, text, category,
                         quarantined_at, source_table)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row.row_id,
                        row.subject_user_id,
                        row.session_id,
                        row.kind,
                        row.text,
                        _match_category(row.text or "") or "unknown",
                        now_text,
                        row.store_table,
                    ),
                )
            connection.commit()
            # 摘除两面都**不写第二套 SQL**：旧表行走 v1 真身
            # ``SQLiteMemoryRepository.delete_fact``（它自带 subject+session 归属
            # 条件），总线行走 ``MemoryBus.forget``（v2 真身）。本件因此不持有任何
            # 一张记忆表的 SQL——全仓「谁能写这两张表」的账保持一处不增。
            legacy_rows = [row for row in flagged if not row.is_from_bus]
            if legacy_rows:
                repository = SQLiteMemoryRepository(path)
                for row in legacy_rows:
                    repository.delete_fact(
                        fact_id=row.row_id,
                        subject_user_id=row.subject_user_id,
                        session_id=row.session_id,
                    )
            _forget_bus_rows(path, [row for row in flagged if row.is_from_bus])
    finally:
        connection.close()
    return SanitizeReport(
        scanned=scanned, quarantined=len(flagged), by_category=by_category, by_table=by_table
    )


def resolve_memory_db_path(config: object) -> Path | None:
    raw = str(getattr(config, "bot_memory_db_path", "") or "").strip()
    if not raw:
        return None
    from plugins.bot_unified_runtime.domains.link_parse.parsers.cookies import (
        _resolve_relative_cookie_path,
    )

    # data/ 前缀 → Runtime 数据根（与 cookie 文件同一套映射规则）。
    return _resolve_relative_cookie_path(Path(raw))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="sanitize long-term memory DB")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="只报告命中，不删除")
    group.add_argument("--apply", action="store_true", help="隔离并删除命中记忆")
    parser.add_argument("--db", default="", help="覆盖记忆库路径（默认读 BOT_MEMORY_DB_PATH）")
    args = parser.parse_args(argv)

    if args.db:
        db_path: Path | str = args.db
    else:
        from plugins.bot_unified_runtime.domains.ops.smoke.smoke import (
            load_smoke_config,
        )

        resolved = resolve_memory_db_path(load_smoke_config())
        if resolved is None:
            print("未配置 BOT_MEMORY_DB_PATH，无事可做。")
            return 2
        db_path = resolved
    report = sanitize_memory_db(db_path, apply=args.apply)
    print(report.render(applied=args.apply))
    print(f"数据库：{db_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
