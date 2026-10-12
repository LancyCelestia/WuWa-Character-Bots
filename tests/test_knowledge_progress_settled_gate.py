"""`scripts/knowledge_progress.py` 的收工判据离线锁（零网络、零生产库）。

立锁缘由（2026-09-22 本波自己踩的）：kb-sync 摘要里的 `embed_pending` 是**本轮投料数（分母）**，
不是"还剩多少没嵌"。把它读成剩余量，就会写出一条永不成立的判据 `embed_pending == 0`，
而一次完全成功的同步（实跑值 `chunks=embedded=embed_pending=24060`）会被判成"没收工"。
同型错误还有第二条：块表 100% 带向量也不等于收工（投料阶段就把行落库了）。
第三条失明＝**索引实数腿缺牙**（2026-10-08 补）：判据只比 `ann_expected_vector_count`
与库内列、从不开 ``.index``，短装的索引照样打出一排 ``[ok]``——本件下半部的
「短装／取不到／接地／结构」四组锁钉的就是这一条（用例清单看本文件自身，不在此抄数）。
第四条失明＝**从没问过语料名册**（2026-10-12 补）：上面几条比的全是「库内几本账自不自洽」，
连摘要里的 `documents_after` 也是同步侧自己盖的**戳**——戳只会自证。于是"货到了没进索引"
（名册比仓侧台账多出一截）在旧判据下静默通过、照样打「这一轮已投完收工」。下半部
「名册对榫腿」那一组钉这条：恒等式 `回读计数 == 名册声称计数`（差值非零逐字点名、零容差）、
取不到一律 UNDECIDABLE 不许折成 ok、回读只准 SQL 实读不许拿戳顶替、整层只读。
"""

from __future__ import annotations

import ast
import json
import sqlite3
import struct
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import knowledge_progress as kp

SUMMARY_COMPLETE = {
    "started_at": "2026-09-21T22:39:50Z",
    "finished_at": "2026-09-21T23:10:27Z",
    "ok": True,
    "error_kind": "none",
    "added": 7662,
    "changed": 0,
    "removed": 0,
    "chunks": 24060,
    "embedded": 24060,
    "embed_pending": 24060,
    "documents_after": 12,
    "chunks_after": 40,
    "embedded_after": 40,
    "ann_rebuilt": True,
    "reconcile_status": "ok",
}

#: 夹具哨兵：``ann_ntotal=_NO_INDEX`` ⇒ 根本不写 ``.index``（"索引实数取不到"那一形）。
_NO_INDEX = object()
#: 桩件头里的维数读数（本尺只判 ``dim > 0``，具体值不进判据）。
_STUB_DIM = 8


def _write_index_header(
    path: Path, ntotal: int, *, dim: int = _STUB_DIM, fourcc: bytes = b"IHNs"
) -> Path:
    """写一枚**只有序列化头**的 ``.index``（``fourcc`` + int32 维数 + int64 ntotal，共 16 B）。

    头部腿只读前 16 字节，所以桩件里没有正文——「16 字节的桩件也读得出来」本身就是
    本尺不整本载入的结构自证（另由 ``test_leg_never_loads_the_whole_index`` 拿 AST 钉住）。
    """
    path.write_bytes(fourcc + struct.pack("<iq", dim, ntotal))
    return path


def _leg_lines(out: str) -> list[str]:
    """取人读的索引实数那一行（不含下方 `↳` 修法提示行）。"""
    return [line.strip() for line in out.splitlines() if "ANN 索引实数" in line]


