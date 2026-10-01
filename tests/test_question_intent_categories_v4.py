"""时效类目分流 v4（WEB 席·用户第 3 项）：赛事/版本更新必搜、二游走库、类目时间窗。

三条分流纪律，各配表驱动用例：

① **时效/权威类必搜**：科技、时政、新闻、金融经济，加上本轮补的**赛事/电竞**
   与**版本更新·补丁**形态——裸话题句（无疑问词、无「最新」）也要触发。
   实证缺口（现算探针）：``英超比分``/``NBA 总决赛``/``世界杯预选赛``/
   ``英雄联盟 S15 冠军``/``中国女排赛程``/``球员转会`` 六句全部
   ``never/no_strong_signal``、域判 ``general``；``Windows 11 最新补丁`` 同判。
② **二游内容走库**：本地域命中 ⇒ ``FALLBACK``（库内优先），库里问得出就不联网编；
   库空才补搜。这一条已有判据（``decide_web_search``），本锁钉死它不被新词表
   顺手拖走——赛事词表与本地域词表同句相撞时，**本地域抢先**。
③ **时间窗按类目收窄**：行情/新闻/赛果按天，时政/科技按周，
   lore 与泛史题**不开窗**（E-3 已经钉过「裸年份历史题绝不进窗」，这里续同一条口径）。

判定面全部走纯函数（``classify_timely_domain`` / ``classify_question_intent`` /
``request_time_window`` / ``decide_web_search``），零网络、零读钟、零写盘。
"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.runtime.question_intent import (
    DOMAIN_TERMS,
    TimelyDomain,
    WebDecision,
    classify_question_intent,
    classify_timely_domain,
    decide_web_search,
    request_time_window,
)

# ---------------------------------------------------------------------------
# 表驱动夹具：库里问得出（高置信）与库里没东西（零命中）两种上下文
# ---------------------------------------------------------------------------

_KB_RICH = {
    "answerable": True,
    "confidence": 0.9,
    "chunk_count": 4,
    "knowledge_threshold": 0.6,
    "confidence_floor": 0.2,
}
_KB_EMPTY = {
    "answerable": False,
    "confidence": 0.0,
    "chunk_count": 0,
    "knowledge_threshold": 0.6,
    "confidence_floor": 0.2,
}


def _searches(text: str, kb: dict[str, object]) -> bool:
    decision = classify_question_intent(text)
    return decide_web_search(web_enabled=True, decision=decision.decision,
                             allow_web_fallback=decision.allow_web_fallback, **kb)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ① 赛事/电竞：类目在册、裸话题句必搜
# ---------------------------------------------------------------------------

SPORTS_TOPIC_PHRASES = [
    "英超比分",
    "NBA 总决赛",
    "世界杯预选赛",
    "英雄联盟 S15 冠军",
    "中国女排赛程",
    "球员转会",
    "欧冠赛果",
    "LPL 季后赛",
]


@pytest.mark.parametrize("text", SPORTS_TOPIC_PHRASES)
def test_sports_topic_phrase_is_classified_sports(text: str) -> None:
    assert classify_timely_domain(text) == TimelyDomain.SPORTS.value, text


@pytest.mark.parametrize("text", SPORTS_TOPIC_PHRASES)
def test_sports_topic_phrase_is_a_hard_must_search(text: str) -> None:
    """无疑问词、无「最新」的裸话题句也必须上网：赛事结果不在模型知识里。"""
    decision = classify_question_intent(text)
    assert decision.decision is WebDecision.PRIMARY, (text, decision.reason)
    assert _searches(text, _KB_RICH) is True, text


def test_sports_opinion_question_stays_off_the_web() -> None:
    """「怎么看」是要观点，不是要事实：域词命中也不许拖上网（既有意见闸）。"""
    decision = classify_question_intent("这场球你怎么看")
    assert decision.decision is not WebDecision.PRIMARY, decision.reason


# ---------------------------------------------------------------------------
# ② 科技补拉丁品牌形与版本/补丁形（E-5 + 「版本更新」类目）
# ---------------------------------------------------------------------------

TECH_SHAPES_NOW_ROUTED_TO_TECH = [
    "iPhone 17 发布时间",
    "Windows 11 最新补丁",
    "iPadOS 更新",
    "PlayStation 5 售价",
    "Galaxy S26 折叠屏",
]
# 刻意不收「Galaxy S26 发布会」这一形：`发布会` 是时政锚点且时政先于科技判，
# 产品发布会归时政是**既有判序**的结果，不在本席改动面内（要改得动判序文档
# 与四张表的优先级论证，那是另一次裁定）。


@pytest.mark.parametrize("text", TECH_SHAPES_NOW_ROUTED_TO_TECH)
def test_latin_product_shapes_are_classified_tech_not_general(text: str) -> None:
    """触发对了、装饰域曾经是错的（E-5）：这里要求**域也判对**，否则按域选源全塌。"""
    assert classify_timely_domain(text) == TimelyDomain.TECH.value, text


@pytest.mark.parametrize("text", TECH_SHAPES_NOW_ROUTED_TO_TECH)
def test_latin_product_shapes_search(text: str) -> None:
    assert _searches(text, _KB_EMPTY) is True, text


def test_ordinary_words_cannot_masquerade_as_latin_brands() -> None:
    """拉丁形必须带词边界：explain/said/pineapple 一类子串不许命中科技域。"""
    for text in ("请 explain 一下", "他 said 今天不去", "pineapple 怎么去皮"):
        assert classify_timely_domain(text) != TimelyDomain.TECH.value, text


# ---------------------------------------------------------------------------
# ③ 二游内容走库：本地域抢先、库里有就不联网、库里没有才补搜
# ---------------------------------------------------------------------------


def test_local_domain_wins_over_sports_words() -> None:
    """同时踩本地世界观与赛事词时判 ANIME_LORE：先按库内 lore 答，不按体育媒体搜。"""
    anchor = DOMAIN_TERMS[0]
    text = f"{anchor}的电竞比赛设定"
    assert classify_timely_domain(text) == TimelyDomain.ANIME_LORE.value, text


def test_lore_question_defers_to_local_knowledge_base() -> None:
    """库里问得出 ⇒ 不联网编（FALLBACK 且高置信不补搜）。"""
    decision = classify_question_intent("守岸人是谁")
    assert decision.decision is WebDecision.FALLBACK, decision.reason
    assert _searches("守岸人是谁", _KB_RICH) is False


def test_lore_question_falls_back_to_web_when_knowledge_base_is_empty() -> None:
    assert _searches("守岸人是谁", _KB_EMPTY) is True


def test_game_version_update_is_anime_lore_not_tech() -> None:
    """「鸣潮新版本更新了什么」是二游时效题：既必须搜（版本公告），又必须按 lore 选源。"""
    text = "鸣潮新版本更新了什么"
    assert classify_timely_domain(text) == TimelyDomain.ANIME_LORE.value
    assert _searches(text, _KB_EMPTY) is True


def test_explicit_no_web_beats_every_new_trigger_word() -> None:
    """新词表不得越过「不要联网」红线：显式禁网恒 NEVER（含赛事/科技形）。"""
    for text in (
        "不要联网，英超比分",
        "只用本地资料查一下 iPhone 17 发布时间",
    ):
        decision = classify_question_intent(text)
        assert decision.decision is WebDecision.NEVER, (text, decision.reason)
        assert _searches(text, _KB_EMPTY) is False, text


def test_small_talk_and_emotion_are_never_dragged_by_sports_words() -> None:
    for text in ("你好呀", "今天心情不好", "陪我聊聊", "帮我写一首诗"):
        decision = classify_question_intent(text)
        assert decision.decision is WebDecision.NEVER, (text, decision.reason)


# ---------------------------------------------------------------------------
# ④ 类目时间窗：纯函数 + 表驱动
# ---------------------------------------------------------------------------

WINDOW_TABLE = [
    (TimelyDomain.FINANCE.value, "day"),
    (TimelyDomain.NEWS.value, "day"),
    (TimelyDomain.SPORTS.value, "day"),
    (TimelyDomain.CURRENT_AFFAIRS.value, "week"),
    (TimelyDomain.TECH.value, "week"),
    # lore 与泛史题不开窗：萌百/维基的设定条目本来就不按天更新。
    (TimelyDomain.ANIME_LORE.value, ""),
    (TimelyDomain.GENERAL.value, ""),
]


@pytest.mark.parametrize(("domain", "expected"), WINDOW_TABLE)
def test_time_window_table_per_category(domain: str, expected: str) -> None:
    assert request_time_window(domain, explicit_latest=True) == expected


@pytest.mark.parametrize("domain", [item[0] for item in WINDOW_TABLE])
def test_time_window_never_opens_without_explicit_latest(domain: str) -> None:
    """裸年份/无明示时效词 ⇒ 绝不开窗（E-3 同一条口径：不许把历史题锁进近周档）。"""
    assert request_time_window(domain, explicit_latest=False) == ""


def test_time_window_is_empty_for_unknown_category() -> None:
    assert request_time_window("no_such_category", explicit_latest=True) == ""


def test_every_declared_category_has_a_declared_window() -> None:
    """同源锁：枚举加一档、窗表没跟上即红（不许出现「有新域、无窗判据」的半程形）。"""
    covered = {domain for domain, _window in WINDOW_TABLE}
    assert covered == {item.value for item in TimelyDomain}, covered ^ {
        item.value for item in TimelyDomain
    }
