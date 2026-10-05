"""第 446 席补的四格：runtime-layout 门对「绕过 dev.ps1 的裸跑」倒进源码树的字节码仍然全盲。

门本体（``scripts/runtime_layout_smoke.py``）2026-10-04 之前的扫面只有
``PROJECT_ROOT.rglob("*")`` 一型，判据是「名字等于 ``__pycache__`` / ``.mypy_cache__``
之类、或以 ``.pyc``/``.pyo`` 结尾」，看着像全覆盖，实际漏掉四格**同源**的形态：

  ① ``tests/**/__pycache__/``——任何一次没带 ``PYTHONDONTWRITEBYTECODE=1`` 的 pytest
     都会在每个测试包的目录旁倒一批 ``.cpython-312.pyc``。当日实锤 3 处
     （``tests/plugins/bot_unified_runtime/__pycache__/``、
     ``tests/plugins/bot_unified_runtime/domains/subscribe/``、
     ``tests/plugins/bot_unified_runtime/domains/chat_reply/runtime/``）；
  ② ``scripts/**/__pycache__/``——直接 ``python scripts/xxx.py`` 或
     ``importlib.util.spec_from_file_location(...)``（门自己的件、以及第 14 项
     ``kb_domain_anchor`` 的直载腿都走这条路）都会倒。当日实锤 2 处；
  ③ 仓库根散落的 ``*.pyc``——当日实锤 5 枚（``bot.cpython-312.pyc``、
     ``plugin_test.cpython-312.pyc``、``plugin_test_73240__…pyc`` 等），全在
     ``.gitignore`` 的 ``*.pyc`` 覆盖下 ⇒ ``git status`` 永远看不见；
  ④ 字节码**贴着源文件同目录**落盘（源码旁的 sidecar）：``PYTHONDONTWRITEBYTECODE``
     没设、而 ``PYTHONPYCACHEPREFIX`` 没给时的形状就是它——字节码就写在 ``.py`` 旁边，
     既不在 ``__pycache__`` 里也没有子目录，旧扫面一格都抓不到。

为什么这四格值得单独立锁（而不是「旧门照绿、就当没事」）：``.gitignore`` 里写了
``__pycache__/``/``*.pyc`` ⇒ 这些残留**永远不会出现在 git status**，于是「工作树干净」
这个直觉信号对它们是瞎的；而「源码树零缓存」是 AGENTS.md 规则 6 的硬约束。当日
19:25 与 20:04 两波倒灌的**凶手**已由 mtime 取证钉死（19:25 那枚
``scripts/__pycache__/pre_restart_check.cpython-312.pyc`` 与某席一条漏带卫生 env 的
``python -c`` 逐秒对齐），门只是当时没牙。

判据形状只锁不松：新增的都是**扫描面/判据覆盖**，不新增豁免、不改类别名。
全部离线：只在 ``tmp_path``（仓外）造假树，注毒腿不落真实工作区一笔。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

# 须在 sys.path 补丁之后（门本体住 scripts/）；本仓规则集未启用 E402，故不挂 noqa
import runtime_layout_smoke as gate

BYTECODE = gate.RESIDUE_PYTHON_BYTECODE

#: 当日（2026-10-04）真实工作树里被取证到的四格形态，逐条当成「门必须看得见」的样例。
REAL_SAMPLES: tuple[str, ...] = (
    "tests/plugins/bot_unified_runtime/__pycache__/",
    "scripts/__pycache__/pre_restart_check.cpython-312.pyc",
    "bot.cpython-312.pyc",
)


def _write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _clean_tree(root: Path) -> Path:
    """合法源码树骨架：任何字节码形态都不该在它上面响（反向不误伤的基线）。"""
    _write(root / "bot.py", "print('ok')\n")
    _write(root / "scripts/dev.ps1", "# runner\n")
    _write(root / "scripts/runtime_layout_smoke.py", "def main() -> int:\n    return 0\n")
    _write(root / "plugins/bot_unified_runtime/__init__.py", "")
    _write(root / "plugins/bot_unified_runtime/domains/render/reviewer.py", "")
    _write(root / "tests/test_example.py", "def test_example():\n    assert True\n")
    _write(root / "tests/plugins/bot_unified_runtime/__init__.py", "")
    _write(root / "tests/plugins/bot_unified_runtime/domains/__init__.py", "")
    _write(root / ".gitignore", "__pycache__/\n*.pyc\n")
    return root


# ------------------------------------------------------------------ 四格注毒器
def _poison_tests_subtree_pycache(root: Path) -> Path:
    directory = root / "tests/plugins/bot_unified_runtime/__pycache__"
    directory.mkdir(parents=True)
    _write(directory / "test_example.cpython-312.pyc", "")
    return directory


def _poison_scripts_subtree_pycache(root: Path) -> Path:
    directory = root / "scripts/__pycache__"
    directory.mkdir(parents=True)
    _write(directory / "pre_restart_check.cpython-312.pyc", "")
    return directory


def _poison_root_loose_pyc(root: Path) -> Path:
    return _write(root / "bot.cpython-312.pyc", "")


def _poison_sidecar_beside_source(root: Path) -> Path:
    """字节码贴着源文件同目录落盘（无 __pycache__、无子目录）＝旧扫面全盲那一型。"""
    return _write(
        root / "plugins/bot_unified_runtime/domains/render/reviewer.cpython-312.pyc", ""
    )


# ------------------------------------------------------------------ ① 反向不误伤
def test_clean_tree_never_flags_bytecode_for_the_four_new_shapes(tmp_path: Path) -> None:
    root = _clean_tree(tmp_path / "repo")
    assert gate.scan_generated_residue(root) == {}, (
        "legitimate layout must produce zero findings before any poisoning"
    )


@pytest.mark.parametrize(
    "planter",
    (_poison_tests_subtree_pycache, _poison_scripts_subtree_pycache),
    ids=["tests-subtree", "scripts-subtree"],
)
def test_subtree_pycache_is_named_and_only_itself(tmp_path: Path, planter) -> None:
    """``tests/**`` 与 ``scripts/**`` 里的 ``__pycache__`` 必须点名，且不许连带误伤。"""
    root = _clean_tree(tmp_path / "repo")
    planted = planter(root)

    findings = gate.scan_generated_residue(root)

    assert BYTECODE in findings, f"blind spot: {planted.name} residue invisible; findings={findings}"
    assert set(findings) == {BYTECODE}, f"only bytecode was planted, got {sorted(findings)}"
    reported = "\n".join(findings[BYTECODE])
    relative = planted.relative_to(root).as_posix()
    assert relative in reported, f"{relative} must be named: {reported}"


def test_root_loose_pyc_is_named(tmp_path: Path) -> None:
    root = _clean_tree(tmp_path / "repo")
    planted = _poison_root_loose_pyc(root)

    findings = gate.scan_generated_residue(root)
    reported = "\n".join(findings.get(BYTECODE, []))

    assert BYTECODE in findings, f"blind spot: root-level loose .pyc invisible; findings={findings}"
    assert set(findings) == {BYTECODE}, f"only bytecode was planted, got {sorted(findings)}"
    assert planted.name in reported, f"{planted.name} must be named: {reported}"


def test_bytecode_beside_source_is_named(tmp_path: Path) -> None:
    """sidecar 形态：``X.cpython-3XX.pyc`` 与 ``X.py`` 同目录 ⇒ 必须点名那枚 .pyc。"""
    root = _clean_tree(tmp_path / "repo")
    planted = _poison_sidecar_beside_source(root)

    findings = gate.scan_generated_residue(root)
    reported = "\n".join(findings.get(BYTECODE, []))

    assert BYTECODE in findings, f"blind spot: sidecar bytecode invisible; findings={findings}"
    assert set(findings) == {BYTECODE}, f"only bytecode was planted, got {sorted(findings)}"
    assert planted.relative_to(root).as_posix() in reported, (
        f"the offender itself must be named, not just its parent: {reported}"
    )


# ------------------------------------------------------------------ ② 四格同树混注
def test_all_four_bytecode_shapes_fire_in_one_tree(tmp_path: Path) -> None:
    """扩面覆盖锁：四格同树 ⇒ 四格全部现身，且只有字节码那一类响。"""
    root = _clean_tree(tmp_path / "repo")
    planted = [
        _poison_tests_subtree_pycache(root),
        _poison_scripts_subtree_pycache(root),
        _poison_root_loose_pyc(root),
        _poison_sidecar_beside_source(root),
    ]

    findings = gate.scan_generated_residue(root)

    assert set(findings) == {BYTECODE}, f"expected only the bytecode class, got {sorted(findings)}"
    reported = "\n".join(findings[BYTECODE])
    for path in planted:
        needle = path.name if path.is_file() else path.name + "/"
        assert needle in reported, f"{path} not named in: {reported}"


# ------------------------------------------------------------------ ③ 真实工作树读数
def test_real_workspace_bytecode_is_within_known_classes() -> None:
    """真实工作树扫面必须只报已知类别（不许漂出尺外），并且扫得动（有界耗时）。"""
    import time

    started = time.monotonic()
    findings = gate.scan_generated_residue(gate.PROJECT_ROOT)
    elapsed = time.monotonic() - started

    assert set(findings) <= set(gate.RESIDUE_CLASS_TAGS), (
        f"unknown residue class reported: {sorted(set(findings) - set(gate.RESIDUE_CLASS_TAGS))}"
    )
    for tag, paths in findings.items():
        assert paths, f"empty class must be dropped, not reported: {tag}"
    assert elapsed < 120.0, f"residue scan took {elapsed:.1f}s"
    # 读数原样带进报告：本席不写死枚数（规则 10），只保证「有这一类时名字落在树内」。
    for entry in findings.get(BYTECODE, []):
        head = Path(entry.split(" ")[0].split("/")[0])
        assert (gate.PROJECT_ROOT / head).exists() or head == Path("."), f"escaping finding: {entry}"


# ------------------------------------------------------------------ ④ 锁自己要有牙
@pytest.mark.parametrize(
    ("needle", "replacement", "must_escape"),
    (
        ('name == "__pycache__"', 'name == "__pycache__DISABLED__"', "dir"),
        (
            'filename.endswith((".pyc", ".pyo"))',
            'filename.endswith((".pycDISABLED__", ".pyoDISABLED__"))',
            "file",
        ),
    ),
    ids=["kill-pycache-name", "kill-pyc-suffix"],
)
def test_killing_the_ruler_makes_the_planted_shapes_escape(
    tmp_path: Path, needle: str, replacement: str, must_escape: str
) -> None:
    """摘一条判据腿 ⇒ **它自己那格**必须失焦，另一条腿必须还在报（两腿互不遮掩）。

    没有这一腿，「扫面扩了」这句话可以靠加一条永不命中的分支假装做到。
    ⚠ 2026-10-05 修锚点：门本体在两批之间把字节码判定拆成**目录腿＋文件腿**两处
    （``name == "__pycache__"`` 与 ``filename.endswith((".pyc", ".pyo"))``），旧写法
    「摘掉一条腿后整格应为空」从此不成立（另一条腿照报），且第二条锚点字面量已被
    真身换掉——本条按真身重锚，并把断言收紧成**逐腿独立性**（比原断言更强）。
    """
    source = (SCRIPTS_DIR / "runtime_layout_smoke.py").read_text(encoding="utf-8")
    assert source.count(needle) == 1, f"anchor drifted ({needle}) — 本锁的锚点要跟真身一起改"
    module = _load_copy(tmp_path, source.replace(needle, replacement))

    root = _clean_tree(tmp_path / "repo")
    for planter in (
        _poison_tests_subtree_pycache,
        _poison_scripts_subtree_pycache,
        _poison_root_loose_pyc,
        _poison_sidecar_beside_source,
    ):
        planter(root)

    listed = module.scan_generated_residue(root).get(BYTECODE, [])
    dirs = [f for f in listed if f.endswith("__pycache__/")]
    files = [f for f in listed if f.endswith((".pyc", ".pyo"))]
    if must_escape == "dir":
        assert not dirs, f"目录腿摘了还在报 __pycache__ 目录＝判据不止一处：{dirs}"
        assert files, "反向腿：文件腿应当照报（两腿若其实是同一处，本锁就是假独立）"
    else:
        assert not files, f"文件腿摘了还在报散落脚本：{files}"
        assert dirs, "反向腿：目录腿应当照报（否则真身只剩一条腿，本臂无意义）"


def _load_copy(tmp_path: Path, source: str):
    """把注毒后的门源码装成独立模块——真身零接触（exec 完即摘，不留幽灵模块）."""
    import importlib.util

    path = _write(tmp_path / "gate_copy.py", source)
    spec = importlib.util.spec_from_file_location("runtime_layout_gate_poisoned", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


# ------------------------------------------------------------------ ⑤ 端到端真跑
@pytest.fixture(scope="module")
def scratch_base() -> Path:
    """仓外、且不在 ``ChatBot_Runtime`` 之下的扫描根（假绿形态清单 242 那条坑）。"""
    runtime_root = (REPO_ROOT.parent / "ChatBot_Runtime").resolve()
    for name in ("LOCALAPPDATA", "TEMP", "TMP"):
        raw = os.environ.get(name)
        if not raw:
            continue
        candidate = Path(raw).resolve() / "seat446" / "runtime-layout"
        if _inside(candidate, runtime_root):
            continue
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate
    raise AssertionError("no writable scan root outside the workspace and ChatBot_Runtime")


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _build_repo_copy(scratch: Path, case: str) -> tuple[Path, dict[str, str]]:
    """只拷「参与判定」的少数文件，避免整仓 rglob 被拖慢。"""
    repo = scratch / case
    if repo.exists():
        shutil.rmtree(repo)
    (repo / "scripts").mkdir(parents=True)
    shutil.copy2(SCRIPTS_DIR / "runtime_layout_smoke.py", repo / "scripts" / "runtime_layout_smoke.py")
    # ⚠ 2026-10-05 补：门本体现在**模块级**就 `from runtime_paths import …`（真身 :38），
    # 夹具只拷一枚文件会让子进程 ImportError 而 stdout 全空——端到端两臂此前就是这样瞎的。
    shutil.copy2(SCRIPTS_DIR / "runtime_paths.py", repo / "scripts" / "runtime_paths.py")
    _write(repo / "bot.py", "print('ok')\n")
    _write(repo / "pyproject.toml", '[tool.nonebot]\nplugin_dirs = ["plugins"]\n')
    _write(repo / "plugins/bot_unified_runtime/__init__.py", "")
    _write(repo / "tests/test_example.py", "def test_example():\n    assert True\n")
    runtime_root = scratch / f"Runtime_{case}"
    # ⚠ 2026-10-05 补：门本体（`main()` :305）自 10-02 那批起多了一条硬前提——
    # `PROJECT_ROOT.parent / "ChatBot_Runtime"` 必须存在。合成仓的 parent 就是 `scratch`，
    # 不造这枚同级目录，端到端两臂会一律吃 `runtime root missing` 而红在**夹具**上。
    (scratch / "ChatBot_Runtime").mkdir(parents=True, exist_ok=True)
    # ⚠ 2026-10-05 修：`scratch_base` 是**模块级固定路径**，上一发留下的 Runtime_*/personas_*
    # 会让这里的 mkdir 直接 FileExistsError（第二发必炸＝夹具不幂等，端到端两臂此前就是这样红）。
    for stale in (runtime_root, scratch / f"personas_{case}"):
        if stale.exists():
            shutil.rmtree(stale)
    data_root = runtime_root / "runtime_data"
    data_root.mkdir(parents=True, exist_ok=True)
    _write(data_root / "knowledge_embeddings.sqlite3", "")
    _write(data_root / "knowledge_faiss.index", "")
    _write(runtime_root / "card_render_assets/shell.svg", "<svg/>")
    persona = _write(scratch / f"personas_{case}/shorekeeper/prompt.md", "守岸人\n")
    for sub in ("cache", "config", "localstore_data"):
        (runtime_root / sub).mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    for key in (
        "BOT_RUNTIME_DATA_DIR",
        "BOT_PERSONA_FILES",
        "BOT_KNOWLEDGE_FILES",
        "BOT_CARD_ASSET_DIR",
        "LOCALSTORE_USE_CWD",
        "LOCALSTORE_CACHE_DIR",
        "LOCALSTORE_CONFIG_DIR",
        "LOCALSTORE_DATA_DIR",
    ):
        env.pop(key, None)
    env.update(
        {
            "BOT_RUNTIME_DATA_DIR": str(data_root),
            "BOT_PERSONA_FILES": os.pathsep.join([str(persona)]),
            "BOT_KNOWLEDGE_FILES": os.pathsep.join([str(data_root / "knowledge_embeddings.sqlite3")]),
            "BOT_CARD_ASSET_DIR": str(runtime_root / "card_render_assets"),
            "LOCALSTORE_USE_CWD": "false",
            "LOCALSTORE_CACHE_DIR": str(runtime_root / "cache"),
            "LOCALSTORE_CONFIG_DIR": str(runtime_root / "config"),
            "LOCALSTORE_DATA_DIR": str(runtime_root / "localstore_data"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPYCACHEPREFIX": str(runtime_root / "pycache"),
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "BOT_AUTOSYNC": "0",
        }
    )
    return repo, env


def _run_gate(repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    # 台账 #47★：subprocess.run 不钉 encoding 必崩（中文 stdout 在 Windows 上炸 UnicodeDecodeError）。
    return subprocess.run(
        [sys.executable, "scripts/runtime_layout_smoke.py"],
        cwd=str(repo),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def test_end_to_end_clean_copy_exits_zero(scratch_base: Path) -> None:
    repo, env = _build_repo_copy(scratch_base, "clean")

    proc = _run_gate(repo, env)

    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
    assert "runtime-layout: PASS" in proc.stdout, proc.stdout
    assert "generated_residue=absent" in proc.stdout, proc.stdout


def test_end_to_end_all_four_shapes_exit_nonzero_and_named(scratch_base: Path) -> None:
    """端到端：真跑门本体，四格同造 ⇒ rc=1，且 stdout 逐格点名 + 归因不冤杀 dev.ps1。"""
    repo, env = _build_repo_copy(scratch_base, "poisoned")
    planted = [
        _poison_tests_subtree_pycache(repo),
        _poison_scripts_subtree_pycache(repo),
        _poison_root_loose_pyc(repo),
        _poison_sidecar_beside_source(repo),
    ]

    proc = _run_gate(repo, env)

    assert proc.returncode == 1, f"poison escaped the gate: stdout={proc.stdout}"
    assert "runtime-layout: PASS" not in proc.stdout, proc.stdout
    assert f"[{BYTECODE}]" in proc.stdout, proc.stdout
    for path in planted:
        needle = path.name if path.is_file() else path.name + "/"
        assert needle in proc.stdout, f"{path} not named in stdout:\n{proc.stdout}"
    assert "bypassed dev.ps1" in proc.stdout, (
        "归因句必须说清污染源是裸跑路线，不是门自己：\n" + proc.stdout
    )
