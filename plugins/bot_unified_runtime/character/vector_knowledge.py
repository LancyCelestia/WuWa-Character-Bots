from __future__ import annotations

import hashlib
import json
import re
import struct

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
from dataclasses import dataclass
from math import isnan, sqrt
from pathlib import Path
from typing import Any, Protocol, cast

import httpx

from plugins.bot_unified_runtime.contracts import KnowledgeChunk

from .documents import load_character_document

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
        """批量编码：本地优先、远程兜底；模型列表内部依次回退。"""
        if not texts:
            return []
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


def _rrf_fuse(
    vector_ids: list[str],
    keyword_ids: list[str],
    top_k: int,
    k: float = _RRF_K,
) -> list[str]:
    """Reciprocal Rank Fusion：把两个通道的排序融合成一个稳定排序。

    只做排序，不加载正文；同一 chunk 同时命中两通道时会获得更高权重。
    """
    scores: dict[str, float] = {}
    for rank, chunk_id in enumerate(vector_ids):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
    for rank, chunk_id in enumerate(keyword_ids):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
    ranked = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))
    return ranked[: max(0, int(top_k))]


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
        self._vector_cache: Any | None = None
        self._vector_meta: list[dict] | None = None
        # FTS5 关键词通道状态；None 表示“本进程尚未确认”，
        # False 表示已确认不可用（仅在知识库内容变化后重试）。
        self._fts_valid: bool | None = None
        # 低置信未命中阈值：无关键词命中且向量最高余弦低于该值时返回空结果。
        self.min_cosine_threshold = float(min_cosine_threshold)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        if self.db_path != ":memory:":
            Path(self.db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
                """
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
        self._set_stored_signature("")
        self._invalidate_vector_cache()
        return True

    def _embed_all_pending(self, on_progress=None) -> tuple[int, int]:
        """把全部待嵌入行编码入库；完成后记录模型指纹，失败可断点续跑。

        on_progress(done, total) 每处理一批调用一次，用于打印进度。
        """
        self._reset_vectors_if_needed()
        pending = self._pending_rows()
        done = 0
        for batch in _batches(pending, _EMBED_BATCH_SIZE):
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

    def _connect(self) -> sqlite3.Connection:

        connection = sqlite3.connect(self.db_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def sync_chunks(self, files: list[Path]) -> None:
        with self._lock:
            paths = [Path(path).expanduser() for path in files]
            changed = False
            with self._connect() as connection:
                # 已从 BOT_KNOWLEDGE_FILES 移除的旧文件不再保留在知识库里。
                source_ids = [path.stem for path in paths]
                if source_ids:
                    placeholders = ",".join("?" for _ in source_ids)
                    cursor = connection.execute(
                        f"DELETE FROM knowledge_chunks WHERE source_id NOT IN ({placeholders})",
                        source_ids,
                    )
                    if cursor.rowcount > 0:
                        changed = True
                for path in paths:
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

                if changed:
                    # 内容/行集合变化会改变 FTS 索引内容：先删除共享签名，
                    # 让本进程与 knowledge-sync 进程都判定索引过期并在下次查询时重建。
                    connection.execute(
                        "DELETE FROM knowledge_meta WHERE key = 'fts_signature'"
                    )
            if changed:
                self._invalidate_vector_cache()
                self._invalidate_fts()

    def embed_pending(
        self,
        files: list[Path] | None = None,
        on_progress=None,
    ) -> tuple[int, int]:
        """预建库：同步文件切片后把未向量化的行全部嵌入。

        模型/端点指纹变化时自动清空旧向量重嵌；返回
        (本次成功嵌入行数, 处理前待嵌入行数)；中途失败即停止、可断点续跑。
        """
        with self._lock:
            if files:
                self.sync_chunks(list(files))
            return self._embed_all_pending(on_progress=on_progress)

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

            # 双通道候选：BM25/FTS 关键词 + 向量（HNSW/暴力），再 RRF 融合。
            keyword_ranked = self._keyword_candidates(str(query_text))
            vector_ranked, best_cosine = self._vector_candidates(query_vector)
            fused_ids = _rrf_fuse(vector_ranked, keyword_ranked, self.top_k)
            if not fused_ids:
                return []
            # 低置信未命中：既没有关键词命中、向量最强余弦也低于阈值 -> 空结果。
            if not keyword_ranked and best_cosine < self.min_cosine_threshold:
                return []
            return self._fetch_chunks(fused_ids)

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

    def _brute_force_python(self, query_vector: list[float]) -> list[KnowledgeChunk]:
        chunk_ids, _best = self._brute_candidates_python(query_vector, self.top_k)
        return self._fetch_chunks(chunk_ids)

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

    def _try_ann_search(self, query_vector: list[float]) -> list[KnowledgeChunk] | None:
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
            _scores, indices = index.search(query, self.top_k)
            picked_ids = [
                str(order[int(index)])
                for index in indices[0]
                if 0 <= int(index) < len(order)
            ]
            return self._fetch_chunks(picked_ids)
        except Exception:  # noqa: BLE001
            return None

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
        """由 knowledge-sync 调用：把全部向量归一化写入 faiss HNSW 并落盘。"""
        if faiss is None:
            # faiss 缺失不影响关键词索引：仍幂等构建 FTS，供关键词/降级检索使用。
            self.ensure_fts_index()
            return {"built": False, "reason": "faiss_missing"}
        with self._lock:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT chunk_id, vector_blob, vector_json
                    FROM knowledge_chunks
                    WHERE vector_json IS NOT NULL AND vector_json != ''
                    """
                ).fetchall()
            vectors: list = []
            chunk_ids: list[str] = []
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
                vectors.append(vector)
                chunk_ids.append(str(row["chunk_id"]))
            if not vectors:
                self.ensure_fts_index()
                return {"built": False, "reason": "empty"}
            matrix = np.vstack(vectors).astype(np.float32)
            norms = np.linalg.norm(matrix, axis=1).astype(np.float32)
            matrix = (matrix / np.maximum(norms, np.float32(1e-9))[:, None]).astype(np.float32)
            dimension = int(matrix.shape[1])
            try:
                faiss.omp_set_num_threads(1)
            except Exception:  # noqa: S110, BLE001 - 线程数设置失败按默认继续构建索引。
                pass
            index = faiss.IndexHNSWFlat(dimension, 32, faiss.METRIC_INNER_PRODUCT)
            index.hnsw.efConstruction = 200
            index.add(matrix)
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
            self.ensure_fts_index()
            return {"built": True, "vectors": len(chunk_ids), "dim": dimension}

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
        """把全部向量一次性载入 numpy 矩阵并缓存；只保留 chunk_id，正文懒加载。"""
        if self._vector_cache is not None and self._vector_meta is not None:
            return self._vector_cache, self._vector_meta
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT chunk_id, vector_json, vector_blob
                FROM knowledge_chunks
                WHERE vector_json IS NOT NULL AND vector_json != ''
                """
            ).fetchall()
        vectors: list = []
        chunk_ids: list[str] = []
        for row in rows:
            raw_blob = row["vector_blob"]
            if isinstance(raw_blob, (bytes, bytearray, memoryview)):
                try:
                    vector = np.frombuffer(bytes(raw_blob), dtype=np.float32)
                    if vector.size > 0:
                        vectors.append(vector.astype(np.float32))
                        chunk_ids.append(str(row["chunk_id"]))
                        continue
                except Exception:  # noqa: S110, BLE001 - 单行向量解码失败跳过该行。
                    pass
            try:
                vector = json.loads(str(row["vector_json"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if vector:
                vectors.append(np.asarray(vector, dtype=np.float32))
                chunk_ids.append(str(row["chunk_id"]))
        if not vectors:
            self._vector_cache = None
            self._vector_meta = None
            return None, None
        self._vector_cache = np.vstack(vectors).astype(np.float32)
        self._vector_meta = chunk_ids
        return self._vector_cache, self._vector_meta

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
            self._invalidate_vector_cache()
            return True
        except (TypeError, ValueError, sqlite3.Error):
            return False

    # ---------- FTS5 BM25 关键词通道 -----------------------------------------

    def ensure_fts_index(self) -> bool:
        """幂等地确保 FTS5 trigram 关键词索引可用（返回 True/False）。

        knowledge_meta 中已有非空 fts_signature 时直接复用，避免每条消息
        全量重建或全表扫描；内容刚变化（sync_chunks 会清掉该签名）或首次
        构建时才全量重建一次。签名由 chunk_id + content_hash 聚合派生。
        """
        with self._lock:
            if self._fts_valid is False:
                return False
            try:
                self._ensure_fts_table()
                stored = self._stored_fts_signature()
                if stored:
                    # 非空签名说明索引与当前行集合匹配（内容变化时签名已被清空），
                    # 同时兼容 knowledge-sync 进程刚建好、运行期直接复用的情况。
                    self._fts_valid = True
                    return True
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
        """内容变化后允许此前判定“不可用”的 FTS 通道重试一次。"""
        if self._fts_valid is False:
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
        try:
            stat = path.stat()
            return (stat.st_mtime_ns, stat.st_size)
        except OSError:
            return None

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


def build_vector_knowledge_provider(config: object) -> object:
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
        embed_provider = OpenAICompatibleEmbeddingProvider(
            base_url=base_url,
            model=model,
            api_key=str(getattr(config, "bot_embedding_api_key", "") or ""),
            timeout_seconds=float(
                _first_defined(config, "bot_embedding_timeout_seconds", 15.0)
            ),
            dimensions=int(_first_defined(config, "bot_embedding_dimensions", 1024)),
            local_base_url=local_base_url,
            local_models=local_models,
            local_api_key=str(
                getattr(config, "bot_embedding_local_api_key", "") or ""
            ),
            local_enabled=local_enabled,
            local_timeout_seconds=float(
                _first_defined(config, "bot_embedding_local_timeout_seconds", 60.0)
            ),
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
        )
        files = [
            Path(path).expanduser()
            for path in (getattr(config, "bot_knowledge_files", []) or [])
        ]
        return _VectorKnowledgeRetriever(store=store, files=files)
    except Exception:  # noqa: BLE001 - 向量库构建失败时降级为不可用提供者。
        return _UnavailableVectorKnowledgeProvider()