"""记忆总线 v2 一次性迁移：``reflection_facts`` → ``memory_entries_v21``（WP6）。

规约（AGENTS 铁律 2 + 设计稿 §六，逐条落地）：
- **幂等**：幂等键 ``reflmig:<fact_id>`` 落在总线唯一索引 (owner_id, source_event_id) 上，
  重跑只算一次，第二次执行零写入；
- **运行数据不可删**：迁移前把记忆库整库复制到 ``%TEMP%``；只读反思库、只
  INSERT 总线表，**绝不 UPDATE/DELETE 反思原表、绝不 DROP 列或表**；
  回滚粒度=「停止写总线 + 新列闲置」；
- **不复活已删事实**：用户显式遗忘过的行（有墓碑）即便幂等键再次出现也只跳过；
- **守恒断言**：迁移后「旧表未作废行的按人分组数 == 总线 reflected-migration 行的
  按人分组数」且「旧表总行数分毫未动」，任一不满足即报 ``ConservationError`` 中止。
  如实口径（2026-09-26 S-T-MEMBUS 合成库实证）：store 层逐操作提交，断言**只检测、
  不回滚**——中毒跑的半迁移会留在盘上；收口方式是拿 %TEMP% 备份 **幂等续跑**把
  差额补到守恒期望（回归锁 test_resume_after_conservation_failure_completes_migration），
  绝不静默放行半迁移，也绝不假装能整事务撤回。

用法：
    python scripts/migrate_memory_bus_v2.py                      # dry-run（默认，不写库）
    python scripts/migrate_memory_bus_v2.py --execute            # 备份 + 实迁
    python scripts/migrate_memory_bus_v2.py --memory-db X --reflection-db Y --history-db Z
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from plugins.bot_unified_runtime.domains.chat_reply.character.memory_bus_v2 import (
    PROVENANCE_REFLECTED,
    MemoryBus,
    derive_scope,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.memory_store_v21 import (
    MemoryStoreV21,
)

# 全局可见的历史形态（与 reflection.facts_for 的读侧名单同口径，单一来源在总线侧
# 由 derive_scope 承担，这里只处理「旧库里已经写成通配」的三种字面量）。
_GLOBAL_SCOPE_KEYS = frozenset({"", "*", "global"})

# 本脚本自己的幂等探针前缀（真身只此一处：造键与对账都读它，禁第二份字面量）。
# 前缀唯一属于本迁移 ⇒ 「这一行是不是本脚本落的」按探针判，不按 ``source`` 列判，
# 见 ``_count_migrated_by_owner`` 的口径说明。
_MIGRATION_EVENT_PREFIX = "reflmig:"


class ConservationError(RuntimeError):
    """守恒断言失败——迁移被整体回滚。"""


@dataclass(frozen=True)
class LegacyFact:
    fact_id: str
    sender_id: str
    session_key: str
    fact_text: str
    category: str
    confidence: float
    created_at: str
    superseded: bool = False


@dataclass
class MigrationReport:
    legacy_total: int = 0
    legacy_active: int = 0
    planned: int = 0
    migrated: int = 0
    skipped_existing: int = 0
    skipped_forgotten: int = 0
    unresolved_scope: int = 0
    per_owner_before: dict[str, int] = field(default_factory=dict)
    per_owner_after: dict[str, int] = field(default_factory=dict)
    backup_dir: str = ""
    executed: bool = False

    def render(self) -> str:
        lines = [
            (
                "记忆总线 v2 迁移报告"
                f"（{'已执行' if self.executed else 'DRY-RUN 预览'}）"
            ),
            f"  反思库行：总计 {self.legacy_total}，未作废 {self.legacy_active}",
            f"  计划投递：{self.planned} 条；本次落库 {self.migrated} 条",
            (
                f"  已存在跳过 {self.skipped_existing} 条；"
                f"正当拒收跳过（已遗忘/硬线/无作用域）{self.skipped_forgotten} 条"
            ),
            (
                "  作用域未能从会话表还原（按原复合键落库，跨键不可见）："
                f"{self.unresolved_scope} 条"
            ),
        ]
        if self.backup_dir:
            lines.append(f"  备份目录：{self.backup_dir}")
        return "\n".join(lines)


def _connect_ro(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def read_legacy_facts(reflection_db: str | Path) -> list[LegacyFact]:
    path = Path(reflection_db)
    if not path.exists():
        return []
    connection = _connect_ro(path)
    try:
        tables = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "reflection_facts" not in tables:
            return []
        rows = connection.execute(
            """
            SELECT fact_id, sender_id, session_key, fact_text, category,
                   confidence, created_at, superseded
            FROM reflection_facts
            ORDER BY sender_id ASC, created_at ASC, fact_id ASC
            """
        ).fetchall()
    finally:
        connection.close()
    return [
        LegacyFact(
            fact_id=str(row["fact_id"]),
            sender_id=str(row["sender_id"]),
            session_key=str(row["session_key"] or ""),
            fact_text=str(row["fact_text"]),
            category=str(row["category"] or ""),
            confidence=float(row["confidence"] or 0.0),
            created_at=str(row["created_at"] or ""),
            superseded=int(row["superseded"] or 0) != 0,
        )
        for row in rows
    ]


def build_composite_index(history_db: str | Path | None) -> dict[str, str]:
    """复合键 → 裸会话键 的查表（**取自会话表实况，不做字符串拆分猜形**）。

    反思库的 session_key 是 ``f"{platform}:{session_id}"``（采集侧构造）。迁移要
    把它落回中央件认可的裸键，唯一可靠来源是 conversation_turns 里同款的
    (platform, session_id) 两列——按数据连接还原，而不是按分隔符切字符串。
    历史库缺失/已剪枝时查不到 ⇒ 调用方按 fail-closed 处理（保留复合键）。
    """
    if not history_db:
        return {}
    path = Path(history_db)
    if not path.exists():
        return {}
    connection = _connect_ro(path)
    try:
        rows = connection.execute(
            "SELECT DISTINCT platform, session_id FROM conversation_turns"
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        connection.close()
    return {
        f"{row['platform']}:{row['session_id']}": str(row["session_id"])
        for row in rows
        if str(row["platform"] or "").strip() and str(row["session_id"] or "").strip()
    }


def plan_migration(
    facts: list[LegacyFact], *, composite_index: dict[str, str]
) -> list[dict[str, Any]]:
    """纯函数：旧行 → 总线 absorb 参数（未作废行才迁；作用域按查表还原）。"""
    plans: list[dict[str, Any]] = []
    for fact in facts:
        if not fact.fact_id.strip() or not fact.sender_id.strip():
            continue
        if fact.superseded:
            # 旧库里已被 keep-newest 作废的行不迁入总线：它们本就召不回，
            # 迁过去等于把作废的旧说法重新变成候选（语义倒退）。
            continue
        if fact.session_key in _GLOBAL_SCOPE_KEYS:
            # 旧 global 形态 → global 空作用域。总线归纳侧「空作用域不配全局可见」
            # 闸（memory_bus_v2.absorb 的 unscoped_candidate 分支）会把这类行**正当
            # 拒收**——它们留在旧表、经旧路径/候选源仍可见，但结构上迁不进总线
            # （回归锁 test_legacy_global_rows_are_refused_not_faked）。生产现算 0 行
            # （2026-09-26）；切 target=bus 前必须复核此形态计数仍为 0，否则这批旧
            # 归纳行会从召回面消失。
            scope = derive_scope("")
            unresolved = False
        else:
            bare = composite_index.get(fact.session_key, "")
            scope = derive_scope(bare)
            unresolved = not bare
            if unresolved:
                # 还原失败：把原复合键当作会话键落库——等值判据下它与任何真实裸键
                # 都不相等 ⇒ 结构上召不回（宁可看不见，绝不让群聊私事跨会话可见）。
                scope = derive_scope(fact.session_key)
        plans.append(
            {
                "fact_id": fact.fact_id,
                "owner_id": fact.sender_id,
                "subject_user_id": fact.sender_id,
                "text": fact.fact_text,
                "category": fact.category,
                "confidence": max(0.0, min(1.0, fact.confidence)),
                "provenance": PROVENANCE_REFLECTED,
                "source": "reflection_migration",
                "scope": scope,
                "unresolved_scope": unresolved,
                "source_event_id": f"{_MIGRATION_EVENT_PREFIX}{fact.fact_id}",
            }
        )
    return plans


def assert_conservation(
    *,
    expected_by_owner: dict[str, int],
    migrated_by_owner: dict[str, int],
    legacy_total_before: int,
    legacy_total_after: int,
) -> None:
    """守恒断言：每个「该落库的」计划都必须真的在总线里有一行，且旧表总行数分毫未动。

    ``expected_by_owner`` = 计划投递数 − 正当拒收数（硬线/已遗忘），所以断言既不会被
    正当跳过误伤，也**绝不放过丢行**：负样本用例故意让投递环节吞掉一行，必须在此红。
    """
    if dict(expected_by_owner) != dict(migrated_by_owner):
        missing = {
            owner: count - migrated_by_owner.get(owner, 0)
            for owner, count in expected_by_owner.items()
            if migrated_by_owner.get(owner, 0) != count
        }
        raise ConservationError(f"迁移不守恒（按人差量）：{missing}")
    if legacy_total_before != legacy_total_after:
        raise ConservationError(
            "反思原表行数发生变化"
            f"（{legacy_total_before} → {legacy_total_after}）：迁移只准 INSERT 总线"
        )


def _backup(memory_db: str | Path, reflection_db: str | Path) -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    target = Path(tempfile.gettempdir()) / f"chatbot-memory-bus-migration-{stamp}"
    target.mkdir(parents=True, exist_ok=True)
    for path in (Path(memory_db), Path(reflection_db)):
        if path.exists():
            shutil.copy2(path, target / path.name)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(path) + suffix)
            if sidecar.exists():
                shutil.copy2(sidecar, target / sidecar.name)
    return str(target)


def migrate(
    *,
    memory_db: str | Path,
    reflection_db: str | Path,
    history_db: str | Path | None = None,
    execute: bool = False,
    config: object | None = None,
) -> MigrationReport:
    """迁移主流程（execute=False 只出计划与 dry-run 报告，绝不碰库）。"""
    facts = read_legacy_facts(reflection_db)
    total_before = len(facts)
    active = [fact for fact in facts if not fact.superseded]
    plans = plan_migration(active, composite_index=build_composite_index(history_db))
    report = MigrationReport(
        legacy_total=total_before,
        legacy_active=len(active),
        planned=len(plans),
        per_owner_before=dict(Counter(plan["owner_id"] for plan in plans)),
        unresolved_scope=sum(1 for plan in plans if plan["unresolved_scope"]),
    )
    if not execute:
        report.per_owner_after = dict(Counter(plan["owner_id"] for plan in plans))
        return report

    backup_dir = _backup(memory_db, reflection_db)
    report.backup_dir = backup_dir
    store = MemoryStoreV21(str(memory_db))
    bus = MemoryBus(store, config=_BusConfig(config))
    planned_by_owner: Counter[str] = Counter(plan["owner_id"] for plan in plans)
    rejected_by_owner: Counter[str] = Counter()
    for plan in plans:
        outcome = _absorb_one(bus, plan)
        if outcome in ("migrated", "skipped_existing"):
            report.migrated += 1 if outcome == "migrated" else 0
            report.skipped_existing += 1 if outcome == "skipped_existing" else 0
        else:
            # 正当拒收（硬线词面命中 / 用户已显式遗忘）：不迁，但要从守恒期望里扣掉。
            report.skipped_forgotten += 1
            rejected_by_owner[plan["owner_id"]] += 1
    total_after = len(read_legacy_facts(reflection_db))
    expected_by_owner = planned_by_owner - rejected_by_owner
    report.per_owner_after = dict(expected_by_owner)
    # 断言面：总线里由本脚本落的行按 ``reflmig:`` 探针逐人计数（口径见
    # ``_count_migrated_by_owner``——按 source 列数会在「同槽脏前置」下假红）。
    store_counts = _count_migrated_by_owner(store)
    assert_conservation(
        expected_by_owner=dict(expected_by_owner),
        migrated_by_owner=store_counts,
        legacy_total_before=total_before,
        legacy_total_after=total_after,
    )
    report.executed = True
    return report


def _absorb_one(bus: MemoryBus, plan: dict[str, Any]) -> str:
    existing = bus.store.find_by_source_event(
        owner_id=plan["owner_id"], source_event_id=plan["source_event_id"]
    )
    if existing is not None:
        return "skipped_existing"
    outcome = bus.absorb(
        owner_id=plan["owner_id"],
        subject_user_id=plan["subject_user_id"],
        text=plan["text"],
        session_id="",
        category=plan["category"],
        confidence=plan["confidence"],
        provenance=plan["provenance"],
        source=plan["source"],
        scope=plan["scope"],
        source_event_id=plan["source_event_id"],
        audit_only_reason="reflection_migration",
    )
    if outcome.action == "rejected":
        return f"rejected:{outcome.reason}"
    if outcome.action == "duplicate_skipped":
        return "skipped_existing"
    return "migrated"


def _count_migrated_by_owner(store: MemoryStoreV21) -> dict[str, int]:
    """总线里由本脚本落的行，按**幂等探针**逐人计数。

    尺子必须是探针而不是 ``source`` 列：``source`` 记的是「谁建的行」，而库里可能
    早有一行同槽事实（抽取腿先落，``source=llm_extract``、无探针）。迁移撞上它就是
    一次「带探针的确认」——只补空位、不抢写建行者那本账（锁见
    ``test_absorb_confirmed_does_not_steal_existing_probe``），于是按 ``source`` 数会把
    这次**真实完成**的迁移漏计成 0，守恒断言当场假红（ConservationError），而实际
    一行未丢。探针前缀唯一属于本迁移，补位成功即计数成立，重跑只命中不新增。
    """
    with store._lock:
        rows = store._connection.execute(
            "SELECT owner_id, COUNT(*) AS n FROM memory_entries_v21 "
            "WHERE substr(source_event_id, 1, length(?)) = ? GROUP BY owner_id",
            (_MIGRATION_EVENT_PREFIX, _MIGRATION_EVENT_PREFIX),
        ).fetchall()
    return {str(row["owner_id"]): int(row["n"]) for row in rows}


class _BusConfig:
    """迁移期最小配置面：总线常开 + 归纳落总线，其余取设计稿缺省。

    真配置里 ``bot_memory_bus_enabled`` 可能仍关（灰度未开），但「把旧归纳行搬进
    总线」这件事本身就是开总线的前置动作，故迁移强制按开态打分参数运行。
    """

    bot_memory_bus_enabled = True
    bot_memory_reflected_write_target = "bus"
    bot_memory_strength_k = 3.0
    bot_memory_tau_stable_days = 180
    bot_memory_tau_seasonal_days = 45
    bot_memory_tau_episodic_days = 14
    bot_memory_relevance_weights = ""
    bot_memory_per_category_max = 1
    bot_memory_semantic_recall_enabled = True

    def __init__(self, override: object | None = None) -> None:
        if override is None:
            return
        for name in (
            "bot_memory_strength_k",
            "bot_memory_tau_stable_days",
            "bot_memory_tau_seasonal_days",
            "bot_memory_tau_episodic_days",
            "bot_memory_relevance_weights",
            "bot_memory_per_category_max",
        ):
            value = getattr(override, name, None)
            if value is not None:
                setattr(self, name, value)


def _default_paths() -> tuple[str, str, str]:
    try:
        from load_runtime_config import load_runtime_config

        config = load_runtime_config()
        return (
            str(getattr(config, "bot_memory_db_path", "") or ""),
            str(getattr(config, "bot_reflection_db_path", "") or ""),
            str(getattr(config, "bot_history_db_path", "") or ""),
        )
    except Exception as exc:  # noqa: BLE001 - 配置装载不了就要求显式传参
        print(f"[warn] 配置装载失败，需显式 --memory-db/--reflection-db：{exc}")
        return "", "", ""


def main(argv: list[str] | None = None) -> int:
    memory_default, reflection_default, history_default = _default_paths()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-db", default=memory_default or None)
    parser.add_argument("--reflection-db", default=reflection_default or None)
    parser.add_argument("--history-db", default=history_default or None)
    parser.add_argument(
        "--execute", action="store_true", help="实迁（默认 dry-run，不写任何库）"
    )
    args = parser.parse_args(argv)
    if not args.memory_db or not args.reflection_db:
        print("缺少库路径：--memory-db / --reflection-db（或可装载的 .env）")
        return 2
    for path in (args.memory_db, args.reflection_db):
        if not Path(path).exists():
            print(f"库文件不存在：{path}")
            return 2
    report = migrate(
        memory_db=args.memory_db,
        reflection_db=args.reflection_db,
        history_db=args.history_db,
        execute=bool(args.execute),
    )
    print(report.render())
    if not args.execute and report.planned:
        print("  （dry-run：加 --execute 才落库；落库前自动整库备份到 %TEMP%）")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
