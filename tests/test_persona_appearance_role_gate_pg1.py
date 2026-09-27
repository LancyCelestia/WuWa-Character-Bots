"""P-G1（S-ATK-PERSONA，2026-09-27）：外观下发腿必须有角色门。

漏洞形态：`/bot runtime ...` 回执只要是 ``sent`` 就触发外观随切——但
**驳回回执同样是 sent**（非管理员跑 ``persona switch <当前生效id>`` 时
override 读回校验照样通过）⇒ 任意用户可反复驱动 bot 账号写 QQ 资料/头像。
修法＝matcher 在 runtime 能力闭包里记下本次 actor_roles，经钩子传进
``_dispatch_persona_appearance_if_switched``，非 admin/super_admin 直接不动作。

本锁按 AST 现算（不 import 根件，避免装配副作用）：四腿缺一即红——
① helper 形参含 actor_roles；② helper 体内角色判据存在且排在
apply_persona_profile 之前；③ 钩子调用点传了 actor_roles；④ runtime 分支
能力闭包把 _decision.actor_roles 写进 persona_gate_roles。
"""

from __future__ import annotations

import ast
from pathlib import Path

_ROOT = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "bot_unified_runtime"
    / "__init__.py"
)


def _tree() -> ast.Module:
    return ast.parse(_ROOT.read_text(encoding="utf-8"))


def _helper_def() -> ast.FunctionDef:
    for node in _tree().body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_dispatch_persona_appearance_if_switched"
        ):
            return node
    raise AssertionError("外观下发 helper 不在根件顶层")


def _literal_names(node: ast.AST) -> set[str]:
    # 名字与字符串常量都算「在场」——角色判据写的是 `"admin" not in roles`
    # （Constant），采集袋读的是 `_decision.actor_roles`（attr 名也是 Constant）。
    names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
    strings = {n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    return names | strings


def _call_lines(node: ast.AST, func_name: str) -> list[int]:
    return [
        call.lineno
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == func_name
    ]


def test_helper_takes_actor_roles_and_gates_before_dispatch() -> None:
    helper = _helper_def()
    params = {a.arg for a in helper.args.args} | {a.arg for a in helper.args.kwonlyargs}
    assert "actor_roles" in params, "helper 未收 actor_roles 形参"
    guard_lines = [
        node.lineno
        for node in ast.walk(helper)
        if isinstance(node, ast.Compare)
        and {"admin", "super_admin"} & _literal_names(node)
    ]
    assert guard_lines, "helper 体内没有角色判据"
    dispatch_lines = _call_lines(helper, "apply_persona_profile")
    assert dispatch_lines, "helper 未调 apply_persona_profile（结构变了，请同步本锁）"
    assert min(guard_lines) < min(dispatch_lines), "角色门排在下发之后＝永假承诺"


def test_hook_call_site_passes_actor_roles() -> None:
    calls = [
        call
        for call in ast.walk(_tree())
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "_dispatch_persona_appearance_if_switched"
    ]
    assert calls, "外观随切钩子调用点消失（结构变了，请同步本锁）"
    for call in calls:
        kwargs = {kw.arg for kw in call.keywords}
        assert "actor_roles" in kwargs, "钩子调用点没把角色面传进 helper"


def test_runtime_branch_captures_decision_roles() -> None:
    source = _ROOT.read_text(encoding="utf-8")
    assert "persona_gate_roles" in source, "matcher 未记录 actor_roles 采集袋"
    tree = ast.parse(source)
    capture = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "persona_gate_roles"
            or isinstance(target, ast.Subscript)
            and isinstance(target.value, ast.Name)
            and target.value.id == "persona_gate_roles"
            for target in node.targets
        )
        and "actor_roles" in _literal_names(node.value)
    ]
    assert capture, "没有任何一处把 _decision.actor_roles 写进 persona_gate_roles"
