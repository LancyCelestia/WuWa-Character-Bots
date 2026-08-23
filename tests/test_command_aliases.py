from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.runtime.aliases import (
    CommandAliasResolver,
    build_command_alias_resolver,
)


def test_alias_resolver_maps_nickname_commands():
    resolver = CommandAliasResolver(nickname="岸宝")

    assert resolver.resolve("/岸宝帮助") is not None
    assert resolver.resolve("/岸宝帮助").capability_id == "bot.help"
    assert resolver.resolve("/岸宝状态").capability_id == "bot.status"
    assert resolver.resolve("/岸宝为什么").capability_id == "bot.why"
    assert resolver.resolve("/岸宝为啥").capability_id == "bot.why"


def test_alias_resolver_long_verb_wins():
    resolver = CommandAliasResolver(nickname="岸宝")

    resolution = resolver.resolve("/岸宝清理历史")
    assert resolution is not None
    assert resolution.capability_id == "bot.history"
    assert resolution.verb == "清理历史"


def test_alias_resolver_rest_text():
    resolver = CommandAliasResolver(nickname="岸宝")

    resolution = resolver.resolve("/岸宝为什么 今天为什么不理我")
    assert resolution is not None
    assert resolution.capability_id == "bot.why"
    assert resolution.rest_text == "今天为什么不理我"


def test_alias_resolver_ignores_plain_chat_and_other_prefixes():
    resolver = CommandAliasResolver(nickname="岸宝")

    assert resolver.resolve("今天天气怎么样") is None
    assert resolver.resolve("/bot status") is None
    assert resolver.resolve("/守岸人帮助") is None
    assert resolver.resolve("") is None


def test_alias_resolver_disabled_without_nickname():
    resolver = CommandAliasResolver(nickname="")
    assert resolver.resolve("/岸宝帮助") is None


def test_build_alias_resolver_from_config():
    config = Config(bot_runtime_persona_nickname="岸宝")
    resolver = build_command_alias_resolver(config)

    assert resolver.nicknames == ["岸宝"]
    assert resolver.resolve("/岸宝帮助").capability_id == "bot.help"

    multi_config = Config(
        bot_runtime_persona_nicknames=["岸宝", "守岸人"],
    )
    multi_resolver = build_command_alias_resolver(multi_config)
    assert multi_resolver.nicknames == ["岸宝", "守岸人"]
    assert multi_resolver.resolve("/守岸人状态").capability_id == "bot.status"
    assert multi_resolver.resolve("/岸宝为什么").capability_id == "bot.why"

    empty_config = Config()
    assert build_command_alias_resolver(empty_config).nicknames == []


def test_alias_resolver_maps_feature_commands_and_rest_text():
    resolver = CommandAliasResolver(nickname="岸宝")

    assert resolver.resolve("/岸宝天气 杭州").capability_id == "bot.weather"
    assert resolver.resolve("/岸宝天气 杭州").rest_text == "杭州"
    assert resolver.resolve("/岸宝点歌 晴天").capability_id == "bot.music"
    assert resolver.resolve("/岸宝点歌 晴天").rest_text == "晴天"
    assert resolver.resolve("/岸宝wiki 鸣潮").capability_id == "bot.wiki"
    assert resolver.resolve("/岸宝Wikipedia 鸣潮").capability_id == "bot.wiki"
    assert resolver.resolve("/岸宝维基百科 鸣潮").capability_id == "bot.wiki"
    assert resolver.resolve("/岸宝epic").capability_id == "bot.epic"
    assert resolver.resolve("/岸宝EPICFREE").capability_id == "bot.epic"
    assert resolver.resolve("/岸宝历史上的今天").capability_id == "bot.today_history"
    assert resolver.resolve("/岸宝订阅 添加 https://space.bilibili.com/1").capability_id == "bot.subscribe"


def test_alias_resolver_ascii_verbs_are_case_insensitive():
    resolver = CommandAliasResolver(nickname="岸宝")

    assert resolver.resolve("/岸宝HELP").capability_id == "bot.help"
    assert resolver.resolve("/岸宝WiKi 鸣潮").capability_id == "bot.wiki"


def test_alias_resolver_accepts_commands_without_slash():
    resolver = CommandAliasResolver(nickname="守岸人")

    assert resolver.resolve("守岸人帮助").capability_id == "bot.help"
    assert resolver.resolve("守岸人查询").capability_id == "bot.status"
    assert resolver.resolve("守岸人查询天气 杭州").capability_id == "bot.weather"
    assert resolver.resolve("守岸人查询天气 杭州").rest_text == "杭州"
    assert resolver.resolve("守岸人天气 杭州").capability_id == "bot.weather"


def test_alias_resolver_long_query_verbs_win():
    resolver = CommandAliasResolver(nickname="守岸人")

    assert resolver.resolve("守岸人查询天气 杭州").capability_id == "bot.weather"
    assert resolver.resolve("守岸人查询订阅").capability_id == "bot.subscribe"
    assert resolver.resolve("守岸人查询日志").capability_id == "bot.logs"


def test_alias_resolver_does_not_treat_plain_chat_as_command():
    resolver = CommandAliasResolver(nickname="守岸人")

    assert resolver.resolve("守岸人 你好") is None
    assert resolver.resolve("守岸人，今天天气怎么样") is None


def test_both_nickname_prefixes_work_with_and_without_slash():
    resolver = CommandAliasResolver(nicknames=["守岸人", "岸宝"])

    assert resolver.resolve("/守岸人帮助").capability_id == "bot.help"
    assert resolver.resolve("守岸人帮助").capability_id == "bot.help"
    assert resolver.resolve("/岸宝帮助").capability_id == "bot.help"
    assert resolver.resolve("岸宝帮助").capability_id == "bot.help"
    assert resolver.resolve("/岸宝查询天气 杭州").capability_id == "bot.weather"
    assert resolver.resolve("守岸人查询天气 杭州").rest_text == "杭州"


def test_config_accepts_share_group_names():
    from plugins.bot_unified_runtime.config import Config

    config = Config(
        bot_share_groups=["A and B", "A and B and C"],
    )
    assert config.bot_share_groups == ["A and B", "A and B and C"]

def test_config_accepts_share_group_names_from_env_strings():
    from plugins.bot_unified_runtime.config import Config

    assert Config(bot_share_groups='["A and B", "A and B and C"]').bot_share_groups == ["A and B", "A and B and C"]
    assert Config(bot_share_groups="A and B, A and B and C").bot_share_groups == ["A and B", "A and B and C"]
    assert Config(bot_share_groups="[]").bot_share_groups == []


def test_meme_library_alias_with_and_without_slash_and_name():
    from plugins.bot_unified_runtime.runtime.aliases import CommandAliasResolver

    resolver = CommandAliasResolver(nickname="岸宝", nicknames=["岸宝", "守岸人"])
    for text in ["/岸宝偷表情", "岸宝偷表情", "守岸人偷表情包", "/岸宝表情库统计"]:
        resolution = resolver.resolve(text)
        assert resolution is not None, text
        assert resolution.capability_id == "bot.meme_library", (text, resolution)
