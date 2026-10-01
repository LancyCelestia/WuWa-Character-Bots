"""Verify that mutable runtime data stays outside the AI source workspace.

This is an offline structural check. It never opens database contents, calls an
LLM, connects to a platform, or prints secrets from dotenv files.  It is read-only
by design: it reports generated residue (bytecode, tool caches, in-tree venvs,
pytest scratch roots, distribution metadata shells) instead of deleting it -- the
cleanup decision belongs to a human, and blind recursive deletion in this workspace
has already destroyed in-flight work twice.

Self test lock: ``tests/test_runtime_layout_smoke.py`` (poison legs per class, a
no-false-positive leg, and an end-to-end run of ``main()`` in a copy of the gate
outside the repository).  Extending the scan surface without that lock in the same
batch is what ledger #68 forbids.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# S139：本门曾自己往源码树写字节码（S129 的 C1）。第一个「项目树」import
# （runtime_paths，住 scripts/）若在本进程尚无字节码保护时执行，会当场长出
# scripts/__pycache__，随后的扫描把自家产物记成红——裸跑路线必现（已实证），
# dev.ps1 路线靠启动期 $env 不写（5 连跑实证）。旧 :123 的 setdefault 既排在
# import 之后、又只及**之后启动的子进程**，两样都救不了本进程 import。
# 修法＝在第一个项目树 import 之前把两条通道都设好：
#   - os.environ.setdefault：解释器启动期已被 site.py 读完，进程中途改它
#     不影响本进程 import（%TEMP% 探针实证），作用域只有子进程；
#   - sys.dont_write_bytecode：本进程后续 import 的唯一有效闸。
# stdlib（json/os/sys/pathlib）留在闸之前是安全的：其 .pyc 落解释器安装目录，
# 永不在门扫描面 PROJECT_ROOT.rglob 之内。
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
sys.dont_write_bytecode = True

from runtime_paths import PROJECT_ROOT, _dotenv_value, runtime_data_dir

RUNTIME_ROOT = PROJECT_ROOT.parent / "ChatBot_Runtime"


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _configured_list(key: str) -> list[Path]:
    raw = _dotenv_value(key)
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = [item.strip() for item in raw.split(";") if item.strip()]
    if not isinstance(parsed, list):
        return []
    return [Path(str(item)).expanduser() for item in parsed]


def _external_path(key: str) -> Path | None:
    raw = _dotenv_value(key)
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


# ---------------------------------------------------------------------------
# 生成物残留扫描面（席 R1，2026-10-02；台账 #68★＝扩扫面与它的自测锁必须同批）
#
# 旧扫面只有 `rglob("*.pyc")` + `*.pyo` + `__pycache__`，对以下两类全盲：
#   ① 工具缓存 / venv / 树内 basetemp（本波 433 枚 .pyc 落进 plugins/** 把门打成
#      FAIL、`.pytest_cache` 残件、`cb-w9chk` 这种 basetemp 残根全都不叫）；
#   ② 被 .gitignore 吞掉、`git status` 永远看不见的残留——一枚**空**的
#      `Bot_Character_Bots.egg-info/` 让 `importlib.metadata` 认到一个无 Version 的
#      distribution，直接吃掉三枚 `test_error_report`（HANDBOOK P1 段在册）。
# 现算基线（2026-10-02 01:4x 本地，同一把尺）：全树 os.walk 0.5s；`.pyc` 岛外 1 枚、
# 岛内 0 枚；树内 basetemp 形状命中恰好 1 个目录（`cb-w9chk/`，46 枚 `test_*<N>` 子
# 目录）；空目录 1198 枚 ⇒ **「空目录」本身绝不能当判据**（一上就误杀 1198 格），
# 只有落在生成物形状上（`*.egg-info` 一类）才记账。
#
# 判据形状照仓内既有门 `tests/test_static_hygiene_snapshot.py::_scan_tree_cache_products`
# （os.walk + 命中即剪枝），只锁不松：本函数覆盖旧 rglob 的全部三类，另加四格。
# 自测锁＝``tests/test_runtime_layout_smoke.py``（注毒腿逐类真跑 + 反向不误伤腿 +
# 仓外副本的端到端 rc 双腿）。
# ---------------------------------------------------------------------------

RESIDUE_PYTHON_BYTECODE: str = "python-bytecode"
RESIDUE_TOOL_CACHE: str = "tool-cache"
RESIDUE_IN_TREE_VENV: str = "in-tree-venv"
RESIDUE_PYTEST_SCRATCH: str = "pytest-scratch-in-repo"
RESIDUE_DISTRIBUTION_METADATA: str = "distribution-metadata"

#: 类别标签即报告口径：一条红必须点名是哪一类，便于把「污染源」和「凶手」分清。
RESIDUE_CLASS_TAGS: tuple[str, ...] = (
    RESIDUE_PYTHON_BYTECODE,
    RESIDUE_TOOL_CACHE,
    RESIDUE_IN_TREE_VENV,
    RESIDUE_PYTEST_SCRATCH,
    RESIDUE_DISTRIBUTION_METADATA,
)

TOOL_CACHE_DIR_NAMES: frozenset[str] = frozenset(
    {".pytest_cache", ".ruff_cache", ".mypy_cache"}
)
#: 裸名即算 venv 残根的两个名字（`.venv`/`venv` 在 `.gitignore` 里在册，源码树不该有）。
STRONG_VENV_DIR_NAMES: frozenset[str] = frozenset({".venv", "venv"})
#: `env` 太像正常源码目录名，只有拿到硬形状（pyvenv.cfg / site-packages）才算。
WEAK_VENV_DIR_NAMES: frozenset[str] = frozenset({"env"})
#: 永不进入的第三方/版本库岛；`site-packages` 剪枝同时兜住「包内 dist-info 属正常物」。
PRUNED_DIR_NAMES: frozenset[str] = frozenset(
    {".git", "node_modules", "site-packages", "dist-packages", "__pypackages__"}
)
DISTRIBUTION_METADATA_SUFFIXES: tuple[str, ...] = (".egg-info", ".dist-info")
DISTRIBUTION_METADATA_NAMES: frozenset[str] = frozenset({".eggs"})
#: pytest `tmp_path` 目录名＝`test_<用例名截断>` + `<序号>`（`cb-w9chk` 现算 46 枚如此）。
_PYTEST_TMP_CHILD_RE: re.Pattern[str] = re.compile(r"^test_[^\\/]*\d{1,3}$")
_PYTEST_SCRATCH_NAME_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"^pytest-of-.+$"),
    re.compile(r"^\.pytest_tmp.*$"),
    re.compile(r"^basetemp$"),
)
#: basetemp 内容形状阈值＝3（真实分布：全树只有 `cb-w9chk/` 达 46，其余 0，无灰区）。
_PYTEST_SCRATCH_CHILD_MIN: int = 3
_MAX_LISTED_PATHS: int = 12

#: 归因文案：dev.ps1 路线本身是干净的，红来自**绕过**它的裸跑。别把门报成凶手。
RESIDUE_ATTRIBUTION: dict[str, str] = {
    RESIDUE_PYTHON_BYTECODE: (
        "attribution: scripts/dev.ps1 pins PYTHONDONTWRITEBYTECODE=1 and "
        "PYTHONPYCACHEPREFIX=<ChatBot_Runtime>/pycache before any tool starts, so "
        "bytecode inside the source tree can only come from a Python/pytest invocation "
        "that bypassed dev.ps1 (AGENTS rule 6 hygiene prefix) -- not from dev.ps1 itself"
    ),
    RESIDUE_TOOL_CACHE: (
        "attribution: scripts/dev.ps1 hands ruff/mypy a --cache-dir inside "
        "ChatBot_Runtime/cache and pytest runs with -p no:cacheprovider, so a cache dir "
        "in the source tree comes from a raw `ruff`/`mypy`/`pytest` call outside dev.ps1"
    ),
    RESIDUE_IN_TREE_VENV: (
        "attribution: the project interpreter lives in ChatBot_Runtime/venv; dev.ps1 "
        "probes an in-tree .venv as a fallback, so this is interpreter drift waiting to "
        "happen (AGENTS: runtime data root is ChatBot_Runtime)"
    ),
    RESIDUE_PYTEST_SCRATCH: (
        "attribution: a pytest basetemp/tmp_path root landed inside the workspace -- "
        "--basetemp was passed without the outside-repo scratch base dev.ps1 uses"
    ),
    RESIDUE_DISTRIBUTION_METADATA: (
        "attribution: build/install metadata inside the AI workspace is claimed by "
        "importlib.metadata (a shell without a Version line shadows the real "
        "distribution), and .gitignore hides it from `git status` entirely"
    ),
}


def _relative_to_root(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _is_empty_dir(path: Path) -> bool:
    try:
        return not any(path.iterdir())
    except OSError:
        return False


def _looks_like_venv(child: Path, name: str) -> bool:
    if (child / "pyvenv.cfg").is_file():
        return True
    if (child / "Lib" / "site-packages").is_dir() or (child / "site-packages").is_dir():
        return True
    if name in STRONG_VENV_DIR_NAMES:
        return (child / "Scripts").is_dir() or (child / "bin").is_dir()
    return False


def _distribution_metadata_detail(child: Path) -> str:
    """说清这枚元数据壳会不会真的骗过 ``importlib.metadata``（本波实咬的那格）。"""
    for filename in ("METADATA", "PKG-INFO"):
        candidate = child / filename
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return f"{filename} unreadable"
        if re.search(r"^Version:\s*\S", text, re.MULTILINE):
            return f"{filename} declares a Version -- shadows the real distribution"
        return f"{filename} carries no Version: line (importlib.metadata still claims it)"
    return "empty metadata shell -- importlib.metadata claims a distribution with no Version"


def _is_distribution_metadata(name: str) -> bool:
    """`*.egg-info` / `*.dist-info` / `.eggs`＝安装与构建元数据，源码树一律不该有。"""
    return name.endswith(DISTRIBUTION_METADATA_SUFFIXES) or name in DISTRIBUTION_METADATA_NAMES


def _basetemp_children(dirnames: list[str]) -> list[str]:
    return [name for name in dirnames if _PYTEST_TMP_CHILD_RE.match(name)]


def scan_generated_residue(root: Path) -> dict[str, list[str]]:
    """One pass over ``root`` returning ``{class tag: [offending relative path, ...]}``.

    Pure and read-only: it never creates, deletes, or rewrites anything, so the self
    test can point it at a fabricated tree outside the repository and at the real one.
    A residue directory that has been named is pruned -- its innards belong to the
    class already reported (that is how an in-tree ``.venv`` stays one line instead of
    hundreds of ``site-packages`` hits).
    """
    findings: dict[str, list[str]] = {tag: [] for tag in RESIDUE_CLASS_TAGS}
    if not root.is_dir():
        # 缺席的根＝零命中，返回值形态必须与"扫过且干净"逐字一致（都剥掉空类别），
        # 否则调用方按 `if findings:` 判红时会把"没得扫"读成"扫出五类"。
        return {}

    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda _error: None):
        current = Path(dirpath)
        scratch = _basetemp_children(dirnames)
        if len(scratch) >= _PYTEST_SCRATCH_CHILD_MIN:
            findings[RESIDUE_PYTEST_SCRATCH].append(
                f"{_relative_to_root(current, root) or '.'}/ "
                f"({len(scratch)} pytest tmp_path child dirs)"
            )
            # One finding per residue root: the tmp_path children belong to it.
            for name in scratch:
                if name in dirnames:
                    dirnames.remove(name)
        for name in list(dirnames):
            child = current / name
            relative = _relative_to_root(child, root)
            if name == "__pycache__":
                findings[RESIDUE_PYTHON_BYTECODE].append(f"{relative}/")
                dirnames.remove(name)
                continue
            if name in TOOL_CACHE_DIR_NAMES:
                findings[RESIDUE_TOOL_CACHE].append(f"{relative}/")
                dirnames.remove(name)
                continue
            if name in PRUNED_DIR_NAMES:
                dirnames.remove(name)
                continue
            if (
                name in STRONG_VENV_DIR_NAMES or name in WEAK_VENV_DIR_NAMES
            ) and _looks_like_venv(child, name):
                findings[RESIDUE_IN_TREE_VENV].append(f"{relative}/")
                dirnames.remove(name)
                continue
            if _is_distribution_metadata(name):
                marker = " [empty]" if _is_empty_dir(child) else ""
                findings[RESIDUE_DISTRIBUTION_METADATA].append(
                    f"{relative}/{marker} -- {_distribution_metadata_detail(child)}"
                )
                dirnames.remove(name)
                continue
            for pattern in _PYTEST_SCRATCH_NAME_RES:
                if pattern.match(name):
                    findings[RESIDUE_PYTEST_SCRATCH].append(f"{relative}/")
                    dirnames.remove(name)
                    break
        for filename in filenames:
            if filename.endswith((".pyc", ".pyo")):
                findings[RESIDUE_PYTHON_BYTECODE].append(
                    _relative_to_root(current / filename, root)
                )
    return {tag: sorted(paths) for tag, paths in findings.items() if paths}


def format_generated_residue_errors(findings: dict[str, list[str]]) -> list[str]:
    """Render scan findings as gate error lines, each naming its class and its source."""
    errors: list[str] = []
    for tag in RESIDUE_CLASS_TAGS:
        paths = findings.get(tag, [])
        if not paths:
            continue
        shown = paths[:_MAX_LISTED_PATHS]
        suffix = "" if len(paths) <= _MAX_LISTED_PATHS else f" (+{len(paths) - len(shown)} more)"
        attribution = RESIDUE_ATTRIBUTION.get(tag, "")
        errors.append(
            f"generated residue [{tag}] x{len(paths)}: "
            + ", ".join(shown)
            + suffix
            + (f" -- {attribution}" if attribution else "")
        )
    return errors


def main() -> int:
    errors: list[str] = []
    data_root = runtime_data_dir()
    if not data_root.is_dir():
        errors.append(f"runtime data directory missing: {data_root}")
    if _inside(data_root, PROJECT_ROOT):
        errors.append("BOT_RUNTIME_DATA_DIR points inside the AI source workspace")
    if not RUNTIME_ROOT.is_dir():
        errors.append(f"runtime root missing: {RUNTIME_ROOT}")

    for relative in ("knowledge_embeddings.sqlite3", "knowledge_faiss.index"):
        path = data_root / relative
        if not path.is_file():
            errors.append(f"required runtime file missing: {path}")

    if not _configured_list("BOT_PERSONA_FILES"):
        errors.append("BOT_PERSONA_FILES is empty")
    if not _configured_list("BOT_KNOWLEDGE_FILES"):
        errors.append("BOT_KNOWLEDGE_FILES is empty")
    for key in ("BOT_PERSONA_FILES", "BOT_KNOWLEDGE_FILES"):
        for path in _configured_list(key):
            if not path.is_absolute():
                path = PROJECT_ROOT / path
            if not path.is_file():
                errors.append(f"configured {key} file missing: {path.resolve()}")

    card_assets = _external_path("BOT_CARD_ASSET_DIR")
    if card_assets is None:
        card_assets = RUNTIME_ROOT / "card_render_assets"
    if not card_assets.is_dir() or not any(card_assets.rglob("*.svg")):
        errors.append(f"card SVG asset directory is missing or empty: {card_assets}")
    elif _inside(card_assets, PROJECT_ROOT):
        errors.append("card SVG assets unexpectedly live inside the AI source workspace")

    localstore_use_cwd = _dotenv_value("LOCALSTORE_USE_CWD").lower()
    if localstore_use_cwd == "true":
        errors.append("LOCALSTORE_USE_CWD=true would write third-party state into CWD")
    elif localstore_use_cwd not in {"false", "0", "no"}:
        errors.append("LOCALSTORE_USE_CWD must be explicitly false")
    for key in ("LOCALSTORE_CACHE_DIR", "LOCALSTORE_CONFIG_DIR", "LOCALSTORE_DATA_DIR"):
        path = _external_path(key)
        if path is None:
            errors.append(f"{key} is not configured")
        elif _inside(path, PROJECT_ROOT):
            errors.append(f"{key} points inside the AI source workspace: {path}")

    for relative in ("data", "cache", "config"):
        local_dir = PROJECT_ROOT / relative
        if local_dir.is_dir() and any(local_dir.rglob("*")):
            errors.append(f"source workspace contains generated/runtime files in {local_dir}")

    residue = scan_generated_residue(PROJECT_ROOT)
    errors.extend(format_generated_residue_errors(residue))

    if errors:
        print("runtime-layout: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    print("runtime-layout: PASS")
    print(f"source_workspace={PROJECT_ROOT}")
    print(f"runtime_root={RUNTIME_ROOT}")
    print(f"runtime_data={data_root}")
    print("external_databases=knowledge_embeddings.sqlite3, knowledge_faiss.index")
    print("localstore=external cache/config/data")
    print("source_generated_dirs=empty")
    print("generated_residue_classes=" + ",".join(RESIDUE_CLASS_TAGS))
    print("generated_residue=absent")
    return 0


if __name__ == "__main__":
    # 旧版在这里 os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")——排在
    # 模块顶部 import 之后且只及子进程，是 S129 C1 的成因；已上移至守卫区。
    raise SystemExit(main())
