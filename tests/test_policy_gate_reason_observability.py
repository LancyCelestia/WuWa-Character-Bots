"""回归：门禁「门因」必须落在事件行上（pipeline_result 可观测性锁）。

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_policy_gate_reason_observability.py -q

病根（2026-09-29 实跑取证）：群侧大量
`event=pipeline_result capability_id=bot.chat receipt_state=blocked transport=policy`
却读不出**为什么**被拦。判定链上门因一直在（`policy/gate.py::_denied(reason, tags)`），
但 `DeliveryReceipt` 不承载 reason、blocked 腿又没有 SendRequest ⇒ 根 `__init__.py`
的发射点拿不到它。唯一留着门因的地方＝pipeline 拦截时 append 的那条
`AuditRecord(stage="policy")`；本波把它读回日志行（纯观测面，零判定改动）。

三条红线各有一枚锁：
① 规则 3——字段只能由受控枚举白名单放行，用户正文结构上进不去（见 §泄漏腿）；
② 不改判定——本文件只断言「读得到」，不碰放行/拦截结果（见 §零判定腿）；
③ 不新增配置键——全链无 config 读取（发射点靠 receipt.transport 短路）。

注毒判据（两条，摘掉任一即红）：
* 把发射点的 `**_policy_gate_values(audit_logger, receipt, message)` 删掉
  ⇒ §接线腿当场红（行为腿仍绿，正是"库里有账、行上看不见"的原始病形）；
* 把 `gate.py::_denied` 的 `reason=reason` 传参摘掉（或把
  `domains/ops/smoke/diagnostics.py::infer_policy_gate_fields` 的 reason 分支摘掉）
  ⇒ §真链路腿全红。
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime import (
    _log_runtime_event,
    _policy_gate_values,
    _runtime_tag_values,
)
from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.contracts import (
    AuditRecord,
    CapabilityResult,
    DeliveryReceipt,
    IncomingMessage,
    ReceiptState,
    RiskLevel,
    SendPolicy,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.pipeline import (
    RuntimePipeline,
)
from plugins.bot_unified_runtime.domains.ops.monitor.runtime_event_log import (
    RuntimeEventLog,
)
from plugins.bot_unified_runtime.domains.transport.sender import InMemorySendQueue

_ROOT_INIT = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "bot_unified_runtime"
    / "__init__.py"
)

#: 发射点已占用的字段名（`_log_runtime_event` 自己补的 + 显式 kwarg +
#: `_runtime_tag_values` 的既有载体）。新键与之相交＝`**` 展开当场 TypeError，
#: 或覆盖旧字段＝谎报，两者都是「加了可观测性、炸了发消息」的最坏连带损伤。
_OCCUPIED_LOG_FIELDS = {
    "request_id",
    "adapter",
    "platform",
    "bot_id",
    "session_type",
    "capability_id",
    "receipt_state",
    "transport",
    "duration_ms",
    "route_attempts",
    "model",
    "error_kind",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "cost_milli",
}

_USER_TEXT = "今晚月色真美，我在群里闲聊的一句话，别把它写进日志"


def _group_message(text: str = _USER_TEXT, **overrides: object) -> IncomingMessage:
    kwargs: dict[str, object] = {
        "platform": "qq",
        "adapter": "onebot",
        "bot_id": "10000",
        "session_id": "group_123",
        "session_type": SessionType.GROUP,
        "sender_id": "user-1",
        "group_id": "group-1",
        "plain_text": text,
        "mentions_bot": False,
        "message_id": "m-1",
    }
    kwargs.update(overrides)
    return IncomingMessage(**kwargs)  # type: ignore[arg-type]


def _blocked_capability(calls: list[str]):
    def _run(message: IncomingMessage, decision: object) -> CapabilityResult:
        calls.append(message.message_id or "")
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.chat",
            kind="text",
            body="不该被跑到",
            send_policy=SendPolicy.SILENT_AUDIT,
        )

    return _run


def _never_run_capability(calls: list[str]):
    def _run(message: IncomingMessage, decision: object) -> CapabilityResult:
        calls.append(message.message_id or "")
        raise AssertionError("capability must not run when a gate blocks the message")

    return _run


def _pipeline(
    audit: InMemoryAuditLogger,
    **policy_kwargs: object,
) -> RuntimePipeline:
    """真门禁、真管线、真审计留痕——只把「能力执行」这一格换掉。"""
    queue = InMemorySendQueue(audit_logger=audit)
    kwargs: dict[str, object] = {
        "group_auto_reply_enabled": False,
        "group_auto_reply_probability": 0.0,
    }
    kwargs.update(policy_kwargs)
    return RuntimePipeline(
        send_queue=queue,
        audit_logger=audit,
        rate_limiter=SimpleNamespace(  # 桩：本文件测「读得到」，不限流器行为
            check_and_record=lambda *a, **k: SimpleNamespace(
                allowed=True, reason="allowed", audit_tags=[], debug_id="rl-ok"
            )
        ),
        quiet_hours_checker=SimpleNamespace(
            check=lambda *a, **k: SimpleNamespace(
                allowed=True, reason="disabled", audit_tags=[], debug_id="qh-ok"
            )
        ),
        **kwargs,  # type: ignore[arg-type]
    )


def _gate_fields(
    audit: InMemoryAuditLogger,
    receipt: DeliveryReceipt,
    message: IncomingMessage,
) -> dict[str, object]:
    """调根文件真身（发射点上的字段就是它产的），不在测试里复刻判据。"""
    return _policy_gate_values(audit, receipt, message)


def _emit_pipeline_result(
    log: RuntimeEventLog,
    audit: InMemoryAuditLogger,
    receipt: DeliveryReceipt,
    message: IncomingMessage,
) -> str:
    """按发射点同款 kwargs 落一行——用的还是那两枚真提取口。"""
    _log_runtime_event(
        log,
        "WARNING",
        "pipeline_result",
        message=message,
        capability_id="bot.chat",
        receipt_state=receipt.state.value,
        transport=receipt.transport,
        duration_ms=48.4,
        **_runtime_tag_values(None),
        **_policy_gate_values(audit, receipt, message),
    )
    return (Path(str(log.path))).read_text(encoding="utf-8")


# ============================ ① 真链路：门因读得到 ============================


def test_passive_group_block_reports_its_gate_reason(tmp_path: Path) -> None:
    """今晚实跑那条形体的理想态：一行之内看得见「哪一层、哪道门、门因叫什么」。"""
    audit = InMemoryAuditLogger()
    calls: list[str] = []
    message = _group_message()
    receipt = _pipeline(audit).handle(
        message, _never_run_capability(calls), "bot.chat"
    )

    assert receipt.state is ReceiptState.BLOCKED
    assert receipt.transport == "policy"
    assert calls == []  # 红线②：本波零判定改动，被拦的照旧不进能力

    fields = _gate_fields(audit, receipt, message)
    assert fields["policy_gate"] == "policy_denied", fields
    assert fields["policy_reason"] == "passive_group_message", fields

    line = _emit_pipeline_result(
        RuntimeEventLog(tmp_path / "runtime.log"), audit, receipt, message
    )
    assert "receipt_state=blocked" in line and "transport=policy" in line
    assert "policy_gate=policy_denied" in line
    assert "policy_reason=passive_group_message" in line
    # 红线①（规则 3）：门因进来了，用户原话一个字都没跟进来。
    assert _USER_TEXT not in line, line


@pytest.mark.parametrize(
    ("policy_kwargs", "expected_reason"),
    [
        ({"group_black1": frozenset({"group-1"})}, "group_black1"),
        ({"group_black2": frozenset({"group-1"})}, "group_black2"),
        ({"group_white2": frozenset({"group-1"})}, "group_white2_need_trigger"),
    ],
)
def test_every_controlled_group_denial_reason_reaches_the_fields(
    policy_kwargs: dict[str, object], expected_reason: str
) -> None:
    """抽签未中之外的三道群策略门：门因逐个都得读得出来，不是只修一条腿。"""
    audit = InMemoryAuditLogger()
    calls: list[str] = []
    message = _group_message()
    receipt = _pipeline(audit, **policy_kwargs).handle(
        message, _never_run_capability(calls), "bot.chat"
    )

    assert receipt.state is ReceiptState.BLOCKED
    assert calls == []
    assert _gate_fields(audit, receipt, message)["policy_reason"] == expected_reason


def test_long_text_soft_mention_reason_is_not_flattened_into_passive_message() -> None:
    """R4 软点名那条门必须与「抽签未中」区分得开——否则「为什么不回我」还是查不清。"""
    audit = InMemoryAuditLogger()
    calls: list[str] = []
    message = _group_message(
        "刚才那段复盘我先记着，晚上再对着地图核一遍，谁值日记得把灯带上，"
        "别又留到第二天早上一堆东西没人管，看着怪难受的",
        soft_persona_mention=True,
    )
    receipt = _pipeline(audit).handle(message, _never_run_capability(calls), "bot.chat")

    assert receipt.state is ReceiptState.BLOCKED
    assert _gate_fields(audit, receipt, message)["policy_reason"] == (
        "long_text_soft_mention"
    )


def test_quiet_hours_block_reports_reason_and_controlled_tags(tmp_path: Path) -> None:
    """安静时间腿的留痕形是 `reason=…; audit_tags=…`：门因与受控标签都要读回。"""
    audit = InMemoryAuditLogger()
    calls: list[str] = []
    message = _group_message(mentions_bot=True)
    pipeline = _pipeline(audit)
    pipeline.quiet_hours_checker = SimpleNamespace(
        check=lambda *a, **k: SimpleNamespace(
            allowed=False,
            reason="quiet_hours",
            audit_tags=[
                "quiet_hours:blocked",
                "quiet_hours:session:group",
                "quiet_hours:capability:bot.chat",
            ],
            debug_id="qh-blocked",
        )
    )
    receipt = pipeline.handle(message, _never_run_capability(calls), "bot.chat")

    assert receipt.state is ReceiptState.BLOCKED
    fields = _gate_fields(audit, receipt, message)
    assert fields["policy_gate"] == "quiet_hours_blocked", fields
    assert fields["policy_reason"] == "quiet_hours", fields
    assert fields["policy_tags"] == (
        "quiet_hours:blocked|quiet_hours:session:group|quiet_hours:capability:bot.chat"
    ), fields

    line = _emit_pipeline_result(
        RuntimeEventLog(tmp_path / "runtime.log"), audit, receipt, message
    )
    assert "policy_tags=quiet_hours:blocked" in line


def test_rate_limit_block_reports_the_limiter_reason() -> None:
    """限流腿（`reason=…; retry_after_seconds=…`）：门因取限流器的受控枚举。"""
    audit = InMemoryAuditLogger()
    calls: list[str] = []
    message = _group_message(mentions_bot=True)
    pipeline = _pipeline(audit)
    pipeline.rate_limiter = SimpleNamespace(
        check_and_record=lambda *a, **k: SimpleNamespace(
            allowed=False,
            reason="sender_min_interval",
            retry_after_seconds=45,
            audit_tags=["rate_limit:sender_interval"],
            debug_id="rl-blocked",
        )
    )
    receipt = pipeline.handle(message, _never_run_capability(calls), "bot.chat")

    assert receipt.state is ReceiptState.BLOCKED
    fields = _gate_fields(audit, receipt, message)
    assert fields["policy_gate"] == "rate_limited", fields
    assert fields["policy_reason"] == "sender_min_interval", fields


def test_runtime_paused_and_duplicate_layers_fall_back_to_the_event_name() -> None:
    """留痕里没有 reason 的层（暂停/重复投递）也要有个可归因的门因，不许留空。"""
    audit = InMemoryAuditLogger()
    calls: list[str] = []
    message = _group_message(mentions_bot=True)
    pipeline = _pipeline(audit)
    pipeline.runtime_control = SimpleNamespace(
        allows=lambda capability_id: False, reason="manual_pause"
    )
    receipt = pipeline.handle(message, _never_run_capability(calls), "bot.chat")

    assert receipt.state is ReceiptState.BLOCKED
    assert _gate_fields(audit, receipt, message)["policy_reason"] == "manual_pause"


# ==================== ② 红线①：白名单之外什么都进不了字段 ====================


class _StubAudit:
    def __init__(self, records: list[AuditRecord]) -> None:
        self._records = records

    def list_records(self, request_id: str | None = None) -> list[AuditRecord]:
        return list(self._records)


def _policy_record(private_debug: str, *, event: str = "policy_denied") -> AuditRecord:
    return AuditRecord(
        request_id="req-1",
        session_id="group_123",
        capability_id="bot.chat",
        stage="policy",
        event=event,
        severity=RiskLevel.LOW,
        public_message="",
        private_debug=private_debug,
    )


def _runtime_receipt() -> DeliveryReceipt:
    return DeliveryReceipt(
        request_id="req-1",
        state=ReceiptState.BLOCKED,
        transport="policy",
        public_message="",
    )


def test_free_text_never_becomes_a_gate_reason(tmp_path: Path) -> None:
    """留痕里混进自由文本（正文/路径/密钥形态）时：只准退回受控 event 名。"""
    record = _policy_record(f"{_USER_TEXT} C:/Users/x/.env token=sk-abcdef1234567")
    fields = _policy_gate_values(
        _StubAudit([record]), _runtime_receipt(), _group_message()
    )

    assert fields == {"policy_gate": "policy_denied", "policy_reason": "policy_denied"}
    log = RuntimeEventLog(tmp_path / "runtime.log")
    line = _emit_pipeline_result(log, _StubAudit([record]), _runtime_receipt(), _group_message())
    assert _USER_TEXT not in line and "sk-abcdef1234567" not in line and ".env" not in line


def test_reason_key_value_must_also_pass_the_whitelist() -> None:
    """`reason=<自由文本>` 同样被拒：白名单不看键名，只看取值形不形如受控枚举。"""
    fields = _policy_gate_values(
        _StubAudit(
            [_policy_record(f"reason={_USER_TEXT}; audit_tags=quiet_hours:blocked")]
        ),
        _runtime_receipt(),
        _group_message(),
    )
    assert fields["policy_reason"] == "policy_denied", fields
    # 标签腿独立过闸：能放行受控记号，也拒得掉混进来的正文。
    assert fields["policy_tags"] == "quiet_hours:blocked", fields


def test_new_gate_fields_never_collide_with_existing_log_fields() -> None:
    """`**` 展开的键名必须与发射点既有字段不相交（相交即覆盖旧账或当场报错）。"""
    fields = _policy_gate_values(
        _StubAudit(
            [
                _policy_record(
                    "reason=quiet_hours; audit_tags=quiet_hours:blocked",
                    event="quiet_hours_blocked",
                )
            ]
        ),
        _runtime_receipt(),
        _group_message(),
    )
    assert fields
    assert set(fields) & _OCCUPIED_LOG_FIELDS == set(), sorted(fields)
    assert all(key.isidentifier() for key in fields), sorted(fields)


# ==================== ③ 零污染 / fail-open：观测面不许碰链路 ====================


def test_non_policy_lines_emit_no_gate_fields() -> None:
    """正常发送腿（transport=runtime/onebot）一个字节都不许多出来。"""
    receipt = DeliveryReceipt(
        request_id="req-1", state=ReceiptState.SENT, transport="runtime"
    )

    def _boom(*_a: object, **_k: object) -> object:
        raise AssertionError("gate fields must not read the audit store on non-policy legs")

    assert _policy_gate_values(
        SimpleNamespace(list_records=_boom), receipt, _group_message()
    ) == {}


def test_audit_store_read_failure_stays_silent() -> None:
    """读不到留痕＝退回旧行形态，绝不把异常漏进消息链路。"""

    def _raise(*_a: object, **_k: object) -> object:
        raise RuntimeError("audit store exploded")

    assert _policy_gate_values(
        SimpleNamespace(list_records=_raise), _runtime_receipt(), _group_message()
    ) == {}


def test_last_policy_record_wins_when_a_request_carries_several_gates() -> None:
    """同一 request 上多条门禁留痕：取最后一条（本轮真正的拦截层），不自己拼判定。"""
    fields = _policy_gate_values(
        _StubAudit(
            [
                _policy_record("passive_group_message"),
                _policy_record("reason=quiet_hours", event="quiet_hours_blocked"),
            ]
        ),
        _runtime_receipt(),
        _group_message(),
    )
    assert fields["policy_gate"] == "quiet_hours_blocked", fields
    assert fields["policy_reason"] == "quiet_hours", fields


def test_gate_emits_nothing_when_no_policy_record_exists() -> None:
    assert (
        _policy_gate_values(_StubAudit([]), _runtime_receipt(), _group_message()) == {}
    )


# ==================== ④ 接线腿（注毒靶：删掉那枚 ** 就红） ====================


def _pipeline_result_call() -> ast.Call:
    tree = ast.parse(_ROOT_INIT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "_log_runtime_event":
            continue
        literals = [arg.value for arg in node.args if isinstance(arg, ast.Constant)]
        if "pipeline_result" in literals:
            return node
    raise AssertionError("根 __init__.py 里找不到 pipeline_result 的发射点")


def test_pipeline_result_emit_site_wires_the_gate_fields() -> None:
    """发射点必须真的 `**_policy_gate_values(...)`：库里有账 ≠ 行上看得见。

    注毒＝把那一行 `**_policy_gate_values(audit_logger, receipt, message),` 删掉，
    本例当场红（其余行为腿全绿——这正是本波要治的那枚病形）。
    """
    call = _pipeline_result_call()
    unpacked = [kw for kw in call.keywords if kw.arg is None]
    unpack_names = [
        item.value.func.id
        for item in unpacked
        if isinstance(item.value, ast.Call) and isinstance(item.value.func, ast.Name)
    ]
    assert "_policy_gate_values" in unpack_names, unpack_names
    # 旧载体不许被替换掉：门因是**加**上去的，不是把 tags 提取口挤下来。
    assert "_runtime_tag_values" in unpack_names, unpack_names
    given = {kw.arg for kw in call.keywords if kw.arg}
    assert {"receipt_state", "transport", "capability_id"} <= given, sorted(given)
    for name in unpack_names:
        assert name in {"_runtime_tag_values", "_policy_gate_values"}, unpack_names


def test_gate_field_reader_lives_outside_the_root_file(tmp_path: Path) -> None:
    """解析判据只准有一份真身：根文件只做「取记录 + 转交」，不在发射点旁再拼判定。"""
    source = _ROOT_INIT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    helpers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_policy_gate_values"
    ]
    assert len(helpers) == 1, helpers
    body = ast.dump(helpers[0])
    assert "infer_policy_gate_fields" in body, "提取口必须转交 diagnostics 真身"
    # 根文件里不许长出第二份「读门禁留痕」的解析逻辑。
    assert source.count('record.stage != "policy"') == 0
    assert source.count('stage == "policy"') <= 1, "只准 _should_silently_skip 那一处旧判据"
