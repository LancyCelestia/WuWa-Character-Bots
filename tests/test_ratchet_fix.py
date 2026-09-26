"""Ratchet 台账剩余 11 处真实违规清零回归（tests/test_trigger_spec.py 棘轮）。

跨能力冲突 ×4：mode 词族裸词（点歌模式/點歌模式/music mode/song mode）
唯一命中 bot.music_mode（模式选择归点歌模式子命令，裸「点歌」归点歌主命令）；
带歌名/参数后继形态（music mode link / 點歌模式 卡片）保持
music_mode+music 双命中让路对——既有形态零改动，
test_trigger_english.PRIORITY_PAIRS 同口径，由 base_router 优先级裁定。

ASCII 右侧胶合 ×7：<word>qq 类字母延续不得命中自身能力
（_alias_hit 词边界纪律，wiki/moegirl/eat/today_history 先例：
IGNORECASE 正则用 ``(?![a-z0-9])``；weather 无 IGNORECASE，用
``(?![A-Za-z0-9])``）。
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.capabilities.affinity import (
    is_affinity_command,
)
from plugins.bot_unified_runtime.domains.meme.capabilities.meme import is_meme_command
from plugins.bot_unified_runtime.domains.meme.capabilities.meme_library import (
    is_meme_library_command,
)
from plugins.bot_unified_runtime.domains.music.capabilities.music import (
    is_music_command,
    is_music_mode_command,
)
from plugins.bot_unified_runtime.domains.weather.capabilities.weather import (
    is_weather_command,
)

# ---------------------------------------------------------------------------
# 跨能力冲突 ×4：mode 词族裸词唯一归 bot.music_mode
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "probe",
    ["点歌模式", "點歌模式", "music mode", "song mode"],
)
def test_mode_phrase_unique_to_music_mode(probe: str) -> None:
    """mode 词族裸词唯一归点歌模式子命令，点歌主命令不再抢匹配。"""
    assert is_music_mode_command(probe), f"{probe!r} 应命中点歌模式"
    assert not is_music_command(probe), f"{probe!r} 仍被点歌主命令抢匹配"


@pytest.mark.parametrize(
    "probe",
    ["music mode link", "點歌模式 卡片"],
)
def test_mode_phrase_with_payload_dual_hit_unchanged(probe: str) -> None:
    """带歌名/参数后继的 mode 形态保持双命中让路对（既有形态零改动）。"""
    assert is_music_mode_command(probe)
    assert is_music_command(probe), f"{probe!r} 的点歌主命令让路形态被误伤"


# ---------------------------------------------------------------------------
# ASCII 右侧胶合 ×7：<word>qq 类字母延续不得命中自身能力
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("capability", "detector", "glued"),
    [
        ("bot.affinity", is_affinity_command, "affinityqq"),
        ("bot.meme", is_meme_command, "meme generateqq"),
        ("bot.meme_library", is_meme_library_command, "meme randomqq"),
        ("bot.meme_library", is_meme_library_command, "steal memeqq"),
        ("bot.music", is_music_command, "musicqq"),
        ("bot.music", is_music_command, "songqq"),
        ("bot.weather", is_weather_command, "weatherqq"),
    ],
    ids=lambda x: str(x),
)
def test_ascii_right_glue_does_not_fire(
    capability: str, detector: Callable[[str], bool], glued: str
) -> None:
    """胶合探针不得命中自身能力（_alias_hit 词边界纪律）。"""
    assert not detector(glued), f"{capability} 对胶合探针 {glued!r} 仍裸子串命中"


# ---------------------------------------------------------------------------
# 既有真命令触发照旧（回归零改动）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("capability", "detector", "sample"),
    [
        ("bot.affinity", is_affinity_command, "affinity"),
        ("bot.affinity", is_affinity_command, "亲密度"),
        ("bot.affinity", is_affinity_command, "親密度"),
        ("bot.affinity", is_affinity_command, "好感度 算法"),
        ("bot.meme", is_meme_command, "meme"),
        ("bot.meme", is_meme_command, "memes"),
        ("bot.meme", is_meme_command, "meme generate"),
        ("bot.meme", is_meme_command, "meme petpet 可爱"),
        ("bot.meme_library", is_meme_library_command, "steal"),
        ("bot.meme_library", is_meme_library_command, "steal meme"),
        ("bot.meme_library", is_meme_library_command, "meme random"),
        ("bot.meme_library", is_meme_library_command, "表情库统计"),
        ("bot.music", is_music_command, "点歌 晴天"),
        ("bot.music", is_music_command, "點唱 晴天"),
        ("bot.music", is_music_command, "music november rain"),
        ("bot.music", is_music_command, "song hotel california"),
        ("bot.weather", is_weather_command, "weather Tokyo"),
        ("bot.weather", is_weather_command, "天气 上海"),
    ],
    ids=lambda x: str(x),
)
def test_real_commands_still_fire(
    capability: str, detector: Callable[[str], bool], sample: str
) -> None:
    """既有触发零改动：修复只收窄胶合/冲突形态，真命令一律照旧。"""
    assert detector(sample), f"{capability} 既有触发 {sample!r} 失效"
