"""S-FIX-ATK-LLM3 · ATKLLM-2（P3）修复锁：usage token 入账前按发送侧 payload 尺寸取夹。

对照 .superpowers/sdd/2026-09-27-fullload/logs/SEAT-ATK-LLMLEDGER.md 票 2 + 探针
probes/ATKLLM-2_usage_tokens_unbounded_overrecord.py。

链路：上游/被控中转可回虚报 token 把 channel_spec 臂撑成天文成本（虚记臂）；
F-2 gateway_cost_trust 的对照基线同源于这份不可信 usage、自指放行。修法（票据明许
「夹值**或标注存疑**」二者取其一）：入账 token 进入估价与列存**之前**，绝对上限
`min(报告值, TOKEN_MAX_ABSOLUTE)` 恒执法（把天文级虚记掐死，探针 A1 的 inflated 归位）；
发送侧 payload 相对判据**只做存疑标注**（token_report_sanity + 留痕日志）、不改动入账值
——因真实 prompt 含系统提示/工具 schema/记忆等我方 messages 之外的组装开销，纯按已见
payload 硬夹会误伤合法长上下文、并与账单计价口径冲突。审计臂 `_safe_usage_int` 同源复用绝对上限。
离线 mock：不起线程、不连网、全部落 tmp_path。
"""

from __future__ import annotations

from types import SimpleNamespace

from plugins.bot_unified_runtime.domains.chat_reply.capabilities import chat
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.ledger import (
    TOKEN_CHARS_PER_TOKEN_EST,
    TOKEN_MAX_ABSOLUTE,
    TOKEN_REPORT_CONSTANT_HEAD,
    TOKEN_REPORT_MAX_FACTOR,
    build_call_draft,
)

HUGE = 10**12


def test_absolute_cap_bounds_inflated_usage_without_payload() -> None:
    # A1 复刻：无发送侧证据时，绝对上限仍须掐死天文量级 token 的虚记。
    draft = build_call_draft(
        request_id="atk-2-abs",
        usage={"prompt_tokens": HUGE, "completion_tokens": HUGE, "total_tokens": 2 * HUGE},
        price_in=1.0,
        price_out=1.0,
        status="success",
    )
    assert draft.prompt_tokens is not None and draft.prompt_tokens <= TOKEN_MAX_ABSOLUTE
    assert draft.completion_tokens is not None and draft.completion_tokens <= TOKEN_MAX_ABSOLUTE
    assert draft.total_tokens is not None and draft.total_tokens <= TOKEN_MAX_ABSOLUTE
    # 成本被夹到与上限同量级，绝不随虚报线性放大到 1e12。
    assert draft.total_cost_micro is not None and draft.total_cost_micro < HUGE
    assert draft.total_cost_micro <= 2 * TOKEN_MAX_ABSOLUTE


def test_prompt_relative_check_marks_suspicion_without_mutating(caplog) -> None:
    # payload 相对判据＝「标注存疑」而非夹值（票据明许二选一）：报告 prompt
    # 在绝对上限之下、却远超 payload 估算上界时，绝对夹不触、入账值逐字保留，
    # 但必须留痕 token_report_sanity（相对分支 gated on sent_payload_chars 非 None）。
    import logging

    import plugins.bot_unified_runtime.domains.chat_reply.llm_engine.ledger as ledger_mod

    sent_chars = 40  # 估算 ~10 token
    est_tokens = (sent_chars + TOKEN_CHARS_PER_TOKEN_EST - 1) // TOKEN_CHARS_PER_TOKEN_EST
    prompt_cap = est_tokens * TOKEN_REPORT_MAX_FACTOR + TOKEN_REPORT_CONSTANT_HEAD
    reported_prompt = prompt_cap + 50_000  # 在绝对上限之下、payload 上界之上
    assert reported_prompt < TOKEN_MAX_ABSOLUTE
    with caplog.at_level(logging.DEBUG, logger=ledger_mod.logger.name):
        draft = build_call_draft(
            request_id="atk-2-payload",
            usage={"prompt_tokens": reported_prompt, "completion_tokens": 0},
            price_in=1.0,
            price_out=1.0,
            status="success",
            sent_payload_chars=sent_chars,
        )
    # 非破坏式：入账值不被改动（账单计价口径不变）。
    assert draft.prompt_tokens == reported_prompt
    # 存疑标注留痕。
    assert "token_report_sanity" in caplog.text


