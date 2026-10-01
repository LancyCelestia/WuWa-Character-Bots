"""戳一戳三线选路（ITEM 14，席 POKE）离线回归。

三条线（用户 2026-09-25 裁定「完善戳一戳系统」）：

① ``poked_bot``   —— bot 被戳 ⇒ 反戳 / 自然语言 / 语音+文本 / 表情包 / 随机图 任取其一；
② ``peer_poke``   —— 用户 A 戳用户 B ⇒ bot 有概率跟戳；
③ ``bot_spoke``   —— bot 回复完用户 / 主动发言后 ⇒ bot 有概率戳对方。

本件测的是**选路决策纯函数**（``capabilities/poke_routing.py``）：表驱动、无副作用、
可复现（种子注入）。与既有锁的分工：

- ``test_poke_matrix_v4.py`` / ``test_poke_arms_v3.py`` / ``test_poke_randpic_open_state_s_meta.py``
  测 **臂池本体**（``poke.py`` 的行表、恰一臂、五层门语义、根装配接线）；
- 本件测 **三线怎么进臂池**：谁有权掷骰（``dice_owner``）、不可用臂怎么按序回落、
  主动打扰型那两条要过哪些门、私聊 poke 未证实时**绝不"想发却发不出"**。

判据口径（写在这里是因为它们就是测试的断言）：

1. **概率来源可点名**：每个决策都带 ``probability_source``，指明这发是**哪枚配置键**
   或**池内哪一格权重**决定的，审计读得懂、改键找得到地方。
2. **单骰不双掷**：①线的概率归 ``PokeLimiter``（``dice_owner=poke_limiter``），
   ②③线的概率归 ``ProactiveGate``（``dice_owner=proactive_gate``）⇒ 选路层对概率
   ``rolled=False``，只做臂位轮换（``dice_owner=poke_routing`` 只发生在臂下标选择上）。
   两层各掷一次骰 = 同一事件两个概率真身，本件把它钉死。
3. **回落有序且必留痕**：任一臂不可用 ⇒ 按表退到下一臂，``skipped`` 逐臂记否因；
   全链落空 ⇒ ``action=silent`` 且 ``reason=no_usable_arm``（可诊断，绝不假成功）。
4. **主动打扰型受门禁**：blocked 名单 / 安静时间 / 群黑白名单（``policy/gate`` 同源
   四档）任一不过 ⇒ 静默，且**不消耗**任何额度（决策层本就不 commit）。
5. **未证实即不放开**：私聊 poke 通道未实测 ⇒ ②③线私聊一律不投（先例：QQ 无私聊
   表情回应通道，台账 #35★）。

全离线：假时钟、SimpleNamespace、零网络、零真实目录、零源码树写入。
"""

from __future__ import annotations

import ast
from pathlib import Path

