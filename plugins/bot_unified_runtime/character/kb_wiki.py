"""Crawl Wiki 知识库桥：同步 + 检索器 + 合并检索 + 实时爬降级。

对接 Crawl Wiki 仓库（``bot_kb_wiki_root``，默认 D:\\Coding\\Crawl Wiki）导出的
知识库，协议见该仓库 ``docs/KB_HANDOFF.md``：

- 增量同步读 ``manifest.json`` 三张清单 + ``updates.jsonl`` 变更行，
  按 (doc_id, hash) 幂等（``SqliteVectorKnowledgeStore.sync_documents``）；
- 初次灌库/定期对账（``full=True``）流式逐行读 ``documents.jsonl``（237MB，
  常驻内存 O(1)），中断重跑自动续传；
- 分块按 Markdown 标题分节，每块携带「词条标题｜节标题」前缀做嵌入上下文；
- 嵌入复用 OpenAICompatibleEmbeddingProvider（本地 Ollama bge-m3 优先，
  远程付费链兜底）；向量库独立于人格知识库（``bot_kb_wiki_db_path``），
  两边的文件清单删除语义互不干扰；
- 聊天链路经 ``MergedKnowledgeRetriever`` 把人格知识块与 wiki 知识块
  轮询交错注入 prompt（人格知识优先）。

未做：检索不到时的自动实时爬降级。``realtime_lookup`` 仅作预留工具，
不接进聊天链路（单页 3-10 秒 + 目标站反爬礼节，需人工决策频率）。
"""

from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any

from .vector_knowledge import (
    OpenAICompatibleEmbeddingProvider,
    SqliteVectorKnowledgeStore,
    _UnavailableVectorKnowledgeProvider,
)

_KB_SUBDIR = Path("crawl_output") / "knowledge_base"
_SOURCE_LABELS = {
    "moegirl": "萌娘百科",
    "wikipedia_zh": "维基百科",
    "baidu_baike": "百度百科",
}

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
    if full:
        docs: Iterable[dict] = (
            _to_sync_doc(row, chunk_chars=chunk_chars)
            for row in iter_kb_documents(kb_dir, topics)
        )
    else:
        removed_ids = [
            str(row.get("id") or "")
            for row in iter_kb_updates(kb_dir, topics)
            if str(row.get("op")) == "delete" and str(row.get("id") or "")
        ]
        docs = (
            _to_sync_doc(row, chunk_chars=chunk_chars)
            for row in iter_kb_updates(kb_dir, topics)
            if str(row.get("op")) == "upsert"
        )
        for doc_id in manifest.get("removed", []):
            doc_id = str(doc_id)
            if doc_id and (not topics or _id_topic(doc_id) in topics):
                removed_ids.append(doc_id)

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
        **stats,
    }


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


def run_kb_sync_task(
    config: object,
    *,
    full: bool = False,
    embed: bool = True,
    store: SqliteVectorKnowledgeStore | None = None,
    on_progress: Callable[[dict], None] | None = None,
    embed_progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """kb-sync 任务主体：同步 → 嵌入 → ANN/FTS 索引重建。

    scheduler（进程内）传 ``store=共享实例``，同步完成后检索器即时可见；
    CLI（独立进程）不传 store，用 auto_reset=True 的临时实例，
    嵌入模型/端点指纹变化时可自动清空重嵌。
    """
    result: dict[str, Any] = {
        "ok": False,
        "kb_dir": "",
        "generated_at": "",
        "documents_total": 0,
        "added": 0,
        "changed": 0,
        "removed": 0,
        "skipped": 0,
        "chunks": 0,
        "mode": "full" if full else "incremental",
        "embed": bool(embed),
        "embed_done": 0,
        "embed_pending": 0,
        "total_after": 0,
        "embedded_after": 0,
        "ann_built": False,
        "ann_vectors": 0,
        "ann_reason": "not_attempted",
        "active_base_url": "",
        "active_model": "",
        "error_kind": "none",
        "public_message": "",
    }
    try:
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
            sync = sync_kb_wiki(store, config, full=full, on_progress=on_progress)
            result.update(sync)
            if embed:
                # 本地 Ollama 实测批 128 吞吐最高（19 块/s vs 批 10 的 3 块/s）；
                # 本地不可用退到远程链时远程单批限额(10)会拒绝大批 → 本次中止，
                # 断点续跑，无数据损坏（见 BOT_KB_WIKI_EMBED_BATCH 注释）。
                batch = max(
                    1, int(getattr(config, "bot_kb_wiki_embed_batch", 128) or 128)
                )
                done, pending = store.embed_pending(
                    None, on_progress=embed_progress, batch_size=batch
                )
                result["embed_done"] = int(done)
                result["embed_pending"] = int(pending)
        finally:
            store.embed_provider = restore_provider
        stats = store.stats()
        result["total_after"] = int(stats["total"])
        result["embedded_after"] = int(stats["embedded"])
        result["documents_after"] = store.document_count()
        if stats["embedded"] > 0:
            try:
                ann = store.build_ann_index()
            except Exception as exc:  # noqa: BLE001
                ann = {"built": False, "reason": type(exc).__name__}
            result["ann_built"] = bool(ann.get("built"))
            result["ann_vectors"] = int(ann.get("vectors", 0) or 0)
            result["ann_reason"] = str(ann.get("reason", ""))
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
        result["public_message"] = (
            f"kb-sync 完成（{result['mode']}）：台账 {result['documents_after']} 文档 / "
            f"{result['total_after']} 块（新增 {result['added']}、变更 {result['changed']}、"
            f"删除 {result['removed']}、跳过 {result['skipped']}）；"
            f"已向量化 {result['embedded_after']}；ANN={result['ann_built']} "
            f"({result['active_base_url']} / {result['active_model']})。"
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


# ---------------------------------------------------------------- 实时爬降级（预留）


def realtime_lookup(
    config: object,
    title: str,
    source: str,
    *,
    store: bool = False,
    topic: str = "",
    proxy: str = "none",
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    """知识库没有时单页实时爬取（3-10 秒）。预留工具，未接入聊天链路。

    ``store=True`` 会把结果落盘进 Crawl Wiki 语料树（当晚知识库自动并入）；
    默认纯查询零写入。source 取值如 moegirl / bilibili_wiki_wutheringwaves。
    """
    root, _kb_dir = kb_paths(config)
    python = root / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        return {"status": "error", "error": f"解释器不存在: {python}"}
    args = [
        str(python),
        str(root / "realtime_lookup_cli.py"),
        "--source",
        source,
        "--title",
        title,
        "--proxy",
        proxy,
    ]
    if store:
        args.append("--store")
        if topic:
            args += ["--topic", topic]
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=float(timeout_seconds),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": f"realtime_lookup 超时（{timeout_seconds}s）"}
    except OSError as exc:
        return {"status": "error", "error": f"realtime_lookup 启动失败: {exc}"}
    for line in reversed((proc.stdout or "").strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                break
    return {"status": "error", "error": "无结构化输出", "stdout": (proc.stdout or "")[-400:]}
