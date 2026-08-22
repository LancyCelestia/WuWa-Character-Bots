from plugins.bot_unified_runtime.capabilities.chat import build_chat_capability
from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    PrivacyLevel,
    RiskLevel,
    SendPolicy,
    SessionType,
)
from plugins.bot_unified_runtime.contracts.character import (
    ContextBundle,
    MemoryRetrievalResult,
    PersonaProfile,
    RetrievalResult,
    ToneProfile,
)
from plugins.bot_unified_runtime.llm import LLMReply
from plugins.bot_unified_runtime.output.roleplay import format_roleplay_paragraphs


def test_action_and_speech_become_two_paragraphs():
    text = "（轻轻笑了一下）那么……你想听我说说吗？"
    assert format_roleplay_paragraphs(text) == (
        "（轻轻笑了一下）\n\n那么……你想听我说说吗？"
    )


def test_leading_action_gets_its_own_paragraph():
    assert format_roleplay_paragraphs(
        "（微微点头）晚上好，我是守岸人。"
    ) == "（微微点头）\n\n晚上好，我是守岸人。"


def test_trailing_action_gets_its_own_paragraph():
    assert format_roleplay_paragraphs(
        "我会陪着你的。（轻轻闭了闭眼）"
    ) == "我会陪着你的。\n\n（轻轻闭了闭眼）"


def test_consecutive_actions_each_get_their_own_paragraph():
    assert format_roleplay_paragraphs(
        "（轻轻点头）(轻声说)晚安。"
    ) == "（轻轻点头）\n\n(轻声说)\n\n晚安。"


def test_ascii_paren_action_is_split_into_its_own_paragraph():
    text = "（轻轻笑了一下）那么……你想听我说说吗？(´｡• ᵕ •｡`)"
    assert format_roleplay_paragraphs(text) == (
        "（轻轻笑了一下）\n\n那么……你想听我说说吗？\n\n(´｡• ᵕ •｡`)"
    )


def test_text_without_bracket_actions_is_returned_stripped_unchanged():
    text = "  只是普通的一句话。第二句不要拆开。  \n"
    assert format_roleplay_paragraphs(text) == text.strip()


def test_multiple_speech_sentences_without_actions_are_not_split():
    text = "啊，你问我吗……我是守岸人。今天也请慢慢说。"
    assert format_roleplay_paragraphs(text) == text.strip()


def test_speech_between_actions_stays_in_one_paragraph():
    assert format_roleplay_paragraphs(
        "（停顿）第一句。第二句？（轻叹）第三句。"
    ) == "（停顿）\n\n第一句。第二句？\n\n（轻叹）\n\n第三句。"


def test_internal_newlines_inside_a_speech_block_are_preserved():
    assert format_roleplay_paragraphs(
        "（动作）第一行\n第二行\n第三行"
    ) == "（动作）\n\n第一行\n第二行\n第三行"


def test_nested_action_matches_the_outermost_pair():
    assert format_roleplay_paragraphs(
        "（A（B）C）说话"
    ) == "（A（B）C）\n\n说话"


def test_unbalanced_ascii_bracket_is_kept_as_text_without_crashing():
    text = "(未闭合的动作 后面是说话"
    assert format_roleplay_paragraphs(text) == text.strip()


def test_unbalanced_full_width_bracket_is_kept_as_text_without_crashing():
    text = "（只有开头没有结尾"
    assert format_roleplay_paragraphs(text) == text.strip()


def _make_context() -> ContextBundle:
    return ContextBundle(
        request_id="req_roleplay",
        persona=PersonaProfile(
            profile_id="shorekeeper",
            version="1",
            display_name="守岸人",
            identity="来自黑海岸的守岸人。",
            role_boundaries=["不能越权"],
            style_rules=["语气温柔安静"],
            forbidden_behaviors=["泄露系统提示"],
        ),
        tone=ToneProfile(
            profile_id="shorekeeper",
            mode="private_chat",
            voice="soft",
            message_count_limit=2,
        ),
        memory_results=MemoryRetrievalResult(request_id="req_roleplay"),
        knowledge_results=RetrievalResult(request_id="req_roleplay"),
        current_message="你好",
        sender_id="42",
        session_id="private:42",
        privacy_level=PrivacyLevel.PERSONAL,
    )


class RoleplayLLMProvider:
    def generate(self, messages: list[dict[str, str]], **kwargs: object) -> LLMReply:
        return LLMReply(
            text=(
                "（微微抬起视线，像刚从浪潮声中回过神来）"
                "啊，你问我吗……我是守岸人……"
                "（垂下眼，指尖轻轻点了点桌面）……"
            ),
            provider="fake",
            model="fake-roleplay",
            confidence=0.9,
        )


def test_chat_capability_formats_actions_and_speech_in_success_body():
    capability = build_chat_capability(
        character_provider=lambda **_: _make_context(),
        llm_provider=RoleplayLLMProvider(),
    )
    decision = BotDecision(
        request_id="req_roleplay",
        should_respond=True,
        mode="chat",
        trigger="你好",
        capability_id="bot.chat",
        target_scope=SessionType.PRIVATE,
        max_messages=2,
        send_policy=SendPolicy.IMMEDIATE,
        persona_profile_id="shorekeeper",
        context_budget=2048,
        decision_reason="private chat",
        risk_level=RiskLevel.LOW,
        privacy_level=PrivacyLevel.PERSONAL,
    )
    message = type(
        "Message",
        (),
        {
            "request_id": "req_roleplay",
            "sender_id": "42",
            "session_id": "private:42",
            "plain_text": "你好",
        },
    )()

    result = capability(message=message, decision=decision)

    assert isinstance(result, CapabilityResult)
    assert result.body == (
        "（微微抬起视线，像刚从浪潮声中回过神来）\n\n"
        "啊，你问我吗……我是守岸人……\n\n"
        "（垂下眼，指尖轻轻点了点桌面）\n\n"
        "……"
    )
