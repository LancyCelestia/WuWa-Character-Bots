"""A-05 治理回执回归：顺延/作废不再静默。

语义（2026-09-15）：
- 顺延（迟到 >30min ≤24h）/ 作废（迟到 >24h，含存储时刻脏数据）各按
  会话折成至多一句守岸人短句回执；
- 回执是合成 Reminder（id 带 ``gov-`` 前缀），随 ``due()`` 返回值搭
  既有投递路径（__init__ 每分钟调度内联投递）主动送达；
- 回执绝不顶替真提醒：顺延件仍 pending（remind_at 已更新），送达侧的
  ``mark_done(回执id)`` 是无害空操作；
- 一次治理扫描每会话至多一条回执（群聊同会话节流哲学），且治理只发生
  一次，回执天然不重复。
全部用注入时钟（``due(now=...)``），零真 sleep。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from plugins.bot_unified_runtime.character.reminders import (
    LATE_DELIVERY_GRACE,
    ReminderStore,
    build_reminder_text,
)

_TZ = timezone(timedelta(hours=8))
_RECEIPT = "gov-"


def _add(
    store: ReminderStore,
    text: str,
    *,
    remind_at: datetime,
    session_key: str = "private:u1",
    target_scope: str = "private",
    target_id: str = "u1",
    sender_id: str = "u1",
):
    return store.add(
        session_key=session_key,
        sender_id=sender_id,
        target_scope=target_scope,
        target_id=target_id,
        adapter="nonebot",
        bot_id="bot",
        remind_at=remind_at,
        text=text,
    )


def _split(items: list) -> tuple[list, list]:
    real = [item for item in items if not item.reminder_id.startswith(_RECEIPT)]
    receipts = [item for item in items if item.reminder_id.startswith(_RECEIPT)]
    return real, receipts


def test_postponed_receipt_once_with_source_routing(tmp_path) -> None:
    """顺延回执：路由字段沿用原提醒、一次性、真提醒仍 pending。"""
    store = ReminderStore(tmp_path / "r.sqlite3")
    reminder = _add(
        store, "收衣服",
        remind_at=datetime(2026, 9, 12, 23, 0, tzinfo=_TZ),
        session_key="private:u7", target_id="7", sender_id="7",
    )
    now = datetime(2026, 9, 13, 13, 51, tzinfo=_TZ)  # 迟到 ~14.9 小时
    real, receipts = _split(store.due(now=now))
    assert real == [], "错过的提醒不得原样补投"
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt.session_key == "private:u7"
    assert receipt.target_scope == "private"
    assert receipt.target_id == "7"
    assert receipt.sender_id == "7"
    assert receipt.adapter == "nonebot" and receipt.bot_id == "bot"
    assert "收衣服" in receipt.text and "明天" in receipt.text
    # 真提醒仍是待办，时刻已顺延到明天同一时刻（09-13 23:00）。
    pending = store.list_pending("private:u7")
    assert [item.reminder_id for item in pending] == [reminder.reminder_id]
    stored = datetime.fromisoformat(pending[0].remind_at)
    assert stored.astimezone(_TZ) == datetime(2026, 9, 13, 23, 0, tzinfo=_TZ)
    # 治理只发生一次：下一轮不再有回执。
    assert store.due(now=now + timedelta(minutes=1)) == []


def test_receipt_text_passes_through_build_reminder_text(tmp_path) -> None:
    """回执文案原样放行：带「吃药」关键词也不许被分型模板误包装。"""
    store = ReminderStore(tmp_path / "r.sqlite3")
    _add(store, "吃药", remind_at=datetime(2026, 9, 12, 8, 0, tzinfo=_TZ))
    now = datetime(2026, 9, 13, 13, 51, tzinfo=_TZ)
    _real, receipts = _split(store.due(now=now))
    assert len(receipts) == 1
    assert build_reminder_text(receipts[0]) == receipts[0].text
    assert "你之前说过的" not in receipts[0].text, "不得套到点投递的分型模板"


def test_expired_receipt_and_no_pending_left(tmp_path) -> None:
    """作废回执：一句告知放下，待办清空，且不重复出回执。"""
    store = ReminderStore(tmp_path / "r.sqlite3")
    _add(store, "过期件", remind_at=datetime(2026, 9, 12, 8, 0, tzinfo=_TZ))
    now = datetime(2026, 9, 13, 13, 51, tzinfo=_TZ)  # 迟到 ~29.9 小时
    _real, receipts = _split(store.due(now=now))
    assert len(receipts) == 1 and "过期件" in receipts[0].text
    assert store.list_pending("private:u1") == []
    assert store.due(now=now + timedelta(minutes=1)) == []


def test_receipts_coalesced_per_session(tmp_path) -> None:
    """同会话多条顺延折成一句回执；不同会话各回各的，不串话。"""
    store = ReminderStore(tmp_path / "r.sqlite3")
    base = datetime(2026, 9, 12, 20, 0, tzinfo=_TZ)
    for index in range(3):
        _add(
            store, f"事项{index}",
            remind_at=base + timedelta(hours=index),  # 迟到 15~17h：全落在顺延窗
            session_key="group:42", target_scope="group", target_id="42",
        )
    _add(
        store, "别会话的事", remind_at=base,
        session_key="private:u9", target_id="9", sender_id="9",
    )
    now = datetime(2026, 9, 13, 13, 51, tzinfo=_TZ)
    _real, receipts = _split(store.due(now=now))
    assert len(receipts) == 2, "每会话至多一条（群聊同会话节流）"
    by_session = {receipt.session_key: receipt for receipt in receipts}
    assert set(by_session) == {"group:42", "private:u9"}
    group_text = by_session["group:42"].text
    assert "事项0" in group_text and "事项2" in group_text
    assert "别会话的事" not in group_text
    assert "别会话的事" in by_session["private:u9"].text


def test_mixed_postpone_and_expire_single_receipt(tmp_path) -> None:
    """同会话既有顺延又有作废：一句 mixed 回执两处交代，待办只剩顺延件。"""
    store = ReminderStore(tmp_path / "r.sqlite3")
    kept = _add(store, "顺延件", remind_at=datetime(2026, 9, 12, 23, 0, tzinfo=_TZ))
    _add(store, "作废件", remind_at=datetime(2026, 9, 11, 8, 0, tzinfo=_TZ))
    now = datetime(2026, 9, 13, 13, 51, tzinfo=_TZ)
    real, receipts = _split(store.due(now=now))
    assert real == []
    assert len(receipts) == 1
    assert "顺延件" in receipts[0].text and "作废件" in receipts[0].text
    assert [item.reminder_id for item in store.list_pending("private:u1")] == [
        kept.reminder_id
    ]


def test_mark_done_on_receipt_id_is_noop(tmp_path) -> None:
    """送达侧照常 mark_done(回执id)：空操作，绝不销掉顺延中的真提醒。"""
    store = ReminderStore(tmp_path / "r.sqlite3")
    reminder = _add(store, "收衣服", remind_at=datetime(2026, 9, 12, 23, 0, tzinfo=_TZ))
    now = datetime(2026, 9, 13, 13, 51, tzinfo=_TZ)
    _real, receipts = _split(store.due(now=now))
    assert len(receipts) == 1
    store.mark_done(receipts[0].reminder_id)  # __init__ 内联投递后的销账路径
    pending = store.list_pending("private:u1")
    assert [item.reminder_id for item in pending] == [reminder.reminder_id]


def test_on_time_delivery_never_carries_receipt(tmp_path) -> None:
    """按时（含 30 分钟容忍窗内）：只有真提醒，绝不夹带回执。"""
    store = ReminderStore(tmp_path / "r.sqlite3")
    reminder = _add(
        store, "到点件", remind_at=datetime(2026, 9, 13, 22, 50, tzinfo=_TZ)
    )
    now = datetime(2026, 9, 13, 23, 5, tzinfo=_TZ)  # 迟到 15 分钟 ≤ 容忍窗
    real, receipts = _split(store.due(now=now))
    assert [item.reminder_id for item in real] == [reminder.reminder_id]
    assert receipts == []


def test_late_window_boundaries(tmp_path) -> None:
    """顺延窗口边界：恰好 30 分钟照常投递；超 30 分钟顺延；24h 内不作废。"""
    store = ReminderStore(tmp_path / "r.sqlite3")
    edge = _add(
        store, "边界件",
        remind_at=datetime(2026, 9, 13, 22, 0, tzinfo=_TZ) - LATE_DELIVERY_GRACE,
    )
    now = datetime(2026, 9, 13, 22, 0, tzinfo=_TZ)
    real, receipts = _split(store.due(now=now))
    assert [item.reminder_id for item in real] == [edge.reminder_id]
    assert receipts == [], "恰好容忍窗不得顺延"

    store.mark_done(edge.reminder_id)
    upper = _add(store, "上限件", remind_at=now - timedelta(hours=23))
    # 迟到 23h：>30min 且 <24h → 顺延不作废。
    real, receipts = _split(store.due(now=now))
    assert real == []
    assert len(receipts) == 1
    pending = store.list_pending("private:u1")
    assert [item.reminder_id for item in pending] == [upper.reminder_id]


def test_dirty_stored_moment_expires_with_receipt(tmp_path) -> None:
    """存储时刻脏数据：按作废治理，同样出一句回执（事项文本仍可知）。"""
    store = ReminderStore(tmp_path / "r.sqlite3")
    _add(store, "时刻坏了的事", remind_at=datetime(2026, 9, 13, 12, 0, tzinfo=_TZ))
    conn = sqlite3.connect(tmp_path / "r.sqlite3")
    conn.execute(
        "UPDATE reminders SET remind_at = 'not-a-time' WHERE text = '时刻坏了的事'"
    )
    conn.commit()
    conn.close()
    now = datetime(2026, 9, 13, 13, 51, tzinfo=_TZ)
    real, receipts = _split(store.due(now=now))
    assert real == []
    assert len(receipts) == 1 and "时刻坏了的事" in receipts[0].text
    assert store.list_pending("private:u1") == []


def test_shared_store_build_path_emits_receipt_too(tmp_path, monkeypatch) -> None:
    """build_reminder_store 注入路径下同样出回执（生产调度消费的就是它）。"""
    import plugins.bot_unified_runtime.character.reminders as reminders_mod

    monkeypatch.setattr(reminders_mod, "_STORES", {})
    config = SimpleNamespace(bot_reminder_db_path=str(tmp_path / "r.sqlite3"))
    store = reminders_mod.build_reminder_store(config)
    _add(store, "收衣服", remind_at=datetime(2026, 9, 12, 23, 0, tzinfo=_TZ))
    now = datetime(2026, 9, 13, 13, 51, tzinfo=_TZ)
    _real, receipts = _split(store.due(now=now))
    assert len(receipts) == 1 and "收衣服" in receipts[0].text
