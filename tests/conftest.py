"""Session-level guards for the whole test tree.

1. Autosync hook (top section): with ``BOT_AUTOSYNC=1`` (set by
   ``scripts/dev.ps1 -Task test``), regenerate the machine-owned files at
   session start so drift never reaches the resident gates; a summary is
   printed when the session finishes.  When the hash manifest is re-recorded
   the affected deliverables are named in a warning -- auto-fix stays silent
   for humans, but the change itself always leaves a trace.
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

import json
import os
import subprocess
import sys
import time
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# 源码树零缓存守卫（S144，2026-09-22）
# ---------------------------------------------------------------------------
# 复现结论：测试进程只要以**不带** PYTHONDONTWRITEBYTECODE 的方式启动（例如
# `pytest tests/test_taxonomy_spec_gates.py` 裸跑，而非经 dev.ps1 -Task test），
# pytest 收集期 import scripts/*.py 门模块会当场在 scripts/__pycache__ 落 6~7 枚
# .pyc，被 runtime-layout 门记成"源码树有字节码"。dev.ps1 路线靠启动期同时设
# PYTHONDONTWRITEBYTECODE=1 + PYTHONPYCACHEPREFIX 兜住（scripts/dev.ps1:59-62）；
# 但"绕开 dev.ps1 的裸跑"是 AGENTS 规则 6 明确允许、且历史上被并行席反复踩到的
# 入口（S141 观察到的"亚分钟写-清四拍"正是某席裸跑写、别席清）。
# 修法＝在 conftest 这个"pytest 最早加载、且早于任何测试模块 import"的位置，把
# runtime_layout_smoke（S139 实证）同一套三通道设好，让测试树自护而非依赖调用方：
#   - sys.dont_write_bytecode：本进程（pytest）后续 import 不落 .pyc 的唯一有效闸
#     ——中途改 os.environ 对已启动解释器无效，只有这个直接生效；
#   - os.environ.setdefault：覆盖所有按环境继承起来的子进程（autosync 三件等）；
#   - PYTHONPYCACHEPREFIX：连 py_compile/compileall 这类无视 dont_write_bytecode 的
#     写也一并重定向到 Runtime，绝不进 AI 工作区。
# 三项均为"设缺省不覆盖"：dev.ps1 路线上它们本已就位⇒该守卫零行为变化；
# 只动 hygiene，绝不触碰任何判据 / 阈值 / 断言 / 门本体。
_RUNTIME_ROOT = REPO_ROOT.parent / "ChatBot_Runtime"
_PYCACHE_PREFIX = str(_RUNTIME_ROOT / "pycache")
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
os.environ.setdefault("PYTHONPYCACHEPREFIX", _PYCACHE_PREFIX)
sys.dont_write_bytecode = True

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

_HASH_MANIFEST = "tests/render_hashes.json"

_autosync_changed: list[str] = []
_hash_baseline_changed: list[str] = []


# V2.1 §13（2026-09-17 A3）：autosync 启用判定抽成纯函数，供 ``run_autosync``
# 与回归测试（tests/test_autosync_gate.py）共用；``scripts/dev.ps1::Invoke-Test``
# 持同一语义（仅当调用方未显式设置 BOT_AUTOSYNC 时才默认 1，显式值原样透传）。
# 显式 0/false/no/off（大小写不敏感）= 禁自动重录——V2.1 验收模式下生成物
# 基线必须逐字节不变，自动 --write 不得把真实回归「洗绿」。
_AUTOSYNC_ENABLE_VALUE = "1"


def is_autosync_enabled(raw: str | None) -> bool:
    """判定 autosync 自动 ``--write`` 联动是否启用。

    仅当值为 ``"1"``（dev.ps1 未显式设置时的默认）时启用；显式
    ``0/false/no/off``（大小写不敏感）及其他任何值一律禁用；未设置
    （裸 pytest/CI）禁用，整个钩子零开销跳过。与历史 ``!= "1"`` 判定
    字节级兼容：任何取值组合下的启用/禁用结论不变。
    """
    return raw == _AUTOSYNC_ENABLE_VALUE


def _manifest_keys(raw: bytes | None) -> dict[str, str]:
    """把哈希清单字节解析成 {交付物: sha256}；解析失败返回空 dict。"""
    if not raw:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def run_autosync(root: Path | None = None) -> list[str]:
    """静默重生成机器管文件；返回被实际改动的文件（仓库相对路径）列表。

    哈希清单（``tests/render_hashes.json``）被重录时，额外记录**哪些交付物**
    的基线变了并发出 warning——自动修正保留「人无感」，但改动必须留痕，
    否则一次非有意的模板改动会被静默吸收成新的「正确基线」。
    """
    if not is_autosync_enabled(os.environ.get("BOT_AUTOSYNC")):
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
                # S144：会话级唯一的树内子进程出口显式带不写字节码的环境，
                # 不再依赖调用方 ambient 继承（tts_offline_selfcheck 同款配方）。
                env={
                    **os.environ,
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONPYCACHEPREFIX": _PYCACHE_PREFIX,
                },
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
            if output == _HASH_MANIFEST:
                before_keys = _manifest_keys(before)
                after_keys = _manifest_keys(after)
                for name in sorted(set(before_keys) | set(after_keys)):
                    if before_keys.get(name) != after_keys.get(name):
                        _hash_baseline_changed.append(name)
    if _hash_baseline_changed:
        warnings.warn(
            "[autosync] 哈希基线被自动重录（非有意改动请复核）："
            + ", ".join(_hash_baseline_changed),
            stacklevel=2,
        )
    return changed


@pytest.fixture(autouse=True)
def _isolate_render_phase2_env(monkeypatch):
    """渲染 Phase 2 解锁键属机器级 .env 配置（A43 预跑 5 红根因）：
    契约测试断言「缺省=字节级现状」，套件内一律隔离；单测自设用 monkeypatch.setenv 在本 fixture 之后生效。"""
    monkeypatch.delenv("BOT_RENDER_MAX_CONCURRENCY", raising=False)
    monkeypatch.delenv("BOT_RENDER_WAIT_BUDGET_MS", raising=False)


@pytest.fixture(scope="module", autouse=True)
def _quarantine_render_pool_between_modules():
    """模块边界收口错误卡渲染池 + cap-proto 执行器（2026-09-18 REAPER 清障；
    CAPEXEC 收口席按其残余登记补 capability_protocols 一口）。

    ``error_report._RENDER_POOL`` 与 ``capability_protocols._EXECUTOR``
    （``cap-proto_0..3``，tests/test_v21_s10_protocols.py 经 invoke 拉起）都是
    模块级常驻单例（非 daemon worker、仅 atexit 收口）：任一测试模块拉起后，
    worker 线程会带进同会话后续任意模块，使线程面敏感用例（如
    test_v21r2_lifecycle_r2 的停机 reaper 扫描）随**用例执行顺序**飘——
    单独跑绿、组合/全量跑红。本 fixture 在每个测试模块前后各收口一次：
    两个 ``_shutdown_*`` 均幂等（单例为 None 时仅一次锁+判空，零开销）、
    ``wait=True`` 且不取消排队任务，与生产 atexit 同语义；shutdown 后池懒
    重建，后续用例零感知。语义回归锁：tests/test_render_pool_hygiene.py
    （组合复现命令见其文件头）。
    """
    try:
        from plugins.bot_unified_runtime.domains.ops.monitor import error_report
    except ModuleNotFoundError:  # autosync 骨架会话（tests/_autosync_fixture.py 最小仓）不含 domains 依赖闭包：模块缺位则池亦无从拉起，跳过即语义等价；真树模块缺位由 test_render_pool_hygiene 哨兵兜底
        error_report = None
    try:
        from plugins.bot_unified_runtime.runtime import capability_protocols
    except ModuleNotFoundError:  # 同上（骨架仓不含 runtime/capability_protocols.py）
        capability_protocols = None

    if error_report is not None:
        error_report._shutdown_render_pool()  # 挡前序模块残留
    if capability_protocols is not None:
        capability_protocols._shutdown_capability_executor()
    yield
    if error_report is not None:
        error_report._shutdown_render_pool()  # 不让本模块残留漏给后序
    if capability_protocols is not None:
        capability_protocols._shutdown_capability_executor()


@pytest.fixture(scope="session", autouse=True)
def _autosync_session_gate():
    _autosync_changed.extend(run_autosync())
    yield


def pytest_terminal_summary(terminalreporter) -> None:
    if _hash_baseline_changed:
        terminalreporter.write_line(
            "[autosync] 哈希基线已自动重录（非有意改动请复核）："
            + ", ".join(_hash_baseline_changed)
        )
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
