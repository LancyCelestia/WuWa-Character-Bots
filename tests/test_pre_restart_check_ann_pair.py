"""重启前体检第 13 项 ann_pair：ANN 这一代到底可不可用（S141，2026-09-26）.

全部离线：假库在 tmp_path 里现造（`knowledge_meta` 单表 + 两枚 ANN 文件），
零网络、零真库、零 faiss——本项**刻意不去 mmap 加载 `.index`**（那是重启后要付
一秒的事），ntotal 取 SQLite 里的代际证明，并按体积只 stat 两个 ANN 文件。

五态各一例（PASS / REFUSED / UNSTAMPED / MEMORY_SKIP / NOT_APPLICABLE），
外加签名不符与文件缺席两枚（防"证明自洽但磁盘没东西"的假绿）、键名与阈值
同源锁（判据不许写第二把尺），以及 S159 代次覆盖锁（发现 2 的假 PASS 形态：
戳/签名/文件全对但当前代次 > 盖章代次 ⇒ 必须红并同屏点名两个数）与
注毒自证（造代次超前状态必红、还原逐字节 cmp，兼证体检只读不写库）。
"""

from __future__ import annotations

import filecmp
import json
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import pre_restart_check as prc

PASS, SKIP, FAIL = prc.PASS, prc.SKIP, prc.FAIL

INDEX_NAME = "kb_wiki_faiss.index"
ORDER_NAME = "kb_wiki_faiss.order.json"
SIG = "http://127.0.0.1:11434/v1|bge-m3"

STAMP_KEY = "ann_expected_vector_count"
ATTESTATION_KEY = "ann_pair_attestation"
ANN_SIG_KEY = "ann_signature"
EMBED_SIG_KEY = "embedding_signature"
MEMORY_SKIP_KEY = "ann_build_last_memory_skip"
SUMMARY_KEY = "kb_sync_last_summary"
GENERATION_KEY = "ann_embed_generation"
ATTEST_GENERATION_FIELD = "embed_generation"


# ---------------------------------------------------------------------------
# 假 kb_wiki 库构造
# ---------------------------------------------------------------------------

def make_wiki_db(
    tmp_path: Path,
    *,
    stamp: str | None = "1000",
    ntotal: int = 1000,
    count: int | None = None,
    attested_signature: str | None = SIG,
    live_signature: str = SIG,
    index_bytes: int | None = 1234,
    order_bytes: int | None = 56,
    memory_skip: dict[str, object] | None = None,
    summary: dict[str, object] | None = None,
    embed_generation: str | None = None,
    attested_generation: int | None = None,
    write_files: bool = True,
    with_meta_table: bool = True,
    slot: str = "a",
) -> tuple[Path, dict[str, str]]:
    """造一座 wiki 向量库（只建 knowledge_meta 一张表）+ 同目录两枚 ANN 文件.

    返回 (db_path, env)：env 只带 BOT_KB_WIKI_DB_PATH 一枚键（绝对路径，
    不经 runtime_paths 重映射，保持夹具可读）。`slot` 让同一 tmp_path 下
    能并排放多座互不干扰的库（一枚用例里要比两种形态时用它分开）。
    `embed_generation`（meta 行原文）与 `attested_generation`（证明 JSON 字段）
    分别控制 S159 代次闸的两侧——两者都缺省 = 存量库形态（两行俱无 ⇒ 0 对 0）。
    """
    data_root = tmp_path / f"rt_data_{slot}"
    data_root.mkdir(parents=True, exist_ok=True)
    db_path = data_root / "kb_wiki_embeddings.sqlite3"
    if with_meta_table:
        con = sqlite3.connect(str(db_path))
        con.execute(
            "CREATE TABLE IF NOT EXISTS knowledge_meta ("
            "key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL)"
        )
        rows: dict[str, str] = {}
        if stamp is not None:
            rows[STAMP_KEY] = stamp
        if embed_generation is not None:
            rows[GENERATION_KEY] = embed_generation
        if attested_signature is not None or live_signature:
            rows[ANN_SIG_KEY] = live_signature
            rows[EMBED_SIG_KEY] = live_signature
        if attested_signature is not None:
            attestation_payload: dict[str, object] = {
                "ntotal": ntotal,
                "count": ntotal if count is None else count,
                "signature": attested_signature,
                "index_bytes": index_bytes if index_bytes is not None else 0,
                "order_bytes": order_bytes if order_bytes is not None else 0,
            }
            if attested_generation is not None:
                attestation_payload[ATTEST_GENERATION_FIELD] = attested_generation
            rows[ATTESTATION_KEY] = json.dumps(attestation_payload)
        if memory_skip is not None:
            rows[MEMORY_SKIP_KEY] = json.dumps(memory_skip)
        if summary is not None:
            rows[SUMMARY_KEY] = json.dumps(summary)
        con.executemany(
            "INSERT INTO knowledge_meta (key, value) VALUES (?, ?)",
            list(rows.items()),
        )
        con.commit()
        con.close()
    if write_files:
        (data_root / INDEX_NAME).write_bytes(
            b"i" * (index_bytes if index_bytes is not None else 0)
        )
        (data_root / ORDER_NAME).write_text(
            "x" * (order_bytes if order_bytes is not None else 0), encoding="utf-8"
        )
    env = {"BOT_KB_WIKI_DB_PATH": str(db_path)}
    return db_path, env


