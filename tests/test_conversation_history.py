from plugins.bot_unified_runtime.character.history import (
    SQLiteConversationHistoryRepository,
)
from plugins.bot_unified_runtime.character.providers import FileCharacterContextProvider
from plugins.bot_unified_runtime.config import Config


def test_sqlite_conversation_history_returns_latest_turns_chronologically(tmp_path):
    repository = SQLiteConversationHistoryRepository(tmp_path / "history.sqlite3")
    for index in range(4):
        repository.append_turn(
            request_id=f"req_{index}",
            platform="qq",
            adapter="onebot.v11",
            bot_id="bot-1",
            session_id="private:42",
            sender_id="42",
            role="user" if index % 2 == 0 else "assistant",
            text=f"第 {index} 轮消息",
        )

    result = repository.retrieve(
        request_id="req_read",
        platform="qq",
        adapter="onebot.v11",
        bot_id="bot-1",
        session_id="private:42",
        sender_id="42",
        max_turns=3,
        max_chars=200,
    )

    assert [turn.text for turn in result.turns] == [
        "第 1 轮消息",
        "第 2 轮消息",
        "第 3 轮消息",
    ]
    assert [turn.role for turn in result.turns] == ["assistant", "user", "assistant"]


def test_sqlite_conversation_history_does_not_cross_user_session_or_bot(tmp_path):
    repository = SQLiteConversationHistoryRepository(tmp_path / "history.sqlite3")
    repository.append_turn(
        request_id="req_user",
        platform="qq",
        adapter="onebot.v11",
        bot_id="bot-1",
        session_id="private:42",
        sender_id="42",
        role="user",
        text="当前用户的消息",
    )
    repository.append_turn(
        request_id="req_other_user",
        platform="qq",
        adapter="onebot.v11",
        bot_id="bot-1",
        session_id="private:99",
        sender_id="99",
        role="user",
        text="其他用户的消息",
    )
    repository.append_turn(
        request_id="req_other_bot",
        platform="qq",
        adapter="onebot.v11",
        bot_id="bot-2",
        session_id="private:42",
        sender_id="42",
        role="user",
        text="其他机器人实例的消息",
    )

    result = repository.retrieve(
        request_id="req_read",
        platform="qq",
        adapter="onebot.v11",
        bot_id="bot-1",
        session_id="private:42",
        sender_id="42",
        max_turns=10,
        max_chars=200,
    )

    assert [turn.text for turn in result.turns] == ["当前用户的消息"]


def test_sqlite_conversation_history_clear_scope_only_removes_matching_rows(tmp_path):
    repository = SQLiteConversationHistoryRepository(tmp_path / "history.sqlite3")
    rows = [
        ("req_current_1", "qq", "nonebot", "bot-1", "private:42", "42", "user", "当前用户消息 1"),
        ("req_current_2", "qq", "nonebot", "bot-1", "private:42", "42", "assistant", "当前用户消息 2"),
        ("req_other_session", "qq", "nonebot", "bot-1", "private:99", "99", "user", "其他会话消息"),
        ("req_other_bot", "qq", "nonebot", "bot-2", "private:42", "42", "user", "其他机器人消息"),
        ("req_other_adapter", "qq", "onebot.v11", "bot-1", "private:42", "42", "user", "其他适配器消息"),
    ]
    for request_id, platform, adapter, bot_id, session_id, sender_id, role, text in rows:
        repository.append_turn(
            request_id=request_id,
            platform=platform,
            adapter=adapter,
            bot_id=bot_id,
            session_id=session_id,
            sender_id=sender_id,
            role=role,
            text=text,
        )

    cleared = repository.clear_scope(
        platform="qq",
        adapter="nonebot",
        bot_id="bot-1",
        session_id="private:42",
        sender_id="42",
    )

    assert cleared == 2
    current = repository.retrieve(
        request_id="req_read",
        platform="qq",
        adapter="nonebot",
        bot_id="bot-1",
        session_id="private:42",
        sender_id="42",
        max_turns=10,
        max_chars=500,
    )
    other_session = repository.retrieve(
        request_id="req_read",
        platform="qq",
        adapter="nonebot",
        bot_id="bot-1",
        session_id="private:99",
        sender_id="99",
        max_turns=10,
        max_chars=500,
    )
    other_bot = repository.retrieve(
        request_id="req_read",
        platform="qq",
        adapter="nonebot",
        bot_id="bot-2",
        session_id="private:42",
        sender_id="42",
        max_turns=10,
        max_chars=500,
    )
    other_adapter = repository.retrieve(
        request_id="req_read",
        platform="qq",
        adapter="onebot.v11",
        bot_id="bot-1",
        session_id="private:42",
        sender_id="42",
        max_turns=10,
        max_chars=500,
    )

    assert current.turns == []
    assert [turn.text for turn in other_session.turns] == ["其他会话消息"]
    assert [turn.text for turn in other_bot.turns] == ["其他机器人消息"]
    assert [turn.text for turn in other_adapter.turns] == ["其他适配器消息"]


