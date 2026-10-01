"""Crawl Wiki 知识库桥：同步 + 检索器 + 合并检索。

对接 Crawl Wiki 仓库（``bot_kb_wiki_root``，默认 D:\\Coding\\Crawl Wiki）导出的
知识库，协议见该仓库 ``docs/KB_HANDOFF.md``：

- 增量同步读 ``manifest.json`` 三张清单 + ``updates.jsonl`` 变更行，
  按 (doc_id, hash) 幂等（``SqliteVectorKnowledgeStore.sync_documents``）；
- 每轮增量再与 ``manifest.entries``（全量 id→hash 快照）**对账**：
  ``updates.jsonl`` 是每轮覆盖写的「本轮 diff」，爬虫一天两档导出（16:00 /
  23:00）而 Bot 只读 23:40 一档时，前档 diff 会被覆盖后永久丢失——对账把
  台账缺项（含 hash 漂移）从 ``documents.jsonl`` 补回、把台账多项删除，
  不再依赖 updates.jsonl 的完整性（台账 ``knowledge_docs`` 为准绳）；
- 初次灌库/定期对账（``full=True``）流式逐行读 ``documents.jsonl``（237MB，
  常驻内存 O(1)），中断重跑自动续传；
- 文档台账落 ``source_updated_at``（上游编辑时间）/``crawl_at``（本地抓取落盘
  时间）两列元数据（列名契约，源自语料行的 ``updated_at``/``crawled_at``）；
  语料侧只加时间字段、正文一字未改时走 ``refresh_kb_metadata`` 做**零嵌入成本**
  的全表回填（只 UPDATE 台账，chunk 字节与 hash 不动，一次 Ollama 都不调）；
  「要不要刷」这道闸由 ``probe_corpus_time_fields`` 的**有界窗口计数**判定
  （流式读前 300 行，≥1 行且 ≥10% 带字段才刷；判据依据 probed/with_time 与
  状态同行落库），不用首行一条样本给七万五千行语料背书；
- 分块按 Markdown 标题分节，每块携带「词条标题｜节标题」前缀做嵌入上下文；
- 嵌入复用 OpenAICompatibleEmbeddingProvider（本地 Ollama bge-m3 优先，
  远程付费链兜底）；向量库独立于人格知识库（``bot_kb_wiki_db_path``），
  两边的文件清单删除语义互不干扰；
- 聊天链路经 ``MergedKnowledgeRetriever`` 把人格知识块与 wiki 知识块
  轮询交错注入 prompt（人格知识优先）；
- 同步任务治理（R3 停摆批 2026-09-17）：进程级互斥（启动补同步/夜间同步
  撞车即 busy 跳过）、协作式可取消（``cancel_kb_sync_task``，批边界检查、
  断点落库续传）、零变更夜跳过 ANN 全量重建（实测省 8.5 分钟默认线程池占用）；
- 同步可观测性（2026-09-20 元数据批）：每轮 summary（成败/耗时/增删改嵌/
  对账/回填）落 ``knowledge_meta['kb_sync_last_summary']`` 供 WebUI 知识页读，
  失败与部分失败经 ``set_kb_sync_alert_sink`` 接入 runtime/alerts
  （缺省未注入时退回 WARNING 日志，行为与旧版一致）。

未做：检索不到时的自动实时爬降级（单页 3-10 秒 + 目标站反爬礼节，
需人工决策频率；此前预留的 ``realtime_lookup`` 工具因全仓零引用已移除）。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime
from itertools import chain, islice
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.domains.chat_reply.character.vector_knowledge import (
    OpenAICompatibleEmbeddingProvider,
    SqliteVectorKnowledgeStore,
    _UnavailableVectorKnowledgeProvider,
)

logger = logging.getLogger(__name__)

_KB_SUBDIR = Path("crawl_output") / "knowledge_base"
_SOURCE_LABELS = {
    "moegirl": "萌娘百科",
    "wikipedia_zh": "维基百科",
    "baidu_baike": "百度百科",
}

# 同步摘要落库键（knowledge_meta 单行 JSON，WebUI 知识页只读消费）。
SYNC_SUMMARY_META_KEY = "kb_sync_last_summary"
# 台账对账异常兜底：台账里出现、而本轮清单里没有的文档，只删「清单确实覆盖了
# 它所属语料域」的那些——爬虫按 topic 子集导出时清单本身不完整，据此放行删除
# 会把整域文档连块清掉（丢数据比丢元数据严重得多）。
_RECONCILE_REMOVE_SUSPENDED = "remove_suspended"

# 进程级共享 store：检索器与调度同步任务共用一个实例，
# 同步后的向量缓存/FTS/ANN 状态才能在同一进程内即时生效。
_SHARED_STORES: dict[str, SqliteVectorKnowledgeStore] = {}
_SHARED_STORES_LOCK = threading.Lock()


def kb_paths(config: object) -> tuple[Path, Path]:
    """返回 (Crawl Wiki 仓库根, knowledge_base 目录)。"""
    root = Path(
        str(getattr(config, "bot_kb_wiki_root", "") or "")
        or r"D:\Coding\Crawl Wiki"
    ).expanduser()
    return root, root / _KB_SUBDIR


def parse_topics(config: object) -> list[str]:
    raw = str(getattr(config, "bot_kb_wiki_topics", "") or "")
    return [part.strip() for part in raw.split(",") if part.strip()]


def source_label(source: str) -> str:
    if source in _SOURCE_LABELS:
        return _SOURCE_LABELS[source]
    if source.startswith("bilibili_wiki"):
        return "B站wiki"
    return source


def _id_topic(doc_id: str) -> str:
    return doc_id.split("/", 1)[0]


# 语料行时间字段 → 台账列名：爬虫侧叫 updated_at/crawled_at（KB_HANDOFF 契约），
# Bot 台账列叫 source_updated_at/crawl_at。映射只在这一处发生，两侧名字都是契约。
_TIME_FIELD_TO_LEDGER_COLUMN = (("updated_at", "source_updated_at"), ("crawled_at", "crawl_at"))


def row_time_metadata(row: dict) -> dict[str, str]:
    """语料行的时间元数据（台账列名为键）。

    只透出**行里存在**的键：未增强的旧导出没有这两个字段，此时返回空字典，
    台账保持 NULL（=从未回填），绝不写空串冒充「上游没有编辑时间」。
    """
    metadata: dict[str, str] = {}
    for row_key, column in _TIME_FIELD_TO_LEDGER_COLUMN:
        if row_key in row:
            metadata[column] = str(row.get(row_key) or "")
    return metadata


# ---------------------------------------------------------------- 分块


def split_doc_chunks(text: str, title: str, *, hard_limit: int = 800) -> list[str]:
    """按 Markdown 标题分节；每块携带「词条标题｜节标题」前缀便于嵌入与溯源。

    超长节/超长单行按 hard_limit 硬切（接「｜续」前缀）；空正文返回空列表。
    """
    if not str(text or "").strip():
        return []
    chunks: list[str] = []
    buffer: list[str] = [f"【{title}】"]

    def flush(new_header: str) -> None:
        block = "\n".join(buffer).strip()
        if block:
            chunks.append(block)
        buffer.clear()
        buffer.append(new_header)

    for raw_line in str(text).splitlines():
        line = raw_line.rstrip()
        if line.startswith("##"):
            heading = line.lstrip("#").strip()
            flush(f"【{title}｜{heading or '续'}】")
            continue
        while len(line) > hard_limit:
            buffer.append(line[:hard_limit])
            flush(f"【{title}｜续】")
            line = line[hard_limit:]
        buffer.append(line)
        if sum(len(part) + 1 for part in buffer) > hard_limit:
            flush(f"【{title}｜续】")
    flush("")
    return [chunk for chunk in chunks if chunk.strip()]


def _to_sync_doc(row: dict, *, chunk_chars: int) -> dict:
    title = str(row.get("title") or "")
    source = str(row.get("source") or "")
    label = source_label(source)
    display_title = f"{title}·{label}" if label and label != title else title
    return {
        "id": str(row.get("id") or ""),
        "hash": str(row.get("hash") or ""),
        "topic": str(row.get("topic") or ""),
        "source": source,
        "title": display_title or str(row.get("id") or ""),
        "chunks": split_doc_chunks(
            str(row.get("text") or ""), title, hard_limit=chunk_chars
        ),
        **row_time_metadata(row),
    }


# ---------------------------------------------------------------- 语料流


def iter_kb_documents(kb_dir: Path, topics: list[str]) -> Iterator[dict]:
    """流式逐行读 documents.jsonl 全量快照；topics 为空 = 全部。"""
    path = kb_dir / "documents.jsonl"
    allowed = set(topics)
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if allowed and str(row.get("topic") or "") not in allowed:
                continue
            yield row


def iter_kb_updates(kb_dir: Path, topics: list[str]) -> Iterator[dict]:
    """流式逐行读 updates.jsonl 本轮增量（op=upsert/delete）；topics 为空 = 全部。"""
    path = kb_dir / "updates.jsonl"
    if not path.is_file():
        return
    allowed = set(topics)
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            topic = str(row.get("topic") or "") or _id_topic(str(row.get("id") or ""))
            if allowed and topic not in allowed:
                continue
            yield row


def iter_kb_document_metadata(kb_dir: Path, topics: list[str]) -> Iterator[dict]:
    """documents.jsonl → 台账时间元数据流（只投影 id/hash 与两列时间）。

    与 ``iter_kb_documents`` 同一份磁盘流，但**不分块、不算 hash、不读进内存**：
    全表回填 7.5 万条元数据的成本就是一遍顺序读，零嵌入调用。
    """
    for row in iter_kb_documents(kb_dir, topics):
        doc_id = str(row.get("id") or "")
        if not doc_id:
            continue
        yield {
            "id": doc_id,
            "hash": str(row.get("hash") or ""),
            **row_time_metadata(row),
        }


# ------------------------------------------------ 库侧在册主题 ↔ 本地域锚点
#
# 同源门（2026-09-28，测试件 tests/test_kb_list_domain_gate.py）：库里**实际收录**
# 哪些语料域，和本 bot「哪些域走本地优先」的词表是两份各写各的东西时，会出现
# 「资料明明躺着、却被推去联网」。本区只出库侧那一侧的真身（现算，源码里不登
# 第二份名单——规则 10）；锚点侧一律引用 ``question_intent.DOMAIN_TERMS`` 本体，
# 两侧相减的判据在 ``topics_without_local_domain_anchor``。
#
# 接线状态：本区今天全仓零消费方（门已立、接线待下一票），不要把它当成生效闸。


def iter_corpus_topic_names(
    kb_dir: Path, *, scan_limit: int | None = None
) -> Iterator[str]:
    """流式逐行读 documents.jsonl，按首次出现顺序透出库里实际收录的语料域。

    - 主题口径与 ``iter_kb_updates`` 同源：行里的 ``topic`` 优先，旧导出没这个
      字段时退回 ``_id_topic(id)``（doc_id 首段），**不许静默丢域**；
    - 去重按首次出现（``dict`` 保序语义），所以读数即「库里有哪些域」；
    - ``scan_limit`` 把**原始行读取量**钉在上限（与元数据探针同一纪律：诊断
      路径不许退化成全表扫），None = 不设限。注意它限的是行数不是产出个数——
      窗口里重复域多时透出的域名可以少于上限，那是真读数；
    - 文件缺失/不可读 → 不透出任何域名：读不到就是**没有证据**，调用方不得据此
      宣称「库里没有这一域」（台账 #51★「没检索禁写它没有」）。
    """
    path = kb_dir / "documents.jsonl"
    if not path.is_file():
        return
    budget = None if scan_limit is None else max(1, int(scan_limit))
    seen: set[str] = set()
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in islice(handle, budget):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                topic = str(row.get("topic") or "") or _id_topic(str(row.get("id") or ""))
                if not topic or topic in seen:
                    continue
                seen.add(topic)
                yield topic
    except (OSError, UnicodeError):
        # 读到一半坏了：把已经拿到的域名如实交出去（上面已 is_file，缺文件即空）。
        return


def local_domain_anchor_terms() -> tuple[str, ...]:
    """本地域锚点名册＝``question_intent.DOMAIN_TERMS`` 本身（真身只有一处）。

    惰性 import 是刻意的：本文件已跨域引 ``chat_reply.character.vector_knowledge``，
    再往模块级挂第二层跨域边不值当。这里只透出真身的 tuple 视图，绝不复制内容。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.question_intent import (
        DOMAIN_TERMS,
    )

    return tuple(DOMAIN_TERMS)


