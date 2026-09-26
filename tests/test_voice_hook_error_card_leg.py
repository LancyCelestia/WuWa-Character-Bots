"""S64 · 自动配音 hook 腿 `INVOKER_ERROR_DATA_KEY` 消费点锁 + 结构性不出卡缺口锁。

任务（GAP-HOOK-TIMEOUT-NO-CARD，S50 §2-G1 实锤）：hook 直呼腿拿到带载荷的
TIMEOUT/DEGRADED 信封后旧行为＝**只映射 issue、载荷逐字无视**。本件锁两件事：

1. **消费半已修**（修法=与 image provider 同法读键，但交回口只走既有 issue 旁路）：
   ``voice_enricher._envelope_failure_reason`` 把 ``data[INVOKER_ERROR_DATA_KEY]``
   的异常身份追加进证据串 ⇒ 第二信号（管理员告警链）可归因「挂死」；
   kind/retryable 仍唯一由 ``tts._FAILURE_KINDS`` 前缀表裁决（本件锁死这一不变量）。
2. **出卡半结构性不可得**（GAP-HOOK-STRUCTURAL-NO-CARD，显式命名缺口锁）：
   全树唯一的诊断卡旁路是 pipeline ``_internal_error``，只由**异常逃逸出
   ``_complete``** 触发；hook 跑在 review 批准之后，把载荷 raise 出去＝用整条
   已过审正文换一张卡（拖垮回复，违反 M-10/M-13/R-16② 在册红线）。缺口锁以
   「raise 版腿的真实 pipeline 终态」钉死这一代价，两口径裁定请求见 SEAT-S64 报告。

判据纪律（S50 同风）：看**终态与被调用到的出口**，不看「有没有调用」——
出口枚举＝①SendRequest.operational_issue（唯一应有出口）②error_report 卡钩子
（必须零触达）③异常逃逸出 enrich（必须零）。全离线 mock：伪造信封经 monkeypatch
``default_invoker`` 注入（90s 真预算不等），``synthesize`` 原语插雷证不被触达，
零端口接触。注毒以 ``test_injection_`` 前缀在**生产源文件**上物理施行后还原
（本席独占写面含 voice_enricher.py，还原比对 sha256[:16]=66b93deca38943c7）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    ReceiptState,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.pipeline import (
    RuntimePipeline,
)
from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
    BotDecision,
    IncomingMessage,
)
from plugins.bot_unified_runtime.domains.media import voice_enricher as ve
from plugins.bot_unified_runtime.domains.media.capabilities import tts as tts_mod
from plugins.bot_unified_runtime.domains.ops.monitor import (
    error_report as error_report_module,
)
from plugins.bot_unified_runtime.domains.transport.sender import InMemorySendQueue
from plugins.bot_unified_runtime.runtime import capability_protocols as cp

# 本席基线（干净修好的 voice_enricher.py）：注毒还原后必须逐字节回到该值。
# S91（中央调度收编波）按用户 mandate 退役了 voice_enricher 的内联变换段
# （取文/硬顶/逐块产出步/合并搬进中央第三形 media.tts.autodub_transform），
# 该改动手写授权、非注毒 ⇒ 本注毒残留基线随之刷新为新干净字节（消费点
# _envelope_failure_reason 与 INVOKER_ERROR_DATA_KEY 逐字保留，见下方 6 行为锁仍全绿）。
# 基线随 S91 二次刷新：内联退役改动 + 模块 docstring 同步（叙述与真身一致，非行为改动）。
# S270 归位第三次刷新（手写授权、非注毒）：产出步 ``dub`` 闭包改调单一组合口
# result_transform.dub_via_central、``_envelope_failure_reason`` 降为薄委派——本消费点判据
# 方向逐字不变（6 行为锁仍全绿），仅文件字节变 ⇒ 干净基线随之刷到新值。判据本体未放宽。
_CLEAN_SHA16 = "5a85ca9e367ef5cc"


# ---------------------------------------------------------------------------
# 夹具（与 test_tts_error_surface/test_voice_hook_assembly 同构，全离线）
# ---------------------------------------------------------------------------


class _NullAuditLogger:
    def append(self, record: object) -> None:
        return


def _config(tmp_path: Path, **overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "bot_tts_enabled": True,
        "bot_tts_api_url": "http://127.0.0.1:9880",
        "bot_tts_gptsovits_dir": "",
        "bot_tts_ref_audios": [],
        "bot_tts_trigger_words": [],
        "bot_tts_output_dir": str(tmp_path / "tts_out"),
        "bot_tts_preset": "shorekeeper",
        "bot_tts_max_chars": 0,
        "bot_tts_hard_max_chars": 2000,
        "bot_tts_max_audio_bytes": 0,
        "bot_tts_cache_enabled": False,
        "bot_tts_cache_max_bytes": 0,
        "bot_tts_cache_max_age_days": 0,
        "bot_tts_timeout_seconds": 60.0,
        "bot_tts_speed_factor": 0.85,
        "bot_tts_temperature": 0.9,
        "bot_tts_top_k": 15,
        "bot_tts_top_p": 1.0,
        "bot_tts_text_lang": "zh",
        "bot_tts_text_split_method": "cut5",
        "bot_tts_voice_hook_enabled": True,
        "bot_tts_auto_reply_enabled": True,
        "bot_tts_auto_reply_scope": "private",
        "bot_tts_auto_reply_probability": 1.0,
        "bot_tts_auto_reply_max_chars": 0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _ref_entry(tmp_path: Path) -> str:
    ref = tmp_path / "ref.flac"
    ref.write_bytes(b"fLaC" + b"\x00" * 32)
    return f"{ref}|参考文本|zh"


def _hook_config(tmp_path: Path, **over: object) -> SimpleNamespace:
    return _config(
        tmp_path,
        bot_tts_ref_audios=[_ref_entry(tmp_path)],
        **over,
    )


def _message() -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot11",
        bot_id="10000",
        session_id="private:20000",
        session_type=SessionType.PRIVATE,
        sender_id="20000",
        group_id="",
        plain_text="无所谓",
        message_id="m-s64",
        debug_id="dbg-s64",
    )


def _chat_result(body: str = "潮汐很安静") -> CapabilityResult:
    return CapabilityResult(
        request_id="req-s64",
        capability_id="bot.chat",
        kind="text",
        body=body,
    )


def _decision() -> BotDecision:
    return BotDecision(
        request_id="req-s64",
        should_respond=True,
        mode="command",
        trigger="你好",
        capability_id="bot.chat",
        target_scope=SessionType.PRIVATE,
        decision_reason="s64",
    )


def _static_capability(result: object):
    async def _run(message: IncomingMessage, decision: object) -> object:
        return result

    return _run


def _make_pipeline(enricher: object | None) -> tuple[RuntimePipeline, InMemorySendQueue]:
    queue = InMemorySendQueue(audit_logger=_NullAuditLogger())
    pipeline = RuntimePipeline(
        send_queue=queue,
        audit_logger=_NullAuditLogger(),
        outbound_voice_enricher=enricher,  # type: ignore[arg-type]
    )
    return pipeline, queue


def _envelope(status: cp.InvocationStatus, detail: str, data: dict[str, Any]) -> cp.InvocationResult:
    return cp.InvocationResult(
        capability_id="media.tts.autodub",
        status=status,
        detail=detail,
        via="invoker",
        data=data,
    )


class _ScriptedInvoker:
    """固定返回同一枚伪造信封的 invoker（不经 handler，绝不触达合成原语）。"""

    def __init__(self, envelope: cp.InvocationResult) -> None:
        self.envelope = envelope
        self.requests: list[Any] = []

    def invoke(self, request: Any) -> cp.InvocationResult:
        self.requests.append(request)
        return self.envelope


def _never_synthesize(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ve,
        "synthesize",
        lambda **_kw: (_ for _ in ()).throw(AssertionError("合成原语不得被触达")),
    )


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> Any:
    tts_mod._clear_failure()
    tts_mod._CACHE.clear()
    yield


@pytest.fixture()
def card_tripwire(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, BaseException]]:
    """error_report 卡钩子的哨兵：记录每次触达，绝不真渲染/真投递。"""
    calls: list[tuple[str, BaseException]] = []

    def _spy(pipeline: Any, message: Any, capability_id: str, exc: BaseException, **_kw: Any) -> None:
        calls.append((capability_id, exc))

    monkeypatch.setattr(error_report_module, "maybe_submit_error_card", _spy)
    return calls


# ---------------------------------------------------------------------------
# 1/2 · 消费点：TIMEOUT 与 DEGRADED 两形的载荷都必须进证据串
# ---------------------------------------------------------------------------


def test_leg_consumes_timeout_payload_into_issue_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """GAP-HOOK-TIMEOUT-NO-CARD 消费半（挂死形）：伪造 TIMEOUT 信封（90s 真预算
    离线不可等），载荷 ``CapabilityTimeout`` 必须被读并进 issue 证据串；kind 仍落
    兜底（前缀表在 detail 头部，不受追加影响）；正文逐字存活；**不抛**。"""
    timeout_error = cp.CapabilityTimeout("media.tts.autodub 超过中央预算 90s")
    invoker = _ScriptedInvoker(
        _envelope(
            cp.InvocationStatus.TIMEOUT,
            "超时 90s（线程跑到自然结束，结果弃用）",
            {cp.INVOKER_ERROR_DATA_KEY: timeout_error},
        )
    )
    monkeypatch.setattr(ve, "default_invoker", lambda: invoker)
    _never_synthesize(monkeypatch)
    result = _chat_result()

    enriched = ve.build_voice_enricher(_hook_config(tmp_path))(_message(), _decision(), result)

    assert enriched.body == result.body, "增益腿挂死不得伤正文（fail-open 红线）"
    assert not enriched.audio
    issue = enriched.operational_issue
    assert issue is not None, "非成功终态必须挂 issue（M-13 自动半在册）"
    assert issue.kind == "tts_synthesize_failed", "kind 唯一由 _FAILURE_KINDS 前缀表裁决"
    # 消费点本体：载荷异常的类型名与消息都进了证据串（旧代码逐字无视）。
    assert "CapabilityTimeout" in issue.safe_summary
    assert "超过中央预算 90s" in issue.safe_summary
    assert len(invoker.requests) == 1


def test_leg_consumes_degraded_payload_beyond_detail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """DEGRADED（诚实降级）形：中央 detail 不带异常原文时，载荷 RuntimeError 的
    身份必须进证据串——运维从「一句降级说明」升级为「可归因的真异常」。"""
    invoker = _ScriptedInvoker(
        _envelope(
            cp.InvocationStatus.DEGRADED,
            "主链失败；诚实降级：产出步不可用",
            {cp.INVOKER_ERROR_DATA_KEY: RuntimeError("真因G2XYZ 引擎连接被掐")},
        )
    )
    monkeypatch.setattr(ve, "default_invoker", lambda: invoker)
    _never_synthesize(monkeypatch)

    enriched = ve.build_voice_enricher(_hook_config(tmp_path))(_message(), _decision(), _chat_result())

    issue = enriched.operational_issue
    assert issue is not None and issue.kind == "tts_synthesize_failed"
    assert "RuntimeError" in issue.safe_summary and "真因G2XYZ" in issue.safe_summary
    assert enriched.body == "潮汐很安静"


# ---------------------------------------------------------------------------
# 3 · 载荷缺席/形不对 ⇒ 逐字退化 detail（分类学不被追加逻辑扰动）
# ---------------------------------------------------------------------------


def test_leg_payload_absent_degrades_to_detail_and_taxonomy_intact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """无载荷的 FAILED（中央私有 handler 直产信封的形态，S50 M6a 同源）：证据串
    =detail 原文，前缀表照常给 ``tts_service_unreachable``/可重试——追加逻辑零扰动。"""
    invoker = _ScriptedInvoker(
        _envelope(
            cp.InvocationStatus.FAILED,
            "服务不可达：注入式断网",
            {},
        )
    )
    monkeypatch.setattr(ve, "default_invoker", lambda: invoker)
    _never_synthesize(monkeypatch)
    enriched = ve.build_voice_enricher(_hook_config(tmp_path))(_message(), _decision(), _chat_result())

    issue = enriched.operational_issue
    assert issue is not None
    assert (issue.kind, issue.retryable) == ("tts_service_unreachable", True)
    assert "invoker载荷" not in issue.safe_summary, "无载荷不得伪造身份段"


def test_leg_payload_wrong_shape_degrades_to_detail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """键在场但不是异常对象（垃圾形态）：诚实退化 detail，绝不 str() 一把梭。"""
    invoker = _ScriptedInvoker(
        _envelope(
            cp.InvocationStatus.FAILED,
            "主链与降级链全部失败：ValueError",
            {cp.INVOKER_ERROR_DATA_KEY: "这不是异常对象"},
        )
    )
    monkeypatch.setattr(ve, "default_invoker", lambda: invoker)
    _never_synthesize(monkeypatch)

    enriched = ve.build_voice_enricher(_hook_config(tmp_path))(_message(), _decision(), _chat_result())

    issue = enriched.operational_issue
    assert issue is not None
    assert "这不是异常对象" not in issue.safe_summary
    assert enriched.body == "潮汐很安静"


# ---------------------------------------------------------------------------
# 4 · 出口枚举（真实 pipeline）：唯一出口=SendRequest.issue；卡钩子零触达
# ---------------------------------------------------------------------------


def test_leg_egress_is_issue_only_card_hook_and_bubble_stay_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, card_tripwire: list[Any]
) -> None:
    """过审正文照常入队、载荷身份随 **SendRequest.operational_issue** 这唯一出口
    入告警链；error_report 卡钩子零触达（本腿不出卡）；无异常逃逸（fail-open）。"""
    timeout_error = cp.CapabilityTimeout("media.tts.autodub 超过中央预算 90s")
    invoker = _ScriptedInvoker(
        _envelope(
            cp.InvocationStatus.TIMEOUT,
            "超时 90s（线程跑到自然结束，结果弃用）",
            {cp.INVOKER_ERROR_DATA_KEY: timeout_error},
        )
    )
    monkeypatch.setattr(ve, "default_invoker", lambda: invoker)
    _never_synthesize(monkeypatch)
    pipeline, queue = _make_pipeline(ve.build_voice_enricher(_hook_config(tmp_path)))

    receipt = asyncio.run(
        pipeline.handle_async(_message(), _static_capability(_chat_result()), "bot.chat")
    )

    request = queue.sent_requests[-1]
    assert receipt.state == ReceiptState.SENT, "正文必须照常投递（增益失败不压体）"
    assert request.operational_issue is not None
    assert "CapabilityTimeout" in request.operational_issue.safe_summary
    assert request.operational_issue.kind == "tts_synthesize_failed"
    assert card_tripwire == [], "hook 腿结构性不出卡：卡旁路一次都不许被触达"


# ---------------------------------------------------------------------------
# 5 · GAP-HOOK-STRUCTURAL-NO-CARD（显式命名缺口锁：两口径代价钉死）
# ---------------------------------------------------------------------------


def test_gap_hook_structural_no_card_raise_would_kill_reply(
    tmp_path: Path, card_tripwire: list[Any]
) -> None:
    """GAP-HOOK-STRUCTURAL-NO-CARD：既有卡旁路（``_internal_error``）与「回复存活」
    在 hook 腿互斥——把载荷 raise 给它的真实终态是**整条过审正文作废**：
    队列零请求、回执 FAILED_FINAL、issue 翻成 ``internal_error``（丢配音归因）。

    本锁同时是裁定请求的证据 A 案（raise=出卡）的代价：代价不是假想，是实跑终态。
    将来若装配面给了 hook 安全的出卡路（裁定 B/C 案落地），本锁第二断言组翻面⇒摘牌。
    """
    boom = cp.CapabilityTimeout("media.tts.autodub 超过中央预算 90s")

    def raising_enricher(message: Any, decision: Any, result: Any) -> Any:
        raise boom  # 「与 image provider 同法」的字面版：把载荷交回层 1

    pipeline, queue = _make_pipeline(raising_enricher)
    receipt = asyncio.run(
        pipeline.handle_async(_message(), _static_capability(_chat_result()), "bot.chat")
    )

    # A 案代价（实跑）：卡有了，回复没了。
    assert len(queue.sent_requests) == 0, "raise 版=正文根本没入队"
    assert receipt.state == ReceiptState.FAILED_FINAL
    assert receipt.operational_issue is not None
    assert receipt.operational_issue.kind == "internal_error"
    assert receipt.operational_issue.safe_summary == "bot.chat:CapabilityTimeout"
    assert len(card_tripwire) == 1 and card_tripwire[0][1] is boom


def test_gap_hook_structural_no_card_today_evidence_is_issue_borne(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, card_tripwire: list[Any]
) -> None:
    """缺口锁第二组：现行实现（B 案=载荷进 issue、不出卡）下，挂死满预算对
    用户的可见面=只有文字回复；对运维的可见面=告警链里带 ``CapabilityTimeout``
    身份的一条 issue。卡三面（error_report）零触达——「在册未执法」从散文变成
    显式命名锁，等裁的不是实现缺失，是两口径取舍本身。"""
    timeout_error = cp.CapabilityTimeout("media.tts.autodub 超过中央预算 90s")
    invoker = _ScriptedInvoker(
        _envelope(
            cp.InvocationStatus.TIMEOUT,
            "超时 90s（线程跑到自然结束，结果弃用）",
            {cp.INVOKER_ERROR_DATA_KEY: timeout_error},
        )
    )
    monkeypatch.setattr(ve, "default_invoker", lambda: invoker)
    _never_synthesize(monkeypatch)
    enricher = ve.build_voice_enricher(_hook_config(tmp_path))

    enriched = enricher(_message(), _decision(), _chat_result())
    assert card_tripwire == [], "现行腿不存在任何触卡路径（结构性，非遗漏）"
    assert enriched.operational_issue is not None
    assert "CapabilityTimeout" in enriched.operational_issue.safe_summary


# ---------------------------------------------------------------------------
# 6 · 注毒自证（物理改生产件 ⇒ 断言必红 ⇒ 还原比 sha）——见 SEAT-S64 §三
#
# 三发注毒在席位执行时以「备份-注毒-跑-还原-sha」流程物理施行（本席独占写面
# 含 voice_enricher.py），不在测试件内自动改源码（防套件自身变成注毒器）。
# 每发的预期杀伤：
#   INJ-A 摘掉读载荷腿（分支退回 `_failure_issue(message, invocation.detail)`）
#         → test_leg_consumes_timeout_payload_into_issue_evidence /
#           test_leg_consumes_degraded_payload_beyond_detail /
#           test_leg_egress_is_issue_only_card_hook_and_bubble_stay_zero /
#           test_gap_hook_structural_no_card_today_evidence_is_issue_borne 红
#   INJ-B 把交回换成只记日志（非成功分支 logger 后原样返回 result）
#         → 上述四件全红（issue 根本没挂）+ test_leg_payload_wrong_shape 红
#   INJ-C 把 fail-open 改成冒泡（分支 raise 载荷 ∧ catch-all 直 raise）
#         → 直调类用例当场被异常打红；egress 用例红在「正文未入队/卡钩子被触达」
# ---------------------------------------------------------------------------


def test_injection_guard_baseline_sha_matches_seat_ledger() -> None:
    """自证锚：注毒流程前后本文件记录的干净基线哈希必须咬住现盘字节。
    （该锁只在席位执行期有意义——还原后复跑本件全绿即证注毒未残留。）"""
    import hashlib
    from pathlib import Path as _P

    src = _P("plugins/bot_unified_runtime/domains/media/voice_enricher.py")
    digest = hashlib.sha256(src.read_bytes()).hexdigest()[:16]
    assert digest == _CLEAN_SHA16, (
        "voice_enricher.py 现盘字节 != 本席干净基线（注毒残留或他席改动——"
        "先分清是谁再动笔）"
    )
