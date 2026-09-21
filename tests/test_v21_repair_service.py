"""V21-REPAIR-001 RepairService 回归（REP 席新建件，全离线）。

覆盖合同钉死面：
- 两轮预算耗尽 → abandoned + RED 保留件（失败测试原样，内容+mtime 不变）；
- 补丁绝不落目标文件（目标文件内容 + mtime_ns 双断言）；
- 越权应用（apply_to_target / deploy_patch）拒绝 + 审计事件；
- 脱敏（BOT_= / sk- / 盘符路径 / Bearer 在 patch 件与 diagnostic 件被打码）；
- ticket 目录名消毒（越界/分隔符/非安全字符 → 安全单段名）；
- 幂等（同失败坐标重复提交零新产件、manifest 不重写）；
- 两轮预算钳制（构造器传大值也被钳回 2）；
- NoopVerifier 诚实申报；验证 detail 截断+脱敏；
- apply_unified_diff 纯函数往返 + 失配拒绝；
- SandboxCopyVerifier 迷你仓端到端真跑（本地子进程 pytest，仓库零触碰）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.ops.repair.service import (
    DEFAULT_MAX_ROUNDS,
    PatchApplyError,
    PatchProposal,
    RepairRequest,
    RepairService,
    RepairStatus,
    SandboxCopyVerifier,
    StaticProposalGenerator,
    TargetRejectedError,
    UnauthorizedRepairOperation,
    apply_unified_diff,
    build_unified_diff,
)
from plugins.bot_unified_runtime.domains.ops.repair.service import (
    redact_text as _repair_redact_text,
)

PAST_MTIME_NS = 1_700_000_000_000_000_000

TARGET_ORIGINAL = 'VALUE = "original"\n\n\ndef get_value() -> str:\n    return VALUE\n'

REDACT_TEST_FILE = "tests/test_target_feature.py"
REDACT_TEST_CONTENT = (
    "from pkg_assert.target import get_value\n"
    "\n"
    "\n"
    "def test_value():\n"
    "    assert get_value() == 'original'\n"
)


class ListAuditSink:
    """审计收集器（测试专用）。"""

    def __init__(self) -> None:
        self.events: list[dict] = []

    def emit(self, event: dict) -> None:
        self.events.append(event)


class ScriptedVerifier:
    """按剧本回放验证结果（离线桩）。"""

    def __init__(self, passed: bool, detail: str = "scripted") -> None:
        self._passed = passed
        self._detail = detail
        self.calls: list[int] = []

    def verify(self, ticket, patch_text: str, round_no: int):
        self.calls.append(round_no)
        from plugins.bot_unified_runtime.domains.ops.repair.service import (
            VerificationResult,
        )

        return VerificationResult(
            passed=self._passed, detail=self._detail, round_no=round_no
        )


class DetailVerifier:
    """固定 detail 回放（用于截断/脱敏断言）。"""

    def __init__(self, detail: str) -> None:
        self._detail = detail

    def verify(self, ticket, patch_text: str, round_no: int):
        from plugins.bot_unified_runtime.domains.ops.repair.service import (
            VerificationResult,
        )

        return VerificationResult(passed=False, detail=self._detail, round_no=round_no)


def _make_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "pkg_assert" / "target.py").parent.mkdir(parents=True)
    (ws / "pkg_assert" / "target.py").write_text(TARGET_ORIGINAL, encoding="utf-8")
    (ws / REDACT_TEST_FILE).parent.mkdir(parents=True, exist_ok=True)
    (ws / REDACT_TEST_FILE).write_text(REDACT_TEST_CONTENT, encoding="utf-8")
    return ws


def _pin_mtime(path: Path) -> None:
    os.utime(path, ns=(PAST_MTIME_NS, PAST_MTIME_NS))


def _proposal(index: int, extra: str = "") -> PatchProposal:
    return PatchProposal(
        target_file="pkg_assert/target.py",
        new_content=(
            f'VALUE = "fixed-{index}"\n{extra}\n\ndef get_value() -> str:\n'
            "    return VALUE\n"
        ),
        note=f"round {index} proposal",
    )


def _make_service(
    tmp_path: Path,
    ws: Path,
    *,
    verifier=None,
    proposals: tuple[PatchProposal, ...] = (),
    audit_sink: ListAuditSink | None = None,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
) -> RepairService:
    sinks = [audit_sink] if audit_sink is not None else []
    return RepairService(
        pending_root=tmp_path / "pending",
        workspace_root=ws,
        verifier=verifier,
        generator=StaticProposalGenerator(list(proposals)),
        audit_sinks=sinks,
        clock=lambda: 1_000.0,
        max_rounds=max_rounds,
    )


def _make_request(extra_summary: str = "") -> RepairRequest:
    return RepairRequest(
        test_id=f"{REDACT_TEST_FILE}::test_value",
        error_summary=f"AssertionError: assert 'original' == 'expected' {extra_summary}",
        target_file="pkg_assert/target.py",
    )


def _ticket_files(pending: Path, ticket_id: str) -> set[str]:
    return {p.name for p in (pending / ticket_id).iterdir()}


# --- 两轮预算 + RED 保留 ------------------------------------------------------


def test_two_round_budget_exhaustion_abandons_and_preserves_red(tmp_path):
    ws = _make_workspace(tmp_path)
    red_file = ws / REDACT_TEST_FILE
    _pin_mtime(red_file)
    red_before = red_file.read_bytes()
    sink = ListAuditSink()
    service = _make_service(
        tmp_path,
        ws,
        verifier=ScriptedVerifier(passed=False),
        proposals=(_proposal(1), _proposal(2), _proposal(3)),
        audit_sink=sink,
    )
    ticket = service.submit_failure(_make_request())
    assert ticket.max_rounds == 2
    ticket = service.run_repair(ticket.ticket_id, _make_request())

    assert ticket.status == RepairStatus.ABANDONED
    assert ticket.rounds_used == 2
    assert ticket.red_retained is True
    pending = tmp_path / "pending"
    names = _ticket_files(pending, ticket.ticket_id)
    # 恰好两轮待审件；第三提案永不消费（预算钳死）。
    assert names == {
        "manifest.json",
        "round-1.patch",
        "round-1.verify.json",
        "round-2.patch",
        "round-2.verify.json",
        "diagnostic.md",
        "RED-RETAINED.md",
    }
    # RED 声明在盘且点名坐标。
    red_note = (pending / ticket.ticket_id / "RED-RETAINED.md").read_text(
        encoding="utf-8"
    )
    assert "test_target_feature.py::test_value" in red_note
    assert "RED" in red_note
    # 失败测试原样：内容 + mtime 双断言（RED 不删不改）。
    assert red_file.read_bytes() == red_before
    assert red_file.stat().st_mtime_ns == PAST_MTIME_NS
    # 诊断报告记录两轮与放弃原因。
    diag = (pending / ticket.ticket_id / "diagnostic.md").read_text(encoding="utf-8")
    assert "round 1" in diag and "round 2" in diag
    assert "budget_exhausted" in diag
    # 终态 ticket 重跑不追加任何产件（幂等运行）。
    service.run_repair(ticket.ticket_id, _make_request())
    assert _ticket_files(pending, ticket.ticket_id) == names
    kinds = [e["kind"] for e in sink.events]
    assert kinds.count("repair_abandoned") == 1


def test_patch_never_writes_target_file(tmp_path):
    ws = _make_workspace(tmp_path)
    target = ws / "pkg_assert" / "target.py"
    _pin_mtime(target)
    original_bytes = target.read_bytes()
    service = _make_service(
        tmp_path,
        ws,
        verifier=ScriptedVerifier(passed=False),
        proposals=(_proposal(1), _proposal(2)),
    )
    ticket = service.submit_failure(_make_request())
    service.run_repair(ticket.ticket_id, _make_request())
    # 补丁只能落待审区，目标文件内容与 mtime_ns 零变化。
    assert target.read_bytes() == original_bytes
    assert target.stat().st_mtime_ns == PAST_MTIME_NS
    patch_text = (
        tmp_path / "pending" / ticket.ticket_id / "round-1.patch"
    ).read_text(encoding="utf-8")
    assert "fixed-1" in patch_text  # 修正内容只存在于 diff 产物里
    assert target.read_bytes() == original_bytes


def test_verified_patch_still_pending_never_applied(tmp_path):
    ws = _make_workspace(tmp_path)
    target = ws / "pkg_assert" / "target.py"
    _pin_mtime(target)
    original_bytes = target.read_bytes()
    sink = ListAuditSink()
    service = _make_service(
        tmp_path,
        ws,
        verifier=ScriptedVerifier(passed=True, detail="1 passed"),
        proposals=(_proposal(1), _proposal(2)),
        audit_sink=sink,
    )
    ticket = service.submit_failure(_make_request())
    ticket = service.run_repair(ticket.ticket_id, _make_request())
    assert ticket.status == RepairStatus.VERIFIED_PENDING
    assert ticket.rounds_used == 1
    # 验证通过也绝不应用：目标文件原样。
    assert target.read_bytes() == original_bytes
    assert target.stat().st_mtime_ns == PAST_MTIME_NS
    info = service.request_application(ticket.ticket_id)
    assert info["status"] == RepairStatus.VERIFIED_PENDING
    assert "round-1.patch" in info["pending_artifacts"]
    assert "人工" in info["instruction"]
    kinds = [e["kind"] for e in sink.events]
    assert "repair_round_completed" in kinds


# --- 越权防护 -----------------------------------------------------------------


def test_unauthorized_apply_and_deploy_rejected_and_audited(tmp_path):
    ws = _make_workspace(tmp_path)
    target = ws / "pkg_assert" / "target.py"
    _pin_mtime(target)
    original_bytes = target.read_bytes()
    sink = ListAuditSink()
    service = _make_service(
        tmp_path, ws, proposals=(_proposal(1),), audit_sink=sink
    )
    ticket = service.submit_failure(_make_request())
    with pytest.raises(UnauthorizedRepairOperation):
        service.apply_to_target(ticket.ticket_id)
    with pytest.raises(UnauthorizedRepairOperation):
        service.deploy_patch(ticket.ticket_id, force=True)
    # 两次越权各有审计事件，目标文件零触碰。
    kinds = [e["kind"] for e in sink.events]
    assert kinds.count("repair_unauthorized_rejected") == 2
    assert target.read_bytes() == original_bytes
    assert target.stat().st_mtime_ns == PAST_MTIME_NS


# --- 脱敏 ---------------------------------------------------------------------


def test_sanitization_masks_secrets_in_patch_and_diagnostic(tmp_path):
    ws = _make_workspace(tmp_path)
    secret_extra = (
        'BOT_SUPER_SECRET_TOKEN=supersecretvalue123\n'
        'api_key = "sk-abcdef1234567890abcdef"\n'
        'log_dir = r"C:\\Users\\lancy\\AppData\\secret"\n'
        'auth_header = "Bearer abcdefgh12345678"\n'
    )
    sink = ListAuditSink()
    service = _make_service(
        tmp_path,
        ws,
        verifier=ScriptedVerifier(passed=False),
        proposals=(_proposal(1, secret_extra), _proposal(2, secret_extra)),
        audit_sink=sink,
    )
    ticket = service.submit_failure(_make_request())
    ticket = service.run_repair(ticket.ticket_id, _make_request())
    assert ticket.status == RepairStatus.ABANDONED
    ticket_dir = tmp_path / "pending" / ticket.ticket_id
    for name in ("round-1.patch", "round-2.patch", "diagnostic.md"):
        text = (ticket_dir / name).read_text(encoding="utf-8")
        assert "supersecretvalue123" not in text
        assert "sk-abcdef1234567890abcdef" not in text
        assert "Users\\\\lancy" not in text and "Users\\lancy" not in text
        assert "abcdefgh12345678" not in text
    patch_text = (ticket_dir / "round-1.patch").read_text(encoding="utf-8")
    assert "<已隐藏>" in patch_text
    assert "<本机路径已隐藏>" in patch_text
    # 审计事件里同样不允许出现原始密钥形态。
    for event in sink.events:
        blob = json.dumps(event, ensure_ascii=False)
        assert "supersecretvalue123" not in blob
        assert "sk-abcdef" not in blob


def test_verifier_detail_truncated_and_sanitized(tmp_path):
    ws = _make_workspace(tmp_path)
    huge = ("x" * 5000) + " token=ghp_abcdefghijklmnopqrstuvwxyz012345 end"
    service = _make_service(
        tmp_path,
        ws,
        verifier=DetailVerifier(huge),
        proposals=(_proposal(1), _proposal(2)),
    )
    ticket = service.submit_failure(_make_request())
    service.run_repair(ticket.ticket_id, _make_request())
    verify = json.loads(
        (tmp_path / "pending" / ticket.ticket_id / "round-1.verify.json").read_text(
            encoding="utf-8"
        )
    )
    assert verify["passed"] is False
    assert "ghp_abcdefghijklmnopqrstuvwxyz012345" not in verify["detail"]
    assert len(verify["detail"]) <= 1300  # 1200 截断 + 省略号标记


# --- 目录消毒 / 目标校验 / 幂等 ------------------------------------------------


def test_ticket_dir_name_sanitized(tmp_path):
    ws = _make_workspace(tmp_path)
    service = _make_service(tmp_path, ws, proposals=(_proposal(1),))
    request = RepairRequest(
        test_id="../../evil path::test_你好??<script>",
        error_summary="AssertionError: boom",
        target_file="pkg_assert/target.py",
    )
    ticket = service.submit_failure(request)
    name = ticket.ticket_id.rsplit("-", 1)[0]
    bad_chars = set(name) & set("/\\ !?:<>?") | {c for c in name if ord(c) > 127}
    assert not bad_chars
    assert ".." not in name
    assert (tmp_path / "pending" / ticket.ticket_id).is_dir()


def test_forbidden_or_escaping_targets_rejected_before_any_write(tmp_path):
    ws = _make_workspace(tmp_path)
    service = _make_service(tmp_path, ws, proposals=(_proposal(1),))
    bad_targets = [
        ".env",
        "ChatBot_Runtime/db/x.sqlite3",
        "../outside.py",
        "C:\\abs\\path.py",
        "personas/shorekeeper/identity.md",
    ]
    for target in bad_targets:
        with pytest.raises(TargetRejectedError):
            service.submit_failure(
                RepairRequest(
                    test_id="tests/test_x.py::test_y",
                    error_summary="AssertionError: x",
                    target_file=target,
                )
            )
    # 提交期即拒绝：待审区零落盘。
    assert not (tmp_path / "pending").exists() or not any(
        (tmp_path / "pending").iterdir()
    )


def test_idempotent_resubmission_no_duplicate_artifacts(tmp_path):
    ws = _make_workspace(tmp_path)
    sink = ListAuditSink()
    service = _make_service(
        tmp_path, ws, verifier=ScriptedVerifier(passed=False),
        proposals=(_proposal(1), _proposal(2)), audit_sink=sink,
    )
    first = service.submit_failure(_make_request())
    pending = tmp_path / "pending"
    files_before = sorted(_ticket_files(pending, first.ticket_id))
    manifest_before = (pending / first.ticket_id / "manifest.json").read_bytes()
    second = service.submit_failure(_make_request())
    assert second.ticket_id == first.ticket_id
    assert sorted(_ticket_files(pending, first.ticket_id)) == files_before
    assert (pending / first.ticket_id / "manifest.json").read_bytes() == manifest_before
    kinds = [e["kind"] for e in sink.events]
    assert kinds.count("repair_submitted") == 1
    assert kinds.count("repair_resubmit_ignored") == 1


def test_max_rounds_clamped_to_contract_budget(tmp_path):
    ws = _make_workspace(tmp_path)
    service = _make_service(
        tmp_path,
        ws,
        verifier=ScriptedVerifier(passed=False),
        proposals=tuple(_proposal(i) for i in range(1, 6)),
        max_rounds=9,
    )
    ticket = service.submit_failure(_make_request())
    assert ticket.max_rounds == 2
    ticket = service.run_repair(ticket.ticket_id, _make_request())
    assert ticket.rounds_used == 2
    assert ticket.status == RepairStatus.ABANDONED


def test_noop_verifier_honest_no_false_pass(tmp_path):
    ws = _make_workspace(tmp_path)
    service = _make_service(tmp_path, ws, proposals=(_proposal(1), _proposal(2)))
    ticket = service.submit_failure(_make_request())
    ticket = service.run_repair(ticket.ticket_id, _make_request())
    assert ticket.status == RepairStatus.ABANDONED
    verify = json.loads(
        (tmp_path / "pending" / ticket.ticket_id / "round-1.verify.json").read_text(
            encoding="utf-8"
        )
    )
    assert verify["passed"] is False
    assert "NoopVerifier" in verify["detail"]


# --- diff 纯函数 ---------------------------------------------------------------


def test_apply_unified_diff_roundtrip_and_mismatch():
    original = "line1\nline2\nline3\nline4\n"
    updated = "line1\nline2-changed\nline3\nline4\nline5\n"
    diff_text = build_unified_diff(original, updated, "some/target.py")
    assert diff_text.startswith("--- a/some/target.py")
    assert apply_unified_diff(original, diff_text) == updated
    with pytest.raises(PatchApplyError):
        apply_unified_diff("totally\ndifferent\ncontent\n", diff_text)


# --- 迷你仓端到端（真实子进程 pytest，仓库本体零触碰） -------------------------


def test_sandbox_copy_verifier_end_to_end(tmp_path):
    venv_python = sys.executable
    ws = tmp_path / "mini"
    (ws / "mathlib").mkdir(parents=True)
    (ws / "mathlib" / "__init__.py").write_text("", encoding="utf-8")
    (ws / "mathlib" / "calc.py").write_text(
        "def add(a, b):\n    return a - b\n", encoding="utf-8"
    )
    (ws / "tests").mkdir()
    (ws / "tests" / "test_calc.py").write_text(
        "from mathlib.calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    (ws / "conftest.py").write_text('"""mini repo conftest."""\n', encoding="utf-8")
    target = ws / "mathlib" / "calc.py"
    _pin_mtime(target)
    broken_bytes = target.read_bytes()

    service = RepairService(
        pending_root=tmp_path / "pending",
        workspace_root=ws,
        verifier=SandboxCopyVerifier(venv_python, ws, timeout_seconds=120.0),
        generator=StaticProposalGenerator(
            [
                PatchProposal(
                    target_file="mathlib/calc.py",
                    new_content="def add(a, b):\n    return a + b\n",
                    note="operator fix",
                )
            ]
        ),
        audit_sinks=[],
        clock=lambda: 1.0,
    )
    request = RepairRequest(
        test_id="tests/test_calc.py::test_add",
        error_summary="AssertionError: assert -1 == 5",
        target_file="mathlib/calc.py",
    )
    ticket = service.submit_failure(request)
    ticket = service.run_repair(ticket.ticket_id, request)
    assert ticket.status == RepairStatus.VERIFIED_PENDING
    assert ticket.rounds_used == 1
    # 真实验证器确实跑过目标测试且通过。
    verify = json.loads(
        (tmp_path / "pending" / ticket.ticket_id / "round-1.verify.json").read_text(
            encoding="utf-8"
        )
    )
    assert verify["passed"] is True
    assert "1 passed" in verify["detail"]
    # 仓库本体的坏实现原样（补丁只存在于沙箱与待审件）。
    assert target.read_bytes() == broken_bytes
    assert target.stat().st_mtime_ns == PAST_MTIME_NS
    # 脱敏出口自检（与 render 真身同一事实源的懒加载通路）。
    assert _repair_redact_text("BOT_X=a secret here").startswith("BOT_X=<已隐藏>")
