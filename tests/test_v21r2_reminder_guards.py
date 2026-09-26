"""提醒粘贴体守卫回归（2026-09-18 实弹：其他 AI 的缴费广告被整段记成提醒，
到点五条齐炸）。守卫三层：粘贴痕迹标记 / 超长 / 多句号拒绝 + 24h 正文去重。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import plugins.bot_unified_runtime.domains.schedule.capabilities.reminder as reminder_mod
import plugins.bot_unified_runtime.domains.schedule.store.reminders as reminders_store_mod
from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.schedule.capabilities.reminder import (
    build_reminder_capability,
)
from plugins.bot_unified_runtime.domains.schedule.store.reminders import ReminderStore

_AD = (
    "【套餐 】尊敬的用户您好 截至9月17日12时 您的token账户已不足支付本群的AI好友聊天 "
    "为了不影响您正常调用AI好友的聊天功能 请及时缴费50元"
)


@pytest.fixture(autouse=True)
def _isolated_guard_state(tmp_path, monkeypatch):
    """store 与 24h 去重表都是模块级单例：每例前后清零防泄漏。"""
    monkeypatch.setattr(reminders_store_mod, "_STORES", {})
    monkeypatch.setattr(reminder_mod, "_RECENT_BODIES", {})
    yield
    reminder_mod._RECENT_BODIES.clear()


def _harness(tmp_path):
    config = SimpleNamespace(
        bot_reminder_db_path=str(tmp_path / "r.sqlite3"),
        bot_notes_enabled=False,
    )
    store = ReminderStore(tmp_path / "r.sqlite3")

    def _message(text: str) -> IncomingMessage:
        return IncomingMessage(
            platform="qq", adapter="nonebot", bot_id="bot-1",
            session_id="group:1", session_type=SessionType.GROUP, sender_id="u1",
            group_id="1", plain_text=text, message_id="m1",
        )

    return build_reminder_capability(config), store, _message


def test_ad_paste_never_becomes_reminder(tmp_path) -> None:
    """实弹回归：广告全文（含提醒信号+12时）整段粘贴 → 拒绝入库。"""
    capability, store, message = _harness(tmp_path)
    result = capability(message("12点提醒我 " + _AD), object())
    assert "rejected_paste" in result.audit_tags
    assert store.list_pending("group:1") == []


def test_ad_paste_short_with_markers_rejected(tmp_path) -> None:
    """短但带广告痕迹标记（尊敬的用户/缴费）同样拒绝——长度不是唯一判据。"""
    capability, store, message = _harness(tmp_path)
    result = capability(message("12点提醒我尊敬的用户请尽快缴费"), object())
    assert "rejected_paste" in result.audit_tags
    assert store.list_pending("group:1") == []


def test_overlong_body_rejected(tmp_path) -> None:
    """超长正文（>120 字文档上限）拒绝，即便无广告标记。"""
    capability, store, message = _harness(tmp_path)
    filler = "帮我盯着这件事别弄丢了" * 16
    result = capability(message("12点提醒我 " + filler), object())
    assert "rejected_paste" in result.audit_tags
    assert store.list_pending("group:1") == []


def test_multi_sentence_body_rejected(tmp_path) -> None:
    """多句正文（像转发的段落而非一句意图）拒绝。"""
    capability, store, message = _harness(tmp_path)
    result = capability(
        message("12点提醒我开会。之后还要吃饭。然后看一遍报告"), object()
    )
    assert "rejected_paste" in result.audit_tags
    assert store.list_pending("group:1") == []


def test_duplicate_body_within_window_suppressed(tmp_path) -> None:
    """同正文 24h 内重复提交 → 不重复记（跨会话刷屏先例的直接封堵）。"""
    capability, store, message = _harness(tmp_path)
    first = capability(message("12点提醒我买牛奶"), object())
    assert "added" in first.audit_tags
    second = capability(message("12点提醒我买牛奶"), object())
    assert "duplicate_recent" in second.audit_tags
    assert len(store.list_pending("group:1")) == 1


def test_normal_short_intent_still_passes(tmp_path) -> None:
    """回归锁：正常短意图不受守卫影响。"""
    capability, store, message = _harness(tmp_path)
    result = capability(message("12点提醒我写作业"), object())
    assert "added" in result.audit_tags
    pending = store.list_pending("group:1")
    assert len(pending) == 1 and "写作业" in pending[0].text
