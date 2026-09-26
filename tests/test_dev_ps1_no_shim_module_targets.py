"""FIX-2 回归锁：``scripts/dev.ps1`` 每个 ``-m`` 目标必须是可执行真身，不得是 Compat 垫片。

缺陷（P1，内容安全面）：``Invoke-MemorySanitize``（dev.ps1:861-872）实跑
``python -m plugins.bot_unified_runtime.security.memory_sanitize --dry-run``，而该路径实测是
18 行 PEP562 兼容垫片（体仅 ``_CANONICAL`` + ``def __getattr__``，无 ``if __name__ ==
"__main__"``）。``python -m <垫片>`` 只 import 就退出：**exit 0、零输出，``--dry-run``/``--apply``
被静默吞掉**——于是「记忆已清洗」成为假成功。真 CLI 在
``plugins/bot_unified_runtime/domains/chat_reply/security/memory_sanitize.py``。
第二层：真身 docstring 自称的用法恰恰写着那条已失效的旧路径命令（等于教人复现假成功），
本文件第五个用例把「文档不得教 ``-m`` 打进垫片」一并钉死。

判据（纯 AST + 文本，绝不起子进程、绝不执行被守卫的脚本）：
  · PEP562 垫片 —— 模块体含 ``def __getattr__`` 且转发到 ``_CANONICAL``；
  · re-export 垫片 —— docstring 以 ``Compat shim`` 开头，或模块体只有文档/import 且无 ``__main__`` 入口；
  · 不可执行 —— 模块体没有 ``if __name__ == "__main__":``（``-m`` 跑它必然静默退出）。

全离线：零网络、零进程、零 Runtime/数据读写。
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_DEV_PS1 = _ROOT / "scripts" / "dev.ps1"
# 2026-09-23「四门禁入口改成读一枚 JSON」后，具体任务的 ``-m`` 目标从 dev.ps1 内联文本
# 迁入本 JSON（真身任务表）。本门要把「dev.ps1 实际会执行的全部 -m 插件模块」都纳入，
# 取数口就必须同时覆盖 dev.ps1 与这份 JSON（否则命中数塌成 0，提取器判据失效＝账实不符）。
_TASKS_JSON = _ROOT / "scripts" / "chatbot-tasks.json"

_CANONICAL_MEMORY_SANITIZE = (
    "plugins.bot_unified_runtime.domains.chat_reply.security.memory_sanitize"
)
_LEGACY_MEMORY_SANITIZE = "plugins.bot_unified_runtime.security.memory_sanitize"

# 同时覆盖三种写法：
#   @("-m", "plugins.x.y")  /  @(\n  "-m",\n  "plugins.x.y")  /  & $python -m plugins.x.y
_MODULE_TARGET_RE = re.compile(
    r"""-m["']?\s*,\s*["']?(plugins\.bot_unified_runtime[\w.]+)"""
    r"""|-m\s+(plugins\.bot_unified_runtime[\w.]+)"""
)
_DOCSTRING_MODULE_RE = re.compile(r"""python\s+-m\s+(plugins\.bot_unified_runtime[\w.]+)""")

_SHIM_TAGS = frozenset({"PEP562_SHIM", "REEXPORT_SHIM", "NO_MAIN_ENTRY", "UNPARSEABLE"})


def _name_equals(node: ast.expr, name: str, value: str) -> bool:
    return (
        isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Name)
        and node.left.id == name
        and any(isinstance(c, ast.Constant) and c.value == value for c in node.comparators)
    )


def _has_main_guard(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.If) and _name_equals(node.test, "__name__", "__main__")
        for node in tree.body
    )


def _module_tags(source: str) -> list[str]:
    """给一段模块源码打上「垫片/不可执行」标签；空列表 = 可执行真身。"""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ["UNPARSEABLE"]
    tags: list[str] = []
    forwards = any(
        isinstance(node, ast.FunctionDef) and node.name == "__getattr__" for node in tree.body
    )
    if forwards and "_CANONICAL" in source:
        tags.append("PEP562_SHIM")
    doc = (ast.get_docstring(tree) or "").lstrip()
    only_reexports = all(
        isinstance(node, (ast.Import, ast.ImportFrom, ast.Expr)) for node in tree.body
    )
    has_main = _has_main_guard(tree)
    if doc.startswith("Compat shim") or (only_reexports and not has_main):
        tags.append("REEXPORT_SHIM")
    if not has_main:
        tags.append("NO_MAIN_ENTRY")
    return tags