def test_sqlite_conversation_history_prunes_old_rows_per_scope(tmp_path):
    repository = SQLiteConversationHistoryRepository(tmp_path / "history.sqlite3", max_items=3)
    for index in range(5):
        repository.append_turn(
            request_id=f"req_current_{index}",
            platform="qq",
            adapter="nonebot",
            bot_id="bot-1",
            session_id="private:42",
            sender_id="42",
            role="user",
            text=f"当前作用域消息 {index}",
        )
    for index in range(2):
        repository.append_turn(
            request_id=f"req_other_{index}",
            platform="qq",
            adapter="nonebot",
            bot_id="bot-1",
            session_id="private:99",
            sender_id="99",
            role="user",
            text=f"其他作用域消息 {index}",
        )

    current = repository.retrieve(
        request_id="req_read",
        platform="qq",
        adapter="nonebot",
        bot_id="bot-1",
        session_id="private:42",
        sender_id="42",
        max_turns=10,
        max_chars=500,
    )
    other = repository.retrieve(
        request_id="req_read",
        platform="qq",
        adapter="nonebot",
        bot_id="bot-1",
        session_id="private:99",
        sender_id="99",
        max_turns=10,
        max_chars=500,
    )

    assert [turn.text for turn in current.turns] == [
        "当前作用域消息 2",
        "当前作用域消息 3",
        "当前作用域消息 4",
    ]
    assert [turn.text for turn in other.turns] == [
        "其他作用域消息 0",
        "其他作用域消息 1",
    ]


def test_sqlite_conversation_history_respects_char_budget(tmp_path):
    repository = SQLiteConversationHistoryRepository(tmp_path / "history.sqlite3")
    repository.append_turn(
        request_id="req_1",
        platform="qq",
        adapter="onebot.v11",
        bot_id="bot-1",
        session_id="private:42",
        sender_id="42",
        role="user",
        text="一" * 80,
    )
    repository.append_turn(
        request_id="req_2",
        platform="qq",
        adapter="onebot.v11",
        bot_id="bot-1",
        session_id="private:42",
        sender_id="42",
        role="assistant",
        text="二" * 80,
    )

    result = repository.retrieve(
        request_id="req_read",
        platform="qq",
        adapter="onebot.v11",
        bot_id="bot-1",
        session_id="private:42",
        sender_id="42",
        max_turns=10,
        max_chars=40,
    )

    assert len(result.turns) == 1
    assert result.turns[0].role == "assistant"
    assert result.turns[0].text == "二" * 39 + "…"


def test_file_character_provider_injects_recent_conversation_history(tmp_path):
    persona_file = tmp_path / "shorekeeper.md"
    persona_file.write_text("守岸人来自黑海岸。\n说话温柔克制。", encoding="utf-8")
    repository = SQLiteConversationHistoryRepository(tmp_path / "history.sqlite3")
    repository.append_turn(
        request_id="req_before_1",
        platform="qq",
        adapter="nonebot",
        bot_id="bot-1",
        session_id="private:42",
        sender_id="42",
        role="user",
        text="我刚刚问过你会不会记得我。",
    )
    repository.append_turn(
        request_id="req_before_2",
        platform="qq",
        adapter="nonebot",
        bot_id="bot-1",
        session_id="private:42",
        sender_id="42",
        role="assistant",
        text="我会在允许的范围内记住我们刚说过的话。",
    )
    provider = FileCharacterContextProvider(
        persona_profile_id="shorekeeper",
        persona_display_name="守岸人",
        persona_version="test",
        persona_files=[persona_file],
        knowledge_files=[],
        conversation_history_provider=repository,
        history_max_turns=4,
        history_max_chars=300,
    )

    bundle = provider.build_context(
        request_id="req_current",
        sender_id="42",
        session_id="private:42",
        query_text="那你还记得吗？",
        platform="qq",
        adapter="nonebot",
        bot_id="bot-1",
    )

    assert [turn.text for turn in bundle.conversation_history.turns] == [
        "我刚刚问过你会不会记得我。",
        "我会在允许的范围内记住我们刚说过的话。",
    ]


def test_character_provider_factory_enables_history_from_config(tmp_path):
    from plugins.bot_unified_runtime.character import build_character_context_provider

    persona_file = tmp_path / "shorekeeper.md"
    persona_file.write_text("守岸人来自黑海岸。", encoding="utf-8")
    db_path = tmp_path / "history.sqlite3"
    SQLiteConversationHistoryRepository(db_path).append_turn(
        request_id="req_before",
        platform="qq",
        adapter="nonebot",
        bot_id="bot-1",
        session_id="private:42",
        sender_id="42",
        role="user",
        text="上一轮聊天内容",
    )

    provider = build_character_context_provider(
        Config(
            bot_persona_profile_id="shorekeeper",
            bot_persona_display_name="守岸人",
            bot_persona_files=[str(persona_file)],
            bot_history_enabled=True,
            bot_history_db_path=str(db_path),
            bot_history_max_turns=3,
            bot_history_max_chars=200,
        )
    )
    bundle = provider.build_context(
        request_id="req_current",
        sender_id="42",
        session_id="private:42",
        query_text="继续",
        platform="qq",
        adapter="nonebot",
        bot_id="bot-1",
    )

    assert bundle.conversation_history.turns[0].text == "上一轮聊天内容"


def test_conversation_history_factory_passes_storage_retention_limit(tmp_path):
    from plugins.bot_unified_runtime.character import (
        build_conversation_history_provider,
    )

    db_path = tmp_path / "history.sqlite3"
    repository = build_conversation_history_provider(
        Config(
            bot_history_enabled=True,
            bot_history_db_path=str(db_path),
            bot_history_max_items=2,
        )
    )
    for index in range(4):
        repository.append_turn(
            request_id=f"req_{index}",
            platform="qq",
            adapter="nonebot",
            bot_id="bot-1",
            session_id="private:42",
            sender_id="42",
            role="user",
            text=f"保留测试 {index}",
        )

    result = repository.retrieve(
        request_id="req_read",
        platform="qq",
        adapter="nonebot",
        bot_id="bot-1",
        session_id="private:42",
        sender_id="42",
        max_turns=10,
        max_chars=500,
    )

    assert [turn.text for turn in result.turns] == ["保留测试 2", "保留测试 3"]
