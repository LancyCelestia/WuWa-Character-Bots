"""TG 拼格「同册只回一次」的接线锁（台账 #73，席 P9 判据＋P9b 补丁＋主会话落线）。

判据本体有单测（`tests/test_album_single_turn_p9b.py`），但**判据写了≠接上了**——
本仓点名的失效形态就是「声明在册而执法半边没接」。所以本件只回答一个问题：
根摄取路径上，`telegram_album_turn_decision` 真被调用，且 `merged=True` 那一支
**当场 return**（不进 RuntimePipeline、不触发第二次能力调用）。

反证不靠注毒改盘：同一把尺量两份源码——工作树（已接线）必须命中，
`git show HEAD~1` 那份（未接线）必须零命中。缺一条判据即本件自证为假绿。
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

REL = "plugins/bot_unified_runtime/__init__.py"
FN = "telegram_album_turn_decision"
PIPELINE_CALLS = ("pipeline", "handle_async", "RuntimePipeline")


def _tree(source: str) -> ast.Module:
    return ast.parse(source)


def _wiring_hits(tree: ast.Module) -> dict[str, bool]:
    # `from … import telegram_album_turn_decision as _x` 这种别名形必须认——
    # 根件真身就是这么写的（只认原名会把接好的线判成没接，即假红）。
    names: set[str] = {FN}
    call_found = imported_from_right_module = folded_return = guards_pipeline = False
    folded_var: str | None = None

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == FN:
                    names.add(alias.asname or alias.name)
                    if str(node.module or "").endswith("chat_reply.ingest.message_context"):
                        imported_from_right_module = True
    for node in ast.walk(tree):
        # ① 取判据的那次调用
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in names:
                call_found = True
            if folded_var and node.func.id in PIPELINE_CALLS:
                guards_pipeline = False
        # 赋值句柄：album_turn = <判据>(...)
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            if isinstance(node.value.func, ast.Name) and node.value.func.id in names:
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        folded_var = tgt.id
        # ② `if <handle>.merged:` 且体内当场 return
        if isinstance(node, ast.If) and folded_var:
            test = node.test
            if (
                isinstance(test, ast.Attribute)
                and test.attr == "merged"
                and isinstance(test.value, ast.Name)
                and test.value.id == folded_var
            ):
                body_src = ast.dump(node.body[0]) if node.body else ""
                if any(isinstance(st, ast.Return) for st in node.body) or "Return" in body_src:
                    folded_return = True
                    # ③ 这一支里不得再走管道
                    inner = "\n".join(ast.dump(st) for st in node.body)
                    guards_pipeline = not any(tok in inner for tok in PIPELINE_CALLS)
    return {
        "call": call_found,
        "import_from_central_module": imported_from_right_module,
        "folded_branch_returns": folded_return,
        "folded_branch_skips_pipeline": guards_pipeline,
    }


def _worktree_source() -> str:
    return (Path(__file__).resolve().parents[1] / REL).read_text(encoding="utf-8")


def test_worktree_root_wires_the_album_turn_decision() -> None:
    hits = _wiring_hits(_tree(_worktree_source()))
    assert hits["call"], f"根件里没人调用 {FN}＝判据写了没接（declared not enforced）"
    assert hits["import_from_central_module"], "取判据的出处不是 ingest.message_context＝第二真身"
    assert hits["folded_branch_returns"], "merged=True 一支没有当场 return＝同册仍会回 N 次"
    assert hits["folded_branch_skips_pipeline"], "折掉的那支还在往管道走＝副作用没省掉"


def test_pullng_the_wired_line_out_of_the_real_source_breaks_the_lock() -> None:
    """真件自检：在内存里把根件那条 `telegram_album_turn_decision(` 调用改掉，
    四条判据必须立刻落空——证明本件咬的是**这枚文件里的这一行**，不是空转。

    不动盘上的 `__init__.py`（共享热件，多席在写），只在字符串层面做变异。
    """
    source = _worktree_source()
    assert FN in source, "根件里连判据名字都没有＝上一腿是假绿"
    mutated = source.replace(f"{FN}(", f"{FN}_REMOVED(", 1)
    hits = _wiring_hits(_tree(mutated))
    assert not hits["call"], "摘掉调用行后仍报命中＝尺在认注释/字符串"
    assert not hits["folded_branch_returns"], "摘掉调用后折句支仍被判在 return＝判据串了别处"


def test_the_ruler_itself_has_teeth() -> None:
    """尺的自检（不靠" HEAD 里还没有"当反证——那会随提交自失效）。

    两份合成源码同尺对跑：未接线那份四条必须全空，接线那份必须全中。
    若未接线也"命中"＝这把尺在把注释/字符串当调用，上一腿一律不可信。
    """
    unwired = """
from .domains.chat_reply.ingest.message_context import telegram_album_context
async def _handle_chat(event):
    message = _incoming_from_nonebot_event(event)
    album = telegram_album_context(message)
    await pipeline.handle_async(message)
"""
    wired = """
from .domains.chat_reply.ingest.message_context import (
    telegram_album_turn_decision as _telegram_album_turn_decision,
)
async def _handle_chat(event):
    message = _incoming_from_nonebot_event(event)
    album_turn = _telegram_album_turn_decision(message)
    if album_turn.merged:
        return
    await pipeline.handle_async(message)
"""
    off = _wiring_hits(_tree(unwired))
    on = _wiring_hits(_tree(wired))
    assert not any(off.values()), f"尺瞎了：未接线源码被判成已接线 {off}"
    assert all(on.values()), f"尺漏了：接线样例没被判全 {on}"