def verdict_of(tmp_path: Path, *, slot: str = "a", **kwargs: object):
    db_path, env = make_wiki_db(tmp_path, slot=slot, **kwargs)  # type: ignore[arg-type]
    return prc.inspect_ann_generation_pair(env, tmp_path), db_path


# ---------------------------------------------------------------------------
# 五态
# ---------------------------------------------------------------------------

def test_ann_pair_state_pass(tmp_path: Path) -> None:
    """戳 == 代际证明 ntotal == count，签名一致，两文件在位 ⇒ PASS（生产实况形）."""
    verdict, db_path = verdict_of(
        tmp_path,
        stamp="740996",
        ntotal=740996,
        index_bytes=4096,
        order_bytes=64,
        summary={
            "ann_rebuilt": True,
            "ann_reason": "built",
            "embed_pending": 0,
            "embedded_after": 740996,
            "chunks_after": 740996,
        },
    )
    assert verdict.state == prc.ANN_STATE_PASS
    assert verdict.missing == 0
    assert verdict.headline.startswith("这一代 ANN 可用")
    joined = "\n".join(verdict.facts)
    assert "计数戳：740996" in joined
    assert "代际证明 ntotal：740996" in joined
    assert "代际签名：与库内 ann_signature 一致" in joined
    assert "ANN 文件：两枚在位且体积与代际证明相符" in joined
    assert "上一轮 kb-sync：ann_reason=built" in joined
    assert "embed_pending=0" in joined
    assert "短装行数：0" in joined
    assert "内存门留痕：无" in joined
    assert db_path.is_file()  # 夹具自检：库真的建起来了

    # ntotal 比戳多（发布中途被杀的残态）：真身不算短装，本项同判、但必须报出来
    over, _ = verdict_of(tmp_path, slot="over", stamp="900", ntotal=1000)
    assert over.state == prc.ANN_STATE_PASS
    assert over.missing == -100
    assert "短装行数：0（ntotal 比戳多 100 条" in "\n".join(over.facts)

    result = prc.check_ann_generation_pair(
        {"BOT_KB_WIKI_DB_PATH": str(db_path)}, tmp_path
    )
    assert result.id == "ann_pair"
    assert result.status == PASS
    assert "\n" in result.message  # 结论一句 + 每个事实单独一行中文标签


def test_ann_pair_state_refused_reports_missing_count(tmp_path: Path) -> None:
    """戳高于 ntotal ⇒ REFUSED 并点名短装行数（09-22 停摆的那一格）."""
    verdict, db_path = verdict_of(tmp_path, stamp="741428", ntotal=740996)
    assert verdict.state == prc.ANN_STATE_REFUSED
    assert verdict.missing == 432
    assert verdict.reason == "short_by_stamp"
    joined = "\n".join(verdict.facts)
    assert "计数戳：741428" in joined
    assert "代际证明 ntotal：740996" in joined
    assert "短装行数：432" in joined

    result = prc.check_ann_generation_pair(
        {"BOT_KB_WIKI_DB_PATH": str(db_path)}, tmp_path
    )
    assert result.status == FAIL
    assert "回落暴力扫描" in result.message
    assert "432" in result.message
    assert "knowledge-sync" in result.fix_hint


def test_ann_pair_state_unstamped(tmp_path: Path) -> None:
    """有代际证明但没有计数戳 ⇒ UNSTAMPED（load_ann_index 同判：无从证明完备）."""
    verdict, db_path = verdict_of(tmp_path, stamp=None, ntotal=1000)
    assert verdict.state == prc.ANN_STATE_UNSTAMPED
    assert verdict.reason == "unstamped"
    assert verdict.missing is None
    joined = "\n".join(verdict.facts)
    assert "计数戳：缺失（无从判定）" in joined
    assert "代际证明 ntotal：1000" in joined

    result = prc.check_ann_generation_pair(
        {"BOT_KB_WIKI_DB_PATH": str(db_path)}, tmp_path
    )
    assert result.status == FAIL
    assert "无戳" in result.message or "unstamped" in result.message


