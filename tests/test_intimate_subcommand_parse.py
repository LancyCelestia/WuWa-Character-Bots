"""`match_intimate_subcommand`：/bot intimate 子命令族的**参数串**解析口（纯解析）。

边界（与整句口 `match_intimate_command` 同形不同路）：
- 输入＝调用方剥掉 `/bot intimate` 前缀后剩下的参数串，本口**不管前缀**；
- 词表只认 on/open/l1 → 浅档、deep/l2/deeper → 深档、off/close/unset → 解除；
- `show` 不是开关：本口返回 None，由调用方另判（见函数 docstring）；
- 认不出的一律 None——不猜档、不回落成"开"。

全离线：不碰引擎状态、不碰配置、不构造能力面。
"""
from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.runtime.content_route import (
    INTIMATE_TIER_L1,
    INTIMATE_TIER_L2,
    INTIMATE_TIER_NONE,
    MODE_INTIMATE,
    MODE_NORMAL,
    match_intimate_subcommand,
)


def test_tier_constants_are_distinct() -> None:
    """前提锁：浅/深/未进档三枚档位值互不相同，否则下面所有元组断言都是空断言。"""
    assert INTIMATE_TIER_L1 != INTIMATE_TIER_L2
    assert INTIMATE_TIER_NONE not in {INTIMATE_TIER_L1, INTIMATE_TIER_L2}


@pytest.mark.parametrize("word", ["on", "open", "l1"])
def test_shallow_words_map_to_intimate_l1(word: str) -> None:
    assert match_intimate_subcommand(word) == (MODE_INTIMATE, INTIMATE_TIER_L1)


@pytest.mark.parametrize("word", ["deep", "l2", "deeper"])
def test_deep_words_map_to_intimate_l2(word: str) -> None:
    assert match_intimate_subcommand(word) == (MODE_INTIMATE, INTIMATE_TIER_L2)


@pytest.mark.parametrize("word", ["off", "close", "unset"])
def test_off_words_map_to_normal_none(word: str) -> None:
    assert match_intimate_subcommand(word) == (MODE_NORMAL, INTIMATE_TIER_NONE)


def test_case_insensitive() -> None:
    assert match_intimate_subcommand("ON") == (MODE_INTIMATE, INTIMATE_TIER_L1)
    assert match_intimate_subcommand("Deep") == (MODE_INTIMATE, INTIMATE_TIER_L2)
    assert match_intimate_subcommand("L2") == (MODE_INTIMATE, INTIMATE_TIER_L2)
    assert match_intimate_subcommand("OFF") == (MODE_NORMAL, INTIMATE_TIER_NONE)


def test_surrounding_whitespace_tolerated() -> None:
    assert match_intimate_subcommand("  on  ") == (MODE_INTIMATE, INTIMATE_TIER_L1)
    assert match_intimate_subcommand("\tdeep\n") == (MODE_INTIMATE, INTIMATE_TIER_L2)
    assert match_intimate_subcommand(" off ") == (MODE_NORMAL, INTIMATE_TIER_NONE)


def test_bare_command_returns_none() -> None:
    """裸命令（参数串为空/只有空白）→ None，不许猜一个默认档。"""
    assert match_intimate_subcommand("") is None
    assert match_intimate_subcommand("   ") is None


@pytest.mark.parametrize("word", ["banana", "开", "l3", "on off", "deeep", "not"])
def test_unrecognized_words_return_none(word: str) -> None:
    assert match_intimate_subcommand(word) is None


def test_show_returns_none_for_caller_to_handle() -> None:
    """show 不是开关：本口不给 (mode, tier) 元组，返回 None 让调用方另判。"""
    assert match_intimate_subcommand("show") is None


def test_l1_is_never_misjudged_as_deep() -> None:
    """防过修格①：浅档词绝不能吃成深档（深浅只此一处判据，不许串档）。"""
    verdict = match_intimate_subcommand("l1")
    assert verdict == (MODE_INTIMATE, INTIMATE_TIER_L1)
    assert verdict is not None and verdict[1] != INTIMATE_TIER_L2


def test_deep_is_never_downgraded_to_shallow() -> None:
    """防过修格②：深档词绝不被降成浅档（grok 优先是深档独有权限）。"""
    verdict = match_intimate_subcommand("deep")
    assert verdict == (MODE_INTIMATE, INTIMATE_TIER_L2)
    assert verdict is not None and verdict[1] != INTIMATE_TIER_L1
