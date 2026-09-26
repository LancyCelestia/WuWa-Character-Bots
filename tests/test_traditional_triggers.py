"""繁體触发词路由层回归（TRA 草稿三处错位：親密度/天氣預報/點唱）。

数据来源：.superpowers/sdd/2026-09-12-shorekeeper-global-audit/
traditional-mapping-draft.json（错位④/天氣預報/點唱 条目）。
只锁路由层 is_* 判定与查询解析；昵称动词表（DEFAULT_VERB_MAP）不归本文件。
"""

from __future__ import annotations

from plugins.bot_unified_runtime.domains.chat_reply.capabilities.affinity import (
    is_affinity_command,
    parse_affinity_query,
)
from plugins.bot_unified_runtime.domains.music.capabilities.music import (
    extract_music_query,
    is_music_command,
    is_music_mode_command,
)
from plugins.bot_unified_runtime.domains.weather.capabilities.weather import (
    _WEATHER_RE,
    is_weather_command,
)

# ---------------------------------------------------------------- 親密度（错位④）


def test_affinity_traditional_intimacy_routes() -> None:
    assert is_affinity_command("親密度") is True
    assert is_affinity_command("/親密度") is True
    assert is_affinity_command("親密度 算法") is True
    assert parse_affinity_query("親密度 算法") == "算法"


def test_affinity_simplified_control_unchanged() -> None:
    assert is_affinity_command("亲密度") is True
    # 独立成词约束照旧：口语句不得误触。
    assert is_affinity_command("好感消失了") is False


# ---------------------------------------------------------------- 天氣預報（修活）


def test_weather_traditional_forecast_with_city_parses_clean_query() -> None:
    assert is_weather_command("天氣預報 台北") is True
    match = _WEATHER_RE.match("天氣預報 台北")
    assert match is not None
    # 修活核心：query 直接解析出城市，而不是「預報 台北」靠变体链兜底。
    assert match.group("query") == "台北"


def test_weather_traditional_forecast_bare_no_city_no_doomed_lookup() -> None:
    # 裸「天氣預報」此前把「預報」当地名触发必败外呼；与简体「天气预报」同口径拒路由。
    assert is_weather_command("天氣預報") is False


def test_weather_simplified_forecast_family_aligned() -> None:
    assert is_weather_command("天气预报 台北") is True
    match = _WEATHER_RE.match("天气预报 台北")
    assert match is not None
    assert match.group("query") == "台北"
    assert is_weather_command("天气预报") is False


def test_weather_existing_triggers_unchanged() -> None:
    assert is_weather_command("天气 上海") is True
    assert is_weather_command("查天气 上海") is True
    assert is_weather_command("天氣 台北") is True
    assert is_weather_command("天气真好") is False


# ---------------------------------------------------------------- 點唱（补齐）


def test_music_traditional_request_routes() -> None:
    assert is_music_command("點唱 晴天") is True
    assert extract_music_query("點唱 晴天") == "晴天"
    assert is_music_command("/點唱 晴天") is True


def test_music_simplified_twin_added() -> None:
    assert is_music_command("点唱 晴天") is True
    assert extract_music_query("点唱 晴天") == "晴天"


def test_music_traditional_candidate_selection() -> None:
    # 候选二次选择「点歌 2」的繁體同形态也要可达。
    assert is_music_command("點唱 2") is True
    assert extract_music_query("點唱 2") == "2"


def test_music_existing_triggers_unchanged() -> None:
    assert is_music_command("点歌 晴天") is True
    assert is_music_command("點歌 晴天") is True
    assert is_music_command("music 晴天") is True
    # 模式设置路由不受新增触发词影响。
    assert is_music_mode_command("點歌模式 卡片") is True
