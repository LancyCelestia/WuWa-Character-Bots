"""weather 陈述句守卫回归锁（ORDER-FIX 探针移交：天气预报说明天下雨 → chat）。

「天气预报说明天下雨」是陈述句（天气预报说：明天下雨），不是
「天气 <城市>」查询；此前 query=「说明天下雨」被当地名喂进变体链，
NMC/Open-Meteo geocoding 必败。修法：陈述引导词守卫（只动触发判定与
地名提取，能力逻辑零改动），两层提取点同守卫：
1. weather 触发层：查询词以陈述引导词（预报说/听说/据说/消息称…含繁体）
   开头 → 非地名候选；「天气预报/天氣預報」后无空格紧跟「说/称」→ 陈述句式
   （「天气预报 称多」带空格的县名查询不受影响）。
2. 自然语言层（natural_language._clean_city，经 weather.is_statement_lead
   共享同一守卫）：weather 基层路由让位后，自然语言 weather 问法曾把
   「预报说明天下雨」整段当地名归一化成「天气 预报说明天下雨」（二阶劫持，
   探针全清所必需）；正常自然问法（帮我查台北天气/香港天气）零回归。
正常查询与 F18 变体链零回归；「明天会下雨吗」类问句行为不变。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.capabilities.weather import (
    _WEATHER_RE,
    _query_variants,
    is_weather_command,
)
from plugins.bot_unified_runtime.runtime.base_router import (
    RouteKind,
    classify_message_route,
    clear_route_decision_cache,
)
from plugins.bot_unified_runtime.runtime.natural_language import detect_natural_command

# 陈述句样例（probe 样例「天气预报说明天下雨」+ 同族变体，含繁體同款句式）。
STATEMENT_SAMPLES: list[str] = [
    "天气预报说明天下雨",
    "天氣預報說明天氣不錯",
    "听天气预报说周五有雨",
    "天气预报说台风要来",
    "天气 听说台北要下雨",
    "天气预报称明天台风登陆",
]

# 正常查询对照（照既有口径：is_weather_command 预期 + 路由落点）。
NORMAL_TRIGGER_SAMPLES: list[str] = [
    "天气 台北",
    "天气 上海",
    "天气预报 台北",
    "天氣預報 台北",
    "查天气 杭州",
    "weather tokyo",
]


def _route(text: str) -> RouteKind:
    clear_route_decision_cache()
    try:
        return classify_message_route(
            text, config=SimpleNamespace(), alias_resolver=None
        ).kind
    finally:
        clear_route_decision_cache()


@pytest.mark.parametrize("sample", STATEMENT_SAMPLES)
def test_statement_sample_does_not_trigger_weather(sample: str) -> None:
    assert is_weather_command(sample) is False, f"陈述句仍被 weather 抢走：{sample!r}"


@pytest.mark.parametrize("sample", STATEMENT_SAMPLES)
def test_statement_sample_routes_to_chat(sample: str) -> None:
    """路由级：陈述句应落 chat（probe 预期落点）。"""
    kind = _route(sample)
    assert kind is RouteKind.CHAT, f"{sample!r} 预期落 chat，实得 {kind.value}"


@pytest.mark.parametrize("sample", NORMAL_TRIGGER_SAMPLES)
def test_normal_query_still_triggers(sample: str) -> None:
    assert is_weather_command(sample) is True, f"正常查询回归：{sample!r} 不再触发"


@pytest.mark.parametrize("sample", NORMAL_TRIGGER_SAMPLES)
def test_normal_query_routes_to_weather(sample: str) -> None:
    assert _route(sample) is RouteKind.WEATHER, f"正常查询路由回归：{sample!r}"


def test_forecast_with_city_parses_clean_query() -> None:
    """带城市的前置触发照旧直接解析出城市（守卫不得吃掉 query）。"""
    for text, city in (("天气预报 台北", "台北"), ("天氣預報 台北", "台北")):
        match = _WEATHER_RE.match(text)
        assert match is not None
        assert match.group("query") == city


def test_natural_suffix_and_question_forms_unchanged() -> None:
    """「香港天气」既有口径不归 weather（NATURAL_COMMAND 接）；问句落 chat 不变。"""
    assert is_weather_command("香港天气") is False
    assert _route("香港天气") is not RouteKind.WEATHER
    assert _route("明天会下雨吗") is RouteKind.CHAT


# ---------------------------------------------------------------- 自然语言层（二阶提取点）


@pytest.mark.parametrize("sample", STATEMENT_SAMPLES)
def test_natural_layer_does_not_normalize_statement(sample: str) -> None:
    """基层 weather 让位后，自然语言层不得把陈述句当地名归一化成天气命令。"""
    assert detect_natural_command(sample) is None, (
        f"自然语言层仍把陈述句归一化为天气命令：{sample!r}"
    )


def test_natural_layer_normal_queries_unbroken() -> None:
    """正常自然问法零回归：礼貌式/城市后缀式照旧归一化。"""
    resolution = detect_natural_command("帮我查台北天气")
    assert resolution is not None
    assert resolution.capability_id == "bot.weather"
    assert resolution.normalized_text == "天气 台北"
    resolution_suffix = detect_natural_command("香港天气")
    assert resolution_suffix is not None
    assert resolution_suffix.normalized_text == "天气 香港"


# ---------------------------------------------------------------- F18 变体链


def test_f18_variant_chain_unbroken() -> None:
    assert is_weather_command("天气 湘潭-雨湖") is True
    assert is_weather_command("天气 湘潭 雨湖") is True
    assert is_weather_command("天气 河北-大城") is True
    assert _query_variants("湘潭 雨湖") == ["湘潭 雨湖", "湘潭雨湖", "雨湖"]
    assert _query_variants("河北-大城") == ["河北-大城", "河北大城", "大城"]


def test_district_named_chengduo_not_blocked() -> None:
    """青海称多县：带空格查询不得被「预报称」守卫误杀。"""
    assert is_weather_command("天气 称多") is True
    assert is_weather_command("天气预报 称多") is True
