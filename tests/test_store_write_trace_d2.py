"""写路径留痕三件锁（2026-10-02 席 D2，用户报「数据库也没有更新」那一案的产出）。

三条线一把尺：

① **形状漂移不得再被 fail-open 吞掉**：生产 ``reply_policy.sqlite3`` 的
   ``person_imagery_usage`` 停在旧形状 ``(person_key, family, used_at)``，代码写的是
   ``(person_key, families, updated_at)`` ⇒ 两条腿每次 ``OperationalError``、被
   ``except`` 吞成「本轮没用过意象」，盘上 0 行、日志零痕。现算证据＝
   :func:`_legacy_imagery_shape` 造的同一形状，改前必红（注毒腿另有 ③）。

② **写路径被调用必须留可见痕迹**：三枚库的每一个公开写口调用一次就出一格痕，
   失败记 ``failed``、被拒记 ``refused``、什么都不该写记 ``noop``。
   :func:`test_write_methods_all_record_trace_by_ast` 是机械门：新增写口不记账即红。

③ **fail-open 一格都不许改**：写腿坏了只降级（返回 False / 抛原异常），
   绝不让一条聊天消息或一轮 prompt 渲染被带走。

另附**盘上读数**的口径锁：WAL 库主文件 mtime 停更**不是**停写——
生产 ``reply_policy`` 主文件停在 10-01 01:18 而 ``-wal`` 与 ``max(updated_at)`` 都在 18:22，
席 D2 就是被这一格绊住的；:func:`test_disk_write_state_names_wal_lag_not_staleness` 钉死判据。
"""

from __future__ import annotations

import ast
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.control_plane.config_store import (
    ConfigVersionConflict,
    SQLiteConfigStateStore,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.quirks import QuirkStore
from plugins.bot_unified_runtime.domains.chat_reply.character.reply_policy import (
    LENGTH_MODE_VERBOSE,
    ReplyPolicy,
    ReplyPolicyStore,
)
from plugins.bot_unified_runtime.domains.core.write_trace import (
    OUTCOME_FAILED,
    OUTCOME_NOOP,
    OUTCOME_OK,
    OUTCOME_REFUSED,
    disk_write_state,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]

#: 三枚停更库的写侧真身（席 D2 独占面）；静态门按类逐个核公开写口。
_WRITE_SIDE_TARGETS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "domains/chat_reply/character/reply_policy.py",
        "ReplyPolicyStore",
        ("put", "clear", "record_imagery_use", "_move_imagery_usage"),
    ),
    (
        "domains/chat_reply/character/quirks.py",
        "QuirkStore",
        ("propose", "approve", "retire", "add_direct"),
    ),
    (
        "control_plane/config_store.py",
        "SQLiteConfigStateStore",
        ("_change", "import_legacy"),
    ),
)

#: 静态门认这一形＝这一腿记过账：AST 层「调了一枚名为 ``_record`` / ``record`` 的方法」。
#: 刻意按**调用节点**判而不是按子串判——把留痕抹成 ``pass  # _record(...)`` 这种注释
#: 形态是想骗过文本尺的（席 D2 写这把尺时自己踩过，注毒腿当场不红）。
_TRACE_METHOD_NAMES = frozenset({"_record", "record"})

_IMAGERY_LEGACY_DDL = """
CREATE TABLE person_imagery_usage (
    person_key TEXT NOT NULL,
    family TEXT NOT NULL,
    used_at TEXT NOT NULL,
    PRIMARY KEY (person_key, family)
)
"""


def _legacy_imagery_shape(db: Path, rows: list[tuple[str, str, str]] | None = None) -> None:
    """把意象账摆成**生产实测的旧形状**（席 D2 普查读数：列＝person_key/family/used_at）。"""
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("DROP TABLE IF EXISTS person_imagery_usage")
        conn.execute(_IMAGERY_LEGACY_DDL)
        conn.executemany(
            "INSERT INTO person_imagery_usage (person_key, family, used_at) VALUES (?, ?, ?)",
            rows or [],
        )
        conn.commit()
    finally:
        conn.close()


