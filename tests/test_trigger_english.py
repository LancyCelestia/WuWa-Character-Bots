"""T-Spec T1.2：路由级公开能力的英文短命令触发全集 + 全路由唯一命中检测。

锁定四件事（全离线，不外呼）：
1. 每个路由级公开能力至少一个英文短命令触发（小写、词边界、≥3 字母）；
   既有英文触发（weather/wiki/moegirl/music/meme/epic/affinity/subscribe/
   fx/stocks 语境形态）一并锁定防回归；
2. 反劫持负样本：子串形态（supermarket/stockholm/newsletter/itching）与
   聊天高频句（fast food/set a reminder/today is friday）不得触发；
3. 唯一命中：同一样例遍历全部 is_* 判定，除「stock market」让路对
   （market 41 先于 stocks 42，与「行情」裸词归 market 同构）外必须唯一；
4. 触发词 ↔ 帮助别名防脱册：每个英文触发在 echo 帮助注册表可见。
管理面命令（/bot …）不开放裸英文触发，不在本文件范围。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.capabilities.affinity import (
    is_affinity_command,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import (
    HELP_ENTRIES,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.base_router import (
    RouteKind,
    classify_message_route,
    clear_route_decision_cache,
)
from plugins.bot_unified_runtime.domains.divination.capabilities.divination import (
    is_divination_command,
    parse_divination_intent,
)
from plugins.bot_unified_runtime.domains.finance.capabilities.fx import is_fx_command
from plugins.bot_unified_runtime.domains.finance.capabilities.market import (
    is_market_command,
)
from plugins.bot_unified_runtime.domains.finance.capabilities.stocks import (
    is_stocks_command,
)
from plugins.bot_unified_runtime.domains.food.capabilities.eat import (
    is_eat_command,
    is_recipe_command,
)
from plugins.bot_unified_runtime.domains.location.capabilities.moegirl import (
    is_moegirl_command,
)
from plugins.bot_unified_runtime.domains.location.capabilities.wiki import (
    is_wiki_command,
)
from plugins.bot_unified_runtime.domains.meme.capabilities.meme import is_meme_command
from plugins.bot_unified_runtime.domains.meme.capabilities.meme_library import (
    is_meme_library_command,
)
from plugins.bot_unified_runtime.domains.meme.capabilities.randpic import (
    is_randpic_command,
)
from plugins.bot_unified_runtime.domains.music.capabilities.music import (
    is_music_command,
    is_music_mode_command,
)
from plugins.bot_unified_runtime.domains.schedule.auto_send import (
    is_auto_send_command_text,
)
from plugins.bot_unified_runtime.domains.schedule.capabilities.reminder import (
    is_reminder_command,
)
from plugins.bot_unified_runtime.domains.subscribe.capabilities.epic import (
    is_epic_command,
)
from plugins.bot_unified_runtime.domains.subscribe.capabilities.news import (
    is_news_command,
)
from plugins.bot_unified_runtime.domains.subscribe.capabilities.subscribe import (
    is_standalone_subscribe_command,
)
from plugins.bot_unified_runtime.domains.subscribe.capabilities.today_history import (
    is_today_history_command,
)
from plugins.bot_unified_runtime.domains.weather.capabilities.weather import (
    is_weather_command,
)


def _randpic(text: str) -> bool:
    return is_randpic_command(text)


# 全部路由级文本判定（与 base_router ROUTE_RULES 一一对应；chat/content/
# alias/admin/natural/moegirl_question 非短命令触发面，不在此表）。
ALL_MATCHERS: dict[str, object] = {
    "subscribe": is_standalone_subscribe_command,
    "auto_send": is_auto_send_command_text,
    "meme": is_meme_command,
    "meme_library": is_meme_library_command,
    "music_mode": is_music_mode_command,
    "music": is_music_command,
    "today_history": is_today_history_command,
    "wiki": is_wiki_command,
    "moegirl": is_moegirl_command,
    "epic": is_epic_command,
    "weather": is_weather_command,
    "market": is_market_command,
    "fx": is_fx_command,
    "stocks": is_stocks_command,
    "eat": is_eat_command,
    "recipe": is_recipe_command,
    "affinity": is_affinity_command,
    "divination": is_divination_command,
    "news": is_news_command,
    "randpic": _randpic,
    "reminder": is_reminder_command,
}

# (能力, 英文正样本)。recipe/eat 同属 bot.eat；music_mode 属点歌模式。
ENGLISH_TRIGGERS: list[tuple[str, str]] = [
    # —— 既有英文触发（回归锁定，零改动）——
    ("weather", "weather tokyo"),
    ("wiki", "wiki transistor"),
    ("wiki", "wikipedia quantum"),
    ("moegirl", "moegirl hatsune miku"),
    ("music", "music november rain"),
    ("music", "song hotel california"),
    ("music_mode", "music mode link"),
    ("meme", "meme petpet 可爱"),
    ("epic", "epic"),
    ("affinity", "affinity"),
    ("subscribe", "subscribe"),
    ("fx", "fx"),
    ("fx", "forex"),
    ("fx", "exchange rate"),
    ("stocks", "tech stocks"),
    ("stocks", "nvidia stock price"),
    # —— T1.2 新增英文触发 ——
    ("market", "market"),
    ("market", "markets"),
    ("market", "stock market"),
    ("stocks", "stock"),
    ("stocks", "stocks"),
    ("eat", "eat"),
    ("eat", "food"),
    ("eat", "eat something"),
    ("eat", "eat spicy"),
    ("recipe", "recipe 番茄炒蛋"),
    ("news", "news"),
    ("news", "tech news"),
    ("reminder", "reminder"),
    ("reminder", "reminders"),
    ("reminder", "my reminders"),
    ("reminder", "reminder list"),
    ("randpic", "randpic"),
    ("divination", "tarot"),
    ("divination", "tarots"),
    ("divination", "bazi"),
    ("divination", "iching"),
    ("divination", "hexagram"),
    ("divination", "daily tarot"),
    ("divination", "tarot three cards"),
    ("today_history", "today in history"),
    ("today_history", "/today"),
    ("today_history", "/history"),
    ("meme_library", "steal"),
    ("meme_library", "steal meme"),
]

# 反劫持负样本：任何判定都不命中（落回聊天/链接解析）。
HIJACK_NEGATIVES: list[str] = [
    "housing market",
    "labor market",
    "job market",
    "supermarket",
    "marketer",
    "stockholm",
    "fast food",
    "foodie",
    "eating",
    "newsletter",
    "breakingnews",
    "set a reminder",
    "reminder about friday",
    "random pictures",
    "itching",
    "enriching",
    "today is friday",
    "history of tea",
    "heated debate",
]

# 词面多命中、由 base_router 优先级裁定的让路对（与「行情」裸词归 market 同构）：
# 「stock market」→ MARKET（41 先于 stocks 42）；「music mode link」→
# MUSIC_MODE（40 先于 music 41，music 正则把 "mode link" 当歌名候选，属既有形态）。
PRIORITY_PAIRS: dict[str, tuple[frozenset[str], RouteKind]] = {
    "stock market": (frozenset({"market", "stocks"}), RouteKind.MARKET),
    "music mode link": (frozenset({"music_mode", "music"}), RouteKind.MUSIC_MODE),
}


def _hits(text: str) -> set[str]:
    return {
        name
        for name, matcher in ALL_MATCHERS.items()
        # 注释不可写成 `# type: …` 形态：mypy 会按类型注释解析，一枚非法注释即让
        # 全树 typecheck 停在 syntax 错误上（「errors prevented further checking」）。
        if matcher(text)
    }


@pytest.mark.parametrize(("capability", "sample"), ENGLISH_TRIGGERS)
def test_english_trigger_fires_capability(capability: str, sample: str) -> None:
    assert ALL_MATCHERS[capability](sample), (
        f"英文触发缺失：{capability} 应命中 {sample!r}（T-Spec T1.2）"
    )


@pytest.mark.parametrize("sample", HIJACK_NEGATIVES)
def test_hijack_negatives_fire_nothing(sample: str) -> None:
    hits = _hits(sample)
    assert not hits, f"反劫持失败：{sample!r} 误触发 {sorted(hits)}"


@pytest.mark.parametrize(("capability", "sample"), ENGLISH_TRIGGERS)
def test_unique_route_hit(capability: str, sample: str) -> None:
    if sample in PRIORITY_PAIRS:
        expected_names, _ = PRIORITY_PAIRS[sample]
        assert _hits(sample) == set(expected_names)
        return
    hits = _hits(sample)
    expected_names = set(capability.split("|"))
    assert hits == expected_names, (
        f"{sample!r} 预期仅命中 {sorted(expected_names)}，实得 {sorted(hits)}"
    )


@pytest.mark.parametrize(
    ("sample", "expected"), sorted(PRIORITY_PAIRS.items())
)
def test_priority_pair_resolves_by_router(
    sample: str, expected: tuple[frozenset[str], RouteKind]
) -> None:
    """让路对裁定：多命中样例由 base_router 优先级归一（先到先得）。"""
    _, expected_kind = expected
    clear_route_decision_cache()
    config = SimpleNamespace(
        bot_market_enabled=True,
        bot_stocks_enabled=True,
        bot_fx_enabled=True,
        bot_subscribe_enabled=True,
        bot_music_enabled=True,
        bot_auto_send_enabled=True,
    )
    decision = classify_message_route(sample, config=config)
    assert decision.kind is expected_kind, (
        f"{sample!r} 预期路由 {expected_kind}，实得 {decision.kind}"
    )
    clear_route_decision_cache()


def test_stock_market_resolves_to_market_by_priority() -> None:
    """让路对裁定：「stock market」归 MARKET（大盘语义），与「行情」裸词同构。"""
    clear_route_decision_cache()
    config = SimpleNamespace(
        bot_market_enabled=True,
        bot_stocks_enabled=True,
        bot_fx_enabled=True,
        bot_subscribe_enabled=True,
        bot_auto_send_enabled=True,
    )
    decision = classify_message_route("stock market", config=config)
    assert decision.kind is RouteKind.MARKET
    clear_route_decision_cache()


def test_divination_english_parses_intent() -> None:
    """英文触发必须能被意图解析承接（路由命中但 parse=None 会落 noop 分支）。"""
    assert parse_divination_intent("tarot") is not None
    assert parse_divination_intent("tarot").kind == "tarot"  # type: ignore[union-attr]
    assert parse_divination_intent("bazi").kind == "bazi"  # type: ignore[union-attr]
    assert parse_divination_intent("iching").kind == "iching"  # type: ignore[union-attr]
    assert parse_divination_intent("daily tarot").target == "daily"  # type: ignore[union-attr]


def test_reminder_english_maps_to_list_view() -> None:
    """reminder 英文触发承接列表查询（自然语言建提醒的 NLP 在 character 域，不在本批范围）。"""
    from plugins.bot_unified_runtime.domains.schedule.capabilities.reminder import (
        _LIST_RE,
    )

    for sample in ("reminder", "reminders", "my reminders", "reminder list"):
        assert _LIST_RE.search(sample), f"提醒列表正则未覆盖 {sample!r}"


# ---------------------------------------------------------------------------
# 防脱册：英文触发 ↔ echo 帮助别名
# ---------------------------------------------------------------------------

_TOPIC_ALIAS_FLOOR: dict[str, tuple[str, ...]] = {
    "天气": ("weather",),
    "点歌": ("music", "song"),
    "订阅": ("subscribe",),
    "维基": ("wiki",),
    "萌娘百科": ("moegirl",),
    "Epic": ("epic",),
    "表情": ("meme",),
    "偷表情": ("steal",),
    "行情": ("market",),
    "个股行情": ("stocks", "stock"),
    "汇率": ("fx", "forex", "exchange rate"),
    "占卜": ("divination", "tarot", "bazi", "iching"),
    "快报": ("news",),
    "吃什么": ("eat", "food", "recipe"),
    "历史上的今天": ("today", "today in history"),
    "随机图": ("randpic",),
    "提醒": ("reminder",),
    "好感度": ("affinity",),
}


def _aliases_of(topic: str) -> set[str]:
    matches = [entry for entry in HELP_ENTRIES if entry["topic"] == topic]
    assert len(matches) == 1, f"帮助主题 {topic} 出现 {len(matches)} 次"
    return {str(alias) for alias in matches[0]["aliases"]}


@pytest.mark.parametrize(
    ("topic", "expected"), sorted(_TOPIC_ALIAS_FLOOR.items())
)
def test_english_triggers_documented_in_help(topic: str, expected: tuple[str, ...]) -> None:
    aliases = _aliases_of(topic)
    missing = {word for word in expected if word not in aliases}
    assert not missing, f"帮助主题 {topic} 缺英文别名：{sorted(missing)}（防脱册）"
