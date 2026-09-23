"""S13 · 联网「该不该搜」行为判定的离线回归锁。

背景（缺陷 S13）：把一堆观测开关（BOT_WEB_INTENT_TELEMETRY_ENABLED /
BOT_WEB_DECISION_*）当成"联网开关"，真正左右行为的是
``knowledge_confidence`` 与阈值——而置信度是「有知识块就恒定 0.8」的词面近似，
阈值又偏高，导致绝大多数本地世界观问题被误判成「知识库够用、不用搜」。

本文件锁三件事（全离线、零网络、零副作用）：
  1. ``knowledge_confidence_from_evidence`` 是真实信号：偶然命中≠能答（不再虚高），
     主题被充分覆盖才算能答，且可复现。
  2. ``decide_web_search`` 是行为开关：总闸关=永不搜；PRIMARY 必搜；
     FALLBACK 按阈值/硬底线补搜；闲聊/创作/自带内容/explicit_no_web 永不被拖上网。
  3. 端到端（分类器 + 证据 + 决策）：
     (a) 「该搜却没搜」——本地知识近乎空白时必须搜；
     (b) 「本地知识够用不搜」——主题被充分覆盖时不搜。
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
    existing = sys.modules.get("question_intent_s13")
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location("question_intent_s13", _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["question_intent_s13"] = module
    spec.loader.exec_module(module)
    return module


_qi = _load()
classify_question_intent = _qi.classify_question_intent
knowledge_confidence_from_evidence = _qi.knowledge_confidence_from_evidence
decide_web_search = _qi.decide_web_search
QuestionIntent = _qi.QuestionIntent
WebDecision = _qi.WebDecision

DEFAULT_THRESHOLD = 0.60
DEFAULT_FLOOR = 0.20


# ---------------------------------------------------------------------------
# 1) 置信度是真实信号，而非恒定 0.8
# ---------------------------------------------------------------------------

def test_no_evidence_is_zero_confidence() -> None:
    assert knowledge_confidence_from_evidence("守岸人是谁", []) == 0.0
    assert knowledge_confidence_from_evidence("", ["随便一段文本"]) == 0.0


def test_incidental_overlap_no_longer_reads_as_answerable() -> None:
    """旧实现里"有块就 0.8"，一条偶然命中即可压制搜索；现在弱命中置信度低。"""
    weak = knowledge_confidence_from_evidence(
        "守岸人的泰缇斯系统第三实例设定是什么",
        ["今天天气不错，我们一起去海边散步吧，守岸提到了潮汐。"],
    )
    assert weak < DEFAULT_THRESHOLD, (
        f"仅一次偶然词面命中却被判成'可答'（{weak}），正是 S13 的虚高缺陷"
    )


def test_strong_topical_coverage_reads_as_answerable() -> None:
    confident = knowledge_confidence_from_evidence(
        "守岸人 声骸 共鸣者",
        ["守岸人是管理声骸与共鸣者数据的泰缇斯系统第二实例。"],
    )
    assert confident >= DEFAULT_THRESHOLD, (
        f"主题被充分覆盖却仍判低置信度（{confident}），会把本地够用的问题也拖上网"
    )


def test_multi_chunk_corroboration_lifts_confidence() -> None:
    single = knowledge_confidence_from_evidence(
        "维里奈 卡卡罗 露帕", ["维里奈是调律大厅的共鸣者。"]
    )
    many = knowledge_confidence_from_evidence(
        "维里奈 卡卡罗 露帕",
        ["维里奈是调律大厅的共鸣者。", "卡卡罗与露帕同为可操作角色。"],
    )
    assert many > single, "多块佐证应提升置信度"


def test_confidence_is_deterministic_and_bounded() -> None:
    query = "弗洛洛 黑潮 残星会 是什么"
    evidence = ["弗洛洛隶属残星会，与黑潮事件相关。", "残星会是鸣潮中的组织。"]
    first = knowledge_confidence_from_evidence(query, evidence)
    second = knowledge_confidence_from_evidence(query, evidence)
    assert first == second, "同一输入必须逐次可复现（离线可复算）"
    assert 0.0 <= first <= 1.0


# ---------------------------------------------------------------------------
# 2) decide_web_search 是行为开关
# ---------------------------------------------------------------------------

def test_master_switch_off_never_searches_even_with_no_knowledge() -> None:
    # 联网总闸关闭时，无论置信度多低都不搜（证明总闸是行为、不是观测）。
    assert decide_web_search(
        web_enabled=False,
        decision=WebDecision.FALLBACK,
        allow_web_fallback=True,
        answerable=False,
        confidence=0.0,
        chunk_count=0,
        knowledge_threshold=DEFAULT_THRESHOLD,
        confidence_floor=DEFAULT_FLOOR,
    ) is False


def test_primary_always_searches() -> None:
    assert decide_web_search(
        web_enabled=True,
        decision=WebDecision.PRIMARY,
        allow_web_fallback=False,
        answerable=True,
        confidence=0.99,
        chunk_count=5,
        knowledge_threshold=DEFAULT_THRESHOLD,
        confidence_floor=DEFAULT_FLOOR,
    ) is True


def test_fallback_with_confident_knowledge_does_not_search() -> None:
    assert decide_web_search(
        web_enabled=True,
        decision=WebDecision.FALLBACK,
        allow_web_fallback=True,
        answerable=True,
        confidence=0.90,
        chunk_count=2,
        knowledge_threshold=DEFAULT_THRESHOLD,
        confidence_floor=DEFAULT_FLOOR,
    ) is False


def test_fallback_below_threshold_searches() -> None:
    assert decide_web_search(
        web_enabled=True,
        decision=WebDecision.FALLBACK,
        allow_web_fallback=True,
        answerable=True,  # 即使"有块"，只要置信度不足仍要补搜（S13 修正点）
        confidence=0.30,
        chunk_count=1,
        knowledge_threshold=DEFAULT_THRESHOLD,
        confidence_floor=DEFAULT_FLOOR,
    ) is True


def test_confidence_floor_is_independent_hard_safety_valve() -> None:
    """阈值被影子期调低到 0.0 时，硬底线仍兜住近乎空白的本地知识。"""
    assert decide_web_search(
        web_enabled=True,
        decision=WebDecision.FALLBACK,
        allow_web_fallback=True,
        answerable=True,
        confidence=0.05,
        chunk_count=1,
        knowledge_threshold=0.0,  # 有人把阈值调到最低
        confidence_floor=DEFAULT_FLOOR,
    ) is True, "低于硬底线却因阈值被调低而不搜 = S13 的误判复发"


@pytest.mark.parametrize(
    "reason_query",
    [
        "你好呀",  # 短寒暄
        "陪我聊聊天",  # 情绪陪伴
        "帮我总结一下这段文字",  # 用户自带内容
        "不要联网，只用本地回答 守岸人是谁",  # 显式禁止联网
        "以守岸人身份写一首诗",  # 创作角色扮演
    ],
)
def test_never_categories_are_never_force_searched(reason_query: str) -> None:
    """安全红线类别：置信度为 0 也绝不因安全阀被拖上网（allow_web_fallback=False）。"""
    decision = classify_question_intent(reason_query)
    assert decision.decision is WebDecision.NEVER, reason_query
    assert decision.allow_web_fallback is False, reason_query
    assert decide_web_search(
        web_enabled=True,
        decision=decision.decision,
        allow_web_fallback=decision.allow_web_fallback,
        answerable=False,
        confidence=0.0,
        chunk_count=0,
        knowledge_threshold=DEFAULT_THRESHOLD,
        confidence_floor=DEFAULT_FLOOR,
    ) is False


# ---------------------------------------------------------------------------
# 3) 端到端：分类器 + 真实证据 + 决策（两条指定方向）
# ---------------------------------------------------------------------------

def test_e2e_should_search_but_did_not_direction() -> None:
    """(a) 该搜却没搜：本地世界观问题、知识库里几乎没有相关内容 → 必须搜。"""
    query = "守岸人 泰缇斯系统 第三实例 的 设定 是什么"
    decision = classify_question_intent(query)
    # 命中本地域词（守岸人/泰缇斯）走 FALLBACK，可回退联网。
    assert decision.decision is WebDecision.FALLBACK, (decision.reason, decision.category)
    weak_evidence = ["守岸人静静地望着海面。"]  # 只有偶然命中，主题词几乎不覆盖
    confidence = knowledge_confidence_from_evidence(query, weak_evidence)
    do_web = decide_web_search(
        web_enabled=True,
        decision=decision.decision,
        allow_web_fallback=decision.allow_web_fallback,
        answerable=bool(weak_evidence),
        confidence=confidence,
        chunk_count=len(weak_evidence),
        knowledge_threshold=DEFAULT_THRESHOLD,
        confidence_floor=DEFAULT_FLOOR,
    )
    assert do_web is True, "本地知识近乎空白却判'不用搜'，正是 S13 缺陷"


def test_e2e_local_knowledge_is_enough_direction() -> None:
    """(b) 本地知识够用不搜：主题词被知识库充分覆盖 → 不搜。"""
    query = "守岸人 声骸 共鸣者 是什么"
    decision = classify_question_intent(query)
    assert decision.decision is WebDecision.FALLBACK, (decision.reason, decision.category)
    good_evidence = [
        "守岸人负责保管与解析声骸，并引导共鸣者完成调律。"
    ]
    confidence = knowledge_confidence_from_evidence(query, good_evidence)
    do_web = decide_web_search(
        web_enabled=True,
        decision=decision.decision,
        allow_web_fallback=decision.allow_web_fallback,
        answerable=bool(good_evidence),
        confidence=confidence,
        chunk_count=len(good_evidence),
        knowledge_threshold=DEFAULT_THRESHOLD,
        confidence_floor=DEFAULT_FLOOR,
    )
    assert do_web is False, "本地知识已充分覆盖主题仍去搜 = 过度联网"
