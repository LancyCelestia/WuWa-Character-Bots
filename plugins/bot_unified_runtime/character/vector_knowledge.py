from __future__ import annotations

import hashlib
import re
import json
import sqlite3
import threading
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


class OpenAICompatibleEmbeddingProvider:
    def __init__(
        self,
        base_url: str,
        model: str | list[str],
        api_key: str,
        timeout_seconds: float = 15.0,
        dimensions: int | None = None,
    ) -> None:
        self.base_url = str(base_url).rstrip("/")
        if isinstance(model, str):
            models = [part.strip() for part in model.split(",") if part.strip()]
        else:
            models = [str(part).strip() for part in model if str(part).strip()]
        self.models = models or [str(model).strip() or ""]
        self.model = self.models[0]
        self.api_key = api_key
        self.timeout_seconds = float(timeout_seconds)
        self.dimensions = int(dimensions) if dimensions else None

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """批量编码；配置多个模型时按顺序回退（如 qwen3.7 配额耗尽后换 v4）。"""
        if not texts:
            return []
        for model in self.models:
            try:
                body: dict = {"model": model, "input": texts}
                if self.dimensions:
                    body["dimensions"] = self.dimensions
                response = httpx.post(
                    f"{self.base_url}/embeddings",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=body,
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
                payload = response.json()
                data = payload["data"]
                if all("index" in item for item in data):
                    data = sorted(data, key=lambda item: int(item["index"]))
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
    ) -> None:
        self.db_path = str(db_path)
        self.embed_provider = embed_provider
        self.chunk_chars = max(_MIN_CHUNK_CHARS, int(chunk_chars))
        self.top_k = max(0, int(top_k))
        self._lock = threading.RLock()
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
                    vector_json TEXT
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def sync_chunks(self, files: list[Path]) -> None:
        with self._lock:
            paths = [Path(path).expanduser() for path in files]
            with self._connect() as connection:
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

    def embed_pending(self, files: list[Path] | None = None) -> tuple[int, int]:
        """预建库：同步文件切片后把未向量化的行全部嵌入。

        返回 (本次成功嵌入行数, 处理前待嵌入行数)；中途失败即停止。
        """
        with self._lock:
            if files:
                self.sync_chunks(list(files))
            pending = self._pending_rows()
            done = 0
            for batch in _batches(pending, _EMBED_BATCH_SIZE):
                vectors = self._embed([str(row["content"]) for row in batch])
                if vectors is None:
                    break
                if not self._save_vectors(batch, vectors):
                    break
                done += len(batch)
            return done, len(pending)

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
    ) -> list[KnowledgeChunk]:
        with self._lock:
            self.sync_chunks(list(files) if files else [])
            if self.top_k <= 0:
                return []
            pending = self._pending_rows()
            for batch in _batches(pending, _EMBED_BATCH_SIZE):
                vectors = self._embed([str(row["content"]) for row in batch])
                if vectors is None:
                    return []
                if not self._save_vectors(batch, vectors):
                    return []
            query_vectors = self._embed([str(query_text)])
            if query_vectors is None or len(query_vectors) != 1:
                return []
            query_vector = query_vectors[0]
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
                        "UPDATE knowledge_chunks SET vector_json = ? WHERE chunk_id = ?",
                        (json.dumps(vector), str(row["chunk_id"])),
                    )
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
            return self._store.retrieve(query_text, files=self._files)
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
    if not enabled or not model or not base_url:
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
        )
        files = [
            Path(path).expanduser()
            for path in (getattr(config, "bot_knowledge_files", []) or [])
        ]
        return _VectorKnowledgeRetriever(store=store, files=files)
    except Exception:
        return _UnavailableVectorKnowledgeProvider()