from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import httpx
import pytest

from plugins.bot_unified_runtime.character.providers import (
    FileCharacterContextProvider,
    build_character_context_provider,
)
from plugins.bot_unified_runtime.character.vector_knowledge import (
    OpenAICompatibleEmbeddingProvider,
    SqliteVectorKnowledgeStore,
    build_vector_knowledge_provider,
)
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import KnowledgeChunk


class FakeEmbeddingProvider:
    def __init__(self, vectors=None, *, fail=False):
        self.vectors = dict(vectors or {})
        self.fail = fail
        self.calls: list[str] = []

    def embed_texts(self, texts):
        self.calls.extend(texts)
        if self.fail:
            return []
        return [self.vectors.get(text, [0.0, 0.0, 0.0, 0.0]) for text in texts]


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://api.example.com/v1/embeddings")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("request failed", request=request, response=response)

    def json(self):
        return self._payload


def _read_rows(db_path):
    connection = sqlite3.connect(str(db_path))
    try:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT chunk_id, source_id, title, content, content_hash, vector_json "
            "FROM knowledge_chunks ORDER BY rowid"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def _make_persona_file(tmp_path):
    path = tmp_path / "persona.md"
    path.write_text("守岸人来自黑海岸。\n说话温柔克制。", encoding="utf-8")
    return path


def test_sync_chunks_is_idempotent_for_unchanged_content(tmp_path):
    paragraphs = ["苹果香蕉甜点" * 11, "香蕉樱桃果酱" * 11, "数字密码学" * 14]
    knowledge_file = tmp_path / "menu.md"
    knowledge_file.write_text("\n".join(paragraphs), encoding="utf-8")
    store = SqliteVectorKnowledgeStore(
        tmp_path / "knowledge.sqlite3",
        FakeEmbeddingProvider(),
        chunk_chars=120,
        top_k=2,
    )

    store.sync_chunks([knowledge_file])
    first = _read_rows(store.db_path)

    store.sync_chunks([knowledge_file])
    second = _read_rows(store.db_path)

    assert len(first) == 3
    assert second == first
    for index, (content, row) in enumerate(zip(paragraphs, first), start=1):
        assert row["chunk_id"] == hashlib.sha1(
            f"{knowledge_file.as_posix()}:{index}:{content}".encode("utf-8")
        ).hexdigest()
        assert row["content_hash"] == hashlib.sha1(content.encode("utf-8")).hexdigest()
        assert row["source_id"] == knowledge_file.stem
        assert row["title"] == knowledge_file.stem
        assert row["vector_json"] is None


def test_sync_chunks_updates_changed_content_and_clears_vector(tmp_path):
    paragraphs = ["苹果香蕉甜点" * 11, "香蕉樱桃果酱" * 11]
    knowledge_file = tmp_path / "menu.md"
    knowledge_file.write_text("\n".join(paragraphs), encoding="utf-8")
    vectors = {
        paragraphs[0]: [1.0, 1.0, 0.0, 0.0],
        paragraphs[1]: [0.0, 1.0, 1.0, 0.0],
        "苹果香蕉": [1.0, 1.0, 0.0, 0.0],
    }
    store = SqliteVectorKnowledgeStore(
        tmp_path / "knowledge.sqlite3",
        FakeEmbeddingProvider(vectors),
        chunk_chars=120,
        top_k=2,
    )

    store.sync_chunks([knowledge_file])
    assert store.retrieve("苹果香蕉", files=[knowledge_file])
    assert all(row["vector_json"] for row in _read_rows(store.db_path))

    paragraphs[0] = "苹果香蕉点心" * 11
    knowledge_file.write_text("\n".join(paragraphs), encoding="utf-8")
    store.sync_chunks([knowledge_file])

    rows = _read_rows(store.db_path)
    updated = next(row for row in rows if row["content"] == paragraphs[0])
    assert updated["content_hash"] == hashlib.sha1(paragraphs[0].encode("utf-8")).hexdigest()
    assert updated["vector_json"] in (None, "")


def test_retrieve_returns_top_k_ordered_by_cosine_similarity(tmp_path):
    paragraphs = ["苹果香蕉甜点" * 11, "香蕉樱桃果酱" * 11, "数字密码学" * 14]
    knowledge_file = tmp_path / "menu.md"
    knowledge_file.write_text("\n".join(paragraphs), encoding="utf-8")
    vectors = {
        paragraphs[0]: [1.0, 1.0, 0.0, 0.0],
        paragraphs[1]: [0.0, 1.0, 1.0, 0.0],
        paragraphs[2]: [0.0, 0.0, 0.0, 1.0],
        "苹果香蕉": [1.0, 1.0, 0.0, 0.0],
    }
    provider = FakeEmbeddingProvider(vectors)
    store = SqliteVectorKnowledgeStore(
        tmp_path / "knowledge.sqlite3",
        provider,
        chunk_chars=120,
        top_k=2,
    )

    results = store.retrieve("苹果香蕉", files=[knowledge_file])

    assert [chunk.content for chunk in results] == [paragraphs[0], paragraphs[1]]
    assert all(isinstance(chunk, KnowledgeChunk) for chunk in results)
    assert results[0].source_id == knowledge_file.stem
    assert results[0].title == knowledge_file.stem
    assert "苹果香蕉" in provider.calls


