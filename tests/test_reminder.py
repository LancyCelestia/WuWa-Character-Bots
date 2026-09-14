"""提醒（时间点记忆→主动督促）回归：解析矩阵 + 存储 + 能力 + 路由触发。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.capabilities import reminder as reminder_cap_mod
from plugins.bot_unified_runtime.capabilities.reminder import (
    build_reminder_capability,
    clear_checkoff_pending_for_tests,
    is_reminder_command,
)
from plugins.bot_unified_runtime.character.reminders import (
    ReminderStore,
    build_reminder_store,
    build_reminder_text,
    parse_reminder_intent,
    resolve_todo_match,
)
from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType

_TZ = timezone(timedelta(hours=8))


@pytest.fixture(autouse=True)
def _isolated_checkoff_pending_state():
    """勾选消歧追问状态是模块级单例：每例前后清零，防跨用例/跨文件泄漏
    （残留追问会让别的用例里 is_reminder_command("是") 意外放行）。"""
    clear_checkoff_pending_for_tests()
    yield
    clear_checkoff_pending_for_tests()


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


def test_store_pending_cap_rejects_instead_of_evicting(tmp_path) -> None:
    """审查 A-07：清单满（默认 20）拒绝新增返回 None，绝不静默删最旧一条。"""
    store = ReminderStore(tmp_path / "r.sqlite3")
    assert store.max_pending == 20
    base = datetime.now(timezone.utc)
    for index in range(store.max_pending):
        assert store.add(
            session_key="group:1", sender_id="u1", target_scope="group", target_id="1",
            adapter="nonebot", bot_id="bot",
            remind_at=base + timedelta(hours=index + 1), text=f"事{index}",
        ) is not None
    pending = store.list_pending("group:1", limit=50)
    assert len(pending) == store.max_pending
    # 满：新增被拒（None），且最早一条原封不动。
    assert store.add(
        session_key="group:1", sender_id="u1", target_scope="group", target_id="1",
        adapter="nonebot", bot_id="bot",
        remind_at=base + timedelta(hours=99), text="挤不进的一条",
    ) is None
    still = store.list_pending("group:1", limit=50)
    assert len(still) == store.max_pending
    assert all("挤不进" not in item.text for item in still)
    assert any("事0" in item.text for item in still), "最旧一条不得被挤掉"


def test_parse_half_hour_suffix() -> None:
    """审查 A-09：「7点半」= 7:30（旧正则无「半」分支会落到 7:00）。"""
    intent = parse_reminder_intent(
        "7点半提醒我吃饭", now=datetime(2026, 9, 14, 6, 0, tzinfo=_TZ)
    )
    assert intent is not None
    assert intent.remind_at == datetime(2026, 9, 14, 7, 30, tzinfo=_TZ)
    late = parse_reminder_intent(
        "明天早上7点半叫我起床", now=datetime(2026, 9, 14, 23, 30, tzinfo=_TZ)
    )
    assert late is not None
    assert late.remind_at == datetime(2026, 9, 15, 7, 30, tzinfo=_TZ)


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
    governed = store.due(now=now)
    # 过期不原样投递；顺延出一句回执（A-05 治理不静默）。
    assert [item for item in governed if not item.reminder_id.startswith("gov-")] == []
    receipts = [item for item in governed if item.reminder_id.startswith("gov-")]
    assert len(receipts) == 1 and "收衣服" in receipts[0].text
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
    governed = store.due(now=now)
    # 作废也出一句回执（A-05），真提醒不再投递。
    assert [item for item in governed if not item.reminder_id.startswith("gov-")] == []
    receipts = [item for item in governed if item.reminder_id.startswith("gov-")]
    assert len(receipts) == 1 and "过期件" in receipts[0].text
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


def test_capability_full_list_replies_instead_of_silent_evict(tmp_path, monkeypatch) -> None:
    """审查 A-07 能力层：清单满时如实回复先取消，不再假装「记下了」。"""
    import plugins.bot_unified_runtime.character.reminders as reminders_mod

    monkeypatch.setattr(reminders_mod, "_STORES", {})
    config = SimpleNamespace(
        bot_reminder_db_path=str(tmp_path / "r.sqlite3"),
        bot_notes_enabled=False,
    )
    capability = build_reminder_capability(config)
    store = reminders_mod.build_reminder_store(config)
    base = datetime.now(timezone.utc)
    for index in range(store.max_pending):
        store.add(
            session_key="group:1", sender_id="u1", target_scope="group", target_id="1",
            adapter="nonebot", bot_id="bot",
            remind_at=base + timedelta(hours=index + 1), text=f"事{index}",
        )
    result = capability(_message("12点提醒我写作业"), object())
    assert "排满" in result.body and "提醒列表" in result.body
    assert "记下了" not in result.body


# ---------- 勾选消歧追问（审查 A-10/A-11，2026-09-14） ----------


def _add_pending_reminder(store: ReminderStore, text: str) -> None:
    store.add(
        session_key="group:1", sender_id="u1", target_scope="group", target_id="1",
        adapter="nonebot", bot_id="bot",
        remind_at=datetime.now(timezone.utc) + timedelta(hours=1), text=text,
    )


def _disambig_capability(tmp_path, monkeypatch):
    """消歧追问回归专用：清提醒 store 缓存 + 清追问状态（模块级单例）。"""
    import plugins.bot_unified_runtime.character.reminders as reminders_mod

    monkeypatch.setattr(reminders_mod, "_STORES", {})
    clear_checkoff_pending_for_tests()
    return build_reminder_capability(_tone_config(tmp_path))


def test_resolve_todo_match_single_low_similarity_is_uncertain() -> None:
    """审查 A-10：唯一候选只是「有点像」（0.667）不再判 hit 直接勾。

    新旧行为对照：旧实现返回 ("hit", [0])——「买牛奶做完了」会把唯一
    候选「买酸奶」直接勾掉；现返回 ("uncertain", [0]) 交能力层追问。
    """
    outcome, indexes = resolve_todo_match("买牛奶", ["买酸奶"])
    assert outcome == "uncertain" and indexes == [0]
    # 达到 0.8 线的包含关系照旧直接勾：「作业」vs「写作业」= 0.85。
    outcome, indexes = resolve_todo_match("作业", ["写作业"])
    assert outcome == "hit" and indexes == [0]
    # 精确一致 / 明显唯一的最高分照旧 hit，日常用法不受影响。
    outcome, indexes = resolve_todo_match("买牛奶", ["买牛奶", "买酸奶"])
    assert outcome == "hit" and indexes == [0]


def test_checkoff_single_low_similarity_asks_then_confirms(tmp_path, monkeypatch) -> None:
    """审查 A-10 ①②：低相似单候选先出确认、回「是」才勾。"""
    capability = _disambig_capability(tmp_path, monkeypatch)
    store = ReminderStore(tmp_path / "r.sqlite3")
    _add_pending_reminder(store, "买酸奶")
    prompt = capability(_message("买牛奶做完了"), object())
    assert "买酸奶" in prompt.body, "确认文案要复述候选事项"
    assert "「是」" in prompt.body, "确认文案要给肯定词回收口"
    assert len(store.list_pending("group:1")) == 1, "确认前绝不勾"
    confirm = capability(_message("是"), object())
    assert "买酸奶" in confirm.body and "放下" in confirm.body
    assert store.list_pending("group:1") == [], "回「是」之后应把候选勾掉"


def test_checkoff_confirmation_other_reply_does_not_check(tmp_path, monkeypatch) -> None:
    """审查 A-10 ②：确认态回「不是」等其他内容绝不勾。"""
    capability = _disambig_capability(tmp_path, monkeypatch)
    store = ReminderStore(tmp_path / "r.sqlite3")
    _add_pending_reminder(store, "买酸奶")
    capability(_message("买牛奶做完了"), object())
    capability(_message("不是"), object())
    assert len(store.list_pending("group:1")) == 1, "非肯定回复不勾"


def test_checkoff_confirmation_ttl_expired_asks_restated(tmp_path, monkeypatch) -> None:
    """审查 A-10 ③：确认过时效（TTL 300s）后回「是」不勾，提示重新说。"""
    capability = _disambig_capability(tmp_path, monkeypatch)
    store = ReminderStore(tmp_path / "r.sqlite3")
    _add_pending_reminder(store, "买酸奶")
    capability(_message("买牛奶做完了"), object())
    # 把追问时钟拨过 TTL，模拟 5 分钟后才回「是」。
    monkeypatch.setattr(
        reminder_cap_mod, "_monotonic", lambda: reminder_cap_mod.time.monotonic() + 301.0
    )
    reply = capability(_message("是"), object())
    assert "再说" in reply.body or "重新" in reply.body, "过期确认要请用户重新说"
    assert len(store.list_pending("group:1")) == 1, "过期确认绝不勾"


def test_checkoff_ambiguous_ordinal_reply_checks_chosen(tmp_path, monkeypatch) -> None:
    """审查 A-11 ①：歧义编号清单后回「2」/「第一件」勾对应项。

    新旧行为对照：旧实现只列候选清单，序号回复坠到提醒用法提示。
    """
    capability = _disambig_capability(tmp_path, monkeypatch)
    store = ReminderStore(tmp_path / "r.sqlite3")
    _add_pending_reminder(store, "写数学作业")
    _add_pending_reminder(store, "写语文作业")
    _add_pending_reminder(store, "写英语作业")
    prompt = capability(_message("作业做完了"), object())
    assert "1." in prompt.body and "写数学作业" in prompt.body, "清单要带编号"
    assert "2." in prompt.body and "写语文作业" in prompt.body
    pick = capability(_message("2"), object())
    assert "写语文作业" in pick.body and "放下" in pick.body
    assert [item.text for item in store.list_pending("group:1")] == [
        "写数学作业",
        "写英语作业",
    ], "只勾编号对应的那一件"
    # 第二轮：中文序数词同样能对上编号清单。
    capability(_message("作业做完了"), object())
    pick_cn = capability(_message("第一件"), object())
    assert "写数学作业" in pick_cn.body
    assert [item.text for item in store.list_pending("group:1")] == ["写英语作业"]


def test_checkoff_ambiguous_ordinal_out_of_bounds_hints(tmp_path, monkeypatch) -> None:
    """审查 A-11 ②：越界序号不勾、给有效范围提示，追问保留可重试。"""
    capability = _disambig_capability(tmp_path, monkeypatch)
    store = ReminderStore(tmp_path / "r.sqlite3")
    _add_pending_reminder(store, "写数学作业")
    _add_pending_reminder(store, "写语文作业")
    capability(_message("作业做完了"), object())
    bad = capability(_message("9"), object())
    assert "1 到 2" in bad.body, "越界要提示有效编号范围"
    assert len(store.list_pending("group:1")) == 2, "越界序号绝不勾"
    retry = capability(_message("1"), object())
    assert "写数学作业" in retry.body, "追问保留，重试仍可勾"


def test_ordinal_and_affirmative_parser_matrix() -> None:
    """序号/肯定词形态解析矩阵（A-11 序号词面 + A-10 肯定词白名单）。"""
    ordinal = reminder_cap_mod._match_ordinal
    assert ordinal("1") == 1 and ordinal("12") == 12
    assert ordinal("第一件") == 1
    assert ordinal("第2件") == 2
    assert ordinal("第 2 个") == 2
    assert ordinal("第三条") == 3
    assert ordinal("第十二件") == 12
    assert ordinal("第二十三件") == 23
    assert ordinal("0") is None and ordinal("第0件") is None
    assert ordinal("第一名") is None and ordinal("第一百") is None
    assert ordinal("作业") is None
    affirmative = reminder_cap_mod._match_affirmative
    assert affirmative("是") and affirmative("是的") and affirmative("嗯嗯")
    assert affirmative("对的对的。")  # 尾标点剥掉后仍是肯定词。
    assert not affirmative("不是") and not affirmative("好吧我去") and not affirmative("1")


def test_is_reminder_command_followup_shapes_gated_by_pending(
    tmp_path, monkeypatch
) -> None:
    """审查 A-10/A-11 路由闸：只有追问窗口内光杆肯定词/序号才放行。"""
    clear_checkoff_pending_for_tests()
    assert not is_reminder_command("是")
    assert not is_reminder_command("1")
    assert not is_reminder_command("第一件")
    capability = _disambig_capability(tmp_path, monkeypatch)
    store = ReminderStore(tmp_path / "r.sqlite3")
    _add_pending_reminder(store, "买酸奶")
    capability(_message("买牛奶做完了"), object())  # 产生追问状态
    assert is_reminder_command("是")
    assert is_reminder_command("嗯嗯")
    assert is_reminder_command("第一件")
    assert is_reminder_command("12点提醒我写作业"), "常规提醒语义不受追问闸影响"
    # 追问过时效后，光杆短句回到「绝不进提醒路由」的常态。
    monkeypatch.setattr(
        reminder_cap_mod, "_monotonic", lambda: reminder_cap_mod.time.monotonic() + 301.0
    )
    assert not is_reminder_command("是")


def test_checkoff_ambiguous_ordinal_covers_note_todo(tmp_path, monkeypatch) -> None:
    """审查 A-11：歧义候选来自提醒+笔记待办混合时，序号也能勾笔记条目。"""
    import plugins.bot_unified_runtime.character.reminders as reminders_mod
    from plugins.bot_unified_runtime.character import notes_store as notes_store_mod
    from plugins.bot_unified_runtime.character.notes_store import reset_stores_for_tests

    monkeypatch.setattr(reminders_mod, "_STORES", {})
    reset_stores_for_tests()
    clear_checkoff_pending_for_tests()
    notes_store_mod.NotesStore(tmp_path / "n.sqlite3").add(
        user_id="u1", chat_id="group:1", content_md="学习清单\n- [ ] 写语文作业",
    )
    store = ReminderStore(tmp_path / "r.sqlite3")
    _add_pending_reminder(store, "写数学作业")
    config = SimpleNamespace(
        bot_reminder_db_path=str(tmp_path / "r.sqlite3"),
        bot_notes_db_path=str(tmp_path / "n.sqlite3"),
    )
    capability = build_reminder_capability(config)
    prompt = capability(_message("作业做完了"), object())
    assert "1." in prompt.body and "2." in prompt.body
    pick = capability(_message("2"), object())
    assert "写语文作业" in pick.body
    assert notes_store_mod.NotesStore(tmp_path / "n.sqlite3").list_open_todos("group:1") == [], (
        "序号应能勾掉笔记待办"
    )
    assert [item.text for item in store.list_pending("group:1")] == ["写数学作业"]


def test_undo_phrases_route_into_reminder_surface() -> None:
    """A-14 接线收编：「取消勾选 X」/「X 还没做」要能进提醒/笔记路由面。"""
    from plugins.bot_unified_runtime.capabilities.reminder import is_reminder_command

    assert is_reminder_command("取消勾选 买牛奶")
    assert is_reminder_command("买牛奶还没做")
    # 与删除类指令不互抢：「取消笔记」不因撤销词误进提醒路由。
    assert not is_reminder_command("取消笔记")
