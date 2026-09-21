"""V2.1 S6 出站收编地基席（A16）回归：契约严格性 + 状态机 + 租约线性化 +
幂等/对账 + 注册表完整性 + Transport 拒绝面。

合同来源（本文件是它们的机器可执行形态之一）：
- 主规范 §10：OutboundIntent 字段面 / Transport 固定映射 / 发送前复验 /
  「领取受控许可为线性化点，之后在途调用不能承诺撤回」/ pause/drain 不删队列 /
  「UNKNOWN先对账，无平台幂等时不承诺exactly-once」。
- V21-DISPATCH-001 / DELIVERY-001（验收矩阵）：契约层与登记表。
- A1 冻结清单（v21-s0-inventory §2）：50 matcher / 12 调度族 / 62 控制面路由 /
  直发嫌疑 8 组——登记表完整性的对照锚。

全部离线（零网络/零 nonebot 运行时依赖）；唯一子进程探针只验证可导入性。
"""

from __future__ import annotations

import os
import subprocess
import threading
from datetime import datetime, timedelta, timezone

import pytest

import plugins.bot_unified_runtime.domains.core.decision.outbound as outbound_facade
from plugins.bot_unified_runtime.domains.core.decision.outbound import (
    OPERATION_TRANSITIONS,
    PART_TRANSITIONS,
    AdmissionDenied,
    AdmissionTicket,
    CancelOutcome,
    ConfirmationCheck,
    DedupeIndex,
    DirectSendCategory,
    DuplicateClaim,
    FeatureGateCheck,
    IllegalOutboundTransition,
    LeasePaused,
    OutboundAdmissionGate,
    OutboundIntent,
    OutboundOperation,
    OutboundOperationState,
    OutboundPart,
    OutboundPartState,
    OutboundTarget,
    PermissionCheck,
    PermitLease,
    ReconciliationLedger,
    TakeoverChecklist,
    TransportChannel,
    TransportPlatform,
    TransportRegistry,
    UnknownPendingError,
    UnregisteredTransportError,
    build_default_takeover_registry,
    build_default_transport_registry,
    derive_dedupe_key,
    operation_has_inflight_claim,
    transition_operation,
    transition_part,
)

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# 造数工厂
# ---------------------------------------------------------------------------


def make_target(platform: str = "qq") -> OutboundTarget:
    return OutboundTarget(
        platform=platform,
        session_type="group",
        target_id="123456",
        bot_id="2300230562",
        adapter="onebot",
    )


