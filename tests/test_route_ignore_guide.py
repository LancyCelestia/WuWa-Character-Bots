"""IGNORE 命令形态引导回归（审查 C-07，全离线）。

修前实证：RouteKind.IGNORE 兜底全项目无任何消费点（仅影子决策引擎记账），
「/help」「/帮助」「!help」等命令形态落 IGNORE 后完全静默。

锁定四件事（对齐任务验收 ①②③④）：
1. /help 形态 → 判定链给出引导回复素材（kind=IGNORE ∧ is_command_form_text
   ∧ 引导语可构建，capability_id=bot.ignore 审计可归因）；
2. 普通闲聊仍走 CHAT 零变化；空文本/纯媒体（空消息兜底）与 chat 关闭时的
   闲聊即使落 IGNORE 也不触发引导（静默语义红线）；
3. IgnoreGuideGate 节流：同会话 60s 窗口内第二条不再回，跨会话互不影响，
   窗口过后恢复；
4. 主模块接线契约（rule 函数与 __init__ 拟接线的同一表达式）端到端可复现，
   既有路由判定（/bot 管理面、点歌等命令 kind）不受影响。
"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.capabilities.echo import (
    _IGNORE_GUIDE_LINES,
    IgnoreGuideGate,
    build_ignore_command_guidance,
    build_ignore_guide_result,
)
from plugins.bot_unified_runtime.runtime.base_router import (
    RouteKind,
    classify_message_route,
    clear_route_decision_cache,
    is_command_form_text,
)


class _DefaultConfig:
    """全部路由开关走 base_router 的 getattr 默认值（默认启用语义）。"""


class _ChatDisabledConfig:
    bot_chat_enabled = False


@pytest.fixture(autouse=True)
def _clean_route_cache():
    clear_route_decision_cache()
    yield
    clear_route_decision_cache()


# ---------------------------------------------------------------------------
# ① /help 形态：IGNORE + 命令形态 + 引导语素材（修前完全静默的路径）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["/help", "/帮助", "!help", "！帮助", "/help 天气"])
def test_help_form_falls_to_ignore_and_is_command_form(text: str) -> None:
    decision = classify_message_route(text, config=_DefaultConfig(), alias_resolver=None)
    assert decision.kind is RouteKind.IGNORE
    assert decision.capability_id == "bot.ignore"
    assert is_command_form_text(text) is True


def test_guidance_result_contract() -> None:
    result = build_ignore_guide_result("req-c07")
    assert result.capability_id == "bot.ignore"
    assert result.kind == "text"
    assert result.body in _IGNORE_GUIDE_LINES
    assert "/bot help" in result.body
    assert "ignore_guide" in result.audit_tags and "c07" in result.audit_tags


def test_guidance_rotation_covers_all_lines_without_user_echo() -> None:
    seen = {build_ignore_command_guidance() for _ in range(len(_IGNORE_GUIDE_LINES) * 2)}
    assert seen == set(_IGNORE_GUIDE_LINES)
    # 静态文案：不回显用户输入（防注入/防怪回显）。
    for line in _IGNORE_GUIDE_LINES:
        assert "签到" not in line


# ---------------------------------------------------------------------------
# ② 普通闲聊/空消息红线：不受引导波及
# ---------------------------------------------------------------------------


def test_plain_chat_still_routes_to_chat_without_guide() -> None:
    decision = classify_message_route("今天天气不错", config=_DefaultConfig(), alias_resolver=None)
    assert decision.kind is RouteKind.CHAT
    assert is_command_form_text("今天天气不错") is False


def test_empty_text_ignore_stays_silent() -> None:
    # 空文本/纯媒体消息落「空消息」兜底：引导语不得触发（红线：不回复）。
    for text in ["", "   "]:
        decision = classify_message_route(text, config=_DefaultConfig(), alias_resolver=None)
        assert decision.kind is RouteKind.IGNORE
        assert is_command_form_text(text) is False


def test_chat_disabled_plain_text_ignore_stays_silent() -> None:
    # chat 关闭时闲聊文本也落 IGNORE，但其非命令形态：不引导（保持安静）。
    decision = classify_message_route("在吗", config=_ChatDisabledConfig(), alias_resolver=None)
    assert decision.kind is RouteKind.IGNORE
    assert is_command_form_text("在吗") is False


# ---------------------------------------------------------------------------
# ③ 节流：同会话窗口内不重复，跨会话独立，窗口过后恢复
# ---------------------------------------------------------------------------


def test_gate_throttles_same_session_within_window() -> None:
    clock = [1000.0]
    gate = IgnoreGuideGate(window_seconds=60.0, clock=lambda: clock[0])
    assert gate.check_and_mark("private:10001") is True
    assert gate.check_and_mark("private:10001") is False
    clock[0] += 59.0
    assert gate.check_and_mark("private:10001") is False
    clock[0] += 2.0  # 越过 60s 窗口
    assert gate.check_and_mark("private:10001") is True


def test_gate_is_per_session() -> None:
    clock = [0.0]
    gate = IgnoreGuideGate(window_seconds=60.0, clock=lambda: clock[0])
    assert gate.check_and_mark("private:10001") is True
    assert gate.check_and_mark("private:10002") is True
    assert gate.check_and_mark("group:88801_20002") is True
    assert gate.check_and_mark("private:10001") is False


def test_gate_reset_and_bounded_capacity() -> None:
    clock = [0.0]
    gate = IgnoreGuideGate(window_seconds=60.0, clock=lambda: clock[0], max_entries=2)
    assert gate.check_and_mark("a") is True
    assert gate.check_and_mark("b") is True
    assert gate.check_and_mark("c") is True  # 超限清空重建，不无界增长
    gate.reset()
    assert gate.check_and_mark("a") is True


# ---------------------------------------------------------------------------
# ④ 接线契约端到端：rule 判定式与主模块拟接线一致（既有 matcher 模式）
# ---------------------------------------------------------------------------


def _guide_rule_wiring(text: str, session_key: str, gate: IgnoreGuideGate) -> str | None:
    """与 __init__ 拟接线的 help_guide rule 同一判定式（契约镜像）。

    rule: kind=IGNORE ∧ is_command_form_text ∧ gate.check_and_mark
    （gate 放在 rule 侧：被群门禁/安静时间拦下的尝试也占窗口名额，
    只会更保守地少回，不产生额外刷屏。）
    """
    decision = classify_message_route(text, config=_DefaultConfig(), alias_resolver=None)
    if decision.kind is not RouteKind.IGNORE:
        return None
    if not is_command_form_text(text):
        return None
    if not gate.check_and_mark(session_key):
        return None
    return build_ignore_guide_result(f"req-{session_key}").body


def test_wiring_contract_help_form_replies_then_throttles() -> None:
    gate = IgnoreGuideGate(window_seconds=60.0, clock=lambda: 0.0)
    first = _guide_rule_wiring("/help", "private:10001", gate)
    assert first is not None and "/bot help" in first
    # 窗口内换一种未知命令形态（/帮助）：同一会话不再回。
    assert _guide_rule_wiring("/帮助", "private:10001", gate) is None


def test_wiring_contract_chat_and_empty_never_reach_guide() -> None:
    gate = IgnoreGuideGate(window_seconds=60.0, clock=lambda: 0.0)
    assert _guide_rule_wiring("今天天气不错", "private:10001", gate) is None
    assert _guide_rule_wiring("", "private:10001", gate) is None
    # 闲聊/空消息不占节流名额：其后首个命令形态仍能得到引导。
    assert _guide_rule_wiring("/help", "private:10001", gate) is not None


def test_existing_command_kinds_unaffected() -> None:
    # 引导消费只挂 IGNORE 兜底；既有命令判定面零变化（/bot 管理面等）。
    admin = classify_message_route("/bot status", config=_DefaultConfig(), alias_resolver=None)
    assert admin.kind is RouteKind.ADMIN
    music = classify_message_route("点歌 晴天", config=_DefaultConfig(), alias_resolver=None)
    assert music.kind is RouteKind.MUSIC
