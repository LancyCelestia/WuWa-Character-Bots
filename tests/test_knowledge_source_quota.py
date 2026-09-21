"""人格库源族配额（per-source quota）回归锁 — 2026-09-20。

背景（生产实测）：knowledge_chunks 35479 块中人格本体仅 373（1.05%），
战双/鸣潮库街区百科 30802（86.8%）；th-01…th-12 为 12 个独立 source_id。
补嵌完成后向量通道全量参战，每轮内部 top_k（生产 5）槽位可能被百科源洗掉。
本文件锁死：①族粒度选择算法（纯函数单测，含 th-* 并族与溢出回填）；
②检索链集成（配额开/关两态、词条置顶次序、search_scored 同链）；
③语料级前后对照（人格向查询人格块占位只增不减；纯百科单源查询逐 id 不变）。
全程离线：tmp_path 合成语料 + 确定性词袋假嵌入器，绝不触碰生产库。
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.contracts import KnowledgeChunk
from plugins.bot_unified_runtime.domains.chat_reply.character.vector_knowledge import (
    _PERSONA_FAMILY,
    SqliteVectorKnowledgeStore,
    _quota_family_cap,
    _quota_persona_reserved,
    _rrf_fuse,
    _select_within_source_quota,
    _source_family,
)
from plugins.bot_unified_runtime.domains.location.knowledge.kb_wiki import (
    MergedKnowledgeRetriever,
)

# --------------------------------------------------------------- 纯函数单测


def test_source_family_grouping_matches_production_ids() -> None:
    # 生产实测 17 源的归族行为。
    assert _source_family("th-01") == "on-this-day"
    assert _source_family("th-12") == "on-this-day"
    assert _source_family("守岸人_核心知识") == _PERSONA_FAMILY
    assert _source_family("守岸人_人格与表达规范") == _PERSONA_FAMILY
    assert _source_family("鸣潮库街区百科") == "鸣潮库街区百科"
    assert _source_family("ai-kb-operations-manual") == "ai-kb-operations-manual"
    # 非生产格式（th-1x / th-013）不并族，正则锁 \d{1,2} 全匹配。
    assert _source_family("th-1x") == "th-1x"
    assert _source_family("th-013") == "th-013"
    assert _source_family("") == ""


def test_quota_params_for_production_sizes() -> None:
    assert _quota_family_cap(5) == 3 and _quota_persona_reserved(5) == 2
    assert _quota_family_cap(8) == 4 and _quota_persona_reserved(8) == 2
    assert _quota_family_cap(4) == 2 and _quota_persona_reserved(4) == 2
    assert _quota_family_cap(1) == 1 and _quota_persona_reserved(1) == 1


def test_th_twelve_sources_cannot_fill_slots_when_grouped() -> None:
    """th-* 陷阱：12 个独立源不并族能占满槽；并族后受 cap、余槽让路。"""
    ranked = [f"t{i}" for i in range(12)] + ["a1", "a2", "a3"]
    family_of = {f"t{i}": "on-this-day" for i in range(12)}
    family_of.update({"a1": "wikiA", "a2": "wikiA", "a3": "wikiB"})
    picked = _select_within_source_quota(ranked, family_of, 5)
    # th 并族 cap=3 → t0..t2 入选、t3+ 让位给 wikiA 前两名（融合序取，a3 出 limit）。
    assert sum(1 for cid in picked if family_of[cid] == "on-this-day") == 3
    assert {"a1", "a2"} <= set(picked) and "a3" not in picked
    assert len(picked) == 5
    assert picked == sorted(picked, key=ranked.index)  # 输出保持融合序


def test_persona_reserved_slots_promoted_over_weakest() -> None:
    ranked = ["a1", "a2", "a3", "b1", "b2", "p1", "p2"]
    family_of = {
        "a1": "A", "a2": "A", "a3": "A", "b1": "B", "b2": "B",
        "p1": _PERSONA_FAMILY, "p2": _PERSONA_FAMILY,
    }
    picked = _select_within_source_quota(ranked, family_of, 5)
    # 无配额时 A3+B2 占满、persona 池内却被挤出；配额后保留位成立。
    assert {"p1", "p2"} <= set(picked)
    assert sum(1 for c in picked if family_of[c] == _PERSONA_FAMILY) == 2
    assert "b1" not in picked and "b2" not in picked
    assert picked == sorted(picked, key=ranked.index)


def test_single_family_query_overflow_keeps_all_slots() -> None:
    """纯百科单源查询：cap 内其他族不足时溢出回填，槽位零损失。"""
    ranked = [f"a{i}" for i in range(9)]
    family_of = {f"a{i}": "鸣潮库街区百科" for i in range(9)}
    assert _select_within_source_quota(ranked, family_of, 5) == ranked[:5]


def test_persona_uncapped_when_it_legitimately_dominates() -> None:
    ranked = ["p1", "p2", "p3", "p4", "p5", "a1"]
    family_of = {**{f"p{i}": _PERSONA_FAMILY for i in range(1, 6)}, "a1": "A"}
    assert _select_within_source_quota(ranked, family_of, 5) == ranked[:5]


def test_no_persona_candidates_reservation_automatically_unused() -> None:
    ranked = ["a1", "b1", "c1", "d1", "e1", "f1", "g1"]
    family_of = {c: c for c in ranked}
    picked = _select_within_source_quota(ranked, family_of, 5)
    assert len(picked) == 5
    assert all(family_of[c] != _PERSONA_FAMILY for c in picked)


def test_partial_pool_returns_min_limit_pool() -> None:
    ranked = ["a1", "b1"]
    family_of = {"a1": "A", "b1": "B"}
    assert _select_within_source_quota(ranked, family_of, 5) == ranked
    assert _select_within_source_quota(ranked, family_of, 0) == []


def test_limit_one_prefers_persona_in_pool() -> None:
    ranked = ["a1", "p1"]
    family_of = {"a1": "A", "p1": _PERSONA_FAMILY}
    assert _select_within_source_quota(ranked, family_of, 1) == ["p1"]


# ------------------------------------------------------------- 检索链集成

# 候选全集融合序（假通道直接返回的向量序）：wiki 前段占满、persona 沉底。
_ALL_IDS = [
    "a0", "a1", "a2", "b0", "b1",
    "t0", "t1", "t2", "t3", "p1", "p2",
]
_ROWS = (
    [(f"a{i}", "鸣潮库街区百科") for i in range(3)]
    + [(f"b{i}", "战双帕弥什库街区百科") for i in range(2)]
    + [(f"t{i}", f"th-0{i}") for i in range(4)]
    + [("p1", "守岸人_核心知识"), ("p2", "守岸人_人格与表达规范")]
)


class _ZeroEmbedder:
    def embed_texts(self, texts):
        return [[0.0, 0.0, 1.0] for _ in texts]


def _seed_rows(store: SqliteVectorKnowledgeStore, rows) -> None:
    with store._connect() as connection:
        connection.executemany(
            "INSERT OR REPLACE INTO knowledge_chunks "
            "(chunk_id, source_id, title, content, content_hash, vector_json) "
            "VALUES (?, ?, ?, ?, ?, NULL)",
            [
                (
                    cid,
                    sid,
                    sid,
                    f"内容 {cid} for {sid}",
                    hashlib.sha1(cid.encode("utf-8")).hexdigest(),
                )
                for cid, sid in rows
            ],
        )
        connection.commit()


def _stub_channels(store: SqliteVectorKnowledgeStore, entry_hits) -> None:
    def _vector_stub(_query_vector, scores_out=None):
        # 真实契约（本波扩展）：(query_vector, scores_out=None)，开配额时
        # 逐块余弦回填 scores_out——ANN/numpy/brute 三路径皆如此。
        if scores_out is not None:
            scores_out.update({chunk_id: 0.9 for chunk_id in _ALL_IDS})
        return list(_ALL_IDS), 0.9

    store._vector_candidates = _vector_stub  # type: ignore[method-assign]
    store._keyword_candidates = lambda _q: list(_ALL_IDS[:5])  # type: ignore[method-assign]
    store._entry_title_candidates = lambda _q: list(entry_hits)  # type: ignore[method-assign]


@pytest.fixture()
def seeded(tmp_path: Path):
    stores = {}
    for quota in (False, True):
        store = SqliteVectorKnowledgeStore(
            db_path=tmp_path / f"kb-{int(quota)}.sqlite3",
            embed_provider=_ZeroEmbedder(),
            top_k=5,
            signature="test|fake",
            auto_reset=False,
            source_quota_enabled=quota,
        )
        _seed_rows(store, _ROWS)
        _stub_channels(store, [])
        stores[quota] = store
    return stores[False], stores[True]


def test_disabled_quota_reproduces_legacy_rrf_exactly(seeded) -> None:
    off, _on = seeded
    legacy_ids = _rrf_fuse(list(_ALL_IDS), list(_ALL_IDS[:5]), 5)
    chunks = off.retrieve("任意查询")
    assert [c.chunk_id for c in chunks] == legacy_ids
    assert sum(1 for c in chunks if c.source_id.startswith("守岸人")) == 0


def test_enabled_quota_reserves_persona_slots(seeded) -> None:
    _off, on = seeded
    on_chunks = on.retrieve("任意查询")
    assert len(on_chunks) == 5
    assert sum(1 for c in on_chunks if c.source_id.startswith("守岸人")) == 2
    assert sum(1 for c in on_chunks if re.match(r"^th-\d", c.source_id)) <= 3
    # 融合序保持：a 族三连在前，persona 保留位在其后按各自 rank 排。
    ids = [c.chunk_id for c in on_chunks]
    assert ids == sorted(ids, key=_ALL_IDS.index)


def test_pinned_entries_keep_direct_hit_position(seeded) -> None:
    _off, on = seeded
    _stub_channels(on, [(3, True, "b0"), (2, False, "a0")])
    ids = [c.chunk_id for c in on.retrieve("战双词条 守岸人")]
    assert ids[0] == "b0"  # 精确词条置顶直通第一，不被配额挤掉
    assert len(ids) == 5
    assert sum(1 for cid in ids if cid.startswith("p")) >= 1


def test_search_scored_shares_quota_chain(seeded) -> None:
    off, on = seeded
    off_hits = off.search_scored("任意查询", sync_files=False)
    on_hits = on.search_scored("任意查询", sync_files=False)
    assert sum(1 for h in off_hits if h.chunk.source_id.startswith("守岸人")) == 0
    assert sum(1 for h in on_hits if h.chunk.source_id.startswith("守岸人")) == 2
    assert all(set(h.channels) == {"vector", "keyword", "entry"} for h in on_hits)


def test_family_lookup_unknown_rows_get_own_family(tmp_path: Path) -> None:
    store = SqliteVectorKnowledgeStore(
        db_path=tmp_path / "kb-lookup.sqlite3",
        embed_provider=_ZeroEmbedder(),
        top_k=5,
        source_quota_enabled=True,
    )
    _seed_rows(store, [("c1", "守岸人_核心知识"), ("c2", "th-07")])
    fam = store._family_of_chunks(["c1", "c2", "ghost"])
    assert fam["c1"] == _PERSONA_FAMILY and fam["c2"] == "on-this-day"
    assert fam["ghost"] == "unknown:ghost"


def test_kb_wiki_store_class_default_has_no_quota(tmp_path: Path) -> None:
    """范围锁：kb_wiki/smoke 等其余构造点缺省=关，配额只属人格 provider。"""
    store = SqliteVectorKnowledgeStore(
        db_path=tmp_path / "kb-default.sqlite3",
        embed_provider=_ZeroEmbedder(),
    )
    assert store.source_quota_enabled is False


# ------------------------------------------------- 语料级前后对照（12 查询）

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_CJK_RUN_RE = re.compile(r"[一-鿿]+")


class _TokenEmbedder:
    """确定性词袋假嵌入器（md5 稳定）：离线、零网络、零生产库。"""

    @staticmethod
    def _tokens(text: str) -> list[str]:
        toks = [m.group(0).lower() for m in _TOKEN_RE.finditer(str(text))]
        for run in _CJK_RUN_RE.findall(str(text)):
            toks.extend(run[i : i + 2] for i in range(max(0, len(run) - 1)))
        return toks

    def embed_texts(self, texts):
        out = []
        for text in texts:
            vector = {}
            for tok in self._tokens(text):
                index = int(hashlib.md5(tok.encode("utf-8")).hexdigest()[:8], 16)
                vector[index] = vector.get(index, 0.0) + 1.0
            norm = sum(v * v for v in vector.values()) ** 0.5 or 1.0
            dim = {}
            for index, value in vector.items():
                dim[index % 1024] = value / norm
            out.append([dim.get(i, 0.0) for i in range(1024)])
        return out


_CORPUS: dict[str, list[str]] = {
    # 问答体内嵌人格向查询原句（生产实况=库街区百科有守岸人剧情页与玩家讨论，
    # 30k 级近重复块在两条通道同时压过 373 块人格本体的同义改写文本）。
    "鸣潮库街区百科": [
        f"鸣潮角色图鉴第{i}条：玩家问答——鸣潮的剧情你怎么看；平时说话的方式"
        f"是什么样的；你是谁、你的身份是什么；你和漂泊者之间是什么关系；历史"
        f"上的今天你怎么看；今天心情怎么样；忌炎与今汐详见条目{i}，声骸随版本更新。"
        for i in range(14)
    ],
    "战双帕弥什库街区百科": [
        f"战双构造体档案第{i}条：万事与露西亚的战斗数值，观察该构造体强度，"
        f"库街区信号配置说明{i}，版本变更记录归档。"
        for i in range(40)
    ],
    "守岸人_核心知识": [
        "我的来历与身份：泰缇斯第二实例，守护乐土，非人造智能。",
        "如何看待世界：以守护者视角温和评述剧情，不吹不黑。",
        "你与漂泊者：重要的人会记得；称呼与边界，私聊语境为准。",
    ],
    "守岸人_人格与表达规范": [
        "分寸：像呼吸一样自然的表达，语气随对话节奏，忌客服腔。",
        "今天也要好好陪伴你：主动搭话需要好感门槛。",
    ],
    "ai-kb-operations-manual": [
        f"知识库运维第{i}条：同步、嵌入、ANN 构建的离线流程。" for i in range(8)
    ],
}
for _n in range(1, 13):
    _CORPUS[f"th-{_n:02d}"] = [
        f"历史上的今天 9月{_n}日 第{i}条：今天的鸣潮大事记与今天的历史事件。"
        for i in range(6)
    ]

_QUERIES: list[tuple[str, str]] = [
    ("人格向", "你怎么看鸣潮的剧情"),
    ("人格向", "你平时说话的方式是什么样的"),
    ("人格向", "你是谁？你的身份是什么"),
    ("人格向", "你和漂泊者之间是什么关系"),
    ("人格向", "历史上的今天你怎么看"),
    ("人格向", "今天心情怎么样"),
    ("百科向", "鸣潮 忌炎 图鉴"),
    ("百科向", "鸣潮剧情 今汐 条目"),
    ("百科向", "战双 万事 构造体 档案"),
    ("百科向", "战双帕弥什 信号 配置"),
    ("百科向", "知识库运维 同步 嵌入"),
    ("百科向", "历史上的今天 9月7日 大事记"),
]


def _corpus_files(tmp_path: Path) -> list[Path]:
    files = []
    for stem, entries in _CORPUS.items():
        path = tmp_path / f"{stem}.md"
        path.write_text("\n\n".join(entries), encoding="utf-8")
        files.append(path)
    return files


@pytest.fixture(scope="module")
def quota_report(tmp_path_factory) -> dict:
    tmp_path = tmp_path_factory.mktemp("quota-corpus")
    files = _corpus_files(tmp_path)
    stores = {}
    for quota in (False, True):
        store = SqliteVectorKnowledgeStore(
            db_path=tmp_path / f"corpus-{int(quota)}.sqlite3",
            embed_provider=_TokenEmbedder(),
            chunk_chars=240,
            top_k=5,
            signature="test|token-embed",
            auto_reset=False,
            source_quota_enabled=quota,
        )
        store.sync_chunks(files)
        done, pending = store._embed_all_pending()
        assert done == pending
        stores[quota] = store
    rows = []
    for kind, query in _QUERIES:
        result = {"kind": kind, "query": query}
        for quota, label in ((False, "before"), (True, "after")):
            chunks = stores[quota].retrieve(query, files=files)
            result[f"{label}_ids"] = [c.source_id for c in chunks]
            result[f"{label}_persona"] = sum(
                1 for c in chunks if c.source_id.startswith("守岸人")
            )
            result[f"{label}_th"] = sum(
                1 for c in chunks if re.match(r"^th-\d", c.source_id)
            )
        rows.append(result)
    return {"rows": rows}


def test_persona_queries_gain_and_encyclopedia_untouched(quota_report) -> None:
    for row in quota_report["rows"]:
        if row["kind"] == "人格向":
            # 结构保证：人格块占位只增不减（persona 族不受 cap，保留位只提升）。
            assert row["after_persona"] >= row["before_persona"], row
        else:
            assert len(row["after_ids"]) == len(row["before_ids"]), row
    gained = [
        r for r in quota_report["rows"]
        if r["kind"] == "人格向" and r["after_persona"] > r["before_persona"]
    ]
    assert len(gained) >= 3, [
        (r["query"], r["before_persona"], r["after_persona"])
        for r in quota_report["rows"]
    ]
    # 回归锁：纯百科查询前后完全一致（没把百科通道治残）。
    identical = [
        r for r in quota_report["rows"]
        if r["kind"] == "百科向" and r["before_ids"] == r["after_ids"]
    ]
    assert len(identical) >= 3, [
        (r["query"], r["before_ids"], r["after_ids"])
        for r in quota_report["rows"]
        if r["kind"] == "百科向"
    ]


def test_th_family_cap_holds_in_corpus(quota_report) -> None:
    # 各查询候选池均含 ≥2 个族，cap 不会触发溢出：th 并族后必 ≤3。
    for row in quota_report["rows"]:
        assert row["after_th"] <= _quota_family_cap(5), row


class _StreamRetriever:
    available = True

    def __init__(self, chunks):
        self._chunks = chunks

    def retrieve(self, _query_text):
        return list(self._chunks)


def test_merged_prompt_projection(quota_report) -> None:
    """端到端投影：真 MergedKnowledgeRetriever 轮转后前 8 槽里的人格本体数。"""
    wiki_stream = [
        KnowledgeChunk(chunk_id=f"w{i}", source_id="kb_wiki某页", title="页", content="x")
        for i in range(5)
    ]
    improved = 0
    for row in quota_report["rows"]:
        if row["kind"] != "人格向":
            continue
        for label in ("before", "after"):
            persona_stream = [
                KnowledgeChunk(
                    chunk_id=f"{label}-{i}", source_id=sid, title=sid, content="x"
                )
                for i, sid in enumerate(row[f"{label}_ids"])
            ]
            merged = MergedKnowledgeRetriever(
                [
                    _StreamRetriever(persona_stream),
                    _StreamRetriever(wiki_stream),
                ]
            ).retrieve("q")
            row[f"{label}_prompt"] = sum(
                1 for chunk in merged[:8] if chunk.source_id.startswith("守岸人")
            )
        assert row["after_prompt"] >= row["before_prompt"], row
        if row["after_prompt"] > row["before_prompt"]:
            improved += 1
    assert improved >= 1, quota_report["rows"]


def test_print_comparison_table(quota_report, capsys) -> None:
    # 供报告引用的表格输出（pytest -s 可见）。
    print("\nQUERY-KIND\tQUERY\tBEFORE-PERSONA\tAFTER-PERSONA\tBEFORE-PROMPT\tAFTER-PROMPT")
    for row in quota_report["rows"]:
        print(
            f"{row['kind']}\t{row['query']}\t{row['before_persona']}\t"
            f"{row['after_persona']}\t{row.get('before_prompt', '-')}\t{row.get('after_prompt', '-')}"
        )
