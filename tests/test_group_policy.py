from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.contracts import (
    IncomingMessage,
    RiskLevel,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.policy.gate import (
    GROUP_POLICY_SLOTS,
    PolicySettings,
    configure_proactive_affinity_gate,
    evaluate_policy,
    group_is_listed,
)


def _message(text: str, *, mentions_bot: bool = False, group_id: str = "group-1") -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="nonebot",
        bot_id="bot-1",
        session_id=f"group:{group_id}",
        session_type=SessionType.GROUP,
        sender_id="user-1",
        group_id=group_id,
        plain_text=text,
        mentions_bot=mentions_bot,
        message_id="message-1",
    )


def test_white2_allows_explicit_command_without_mention() -> None:
    decision = evaluate_policy(
        _message("/bot status"),
        "bot.chat",
        PolicySettings(group_white2=frozenset({"group-1"})),
    )

    assert decision.allowed is True


def test_white2_allows_mentioned_message_but_rejects_passive_message() -> None:
    settings = PolicySettings(group_white2=frozenset({"group-1"}))

    assert evaluate_policy(_message("你好", mentions_bot=True), "bot.chat", settings).allowed
    denied = evaluate_policy(_message("你好"), "bot.chat", settings)
    assert denied.allowed is False
    assert denied.reason == "group_white2_need_trigger"


def test_white2_does_not_proactively_reply() -> None:
    decision = evaluate_policy(
        _message("普通闲聊"),
        "bot.chat",
        PolicySettings(
            group_white2=frozenset({"group-1"}),
            group_auto_reply_enabled=True,
            group_auto_reply_probability=1.0,
        ),
    )

    assert decision.allowed is False


def test_white1_is_the_only_group_allowed_to_proactively_reply() -> None:
    settings = PolicySettings(
        group_white1=frozenset({"group-1"}),
        group_auto_reply_enabled=True,
        group_auto_reply_probability=1.0,
    )

    selected = evaluate_policy(_message("普通闲聊"), "bot.chat", settings)
    assert selected.allowed is True
    assert selected.reason == "proactive_reply_selected"

    other = evaluate_policy(
        _message("普通闲聊", group_id="group-2"),
        "bot.chat",
        settings,
    )
    assert other.allowed is False
    assert other.reason == "passive_group_message"


# ---------------------------------------------------------------------------
# 视觉回复腿 × 两枚中央门（group_auto_reply_enabled 总闸 / N4 好感门）真值表。
# 缺陷底账＝M2-31：视觉腿 `vision_reply_selected` 此前两门都不查，且全仓零测试锁。
# 配对锁与代码同笔（只准变严：删掉任一枚门的接线本段必红）。
# ---------------------------------------------------------------------------


def _visual_message(*, group_id: str = "group-1") -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="nonebot",
        bot_id="bot-1",
        session_id=f"group:{group_id}",
        session_type=SessionType.GROUP,
        sender_id="user-1",
        group_id=group_id,
        plain_text="",
        message_id="message-1",
        raw_segments=[{"type": "image", "data": {"url": "https://visual.test/x.png"}}],
    )


def _white1_always_drawn(*, enabled: bool = True) -> PolicySettings:
    return PolicySettings(
        group_white1=frozenset({"group-1"}),
        group_auto_reply_enabled=enabled,
        group_auto_reply_probability=1.0,  # 抽签必中，聚焦测门本身。
    )


@pytest.fixture()
def _reset_affinity_gate():
    yield
    configure_proactive_affinity_gate(None)


def test_vision_leg_respects_auto_reply_switch() -> None:
    decision = evaluate_policy(
        _visual_message(), "bot.chat", _white1_always_drawn(enabled=False)
    )
    assert decision.allowed is False
    assert decision.reason == "passive_group_message"


def test_vision_leg_selected_with_switch_on_and_close_sender(_reset_affinity_gate) -> None:
    configure_proactive_affinity_gate(lambda sender: True)
    decision = evaluate_policy(_visual_message(), "bot.chat", _white1_always_drawn())
    assert decision.allowed is True
    assert decision.reason == "vision_reply_selected"


