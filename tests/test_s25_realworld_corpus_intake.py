"""S25 席：现实世界语料「零改码入库」预演锁（合成样本，全程离线、仓外临时库）。

判据要回答的唯一问题：**语料侧真灌进现实 topic 之后，bot 侧要不要改码**——
所以这里只走 ``kb_wiki`` 的真身入口（``sync_kb_wiki`` / ``parse_topics`` /
``iter_corpus_topic_names`` / ``MergedKnowledgeRetriever``），不 mock 任何一段链路。

红线：
- 🔴 本文件里的每一条"语料"都是**合成试纸**（正文一律带 ``【合成样本】``），
  不是事实、不是语料，只用于证明通路；
- 🔴 零生产写：库文件与语料目录一律落在 ``tmp_path``（``--basetemp`` 在仓库外），
  绝不指向 ``ChatBot_Runtime/``；
- 🔴 零改码断言：新 topic 的名字**不以任何形式出现在源码里**也能入库——
  所以断言只用运行读数，不看常量表。
"""

from __future__ import annotations

import hashlib
import json
import re
import zlib
from pathlib import Path
from types import SimpleNamespace

from plugins.bot_unified_runtime.domains.chat_reply.character.vector_knowledge import (
    SqliteVectorKnowledgeStore,
)
from plugins.bot_unified_runtime.domains.core.search import search_service
from plugins.bot_unified_runtime.domains.location.knowledge import kb_wiki

# ---------------------------------------------------------------- 合成语料

REAL_TOPICS = ("漫展", "科技产品", "公司")
ACG_TOPIC = "梗知识"

_syn = "【合成样本】"


def _syn_docs() -> list[dict]:
    """八条合成文档：4 个 topic（3 枚现实 + 1 枚二游对照）。

    事实句刻意写成「可判定但显然假」的形状（样本市 / 第 N 届 / 样机 X9），
    这样验收时一眼能分清「通路跑通了」与「内容是真的」。
    """
    rows = [
        (
            f"{ACG_TOPIC}/moegirl/SYN-ACG-01",
            "合成梗·旧语料",
            "moegirl",
            (f"## 简介\n{_syn}这是一条二游 topic 的对照样本，用于验证现实 topic 入库后\n"
            "老语料是否仍占坑。样本编号 SYN-ACG-01。\n## 台词\n{_syn}对照台词。"),
        ),
        (
            f"{ACG_TOPIC}/moegirl/SYN-ACG-02",
            "合成梗·旧语料乙",
            "moegirl",
            f"## 简介\n{_syn}第二条二游对照样本。样本编号 SYN-ACG-02。",
        ),
        (
            "漫展/baidu_baike/SYN-CON-01",
            "样本漫展",
            "baidu_baike",
            (f"## 基本信息\n{_syn}样本漫展的举办城市写作**样本市**，届数写作**第三届**，"
            "年份写作样本年份 20XX。本条是通路试纸，不是任何真实展会。\n"
            f"## 交通\n{_syn}样本市地铁 1 号线样本站。"),
        ),
        (
            "漫展/wikipedia_zh/SYN-CON-02",
            "样本漫展乙",
            "wikipedia_zh",
            f"## 基本信息\n{_syn}样本漫展乙在第 7 届移师样本港，样本编号 SYN-CON-02。",
        ),
        (
            "漫展/baidu_baike/SYN-CON-03",
            "样本同人展",
            "baidu_baike",
            f"## 概况\n{_syn}样本同人展规模写作样本人数 3,000 人次。",
        ),
        (
            "科技产品/wikipedia_zh/SYN-TEC-01",
            "样机 X9",
            "wikipedia_zh",
            (f"## 规格\n{_syn}样机 X9 的屏幕写作 6.7 英寸，发布年份写作样本年份。"
            "本条是通路试纸，不是任何真实产品。\n## 争议\n{_syn}样本争议一句话。"),
        ),
        (
            "科技产品/baidu_baike/SYN-TEC-02",
            "样机 X9 Pro",
            "baidu_baike",
            f"## 规格\n{_syn}样机 X9 Pro 电池写作 5,000 毫安时。样本编号 SYN-TEC-02。",
        ),
        (
            "公司/wikipedia_zh/SYN-CO-01",
            "样本科技",
            "wikipedia_zh",
            (f"## 简介\n{_syn}样本科技注册地写作样本市，成立年份写作样本年份。"
            "本条是通路试纸，不是任何真实公司。\n## 业务\n{_syn}样本业务描述。"),
        ),
        (
            "公司/baidu_baike/SYN-CO-02",
            "样本传媒",
            "baidu_baike",
            f"## 简介\n{_syn}样本传媒主营写作样本业务。样本编号 SYN-CO-02。",
        ),
    ]
    docs = []
    for doc_id, title, source, text in rows:
        docs.append(
            {
                "id": doc_id,
                "hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "topic": doc_id.split("/", 1)[0],
                "source": source,
                "title": title,
                "text": text,
                "updated_at": "2026-10-01T00:00:00Z",
                "crawled_at": "2026-10-03T00:00:00Z",
            }
        )
    return docs


