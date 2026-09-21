"""自然语言勾选回归（2026-09-13 六域批）：命中 / 歧义 / 未命中 + 笔记待办。

「做完了/完成了/搞定 + 事项名」→ 模糊匹配（包含 + 编辑距离）未完成提醒
与笔记待办；命中即勾选并回守岸人口吻确认，未命中给最接近候选。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import plugins.bot_unified_runtime.domains.schedule.store.reminders as reminders_mod
from plugins.bot_unified_runtime.capabilities.reminder import (
    build_reminder_capability,
    extract_checkoff_query,
    is_reminder_command,
)
from plugins.bot_unified_runtime.character import notes_store as notes_store_mod
from plugins.bot_unified_runtime.character.notes_store import reset_stores_for_tests
from plugins.bot_unified_runtime.character.reminders import (
    ReminderStore,
    resolve_todo_match,
)
from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType


def _config(tmp_path) -> SimpleNamespace:
    return SimpleNamespace(
        bot_reminder_db_path=str(tmp_path / "r.sqlite3"),
        bot_notes_db_path=str(tmp_path / "n.sqlite3"),
    )


def _message(text: str) -> IncomingMessage:
    return IncomingMessage(
        platform="qq", adapter="nonebot", bot_id="bot-1",
        session_id="group:1", session_type=SessionType.GROUP, sender_id="u1",
        group_id="1", plain_text=text, message_id="m1",
    )


def _setup(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(reminders_mod, "_STORES", {})
    reset_stores_for_tests()


def _add_pending(store: ReminderStore, text: str, *, minutes_ahead: int = 60) -> None:
    store.add(
        session_key="group:1", sender_id="u1", target_scope="group", target_id="1",
        adapter="nonebot", bot_id="bot",
        remind_at=datetime.now(timezone.utc) + timedelta(minutes=minutes_ahead),
        text=text,
    )


# ---------- 形态提取 ----------

def test_checkoff_query_extraction_matrix() -> None:
    assert extract_checkoff_query("作业做完了") == "作业"
    assert extract_checkoff_query("把数学作业做完了") == "数学作业"
    assert extract_checkoff_query("搞定了年度报告") == "年度报告"
    assert extract_checkoff_query("报告搞定了") == "报告"
    assert extract_checkoff_query("写完了吗") is None  # 疑问不勾。
    assert extract_checkoff_query("做完了") is None  # 光杆无事项：让位聊天。
    assert extract_checkoff_query("做完") is None
    assert (
        extract_checkoff_query("今天的这份拖了整整一个月的年度总结报告终于做完了好开心呀真的太轻松了")
        is None
    )  # 超长叙事不进勾选面（>32 字守护）。


# ---------- 纯匹配器 ----------

def test_resolve_todo_match_hit_ambiguous_miss() -> None:
    names = ["写数学作业", "写语文作业", "取快递"]
    outcome, indexes = resolve_todo_match("作业做完了".replace("做完了", ""), names)
    assert outcome == "ambiguous" and len(indexes) == 2  # 作业 同时命中两件。
    outcome, indexes = resolve_todo_match("数学", names)
    assert outcome == "hit" and names[indexes[0]] == "写数学作业"
    outcome, _indexes = resolve_todo_match("打扫卫生", names)
    assert outcome == "miss"


# ---------- 端到端（能力层） ----------

def test_checkoff_hits_pending_reminder(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    store = ReminderStore(tmp_path / "r.sqlite3")
    _add_pending(store, "写作业")
    capability = build_reminder_capability(_config(tmp_path))
    result = capability(_message("作业做完了"), object())
    assert "写作业" in result.body
    assert "放下" in result.body or "完成" in result.body
    assert store.list_pending("group:1") == [], "命中后应把提醒勾掉"


def test_checkoff_ambiguous_asks_which(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    store = ReminderStore(tmp_path / "r.sqlite3")
    _add_pending(store, "写数学作业")
    _add_pending(store, "写语文作业")
    capability = build_reminder_capability(_config(tmp_path))
    result = capability(_message("作业做完了"), object())
    assert "哪一件" in result.body
    assert "写数学作业" in result.body and "写语文作业" in result.body
    assert len(store.list_pending("group:1")) == 2, "歧义时都不勾"


def test_checkoff_miss_offers_nearest(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    store = ReminderStore(tmp_path / "r.sqlite3")
    _add_pending(store, "交周报")
    capability = build_reminder_capability(_config(tmp_path))
    result = capability(_message("交报告做完了"), object())
    # 「交报告」与「交周报」编辑距离相近但低于命中线：给最接近候选问一句。
    assert "交周报" in result.body and "是指" in result.body
    assert len(store.list_pending("group:1")) == 1, "未命中不误勾"


def test_checkoff_marks_note_todo(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    notes_store_mod.NotesStore(tmp_path / "n.sqlite3").add(
        user_id="u1", chat_id="group:1", content_md="采购清单\n- [ ] 买牛奶",
    )
    store = ReminderStore(tmp_path / "r.sqlite3")
    _add_pending(store, "写作业")
    capability = build_reminder_capability(_config(tmp_path))
    result = capability(_message("买牛奶搞定了"), object())
    assert "买牛奶" in result.body
    note = notes_store_mod.NotesStore(tmp_path / "n.sqlite3").list_open_todos("group:1")
    assert note == [], "笔记待办应被勾掉"
    done_note = notes_store_mod.NotesStore(tmp_path / "n.sqlite3").list_notes("group:1")[0]
    assert done_note.todo_state == "done" and done_note.done_at


def test_checkoff_without_candidates_falls_back_to_usage(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    capability = build_reminder_capability(_config(tmp_path))
    result = capability(_message("作业做完了"), object())
    # 会话里没有任何候选：不让勾选面抢话，落回提醒用法提示。
    assert "什么时候提醒你" in result.body


def test_routing_recognizes_checkoff_shape() -> None:
    assert is_reminder_command("作业做完了")
    assert is_reminder_command("搞定了年度报告")
    assert not is_reminder_command("做完了")  # 光杆让位聊天。
    long_story = "今天的这份拖了整整一个月的年度总结报告终于做完了好开心呀真的太轻松了"
    assert not is_reminder_command(long_story)  # 超长叙事不进勾选面。


def test_reminder_signal_beats_checkoff(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    capability = build_reminder_capability(_config(tmp_path))
    result = capability(_message("6点提醒我做完作业"), object())
    assert "记下了" in result.body, "含提醒信号的句子归提醒语义，不被勾选面截走"
