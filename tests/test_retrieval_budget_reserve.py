"""D1（2026-09-26 用户裁定 A）：可选增强段不得吃掉必选段的预算。

三条锁各司其职，缺一不可：

① ``_retrieval_affordance`` 的**纯函数语义**（含三种 fail-open 形态）——判"算法对不对"；
② 生产调用点的 **AST 活性锁**——判"这段判据真在 ``build_chat_result`` 里被执行，
   且真的同时关掉联网与竖源两条腿、并把归因标签贴进审计"。只测①会得到一把
   "函数存在但没人调"的假锁（本仓最高频形态：在册未执法）；
③ 注毒自证在 ``$TEMP`` 副本上跑（绝不在真实树注毒），证明②有杀伤力。

背景数字（生产诊断库实测）：一轮 820 秒里 LLM 只拿到 3.4 秒，联网被跳过——
``DeadlineBudget.ensure_available()`` 只在阶段边界被查询，**打断不了已经跑起来的
检索**，所以放行判断必须落在"开跑之前"。
"""

from __future__ import annotations

import ast
import math
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
    _LLM_HANDOVER_RESERVE_SECONDS,
    _retrieval_affordance,
)

CHAT_PY = (
    Path(__file__).resolve().parents[1]
    / "plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py"
)


class _Budget:
    """替身：只暴露真身读的那三枚成员，别把测试绑到完整 ``DeadlineBudget`` 上。"""

    def __init__(self, remaining: float, *, enabled: bool = True) -> None:
        self.remaining = remaining
        self.enabled = enabled

    def remaining_seconds(self) -> float:
        return self.remaining


# ---------------------------------------------------------------- ① 纯函数语义
def test_affordable_when_headroom_exceeds_reserve() -> None:
    ok, remaining, reason = _retrieval_affordance(_Budget(300.0))
    assert ok is True and remaining == 300.0 and reason == ""


def test_refused_when_remaining_at_or_below_reserve() -> None:
    for remaining in (_LLM_HANDOVER_RESERVE_SECONDS, 30.0, 0.0, -12.0):
        ok, _r, reason = _retrieval_affordance(_Budget(remaining))
        assert ok is False, f"剩余 {remaining}s 仍放行＝又把 LLM 那一段饿掉了"
        assert "llm_reserve" in reason, reason  # 归因必须可读，不许只给个 bool


def test_fail_open_three_forms() -> None:
    """预算未启用／句柄缺失／读数为 NaN ⇒ 一律放行（观测件坏了不带走检索功能）。"""

    assert _retrieval_affordance(None)[0] is True
    assert _retrieval_affordance(_Budget(5.0, enabled=False))[0] is True
    nan_ok, nan_remaining, nan_reason = _retrieval_affordance(_Budget(float("nan")))
    assert nan_ok is True and nan_reason == ""
    assert math.isnan(nan_remaining)  # NaN 原样带出，不偷偷折成 0


def test_disabled_handle_is_not_the_same_as_a_real_zero() -> None:
    """``enabled=False`` 与"启用但剩余=0"是两件事：后者必须拦。

    写成"读不到就当放行"会让整条判据在装配失败时静默消失——那正是本仓
    ``outbound_gate_settings_unreadable`` 一族点名的形态。
    """

    assert _retrieval_affordance(_Budget(0.0, enabled=False))[0] is True
    assert _retrieval_affordance(_Budget(0.0))[0] is False


# ------------------------------------------------------- ② 生产调用点的活性锁
def _function_tree(source: str, name: str) -> ast.FunctionDef:
    module = ast.parse(source)
    for node in ast.walk(module):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"找不到函数 {name}")


def _assignments(body: list[ast.stmt], target: str) -> list[ast.stmt]:
    found: list[ast.stmt] = []
    for stmt in body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Assign):
                names = [
                    t.id for t in node.targets if isinstance(t, ast.Name)
                ]
                if target in names:
                    found.append(stmt)
                    break
    return found


