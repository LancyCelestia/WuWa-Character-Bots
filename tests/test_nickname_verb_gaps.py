"""昵称动词缺口补全回归（fix-tra3 §四.1 移交：「点唱」「天气预报」简体对向缺口）。

需求：.superpowers/sdd/2026-09-12-shorekeeper-global-audit/fix-tra3-report.md §四。
- 缺口取证（修前实跑）：VERB_MAP 只有繁體「點唱」「天氣預報」与简体
  「点歌」「天气」——「守岸人点唱」「守岸人天气预报」解析落 None 坠 help。
- 修法：DEFAULT_VERB_MAP 补简体两词（实际机制在 runtime/aliases.py，
  非移交单所写 capabilities/echo.py）；personas/shorekeeper/aliases.txt
  只承载昵称（「守岸人」已在册），动词不登记于此，无需改。
- 防劫持：陈述句「天气预报说明天下雨」不得经昵称路径触发——昵称前缀
  本身是强信号，且动词后必须空白或结尾（胶合陈述句不匹配）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.runtime.aliases import CommandAliasResolver
from plugins.bot_unified_runtime.runtime.base_router import (
    RouteKind,
    classify_message_route,
    clear_route_decision_cache,
)

RESOLVER = CommandAliasResolver(nicknames=["守岸人", "岸宝"])


# ---------------------------------------------------------------- 缺口补齐（昵称可达）


def test_nick_request_song_reachable() -> None:
    r = RESOLVER.resolve("守岸人点唱")
    assert r is not None
    assert r.capability_id == "bot.music"
    assert r.verb == "点唱"
    assert r.rest_text == ""


def test_nick_request_song_with_query() -> None:
    r = RESOLVER.resolve("守岸人点唱 晴天")
    assert r is not None
    assert r.capability_id == "bot.music"
    assert r.rest_text == "晴天"


def test_nick_weather_forecast_reachable() -> None:
    r = RESOLVER.resolve("守岸人天气预报")
    assert r is not None
    assert r.capability_id == "bot.weather"
    assert r.verb == "天气预报"
    assert r.rest_text == ""


def test_nick_weather_forecast_with_city() -> None:
    r = RESOLVER.resolve("守岸人天气预报 台北")
    assert r is not None
    assert r.capability_id == "bot.weather"
    assert r.rest_text == "台北"


def test_longest_verb_priority_not_shadowed_by_weather() -> None:
    # 「天气预报」4 字动词必须先于「天气」2 字动词命中（长词优先既有机制）。
    r = RESOLVER.resolve("守岸人天气预报 台北")
    assert r is not None
    assert r.verb == "天气预报"


def test_existing_verb_twins_unchanged() -> None:
    # 对照组：既有简体动词零回归。
    assert RESOLVER.resolve("守岸人点歌 晴天") is not None
    r = RESOLVER.resolve("守岸人天气 台北")
    assert r is not None
    assert r.verb == "天气"


# ---------------------------------------------------------------- 防劫持（陈述句不达昵称路径）


def test_declarative_without_nickname_never_via_alias() -> None:
    # 无昵称前缀 → 昵称路径结构性不可达（前缀本身是强信号）。
    assert RESOLVER.resolve("天气预报说明天下雨") is None


def test_declarative_glued_after_nickname_not_matched() -> None:
    # 动词后必须空白或结尾：胶合陈述句不得当动词吃掉。
    assert RESOLVER.resolve("守岸人天气预报说明天下雨") is None


def test_glued_noun_guard_for_music() -> None:
    assert RESOLVER.resolve("守岸人点唱机坏了") is None


def test_query_form_with_space_is_intended_semantics() -> None:
    # 空白边界恰好区分「问天气」与「陈述句」：带空格=查询语义（既有口径）。
    r = RESOLVER.resolve("守岸人天气预报 明天下雨")
    assert r is not None
    assert r.capability_id == "bot.weather"
    assert r.rest_text == "明天下雨"


# ---------------------------------------------------------------- 端到端路由分类（离线）


@pytest.fixture(autouse=True)
def _clean_route_cache() -> None:
    clear_route_decision_cache()


def _cfg() -> SimpleNamespace:
    return SimpleNamespace(
        bot_music_enabled=True,
        bot_music_candidates_enabled=False,
        bot_weather_enabled=True,
        bot_help_enabled=True,
    )


@pytest.mark.parametrize(
    "text",
    [
        "守岸人点唱",
        "守岸人点唱 晴天",
        "守岸人天气预报",
        "守岸人天气预报 台北",
    ],
)
def test_route_reaches_alias_kind(text: str) -> None:
    decision = classify_message_route(text, config=_cfg(), alias_resolver=RESOLVER)
    assert decision.kind is RouteKind.ALIAS


@pytest.mark.parametrize(
    "text",
    [
        "天气预报说明天下雨",  # 裸陈述句：不经昵称路径
        "守岸人天气预报说明天下雨",  # 胶合陈述句：动词后无空白不匹配
        "守岸人点唱机坏了",
    ],
)
def test_route_does_not_take_alias_path(text: str) -> None:
    decision = classify_message_route(text, config=_cfg(), alias_resolver=RESOLVER)
    assert decision.kind is not RouteKind.ALIAS
