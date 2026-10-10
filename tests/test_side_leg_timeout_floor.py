"""侧腿（判域／贴纸情感）与自适应钳制共用一把每跳地板（台账 #80）。

生产实弹（2026-10-06 17:41–18:00 私聊无回复，实据＝
`ChatBot_Runtime/data/llm_billing.sqlite3` + `channel_health.sqlite3`）：

1. `chat.py` 把 `question_intent.llm_timely_domain_hint` 接进每条消息的判定路，
   它带 `timeout_seconds=4.0` 走**完整**故障转移链；gemini 实测要 27s、grok 要 30s，
   4s 是**必然失败**，不是渠道慢（实据 17:51:38 `["axon-gemini-38-flash:timeout",
   "axon-grok-46:timeout","axon-qwen35-local:success"]` 总时长 9031ms＝两跳各 ~4s）。
2. 被掐死的 timeout 照写渠道健康账（`_health_record_failure` 只免 `auth/config_missing`）
   ⇒ gemini+grok 进了 30 分钟不可用；十秒后用户真正的回复请求，健康过滤一剔
   只剩单候选（实据告警 `chain=1跳全败 last=axon-qwen35-local:timeout`，
   `attempts=max(1,len(route_attempts))` 在 `chat.py` 里就是字面跳数）。
3. 自适应超时 `min(原值, max(地板, ema×3))` 把地板放在 8s：本地渠道 ema_ms=903
   （被 `max_tokens=12/64` 截断成 `finish_reason=length` 的 0.85s 微调用喂出来）
   ⇒ 每一跳钳到 8.0s（实据＝9 条失败记录时长 8030–8422ms）。

本文件钉三件事（缺一即红）：
① 每跳地板**只有一处真身**（`channel_health.PER_HOP_TIMEOUT_FLOOR_SECONDS`）；
   自适应钳制与两枚侧腿都读它——把地板另抄一份、或把侧腿改回小秒数，本门必红。
② 侧腿交给路由的单跳预算不得低于地板。
③ 抬地板不许把小腿变成阻塞腿：侧腿必须自己封顶候选宽度。
"""

from __future__ import annotations

from typing import Any

