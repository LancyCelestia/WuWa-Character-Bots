"""Session-level guards for the whole test tree.

1. Autosync hook (top section): with ``BOT_AUTOSYNC=1`` (set by
   ``scripts/dev.ps1 -Task test``), silently regenerate the machine-owned
   files at session start so drift never reaches the resident gates; a
   one-line summary is printed when the session finishes.
2. Source-tree ``data/`` guard: fail any test that creates new files under
   the source-tree ``data/``.

Repo rules (AGENTS.md #2/#6): the source tree must never contain ``data/`` --
runtime paths resolve through ``scripts/runtime_paths.py`` into
``ChatBot_Runtime/`` and tests must write to ``tmp_path``.  Before and after
each of a test's setup/call/teardown phases we snapshot the repo ``data/``
directory; any file appearing mid-phase fails exactly that phase with the
list of offending paths.  Diagnostics are also appended to
``%TEMP%/g1-data-writes.log`` (outside the source tree).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# BOT_AUTOSYNC 常驻自动同步钩子（session 级，人完全无感）
# ---------------------------------------------------------------------------
# 仅当 BOT_AUTOSYNC=1（dev.ps1 -Task test 设置）时启用：session 开始时依次
# 静默重跑三个机器管文件的 --write（command-catalog / auto-facts /
# render_hashes），谁漂了就修谁，session 结束打印一行改动汇总。三个脚本
# 的 --write 输出字节确定（无漂移时前后字节一致＝不算改动），写后即与
# --check 一致（幂等）。子进程失败只 warning 不阻断测试——同步失败由既有
# 常驻门（tests/test_cross_validation_gates.py 的 --check）兜底报红。
# 未设 BOT_AUTOSYNC（CI/生产/裸 pytest）时整个钩子零开销跳过，绝不写盘。

_AUTOSYNC_STEPS: tuple[tuple[str, str], ...] = (
    ("scripts/command_catalog.py", "docs/command-catalog.md"),
    ("scripts/doc_sync.py", "docs/auto-facts.md"),
    ("tests/verify_hashes.py", "tests/render_hashes.json"),
)

_autosync_changed: list[str] = []


def run_autosync(root: Path | None = None) -> list[str]:
    """静默重生成机器管文件；返回被实际改动的文件（仓库相对路径）列表。"""
    if os.environ.get("BOT_AUTOSYNC") != "1":
        return []
    root = REPO_ROOT if root is None else root
    changed: list[str] = []
    for script, output in _AUTOSYNC_STEPS:
        target = root / output
        try:
            before = target.read_bytes() if target.is_file() else None
            proc = subprocess.run(
                [sys.executable, str(root / script), "--write"],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            warnings.warn(
                f"[autosync] {script} --write 未跑成（{exc}）；"
                "漂移由常驻门 --check 兜底报红",
                stacklevel=2,
            )
            continue
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()
            warnings.warn(
                f"[autosync] {script} --write 失败（exit {proc.returncode}）"
                f"{': ' + tail[-1] if tail else ''}；漂移由常驻门 --check 兜底报红",
                stacklevel=2,
            )
            continue
        try:
            after = target.read_bytes() if target.is_file() else None
        except OSError as exc:
            warnings.warn(f"[autosync] {output} 回读失败（{exc}）", stacklevel=2)
            continue
        if after != before:
            changed.append(output)
    return changed


@pytest.fixture(scope="session", autouse=True)
def _autosync_session_gate():
    _autosync_changed.extend(run_autosync())
    yield


def pytest_terminal_summary(terminalreporter) -> None:
    if _autosync_changed:
        terminalreporter.write_line(
            "[autosync] 自动同步：" + ", ".join(_autosync_changed)
        )


# ---------------------------------------------------------------------------
# 源码树 data/ 写入拦截守卫（G1，根治台账 #1）
# ---------------------------------------------------------------------------

_REPO_DATA = REPO_ROOT / "data"
_LOG = Path(os.environ.get("TEMP", ".")) / "g1-data-writes.log"


def _snapshot() -> set[str]:
    if not _REPO_DATA.is_dir():
        return set()
    return {str(p.relative_to(_REPO_DATA)) for p in _REPO_DATA.rglob("*")}


def _log(node: str, phase: str, fresh: list[str]) -> None:
    stamp = time.strftime("%H:%M:%S")
    try:
        with open(_LOG, "a", encoding="utf-8") as fh:
            fh.writelines(f"{stamp}\t{node}\t{phase}\tNEW\t{name}\n" for name in fresh)
    except OSError:  # pragma: no cover - diagnostics must never break the run
        pass


def _enforce(node: str, phase: str, before: set[str], excinfo: object) -> None:
    """Fail the phase when new files appeared under the source-tree data/.

    ``excinfo`` is the pluggy hookwrapper result's ``excinfo``: non-None means
    the phase already failed for its own reason and we must not mask it.
    """
    fresh = sorted(_snapshot() - before)
    if not fresh:
        return
    _log(node, phase, fresh)
    if excinfo is not None:
        return
    listing = "\n".join(f"  data/{name}" for name in fresh)
    raise AssertionError(
        f"{node} wrote new file(s) into the source tree data/ during {phase}:\n"
        f"{listing}\n"
        "Write to tmp_path (or resolve via scripts/runtime_paths.py) instead; "
        "see AGENTS.md rules 2/6."
    )


def _make_phase_guard(phase: str):
    @pytest.hookimpl(hookwrapper=True)
    def impl(item: pytest.Item):
        before = _snapshot()
        outcome = yield
        _enforce(item.nodeid, phase, before, outcome.excinfo)

    return impl


pytest_runtest_setup = _make_phase_guard("setup")
pytest_runtest_call = _make_phase_guard("call")
pytest_runtest_teardown = _make_phase_guard("teardown")
