"""提醒（时间点记忆→主动督促）回归：解析矩阵 + 存储 + 能力 + 路由触发。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from plugins.bot_unified_runtime.capabilities.reminder import (
    build_reminder_capability,
    is_reminder_command,
)
from plugins.bot_unified_runtime.character.reminders import (
    ReminderStore,
    build_reminder_text,
    parse_reminder_intent,
)
from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType

_TZ = timezone(timedelta(hours=8))


def _now() -> datetime:
    return datetime(2026, 9, 11, 10, 0, tzinfo=_TZ)


# ---------- 解析矩阵 ----------

def test_parse_absolute_hour_today() -> None:
    intent = parse_reminder_intent("12点提醒我写作业", now=_now())
    assert intent is not None
    assert intent.remind_at == datetime(2026, 9, 11, 12, 0, tzinfo=_TZ)
    assert "写作业" in intent.text
    assert intent.label == "今天 12:00"


def test_parse_no_signal_returns_none() -> None:
    assert parse_reminder_intent("12点要写作业", now=_now()) is None
    assert parse_reminder_intent("提醒我一下", now=_now()) is None


def test_parse_past_time_rolls_to_tomorrow() -> None:
    intent = parse_reminder_intent("9点提醒我交表", now=_now())
    assert intent is not None
    assert intent.remind_at == datetime(2026, 9, 12, 9, 0, tzinfo=_TZ)


def test_parse_tomorrow_morning_period() -> None:
    intent = parse_reminder_intent("明天早上8点叫我起床", now=_now())
    assert intent is not None
    assert intent.remind_at == datetime(2026, 9, 12, 8, 0, tzinfo=_TZ)
    assert "起床" in intent.text


def test_parse_period_only_and_relative() -> None:
    noon = parse_reminder_intent("中午提醒我吃药", now=_now())
    assert noon is not None and noon.remind_at.hour == 12
    half = parse_reminder_intent("半小时后提醒我看看汤", now=_now())
    assert half is not None and half.remind_at == _now() + timedelta(minutes=30)
    hours = parse_reminder_intent("2小时后叫我", now=_now())
    assert hours is not None and hours.remind_at == _now() + timedelta(hours=2)


def test_is_reminder_command_matrix() -> None:
    assert is_reminder_command("12点提醒我写作业")
    assert is_reminder_command("提醒列表")
    assert is_reminder_command("取消提醒 abc123")
    assert not is_reminder_command("提醒我一下")
    assert not is_reminder_command("今天天气怎么样")


# ---------- 存储 ----------

def test_store_add_due_done_and_cancel(tmp_path) -> None:
    store = ReminderStore(tmp_path / "r.sqlite3")
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    reminder = store.add(
        session_key="group:1", sender_id="u1", target_scope="group", target_id="1",
        adapter="nonebot", bot_id="bot", remind_at=past, text="写作业",
    )
    due = store.due()
    assert [item.reminder_id for item in due] == [reminder.reminder_id]
    assert "写作业" in build_reminder_text(due[0])
    store.mark_done(reminder.reminder_id)
    assert store.due() == []

    future = datetime.now(timezone.utc) + timedelta(hours=1)
    second = store.add(
        session_key="group:1", sender_id="u1", target_scope="group", target_id="1",
        adapter="nonebot", bot_id="bot", remind_at=future, text="交表",
    )
    assert len(store.list_pending("group:1")) == 1
    assert store.cancel(second.reminder_id) is True
    assert store.list_pending("group:1") == []


def test_store_pending_cap_evicts_oldest(tmp_path) -> None:
    store = ReminderStore(tmp_path / "r.sqlite3", max_pending_per_session=2)
    base = datetime.now(timezone.utc)
    for index in range(3):
        store.add(
            session_key="group:1", sender_id="u1", target_scope="group", target_id="1",
            adapter="nonebot", bot_id="bot",
            remind_at=base + timedelta(hours=index + 1), text=f"事{index}",
        )
    pending = store.list_pending("group:1", limit=10)
    assert len(pending) == 2
    assert all("事0" not in item.text for item in pending)


# ---------- 能力 ----------

def _message(text: str) -> IncomingMessage:
    return IncomingMessage(
        platform="qq", adapter="nonebot", bot_id="bot-1",
        session_id="group:1", session_type=SessionType.GROUP, sender_id="u1",
        group_id="1", plain_text=text, message_id="m1",
    )


def test_capability_adds_and_confirms(tmp_path, monkeypatch) -> None:
    import plugins.bot_unified_runtime.character.reminders as reminders_mod

    monkeypatch.setattr(reminders_mod, "_STORES", {})
    config = SimpleNamespace(bot_reminder_db_path=str(tmp_path / "r.sqlite3"))
    capability = build_reminder_capability(config)

    class _Decision:
        pass

    result = capability(_message("半小时后提醒我写作业"), _Decision())
    assert "提醒" in result.body and "写作业" in result.body
    listed = capability(_message("提醒列表"), _Decision())
    assert "写作业" in listed.body
