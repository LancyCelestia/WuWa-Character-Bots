"""亲密档 v4 的**接线席**（2026-09-24 裁定 R1/R2/R3/R6 落到 chat 主链）。

档位判据、关系词表、TTL 语义本身已由 `tests/test_intimate_tiers_v4.py` 与
`tests/test_relationships.py` 锁住；本文件只锁 **`capabilities/chat.py` 真的把中央件
接上了、且没有第二套判据**：

① 深浅两档的命令接线（`match_intimate_command` → `apply_manual(tier=…)` → 三句回话）；
② 好感度自动腿（浅档、绝不换模型、只给"从未被钉过"的会话上钉 ⇒ TTL 起点不被续期）；
③ 关系档注入（只在亲密档成立的那几轮注入；Master Love 走词表 `master` 同一格，
   同一条注入路零第二份同义文本）；
④ R6 时序泄露根修（装配期用 `verdict_with_pending_turn` 预览"本轮真会换头吗"，
   媒体据此走转译，而不是把原生件挂给即将上台的零声明首跳）；
⑤ 一轮只记一次账（预览不落账 ⇒ `observe_turn` 每轮恰一次）。

夹具纪律（沿用 S40/S42 同一套）：会话键只由中央件产出；档只由**真入口**产生
（说一句指令、或让自动腿自己钉上），测试不手写 `apply_manual` 伪造档；好感度与
关系档都用 **真 store**（tmp_path 下的 SQLite，走既有取数口），零网络、零真实 LLM。
"""
from __future__ import annotations

