from plugins.bot_unified_runtime.capabilities.chat import build_chat_prompt
from plugins.bot_unified_runtime.character import build_character_context_provider
from plugins.bot_unified_runtime.character.memory import SQLiteMemoryRepository
from plugins.bot_unified_runtime.character.providers import FileCharacterContextProvider
from plugins.bot_unified_runtime.config import Config


def test_sqlite_memory_repository_retrieves_scoped_user_facts(tmp_path):
    db_path = tmp_path / "memory.sqlite3"
    repository = SQLiteMemoryRepository(db_path)
    repository.upsert_fact(
        fact_id="fact_1",
        subject_user_id="42",
        session_id="private:42",
        memory_kind="preference",
        text="用户喜欢鸣潮，也喜欢安静、有陪伴感的回复。",
        confidence=0.84,
    )
    repository.upsert_fact(
        fact_id="fact_other_user",
        subject_user_id="99",
        session_id="private:99",
        memory_kind="preference",
        text="另一个用户的偏好不应被读到。",
    )

    result = repository.retrieve(
        request_id="req_memory",
        requester_id="42",
        subject_user_id="42",
        session_id="private:42",
        query_text="今天有点累，陪我聊鸣潮。",
        max_items=5,
        max_chars=200,
    )

    assert result.request_id == "req_memory"
    assert result.confidence == 0.84
    assert result.facts == [
        {
            "fact_id": "fact_1",
            "kind": "preference",
            "text": "用户喜欢鸣潮，也喜欢安静、有陪伴感的回复。",
            "source": "sqlite",
            "sensitivity": "personal",
            "scope_key": "session:private:42",
        }
    ]


def test_sqlite_memory_repository_preserves_sensitivity_and_scope(tmp_path):
    db_path = tmp_path / "memory.sqlite3"
    repository = SQLiteMemoryRepository(db_path)
    repository.upsert_fact(
        fact_id="fact_group",
        subject_user_id="42",
        session_id="group:100",
        memory_kind="manual",
        text="这个群喜欢简短的鸣潮活动提醒。",
        sensitivity="group",
        scope_key="session:group:100",
    )

    result = repository.retrieve(
        request_id="req_memory",
        requester_id="42",
        subject_user_id="42",
        session_id="group:100",
        query_text="群规则",
        max_items=5,
        max_chars=200,
    )

    assert result.facts == [
        {
            "fact_id": "fact_group",
            "kind": "manual",
            "text": "这个群喜欢简短的鸣潮活动提醒。",
            "source": "sqlite",
            "sensitivity": "group",
            "scope_key": "session:group:100",
        }
    ]


def test_sqlite_memory_repository_respects_zero_item_limit(tmp_path):
    repository = SQLiteMemoryRepository(tmp_path / "memory.sqlite3")
    repository.upsert_fact(
        fact_id="fact_1",
        subject_user_id="42",
        session_id="private:42",
        memory_kind="preference",
        text="用户喜欢鸣潮。",
    )

    result = repository.retrieve(
        request_id="req_memory",
        requester_id="42",
        subject_user_id="42",
        session_id="private:42",
        query_text="鸣潮",
        max_items=0,
        max_chars=200,
    )

    assert result.facts == []
    assert result.confidence == 0.0


def test_file_character_provider_injects_sqlite_memory_into_prompt(tmp_path):
    persona_file = tmp_path / "shorekeeper.md"
    persona_file.write_text("守岸人来自黑海岸。\n说话温柔克制。", encoding="utf-8")
    repository = SQLiteMemoryRepository(tmp_path / "memory.sqlite3")
    repository.upsert_fact(
        fact_id="fact_1",
        subject_user_id="42",
        session_id="private:42",
        memory_kind="preference",
        text="用户说过自己喜欢守岸人的安静陪伴。",
    )
    provider = FileCharacterContextProvider(
        persona_profile_id="shorekeeper",
        persona_display_name="守岸人",
        persona_version="test",
        persona_files=[persona_file],
        knowledge_files=[],
        memory_provider=repository,
    )

    bundle = provider.build_context(
        request_id="req_memory",
        sender_id="42",
        session_id="private:42",
        query_text="今天想听你说话。",
    )
    prompt_text = "\n".join(message["content"] for message in build_chat_prompt(bundle))

    assert bundle.memory_results.facts[0]["text"] == "用户说过自己喜欢守岸人的安静陪伴。"
    assert "用户说过自己喜欢守岸人的安静陪伴" in prompt_text


