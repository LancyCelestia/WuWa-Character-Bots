"""能力真身册迁移的**等值证明量具**（中央调度收编波 S10，2026-09-24）.

一句话：把「若把唯一在册表 ``CAPABILITY_DESCRIPTOR`` 搬进 ``domains/core/capability_manifest.py``、
再以册为源投影回现表，两侧是否逐字段等值」这句话变成可复跑的差集，而不是口头承诺。

零运行时 import（与 ``scripts/central_seam_census.py`` / ``scripts/board_doc_sync.py`` 同一哲学）：
本件只用 ``ast`` 静态解析三份真身，不 ``import plugins.…``、不起 bot、不读 config、不碰网络。
因此它**看得见代码形状**、看不见 ``__pycache__`` 里的旧字节码，也不被运行时覆盖层污染。

## 它到底在比什么（两侧定义，别混）
  侧 A「今日表」= 静态重现 ``capability_protocols.py::_build_capability_descriptor()``
    （:2741-2844）的产物——五路输入取并集派生的 ``CapabilityRegistration`` 行集。
  侧 B「迁移后册」= 把侧 A 的每一行按 dataclass 声明序**写成字面量**，落进册，
    再从那份字面量**解析回来**（生成 → ``ast.parse`` → 求值 = 真往返，不是自我宣布）。
  差集 = 逐字段比较 (值, 出处类别, 书写状态)。

## 为什么"值相等"不够（本件存在的全部理由）
搬家常识级陷阱在这张表上全是现成的：**值相等但账已经改了**。所以每条字段还带一列
``provenance``：``literal`` / ``const-folded`` / ``enum-member`` / ``derived-code``（由代码算出，
如 ``gate_feature_id``、route 行的 ``handler_ref`` 兜底串）/ ``default-not-written``（调用点根本没写，
靠 dataclass 缺省）。搬家把 ``derived-code`` 写成字面量 = **派生升格为复制**，今后输入源变了它不动，
这正是"第二真身"的生成方式；把 ``default-not-written`` 写成字面量 = 文本变了、值没变。
两种都必须显式点名，不许并进"等值"里。

## 输出与退出码
  ``--report``（缺省）人类可读；``--json`` 机器形态（同数据，不是第二套判据）。
  退出码：**0 = 零差集**；**2 = 有差集**（含"不可字面搬运"项——搬不动就是差，不算通过）；
  3 = 量具自身失明（三份真身任一读不出/解析不了 ⇒ 整件红，绝不降级成"没扫到=没问题"）。
  ``--census-json`` 可选：吃 ``scripts/central_seam_census.py --json`` 的快照，
  与本件的在册 id 全集做**双向差集**——用第二把独立的尺子夹住本件的派生重现，
  防止"我自己派生、我自己对比"的同义反复假绿。

## 本件的两处自我限制（如实，别当已证）
 1. 侧 A 是**独立重实现**的派生逻辑（按 :2741-2844 逐条抄写语义）。它与生产函数可能同错同对。
    唯一的外部夹子是 ``--census-json`` 的 id 全集对账 + 下方打印的 ``assumptions`` 清单
    （解释器跳过的守卫/无法求值的表达式，逐条列出，不静默）。
 2. 求值器只覆盖本三件实际用到的表达式形态；任何求不出的一律记 ``unresolved`` 并升级为差集，
    **不猜值**。

## CM-P-9 前置改造（S44，2026-09-24：P2「降为再导出垫片」之前先修眼睛）
 - ``load_module`` 现把 ``from X import Y``（含 ``Y as Y`` / 包内星号形）**顺链追到真身文件**
   再充实常量表，追证逐条进 ``assumptions`` 清单；注册表降为薄壳后本件不再 KeyError/读空。
 - ``module_exports`` 三改：再导出计入公开导出面（旧版纯壳=假账空面）；读不出/解析失败
   **点名抛**（旧版静默返回空集）；空面抛（三处旧账今日皆数十枚符号，空=壳读壳）。
 - 塌陷锁：注册册五表缺名/零行、册侧四件求值 ``Unresolved`` ⇒ ``[FATAL]`` 点名文件与表名，
   绝不降级成"没扫到=没问题"。合法可空的 ``PLACEHOLDER_UNIMPLEMENTED`` 只禁 Unresolved。
 - 同波根修：求值器不认 ``frozenset()`` 零参空构造 ⇒ 册摘牌后 ``run()`` 在 ``_crosscheck``
   直接 TypeError（本席接手前实测崩在盘上，归因为 2026-09-23T23:06Z 摘牌波与 S10 量具的
   接缝，非本席引入）。
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

VERSION = "0.1.1-s44-cm9"

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG_ROOT = REPO_ROOT / "plugins" / "bot_unified_runtime"

PROTOCOLS = PKG_ROOT / "runtime" / "capability_protocols.py"
REGISTRY = PKG_ROOT / "domains" / "chat_reply" / "runtime" / "capability_registry.py"
MANIFEST = PKG_ROOT / "domains" / "core" / "capability_manifest.py"
TAGS = PKG_ROOT / "domains" / "core" / "channel_capability_tags.py"
TAXONOMY = PKG_ROOT / "domains" / "core" / "board_taxonomy.py"

GATE = REPO_ROOT / "tests" / "test_capability_manifest_gate.py"

REQUIRED_SOURCES = (PROTOCOLS, REGISTRY, MANIFEST)

#: 降为再导出垫片时须对账的三处旧账（任务书第 2 项）。
LEGACY_LEDGERS: dict[str, Path] = {
    "capability_registry": REGISTRY,
    "board_taxonomy": TAXONOMY,
    "channel_capability_tags": TAGS,
}

#: 唯一在册表一行的字段（顺序=dataclass 声明序；本件从 AST 现读，此元组只做交叉自检）。
REGISTRATION_FIELDS_EXPECTED = (
    "capability_id", "title", "handler_ref", "health_probe", "health_default",
    "fallbacks", "timeout_seconds", "family", "gate_feature_id", "routes",
    "help_topics", "interface_id", "authored_by",
)

# 出处类别（provenance）：值相等但这一列变了，就是"搬家改了账"。
P_LITERAL = "literal"
P_CONST = "const-folded"
P_ENUM = "enum-member"
P_DERIVED = "derived-code"
P_DEFAULT = "default-not-written"
P_UNRESOLVED = "unresolved"

# ============================================================================
# 值域：三种带出处的包装 + 一个不可求值哨兵
# ============================================================================


@dataclass(frozen=True)
class Unresolved:
    """求不出来的表达式——保留源码文本，绝不猜值。"""

    text: str

    def __repr__(self) -> str:  # pragma: no cover - 只在报告里出现
        return f"<UNRESOLVED {self.text}>"


@dataclass(frozen=True)
class EnumMember:
    """枚举成员。**比较只看 (owner, name)**：成员携带的 value 只在往返两侧由不同代码填充
    （侧 A 从 dataclass 缺省注解拿不到 value、侧 B 从枚举类表拿得到），
    把它纳入比较会把"往返工具的差别"误报成"搬家改了账"。
    """

    owner: str
    name: str
    value: Any = field(default=None, compare=False)


@dataclass(frozen=True)
class EnumClass:
    name: str
    members: tuple[tuple[str, Any], ...]

    def by_value(self, value: Any) -> EnumMember | None:
        for name, member_value in self.members:
            if member_value == value:
                return EnumMember(self.name, name, member_value)
        return None

    def by_name(self, name: str) -> EnumMember | None:
        for member_name, member_value in self.members:
            if member_name == name:
                return EnumMember(self.name, member_name, member_value)
        return None


@dataclass(frozen=True)
class Record:
    """一次 dataclass 构造的产物（含"调用点到底写没写这一列"的信息）。"""

    cls: str
    values: tuple[tuple[str, Any], ...]
    written: frozenset[str]

    def get(self, name: str) -> Any:
        for key, value in self.values:
            if key == name:
                return value
        return None

    def has(self, name: str) -> bool:
        return name in self.written


@dataclass(frozen=True)
class ModuleRef:
    """一个被 ``import x as y`` 绑定进来的模块命名空间（用于 ``_registry.TABLE`` 形态）。

    只带模块名：常量表由 ``Evaluator.modules`` 按名字查，避免这里再存一份可过期的副本。
    """

    name: str


class Fn:
    """一个可调用条目：既可能是"单 return 表达式"的纯函数（``_f`` / ``_read``），
    也可能是含循环/赋值的派生函数（``_route_execution_rows``）——后者由 ``call_pure``
    委托给 ``Interpreter``，绝不在这里静默交出 0 行。"""

    def __init__(self, node: ast.FunctionDef) -> None:
        self.node = node
        self.name = node.name


@dataclass
class Ctx:
    notes: list[str] = field(default_factory=list)

    def note(self, text: str) -> None:
        if text not in self.notes:
            self.notes.append(text)


# ============================================================================
# 模块骨架：常量表 + dataclass 字段表 + 枚举表 + 函数表
# ============================================================================


@dataclass
class ModuleFacts:
    path: Path
    tree: ast.Module
    consts: dict[str, ast.expr] = field(default_factory=dict)
    declared_at: dict[str, int] = field(default_factory=dict)
    dataclasses: dict[str, list[tuple[str, ast.expr | None]]] = field(default_factory=dict)
    enums: dict[str, EnumClass] = field(default_factory=dict)
    functions: dict[str, ast.FunctionDef] = field(default_factory=dict)
    class_refs: set[str] = field(default_factory=set)
    imports: dict[str, str] = field(default_factory=dict)  # 本地名 -> 末段模块名
    # CM-P-9（S44）：模块级再导出的账目，供 load 时顺链追真身
    rebinds: dict[str, tuple[str, str | None, int]] = field(default_factory=dict)  # 本地名 -> (真名, 模块, level)
    star_reexports: list[tuple[str | None, int]] = field(default_factory=list)  # (模块, level)
    reexport_origin: dict[str, str] = field(default_factory=dict)  # 本地名 -> "真身相对路径:行号"

    @property
    def rel(self) -> str:
        try:
            return self.path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            return str(self.path)  # 合成件（往返用的假册）不在仓内，直接给名


_MAX_REEXPORT_CHAIN = 12


def _resolve_import_source(from_file: Path, module: str | None, level: int) -> Path | None:
    """import 语句 → 仓内真实 .py；解析不到（仓外/stdlib）返回 None，绝不猜.

    相对导入沿 from_file 上跳；绝对导入依次试仓库根 / ``plugins/`` / 包根三锚点
    （本仓包内互引实况是 ``from plugins.bot_unified_runtime.…``）。
    """
    target: Path | None
    if level >= 1:
        base = from_file.parent
        for _ in range(level - 1):
            base = base.parent
        target = base.joinpath(*module.split(".")) if module else base
    else:
        if not module:
            return None
        parts = module.split(".")
        target = None
        for anchor in (REPO_ROOT, REPO_ROOT / "plugins", PKG_ROOT):
            candidate = anchor.joinpath(*parts)
            if candidate.with_suffix(".py").is_file() or candidate.is_dir():
                target = candidate
                break
    if target is None:
        return None
    if target.is_dir():
        init = target / "__init__.py"
        return init if init.is_file() else None
    py = target.with_suffix(".py")
    return py if py.is_file() else None


def load_module(path: Path, ctx: Ctx) -> ModuleFacts:
    return _load_module_cached(path, ctx, {}, frozenset())


def _load_module_cached(path: Path, ctx: Ctx, cache: dict[Path, ModuleFacts],
                        chain: frozenset[str]) -> ModuleFacts:
    cached = cache.get(path)
    if cached is not None:
        return cached
    key = str(path.resolve()).lower()
    if key in chain or len(chain) > _MAX_REEXPORT_CHAIN:
        ctx.note(f"CM-P-9 追再导出：{path} 在链上重复或链超限，此路不充实（缺表由使用侧塌陷锁点名）")
        return ModuleFacts(path=path, tree=ast.parse(""))
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(text)
    except (OSError, SyntaxError) as exc:
        raise SystemExit(f"[FATAL] 真身读不出/解析失败 {path}: {exc}") from exc
    facts = ModuleFacts(path=path, tree=tree)
    cache[path] = facts
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            facts.consts.setdefault(node.targets[0].id, node.value)
            facts.declared_at.setdefault(node.targets[0].id, node.lineno)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            facts.consts.setdefault(node.target.id, node.value)
            facts.declared_at.setdefault(node.target.id, node.lineno)
        elif isinstance(node, ast.FunctionDef):
            facts.functions[node.name] = node
            facts.declared_at.setdefault(node.name, node.lineno)
        elif isinstance(node, ast.ImportFrom):
            # CM-P-9（S44）：模块级 `from X import Y` 是薄壳的全部形态——记账，load 末追真身。
            for alias in node.names:
                if alias.name == "*":
                    facts.star_reexports.append((node.module, node.level))
                else:
                    facts.rebinds.setdefault(alias.asname or alias.name,
                                             (alias.name, node.module, node.level))
        elif isinstance(node, ast.ClassDef):
            facts.declared_at.setdefault(node.name, node.lineno)
            facts.class_refs.add(node.name)
            fields_list: list[tuple[str, ast.expr | None]] = []
            members: list[tuple[str, Any]] = []
            for sub in node.body:
                if isinstance(sub, ast.AnnAssign) and isinstance(sub.target, ast.Name):
                    fields_list.append((sub.target.id, sub.value))
                elif (isinstance(sub, ast.Assign) and len(sub.targets) == 1
                      and isinstance(sub.targets[0], ast.Name)
                      and isinstance(sub.value, ast.Constant)):
                    members.append((sub.targets[0].id, sub.value.value))
            # `class X(str, Enum): MEMBER = "value"` 的成员是**裸赋值**、无注解：
            # 只按 AnnAssign 收成员会把三枚枚举（EntryKind/CapabilityTag/CapabilityFamily…）
            # 整个看成"不可求值的类"，进而让以它们为参数的构造全判 unresolved。
            if any("Enum" in _unparse(base) for base in node.bases):
                for name, default in fields_list:
                    if isinstance(default, ast.Constant):
                        members.append((name, default.value))
                if members:
                    facts.enums[node.name] = EnumClass(node.name, tuple(members))
            if fields_list:
                facts.dataclasses[node.name] = fields_list
    _follow_reexported_consts(facts, ctx, cache, chain | {key})
    return facts


def _follow_reexported_consts(facts: ModuleFacts, ctx: Ctx,
                              cache: dict[Path, ModuleFacts], chain: frozenset[str]) -> None:
    """CM-P-9 追再导出：本文件缺的名，若由模块级 import 绑定且真身在仓内 ⇒ 充实其常量表.

    这里**只增补、不裁决**：追不到（仓外、名字其实是函数/类、成环）都不报错——
    "某张表读不出"的红由使用侧塌陷锁（run() 的注册册五表检查 / module_exports 空面锁）
    点名文件与表名来发，本函数不存在"解析不到就当表为空"的出口。
    """
    if not facts.rebinds and not facts.star_reexports:
        return
    for local, (orig, module, level) in facts.rebinds.items():
        if local in facts.consts:
            continue
        source = _resolve_import_source(facts.path, module, level)
        if source is None:
            continue
        sub = _load_module_cached(source, ctx, cache, chain)
        node = sub.consts.get(orig)
        if node is not None:
            facts.consts[local] = node
            facts.reexport_origin[local] = f"{sub.rel}:{sub.declared_at.get(orig, 0)}"
            ctx.note(f"CM-P-9 追再导出：{facts.rel}.{local} ← {facts.reexport_origin[local]}")
    for module, level in facts.star_reexports:
        source = _resolve_import_source(facts.path, module, level)
        if source is None:
            continue
        sub = _load_module_cached(source, ctx, cache, chain)
        for name, node in sub.consts.items():
            if name.startswith("_") or name in facts.consts:
                continue
            facts.consts[name] = node
            facts.reexport_origin[name] = f"{sub.rel}:{sub.declared_at.get(name, 0)}（星号）"
            ctx.note(f"CM-P-9 追再导出（星号）：{facts.rel}.{name} ← {facts.reexport_origin[name]}")


# ============================================================================
# 表达式求值器（只求本三件真身实际用到的形态；求不出即 Unresolved）
# ============================================================================

_ORDER = {P_LITERAL: 0, P_ENUM: 1, P_CONST: 2, P_DERIVED: 3, P_UNRESOLVED: 4}


class Evaluator:
    def __init__(self, modules: dict[str, ModuleFacts], ctx: Ctx) -> None:
        self.modules = modules
        self.ctx = ctx

    # -- 名字解析 ---------------------------------------------------------
    def _module_for(self, name: str, env: dict[str, Any]) -> ModuleFacts | None:
        target = env.get(name)
        if isinstance(target, ModuleRef):
            for facts in self.modules.values():
                if facts.path.name.removesuffix(".py") == target.name or facts.rel.endswith(
                        "/" + target.name + ".py"):
                    return facts
        return None

    def resolve_const(self, facts: ModuleFacts, name: str, env: dict[str, Any],
                      stack: frozenset[str] = frozenset()) -> tuple[Any, str]:
        node = facts.consts.get(name)
        if node is None:
            return Unresolved(f"{facts.rel}:{name}（非模块级字面量）"), P_UNRESOLVED
        if name in stack:
            return Unresolved(f"cycle:{name}"), P_UNRESOLVED
        return self.eval_node(node, {}, facts, stack | {name})

    # -- 主入口 -----------------------------------------------------------
    def eval_node(self, node: ast.expr, env: dict[str, Any], facts: ModuleFacts,
                  stack: frozenset[str] = frozenset()) -> tuple[Any, str]:
        if isinstance(node, ast.Constant):
            return node.value, P_LITERAL

        if isinstance(node, ast.Name):
            if node.id in env:
                value = env[node.id]
                if isinstance(value, EnumClass):
                    return value, P_ENUM
                return value, P_DERIVED
            if node.id in facts.enums:
                return facts.enums[node.id], P_ENUM
            if node.id in facts.functions:
                return Fn(facts.functions[node.id]), P_DERIVED
            if node.id in facts.class_refs:
                return Unresolved(f"class:{node.id}"), P_UNRESOLVED
            module_name = facts.imports.get(node.id)
            if module_name:
                for other in self.modules.values():
                    if other.path.name.removesuffix(".py") == module_name:
                        return ModuleRef(module_name), P_DERIVED
            return self.resolve_const(facts, node.id, env, stack)

        if isinstance(node, ast.Attribute):
            base, _base_kind = self.eval_node(node.value, env, facts, stack)
            if isinstance(base, Record):
                return base.get(node.attr), P_DERIVED
            if isinstance(base, ModuleRef):
                for other in self.modules.values():
                    if other.path.name.removesuffix(".py") == base.name:
                        value, kind = self.resolve_const(other, node.attr, env, stack)
                        return value, kind
                return Unresolved(f"module:{base.name}.{node.attr}"), P_UNRESOLVED
            if isinstance(base, EnumClass):
                member = base.by_name(node.attr)
                return (member if member is not None else
                        Unresolved(f"{base.name}.{node.attr}")), P_ENUM
            if isinstance(base, EnumMember) and node.attr == "value":
                return base.value, P_ENUM
            if isinstance(base, Unresolved):
                return Unresolved(f"{base.text}.{node.attr}"), P_UNRESOLVED
            return Unresolved(f"attr:{type(base).__name__}.{node.attr}"), P_UNRESOLVED

        if isinstance(node, ast.Tuple | ast.List | ast.Set):
            items = [self.eval_node(elt, env, facts, stack) for elt in node.elts]
            values = tuple(value for value, _kind in items)
            kind = max((_kind for _value, _kind in items), key=lambda k: _ORDER.get(k, 9), default=P_LITERAL)
            if any(isinstance(value, Unresolved) for value in values):
                return Unresolved(_unparse(node)), P_UNRESOLVED
            if isinstance(node, ast.Set):
                return frozenset(values), kind
            if isinstance(node, ast.List):
                return values, kind  # list/tuple 归一为 tuple，形态差异在 diff 里显式点名
            return values, kind

        if isinstance(node, ast.Dict):
            pairs = []
            for key, value in zip(node.keys, node.values):
                if key is None:
                    return Unresolved(f"dict-splat:{_unparse(node)}"), P_UNRESOLVED
                key_value, _kk = self.eval_node(key, env, facts, stack)
                value_value, _vk = self.eval_node(value, env, facts, stack)
                if isinstance(key_value, Unresolved) or isinstance(value_value, Unresolved):
                    return Unresolved(_unparse(node)), P_UNRESOLVED
                pairs.append((key_value, value_value))
            kind = P_LITERAL
            return dict(pairs), kind

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            value, kind = self.eval_node(node.operand, env, facts, stack)
            if isinstance(value, (int, float)):
                return -value, P_CONST if kind == P_LITERAL else kind
            return Unresolved(_unparse(node)), P_UNRESOLVED

        if isinstance(node, ast.BinOp):
            left, left_kind = self.eval_node(node.left, env, facts, stack)
            right, right_kind = self.eval_node(node.right, env, facts, stack)
            kind = max(left_kind, right_kind, key=lambda k: _ORDER.get(k, 9))
            kind = P_CONST if kind in (P_LITERAL, P_CONST) else kind
            if isinstance(left, Unresolved) or isinstance(right, Unresolved):
                return Unresolved(_unparse(node)), P_UNRESOLVED
            try:
                if isinstance(node.op, ast.Add):
                    return left + right, kind          # type: ignore[operator]
                if isinstance(node.op, ast.Mult):
                    return left * right, kind          # type: ignore[operator]
                if isinstance(node.op, ast.Sub):
                    return left - right, kind          # type: ignore[operator]
            except TypeError:
                return Unresolved(_unparse(node)), P_UNRESOLVED
            return Unresolved(_unparse(node)), P_UNRESOLVED

        if isinstance(node, ast.JoinedStr):
            parts = []
            worst = P_LITERAL
            for value in node.values:
                if isinstance(value, ast.Constant):
                    parts.append(str(value.value))
                    continue
                if isinstance(value, ast.FormattedValue):
                    inner, kind = self.eval_node(value.value, env, facts, stack)
                    worst = max(worst, kind, key=lambda k: _ORDER.get(k, 9))
                    if isinstance(inner, Unresolved):
                        return Unresolved(_unparse(node)), P_UNRESOLVED
                    if isinstance(inner, EnumMember):
                        inner = inner.value
                    parts.append(str(inner))
                    continue
                return Unresolved(_unparse(node)), P_UNRESOLVED
            return "".join(parts), (P_CONST if worst == P_LITERAL else worst)

        if isinstance(node, ast.Compare):
            left, _lk = self.eval_node(node.left, env, facts, stack)
            comparators = [self.eval_node(c, env, facts, stack)[0] for c in node.comparators]
            if isinstance(left, Unresolved) or any(isinstance(c, Unresolved) for c in comparators):
                return Unresolved(_unparse(node)), P_UNRESOLVED
            result = True
            for op, right in zip(node.ops, comparators):
                try:
                    if isinstance(op, ast.Eq):
                        ok = left == right
                    elif isinstance(op, ast.NotEq):
                        ok = left != right
                    elif isinstance(op, ast.Is):
                        ok = left is right
                    elif isinstance(op, ast.IsNot):
                        ok = left is not right
                    elif isinstance(op, ast.In):
                        ok = left in right
                    elif isinstance(op, ast.NotIn):
                        ok = left not in right
                    elif isinstance(op, ast.Lt):
                        ok = left < right
                    elif isinstance(op, ast.Gt):
                        ok = left > right
                    else:
                        return Unresolved(_unparse(node)), P_UNRESOLVED
                except TypeError:
                    return Unresolved(_unparse(node)), P_UNRESOLVED
                if not ok:
                    result = False
                    break
                left = right
            return result, P_DERIVED

        if isinstance(node, ast.BoolOp):
            operands = [self.eval_node(v, env, facts, stack) for v in node.values]
            operand_values = [value for value, _kind in operands]
            if any(isinstance(item, Unresolved) for item in operand_values):
                return Unresolved(_unparse(node)), P_UNRESOLVED
            worst = max((kind for _value, kind in operands), key=lambda k: _ORDER.get(k, 9))
            if isinstance(node.op, ast.And):
                return next((item for item in operand_values if not item),
                            operand_values[-1]), worst
            return next((item for item in operand_values if item), operand_values[-1]), worst

        if isinstance(node, ast.IfExp):
            test, _tk = self.eval_node(node.test, env, facts, stack)
            if isinstance(test, Unresolved):
                return Unresolved(_unparse(node)), P_UNRESOLVED
            branch = node.body if test else node.orelse
            return self.eval_node(branch, env, facts, stack)

        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            return self.eval_comprehension(node, env, facts, stack)

        if isinstance(node, ast.Call):
            return self.eval_call(node, env, facts, stack)

        return Unresolved(_unparse(node)), P_UNRESOLVED

    # -- 推导式 -----------------------------------------------------------
    def eval_comprehension(self, node: Any, env: dict[str, Any], facts: ModuleFacts,
                           stack: frozenset[str]) -> tuple[Any, str]:
        gen = node.generators[0]
        iterable, _kind = self.eval_node(gen.iter, env, facts, stack)
        if isinstance(iterable, EnumClass):
            iterable = [EnumMember(iterable.name, name, value) for name, value in iterable.members]
        if isinstance(iterable, Unresolved) or not isinstance(iterable, Iterable) or isinstance(iterable, str):
            return Unresolved(_unparse(node)), P_UNRESOLVED
        out: list[Any] = []
        for item in iterable:
            inner = dict(env)
            if isinstance(gen.target, ast.Tuple):
                try:
                    for target, value in zip(gen.target.elts, item):
                        if isinstance(target, ast.Name):
                            inner[target.id] = value
                except TypeError:
                    return Unresolved(_unparse(node)), P_UNRESOLVED
            elif isinstance(gen.target, ast.Name):
                inner[gen.target.id] = item
            ok = True
            for condition in gen.ifs:
                flag, _ck = self.eval_node(condition, inner, facts, stack)
                if isinstance(flag, Unresolved) or not flag:
                    ok = False
                    break
            if not ok:
                continue
            if isinstance(node, ast.DictComp):
                key, _k1 = self.eval_node(node.key, inner, facts, stack)
                value, _k2 = self.eval_node(node.value, inner, facts, stack)
                out.append((key, value))
            else:
                out.append(self.eval_node(node.elt, inner, facts, stack)[0])
        if isinstance(node, ast.DictComp):
            return dict(out), P_DERIVED  # type: ignore[arg-type]
        if isinstance(node, ast.SetComp):
            return frozenset(out), P_DERIVED
        if isinstance(node, ast.ListComp):
            return tuple(out), P_DERIVED
        return tuple(out), P_DERIVED

    # -- 调用 -------------------------------------------------------------
    def eval_call(self, node: ast.Call, env: dict[str, Any], facts: ModuleFacts,
                  stack: frozenset[str]) -> tuple[Any, str]:
        func, _func_kind = self.eval_node(node.func, env, facts, stack)
        args = [self.eval_node(a, env, facts, stack) for a in node.args]
        keywords = {kw.arg: self.eval_node(kw.value, env, facts, stack) for kw in node.keywords
                    if kw.arg is not None}
        splat = any(kw.arg is None for kw in node.keywords)

        # 内建：容器/杂项白名单
        if isinstance(node.func, ast.Name) and node.func.id in {"frozenset", "set", "tuple", "list"} and not args:
            # 零参空构造：PLACEHOLDER_UNIMPLEMENTED 摘牌后就是 `frozenset()`——本件 0.1.0 不认它，
            # 直接把 run() 崩在 _crosscheck 上（CM-P-9 接手实测）。求得出才谈得上塌陷锁。
            return {"frozenset": frozenset(), "set": set(), "tuple": (), "list": []}[node.func.id], P_CONST
        if isinstance(node.func, ast.Name) and node.func.id in {"frozenset", "tuple", "list", "set", "sorted"}:
            if len(args) != 1 or isinstance(args[0][0], Unresolved):
                return Unresolved(_unparse(node)), P_UNRESOLVED
            value = args[0][0]
            if isinstance(value, dict):
                value = list(value)
            items = tuple(value) if not isinstance(value, (str, bytes)) else (value,)
            if node.func.id == "sorted":
                items = tuple(sorted(items, key=repr))
            if node.func.id in {"frozenset", "set"}:
                return frozenset(items), P_CONST
            return items, P_CONST
        if isinstance(node.func, ast.Name) and node.func.id in {"str", "int", "float", "bool", "len"}:
            if len(args) != 1 or isinstance(args[0][0], Unresolved):
                return Unresolved(_unparse(node)), P_UNRESOLVED
            value = args[0][0]
            value = value.value if isinstance(value, EnumMember) else value
            if node.func.id == "len":
                return len(value), P_CONST
            return {
                "str": lambda: str(value),
                "int": lambda: int(value),
                "float": lambda: float(value),
                "bool": lambda: bool(value),
            }[node.func.id](), P_CONST
        if isinstance(node.func, ast.Name) and node.func.id == "dict":
            if args or keywords:
                return Unresolved(_unparse(node)), P_UNRESOLVED
            return {}, P_LITERAL
        if isinstance(node.func, ast.Name) and node.func.id == "MappingProxyType":
            if len(args) == 1:
                return args[0][0], P_CONST
            return Unresolved(_unparse(node)), P_UNRESOLVED
        if isinstance(node.func, ast.Name) and node.func.id == "field":
            return Unresolved(f"field(default_factory)…:{_unparse(node)}"), P_UNRESOLVED

        # dataclass 构造（先判，避免与同名枚举类互相抢分支）
        if isinstance(node.func, ast.Name) and node.func.id in facts.dataclasses:
            return self.build_record(node.func.id, node, env, facts, stack)

        # 枚举类调用：CapabilityFamily("command") → 成员
        if isinstance(func, EnumClass):
            if len(args) != 1 or isinstance(args[0][0], Unresolved):
                return Unresolved(_unparse(node)), P_UNRESOLVED
            member = func.by_value(args[0][0])
            return (member if member is not None else Unresolved(_unparse(node))), P_ENUM

        # 纯函数（单 return）
        if isinstance(func, Fn):
            return self.call_pure(func, node, env, facts, stack)

        if splat:
            self.ctx.note(f"call-with-**kwargs 未展开：{_unparse(node)}")
        return Unresolved(_unparse(node)), P_UNRESOLVED

    def build_record(self, cls: str, node: ast.Call, env: dict[str, Any], facts: ModuleFacts,
                     stack: frozenset[str]) -> tuple[Any, str]:
        spec = facts.dataclasses[cls]
        positional = [self.eval_node(a, env, facts, stack) for a in node.args]
        given: dict[str, tuple[Any, str]] = {}
        for index, (field_name, default) in enumerate(spec):
            if index < len(positional):
                given[field_name] = positional[index]
        for kw in node.keywords:
            if kw.arg is None:
                inner, _kind = self.eval_node(kw.value, env, facts, stack)
                if isinstance(inner, dict):
                    for key, value in inner.items():
                        if key in {name for name, _d in spec}:
                            given[str(key)] = (value, P_DERIVED)
                else:
                    self.ctx.note(f"{cls}: **kwargs 来源不可静态展开（{_unparse(kw.value)}）")
                continue
            given[kw.arg] = self.eval_node(kw.value, env, facts, stack)
        values: list[tuple[str, Any]] = []
        written: set[str] = set()
        for field_name, default in spec:
            if field_name in given:
                values.append((field_name, given[field_name][0]))
                written.add(field_name)
            else:
                if default is None:
                    values.append((field_name, Unresolved(f"{cls}.{field_name}: 无缺省表达式")))
                else:
                    value, kind = self.eval_node(default, env, facts, stack)
                    values.append((field_name, value if kind != P_UNRESOLVED else
                                   Unresolved(f"{cls}.{field_name} 缺省不可求值")))
        return Record(cls, tuple(values), frozenset(written)), P_DERIVED

    def call_pure(self, fn: Fn, node: ast.Call, env: dict[str, Any], facts: ModuleFacts,
                  stack: frozenset[str]) -> tuple[Any, str]:
        body = fn.node.body
        if len(body) != 1 or not isinstance(body[0], ast.Return) or body[0].value is None:
            # 多语句函数（`_route_execution_rows` 一类"循环派生描述符"的家）：交给语句解释器。
            # 在此静默返回 Unresolved 会让那个 builder 悄悄交出 0 行，等于把在册面缩小。
            value = Interpreter(facts, self).run(fn.name)[0]
            if isinstance(value, Unresolved):
                return Unresolved(f"{fn.name}(): 语句解释器也没能派生出行"), P_UNRESOLVED
            return value, P_DERIVED
        inner = dict(env)
        arguments = fn.node.args
        if arguments.posonlyargs or getattr(arguments, "kw_defaults", None) and len(arguments.kw_defaults) > len(arguments.kwarg and [1] or []):
            pass
        provided = [value for value, _kind in (self.eval_node(a, env, facts, stack) for a in node.args)]
        for index, arg in enumerate(arguments.args):
            inner[arg.arg] = provided[index] if index < len(provided) else Unresolved(f"{fn.name}:{arg.arg}")
        if arguments.vararg is not None:
            inner[arguments.vararg.arg] = tuple(provided[len(arguments.args):])
        defaults = list(arguments.defaults)
        offset = len(arguments.args) - len(defaults)
        for index, arg in enumerate(arguments.args):
            if index >= offset and arg.arg not in {kw for kw in inner}:
                pass
        for kwarg, default in zip(arguments.kwonlyargs, arguments.kw_defaults):
            given = next((kw for kw in node.keywords if kw.arg == kwarg.arg), None)
            if given is not None:
                inner[kwarg.arg] = self.eval_node(given.value, env, facts, stack)[0]
            elif default is not None:
                inner[kwarg.arg] = self.eval_node(default, env, facts, stack)[0]
        if arguments.kwarg is not None:
            inner[arguments.kwarg.arg] = {}
        return self.eval_node(body[0].value, inner, facts, stack)


def _unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except (SyntaxError, TypeError, ValueError):  # pragma: no cover - 兜底只为不炸量具
        return "<unparse-failed>"


# ============================================================================
# 语句解释器：只求 DescriptorBuilder 里"循环派生描述符"的两家
# ============================================================================


class Interpreter:
    def __init__(self, facts: ModuleFacts, evaluator: Evaluator) -> None:
        self.facts = facts
        self.ev = evaluator

    def run(self, fn_name: str) -> tuple[Any, list[str]]:
        notes_before = len(self.ev.ctx.notes)
        node = self.facts.functions.get(fn_name)
        if node is None:
            return Unresolved(f"{fn_name}: 不存在"), []
        value = self.exec_function(node)
        return value, self.ev.ctx.notes[notes_before:]

    def exec_expr(self, node: ast.expr, env: dict[str, Any]) -> None:
        """语句位置求值：``X.append(expr)`` 是 builder 收集行的唯一手段，必须真生效。"""
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "append" and len(node.args) == 1):
            base = self.ev.eval_node(node.func.value, env, self.facts)[0]
            if isinstance(base, list):
                base.append(self.ev.eval_node(node.args[0], env, self.facts)[0])
                return
        self.ev.eval_node(node, env, self.facts)

    def exec_function(self, node: ast.FunctionDef) -> Any:
        env: dict[str, Any] = {}
        self.ev.ctx.note(f"解释器进入 {node.name}：其内 `raise` 守卫若触发，本件不中止、只记假设")
        try:
            self.exec_block(node.body, env)
        except _Returned as returned:
            return returned.value
        except _Abort as abort:
            self.ev.ctx.note(f"{node.name} 派生过程中触发 raise ⇒ 生产 import 必炸：{abort.text}")
            return Unresolved(f"{node.name}: raise {abort.text}")
        return Unresolved(f"{node.name}: 无 return")

    def exec_block(self, stmts: list[ast.stmt], env: dict[str, Any]) -> None:
        for stmt in stmts:
            self.exec_stmt(stmt, env)

    def exec_stmt(self, stmt: ast.stmt, env: dict[str, Any]) -> None:
        if isinstance(stmt, ast.Continue):
            raise _Continue
        if isinstance(stmt, ast.Break):
            raise _Break
        if isinstance(stmt, ast.Return):
            value = self.ev.eval_node(stmt.value, env, self.facts)[0] if stmt.value else None
            raise _Returned(value)
        if isinstance(stmt, ast.Assign):
            value = self.ev.eval_node(stmt.value, env, self.facts)[0]
            if isinstance(stmt.value, ast.List) and not stmt.value.elts:
                value = []  # 累加器（`rows: list[...] = []`）必须可变异，别归一成空 tuple
            for target in stmt.targets:
                self.bind(target, value, env)
            return
        if isinstance(stmt, ast.AnnAssign):
            if stmt.value is not None:
                value = self.ev.eval_node(stmt.value, env, self.facts)[0]
                if isinstance(stmt.value, ast.List) and not stmt.value.elts:
                    value = []
                self.bind(stmt.target, value, env)
            return
        if isinstance(stmt, ast.Expr):
            self.exec_expr(stmt.value, env)
            return
        if isinstance(stmt, ast.ImportFrom | ast.Import):
            for alias in stmt.names:
                local = alias.asname or alias.name.split(".")[-1]
                env[local] = ModuleRef(alias.name.split(".")[-1])
            return
        if isinstance(stmt, ast.For):
            iterable = self.ev.eval_node(stmt.iter, env, self.facts)[0]
            if isinstance(iterable, Unresolved):
                self.ev.ctx.note(f"for 迭代源不可求值 ⇒ 该循环派生的行**丢失**：{_unparse(stmt.iter)}")
                return
            for item in iterable if isinstance(iterable, tuple) else (iterable,):
                inner = dict(env)
                self.bind(stmt.target, item, inner)
                try:
                    self.exec_block(stmt.body, inner)
                except _Continue:
                    continue
                except _Break:
                    break
            return
        if isinstance(stmt, ast.If):
            test = self.ev.eval_node(stmt.test, env, self.facts)[0]
            if isinstance(test, Unresolved):
                self.ev.ctx.note(f"守卫条件不可求值 ⇒ 假设其**不触发**（不执行体内 raise/continue）："
                                 f"{_unparse(stmt.test)}")
                return
            self.exec_block(stmt.body if test else stmt.orelse, env)
            return
        if isinstance(stmt, ast.Raise):
            self.ev.ctx.note(f"解释器遇到 raise ⇒ 生产装配在此必炸：{_unparse(stmt)}")
            raise _Abort(_unparse(stmt))
        if isinstance(stmt, ast.FunctionDef):
            env[stmt.name] = Fn(stmt)
            return
        self.ev.ctx.note(f"未求值的语句形态：{type(stmt).__name__}")

    def bind(self, target: ast.expr, value: Any, env: dict[str, Any]) -> None:
        if isinstance(target, ast.Name):
            env[target.id] = value
        elif isinstance(target, ast.Tuple):
            items = value if isinstance(value, tuple) else (value,)
            for index, elt in enumerate(target.elts):
                self.bind(elt, items[index] if index < len(items) else Unresolved("<缺>"), env)


class _Returned(Exception):
    def __init__(self, value: Any) -> None:
        self.value = value


class _Continue(Exception):
    pass


class _Break(Exception):
    pass


class _Abort(Exception):
    def __init__(self, text: str) -> None:
        self.text = text


# ============================================================================
# 侧 A：重现 _build_capability_descriptor()（:2741-2844，逐条抄写语义）
# ============================================================================


@dataclass
class Extraction:
    rows: dict[str, dict[str, tuple[Any, str]]]
    authored_by: dict[str, list[str]]
    routes: dict[str, list[Record]]
    topics: dict[str, list[Record]]
    gate_ids: set[str]
    descriptors: list[Record]
    builder_report: list[dict[str, Any]]
    notes: list[str]
    conflicts: list[str]
    put_order: dict[str, list[str]] = field(default_factory=dict)


def collect_descriptors(facts: ModuleFacts, evaluator: Evaluator,
                        registry_facts: ModuleFacts) -> tuple[list[Record], list[dict[str, Any]]]:
    """按 DESCRIPTOR_BUILDERS 的在册顺序收集 CapabilityDescriptor。"""
    builders_node = facts.consts.get("DESCRIPTOR_BUILDERS")
    report: list[dict[str, Any]] = []
    if builders_node is None:
        return [], [{"builder": "<missing>", "rows": 0, "how": "DESCRIPTOR_BUILDERS 不存在"}]
    names, _kind = evaluator.eval_node(builders_node, {}, facts)
    builder_names = names if isinstance(names, tuple) else ()
    out: list[Record] = []
    for builder in builder_names:
        # `DESCRIPTOR_BUILDERS = (_media_descriptors, …)` 的元素是**函数对象引用**、不是字符串。
        # 只按字符串找名字会让六个 builder 全判"函数不存在"、整册零行——量具瞎了还报数，
        # 正是本仓反复定罪的那一形，故此处类型分派必须显式。
        builder_fn: ast.FunctionDef | None
        label: str
        if isinstance(builder, Fn):
            builder_fn, label = builder.node, builder.name
        elif isinstance(builder, str):
            builder_fn, label = facts.functions.get(builder), builder
        else:
            report.append({"builder": type(builder).__name__, "rows": 0,
                           "how": "builder 元素形态未被量具识别（既非字符串也非函数引用）"})
            continue
        if builder_fn is None:
            report.append({"builder": label, "rows": 0, "how": "builder 函数不存在"})
            continue
        fn = builder_fn
        value = evaluator.eval_node(_return_value(fn) or ast.Constant(value=""), {}, facts)[0] \
            if _is_single_return_list(fn) else Interpreter(facts, evaluator).run(fn.name)[0]
        how = ("字面/纯函数（含 _read 内联与推导式）" if _is_single_return_list(fn)
               else "语句解释器执行函数体")
        if _is_single_return_list(fn) and _calls_deriving_function(fn, facts):
            # `_route_execution_descriptors` 的"单 return"里套着 `_route_execution_rows()`，
            # 真派生发生在被调函数里 ⇒ 标成"字面"就是给强度说谎，这里显式降级标注。
            how += "（推导式内调派生函数，真身在被调函数里）"
        rows = list(value) if isinstance(value, tuple | list) else []
        if not rows:
            rows = list(_extract_records_in_loop(fn, facts, evaluator))
            how += " ⇒ 兜底：循环体直取调用点（非真派生，等值强度低，必须逐行复核）"
        rows = [r for r in rows if isinstance(r, Record) and r.cls == "CapabilityDescriptor"]
        report.append({"builder": fn.name, "rows": len(rows), "how": how,
                       "ids": [r.get("capability_id") for r in rows]})
        out.extend(rows)
    return out, report


def _is_single_return_list(fn: ast.FunctionDef) -> bool:
    return (len(fn.body) == 1 and isinstance(fn.body[0], ast.Return)
            and fn.body[0].value is not None)


def _return_value(fn: ast.FunctionDef) -> ast.expr | None:
    """取函数最后一个 return 的表达式（本仓 builder 全以此收尾）。"""
    last = fn.body[-1] if fn.body else None
    return last.value if isinstance(last, ast.Return) else None


def _calls_deriving_function(fn: ast.FunctionDef, facts: ModuleFacts) -> bool:
    """单 return 形态的 builder 里是否又调了**非纯**函数（如 `_route_execution_rows`）。

    套了派生函数的"单 return"不是字面表：把它标成"字面/纯函数"会给等值强度说谎，
    所以此处显式降级标注，读报告的人才知道那 21 行是从注册册现算出来的。
    """
    body = fn.body[-1]
    if not isinstance(body, ast.Return) or body.value is None:
        return False
    for node in ast.walk(body.value):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            target = facts.functions.get(node.func.id)
            if target is not None and not _is_pure_derivation(target):
                return True
    return False


def _is_pure_derivation(fn: ast.FunctionDef) -> bool:
    """真派生 vs 只是"带 docstring 的字面返回"。

    只看 ``len(body) == 1`` 会把 ``_files_descriptors`` / ``_creation_descriptors`` 误判成
    "含循环守卫"——它们只是多了一行 docstring。判据要落在**语句形态**上。
    """
    if not fn.body or not isinstance(fn.body[-1], ast.Return) or fn.body[-1].value is None:
        return False
    for stmt in fn.body[:-1]:
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            continue  # docstring
        if isinstance(stmt, ast.FunctionDef):
            continue  # 内联纯函数（`_read`）
        return False
    return True


def _extract_records_in_loop(fn: ast.FunctionDef, facts: ModuleFacts,
                             evaluator: Evaluator) -> tuple[Record, ...]:
    """兜底路径：在 for 循环体里找 CapabilityDescriptor(...)，迭代源取注册册的同名表。

    只在语句解释器拿不到东西时使用；每次使用都在 builder 报告里写明"循环体直取"，
    绝不冒充"真派生"。"""
    rows: list[Record] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.For):
            continue
        iterable, _kind = evaluator.eval_node(node.iter, {}, facts)
        if isinstance(iterable, Unresolved):
            evaluator.ctx.note(f"循环体直取失败：迭代源不可求值 {_unparse(node.iter)}")
            continue
        for item in iterable:
            env = _bind_for_target(node.target, item)
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                        and sub.func.id == "CapabilityDescriptor"):
                    record, _rk = evaluator.build_record("CapabilityDescriptor", sub, env, facts, frozenset())
                    if isinstance(record, Record):
                        rows.append(record)
    return tuple(rows)


def _bind_for_target(target: ast.expr, item: Any) -> dict[str, Any]:
    env: dict[str, Any] = {}
    if isinstance(target, ast.Name):
        env[target.id] = item
    elif isinstance(target, ast.Tuple):
        values = item if isinstance(item, tuple) else (item,)
        for index, elt in enumerate(target.elts):
            if isinstance(elt, ast.Name):
                env[elt.id] = values[index] if index < len(values) else Unresolved("<缺>")
    return env


SOURCE_ORCH = "orchestration_descriptor"
SOURCE_ROUTE = "route_declaration"
SOURCE_CONTROLLED = "controlled_internal"
SOURCE_HELP = "help_topic"
SOURCE_INTERFACE = "interface_declaration"

_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")


def build_side_a(protocols: ModuleFacts, registry: ModuleFacts,
                 evaluator: Evaluator, tables: dict[str, tuple[Record, ...]]) -> Extraction:
    descriptors, builder_report = collect_descriptors(protocols, evaluator, registry)
    rows: dict[str, dict[str, tuple[Any, str]]] = {}
    provenance: dict[str, list[str]] = {}
    extraction_order: dict[str, list[str]] = {}
    routes: dict[str, list[Record]] = {}
    topics: dict[str, list[Record]] = {}
    conflicts: list[str] = []

    def touch(cid: Any, source: str) -> dict[str, tuple[Any, str]]:
        if not isinstance(cid, str) or not cid:
            return {}
        provenance.setdefault(cid, [])
        if source not in provenance[cid]:
            provenance[cid].append(source)
        return rows.setdefault(cid, {})

    def put(bucket: dict[str, tuple[Any, str]], key: str, value: Any, kind: str,
            cid: Any) -> None:
        if value is None:
            return
        previous = bucket.get(key)
        if previous is not None and previous[0] != value:
            conflicts.append(f"{cid}.{key}: {previous[0]!r} vs {value!r}（来源 {provenance.get(cid)}）")
            return
        if previous is None:
            extraction_order.setdefault(str(cid), []).append(key)
        bucket[key] = (value, kind)

    for descriptor in descriptors:
        bucket = touch(descriptor.get("capability_id"), SOURCE_ORCH)
        cid = descriptor.get("capability_id")
        for table_field, source_field in (
            ("title", "title"), ("handler_ref", "implementation_ref"),
            ("health_probe", "health_probe"), ("health_default", "health_default"),
            ("fallbacks", "fallback_chain"), ("timeout_seconds", "timeout_seconds"),
            ("family", "family"),
        ):
            value = descriptor.get(source_field)
            # 未书写 = **描述符的 dataclass 缺省**，不是"代码派生"；两者搞混会把
            # "搬家把缺省写成字面量"这一格算进"派生冻结"，等于给差集编了个更严重的名目。
            kind = P_LITERAL if descriptor.has(source_field) else P_DEFAULT
            if source_field == "health_default" and not descriptor.has(source_field):
                value, kind = EnumMember("CapabilityHealth", "UNKNOWN", None), P_DEFAULT
            if source_field == "fallback_chain" and not descriptor.has(source_field):
                value, kind = (), P_DEFAULT
            if value is not None:
                put(bucket, table_field, value, kind, cid)

    for decl in tables["route"]:
        bucket = touch(decl.get("capability_id"), SOURCE_ROUTE)
        cid = decl.get("capability_id")
        binding = Record("RouteBinding", tuple(
            (name, decl.get(name)) for name in
            ("kind", "value", "priority", "label", "matcher_name", "has_rule", "command")),
            frozenset({"kind", "value", "priority", "label", "matcher_name", "has_rule", "command"}))
        bucket_routes = routes.setdefault(str(cid), [])
        if not any(_record_equals(existing, binding) for existing in bucket_routes):
            bucket_routes.append(binding)
        matcher = decl.get("matcher_name")
        if matcher:
            existing = bucket.get("handler_ref")
            if existing is None or not existing[0]:
                put(bucket, "handler_ref",
                    f"plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py#{matcher}",
                    P_DERIVED, cid)

    for cid_value in tables["controlled"]:
        touch(cid_value, SOURCE_CONTROLLED)

    for decl in tables["help"]:
        capability = str(decl.get("capability")).strip()
        if not _ID_PATTERN.fullmatch(capability):
            continue
        touch(capability, SOURCE_HELP)
        binding = Record("HelpBinding", (("topic", decl.get("topic")),
                                         ("admin_only", decl.get("admin_only"))),
                         frozenset({"topic", "admin_only"}))
        bucket_topics = topics.setdefault(capability, [])
        if not any(_record_equals(existing, binding) for existing in bucket_topics):
            bucket_topics.append(binding)

    for decl in tables["interface"]:
        interface_id = decl.get("interface_id")
        if isinstance(interface_id, str) and _ID_PATTERN.fullmatch(interface_id):
            bucket = touch(interface_id, SOURCE_INTERFACE)
            put(bucket, "interface_id", interface_id, P_DERIVED, interface_id)

    gate_ids = {str(decl.get("capability_id")) for decl in tables["route"] if decl.get("has_rule")}
    gate_ids |= {str(cid_value) for cid_value in tables["controlled"]}

    return Extraction(rows=rows, authored_by=provenance, routes=routes, topics=topics,
                      gate_ids=gate_ids, descriptors=descriptors, builder_report=builder_report,
                      notes=[], conflicts=conflicts, put_order=extraction_order)


def _record_equals(left: Record, right: Record) -> bool:
    return left.cls == right.cls and tuple(v for _k, v in left.values) == tuple(v for _k, v in right.values)


def spec_fields(facts: ModuleFacts, cls: str) -> list[tuple[str, ast.expr | None]]:
    return facts.dataclasses[cls]


# ============================================================================
# 可移植性判定 + 往返投影（侧 B）
# ============================================================================

ENUM_SYMBOL_OWNERS = {
    "CapabilityFamily": "runtime.capability_protocols",
    "CapabilityHealth": "runtime.capability_protocols",
}


def literal_source(value: Any) -> str | None:
    """能写成 ``ast.literal_eval`` 认得的字面量 ⇒ 返回该文本；否则 None（搬不动）。"""
    if value is None or isinstance(value, bool | int | float | str):
        return repr(value)
    if isinstance(value, tuple):
        raw = [literal_source(item) for item in value]
        if any(part is None for part in raw):
            return None
        parts = [str(part) for part in raw]
        return "(" + ", ".join(parts) + ("," if len(parts) == 1 else "") + ")"
    if isinstance(value, frozenset):
        raw_set = [literal_source(item) for item in sorted(value, key=repr)]
        if any(part is None for part in raw_set):
            return None
        return "frozenset({" + ", ".join(str(part) for part in raw_set) + "})"
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            key_text, value_text = literal_source(key), literal_source(item)
            if key_text is None or value_text is None:
                return None
            parts.append(f"{key_text}: {value_text}")
        return "{" + ", ".join(parts) + "}"
    return None


_SEVERITY = {"portable-literal": 0, "portable-call": 1, "enum-symbol": 2,
             "nested-record": 3, "blocked": 9}


def portability(value: Any) -> tuple[str, str]:
    """返回 (类别, 建议形态)。序列按**最不利元素**定级：
    ``(RouteBinding, …)`` 这种"元组套 dataclass"若按元组整体判字面量，会把类依赖藏起来。
    """
    if isinstance(value, Unresolved):
        return "blocked", f"表达式求不出（第二真身风险）：{value.text}"
    if isinstance(value, EnumMember):
        owner = ENUM_SYMBOL_OWNERS.get(value.owner, "<未知 owner>")
        return "enum-symbol", (f"枚举成员 {value.owner}.{value.name}：册内可写符号引用，但枚传真身仍住 "
                               f"{owner}——枚传必须随迁或以再导出保面，否则册要么 import 机制件（成环）、"
                               f"要么自造第二套枚举")
    if isinstance(value, Record):
        inner = [portability(item) for _k, item in value.values]
        worst = max(inner, key=lambda pair: _SEVERITY.get(pair[0], 9)) if inner else ("portable-literal", "")
        if worst[0] == "blocked":
            return "blocked", f"{value.cls} 内层含不可搬运值"
        return "nested-record", (f"{value.cls} 构造调用：可搬运，但类定义必须同册可见"
                                 + ("；内层还含枚举成员 ⇒ 随枚迁同一条路"
                                    if worst[0] == "enum-symbol" else ""))
    if isinstance(value, tuple | frozenset):
        items = value if isinstance(value, tuple) else tuple(sorted(value, key=repr))
        inner = [portability(item) for item in items]
        worst = max(inner, key=lambda pair: _SEVERITY.get(pair[0], 9)) if inner else ("portable-literal", "")
        if worst[0] in {"nested-record", "enum-symbol"}:
            return "nested-record", worst[1]
        if worst[0] == "blocked":
            return "blocked", worst[1]
        if isinstance(value, frozenset):
            return "portable-call", ("集合形态需 `frozenset({…})` 构造调用：它**不是** `ast.literal_eval` "
                                     "认得的纯字面量，按字面抽取的静态消费方（如 board_taxonomy 家规要求）"
                                     "会读不出来")
        return "portable-literal", "字面量直搬"
    if literal_source(value) is not None:
        return "portable-literal", "字面量直搬"
    return "blocked", f"不可字面表示的 Python 对象：{type(value).__name__}"


#: 不可搬运列在往返文本里的占位：**整行照生成、照解析回来**，让该列自己现形为
#: "值变了"，而不是把这一行从对账里摘掉（摘行=缩扫描面，禁止）。
NON_PORTABLE_SENTINEL = "__non_portable__"


def render_registration_text(cid: str, row: dict[str, tuple[Any, str]], fields: list[str],
                             extraction: Extraction) -> tuple[str, list[dict[str, str]]]:
    """把一行按**声明序全列写出**（Form L：字面行），返回 (源码文本, 不可搬运点名).

    取列一律走 `_row_value`（与比较侧同一读法）——两处各读一遍就会把量具的读法差
    误报成搬家的账差。
    """
    parts: list[str] = []
    blocked: list[dict[str, str]] = []
    for name in fields:
        value = _row_value(name, row, extraction, cid)[0]
        if name == "capability_id":
            parts.append(f"capability_id={literal_source(value)}")
            continue
        kind, advice = portability(value)
        if kind in {"portable-literal", "portable-call"}:
            parts.append(f"{name}={literal_source(value)}")
        elif kind == "enum-symbol":
            parts.append(f"{name}={value.owner}.{value.name}")
        elif kind == "nested-record":
            parts.append(f"{name}={_render_record(value)}")
        else:
            blocked.append({"capability_id": cid, "field": name, "why": advice})
            parts.append(f'{name}=("{NON_PORTABLE_SENTINEL}:{name}",)')
    return (f"CapabilityRegistration({', '.join(parts)})", blocked)


def _render_record(value: Any) -> str:
    if isinstance(value, tuple):
        return "(" + "".join(f"{_render_record(item)},\n " for item in value) + ")"
    if isinstance(value, Record):
        inner = ", ".join(f"{name}={_render_record(item)}" for name, item in value.values)
        return f"{value.cls}({inner})"
    if isinstance(value, EnumMember):
        return f"{value.owner}.{value.name}"
    text = literal_source(value)
    return text if text is not None else f'"{NON_PORTABLE_SENTINEL}:nested"'


# ============================================================================
# 差集
# ============================================================================


@dataclass
class Diff:
    capability_id: str
    field: str
    side_a: str
    side_b: str
    verdict: str
    provenance: str
    note: str


#: 判定 → 是否计入"差集"（True=搬家会改账，必须逐条消化）
DIFF_IS_DIFF = {
    "ROUNDTRIP-VALUE-DIFF": True,
    "NON-PORTABLE": True,
    "ENUM-OWNER": True,
    "DERIVED-FROZEN": True,
    "DEFAULT-MATERIALIZED": True,
    "EQUAL": False,
}


def describe(value: Any, limit: int = 160) -> str:
    if isinstance(value, Unresolved):
        text = f"UNRESOLVED({value.text})"
    elif isinstance(value, EnumMember):
        text = f"{value.owner}.{value.name}"
    elif isinstance(value, Record):
        text = _render_record(value)
    else:
        text = repr(value)
    text = text.replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "…"


def project_and_compare(side_a: dict[str, dict[str, tuple[Any, str]]], extraction: Extraction,
                        reg_fields: list[str], protocols: ModuleFacts,
                        poison: Any = None) -> tuple[list[Diff],
                                                     list[dict[str, Any]],
                                                     list[dict[str, str]],
                                                     dict[str, Any]]:
    """真往返：侧 A 行 → 生成字面册源码 → ``ast.parse`` → 求值回行 → 逐字段比。

    "生成后自己说相等"不作数：必须把生成的文本**再解析回来**求值，才谈得上等值证明。
    ``poison`` 仅供 ``--selftest`` 在侧 B 生成**之后**改侧 A，用来证明本件真有牙。
    """
    diffs: list[Diff] = []
    blocked: list[dict[str, str]] = []
    per_field: dict[str, dict[str, int]] = {name: {"rows": 0, "equal": 0, "derived_frozen": 0,
                                                   "derived_nonempty": 0,
                                                   "default_materialized": 0, "enum_owner": 0,
                                                   "non_portable": 0, "roundtrip_diff": 0}
                                            for name in reg_fields}
    blocks: list[str] = []
    blocked_fields_by_row: dict[str, set[str]] = {}
    sentinels: dict[str, dict[str, int]] = {name: {} for name in reg_fields}
    for cid in sorted(side_a):
        text, row_blocked = render_registration_text(cid, side_a[cid], reg_fields, extraction)
        blocked.extend(row_blocked)
        blocked_fields_by_row[cid] = {item["field"] for item in row_blocked}
        blocks.append(f"{_indent(text)}")
    side_b = _parse_back("".join(blocks), reg_fields, protocols)
    if poison is not None:
        # 注毒发生在**生成并回读之后**：这样"值变了"才是真变了，而不是生成器一起被改。
        poison(side_a, extraction)

    for cid in sorted(side_a):
        row = side_a[cid]
        back = side_b.get(cid)
        for name in reg_fields:
            per_field[name]["rows"] += 1
            value, kind = _row_value(name, row, extraction, cid)
            back_value = None if back is None else back.get(name)
            sentinel = isinstance(back_value, tuple) and any(
                isinstance(item, str) and item.startswith(NON_PORTABLE_SENTINEL)
                for item in back_value)
            if isinstance(value, Unresolved) or name in blocked_fields_by_row.get(cid, set()):
                verdict, note = "NON-PORTABLE", portability(value)[1] if isinstance(
                    value, Unresolved) else "该行此列含不可字面搬运的内层值"
                per_field[name]["non_portable"] += 1
            elif back is None:
                verdict, note = "ROUNDTRIP-VALUE-DIFF", "往返后整行读不回来（生成物解析失败）"
                per_field[name]["roundtrip_diff"] += 1
            elif sentinel:
                verdict, note = "NON-PORTABLE", "往返以占位符现形：此列今日根本搬不过去"
                per_field[name]["non_portable"] += 1
            elif back_value != value:
                verdict, note = "ROUNDTRIP-VALUE-DIFF", "往返后值变了 ⇒ 该列搬不动或被折叠错了"
                per_field[name]["roundtrip_diff"] += 1
            elif isinstance(value, EnumMember):
                verdict, note = "ENUM-OWNER", (
                    f"值等，但成员真身住 {ENUM_SYMBOL_OWNERS.get(value.owner, 'runtime.capability_protocols')}"
                    " ⇒ 册要么 import 机制件（与再导出成环）、要么枚举随迁")
                per_field[name]["enum_owner"] += 1
            elif kind == P_DEFAULT:
                verdict, note = "DEFAULT-MATERIALIZED", (
                    "值等，但今日该列由 dataclass 缺省兜住、字面化后被显式写出 ⇒ 文本变了")
                per_field[name]["default_materialized"] += 1
            elif kind == P_DERIVED:
                verdict, note = "DERIVED-FROZEN", (
                    "值等，但该列今日由代码派生（gate_feature_id / route handler_ref 兜底 / "
                    "authored_by 出处序 / 循环派生行），写成字面量即把派生升格为复制 ⇒ 输入源变更后不跟随")
                per_field[name]["derived_frozen"] += 1
                if value not in ((), "", None, {}):
                    # 空容器的"派生冻结"是低危（没有内容会漂移）；非空才是真雷。
                    per_field[name]["derived_nonempty"] += 1
            else:
                verdict, note = "EQUAL", ""
                per_field[name]["equal"] += 1
            sentinels[name][_sentinel_of(value)] = sentinels[name].get(_sentinel_of(value), 0) + 1
            if DIFF_IS_DIFF.get(verdict, True):
                diffs.append(Diff(cid, name, describe(value), describe(back_value), verdict, kind, note))
    stats = []
    for name, counts in per_field.items():
        # "值存活"= 行数 −（往返值差 + 搬不动）。这一列必须单独摆出来：
        # 判定列按"最不利取一"，ENUM-OWNER 会吃掉本该是 EQUAL 的行，
        # 只看 equal 列会误读成"值也对不上"——那是另一种假账。
        stats.append({"field": name, "value_survived": counts["rows"] - counts["roundtrip_diff"]
                      - counts["non_portable"], **counts})
    order = _order_report(side_a, extraction, reg_fields)
    order["rows_materialized"] = len(side_b)
    order["sentinel_census"] = {name: sentinels[name] for name in reg_fields}
    return diffs, stats, blocked, order


def _sentinel_of(value: Any) -> str:
    """空值形态点名：`None` / `''` / `()` / `frozenset()` 是**四种不同的空**，
    搬家时把它们互相替换（尤其 `None`↔`()`）就是本件要抓的"改了账"。"""
    if value is None:
        return "None"
    if isinstance(value, str):
        return "''（空串）" if value == "" else "非空 str"
    if isinstance(value, tuple):
        return "()（空元组）" if not value else f"{len(value)} 元元组"
    if isinstance(value, frozenset):
        return "frozenset()" if not value else f"frozenset×{len(value)}"
    if isinstance(value, dict):
        return "{}" if not value else f"dict×{len(value)}"
    if isinstance(value, EnumMember):
        return f"枚举 {value.owner}.{value.name}"
    if isinstance(value, Unresolved):
        return "UNRESOLVED"
    return repr(value)


def _row_value(name: str, row: dict[str, tuple[Any, str]], extraction: Extraction,
               cid: str) -> tuple[Any, str]:
    if name == "routes":
        return tuple(extraction.routes.get(cid, ())), P_DERIVED
    if name == "help_topics":
        return tuple(extraction.topics.get(cid, ())), P_DERIVED
    if name == "authored_by":
        return tuple(extraction.authored_by.get(cid, ())), P_DERIVED
    return row.get(name, (Unresolved(f"{cid}.{name} 未赋值"), P_UNRESOLVED))


def _indent(text: str) -> str:
    return "    " + text.replace("\n", "\n    ") + ",\n"


def _parse_back(body_source: str, reg_fields: list[str], protocols: ModuleFacts) -> dict[str, Record]:
    """把生成的字面行**再解析回来**（真往返，不是自我宣布）。"""
    source = "_ROWS = (\n" + body_source + "\n)\n"
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise SystemExit(f"[FATAL] 生成的字面册解析不回来（＝搬过去必然读不出）：{exc}\n"
                         f"{_probe_line(source, exc.lineno)}") from exc
    synthetic = ModuleFacts(path=Path("<synthetic-manifest>"), tree=tree)
    synthetic.consts = {n.targets[0].id: n.value for n in tree.body
                        if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)}
    synthetic.dataclasses = dict(protocols.dataclasses)
    synthetic.enums = dict(protocols.enums)
    ctx = Ctx()
    evaluator = Evaluator({"synthetic": synthetic}, ctx)
    value, _kind = evaluator.eval_node(synthetic.consts["_ROWS"], {}, synthetic)
    out: dict[str, Record] = {}
    if isinstance(value, tuple):
        for item in value:
            if isinstance(item, Record) and item.cls == "CapabilityRegistration":
                out[str(item.get("capability_id"))] = item
    return out


def _probe_line(source: str, lineno: int | None) -> str:
    if not lineno:
        return ""
    lines = source.splitlines()
    start = max(0, lineno - 3)
    return "\n".join(f"{index + start + 1:>5} | {line}"
                     for index, line in enumerate(lines[start:lineno + 1]))


def _order_report(side_a: dict[str, dict[str, tuple[Any, str]]], extraction: Extraction,
                  reg_fields: list[str]) -> dict[str, Any]:
    """字段书写序：今日构造序（capability_id/routes/help_topics/authored_by + bucket 插入序）
    与 dataclass 声明序的比较——值不受影响、文本必受影响，属"搬家改了账"的一种。"""
    differing = 0
    sample: list[str] = []
    for cid in sorted(side_a):
        bucket_order = list(extraction.put_order.get(cid, []))  # gate_feature_id 已在物化阶段并入
        today = ["capability_id", "routes", "help_topics", "authored_by"] + bucket_order
        if today != reg_fields:
            differing += 1
            if len(sample) < 3:
                sample.append(f"{cid}: 今日={today} vs 声明序={reg_fields}")
    return {"rows_compared": len(side_a), "rows_with_order_drift": differing,
            "declared_order": reg_fields, "samples": sample,
            "instrument_selfcheck_declared_order_matches_frozen_expectation":
                reg_fields == list(REGISTRATION_FIELDS_EXPECTED),
            "note": "今日构造用 kwargs + `**bucket`（capability_protocols.py:2837-2843），"
                    "字面化后必然按声明序书写 ⇒ 每行文本都变、值不变"}


def _gate_feature_id(capability_id: str) -> str:
    """抄自 ``capability_protocols.py::_gate_feature_id``（:2736-2738）。"""
    return capability_id.replace("bot.", "bot.plugin.", 1)


# ============================================================================
# 搬家表面（P2 迁移标的）：逐符号现算它"是什么形态"，据此判可否当数据搬
# ============================================================================

#: 迁移标的清单（口径=``capability_manifest.py`` 头注 §迁移路线 点名的三件 + 其全部支撑件）。
#: 本件按名去 AST 里找**实况形态**；找不到就红着写出来，绝不静默少一行。
MIGRATION_TARGETS: tuple[str, ...] = (
    "CAPABILITY_DESCRIPTOR", "_build_capability_descriptor", "DESCRIPTOR_BUILDERS",
    "_ORCHESTRATION_DESCRIPTORS", "CapabilityDescriptor", "CapabilityRegistration",
    "RouteBinding", "HelpBinding", "CapabilityFamily", "CapabilityHealth",
    "registered_capability_ids", "gate_feature_bindings", "gate_route_projection",
    "orchestration_descriptor_rows", "_gate_feature_id", "_KNOWN_ADAPTERS",
    "CAPABILITY_SOURCE_ORCHESTRATION", "CAPABILITY_SOURCE_ROUTE",
    "CAPABILITY_SOURCE_CONTROLLED", "CAPABILITY_SOURCE_HELP", "CAPABILITY_SOURCE_INTERFACE",
    "_media_descriptors", "_files_descriptors", "_search_descriptors", "_creation_descriptors",
    "_route_execution_descriptors", "_route_execution_rows", "_pipeline_managed_descriptors",
)


def migration_surface(protocols: ModuleFacts) -> list[dict[str, Any]]:
    """逐标的判形态：数据（可搬）/ 函数（随数据同处才算一处真身）/ 函数对象（**不能当数据搬**）。"""
    rows: list[dict[str, Any]] = []
    for name in MIGRATION_TARGETS:
        line = protocols.declared_at.get(name, 0)
        node = (protocols.consts.get(name) or protocols.functions.get(name))
        kind = "未在本件 AST 里找到（清单过期，须人工核对）"
        detail = ""
        if name in protocols.dataclasses:
            node = None
        if isinstance(node, ast.FunctionDef):
            pure = _is_pure_derivation(node)
            kind = "函数（纯派生：体内只有字面量/内联纯函数）" if pure else "函数（真派生：含循环/条件/raise）"
            detail = ("值可由字面量表重算，随数据一起迁不改变任何一行"
                      if pure else
                      "搬数据就必须把它一起搬，否则册内投影与现表不一致（_route_execution_rows "
                      "一类还读注册册表，属跨件派生）")
        elif name in protocols.consts:
            if name == "DESCRIPTOR_BUILDERS":
                kind = "函数对象元组 ⇒ 不可当数据搬运"
                detail = ("元素是 `Callable[[], list[CapabilityDescriptor]]`：值本身不是数据，"
                          "只能随六个 builder 一起迁，或在册内以符号引用+再导出保面")
            elif name == "_ORCHESTRATION_DESCRIPTORS":
                kind = "派生 tuple（由 DESCRIPTOR_BUILDERS 现算）"
                detail = "字面化它=把派生升格为复制；保留派生则函数对象问题原样留在册内"
            elif name == "CAPABILITY_DESCRIPTOR":
                kind = "MappingProxyType(派生调用)"
                detail = "真身是 `_build_capability_descriptor()` 的产物，不是字面量表"
            elif name == "_KNOWN_ADAPTERS":
                kind = "frozenset 字面量"
                detail = "可搬；但它是 invoke 侧的判据，搬走后机制侧要反向引用册"
            else:
                kind = "模块级字面量常量"
                detail = "可搬"
        elif name in protocols.dataclasses:
            kind = "dataclass 定义"
            detail = (f"{len(protocols.dataclasses[name])} 列；"
                      + ("含可变缺省 field(default_factory) 风险列" if name == "CapabilityDescriptor" else "缺省全为不可变字面量"))
        elif name in protocols.enums:
            kind = "Enum 定义"
            detail = "行值以成员形态入表 ⇒ 枚传不随迁就必然 import 机制件（成环）"
        rows.append({"target": name, "form": kind, "detail": detail, "first_seen_at_line": line})
    return rows


# ============================================================================
# 册侧四件（FACETS / EVIDENCE / PLACEHOLDER / CEILING）的静态现算
# ============================================================================


def read_manifest_side(manifest: ModuleFacts, evaluator: Evaluator) -> dict[str, Any]:
    def _need(name: str) -> ast.expr:
        node = manifest.consts.get(name)
        if node is None:
            raise SystemExit(
                f"[FATAL] 塌陷锁：册侧 {name} 在 {manifest.rel} 读不出（含再导出追真身后仍缺）"
            )
        return node

    facets_value, _fk = evaluator.eval_node(_need("FACETS"), {}, manifest)
    if not isinstance(facets_value, dict):
        raise SystemExit(f"[FATAL] 塌陷锁：{manifest.rel}::FACETS 求值不成 dict（{describe(facets_value)}）"
                         "——降级成空面=壳读壳（CM-P-9）")
    facets = facets_value
    evidence_value, _ek = evaluator.eval_node(_need("EVIDENCE"), {}, manifest)
    if not isinstance(evidence_value, dict):
        raise SystemExit(f"[FATAL] 塌陷锁：{manifest.rel}::EVIDENCE 求值不成 dict（{describe(evidence_value)}）")
    placeholder_value, _pk = evaluator.eval_node(_need("PLACEHOLDER_UNIMPLEMENTED"), {}, manifest)
    if isinstance(placeholder_value, Unresolved):
        # 允许合法为空（frozenset()），不允许"求不出"——旧版把求不出的降级成 []，正禁。
        raise SystemExit(f"[FATAL] 塌陷锁：{manifest.rel}::PLACEHOLDER_UNIMPLEMENTED 求不出"
                         f"（{placeholder_value.text}）——不返回空名单")
    ceiling_value, _ck = evaluator.eval_node(_need("UNCOVERED_CEILING"), {}, manifest)
    if isinstance(ceiling_value, Unresolved):
        raise SystemExit(f"[FATAL] 塌陷锁：{manifest.rel}::UNCOVERED_CEILING 求不出"
                         f"（{ceiling_value.text}）")
    return {
        "facet_ids": sorted(str(key) for key in facets),
        "facet_rows": {
            str(key): {name: describe(value) for name, value in getattr(row, "values", ())}
            for key, row in facets.items() if isinstance(row, Record)
        },
        "evidence_keys": sorted(f"{key[0]}:{getattr(key[1], 'value', key[1])}"
                                for key in evidence_value),
        "placeholder": sorted(placeholder_value) if isinstance(placeholder_value, frozenset) else [],
        "uncovered_ceiling": ceiling_value,
    }


# ============================================================================
# 垫片保留面（任务 2）：真实 import / from-import / 属性加载 / 字符串引用
# ============================================================================

SCAN_ROOTS = ("plugins", "scripts", "tests")

#: `__all__` 展开不进导出面时的点名（静态导出面对不上时必须有地方记，不许静默少算）
unresolvable_exports: list[str] = []

#: 本件自身是量具，不是消费方——不排除就会把"我在读它"记成"它被依赖"，虚增保留面。
SELF = Path(__file__).resolve()


def all_python_files() -> list[Path]:
    files: list[Path] = []
    for root in SCAN_ROOTS:
        for path in (REPO_ROOT / root).rglob("*.py"):
            if path.resolve() != SELF:
                files.append(path)
    for extra in (REPO_ROOT / "bot.py", REPO_ROOT / "conftest.py"):
        if extra.is_file() and extra.resolve() != SELF:
            files.append(extra)
    return files


def shim_surface() -> dict[str, Any]:
    report: dict[str, Any] = {}
    for key, path in LEGACY_LEDGERS.items():
        report[key] = {
            "module_path": path.relative_to(REPO_ROOT).as_posix(),
            "public_exports": sorted(module_exports(path)),
            "importers": [],
            "attribute_loads": [],
            "string_refs": [],
        }
    for file in all_python_files():
        if any(file == path for path in LEGACY_LEDGERS.values()):
            continue
        try:
            text = file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(text)
        except (OSError, SyntaxError):
            continue
        lines = text.splitlines()
        rel = file.relative_to(REPO_ROOT).as_posix()
        bound: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                # 两种形态都要认：
                #   ① `from …runtime.capability_registry import X`（module 末段命中）
                #   ② `from …runtime import capability_registry as _registry`（alias 名命中）
                #      —— 唯一在册表的合并函数 `_build_capability_descriptor` 与三个 builder
                #      用的就是 ②（capability_protocols.py:2276/2326/2339/2778），
                #      只认 ① 会把头号消费方整个漏掉，保留面就成了假账。
                tail = (node.module or "").split(".")[-1]
                hit_module = tail in LEGACY_LEDGERS
                if hit_module:
                    for alias in node.names:
                        bound[alias.asname or alias.name] = tail
                    report[tail]["importers"].append({
                        "file": rel, "line": node.lineno,
                        "form": f"from {node.module or '.' * node.level} import",
                        "names": [f"{a.name} as {a.asname}" if a.asname else a.name
                                  for a in node.names],
                        "wildcard": any(alias.name == "*" for alias in node.names),
                    })
                    continue
                for alias in node.names:
                    alias_tail = alias.name.split(".")[-1]
                    if alias_tail not in LEGACY_LEDGERS:
                        continue
                    bound[alias.asname or alias.name] = alias_tail
                    report[alias_tail]["importers"].append({
                        "file": rel, "line": node.lineno,
                        "form": f"from {node.module or '.' * node.level} import（子模块别名）",
                        "names": [alias.name],
                        "submodule_alias": True,
                    })
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    tail = alias.name.split(".")[-1]
                    if tail in LEGACY_LEDGERS:
                        bound[alias.asname or alias.name.split(".")[-1]] = tail
                        entry_alias = alias.asname or alias.name
                        report[tail]["importers"].append({
                            "file": rel, "line": node.lineno,
                            "form": f"import {alias.name}（模块别名）",
                            "names": [entry_alias], "module_alias": True,
                        })
            elif isinstance(node, ast.Attribute):
                base = node.value
                if isinstance(base, ast.Name) and base.id in bound:
                    report[bound[base.id]]["attribute_loads"].append({
                        "file": rel, "line": node.lineno,
                        "name": f"{base.id}.{node.attr}",
                    })
            elif isinstance(node, ast.Constant):
                if isinstance(node.value, str):
                    for key_name in LEGACY_LEDGERS:
                        if key_name in node.value:
                            report[key_name]["string_refs"].append({
                                "file": rel, "line": node.lineno,
                                "text": node.value[:120],
                            })
        for index, line in enumerate(lines, start=1):
            for key_name in LEGACY_LEDGERS:
                if key_name in line and "import" not in line:
                    report[key_name].setdefault("text_refs", []).append({
                        "file": rel, "line": index, "text": line.strip()[:120]})
    for entry in report.values():
        symbol_names = _names_from(entry["importers"]) | _attr_names(entry["attribute_loads"])
        entry["module_aliases"] = sorted(_names_from(entry["importers"], symbols=False))
        entry["retained_names_required"] = sorted(set(entry["public_exports"]) & symbol_names)
        entry["consumed_but_not_exported"] = sorted(symbol_names - set(entry["public_exports"]))
        entry["names_from_imports"] = sorted(_names_from(entry["importers"]))
        entry["names_from_attributes"] = sorted(_attr_names(entry["attribute_loads"]))
        entry["text_refs"] = entry.get("text_refs", [])
        for group in ("string_refs", "text_refs"):
            for item in entry[group]:
                item["text"] = " ".join(str(item["text"]).split())[:110]
    return report


def _names_from(importers: list[dict[str, Any]], *, symbols: bool = True) -> set[str]:
    """`from X import a, b` 的**符号名**才进保留面；模块别名（含子模块别名）只要求模块可导入。"""
    out: set[str] = set()
    for item in importers:
        is_moduleish = bool(item.get("module_alias")) or bool(item.get("submodule_alias"))
        if is_moduleish == symbols:
            continue
        for name in item["names"]:
            if "*" in name:
                continue
            out.add(name.split(" as ")[0])
    return out


def _attr_names(loads: list[dict[str, Any]]) -> set[str]:
    return {str(item["name"]).split(".", 1)[1] for item in loads if "." in str(item["name"])}


def module_exports(path: Path, *, _chain: frozenset[str] = frozenset()) -> set[str]:
    """模块公开导出面。**CM-P-9（S44）三改**：

    ① 再导出**顺链追真身**后计入：旧版只数 def/assign/__all__，P2 薄壳
       （只有 ``from 册 import X as X``、无本地定义）会被读成空面 ⇒ 垫片保留面
       变假账（绿着漏）；现追进真身核验、星号再导出取真身公开面；
    ② 读不出/解析失败 ⇒ ``[FATAL]`` 点名文件——旧版静默 ``return set()``
       正是本波六禁里"把解析不到处理成返回空表"那一形；
    ③ 空导出面 ⇒ ``[FATAL]``：三处旧账今日皆数十枚符号，空面与"整册被抹"不可分辨。

    真身在仓外（stdlib/三方）的裸导入**不**计入（与旧版基线一致：11/7/10 枚的
    口径不因本改造漂移）；``X as X`` 显式再导出惯用形一律计入。
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except OSError as exc:
        raise SystemExit(
            f"[FATAL] 塌陷锁：module_exports 读不出 {path}：{exc}——读不出≠没有导出，停手点名"
        ) from exc
    except SyntaxError as exc:
        raise SystemExit(
            f"[FATAL] 塌陷锁：module_exports 解析失败 {path}：{exc}——解析失败≠没有导出，停手点名"
        ) from exc
    names = {node.name for node in tree.body
             if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
            for target in node.targets:
                if isinstance(target, ast.Tuple):
                    names.update(elt.id for elt in target.elts if isinstance(elt, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    dunder = next((node for node in tree.body if isinstance(node, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets)), None)
    if dunder is not None:
        try:
            names.update(str(item) for item in ast.literal_eval(dunder.value))
        except (ValueError, TypeError, SyntaxError):
            # `__all__` 里带 `[*x]` 之类的非字面量时 literal_eval 必炸（本仓三件都这形）。
            # 退而求其次：按 AST 把能认的字面量收进来，认不出的**显式记一条**，不静默少算导出面。
            for element in getattr(dunder.value, "elts", []):
                if isinstance(element, ast.Constant):
                    names.add(str(element.value))
                elif isinstance(element, ast.Starred):
                    unresolvable_exports.append(f"{path}:__all__ 内 `*{ast.unparse(element.value)}`")
    chain = _chain | {str(path.resolve()).lower()}

    def _source_surface(source: Path) -> set[str]:
        if str(source.resolve()).lower() in chain:
            return set()  # 循环再导出：本层不再展开，缺名由使用侧塌陷锁兜底
        return module_exports(source, _chain=chain)

    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        for alias in node.names:
            if alias.name == "*":
                source = _resolve_import_source(path, node.module, node.level)
                if source is None:
                    unresolvable_exports.append(
                        f"{path}:星号再导出自仓外 {node.module or '当前包'}，无法静态展开")
                    continue
                names.update(n for n in _source_surface(source) if not n.startswith("_"))
                continue
            bound = alias.asname or alias.name
            explicit_reexport = alias.asname is not None and alias.asname == alias.name
            source = _resolve_import_source(path, node.module, node.level)
            if not explicit_reexport and source is None:
                continue  # 仓外裸导入（dataclass/Iterator 这一类）：与旧版口径一致，不计
            if not explicit_reexport and bound.startswith("_"):
                continue  # 私有别名（`as _registry` 一族）绑的是模块句柄，不是符号
            if source is not None and alias.name not in _source_surface(source):
                unresolvable_exports.append(f"{path}:再导出 {alias.name} 在 {source} 公开面核验不中（按绑定照记）")
            names.add(bound)
    surface = {name for name in names if not name.startswith("_")}
    if not surface:
        try:
            shown = path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            shown = str(path)
        raise SystemExit(
            f"[FATAL] 塌陷锁：{shown} 公开导出面为空——薄壳无导出面与「整册被抹」不可分辨"
            "（CM-P-9），先修导出面/追再导出链再跑本件"
        )
    return surface


# ============================================================================
# main
# ============================================================================


def read_registry_tables(registry: ModuleFacts, evaluator: Evaluator) -> dict[str, tuple[Any, ...]]:
    """读注册册五表。**CM-P-9 塌陷锁（S44）落点**：缺名/求不出/零行都 ``[FATAL]`` 点名文件与表名.

    注册册降为再导出垫片后，缺名意味着「壳→册的追再导出链没接通」——裸搬数据造出的
    绿着漏正是这一形；这里绝不降级成空表，把红留在读点上。
    """
    tables: dict[str, tuple[Any, ...]] = {}
    for key, attr in (("route", "ROUTE_CAPABILITY_DECLARATIONS"),
                      ("interface", "INTERFACE_DECLARATIONS"),
                      ("help", "HELP_TOPIC_DECLARATIONS"),
                      ("controlled", "CONTROLLED_INTERNAL_CAPABILITIES"),
                      ("pipeline", "PIPELINE_MANAGED_CAPABILITY_DECLARATIONS")):
        const_node = registry.consts.get(attr)
        if const_node is None:
            raise SystemExit(
                f"[FATAL] 塌陷锁：注册册表 {attr} 在 {registry.rel} 读不出（含再导出追真身后仍缺）"
                "——若该文件已降为再导出垫片，是壳→册链没接上，先修读点再搬数据（CM-P-9）"
            )
        value, _kind = evaluator.eval_node(const_node, {}, registry)
        if isinstance(value, Unresolved):
            raise SystemExit(f"[FATAL] 注册册表 {attr} 静态求值失败：{value.text}")
        rows: tuple[Any, ...]
        if key == "controlled":
            rows = tuple(item for item in list(value) if isinstance(item, str))
        else:
            rows = tuple(item for item in list(value) if isinstance(item, Record))
        if not rows:
            raise SystemExit(
                f"[FATAL] 塌陷锁：注册册表 {attr} 解析为零行（{registry.rel}）——"
                "该表在册语义下不可能为空，空=眼睛瞎（CM-P-9）"
            )
        tables[key] = rows
    return tables


def run(census_json: Path | None, poison: Any = None) -> tuple[dict[str, Any], int]:
    ctx = Ctx()
    protocols = load_module(PROTOCOLS, ctx)
    registry = load_module(REGISTRY, ctx)
    manifest = load_module(MANIFEST, ctx)
    for facts in (protocols, registry, manifest):
        for node in ast.walk(facts.tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    facts.imports[alias.asname or alias.name.split(".")[-1]] = alias.name.split(".")[-1]
    modules = {"protocols": protocols, "registry": registry, "manifest": manifest}
    evaluator = Evaluator(modules, ctx)

    tables = read_registry_tables(registry, evaluator)

    extraction = build_side_a(protocols, registry, evaluator, tables)
    side_a = _finalize_rows(extraction, registry, protocols)

    reg_fields = [name for name, _default in spec_fields(protocols, "CapabilityRegistration")]
    diffs, per_field, blocked, order = project_and_compare(side_a, extraction, reg_fields,
                                                           protocols, poison=poison)

    payload: dict[str, Any] = {
        "version": VERSION,
        "sources": {
            "protocols": protocols.rel,
            "registry": registry.rel,
            "manifest": manifest.rel,
        },
        "scale_triples": {
            "CAPABILITY_DESCRIPTOR": f"{protocols.rel}::_build_capability_descriptor:2741",
            "registered_capability_ids": f"{protocols.rel}::registered_capability_ids:2887",
            "DESCRIPTOR_BUILDERS": f"{protocols.rel}::DESCRIPTOR_BUILDERS:2656",
            "CapabilityRegistration": f"{protocols.rel}::CapabilityRegistration:2693",
            "FACETS": f"{manifest.rel}::FACETS:111",
            "EVIDENCE": f"{manifest.rel}::EVIDENCE:150",
            "PLACEHOLDER_UNIMPLEMENTED": f"{manifest.rel}::PLACEHOLDER_UNIMPLEMENTED:177",
            "UNCOVERED_CEILING": f"{manifest.rel}::UNCOVERED_CEILING:165",
        },
        "row_count": len(side_a),
        "field_order_declared": reg_fields,
        "field_order_drift": order,
        "per_field_stats": per_field,
        "diffs": [diff.__dict__ for diff in diffs],
        "non_portable": blocked,
        "merge_conflicts": extraction.conflicts,
        "builder_report": extraction.builder_report,
        "migration_surface": migration_surface(protocols),
        "assumptions": ctx.notes,
        "manifest_side": read_manifest_side(manifest, evaluator),
        "gate_baselines": gate_baseline_crosscheck(side_a),
        "crosscheck_manifest_vs_table": _crosscheck(side_a, manifest, evaluator),
    }

    if census_json is not None:
        payload["census_crosscheck"] = _against_census(side_a, census_json)

    exit_code = 2 if (diffs or blocked or extraction.conflicts) else 0
    return payload, exit_code


def _finalize_rows(extraction: Extraction, registry: ModuleFacts,
                   protocols: ModuleFacts) -> dict[str, dict[str, tuple[Any, str]]]:
    """补齐未赋值列（dataclass 缺省）+ 把两枚**派生列**就地物化，与真表逐列对齐。

    ``capability_id`` 与 ``gate_feature_id`` 在真实构造里分别由位置参数与 :2836 的直接赋值给出，
    不物化就会在往返里被写成占位、报成"值变了"——那是量具的错，不是搬家的账。
    """
    defaults = _registration_defaults(protocols)
    rows = extraction.rows
    for cid in rows:
        for name, (value, kind) in defaults.items():
            rows[cid].setdefault(name, (value, kind))
        rows[cid]["capability_id"] = (cid, P_LITERAL)
        if cid in extraction.gate_ids:
            rows[cid]["gate_feature_id"] = (_gate_feature_id(cid), P_DERIVED)
            if "gate_feature_id" not in extraction.put_order.setdefault(cid, []):
                extraction.put_order[cid].append("gate_feature_id")
    return rows


def _registration_defaults(protocols: ModuleFacts) -> dict[str, tuple[Any, str]]:
    out: dict[str, tuple[Any, str]] = {}
    for name, default in protocols.dataclasses["CapabilityRegistration"]:
        if default is None:
            continue
        if isinstance(default, ast.Constant):
            out[name] = (default.value, P_DEFAULT)
        elif isinstance(default, ast.Tuple) and not default.elts:
            out[name] = ((), P_DEFAULT)
        elif isinstance(default, ast.Attribute):
            member = EnumMember("CapabilityHealth", default.attr, None)
            out[name] = (member, P_DEFAULT)
        else:
            out[name] = (Unresolved(f"default:{_unparse(default)}"), P_DEFAULT)
    return out


def _crosscheck(side_a: dict[str, Any], manifest: ModuleFacts,
                evaluator: Evaluator) -> list[dict[str, Any]]:
    facets_value, _fk = evaluator.eval_node(manifest.consts["FACETS"], {}, manifest)
    facets = facets_value if isinstance(facets_value, dict) else {}
    placeholder_value, _pk = evaluator.eval_node(manifest.consts["PLACEHOLDER_UNIMPLEMENTED"], {}, manifest)
    rows: list[dict[str, Any]] = []
    for cid in sorted(str(key) for key in facets):
        row = side_a.get(cid, {})
        handler = row.get("handler_ref", (Unresolved("行不存在"), P_UNRESOLVED))[0]
        rows.append({
            "capability_id": cid,
            "in_table": cid in side_a,
            "handler_ref": describe(handler),
            "placeholder_declared": cid in (placeholder_value or frozenset()),
        })
    return rows


def gate_baseline_crosscheck(side_a: dict[str, dict[str, tuple[Any, str]]]) -> dict[str, Any]:
    """与本波常驻门 G-CM 的**在册基线**对账（基线从门文件 AST 现读，不抄第二份）。

    本件是"独立重实现"，所以必须有第二把尺子卡它：这三枚基线由运行时真表算出并写死在门里，
    本件的静态重算若与它们对不上，问题在本件（不是在生产代码）。
    """
    out: dict[str, Any] = {"gate_file": GATE.relative_to(REPO_ROOT).as_posix(), "checks": []}
    try:
        tree = ast.parse(GATE.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError) as exc:
        return {"gate_file": out["gate_file"], "error": f"门文件读不出：{exc}"}
    baselines: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)                 and isinstance(node.value.value, int):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.endswith(("BASELINE", "FLOOR")):
                    baselines[target.id] = node.value.value
    if not baselines:
        return {**out, "error": "门里没读到任何 BASELINE/FLOOR 整数常量＝基线改名了，本对账不作数"}
    empty_handler = sum(1 for row in side_a.values()
                        if not str(row.get("handler_ref", ("",))[0]))
    reserved = sum(1 for row in side_a.values()
                   if str(row.get("handler_ref", ("",))[0]).endswith("#reserved"))
    declared = sum(1 for row in side_a.values() if "help_topic" in str(row.get("authored_by", "")))
    mine = {"REGISTERED_FLOOR": len(side_a), "EXECUTION_SURFACE_BASELINE": empty_handler,
            "PLACEHOLDER_BASELINE": reserved, "DECLARED_UNWIRED_BASELINE": declared}
    meaning = {"REGISTERED_FLOOR": "在册 id 总数（地板：本件须 ≥ 它）",
               "EXECUTION_SURFACE_BASELINE": "在册但 handler_ref 为空的枚数（上限：本件须 ≤ 它）",
               "PLACEHOLDER_BASELINE": "#reserved 占位执行体枚数（上限：本件须 ≤ 它）",
               "DECLARED_UNWIRED_BASELINE": "口径不同：门按普查态算、本件无普查态 ⇒ 只并列不作判据"}
    for name, baseline in sorted(baselines.items()):
        value = mine.get(name)
        if value is None:
            out["checks"].append({"baseline": name, "gate": baseline, "projection": None,
                                  "verdict": "本件无对应口径"})
            continue
        if name == "REGISTERED_FLOOR":
            ok = value >= baseline
            relation = "≥"
        elif name == "DECLARED_UNWIRED_BASELINE":
            ok = True
            relation = "≈(口径不同)"
        else:
            ok = value <= baseline
            relation = "≤"
        out["checks"].append({"baseline": name, "gate": baseline, "projection": value,
                              "relation": relation, "meaning": meaning.get(name, ""),
                              "verdict": "一致" if ok else "**不一致⇒问题在本件**"})
    out["all_consistent"] = all("一致" == item["verdict"] for item in out["checks"])
    return out


def _against_census(side_a: dict[str, Any], census_json: Path) -> dict[str, Any]:
    try:
        payload = json.loads(census_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"error": f"普查快照读不出：{exc}"}
    roster = payload.get("roster")
    if not isinstance(roster, dict) or not roster:
        return {"error": "普查快照无 roster＝第二把尺子瞎了，本次对账不作数"}
    mine, theirs = set(side_a), set(roster)
    return {
        "mine": len(mine), "census": len(theirs),
        "only_in_projection": sorted(mine - theirs),
        "only_in_census": sorted(theirs - mine),
        "agree": mine == theirs,
    }


# ============================================================================
# 人类可读渲染
# ============================================================================


def protocols_rel(payload: dict[str, Any]) -> str:
    return str(payload["sources"]["protocols"])


def render_text(payload: dict[str, Any], surface: dict[str, Any], shim_only: bool) -> str:
    out: list[str] = []
    add = out.append
    add(f"capability_manifest_projection_check {VERSION}")
    add("尺身份（文件::函数:行号，全部现读）：")
    for name, triple in payload.get("scale_triples", {}).items():
        add(f"  {name:<32} {triple}")
    if shim_only:
        _render_surface(surface, add)
        return "\n".join(out)

    order = payload["field_order_drift"]
    add("")
    add(f"侧 A 行数（在册 id 全集，静态重现 _build_capability_descriptor）= {payload['row_count']}")
    add(f"  · CapabilityRegistration 声明序 = {payload['field_order_declared']}")
    add(f"  · 量具自校准（声明序 == 件内冻结预期序）= "
        f"{order['instrument_selfcheck_declared_order_matches_frozen_expectation']}")
    add(f"  · 字段书写序漂移行数 = {order['rows_with_order_drift']}/{order['rows_compared']}"
        f"（{order['note']}）")
    for sample in order["samples"]:
        add(f"      例 {sample}")
    add("")
    add("①′ 空值形态盘点（None / '' / () / frozenset() 是四种不同的空，互换即改账）")
    for name, tally in order["sentinel_census"].items():
        add(f"  {name:<18}" + "  ".join(f"{k}={v}" for k, v in sorted(tally.items())))
    add("")
    add("① 逐字段投影账（今日表 → 生成字面册 → ast.parse 回读 → 逐列比）")
    add(f"  · 行集全等（生成物回读 id 集 == 侧 A id 集）= {order['rows_materialized']}"
        f"/{order['rows_compared']}")
    add(f"  {'字段':<18}{'行数':>5}{'值存活':>6}{'等值':>6}{'派生冻结':>9}{'其中非空':>9}"
        f"{'缺省显式化':>10}{'枚举主':>7}{'搬不动':>7}{'往返值差':>9}")
    for item in payload["per_field_stats"]:
        add(f"  {item['field']:<18}{item['rows']:>5}{item['value_survived']:>6}{item['equal']:>6}"
            f"{item['derived_frozen']:>9}{item['derived_nonempty']:>9}"
            f"{item['default_materialized']:>10}{item['enum_owner']:>7}"
            f"{item['non_portable']:>7}{item['roundtrip_diff']:>9}")
    add("  （判定按最不利取一：`等值`列会少算被枚举主/派生冻结吃掉的行，`值存活`列才是往返真值）")
    add("")
    add(f"② 非等值条目（逐条，共 {len(payload['diffs'])} 条）")
    if not payload["diffs"]:
        add("  （无）")
    seen: set[tuple[str, str]] = set()
    for diff in payload["diffs"]:
        signature = (diff["field"], diff["verdict"])
        if signature in seen:
            continue
        seen.add(signature)
        add(f"  [{diff['verdict']}] {diff['field']} 例：{diff['capability_id']} = "
            f"{diff['side_a']} — {diff['note']}")
    grouped: dict[tuple[str, str], list[str]] = {}
    for diff in payload["diffs"]:
        grouped.setdefault((diff["field"], diff["verdict"]), []).append(diff["capability_id"])
    add("")
    add("  按 (字段, 判定) 归拢的受影响能力（全量，不抽样）：")
    for (field_name, verdict), ids in sorted(grouped.items()):
        add(f"   {field_name:<18}{verdict:<22}{len(ids):>4} 枚  "
            + ", ".join(ids[:6]) + (" …" if len(ids) > 6 else ""))
    add("")
    add(f"③ 不可字面搬运项（{len(payload['non_portable'])} 条）")
    for item in payload["non_portable"][:40]:
        add(f"  {item['capability_id']} · {item['field']}：{item['why']}")
    if len(payload["non_portable"]) > 40:
        add(f"  …余 {len(payload['non_portable']) - 40} 条见 --json")
    add("")
    add("④′ 搬家表面（P2 标的逐符号现算形态）")
    for item in payload["migration_surface"]:
        flag = "⚠" if "不可当数据" in item["form"] or "未在本件" in item["form"] else " "
        add(f"  {flag} {item['target']:<34}{item['form']:<28}"
            f"{item['detail']}（{protocols_rel(payload)}:{item['first_seen_at_line']}）")
    add("")
    add(f"④ 合并冲突（同列两路输入不一致 ⇒ 生产 import 当场炸）= {len(payload['merge_conflicts'])} 条")
    for item in payload["merge_conflicts"][:20]:
        add(f"  {item}")
    add("")
    add("⑤ builders 收集方式（哪些行是字面、哪些是循环派生——派生的搬运等价性最脆）")
    for item in payload["builder_report"]:
        add(f"  {item['builder']:<34}{item['rows']:>4} 行  {item['how']}")
    add("")
    add(f"⑥ 量具自身假设（求值器跳过项，共 {len(payload['assumptions'])} 条）")
    for item in payload["assumptions"][:30]:
        add(f"  · {item}")
    if len(payload["assumptions"]) > 30:
        add(f"  …余 {len(payload['assumptions']) - 30} 条见 --json")
    add("")
    add("⑦ 册侧四件现算（FACETS / EVIDENCE / PLACEHOLDER / CEILING）")
    side = payload["manifest_side"]
    add(f"  FACETS 申报 {len(side['facet_ids'])} 枚；EVIDENCE 票根 {len(side['evidence_keys'])} 枚："
        f"{side['evidence_keys']}")
    add(f"  PLACEHOLDER_UNIMPLEMENTED={side['placeholder']}；UNCOVERED_CEILING={side['uncovered_ceiling']}")
    add("  册↔表交叉账：")
    for row in payload["crosscheck_manifest_vs_table"]:
        add(f"   {row['capability_id']:<28}在册={row['in_table']!s:<5}"
            f"占位点名={row['placeholder_declared']!s:<5}handler_ref={row['handler_ref']}")
    gate = payload["gate_baselines"]
    add("")
    add("⑦′ 与常驻门 G-CM 基线对账（基线从门文件 AST 现读；本件静态重算须落进门的判据区间）")
    if "error" in gate:
        add(f"  ⚠ {gate['error']}")
    else:
        for item in gate["checks"]:
            add(f"  {item['baseline']:<30} 门={item['gate']:<6} 本件={item['projection']!s:<6}"
                f"{item.get('relation',''):<12}{item['verdict']}   {item.get('meaning','')}")
        add(f"  合计：{'全部一致' if gate['all_consistent'] else '有不一致——先怀疑本件'}")
    if "census_crosscheck" in payload:
        add("")
        add("⑧ 与第二把尺（scripts/central_seam_census.py roster）双向对账")
        cross = payload["census_crosscheck"]
        if "error" in cross:
            add(f"  {cross['error']}")
        else:
            add(f"  本件 {cross['mine']} vs 普查 {cross['census']} ⇒ 全等={cross['agree']}")
            add(f"  只在本件：{cross['only_in_projection'] or '（无）'}")
            add(f"  只在普查：{cross['only_in_census'] or '（无）'}")
    add("")
    add("⑨ 三处旧账降垫片的保留面")
    _render_surface(surface, add)
    return "\n".join(out)


def _render_surface(surface: dict[str, Any], add) -> None:
    for key, entry in surface.items():
        add("")
        add(f"· {key}  （{entry['module_path']}）")
        add(f"    模块级公开导出（现算 {len(entry['retained_names_required'])} 枚被真实消费，"
            f"导出面共 {len(entry['public_exports'])} 枚）")
        add(f"    必须保留的导出名：{entry['retained_names_required']}")
        add(f"    模块别名绑定（只要模块可导入、不需保留名）：{entry['module_aliases']}")
        if entry.get("consumed_but_not_exported"):
            add(f"    ⚠ 被取用但不在公开导出面（私有名/动态名，垫片同样要给）："
                f"{entry['consumed_but_not_exported']}")
        add(f"    import 侧取用名：{entry['names_from_imports']}")
        add(f"    属性侧取用名：{entry['names_from_attributes']}")
        add(f"    读取者 {len(entry['importers'])} 处：")
        for item in entry["importers"]:
            add(f"      {item['file']}:{item['line']}  {item['form']} {item['names']}")
        if entry["attribute_loads"]:
            add(f"    属性式取用 {len(entry['attribute_loads'])} 处（前 12）：")
            for item in entry["attribute_loads"][:12]:
                add(f"      {item['file']}:{item['line']}  {item['name']}")
        if entry["string_refs"]:
            add(f"    字符串引用（动态 import / 路径字面）{len(entry['string_refs'])} 处（前 12）：")
            for item in entry["string_refs"][:12]:
                add(f"      {item['file']}:{item['line']}  {item['text']}")
        text_refs = entry.get("text_refs", [])
        if text_refs:
            add(f"    正文提及（含 AST 解析器路径/注释）{len(text_refs)} 处（前 12）：")
            for item in text_refs[:12]:
                add(f"      {item['file']}:{item['line']}  {item['text']}")


# ============================================================================
# 注毒自证：证明本件真有牙（否则"零差集"只是量具瞎了的同义反复）
# ============================================================================

POISONS: tuple[tuple[str, str, str], ...] = (
    ("title", "改一个字的标题", "ROUNDTRIP-VALUE-DIFF"),
    ("gate_feature_id", "改门 id 前缀", "ROUNDTRIP-VALUE-DIFF"),
    ("family", "换枚举成员", "ROUNDTRIP-VALUE-DIFF"),
    ("routes", "删掉一条路由绑定", "ROUNDTRIP-VALUE-DIFF"),
    ("handler_ref", "换成求不出的表达式", "NON-PORTABLE"),
)


def _apply_poison(field_name: str, side_a: dict[str, dict[str, tuple[Any, str]]],
                  extraction: Extraction) -> str:
    """把某一列改出**必定不等**的形态（不是"随便写个值"，那种注毒可能撞上原值而空跑）。"""
    victim = min(side_a)
    row = side_a[victim]
    value, kind = row.get(field_name, ("", P_LITERAL))
    if field_name == "title":
        row["title"] = (str(value) + "【注毒】", kind)
    elif field_name == "gate_feature_id":
        row["gate_feature_id"] = ("poisoned." + str(value), kind)
    elif field_name == "family":
        current = value.name if isinstance(value, EnumMember) else ""
        row["family"] = (EnumMember("CapabilityFamily", "FILES" if current != "FILES" else "MEDIA",
                                    None), kind)
    elif field_name == "routes":
        items = tuple(extraction.routes.get(victim, ()))
        extraction.routes[victim] = list(items[1:])  # 删掉一条路由绑定：条数与内容同时变
    else:
        row["handler_ref"] = (Unresolved("注毒：运行时拼接，静态不可求值"), P_UNRESOLVED)
    return victim


def selftest(census_json: Path | None) -> int:
    """逐发注毒：每发都必须被对应字段抓到，否则退出码 3（量具无牙=结论不作数）。"""
    results: list[tuple[str, str, bool, str]] = []
    for field_name, label, expected in POISONS:
        captured: dict[str, str] = {}

        def poison(side_a: dict[str, dict[str, tuple[Any, str]]], extraction: Extraction,
                   f: str = field_name, cap: dict[str, str] = captured) -> None:
            cap["victim"] = _apply_poison(f, side_a, extraction)

        payload, _code = run(census_json, poison=poison)
        victim = captured.get("victim", "")
        hits = [item for item in payload["diffs"]
                if item["field"] == field_name and item["capability_id"] == victim]
        caught = bool(hits) and any(expected in str(item["verdict"]) for item in hits)
        results.append((field_name, label, caught,
                        hits[0]["verdict"] if hits else "无（注毒未被抓到）"))
    width = max(len(name) for name, _l, _c, _v in results)
    print("注毒自证（每发都必须被自己的字段抓到）：")
    failures = 0
    for name, label, caught, verdict in results:
        mark = "被抓" if caught else "**漏抓**"
        if not caught:
            failures += 1
        print(f"  [{'PASS' if caught else 'FAIL'}] {name:<{width}}  {label:<18} → {mark}，判定={verdict}")
    print(f"  合计 {len(results) - failures}/{len(results)} 发被抓")
    return 0 if failures == 0 else 3


def main(argv: list[str] | None = None) -> int:
    # 本件输出中文与假名：Windows 控制台缺省 GBK，不钉 utf-8 就会在 print 处崩
    # （本仓台账 #47 已为同类问题记过一笔，这里直接从源头钉死，不依赖调用方咒语）。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, OSError):
            pass
    parser = argparse.ArgumentParser(description="能力真身册迁移等值证明量具（纯 AST，零 import）")
    parser.add_argument("--json", action="store_true", help="机器形态输出（同一套数据）")
    parser.add_argument("--report", action="store_true", help="人类可读输出（缺省即此）")
    parser.add_argument("--shim-surface", action="store_true", help="只出借片保留面一节")
    parser.add_argument("--selftest", action="store_true",
                        help="注毒自证：五发毒弹逐发验牙（全抓 0、有漏 3）")
    parser.add_argument("--census-json", type=Path, default=None,
                        help="scripts/central_seam_census.py --json 的快照，用于双向对账")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest(args.census_json)

    surface = shim_surface()
    payload, exit_code = run(args.census_json)
    if args.json:
        print(json.dumps({"projection": payload, "shim_surface": surface},
                         ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_text(payload, surface, shim_only=args.shim_surface))
    if not args.shim_surface and (payload["diffs"] or payload["non_portable"]
                                  or payload["merge_conflicts"]):
        return exit_code
    if args.shim_surface:
        return 0
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
