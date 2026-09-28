"""S-PATCH-WEBCFG-FIX / 缺口 E-2：时效现实域话题词组应接入 PRIMARY 主搜索。

审计病根（reports/WEBCFG-AUDIT.md E-2，台账 #120/#121 更正后口径）：
「英伟达新一代芯片」「央行降准落地」这类**没有问句标记、没有显式时间词**的科技/
时政/金融话题，在 intent-v3 里恒判 never——`classify_timely_domain` 的四张现实域
表过去只参与检索后的来源排序，从没接进 PRIMARY 判据。

本件用「路径直载 + 临时桩包」加载 question_intent（沿用 test_question_intent 的
先例，并进一步隔离 bot_unified_runtime.__init__ 热区并发写——判据只依赖
question_intent + stdlib-only 的 search_intent，不该被别的热文件带崩）。

两态预期（规则 50★：判据依赖未入库补丁 WEBCFG-E-2.patch.md，此处如实标注）：
* **HEAD 基线（5bb67b3）**：LOCK_A（timely_domain_signal 四句）与 ORDER_PIN
  （美联储最新利率 reason 应为 temporal_intent）为**红**——修复未入库，这是
  预期的注毒自证红腿；NEG_* 负样本腿为绿。
* **HEAD+补丁 / 当前盘面**：全绿。
（当前盘面已有同判据的未入库改动——审计更正：修复主体已由他席写盘未 commit，
本补丁件记录 HEAD→目标 全文，供主代理统一落盘。）

注毒自证（退化实现必须被抓红）：
* 不接 PRIMARY（维持现状）→ LOCK_A 红；
* 无脑全 PRIMARY → NEG_NO_WEB / NEG_OPINION / NEG_LORE 红；
* 去掉 opinion 否决守卫 → NEG_OPINION 红（「手机」命中科技表即上网）；
* 去掉本地域抢先守卫 → NEG_LORE 红（鸣潮抽卡建议被推去时政源）；
* 把 timely 支挪到 no_web 短路之前 → NEG_NO_WEB 红；
* 表序写反（timely 抢在 temporal 前）→ ORDER_PIN 红。
禁手写漂移计数：全部断言按符号语义取值，无任何「共 N 句」计数。
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_QI_PATH = (
    _REPO_ROOT
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "chat_reply"
    / "runtime"
    / "question_intent.py"
)
_SI_PATH = (
    _REPO_ROOT
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "core"
    / "search"
    / "search_intent.py"
)


def _load():
    """按文件路径直载 question_intent；临时桩掉包链并即时还原。

    桩包只在该件 exec 期间存在（target 树里 question_intent 会绝对导入
    search_intent），载完立刻还原 sys.modules——不给同进程其他测试留
    半成品包，避免跨测试污染。真实包若已在 sys.modules，则原样复用。
    """
    existing = sys.modules.get("webcfg_e2_qi_under_test")
    if existing is not None:
        return existing
    chain = [
        ("plugins", "plugins"),
        ("plugins.bot_unified_runtime", "plugins/bot_unified_runtime"),
        ("plugins.bot_unified_runtime.domains", "plugins/bot_unified_runtime/domains"),
        (
            "plugins.bot_unified_runtime.domains.core",
            "plugins/bot_unified_runtime/domains/core",
        ),
        (
            "plugins.bot_unified_runtime.domains.core.search",
            "plugins/bot_unified_runtime/domains/core/search",
        ),
        (
            "plugins.bot_unified_runtime.domains.core.search.search_intent",
            None,
        ),
    ]
    saved: dict[str, types.ModuleType | None] = {}
    try:
        for name, rel in chain:
            saved[name] = sys.modules.get(name)
            if saved[name] is not None:
                continue
            if rel is None:
                spec = importlib.util.spec_from_file_location(name, _SI_PATH)
                assert spec is not None and spec.loader is not None
                module = importlib.util.module_from_spec(spec)
                sys.modules[name] = module
                spec.loader.exec_module(module)
            else:
                stub = types.ModuleType(name)
                stub.__path__ = [str(_REPO_ROOT / rel)]
                sys.modules[name] = stub
        spec = importlib.util.spec_from_file_location(
            "webcfg_e2_qi_under_test", _QI_PATH
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["webcfg_e2_qi_under_test"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        for name in reversed([n for n, _ in chain]):
            original = saved[name]
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


_qi = _load()
classify_question_intent = _qi.classify_question_intent
classify_timely_domain = _qi.classify_timely_domain
decide_web_search = _qi.decide_web_search
WebDecision = _qi.WebDecision
TimelyDomain = _qi.TimelyDomain


def _verdict(text: str):
    decision = classify_question_intent(text)
    needs_web = decide_web_search(
        web_enabled=True,
        decision=decision.decision,
        allow_web_fallback=decision.allow_web_fallback,
        answerable=False,
        confidence=0.0,
        chunk_count=0,
        knowledge_threshold=0.6,
        confidence_floor=0.2,
    )
    return decision, needs_web


# ---------------------------------------------------------------------------
# LOCK_A：无问句标记/无时间词的现实域话题 → PRIMARY + timely_domain_signal
# （HEAD 基线红=预期注毒自证腿；补丁后绿）
# ---------------------------------------------------------------------------
TIMELY_LOCK_SAMPLES = [
    "英伟达新一代芯片",   # 科技
    "央行降准落地",       # 金融
    "国务院任免",         # 时政
    "LPR又降了吗",        # 纯时效是非句（审计点名「不再恒判 never」）
]


@pytest.mark.parametrize("text", TIMELY_LOCK_SAMPLES)
def test_timely_topic_phrase_becomes_primary(text: str):
    decision, needs_web = _verdict(text)
    assert decision.decision is WebDecision.PRIMARY, (
        f"{text!r} 仍被判 {decision.decision.value}（reason={decision.reason}）："
        "现实域表没接进 PRIMARY（缺口 E-2 未修）"
    )
    assert decision.reason == "timely_domain_signal"
    assert needs_web is True


# ---------------------------------------------------------------------------
# ORDER_PIN：判序保真——既命中时间词又命中现实域时，temporal 仍排在前
# （HEAD 基线红：美联储最新利率 reason=external_entity_topic；补丁后绿）
# ---------------------------------------------------------------------------
def test_temporal_reason_keeps_precedence_over_timely_domain():
    decision, needs_web = _verdict("美联储最新利率")
    assert decision.decision is WebDecision.PRIMARY
    assert decision.reason == "temporal_intent", (
        f"reason={decision.reason!r}：timely 支抢在 temporal 之前会改写既有归因口径"
    )
    assert needs_web is True


def test_news_headlines_stay_primary_via_temporal():
    # 「新闻头条」两态均 PRIMARY/temporal_intent：本腿锁的是「修复不改变既有正解」
    decision, needs_web = _verdict("新闻头条")
    assert decision.decision is WebDecision.PRIMARY
    assert decision.reason == "temporal_intent"
    assert needs_web is True


# ---------------------------------------------------------------------------
# NEG_*：负样本腿（两态皆绿；退化修法一碰就红）
# ---------------------------------------------------------------------------
def test_explicit_no_web_still_wins_over_timely_domain():
    decision, needs_web = _verdict("别联网，英伟达新一代芯片")
    assert decision.reason == "explicit_no_web"
    assert decision.decision is WebDecision.NEVER
    assert needs_web is False


@pytest.mark.parametrize("text", ["这款手机好不好用", "这款手机怎么样"])
def test_opinion_questions_not_dragged_online_by_domain_tables(text: str):
    decision, needs_web = _verdict(text)
    assert decision.reason != "timely_domain_signal"
    assert decision.decision is not WebDecision.PRIMARY
    assert needs_web is False


def test_local_anime_topic_is_not_treated_as_realworld_timely():
    # 去掉 in_local_domain 抢先守卫的修法会把鸣潮抽卡题标成 timely_domain_signal
    text = "鸣潮最新版本卡池抽卡建议"
    decision, _ = _verdict(text)
    assert decision.reason != "timely_domain_signal"
    assert (
        classify_timely_domain(text, in_local_domain=True)
        == TimelyDomain.ANIME_LORE.value
    )
