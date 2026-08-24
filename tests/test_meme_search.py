from plugins.bot_unified_runtime.sources.meme_search import (
    DuckDuckGoMemeSearchProvider,
    NullMemeSearchProvider,
    _domain_of,
    _strip_html,
    extract_meme_query,
    filter_meme_results,
)


def test_extract_meme_query_ask_patterns():
    assert extract_meme_query("这到底是什么意思？") is not None
    assert extract_meme_query('"鼠鼠我鸭"是什么梗？') == "鼠鼠我鸭"
    assert extract_meme_query("\u201c鼠鼠我鸭\u201d是什么梗？") == "鼠鼠我鸭"
    assert extract_meme_query("抽象是什么意思") is not None
    assert extract_meme_query("今天天气不错") is None
    assert extract_meme_query("你好呀") is None


def test_extract_meme_query_short_term_with_question_mark():
    assert extract_meme_query("NBCS?") == "NBCS"
    assert extract_meme_query("绝区零?") == "绝区零"


def test_null_provider_returns_empty():
    provider = NullMemeSearchProvider()

    assert provider.search("鼠鼠我鸭") == []


def test_domain_and_html_helpers():
    assert _domain_of("https://www.bilibili.com/video/BV1xx") == "www.bilibili.com"
    assert _strip_html("<b>标题</b> 摘要") == "标题 摘要"


def test_meme_results_filter_unpreferred_domains_and_blocked_terms():
    items = [
        (
            "某梗的解释",
            "这个梗出自一部动画",
            "https://www.bilibili.com/video/BV1xx",
        ),
        (
            "不好的内容",
            "某网红去世相关",
            "https://news.example.com/a/1",
        ),
        (
            "被过滤的内容",
            "包含歧视言论的烂梗",
            "https://www.bilibili.com/video/BV2xx",
        ),
    ]

    results = filter_meme_results("某梗", items)

    assert len(results) == 1
    assert results[0].source_domain == "www.bilibili.com"


def test_meme_provider_caches_results(monkeypatch):
    provider = DuckDuckGoMemeSearchProvider(cache_seconds=3600)
    calls = {"count": 0}

    def fake_fetch(query: str):
        calls["count"] += 1
        return [("标题", "摘要", "https://zh.moegirl.org.cn/某词条")]

    monkeypatch.setattr(provider, "_fetch", fake_fetch)

    provider.search("某词条")
    provider.search("某词条")

    assert calls["count"] == 1