import ast
import copy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

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
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
    build_chat_capability,
    build_chat_result,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.addressing import (
    AddressingPreferenceStore,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
    DynamicAffinityStore,
    tier_for_affinity,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
    NullCharacterContextProvider,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.relationships import (
    normalize_relationship,
    relation_instruction,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router import (
    ModelRouter,
    ModelSpec,
    native_media_kinds_in_payload,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
    StaticLLMProvider,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.content_route import (
    INTIMATE_SOURCE_AFFINITY,
    INTIMATE_SOURCE_MANUAL,
    INTIMATE_SOURCE_MASTER_LOVE,
    INTIMATE_SOURCE_NONE,
    INTIMATE_TIER_L1,
    INTIMATE_TIER_L2,
    INTIMATE_TIER_NONE,
    MANUAL_DEEP_ON_REPLY,
    MANUAL_OFF_REPLY,
    MANUAL_ON_REPLY,
    MASTER_LOVE_INSTRUCTION,
    SHARED_CONTENT_ROUTE_ENGINE,
)
from plugins.bot_unified_runtime.domains.core.session_keys import (
    build_session_key,
    private_session_key,
)
from plugins.bot_unified_runtime.llm import LLMProviderError
from plugins.bot_unified_runtime.llm.providers import LLMReply

MINUTE = 60.0
_REPO_ROOT = Path(__file__).resolve().parents[1]

# 生产形状的两跳链：默认链首 gemini（声明三种原生媒体）+ grok（一个都不声明）。
# 依据是 2026-09-23 实测：grok 收 video_url 返回 200 却答"没有附带任何视频"。
_GEMINI_TAGS = ("vision", "native-audio", "native-video", "native-animation")
_GROK_TAGS = ("high",)


def _config(**overrides: object) -> SimpleNamespace:
    """内容路由配置面（键名与 `Config` 一致，值取生产缺省）。"""
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
        "bot_content_route_l1_auto_enabled": True,
        "bot_content_route_l1_auto_min_tier": 1,
        "bot_master_love_enabled": False,
        "bot_master_love_admins": [],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class _CapturingProvider:
    """离线 LLM 替身：把这一轮真正发出去的 messages 留下账。"""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    def generate(self, messages: list[dict[str, Any]], **kwargs: object) -> LLMReply:
        self.messages = copy.deepcopy(list(messages))
        return LLMReply(text="嗯，我在听。你慢慢说。", provider="fake", model="m")


def _system_join(provider: _CapturingProvider) -> str:
    return "\n".join(
        str(item.get("content") or "")
        for item in provider.messages
        if item.get("role") == "system"
    )


def _private_message(
    uid: str, text: str, segments: list | None = None
) -> IncomingMessage:
    key = private_session_key(uid)
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="bot-1",
        session_id=key,
        session_type=SessionType.PRIVATE,
        sender_id=uid,
        plain_text=text,
        raw_segments=list(segments or []),
    )


def _decision(message: IncomingMessage) -> BotDecision:
    return BotDecision(
        request_id=message.request_id,
        should_respond=True,
        mode="chat",
        trigger="private",
        capability_id="bot.chat",
        target_scope=message.session_type,
        privacy_level=PrivacyLevel.PERSONAL,
        risk_level=RiskLevel.LOW,
        send_policy=SendPolicy.IMMEDIATE,
        decision_reason="test",
    )


def _context(message: IncomingMessage) -> ContextBundle:
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


def _private_turn(
    uid: str, text: str, cfg: SimpleNamespace, **kwargs: object
):
    """真入口跑一条私聊消息（指令 / 自动钉 / 注入都发生在它里面）。"""
    message = _private_message(uid, text)
    provider = _CapturingProvider()
    result = build_chat_result(
        message,
        _decision(message),
        _context(message),
        llm_provider=provider,
        content_route_config=cfg,
        **kwargs,  # type: ignore[arg-type]
    )
    return result, provider, private_session_key(uid)


def _verdict(key: str, cfg: SimpleNamespace) -> dict[str, Any]:
    return SHARED_CONTENT_ROUTE_ENGINE.route_verdict(key, cfg)


# ========================================================== ① 深浅两档的命令接线


def test_shallow_command_pins_shallow_tier_and_never_switches_the_head() -> None:
    """「亲密模式 开」= 浅档：档成立（语气与放行照给），默认模型**不换**。

    这是 2026-09-24 R3 A 的行为改道：改前这一句会把真实首跳换成 grok。
    """
    cfg = _config()

    result, _provider, key = _private_turn("960000001", "亲密模式 开", cfg)

    assert result.body == MANUAL_ON_REPLY
    assert "tier:l1" in (result.audit_tags or []), result.audit_tags
    verdict = _verdict(key, cfg)
    assert verdict["mode"] == "intimate"
    assert verdict["tier"] == INTIMATE_TIER_L1
    assert verdict["source"] == INTIMATE_SOURCE_MANUAL
    assert verdict["head_models"] == [], "浅档把真实首跳换掉了 ⇒ tier 没交给 apply_manual"


def test_deep_command_pins_deep_tier_and_switches_the_head() -> None:
    """「亲密模式 深开」= 深档：回话与浅档不同句，且 grok 头插恢复。"""
    cfg = _config()

    result, _provider, key = _private_turn("960000002", "亲密模式 深开", cfg)

    assert result.body == MANUAL_DEEP_ON_REPLY
    assert "tier:l2" in (result.audit_tags or []), result.audit_tags
    verdict = _verdict(key, cfg)
    assert verdict["tier"] == INTIMATE_TIER_L2
    assert verdict["head_models"][0] == "grok-4.6"


def test_off_command_clears_both_tiers() -> None:
    """「亲密模式 关」两档一起解除：钉、来源、档位、头插全部回空。"""
    uid = "960000003"
    cfg = _config()

    _private_turn(uid, "亲密模式 深开", cfg)
    assert _verdict(private_session_key(uid), cfg)["tier"] == INTIMATE_TIER_L2
    result, _provider, key = _private_turn(uid, "亲密模式 关", cfg)

    assert result.body == MANUAL_OFF_REPLY
    verdict = _verdict(key, cfg)
    assert verdict["mode"] == "normal"
    assert verdict["tier"] == INTIMATE_TIER_NONE
    assert verdict["source"] == INTIMATE_SOURCE_NONE
    assert verdict["head_models"] == []


def test_the_three_ack_texts_are_pairwise_distinct() -> None:
    """三句回话互不相同（防把深浅两档接到同一句常量上——那样档位就看不见了）。"""
    assert len({MANUAL_ON_REPLY, MANUAL_DEEP_ON_REPLY, MANUAL_OFF_REPLY}) == 3


# ================================================== ② 好感度自动腿（L1 对所有用户）


def _seeded_affinity(tmp_path, uid: str) -> DynamicAffinityStore:
    """真 store + 真写入路径把好感度抬到缺省门槛（+1「亲近」）及以上。

    每次入账之间把时钟推过 24 小时：滚动预算会把单日增益钳住，不推钟就抬不到档
    （抬不动时下面的前提自证会当场红，而不是让用例悄悄变成空跑）。
    """
    now = [1_700_000_000.0]
    store = DynamicAffinityStore(
        tmp_path / f"affinity-{uid}.sqlite3", clock=lambda: now[0]
    )
    for _ in range(6):
        store.observe_points(uid, 20.0, behavior="warm")
        now[0] += 25 * 3600.0
    snapshot = store.snapshot(uid)
    # 前提自证：读数确实够格（不够格就是夹具在骗人，不是代码对）。
    assert int(snapshot["tier"]) >= 1, snapshot
    assert int(snapshot["tier"]) == tier_for_affinity(float(snapshot["affinity"]))
    return store


def test_affinity_leg_grants_shallow_tier_without_changing_the_model(tmp_path) -> None:
    """R1 A：好感度达标的普通用户自动进**浅档**，且绝不换模型。"""
    uid = "960000101"
    cfg = _config()
    store = _seeded_affinity(tmp_path, uid)

    _private_turn(uid, "今天也辛苦啦", cfg, affinity_store=store)

    verdict = _verdict(private_session_key(uid), cfg)
    assert verdict["mode"] == "intimate", verdict
    assert verdict["source"] == INTIMATE_SOURCE_AFFINITY, verdict
    assert verdict["tier"] == INTIMATE_TIER_L1, verdict
    assert verdict["head_models"] == [], "好感度自动腿换模型了（裁定明令禁止）"


def test_affinity_leg_does_not_repso_the_ttl_origin_survives(tmp_path, monkeypatch) -> None:
    """第二条消息**不再重钉**：TTL 起点仍是第一次进档的时刻（S40-D2 同型教训）。

    守卫必须是 `pinned_mode(key) is None`。若退化成 `!= "normal"`，每条消息都会重钉
    并把 `activated_at` 归零 ⇒ 第 61 分钟这一格仍然 intimate ⇒ 本用例当场红。
    """
    uid = "960000102"
    cfg = _config()
    store = _seeded_affinity(tmp_path, uid)
    now = [1000.0]
    monkeypatch.setattr(SHARED_CONTENT_ROUTE_ENGINE, "clock", lambda: now[0])
    key = private_session_key(uid)

    _private_turn(uid, "早", cfg, affinity_store=store)
    assert _verdict(key, cfg)["source"] == INTIMATE_SOURCE_AFFINITY

    now[0] += 59 * MINUTE
    _private_turn(uid, "午安", cfg, affinity_store=store)  # 常规流量：不得续期
    now[0] += 2 * MINUTE  # 距**首次进档** 61 分钟
    assert _verdict(key, cfg)["mode"] == "normal", (
        "好感度自动腿每条消息重钉 ⇒ TTL 起点被续期（S40-D2 同型缺陷复开）"
    )


@pytest.mark.parametrize(
    ("uid", "overrides", "rounds", "want_pinned"),
    [
        ("960000201", {}, 6, True),  # 缺省：开关开、门槛 +1、够格
        ("960000202", {"bot_content_route_l1_auto_enabled": False}, 6, False),  # 总闸关
        ("960000203", {"bot_content_route_l1_auto_min_tier": 3}, 6, False),  # 门槛更高
        ("960000204", {"bot_content_route_l1_auto_min_tier": -4}, 0, True),  # 未建档也放行
    ],
)
def test_affinity_leg_reads_its_two_knobs_from_the_central_table(
    tmp_path, uid: str, overrides: dict[str, object], rounds: int, want_pinned: bool
) -> None:
    """两个 knob 只有一个读点（引擎 `_knobs`）：关闸或门槛不符时整条自动腿不动。"""
    cfg = _config(**overrides)
    now = [1_700_000_000.0]
    store = DynamicAffinityStore(
        tmp_path / f"aff-{uid}.sqlite3", clock=lambda: now[0]
    )
    for _ in range(rounds):
        store.observe_points(uid, 20.0, behavior="warm")
        now[0] += 25 * 3600.0

    _private_turn(uid, "在吗", cfg, affinity_store=store)

    verdict = _verdict(private_session_key(uid), cfg)
    assert (verdict["source"] == INTIMATE_SOURCE_AFFINITY) is want_pinned, verdict
    if want_pinned:
        assert verdict["tier"] == INTIMATE_TIER_L1
        assert verdict["head_models"] == []
    else:
        assert verdict["mode"] == "normal"


def test_affinity_leg_never_overrides_an_existing_pin(tmp_path) -> None:
    """已显式深开的会话：自动腿不重钉（来源与档位都归那一支显式指令）。"""
    uid = "960000103"
    cfg = _config()
    store = _seeded_affinity(tmp_path, uid)
    key = private_session_key(uid)

    _private_turn(uid, "亲密模式 深开", cfg, affinity_store=store)
    _private_turn(uid, "在吗", cfg, affinity_store=store)

    verdict = _verdict(key, cfg)
    assert verdict["source"] == INTIMATE_SOURCE_MANUAL, verdict
    assert verdict["tier"] == INTIMATE_TIER_L2, verdict
    assert verdict["head_models"], "显式深档被自动腿降下来了"


def test_affinity_leg_needs_a_reading_point_and_the_session_gate(tmp_path) -> None:
    """没有好感度读点（store=None）= 不上钉；未获准的群会话同样不动。"""
    uid = "960000104"
    cfg = _config()
    _private_turn(uid, "在吗", cfg)
    assert _verdict(private_session_key(uid), cfg)["mode"] == "normal"

    store = _seeded_affinity(tmp_path, uid)
    group_id = "9600001040"
    message = IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="bot-1",
        session_id=build_session_key(group_id, uid),
        session_type=SessionType.GROUP,
        sender_id=uid,
        group_id=group_id,
        sender_roles=["user"],
        plain_text="在吗",
    )
    build_chat_result(
        message,
        _decision(message),
        _context(message),
        llm_provider=_CapturingProvider(),
        affinity_store=store,
        # 群白名单为空 = 群聊亲密面整体关闭（绝不猜群）⇒ 自动腿也不该上钉。
        content_route_config=_config(bot_content_route_group_whitelist=[]),
    )
    verdict = _verdict(build_session_key(group_id, uid), cfg)
    assert verdict["mode"] == "normal", verdict
    assert verdict["source"] == INTIMATE_SOURCE_NONE


# =============================================================== ③ 关系档注入


def _declare_relationship(tmp_path, cfg: SimpleNamespace, uid: str, raw: str) -> str:
    """把关系档写进**真**称谓偏好库，返回落档的 canon id。

    键位与 `/bot identity` 完全一致（私聊 session_id 为空），否则设在一处、读在另一处。
    """
    db_path = tmp_path / f"addr-{uid}.sqlite3"
    cfg.bot_addressing_preferences_db_path = str(db_path)
    store = AddressingPreferenceStore(db_path)
    try:
        canon = store.set_relationship(
            session_type="private", session_id="", sender_id=uid, relationship=raw
        )
        assert canon and canon == normalize_relationship(raw), canon
        return canon
    finally:
        store._conn.close()


def test_relationship_tone_is_injected_only_while_the_tier_holds(
    tmp_path, monkeypatch
) -> None:
    """关系语气只在**亲密档成立**的那几轮注入；到点退出后必须消失。

    判据复用 `resolve_intimate_context` 的 mode——旧写法 `pinned_mode(...) != "normal"`
    会在过期那一刻起"路由按普通走、恋人语气照注入"（09-24 复核点名的形态）。
    """
    uid = "960000301"
    cfg = _config(bot_content_route_l1_auto_enabled=False)
    canon = _declare_relationship(tmp_path, cfg, uid, "恋人")
    assert canon == "lover"
    now = [2000.0]
    monkeypatch.setattr(SHARED_CONTENT_ROUTE_ENGINE, "clock", lambda: now[0])

    _private_turn(uid, "亲密模式 开", cfg)  # 浅档：不换模型，但档成立
    _result, provider, key = _private_turn(uid, "和你说说话", cfg)
    assert _verdict(key, cfg)["mode"] == "intimate"
    joined = _system_join(provider)
    assert relation_instruction("lover") in joined, "档成立的轮次没注入关系语气"
    assert joined.count("【当前关系") == 1, "同一条注入路出现了两份关系文本"

    now[0] += 61 * MINUTE  # 浅档 TTL 到点
    _result2, provider2, _key2 = _private_turn(uid, "我回来啦", cfg)
    assert relation_instruction("lover") not in _system_join(provider2), (
        "档已过期仍在注入关系语气 ⇒ 注入判据与 resolve_intimate_context 不同源"
    )


def test_relationship_is_not_injected_for_normal_turns(tmp_path) -> None:
    """反向格（防"设过关系就永远灌注"）：未进档的轮次一个字都不注入。"""
    uid = "960000302"
    cfg = _config(bot_content_route_l1_auto_enabled=False)
    _declare_relationship(tmp_path, cfg, uid, "夫妻")

    _result, provider, key = _private_turn(uid, "今天天气怎么样", cfg)

    assert _verdict(key, cfg)["mode"] == "normal"
    assert relation_instruction("spouse") not in _system_join(provider)


def test_master_love_uses_the_same_relation_path_and_yields_one_text(tmp_path) -> None:
    """ML 与词表同路：没自设关系时 ML 落 `master` 那一格，逐字仍是原句且只出现一次。"""
    uid = "960000303"
    cfg = _config(
        bot_master_love_enabled=True,
        bot_master_love_admins=[uid],
        bot_content_route_l1_auto_enabled=False,
    )
    cfg.bot_addressing_preferences_db_path = str(tmp_path / f"addr-{uid}.sqlite3")

    _private_turn(uid, "在吗", cfg)
    _result, provider, key = _private_turn(uid, "想你啦", cfg)

    assert _verdict(key, cfg)["source"] == INTIMATE_SOURCE_MASTER_LOVE
    joined = _system_join(provider)
    assert MASTER_LOVE_INSTRUCTION in joined
    assert joined.count("【当前对话对象") == 1, joined
    assert joined.count("【当前关系") == 0, "ML 会话被同时灌了两份同义关系文本"


def test_self_declared_relationship_wins_over_master_love(tmp_path) -> None:
    """本人显式自设的关系压过 ML 缺省格：同一条路上只有一份文本，且是他选的那一格。"""
    uid = "960000304"
    cfg = _config(
        bot_master_love_enabled=True,
        bot_master_love_admins=[uid],
        bot_content_route_l1_auto_enabled=False,
    )
    canon = _declare_relationship(tmp_path, cfg, uid, "妈妈")
    assert canon == "parent"

    _result, provider, key = _private_turn(uid, "回家啦", cfg)

    assert _verdict(key, cfg)["mode"] == "intimate"
    joined = _system_join(provider)
    assert relation_instruction("parent") in joined
    assert MASTER_LOVE_INSTRUCTION not in joined, "ML 缺省格压过了本人自设的关系"
    assert joined.count("【当前") == 1, joined


def test_unreadable_relationship_store_never_breaks_the_chain(tmp_path) -> None:
    """关系库打不开（路径指向目录 → sqlite connect 失败 → 取数口回 None）：
    关系面整段 fail-open——不注入、不抛、正文照回。"""
    uid = "960000305"
    cfg = _config(bot_content_route_l1_auto_enabled=False)
    cfg.bot_addressing_preferences_db_path = str(tmp_path)  # 一枚目录，开不出库

    _private_turn(uid, "亲密模式 开", cfg)
    result, provider, key = _private_turn(uid, "随便聊聊", cfg)

    assert _verdict(key, cfg)["mode"] == "intimate", "档本身不该被关系面的故障带走"
    assert result.body.strip()
    joined = _system_join(provider)
    assert "【当前关系" not in joined
    assert "【当前对话对象" not in joined


# ============================================== ④ R6 时序泄露根修（装配期预览）


def _spec(model_id: str, priority: int, *tags: str) -> ModelSpec:
    return ModelSpec(
        model_id=model_id,
        model=model_id,
        base_url="https://example.test/v1",
        api_key="key",
        tags=tags,
        priority=priority,
    )


def _failing_factory(journal: list):
    """provider 替身：记下该跳**真正收到**的 messages，再以可转移错误失败（逼出第二跳）。

    用 `error_kind="server"`（在册可转移类）而非网络类，免得链级 fail-fast 把
    "第二跳收到了什么"这一幕直接抹掉＝假绿。
    """

    def factory(spec: ModelSpec):
        def generate(messages, **kwargs):
            journal.append((spec.model_id, copy.deepcopy(list(messages))))
            raise LLMProviderError("hop failed", error_kind="server")

        return SimpleNamespace(generate=generate)

    return factory


def _chain_router(cfg: SimpleNamespace, journal: list) -> ModelRouter:
    return ModelRouter(
        {
            "gemini-3.8-flash": _spec("gemini-3.8-flash", 1, *_GEMINI_TAGS),
            "grok-4.6": _spec("grok-4.6", 2, *_GROK_TAGS),
        },
        provider_factory=_failing_factory(journal),
        content_route_cb=(
            lambda key, text: SHARED_CONTENT_ROUTE_ENGINE.route_verdict(key, cfg)
        ),
        max_failover_seconds=0.0,
    )


class _RecordingAsrProvider:
    def __init__(self, transcript: str) -> None:
        self.transcript = transcript
        self.calls: list[str] = []

    def generate(self, audio_bytes: bytes, filename: str, **kwargs: object) -> str:
        self.calls.append(filename)
        return self.transcript


class _ModelOverrideSettings:
    """runtime_settings 替身：只把 BOT_CHAT_MODEL 顶成管理员指定的那一跳。"""

    def __init__(self, model: str) -> None:
        self.model = model

    def get_or(self, key: str, default: Any = None) -> Any:
        if key == "BOT_CHAT_MODEL":
            return self.model
        return default


def _voice_segments(tmp_path) -> list:
    clip = tmp_path / "voice.mp3"
    clip.write_bytes(b"ID3\x04" + b"\x00" * 128)
    return [{"type": "record", "data": {"file": str(clip)}}]


def _run_media_turn(
    cfg: SimpleNamespace,
    uid: str,
    text: str,
    segments: list,
    journal: list,
    **capability_kwargs: object,
) -> None:
    capability = build_chat_capability(
        NullCharacterContextProvider(),
        StaticLLMProvider(text="不该被用到"),
        model_router=_chain_router(cfg, journal),
        content_route_config=cfg,
        **capability_kwargs,  # type: ignore[arg-type]
    )
    message = _private_message(uid, text, segments)
    capability(message, _decision(message))


def _hop_texts(journal: list, model_id: str) -> list[str]:
    out: list[str] = []
    for hop_id, messages in journal:
        if hop_id != model_id:
            continue
        for item in messages:
            content = item.get("content")
            if isinstance(content, str):
                out.append(content)
            elif isinstance(content, list):
                out.extend(
                    str(part.get("text", ""))
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                )
    return out


def test_same_round_strong_word_with_voice_goes_to_translation(tmp_path) -> None:
    """**R6 主锁**：本轮强词刚跨过阈值 + 这条消息带语音 ⇒ 语音走转译，不挂原生。

    改码前的形态：装配门按"还没记账"的默认链首答"能原生吃" ⇒ 部件挂上、ASR 让路 ⇒
    真实首跳换成零声明的 grok ⇒ 逐跳裁件把音频裁掉 ⇒ 她没听见、用户侧零报错。
    """
    uid = "960000401"
    cfg = _config()
    journal: list = []
    asr = _RecordingAsrProvider("明天的天气怎么样")

    _run_media_turn(
        cfg,
        uid,
        "和我做爱前先听听这段",
        _voice_segments(tmp_path),
        journal,
        asr_provider=asr,
        asr_enabled=True,
    )

    # 前提自证：这一轮真实首跳真的被换掉了（否则本用例只是空跑）。
    assert journal and journal[0][0] == "grok-4.6", journal
    assert _verdict(private_session_key(uid), cfg)["head_models"], "预览与真实判定不一致"
    # 判据：零声明的首跳**没有**收到原生音频，而转译真的跑了。
    assert "audio" not in native_media_kinds_in_payload(journal[0][1]), (
        "本轮换头却把原生音频挂给了即将上台的零声明首跳（R6 时序泄露）"
    )
    assert asr.calls, "音频既没原生送达也没转写 ⇒ 内容彻底丢失"
    assert any(asr.transcript in text for text in _hop_texts(journal, "grok-4.6"))


def test_preview_and_accounted_verdict_agree(tmp_path, monkeypatch) -> None:
    """装配期预览与生成期真实判定**逐字段一致**（两问一处答，不许第二套判据）。"""
    uid = "960000402"
    cfg = _config()
    journal: list = []
    recorded: dict[str, dict[str, Any]] = {}
    real_preview = SHARED_CONTENT_ROUTE_ENGINE.verdict_with_pending_turn

    def _spy(session_key: str, **kwargs: object) -> dict[str, Any]:
        verdict = real_preview(session_key, **kwargs)  # type: ignore[arg-type]
        recorded.setdefault("preview", dict(verdict))
        return verdict

    monkeypatch.setattr(SHARED_CONTENT_ROUTE_ENGINE, "verdict_with_pending_turn", _spy)
    _run_media_turn(
        cfg,
        uid,
        "和我做爱",
        _voice_segments(tmp_path),
        journal,
        asr_provider=_RecordingAsrProvider("一句转写"),
        asr_enabled=True,
    )

    assert "preview" in recorded, "装配期根本没调用预览口 ⇒ 本用例是空跑"
    preview = recorded["preview"]
    real = _verdict(private_session_key(uid), cfg)
    assert {k: str(preview.get(k)) for k in ("mode", "tier", "source")} == {
        k: str(real.get(k)) for k in ("mode", "tier", "source")
    }
    assert list(preview.get("head_models") or []) == list(real["head_models"])


def test_shallow_pinned_voice_still_goes_native(tmp_path) -> None:
    """反向格（防过修成"干脆别原生"）：浅档不换头 ⇒ 语音照旧原生送达、ASR 让路。"""
    uid = "960000403"
    cfg = _config()
    journal: list = []
    asr = _RecordingAsrProvider("这句话不该被转写")

    _run_media_turn(cfg, uid, "亲密模式 开", [], journal)
    _run_media_turn(
        cfg,
        uid,
        "听听这个",
        _voice_segments(tmp_path),
        journal,
        asr_provider=asr,
        asr_enabled=True,
    )

    assert _verdict(private_session_key(uid), cfg)["tier"] == INTIMATE_TIER_L1
    assert journal, "一次请求都没发出：本用例退化成空跑"
    assert journal[0][0] == "gemini-3.8-flash"
    assert "audio" in native_media_kinds_in_payload(journal[0][1])
    assert asr.calls == [], "浅档会话被拖回落 ASR ⇒ 预览判据放宽过头"


def test_pending_switch_without_translation_still_mounts_the_part(tmp_path) -> None:
    """教义不放宽：本轮要换头但**转译也不可用**时，唯一允许的"剥掉"一档仍须把部件
    挂在请求体上，让故障转移去兜（声明过的那一跳真的收到它），而不是把内容变没。"""
    uid = "960000404"
    cfg = _config()
    journal: list = []

    _run_media_turn(cfg, uid, "和我做爱，听听这段", _voice_segments(tmp_path), journal)

    hops = [hop for hop, _ in journal]
    assert hops == ["grok-4.6", "gemini-3.8-flash"], hops
    assert "audio" not in native_media_kinds_in_payload(journal[0][1])
    assert any("未送达" in text for text in _hop_texts(journal, "grok-4.6")), (
        "裁件没留痕迹 ⇒ 首跳会自信地臆答它没收到的附件"
    )
    assert "audio" in native_media_kinds_in_payload(journal[1][1]), (
        "音频既没原生送达也没转译 ⇒ 内容静默丢失"
    )


def test_admin_override_never_lets_the_preview_change_the_media_answer(tmp_path) -> None:
    """管理员 override 分支本就不吃内容路由 ⇒ 预览在那一格必须闭嘴。

    若这里也按预览压掉原生，就把"override 指定的那一跳声明过"这条既有语义改掉了。
    """
    uid = "960000405"
    cfg = _config()
    journal: list = []
    asr = _RecordingAsrProvider("不必转写")

    _run_media_turn(
        cfg,
        uid,
        "和我做爱，听听这段",
        _voice_segments(tmp_path),
        journal,
        asr_provider=asr,
        asr_enabled=True,
        runtime_settings=_ModelOverrideSettings("gemini-3.8-flash"),
    )

    assert journal, "一次请求都没发出：本用例退化成空跑"
    assert journal[0][0] == "gemini-3.8-flash"
    assert "audio" in native_media_kinds_in_payload(journal[0][1])


# ============================================== ⑤ 一轮只记一次账（预览不落账）


def test_one_turn_accounts_signals_exactly_once(tmp_path, monkeypatch) -> None:
    """预览必须**不落账**：同一轮里 `observe_turn` 恰调用一次，且预览口真的被走过。"""
    uid = "960000501"
    cfg = _config()
    journal: list = []
    counts = {"observe": 0, "preview": 0}
    real_observe = SHARED_CONTENT_ROUTE_ENGINE.observe_turn
    real_preview = SHARED_CONTENT_ROUTE_ENGINE.verdict_with_pending_turn

    def _observe(session_key: str, **kwargs: object) -> None:
        counts["observe"] += 1
        real_observe(session_key, **kwargs)  # type: ignore[arg-type]

    def _preview(session_key: str, **kwargs: object) -> dict[str, Any]:
        counts["preview"] += 1
        return real_preview(session_key, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(SHARED_CONTENT_ROUTE_ENGINE, "observe_turn", _observe)
    monkeypatch.setattr(SHARED_CONTENT_ROUTE_ENGINE, "verdict_with_pending_turn", _preview)

    _run_media_turn(
        cfg,
        uid,
        "和我做爱，听听这段",
        _voice_segments(tmp_path),
        journal,
        asr_provider=_RecordingAsrProvider("一句转写"),
        asr_enabled=True,
    )

    assert counts["preview"] >= 1, "装配期没走预览口 ⇒ 计数断言成了空跑"
    assert counts["observe"] == 1, f"一轮记了 {counts['observe']} 次账（信号被重复计分）"


def test_chat_capability_still_forwards_the_affinity_store() -> None:
    """装配可达性锁：好感度读点必须真的从能力层透到 `build_chat_result`。

    本波才让 `affinity_store` 在 `build_chat_result` 里被真正使用（此前只是形参）；
    删掉能力层那一行转发，② 的整条自动腿在生产链路上就永远拿不到读数。
    """
    source = (
        _REPO_ROOT
        / "plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py"
    ).read_text(encoding="utf-8")
    forwarded = 0
    for node in ast.walk(ast.parse(source)):
        is_chat_result_call = (
            isinstance(node, ast.Call)
            and getattr(node.func, "id", "") == "build_chat_result"
        )
        if is_chat_result_call and any(
            k.arg == "affinity_store" for k in node.keywords
        ):
            forwarded += 1
    assert forwarded >= 1, "build_chat_capability 不再把 affinity_store 交给 build_chat_result"


# ================================= ⑤ 群内带 @ 前缀的命令必须照样落档（用户令修的那扇窗）


def _mentioned_message(uid: str, plain: str, command: str) -> IncomingMessage:
    """照生产形态造一条"先 @ 她再说指令"的消息：`plain_text` 含 @ 文本，
    `command_text` 是摄取层用中央件 `strip_leading_name_mention` 派生出的指令文本。"""
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="bot-1",
        session_id=private_session_key(uid),
        session_type=SessionType.PRIVATE,
        sender_id=uid,
        plain_text=plain,
        command_text=command,
        raw_segments=[],
    )


def test_at_prefixed_command_still_lands_on_the_deep_tier() -> None:
    """`@守岸人 亲密模式 深开` 若仍拿 `plain_text` 去匹配 ⇒ 永远不命中（锚在句首句尾）。
    命令匹配必须改吃 `command_text`，中央件与契约字段才算真接上。"""
    uid = "u-at-deep"
    key = private_session_key(uid)
    cfg = _config()
    message = _mentioned_message(uid, "@守岸人 亲密模式 深开", "亲密模式 深开")
    build_chat_result(
        message,
        _decision(message),
        _context(message),
        llm_provider=_CapturingProvider(),
        content_route_config=cfg,
    )
    verdict = _verdict(key, cfg)
    assert verdict["mode"] == "intimate"
    assert verdict["tier"] == INTIMATE_TIER_L2
    assert verdict["head_models"][:1] == ["grok-4.6"]


def test_command_text_absent_falls_back_to_plain_text() -> None:
    """派生字段缺席（旧构造面/未过摄取层的自造消息）时必须回退 `plain_text`，
    否则私聊那条路会被这次修复打断。"""
    uid = "u-at-fallback"
    key = private_session_key(uid)
    cfg = _config()
    message = _mentioned_message(uid, "亲密模式 开", "")
    build_chat_result(
        message,
        _decision(message),
        _context(message),
        llm_provider=_CapturingProvider(),
        content_route_config=cfg,
    )
    verdict = _verdict(key, cfg)
    assert verdict["mode"] == "intimate"
    assert verdict["tier"] == INTIMATE_TIER_L1
