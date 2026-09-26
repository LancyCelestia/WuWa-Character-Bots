"""记忆总线 v2 启用就绪锁（S-T-MEMBUS，2026-09-26，用户第 11 项 + 裁定 D7）。

今晚只做到 **DRY-RUN 就绪态**：本件全部离线（tmp_path 合成库），零生产接触。

锁四件事（逐件对应席位日志 §3 的启用三步阻塞点）：
1. 建表不是阻塞点——开关一开，``build_memory_bus`` 经 ``shared_bus_store``
   自动 ensure_schema；关态则连库都不碰（既有不变量）。
2. 热改不可达——``BOT_MEMORY_BUS_ENABLED`` 既不在 ``SETTABLE_KEYS`` 也不在
   ``RESTART_REQUIRED_KEYS``：``/bot runtime set`` 直接拒；唯一杠杆是
   ``.env`` + 重启（读路装配冻结在 ``build_character_context_provider`` 构造期）。
   同时它是 safety_exec 的 R2 显名单（改配置面本身要书面同意门）。
3. 读写同源的排序陷阱——``reflected_write_target=bus`` 且**迁移未跑**时，
   读取装配不再把旧 ``reflection_facts`` 折进候选池（providers 只在
   ``not writes_to_bus`` 时 attach）⇒ 旧归纳行会从召回面整表消失。
   本件把「先迁移、后切 target」钉成行为断言，而不只是散文。
4. 迁移脚本的两处真实契约（旧文案曾宣称不成立）：守恒断言**只检测不回滚**、
   失败后幂等续跑补差额；旧库 global 形态（session_key ∈ {'','*','global'}）
   的行会被总线空作用域闸正当拒收——生产现算 0 行，切换前必须复核。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character.memory_bus_v2 import (
    MemoryBus,
    build_memory_bus,
    canonical_fact_text,
    settings_from_config,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.memory_store_v21 import (
    MemoryStoreV21,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
    build_memory_read_provider,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.reflection import (
    build_digest_id,
    build_reflection_fact_id,
)
from scripts import migrate_memory_bus_v2 as migrator

GROUP_A = "group_1108838060_3865067623"
GROUP_B = "group_631785829_3865067623"


class Cfg:
    """生产同形最小配置面：只放读取/装配路径真会 getattr 的键。"""

    bot_memory_enabled = True
    bot_memory_db_path = ""
    bot_memory_bus_enabled = True
    bot_memory_reflected_write_target = "legacy"
    bot_memory_strength_k = 3.0
    bot_memory_tau_stable_days = 180
    bot_memory_tau_seasonal_days = 45
    bot_memory_tau_episodic_days = 14
    bot_memory_relevance_weights = ""
    bot_memory_per_category_max = 1
    bot_memory_semantic_recall_enabled = True
    bot_reflection_enabled = True
    bot_reflection_db_path = ""


def _seed_reflection(db: Path, rows: list[tuple[str, str, str, str]]) -> None:
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
                    build_digest_id(session_key, "2026-09-26"),
                    "2026-09-21T10:00:00Z",
                    0,
                ),
            )


def _migration_rows(store: MemoryStoreV21) -> list[dict[str, object]]:
    with store._lock:
        return [
            dict(row)
            for row in store._connection.execute(
                "SELECT owner_id, text, status FROM memory_entries_v21 "
                "WHERE source = 'reflection_migration' ORDER BY owner_id, text"
            ).fetchall()
        ]


# --------------------------------------------------------------- 1. 建表不是阻塞点


def test_disabled_bus_touches_no_store(tmp_path: Path) -> None:
    config = Cfg()
    config.bot_memory_bus_enabled = False
    config.bot_memory_db_path = str(tmp_path / "memory.sqlite3")
    assert build_memory_bus(config) is None
    assert not Path(config.bot_memory_db_path).exists()  # 关态连库都不建


def test_enabled_bus_creates_tables_without_manual_ddl(tmp_path: Path) -> None:
    config = Cfg()
    config.bot_memory_db_path = str(tmp_path / "memory.sqlite3")
    bus = build_memory_bus(config)
    assert bus is not None
    tables = set(bus._store.table_names()) if hasattr(bus._store, "table_names") else None
    if tables is None:  # store 无列举口就直接查 sqlite_master
        with sqlite3.connect(config.bot_memory_db_path) as connection:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
    assert "memory_entries_v21" in tables
    assert "memory_tombstones_v21" in tables


# ------------------------------------------------------- 2. 热改不可达（重启是唯一杠杆）


def test_enablement_is_not_hot_settable() -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
        settings as runtime_settings,
    )

    key = "BOT_MEMORY_BUS_ENABLED"
    # 不在 SETTABLE：`/bot runtime set` 走 settings.py 白名单外即拒。
    assert key not in runtime_settings.SETTABLE_KEYS
    # 不在 RESTART 登记表：合并层根本没有该族的读点，登记了反而是「看着能热改」的
    # 假面（config.py 注释与 2026-09-21 裁定同口径）。两本账都不在册 ⇒ 唯一杠杆
    # = .env + 重启。此断言同时是绊线：谁把它加进 SETTABLE 而读路仍冻结在装配期
    # （providers.build_character_context_provider 构造 memory_provider 一次），
    # 本测试必须红并逼施工者先接合并层现读。
    assert key not in runtime_settings.RESTART_REQUIRED_KEYS


def test_enablement_key_is_consent_tier() -> None:
    from plugins.bot_unified_runtime.domains.core.safety_exec import config_risk

    assert "BOT_MEMORY_BUS_ENABLED" in config_risk.EXPLICIT_R2_KEYS


# --------------------------------------------------- 3. 读写同源的排序陷阱（先迁移后切）


def _seed_history(db: Path, pairs: list[tuple[str, str]]) -> None:
    with sqlite3.connect(db) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS conversation_turns "
            "(request_id TEXT, platform TEXT, session_id TEXT)"
        )
        for index, (platform, session_id) in enumerate(pairs):
            connection.execute(
                "INSERT INTO conversation_turns VALUES (?,?,?)",
                (f"r{index}", platform, session_id),
            )


def test_legacy_target_pools_old_reflection_rows(tmp_path: Path) -> None:
    """开总线、归纳仍写旧表（第一档）：旧 reflection_facts 折进同一打分池，不丢记忆。

    夹具按**裸键**落——锁的是折叠闸的等值档。生产历史形态是复合键（``platform:裸键``），
    那一档由下方 ``test_production_composite_keys_reach_the_pool`` 各测一次，两案不合并
    （裸键案证明「等值仍成立」，复合案证明「整尾等值 + 冒号分隔也成立」）。
    """
    reflection_db = tmp_path / "reflection.sqlite3"
    memory_db = tmp_path / "memory.sqlite3"
    _seed_reflection(reflection_db, [("u1", GROUP_A, "我喜欢柠檬茶", "preference")])
    config = Cfg()
    config.bot_memory_db_path = str(memory_db)
    config.bot_reflection_db_path = str(reflection_db)
    config.bot_memory_reflected_write_target = "legacy"
    provider = build_memory_read_provider(config)
    bus = getattr(provider, "bus", None) or getattr(provider, "_audit_bus", None)
    assert bus is not None, "开态装配必须给出总线实例"
    assert bus.candidate_source_names(), "legacy 档必须把旧归纳表 attach 成候选源"
    outcome = bus.recall(owner_id="u1", session_id=GROUP_A, query_text="柠檬茶")
    assert [item.text for item in outcome.items] == ["我喜欢柠檬茶"]


# 挂账原文（S-T-MEMBUS 2026-09-26 现算，保留为注释而非删掉——转正理由要能被复查）：
#   生产 reflection_facts 的历史 session_key 是复合形（platform:裸键，实测 112 行全为
#   此形态、build_composite_index 命中 112），而候选源折叠闸 legacy_session_visible
#   只认裸键等值 ⇒ 第一档（target=legacy）下这些行结构上进不了打分池；读路席位自家
#   测试全绿仅因其夹具用裸键——又一例「夹具与生产形态不符」。
# 2026-09-26 S-T-MEMKEY-1 转正：折叠闸补上「冒号 + 整尾等值」这一档（宽度按来源给定，
#   注入源那路传 True、旧显式库那路仍传 False），并与注入方 facts_for 的真 SQL 逐条
#   比宽锁在 tests/test_memory_bus_read_leg.py::test_folded_pool_never_wider_than_facts_for。
#   本用例摘牌前实跑为 XPASS（判据在场而用例不红，才是真绿）。
def test_production_composite_keys_reach_the_pool(tmp_path: Path) -> None:
    """生产形态（复合 session_key）的旧归纳行必须在第一档召回里看得见。"""
    reflection_db = tmp_path / "reflection.sqlite3"
    memory_db = tmp_path / "memory.sqlite3"
    _seed_reflection(reflection_db, [("u1", f"qq:{GROUP_A}", "我喜欢柠檬茶", "preference")])
    config = Cfg()
    config.bot_memory_db_path = str(memory_db)
    config.bot_reflection_db_path = str(reflection_db)
    config.bot_memory_reflected_write_target = "legacy"
    provider = build_memory_read_provider(config)
    bus = getattr(provider, "bus", None) or getattr(provider, "_audit_bus", None)
    outcome = bus.recall(owner_id="u1", session_id=GROUP_A, query_text="柠檬茶")
    assert [item.text for item in outcome.items] == ["我喜欢柠檬茶"]


def test_bus_target_without_migration_hides_old_reflection_rows(tmp_path: Path) -> None:
    """排序陷阱：target=bus 但迁移未跑 ⇒ 旧归纳行不进候选池、召回面整表消失。

    这不是缺陷，是设计语义（归纳改落总线后旧表不再挂候选源）——所以**迁移必须
    先于切档**，本用例把这条操作次序钉成可复跑判据。
    """
    reflection_db = tmp_path / "reflection.sqlite3"
    memory_db = tmp_path / "memory.sqlite3"
    history_db = tmp_path / "history.sqlite3"
    _seed_history(history_db, [("qq", GROUP_A)])
    _seed_reflection(reflection_db, [("u1", f"qq:{GROUP_A}", "我喜欢柠檬茶", "preference")])
    config = Cfg()
    config.bot_memory_db_path = str(memory_db)
    config.bot_reflection_db_path = str(reflection_db)
    config.bot_memory_reflected_write_target = "bus"
    provider = build_memory_read_provider(config)
    bus = getattr(provider, "bus", None) or getattr(provider, "_audit_bus", None)
    assert bus is not None
    assert bus.candidate_source_names() == (), "切 bus 档还挂候选源=两真身并写"
    outcome = bus.recall(owner_id="u1", session_id=GROUP_A, query_text="柠檬茶")
    assert outcome.items == []  # 迁移未跑 ⇒ 这条旧记忆今天召不回（陷阱实证）
    # 跑过迁移后同一条必须回到召回面——「先迁移、后切档」的正向半腿。
    report = migrator.migrate(
        memory_db=memory_db,
        reflection_db=reflection_db,
        history_db=history_db,
        execute=True,
    )
    assert report.migrated == 1, report
    outcome_after = bus.recall(owner_id="u1", session_id=GROUP_A, query_text="柠檬茶")
    assert [item.text for item in outcome_after.items] == ["我喜欢柠檬茶"]


# ------------------------------------------------------------- 4. 迁移的两处真实契约


def test_conservation_failure_leaves_committed_rows_then_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """守恒断言只检测、不回滚；失败后幂等续跑把差额补全（替代旧文案的「整事务回滚」宣称）。"""
    reflection_db = tmp_path / "reflection.sqlite3"
    memory_db = tmp_path / "memory.sqlite3"
    _seed_reflection(
        reflection_db,
        [
            ("u1", f"qq:{GROUP_A}", "我喜欢柠檬茶", "preference"),
            ("u1", f"qq:{GROUP_A}", "我在学 Rust", "activity"),
            ("u2", f"qq:{GROUP_A}", "我住在北京", "identity"),
        ],
    )
    original = migrator._absorb_one
    swallowed: list[str] = []

    def _losing_absorb(bus: MemoryBus, plan: dict[str, object]) -> str:
        if str(plan["text"]) == "我在学 Rust":
            swallowed.append(str(plan["text"]))
            return "migrated"  # 谎报：账上记成功，库里没这行
        return original(bus, plan)

    monkeypatch.setattr(migrator, "_absorb_one", _losing_absorb)
    with pytest.raises(migrator.ConservationError):
        migrator.migrate(memory_db=memory_db, reflection_db=reflection_db, execute=True)
    assert swallowed == ["我在学 Rust"]
    store = MemoryStoreV21(str(memory_db))
    partial = sorted(str(row["text"]) for row in _migration_rows(store))
    # 断言不开谎：中毒跑已提交的行确实留在盘上（半迁移可检测、可续跑，不可假装回滚）。
    assert partial == sorted(["我喜欢柠檬茶", "我住在北京"])

    monkeypatch.undo()
    resumed = migrator.migrate(
        memory_db=memory_db, reflection_db=reflection_db, execute=True
    )
    assert resumed.migrated == 1 and resumed.skipped_existing == 2, resumed
    assert sorted(str(row["text"]) for row in _migration_rows(store)) == sorted(
        ["我喜欢柠檬茶", "我在学 Rust", "我住在北京"]
    )


def test_legacy_global_rows_are_refused_not_faked(tmp_path: Path) -> None:
    """旧库 global 形态行被总线空作用域闸正当拒收：不迁、不谎报、守恒照样成立。

    操作含义（启用三步的前置检查依据）：``session_key IN ('','*','global')`` 的
    行在总线上永远召不回；这些行留在旧表、legacy 档经候选源仍可见；一旦切
    target=bus 而这类行 >0，它们会从召回面消失 ⇒ 执行迁移前必须现算该形态计数。
    """
    reflection_db = tmp_path / "reflection.sqlite3"
    memory_db = tmp_path / "memory.sqlite3"
    _seed_reflection(
        reflection_db,
        [
            ("u1", "", "全局形态一", "misc"),
            ("u1", "*", "全局形态二", "misc"),
            ("u1", f"qq:{GROUP_A}", "我喜欢柠檬茶", "preference"),
        ],
    )
    report = migrator.migrate(
        memory_db=memory_db, reflection_db=reflection_db, execute=True
    )
    assert report.planned == 3
    assert report.migrated == 1, report
    # 拒收计数走的是 skipped_forgotten 计数器（报告文案已改为「正当拒收」）。
    assert report.skipped_forgotten == 2, report
    texts = [str(row["text"]) for row in _migration_rows(MemoryStoreV21(str(memory_db)))]
    assert texts == ["我喜欢柠檬茶"]
    # 反向半腿：全局形态绝不允许以 global 作用域混进总线（隐私 fail-closed 教义）。
    with sqlite3.connect(memory_db) as connection:
        globals_in_bus = connection.execute(
            "SELECT COUNT(*) FROM memory_entries_v21 WHERE scope_kind='global'"
        ).fetchone()[0]
    assert int(globals_in_bus) == 0


def test_production_default_is_off() -> None:
    """代码缺省位：开关缺省 False、归纳落点缺省 legacy——现网关态的根判据。"""
    from plugins.bot_unified_runtime.config import Config

    fields = Config.model_fields
    assert fields["bot_memory_bus_enabled"].default is False
    assert fields["bot_memory_reflected_write_target"].default == "legacy"
    settings = settings_from_config(object())  # 全 getattr 兜底的裸对象
    assert settings.enabled is False and settings.writes_to_bus is False
