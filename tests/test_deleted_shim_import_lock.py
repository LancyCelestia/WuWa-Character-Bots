"""已删垫片路径的 import 存在性锁（席 S-BLIND-REPOINT-b，2026-09-27）。

背景：垫片退役波 W1 已删除四枚 PEP562 转发垫片——

- ``plugins/bot_unified_runtime/llm/ledger.py``
- ``plugins/bot_unified_runtime/llm/providers.py``
- ``plugins/bot_unified_runtime/character/reminders.py``
- ``plugins/bot_unified_runtime/character/vector_knowledge.py``

（备份 ``%TEMP%\\shim-w1-backup-20260927-013104\\``。）任何**直连**这四条模块路径的
import 在垫片文件已物理消失的现在都必致 ImportError；而经 ``llm/``、``character/``
两个仍存活的壳包按属性形 import（如 ``from plugins.bot_unified_runtime.llm import
providers``）会被壳的 ``__getattr__`` 兜到 canonical——静态普查看不见、运行期却是活的，
退役台账收口判据会被它糊过去。本门把两种形态一并钉死：**全树不允许再有任何 import
指向这四条已删路径（含壳包属性形）**。

判据口径（防三型假绿）：
- **扫描面不许塌陷**：只数命中不数被检文件数，glob 一改就能把账做没，故设文件数地板。
- **注毒走内存源码**：判据函数吃字符串，不往树里写毒件；每形态一发、各杀各锁。
- **相对 import 也解析**：level>0 的 from-import 按所在包上下文折算绝对路径后再判，
  否则壳包内 ``from . import providers`` 就是尺的盲区。
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG_ROOT = REPO_ROOT / "plugins" / "bot_unified_runtime"

#: 本锁所在的文件自身不吃扫——它必须持有这四条路径的字符串常量才能执法。
SELF_FILE = Path(__file__).resolve()

#: 已删垫片模块的绝对 dotted 路径（唯一真身清单）。
DELETED_MODULES: frozenset[str] = frozenset(
    {
        "plugins.bot_unified_runtime.llm.ledger",
        "plugins.bot_unified_runtime.llm.providers",
        "plugins.bot_unified_runtime.character.reminders",
        "plugins.bot_unified_runtime.character.vector_knowledge",
    }
)

#: 仍存活的壳包 → 该包下已删的子模块名（属性形 ``from <壳包> import <子模块名>`` 判据）。
SHELL_PACKAGES: dict[str, frozenset[str]] = {
    "plugins.bot_unified_runtime.llm": frozenset({"ledger", "providers"}),
    "plugins.bot_unified_runtime.character": frozenset({"reminders", "vector_knowledge"}),
}

#: 扫描根（生产 + 工具 + 测试全覆盖）。
SCAN_ROOTS: tuple[str, ...] = ("plugins", "scripts", "tests")
#: 扫描文件数地板：低于此＝扫描面塌了，不是"大家都迁完了"。
MIN_SCANNED_FILES = 900


def _package_context(rel_path: Path) -> str:
    """文件相对仓根的 dotted 模块上下文（__init__.py 归属其所在包本身）。"""
    parts = list(rel_path.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _resolve_from_module(ctx: str, is_init: bool, node: ast.ImportFrom) -> str:
    """把 ImportFrom（含相对形）折成绝对 dotted 模块路径。"""
    if node.level == 0:
        return node.module or ""
    parts = ctx.split(".") if ctx else []
    if not parts:
        return node.module or ""
    if not is_init:
        # ctx 含模块名末段；level=1 的锚是其所在包。
        parts = parts[:-1]
    # level>=2 时每多一级再向上跳一层包。
    for _ in range(node.level - 1):
        if parts:
            parts = parts[:-1]
    joined = ".".join(parts)
    if node.module:
        joined = f"{joined}.{node.module}" if joined else node.module
    return joined


def _is_deleted_target(module_path: str, names: set[str]) -> bool:
    """模块路径本身、其子模块、或"壳包+已删子模块名"属性形，命中即真。"""
    for deleted in DELETED_MODULES:
        if module_path == deleted or module_path.startswith(deleted + "."):
            return True
    shell = SHELL_PACKAGES.get(module_path)
    return shell is not None and bool(names & shell)


def _iter_violations(source: str, rel_path: Path) -> list[str]:
    """扫一份源码，返回违规描述列表（空=干净）。"""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [f"{rel_path}: 语法解析失败（跳过会把盲区洗成绿）"]
    is_init = rel_path.name == "__init__.py"
    ctx = _package_context(rel_path)
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_deleted_target(alias.name, set()):
                    out.append(f"{rel_path}:{node.lineno}: import {alias.name} → 已删垫片路径")
        elif isinstance(node, ast.ImportFrom):
            module_path = _resolve_from_module(ctx, is_init, node)
            names = {alias.name for alias in node.names}
            if _is_deleted_target(module_path, names):
                out.append(
                    f"{rel_path}:{node.lineno}: from {module_path or '(包)'} import "
                    f"{sorted(names)} → 已删垫片路径（含壳包属性形）"
                )
        elif isinstance(node, ast.Call):
            fn = node.func
            fname = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if fname in {"import_module", "__import__"} and node.args:
                first = node.args[0]
                if (
                    isinstance(first, ast.Constant)
                    and isinstance(first.value, str)
                    and _is_deleted_target(first.value, set())
                ):
                    out.append(f"{rel_path}:{node.lineno}: {fname}({first.value!r}) → 已删垫片路径")
    return out


def _iter_py_files() -> list[Path]:
    files: list[Path] = []
    for root in SCAN_ROOTS:
        base = REPO_ROOT / root
        files.extend(p for p in base.rglob("*.py") if p.resolve() != SELF_FILE)
    return sorted(files)


# ------------------------------------------------------------------ 真树锁


def test_scanned_surface_does_not_collapse() -> None:
    """扫描面地板：文件数掉下去＝glob/排除被改，不是迁完了。"""
    files = _iter_py_files()
    assert len(files) >= MIN_SCANNED_FILES, (
        f"扫描面塌陷：只扫到 {len(files)} 件（地板 {MIN_SCANNED_FILES}）"
    )


def test_no_import_targets_deleted_shims() -> None:
    """全树（plugins/scripts/tests）无任何 import 指向四条已删垫片路径。"""
    violations: list[str] = []
    unparsable: list[str] = []
    for path in _iter_py_files():
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            source = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(REPO_ROOT)
        for v in _iter_violations(source, rel):
            (unparsable if "语法解析失败" in v else violations).append(v)
    assert not unparsable, f"解析失败件（不许静默跳过）：{unparsable[:5]}"
    assert not violations, "发现指向已删垫片的 import：\n" + "\n".join(violations[:20])


def test_shell_packages_still_lazy_but_lock_targets_are_gone() -> None:
    """壳包与四枚垫片文件的现状对照：壳在（不许误删），垫片文件必须已物理消失。"""
    assert (PKG_ROOT / "llm" / "__init__.py").is_file()
    assert (PKG_ROOT / "character" / "__init__.py").is_file()
    for gone in (
        PKG_ROOT / "llm" / "ledger.py",
        PKG_ROOT / "llm" / "providers.py",
        PKG_ROOT / "character" / "reminders.py",
        PKG_ROOT / "character" / "vector_knowledge.py",
    ):
        assert not gone.exists(), f"已删垫片又出现在盘上（谁还原的？）：{gone}"


# ------------------------------------------------------------------ 注毒自证（纯内存）

_POISON_SAMPLES: tuple[tuple[str, str, Path], ...] = (
    # (说明, 源码, 伪装路径)
    (
        "绝对 from-import 已删模块",
        "from plugins.bot_unified_runtime.llm.ledger import LedgerService\n",
        Path("x/y.py"),
    ),
    (
        "点号 import 已删模块",
        "import plugins.bot_unified_runtime.character.vector_knowledge\n",
        Path("x/y.py"),
    ),
    (
        "壳包属性形（PEP562 可解，但静态必须点名）",
        "from plugins.bot_unified_runtime.llm import providers\n",
        Path("x/y.py"),
    ),
    (
        "character 壳属性形 reminders",
        "from plugins.bot_unified_runtime.character import reminders\n",
        Path("x/y.py"),
    ),
    (
        "import_module 字符串形",
        (
            "from importlib import import_module\n"
            "m = import_module('plugins.bot_unified_runtime.llm.providers')\n"
        ),
        Path("x/y.py"),
    ),
    (
        "相对形（llm 壳包内 from . import providers）",
        "from . import providers\n",
        Path("plugins/bot_unified_runtime/llm/_poison_sample.py"),
    ),
    (
        "壳包子模块直连（from llm.providers import X）",
        "from plugins.bot_unified_runtime.llm.providers import LLMProviderError\n",
        Path("x/y.py"),
    ),
)


def test_poison_samples_are_all_caught() -> None:
    """每形态一发注毒，判据各杀各的——尺变瞎当场红。"""
    for label, src, rel in _POISON_SAMPLES:
        hits = _iter_violations(src, rel)
        assert hits, f"注毒未被抓住（{label}）：{src!r}"


def test_clean_sample_is_not_flagged() -> None:
    """反向锁：改线后的正确写法与合法壳属性名（契约名，非子模块）不得误伤。"""
    src = (
        "from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers "
        "import LLMProviderError\n"
        "from plugins.bot_unified_runtime.llm import LLMProvider  # 壳属性名=契约名，非子模块\n"
    )
    hits = _iter_violations(src, Path("x/y.py"))
    assert hits == [], hits
