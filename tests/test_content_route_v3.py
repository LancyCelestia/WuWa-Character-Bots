"""v21r5 B 席：群聊亲密模式双开关 + 1h TTL + 四名单（离线单测）。

用户裁定（2026-09-19）：
1. 开关一（个人级）：群成员对自己「亲密模式 开」→ 仅 (群,用户) 生效；
2. 开关二（全群级）：管理员开 → 全群生效（既有语义保留）；
3. 两个开关同一 TTL，默认 60 分钟自动退出（按激活时刻起算、活跃不续期、
   重新开启即重置；既有 max_ttl=120 保留为全状态硬上限）；
4. 四名单：私聊白/黑名单（白名单空=放开、非空=仅名单内；黑名单最高优先，
   Master Love 压不过黑名单）+ 群白/黑名单（既有，群白名单空=关闭）。

覆盖：TTL 过期语义（默认 60m/覆盖/活动不续期/重开重置/max_ttl 交叠/
normal 钉不吃 TTL）、群级/个人级并存与优先级、指令分流（管理员→群键、
成员→成员键、per_user 关闭拒绝）、四名单全场景、resolve_intimate_context
合成（双门同源）、build_chat_result 群聊集成（成员隔离/分流落地）。
全部离线 mock，零网络、零真实 LLM。
"""
from __future__ import annotations

from types import SimpleNamespace

from plugins.bot_unified_runtime.capabilities.chat import (
    INTIMATE_RP_STYLE_INSTRUCTION,
    MANUAL_OFF_REPLY,
    MANUAL_ON_REPLY,
    NORMAL_NO_ACTION_INSTRUCTION,
    _manual_command_scope_key,
    build_chat_result,
)
from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    ContextBundle,
    ConversationHistoryResult,
    IncomingMessage,
    MemoryRetrievalResult,
    PersonaProfile,
    PrivacyLevel,
    RetrievalResult,
    RiskLevel,
    SendPolicy,
    SessionType,
    ToneProfile,
)
from plugins.bot_unified_runtime.llm.providers import LLMReply
from plugins.bot_unified_runtime.runtime.content_route import (
    ContentRouteEngine,
    explicit_allowed_for_session,
    match_manual_command,
    member_session_key,
    resolve_intimate_context,
    split_member_session_key,
)