import pytest

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine import (
    channel_health as channel_health_module,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.channel_health import (
    PER_HOP_TIMEOUT_FLOOR_SECONDS,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router import (
    ModelRouter,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime import question_intent
from plugins.bot_unified_runtime.domains.meme.reactions import sentiment_selector

# ==================== 复位 channel_health 进程级单例（test_llm_failfast 同款） ====================


@pytest.fixture(autouse=True)
def _reset_channel_health_singleton(tmp_path, monkeypatch):
    """隔离到 tmp_path 独立库，绝不碰生产 `channel_health.sqlite3`。"""
    db_path = str(tmp_path / "channel_health.sqlite3")
    monkeypatch.setattr(
        channel_health_module,
        "_GLOBAL_STORE",
        channel_health_module.ChannelHealthStore(db_path),
    )
    monkeypatch.setattr(channel_health_module, "resolve_default_db_path", lambda: db_path)
    monkeypatch.setenv("BOT_CHANNEL_HEALTH_ENABLED", "0")
    monkeypatch.setenv("BOT_CHANNEL_HEALTH_LATENCY_FIRST", "0")


class _RecordingRouter:
    """假路由：记下 generate 收到的 kwargs，返回一段无法解析的文本（腿自行 fail-open）。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def generate(self, messages: list[dict[str, str]], **kwargs: Any) -> Any:
        self.calls.append(kwargs)

        class _Reply:
            text = "NOT_A_DOMAIN"

        return _Reply()


# ==================== ① 地板单一真身 ====================


def test_adaptive_clamp_follows_the_single_floor_source(monkeypatch) -> None:
    """把地板改到 999，钳制必须跟着走——否则 model_router 里还私藏一份数。"""
    monkeypatch.setattr(channel_health_module, "PER_HOP_TIMEOUT_FLOOR_SECONDS", 999.0)
    # ema 903ms ⇒ ema×3 远小于地板 ⇒ 结果由地板决定
    assert ModelRouter._tighten_timeout("ch", 1000.0, {"ch": 903}) == 999.0


def test_adaptive_clamp_never_undermines_per_hop_floor() -> None:
    """真身缺省档：ema 被微调用喂小的渠道，单跳仍要拿到地板级预算。"""
    tightened = ModelRouter._tighten_timeout("axon-qwen35-local", 40.0, {"axon-qwen35-local": 903})
    assert tightened >= PER_HOP_TIMEOUT_FLOOR_SECONDS, (
        f"自适应钳制把单跳压到 {tightened}s，低于每跳地板 "
        f"{PER_HOP_TIMEOUT_FLOOR_SECONDS}s：思考型模型连首字都等不到，"
        "每一跳同死，用户侧只剩失败话术。"
    )


def test_floor_is_not_duplicated_in_model_router_source() -> None:
    """model_router 不许再自带一份地板字面量（第二把尺＝改一处漏一处）。"""
    import inspect

    source = inspect.getsource(
        __import__(
            "plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router",
            fromlist=["ModelRouter"],
        )
    )
    assert "_ADAPTIVE_TIMEOUT_FLOOR_S" not in source, (
        "model_router 仍私藏地板常量；唯一真身＝channel_health.PER_HOP_TIMEOUT_FLOOR_SECONDS"
    )


# ==================== ② 侧腿预算不低于地板 ====================


def _kwarg_default(func: Any, name: str) -> Any:
    import inspect

    signature = inspect.signature(func)
    return signature.parameters[name].default


def test_side_leg_default_budgets_are_at_or_above_per_hop_floor() -> None:
    """贴纸腿的预算住在 Config 键缺省里，判域腿的预算走地板兜底（见 wiring 两测）。"""
    reactions_default = float(
        Config.model_fields["bot_reactions_sentiment_timeout_seconds"].default or 0.0
    )
    too_low = {
        "bot_reactions_sentiment_timeout_seconds": reactions_default
    }
    too_low = {k: v for k, v in too_low.items() if v < PER_HOP_TIMEOUT_FLOOR_SECONDS}
    assert not too_low, (
        f"侧腿单跳预算低于地板 {PER_HOP_TIMEOUT_FLOOR_SECONDS}s：{too_low}。"
        "小腿用短预算打满整条故障转移链＝系统性制造假超时，"
        "并把健康的主聊天渠道打进 30 分钟黑名单。"
    )


def test_domain_hint_leg_budget_defaults_to_the_floor_not_a_private_number() -> None:
    """判域腿不自带秒数：缺省 None＝现取地板（把 4.0 这类私藏数写回来＝本测红）。"""
    assert _kwarg_default(question_intent.llm_timely_domain_hint, "timeout_seconds") is None, (
        "判域腿又自带超时数字；唯一真身＝channel_health.PER_HOP_TIMEOUT_FLOOR_SECONDS"
    )


def test_domain_hint_leg_forwards_floor_sized_budget_and_bounded_width(monkeypatch) -> None:
    """判域腿：预算≥地板，且候选宽度自封（抬地板不得把它变成阻塞腿）。"""
    router = _RecordingRouter()
    question_intent.llm_timely_domain_hint("今天上海天气怎么样", model_router=router)

    assert len(router.calls) == 1, "判域腿未走路由（接线变了，本门要跟着复核）"
    call = router.calls[0]
    assert float(call.get("timeout_seconds") or 0.0) >= PER_HOP_TIMEOUT_FLOOR_SECONDS, (
        f"判域腿把 {call.get('timeout_seconds')}s 交给路由每一跳，低于地板。"
    )
    assert call.get("fast_mode") is True, "判域腿未封顶候选宽度：抬地板会把它拖成分钟级阻塞。"
    width = int(call.get("fast_max_candidates") or 0)
    assert 1 <= width <= 2, f"判域腿候选宽度未封顶（现值 {width}）：inline 二判最多问 1-2 个渠道。"


def test_reactions_leg_forwards_floor_sized_budget_and_bounded_width(monkeypatch) -> None:
    """贴纸腿：同一把地板；它跑线程池，但仍不得制造假超时污染健康账。"""
    import plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router as mr_module

    router = _RecordingRouter()
    monkeypatch.setattr(mr_module, "build_model_router", lambda _config: router)

    sentiment_selector.classify_sticker_sentiment(
        Config(),
        user_text="谢谢你呀",
        reply_text="这句话我记得。",
        session_key="private:test",
    )

    assert len(router.calls) == 1, "贴纸腿未走路由（接线变了，本门要跟着复核）"
    call = router.calls[0]
    assert float(call.get("timeout_seconds") or 0.0) >= PER_HOP_TIMEOUT_FLOOR_SECONDS, (
        f"贴纸腿把 {call.get('timeout_seconds')}s 交给路由每一跳，低于地板。"
    )
    assert call.get("fast_mode") is True, "贴纸腿候选宽度封顶缺位。"
