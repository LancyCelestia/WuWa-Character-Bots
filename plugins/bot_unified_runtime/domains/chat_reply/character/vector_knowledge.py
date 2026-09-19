from __future__ import annotations

import hashlib
import json
import re
import struct
import time

try:
    import numpy as np
except Exception:  # noqa: BLE001 - numpy 可选，缺失回退纯 Python 余弦。
    np = None  # type: ignore[assignment]

try:
    import faiss
except Exception:  # noqa: BLE001 - faiss 可选，缺失回退 numpy 暴力检索。
    faiss = None  # type: ignore[assignment]
import sqlite3
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from math import isnan, sqrt
from pathlib import Path
from typing import Any, Protocol, cast

import httpx

from plugins.bot_unified_runtime.contracts import KnowledgeChunk
from plugins.bot_unified_runtime.domains.chat_reply.character.documents import (
    load_character_document,
)

_EMBED_BATCH_SIZE = 10  # 百炼 qwen3.7 上限 20 条、v4 上限 10 条，取 10 两者都兼容。
_MIN_CHUNK_CHARS = 120

# --- BM25 关键词通道 + RRF 混合融合参数 ---------------------------------------
# FTS5 trigram 只能匹配 >=3 字符的 MATCH 词；1~2 字符词退化为 title LIKE。
_FTS_TABLE_NAME = "knowledge_chunks_fts"
_FTS_SIGNATURE_KEY = "fts_signature"
_FTS_CREATE_SQL = (
    f"CREATE VIRTUAL TABLE {_FTS_TABLE_NAME} USING fts5("
    "chunk_id UNINDEXED, title, content, tokenize='trigram'"
    ")"
)
_FTS_MIN_MATCH_CHARS = 3
_RRF_K = 60.0  # RRF 平滑常数：k 越大排名越平滑，越不容易被单一通道霸榜。
_VECTOR_CANDIDATE_FACTOR = 4
_VECTOR_CANDIDATE_FLOOR = 20
_KEYWORD_CANDIDATE_FACTOR = 2

_SHORT_TERM_STOP_CHARS = frozenset("的是在了和与或吗呢么什么有没有只让被把从对向给将")
_MAX_PHRASE_TERMS = 16
_CJK_RE = re.compile(r"[一-鿿]+")
_ALNUM_RE = re.compile(r"[A-Za-z0-9_]{3,}")
# 无任何关键词命中且向量最高余弦低于该阈值 -> 判定未命中（可经构造参数覆盖）。
_MISS_COSINE_THRESHOLD = 0.30

# sync_chunks 源级同步台账（knowledge_meta key 前缀）：按 (mtime,size) 精确
# 删除「曾同步过、已移出清单」的源，取代旧的 `NOT IN (清单)` 全集删除。
_SOURCE_SIG_KEY_PREFIX = "sync_source_sig:"

# 文档台账的时间元数据列（列名是与 Crawl Wiki 导出层的契约，不得自创别名）：
# 语料行的 `updated_at`（上游站点最后编辑时间）→ source_updated_at，
# `crawled_at`（本地抓取落盘时间）→ crawl_at。NULL=本库从未写过该文档的
# 时间元数据（首晚回填据此判定），''=上游确实没有可信时间值（非 MediaWiki 系）。
_DOC_METADATA_COLUMNS = ("source_updated_at", "crawl_at")


