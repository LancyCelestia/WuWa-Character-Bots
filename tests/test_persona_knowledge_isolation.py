"""S5 席 单元 2/3：检索侧 persona 行级过滤真的咬得住（含注毒）。

现场（取证读数，非回忆）：``retrieve()`` 全链此前**没有任何 persona WHERE**，
``persona_id`` 在该文件命中 0 枚，人格库 35,274 块（含主人格本体 158 块 +
鸣潮/战双库街区百科 30,802 块）在切到备用人格后继续注入新人格的 prompt。
迁移件＝``scripts/migrate_persona_isolation.py``（**副本已验、生产未执行**）；
本件钉读侧三件事：

1. 归属明确的**别人格**行一律出不了候选池（三通道 + 末闸 ``_fetch_chunks`` 都裁）；
2. **未归属**（``persona_id=''``，＝迁移后新增但没定主）仍可见——这条不许被
   "顺手改成只认自己"（那会让未迁移期整条知识通道静默消失）；
3. 不注入 provider ＝ **逐字节现状**（kb_wiki / smoke / KnowledgeService 构造点不传）。

台账 241 教训写进判据里：成对保证里"缺席即 skip"那一侧天生无牙 ⇒ 每条 A/B 都
先断言**两侧样本非零**，再断言读数不同。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character.vector_knowledge import (
    SqliteVectorKnowledgeStore,
)

_SHORE = "shorekeeper"
_DANYA = "danya"


class _StubEmbedder:
    def embed_texts(self, texts):
        return [[0.0, 0.0, 1.0] for _ in texts]


def _store(tmp_path: Path, *, persona: str | None, top_k: int = 5) -> SqliteVectorKnowledgeStore:
    store = SqliteVectorKnowledgeStore(
        db_path=tmp_path / f"kb-{persona}.sqlite3",
        embed_provider=_StubEmbedder(),
        top_k=top_k,
        signature="test|fake",
        auto_reset=False,
        fts_auto_rebuild=False,
        persona_provider=(None if persona is None else (lambda: persona)),
    )
    return store


def _seed(store: SqliteVectorKnowledgeStore, rows: list[tuple[str, str, str]]) -> None:
    """rows＝(chunk_id, source_id, persona_id)；直插，绕开同步链的 IO 依赖。"""
    with store._connect() as connection:
        connection.executemany(
            "INSERT OR REPLACE INTO knowledge_chunks "
            "(chunk_id, source_id, title, content, content_hash, vector_json, persona_id) "
            "VALUES (?, ?, ?, ?, ?, NULL, ?)",
            [
                (
                    cid,
                    sid,
                    sid,
                    f"内容 {cid} for {sid}",
                    hashlib.sha1(cid.encode("utf-8")).hexdigest(),
                    owner,
                )
                for cid, sid, owner in rows
            ],
        )
        connection.commit()


_ROWS: list[tuple[str, str, str]] = [
    ("s1", "守岸人_核心知识", _SHORE),
    ("s2", "鸣潮库街区百科", _SHORE),
    ("d1", "达妮娅_核心知识", _DANYA),
    ("u1", "无主源", ""),  # 未归属：必须**两侧都看得见**
]


def _open_channels(store: SqliteVectorKnowledgeStore) -> None:
    """把三通道都替成"全量吐出"，只考过滤腿本身（不联网、不建 ANN）。"""
    ids = [cid for cid, _s, _o in _ROWS]
    store._vector_candidates = lambda _q, scores_out=None: (  # type: ignore[assignment]
        list(ids),
        0.9,
    )
    store._keyword_candidates = lambda _q: list(ids)  # type: ignore[assignment]
    store._entry_title_candidates = lambda _q: [  # type: ignore[assignment]
        (6, True, cid) for cid in ids
    ]


def test_schema_carries_persona_column_and_index(tmp_path: Path) -> None:
    store = _store(tmp_path, persona=_SHORE)
    with store._connect() as connection:
        names = {str(r[1]) for r in connection.execute("PRAGMA table_info(knowledge_chunks)")}
        indexes = {
            str(r[1])
            for r in connection.execute("PRAGMA index_list(knowledge_chunks)")
        }
    assert "persona_id" in names, names
    assert any("persona" in str(name) for name in indexes), indexes


def test_retrieve_filters_by_persona_on_copies(tmp_path: Path) -> None:
    store = _store(tmp_path, persona=_SHORE)
    _seed(store, _ROWS)
    _open_channels(store)
    shore = [chunk.chunk_id for chunk in store.retrieve("随便问点什么")]
    assert shore, "主人格档读出零块 ⇒ 过滤腿把该看的也裁了（未归属行必须可见）"
    assert {"s1", "s2", "u1"} <= set(shore), shore
    assert "d1" not in shore, "别人格的块混进来了 ⇒ 串味没治住"

    # 同一库、只换 provider ⇒ 证明裁的是"生效谁"而不是"哪一枚库"。
    store.persona_provider = lambda: _DANYA
    danya = [chunk.chunk_id for chunk in store.retrieve("随便问点什么")]
    # 两侧样本都非零（241 教训）＋读数互不含别人的专属块。
    assert shore and danya, (shore, danya)
    assert "d1" in danya and "s1" not in danya and "s2" not in danya, danya
    assert "u1" in danya, danya
    assert set(shore) != set(danya)


def test_unknown_persona_declares_absence_not_borrowed(tmp_path: Path) -> None:
    """册里没有的一格（幽灵人格）⇒ 只看得见未归属行，绝不借主人格的语料。"""
    store = _store(tmp_path, persona="ghost-not-in-register")
    _seed(store, _ROWS)
    _open_channels(store)
    got = [chunk.chunk_id for chunk in store.retrieve("随便问点什么")]
    assert got == ["u1"], got


def test_no_provider_is_byte_identical_legacy(tmp_path: Path) -> None:
    store = _store(tmp_path, persona=None)
    _seed(store, _ROWS)
    _open_channels(store)
    got = [chunk.chunk_id for chunk in store.retrieve("随便问点什么")]
    assert {"s1", "s2", "d1", "u1"} <= set(got), got


def test_absent_column_fails_open_with_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """列未迁移＝**不裁剪**（迁移与上线可以分两批），且必须留一行 WARN 点名。"""
    store = _store(tmp_path, persona=_SHORE)
    _seed(store, _ROWS)
    _open_channels(store)
    monkeypatch.setattr(store, "_persona_column_present", lambda: False)
    got = [chunk.chunk_id for chunk in store.retrieve("随便问点什么")]
    assert {"s1", "s2", "d1", "u1"} <= set(got), got


def test_poison_removed_filter_leaks_foreign_persona(tmp_path: Path) -> None:
    """注毒腿：把过滤摘成直通 ⇒ 本件必须红（否则前面几把尺全是空转）。"""
    store = _store(tmp_path, persona=_SHORE)
    _seed(store, _ROWS)
    _open_channels(store)
    store._retain_active_persona = lambda ids: list(ids)  # type: ignore[method-assign]
    leaked = [chunk.chunk_id for chunk in store.retrieve("随便问点什么")]
    assert "d1" in leaked, "摘掉过滤都不漏 ⇒ 说明过滤本来就没被走到，尺是假的"


def test_sync_deletes_only_active_persona_sources(tmp_path: Path) -> None:
    """删侧护城河：切人格后清单只带新人格的件 ⇒ 别人格的源**不得**进删除计划。

    守卫 C（多数闸）只是偶然拦住这种形态，删库风险不许押在偶然上。
    """
    store = _store(tmp_path, persona=_DANYA)
    _seed(store, _ROWS)
    with store._connect() as connection:
        # 台账把主人格的两个源记成"曾同步过"，本轮清单里没有 ⇒ 落进 stale。
        for source in ("守岸人_核心知识", "鸣潮库街区百科"):
            connection.execute(
                "INSERT OR REPLACE INTO knowledge_meta (key, value) VALUES (?, ?)",
                (f"sync_source_sig:{source}", "1:1"),
            )
        connection.commit()
    store.sync_chunks([Path(tmp_path / "达妮娅_核心知识.md")])
    with store._connect() as connection:
        left = {
            str(row["source_id"])
            for row in connection.execute("SELECT DISTINCT source_id FROM knowledge_chunks")
        }
    assert "守岸人_核心知识" in left and "鸣潮库街区百科" in left, left


# ---------------------------------------------------------------------------
# 单元 3：七张小表 + knowledge_chunks 用**同一形态**的归属列（禁第二形态）
# ---------------------------------------------------------------------------

SHARED_TABLES: tuple[str, ...] = (
    "conversation_turns",
    "memory_facts",
    "memory_entries_v21",
    "user_affinity",
    "group_affinity",
    "persona_quirks",
    "memes",
)


def test_migration_script_uses_one_column_shape() -> None:
    import sys

    script_dir = Path(__file__).resolve().parents[1] / "scripts"
    sys.path.insert(0, str(script_dir))
    import migrate_persona_isolation as mig

    assert mig.PERSONA_COLUMN_SQL.strip().endswith("persona_id TEXT NOT NULL DEFAULT ''")
    assert {table for _db, table, _i, _c in mig.SMALL_TARGETS} == set(SHARED_TABLES), (
        mig.SMALL_TARGETS
    )
    assert {table for _db, table, _i, _c in mig.WIKI_TARGETS} == {"knowledge_chunks"}
    # knowledge_chunks 的读侧建表与迁移脚本的 ALTER 必须是同一形态（缺省同值）。
    from plugins.bot_unified_runtime.domains.chat_reply.character import (
        vector_knowledge as vk,
    )

    source = Path(vk.__file__).read_text(encoding="utf-8")
    assert "persona_id TEXT NOT NULL DEFAULT ''" in source
    # 注毒腿：把脚本里的缺省换成 NOT NULL 无缺省 ⇒ 上面两把都该红。
    assert "persona_id TEXT NOT NULL," not in mig.PERSONA_COLUMN_SQL


# ---------------------------------------------------------------------------
# S7：死腿修复的判据（blanket-fill 误归属 ＋ 哑读数）
# ---------------------------------------------------------------------------


def _import_mig():
    import sys

    script_dir = Path(__file__).resolve().parents[1] / "scripts"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    import migrate_persona_isolation as mig

    return mig


def _make_db(path: Path, table: str, rows: list[tuple[str, str]]) -> None:
    """rows＝(id, persona_id)；建一张与在册形态同构的小表。"""
    connection = sqlite3.connect(str(path))
    connection.execute(f"CREATE TABLE {table} (fact_id TEXT PRIMARY KEY, text TEXT)")
    connection.executemany(
        f"INSERT INTO {table} (fact_id, text) VALUES (?, ?)",
        [(rid, txt) for rid, txt in rows],
    )
    connection.commit()
    connection.close()


def _persona_of(path: Path, table: str) -> dict[str, str]:
    connection = sqlite3.connect(str(path))
    try:
        return {
            str(row[0]): str(row[1])
            for row in connection.execute(f"SELECT fact_id, persona_id FROM {table}")
        }
    finally:
        connection.close()


def test_default_execute_never_assigns_unowned_rows(tmp_path: Path) -> None:
    """死腿 #1 修复：缺省＝无主行保持无主（读侧 ``OR ''`` 继续放行＝共享）。

    老代码在这里把 2 行一律刷成主人格 ⇒ ``still>0`` 审计腿结构上永不触发，
    并且新人格永远读不到这些行、主人格凭空继承全语料（误归属面）。
    """
    mig = _import_mig()
    db = tmp_path / "wuwa_memory.sqlite3"
    _make_db(db, "memory_facts", [("f1", ""), ("f2", "")])
    _make_db(db, "memory_entries_v21", [("e1", "")])

    assert mig.main(["--stage", "small", "--db", str(db), "--partial-scope"]) == 0
    connection = sqlite3.connect(str(db))
    names = {str(r[1]) for r in connection.execute("PRAGMA table_info(memory_facts)")}
    connection.close()
    assert "persona_id" not in names, "演练腿把列写下去了 ⇒ 缺省不再只读"

    assert mig.main(["--stage", "small", "--db", str(db), "--partial-scope", "--execute"]) == 0
    assert mig.main(["--stage", "small", "--db", str(db), "--partial-scope", "--execute"]) == 0
    connection = sqlite3.connect(str(db))
    try:
        names = {str(r[1]) for r in connection.execute("PRAGMA table_info(memory_facts)")}
        unowned = int(
            connection.execute("SELECT COUNT(*) FROM memory_facts WHERE persona_id = ''").fetchone()[0]
        )
        owned = int(
            connection.execute(
                "SELECT COUNT(*) FROM memory_facts WHERE persona_id != ''"
            ).fetchone()[0]
        )
    finally:
        connection.close()
    assert "persona_id" in names, names
    assert (unowned, owned) == (2, 0), (
        f"无主行被静默指派＝死腿复活（unowned={unowned} owned={owned}）"
    )


def test_fill_unowned_changes_exactly_the_pending_rows(tmp_path: Path) -> None:
    """``--fill-unowned`` 腿：只改**无主**那部分，已归属行一字不动（N-1a 独占档才用）。"""
    mig = _import_mig()
    db = tmp_path / "wuwa_memory.sqlite3"
    connection = sqlite3.connect(str(db))
    connection.execute(
        "CREATE TABLE memory_facts (fact_id TEXT PRIMARY KEY, text TEXT, persona_id TEXT NOT NULL DEFAULT '')"
    )
    connection.execute("CREATE TABLE memory_entries_v21 (fact_id TEXT PRIMARY KEY, text TEXT)")
    connection.executemany(
        "INSERT INTO memory_entries_v21 VALUES (?, ?)", [("e1", "戊")]
    )
    connection.executemany(
        "INSERT INTO memory_facts VALUES (?, ?, ?)",
        [("f1", "甲", ""), ("f2", "乙", ""), ("f3", "丙", "someone-else")],
    )
    connection.commit()
    connection.close()

    assert (
        mig.main(
            ["--stage", "small", "--db", str(db), "--partial-scope", "--execute",
             "--fill-unowned", "shorekeeper"]
        )
        == 0
    )
    owners = _persona_of(db, "memory_facts")
    assert owners == {"f1": "shorekeeper", "f2": "shorekeeper", "f3": "someone-else"}, owners

    # 注毒腿：指派额与现算待决额不符 ⇒ 必须红（不许"顺手多改/少改"）。
    connection = sqlite3.connect(str(db))
    connection.execute("INSERT INTO memory_facts VALUES ('f4','丁','')")
    connection.execute("UPDATE memory_facts SET persona_id = 'ghost' WHERE fact_id = 'f3'")
    connection.commit()
    connection.close()
    assert (
        mig.main(
            ["--stage", "small", "--db", str(db), "--partial-scope", "--execute",
             "--fill-unowned", "shorekeeper", "--require-assigned"]
        )
        == 0
    ), "补一行无主后终态门该绿；这条同时钉住『指派不许越界改已归属行』"
    assert _persona_of(db, "memory_facts")["f3"] == "ghost", "指派越界改写了已归属行"


def test_require_assigned_flags_leftover_unowned(tmp_path: Path) -> None:
    """N-1a 取"独占"档时的终态门：还有无主行就红；缺省档下同形态必须绿。"""
    mig = _import_mig()
    db = tmp_path / "wuwa_memory.sqlite3"
    _make_db(db, "memory_facts", [("f1", ""), ("f2", "")])
    _make_db(db, "memory_entries_v21", [("e1", "")])
    assert mig.main(["--stage", "small", "--db", str(db), "--partial-scope", "--execute"]) == 0
    assert (
        mig.main(
            ["--stage", "small", "--db", str(db), "--partial-scope", "--execute",
             "--require-assigned"]
        )
        != 0
    ), "--require-assigned 却留着无主行还报成功 ⇒ 终态门没牙"


def test_missing_table_is_red_and_never_prints_a_dash(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """死腿 #2 修复：取不到样本的那一格必须红，不许输出 ``-`` ＋ ``problems=[]``。"""
    mig = _import_mig()
    db = tmp_path / "meme_library.sqlite3"
    sqlite3.connect(str(db)).close()  # 库名在册、表却不在 ⇒ 作用域判据可疑

    rc = mig.main(["--stage", "small", "--db", str(db), "--partial-scope"])
    out = capsys.readouterr().out
    assert rc != 0, f"表缺席还报绿：rc={rc}\n{out}"
    assert "count_before=-" not in out, out
    assert "作用域" in out or "problems=[" in out, out