def _imagery_columns(db: Path) -> set[str]:
    conn = sqlite3.connect(str(db))
    try:
        found = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(person_imagery_usage)").fetchall()
        }
    finally:
        conn.close()
    return found


def _table_names(db: Path) -> set[str]:
    conn = sqlite3.connect(str(db))
    try:
        return {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    finally:
        conn.close()


def _rename_away(db: Path, table: str) -> None:
    """注毒用：把某枚表改名 ⇒ 让写腿真炸一次 ``OperationalError``（不造桩、不改代码）。

    刻意不留未提交的事务：那会握住写锁，把后面的读数打成 ``database is locked``
    ——本席踩过一次，别把「锁」的读数当成「形状/写腿」的读数。
    """
    conn = sqlite3.connect(str(db))
    conn.execute(f"ALTER TABLE {table} RENAME TO {table}_gone")
    conn.commit()
    conn.close()


def _last_entry(store: object, op: str = "") -> dict[str, str]:
    """读该 store 留痕的最近一笔（``op`` 给定时只看那一腿）；空账当场判红。"""
    recent = store.write_trace()["recent"]  # type: ignore[attr-defined]
    if op:
        recent = [item for item in recent if item["op"] == op]
    assert recent, f"写腿 {op or '(任意)'} 调用过却一格痕都没有"
    return recent[-1]


def _policy(person_key: str, **changes: object) -> ReplyPolicy:
    payload: dict[str, object] = {
        "person_key": person_key,
        "length_mode": LENGTH_MODE_VERBOSE,
        "content_directives": ("break_down_everything",),
        "note": "每条回复都带一句晚安",
        "evidence": "以后讲详细一点",
    }
    payload.update(changes)
    return ReplyPolicy(**payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ① 意象用量账的形状漂移：改前必红（生产形状原样复刻）
# ---------------------------------------------------------------------------


def test_legacy_imagery_shape_migrates_and_lands(tmp_path: Path) -> None:
    db = tmp_path / "reply_policy.sqlite3"
    store = ReplyPolicyStore(db)
    assert store.put(_policy("888000999")) is True
    store.close()
    _legacy_imagery_shape(db, [("777000888", "潮汐", "2026-09-30T10:00:00+00:00")])

    # 构造一次＝搬家一次；旧形状不许再用「CREATE TABLE IF NOT EXISTS」蒙过去。
    migrated = ReplyPolicyStore(db)
    assert _imagery_columns(db) >= {"families", "updated_at"}
    assert migrated.record_imagery_use("777000888", ["星轨", "琴键"]) is True

    # 换一个 store 对象读同一枚文件才叫落库（内存态自证不算）；旧形状那本的账**不丢**，
    # 新→旧排在后面＝搬家与本轮派族合起来的那只窗口。
    peer = ReplyPolicyStore(db)
    assert peer.recent_imagery_families("777000888") == ["星轨", "琴键", "潮汐"]
    assert _last_entry(migrated, "imagery_use")["outcome"] == OUTCOME_OK
    assert migrated.write_counts()["ok"] >= 2  # 搬家那一格 + 写账那一格
    peer.close()
    migrated.close()
    store.close()


def test_current_shape_is_left_untouched(tmp_path: Path) -> None:
    """反向不误伤：已经是现行形状的库，构造时一枚列都不许动、也不许多出归档表。"""
    db = tmp_path / "reply_policy.sqlite3"
    ReplyPolicyStore(db).close()
    before = _table_names(db)
    second = ReplyPolicyStore(db)
    assert _table_names(db) == before
    assert not [name for name in before if "legacy" in name]
    assert _last_entry(second, "imagery_schema")["outcome"] == OUTCOME_NOOP
    second.close()


def test_imagery_migration_failure_does_not_kill_the_policy_leg(tmp_path: Path) -> None:
    """搬不动只关那一本账：策略主表那条腿照读照写（fail-open 不许升级成整链打烊）。"""
    db = tmp_path / "reply_policy.sqlite3"
    victim = ReplyPolicyStore(db)

    def _boom() -> str:
        raise sqlite3.OperationalError("simulated schema leg bust")

    victim._reconcile_imagery_table = _boom  # type: ignore[method-assign]
    victim._ensure_schema()  # 不抛＝合格
    assert victim.put(_policy("700000111")) is True
    assert _last_entry(victim, "imagery_schema")["outcome"] == OUTCOME_FAILED
    victim.close()


def test_alias_row_move_lands_and_records_the_move(tmp_path: Path) -> None:
    """并号搬家（台账 #66★「并号只并偏好键**不并权限**」）的写入半边也得留痕。

    本函数同时钉住本席抓到并修掉的第二枚「该写没写」：``read_policy`` 的搬家腿写的是
    「意象账跟着同一次搬家走」，而旧实现拿 :meth:`recent_imagery_families` 去读旧号——
    那一口会先把旧号 **canonical 化成新号**，于是旧行永远读不到（合到零），紧接着
    ``_delete_key(旧号)`` 把那本账整个删掉。现算复现＝留痕里写着 ``families=0``、
    新号账是空表。修法＝搬家那一腿改吃**字面键**（:meth:`_families_of_raw`，只多一口
    不做归一的读法，判据与解码仍同一条），不许出现第二套 JSON 折形。
    """
    db = tmp_path / "reply_policy.sqlite3"
    side_number = ReplyPolicyStore(db)  # 并号之前：那一行写在侧号上
    side_number.put(_policy("3865067623", note="钉过一句"))
    assert side_number.record_imagery_use("3865067623", ["潮汐", "琴键"]) is True
    assert side_number.recent_imagery_families("3865067623") == ["潮汐", "琴键"]
    side_number.close()

    merged = ReplyPolicyStore(db, person_aliases={"3865067623": "1722380002"})
    policy, readable = merged.read_policy("1722380002")
    assert readable and policy is not None and policy.note == "钉过一句"
    assert _last_entry(merged, "imagery_move")["outcome"] == OUTCOME_OK
    # 旧侧号不许留第二份真身（「撤了又回来」那一案的同族）——策略行确实搬走了。
    latecomer = ReplyPolicyStore(db)
    assert latecomer.get("3865067623") is None
    # 意象账跟着同一次搬家走（``read_policy`` 自己写的口径：否则并号前后换两套轮换窗口）。
    assert merged.recent_imagery_families("1722380002") == ["潮汐", "琴键"]
    assert _last_entry(merged, "imagery_move")["detail"] == "families=2"
    latecomer.close()
    merged.close()


def test_legacy_rows_are_carried_over_and_archived_not_dropped(tmp_path: Path) -> None:
    db = tmp_path / "reply_policy.sqlite3"
    first = ReplyPolicyStore(db)
    first.close()
    # 旧形状的主键是 (person_key, family) ⇒ 同人同族**存不下两行**，本函数按新→旧折窗口，
    # 顺带钉住「窗口外的旧账不搬」（超上限那几族留在归档表里，不许悄悄挤掉别的）。
    rows = [
        ("p1", "潮汐", "2026-09-30T10:00:00+00:00"),
        ("p1", "星轨", "2026-09-30T11:00:00+00:00"),
        ("p1", "琴键", "2026-09-30T09:00:00+00:00"),
        ("p2", "金属", "2026-09-29T08:00:00+00:00"),
    ]
    _legacy_imagery_shape(db, rows)

    second = ReplyPolicyStore(db)
    # 同人各族按 used_at 新→旧折成现行的一人一行窗口。
    assert second.recent_imagery_families("p1") == ["星轨", "潮汐", "琴键"]
    assert second.recent_imagery_families("p2") == ["金属"]

    conn = sqlite3.connect(str(db))
    try:
        names = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert any(name.startswith("person_imagery_usage_legacy") for name in names), names
        # 归档表里旧行一枚不少（运行数据不可删＝AGENTS 规则 2）。
        archived = min(name for name in names if name.startswith("person_imagery_usage_legacy"))
        assert conn.execute(f"SELECT count(*) FROM {archived}").fetchone()[0] == len(rows)
    finally:
        conn.close()
    second.close()


def test_unrecognisable_imagery_shape_renames_aside_and_keeps_db(tmp_path: Path) -> None:
    db = tmp_path / "reply_policy.sqlite3"
    ReplyPolicyStore(db).close()
    conn = sqlite3.connect(str(db))
    conn.execute("DROP TABLE person_imagery_usage")
    conn.execute("CREATE TABLE person_imagery_usage (person_key TEXT, nonsense TEXT)")
    conn.execute("INSERT INTO person_imagery_usage VALUES ('p1', 'x')")
    conn.commit()
    conn.close()

    store = ReplyPolicyStore(db)
    assert _imagery_columns(db) >= {"families", "updated_at"}
    # 认不出的形状**不猜内容**，但整表改名留在盘上。
    conn = sqlite3.connect(str(db))
    try:
        names = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert any(name.startswith("person_imagery_usage_legacy") for name in names), names
    finally:
        conn.close()
    assert store.write_trace()["by_op"]["imagery_schema"]["ok"] >= 1
    store.close()


# ---------------------------------------------------------------------------
# ② 写路径留痕：三枚库逐个「调用过就有痕、做对了不误伤」
# ---------------------------------------------------------------------------


def test_reply_policy_write_records_trace_and_roundtrips_disk(tmp_path: Path) -> None:
    db = tmp_path / "reply_policy.sqlite3"
    store = ReplyPolicyStore(db)
    # 起点：put 那一腿一格都没有（构造只出 imagery_schema 的 noop，两码事）。
    assert OUTCOME_OK not in store.write_trace()["by_op"].get("put", {})
    assert store.put(_policy("700000001")) is True
    assert _last_entry(store, "put")["outcome"] == OUTCOME_OK
    # 落库＝另一个 store 对象读同一枚文件拿得到（不是内存态自证）。
    reader = ReplyPolicyStore(db)
    assert reader.get("700000001") is not None
    assert store.clear("700000001") is True
    assert _last_entry(store, "clear")["outcome"] == OUTCOME_OK
    after_clear = ReplyPolicyStore(db)
    assert after_clear.get("700000001") is None
    store.close()
    reader.close()
    after_clear.close()


def test_reply_policy_failed_write_leaves_failed_trace_without_raising(tmp_path: Path) -> None:
    """注毒：主表被改名 ⇒ ``put`` 返回 False、痕里写 ``failed``、一个异常都不递出去。"""
    db = tmp_path / "reply_policy.sqlite3"
    store = ReplyPolicyStore(db)
    _rename_away(db, "user_reply_policy")

    assert store.put(_policy("700000002")) is False  # fail-open：不许阻断聊天
    entry = _last_entry(store, "put")
    assert entry["outcome"] == OUTCOME_FAILED and entry["detail"] == "OperationalError"
    # 「读不出来」≠「这人没说过」（台账 #67★）——这一格区分也得现算得出，写腿据此拒写。
    assert store.read_policy("700000002") == (None, False)

    # 同一条写腿的 noop 那一格也在账上：键构造不出来＝本应写而什么都没写。
    noop = ReplyPolicyStore(tmp_path / "noop.sqlite3")
    assert noop.put(_policy("")) is False
    assert _last_entry(noop, "put")["outcome"] == OUTCOME_NOOP
    store.close()
    noop.close()


def test_quirks_every_write_call_records_one_entry(tmp_path: Path) -> None:
    store = QuirkStore(tmp_path / "persona_quirks.sqlite3")
    quirk = store.propose("句尾会悄悄带一个波浪号", "reflection:day1")
    assert _last_entry(store, "propose")["outcome"] == OUTCOME_OK
    assert store.propose("句尾会悄悄带一个波浪号", "reflection:day2") is not None
    # 去重命中＝什么都没写，也要留痕（否则「投了没投」只能靠行数猜）。
    assert _last_entry(store, "propose")["outcome"] == OUTCOME_NOOP
    assert store.approve(quirk.quirk_id) is True
    assert store.approve(quirk.quirk_id) is False  # 已 active ⇒ noop
    assert _last_entry(store, "approve")["outcome"] == OUTCOME_NOOP
    assert store.retire(quirk.quirk_id) is True
    assert _last_entry(store, "retire")["outcome"] == OUTCOME_OK
    assert store.add_direct("偶尔把潮水声当节拍", "admin").status == "active"
    assert _last_entry(store, "add_direct")["outcome"] == OUTCOME_OK
    by_op = store.write_trace()["by_op"]
    for op in ("propose", "approve", "retire", "add_direct"):
        assert sum(by_op[op].values()) >= 1, op
    # 消毒闸拒入也留痕：这一格以前完全看不见（提案侧的「该写没写」）。
    with pytest.raises(ValueError):
        store.propose("   ")
    assert _last_entry(store, "propose")["outcome"] == OUTCOME_REFUSED
    # 落库＝换一个 store 对象读同一枚文件（active 一条、render 非空）。
    peer = QuirkStore(tmp_path / "persona_quirks.sqlite3")
    assert [item.quirk_text for item in peer.list_active()] == ["偶尔把潮水声当节拍"]
    assert "小习惯" in peer.render_prompt_section()


def test_quirks_storage_failure_records_failed_and_still_raises(tmp_path: Path) -> None:
    """注毒：评审表被改名 ⇒ 痕里 ``failed``，异常照旧递给调用方（语义一字未动）。

    ⚠ 分层在这儿钉死：quirks **store 层的读腿本来就会抛**（改前改后一样），
    fail-open 住在调用方 ``providers.py`` 的 quirk 段 ``try/except``（现读 providers:505-513）
    ——本席一格都没动这个分层，也不许把阻断面上移进 store。
    """
    db = tmp_path / "persona_quirks.sqlite3"
    store = QuirkStore(db)
    _rename_away(db, "persona_quirks")
    with pytest.raises(sqlite3.OperationalError):
        store.propose("会炸的一条", "reflection:day3")
    entry = _last_entry(store, "propose")
    assert entry["outcome"] == OUTCOME_FAILED and entry["detail"] == "OperationalError"
    assert store.write_counts()["failed"] >= 1
    with pytest.raises(sqlite3.OperationalError):
        store.render_prompt_section()


def test_config_store_records_ok_refused_and_failed(tmp_path: Path) -> None:
    backend = SQLiteConfigStateStore(tmp_path / "control_plane_config.sqlite3", instance="default")
    assert backend.write_counts()["total"] == 0  # 构造不写账（＝「mtime 假象」的一半证据）
    snap = backend.set_override("BOT_REPLY_DETAIL", "detail", expected_version=0, actor="席D2")
    assert snap.version == 1
    assert _last_entry(backend, "set")["outcome"] == OUTCOME_OK
    # 落库＝独立对象读同一枚文件（覆盖册本来就无缓存，这条同时锁住 CAS 与审计行）。
    peer = SQLiteConfigStateStore(tmp_path / "control_plane_config.sqlite3", instance="default")
    assert peer.snapshot().overrides["BOT_REPLY_DETAIL"] == "detail"
    assert peer.write_counts()["total"] == 0  # 只读不写＝账上一格都不许有
    assert len(backend.changes()) == 1 and backend.changes()[0]["action"] == "set"

    with pytest.raises(ConfigVersionConflict):
        peer.set_override("BOT_REPLY_DETAIL", "concise", expected_version=99, actor="席D2")
    # 别人的失败不记进本 store 的账（每枚 store 一本环形账，禁串）。
    assert backend.write_counts()["total"] == 1
    assert _last_entry(peer, "set")["outcome"] == OUTCOME_REFUSED

    with pytest.raises(KeyError):
        peer.set_override("BOT_NOT_REGISTERED", "x", expected_version=1, actor="席D2")
    assert peer.write_trace()["by_op"]["set"][OUTCOME_REFUSED] == 2

    db = tmp_path / "cp_failed.sqlite3"
    victim = SQLiteConfigStateStore(db, instance="default")
    _rename_away(db, "config_instances")
    with pytest.raises(sqlite3.OperationalError):
        victim.set_override("BOT_REPLY_DETAIL", "detail", expected_version=0, actor="席D2")
    assert _last_entry(victim, "set")["outcome"] == OUTCOME_FAILED


def test_legacy_import_seal_touches_disk_without_any_audit_row(tmp_path: Path) -> None:
    """坐实「动盘 ≠ 拨开关」：legacy 无可导入键时**封口写动了 mtime、审计 0 行**。

    本案定性的直接证据。生产 ``control_plane_config.sqlite3`` 主文件停在 10-01 01:38:51，
    而 ``config_audit`` 最后一行是 09-27 的 v14——本函数的封口写、以及同库同意账
    （``safetyexec_*`` 的状态 UPDATE，见 ``domains/core/safety_exec/consent.py`` 就在这枚
    文件上建表）两类「无审计行的写」都造得出那个形状。
    ⇒ **mtime 既证明不了拨过开关、也证明不了没拨过，唯一的账是 ``config_audit``**。
    """
    db = tmp_path / "control_plane_config.sqlite3"
    store = SQLiteConfigStateStore(db, instance="shorekeeper")
    before = db.stat().st_mtime_ns
    assert store.import_legacy({"BOT_NOT_A_REGISTERED_KEY": "x"}) is True
    assert db.stat().st_mtime_ns > before, "封口写没动盘＝本判据要证的形态没复现，读数得重取"
    assert store.changes() == []  # 一格审计行都没有
    assert store.snapshot().version == 0
    assert _last_entry(store, "import_legacy")["outcome"] == OUTCOME_NOOP

    # 同尺对照：真拨一笔才既动盘又出账（不许只留反例）。
    time.sleep(0.02)
    stamp = db.stat().st_mtime_ns
    store.set_override("BOT_REPLY_DETAIL", "detail", expected_version=0, actor="席D2")
    assert db.stat().st_mtime_ns > stamp
    assert len(store.changes()) == 1
    assert _last_entry(store, "set")["outcome"] == OUTCOME_OK


# ---------------------------------------------------------------------------
# ③ 机械门：新增写口不记账即红（AST，不跑起来也算）
# ---------------------------------------------------------------------------


def _class_node(source: str, class_name: str) -> ast.ClassDef:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return node
    raise AssertionError(f"{class_name} 不在这份源码里（改名要同批改静态门）")


def _has_write_statement(function: ast.FunctionDef, writers: set[str]) -> bool:
    for node in ast.walk(function):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            head = " ".join(node.value.split()).lower()
            if any(
                word in head
                for word in ("insert into", "update ", "delete from", "rename to", "alter table")
            ):
                return True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in writers
        ):
            return True
    return False


def _class_writers(source: str, class_name: str) -> set[str]:
    """先扫一遍：这个类里哪些函数自己手里有 SQL（供 :func:`_has_write_statement` 递归判）。"""
    members = {
        node.name: node
        for node in _class_node(source, class_name).body
        if isinstance(node, ast.FunctionDef)
    }
    return {
        name
        for name, node in members.items()
        if any(
            isinstance(child, ast.Constant)
            and isinstance(child.value, str)
            and any(
                word in " ".join(child.value.split()).lower()
                for word in ("insert into", "update ", "delete from")
            )
            for child in ast.walk(node)
        )
    }


def _is_traced(function: ast.FunctionDef) -> bool:
    """AST 层判「这一腿调过留痕口」——抹成注释形态的假留痕骗不过它。"""
    for node in ast.walk(function):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _TRACE_METHOD_NAMES
        ):
            return True
    return False


