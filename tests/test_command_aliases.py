from plugins.wuwa_unified_runtime.config import Config
from plugins.wuwa_unified_runtime.runtime.aliases import (
    CommandAliasResolver,
    build_command_alias_resolver,
)


def test_alias_resolver_maps_nickname_commands():
    resolver = CommandAliasResolver(nickname="岸宝")

    assert resolver.resolve("/岸宝帮助") is not None
    assert resolver.resolve("/岸宝帮助").capability_id == "wuwa.help"
    assert resolver.resolve("/岸宝状态").capability_id == "wuwa.status"
    assert resolver.resolve("/岸宝为什么").capability_id == "wuwa.why"
    assert resolver.resolve("/岸宝为啥").capability_id == "wuwa.why"


def test_alias_resolver_long_verb_wins():
    resolver = CommandAliasResolver(nickname="岸宝")

    resolution = resolver.resolve("/岸宝清理历史")
    assert resolution is not None
    assert resolution.capability_id == "wuwa.history"
    assert resolution.verb == "清理历史"


def test_alias_resolver_rest_text():
    resolver = CommandAliasResolver(nickname="岸宝")

    resolution = resolver.resolve("/岸宝为什么 今天为什么不理我")
    assert resolution is not None
    assert resolution.capability_id == "wuwa.why"
    assert resolution.rest_text == "今天为什么不理我"


def test_alias_resolver_ignores_plain_chat_and_other_prefixes():
    resolver = CommandAliasResolver(nickname="岸宝")

    assert resolver.resolve("今天天气怎么样") is None
    assert resolver.resolve("/wuwa status") is None
    assert resolver.resolve("/守岸人帮助") is None
    assert resolver.resolve("") is None


def test_alias_resolver_disabled_without_nickname():
    resolver = CommandAliasResolver(nickname="")
    assert resolver.resolve("/岸宝帮助") is None


def test_build_alias_resolver_from_config():
    config = Config(wuwa_runtime_persona_nickname="岸宝")
    resolver = build_command_alias_resolver(config)

    assert resolver.nicknames == ["岸宝"]
    assert resolver.resolve("/岸宝帮助").capability_id == "wuwa.help"

    multi_config = Config(
        wuwa_runtime_persona_nicknames=["岸宝", "守岸人"],
    )
    multi_resolver = build_command_alias_resolver(multi_config)
    assert multi_resolver.nicknames == ["岸宝", "守岸人"]
    assert multi_resolver.resolve("/守岸人状态").capability_id == "wuwa.status"
    assert multi_resolver.resolve("/岸宝为什么").capability_id == "wuwa.why"

    empty_config = Config()
    assert build_command_alias_resolver(empty_config).nicknames == []
