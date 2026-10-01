"""S-FIX-ATK-SCHED2 票1+票5（ATK-SCHED 审计票1/票4）：板主键接管链与删课撞号回归。

票1 锁（探针 ATKSCHED-1 同型）：日程板键改为平台域限定人物键后——
- TG 同号者对 QQ 超管的板**读写全空**（列表空、翻公开 miss、删 miss、
  投毒只落自己的桶），受害者板逐格不动；
- owner 档只在**同键**时成立——同号不同域拼不出 owner；
- 第三人称代答经 ``_board_owner_from_roster_id`` 折算仍能从名单命中本人板子
  （修复不误伤正常代答面）。

票5 锁（探针 ATKSCHED-4 同型）：「日程 删课」删掉非末尾条目后新增不再撞
引擎 duplicate task_id——取号只进不退（eNNN 最大值+1），板可继续自愈。

全离线 tmp_path；不碰网络、不碰真库、不启动任何服务。
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
)

ZONE = ZoneInfo("Asia/Shanghai")
VICTIM = "10001"  # QQ 超管（名单裸号条目）


class _Config:
    def __init__(self, tmp_path: Path, **overrides: object) -> None:
        self.bot_schedule_enabled = True
        self.bot_schedule_db_path = str(tmp_path / "atk_sched2.sqlite3")
        self.bot_schedule_status_reply_enabled = True
        self.bot_schedule_natural_capture_enabled = True
        self.bot_timezone = "Asia/Shanghai"
        self.bot_super_admin_user_ids = [VICTIM]
        self.bot_admin_profiles = [{"user_id": VICTIM, "name": "澜汐"}]
        for key, value in overrides.items():
            setattr(self, key, value)


def _message(
    text: str,
    *,
    platform: str = "qq",
    sender: str = VICTIM,
    roles: list[str] | None = None,
    group: bool = False,
    session_type: SessionType | None = None,
    request_id: str = "req-atk2",
) -> IncomingMessage:
    return IncomingMessage(
        request_id=request_id,
        platform=platform,
        adapter="nonebot" if platform == "qq" else "telegram",
        bot_id="bot1",
        session_id=f"{platform}_{sender}",
        session_type=session_type or (SessionType.GROUP if group else SessionType.PRIVATE),
        sender_id=sender,
        plain_text=text,
        command_text=text,
        sender_roles=roles or ["user"],
        message_id=f"m-{request_id}",
        raw_segments=[],
    )


@pytest.fixture()
def config(tmp_path: Path) -> _Config:
    return _Config(tmp_path)


def _run(cap_text: str, config: _Config, **msg_kw) -> str:
    capability = sb.build_schedule_board_capability(config)
    result = capability(_message(cap_text, **msg_kw), None)
    assert result is not None, f"能力未承接: {cap_text!r}"
    return result.body


# ===========================================================================
# 票1：跨平台同号接管链全断
# ===========================================================================


def test_same_id_other_platform_sees_empty_board(config: _Config) -> None:
    """TG 同号者列 QQ 超管的板：只会看到自己的空桶，隐私题面一字不出。"""
    _run("日程 明天8点去牙科复诊", config, platform="qq")
    body = _run("日程表", config, platform="telegram", request_id="req-atk2-tg")
    assert "空着" in body
    assert "复诊" not in body and "牙科" not in body


def test_same_id_other_platform_cannot_flip_visibility_or_delete(config: _Config) -> None:
    """翻公开/删除在攻击者桶里都是 miss——受害者条目逐格不动。"""
    _run("日程 明天8点去牙科复诊", config, platform="qq")
    flip = _run("日程 公开 1", config, platform="telegram", request_id="req-atk2-flip")
    assert "没有第 1 条" in flip
    delete = _run("日程 删 1", config, platform="telegram", request_id="req-atk2-del")
    assert "没有第 1 条" in delete
    # 受害者自己的板仍在（原桶未被掏空/翻转）。
    listing = _run("日程表", config, platform="qq", request_id="req-atk2-v")
    assert listing.count("[密]") == 1


def test_poison_lands_on_attacker_bucket_victim_untouched(config: _Config) -> None:
    """投毒只脏自己的桶：受害者列表条目数与内容不变。"""
    _run("日程 明天8点去牙科复诊", config, platform="qq")
    poison = _run("日程 明天9点上冒名课", config, platform="telegram", request_id="req-atk2-p")
    assert "记上了" in poison  # 写成功——但写进的是 telegram:10001 自己的桶
    victim_listing = _run("日程表", config, platform="qq", request_id="req-atk2-v2")
    assert "冒名" not in victim_listing
    assert victim_listing.count("[密]") == 1


def test_owner_tier_requires_key_not_bare_id(config: _Config) -> None:
    """同号 TG 者自带 super_admin 角色话术也拿不到 owner 档：键不同即非本人。"""
    store = sb.build_board_store(config)
    service = sb.build_board_service(config)
    _add_entry(  # 受害者（qq:10001）板上放一条**进行中**的隐私条目
        service,
        store,
        sb._board_owner_from_roster_id(VICTIM),
        ScheduleAddIntent(
            start_local=datetime.now(ZONE) - timedelta(minutes=30),
            activity="私下安排", duration_minutes=90, public=False,
            weekly_weekday=None, parity=None, semester_start=None,
        ),
    )
    # 真主（qq 私聊）第一人称：owner 档如实报自己隐私条目。
    body = _run(
        "我现在在忙什么", config, platform="qq",
        roles=["user", "super_admin"], request_id="req-atk2-own",
    )
    assert "私下安排" in body and "隐私" in body
    # 同号冒充者（telegram 私聊、同样自称超管）：读的是自己的空桶——
    # owner 档即便成立也只对自己的板成立，受害者条目一字不出口。
    fake = _run(
        "我现在在忙什么", config, platform="telegram",
        roles=["user", "super_admin"], request_id="req-atk2-fake",
    )
    assert "私下安排" not in fake


def test_third_person_answer_still_resolves_roster_to_qualified_board(config: _Config) -> None:
    """名单→板键折算不误伤正常代答：trusted 第三人称仍可答公开条目。"""
    store = sb.build_board_store(config)
    service = sb.build_board_service(config)
    _add_entry(
        service,
        store,
        sb._board_owner_from_roster_id(VICTIM),
        ScheduleAddIntent(
            start_local=datetime.now(ZONE) - timedelta(minutes=10),
            activity="高数课", duration_minutes=90, public=True,
            weekly_weekday=None, parity=None, semester_start=None,
        ),
    )
    body = _run(
        "她在干嘛", config, platform="qq", sender="u_friend",
        roles=["user", "trusted"], group=True, request_id="req-atk2-3p",
    )
    assert "高数" in body


def test_unknown_platform_gets_isolated_bucket(config: _Config) -> None:
    """不认识的平台 fail-closed：吃不到 QQ 板（空域独立桶）。"""
    _run("日程 明天8点去牙科复诊", config, platform="qq")
    body = _run("日程表", config, platform="discord", request_id="req-atk2-dc")
    assert "空着" in body and "复诊" not in body


# ===========================================================================
# 票5：删课后取号只进不退（永久 dup task_id 修复）
# ===========================================================================


def test_add_after_deleting_middle_course_recovers(config: _Config) -> None:
    """删掉非末尾条目后新增必须成功：旧式 len(tasks)+1 在这里永久撞号（探针4）。"""
    _run("日程 明天8点上甲", config)
    _run("日程 明天9点上乙", config)
    _run("日程 明天10点上丙", config)
    assert "放下" in _run("日程 删课 2", config)  # 删中段：len 从 3 → 2
    revived = _run("日程 明天11点上丁", config)
    assert "记上了" in revived and "放不下" not in revived  # 修复前：error「这会儿放不下」
    listing = _run("日程表", config, request_id="req-atk2-list")
    assert listing.count("[密]") == 3


def test_task_ids_unique_and_forward_only(config: _Config) -> None:
    """多轮「删中段+新增」后板上 task_id 互异且编号不回退。"""
    _run("日程 明天8点上甲", config)
    _run("日程 明天9点上乙", config)
    _run("日程 明天10点上丙", config)
    _run("日程 删课 2", config)
    _run("日程 明天11点上丁", config)
    _run("日程 删课 1", config)
    _run("日程 明天12点上戊", config)
    store = sb.build_board_store(config)
    service = sb.build_board_service(config)
    plan_id = store.plan_id_for_owner(sb._board_owner_from_roster_id(VICTIM))
    assert plan_id is not None
    plan = service.get_plan(plan_id)
    ids = [str(t.task_id) for t in plan.tasks]
    assert len(ids) == len(set(ids)), f"task_id 撞号：{ids}"
    seqs = [int(str(i)[1:]) for i in ids if str(i).startswith("e")]
    assert max(seqs) >= 5  # 只进不退：新增号严格越过历史最大号


def test_legacy_board_with_gapped_ids_still_appends(config: _Config) -> None:
    """存量板（历史上被旧取号式写出的缺号形态）自愈：新取号吃最大值不吃条数。"""
    owner = sb._board_owner_from_roster_id(VICTIM)
    store = sb.build_board_store(config)
    service = sb.build_board_service(config)
    _add_entry(
        service, store, owner,
        ScheduleAddIntent(
            start_local=datetime.now(ZONE) + timedelta(days=1),
            activity="旧甲", duration_minutes=60, public=False,
            weekly_weekday=None, parity=None, semester_start=None,
        ),
    )
    _add_entry(  # 人为构造撞号现场：直接塞一条 e009（等价旧板里的大序号遗留）
        service, store, owner,
        ScheduleAddIntent(
            start_local=datetime.now(ZONE) + timedelta(days=2),
            activity="旧乙", duration_minutes=60, public=False,
            weekly_weekday=None, parity=None, semester_start=None,
        ),
    )
    plan_id = store.plan_id_for_owner(owner)
    plan = service.get_plan(plan_id)
    payload = plan.model_dump()
    payload["tasks"][1]["task_id"] = "e009"
    payload["rules"][1]["task_id"] = "e009"
    payload["rules"][1]["rule_id"] = "r_e009"
    sb._resubmit(service, payload, expected_revision=plan.revision)
    # 现在 len(tasks)=2 → 旧式取号 e003（可用）；即便再删出 len=1 的窗口，
    # 新取号也只会从 max(9)+1=e010 起——绝不回头撞 e009。
    line = _add_entry(
        service, store, owner,
        ScheduleAddIntent(
            start_local=datetime.now(ZONE) + timedelta(days=3),
            activity="新丙", duration_minutes=60, public=False,
            weekly_weekday=None, parity=None, semester_start=None,
        ),
    )
    assert "新丙" in line
    fresh = service.get_plan(plan_id)
    assert all(t.task_id != "e009" or str(t.title) == "旧乙" for t in fresh.tasks)
