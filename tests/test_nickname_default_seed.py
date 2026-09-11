"""昵称词表兜底与叫应链路回归（2026-09-11「岸宝叫不应」根因修复）。

根因：personas/<profile>/aliases.txt 长期无代码消费，昵称词表全靠 env，
生产未配置 BOT_PERSONA_NICKNAMES 时策展昵称全部缺席，群内称呼走闲聊抽签近乎静默。
修复：aliases.txt 真正接线 + 官方策展昵称硬编码兜底 + 去重保序。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from plugins.bot_unified_runtime.runtime.aliases import (
    DEFAULT_PERSONA_NICKNAMES,
    build_command_alias_resolver,
)
from plugins.bot_unified_runtime.runtime.mentions import detect_name_mention


def _config(**extra: object) -> SimpleNamespace:
    base = {
        "bot_persona_profile_id": "shorekeeper",
        "bot_persona_nicknames": [],
        "bot_runtime_persona_nickname": "",
        "bot_runtime_persona_nicknames": [],
        "bot_runtime_instance": "default",
    }
    base.update(extra)
    return SimpleNamespace(**base)


def test_default_nicknames_seeded_without_env() -> None:
    resolver = build_command_alias_resolver(_config())
    for name in (
        "岸宝",
        "守岸人",
        "小岸同学",
        "我的蒙娜丽莎",
        "第二实例",
        "蓝蝴蝶",
        "花房的守护者",
        "漂泊的终点",
        "独属于我的蒙娜丽莎",
    ):
        assert name in resolver.nicknames, (name, resolver.nicknames)


def test_default_seed_matches_persona_file() -> None:
    # aliases.txt 与 DEFAULT_PERSONA_NICKNAMES 必须同齐（09-12 对齐生产 .env 的 9 个）。
    persona_file = (
        Path(__file__).resolve().parents[1] / "personas" / "shorekeeper" / "aliases.txt"
    )
    names = [n for n in persona_file.read_text(encoding="utf-8").split("|") if n]
    assert sorted(names) == sorted(DEFAULT_PERSONA_NICKNAMES)


def test_env_config_override_wins_over_defaults() -> None:
    resolver = build_command_alias_resolver(
        _config(bot_persona_nicknames=["自定义昵称"])
    )
    # env 配置追加在最前（优先用于命令解析），人格 aliases.txt 的名字继续生效。
    assert resolver.nicknames[0] == "自定义昵称"
    assert "守岸人" in resolver.nicknames


def test_resolver_still_parses_nickname_commands() -> None:
    resolver = build_command_alias_resolver(_config())
    resolution = resolver.resolve("岸宝天气")
    assert resolution is not None
    assert resolution.capability_id == "bot.weather"


def test_persona_file_names_are_detectable_mentions() -> None:
    terms = list(DEFAULT_PERSONA_NICKNAMES)
    assert detect_name_mention("岸宝，帮我查天气", terms)
    assert detect_name_mention("守岸人 今天天气怎么样", terms)
    assert detect_name_mention("大家晚上好，我的蒙娜丽莎，在吗？", terms)
    assert detect_name_mention("呼叫第二实例", terms)
    assert detect_name_mention("岸宝", terms)
    assert detect_name_mention("漂泊的终点，终于等到你", terms)
    assert detect_name_mention("独属于我的蒙娜丽莎，在吗？", terms)
    # 包含关系词不误触发（保守边界语义保持）。
    assert not detect_name_mention("岸宝贝真可爱", terms)
    assert not detect_name_mention("这个守岸人设真不错", terms)
    assert not detect_name_mention("你就是我的蒙娜丽莎画作", terms)
