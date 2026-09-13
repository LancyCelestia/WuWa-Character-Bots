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
    build_reminder_store,
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


# ---------- 时区口径与过期治理（2026-09-13 bug B 回归） ----------

def test_parse_23_point_cross_midnight() -> None:
    """13:51 说「23点」= 今天 23:00；23:30 说「23点」跨午夜顺延明天 23:00。"""
    intent = parse_reminder_intent(
        "23点提醒我收衣服", now=datetime(2026, 9, 13, 13, 51, tzinfo=_TZ)
    )
    assert intent is not None
    assert intent.remind_at == datetime(2026, 9, 13, 23, 0, tzinfo=_TZ)
    assert intent.label == "今天 23:00"
    late = parse_reminder_intent(
        "23点提醒我收衣服", now=datetime(2026, 9, 13, 23, 30, tzinfo=_TZ)
    )
    assert late is not None
    assert late.remind_at == datetime(2026, 9, 14, 23, 0, tzinfo=_TZ)
    assert late.label == "明天 23:00"


def test_parse_utc_now_wall_clock_stays_in_now_frame() -> None:
    """aware 注入的 now 沿用其时区做墙钟推算：UTC 05:51 说「23点」= 23:00Z。"""
    intent = parse_reminder_intent(
        "23点提醒我收衣服", now=datetime(2026, 9, 13, 5, 51, tzinfo=timezone.utc)
    )
    assert intent is not None
    assert intent.remind_at.astimezone(timezone.utc) == datetime(
        2026, 9, 13, 23, 0, tzinfo=timezone.utc
    )


def test_store_due_compares_instants_across_timezones(tmp_path) -> None:
    """+08:00 存储串 vs UTC now：按时刻比较（旧实现字符串字典序会漏触发）。"""
    store = ReminderStore(tmp_path / "r.sqlite3")
    reminder = store.add(
        session_key="group:1", sender_id="u1", target_scope="group", target_id="1",
        adapter="nonebot", bot_id="bot",
        remind_at=datetime(2026, 9, 13, 21, 30, tzinfo=_TZ),  # = 13:30Z
        text="收衣服",
    )
    now_utc = datetime(2026, 9, 13, 13, 51, tzinfo=timezone.utc)  # = 21:51+08，迟到 21 分钟
    due = store.due(now=now_utc)
    assert [item.reminder_id for item in due] == [reminder.reminder_id]


def test_store_due_on_time_within_grace_delivered(tmp_path) -> None:
    """正常到点（含巡检间隙内的小幅迟到 ≤30 分钟）照常投递。"""
    store = ReminderStore(tmp_path / "r.sqlite3")
    now = datetime(2026, 9, 13, 22, 55, tzinfo=_TZ)
    reminder = store.add(
        session_key="group:1", sender_id="u1", target_scope="group", target_id="1",
        adapter="nonebot", bot_id="bot",
        remind_at=now - timedelta(minutes=5), text="到点件",
    )
    due = store.due(now=now)
    assert [item.reminder_id for item in due] == [reminder.reminder_id]
    assert "到点件" in build_reminder_text(due[0])


def test_store_late_over_30min_postpones_instead_of_delivering(tmp_path) -> None:
    """离线错过 >30 分钟：不原样补投递，顺延到下一个同一时刻（通常明天）。"""
    store = ReminderStore(tmp_path / "r.sqlite3")
    reminder = store.add(
        session_key="group:1", sender_id="u1", target_scope="group", target_id="1",
        adapter="nonebot", bot_id="bot",
        remind_at=datetime(2026, 9, 12, 23, 0, tzinfo=_TZ), text="收衣服",
    )
    now = datetime(2026, 9, 13, 13, 51, tzinfo=_TZ)  # 迟到 ~14.9 小时
    assert store.due(now=now) == []  # 过期不原样投递
    pending = store.list_pending("group:1")
    assert [item.reminder_id for item in pending] == [reminder.reminder_id]  # 仍是待办
    # 顺延到 09-13 23:00（下一个同一时刻；相对原定时刻即"明天同一时刻"）。
    stored = datetime.fromisoformat(pending[0].remind_at)
    assert stored.astimezone(_TZ) == datetime(2026, 9, 13, 23, 0, tzinfo=_TZ)
    # 顺延后到点正常投递，之后不再重复。
    due = store.due(now=datetime(2026, 9, 13, 23, 5, tzinfo=_TZ))
    assert [item.reminder_id for item in due] == [reminder.reminder_id]
    store.mark_done(reminder.reminder_id)
    assert store.due(now=datetime(2026, 9, 13, 23, 6, tzinfo=_TZ)) == []


