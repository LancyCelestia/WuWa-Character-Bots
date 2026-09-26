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
