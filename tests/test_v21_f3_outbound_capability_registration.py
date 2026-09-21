"""F3 反证锁（2026-09-20 统一性波次）：四个出站 capability_id 过真实功能门不被吞。

背景（审计 ``docs/design/audit-20260920-unify-U3-outbound.md`` U3-01/U3-02，P1）：
``RuntimePipeline`` 接入 ``ProductFeatureGate`` 后，**未登记的 capability_id 一律
fail-closed 判否**（``feature_gate.py`` ``FeatureAccess(False, "feature_unregistered")``
→ ``pipeline._prepare`` 返回 BLOCKED「这项功能暂时不可用。」且在入队之前结束）。
管理端出站链实际使用的四个 id——``bot.file``（含 ``_send_text_through_unified_pipeline``
/ ``_send_files_through_unified_pipeline`` 两形参缺省值，覆盖约 21 处调用点）、
``bot.group_welcome``、``bot.cookie_login``、``bot.cookie_expiry_notice``——全部
未登记 → 出站文案静默消失。既有 S0 收编测试（``tests/test_v21_s0_root_collect.py``
等）把 ``_run_capability_through_pipeline``/``_send_*_through_unified_pipeline``
整体换成 spy，真实管线与门从未进入被测路径 → 126 全绿是假绿。

本文件**不 spy 任何被测咽喉**：真实 ``ProductFeatureGate``（绑定来自真实注册册）+
真实 ``RuntimePipeline``（个别用例再经生产胶水 ``_run_capability_through_pipeline``），
逐 id 驱动出站并断言回执 SENT、正文入队。修前红（BLOCKED）/修后绿即本席证据链。

同时锁定设计语义（本席判定，见 F3-report）：「未登记 = 拒绝」是**有意**的
fail-closed 控制（docs/design/control-plane-registry.md §bot.poke 补登记先例 +
backend-v2-implementation-guide「启动门拒绝未登记入口」），因此本文件另用一条
永不登记的哨兵 id 钉死该方向**不许翻转**，并要求未登记路径产出可观测告警
（logger.warning，每 id 一次；不再零日志静默）。

全离线：JSON 状态库落 tmp_path、假 bot/事件、零网络、零真实发送、零 ``.env`` 读取。
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

import plugins.bot_unified_runtime as runtime_module
from plugins.bot_unified_runtime import _run_capability_through_pipeline
from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    DeliveryReceipt,
    IncomingMessage,
    ReceiptState,
    SessionType,
)
from plugins.bot_unified_runtime.control_plane.features import FeatureStateStore
from plugins.bot_unified_runtime.control_plane.services import FeatureControlService
from plugins.bot_unified_runtime.domains.chat_reply.runtime.pipeline import (
    RuntimePipeline,
)
from plugins.bot_unified_runtime.domains.ops.audit.logger import InMemoryAuditLogger
from plugins.bot_unified_runtime.domains.ops.features.feature_catalog import (
    build_product_descriptors,
    capability_feature_bindings,
)
from plugins.bot_unified_runtime.domains.ops.features.feature_gate import (
    ProductFeatureGate,
)
from plugins.bot_unified_runtime.domains.transport.sender.queue import InMemorySendQueue

_REPO_ROOT = Path(__file__).resolve().parents[1]

#: 审计 U3-01/U3-02 点名的四个出站 capability_id（根 __init__.py 实参/缺省值）。
FOUR_OUTBOUND_IDS = (
    "bot.file",
    "bot.group_welcome",
    "bot.cookie_login",
    "bot.cookie_expiry_notice",
)


def _real_gate(tmp_path: Path) -> ProductFeatureGate:
    """真实门：绑定表来自真实注册册（CONTROLLED_INTERNAL + ROUTE 声明投影）。"""
    service = FeatureControlService(
        FeatureStateStore(
            tmp_path / "features.json", descriptors=build_product_descriptors()
        )
    )
    return ProductFeatureGate(service)


def _private_message(text: str = "f3 出站探针") -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="bot-1",
        sender_id="u-1",
        session_id="private:u-1",
        session_type=SessionType.PRIVATE,
        plain_text=text,
    )


def _text_capability(calls: list[str], body: str) -> Any:
    """等价于 ``_send_text_through_unified_pipeline`` 内嵌 ``_capability`` 闭包。"""

    def _capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
        calls.append(message.request_id)
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="ignored",
            kind="text",
            body=body,
            audit_tags=["unified_text_reply"],
        )

    return _capability


# ---------------------------------------------------------------------------
# 1) 反证锁（修后须绿）：四个 id 真调 RuntimePipeline，出站不被门吞
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("capability_id", FOUR_OUTBOUND_IDS)
def test_four_outbound_capability_ids_pass_real_pipeline(
    tmp_path: Path, capability_id: str
) -> None:
    """真门+真管线（零 spy）：四个 id 出站回执 SENT、正文入队、无 feature 拦截。"""
    audit = InMemoryAuditLogger()
    queue = InMemorySendQueue(audit_logger=audit)
    pipeline = RuntimePipeline(
        send_queue=queue,
        audit_logger=audit,
        feature_gate=_real_gate(tmp_path),
    )
    calls: list[str] = []
    body = f"管理端出站文案::{capability_id}"
    message = _private_message()

    receipt = pipeline.handle(
        message, _text_capability(calls, body), capability_id=capability_id
    )

    assert receipt.state is not ReceiptState.BLOCKED, (
        f"{capability_id} 被功能门吞掉：state=BLOCKED public={receipt.public_message!r}"
    )
    assert receipt.state is ReceiptState.SENT
    # 能力真的执行了（不是被任何前置门早退），文案落进发送队列。
    assert calls == [message.request_id]
    queued = queue.find_request(message.request_id)
    assert queued is not None
    assert queued.content.text_fallback == body
    assert queued.capability_id == capability_id
    blocked_events = [
        record.event
        for record in audit.list_records(message.request_id)
        if record.event in {"feature_unregistered", "feature_disabled", "feature_state_unavailable"}
    ]
    assert blocked_events == []


@pytest.mark.parametrize("capability_id", FOUR_OUTBOUND_IDS)
def test_four_ids_are_registered_in_active_registry(capability_id: str) -> None:
    """四 id 必须出现在现役注册册投影的绑定表里（补登记路线的直白锁）。"""
    bindings = capability_feature_bindings()
    assert capability_id in bindings, (
        f"{capability_id} 未登记：capability_feature_bindings() 缺该键，"
        "ProductFeatureGate 会 fail-closed 吞出站"
    )


# ---------------------------------------------------------------------------
# 2) 设计语义反证（恒绿）：未登记 = 拒绝不许翻转，且不得零日志静默
# ---------------------------------------------------------------------------

_SENTINEL_ID = "bot.f3_never_registered_sentinel"


def test_unregistered_capability_still_fail_closed_and_observable(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """哨兵 id（永不登记）真调管线：仍 BLOCKED（fail-closed 有意设计），
    但门本体必须产出可观测告警——logger.warning 点名该 id，不得继续零日志。"""
    ProductFeatureGate.reset_unregistered_warnings()
    audit = InMemoryAuditLogger()
    queue = InMemorySendQueue(audit_logger=audit)
    pipeline = RuntimePipeline(
        send_queue=queue,
        audit_logger=audit,
        feature_gate=_real_gate(tmp_path),
    )
    calls: list[str] = []
    message = _private_message()

    with caplog.at_level(
        logging.WARNING,
        logger="plugins.bot_unified_runtime.domains.ops.features.feature_gate",
    ):
        receipt = pipeline.handle(
            message, _text_capability(calls, "不该出现"), capability_id=_SENTINEL_ID
        )

    assert receipt.state is ReceiptState.BLOCKED
    assert calls == [] and queue.sent_requests == []
    assert receipt.public_message == "这项功能暂时不可用。"
    warnings = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert any(_SENTINEL_ID in str(text) for text in warnings), (
        "未登记路径必须产出可观测告警（F3 任务 2：不得零日志静默）"
    )
    events = [record.event for record in audit.list_records(message.request_id)]
    assert "feature_unregistered" in events


def test_unregistered_warning_is_emitted_once_per_capability_id(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """告警去重：同一 id 反复未登记只警告一次（防热路径刷屏），且可复位。"""
    gate = _real_gate(tmp_path)
    ProductFeatureGate.reset_unregistered_warnings()
    with caplog.at_level(
        logging.WARNING,
        logger="plugins.bot_unified_runtime.domains.ops.features.feature_gate",
    ):
        first = gate(_private_message(), _SENTINEL_ID + "_2")
        second = gate(_private_message(), _SENTINEL_ID + "_2")
    assert not first.allowed and not second.allowed
    hits = [
        r for r in caplog.records if _SENTINEL_ID + "_2" in str(r.message)
    ]
    assert len(hits) == 1
    ProductFeatureGate.reset_unregistered_warnings()
    gate(_private_message(), _SENTINEL_ID + "_2")
    hits_after_reset = [
        r for r in caplog.records if _SENTINEL_ID + "_2" in str(r.message)
    ]
    assert len(hits_after_reset) == 2


# ---------------------------------------------------------------------------
# 3) 生产胶水全链路（不 spy 管线）：缺省 bot.file 的 21 调用点形态过真门
# ---------------------------------------------------------------------------


class _FakePrivateMsgEvent:
    """私聊消息事件形（``_run_capability_through_pipeline`` 摄取入参）。"""

    __module__ = "nonebot.adapters.onebot.v11.event"

    time = 1700000000
    self_id = 10001
    post_type = "message"
    message_type = "private"
    sub_type = "friend"
    user_id = 42
    message_id = 555
    group_id = None
    message: ClassVar[list[dict[str, Any]]] = [{"type": "text", "data": {"text": "cookie"}}]

    def get_plaintext(self) -> str:
        return "cookie"

    def get_session_id(self) -> str:
        return "42"

    def get_user_id(self) -> str:
        return "42"


@pytest.mark.asyncio
async def test_default_bot_file_full_glue_path_not_swallowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """经真实 ``_run_capability_through_pipeline`` + 真门 ``RuntimePipeline`` 复现
    21 调用点形态（capability_id 缺省 ``bot.file``）：修前 BLOCKED（文案消失），
    修后 SENT 且正文入队。唯一替身=平台投递本体（离线不真发），咽喉不 spy。"""
    queue = InMemorySendQueue(audit_logger=InMemoryAuditLogger())
    audit = InMemoryAuditLogger()
    pipeline = RuntimePipeline(
        send_queue=queue,
        audit_logger=audit,
        feature_gate=_real_gate(tmp_path),
    )

    async def _fake_transport(
        _bot: Any, _event: Any, request: Any, *_a: Any, **_k: Any
    ) -> DeliveryReceipt:
        return DeliveryReceipt(
            request_id=request.request_id,
            state=ReceiptState.SENT,
            transport="onebot",
            public_message=request.content.text_fallback,
        )

    monkeypatch.setattr(
        runtime_module, "_deliver_transport_send_request", _fake_transport
    )
    calls: list[str] = []
    receipt = await _run_capability_through_pipeline(
        bot=SimpleNamespace(self_id="bot-1"),
        event=_FakePrivateMsgEvent(),
        config=SimpleNamespace(),
        pipeline=pipeline,
        send_queue=queue,
        audit_logger=audit,
        diagnostics_store=SimpleNamespace(record=lambda _diagnostic: None),
        capability=_text_capability(calls, "文件已生成但上传失败：doc.md"),
        capability_id="bot.file",  # 缺省值实参化：与 21 处调用点同款
        record_diagnostic=False,
    )
    assert calls, "能力未执行：出站被前置门吞掉"
    assert receipt.state is ReceiptState.SENT
    assert receipt.public_message == "文件已生成但上传失败：doc.md"


# ---------------------------------------------------------------------------
# 4) 常驻一致性门：根 __init__.py 全部 capability_id（含形参缺省值）⊆ 绑定表
# ---------------------------------------------------------------------------


def _capability_ids_declared_in_runtime_init() -> set[str]:
    """AST 枚举根 ``__init__.py`` 的 capability_id 字面量。

    覆盖三形态（比既有 test_runtime_feature_gate 的门多收**形参缺省值**——
    ``_send_text_through_unified_pipeline(capability_id: str = "bot.file")``
    正是 21 处被吞调用点的真实 id 来源，旧门只查 keyword/Assign 会漏）。
    """
    source = _REPO_ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    ids: set[str] = set()

    def add(value: ast.expr) -> None:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            ids.add(value.value)

    for node in ast.walk(tree):
        literal: ast.expr | None = None
        if (isinstance(node, ast.keyword) and node.arg == "capability_id") or (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "capability_id"
                for target in node.targets
            )
        ):
            literal = node.value
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            argnames = [a.arg for a in node.args.args]
            defaults = list(node.args.defaults)
            offset = len(argnames) - len(defaults)
            for index, name in enumerate(argnames):
                if name != "capability_id":
                    continue
                default_index = index - offset
                if default_index >= 0:
                    literal = defaults[default_index]
        if literal is not None:
            add(literal)
    return ids


def test_runtime_init_capability_id_literals_all_registered() -> None:
    """根 __init__.py 的每个 capability_id 字面量（含缺省值）都必须在现役
    注册册绑定表内——未登记=拒绝是有意语义，则**使用即登记**是不变量。"""
    bindings = set(capability_feature_bindings())
    missing = sorted(
        value
        for value in _capability_ids_declared_in_runtime_init()
        if value.startswith("bot.") and value not in bindings
    )
    assert not missing, f"根 __init__.py 声明/缺省了未登记能力（会被门 fail-closed 吞）：{missing}"
