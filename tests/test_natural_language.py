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
