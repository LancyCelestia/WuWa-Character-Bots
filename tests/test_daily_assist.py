"""日常助理回归（bot.daily_assist）。

离线验证（不依赖 NoneBot 运行时/网络）：
- 菜单解析（分节/备注排除/条目清洗）与择菜（7 天不重复、全排除回退、历史落盘）
- 收件箱追加/读取/归档往返（其余分节原样保留）
- 任务清单分节读取、早晚简报文案（含空态）
- 收件箱命令面（速记/查询/帮助）与触发判定
- 定时调度注册（FakeScheduler：job id/时刻/名单为空跳过）与私聊 SendRequest 形状
"""

from __future__ import annotations

import json
import random
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime import (
    _parse_daily_assist_clock,
    _push_daily_assist_private,
    _register_daily_assist_scheduler,
)
from plugins.bot_unified_runtime.contracts import PrivacyLevel, SendPolicy, SessionType
from plugins.bot_unified_runtime.domains.assistant.daily.capabilities.daily_assist import (
    _CAPTURE_VARIANTS,
    _HELP_VARIANTS,
    _QUERY_EMPTY_VARIANTS,
    _QUERY_LISTING_VARIANTS,
    build_daily_assist_capability,
    is_daily_assist_command,
)
from plugins.bot_unified_runtime.domains.assistant.daily.store.daily_assist import (
    _EVENING_IDEA_NUDGES,
    _EVENING_INBOX_COUNTED_LINES,
    _EVENING_INBOX_EMPTY_LINES,
    _EVENING_OPENERS,
    _MORNING_EMPTY_OPENERS,
    _MORNING_IDEA_NOTES,
    _MORNING_OPENERS,
    append_inbox_line,
    archive_inbox,
    build_evening_brief,
    build_morning_brief,
    choose_meal,
    daily_archive_dir,
    food_path,
    inbox_path,
    load_daily_archive,
    meal_display_name,
    meal_history_path,
    parse_food_choices,
    pick_variant,
    read_pending_inbox,
    read_task_sections,
    summarize_with_llm,
    tasks_path,
)
from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
    build_outbound_gate,
)

_MENU = """# 美食偏好清单

## 主食正餐

- 红烧牛肉饭
- 黄焖鸡米饭
- 麻辣香锅（不想太辣的日子跳过）

## 轻食简餐

- 三明治

## 备注

- 口味忌讳：不吃香菜
"""


def _make_config(tmp_path, **overrides):
    base = {
        "bot_daily_assist_enabled": True,
        "bot_daily_assist_dir": "data/daily_assist",
        "bot_daily_assist_push_user_ids": ["10001"],
        "bot_daily_assist_meal_times": ["11:15", "17:15"],
        "bot_daily_assist_morning_time": "09:00",
        "bot_daily_assist_evening_time": "21:00",
        "bot_persona_profile_id": "default",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture()
def assist_env(monkeypatch, tmp_path):
    monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(tmp_path))
    return tmp_path


# ---------------------------------------------------------------------------
# 菜单与择菜
# ---------------------------------------------------------------------------


def test_parse_food_choices_skips_notes_and_comments() -> None:
    choices = parse_food_choices(_MENU)
    assert choices == ["红烧牛肉饭", "黄焖鸡米饭", "麻辣香锅（不想太辣的日子跳过）", "三明治"]


def test_meal_display_name_strips_parenthetical() -> None:
    assert meal_display_name("麻辣香锅（不想太辣的日子跳过）") == "麻辣香锅"
    assert meal_display_name("咖喱鸡饭") == "咖喱鸡饭"


def test_choose_meal_prefers_custom_menu_and_records_history(assist_env, tmp_path) -> None:
    config = _make_config(tmp_path)
    food = food_path(config)
    food.parent.mkdir(parents=True, exist_ok=True)
    food.write_text(_MENU, encoding="utf-8")
    now = datetime(2026, 9, 15, 11, 0, tzinfo=timezone.utc)
    picked = choose_meal(config, now=now, rng=random.Random(7))
    assert meal_display_name(picked) in {"红烧牛肉饭", "黄焖鸡米饭", "麻辣香锅", "三明治"}
    history = meal_history_path(config)
    assert json.loads(history.read_text(encoding="utf-8").splitlines()[-1]) == {
        "date": "2026-09-15",
        "name": meal_display_name(picked),
    }


