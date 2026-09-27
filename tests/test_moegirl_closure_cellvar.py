"""萌百问句闭包的 cellvar 遮蔽锁（2026-09-27 生产 NameError 根修）。

根修对象：`plugins/bot_unified_runtime/__init__.py` 的 `_handle_moegirl_question`。

崩形（生产实况 2026-09-27 12:29，`bot.moegirl:NameError`，排查编号
dbg_0e786373fac9，另有 2 条同类被 300 秒抑制器压住）：

    File "plugins/bot_unified_runtime/__init__.py", line 9867, in capability
        return CapabilityResult(
    NameError: cannot access free variable 'CapabilityResult' where it is not
    associated with a value in enclosing scope

机制：函数体内「`if kb_body:` 分支里」再 `from ...contracts import CapabilityResult,...`
这四枚名——Python 只看**有没有绑定语句**，不看它在哪个分支，于是把名字绑成
`_handle_moegirl_question` 的 **cellvar**，并遮蔽模块级同一份导入。内层闭包
`capability()` 于是按 **freevar** 去外层要这个名字。走到「本地库未命中 + 萌百命中主词条」
这一格时那条分支根本没跑 ⇒ cell 未填 ⇒ 闭包当场炸。**ruff F821 不报**（名字确实有绑定），
静态门全绿而线上这条路 18 天没被走到（只有这一格必炸，显式 `萌娘百科 <词条>` 与
降级转 chat 两条路径都无恙）。

同型写法在 `__init__.py` 里另扫出 16 处（如 `_handle_chat@8566` 的 `_CR/_PL/_RL/_SP`
lambda），本文件只钉萌百这一格并留一处整文件普查的点名，不替其余站点降账。
"""

from __future__ import annotations

import ast
from pathlib import Path

_SOURCE = Path(__file__).resolve().parents[1] / "plugins" / "bot_unified_runtime" / "__init__.py"
_HOST_FUNCTION = "_handle_moegirl_question"
# 这四枚名在模块级 23-36 行已导入，函数体内重复导入＝遮蔽 + cellvar 化。
_CONTRACT_NAMES = ("CapabilityResult", "PrivacyLevel", "RiskLevel", "SendPolicy")


def _module_ast() -> ast.Module:
    return ast.parse(_SOURCE.read_text(encoding="utf-8"))


def _host_function(tree: ast.Module) -> ast.FunctionDef:
    for node in ast.walk(tree):
        # async def 编译成「包裹函数 + 协程」两个码对象，AST 侧同理两种节点——
        # 只匹配 FunctionDef 会把 async 宿主整个看漏（本锁第一版就栽在这里）。
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == _HOST_FUNCTION:
            return node
    raise AssertionError(f"{_HOST_FUNCTION} 不在了——本锁的前提被换掉，请连同修法一起复核")


def test_host_function_body_has_no_contract_import() -> None:
    """宿主函数体内**任何位置**都不许再导入那四枚契约名。

    这是根修的判据本体：分支内导入即使只在一条路径上执行，也会把名字绑成
    cellvar 并遮蔽模块级导入——「看起来更省」的写法正是崩因。
    """
    host = _host_function(_module_ast())
    offenders: list[str] = []
    for node in ast.walk(host):
        if isinstance(node, ast.ImportFrom):
            bound = {alias.name for alias in node.names}
            hit = bound & set(_CONTRACT_NAMES)
            if hit:
                offenders.append(f"L{node.lineno} from {node.module} 导入 {sorted(hit)}")
    assert not offenders, (
        "契约名不得在函数体内重复导入（会造成 cellvar 遮蔽，分支不跑即 NameError）：\n"
        + "\n".join(offenders)
    )


def test_nested_capability_closure_does_not_freevar_contract_names() -> None:
    """编译后实证：内层 `capability` 码对象不许把契约名当 freevar 取用。

    注毒反证（本锁的杀伤力）：把修法回退成「在 `if kb_body:` 里重新 import 那四枚」
    ⇒ `CapabilityResult` 立刻进 `co_freevars` ⇒ 本条必红。字节码层面的判据不依赖
    分支是否执行，所以它不会被「这次恰好走到命中分支」糊过去。
    """
    code = compile(_SOURCE.read_text(encoding="utf-8"), str(_SOURCE), "exec")

    def _walk(obj):
        yield obj
        for const in obj.co_consts:
            if hasattr(const, "co_consts"):
                yield from _walk(const)

    hosts = [c for c in _walk(code) if c.co_name == _HOST_FUNCTION]
    assert hosts, f"字节码里找不到 {_HOST_FUNCTION}（函数被改名或内联了？）"
    host = hosts[0]
    # 判据只认 co_freevars：闭包里 CapabilityResult 是**外层 cell**，它不进
    # co_names（那张表只装全局名）。用 co_names 筛靶子会把真凶整个筛掉——
    # 本锁第一版就栽在这里，故此处显式不按 co_names 过滤。
    nested = [c for c in _walk(host) if c is not host and c.co_name == "capability"]
    assert nested, "内层 capability 闭包不在了——本锁失去靶子，请复核是不是被重构成别的形状"
    for inner in nested:
        leaked = sorted(set(inner.co_freevars) & set(_CONTRACT_NAMES))
        assert not leaked, f"内层 capability 把契约名当 freevar 取用（cellvar 遮蔽回潮）：{leaked}"
        assert not (set(host.co_cellvars) & set(_CONTRACT_NAMES)), (
            f"宿主函数把契约名绑成了 cellvar：{sorted(set(host.co_cellvars) & set(_CONTRACT_NAMES))}"
        )
