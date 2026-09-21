"""记忆总线 v2 迁移门（WP6）：幂等 + 只 INSERT + 守恒断言（含负样本）。

全部跑在 tmp_path 造出的库上——真机 SQLite 库绝不拿来做迁移试验（铁律 2）。
"""

from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character import (
    memory_bus_v2 as bus_mod,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.memory_bus_v2 import (
    MemoryBus,
    canonical_fact_text,
    settings_from_config,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.memory_store_v21 import (
    MemoryStoreV21,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.reflection import (
    build_digest_id,
    build_reflection_fact_id,
)
from scripts import migrate_memory_bus_v2 as migrator

GROUP_A = "group_1108838060_3865067623"
GROUP_B = "group_631785829_3865067623"
FIXED_NOW = datetime.datetime(2026, 9, 21, 12, 0, tzinfo=datetime.timezone.utc)


class Cfg:
    bot_memory_bus_enabled = True
    bot_memory_reflected_write_target = "bus"
    bot_memory_strength_k = 3.0
    bot_memory_tau_stable_days = 180
    bot_memory_tau_seasonal_days = 45
    bot_memory_tau_episodic_days = 14
    bot_memory_relevance_weights = ""
    bot_memory_per_category_max = 1
    bot_memory_semantic_recall_enabled = True
    bot_memory_db_path = ""


def _epoch(moment: datetime.datetime):
    return lambda: moment.timestamp()


def _seed_reflection(db: Path, rows: list[tuple[str, str, str, str]]) -> None:
    """rows = (sender, session_key, text, category)；每个 session_key 一份当日摘要。

    直接按反思库真身建表再逐行插：``fact_id`` 用旧库同款派生式
    （``build_reflection_fact_id``），使夹具与生产写侧同形。
    """
    with sqlite3.connect(db) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS reflection_facts (
                fact_id TEXT PRIMARY KEY, sender_id TEXT NOT NULL,
                session_key TEXT NOT NULL DEFAULT '', fact_text TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT '', confidence REAL NOT NULL DEFAULT 0.6,
                source_digest_id TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
                superseded INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        for sender, session_key, text, category in rows:
            connection.execute(
                "INSERT INTO reflection_facts VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    build_reflection_fact_id(sender, canonical_fact_text(text)),
                    sender, session_key, text, category, 0.7,
                    build_digest_id(session_key, "2026-09-21"),
                    "2026-09-21T10:00:00Z",
                    0,
                ),
            )


def _dump_reflection(db: Path) -> str:
    """旧表全量转写（守恒/零改动的判据本体）。"""
    with sqlite3.connect(db) as connection:
        rows = connection.execute(
            "SELECT fact_id, sender_id, session_key, fact_text, category,"
            " confidence, superseded FROM reflection_facts"
            " ORDER BY fact_id"
        ).fetchall()
    return repr(rows)


def _insert_reflection_row(
    db: Path,
    *,
    sender: str,
    session_key: str,
    text: str,
    category: str,
    superseded: int = 0,
) -> None:
    with sqlite3.connect(db) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO reflection_facts VALUES (?,?,?,?,?,?,?,?,?)",
            (
                build_reflection_fact_id(sender, canonical_fact_text(text)),
                sender, session_key, text, category, 0.7,
                build_digest_id(session_key, "2026-09-21"),
                "2026-09-21T10:00:00Z", superseded,
            ),
        )


def _bus_rows(store: MemoryStoreV21) -> list[dict[str, object]]:
    with store._lock:
        return [
            dict(row)
            for row in store._connection.execute(
                "SELECT owner_id, text, provenance, source, scope_kind, scope_key,"
                " status, source_event_id FROM memory_entries_v21 ORDER BY owner_id, text"
            ).fetchall()
        ]


def test_migration_dry_run_writes_nothing(tmp_path: Path) -> None:
    reflection_db = tmp_path / "reflection.sqlite3"
    memory_db = tmp_path / "memory.sqlite3"
    _seed_reflection(reflection_db, [("u1", f"qq:{GROUP_A}", "我喜欢柠檬茶", "preference")])
    report = migrator.migrate(
        memory_db=memory_db, reflection_db=reflection_db, execute=False
    )
    assert report.planned == 1 and report.migrated == 0
    assert not memory_db.exists()  # dry-run 连库都不该建


def test_migration_moves_active_rows_then_is_idempotent(tmp_path: Path) -> None:
    reflection_db = tmp_path / "reflection.sqlite3"
    memory_db = tmp_path / "memory.sqlite3"
    history_db = tmp_path / "history.sqlite3"
    _seed_history(history_db, [("qq", GROUP_A), ("qq", GROUP_B)])
    _seed_reflection(
        reflection_db,
        [
            ("u1", f"qq:{GROUP_A}", "我喜欢柠檬茶", "preference"),
            ("u1", f"qq:{GROUP_B}", "我在学 Rust", "activity"),
            ("u2", f"qq:{GROUP_A}", "我住在北京", "identity"),
        ],
    )
    before = _dump_reflection(reflection_db)

    first = migrator.migrate(
        memory_db=memory_db,
        reflection_db=reflection_db,
        history_db=history_db,
        execute=True,
    )
    assert first.migrated == 3, first
    assert Path(first.backup_dir).exists() and Path(first.backup_dir).is_dir()
    assert _dump_reflection(reflection_db) == before, "旧表被改写过"

    store = MemoryStoreV21(str(memory_db))
    rows = _bus_rows(store)
    assert {str(row["owner_id"]) for row in rows} == {"u1", "u2"}
    assert {str(row["provenance"]) for row in rows} == {"reflected"}
    assert {str(row["source"]) for row in rows} == {"reflection_migration"}

    second = migrator.migrate(
        memory_db=memory_db,
        reflection_db=reflection_db,
        history_db=history_db,
        execute=True,
    )
    assert second.migrated == 0 and second.skipped_existing == 3, second
    assert len(_bus_rows(store)) == 3  # 幂等：重跑零新增
    assert _dump_reflection(reflection_db) == before


def test_migration_scope_restored_from_history_join(tmp_path: Path) -> None:
    """复合键按**数据连接**还原成裸键（不按分隔符猜形），还原后按裸键可见、异群不可见。"""
    reflection_db = tmp_path / "reflection.sqlite3"
    memory_db = tmp_path / "memory.sqlite3"
    history_db = tmp_path / "history.sqlite3"
    _seed_history(history_db, [("qq", GROUP_A)])
    _seed_reflection(reflection_db, [("u1", f"qq:{GROUP_A}", "我喜欢柠檬茶", "preference")])
    migrator.migrate(
        memory_db=memory_db,
        reflection_db=reflection_db,
        history_db=history_db,
        execute=True,
    )
    config = Cfg()
    config.bot_memory_db_path = str(memory_db)
    bus = MemoryBus(MemoryStoreV21(str(memory_db)), config=config,
                    clock=lambda: FIXED_NOW)
    home = bus.recall(owner_id="u1", session_id=GROUP_A, query_text="柠檬茶")
    away = bus.recall(owner_id="u1", session_id=GROUP_B, query_text="柠檬茶")
    assert [item.text for item in home.items] == ["我喜欢柠檬茶"]
    assert away.items == []
    assert home.scope_key == GROUP_A


def test_migration_fail_closed_when_history_join_misses(tmp_path: Path) -> None:
    """历史库缺失 ⇒ 复合键原样落库（谁 also 召不回）并如实计数，绝不退化成 global。"""
    reflection_db = tmp_path / "reflection.sqlite3"
    memory_db = tmp_path / "memory.sqlite3"
    _seed_reflection(reflection_db, [("u1", f"qq:{GROUP_A}", "我喜欢柠檬茶", "preference")])
    report = migrator.migrate(
        memory_db=memory_db, reflection_db=reflection_db, execute=True
    )
    assert report.unresolved_scope == 1
    store = MemoryStoreV21(str(memory_db))
    rows = _bus_rows(store)
    assert str(rows[0]["scope_key"]) == f"qq:{GROUP_A}"
    assert str(rows[0]["scope_kind"]) != "global"
    config = Cfg()
    config.bot_memory_db_path = str(memory_db)
    bus = MemoryBus(store, config=config, clock=lambda: FIXED_NOW)
    assert bus.recall(owner_id="u1", session_id=GROUP_A, query_text="柠檬茶").items == []


def test_superseded_legacy_rows_are_not_migrated(tmp_path: Path) -> None:
    """旧库里被 keep-newest 作废的行不许借迁移还魂。"""
    reflection_db = tmp_path / "reflection.sqlite3"
    memory_db = tmp_path / "memory.sqlite3"
    _seed_reflection(reflection_db, [])  # 建表
    _insert_reflection_row(
        reflection_db, sender="u1", session_key=f"qq:{GROUP_A}", text="我喜欢柠檬茶",
        category="preference", superseded=1,
    )
    _insert_reflection_row(
        reflection_db, sender="u1", session_key=f"qq:{GROUP_A}", text="我超爱柠檬茶",
        category="preference", superseded=0,
    )
    with sqlite3.connect(reflection_db) as connection:
        stale = connection.execute(
            "SELECT COUNT(*) FROM reflection_facts WHERE superseded = 1"
        ).fetchone()[0]
    assert int(stale) == 1  # 夹具自证：确实有一行被旧规则作废
    report = migrator.migrate(
        memory_db=memory_db, reflection_db=reflection_db, execute=True
    )
    assert report.legacy_active == 1 and report.planned == 1
    assert [row["text"] for row in _bus_rows(MemoryStoreV21(str(memory_db)))] == [
        "我超爱柠檬茶"
    ]


def test_migration_does_not_resurrect_user_forgotten_fact(tmp_path: Path) -> None:
    reflection_db = tmp_path / "reflection.sqlite3"
    memory_db = tmp_path / "memory.sqlite3"
    _seed_history(tmp_path / "history.sqlite3", [("qq", GROUP_A)])
    _seed_reflection(reflection_db, [("u1", f"qq:{GROUP_A}", "我喜欢柠檬茶", "preference")])
    migrator.migrate(
        memory_db=memory_db,
        reflection_db=reflection_db,
        history_db=tmp_path / "history.sqlite3",
        execute=True,
    )
    store = MemoryStoreV21(str(memory_db))
    row = _bus_rows(store)[0]
    config = Cfg()
    config.bot_memory_db_path = str(memory_db)
    bus = MemoryBus(store, config=config, clock=lambda: FIXED_NOW)
    memory_id = _memory_id_of(store, str(row["text"]))
    assert bus.forget(
        memory_id=memory_id, owner_id=str(row["owner_id"]), forgotten_by="u1"
    )
    # 再迁一次：既有的行有墓碑 ⇒ 幂等探针命中，状态不得翻回 active。
    migrator.migrate(
        memory_db=memory_db,
        reflection_db=reflection_db,
        history_db=tmp_path / "history.sqlite3",
        execute=True,
    )
    assert store.get_entry(memory_id)["status"] == "forgotten"
    assert bus.recall(owner_id="u1", session_id=GROUP_A, query_text="柠檬茶").items == []


# ---------------------------------------------------------------- 守恒断言与负样本


def test_conservation_assertion_is_red_when_a_row_is_missing() -> None:
    """负样本①：断言函数本体——按人差一行必须红。"""
    # 旧库三行（u1 两条、u2 一条）——期望值直接按这个分布写死，读代码就能核对。
    migrator.assert_conservation(
        expected_by_owner={"u1": 2, "u2": 1},
        migrated_by_owner={"u1": 2, "u2": 1},
        legacy_total_before=3,
        legacy_total_after=3,
    )
    with pytest.raises(migrator.ConservationError):
        migrator.assert_conservation(
            expected_by_owner={"u1": 2, "u2": 1},
            migrated_by_owner={"u1": 1, "u2": 1},  # 故意漏掉 u1 的一行
            legacy_total_before=3,
            legacy_total_after=3,
        )
    with pytest.raises(migrator.ConservationError):
        migrator.assert_conservation(
            expected_by_owner={"u1": 2, "u2": 1},
            migrated_by_owner={"u1": 2, "u2": 1},
            legacy_total_before=3,
            legacy_total_after=2,  # 旧表被动过一行
        )


def test_conservation_assertion_is_red_when_migration_loses_a_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """负样本②：走完整流程，让投递环节偷偷吞掉一行 ⇒ 迁移必须报错而非交半份账。"""
    reflection_db = tmp_path / "reflection.sqlite3"
    memory_db = tmp_path / "memory.sqlite3"
    _seed_reflection(
        reflection_db,
        [
            ("u1", f"qq:{GROUP_A}", "我喜欢柠檬茶", "preference"),
            ("u1", f"qq:{GROUP_A}", "我在学 Rust", "activity"),
        ],
    )
    original = migrator._absorb_one
    swallowed: list[str] = []

    def _losing_absorb(bus: MemoryBus, plan: dict[str, object]) -> str:
        if str(plan["text"]) == "我在学 Rust":
            swallowed.append(str(plan["text"]))
            return "migrated"  # 报成功，但真的没写进去
        return original(bus, plan)

    monkeypatch.setattr(migrator, "_absorb_one", _losing_absorb)
    with pytest.raises(migrator.ConservationError):
        migrator.migrate(
            memory_db=memory_db, reflection_db=reflection_db, execute=True
        )
    assert swallowed == ["我在学 Rust"]
    assert len(_bus_rows(MemoryStoreV21(str(memory_db)))) == 1  # 半迁移被点名，不静默放行


def test_migration_reports_per_owner_before_and_after(tmp_path: Path) -> None:
    reflection_db = tmp_path / "reflection.sqlite3"
    memory_db = tmp_path / "memory.sqlite3"
    _seed_reflection(
        reflection_db,
        [
            ("u1", f"qq:{GROUP_A}", "我喜欢柠檬茶", "preference"),
            ("u2", f"qq:{GROUP_B}", "我住在上海", "identity"),
        ],
    )
    report = migrator.migrate(
        memory_db=memory_db, reflection_db=reflection_db, execute=True
    )
    assert report.per_owner_before == {"u1": 1, "u2": 1}
    assert report.per_owner_after == {"u1": 1, "u2": 1}
    assert report.legacy_total == report.legacy_active == 2


def test_migration_skips_hard_line_rows_and_still_conserves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """硬线词面命中=正当拒收，要从守恒期望里扣掉（否则整库迁移会被一条脏数据永久卡死）。"""
    reflection_db = tmp_path / "reflection.sqlite3"
    memory_db = tmp_path / "memory.sqlite3"
    _seed_reflection(
        reflection_db,
        [
            ("u1", f"qq:{GROUP_A}", "我喜欢柠檬茶", "preference"),
            ("u1", f"qq:{GROUP_A}", "她八岁，给我看色情", "preference"),
        ],
    )
    report = migrator.migrate(
        memory_db=memory_db, reflection_db=reflection_db, execute=True
    )
    assert report.skipped_forgotten == 1, report
    assert report.migrated == 1
    texts = [str(row["text"]) for row in _bus_rows(MemoryStoreV21(str(memory_db)))]
    assert texts == ["我喜欢柠檬茶"]


def test_migration_backup_contains_both_databases(tmp_path: Path) -> None:
    reflection_db = tmp_path / "reflection.sqlite3"
    memory_db = tmp_path / "memory.sqlite3"
    _seed_reflection(reflection_db, [("u1", f"qq:{GROUP_A}", "我喜欢柠檬茶", "preference")])
    MemoryStoreV21(str(memory_db)).close()
    report = migrator.migrate(
        memory_db=memory_db, reflection_db=reflection_db, execute=True
    )
    backed_up = {path.name for path in Path(report.backup_dir).iterdir()}
    assert memory_db.name in backed_up and reflection_db.name in backed_up


def test_migration_settings_gate_is_per_call() -> None:
    config = Cfg()
    assert settings_from_config(config).writes_to_bus is True
    config.bot_memory_reflected_write_target = "legacy"
    assert settings_from_config(config).writes_to_bus is False


def _memory_id_of(store: MemoryStoreV21, text: str) -> str:
    with store._lock:
        row = store._connection.execute(
            "SELECT memory_id FROM memory_entries_v21 WHERE text = ?", (text,)
        ).fetchone()
    return str(row["memory_id"])


def _seed_history(db: Path, pairs: list[tuple[str, str]]) -> None:
    with sqlite3.connect(db) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_turns (
                request_id TEXT NOT NULL, platform TEXT NOT NULL, adapter TEXT NOT NULL,
                bot_id TEXT NOT NULL, session_id TEXT NOT NULL, sender_id TEXT NOT NULL,
                role TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'chat'
            )
            """
        )
        for index, (platform, session_id) in enumerate(pairs):
            connection.execute(
                "INSERT INTO conversation_turns VALUES (?,?,?,?,?,?,?,?,?,'chat')",
                (
                    f"r{index}", platform, "onebot", "bot", session_id, "u1", "user",
                    "x", "2026-09-21T10:00:00.000000+00:00",
                ),
            )


def test_bus_module_never_imports_migration_side_effects() -> None:
    """总线件不许反向依赖迁移脚本（否则 import 插件就会碰 scripts 路径）。"""
    import ast

    source = Path(
        "plugins/bot_unified_runtime/domains/chat_reply/character/memory_bus_v2.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    modules = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    } | {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    }
    assert not [name for name in modules if "migrate" in name], modules
    assert bus_mod.PROVENANCE_REFLECTED == "reflected"
