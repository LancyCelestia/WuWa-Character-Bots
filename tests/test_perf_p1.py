"""P1/P2 性能落地回归：注册表单例、嵌入 memo、检索缓存、日志句柄、ensure-once、ANN 分批。

全部离线；网络探测类断言不在此文件（酷狗 HTTPS/NMC 证书结论见审计报告）。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.core.search.web_search import (
    ChainedWebSearchProvider,
    WebSearchHit,
)

# ---------------------------------------------------------------- P1-2 注册表单例


@pytest.fixture()
def _reset_default_registry():
    from plugins.bot_unified_runtime.sources import parsers

    parsers._DEFAULT_REGISTRY_BUNDLE = None
    yield
    parsers._DEFAULT_REGISTRY_BUNDLE = None


def test_default_parser_registry_memoized(_reset_default_registry):
    from plugins.bot_unified_runtime.sources.parsers import (
        build_content_parser_registry,
    )

    first = build_content_parser_registry()
    second = build_content_parser_registry()
    assert first is second, "全默认参数调用必须返回同一单例（群门禁每消息调用）"

    custom = build_content_parser_registry(enabled_platforms=["bilibili"])
    assert custom is not first
    assert "bilibili" in custom["parsers"]
    assert "youtube" not in custom["parsers"]


# ---------------------------------------------------------------- P1-3 嵌入 memo


@pytest.fixture()
def _reset_embed_memo():
    from plugins.bot_unified_runtime.domains.chat_reply.character import (
        vector_knowledge,
    )

    vector_knowledge.reset_query_embed_memo()
    yield
    vector_knowledge.reset_query_embed_memo()


def _fake_embed_response(dim: int = 4, count: int = 1):
    payload = {
        "data": [
            {"index": index, "embedding": [0.1] * dim} for index in range(count)
        ]
    }
    return SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: payload,
    )


def _provider():
    from plugins.bot_unified_runtime.character.vector_knowledge import (
        OpenAICompatibleEmbeddingProvider,
    )

    return OpenAICompatibleEmbeddingProvider(
        base_url="http://embed.test",
        model="m1",
        api_key="",
        timeout_seconds=1.0,
        dimensions=None,
        local_base_url="",
        local_models="",
        local_api_key="",
        local_enabled=False,
        local_timeout_seconds=1.0,
    )


def test_query_embed_memo_dedupes_single_text(monkeypatch, _reset_embed_memo):
    import plugins.bot_unified_runtime.domains.chat_reply.character.vector_knowledge as vk

    calls: list[list[str]] = []

    def fake_post(url, **kwargs):
        inputs = list(kwargs["json"]["input"])
        calls.append(inputs)
        return _fake_embed_response(count=len(inputs))

    monkeypatch.setattr(vk.httpx, "post", fake_post)
    provider = _provider()

    assert len(provider.embed_texts(["你好"])) == 1
    assert len(provider.embed_texts(["你好"])) == 1
    assert len(calls) == 1, "同 signature+文本的单文本查询必须命中 memo"

    assert len(provider.embed_texts(["世界"])) == 1
    assert len(calls) == 2

    assert len(provider.embed_texts(["a", "b"])) == 2
    assert calls[-1] == ["a", "b"], "批量嵌入不走 memo"


# ---------------------------------------------------------------- P1-4 检索缓存


class _CountingProvider:
    name = "counting"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def search(self, query: str, *, max_results: int = 3) -> list[WebSearchHit]:
        self.calls.append(f"{query}:{max_results}")
        return [WebSearchHit(title="t", snippet="s", url="https://example.com")]


def test_chained_search_cache():
    fake = _CountingProvider()
    chain = ChainedWebSearchProvider([fake])

    first = chain.search("洛天依 新歌", max_results=5)
    second = chain.search("洛天依 新歌", max_results=5)
    assert first == second
    assert fake.calls == ["洛天依 新歌:5"], "600s 内同查询不得重复外呼"

    chain.search("洛天依 新歌", max_results=3)
    assert fake.calls == ["洛天依 新歌:5", "洛天依 新歌:3"]

    assert chain.search("别的查询") != []
    assert fake.calls[-1] == "别的查询:3"


# ---------------------------------------------------------------- P1-5 事件日志句柄


def test_runtime_event_log_reuses_handle_and_rotates(tmp_path, monkeypatch):
    import pathlib

    from plugins.bot_unified_runtime.domains.ops.monitor.runtime_event_log import (
        RuntimeEventLog,
    )

    log_path = tmp_path / "events.log"
    log = RuntimeEventLog(log_path, max_bytes=64 * 1024, min_level="INFO")

    real_open = pathlib.Path.open
    open_calls: list[str] = []

    def counting_open(self, *args, **kwargs):
        if str(self) == str(log_path):
            open_calls.append(str(self))
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "open", counting_open)

    for index in range(5):
        log.info("test_event", index=index)
    assert len(open_calls) == 1, "连续 emit 不得每次重开文件句柄"

    # emit 对字段截断到 300 字符，单行 ~320B：写 1500 行 ≈ 480KB 必然触发轮转。
    for index in range(1500):
        log.info("bulk_event", seq=f"line-{index}-" + "y" * 260)
    assert log_path.with_suffix(log_path.suffix + ".old").exists(), "超限后应轮转"
    log.info("after_rotate")
    assert "after_rotate" in log_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------- P2-a/b ensure-once 与 ANN


def _audit_record(request_id: str):
    from plugins.bot_unified_runtime.contracts import AuditRecord, RiskLevel

    return AuditRecord(
        request_id=request_id,
        session_id="private:1",
        capability_id="bot.chat",
        stage="test",
        event="test_event",
        severity=RiskLevel.LOW,
        public_message="ok",
        private_debug="debug",
    )


def test_sqlite_audit_ensure_once(tmp_path, monkeypatch):
    from plugins.bot_unified_runtime.domains.ops.audit.logger import (
        SQLiteAuditRepository,
    )

    repository = SQLiteAuditRepository(tmp_path / "audit.sqlite3")
    ensure_calls: list[int] = []
    real_ensure = repository._ensure_schema

    def counting_ensure():
        ensure_calls.append(1)
        real_ensure()

    monkeypatch.setattr(repository, "_ensure_schema", counting_ensure)

    for index in range(3):
        repository.append(_audit_record(f"req-{index}"))
    repository.list_records()
    assert sum(ensure_calls) == 1, "DDL 只应在进程内执行一次"


def test_history_ensure_once(tmp_path, monkeypatch):
    from plugins.bot_unified_runtime.domains.chat_reply.character.history import (
        SQLiteConversationHistoryRepository,
    )

    repository = SQLiteConversationHistoryRepository(tmp_path / "history.sqlite3")
    ensure_calls: list[int] = []
    real_ensure = repository._ensure_schema

    def counting_ensure():
        ensure_calls.append(1)
        real_ensure()

    monkeypatch.setattr(repository, "_ensure_schema", counting_ensure)

    for index in range(3):
        repository.append_turn(
            request_id=f"req-{index}",
            platform="qq",
            adapter="onebot",
            bot_id="bot",
            session_id="private:1",
            sender_id="1",
            role="user",
            text=f"消息{index}",
        )
    assert sum(ensure_calls) == 1, "DDL 只应在进程内执行一次"


class _FakeEmbedder:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            digest = hashlib.sha1(text.encode("utf-8")).digest()
            vectors.append([byte / 255.0 for byte in digest[:8]])
        return vectors


def test_build_ann_index_batched(tmp_path, monkeypatch):
    """分批构建与全量构建结果等价：批量调小也应建满全部向量。"""
    from plugins.bot_unified_runtime.character.vector_knowledge import (
        SqliteVectorKnowledgeStore,
    )
    from plugins.bot_unified_runtime.domains.chat_reply.character import (
        vector_knowledge,
    )

    store = SqliteVectorKnowledgeStore(
        db_path=tmp_path / "kb.sqlite3",
        embed_provider=_FakeEmbedder(),
        chunk_chars=800,
        top_k=4,
        signature="test|fake",
        auto_reset=True,
    )
    docs = [
        {
            "id": f"topic/doc-{index}",
            "hash": hashlib.sha1(f"doc{index}".encode()).hexdigest(),
            "topic": "topic",
            "source": "moegirl",
            "title": f"doc-{index}",
            "chunks": [f"【doc-{index}】内容{index}"],
        }
        for index in range(24)
    ]
    store.sync_documents(iter(docs), removed_ids=[], full=True)
    store.embed_pending(None)

    monkeypatch.setattr(vector_knowledge, "_ANN_BUILD_BATCH_SIZE", 10)
    result = store.build_ann_index()
    assert result["built"] is True
    assert result["vectors"] == 24
    assert Path(store._ann_files()[0]).exists()
