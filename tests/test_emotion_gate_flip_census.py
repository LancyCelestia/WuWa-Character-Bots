"""情感腿让位前的翻转尺（2026-10-03，台账 #75）。

为什么必须先有它：`tests/test_acg_intent_tiers.py` 锁的是 `detect_acg_intent`
（search_intent 三档），**不锁 `classify_question_intent`**——也就是说动 `question_intent.py`
的闸口次序**躲得过本仓自己的注毒门禁**。这把尺把"情感腿一票否决掉了多少句本该检索的
现实题"与"让位后会误开多少句闲聊"同时量出来，两侧都是判据，不是读数展示。

⚠ 结构债收口（Task 5）：`_pull` 的**判据形状**不得与生产 `reality_pull` 各写一套。
Task 5 落地后本尺改为直接调用 `question_intent.is_timely_reality` / `reality_pull`，
开搜域集合也从生产 `REALITY_TIMELY_DOMAINS` 取，禁两处各立一份正则或集合。
"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.runtime import question_intent as qi

# 开搜域集合的真身在生产（qi.REALITY_TIMELY_DOMAINS）；尺不另立第二份集合。
# (标签, 原话, 期望：让位后该上网?)  —— P 组＝生产遥测实锤过的案发原话
CENSUS: tuple[tuple[str, str, bool], ...] = (
    ("P1436", "byd为什么ai都喜欢前台派子代理😅😅😅", True),
    ("P1437", "llm ai大模型派子agent都喜欢放前台占用会话窗口，为啥不放background", True),
    ("P1438", "你知道NPU吗", True),
    ("P1439", "你知道LLM是什么吗", True),
    ("E1", "今天心情不好，陪我聊聊", False),
    ("E2", "晚安，辛苦了", False),
    ("E3", "你能陪我待一会儿吗", False),
    ("E4", "谢谢你的陪伴", False),
    ("E5", "我最近老做梦，梦见海", False),
    ("H1", "我喜欢苹果", False),
    ("H2", "他训练得很累", False),
    ("H3", "我感觉显卡的功耗越来越夸张了", False),
    ("H6", "我喜欢那首歌的钢琴版本", False),
)


def _pull(text: str) -> bool:
    """让位判据＝逐字复用生产 `is_timely_reality` / `reality_pull`（Task 5 已并，禁第二真身）。

    尺与闸口 2 同调这两枚纯函数，集合也从 `qi.REALITY_TIMELY_DOMAINS` 取；
    这里只做「把原话拆成生产判定要的六个旗标」，不重写任何正则或组合公式。
    """
    st = qi._strip(text)
    question_like = qi._is_question_like(st)
    timely = qi.classify_timely_domain(
        st, in_local_domain=any(term in st for term in qi.DOMAIN_TERMS), domain_hint=None
    )
    return qi.reality_pull(
        question_like=question_like,
        timely_reality=qi.is_timely_reality(
            timely=timely,
            static_knowledge=bool(qi._STATIC_KNOWLEDGE_RE.search(st)),
            opinion_eval=bool(qi._OPINION_EVAL_RE.search(st)),
        ),
        explicit_search=bool(qi._EXPLICIT_SEARCH_RE.search(st)),
        external_entity_anchor=bool(qi._EXTERNAL_ENTITY_RE.search(st)),
        current=bool(qi._CURRENT_RE.search(st)),
        current_request=bool(qi._CURRENT_REQUEST_RE.search(st)),
    )


@pytest.mark.parametrize(("tag", "text", "want_web"), CENSUS)
def test_pull_flag_matches_expectation(tag, text, want_web):
    assert _pull(text) is want_web, f"{tag} 让位判据与预期不符（先修尺再谈改判据）"


def test_emotion_gate_yields_to_reality_pull_but_keeps_teeth():
    """让位锁（Task 5 落地后的现状）：情感腿不再吃掉带问句形状的现实题，
    但对真情感句仍一票否决——证明这是「让位」而非「拆掉情感腿」。

    Task 4 的「现状腿」（P1436/P1437 当时都 `personal_emotional`）已在 census 里取过，
    本波正是要把它翻掉，故此处钉的是**改后**不变量：
    * 案发两条 → 决策 PRIMARY、reason 不再是 personal_emotional、`_pull` 为真；
    * 真情感一句（E1）→ 仍 personal_emotional / NEVER、`_pull` 为假。
    """
    for text in (
        "byd为什么ai都喜欢前台派子代理😅😅😅",
        "llm ai大模型派子agent都喜欢放前台占用会话窗口，为啥不放background",
    ):
        d = qi.classify_question_intent(text)
        assert _pull(text) is True, f"{text} 现实题判据应成立"
        assert d.reason != "personal_emotional", f"情感腿仍在吃掉现实题：{d.reason}"
        assert d.decision is qi.WebDecision.PRIMARY, f"{text} 该转 PRIMARY：{d.decision}"

    e1 = "今天心情不好，陪我聊聊"
    d = qi.classify_question_intent(e1)
    assert d.reason == "personal_emotional" and d.decision is qi.WebDecision.NEVER, (
        f"情感腿被误拆，真情感句不再被否决：{d.reason}/{d.decision}"
    )
    assert _pull(e1) is False, "真情感句的开搜判据不该成立"
