from __future__ import annotations

from types import SimpleNamespace

from plugins.bot_unified_runtime.capabilities.runtime_admin import _handle_model_command
from plugins.bot_unified_runtime.llm.model_router import (
    ModelSpec,
    normalize_priority_entries,
    reorder_priority_entries,
)
from plugins.bot_unified_runtime.runtime.settings import RuntimeSettingsStore


def _spec(model_id: str, priority: int) -> ModelSpec:
    return ModelSpec(
        model_id=model_id,
        model=f"model-{model_id}",
        base_url="https://example.test/v1",
        api_key="key",
        tags=("strong",),
        priority=priority,
    )


def test_priority_normalization_produces_unique_dense_slots():
    entries = {
        "a": {"model": "a", "priority": 2},
        "b": {"model": "b", "priority": 2},
        "c": {"model": "c", "priority": 99},
    }

    normalized = normalize_priority_entries(entries)

    assert [normalized[key]["priority"] for key in ("a", "b", "c")] == [1, 2, 3]
    assert sorted(item["priority"] for item in normalized.values()) == [1, 2, 3]


def test_priority_move_shifts_other_models_instead_of_creating_duplicates():
    entries = {
        "a": {"model": "a", "priority": 1},
        "b": {"model": "b", "priority": 2},
        "c": {"model": "c", "priority": 3},
    }

    reordered = reorder_priority_entries(entries, "c", 1)

    assert [key for key, _ in sorted(reordered.items(), key=lambda item: item[1]["priority"])] == [
        "c",
        "a",
        "b",
    ]
    assert sorted(item["priority"] for item in reordered.values()) == [1, 2, 3]


def test_model_priority_command_reorders_runtime_slots():
    store = RuntimeSettingsStore()
    config = SimpleNamespace(
        bot_model_registry={
            "a": {"model": "a", "base_url": "https://a", "api_key": "k", "priority": 1},
            "b": {"model": "b", "base_url": "https://b", "api_key": "k", "priority": 2},
            "c": {"model": "c", "base_url": "https://c", "api_key": "k", "priority": 3},
        },
        bot_chat_model="a",
        bot_model_auto_route=True,
        bot_model_priority_groups=[],
        bot_timezone="Asia/Hong_Kong",
        bot_chat_base_url="https://a",
        bot_chat_api_key="k",
        bot_model_presets={},
    )

    message = _handle_model_command(store, config, ["priority", "c", "1"])

    assert "1" in message
    runtime = store.list_model_registry()
    assert [key for key, _ in sorted(runtime.items(), key=lambda item: item[1]["priority"])] == [
        "c",
        "a",
        "b",
    ]


def test_detail_policy_requires_expanded_relationship_answer():
    from plugins.bot_unified_runtime.capabilities.chat import _RUNTIME_ANSWER_RULES

    assert "身份" in _RUNTIME_ANSWER_RULES
    assert "关系" in _RUNTIME_ANSWER_RULES
    assert "一两句定性" not in _RUNTIME_ANSWER_RULES

def test_detail_and_concise_prompts_have_no_contradictory_runtime_rules():
    from plugins.bot_unified_runtime.capabilities.chat import build_chat_prompt
    from plugins.bot_unified_runtime.character.providers import (
        NullCharacterContextProvider,
    )
    context = NullCharacterContextProvider().build_context("r", "u", "s", "守岸人与黑海岸是什么关系")
    context = context.model_copy(update={"context_budget": 12000, "reply_detail": "detail"})
    for raw in ("", "人设原文必须保持不变"):
        context.persona.raw_text = raw
        prompt = build_chat_prompt(context)[0]["content"]
        assert "身份" in prompt and "关系" in prompt
        assert "一两句定性" not in prompt
        assert "只挑最关键的一两点" not in prompt
        if raw: assert raw in prompt
    context.reply_detail = "concise"
    assert "当前为详细测试阶段" not in build_chat_prompt(context)[0]["content"]


