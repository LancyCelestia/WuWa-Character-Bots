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


def _helper_contract_problems(fn: ast.AST) -> list[str]:
    """纯判据：给定一个 helper 的 AST 节点，返回它违背外观角色门契约的问题清单（空＝合格）。

    抽成纯函数，是为了让「门真的会咬人」这件事能被注毒自证——原来三条断言散在测试体里，
    只能证明**今天那一份真件**合格，证不了「谁把角色门摘掉/挪到下发之后，本锁一定红」。
    """
    problems: list[str] = []
    params = {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}
    if "actor_roles" not in params:
        problems.append("helper 未收 actor_roles 形参")
    guard_lines = [
        node.lineno
        for node in ast.walk(fn)
        if isinstance(node, ast.Compare) and {"admin", "super_admin"} & _literal_names(node)
    ]
    dispatch_lines = _call_lines(fn, "apply_persona_profile")
    if not guard_lines:
        problems.append("helper 体内没有角色判据")
    if not dispatch_lines:
        problems.append("helper 未调 apply_persona_profile（结构变了，请同步本锁）")
    if guard_lines and dispatch_lines and not min(guard_lines) < min(dispatch_lines):
        problems.append("角色门排在下发之后＝永假承诺")
    return problems


def _parse_single_fn(source: str) -> ast.FunctionDef:
    """把一段源码里的唯一顶层函数取出来（注毒用例喂合成 AST，绝不动生产件）。"""
    tree = ast.parse(source)
    fns = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert len(fns) == 1, "注毒夹具必须恰含一枚顶层函数"
    return fns[0]


def test_helper_takes_actor_roles_and_gates_before_dispatch() -> None:
    problems = _helper_contract_problems(_helper_def())
    assert not problems, "外观角色门 helper 违约：" + "；".join(problems)


def test_role_gate_lock_catches_missing_late_or_absent_guard() -> None:
    """注毒自证（原缺的那条腿）：合成 AST 里逐格破坏角色门，本锁必须逐格报红。

    没有这条腿，`_helper_contract_problems` 可能被悄悄写成 `return []`（永真摆设），
    现件照样绿——正是简报点名的「green-but-toothless」。合格件先自证尺不是恒红。
    """
    compliant = (
        "def _dispatch_persona_appearance_if_switched(message, actor_roles):\n"
        "    if 'admin' not in actor_roles:\n"
        "        return\n"
        "    apply_persona_profile(message)\n"
    )
    assert _helper_contract_problems(_parse_single_fn(compliant)) == [], "合格件被误判＝尺恒红"

    no_guard = (
        "def _dispatch_persona_appearance_if_switched(message, actor_roles):\n"
        "    apply_persona_profile(message)\n"
    )
    assert any("角色判据" in p for p in _helper_contract_problems(_parse_single_fn(no_guard))), (
        "注毒未被抓住：删掉角色门仍绿=锁是空跑"
    )

    late_guard = (
        "def _dispatch_persona_appearance_if_switched(message, actor_roles):\n"
        "    apply_persona_profile(message)\n"
        "    if 'admin' not in actor_roles:\n"
        "        return\n"
    )
    assert any("永假承诺" in p for p in _helper_contract_problems(_parse_single_fn(late_guard))), (
        "注毒未被抓住：角色门挪到下发之后仍绿"
    )

    no_param = (
        "def _dispatch_persona_appearance_if_switched(message, roles):\n"
        "    if 'admin' not in roles:\n"
        "        return\n"
        "    apply_persona_profile(message)\n"
    )
    assert any("actor_roles 形参" in p for p in _helper_contract_problems(_parse_single_fn(no_param))), (
        "注毒未被抓住：没收 actor_roles 形参仍绿"
    )

    no_dispatch = (
        "def _dispatch_persona_appearance_if_switched(message, actor_roles):\n"
        "    if 'admin' not in actor_roles:\n"
        "        return\n"
        "    log_only(message)\n"
    )
    assert any("apply_persona_profile" in p for p in _helper_contract_problems(_parse_single_fn(no_dispatch))), (
        "注毒未被抓住：不再下发外观仍绿"
    )


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
