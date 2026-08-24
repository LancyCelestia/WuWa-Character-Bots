from plugins.bot_unified_runtime.capabilities.chat import build_chat_prompt
from plugins.bot_unified_runtime.character.glossary import (
    FileGlossaryProvider,
    _parse_entry_line,
)
from plugins.bot_unified_runtime.character.providers import FileCharacterContextProvider
from plugins.bot_unified_runtime.character.relationship import (
    FileRelationshipProvider,
    apply_relationship_to_tone,
)
from plugins.bot_unified_runtime.character.shared_group import (
    NullSharedGroupContextProvider,
)
from plugins.bot_unified_runtime.contracts.character import (
    SharedGroupContext,
)


def test_parse_entry_line_formats():
    assert _parse_entry_line("声骸：鸣潮中的核心养成系统") == (
        "声骸",
        "鸣潮中的核心养成系统",
    )
    assert _parse_entry_line("**黑海岸**：游戏中的主要势力之一") == (
        "黑海岸",
        "游戏中的主要势力之一",
    )
    assert _parse_entry_line("鸣潮|由库洛开发的开放世界动作游戏") == (
        "鸣潮",
        "由库洛开发的开放世界动作游戏",
    )
    assert _parse_entry_line("# 这是标题") is None
    assert _parse_entry_line("没有分隔符的一行") is None


def test_file_glossary_provider_loads_entries(tmp_path):
    glossary_file = tmp_path / "glossary.md"
    glossary_file.write_text(
        "声骸：核心养成系统\n**黑海岸**：主要势力\n共鸣者：觉醒异能之人\n",
        encoding="utf-8",
    )
    provider = FileGlossaryProvider([glossary_file], max_entries=10, max_chars=800)

    context = provider.load("req_glossary")

    assert [entry.term for entry in context.entries] == ["声骸", "黑海岸", "共鸣者"]


def test_glossary_injected_into_prompt(tmp_path):
    persona_file = tmp_path / "shorekeeper.md"
    persona_file.write_text(
        "来自黑海岸的守岸人，温柔、克制、可靠。\n说话语气要安静温柔。",
        encoding="utf-8",
    )
    glossary_file = tmp_path / "glossary.md"
    glossary_file.write_text("声骸：核心养成系统\n", encoding="utf-8")
    provider = FileCharacterContextProvider(
        persona_profile_id="shorekeeper",
        persona_display_name="守岸人",
        persona_version="test",
        persona_files=[persona_file],
        knowledge_files=[],
        glossary_provider=FileGlossaryProvider([glossary_file]),
    )
    bundle = provider.build_context(
        request_id="req_glossary",
        sender_id="42",
        session_id="private:42",
        query_text="声骸是什么？",
    )
    prompt_text = "\n".join(
        message["content"] for message in build_chat_prompt(bundle)
    )

    assert "世界观与专有名词" in prompt_text
    assert "声骸" in prompt_text
    assert "核心养成系统" in prompt_text


def test_relationship_profile_and_tone_adjustment(tmp_path):
    profile_file = tmp_path / "profiles.json"
    profile_file.write_text(
        '{"users": {"42": {"label": "小岸", "familiarity": "close", '
        '"affinity": 0.9, "preferences": ["喜欢简短回复"], '
        '"notes": ["最近在学配队"]}}}',
        encoding="utf-8",
    )
    provider = FileRelationshipProvider(profile_file)

    known = provider.load("req_rel", "42")
    stranger = provider.load("req_rel", "99")

    assert known.familiarity == "close"
    assert known.user_label == "小岸"
    assert known.preferences == ["喜欢简短回复"]
    assert stranger.familiarity == "stranger"

    warmth, directness = apply_relationship_to_tone(0.7, 0.5, known)
    assert warmth > 0.7
    assert directness < 0.5
    unchanged = apply_relationship_to_tone(0.7, 0.5, stranger)
    assert unchanged == (0.7, 0.5)


def test_relationship_injected_into_prompt(tmp_path):
    persona_file = tmp_path / "shorekeeper.md"
    persona_file.write_text("来自黑海岸的守岸人。\n说话语气要安静温柔。", encoding="utf-8")
    profile_file = tmp_path / "profiles.json"
    profile_file.write_text(
        '{"users": {"42": {"label": "小岸", "familiarity": "familiar", '
        '"affinity": 0.8}}}',
        encoding="utf-8",
    )
    provider = FileCharacterContextProvider(
        persona_profile_id="shorekeeper",
        persona_display_name="守岸人",
        persona_version="test",
        persona_files=[persona_file],
        knowledge_files=[],
        relationship_provider=FileRelationshipProvider(profile_file),
    )
    bundle = provider.build_context(
        request_id="req_rel",
        sender_id="42",
        session_id="private:42",
        query_text="在吗？",
    )
    prompt_text = "\n".join(
        message["content"] for message in build_chat_prompt(bundle)
    )

    assert "对当前用户：" in prompt_text
    assert "小岸" in prompt_text
    assert "familiar" in prompt_text


def test_shared_group_context_off_by_default():
    provider = NullSharedGroupContextProvider()

    context = provider.load("req_shared", "group:1", "42")

    assert isinstance(context, SharedGroupContext)
    assert context.enabled is False
    assert context.summary == ""


def test_shared_group_section_skipped_when_disabled(tmp_path):
    persona_file = tmp_path / "shorekeeper.md"
    persona_file.write_text("来自黑海岸的守岸人。\n说话语气要安静温柔。", encoding="utf-8")
    provider = FileCharacterContextProvider(
        persona_profile_id="shorekeeper",
        persona_display_name="守岸人",
        persona_version="test",
        persona_files=[persona_file],
        knowledge_files=[],
        shared_group_provider=NullSharedGroupContextProvider(),
    )
    bundle = provider.build_context(
        request_id="req_shared",
        sender_id="42",
        session_id="group:1",
        query_text="大家好。",
        group_id="1",
    )
    prompt_text = "\n".join(
        message["content"] for message in build_chat_prompt(bundle)
    )

    assert "最近共同会话" not in prompt_text
