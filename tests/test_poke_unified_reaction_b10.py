"""B10 杂项批 · 统一戳一戳 reaction 分发回归（离线，不依赖 NoneBot）。

交付点：
1. PokeEvent.from_notice 适配器归一（OneBot 风格对象 → 中立事件）；
2. PokeDispatcher 统一门控：开关/目标/冷却/概率，被抑制返回 None；
3. 回戳/话术可配：poke_back 意图、群/私话术覆盖（bot_poke_* 配置）；
4. 旧 API（PokeLimiter / build_poke_text）行为不变（兼容 test_phase0_3_features）。
"""

from __future__ import annotations

from types import SimpleNamespace

from plugins.bot_unified_runtime.domains.chat_reply.capabilities.poke import (
    PokeDispatcher,
    PokeEvent,
    PokeLimiter,
    build_poke_text,
)


def _onebot_notice(**overrides) -> SimpleNamespace:
    base = {
        "notice_type": "notify",
        "sub_type": "poke",
        "target_id": 10001,
        "user_id": 20002,
        "group_id": 30003,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _config(**overrides) -> SimpleNamespace:
    base = {
        "bot_poke_enabled": True,
        "bot_poke_private_cooldown_seconds": 30.0,
        "bot_poke_group_cooldown_seconds": 10.0,
        "bot_poke_probability": 1.0,
        "bot_poke_reply_enabled": True,
        "bot_poke_poke_back": False,
        "bot_poke_group_text": "",
        "bot_poke_private_text": "",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_from_notice_normalizes_onebot_event() -> None:
    poke = PokeEvent.from_notice(_onebot_notice(), bot_id="10001")
    assert poke is not None
    assert poke.target_id == "10001"
    assert poke.user_id == "20002"
    assert poke.group_id == "30003"
    assert poke.sub_type == "poke"
    # 私聊（无 group_id）归一为空串；缺 target_id 时回落 bot_id。
    private = PokeEvent.from_notice(
        _onebot_notice(group_id=None, target_id=None), bot_id="10001"
    )
    assert private is not None
    assert private.group_id == ""
    assert private.target_id == "10001"
    # 非 poke 通知（如群文件上传）拒收。
    assert PokeEvent.from_notice(_onebot_notice(notice_type="group_upload"), bot_id="10001") is None
    # 已归一的 PokeEvent 再过一遍 from_notice 仍可解析（同构复用）。
    normalized = PokeEvent(target_id="10001", user_id="20002", group_id="30003")
    assert PokeEvent.from_notice(normalized, bot_id="10001") is not None


def test_dispatcher_gates_target_enabled_and_cooldown() -> None:
    clock = [100.0]
    dispatcher = PokeDispatcher(clock=lambda: clock[0])
    config = _config()
    # 非戳机器人 → None。
    assert (
        dispatcher.build_poke_reaction(
            _onebot_notice(target_id=99999), bot_id="10001", config=config
        )
        is None
    )
    # 正常命中：默认话术 + 不回戳。
    reaction = dispatcher.build_poke_reaction(
        _onebot_notice(), bot_id="10001", config=config
    )
    assert reaction is not None
    assert reaction.active is True
    assert "轻轻一碰" in reaction.reply
    assert reaction.poke_back is False
    assert reaction.group is True
    assert "poke_group" in reaction.audit_tags
    # 同会话冷却期内 → None。
    assert (
        dispatcher.build_poke_reaction(_onebot_notice(), bot_id="10001", config=config)
        is None
    )
    # 冷却过后恢复。
    clock[0] += 30.0
    assert (
        dispatcher.build_poke_reaction(_onebot_notice(), bot_id="10001", config=config)
        is not None
    )
    # 总开关关闭 → None。
    assert (
        dispatcher.build_poke_reaction(
            _onebot_notice(), bot_id="10001", config=_config(bot_poke_enabled=False)
        )
        is None
    )


def test_dispatcher_poke_back_and_custom_text() -> None:
    """回戳意图可配（恰一臂口径，2026-09-25 ITEM 14(a)）。

    本例原名想验「回戳 + 自定义话术同时成立」——那条语义已被裁定收掉：一次被戳
    只出一种表达，回戳只在形态选中 ``poke`` 那一臂时成立。故这里显式指名
    ``bot_poke_reply_mode="poke"``，保留「poke_back 意图由配置决定」这层原意，
    并把「文本腿仍可按配置取话术」一并锁住。
    """
    dispatcher = PokeDispatcher(clock=lambda: 0.0)
    config = _config(
        bot_poke_poke_back=True,
        bot_poke_reply_mode="poke",
        bot_poke_group_text="别戳啦",
        bot_poke_private_text="戳我干嘛",
    )
    group = dispatcher.build_poke_reaction(
        _onebot_notice(), bot_id="10001", config=config
    )
    assert group is not None
    assert group.mode == "poke" and group.poke_back is True
    assert "poke_back" in group.audit_tags
    # 恰一臂反向锁：形态不是 poke 时，poke_back 开关再开也不许叠第二臂。
    both_off = PokeDispatcher(clock=lambda: 0.0).build_poke_reaction(
        _onebot_notice(user_id=20999),
        bot_id="10001",
        config=_config(bot_poke_poke_back=True, bot_poke_reply_mode="fixed"),
    )
    assert both_off is not None
    assert both_off.mode == "fixed" and both_off.poke_back is False
    private = dispatcher.build_poke_reaction(
        _onebot_notice(group_id=None, user_id=20998), bot_id="10001", config=config
    )
    assert private is not None
    assert private.group is False
    # 话术关闭：只回戳不发文本（新 dispatcher，避免上一步冷却占用）。
    quiet = PokeDispatcher(clock=lambda: 0.0).build_poke_reaction(
        _onebot_notice(),
        bot_id="10001",
        config=_config(
            bot_poke_reply_enabled=False,
            bot_poke_poke_back=True,
            bot_poke_reply_mode="poke",
        ),
    )
    assert quiet is not None
    assert quiet.reply == ""
    assert quiet.poke_back is True
    assert quiet.active is True
    # 话术与回戳全关 → 视为无动作。
    nothing = PokeDispatcher(clock=lambda: 0.0).build_poke_reaction(
        _onebot_notice(),
        bot_id="10001",
        config=_config(bot_poke_reply_enabled=False, bot_poke_poke_back=False),
    )
    assert nothing is not None
    assert nothing.active is False


def test_legacy_poke_limiter_and_text_unchanged() -> None:
    clock = [0.0]
    limiter = PokeLimiter(clock=lambda: clock[0])
    event = SimpleNamespace(
        notice_type="notify",
        sub_type="poke",
        target_id=10,
        user_id=20,
        group_id=30,
    )
    assert limiter.accept(event, "10", True, 60, 30, 10)
    assert not limiter.accept(event, "10", True, 60, 30, 10)
    clock[0] = 80
    event.target_id = 99
    assert not limiter.accept(event, "10", True, 60, 30, 10)
    assert "轻轻一碰" in build_poke_text(group=True, nickname="旅人")
    assert "我在这里" in build_poke_text(group=False)
