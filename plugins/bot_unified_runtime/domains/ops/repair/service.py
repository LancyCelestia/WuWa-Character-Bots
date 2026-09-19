"""自修复编排服务（V21-REPAIR-001 唯一载体，REP 席新建件）。

合同条款（V21-REPAIR-001，全部钉死在本模块）：

1. **输入** = 失败测试坐标：test id + 错误摘要（+ 可选补丁提案）。提案源是
   可注入的 ``PatchGenerator``（缺省 ``StaticProposalGenerator`` 重放调用方
   提案）；本服务负责的是**纪律面**——预算、待审、验证、脱敏、审计、幂等，
   不负责智能生成。
2. **两轮预算**（``DEFAULT_MAX_ROUNDS = 2``，构造器传入更大值一律钳回 2）：
   每轮取一个提案 → 生成 unified diff → 落待审区 → 沙箱跑目标测试验证 →
   过 = ``verified_pending``（**仍然不应用**）；两轮未过 = ``abandoned``
   并留 RED 声明 + 诊断报告（RED 测试必须保留，本服务永不删改它）。
3. **绝不直接写目标文件**：补丁 = diff 形态产物，只能落
   ``pending/<ticket>/round-N.patch`` 待审区；``apply_to_target()`` /
   ``deploy_patch()`` 等任何自动写入/部署面一律 raise
   ``UnauthorizedRepairOperation`` 并发审计事件。唯一合法出口 =
   ``request_application()``（只读返回待审件路径，供人审后手动应用）。
4. **脱敏（零例外）**：补丁待审件、诊断报告、审计事件三面全部过
   ``domains/render/plain_text.py::redact_local_secrets`` 真身（懒加载单一
   事实源，同 incident/service.py 形态；导入失败降级本地最小正则，绝不因
   脱敏器缺失而泄漏）；用户派生文本走 ``redact_user_text`` 只留字数痕迹。
   注意：沙箱验证用的是**未脱敏**原始提案（验证需要保真，且只存在于内存
   与一次性沙箱）；落盘待审件一律脱敏。
5. **幂等**：同失败坐标（test_id + 目标 + 归一化摘要）重复提交返回既有
   ticket，零新产件、manifest 不重写。
6. **目录消毒**：ticket 目录名 = test_id 消毒 slug + key 段，仅
   ``[A-Za-z0-9._-]``，解析后必须居 pending 根内。
7. **审计**：``RepairAuditSink`` 协议（emit(dict)），缺省 stdlib log sink
   （同 LoggingIncidentSink 形态）；可注入收集器。

沙箱验证：缺省 ``SandboxCopyVerifier`` 把工作区整树拷贝进一次性临时目录
（排除 .git/ChatBot_Runtime/缓存等重物），在沙箱内应用补丁后以子进程
``python -m pytest <node>`` 验证（PYTHONDONTWRITEBYTECODE=1 / PYTHONUTF8=1 /
BOT_AUTOSYNC=0 / -p no:cacheprovider / --basetemp 沙箱内一次性目录）；
验证完沙箱即弃。仓库本体零触碰。无验证器时用 ``NoopVerifier`` 诚实申报
「无法自动验证，待人审」，绝不谎报通过。

默认 ``pending_root`` 位于源码树（评审件同 .superpowers/sdd 先例，允许入
库供人审）；运行态部署应显式注入 Runtime 路径。测试必须注入 tmp_path。
"""

from __future__ import annotations

import difflib
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_MAX_ROUNDS",
    "DEFAULT_MAX_TEXT_CHARS",
    "FORBIDDEN_TARGET_PARTS",
    "LoggingRepairAuditSink",
    "NoopVerifier",
    "PatchApplyError",
    "PatchGenerator",
    "PatchProposal",
    "RepairAuditSink",
    "RepairRequest",
    "RepairService",
    "RepairStatus",
    "RepairTicket",
    "RepairVerifier",
    "SandboxCopyVerifier",
    "StaticProposalGenerator",
    "TargetRejectedError",
    "UnauthorizedRepairOperation",
    "VerificationResult",
    "apply_unified_diff",
    "redact_text",
    "redact_user_text",
]