def topics_without_local_domain_anchor(
    topics: Iterable[str], *, domain_terms: Iterable[str] | None = None
) -> list[str]:
    """在册主题里「本地域词表缺锚点」的那几枚（缺口名单）。

    - ``domain_terms`` 缺省取 ``local_domain_anchor_terms()``（同源）；调用方传入
      时按传入的词表判（测试用它做「摘掉锚点必须报缺」的反证腿）；
    - 返回保输入序、不去重；空列表＝两侧今天对齐，非空＝这些域的题既不判
      LOCAL_KNOWLEDGE、也走不到「本地优先、低置信才补网」。
    """
    vocab = set(local_domain_anchor_terms() if domain_terms is None else domain_terms)
    return [str(topic) for topic in topics if str(topic) not in vocab]


# ---------------------------------------------------------------- 清单对账


def manifest_index(manifest: dict, topics: list[str]) -> dict[str, str]:
    """manifest.entries（全量 id→hash 快照）→ 本域可用的对账索引。

    清单自相矛盾（``documents`` 与 entries 条数不等）或为空时返回空字典，
    调用方据此**放弃对账**而不是照删：宁可不补不漏删，残缺清单驱动删除会把
    整域文档连块清掉。topics 为空 = 全部。
    """
    entries = manifest.get("entries")
    if not isinstance(entries, dict) or not entries:
        return {}
    declared = int(manifest.get("documents", 0) or 0)
    if declared and declared != len(entries):
        return {}
    allowed = set(topics)
    index: dict[str, str] = {}
    for doc_id, digest in entries.items():
        doc_id = str(doc_id)
        if not doc_id or not isinstance(digest, str) or not digest.strip():
            continue
        if allowed and _id_topic(doc_id) not in allowed:
            continue
        index[doc_id] = digest
    return index


def _manifest_corpus_topics(manifest: dict, entries: dict[str, str]) -> set[str]:
    """清单覆盖到的语料域集合（per-topic 统计优先，退回从 entries 推导）。

    对账删除只用它做「清单是否覆盖该域」的判据：不覆盖就绝不删该域的台账行。
    注意这只是**清单侧**的覆盖集——本地 topics 收窄同步时，调用方还须把它
    与授权域求交（见 reconcile_with_manifest），否则全量统计会让子集外的域
    被误判「覆盖」而放行整域删除。
    """
    stats = manifest.get("topics")
    if isinstance(stats, dict) and stats:
        return {str(topic) for topic in stats if str(topic)}
    return {_id_topic(doc_id) for doc_id in entries}


def reconcile_with_manifest(
    store: SqliteVectorKnowledgeStore,
    manifest: dict,
    topics: list[str],
) -> tuple[dict[str, Any], set[str], set[str]]:
    """台账 ↔ manifest.entries 对账：返回 ``(统计, 待补 id 集, 待删 id 集)``。

    - **待补**：清单有、台账没有，或两边 hash 不同（内容变了却没进本轮
      updates.jsonl——正是「一天两档导出、Bot 只读一档」时被覆盖掉的那部分）；
      全文由调用方从 documents.jsonl 补投。
    - **待删**：台账有、清单没有，且清单确实覆盖了它所属的语料域、该域又在
      本轮 ``topics`` 授权范围内（``topics`` 为空 = 全部）。
      清单没覆盖该域（爬虫按 topic 子集导出、或 entries 与 documents 数不等）、
      或本地把同步收窄到了子集白名单时，域外一律视为「本轮未覆盖」：挂起删除、
      只记 ``reconcile_status``，绝不拿残缺清单当删除依据。
    """
    stats: dict[str, Any] = {
        "reconcile_status": "ok",
        "reconcile_missing": 0,
        "reconcile_extra": 0,
        "reconcile_held": 0,
    }
    entries = manifest_index(manifest, topics)
    if not entries:
        stats["reconcile_status"] = "skipped_manifest_incomplete"
        return stats, set(), set()
    ledger = store.document_ledger()
    missing = {
        doc_id for doc_id, digest in entries.items() if ledger.get(doc_id) != digest
    }
    corpus_topics = _manifest_corpus_topics(manifest, entries)
    # 护栏收紧（2026-09-20 整域误删修复）：删除判据必须与收窄 entries 的是
    # **同一个** topics 集合——本地只授权子集域同步时，清单的全量 per-topic
    # 统计对子集外的域不构成「覆盖」，其台账行一律挂起（进 held）。不收紧，
    # 填一次子集白名单就会把其余整域连块带台账清空。topics 为空 = 全部，
    # 此处交集为无操作，全量行为逐字段不变。
    allowed = set(topics)
    if allowed:
        corpus_topics &= allowed
    orphans = {doc_id for doc_id in ledger if doc_id not in entries}
    removable = {doc_id for doc_id in orphans if _id_topic(doc_id) in corpus_topics}
    stats["reconcile_missing"] = len(missing)
    stats["reconcile_extra"] = len(removable)
    stats["reconcile_held"] = len(orphans) - len(removable)
    if stats["reconcile_held"]:
        stats["reconcile_status"] = _RECONCILE_REMOVE_SUSPENDED
    return stats, missing, removable


# ---------------------------------------------------------------- 同步编排


def sync_kb_wiki(
    store: SqliteVectorKnowledgeStore,
    config: object,
    *,
    full: bool = False,
    on_progress: Callable[[dict], None] | None = None,
) -> dict[str, Any]:
    """把 Crawl Wiki 知识库按 hash 幂等协议同步进向量库，返回统计。"""
    _root, kb_dir = kb_paths(config)
    manifest_path = kb_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"知识库清单不存在: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    topics = parse_topics(config)
    chunk_chars = max(200, int(getattr(config, "bot_kb_wiki_chunk_chars", 800) or 800))

    removed_ids: list[str] = []
    reconcile: dict[str, Any] = {
        "reconcile_status": "skipped_full" if full else "ok",
        "reconcile_missing": 0,
        "reconcile_extra": 0,
        "reconcile_held": 0,
    }
    docs: Iterable[dict]
    if full:
        docs = (
            _to_sync_doc(row, chunk_chars=chunk_chars)
            for row in iter_kb_documents(kb_dir, topics)
        )
    else:
        removed_ids = [
            str(row.get("id") or "")
            for row in iter_kb_updates(kb_dir, topics)
            if str(row.get("op")) == "delete" and str(row.get("id") or "")
        ]
        covered: set[str] = set()

        def _update_docs() -> Iterator[dict]:
            for row in iter_kb_updates(kb_dir, topics):
                if str(row.get("op")) != "upsert":
                    continue
                doc_id = str(row.get("id") or "")
                if doc_id:
                    covered.add(doc_id)
                yield _to_sync_doc(row, chunk_chars=chunk_chars)

        for doc_id in manifest.get("removed", []):
            doc_id = str(doc_id)
            if doc_id and (not topics or _id_topic(doc_id) in topics):
                removed_ids.append(doc_id)

        # 对账兜底（2026-09-20 元数据批）：updates.jsonl 是每轮**覆盖写**的本轮
        # diff，而爬虫一天两档导出（16:00 / 23:00）、Bot 只在 23:40 读一档，
        # 前档 diff 被覆盖后永久丢失。这里不再依赖 updates.jsonl 的完整性，改用
        # manifest.entries 全量 id→hash 快照与本地台账比对：缺项补投（从
        # documents.jsonl 取全文）、多项删除（清单未覆盖该域时挂起，见上）。
        reconcile, missing_ids, extra_ids = reconcile_with_manifest(
            store, manifest, topics
        )
        removed_ids.extend(sorted(extra_ids))
        if missing_ids:
            def _reconcile_docs() -> Iterator[dict]:
                for row in iter_kb_documents(kb_dir, topics):
                    doc_id = str(row.get("id") or "")
                    # covered 由上一段生成器在 chain 消费顺序下先于此处填满：
                    # 本轮 updates 已投过的文档不再重复投（否则同一文档计两次
                    # added/changed 并把刚写好的块删了重写）。
                    if doc_id in missing_ids and doc_id not in covered:
                        yield _to_sync_doc(row, chunk_chars=chunk_chars)

            docs = chain(_update_docs(), _reconcile_docs())
        else:
            docs = _update_docs()

    stats = store.sync_documents(
        docs,
        removed_ids=removed_ids,
        full=full,
        on_progress=on_progress,
    )
    return {
        "kb_dir": str(kb_dir),
        "generated_at": str(manifest.get("generated_at", "")),
        "documents_total": int(manifest.get("documents", 0) or 0),
        **reconcile,
        **stats,
    }


