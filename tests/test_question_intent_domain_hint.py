"""GENERAL 廉价 LLM 二判兜底（2026-10-03 检索与知识波·施工席2）的判据锁。

四条锁面：

① **缺省逐字节不变**：``domain_hint=None``（含完全不传）时
   ``classify_timely_domain`` / ``classify_question_intent`` 的产物与既有行为
   全等——钩子是**可注入**的增强，不许在缺省路上改任何一个字节。
② **只升不抢**：钩子只在确定性判定已落 GENERAL 时被征询； SPORTS/FINANCE/
   ANIME_LORE 等既有判域不许被钩子改写，「不要联网」与闲聊闸照旧压过一切。
③ **fail-open**：钩子抛异常/回认不出的值/回 GENERAL 一律当「不表态」，
   判定链照旧回 GENERAL——二判绝不许变成新的故障面。
④ **适配函数**（``llm_timely_domain_hint``）：形态对齐 chat.py
   ``_ask_policy_llm_once``（model_router 优先、llm_provider 兜底），
   解析认值/名两形，任何失败回 None。

全部离线：假 provider/recorder，零网络、零读钟、零写盘。
"""

from __future__ import annotations

from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.runtime.question_intent import (
    TimelyDomain,
    WebDecision,
    classify_question_intent,
    classify_timely_domain,
    decide_web_search,
    llm_timely_domain_hint,
)

# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------

_KB_RICH = {
    "answerable": True,
    "confidence": 0.9,
    "chunk_count": 4,
    "knowledge_threshold": 0.6,
    "confidence_floor": 0.2,
}

#: 闭集正则的**现行漏词形**：断言它今天确实落 GENERAL（若将来词表收录了它，
#: 这里会红——那说明二判兜底对它已无必要，本锁的语义仍成立）。
_MISSED_FINANCE_TEXT = "医保报销比例今年提高了吗"


