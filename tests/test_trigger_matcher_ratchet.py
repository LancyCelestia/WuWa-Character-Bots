"""IGEN2-③：触发词「规模下降棘轮」+「路由可达 ⇄ matcher 实际注册」等价门（全离线）。

两件（对既有门的补强，不改 ``tests/test_trigger_bidirectional_gate.py``、不动其台账）：

A. 规模下降棘轮（SA2-05）——既有双向门断言「缺口集合 == 冻结台账（106/113）」，
   只拦「集合变化」不拦「规模」：绿灯下实载 219 条在册缺口，易被误读为「已归零」。
   本席**不新建台账、不改台账数字、不删存量项**，而是把现台账（``LEDGER_ROUTE_TO_HELP``
   / ``LEDGER_HELP_TO_ROUTE``）当**只降不升的规模上界**：
   - 新增缺口项（当前集合 − 台账）→ 红（存量之外一律禁止）；
   - 规模上界 ``len(current) <= len(ledger)``（台账外多一条即越界）；
   - 存量项被修复而消失 → **放行**（单调递减是好事，不像既有等值门那样逼清账才绿）。
   等价于把「冻结台账」重述成一条方向正确的棘轮，与既有门并存互补。

B. 路由可达 ⇄ matcher 实际注册（SYNC1 缺口7 / SA2-10 建议）——此前**零门**的等价关系：
   ``DEFAULT_VERB_MAP``（昵称动词 → capability_id）声明某能力可被「/岸宝X」/「/bot X」唤起，
   但该 capability 必须真有落点：或注册为 RouteRule 能力（``ROUTE_CAPABILITY_DECLARATIONS``
   里 ``has_rule=True``），或登记于 ``CONTROLLED_INTERNAL_CAPABILITIES``（/bot 子命令与入站/
   通知链显式使用集）。两者皆无 = **悬空动词**（在册宣称、执行即坠 /bot help 兜底）。
   复核实测现仅 1 条：``bot.decision``（动词 决策/decision，分发链无分支、
   ``build_decision_query_result`` 零消费者——SA2-02/10、SA8-09 实锤）。
   本条同样做**规模下降棘轮**：现有悬空登记为基线（存量只登记不消），新增悬空动词即红、
   接线修好后悬空减少放行。

纪律：全离线；仅静态读声明表 + 复用 ``scripts`` 提取器，不 import NoneBot 装配、不触网、
不发消息、不连 Runtime；``build_inventory`` 与既有门同源（进程内 lru_cache，不重跑）。
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from plugins.bot_unified_runtime.domains.chat_reply.runtime.aliases import (
    DEFAULT_VERB_MAP,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.capability_registry import (
    CONTROLLED_INTERNAL_CAPABILITIES,
    ROUTE_CAPABILITY_DECLARATIONS,
)
from scripts.extract_trigger_words import (
    build_help_trigger_side,
    build_inventory,
    build_route_trigger_side,
    flat_verb_map,
    gate_help_to_route,
    gate_route_to_help,
    live_detectors_by_capability,
)
from tests.test_trigger_bidirectional_gate import (
    LEDGER_HELP_TO_ROUTE,
    LEDGER_ROUTE_TO_HELP,
)

# 既有台账 = 只降不升的规模上界（本席只引用、不复制、不删改）。
ROUTE_TO_HELP_CEILING = LEDGER_ROUTE_TO_HELP
HELP_TO_ROUTE_CEILING = LEDGER_HELP_TO_ROUTE
# B 类：现状悬空动词能力基线（存量登记，禁增长；接线后可单调递减，绝不删基线凑绿）。
DANGLING_VERB_CAPABILITIES_BASELINE: frozenset[str] = frozenset({"bot.decision"})

INV = build_inventory()


def _ratchet_report(current: set, ceiling: frozenset) -> tuple[list, int]:
    """棘轮判定：返回 (台账/基线外新增项, 规模超出量)。两者皆空/非正即为绿。"""
    new_items = sorted(current - set(ceiling))
    count_delta = len(current) - len(ceiling)
    return new_items, count_delta


def _dangling_verb_capabilities(verb_capabilities: set[str]) -> set[str]:
    """可达但无落点：verb 映射能力 − (RouteRule 注册能力 ∪ 受控内部能力)。"""
    route_rule_caps = {decl.capability_id for decl in ROUTE_CAPABILITY_DECLARATIONS if decl.has_rule}
    landed = route_rule_caps | set(CONTROLLED_INTERNAL_CAPABILITIES)
    return verb_capabilities - landed


# ---------------------------------------------------------------------------
# 基线快照：确认现状规模与既有台账/基线一致（防提取器/依赖被静默改动，非永真）。
# ---------------------------------------------------------------------------


def test_truth_sources_nonempty_and_baseline_matches_ledger() -> None:
    route_side = build_route_trigger_side(INV)
    help_side = build_help_trigger_side(INV["help_topics"])
    gaps = set(gate_route_to_help(route_side, help_side))
    violations = {
        (item["topic"], item["word"])
        for item in gate_help_to_route(INV["help_topics"], flat_verb_map(INV), live_detectors_by_capability(INV))
    }
    assert gaps == set(ROUTE_TO_HELP_CEILING), "路由→帮助规模基线与既有台账漂移（本席不得改台账，须核对依赖）"
    assert violations == set(HELP_TO_ROUTE_CEILING), "帮助→路由规模基线与既有台账漂移（本席不得改台账，须核对依赖）"
    verb_caps = set(DEFAULT_VERB_MAP.values())
    assert _dangling_verb_capabilities(verb_caps) == set(DANGLING_VERB_CAPABILITIES_BASELINE), (
        "悬空动词基线漂移：接线修好应递减（放行）、新增须显式登记，不得静默扩大"
    )


# ---------------------------------------------------------------------------
# A. 规模下降棘轮：路由 ↔ 帮助 词级缺口（新增即红、存量允许单调递减）
# ---------------------------------------------------------------------------


def test_route_to_help_gap_decreasing_ratchet() -> None:
    gaps = set(gate_route_to_help(build_route_trigger_side(INV), build_help_trigger_side(INV["help_topics"])))
    new_items, count_delta = _ratchet_report(gaps, ROUTE_TO_HELP_CEILING)
    assert not new_items, f"新增「路由有、help 无」缺口（台账外，禁止）：{new_items[:15]}"
    assert count_delta <= 0, f"路由→帮助缺口规模越界（{len(gaps)} > 上界 {len(ROUTE_TO_HELP_CEILING)}）"


def test_help_to_route_gap_decreasing_ratchet() -> None:
    violations = {
        (item["topic"], item["word"])
        for item in gate_help_to_route(INV["help_topics"], flat_verb_map(INV), live_detectors_by_capability(INV))
    }
    new_items, count_delta = _ratchet_report(violations, HELP_TO_ROUTE_CEILING)
    assert not new_items, f"新增「help 有、路由坠兜底」缺口（台账外，禁止）：{new_items[:15]}"
    assert count_delta <= 0, f"帮助→路由违规规模越界（{len(violations)} > 上界 {len(HELP_TO_ROUTE_CEILING)}）"


def test_ratchet_allows_monotonic_decrease() -> None:
    """棘轮语义自证：存量项减少（修好一条）→ 绿；台账不动、只降不升。"""
    shrink = set(ROUTE_TO_HELP_CEILING) - {("bot.weather", "天气预报")}
    new_items, count_delta = _ratchet_report(shrink, ROUTE_TO_HELP_CEILING)
    assert not new_items and count_delta < 0, "棘轮应放行存量递减（修复不被惩罚）"


# ---------------------------------------------------------------------------
# B. 路由可达 ⇄ matcher 实际注册（此前无门的等价关系，做规模下降棘轮）
# ---------------------------------------------------------------------------


def test_route_reachable_capability_has_registered_landing() -> None:
    dangling = _dangling_verb_capabilities(set(DEFAULT_VERB_MAP.values()))
    new_items, count_delta = _ratchet_report(dangling, DANGLING_VERB_CAPABILITIES_BASELINE)
    assert not new_items, (
        "出现悬空动词能力（DEFAULT_VERB_MAP 可达，但既非 RouteRule 注册能力、"
        f"亦未登记 CONTROLLED_INTERNAL_CAPABILITIES，执行必坠 /bot help 兜底）：{new_items}"
    )
    assert count_delta <= 0, f"悬空动词能力规模越界（{len(dangling)} > 基线 {len(DANGLING_VERB_CAPABILITIES_BASELINE)}）"


def test_decision_is_the_recorded_dangling_verb() -> None:
    """实证锁：bot.decision 确在悬空集、确为在册基线（决策/decision 无分发落点）。"""
    dangling = _dangling_verb_capabilities(set(DEFAULT_VERB_MAP.values()))
    assert "bot.decision" in dangling, "bot.decision 悬空态改变：若已接线请从基线清账（递减放行）、勿静默"
    assert any(verb_map_cap == "bot.decision" for verb_map_cap in DEFAULT_VERB_MAP.values())


# ---------------------------------------------------------------------------
# 可红性（变异测试）：内存内构造新增 → 棘轮必须红（绝不写盘）。
# ---------------------------------------------------------------------------


def test_mutation_new_wordgap_trips_ratchet() -> None:
    fake_gap = ("bot.igen2", "zombie-word")
    new_items, count_delta = _ratchet_report(
        set(ROUTE_TO_HELP_CEILING) | {fake_gap}, ROUTE_TO_HELP_CEILING
    )
    assert fake_gap in new_items, "棘轮失效：新增缺口未浮出（永真摆设）"
    assert count_delta == 1, "棘轮失效：规模越界未被量化捕获"


def test_mutation_new_dangling_verb_trips_gate() -> None:
    fake_cap = "bot.igen2_orphan"
    dangling = _dangling_verb_capabilities(set(DEFAULT_VERB_MAP.values()) | {fake_cap})
    new_items, _count_delta = _ratchet_report(dangling, DANGLING_VERB_CAPABILITIES_BASELINE)
    assert fake_cap in new_items, "等价门失效：新增悬空动词能力未被捕获（永真摆设）"


def test_mutation_wired_decision_shrinks_not_breaks() -> None:
    """反向变异：若把 bot.decision 接上落点，悬空集应清空且仍为绿（递减放行，非等值冻结）。"""
    landed_plus_decision = _dangling_verb_capabilities(
        set(DEFAULT_VERB_MAP.values()) - {"bot.decision"}
    )
    new_items, count_delta = _ratchet_report(
        landed_plus_decision, DANGLING_VERB_CAPABILITIES_BASELINE
    )
    assert not new_items and count_delta <= 0, "修好悬空后棘轮应仍绿（存量允许单调递减）"

