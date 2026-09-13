"""路由判定序语义回归（T-Spec T2，TDD，全离线）：priority 数值即真实判定序。

修前实证：RouteRule 清单书写序中 STOCKS(42) 排在 EAT/AFFINITY 等 41 档之前，
而判定循环按列表序遍历——「让路档」42 反而抢占 41 档。「怎么做股票」同时
命中 is_recipe_command（eat 41）与 is_stocks_command（stocks 42），修前被
STOCKS 抢走（列表序），修后归 EAT（priority 序）。

锁定三件事：
1. 判定循环按 (priority, 原清单序) 稳定排序后遍历：低数值优先（合成规则
   直接证明），同 priority 保持书写序先到先得；
2. 真实双命中样例（stocks 42 vs eat 41）：41 档胜；
3. stocks 真命令（英伟达股价等）无 41 档竞争者，照旧归 STOCKS；
   清单书写顺序不被重排（最小改动：只动遍历处的排序）。
"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.capabilities.eat import is_recipe_command
from plugins.bot_unified_runtime.capabilities.stocks import is_stocks_command
from plugins.bot_unified_runtime.runtime import base_router
from plugins.bot_unified_runtime.runtime.base_router import (
    ROUTE_RULES,
    RouteDecision,
    RouteKind,
    RouteRule,
    classify_message_route,
    clear_route_decision_cache,
)


class _DefaultConfig:
    """全部路由开关走 base_router 的 getattr 默认值（默认启用语义）。"""


@pytest.fixture(autouse=True)
def _clean_route_cache():
    clear_route_decision_cache()
    yield
    clear_route_decision_cache()


# ---------------------------------------------------------------------------
# ① 合成规则：直接锁定循环的排序语义（不依赖任何能力词表）
# ---------------------------------------------------------------------------


def _fake_rule(kind: RouteKind, priority: int, decision: RouteDecision) -> RouteRule:
    return RouteRule(
        kind,
        "bot.fake",
        priority,
        "假规则",
        "排序语义测试",
        matcher=lambda _text, _config, _alias: decision,
    )


def test_lower_priority_number_wins_regardless_of_list_order(monkeypatch) -> None:
    """修前语义反证：清单序在前的 50 档会抢赢在后的 41 档；修后 41 档胜。"""
    chat = RouteDecision(RouteKind.CHAT, "bot.chat", 50, "低优先（数值大）", ())
    eat = RouteDecision(RouteKind.EAT, "bot.eat", 41, "高优先（数值小）", ())
    monkeypatch.setattr(
        base_router, "ROUTE_RULES", [_fake_rule(RouteKind.CHAT, 50, chat), _fake_rule(RouteKind.EAT, 41, eat)]
    )
    clear_route_decision_cache()
    decision = classify_message_route("任意文本", config=object(), alias_resolver=None)
    assert decision.kind is RouteKind.EAT


def test_equal_priority_keeps_declared_order(monkeypatch) -> None:
    """同 priority：稳定排序保持原清单相对序，先到先得语义不变。"""
    music = RouteDecision(RouteKind.MUSIC, "bot.music", 41, "清单序在前", ())
    eat = RouteDecision(RouteKind.EAT, "bot.eat", 41, "清单序在后", ())
    monkeypatch.setattr(
        base_router, "ROUTE_RULES", [_fake_rule(RouteKind.MUSIC, 41, music), _fake_rule(RouteKind.EAT, 41, eat)]
    )
    clear_route_decision_cache()
    decision = classify_message_route("任意文本", config=object(), alias_resolver=None)
    assert decision.kind is RouteKind.MUSIC


# ---------------------------------------------------------------------------
# ② 真实双命中样例：同文本命中 stocks(42) 与 eat(41)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["怎么做股票", "如何做股票"])
def test_double_hit_sample_really_hits_both_stocks_and_eat(text: str) -> None:
    """前提自证：样例确实双命中（否则排序语义断言失去意义）。"""
    assert is_recipe_command(text) is True  # eat 侧走 _RECIPE_RE（怎么做/如何做）
    assert is_stocks_command(text) is True  # stocks 侧走 _STOCK_HINT_RE（股票 hint）


@pytest.mark.parametrize("text", ["怎么做股票", "如何做股票"])
def test_eat_41_beats_stocks_42_on_double_hit(text: str) -> None:
    """priority 即判定序：41 档 eat 先于 42 档 stocks（修前列表序反之被抢）。"""
    decision = classify_message_route(text, config=_DefaultConfig(), alias_resolver=None)
    assert decision.kind is RouteKind.EAT


# ---------------------------------------------------------------------------
# ③ stocks 真命令照旧 + 清单书写顺序不被重排
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["英伟达股价", "美股股价", "腾讯股价", "openai 估值多少"])
def test_stocks_real_commands_unaffected_by_order_fix(text: str) -> None:
    """无 41 档竞争者时 stocks 真命令照旧归 STOCKS（排序修复零回归）。"""
    decision = classify_message_route(text, config=_DefaultConfig(), alias_resolver=None)
    assert decision.kind is RouteKind.STOCKS


def test_declared_list_order_untouched() -> None:
    """最小改动铁律：只改遍历排序，清单书写顺序不动（stocks 仍写在 eat 之前）。"""
    kinds = [rule.kind for rule in ROUTE_RULES]
    assert kinds.index(RouteKind.STOCKS) < kinds.index(RouteKind.EAT)