class EmbeddingProvider(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """把文本批量编码为等长浮点向量；失败可返回空列表或抛异常。"""
        ...


@dataclass(frozen=True)
class _EmbeddingChain:
    """一个 OpenAI-compatible embeddings 服务端 + 其模型回退列表。"""

    base_url: str
    models: tuple[str, ...]
    api_key: str = ""
    dimensions: int | None = None
    timeout_seconds: float = 15.0


def _parse_model_list(model: str | list[str]) -> list[str]:
    if isinstance(model, str):
        parts = [part.strip() for part in model.split(",") if part.strip()]
    else:
        parts = [str(part).strip() for part in model if str(part).strip()]
    return parts


# 单文本查询嵌入 memo：聊天检索热路径（每条消息至少人格库+kb_wiki 库各一次）
# 对同一 query 的重复嵌入跨库去重；TTL 过后自然失效，不做逐条淘汰。
_QUERY_EMBED_MEMO: dict[tuple[str, str], tuple[float, list[list[float]]]] = {}
_QUERY_EMBED_MEMO_LOCK = threading.Lock()
_QUERY_EMBED_MEMO_TTL_SECONDS = 60.0
_QUERY_EMBED_MEMO_MAX_ENTRIES = 256


def _query_embed_memo_get(key: tuple[str, str]) -> list[list[float]] | None:
    now = time.monotonic()
    with _QUERY_EMBED_MEMO_LOCK:
        hit = _QUERY_EMBED_MEMO.get(key)
    if hit is None or now - hit[0] >= _QUERY_EMBED_MEMO_TTL_SECONDS:
        return None
    return hit[1]


def _query_embed_memo_put(key: tuple[str, str], vectors: list[list[float]]) -> None:
    with _QUERY_EMBED_MEMO_LOCK:
        if len(_QUERY_EMBED_MEMO) >= _QUERY_EMBED_MEMO_MAX_ENTRIES:
            _QUERY_EMBED_MEMO.clear()
        _QUERY_EMBED_MEMO[key] = (
            time.monotonic(),
            [list(vector) for vector in vectors],
        )


def reset_query_embed_memo() -> None:
    """清空查询嵌入 memo（测试用）。"""
    with _QUERY_EMBED_MEMO_LOCK:
        _QUERY_EMBED_MEMO.clear()


# ANN 重建流式读取向量批大小（2048×1024 维 ≈ 8MB/批，替代全量驻留）。
_ANN_BUILD_BATCH_SIZE = 2048
# 检索向量缓存流式读取批大小（R3 停摆批）：旧实现全表 fetchall 会把
# vector_json 文本与 vector_blob 一起物化（kb_wiki 23.8 万块、库文件
# 5.7GB → 进程内存 GB 级尖峰 + 分钟级 JSON 解析，且发生在检索锁内）。
_VECTOR_CACHE_LOAD_BATCH_SIZE = 2048


class OpenAICompatibleEmbeddingProvider:
    """按链顺序请求：本地（如 Ollama bge-m3）优先，远程付费模型兜底。

    每条链内部又可按逗号分隔的模型列表依次回退（如 qwen3.7 配额耗尽换 v4）。
    一旦某条链成功，后续请求优先复用该链（sticky），只有它失败才再切。
    """

    def __init__(
        self,
        base_url: str,
        model: str | list[str],
        api_key: str,
        timeout_seconds: float = 15.0,
        dimensions: int | None = None,
        local_base_url: str = "",
        local_models: str | list[str] = "",
        local_api_key: str = "",
        local_enabled: bool = True,
        local_timeout_seconds: float = 5.0,
        local_dimensions: int | None = None,
    ) -> None:
        chains: list[_EmbeddingChain] = []
        if local_enabled and str(local_base_url).strip():
            local_models_list = _parse_model_list(local_models)
            if local_models_list:
                chains.append(
                    _EmbeddingChain(
                        base_url=str(local_base_url).strip().rstrip("/"),
                        models=tuple(local_models_list),
                        api_key=str(local_api_key),
                        dimensions=int(local_dimensions) if local_dimensions else None,
                        timeout_seconds=float(local_timeout_seconds),
                    )
                )
        remote_models = _parse_model_list(model)
        if remote_models and str(base_url).strip():
            chains.append(
                _EmbeddingChain(
                    base_url=str(base_url).strip().rstrip("/"),
                    models=tuple(remote_models),
                    api_key=str(api_key),
                    dimensions=int(dimensions) if dimensions else None,
                    timeout_seconds=float(timeout_seconds),
                )
            )
        self.chains = chains
        first = chains[0] if chains else None
        self.base_url = first.base_url if first else ""
        self.models = list(first.models) if first else []
        self.model = self.models[0] if self.models else ""
        self.api_key = first.api_key if first else api_key
        self.timeout_seconds = first.timeout_seconds if first else float(timeout_seconds)
        self.dimensions = first.dimensions if first else None
        self._active_index: int | None = None
        self.active_base_url = ""
        self.active_model = ""

    @property
    def signature(self) -> str:
        """配置指纹：base_url 或模型列表变化时触发知识库向量重建。"""
        return ";".join(
            f"{chain.base_url}|{','.join(chain.models)}" for chain in self.chains
        )

    def _chain_order(self) -> list[tuple[int, _EmbeddingChain]]:
        if self._active_index is not None:
            sticky = self.chains[self._active_index]
            rest = [
                (index, chain)
                for index, chain in enumerate(self.chains)
                if index != self._active_index
            ]
            return [(self._active_index, sticky), *rest]
        return list(enumerate(self.chains))

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """批量编码：本地优先、远程兜底；模型列表内部依次回退。

        单文本查询（聊天链路每次检索一条 query）走进程级 TTL memo：
        人格库与 kb_wiki 库对同一 query 各嵌一次、且 provider 实例不同，
        按 signature+文本为键即可跨库去重；批量文档嵌入不经 memo。
        """
        if not texts:
            return []
        memo_key: tuple[str, str] | None = None
        if len(texts) == 1:
            memo_key = (self.signature, texts[0])
            cached = _query_embed_memo_get(memo_key)
            if cached is not None:
                return [list(vector) for vector in cached]
        result = self._embed_texts_uncached(texts)
        if memo_key is not None and result:
            _query_embed_memo_put(memo_key, result)
        return result

    def _embed_texts_uncached(self, texts: list[str]) -> list[list[float]]:
        for index, chain in self._chain_order():
            for model in chain.models:
                try:
                    body: dict = {"model": model, "input": texts}
                    if chain.dimensions:
                        body["dimensions"] = chain.dimensions
                    headers = (
                        {"Authorization": f"Bearer {chain.api_key}"}
                        if chain.api_key
                        else {}
                    )
                    response = httpx.post(
                        f"{chain.base_url}/embeddings",
                        headers=headers,
                        json=body,
                        timeout=chain.timeout_seconds,
                    )
                    response.raise_for_status()
                    payload = response.json()
                    data = payload["data"]
                    if all("index" in item for item in data):
                        data = sorted(data, key=lambda item: int(item["index"]))
                    self._active_index = index
                    self.active_base_url = chain.base_url
                    self.active_model = model
                    return [list(item["embedding"]) for item in data]
                except Exception:  # noqa: S112, BLE001 - 单个嵌入服务失败时尝试下一个备用服务。
                    continue
        return []


def _chunk_text(text: str, *, chunk_chars: int) -> list[str]:
    """与 FileCharacterContextProvider._chunk_text 同语义的段落切块。"""
    paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        next_value = paragraph if not current else f"{current}\n{paragraph}"
        if len(next_value) <= chunk_chars:
            current = next_value
            continue
        if current:
            chunks.append(current)
        current = paragraph[:chunk_chars]
        while len(paragraph) > chunk_chars:
            paragraph = paragraph[chunk_chars:]
            chunks.append(current)
            current = paragraph[:chunk_chars]
    if current:
        chunks.append(current)
    return chunks


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    try:
        dot = sum(float(a) * float(b) for a, b in zip(left, right))
        left_norm = sqrt(sum(float(a) * float(a) for a in left))
        right_norm = sqrt(sum(float(b) * float(b) for b in right))
    except (TypeError, ValueError):
        return 0.0
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _batches(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _escape_like(term: str) -> str:
    """转义 LIKE 通配符，配合 SQL 的 ESCAPE '\' 使用。"""
    return (
        str(term)
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


# 词条名通道的切分与前缀匹配参数：人格知识库标题即文件名，常用 _/-/空白
# 连接主名与子题（如「纳西妲_背景故事」）；用户提及常只说到词条名前 2~4 字。
_TITLE_SEGMENT_SPLIT_RE = re.compile(r"[_\-\s]+")
_TITLE_PREFIX_MIN_CHARS = 2
_TITLE_PREFIX_MAX_CHARS = 4


def _entry_title_match_len(title: str, text: str) -> int:
    """词条名与查询文本的命中长度；0 = 未命中。

    人格库词条名按 ``_``/``-``/空白切分后逐段匹配：段整体包含于查询即
    命中（包含匹配）；纯中文段再取 2~4 字前缀（从长到宽尝试）出现在
    查询中也算命中（前缀匹配），容忍用户只提到词条名开头几个字。
    wiki 库标题「标题·来源」先剥来源后缀再比对。返回最长命中长度供排序。
    """
    base = title.split("·", 1)[0] if "·" in title else title
    best = 0
    for segment in _TITLE_SEGMENT_SPLIT_RE.split(base):
        if len(segment) < _TITLE_PREFIX_MIN_CHARS:
            continue
        if segment in text:
            best = max(best, len(segment))
            continue
        if not _CJK_RE.fullmatch(segment):
            continue
        for length in range(
            min(_TITLE_PREFIX_MAX_CHARS, len(segment) - 1),
            _TITLE_PREFIX_MIN_CHARS - 1,
            -1,
        ):
            if segment[:length] in text:
                best = max(best, length)
                break
    return best


def _title_exact_hit(title: str, text: str) -> bool:
    """词条标题是否被查询**整段**包含（区别于 2~4 字前缀的部分命中）。

    人格库标题按 ``_``/``-``/空白切分后，任一 >=2 字的段完整出现在查询
    中即为精确命中（如查询「守岸人是谁」整段包含词条《守岸人》）；
    wiki 库标题先剥「·来源」后缀再切分。精确命中供检索置顶（直通第一），
    前缀命中只保留原有的 RRF 加权，不置顶。
    """
    base = title.split("·", 1)[0] if "·" in title else title
    return any(
        len(segment) >= _TITLE_PREFIX_MIN_CHARS and segment in text
        for segment in _TITLE_SEGMENT_SPLIT_RE.split(base)
    )


def _rrf_scores(
    vector_ids: list[str],
    keyword_ids: list[str],
    k: float = _RRF_K,
    bonus_ids: list[str] | None = None,
) -> dict[str, float]:
    """RRF 打分（与 _rrf_fuse 同式），供 search_scored 暴露逐块融合分。"""
    scores: dict[str, float] = {}
    for rank, chunk_id in enumerate(vector_ids):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
    for rank, chunk_id in enumerate(keyword_ids):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
    for rank, chunk_id in enumerate(bonus_ids or []):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 2.0 / (k + rank + 1)
    return scores


def _rrf_fuse(
    vector_ids: list[str],
    keyword_ids: list[str],
    top_k: int,
    k: float = _RRF_K,
    bonus_ids: list[str] | None = None,
) -> list[str]:
    """Reciprocal Rank Fusion：把多个通道的排序融合成一个稳定排序。

    bonus_ids（词条名命中通道）以双倍权重并入：查询里包含某词条名时
    （如「纳西妲的元素战技叫什么」含词条《纳西妲》），该词条页应优先于
    正文堆满相近词的机制/攻略页。只做排序，不加载正文。
    """
    scores = _rrf_scores(vector_ids, keyword_ids, k=k, bonus_ids=bonus_ids)
    ranked = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))
    return ranked[: max(0, int(top_k))]


def _file_signature(path: Path) -> tuple[int, int] | None:
    """(mtime,size) 内容签名；文件不可达返回 None（调用方不得用它跳过同步）。"""
    try:
        stat = path.stat()
        return (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return None


def _metadata_value(doc: dict, column: str) -> str | None:
    """台账时间元数据取值：键缺失 → None（无从得知，落 NULL 绝不冒充）。

    键存在则规范为去空白字符串：``''`` 是诚实的「上游没有可信时间值」
    （非 MediaWiki 系源没有编辑时间），与 NULL 的「从未回填」严格区分。
    """
    if column not in doc:
        return None
    return str(doc.get(column) or "").strip()


@dataclass(frozen=True)
class ScoredKnowledgeChunk:
    """带通道排名与 RRF 融合分的检索单条（KnowledgeService 供分面用）。

    channels 值为该块在各通道候选中的 0 基排名；None = 未命中该通道。
    """

    chunk: KnowledgeChunk
    score: float
    channels: dict[str, int | None]


class SqliteVectorKnowledgeStore:
    def __init__(
        self,
        db_path: str | Path,
        embed_provider: EmbeddingProvider,
        chunk_chars: int = 900,
        top_k: int = 4,
        signature: str = "",
        auto_reset: bool = True,
        ann_index_path: str = "",
        ann_order_path: str = "",
        min_cosine_threshold: float = _MISS_COSINE_THRESHOLD,
        fts_auto_rebuild: bool = True,
    ) -> None:
        self.db_path = str(db_path)
        self.embed_provider = embed_provider
        self.chunk_chars = max(_MIN_CHUNK_CHARS, int(chunk_chars))
        self.top_k = max(0, int(top_k))
        self.signature = str(signature or "").strip()
        self.ann_index_path = str(ann_index_path or "").strip() or str(
            Path(self.db_path).with_name("knowledge_faiss.index")
        )
        self.ann_order_path = str(ann_order_path or "").strip() or str(
            Path(self.db_path).with_name("knowledge_faiss.order.json")
        )
        self._ann_index: Any | None = None
        self._ann_order: list[str] | None = None
        # 运行时应为 False：只有显式 knowledge-sync 才允许因指纹变化清空向量，
        # 避免机器人进程与同步进程并发时互相清空、进度反复回退。
        self.auto_reset = bool(auto_reset)
        self._lock = threading.RLock()
        # 文件代际号：原子换索引（KnowledgeService.reindex → swap）后递增，
        # 各线程 _connect 发现代际不符即关旧连接重开（旧句柄指向旧 inode）。
        self._file_generation: int = 0
        # 维护任务锁：embed_pending/build_ann_index 等分钟级重建相互互斥，
        # 但绝不持 _lock（检索锁）执行——否则一次重建冻结所有会话的检索。
        self._maintenance_lock = threading.Lock()
        # 线程局部连接缓存（见 _connect）；:memory: 库不缓存。
        self._conn_tls = threading.local()
        # (mtime,size) 同步签名缓存：签名未变的知识文件在 sync_chunks 里跳过
        # 重读/分块/哈希（管线检视 #9；每条消息至少进一次 sync_chunks）。
        self._synced_signatures: dict[Path, tuple[int, int]] = {}
        self._vector_cache: Any | None = None
        self._vector_meta: list[dict] | None = None
        # R3 停摆批：向量缓存单飞构建锁——GB 级全表载入（见 _build_vector_cache）
        # 多线程只做一次，其余等同一份结果；构建绝不重复、也绝不互相踩。
        # 只与 _load_vector_cache/_prewarm_vector_cache 配套，是叶子锁：
        # 持有它期间不得再取 _lock（锁序：_lock → 本锁，防环）。
        self._vector_cache_build_lock = threading.Lock()
        # 缓存世代号：_invalidate_vector_cache 递增；锁外预热构建期间若发生
        # 新失效（世代变化）则丢弃本轮结果（防把过期矩阵换入）。
        self._vector_cache_generation: int = 0
        # FTS5 关键词通道状态；None 表示“本进程尚未确认”，
        # False 表示已确认不可用（仅在知识库内容变化后重试）。
        self._fts_valid: bool | None = None
        # 低置信未命中阈值：无关键词命中且向量最高余弦低于该值时返回空结果。
        self.min_cosine_threshold = float(min_cosine_threshold)
        # False 时检索路径发现 FTS 签名缺失不做内联重建（大库重建分钟级，
        # 会卡住消息处理），降级为纯向量通道，重建交给显式同步任务 force=True。
        self.fts_auto_rebuild = bool(fts_auto_rebuild)
        self._ensure_schema()
        # 库内既有向量维度（首次写入时落 knowledge_meta，重启后恢复）：
        # _save_vectors 用它拒绝混合维度语料入库。
        self._vector_dim: int | None = self._stored_vector_dim()

    def _stored_vector_dim(self) -> int | None:
        if self.db_path == ":memory:":
            return None
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT value FROM knowledge_meta WHERE key = 'vector_dim'"
                ).fetchone()
            return int(str(row[0])) if row else None
        except (sqlite3.Error, TypeError, ValueError):
            return None

    def _ensure_schema(self) -> None:
        if self.db_path != ":memory:":
            Path(self.db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            # WAL（持久属性，设一次即可）：与 knowledge-sync/kb-sync 独立进程
            # 并发读写时不再互相阻塞成片 SQLITE_BUSY（affinity/media_registry 同款）。
            try:
                connection.execute("PRAGMA journal_mode=WAL")
            except sqlite3.Error:
                pass
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    source_id TEXT,
                    title TEXT,
                    content TEXT,
                    content_hash TEXT,
                    vector_json TEXT,
                    vector_blob BLOB
                )
                """
            )
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(knowledge_chunks)")
            }
            if "vector_blob" not in columns:
                connection.execute(
                    "ALTER TABLE knowledge_chunks ADD COLUMN vector_blob BLOB"
                )
            # sync_documents / sync_chunks 的按源删除与源级统计走这个索引，
            # 大库（十万行级）没有它每次删源都退化为全表扫描。
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_source "
                "ON knowledge_chunks(source_id)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
                """
            )
            # 外部知识库文档台账：doc_id → hash，sync_documents 幂等判断的依据。
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_docs (
                    doc_id TEXT PRIMARY KEY,
                    topic TEXT,
                    source TEXT,
                    title TEXT,
                    hash TEXT,
                    source_updated_at TEXT,
                    crawl_at TEXT
                )
                """
            )
            # 存量库列迁移（与 knowledge_chunks.vector_blob 同一套幂等做法：
            # PRAGMA table_info 探测 → 缺列才 ALTER）：时间元数据是「只增不改」
            # 的旁路信息，ALTER 只加可空列，既有行取值 NULL（=从未回填），
            # 永不触碰 chunk/向量，因此升级本身零重嵌成本。
            doc_columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(knowledge_docs)")
            }
            for column in _DOC_METADATA_COLUMNS:
                if column not in doc_columns:
                    connection.execute(
                        f"ALTER TABLE knowledge_docs ADD COLUMN {column} TEXT"
                    )

    def _stored_signature(self) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM knowledge_meta WHERE key = 'embedding_signature'"
            ).fetchone()
        return str(row[0]) if row else ""

    def _set_stored_signature(self, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO knowledge_meta (key, value)
                VALUES ('embedding_signature', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (value,),
            )

    def set_meta(self, key: str, value: str) -> None:
        """knowledge_meta 通用写入口（键值均为字符串，供同步摘要等观测项落库）。

        与 embedding_signature/fts_signature 同表同语义：单行 UPSERT，跨进程、
        跨重启可见；不改任何 chunk/向量行，因此写入本身零重嵌成本。
        """
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO knowledge_meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(key), str(value)),
            )

    def get_meta(self, key: str) -> str:
        """knowledge_meta 通用读入口；键不存在返回空串（不猜默认值）。"""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM knowledge_meta WHERE key = ?", (str(key),)
            ).fetchone()
        return str(row[0]) if row is not None and row[0] is not None else ""

    def _reset_vectors_if_needed(self) -> bool:
        """模型/端点指纹变化时清空旧向量（返回是否执行了重置）。

        首次构建或上一次构建未完成时，stored 为空：不清空，保留已有
        向量并断点续跑剩余行，避免重启同步把已完成进度全部回退。
        """
        if not self.signature:
            return False
        if not self.auto_reset:
            return False
        stored = self._stored_signature()
        if not stored or stored == self.signature:
            return False
        with self._connect() as connection:
            connection.execute("UPDATE knowledge_chunks SET vector_json = NULL")
            # 模型指纹变化常伴随维度变化：维度守卫一并复位，允许新维度重新入库。
            connection.execute("DELETE FROM knowledge_meta WHERE key = 'vector_dim'")
        with self._lock:
            self._vector_dim = None
        self._set_stored_signature("")
        self._invalidate_vector_cache()
        return True

    def _embed_all_pending(self, on_progress=None, batch_size: int | None = None) -> tuple[int, int]:
        """把全部待嵌入行编码入库；完成后记录模型指纹，失败可断点续跑。

        on_progress(done, total) 每处理一批调用一次，用于打印进度。
        batch_size 覆盖默认批大小（默认值迁就远程链限额；本地 Ollama
        大批吞吐显著更高，由调用方按需传入）。
        """
        self._reset_vectors_if_needed()
        pending = self._pending_rows()
        size = max(1, int(batch_size)) if batch_size else _EMBED_BATCH_SIZE
        done = 0
        for batch in _batches(pending, size):
            vectors = self._embed([str(row["content"]) for row in batch])
            if vectors is None:
                break
            if not self._save_vectors(batch, vectors):
                break
            done += len(batch)
            if on_progress is not None:
                try:
                    on_progress(done, len(pending))
                except Exception:  # noqa: S110, BLE001 - 进度回调失败不影响嵌入任务。
                    pass
        if self.signature and done == len(pending):
            self._set_stored_signature(self.signature)
        return done, len(pending)

    def _invalidate_vector_cache(self) -> None:
        self._vector_cache = None
        self._vector_meta = None
        # R3 停摆批：世代号递增，锁外预热（_prewarm_vector_cache）构建期间
        # 发生新失效时据此丢弃过期结果。部分调用点不持 _lock（sync_documents），
        # 整数自增的竞态最坏是多保留一轮旧缓存，可接受。
        self._vector_cache_generation += 1

    def _prewarm_vector_cache(self) -> None:
        """检索锁外预热向量缓存（R3 停摆批根治项）。

        背景：``retrieve``/``search_scored`` 的向量通道在**持有检索锁**时
        走 ``_vector_candidates`` → ``_load_vector_cache``，缓存失效后的
        首次检索会把全表载入（kb_wiki 23.8 万块库文件 5.7GB）也放进锁内，
        全部会话的检索在锁后排队、聊天线程池堆满 → 消息被 pipeline_busy
        静默吞掉、LLM 请求发不出（22:25 停摆实弹根因之一）。

        本方法在进锁**之前**把缓存烧热：单飞构建锁保证多线程只等一份构建，
        构建完成后世代校验 + 原子换入；进锁后的 ``_load_vector_cache`` 命中
        热缓存即瞬时返回。fail-open：任何异常不影响检索主链路（锁内路径
        自会再试）。
        """
        if self._vector_cache is not None and self._vector_meta is not None:
            return
        try:
            generation = self._vector_cache_generation
            with self._vector_cache_build_lock:
                if self._vector_cache is not None and self._vector_meta is not None:
                    return  # 别的线程刚烧热，直接用。
                matrix, chunk_ids = self._build_vector_cache()
            if generation != self._vector_cache_generation:
                return  # 构建期间发生了新的失效：本轮结果已过期，丢弃。
            if matrix is not None:
                with self._lock:
                    # 只在缓存仍为空时换入（避免覆盖更近一次失效后的重建）。
                    if self._vector_cache is None:
                        self._vector_cache = matrix
                        self._vector_meta = chunk_ids
        except Exception:  # noqa: BLE001 - 预热失败不影响检索（锁内路径兜底）。
            return

    def _connect(self) -> sqlite3.Connection:
        """线程局部连接复用（本机延迟压榨项）：一次检索要开 6~8 个连接
        （sync_chunks/FTS 探查×2/短语 MATCH/词条 MATCH/正文懒加载），人格库
        +wiki 库每条消息合计 12~16 次 sqlite3.connect；Windows 上每次建连
        0.1~0.3ms 且伴随文件句柄开销。按 (store, thread) 缓存后归零。

        安全边界：``check_same_thread=False`` 下并发共享同一连接不安全，
        因此按线程隔离（每线程各一条，互不交叉）；``:memory:`` 库按线程
        缓存会变成各线程一张空库，必须每次新建。连接异常自愈交给上层
        检索器的兜底（_VectorKnowledgeRetriever/KBWikiRetriever 捕获降级）。
        """
        if self.db_path == ":memory:":
            return self._new_connection()
        connection = getattr(self._conn_tls, "connection", None)
        if connection is not None and (
            getattr(self._conn_tls, "generation", -1) != self._file_generation
        ):
            # 代际已切换（原子换索引）：旧连接指向被替换前的旧 inode，作废重开。
            try:
                connection.close()
            except sqlite3.Error:
                pass
            connection = None
        if connection is None:
            connection = self._new_connection()
            self._conn_tls.connection = connection
            self._conn_tls.generation = self._file_generation
        return connection

    def invalidate_runtime_caches(self) -> None:
        """换代后清空进程内缓存并作废线程连接（原子换索引后必须调用）。

        递增文件代际号：各线程 `_connect` 下次取连接时发现代际不符即关
        旧连接重开（旧句柄指向被替换前的旧 inode，不再复用）；向量缓存、
        ANN 索引、FTS 有效性状态、同步签名缓存一并作废。
        """
        with self._lock:
            self._file_generation += 1
            self._invalidate_vector_cache()
            self._ann_index = None
            self._ann_order = None
            self._fts_valid = None
            self._synced_signatures.clear()

    def close_runtime_handles(self) -> None:
        """关闭当前线程的缓存连接并清缓存（重建临时库换文件前必须调用）。

        Windows 上 sqlite 打开的文件无法原子替换，临时库 swap 前必须把
        本线程句柄干净关闭（close 时 WAL 自动 checkpoint 落盘、删旁车）。
        """
        connection = getattr(self._conn_tls, "connection", None)
        if connection is not None:
            try:
                connection.close()
            except sqlite3.Error:
                pass
            self._conn_tls.connection = None
        self.invalidate_runtime_caches()

    def _new_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_source_ledger(
        self,
        connection: sqlite3.Connection,
        source_id: str,
        signature: tuple[int, int],
        ledger: set[str],
    ) -> None:
        """确保源级台账有记录；首次升级/首次同步时补写一次，之后零写入。"""
        if source_id in ledger:
            return
        connection.execute(
            "INSERT OR IGNORE INTO knowledge_meta (key, value) VALUES (?, ?)",
            (_SOURCE_SIG_KEY_PREFIX + source_id, f"{signature[0]}:{signature[1]}"),
        )
        ledger.add(source_id)

    def sync_chunks(self, files: list[Path]) -> None:
        with self._lock:
            paths = [Path(path).expanduser() for path in files]
            manifest_stems = {path.stem for path in paths}
            changed = False
            with self._connect() as connection:
                # 精确删除（清单过期不得删清单外新块）：旧实现
                # `DELETE ... WHERE source_id NOT IN (当前清单)` 以本次清单为
                # 全集，机器人进程清单过期/偏小时会把 knowledge-sync 等其他
                # 写入方刚落库的清单外新块连同旧块一起清掉。改为按台账精确
                # 删除：只删「本库此前同步过（台账有记录）、且已不在当前清单」
                # 的源；台账 key=sync_source_sig:<source_id> 持久化在
                # knowledge_meta，跨进程、跨重启有效。
                ledger = {
                    str(row["key"])[len(_SOURCE_SIG_KEY_PREFIX) :]
                    for row in connection.execute(
                        "SELECT key FROM knowledge_meta WHERE key LIKE ?",
                        (_SOURCE_SIG_KEY_PREFIX + "%",),
                    )
                }
                for stale_source in sorted(ledger - manifest_stems):
                    cursor = connection.execute(
                        "DELETE FROM knowledge_chunks WHERE source_id = ?",
                        (stale_source,),
                    )
                    changed = changed or cursor.rowcount > 0
                    connection.execute(
                        "DELETE FROM knowledge_meta WHERE key = ?",
                        (_SOURCE_SIG_KEY_PREFIX + stale_source,),
                    )
                for path in paths:
                    # (mtime,size) 签名未变的文件跳过重读：retrieve 每条消息都会进这里，
                    # 向量未命中为常态，无签名缓存时每次都要全量读盘+分块+双 sha1
                    #（管线检视 #9；签名语义与 KeywordKnowledgeRetriever._sync_path 一致）。
                    signature = _file_signature(path)
                    if signature is not None and self._synced_signatures.get(path) == signature:
                        self._ensure_source_ledger(connection, path.stem, signature, ledger)
                        continue
                    if signature is None:
                        if path.exists():
                            # 存在但暂时不可读（占用/权限瞬态）：跳过，下条消息重试。
                            continue
                        # 文件已被删除：清掉旧块，避免被删知识继续被检索命中；
                        # 台账记录一并移除。
                        cursor = connection.execute(
                            "DELETE FROM knowledge_chunks WHERE source_id = ?",
                            (path.stem,),
                        )
                        changed = changed or cursor.rowcount > 0
                        connection.execute(
                            "DELETE FROM knowledge_meta WHERE key = ?",
                            (_SOURCE_SIG_KEY_PREFIX + path.stem,),
                        )
                        ledger.discard(path.stem)
                        self._synced_signatures.pop(path, None)
                        continue
                    text = load_character_document(path)
                    source_id = path.stem
                    for index, content in enumerate(
                        _chunk_text(text, chunk_chars=self.chunk_chars),
                        start=1,
                    ):
                        chunk_id = hashlib.sha1(
                            f"{path.as_posix()}:{index}:{content}".encode()
                        ).hexdigest()
                        content_hash = hashlib.sha1(
                            content.encode("utf-8")
                        ).hexdigest()
                        existing = connection.execute(
                            "SELECT content_hash FROM knowledge_chunks WHERE chunk_id = ?",
                            (chunk_id,),
                        ).fetchone()
                        if existing is None:
                            connection.execute(
                                """
                                INSERT INTO knowledge_chunks (
                                    chunk_id, source_id, title, content,
                                    content_hash, vector_json
                                )
                                VALUES (?, ?, ?, ?, ?, ?)
                                """,
                                (chunk_id, source_id, source_id, content, content_hash, None),
                            )
                            changed = True
                        elif str(existing["content_hash"]) != content_hash:
                            connection.execute(
                                """
                                UPDATE knowledge_chunks
                                SET source_id = ?, title = ?, content = ?,
                                    content_hash = ?, vector_json = NULL
                                WHERE chunk_id = ?
                                """,
                                (source_id, source_id, content, content_hash, chunk_id),
                            )
                            changed = True
                    if signature is not None:
                        self._synced_signatures[path] = signature
                        self._ensure_source_ledger(connection, path.stem, signature, ledger)
                # 清单里已移除的文件不再保留签名缓存条目。
                for stale in set(self._synced_signatures) - set(paths):
                    self._synced_signatures.pop(stale, None)

                if changed:
                    # 内容/行集合变化会改变 FTS 索引内容：先删除共享签名，
                    # 让本进程与 knowledge-sync 进程都判定索引过期并在下次查询时重建。
                    connection.execute(
                        "DELETE FROM knowledge_meta WHERE key = 'fts_signature'"
                    )
            if changed:
                self._invalidate_vector_cache()
                self._invalidate_fts()

    def sync_documents(
        self,
        docs: Iterable[dict],
        *,
        removed_ids: Iterable[str] = (),
        full: bool = False,
        batch_size: int = 500,
        on_progress=None,
    ) -> dict[str, int]:
        """按 (doc_id, hash) 幂等同步外部文档集（如 Crawl Wiki 知识库）。

        docs 迭代产出 ``{"id", "hash", "chunks", "topic", "source", "title"}``，
        可带 ``source_updated_at``/``crawl_at`` 时间元数据；分块由调用方完成
        （如按 Markdown 标题分节），本方法只负责台账比对与落库：
        hash 未变的文档跳过（只顺带刷时间元数据，见下），新增/变化的先删旧块再
        插入（向量置空等待 embed），``removed_ids`` 与 full 模式下清单中消失的
        文档连同 chunk 一并删除。
        每 batch_size 个文档提交一次，中断后重跑自动续传。
        返回 ``{"added", "changed", "removed", "skipped", "chunks",
        "metadata_refreshed"}``。
        """
        stats = {
            "added": 0,
            "changed": 0,
            "removed": 0,
            "skipped": 0,
            "chunks": 0,
            "metadata_refreshed": 0,
        }
        changed_any = False
        # 批量同步走一次性新建连接（方法结尾显式 close）：不能复用线程局部
        # 缓存连接，否则 close 会毒化本线程后续所有 _connect() 调用。
        connection = self._new_connection()
        try:
            ledger = {
                str(row["doc_id"]): row
                for row in connection.execute(
                    "SELECT doc_id, hash, source_updated_at, crawl_at FROM knowledge_docs"
                )
            }
            seen: set[str] = set()

            def apply_doc(doc_id: str, doc: dict, doc_hash: str) -> None:
                nonlocal changed_any
                connection.execute(
                    "DELETE FROM knowledge_chunks WHERE source_id = ?", (doc_id,)
                )
                chunks = [str(chunk) for chunk in (doc.get("chunks") or []) if str(chunk).strip()]
                connection.executemany(
                    """
                    INSERT INTO knowledge_chunks (
                        chunk_id, source_id, title, content, content_hash, vector_json
                    )
                    VALUES (?, ?, ?, ?, ?, NULL)
                    """,
                    [
                        (
                            hashlib.sha1(
                                f"doc:{doc_id}:{index}:{content}".encode()
                            ).hexdigest(),
                            doc_id,
                            str(doc.get("title") or doc_id),
                            content,
                            hashlib.sha1(content.encode("utf-8")).hexdigest(),
                        )
                        for index, content in enumerate(chunks, start=1)
                    ],
                )
                connection.execute(
                    """
                    INSERT INTO knowledge_docs (
                        doc_id, topic, source, title, hash,
                        source_updated_at, crawl_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(doc_id) DO UPDATE SET
                        topic = excluded.topic,
                        source = excluded.source,
                        title = excluded.title,
                        hash = excluded.hash,
                        source_updated_at = excluded.source_updated_at,
                        crawl_at = excluded.crawl_at
                    """,
                    (
                        doc_id,
                        str(doc.get("topic") or ""),
                        str(doc.get("source") or ""),
                        str(doc.get("title") or ""),
                        doc_hash,
                        _metadata_value(doc, "source_updated_at"),
                        _metadata_value(doc, "crawl_at"),
                    ),
                )
                stats["chunks"] += len(chunks)
                if doc_id in ledger:
                    stats["changed"] += 1
                else:
                    stats["added"] += 1
                changed_any = True

            def refresh_doc_metadata(doc_id: str, doc: dict) -> None:
                """hash 未变行的时间元数据顺手补齐：只 UPDATE 台账两列。

                不碰 knowledge_chunks、不清 FTS 签名、不失效向量缓存——时间与
                正文同源而 hash 只认正文，因此这条路径的重跑成本是常数次 UPDATE，
                永不引发重嵌（首晚全表回填走 sync_document_metadata 同语义）。
                """
                row = ledger.get(doc_id)
                if row is None:
                    return
                for column in _DOC_METADATA_COLUMNS:
                    want = _metadata_value(doc, column)
                    if want is None or row[column] == want:
                        continue
                    connection.execute(
                        f"UPDATE knowledge_docs SET {column} = ? WHERE doc_id = ?",
                        (want, doc_id),
                    )
                    stats["metadata_refreshed"] += 1

            buffered = 0
            for doc in docs:
                doc_id = str(doc.get("id") or "").strip()
                doc_hash = str(doc.get("hash") or "").strip()
                if not doc_id or not doc_hash:
                    continue
                if full:
                    seen.add(doc_id)
                if ledger.get(doc_id) is not None and str(
                    ledger[doc_id]["hash"] or ""
                ) == doc_hash:
                    refresh_doc_metadata(doc_id, doc)
                    stats["skipped"] += 1
                    continue
                apply_doc(doc_id, doc, doc_hash)
                buffered += 1
                if buffered >= max(1, int(batch_size)):
                    connection.commit()
                    buffered = 0
                    if on_progress is not None:
                        try:
                            on_progress(dict(stats))
                        except Exception:  # noqa: S110, BLE001 - 进度回调失败不影响同步。
                            pass
            connection.commit()

            removed = {str(doc_id) for doc_id in removed_ids if str(doc_id)}
            removed &= set(ledger)
            if full:
                removed |= set(ledger) - seen
            for doc_id in sorted(removed):
                connection.execute(
                    "DELETE FROM knowledge_chunks WHERE source_id = ?", (doc_id,)
                )
                connection.execute(
                    "DELETE FROM knowledge_docs WHERE doc_id = ?", (doc_id,)
                )
                stats["removed"] += 1
                changed_any = True
            if changed_any or removed:
                # 行集合/内容变化后 FTS 索引过期：清签名让显式同步任务
                # （或 fts_auto_rebuild 的检索进程）在下次访问时重建。
                # ANN 索引不清签名：同步窗口内继续用旧索引（拿不到新块但
                # 崩溃安全），重建由 embed 完成后的 build_ann_index 负责。
                connection.execute(
                    "DELETE FROM knowledge_meta WHERE key = 'fts_signature'"
                )
            connection.commit()
        finally:
            connection.close()
        if changed_any or removed:
            self._invalidate_vector_cache()
            self._invalidate_fts()
        return stats

    def document_count(self) -> int:
        """台账中的文档数（sync_documents 同步范围），供烟测/调度日志使用。"""
        with self._connect() as connection:
            return int(
                connection.execute("SELECT COUNT(*) FROM knowledge_docs").fetchone()[0]
            )

    def document_ledger(self) -> dict[str, str]:
        """台账快照 ``{doc_id: hash}``（对账用：与 manifest.entries 全量比对）。

        十万行级台账一次性载入约数 MB 常驻，只在对账轮调用；行序不保证，
        调用方按 key 取用。
        """
        with self._connect() as connection:
            return {
                str(row["doc_id"]): str(row["hash"] or "")
                for row in connection.execute("SELECT doc_id, hash FROM knowledge_docs")
            }

    def documents_missing_metadata(self) -> int:
        """台账里时间元数据尚未回填的文档数（crawl_at IS NULL）。

        ``crawl_at`` 由导出侧保证 100% 有值，故 NULL 唯一含义是「本库从未写过
        该文档的时间元数据」；``source_updated_at`` 不用于判缺（非 MediaWiki 系
        上游本就没有编辑时间，回填后合理为空串）。
        """
        with self._connect() as connection:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM knowledge_docs WHERE crawl_at IS NULL"
                ).fetchone()[0]
            )

    def sync_document_metadata(self, docs: Iterable[dict], *, batch_size: int = 500) -> dict[str, int]:
        """零嵌入成本的全表时间元数据回填：只 UPDATE 台账两列，绝不动正文/向量。

        docs 迭代产出 ``{"id", "hash", "source_updated_at", "crawl_at"}``（不必
        带 chunks）。语义与 sync_documents 的跳过分支完全一致，但省掉读正文、
        分块、算 sha1 的全部开销，用于「语料侧只新增时间字段、正文一字未改」
        这类升级的第一晚回填：

        - 台账里没有的 doc_id → 计 ``missing``（新增文档归同步/对账路径管）；
        - 行 hash 与台账 hash 不一致 → 计 ``stale`` 并跳过：那条时间值描述的
          是**另一个内容版本**，写进本库就是假元数据，留给下一轮正常同步；
        - 只在与已存值不同才 UPDATE（``refreshed`` 计数），重跑幂等；
        - 不清 FTS 签名、不失效向量缓存、不产生待嵌行。

        返回 ``{"matched", "refreshed", "missing", "stale"}``。
        """
        stats = {"matched": 0, "refreshed": 0, "missing": 0, "stale": 0}
        connection = self._new_connection()
        try:
            ledger = {
                str(row["doc_id"]): row
                for row in connection.execute(
                    "SELECT doc_id, hash, source_updated_at, crawl_at FROM knowledge_docs"
                )
            }
            buffered = 0
            for doc in docs:
                doc_id = str(doc.get("id") or "").strip()
                if not doc_id:
                    continue
                row = ledger.get(doc_id)
                if row is None:
                    stats["missing"] += 1
                    continue
                doc_hash = str(doc.get("hash") or "").strip()
                if doc_hash and doc_hash != str(row["hash"] or ""):
                    stats["stale"] += 1
                    continue
                stats["matched"] += 1
                for column in _DOC_METADATA_COLUMNS:
                    want = _metadata_value(doc, column)
                    # NULL 与 '' 是两回事：NULL=从未回填（要写），''=上游确无
                    # 可信时间值（写过就不再动）。
                    if want is None or row[column] == want:
                        continue
                    connection.execute(
                        f"UPDATE knowledge_docs SET {column} = ? WHERE doc_id = ?",
                        (want, doc_id),
                    )
                    stats["refreshed"] += 1
                buffered += 1
                if buffered >= max(1, int(batch_size)):
                    connection.commit()
                    buffered = 0
            connection.commit()
        finally:
            connection.close()
        return stats

    def embed_pending(
        self,
        files: list[Path] | None = None,
        on_progress=None,
        *,
        batch_size: int | None = None,
    ) -> tuple[int, int]:
        """预建库：同步文件切片后把未向量化的行全部嵌入。

        模型/端点指纹变化时自动清空旧向量重嵌；返回
        (本次成功嵌入行数, 处理前待嵌入行数)；中途失败即停止、可断点续跑。
        batch_size 覆盖每批行数（本地大批更快，见 _embed_all_pending）。
        """
        with self._maintenance_lock:
            if files:
                self.sync_chunks(list(files))
            return self._embed_all_pending(on_progress=on_progress, batch_size=batch_size)

    def stats(self) -> dict[str, int]:
        """返回 (总行数, 已向量化行数)，供烟测/后台统计使用。"""
        with self._connect() as connection:
            total = int(
                connection.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
            )
            embedded = int(
                connection.execute(
                    "SELECT COUNT(*) FROM knowledge_chunks "
                    "WHERE vector_json IS NOT NULL AND vector_json != ''"
                ).fetchone()[0]
            )
        return {"total": total, "embedded": embedded}

    def retrieve(
        self,
        query_text: str,
        files: list[Path] | None = None,
        *,
        embed_backlog: bool = False,
    ) -> list[KnowledgeChunk]:
        # R3 停摆批：进锁前把向量缓存烧热（GB 级全表载入绝不持检索锁执行）。
        self._prewarm_vector_cache()
        # 锁分段策略：查询嵌入是同步网络调用（httpx 最长 60s），绝不能持
        # self._lock 执行，否则全会话检索在此串行停摆。锁内只保留
        # sync_chunks / 积压补齐 / 候选索引一致读这些快操作。
        with self._lock:
            self.sync_chunks(list(files) if files else [])
            if self.top_k <= 0:
                return []
            if embed_backlog:
                # 只有显式预建/同步路径才补齐积压；请求路径不做全表扫描。
                done, pending = self._embed_all_pending()
                if done < pending:
                    return []
        query_vectors = self._embed([str(query_text)])
        if query_vectors is None or len(query_vectors) != 1:
            return []
        query_vector = query_vectors[0]
        with self._lock:
            # 三通道候选：BM25/FTS 关键词 + 向量（HNSW/暴力）+ 词条名命中，
            # 再 RRF 融合（词条名通道双倍权重）。
            keyword_ranked = self._keyword_candidates(str(query_text))
            vector_ranked, best_cosine = self._vector_candidates(query_vector)
            try:
                entry_hits = self._entry_title_candidates(str(query_text))
            except Exception:  # noqa: BLE001 - 词条通道失败不阻断其余两通道。
                entry_hits = []
            entry_ranked = [chunk_id for _match_len, _exact, chunk_id in entry_hits]
            # 人格词条置顶（最高优先）：查询**整段包含**某条目标题时，该词条
            # 的块直通结果头部，不再依赖 RRF 相对分数——「守岸人是谁」必须先
            # 命中人格库《守岸人》词条，而不是正文堆满「守岸人」的相邻页。
            pinned_ids = [chunk_id for _match_len, exact, chunk_id in entry_hits if exact]
            fused_ids = _rrf_fuse(
                vector_ranked, keyword_ranked, self.top_k, bonus_ids=entry_ranked
            )
            if not fused_ids and not pinned_ids:
                return []
            # 低置信未命中：既没有关键词命中、也没有精确词条命中、向量最强
            # 余弦又低于阈值 -> 空结果。
            if (
                not keyword_ranked
                and not pinned_ids
                and best_cosine < self.min_cosine_threshold
            ):
                return []
            if pinned_ids:
                pinned_seen = set(pinned_ids)
                fused_ids = [
                    *pinned_ids,
                    *[chunk_id for chunk_id in fused_ids if chunk_id not in pinned_seen],
                ]
            return self._fetch_chunks(list(fused_ids)[: max(1, self.top_k)])

    def search_scored(
        self,
        query_text: str,
        files: list[Path] | None = None,
        *,
        embed_backlog: bool = False,
        top_k: int | None = None,
        sync_files: bool = True,
    ) -> list[ScoredKnowledgeChunk]:
        """带分数检索：与 retrieve 同一三通道候选链，但不丢弃分数。

        返回按 RRF 融合分降序的 ScoredKnowledgeChunk（含词条置顶直通），
        channels 记录各通道 0 基排名（None=未命中），供 KnowledgeService
        做跨库二次融合与来源/分数透出。sync_files=False 时不做文件同步
        （纯只读检索路径；同步属显式 reindex/预建链路）。
        """
        limit = self.top_k if top_k is None else max(0, int(top_k))
        # R3 停摆批：与 retrieve 同口径——进锁前烧热向量缓存（锁外预热）。
        self._prewarm_vector_cache()
        with self._lock:
            if sync_files:
                self.sync_chunks(list(files) if files else [])
            if limit <= 0:
                return []
            if embed_backlog:
                done, pending = self._embed_all_pending()
                if done < pending:
                    return []
        query_vectors = self._embed([str(query_text)])
        if query_vectors is None or len(query_vectors) != 1:
            return []
        query_vector = query_vectors[0]
        with self._lock:
            keyword_ranked = self._keyword_candidates(str(query_text))
            vector_ranked, best_cosine = self._vector_candidates(query_vector)
            try:
                entry_hits = self._entry_title_candidates(str(query_text))
            except Exception:  # noqa: BLE001 - 词条通道失败不阻断其余两通道。
                entry_hits = []
            entry_ranked = [chunk_id for _match_len, _exact, chunk_id in entry_hits]
            pinned_ids = [chunk_id for _match_len, exact, chunk_id in entry_hits if exact]
            fused_ids = _rrf_fuse(
                vector_ranked, keyword_ranked, limit, bonus_ids=entry_ranked
            )
            if not fused_ids and not pinned_ids:
                return []
            if (
                not keyword_ranked
                and not pinned_ids
                and best_cosine < self.min_cosine_threshold
            ):
                return []
            if pinned_ids:
                pinned_seen = set(pinned_ids)
                fused_ids = [
                    *pinned_ids,
                    *[chunk_id for chunk_id in fused_ids if chunk_id not in pinned_seen],
                ]
            fused_ids = list(fused_ids)[: max(1, limit)]
            scores = _rrf_scores(
                vector_ranked, keyword_ranked, bonus_ids=entry_ranked
            )
            vector_rank_map = {cid: i for i, cid in enumerate(vector_ranked)}
            keyword_rank_map = {cid: i for i, cid in enumerate(keyword_ranked)}
            entry_rank_map = {cid: i for i, cid in enumerate(entry_ranked)}
            results: list[ScoredKnowledgeChunk] = []
            for chunk in self._fetch_chunks(list(fused_ids)):
                chunk_id = chunk.chunk_id
                results.append(
                    ScoredKnowledgeChunk(
                        chunk=chunk,
                        score=float(scores.get(chunk_id, 0.0)),
                        channels={
                            "vector": vector_rank_map.get(chunk_id),
                            "keyword": keyword_rank_map.get(chunk_id),
                            "entry": entry_rank_map.get(chunk_id),
                        },
                    )
                )
            return results

    def _entry_title_candidates(self, query_text: str) -> list[tuple[int, bool, str]]:
        """词条名命中通道：查询包含/前缀命中某条目标题（或其切分段）时返回该词条的块。

        例：查询「纳西妲的元素战技叫什么」包含词条《纳西妲》→ 其页面块
        经 RRF 双倍权重优先于正文堆满相近词的机制/攻略页。wiki 库标题存储为
        「标题·来源」，比对时剥掉来源后缀；人格知识库标题即文件名，按
        ``_``/``-``/空白切分后逐段比对（包含命中或 2~4 字中文前缀命中，
        见 ``_entry_title_match_len``）。先走 FTS trigram 标题列取有界
        候选，再在 Python 侧做切分/前缀校验，避免 20 万行级全表扫描
        （实测全表 instr 需 0.6~10 秒）。

        返回 ``(match_len, exact, chunk_id)`` 列表，按命中长度降序；
        ``exact=True`` 表示标题整段出现在查询中（供检索置顶，见 retrieve）。
        """
        text = str(query_text or "").strip()
        if len(text) < 2 or not self.ensure_fts_index():
            return []
        # 全文 3 字滑窗覆盖中英混排边界词（「你知道AI梗…」→ 道AI/AI梗），
        # 再补 3~6 字纯 CJK 短段整段匹配（词条名整体命中）。
        windows = [text[index : index + 3] for index in range(len(text) - 2)]
        for match in _CJK_RE.finditer(text):
            segment = match.group(0)
            if _FTS_MIN_MATCH_CHARS <= len(segment) <= 6:
                windows.append(segment)
        windows = list(dict.fromkeys(windows))[:_MAX_PHRASE_TERMS]
        if not windows:
            return []
        match_query = "{title} : (" + " OR ".join(f'"{w}"' for w in windows) + ")"
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    f"SELECT chunk_id, title FROM {_FTS_TABLE_NAME} "
                    f"WHERE {_FTS_TABLE_NAME} MATCH ? LIMIT 400",
                    (match_query,),
                ).fetchall()
        except sqlite3.Error:
            return []
        scored: list[tuple[int, bool, str]] = []
        for row in rows:
            title = str(row["title"] or "")
            match_len = _entry_title_match_len(title, text)
            if match_len:
                scored.append((match_len, _title_exact_hit(title, text), str(row["chunk_id"])))
        scored.sort(key=lambda triple: (-triple[0], triple[2]))
        return scored[: max(1, self.top_k) * 3]

    def _brute_candidates_python(
        self, query_vector: list[float], limit: int
    ) -> tuple[list[str], float]:
        """纯 Python 暴力余弦：返回 (按相似度降序的 chunk_id, 最高余弦)。"""
        scored: list[tuple[float, str]] = []
        for row in self._vector_rows():
            try:
                vector = json.loads(str(row["vector_json"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            scored.append(
                (_cosine_similarity(query_vector, vector), str(row["chunk_id"]))
            )
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        scored = scored[: max(0, int(limit))]
        return (
            [chunk_id for _, chunk_id in scored],
            float(scored[0][0]) if scored else 0.0,
        )

    def _vector_candidates(
        self, query_vector: list[float]
    ) -> tuple[list[str], float]:
        """向量通道候选：HNSW 命中则用近似分数，否则 numpy/纯 Python 暴力。

        返回 (按余弦降序的 chunk_id, 最高余弦)；候选数量为
        max(top_k*4, 20)，只用于 RRF 排序，正文仍由 _fetch_chunks 懒加载。
        """
        limit = max(self.top_k * _VECTOR_CANDIDATE_FACTOR, _VECTOR_CANDIDATE_FLOOR)
        ann_ranked = self._ann_candidates(query_vector, limit)
        if ann_ranked is not None:
            chunk_ids = [chunk_id for chunk_id, _score in ann_ranked]
            best = float(ann_ranked[0][1]) if ann_ranked else 0.0
            if isnan(best):
                best = 0.0
            return chunk_ids, best
        if np is None:
            return self._brute_candidates_python(query_vector, limit)
        try:
            matrix, chunk_ids = self._load_vector_cache()
            if matrix is None or not chunk_ids:
                return [], 0.0
            query_array = np.asarray(query_vector, dtype=np.float32)
            # 查询向量必须归一化：matrix 已按行归一化，不归一查询时
            # scores = cos * ||q||，得分被查询模长缩放，min_cosine_threshold 失效。
            query_norm = float(np.linalg.norm(query_array))
            if query_norm < 1e-9:
                return [], 0.0
            query_array = (query_array / query_norm).astype(np.float32)
            norms = np.linalg.norm(matrix, axis=1)
            matrix_norm = matrix / np.maximum(norms, 1e-9)[:, None]
            scores = matrix_norm @ query_array
            count = min(int(limit), len(chunk_ids))
            if count <= 0:
                return [], 0.0
            top_indices = np.argsort(-scores)[:count]
            ranked_ids = [chunk_ids[int(index)] for index in top_indices]
            best = float(scores[int(top_indices[0])])
            if isnan(best):
                best = 0.0
            return ranked_ids, best
        except Exception:  # noqa: BLE001 - 维度/缓存异常时退回纯 Python 路径。
            return self._brute_candidates_python(query_vector, limit)

    def _fetch_chunks(self, chunk_ids: list[str]) -> list[KnowledgeChunk]:
        if not chunk_ids:
            return []
        placeholders = ",".join("?" for _ in chunk_ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT chunk_id, source_id, title, content
                FROM knowledge_chunks WHERE chunk_id IN ({placeholders})
                """,
                chunk_ids,
            ).fetchall()
        by_id = {str(row["chunk_id"]): row for row in rows}
        chunks: list[KnowledgeChunk] = []
        for chunk_id in chunk_ids:
            row = by_id.get(chunk_id)
            if row is None:
                continue
            chunks.append(
                KnowledgeChunk(
                    chunk_id=str(row["chunk_id"]),
                    source_id=str(row["source_id"] or ""),
                    title=str(row["title"] or ""),
                    content=str(row["content"] or ""),
                )
            )
        return chunks

    def _ann_files(self) -> tuple[str, str]:
        return self.ann_index_path, self.ann_order_path

    def load_ann_index(self) -> bool:
        """签名匹配时 mmap 加载 HNSW 索引；缺失/过期返回 False 回退暴力。"""
        if faiss is None:
            return False
        if self._ann_index is not None and self._ann_order is not None:
            return True
        index_path, order_path = self._ann_files()
        try:
            if not Path(index_path).exists() or not Path(order_path).exists():
                return False
            stored_ann = self._stored_ann_signature()
            if not stored_ann or stored_ann != self.signature:
                return False
            index = faiss.read_index(str(index_path), faiss.IO_FLAG_MMAP)
            cast(Any, index).hnsw.efSearch = 64
            order = json.loads(Path(order_path).read_text(encoding="utf-8"))
            if not isinstance(order, list):
                return False
            self._ann_index = index
            self._ann_order = [str(item) for item in order]
            return True
        except Exception:  # noqa: BLE001 - 索引损坏/不可读时回退。
            self._ann_index = None
            self._ann_order = None
            return False

    def _ann_candidates(
        self, query_vector: list[float], limit: int
    ) -> list[tuple[str, float]] | None:
        """HNSW 近似检索候选：返回 (chunk_id, 内积分数) 降序；不可用返回 None。

        向量已按 L2 归一化 + METRIC_INNER_PRODUCT，因此内积即余弦相似度。
        """
        if not self.load_ann_index():
            return None
        index = self._ann_index
        order = self._ann_order
        if index is None or order is None:
            return None
        try:
            query = np.asarray(query_vector, dtype=np.float32).reshape(1, -1)
            norm = float(np.linalg.norm(query))
            if norm > 0:
                query = query / norm
            _scores, indices = index.search(query, max(1, int(limit)))
            ranked: list[tuple[str, float]] = []
            for score, index in zip(_scores[0], indices[0]):
                if 0 <= int(index) < len(order):
                    ranked.append((str(order[int(index)]), float(score)))
            return ranked
        except Exception:  # noqa: BLE001
            return None

    def build_ann_index(self, on_progress=None) -> dict:
        """由 knowledge-sync 调用：把全部向量归一化写入 faiss HNSW 并落盘。

        向量按批从 SQLite 流式读出、逐批归一化 add 进索引——此前一次性
        fetchall + vstack 全量矩阵，10 万 chunk 级语料会产生数百 MB 内存尖峰。
        """
        if faiss is None:
            # faiss 缺失不影响关键词索引：仍幂等构建 FTS，供关键词/降级检索使用。
            self.ensure_fts_index(force=True)
            return {"built": False, "reason": "faiss_missing"}
        with self._maintenance_lock:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    SELECT chunk_id, vector_blob, vector_json
                    FROM knowledge_chunks
                    WHERE vector_json IS NOT NULL AND vector_json != ''
                    """
                )
                chunk_ids: list[str] = []
                index = None
                while True:
                    rows = cursor.fetchmany(_ANN_BUILD_BATCH_SIZE)
                    if not rows:
                        break
                    batch_vectors: list = []
                    for row in rows:
                        raw_blob = row["vector_blob"]
                        vector = None
                        if isinstance(raw_blob, (bytes, bytearray, memoryview)):
                            try:
                                parsed = np.frombuffer(bytes(raw_blob), dtype=np.float32)
                                if parsed.size > 0:
                                    vector = parsed.astype(np.float32)
                            except Exception:  # noqa: BLE001
                                vector = None
                        if vector is None:
                            try:
                                vector = np.asarray(
                                    json.loads(str(row["vector_json"])), dtype=np.float32
                                )
                            except (TypeError, ValueError, json.JSONDecodeError):
                                continue
                        batch_vectors.append(vector)
                        chunk_ids.append(str(row["chunk_id"]))
                    if not batch_vectors:
                        continue
                    matrix = np.vstack(batch_vectors).astype(np.float32)
                    norms = np.linalg.norm(matrix, axis=1).astype(np.float32)
                    matrix = (matrix / np.maximum(norms, np.float32(1e-9))[:, None]).astype(np.float32)
                    if index is None:
                        try:
                            faiss.omp_set_num_threads(1)
                        except Exception:  # noqa: S110, BLE001 - 线程数设置失败按默认继续构建索引。
                            pass
                        dimension = int(matrix.shape[1])
                        index = faiss.IndexHNSWFlat(dimension, 32, faiss.METRIC_INNER_PRODUCT)
                        index.hnsw.efConstruction = 200
                    index.add(matrix)
                    if on_progress is not None:
                        try:
                            on_progress(len(chunk_ids))
                        except Exception:  # noqa: S110, BLE001 - 进度回调失败不影响构建。
                            pass
            if index is None or not chunk_ids:
                self.ensure_fts_index()
                return {"built": False, "reason": "empty"}
            index_path, order_path = self._ann_files()
            Path(index_path).parent.mkdir(parents=True, exist_ok=True)
            faiss.write_index(index, str(index_path))
            Path(order_path).write_text(
                json.dumps(chunk_ids, ensure_ascii=False), encoding="utf-8"
            )
            self._set_stored_ann_signature(self.signature)
            self._ann_index = None
            self._ann_order = None
            # knowledge-sync 一次性构建：ANN 落盘后顺带幂等构建 FTS 关键词索引。
            self.ensure_fts_index(force=True)
            return {"built": True, "vectors": len(chunk_ids), "dim": int(index.d)}

    def _stored_ann_signature(self) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM knowledge_meta WHERE key = 'ann_signature'"
            ).fetchone()
        return str(row[0]) if row else ""

    def _set_stored_ann_signature(self, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO knowledge_meta (key, value) VALUES ('ann_signature', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (value,),
            )

    def _load_vector_cache(self):
        """把全部向量一次性载入 numpy 矩阵并缓存；只保留 chunk_id，正文懒加载。

        R3 停摆批改造：流式 fetchmany + blob 优先 + 单飞构建。
        旧实现全表 fetchall 同时物化 vector_json 文本（kb_wiki 23.8 万行 ×
        ~20KB 文本 + blob ≈ 库文件 5.7GB 全部过 Python 手），首载即 GB 级
        内存尖峰 + 分钟级 JSON 解析；现逐批读取，blob（4 字节/维 float32）
        命中即收，JSON 通道只对 blob 缺失/损坏的残行按批二次查询。
        构建由 _vector_cache_build_lock 单飞互斥（并发首载只做一次），
        热缓存读取路径零锁开销。
        """
        if self._vector_cache is not None and self._vector_meta is not None:
            return self._vector_cache, self._vector_meta
        with self._vector_cache_build_lock:
            if self._vector_cache is not None and self._vector_meta is not None:
                return self._vector_cache, self._vector_meta
            matrix, chunk_ids = self._build_vector_cache()
            # 全库无向量返回 (None, None)：与旧实现一致不驻留"空缓存"标记，
            # 但空表重扫成本趋近于零，不值得引入哨兵对象。
            self._vector_cache = matrix
            self._vector_meta = chunk_ids if matrix is not None else None
            return self._vector_cache, self._vector_meta

    def _build_vector_cache(self):
        """流式全表读取向量，构建 (matrix|None, chunk_ids|None)；不取检索锁。

        锁序约束：调用方持有 _vector_cache_build_lock，本方法内部绝不取
        self._lock（否则锁外预热会与检索路径成环）。行序 = 表序，与旧实现
        一致（chunk_ids 与矩阵行对齐）。
        """
        vectors: list = []
        chunk_ids: list[str] = []
        blob_miss_ids: list[str] = []
        with self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT chunk_id, vector_blob
                FROM knowledge_chunks
                WHERE vector_json IS NOT NULL AND vector_json != ''
                """
            )
            while True:
                rows = cursor.fetchmany(_VECTOR_CACHE_LOAD_BATCH_SIZE)
                if not rows:
                    break
                for row in rows:
                    raw_blob = row["vector_blob"]
                    vector = None
                    if isinstance(raw_blob, (bytes, bytearray, memoryview)):
                        try:
                            parsed = np.frombuffer(bytes(raw_blob), dtype=np.float32)
                            if parsed.size > 0:
                                vector = parsed.astype(np.float32)
                        except Exception:  # noqa: BLE001 - 单行向量解码失败走 JSON 兜底。
                            vector = None
                    if vector is None:
                        blob_miss_ids.append(str(row["chunk_id"]))
                        continue
                    vectors.append(vector)
                    chunk_ids.append(str(row["chunk_id"]))
            # blob 缺失/损坏的残行回退 JSON 通道（有界分批 IN 查询，不整表取文本）。
            for start in range(0, len(blob_miss_ids), 500):
                batch_ids = blob_miss_ids[start : start + 500]
                placeholders = ",".join("?" for _ in batch_ids)
                try:
                    json_rows = connection.execute(
                        "SELECT chunk_id, vector_json FROM knowledge_chunks "
                        f"WHERE chunk_id IN ({placeholders})",
                        batch_ids,
                    ).fetchall()
                except sqlite3.Error:
                    continue
                for row in json_rows:
                    try:
                        vector = json.loads(str(row["vector_json"]))
                    except (TypeError, ValueError, json.JSONDecodeError):
                        continue
                    if vector:
                        vectors.append(np.asarray(vector, dtype=np.float32))
                        chunk_ids.append(str(row["chunk_id"]))
        if not vectors:
            return None, None
        return np.vstack(vectors).astype(np.float32), chunk_ids

    def _pending_rows(self) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return list(
                connection.execute(
                    """
                    SELECT chunk_id, content
                    FROM knowledge_chunks
                    WHERE vector_json IS NULL OR vector_json = ''
                    """
                ).fetchall()
            )

    def _vector_rows(self) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return list(
                connection.execute(
                    """
                    SELECT chunk_id, source_id, title, content, vector_json
                    FROM knowledge_chunks
                    WHERE vector_json IS NOT NULL AND vector_json != ''
                    """
                ).fetchall()
            )

    def _embed(self, texts: list[str]) -> list[list[float]] | None:
        if not texts:
            return []
        try:
            result = self.embed_provider.embed_texts(list(texts))
        except Exception:  # noqa: BLE001 - 嵌入服务失败时返回 None 表示重试/降级。
            return None
        if not isinstance(result, list) or len(result) != len(texts):
            return None
        return result

    def _save_vectors(
        self,
        rows: list[sqlite3.Row],
        vectors: list[list[float]],
    ) -> bool:
        # 维度一致性守卫：本地/远程嵌入链回退可能产出不同维度，混入后
        # numpy 路径会静默退化成 zip 截断的伪余弦，min_cosine_threshold 失真。
        lengths = {len(vector) for vector in vectors if vector}
        if len(lengths) != 1:
            return False
        with self._lock:
            stored_dim = self._vector_dim
        if stored_dim is not None and lengths and next(iter(lengths)) != stored_dim:
            return False
        try:
            with self._connect() as connection:
                for row, vector in zip(rows, vectors):
                    connection.execute(
                        "UPDATE knowledge_chunks SET vector_json = ?, vector_blob = ? WHERE chunk_id = ?",
                        (
                            json.dumps(vector),
                            struct.pack(f"<{len(vector)}f", *vector),
                            str(row["chunk_id"]),
                        ),
                    )
                if stored_dim is None and lengths:
                    connection.execute(
                        "INSERT INTO knowledge_meta (key, value) VALUES ('vector_dim', ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (str(next(iter(lengths))),),
                    )
            if stored_dim is None and lengths:
                with self._lock:
                    self._vector_dim = next(iter(lengths))
            self._invalidate_vector_cache()
            return True
        except (TypeError, ValueError, sqlite3.Error):
            return False

    # ---------- FTS5 BM25 关键词通道 -----------------------------------------

    def ensure_fts_index(self, *, force: bool = False) -> bool:
        """幂等地确保 FTS5 trigram 关键词索引可用（返回 True/False）。

        knowledge_meta 中已有非空 fts_signature 时直接复用，避免每条消息
        全量重建或全表扫描；内容刚变化（sync_chunks/sync_documents 会清掉
        该签名）或首次构建时才全量重建一次。签名由 chunk_id + content_hash
        聚合派生。``force=True`` 供显式同步任务绕过 fts_auto_rebuild=False。
        """
        with self._lock:
            # 快路径（本机延迟压榨项）：状态已确认（True 可用 / False 不可用）
            # 时直接返回，不再每条消息重复执行 sqlite_master 探查 + 签名
            # SELECT（关键词 + 词条两通道各调一次，合计 4 次往返/条）。
            # 内容变化由 _invalidate_fts 复位为 None 强制重新探查。
            if self._fts_valid is not None:
                return self._fts_valid
            try:
                self._ensure_fts_table()
                stored = self._stored_fts_signature()
                if stored:
                    # 非空签名说明索引与当前行集合匹配（内容变化时签名已被清空），
                    # 同时兼容 knowledge-sync 进程刚建好、运行期直接复用的情况。
                    self._fts_valid = True
                    return True
                if not force and not self.fts_auto_rebuild:
                    # 大库内联重建分钟级，会卡死消息处理：降级为纯向量通道，
                    # 等显式同步任务 force 重建。不置 _fts_valid=False，
                    # 重建完成后本进程可立即恢复关键词通道。
                    return False
                rebuilt = self._rebuild_fts()
                if rebuilt:
                    self._fts_valid = True
                    return True
                if self._stored_fts_signature():
                    # 本进程重建失败但可能由另一进程完成：信任已落库的签名。
                    self._fts_valid = True
                    return True
                self._fts_valid = False
                return False
            except Exception:  # noqa: BLE001 - FTS5 缺失/损坏时禁用关键词通道。
                self._fts_valid = False
                return False

    def _invalidate_fts(self) -> None:
        """内容变化后强制重探 FTS 通道（下一次访问重读签名/必要时重建）。

        必须无条件复位（含 True→None）：共享 store 进程内同步后 FTS 表
        已是旧行集合，若保留 True 快路径会让关键词通道一直命中被删文档
        的过期 chunk_id（_fetch_chunks 静默丢弃 → 召回静默劣化）。探查
        只有两条轻量查询，复位成本低。
        """
        self._fts_valid = None

    def _ensure_fts_table(self) -> None:
        """确保 FTS5 trigram 虚拟表存在；不可用时抛异常由调用方降级。"""
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (_FTS_TABLE_NAME,),
            ).fetchone()
            if existing is None:
                connection.execute(_FTS_CREATE_SQL)

    def _stored_fts_signature(self) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM knowledge_meta WHERE key = ?",
                (_FTS_SIGNATURE_KEY,),
            ).fetchone()
        return str(row[0]) if row else ""

    def _rebuild_fts(self) -> str | None:
        """全量重建 FTS 索引并写入内容签名；失败返回 None。

        只在知识库内容变化或首次构建时调用一次；签名由 chunk_id +
        content_hash 聚合派生（与向量索引同源，反映同一批行）。
        """
        try:
            with self._connect() as connection:
                digest = hashlib.sha1()
                cursor = connection.execute(
                    "SELECT chunk_id, content_hash FROM knowledge_chunks ORDER BY chunk_id"
                )
                for row in cursor:
                    digest.update(
                        f"{row['chunk_id']}:{row['content_hash'] or ''}|".encode()
                    )
                cursor.close()
                signature = digest.hexdigest()

                connection.execute(f"DROP TABLE IF EXISTS {_FTS_TABLE_NAME}")
                connection.execute(_FTS_CREATE_SQL)
                cursor = connection.execute(
                    "SELECT chunk_id, title, content FROM knowledge_chunks ORDER BY chunk_id"
                )
                for row in cursor:
                    connection.execute(
                        f"INSERT INTO {_FTS_TABLE_NAME} (chunk_id, title, content) "
                        "VALUES (?, ?, ?)",
                        (
                            str(row["chunk_id"]),
                            str(row["title"] or ""),
                            str(row["content"] or ""),
                        ),
                    )
                cursor.close()
                connection.execute(
                    """
                    INSERT INTO knowledge_meta (key, value) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (_FTS_SIGNATURE_KEY, signature),
                )
            return signature
        except sqlite3.Error:
            return None

    def _match_candidates(self, terms: list[str], limit: int) -> list[str]:
        """FTS5 trigram MATCH + bm25() 排名；只接受 >=3 字符的词。"""
        match_terms = [term for term in terms if len(term) >= _FTS_MIN_MATCH_CHARS]
        if not match_terms or limit <= 0:
            return []
        query = " OR ".join(match_terms)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT chunk_id
                FROM {_FTS_TABLE_NAME}
                WHERE {_FTS_TABLE_NAME} MATCH ?
                ORDER BY bm25({_FTS_TABLE_NAME})
                LIMIT ?
                """,
                (query, max(0, int(limit))),
            ).fetchall()
        return [str(row["chunk_id"]) for row in rows]

    def _title_like_candidates(self, terms: list[str], limit: int) -> list[str]:
        """1~2 字符词退化为 title LIKE（title 短、扫描成本低），按命中词数排序。"""
        if not terms or limit <= 0:
            return []
        conditions: list[str] = []
        params: list[str] = []
        for term in terms:
            conditions.append("title LIKE ? ESCAPE '\\'")
            params.append(f"%{_escape_like(term)}%")
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT DISTINCT title FROM knowledge_chunks WHERE {' OR '.join(conditions)}",
                params,
            ).fetchall()
            titles = sorted(
                {str(row["title"]) for row in rows},
                key=lambda title: (
                    -sum(1 for term in terms if term in str(title).lower()),
                    str(title),
                ),
            )
        ranked: list[str] = []
        if not titles:
            return ranked
        with self._connect() as connection:
            for title in titles:
                remaining = max(0, int(limit)) - len(ranked)
                if remaining <= 0:
                    break
                rows = connection.execute(
                    "SELECT chunk_id FROM knowledge_chunks "
                    "WHERE title = ? ORDER BY chunk_id LIMIT ?",
                    (title, remaining),
                ).fetchall()
                ranked.extend(str(row["chunk_id"]) for row in rows)
        return ranked

    def _phrase_match_candidates(self, query_text: str, limit: int) -> list[str]:
        """整段中文/英数词直接做 trigram MATCH（中文需 >=3 字才可被 trigram 命中）。

        ``_query_terms`` 只产中文二元组，永远无法触发 >=3 字的 trigram 索引；
        本方法把原始查询里的连续中文片段拆成 3 字滑窗（长片段整体匹配不到时
        仍能靠“守岸人/黑海岸”这类 3 字串命中），加英文数字词，再按 bm25() 排序。
        """
        if limit <= 0:
            return []
        phrases: list[str] = []
        for match in _CJK_RE.finditer(query_text or ""):
            segment = match.group(0)
            if len(segment) >= _FTS_MIN_MATCH_CHARS:
                if len(segment) <= 6:
                    phrases.append(segment)
                for index in range(len(segment) - 2):
                    phrases.append(segment[index : index + 3])
        phrases.extend(match.group(0).lower() for match in _ALNUM_RE.finditer(query_text or ""))
        phrases = list(dict.fromkeys(phrases))[:_MAX_PHRASE_TERMS]
        if not phrases:
            return []
        query = " OR ".join(f'"{phrase}"' for phrase in phrases)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT chunk_id
                FROM {_FTS_TABLE_NAME}
                WHERE {_FTS_TABLE_NAME} MATCH ?
                ORDER BY bm25({_FTS_TABLE_NAME})
                LIMIT ?
                """,
                (query, max(0, int(limit))),
            ).fetchall()
        return [str(row["chunk_id"]) for row in rows]

    def _content_like_candidates(self, terms: list[str], limit: int) -> list[str]:
        """1~2 字符词退化为 content LIKE，按命中词数降序、有界返回。

        真实知识库每个源只有一个 title（文件名），title LIKE 几乎无法区分
        chunk，因此用正文 LIKE 兜底短词；查询词只含中文/英数（无 ``%``/``_``），
        无需 ESCAPE。常见功能字组成的噪声二元组会被停用字过滤。
        """
        if not terms or limit <= 0:
            return []
        kept = [
            term
            for term in terms
            if not any(char in _SHORT_TERM_STOP_CHARS for char in term)
        ]
        if not kept:
            return []
        conditions = " OR ".join("content LIKE ?" for _ in kept)
        params = [f"%{term}%" for term in kept]
        score_sql = " + ".join("CASE WHEN content LIKE ? THEN 1 ELSE 0 END" for _ in kept)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT chunk_id
                FROM knowledge_chunks
                WHERE {conditions}
                ORDER BY ({score_sql}) DESC, chunk_id
                LIMIT ?
                """,
                (*params, *params, max(0, int(limit))),
            ).fetchall()
        return [str(row["chunk_id"]) for row in rows]

    def _keyword_candidates(self, query_text: str) -> list[str]:
        """关键词通道候选（按相关性降序）。

        编排：整段短语 MATCH（中文专名）→ 分词 MATCH（英数词）→
        短词正文 LIKE（中文二元组）→ title LIKE（最后兜底）。
        只有 FTS 虚拟表查询出错才判定索引损坏并清签名；LIKE 兜底出错
        只丢弃该兜底，不连坐索引。
        """
        if not self.ensure_fts_index():
            return []
        terms = _query_terms(query_text)
        if not terms:
            return []
        limit = max(1, self.top_k * _KEYWORD_CANDIDATE_FACTOR)
        ranked: list[str] = []

        def _append(candidates: list[str]) -> None:
            for chunk_id in candidates:
                if chunk_id not in ranked:
                    ranked.append(chunk_id)
                if len(ranked) >= limit:
                    return

        try:
            _append(self._phrase_match_candidates(query_text, limit))
            if len(ranked) < limit:
                _append(self._match_candidates(terms, limit - len(ranked)))
        except sqlite3.Error:
            # 虚拟表可能被并发重建/损坏：清掉签名并标记未知，下次查询重建。
            try:
                with self._connect() as connection:
                    connection.execute(
                        "DELETE FROM knowledge_meta WHERE key = ?",
                        (_FTS_SIGNATURE_KEY,),
                    )
            except sqlite3.Error:
                pass
            self._fts_valid = None
            return []

        like_terms = [
            term for term in terms if len(term) < _FTS_MIN_MATCH_CHARS
        ]
        try:
            if len(ranked) < limit:
                _append(
                    self._content_like_candidates(like_terms, limit - len(ranked))
                )
        except sqlite3.Error:
            pass
        try:
            if len(ranked) < limit:
                _append(
                    self._title_like_candidates(like_terms, limit - len(ranked))
                )
        except sqlite3.Error:
            pass
        return ranked