def test_vision_leg_blocked_by_affinity_gate(_reset_affinity_gate) -> None:
    configure_proactive_affinity_gate(lambda sender: False)
    decision = evaluate_policy(_visual_message(), "bot.chat", _white1_always_drawn())
    assert decision.allowed is False
    assert decision.reason == "proactive_affinity_gate"


def test_vision_and_text_legs_share_both_gates(_reset_affinity_gate) -> None:
    """两腿同闸：同 settings 下两腿读数一致（防第 N 条抽签腿再漏接）。"""
    settings_on = _white1_always_drawn()
    configure_proactive_affinity_gate(lambda sender: False)
    assert evaluate_policy(_visual_message(), "bot.chat", settings_on).reason == (
        evaluate_policy(_message("普通闲聊"), "bot.chat", settings_on).reason
    )

    settings_off = _white1_always_drawn(enabled=False)
    configure_proactive_affinity_gate(None)
    vision = evaluate_policy(_visual_message(), "bot.chat", settings_off)
    assert vision.allowed is False
    assert vision.reason == evaluate_policy(
        _message("普通闲聊"), "bot.chat", settings_off
    ).reason


# ---------------------------------------------------------------------------
# E05 缺口一 · 未在册群的命令腿必须关门。
# 缺陷底账：群分支末尾 fall-through `allowed=True`——群不在 black1/black2/
# white1/white2 任何一册时，任意成员敲 /bot 全通（.env 从未填过群名单）。
# 红线（同段配对锁）：黑白名单既有语义**一字未动**——硬否决仍在最前、
# 空名单被动回复仍 fail-close、搭话好感门双腿仍同检。本段只收紧命令态。
# ---------------------------------------------------------------------------


def _private(text: str, *, roles: tuple[str, ...] = ("user",)) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="nonebot",
        bot_id="bot-1",
        session_id="private:user-1",
        session_type=SessionType.PRIVATE,
        sender_id="user-1",
        sender_roles=list(roles),
        plain_text=text,
        message_id="message-1",
    )


def _group(text, *, roles=("user",), mentions_bot=False, group_id="group-1"):
    message = _message(text, mentions_bot=mentions_bot, group_id=group_id)
    return message.model_copy(update={"sender_roles": list(roles)})


def test_command_in_unlisted_group_is_denied() -> None:
    """四册皆不含的群 + 命令态 ⇒ 拒（这就是缺口本身，改前恒放行）。"""
    decision = evaluate_policy(_group("/bot status"), "bot.status", PolicySettings())
    assert decision.allowed is False
    assert decision.reason == "command_group_unlisted"
    assert "policy" in decision.audit_tags


def test_alias_command_in_unlisted_group_is_denied() -> None:
    """别名命令（extra_command_check）同受此门——攻击面同形，不留第二道缝。"""
    settings = PolicySettings(extra_command_check=lambda text: text.startswith("/岸宝"))
    decision = evaluate_policy(_group("/岸宝帮助"), "bot.help", settings)
    assert decision.allowed is False
    assert decision.reason == "command_group_unlisted"


@pytest.mark.parametrize(
    "settings",
    [
        PolicySettings(group_white1=frozenset({"group-1"})),
        PolicySettings(group_white2=frozenset({"group-1"})),
        PolicySettings(group_black2=frozenset({"group-1"})),
    ],
    ids=["white1", "white2", "black2-mentioned"],
)
def test_listed_group_command_still_allowed(settings: PolicySettings) -> None:
    """合法形：在册群的命令一律照旧能过（black2 需带 @，夹具已带）。"""
    decision = evaluate_policy(
        _group("/bot help", mentions_bot=True), "bot.chat", settings
    )
    assert decision.allowed is True


