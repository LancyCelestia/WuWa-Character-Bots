"""tts_offline_selfcheck — TTS 真机验收前置一键自检编排器（纯编排，零业务断言）.

定位：把 TTS 真机验收窗（acceptance-manual §6.6.11，30 项版）前的三道既有
离线体检串成一条命令；本工具**零业务断言**——判定全部透传各子工具，FAIL
只做汇总与处置指引，不重复判定、不吞状态。SKIP 放行（沿 pre_restart_check
惯例：SKIP 不假红）。

顺序（依赖串行，无并行必要——三步都在同一棵树上）：
  1. pre_restart_check   重启前置 10 项（含第 10 项 tts_voice 音色守望，
                         T60 1b2860c）——`--json` 逐项取 PASS/SKIP/FAIL；
  2. verify_chatbot_env  .env 配置面快查（T87 7e2fe36：判据走生产 Config
                         真身）——`--json` 逐 finding 取状态；
  3. 语料门              tests/test_tts_corpus_gate.py（存在才跑；pytest
                         -q -p no:cacheprovider，basetemp 落源码树外
                         Runtime/cache/tts_selfcheck，环境变量按仓库配方
                         PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0）。

退出码：任一步 FAIL → 1（透传）；全 PASS/SKIP → 0。
--dry-run：各子命令桩化（不真跑任何子进程），只演练编排/汇总/退出码路径。

用法：
  venv python scripts/tts_offline_selfcheck.py                 # 人读表
  venv python scripts/tts_offline_selfcheck.py --json          # 结构化输出
  venv python scripts/tts_offline_selfcheck.py --dry-run       # 桩化演练
  venv python scripts/tts_offline_selfcheck.py --project-root <path>
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

PASS = "PASS"
SKIP = "SKIP"
FAIL = "FAIL"

CORPUS_GATE_REL = "tests/test_tts_corpus_gate.py"
BASETEMP_REL = Path("ChatBot_Runtime") / "cache" / "tts_selfcheck"

# 仓库统一离线配方（pytest 子进程环境；os.environ 既有值被配方覆盖）
_PYTEST_ENV_OVERRIDE = {
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONUTF8": "1",
    "BOT_AUTOSYNC": "0",
}

_TIMEOUT_PRE_CHECK = 900  # pre_restart_check 内含 ruff（其自身预算 600s）
_TIMEOUT_VERIFY_ENV = 300
_TIMEOUT_PYTEST = 900

# 子命令执行面类型：runner(args, cwd, timeout) -> (exit_code, stdout, stderr)
Runner = Callable[[list[str], Path, int], tuple[int, str, str]]


@dataclass(frozen=True)
class StepResult:
    """单步结论：PASS/SKIP/FAIL + 一句话 + FAIL 时的处置指引."""

    id: str
    name: str
    status: str
    message: str
    fix_hint: str = ""


@dataclass(frozen=True)
class SelfcheckReport:
    """一次自检编排的汇总（步骤序列+透传退出码）."""

    project_root: str
    steps: tuple[StepResult, ...]
    exit_code: int

    def as_dict(self) -> dict[str, object]:
        return {
            "project_root": self.project_root,
            "exit_code": self.exit_code,
            "steps": [asdict(s) for s in self.steps],
        }


# ---------------------------------------------------------------------------
# 可注入的副作用封装（测试 monkeypatch 点：_run_cmd / _run_verify）
# ---------------------------------------------------------------------------

def _run_cmd(args: list[str], cwd: Path, timeout: int) -> tuple[int, str, str]:
    """通用子命令执行（真身；测试以同名单参函数替换）."""
    proc = subprocess.run(
        args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,  # 退出码交给调用方判定（编排本就要区分红绿）
    )
    return proc.returncode, proc.stdout, proc.stderr


def _run_verify(args: list[str], cwd: Path, timeout: int) -> tuple[int, str, str]:
    """verify_chatbot_env 专用执行点（独立 monkeypatch 缝，语义同 _run_cmd）."""
    return _run_cmd(args, cwd, timeout)


# ---------------------------------------------------------------------------
# 三步编排（零业务断言：状态全部透传子工具）
# ---------------------------------------------------------------------------

def _parse_findings_json(stdout: str) -> list[dict[str, object]] | None:
    """取子工具 --json 输出的 findings/results 列表；解析失败返回 None."""
    try:
        payload = json.loads(stdout.strip())
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    items = payload.get("results") or payload.get("findings")
    if not isinstance(items, list):
        return None
    converted: list[dict[str, object]] = []
    for item in items:
        if isinstance(item, dict):
            converted.append({str(k): v for k, v in item.items()})
    return converted


def _step_from_findings(
    step_id: str, step_name: str, items: list[dict[str, object]], doc_hint: str
) -> StepResult:
    """把子工具逐项结果折叠成一个步骤结论（FAIL 汇总 id 与处置指引）."""
    fails = [i for i in items if i.get("status") == FAIL]
    if fails:
        ids = ", ".join(str(i.get("id", "?")) for i in fails)
        hints = "; ".join(str(i.get("fix_hint", "")).strip() for i in fails if i.get("fix_hint"))
        first_fail = str(fails[0].get("message", ""))[:160]
        return StepResult(
            step_id,
            step_name,
            FAIL,
            f"FAIL x{len(fails)}（{ids}）：{first_fail}",
            hints or doc_hint,
        )
    skips = [str(i.get("id", "?")) for i in items if i.get("status") == SKIP]
    n_pass = len(items) - len(skips)
    message = f"PASS {n_pass} / SKIP {len(skips)} / FAIL 0"
    if skips:
        message += f"（SKIP：{', '.join(skips)}）"
    return StepResult(step_id, step_name, PASS, message)


def _step_pre_restart_check(project_root: Path) -> StepResult:
    rc, out, err = _run_cmd(
        [sys.executable, "scripts/pre_restart_check.py", "--json"],
        project_root,
        _TIMEOUT_PRE_CHECK,
    )
    items = _parse_findings_json(out)
    if items is None:
        detail = (err.strip() or out.strip() or f"exit {rc}").splitlines()[-1][:160]
        return StepResult(
            "pre_restart_check",
            "重启前置 10 项预检",
            FAIL,
            f"输出不可解析（{detail}）",
            "单独复跑 python scripts/pre_restart_check.py 看人读表定位；"
            "十项口径见该文件 docstring。",
        )
    step = _step_from_findings(
        "pre_restart_check", "重启前置 10 项预检", items, "逐项按 pre_restart_check 输出指引处置"
    )
    if step.status == PASS and rc != 0:
        return StepResult(step.id, step.name, FAIL, f"输出无 FAIL 但 exit={rc}", step.fix_hint)
    return step


def _step_verify_env(project_root: Path) -> StepResult:
    rc, out, err = _run_verify(
        [sys.executable, "scripts/verify_chatbot_env.py", "--json"],
        project_root,
        _TIMEOUT_VERIFY_ENV,
    )
    items = _parse_findings_json(out)
    if items is None:
        detail = (err.strip() or out.strip() or f"exit {rc}").splitlines()[-1][:160]
        return StepResult(
            "verify_env",
            ".env 配置面快查（T87）",
            FAIL,
            f"输出不可解析（{detail}）",
            "单独复跑 python scripts/verify_chatbot_env.py 看人读表定位；"
            "分工口径见该文件 docstring（本工具守 bot 侧配置面非重启门）。",
        )
    step = _step_from_findings(
        "verify_env", ".env 配置面快查（T87）", items, "逐项按 verify_chatbot_env 输出处置"
    )
    if step.status == PASS and rc != 0:
        return StepResult(step.id, step.name, FAIL, f"输出无 FAIL 但 exit={rc}", step.fix_hint)
    return step


def _step_corpus_gate(project_root: Path) -> StepResult:
    gate_path = project_root / CORPUS_GATE_REL
    if not gate_path.is_file():
        return StepResult(
            "corpus_gate",
            "语料门（参考音频语料一致性）",
            SKIP,
            f"{CORPUS_GATE_REL} 不存在——语料门未在树，跳过",
        )
    basetemp = project_root.parent / BASETEMP_REL
    args = [
        sys.executable,
        "-m",
        "pytest",
        CORPUS_GATE_REL,
        "-q",
        "-p",
        "no:cacheprovider",
        f"--basetemp={basetemp}",
    ]
    # 离线配方经 os.environ 下发给 pytest 子进程（保持 runner 三参签名不变）
    saved = {key: os.environ.get(key) for key in _PYTEST_ENV_OVERRIDE}
    os.environ.update(_PYTEST_ENV_OVERRIDE)
    try:
        rc, out, err = _run_cmd(args, project_root, _TIMEOUT_PYTEST)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    if rc == 0:
        tail = out.strip().splitlines()[-1] if out.strip() else "exit 0"
        return StepResult("corpus_gate", "语料门（参考音频语料一致性）", PASS, tail)
    detail = (out.strip() or err.strip() or f"exit {rc}").splitlines()[-1][:160]
    return StepResult(
        "corpus_gate",
        "语料门（参考音频语料一致性）",
        FAIL,
        detail,
        "复跑 pytest tests/test_tts_corpus_gate.py -q 看失败用例定位（语料权威="
        ".env 语料段 vs refs 校对基线；TSV 修复后门自动转绿）。",
    )


def run_all(project_root: Path, dry_run: bool = False) -> SelfcheckReport:
    """按序跑三步并汇总退出码（纯编排：判定透传，不补业务断言）."""
    if dry_run:
        steps = tuple(
            StepResult(
                sid,
                sname,
                PASS,
                "dry-run：子命令桩化，未执行",
            )
            for sid, sname in (
                ("pre_restart_check", "重启前置 10 项预检"),
                ("verify_env", ".env 配置面快查（T87）"),
                ("corpus_gate", "语料门（参考音频语料一致性）"),
            )
        )
        return SelfcheckReport(str(project_root), steps, 0)
    steps = (
        _step_pre_restart_check(project_root),
        _step_verify_env(project_root),
        _step_corpus_gate(project_root),
    )
    exit_code = 1 if any(s.status == FAIL for s in steps) else 0
    return SelfcheckReport(str(project_root), steps, exit_code)


def render_table(report: SelfcheckReport) -> str:
    id_w = max(len(s.id) for s in report.steps)
    lines = [f"{'步骤':<{id_w}}  说明  状态  详情", "-" * 72]
    for s in report.steps:
        lines.append(f"{s.id:<{id_w}}  {s.name}  {s.status}  {s.message}")
    fails = [s for s in report.steps if s.status == FAIL]
    if fails:
        lines.append("")
        lines.append("FAIL 处置指引：")
        for s in fails:
            lines.append(f"  [{s.id}] {s.fix_hint}")
    lines.append("")
    verdict = (
        "前置自检通过——可进 §6.6.11 验收窗（引擎/重启动作仍须用户本人执行）"
        if report.exit_code == 0
        else "存在 FAIL 步骤——先按指引处置再进验收窗"
    )
    lines.append(f"汇总: exit={report.exit_code} → {verdict}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="TTS 真机验收前置一键自检（三步编排，纯透传零业务断言）"
    )
    parser.add_argument("--json", action="store_true", help="结构化 JSON 输出")
    parser.add_argument("--dry-run", action="store_true", help="子命令桩化演练（不真跑）")
    parser.add_argument("--project-root", default=None, help="覆盖项目根（默认仓库根）")
    args = parser.parse_args(argv)

    try:  # Windows 控制台中文输出防 mojibake
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

    project_root = Path(args.project_root).resolve() if args.project_root else PROJECT_ROOT
    report = run_all(project_root, dry_run=args.dry_run)

    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(render_table(report))
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
