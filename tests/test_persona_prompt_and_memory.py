from __future__ import annotations

from types import SimpleNamespace

from plugins.bot_unified_runtime.capabilities.chat import build_chat_prompt
from plugins.bot_unified_runtime.character.memory import SQLiteMemoryRepository
from plugins.bot_unified_runtime.character.memory_extract import (
    extract_memory_texts,
    store_extracted_memories,
)
from plugins.bot_unified_runtime.contracts import (
    ContextBundle,
    ConversationHistoryResult,
    MemoryRetrievalResult,
    PersonaProfile,
    RetrievalResult,
    ToneProfile,
)

PERSONA_TEXT = "# 角色沉浸要求\n\n你就是守岸人本人，以第一人称思考与回应。"


def _context(*, raw_text: str = "", facts: list[dict[str, str]] | None = None) -> ContextBundle:
    return ContextBundle(
        request_id="req-1",
        persona=PersonaProfile(
            profile_id="shorekeeper",
            version="1",
            display_name="守岸人",
            identity="守岸人",
            raw_text=raw_text,
        ),
        tone=ToneProfile(profile_id="shorekeeper", mode="default"),
        memory_results=MemoryRetrievalResult(
            request_id="req-1",
            facts=facts or [],
        ),
        conversation_history=ConversationHistoryResult(request_id="req-1"),
        knowledge_results=RetrievalResult(request_id="req-1"),
        current_message="你好",
        sender_id="user-1",
        session_id="private:user-1",
    )


def test_raw_persona_used_verbatim_with_runtime_sections() -> None:
    facts = [
        {
            "fact_id": "f1",
            "kind": "auto",
            "text": "用户喜欢蝴蝶",
            "source": "llm_extract",
            "sensitivity": "personal",
            "scope_key": "session:private:user-1",
        }
    ]
    messages = build_chat_prompt(_context(raw_text=PERSONA_TEXT, facts=facts))
    system_prompt = messages[0]["content"]

    assert PERSONA_TEXT in system_prompt
    assert "运行时注入的实时上下文" in system_prompt
    assert "已读取记忆：" in system_prompt
    assert "用户喜欢蝴蝶" in system_prompt
    assert "安全边界" in system_prompt
    # 原文模式下不再使用字段重组版的头部。
    assert not system_prompt.startswith("你是守岸人。")
    assert "人格名称：" not in system_prompt


def test_legacy_prompt_kept_when_raw_text_empty() -> None:
    messages = build_chat_prompt(_context())
    system_prompt = messages[0]["content"]

    assert system_prompt.startswith("你是守岸人。")
    assert "人格名称：" in system_prompt


class _FakeLLM:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[list[dict[str, str]]] = []

    def generate(self, messages: list[dict[str, str]], **kwargs: object) -> object:
        self.calls.append(messages)
        return SimpleNamespace(text=self.text)


def test_extract_memory_texts_parses_bullets_and_skips_none() -> None:
    provider = _FakeLLM("- 用户养了一只叫小蓝的猫\n1. 用户讨厌拥挤的人群\n无")
    facts = extract_memory_texts(provider, user_text="我回来了", reply_text="欢迎回来。")

    assert facts == ["用户养了一只叫小蓝的猫", "用户讨厌拥挤的人群"]
    assert provider.calls[0][0]["role"] == "system"


def test_extract_memory_texts_empty_when_nothing_worth_remembering() -> None:
    provider = _FakeLLM("无")
    assert extract_memory_texts(provider, user_text="你好", reply_text="我在。") == []


def test_store_extracted_memories_writes_sqlite(tmp_path: object) -> None:
    repository = SQLiteMemoryRepository(tmp_path / "memory.sqlite3")  # type: ignore[operator]
    stored = store_extracted_memories(
        repository,
        subject_user_id="user-1",
        session_id="private:user-1",
        texts=["用户喜欢蝴蝶"],
    )

    assert stored == 1
    result = repository.retrieve(
        request_id="req-1",
        requester_id="user-1",
        subject_user_id="user-1",
        session_id="private:user-1",
        query_text="蝴蝶",
        max_items=5,
        max_chars=1200,
    )
    assert result.facts and result.facts[0]["text"] == "用户喜欢蝴蝶"
    assert result.facts[0]["source"] == "llm_extract"
