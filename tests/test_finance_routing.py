"""金融能力生产接线回归（TDD，全离线）：个股 bot.stocks / 汇率 bot.fx 进基层路由与分发。

锁定四件事：
1. stocks_match/fx_match 触发面（镜像 market_match：config 开关默认开 + 能力触发词）；
2. market > fx > stocks 让路序（「行情」裸词仍归 MARKET；fx 数值优先于 stocks；
   fx 触发词「汇率」已被 market 非股市词表排除，market/fx 天然互斥）；
3. bot_stocks_enabled / bot_fx_enabled 关闭即不触发；
4. __init__.py 分发层接线（stocks/fx 共享与 market 同源的 render_backend；
   today_history 调度器内部分流：推送显式 render_backend=None 纯文字、交互
   注入同源后端出卡；divination 走 backend 工厂壳）——启动函数体无法离线
   单测，按「源码 AST 断言接线存在 + 顶层模块导入断言 OFFLOADED 集合」切口锁定。
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.capabilities.divination import (
    build_divination_capability,
)
from plugins.bot_unified_runtime.capabilities.fx import (
    build_fx_capability,
    is_fx_command,
)
from plugins.bot_unified_runtime.capabilities.market import is_market_command
from plugins.bot_unified_runtime.capabilities.stocks import (
    build_stocks_capability,
    is_stocks_command,
)
from plugins.bot_unified_runtime.capabilities.today_history import (
    build_today_history_capability,
)
from plugins.bot_unified_runtime.runtime.base_router import (
    COMMAND_ROUTE_KINDS,
    INTERNAL_CAPABILITY_NOTES,
    ROUTE_RULES,
    RouteKind,
    build_route_rules,
    classify_message_route,
    clear_route_decision_cache,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INIT_PATH = PROJECT_ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"


@pytest.fixture(autouse=True)
def _clean_route_cache():
    clear_route_decision_cache()
    yield
    clear_route_decision_cache()


def _cfg(**overrides):
    base = {
        "bot_market_enabled": True,
        "bot_stocks_enabled": True,
        "bot_fx_enabled": True,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _rule(kind: RouteKind):
    for rule in build_route_rules():
        if rule.kind is kind:
            return rule
    raise AssertionError(f"路由表缺 {kind} 规则")


def _match(kind: RouteKind, text: str, config: SimpleNamespace | None = None):
    rule = _rule(kind)
    assert rule.matcher is not None, f"{kind} 规则缺 matcher"
    return rule.matcher(text, config if config is not None else _cfg(), None)


# ---------------------------------------------------------------------------
# ① 触发面：stocks_match / fx_match（直接调 match 函数）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["英伟达股价", "美股股价", "AMD市值"])
def test_stocks_match_routes_equity_triggers(text: str) -> None:
    decision = _match(RouteKind.STOCKS, text)
    assert decision is not None
    assert decision.kind is RouteKind.STOCKS
    assert decision.capability_id == "bot.stocks"


@pytest.mark.parametrize("text", ["美元兑人民币", "汇率", "100日元换多少人民币"])
def test_fx_match_routes_fx_triggers(text: str) -> None:
    decision = _match(RouteKind.FX, text)
    assert decision is not None
    assert decision.kind is RouteKind.FX
    assert decision.capability_id == "bot.fx"


@pytest.mark.parametrize("kind", [RouteKind.STOCKS, RouteKind.FX])
@pytest.mark.parametrize("text", ["行情", "随便聊聊"])
def test_finance_match_yields_non_finance_texts(kind: RouteKind, text: str) -> None:
    assert _match(kind, text) is None


def test_market_still_owns_bare_quotes() -> None:
    decision = _match(RouteKind.MARKET, "行情")
    assert decision is not None
    assert decision.kind is RouteKind.MARKET
    # 互让语义内建：market 的非股市词表本就排除「汇率」。
    assert is_market_command("汇率") is False
    assert is_market_command("行情") is True


def test_capability_trigger_predicates_agree_with_routes() -> None:
    # 路由判定与能力触发词同源（防止 match 壳与能力层漂移）。
    assert is_stocks_command("英伟达股价") is True
    assert is_stocks_command("随便聊聊") is False
    assert is_fx_command("美元兑人民币") is True
    assert is_fx_command("随便聊聊") is False


# ---------------------------------------------------------------------------
# ①（端到端）classify_message_route：全链路分类
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("英伟达股价", RouteKind.STOCKS),
        ("美股股价", RouteKind.STOCKS),
        ("美元兑人民币", RouteKind.FX),
        ("汇率", RouteKind.FX),
        ("行情", RouteKind.MARKET),
    ],
)
def test_classify_routes_finance_texts(text: str, expected: RouteKind) -> None:
    decision = classify_message_route(text, config=_cfg())
    assert decision.kind is expected


def test_classify_chat_text_not_hijacked_by_finance() -> None:
    decision = classify_message_route("随便聊聊", config=_cfg())
    assert decision.kind not in (RouteKind.STOCKS, RouteKind.FX)


# ---------------------------------------------------------------------------
# ② 优先级裁定：market > fx > stocks，且与既有 41 档不冲突
# ---------------------------------------------------------------------------


def test_route_order_market_before_fx_before_stocks() -> None:
    kinds = [rule.kind for rule in build_route_rules()]
    assert kinds.index(RouteKind.MARKET) < kinds.index(RouteKind.FX)
    assert kinds.index(RouteKind.FX) < kinds.index(RouteKind.STOCKS)


def test_priority_numbers_fx_beats_stocks_and_market_tier_unchanged() -> None:
    market_rule = _rule(RouteKind.MARKET)
    fx_rule = _rule(RouteKind.FX)
    stocks_rule = _rule(RouteKind.STOCKS)
    assert market_rule.priority == 41  # market 既有 41 档不动（最泛「行情」catch-all）
    assert fx_rule.priority < stocks_rule.priority  # 重叠时 fx 优先级更高
    assert stocks_rule.priority in (41, 42)  # 均在 market 相邻档
    # WP5（2026-09-21）：fx 从 41 拆到 36，与 market(41) 数值互不相同，问汇率不再
    # 靠「market/fx 同 41 书写序」定胜负（旧口径 fx∈(41,42) 会强制 fx=41=market，
    # 正是审计 E4-2 的同优先级劫持根因）。仍锁 fx < stocks，三档 (market,fx,stocks)
    # 优先级两两不同（见下方 distinct 断言）。
    assert fx_rule.priority in (36, 41, 42)
    assert (
        len({(market_rule.priority, market_rule.kind), (fx_rule.priority, fx_rule.kind), (stocks_rule.priority, stocks_rule.kind)})
        == 3
    )


def test_market_wins_when_market_and_stocks_both_match() -> None:
    # 「股市股价」同时命中 market（股市）与 stocks（股价）→ market 让路序在前。
    assert is_market_command("股市股价") is True
    assert is_stocks_command("股市股价") is True
    decision = classify_message_route("股市股价", config=_cfg())
    assert decision.kind is RouteKind.MARKET


def test_existing_route_kinds_order_semantics_untouched() -> None:
    # 枚举增量不得打乱既有成员相对顺序（audit 表/文档生成依赖声明顺序）。
    kinds = [rule.kind for rule in ROUTE_RULES]
    anchors = [
        RouteKind.ALIAS,
        RouteKind.ADMIN,
        RouteKind.SUBSCRIBE,
        RouteKind.MUSIC,
        RouteKind.TODAY_HISTORY,
        RouteKind.WEATHER,
        RouteKind.MARKET,
        RouteKind.EAT,
        RouteKind.AFFINITY,
        RouteKind.DIVINATION,
        RouteKind.NEWS,
        RouteKind.NATURAL_COMMAND,
        RouteKind.CONTENT,
        RouteKind.CHAT,
    ]
    positions = [kinds.index(kind) for kind in anchors]
    assert positions == sorted(positions), "既有路由规则相对顺序被打乱"


def test_finance_kinds_are_command_route_kinds() -> None:
    # 与 market 同门控：进 COMMAND_ROUTE_KINDS 才能被群门禁识别为确定性命令。
    assert RouteKind.STOCKS in COMMAND_ROUTE_KINDS
    assert RouteKind.FX in COMMAND_ROUTE_KINDS


def test_finance_capabilities_registered_as_internal_notes() -> None:
    # 无独立帮助主题的路由能力必须在 INTERNAL_CAPABILITY_NOTES 登记
    # （tests/test_documentation_consistency.py 的「路由能力无孤儿」门禁消费）。
    assert "bot.stocks" in INTERNAL_CAPABILITY_NOTES
    assert "bot.fx" in INTERNAL_CAPABILITY_NOTES


# ---------------------------------------------------------------------------
# ③ config 开关：bot_stocks_enabled / bot_fx_enabled 默认开、关即不触发
# ---------------------------------------------------------------------------


def test_finance_switches_default_open() -> None:
    assert _match(RouteKind.STOCKS, "英伟达股价") is not None
    assert _match(RouteKind.FX, "美元兑人民币") is not None


def test_finance_switches_off_disables_routing() -> None:
    assert _match(RouteKind.STOCKS, "英伟达股价", _cfg(bot_stocks_enabled=False)) is None
    assert _match(RouteKind.FX, "美元兑人民币", _cfg(bot_fx_enabled=False)) is None
    stocks_off = _cfg(bot_stocks_enabled=False)
    assert classify_message_route("英伟达股价", config=stocks_off).kind is not RouteKind.STOCKS
    fx_off = _cfg(bot_fx_enabled=False)
    assert classify_message_route("汇率", config=fx_off).kind is not RouteKind.FX


# ---------------------------------------------------------------------------
# ④ __init__.py 分发层接线（AST 源码级 + 顶层模块导入级）
# ---------------------------------------------------------------------------


def _init_tree() -> ast.Module:
    return ast.parse(INIT_PATH.read_text(encoding="utf-8"), filename=str(INIT_PATH))


def _function_names(tree: ast.Module) -> set[str]:
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _calls(tree: ast.Module, name: str) -> list[ast.Call]:
    found: list[ast.Call] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if (isinstance(func, ast.Name) and func.id == name) or (
                isinstance(func, ast.Attribute) and func.attr == name
            ):
                found.append(node)
    return found


def _has_render_backend_kwarg(call: ast.Call) -> bool:
    return any(kw.arg == "render_backend" for kw in call.keywords)


def _backend_factory_builds_capability(
    tree: ast.Module, factory: str, builder: str
) -> bool:
    names = _function_names(tree)
    if factory not in names:
        return False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == factory:
            for call in ast.walk(node):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name)
                    and call.func.id == builder
                    and _has_render_backend_kwarg(call)
                ):
                    return True
    return False


def _simple_capability_dispatches(tree: ast.Module, capability_id: str, factory: str) -> bool:
    for call in _calls(tree, "_run_simple_capability"):
        constants = [arg.value for arg in call.args if isinstance(arg, ast.Constant)]
        names = [arg.id for arg in call.args if isinstance(arg, ast.Name)]
        if capability_id in constants and factory in names:
            return True
    return False


def _on_message_with_rule(tree: ast.Module, rule_name: str) -> bool:
    for call in _calls(tree, "on_message"):
        for kw in call.keywords:
            if kw.arg == "rule" and isinstance(kw.value, ast.Name) and kw.value.id == rule_name:
                return True
    return False


def test_init_builds_stocks_fx_with_shared_render_backend() -> None:
    tree = _init_tree()
    assert _backend_factory_builds_capability(tree, "_build_stocks_with_backend", "build_stocks_capability")
    assert _backend_factory_builds_capability(tree, "_build_fx_with_backend", "build_fx_capability")
    # 与 market 同一实例来源：两个工厂都定义在启动函数内、引用同一 render_backend 闭包变量。
    assert _backend_factory_builds_capability(tree, "_build_market_with_backend", "build_market_capability")


def test_init_registers_stocks_fx_matchers_and_handlers() -> None:
    tree = _init_tree()
    assert _on_message_with_rule(tree, "_is_stocks_event")
    assert _on_message_with_rule(tree, "_is_fx_event")
    assert _simple_capability_dispatches(tree, "bot.stocks", "_build_stocks_with_backend")
    assert _simple_capability_dispatches(tree, "bot.fx", "_build_fx_with_backend")


def test_init_offloads_stocks_fx_capabilities() -> None:
    # 与 bot.market 同池：网络拉取 + Playwright 渲染必须 offload（线程池），防冻结事件循环。
    from plugins.bot_unified_runtime import OFFLOADED_CAPABILITY_IDS

    assert "bot.stocks" in OFFLOADED_CAPABILITY_IDS
    assert "bot.fx" in OFFLOADED_CAPABILITY_IDS
    assert "bot.market" in OFFLOADED_CAPABILITY_IDS


def test_init_passes_render_backend_to_divination_and_today_history() -> None:
    tree = _init_tree()
    today_calls = [
        call
        for call in _calls(tree, "build_today_history_capability")
        if isinstance(call.func, ast.Name)
    ]
    assert len(today_calls) >= 4, "today_history 生产调用点数量异常"
    for call in today_calls:
        assert _has_render_backend_kwarg(call), "today_history 调用点缺 render_backend"
    divination_calls = [
        call
        for call in _calls(tree, "build_divination_capability")
        if isinstance(call.func, ast.Name)
    ]
    assert len(divination_calls) >= 1, "divination 生产调用点缺失"
    for call in divination_calls:
        assert _has_render_backend_kwarg(call), "divination 调用点缺 render_backend"
    # divination 分发走 market 同款 backend 工厂壳。
    assert _simple_capability_dispatches(tree, "bot.divination", "_build_divination_with_backend")
    # F2 分流后的现行行为：调度器注册点把同源后端传进 _register_today_history_scheduler，
    # 函数内部再分流——推送能力显式 render_backend=None（纯文字，不依赖 Playwright
    # 渲染进程），交互能力注入同源后端出卡。两次 build 调用都带 render_backend
    # kwarg，故 kwarg 存在性断言仍覆盖两路。
    scheduler_calls = _calls(tree, "_register_today_history_scheduler")
    assert scheduler_calls, "today_history 调度器注册调用缺失"
    assert all(_has_render_backend_kwarg(call) for call in scheduler_calls)


def test_capability_builders_accept_render_backend_kwarg() -> None:
    # 接线契约：四个能力工厂都接受 render_backend 关键字（默认 None）。
    for builder in (
        build_stocks_capability,
        build_fx_capability,
        build_divination_capability,
        build_today_history_capability,
    ):
        signature = inspect.signature(builder)
        assert "render_backend" in signature.parameters, builder
        assert signature.parameters["render_backend"].default is None
