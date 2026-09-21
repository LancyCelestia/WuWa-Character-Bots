"""提醒分型语气回归（2026-09-13 六域批）：用途分型 + 到点文案按型切换。

语气基准 = personas/shorekeeper（温柔、克制、海与星意象、不生硬不 AI 味）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.capabilities.reminder import (
    build_reminder_capability,
    clear_checkoff_pending_for_tests,
)
from plugins.bot_unified_runtime.character.reminders import (
    Reminder,
    ReminderStore,
    build_reminder_text,
    classify_reminder_kind,
)
from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType


@pytest.fixture(autouse=True)
def _isolated_checkoff_pending_state():
    """勾选消歧追问状态是模块级单例：每例前后清零，防跨用例/跨文件泄漏。"""
    clear_checkoff_pending_for_tests()
    yield
    clear_checkoff_pending_for_tests()


def _reminder(text: str) -> Reminder:
    return Reminder(
        reminder_id="r1", session_key="group:1", sender_id="u1",
        target_scope="group", target_id="1", adapter="nonebot", bot_id="bot",
        remind_at="2026-09-13T12:00:00+08:00", text=text,
        status="pending", created_at="2026-09-13T10:00:00+08:00",
    )


# ---------- 分型 ----------

def test_classify_medicine_beats_other_kinds() -> None:
    assert classify_reminder_kind("中午提醒我吃药") == "medicine"
    assert classify_reminder_kind("买药") == "medicine"  # 健康 > 采购。
    assert classify_reminder_kind("下午三点输液") == "medicine"


def test_classify_appointment_and_shopping() -> None:
    assert classify_reminder_kind("明天早上8点叫我起床开会") == "appointment"
    assert classify_reminder_kind("6点提醒我赶飞机") == "appointment"
    assert classify_reminder_kind("中午提醒我取快递") == "shopping"
    assert classify_reminder_kind("提醒我买牛奶") == "shopping"


def test_classify_todo_and_custom_fallback() -> None:
    assert classify_reminder_kind("12点提醒我写作业") == "todo"
    assert classify_reminder_kind("10点提醒我收衣服") == "todo"
    assert classify_reminder_kind("提醒我给花拍照") == "custom"  # 无关键词兜底。
    assert classify_reminder_kind("") == "custom"


# ---------- 到点文案按型切换 ----------

def test_delivery_text_switches_by_kind() -> None:
    texts = {
        kind: build_reminder_text(_reminder(content))
        for kind, content in (
            ("medicine", "吃药"),
            ("appointment", "开会"),
            ("shopping", "取快递"),
            ("todo", "写作业"),
            ("custom", "给花拍照"),
        )
    }
    assert len(set(texts.values())) == 5, "五型文案必须互不相同"
    for text in texts.values():
        assert "到时间" in text or "时间到了" in text or "到点了" in text


def test_delivery_text_keeps_item_and_shorekeeper_voice() -> None:
    text = build_reminder_text(_reminder("写作业"))
    assert "写作业" in text, "文案必须复述提醒事项"
    # 守岸人语气：温柔收尾 + 意象词，不出现机器腔。
    assert "守在这里" in text or "陪着你" in text or "我都在" in text
    for banned in ("您有一个", "温馨提示", "请注意查收", "尊敬的用户"):
        assert banned not in text


def test_custom_kind_keeps_legacy_default_text() -> None:
    text = build_reminder_text(_reminder("给花拍照"))
    assert text == (
        "（远处的海浪声）……到时间了。\n"
        "你之前说过的：给花拍照。\n"
        "我就守在这里。慢一点也没关系，记得去做。"
    )


# ---------- 勾选消歧追问文案（审查 A-10/A-11，2026-09-14） ----------

def _disambig_setup(tmp_path, monkeypatch):
    """追问文案回归：提醒 store 隔离 + 追问状态清零 + 笔记面关闭。"""
    import plugins.bot_unified_runtime.domains.schedule.store.reminders as reminders_mod

    monkeypatch.setattr(reminders_mod, "_STORES", {})
    clear_checkoff_pending_for_tests()
    config = SimpleNamespace(
        bot_reminder_db_path=str(tmp_path / "r.sqlite3"),
        bot_notes_enabled=False,
    )
    store = ReminderStore(tmp_path / "r.sqlite3")

    def _add(text: str) -> None:
        store.add(
            session_key="group:1", sender_id="u1", target_scope="group", target_id="1",
            adapter="nonebot", bot_id="bot",
            remind_at=datetime.now(timezone.utc) + timedelta(hours=1), text=text,
        )

    def _message(text: str) -> IncomingMessage:
        return IncomingMessage(
            platform="qq", adapter="nonebot", bot_id="bot-1",
            session_id="group:1", session_type=SessionType.GROUP, sender_id="u1",
            group_id="1", plain_text=text, message_id="m1",
        )

    return build_reminder_capability(config), store, _add, _message


def test_checkoff_confirmation_copy_keeps_shorekeeper_voice(tmp_path, monkeypatch) -> None:
    """审查 A-10：单候选确认文案要守岸人语气——复述候选、给肯定词回收口、
    不出现机器腔；且先确认后勾，不替用户做主。"""
    capability, _store, add, message = _disambig_setup(tmp_path, monkeypatch)
    add("买酸奶")
    prompt = capability(message("买牛奶做完了"), object())
    body = prompt.body
    assert "买酸奶" in body and "「是」" in body, "要复述候选并给明确回收口"
    assert "做主" in body or "不敢" in body, "低相似要承认不确定，守岸人不武断"
    for banned in ("相似度", "候选 ", "请确认", "您的选择", "系统检测"):
        assert banned not in body, f"确认文案不得出现机器腔：{banned}"


# ---------- 审查 A-13：文案模板池收口（只挪位置，不改任何字面） ----------

def test_delivery_template_table_covers_all_kinds() -> None:
    """A-13：到点文案模板表必须覆盖全部分型，每条模板都带 {text} 占位。"""
    from plugins.bot_unified_runtime.character.reminders import (
        _REMINDER_TEXT_TEMPLATES,
        REMINDER_KINDS,
    )

    assert set(_REMINDER_TEXT_TEMPLATES) == set(REMINDER_KINDS)
    for variants in _REMINDER_TEXT_TEMPLATES.values():
        assert variants, "每个分型至少保留一条模板"
        for template in variants:
            assert "{text}" in template


def test_delivery_text_persona_variant_selection_is_deterministic() -> None:
    """A-13：persona_profile_id 参与选变体——同参确定性；缺省退化恒取
    首个变体，与既有单变体字面逐字一致（行为不变的收口）。"""
    reminder = _reminder("写作业")
    assert build_reminder_text(
        reminder, persona_profile_id="default"
    ) == build_reminder_text(reminder, persona_profile_id="default")
    assert build_reminder_text(reminder) == build_reminder_text(
        reminder, persona_profile_id="anything-else"
    )


def test_checkoff_copy_pool_is_module_level() -> None:
    """A-13：勾选四类回执文案（确认/歧义/序号/过期，附 gone 兜底）收进
    模块级常量池，函数体不再内联字面；关键句面与 A-10/A-11 批锁定一致。"""
    import plugins.bot_unified_runtime.domains.schedule.capabilities.reminder as reminder_mod

    pool_names = (
        "_CHECKOFF_DONE_TEMPLATE",
        "_CHECKOFF_CONFIRM_TEMPLATE",
        "_CHECKOFF_AMBIGUOUS_TEMPLATE",
        "_CHECKOFF_NEED_NUMBER_TEMPLATE",
        "_CHECKOFF_CONFIRM_ONLY_TEMPLATE",
        "_CHECKOFF_OUT_OF_RANGE_TEMPLATE",
        "_CHECKOFF_EXPIRED_TEMPLATE",
        "_CHECKOFF_GONE_TEMPLATE",
    )
    for const_name in pool_names:
        value = getattr(reminder_mod, const_name, None)
        assert isinstance(value, str) and value, f"{const_name} 应为模块级常量"
    assert "做主" in reminder_mod._CHECKOFF_CONFIRM_TEMPLATE
    assert "有几件事都对得上" in reminder_mod._CHECKOFF_AMBIGUOUS_TEMPLATE
    assert "不在刚才的清单里" in reminder_mod._CHECKOFF_OUT_OF_RANGE_TEMPLATE
    assert "过了时效" in reminder_mod._CHECKOFF_EXPIRED_TEMPLATE


def test_checkoff_ambiguous_numbered_copy_invites_ordinal(tmp_path, monkeypatch) -> None:
    """审查 A-11：歧义清单带编号并邀请序号回复，编号与序号回收对应。"""
    capability, _store, add, message = _disambig_setup(tmp_path, monkeypatch)
    add("写数学作业")
    add("写语文作业")
    body = capability(message("作业做完了"), object()).body
    assert "1." in body and "2." in body, "清单要带编号（与序号回复对应）"
    assert "编号" in body, "要邀请用户回编号"
    assert "有几件事" in body, "沿用既有守岸人歧义开头，不点数"
