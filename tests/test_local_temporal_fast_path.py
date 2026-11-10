"""本地时间/日期问句必须走本地上下文，禁止触发知识库与联网检索。

回归对象（2026-11-10 实测）：一句「现在几点」在 console 里触发
vector_knowledge.retrieve（约 14.5s）与 web_search（约 12.2s），把
一轮简单对话拖到 37s。时间事实已经由 TemporalContext 注入，不需要
外部检索；这里锁住分类与 build_context 两条腿。
"""

from __future__ import annotations

from typing import Any

from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
    FileCharacterContextProvider,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.temporal import (
    RuleBasedTemporalProvider,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.question_intent import (
    WebDecision,
    classify_question_intent,
    is_local_temporal_query,
)


def test_local_temporal_queries_are_classified_never() -> None:
    for text in (
        "现在几点了？",
        "今天几号",
        "今天星期几？",
        "现在是什么节气",
        "今天是什么季节",
        "今年是哪一年",
        "现在农历几月几号",
    ):
        decision = classify_question_intent(text)
        assert decision.category == "LOCAL_TEMPORAL", text
        assert decision.reason == "local_temporal", text
        assert decision.decision is WebDecision.NEVER, text
        assert decision.allow_web_fallback is False, text


def test_local_temporal_helper_rejects_news_and_weather() -> None:
    assert is_local_temporal_query("现在几点") is True
    assert is_local_temporal_query("今天有什么新闻？") is False
    assert is_local_temporal_query("今天天气怎么样") is False
    assert is_local_temporal_query("鸣潮今天更新了什么") is False


def test_news_query_still_goes_to_web() -> None:
    decision = classify_question_intent("今天有什么新闻？")
    assert decision.decision is WebDecision.PRIMARY


def test_build_context_skips_knowledge_retrieval_for_local_time() -> None:
    calls: list[str] = []

    def retriever(query: str) -> list[Any]:
        calls.append(query)
        return []

    provider = FileCharacterContextProvider(
        persona_profile_id="test",
        persona_display_name="测试人格",
        persona_version="1",
        persona_files=[],
        knowledge_files=[],
        vector_retriever=retriever,
        temporal_provider=RuleBasedTemporalProvider(timezone="Asia/Singapore"),
    )
    provider.build_context("req-1", "u1", "private:u1", "现在几点了？")
    assert calls == []

    provider.build_context("req-2", "u1", "private:u1", "鸣潮 今汐 剧情")
    assert calls == ["鸣潮 今汐 剧情"]