# ------------------------------------------------ 元数据闸的有界窗口探针
# 判据形态（2026-09-20 修复）：旧版只看 documents.jsonl **首行**有没有 crawled_at
# 就给整个语料（实测 75,737 行）判「有没有时间字段」。一行样本不具代表性——行序
# 一变（某个不带该字段的源排到最前）全库回填被一票否决，而记出的 skipped_* 看
# 起来像「语料本来就没这字段」，没人会去查。现在读前 N 行做计数，判据依据
# （probed/with_time）随状态一起透出。
#
# 窗口有界是真需求，不是偷懒：全表 240MB 顺序读每夜白付不值得（未增强语料怎么
# 扫都扫不出东西）。N=300 既让「首行噪声」翻不了案（一行的影响力被摊薄到
# ≤0.33%），又只是全扫的 0.4% 成本。
_METADATA_PROBE_WINDOW_LINES = 300
# 采样比例门槛：窗口里至少 10% 的行带时间字段才认定「语料已增强」。
# 用百分数做整数比对（with_time*100 >= probed*10），不引入浮点边界毛刺。
# 下限另设 1 行，保证微型语料（1-9 行且全带字段）照常刷，与旧行为向后一致。
_METADATA_PROBE_MIN_RATIO_PCT = 10
# 指定 topics 子集时的原始行扫描上限：凑不满窗口也不许退化成全表扫。
_METADATA_PROBE_MAX_SCAN_LINES = _METADATA_PROBE_WINDOW_LINES * 20


def probe_corpus_time_fields(
    kb_dir: Path,
    *,
    topics: Iterable[str] = (),
    window: int = _METADATA_PROBE_WINDOW_LINES,
) -> dict[str, Any]:
    """流式数 documents.jsonl 前 ``window`` 行里带 ``crawled_at`` 的比例。

    返回 ``{"probed", "with_time", "has_fields"}``：

    - ``probed`` = 窗口内**计入样本**的行数（空行、坏 JSON、非对象行既不进分子
      也不进分母——它们不给任何样本背书）；
    - ``has_fields`` = ``with_time >= 1`` 且命中数不低于窗口样本的 10%；
    - 文件缺失/不可读 → 诚实的 ``{0, 0, False}``（读不到就是没证据，不猜）。

    ``topics`` 非空时只统计这些语料域的行（与 ``refresh_kb_metadata`` 的过滤
    口径同源：闸采的样必须是被闸管的总体），最多扫
    ``_METADATA_PROBE_MAX_SCAN_LINES`` 原始行即止。
    """
    path = kb_dir / "documents.jsonl"
    allowed = {str(topic) for topic in topics if str(topic)}
    budget = max(1, int(window))
    probed = 0
    with_time = 0
    try:
        with path.open("r", encoding="utf-8") as handle:
            # islice 把「原始行扫描量」钉死在上限：被 topics 滤掉的行也得计数，
            # 否则窄域配置下这里会一路 continue 到文件尾，退化成每夜全表扫。
            for line in islice(handle, _METADATA_PROBE_MAX_SCAN_LINES):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                if allowed and _id_topic(str(row.get("id") or "")) not in allowed:
                    continue
                probed += 1
                if "crawled_at" in row:
                    with_time += 1
                # 窗口判定放循环体末尾：放开头会为下一行先付一次读（窗口外哪怕
                # 是不可解码的脏字节也会被碰一下），"有界"就成了嘴上说说。
                if probed >= budget:
                    break
    except (OSError, UnicodeError):
        # 打不开/读到一半坏了：把已经拿到的样本如实交出去（缺文件时即 0/0）。
        pass
    has_fields = with_time >= 1 and with_time * 100 >= probed * _METADATA_PROBE_MIN_RATIO_PCT
    return {"probed": probed, "with_time": with_time, "has_fields": has_fields}


def corpus_has_time_fields(kb_dir: Path) -> bool:
    """语料侧是否已带时间字段（bool 视图，判据与 ``probe_corpus_time_fields`` 同源）。

    保留这个签名只因为它是既有调用面/测试面；判据细节（有界窗口计数、比例门槛）
    一律在探针里，别再在这里长第二套判法。
    """
    return bool(probe_corpus_time_fields(kb_dir)["has_fields"])


def refresh_kb_metadata(
    store: SqliteVectorKnowledgeStore, config: object
) -> dict[str, Any]:
    """零嵌入成本的全表时间元数据回填（语料侧只加时间字段时的首晚路径）。

    爬虫导出层新增 ``updated_at``/``crawled_at`` 后，正文一字未改、hash 不变，
    Bot 侧幂等协议因此**不会**重走同步分支——台账两列会永远停在 NULL。本函数
    只读 documents.jsonl 的时间字段并 UPDATE 台账（``sync_document_metadata``），
    不产生待嵌行、不清 FTS/ANN 签名、一次嵌入都不调；由 ``run_kb_sync_task``
    在检测到台账存在未回填文档时自动触发，也可单独调用补跑。
    """
    _root, kb_dir = kb_paths(config)
    topics = parse_topics(config)
    stats = store.sync_document_metadata(iter_kb_document_metadata(kb_dir, topics))
    return {"kb_dir": str(kb_dir), **stats}


def _build_provider(
    config: object, *, timeout_override: float | None = None
) -> OpenAICompatibleEmbeddingProvider:
    """与 build_vector_knowledge_provider 同源的嵌入链：本地 Ollama 优先。"""

    def _first(name: str, default):
        value = getattr(config, name, None)
        if value is None or (isinstance(value, str) and not value.strip()):
            return default
        return value

    effective_timeout = (
        max(0.5, float(timeout_override))
        if timeout_override is not None
        else float(_first("bot_embedding_timeout_seconds", 15.0))
    )
    effective_local_timeout = (
        max(0.5, float(timeout_override))
        if timeout_override is not None
        else float(_first("bot_embedding_local_timeout_seconds", 60.0))
    )
    return OpenAICompatibleEmbeddingProvider(
        base_url=str(getattr(config, "bot_embedding_base_url", "") or ""),
        model=str(getattr(config, "bot_embedding_model", "") or ""),
        api_key=str(getattr(config, "bot_embedding_api_key", "") or ""),
        timeout_seconds=effective_timeout,
        dimensions=int(_first("bot_embedding_dimensions", 1024)),
        local_base_url=str(getattr(config, "bot_embedding_local_base_url", "") or ""),
        local_models=str(getattr(config, "bot_embedding_local_models", "") or ""),
        local_api_key=str(getattr(config, "bot_embedding_local_api_key", "") or ""),
        local_enabled=bool(getattr(config, "bot_embedding_local_enabled", True)),
        local_timeout_seconds=effective_local_timeout,
    )


def _embedding_chain_ready(config: object) -> bool:
    if not bool(getattr(config, "bot_embedding_enabled", False)):
        return False
    local_ready = bool(getattr(config, "bot_embedding_local_enabled", True)) and bool(
        str(getattr(config, "bot_embedding_local_models", "") or "").strip()
    ) and bool(str(getattr(config, "bot_embedding_local_base_url", "") or "").strip())
    remote_ready = bool(
        str(getattr(config, "bot_embedding_model", "") or "").strip()
    ) and bool(str(getattr(config, "bot_embedding_base_url", "") or "").strip())
    return local_ready or remote_ready


def _kb_db_path(config: object) -> str:
    """kb 向量库路径的唯一派生式（缺省值只这一处）。

    取消旗与库同目录，故旗路径必须由它派生；此前这段"取配置或落缺省"在
    `_build_store` / `_get_shared_store` 各写一遍，S112 再要一次就是第四遍
    ——缺省串多一份副本，就多一个"改了这处忘了那处"的口径分叉面。
    """
    return str(getattr(config, "bot_kb_wiki_db_path", "") or "data/kb_wiki_embeddings.sqlite3")


def _build_store(
    config: object,
    *,
    timeout_override: float | None = None,
    auto_reset: bool,
) -> SqliteVectorKnowledgeStore:
    db_path = _kb_db_path(config)
    provider = _build_provider(config, timeout_override=timeout_override)
    return SqliteVectorKnowledgeStore(
        db_path=db_path,
        embed_provider=provider,
        chunk_chars=max(200, int(getattr(config, "bot_kb_wiki_chunk_chars", 800) or 800)),
        top_k=int(getattr(config, "bot_kb_wiki_top_k", 4) or 4),
        signature=getattr(provider, "signature", ""),
        auto_reset=auto_reset,
        ann_index_path=str(Path(db_path).with_name("kb_wiki_faiss.index")),
        ann_order_path=str(Path(db_path).with_name("kb_wiki_faiss.order.json")),
        # 检索进程发现 FTS 签名缺失不做分钟级内联重建，重建由 kb-sync 负责。
        fts_auto_rebuild=False,
    )


def _get_shared_store(
    config: object, *, timeout_override: float | None = None
) -> SqliteVectorKnowledgeStore:
    """进程级共享 store（检索器与调度同步任务共用，同步状态即时生效）。

    timeout_override 只在首次构建时生效（fast 模式传 3s 上限查询嵌入）；
    同步任务运行期间会临时换上全长超时 provider，不影响这里的常态配置。
    """
    db_path = _kb_db_path(config)
    with _SHARED_STORES_LOCK:
        store = _SHARED_STORES.get(db_path)
        if store is None:
            store = _build_store(
                config, timeout_override=timeout_override, auto_reset=False
            )
            _SHARED_STORES[db_path] = store
        return store


# ---------------------------------------------------------------- 检索


class KBWikiRetriever:
    """Crawl Wiki 向量库检索器（与 _VectorKnowledgeRetriever 同接口）。"""

    available = True

    def __init__(self, store: SqliteVectorKnowledgeStore) -> None:
        self._store = store

    def retrieve(self, query_text: str) -> list:
        if not str(query_text or "").strip():
            return []
        try:
            return self._store.retrieve(
                str(query_text), files=None, embed_backlog=False
            )
        except Exception as exc:  # noqa: BLE001 - 检索异常按无结果降级，不阻断对话。
            # 降级照旧，但必须留痕（S-KB-QUALITY KQ-7）：旧写法一句日志不打，
            # 于是「存储层炸了」与「库里确实没有」在日志里长得一模一样，运维只能
            # 等用户报「它说没有」才反推。只记类型与长度，不记查询正文——查询是用户内容。
            logger.warning(
                "kb wiki retrieval degraded type=%s query_len=%d",
                type(exc).__name__,
                len(str(query_text)),
            )
            return []


def build_kb_wiki_retriever(
    config: object, *, timeout_override: float | None = None
) -> object:
    """按配置构建 wiki 知识库检索器；未启用/语料缺失/嵌入链缺失时不可用。"""
    if not bool(getattr(config, "bot_kb_wiki_enabled", False)):
        return _UnavailableVectorKnowledgeProvider()
    if not _embedding_chain_ready(config):
        return _UnavailableVectorKnowledgeProvider()
    _root, kb_dir = kb_paths(config)
    if not (kb_dir / "manifest.json").is_file():
        return _UnavailableVectorKnowledgeProvider()
    try:
        return KBWikiRetriever(
            _get_shared_store(config, timeout_override=timeout_override)
        )
    except Exception:  # noqa: BLE001 - 构建失败降级为不可用，不阻断对话。
        return _UnavailableVectorKnowledgeProvider()