def _query_terms(text: str) -> list[str]:
    """提取用于关键词检索的英文/数字词与中文二元组。"""
    terms: list[str] = []
    for match in re.finditer(r"[A-Za-z0-9_]+", text or ""):
        terms.append(match.group(0).lower())
    cjk = "".join(re.findall(r"[一-鿿]", text or ""))
    for index in range(max(0, len(cjk) - 1)):
        terms.append(cjk[index : index + 2])
    return list(dict.fromkeys(terms))


class KeywordKnowledgeRetriever:
    """跨文件关键词检索：向量嵌入未启用/不可用时的可用回退。"""

    available = True

    def __init__(
        self,
        files: list[Path],
        top_k: int = 4,
        chunk_chars: int = 900,
    ) -> None:
        self._files = [Path(path).expanduser() for path in files]
        self._top_k = max(0, int(top_k))
        self._chunk_chars = max(_MIN_CHUNK_CHARS, int(chunk_chars))
        self._lock = threading.RLock()
        self._cache: dict[Path, tuple[tuple[int, int], list[tuple[str, str, str]]]] = {}

    def _signature(self, path: Path) -> tuple[int, int] | None:
        return _file_signature(path)

    def _sync_path(self, path: Path) -> None:
        signature = self._signature(path)
        if signature is None:
            return
        cached = self._cache.get(path)
        if cached is not None and cached[0] == signature:
            return
        text = load_character_document(path)
        source_id = path.stem
        rows: list[tuple[str, str, str]] = []
        for index, content in enumerate(_chunk_text(text, chunk_chars=self._chunk_chars), start=1):
            chunk_id = hashlib.sha1(
                f"{path.as_posix()}:{index}:{content}".encode()
            ).hexdigest()
            rows.append((chunk_id, source_id, content))
        self._cache[path] = (signature, rows)

    def retrieve(self, query_text: str) -> list[KnowledgeChunk]:
        terms = _query_terms(query_text)
        if not terms:
            return []
        with self._lock:
            for path in self._files:
                self._sync_path(path)
            scored: list[tuple[int, str, KnowledgeChunk]] = []
            for _signature, rows in self._cache.values():
                for chunk_id, source_id, content in rows:
                    overlap = sum(1 for term in terms if term in content)
                    if overlap <= 0:
                        continue
                    scored.append(
                        (
                            overlap,
                            chunk_id,
                            KnowledgeChunk(
                                chunk_id=chunk_id,
                                source_id=source_id,
                                title=source_id,
                                content=content,
                            ),
                        )
                    )
            scored.sort(key=lambda pair: (-pair[0], pair[1]))
            return [chunk for _, _, chunk in scored[: self._top_k]]


