"""v21r2 SEARCH 席：ACG 检索意图识别测试（全离线，零网络）。"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.domains.core.search.search_intent import (
    TIMELINESS_BACKGROUND,
    TIMELINESS_LATEST,
    acg_query_variants,
    acg_search_allowed,
    detect_acg_intent,
    extract_acg_query,
)

# ---------------------------------------------------------------------------
# 意图识别样例：正例（ACG 命中 + 时效档）/ 反例（绝不误触）
# ---------------------------------------------------------------------------

_POSITIVE_CASES: list[tuple[str, tuple[str, ...], str]] = [
    # (查询, 期望标签子集, 期望时效档)
    ("芙莉莲第三季出了吗", ("anime",), TIMELINESS_LATEST),
    ("鬼灭之刃最新话更新到哪了", ("anime",), TIMELINESS_LATEST),
    ("咒术回战第25集什么时候出", ("anime",), TIMELINESS_LATEST),
    ("一月新番有哪些值得追", ("anime",), TIMELINESS_LATEST),
    ("2026年7月新番列表", ("anime",), TIMELINESS_LATEST),
    ("孤独摇滚漫画连载到第几话", ("manga",), TIMELINESS_LATEST),
    ("进击的巨人漫画完结了吗", ("manga",), TIMELINESS_LATEST),
    ("原神5.0卡池什么时候复刻", ("game",), TIMELINESS_LATEST),
    ("明日方舟新版本前瞻直播", ("game",), TIMELINESS_LATEST),
    ("鸣潮今天有什么活动", ("game",), TIMELINESS_LATEST),
    ("星穹铁道深渊这期怎么配队", ("game",), TIMELINESS_LATEST),
    ("少女前线2追放公测了吗", ("game",), TIMELINESS_LATEST),
    ("硬控是什么梗", ("meme",), TIMELINESS_BACKGROUND),
    ("下次一定这个梗出自哪里", ("meme",), TIMELINESS_BACKGROUND),
    ("最近B站有什么热梗", ("meme",), TIMELINESS_LATEST),
    ("百大UP主公布了吗", ("meme",), TIMELINESS_LATEST),
    ("B站鬼畜区最近的名场面", ("bilibili",), TIMELINESS_LATEST),
    ("vtuber中之人是什么意思", ("vtuber",), TIMELINESS_BACKGROUND),
    ("EVA剧场版剧情讲了什么", ("anime",), TIMELINESS_BACKGROUND),
    ("芙莉莲的声优是谁", ("anime",), TIMELINESS_BACKGROUND),
    # 纯模式兜底：无词表命中但模式明确
    ("第12集什么时候出", (), TIMELINESS_LATEST),
]

_NEGATIVE_CASES: list[str] = [
    "今天天气怎么样",
    "最新基金行情如何",
    "提醒我12点吃药",
    "用Python写个快速排序",
    "美股最新股价",
    "你好呀",
    "帮我看看今天吃什么",
    "美元兑人民币汇率",
    "",
]


@pytest.mark.parametrize(("text", "tags", "timeliness"), _POSITIVE_CASES)
def test_acg_positive(text: str, tags: tuple[str, ...], timeliness: str) -> None:
    intent = detect_acg_intent(text)
    assert intent.is_acg is True, text
    for tag in tags:
        assert tag in intent.tags, (text, intent.tags)
    assert intent.timeliness == timeliness, (text, intent.timeliness)


@pytest.mark.parametrize("text", _NEGATIVE_CASES)
def test_acg_negative(text: str) -> None:
    intent = detect_acg_intent(text)
    assert intent.is_acg is False, (text, intent.tags, intent.matched_terms)
    assert intent.tags == ()


def test_timeliness_constants() -> None:
    assert TIMELINESS_LATEST == "latest"
    assert TIMELINESS_BACKGROUND == "background"
    assert detect_acg_intent("原神卡池").wants_latest


def test_matched_terms_auditable() -> None:
    intent = detect_acg_intent("芙莉莲漫画连载到哪了")
    assert "芙莉莲" in intent.matched_terms
    assert "漫画" in intent.matched_terms


# ---------------------------------------------------------------------------
# 门禁：安全红线 NEVER 永不放行；知识缺口类 NEVER 放行
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reason",
    [
        "explicit_no_web",
        "short_smalltalk",
        "asks_user_identity",
        "you_state_chat",
        "personal_emotional",
        "creative_roleplay",
        "user_provided_content",
        "empty",
    ],
)
def test_denied_reasons(reason: str) -> None:
    assert acg_search_allowed(reason) is False


@pytest.mark.parametrize(
    "reason",
    [
        "general_static_knowledge",
        "no_strong_signal",
        "temporal_intent",
        "entity_not_in_domain",
        "explicit_search",
        "domain_lore",
        "domain_fallback",
        "technical_how_to",
        "real_world_signal",
        "",
    ],
)
def test_allowed_reasons(reason: str) -> None:
    assert acg_search_allowed(reason) is True


# ---------------------------------------------------------------------------
# 查询洗涤与变体
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("芙莉莲第三季出了吗", "芙莉莲第三季"),
        ("硬控是什么梗", "硬控"),
        ("原神5.0卡池最新消息", "原神5.0卡池"),
        ("请问帮我看看孤独摇滚", "孤独摇滚"),
        ("咒术回战哪里能看", "咒术回战"),
        ("", ""),
    ],
)
def test_extract_acg_query(raw: str, expected: str) -> None:
    assert extract_acg_query(raw) == expected


def test_query_variants_by_tag() -> None:
    anime = detect_acg_intent("芙莉莲哪里能看")
    variants = acg_query_variants("芙莉莲哪里能看", anime)
    assert variants and any("番剧" in v for v in variants)

    meme = detect_acg_intent("硬控是什么梗")
    variants = acg_query_variants("硬控是什么梗", meme)
    assert variants and any("出处" in v for v in variants)

    game = detect_acg_intent("原神卡池")
    variants = acg_query_variants("原神卡池", game)
    assert variants and any("前瞻" in v or "版本" in v for v in variants)


def test_query_variants_not_acg_empty() -> None:
    intent = detect_acg_intent("今天天气怎么样")
    assert acg_query_variants("今天天气怎么样", intent) == []


def test_query_variants_at_most_two() -> None:
    intent = detect_acg_intent("芙莉莲漫画B站名场面")
    assert len(acg_query_variants("芙莉莲漫画B站名场面", intent)) <= 2
