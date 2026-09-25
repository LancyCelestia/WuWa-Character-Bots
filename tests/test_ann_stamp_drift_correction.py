"""活戳漂移纠偏锁（stamp-drift 波）。

生产实况（2026-09-26 03:2x 现算）：`ann_expected_vector_count=741,428`，
而索引 `ntotal=740,996`、库里已嵌入行数也是 `740,996`（同轮 kb-sync 自报
`chunks_after=embedded_after=740996 / embed_pending=0 / reconcile_missing=0`）。
⇒ 完备性闸按 `missing=432>0` 恒拒，而这条路**任何既有路径都修不掉**：
零变更夜不重建（`unchanged_skip`），重建线又不达，`certify` 又被「活戳一字不碰」
挡在门外 ⇒ 库被永久钉在暴力扫描上（09-22 停摆的同一形态：每问 84–157s、CPU 418%）。

本锁钉死第四条件：漂移纠偏**必须**同时拿到「库侧真值 == 代际证明 == 集合级覆盖」
三件证据才许落戳，缺一即拒并保持原戳——纠偏只把「已被证明完备却因戳漂移被误拒」
这一类放回绿区，绝不给「真短装」开门（那是把闸掏空）。取数方向仍是
**SQLite COUNT 裁决文件**，绝不拿 index.ntotal 落戳（见 test_ann_certify_prewarm 的同名陷阱锁）。
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pytest
from test_ann_certify_prewarm import (
    _STAMP_KEY,
    _append_embedded,
    _docs,
    _make_store,
    _ntotal_on_disk,
    _stamp,
    _write_raw_stamp,
)

from plugins.bot_unified_runtime.domains.chat_reply.character import (
    vector_knowledge as vk,
)

pytestmark = pytest.mark.skipif(vk.faiss is None, reason="纠偏依赖 faiss 成对产物")

_REFUSAL_TOKEN = "stamp reconcile refused"
_GIB = 1024**3


def _complete_pair_store(tmp_path, count: int = 20):
    """建一代完备索引（文件 + 代际证明 + 戳 := ntotal），随后把戳人为抬高。"""
    store = _make_store(tmp_path, count=count)
    built = store.build_ann_index()
    assert built["built"] is True, built
    assert _ntotal_on_disk(store) == count
    assert _stamp(store) == count
    return store


def _read_attestation(store) -> dict:
    attestation = store._read_ann_attestation()
    assert isinstance(attestation, dict), "代际证明必须成在（本文件全部前提）"
    return attestation


def _mutate_attestation(store, **over) -> None:
    attestation = {**_read_attestation(store), **over}
    store._write_ann_attestation(attestation)


# === 缺省不开门（家规：新谓词 = 新 kwarg 且缺省 False）========================


def test_drift_correction_off_by_default_leaves_live_stamp_untouched(tmp_path):
    """不带 kwarg ⇒ 与今天逐字节同形：活戳在位即一字不碰、返回 None。"""
    store = _complete_pair_store(tmp_path)
    _write_raw_stamp(store, "40")  # 漂移态：实嵌 20，戳 40

    assert store.certify_expected_vector_count() is None
    assert _stamp(store) == 40, "缺省不开门：纠偏必须是显式 opt-in，不是 certify 的新默认"


def test_existing_certify_locks_still_hold_with_flag_absent(tmp_path):
    """无戳补盖这条老路不受本件影响：仍落 COUNT(已嵌入)=20（不是总行数、不是 ntotal）。"""
    store = _complete_pair_store(tmp_path)
    store.sync_documents(iter(_docs(5, "p")), removed_ids=[], full=False)  # 5 行未嵌
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("DELETE FROM knowledge_meta WHERE key = ?", (_STAMP_KEY,))
        conn.commit()

    assert store.certify_expected_vector_count() == 20
    assert _stamp(store) == 20


# === 开门条件：三件证据齐全才落戳 =============================================


def test_drift_correction_lowers_stamp_to_db_truth_when_pair_provably_covers_rows(
    tmp_path, caplog
):
    """生产实况类：戳高于库真值，而索引确实装满每一行已嵌入 ⇒ 落库侧真值、闸自愈。"""
    store = _complete_pair_store(tmp_path)
    _write_raw_stamp(store, "40")
    store._drop_ann_cache()
    with caplog.at_level(logging.WARNING, logger=vk.logger.name):
        assert store.load_ann_index() is False, "基线：漂移态被拒（这就是今晚的红）"
    refused = [
        r.getMessage() for r in caplog.records if "completeness refused" in r.getMessage()
    ]
    assert refused and "expected=40" in refused[0], (
        "基线要的是「因完备性闸而拒」这一条，不是任何一句日志——写反的断言等于没断"
    )

    with caplog.at_level(logging.INFO, logger=vk.logger.name):
        corrected = store.certify_expected_vector_count(drift_correction=True)

    assert corrected == 20, "落戳值必须是库侧 COUNT(已嵌入)"
    assert _stamp(store) == 20
    # 不重启、不手动清缓存：下一次载入即自愈（戳值变化是运行中进程唯一感知通道）。
    assert store.load_ann_index() is True


def test_drift_correction_is_idempotent_when_stamp_already_honest(tmp_path):
    """戳已等于库真值 ⇒ 无漂移可纠：返回 None、一字不写（防把纠偏当例行落戳刷）。"""
    store = _complete_pair_store(tmp_path)

    assert store.certify_expected_vector_count(drift_correction=True) is None
    assert _stamp(store) == 20


# === 四道拒绝门（缺一即拒，保持原戳）========================================


def test_drift_correction_refuses_when_index_truly_short(tmp_path, caplog):
    """真短装（索引 20、库 50、戳被抬到 60）⇒ 拒纠、戳保持 60、闸继续红。

    这条是"借纠偏之名掏闸"的反面锁：一旦实现被改坏成拿 ntotal 当基线，
    这里会把 60 落成 20 ⇒ 下一句 load 变 True ⇒ 本用例当场转红。
    """
    store = _complete_pair_store(tmp_path)
    _append_embedded(store, 30, "b")  # 库 50 行已嵌入，索引仍 20
    _write_raw_stamp(store, "60")
    store._drop_ann_cache()

    with caplog.at_level(logging.WARNING, logger=vk.logger.name):
        assert store.certify_expected_vector_count(drift_correction=True) is None
    assert _stamp(store) == 60, "短装代不得被纠偏洗绿"
    assert store.load_ann_index() is False
    refused = [
        r.getMessage() for r in caplog.records if _REFUSAL_TOKEN in r.getMessage()
    ]
    assert refused and "reason=index_does_not_cover_embedded_rows" in refused[0]


def test_drift_correction_refuses_on_id_set_swap_even_when_counts_agree(
    tmp_path, caplog
):
    """集合格：行数对得上但**换了一批 id**（删 20 补 20）⇒ 拒纠。

    纯计数相等证明不了覆盖——这一格是计数判据的天花板，必须用集合级自证补上。
    """
    store = _complete_pair_store(tmp_path)  # 索引装着 a-0..a-19 的 id
    store.sync_documents(iter(_docs(20, "z")), removed_ids=[], full=False)
    store.embed_pending(None)
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("DELETE FROM knowledge_chunks WHERE source_id LIKE 'topic/a-%'")
        conn.commit()
    assert store.stats()["embedded"] == 20, "前提：库侧仍是 20 行（换成 z-*）"
    assert _ntotal_on_disk(store) == 20, "前提：索引仍是 a 代 20 条"
    _write_raw_stamp(store, "60")

    with caplog.at_level(logging.WARNING, logger=vk.logger.name):
        assert store.certify_expected_vector_count(drift_correction=True) is None
    assert _stamp(store) == 60
    refused = [r.getMessage() for r in caplog.records if _REFUSAL_TOKEN in r.getMessage()]
    assert refused and "reason=id_set_mismatch" in refused[0]


def test_drift_correction_refuses_on_signature_drift(tmp_path, caplog):
    """代际证明的签名与当前嵌入签名不符 ⇒ 这代索引本就不属于现在 ⇒ 拒纠。"""
    store = _complete_pair_store(tmp_path)
    _write_raw_stamp(store, "40")
    _mutate_attestation(store, signature="other|sig")

    with caplog.at_level(logging.WARNING, logger=vk.logger.name):
        assert store.certify_expected_vector_count(drift_correction=True) is None
    assert _stamp(store) == 40
    refused = [r.getMessage() for r in caplog.records if _REFUSAL_TOKEN in r.getMessage()]
    assert refused and "reason=signature_mismatch" in refused[0]


def test_drift_correction_refuses_without_attestation(tmp_path, caplog):
    """无代际证明（旧存量产物）⇒ 无从证明完备 ⇒ fail-closed 拒纠。"""
    store = _complete_pair_store(tmp_path)
    _write_raw_stamp(store, "40")
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("DELETE FROM knowledge_meta WHERE key = ?", (vk._ANN_ATTESTATION_KEY,))
        conn.commit()

    with caplog.at_level(logging.WARNING, logger=vk.logger.name):
        assert store.certify_expected_vector_count(drift_correction=True) is None
    assert _stamp(store) == 40
    refused = [r.getMessage() for r in caplog.records if _REFUSAL_TOKEN in r.getMessage()]
    assert refused and "reason=no_attestation" in refused[0]


def test_drift_correction_refuses_on_self_inconsistent_attestation(tmp_path, caplog):
    """证明内部 ntotal != count ⇒ 成对性本就破了 ⇒ 拒纠（不许拿畸形证明背书）。"""
    store = _complete_pair_store(tmp_path)
    _write_raw_stamp(store, "40")
    _mutate_attestation(store, count=19)

    with caplog.at_level(logging.WARNING, logger=vk.logger.name):
        assert store.certify_expected_vector_count(drift_correction=True) is None
    assert _stamp(store) == 40
    refused = [r.getMessage() for r in caplog.records if _REFUSAL_TOKEN in r.getMessage()]
    assert refused and "reason=attestation_self_inconsistent" in refused[0]


def test_drift_correction_never_raises_the_stamp(tmp_path, caplog):
    """戳低于库真值（涨点漏了）⇒ 纠偏不代行涨戳：拒纠并点名该走重建线。"""
    store = _complete_pair_store(tmp_path)
    _write_raw_stamp(store, "5")  # 实嵌 20，戳 5（偏低＝危险侧，闸本该更严）

    with caplog.at_level(logging.WARNING, logger=vk.logger.name):
        assert store.certify_expected_vector_count(drift_correction=True) is None
    assert _stamp(store) == 5, "偏低戳保持原样：纠偏只准降回真值，不准替重建线作主"
    refused = [r.getMessage() for r in caplog.records if _REFUSAL_TOKEN in r.getMessage()]
    assert refused and "reason=stamp_below_db_count" in refused[0]


def test_drift_correction_refuses_below_memory_floor(tmp_path, monkeypatch, caplog):
    """内存地板之下不跑集合级比对（本件要在维护线程读两份数十万项 id）。"""
    store = _complete_pair_store(tmp_path)
    _write_raw_stamp(store, "40")
    monkeypatch.setattr(vk, "_available_physical_memory_bytes", lambda: 1)

    with caplog.at_level(logging.WARNING, logger=vk.logger.name):
        assert store.certify_expected_vector_count(drift_correction=True) is None
    assert _stamp(store) == 40
    refused = [r.getMessage() for r in caplog.records if _REFUSAL_TOKEN in r.getMessage()]
    assert refused and "reason=insufficient_memory" in refused[0]


def test_drift_correction_refuses_when_probe_unavailable(tmp_path, monkeypatch, caplog):
    """探针不可判定 ⇒ 与 ANN 内存门同口径 fail-closed（None 不当"够"用）。"""
    store = _complete_pair_store(tmp_path)
    _write_raw_stamp(store, "40")
    monkeypatch.setattr(vk, "_available_physical_memory_bytes", lambda: None)

    with caplog.at_level(logging.WARNING, logger=vk.logger.name):
        assert store.certify_expected_vector_count(drift_correction=True) is None
    assert _stamp(store) == 40
    refused = [r.getMessage() for r in caplog.records if _REFUSAL_TOKEN in r.getMessage()]
    assert refused and "reason=memory_probe_unavailable" in refused[0]


# === 接线与卫生 ==============================================================


def test_drift_correction_never_touches_ann_files(tmp_path):
    """纠偏只写 knowledge_meta 一行：两文件字节与 mtime 都不许动（它是账，不是重建）。"""
    store = _complete_pair_store(tmp_path)
    _write_raw_stamp(store, "40")
    index_path, order_path = (Path(p) for p in store._ann_files())
    before = [
        (index_path.stat().st_size, index_path.stat().st_mtime_ns),
        (order_path.stat().st_size, order_path.stat().st_mtime_ns),
    ]

    assert store.certify_expected_vector_count(drift_correction=True) == 20
    after = [
        (index_path.stat().st_size, index_path.stat().st_mtime_ns),
        (order_path.stat().st_size, order_path.stat().st_mtime_ns),
    ]
    assert before == after, "纠偏不得碰 ANN 文件（碰了就是第二次发布）"


def test_kb_sync_skip_branch_asks_for_drift_correction():
    """零变更夜（今晚的红就诞生在这条分支上）必须显式开门，否则漂移永不自愈。"""
    import ast

    source = (
        Path(__file__).resolve().parents[1]
        / "plugins/bot_unified_runtime/domains/location/knowledge/kb_wiki.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    hit = None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_certify"
        ):
            hit = node
            break
    assert hit is not None, "找不到零变更夜的 _certify() 调用点（分支被改写？先复核再判红）"
    kwargs = {kw.arg: kw for kw in hit.keywords}
    assert "drift_correction" in kwargs, (
        "零变更夜未开门：活戳漂移在这一夜没有任何路径能纠正（今晚实测 missing=432 恒红）"
    )
    value = kwargs["drift_correction"].value
    assert isinstance(value, ast.Constant) and value.value is True, (
        "开门必须是字面 True，不是变量——变量会被下一席顺手改回 False"
    )


def test_refusal_reasons_are_a_closed_set(tmp_path, caplog):
    """拒绝原因是有限集，且**只有一本账**：测试侧集合由模块常量派生，禁抄第二份。"""
    allowed = set(vk._STAMP_RECONCILE_REASONS)
    assert allowed, "闭集空 = 判据没在册"
    store = _complete_pair_store(tmp_path)
    _write_raw_stamp(store, "40")
    _mutate_attestation(store, count=19)
    with caplog.at_level(logging.WARNING, logger=vk.logger.name):
        store.certify_expected_vector_count(drift_correction=True)
    messages = [r.getMessage() for r in caplog.records if _REFUSAL_TOKEN in r.getMessage()]
    assert messages, "拒纠必须点名原因（静默 None = 下一次又要靠人肉考古）"
    seen = {m.split("reason=", 1)[1].split()[0].rstrip(")") for m in messages}
    assert seen <= allowed, f"越闭集的拒绝原因：{sorted(seen - allowed)}"
    assert "attestation_self_inconsistent" in seen, "本枚注毒应打到这一格"


# === 第一层：移除侧的对称记账（漂移的出生地）=================================


def _store_with_partial_vectors(tmp_path, count: int = 12):
    """造一副好量子的库：count 行已嵌并建索引，另 n 行有正文无向量。"""
    store = _complete_pair_store(tmp_path, count=count)
    store.sync_documents(iter(_docs(4, "p")), removed_ids=[], full=False)
    assert store.stats() == {"total": count + 4, "embedded": count}
    assert _stamp(store) == count
    return store


def test_forget_chunks_lowers_by_rows_that_actually_had_vectors(tmp_path):
    """删块按「真带向量的行数」拉低戳，不是按 rowcount——未嵌行也算 rowcount。

    这一枚钉的是今晚漏拒/误降的分界：拿 rowcount 当账会把没向量的行也扣掉，
    戳从此低于真实值 = 危险侧（该拦的放行）。
    """
    store = _store_with_partial_vectors(tmp_path)
    with sqlite3.connect(store.db_path) as conn:
        conn.row_factory = sqlite3.Row
        embedded_before = int(
            conn.execute(
                "SELECT COUNT(*) FROM knowledge_chunks "
                "WHERE vector_json IS NOT NULL AND vector_json != ''"
            ).fetchone()[0]
        )
        # 一次删掉 3 行：其中 2 行带向量、1 行没有（pending 从未嵌）
        ids = [
            str(row[0])
            for row in conn.execute(
                "SELECT chunk_id FROM knowledge_chunks ORDER BY chunk_id LIMIT 3"
            ).fetchall()
        ]
        pending = [
            str(row[0])
            for row in conn.execute(
                "SELECT chunk_id FROM knowledge_chunks "
                "WHERE (vector_json IS NULL OR vector_json = '') LIMIT 1"
            ).fetchall()
        ]
        victims = ids[:2] + pending
        removed_rows = store._forget_chunks(
            conn,
            where="chunk_id IN (" + ",".join("?" * len(victims)) + ")",
            params=tuple(victims),
        )
        conn.commit()
    assert removed_rows == len(victims), "漏斗该报「真删了几行」（台账用），不是向量数"
    after = store.stats()["embedded"]
    assert after == embedded_before - 2, "只有带向量的那 2 行该从戳里出去"
    assert _stamp(store) == after == 10, f"戳必须恒等于库侧真值：stamp={_stamp(store)} after={after}"


def test_removing_documents_keeps_stamp_equal_to_embedded_count(tmp_path):
    """removed_ids 这条路（导出侧删文档的正路）走完，戳必须等于已嵌行数。"""
    store = _complete_pair_store(tmp_path, count=12)
    store.sync_documents(
        iter(_docs(0, "a")),
        removed_ids=[f"topic/a-doc-{i}" for i in range(5)],
        full=False,
    )
    assert store.stats()["embedded"] == 7
    assert _stamp(store) == 7, (
        "删完 5 篇文档的向量后戳还停在 12 ⇒ 就是今晚 missing=432 的出生形态"
    )


def test_clear_all_vectors_resets_the_stamp(tmp_path):
    """全库清向量（auto_reset 形态）：清完一行都不该带向量，戳也该归零。"""
    store = _complete_pair_store(tmp_path, count=12)
    with sqlite3.connect(store.db_path) as conn:
        conn.row_factory = sqlite3.Row
        cleared = store._clear_all_vectors(conn)
        conn.commit()
    assert cleared == 12
    assert store.stats()["embedded"] == 0
    assert _stamp(store) == 0, "行清光而戳不动 = 凭空造出 12 条假短装"


def test_lowering_never_forges_a_stamp_from_absence(tmp_path):
    """无戳库删块**不许**建戳（与涨戳同规）：从 0 起算会把「从未认证」洗成「已归零」。"""
    store = _complete_pair_store(tmp_path, count=12)
    with sqlite3.connect(store.db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("DELETE FROM knowledge_meta WHERE key = ?", (_STAMP_KEY,))
        conn.commit()
    assert _stamp(store) is None
    with sqlite3.connect(store.db_path) as conn:
        conn.row_factory = sqlite3.Row
        store._forget_chunks(conn, where="source_id = ?", params=("topic/a-doc-0",))
        conn.commit()
    assert _stamp(store) is None, "缺席必须继续缺席，交给认证/重建线（危险侧不擅自起算）"


def test_vector_removal_sites_all_go_through_the_funnel():
    """全部向量移除点一律走漏斗：除漏斗自身外，源码里不许再留裸 DELETE chunk /
    裸置 NULL 的写法。漏斗是这条账的唯一入口，漏一处就漏一种漂
    （今晚就漏在 removed_ids 那处）。
    """
    import ast

    path = (
        Path(__file__).resolve().parents[1]
        / "plugins/bot_unified_runtime/domains/chat_reply/character/vector_knowledge.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    funnel_owner = {"_forget_chunks", "_clear_all_vectors", "_null_out_chunk_vector"}
    offenders: list[str] = []
    for func in [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]:
        if func.name in funnel_owner:
            continue
        for node in ast.walk(func):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "execute"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                continue
            text = " ".join(node.args[0].value.split()).lower()
            if "knowledge_chunks" not in text:
                continue
            if text.startswith("delete from knowledge_chunks") or (
                "update knowledge_chunks" in text and "vector_json = null" in text
            ):
                offenders.append(f"{func.name}:{node.lineno}:{text[:44]}")
    assert not offenders, (
        f"绕过漏斗的向量移除点（这些行的删除不会拉低计数戳）：{offenders}"
    )
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert funnel_owner <= defined, "漏斗本体必须在（_forget_chunks / _clear_all_vectors）"
    assert "_lower_expected_vector_count" in defined


def test_stamp_reconcile_reasons_cover_every_return_path(tmp_path):
    """闭集里每个原因都得真能到达：判据两种形态都认——字面 return，或嵌在
    `reason=<值>` 的告警格式串里（后者才是拒绝路径的常态）。第三个函数的原因
    也算（内存地板住在 `_stamp_reconcile_memory_reason`）。
    """
    import ast

    source = (
        Path(__file__).resolve().parents[1]
        / "plugins/bot_unified_runtime/domains/chat_reply/character/vector_knowledge.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    owners = (
        "certify_expected_vector_count",
        "reconcile_ann_completeness",
        "_stamp_reconcile_memory_reason",
    )
    literals: set[str] = set()
    for name in owners:
        for node in ast.walk(functions[name]):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                literals.add(node.value)
    declared = set(vk._STAMP_RECONCILE_REASONS)
    unreachable = sorted(
        reason
        for reason in declared
        if not any(
            reason == text or f"reason={reason}" in text for text in literals
        )
    )
    assert not unreachable, f"在册却从未被任何 return/日志路径发出的原因：{unreachable}"
    assert "pair_files_inconsistent" in declared and "id_set_mismatch" in declared, (
        "成对性与集合级两格必须在册——少了任一格，纠偏就退化成比条数"
    )


# === 补锁：三格「在册却只有字面量证据」的原因，逐格给行为杀伤力 ================


def test_pair_files_inconsistent_refuses_settling(tmp_path, monkeypatch):
    """文件与代际证明不符（体积/sha 任一处对不上）⇒ 拒纠并保持原戳。

    评审席实锤：删掉整条成对文件比对腿，其余用例仍全绿 ⇒ 上一版只有"字面量在场"
    这种存在性证据。本枚按三种坏法各打一次（index 尺寸 / order 尺寸 / order sha）。
    """
    monkeypatch.setattr(vk, "_available_physical_memory_bytes", lambda: 64 * _GIB)
    for field, value in (
        ("index_bytes", 1),
        ("order_bytes", 1),
        ("order_sha256", "0" * 64),
    ):
        store = _complete_pair_store(tmp_path / str(field))
        _write_raw_stamp(store, "40")
        _mutate_attestation(store, **{field: value})
        assert store.certify_expected_vector_count(drift_correction=True) is None, field
        assert _stamp(store) == 40, f"{field} 被改坏时不许落戳"


def test_too_large_for_set_proof_refuses_before_any_big_read(tmp_path):
    """项数超上限 ⇒ 在读 faiss/序列表**之前**就拒；既不落戳也不产生大开销。"""
    store = _complete_pair_store(tmp_path)
    _write_raw_stamp(store, "40")
    with sqlite3.connect(store.db_path) as conn:
        conn.row_factory = sqlite3.Row
        ok, reason = store.reconcile_ann_completeness(
            conn, db_embedded_count=20, max_items=5
        )
    assert (ok, reason) == (False, "too_large_for_set_proof")
    assert _stamp(store) == 40


def test_db_error_refuses_and_leaves_stamp_alone(tmp_path, monkeypatch, caplog):
    """事务本身炸（SQLITE_BUSY / 库不可写）⇒ 点名 reason=db_error、戳一字不动。"""
    store = _complete_pair_store(tmp_path)
    _write_raw_stamp(store, "40")
    monkeypatch.setattr(vk, "_available_physical_memory_bytes", lambda: 64 * _GIB)

    real_connect = store._connect
    calls = {"n": 0}

    def _boom():
        # 只在 certify 那一发上炸；后面读回戳必须还能连（否则测的是夹具不是判据）。
        calls["n"] += 1
        if calls["n"] == 1:
            raise sqlite3.OperationalError("database is locked")
        return real_connect()

    monkeypatch.setattr(store, "_connect", _boom)
    with caplog.at_level(logging.WARNING, logger=vk.logger.name):
        assert store.certify_expected_vector_count(drift_correction=True) is None
    messages = [r.getMessage() for r in caplog.records if _REFUSAL_TOKEN in r.getMessage()]
    assert messages and "reason=db_error" in messages[0]
    assert _stamp(store) == 40
