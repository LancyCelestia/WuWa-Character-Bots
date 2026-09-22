"""v21r2 RP 席：R-18 文风多样化与复读三连治理（离线单测）。

覆盖（设计稿 docs/design/v21r2-rp-style-log.md §五.3）：
- 文风指令按 content_route 会话态二选一注入（互斥）：INTIMATE=动作/环境/
  体感详细描写+篇幅放开；normal=全年龄禁动作描写；
- 路由整体关闭时仍得 normal 禁令（全年龄全局口径）；
- 复读三连（「我不会躲。」「我在。」「我在这里。」）不再以固定形态出现在
  提示词常量与人格源改写节；
- 危险安抚示例池规模 ≥8 + 游标轮换确定性（整轮无重复、重放一致）。

minors 硬红线回归由 tests/test_content_safety_v2.py、tests/test_content_route.py
承担（本文件不重复）。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from plugins.bot_unified_runtime.capabilities.chat import (
    _DANGER_COMFORT_EXAMPLES,
    INTIMATE_RP_STYLE_INSTRUCTION,
    NORMAL_NO_ACTION_INSTRUCTION,
    _danger_style_line,
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
    SHARED_CONTENT_ROUTE_ENGINE,
)

_REPO = Path(__file__).resolve().parents[1]


class _CapturingProvider:
    """记录收到的 messages 并原样成功返回（触发 prompt 组装全链）。"""

    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    def generate(
        self, messages: list[dict[str, str]], **kwargs: object
    ) -> LLMReply:
        self.messages = messages
        return LLMReply(text="嗯，我在听。你慢慢说。", provider="fake", model="m")


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


def _message(session_id: str, text: str = "今天有点累，想和你说说话。") -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="bot-1",
        session_id=session_id,
        session_type=SessionType.PRIVATE,
        sender_id="user-rp",
        plain_text=text,
    )


def _decision(message: IncomingMessage) -> BotDecision:
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


def _context(session_id: str) -> ContextBundle:
    return ContextBundle(
        request_id="req-rp-style",
        persona=PersonaProfile(
            profile_id="shorekeeper",
            version="1",
            display_name="守岸人",
            identity="守岸人",
        ),
        tone=ToneProfile(profile_id="shorekeeper", mode="default"),
        memory_results=MemoryRetrievalResult(request_id="req-rp-style"),
        conversation_history=ConversationHistoryResult(request_id="req-rp-style"),
        knowledge_results=RetrievalResult(request_id="req-rp-style"),
        current_message="今天有点累，想和你说说话。",
        sender_id="user-rp",
        session_id=session_id,
    )


def _system_join(provider: _CapturingProvider) -> str:
    return "\n".join(
        str(item.get("content") or "")
        for item in provider.messages
        if item.get("role") == "system"
    )


# ---------------------------------------------------------------- 会话态互斥注入

def test_intimate_session_gets_action_directive() -> None:
    session = "private:rp-style-intimate-1"
    cfg = _config()
    assert SHARED_CONTENT_ROUTE_ENGINE.apply_manual(session, "intimate", cfg) is True
    provider = _CapturingProvider()
    message = _message(session)
    build_chat_result(
        message,
        _decision(message),
        _context(session),
        llm_provider=provider,
        content_route_config=cfg,
    )
    joined = _system_join(provider)
    assert "【亲密场景的叙述】" in joined
    assert "能详则详" in joined
    assert "动作" in joined
    assert "【日常对话的叙述】" not in joined  # 互斥：不并存
    assert "不加括号" not in joined


def test_normal_session_gets_no_action_directive() -> None:
    session = "private:rp-style-normal-1"
    cfg = _config()
    provider = _CapturingProvider()
    message = _message(session, text="今天天气怎么样？")
    build_chat_result(
        message,
        _decision(message),
        _context(session),
        llm_provider=provider,
        content_route_config=cfg,
    )
    joined = _system_join(provider)
    assert "【日常对话的叙述】" in joined
    assert "不加括号" in joined
    assert "【亲密场景的叙述】" not in joined  # 互斥：不并存


def test_route_disabled_still_gets_normal_directive() -> None:
    session = "private:rp-style-route-off-1"
    provider = _CapturingProvider()
    message = _message(session, text="晚饭吃什么好")
    build_chat_result(
        message,
        _decision(message),
        _context(session),
        llm_provider=provider,
        content_route_config=None,
    )
    joined = _system_join(provider)
    assert "【日常对话的叙述】" in joined
    assert "【亲密场景的叙述】" not in joined


# ---------------------------------------------------------------- 复读三连治理

def test_repeat_trio_absent_from_prompt_constants() -> None:
    assert "我不会躲" not in INTIMATE_RP_STYLE_INSTRUCTION
    assert "我不会躲" not in NORMAL_NO_ACTION_INSTRUCTION
    for variant in _DANGER_COMFORT_EXAMPLES:
        assert "我不会躲" not in variant
        assert "我在这里。" not in variant
        assert "我在。" not in variant


def test_repeat_trio_absent_from_persona_source_fixed_forms() -> None:
    persona_path = (
        _REPO / "personas" / "shorekeeper" / "knowledge" / "守岸人_人格与表达规范.md"
    )
    persona_text = persona_path.read_text(encoding="utf-8")
    # 旧 MaiBot 合并节的极简三连示例（固定形态）必须已被多样化改写替换。
    assert '"我在这里。"、"你回来了。"、"我等你。"' not in persona_text
    assert "“我在这里”“我会一直听着”" not in persona_text
    assert "我不会躲" not in persona_text
    assert "我在这里......一直都在" not in persona_text
    # 多样化指引与变体池在位。
    assert "在场与安抚，从来不是同一句话" in persona_text
    assert "不重复固定短句" in persona_text


def test_runtime_answer_rules_no_longer_carry_fixed_example() -> None:
    from plugins.bot_unified_runtime.capabilities.chat import _RUNTIME_ANSWER_RULES

    assert "我在这里" not in _RUNTIME_ANSWER_RULES
    assert "不用怕。" not in _RUNTIME_ANSWER_RULES
    # 危险与战斗引导改为动态轮换行（含池示例）。
    line = _danger_style_line()
    assert line.startswith("危险与战斗：")
    assert any(example in line for example in _DANGER_COMFORT_EXAMPLES)


# ---------------------------------------------------------------- 池化轮换

def test_danger_pool_size_and_deterministic_rotation() -> None:
    from plugins.bot_unified_runtime.domains.assistant.daily.store import daily_assist

    pool = _DANGER_COMFORT_EXAMPLES
    assert len(pool) >= 8
    daily_assist._VARIANT_CURSORS.pop("chat_danger_comfort", None)
    first_cycle = [_danger_style_line() for _ in range(len(pool))]
    daily_assist._VARIANT_CURSORS["chat_danger_comfort"] = 0
    second_cycle = [_danger_style_line() for _ in range(len(pool))]
    assert first_cycle == second_cycle  # 同起点重放一致（确定性）
    assert len(set(first_cycle)) == len(pool)  # 整轮无重复
