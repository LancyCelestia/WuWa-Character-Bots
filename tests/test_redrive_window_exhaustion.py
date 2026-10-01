"""补回「超窗即弃」的收口 + 两处残余判据的回归锁（2026-09-28 S-ACK 波）。

分工（别和邻件重复）：
- `tests/test_throttle_redrive_and_adaptive_ack.py` 锁「该不该补」的三道门与回执自适应阈值；
- `tests/test_policy_queue_not_drop.py` 锁「连发在假钟上到底补不补得回来」（活性面）；
- **本件**锁三件新落的判据本身：
  ① 超窗改「钳制到最近可用槽」而不是「弃」（她需求 2 的残留：连发 6 条只回 5 条）；
  ② 补回参数以 `rate_limit` 模块常量为**唯一数值真身**，窗口按点名间隔派生不写字面量，
     并把 `config.py` 的两枚字段缺省锁成与代码真身同源（09-28 曾挂 strict xfail，
     09-29 config 抬到 270/3 后转正为双向同源锁）；
  ③ `_is_directed_request` 的群自动回复腿（`proactive_selected`）——缺省 False 保现状、
     显式 True 才纳入补回，因为标签在 `pipeline.py`（本席禁写面），线未接之前
     不许靠猜把主动接话算成欠回复（那会写坏「没 @ 的群闲聊不补回」这条既有裁定）。
  ④ 另收 DEFECT-2 的**接收腿**：回执群侧名单只吃 QQ 协议域。

复跑：
    PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe \
      -m pytest tests/test_redrive_window_exhaustion.py -q -p no:cacheprovider \
      --basetemp=<仓库外私有目录>
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.chat_reply.policy import rate_limit
from plugins.bot_unified_runtime.domains.chat_reply.policy import roles as roles_module
from plugins.bot_unified_runtime.domains.chat_reply.policy.rate_limit import (
    DEFAULT_REDRIVE_MAX_ATTEMPTS,
    DEFAULT_REDRIVE_MAX_WAIT_SECONDS,
    RateLimitDecision,
    RateLimitSettings,
    RedriveSettings,
    _is_directed_request,
    redrive_wait_seconds,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime import progress_ack as PA
from plugins.bot_unified_runtime.domains.chat_reply.runtime.progress_ack import (
    ProgressAckSettings,
    progress_ack_allowed,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CONFIG_PY = _REPO_ROOT / "plugins" / "bot_unified_runtime" / "config.py"

_SENDER = "u1"
# 间隔缺省从真身反射取，不抄第二份 45（本件断言的正是"窗口跟着间隔派生"这条判据）。
_INTERVAL = int(RateLimitSettings.model_fields["chat_sender_min_interval_seconds"].default)


def _message(
    *,
    mentions_bot: bool = True,
    session_type: SessionType = SessionType.GROUP,
    redrive_count: int = 0,
) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot_v11",
        bot_id="3958874605",
        session_id=(
            f"group_10_{_SENDER}" if session_type is SessionType.GROUP else f"private_{_SENDER}"
        ),
        session_type=session_type,
        sender_id=_SENDER,
        group_id="10" if session_type is SessionType.GROUP else None,
        plain_text="守岸人 在吗",
        mentions_bot=mentions_bot,
        redrive_count=redrive_count,
    )


def _denied(reason: str, retry_after: int) -> RateLimitDecision:
    return RateLimitDecision(
        allowed=False, reason=reason, retry_after_seconds=retry_after
    )


# ---------------------------------------------------------------------------
# ① 超窗：钳制到最近可用槽，不再"弃"
# ---------------------------------------------------------------------------


def test_over_window_wait_is_clamped_to_the_cap_instead_of_dropped() -> None:
    """旧写法在 `wait > max_wait` 那格 return None＝当场判弃。

    小时级帽那条**老判据仍然在场**：钳制后的上界就是窗口本身（90 秒），
    绝不出现"隔一小时突然冒一句"；变的是"到点再看一眼"取代"直接不回"，
    于是被排队算术推出窗口的连发消息有了被补回来的路。
    """
    settings = RedriveSettings(max_wait_seconds=90.0)
    wait = redrive_wait_seconds(
        settings, _message(), "bot.chat", _denied("sender_window_exceeded", 3_600)
    )
    assert wait == 90.0, f"超窗必须钳制到窗口上界，实测 {wait!r}"


def test_clamped_redrive_is_still_bounded_by_the_attempt_budget() -> None:
    """钳制不许长出重放循环：额度用尽照样收口为「不补」（有界性原样在场）。"""
    settings = RedriveSettings(max_wait_seconds=90.0, max_attempts=2)
    spent = _message(redrive_count=2)
    assert (
        redrive_wait_seconds(settings, spent, "bot.chat", _denied("sender_window_exceeded", 30))
        is None
    )


def test_disabled_switch_still_never_schedules_a_redrive() -> None:
    settings = RedriveSettings(enabled=False)
    assert (
        redrive_wait_seconds(settings, _message(), "bot.chat", _denied("sender_window_exceeded", 5))
        is None
    )


def test_zero_wait_still_means_nothing_to_redrive() -> None:
    """解禁点已过（报 0 秒）＝这一条根本不该被补：钳制只处理"还要等很久"那一侧。"""
    assert (
        redrive_wait_seconds(RedriveSettings(), _message(), "bot.chat", _denied("sender_window_exceeded", 0))
        is None
    )


# ---------------------------------------------------------------------------
# ② 参数真身：一处字面量都没有，窗口由点名间隔派生
# ---------------------------------------------------------------------------


def test_window_default_is_derived_from_the_sender_interval_not_a_literal() -> None:
    """窗口＝6×间隔：连发 6 条整轮排得下（第 6 条回位 5×间隔 ＋ 一格余量）。

    反射派生（同 `test_tts_probability_lock.py` 的"指门不指数"口径）：谁抬 R3 间隔，
    窗口跟着走；把 270/45 抄进本件会让"抬间隔"这一改动静默写爆补回的账。
    """
    assert DEFAULT_REDRIVE_MAX_WAIT_SECONDS == float(6 * _INTERVAL)
    defaults = RedriveSettings()
    assert defaults.max_wait_seconds == DEFAULT_REDRIVE_MAX_WAIT_SECONDS
    assert defaults.max_attempts == DEFAULT_REDRIVE_MAX_ATTEMPTS
    assert DEFAULT_REDRIVE_MAX_ATTEMPTS == 3, "额度面变了要连同 pipeline 的计数面一起看"


def test_sixth_burst_slot_fits_inside_the_window() -> None:
    """把"第 6 条排不进窗口"这件事本身钉住：账本给第 6 条的回位是 5×间隔。"""
    sixth_slot = 5 * _INTERVAL
    assert sixth_slot <= DEFAULT_REDRIVE_MAX_WAIT_SECONDS
    # 旧窗口（4×间隔）下同一格确实排不进——本用例的对照对象，别让它悄悄失效。
    assert sixth_slot > float(4 * _INTERVAL)


def test_config_default_matches_the_code_truth() -> None:
    """同源锁（挂账已销）：`config.py` 的两枚缺省必须等于代码真身。

    历史形态（2026-09-28 S-ACK 波）：那一席不能碰 `config.py`，于是把「config 仍是
    旧值 180.0/1」挂成 strict xfail——宁可红一次，也不许两份口径长期并存没人知道。
    2026-09-29 config.py 抬到 270.0/3 后 xfail 标记摘除，本发转正为**双向同源锁**：
    谁改了 `rate_limit.DEFAULT_REDRIVE_*` 或 `config.py` 字段缺省而没同步另一侧，
    这里当场红（生产生效值走的是 `build_redrive_settings` 从 Config 搬来的那一条，
    所以 config 侧才是线上真身；代码真身只在 Config 缺席时兜底）。
    """
    tree = ast.parse(_CONFIG_PY.read_text(encoding="utf-8"))
    declared: dict[str, object] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        name = node.target.id
        if name in {
            "bot_chat_rate_limit_redrive_max_wait_seconds",
            "bot_chat_rate_limit_redrive_max_attempts",
        }:
            declared[name] = ast.literal_eval(node.value)
    assert declared == {
        "bot_chat_rate_limit_redrive_max_wait_seconds": DEFAULT_REDRIVE_MAX_WAIT_SECONDS,
        "bot_chat_rate_limit_redrive_max_attempts": DEFAULT_REDRIVE_MAX_ATTEMPTS,
    }, f"config 缺省={declared} 与代码真身=" \
        f"{(DEFAULT_REDRIVE_MAX_WAIT_SECONDS, DEFAULT_REDRIVE_MAX_ATTEMPTS)} 不同源"


# ---------------------------------------------------------------------------
# ③ 群自动回复腿：显式传标签才算欠回复（线未接之前保持现状）
# ---------------------------------------------------------------------------


def test_unmentioned_group_chatter_stays_not_redriven_by_default() -> None:
    """缺省 False＝现状逐字节不变，「没 @ 的群闲聊不补回」这条既有裁定仍在场。"""
    message = _message(mentions_bot=False)
    assert _is_directed_request(message, "bot.chat") is False
    assert (
        redrive_wait_seconds(
            RedriveSettings(), message, "bot.chat", _denied("sender_window_exceeded", 20)
        )
        is None
    )


def test_group_auto_reply_leg_is_redriven_when_the_caller_marks_it() -> None:
    """门禁这轮已经抽中要接话（群自动回复腿）⇒ 被"太密"吞掉就是白抽签，该补。

    判据与 `pipeline.py:812-817` 的 `interactive_request` 同形；标签由调用方传入
    （H-2 补丁：把已经算出来的 `proactive_request` 递进来）。本发同时锁住
    「主动接话那两道拒因仍然永不补回」——见邻件的 proactive 用例，这里不重复。
    """
    message = _message(mentions_bot=False)
    assert _is_directed_request(message, "bot.chat", proactive_selected=True) is True
    wait = redrive_wait_seconds(
        RedriveSettings(),
        message,
        "bot.chat",
        _denied("sender_window_exceeded", 20),
        proactive_selected=True,
    )
    assert wait == 20.0


def test_proactive_selected_never_opens_the_non_chat_or_private_doors_wider() -> None:
    """标签只影响"群里没 @ 的那一支"：其余判定路径不许被它带偏。"""
    assert _is_directed_request(_message(mentions_bot=False), "bot.music") is True
    assert (
        _is_directed_request(
            _message(mentions_bot=False, session_type=SessionType.PRIVATE), "bot.chat"
        )
        is True
    )
    assert _is_directed_request(_message(), "bot.chat") is True


# ---------------------------------------------------------------------------
# ④ DEFECT-2 接收腿：回执群侧名单只吃 QQ 协议域
# ---------------------------------------------------------------------------


def _gate() -> ProgressAckSettings:
    return ProgressAckSettings(
        enabled=True,
        group_whitelist=frozenset({"662948429"}),
    )


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("qq", True),  # 本命平台：照发
        ("onebot", True),  # QQ 协议域的其他写法（roles 的唯一表说了算）
        ("nonebot", True),
        ("", True),  # 线未接：调用方没给平台 ⇒ 逐字节现状，不许整面关死
        ("telegram", False),  # ★ DEFECT-2：同号 TG 频道不再被 QQ 群白名单带走
        ("tg", False),
    ],
)
def test_group_side_gate_only_accepts_the_qq_platform_domain(
    platform: str, expected: bool
) -> None:
    assert (
        progress_ack_allowed(
            _gate(), session_type="group", group_id="662948429", platform=platform
        )
        is expected
    )


def test_platform_leg_does_not_loosen_any_other_door() -> None:
    """补腿只准收紧不准放宽：黑名单、没进白名单、总闸关，三格在 QQ 平台上照样 False。"""
    gate = _gate()
    assert (
        progress_ack_allowed(
            _gate(), session_type="group", group_id="999999999", platform="qq"
        )
        is False
    )
    assert (
        progress_ack_allowed(
            ProgressAckSettings(
                enabled=True,
                group_whitelist=frozenset({"662948429"}),
                group_blacklist=frozenset({"662948429"}),
            ),
            session_type="group",
            group_id="662948429",
            platform="qq",
        )
        is False
    )
    assert (
        progress_ack_allowed(
            ProgressAckSettings(enabled=False, group_whitelist=frozenset({"662948429"})),
            session_type="group",
            group_id="662948429",
            platform="qq",
        )
        is False
    )
    assert gate.enabled is True


def test_alias_table_has_no_second_copy_in_the_ack_face() -> None:
    """反第二真身：回执面不得自己抄一张平台别名表（唯一声明位在 `policy/roles.py`）。"""
    ack_source = Path(PA.__file__).read_text(encoding="utf-8")
    for needle in ('"onebot_v11"', '"onebot-v11"', '"telegram"', '"tg"'):
        assert needle not in ack_source, f"别名表被抄进 progress_ack.py：{needle}"
    assert "platform_domain_of" in ack_source, "回执面没共读 roles 的平台归一真身"
    # 限流侧也不许长出一份读平台的判据（本波只有回执面缺这条腿）。
    assert "platform_domain_of" not in Path(rate_limit.__file__).read_text(encoding="utf-8")
    assert hasattr(roles_module, "platform_domain_of"), "别名表真身被搬走：本判据要跟着改"