#: 合同钉死的两轮预算（构造器传入更大值一律钳回此值）。
DEFAULT_MAX_ROUNDS = 2

#: 落盘文本（验证 detail / 错误摘要等）默认截断长度，防日志与报告膨胀。
DEFAULT_MAX_TEXT_CHARS = 400

#: 目标文件禁触名单（路径首段或大小写折叠前缀；本服务永远不写目标，此处
#: 是提交期即拒绝的纵深防御）。
FORBIDDEN_TARGET_PARTS: frozenset[str] = frozenset(
    {".env", "chatbot_runtime", "chatbot_archive", ".git", "personas"}
)

_SANITIZED_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")
_MULTIPLE_SEPARATORS_RE = re.compile(r"_+")

# --- 脱敏（懒加载 render 真身；形态同 incident/service.py，只读参照） -------

_FALLBACK_SK_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{6,}")
_FALLBACK_DRIVE_RE = re.compile(r"\b[A-Za-z]:[\\/][^\s\"'）)】\]]*")
_FALLBACK_ENV_RE = re.compile(r"\b(BOT_[A-Z0-9_]+)\s*=\s*[^\s，。；\"']+")
_FALLBACK_BEARER_RE = re.compile(r"\b(Bearer|bearer)\s+[A-Za-z0-9._\-]{8,}")

_REDACT_FN: Any = None


def _fallback_redact(text: str) -> str:
    """脱敏真身导入失败时的本地最小兜底（宁可多打码不能漏）。"""
    value = _FALLBACK_ENV_RE.sub(r"\1=<已隐藏>", text)
    value = _FALLBACK_BEARER_RE.sub(r"\1 <已隐藏>", value)
    value = _FALLBACK_SK_RE.sub("sk-<已隐藏>", value)
    value = _FALLBACK_DRIVE_RE.sub("<本机路径已隐藏>", value)
    return value


def _load_redactor() -> Any:
    """懒加载 render 域脱敏真身（单一事实源）；失败固定到本地兜底。"""
    global _REDACT_FN
    if _REDACT_FN is None:
        try:
            from plugins.bot_unified_runtime.domains.render.plain_text import (
                redact_local_secrets as _fn,
            )

            _REDACT_FN = _fn
        except Exception:  # noqa: BLE001 - 渲染域缺失时兜底（fail-open）
            logger.warning("repair: redact_local_secrets unavailable, fallback on")
            _REDACT_FN = _fallback_redact
    return _REDACT_FN


def redact_user_text(text: str | None) -> str:
    """用户派生文本专用：只留字数痕迹，原文零保留（同 incident 契约）。"""
    if not text:
        return ""
    return f"<用户文本 {len(text)} 字，已隐去>"


def redact_text(text: str | None, *, max_chars: int | None = None) -> str:
    """公开脱敏入口：render 真身懒加载（失败降级本地兜底正则）+ 截断。"""
    value = text or ""
    try:
        value = _load_redactor()(value)
    except Exception:
        logger.exception("repair: redaction failed, using fallback patterns")
        value = _fallback_redact(value)
    if max_chars is not None and len(value) > max_chars:
        value = value[:max_chars] + "…(已截断)"
    return value


# --- 错误粗分类（诊断报告用，确定性关键词，不猜根因） -----------------------

_ERROR_CLASSIFICATIONS: tuple[tuple[str, str], ...] = (
    ("ModuleNotFoundError", "import_breakage"),
    ("ImportError", "import_breakage"),
    ("AttributeError", "symbol_missing"),
    ("NameError", "symbol_missing"),
    ("AssertionError", "assertion_mismatch"),
    ("TypeError", "type_or_key_mismatch"),
    ("KeyError", "type_or_key_mismatch"),
    ("IndexError", "type_or_key_mismatch"),
    ("TimeoutError", "timeout"),
    ("FileNotFoundError", "missing_file"),
)


def _classify_error(summary: str) -> str:
    for needle, label in _ERROR_CLASSIFICATIONS:
        if needle in summary:
            return label
    return "unknown"


