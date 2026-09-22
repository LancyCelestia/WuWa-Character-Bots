"""LLM 连接诊断话术只准有一个出处（2026-09-22 统一波）。

收编前 `admin/debug.py` 与 `smoke/smoke.py` 各抄一份同样的提示词与回执，被
`tests/test_copy_single_source.py` 抓成 `ops-diag` 簇；收编时那三簇从普查登记面摘掉，
普查门因此**不再盯这件事**——本件补上的就是这一格：把"别再加第二份"变成常驻判据。

判据只认 AST 与现读，不靠"记得改回来"。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = REPO_ROOT / "plugins" / "bot_unified_runtime"
HOME = PACKAGE / "domains/ops/smoke/diagnostics.py"
CONSUMERS = (
    PACKAGE / "domains/ops/admin/debug.py",
    PACKAGE / "domains/ops/smoke/smoke.py",
)
#: 曾经被双写的三句话（诊断话术本体）。任何一处再出现字面量＝第二份实现复活。
BANNED_PHRASES = (
    "你是本地 LLM 连接诊断请求",
    "请回复：诊断连接正常。",
    "LLM 诊断通过。",
)
SHARED_NAMES = ("llm_diagnostic_messages", "LLM_DIAGNOSTIC_OK_MESSAGE")


def _imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("smoke.diagnostics"):
            names |= {alias.name for alias in node.names}
    return names


def test_home_module_owns_the_copy() -> None:
    from plugins.bot_unified_runtime.domains.ops.smoke import diagnostics

    messages = diagnostics.llm_diagnostic_messages()
    assert [m["role"] for m in messages] == ["system", "user"], messages
    assert diagnostics.LLM_DIAGNOSTIC_SYSTEM_PROMPT.startswith("你是本地 LLM 连接诊断请求")
    assert diagnostics.LLM_DIAGNOSTIC_USER_PROMPT == "请回复：诊断连接正常。"
    assert diagnostics.LLM_DIAGNOSTIC_OK_MESSAGE == "LLM 诊断通过。"
    # 每次调用给新列表：调用方就地改 messages 不许污染下一次诊断
    messages.append({"role": "user", "content": "x"})
    assert len(diagnostics.llm_diagnostic_messages()) == 2


@pytest.mark.parametrize("path", CONSUMERS, ids=lambda p: p.name)
def test_consumers_hold_no_second_copy(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    leaked = [phrase for phrase in BANNED_PHRASES if phrase in source]
    assert not leaked, f"{path.name} 里又出现诊断话术字面量 {leaked}——改回引用 diagnostics 的共享出处"


@pytest.mark.parametrize("path", CONSUMERS, ids=lambda p: p.name)
def test_consumers_import_the_shared_symbols(path: Path) -> None:
    imported = _imported_names(path)
    missing = sorted(set(SHARED_NAMES) - imported)
    assert not missing, f"{path.name} 没有 import 共享符号 {missing}（那它多半在自抄一份）"