def _make_store(
    root: Path,
    *,
    embedded_rows: int,
    summary: dict,
    ann_expected: int,
    ann_ntotal: object | None = None,
    attestation: dict | None = None,
    docs_rows: int = 12,
    declared_documents: int | None = None,
    roster_sidecar: bool = True,
) -> None:
    """造一枚最小 wiki 库：40 条块行、`docs_rows` 篇台账、一枚收工摘要，外加盘上那枚 ``.index``。

    ``ann_ntotal`` 控制索引实数腿的夹具形态：``None``＝与应嵌数齐平（装下）、
    整数＝短装/多装到那个数、``_NO_INDEX``＝**根本不写 ``.index``**（取不到形态）。
    ``attestation`` 给一行 ``ann_pair_attestation``（第②级退路的读数来源）。

    名册那一层（2026-10-12 补）：``declared_documents``＝语料清单**声称**的篇数（缺省与
    ``docs_rows`` 齐平＝正常路径），并在 ``root/corpus_manifest.json`` 落一份**与声称数自洽**
    的 sidecar（``entries`` 真给满 ``declared_documents`` 条、id/ hash 覆盖住台账里那
    ``docs_rows`` 行）。``_run`` 把 ``kp._corpus_manifest`` 指到这份 sidecar 上——**本件因此
    永不读生产库根**（真跑那一份凭据在席报里，不在此）。``roster_sidecar=False`` 造"名册取不到"
    那一形（腿必须 UNDECIDABLE，不许折成 ok）。
    """
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    declared = docs_rows if declared_documents is None else int(declared_documents)
    con = sqlite3.connect(data / "kb_wiki_embeddings.sqlite3")
    with con:
        con.execute("CREATE TABLE knowledge_docs (doc_id TEXT PRIMARY KEY, hash TEXT)")
        con.execute(
            "CREATE TABLE knowledge_chunks (chunk_id TEXT PRIMARY KEY, vector_json TEXT)"
        )
        con.execute("CREATE TABLE knowledge_meta (key TEXT PRIMARY KEY, value TEXT)")
        con.executemany(
            "INSERT INTO knowledge_docs VALUES (?, ?)",
            [(f"d{i}", f"h{i}") for i in range(docs_rows)],
        )
        con.executemany(
            "INSERT INTO knowledge_chunks VALUES (?, ?)",
            [(f"c{i}", "[0.1]" if i < embedded_rows else "") for i in range(40)],
        )
        con.execute(
            "INSERT INTO knowledge_meta VALUES ('kb_sync_last_summary', ?)",
            (json.dumps(summary, ensure_ascii=False),),
        )
        con.execute(
            "INSERT INTO knowledge_meta VALUES ('ann_expected_vector_count', ?)",
            (str(ann_expected),),
        )
        if attestation is not None:
            con.execute(
                "INSERT INTO knowledge_meta VALUES ('ann_pair_attestation', ?)",
                (json.dumps(attestation, ensure_ascii=False),),
            )
    con.close()
    if roster_sidecar:
        (root / "corpus_manifest.json").write_text(
            json.dumps(
                {
                    "documents": declared,
                    "entries": {f"d{i}": f"h{i}" for i in range(declared)},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    if ann_ntotal is not _NO_INDEX:
        _write_index_header(
            data / "kb_wiki_faiss.index",
            ann_expected if ann_ntotal is None else int(ann_ntotal),  # type: ignore[arg-type]
        )
    # memory 库也要有一枚，否则脚本会打「打不开」而不是进度
    (data / "knowledge_embeddings.sqlite3").touch()


def _fixture_manifest(root: Path) -> tuple[dict | None, int | None, str]:
    """把 sidecar 当名册读回来（与真身 `_corpus_manifest` 同签名，测试里替掉线上取数口）。"""
    path = root / "corpus_manifest.json"
    if not path.is_file():
        return None, None, "manifest_absent"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw, int(raw["documents"]), ""


#: 名册腿在 pytest 里绝不碰线上装载口：真身 ``_corpus_config`` 会去读 .env、拉插件链，
#: 既不是本件要锁的东西，也会把**生产库根**混进 tmp 夹具。缺了装载口 ⇒ 集合那一层必须
#: 明写「未做、只判到计数那一层」——这正是本件要钉的诚实形态（不假装做到了）。
_ISOLATED_CORPUS_CONFIG: tuple[None, str] = (
    None,
    f"{kp.CALIBER_ENV_FORBIDDEN}:pytest_isolation",
)


def _run(
    monkeypatch,
    root: Path,
    capsys,
    argv: tuple[str, ...] = (),
    *,
    corpus_config: tuple[object | None, str] = _ISOLATED_CORPUS_CONFIG,
) -> str:
    monkeypatch.setattr(kp, "runtime_path", lambda rel: root / rel)
    monkeypatch.setattr(kp, "_corpus_manifest", lambda: _fixture_manifest(root))
    monkeypatch.setattr(kp, "_corpus_config", lambda: corpus_config)
    kp.main(list(argv))
    return capsys.readouterr().out


def _read_docs_count(root: Path) -> int:
    """现读夹具台账实数（派生式判据用：测试里的"应有值"一律从夹具本身算，不抄字面）。"""
    con = sqlite3.connect(root / "data" / "kb_wiki_embeddings.sqlite3")
    try:
        return int(con.execute("SELECT COUNT(*) FROM knowledge_docs").fetchone()[0])
    finally:
        con.close()


def _declared_of(root: Path) -> int:
    """现读名册声称数（同上：派生，不写死）。"""
    return int(
        json.loads((root / "corpus_manifest.json").read_text(encoding="utf-8"))["documents"]
    )


def _roster_lines(out: str) -> list[str]:
    """取名册对榫那一行（不含下方 `↳` 修法提示行）。"""
    return [line.strip() for line in out.splitlines() if kp.ROSTER_LEG_MARK in line]


def test_finished_round_is_settled_even_though_embed_pending_is_nonzero(monkeypatch, tmp_path, capsys):
    """实跑真值复刻：embed_pending=本轮投料数，done>=pending 即清空。"""
    _make_store(tmp_path, embedded_rows=40, summary=SUMMARY_COMPLETE, ann_expected=40)
    out = _run(monkeypatch, tmp_path, capsys)
    assert "这一轮已投完收工" in out
    assert "[!!]" not in out


def test_row_counts_alone_are_not_a_settlement_criterion(monkeypatch, tmp_path, capsys):
    """块行 100% 带向量、但本轮只嵌了分母的一半 ⇒ 必须判未收工。"""
    half = dict(SUMMARY_COMPLETE, embedded=12000, embed_pending=24060)
    _make_store(tmp_path, embedded_rows=40, summary=half, ann_expected=40)
    out = _run(monkeypatch, tmp_path, capsys)
    assert "未收工" in out
    assert "[!!] 本轮队列清空" in out


def test_ann_count_drift_blocks_settlement(monkeypatch, tmp_path, capsys):
    """摘要自称投完，但 ANN 应嵌数与库内已嵌数两本账不同源 ⇒ 不算收工。"""
    _make_store(tmp_path, embedded_rows=40, summary=SUMMARY_COMPLETE, ann_expected=16)
    out = _run(monkeypatch, tmp_path, capsys)
    assert "未收工" in out
    assert "[!!] ANN 应嵌数" in out


def test_missing_summary_is_reported_honestly(monkeypatch, tmp_path, capsys):
    """库里有条目却从没跑完过同步：不得凭行数说"完成"。"""
    _make_store(tmp_path, embedded_rows=40, summary=SUMMARY_COMPLETE, ann_expected=40)
    store = tmp_path / "data" / "kb_wiki_embeddings.sqlite3"
    con = sqlite3.connect(store)
    with con:
        con.execute("DELETE FROM knowledge_meta WHERE key = 'kb_sync_last_summary'")
    con.close()
    out = _run(monkeypatch, tmp_path, capsys)
    assert "还没有 kb-sync 收工摘要" in out
    assert "已投完收工" not in out


def test_null_after_fields_render_unmeasured_not_zero(monkeypatch, tmp_path, capsys):
    """失败轮摘要的 after 三件是 null（未测得）：进度页打「未测得」，判据判未收工。

    2026-09-27 汇总修复的读侧跟随：`_sync_summary` 不再把未回填的默认 0 落盘，
    改写 null；本脚本若把 None 折回 0（旧 `num()` 行为），"没测"就又被读成
    "测得 0"——三态在展示与判据两处都必须保住。
    """
    failed = dict(
        SUMMARY_COMPLETE,
        ok=False,
        error_kind="cancelled",
        documents_after=None,
        chunks_after=None,
        embedded_after=None,
    )
    _make_store(tmp_path, embedded_rows=40, summary=failed, ann_expected=40)
    out = _run(monkeypatch, tmp_path, capsys)
    assert "documents_after=未测得" in out
    assert "chunks_after=未测得" in out
    assert "embedded_after=未测得" in out
    # 判据行同样报「未测得」，且不得出现伪装成测得值的 "embedded_after=0"。
    assert "库内已嵌(未测得)" in out
    assert "embedded_after=0" not in out
    assert "已投完收工" not in out
    assert "未收工" in out


def test_stale_round_before_baseline_never_counts_as_tonight_settled(monkeypatch, tmp_path, capsys):
    """**上一轮**完全收工，但今晚这档还没开跑 ⇒ 不许打「已投完收工」。

    值守脚本就栽过这一格：它第一轮就 grep 到"收工"自行退出，而那时生产侧
    连新摘要都还没写。判据必须带基线（`--since`），否则报的是历史不是今夜。
    """
    _make_store(tmp_path, embedded_rows=40, summary=SUMMARY_COMPLETE, ann_expected=40)
    out = _run(monkeypatch, tmp_path, capsys, ("--since", "2026-09-22T00:00:00Z"))
    assert "本轮未开始" in out
    assert "已投完收工" not in out, "拿上一轮的收工冒充今晚＝假绿"


def test_baseline_older_than_the_round_still_reports_settled(monkeypatch, tmp_path, capsys):
    """基线早于本轮 started_at 时，判据照常成立（守卫不许把正常路径也堵死）。"""
    _make_store(tmp_path, embedded_rows=40, summary=SUMMARY_COMPLETE, ann_expected=40)
    out = _run(monkeypatch, tmp_path, capsys, ("--since", "2026-09-01T00:00:00Z"))
    assert "这一轮已投完收工" in out


# ---------------------------------------------------------------------------
# 索引实数腿（2026-10-08 补牙）：账面数对得上 ≠ 盘上那枚 .index 真装下了。
# 立锁缘由：这条判据曾长期只比 `ann_expected_vector_count` 与库内列，**从不开 .index**，
# 于是短装的索引照样打出一排 `[ok]`；同一天三把独立尺都现算出索引实数比应嵌数少一大截。
# 下面两发注毒（短装夹具／取不到夹具）就是那条无牙的尺当场该喊而没喊的两种形态。
# ---------------------------------------------------------------------------


def test_leg_reports_three_numbers_with_signed_gap(monkeypatch, tmp_path, capsys):
    """装下的形态：三个数并列 + 带符号差 0，且这行是 [ok]（正常路径不许被新腿堵死）。"""
    _make_store(tmp_path, embedded_rows=40, summary=SUMMARY_COMPLETE, ann_expected=40)
    out = _run(monkeypatch, tmp_path, capsys)
    leg = _leg_lines(out)
    assert len(leg) == 1, f"索引实数腿应当只有一行，实得 {leg}"
    assert leg[0].startswith("[ok]"), leg
    assert "［应嵌(40)／库内已嵌(40)／索引ntotal(40)／差(应嵌-索引)=+0，正数＝短装］" in leg[0]
    assert "源=索引头实读" in leg[0]
    assert "这一轮已投完收工" in out
    assert "[!!]" not in out


def test_short_loaded_index_blocks_settlement(monkeypatch, tmp_path, capsys):
    """注毒①：索引实数 ntotal 比应嵌数少 9 条 ⇒ 该行必须从 ok 变红、整轮判未收工。

    这正是补牙前那把尺的失明形态：`ann_expected == embedded_after` 两条账面数完全相等，
    而盘上的索引短装——旧尺照打 `[ok]`，新腿必须自己喊出来。
    """
    _make_store(
        tmp_path, embedded_rows=40, summary=SUMMARY_COMPLETE, ann_expected=40, ann_ntotal=31
    )
    out = _run(monkeypatch, tmp_path, capsys)
    leg = _leg_lines(out)
    assert len(leg) == 1, f"索引实数腿应当只有一行，实得 {leg}"
    assert leg[0].startswith("[!!]"), f"短装必须降级，实得 {leg}"
    assert "索引ntotal(31)" in leg[0] and "应嵌(40)" in leg[0] and "库内已嵌(40)" in leg[0]
    assert "差(应嵌-索引)=+9" in leg[0]
    assert "已投完收工" not in out and "未收工" in out


def test_absent_index_file_is_undecidable_not_ok(monkeypatch, tmp_path, capsys):
    """注毒②：盘上没有 .index（也没盖戳）⇒ 只能 UNDECIDABLE，不许出现 ok。"""
    _make_store(
        tmp_path,
        embedded_rows=40,
        summary=SUMMARY_COMPLETE,
        ann_expected=40,
        ann_ntotal=_NO_INDEX,
    )
    out = _run(monkeypatch, tmp_path, capsys)
    leg = _leg_lines(out)
    assert len(leg) == 1, f"索引实数腿应当只有一行，实得 {leg}"
    assert "UNDECIDABLE:" in leg[0], f"取不到必须明写 UNDECIDABLE，实得 {leg}"
    assert "index_absent" in leg[0], f"原因要点名是哪一形，实得 {leg}"
    assert "[ok]" not in leg[0]
    assert "已投完收工" not in out and "未收工" in out


def test_unparseable_header_is_undecidable_not_ok(monkeypatch, tmp_path, capsys):
    """头部读不出（fourcc 不在册／只剩半截头）⇒ UNDECIDABLE，不许猜偏移洗成 ok。"""
    _make_store(
        tmp_path, embedded_rows=40, summary=SUMMARY_COMPLETE, ann_expected=40, ann_ntotal=40
    )
    index = tmp_path / "data" / "kb_wiki_faiss.index"
    _write_index_header(index, 40, fourcc=b"IVFx")  # 不在册的类标：偏移无从认定
    out = _run(monkeypatch, tmp_path, capsys)
    leg = _leg_lines(out)
    assert len(leg) == 1 and "UNDECIDABLE:" in leg[0] and "index_fourcc_unlisted" in leg[0], leg
    assert "[ok]" not in leg[0] and "已投完收工" not in out
    index.write_bytes(b"IHN")  # 半截头（不足 16 B）＝同一形
    out = _run(monkeypatch, tmp_path, capsys)
    leg = _leg_lines(out)
    assert len(leg) == 1 and "UNDECIDABLE:" in leg[0] and "index_header_short" in leg[0], leg
    assert "[ok]" not in leg[0]


def test_attestation_is_only_a_fallback_when_the_file_is_on_disk(monkeypatch, tmp_path, capsys):
    """第②级退路的边界：文件在盘但头部读不出 ⇒ 用代际证明戳并**点名来源**；
    文件不在盘 ⇒ 有戳也不许拿来冒充索引实数（ann_pair 在册的"证明自洽而磁盘没东西"假绿形）。"""
    pytest.importorskip("pre_restart_check")  # 退路那一级借的就是这把尺的原语
    attestation = {"ntotal": 40, "count": 40, "signature": "sig", "embed_generation": 1}
    _make_store(
        tmp_path,
        embedded_rows=40,
        summary=SUMMARY_COMPLETE,
        ann_expected=40,
        ann_ntotal=40,
        attestation=attestation,
    )
    _write_index_header(tmp_path / "data" / "kb_wiki_faiss.index", 40, fourcc=b"IVFx")
    out = _run(monkeypatch, tmp_path, capsys)
    leg = _leg_lines(out)
    assert len(leg) == 1 and "源=代际证明戳" in leg[0], f"退路要用戳并写明来源，实得 {leg}"
    assert "UNDECIDABLE" not in leg[0]

    (tmp_path / "data" / "kb_wiki_faiss.index").unlink()
    out = _run(monkeypatch, tmp_path, capsys)
    leg = _leg_lines(out)
    assert len(leg) == 1 and "UNDECIDABLE:" in leg[0], f"文件缺席时拿戳顶数＝假绿，实得 {leg}"
    assert "代际证明戳" not in leg[0]


def test_zero_ntotal_is_a_measured_value_not_undecidable(monkeypatch, tmp_path, capsys):
    """真·空索引（头里 ntotal=0）是**测得的 0**：不许与「取不到」塌成同一态。"""
    ntotal, reason = kp._read_index_ntotal(_write_index_header(tmp_path / "empty.index", 0))
    assert (ntotal, reason) == (0, "")
    _make_store(
        tmp_path, embedded_rows=40, summary=SUMMARY_COMPLETE, ann_expected=40, ann_ntotal=0
    )
    out = _run(monkeypatch, tmp_path, capsys)
    leg = _leg_lines(out)
    assert len(leg) == 1 and "索引ntotal(0)" in leg[0] and "UNDECIDABLE" not in leg[0], leg
    assert "差(应嵌-索引)=+40" in leg[0]


def test_header_ntotal_matches_real_faiss_serialization(tmp_path):
    """接地锁：头部偏移的读数必须等于真 faiss 打开同一枚文件后的 ``index.ntotal``。

    桩件只能证明「本尺与桩件自洽」，证明不了它量的是真格式——所以这里用 faiss 真写
    （现役 ``IndexHNSWSQ`` 与被取代的 ``IndexHNSWFlat`` 各一枚），两把尺读同一个数才算数。
    faiss 缺席（开发树没装）时按没有证据走 skip，不假绿也不假红。
    """
    faiss = pytest.importorskip("faiss")
    numpy = pytest.importorskip("numpy")

    rng = numpy.random.default_rng(20261008)

    def _build(path: Path, count: int, *, use_sq: bool) -> int:
        if use_sq:
            index = faiss.IndexHNSWSQ(
                16, faiss.ScalarQuantizer.QT_8bit, 8, faiss.METRIC_INNER_PRODUCT
            )
            index.train(numpy.ascontiguousarray(rng.random((48, 16), dtype=numpy.float32)))
        else:
            index = faiss.IndexHNSWFlat(16, 8, faiss.METRIC_INNER_PRODUCT)
        index.add(numpy.ascontiguousarray(rng.random((count, 16), dtype=numpy.float32)))
        faiss.write_index(index, str(path))
        return int(index.ntotal)

    for use_sq, count in ((True, 13), (False, 41), (True, 0)):
        path = tmp_path / f"real_{'sq' if use_sq else 'flat'}_{count}.index"
        written = _build(path, count, use_sq=use_sq)
        read, reason = kp._read_index_ntotal(path)
        assert reason == "", reason
        assert read == written == count, f"头部腿 {read} ≠ faiss {written}"


def test_leg_never_loads_the_whole_index() -> None:
    """结构锁：本尺不调 faiss、不调 read_index，只读 `ANN_HEADER_BYTES` 那一截。

    线上 ``.index`` 是 GB 量级、bot 常驻数 GiB——整本载入一次就把她压死（台账在册的
    内存前科）。锁读 AST 不读散文：docstring 里"绝不整本载入"那句必然提到 faiss。
    """
    source = (REPO_ROOT / "scripts" / "knowledge_progress.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: list[str] = []
    called: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(str(node.module))
        elif isinstance(node, ast.Attribute):
            called.append(node.attr)
    assert not [name for name in imported if "faiss" in name], imported
    assert "read_index" not in called, "索引实数腿不许走整本载入的取数口"
    assert "read(ANN_HEADER_BYTES)" in source, "读盘面必须钉死在头部字节数"


# ---------------------------------------------------------------------------
# 名册对榫腿（第四条失明的补牙）：恒等式 `回读计数 == 名册声称计数`，差值非零当场点名
#
# 判据一律**派生**：应有值从夹具本身现算（``_read_docs_count`` 走 SQL、``_declared_of``
# 读 sidecar），测试里不出现任何写死的篇数；每条腿都带**反空转前置**（两侧读数都 > 0
# 且差值确实由夹具决定），否则"相等"与"不等"都能被空夹具蒙过去。
# ---------------------------------------------------------------------------


def test_roster_leg_settles_only_when_readback_equals_declared(monkeypatch, tmp_path, capsys):
    """两本账逐字相等 ⇒ 这一行才是收工证据的一部分（并且必须真的在盘上报出来）。"""
    _make_store(tmp_path, embedded_rows=40, summary=SUMMARY_COMPLETE, ann_expected=40)
    readback, declared = _read_docs_count(tmp_path), _declared_of(tmp_path)
    assert readback > 0 and declared > 0 and readback == declared, "夹具空转：两侧读数没构成判据"
    out = _run(monkeypatch, tmp_path, capsys)
    leg = _roster_lines(out)
    assert len(leg) == 1, leg
    assert f"（{kp.ROSTER_SOURCE_READBACK}={readback}）" in leg[0], leg
    assert f"（{kp.ROSTER_SOURCE_MANIFEST}={declared}）" in leg[0], leg
    assert "差(名册-实读)=+0" in leg[0], leg
    assert "[!!]" not in out and "这一轮已投完收工" in out, out


def test_roster_shortfall_names_both_counts_and_blocks_settlement(monkeypatch, tmp_path, capsys):
    """货到了没进索引（名册 > 实读）⇒ 逐字点名两个计数与带符号差，收工话一律不许出现。"""
    _make_store(
        tmp_path,
        embedded_rows=40,
        summary=SUMMARY_COMPLETE,
        ann_expected=40,
        docs_rows=7,
        declared_documents=10,
    )
    readback, declared = _read_docs_count(tmp_path), _declared_of(tmp_path)
    gap = declared - readback
    assert gap > 0, "夹具空转：这一形造不出'到货未投'的差"
    out = _run(monkeypatch, tmp_path, capsys)
    leg = _roster_lines(out)
    assert len(leg) == 1, leg
    assert f"={readback}）" in leg[0] and f"={declared}）" in leg[0], leg
    assert f"差(名册-实读)={gap:+d}" in leg[0], leg
    assert "集合那一层未做" in leg[0] and "只判到计数那一层" in leg[0], leg
    assert "这一轮已投完收工" not in out and "未收工" in out, out
    assert "↳ 名册对榫腿" in out, out


def test_roster_surplus_blocks_too_because_the_identity_has_no_tolerance(
    monkeypatch, tmp_path, capsys
):
    """反向差（台账比名册多）同样不成立：恒等式零容差，不许"多出来就不管"。"""
    _make_store(
        tmp_path,
        embedded_rows=40,
        summary=SUMMARY_COMPLETE,
        ann_expected=40,
        docs_rows=9,
        declared_documents=5,
    )
    readback, declared = _read_docs_count(tmp_path), _declared_of(tmp_path)
    gap = declared - readback
    assert gap < 0, "夹具空转：这一形造不出反向差"
    out = _run(monkeypatch, tmp_path, capsys)
    leg = _roster_lines(out)
    assert f"差(名册-实读)={gap:+d}" in leg[0], leg
    assert "这一轮已投完收工" not in out and "未收工" in out, out


def test_roster_leg_reads_the_sql_count_never_the_summary_stamp(monkeypatch, tmp_path, capsys):
    """伪装形态锁：摘要戳 ``documents_after`` 与名册声称数**齐平**、台账实读却少一截——
    拿戳代答的写法会当场自证通过并打"已投完收工"，只有 SQL 实读才报得出差。"""
    declared = 11
    _make_store(
        tmp_path,
        embedded_rows=40,
        summary=dict(SUMMARY_COMPLETE, documents_after=declared),
        ann_expected=40,
        docs_rows=4,
        declared_documents=declared,
    )
    readback = _read_docs_count(tmp_path)
    assert readback < declared and readback > 0, "夹具空转：戳与实读没拉开距离"
    out = _run(monkeypatch, tmp_path, capsys)
    leg = _roster_lines(out)
    assert f"（{kp.ROSTER_SOURCE_READBACK}={readback}）" in leg[0], leg
    assert f"={readback}）" in leg[0] and f"={declared}）" in leg[0], leg
    assert "documents_after=11" in out, out  # 戳照样上屏，但它不是判据
    assert "这一轮已投完收工" not in out, out


def test_absent_roster_is_undecidable_and_never_folded_into_ok(monkeypatch, tmp_path, capsys):
    """名册取不到 ⇒ 明写 UNDECIDABLE＋本行不构成收工证据；不许折成 ok、也不许折成 0。"""
    _make_store(
        tmp_path, embedded_rows=40, summary=SUMMARY_COMPLETE, ann_expected=40, roster_sidecar=False
    )
    readback = _read_docs_count(tmp_path)
    assert readback > 0, "夹具空转：回读侧都没数"
    out = _run(monkeypatch, tmp_path, capsys)
    leg = _roster_lines(out)
    assert len(leg) == 1, leg
    assert f"{kp.UNDECIDABLE_PREFIX}manifest_absent" in leg[0], leg
    assert f"（{kp.ROSTER_SOURCE_READBACK}={readback}）" in leg[0], leg
    assert "不构成收工证据" in leg[0], leg
    assert "这一轮已投完收工" not in out and "未收工" in out, out


def test_roster_set_layer_names_the_set_when_the_ruler_answers(monkeypatch, tmp_path, capsys):
    """装载口与真身都在位时再 dig 一层：缺的是哪几篇（判据留在真身 ``reconcile_with_manifest``）。"""
    from plugins.bot_unified_runtime.domains.location.knowledge import (
        kb_wiki as real_kb_wiki,
    )

    declared = 10
    _make_store(
        tmp_path,
        embedded_rows=40,
        summary=SUMMARY_COMPLETE,
        ann_expected=40,
        docs_rows=7,
        declared_documents=declared,
    )
    readback = _read_docs_count(tmp_path)
    monkeypatch.setattr(kp, "_kb_wiki_module", lambda: (real_kb_wiki, ""))
    out = _run(
        monkeypatch,
        tmp_path,
        capsys,
        corpus_config=(types.SimpleNamespace(bot_kb_wiki_topics=""), ""),
    )
    leg = _roster_lines(out)
    assert "集合对榫＝真身 reconcile_with_manifest" in leg[0], leg
    assert f"待补 {declared - readback}" in leg[0], leg
    assert "待删 0" in leg[0] and "挂起 0" in leg[0], leg
    assert "集合那一层未做" not in leg[0], leg


def test_readback_count_leg_is_wired_to_the_sql_count_not_the_stamp() -> None:
    """AST 结构锁：``_roster_leg_line`` 的第一枚入参必须是那条 ``SELECT COUNT(*)`` 的绑定名，
    摘要戳（``documents_after``）一律不许进这条腿的入参——散文说"只准实读"没有用。"""
    source = (REPO_ROOT / "scripts" / "knowledge_progress.py").read_text(encoding="utf-8")
    fn = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "_report_wiki_settled"
    )
    calls = [
        node
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_roster_leg_line"
    ]
    assert len(calls) == 1, "名册腿在收工判据里必须只挂一处（第二处＝第二本进度台账）"
    rendered_call = ast.unparse(calls[0])
    first = calls[0].args[0]
    assert isinstance(first, ast.Name) and first.id == "docs", rendered_call
    assert "documents_after" not in rendered_call, rendered_call
    binding = next(
        node
        for node in ast.walk(fn)
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "docs" for t in node.targets)
    )
    assert "SELECT COUNT(*) FROM knowledge_docs" in ast.unparse(binding.value), ast.unparse(binding)


def test_roster_layer_never_touches_the_write_side() -> None:
    """整条名册腿只准读：库里只 ``mode=ro``（禁 ``immutable=1``——WAL 下它造得出假缺席），
    台账适配器只 SELECT，判据真身 ``reconcile_with_manifest`` 由本仓的只读视图喂数。"""
    source = (REPO_ROOT / "scripts" / "knowledge_progress.py").read_text(encoding="utf-8")
    assert "immutable" not in source, "SQLite 只读口只认 mode=ro，immutable 在 WAL 下会假缺席"
    assert "mode=ro" in source, "开库必须走只读 URI"
    leg_src = source.split("class _ReadOnlyLedger", 1)[1].split("def _roster_set_layer", 1)[0]
    assert not any(
        word in leg_src.upper() for word in ("INSERT ", "UPDATE ", "DELETE ", "COMMIT", "EXECUTEMANY")
    ), f"只读台账适配器里出现了写语句：{leg_src}"