def test_chat_prompt_marks_memory_sensitivity_and_scope(tmp_path):
    persona_file = tmp_path / "shorekeeper.md"
    persona_file.write_text("守岸人来自黑海岸。", encoding="utf-8")
    repository = SQLiteMemoryRepository(tmp_path / "memory.sqlite3")
    repository.upsert_fact(
        fact_id="fact_group",
        subject_user_id="42",
        session_id="group:100",
        memory_kind="manual",
        text="这个群喜欢简短的鸣潮活动提醒。",
        sensitivity="group",
        scope_key="session:group:100",
    )
    provider = FileCharacterContextProvider(
        persona_profile_id="shorekeeper",
        persona_display_name="守岸人",
        persona_version="test",
        persona_files=[persona_file],
        knowledge_files=[],
        memory_provider=repository,
    )

    bundle = provider.build_context(
        request_id="req_memory",
        sender_id="42",
        session_id="group:100",
        query_text="今天有什么活动？",
    )
    prompt_text = "\n".join(message["content"] for message in build_chat_prompt(bundle))

    assert "这个群喜欢简短的鸣潮活动提醒" in prompt_text
    assert "sensitivity=group" in prompt_text
    assert "scope=session:group:100" in prompt_text


def test_character_context_excludes_credentialed_memory_from_llm_prompt(tmp_path):
    persona_file = tmp_path / "shorekeeper.md"
    persona_file.write_text("守岸人来自黑海岸。", encoding="utf-8")
    repository = SQLiteMemoryRepository(tmp_path / "memory.sqlite3")
    repository.upsert_fact(
        fact_id="fact_personal",
        subject_user_id="42",
        session_id="private:42",
        memory_kind="preference",
        text="用户喜欢安静的回复。",
        sensitivity="personal",
    )
    repository.upsert_fact(
        fact_id="fact_credential",
        subject_user_id="42",
        session_id="private:42",
        memory_kind="credential",
        text="登录口令是 never-send-this-secret",
        sensitivity="credentialed",
    )
    provider = FileCharacterContextProvider(
        persona_profile_id="shorekeeper",
        persona_display_name="守岸人",
        persona_version="test",
        persona_files=[persona_file],
        knowledge_files=[],
        memory_provider=repository,
    )

    bundle = provider.build_context(
        request_id="req_memory",
        sender_id="42",
        session_id="private:42",
        query_text="你还记得我吗？",
    )
    prompt_text = "\n".join(message["content"] for message in build_chat_prompt(bundle))

    assert [fact["fact_id"] for fact in bundle.memory_results.facts] == [
        "fact_personal"
    ]
    assert "never-send-this-secret" not in prompt_text
    assert "credentialed" not in prompt_text


def test_character_provider_factory_enables_sqlite_memory_from_config(tmp_path):
    persona_file = tmp_path / "shorekeeper.md"
    persona_file.write_text("守岸人来自黑海岸。", encoding="utf-8")
    db_path = tmp_path / "memory.sqlite3"
    SQLiteMemoryRepository(db_path).upsert_fact(
        fact_id="fact_1",
        subject_user_id="42",
        session_id="private:42",
        memory_kind="profile",
        text="用户希望机器人称呼自己为漂泊者。",
    )

    provider = build_character_context_provider(
        Config(
            bot_persona_profile_id="shorekeeper",
            bot_persona_display_name="守岸人",
            bot_persona_files=[str(persona_file)],
            bot_memory_enabled=True,
            bot_memory_db_path=str(db_path),
            bot_memory_max_items=3,
            bot_memory_max_chars=300,
        )
    )
    bundle = provider.build_context(
        request_id="req_memory",
        sender_id="42",
        session_id="private:42",
        query_text="你还记得怎么称呼我吗？",
    )

    assert bundle.memory_results.facts[0]["text"] == "用户希望机器人称呼自己为漂泊者。"
