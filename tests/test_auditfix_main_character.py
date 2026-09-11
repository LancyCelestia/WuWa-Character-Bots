"""审计修复 C 组回归（离线，不依赖 nonebot 运行时）。

覆盖：
- C17a 向量检索查询向量归一化（模长≠1 时 0.30 低置信阈值判定正确）。
- C20 安全规则匹配入口 Unicode 归一化（全角/零宽变体可命中、普通文本不误伤）。
- C23 天气缓存过期返回旧值 + 后台刷新，无旧值才同步拉取。
- C22 LLM 群摘要缓存 LRU 上限（附带）。
"""

from __future__ import annotations

import json
import threading
import time
import unicodedata

import pytest

from plugins.bot_unified_runtime.character.shared_group import (
    OpenAICompatibleGroupSummarizer,
)
from plugins.bot_unified_runtime.character.temporal import (
    OpenMeteoWeatherProvider,
    _WeatherSnapshot,
)
from plugins.bot_unified_runtime.character.vector_knowledge import (
    SqliteVectorKnowledgeStore,
)
from plugins.bot_unified_runtime.security.content_safety import (
    assess_public_content,
    normalize_for_matching,
)
from plugins.bot_unified_runtime.security.memory_sanitize import _match_category

# ---------------------------------------------------------------------------
# C17a: 查询向量归一化
# ---------------------------------------------------------------------------


class _FixedVectorEmbed:
    """嵌入桩：所有文本返回同一固定向量（模长刻意 != 1）。"""

    signature = "fixed-vector"

    def __init__(self, vector: list[float]) -> None:
        self._vector = list(vector)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [list(self._vector) for _ in texts]


def _store_with_one_vector(vector: list[float], embed_vector: list[float], tmp_path):
    # 注意不能用 :memory:：_connect() 每次新建连接，:memory: 库互相不可见。
    store = SqliteVectorKnowledgeStore(
        db_path=str(tmp_path / "vector_test.sqlite3"),
        embed_provider=_FixedVectorEmbed(embed_vector),
        top_k=4,
        auto_reset=False,
    )
    with store._connect() as connection:
        connection.execute(
            "INSERT INTO knowledge_chunks "
            "(chunk_id, source_id, title, content, content_hash, vector_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("c1", "src", "词条", "正文内容", "hash-1", json.dumps(vector)),
        )
    return store


def test_vector_candidates_normalizes_query_vector(tmp_path) -> None:
    # 库内向量 [3,4]（模长 5，单位向 [0.6,0.8]）；查询与它同向但模长 0.1。
    # 归一化后余弦应为 1.0；未归一化的旧实现会得到 0.1（被查询模长缩放）。
    store = _store_with_one_vector([3.0, 4.0], [0.06, 0.08], tmp_path)

    ranked, best = store._vector_candidates([0.06, 0.08])

    assert ranked == ["c1"]
    assert best == pytest.approx(1.0, abs=1e-5)


def test_retrieve_low_confidence_threshold_unaffected_by_query_norm(tmp_path) -> None:
    # 无关键词命中时：最高余弦 1.0 >= 0.30 阈值，必须正常返回结果；
    # 旧实现查询模长 0.1 把分数压到 0.1 < 0.30，被误判为低置信未命中。
    store = _store_with_one_vector([3.0, 4.0], [0.06, 0.08], tmp_path)

    chunks = store.retrieve("这个词条讲什么")

    assert [chunk.chunk_id for chunk in chunks] == ["c1"]


def test_retrieve_zero_norm_query_returns_empty(tmp_path) -> None:
    # 零向量查询不崩溃、返回空（归一化保护的 1e-9 分支）。
    store = _store_with_one_vector([3.0, 4.0], [0.0, 0.0], tmp_path)

    chunks = store.retrieve("随便问一句")

    assert chunks == []


# ---------------------------------------------------------------------------
# C20: 安全规则匹配 Unicode 归一化
# ---------------------------------------------------------------------------


def _ascii_word(*parts: str) -> str:
    return "".join(parts)


def _fullwidth(text: str) -> str:
    """ASCII → 全角（U+FF01 起，偏移 0xFEE0）。"""
    return "".join(chr(ord(ch) + 0xFEE0) for ch in text)


def test_normalize_for_matching_folds_width_zero_width_and_spaces() -> None:
    assert normalize_for_matching("ＡＢＣ ｄｅｆ") == "ABC def"
    assert normalize_for_matching("ab\u200bc\u200dd\ufeffe") == "abcde"
    assert normalize_for_matching("a \t\n b") == "a b"
    assert normalize_for_matching("") == ""
    assert normalize_for_matching(None) == ""  # type: ignore[arg-type]


