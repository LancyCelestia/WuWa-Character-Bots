from plugins.wuwa_unified_runtime.capabilities.auto_send import parse_auto_send_command
from plugins.wuwa_unified_runtime.character import NullCharacterContextProvider
from plugins.wuwa_unified_runtime.contracts import MemoryQuery, PrivacyLevel, SessionType
from plugins.wuwa_unified_runtime.sources import ParserRegistry, ParserRule, SourceInput


def test_null_character_provider_returns_persona_tone_and_empty_context():
    provider = NullCharacterContextProvider()

    bundle = provider.build_context(
        request_id="req_test",
        sender_id="42",
        session_id="private:42",
        query_text="你好",
    )

    assert bundle.persona.profile_id == "default"
    assert bundle.tone.mode == "private_chat"
    assert bundle.memory_results.facts == []
    assert bundle.knowledge_results.chunks == []


def test_memory_query_is_structured_and_exported():
    query = MemoryQuery(
        request_id="req_test",
        query_text="用户偏好",
        requester_id="42",
        subject_user_id="42",
        session_id="private:42",
        purpose="reply_context",
    )

    assert query.max_items == 5
    assert query.include_summarized_facts is True


def test_parser_registry_prefers_longest_keyword_then_priority():
    registry = ParserRegistry()
    registry.register(
        ParserRule(
            parser_id="generic_bili",
            source_id="bilibili",
            keyword_patterns=["bili"],
            priority=10,
        )
    )
    registry.register(
        ParserRule(
            parser_id="video_bili",
            source_id="bilibili",
            keyword_patterns=["bilibili.com/video"],
            priority=1,
        )
    )

    matches = registry.match(
        SourceInput(
            request_id="req_test",
            session_id="group:1",
            capability_id="media_parse",
            raw_text="https://www.bilibili.com/video/BV1xx",
            privacy_level=PrivacyLevel.GROUP,
        )
    )

    assert [match.parser_id for match in matches][:2] == ["video_bili", "generic_bili"]


def test_parser_registry_matches_url_patterns_without_keyword():
    registry = ParserRegistry()
    registry.register(
        ParserRule(
            parser_id="bili_url",
            source_id="bilibili",
            url_patterns=[r"bilibili\.com/video"],
            priority=1,
        )
    )

    matches = registry.match(
        SourceInput(
            request_id="req_test",
            session_id="group:1",
            capability_id="media_parse",
            raw_text="https://www.bilibili.com/video/BV1xx",
            urls=["https://www.bilibili.com/video/BV1xx"],
            privacy_level=PrivacyLevel.GROUP,
        )
    )

    assert [match.parser_id for match in matches] == ["bili_url"]


def test_auto_send_parser_creates_draft_intent_but_not_send_request():
    intent = parse_auto_send_command(
        "报存 给 A、B 发邮件，主题：周末安排，内容根据你对他们的了解分别写",
        actor_sender_id="42",
        actor_session_id="private:42",
        actor_session_type=SessionType.PRIVATE,
    )

    assert intent.action == "draft"
    assert intent.channel == "email"
    assert [r.raw_text for r in intent.recipient_descriptors] == ["A", "B"]
    assert intent.requested_send_policy == "confirm_required"