def test_ann_pair_state_memory_skip_names_gate_and_shortfall(tmp_path: Path) -> None:
    """短装 + 上一轮内存门拒建留痕 ⇒ MEMORY_SKIP（根因优先，missing 数仍在事实行）."""
    verdict, db_path = verdict_of(
        tmp_path,
        stamp="741428",
        ntotal=740996,
        memory_skip={
            "available": "1.62GiB",
            "required": "3.90GiB",
            "floor": "4.50GiB",
            "headroom": "128MiB",
            "expected_vectors": 741428,
            "dim": 1024,
            "probe_failed": False,
            "forced": False,
            "stage": "pre",
            "at_unix": 1790000000,
        },
    )
    assert verdict.state == prc.ANN_STATE_MEMORY_SKIP
    assert verdict.reason == "insufficient_memory"
    assert verdict.missing == 432
    joined = "\n".join(verdict.facts)
    assert "内存门留痕：上一轮 ANN 重建被挡" in joined
    assert "可用 1.62GiB < 需要 3.90GiB" in joined
    assert "未越门" in joined
    assert "短装行数：432" in joined  # 根因抢了状态名，短装数一个字不藏

    result = prc.check_ann_generation_pair(
        {"BOT_KB_WIKI_DB_PATH": str(db_path)}, tmp_path
    )
    assert result.status == FAIL
    assert "内存门" in result.message
    assert "--ann-force-low-memory" in result.fix_hint


def test_ann_pair_state_not_applicable(tmp_path: Path) -> None:
    """库不存在 / 库在但三行全无 ⇒ NOT_APPLICABLE（不假红也不假绿）."""
    missing_db = prc.check_ann_generation_pair(
        {"BOT_KB_WIKI_DB_PATH": str(tmp_path / "nope" / "kb_wiki_embeddings.sqlite3")},
        tmp_path,
    )
    assert missing_db.status == SKIP
    assert "不适用" in missing_db.message

    no_db, env = make_wiki_db(tmp_path, with_meta_table=False, write_files=False)
    assert not no_db.exists()
    assert prc.inspect_ann_generation_pair(env, tmp_path).state == prc.ANN_STATE_NOT_APPLICABLE
    assert prc.check_ann_generation_pair(env, tmp_path).status == SKIP

    no_keys, env2 = make_wiki_db(tmp_path)
    con = sqlite3.connect(str(no_keys))
    con.execute("DELETE FROM knowledge_meta")
    con.commit()
    con.close()
    assert (
        prc.inspect_ann_generation_pair(env2, tmp_path).state
        == prc.ANN_STATE_NOT_APPLICABLE
    )


# ---------------------------------------------------------------------------
# 附加两枚：假绿防线 + 同源锁
# ---------------------------------------------------------------------------

def test_ann_pair_signature_mismatch_and_absent_files_are_named(tmp_path: Path) -> None:
    """签名不符 / ANN 文件缺席都必须点名（证明自洽但磁盘没东西 = 生产必拒用）."""
    verdict, _db_path = verdict_of(tmp_path, stamp="1000", ntotal=1000, live_signature="other-model|dim=1024")
    assert verdict.state == prc.ANN_STATE_REFUSED
    assert verdict.reason == "signature_mismatch"
    joined = "\n".join(verdict.facts)
    assert "代际签名：与库内 ann_signature 不符" in joined

    gone, env = make_wiki_db(tmp_path, slot="b", stamp="1000", ntotal=1000, write_files=False)
    assert gone.is_file()
    verdict2 = prc.inspect_ann_generation_pair(env, tmp_path)
    assert verdict2.state == prc.ANN_STATE_REFUSED
    assert verdict2.reason == "pair_files_absent"
    assert "ANN 文件：" in "\n".join(verdict2.facts)
    assert prc.check_ann_generation_pair(env, tmp_path).status == FAIL


