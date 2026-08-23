from __future__ import annotations

import hashlib
import re
import json
import struct

try:
    import numpy as np
except Exception:  # noqa: BLE001 - numpy 可选，缺失回退纯 Python 余弦。
    np = None
import sqlite3
import threading
from dataclasses import dataclass
from math import sqrt
from pathlib import Path
from typing import Protocol

import httpx

from plugins.bot_unified_runtime.contracts import KnowledgeChunk

from .documents import load_character_document

_EMBED_BATCH_SIZE = 10  # 百炼 qwen3.7 上限 20 条、v4 上限 10 条，取 10 两者都兼容。
_MIN_CHUNK_CHARS = 120


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
                except Exception:
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


class SqliteVectorKnowledgeStore:
    def __init__(
        self,
        db_path: str | Path,
        embed_provider: EmbeddingProvider,
        chunk_chars: int = 900,
        top_k: int = 4,
        signature: str = "",
        auto_reset: bool = True,
    ) -> None:
        self.db_path = str(db_path)
        self.embed_provider = embed_provider
        self.chunk_chars = max(_MIN_CHUNK_CHARS, int(chunk_chars))
        self.top_k = max(0, int(top_k))
        self.signature = str(signature or "").strip()
        # 运行时应为 False：只有显式 knowledge-sync 才允许因指纹变化清空向量，
        # 避免机器人进程与同步进程并发时互相清空、进度反复回退。
        self.auto_reset = bool(auto_reset)
        self._lock = threading.RLock()
        self._vector_cache: Any | None = None
        self._vector_meta: list[dict] | None = None
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
                except Exception:  # noqa: BLE001
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
            self._invalidate_vector_cache()
            paths = [Path(path).expanduser() for path in files]
            with self._connect() as connection:
                # 已从 BOT_KNOWLEDGE_FILES 移除的旧文件不再保留在知识库里。
                source_ids = [path.stem for path in paths]
                if source_ids:
                    placeholders = ",".join("?" for _ in source_ids)
                    connection.execute(
                        f"DELETE FROM knowledge_chunks WHERE source_id NOT IN ({placeholders})",
                        source_ids,
                    )
                for path in paths:
                    text = load_character_document(path)
                    source_id = path.stem
                    for index, content in enumerate(
                        _chunk_text(text, chunk_chars=self.chunk_chars),
                        start=1,
                    ):
                        chunk_id = hashlib.sha1(
                            f"{path.as_posix()}:{index}:{content}".encode("utf-8")
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
        embed_backlog: bool = True,
    ) -> list[KnowledgeChunk]:
        with self._lock:
            self.sync_chunks(list(files) if files else [])
            if self.top_k <= 0:
                return []
            if not embed_backlog and self._pending_rows():
                # 请求路径不得承担大批量离线补建：待嵌入行交给后台
                # knowledge-sync 处理，否则每条消息都会同步补齐整个积压队列。
                return []
            done, pending = self._embed_all_pending()
            if done < pending:
                return []
            query_vectors = self._embed([str(query_text)])
            if query_vectors is None or len(query_vectors) != 1:
                return []
            query_vector = query_vectors[0]
            if np is not None:
                matrix, metas = self._load_vector_cache()
                if matrix is None or not metas:
                    return []
                query_array = np.asarray(query_vector, dtype=np.float32)
                norms = np.linalg.norm(matrix, axis=1)
                matrix_norm = matrix / np.maximum(norms, 1e-9)[:, None]
                scores = matrix_norm @ query_array
                top_indices = np.argsort(-scores)[: self.top_k]
                results: list[KnowledgeChunk] = []
                for index in top_indices:
                    meta = metas[int(index)]
                    results.append(
                        KnowledgeChunk(
                            chunk_id=meta["chunk_id"],
                            source_id=meta["source_id"],
                            title=meta["title"],
                            content=meta["content"],
                        )
                    )
                return results

            scored: list[tuple[float, KnowledgeChunk]] = []
            for row in self._vector_rows():
                try:
                    vector = json.loads(str(row["vector_json"]))
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                score = _cosine_similarity(query_vector, vector)
                scored.append(
                    (
                        score,
                        KnowledgeChunk(
                            chunk_id=str(row["chunk_id"]),
                            source_id=str(row["source_id"] or ""),
                            title=str(row["title"] or ""),
                            content=str(row["content"] or ""),
                        ),
                    )
                )
            scored.sort(key=lambda pair: (-pair[0], pair[1].chunk_id))
            return [chunk for _, chunk in scored[: self.top_k]]

    def _load_vector_cache(self):
        """把全部向量一次性载入 numpy 矩阵并缓存；blob 优先，否则解析 JSON。"""
        if self._vector_cache is not None and self._vector_meta is not None:
            return self._vector_cache, self._vector_meta
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT chunk_id, source_id, title, content, vector_json, vector_blob
                FROM knowledge_chunks
                WHERE vector_json IS NOT NULL AND vector_json != ''
                """
            ).fetchall()
        vectors: list = []
        metas: list[dict] = []
        for row in rows:
            raw_blob = row["vector_blob"]
            if isinstance(raw_blob, (bytes, bytearray, memoryview)):
                try:
                    vector = np.frombuffer(bytes(raw_blob), dtype=np.float32)
                    if vector.size > 0:
                        vectors.append(vector.astype(np.float32))
                        metas.append(
                            {
                                "chunk_id": str(row["chunk_id"]),
                                "source_id": str(row["source_id"] or ""),
                                "title": str(row["title"] or ""),
                                "content": str(row["content"] or ""),
                            }
                        )
                        continue
                except Exception:  # noqa: BLE001
                    pass
            try:
                vector = json.loads(str(row["vector_json"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if vector:
                vectors.append(np.asarray(vector, dtype=np.float32))
                metas.append(
                    {
                        "chunk_id": str(row["chunk_id"]),
                        "source_id": str(row["source_id"] or ""),
                        "title": str(row["title"] or ""),
                        "content": str(row["content"] or ""),
                    }
                )
        if not vectors:
            self._vector_cache = None
            self._vector_meta = None
            return None, None
        self._vector_cache = np.vstack(vectors).astype(np.float32)
        self._vector_meta = metas
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
        except Exception:
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
                            struct.pack("<%df" % len(vector), *vector),
                            str(row["chunk_id"]),
                        ),
                    )
            self._invalidate_vector_cache()
            return True
        except (TypeError, ValueError, sqlite3.Error):
            return False




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
                f"{path.as_posix()}:{index}:{content}".encode("utf-8")
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
        except Exception:
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
    except Exception:
        return _UnavailableVectorKnowledgeProvider()