def test_retrieve_returns_empty_when_embed_provider_fails(tmp_path):
    knowledge_file = tmp_path / "menu.md"
    knowledge_file.write_text("苹果香蕉甜点" * 20, encoding="utf-8")
    store = SqliteVectorKnowledgeStore(
        tmp_path / "knowledge.sqlite3",
        FakeEmbeddingProvider(fail=True),
        chunk_chars=120,
        top_k=4,
    )

    assert store.retrieve("苹果香蕉", files=[knowledge_file]) == []


def test_build_vector_knowledge_provider_unavailable_by_default():
    provider = build_vector_knowledge_provider(Config())

    assert provider.available is False
    assert provider.retrieve("任意查询") == []


def test_build_vector_knowledge_provider_requires_model_and_base_url(tmp_path):
    base = {
        "bot_embedding_enabled": True,
        "bot_knowledge_db_path": str(tmp_path / "knowledge.sqlite3"),
    }
    missing_model = Config(**base, bot_embedding_base_url="https://api.example.com/v1")
    missing_base_url = Config(**base, bot_embedding_model="embed-model")

    assert build_vector_knowledge_provider(missing_model).available is False
    assert build_vector_knowledge_provider(missing_base_url).available is False


def test_build_vector_knowledge_provider_available_when_configured(tmp_path):
    config = Config(
        bot_embedding_enabled=True,
        bot_embedding_model="embed-model",
        bot_embedding_base_url="https://api.example.com/v1",
        bot_knowledge_db_path=str(tmp_path / "knowledge.sqlite3"),
        bot_knowledge_top_k=2,
    )
    provider = build_vector_knowledge_provider(config)

    assert provider.available is True
    assert provider.retrieve("查询") == []


def test_config_exposes_vector_knowledge_defaults():
    config = Config()

    assert config.bot_embedding_enabled is False
    assert config.bot_embedding_model == ""
    assert config.bot_embedding_base_url == ""
    assert config.bot_embedding_api_key == ""
    assert config.bot_embedding_timeout_seconds == 15.0
    assert config.bot_knowledge_top_k == 4
    assert config.bot_knowledge_db_path == "data/knowledge_embeddings.sqlite3"


def test_file_character_provider_uses_vector_retriever_results(tmp_path):
    knowledge_file = tmp_path / "knowledge.md"
    knowledge_file.write_text("顺序第一段内容。", encoding="utf-8")
    vector_chunk = KnowledgeChunk(
        chunk_id="vec:1",
        source_id="vector",
        title="向量知识",
        content="检索到的向量知识",
    )
    seen_queries = []

    def retriever(query_text):
        seen_queries.append(query_text)
        return [vector_chunk]

    provider = FileCharacterContextProvider(
        persona_profile_id="test",
        persona_display_name="测试",
        persona_version="0",
        persona_files=[_make_persona_file(tmp_path)],
        knowledge_files=[knowledge_file],
        vector_retriever=retriever,
    )

    bundle = provider.build_context(
        request_id="req_vector",
        sender_id="42",
        session_id="private:42",
        query_text="向量检索查询",
    )

    assert bundle.knowledge_results.chunks == [vector_chunk]
    assert bundle.knowledge_results.answerable is True
    assert bundle.knowledge_results.confidence == 0.8
    assert seen_queries == ["向量检索查询"]


def test_file_character_provider_falls_back_to_sequential_chunks_when_retriever_empty(tmp_path):
    knowledge_file = tmp_path / "knowledge.md"
    knowledge_file.write_text("顺序回退知识。", encoding="utf-8")
    provider = FileCharacterContextProvider(
        persona_profile_id="test",
        persona_display_name="测试",
        persona_version="0",
        persona_files=[_make_persona_file(tmp_path)],
        knowledge_files=[knowledge_file],
        knowledge_max_chunks=1,
        knowledge_chunk_chars=120,
        vector_retriever=lambda query_text: [],
    )

    bundle = provider.build_context(
        request_id="req_fallback",
        sender_id="42",
        session_id="private:42",
        query_text="查询",
    )

    assert [chunk.content for chunk in bundle.knowledge_results.chunks] == ["顺序回退知识。"]
    assert bundle.knowledge_results.answerable is True
    assert bundle.knowledge_results.confidence == 0.8


