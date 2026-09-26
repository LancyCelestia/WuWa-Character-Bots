"""繁體触发词路由层回归（TRA 第二批：news 快報族 + randpic 隨機圖族）。

数据来源：.superpowers/sdd/2026-09-12-shorekeeper-global-audit/
traditional-mapping-draft.json（错位① 快報/財經新聞/國際新聞、
错位② 隨機圖/來張圖 条目）与 fix-tra-report.md。
只锁路由层 is_* 判定；昵称动词表（DEFAULT_VERB_MAP）、echo 别名、
news 抓取/营销过滤/条数行为均不归本文件。
"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.domains.meme.capabilities.randpic import (
    is_randpic_command,
)
from plugins.bot_unified_runtime.domains.subscribe.capabilities.news import (
    is_news_command,
)

# ---------------------------------------------------------------- news（错位①：快報族繁體路由缺失）


@pytest.mark.parametrize(
    "text",
    [
        "快報",
        "早報",
        "晚報",
        "今日熱點",
        "科技新聞",
        "AI新聞",
        "ai新聞",  # 大小写不敏感与简体同口径
        "AI快報",
        "財經新聞",
        "財經快報",
        "國際新聞",
        "來一份財經新聞",  # 子串命中，与简体「来一份今日快报」同哲学
    ],
)
def test_news_traditional_triggers_route(text: str) -> None:
    assert is_news_command(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "新聞",  # 裸「新聞」与裸「新闻」同口径：那是搜索链路的地盘
        "搜索財經新聞",  # 明确搜索意图让路（「搜索」简繁同形）
        "快報 https://example.com",  # 带链接是链接解析的活
    ],
)
def test_news_traditional_guards_unchanged(text: str) -> None:
    assert is_news_command(text) is False


def test_news_simplified_controls_unchanged() -> None:
    assert is_news_command("快报") is True
    assert is_news_command("财经新闻") is True
    assert is_news_command("新闻") is False


# ---------------------------------------------------------------- randpic（错位②：方向反转，路由层补繁體）


@pytest.mark.parametrize(
    "text,expected",
    [
        # 繁體补齐（草稿：路由加隨機圖/來張圖）。
        ("隨機圖", True),
        ("來張圖", True),
        ("隨機圖！", True),  # 标点边界与简体同口径
        ("隨機圖片庫", False),  # 包含关系词不误触发（与「随机图片库在哪」同门）
        # 既有简体/英文触发零回归。
        ("随机图", True),
        ("来张图！", True),
        ("randpic", True),
        ("随机图片库在哪", False),
    ],
)
def test_randpic_traditional_and_simplified_matrix(text: str, expected: bool) -> None:
    assert is_randpic_command(text) is expected
