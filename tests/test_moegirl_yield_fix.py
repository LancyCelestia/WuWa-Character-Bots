"""moegirl_question 让路修复回归（invest-moegirl-hijack §四 三件套 A+B+C）。

劫持机制：「帮我查一下杭州天气」被 moegirl_question(44) 的剥前缀判定抢路，
weather 基层(41) 前缀锚定接不到、natural_command(45) 被 44 跳过。

三件套：
- A（主修）：MOEGIRL_QUESTION 优先级 44→46，排到 NATURAL_COMMAND(45) 之后；
  base_router 规则表/决策标签/InterfaceEntry 展示口径 + __init__ matcher 接线四处同步。
- B：``normalize_entity_question`` 域词尾守卫——剥词后剩串以 天气/天氣/预报/預報
  收尾、或「天气/天氣+空格」开头（「天气 杭州」形态）不判为萌百实体；
  「天气之子」类词条无空格、不以域词收尾，零误伤。
- C：``_CITY_FORBIDDEN_FRAGMENTS`` 补 是谁/是什么/是啥——防 A 生效后 NL 层
  把「帮我查一下天气之子是谁」吞成 city「之子是谁」反噬。

样例口径（调查报告 §二 30 样例表）：HIJACK 行 15 条 + 表格外语族补样 1 条
（帮我看看维基 鸣潮）= 16 条被抢族；合法萌百对照 7 条；天气基层对照 4 条。
繁體/无城市 4 条修复后按报告「遗留①」口径不再被萌百抢（落 chat/ignore，
NL 层尚无繁體天气变体，属已知登记残余）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.capabilities.moegirl import normalize_entity_question
from plugins.bot_unified_runtime.runtime.base_router import (
    ROUTE_RULES,
    RouteKind,
    build_interface_manifest,
    classify_message_route,
    clear_route_decision_cache,
)
from plugins.bot_unified_runtime.runtime.natural_language import (
    _CITY_FORBIDDEN_FRAGMENTS,
    detect_natural_command,
)

ROOT = Path(__file__).resolve().parents[1]
INIT_PY = ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"


class _DefaultConfig:
    """全部路由开关走 base_router 的 getattr 默认值（与探针同口径）。"""


_CONFIG = _DefaultConfig()


@pytest.fixture(autouse=True)
def _fresh_route_cache():
    clear_route_decision_cache()
    yield
    clear_route_decision_cache()


# ── 样例集 ────────────────────────────────────────────────────────────────

# 报告 §二 HIJACK 行：简体天气族（9）+ wiki 族（2，表格内），
# 修复后应落 natural_command 且归一化正确（weather/wiki）。
HIJACK_FAMILY_TO_NL: list[tuple[str, str, str]] = [
    ("帮我查一下杭州天气", "bot.weather", "天气 杭州"),
    ("帮我查天气 杭州", "bot.weather", "天气 杭州"),
    ("帮我查杭州天气", "bot.weather", "天气 杭州"),
    ("帮我查一下北京天气怎么样", "bot.weather", "天气 北京"),
    ("帮我看看上海天气", "bot.weather", "天气 上海"),
    ("查一下广州天气", "bot.weather", "天气 广州"),
    ("帮我查一下东京天气", "bot.weather", "天气 东京"),
    ("帮我查一下武汉天气", "bot.weather", "天气 武汉"),
    ("帮我查查杭州天气", "bot.weather", "天气 杭州"),
    ("帮我查维基 鸣潮", "bot.wiki", "wiki 鸣潮"),
    ("查一下维基 鸣潮", "bot.wiki", "wiki 鸣潮"),
    # 报告「16/16」口径的第 16 条：同族「帮我看看 + 维基」（表格外语族补样）。
    ("帮我看看维基 鸣潮", "bot.wiki", "wiki 鸣潮"),
]

# 报告 §二 HIJACK 行中的繁體/无城市形（4）：NL 层无繁體天气变体、无城市形
# 不可归一化——修复后按「遗留①」落 chat/ignore，但**绝不再落 moegirl_question**。
HIJACK_FAMILY_RESIDUAL: list[str] = [
    "幫我查一下台北天氣",
    "幫我查天氣 台北",
    "帮我查天气",
    "帮我查一下天气",
]

# 报告 §二 合法萌百问句对照（7/7）：修复后必须照旧落 moegirl_question。
LEGAL_MOEGIRL: list[str] = [
    "初音未来是谁",
    "什么是崩坏三",
    "帮我查一下初音未来是谁",
    "openai是什么",
    "英伟达是谁",
    "守岸人是谁",
    "帮我查一下天气之子是谁",
]

# 报告 §二 天气基层对照（4 形，含繁體）：41 层判定不受三件套影响。
WEATHER_BASELINE: list[str] = [
    "天气 杭州",
    "查天气 杭州",
    "天气预报 台北",
    "天氣預報 台北",
]


# ── A：优先级让路（规则表/决策标签/matcher 接线三处同步） ─────────────────


def test_moegirl_question_priority_moved_behind_natural() -> None:
    rules = {rule.kind: rule for rule in ROUTE_RULES}
    assert rules[RouteKind.WEATHER].priority == 41
    assert rules[RouteKind.NATURAL_COMMAND].priority == 45
    assert rules[RouteKind.MOEGIRL_QUESTION].priority == 46
    # 同 46 与 CONTENT：moegirl 拒 URL、content 要 URL，天然不相交；
    # 声明序 moegirl 在 content 之前，同值先到先得不受影响。
    assert rules[RouteKind.CONTENT].priority == 46


def test_route_order_weather_before_natural_before_moegirl_question() -> None:
    order = [rule.kind for rule in sorted(ROUTE_RULES, key=lambda r: r.priority)]
    assert order.index(RouteKind.WEATHER) < order.index(RouteKind.NATURAL_COMMAND)
    assert order.index(RouteKind.NATURAL_COMMAND) < order.index(
        RouteKind.MOEGIRL_QUESTION
    )


def test_moegirl_question_decision_label_synced_with_rule() -> None:
    decision = classify_message_route("初音未来是谁", config=_CONFIG, alias_resolver=None)
    assert decision.kind is RouteKind.MOEGIRL_QUESTION
    assert decision.priority == 46


def test_nonebot_matcher_priority_synced() -> None:
    """NoneBot matcher 接线必须与 classify 次序同步（否则群门禁口径漂移）。"""
    match = re.search(
        r"moegirl_question = on_message\(\s*rule=_is_moegirl_question_event, "
        r"priority=(\d+)",
        INIT_PY.read_text(encoding="utf-8"),
    )
    assert match, "__init__.py 里找不到 moegirl_question 的 on_message 接线"
    assert match.group(1) == "46"


def test_interface_manifest_moegirl_priority_synced() -> None:
    entries = {
        entry.interface_id: entry for entry in build_interface_manifest()
    }
    assert entries["capability.moegirl"].priority == 46


# ── 16 条被抢族：全数转绿 ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text, capability_id, normalized", HIJACK_FAMILY_TO_NL
)
def test_hijacked_family_normalized_by_natural_layer(
    text: str, capability_id: str, normalized: str
) -> None:
    decision = classify_message_route(text, config=_CONFIG, alias_resolver=None)
    assert decision.kind is RouteKind.NATURAL_COMMAND
    assert decision.target_capability_id == capability_id
    assert decision.normalized_text == normalized


@pytest.mark.parametrize("text", HIJACK_FAMILY_RESIDUAL)
def test_hijacked_family_no_city_or_traditional_never_moegirl(text: str) -> None:
    decision = classify_message_route(text, config=_CONFIG, alias_resolver=None)
    assert decision.kind is not RouteKind.MOEGIRL_QUESTION


# ── 7 条合法萌百对照：照旧 ────────────────────────────────────────────────


@pytest.mark.parametrize("text", LEGAL_MOEGIRL)
def test_legal_moegirl_questions_unchanged(text: str) -> None:
    decision = classify_message_route(text, config=_CONFIG, alias_resolver=None)
    assert decision.kind is RouteKind.MOEGIRL_QUESTION


# ── 天气基层对照：41 层不受影响 ───────────────────────────────────────────


@pytest.mark.parametrize("text", WEATHER_BASELINE)
def test_weather_base_layer_untouched(text: str) -> None:
    decision = classify_message_route(text, config=_CONFIG, alias_resolver=None)
    assert decision.kind is RouteKind.WEATHER


# ── B：normalize_entity_question 域词尾守卫 ───────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "帮我查一下杭州天气",
        "帮我查天气",
        "帮我查一下天气",
        "帮我查一下天气预报",
        "幫我查一下台北天氣",
        "幫我查天氣 台北",
    ],
)
def test_domain_guard_rejects_weather_shaped_entities(text: str) -> None:
    assert normalize_entity_question(text) is None


@pytest.mark.parametrize(
    "text, expected",
    [
        # 「天气之子」类词条零误伤：不以域词收尾、无「天气+空格」形态。
        ("帮我查一下天气之子是谁", "天气之子"),
        ("帮我查一下天气之子", "天气之子"),
        ("介绍一下天气之子", "天气之子"),
        ("天气之子是谁", "天气之子"),
        ("默娘是谁", "默娘"),
        ("什么是崩坏三", "崩坏三"),
        ("帮我查一下初音未来是谁", "初音未来"),
    ],
)
def test_domain_guard_keeps_legal_entities(text: str, expected: str) -> None:
    assert normalize_entity_question(text) == expected


# ── C：NL 城市黑名单防反噬 ────────────────────────────────────────────────


def test_city_forbidden_fragments_added() -> None:
    for fragment in ("是谁", "是什么", "是啥"):
        assert fragment in _CITY_FORBIDDEN_FRAGMENTS


@pytest.mark.parametrize(
    "text",
    [
        "帮我查一下天气之子是谁",
        "帮我查一下天气之子是什么",
        "帮我查一下天气之子是啥",
    ],
)
def test_natural_layer_does_not_swallow_question_suffix(text: str) -> None:
    """「天气之子是谁」类问句不得被 NL 层吞成 city「之子是谁」→ weather。"""
    assert detect_natural_command(text, _CONFIG) is None


@pytest.mark.parametrize(
    "text, capability_id, normalized",
    [
        ("帮我查一下杭州天气", "bot.weather", "天气 杭州"),
        ("帮我查维基 鸣潮", "bot.wiki", "wiki 鸣潮"),
    ],
)
def test_natural_layer_positive_controls(
    text: str, capability_id: str, normalized: str
) -> None:
    resolution = detect_natural_command(text, _CONFIG)
    assert resolution is not None
    assert resolution.capability_id == capability_id
    assert resolution.normalized_text == normalized