def build_keyword_knowledge_provider(config: object) -> object:
    files = [
        Path(path).expanduser()
        for path in (getattr(config, "bot_knowledge_files", []) or [])
    ]
    if not files:
        return _UnavailableVectorKnowledgeProvider()
    return KeywordKnowledgeRetriever(
        files=files,
        top_k=int(_first_defined(config, "bot_knowledge_top_k", 4)),
        chunk_chars=int(_first_defined(config, "bot_knowledge_chunk_chars", 900)),
    )


class _UnavailableVectorKnowledgeProvider:
    available = False

    def retrieve(self, query_text: str) -> list[KnowledgeChunk]:
        return []


class _VectorKnowledgeRetriever:
    available = True

    def __init__(self, store: SqliteVectorKnowledgeStore, files: list[Path]) -> None:
        self._store = store
        self._files = files

    def retrieve(self, query_text: str) -> list[KnowledgeChunk]:
        try:
            return self._store.retrieve(
                query_text,
                files=self._files,
                embed_backlog=False,
            )
        except Exception:  # noqa: BLE001 - 检索异常按无结果降级，不阻断对话。
            return []


def _first_defined(config: object, name: str, default):
    value = getattr(config, name, None)
    if value is None:
        return default
    if isinstance(value, str) and not value.strip():
        return default
    return value


