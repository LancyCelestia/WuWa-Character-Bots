"""触发劫持②修复回归（T-Spec T1.7 防劫持：语境不足不接）。

探针实证（``scripts/probe_trigger_hijack.py``，HEAD 36b373e）：STOCKS(42)
先于 moegirl_question(44)/chat——openai/anthropic 豁免词 ≤32 字子串即触发、
「股票」hint 词同为无锚子串，4 条聊天/问答句被个股面板劫持：

- 「openai是什么」→ 应落 moegirl_question（探针让路复测坐实）；
- 「openai 的 gpt 咋用」「anthropic和openai哪家强」「股票被套了怎么办，难受」
  → 应落 chat（用户要的是回答/建议，不是行情面板）。

修复口径：豁免公司词必须与股价语境词共现才触发；「是什么/咋用/哪家强/
被套/怎么办」类问答求建议句式一律让路。8 条真命令对照（openai 估值、
英伟达股价等）必须原样触发，路由仍归 STOCKS。全离线，零网络零落盘。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.runtime.base_router import (
    RouteKind,
    classify_message_route,
)
from plugins.bot_unified_runtime.domains.finance.capabilities.stocks import (
    is_stocks_command,
)

# 探针 ② 节 4 条劫持样例（text, 预期让路落点集）。
_HIJACK_SAMPLES: list[tuple[str, set[RouteKind]]] = [
    ("openai是什么", {RouteKind.MOEGIRL_QUESTION}),
    ("openai 的 gpt 咋用", {RouteKind.CHAT}),
    ("anthropic和openai哪家强", {RouteKind.CHAT}),
    ("股票被套了怎么办，难受", {RouteKind.CHAT}),
]

# 探针 ② 节真命令对照（+ 既有语境组合），必须原样触发个股面板。
_REAL_COMMANDS: list[str] = [
    "openai 估值多少",
    "英伟达股价",
    "openai 估值",
    "腾讯股价",
    "苹果市值",
    "stock",
    "stocks",
    "nvidia stock price",
]


@pytest.mark.parametrize(("text", "expected"), _HIJACK_SAMPLES)
def test_hijack_samples_vetoed_by_stocks_trigger(
    text: str, expected: set[RouteKind]
) -> None:
    """4 条劫持样例：is_stocks_command 必须否决（等价探针 HIJACKED→OK）。"""
    assert is_stocks_command(text) is False


@pytest.mark.parametrize(("text", "expected"), _HIJACK_SAMPLES)
def test_hijack_samples_fall_through_to_chat_or_moegirl(
    text: str, expected: set[RouteKind]
) -> None:
    """4 条劫持样例在真实路由序中落到 chat/moegirl，不再被 STOCKS(42) 抢走。"""
    decision = classify_message_route(
        text, config=SimpleNamespace(), alias_resolver=None
    )
    assert decision.kind in expected


@pytest.mark.parametrize("text", _REAL_COMMANDS)
def test_real_commands_still_trigger(text: str) -> None:
    """8 条真命令对照：修复不得破坏既有触发面。"""
    assert is_stocks_command(text) is True


@pytest.mark.parametrize("text", ["openai 估值多少", "英伟达股价"])
def test_real_commands_still_route_to_stocks(text: str) -> None:
    """探针 control 两条：路由仍归 STOCKS（让路只发生在问答/求建议句式）。"""
    decision = classify_message_route(
        text, config=SimpleNamespace(), alias_resolver=None
    )
    assert decision.kind is RouteKind.STOCKS
