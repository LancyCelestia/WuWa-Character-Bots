"""S3 席：词表补现实实体后的分类器 A/B 对照锁 + 日常句防误开对照腿。

背景（现算取证，2026-10-02）：席简报给的「HKACG 是什么 改前 never」**未在工作树复现**——
它改前就已是 ``primary``（reason ``entity_not_in_domain``，走的是「域外实体 + 是什么」那条腿）。
本件因此把 A/B 的**实测轴**写清楚，并锁住两件事：

① 现实实体补进 ``ACG_DOMAIN_TERMS`` 的**新子域**（expo/hardware）之后，竖源腿（ACG 检索）
   从「不判」变「判」——这是本波真正改变的行为；
② 决策档（NEVER/PRIMARY/FALLBACK/TOOL_ALLOWED）**一格都不许被推倒**：
   「漫展/展会」类若被并进 ``game`` 强档，就会被 ``question_intent.DOMAIN_TERMS`` 读成
   「本地库已知话题」⇒ 从 PRIMARY 掉到 FALLBACK（库里现实条目为 0，等于不联网）。
   ``test_expo_terms_do_not_leak_into_local_domain_set`` 就是这条反案的门。

零 HTTP：只读调用 ``classify_question_intent`` / ``decide_web_search`` / ``detect_acg_intent``。
"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.runtime import question_intent as qi
from plugins.bot_unified_runtime.domains.core.search import search_intent as si
from plugins.bot_unified_runtime.domains.core.search.search_intent import (
    ACG_DOMAIN_TERMS,
    ACG_TIER_STRONG,
    detect_acg_intent,
)

#: 竖源开关今天生效真值（装载链现算：BOT_SEARCH_ACG_ENABLED=True，见席报告现场段）。
_ACG_ENABLED = True

VERTICAL_LEG_CORPUS: tuple[tuple[str, bool], ...] = (
    # (问句, 是否**应当**触发 ACG 竖源腿)
    ("HKACG 是什么", False),          # 裸缩写＝weak，单独不判（21 句误开的教训）
    ("HKACG 漫展门票多少钱", True),   # 缩写 + 强档「漫展」共现 ⇒ 判
    ("最近的漫展", True),
    ("CP 漫展是什么", True),
    ("cosplay 摄影用什么相机", True),
    ("萤火虫漫展在哪里举办", True),
    ("我去看 CICF", True),
    ("装机和显卡怎么选", False),      # 两枚 weak 词共现仍不判（weak 永不单独成判）
    ("大模型最新进展", True),
)

#: 5 句**不该联网**的日常句（防误开对照组，简报点名必给）。
SHOULD_NOT_SEARCH: tuple[str, ...] = (
    "今天心情不好",
    "帮我看看这段代码",
    "守岸人你喜欢什么",
    "晚安",
    "你是谁",
)


def _decide(text: str) -> qi.IntentDecision:
    return qi.classify_question_intent(text)


def _would_search(text: str) -> bool:
    """现网等价读数：总闸开 + 决策档 + 知识库零命中（现实话题必然零命中）。"""
    d = _decide(text)
    return qi.decide_web_search(
        web_enabled=True,
        decision=d.decision,
        allow_web_fallback=d.allow_web_fallback,
        answerable=False,
        confidence=0.0,
        chunk_count=0,
        knowledge_threshold=0.6,
        confidence_floor=0.15,
    )


def _vertical_leg_fires(text: str) -> bool:
    """``run_acg`` 的三件判定（chat.py 同式）：开关 ∧ 词表 ∧ reason 未被红线否决。"""
    d = _decide(text)
    return bool(_ACG_ENABLED and detect_acg_intent(text).is_acg and si.acg_search_allowed(d.reason))


# ---------------------------------------------------------------------------
# ① 决策档：简报点名的四句（改后读数原样钉住）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("HKACG 是什么", qi.WebDecision.PRIMARY),
        ("库洛科技在哪里", qi.WebDecision.FALLBACK),  # 如实：库洛已在 game 强档＝本地域词
        ("英伟达最新芯片", qi.WebDecision.PRIMARY),
        ("最近的漫展", qi.WebDecision.PRIMARY),
    ],
)
def test_decision_tiers_after_the_wordlist(text: str, expected: qi.WebDecision) -> None:
    assert _decide(text).decision is expected, f"{text} 决策档漂了：{_decide(text).reason}"


@pytest.mark.parametrize("text", ["HKACG 是什么", "最近的漫展", "英伟达最新芯片"])
def test_named_real_world_questions_actually_search(text: str) -> None:
    assert _would_search(text) is True, f"{text} 判了档却没上网：{_decide(text).reason}"


# ---------------------------------------------------------------------------
# ② 竖源腿：本波真正改变的行为
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text,expected", VERTICAL_LEG_CORPUS)
def test_acg_vertical_leg_matches_the_intended_tiering(text: str, expected: bool) -> None:
    assert _vertical_leg_fires(text) is expected, (
        f"{text}：竖源腿判 {not expected}（期望 {expected}）；"
        f"词表命中={detect_acg_intent(text).matched_terms} reason={_decide(text).reason}"
    )


def test_two_letter_proper_names_are_all_weak() -> None:
    """两字母专名一律 weak（21 句误开的直接教训）：CP/CQ/CD/BW/HKACG 单独成句都不判。"""
    for term in ("CP", "CQ", "CD", "BW", "HKACG"):
        assert term in ACG_DOMAIN_TERMS["expo"][si.ACG_TIER_WEAK], term
        assert detect_acg_intent(term).is_acg is False, term


def test_everyday_words_with_non_acg_senses_are_weak() -> None:
    """有日常义项的词（萤火虫＝昆虫、世界线＝科幻、梦乡＝入睡）一律 weak，不单独成判。"""
    for term in ("萤火虫", "世界线", "梦乡"):
        assert term in ACG_DOMAIN_TERMS["expo"][si.ACG_TIER_WEAK], term
        assert detect_acg_intent(term).is_acg is False, term
    # 反过来：与强档共现时它们照样贡献审计词（降档≠删词）。
    intent = detect_acg_intent("萤火虫漫展在哪举办")
    assert intent.is_acg and "萤火虫" in intent.matched_terms


# ---------------------------------------------------------------------------
# ③ 反案门：现实实体绝不许被并进 game 强档（那会掉进 FALLBACK）
# ---------------------------------------------------------------------------

_GAME_STRONG: tuple[str, ...] = ACG_DOMAIN_TERMS["game"][ACG_TIER_STRONG]


@pytest.mark.parametrize("term", ["漫展", "cosplay", "COMICUP", "CICF", "CP", "HKACG", "摄影", "芯片"])
def test_expo_terms_do_not_leak_into_local_domain_set(term: str) -> None:
    """`question_intent.DOMAIN_TERMS` 只读 game 强档 ⇒ 展会/器材词若被挪进去＝本地域误判。"""
    assert term not in _GAME_STRONG, (
        f"{term} 被登记进 game 强档 ⇒ 它会进 DOMAIN_TERMS，"
        "「X 是什么」将从 PRIMARY 掉到 FALLBACK（本地库优先），方向反了"
    )


def test_expo_and_hardware_domains_exist_with_a_decisive_entry() -> None:
    for domain in ("expo", "hardware"):
        tiers = ACG_DOMAIN_TERMS[domain]
        assert set(tiers) == set(si.ACG_TIERS), domain
        assert tiers[ACG_TIER_STRONG] or tiers[si.ACG_TIER_MEDIUM], domain


def test_variants_are_still_capped_at_two() -> None:
    """检索变体面不扩容：新增两子域后仍然 ≤2 条（旧契约）。"""
    for text, _expected in VERTICAL_LEG_CORPUS:
        assert len(si.acg_query_variants(text, detect_acg_intent(text))) <= 2


# ---------------------------------------------------------------------------
# ④ 防误开对照组（简报必给）：5 句日常句没被判成 primary、也没被拖上竖源
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", SHOULD_NOT_SEARCH)
def test_everyday_sentences_are_not_primary(text: str) -> None:
    assert _decide(text).decision is not qi.WebDecision.PRIMARY, text
    assert _would_search(text) is False, f"{text} 被误开联网：{_decide(text).reason}"
    assert _vertical_leg_fires(text) is False, f"{text} 被误开 ACG 竖源"


def test_control_group_is_not_hollow() -> None:
    """对照腿不许变空转：这几句必须真被判过 NEVER 类（而不是全部 TOOL_ALLOWED 蒙过）。"""
    decisions = [_decide(text).decision for text in SHOULD_NOT_SEARCH]
    assert qi.WebDecision.NEVER in decisions, decisions
