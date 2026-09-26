from plugins.bot_unified_runtime.domains.chat_reply.character.addressing import (
    build_addressing_context,
)


def test_private_user_is_wanderer_without_gender_guess():
    ctx = build_addressing_context(session_type="private", sender_display_name="小明", sender_roles=["user"])
    assert ctx.can_use_wanderer_title is True
    assert ctx.preferred_name == "漂泊者"
    assert ctx.gender_identity == "unknown"


def test_group_member_uses_nickname_not_wanderer():
    ctx = build_addressing_context(session_type="group", sender_display_name="群昵称", sender_roles=["user"])
    assert ctx.can_use_wanderer_title is False
    assert ctx.preferred_name == "群昵称"
    assert "禁止称其为漂泊者" in ctx.instruction


def test_group_member_wanderer_preference_falls_back_to_display_name():
    """评审 D1 回归：群友自设偏好「漂泊者」必须被忽略，
    否则指令变成「优先称呼“漂泊者”+禁止称其为漂泊者」自斥。"""
    ctx = build_addressing_context(
        session_type="group", sender_display_name="群昵称",
        sender_roles=["user"], addressing_preference="漂泊者",
    )
    assert ctx.preferred_name == "群昵称"
    assert "优先称呼“漂泊者”" not in ctx.instruction
    assert "禁止称其为漂泊者" in ctx.instruction


def test_private_and_master_keep_wanderer_preference():
    """私聊与群超管的「漂泊者」偏好是合法用法，保留现有行为。"""
    private_ctx = build_addressing_context(
        session_type="private", sender_display_name="小明",
        addressing_preference="漂泊者",
    )
    assert private_ctx.preferred_name == "漂泊者"
    assert private_ctx.can_use_wanderer_title is True
    master_ctx = build_addressing_context(
        session_type="group", sender_display_name="主人",
        sender_roles=["user", "super_admin"], addressing_preference="漂泊者",
    )
    assert master_ctx.is_master is True
    assert master_ctx.preferred_name == "漂泊者"


def test_group_super_admin_is_master_exception():
    ctx = build_addressing_context(session_type="group", sender_display_name="主人", sender_roles=["user", "super_admin"])
    assert ctx.is_master is True
    assert ctx.can_use_wanderer_title is True
    assert "master" in ctx.instruction


def test_null_provider_and_prompt_receive_group_boundary():
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
        build_chat_prompt,
    )
    from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
        NullCharacterContextProvider,
    )

    context = NullCharacterContextProvider().build_context(
        "r", "u", "group:g", "你好", group_id="g",
        sender_display_name="群友甲", sender_roles=["user"],
    )
    assert context.addressing_context is not None
    assert context.addressing_context.preferred_name == "群友甲"
    assert "禁止称其为漂泊者" in build_chat_prompt(context)[0]["content"]


def test_private_explicit_addressing_preference_wins():
    ctx = build_addressing_context(
        session_type="private", sender_display_name="小明",
        addressing_preference="旅人", gender_identity="male",
    )
    assert ctx.preferred_name == "旅人"
    assert ctx.can_use_wanderer_title is True
    assert ctx.gender_identity == "male"
    assert ctx.gender_confidence == "explicit"


def test_addressing_preference_store_roundtrip(tmp_path):
    from plugins.bot_unified_runtime.domains.chat_reply.character.addressing import (
        AddressingPreferenceStore,
    )

    store = AddressingPreferenceStore(tmp_path / "addressing.sqlite3")
    assert store.get(session_type="private", sender_id="u1") == ("", "unknown")

    store.set(
        session_type="private", sender_id="u1",
        addressing_preference="旅人", gender_identity="female",
    )
    assert store.get(session_type="private", sender_id="u1") == ("旅人", "female")

    # 部分更新：只改性别时称谓偏好保留；未知性别值归一为 unknown。
    store.set(session_type="private", sender_id="u1", gender_identity="nonbinary")
    assert store.get(session_type="private", sender_id="u1") == ("旅人", "nonbinary")
    store.set(session_type="private", sender_id="u2", gender_identity="bogus")
    assert store.get(session_type="private", sender_id="u2") == ("", "unknown")

    store.clear(session_type="private", sender_id="u1")
    assert store.get(session_type="private", sender_id="u1") == ("", "unknown")


def test_file_provider_prefers_stored_preference(tmp_path):
    from plugins.bot_unified_runtime.domains.chat_reply.character.addressing import (
        AddressingPreferenceStore,
    )
    from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
        FileCharacterContextProvider,
    )

    store = AddressingPreferenceStore(tmp_path / "addressing.sqlite3")
    store.set(
        session_type="private", sender_id="u1",
        addressing_preference="旅人", gender_identity="female",
    )
    provider = FileCharacterContextProvider(
        persona_profile_id="default",
        persona_display_name="报存",
        persona_version="0",
        persona_files=[],
        knowledge_files=[],
        addressing_preferences=store,
    )
    bundle = provider.build_context("req-1", "u1", "private:u1", "在吗")
    ctx = bundle.addressing_context
    assert ctx is not None
    assert ctx.preferred_name == "旅人"
    assert ctx.can_use_wanderer_title is True
    assert ctx.gender_identity == "female"
    assert ctx.gender_confidence == "explicit"

    # 调用方显式参数优先于持久化偏好。
    overridden = provider.build_context(
        "req-2", "u1", "private:u1", "在吗", addressing_preference="岸友",
    )
    assert overridden.addressing_context is not None
    assert overridden.addressing_context.preferred_name == "岸友"


def test_group_digest_keeps_members_as_group_friends(tmp_path):
    import sqlite3

    from plugins.bot_unified_runtime.domains.chat_reply.character.shared_group import (
        OpenAICompatibleGroupSummarizer,
        SQLiteGroupDigestProvider,
    )

    db = tmp_path / "turns.sqlite3"
    with sqlite3.connect(db) as connection:
        connection.execute(
            """
            CREATE TABLE conversation_turns (
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                kind TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO conversation_turns VALUES"
            " ('group_1_u1', 'user', '早上好', '2026-09-11T08:00:00', 'chat')"
        )
        connection.execute(
            "INSERT INTO conversation_turns VALUES"
            " ('group_1_u1', 'assistant', '早', '2026-09-11T08:01:00', 'chat')"
        )

    digest = SQLiteGroupDigestProvider(db).load("req-1", "1", "u1")
    assert digest.enabled
    assert "均为群友" in digest.summary
    assert "漂泊者" in digest.summary

    captured: dict[str, object] = {}

    class _CapturingSummarizer:
        def generate(self, messages, **kwargs):
            captured["messages"] = messages

            class _Reply:
                text = "1. 群友问早"

            return _Reply()

    OpenAICompatibleGroupSummarizer(_CapturingSummarizer()).summarize(digest.summary)
    user_prompt = str(captured["messages"][1]["content"])
    assert "均为群友" in user_prompt
    assert "漂泊者" in user_prompt