def _config(**overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "bot_content_route_enabled": True,
        "bot_content_route_model": "grok-4.6",
        "bot_content_route_order": "grok-4.6,gemini-3.8-flash",
        "bot_content_route_words": "",
        "bot_content_route_intimate_threshold": 60.0,
        "bot_content_route_normal_threshold": 25.0,
        "bot_content_route_context_turns": 4,
        "bot_content_route_max_ttl_minutes": 120.0,
        "bot_content_route_idle_reset_minutes": 10.0,
        "bot_content_route_intimate_ttl_minutes": 60.0,
        "bot_content_route_group_per_user_enabled": True,
        "bot_content_route_group_whitelist": [],
        "bot_content_route_group_blacklist": [],
        "bot_content_route_private_whitelist": [],
        "bot_content_route_private_blacklist": [],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _engine(clock_now: list[float]) -> ContentRouteEngine:
    return ContentRouteEngine(clock=lambda: clock_now[0])


MIN = 60.0


# ---------------------------------------------------------------- 键往返

def test_member_key_roundtrip() -> None:
    key = member_session_key("group:123", "456")
    assert key == "group:123||u:456"
    assert split_member_session_key(key) == ("group:123", "456")
    assert split_member_session_key("group:123") is None
    assert split_member_session_key("group:123||u:") is None  # 空成员不构成键
    assert split_member_session_key("||u:456") is None  # 空群键不构成键
    # 私聊键不会误判（不同前缀形态）。
    assert split_member_session_key("private:456") is None


# ---------------------------------------------------------------- TTL：默认 60 分钟自动退出

def test_private_pin_expires_after_default_60_minutes() -> None:
    now = [100.0]
    engine = _engine(now)
    cfg = _config()  # 不含覆盖：验证 getattr 缺省 60。
    assert engine.apply_manual("private:u1", "intimate", cfg)
    now[0] += 59 * MIN
    assert engine.route_verdict("private:u1", cfg)["mode"] == "intimate"
    now[0] += 2 * MIN  # 61 分钟：超过默认 TTL。
    assert engine.route_verdict("private:u1", cfg)["mode"] == "normal"
    # 钉死后回到滞回/分数态：分数已清零，L1 强词才可再进。
    engine.observe_turn("private:u1", message_text="今天天气很好", config=cfg)
    assert engine.route_verdict("private:u1", cfg)["mode"] == "normal"


def test_activity_does_not_extend_intimate_pin_ttl() -> None:
    """裁定 3：1 小时后自动退出——活跃会话不续期（activated_at 不滑动）。
    激活后持续聊天 59 分钟仍在档；61 分钟时即便 2 分钟前刚活跃过也退出。"""
    now = [100.0]
    engine = _engine(now)
    cfg = _config()
    assert engine.apply_manual("private:u1", "intimate", cfg)
    for _ in range(5):  # 10 分钟一轮的活跃会话，聊满 50 分钟。
        now[0] += 10 * MIN
        engine.observe_turn("private:u1", message_text="还在聊哦", config=cfg)
        assert engine.route_verdict("private:u1", cfg)["mode"] == "intimate"
    now[0] += 9 * MIN  # 59 分钟：最近一次活跃仅在 1 分钟前。
    engine.observe_turn("private:u1", message_text="继续呀", config=cfg)
    assert engine.route_verdict("private:u1", cfg)["mode"] == "intimate"
    now[0] += 2 * MIN  # 61 分钟：越过 TTL，活跃不续期。
    assert engine.route_verdict("private:u1", cfg)["mode"] == "normal"


def test_repin_resets_ttl_timer() -> None:
    now = [100.0]
    engine = _engine(now)
    cfg = _config()
    assert engine.apply_manual("private:u1", "intimate", cfg)
    now[0] += 50 * MIN
    assert engine.apply_manual("private:u1", "intimate", cfg)  # 重新开启=重置计时。
    now[0] += 50 * MIN  # 距首次开启 100 分钟，但距重开仅 50 分钟。
    assert engine.route_verdict("private:u1", cfg)["mode"] == "intimate"
    now[0] += 11 * MIN
    assert engine.route_verdict("private:u1", cfg)["mode"] == "normal"


def test_ttl_config_override() -> None:
    now = [100.0]
    engine = _engine(now)
    cfg = _config(bot_content_route_intimate_ttl_minutes=5)
    assert engine.apply_manual("private:u1", "intimate", cfg)
    now[0] += 4 * MIN
    assert engine.route_verdict("private:u1", cfg)["mode"] == "intimate"
    now[0] += 2 * MIN
    assert engine.route_verdict("private:u1", cfg)["mode"] == "normal"


def test_max_ttl_hard_cap_still_applies_below_ttl() -> None:
    """既有 max_ttl=120 保留为硬上限：max_ttl < TTL 时小者先到。"""
    now = [100.0]
    engine = _engine(now)
    cfg = _config(
        bot_content_route_max_ttl_minutes=10.0,
        bot_content_route_intimate_ttl_minutes=60.0,
    )
    assert engine.apply_manual("private:u1", "intimate", cfg)
    now[0] += 11 * MIN
    assert engine.route_verdict("private:u1", cfg)["mode"] == "normal"


def test_normal_pin_does_not_eat_intimate_ttl() -> None:
    """TTL 只作用于 intimate 钉；「亲密模式 关」的 normal 钉维持既有语义
    （只受 max_ttl 硬上限/空闲重置约束），master 显式关不被时间架空。"""
    now = [100.0]
    engine = _engine(now)
    cfg = _config()
    assert engine.apply_manual("private:u1", "normal", cfg)
    now[0] += 61 * MIN
    assert engine.pinned_mode("private:u1", cfg) == "normal"


def test_group_pin_same_ttl_as_member_pin() -> None:
    """裁定 3：两个开关同一 TTL——管理员全群钉 60 分钟后同样自动退出。"""
    now = [100.0]
    engine = _engine(now)
    cfg = _config()
    group_key = "group:900"
    u1 = member_session_key(group_key, "111")
    u2 = member_session_key(group_key, "222")
    assert engine.apply_manual(group_key, "intimate", cfg)
    now[0] += 59 * MIN
    assert engine.route_verdict(u1, cfg)["mode"] == "intimate"
    assert engine.route_verdict(u2, cfg)["mode"] == "intimate"
    now[0] += 2 * MIN
    assert engine.route_verdict(u1, cfg)["mode"] == "normal"
    assert engine.route_verdict(u2, cfg)["mode"] == "normal"


# ---------------------------------------------------------------- 两级状态：并存与优先级

def test_group_pin_covers_all_members() -> None:
    now = [100.0]
    engine = _engine(now)
    cfg = _config()
    group_key = "group:901"
    assert engine.apply_manual(group_key, "intimate", cfg)
    for member in ("a", "b", "c"):
        verdict = engine.route_verdict(member_session_key(group_key, member), cfg)
        assert verdict["mode"] == "intimate"
        assert verdict["head_models"] == ["grok-4.6", "gemini-3.8-flash"]


def test_member_pin_scoped_to_self_only() -> None:
    now = [100.0]
    engine = _engine(now)
    cfg = _config()
    group_key = "group:902"
    u1 = member_session_key(group_key, "a")
    u2 = member_session_key(group_key, "b")
    assert engine.apply_manual(u1, "intimate", cfg)
    assert engine.route_verdict(u1, cfg)["mode"] == "intimate"
    assert engine.route_verdict(u2, cfg)["mode"] == "normal"
    # 开关一不泄漏到全群：群键自身判定保持 normal。
    assert engine.route_verdict(group_key, cfg)["mode"] == "normal"
    # 第三人不因 u1 的钉受影响。
    assert engine.route_verdict(member_session_key(group_key, "c"), cfg)["mode"] == "normal"


def test_group_off_does_not_suppress_member_pin() -> None:
    """设计裁定：管理员「亲密模式 关」关闭全群默认档，但不压制成员个人档
    （开关一的存在意义即个人自主；个人同意 + 群白名单环境已过外门）。"""
    now = [100.0]
    engine = _engine(now)
    cfg = _config()
    group_key = "group:903"
    u1 = member_session_key(group_key, "a")
    assert engine.apply_manual(u1, "intimate", cfg)
    assert engine.apply_manual(group_key, "normal", cfg)
    assert engine.route_verdict(u1, cfg)["mode"] == "intimate"
    # 未自拨的成员跟随全群 OFF。
    assert engine.route_verdict(member_session_key(group_key, "b"), cfg)["mode"] == "normal"


def test_member_strong_word_does_not_flip_whole_group() -> None:
    """v21r5 附带收口：L1/L2 分数在群内按成员键隔离——一个成员的露骨发言
    只切自己（旧版群共享键会整群切 grok）。"""
    now = [100.0]
    engine = _engine(now)
    cfg = _config()
    group_key = "group:904"
    u1 = member_session_key(group_key, "a")
    u2 = member_session_key(group_key, "b")
    engine.observe_turn(u1, message_text="给我讲个色情故事", config=cfg)
    assert engine.route_verdict(u1, cfg)["mode"] == "intimate"
    assert engine.route_verdict(u2, cfg)["mode"] == "normal"
    assert engine.route_verdict(group_key, cfg)["mode"] == "normal"


# ---------------------------------------------------------------- 指令分流

def test_manual_scope_key_routing() -> None:
    session_key = "group:905"
    route_key = member_session_key(session_key, "a")
    # 群管理员 → 群键（开关二）。
    assert _manual_command_scope_key(
        session_type="group", session_key=session_key, route_key=route_key,
        sender_roles=["admin"], per_user_enabled=True,
    ) == session_key
    # 群普通成员 → 本人成员键（开关一）。
    assert _manual_command_scope_key(
        session_type="group", session_key=session_key, route_key=route_key,
        sender_roles=["user"], per_user_enabled=True,
    ) == route_key
    # per_user 关闭且非管理员 → 拒绝。
    assert _manual_command_scope_key(
        session_type="group", session_key=session_key, route_key=route_key,
        sender_roles=["user"], per_user_enabled=False,
    ) is None
    # per_user 关闭但管理员仍可拨全群。
    assert _manual_command_scope_key(
        session_type="group", session_key=session_key, route_key=route_key,
        sender_roles=["admin"], per_user_enabled=False,
    ) == session_key
    # 私聊 → 本人会话键（不设角色门）。
    assert _manual_command_scope_key(
        session_type="private", session_key="private:1", route_key="private:1",
        sender_roles=["user"], per_user_enabled=True,
    ) == "private:1"


def test_match_manual_command_unchanged() -> None:
    """指令词面零改动（v21r5 只改作用域，不改触发形态）。"""
    assert match_manual_command("亲密模式 开") == "intimate"
    assert match_manual_command("开启亲密模式") == "intimate"
    assert match_manual_command("亲密模式 关") == "normal"
    assert match_manual_command("关闭亲密模式") == "normal"
    assert match_manual_command("今天天气不错") is None


# ---------------------------------------------------------------- 四名单

def test_private_lists_empty_allows_everyone() -> None:
    """白名单空=私聊亲密面默认放开（沿用既有私聊放开裁定）。"""
    cfg = _config()
    assert explicit_allowed_for_session("private", "", cfg, sender_id="10086") is True
    assert explicit_allowed_for_session("private", "", cfg, sender_id="") is True
    # 缺省 sender_id（被动好感感知旧调用面）= 行为与旧版一致。
    assert explicit_allowed_for_session("private", "", cfg) is True


def test_private_whitelist_nonempty_gates() -> None:
    cfg = _config(bot_content_route_private_whitelist=["10086", "10010"])
    assert explicit_allowed_for_session("private", "", cfg, sender_id="10086") is True
    assert explicit_allowed_for_session("private", "", cfg, sender_id="10010") is True
    assert explicit_allowed_for_session("private", "", cfg, sender_id="99999") is False
    # 空名单字段与 None 容错。
    cfg2 = _config(bot_content_route_private_whitelist=None)
    assert explicit_allowed_for_session("private", "", cfg2, sender_id="10086") is True


def test_private_blacklist_wins_over_everything() -> None:
    """黑名单永远赢：命中即关，白名单/Master Love 都压不过。"""
    cfg = _config(
        bot_content_route_private_whitelist=["10086"],
        bot_content_route_private_blacklist=["10086"],
    )
    assert explicit_allowed_for_session("private", "", cfg, sender_id="10086") is False
    # 黑名单非命中者不受影响（白名单仍放行名单内）。
    assert explicit_allowed_for_session("private", "", cfg, sender_id="10010") is False
    cfg2 = _config(bot_content_route_private_blacklist=["10086"])
    assert explicit_allowed_for_session("private", "", cfg2, sender_id="10010") is True


def test_console_not_gated_by_private_lists() -> None:
    """设计裁定：console 为运营者本地面，不参与私聊名单门。"""
    cfg = _config(bot_content_route_private_blacklist=["10086"])
    assert explicit_allowed_for_session("console", "", cfg, sender_id="10086") is True


def test_group_lists_unchanged_and_close_personal_pins() -> None:
    """群两面沿用既有键：白名单空=关闭；黑名单永远赢——群黑名单使该群
    亲密面整体关闭，个人开关也无效（resolve 层 eligible=False）。"""
    cfg = _config(
        bot_content_route_group_whitelist=["901", "902"],
        bot_content_route_group_blacklist=["902"],
    )
    assert explicit_allowed_for_session("group", "901", cfg) is True
    assert explicit_allowed_for_session("group", "902", cfg) is False
    assert explicit_allowed_for_session("group", "903", cfg) is False  # 白名单外
    assert explicit_allowed_for_session("group", "904", _config()) is False  # 空=关闭
    # 黑名单群即使成员自拨了亲密键，合成层也不放行。
    engine = _engine([100.0])
    member = member_session_key("group:902", "a")
    assert engine.apply_manual(member, "intimate", cfg)
    ctx = resolve_intimate_context(
        engine, session_type="group", group_id="902", sender_id="a",
        session_key="group:902", config=cfg,
    )
    assert ctx["eligible"] is False
    assert ctx["mode"] == "normal"


def test_master_love_cannot_beat_blacklist() -> None:
    """Master Love 压不过黑名单（裁定 4）：黑名单私聊里 ML 名单用户的
    亲密合成面整层关闭（chat 主链 master_love_here 前置条件=eligible）。"""
    engine = _engine([100.0])
    cfg = _config(
        bot_content_route_private_blacklist=["3865067623"],
    )
    ctx = resolve_intimate_context(
        engine, session_type="private", group_id="", sender_id="3865067623",
        session_key="private:3865067623", config=cfg,
    )
    assert ctx["eligible"] is False
    assert ctx["mode"] == "normal"
    # 同一用户非黑名单场景照常。
    ctx2 = resolve_intimate_context(
        engine, session_type="private", group_id="", sender_id="3865067623",
        session_key="private:3865067623", config=_config(),
    )
    assert ctx2["eligible"] is True


# ---------------------------------------------------------------- 合成函数（双门同源）

def test_resolve_route_key_member_vs_group_vs_private() -> None:
    engine = _engine([100.0])
    # 群聊 + per_user 开 → 成员派生键。
    ctx = resolve_intimate_context(
        engine, session_type="group", group_id="905", sender_id="a",
        session_key="group:905", config=_config(),
    )
    assert ctx["route_key"] == "group:905||u:a"
    # 群聊 + per_user 关 → 原群键（回到既有群级语义）。
    ctx2 = resolve_intimate_context(
        engine, session_type="group", group_id="905", sender_id="a",
        session_key="group:905",
        config=_config(bot_content_route_group_per_user_enabled=False),
    )
    assert ctx2["route_key"] == "group:905"
    # 私聊 → 原会话键。
    ctx3 = resolve_intimate_context(
        engine, session_type="private", group_id="", sender_id="u9",
        session_key="private:u9", config=_config(),
    )
    assert ctx3["route_key"] == "private:u9"


def test_resolve_mode_reflects_member_pin() -> None:
    engine = _engine([100.0])
    cfg = _config(bot_content_route_group_whitelist=["906"])
    assert engine.apply_manual("group:906||u:a", "intimate", cfg)
    ctx = resolve_intimate_context(
        engine, session_type="group", group_id="906", sender_id="a",
        session_key="group:906", config=cfg,
    )
    assert ctx["mode"] == "intimate"
    ctx_b = resolve_intimate_context(
        engine, session_type="group", group_id="906", sender_id="b",
        session_key="group:906", config=cfg,
    )
    assert ctx_b["mode"] == "normal"


def test_resolve_fail_open_on_broken_config() -> None:
    engine = _engine([100.0])

    class _Boom:
        def __getattr__(self, name: str) -> object:
            raise RuntimeError("boom")

    ctx = resolve_intimate_context(
        engine, session_type="group", group_id="1", sender_id="a",
        session_key="group:1", config=_Boom(),
    )
    assert ctx["eligible"] is False
    assert ctx["mode"] == "normal"
    assert ctx["route_key"] == "group:1"  # 键回退原会话键（安全侧）。


# ---------------------------------------------------------------- 群聊集成（build_chat_result 离线全链）

class _CapturingProvider:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    def generate(self, messages: list[dict[str, str]], **kwargs: object) -> LLMReply:
        self.messages = messages
        return LLMReply(text="嗯，我在听。你慢慢说。", provider="fake", model="m")


def _group_message(session_id: str, sender_id: str, text: str, roles: list[str]) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="bot-1",
        session_id=session_id,
        session_type=SessionType.GROUP,
        sender_id=sender_id,
        group_id=session_id.split(":", 1)[-1],
        sender_roles=roles,
        plain_text=text,
    )