def test_file_character_provider_falls_back_when_retriever_raises(tmp_path):
    knowledge_file = tmp_path / "knowledge.md"
    knowledge_file.write_text("顺序回退知识。", encoding="utf-8")

    def retriever(query_text):
        raise RuntimeError("embedding backend down")

    provider = FileCharacterContextProvider(
        persona_profile_id="test",
        persona_display_name="测试",
        persona_version="0",
        persona_files=[_make_persona_file(tmp_path)],
        knowledge_files=[knowledge_file],
        vector_retriever=retriever,
    )

    bundle = provider.build_context(
        request_id="req_raise",
        sender_id="42",
        session_id="private:42",
        query_text="查询",
    )

    assert [chunk.content for chunk in bundle.knowledge_results.chunks] == ["顺序回退知识。"]


def test_build_character_context_provider_injects_retriever_only_when_available(tmp_path):
    disabled = build_character_context_provider(Config())
    assert disabled.vector_retriever is None

    enabled_config = Config(
        bot_embedding_enabled=True,
        bot_embedding_model="embed-model",
        bot_embedding_base_url="https://api.example.com/v1",
        bot_knowledge_db_path=str(tmp_path / "knowledge.sqlite3"),
    )
    enabled = build_character_context_provider(enabled_config)
    assert callable(enabled.vector_retriever)