def _scan_write_side(source: str, class_name: str, expected: tuple[str, ...]) -> list[str]:
    """一册源码 → 违规清单（空表＝合格）。静态门与注毒自证共用**同一把尺**。"""
    class_node = _class_node(source, class_name)
    members = {
        node.name: node for node in class_node.body if isinstance(node, ast.FunctionDef)
    }
    writers = _class_writers(source, class_name)
    violations: list[str] = []
    for name in expected:
        function = members.get(name)
        if function is None:
            violations.append(f"{class_name}.{name} 不见了（写口退场要同批改本门）")
            continue
        if not _is_traced(function):
            violations.append(f"{class_name}.{name} 没有留痕")
        if not _has_write_statement(function, writers):
            violations.append(f"{class_name}.{name} 被登记成写口却碰不到 SQL——门在骗人")
    return violations


def test_write_methods_all_record_trace_by_ast() -> None:
    """每个会写库的公开口都必须留下痕；没留 ⇒ 红（注毒自证另有一格，见下）。"""
    failures: list[str] = []
    for relative, class_name, expected in _WRITE_SIDE_TARGETS:
        source = (_REPO_ROOT / "plugins" / "bot_unified_runtime" / relative).read_text(
            encoding="utf-8"
        )
        failures.extend(_scan_write_side(source, class_name, expected))
    assert not failures, "这些写腿没有留痕（调用过查不到＝下次还是这本糊账）：" + "；".join(failures)