class MergedKnowledgeRetriever:
    """多检索器轮询交错合并：按各路排名 round-robin，chunk_id 去重。

    传入顺序即优先级（人格知识库在前、wiki 库在后），prompt 字符预算裁剪
    时排在前面的块更可能保留。

    ``libraries`` 与 ``retrievers`` 等长时，按**路**给每条块标注来源库名
    （``source_library``）。各路自己的 ``source_id`` 是页级标识（可超 64 字符、
    且对不上「谁先答」阶梯），标注是阶梯判「本地命中」的唯一依据——只有这一处
    知道某条块是从哪一路来的，所以标注发生在这里，不在下游猜前缀。
    """

    available = True

    def __init__(self, retrievers: list, libraries: list[str] | None = None) -> None:
        names = [str(name or "").strip() for name in libraries] if libraries else None
        if names is not None and len(names) != len(retrievers):
            # 长度不匹配＝调用方漏了一路；宁可整体不标注，也不按位置瞎配。
            logger.warning(
                "merged retriever library stamping skipped legs=%d names=%d",
                len(retrievers),
                len(names),
            )
            names = None
        self._retrievers: list = []
        self._libraries: list[str | None] = []
        for index, retriever in enumerate(retrievers):
            if not getattr(retriever, "available", True):
                continue
            self._retrievers.append(retriever)
            self._libraries.append(names[index] if names else None)

    @staticmethod
    def _stamp(chunk: Any, library: str | None) -> Any:
        if not library:
            return chunk
        copier = getattr(chunk, "model_copy", None)
        if not callable(copier):  # 测试假块/旧契约代际：原样放行，不冒充标注。
            return chunk
        if str(getattr(chunk, "source_library", "") or "").strip():
            return chunk  # 已标注过（嵌套合并）⇒ 不覆盖第一手的来源路。
        try:
            return copier(update={"source_library": library})
        except Exception:  # noqa: BLE001 - 契约不含该字段时退回原块，绝不为标注炸掉检索。
            return chunk

    def retrieve(self, query_text: str) -> list:
        streams: list[list] = []
        for retriever in self._retrievers:
            try:
                streams.append(list(retriever.retrieve(query_text) or []))
            except Exception as exc:  # noqa: BLE001 - 单路失败不影响另一路。
                # 留痕到「哪一路」：只说"合并检索降级"分不出人格库还是维基库，
                # 而这两路的 owner、库文件、重建命令都不一样（KQ-7 同票）。
                logger.warning(
                    "merged knowledge retrieval leg failed leg=%s type=%s",
                    type(retriever).__name__,
                    type(exc).__name__,
                )
                streams.append([])
        total = sum(len(stream) for stream in streams)
        merged: list = []
        seen: set[str] = set()
        index = 0
        while len(merged) < total:
            progressed = False
            for stream_index, stream in enumerate(streams):
                if index >= len(stream):
                    continue
                chunk = self._stamp(
                    stream[index], self._libraries[stream_index]
                    if stream_index < len(self._libraries)
                    else None
                )
                if chunk.chunk_id in seen:
                    continue
                seen.add(chunk.chunk_id)
                merged.append(chunk)
                progressed = True
            if not progressed:
                break
            index += 1
        return merged


# ---------------------------------------------------------------- 同步任务入口

# R3 停摆批（2026-09-17）：同步任务治理三件。
# 背景：调度器（nonebot_plugin_apscheduler 的 AsyncIOScheduler）对同步 job
# 走 ``loop.run_in_executor(None, ...)``＝事件循环默认线程池（与语音转码、
# TG 下载等 to_thread 共享、min(32, cpu+4)）。启动补同步（+45s）与夜间
# 23:40 两个 job-id 可并发，全量灌库（75683 文档/238453 块）单次要数小时；
# 零变更夜也全量重建 ANN（实测 8.5 分钟）。此前的故障链：同步失效向量缓存
# → 首次检索在检索锁内全表载入（5.7GB 库）→ 聊天池堆满 → pipeline_busy
# 静默吞消息、LLM 请求发不出。除 kb_wiki 侧治理外，检索锁内全表载入已在
# vector_knowledge._prewarm_vector_cache 根修（2026-09-17 R3 停摆批）。

# 进程级任务互斥：启动补同步与夜间同步撞车时后者直接 busy 跳过。
_SYNC_TASK_MUTEX = threading.Lock()
# 协作式取消事件：嵌入/同步批次之间检查（检查点=批边界，落库断点天然存在：
# sync_documents 每 500 文档一提交、embed 每批一落向量行，重跑自动续传）。
_SYNC_CANCEL_EVENT = threading.Event()

# --- 操作员取消旗（S112，2026-09-26）------------------------------------------
# 为什么需要旗标而不是函数调用：`_SYNC_CANCEL_EVENT` 是**进程局部**的
# `threading.Event`，而 `cancel_kb_sync_task()` 全仓唯一调用点在 `bot.py:405`
# 的 `@driver.on_shutdown` 钩子里 ⇒ 今天想停掉在跑的夜间同步，只有把 bot 停机
# 这一条路（S105 报的"只能等它跑完或杀进程"就是这个形状）。
# 三条候选通路现算否决两条：
#   ① operator CLI 旗 —— smoke 是**另一个进程**，它置不到 bot 进程里的 Event；
#   ② 控制面端点 —— `control_plane` 是独立 uvicorn 进程（`__main__.py:serve()`）
#      且 `bot_control_plane_enabled` 缺省 False，同样跨不到进程边界；
#   ③ 文件哨兵 —— 跨进程可见、不需要新监听面、不需要凭据、崩了不留半状态。
# 故选 ③：操作员在 kb 库同目录放一个 `kb_sync.cancel`，下一个批边界停。
# 取消粒度**完全沿用既有协作式语义**（批边界检查、断点已在库、重跑自动续传），
# 本旗只是多给一个"从进程外按同一个钮"的入口，不改任何检查点。
_SYNC_CANCEL_FLAG_FILENAME = "kb_sync.cancel"
# 有效期：只在 TTL 内认这个旗。防的是"某次手滑建了个文件、此后台台同步每晚被
# 莫名取消"——陈旧旗与陈旧取消事件是同一类毒，处理办法也同一条：一次性消费 +
# 过期即当垃圾清掉（对齐 `run_kb_sync_task` 出口那行"陈旧置位最多取消一轮"）。
_SYNC_CANCEL_FLAG_TTL_SECONDS = 6 * 3600
# 当前在跑那一轮的旗标路径（`_SYNC_TASK_MUTEX` 保证同刻最多一轮，故单变量够用；
# 与 `vector_knowledge._ann_build_gate` 同一手法：入口登记、finally 归还）。
_SYNC_CANCEL_FLAG_PATH: Path | None = None
_SYNC_CANCEL_FLAG_LOCK = threading.Lock()


def current_kb_sync_cancel_flag_path() -> Path | None:
    """本轮 kb-sync 监听的取消旗路径（在跑才非空）。供日志/测试/运维探针读。"""
    with _SYNC_CANCEL_FLAG_LOCK:
        return _SYNC_CANCEL_FLAG_PATH


def _set_kb_sync_cancel_flag_path(path: Path | None) -> None:
    """登记/归还本轮旗路径。

    ⚠ `global` 不是装饰性关键字：少了它这句赋值只是在函数里造一个**局部变量**，
    Python 一声不响，模块值恒为 None ⇒ 旗路径永远没登记、旗标永远没人消费、
    取消钮按下去毫无反应。本席第一版就漏了它，被活性锁
    `test_cancel_flag_consumed_at_sync_batch_boundary` 当场打回（见席位报告 §4）。
    """
    global _SYNC_CANCEL_FLAG_PATH
    with _SYNC_CANCEL_FLAG_LOCK:
        _SYNC_CANCEL_FLAG_PATH = path


def kb_sync_cancel_flag_path(db_path: object) -> Path:
    """由 kb 库路径派生取消旗路径（与库同目录，确定性、可口述）。"""
    return Path(str(db_path)).with_name(_SYNC_CANCEL_FLAG_FILENAME)


def _consume_cancel_flag() -> bool:
    """批边界上的旗标消费：在位且未过期 ⇒ 置位 Event 并删除文件，返回 True。

    一次性消费（删文件）是关键：不删的话这面旗会取消此后每一轮同步，
    而操作员的本意从来只有"停掉这一次"。置位 Event 而非直接抛，是为了让
    "从文件来的请求"与"从停机钩子来的请求"走**同一条**判定路径
    （`_raise_if_cancelled`），不留第二种取消语义。
    """
    flag = current_kb_sync_cancel_flag_path()
    if flag is None:
        return False
    try:
        if not flag.is_file():
            return False
        age = time.time() - flag.stat().st_mtime
        flag.unlink(missing_ok=True)
    except OSError as exc:
        # 读不到就不当作请求：宁可让这一轮跑完，也不要因为一次 stat 失败
        # 把数小时的同步判死（那是把可观测性故障升级成生产故障）。
        logger.warning("kb_wiki_sync: 取消旗读取失败（按未取消处理）：%s", exc)
        return False
    if age > _SYNC_CANCEL_FLAG_TTL_SECONDS:
        logger.warning(
            "kb_wiki_sync: 忽略过期的取消旗（存在 %.1f 小时 > TTL %.1f 小时），已清掉。",
            age / 3600.0,
            _SYNC_CANCEL_FLAG_TTL_SECONDS / 3600.0,
        )
        return False
    if _SYNC_CANCEL_EVENT.is_set():
        return True
    logger.warning(
        "kb_wiki_sync: 收到取消旗 %s（存在 %.1f 分钟），本轮将在下一个批边界停止。",
        flag.name,
        max(0.0, age) / 60.0,
    )
    _SYNC_CANCEL_EVENT.set()
    return True


