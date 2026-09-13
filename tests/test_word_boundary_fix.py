r"""ASCII 词边界右侧胶合修复回归（bot.wiki / bot.moegirl / bot.eat / bot.today_history）。

背景：T-Spec 触发规格体检（tests/test_trigger_spec.py 词边界纪律棘轮）钉出
四处 is_* 判定对右侧胶合探针（``<word>qq`` 类字母延续）裸子串命中：
wiki×2（wikiqq / wikipediaqq）、moegirl×1、eat×1（recipesqq）、
today_history×1（today in historyqq）。

修复口径沿用 stocks ``_alias_hit`` 先例：ASCII 词右侧词边界
``(?![a-z0-9])``（IGNORECASE 下等同阻断全字母数字延续；
eat 的 _RECIPE_RE 无 IGNORECASE，用显式 ``(?![A-Za-z0-9])``）。
不采用 meme ``steal(?!\S)`` 口径：体检 verified 探针含 ``？`` 后缀
（``wiki？`` / ``recipes？`` 等必须照常命中），而 ``？`` 属 ``\S`` 会误伤。

同时锁定既有触发零回归：中文胶合查询（维基鸣潮）、全角标点后缀、
斜杠短别名（/today、/history）均维持原命中行为。
"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.capabilities.eat import is_recipe_command
from plugins.bot_unified_runtime.capabilities.moegirl import is_moegirl_command
from plugins.bot_unified_runtime.capabilities.today_history import (
    is_today_history_command,
)
from plugins.bot_unified_runtime.capabilities.wiki import is_wiki_command

# 右侧胶合探针（字母延续）必须不命中——T-Spec 台账 5 条的修复断言。
_GLUED_CASES = [
    (is_wiki_command, "wikiqq"),
    (is_wiki_command, "wikipediaqq"),
    (is_moegirl_command, "moegirlqq"),
    (is_recipe_command, "recipesqq"),
    (is_today_history_command, "today in historyqq"),
]

# 真词与既有触发形态必须照常命中（零回归锁定）。
_REAL_CASES = [
    (is_wiki_command, "wiki 鸣潮"),
    (is_wiki_command, "wikipedia 鸣潮"),
    (is_wiki_command, "wiki？"),
    (is_wiki_command, "维基 鸣潮"),
    (is_wiki_command, "维基鸣潮"),  # 中文胶合查询是既有行为，保持
    (is_wiki_command, "维基百科鸣潮"),
    (is_moegirl_command, "moegirl 初音未来"),
    (is_moegirl_command, "moegirl？"),
    (is_moegirl_command, "萌百 初音未来"),
    (is_recipe_command, "recipes 红烧肉"),
    (is_recipe_command, "recipes：红烧肉"),
    (is_recipe_command, "recipes？"),
    (is_recipe_command, "菜谱 红烧肉"),
    (is_today_history_command, "today in history"),
    (is_today_history_command, "today in history 测试"),
    (is_today_history_command, "today in history？"),
    (is_today_history_command, "历史上的今天"),
    (is_today_history_command, "/today"),  # 斜杠短别名不涉本修复，锁定不变
    (is_today_history_command, "/history"),
]


@pytest.mark.parametrize("detector,glued", _GLUED_CASES, ids=lambda x: str(x))
def test_right_glued_ascii_probe_not_hit(detector, glued: str) -> None:
    """ASCII 右侧胶合（字母延续）不得命中自身触发判定。"""
    assert not detector(glued), f"{detector.__name__} 对胶合探针 {glued!r} 仍命中"


@pytest.mark.parametrize("detector,text", _REAL_CASES, ids=lambda x: str(x))
def test_real_words_still_hit(detector, text: str) -> None:
    """真词与既有触发形态照常命中——修复不得引入触发回归。"""
    assert detector(text), f"{detector.__name__} 丢失既有触发 {text!r}"