def test_ann_pair_generation_ahead_is_refused_and_names_both_numbers(tmp_path: Path) -> None:
    """S159 形态（发现 2 的假 PASS）：戳/签名/文件全对，但当前代次 > 盖章代次 ⇒ 必红.

    真身 load_ann_index 在这一格必然 coverage refused（删+嵌同轮把标量戳拉回原值，
    `ntotal >= 戳` 恒成立却没装下新那批）；预检若照旧 PASS 就是第二把尺失真——
    必须 REFUSED(coverage) 并把两个数字同屏点名（headline 与事实行都要有）。
    """
    verdict, db_path = verdict_of(
        tmp_path,
        stamp="740996",
        ntotal=740996,
        embed_generation="7",
        attested_generation=5,
    )
    assert verdict.state == prc.ANN_STATE_REFUSED
    assert verdict.reason == "coverage_behind_generation"
    assert verdict.missing == 0  # 戳判全过——红只能来自代次这发
    assert "7" in verdict.headline and "5" in verdict.headline
    joined = "\n".join(verdict.facts)
    assert "嵌入代次：当前 7 ／ 证明盖章代次 5" in joined
    assert "代次超前" in joined

    result = prc.check_ann_generation_pair(
        {"BOT_KB_WIKI_DB_PATH": str(db_path)}, tmp_path
    )
    assert result.status == FAIL
    assert "回落暴力扫描" in result.message
    assert "knowledge-sync" in result.fix_hint


def test_ann_pair_generation_equal_and_legacy_forms_stay_pass(tmp_path: Path) -> None:
    """两值相等 ⇒ PASS；存量形态（两行俱无 0 对 0、证明缺字段）放行语义一字不变.

    只严不松的另一半：真身代次闸只拦 `generation > covered`（covered > generation
    的非自然态由 plugins 侧另案登记——发现 4，不在预检这格改口，禁第二把尺）。
    """
    equal, _ = verdict_of(
        tmp_path, slot="eq", stamp="1000", ntotal=1000,
        embed_generation="3", attested_generation=3,
    )
    assert equal.state == prc.ANN_STATE_PASS
    assert "嵌入代次：当前 3 ／ 证明盖章代次 3" in "\n".join(equal.facts)

    legacy, _ = verdict_of(tmp_path, slot="legacy", stamp="1000", ntotal=1000)
    assert legacy.state == prc.ANN_STATE_PASS  # 两行俱无 ⇒ 0 对 0，现状逐字节同形

    covered_ahead, _ = verdict_of(
        tmp_path, slot="ahead", stamp="1000", ntotal=1000,
        embed_generation="1", attested_generation=2,
    )
    assert covered_ahead.state == prc.ANN_STATE_PASS  # 真身同判：只拦反方向


def test_ann_pair_generation_malformed_folds_to_zero_like_true_source(tmp_path: Path) -> None:
    """代次取数口径同 `_parse_embed_generation`：缺行/畸形/负值折 0，不许读成已证.

    `True` 这类布尔垃圾折 0（`int(str(True))` 抛错）⇒ 对 5 不构成超前；
    证明里缺 `embed_generation` 字段 ⇒ 盖章 0 = 从未证过任何一批，当前 9 > 0 ⇒ 红。
    """
    garbage, _ = verdict_of(
        tmp_path, slot="garbage", stamp="1000", ntotal=1000,
        embed_generation="True", attested_generation=5,
    )
    assert garbage.state == prc.ANN_STATE_PASS

    no_field, _ = verdict_of(
        tmp_path, slot="nofield", stamp="1000", ntotal=1000, embed_generation="9",
    )
    assert no_field.state == prc.ANN_STATE_REFUSED
    assert no_field.reason == "coverage_behind_generation"
    assert "证明盖章代次 0" in "\n".join(no_field.facts)

    negative, _ = verdict_of(
        tmp_path, slot="neg", stamp="1000", ntotal=1000, embed_generation="-2",
    )
    assert negative.state == prc.ANN_STATE_PASS  # 负值折 0（真身 max(0, parsed) 同口径）


def test_ann_pair_generation_poison_flips_red_and_restore_is_byte_exact(tmp_path: Path) -> None:
    """注毒自证：同一座库插一行「代次超前」⇒ 必红；撤毒还原后逐字节一致、复绿.

    毒插 INSERT（不是改判据），还原用快照回写 + `filecmp(shallow=False)` 逐字节
    对账——这同时反证体检只读不写库：PASS 态与还原态的字节都要等于 pristine 快照。
    """
    db_path, env = make_wiki_db(
        tmp_path, slot="poison", stamp="1000", ntotal=1000,
        embed_generation="1", attested_generation=1,
    )
    snapshot = tmp_path / "poison_db.snapshot"
    shutil.copy2(db_path, snapshot)

    assert prc.inspect_ann_generation_pair(env, tmp_path).state == prc.ANN_STATE_PASS
    assert filecmp.cmp(str(db_path), str(snapshot), shallow=False)  # 体检跑过，字节未动

    try:
        con = sqlite3.connect(str(db_path))
        con.execute(
            "UPDATE knowledge_meta SET value = ? WHERE key = ?",
            ("2", GENERATION_KEY),
        )  # 注毒：当前代次抬到盖章代次之上（自然形态 = 盖章后又嵌了一批）
        con.commit()
        con.close()
        poisoned = prc.inspect_ann_generation_pair(env, tmp_path)
        assert poisoned.state == prc.ANN_STATE_REFUSED, "代次超前不判红 = 发现 2 的假绿复发"
        assert poisoned.reason == "coverage_behind_generation"
        assert prc.check_ann_generation_pair(env, tmp_path).status == FAIL
    finally:
        shutil.copy2(snapshot, db_path)  # 撤毒：快照回写

    assert filecmp.cmp(str(db_path), str(snapshot), shallow=False), "撤毒必须逐字节还原"
    assert prc.inspect_ann_generation_pair(env, tmp_path).state == prc.ANN_STATE_PASS


