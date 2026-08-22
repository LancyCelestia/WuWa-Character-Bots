from plugins.bot_unified_runtime.capabilities.epic import (
    build_epic_capability,
    is_epic_command,
)
from plugins.bot_unified_runtime.capabilities.wiki import (
    build_wiki_capability,
    extract_wiki_query,
    is_wiki_command,
)
from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.sources.epicfree import format_epic_free_games
from plugins.bot_unified_runtime.sources.mediawiki import (
    wiki_lookup,
    wiki_search,
    wiki_summary,
)


def _message(text: str) -> IncomingMessage:
    return IncomingMessage(
        platform="test",
        adapter="test",
        bot_id="bot",
        session_id="s1",
        session_type=SessionType.PRIVATE,
        sender_id="u1",
        plain_text=text,
        raw_segments=[{"type": "text", "data": {"text": text}}],
        mentions_bot=True,
    )


def test_wiki_command_parsing():
    assert is_wiki_command("维基 鸣潮")
    assert is_wiki_command("wiki wuthering waves")
    assert is_wiki_command("维基百科 量子力学")
    assert extract_wiki_query("维基 鸣潮") == "鸣潮"
    assert not is_wiki_command("维基")


def test_wiki_search_and_summary(monkeypatch):
    from plugins.bot_unified_runtime.sources import mediawiki

    def fake_http_get_json(url, **kwargs):
        if "opensearch" in url:
            return ["鸣潮", ["鸣潮角色列表"], ["desc"], ["https://zh.wikipedia.org/wiki/鸣潮角色列表"]]
        return {
            "query": {
                "pages": [
                    {
                        "title": "鸣潮角色列表",
                        "extract": "《鸣潮》世界观里登场的共鸣者。",
                    }
                ]
            }
        }

    monkeypatch.setattr(mediawiki, "http_get_json", fake_http_get_json)

    titles = wiki_search("鸣潮")
    assert titles == ["鸣潮角色列表"]
    summary = wiki_summary("鸣潮角色列表")
    assert "共鸣者" in summary
    result = wiki_lookup("鸣潮")
    assert result is not None and result.startswith("鸣潮角色列表")


def test_wiki_capability_result(monkeypatch):
    from plugins.bot_unified_runtime.capabilities import wiki as wiki_module

    monkeypatch.setattr(
        wiki_module,
        "wiki_lookup",
        lambda query, **kwargs: f"{query}\n简介内容\n链接：https://zh.wikipedia.org/wiki/{query}",
    )

    capability = build_wiki_capability()
    result = capability(_message("维基 鸣潮"), None)

    assert result.capability_id == "bot.wiki"
    assert "简介内容" in result.body


def test_wiki_capability_not_found(monkeypatch):
    from plugins.bot_unified_runtime.capabilities import wiki as wiki_module

    monkeypatch.setattr(wiki_module, "wiki_lookup", lambda query, **kwargs: None)

    capability = build_wiki_capability()
    result = capability(_message("维基 不存在的词条"), None)

    assert "not_found" in result.audit_tags


def test_epic_command_parsing():
    assert is_epic_command("epic")
    assert is_epic_command("Epic 免费")
    assert not is_epic_command("epic games")


def test_epic_format():
    text = format_epic_free_games(
        [
            {
                "title": "测试游戏",
                "status": "免费中",
                "start": "08-21 15:00",
                "end": "08-28 15:00",
                "url": "https://store.epicgames.com/zh-CN/p/test",
            }
        ]
    )
    assert "测试游戏" in text
    assert "08-28 15:00" in text


def test_epic_capability_result(monkeypatch):
    from plugins.bot_unified_runtime.capabilities import epic as epic_module

    monkeypatch.setattr(
        epic_module,
        "fetch_epic_free_games",
        lambda **kwargs: [
            {"title": "免费游戏A", "status": "免费中", "start": "", "end": "", "url": ""}
        ],
    )

    capability = build_epic_capability()
    result = capability(_message("epic"), None)

    assert result.capability_id == "bot.epic"
    assert "免费游戏A" in result.body


def test_epic_capability_fetch_failure(monkeypatch):
    from plugins.bot_unified_runtime.capabilities import epic as epic_module

    def boom(**kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(epic_module, "fetch_epic_free_games", boom)

    capability = build_epic_capability()
    result = capability(_message("epic"), None)

    assert "fetch_failed" in result.audit_tags
