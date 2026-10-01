"""第 20 项补口席位回归（S-IMPL-SCHED20，2026-09-27）：三格缺口各自的锁。

三格（对齐席位简报，逐条锁死）：
- **G1 第一人称代答**：她亲口问「我现在在忙什么」应命中日程板、且只答**会话所有者**
  本人的板子；第三人称（她/他/主人）语义**不回归**（多超管仍不猜人、档位不变）。
- **G2 自看不外泄标题**：`_handle_list` 清单只落「时刻 + [公]/[密] 标记」，**逐字不含
  条目标题**（含反证锁——把清单行改成含 {item.title} 立刻变红）；群聊/私聊一视同仁。
- **G3 记录幂等**：同一句「日程 明天8点上高数」说两遍**不双记**（同天+同题+同刻）；
  不同时刻/不同标题仍分别记录（去重键不是只看标题）。

全离线 tmp_path；不碰网络、不碰真库、不启动任何服务。 fixtures 自带一份，
不与他席测试文件耦合（本席只新建此件，不改他人测试）。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.schedule.capabilities import (
    schedule_board as sb,
)
from plugins.bot_unified_runtime.domains.schedule.capabilities.schedule_board import (
    ScheduleAddIntent,
    _add_entry,
    is_status_question,
)

ZONE = ZoneInfo("Asia/Shanghai")
OWNER = "u_super"
OTHER_SUPER = "u_super2"


class _Config:
    """局部配置桩：本能力读取的键逐枚给值，杜绝 getattr 兜底糊过。"""

    def __init__(self, tmp_path: Path, **overrides: object) -> None:
        self.bot_schedule_enabled = True
        self.bot_schedule_db_path = str(tmp_path / "schedule_test.sqlite3")
        self.bot_schedule_status_reply_enabled = True
        self.bot_schedule_natural_capture_enabled = True
        self.bot_timezone = "Asia/Shanghai"
        self.bot_super_admin_user_ids = [OWNER]
        self.bot_admin_profiles = [{"user_id": OWNER, "name": "澜汐"}]
        self.bot_reminder_enabled = True
        self.bot_notes_enabled = True
        for key, value in overrides.items():
            setattr(self, key, value)


def _message(
    text: str,
    *,
    sender: str = "u_other",
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


def _make_active(
    config: _Config,
    owner: str,
    *,
    title: str,
    minutes_ago: int = 30,
    duration: int = 90,
    public: bool,
) -> None:
    store = sb.build_board_store(config)
    service = sb.build_board_service(config)
    start = datetime.now(ZONE) - timedelta(minutes=minutes_ago)
    _add_entry(
        service,
        store,
        # S-FIX-ATK-SCHED2 票1 跟改：能力腿建板已改吃平台域限定人物键，
        # 直连播种的 owner 必须过同一折算口（裸号=QQ 原生域），否则种进
        # 裸号桶、代答腿在限号桶读空——键形迁移，非新语义。
        sb._board_owner_from_roster_id(owner),
        ScheduleAddIntent(
            start_local=start,
            activity=title,
            duration_minutes=duration,
            public=public,
            weekly_weekday=None,
            parity=None,
            semester_start=None,
        ),
    )


# ===========================================================================
# G1 第一人称命中日程板 + 只答会话所有者
# ===========================================================================


def test_first_person_question_hits_board_and_shows_owner_private(
    config: _Config,
) -> None:
    """她亲口问「我现在在忙什么」→ 命中板面、owner 档看到自己隐私条目（现网落回聊天=红）。"""
    _make_active(config, OWNER, title="私下安排", public=False)
    body = _run(
        "我现在在忙什么",
        config,
        sender=OWNER,
        roles=["user", "admin", "super_admin"],
        group=False,
    )
    assert "私下安排" in body and "隐私" in body


def test_first_person_only_answers_session_owner_not_other_super(
    config: _Config, tmp_path: Path
) -> None:
    """两位超管各有公开进行中：她问「我…」只答她自己那条，绝不串到别人的板子。"""
    cfg = _Config(
        tmp_path,
        bot_super_admin_user_ids=[OWNER, OTHER_SUPER],
        bot_admin_profiles=[{"user_id": OWNER, "name": "澜汐"}],
    )
    _make_active(cfg, OWNER, title="高数课", public=True)
    _make_active(cfg, OTHER_SUPER, title="大学物理", public=True)
    body = _run(
        "我现在在干什么",
        cfg,
        sender=OWNER,
        roles=["user", "admin", "super_admin"],
        group=False,
    )
    assert "高数" in body  # 命中自己的板子
    assert "物理" not in body  # 不猜、不串到另一位超管


def test_first_person_group_does_not_leak_private(config: _Config) -> None:
    """超管在群里问「我…」：隐私条目不上全群可见面（收紧方向唯一）。"""
    _make_active(config, OWNER, title="私下安排", public=False)
    _make_active(config, OWNER, title="公开课", public=True)
    body = _run(
        "我现在在忙什么",
        config,
        sender=OWNER,
        roles=["user", "admin", "super_admin"],
        group=True,
    )
    assert "私下安排" not in body


# ===========================================================================
# G1 第三人称语义不回归
# ===========================================================================


def test_third_person_head_words_still_recognized(config: _Config) -> None:
    """她/他/主人 三点头词照常命中代答面（补第一人称不得挤掉第三人称）。"""
    assert is_status_question("她在干嘛", config=config)
    assert is_status_question("他在忙什么", config=config)
    assert is_status_question("主人在干嘛", config=config)


def test_third_person_two_owners_still_not_guessed(config: _Config, tmp_path: Path) -> None:
    """第三人称多超管同活仍回模糊句（第一人称限定 owner 不得外溢到第三人称路径）。"""
    cfg = _Config(
        tmp_path,
        bot_super_admin_user_ids=[OWNER, OTHER_SUPER],
        bot_admin_profiles=[{"user_id": OWNER, "name": "澜汐"}],
    )
    _make_active(cfg, OWNER, title="高数课", public=True)
    _make_active(cfg, OTHER_SUPER, title="大学物理", public=True)
    body = _run("她在干嘛", cfg, roles=["user", "trusted"])
    assert "高数" not in body and "物理" not in body  # 不猜人：逐字模糊句
    assert body in sb._FALLBACK_LINES


def test_second_person_still_excluded(config: _Config) -> None:
    """问 bot 本人（你…）仍不进代答面（补第一人称不得顺手放开第二人称）。"""
    assert not is_status_question("你在干嘛", config=config)
    assert not is_status_question("你今天在忙什么", config=config)


# ===========================================================================
# G2 自看不外泄：清单只落「时刻 + 标记」，绝不含条目标题（含反证锁）
# ===========================================================================


def _seed_private_and_public(config: _Config) -> None:
    _run("日程 明天8点去牙科复诊", config, sender=OWNER, roles=["user", "super_admin"], group=True)
    _run(
        "日程 明天9点开组会汇报 公开",
        config,
        sender=OWNER,
        roles=["user", "super_admin"],
        group=True,
    )


def test_group_self_view_never_leaks_entry_titles(config: _Config) -> None:
    """G2 反证锁：群聊自看清单只落时刻+标记，绝不出现任何条目标题（隐私题面尤甚）。

    现网 _handle_list 本就不取 title；把清单行改成含 {item.title} 即触发本锁当场变红。
    """
    _seed_private_and_public(config)
    body = _run("日程表", config, sender=OWNER, roles=["user", "super_admin"], group=True)
    assert "复诊" not in body and "牙科" not in body  # 隐私条目题面不外泄
    assert "组会" not in body  # 连公开条目标题也不落在自看清单（标记制投影）
    assert "[公]" in body  # 仍在如实报数（打码不是吞信）


def test_private_self_view_never_leaks_entry_titles(config: _Config) -> None:
    """私聊自看同样不标题化：sanitization 是整面的，不只在群里做样子。"""
    _seed_private_and_public(config)
    body = _run("日程表", config, sender=OWNER, roles=["user", "super_admin"], group=False)
    assert "复诊" not in body and "牙科" not in body  # 清单里就是不出现标题
    assert "[密]" in body  # 对本人不隐藏「有这么一条隐私」（只隐题面）


# ===========================================================================
# G3 记录幂等（同天+同题+同刻）
# ===========================================================================


def test_add_same_sentence_twice_is_idempotent(config: _Config) -> None:
    """同一句说两遍不双记：第二句回「已记过」，板上只有一条（私聊自看看全）。"""
    _run("日程 明天8点上高数", config, group=False)
    again = _run("日程 明天8点上高数", config, group=False)
    assert "已经记过" in again or "不重复记" in again
    listing = _run("日程表", config, group=False)
    assert listing.count("[密]") == 1  # 只有一条隐私条目


def test_add_different_time_still_records_both(config: _Config) -> None:
    """同标题不同时刻仍分别记录：去重键含时刻，绝不只看标题。"""
    _run("日程 明天8点上高数", config, group=False)
    _run("日程 明天9点上高数", config, group=False)
    listing = _run("日程表", config, group=False)
    assert listing.count("[密]") == 2


def test_add_different_title_same_time_still_records_both(config: _Config) -> None:
    """同刻不同标题分别记录：去重键含标题。"""
    _run("日程 明天8点上高数", config, group=False)
    _run("日程 明天8点开组会", config, group=False)
    listing = _run("日程表", config, group=False)
    assert listing.count("[密]") == 2