def test_ann_pair_keys_and_threshold_match_single_source() -> None:
    """判据不许有第二把尺：键名与 `_ANN_COMPLETENESS_MAX_MISSING` 逐字对住真身.

    读的是 `vector_knowledge.py` 的**源码文本**（该模块 import 会拉起 faiss 与
    插件依赖，体检脚本按既有惯例不 import 插件根），比对的是本项里写死的键名字
    面量与真身常量赋值。任何一侧改名 ⇒ 本例红。
    """
    source = (
        PROJECT_ROOT
        / "plugins"
        / "bot_unified_runtime"
        / "domains"
        / "chat_reply"
        / "character"
        / "vector_knowledge.py"
    ).read_text(encoding="utf-8")

    def literal_of(constant: str) -> str:
        marker = f"{constant} = \""
        start = source.index(marker) + len(marker)
        return source[start : source.index('"', start)]

    assert prc.ANN_STAMP_META_KEY == literal_of("_EMBEDDED_COUNT_KEY")
    assert prc.ANN_ATTESTATION_META_KEY == literal_of("_ANN_ATTESTATION_KEY")
    assert prc.ANN_MEMORY_SKIP_META_KEY == literal_of("_ANN_MEMORY_SKIP_META_KEY")
    assert ATTESTATION_KEY == prc.ANN_ATTESTATION_META_KEY
    # S159 代次闸两侧的名字也要对住真身（发现 2 的修复纳入单源锁）；且代次键
    # 必须在取数名册里——不在名册 = 读不到 = 假 PASS 复发的结构形态
    assert prc.ANN_EMBED_GENERATION_META_KEY == literal_of("_EMBED_GENERATION_KEY")
    assert prc.ANN_ATTEST_EMBED_GENERATION_FIELD == literal_of(
        "_ATTEST_EMBED_GENERATION_FIELD"
    )
    assert GENERATION_KEY == prc.ANN_EMBED_GENERATION_META_KEY
    assert ATTEST_GENERATION_FIELD == prc.ANN_ATTEST_EMBED_GENERATION_FIELD
    assert prc.ANN_EMBED_GENERATION_META_KEY in prc._ANN_META_KEYS

    kb_wiki_src = (
        PROJECT_ROOT
        / "plugins"
        / "bot_unified_runtime"
        / "domains"
        / "location"
        / "knowledge"
        / "kb_wiki.py"
    ).read_text(encoding="utf-8")
    assert prc.ANN_SUMMARY_META_KEY == "kb_sync_last_summary"
    assert 'SYNC_SUMMARY_META_KEY = "kb_sync_last_summary"' in kb_wiki_src

    # 短装容差：真身是 0（一条都不许少），本项判据必须同值
    assert "_ANN_COMPLETENESS_MAX_MISSING = 0" in source
    assert prc.ANN_COMPLETENESS_MAX_MISSING == 0

    # 默认库路径与 ANN 文件名两处口径也要对住真身
    assert 'bot_kb_wiki_db_path: str = "data/kb_wiki_embeddings.sqlite3"' in (
        (PROJECT_ROOT / "plugins" / "bot_unified_runtime" / "config.py").read_text(
            encoding="utf-8"
        )
    )
    assert prc.DEFAULT_KB_WIKI_DB == "data/kb_wiki_embeddings.sqlite3"
    assert 'with_name("kb_wiki_faiss.index")' in kb_wiki_src
    assert 'with_name("kb_wiki_faiss.order.json")' in kb_wiki_src
    assert prc.KB_WIKI_ANN_INDEX_NAME == "kb_wiki_faiss.index"
    assert prc.KB_WIKI_ANN_ORDER_NAME == "kb_wiki_faiss.order.json"


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
