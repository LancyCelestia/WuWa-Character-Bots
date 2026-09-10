"""反思回路（character/reflection.py）的回归测试。

全部同步、无网络；LLM 客户端用 stub 对象模拟（不触真实 HTTP）；
时间用假时钟（每次调用 +1s）保证 created_at 排序确定。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from plugins.bot_unified_runtime.character.memory import NullMemoryProvider
from plugins.bot_unified_runtime.character.reflection import (
    FactDraft,
    HeuristicSummarizer,
    LLMSummarizer,
    ReflectionMemoryProvider,
    ReflectionStore,
    Turn,
    gather_turns_by_date,
    run_reflection,
)


class _FakeClock:
    """假时钟：每次读取前进 1 秒，使同库多行 created_at 单调递增。"""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        self.now += 1.0
        return self.now


class _StubReply:
    def __init__(self, text: str) -> None:
        self.text = text


class _StubLLM:
    """OpenAI 兼容客户端的最小 stub：记录调用，可配置为抛异常。"""

    def __init__(self, text: str = "", *, fail: bool = False) -> None:
        self._text = text
        self._fail = fail
        self.calls: list[list[dict[str, str]]] = []

    def generate(self, messages: list[dict[str, str]], **options: object) -> _StubReply:
        if self._fail:
            raise RuntimeError("llm unavailable")
        self.calls.append(messages)
        return _StubReply(self._text)


def _turn(role: str, text: str, created_at: str = "2026-09-10T08:00:00Z", sender_id: str = "") -> Turn:
    return Turn(role=role, text=text, created_at=created_at, sender_id=sender_id)


def _chat_turns() -> list[Turn]:
    return [
        _turn("user", "你好呀", "2026-09-10T08:00:00Z", "u1"),
        _turn("assistant", "你好，今天怎么样？", "2026-09-10T08:00:10Z"),
        _turn("user", "我最喜欢的颜色是蓝色", "2026-09-10T08:01:00Z", "u1"),
        _turn("user", "我最近在学Rust，有点累", "2026-09-10T08:02:00Z", "u1"),
        _turn("assistant", "辛苦了，注意休息", "2026-09-10T08:02:10Z"),
        _turn("user", "我要去北京出差", "2026-09-10T08:03:00Z", "u1"),
    ]


def test_digest_upsert_same_day_replaces_and_supersedes_facts(tmp_path: Path) -> None:
    store = ReflectionStore(tmp_path / "reflection.sqlite3", clock=_FakeClock())
    digest_id = store.save_digest(
        session_key="qq:group:1", scope_date="2026-09-10", summary="v1", turn_count=3
    )
    assert store.save_facts(digest_id, "u1", [FactDraft("我喜欢猫")]) == 1
    assert len(store.facts_for("u1")) == 1

    # 同日重跑：digest_id 确定性相同，整行替换 + 旧事实作废。
    replaced_id = store.save_digest(
        session_key="qq:group:1", scope_date="2026-09-10", summary="v2", turn_count=5
    )
    assert replaced_id == digest_id
    digest = store.digest_for("qq:group:1", "2026-09-10")
    assert digest is not None
    assert digest.summary == "v2"
    assert digest.turn_count == 5
    assert store.facts_for("u1") == []

    # 新一轮归纳重新写入后可见，来源指向新 digest。
    store.save_facts(replaced_id, "u1", [FactDraft("我喜欢猫")])
    facts = store.facts_for("u1")
    assert len(facts) == 1
    assert facts[0].source_digest_id == replaced_id

    # 跨日不互相覆盖。
    other_day = store.save_digest(
        session_key="qq:group:1", scope_date="2026-09-11", summary="d2", turn_count=1
    )
    assert other_day != replaced_id
    assert store.digest_for("qq:group:1", "2026-09-11") is not None


def test_fact_dedupe_by_normalized_text_keeps_newest(tmp_path: Path) -> None:
    store = ReflectionStore(tmp_path / "reflection.sqlite3", clock=_FakeClock())
    digest_a = store.save_digest(
        session_key="s1", scope_date="2026-09-10", summary="a", turn_count=1
    )
    digest_b = store.save_digest(
        session_key="s1", scope_date="2026-09-11", summary="b", turn_count=1
    )
    store.save_facts(digest_a, "u1", [FactDraft("我喜欢猫")])
    # 空白/大小写差异在归一化后视为同一事实：旧行作废，新行 keep。
    store.save_facts(digest_b, "u1", [FactDraft(" 我喜欢 猫 ")])

    facts = store.facts_for("u1")
    assert len(facts) == 1
    assert facts[0].fact_text == "我喜欢 猫"
    assert facts[0].source_digest_id == digest_b


def test_facts_for_filters_superseded_confidence_and_budget(tmp_path: Path) -> None:
    store = ReflectionStore(tmp_path / "reflection.sqlite3", clock=_FakeClock())
    digest_id = store.save_digest(
        session_key="s1", scope_date="2026-09-10", summary="s", turn_count=4
    )
    store.save_facts(digest_id, "u1", [FactDraft("我喜欢猫", "preference", 0.6)])
    store.save_facts(digest_id, "u1", [FactDraft("我喜欢橘猫", "preference", 0.6)])  # 文本不同 → 各自成行
    store.save_facts(digest_id, "u1", [FactDraft("我要学日语", "plan", 0.4)])  # 低于阈值
    store.save_facts(digest_id, "u1", [FactDraft("我住在上海", "identity", 0.5)])  # 边界值应保留

    facts = store.facts_for("u1", limit=10)
    # 0.4 的被过滤；0.5 边界保留；recency-first（后写在前）。
    assert [fact.fact_text for fact in facts] == ["我住在上海", "我喜欢橘猫", "我喜欢猫"]

    # recency-first + limit。
    assert [fact.fact_text for fact in store.facts_for("u1", limit=1)] == ["我住在上海"]

    # max_chars 预算：每条 5 字，预算 10 恰好容纳两条，第三条挤不下。
    budgeted = store.facts_for("u1", limit=10, max_chars=10)
    assert [fact.fact_text for fact in budgeted] == ["我住在上海", "我喜欢橘猫"]

    # 8 字预算：第二条被裁到剩余 3 字（"我喜…"，与 memory.py 的预算行为一致）。
    tight = store.facts_for("u1", limit=10, max_chars=8)
    assert [fact.fact_text for fact in tight] == ["我住在上海", "我喜…"]

    # 其他 sender 不可见；空 sender 恒空。
    assert store.facts_for("u2") == []
    assert store.facts_for("") == []


def test_heuristic_summarizer_extracts_self_facts_deterministically() -> None:
    summarizer = HeuristicSummarizer()
    reflection = summarizer.summarize("qq:group:1", _chat_turns())

    texts = [draft.text for draft in reflection.facts]
    assert any("最喜欢" in text for text in texts)
    assert any("在学Rust" in text for text in texts)
    assert any("要去北京出差" in text for text in texts)
    assert len(reflection.facts) <= 3
    assert all(len(draft.text) <= 60 for draft in reflection.facts)
    # bot 消息里的自述句式不得混入（只有 user 轮参与抽取）。
    assert all("辛苦了" not in text for text in texts)
    # 摘要 = 开场用户消息 + 最后话题。
    assert "开场话题：你好呀" in reflection.summary
    assert "后来聊到：我要去北京出差" in reflection.summary

    # 确定性：同输入两次调用逐字段相等。
    assert summarizer.summarize("qq:group:1", _chat_turns()) == reflection

    # 无用户消息 → 空摘要、零事实。
    empty = summarizer.summarize("s", [_turn("assistant", "我在待机")])
    assert empty.summary == ""
    assert empty.facts == ()


def test_gather_turns_by_date_filters_kind_and_groups_by_session(tmp_path: Path) -> None:
    db_path = tmp_path / "history.sqlite3"
    _create_turns_db(db_path)

    grouped = gather_turns_by_date(db_path, "2026-09-10")
    assert sorted(grouped) == ["qq:group:123", "qq:private:777"]
    group_turns = grouped["qq:group:123"]
    assert [turn.text for turn in group_turns] == ["我喜欢猫", "我最近在学Rust", "好的"]
    # sender_id 从库中带入；command 与跨日行被排除。
    assert group_turns[0].sender_id == "u1"
    assert all("/help" != turn.text for turn in group_turns)
    private = grouped["qq:private:777"]
    assert len(private) == 1
    assert private[0].sender_id == "u2"

    # 日期前缀过滤生效。
    assert sorted(gather_turns_by_date(db_path, "2026-09-11")) == ["qq:group:123"]

    # 库不存在 → 空 dict（调度器据此静默跳过）。
    assert gather_turns_by_date(tmp_path / "missing.sqlite3", "2026-09-10") == {}


def test_run_reflection_caps_sessions_and_reports(tmp_path: Path) -> None:
    store = ReflectionStore(tmp_path / "reflection.sqlite3", clock=_FakeClock())
    turns_by_session: dict[str, list[Turn]] = {}
    for index in range(12):
        key = f"qq:private:{index:03d}"
        turns_by_session[key] = [
            _turn("user", "我最喜欢的颜色是蓝色", sender_id=f"u{index:03d}"),
            _turn("assistant", "好的"),
        ]
    turns_by_session["qq:private:empty"] = []

    report = run_reflection(
        store,
        turns_by_session,
        summarizer=HeuristicSummarizer(),
        scope_date="2026-09-10",
        source_limit_sessions=5,
    )
    assert report.scope_date == "2026-09-10"
    assert report.sessions_seen == 13
    assert report.sessions_processed == 5  # 空会话被跳过
    assert report.digests_saved == 5
    assert report.facts_saved == 5  # 每个会话恰好 1 条自述事实

    # 截断按 session_key 字典序：前 5 个会话有摘要，其后没有。
    for index in range(5):
        assert store.digest_for(f"qq:private:{index:03d}", "2026-09-10") is not None
        facts = store.facts_for(f"u{index:03d}")
        assert len(facts) == 1
        assert facts[0].fact_text.startswith("我最喜欢")
    assert store.digest_for("qq:private:005", "2026-09-10") is None
    assert store.facts_for("u005") == []


def test_reflection_memory_provider_matches_protocol_shapes(tmp_path: Path) -> None:
    # 未配置：与 NullMemoryProvider 行为一致。
    unconfigured = ReflectionMemoryProvider(None)
    null_result = NullMemoryProvider().retrieve(
        request_id="r1",
        requester_id="u1",
        subject_user_id="u1",
        session_id="s",
        query_text="q",
        max_items=5,
        max_chars=900,
    )
    assert unconfigured.retrieve(
        request_id="r1",
        requester_id="u1",
        subject_user_id="u1",
        session_id="s",
        query_text="q",
        max_items=5,
        max_chars=900,
    ) == null_result

    store = ReflectionStore(tmp_path / "reflection.sqlite3", clock=_FakeClock())
    digest_id = store.save_digest(
        session_key="qq:private:1", scope_date="2026-09-10", summary="s", turn_count=2
    )
    store.save_facts(digest_id, "u1", [FactDraft("我喜欢猫", "preference", 0.6)])
    provider = ReflectionMemoryProvider(store)

    result = provider.retrieve(
        request_id="r2",
        requester_id="u1",
        subject_user_id="u1",
        session_id="qq:private:1",
        query_text="我喜欢什么",
        max_items=5,
        max_chars=900,
    )
    assert result.request_id == "r2"
    assert len(result.facts) == 1
    assert result.facts[0]["kind"] == "reflection"
    assert result.facts[0]["text"] == "我喜欢猫"
    assert result.facts[0]["source"] == "reflection"
    assert result.facts[0]["sensitivity"] == "personal"
    assert result.facts[0]["scope_key"] == "session:qq:private:1"
    assert result.confidence == 0.6

    # 隐私闸：查询者非本人 → 空。
    stranger = provider.retrieve(
        request_id="r3",
        requester_id="u2",
        subject_user_id="u1",
        session_id="qq:private:1",
        query_text="q",
        max_items=5,
        max_chars=900,
    )
    assert stranger.facts == []


def test_llm_summarizer_falls_back_without_or_failing_client() -> None:
    turns = _chat_turns()
    heuristic = HeuristicSummarizer().summarize("s", turns)
    # 未注入客户端 → 与启发式逐字段一致。
    assert LLMSummarizer(None).summarize("s", turns) == heuristic
    # 客户端抛异常 → 回退启发式，不向上抛。
    assert LLMSummarizer(_StubLLM(fail=True)).summarize("s", turns) == heuristic


def test_llm_summarizer_parses_stub_client_lines() -> None:
    long_line = "长" * 65  # 超过 60 字上限，应被裁到 59 字 + 省略号
    stub = _StubLLM(f"1. 我喜欢猫\n- 我讨厌香菜\n无\n我喜欢猫\n{long_line}")
    turns = _chat_turns()
    reflection = LLMSummarizer(stub).summarize("s", turns)

    texts = [draft.text for draft in reflection.facts]
    assert texts == ["我喜欢猫", "我讨厌香菜", "长" * 59 + "…"]
    assert all(len(draft.text) <= 60 for draft in reflection.facts)
    assert all(draft.confidence == 0.6 for draft in reflection.facts)
    # 客户端确实被调用了一次，且系统提示词在场。
    assert len(stub.calls) == 1
    assert stub.calls[0][0]["role"] == "system"
    # 摘要句仍为确定性抽取式，不依赖 LLM。
    assert "开场话题：你好呀" in reflection.summary


def _create_turns_db(path: Path) -> None:
    """建一个与 character/history.py 完全同构的 conversation_turns 临时库。

    - 表 DDL 与 history.py:427-437 一致；
    - kind 列对应 history.py:448-452 的 ALTER（NOT NULL DEFAULT 'chat'）；
    - created_at 写入侧为 datetime.now(UTC).isoformat()（history.py:236），
      形如 "2026-09-10T08:00:00+00:00"，按 "YYYY-MM-DD" 前缀命中同一 UTC 日。
    """
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            CREATE TABLE conversation_turns (
                request_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                adapter TEXT NOT NULL,
                bot_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                sender_id TEXT NOT NULL,
                role TEXT NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "ALTER TABLE conversation_turns ADD COLUMN kind TEXT NOT NULL DEFAULT 'chat'"
        )
        rows = [
            ("r1", "qq", "onebot.v11", "bot", "group:123", "u1", "user", "我喜欢猫", "2026-09-10T08:00:00+00:00", "chat"),
            ("r2", "qq", "onebot.v11", "bot", "group:123", "u1", "user", "我最近在学Rust", "2026-09-10T09:00:00+00:00", "chat"),
            ("r3", "qq", "onebot.v11", "bot", "group:123", "u1", "assistant", "好的", "2026-09-10T09:00:10+00:00", "chat"),
            ("r4", "qq", "onebot.v11", "bot", "group:123", "u1", "user", "/help", "2026-09-10T10:00:00+00:00", "command"),
            ("r5", "qq", "onebot.v11", "bot", "private:777", "u2", "user", "我喜欢狗", "2026-09-10T11:00:00+00:00", "chat"),
            ("r6", "qq", "onebot.v11", "bot", "group:123", "u1", "user", "第二天早上的消息", "2026-09-11T00:30:00+00:00", "chat"),
        ]
        connection.executemany(
            "INSERT INTO conversation_turns VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        connection.commit()
    finally:
        connection.close()