def test_write_side_classes_expose_the_trace(tmp_path: Path) -> None:
    """三枚 store 都必须在**公开面**给得出读数（运维面/测试同一只口，禁第二本账）。"""
    policy = ReplyPolicyStore(tmp_path / "rp.sqlite3")
    quirk = QuirkStore(tmp_path / "pq.sqlite3")
    backend = SQLiteConfigStateStore(tmp_path / "cp.sqlite3")
    for store in (policy, quirk, backend):
        snapshot = store.write_trace()
        assert set(snapshot) >= {"store", "counts", "by_op", "recent"}
        assert isinstance(snapshot["store"], str) and snapshot["store"]
        assert set(snapshot["counts"]) >= {"ok", "noop", "refused", "failed", "total"}
    # 构造阶段不许有「写成了」的格子；策略 store 只可能出「形状已现行」那枚 noop。
    assert backend.write_counts()["total"] == 0
    assert quirk.write_counts()["total"] == 0
    assert policy.write_counts()["ok"] == 0 and policy.write_counts()["noop"] >= 1
    policy.close()
    quirk.close()


def test_poison_gate_self_proves_the_static_scan_is_live(tmp_path: Path) -> None:
    """注毒自证 + 反向不误伤：抹掉一格留痕，同一把尺必须改口判红。

    ``retire`` 有**两腿**留痕（ok/noop 腿 + except 失败腿），注毒必须**两腿同批抹净**
    ——AST 尺按「函数内任一 ``_record`` 调用」判，只抹一腿，另一腿会替它顶账（假绿，
    席 D2F 踩过一次：``AssertionError: []``）。注毒形态刻意用注释形态——**文本尺**
    在这种形态上会假绿（源码里还剩 ``.record(`` 子串在注释/别的词里），AST 尺才认
    「真的调了留痕口」。全程只在内存里的源码文本上判，不落临时假件（规则 6 源码树零缓存）。
    """
    relative, class_name, expected = _WRITE_SIDE_TARGETS[1]  # quirks：写口最密，抹一格最容易
    original = (_REPO_ROOT / "plugins" / "bot_unified_runtime" / relative).read_text(encoding="utf-8")
    assert _scan_write_side(original, class_name, expected) == []  # 做对了必须绿

    ok_leg = original.replace(
        '        self._record("retire", OUTCOME_OK if changed else OUTCOME_NOOP)',
        "        changed = True  # .record( 注毒：留痕被抹成注释形态",
        1,
    )
    poisoned = ok_leg.replace(
        '            self._record("retire", OUTCOME_FAILED, type(exc).__name__)',
        "            pass  # .record( 注毒：失败腿的留痕一并抹掉",
        1,
    )
    assert ok_leg != original and poisoned != ok_leg, (
        "注毒没打中：quirks.retire 的两腿留痕写法变了（本门两腿各认一枚 _record），本锁要跟着改"
    )
    assert ".record(" in poisoned, "注毒形态得留着文本尺会误信的子串，否则这条自证没说服力"
    violations = _scan_write_side(poisoned, class_name, expected)
    assert any("retire" in item and "留痕" in item for item in violations), violations

    # 反向不误伤：改一枚**读腿**的文案，写口名单没变 ⇒ 不许判红。
    read_only = original.replace("只输出自然语言", "只输出自然语言的话", 1)
    assert read_only != original
    assert _scan_write_side(read_only, class_name, expected) == []

    # 写口退场（改名）也必须被抓，不许悄悄蒸发。
    gone = original.replace("    def retire(", "    def retire_v2(", 1)
    assert any("不见了" in item for item in _scan_write_side(gone, class_name, expected))


