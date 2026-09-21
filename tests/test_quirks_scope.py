"""persona_quirks scope 维度回归（审查 G-07 跨用户泄漏防线）。

覆盖：
①user scope 怪癖只进本人 prompt，他人/无 sender 上下文零渲染；
②global 怪癖全员渲染（既有语义不变）；
③反思投喂条目默认 user scope 且带来源 sender，approve 后不外溢；
④旧库（无 scope 列）自动迁移后旧条目=global；
⑤管理员直添仍 global（含命中 pending/retired 的 scope 语义）。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.character.quirks import (
    SCOPE_GLOBAL,
    SCOPE_USER,
    QuirkStore,
    format_scope_label,
)
from plugins.bot_unified_runtime.character.reflection import (
    FactDraft,
    HeuristicSummarizer,
    ReflectionStore,
    Turn,
    build_reflection_quirk_proposer,
    run_reflection,
)


class _StepClock:
    """可注入时钟：每次调用前进 1 秒，保证时间戳严格递增（同 test_quirks）。"""

    def __init__(self) -> None:
        self._moment = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        current = self._moment
        self._moment += timedelta(seconds=1)
        return current


def _make_store(tmp_path: Path, name: str = "persona_quirks.sqlite3") -> QuirkStore:
    return QuirkStore(tmp_path / name, clock=_StepClock())


class _Config:
    """build_reflection_quirk_proposer 所需的最小配置面（全开、门槛 0.5）。"""

    bot_quirks_enabled = True
    bot_reflection_quirks_propose_enabled = True
    bot_quirks_db_path = "data/persona_quirks.sqlite3"
    bot_reflection_quirks_min_confidence = 0.5


# ---- ① user scope 只进本人 prompt ----


def test_user_scope_renders_only_for_owner(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    quirk = store.propose(
        "我很喜欢弹吉他", "reflection", scope_kind=SCOPE_USER, scope_key="alice"
    )
    assert quirk.scope_kind == "user"
    assert quirk.scope_key == "alice"
    assert store.approve(quirk.quirk_id) is True
    # 本人上下文可见（sender 两侧空白容忍，与 scope_key 存储口径一致）。
    assert "吉他" in store.render_prompt_section(sender_id="alice")
    assert "吉他" in store.render_prompt_section(sender_id="  alice  ")
    # 他人上下文零渲染；无 sender（未知会话）fail-closed 零渲染。
    assert store.render_prompt_section(sender_id="bob") == ""
    assert store.render_prompt_section() == ""


def test_mixed_scope_render_and_budget(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.add_direct("全局习惯甲", "admin")
    store.add_direct("全局习惯乙", "admin")
    user_quirk = store.propose(
        "我很喜欢弹吉他", "reflection", scope_kind=SCOPE_USER, scope_key="alice"
    )
    assert store.approve(user_quirk.quirk_id) is True
    mine = store.render_prompt_section(sender_id="alice", max_active=6)
    assert "全局习惯甲" in mine and "全局习惯乙" in mine and "吉他" in mine
    # alice 视角 = global 2 条 + 本人 user 1 条。
    assert mine.count("\n- ") == 3
    theirs = store.render_prompt_section(sender_id="bob", max_active=6)
    assert "全局习惯乙" in theirs and "吉他" not in theirs
    assert theirs.count("\n- ") == 2


def test_propose_rejects_unknown_scope_kind(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    with pytest.raises(ValueError):
        store.propose("某习惯", "reflection", scope_kind="everyone")


# ---- ② global 全员渲染（既有语义不变）----


def test_global_scope_renders_for_everyone(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    quirk = store.add_direct("睡前会检查星星有没有归位", "admin")
    assert quirk.scope_kind == SCOPE_GLOBAL
    assert quirk.scope_key == ""
    for viewer in (None, "", "alice", "bob"):
        assert "星星" in store.render_prompt_section(sender_id=viewer)


# ---- ③ 反思投喂默认 user scope 且带来源 ----


def _reflection_turns() -> list[Turn]:
    return [
        Turn(
            role="user",
            text="我很喜欢弹吉他",
            created_at="2026-09-12T01:00:00Z",
            sender_id="alice",
        ),
        Turn(
            role="user",
            text="我住在上海",
            created_at="2026-09-12T01:01:00Z",
            sender_id="bob",
        ),
        # 无 sender 的历史轮次：主流程回退主 sender（并列取字典序最小 = alice）。
        Turn(role="user", text="我要学Python", created_at="2026-09-12T01:02:00Z"),
    ]


def test_reflection_feed_is_user_scoped_with_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.character import providers

    monkeypatch.setattr(
        providers,
        "build_runtime_data_path",
        lambda config, value: tmp_path / value,
    )
    proposer = build_reflection_quirk_proposer(_Config())
    assert proposer is not None
    collected: list[FactDraft] = []

    def _collector(facts: Sequence[FactDraft]) -> None:
        collected.extend(facts)
        proposer(facts)

    store = ReflectionStore(tmp_path / "reflection.sqlite3")
    run_reflection(
        store,
        {"qq:g1": _reflection_turns()},
        summarizer=HeuristicSummarizer(),
        scope_date="2026-09-12",
        quirk_collector=_collector,
    )
    quirk_store = QuirkStore(tmp_path / "data/persona_quirks.sqlite3")
    rows = {
        q.quirk_text: q for q in quirk_store.list(status="pending_review", limit=100)
    }
    assert set(rows) == {"我很喜欢弹吉他", "我住在上海", "我要学Python"}
    assert all(q.source == "reflection" for q in rows.values())
    assert all(q.scope_kind == "user" for q in rows.values())
    assert rows["我很喜欢弹吉他"].scope_key == "alice"
    assert rows["我住在上海"].scope_key == "bob"
    assert rows["我要学Python"].scope_key == "alice"
    # approve 后只在本人上下文渲染，绝不外溢。
    assert quirk_store.approve(rows["我很喜欢弹吉他"].quirk_id) is True
    assert "吉他" in quirk_store.render_prompt_section(sender_id="alice")
    assert quirk_store.render_prompt_section(sender_id="bob") == ""


def test_unattributed_proposal_renders_nobody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """归属链拿不到 sender 的自动提案：user+空 key，approve 后也渲染不到任何人。"""
    from plugins.bot_unified_runtime.domains.chat_reply.character import providers

    monkeypatch.setattr(
        providers,
        "build_runtime_data_path",
        lambda config, value: tmp_path / value,
    )
    proposer = build_reflection_quirk_proposer(_Config())
    assert proposer is not None
    assert (
        proposer(
            [FactDraft(text="我很喜欢弹吉他", category="preference", confidence=0.5)]
        )
        == 1
    )
    quirk_store = QuirkStore(tmp_path / "data/persona_quirks.sqlite3")
    (row,) = quirk_store.list(status="pending_review", limit=10)
    assert row.scope_kind == "user" and row.scope_key == ""
    assert format_scope_label(row) == "user:（无来源）"
    assert quirk_store.approve(row.quirk_id) is True
    assert quirk_store.render_prompt_section(sender_id="alice") == ""
    assert quirk_store.render_prompt_section() == ""


# ---- ④ 旧库自动迁移：存量条目 = global ----


def test_legacy_db_without_scope_columns_migrates_to_global(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE persona_quirks (
            quirk_id TEXT PRIMARY KEY,
            quirk_text TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending_review',
            source TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            reviewed_at TEXT
        )
        """
    )
    connection.execute(
        "INSERT INTO persona_quirks"
        " (quirk_id, quirk_text, status, source, created_at, reviewed_at)"
        " VALUES ('legacy1', '旧库里的全局习惯', 'active', 'admin',"
        " '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
    )
    connection.commit()
    connection.close()

    store = QuirkStore(path, clock=_StepClock())
    active = store.list_active(limit=10)
    assert len(active) == 1
    assert active[0].scope_kind == "global" and active[0].scope_key == ""
    # 迁移后渲染语义与旧版一致：全员可见。
    assert "旧库里的全局习惯" in store.render_prompt_section()
    assert "旧库里的全局习惯" in store.render_prompt_section(sender_id="stranger")
    # 迁移后的库继续接受 user scope 条目。
    scoped = store.propose(
        "我很喜欢弹吉他", "reflection", scope_kind=SCOPE_USER, scope_key="alice"
    )
    assert store.approve(scoped.quirk_id) is True
    assert "吉他" in store.render_prompt_section(sender_id="alice")
    assert "吉他" not in store.render_prompt_section(sender_id="stranger")
    store.close()


