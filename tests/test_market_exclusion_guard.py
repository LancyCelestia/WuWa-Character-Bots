"""触发劫持③回归锁（TDD，全离线）：market「行情」排除表补商品价格语境词。

探针实证（scripts/probe_trigger_hijack.py §③，HEAD 36b373e）：
「油价行情/金价行情」≤32 字落股指面板（MARKET 先于 CHAT），应让路 chat。
修法与既有「汇率」排除同款：_NON_STOCK_RE 补 油价/金价/银价/铜价/煤价/电价/
菜价/石油/黄金 及繁体变体。

2026-09-13 六域批语义迁移（本席接线 bot.commodities 后）：market 排除表
谓词层零改动（is_market_command 仍 False），但金价/油价等商品触发词的
L2 落点从 CHAT 迁到 bot.commodities 商品卡（COMMODITIES 先于 MARKET）；
无触发词的 煤价/电价/菜价/石油 与带 URL 的样例仍归 CHAT。

铁律：真命令对照（行情/A股行情/美股行情/大盘行情/莫斯科股指…）零回归；
「黄金股行情」含股 hint 词仍归 market（黄金板块是股市语境，守卫放行）。
"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.capabilities.market import is_market_command
from plugins.bot_unified_runtime.runtime.base_router import (
    RouteKind,
    classify_message_route,
)


class _DefaultConfig:
    """全部路由开关走 base_router 的 getattr 默认值（默认启用语义）。"""


# 探针 §③ 三条劫持样例（修后应让路 chat）。
_HIJACK_SAMPLES = (
    "今天油价行情怎么样",
    "金价行情如何",
    "看看油价行情",
)

# 同族商品价格语境词（与油价/金价同一挂法补入排除表）。
_COMMODITY_SAMPLES = (
    "银价行情",
    "铜价行情",
    "煤价行情",
    "电价行情",
    "菜价行情",
    "石油行情",
    "黄金行情",
    "油價行情",  # 繁体变体（评审 P1-2 繁简一致先例）
    "金價行情",
)

# 既有边界（修前即正确，防回归）。
_ALREADY_CORRECT = (
    "今天金价多少",  # 不带「行情」本就不触发
    "金价行情 https://example.com/gold",  # URL 守卫让位链接解析
)

# 真命令对照（零回归铁律）。
_TRUE_COMMANDS = (
    "行情",
    "A股行情",
    "美股行情",
    "大盘行情",
    "莫斯科股指",
    "看看日经行情",
    "股市大盘行情",  # 非股词 + 股票词 → 放行（既有语义）
    "黄金股行情",  # 黄金板块是股市语境：股 hint 词覆盖商品排除
)


@pytest.mark.parametrize("text", [*_HIJACK_SAMPLES, *_COMMODITY_SAMPLES, *_ALREADY_CORRECT])
def test_commodity_price_context_yields_market(text: str) -> None:
    assert is_market_command(text) is False


@pytest.mark.parametrize("text", _TRUE_COMMANDS)
def test_real_market_commands_unchanged(text: str) -> None:
    assert is_market_command(text) is True


@pytest.mark.parametrize("text", [*_HIJACK_SAMPLES, *_COMMODITY_SAMPLES])
def test_routing_hijack_fixed(text: str) -> None:
    """L2 共享判定层复核（2026-09-13 语义迁移后）：market 仍不接商品语境。

    有商品触发词的样例落 bot.commodities 商品卡；煤价/电价/菜价/石油
    （无商品卡触发词）维持让路 chat——两种落点都绝不再被 MARKET 劫持。
    """
    decision = classify_message_route(text, config=_DefaultConfig(), alias_resolver=None)
    assert decision.kind in (RouteKind.COMMODITIES, RouteKind.CHAT)
    assert decision.kind is not RouteKind.MARKET


@pytest.mark.parametrize(
    "text",
    [
        "今天油价行情怎么样",
        "金价行情如何",
        "看看油价行情",
        "银价行情",
        "铜价行情",
        "黄金行情",
        "油價行情",
        "金價行情",
        "今天金价多少",  # 商品卡上线后：金价是显式触发词，落商品卡而非 chat。
    ],
)
def test_commodity_triggered_samples_route_to_commodities(text: str) -> None:
    decision = classify_message_route(text, config=_DefaultConfig(), alias_resolver=None)
    assert decision.kind is RouteKind.COMMODITIES


@pytest.mark.parametrize(
    "text",
    [
        "煤价行情",  # 无商品卡触发词：维持让路 chat。
        "电价行情",
        "菜价行情",
        "石油行情",
    ],
)
def test_non_card_commodity_context_still_chat(text: str) -> None:
    decision = classify_message_route(text, config=_DefaultConfig(), alias_resolver=None)
    assert decision.kind is RouteKind.CHAT


@pytest.mark.parametrize("text", ["美股行情", "大盘行情", "莫斯科股指"])
def test_routing_true_commands_unchanged(text: str) -> None:
    decision = classify_message_route(text, config=_DefaultConfig(), alias_resolver=None)
    assert decision.kind is RouteKind.MARKET