def test_choose_meal_avoids_recent_picks_then_falls_back(assist_env, tmp_path) -> None:
    config = _make_config(tmp_path)
    food = food_path(config)
    food.parent.mkdir(parents=True, exist_ok=True)
    food.write_text("- 拉面\n- 饺子\n", encoding="utf-8")
    history = meal_history_path(config)
    history.parent.mkdir(parents=True, exist_ok=True)
    now = datetime(2026, 9, 15, 11, 0, tzinfo=timezone.utc)
    today = date(2026, 9, 15)
    history.write_text(
        json.dumps({"date": today.isoformat(), "name": "拉面"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    assert meal_display_name(choose_meal(config, now=now, rng=random.Random(1))) == "饺子"
    # 7 天内全吃过 → 回退全量池，宁可重复也不空手。
    history.write_text(
        json.dumps({"date": today.isoformat(), "name": "拉面"}, ensure_ascii=False) + "\n"
        + json.dumps({"date": today.isoformat(), "name": "饺子"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    assert meal_display_name(choose_meal(config, now=now, rng=random.Random(1))) in {"拉面", "饺子"}


# ---------------------------------------------------------------------------
# 收件箱
# ---------------------------------------------------------------------------


def test_inbox_append_read_archive_roundtrip(assist_env, tmp_path) -> None:
    config = _make_config(tmp_path)
    inbox = inbox_path(config)
    now = datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc)
    append_inbox_line(inbox, "买牛奶", now=now)
    append_inbox_line(inbox, "周五前还信用卡", now=now)
    assert read_pending_inbox(inbox) == [
        "[2026-09-15 08:00] 买牛奶",
        "[2026-09-15 08:00] 周五前还信用卡",
    ]
    archived = archive_inbox(inbox, daily_archive_dir(config), now=now)
    assert len(archived) == 2
    assert read_pending_inbox(inbox) == []
    daily_file = daily_archive_dir(config) / "2026-09-15.md"
    assert "买牛奶" in daily_file.read_text(encoding="utf-8")
    # 再归档一次是无操作（空段不写盘）。
    assert archive_inbox(inbox, daily_archive_dir(config), now=now) == []


def test_inbox_preserves_other_sections(assist_env, tmp_path) -> None:
    config = _make_config(tmp_path)
    inbox = inbox_path(config)
    inbox.parent.mkdir(parents=True, exist_ok=True)
    inbox.write_text(
        "# 收件箱（Inbox）\n\n## 待处理\n\n- [2026-09-14 09:00] 旧条目\n\n## 已处理规则\n\n- 别动我\n",
        encoding="utf-8",
    )
    archive_inbox(inbox, daily_archive_dir(config), now=datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc))
    text = inbox.read_text(encoding="utf-8")
    assert "旧条目" not in text
    assert "## 已处理规则" in text
    assert "别动我" in text


# ---------------------------------------------------------------------------
# 任务清单与文案
# ---------------------------------------------------------------------------


def test_read_task_sections(assist_env, tmp_path) -> None:
    config = _make_config(tmp_path)
    path = tasks_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "## 进行中\n\n- 写周报\n\n## 已计划\n\n- 2026-09-20 取快递\n\n## 想法池\n\n- （空）\n",
        encoding="utf-8",
    )
    sections = read_task_sections(path)
    assert sections["进行中"] == ["写周报"]
    assert sections["已计划"] == ["2026-09-20 取快递"]
    assert sections.get("想法池", []) == []


def test_morning_and_evening_briefs() -> None:
    # 文案已池化轮换：断言「结构 + 数据 + 池成员」，不钉死具体措辞。
    empty = build_morning_brief([], {}, "")
    assert empty in _MORNING_EMPTY_OPENERS
    morning = build_morning_brief(
        ["[2026-09-15 08:00] 买牛奶"], {"进行中": ["写周报"]}, "先还信用卡"
    )
    assert "买牛奶" in morning and "写周报" in morning and "先还信用卡" in morning
    assert morning.splitlines()[0] in _MORNING_OPENERS
    assert "【收件箱】" in morning and "【划重点】" in morning
    evening = build_evening_brief({"想法池": ["学做菜"]}, ["买牛奶"], "明天有雨带伞")
    assert "学做菜" in evening and "明天有雨带伞" in evening
    assert "1 条" in evening and "【想法池】" in evening and "【替你想了想】" in evening
    assert evening.splitlines()[0] in _EVENING_OPENERS
    calm = build_evening_brief({}, [], "")
    calm_expected = {
        f"{opener}\n{line}"
        for opener in _EVENING_OPENERS
        for line in _EVENING_INBOX_EMPTY_LINES
    }
    assert calm in calm_expected


# ---------------------------------------------------------------------------
# 文案语气守卫（守岸人语气：变体数 / 违禁词 / 第三人称自称）
# ---------------------------------------------------------------------------

_BANNED_TOKENS = (
    "～",
    "系统",
    "提示词",
    "脚本",
    "注入",
    "作为AI",
    "值得注意的是",
    "综上所述",
)


def _all_copy_pools() -> dict[str, tuple[str, ...]]:
    return {
        "morning_empty": _MORNING_EMPTY_OPENERS,
        "morning_open": _MORNING_OPENERS,
        "morning_ideas": _MORNING_IDEA_NOTES,
        "evening_open": _EVENING_OPENERS,
        "evening_inbox_empty": _EVENING_INBOX_EMPTY_LINES,
        "evening_inbox_counted": _EVENING_INBOX_COUNTED_LINES,
        "evening_ideas_nudge": _EVENING_IDEA_NUDGES,
        "capability_help": _HELP_VARIANTS,
        "capability_query_empty": _QUERY_EMPTY_VARIANTS,
        "capability_query_list": _QUERY_LISTING_VARIANTS,
        "capability_capture": _CAPTURE_VARIANTS,
    }


def test_copy_pools_tone_guards() -> None:
    for name, pool in _all_copy_pools().items():
        assert len(pool) >= 6, f"{name} 变体数不足 6"
        joined = "\n".join(pool)
        for token in _BANNED_TOKENS:
            assert token not in joined, f"{name} 命中违禁词：{token}"
        assert "守岸人" in joined, f"{name} 缺第三人称自称"
    # 推送开场是当日文案的声线锚：早晚报开场每条都带第三人称自称。
    for opener in (*_MORNING_OPENERS, *_EVENING_OPENERS):
        assert "守岸人" in opener


def test_brief_outputs_pass_tone_guard() -> None:
    evening = build_evening_brief(
        {"进行中": ["写周报"], "想法池": ["学做菜"]},
        ["买牛奶", "取快递"],
        "明天有雨带伞",
    )
    morning = build_morning_brief(["[2026-09-15 08:00] 买牛奶"], {}, "")
    for text in (morning, evening):
        for token in _BANNED_TOKENS:
            assert token not in text, f"简报成品命中违禁词：{token}"


def test_pick_variant_rotates_deterministically() -> None:
    from plugins.bot_unified_runtime.domains.assistant.daily.store.daily_assist import (
        _VARIANT_CURSORS,
    )

    _VARIANT_CURSORS.clear()
    pool = ("甲", "乙", "丙")
    sequence = [pick_variant("t-guard", pool) for _ in range(6)]
    assert sequence == ["甲", "乙", "丙", "甲", "乙", "丙"]
    # 各池游标互不干扰。
    assert pick_variant("t-other", pool) == "甲"
    # 用户内容只作格式化参数，含大括号也不炸模板。
    assert pick_variant("t-fmt", ("记下了：{line}",), line="{花括号}内容") == "记下了：{花括号}内容"


def test_summarize_with_llm_falls_back_to_empty() -> None:
    assert summarize_with_llm(None, "内容", instruction="总结") == ""
    assert summarize_with_llm(None, "  ", instruction="总结") == ""


# ---------------------------------------------------------------------------
# 命令面
# ---------------------------------------------------------------------------


def test_is_daily_assist_command() -> None:
    assert is_daily_assist_command("收件箱 买牛奶")
    assert is_daily_assist_command("收件箱")
    assert is_daily_assist_command("inbox buy milk")
    assert is_daily_assist_command("shoujianxiang")
    assert not is_daily_assist_command("")
    assert not is_daily_assist_command("查看收件箱列表")
    assert not is_daily_assist_command("shoujianxiangqq")


def _run_capability(config, text: str):
    message = SimpleNamespace(plain_text=text, request_id="req-test")
    return build_daily_assist_capability(config)(message, None)


def test_capability_capture_and_query(assist_env, tmp_path) -> None:
    config = _make_config(tmp_path)
    result = _run_capability(config, "收件箱 买牛奶")
    assert "买牛奶" in result.body
    assert result.capability_id == "bot.daily_assist"
    assert result.send_policy is SendPolicy.SILENT_AUDIT
    assert "daily_assist" in result.audit_tags
    inbox = inbox_path(config)
    assert "买牛奶" in inbox.read_text(encoding="utf-8")
    listing = _run_capability(config, "收件箱")
    assert "1 件" in listing.body and "买牛奶" in listing.body


def test_capability_help_when_bare_prefix_without_body(assist_env, tmp_path) -> None:
    config = _make_config(tmp_path)
    result = _run_capability(config, "收件箱?")
    assert "攒着" in result.body or "收件箱" in result.body
    assert "daily_assist" in result.audit_tags


def test_capability_long_body_truncated(assist_env, tmp_path) -> None:
    config = _make_config(tmp_path)
    _run_capability(config, "收件箱 " + "啊" * 2500)
    assert "啊" * 2000 in inbox_path(config).read_text(encoding="utf-8")
    assert "啊" * 2001 not in inbox_path(config).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 调度与私聊投递
# ---------------------------------------------------------------------------


class _FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[tuple[object, str, dict]] = []

    def add_job(self, func, trigger, **kwargs) -> None:
        self.jobs.append((func, trigger, kwargs))


class _FakeQueue:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    def submit(self, request) -> None:
        self.requests.append(request)


def test_parse_daily_assist_clock() -> None:
    assert _parse_daily_assist_clock("11:15") == (11, 15)
    assert _parse_daily_assist_clock("07:05") == (7, 5)
    assert _parse_daily_assist_clock("25:00") is None
    assert _parse_daily_assist_clock("abc") is None
    assert _parse_daily_assist_clock("") is None


def test_register_daily_assist_scheduler_jobs() -> None:
    scheduler = _FakeScheduler()
    config = _make_config(None)
    info = _register_daily_assist_scheduler(
        scheduler, config, _FakeQueue(), build_outbound_gate(SimpleNamespace())
    )
    assert info["meals"] == ["11:15", "17:15"]
    assert info["morning"] == [9, 0]
    assert info["evening"] == [21, 0]
    job_ids = {kwargs["id"] for _, _, kwargs in scheduler.jobs}
    assert job_ids == {
        "bot_daily_assist_meal_1115",
        "bot_daily_assist_meal_1715",
        "bot_daily_assist_morning",
        "bot_daily_assist_evening",
    }
    triggers = {id_: (hour, minute) for _, _, kwargs in scheduler.jobs
                for id_ in [kwargs["id"]]
                for hour, minute in [(kwargs["hour"], kwargs["minute"])]}
    assert triggers["bot_daily_assist_meal_1115"] == (11, 15)
    assert triggers["bot_daily_assist_morning"] == (9, 0)


def test_register_daily_assist_scheduler_skips_without_targets() -> None:
    scheduler = _FakeScheduler()
    config = _make_config(None, bot_daily_assist_push_user_ids=[])
    info = _register_daily_assist_scheduler(
        scheduler, config, _FakeQueue(), build_outbound_gate(SimpleNamespace())
    )
    assert info == {"skipped": "no_targets"}
    assert scheduler.jobs == []


def test_push_daily_assist_private_request_shape() -> None:
    queue = _FakeQueue()
    config = _make_config(None, bot_daily_assist_push_user_ids=["10001", "10002"])
    now = datetime(2026, 9, 15, 11, 15, tzinfo=timezone.utc)
    pushed = _push_daily_assist_private(
        config, queue, build_outbound_gate(SimpleNamespace()),
        capability_id="bot.daily_assist",
        text="到饭点啦", tag="meal-1115", now=now,
    )
    assert pushed == 2
    request = queue.requests[0]
    assert request.target_scope is SessionType.PRIVATE
    assert request.target_id == "10001"
    assert request.session_id == "private:10001"
    assert request.send_policy is SendPolicy.QUEUED
    assert request.privacy_level is PrivacyLevel.PERSONAL
    assert request.content.text_fallback == "到饭点啦"
    assert request.dedupe_key == "daily_assist:meal-1115:10001:2026-09-15"
    assert request.persona_profile_id == "default"


def test_meal_job_and_morning_runner_push(assist_env, tmp_path, monkeypatch) -> None:
    from plugins.bot_unified_runtime import (
        _run_daily_assist_meal_push,
        _run_daily_assist_morning_push,
    )

    # 离线纪律：早报里的 LLM 摘要在单测中打桩为空串（走回退文案）。
    # v21r2 W12：daily_assist 真身迁 domains/assistant/daily/store/，monkeypatch 打真身新路径。
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.domains.assistant.daily.store.daily_assist.summarize_with_llm",
        lambda *_args, **_kwargs: "",
    )

    config = _make_config(tmp_path)
    food = food_path(config)
    food.parent.mkdir(parents=True, exist_ok=True)
    food.write_text("- 拉面\n", encoding="utf-8")
    queue = _FakeQueue()
    _run_daily_assist_meal_push(config, queue, build_outbound_gate(SimpleNamespace()), "11:15")
    assert len(queue.requests) == 1
    assert "拉面" in queue.requests[0].content.text_fallback

    append_inbox_line(
        inbox_path(config), "买牛奶", now=datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc)
    )
    _run_daily_assist_morning_push(config, queue, build_outbound_gate(SimpleNamespace()))
    assert len(queue.requests) == 2
    assert "买牛奶" in queue.requests[1].content.text_fallback
    assert read_pending_inbox(inbox_path(config)) == []
    assert load_daily_archive(daily_archive_dir(config)) != []
