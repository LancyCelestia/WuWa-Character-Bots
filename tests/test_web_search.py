"""问题意图分层判定（v2，不斩断联网权限）+ 联网检索提供器测试。"""

from plugins.bot_unified_runtime.runtime.question_intent import (
    QuestionIntent,
    classify_question_intent,
)
from plugins.bot_unified_runtime.sources.web_search import (
    DuckDuckGoWebSearchProvider,
    _extract_bing_hits,
    _extract_ddg_hits,
)


def test_domain_entity_questions_use_knowledge_first_with_web_fallback():
    # 领域实体问句：知识库优先，但保留联网回退（不斩断权限）。
    for text in [
        "鸣潮是什么",
        "今州是什么",
        "拉古那是什么",
        "七丘是什么",
        "漂泊者是谁",
        "艾弥斯是谁",
        "洛斯拉是谁",
    ]:
        decision = classify_question_intent(text)
        assert decision.intent is QuestionIntent.KNOWLEDGE_FIRST, (text, decision)
        assert decision.allow_web_fallback is True, text


def test_real_world_entity_questions_search():
    # 同一语法但实体不是领域词：百科联网。
    for text in [
        "习近平是谁",
        "普京是谁",
        "陈睿是谁",
        "库洛游戏是个什么样的公司",
    ]:
        decision = classify_question_intent(text)
        assert decision.intent is QuestionIntent.WEB_SEARCH, (text, decision)


def test_temporal_questions_search_even_with_domain_terms():
    for text in [
        "鸣潮今天更新了什么",
        "鸣潮2.0什么时候上线",
        "守岸人卡池什么时候复刻",
        "你知道鸣潮演唱会吗",
        "你知道库洛所在地吗",
    ]:
        decision = classify_question_intent(text)
        assert decision.intent is QuestionIntent.WEB_SEARCH, (text, decision)


def test_real_world_signals_never_blocked():
    for text in [
        "今州房价多少",
        "守岸人手办多少钱",
        "库洛游戏在哪里",
    ]:
        assert classify_question_intent(text).intent is QuestionIntent.WEB_SEARCH, text


def test_self_chat_does_not_search():
    for text in ["你最近怎么样", "守岸人今天心情怎么样", "岸宝在吗", "今天有点累，陪我说说话"]:
        decision = classify_question_intent(text)
        assert decision.intent is not QuestionIntent.WEB_SEARCH, text


def test_general_knowledge_questions_now_search():
    # 用户要求大部分消息联网：科普/科学/方法类问句默认联网。
    for text in [
        "为什么天空是蓝的",
        "Python 怎么安装",
        "什么是光合作用",
        "量子力学是什么",
    ]:
        assert classify_question_intent(text).intent is QuestionIntent.WEB_SEARCH, text


def test_plain_chat_still_neutral():
    for text in ["今天天气不错", "播放量好高", "今天有点累，陪我说说话"]:
        assert classify_question_intent(text).intent is QuestionIntent.NEUTRAL, text


def test_real_world_categories_always_search():
    for text in ["当前国际局势怎么样", "中美贸易战是怎么回事", "芯片制造原理是什么"]:
        assert classify_question_intent(text).intent is QuestionIntent.WEB_SEARCH, text


def test_ddg_extract_hits_from_html():
    html = (
        '<div class="result"><a class="result__a" href="https://example.com/a">'
        "标题A</a><a class=\"result__snippet\">摘要A</a></div>"
    )
    hits = _extract_ddg_hits(html, max_results=2)
    assert hits and hits[0].title == "标题A"
    assert hits[0].source_domain == "example.com"


def test_bing_extract_hits_from_html():
    html = (
        '<li class="b_algo"><h2><a href="https://example.org/b">标题B</a></h2>'
        "<p>摘要B</p></li>"
    )
    hits = _extract_bing_hits(html, max_results=2)
    assert hits and hits[0].title == "标题B"
    assert hits[0].snippet == "摘要B"


def test_provider_search_returns_empty_on_network_error(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    provider = DuckDuckGoWebSearchProvider(timeout_seconds=1.0)
    assert provider.search("今天的新闻", max_results=3) == []


def test_filter_drops_dictionary_junk_and_keeps_relevant():
    from plugins.bot_unified_runtime.sources.web_search import (
        WebSearchHit,
        _filter_relevant,
    )

    junk = WebSearchHit(
        title="库（汉语汉字）_百度百科",
        snippet="本义为收藏兵车及其他武器的处所。",
        url="https://baike.baidu.com/item/库",
        source_domain="baike.baidu.com",
    )
    relevant = WebSearchHit(
        title="库街区 - 库洛游戏官方社区",
        snippet="《库街区》是库洛游戏官方社区APP。",
        url="https://www.kurobbs.com",
        source_domain="www.kurobbs.com",
    )
    hits = _filter_relevant([junk, relevant], "库洛游戏 公司 百科")
    assert len(hits) == 1
    assert hits[0].url == relevant.url


def test_fetch_page_text_returns_empty_for_bad_url(monkeypatch):
    from plugins.bot_unified_runtime.sources.web_search import fetch_page_text

    def boom(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    assert fetch_page_text("https://example.com/x", timeout_seconds=1.0) == ""


def test_web_hits_sorted_by_preferred_encyclopedia():
    from plugins.bot_unified_runtime.capabilities.chat import _sort_web_hits
    from plugins.bot_unified_runtime.sources.web_search import WebSearchHit

    hits = [
        WebSearchHit(title="百度", snippet="", url="https://baike.baidu.com/x", source_domain="baike.baidu.com"),
        WebSearchHit(title="维基", snippet="", url="https://zh.wikipedia.org/y", source_domain="zh.wikipedia.org"),
        WebSearchHit(title="萌娘", snippet="", url="https://zh.moegirl.org.cn/z", source_domain="zh.moegirl.org.cn"),
    ]
    ordered = _sort_web_hits(hits)
    assert ordered[0].source_domain == "zh.moegirl.org.cn"
    assert ordered[1].source_domain == "zh.wikipedia.org"
    assert ordered[2].source_domain == "baike.baidu.com"
