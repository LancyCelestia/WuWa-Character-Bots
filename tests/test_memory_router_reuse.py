from __future__ import annotations

from types import SimpleNamespace

import plugins.bot_unified_runtime as runtime_module


def test_memory_writer_uses_supplied_model_router(monkeypatch):
    sentinel = object()
    captured = {}

    class Repo:
        def __init__(self, _path):
            pass

    def fake_extract(provider, **_kwargs):
        captured["provider"] = provider
        return []

    monkeypatch.setattr(runtime_module, "_build_chat_llm_provider", lambda _config: (_ for _ in ()).throw(AssertionError("direct provider used")))
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.character.memory.SQLiteMemoryRepository",
        Repo,
    )
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.character.memory_extract.extract_memory_texts",
        fake_extract,
    )
    config = SimpleNamespace(
        bot_memory_enabled=True,
        bot_memory_extract_enabled=True,
        bot_memory_db_path="memory.sqlite3",
        bot_chat_provider="openai_compatible",
    )

    writer = runtime_module._build_memory_writer(config, model_router=sentinel)
    writer(user_text="hello", reply_text="hi", sender_id="u", session_id="s")

    assert captured["provider"] is sentinel

def test_memory_uses_runtime_selection_and_multiple_keys_without_mutating_chat(monkeypatch):
    from plugins.bot_unified_runtime.config import Config
    from plugins.bot_unified_runtime.llm import LLMProviderError
    from plugins.bot_unified_runtime.llm.model_router import build_model_router
    from plugins.bot_unified_runtime.runtime.settings import RuntimeSettingsStore

    monkeypatch.delenv("BOT_API_KEY_AIPRC", raising=False)
    config = Config(bot_memory_enabled=True, bot_memory_db_path="unused.sqlite3",
        bot_chat_provider="openai_compatible", bot_chat_api_key="invalid-base",
        bot_api_key_aiprc="valid-dynamic",
        bot_model_registry={"main": {"model": "main", "base_url": "https://main.test/v1",
            "api_key": "main-key", "priority": 1}})
    settings = RuntimeSettingsStore()
    settings.set_model_entry("selected", {"model": "vision-free-text", "base_url": "https://selected.test/v1",
        "api_key": ["invalid-key", "env:BOT_API_KEY_AIPRC"], "priority": 1})
    settings.set_override("BOT_CHAT_MODEL", "selected")
    calls, facts = [], []
    class Provider:
        def __init__(self, spec): self.spec = spec
        def generate(self, messages, **kwargs):
            calls.append((self.spec.model_id, self.spec.api_key, kwargs))
            if self.spec.api_key != "valid-dynamic":
                raise LLMProviderError("unauthorized", error_kind="auth")
            return SimpleNamespace(text="用户喜欢蝴蝶")
    router = build_model_router(config, provider_factory=Provider, dynamic_registry=settings.list_model_registry)
    router.last_attempts = ["chat:success"]
    monkeypatch.setattr("plugins.bot_unified_runtime.character.memory.SQLiteMemoryRepository",
        lambda path: SimpleNamespace(upsert_fact=lambda **kw: facts.append(kw)))
    writer = runtime_module._build_memory_writer(config, model_router=router, runtime_settings=settings)
    writer(user_text="我喜欢蝴蝶", reply_text="记住了", sender_id="u", session_id="private:u")
    assert [(x[0], x[1]) for x in calls] == [("selected", "invalid-key"), ("selected", "valid-dynamic")]
    assert len(facts) == 1
    assert router.last_attempts == ["chat:success"]
    assert calls[-1][2]["max_tokens"] == 200


def test_memory_failure_is_safe_and_cools_down(monkeypatch, caplog):
    from plugins.bot_unified_runtime.config import Config
    from plugins.bot_unified_runtime.llm import LLMProviderError
    calls = []
    class Router:
        def generate(self, *args, **kwargs):
            calls.append(1)
            raise LLMProviderError("Authorization: Bearer PRIVATE-SECRET", error_kind="auth")
    monkeypatch.setattr("plugins.bot_unified_runtime.character.memory.SQLiteMemoryRepository", lambda path: None)
    config = Config(bot_memory_enabled=True, bot_memory_db_path="unused.sqlite3", bot_chat_provider="openai_compatible")
    writer = runtime_module._build_memory_writer(config, model_router=Router())
    for _ in range(2):
        writer(user_text="我喜欢蝴蝶", reply_text="好的", sender_id="u", session_id="s")
    assert len(calls) == 1
    assert "PRIVATE-SECRET" not in caplog.text
    assert not any(record.exc_info for record in caplog.records)