class _FakeReply:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeRouter:
    """model_router 形：generate(messages, *, message_text, override, session_id, **kw)。"""

    def __init__(self, reply: str = "", *, error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    def generate(self, messages: list[dict[str, str]], **kwargs: Any) -> Any:
        self.calls.append((messages, kwargs))
        if self.error is not None:
            raise self.error
        return _FakeReply(self.reply)


class _FakeProvider:
    def __init__(self, reply: str = "", *, error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.calls: list[Any] = []

    def generate(self, messages: list[dict[str, str]], **kwargs: Any) -> Any:
        self.calls.append((messages, kwargs))
        if self.error is not None:
            raise self.error
        return _FakeReply(self.reply)


# ---------------------------------------------------------------------------
# ① 缺省逐字节不变
# ---------------------------------------------------------------------------

_PROBE_CORPUS = [
    "英超比分",
    "守岸人是谁",
    "鸣潮新版本更新了什么",
    "你好呀",
    "今天心情不好",
    "帮我写一首诗",
    "不要联网，英超比分",
    _MISSED_FINANCE_TEXT,
    "iPhone 17 发布时间",
    "",
]


@pytest.mark.parametrize("text", _PROBE_CORPUS)
def test_default_none_keeps_domain_verbatim(text: str) -> None:
    assert classify_timely_domain(text) == classify_timely_domain(text, domain_hint=None)


@pytest.mark.parametrize("text", _PROBE_CORPUS)
def test_default_none_keeps_full_decision_verbatim(text: str) -> None:
    assert classify_question_intent(text) == classify_question_intent(text, domain_hint=None)


def test_missed_finance_phrase_is_general_today() -> None:
    """前提锁：这句**今天**确实被闭集正则漏成 GENERAL（二判兜底的存在依据）。"""
    assert classify_timely_domain(_MISSED_FINANCE_TEXT) == TimelyDomain.GENERAL.value


# ---------------------------------------------------------------------------
# ② 只升不抢：GENERAL 才征询，既有判域与安全闸不被改写
# ---------------------------------------------------------------------------


def test_hint_upgrades_general_to_finance() -> None:
    hinted = classify_timely_domain(
        _MISSED_FINANCE_TEXT, domain_hint=lambda _t: TimelyDomain.FINANCE
    )
    assert hinted == TimelyDomain.FINANCE.value


def test_hinted_domain_reaches_primary_and_must_search() -> None:
    decision = classify_question_intent(
        _MISSED_FINANCE_TEXT, domain_hint=lambda _t: TimelyDomain.FINANCE.value
    )
    assert decision.decision is WebDecision.PRIMARY, decision.reason
    assert "timely_domain_signal" in decision.reason_codes
    assert decide_web_search(
        web_enabled=True,
        decision=decision.decision,
        allow_web_fallback=decision.allow_web_fallback,
        **_KB_RICH,  # type: ignore[arg-type]
    )


def test_hint_cannot_rewrite_a_deterministic_domain() -> None:
    assert (
        classify_timely_domain("英超比分", domain_hint=lambda _t: TimelyDomain.FINANCE)
        == TimelyDomain.SPORTS.value
    )
    assert (
        classify_timely_domain(
            "守岸人是谁", domain_hint=lambda _t: TimelyDomain.CURRENT_AFFAIRS
        )
        == TimelyDomain.ANIME_LORE.value
    )


def test_no_web_red_line_survives_the_hint() -> None:
    decision = classify_question_intent(
        f"不要联网，{_MISSED_FINANCE_TEXT}",
        domain_hint=lambda _t: TimelyDomain.FINANCE,
    )
    assert decision.decision is WebDecision.NEVER, decision.reason


def test_small_talk_red_line_survives_the_hint() -> None:
    for text in ("今天心情不好", "你好呀", "陪我聊聊"):
        decision = classify_question_intent(text, domain_hint=lambda _t: TimelyDomain.NEWS)
        assert decision.decision is WebDecision.NEVER, (text, decision.reason)


# ---------------------------------------------------------------------------
# ③ fail-open：异常/不表态/认不出一律按没有钩子走
# ---------------------------------------------------------------------------


def _never_called_hint(_text: str) -> str:
    raise AssertionError("既有判域不该征询钩子")


def test_hint_not_consulted_when_deterministic_domain_exists() -> None:
    assert (
        classify_timely_domain("英超比分", domain_hint=_never_called_hint)
        == TimelyDomain.SPORTS.value
    )


@pytest.mark.parametrize(
    "bad_hint",
    [
        lambda _t: None,
        lambda _t: "not_a_domain",
        lambda _t: TimelyDomain.GENERAL,
        lambda _t: "general",
        lambda _t: 12345,
        lambda _t: (_ for _ in ()).throw(RuntimeError("hint exploded")),
    ],
)
def test_unusable_hint_falls_back_to_general(bad_hint: Any) -> None:
    assert (
        classify_timely_domain(_MISSED_FINANCE_TEXT, domain_hint=bad_hint)
        == TimelyDomain.GENERAL.value
    )
    baseline = classify_question_intent(_MISSED_FINANCE_TEXT)
    hinted = classify_question_intent(_MISSED_FINANCE_TEXT, domain_hint=bad_hint)
    assert hinted == baseline


# ---------------------------------------------------------------------------
# ④ 适配函数：形态、解析与 fail-open
# ---------------------------------------------------------------------------


def test_adapter_prefers_model_router_and_passes_cheap_budget() -> None:
    router = _FakeRouter(reply="finance_economy")
    provider = _FakeProvider(reply="news")
    assert (
        llm_timely_domain_hint(_MISSED_FINANCE_TEXT, llm_provider=provider, model_router=router)
        == TimelyDomain.FINANCE.value
    )
    assert provider.calls == [], "给了 router 就不该再打 provider"
    messages, kwargs = router.calls[0]
    assert kwargs["max_tokens"] <= 32 and kwargs["timeout_seconds"] <= 8.0, (
        "二判必须廉价：小 max_tokens、短超时",
    )
    assert messages[-1]["content"].startswith("医保报销比例")


def test_adapter_falls_back_to_llm_provider() -> None:
    provider = _FakeProvider(reply="  FINANCE  ")
    assert (
        llm_timely_domain_hint(_MISSED_FINANCE_TEXT, llm_provider=provider) == TimelyDomain.FINANCE.value
    )


@pytest.mark.parametrize("reply", ["general", "GENERAL", "我看不懂", "", "```"])
def test_adapter_returns_none_for_non_committal_replies(reply: str) -> None:
    assert llm_timely_domain_hint("随便什么", llm_provider=_FakeProvider(reply=reply)) is None


def test_adapter_backtick_wrapped_tag_is_parsed() -> None:
    assert (
        llm_timely_domain_hint("巴萨这轮赢了吗", llm_provider=_FakeProvider(reply="`sports`"))
        == TimelyDomain.SPORTS.value
    )


def test_adapter_returns_none_without_any_provider() -> None:
    assert llm_timely_domain_hint(_MISSED_FINANCE_TEXT) is None


def test_adapter_returns_none_on_empty_text() -> None:
    router = _FakeRouter()
    assert llm_timely_domain_hint("   ", model_router=router) is None
    assert router.calls == [], "空文本不许打一次 LLM"


@pytest.mark.parametrize(
    "kwargs",
    [{"model_router": _FakeRouter(error=RuntimeError("boom"))}, {"llm_provider": _FakeProvider(error=RuntimeError("boom"))}],
)
def test_adapter_swallows_provider_failures(kwargs: dict[str, Any]) -> None:
    assert llm_timely_domain_hint(_MISSED_FINANCE_TEXT, **kwargs) is None


def test_adapter_reply_is_bound_into_the_real_decision_chain() -> None:
    """端到端形：适配函数输出直接作 domain_hint 注入判定链（接线行的最小复现）。"""
    router = _FakeRouter(reply="current_affairs")
    decision = classify_question_intent(
        _MISSED_FINANCE_TEXT,
        domain_hint=lambda q: llm_timely_domain_hint(q, model_router=router),
    )
    assert decision.decision is WebDecision.PRIMARY, decision.reason
    assert router.calls, "钩子真的被征询了一次"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