# --- 统一 diff 构造与应用 ----------------------------------------------------


def build_unified_diff(original: str, updated: str, target_rel: str) -> str:
    """original→updated 的 unified diff（diff 形态产物，人审可直接读）。"""
    old_lines = original.splitlines(keepends=True)
    new_lines = updated.splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{target_rel}",
            tofile=f"b/{target_rel}",
        )
    )


def apply_unified_diff(original: str, diff_text: str) -> str:
    """把 unified diff 应用到 original 的纯函数（沙箱专用，仓库零触碰）。

    只支持本模块 ``build_unified_diff`` 及同构产物（标准 @@ hunk 格式）。
    上下文对不上即 raise ``PatchApplyError``（宁失败不误应用）。
    """
    src = original.splitlines(keepends=True)
    diff_lines = diff_text.splitlines(keepends=True)
    out: list[str] = []
    src_pos = 0
    i = 0
    n = len(diff_lines)
    while i < n:
        line = diff_lines[i]
        if line.startswith("@@"):
            match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            if match is None:
                raise PatchApplyError(f"无法解析 hunk 头: {line.strip()!r}")
            old_start = int(match.group(1))
            if old_start < 1 or old_start - 1 < src_pos:
                raise PatchApplyError(f"hunk 旧起点回退: {old_start}")
            out.extend(src[src_pos : old_start - 1])
            src_pos = old_start - 1
            i += 1
            while i < n and not diff_lines[i].startswith("@@"):
                body = diff_lines[i]
                tag, payload = body[:1], body[1:]
                if tag == " ":
                    if src_pos >= len(src) or _line_eq(src[src_pos], payload):
                        if src_pos < len(src):
                            out.append(src[src_pos])
                            src_pos += 1
                    else:
                        raise PatchApplyError(
                            f"上下文不匹配 @ 旧第 {src_pos + 1} 行: {payload!r}"
                        )
                elif tag == "-":
                    if src_pos >= len(src) or not _line_eq(src[src_pos], payload):
                        raise PatchApplyError(
                            f"删除行不匹配 @ 旧第 {src_pos + 1} 行: {payload!r}"
                        )
                    src_pos += 1
                elif tag == "+":
                    out.append(payload if payload.endswith("\n") else payload + "\n")
                else:
                    # "\ No newline ..." 等杂注行：跳过
                    pass
                i += 1
        elif line.startswith(("--- ", "+++ ", "diff ")):  # 文件头
            i += 1
        else:
            i += 1
    out.extend(src[src_pos:])
    return "".join(out)


def _line_eq(a: str, b: str) -> bool:
    return a.rstrip("\r\n") == b.rstrip("\r\n")


# --- 数据模型 ----------------------------------------------------------------


class RepairStatus:
    """ticket 状态（纯字符串常量，manifest JSON 友好）。"""

    OPEN = "open"
    VERIFIED_PENDING = "verified_pending"
    ABANDONED = "abandoned"


@dataclass(frozen=True)
class RepairRequest:
    """失败测试坐标 + 可选补丁提案（提案内容为本服务的输入，非本服务生成）。"""

    test_id: str
    error_summary: str
    target_file: str
    patch_proposals: tuple[PatchProposal, ...] = ()


@dataclass(frozen=True)
class PatchProposal:
    """一轮补丁提案：目标文件的建议新全文（diff 由服务统一生成）。"""

    target_file: str
    new_content: str
    note: str = ""


@dataclass(frozen=True)
class VerificationResult:
    """一轮沙箱验证结果。passed 只能来自真实测试运行，绝不谎报。"""

    passed: bool
    detail: str
    round_no: int