# ---- ⑤ 管理员直添 global + 命中语义 ----


def test_add_direct_stays_global_and_hit_semantics(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    fresh = store.add_direct("下雨天想把伞让给别人", "admin")
    assert fresh.scope_kind == SCOPE_GLOBAL and fresh.scope_key == ""
    assert "让给别人" in store.render_prompt_section()

    # 命中 pending 的 user 提案：当场转正但保持 user scope（=approve 语义，G-07）。
    pending = store.propose(
        "我很喜欢弹吉他", "reflection", scope_kind=SCOPE_USER, scope_key="alice"
    )
    direct = store.add_direct("  我很喜欢弹吉他  ", "admin")
    assert direct.quirk_id == pending.quirk_id
    assert direct.status == "active"
    assert direct.scope_kind == "user" and direct.scope_key == "alice"
    assert "吉他" not in store.render_prompt_section()
    assert "吉他" in store.render_prompt_section(sender_id="alice")

    # 命中 retired：按管理员本次直添意图复活为 global。
    assert store.retire(fresh.quirk_id) is True
    revived = store.add_direct("下雨天想把伞让给别人", "admin")
    assert revived.status == "active"
    assert revived.scope_kind == SCOPE_GLOBAL and revived.scope_key == ""
    assert "让给别人" in store.render_prompt_section(sender_id="bob")


def test_retired_user_scope_revive_carries_new_scope(tmp_path: Path) -> None:
    """propose 复活 retired 行：scope 以本次提案为准（新证据新归属）。"""
    store = _make_store(tmp_path)
    first = store.propose(
        "我很喜欢弹吉他", "reflection", scope_kind=SCOPE_USER, scope_key="alice"
    )
    store.retire(first.quirk_id)
    revived = store.propose(
        "我很喜欢弹吉他", "reflection", scope_kind=SCOPE_USER, scope_key="bob"
    )
    assert revived.status == "pending_review"
    assert revived.scope_kind == "user" and revived.scope_key == "bob"
    # 旧 scope 不复活：alice 视角仍渲染不到。
    store.approve(revived.quirk_id)
    assert store.render_prompt_section(sender_id="alice") == ""
    assert "吉他" in store.render_prompt_section(sender_id="bob")


def test_scope_label_formatting(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    global_quirk = store.add_direct("习惯甲", "admin")
    user_quirk = store.propose(
        "我很喜欢弹吉他", "reflection", scope_kind=SCOPE_USER, scope_key="12345"
    )
    assert format_scope_label(global_quirk) == "global"
    assert format_scope_label(user_quirk) == "user:12345"
