"""层 2 feature 门执法（中央调度收编波 P4 · 收编「`invoke()` 不读 gate_feature_id」）。

判据来源＝S43 施工图 §1（实算：120 descriptors / 76 gate_scoped / 44 未受门；
四条**绕过 pipeline 直呼 `default_invoker().invoke()`** 的能力全部未受门）。因此本案
唯一的执法形是「只对在**册且受门**者执法、未受门 pass-through」，照抄层 1 的
「未登记即拒」会把那四条今天真在跑的直接调用当场挡死——所以本文件最重要的一条锁
是 ``test_unbound_capability_passes_through_even_when_gate_denies``。

受门/未受门两侧的用例 id 一律**从唯一在册表现算派生**（不手写 id）：手写的受害 cid
会让锁变成空跑（统一波自打脸账同点）。

全离线：零网络、零消息、零真实 FeatureControlService（store 不建库）。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.domains.chat_reply.policy.roles import ROLE_BLOCKED
from plugins.bot_unified_runtime.domains.ops.features.feature_catalog import (
    RECOVERY_CAPABILITIES,
)
from plugins.bot_unified_runtime.domains.ops.features.feature_gate import (
    FeatureAccess,
    ProductFeatureGate,
)
from plugins.bot_unified_runtime.runtime.capability_protocols import (
    CAPABILITY_DESCRIPTOR,
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
    attach_default_feature_gate,
    gate_feature_bindings,
)

ROOT = Path(__file__).resolve().parents[1]
PROTOCOLS = ROOT / "plugins/bot_unified_runtime/runtime/capability_protocols.py"
FEATURE_GATE = ROOT / "plugins/bot_unified_runtime/domains/ops/features/feature_gate.py"
RUNTIME_ROOT = ROOT / "plugins/bot_unified_runtime/__init__.py"

# ---- 现算派生的两侧样本（起点==实测：空集即当场红，不给空跑留活路）-------------

BOUND = sorted(set(gate_feature_bindings()) - set(RECOVERY_CAPABILITIES))
UNBOUND = sorted(set(CAPABILITY_DESCRIPTOR) - set(gate_feature_bindings()))


def _ok_handler(request: CapabilityRequest) -> InvocationResult:
    return InvocationResult(capability_id=request.capability_id, status=InvocationStatus.OK)


def _mini_invoker(
    capability_id: str,
    *,
    predicate: Any = None,
) -> tuple[CapabilityInvoker, list[CapabilityRequest]]:
    """自有注册面的 invoker（绝不碰默认单例，避免席位间互相污染）。"""
    invoker = CapabilityInvoker(
        registry=CapabilityRegistry(),
        handlers=HandlerRegistry(),
        fallbacks=FallbackRegistry(),
        probes=HealthProbeRegistry(),
        feature_gate=predicate,
    )
    invoker.registry.register(
        CapabilityDescriptor(
            capability_id=capability_id,
            family=CapabilityFamily.MEDIA,
            title="层 2 门测试能力",
            input_protocol="test.v1{in}",
            output_protocol="test.v1{out}",
            required_roles=("user",),
            timeout_seconds=5.0,
            limits={},
            limit_fields=(),
            fallback_chain=(),
            implementation_ref=(
                "plugins/bot_unified_runtime/runtime/capability_protocols.py#CapabilityInvoker"
            ),
            notes="测试专用描述符",
        )
    )
    seen: list[CapabilityRequest] = []

    def _handler(request: CapabilityRequest) -> InvocationResult:
        seen.append(request)
        return _ok_handler(request)

    invoker.handlers.register(capability_id, _handler)
    return invoker, seen


def _request(capability_id: str, *, roles: tuple[str, ...] = ("user",)) -> CapabilityRequest:
    return CapabilityRequest(
        capability_id=capability_id, payload={}, principal="tester", roles=roles, context={}
    )


def _deny(capability_id: str) -> FeatureAccess:
    return FeatureAccess(False, "feature_disabled", gate_feature_bindings().get(capability_id))


class _StubService:
    """只喂 ``check_capability`` 真身读到的那一个出口（不建库、不起控制面）。"""

    def __init__(self, *, enabled: bool = False, broken: bool = False) -> None:
        self.enabled = enabled
        self.broken = broken
        self.seen: list[str] = []

    def detail(self, feature_id: str) -> dict[str, Any]:
        self.seen.append(feature_id)
        if self.broken:
            raise RuntimeError("store down")
        return {"state": {"effective_enabled": self.enabled, "graph_revision": 3}}

    def state_snapshot(self) -> tuple[Any, ...]:  # pragma: no cover - 本文件不测快照面
        return ()


# ===========================================================================
# 一、执法形本身
# ===========================================================================


class TestLayer2Enforcement:
    def test_both_samples_exist(self) -> None:
        """两侧样本非空，否则下面每一条都是空跑（判据地板，不是成绩）。"""
        assert BOUND, "唯一在册表里找不到非恢复类受门能力——执法锁无从证明有牙"
        assert UNBOUND, "唯一在册表里找不到未受门能力——pass-through 锁无从证明有牙"

    def test_bound_capability_denied_at_layer2(self) -> None:
        invoker, seen = _mini_invoker(BOUND[0], predicate=_deny)
        result = invoker.invoke(_request(BOUND[0]))
        assert result.status is InvocationStatus.DENIED
        assert result.via == "feature_gate"
        assert "feature_disabled" in result.detail
        assert f"feature_id={gate_feature_bindings()[BOUND[0]]}" in result.detail
        assert seen == [], "拒绝必须发生在 handler 之前，不能跑完再改口"

    def test_unbound_capability_passes_through_even_when_gate_denies(self) -> None:
        """最危险反例锁：层 2 绝不照抄层 1 的「未登记→拒绝」。

        注毒「把 ``if bound is not None`` 去掉＝对所有 id 无门可查即拒」⇒ 本条必红
        ⇒ 等价于今天把 ``search.web``/``media.vision.anime_ip``/
        ``creation.tts.synthesize``/``media.tts.autodub`` 四条直呼路当场挡死。
        """
        cid = next(item for item in UNBOUND if item not in RECOVERY_CAPABILITIES)
        invoker, seen = _mini_invoker(cid, predicate=lambda _cid: FeatureAccess(False, "any_reason"))
        result = invoker.invoke(_request(cid))
        assert result.status is InvocationStatus.OK, "未受门能力被功能门拒掉＝越权执法"
        assert len(seen) == 1

    def test_predicate_exception_fails_closed(self) -> None:
        def _broken(_cid: str) -> FeatureAccess:
            raise RuntimeError("store down")

        invoker, seen = _mini_invoker(BOUND[0], predicate=_broken)
        result = invoker.invoke(_request(BOUND[0]))
        assert result.status is InvocationStatus.DENIED
        assert "feature_state_unavailable" in result.detail
        assert seen == []
        assert "store down" not in result.detail, "底层异常不得外泄进终态文案"

    def test_no_predicate_injected_keeps_status_quo(self) -> None:
        """缺省 None＝本波之前的逐字节现状（现网行为中性这条口径的锁）。"""
        invoker, seen = _mini_invoker(BOUND[0], predicate=None)
        result = invoker.invoke(_request(BOUND[0]))
        assert result.status is InvocationStatus.OK
        assert len(seen) == 1

    def test_gate_precedes_role_gate_to_match_layer1(self) -> None:
        """层 1 ``_prepare`` 的 feature gate 是第一道 ⇒ 层 2 同序（同一能力两层同序）。"""
        invoker, _seen = _mini_invoker(BOUND[0], predicate=_deny)
        result = invoker.invoke(_request(BOUND[0], roles=("user", ROLE_BLOCKED)))
        assert result.via == "feature_gate", "先答角色再答功能门＝与层 1 序不一致"

    def test_denial_is_a_real_terminal_state_in_audit(self) -> None:
        """终态判据而非「调了没调」——防「字段存在≠执法」重演。"""
        records: list[Any] = []
        invoker, _seen = _mini_invoker(BOUND[0], predicate=_deny)
        invoker.audit_hooks.register(records.append)
        result = invoker.invoke(_request(BOUND[0]))
        assert len(records) == 1
        assert records[0].status is InvocationStatus.DENIED
        assert records[0].via == "feature_gate"
        assert result.elapsed_ms >= 0


# ===========================================================================
# 二、单一真身纪律（禁第二份名单、禁第二套门序）
# ===========================================================================


class TestSingleSourceDiscipline:
    def test_call_is_pure_forward_to_check_capability(self) -> None:
        """``__call__`` 只准转发：判定真身唯一住 ``check_capability``。

        这条锁的杀伤力＝有人往 ``__call__`` 里重新塞回 message 相关判定，或把
        ``check_capability`` 掏空成另一套逻辑 ⇒ 层 1/层 2 从此分叉，本条当场红。
        """
        tree = ast.parse(FEATURE_GATE.read_text(encoding="utf-8"))
        klass = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name == "ProductFeatureGate"
        )
        call = next(
            node
            for node in klass.body
            if isinstance(node, ast.FunctionDef) and node.name == "__call__"
        )
        body = [
            stmt
            for stmt in call.body
            if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant))
        ]
        assert len(body) == 1 and isinstance(body[0], ast.Return), "__call__ 必须是纯转发"
        returned = body[0].value
        assert isinstance(returned, ast.Call), "__call__ 必须直接返回 check_capability 的结果"
        assert (
            isinstance(returned.func, ast.Attribute)
            and returned.func.attr == "check_capability"
            and isinstance(returned.func.value, ast.Name)
            and returned.func.value.id == "self"
        )
        assert [ast.dump(a) for a in returned.args] == [
            ast.dump(ast.Name(id="capability_id", ctx=ast.Load()))
        ], "转发只准带 capability_id"
        assert "message" not in ast.dump(body[0]), "判定不得回读 message（层 2 拿不到它）"

    def test_layer2_never_copies_gate_or_recovery_lists(self) -> None:
        """层 2 只准读唯一在册表的 ``gate_feature_bindings``，禁抄第二份受门/恢复名单。"""
        tree = ast.parse(PROTOCOLS.read_text(encoding="utf-8"))
        banned = {"RECOVERY_CAPABILITIES", "capability_feature_bindings"}
        hits = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and node.id in banned
        } | {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in banned
        }
        assert not hits, f"层 2 抄了第二份名单：{sorted(hits)}"

    def test_gate_level_recovery_bypass(self) -> None:
        gate = ProductFeatureGate(_StubService(enabled=False))  # type: ignore[arg-type]
        recovery_id = min(RECOVERY_CAPABILITIES)
        access = gate.check_capability(recovery_id)
        assert access.allowed and access.reason == "protected_recovery"

    def test_gate_level_disabled_denies_with_bound_feature(self) -> None:
        service = _StubService(enabled=False)
        gate = ProductFeatureGate(service)  # type: ignore[arg-type]
        access = gate.check_capability(BOUND[0])
        assert not access.allowed
        assert access.reason == "feature_disabled"
        assert service.seen == [gate_feature_bindings()[BOUND[0]]]

    def test_attach_helper_is_the_only_injection_door(self) -> None:
        """装配只经壳侧口子；``attach_default_feature_gate`` 自身必须真落到单例上。"""
        import plugins.bot_unified_runtime.runtime.capability_protocols as protocols

        original = protocols.default_invoker().feature_gate
        try:
            attach_default_feature_gate(lambda _cid: FeatureAccess(False, "poison_probe"))
            assert protocols.default_invoker().feature_gate is not None
            result = protocols.default_invoker().invoke(
                CapabilityRequest(
                    capability_id=BOUND[0],
                    payload={},
                    principal="tester",
                    roles=("user",),
                    context={},
                )
            )
            assert result.status is InvocationStatus.DENIED
            assert result.via == "feature_gate"
        finally:
            protocols.default_invoker().feature_gate = original


# ===========================================================================
# 三、生产可达性（AST 活性锁：机制存在 ≠ 装配接上）
# ===========================================================================


class TestProductionWiring:
    def _calls(self, tree: ast.AST, name: str) -> list[ast.Call]:
        return [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and (
                (isinstance(node.func, ast.Name) and node.func.id == name)
                or (isinstance(node.func, ast.Attribute) and node.func.attr == name)
            )
        ]

    def test_root_attaches_the_real_predicate(self) -> None:
        """根装配真把 ``product_feature_gate.check_capability`` 注入了——**且晚于构造**。

        注毒「把 attach 那行删掉」⇒ 本条红（层 2 回到不执法，而 #49 的「在册未执法」
        又变成真话）；注毒「注入一个恒 True 的桩」⇒ 本条红（假绿，见 S43 §1.5）。
        """
        tree = ast.parse(RUNTIME_ROOT.read_text(encoding="utf-8"))
        attaches = self._calls(tree, "attach_default_feature_gate")
        assert len(attaches) == 1, "层 2 门注入点必须唯一"
        attached = attaches[0].args[0]
        assert (
            isinstance(attached, ast.Attribute) and attached.attr == "check_capability"
        ), "层 2 只能挂真身谓词，禁挂桩"
        constructions = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "ProductFeatureGate"
        ]
        assert constructions, "根装配里找不到 ProductFeatureGate 构造点"
        assert attaches[0].lineno > min(node.lineno for node in constructions), (
            "注入早于构造＝拿到未成型对象"
        )

    def test_root_imports_the_shell_door_not_the_invoker(self) -> None:
        """根不自己取 ``default_invoker()``（第二 invoker 点位由结构门执法）。"""
        tree = ast.parse(RUNTIME_ROOT.read_text(encoding="utf-8"))
        assert not self._calls(tree, "default_invoker")