@dataclass
class RepairTicket:
    """待审工单（manifest.json 的内存形态）。"""

    ticket_id: str
    test_id: str
    target_file: str
    status: str
    rounds_used: int
    max_rounds: int
    red_retained: bool
    created_at: float
    updated_at: float
    abandon_reason: str = ""
    error_class: str = ""

    def to_manifest(self) -> dict[str, Any]:
        return {
            "ticket_id": self.ticket_id,
            "test_id": self.test_id,
            "target_file": self.target_file,
            "status": self.status,
            "rounds_used": self.rounds_used,
            "max_rounds": self.max_rounds,
            "red_retained": self.red_retained,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "abandon_reason": self.abandon_reason,
            "error_class": self.error_class,
        }

    @classmethod
    def from_manifest(cls, data: dict[str, Any]) -> RepairTicket:
        return cls(
            ticket_id=str(data["ticket_id"]),
            test_id=str(data["test_id"]),
            target_file=str(data["target_file"]),
            status=str(data["status"]),
            rounds_used=int(data["rounds_used"]),
            max_rounds=int(data["max_rounds"]),
            red_retained=bool(data["red_retained"]),
            created_at=float(data["created_at"]),
            updated_at=float(data["updated_at"]),
            abandon_reason=str(data.get("abandon_reason", "")),
            error_class=str(data.get("error_class", "")),
        )


class UnauthorizedRepairOperation(RuntimeError):
    """越权操作：任何自动写入目标文件/部署面都被合同禁止。"""


class TargetRejectedError(ValueError):
    """目标路径越界/禁触（提交期即拒绝，零落盘）。"""


class PatchApplyError(RuntimeError):
    """unified diff 应用失败（上下文不匹配等）。"""


# --- 协议（注入面） ----------------------------------------------------------


@runtime_checkable
class RepairAuditSink(Protocol):
    """审计 sink（同 IncidentSink 形态：emit 一个 JSON 兼容 dict）。"""

    def emit(self, event: dict[str, Any]) -> None: ...


@runtime_checkable
class RepairVerifier(Protocol):
    """验证器：在**不写仓库**的前提下对补丁跑目标测试。"""

    def verify(
        self, ticket: RepairTicket, patch_text: str, round_no: int
    ) -> VerificationResult: ...


@runtime_checkable
class PatchGenerator(Protocol):
    """提案源：按轮次给提案；返回 None = 提案耗尽（诚实放弃）。"""

    def propose(
        self,
        request: RepairRequest,
        round_no: int,
        history: list[VerificationResult],
    ) -> PatchProposal | None: ...


class LoggingRepairAuditSink:
    """缺省审计 sink：stdlib log（同 LoggingIncidentSink 形态），零出站。"""

    def emit(self, event: dict[str, Any]) -> None:
        logger.info(
            "repair-audit kind=%s ticket=%s detail=%s",
            event.get("kind", "?"),
            event.get("ticket", "?"),
            event.get("detail", ""),
        )


class NoopVerifier:
    """无验证器时的诚实占位：永不判过，待审件留给人审。"""

    def verify(
        self, ticket: RepairTicket, patch_text: str, round_no: int
    ) -> VerificationResult:
        return VerificationResult(
            passed=False,
            detail="no verifier configured (NoopVerifier)；无法自动验证，补丁留待人工审核",
            round_no=round_no,
        )


class StaticProposalGenerator:
    """重放调用方预置提案（离线确定性；智能生成面留给后续席位注入）。"""

    def __init__(self, proposals: list[PatchProposal] | tuple[PatchProposal, ...]):
        self._proposals = list(proposals)

    def propose(
        self,
        request: RepairRequest,
        round_no: int,
        history: list[VerificationResult],
    ) -> PatchProposal | None:
        if not self._proposals:
            return None
        return self._proposals.pop(0)


