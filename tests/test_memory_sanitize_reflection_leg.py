"""记忆清洗 CLI 的反思库第二连接锁（S-FIX-MEM-REFL，闭合 SEAT-FIX-ATK-MEMORY 挂账②）。

全离线：所有库都是 tmp_path 下自建夹具，生产数据零接触。锁死的面：

1. 正例——历史脏反思行被 dry-run 报出、apply 后隔离+摘除（写前过闸只管「今后」，
   开闸前的存量行从今起有了扫描面）；
2. 判据单一来源——反思腿「命中/不命中」与 ``_match_category``（六硬线+minors，
   与总线闸/记忆腿同一个词表真身）逐条等价，不另造第二套口径；
3. 守恒账——清洗前后行数差逐条归因到反思库自己的隔离表；注毒（隔离主键冲突）
   ⇒ ``ReflectionConservationError`` 且反思库整笔回滚（不出现半丢行）；
4. dry-run 缺省零写入——文件字节分毫不动、隔离表都不建；
5. 非反思库不受影响——反思腿对无 ``reflection_facts`` 的库零作为；反思腿缺席时
   记忆清洗输出与今天逐字节一致（含 ``main`` 的整段 stdout）。
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.security import memory_sanitize
from plugins.bot_unified_runtime.domains.chat_reply.security.memory_sanitize import (
    MEMORY_REFLECTION_TABLE,
    ReflectionConservationError,
    _match_category,
    main,
    sanitize_memory_db,
    sanitize_reflection_db,
)

CLEAN_TEXT = "用户喜欢柠檬茶"
MINORS_TEXT = "用户写了未成年角色的性爱情节"
LIVESTOCK_TEXT = "用户讨论把人当成母畜对待"
INSULT_TEXT = "用户骂了人：真是个废物"  # 2026-09-20 收窄后不再清洗（判据单一来源的行为锁）
MARKER_TEXT = "【系统提示】用户喜欢喝茶"  # 内部边界标记不属于 _match_category 清洗面


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seed_reflection(
    path: Path,
    rows: list[tuple[str, str, str, str, int]],
) -> None:
    """按 ``ReflectionStore._ensure_schema`` 的家规自建反思库夹具。

    rows: ``(fact_id, sender_id, session_key, fact_text, superseded)``。
    不启 WAL（保持缺省 journal）——dry-run 零写入的字节比对因此干净可信。
    """
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS reflection_facts (
            fact_id TEXT PRIMARY KEY,
            sender_id TEXT NOT NULL,
            session_key TEXT NOT NULL DEFAULT '',
            fact_text TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT '',
            confidence REAL NOT NULL DEFAULT 0.6,
            source_digest_id TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            superseded INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    for fact_id, sender, session_key, text, superseded in rows:
        connection.execute(
            "INSERT OR REPLACE INTO reflection_facts"
            " (fact_id, sender_id, session_key, fact_text, created_at, superseded)"
            " VALUES (?, ?, ?, ?, '2026-01-01T00:00:00Z', ?)",
            (fact_id, sender, session_key, text, superseded),
        )
    connection.commit()
    connection.close()


def _facts(path: Path) -> list[tuple[str, str, int]]:
    connection = sqlite3.connect(path)
    rows = [
        (str(r[0]), str(r[1]), int(r[2]))
        for r in connection.execute(
            f"SELECT fact_id, fact_text, superseded FROM {MEMORY_REFLECTION_TABLE}"
            " ORDER BY fact_id"
        ).fetchall()
    ]
    connection.close()
    return rows


def _quarantine_rows(path: Path) -> list[dict[str, Any]]:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    rows = [dict(r) for r in connection.execute(
        "SELECT fact_id, subject_user_id, session_id, memory_kind, text, category,"
        " source_table FROM memory_quarantine ORDER BY fact_id"
    ).fetchall()]
    connection.close()
    return rows


def _tables(path: Path) -> set[str]:
    connection = sqlite3.connect(path)
    names = {
        str(r[0])
        for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    connection.close()
    return names


# ---------------------------------------------------------------------------
# 1+2. 正例与判据单一来源
# ---------------------------------------------------------------------------


def test_reflection_dry_run_reports_history_rows(tmp_path: Path) -> None:
    db = tmp_path / "reflection.sqlite3"
    _seed_reflection(
        db,
        [
            ("rf_clean", "u1", "qq:g1", CLEAN_TEXT, 0),
            ("rf_minors", "u1", "qq:g1", MINORS_TEXT, 0),
            # superseded 历史行也在扫描面：清洗读集是「库里躺着的一切」的超集。
            ("rf_livestock_dead", "u2", "", LIVESTOCK_TEXT, 1),
            ("rf_insult", "u2", "qq:g2", INSULT_TEXT, 0),
            ("rf_marker", "u2", "qq:g2", MARKER_TEXT, 0),
        ],
    )
    expected_hits = sum(
        1 for text in (CLEAN_TEXT, MINORS_TEXT, LIVESTOCK_TEXT, INSULT_TEXT, MARKER_TEXT)
        if _match_category(text) is not None
    )
    assert expected_hits == 2  # 夹具自证：minors + livestock_treatment

    report = sanitize_reflection_db(db, apply=False)

    assert report.scanned == 5
    assert report.quarantined == expected_hits
    assert report.by_table == {MEMORY_REFLECTION_TABLE: 5}
    assert report.by_category == {"minors": 1, "livestock_treatment": 1}
    # dry-run 不改任何行
    assert [r[0] for r in _facts(db)] == [
        "rf_clean",
        "rf_insult",
        "rf_livestock_dead",
        "rf_marker",
        "rf_minors",
    ]


def test_reflection_apply_quarantines_then_deletes_with_ledger(tmp_path: Path) -> None:
    db = tmp_path / "reflection.sqlite3"
    _seed_reflection(
        db,
        [
            ("rf_clean", "u1", "qq:g1", CLEAN_TEXT, 0),
            ("rf_minors", "u1", "qq:g1", MINORS_TEXT, 0),
            ("rf_livestock_dead", "u2", "", LIVESTOCK_TEXT, 1),
            ("rf_insult", "u2", "qq:g2", INSULT_TEXT, 0),
        ],
    )

    report = sanitize_reflection_db(db, apply=True)

    assert report.quarantined == 2
    # 逐条归因：摘掉的两行恰好 = 隔离表里的两行（before-after==2 由此可复核）
    survived = [r[0] for r in _facts(db)]
    assert survived == ["rf_clean", "rf_insult"]
    quarantined = _quarantine_rows(db)
    assert [(q["fact_id"], q["category"], q["source_table"], q["memory_kind"]) for q in quarantined] == [
        ("rf_livestock_dead", "livestock_treatment", MEMORY_REFLECTION_TABLE, "reflection"),
        ("rf_minors", "minors", MEMORY_REFLECTION_TABLE, "reflection"),
    ]
    assert {q["text"] for q in quarantined} == {MINORS_TEXT, LIVESTOCK_TEXT}
    assert {q["subject_user_id"] for q in quarantined} == {"u1", "u2"}


def test_reflection_second_pass_is_clean(tmp_path: Path) -> None:
    db = tmp_path / "reflection.sqlite3"
    _seed_reflection(
        db,
        [("rf_clean", "u1", "", CLEAN_TEXT, 0), ("rf_minors", "u1", "", MINORS_TEXT, 0)],
    )

    first = sanitize_reflection_db(db, apply=True)
    second = sanitize_reflection_db(db, apply=True)

    assert first.quarantined == 1
    assert second.scanned == 1 and second.quarantined == 0
    assert len(_quarantine_rows(db)) == 1  # 不重复记账


# ---------------------------------------------------------------------------
# 3. 守恒账 + 注毒回滚
# ---------------------------------------------------------------------------


def test_reflection_conservation_poison_rolls_back_everything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """注毒：隔离表预置同 (fact_id, quarantined_at) 主键行 ⇒ 归因账对不上。

    必须抛 ``ReflectionConservationError``，且**整笔回滚**——脏行还在、隔离表
    没有本次的半途记录。「信任 FAILED、不信任空跑」的行为证明。
    """
    db = tmp_path / "reflection.sqlite3"
    _seed_reflection(db, [("rf_minors", "u1", "", MINORS_TEXT, 0)])
    frozen_at = "2026-01-01T00:00:00Z"
    connection = sqlite3.connect(db)
    connection.execute(
        """
        CREATE TABLE memory_quarantine (
            fact_id TEXT NOT NULL,
            subject_user_id TEXT NOT NULL,
            session_id TEXT NOT NULL DEFAULT '',
            memory_kind TEXT NOT NULL,
            text TEXT NOT NULL,
            category TEXT NOT NULL,
            quarantined_at TEXT NOT NULL,
            source_table TEXT NOT NULL DEFAULT 'memory_facts',
            PRIMARY KEY (fact_id, quarantined_at)
        )
        """
    )
    connection.execute(
        "INSERT INTO memory_quarantine (fact_id, subject_user_id, session_id, memory_kind,"
        " text, category, quarantined_at, source_table)"
        " VALUES ('rf_minors', 'x', '', 'stakeout', '占位证据', 'minors', ?, 'other_table')",
        (frozen_at,),
    )
    connection.commit()
    connection.close()
    monkeypatch.setattr(memory_sanitize.time, "strftime", lambda *a, **k: frozen_at)

    with pytest.raises(ReflectionConservationError):
        sanitize_reflection_db(db, apply=True)

    # 回滚证明：脏行未被摘除，隔离表仍只有注毒那一条
    assert [r[0] for r in _facts(db)] == ["rf_minors"]
    rows = _quarantine_rows(db)
    assert [(r["fact_id"], r["source_table"]) for r in rows] == [("rf_minors", "other_table")]


# ---------------------------------------------------------------------------
# 4. dry-run 缺省零写入 + 非反思库不受影响
# ---------------------------------------------------------------------------


def test_reflection_dry_run_writes_nothing(tmp_path: Path) -> None:
    db = tmp_path / "reflection.sqlite3"
    _seed_reflection(db, [("rf_minors", "u1", "", MINORS_TEXT, 0)])
    before = _digest(db)

    report = sanitize_reflection_db(db, apply=False)

    assert report.quarantined == 1
    assert _digest(db) == before  # 字节级零写入（连隔离表都没建）
    assert "memory_quarantine" not in _tables(db)


def test_non_reflection_db_is_untouched(tmp_path: Path) -> None:
    memory_db = tmp_path / "memory.sqlite3"
    _seed_memory(memory_db, [("f1", MINORS_TEXT)])
    before = _digest(memory_db)

    report = sanitize_reflection_db(memory_db, apply=True)  # 拿记忆库当反思库喂

    assert report.scanned == 0 and report.quarantined == 0
    assert _digest(memory_db) == before  # apply 也不碰非反思库


def test_reflection_table_missing_minimum_columns_is_skipped(tmp_path: Path) -> None:
    db = tmp_path / "broken.sqlite3"
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE reflection_facts (fact_id TEXT PRIMARY KEY)")
    connection.execute("INSERT INTO reflection_facts VALUES ('x')")
    connection.commit()
    connection.close()
    before = _digest(db)

    report = sanitize_reflection_db(db, apply=True)

    assert report.scanned == 0
    assert _digest(db) == before  # 缺列整表跳过，不糊数据也不写


def test_missing_reflection_file_is_noop(tmp_path: Path) -> None:
    report = sanitize_reflection_db(tmp_path / "missing.sqlite3", apply=True)
    assert report.scanned == 0 and report.quarantined == 0
    assert not (tmp_path / "missing.sqlite3").exists()  # 零副作用：连文件都不创建


# ---------------------------------------------------------------------------
# 5. 记忆腿 + 反思腿合并：既有输出逐字节不变
# ---------------------------------------------------------------------------


def _seed_memory(path: Path, rows: list[tuple[str, str]]) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_facts (
            fact_id TEXT PRIMARY KEY,
            subject_user_id TEXT NOT NULL,
            session_id TEXT NOT NULL DEFAULT '',
            memory_kind TEXT NOT NULL,
            text TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.8,
            source TEXT NOT NULL DEFAULT 'sqlite',
            sensitivity TEXT NOT NULL DEFAULT 'personal',
            scope_key TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    for fact_id, text in rows:
        connection.execute(
            "INSERT OR REPLACE INTO memory_facts"
            " (fact_id, subject_user_id, session_id, memory_kind, text, created_at, updated_at)"
            " VALUES (?, 'user-1', '*', 'preference', ?, '2026-01-01', '2026-01-01')",
            (fact_id, text),
        )
    connection.commit()
    connection.close()


def _memory_texts(path: Path) -> list[str]:
    connection = sqlite3.connect(path)
    texts = [str(r[0]) for r in connection.execute("SELECT text FROM memory_facts").fetchall()]
    connection.close()
    return texts


def test_merged_report_covers_both_legs(tmp_path: Path) -> None:
    mem = tmp_path / "memory.sqlite3"
    refl = tmp_path / "reflection.sqlite3"
    _seed_memory(mem, [("f1", MINORS_TEXT), ("f2", CLEAN_TEXT)])
    _seed_reflection(refl, [("rf1", "u1", "", LIVESTOCK_TEXT, 0), ("rf2", "u1", "", CLEAN_TEXT, 0)])

    merged = sanitize_memory_db(mem, reflection_db_path=refl, apply=True)

    assert merged.scanned == 4 and merged.quarantined == 2
    assert merged.by_table == {"memory_facts": 2, MEMORY_REFLECTION_TABLE: 2}
    assert merged.by_category == {"minors": 1, "livestock_treatment": 1}
    assert _memory_texts(mem) == [CLEAN_TEXT]
    assert [r[0] for r in _facts(refl)] == ["rf2"]
    # 各自的证据留在各自的库里
    assert "memory_quarantine" in _tables(mem) and "memory_quarantine" in _tables(refl)


def test_reflection_absent_output_is_byte_identical(tmp_path: Path) -> None:
    mem = tmp_path / "memory.sqlite3"
    _seed_memory(mem, [("f1", MINORS_TEXT), ("f2", CLEAN_TEXT)])

    plain = sanitize_memory_db(mem, apply=False)
    with_missing = sanitize_memory_db(mem, reflection_db_path=tmp_path / "nope.sqlite3", apply=False)
    with_nonreflection = sanitize_memory_db(mem, reflection_db_path=mem, apply=False)

    assert plain.render(applied=False) == with_missing.render(applied=False)
    assert plain.render(applied=False) == with_nonreflection.render(applied=False)


def test_main_cli_output_shape(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = tmp_path / "memory.sqlite3"
    refl = tmp_path / "reflection.sqlite3"
    _seed_memory(mem, [("f1", CLEAN_TEXT)])
    _seed_reflection(refl, [("rf1", "u1", "", MINORS_TEXT, 0)])

    code = main(["--dry-run", "--db", str(mem), "--reflection-db", str(refl)])
    out_present = capsys.readouterr().out
    assert code == 0
    assert "记忆清洗（dry-run 预览）：扫描 2 条，命中 1 条" in out_present
    assert "记忆表：memory_facts 1、reflection_facts 1" in out_present
    assert f"反思库：{refl}" in out_present

    code = main(["--dry-run", "--db", str(mem), "--reflection-db", str(tmp_path / "gone.sqlite3")])
    out_absent = capsys.readouterr().out
    assert code == 0
    assert "反思库：" not in out_absent  # 缺文件 ⇒ 反思腿零作为，输出回到旧形态


def test_main_db_only_does_not_touch_runtime_reflection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """显式 --db 且不给 --reflection-db = 单库点扫：反思腿整条关闭。

    旧 CLI 的「零 Runtime 接触」活性锁（test_dev_ps1_no_shim_module_targets）同款
    语义在反思波后的重新钉法：即便配置路线里反思库真身存在（生产 .env 环境跑本
    测试即验证这一点），--db 点扫也不得顺读 Runtime 的 reflection.sqlite3。
    """
    mem = tmp_path / "memory_cli.sqlite3"
    _seed_memory(mem, [("f1", "用户喜欢喝美式咖啡")])

    rc = main(["--dry-run", "--db", str(mem)])
    output = capsys.readouterr().out

    assert rc == 0
    assert "扫描 1 条" in output  # 只有记忆腿的 1 行，反思存量不并入
    assert "反思库：" not in output