# ---------------------------------------------------------------------------
# ④ 盘上读数：WAL 滞后 ≠ 停更（本案定性的那把尺）
# ---------------------------------------------------------------------------


def test_disk_write_state_names_wal_lag_not_staleness(tmp_path: Path) -> None:
    db = tmp_path / "wal_lag.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t(v TEXT)")
    conn.execute("INSERT INTO t VALUES ('first')")
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()

    baseline = disk_write_state(db)
    assert baseline["verdict"] in {"no_sidecar_mtime_ambiguous", "wal_empty_checkpointed"}

    holder = sqlite3.connect(str(db))  # 连接不关＝提交留在 -wal，主文件不动
    holder.execute("PRAGMA journal_mode=WAL")
    holder.execute("INSERT INTO t VALUES ('second')")
    holder.commit()
    time.sleep(0.02)
    held = disk_write_state(db)
    assert held["verdict"] == "wal_ahead_main_mtime_is_not_staleness", held
    assert held["wal_bytes"] > 0 and held["main_mtime"] == baseline["main_mtime"]
    rows = holder.execute("SELECT v FROM t ORDER BY rowid").fetchall()
    assert [row[0] for row in rows] == ["first", "second"]  # 读得出来＝真写了
    holder.close()


def test_disk_write_state_of_missing_and_plain_files(tmp_path: Path) -> None:
    assert disk_write_state(tmp_path / "none.sqlite3")["verdict"] == "absent"
    plain = tmp_path / "plain.sqlite3"
    SQLiteConfigStateStore(plain, instance="default").set_override(
        "BOT_REPLY_DETAIL", "concise", expected_version=0, actor="席D2"
    )
    state = disk_write_state(plain)
    assert state["present"] and state["main_bytes"] > 0
    assert state["verdict"] == "no_sidecar_mtime_ambiguous"
    # 时刻一律带偏移（台账 #6★：裸串分不清 UTC 与本地）。
    parsed = datetime.fromisoformat(state["main_mtime"])
    assert parsed.tzinfo is not None and parsed.utcoffset() == timedelta_zero()


def timedelta_zero():
    from datetime import timedelta

    return timedelta(0)