def test_content_safety_hits_fullwidth_and_zero_width_variants() -> None:
    # 规则词用变量拼接构造，不在测试里落具体敏感词字面量。
    word = _ascii_word("n", "s", "f", "w")
    assert assess_public_content(word).action == "refuse"
    # 全角变体此前无法命中既有规则。
    assert assess_public_content(_fullwidth(word)).action == "refuse"
    # 夹零宽字符变体此前同样漏检。
    zero_width = word[:2] + "\u200b" + word[2:] + "\ufeff"
    assert assess_public_content(zero_width).action == "refuse"


def test_content_safety_normal_text_not_flagged() -> None:
    normal_texts = [
        "今天天气不错，我们去散步吧。",
        "这个函数的复杂度是 O(n log n)。",
        "记得把 report 发给我，谢谢！",
    ]
    for text in normal_texts:
        result = assess_public_content(text)
        assert result.action == "allow"
        assert result.category == "none"


def test_memory_sanitize_hits_zero_width_variant() -> None:
    # CJK 规则词用码点拼接（5E9F 7269），夹零宽字符后必须仍命中 insult。
    word = chr(0x5E9F) + chr(0x7269)
    assert _match_category(word) == "insult"
    assert _match_category(word[0] + "\u200b" + word[1] + "\u200c") == "insult"
    # 普通文本不误伤。
    assert _match_category("今天一起吃了火锅，聊了项目进度。") is None


# ---------------------------------------------------------------------------
# C23: 天气缓存过期返回旧值 + 后台刷新
# ---------------------------------------------------------------------------


def test_weather_expired_cache_returns_old_value_and_refreshes_in_background() -> None:
    provider = OpenMeteoWeatherProvider(
        latitude=1.0, longitude=2.0, timeout_seconds=1.0, cache_seconds=60
    )
    provider._cache = _WeatherSnapshot(
        summary="旧天气：晴", fetched_at=time.monotonic() - 10_000.0
    )

    refreshed = threading.Event()
    remote_calls: list[float] = []

    def _fake_remote(now: float) -> _WeatherSnapshot | None:
        remote_calls.append(now)
        provider._cache = _WeatherSnapshot(summary="新天气：雨", fetched_at=now)
        refreshed.set()
        return provider._cache

    provider._fetch_remote = _fake_remote  # type: ignore[method-assign]

    started = time.monotonic()
    summary = provider.current_weather("request-1")
    elapsed = time.monotonic() - started

    # 过期缓存必须立即返回旧值（不等待网络），刷新交给后台线程。
    assert summary == "旧天气：晴"
    assert elapsed < 1.0
    assert refreshed.wait(timeout=5.0), "后台刷新线程未执行"
    # 后台刷新完成后，下一次读取应拿到新值。
    assert provider.current_weather("request-2") == "新天气：雨"


def test_weather_without_cache_fetches_synchronously() -> None:
    provider = OpenMeteoWeatherProvider(
        latitude=1.0, longitude=2.0, timeout_seconds=1.0, cache_seconds=60
    )

    def _fake_remote(now: float) -> _WeatherSnapshot | None:
        snapshot = _WeatherSnapshot(summary="同步天气：阴", fetched_at=now)
        provider._cache = snapshot
        return snapshot

    provider._fetch_remote = _fake_remote  # type: ignore[method-assign]

    assert provider.current_weather("request-1") == "同步天气：阴"
    # 同步拉取后进入 TTL 缓存。
    assert provider.current_weather("request-2") == "同步天气：阴"


def test_weather_fresh_cache_does_not_touch_network() -> None:
    provider = OpenMeteoWeatherProvider(
        latitude=1.0, longitude=2.0, timeout_seconds=1.0, cache_seconds=1800
    )
    provider._cache = _WeatherSnapshot(
        summary="缓存天气", fetched_at=time.monotonic()
    )

    def _fail_remote(now: float) -> _WeatherSnapshot | None:
        raise AssertionError("缓存新鲜时不应发起网络刷新")

    provider._fetch_remote = _fail_remote  # type: ignore[method-assign]

    assert provider.current_weather("request-1") == "缓存天气"


# ---------------------------------------------------------------------------
# C22: LLM 群摘要缓存 LRU 上限（附带）
# ---------------------------------------------------------------------------


class _CountingLLM:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages: list[dict], **_kwargs: object):
        self.calls += 1

        class _Reply:
            text = "  摘要要点  "

        return _Reply()


def test_group_summarizer_cache_is_bounded_lru() -> None:
    llm = _CountingLLM()
    summarizer = OpenAICompatibleGroupSummarizer(llm, ttl_seconds=3600)

    for index in range(48):
        summarizer.summarize(f"群聊摘要 第{index} 条：话题内容 {unicodedata.normalize('NFKC', 'Ａ')}")

    assert len(summarizer._cache) <= summarizer._CACHE_CAPACITY
    assert summarizer._CACHE_CAPACITY == 32