def _group_decision(message: IncomingMessage) -> BotDecision:
    return BotDecision(
        request_id=message.request_id,
        should_respond=True,
        mode="chat",
        trigger="mention",
        capability_id="bot.chat",
        target_scope=SessionType.GROUP,
        privacy_level=PrivacyLevel.PERSONAL,
        risk_level=RiskLevel.LOW,
        send_policy=SendPolicy.IMMEDIATE,
        decision_reason="test",
    )


def _private_message(session_id: str, sender_id: str, text: str) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="bot-1",
        session_id=session_id,
        session_type=SessionType.PRIVATE,
        sender_id=sender_id,
        plain_text=text,
    )


def _private_decision(message: IncomingMessage) -> BotDecision:
    return BotDecision(
        request_id=message.request_id,
        should_respond=True,
        mode="chat",
        trigger="mention",
        capability_id="bot.chat",
        target_scope=SessionType.PRIVATE,
        privacy_level=PrivacyLevel.PERSONAL,
        risk_level=RiskLevel.LOW,
        send_policy=SendPolicy.IMMEDIATE,
        decision_reason="test",
    )


def _group_context(message: IncomingMessage) -> ContextBundle:
    return ContextBundle(
        request_id=message.request_id,
        persona=PersonaProfile(
            profile_id="shorekeeper",
            version="1",
            display_name="守岸人",
            identity="守岸人",
        ),
        tone=ToneProfile(profile_id="shorekeeper", mode="default"),
        memory_results=MemoryRetrievalResult(request_id=message.request_id),
        conversation_history=ConversationHistoryResult(request_id=message.request_id),
        knowledge_results=RetrievalResult(request_id=message.request_id),
        current_message=message.plain_text,
        sender_id=message.sender_id,
        session_id=message.session_id,
    )