def make_intent(**overrides: object) -> OutboundIntent:
    base: dict[str, object] = {
        "operation": OutboundOperation.SEND_MESSAGE,
        "target": make_target(),
        "parts": [OutboundPart(part_id="p1")],
        "feature_id": "chat.reply",
        "policy_revision": "policy@2026-09-17",
        "dedupe_key": "qq:chat:evt_1",
        "trace_id": "trace_abc",
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    base.update(overrides)
    return OutboundIntent(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 0. 门面导出面
# ---------------------------------------------------------------------------


class TestFacadeSurface:
    def test_all_exports_resolve(self) -> None:
        for name in outbound_facade.__all__:
            assert getattr(outbound_facade, name) is not None, name

    def test_state_transition_tables_exposed(self) -> None:
        assert len(outbound_facade.PART_TRANSITIONS) == len(OutboundPartState)
        assert len(outbound_facade.OPERATION_TRANSITIONS) == len(
            OutboundOperationState
        )


# ---------------------------------------------------------------------------
# 1. DTO 严格性
# ---------------------------------------------------------------------------


class TestDtoStrictness:
    def test_unknown_field_rejected(self) -> None:
        with pytest.raises(ValueError, match="extra"):
            make_intent(totally_unknown_field="x")

    def test_nan_budget_rejected(self) -> None:
        with pytest.raises(ValueError, match="finite"):
            make_intent(budget_ms=float("nan"))

    def test_inf_budget_rejected(self) -> None:
        with pytest.raises(ValueError, match="finite"):
            make_intent(budget_ms=float("inf"))

    def test_naive_expires_at_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            # 故意传 naive datetime：本用例正是验证 DTO 拒绝非 aware 时间。
            make_intent(expires_at=datetime(2026, 9, 17, 12, 0, 0))  # noqa: DTZ001

    def test_blank_ids_rejected(self) -> None:
        for field in ("feature_id", "policy_revision", "dedupe_key", "trace_id"):
            with pytest.raises(ValueError):
                make_intent(**{field: "  "})

    def test_empty_parts_rejected(self) -> None:
        with pytest.raises(ValueError):
            make_intent(parts=[])

    def test_duplicate_part_ids_rejected(self) -> None:
        with pytest.raises(ValueError, match="unique"):
            make_intent(
                parts=[OutboundPart(part_id="p1"), OutboundPart(part_id="p1")]
            )

    def test_cancel_requested_on_settled_rejected(self) -> None:
        # cancel_requested ≠ cancelled：终局成功/失败意图不允许再挂取消标记。
        with pytest.raises(ValueError, match="cancel_requested"):
            make_intent(
                operation_state=OutboundOperationState.SUCCEEDED,
                cancel_requested=True,
            )

    def test_enum_values_preserved_not_coerced(self) -> None:
        intent = make_intent()
        assert intent.operation is OutboundOperation.SEND_MESSAGE
        assert intent.parts[0].state is OutboundPartState.QUEUED

    def test_deny_verdict_requires_reason_code(self) -> None:
        from plugins.bot_unified_runtime.domains.core.decision.outbound import (
            AdmissionVerdict,
        )

        with pytest.raises(ValueError, match="reason_code"):
            AdmissionVerdict(check_name="x", allow=False)


# ---------------------------------------------------------------------------
# 2. 状态机
# ---------------------------------------------------------------------------


class TestStateMachines:
    def test_part_legal_path(self) -> None:
        part = OutboundPart(part_id="p1")
        sending = transition_part(part, OutboundPartState.SENDING)
        delivered = transition_part(sending, OutboundPartState.DELIVERED)
        assert delivered.state is OutboundPartState.DELIVERED

    def test_part_unknown_reconcile_path(self) -> None:
        part = transition_part(
            transition_part(OutboundPart(part_id="p"), OutboundPartState.SENDING),
            OutboundPartState.UNKNOWN,
        )
        assert (
            transition_part(part, OutboundPartState.DELIVERED).state
            is OutboundPartState.DELIVERED
        )
        assert (
            transition_part(part, OutboundPartState.FAILED).state
            is OutboundPartState.FAILED
        )

    def test_part_full_transition_matrix(self) -> None:
        # 全迁移矩阵：不在表内的迁移必须拒绝，一个不漏。
        for src in OutboundPartState:
            for dst in OutboundPartState:
                part = OutboundPart(part_id="p", state=src)
                if dst in PART_TRANSITIONS[src]:
                    assert transition_part(part, dst).state is dst
                else:
                    with pytest.raises(IllegalOutboundTransition):
                        transition_part(part, dst)

    def test_operation_full_transition_matrix(self) -> None:
        for src in OutboundOperationState:
            for dst in OutboundOperationState:
                intent = make_intent(operation_state=src)
                if dst in OPERATION_TRANSITIONS[src]:
                    assert transition_operation(intent, dst).operation_state is dst
                else:
                    with pytest.raises(IllegalOutboundTransition):
                        transition_operation(intent, dst)

    def test_cancel_with_inflight_claim_rejected(self) -> None:
        # 领取后在途调用不可承诺撤回：part 推进到 sending 后（派发器经
        # model_copy 推进 part，同真实路径）ADMITTED 不允许落 CANCELLED。
        intent = make_intent()  # PENDING + queued
        inflight = intent.model_copy(
            update={
                "operation_state": OutboundOperationState.ADMITTED,
                "parts": [
                    OutboundPart(part_id="p1", state=OutboundPartState.SENDING)
                ],
            }
        )
        assert operation_has_inflight_claim(inflight) is True
        with pytest.raises(IllegalOutboundTransition, match="irreversible"):
            transition_operation(inflight, OutboundOperationState.CANCELLED)

    def test_dto_rejects_pending_with_non_queued_parts(self) -> None:
        # DTO 自身的不变量：pending/admitted 意图不允许携带非 queued part
        # （准入前的结构性防线，独立于 gate 复验）。
        with pytest.raises(ValueError, match="queued/cancelled"):
            make_intent(
                parts=[OutboundPart(part_id="p1", state=OutboundPartState.SENDING)]
            )

    def test_cancel_requested_flag_is_not_state(self) -> None:
        # 标记位挂上不改变状态机位置，也不等于已取消。
        intent = make_intent(cancel_requested=True)
        assert intent.cancel_requested is True
        assert intent.operation_state is OutboundOperationState.PENDING


# ---------------------------------------------------------------------------
# 3. 准入协议
# ---------------------------------------------------------------------------


class TestAdmissionGate:
    def test_happy_path_admits_with_ticket(self) -> None:
        gate = OutboundAdmissionGate()
        ticket = gate.admit(make_intent())
        assert isinstance(ticket, AdmissionTicket)
        assert ticket.policy_revision == "policy@2026-09-17"
        assert "expiry" in ticket.passed_checks
        assert gate.check_order == ["expiry", "part_state", "operation_state"]

    def test_expired_intent_denied(self) -> None:
        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        with pytest.raises(AdmissionDenied, match="expired"):
            OutboundAdmissionGate().admit(make_intent(expires_at=past))

    def test_non_queued_part_denied(self) -> None:
        # RUNNING 意图携带非 queued part：part_state 复验拒绝
        # （operation_state 复验在其后，prior 检查先命中）。
        with pytest.raises(AdmissionDenied, match="parts_not_queued"):
            OutboundAdmissionGate().admit(
                make_intent(
                    operation_state=OutboundOperationState.RUNNING,
                    parts=[OutboundPart(part_id="p1", state=OutboundPartState.FAILED)],
                )
            )

    def test_operation_state_check(self) -> None:
        # RUNNING 意图不允许再次进入发送准备。
        with pytest.raises(AdmissionDenied, match="operation_not_admittable"):
            OutboundAdmissionGate().admit(
                make_intent(operation_state=OutboundOperationState.RUNNING)
            )

    def test_feature_gate_and_permission_checks(self) -> None:
        gate = OutboundAdmissionGate(
            checks=[
                FeatureGateCheck(lambda fid: fid != "disabled.feature"),
                PermissionCheck(lambda intent: intent.target.target_id != "banned"),
            ]
        )
        assert gate.admit(make_intent(feature_id="ok.feature")) is not None
        with pytest.raises(AdmissionDenied, match="feature_disabled"):
            gate.admit(make_intent(feature_id="disabled.feature"))
        with pytest.raises(AdmissionDenied, match="permission_denied"):
            gate.admit(
                make_intent(
                    target=OutboundTarget(
                        platform="qq", session_type="group", target_id="banned"
                    )
                )
            )

    def test_confirmation_check(self) -> None:
        gate = OutboundAdmissionGate(
            checks=[ConfirmationCheck(lambda intent: False)]
        )
        with pytest.raises(AdmissionDenied, match="confirmation_missing"):
            gate.admit(make_intent())

    def test_first_denial_short_circuits(self) -> None:
        # 固定顺序：过期先于 part 状态（首个拒绝即短路）。
        gate = OutboundAdmissionGate()
        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        with pytest.raises(AdmissionDenied) as excinfo:
            gate.admit(
                make_intent(
                    operation_state=OutboundOperationState.RUNNING,
                    expires_at=past,
                    parts=[OutboundPart(part_id="p1", state=OutboundPartState.FAILED)],
                )
            )
        assert excinfo.value.verdict.check_name == "expiry"


# ---------------------------------------------------------------------------
# 4. 许可租约：pause / drain / claim 线性化 / irreversible
# ---------------------------------------------------------------------------


class TestPermitLease:
    def test_acquire_and_release(self) -> None:
        lease = PermitLease()
        token = lease.acquire("k1", holder="h")
        assert lease.inflight_keys() == ["k1"]
        lease.release(token)
        assert lease.inflight_keys() == []

    def test_duplicate_claim_rejected(self) -> None:
        lease = PermitLease()
        lease.acquire("k1", holder="first")
        with pytest.raises(DuplicateClaim, match="first"):
            lease.acquire("k1", holder="second")

    def test_pause_stops_claiming_only(self) -> None:
        lease = PermitLease()
        held = lease.acquire("k1")
        lease.pause()
        assert lease.paused is True
        with pytest.raises(LeasePaused):
            lease.acquire("k2")
        # 已领取的不受影响；resume 后恢复领取。
        lease.release(held)
        lease.resume()
        assert lease.acquire("k2").key == "k2"

    def test_drain_waits_for_specified_keys_and_deletes_nothing(self) -> None:
        # drain 等指定任务集完成；「队列」语义由调用方持有——本测试用一个
        # 独立列表扮演待领取队列，断言 drain 前后队列内容零删除。
        lease = PermitLease()
        pending_queue = ["k1", "k2", "k3"]  # 模拟待领取任务（不被租约触碰）
        token1 = lease.acquire("k1")
        token2 = lease.acquire("k2")

        done = threading.Event()
        reports: list[object] = []

        def drain_worker() -> None:
            reports.append(lease.drain(keys=["k1", "k2"]))
            done.set()

        thread = threading.Thread(target=drain_worker)
        thread.start()
        lease.release(token1)
        # k2 仍持有：drain 不得提前完成
        assert not done.wait(timeout=0.2)
        lease.release(token2)
        assert done.wait(timeout=2.0)
        report = reports[0]
        assert sorted(report.completed) == ["k1", "k2"]  # type: ignore[attr-defined]
        assert report.timed_out == []  # type: ignore[attr-defined]
        thread.join(timeout=2.0)
        # 队列不被 drain 删除
        assert pending_queue == ["k1", "k2", "k3"]

    def test_drain_timeout_reports_honestly(self) -> None:
        lease = PermitLease()
        lease.acquire("stuck")
        report = lease.drain(keys=["stuck"], timeout_s=0.2)
        assert report.timed_out == ["stuck"]
        assert report.completed == []
        assert report.waited_keys == ["stuck"]
        assert report.elapsed_ms >= 0

    def test_concurrent_claim_unique_winner(self) -> None:
        # 线性化点：同 key 并发 claim 恰有一个胜者（16 线程 × 独立 key 一胜者 +
        # 32 线程争抢同一 key 恰一胜者）。
        lease = PermitLease()
        single_key_winners: list[int] = []
        lock = threading.Lock()
        barrier = threading.Barrier(32)

        def contend_same_key(idx: int) -> None:
            barrier.wait()
            try:
                lease.acquire("one-key", holder=f"t{idx}")
            except DuplicateClaim:
                return
            with lock:
                single_key_winners.append(idx)

        threads = [
            threading.Thread(target=contend_same_key, args=(i,)) for i in range(32)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)
        assert len(single_key_winners) == 1
        assert lease.inflight_keys() == ["one-key"]

    def test_claim_irreversible_then_cancel_denied(self) -> None:
        lease = PermitLease()
        token = lease.acquire("k1", holder="worker")
        # 派发前：可撤（pre_dispatch_cancel）
        outcome = token.try_cancel()
        assert outcome == CancelOutcome(granted=True, reason="pre_dispatch_cancel")
        # 标记 irreversible（真实平台调用已在途）：撤回不可承诺
        marked = lease.mark_irreversible(token)
        assert marked.irreversible is True
        denied = lease.cancel(marked)
        assert denied == CancelOutcome(
            granted=False, reason="irreversible_inflight_call"
        )
        assert denied.granted is False
        # 在途调用只能走完：结果落状态机后正常释放
        lease.release(marked)
        assert lease.inflight_keys() == []

    def test_cancel_not_held(self) -> None:
        lease = PermitLease()
        token = lease.acquire("k1")
        lease.release(token)
        assert lease.cancel(token).reason == "not_held"


# ---------------------------------------------------------------------------
# 5. 幂等键确定性 + 去重 + UNKNOWN 对账
# ---------------------------------------------------------------------------


class TestDedupeAndReconciliation:
    def test_dedupe_key_deterministic(self) -> None:
        a = derive_dedupe_key("qq", "evt_42", "matcher")
        b = derive_dedupe_key("qq", "evt_42", "matcher")
        assert a == b == "qq:matcher:evt_42"

    def test_cross_entry_kind_no_collision(self) -> None:
        # 同一事件经不同入口 kind → 不同键（互不吞并）。
        keys = {
            derive_dedupe_key("qq", "evt_42", "matcher"),
            derive_dedupe_key("qq", "evt_42", "scheduler"),
            derive_dedupe_key("qq", "evt_42", "control_plane"),
        }
        assert len(keys) == 3

    def test_cross_event_no_collision(self) -> None:
        assert derive_dedupe_key("qq", "evt_1", "matcher") != derive_dedupe_key(
            "qq", "evt_2", "matcher"
        )

    def test_blank_or_separator_components_rejected(self) -> None:
        with pytest.raises(ValueError, match="platform"):
            derive_dedupe_key("", "e", "m")
        with pytest.raises(ValueError, match="event_id"):
            derive_dedupe_key("qq", " ", "m")
        with pytest.raises(ValueError, match="entry_kind"):
            derive_dedupe_key("qq", "e", "match:er")  # ':' 会破坏键体解析

    def test_dedupe_index_first_wins(self) -> None:
        index = DedupeIndex()
        key = derive_dedupe_key("qq", "evt_1", "matcher")
        assert index.claim_first(key, holder="a") is True
        assert index.claim_first(key, holder="b") is False  # 同事件同键 → 去重
        assert index.first_holder(key) == "a"

    def test_unknown_pending_blocks_retry_until_reconciled(self) -> None:
        # UNKNOWN 先对账，不盲重发：定性前 assert_may_retry 抛；delivered/failed
        # 定性后门开。
        ledger = ReconciliationLedger()
        key = derive_dedupe_key("qq", "evt_9", "scheduler")
        ledger.record_unknown(key, coordinate="__init__.py:4071")
        assert ledger.is_pending(key) is True
        with pytest.raises(UnknownPendingError):
            ledger.assert_may_retry(key)
        assert ledger.reconcile(key, "delivered") == "delivered"
        ledger.assert_may_retry(key)  # 定性后不再阻拦（是否重发由键级去重定）
        assert ledger.resolved_state(key) == "delivered"
        assert ledger.is_pending(key) is False

    def test_reconcile_requires_pending_and_valid_state(self) -> None:
        ledger = ReconciliationLedger()
        with pytest.raises(KeyError):
            ledger.reconcile("unknown-key", "delivered")
        ledger.record_unknown("k")
        with pytest.raises(ValueError, match="delivered.*failed"):
            ledger.reconcile("k", "retrying")

    def test_failed_reconcile_allows_retry(self) -> None:
        # failed 定性 = 平台确认未送达 → 允许（键级去重允许的）重试。
        ledger = ReconciliationLedger()
        ledger.record_unknown("k2")
        ledger.reconcile("k2", "failed")
        ledger.assert_may_retry("k2")


# ---------------------------------------------------------------------------
# 6. Transport 固定映射注册表
# ---------------------------------------------------------------------------


class TestTransportRegistry:
    def test_default_registry_resolves_known_channels(self) -> None:
        reg = build_default_transport_registry()
        qq_msg = reg.resolve(TransportPlatform.QQ, TransportChannel.SEND_MESSAGE)
        assert qq_msg.platform_method_for("group") == "send_group_msg"
        assert qq_msg.platform_method_for("private") == "send_private_msg"
        poke = reg.resolve(TransportPlatform.QQ, TransportChannel.POKE)
        assert poke.platform_method_for("group") == "group_poke"
        assert poke.platform_method_for("private") == "friend_poke"
        reaction = reg.resolve(TransportPlatform.QQ, TransportChannel.REACTION)
        assert reaction.platform_method_for() == "set_msg_emoji_like"
        tg_msg = reg.resolve(TransportPlatform.TELEGRAM, TransportChannel.SEND_MESSAGE)
        assert tg_msg.platform_method_for() == "sendMessage"

    def test_unregistered_transport_explicit_error(self) -> None:
        # TG 无 poke 通道：有意不注册 → 显式错误（绝不合成方法名）。
        reg = build_default_transport_registry()
        with pytest.raises(UnregisteredTransportError, match="poke"):
            reg.resolve(TransportPlatform.TELEGRAM, TransportChannel.POKE)
        with pytest.raises(UnregisteredTransportError, match="mail"):
            reg.resolve(TransportPlatform.MAIL, TransportChannel.POKE)

    def test_unknown_session_type_explicit_error(self) -> None:
        reg = build_default_transport_registry()
        entry = reg.resolve(TransportPlatform.QQ, TransportChannel.SEND_MESSAGE)
        with pytest.raises(UnregisteredTransportError, match="session_type"):
            entry.platform_method_for("channel")

    def test_methods_are_registered_literals_only(self) -> None:
        # 禁任意 API 名拼接：方法名必须是标识符形态的登记字面量（QQ snake_case /
        # TG camelCase 均为平台原样字面量，不做运行时拼装/变换）。
        import re

        literal_shape = re.compile(r"^[a-z][a-z0-9_]*$", re.IGNORECASE)
        reg = build_default_transport_registry()
        for entry in reg.entries():
            for method in entry.methods.values():
                assert literal_shape.match(method), method
                assert method == method.strip()
                assert " " not in method

    def test_all_entries_carry_evidence(self) -> None:
        # 每个方法名必须有出处（file:line 坐标或标准来源声明）。
        reg = build_default_transport_registry()
        for entry in reg.entries():
            assert entry.evidence.strip(), (
                f"{entry.platform.value}/{entry.channel.value} missing evidence"
            )
            assert entry.status in ("placeholder", "bound")
            assert entry.handler is None or entry.status == "bound"

    def test_bind_handler_flips_status(self) -> None:
        reg = build_default_transport_registry()
        entry = reg.resolve(TransportPlatform.QQ, TransportChannel.DELETE)

        def fake_sender(payload: object) -> str:
            return "ok"

        bound = reg.bind_handler(
            TransportPlatform.QQ, TransportChannel.DELETE, fake_sender
        )
        assert bound.status == "bound"
        assert bound.handler is fake_sender
        # 注册表已替换为 bound 条目；原不可变条目不变
        assert (
            reg.resolve(TransportPlatform.QQ, TransportChannel.DELETE).status
            == "bound"
        )
        assert entry.status == "placeholder"

    def test_double_register_rejected_without_replace(self) -> None:
        reg = TransportRegistry()
        entry = build_default_transport_registry().resolve(
            TransportPlatform.QQ, TransportChannel.DELETE
        )
        reg.register(entry)
        with pytest.raises(ValueError, match="already registered"):
            reg.register(entry)

    def test_channel_coverage_per_task_brief(self) -> None:
        # 任务占位要求：QQ/TG/Mail/sticker/reaction/poke/edit/delete 通道成表。
        reg = build_default_transport_registry()
        pairs = {(e.platform, e.channel) for e in reg.entries()}
        required = {
            (TransportPlatform.QQ, TransportChannel.SEND_MESSAGE),
            (TransportPlatform.QQ, TransportChannel.SEND_FILE),
            (TransportPlatform.QQ, TransportChannel.STICKER),
            (TransportPlatform.QQ, TransportChannel.REACTION),
            (TransportPlatform.QQ, TransportChannel.POKE),
            (TransportPlatform.QQ, TransportChannel.EDIT),
            (TransportPlatform.QQ, TransportChannel.DELETE),
            (TransportPlatform.TELEGRAM, TransportChannel.SEND_MESSAGE),
            (TransportPlatform.TELEGRAM, TransportChannel.EDIT),
            (TransportPlatform.TELEGRAM, TransportChannel.DELETE),
            (TransportPlatform.MAIL, TransportChannel.SEND_MAIL),
        }
        assert required <= pairs


# ---------------------------------------------------------------------------
# 7. 入口接管登记表完整性（对照 A1 冻结清单）
# ---------------------------------------------------------------------------


class TestTakeoverRegistryIntegrity:
    def test_counts_match_a1_freeze(self) -> None:
        reg = build_default_takeover_registry()
        summary = reg.summary()
        assert summary["matchers"] == 50
        assert summary["schedulers"] == 12
        assert summary["control_routes"] == 62
        assert summary["direct_send_entries"] >= 10

    def test_matcher_type_census_matches_a1(self) -> None:
        # A1 §2.1：on_message 41 / on_notice 7 / on_command 2 / 其余 0。
        reg = build_default_takeover_registry()
        census = {"on_message": 0, "on_notice": 0, "on_command": 0}
        for entry in reg.matchers:
            census[entry.matcher_type] += 1
        assert census == {"on_message": 41, "on_notice": 7, "on_command": 2}

    def test_matcher_locations_unique_and_wellformed(self) -> None:
        reg = build_default_takeover_registry()
        locations = [entry.location for entry in reg.matchers]
        assert len(locations) == len(set(locations))
        for location in locations:
            file_part, _, line_part = location.rpartition(":")
            assert file_part and line_part.isdigit(), location

    def test_all_entries_default_legacy_with_checklist(self) -> None:
        reg = build_default_takeover_registry()
        for entry in reg.matchers:
            assert entry.status.value == "legacy"
            assert isinstance(entry.checklist, TakeoverChecklist)
        for entry in reg.schedulers:
            assert entry.status.value == "legacy"
            assert entry.add_job_locations  # add_job 坐标必须登记
        for group in reg.route_groups:
            assert group.status.value == "legacy"
            assert len(group.members) <= group.route_count  # 明细不超计数（不臆造）

    def test_route_group_counts_match_a1_table(self) -> None:
        # A1 §2.3 逐文件计数：28/10/9/7/4/4 + platform.py 动态未枚举(0)。
        reg = build_default_takeover_registry()
        by_module = {g.module: g.route_count for g in reg.route_groups}
        assert by_module == {
            "control_plane/api/v1.py": 28,
            "control_plane/api/workspaces.py": 10,
            "control_plane/api/llm.py": 9,
            "control_plane/api/actions.py": 7,
            "control_plane/api/health.py": 4,
            "control_plane/api/events.py": 4,
            "control_plane/api/platform.py": 0,
        }

    def test_direct_send_categories_cover_a1(self) -> None:
        # 4 组绕队列嫌疑（S0-COLLECT 补登；S0-ROOT-c 收编为 *_via_queue 门开分支，
        # 门关旧直连仍在）+ poke/reactions by-design（L34/L35 executor 面已收编）
        # + 通道本体（onebot + file_gateway 改判 CHANNEL_BODY）。
        reg = build_default_takeover_registry()
        suspects = [
            e
            for e in reg.direct_sends
            if e.category is DirectSendCategory.BYPASS_SUSPECT
        ]
        assert len(suspects) == 4
        # REG-REFRESH 2026-09-19 grep 复核（门关分支旧直连现坐标）：cookie 提醒 /
        # 入群欢迎 / 二维码双通道 / 文档导出上传；S0-COLLECT 快照 4300/5184/5481/
        # 5303 已随根文件在飞编辑漂移清零。
        assert any("4440" in e.location for e in suspects)
        assert any("5378" in e.location for e in suspects)
        assert any("5730" in e.location for e in suspects)
        assert any("5526" in e.location for e in suspects)
        # 状态=已收编（门缺省关：重启不拨门=生产零变更，不写「已生效」）：
        # note 记 via_queue 门与收编语义；pending-on-RWC5-b 仅以前态注记保留
        # （S0-COLLECT 契约锁仍钉该字面量，见 test_v21_s0_collect.py）。
        assert all("已收编" in e.note for e in suspects)
        assert all("via_queue" in e.note for e in suspects)
        by_design = [
            e for e in reg.direct_sends if e.category is DirectSendCategory.BY_DESIGN
        ]
        coordinates = " | ".join(e.location for e in by_design)
        # poke 直连点已不存在→L34 执行器面；reaction 真身=domains/meme/reactions/
        # engine.py（runtime/ 旧路径为 compat shim）；delete_msg 现坐标 :4978。
        assert "control_plane/dispatcher.py:162" in coordinates  # poke executor
        assert "reactions/engine.py:754" in coordinates  # set_msg_emoji_like
        assert "reactions/engine.py:785" in coordinates  # TG set_message_reaction
        assert "4978" in coordinates  # delete_msg（dirty guard）
        assert "4745" not in coordinates  # poke 陈旧直连坐标清零
        assert "runtime/reactions.py" not in coordinates  # shim 旧路径清零
        bodies = [
            e for e in reg.direct_sends if e.category is DirectSendCategory.CHANNEL_BODY
        ]
        assert any("sender/onebot.py" in e.location for e in bodies)
        # file_gateway 内环=统一文件出站路径通道本体（DIRECT-PLAN §二④ 改判，
        # 路径对齐 reorg 后真身 domains/transport/sender/file_gateway.py）。
        assert any(
            "domains/transport/sender/file_gateway.py" in e.location for e in bodies
        )
        pending = [
            e
            for e in reg.direct_sends
            if e.category is DirectSendCategory.PENDING_RULING
        ]
        assert not pending  # PENDING_RULING 对直发项退役（file_gateway 已改判）

    def test_checklist_completion_gate(self) -> None:
        # checklist 未补齐（todo）不得置 takeover_ready——迁移门禁的机器形态。
        incomplete = TakeoverChecklist()
        assert incomplete.is_complete() is False
        complete = TakeoverChecklist(
            idempotency_key_source="qq+message_id+matcher",
            feature_gate="chat.reply",
            trace_point="ingress.trace_id",
        )
        assert complete.is_complete() is True

    def test_scheduler_family_register_locations(self) -> None:
        # A1 §2.2 的 12 族注册点全覆盖（含用途 unknown 的裸 add_job 双笔）。
        reg = build_default_takeover_registry()
        families = {s.family for s in reg.schedulers}
        assert len(families) == 12
        assert "unattributed_bare_add_jobs" in families  # unknown 如实登记


# ---------------------------------------------------------------------------
# 8. 导入探针（模块可独立导入，无运行时副作用）
# ---------------------------------------------------------------------------


class TestImportProbe:
    def test_module_importable_in_subprocess(self) -> None:
        # 子进程正常 import（父包真实装配路径），断言可导入且导出面完整。
        env = dict(os.environ)
        env.update(
            {
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONUTF8": "1",
                "BOT_AUTOSYNC": "0",
            }
        )
        proc = subprocess.run(
            [
                os.environ.get(
                    "V21_PYTHON",
                    os.path.join(
                        os.path.dirname(WORKSPACE_ROOT),
                        "ChatBot_Runtime",
                        "venv",
                        "Scripts",
                        "python.exe",
                    ),
                ),
                "-c",
                (
                    "import plugins.bot_unified_runtime.domains.core.decision.outbound as m; "
                    "print(len(m.__all__))"
                ),
            ],
            cwd=WORKSPACE_ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            env=env,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        assert int(proc.stdout.strip()) >= 45