def test_no_payload_evidence_below_absolute_is_silent(caplog) -> None:
    # 无发送侧证据且未越绝对上限 ⇒ 既不改值也不误标存疑（合法小额零成本直通）。
    import logging

    import plugins.bot_unified_runtime.domains.chat_reply.llm_engine.ledger as ledger_mod

    with caplog.at_level(logging.DEBUG, logger=ledger_mod.logger.name):
        draft = build_call_draft(
            request_id="atk-2-silent",
            usage={"prompt_tokens": 5000, "completion_tokens": 0},
            price_in=1.0,
            price_out=1.0,
            status="success",
        )
    assert draft.prompt_tokens == 5000
    assert "token_report_sanity" not in caplog.text


def test_audit_arm_safe_usage_int_shares_absolute_cap() -> None:
    # 审计臂"同修"：_safe_usage_int 与台账同源，夹到绝对上限、合法值不动。
    assert chat._safe_usage_int(HUGE) == TOKEN_MAX_ABSOLUTE
    assert chat._safe_usage_int(5000) == 5000
    assert chat._safe_usage_int(str(HUGE)) == TOKEN_MAX_ABSOLUTE
    assert chat._safe_usage_int(-5) == 0
    assert chat._safe_usage_int(True) == 0
    # _llm_usage_audit_tags 用同一份不可信 raw_usage 重算——token 标签须为夹后值。
    tags = chat._llm_usage_audit_tags({"prompt_tokens": HUGE, "completion_tokens": HUGE})
    prompt_tag = next(t for t in tags if t.startswith("llm_usage_prompt_tokens:"))
    assert int(prompt_tag.split(":", 1)[1]) == TOKEN_MAX_ABSOLUTE


class _HugeUsageProvider:
    """真实调用一次、回虚报 prompt token（低于绝对上限）的桩 provider。"""

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id

    def generate(self, messages, **kwargs):
        from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
            LLMReply,
        )

        return LLMReply(
            text="ok",
            provider="stub",
            model=self.model_id,
            raw_usage={"prompt_tokens": 200_000, "completion_tokens": 10, "total_tokens": 200_010},
            remote_request_id="atk-2-router",
        )


def test_router_threads_sent_payload_evidence(caplog) -> None:
    # 端到端接线：router.generate 须把发送侧 messages 体量透传 ledger，令相对
    # 存疑判据对虚报 prompt token 生效。报告 prompt 在绝对上限之下（绝对夹不触），
    # 只有 sent_payload_chars 被真正透传时，相对分支才会留痕 token_report_sanity
    # ⇒ 日志出现即证明接线（未接线则 sent_payload_chars=None，相对分支整段跳过）。
    import logging

    import plugins.bot_unified_runtime.domains.chat_reply.llm_engine.ledger as ledger_mod
    from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.ledger import (
        LLMCallDraft,
    )
    from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router import (
        ModelRouter,
        ModelSpec,
    )

    captured: list[LLMCallDraft] = []

    class _Sink:
        def submit(self, draft):
            captured.append(draft)

    spec = ModelSpec(
        model_id="m-probe",
        model="m-probe",
        base_url="https://probe.invalid/v1",
        api_key="sk",
        tags=(),
        priority=1,
    )
    router = ModelRouter(
        {"m-probe": spec},
        provider_factory=lambda s: _HugeUsageProvider(s.model_id),
        credential_config=SimpleNamespace(),
        call_record_sink=_Sink(),
    )
    with caplog.at_level(logging.DEBUG, logger=ledger_mod.logger.name):
        router.generate([{"role": "user", "content": "很短"}], message_text="很短")

    assert captured, "出口记账必须产出一条 draft"
    draft = captured[-1]
    assert draft.prompt_tokens is not None
    # 200000 在绝对上限之下 ⇒ 入账值不被破坏式改动。
    assert draft.prompt_tokens == 200_000
    # 相对存疑判据经发送侧证据触发 ⇒ payload 已透传到 ledger。
    assert "token_report_sanity" in caplog.text
