"""每跳超时地板锁（2026-09-27 弹模板文案事故）。

生产实弹（`ChatBot_Runtime/data/runtime_events.log`）：
    event=pipeline_result capability_id=bot.chat duration_ms=69436.9
    route_attempts=axon-gemini-38-flash:timeout|axon-grok-46:timeout error_kind=timeout

两跳各被 20s 掐死（合计 69s），随后弹出 `_PERSONA_FAILURE_MESSAGES` 模板文案。
模型光首字就要 20 秒以上，20s 不是「响应慢」而是**必然失败**：故障转移链上每一跳
共用同一个钳制值（`model_router.build_model_router` 的 `timeout_seconds`），
换渠道不会更快，只会把同一发超时重放 N 遍。

本锁钉两件事：
① 两枚超时键的**代码缺省**不得低于地板（新装/漏配时不该回到必然失败的那一档）；
② 快速模式开着时 `min(normal, fast)` 不得把地板重新压穿（只抬一枚键＝没抬）。
"""

from __future__ import annotations

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router import (
    build_model_router,
)

#: 单跳最小预算（秒）。地板值取用户裁定区间下沿（30-40s），实测缺省已抬到 40s。
PER_HOP_FLOOR_SECONDS = 30.0

_TIMEOUT_KEYS = (
    "bot_chat_timeout_seconds",
    "bot_chat_fast_timeout_seconds",
)


def _default_of(key: str) -> float:
    field = Config.model_fields[key]
    assert field.default is not None, f"{key} 缺省值缺席"
    return float(field.default)


def test_per_hop_timeout_defaults_are_above_the_failure_floor() -> None:
    too_low = {k: _default_of(k) for k in _TIMEOUT_KEYS if _default_of(k) < PER_HOP_FLOOR_SECONDS}
    assert not too_low, (
        f"每跳超时缺省低于 {PER_HOP_FLOOR_SECONDS}s：{too_low}。"
        "低于该档时思考型模型连首字都等不到，故障转移链每一跳同钳，"
        "结局恒为 error_kind=timeout + 失败话术模板。"
    )


def test_fast_mode_does_not_reclamp_below_the_floor() -> None:
    """快速模式走 `min(normal, fast)`：两枚键必须一起达标才叫真抬上去。"""
    config = Config(bot_chat_fast_mode=True)
    router = build_model_router(config, provider_factory=lambda _spec: None)
    assert router.timeout_seconds >= PER_HOP_FLOOR_SECONDS, (
        f"快速模式下每跳超时被压到 {router.timeout_seconds}s，"
        f"低于地板 {PER_HOP_FLOOR_SECONDS}s（min 钳制只认两枚键里较小的那枚）。"
    )

    normal = build_model_router(
        Config(bot_chat_fast_mode=False), provider_factory=lambda _spec: None
    )
    assert normal.timeout_seconds >= PER_HOP_FLOOR_SECONDS