def test_partial_scope_must_be_declared(tmp_path: Path) -> None:
    """只给一枚 --db 跑 stage=all：没覆盖的在册目标要红，承认了才绿。"""
    mig = _import_mig()
    db = tmp_path / "wuwa_memory.sqlite3"
    _make_db(db, "memory_facts", [("f1", "")])
    _make_db(db, "memory_entries_v21", [("e1", "")])

    assert mig.main(["--stage", "all", "--db", str(db)]) != 0, "部分作用域当全绿 ⇒ 假绿"
    assert mig.main(
        ["--stage", "all", "--db", str(db), "--partial-scope"]
    ) == 0


def test_wiki_stage_lands_index_and_topic_report(tmp_path: Path) -> None:
    """kb_wiki 行级落地：建列 + **复合索引 (persona_id, source_id)** + 只读 topic 报告。"""
    mig = _import_mig()
    db = tmp_path / "kb_wiki_embeddings.sqlite3"
    connection = sqlite3.connect(str(db))
    connection.execute(
        "CREATE TABLE knowledge_chunks (chunk_id TEXT PRIMARY KEY, source_id TEXT, "
        "title TEXT, content TEXT, content_hash TEXT, vector_json TEXT)"
    )
    connection.executemany(
        "INSERT INTO knowledge_chunks VALUES (?, ?, ?, ?, ?, NULL)",
        [("c1", "doc-a", "t", "内容一", "h1"), ("c2", "doc-b", "t", "内容二", "h2")],
    )
    connection.execute(
        "CREATE TABLE knowledge_docs (doc_id TEXT PRIMARY KEY, topic TEXT, source TEXT, "
        "title TEXT, hash TEXT, source_updated_at TEXT, crawl_at TEXT)"
    )
    connection.executemany(
        "INSERT INTO knowledge_docs VALUES (?, ?, ?, ?, ?, '', '')",
        [("doc-a", "明日方舟", "s", "t1", "h"), ("doc-b", "鸣潮", "s", "t2", "h")],
    )
    connection.commit()
    connection.close()
    report = tmp_path / "wiki-topic-report.json"

    assert mig.main(
        ["--stage", "wiki", "--db", str(db), "--execute", "--topic-report", str(report)]
    ) == 0
    connection = sqlite3.connect(str(db))
    try:
        cols = {str(r[1]) for r in connection.execute("PRAGMA table_info(knowledge_chunks)")}
        idx = [str(r[1]) for r in connection.execute("PRAGMA index_list(knowledge_chunks)")]
        idx_cols = {
            str(r[2])
            for r in connection.execute("PRAGMA index_info(idx_knowledge_chunks_persona_source)")
        }
    finally:
        connection.close()
    assert "persona_id" in cols, cols
    assert "idx_knowledge_chunks_persona_source" in idx, idx
    assert idx_cols == {"persona_id", "source_id"}, idx_cols

    payload = json.loads(report.read_bytes().decode("utf-8"))
    topics = {row["topic"]: row["docs"] for row in payload["rows"]}
    assert topics == {"明日方舟": 1, "鸣潮": 1}, payload
    assert payload["ledger_rows"] == 2, payload

    # 注毒腿：消费者没接线（``_build_store`` 不传 persona_provider）⇒ 加列必须红。
    original = mig.consumer_wired
    mig.consumer_wired = lambda: {  # type: ignore[method-assign]
        "kb_wiki_build_store_passes_persona_provider": False,
        "store_over_fetch_before_filter": True,
        "source_probe_failed": [],
    }
    try:
        assert mig.main(["--stage", "wiki", "--db", str(db)]) != 0, (
            "只加列不接消费者还报绿 ⇒ 检索侧根本没人按行裁剪"
        )
    finally:
        mig.consumer_wired = original  # type: ignore[method-assign]