def test_dynamic_provider_listing_opens_the_command_leg() -> None:
    """在册面含动态 provider（管理员热改）：provider 给了群就算在册。"""
    settings = PolicySettings(
        group_lists_provider=lambda: {"white1": frozenset({"group-1"})}
    )
    assert evaluate_policy(_group("/bot help"), "bot.chat", settings).allowed is True


def test_flag_off_restores_legacy_open_behaviour() -> None:
    """止血开关：置 False 回退旧行为（事故时可关，不作缺省）。"""
    settings = PolicySettings(command_requires_listed_group=False)
    decision = evaluate_policy(_group("/bot status"), "bot.status", settings)
    assert decision.allowed is True


def test_unlisted_group_passive_message_keeps_old_reason() -> None:
    """被动腿零变更：未触发群消息仍 fail-close 到 passive_group_message。"""
    decision = evaluate_policy(_message("普通闲聊"), "bot.chat", PolicySettings())
    assert decision.allowed is False
    assert decision.reason == "passive_group_message"


def test_unlisted_group_mentioned_chat_unchanged() -> None:
    """红线锁（不是新门的战利品）：@bot 说人话在 HEAD 就是「主动触发」，未在册群
    也照旧放行——本席**只收紧命令态**，不顺手改 @ 腿语义（要治那一层属白名单面，
    归用户裁定）。此断言若哪天变 False，说明有人把命令门扩到了 @ 腿上。
    """
    decision = evaluate_policy(
        _message("你好", mentions_bot=True), "bot.chat", PolicySettings()
    )
    assert decision.allowed is True
    assert decision.reason == "allowed"


def test_prefix_without_word_boundary_is_not_command_state() -> None:
    """`/botxxx` 不算命令态（is_command_text 语义守住）⇒ 不落到新 reason。"""
    decision = evaluate_policy(_message("/botxxx"), "bot.chat", PolicySettings())
    assert decision.allowed is False
    assert decision.reason == "passive_group_message"


def test_private_session_commands_are_untouched() -> None:
    """私聊路径不受影响：整段门只在 GROUP 分支内。"""
    assert evaluate_policy(_private("/bot status"), "bot.status", PolicySettings()).allowed
    assert evaluate_policy(_private("/bot 帮助"), "bot.help", PolicySettings()).allowed


def test_hard_vetoes_precede_the_unlisted_command_gate() -> None:
    """硬否决优先：blocked 角色 / CRITICAL 风险 / black1 群都仍是原 reason。"""
    blocked = evaluate_policy(
        _group("/bot status", roles=("blocked",)), "bot.status", PolicySettings()
    )
    assert blocked.reason == "sender_blocked"

    black1 = evaluate_policy(
        _group("/bot status"),
        "bot.status",
        PolicySettings(group_black1=frozenset({"group-1"})),
    )
    assert black1.reason == "group_black1"

    critical = evaluate_policy(
        _group("/bot status").model_copy(update={"risk_level": RiskLevel.CRITICAL}),
        "bot.status",
        PolicySettings(),
    )
    assert critical.reason == "critical_input_risk"


def test_listen_only_account_still_wins_over_the_new_gate() -> None:
    """监听专用号：命令/点名全否决的旧语义在前，reason 不许被新门顶掉。"""
    settings = PolicySettings(listen_only_bot_ids=frozenset({"bot-1"}))
    decision = evaluate_policy(_group("/bot status"), "bot.status", settings)
    assert decision.reason == "listen_only_account"


def test_group_is_listed_uses_the_four_slots_single_truth() -> None:
    """谓词只吃 GROUP_POLICY_SLOTS（禁第二份名单名），缺键按缺席处理。"""
    assert group_is_listed({"black2": frozenset({"g"})}, "g")
    assert not group_is_listed({"black2": frozenset({"g"})}, "other")
    assert not group_is_listed({}, "")
    # 槽名真身＝四档；多给无关键不算在册。
    assert not group_is_listed({"grey": frozenset({"g"})}, "g")
    assert set(GROUP_POLICY_SLOTS) == {"black1", "black2", "white1", "white2"}