def write_corpus(kb_dir: Path, docs: list[dict], *, updates: list[dict] | None = None) -> dict:
    """按 kb_wiki 注释的三件套落盘：manifest.json + documents.jsonl + updates.jsonl。"""
    kb_dir.mkdir(parents=True, exist_ok=True)
    entries = {str(d["id"]): str(d["hash"]) for d in docs}
    topic_stats: dict[str, int] = {}
    for d in docs:
        topic_stats[d["topic"]] = topic_stats.get(d["topic"], 0) + 1
    manifest = {
        "generated_at": "2026-10-03T00:00:00Z",
        "documents": len(docs),
        "topics": topic_stats,
        "entries": entries,
        "removed": [],
    }
    (kb_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    (kb_dir / "documents.jsonl").write_text(
        "".join(json.dumps(d, ensure_ascii=False) + "\n" for d in docs), encoding="utf-8"
    )
    (kb_dir / "updates.jsonl").write_text(
        "".join(json.dumps(u, ensure_ascii=False) + "\n" for u in (updates or [])),
        encoding="utf-8",
    )
    return manifest


def _config(kb_root: Path, topics: str = "", *, top_k: int = 4) -> SimpleNamespace:
    return SimpleNamespace(
        bot_kb_wiki_root=str(kb_root),
        bot_kb_wiki_topics=topics,
        bot_kb_wiki_chunk_chars=800,
        bot_kb_wiki_top_k=top_k,
        bot_kb_wiki_db_path="",
    )


def _store(tmp_path: Path, name: str, top_k: int) -> SqliteVectorKnowledgeStore:
    return SqliteVectorKnowledgeStore(
        db_path=tmp_path / f"{name}.sqlite3",
        embed_provider=_BOW(),
        chunk_chars=800,
        top_k=top_k,
        signature="s25|bow-fake-embedder",
        auto_reset=True,
    )


class _BOW:
    """确定性词袋假嵌入（character-bigram + crc32 分桶，512 维、单位模长）。

    刻意不用 sha1 逐字节派生（test_kb_wiki_sync 那枚）：那版向量与文本内容
    无相关，「改前/改后命中来源分布」会退化成噪声，量不出配额效应。
    """

    DIM = 512

    @staticmethod
    def _tokens(text: str) -> list[str]:
        low = str(text or "").lower()
        ascii_words = re.findall(r"[a-z0-9]+", low)
        cjk = re.sub(r"[^一-鿿]", "", low)
        bigrams = [cjk[i : i + 2] for i in range(max(0, len(cjk) - 1))]
        return ascii_words + bigrams

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self.DIM
            for tok in self._tokens(text):
                vec[zlib.crc32(tok.encode("utf-8")) % self.DIM] += 1.0
            norm = sum(v * v for v in vec) ** 0.5
            out.append([v / norm for v in vec] if norm else vec)
        return out


# ---------------------------------------------------------------- ① 入库：零改码


def test_realworld_topics_ingest_with_zero_code_change(tmp_path):
    docs = _syn_docs()
    root = tmp_path / "fake_wiki_root"
    write_corpus(root / "crawl_output" / "knowledge_base", docs)
    store = _store(tmp_path, "kb_after", 4)

    result = kb_wiki.sync_kb_wiki(store, _config(root, ""), full=True)
    assert result["added"] == len(docs), result
    assert result["documents_total"] == len(docs)

    store.embed_pending(None)
    topic_counts = _topic_counts(store)
    # 读数本身即交付物：现实 topic 一条命令都没改就进了台账与块表。
    assert topic_counts[ACG_TOPIC] == 2
    assert topic_counts["漫展"] == 3
    assert topic_counts["科技产品"] == 2
    assert topic_counts["公司"] == 2
    assert sum(topic_counts.values()) == 9
    print(f"[S25][full-sync] docs={len(docs)} topic_counts={topic_counts}")
    print(f"[S25][chunks] total={store.stats()['total']} embedded={store.stats()['embedded']}")

    # 库侧「实际收录了哪些域」——现实 topic 立刻可被诊断路径枚举到。
    surfaced = list(
        kb_wiki.iter_corpus_topic_names(root / "crawl_output" / "knowledge_base")
    )
    assert set(surfaced) == {*REAL_TOPICS, ACG_TOPIC}, surfaced

    # 增量腿（日增量入口的真身协议）：新一轮 updates.jsonl 带一条现实新文档。
    new_doc = {
        "id": "漫展/baidu_baike/SYN-CON-09",
        "hash": "x",
        "topic": "漫展",
        "source": "baidu_baike",
        "title": "样本漫展·增补",
        "text": f"## 基本信息\n{_syn}增补样本，验证增量腿吃新 topic。届数写作第七届。",
    }
    new_doc["hash"] = hashlib.sha256(new_doc["text"].encode("utf-8")).hexdigest()
    kb_dir = root / "crawl_output" / "knowledge_base"
    write_corpus(
        kb_dir,
        docs + [new_doc],
        updates=[{**new_doc, "op": "upsert"}, {"id": f"{ACG_TOPIC}/moegirl/SYN-ACG-02", "op": "delete"}],
    )
    inc = kb_wiki.sync_kb_wiki(store, _config(root, ""), full=False)
    assert inc["added"] == 1 and inc["removed"] == 1, inc
    after = _topic_counts(store)
    assert after["漫展"] == 4 and after[ACG_TOPIC] == 1, after
    print(f"[S25][incremental] {inc['added']}/{inc['removed']} topic_counts={after}")


def _topic_counts(store: SqliteVectorKnowledgeStore) -> dict[str, int]:
    """台账按语料域计数。

    topic 一律从 ``doc_id`` 首段派生（``kb_wiki._id_topic`` 同一口径），不在
    这里赌 ``knowledge_docs`` 有没有 ``topic`` 列——列名是 store 侧的实现细节，
    而「id 首段＝语料域」才是本席要验的契约。
    """
    conn = store._connect()
    cols = [str(r[1]) for r in conn.execute("PRAGMA table_info(knowledge_docs)")]
    id_col = next((c for c in ("id", "doc_id", "source_id") if c in cols), None)
    assert id_col, cols
    out: dict[str, int] = {}
    for row in conn.execute(f"SELECT {id_col} FROM knowledge_docs").fetchall():
        topic = str(row[0] or "").split("/", 1)[0]
        out[topic] = out.get(topic, 0) + 1
    return out


# ---------------------------------------------------------------- ② topic 过滤


def test_topic_filter_admits_only_realworld(tmp_path):
    docs = _syn_docs()
    root = tmp_path / "fake_wiki_root"
    write_corpus(root / "crawl_output" / "knowledge_base", docs)

    # 空 = 全放（现算 parse_topics 的缺省语义）
    assert kb_wiki.parse_topics(_config(root, "")) == []
    assert kb_wiki.parse_topics(_config(root, " 漫展 , 科技产品 ,, 公司 ")) == [
        "漫展",
        "科技产品",
        "公司",
    ]

    allow = "漫展,科技产品,公司"
    store = _store(tmp_path, "kb_filtered", 4)
    kb_wiki.sync_kb_wiki(store, _config(root, allow), full=True)

    topic_counts = _topic_counts(store)
    admitted = sum(topic_counts.values())
    blocked = len(docs) - admitted
    assert ACG_TOPIC not in topic_counts, topic_counts
    assert admitted == 7 and blocked == 2, (topic_counts, admitted, blocked)
    print(f"[S25][filter] allow={allow} admitted={admitted} blocked={blocked} groups={topic_counts}")

    # 流侧同口径：iter_kb_documents 过滤掉的就是二游那两条
    streamed = [
        r["id"]
        for r in kb_wiki.iter_kb_documents(root / "crawl_output" / "knowledge_base", ["漫展"])
    ]
    assert len(streamed) == 3

    # 子集白名单的对账护栏：域外台账行必须挂起而不是被删（现实入库不能反过来清二游）
    filt = kb_wiki.reconcile_with_manifest(
        store,
        json.loads((root / "crawl_output" / "knowledge_base" / "manifest.json").read_text("utf-8")),
        kb_wiki.parse_topics(_config(root, allow)),
    )
    stats, _missing, removable = filt
    assert stats["reconcile_status"] == "ok" and not removable, (stats, removable)
    print(f"[S25][reconcile-subset] {stats} removable={len(removable)}")


# ---------------------------------------------------------------- ③ 配额对照


class _Leg:
    available = True

    def __init__(self, store: SqliteVectorKnowledgeStore) -> None:
        self._store = store

    def retrieve(self, query: str) -> list:
        return self._store.retrieve(str(query), files=None, embed_backlog=False)


def _build_wiki_store(tmp_path, name: str, topics: str):
    docs = _syn_docs()
    root = tmp_path / f"root_{name}"
    kb_dir = root / "crawl_output" / "knowledge_base"
    write_corpus(kb_dir, docs)
    store = _store(tmp_path, name, 4)
    kb_wiki.sync_kb_wiki(store, _config(root, topics), full=True)
    store.embed_pending(None)
    return root, store


def test_merged_topk_source_distribution_before_after(tmp_path):
    """同一条现实提问，改前（wiki 只有二游）↔ 改后（wiki 有现实 topic）的来源分布。"""
    persona_docs = [
        {
            "id": f"{ACG_TOPIC}/persona/SYN-P{i:02d}",
            "hash": "h",
            "topic": ACG_TOPIC,
            "source": "persona",
            "title": f"合成二游人格块{i}",
            "text": f"## 设定\n{_syn}二游世界观描述第{i}条，含角色 鸣潮 守岸人 千咲 散华。",
        }
        for i in range(8)
    ]
    for d in persona_docs:
        d["hash"] = hashlib.sha256(d["text"].encode("utf-8")).hexdigest()
    persona = _store(tmp_path, "persona", 8)
    persona.sync_documents(
        [
            {
                "id": d["id"],
                "hash": d["hash"],
                "topic": d["topic"],
                "source": d["source"],
                "title": d["title"],
                "chunks": kb_wiki.split_doc_chunks(d["text"], d["title"], hard_limit=800),
            }
            for d in persona_docs
        ]
    )
    persona.embed_pending(None)

    _r_before, before = _build_wiki_store(tmp_path, "kb_before", ACG_TOPIC)
    _r_after, after = _build_wiki_store(tmp_path, "kb_after_q", "")

    query = "样本漫展 在 哪个城市 举办 第几届"
    runs = {}
    for label, wiki in (("改前(仅二游 wiki)", before), ("改后(含现实 topic)", after)):
        merged = kb_wiki.MergedKnowledgeRetriever(
            [_Leg(persona), _Leg(wiki)],
            libraries=[search_service.KB_SOURCE_PERSONA, search_service.KB_SOURCE_WIKI],
        )
        hits = merged.retrieve(query)
        dist: dict[str, int] = {}
        wiki_topics: dict[str, int] = {}
        for h in hits:
            lib = str(getattr(h, "source_library", "") or "?")
            dist[lib] = dist.get(lib, 0) + 1
            if lib == search_service.KB_SOURCE_WIKI:
                topic = str(getattr(h, "source_id", "")).split("/", 1)[0]
                wiki_topics[topic] = wiki_topics.get(topic, 0) + 1
        runs[label] = (len(hits), dist, wiki_topics)
        print(f"[S25][quota] {label} hits={len(hits)} dist={dist} wiki_topics={wiki_topics}")

    before_n, before_dist, before_topics = runs["改前(仅二游 wiki)"]
    after_n, after_dist, after_topics = runs["改后(含现实 topic)"]
    persona_leg = search_service.KB_SOURCE_PERSONA
    wiki_leg = search_service.KB_SOURCE_WIKI
    # wiki 腿槽位由 BOT_KB_WIKI_TOP_K 定死 4：现实 topic 挤掉的是 wiki 腿内部的
    # 二游块（换血），不是把 wiki 腿撑大、也不是去抢人格腿的 8 块（扩容）。
    assert after_dist.get(wiki_leg, 0) == 4, after_dist
    assert before_dist.get(wiki_leg, 0) >= 1, before_dist
    assert set(before_topics) == {ACG_TOPIC}, before_topics
    assert ACG_TOPIC not in after_topics, after_topics
    assert set(after_topics) <= set(REAL_TOPICS), after_topics
    assert before_dist.get(persona_leg, 0) == after_dist.get(persona_leg, 0), (
        before_dist,
        after_dist,
    )
    assert before_n < after_n or after_n == before_n, (before_n, after_n)
