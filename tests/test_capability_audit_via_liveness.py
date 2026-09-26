"""席位 S61：中央执行「可观测闭环」的活性锁（把 #49 的散文变成会咬人的门）。

判据来源 = AGENTS #49「已落地八面」第⑤条的可观测子项：
    "中央审计 sink 生产注册且幂等、``via`` 带执行体模块.限定名、
     ``request_id/session_key`` 关联键、崩溃经 ``INVOKER_ERROR_DATA_KEY`` 交回层 1"

本波反复栽在「字段存在」被写成「已执法/已生效」。`CapabilityAuditRecord` 早就*有*
``via``/``request_id``/``session_key`` 三个字段（存在性），但「存在」不等于「emit 时
真把执行体身份、真把关联键原样搬进记录」。本件用**实跑一次 invoke + 捕获审计记录**的
方式把下面五判据钉成活性锁：

① ``via`` 真身：经生产 prepared 信封跑一次，审计记录的 via 必须是执行体的
   ``caller_capability:<模块>.<限定名>``，不是常量 ``"invoker"``、不是空串。
② 层 2 feature 门把 DENIED 终态的 via 也写进审计（``"feature_gate"``），且与 handler
   成功路的 via 可判别（别混淆两条路）。
③ ``request_id``/``session_key`` 关联键在**默认空值**与**非空值**两侧都必须原样进审计
   ——空值不得被吞成 ``None``、不得缺键。
④ 崩溃交回腿：抛异常的 handler ⇒ 终态 ``data`` 带 ``INVOKER_ERROR_DATA_KEY`` 且异常类型可归因。
⑤ 幂等：同一 sink 重复注册不得让一次 invoke 双写（``AuditHookRegistry`` 确有去重 ⇒ 锁住；
   生产口子 ``attach_default_audit_sink`` 同钩子两次 attach ⇒ 只落一条）。

全离线：零网络、零消息、零真实 store；不往 ``default_invoker()`` 单例留测试态钩子
（⑤ 的产线幂等锁在 finally 里逐字节还原）。
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from plugins.bot_unified_runtime.domains.ops.features.feature_catalog import (
    RECOVERY_CAPABILITIES,
)
from plugins.bot_unified_runtime.domains.ops.features.feature_gate import FeatureAccess
from plugins.bot_unified_runtime.runtime.capability_protocols import (
    CAPABILITY_DESCRIPTOR,
    HONEST_DEGRADE_PREFIX,
    INVOKER_ERROR_DATA_KEY,
    CapabilityDescriptor,
    CapabilityFamily,
    CapabilityInvoker,
    CapabilityRegistry,
    CapabilityRequest,
    FallbackRegistry,
    HandlerRegistry,
    HealthProbeRegistry,
    InvocationResult,
    InvocationStatus,
    _make_prepared_handler,
    attach_default_audit_sink,
    default_invoker,
    gate_feature_bindings,
)

ROOT = Path(__file__).resolve().parents[1]
SELF_MODULE = __name__

# 现算派生的受门样本（起点==实测：空集即当场红，不给空跑留活路）——与
# tests/test_feature_gate_layer2.py 同源，不手写受害 id。
BOUND = sorted(set(gate_feature_bindings()) - set(RECOVERY_CAPABILITIES))


# ---------------------------------------------------------------------------
# 公共夹具
# ---------------------------------------------------------------------------


class _Presented:
    """最小呈现契约替身：prepared 信封只要求它有 ``model_dump()`` 且返回 dict。"""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def model_dump(self) -> dict[str, Any]:  # 契约替身
        return dict(self._payload)


def _real_execution_body(message: Any, decision: Any) -> _Presented:
    """「执行体」本身——via 真身锁要断言审计里出现的正是**它**的模块.限定名。

    刻意命名成一个可被 qualname 唯一识别的顶层函数：注毒把 via 写成常量时，
    这个名字不再出现在审计记录里 ⇒ 锁当场红。
    """
    return _Presented({"kind": "text", "handled": True})


class _RecordingSink:
    """审计钩子：收集 emit 出来的记录；``records`` 供逐判据断言。"""

    def __init__(self) -> None:
        self.records: list[Any] = []

    def __call__(self, record: Any) -> None:
        self.records.append(record)


def _descriptor(
    capability_id: str,
    *,
    fallback_chain: tuple[str, ...] = (),
    timeout_seconds: float = 5.0,
) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id=capability_id,
        family=CapabilityFamily.MEDIA,
        title="S61 可观测活性锁测试能力",
        input_protocol="test.v1{in}",
        output_protocol="test.v1{out}",
        required_roles=("user",),
        timeout_seconds=timeout_seconds,
        limits={},
        limit_fields=(),
        fallback_chain=fallback_chain,
        implementation_ref=(
            "plugins/bot_unified_runtime/runtime/capability_protocols.py#CapabilityInvoker"
        ),
        notes="S61 测试专用描述符",
    )


def _mini_invoker(*, feature_gate: Any = None) -> CapabilityInvoker:
    return CapabilityInvoker(
        registry=CapabilityRegistry(),
        handlers=HandlerRegistry(),
        fallbacks=FallbackRegistry(),
        probes=HealthProbeRegistry(),
        feature_gate=feature_gate,
    )


def _request(
    capability_id: str,
    *,
    payload: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    request_id: str = "",
    session_key: str = "",
) -> CapabilityRequest:
    return CapabilityRequest(
        capability_id=capability_id,
        payload=payload or {},
        principal="tester",
        roles=("user",),
        context=context or {},
        request_id=request_id,
        session_key=session_key,
    )


def _prepared_ok_invoker(
    capability_id: str, *, sink: _RecordingSink, body: Any = _real_execution_body
) -> CapabilityInvoker:
    """装好 prepared 信封 + 审计 sink 的 invoker：invoke 一次走成功路（emit 落 handler 侧）。"""
    invoker = _mini_invoker()
    invoker.registry.register(_descriptor(capability_id))
    invoker.handlers.register(
        capability_id,
        _make_prepared_handler(
            "plugins/bot_unified_runtime/runtime/capability_protocols.py#_make_prepared_handler"
        ),
    )
    invoker.audit_hooks.register(sink)
    return invoker


# ===========================================================================
# ① via 真身：审计记录带的是执行体的 module.qualname，不是常量、不是空串
# ===========================================================================


class TestViaIsRealExecutionBody:
    def test_both_samples_exist(self) -> None:
        assert CAPABILITY_DESCRIPTOR, "唯一在册表为空＝本件多条锁失去前提"
        assert BOUND, "找不到非恢复类受门能力＝② 的 feature_gate 路无从证明有牙"

    def test_audit_via_equals_execution_body_module_qualname(self) -> None:
        sink = _RecordingSink()
        invoker = _prepared_ok_invoker("test.s61.via", sink=sink)
        result = invoker.invoke(
            _request(
                "test.s61.via",
                payload={"message": object()},
                context={"capability": _real_execution_body, "decision": None},
            ),
            config=SimpleNamespace(),
        )
        assert result.status is InvocationStatus.OK
        # 期望值从**执行体自身的 __module__/__qualname__ 现算**，不复用被测的
        # _callable_identity——否则等于拿被测函数自证（测夹具不测代码）。
        expected_via = (
            f"caller_capability:{_real_execution_body.__module__}."
            f"{_real_execution_body.__qualname__}"
        )
        assert len(sink.records) == 1, f"审计应落一条，实得 {len(sink.records)}"
        record = sink.records[0]
        assert record.via == expected_via
        # 三禁：常量 / 空串 / 缺分隔点，任一亮起即说明 via 没带真身身份。
        assert record.via != "invoker", "via 退化成常量＝可观测闭环是假话"
        assert record.via != "", "via 空串＝审计里查不到是谁跑的"
        assert "." in record.via, "via 无 module.qualname 分隔点"
        assert record.via.startswith("caller_capability:")
        # 身份子串必须真在里面（把 via 换成任何别的字符串都会让这两条红）。
        assert _real_execution_body.__qualname__ in record.via
        assert _real_execution_body.__module__ in record.via
        # 审计路（emit 的 via）与返回信封的 via 同源，二者不得各写一套。
        assert record.via == result.via

    def test_not_wired_terminal_via_is_still_not_blank_handler(self) -> None:
        """对照：能力未接线时 via 是 ``invoker``（诚实归因到调用器），
        这与 ① 的 handler 真身份是**不同终态**——证明 via 是随终态派生的、不是被抹平的常量。"""
        sink = _RecordingSink()
        invoker = _mini_invoker()
        invoker.registry.register(_descriptor("test.s61.notwired"))
        # 故意不注册 handler → UNAVAILABLE via="invoker"（走 _finish emit）
        invoker.audit_hooks.register(sink)
        result = invoker.invoke(_request("test.s61.notwired"))
        assert result.status is InvocationStatus.UNAVAILABLE
        assert sink.records[0].via == "invoker"
        assert result.via == "invoker"


# ===========================================================================
# ② 层 2 feature 门的 via=="feature_gate" 也进审计，且与 handler 路可判别
# ===========================================================================


class TestFeatureGateViaReachesAudit:
    def _deny(self, capability_id: str) -> FeatureAccess:
        return FeatureAccess(
            False, "feature_disabled", gate_feature_bindings().get(capability_id)
        )

    def test_feature_gate_denial_via_lands_in_audit(self) -> None:
        sink = _RecordingSink()
        invoker = _mini_invoker(feature_gate=self._deny)
        cid = BOUND[0]
        invoker.registry.register(_descriptor(cid))

        handler_calls: list[Any] = []

        def _would_run(request: CapabilityRequest) -> InvocationResult:
            handler_calls.append(request)
            return InvocationResult(capability_id=request.capability_id, status=InvocationStatus.OK)

        invoker.handlers.register(cid, _would_run)
        invoker.audit_hooks.register(sink)

        result = invoker.invoke(_request(cid))
        assert result.status is InvocationStatus.DENIED
        assert handler_calls == [], "功能门必须在 handler 之前拦下"
        assert len(sink.records) == 1
        record = sink.records[0]
        assert record.via == "feature_gate"
        assert record.status is InvocationStatus.DENIED

    def test_feature_gate_via_distinguished_from_handler_via(self) -> None:
        """两条路的 via 可判别：handler 成功路绝不等于 feature_gate，反之亦然。"""
        # handler 路（同 ①）
        sink_handler = _RecordingSink()
        _prepared_ok_invoker("test.s61.dist", sink=sink_handler).invoke(
            _request(
                "test.s61.dist",
                payload={"message": object()},
                context={"capability": _real_execution_body, "decision": None},
            )
        )
        handler_via = sink_handler.records[0].via
        # 门路
        sink_gate = _RecordingSink()
        invoker = _mini_invoker(feature_gate=self._deny)
        invoker.registry.register(_descriptor(BOUND[0]))
        invoker.audit_hooks.register(sink_gate)
        invoker.invoke(_request(BOUND[0]))
        gate_via = sink_gate.records[0].via
        assert gate_via == "feature_gate"
        assert handler_via != gate_via
        assert handler_via != "feature_gate"


# ===========================================================================
# ③ request_id / session_key 关联键：默认空值与非空值都原样进审计，不吞 None 不缺键
# ===========================================================================


class TestCorrelationKeysReachAudit:
    def test_record_type_has_both_correlation_fields(self) -> None:
        from plugins.bot_unified_runtime.runtime.capability_protocols import (
            CapabilityAuditRecord,
        )

        names = {f.name for f in dataclasses.fields(CapabilityAuditRecord)}
        assert {"request_id", "session_key"} <= names, "关联键连字段都没有＝谈不上执法"

    def test_default_empty_correlation_survives_verbatim(self) -> None:
        sink = _RecordingSink()
        invoker = _prepared_ok_invoker("test.s61.corr", sink=sink)
        invoker.invoke(
            _request(
                "test.s61.corr",
                payload={"message": object()},
                context={"capability": _real_execution_body, "decision": None},
            )
        )
        record = sink.records[0]
        # 默认空值：必须是**空串**（请求侧真值），既不能被吞成 None、也不能凭空造非空值。
        assert record.request_id == ""
        assert record.session_key == ""
        assert record.request_id is not None
        assert record.session_key is not None
        assert type(record.request_id) is str
        assert type(record.session_key) is str

    def test_nonempty_correlation_forwarded_verbatim(self) -> None:
        sink = _RecordingSink()
        invoker = _prepared_ok_invoker("test.s61.corr2", sink=sink)
        invoker.invoke(
            _request(
                "test.s61.corr2",
                payload={"message": object()},
                context={"capability": _real_execution_body, "decision": None},
                request_id="req-s61-77",
                session_key="group_999_888",
            )
        )
        record = sink.records[0]
        assert record.request_id == "req-s61-77"
        assert record.session_key == "group_999_888"


# ===========================================================================
# ④ 崩溃交回腿：抛异常的 handler ⇒ 终态 data 带 INVOKER_ERROR_DATA_KEY、类型可归因
# ===========================================================================


class TestCrashReturnsViaErrorKey:
    def test_handler_exception_carried_into_terminal_data(self) -> None:
        sink = _RecordingSink()
        invoker = _mini_invoker()
        invoker.registry.register(
            _descriptor(
                "test.s61.crash",
                fallback_chain=(HONEST_DEGRADE_PREFIX + "S61 无解降级",),
            )
        )

        class _S61Boom(ValueError):
            pass

        def _raise(request: CapabilityRequest) -> InvocationResult:
            raise _S61Boom("boom-attributable")

        invoker.handlers.register("test.s61.crash", _raise)
        invoker.audit_hooks.register(sink)

        result = invoker.invoke(_request("test.s61.crash"))
        # 无注册降级腿崩了、只有 honest_degrade ⇒ 终态 DEGRADED，但异常必须原样交回层 1。
        assert result.status is InvocationStatus.DEGRADED
        assert INVOKER_ERROR_DATA_KEY in result.data, "崩溃未交回＝诊断卡拿不到原始异常"
        carried = result.data[INVOKER_ERROR_DATA_KEY]
        assert isinstance(carried, _S61Boom), f"交回体类型不可归因：{type(carried)!r}"
        assert "boom-attributable" in str(carried)
        # 呈现载荷（结果体）绝不因崩溃而被冒充。
        assert "presentation_result" not in result.data

    def test_timeout_also_returns_error_key(self) -> None:
        import time

        from plugins.bot_unified_runtime.runtime.capability_protocols import (
            CapabilityTimeout,
        )

        sink = _RecordingSink()
        invoker = _mini_invoker()
        invoker.registry.register(_descriptor("test.s61.slow", timeout_seconds=0.05))

        def _slow(request: CapabilityRequest) -> InvocationResult:
            time.sleep(0.5)
            return InvocationResult(
                capability_id=request.capability_id, status=InvocationStatus.OK
            )

        invoker.handlers.register("test.s61.slow", _slow)
        invoker.audit_hooks.register(sink)
        result = invoker.invoke(_request("test.s61.slow"))
        assert result.status is InvocationStatus.TIMEOUT
        carried = result.data.get(INVOKER_ERROR_DATA_KEY)
        assert isinstance(carried, CapabilityTimeout), "挂死未包成交回异常＝卡仍不出"


# ===========================================================================
# ⑤ 幂等：同一 sink 重复注册不得双写（registry 去重 + 生产口子幂等）
# ===========================================================================


class TestSinkRegistrationIdempotent:
    def test_same_hook_twice_emits_once(self) -> None:
        sink = _RecordingSink()
        invoker = _mini_invoker()
        invoker.registry.register(_descriptor("test.s61.dedupe"))
        invoker.handlers.register(
            "test.s61.dedupe",
            _make_prepared_handler(
                "plugins/bot_unified_runtime/runtime/capability_protocols.py#_make_prepared_handler"
            ),
        )
        invoker.audit_hooks.register(sink)
        invoker.audit_hooks.register(sink)  # 同一对象二次注册 ⇒ 去重
        invoker.invoke(
            _request(
                "test.s61.dedupe",
                payload={"message": object()},
                context={"capability": _real_execution_body, "decision": None},
            )
        )
        assert len(sink.records) == 1, (
            f"同一 sink 重复注册后一次 invoke 落 {len(sink.records)} 行＝双写，去重失效"
        )

    def test_distinct_hooks_both_emit(self) -> None:
        """反向锁：去重只认同一对象，两个不同 sink 各收一份（防把去重写成'只留第一个'）。"""
        sink_a = _RecordingSink()
        sink_b = _RecordingSink()
        invoker = _mini_invoker()
        invoker.registry.register(_descriptor("test.s61.two"))
        invoker.handlers.register(
            "test.s61.two",
            _make_prepared_handler(
                "plugins/bot_unified_runtime/runtime/capability_protocols.py#_make_prepared_handler"
            ),
        )
        invoker.audit_hooks.register(sink_a)
        invoker.audit_hooks.register(sink_b)
        invoker.invoke(
            _request(
                "test.s61.two",
                payload={"message": object()},
                context={"capability": _real_execution_body, "decision": None},
            )
        )
        assert len(sink_a.records) == 1 and len(sink_b.records) == 1

    def test_production_attach_is_idempotent(self) -> None:
        """#49 的「sink 生产注册且幂等」：同钩子两次 attach_default_audit_sink 只落一条。

        在产线单例上操作 ⇒ finally 逐字节还原 ``_hooks``，绝不把测试态钩子漏给后续调用方
        （tests/test_v21_s10_protocols.py 的旧症：往单例注册钩子会永久粘给同会话每个调用方）。
        """
        registry = default_invoker().audit_hooks
        original = list(registry._hooks)  # 锁产线幂等需读私有表，finally 还原

        def _probe(record: Any) -> None:  # 稳定同一对象
            return None

        try:
            attach_default_audit_sink(_probe)
            after_first = list(registry._hooks)
            attach_default_audit_sink(_probe)  # 第二次同对象
            after_second = list(registry._hooks)
            assert len(after_first) == len(original) + 1, (
                f"attach 一次应加一条：{len(original)} -> {len(after_first)}"
            )
            assert len(after_second) == len(original) + 1, (
                f"同钩子二次 attach 不得再加：{len(original)} -> {len(after_second)}"
            )
            assert any(h is _probe for h in after_second)
        finally:
            registry._hooks[:] = original  # 还原，不留测试态