def test_openai_compatible_embedding_provider_parses_response(monkeypatch):
    calls = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        calls["url"] = url
        calls["headers"] = headers
        calls["json"] = json
        calls["timeout"] = timeout
        return _FakeResponse(
            {
                "data": [
                    {"index": 1, "embedding": [0.3, 0.4]},
                    {"index": 0, "embedding": [0.1, 0.2]},
                ]
            }
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = OpenAICompatibleEmbeddingProvider(
        "https://api.example.com/v1/",
        "embed-model",
        "sk-test",
        timeout_seconds=5.0,
    )

    assert provider.embed_texts(["第一段", "第二段"]) == [[0.1, 0.2], [0.3, 0.4]]
    assert calls["url"] == "https://api.example.com/v1/embeddings"
    assert calls["headers"] == {"Authorization": "Bearer sk-test"}
    assert calls["json"] == {"model": "embed-model", "input": ["第一段", "第二段"]}
    assert calls["timeout"] == 5.0


@pytest.mark.parametrize(
    "post_error",
    [
        httpx.ConnectError("connection refused"),
        _FakeResponse({"error": "missing data"}),
    ],
)
def test_openai_compatible_embedding_provider_returns_empty_on_failure(monkeypatch, post_error):
    def fake_post(url, headers=None, json=None, timeout=None):
        if isinstance(post_error, Exception):
            raise post_error
        return post_error

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = OpenAICompatibleEmbeddingProvider(
        "https://api.example.com/v1",
        "embed-model",
        "sk-test",
    )

    assert provider.embed_texts(["文本"]) == []

def test_keyword_retriever_searches_across_files(tmp_path):
    from plugins.bot_unified_runtime.character.vector_knowledge import (
        KeywordKnowledgeRetriever,
    )

    first = tmp_path / "first.md"
    first.write_text("守岸人喜欢弹钢琴，用琴声传递情感。", encoding="utf-8")
    second = tmp_path / "second.md"
    second.write_text("黑海岸的雪烩浓汤使用海鲜、时蔬和牛奶炖煮。", encoding="utf-8")

    retriever = KeywordKnowledgeRetriever([first, second], top_k=2, chunk_chars=120)
    result = retriever.retrieve("守岸人弹钢琴")

    assert result
    assert any("钢琴" in chunk.content for chunk in result)
    assert all(len(chunk.content) > 0 for chunk in result)


def test_keyword_retriever_returns_empty_for_unknown_query(tmp_path):
    from plugins.bot_unified_runtime.character.vector_knowledge import (
        KeywordKnowledgeRetriever,
    )

    file = tmp_path / "first.md"
    file.write_text("完全无关的一段设定文本。", encoding="utf-8")

    retriever = KeywordKnowledgeRetriever([file], top_k=4, chunk_chars=120)
    assert retriever.retrieve("量子物理 对撞机") == []


class _BatchRecordingProvider:
    """记录每次 embed_texts 传入的条数，返回固定维度向量。"""

    def __init__(self):
        self.batch_sizes: list[int] = []
        self.fail_first = 0

    def embed_texts(self, texts):
        if self.fail_first > 0:
            self.fail_first -= 1
            return []
        self.batch_sizes.append(len(texts))
        return [[float(index), 1.0] for index in range(len(texts))]


def test_provider_sends_dimensions_when_configured(monkeypatch):
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return _FakeResponse(
            {"data": [{"embedding": [0.1, 0.2], "index": 0}]}
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = OpenAICompatibleEmbeddingProvider(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen3.7-text-embedding",
        api_key="sk-test",
        dimensions=1024,
    )
    vectors = provider.embed_texts(["守岸人是谁"])

    assert vectors == [[0.1, 0.2]]
    assert captured["url"].endswith("/embeddings")
    assert captured["json"]["model"] == "qwen3.7-text-embedding"
    assert captured["json"]["dimensions"] == 1024
    assert captured["json"]["input"] == ["守岸人是谁"]


def test_provider_omits_dimensions_when_unset(monkeypatch):
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["json"] = kwargs.get("json")
        return _FakeResponse(
            {"data": [{"embedding": [0.1, 0.2], "index": 0}]}
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = OpenAICompatibleEmbeddingProvider(
        base_url="https://api.siliconflow.cn/v1",
        model="Pro/BAAI/bge-m3",
        api_key="sk-test",
    )
    provider.embed_texts(["文本"])

    assert "dimensions" not in captured["json"]


def test_store_embed_pending_keeps_batch_at_or_below_ten(tmp_path):
    paragraphs = [f"第 {i} 段" * 20 for i in range(25)]
    knowledge_file = tmp_path / "big.md"
    knowledge_file.write_text("\n".join(paragraphs), encoding="utf-8")
    provider = _BatchRecordingProvider()
    store = SqliteVectorKnowledgeStore(
        tmp_path / "knowledge.sqlite3",
        provider,
        chunk_chars=120,
        top_k=2,
    )

    done, pending = store.embed_pending([knowledge_file])

    assert done == 25
    assert pending == 25
    assert provider.batch_sizes
    assert max(provider.batch_sizes) <= 10
    assert store.stats() == {"total": 25, "embedded": 25}


def test_store_embed_pending_is_resumable_after_failure(tmp_path):
    knowledge_file = tmp_path / "resume.md"
    knowledge_file.write_text("第一段" * 20 + "\n" + "第二段" * 20, encoding="utf-8")
    provider = _BatchRecordingProvider()
    store = SqliteVectorKnowledgeStore(
        tmp_path / "knowledge.sqlite3",
        provider,
        chunk_chars=120,
        top_k=2,
    )

    provider.fail_first = 1
    done, pending = store.embed_pending([knowledge_file])
    assert done == 0
    assert pending == 2
    assert store.stats() == {"total": 2, "embedded": 0}

    done, pending = store.embed_pending([knowledge_file])
    assert done == 2
    assert store.stats() == {"total": 2, "embedded": 2}


def test_store_stats_counts_total_and_embedded(tmp_path):
    store = SqliteVectorKnowledgeStore(
        tmp_path / "knowledge.sqlite3",
        _BatchRecordingProvider(),
        chunk_chars=120,
        top_k=2,
    )
    assert store.stats() == {"total": 0, "embedded": 0}


def test_embedding_smoke_disabled_returns_guidance():
    from plugins.bot_unified_runtime.smoke import run_embedding_smoke

    result = run_embedding_smoke(Config(bot_embedding_enabled=False))

    assert result["ok"] is False
    assert result["error_kind"] == "disabled"
    assert "BOT_EMBEDDING_ENABLED" in result["public_message"]


def test_embedding_smoke_reports_missing_key():
    from plugins.bot_unified_runtime.smoke import run_embedding_smoke

    result = run_embedding_smoke(
        Config(
            bot_embedding_enabled=True,
            bot_embedding_model="qwen3.7-text-embedding",
            bot_embedding_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            bot_embedding_api_key="",
        )
    )

    assert result["ok"] is False
    assert result["error_kind"] == "config_missing"
    assert "BOT_EMBEDDING_API_KEY" in result["public_message"]


def test_embedding_smoke_success_path(monkeypatch):
    from plugins.bot_unified_runtime import smoke

    class _FakeProvider:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def embed_texts(self, texts):
            assert len(texts) == 2
            return [[0.1, 0.2] for _ in texts]

    monkeypatch.setattr(smoke, "OpenAICompatibleEmbeddingProvider", _FakeProvider)
    result = smoke.run_embedding_smoke(
        Config(
            bot_embedding_enabled=True,
            bot_embedding_model="qwen3.7-text-embedding",
            bot_embedding_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            bot_embedding_api_key="sk-test",
            bot_embedding_dimensions=1024,
        )
    )

    assert result["ok"] is True
    assert result["dimension_count"] == 2
    assert result["error_kind"] == "none"


def test_build_provider_passes_dimensions_config(tmp_path):
    store_provider = build_vector_knowledge_provider(
        Config(
            bot_embedding_enabled=True,
            bot_embedding_model="qwen3.7-text-embedding",
            bot_embedding_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            bot_embedding_api_key="sk-test",
            bot_embedding_dimensions=768,
        )
    )
    assert getattr(store_provider, "available", False) is True