class SandboxCopyVerifier:
    """整树拷贝沙箱验证器：仓库本体零触碰。

    流程：工作区整树拷入一次性临时目录（排除重物）→ 沙箱内应用补丁 →
    子进程 ``python -m pytest <test_id>`` → 返回结果 → 沙箱即弃。
    """

    DEFAULT_IGNORES = (
        ".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache",
        ".venv", "node_modules", "ChatBot_Runtime", "ChatBot_Archive",
        ".tox", "dist", "build", ".zcode",
    )

    def __init__(
        self,
        python_exe: str,
        workspace_root: Path | str,
        *,
        timeout_seconds: float = 600.0,
        ignores: tuple[str, ...] = DEFAULT_IGNORES,
    ):
        self._python_exe = str(python_exe)
        self._workspace_root = Path(workspace_root)
        self._timeout_seconds = timeout_seconds
        self._ignores = tuple(ignores)

    def verify(
        self, ticket: RepairTicket, patch_text: str, round_no: int
    ) -> VerificationResult:
        sandbox = Path(tempfile.mkdtemp(prefix="v21-repair-sandbox-"))
        try:
            shutil.copytree(
                self._workspace_root,
                sandbox,
                ignore=shutil.ignore_patterns(*self._ignores),
                dirs_exist_ok=True,
            )
            target_abs = sandbox / ticket.target_file
            original = target_abs.read_text(encoding="utf-8")
            patched = apply_unified_diff(original, patch_text)
            target_abs.write_text(patched, encoding="utf-8", newline="")
            basetemp = sandbox / ".pytest_tmp"
            cmd = [
                self._python_exe,
                "-m",
                "pytest",
                ticket.test_id,
                "-q",
                "-p",
                "no:cacheprovider",
                f"--basetemp={basetemp}",
            ]
            env = dict(os.environ)
            env.update(
                PYTHONDONTWRITEBYTECODE="1",
                PYTHONUTF8="1",
                BOT_AUTOSYNC="0",
            )
            proc = subprocess.run(
                cmd,
                cwd=sandbox,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout_seconds,
                check=False,
            )
            detail = (proc.stdout or "") + (proc.stderr or "")
            return VerificationResult(
                passed=proc.returncode == 0,
                detail=detail.strip()[-DEFAULT_MAX_TEXT_CHARS * 4 :],
                round_no=round_no,
            )
        except Exception as exc:  # noqa: BLE001 - 验证器故障=该轮未过，不外溢
            return VerificationResult(
                passed=False,
                detail=f"sandbox verifier error: {type(exc).__name__}: {exc}",
                round_no=round_no,
            )
        finally:
            shutil.rmtree(sandbox, ignore_errors=True)


# --- 服务本体 ----------------------------------------------------------------


