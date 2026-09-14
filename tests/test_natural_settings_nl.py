"""审查 C-01：自然语言改设置映射层回归。

覆盖五条验收线：
① 口语矩阵 ≥12 句 → 正确 SETTABLE_KEY + 目标值；
② 映射表外功能词（提醒/笔记/群摘要等真实键不存在的功能）不命中、落回 chat；
③ 一句多功能词 → 取第一个 + ambiguous 标记；
④ FUNCTION_KEY_MAP 目标键全量遍历断言存在于 SETTABLE_KEYS（防漂移）；
⑤ 旧 7 支（weather/music/wiki/epic/today_history/meme_library/music_mode）零变化。

权限红线（与被测模块 docstring 同口径）：映射层只识别不授权，
派发层必须走 build_runtime_admin_result 既有管理员门——本文件断言
admin_required 载荷位为 True，作为该契约的机器可读形式。
"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.runtime.natural_language import (
    FUNCTION_KEY_MAP,
    SETTING_CAPABILITY_ID,
    detect_natural_command,
)
from plugins.bot_unified_runtime.runtime.settings import SETTABLE_KEYS

# ---- ① 口语矩阵：把/将/帮我 X 功能 开/关/打开/关闭/关掉/启用/停用 ----

@pytest.mark.parametrize(
    ("utterance", "expected_key", "expected_value"),
    [
        ("把识图关掉", "BOT_VISION_ENABLED", "false"),
        ("帮我把识图打开", "BOT_VISION_ENABLED", "true"),
        ("把识图功能关掉", "BOT_VISION_ENABLED", "false"),
        ("关闭视频理解", "BOT_VIDEO_UNDERSTANDING_ENABLED", "false"),
        ("开启安静时间", "BOT_QUIET_HOURS_ENABLED", "true"),
        ("请禁用戳一戳", "BOT_POKE_ENABLED", "false"),
        ("把戳一戳回话停用", "BOT_POKE_REPLY_ENABLED", "false"),
        ("把回戳关掉", "BOT_POKE_POKE_BACK", "false"),
        ("打开快速模式", "BOT_CHAT_FAST_MODE", "true"),
        ("把记忆抽取关掉吧", "BOT_MEMORY_EXTRACT_ENABLED", "false"),
        ("將識圖關掉", "BOT_VISION_ENABLED", "false"),
        ("把网页搜索停用", "BOT_WEB_SEARCH_ENABLED", "false"),
        ("启用语音识别", "BOT_ASR_ENABLED", "true"),
        ("把语音识别功能关掉", "BOT_ASR_ENABLED", "false"),
        ("把梗搜索关掉", "BOT_MEME_SEARCH_ENABLED", "false"),
        ("把动作括号打开", "BOT_PERSONA_ACTION_BRACKETS", "true"),
        ("把视频深度理解关掉", "BOT_VIDEO_DEEP_ENABLED", "false"),
        ("关闭群聊自动回复", "BOT_GROUP_CHAT_AUTO_REPLY_ENABLED", "false"),
        ("把自动接话功能打开", "BOT_GROUP_CHAT_AUTO_REPLY_ENABLED", "true"),
    ],
)
def test_spoken_matrix_maps_to_key_and_value(
    utterance: str, expected_key: str, expected_value: str
) -> None:
    resolution = detect_natural_command(utterance)
    assert resolution is not None, f"应命中设置意图：{utterance}"
    assert resolution.capability_id == SETTING_CAPABILITY_ID
    assert resolution.setting_key == expected_key
    assert resolution.setting_value == expected_value
    assert resolution.normalized_text == f"/bot runtime set {expected_key} {expected_value}"
    assert resolution.admin_required is True, "权限红线：设置意图必须携带管理员门标记"
    assert resolution.source_text == utterance
    assert resolution.ambiguous is False


def test_synonym_long_word_not_flagged_ambiguous() -> None:
    # 「群聊自动回复」内含「自动回复」：长词覆盖短词，不得误报歧义。
    resolution = detect_natural_command("关闭群聊自动回复")
    assert resolution is not None
    assert resolution.ambiguous is False
    assert resolution.setting_key == "BOT_GROUP_CHAT_AUTO_REPLY_ENABLED"


# ---- ② 映射表外功能词：不命中，落回 chat ----

@pytest.mark.parametrize(
    "utterance",
    [
        # 真实键不在 SETTABLE_KEYS 的功能：诚实不映射（宁落回 chat 不假映射）。
        "把提醒功能关掉",
        "关闭快报",
        "把天气关掉",
        "关闭群摘要",
        "帮我把笔记关掉",
        "关闭搜图",
        "把表情回应停用",
        # 槽内夹带未知实体 / 无对象 / 纯闲聊。
        "把识图结果关掉",
        "把识图有关的东西关掉",
        "关闭它",
        "把心关上",
        "关闭朋友圈",
        "帮我把这个功能关掉",
    ],
)
def test_unmapped_feature_words_fall_through_to_chat(utterance: str) -> None:
    assert detect_natural_command(utterance) is None, (
        f"映射表外功能词不得命中设置意图：{utterance}"
    )


# ---- ③ 一句多功能词：取第一个 + ambiguous 标记 ----

def test_multiple_feature_words_take_first_and_flag_ambiguous() -> None:
    resolution = detect_natural_command("把识图和视频理解都关掉")
    assert resolution is not None
    assert resolution.ambiguous is True
    assert resolution.setting_key == "BOT_VISION_ENABLED"
    assert resolution.setting_value == "false"


def test_multiple_feature_words_verb_first_order() -> None:
    resolution = detect_natural_command("关闭识图和安静时间")
    assert resolution is not None
    assert resolution.ambiguous is True
    assert resolution.setting_key == "BOT_VISION_ENABLED"


# ---- ④ 防漂移：映射表目标键必须全量存在于 SETTABLE_KEYS ----

def test_function_key_map_keys_all_exist_in_settable_keys() -> None:
    assert FUNCTION_KEY_MAP, "映射表不应为空"
    for word, (key, label) in FUNCTION_KEY_MAP.items():
        assert key in SETTABLE_KEYS, (
            f"功能词 {word!r} 映射到 SETTABLE_KEYS 之外的键 {key!r}（防漂移红线）"
        )
        assert SETTABLE_KEYS[key] is not None
        assert label, f"功能词 {word!r} 缺少展示名"


def test_function_key_map_values_are_boolean_toggle_keys() -> None:
    # 映射层只收布尔开关键：口语开/关方向必须能被 _bool_converter 解析。
    from plugins.bot_unified_runtime.runtime.settings import _bool_converter

    for word, (key, _label) in FUNCTION_KEY_MAP.items():
        assert SETTABLE_KEYS[key] is _bool_converter, (
            f"功能词 {word!r} 映射到非布尔开关键 {key!r}"
        )


# ---- ⑤ 旧 7 支零变化 ----

def test_legacy_seven_branches_unchanged() -> None:
    weather = detect_natural_command("帮我查台北天气")
    assert weather is not None and weather.capability_id == "bot.weather"
    assert weather.setting_key is None and weather.admin_required is False

    music = detect_natural_command("来首晴天")
    assert music is not None and music.capability_id == "bot.music"
    wiki = detect_natural_command("wiki 鸣潮")
    assert wiki is not None and wiki.capability_id == "bot.wiki"
    epic = detect_natural_command("这周有什么免费游戏")
    assert epic is not None and epic.capability_id == "bot.epic"
    history = detect_natural_command("今天历史上发生了什么")
    assert history is not None and history.capability_id == "bot.today_history"

    # music_mode 归一化分支不受设置分支抢占（「设置成」不是开关动词，不入设置）。
    mode = detect_natural_command("点歌模式设置成卡片和语音")
    assert mode is not None and mode.capability_id == "bot.music_mode"
    assert mode.setting_key is None

    # 闲聊/陈述句依旧不进任何命令分支。
    assert detect_natural_command("今天天气不错") is None
    assert detect_natural_command("幫我看看這個") is None
    assert detect_natural_command("把心关上") is None


def test_runtime_set_command_text_format() -> None:
    """C-02 契约：映射结果拼成 runtime set 子命令体，派发层直喂管理员门。"""
    from plugins.bot_unified_runtime.runtime.natural_language import (
        runtime_set_command_text,
    )

    assert (
        runtime_set_command_text("BOT_VISION_ENABLED", "true")
        == "runtime set BOT_VISION_ENABLED true"
    )
    assert (
        runtime_set_command_text("  BOT_ASR_ENABLED  ", " false ")
        == "runtime set BOT_ASR_ENABLED false"
    )