def request_kb_sync_cancel(*, reason: str = "", db_path: object = "") -> bool:
    """进程外请求取消 kb-sync：落一面旗 + 若在跑的正是本进程则顺手置位。

    返回是否本次真正**新落下**一个取消请求（幂等：Event 已置位且旗已在位时
    返回 False）。给两个入口共用：operator CLI（另一个进程，只能落旗）与
    测试/进程内管理面（同进程，旗与 Event 双落，行为与直接调
    `cancel_kb_sync_task` 一致）。
    """
    requested = cancel_kb_sync_task(reason=reason)
    if str(db_path or "").strip():
        try:
            flag = kb_sync_cancel_flag_path(db_path)
            flag_existed = flag.exists()
            flag.parent.mkdir(parents=True, exist_ok=True)
            flag.write_text(
                f"requested_by_pid={os.getpid()} reason={reason or 'unspecified'}\n",
                encoding="utf-8",
            )
            logger.warning("kb_wiki_sync: 已落取消旗 %s", flag)
            # 旗本来就是幂等的那一半：已存在则本次没有新增请求，返回值不能谎报。
            requested = requested or not flag_existed
        except OSError as exc:
            logger.warning("kb_wiki_sync: 取消旗落不下（只置了本进程事件）：%s", exc)
    return requested


class KbSyncCancelled(BaseException):
    """kb-sync 协作式取消信号。

    刻意继承 ``BaseException``：内层（sync_documents/embed_pending 的
    on_progress 回调包装）对 ``Exception`` 一律吞并，取消信号必须穿透
    这些兜底直达 run_kb_sync_task 的显式 catch；provider 还原等清理由
    调用链上的 ``finally`` 保证执行。
    """


def cancel_kb_sync_task(*, reason: str = "") -> bool:
    """请求取消在跑的 kb-sync（幂等）；返回是否本次真正置位。

    供停机序列（bot.py，R2b 域）或管理面调用；请求在下一次
    run_kb_sync_task 入口被消费（该轮立即取消），出口自动清残留——
    陈旧请求最多取消一轮，绝不毒化后续夜间同步。
    """
    if _SYNC_CANCEL_EVENT.is_set():
        return False
    _SYNC_CANCEL_EVENT.set()
    logger.info(
        "kb_wiki_sync: 已请求取消在跑的同步任务%s",
        f"（{reason}）" if reason else "",
    )
    return True


def _raise_if_cancelled() -> None:
    if _SYNC_CANCEL_EVENT.is_set() or _consume_cancel_flag():
        raise KbSyncCancelled("kb_wiki_sync: 收到取消请求")


def _cancel_aware_progress(
    user_cb: Callable[..., object] | None,
) -> Callable[..., None]:
    """包一层进度回调：先查取消（穿透式抛出），再吞并用户回调的普通异常。

    与 store 内层对 on_progress 的 ``except Exception: pass`` 同语义兼容
    （双重保险），但取消信号是 BaseException 不被吞。参数签名取 ``...``：
    同步进度回调 1 参（dict）、嵌入进度回调 2 参（done, total）共用。
    """

    def wrapped(*args: Any) -> None:
        _raise_if_cancelled()
        if user_cb is not None:
            try:
                user_cb(*args)  # 同步进度 1 参（dict）/嵌入进度 2 参（done,total）。
            except Exception:
                logger.debug(
                    "kb_wiki_sync: 进度回调异常（不影响同步）", exc_info=True
                )

    return wrapped


def _empty_kb_result(mode: str) -> dict[str, Any]:
    return {
        "ok": False,
        "kb_dir": "",
        "generated_at": "",
        "documents_total": 0,
        "added": 0,
        "changed": 0,
        "removed": 0,
        "skipped": 0,
        "chunks": 0,
        "metadata_refreshed": 0,
        "reconcile_status": "ok",
        "reconcile_missing": 0,
        "reconcile_extra": 0,
        "reconcile_held": 0,
        "metadata_status": "not_attempted",
        "metadata_gaps": 0,
        "metadata_probed": 0,
        "metadata_with_time": 0,
        "mode": mode,
        "embed": False,
        "embed_done": 0,
        "embed_pending": 0,
        # after 三件的「本轮是否真测过」标记（2026-09-27 汇总默认 0 修复，甲案
        # 评估后的乙式收口）：total_after/embedded_after/documents_after 只在
        # 成功路径的统计点被真测一次回填；失败出口（cancelled/exception/
        # kb_missing/config_missing）从未回填——落盘摘要必须报「未测得 null」
        # 而不是把构造期默认 0 伪装成测得的 0（读 WebUI/进度页的人会把
        # "没测"读成"测得 0"）。标记只进结果字典与 _sync_summary 的判据，
        # 不作为独立键落库；内存里三件仍是 int 默认，既有直读结果字典的
        # 消费方（CLI/调度日志）逐字节不受影响。
        # 为什么不在失败出口补测一次：真身计数口 store.stats() 是块表两发
        # COUNT、document_count() 是台账全表 COUNT，取证席实测维基库冷缓存
        # 一发 ≈5.5 分钟——分钟级阻塞查询禁入失败路径（取消轮尤其：停机
        # 钩子触发的取消若在 finally 里现算，等于拖住 shutdown）。
        "after_stats_measured": False,
        "total_after": 0,
        "embedded_after": 0,
        "documents_after": 0,
        "ann_built": False,
        "ann_vectors": 0,
        "ann_reason": "not_attempted",
        "active_base_url": "",
        "active_model": "",
        "error_kind": "none",
        "public_message": "",
        "started_at": "",
        "duration_ms": 0,
    }


# ---------------------------------------------------------------- 同步可观测性
# 用户口径「全程静默」= 不打扰聊天会话，不等于无痕：每轮 summary 落
# knowledge_meta（WebUI 知识页只读消费），失败/部分失败经告警接入口出五要素预警。

# 告警投递回调（AlertContent -> sink）由装配期注入（root __init__.py）；
# 缺省 None 时退回 WARNING 日志，与注入前的旧行为完全一致。
_SYNC_ALERT_SINK: Callable[[Any], None] | None = None
_SYNC_ALERT_SINK_LOCK = threading.Lock()

# 需要告警的失败面：cancelled/busy 是治理动作而非故障，不进告警。
_ALERTABLE_ERROR_KINDS = frozenset({"exception", "kb_missing", "config_missing", "partial"})
# ANN 内存门的跳过面（S112）：同步本身成功、但重建被门挡下也必须告警——
# 静默跳过等于把"新内容今晚仍然检索不到"这件事藏起来（09-22 停摆的前置形态
# 就是这么攒出来的）。这三个 reason 由 vector_knowledge.build_ann_index 如实返回。
_ALERTABLE_ANN_REASONS = frozenset(
    {"insufficient_memory", "memory_probe_unavailable", "insufficient_memory_midway"}
)
# 告警五要素里的「位置」：定位到模块，不暴露磁盘路径（出站另有统一打码）。
_SYNC_ALERT_LOCATION = "bot_unified_runtime.domains.location.knowledge.kb_wiki"


def set_kb_sync_alert_sink(sink: Callable[[Any], None] | None) -> None:
    """注入 kb-sync 告警投递回调（``alerts.build_alert_content_sink`` 的产物）。

    传 None 撤销注入（回到只打日志）。sink 内部异常一律被吞：告警链路故障
    绝不把同步任务一起拖下水。
    """
    global _SYNC_ALERT_SINK
    with _SYNC_ALERT_SINK_LOCK:
        _SYNC_ALERT_SINK = sink


def current_kb_sync_alert_sink() -> Callable[[Any], None] | None:
    with _SYNC_ALERT_SINK_LOCK:
        return _SYNC_ALERT_SINK


def build_sync_alert_content(result: dict[str, Any], *, suspended: bool = False) -> Any:
    """同步失败摘要 → 五要素预警内容（``alerts.AlertContent``，延迟导入）。

    ``suspended=True`` 时是「对账挂起删除」而非同步失败：单独一套话术，
    讲清「为什么没删」而不是让人以为同步炸了。

    域隔离纪律：monitor 属 ops 域，本模块只在真正要告警时才导入，
    避免 location 域装配期反向依赖 ops 域。
    """
    from plugins.bot_unified_runtime.domains.ops.monitor.alerts import AlertContent

    if suspended:
        return AlertContent(
            title="知识库对账挂起：清单疑似按子集导出",
            what_happened=(
                "kb-sync 台账里有 "
                f"{int(result.get('reconcile_held') or 0)} 个文档在本轮 "
                "manifest.entries 中查无，但它们所属语料域本轮未被导出——"
                "删除已挂起，未动任何数据。"
            ),
            impact=(
                "被挂起的文档继续留在台账与向量库里可被检索；若确属上游已删除"
                "词条，会有过期内容残留（不会误删整域，风险方向是「留」不是「丢」）。"
            ),
            fix_suggestion=(
                "确认爬虫本轮是否带 topics 子集导出；改回全量导出后下一轮自动补齐删除。"
            ),
            location=_SYNC_ALERT_LOCATION,
            level="warning",
        )
    error_kind = str(result.get("error_kind") or "none")
    message = str(result.get("public_message") or "")[:400]
    return AlertContent(
        title="Crawl Wiki 知识库同步未跑通",
        what_happened=f"kb-sync（{result.get('mode')}）失败，error_kind={error_kind}：{message}",
        impact=(
            "聊天链路仍在用上一次同步成功的语料，回答不受影响，但知识新鲜度"
            "停在上一轮；连续多日失败会让百科类回答持续过时。"
        ),
        fix_suggestion=(
            "看 WebUI 知识页「上次同步」详情或日志 kb_wiki_sync 行；"
            "语料/清单缺失查 BOT_KB_WIKI_ROOT 导出目录，嵌入链失败查 Ollama"
            "（BOT_EMBEDDING_LOCAL_*），随后 dev.ps1 -Task kb-sync 手动补跑。"
        ),
        location=_SYNC_ALERT_LOCATION,
        level="critical" if error_kind == "exception" else "warning",
    )