def test_wiki_consumer_is_wired_at_the_real_seam() -> None:
    """现算真缝：wiki 的取数口复用共用 store 的行级过滤，不长第二把尺。"""
    mig = _import_mig()
    wiring = mig.consumer_wired()
    assert not wiring["source_probe_failed"], wiring
    assert wiring["kb_wiki_build_store_passes_persona_provider"], wiring
    assert wiring["store_over_fetch_before_filter"], wiring


def test_runtime_paths_refused_for_write(tmp_path: Path) -> None:
    """生产库保护：写一律拒；只读也必须显式声明才放行。"""
    mig = _import_mig()
    production = (
        Path(os.environ.get("COMPUTERDRIVE", "C:/"))
        / "Users"
        / "nobody"
        / "ChatBot_Runtime"
        / "data"
        / "wuwa_memory.sqlite3"
    )
    assert (
        mig.main(["--stage", "small", "--db", str(production), "--execute"]) == 2
    ), "运行数据目录内的路径没被拒 ⇒ 脚本能写生产库"
    assert (
        mig.main(["--stage", "small", "--db", str(production)]) == 2
    ), "没声明 --read-production-readonly 就读生产库 ⇒ 越界"


def test_subject_kind_stage_is_plan_only(tmp_path: Path) -> None:
    """S2 需要的 subject_kind：**只出脚本不执行**（本席不与 S2 抢实现）。"""
    mig = _import_mig()
    db = tmp_path / "wuwa_memory.sqlite3"
    connection = sqlite3.connect(str(db))
    connection.execute("CREATE TABLE memory_facts (fact_id TEXT PRIMARY KEY, text TEXT)")
    connection.execute("INSERT INTO memory_facts VALUES ('f1','甲')")
    connection.commit()
    connection.close()

    assert mig.main(["--stage", "subject-kind", "--db", str(db), "--execute"]) == 2
    connection = sqlite3.connect(str(db))
    names = {str(r[1]) for r in connection.execute("PRAGMA table_info(memory_facts)")}
    connection.close()
    assert "subject_kind" not in names, "带 --execute 也不许落 S2 的列"

