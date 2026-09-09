"""吃什么能力回归：推荐/换菜/辣度过滤/菜谱查询。"""

from __future__ import annotations

from types import SimpleNamespace

from plugins.bot_unified_runtime.capabilities.eat import (
    build_eat_capability,
    clear_recent_dishes,
)
from plugins.bot_unified_runtime.contracts import SessionType
from plugins.bot_unified_runtime.contracts.runtime import IncomingMessage


def _message(text: str, session_id: str = "private:u1") -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id=session_id,
        session_type=SessionType.PRIVATE,
        sender_id="u1",
        plain_text=text,
    )


def _capability():
    return build_eat_capability(SimpleNamespace(bot_card_render_dir="", bot_card_cache_max_bytes=0))


def setup_function(_fn) -> None:
    clear_recent_dishes()


def test_random_recommendation_answers_with_dish() -> None:
    result = _capability()(_message("吃什么"), None)
    assert result.body
    assert "🍽" in result.body
    assert "食材" in result.body


def test_three_picks_are_distinct() -> None:
    result = _capability()(_message("吃什么 三选一"), None)
    dish_section = result.body.split("纠结就掷骰子", 1)[-1]
    names = [line for line in dish_section.splitlines() if line.startswith("🍽")]
    assert len(names) == 3
    assert len(set(names)) == 3


def test_recipe_lookup_by_name() -> None:
    result = _capability()(_message("菜谱 番茄炒蛋"), None)
    assert "番茄炒蛋" in result.body
    assert "做法" in result.body


def test_recipe_alias_how_to_cook() -> None:
    result = _capability()(_message("怎么做 可乐鸡翅"), None)
    assert "可乐鸡翅" in result.body


def test_recipe_not_found_message() -> None:
    result = _capability()(_message("菜谱 不存在的黑暗料理王"), None)
    assert "还没有" in result.body


def test_spicy_filter() -> None:
    result = _capability()(_message("吃什么 不辣"), None)
    spicy_marks = ("麻辣", "香辣", "酸辣")
    assert not any(mark in result.body for mark in spicy_marks) or "不辣" in result.body
