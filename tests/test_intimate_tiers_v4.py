"""亲密档分级 v4（2026-09-24 用户裁定六条）：档位带**深浅两档**，只有深档换模型。

覆盖的裁定，逐条对应本文件一节：
- R1 A：L1 的自动腿按好感度档派生（新来源 ``affinity_tier``），且**不换模型**。
- R3 A：「亲密模式 开」= 浅档 L1（不换模型）；「亲密模式 深开」= 深档 L2（grok 优先）；
        「亲密模式 关」两档一起关。**这是行为改道**：改前「亲密模式 开」=换 grok。
- R4 A：显式开/管理员钉这两支**不受 ``max_ttl`` 120 分钟封顶**（长 TTL 配多少就是多少）；
        自动信号那支与非亲密钉仍受其约束。
- 不换模型的那一档照旧给语气与放行（档成立与换模型是两件事，判据一份）。

全离线：时钟走 ``ContentRouteEngine(clock=…)`` 注入缝，配置用 SimpleNamespace。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.runtime.content_route import (
    INTIMATE_SOURCE_ADMIN_PIN,
    INTIMATE_SOURCE_AFFINITY,
    INTIMATE_SOURCE_CONTENT_SIGNAL,
    INTIMATE_SOURCE_MANUAL,
    INTIMATE_SOURCE_MASTER_LOVE,
    INTIMATE_SOURCE_NONE,
    INTIMATE_TIER_L1,
    INTIMATE_TIER_L2,
    INTIMATE_TIER_NONE,
    ContentRouteEngine,
    match_intimate_command,
    match_manual_command,
    resolve_intimate_context,
)

MIN = 60.0


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
        "bot_content_route_l1_auto_enabled": True,
        "bot_content_route_l1_auto_min_tier": 1,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _engine(clock_now: list[float]) -> ContentRouteEngine:
    return ContentRouteEngine(clock=lambda: clock_now[0])


# ---------------------------------------------------------------- R3：命令面分深浅

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("亲密模式 开", ("intimate", INTIMATE_TIER_L1)),
        ("亲密模式开", ("intimate", INTIMATE_TIER_L1)),
        ("开启亲密模式", ("intimate", INTIMATE_TIER_L1)),
        ("/亲密模式 开", ("intimate", INTIMATE_TIER_L1)),
        ("亲密模式 开。", ("intimate", INTIMATE_TIER_L1)),
        # 深档形态必须**先于**浅档被认出：否则「深开」会被「开」吞掉降成浅档。
        ("亲密模式 深开", ("intimate", INTIMATE_TIER_L2)),
        ("亲密模式 开 深", ("intimate", INTIMATE_TIER_L2)),
        ("亲密模式 开 二档", ("intimate", INTIMATE_TIER_L2)),
        ("亲密模式 开 grok", ("intimate", INTIMATE_TIER_L2)),
        ("亲密模式 关", ("normal", INTIMATE_TIER_NONE)),
        ("关闭亲密模式", ("normal", INTIMATE_TIER_NONE)),
    ],
)
def test_command_carries_its_tier(text: str, expected: tuple[str, str]) -> None:
    assert match_intimate_command(text) == expected


def test_non_command_still_returns_none() -> None:
    assert match_intimate_command("亲密模式是什么") is None
    assert match_intimate_command("") is None
    assert match_intimate_command(None) is None  # type: ignore[arg-type]


def test_legacy_helper_still_returns_mode_only() -> None:
    """薄壳不回归：既有消费方（含旧测试）读 ``match_manual_command`` 拿到的仍是
    "intimate"/"normal"，深档也归成 "intimate"。"""
    assert match_manual_command("亲密模式 开") == "intimate"
    assert match_manual_command("亲密模式 深开") == "intimate"
    assert match_manual_command("亲密模式 关") == "normal"
    assert match_manual_command("帮我记个笔记") is None


# ---------------------------------------------------------------- R1/R3：只有深档换模型

def test_shallow_manual_pin_grants_tier_but_never_switches_model() -> None:
    engine = _engine([100.0])
    cfg = _config()
    assert engine.apply_manual(
        "private:u1", "intimate", cfg, source=INTIMATE_SOURCE_MANUAL, tier=INTIMATE_TIER_L1
    )
    verdict = engine.route_verdict("private:u1", cfg)
    assert verdict["mode"] == "intimate"
    assert verdict["tier"] == INTIMATE_TIER_L1
    assert verdict["head_models"] == []  # 浅档：默认链首原样（gemini）


def test_deep_manual_pin_switches_model() -> None:
    engine = _engine([100.0])
    cfg = _config()
    assert engine.apply_manual(
        "private:u1", "intimate", cfg, source=INTIMATE_SOURCE_MANUAL, tier=INTIMATE_TIER_L2
    )
    verdict = engine.route_verdict("private:u1", cfg)
    assert verdict["tier"] == INTIMATE_TIER_L2
    assert verdict["head_models"][0] == "grok-4.6"


def test_affinity_auto_source_is_shallow_and_never_switches_model() -> None:
    """R1 A 的自动腿：好感度派生的浅档**不得**换模型（与 ML 同级语义）。"""
    engine = _engine([100.0])
    cfg = _config()
    assert engine.apply_manual(
        "private:u1", "intimate", cfg, source=INTIMATE_SOURCE_AFFINITY, tier=INTIMATE_TIER_L1
    )
    verdict = engine.route_verdict("private:u1", cfg)
    assert verdict["source"] == INTIMATE_SOURCE_AFFINITY
    assert verdict["tier"] == INTIMATE_TIER_L1
    assert verdict["head_models"] == []


def test_master_love_source_stays_shallow_by_default() -> None:
    """ML 只交来源、不交档位时，按来源派生缺省档=浅档（2026-09-24 裁定不回归）。"""
    engine = _engine([100.0])
    cfg = _config()
    assert engine.apply_manual(
        "private:u1", "intimate", cfg, source=INTIMATE_SOURCE_MASTER_LOVE
    )
    verdict = engine.route_verdict("private:u1", cfg)
    assert verdict["tier"] == INTIMATE_TIER_L1
    assert verdict["head_models"] == []


def test_content_signal_over_threshold_is_deep_and_switches_model() -> None:
    """R-18 在册裁定不回归：强词越阈的自动档仍是深档（grok 优先）。"""
    engine = _engine([100.0])
    cfg = _config()
    engine.observe_turn("private:u1", message_text="和我做爱", context_text="", config=cfg)
    verdict = engine.route_verdict("private:u1", cfg)
    assert verdict["mode"] == "intimate"
    assert verdict["source"] == INTIMATE_SOURCE_CONTENT_SIGNAL
    assert verdict["tier"] == INTIMATE_TIER_L2
    assert verdict["head_models"][0] == "grok-4.6"


def test_untiered_intimate_pin_falls_back_to_pre_change_behavior() -> None:
    """状态里没有档位记录时（旧在飞状态/未交档位的调用面），按来源派生缺省档：
    显式与管理管理员钉=深档（改道之前的行为逐字节一致），绝不误降成浅档。"""
    engine = _engine([100.0])
    cfg = _config()
    assert engine.apply_manual("private:u1", "intimate", cfg, source=INTIMATE_SOURCE_MANUAL)
    assert engine.route_verdict("private:u1", cfg)["tier"] == INTIMATE_TIER_L2
    assert engine.route_verdict("private:u1", cfg)["head_models"] != []
    assert engine.apply_manual(
        "group:g1", "intimate", cfg, source=INTIMATE_SOURCE_ADMIN_PIN
    )
    assert engine.route_verdict("group:g1", cfg)["head_models"] != []


# ---------------------------------------------------------------- R4：显式/钉不受 120 封顶

@pytest.mark.parametrize(
    "source", [INTIMATE_SOURCE_MANUAL, INTIMATE_SOURCE_ADMIN_PIN], ids=["manual", "admin_pin"]
)
def test_explicit_and_admin_pins_are_not_capped_by_max_ttl(source: str) -> None:
    """把 TTL 配到 4 小时、max_ttl 留在 120 分钟：钉必须活过 130 分钟。
    （改前：max_ttl 那一道会在 120 分钟把钉整个清掉，管理员配多长都没用。）"""
    now = [1000.0]
    engine = _engine(now)
    cfg = _config(
        bot_content_route_intimate_ttl_minutes=240.0, bot_content_route_max_ttl_minutes=120.0
    )
    assert engine.apply_manual("private:u1", "intimate", cfg, source=source, tier=INTIMATE_TIER_L2)
    now[0] += 130 * MIN
    verdict = engine.route_verdict("private:u1", cfg)
    assert verdict["mode"] == "intimate"
    assert verdict["head_models"][0] == "grok-4.6"


def test_exempt_pin_still_closes_at_its_own_ttl() -> None:
    """豁免不是永不过期：TTL 240 分钟到点照关。"""
    now = [1000.0]
    engine = _engine(now)
    cfg = _config(
        bot_content_route_intimate_ttl_minutes=240.0, bot_content_route_max_ttl_minutes=120.0
    )
    assert engine.apply_manual(
        "private:u1", "intimate", cfg, source=INTIMATE_SOURCE_MANUAL, tier=INTIMATE_TIER_L2
    )
    now[0] += 241 * MIN
    assert engine.route_verdict("private:u1", cfg)["mode"] == "normal"


def test_normal_pin_is_still_swept_by_max_ttl() -> None:
    """免只给"上着深钉的会话"：normal 钉两小时静默后照旧被清（不留残态）。"""
    now = [1000.0]
    engine = _engine(now)
    cfg = _config(bot_content_route_max_ttl_minutes=120.0)
    assert engine.apply_manual("private:u1", "normal", cfg)
    now[0] += 121 * MIN
    state_score = engine.route_verdict("private:u1", cfg)
    assert state_score["mode"] == "normal"
    assert state_score["source"] == INTIMATE_SOURCE_NONE
    # 清过之后钉本身也不在了（None），而不是留着一条 normal 钉。
    assert engine.pinned_mode("private:u1", cfg) is None


def test_content_signal_state_is_still_swept_by_max_ttl() -> None:
    """自动信号档（无钉）不在豁免面里：静默超 max_ttl 后分数被清。"""
    now = [1000.0]
    engine = _engine(now)
    cfg = _config(bot_content_route_max_ttl_minutes=120.0)
    engine.observe_turn("private:u1", message_text="和我做爱", context_text="", config=cfg)
    assert engine.route_verdict("private:u1", cfg)["mode"] == "intimate"
    now[0] += 121 * MIN
    assert engine.route_verdict("private:u1", cfg)["mode"] == "normal"


# ---------------------------------------------------------------- R6：装配期就能看到"本轮会不会换头"

def test_preview_scores_this_round_without_committing_the_ledger() -> None:
    """媒体形态在**装配期**就要定（`chat.py` 的 `_media_gate_session_key`），
    而记账发生在生成前 ⇒ 必须有一个"把本轮信号算进去、但不落账"的只读预览口。
    预览与真记完账的判定**必须逐字段相等**（两问一处答，不许第二套判据）。"""
    engine = _engine([100.0])
    cfg = _config()
    preview = engine.verdict_with_pending_turn(
        "private:u1", message_text="和我做爱", context_text="", config=cfg
    )
    assert preview["mode"] == "intimate"
    assert preview["tier"] == INTIMATE_TIER_L2
    assert preview["head_models"][0] == "grok-4.6"
    # 预览不落账：紧接着读真实判定仍是普通档。
    assert engine.route_verdict("private:u1", cfg)["mode"] == "normal"
    # 真记账之后与预览一致（等值锁）。
    engine.observe_turn("private:u1", message_text="和我做爱", context_text="", config=cfg)
    real = engine.route_verdict("private:u1", cfg)
    assert {k: preview[k] for k in ("mode", "tier", "source")} == {
        k: real[k] for k in ("mode", "tier", "source")
    }
    assert real["head_models"] == preview["head_models"]


def test_preview_of_shallow_pin_keeps_default_head() -> None:
    """浅档（关系语气那档）不换头 ⇒ 带语音/视频的消息在装配期就该按默认链挂原生。"""
    engine = _engine([100.0])
    cfg = _config()
    assert engine.apply_manual(
        "private:u2", "intimate", cfg, source=INTIMATE_SOURCE_MANUAL, tier=INTIMATE_TIER_L1
    )
    preview = engine.verdict_with_pending_turn(
        "private:u2", message_text="今天天气不错", context_text="", config=cfg
    )
    assert preview["mode"] == "intimate"
    assert preview["tier"] == INTIMATE_TIER_L1
    assert preview["head_models"] == []


def test_preview_is_fail_open() -> None:
    """垃圾输入不许把装配期炸掉：预览任何异常回普通档。"""
    engine = _engine([100.0])
    cfg = _config()
    preview = engine.verdict_with_pending_turn("", message_text=None, context_text=None, config=cfg)  # type: ignore[arg-type]
    assert preview["mode"] == "normal"
    assert preview["head_models"] == []
    assert preview["tier"] == INTIMATE_TIER_NONE


# ---------------------------------------------------------------- 合成面把档位一起报出去

def test_resolve_intimate_context_reports_tier(monkeypatch) -> None:
    """注入缝与路由双门同源：合成结果必须带 tier，供 chat 侧一处读、不再自判。"""
    now = [100.0]
    engine = _engine(now)
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.domains.chat_reply.runtime.content_route."
        "SHARED_CONTENT_ROUTE_ENGINE",
        engine,
        raising=False,
    )
    cfg = _config()
    assert engine.apply_manual(
        "private:u9", "intimate", cfg, source=INTIMATE_SOURCE_MANUAL, tier=INTIMATE_TIER_L1
    )
    ctx = resolve_intimate_context(
        engine,
        session_type="private",
        sender_id="u9",
        session_key="private:u9",
        config=cfg,
    )
    assert ctx["mode"] == "intimate"
    assert ctx["tier"] == INTIMATE_TIER_L1
    # 未进档的会话：档位为空串（没有档就没有"深还是浅"）。
    off = resolve_intimate_context(
        engine,
        session_type="private",
        sender_id="u0",
        session_key="private:u0",
        config=cfg,
    )
    assert off["tier"] == INTIMATE_TIER_NONE
