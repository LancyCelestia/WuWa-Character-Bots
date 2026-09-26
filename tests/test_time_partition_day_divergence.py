"""需求 10「bot 说的今天到底是哪天」——跨日提示的接线与不撒谎锁。

覆盖 ``character/temporal._day_divergence_note`` 经 ``time_partition_extras``
进【当前时间】分区这条链。四把钟（UTC / 配置时区 / 东八区日界 / 系统本地）
在真身 ``domains/ops/self_calendar/moments`` 里判定，本件只验**装配**：

1. 跨日时这一行出现、且把不同的日期逐一点名；
2. 四把钟同日时**整行不出**（不制造噪音，也不写「今天都一样」这种废话行）；
3. 系统钟与所报时刻不同次取数时**不参与比较**——否则补投一条历史消息就会
   拿今天的系统钟去断言那天的日子，当场是假话；
4. 措辞零副本：本件断言分区里那行**等于**真身算出的原句，不和自己手抄的
   字符串比对（手抄副本就是这个项目反复踩的「第二真身」）。

全程离线：时刻由 ``monkeypatch`` 钉住，不读真实系统钟，不联网。
"""

from __future__ import annotations

import ast
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character import temporal as tmod
from plugins.bot_unified_runtime.domains.ops.self_calendar import moments as mmod

_CHARACTER_TEMPORAL = (
    Path(__file__).resolve().parents[1]
    / "plugins/bot_unified_runtime/domains/chat_reply/character/temporal.py"
)

TOKYO = "Asia/Tokyo"
# 东京 09-26 08:30 == UTC 09-25 23:30 == 东八区 09-26 07:30 ⇒ UTC 与另两把钟差一天。
_DIVERGENT_MOMENT = datetime(2026, 9, 26, 8, 30, tzinfo=timezone(timedelta(hours=9)))
# 东京 09-26 11:00 == UTC 09-26 02:00 == 东八区 09-26 10:00 ⇒ 四把钟同日。
_SAME_DAY_MOMENT = datetime(2026, 9, 26, 11, 0, tzinfo=timezone(timedelta(hours=9)))


def _context(moment: datetime, *, timezone_name: str = TOKYO) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        date_local=moment.strftime("%Y-%m-%d"),
        now_local=moment.strftime("%H:%M"),
        weekday="星期六",
        timezone=timezone_name,
    )


_REAL_CLOCK = mmod.system_clock_now


def _note_for(moment: datetime, *, clock_skew: timedelta = timedelta(0)) -> str:
    """把系统钟钉在「所报时刻 + skew」上，返回分区里那一行（没有则空串）。"""
    mmod.system_clock_now = lambda: moment + clock_skew  # type: ignore[assignment]
    try:
        lines = tmod.time_partition_extras(_context(moment))
    finally:
        mmod.system_clock_now = _REAL_CLOCK  # type: ignore[assignment]
    return next((line for line in lines if line.startswith("注意：")), "")


# ==================== ① 跨日要点名 ====================


def test_divergent_clocks_emit_a_note_naming_each_day() -> None:
    note = _note_for(_DIVERGENT_MOMENT)
    assert note, f"四把钟跨日却没出提示行：{note!r}"
    # 两个不同的日期都要被点名，不能只说「有差异」。
    assert "2026-09-25" in note and "2026-09-26" in note, note
    assert "UTC" in note and "东八区" in note, note


def test_note_text_is_the_source_sentence_verbatim_no_second_copy() -> None:
    """分区里那行 == 真身 ``day_divergence_note``：措辞零副本。

    手抄一份提示语就是这个项目反复长出第二真身的方式，所以这一发不比对
    任何本文件里写的字符串常量，只比对真身的返回值。
    """
    mmod.system_clock_now = lambda: _DIVERGENT_MOMENT  # type: ignore[assignment]
    try:
        rendered = _note_for(_DIVERGENT_MOMENT)
        truth = mmod.resolve_moments(
            _DIVERGENT_MOMENT, timezone_name=TOKYO, system_now=_DIVERGENT_MOMENT
        ).day_divergence_note
    finally:
        mmod.system_clock_now = _REAL_CLOCK  # type: ignore[assignment]
    assert truth
    assert rendered == truth


# ==================== ② 同日不制造噪音 ====================