def test_store_late_beyond_grace_expires(tmp_path) -> None:
    """迟到超 grace_hours（默认 24h）标记 expired，不再投递也不无限顺延。"""
    store = ReminderStore(tmp_path / "r.sqlite3")
    store.add(
        session_key="group:1", sender_id="u1", target_scope="group", target_id="1",
        adapter="nonebot", bot_id="bot",
        remind_at=datetime(2026, 9, 12, 8, 0, tzinfo=_TZ), text="过期件",
    )
    now = datetime(2026, 9, 13, 13, 51, tzinfo=_TZ)  # 迟到 ~29.9 小时
    assert store.due(now=now) == []
    assert store.list_pending("group:1") == []


# ---------- 文案审计三处回归（2026-09-13 收编） ----------


def _tone_capability(tmp_path, monkeypatch):
    import plugins.bot_unified_runtime.character.reminders as reminders_mod

    monkeypatch.setattr(reminders_mod, "_STORES", {})
    return build_reminder_capability(_tone_config(tmp_path))


def _tone_config(tmp_path) -> SimpleNamespace:
    return SimpleNamespace(
        bot_reminder_db_path=str(tmp_path / "r.sqlite3"),
        bot_notes_enabled=False,  # 勾选/取消文案回归只看提醒侧，不建 notes store。
    )


def test_checkoff_ambiguous_copy_is_count_agnostic(tmp_path, monkeypatch) -> None:
    """文案审计①：3 个并列候选时正文不点数（不得写死「两件事」）。"""
    capability = _tone_capability(tmp_path, monkeypatch)
    for index in range(3):
        capability(_message(f"12点提醒我抄作业{['一', '二', '三'][index]}"), object())
    # 「作业」包含于三个事项 → 并列最高分 → ambiguous（前 3 个）。
    result = capability(_message("作业做完了"), object())
    assert result.audit_tags[-1] == "ambiguous" or "ambiguous" in result.audit_tags
    assert "两件事" not in result.body, "并列 3 个时「两件事」是硬编码点数"
    assert "有几件事" in result.body
    for label in ("抄作业一", "抄作业二", "抄作业三"):
        assert label in result.body, "歧义清单应列出全部并列候选"


def test_cancel_ambiguous_copy_is_human(tmp_path, monkeypatch) -> None:
    """文案审计③：取消提醒歧义回执不再是裸机器腔（"需要唯一"）。"""
    capability = _tone_capability(tmp_path, monkeypatch)
    capability(_message("12点提醒我写作业"), object())
    capability(_message("13点提醒我交表"), object())
    store = build_reminder_store(_tone_config(tmp_path))
    # id 是 sha1 截断，前缀碰撞不可控：逐行改成同前缀，锁定歧义分支。
    with store._lock, store._conn:
        first = store._conn.execute(
            "SELECT MIN(reminder_id) FROM reminders"
        ).fetchone()[0]
        store._conn.execute(
            "UPDATE reminders SET reminder_id = 'deadbeef1' WHERE reminder_id = ?",
            (first,),
        )
        store._conn.execute(
            "UPDATE reminders SET reminder_id = 'deadbeef2'"
            " WHERE reminder_id <> 'deadbeef1'"
        )
    result = capability(_message("取消提醒 deadbeef"), object())
    assert "需要唯一" not in result.body and "命中" not in result.body
    assert "deadbeef" in result.body and "提醒列表" in result.body