class RepairService:
    """自修复编排：两轮预算内产出**待审补丁**，绝不写目标文件。"""

    def __init__(
        self,
        *,
        pending_root: Path | str | None = None,
        workspace_root: Path | str | None = None,
        verifier: RepairVerifier | None = None,
        generator: PatchGenerator | None = None,
        audit_sinks: tuple[RepairAuditSink, ...] | list[RepairAuditSink] = (),
        clock: Any = None,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
    ):
        self._pending_root = (
            Path(pending_root)
            if pending_root is not None
            else Path(__file__).resolve().parent / "pending"
        )
        self._workspace_root = (
            Path(workspace_root)
            if workspace_root is not None
            else Path(__file__).resolve().parents[5]
        )
        self._verifier = verifier if verifier is not None else NoopVerifier()
        self._generator = (
            generator if generator is not None else StaticProposalGenerator([])
        )
        self._audit_sinks: tuple[RepairAuditSink, ...] = (
            tuple(audit_sinks)
            if audit_sinks
            else (LoggingRepairAuditSink(),)
        )
        self._clock = clock if clock is not None else time.time
        # 合同钳制：两轮预算不允许被放大。
        self._max_rounds = min(int(max_rounds), DEFAULT_MAX_ROUNDS)

    # -- 公开 API ------------------------------------------------------------

    def submit_failure(self, request: RepairRequest) -> RepairTicket:
        """提交失败坐标（幂等：同坐标返回既有 ticket，零新产件）。"""
        rel_target = self._validate_target(request.target_file)
        key = self._ticket_key(request)
        ticket_id = f"{_sanitize_dir_component(request.test_id)}-{key[:12]}"
        ticket_dir = self._pending_root / ticket_id
        manifest_path = ticket_dir / "manifest.json"
        now = float(self._clock())
        if manifest_path.exists():
            ticket = self._read_ticket(manifest_path)
            self._audit(
                "repair_resubmit_ignored",
                ticket_id,
                f"幂等命中，零新产件 test={redact_user_text(request.test_id)}",
            )
            return ticket
        ticket_dir.mkdir(parents=True, exist_ok=False)
        ticket = RepairTicket(
            ticket_id=ticket_id,
            test_id=redact_text(request.test_id, max_chars=200),
            target_file=rel_target,
            status=RepairStatus.OPEN,
            rounds_used=0,
            max_rounds=self._max_rounds,
            red_retained=False,
            created_at=now,
            updated_at=now,
            error_class=_classify_error(request.error_summary),
        )
        self._write_manifest(ticket)
        self._audit(
            "repair_submitted",
            ticket_id,
            f"test={ticket.test_id} target={ticket.target_file} "
            f"class={ticket.error_class}",
        )
        return ticket

    def run_repair(self, ticket_id: str, request: RepairRequest) -> RepairTicket:
        """两轮预算内跑修复循环（终态 ticket 原样返回，不重跑）。

        每轮：取提案 → 生成 diff → 落待审件（脱敏）→ 沙箱验证 →
        过则 ``verified_pending``（仍不应用）；预算耗尽未过则 ``abandoned``
        并落 RED 声明 + 诊断报告。
        """
        ticket = self.load_ticket(ticket_id)
        if ticket.status in (RepairStatus.VERIFIED_PENDING, RepairStatus.ABANDONED):
            return ticket
        history: list[VerificationResult] = []
        abandon_reason = ""
        while ticket.rounds_used < ticket.max_rounds:
            round_no = ticket.rounds_used + 1
            try:
                proposal = self._generator.propose(request, round_no, history)
            except Exception as exc:  # noqa: BLE001 - 提案源故障=放弃，不外溢
                abandon_reason = (
                    f"generator error round={round_no}: "
                    f"{type(exc).__name__}: {redact_text(str(exc), max_chars=200)}"
                )
                break
            if proposal is None:
                abandon_reason = f"proposals_exhausted round={round_no}"
                break
            rel_target = self._validate_target(
                proposal.target_file or request.target_file
            )
            if rel_target != ticket.target_file:
                abandon_reason = (
                    f"proposal_target_mismatch round={round_no}: "
                    f"{rel_target} != {ticket.target_file}"
                )
                break
            target_abs = self._workspace_root / rel_target
            original = target_abs.read_text(encoding="utf-8")
            diff_text = build_unified_diff(
                original, proposal.new_content, rel_target
            )
            if not diff_text.strip():
                history.append(
                    VerificationResult(
                        passed=False, detail="no-op proposal (空 diff)", round_no=round_no
                    )
                )
                ticket.rounds_used = round_no
                self._audit(
                    "repair_round_completed",
                    ticket_id,
                    f"round={round_no} passed=False detail=no-op 空补丁",
                )
                continue
            self._write_ticket_file(
                ticket_id, f"round-{round_no}.patch", redact_text(diff_text)
            )
            try:
                result = self._verifier.verify(ticket, diff_text, round_no)
            except Exception as exc:  # noqa: BLE001 - 验证器炸=该轮未过
                result = VerificationResult(
                    passed=False,
                    detail=(
                        f"verifier error: {type(exc).__name__}: "
                        f"{redact_text(str(exc), max_chars=200)}"
                    ),
                    round_no=round_no,
                )
            history.append(result)
            ticket.rounds_used = round_no
            self._write_ticket_file(
                ticket_id,
                f"round-{round_no}.verify.json",
                json.dumps(
                    {
                        "round": round_no,
                        "passed": result.passed,
                        "detail": redact_text(result.detail, max_chars=1200),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            self._audit(
                "repair_round_completed",
                ticket_id,
                f"round={round_no} passed={result.passed}",
            )
            if result.passed:
                ticket.status = RepairStatus.VERIFIED_PENDING
                self._finish_ticket(ticket)
                return ticket
        if ticket.status == RepairStatus.OPEN:
            if not abandon_reason:
                abandon_reason = f"budget_exhausted rounds={ticket.rounds_used}"
            ticket.status = RepairStatus.ABANDONED
            ticket.abandon_reason = abandon_reason
            ticket.red_retained = True
            self._write_abandon_artifacts(ticket, history, request)
        self._finish_ticket(ticket)
        return ticket

    def apply_to_target(self, ticket_id: str, **_kwargs: Any) -> NoReturn:
        """越权面：自动写入目标文件被合同禁止——一律拒绝并审计。"""
        self._audit(
            "repair_unauthorized_rejected",
            ticket_id,
            "apply_to_target 被拒绝：待审补丁不允许自动写入目标文件",
        )
        raise UnauthorizedRepairOperation(
            "V21-REPAIR-001: apply_to_target 被拒绝——补丁只能以待审件形式"
            "交付人工审核，任何自动写入目标文件的操作均被禁止"
        )

    def deploy_patch(self, ticket_id: str, **_kwargs: Any) -> NoReturn:
        """越权面：部署被合同禁止——同 ``apply_to_target`` 一律拒绝并审计。"""
        self._audit(
            "repair_unauthorized_rejected",
            ticket_id,
            "deploy_patch 被拒绝：待审补丁不允许自动部署",
        )
        raise UnauthorizedRepairOperation(
            "V21-REPAIR-001: deploy_patch 被拒绝——自动部署不在本服务授权范围内"
        )

    def request_application(self, ticket_id: str) -> dict[str, Any]:
        """唯一合法出口：只读列出待审件路径与人工应用指引（零写入）。"""
        ticket = self.load_ticket(ticket_id)
        ticket_dir = self._pending_root / ticket_id
        artifacts = sorted(
            p.name for p in ticket_dir.iterdir() if p.is_file()
        ) if ticket_dir.is_dir() else []
        return {
            "ticket_id": ticket.ticket_id,
            "status": ticket.status,
            "target_file": ticket.target_file,
            "instruction": (
                "人工审核 round-N.patch 后手动应用；本服务不提供任何自动写入"
            ),
            "pending_artifacts": artifacts,
            "pending_dir": str(ticket_dir),
        }

    def load_ticket(self, ticket_id: str) -> RepairTicket:
        manifest_path = self._pending_root / ticket_id / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"ticket 不存在: {ticket_id}")
        return self._read_ticket(manifest_path)

    def list_tickets(self) -> list[str]:
        if not self._pending_root.is_dir():
            return []
        return sorted(
            p.name
            for p in self._pending_root.iterdir()
            if p.is_dir() and (p / "manifest.json").exists()
        )

    # -- 内部 ----------------------------------------------------------------

    def _validate_target(self, target: str) -> str:
        """目标路径校验：仓库内相对路径，禁越界/禁触名单/pending 自身。"""
        value = (target or "").strip().replace("\\", "/")
        if not value:
            raise TargetRejectedError("目标路径为空")
        if re.match(r"^[A-Za-z]:", value) or value.startswith("//"):
            raise TargetRejectedError(f"拒绝绝对路径: {redact_text(value, max_chars=80)}")
        parts = [p for p in value.split("/") if p not in ("", ".")]
        if not parts or any(p == ".." for p in parts):
            raise TargetRejectedError("拒绝越界路径（.. / 空段）")
        lowered = {p.lower() for p in parts}
        if lowered & FORBIDDEN_TARGET_PARTS:
            raise TargetRejectedError(f"禁触目标: {sorted(lowered & FORBIDDEN_TARGET_PARTS)}")
        rel = Path(*parts)
        workspace = self._workspace_root.resolve()
        resolved = (workspace / rel).resolve()
        if workspace != resolved and workspace not in resolved.parents:
            raise TargetRejectedError("目标解析后逃出工作区")
        pending_resolved = self._pending_root.resolve()
        if pending_resolved == resolved or pending_resolved in resolved.parents:
            raise TargetRejectedError("目标是待审区自身")
        return rel.as_posix()

    @staticmethod
    def _ticket_key(request: RepairRequest) -> str:
        normalized = " ".join((request.error_summary or "").split())
        raw = f"{request.test_id}\x00{request.target_file}\x00{normalized}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _read_ticket(self, manifest_path: Path) -> RepairTicket:
        return RepairTicket.from_manifest(
            json.loads(manifest_path.read_text(encoding="utf-8"))
        )

    def _write_manifest(self, ticket: RepairTicket) -> None:
        ticket.updated_at = float(self._clock())
        self._write_ticket_file(
            ticket.ticket_id, "manifest.json",
            json.dumps(ticket.to_manifest(), ensure_ascii=False, indent=2),
        )

    def _finish_ticket(self, ticket: RepairTicket) -> None:
        self._write_manifest(ticket)
        self._audit(
            "repair_finished",
            ticket.ticket_id,
            f"status={ticket.status} rounds={ticket.rounds_used} "
            f"red_retained={ticket.red_retained}",
        )

    def _write_ticket_file(self, ticket_id: str, name: str, content: str) -> None:
        """待审区原子写入（tmp + os.replace；只落 pending 根内）。"""
        ticket_dir = self._pending_root / ticket_id
        ticket_dir.mkdir(parents=True, exist_ok=True)
        final = ticket_dir / name
        fd, tmp_name = tempfile.mkstemp(
            dir=ticket_dir, prefix=f".{name}.", suffix=".tmp"
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                fh.write(content)
            os.replace(tmp_path, final)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    def _write_abandon_artifacts(
        self,
        ticket: RepairTicket,
        history: list[VerificationResult],
        request: RepairRequest,
    ) -> None:
        """放弃产物：诊断报告 + RED 保留声明（失败测试绝不删改）。"""
        lines = [
            "# 修复诊断报告（V21-REPAIR-001）",
            "",
            f"- test: {ticket.test_id}",
            f"- target: {ticket.target_file}",
            f"- error_class: {ticket.error_class}",
            f"- rounds_used: {ticket.rounds_used}/{ticket.max_rounds}",
            f"- abandon_reason: {ticket.abandon_reason}",
            "",
            "## 错误摘要（脱敏）",
            "",
            redact_text(request.error_summary, max_chars=DEFAULT_MAX_TEXT_CHARS),
            "",
            "## 各轮验证（脱敏）",
            "",
        ]
        for result in history:
            lines.append(
                f"- round {result.round_no}: passed={result.passed} "
                f"detail={redact_text(result.detail, max_chars=DEFAULT_MAX_TEXT_CHARS)}"
            )
        lines += [
            "",
            "## 结论",
            "",
            "两轮预算内未验证通过，自动修复放弃；失败测试（RED）必须保留，",
            "等待人工诊断。本服务未对目标文件做任何写入。",
            "",
        ]
        self._write_ticket_file(ticket.ticket_id, "diagnostic.md", "\n".join(lines))
        self._write_ticket_file(
            ticket.ticket_id,
            "RED-RETAINED.md",
            "\n".join(
                [
                    "# RED 保留声明（V21-REPAIR-001）",
                    "",
                    f"- 失败测试坐标: {ticket.test_id}",
                    f"- 状态: {ticket.status}",
                    "- 纪律: 该失败测试必须原样保留（RED 不删、不改、不 skip），",
                    "- 本服务未触碰它；诊断见 diagnostic.md，补丁见 round-N.patch。",
                    "",
                ]
            ),
        )
        self._audit(
            "repair_abandoned",
            ticket.ticket_id,
            f"reason={ticket.abandon_reason} red_retained=True",
        )

    def _audit(self, kind: str, ticket_id: str, detail: str) -> None:
        event = {
            "kind": kind,
            "ts": float(self._clock()),
            "ticket": ticket_id,
            "detail": redact_text(detail, max_chars=DEFAULT_MAX_TEXT_CHARS),
        }
        for sink in self._audit_sinks:
            try:
                sink.emit(event)
            except Exception:
                logger.exception("repair: audit sink emit failed (fail-open)")


def _sanitize_dir_component(test_id: str) -> str:
    """test_id → 安全目录名：仅 [A-Za-z0-9._-]，去越界/分隔符/首尾点，≤48。"""
    slug = _SANITIZED_SLUG_RE.sub("_", test_id or "")
    slug = _MULTIPLE_SEPARATORS_RE.sub("_", slug).strip("._-") or "repair"
    return slug[:48]
