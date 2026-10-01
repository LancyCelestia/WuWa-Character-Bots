"""S-FIX-SCHED20B（2026-09-27）：G4 残余①「引用拼接文本污染日程捕获」的锁。

攻击面（SEAT-ATK-B20b §B20-G4 残余①）：捕获/添加腿在 ``command_text`` 为空时
回退 ``plain_text``，而 ``plain_text`` 可能含摄取层拼接进来的**他人话语**
（``[引用回复 层级N 名] … [/引用回复 层级N]`` / ``[引用内容]`` / ``[转发/聊天记录]``
等块，标记唯一真身 = ``message_context.INTERNAL_MARKER_PATTERN``，
渲染真身 = ``format_reply_chain``，本文件按真实产形取样、不自造标记）。
修法口径：捕获腿与添加腿只吃 ``capture_clean_text``——
本人原文优先；无 command_text 的回退面上，标记在场即整条拒捕（宁漏不脏）。

注毒反向锁（任务 A.3）：把 ``schedule_board`` 的捕获/添加腿改回
「空 command_text 回退 plain_text 且无标记检查」的旧写法，本件的
test_pure_quoted_reply_* 两例必红（旧写法会对引用体返回 added/need_time 结果，
断言 `result is None` 当场 FAILED）——该还原性已在席位日志以实跑证明。

任务 B（G2(a) 未来窗代答）同件落锁：``_window_days`` 窗判据（定基准日现算）、
``window_entries`` 取数（固定 now 注入）、能力端到端（分级隐私不放宽：
非本人档"空窗"与"全隐私窗"逐字同句；owner 档才给诚实"没安排"；
现在腿行为零回归——不带 window 审计戳）。

全离线 tmp_path；不碰网络、不碰真库。与既有测试件不耦合（fixture 自带一份）。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.schedule.capabilities import (
    schedule_board as sb,
)
from plugins.bot_unified_runtime.domains.schedule.capabilities.schedule_board import (
    capture_clean_text,
)

OWNER = "u_her"

# 摄取层真实产形（format_reply_chain 单层渲染 + 转发展开头，逐字对齐 message_context）：
QUOTED_CLASS = "[引用回复 层级1 霞月] 明天8点有课 [/引用回复 层级1]"
QUOTED_ADD_FORM = "[引用回复 层级1 霞月] 日程 明天8点有课 [/引用回复 层级1]"
QUOTED_CONTENT = "[引用内容] 明天8点有课 [/引用内容]"
FORWARDED_BLOCK = "[转发/聊天记录] 小月的群聊\n明天8点有课"


class _Config:
    """三枚日程闸全开的配置桩（本波只测捕获面；闸关态由既有件执法，不重复）。"""

    def __init__(self, tmp_path: Path, **overrides: object) -> None:
        self.bot_schedule_enabled = True
        self.bot_schedule_db_path = str(tmp_path / "schedule_test.sqlite3")
        self.bot_schedule_status_reply_enabled = True
        self.bot_schedule_natural_capture_enabled = True
        self.bot_timezone = "Asia/Shanghai"
        self.bot_super_admin_user_ids = [OWNER]
        self.bot_admin_profiles = [{"user_id": OWNER, "name": "澜汐"}]
        for key, value in overrides.items():
            setattr(self, key, value)


def _message(
    plain_text: str,
    *,
    command_text: str = "",
    sender: str = OWNER,
    request_id: str = "req-sched20b",
    roles: list[str] | None = None,
    session_type: SessionType = SessionType.PRIVATE,
) -> IncomingMessage:
    return IncomingMessage(
        request_id=request_id,
        platform="onebot11",
        adapter="onebot11",
        bot_id="bot1",
        session_id=f"{'private' if session_type is SessionType.PRIVATE else 'group'}_{sender}",
        session_type=session_type,
        sender_id=sender,
        plain_text=plain_text,
        command_text=command_text,
        sender_roles=list(roles) if roles is not None else ["super_admin"],
        message_id=f"m-{request_id}",
        raw_segments=[],
    )


def _board_titles(config: _Config, owner: str) -> list[str]:
    store = sb.build_board_store(config)
    service = sb.build_board_service(config)
    # S-FIX-ATK-SCHED2 票1 跟改：能力腿建板吃平台域限定人物键，直读面按
    # 同一折算口取键（裸号=QQ 原生域），与播种腿同源。
    owner_key = sb._board_owner_from_roster_id(owner)
    return [item.title for item in sb.list_board_items(service, store, owner_key)]


# ---------------------------------------------------------------------------
# capture_clean_text：口径本体（正/负样本各钉死）
# ---------------------------------------------------------------------------


def test_command_text_wins_even_when_plain_spliced() -> None:
    """本人原文非空 ⇒ 只吃 command_text，引用块整体不入视野。"""
    message = _message(
        "明天下午有面试\n" + QUOTED_CLASS,
        command_text="明天下午有面试",
    )
    assert capture_clean_text(message) == "明天下午有面试"


@pytest.mark.parametrize(
    "spliced",
    [QUOTED_CLASS, QUOTED_ADD_FORM, QUOTED_CONTENT, FORWARDED_BLOCK],
)
def test_marker_present_without_command_rejects_capture(spliced: str) -> None:
    """command_text 为空 + plain_text 含引用/转发标记 ⇒ 拒捕（返回 None）。

    覆盖真实标记族：带层级与发送者名的引用块、闭合标记、引用内容、转发展开头。
    """
    assert capture_clean_text(_message(spliced)) is None


def test_legacy_plain_text_without_markers_still_falls_back() -> None:
    """契约缺省形态（从未填 command_text 的摄取路径）无标记 ⇒ 回退照捕，零回归。"""
    assert capture_clean_text(_message("明天8点有课")) == "明天8点有课"


def test_both_empty_is_no_capture_text() -> None:
    assert capture_clean_text(_message("")) == ""


# ---------------------------------------------------------------------------
# 端到端：能力面对引用体的行为（旧写法必红处＝注毒反向锁落点）
# ---------------------------------------------------------------------------


def test_pure_quoted_reply_not_captured(config_tmp: tuple[_Config, Path]) -> None:
    """纯引用回复（无自己正文）里「明天8点有课」绝不脏上板。

    旧写法（空 command_text 回退 plain_text、无标记检查）会命中自然捕捉腿并
    落一条标题含标记残渣的条目 ⇒ 本例断言 None + 板空，注毒还原必 FAILED。
    """
    config, _ = config_tmp
    capability = sb.build_schedule_board_capability(config)
    result = capability(_message(QUOTED_CLASS), None)
    assert result is None, f"引用体被捕获了：{result!r}"
    assert _board_titles(config, OWNER) == []


def test_pure_quoted_reply_add_form_not_added(config_tmp: tuple[_Config, Path]) -> None:
    """引用体里的「日程 明天8点有课」同样不加——别人的命令不是她的命令。

    样本刻意含活动词「有课」（旧写法下自然捕捉判据可命中引用体），
    使本例对注毒同样具判别力（与 not_captured 例同型杀法）。
    """
    config, _ = config_tmp
    capability = sb.build_schedule_board_capability(config)
    result = capability(_message(QUOTED_ADD_FORM), None)
    assert result is None, f"引用体被当成添加命令：{result!r}"
    assert _board_titles(config, OWNER) == []


def test_own_text_with_quoted_noise_records_only_own(config_tmp: tuple[_Config, Path]) -> None:
    """她自己打了字又带引用：只记她那句，引用内容一条不进、也不混进标题。"""
    config, _ = config_tmp
    capability = sb.build_schedule_board_capability(config)
    message = _message(
        "明天8点有课\n" + QUOTED_CONTENT,
        command_text="明天8点有课",
    )
    result = capability(message, None)
    assert result is not None, "本人原文的自然捕捉被误杀"
    assert "记上了" in result.body
    titles = _board_titles(config, OWNER)
    assert len(titles) == 1
    assert "引用" not in titles[0] and "霞月" not in titles[0]


def test_legacy_capture_path_unchanged(config_tmp: tuple[_Config, Path]) -> None:
    """无标记回退面：既有自然捕捉行为逐字保持（对照 test_schedule_board G 组口径）。"""
    config, _ = config_tmp
    capability = sb.build_schedule_board_capability(config)
    result = capability(_message("明天8点有课"), None)
    assert result is not None and "记上了" in result.body
    # 「课」＝既有解析口径（标题剥「有」动词头），非本波改动；对照件只锁「回退面照捕一条」。
    assert _board_titles(config, OWNER) == ["课"]


@pytest.fixture()
def config_tmp(tmp_path: Path) -> tuple[_Config, Path]:
    config = _Config(tmp_path)
    return config, tmp_path


# ---------------------------------------------------------------------------
# 任务 B（G2(a) 未来窗代答）：_window_days 窗判据（定基准日现算，不依赖真实时钟）
# ---------------------------------------------------------------------------

_WED = date(2026, 10, 7)  # 周三
_SUN = date(2026, 10, 11)  # 同一周的周日


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("她明天有空吗", (_WED + timedelta(days=1),) * 2 + ("明天",)),
        ("我后天有空吗", (_WED + timedelta(days=2),) * 2 + ("后天",)),
        ("她本周有空吗", (_WED, _SUN, "本周")),
        ("下周三她有空吗", (date(2026, 10, 14), date(2026, 10, 14), "下周三")),
        ("她周五有空吗", (date(2026, 10, 9), date(2026, 10, 9), "周五")),
        ("她周二有空吗", (date(2026, 10, 13), date(2026, 10, 13), "周二")),
        ("主人10月20日有空吗", (date(2026, 10, 20), date(2026, 10, 20), "10月20日")),
        # 已过日滚明年（宁漏不误但不误滚过去）：
        ("她1月5日有空吗", (date(2027, 1, 5), date(2027, 1, 5), "1月5日")),
        # 无窗的"什么时候忙/几点有事"形 = 默认明天起 7 天：
        ("她什么时候忙", (_WED + timedelta(days=1),
                          _WED + timedelta(days=7), "未来一周")),
        ("她几点有事", (_WED + timedelta(days=1),
                        _WED + timedelta(days=7), "未来一周")),
    ],
)
def test_window_days_resolves_named_windows(text: str, expected: tuple) -> None:
    got = sb._window_days(text, _WED)
    assert got == expected


@pytest.mark.parametrize(
    ("text", "today"),
    [
        ("她在干嘛", _WED),          # 现在腿问句：不产窗
        ("她有空吗", _WED),          # 无窗"有空吗"= 现在有没有空（现在腿）
        ("她周三有空吗", _WED),      # 今天恰是周三：半天已过，让位现在腿
        ("她本周有空吗", _SUN),      # 周日问本周：只剩今天
        ("她本周末有空吗", _SUN),    # 周日问本周末：已过
        ("她2月30日有空吗", _WED),   # 不存在的日子：不猜
        ("她大后天有空吗", _WED),    # 未点名形态：宁漏不误
    ],
)
def test_window_days_declines_ambiguous_or_past(text: str, today: date) -> None:
    assert sb._window_days(text, today) is None


def test_window_days_bare_weekend_from_wednesday() -> None:
    # 裸「周末」= 本周六..周日（周一为一周之始）。
    assert sb._window_days("她周末有空吗", _WED) == (date(2026, 10, 10), _SUN, "周末")
    # 「下周末」独立于本周。
    assert sb._window_days("她下周末有空吗", _WED) == (date(2026, 10, 17), date(2026, 10, 18), "周末")


# ---------------------------------------------------------------------------
# 任务 B：能力端到端（分级隐私不放宽——空窗/全隐私对外同句；owner 档才给"没安排"）
# ---------------------------------------------------------------------------


def _ask_public_tomorrow(config: _Config) -> None:
    """用她自己的显式命令记一条**公开**的明日条目（写面走 Task A 已锁的干净口径）。"""
    capability = sb.build_schedule_board_capability(config)
    result = capability(_message("日程 明天8点到9点半 高数 公开"), None)
    assert result is not None and "记上了" in result.body


def test_named_tier_answers_future_window_with_public_entry(config_tmp) -> None:
    config, _ = config_tmp
    _ask_public_tomorrow(config)
    capability = sb.build_schedule_board_capability(config)
    result = capability(_message("她明天有空吗", sender="u_friend"), None)
    assert result is not None
    assert "window" in result.audit_tags and "answered" in result.audit_tags
    assert "明天" in result.body and "高数" in result.body


def test_named_tier_default_seven_day_window(config_tmp) -> None:
    config, _ = config_tmp
    _ask_public_tomorrow(config)
    capability = sb.build_schedule_board_capability(config)
    result = capability(_message("她什么时候忙", sender="u_friend"), None)
    assert result is not None and "window" in result.audit_tags
    assert "未来一周" in result.body and "高数" in result.body


def test_basic_tier_cannot_distinguish_private_from_empty(config_tmp) -> None:
    """明日只有隐私条目：基本档问「她明天有空吗」与空板**同句**（模糊句）。"""
    config, _ = config_tmp
    capability = sb.build_schedule_board_capability(config)
    assert capability(_message("日程 明天15点到16点 体检"), None) is not None  # 默认隐私
    private_ask = capability(
        _message("她明天有空吗", sender="u_other", roles=["user"], request_id="req-ask"), None
    )
    empty_ask = capability(
        _message("她明天有空吗", sender="u_other2", roles=["user"], request_id="req-ask"), None
    )
    assert private_ask is not None and empty_ask is not None
    assert "answer_fallback" in private_ask.audit_tags
    # 同问句同种（seed 同）：全隐私窗与空板拿到逐字相同模糊句（§5.2 铁律）。
    assert private_ask.body == empty_ask.body
    assert "体检" not in private_ask.body and "明天" not in private_ask.body


def test_owner_first_person_gets_honest_free_answer(config_tmp) -> None:
    """她私聊亲口问自己：明日本板为空 ⇒ 诚实的「没安排」（owner 档特权，不外泄）。"""
    config, _ = config_tmp
    capability = sb.build_schedule_board_capability(config)
    result = capability(_message("我明天有空吗"), None)
    assert result is not None and "answered" in result.audit_tags
    assert "window" in result.audit_tags
    assert "明天" in result.body and "没安排" in result.body


def test_owner_first_person_window_lists_private_entry(config_tmp) -> None:
    config, _ = config_tmp
    capability = sb.build_schedule_board_capability(config)
    assert capability(_message("日程 明天15点到16点 体检"), None) is not None
    result = capability(_message("我明天有安排吗"), None)
    assert result is not None and "window" in result.audit_tags
    assert "明天" in result.body and "体检" in result.body and "隐私" in result.body


def test_current_leg_wording_unchanged_by_window_leg(config_tmp) -> None:
    """现在腿零回归：「她在干嘛」不带 window 戳，行为与窗腿在场前一致。"""
    config, _ = config_tmp
    capability = sb.build_schedule_board_capability(config)
    result = capability(_message("她在干嘛", sender="u_friend"), None)
    assert result is not None
    assert "window" not in result.audit_tags
    assert "answer_fallback" in result.audit_tags  # 空板 → 模糊句（既有铁律）


# ---------------------------------------------------------------------------
# 任务 B：window_entries 取数（固定 now 注入，跨周循环规则确定性入窗）
# ---------------------------------------------------------------------------


def test_window_entries_weekly_rule_hits_next_wednesday(config_tmp) -> None:
    config, _ = config_tmp
    capability = sb.build_schedule_board_capability(config)
    assert capability(_message("日程 每周三8点到9点40 现代史纲要 公开"), None) is not None
    store = sb.build_board_store(config)
    service = sb.build_board_service(config)
    now = datetime(2026, 10, 7, 3, 0, tzinfo=UTC)  # 计划时区（Asia/Shanghai）当日=10-07 周三
    # 票1 跟改：能力腿播种的板在平台域限定键下，直读按同一折算口取键。
    owner_key = sb._board_owner_from_roster_id(OWNER)
    got = sb.window_entries(service, store, owner_key, "她下周三有空吗", now=now)
    assert got is not None
    label, items = got
    assert label == "下周三"
    assert len(items) == 1 and items[0].title == "现代史纲要"
    assert items[0].start_local.date() == date(2026, 10, 14)
    assert items[0].public is True
    # 非窗问句 ⇒ None（调用方回退现在腿）。
    assert sb.window_entries(service, store, owner_key, "她在干嘛", now=now) is None
    # 无板 owner：解得出窗但无数——label 仍给出（投影层按档处置）。
    empty = sb.window_entries(service, store, "u_no_board", "她明天有空吗", now=now)
    assert empty is not None and empty[0] == "明天" and empty[1] == []