def test_chat_respects_detail_default_and_runtime_override(monkeypatch):
    from plugins.bot_unified_runtime.capabilities import chat
    from plugins.bot_unified_runtime.character.providers import (
        NullCharacterContextProvider,
    )
    from plugins.bot_unified_runtime.contracts import (
        BotDecision,
        CapabilityResult,
        IncomingMessage,
        SessionType,
    )
    from plugins.bot_unified_runtime.llm import StaticLLMProvider
    captured = []
    def result(**kwargs):
        captured.append(kwargs["context"].reply_detail)
        return CapabilityResult(request_id=kwargs["message"].request_id, kind="text", body="ok")
    monkeypatch.setattr(chat, "build_chat_result", result)
    settings = RuntimeSettingsStore()
    capability = chat.build_chat_capability(NullCharacterContextProvider(), StaticLLMProvider(),
        reply_detail="detail", runtime_settings=settings)
    msg = IncomingMessage(platform="qq", adapter="nonebot", bot_id="b", session_id="private:u",
        sender_id="u", session_type=SessionType.PRIVATE, plain_text="你好", mentions_bot=True)
    decision = BotDecision(request_id=msg.request_id, should_respond=True, mode="chat",
        trigger="private", capability_id="bot.chat", target_scope=SessionType.PRIVATE,
        context_budget=12000, decision_reason="test")
    capability(msg, decision)
    settings.set_override("BOT_REPLY_DETAIL", "精简")
    capability(msg, decision)
    assert captured == ["detail", "concise"]


def test_add_and_update_priorities_shift_effective_registry():
    config = SimpleNamespace(bot_model_registry={"a": {"model": "a", "base_url": "https://a", "priority": 1},
        "b": {"model": "b", "base_url": "https://b", "priority": 2}})
    store = RuntimeSettingsStore()
    _handle_model_command(store, config, ["add", "c", "model=c", "base_url=https://c", "priority=1"])
    registry = store.list_model_registry()
    assert [(k, v["priority"]) for k, v in registry.items()] == [("c", 1), ("a", 2), ("b", 3)]
    _handle_model_command(store, config, ["update", "b", "priority=1"])
    assert [k for k, v in sorted(store.list_model_registry().items(), key=lambda i:i[1]["priority"])] == ["b", "c", "a"]


def test_memory_settings_and_help_are_discoverable():
    from plugins.bot_unified_runtime.capabilities.echo import HELP_ENTRIES
    from plugins.bot_unified_runtime.runtime.settings import SETTABLE_KEYS
    for key in ("BOT_MEMORY_EXTRACT_ENABLED", "BOT_MEMORY_EXTRACT_TIMEOUT_SECONDS", "BOT_MEMORY_EXTRACT_MAX_TOKENS",
                "BOT_CHAT_FAST_MODE", "BOT_CHAT_FAST_MAX_TOKENS"):
        assert key in SETTABLE_KEYS
        assert any(key in str(entry) for entry in HELP_ENTRIES)


def test_priority_refresh_preserves_alternate_keys_and_aliases():
    from plugins.bot_unified_runtime.llm.model_router import build_model_router
    config = SimpleNamespace(bot_model_registry={"a":{"model":"a", "priority":1, "api_key":["k1","k2"],"aliases":["alpha"]}})
    router = build_model_router(config, dynamic_registry=dict)
    router.route_ids(message_text="hi", override="")
    assert router.specs["a"].all_api_keys() == ("k1", "k2")
    assert router.specs["a"].aliases == ("alpha",)


def test_fast_search_results_reach_generation_without_page_fetch(monkeypatch):
    from plugins.bot_unified_runtime.capabilities import chat
    from plugins.bot_unified_runtime.character.providers import (
        NullCharacterContextProvider,
    )
    from plugins.bot_unified_runtime.contracts import (
        BotDecision,
        CapabilityResult,
        IncomingMessage,
        SessionType,
    )
    from plugins.bot_unified_runtime.llm import StaticLLMProvider
    from plugins.bot_unified_runtime.sources.web_search import WebSearchHit
    captured = []
    class Search:
        def search(self, query, **kw):
            return [WebSearchHit(title="官方说明", url="https://example.test/source", snippet="已验证证据")]
        def fetch_page_text(self, *args, **kw): raise AssertionError("page fetch disabled")
    def result(**kwargs):
        captured.append(kwargs["context"].web_search_context)
        return CapabilityResult(request_id=kwargs["message"].request_id, kind="text", body="ok")
    monkeypatch.setattr(chat, "build_chat_result", result)
    capability = chat.build_chat_capability(NullCharacterContextProvider(), StaticLLMProvider(),
        web_search_enabled=True, web_search_provider=Search(), fast_mode=True, fast_skip_web_pages=True)
    msg = IncomingMessage(platform="qq", adapter="nonebot", bot_id="b", session_id="private:u",
        sender_id="u", session_type=SessionType.PRIVATE, plain_text="搜索最新的官方公告", mentions_bot=True)
    decision = BotDecision(request_id=msg.request_id, should_respond=True, mode="chat", trigger="private",
        capability_id="bot.chat", target_scope=SessionType.PRIVATE, context_budget=12000, decision_reason="test")
    capability(msg, decision)
    assert captured[0] is not None
    assert captured[0].hits[0].snippet == "已验证证据"
