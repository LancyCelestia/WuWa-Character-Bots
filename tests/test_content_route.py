"""R-18 内容感知路由（runtime/content_route.py）离线单测。

覆盖：防御性标记剥离、L1/L2 强词信号与衰减（擦边词不记分——用户裁定
普通模式可以擦边，留在默认链）、滞回判定、手动钉死（含倒装句式）、
TTL/空闲重置、fail-open、路由器候选重排（INTIMATE 头插按注册表优先级）
与管理员 override 不受影响。

2026-09-17 修订：模型自评标签注入层删除（gemini/grok 都把它当注入攻击
整轮拒答）；标签相关用例改为防御剥离语义，不再有注入侧。
"""
from __future__ import annotations

from types import SimpleNamespace

from plugins.bot_unified_runtime.llm.model_router import ModelRouter, ModelSpec
from plugins.bot_unified_runtime.runtime.content_route import (
    ContentRouteEngine,
    build_router_cb,
    match_manual_command,
    match_master_love_admin,
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
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _engine(clock_now: list[float]) -> ContentRouteEngine:
    return ContentRouteEngine(clock=lambda: clock_now[0])


# ---------------------------------------------------------------- 防御性标记剥离

def test_tag_high_stripped_and_score_pinned() -> None:
    now = [100.0]
    engine = _engine(now)
    engine.observe_turn("s1", message_text="今天天气不错", config=_config())
    clean, tag = engine.consume_reply("s1", "<intimacy:high>\n继续聊聊吧。", _config())
    assert tag == "high"
    assert clean == "继续聊聊吧。"
    verdict = engine.route_verdict("s1", _config())
    assert verdict["mode"] == "intimate"
    assert verdict["head_models"] == ["grok-4.6", "gemini-3.8-flash"]


def test_tag_low_speeds_decay() -> None:
    now = [100.0]
    engine = _engine(now)
    engine.observe_turn("s1", message_text="色情 内容", config=_config())
    assert engine.route_verdict("s1", _config())["mode"] == "intimate"
    _, tag = engine.consume_reply("s1", "<intimacy:low>正常回复。", _config())
    assert tag == "low"
    # low → 分数 ×0.4：仍高于 normal 阈值（滞回保持 intimate）但已松动。
    now[0] += 1.0
    engine.observe_turn("s1", message_text="嗯", config=_config())
    now[0] += 1.0
    engine.observe_turn("s1", message_text="嗯", config=_config())
    assert engine.route_verdict("s1", _config())["mode"] == "normal"


def test_tag_absent_or_pure_marker_keeps_text() -> None:
    engine = _engine([100.0])
    clean, tag = engine.consume_reply("s1", "普通回复，无标记。", _config())
    assert (clean, tag) == ("普通回复，无标记。", "")
    # 纯标记回复：保原文防误判空回复，不当信号。
    clean, tag = engine.consume_reply("s1", "<intimacy:high>", _config())
    assert clean == "<intimacy:high>"
    assert tag == ""


def test_tag_tolerates_quotes_and_whitespace() -> None:
    engine = _engine([100.0])
    clean, tag = engine.consume_reply("s1", "  「<intimacy:high>」 正文", _config())
    assert tag == "high"
    assert clean == "正文"


# ---------------------------------------------------------------- L1/L2 与滞回

def test_strong_word_hits_intimate_immediately() -> None:
    now = [100.0]
    engine = _engine(now)
    engine.observe_turn("s1", message_text="给我讲个色情故事", config=_config())
    assert engine.route_verdict("s1", _config())["mode"] == "intimate"


def test_extra_words_from_config_appended() -> None:
    now = [100.0]
    engine = _engine(now)
    cfg = _config(bot_content_route_words="自定义黑话A, 自定义黑话B")
    engine.observe_turn("s1", message_text="来点自定义黑话A", config=cfg)
    assert engine.route_verdict("s1", cfg)["mode"] == "intimate"


def test_borderline_single_hit_stays_normal() -> None:
    now = [100.0]
    engine = _engine(now)
    engine.observe_turn("s1", message_text="抱抱我", config=_config())
    assert engine.route_verdict("s1", _config())["mode"] == "normal"


def test_borderline_never_flips_intimate() -> None:
    """擦边词回归锁（2026-09-17 用户裁定：普通模式可以擦边）——擦边消息
    一律留在默认链，只有强词或手动开关才切 grok。"""
    now = [100.0]
    engine = _engine(now)
    for turn in range(6):
        now[0] += 1.0
        engine.observe_turn("s1", message_text="抱抱我，想跟你贴贴", config=_config())
        assert engine.route_verdict("s1", _config())["mode"] == "normal"


def test_context_strong_accumulation_reaches_intimate() -> None:
    now = [100.0]
    engine = _engine(now)
    context = "用户：讲点色情的\n岸宝：……这个啊\n用户：就是那种内容"
    engine.observe_turn("s1", message_text="继续", context_text=context, config=_config())
    # 当前「继续」无信号，但 L2 历史强词 +35 → 滞回带保持前态 normal；
    # 语境再抬一轮才过阈值。
    assert engine.route_verdict("s1", _config())["mode"] == "normal"
    now[0] += 1.0
    engine.observe_turn("s1", message_text="继续呀", context_text=context, config=_config())
    assert engine.route_verdict("s1", _config())["mode"] == "intimate"


def test_clean_turns_decay_out_of_intimate() -> None:
    now = [100.0]
    engine = _engine(now)
    engine.observe_turn("s1", message_text="色情", config=_config())
    assert engine.route_verdict("s1", _config())["mode"] == "intimate"
    now[0] += 1.0
    engine.observe_turn("s1", message_text="今天吃什么", config=_config())
    # 100×0.5=50 → 滞回带保持 intimate。
    assert engine.route_verdict("s1", _config())["mode"] == "intimate"
    now[0] += 1.0
    engine.observe_turn("s1", message_text="明天见", config=_config())
    # 50×0.5=25 → ≤ normal 阈值回默认链。
    assert engine.route_verdict("s1", _config())["mode"] == "normal"


# ---------------------------------------------------------------- 手动钉死

def test_manual_pin_overrides_signals() -> None:
    now = [100.0]
    engine = _engine(now)
    assert engine.apply_manual("s1", "intimate", _config())
    engine.observe_turn("s1", message_text="今天天气很好", config=_config())
    assert engine.route_verdict("s1", _config())["mode"] == "intimate"
    assert engine.apply_manual("s1", "normal", _config())
    engine.observe_turn("s1", message_text="色情", config=_config())
    assert engine.route_verdict("s1", _config())["mode"] == "normal"


def test_match_manual_command_variants() -> None:
    assert match_manual_command("亲密模式 开") == "intimate"
    assert match_manual_command("亲密模式开") == "intimate"
    # 倒装句式（2026-09-17）：自然语序「开启亲密模式」同样命中。
    assert match_manual_command("开启亲密模式") == "intimate"
    assert match_manual_command("打开亲密模式") == "intimate"
    assert match_manual_command("亲密模式 关") == "normal"
    assert match_manual_command("亲密模式关闭") == "normal"
    assert match_manual_command("关闭 亲密模式") == "normal"
    assert match_manual_command("今天天气不错") is None
    assert match_manual_command("亲密模式是什么") is None


# ---------------------------------------------------------------- TTL / 空闲 / 开关

def test_max_ttl_resets_pin() -> None:
    now = [100.0]
    engine = _engine(now)
    cfg = _config(bot_content_route_max_ttl_minutes=1.0)
    engine.apply_manual("s1", "intimate", cfg)
    assert engine.route_verdict("s1", cfg)["mode"] == "intimate"
    now[0] += 120.0
    assert engine.route_verdict("s1", cfg)["mode"] == "normal"


def test_idle_gap_resets_score() -> None:
    now = [100.0]
    engine = _engine(now)
    engine.observe_turn("s1", message_text="色情", config=_config())
    now[0] += 700.0  # 超过 idle_reset_minutes=10 分钟。
    engine.observe_turn("s1", message_text="继续", config=_config())
    assert engine.route_verdict("s1", _config())["mode"] == "normal"


def test_disabled_config_is_full_noop() -> None:
    engine = _engine([100.0])
    cfg = _config(bot_content_route_enabled=False)
    engine.observe_turn("s1", message_text="色情", config=cfg)
    assert engine.route_verdict("s1", cfg)["mode"] == "normal"
    assert engine.route_verdict("s1", cfg)["head_models"] == []
    assert engine.apply_manual("s1", "intimate", cfg) is False


def test_fail_open_on_broken_config() -> None:
    engine = _engine([100.0])

    class _Boom:
        def __getattr__(self, name: str) -> object:
            raise RuntimeError("boom")

    boom = _Boom()
    engine.observe_turn("s1", message_text="色情", config=boom)
    assert engine.route_verdict("s1", boom)["mode"] == "normal"
    # fail-open：knobs 读取失败 → 原文原样返回、不当信号（tag 空）。
    clean, tag = engine.consume_reply("s1", "<intimacy:high>x", boom)
    assert tag == ""
    assert clean == "<intimacy:high>x"


# ---------------------------------------------------------------- 路由器集成

def _spec(model_id: str, priority: int, model: str | None = None) -> ModelSpec:
    return ModelSpec(
        model_id=model_id,
        model=model or model_id,
        base_url="https://example.test/v1",
        api_key="key",
        tags=("fast",),
        priority=priority,
    )


def _specs() -> dict[str, ModelSpec]:
    return {
        "ch-gemini": _spec("ch-gemini", 1, model="gemini-3.8-flash"),
        "ch-gpt": _spec("ch-gpt", 2, model="gpt-5.6-terra"),
        "ch-grok": _spec("ch-grok", 3, model="grok-4.6"),
        "ch-deepseek": _spec("ch-deepseek", 4, model="deepseek-flash"),
    }


def test_router_reorders_candidates_when_intimate() -> None:
    verdict = {"mode": "intimate", "head_models": ["grok-4.6", "gemini-3.8-flash"]}
    router = ModelRouter(_specs(), content_route_cb=lambda sk, mt: verdict)
    ids = router.route_ids(message_text="x", override="", session_key="s1")
    assert ids[:2] == ["ch-grok", "ch-gemini"]
    assert ids[2:] == ["ch-gpt", "ch-deepseek"]


def test_intimate_head_follows_registry_priority_not_latency() -> None:
    """用户裁定（2026-09-16）：头插候选必须按注册表优先级排序，绝不做
    EWMA 延迟重排（浅夜の梦抢恒星纪元事故的回归锁）。"""
    specs = {
        # gemini-3.8-flash：axon(1) / starapi(104) / toolcode(105)
        "axon-gemini": _spec("axon-gemini", 1, model="gemini-3.8-flash"),
        "starapi-gemini": _spec("starapi-gemini", 104, model="gemini-3.8-flash"),
        "toolcode-gemini": _spec("toolcode-gemini", 105, model="gemini-3.8-flash"),
        # grok-4.6：axon(14) / qian-night(200)——浅夜延迟更低也绝不越位。
        "axon-grok": _spec("axon-grok", 14, model="grok-4.6"),
        "qian-night-grok": _spec("qian-night-grok", 200, model="grok-4.6"),
        "ch-other": _spec("ch-other", 50, model="other-model"),
    }
    verdict = {"mode": "intimate", "head_models": ["grok-4.6", "gemini-3.8-flash"]}
    router = ModelRouter(specs, content_route_cb=lambda sk, mt: verdict)
    ids = router.route_ids(message_text="x", override="", session_key="s1")
    assert ids == [
        "axon-grok",
        "qian-night-grok",
        "axon-gemini",
        "starapi-gemini",
        "toolcode-gemini",
        "ch-other",
    ]


def test_router_keeps_default_order_when_normal_or_missing_session() -> None:
    router = ModelRouter(
        _specs(),
        content_route_cb=lambda sk, mt: {"mode": "normal", "head_models": []},
    )
    assert router.route_ids(message_text="x", override="", session_key="s1") == [
        "ch-gemini",
        "ch-gpt",
        "ch-grok",
        "ch-deepseek",
    ]
    # 空 session_key（无状态调用方）照常出默认队列。
    assert router.route_ids(message_text="x", override="", session_key="") == [
        "ch-gemini",
        "ch-gpt",
        "ch-grok",
        "ch-deepseek",
    ]


def test_router_cb_exception_falls_back_to_default_order() -> None:
    def _boom(session_key: str, message_text: str) -> dict[str, object]:
        raise RuntimeError("boom")

    router = ModelRouter(_specs(), content_route_cb=_boom)
    assert router.route_ids(message_text="x", override="", session_key="s1") == [
        "ch-gemini",
        "ch-gpt",
        "ch-grok",
        "ch-deepseek",
    ]


def test_router_admin_override_ignores_content_route() -> None:
    verdict: dict[str, object] = {"mode": "intimate", "head_models": ["grok-4.6"]}
    calls: list[str] = []

    def _cb(session_key: str, message_text: str) -> dict[str, object]:
        calls.append(session_key)
        return verdict

    router = ModelRouter(_specs(), content_route_cb=_cb)
    ids = router.route_ids(message_text="x", override="ch-gpt", session_key="s1")
    assert ids[0] == "ch-gpt"
    assert calls == []  # override 分支不触发内容路由回调。


def test_build_router_cb_reads_config_provider_each_call() -> None:
    engine = _engine([100.0])
    holder = {"config": _config()}
    cb = build_router_cb(engine, lambda: holder["config"])
    engine.observe_turn("s1", message_text="色情", config=holder["config"])
    assert cb("s1", "x")["mode"] == "intimate"
    holder["config"] = _config(bot_content_route_enabled=False)
    assert cb("s1", "x")["mode"] == "normal"


# ---------------------------------------------------------------- effort 升档抑制

def test_intimate_session_suppresses_complex_effort_upgrade() -> None:
    """成本裁定（2026-09-17）：INTIMATE 会话抑制复杂任务 effort 升档——
    RP 长文本易误触发 ≥300 字/关键词判据，把 grok 顶到家族最高档白烧 token。"""
    from plugins.bot_unified_runtime.llm.model_router import _intimate_mode_for_session

    now = [100.0]
    engine = _engine(now)
    router = ModelRouter(
        _specs(),
        content_route_cb=build_router_cb(engine, lambda: _config()),
    )
    assert _intimate_mode_for_session(router, "s1", "写一篇很长的详细分析") is False
    engine.apply_manual("s1", "intimate", _config())
    assert _intimate_mode_for_session(router, "s1", "写一篇很长的详细分析") is True
    # 未钉死/未知会话：False；空 session：False。
    assert _intimate_mode_for_session(router, "s2", "色情") is False
    assert _intimate_mode_for_session(router, "", "色情") is False
    # 无 cb 的裸路由器（__new__ 构造/旧装配）：fail-open False。
    bare = ModelRouter(_specs())
    assert _intimate_mode_for_session(bare, "s1", "色情") is False


# ---------------------------------------------------------------- Master Love

def test_match_master_love_admin_global_and_scoped() -> None:
    entries = ["3865067623", "1108838060:1722380002"]
    # 全域条目：私聊与任意群都命中。
    assert match_master_love_admin("3865067623", "", entries) is True
    assert match_master_love_admin("3865067623", "1108838060", entries) is True
    # 域条目：仅指定群命中，他群/私聊不命中。
    assert match_master_love_admin("1722380002", "1108838060", entries) is True
    assert match_master_love_admin("1722380002", "", entries) is False
    assert match_master_love_admin("1722380002", "631785829", entries) is False
    # 撞号防护：他人在白名单群里昵称恰好等于 master 号——sender_id 不等就不命中。
    assert match_master_love_admin("999", "1108838060", entries) is False
    # 空守卫与 fail-open。
    assert match_master_love_admin("", "", entries) is False
    assert match_master_love_admin("3865067623", "", None) is False


def test_pinned_mode_readonly_peek() -> None:
    now = [100.0]
    engine = _engine(now)
    assert engine.pinned_mode("s1", _config()) is None
    engine.apply_manual("s1", "intimate", _config())
    assert engine.pinned_mode("s1", _config()) == "intimate"
    engine.apply_manual("s1", "normal", _config())
    assert engine.pinned_mode("s1", _config()) == "normal"
    assert engine.pinned_mode("", _config()) is None
    cfg = _config(bot_content_route_enabled=False)
    assert engine.pinned_mode("s1", cfg) is None
