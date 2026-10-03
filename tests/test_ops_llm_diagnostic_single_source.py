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


def _leaked_phrases(source_text: str) -> list[str]:
    """纯判据：源码文本里出现的诊断话术字面量清单（空＝没自抄第二份）。"""
    return [phrase for phrase in BANNED_PHRASES if phrase in source_text]


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
    leaked = _leaked_phrases(source)
    assert not leaked, f"{path.name} 里又出现诊断话术字面量 {leaked}——改回引用 diagnostics 的共享出处"


@pytest.mark.parametrize("path", CONSUMERS, ids=lambda p: p.name)
def test_consumers_import_the_shared_symbols(path: Path) -> None:
    imported = _imported_names(path)
    missing = sorted(set(SHARED_NAMES) - imported)
    assert not missing, f"{path.name} 没有 import 共享符号 {missing}（那它多半在自抄一份）"


def test_single_source_predicates_catch_synthetic_second_copy(tmp_path: Path) -> None:
    """注毒自证（原缺的那条腿）：两把尺都喂合成件证明真的会咬。

    原来两门只断言**今天这两枚真消费者**恰好没自抄、恰好 import 了——一旦判据被写坏
    （`_leaked_phrases` 恒返空 / import 检查恒过），现件照绿而「第二份实现复活」无人管
    （简报点名的 green-but-toothless）。合格样本必须不报（防尺恒红）。
    """
    dirty = tmp_path / "dirty_consumer.py"
    dirty.write_text('MSG = "请回复：诊断连接正常。"\n', encoding="utf-8")
    assert _leaked_phrases(dirty.read_text(encoding="utf-8")), "第二份诊断话术未被抓住=单源锁空跑"

    shared_import = (
        "from plugins.bot_unified_runtime.domains.ops.smoke.diagnostics import (  # noqa\n"
        "    llm_diagnostic_messages, LLM_DIAGNOSTIC_OK_MESSAGE,\n)\n"
    )
    ok = tmp_path / "ok_consumer.py"
    ok.write_text(shared_import, encoding="utf-8")
    assert _leaked_phrases(ok.read_text(encoding="utf-8")) == []
    assert set(SHARED_NAMES) - _imported_names(ok) == set(), "合格 import 被误报=尺恒红"

    dropped = tmp_path / "dropped_consumer.py"
    dropped.write_text(
        "from plugins.bot_unified_runtime.domains.ops.smoke.diagnostics import (  # noqa\n"
        "    llm_diagnostic_messages,\n)\n",
        encoding="utf-8",
    )
    assert set(SHARED_NAMES) - _imported_names(dropped) == {"LLM_DIAGNOSTIC_OK_MESSAGE"}, (
        "少 import 一枚共享符号未被抓住=import 锁空跑"
    )

    noimport = tmp_path / "noimport_consumer.py"
    noimport.write_text('MSG = "别处自抄一份"\n', encoding="utf-8")
    assert set(SHARED_NAMES) - _imported_names(noimport) == set(SHARED_NAMES), (
        "整段没 import 共享符号未被抓住=import 锁空跑"
    )