from plugins.bot_unified_runtime.domains.chat_reply.capabilities import (
    poke_routing as pr,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.poke import (
    POKE_REACTION_MATRIX,
    poke_mix_pool_arms,
    poke_mix_pool_weights,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTING_SRC = REPO_ROOT / "plugins/bot_unified_runtime/domains/chat_reply/capabilities/poke_routing.py"
CONFIG_SRC = REPO_ROOT / "plugins/bot_unified_runtime/config.py"
MOOD_SRC = REPO_ROOT / "plugins/bot_unified_runtime/domains/chat_reply/character/mood.py"

# ------------------------------------------------------------------ 小工具


def _caps(**overrides) -> pr.PokeCapabilities:
    base = {
        "group_poke_supported": True,
        "private_poke_supported": False,
        "poke_back_switch": True,
        "reply_enabled": True,
        "llm_available": True,
        "tts_available": True,
        "meme_library_available": True,
        "randpic_gallery_available": True,
    }
    base.update(overrides)
    return pr.PokeCapabilities(**base)


def _knobs(**overrides) -> pr.PokeRoutingKnobs:
    base = pr.PokeRoutingKnobs()
    fields = {f: getattr(base, f) for f in base.__dataclass_fields__}
    fields.update(overrides)
    return pr.PokeRoutingKnobs(**fields)


def _req(trigger: str, *, seed: str = "g1:u1", **overrides) -> pr.PokeRouteRequest:
    """构造一次请求；缺省＝"一切能力都在、群已表态、无任何门拦下"，各测试只翻自己要的那枚。"""
    payload: dict[str, object] = {
        "trigger": trigger,
        "seed": seed,
        "is_group": trigger != pr.TRIGGER_POKE_BOT,
        "group_id": "g1",
        "poker_id": "u1",
        "target_id": "u2",
        "now": 1_000.0,
        "bucket": 1,
        "capabilities": _caps(),
        "knobs": _knobs(),
        "recent": pr.PokeRecentLedger(),
        # 群名单四档（policy/gate 同源）里 g1 在白名单1＝主动线默认有场合可站。
        "group_white1": frozenset({"g1"}),
    }
    payload.update(overrides)
    if trigger == pr.TRIGGER_POKE_BOT and "is_group" not in overrides:
        payload["is_group"] = bool(str(payload.get("group_id") or ""))
    return pr.PokeRouteRequest(**payload)


def _line1_extended(**kw) -> pr.PokeRouteDecision:
    knobs = kw.pop("knobs", None) or _knobs(extra_arms_enabled=True)
    return pr.decide_poke_route(_req(pr.TRIGGER_POKE_BOT, knobs=knobs, **kw))


# ============================================================ ① 表本身自洽


def test_routing_table_validates_clean() -> None:
    assert pr.validate_poke_routing_table() == (), "三线选路表自相矛盾"


def test_routing_rows_cover_the_three_lines_exactly_once() -> None:
    rows = pr.poke_routing_rows()
    assert {row.trigger_id for row in rows} == {
        pr.TRIGGER_POKE_BOT,
        pr.TRIGGER_PEER_POKE,
        pr.TRIGGER_BOT_SPOKE,
    }, "三线不齐或多线"
    assert len(rows) == 3, "行数必须恰为三（多一条就是第二真身）"


def test_proactive_lines_declare_proactive_disturbance_and_group_only() -> None:
    """跟戳 / 发言后戳＝主动打扰型：必须自报打扰级、要求群场合、要求群名单表态。"""
    by_id = {row.trigger_id: row for row in pr.poke_routing_rows()}
    for trigger in (pr.TRIGGER_PEER_POKE, pr.TRIGGER_BOT_SPOKE):
        row = by_id[trigger]
        assert row.disturbance == pr.DISTURBANCE_PROACTIVE, trigger
        assert row.requires_group and row.requires_group_consented, trigger
    assert by_id[pr.TRIGGER_POKE_BOT].disturbance == pr.DISTURBANCE_REACTIVE


def test_arm_ids_referenced_by_table_all_exist_in_poke_matrix() -> None:
    """选路表不许自造臂名——臂的唯一真身是 ``poke.py`` 的行表（禁第二真身）。"""
    for row in pr.poke_routing_rows():
        for arm in row.arm_ids():
            assert arm in POKE_REACTION_MATRIX or arm == pr.ACTION_SILENT, f"{row.trigger_id}: {arm} 不在臂表"


def test_dice_owner_is_single_source_of_probability_per_line() -> None:
    """①线概率归 PokeLimiter、②③线归 ProactiveGate；选路层只在臂下标上掷骰。"""
    by_id = {row.trigger_id: row for row in pr.poke_routing_rows()}
    assert by_id[pr.TRIGGER_POKE_BOT].dice_owner == pr.DICE_POKE_LIMITER
    for trigger in (pr.TRIGGER_PEER_POKE, pr.TRIGGER_BOT_SPOKE):
        assert by_id[trigger].dice_owner == pr.DICE_PROACTIVE_GATE
    decision = pr.decide_poke_route(_req(pr.TRIGGER_POKE_BOT))
    assert decision.rolled is False, "选路层不得对「要不要回」再掷一次骰"
    follow = pr.decide_poke_route(_req(pr.TRIGGER_PEER_POKE, knobs=_knobs(follow_enabled=True)))
    assert follow.rolled is False, "选路层不得对跟戳再掷一次骰（那是五层门的骰）"


# ==================================== ② 线一：bot 被戳 ⇒ 五类表达任一可达


def test_all_five_expressions_are_reachable_when_extra_arms_open() -> None:
    """五类表达（反戳/自然语言/语音+文本/表情包/随机图）在扩臂档下都能被选中。"""
    reachable: set[str] = set()
    for index in range(400):
        reachable.add(_line1_extended(seed=f"g1:u{index}").action)
    assert {"poke", "llm", "voice", "meme", "randpic"} <= reachable, f"实到：{sorted(reachable)}"


def test_line1_emits_exactly_one_arm() -> None:
    """恰一臂：决策只有一个动作，回戳绝不与话术/图/语音叠发。"""
    decision = _line1_extended(seed="g1:u7")
    assert decision.action in POKE_REACTION_MATRIX
    assert decision.secondary_actions == (), "一次被戳不得有两个表达"
    if decision.action == "poke":
        assert decision.poke_back is True and decision.reply_needed is False
    else:
        assert decision.poke_back is False


def test_line1_explicit_mode_is_honored() -> None:
    """管理员点名任一臂 ⇒ 不受 mix 池与扩臂档影响（显式意图优先）。"""
    for arm in ("fixed", "llm", "meme", "voice", "randpic", "poke"):
        decision = pr.decide_poke_route(
            _req(pr.TRIGGER_POKE_BOT, seed="g1:uX", knobs=_knobs(reply_mode=arm))
        )
        assert decision.action == arm, f"点名 {arm} 落空：{decision}"


def test_dispatcher_nominated_arm_is_not_re_rolled() -> None:
    """门的交接位：``nominated_arm`` 指哪支就走哪支（选路层不重掷），发不出去才沿链退。"""
    nominated = _line1_extended(seed="g1:u61", nominated_arm="voice")
    assert nominated.action == "voice", nominated
    assert "dispatcher_nominated" in nominated.reasons
    assert nominated.probability_source == "poke_dispatcher.nominated_arm[voice]"
    degraded = _line1_extended(
        seed="g1:u61",
        nominated_arm="meme",
        capabilities=_caps(meme_library_available=False),
    )
    assert degraded.action == "fixed", degraded
    assert degraded.reason == "fallback_to:fixed", degraded
    assert degraded.skipped[0] == ("meme", "arm_unavailable:meme_library_empty")


def test_unavailable_arms_fall_in_written_order_never_nothing() -> None:
    """缺能力 ⇒ 按表回落；链上必须留痕，终态不得是"什么都没发却带成功标签"。"""
    decision = _line1_extended(
        seed="g1:u9",
        knobs=_knobs(reply_mode="meme"),
        capabilities=_caps(meme_library_available=False),
    )
    assert decision.action == "fixed", decision
    assert decision.skipped and decision.skipped[0][0] == "meme"
    assert "arm_unavailable" in decision.skipped[0][1]
    assert decision.reason.startswith("fallback_to"), decision.reason


def test_poke_arm_degrades_to_text_when_platform_unproven() -> None:
    """群内主动 poke 未证实（协议端不支持）⇒ 点名 poke 也要退固定话术，绝不空回。"""
    decision = _line1_extended(
        seed="g1:u3",
        knobs=_knobs(reply_mode="poke"),
        capabilities=_caps(group_poke_supported=False),
    )
    assert decision.action == "fixed"
    assert decision.poke_back is False
    assert any(tag.startswith("poke_channel_off") for tag in decision.audit_tags), decision.audit_tags


def test_whole_chain_unavailable_reports_silent_with_diagnosis() -> None:
    """reply 关 + 各资源缺 + poke 不可用 ⇒ 明确静默并点名原因（不静默失败）。"""
    decision = _line1_extended(
        seed="g1:u5",
        knobs=_knobs(reply_mode="randpic"),
        capabilities=_caps(
            reply_enabled=False,
            llm_available=False,
            tts_available=False,
            meme_library_available=False,
            randpic_gallery_available=False,
            group_poke_supported=False,
        ),
    )
    assert decision.action == pr.ACTION_SILENT
    assert decision.reason == "no_usable_arm", decision
    assert len(decision.skipped) >= 2, "每个被跳过的臂都要留否因"


def test_voice_arm_text_leg_survives_when_tts_off() -> None:
    """语音臂在合成不可用时仍是"文本腿"（既有降级口径），不改成不发。"""
    decision = _line1_extended(
        seed="g1:u11",
        knobs=_knobs(reply_mode="voice"),
        capabilities=_caps(tts_available=False),
    )
    assert decision.action == "voice"
    assert decision.audio_leg is False
    assert any(tag == "voice_audio_leg_off" for tag in decision.audit_tags)


def test_probability_source_names_config_key_or_pool_weight() -> None:
    """审计字段要能指出这发由哪枚键/哪格权重决定。"""
    decision = _line1_extended(seed="g1:u17")
    assert decision.probability_source.startswith("poke_mix_pool_weights[extended]"), decision
    weights = poke_mix_pool_weights("extended")
    assert weights[decision.action] > 0, "点名的臂必须在池内有权重"


# ============================ ③ 线二：A 戳 B ⇒ 跟戳（主动打扰型防骚扰门）


def _follow_knobs() -> pr.PokeRoutingKnobs:
    return _knobs(follow_enabled=True)


def test_follow_targets_the_poked_peer_not_the_poker_by_default() -> None:
    decision = pr.decide_poke_route(_req(pr.TRIGGER_PEER_POKE, knobs=_follow_knobs()))
    assert decision.action == "poke"
    assert decision.target_user_id == "u2", "跟戳先戳被戳者 B"


def test_follow_falls_back_to_poker_when_peer_unusable() -> None:
    """B 在 blocked 名单 ⇒ 候选退 A（既有 ``proactive_poke_candidates`` 口径）。"""
    decision = pr.decide_poke_route(
        _req(pr.TRIGGER_PEER_POKE, knobs=_follow_knobs(), target_blocked=True)
    )
    assert decision.target_user_id == "u1"
    assert any(tag.startswith("follow_candidate_fallback") for tag in decision.audit_tags)


def test_follow_denied_without_candidates_never_burns_the_gate() -> None:
    """A、B 都不可投 ⇒ 静默，且 committable=False（不得让门白烧冷却/额度）。"""
    decision = pr.decide_poke_route(
        _req(pr.TRIGGER_PEER_POKE, knobs=_follow_knobs(), target_blocked=True, poker_blocked=True)
    )
    assert decision.action == pr.ACTION_SILENT
    assert decision.reason == "no_candidate", decision
    assert decision.committable is False


def test_follow_requires_group_channel() -> None:
    """私聊没有"当众跟戳"这回事：非群场合一杠不成立。"""
    decision = pr.decide_poke_route(
        _req(pr.TRIGGER_PEER_POKE, knobs=_follow_knobs(), is_group=False, group_id="")
    )
    assert decision.action == pr.ACTION_SILENT and decision.reason == "requires_group", decision


def test_follow_requires_group_to_have_consented() -> None:
    """群名单四档（policy/gate 同源）：黑名单赢；都没表态＝不放开。"""
    black = pr.decide_poke_route(
        _req(pr.TRIGGER_PEER_POKE, knobs=_follow_knobs(), group_black1=frozenset({"g1"}))
    )
    assert black.action == pr.ACTION_SILENT and black.reason == "group_blacklisted"
    unlisted = pr.decide_poke_route(
        _req(
            pr.TRIGGER_PEER_POKE,
            knobs=_follow_knobs(),
            group_white1=frozenset(),
            group_white2=frozenset(),
        )
    )
    assert unlisted.reason == "group_not_consented", "未表态群不得被主动戳（缺省保守）"
    white = pr.decide_poke_route(
        _req(pr.TRIGGER_PEER_POKE, knobs=_follow_knobs(), group_white2=frozenset({"g1"}))
    )
    assert white.action == "poke"


def test_proactive_lines_never_fall_back_to_an_unrequested_text() -> None:
    """主动线的退路只有「不发」：戳不出去绝不退成一条没人要的话（判据 3）。"""
    for trigger, knobs in (
        (pr.TRIGGER_PEER_POKE, _follow_knobs()),
        (pr.TRIGGER_BOT_SPOKE, _spoke_knobs()),
    ):
        decision = pr.decide_poke_route(
            _req(trigger, knobs=knobs, capabilities=_caps(group_poke_supported=False))
        )
        assert decision.action == pr.ACTION_SILENT, f"{trigger} 落空却改发了正文：{decision}"
        assert decision.reason == "no_usable_arm", decision
        assert decision.fallback_chain == ()


def test_follow_quiet_hours_and_switch_denials_are_distinct_and_free() -> None:
    """安静时间／总闸两类拒绝要能分开点名，且都不消耗额度（committable=False）。"""
    quiet = pr.decide_poke_route(
        _req(pr.TRIGGER_PEER_POKE, knobs=_follow_knobs(), quiet_hours_active=True)
    )
    assert quiet.action == pr.ACTION_SILENT and quiet.reason == "quiet_hours", quiet
    disabled = pr.decide_poke_route(_req(pr.TRIGGER_PEER_POKE, knobs=_knobs()))
    assert disabled.action == pr.ACTION_SILENT and disabled.reason == "line_disabled", disabled
    for decision in (quiet, disabled):
        assert decision.committable is False, "被拦下的一发不得让五层门记账"


def test_follow_recent_ledger_blocks_cooldown_and_hourly_cap() -> None:
    """近期已发账：窗内冷却 / 每小时上限到顶 ⇒ 静默并点名是哪一层。"""
    cooling = pr.decide_poke_route(
        _req(
            pr.TRIGGER_PEER_POKE,
            knobs=_follow_knobs(),
            group_white1=frozenset({"g1"}),
            recent=pr.PokeRecentLedger(
                last_action_at={pr.TRIGGER_PEER_POKE: 999.0},
            ),
        )
    )
    assert cooling.reason == "cooldown", cooling
    assert cooling.cooldown_remaining_seconds > 0
    capped = pr.decide_poke_route(
        _req(
            pr.TRIGGER_PEER_POKE,
            knobs=_knobs(follow_enabled=True, follow_max_per_hour=2),
            group_white1=frozenset({"g1"}),
            recent=pr.PokeRecentLedger(actions_in_hour={pr.TRIGGER_PEER_POKE: 2}),
        )
    )
    assert capped.reason == "hourly_cap", capped


def test_follow_probability_source_names_its_config_key() -> None:
    decision = pr.decide_poke_route(
        _req(pr.TRIGGER_PEER_POKE, knobs=_follow_knobs(), group_white1=frozenset({"g1"}))
    )
    assert decision.probability_source == "bot_poke_follow_probability", decision
    assert decision.probability == _follow_knobs().follow_probability


# ==================== ④ 线三：bot 回复完 / 主动发言后 ⇒ 有概率戳对方


def _spoke_knobs() -> pr.PokeRoutingKnobs:
    return _knobs(after_reply_enabled=True)


def test_after_spoke_pokes_the_addressee_and_reports_its_knob() -> None:
    decision = pr.decide_poke_route(
        _req(pr.TRIGGER_BOT_SPOKE, knobs=_spoke_knobs(), group_white2=frozenset({"g1"}))
    )
    assert decision.action == "poke" and decision.target_user_id == "u1"
    assert decision.probability_source == "bot_poke_after_reply_probability"


def test_after_spoke_never_pokes_privately_while_channel_unproven() -> None:
    """私聊 poke 未实测 ⇒ 发言后戳人在私聊不投（台账 #35★ 同型先例）。"""
    decision = pr.decide_poke_route(
        _req(pr.TRIGGER_BOT_SPOKE, knobs=_spoke_knobs(), is_group=False, group_id="")
    )
    assert decision.action == pr.ACTION_SILENT
    assert decision.reason in {"requires_group", "poke_channel_unproven_private"}, decision


def test_after_spoke_respects_private_channel_once_proven() -> None:
    """拿到实机证据（申报 private_poke_supported=True）后，私聊那发才放行。"""
    decision = pr.decide_poke_route(
        _req(
            pr.TRIGGER_BOT_SPOKE,
            knobs=_spoke_knobs(),
            is_group=False,
            group_id="",
            capabilities=_caps(private_poke_supported=True),
            allow_private_proactive=True,
        )
    )
    assert decision.action == "poke", decision


def test_after_spoke_own_ledger_is_not_shared_with_follow() -> None:
    """三条线各记各的账：跟戳到顶不该吞掉发言后戳的额度。"""
    decision = pr.decide_poke_route(
        _req(
            pr.TRIGGER_BOT_SPOKE,
            knobs=_spoke_knobs(),
            group_white1=frozenset({"g1"}),
            recent=pr.PokeRecentLedger(
                last_action_at={pr.TRIGGER_PEER_POKE: 999.5},
                actions_in_hour={pr.TRIGGER_PEER_POKE: 9},
            ),
        )
    )
    assert decision.action == "poke", decision


# ============================================ ⑤ 心情 / 好感度 / 复现性 / 卫生


def test_low_mood_trims_noisy_arms_and_damps_proactive_probability() -> None:
    trimmed = _line1_extended(
        seed="g1:u21",
        knobs=_knobs(extra_arms_enabled=True, mood_quiet_valence=-0.25),
        mood_valence=-0.8,
    )
    assert trimmed.action not in {"meme", "voice"}, trimmed
    assert any(tag.startswith("mood_quiet_pool_trim") for tag in trimmed.audit_tags)
    damped = pr.decide_poke_route(
        _req(
            pr.TRIGGER_PEER_POKE,
            knobs=_follow_knobs(),
            group_white1=frozenset({"g1"}),
            mood_willingness=0.8,
        )
    )
    assert damped.probability == round(_follow_knobs().follow_probability * 0.8, 6), damped
    assert "×mood.willingness" in damped.probability_source


def test_quiet_mood_never_empties_the_pool() -> None:
    """旧三臂池里除 fixed 外都算吵 ⇒ 修剪后必须还剩一臂，绝不清空成"不发"。"""
    decision = pr.decide_poke_route(
        _req(pr.TRIGGER_POKE_BOT, seed="g1:u23", mood_valence=-0.9, is_group=True)
    )
    assert decision.action in POKE_REACTION_MATRIX, decision


def test_affinity_credit_only_for_the_person_who_poked_bot() -> None:
    """被戳才记正向互动；bot 主动戳人不给自己刷分。"""
    back = _line1_extended(seed="g1:u25")
    assert back.affinity_principal == "u1" and back.affinity_source == "poke"
    for trigger, knobs in (
        (pr.TRIGGER_PEER_POKE, _follow_knobs()),
        (pr.TRIGGER_BOT_SPOKE, _spoke_knobs()),
    ):
        decision = pr.decide_poke_route(
            _req(trigger, knobs=knobs, group_white1=frozenset({"g1"}))
        )
        assert decision.affinity_principal == "", f"{trigger} 不得自带好感加分"


def test_proactive_lines_honour_affinity_floor_when_set() -> None:
    """搭话好感门不许绕：设了地板且读数低于它 ⇒ 主动戳人不投。"""
    decision = pr.decide_poke_route(
        _req(
            pr.TRIGGER_BOT_SPOKE,
            knobs=_knobs(after_reply_enabled=True, proactive_affinity_floor=0.5),
            group_white1=frozenset({"g1"}),
            affinity_value=0.1,
        )
    )
    assert decision.action == pr.ACTION_SILENT and decision.reason == "affinity_floor", decision


def test_decisions_are_reproducible_from_seed_and_change_with_bucket() -> None:
    first = _line1_extended(seed="g1:u31", )
    second = _line1_extended(seed="g1:u31")
    assert first == second, "同种子同判定（可复现是审计的前提）"
    other_bucket = pr.decide_poke_route(
        _req(pr.TRIGGER_POKE_BOT, seed="g1:u31", knobs=_knobs(extra_arms_enabled=True), bucket=99)
    )
    assert isinstance(other_bucket.arm_index, int)
    spread = {
        pr.decide_poke_route(
            _req(pr.TRIGGER_POKE_BOT, seed=f"g1:u{index}", knobs=_knobs(extra_arms_enabled=True))
        ).arm_index
        for index in range(200)
    }
    assert len(spread) > 1, "桶内下标必须真在轮换"


def test_advance_after_failed_delivery_walks_the_chain() -> None:
    """执行面回执"没送出去"时，选路层给出下一臂（有序回落，不静默全失败）。"""
    decision = _line1_extended(seed="g1:u41", knobs=_knobs(reply_mode="poke"))
    assert decision.action == "poke"
    nxt = pr.advance_poke_route(decision, failed_arm="poke", capabilities=_caps(group_poke_supported=False))
    assert nxt.action == "fixed", nxt
    assert nxt.reason == "fallback_after_delivery_failure", nxt
    dead_end = pr.advance_poke_route(nxt, failed_arm="fixed", capabilities=_caps(reply_enabled=False))
    assert dead_end.action == pr.ACTION_SILENT and dead_end.reason == "no_usable_arm"


def test_routing_module_reads_no_config_keys_and_no_affinity_write() -> None:
    """选路层必须是纯函数：不碰 ``getattr(config, ...)``（配置键登记总账的直读尺
    因此不会看见幽灵读点），也不碰好感度入账口（唯一入账口在根装配面）。"""
    tree = ast.parse(ROUTING_SRC.read_text(encoding="utf-8-sig"))
    source = ROUTING_SRC.read_text(encoding="utf-8-sig")
    offenders: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and str(node.args[1].value).startswith(("bot_", "BOT_"))
        ):
            offenders.append(f"getattr(config) 读键：{node.args[1].value}")
    assert not offenders, "选路层不该读配置键（读点在调用点）：" + "；".join(offenders)
    assert ".observe_points(" not in source, "好感度入账口必须唯一（在根装配面）"
    assert "random." not in source, "确定性来自摘要，不用 random"


def test_knob_defaults_match_registered_config_fields() -> None:
    """``PokeRoutingKnobs`` 的缺省数必须等于 ``config.py`` 里同名字段的缺省（零手抄：
    两侧都从源码现读；尚未登记的键跳过，登记当天自动纳管）。"""

    def _config_defaults(path: Path) -> dict[str, object]:
        out: dict[str, object] = {}
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
                continue
            init = node.value
            if isinstance(init, ast.Call) and getattr(init.func, "attr", "") == "Field" and init.args:
                out[node.target.id] = ast.literal_eval(init.args[0])
            elif init is not None:
                try:
                    out[node.target.id] = ast.literal_eval(init)
                except (ValueError, SyntaxError):
                    pass
        return out

    defaults = _config_defaults(CONFIG_SRC)
    knobs = pr.PokeRoutingKnobs()
    mapping = {
        "reply_mode": "bot_poke_reply_mode",
        "extra_arms_enabled": "bot_poke_extra_arms_enabled",
        "follow_enabled": "bot_poke_follow_enabled",
        "follow_probability": "bot_poke_follow_probability",
        "follow_cooldown_seconds": "bot_poke_follow_cooldown_seconds",
        "follow_max_per_hour": "bot_poke_follow_max_per_hour",
        "after_reply_enabled": "bot_poke_after_reply_enabled",
        "after_reply_probability": "bot_poke_after_reply_probability",
        "after_reply_cooldown_seconds": "bot_poke_after_reply_cooldown_seconds",
        "after_reply_max_per_hour": "bot_poke_after_reply_max_per_hour",
    }
    bad = [
        f"{field}: 选路缺省 {getattr(knobs, field)!r} ≠ config.py {defaults[field_key]!r}"
        for field, field_key in mapping.items()
        if field_key in defaults and defaults[field_key] != getattr(knobs, field)
    ]
    assert not bad, "选路缺省与真身不一致：" + "；".join(bad)


def test_mood_quiet_band_default_matches_mood_module() -> None:
    """心情"低落档"阈值不许自造：与 ``character/mood.py`` 的 ``_V_NEGATIVE`` 同值
    （两侧现读，零手抄数字）。"""
    source = MOOD_SRC.read_text(encoding="utf-8-sig")
    assigned = None
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "_V_NEGATIVE":
            assigned = ast.literal_eval(node.value)
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_V_NEGATIVE":
                    assigned = ast.literal_eval(node.value)
    assert assigned is not None, "mood.py 找不到 _V_NEGATIVE＝尺失明"
    assert pr.PokeRoutingKnobs().mood_quiet_valence == float(assigned)


def test_line1_pool_membership_is_the_same_tuple_as_poke_matrix() -> None:
    """臂池不许抄第二份：选路层用的池必须是 ``poke.py`` 派生的同一枚元组。"""
    assert pr.poke_line_arm_pool(True) == poke_mix_pool_arms("extended")
    assert pr.poke_line_arm_pool(False) == poke_mix_pool_arms("legacy")
