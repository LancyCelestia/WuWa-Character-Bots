"""自然语言意图识别的确定性规则测试。"""

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.runtime.natural_language import detect_natural_command


def test_weather_ask_with_city():
    resolution = detect_natural_command("杭州天气怎么样", Config())
    assert resolution is not None
    assert resolution.capability_id == "bot.weather"
    assert resolution.normalized_text == "天气 杭州"


def test_weather_polite_prefix_before_city():
    resolution = detect_natural_command("帮我查一下杭州天气", Config())
    assert resolution is not None
    assert resolution.normalized_text == "天气 杭州"


def test_weather_polite_prefix_after_city():
    resolution = detect_natural_command("帮我查天气 杭州", Config())
    assert resolution is not None
    assert resolution.normalized_text == "天气 杭州"


def test_music_natural_phrases():
    for text, query in [
        ("来首晴天", "晴天"),
        ("点一首晴天", "晴天"),
        ("放首歌 晴天", "晴天"),
        ("帮我放一首周杰伦的歌", "周杰伦的歌"),
    ]:
        resolution = detect_natural_command(text, Config())
        assert resolution is not None, text
        assert resolution.capability_id == "bot.music", text
        assert resolution.normalized_text == f"点歌 {query}", text


def test_wiki_natural_with_polite_prefix():
    resolution = detect_natural_command("帮我查维基 鸣潮", Config())
    assert resolution is not None
    assert resolution.capability_id == "bot.wiki"
    assert resolution.normalized_text == "wiki 鸣潮"


def test_epic_and_history_natural():
    epic = detect_natural_command("今天有什么免费游戏", Config())
    assert epic is not None
    assert epic.capability_id == "bot.epic"
    history = detect_natural_command("今天历史上发生了什么", Config())
    assert history is not None
    assert history.capability_id == "bot.today_history"
    assert history.normalized_text == "历史上的今天"


def test_plain_chat_is_not_hijacked():
    for text in [
        "今天天气不错",
        "杭州天气不错",
        "今天天气怎么样",
        "播放量好高",
        "表情包真好笑",
        "守岸人今天好可爱",
    ]:
        assert detect_natural_command(text, Config()) is None, text


def test_disabled_capability_does_not_produce_natural_resolution():
    assert (
        detect_natural_command(
            "杭州天气怎么样", Config(bot_weather_query_enabled=False)
        )
        is None
    )


def test_link_text_never_routes_to_natural_command():
    assert (
        detect_natural_command(
            "帮我查天气 https://example.com", Config()
        )
        is None
    )


def test_music_mode_natural_combos():
    cases = [
        ("点歌只发卡片", "bot.music_mode"),
        ("以后点歌只发卡片和语音", "bot.music_mode"),
        ("点歌输出改成只发链接", "bot.music_mode"),
        ("music mode card+link", "bot.music_mode"),
    ]
    for text, capability in cases:
        resolution = detect_natural_command(text, Config())
        assert resolution is not None, text
        assert resolution.capability_id == capability, (text, resolution)


def test_music_mode_natural_does_not_hijack_song_query():
    resolution = detect_natural_command("点歌 晴天", Config())
    assert resolution is not None
    assert resolution.capability_id == "bot.music"


def test_english_natural_commands():
    weather = detect_natural_command("what's the weather in Hangzhou", Config())
    assert weather is not None and weather.capability_id == "bot.weather"
    music = detect_natural_command("play me a song Sunny Day", Config())
    assert music is not None and music.capability_id == "bot.music"
    wiki = detect_natural_command("wiki Wuthering Waves", Config())
    assert wiki is not None and wiki.capability_id == "bot.wiki"
    epic = detect_natural_command("what free games are there this week", Config())
    assert epic is not None and epic.capability_id == "bot.epic"
    history = detect_natural_command("today in history", Config())
    assert history is not None and history.capability_id == "bot.today_history"