def build_ann_memory_alert_content(result: dict[str, Any]) -> Any:
    """ANN 重建被内存门挡下 → 五要素预警（S112；``AlertContent`` 延迟导入）。

    话术三条硬要求（简报口径）：**实算了多少 / 阈值多少 / 下一发怎么手动放行**，
    三条都要在卡面上，否则读到的人只会问"那我该怎么办"。数字全部来自
    `vector_knowledge` 门自己产出的度量字典，本函数一字不重算。

    口径修正（S139 缺陷 1）：`floor` 那枚 4.5 GiB 在卡面与 observed 话术里
    曾被写成"绝对下限"——它是 S85 在 766,126 条标定点上的**经验合价（标定值）**，
    需求式是全比例模型、不设绝对门槛（真身注释 `_ANN_BUILD_MIN_AVAILABLE_BYTES`）。
    阈值类文案不得把标定说成物理下限（本仓口径），现措辞以"标定"点名。

    升格（S139 缺陷 4）：度量里 `consecutive_skips` ≥ 真身阈值
    （`_ANN_MEMORY_SKIP_ESCALATION_ROUNDS`，读自 vector_knowledge，不在本模块
    抄第二枚数）⇒ level 升 critical 并点名"连续 N 轮"——长期饿死不许再以
    warning 的音量混过去。level 参与抑制键（location+level+管理员），升级
    天然跳出旧 warning 桶，仍是同一把抑制器、同一本账。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.character.vector_knowledge import (
        _ANN_MEMORY_SKIP_ESCALATION_ROUNDS,
    )
    from plugins.bot_unified_runtime.domains.ops.monitor.alerts import AlertContent

    gate = result.get("ann_memory_gate")
    metrics = gate if isinstance(gate, dict) else {}
    available = str(metrics.get("available") or "未取到")
    required = str(metrics.get("required") or "未取到")
    floor = str(metrics.get("floor") or "未取到")
    headroom = str(metrics.get("headroom") or "未取到")
    vectors = metrics.get("expected_vectors")
    dim = metrics.get("dim")
    probe_failed = bool(metrics.get("probe_failed"))
    reason = str(result.get("ann_reason") or "")
    midway = reason == "insufficient_memory_midway"
    try:
        consecutive = int(metrics.get("consecutive_skips") or 0)
    except (TypeError, ValueError):
        consecutive = 0
    escalated = consecutive >= _ANN_MEMORY_SKIP_ESCALATION_ROUNDS
    measured = (
        "可用物理内存探针取不到数（按不可判定 fail-closed，未开火）"
        if probe_failed
        else f"实测可用物理内存 {available}"
    )
    return AlertContent(
        title="百科知识库 ANN 索引本轮没有重建（内存门）"
        + ("：中途收火" if midway else "")
        + (f"：已连续 {consecutive} 轮" if escalated else ""),
        what_happened=(
            f"kb-sync（{result.get('mode')}）本身跑通了，但 ANN 全量重建被内存门"
            f"挡下：{measured}，本轮需要 {required}"
            f"（全比例线性计价 + 观察余量 {headroom}"
            + (
                f"，按计数戳上界 {vectors} 条 × {dim} 维估）"
                if vectors
                else "，规模无从估定，按活体下限判）"
            )
            + (
                f"；已装 {result.get('ann_vectors_built_before_abort', 0)} 条时收火，"
                "未 publish、线上索引一字未动"
                if midway
                else "；开火前即跳过，线上索引一字未动"
            )
            + (
                f"。这已是连续第 {consecutive} 轮被挡"
                f"（≥{_ANN_MEMORY_SKIP_ESCALATION_ROUNDS} 轮升格）——"
                "不是十分钟级水位抖动的一次失手，是持续饿死"
                if escalated
                else ""
            )
        ),
        impact=(
            "本轮新嵌入的向量今晚仍然进不了 ANN——完备性闸照旧拒用索引，"
            "百科检索继续回落暴力扫描（慢而全，正确性不受影响，延迟受影响）。"
            "跳过不等于恢复：只有下一次重建成功 publish 才会重新放行 ANN"
            + (
                f"；卡面参考值 {floor} 是 S85 在 766,126 条标定点上的经验合价"
                "（标定值，不是绝对下限），需求随条数线性走、不设绝对门槛。"
                if floor != "未取到"
                else "。"
            )
        ),
        fix_suggestion=(
            "①等这台机器空出可用物理内存到上述需求之上（夜间档错开爬虫与 bot），"
            "下一轮同步会自动补建；②要立刻补跑，用 operator CLI："
            "powershell -File scripts/dev.ps1 -Task kb-sync 加 --ann-force-low-memory"
            "（显式越门，越门本身另记一条痕，OOM 风险由越门者承担；"
            "knowledge-sync 任务同旗同门，越门轮也可取消）；"
            "③要看上一轮门到底量到了什么（含连续被挡计数）：读 knowledge_meta 的 "
            "ann_build_last_memory_skip 一行——重启预检第 13 项 ann_pair "
            "（scripts/pre_restart_check.py）现读此行并派生 MEMORY_SKIP 状态。"
        ),
        location=_SYNC_ALERT_LOCATION,
        level="critical" if escalated else "warning",
    )


def _emit_sync_alert(result: dict[str, Any]) -> None:
    """按 error_kind / 对账挂起 / ANN 内存门决定是否告警；fail-open，绝不影响同步主链路。"""
    try:
        error_kind = str(result.get("error_kind") or "none")
        failed = error_kind in _ALERTABLE_ERROR_KINDS
        suspended = str(result.get("reconcile_status") or "") == _RECONCILE_REMOVE_SUSPENDED
        ann_memory_skip = str(result.get("ann_reason") or "") in _ALERTABLE_ANN_REASONS
        if not failed and not suspended and not ann_memory_skip:
            return
        if not failed and not suspended and ann_memory_skip:
            # 内存门跳过：同步本身成功，走专用话术（要点是"实算/阈值/怎么放行"，
            # 不是"跑挂了"）。
            alert = build_ann_memory_alert_content(result)
        else:
            alert = build_sync_alert_content(result, suspended=not failed and suspended)
        sink = current_kb_sync_alert_sink()
        if sink is None:
            logger.warning(
                "kb_wiki_sync 需要关注（未注入告警 sink）：%s",
                alert.format_message(),
            )
            return
        sink(alert)
    except Exception:
        logger.debug("kb_wiki_sync: 告警投递失败（不影响同步）", exc_info=True)


def _fts_status_snapshot(store: object) -> tuple[int, str]:
    """取本轮关键词通道的 (行数, 签名前缀) —— 取数只走一个真身。

    行数和签名一律由 `store.fts_index_status()` 交回（`vector_knowledge` 那边
    是唯一真身：真表 COUNT + 真 meta 行）。本模块**不**自己 COUNT 一遍——两处
    取数迟早漂成两个数，而这两个数是要上告警面给人做判断的。
    替身/旧 store 没有这个方法、或它自己炸了 ⇒ 如实报 (0, "")：观测面故障
    绝不牵连同步结论（fail-open），也不许造数。
    只在维护线程调用：那次 COUNT 在数十万行的表上是实打实的全表计数，
    绝不允许被搬进检索请求路径（禁区锁 tests/test_kb_pricing_guard_fts_s159.py
    ::test_fts_status_never_on_request_path 钉的是 store 那一侧，本函数是它
    唯一的读点之一，别在别处再挂一次）。
    """
    getter = getattr(store, "fts_index_status", None)
    if not callable(getter):
        return 0, ""
    try:
        status = getter()
    except Exception as exc:  # noqa: BLE001 - 观测面故障不牵连同步（fail-open）。
        logger.warning(
            "kb-sync 读关键词通道状态失败（不影响本轮结论）：%s: %s",
            type(exc).__name__,
            exc,
        )
        return 0, ""
    if not isinstance(status, dict):
        return 0, ""
    try:
        rows = max(0, int(status.get("rows") or 0))
    except (TypeError, ValueError):
        rows = 0
    return rows, str(status.get("signature") or "")[:16]


def _sync_summary(result: dict[str, Any]) -> dict[str, Any]:
    """同步结果 → 落库摘要（固定观测字段集，不放任何磁盘路径）。

    after 三件（documents/chunks/embedded）是三态：int=本轮统计点真测值；
    null=本轮从未到达统计点（失败出口）。「未测得」绝不落成 0——0 是合法
    测得值，混写会把观测缺失误读成库被清空（2026-09-26 取证定案）。
    外部手工构造、不带 `after_stats_measured` 键的结果字典按"已测"透传，
    与既有测试夹具/直调 `run_knowledge_sync` 的旧形状逐字节兼容。
    """
    measured = bool(result.get("after_stats_measured", True))

    def _after_or_null(value: Any) -> int | None:
        return None if not measured else int(value or 0)

    return {
        "started_at": str(result.get("started_at") or ""),
        "finished_at": _utc_stamp(),
        "mode": result.get("mode"),
        "ok": bool(result.get("ok")),
        "error_kind": result.get("error_kind"),
        "duration_ms": int(result.get("duration_ms") or 0),
        "added": int(result.get("added") or 0),
        "changed": int(result.get("changed") or 0),
        "removed": int(result.get("removed") or 0),
        "skipped": int(result.get("skipped") or 0),
        "chunks": int(result.get("chunks") or 0),
        "embedded": int(result.get("embed_done") or 0),
        "embed_pending": int(result.get("embed_pending") or 0),
        "ann_rebuilt": bool(result.get("ann_built")),
        "ann_reason": str(result.get("ann_reason") or ""),
        # 关键词通道三件（S159 要求③「可见」）：ANN 被内存门挡下的那一轮 FTS
        # 照常被喂，但报不出来就等于没喂——只报布尔不够，行数与签名才分得开
        # "建了且装满" 与 "建了个空表"。签名只落前 16 位（指纹用途，全值在
        # knowledge_meta 的 fts_signature 行里），行数是真表 COUNT 的原值。
        "fts_built": bool(result.get("fts_built")),
        "fts_rows": int(result.get("fts_rows") or 0),
        "fts_signature": str(result.get("fts_signature") or ""),
        "documents_after": _after_or_null(result.get("documents_after")),
        "chunks_after": _after_or_null(result.get("total_after")),
        "embedded_after": _after_or_null(result.get("embedded_after")),
        "reconcile_status": str(result.get("reconcile_status") or ""),
        "reconcile_missing": int(result.get("reconcile_missing") or 0),
        "reconcile_extra": int(result.get("reconcile_extra") or 0),
        "reconcile_held": int(result.get("reconcile_held") or 0),
        "metadata_status": str(result.get("metadata_status") or ""),
        "metadata_gaps": int(result.get("metadata_gaps") or 0),
        "metadata_probed": int(result.get("metadata_probed") or 0),
        "metadata_with_time": int(result.get("metadata_with_time") or 0),
        "metadata_refreshed": int(result.get("metadata_refreshed") or 0),
        "generated_at": str(result.get("generated_at") or ""),
        "documents_total": int(result.get("documents_total") or 0),
        "public_message": str(result.get("public_message") or "")[:400],
    }


def _persist_sync_summary(store: SqliteVectorKnowledgeStore, result: dict[str, Any]) -> None:
    """摘要落 knowledge_meta（单行 JSON，UPSERT 幂等）；fail-open。

    只读观测面（WebUI 知识页）用同一张表的同一把 key，任何写失败都只记日志：
    可观测性缺一条记录，绝不能把已经跑完的同步判成失败。
    """
    setter = getattr(store, "set_meta", None)
    if not callable(setter):
        return
    try:
        setter(SYNC_SUMMARY_META_KEY, json.dumps(_sync_summary(result), ensure_ascii=False))
    except Exception:
        logger.debug("kb_wiki_sync: 同步摘要落库失败（不影响同步）", exc_info=True)


def read_kb_sync_summary(store: SqliteVectorKnowledgeStore) -> dict[str, Any]:
    """读出最近一轮同步摘要；无记录/JSON 损坏一律返回空字典（不猜）。"""
    getter = getattr(store, "get_meta", None)
    if not callable(getter):
        return {}
    try:
        raw = str(getter(SYNC_SUMMARY_META_KEY) or "")
    except Exception:  # noqa: BLE001 - 读观测面失败按无记录降级。
        return {}
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _refresh_kb_metadata_if_needed(
    store: SqliteVectorKnowledgeStore, config: object, result: dict[str, Any]
) -> None:
    """台账有未回填文档时跑一次零嵌入元数据刷新（首晚一次性，之后毫秒级跳过）。"""
    counter = getattr(store, "documents_missing_metadata", None)
    refresher = getattr(store, "sync_document_metadata", None)
    if not callable(counter) or not callable(refresher):
        result["metadata_status"] = "unsupported_store"
        return
    try:
        _raise_if_cancelled()
        gaps = int(counter())
        result["metadata_gaps"] = gaps
        if gaps <= 0:
            result["metadata_status"] = "not_needed"
            return
        _root, kb_dir = kb_paths(config)
        # 有界窗口计数判「语料侧到底带不带时间字段」：不再让首行一行样本给全库
        # 背书。probed/with_time 与状态同行透出，下次读数的人看得到判据依据。
        probe = probe_corpus_time_fields(kb_dir, topics=parse_topics(config))
        result["metadata_probed"] = int(probe["probed"])
        result["metadata_with_time"] = int(probe["with_time"])
        if not probe["has_fields"]:
            # 窗口内确实没有（或只有撑不过阈值的杂散噪声）：现在扫全表也扫不出
            # 东西，记下原因与样本口径，等下一轮导出带上时间字段再回填。
            # 绝不硬刷——刷出来的是一库假 NULL，比"没刷"更难被发现。
            result["metadata_status"] = "skipped_corpus_without_time_fields"
            return
        stats = refresh_kb_metadata(store, config)
        result["metadata_status"] = "ok"
        result["metadata_refreshed"] = int(stats.get("refreshed", 0) or 0)
        result["metadata_matched"] = int(stats.get("matched", 0) or 0)
        result["metadata_missing"] = int(stats.get("missing", 0) or 0)
        result["metadata_stale"] = int(stats.get("stale", 0) or 0)
    except KbSyncCancelled:
        raise
    except Exception as exc:
        result["metadata_status"] = f"error:{type(exc).__name__}"
        logger.debug("kb_wiki_sync: 时间元数据回填失败", exc_info=True)


def run_kb_sync_task(
    config: object,
    *,
    full: bool = False,
    embed: bool = True,
    store: SqliteVectorKnowledgeStore | None = None,
    on_progress: Callable[[dict], None] | None = None,
    embed_progress: Callable[[int, int], None] | None = None,
    force_low_memory_ann: bool = False,
) -> dict[str, Any]:
    """kb-sync 任务入口：任务互斥 + 取消事件复位后进入主体。

    两个调度 job-id（``kb_wiki_sync_daily`` 夜间 23:40 与
    ``kb_wiki_sync_startup`` 启动 +45s）可并发触发；这里用进程级互斥闸
    保证同一时刻最多一个同步在跑，撞车方立即返回 ``error_kind=busy``
    （断点都在库里，下轮自然续跑，不空转不重活）。

    ``force_low_memory_ann`` 是 operator 显式越过 ANN 内存门的唯一通路
    （S112）：调度器/cron 一律用缺省 False，只有 CLI 旗会带 True 进来。
    告警话术里"下一发怎么手动放行"点名的就是它——写进话术的通路必须真存在。
    """
    if not _SYNC_TASK_MUTEX.acquire(blocking=False):
        busy = _empty_kb_result("full" if full else "incremental")
        busy["embed"] = bool(embed)
        busy["error_kind"] = "busy"
        busy["public_message"] = (
            "已有 kb-sync 任务在跑（启动补同步/夜间同步互斥），本次跳过；"
            "断点续跑语义不变。"
        )
        return busy
    try:
        return _run_kb_sync_task_locked(
            config,
            full=full,
            embed=embed,
            store=store,
            on_progress=on_progress,
            embed_progress=embed_progress,
            force_low_memory_ann=force_low_memory_ann,
        )
    finally:
        # 出口消费取消状态：本轮的取消请求（无论入口还是批边界命中）
        # 不残留到下一轮；陈旧置位最多取消一轮，不毒化后续夜间同步。
        # 旗路径同理归还：不在跑的轮次不许继续监听某个目录（那会把下一轮
        # 之前偶然出现的同名文件当成取消请求）。
        _SYNC_CANCEL_EVENT.clear()
        _set_kb_sync_cancel_flag_path(None)
        _SYNC_TASK_MUTEX.release()


def _run_kb_sync_task_locked(
    config: object,
    *,
    full: bool = False,
    embed: bool = True,
    store: SqliteVectorKnowledgeStore | None = None,
    on_progress: Callable[[dict], None] | None = None,
    embed_progress: Callable[[int, int], None] | None = None,
    force_low_memory_ann: bool = False,
) -> dict[str, Any]:
    """kb-sync 任务主体（持 _SYNC_TASK_MUTEX）：同步 → 嵌入 → ANN/FTS 索引重建。

    scheduler（进程内）传 ``store=共享实例``，同步完成后检索器即时可见；
    CLI（独立进程）不传 store，用 auto_reset=True 的临时实例，
    嵌入模型/端点指纹变化时可自动清空重嵌。

    R3 停摆批：全链协作式可取消——批次边界检查取消事件（同步每 500 文档、
    嵌入每批），取消即穿透抛出，落库断点保留（重跑自动续传）。

    元数据批（2026-09-20）：同步之后追加一次**零嵌入成本**的台账时间元数据
    回填（仅当台账存在未回填文档时）；无论走哪条出口，finally 一律把本轮
    summary 落 ``knowledge_meta`` 并按需告警——「全程静默」指的是不打扰会话，
    不是无痕。busy 轮次没有 store 可用（互斥闸外就返回），不覆盖上一轮真记录。
    """
    result: dict[str, Any] = _empty_kb_result("full" if full else "incremental")
    result["embed"] = bool(embed)
    result["started_at"] = _utc_stamp()
    started = time.monotonic()
    # 取消旗登记（S112）：必须在**第一个取消检查点之前**登记，否则入口那一发
    # `_raise_if_cancelled` 看不见旗——"存在但不被消费"正是本席要注毒验的形状。
    _set_kb_sync_cancel_flag_path(kb_sync_cancel_flag_path(_kb_db_path(config)))
    flag = current_kb_sync_cancel_flag_path()
    logger.info(
        "kb_wiki_sync: 本轮监听取消旗 %s（放这个文件即可在下一个批边界停）",
        flag,
    )
    try:
        _raise_if_cancelled()
        if store is None:
            if not _embedding_chain_ready(config):
                result["error_kind"] = "config_missing"
                result["public_message"] = (
                    "缺少嵌入链配置：BOT_EMBEDDING_ENABLED 且至少配置本地链"
                    "（BOT_EMBEDDING_LOCAL_MODELS/BASE_URL）或远程链。"
                )
                return result
            store = _build_store(config, auto_reset=True)
        # 共享实例的常态 provider 可能带检索短超时（fast 模式 3s）：
        # 嵌入批次换全长超时 provider，结束还原，期间查询嵌入不受影响。
        provider = _build_provider(config)
        restore_provider = store.embed_provider
        store.embed_provider = provider
        try:
            sync = sync_kb_wiki(
                store,
                config,
                full=full,
                on_progress=_cancel_aware_progress(on_progress),
            )
            result.update(sync)
            if embed:
                # 本地 Ollama 实测批 128 吞吐最高（19 块/s vs 批 10 的 3 块/s）。
                # 批大小要和嵌入超时成配比看：128 块 ≈6.7s，而生产 .env 的本地超时
                # 只有 5s ⇒ 每批必超时。嵌入侧按批折半自调（下限 10，恰好也是远程
                # 单批上限），所以这里只传"想要的"批大小，不必为超时链路配平兜底。
                batch = max(
                    1, int(getattr(config, "bot_kb_wiki_embed_batch", 128) or 128)
                )
                done, pending = store.embed_pending(
                    None,
                    on_progress=_cancel_aware_progress(embed_progress),
                    batch_size=batch,
                )
                result["embed_done"] = int(done)
                result["embed_pending"] = int(pending)
        finally:
            store.embed_provider = restore_provider
        # 首晚零嵌入成本的时间元数据回填（正文同步一结束就做，向量与 hash 不动；
        # 台账已全量带时间时 documents_missing_metadata()=0，毫秒级跳过）。
        _refresh_kb_metadata_if_needed(store, config, result)
        stats = store.stats()
        result["total_after"] = int(stats["total"])
        result["embedded_after"] = int(stats["embedded"])
        result["documents_after"] = store.document_count()
        # 统计点已过：after 三件自此是"本轮真测值"，落盘摘要不再置 null。
        # （partial 早退在本行之后 ⇒ 那轮的三件本就是测得值，照常上账。）
        result["after_stats_measured"] = True
        # ANN 重建门（R3 停摆批）：零变更夜不再无条件重建（实测 23.8 万块
        # 全量重建 8.5 分钟、占事件循环默认线程池线程）。重建仅当：
        # ①文档集合有增/改/删；②本次嵌入了新向量；③ANN 索引文件缺失
        #（历史 healing 语义保留：索引被删后下一轮同步补建）。
        # 模型指纹变化的 healing 走 CLI 全量重建（auto_reset 重嵌），不在此列。
        _raise_if_cancelled()
        sync_changed = (
            int(result.get("added", 0) or 0)
            + int(result.get("changed", 0) or 0)
            + int(result.get("removed", 0) or 0)
        ) > 0
        vectors_changed = int(result.get("embed_done", 0) or 0) > 0
        ann_files_exist = bool(store.ann_index_path) and bool(
            store.ann_order_path
        ) and Path(store.ann_index_path).is_file() and Path(
            store.ann_order_path
        ).is_file()
        if stats["embedded"] > 0 and (
            sync_changed or vectors_changed or not ann_files_exist
        ):
            try:
                # on_progress 双重用途（S112 + S105 乙-3）：① wiki 侧重建此前
                # 全程零进度输出（`_build_ann_index_locked` 只在传了回调时打点），
                # 分钟级任务跑成什么样外部全盲；② 用 `_cancel_aware_progress`
                # 包一层，取消检查点就延伸到**建索引自己的批边界**上——
                # `KbSyncCancelled` 继承 BaseException，能穿透内层
                # `except Exception: pass`（见 vector_knowledge 同处注释），
                # 而此刻尚未 publish，中停不碰线上文件。
                ann = store.build_ann_index(
                    force_low_memory=bool(force_low_memory_ann),
                    on_progress=_cancel_aware_progress(
                        lambda built: logger.info(
                            "kb_wiki_sync: ANN 重建进度 已装 %s 条", built
                        )
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                # 发现5 补留痕（同文件计数戳自愈告警同款口径）：只记异常类型与
                # 异常原文，不记任何正文；reason 结构一字不动（常驻锁口径）。
                logger.warning(
                    "kb-sync ANN 重建失败（reason 只记类名，明细见本行）：%s: %s",
                    type(exc).__name__,
                    exc,
                )
                ann = {"built": False, "reason": type(exc).__name__}
            result["ann_built"] = bool(ann.get("built"))
            result["ann_vectors"] = int(ann.get("vectors", 0) or 0)
            result["ann_reason"] = str(ann.get("reason", ""))
            # 内存门的度量原样带进本轮结果（S112）：告警话术与落库摘要都读它，
            # 本模块不重算任何一个字节（重算=第二口径）。
            gate_metrics = ann.get("memory_gate")
            if isinstance(gate_metrics, dict):
                result["ann_memory_gate"] = gate_metrics
                result["ann_vectors_built_before_abort"] = int(
                    ann.get("vectors_built_before_abort", 0) or 0
                )
        else:
            result["ann_built"] = False
            result["ann_vectors"] = 0
            result["ann_reason"] = "unchanged_skip"
            # 零变更夜的完备性戳自愈（#47 闸闭环，certify-prewarm 波 P1）：
            # 戳的权威落点在发布提交点、涨点在补嵌——零变更夜两者都不达；
            # 无戳 ⇒ ANN 永远按「unstamped」拒用、每问付暴力回落（248k 块实测
            # 稳态 +3.6s、每问再涨 ~1GB 驻留）。这里在维护线程做一次权威 COUNT
            # 补盖（仅当无戳；活戳归重建线所有，一字不碰；实测 13-33s，只此
            # 一路，绝不上请求路径）。替身/旧 store 无此方法时如实跳过。
            _certify = getattr(store, "certify_expected_vector_count", None)
            if callable(_certify):
                try:
                    # 零变更夜必须开漂移纠偏：戳是只涨不跌的上界，删行/换代都不拉低它，
                    # 而这一夜重建线不达 ⇒ 不开门的话「虚高一次」就是「永久拒用」。
                    # 2026-09-26 生产实测即这一格（戳 741,428 / 索引与库都是 740,996）。
                    # 判据与闭集见 vector_knowledge 的常量块与 reconcile 方法 docstring。
                    result["ann_certified"] = _certify(drift_correction=True)
                except Exception as exc:  # noqa: BLE001 - 自愈失败不改本轮同步结论。
                    logger.warning(
                        "kb-sync ANN 计数戳自愈失败（不影响本轮结论）：%s: %s",
                        type(exc).__name__,
                        exc,
                    )
        # 关键词通道（FTS）在 kb-sync 收尾处无条件幂等确保一次 —— 兑现本模块
        # _build_store 那句「重建由 kb-sync 负责」（fts_auto_rebuild=False 的检索
        # 进程故意不内联建，见 vector_knowledge.py:3776）。此前 force=True 的 FTS
        # 构建只有两个落点、都在 build_ann_index 之内：faiss 缺失分支
        # （vector_knowledge.py:2776）与 ANN 成功 publish 之后（:3125）。而下面的
        # ANN 重建门在「零变更夜」（sync_changed、vectors_changed、not
        # ann_files_exist 三条件全 false）整个跳过 build_ann_index、只补一枚完备性
        # 戳（certify），压根不碰 FTS ⇒ 维基库一旦错过有 ANN 重建的那一夜，之后
        # 每夜都零变更就每夜都不建 FTS，关键词通道恒 0 行（本席实测：维基库
        # knowledge_chunks_fts=0、无 fts_signature，而个人库同名表 35283 行满）。
        # ensure_fts_index(force=True) 幂等：签名对上即快返回 True，非重建夜只是一
        # 次 meta 比对；内容变更时 sync 已清签名（sync_documents/_invalidate_fts），
        # 此处真正重建。放这里覆盖调度器夜间 job / 启动 job / operator CLI 全路径。
        # S159 要求③「可见」：光报布尔分不清"建了且装满"与"建了个空表"，故把
        # 行数与签名一并上账（取数走 `store.fts_index_status()` 唯一真身，
        # 本模块不 COUNT 第二遍）；失败原因单独留一手，绝不静默吞。
        fts_failure = ""
        try:
            result["fts_built"] = bool(store.ensure_fts_index(force=True))
            result["fts_rows"], result["fts_signature"] = _fts_status_snapshot(store)
        except Exception as exc:  # noqa: BLE001 - 关键词通道重建失败不改本轮同步结论。
            logger.warning(
                "kb-sync FTS 收尾重建失败（不影响本轮结论）：%s: %s",
                type(exc).__name__,
                exc,
            )
            result["fts_built"] = False
            result["fts_rows"] = 0
            result["fts_signature"] = ""
            fts_failure = f"{type(exc).__name__}: {exc}"
        result["active_base_url"] = str(getattr(provider, "active_base_url", "") or "")
        result["active_model"] = str(getattr(provider, "active_model", "") or "")
        if embed and result["embed_pending"] > result["embed_done"]:
            result["error_kind"] = "partial"
            result["public_message"] = (
                f"嵌入只完成 {result['embed_done']}/{result['embed_pending']} 行，"
                "请检查 Ollama/嵌入端点后重跑（断点续跑，已完成行自动跳过）。"
            )
            return result
        result["ok"] = True
        observed: list[str] = []
        if str(result.get("ann_reason") or "") in _ALERTABLE_ANN_REASONS:
            # 内存门跳过的话术要点：实算了多少 / 阈值多少 / 下一发怎么放行。
            # 口径修正（S139 缺陷 1）：floor 那枚是 S85 标定合价，不是绝对下限
            # ——旧话术把它写成"下限+余量"的组成式，与真身全比例模型不符。
            gate = result.get("ann_memory_gate")
            metrics = gate if isinstance(gate, dict) else {}
            try:
                _consec = int(metrics.get("consecutive_skips") or 0)
            except (TypeError, ValueError):
                _consec = 0
            observed.append(
                "ANN 本轮未重建（内存门，"
                f"{result.get('ann_reason')}）：实测可用 "
                f"{metrics.get('available') or '未取到'}，需要 "
                f"{metrics.get('required') or '未取到'}"
                f"（全比例线性计价 + 观察余量 "
                f"{metrics.get('headroom') or '未取到'}；{metrics.get('floor') or '未取到'} "
                "系 S85 标定合价、不是绝对下限）"
                + (f"，已连续 {_consec} 轮被挡" if _consec > 1 else "")
                + "。暴力扫描照旧，"
                "新向量今晚仍进不了 ANN；要立刻补跑用 operator CLI 加 "
                "--ann-force-low-memory（显式越门、另记痕）"
            )
        # 关键词通道一行（S159 要求③）：ANN 那一行报的是"向量没换上"，本行报
        # 的是"关键词这条腿到底喂没喂上"。两件事各报各的，谁也不替谁背锅——
        # 上一轮就是因为它压根不上话术，ANN 被挡顺手把 FTS 一起饿死而无人知晓。
        if fts_failure:
            observed.append(
                f"关键词通道（FTS）本轮没建成：{fts_failure}"
                "（ANN 结论与同步结论都不因此改判，失败只记在这一行）"
            )
        elif result.get("fts_built"):
            observed.append(
                f"关键词通道（FTS）已确保：{result.get('fts_rows')} 行、"
                f"签名前缀 {result.get('fts_signature') or '未取到'}"
            )
        else:
            observed.append(
                "关键词通道（FTS）未建成（ensure_fts_index 返回 False；"
                f"现报行数 {result.get('fts_rows')}）——本轮检索只有向量腿"
            )
        if int(result.get("reconcile_missing") or 0) or int(result.get("reconcile_extra") or 0):
            observed.append(
                f"对账补 {result.get('reconcile_missing')}、删 {result.get('reconcile_extra')}"
            )
        if str(result.get("reconcile_status") or "") == _RECONCILE_REMOVE_SUSPENDED:
            observed.append(f"对账挂起删除 {result.get('reconcile_held')}")
        if int(result.get("metadata_refreshed") or 0):
            observed.append(
                f"时间元数据回填 {result.get('metadata_refreshed')}"
                f"（探针 {result.get('metadata_probed')} 行、{result.get('metadata_with_time')} 行带字段）"
            )
        elif str(result.get("metadata_status") or "").startswith("skipped"):
            # 跳过必须带依据：只写 skipped_* 读起来像"语料本来没这字段"，
            # 把窗口样本量与命中数一起报出来，人才会去查是不是采样问题。
            observed.append(
                f"时间元数据未回填（探针 {result.get('metadata_probed')} 行仅 "
                f"{result.get('metadata_with_time')} 行带时间字段，台账缺口 "
                f"{result.get('metadata_gaps')}）"
            )
        result["public_message"] = (
            f"kb-sync 完成（{result['mode']}）：台账 {result['documents_after']} 文档 / "
            f"{result['total_after']} 块（新增 {result['added']}、变更 {result['changed']}、"
            f"删除 {result['removed']}、跳过 {result['skipped']}）；"
            f"已向量化 {result['embedded_after']}；ANN={result['ann_built']} "
            f"({result['active_base_url']} / {result['active_model']})。"
            + (f" {'；'.join(observed)}。" if observed else "")
        )
        return result
    except KbSyncCancelled:
        # R3 停摆批：协作式取消——落库断点已保留（同步每 500 文档/嵌入每批
        # 均已提交），重跑自动续传；provider 已由内层 finally 还原。
        result["error_kind"] = "cancelled"
        result["public_message"] = (
            "kb-sync 已取消（断点保留，重跑自动续传）。"
        )
        return result
    except FileNotFoundError as exc:
        result["error_kind"] = "kb_missing"
        result["public_message"] = str(exc)
        return result
    except Exception as exc:  # noqa: BLE001
        result["error_kind"] = "exception"
        result["public_message"] = f"kb-sync 异常：{type(exc).__name__}: {exc}"[:400]
        return result
    finally:
        # 可观测性收口（元数据批）：五条出口（含两处提前 return 与三个 except）
        # 都要留痕。落库/告警自身 fail-open，绝不让观测故障改写同步结果或抛出。
        result["duration_ms"] = int((time.monotonic() - started) * 1000)
        if store is not None:
            _persist_sync_summary(store, result)
        _emit_sync_alert(result)
