"""时间窗总结回归：意图解析（纯函数）/ 时间窗召回（tmp DB）/ chat 注入挂接。

覆盖三条链路：
1. runtime/time_window.py：N分钟/N小时/复合表达/半小时/今天/最近N条/默认30分钟
   与负样本（内容宾语、无触发词、带链接、叙述句中段触发词）。
2. character/history.py retrieve_window：时间过滤（含边界）、多说话人、
   升序、双预算钳制、命令轮次与当前轮排除、写入侧脱敏可见。
3. capabilities/chat.py：分区助手、prompt 注入块存在性、capability 端到端
   （真实 SQLite 召回 → system prompt 出现【时间窗聊天记录】与指示句）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    ContextBundle,
    IncomingMessage,
    MemoryRetrievalResult,
    PersonaProfile,
    RetrievalResult,
    SessionType,
    ToneProfile,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
    _time_window_summary_section,
    build_chat_prompt_with_diagnostics,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.history import (
    InMemoryConversationHistoryStore,
    SQLiteConversationHistoryRepository,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
    NullCharacterContextProvider,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
    StaticLLMProvider,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.time_window import (
    detect_time_window_summary,
    parse_time_window,
)

NOW = datetime(2026, 9, 13, 15, 0, tzinfo=UTC).timestamp()


def _local_tz() -> object:
    return datetime.now().astimezone().tzinfo


# ---------------------------------------------------------------------------
# 1. 意图解析（纯函数）
# ---------------------------------------------------------------------------


def test_parse_minutes_window() -> None:
    spec = detect_time_window_summary("总结一下5分钟内的消息", now_epoch=NOW)
    assert spec is not None
    assert spec.until_epoch == pytest.approx(NOW)
    assert spec.since_epoch == pytest.approx(NOW - 300)
    assert "5分钟" in spec.description
    assert spec.max_turns == 0


def test_parse_hours_window() -> None:
    spec = detect_time_window_summary("总结一下2小时内的聊天", now_epoch=NOW)
    assert spec is not None
    assert spec.since_epoch == pytest.approx(NOW - 7200)
    assert "2小时" in spec.description


def test_parse_compound_hour_and_minute() -> None:
    spec = detect_time_window_summary("总结一下1小时30分钟内的消息", now_epoch=NOW)
    assert spec is not None
    assert spec.since_epoch == pytest.approx(NOW - 5400)


def test_parse_half_hour_and_chinese_numeral() -> None:
    half = detect_time_window_summary("总结一下半小时内群里聊了什么", now_epoch=NOW)
    assert half is not None and half.since_epoch == pytest.approx(NOW - 1800)
    one_hour = detect_time_window_summary("总结一小时内的消息", now_epoch=NOW)
    assert one_hour is not None and one_hour.since_epoch == pytest.approx(NOW - 3600)


def test_parse_today_window_uses_local_midnight() -> None:
    spec = detect_time_window_summary("总结一下今天群里的聊天", now_epoch=NOW)
    assert spec is not None
    expected_midnight = (
        datetime.fromtimestamp(NOW, tz=_local_tz())  # type: ignore[arg-type]
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .timestamp()
    )
    assert spec.since_epoch == pytest.approx(expected_midnight)
    assert "今天" in spec.description


def test_parse_recent_n_messages() -> None:
    spec = detect_time_window_summary("总结一下最近20条消息", now_epoch=NOW)
    assert spec is not None
    assert spec.max_turns == 20
    assert spec.until_epoch == pytest.approx(NOW)
    assert "20条" in spec.description


def test_default_window_without_time_word() -> None:
    for text in ("帮我总结一下", "总结一下", "总结一下大家刚才说的话"):
        spec = detect_time_window_summary(text, now_epoch=NOW)
        assert spec is not None, text
        assert spec.since_epoch == pytest.approx(NOW - 1800)
        assert "30分钟" in spec.description


def test_parse_time_window_without_expression_returns_none() -> None:
    assert parse_time_window("没有任何时间表达", now_epoch=NOW) is None


def test_negative_cases_never_trigger() -> None:
    # 内容宾语：总结的是内容而非聊天记录。
    assert detect_time_window_summary("总结一下这篇文章的论点", now_epoch=NOW) is None
    assert detect_time_window_summary("帮我总结一下今天的新闻", now_epoch=NOW) is None
    # 无触发词。
    assert detect_time_window_summary("今天天气不错", now_epoch=NOW) is None
    assert detect_time_window_summary("聊天记录", now_epoch=NOW) is None
    # 带链接（让位链接解析）。
    assert (
        detect_time_window_summary("总结一下 https://example.com 这条链接", now_epoch=NOW)
        is None
    )
    # 触发词在叙述句中段且无时间词：默认路径锚定失败。
    assert detect_time_window_summary("我来总结一下", now_epoch=NOW) is None
    assert detect_time_window_summary("这个问题总结一下就是答案", now_epoch=NOW) is None


# ---------------------------------------------------------------------------
# 2. retrieve_window（tmp DB）
# ---------------------------------------------------------------------------


def _seed_repository(tmp_path) -> SQLiteConversationHistoryRepository:
    repo = SQLiteConversationHistoryRepository(tmp_path / "history.sqlite3")
    base = datetime.now(UTC)

    def seed(sender: str, text: str, *, offset_seconds: float, kind: str = "chat",
             request_id: str = "seed") -> None:
        repo.append_turn(
            request_id=request_id,
            platform="qq",
            adapter="onebot",
            bot_id="b",
            session_id="group:g",
            sender_id=sender,
            role="user",
            text=text,
            kind=kind,
        )

    def stamp(text: str, offset_seconds: float) -> None:
        iso = datetime.fromtimestamp(
            base.timestamp() + offset_seconds, tz=UTC
        ).isoformat()
        with repo._connect() as connection:
            cursor = connection.execute(
                "UPDATE conversation_turns SET created_at = ? WHERE text = ?",
                (iso, text),
            )
            assert cursor.rowcount == 1

    seed("alice", "太早的旧消息", offset_seconds=-3600)
    seed("alice", "第一题选A", offset_seconds=-240)
    seed("bob", "我觉得选B", offset_seconds=-120)
    seed("carol", "@alice 看看这个", offset_seconds=-60)
    seed("dave", "/bot status", offset_seconds=-30, kind="command")
    seed("eve", "未来的消息", offset_seconds=600)
    for text, offset in (
        ("太早的旧消息", -3600),
        ("第一题选A", -240),
        ("我觉得选B", -120),
        ("@alice 看看这个", -60),
        ("/bot status", -30),
        ("未来的消息", 600),
    ):
        stamp(text, offset)
    return repo


def _fetch_window(repo: SQLiteConversationHistoryRepository, **overrides):
    kwargs: dict[str, object] = {
        "platform": "qq",
        "adapter": "onebot",
        "bot_id": "b",
        "session_id": "group:g",
        "since_epoch": (datetime.now(UTC) - timedelta(minutes=5)).timestamp(),
        "until_epoch": (datetime.now(UTC) + timedelta(minutes=1)).timestamp(),
        "max_turns": 50,
        "max_chars": 4000,
    }
    kwargs.update(overrides)
    return repo.retrieve_window(**kwargs)  # type: ignore[arg-type]


def test_window_filters_by_time_and_keeps_all_senders(tmp_path) -> None:
    repo = _seed_repository(tmp_path)
    turns = _fetch_window(repo)
    assert [(turn.sender_id, turn.text) for turn in turns] == [
        ("alice", "第一题选A"),
        ("bob", "我觉得选B"),
        ("carol", "@alice 看看这个"),
    ]
    # 命令轮次与窗外消息都被排除；时间升序。
    assert all("/bot" not in turn.text for turn in turns)


def test_window_respects_max_turns_budget(tmp_path) -> None:
    repo = _seed_repository(tmp_path)
    turns = _fetch_window(repo, max_turns=2)
    assert [turn.text for turn in turns] == ["我觉得选B", "@alice 看看这个"]


def test_window_clips_long_text_to_max_chars(tmp_path) -> None:
    repo = SQLiteConversationHistoryRepository(tmp_path / "clip.sqlite3")
    long_text = "冰" * 200
    repo.append_turn(
        request_id="r",
        platform="qq",
        adapter="onebot",
        bot_id="b",
        session_id="group:g",
        sender_id="alice",
        role="user",
        text=long_text,
    )
    now = datetime.now(UTC).timestamp()
    turns = repo.retrieve_window(
        platform="qq",
        adapter="onebot",
        bot_id="b",
        session_id="group:g",
        since_epoch=now - 60,
        until_epoch=now + 60,
        max_turns=10,
        max_chars=50,
    )
    assert len(turns) == 1
    assert len(turns[0].text) == 50
    assert turns[0].text.endswith("…")


def test_window_excludes_current_request_id(tmp_path) -> None:
    repo = SQLiteConversationHistoryRepository(tmp_path / "exclude.sqlite3")
    repo.append_turn(
        request_id="current",
        platform="qq",
        adapter="onebot",
        bot_id="b",
        session_id="group:g",
        sender_id="alice",
        role="user",
        text="总结一下5分钟内的消息",
    )
    now = datetime.now(UTC).timestamp()
    common = {
        "platform": "qq",
        "adapter": "onebot",
        "bot_id": "b",
        "session_id": "group:g",
        "since_epoch": now - 60,
        "until_epoch": now + 60,
        "max_turns": 10,
        "max_chars": 500,
    }
    assert repo.retrieve_window(**common, exclude_request_id="current") == []
    kept = repo.retrieve_window(**common)
    assert [turn.text for turn in kept] == ["总结一下5分钟内的消息"]


def test_window_sees_write_side_redaction(tmp_path) -> None:
    repo = SQLiteConversationHistoryRepository(tmp_path / "redact.sqlite3")
    repo.append_turn(
        request_id="r",
        platform="qq",
        adapter="onebot",
        bot_id="b",
        session_id="group:g",
        sender_id="alice",
        role="user",
        text="我的 api_key=abcdef12345 别外传",
    )
    now = datetime.now(UTC).timestamp()
    turns = repo.retrieve_window(
        platform="qq",
        adapter="onebot",
        bot_id="b",
        session_id="group:g",
        since_epoch=now - 60,
        until_epoch=now + 60,
        max_turns=10,
        max_chars=500,
    )
    assert len(turns) == 1
    assert "abcdef12345" not in turns[0].text
    assert "[redacted]" in turns[0].text


def test_window_rejects_invalid_budgets(tmp_path) -> None:
    repo = SQLiteConversationHistoryRepository(tmp_path / "invalid.sqlite3")
    now = datetime.now(UTC).timestamp()
    common = {
        "platform": "qq",
        "adapter": "onebot",
        "bot_id": "b",
        "session_id": "group:g",
        "since_epoch": now - 60,
        "until_epoch": now + 60,
    }
    assert repo.retrieve_window(**common, max_turns=0, max_chars=100) == []
    assert repo.retrieve_window(**common, max_turns=10, max_chars=0) == []


def test_in_memory_store_window() -> None:
    store = InMemoryConversationHistoryStore()
    store.append_turn(
        request_id="r",
        platform="console",
        adapter="console",
        bot_id="b",
        session_id="s",
        sender_id="alice",
        role="user",
        text="内存版也支持",
    )
    now = datetime.now(UTC).timestamp()
    turns = store.retrieve_window(
        platform="console",
        adapter="console",
        bot_id="b",
        session_id="s",
        since_epoch=now - 60,
        until_epoch=now + 60,
        max_turns=10,
        max_chars=200,
    )
    assert len(turns) == 1
    assert turns[0].text == "内存版也支持"


# ---------------------------------------------------------------------------
# 3. chat 注入挂接
# ---------------------------------------------------------------------------


class _FixedWindowHistory:
    """测试替身：记录 retrieve_window 入参并返回固定记录。"""

    def __init__(self, turns: list) -> None:
        self.turns = turns
        self.kwargs: dict[str, object] | None = None

    def retrieve_window(self, **kwargs):
        self.kwargs = kwargs
        return self.turns


def _group_message(plain_text: str) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="b",
        session_id="group:g",
        session_type=SessionType.GROUP,
        sender_id="alice",
        group_id="g",
        plain_text=plain_text,
        mentions_bot=True,
    )


def test_section_helper_builds_block_and_degrades_to_empty() -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.character.history import (
        HistoryWindowTurn,
    )

    history = _FixedWindowHistory(
        [
            HistoryWindowTurn(
                sender_id="bob",
                role="user",
                text="今晚吃什么",
                created_at="2026-09-13T14:58:00+00:00",
            )
        ]
    )
    provider = NullCharacterContextProvider()
    provider.conversation_history_provider = history  # type: ignore[attr-defined]
    message = _group_message("总结一下5分钟内的消息")
    section = _time_window_summary_section(
        provider, message, "总结一下5分钟内的消息", now_epoch=NOW
    )
    assert section.startswith("时间窗：")
    assert "bob: 今晚吃什么" in section
    assert "按话题归纳要点" in section
    assert "@提到但没说话的人" in section
    assert history.kwargs is not None
    assert history.kwargs["platform"] == "qq"
    assert history.kwargs["session_id"] == "group:g"
    assert history.kwargs["exclude_request_id"] == message.request_id
    # 未命中意图 → 空串，召回根本不发生。
    history.kwargs = None
    assert (
        _time_window_summary_section(provider, message, "你好", now_epoch=NOW) == ""
    )
    assert history.kwargs is None
    # 无历史存储 → 空串。
    assert (
        _time_window_summary_section(
            NullCharacterContextProvider(), message, "总结一下5分钟内的消息", now_epoch=NOW
        )
        == ""
    )


def _minimal_context() -> ContextBundle:
    return ContextBundle(
        request_id="r",
        persona=PersonaProfile(
            profile_id="p",
            version="0",
            display_name="守岸人",
            identity="测试人格",
        ),
        tone=ToneProfile(profile_id="p", mode="private_chat"),
        memory_results=MemoryRetrievalResult(request_id="r"),
        knowledge_results=RetrievalResult(request_id="r"),
        current_message="总结一下5分钟内的消息",
        sender_id="alice",
        session_id="group:g",
    )


def test_prompt_builder_injects_time_window_section() -> None:
    section = "时间窗：最近5分钟\n- bob: 今晚吃什么\n\n用户要求总结这段时间的聊天。"
    messages, _ = build_chat_prompt_with_diagnostics(
        _minimal_context(), time_window_section=section
    )
    system = messages[0]["content"]
    assert "【时间窗聊天记录】" in system
    assert "- bob: 今晚吃什么" in system
    # 不传分区 → 标签不出现（向后兼容）。
    plain_messages, _ = build_chat_prompt_with_diagnostics(_minimal_context())
    assert "【时间窗聊天记录】" not in plain_messages[0]["content"]


class _RecordingLLM(StaticLLMProvider):
    def __init__(self) -> None:
        super().__init__(text="好的，我来总结。")
        self.messages: list[dict[str, str]] | None = None

    def generate(self, messages, **kwargs):  # type: ignore[no-untyped-def]
        self.messages = messages
        return super().generate(messages, **kwargs)


def test_capability_end_to_end_injects_window_into_system_prompt(tmp_path) -> None:
    repo = _seed_repository(tmp_path)
    character = NullCharacterContextProvider()
    character.conversation_history_provider = repo  # type: ignore[attr-defined]
    llm = _RecordingLLM()
    capability = _build_capability(character, llm)
    message = _group_message("总结一下5分钟内的消息")
    decision = _decision(message)
    capability(message, decision)
    assert llm.messages is not None
    system = llm.messages[0]["content"]
    assert "【时间窗聊天记录】" in system
    assert "第一题选A" in system
    assert "按话题归纳要点" in system
    assert "/bot status" not in system


def test_capability_without_intent_never_touches_window(tmp_path) -> None:
    history = _FixedWindowHistory([])
    character = NullCharacterContextProvider()
    character.conversation_history_provider = history  # type: ignore[attr-defined]
    llm = _RecordingLLM()
    capability = _build_capability(character, llm)
    message = _group_message("你好")
    capability(message, _decision(message))
    assert history.kwargs is None
    assert llm.messages is not None
    assert "【时间窗聊天记录】" not in llm.messages[0]["content"]


def _build_capability(character_provider, llm):  # type: ignore[no-untyped-def]
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
        build_chat_capability,
    )

    return build_chat_capability(character_provider, llm)


def _decision(message: IncomingMessage) -> BotDecision:
    return BotDecision(
        request_id=message.request_id,
        should_respond=True,
        mode="chat",
        trigger="mention",
        capability_id="bot.chat",
        target_scope=SessionType.GROUP,
        context_budget=12000,
        decision_reason="test",
        max_messages=0,
    )
