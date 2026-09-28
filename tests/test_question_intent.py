"""S-W8 (= S-W5)：联网决策触发面扩面的回归锁。

只测 question_intent.classify_question_intent 的判定面：
(a) 正样本——含域外专名/版本号形态 + 评价·知晓·进展类问法的现实话题，应判为会触发检索；
(b) 负样本——源码注释明言要防的「科学/今天/情绪/闲聊/用户自带内容/本地世界观」等误触发，不应触发；
(c) 边界——纯中文无专名评价句、版本号形态、大小写混排、@ 与表情、超长句。

判据：会触发检索 == intent is QuestionIntent.WEB_SEARCH（decision==PRIMARY 一侧）。
KNOWLEDGE_FIRST(FALLBACK)/NEUTRAL(NEVER/TOOL_ALLOWED) 一律算「不触发检索」一侧。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "chat_reply"
    / "runtime"
    / "question_intent.py"
)


def _load():
    # 直接按文件路径加载，避开包 __init__ 的重依赖（本件只依赖 stdlib）。
    existing = sys.modules.get("question_intent_under_test")
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(
        "question_intent_under_test", _MODULE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["question_intent_under_test"] = module
    spec.loader.exec_module(module)
    return module


_qi = _load()
classify_question_intent = _qi.classify_question_intent
QuestionIntent = _qi.QuestionIntent


def _triggers(text: str) -> bool:
    return classify_question_intent(text).intent is QuestionIntent.WEB_SEARCH


# ---------------------------------------------------------------------------
# (a) 正样本：现实时效 / 域外专名话题，应触发检索
# ---------------------------------------------------------------------------
POSITIVE_SAMPLES = [
    # —— W1 报告点名的 6 条 NEVER 形态（本格的头号目标）——
    "芯片行业国产替代进展如何",
    "英伟达最新财报",
    "Claude Opus 5.5好不好用",
    "你知道GPT-6 Sol吗",
    "Anthropic的Claude Opus 5.5怎么样",
    "AI大模型最新进展",
    # —— 六话题（时政/科技/新闻/芯片/AI大模型/经济）扩样 ——
    "华为芯片技术突破了吗",
    "Gemini 3.0好用吗",
    "美联储最新利率决议怎么看",
    "台积电最新制程进展",
    "ChatGPT 和 Claude 谁更强",
    "苹果发布会讲了啥新功能",
    "GPT-6 的定价多少钱",
    "央行宣布降息了吗",
    "AMD 的 new chip 怎么样",
    "三星新款手机值得买吗",
    "英特尔裁员最新消息",
    "本周中美经贸会谈有什么新消息",
    "特斯拉最新股价多少",
    "OpenAI 的 Sora 2 什么时候上线",
    "最近国际上发生了什么事",
    "比亚迪股票行情",
    "俄乌局势最新进展",
    "英伟达股价走势",
]

# ---------------------------------------------------------------------------
# (b) 负样本：设计要防的「单词上网」误触发，不应触发检索
# ---------------------------------------------------------------------------
NEGATIVE_SAMPLES = [
    "今天天气不错",
    "我最近在学量子力学",
    "帮我写个函数",
    "你怎么看昨天那场球的战术",
    "守岸人你喜欢我吗",
    "谢谢你今天的陪伴",
    "光合作用是怎么进行的",
    "天空为什么是蓝色的",
    "你能陪我聊聊天吗",
    "早上好呀",
    "帮我把这段话翻译成英文",
    "以守岸人的口吻写一段诗",
    "鸣潮里的椿是谁",
    "战双帕弥什的剧情讲了什么",
    "1加1等于几",
    "你好厉害呀",
    "帮我改改这段代码的格式",
    "量子纠缠的原理是什么",
    "今天心情不好",
    "推荐几本好看的科幻小说",
    "你怎么评价鸣潮的画质",
    "帮我规划一次成都三日游",
    "解释一下这段代码",
    "你最近怎么样",
    "明天会下雨吗",
]


@pytest.mark.parametrize("text", POSITIVE_SAMPLES)
def test_positive_external_topics_trigger(text: str) -> None:
    assert _triggers(text), f"应触发检索却被判不触发：{text}"


@pytest.mark.parametrize("text", NEGATIVE_SAMPLES)
def test_negative_casual_stays_off_web(text: str) -> None:
    assert not _triggers(text), f"不应触发检索却触发了：{text}"


# ---------------------------------------------------------------------------
# (c) 边界
# ---------------------------------------------------------------------------
def test_boundary_pure_chinese_evaluation_without_proper_name_off() -> None:
    # 纯中文、无域外专名/版本号的评价句：宁可不上网（防「手机/东西」泛词误触发）。
    assert not _triggers("这款手机好不好用")
    assert not _triggers("这个东西怎么样")


def test_boundary_version_number_form_without_known_brand() -> None:
    # 版本号形态（拉丁词 + x.y）本身即锚点。
    assert _triggers("Model 4.2 怎么样")
    assert _triggers("Foo 12.3 好用吗")


def test_boundary_case_mixed_triggers() -> None:
    assert _triggers("gpt-5 好不好用")  # 小写
    assert _triggers("ANTHROPIC 最新进展")  # 大写


def test_boundary_ai_token_not_matched_inside_english_word() -> None:
    # 「AI」不能被 email/said/explain 里的 ai 误命中。
    assert not _triggers("please explain this email in detail")


def test_boundary_mention_and_emoji_with_entity() -> None:
    assert _triggers("@守岸人 英伟达财报怎么看")  # 本地人称谓不吞掉域外现实话题
    assert _triggers("英伟达财报怎么看 🤔")


def test_boundary_long_sentence_still_triggers() -> None:
    long_text = (
        "我想了解一下最近半导体行业的情况，尤其是英伟达这种公司最新的财报和股价走势，"
        "结合 AI 大模型的需求端，国产替代的进展到底怎么样，你帮我梳理一下"
    )
    assert _triggers(long_text)


def test_boundary_empty_and_none_safe() -> None:
    assert not _triggers("")
    assert classify_question_intent("").intent is _qi.QuestionIntent.NEUTRAL


def test_explicit_no_web_still_wins_over_external_topic() -> None:
    # 「不要联网」显式约束永远优先：即便含域外专名也不判检索。
    assert not _triggers("英伟达最新财报，不用联网只用本地回答")


# ===========================================================================
# T4①（2026-09-28，S-POLICY）：本地域词表与检索意图词表**同源**
#
# 病根：库里躺着原神/星穹铁道/FGO 的整套语料，`DOMAIN_TERMS` 却只列了鸣潮/战双/
# 库洛/明日方舟 ⇒ 这些题既不判 LOCAL_KNOWLEDGE、也不走"本地优先、低置信才补网"，
# 被当域外实体直接推去联网。修法不是"再抄一份名单"（规则 10：抄一次过期一次），
# 而是把外部游戏段**从既有词表现取**，并用下面这把同源门锁死"缺谁必红"。
# ===========================================================================

from plugins.bot_unified_runtime.domains.core.search.search_intent import (
    ACG_DOMAIN_TERMS,
    ACG_TIER_STRONG,
)


def _registry_game_terms() -> tuple[str, ...]:
    return tuple(ACG_DOMAIN_TERMS["game"][ACG_TIER_STRONG])


def test_local_domain_terms_are_derived_not_hand_copied() -> None:
    """真身形态锁：DOMAIN_TERMS 必须是"自有设定 ∪ 词表现取"的产物，不是手抄元组。"""
    import ast

    tree = ast.parse(_MODULE_PATH.read_text(encoding="utf-8"))
    assigned: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            assigned[node.target.id] = node.value
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assigned[target.id] = node.value
    value = assigned.get("DOMAIN_TERMS")
    assert isinstance(value, ast.Call), (
        "DOMAIN_TERMS 又变回手写字面量了 ⇒ 词表加一域这里不会跟随（规则 10）"
    )
    assert "_SHOREKEEPER_DOMAIN_TERMS" in assigned, (
        "自有世界观锚点与外部游戏域必须分成两段登记，外部那段才准现取"
    )


def test_every_registry_game_domain_is_a_local_domain_term() -> None:
    """同源门（缺谁必红）：词表强专名档的每一域都必须能在本地域里命中。"""
    missing = [term for term in _registry_game_terms() if term not in _qi.DOMAIN_TERMS]
    assert missing == [], f"检索词表认这些是二游题、本地域词表却不认：{missing}"
    # 自有设定一段不许被现取覆盖掉（那是本 bot 的人格锚点，别处没有）
    for own in ("守岸人", "黑海岸", "漂泊者", "鸣潮"):
        assert own in _qi.DOMAIN_TERMS


def test_registry_growth_propagates_into_the_local_domain_predicate() -> None:
    """注毒/跟随自证：词表加一枚新游戏域 ⇒ 现取函数立刻带上它（这里绝不写死名单）。"""
    extra = "新游戏域甲"
    with pytest.MonkeyPatch.context() as monkeypatch:
        grown = dict(ACG_DOMAIN_TERMS)
        grown["game"] = dict(grown["game"])
        grown["game"][ACG_TIER_STRONG] = (*_registry_game_terms(), extra)
        monkeypatch.setattr(_qi, "ACG_DOMAIN_TERMS", grown)
        derived = _qi._external_game_domain_terms()
        assert extra in derived, "外部游戏段不是从词表现取 ⇒ 它另有第二份真身"
        # 反向注毒：把这段从 DOMAIN_TERMS 里摘掉，同源门必须能抓到（此处只验判据可用）
        trimmed = tuple(t for t in _qi.DOMAIN_TERMS if t != extra)
        assert extra not in trimmed
    assert extra not in _qi._external_game_domain_terms(), "还原失败 ⇒ 后续用例不可信"


@pytest.mark.parametrize(
    "text",
    [
        "原神里的纳西妲是谁",
        "介绍一下星穹铁道的流萤",
        "FGO 有哪些职阶",
        "绝区零的角色关系是怎样的",
    ],
)
def test_games_that_are_in_the_library_route_to_local_knowledge(text: str) -> None:
    """行为面：在库游戏域的问题先查本地库，低置信才补网（不再是"域外实体"直推联网）。"""
    decision = classify_question_intent(text)
    assert decision.intent is QuestionIntent.KNOWLEDGE_FIRST, (
        f"{text!r} 没判成本地知识优先（intent={decision.intent.value}, reason={decision.reason}）"
    )
    assert decision.category == "LOCAL_KNOWLEDGE"
    assert decision.allow_web_fallback is True, "本地优先不等于禁网：低置信仍要能补搜一次"
    assert _qi.classify_timely_domain(text) == _qi.TimelyDomain.ANIME_LORE.value


def test_timely_questions_about_in_library_games_still_reach_the_web() -> None:
    """扩面不许把时效题锁死在本地：卡池/版本这类问题仍判主搜索。"""
    assert _triggers("原神5.0卡池什么时候复刻")
    assert _triggers("鸣潮最新版本公告维护到几点")


def test_endminland_is_still_not_a_local_domain_term() -> None:
    """她明确裁定过的边界：「明日方舟·终末地」不因此扩面而被带进本地域。"""
    assert not any("终末地" in term for term in _qi.DOMAIN_TERMS)
