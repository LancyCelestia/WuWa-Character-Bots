"""提醒分型语气回归（2026-09-13 六域批）：用途分型 + 到点文案按型切换。

语气基准 = personas/shorekeeper（温柔、克制、海与星意象、不生硬不 AI 味）。
"""

from __future__ import annotations

from plugins.bot_unified_runtime.character.reminders import (
    Reminder,
    build_reminder_text,
    classify_reminder_kind,
)


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
