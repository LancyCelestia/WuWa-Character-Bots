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
    _rrf_fuse,
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

    store.embed_pending([knowledge_file])
    assert store.retrieve("苹果香蕉", files=[knowledge_file], embed_backlog=False)
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

    store.embed_pending([knowledge_file])
    results = store.retrieve("苹果香蕉", files=[knowledge_file], embed_backlog=False)

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
        "bot_embedding_local_enabled": False,
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
    assert config.bot_embedding_local_enabled is True
    assert config.bot_embedding_local_base_url == "http://127.0.0.1:11434/v1"
    assert config.bot_embedding_local_models == "bge-m3"
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
            bot_embedding_local_enabled=False,
        )
    )

    assert result["ok"] is False
    assert result["error_kind"] == "config_missing"
    assert "BOT_EMBEDDING" in result["public_message"]


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
            bot_embedding_local_enabled=False,
        )
    )
    assert getattr(store_provider, "available", False) is True


def test_provider_falls_back_to_next_model_on_first_failure(monkeypatch):
    """qwen3.7 失败（配额/不可用）时自动尝试 text-embedding-v4。"""
    calls: list = []

    def fake_post(url, **kwargs):
        body = kwargs.get("json") or {}
        calls.append(body.get("model"))
        if body.get("model") == "qwen3.7-text-embedding":
            raise httpx.HTTPStatusError(
                "quota",
                request=httpx.Request("POST", url),
                response=httpx.Response(429, request=httpx.Request("POST", url)),
            )
        return _FakeResponse(
            {"data": [{"embedding": [0.3, 0.4], "index": 0}]}
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = OpenAICompatibleEmbeddingProvider(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen3.7-text-embedding,text-embedding-v4",
        api_key="sk-test",
        dimensions=1024,
    )

    vectors = provider.embed_texts(["守岸人"])

    assert vectors == [[0.3, 0.4]]
    assert calls == ["qwen3.7-text-embedding", "text-embedding-v4"]
    assert provider.model == "qwen3.7-text-embedding"


def test_provider_normalizes_model_list_with_spaces():
    provider = OpenAICompatibleEmbeddingProvider(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model=" qwen3.7-text-embedding , text-embedding-v4 ",
        api_key="sk-test",
    )
    assert provider.models == ["qwen3.7-text-embedding", "text-embedding-v4"]
    assert provider.model == "qwen3.7-text-embedding"


def test_provider_prefers_local_ollama_over_remote(monkeypatch):
    calls: list = []

    def fake_post(url, **kwargs):
        body = kwargs.get("json") or {}
        calls.append((url, body.get("model"), kwargs.get("headers") or {}))
        return _FakeResponse(
            {"data": [{"embedding": [1.0, 0.0], "index": 0}]}
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = OpenAICompatibleEmbeddingProvider(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen3.7-text-embedding",
        api_key="sk-remote",
        local_base_url="http://127.0.0.1:11434/v1",
        local_models="bge-m3",
    )

    vectors = provider.embed_texts(["守岸人"])

    assert vectors == [[1.0, 0.0]]
    assert len(calls) == 1
    assert calls[0][0] == "http://127.0.0.1:11434/v1/embeddings"
    assert calls[0][1] == "bge-m3"
    # 本地无 Key 时不得发送空 Authorization 头（httpx 会报非法头）。
    assert "Authorization" not in calls[0][2]
    assert provider.active_base_url == "http://127.0.0.1:11434/v1"
    assert provider.active_model == "bge-m3"


def test_provider_falls_back_to_remote_when_local_down(monkeypatch):
    calls: list = []

    def fake_post(url, **kwargs):
        body = kwargs.get("json") or {}
        calls.append((url, body.get("model")))
        if "11434" in url:
            raise httpx.ConnectError("ollama down")
        return _FakeResponse(
            {"data": [{"embedding": [0.5, 0.5], "index": 0}]}
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = OpenAICompatibleEmbeddingProvider(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen3.7-text-embedding",
        api_key="sk-remote",
        local_base_url="http://127.0.0.1:11434/v1",
        local_models="bge-m3",
    )

    vectors = provider.embed_texts(["守岸人"])

    assert vectors == [[0.5, 0.5]]
    assert len(calls) == 2
    assert calls[0][0].startswith("http://127.0.0.1:11434")
    assert calls[1][0].startswith("https://dashscope")
    assert provider.active_model == "qwen3.7-text-embedding"


def test_provider_sticks_to_working_local_chain(monkeypatch):
    calls: list = []

    def fake_post(url, **kwargs):
        calls.append(url)
        return _FakeResponse(
            {"data": [{"embedding": [1.0, 0.0], "index": 0}]}
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = OpenAICompatibleEmbeddingProvider(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen3.7-text-embedding",
        api_key="sk-remote",
        local_base_url="http://127.0.0.1:11434/v1",
        local_models="bge-m3",
    )
    provider.embed_texts(["第一段"])
    provider.embed_texts(["第二段"])

    assert len(calls) == 2
    assert all("11434" in url for url in calls)


def test_store_resets_vectors_when_signature_changes(tmp_path):
    paragraphs = ["第一段" * 20, "第二段" * 20]
    knowledge_file = tmp_path / "menu.md"
    knowledge_file.write_text("\n".join(paragraphs), encoding="utf-8")
    db_path = tmp_path / "knowledge.sqlite3"

    provider_a = _BatchRecordingProvider()
    store_a = SqliteVectorKnowledgeStore(
        db_path, provider_a, chunk_chars=120, top_k=2, signature="local|bge-m3"
    )
    done, pending = store_a.embed_pending([knowledge_file])
    assert done == pending == 2

    # 模拟切换成远程模型：签名不同 → 旧向量应被清空并按新 provider 重嵌。
    provider_b = _BatchRecordingProvider()
    store_b = SqliteVectorKnowledgeStore(
        db_path, provider_b, chunk_chars=120, top_k=2, signature="remote|qwen3.7"
    )
    done, pending = store_b.embed_pending([knowledge_file])
    assert done == pending == 2
    assert store_b.stats() == {"total": 2, "embedded": 2}
    assert provider_b.batch_sizes == [2]


def test_sync_prunes_sources_removed_from_files(tmp_path):
    """从 BOT_KNOWLEDGE_FILES 移除的文件，同步后不再保留其旧切片。"""
    a = tmp_path / "a.md"
    a.write_text("第一段" * 20, encoding="utf-8")
    b = tmp_path / "b.md"
    b.write_text("第二段" * 20, encoding="utf-8")
    db_path = tmp_path / "knowledge.sqlite3"

    provider = _BatchRecordingProvider()
    store = SqliteVectorKnowledgeStore(
        db_path, provider, chunk_chars=120, top_k=2, signature="local|bge-m3"
    )
    store.sync_chunks([a, b])
    assert len(store._pending_rows()) == 2

    store.sync_chunks([a])
    pending = store._pending_rows()
    assert len(pending) == 1
    with store._connect() as connection:
        sources = [row[0] for row in connection.execute("SELECT source_id FROM knowledge_chunks")]
    assert sources == ["a"]


def test_incomplete_build_does_not_reset_partial_vectors(tmp_path):
    """上次同步未完成（指纹为空）时，重开同配置不得清空已有向量。"""
    knowledge_file = tmp_path / "wiki.md"
    knowledge_file.write_text("第一段" * 20 + "\n\n" + "第二段" * 20, encoding="utf-8")
    db_path = tmp_path / "knowledge.sqlite3"

    provider_a = _BatchRecordingProvider()
    provider_a.fail_first = 1  # 第一轮嵌入失败 → 进度不完整、指纹不落库
    store_a = SqliteVectorKnowledgeStore(
        db_path, provider_a, chunk_chars=120, top_k=2, signature="local|bge-m3"
    )
    store_a.embed_pending([knowledge_file])

    provider_b = _BatchRecordingProvider()
    store_b = SqliteVectorKnowledgeStore(
        db_path, provider_b, chunk_chars=120, top_k=2, signature="local|bge-m3"
    )
    assert store_b._reset_vectors_if_needed() is False


def test_provider_falls_back_when_local_returns_404(monkeypatch):
    """Ollama 未拉取模型（404）时静默切到远程，不抛异常。"""
    calls: list = []

    def fake_post(url, **kwargs):
        calls.append(url)
        if "11434" in url:
            response = httpx.Response(
                404, request=httpx.Request("POST", url),
                json={'error': 'model "bge-m3" not found'},
            )
            raise httpx.HTTPStatusError(
                "not found",
                request=httpx.Request("POST", url),
                response=response,
            )
        return _FakeResponse(
            {"data": [{"embedding": [0.6, 0.4], "index": 0}]}
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = OpenAICompatibleEmbeddingProvider(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen3.7-text-embedding",
        api_key="sk-remote",
        local_base_url="http://127.0.0.1:11434/v1",
        local_models="bge-m3",
    )

    vectors = provider.embed_texts(["守岸人"])

    assert vectors == [[0.6, 0.4]]
    assert len(calls) == 2
    assert provider.active_base_url.startswith("https://dashscope")


def test_provider_falls_back_when_local_response_missing_data(monkeypatch):
    """本地返回 200 但结构异常时同样静默切到远程。"""
    calls: list = []

    def fake_post(url, **kwargs):
        calls.append(url)
        if "11434" in url:
            return _FakeResponse({"unexpected": True})
        return _FakeResponse(
            {"data": [{"embedding": [0.2, 0.8], "index": 0}]}
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = OpenAICompatibleEmbeddingProvider(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen3.7-text-embedding",
        api_key="sk-remote",
        local_base_url="http://127.0.0.1:11434/v1",
        local_models="bge-m3",
    )

    vectors = provider.embed_texts(["守岸人"])

    assert vectors == [[0.2, 0.8]]
    assert len(calls) == 2
    assert provider.active_model == "qwen3.7-text-embedding"


def test_store_retrieve_never_raises_when_every_chain_down(tmp_path):
    """所有端点都不可用时检索返回空列表而不是抛错，保证对话链路不崩。"""
    paragraphs = ["第一段" * 20, "第二段" * 20]
    knowledge_file = tmp_path / "menu.md"
    knowledge_file.write_text("\n".join(paragraphs), encoding="utf-8")
    store = SqliteVectorKnowledgeStore(
        tmp_path / "knowledge.sqlite3",
        FakeEmbeddingProvider(fail=True),
        chunk_chars=120,
        top_k=2,
        signature="local|bge-m3;remote|qwen3.7",
    )

    result = store.retrieve("查询", files=[knowledge_file])

    assert result == []
    assert store.stats()["embedded"] == 0


def test_retrieve_skips_backlog_embedding_when_embed_backlog_disabled(tmp_path):
    """请求路径不补齐大批量待嵌入行：直接回退，交由后台 knowledge-sync 补建。"""
    paragraphs = ["第一段" * 20, "第二段" * 20]
    knowledge_file = tmp_path / "menu.md"
    knowledge_file.write_text("\n".join(paragraphs), encoding="utf-8")
    provider = FakeEmbeddingProvider()
    store = SqliteVectorKnowledgeStore(
        tmp_path / "knowledge.sqlite3",
        provider,
        chunk_chars=120,
        top_k=2,
    )

    assert store.retrieve("查询", files=[knowledge_file], embed_backlog=False) == []
    assert len(provider.calls) == 1  # 查询本身仍会编码，只是不补齐积压
    assert store.stats()["embedded"] == 0


def test_retrieve_still_answers_when_no_backlog_with_embed_backlog_disabled(tmp_path):
    """待嵌入行为空时，禁用补建积压仍应正常编码查询并返回结果。"""
    paragraphs = ["苹果香蕉甜点" * 11, "香蕉樱桃果酱" * 11]
    knowledge_file = tmp_path / "menu.md"
    knowledge_file.write_text("\n".join(paragraphs), encoding="utf-8")
    vectors = {
        paragraphs[0]: [1.0, 1.0, 0.0, 0.0],
        paragraphs[1]: [0.0, 1.0, 1.0, 0.0],
        "苹果香蕉": [1.0, 1.0, 0.0, 0.0],
    }
    provider = FakeEmbeddingProvider(vectors)
    store = SqliteVectorKnowledgeStore(
        tmp_path / "knowledge.sqlite3",
        provider,
        chunk_chars=120,
        top_k=2,
    )
    store.embed_pending([knowledge_file])
    results = store.retrieve("苹果香蕉", files=[knowledge_file], embed_backlog=False)

    assert [chunk.content for chunk in results] == [paragraphs[0], paragraphs[1]]


def _fixed_provider(vectors):
    class _P:
        def embed_texts(self, texts):
            return [list(vectors[index]) for index in range(min(len(texts), len(vectors)))]
    return _P()


def test_ann_index_build_and_retrieve(tmp_path):
    faiss = __import__("pytest").importorskip("faiss")
    db = tmp_path / "k.sqlite3"
    knowledge_file = tmp_path / "kb.md"
    knowledge_file.write_text("甲段" * 30 + "\n\n" + "乙段" * 30, encoding="utf-8")
    # 两段内容分别给正交向量，便于确定检索顺序。
    provider = _fixed_provider([[1.0, 0.0], [0.0, 1.0]])
    store = SqliteVectorKnowledgeStore(
        db, provider, chunk_chars=120, top_k=2, signature="sigA",
        ann_index_path=str(tmp_path / "faiss.index"),
        ann_order_path=str(tmp_path / "order.json"),
    )
    store.embed_pending([knowledge_file])
    result = store.build_ann_index()
    assert result.get("built") is True
    assert (tmp_path / "faiss.index").exists()
    assert (tmp_path / "order.json").exists()

    # 查询向量接近第一段，应命中第一段 chunk。
    class QueryProvider:
        def embed_texts(self, texts):
            return [[0.99, 0.01] for _ in texts]

    store.embed_provider = QueryProvider()
    hits = store.retrieve("甲段甲段")
    assert hits and hits[0].content.startswith("甲段")


def test_ann_missing_falls_back_to_bruteforce(tmp_path):
    db = tmp_path / "k.sqlite3"
    knowledge_file = tmp_path / "kb.md"
    knowledge_file.write_text("甲段" * 30 + "\n\n" + "乙段" * 30, encoding="utf-8")
    provider = _fixed_provider([[1.0, 0.0], [0.0, 1.0]])
    store = SqliteVectorKnowledgeStore(db, provider, chunk_chars=120, top_k=2, signature="sigA")
    store.embed_pending([knowledge_file])
    hits = store.retrieve("甲段甲段", embed_backlog=False)
    assert len(hits) == 2
    assert hits[0].content.startswith("甲段")


def test_ann_signature_mismatch_falls_back(tmp_path):
    faiss = __import__("pytest").importorskip("faiss")
    db = tmp_path / "k.sqlite3"
    knowledge_file = tmp_path / "kb.md"
    knowledge_file.write_text("甲段" * 30 + "\n\n" + "乙段" * 30, encoding="utf-8")
    provider = _fixed_provider([[1.0, 0.0], [0.0, 1.0]])
    store_a = SqliteVectorKnowledgeStore(
        db, provider, chunk_chars=120, top_k=2, signature="sigA",
        ann_index_path=str(tmp_path / "faiss.index"),
        ann_order_path=str(tmp_path / "order.json"),
    )
    store_a.embed_pending([knowledge_file])
    store_a.build_ann_index()

    store_b = SqliteVectorKnowledgeStore(
        db, provider, chunk_chars=120, top_k=2, signature="sigB",
        ann_index_path=str(tmp_path / "faiss.index"),
        ann_order_path=str(tmp_path / "order.json"),
    )
    assert store_b.load_ann_index() is False
    hits = store_b.retrieve("甲段甲段", embed_backlog=False)
    assert hits and hits[0].content.startswith("甲段")


def test_sync_no_change_keeps_vector_cache(tmp_path):
    db = tmp_path / "k.sqlite3"
    knowledge_file = tmp_path / "kb.md"
    knowledge_file.write_text("甲段" * 30 + "\n\n" + "乙段" * 30, encoding="utf-8")
    provider = _fixed_provider([[1.0, 0.0], [0.0, 1.0]])
    store = SqliteVectorKnowledgeStore(db, provider, chunk_chars=120, top_k=2, signature="sigA")
    store.embed_pending([knowledge_file])
    matrix, ids = store._load_vector_cache()
    store.sync_chunks([])
    matrix2, ids2 = store._load_vector_cache()
    assert matrix2 is matrix and ids2 is ids
    assert isinstance(ids, list) and all(isinstance(item, str) for item in ids)


def test_fts_keyword_channel_recalls_when_vectors_are_all_zero(tmp_path):
    """正文关键词命中但向量全零时，BM25/FTS 通道仍应召回对应 chunk。"""
    content = "hello world rockets launch into space"
    knowledge_file = tmp_path / "kb.md"
    knowledge_file.write_text(content, encoding="utf-8")
    store = SqliteVectorKnowledgeStore(
        tmp_path / "knowledge.sqlite3",
        FakeEmbeddingProvider(),  # 正文与查询的向量都是零向量
        chunk_chars=120,
        top_k=2,
    )
    store.embed_pending([knowledge_file])

    results = store.retrieve(
        "hello rockets", files=[knowledge_file], embed_backlog=False
    )

    assert results
    assert any(
        "hello" in chunk.content and "rockets" in chunk.content
        for chunk in results
    )


def test_rrf_fusion_puts_documents_in_both_channels_first():
    """RRF 应提升同时命中两通道的文档；向量单通道第一会被挤到其后。"""
    fused = _rrf_fuse(["a", "b", "c"], ["b", "c", "d"], top_k=3)
    assert fused == ["b", "c", "a"]


def test_hybrid_fusion_boosts_keyword_match_over_vector_only(tmp_path):
    """端到端融合：纯向量第一的 chunk 应让位于关键词+向量双命中的 chunk。

    三个文件各成一段，避免 _chunk_text 把短段落合并成同一个 chunk。
    """
    alpha = "alpha only document"
    beta = "beta only document"
    gamma = "gamma only document"
    alpha_file = tmp_path / "alpha.md"
    beta_file = tmp_path / "beta.md"
    gamma_file = tmp_path / "gamma.md"
    alpha_file.write_text(alpha, encoding="utf-8")
    beta_file.write_text(beta, encoding="utf-8")
    gamma_file.write_text(gamma, encoding="utf-8")
    knowledge_files = [alpha_file, beta_file, gamma_file]

    provider = _fixed_provider([[1.0, 0.0], [0.9, 0.1], [0.5, 0.5]])
    store = SqliteVectorKnowledgeStore(
        tmp_path / "knowledge.sqlite3",
        provider,
        chunk_chars=120,
        top_k=3,
    )
    store.embed_pending(knowledge_files)

    results = store.retrieve(
        "beta gamma", files=knowledge_files, embed_backlog=False
    )

    assert len(results) == 3
    assert results[2].content == alpha
    assert {chunk.content for chunk in results[:2]} == {beta, gamma}


def test_fts_signature_invalidated_and_rebuilt_on_content_change(tmp_path):
    """内容变化会清空 FTS 签名，ensure_fts_index 重建后能检索到新内容。"""
    knowledge_file = tmp_path / "kb.md"
    knowledge_file.write_text("hello world document", encoding="utf-8")
    store = SqliteVectorKnowledgeStore(
        tmp_path / "knowledge.sqlite3",
        FakeEmbeddingProvider(),
        chunk_chars=120,
        top_k=2,
    )
    store.sync_chunks([knowledge_file])
    assert store.ensure_fts_index() is True
    old_signature = store._stored_fts_signature()
    assert old_signature

    knowledge_file.write_text("newterm document", encoding="utf-8")
    store.sync_chunks([knowledge_file])
    assert store._stored_fts_signature() == ""

    assert store.ensure_fts_index() is True
    new_signature = store._stored_fts_signature()
    assert new_signature
    assert new_signature != old_signature

    results = store.retrieve(
        "newterm", files=[knowledge_file], embed_backlog=False
    )
    assert results
    assert any("newterm" in chunk.content for chunk in results)


def test_unrelated_query_returns_empty_on_miss_threshold(tmp_path):
    """无关键词命中且向量最高余弦低于 0.30 时，应判未命中返回空列表。"""
    knowledge_file = tmp_path / "kb.md"
    knowledge_file.write_text("hello world document", encoding="utf-8")
    store = SqliteVectorKnowledgeStore(
        tmp_path / "knowledge.sqlite3",
        FakeEmbeddingProvider(),  # 查询与正文向量均为零 → 余弦 0.0
        chunk_chars=120,
        top_k=4,
    )
    store.embed_pending([knowledge_file])

    results = store.retrieve(
        "zzz qqq", files=[knowledge_file], embed_backlog=False
    )

    assert results == []


def test_fts_missing_falls_back_to_vector_only(tmp_path, monkeypatch):
    """FTS5 不可用时关键词通道安全降级，向量检索照常返回且不报错。"""
    knowledge_file = tmp_path / "kb.md"
    knowledge_file.write_text("甲段" * 30 + "\n\n" + "乙段" * 30, encoding="utf-8")
    provider = _fixed_provider([[1.0, 0.0], [0.0, 1.0]])
    store = SqliteVectorKnowledgeStore(
        tmp_path / "knowledge.sqlite3", provider, chunk_chars=120, top_k=2
    )
    store.embed_pending([knowledge_file])

    def raise_no_fts():
        raise sqlite3.OperationalError("no such module: fts5")

    monkeypatch.setattr(store, "_ensure_fts_table", raise_no_fts)

    hits = store.retrieve("甲段甲段", embed_backlog=False)

    assert len(hits) == 2
    assert hits[0].content.startswith("甲段")


def test_build_ann_index_also_builds_fts(tmp_path):
    """knowledge-sync 构建 ANN 后应一并幂等建好 FTS 关键词索引。"""
    faiss = __import__("pytest").importorskip("faiss")
    knowledge_file = tmp_path / "kb.md"
    knowledge_file.write_text("甲段" * 30 + "\n\n" + "乙段" * 30, encoding="utf-8")
    provider = _fixed_provider([[1.0, 0.0], [0.0, 1.0]])
    store = SqliteVectorKnowledgeStore(
        tmp_path / "knowledge.sqlite3",
        provider,
        chunk_chars=120,
        top_k=2,
        signature="sigA",
        ann_index_path=str(tmp_path / "faiss.index"),
        ann_order_path=str(tmp_path / "order.json"),
    )
    store.embed_pending([knowledge_file])

    result = store.build_ann_index()

    assert result.get("built") is True
    assert store.ensure_fts_index() is True
    assert store._stored_fts_signature()

def test_chinese_phrase_match_recalls_entity_names(tmp_path):
    """整段中文专名（>=3 字）应能经 trigram MATCH 召回，即使向量全零。"""
    knowledge_file = tmp_path / "kb.md"
    knowledge_file.write_text("守岸人是黑海岸的守护者", encoding="utf-8")
    store = SqliteVectorKnowledgeStore(
        tmp_path / "knowledge.sqlite3",
        FakeEmbeddingProvider(),  # 向量全零，只能靠关键词通道
        chunk_chars=120,
        top_k=2,
    )
    store.embed_pending([knowledge_file])
    results = store.retrieve("守岸人是谁", files=[knowledge_file], embed_backlog=False)
    assert results
    assert any("守岸人" in chunk.content for chunk in results)


def test_short_term_content_like_recalls_two_char_names(tmp_path):
    """两字专名应经正文 LIKE 兜底召回，且停用字噪声二元组不干扰。"""
    knowledge_file = tmp_path / "kb.md"
    knowledge_file.write_text("今州是鸣潮中的一座城市", encoding="utf-8")
    store = SqliteVectorKnowledgeStore(
        tmp_path / "knowledge.sqlite3",
        FakeEmbeddingProvider(),  # 向量全零，只能靠关键词通道
        chunk_chars=120,
        top_k=2,
    )
    store.embed_pending([knowledge_file])
    results = store.retrieve("今州在哪", files=[knowledge_file], embed_backlog=False)
    assert results
    assert any("今州" in chunk.content for chunk in results)