def _module_source_file(module: str) -> Path | None:
    """点分模块名 → 盘上源码文件（含包 ``__init__.py`` 与包 ``__main__.py`` 优先）。"""
    parts = module.split(".")
    base = _ROOT.joinpath(*parts)
    if base.with_suffix(".py").is_file():
        return base.with_suffix(".py")
    if base.is_dir():
        entry = base / "__main__.py"
        return entry if entry.is_file() else base / "__init__.py"
    return None


def _dev_ps1_inline_targets() -> list[tuple[int, str]]:
    """dev.ps1 文本里内联写法的 ``-m plugins.*`` 目标（正则三形态全覆盖）。"""
    text = _DEV_PS1.read_text(encoding="utf-8")
    hits: list[tuple[int, str]] = []
    for match in _MODULE_TARGET_RE.finditer(text):
        module = (match.group(1) or match.group(2)).rstrip(".")
        hits.append((text[: match.start()].count("\n") + 1, module))
    return hits


def _task_json_targets() -> list[tuple[int, str]]:
    """``chatbot-tasks.json`` 里每个 ``type:"command"`` 且带 ``module`` 的目标。

    dev.ps1 对任何携带 ``module`` 的命令都拼成 ``python -m <module>`` 执行
    （见 dev.ps1:271-272 ``Invoke-DevCommand``；与 runner=external/soft/loop-plain 无关），
    所以这些就是本门要守的 ``-m`` 目标真身。``ensurePythonModule``（走 ``-c import``，
    见 dev.ps1:389）不是 ``-m`` 运行，按 ``type=="command"`` 天然排除。只取
    ``plugins.bot_unified_runtime`` 前缀（与 ``_MODULE_TARGET_RE`` 同域），``pip``/``mypy``
    属外部工具、非本包模块，不纳入。行号取该 ``module`` 字面量在 JSON 源里首次出现的行，
    仅供错误消息定位。
    """
    text = _TASKS_JSON.read_text(encoding="utf-8")
    data = json.loads(text)
    modules: list[str] = []

    def _walk(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "command" and isinstance(node.get("module"), str):
                modules.append(node["module"])
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(data.get("tasks", data))
    line_of: dict[str, int] = {}
    for lineno, line in enumerate(text.splitlines(), 1):
        for module in modules:
            if module not in line_of and f'"module": "{module}"' in line:
                line_of[module] = lineno
    return [
        (line_of.get(module, 1), module)
        for module in modules
        if module.startswith("plugins.bot_unified_runtime")
    ]


def _dev_ps1_targets() -> list[tuple[int, str]]:
    """四门禁实际会执行的全部 ``-m`` 插件模块目标 = dev.ps1 内联 + 迁入 JSON 的任务真身。

    改因（2026-09-24 席 S208，账跟随真值，非缩面而是随真身搬迁**扩大**取数口）：
    dev.ps1 迁入 chatbot-tasks.json 后其内联 ``-m plugins.*`` 归零，旧实现只扫 dev.ps1
    ⇒ 命中 0 处、触发提取器自检下限（是账过时，不是正则真失效）。
    前后值：合并前 dev.ps1 命中 0；合并后 dev.ps1 0 + JSON 31 = **31 处**（去重 **9 枚**）。
    下限 ``>=30``／``unique>=8`` **一字未抬**，由现算自然满足；复跑：
    ``pytest tests/test_dev_ps1_no_shim_module_targets.py::test_dev_ps1_target_extraction_is_not_trivial``。
    """
    return [*_dev_ps1_inline_targets(), *_task_json_targets()]


def _shim_tags_of(module: str) -> list[str]:
    """模块的垫片/不可执行标签；盘上找不到时回 MISSING_ON_DISK（由调用方判红）。"""
    path = _module_source_file(module)
    if path is None:
        return ["MISSING_ON_DISK"]
    source = path.read_text(encoding="utf-8", errors="replace")
    reportable = _SHIM_TAGS | {"MISSING_ON_DISK"}
    return [tag for tag in _module_tags(source) if tag in reportable]


def test_dev_ps1_reads_real_file():
    """守卫前提：被检文件确实在盘且非空（脚本搬家要立刻暴露，不许空转通过）。"""
    assert _DEV_PS1.is_file(), f"缺少工作区脚本：{_DEV_PS1.as_posix()}"
    assert len(_DEV_PS1.read_text(encoding="utf-8")) > 1000


def test_dev_ps1_target_extraction_is_not_trivial():
    """提取器自检（防「正则失效→零命中→假绿」）：命中数有下限，且每个目标都能解析到盘上文件。"""
    targets = _dev_ps1_targets()
    assert len(targets) >= 30, f"dev.ps1 的 -m 目标只抓到 {len(targets)} 处，提取器疑似失效"
    unique = {module for _, module in targets}
    assert len(unique) >= 8, f"-m 目标模块去重后仅 {len(unique)} 个，提取器疑似失效"
    missing = [
        f"dev.ps1:{line} → {module}"
        for line, module in targets
        if _module_source_file(module) is None
    ]
    assert not missing, f"dev.ps1 里有不存在的 -m 目标模块（断链）：{missing}"


def test_dev_ps1_module_targets_are_not_shims():
    """主门：``-m`` 打进垫片=静默 exit 0 的假成功，本门让任何一处命中即红。"""
    offenders = [
        f"dev.ps1:{line} -m {module} → {tags}（{_module_source_file(module)}）"
        for line, module in _dev_ps1_targets()
        if (tags := _shim_tags_of(module))
    ]
    assert not offenders, (
        "scripts/dev.ps1 存在「-m 打进垫片/不可执行模块」的命令行——"
        "python -m 只会静默 exit 0 并吞掉参数（假成功）。改指真身模块：\n"
        + "\n".join(sorted(set(offenders)))
    )


def _memory_sanitize_command() -> dict:
    """取 chatbot-tasks.json 里 ``memory-sanitize`` 任务的 ``python -m`` 命令节点（真身已迁 JSON）。"""
    data = json.loads(_TASKS_JSON.read_text(encoding="utf-8"))
    steps = data["tasks"]["memory-sanitize"]["steps"]
    commands = [s for s in steps if isinstance(s, dict) and s.get("type") == "command"]
    assert commands, "memory-sanitize 任务里找不到 command 步骤（搬走了？守卫前提失效）"
    return commands[-1]


def test_memory_sanitize_task_points_to_canonical_module():
    """本次缺陷的定点锁：``memory_sanitize`` 的 ``-m`` 真身必须指 canonical，旧垫片路径不得复现。

    改因（2026-09-24 席 S208，账跟随真值）：该任务的 ``-m`` 目标自 2026-09-23 从 dev.ps1 的
    ``function Invoke-MemorySanitize`` 搬进 chatbot-tasks.json（memory-sanitize 任务的 command 步），
    dev.ps1 已无此函数 ⇒ 旧实现 ``text.index("function Invoke-MemorySanitize")`` 抛
    ``ValueError: substring not found``（是账过时，非缺陷）。判据的**牙全保留**：module 必等值
    canonical 真身、``--dry-run``/``--apply`` 两支齐全、旧垫片路径在 dev.ps1 与 JSON 两处都不得残留。
    复跑：``pytest tests/test_dev_ps1_no_shim_module_targets.py::test_memory_sanitize_task_points_to_canonical_module``。
    """
    command = _memory_sanitize_command()
    rendered = json.dumps(command, ensure_ascii=False)
    assert command.get("module") == _CANONICAL_MEMORY_SANITIZE, (
        f"memory-sanitize 的 -m 目标不是 canonical 真身，实得 {command.get('module')!r}"
    )
    assert _LEGACY_MEMORY_SANITIZE not in rendered, (
        f"memory-sanitize 命令又指回旧垫片路径 {_LEGACY_MEMORY_SANITIZE}"
        "（18 行 PEP562 垫片，-m 后静默 no-op）"
    )
    assert "--dry-run" in rendered and "--apply" in rendered, (
        "memory-sanitize 的 dry-run/apply 两支参数缺口"
    )
    for src_name, src_text in (
        ("dev.ps1", _DEV_PS1.read_text(encoding="utf-8")),
        ("chatbot-tasks.json", _TASKS_JSON.read_text(encoding="utf-8")),
    ):
        assert _LEGACY_MEMORY_SANITIZE not in src_text, f"{src_name} 全文仍残留旧垫片模块路径"


def test_canonical_module_docstring_does_not_teach_shim_command():
    """真身 docstring 的「用法」不得再写 -m 垫片路径（第二层缺陷：文档教人复现假成功）。"""
    path = _module_source_file(_CANONICAL_MEMORY_SANITIZE)
    assert path is not None
    doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or ""
    taught = [m.rstrip(".") for m in _DOCSTRING_MODULE_RE.findall(doc)]
    assert taught, f"{path.name} docstring 里找不到 python -m 用法示例（示例被删掉了？）"
    bad = [f"{module} → {_shim_tags_of(module)}" for module in taught if _shim_tags_of(module)]
    assert not bad, f"docstring 用法教的是打不进真身的旧路径：{bad}"


# ---------- 运行时活性锁（垫片缺陷的正身：exit 0 但零输出） ----------


def test_memory_sanitize_cli_dry_run_actually_reports(tmp_path, capsys):
    """``-m`` 真身 CLI 必须真的产出报告——垫片式的「exit 0 + 零输出」就是本次缺陷本体。

    只读写 ``tmp_path`` 下的临时库（零 Runtime、零长期记忆接触）；apply/隔离面已由
    ``tests/test_memory_sanitize.py`` 覆盖，本用例只钉「命令行不是静默 no-op」。
    """
    import sqlite3

    from plugins.bot_unified_runtime.domains.chat_reply.security.memory_sanitize import (
        main,
    )

    db = tmp_path / "memory_cli.sqlite3"
    connection = sqlite3.connect(db)
    connection.execute(
        "CREATE TABLE memory_facts ("
        "fact_id TEXT PRIMARY KEY, subject_user_id TEXT, session_id TEXT, "
        "memory_kind TEXT, text TEXT)"
    )
    connection.execute(
        "INSERT INTO memory_facts VALUES ('f1', 'u1', 's1', 'preference', '用户喜欢喝美式咖啡')"
    )
    connection.commit()
    connection.close()

    rc = main(["--dry-run", "--db", str(db)])
    output = capsys.readouterr().out
    assert rc == 0, f"dry-run 退出码异常：{rc}"
    assert output.strip(), "CLI 静默退出（零输出）＝垫片式假成功，缺陷复发"
    assert "扫描 1 条" in output, f"dry-run 未产出可读报告：{output!r}"

    connection = sqlite3.connect(db)
    try:
        assert connection.execute("SELECT COUNT(*) FROM memory_facts").fetchone()[0] == 1
    finally:
        connection.close()


# ---------- 守卫自身的变异自检（不依赖 dev.ps1 现状） ----------

_REAL_MODULE_SRC = '''
"""真身模块。"""
import sys


def main() -> int:
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

_PEP562_SHIM_SRC = '''
"""Compat shim: module moved to plugins.x.canonical (v21r4-B reorg)."""
from importlib import import_module
from typing import Any

_CANONICAL = "plugins.x.canonical"


def __getattr__(name: str) -> Any:
    return getattr(import_module(_CANONICAL), name)
'''

_REEXPORT_SHIM_SRC = '''
"""Compat shim: moved to domains/food/capabilities/eat.py (v21r2 reorg)."""

from plugins.bot_unified_runtime.domains.food.capabilities.eat import *
'''


def test_shim_classifier_catches_both_known_shim_forms_and_passes_real_module():
    """判据本身必须有效：两种垫片形态各测必红、真身模块必绿（否则门形同虚设）。"""
    pep562 = _module_tags(_PEP562_SHIM_SRC)
    assert "PEP562_SHIM" in pep562 and "NO_MAIN_ENTRY" in pep562, pep562
    reexport = _module_tags(_REEXPORT_SHIM_SRC)
    assert "REEXPORT_SHIM" in reexport and "NO_MAIN_ENTRY" in reexport, reexport
    assert _module_tags(_REAL_MODULE_SRC) == [], _module_tags(_REAL_MODULE_SRC)


def test_real_repo_shim_is_detected_by_classifier():
    """现网取样：存量 PEP562 垫片（本次缺陷现场）必须被同一判据认出。"""
    path = _module_source_file(_LEGACY_MEMORY_SANITIZE)
    assert path is not None, "旧垫片不在盘（若已退役，请同步更新本用例与守卫说明）"
    tags = _module_tags(path.read_text(encoding="utf-8"))
    assert "PEP562_SHIM" in tags, tags
