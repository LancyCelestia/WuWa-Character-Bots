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
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime
from itertools import chain, islice
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.character.vector_knowledge import (
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


def _build_store(
    config: object,
    *,
    timeout_override: float | None = None,
    auto_reset: bool,
) -> SqliteVectorKnowledgeStore:
    db_path = str(
        getattr(config, "bot_kb_wiki_db_path", "")
        or "data/kb_wiki_embeddings.sqlite3"
    )
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
    db_path = str(
        getattr(config, "bot_kb_wiki_db_path", "")
        or "data/kb_wiki_embeddings.sqlite3"
    )
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
        except Exception:  # noqa: BLE001 - 检索异常按无结果降级，不阻断对话。
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
    """

    available = True

    def __init__(self, retrievers: list) -> None:
        self._retrievers = [
            retriever
            for retriever in retrievers
            if getattr(retriever, "available", True)
        ]

    def retrieve(self, query_text: str) -> list:
        streams: list[list] = []
        for retriever in self._retrievers:
            try:
                streams.append(list(retriever.retrieve(query_text) or []))
            except Exception:  # noqa: BLE001 - 单路失败不影响另一路。
                streams.append([])
        total = sum(len(stream) for stream in streams)
        merged: list = []
        seen: set[str] = set()
        index = 0
        while len(merged) < total:
            progressed = False
            for stream in streams:
                if index >= len(stream):
                    continue
                chunk = stream[index]
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
    if _SYNC_CANCEL_EVENT.is_set():
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


def _emit_sync_alert(result: dict[str, Any]) -> None:
    """按 error_kind / 对账挂起决定是否告警；fail-open，绝不影响同步主链路。"""
    try:
        error_kind = str(result.get("error_kind") or "none")
        failed = error_kind in _ALERTABLE_ERROR_KINDS
        suspended = str(result.get("reconcile_status") or "") == _RECONCILE_REMOVE_SUSPENDED
        if not failed and not suspended:
            return
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


def _sync_summary(result: dict[str, Any]) -> dict[str, Any]:
    """同步结果 → 落库摘要（固定观测字段集，不放任何磁盘路径）。"""
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
        "documents_after": int(result.get("documents_after") or 0),
        "chunks_after": int(result.get("total_after") or 0),
        "embedded_after": int(result.get("embedded_after") or 0),
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
) -> dict[str, Any]:
    """kb-sync 任务入口：任务互斥 + 取消事件复位后进入主体。

    两个调度 job-id（``kb_wiki_sync_daily`` 夜间 23:40 与
    ``kb_wiki_sync_startup`` 启动 +45s）可并发触发；这里用进程级互斥闸
    保证同一时刻最多一个同步在跑，撞车方立即返回 ``error_kind=busy``
    （断点都在库里，下轮自然续跑，不空转不重活）。
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
        )
    finally:
        # 出口消费取消状态：本轮的取消请求（无论入口还是批边界命中）
        # 不残留到下一轮；陈旧置位最多取消一轮，不毒化后续夜间同步。
        _SYNC_CANCEL_EVENT.clear()
        _SYNC_TASK_MUTEX.release()


def _run_kb_sync_task_locked(
    config: object,
    *,
    full: bool = False,
    embed: bool = True,
    store: SqliteVectorKnowledgeStore | None = None,
    on_progress: Callable[[dict], None] | None = None,
    embed_progress: Callable[[int, int], None] | None = None,
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
                ann = store.build_ann_index()
            except Exception as exc:  # noqa: BLE001
                ann = {"built": False, "reason": type(exc).__name__}
            result["ann_built"] = bool(ann.get("built"))
            result["ann_vectors"] = int(ann.get("vectors", 0) or 0)
            result["ann_reason"] = str(ann.get("reason", ""))
        else:
            result["ann_built"] = False
            result["ann_vectors"] = 0
            result["ann_reason"] = "unchanged_skip"
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
