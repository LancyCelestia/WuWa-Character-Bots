"""第 20 项「日程记录与智能代答」离线回归（S-SCHEDULE-20，2026-09-26）。

三族判据，一一对应用户原话的三件事：
- 记录腿：解析（复用提醒域唯一时间解析器）/建表复用引擎/列表/删/改可见性/课表导入；
- 代答腿：分级投影逐档锁死（隐私永不、公开给什么、敏感类别折叠、空板与全隐私板
  回同一句、地点与路径永不出口、多超管不猜人）；
- 结构锁：REMINDER 车道同源判据、无本机监控 import、代答路径零 LLM、
  总闸关=既有行为逐字节不变、复用 S11 引擎表（禁第二真身）。

全离线 tmp_path；不碰网络、不碰真库、不启动任何服务。
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.schedule.capabilities import (
    schedule_board as sb,
)
from plugins.bot_unified_runtime.domains.schedule.capabilities.reminder import (
    build_reminder_capability,
    is_reminder_command,
)
from plugins.bot_unified_runtime.domains.schedule.capabilities.schedule_board import (
    ScheduleAddIntent,
    _add_entry,
    classify_schedule_activity,
    is_schedule_command,
    is_schedule_natural,
    is_schedule_surface,
    is_status_question,
    parse_schedule_add,
    parse_time_target,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]

ZONE = ZoneInfo("Asia/Shanghai")
OWNER = "u_super"
ASKER = "u_other"
# S-FIX-ATK-SCHED2 票1：板主键改为平台域限定人物键（唯一构造口 session_keys.
# person_scope_key，经 schedule_board._board_owner_from_roster_id 折算——裸号
# 条目按名单原生域归 QQ，与能力腿同源）。既有件里**直连 store/_add_entry**
# 的播种与断言必须吃同一把键，否则与能力腿写的桶分家（这不是新语义，是
# 键形迁移的既有测试跟改）。
OWNER_KEY = sb._board_owner_from_roster_id(OWNER)


class _Config:
    """局部配置桩（本能力读的全部键逐枚显式给值，杜绝「缺字段被 getattr 兜底糊过」。"""

    def __init__(self, tmp_path: Path, **overrides: object) -> None:
        self.bot_schedule_enabled = True
        self.bot_schedule_db_path = str(tmp_path / "schedule_test.sqlite3")
        self.bot_schedule_status_reply_enabled = True
        self.bot_schedule_natural_capture_enabled = True
        self.bot_timezone = "Asia/Shanghai"
        self.bot_super_admin_user_ids = [OWNER]
        self.bot_admin_profiles = [{"user_id": OWNER, "name": "澜汐"}]
        # 车道邻居的既有开关（提醒/笔记照常开，测并联不串扰）
        self.bot_reminder_enabled = True
        self.bot_notes_enabled = True
        for key, value in overrides.items():
            setattr(self, key, value)


def _message(
    text: str,
    *,
    sender: str = ASKER,
    roles: list[str] | None = None,
    group: bool = True,
    request_id: str = "req-fixed",
    segments: list[dict] | None = None,
    command_text: str = "",
) -> IncomingMessage:
    return IncomingMessage(
        request_id=request_id,
        platform="onebot11",
        adapter="onebot11",
        bot_id="bot1",
        session_id=f"group_100_{sender}" if group else f"private_{sender}_{sender}",
        session_type=SessionType.GROUP if group else SessionType.PRIVATE,
        sender_id=sender,
        plain_text=text,
        command_text=command_text,
        sender_roles=roles or ["user"],
        message_id=f"m-{request_id}",
        raw_segments=segments or [],
    )


@pytest.fixture()
def config(tmp_path: Path) -> _Config:
    return _Config(tmp_path)


def _run(cap_text: str, config: _Config, **msg_kw) -> str:
    capability = sb.build_schedule_board_capability(config)
    message = _message(cap_text, **msg_kw)
    result = capability(message, None)
    assert result is not None, f"能力未承接: {cap_text!r}"
    return result.body


# ===========================================================================
# 解析族（时间解析唯一复用提醒域真身；正文/范围/重复/公开标记）
# ===========================================================================


def test_parse_reminder_intent_behavior_unchanged_after_extraction() -> None:
    """抽取重构回归锁：提醒侧行为逐字节不变（级联进了共享函数，口径零漂移）。"""
    from plugins.bot_unified_runtime.domains.schedule.store.reminders import (
        parse_reminder_intent,
    )

    now = datetime(2026, 9, 26, 10, 0, tzinfo=ZONE)
    intent = parse_reminder_intent("明天8点提醒我上课", now=now)
    assert intent is not None
    assert intent.remind_at.month == 9 and intent.remind_at.day == 27
    assert intent.remind_at.hour == 8
    assert "提醒" not in intent.text and "上课" in intent.text
    assert parse_reminder_intent("没有信号词8点", now=now) is None


def test_parse_time_target_public_entry() -> None:
    """公开口：无提醒信号也能解出未来时刻；已过点无日词 → 顺延明天（与提醒同级联）。"""
    now = datetime(2026, 9, 26, 23, 0, tzinfo=ZONE)
    target = parse_time_target("9点开会", now=now)
    assert target is not None and target.day == 27 and target.hour == 9
    assert parse_time_target("毫无时间", now=now) is None


def test_add_once_with_range_and_public() -> None:
    now = datetime(2026, 9, 26, 10, 0, tzinfo=ZONE)
    intent = parse_schedule_add("日程 明天8点到9点半 高数 公开", now=now)
    assert intent is not None
    assert intent.start_local.day == 27 and intent.start_local.hour == 8
    assert intent.duration_minutes == 90
    assert intent.public is True
    assert "高数" in intent.activity
    assert intent.weekly_weekday is None


def test_add_weekly_and_parity_shapes() -> None:
    now = datetime(2026, 9, 26, 10, 0, tzinfo=ZONE)
    weekly = parse_schedule_add("日程 每周三14:00 组会", now=now)
    assert weekly is not None and weekly.weekly_weekday == 2 and weekly.parity is None
    parity = parse_schedule_add("日程 双周周五8点上现代史纲要 学期 2026-09-07", now=now)
    assert parity is not None and parity.parity == "even"
    assert parity.semester_start == "2026-09-07"


def test_add_without_time_returns_none() -> None:
    now = datetime(2026, 9, 26, 10, 0, tzinfo=ZONE)
    assert parse_schedule_add("日程 随便聊聊", now=now) is None


# ===========================================================================
# 记录腿端到端（能力面：建/列/删/公开切换/导入，全走引擎真身）
# ===========================================================================


def test_add_list_delete_flow(config: _Config) -> None:
    body = _run("日程 明天8点到9点半 高数", config)
    assert "记上了" in body and "高数" in body
    listing = _run("日程表", config)
    assert "- 1" in listing and "[密]" in listing
    assert "放下" in _run("日程 删 1", config)
    assert "空着" in _run("日程表", config)


def test_delete_whole_rule_removes_recurrence(config: _Config) -> None:
    _run("日程 每周三14:00 组会", config)
    assert "放下" in _run("日程 删课 1", config)
    # 整条放下后未来 30 天不应再有该实例（supersede + plan 重写双效）
    assert "空着" in _run("日程表", config)


def test_visibility_toggle_flow(config: _Config) -> None:
    _run("日程 明天8点上高数", config)
    assert "可答" in _run("日程 公开 1", config)
    assert "[公]" in _run("日程表", config)
    assert "隐私档" in _run("日程 隐私 1", config)
    assert "[密]" in _run("日程表", config)


def test_add_with_public_keyword_is_public_from_start(config: _Config) -> None:
    _run("日程 明天8点上高数 公开", config)
    assert "[公]" in _run("日程表", config)


def test_parity_without_semester_asks_and_stores_nothing(config: _Config) -> None:
    body = _run("日程 单周周三8点上高数", config)
    assert "学期" in body  # 只回问，绝不猜学期起点
    assert "空着" in _run("日程表", config)


def test_import_text_lines_and_dedupe(config: _Config) -> None:
    block = "日程 导入\n周一 8:00-9:40 高数 一教101\n周三 10:00-11:40 大学物理"
    body = _run(block, config)
    assert "记下了 2 条" in body and "隐私" in body
    again = _run(block, config)
    assert "完全重复" in again
    listing = _run("日程表", config)
    assert listing.count("- ") >= 4  # 每周两条 × 多周次


def test_import_requires_semester_for_parity_lines(config: _Config) -> None:
    body = _run("日程 导入\n周二 8:00-9:40 线性代数 单", config)
    assert "学期" in body
    assert "空着" in _run("日程表", config)


def test_board_reuses_engine_tables_only(tmp_path: Path, config: _Config) -> None:
    """禁第二真身结构锁：日程板只写 S11 引擎既有表，绝不新表。"""
    _run("日程 明天8点上高数", config)
    store = sb.build_board_store(config)
    names = {
        row[0]
        for row in store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert {"schedule_plans", "schedule_occurrences"} <= names
    assert not {"schedule_entries", "board_items", "schedule_board"} & names


def test_purge_only_touches_terminal_rows(config: _Config) -> None:
    store = sb.build_board_store(config)
    service = sb.build_board_service(config)
    _add_entry(
        service, store, OWNER,
        ScheduleAddIntent(
            start_local=datetime.now(ZONE) + timedelta(hours=2),
            activity="将被放下的事", duration_minutes=60, public=False,
            weekly_weekday=None, parity=None, semester_start=None,
        ),
    )
    _add_entry(
        service, store, OWNER,
        ScheduleAddIntent(
            start_local=datetime.now(ZONE) + timedelta(days=3),
            activity="还要留着的事", duration_minutes=60, public=False,
            weekly_weekday=None, parity=None, semester_start=None,
        ),
    )
    plan_id = store.plan_id_for_owner(OWNER)
    assert plan_id is not None
    rows = store.list_occurrences(plan_id=plan_id, status="pending", limit=10)
    assert rows
    oid = str(rows[0]["occurrence_id"])
    store.mark_done(oid, now_utc=datetime.now(UTC))
    # 手工把这条 done 实例推到 90 天窗外（模拟久病存量），再跑 prune。
    # 2026-09-29 S-FIX-SCHED-BOARD：恢复 HEAD 布景步（无此步 done 行 due 在 +2h，
    # 90 天闸永裁不到）。HEAD 的 SLF001 抑制注与 `import sqlite3` 不带回——钉版
    # 规则集（pyproject S-FIX-LINT-PIN）不选 SLF001、选 RUF100/F401，带回必红
    # 「unused 抑制注」/「unused import」，且此块本就不用 sqlite3 模块。
    with store._lock, store._conn:
        store._conn.execute(
            "UPDATE schedule_occurrences SET due_epoch=? WHERE occurrence_id=?",
            (datetime.now(UTC).timestamp() - 400 * 86400, oid),
        )
    store.purge_terminal(before_epoch=sb.purge_cutoff_epoch())
    after = store.list_occurrences(plan_id=plan_id, limit=100)
    assert all(str(r["occurrence_id"]) != oid for r in after)  # 过期终态被裁
    assert any(str(r["status"]) == "pending" for r in after)  # 待办一条不裁


def test_capability_dispatches_schedule_before_notes(config: _Config) -> None:
    """能力分发腿可达性锁：经 build_reminder_capability 入口真跑到日程面。"""
    capability = build_reminder_capability(config)
    message = _message("日程 明天8点上高数")
    result = capability(message, None)
    assert result is not None
    assert "记上了" in result.body and "高数" in result.body
    assert "schedule" in (result.audit_tags or [])


def test_retag_future_occurrences_only(config: _Config) -> None:
    store = sb.build_board_store(config)
    service = sb.build_board_service(config)
    _add_entry(
        service, store, OWNER,
        ScheduleAddIntent(
            start_local=datetime.now(ZONE) + timedelta(days=2),
            activity="每周测量", duration_minutes=60, public=False,
            weekly_weekday=1, parity=None, semester_start=None,
        ),
    )
    plan_id = store.plan_id_for_owner(OWNER)
    assert plan_id is not None
    rows = store.list_occurrences(plan_id=plan_id, status="pending", limit=100)
    assert len(rows) >= 2
    rule_id = str(rows[0]["rule_id"])
    past_done = rows[0]["occurrence_id"]
    store.mark_done(past_done, now_utc=datetime.now(UTC))
    changed = store.retag_future_occurrences(
        plan_id, rule_id, public=True,
        after_epoch=datetime.now(UTC).timestamp(),
    )
    fresh = {str(r["occurrence_id"]): (r.get("tags") or []) for r in
             store.list_occurrences(plan_id=plan_id, limit=100)}
    assert sb.VIS_PUBLIC not in fresh[past_done]  # 已完成的旧实例不回改（历史如实）
    assert changed >= 1
    pending = store.list_occurrences(plan_id=plan_id, status="pending", limit=100)
    assert all(sb.VIS_PUBLIC in (r.get("tags") or []) for r in pending)


def test_recurring_teaching_week_stored_in_engine(config: _Config) -> None:
    store = sb.build_board_store(config)
    service = sb.build_board_service(config)
    _add_entry(
        service, store, OWNER,
        ScheduleAddIntent(
            start_local=datetime(2026, 9, 30, 8, 0, tzinfo=ZONE),
            activity="现代史纲要", duration_minutes=100, public=False,
            weekly_weekday=2, parity="odd", semester_start="2026-09-07",
        ),
    )
    plan = service.get_plan(f"board-{OWNER}")
    rule = next(r for r in plan.rules)
    assert rule.kind.value == "teaching_week"
    assert rule.week_parity.value == "odd"
    assert rule.parity_anchor_date == "2026-09-07"


def test_import_image_clarify_path_no_guess(config: _Config, monkeypatch: pytest.MonkeyPatch) -> None:
    """图片课表缺学期锚：只回问不落库（识图 provider 由她这条消息触发，禁猜）。"""
    from plugins.bot_unified_runtime.domains.schedule import timetable as tt

    monkeypatch.setattr(tt, "build_timetable_provider", lambda _config: object())

    def _fake_recognize(provider, images, **kwargs):
        return tt.TimetableDraft(courses=[
            tt.CourseEntry(
                course_name="高数", weekday=0, start_time="08:00",
                end_time="09:40", week_parity="odd",
            ),
        ], semester_start=None)

    monkeypatch.setattr(tt, "recognize_timetable", _fake_recognize)
    capability = sb.build_schedule_board_capability(config)
    message = _message(
        "课表",
        segments=[{"type": "image", "data": {"url": "https://example.invalid/x.png"}}],
    )
    result = capability(message, None)
    assert result is not None
    assert "学期" in result.body  # 单双周缺学期锚：只回问，绝不猜
    assert "空着" in _run("日程表", config)


def test_import_image_commits_private(config: _Config, monkeypatch: pytest.MonkeyPatch) -> None:
    from plugins.bot_unified_runtime.domains.schedule import timetable as tt

    monkeypatch.setattr(tt, "build_timetable_provider", lambda _config: object())

    def _fake_recognize(provider, images, **kwargs):
        return tt.TimetableDraft(courses=[
            tt.CourseEntry(course_name="高数 一教101", weekday=0, start_time="08:00", end_time="09:40"),
        ], semester_start="2026-09-07", period_table={1: ["08:00", "09:40"]})

    monkeypatch.setattr(tt, "recognize_timetable", _fake_recognize)
    capability = sb.build_schedule_board_capability(config)
    message = _message(
        "课表",
        segments=[{"type": "image", "data": {"url": "https://example.invalid/x.png"}}],
    )
    result = capability(message, None)
    assert result is not None and "记" in result.body
    listing = _run("日程表", config)
    assert "[密]" in listing  # 图片导入不自动公开


# ===========================================================================
# 代答腿（分级投影：每档一锁，全走「此刻进行中」条目）
# ===========================================================================


def _make_active_entry(
    config: _Config,
    *,
    title: str,
    minutes_ago: int = 30,
    duration: int = 90,
    public: bool,
    location: str = "",
) -> None:
    store = sb.build_board_store(config)
    service = sb.build_board_service(config)
    start = datetime.now(ZONE) - timedelta(minutes=minutes_ago)
    # 2026-09-29 S-FIX-SCHED-BOARD：直连 _add_entry 的播种吃 OWNER_KEY（票1 键形
    # 迁移跟改，理由见件顶注释——与能力腿写的桶同源，否则能力腿永远查无）。
    _add_entry(
        service, store, OWNER_KEY,
        ScheduleAddIntent(
            start_local=start, activity=title, duration_minutes=duration,
            public=public, weekly_weekday=None, parity=None, semester_start=None,
            location=location,
        ),
    )


def test_answer_basic_tier_gets_category_not_title(config: _Config) -> None:
    _make_active_entry(config, title="高数课", public=True, location="一教101")
    body = _run("她在干嘛", config)
    assert "在上课" in body  # 类别词
    assert "高数" not in body  # 普通用户档不给活动名
    assert "一教101" not in body  # 地点永不出口


def test_answer_trusted_tier_gets_title_still_no_location(config: _Config) -> None:
    _make_active_entry(config, title="高数课", public=True, location="一教101")
    body = _run("她在干嘛", config, roles=["user", "trusted"])
    assert "高数" in body and "一教101" not in body


def test_answer_admin_tier_equals_trusted_on_data(config: _Config) -> None:
    _make_active_entry(config, title="组织行为学研讨", public=True)
    body = _run("主人在干嘛", config, roles=["user", "admin"])
    assert "组织行为学研讨" in body


def test_answer_private_entry_invisible_to_everyone_but_owner(config: _Config) -> None:
    _make_active_entry(config, title="牙科复诊", public=False)
    for roles in (["user"], ["user", "trusted"], ["user", "admin"], ["user", "super_admin"]):
        body = _run("她在干嘛", config, roles=roles)
        assert "复诊" not in body and "牙" not in body
        assert body in sb._FALLBACK_LINES  # 模糊句池（条目缺席不是证据）


def test_answer_sensitive_public_still_collapses_nature(config: _Config) -> None:
    """标了公开的健康条目：给时刻与「有事情」，不给「吃药/复诊」这类性质词。"""
    _make_active_entry(config, title="吃降压药", public=True)
    basic = _run("她在干嘛", config)
    assert "药" not in basic and "有事情" in basic
    trusted = _run("她在干嘛", config, roles=["user", "trusted"])
    assert "药" not in trusted  # 敏感类别连 trusted 也不给题面
    assert "有事情" in trusted


def test_answer_empty_board_and_private_only_board_are_word_for_word_same(
    config: _Config, tmp_path: Path
) -> None:
    """空板 vs 全隐私板：对提问者逐字同一句模糊——不泄露「日程表存不存在/空不空」。"""
    private_only_cfg = _Config(
        tmp_path, bot_schedule_db_path=str(tmp_path / "s1.sqlite3")
    )
    empty_cfg = _Config(tmp_path, bot_schedule_db_path=str(tmp_path / "s2.sqlite3"))
    _make_active_entry(private_only_cfg, title="私下安排", public=False)
    body_private = _run("她在干嘛", private_only_cfg)
    body_empty = _run("她在干嘛", empty_cfg)
    assert body_private == body_empty
    assert "私下" not in body_private


def test_answer_owner_private_chat_sees_all(config: _Config) -> None:
    _make_active_entry(config, title="私下安排", public=False)
    body = _run(
        "她在干嘛", config,
        sender=OWNER, roles=["user", "admin", "super_admin"], group=False,
    )
    assert "私下安排" in body and "隐私" in body


def test_answer_owner_in_group_gets_public_face_only(config: _Config) -> None:
    """超管在群里问：隐私条目不上全群可见的回复面（收紧方向唯一）。"""
    _make_active_entry(config, title="私下安排", public=False)
    _make_active_entry(config, title="公开课", public=True)
    body = _run(
        "她在干嘛", config,
        sender=OWNER, roles=["user", "admin", "super_admin"], group=True,
    )
    assert "私下安排" not in body
    assert "完整日程" in body  # 私聊引导句


def test_answer_other_super_admin_no_bypass(config: _Config) -> None:
    """另一位超管问：不因同级绕隐私——与 trusted 同格。"""
    _make_active_entry(config, title="私下安排", public=False)
    body = _run(
        "她在干嘛", config,
        sender="u_super2", roles=["user", "admin", "super_admin"],
    )
    assert "私下安排" not in body


def test_answer_multiple_active_picks_earliest(config: _Config) -> None:
    _make_active_entry(config, title="会议A", minutes_ago=90, duration=180, public=True)
    _make_active_entry(config, title="组会B", minutes_ago=10, duration=60, public=True)
    body = _run("她在干嘛", config, roles=["user", "trusted"])
    assert "会议A" in body and "组会B" not in body


def _make_active_entry_for(cfg: _Config, owner: str, title: str) -> None:
    store = sb.build_board_store(cfg)
    service = sb.build_board_service(cfg)
    # 2026-09-29 S-FIX-SCHED-BOARD：名单裸号先经能力腿同一把尺折成板主键再播种
    # （票1 键形迁移跟改，件顶注释为准；不折则落裸桶、代答腿查无）。
    _add_entry(
        service, store, sb._board_owner_from_roster_id(owner),
        ScheduleAddIntent(
            start_local=datetime.now(ZONE) - timedelta(minutes=5),
            activity=title, duration_minutes=60, public=True,
            weekly_weekday=None, parity=None, semester_start=None,
        ),
    )


def test_answer_two_owners_active_is_not_guessed(config: _Config, tmp_path: Path) -> None:
    """两位超管同时有公开进行中：绝不猜人，回模糊句（唯一命中才答）。"""
    cfg = _Config(tmp_path, bot_super_admin_user_ids=[OWNER, "u_super2"])
    _make_active_entry_for(cfg, OWNER, "高数")
    _make_active_entry_for(cfg, "u_super2", "大学物理")
    body = _run("她在干嘛", cfg)
    assert "高数" not in body and "物理" not in body
    assert body in sb._FALLBACK_LINES  # 多主不猜人：回模糊句池


def test_answer_named_super_by_display_name(config: _Config, tmp_path: Path) -> None:
    """点名「澜汐在忙什么」：显示名→超管 id 走档案真身，无第二名单。"""
    cfg = _Config(tmp_path, bot_super_admin_user_ids=[OWNER, "u_other_super"])
    _make_active_entry_for(cfg, OWNER, "高数")
    body = _run("澜汐在忙什么", cfg, roles=["user", "trusted"])
    assert "高数" in body


def test_answer_zero_llm_structurally() -> None:
    """代答路径零大模型：投影与取数函数源码里不存在任何模型调用面（不靠模型自觉）。"""
    src = Path(sb.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    banned = {"build_model_router", "model_router", "llm", "generate"}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in {
            "_project_answer", "active_entries", "asker_tier", "_pick_fallback",
            # F811 去重并入旧层副本的覆盖面（该函数现役生产未定义＝空转锁，
            # 将来谁加 format_answer 就自动被本锁管到）。
            "format_answer",
        }:
            names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            assert not (names & banned), f"{node.name} 引用了模型面: {names & banned}"


def test_answer_body_redacts_local_paths(config: _Config) -> None:
    """条目正文若被写入本机绝对路径形态，出站前必被 redact_local_secrets 洗掉。"""
    _make_active_entry(config, title="去 C:\\Users\\public\\a.jpg 拿快递", public=True)
    body = _run("她在干嘛", config, roles=["user", "trusted"])
    assert "C:\\Users\\" not in body and "Users" not in body  # 盘符路径被洗
    assert "拿快递" in body  # 活动本身仍可答（打码不是吞信）


def test_zero_duration_active_window(config: _Config) -> None:
    """只说了开始时刻的公开条目：进行中窗口按记载值兜底（120 分钟），答句用「起」。"""
    _make_active_entry(config, title="组会", minutes_ago=10, duration=0, public=True)
    body = _run("她在干嘛", config, roles=["user", "trusted"])
    assert "组会" in body and "起" in body


def test_answer_before_start_falls_back(config: _Config) -> None:
    """还没开始的活动不构成「正在做」——回模糊句，不预告。"""
    _make_active_entry(config, title="明天的课", minutes_ago=-60, duration=90, public=True)
    body = _run("她在干嘛", config)
    assert "明天的课" not in body
    assert body in sb._FALLBACK_LINES


# ===========================================================================
# 车道与开关（REMINDER 复用；关闸=逐字节让路）
# ===========================================================================


def test_surface_switches_off_means_route_silent(config: _Config) -> None:
    off = _Config(
        Path(config.bot_schedule_db_path).parent,
        bot_schedule_enabled=False,
        bot_schedule_status_reply_enabled=True,
        bot_schedule_natural_capture_enabled=True,
    )
    assert not is_schedule_command("日程表", config=off)
    assert not is_status_question("她在干嘛", config=off)
    assert not is_schedule_natural("明天8点有课", config=off)
    assert not is_schedule_surface("她在干嘛", config=off)
    assert not is_reminder_command("日程表", config=off)
    assert not is_reminder_command("她在干嘛", config=off)
    assert not is_reminder_command("明天8点有课", config=off)


def test_reply_switch_off_keeps_record_face(config: _Config) -> None:
    no_reply = _Config(
        Path(config.bot_schedule_db_path).parent,
        bot_schedule_status_reply_enabled=False,
    )
    assert is_schedule_command("日程表", config=no_reply)
    assert not is_status_question("她在干嘛", config=no_reply)


def test_neighbour_surfaces_untouched(config: _Config) -> None:
    """并联零串扰：笔记/提醒/取消等既有词面照常进 REMINDER 车道。"""
    for probe in ("笔记列表", "提醒列表", "取消提醒 a3f2", "12点提醒我写作业", "做完 2"):
        assert is_reminder_command(probe, config=config), probe
    # 日程词不会把提醒词吸走：含提醒信号的短句仍走提醒面
    assert is_reminder_command("明天8点提醒我上课", config=config)
    assert not is_schedule_natural("明天8点提醒我上课", config=config)


def test_capability_dispatches_schedule_via_reminder_entry(config: _Config) -> None:
    """能力分发腿可达性锁：经 build_reminder_capability 入口真跑到日程面。"""
    capability = build_reminder_capability(config)
    message = _message("日程 明天8点上高数")
    result = capability(message, None)
    assert result is not None
    assert "记上了" in result.body and "高数" in result.body
    assert "schedule" in (result.audit_tags or [])


def test_single_predicate_used_by_both_legs() -> None:
    """#45 三腿教义锁：路由腿与能力腿引用同一个 is_schedule_surface（AST 现算）。"""
    text = (
        _REPO_ROOT
        / "plugins/bot_unified_runtime/domains/schedule/capabilities/reminder.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(text)
    names = {
        node.func.id  # type: ignore[attr-defined]
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "is_schedule_surface" in names


def test_natural_capture_default_off_respects_switch(tmp_path: Path) -> None:
    off = _Config(tmp_path, bot_schedule_natural_capture_enabled=False)
    assert not is_schedule_natural("明天8点有课", config=off)
    on = _Config(tmp_path, bot_schedule_natural_capture_enabled=True)
    assert is_schedule_natural("明天8点有课", config=on)
    body = _run("明天8点有课", on)
    assert "记上了" in body
    assert "[密]" in _run("日程表", on)  # 自然捕捉缺省隐私


def test_question_head_stripping_for_mentions(config: _Config) -> None:
    assert is_status_question("@守岸人，主人在干嘛？", config=config)
    assert is_status_question("她在忙什么", config=config)
    assert not is_status_question("你今天在干嘛呀", config=config)  # 问 bot 本人不进代答面
    assert not is_status_question("我说明天她在干嘛来着", config=config)  # 长句从句不截胡


# ===========================================================================
# 结构卫生（信息源硬边界 + 分类器锁）
# ===========================================================================

_ALLOWED_IMPORT_ROOTS = {
    "__future__", "logging", "re", "dataclasses", "datetime", "hashlib", "typing",
    "zoneinfo", "functools",
    "plugins",
}
_BANNED_MONITOR_ROOTS = {
    "psutil", "subprocess", "socket", "ctypes", "webbrowser", "winreg",
    "shutil", "platform", "tempfile", "asyncio", "threading", "os",
}


def test_no_host_monitoring_imports() -> None:
    """硬边界：日程板模块不 import 任何本机监控面（设备/进程/网络/文件系统扫描）。

    她「睡了/吃了什么/在哪里」的唯一来源是她说过的话——代码面上就没有第二条取数路。
    """
    tree = ast.parse(Path(sb.__file__).read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    leaked = roots & _BANNED_MONITOR_ROOTS
    assert not leaked, f"日程板出现本机监控面 import: {leaked}"
    assert roots <= _ALLOWED_IMPORT_ROOTS, f"越权 import 根: {roots - _ALLOWED_IMPORT_ROOTS}"


def test_category_classifier_locks_sensitive_order() -> None:
    assert classify_schedule_activity("去看牙医") == "health"
    assert classify_schedule_activity("吃降压药") == "health"
    assert classify_schedule_activity("午休") == "rest"
    assert classify_schedule_activity("聚餐") == "meal"
    assert classify_schedule_activity("上高数课") == "course"
    assert classify_schedule_activity("出门取件") == "away"
    # F811 去重：旧层副本的另一枚判据（实跑证两串现均归 away，两句都留）
    assert classify_schedule_activity("出门取快递") == "away"  # 取件在 away 词表，快于快递歧义
    assert classify_schedule_activity("写报告") == "busy"