def test_same_day_clocks_emit_no_note_and_keep_calendar_lines() -> None:
    mmod.system_clock_now = lambda: _SAME_DAY_MOMENT  # type: ignore[assignment]
    try:
        lines = tmod.time_partition_extras(_context(_SAME_DAY_MOMENT))
    finally:
        mmod.system_clock_now = _REAL_CLOCK  # type: ignore[assignment]
    assert not [line for line in lines if line.startswith("注意：")], lines
    # 少一行提示 ≠ 少整块历法面。
    assert any(line.startswith("农历：") for line in lines), lines


# ==================== ③ 不同次取数不参与比较 ====================


def test_stale_system_clock_is_excluded_from_the_comparison() -> None:
    """系统钟比所报时刻晚了三天 ⇒ 这是历史上下文，不许拿它断言那天。

    反证：若少了这道闸，晚三天的系统钟会让提示行多写出一个莫须有的
    「系统本地 2026-09-29」——补投/回放场景里这就是一句假话。
    """
    note = _note_for(_DIVERGENT_MOMENT, clock_skew=timedelta(days=3))
    assert "系统本地" not in note, note
    assert note, "UTC 与配置时区本来就跨日，提示行不该整行消失"


def test_fresh_system_clock_is_included() -> None:
    note = _note_for(_DIVERGENT_MOMENT, clock_skew=timedelta(seconds=45))
    assert "系统本地" in note, note


def test_skew_ceiling_is_six_hundred_seconds() -> None:
    """窗口边界两侧各打一发，钉住「余量是常数不是随手写的大数」。"""
    assert "系统本地" in _note_for(
        _DIVERGENT_MOMENT, clock_skew=timedelta(seconds=599)
    )
    assert "系统本地" not in _note_for(
        _DIVERGENT_MOMENT, clock_skew=timedelta(seconds=601)
    )


# ==================== ④ 拿不到时刻就整行不出，不带走别的 ====================


@pytest.mark.parametrize(
    "now_local",
    ["", "不是时刻", "25:99", "08"],
)
def test_unusable_wall_clock_drops_only_the_note(now_local: str) -> None:
    context = types.SimpleNamespace(
        date_local="2026-09-26", now_local=now_local, timezone=TOKYO
    )
    lines = tmod.time_partition_extras(context)
    assert not [line for line in lines if line.startswith("注意：")], lines
    assert any(line.startswith("农历：") for line in lines), lines


def test_empty_timezone_drops_only_the_note() -> None:
    context = types.SimpleNamespace(
        date_local="2026-09-26", now_local="08:30", timezone=""
    )
    lines = tmod.time_partition_extras(context)
    assert not [line for line in lines if line.startswith("注意：")], lines
    assert any(line.startswith("农历：") for line in lines), lines


def test_note_always_sits_after_the_calendar_lines() -> None:
    """顺序锁：首行时刻（调用方）→ 时区/授时 → 历法面 → 跨日提示。

    既有分区锁与模型引用都锚在前几行的行序上，提示只能追加在尾部。
    """
    lines = tmod.time_partition_extras(_context(_DIVERGENT_MOMENT))
    note_index = next(i for i, line in enumerate(lines) if line.startswith("注意："))
    calendar_index = min(i for i, line in enumerate(lines) if line.startswith("农历："))
    assert note_index > calendar_index, lines
    assert lines[0].startswith("时区 "), lines


# ==================== ⑤ 装配面只准有一条历法读出 ====================


def test_prompt_calendar_lines_have_exactly_one_producer() -> None:
    """【当前时间】的历法措辞只从 ``_compact_calendar_lines_cached`` 出。

    ``self_calendar`` 里另有一套 ``calendar_compact_lines``（按真身原句拼装、
    给命令面/明细用）。两套**换算**都委托 ``multi_calendar``，所以不算第二真身；
    但如果装配层把第二套也灌进分区，同一个「今天」就会在 prompt 里出现两种措辞。
    这里锁：temporal 件只从 moments 借「四把钟对照」，不借历法行。
    """
    tree = ast.parse(_CHARACTER_TEMPORAL.read_text(encoding="utf-8"))
    borrowed: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and "self_calendar" in node.module:
            borrowed += [alias.name for alias in node.names]
    assert set(borrowed) == {"resolve_moments", "system_clock_now"}, borrowed
    sources = _CHARACTER_TEMPORAL.read_text(encoding="utf-8")
    assert "calendar_compact_lines" not in sources, "历法行出现第二处装配点，prompt 会两套口径"