def _system_join(provider: _CapturingProvider) -> str:
    return "\n".join(
        str(item.get("content") or "")
        for item in provider.messages
        if item.get("role") == "system"
    )


# 共享引擎是进程级单例：集成用例各自使用独立群号/会话键，防钉死态跨用例泄漏。
_GROUP = "group:v3-it-1"
_GROUP_ADMIN = "group:v3-it-2"
_GROUP_NOPU = "group:v3-it-3"
_GROUP_BL = "group:v3-it-4"


def _group_cfg(group: str = _GROUP, **overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {"bot_content_route_group_whitelist": [group.split(":", 1)[-1]]}
    base.update(overrides)
    return _config(**base)


def test_group_member_command_scopes_to_self() -> None:
    """集成：成员 A 说「亲密模式 开」→ 只 A 进亲密档；B 不受影响。"""
    cfg = _group_cfg()
    msg_a = _group_message(_GROUP, "a", "亲密模式 开", ["user"])
    result = build_chat_result(
        msg_a,
        _group_decision(msg_a),
        _group_context(msg_a),
        llm_provider=_CapturingProvider(),
        content_route_config=cfg,
    )
    assert result.body == MANUAL_ON_REPLY
    assert "scope:user" in (result.audit_tags or [])
    # A 后续消息进亲密叙述档。
    provider_a = _CapturingProvider()
    msg_a2 = _group_message(_GROUP, "a", "继续陪我聊会", ["user"])
    build_chat_result(
        msg_a2,
        _group_decision(msg_a2),
        _group_context(msg_a2),
        llm_provider=provider_a,
        content_route_config=cfg,
    )
    joined_a = _system_join(provider_a)
    assert "【亲密场景的叙述】" in joined_a
    # B 完全不受影响：普通叙述档。
    provider_b = _CapturingProvider()
    msg_b = _group_message(_GROUP, "b", "今天天气怎么样？", ["user"])
    build_chat_result(
        msg_b,
        _group_decision(msg_b),
        _group_context(msg_b),
        llm_provider=provider_b,
        content_route_config=cfg,
    )
    joined_b = _system_join(provider_b)
    assert "【日常对话的叙述】" in joined_b
    assert "【亲密场景的叙述】" not in joined_b
    # A 关闭后回到普通档。
    msg_off = _group_message(_GROUP, "a", "亲密模式 关", ["user"])
    result_off = build_chat_result(
        msg_off,
        _group_decision(msg_off),
        _group_context(msg_off),
        llm_provider=_CapturingProvider(),
        content_route_config=cfg,
    )
    assert result_off.body == MANUAL_OFF_REPLY
    provider_a3 = _CapturingProvider()
    msg_a3 = _group_message(_GROUP, "a", "继续聊", ["user"])
    build_chat_result(
        msg_a3,
        _group_decision(msg_a3),
        _group_context(msg_a3),
        llm_provider=provider_a3,
        content_route_config=cfg,
    )
    assert "【亲密场景的叙述】" not in _system_join(provider_a3)


def test_group_admin_command_scopes_to_group() -> None:
    """集成：管理员说「亲密模式 开」→ 全群（含未自拨的成员）进亲密档。"""
    cfg = _group_cfg(_GROUP_ADMIN)
    msg_admin = _group_message(_GROUP_ADMIN, "admin-1", "亲密模式 开", ["admin"])
    result = build_chat_result(
        msg_admin,
        _group_decision(msg_admin),
        _group_context(msg_admin),
        llm_provider=_CapturingProvider(),
        content_route_config=cfg,
    )
    assert result.body == MANUAL_ON_REPLY
    assert "scope:group" in (result.audit_tags or [])
    # 未自拨的普通成员也进亲密档（全群生效）。
    provider_b = _CapturingProvider()
    msg_b = _group_message(_GROUP_ADMIN, "b", "今天吃什么好", ["user"])
    build_chat_result(
        msg_b,
        _group_decision(msg_b),
        _group_context(msg_b),
        llm_provider=provider_b,
        content_route_config=cfg,
    )
    joined = _system_join(provider_b)
    assert "【亲密场景的叙述】" in joined


def test_group_member_command_rejected_when_per_user_disabled() -> None:
    """per_user=False：成员指令不受理（无 MANUAL 回执，落普通聊天），且
    群内任何人都不因该指令进亲密档。"""
    cfg = _group_cfg(_GROUP_NOPU, bot_content_route_group_per_user_enabled=False)
    msg_a = _group_message(_GROUP_NOPU, "a", "亲密模式 开", ["user"])
    provider = _CapturingProvider()
    result = build_chat_result(
        msg_a,
        _group_decision(msg_a),
        _group_context(msg_a),
        llm_provider=provider,
        content_route_config=cfg,
    )
    assert result.body != MANUAL_ON_REPLY  # 未被开关指令受理
    joined = _system_join(provider)
    assert "【日常对话的叙述】" in joined  # 落普通聊天
    assert INTIMATE_RP_STYLE_INSTRUCTION not in joined
    assert NORMAL_NO_ACTION_INSTRUCTION in joined


def test_group_blacklisted_group_closes_intimacy_face() -> None:
    """集成（黑名单群）：黑名单优先——即使白名单也命中该群，成员与管理员
    的亲密开关全部无效，prompt 恒为普通叙述档。"""
    group_id = _GROUP_BL.split(":", 1)[-1]
    cfg = _config(
        bot_content_route_group_whitelist=[group_id],
        bot_content_route_group_blacklist=[group_id],
    )
    msg_a = _group_message(_GROUP_BL, "a", "亲密模式 开", ["user"])
    provider = _CapturingProvider()
    result = build_chat_result(
        msg_a,
        _group_decision(msg_a),
        _group_context(msg_a),
        llm_provider=provider,
        content_route_config=cfg,
    )
    assert result.body != MANUAL_ON_REPLY  # 面都关了，指令不受理
    assert "【亲密场景的叙述】" not in _system_join(provider)


def test_private_blacklist_blocks_intimacy_end_to_end() -> None:
    """集成（黑名单私聊）：名单内用户被关亲密面——钉死无效、prompt 恒普通。"""
    cfg = _config(bot_content_route_private_blacklist=["blocked-u"])
    session = "private:blocked-u"
    msg = _private_message(session, "blocked-u", "亲密模式 开")
    provider = _CapturingProvider()
    result = build_chat_result(
        msg,
        _private_decision(msg),
        _group_context(msg),
        llm_provider=provider,
        content_route_config=cfg,
    )
    assert result.body != MANUAL_ON_REPLY  # 黑名单：指令不受理
    assert "【亲密场景的叙述】" not in _system_join(provider)
    assert NORMAL_NO_ACTION_INSTRUCTION in _system_join(provider)
    # 对照组：非黑名单用户私聊照常可拨。
    cfg_ok = _config()
    msg_ok = _private_message("private:free-u", "free-u", "亲密模式 开")
    result_ok = build_chat_result(
        msg_ok,
        _private_decision(msg_ok),
        _group_context(msg_ok),
        llm_provider=_CapturingProvider(),
        content_route_config=cfg_ok,
    )
    assert result_ok.body == MANUAL_ON_REPLY