def build_vector_knowledge_provider(
    config: object,
    *,
    timeout_override: float | None = None,
) -> object:
    enabled = bool(getattr(config, "bot_embedding_enabled", False))
    model = str(getattr(config, "bot_embedding_model", "") or "").strip()
    base_url = str(getattr(config, "bot_embedding_base_url", "") or "").strip()
    local_models = str(
        getattr(config, "bot_embedding_local_models", "") or ""
    ).strip()
    local_base_url = str(
        getattr(config, "bot_embedding_local_base_url", "") or ""
    ).strip()
    local_enabled = bool(getattr(config, "bot_embedding_local_enabled", True))
    remote_configured = bool(model and base_url)
    local_configured = bool(local_enabled and local_models and local_base_url)
    if not enabled or not (remote_configured or local_configured):
        return _UnavailableVectorKnowledgeProvider()
    try:
        configured_timeout = float(
            _first_defined(config, "bot_embedding_timeout_seconds", 15.0)
        )
        configured_local_timeout = float(
            _first_defined(config, "bot_embedding_local_timeout_seconds", 60.0)
        )
        effective_timeout = (
            max(0.5, float(timeout_override))
            if timeout_override is not None
            else configured_timeout
        )
        effective_local_timeout = (
            max(0.5, float(timeout_override))
            if timeout_override is not None
            else configured_local_timeout
        )
        embed_provider = OpenAICompatibleEmbeddingProvider(
            base_url=base_url,
            model=model,
            api_key=str(getattr(config, "bot_embedding_api_key", "") or ""),
            timeout_seconds=effective_timeout,
            dimensions=int(_first_defined(config, "bot_embedding_dimensions", 1024)),
            local_base_url=local_base_url,
            local_models=local_models,
            local_api_key=str(
                getattr(config, "bot_embedding_local_api_key", "") or ""
            ),
            local_enabled=local_enabled,
            local_timeout_seconds=effective_local_timeout,
        )
        store = SqliteVectorKnowledgeStore(
            db_path=str(
                _first_defined(
                    config,
                    "bot_knowledge_db_path",
                    "data/knowledge_embeddings.sqlite3",
                )
            ),
            embed_provider=embed_provider,
            chunk_chars=int(_first_defined(config, "bot_knowledge_chunk_chars", 900)),
            top_k=int(_first_defined(config, "bot_knowledge_top_k", 4)),
            signature=getattr(embed_provider, "signature", ""),
            auto_reset=False,
            # 与 kb_wiki 同策略：请求路径发现 FTS 签名缺失不做分钟级内联
            # 重建（会持锁卡死全部会话），重建由 knowledge-sync force 负责。
            fts_auto_rebuild=False,
        )
        files = [
            Path(path).expanduser()
            for path in (getattr(config, "bot_knowledge_files", []) or [])
        ]
        return _VectorKnowledgeRetriever(store=store, files=files)
    except Exception:  # noqa: BLE001 - 向量库构建失败时降级为不可用提供者。
        return _UnavailableVectorKnowledgeProvider()