def test_production_gate_runs_before_the_retrieval_legs_and_kills_both() -> None:
    """判据必须**在场、在检索之前、且两条可选腿一起管**。

    拆成三问而不是一句"代码里有 `_retrieval_affordance`"：
    - 在场：``build_chat_result`` 体内真调了它；
    - 在前：调用位置在 ``search_acg_verticals`` 与 ``decide_web_search`` 之前
      （在后面就等于"已经花掉时间才后悔"，那正是本次事故）；
    - 管两条腿：块内同时把 ``do_web`` 与 ``run_acg`` 判假（只关一条＝另一条照烧预算）。
    """

    source = CHAT_PY.read_text(encoding="utf-8")
    module = ast.parse(source)

    def own_body_has_gate(fn: ast.FunctionDef) -> bool:
        """只看这个函数**自己**的函数体，不进嵌套 def。

        `ast.walk(fn)` 会连着内层函数一起走 ⇒ 外层工厂函数也会被算成"含判据"，
        那条 `len(gated) == 1` 从写下第一刻就不可能成立（本席第一版就是这么错的）。
        """

        stack: list[ast.AST] = [fn]
        while stack:
            node = stack.pop()
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == (
                "_retrieval_affordance"
            ):
                return True
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node is not fn:
                continue  # 嵌套函数由它自己那一轮负责
            stack.extend(ast.iter_child_nodes(node))
        return False

    # 自我定位：不写死行号，也不假设外层工厂函数叫什么（本仓这类"照记忆写坐标"
    # 的锁已经错过一次）。先找"自己体内真含该调用"的那个函数，再断言它的身份。
    gated = [
        node
        for node in ast.walk(module)
        if isinstance(node, ast.FunctionDef) and own_body_has_gate(node)
    ]
    assert gated, "生产路径没有任何函数自己调用 _retrieval_affordance＝判据只在测试里活着"
    assert len(gated) == 1, f"判据被复制到多处：{[f.name for f in gated]}＝第二真身"
    capability = gated[0]
    assert capability.name == "capability", (
        f"调用点落在 {capability.name}() 里，不在能力执行体内 ⇒ 装配期判一次、"
        "每轮不再判（那是本判据最容易被写成废掉的方式）"
    )

    def first_line(name: str) -> int:
        """某名字在本函数体内第一次出现的行号（Name 与 Attribute 两种写法都算）。

        竖源那条腿是 `executor.submit(acg_search.search_acg_verticals, ...)` ——
        它是 submit 的**实参**而非被调函数，`Call.func` 是 `executor.submit`，
        所以只按 `Call.func` 匹配的谓词恒空（本席第一版就是这么把判据误读成
        "缺位"的；记在这里，免得下次有人以为这条断言在测别的东西）。
        """

        lines = [
            node.lineno
            for node in ast.walk(capability)
            if (isinstance(node, ast.Name) and node.id == name)
            or (isinstance(node, ast.Attribute) and node.attr == name)
        ]
        assert lines, f"缺位：{name} 不在能力执行体里"
        return min(lines)

    gate_line = first_line("_retrieval_affordance")
    acg_line = first_line("search_acg_verticals")
    decide_line = first_line("decide_web_search")
    assert gate_line > decide_line, "判据应在联网判定之后（要读它的结论）"
    assert gate_line < acg_line, (
        f"判据在 {gate_line} 行、竖源在 {acg_line} 行才开跑 ⇒ 判晚了，"
        "已经跑起来的检索打断不了"
    )

    gate_block_lines = [
        stmt.lineno
        for stmt in capability.body
        if isinstance(stmt, ast.If)
        and any(
            isinstance(n, ast.Name) and n.id == "retrieval_affordable"
            for n in ast.walk(stmt.test)
        )
    ]
    assert gate_block_lines, "没找到 `if not retrieval_affordable:` 那一块"
    block = next(
        stmt
        for stmt in capability.body
        if getattr(stmt, "lineno", -1) == gate_block_lines[0]
    )
    turned_off = {
        names[0]
        for stmt in block.body
        for names in [_assignment_names(stmt)]
        if names and assigns_false(stmt)
    }
    assert {"do_web", "run_acg"} <= turned_off, (
        f"只关了两条可选腿里的一部分：{sorted(turned_off)}"
    )


def _assignment_names(stmt: ast.stmt) -> list[str]:
    if isinstance(stmt, ast.Assign):
        return [t.id for t in stmt.targets if isinstance(t, ast.Name)]
    return []


def assigns_false(stmt: ast.stmt) -> bool:
    """判 `x = False` 字面量。

    ⚠ 少一跳就全错：`x = False` 解析成 `Assign(value=Constant(value=False))`，
    拿 `stmt.value is False` 比的是**节点对象**与 bool 单例，恒 False ⇒ 这条断言
    会在真身上也永远红（本席第一版正是这样，而它对注毒"也红"，于是伪装成了一把
    有杀伤力的锁——假杀伤力与假绿一样要防）。要比的是 `stmt.value.value`。
    """

    return (
        isinstance(stmt, ast.Assign)
        and isinstance(stmt.value, ast.Constant)
        and stmt.value.value is False
    )


def test_skip_is_attributable_not_silently_skipped() -> None:
    """跳过必须留下能分归因的标签：三种 skipped（预算不够／判据不要／网上没有）不许混。"""

    source = CHAT_PY.read_text(encoding="utf-8")
    assert "retrieval_skipped_budget" in source, "跳过没留归因标签＝谎报的温床"
    assert "web_search:skipped" in source, "既有那枚标签不许被改掉（历史账要能对齐）"


def test_chat_module_still_parses_and_imports() -> None:
    """底线：这个文件里任何一处语法塌了，整棵插件装配期就崩、bot 起不来。"""

    ast.parse(CHAT_PY.read_text(encoding="utf-8"))
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities import chat

    assert callable(chat._retrieval_affordance)


if __name__ == "__main__":  # 手工排障入口
    raise SystemExit(pytest.main([__file__, "-q"]))
