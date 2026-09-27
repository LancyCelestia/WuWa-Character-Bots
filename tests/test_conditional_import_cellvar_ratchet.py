"""条件导入 cellvar 遮蔽的只读普查棘轮锁（2026-09-27 萌百 NameError 事故线）。

生产实况（她 09-27 12:29「予愿安洁莉娜是谁？」，`detail=bot.moegirl:NameError`）：
`_handle_moegirl_question` 在 `if kb_body:` **分支内**再 `from .contracts import
CapabilityResult, ...`——Python 只认「有没有绑定语句」、不认它在哪个分支，四枚名被绑成
宿主函数的 **cellvar** 并遮蔽模块级同名导入；内层 `capability` 闭包按 **freevar** 向外层
要人；那条分支这一格没跑 ⇒ cell 空 ⇒ 当场炸。ruff F821 拦不住（名字确有绑定），该形态
自 c77b421b 潜伏 18 天。根修与单格锁见 commit `f6b5f3c` +
`tests/test_moegirl_closure_cellvar.py`（本锁沿用的两条量具纠正——async def 双码对象、
闭包名在 co_freevars 不在 co_names——即取自该文件）。

本锁是**整片执法面的普查账**，不是又一枚单格锁。判据三条全中才算一处站点：

  ① `from X import ...` 出现在函数体内、且**不是**函数体的直接语句（嵌在
     if / try / for / while / with / except 等块里——「分支内重复导入」本体）；
  ② 被导入的**源名**在该文件模块级已被导入（遮蔽条件成立）。两种形态都算：
     原名（`from m import CapabilityResult`，闭包直接引用它）与别名
     （`from m import CapabilityResult as _CR`，闭包引用 `_CR`）——f6b5f3c
     排查点名的 `_handle_chat` 那组 `_CR/_PL/_RL/_SP` lambda 是别名形态，
     只按绑定名对模块级会把这组整个漏掉，故别名形态按「源名在模块级」判定、
     闭包按绑定名判定；
  ③ 宿主函数内存在**嵌套函数/lambda** 以闭包方式引用该绑定名——AST 腿认引用，
     字节码腿用「宿主 `co_cellvars` ∋ 名 ∧ 其下某码对象 `co_freevars` ∋ 名」坐实。
     纯局部使用（名字只是宿主自己的快变量）不算本型。
  注：函数体**顶端**（直接子语句、无条件执行）的重复导入不在本型——它每次都跑，
  cell 不可能带着「分支没跑」的空洞被闭包读到。注解表达式一律不计引用（无
  future-import 时注解在定义处的外层作用域求值、有 future-import 时根本不求值，
  两条都不走「闭包向内层要人」这条路）。

执法范围：`plugins/bot_unified_runtime/__init__.py` + `plugins/bot_unified_runtime/
domains/**` 的全部 `*.py`（扩大范围须连同重扫名册，范围与名册同变）。

棘轮口径（名册 == 实扫，双向锁死）：
  甲) 实扫命中而名册没有 ⇒ 红。新同型站点只有两条出路：当场修，或带归属登记；
  乙) 名册在册而实扫已无 ⇒ **也红**。站点被修好就必须摘牌，防「在册留脏」当收口；
  丙) 每枚名册条目必须带归属（哪波/谁复核），不许空值（真不可考才准写「待查」）。
名册身份 =（文件, 宿主函数点分作用域路径, 命中名集合）；行号只是提示、随他波加行
漂移，**不进身份**（本仓坐标账被顶漂咬过多次，故刻意不拿行号当判据）。

AST 命中但字节码不坐实的「分歧站」另立一本账，现算为空、零容忍：那是两腿判据打架，
必须人工裁决，不许静默计入、也不许静默丢弃。

量具陷阱（都已钉成可执行断言，别重犯）：
  - `async def` 的嵌套码对象挂在协程码上、宿主可能有两个同名码对象：AST 侧必须
    同时匹配 `ast.FunctionDef` 与 `ast.AsyncFunctionDef`（见
    `test_detector_catches_synthetic_moegirl_shape` 的 async 标本），字节码侧对
    同名码对象取并集；
  - 闭包引用的名字在 `co_freevars` 而**不在** `co_names`（那张表只装全局名），
    按 `co_names` 筛靶子会把真凶整个筛没——
    `test_synthetic_site_freevar_not_global` 直接断言这一点。

⚠ 名册里的 line_hint 为 2026-09-27 现算当时值；命中枚数一类计数一律以本文件实跑
输出为准，不在叙述处手写（AGENTS 规则 10）。
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

if sys.version_info < (3, 11):  # 本仓生产与门禁都跑 3.12；形态判据依赖 3.10+ AST
    raise RuntimeError("本锁依赖新版 ast.TryStar/ast.Match；请在 3.11+ 解释器上跑")

_REPO = Path(__file__).resolve().parents[1]
_ENTRY_FILE = _REPO / "plugins" / "bot_unified_runtime" / "__init__.py"
_DOMAINS_DIR = _REPO / "plugins" / "bot_unified_runtime" / "domains"


# ---------------------------------------------------------------------------
# 名册（现算于 2026-09-27，S-CELLVAR-CENSUS 席；行号是当时提示值，不进身份）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RosterEntry:
    file: str                       # 仓内 posix 相对路径
    host: str                       # 宿主函数点分作用域路径
    names: frozenset[str]           # 'Source' 或 'Source as Bound'
    line_hint: int                  # 首枚命中 import 的行号（提示，非判据）
    attribution: str                # 哪波/谁复核——不许空

    @property
    def key(self) -> tuple[str, str, frozenset[str]]:
        return (self.file, self.host, self.names)


_ROSTER: tuple[RosterEntry, ...] = (
    RosterEntry(
        file="plugins/bot_unified_runtime/__init__.py",
        host="<module>._register_nonebot_handlers._handle_alias",
        names=frozenset({"build_meme_library_capability"}),
        line_hint=7300,
        attribution=(
            "2026-09-27 萌百 cellvar 根修波（commit f6b5f3c）同型普查在册站点；"
            "本锁编写席当日现算复核坐实（AST+字节码双腿），归表情包库入口 owner 修，"
            "修好后本条必须摘牌"
        ),
    ),
    RosterEntry(
        file="plugins/bot_unified_runtime/__init__.py",
        host="<module>._register_nonebot_handlers._handle_chat",
        names=frozenset({
            "CapabilityResult as _CR",
            "PrivacyLevel as _PL",
            "RiskLevel as _RL",
            "SendPolicy as _SP",
        }),
        line_hint=8559,
        attribution=(
            "2026-09-27 萌百 cellvar 根修波（commit f6b5f3c）排查点名的「_CR/_PL/_RL/_SP "
            "lambda」组，本锁编写席现算复核同格；导入与消费同在 `if parrot_reply:` 块内、"
            "今日不炸≠安全（把 lambda 提出块外或把导入删掉即炸），归 chat 主链 owner 修，"
            "修好后摘牌"
        ),
    ),
    RosterEntry(
        file="plugins/bot_unified_runtime/__init__.py",
        host="<module>._register_nonebot_handlers._handle_natural",
        names=frozenset({"build_meme_library_capability"}),
        line_hint=9558,
        attribution=(
            "2026-09-27 萌百 cellvar 根修波（commit f6b5f3c）同型普查在册站点；"
            "本锁编写席当日现算复核坐实（AST+字节码双腿），归自然语言入口 owner 修，"
            "修好后本条必须摘牌"
        ),
    ),
)

# AST 命中而字节码不坐实的分歧站：现算为空，零容忍（语义见模块 docstring）。
_DISCREPANCY_ROSTER: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# 判据实现（纯只读：只做 ast.parse / compile，绝不 import、绝不执行被扫模块）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Site:
    file: str
    host: str
    names: frozenset[str]
    first_line: int  # 展示用；不参与身份

    @property
    def key(self) -> tuple[str, str, frozenset[str]]:
        return (self.file, self.host, self.names)


def _bound_name(alias: ast.alias) -> str:
    return alias.asname or alias.name.split(".")[0]


def _module_level_imports(tree: ast.Module) -> set[str]:
    """模块级（含顶层 if/try 等块内）import 绑定的名字；不进 def/class 体。"""
    names: set[str] = set()

    def go(body: Iterable[ast.stmt]) -> None:
        for st in body:
            if isinstance(st, (ast.Import, ast.ImportFrom)):
                names.update(
                    _bound_name(a)
                    for a in st.names
                    if not (isinstance(st, ast.ImportFrom) and st.module == "__future__")
                )
            elif isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            elif isinstance(st, ast.If):
                go(st.body)
                go(st.orelse)
            elif isinstance(st, (ast.Try, ast.TryStar)):
                go(st.body)
                for h in st.handlers:
                    go(h.body)
                go(st.orelse)
                go(st.finalbody)
            elif isinstance(st, (ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith)):
                go(st.body)
                go(st.orelse)
            elif isinstance(st, ast.Match):
                for c in st.cases:
                    go(c.body)

    go(tree.body)
    return names


def _future_annotations_active(tree: ast.Module) -> bool:
    return any(
        isinstance(st, ast.ImportFrom)
        and st.module == "__future__"
        and any(a.name == "annotations" for a in st.names)
        for st in tree.body
    )


def _store_names(node: ast.expr | None) -> set[str]:
    out: set[str] = set()

    def add(t: object) -> None:
        if isinstance(t, ast.Name):
            out.add(t.id)
        elif isinstance(t, (ast.Tuple, ast.List)):
            for e in t.elts:
                add(e)
        elif isinstance(t, ast.Starred):
            add(t.value)

    if node is not None:
        add(node)
    return out


class _Scope:
    __slots__ = ("bindings", "children", "imports", "kind", "loads",
                 "name", "node", "parent", "path")

    def __init__(self, kind: str, name: str, path: str,
                 parent: _Scope | None, node: ast.AST | None):
        self.kind = kind          # module|func|asyncfunc|lambda|class|comp
        self.name = name
        self.path = path
        self.parent = parent
        self.node = node
        self.bindings: set[str] = set()
        self.children: list[_Scope] = []
        # (ImportFrom, 直接包裹它的复合语句 | None=函数体直接子语句)
        self.imports: list[tuple[ast.ImportFrom, ast.stmt | None]] = []
        self.loads: set[str] = set()  # 本作用域**直接**读取（Load）的名字

    def callable_descendants(self) -> list[_Scope]:
        """宿主之下所有嵌套函数/lambda（class/comprehension 只穿道、不当引用人）。"""
        out: list[_Scope] = []
        stack = list(self.children)
        while stack:
            c = stack.pop()
            if c.kind in ("func", "asyncfunc", "lambda"):
                out.append(c)
            stack.extend(c.children)
        return out


class _ScopeBuilder:
    """最小作用域模型，只服务三条判据。

    本腿刻意**宽**：只收集「宿主之上有条件导入」「某层闭包读过这个名字」两个事实，
    收窄一律交给字节码腿（co_cellvars/co_freevars 是编译器的最终判决）。宽判多出的
    候选会被字节码腿挡成分歧站、当场点名——宁可吵，不可默。
    """

    def __init__(self, tree: ast.Module, skip_annotations: bool):
        # skip_annotations=True（future-import annotations 在场）：注解不求值，
        # 整棵注解子树一律不看；False：注解在定义处求值，按「外层读取」看——
        # 两种都不进 ③ 的闭包面（③ 只数嵌套函数/lambda 自己的读取）。
        self.skip_ann = skip_annotations
        self.root = _Scope("module", "<module>", "<module>", None, tree)
        self.all_scopes: list[_Scope] = [self.root]
        self._go(tree.body, self.root, None)

    def _new(self, kind: str, name: str, parent: _Scope, node: ast.AST) -> _Scope:
        s = _Scope(kind, name, f"{parent.path}.{name}", parent, node)
        parent.children.append(s)
        self.all_scopes.append(s)
        return s

    # ---- 表达式 ----------------------------------------------------------
    def _expr(self, node: ast.AST | None, scope: _Scope) -> None:
        if node is None:
            return
        stack = [node]
        while stack:
            n = stack.pop()
            if isinstance(n, ast.Name):
                if isinstance(n.ctx, ast.Load):
                    scope.loads.add(n.id)
                continue
            if isinstance(n, ast.Lambda):
                a = n.args
                for d in list(a.defaults) + list(a.kw_defaults):
                    self._expr(d, scope)  # 缺省值在**外层**求值
                inner = self._new("lambda", "<lambda>", scope, n)
                self._record_params(a, inner)
                self._expr(n.body, inner)
                continue
            if isinstance(n, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
                inner = self._new("comp", "<comp>", scope, n)
                for i, g in enumerate(n.generators):
                    self._expr(g.iter, scope if i == 0 else inner)
                    inner.bindings |= _store_names(g.target)
                    for cnd in g.ifs:
                        self._expr(cnd, inner)
                if isinstance(n, ast.DictComp):
                    self._expr(n.key, inner)
                    self._expr(n.value, inner)
                else:
                    self._expr(n.elt, inner)
                continue
            if isinstance(n, ast.NamedExpr):
                scope.bindings |= _store_names(n.target)
                self._expr(n.value, scope)
                continue
            for c in ast.iter_child_nodes(n):
                if isinstance(c, ast.expr):
                    stack.append(c)
                elif isinstance(c, ast.keyword):
                    # keyword 的值不是 ast.expr 子类——漏掉它会把
                    # `privacy_level=_PL.GROUP` 这类真引用整个丢掉（实测坑①）。
                    stack.append(c.value)

    @staticmethod
    def _record_params(a: ast.arguments, scope: _Scope) -> None:
        for p in a.posonlyargs + a.args + a.kwonlyargs:
            scope.bindings.add(p.arg)
        if a.vararg:
            scope.bindings.add(a.vararg.arg)
        if a.kwarg:
            scope.bindings.add(a.kwarg.arg)

    # ---- 语句 -------------------------------------------------------------
    def _go(self, body: Iterable[ast.stmt], scope: _Scope, parent_stmt: ast.stmt | None) -> None:
        for st in body:
            self._stmt(st, scope, parent_stmt)

    def _stmt(self, st: ast.stmt, scope: _Scope, parent: ast.stmt | None) -> None:
        if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # 装饰器/缺省值/（无 future-import 的）注解都在外层作用域求值：
            # 它们的读取记在 scope、不记进 inner——本型要的是闭包读取，不收这些。
            for d in st.decorator_list:
                self._expr(d, scope)
            a = st.args
            for d in list(a.defaults) + list(a.kw_defaults):
                self._expr(d, scope)
            if not self.skip_ann:
                # future-import annotations 在场时注解整棵不求值——一个字都不看；
                # 不在场时按定义处外层求值处理（不是闭包读取）。
                for p in a.posonlyargs + a.args + a.kwonlyargs:
                    self._expr(p.annotation, scope)
                if a.vararg:
                    self._expr(a.vararg.annotation, scope)
                if a.kwarg:
                    self._expr(a.kwarg.annotation, scope)
                self._expr(st.returns, scope)
            scope.bindings.add(st.name)
            kind = "asyncfunc" if isinstance(st, ast.AsyncFunctionDef) else "func"
            inner = self._new(kind, st.name, scope, st)
            self._record_params(a, inner)
            self._go(st.body, inner, None)
        elif isinstance(st, ast.ClassDef):
            for d in st.decorator_list:
                self._expr(d, scope)
            for base in st.bases:
                self._expr(base, scope)
            for kwd in st.keywords:
                self._expr(kwd.value, scope)
            scope.bindings.add(st.name)
            cls = self._new("class", st.name, scope, st)
            self._go(st.body, cls, None)
        elif isinstance(st, (ast.Import, ast.ImportFrom)):
            for al in st.names:
                scope.bindings.add(_bound_name(al))
            if isinstance(st, ast.ImportFrom) and scope.kind in ("func", "asyncfunc"):
                scope.imports.append((st, parent))
        elif isinstance(st, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = st.targets if isinstance(st, ast.Assign) else [st.target]
            for t in targets:
                scope.bindings |= _store_names(t)
            self._expr(st.value, scope)
        elif isinstance(st, (ast.For, ast.AsyncFor)):
            self._expr(st.iter, scope)
            scope.bindings |= _store_names(st.target)
            self._go(st.body, scope, st)
            self._go(st.orelse, scope, st)
        elif isinstance(st, (ast.While, ast.If)):  # 同体：test + body + orelse
            self._expr(st.test, scope)
            self._go(st.body, scope, st)
            self._go(st.orelse, scope, st)
        elif isinstance(st, (ast.With, ast.AsyncWith)):
            for item in st.items:
                self._expr(item.context_expr, scope)
                scope.bindings |= _store_names(item.optional_vars)
            self._go(st.body, scope, st)
        elif isinstance(st, (ast.Try, ast.TryStar)):
            self._go(st.body, scope, st)
            for h in st.handlers:
                self._expr(h.type, scope)
                if h.name:
                    scope.bindings.add(h.name)
                self._go(h.body, scope, h)
            self._go(st.orelse, scope, st)
            self._go(st.finalbody, scope, st)
        elif isinstance(st, (ast.Expr, ast.Return)):
            self._expr(st.value, scope)
        elif isinstance(st, ast.Raise):
            self._expr(st.exc, scope)
            self._expr(st.cause, scope)
        elif isinstance(st, ast.Assert):
            self._expr(st.test, scope)
            self._expr(st.msg, scope)
        elif isinstance(st, ast.Delete):
            for t in st.targets:
                self._expr(t, scope)
        elif isinstance(st, ast.Match):
            self._expr(st.subject, scope)
            for c in st.cases:
                for sub in ast.walk(c.pattern):
                    if isinstance(sub, (ast.MatchAs, ast.MatchStar)) and sub.name:
                        scope.bindings.add(sub.name)
                    elif isinstance(sub, ast.MatchMapping) and sub.rest:
                        scope.bindings.add(sub.rest)
                    elif isinstance(sub, ast.MatchValue):
                        self._expr(sub.value, scope)
                self._expr(c.guard, scope)
                self._go(c.body, scope, c)
        else:  # Global/Nonlocal/Pass/Break/Continue 及未见形态
            for c in ast.iter_child_nodes(st):
                if isinstance(c, ast.expr):
                    self._expr(c, scope)
                elif isinstance(c, ast.keyword):
                    self._expr(c.value, scope)


def _code_tree(code) -> tuple[dict[str, list], dict[int, list]]:
    """co_name -> [码对象] 与 parent->children；同名取并集，async 双码不漏（实测坑②）。"""
    by_name: dict[str, list] = {}
    kids: dict[int, list] = {}

    def walk(obj) -> None:
        by_name.setdefault(obj.co_name, []).append(obj)
        lst = [c for c in obj.co_consts if hasattr(c, "co_consts")]
        kids[id(obj)] = lst
        for c in lst:
            walk(c)

    walk(code)
    return by_name, kids


def _byte_descendants(obj, kids: dict[int, list]) -> list:
    out: list = []
    stack = [obj]
    while stack:
        c = stack.pop()
        out.append(c)
        stack.extend(kids.get(id(c), []))
    return out


def _scan_source(label: str, src: str) -> tuple[list[Site], list[str]]:
    """对单份源码跑双腿判据。label 为展示名（真实扫描给仓内相对路径）。"""
    tree = ast.parse(src)
    mod_names = _module_level_imports(tree)
    builder = _ScopeBuilder(tree, _future_annotations_active(tree))
    code = compile(src, label, "exec")
    by_name, kids = _code_tree(code)

    grouped: dict[tuple[str, str, str], int] = {}  # (file, host, label_name) -> min line
    discrepancies: list[str] = []
    for scope in builder.all_scopes:
        if scope.kind not in ("func", "asyncfunc"):
            continue
        host_codes = by_name.get(scope.name, [])
        cells: set[str] = set()
        nested_free: set[str] = set()
        for hc in host_codes:
            cells |= set(hc.co_cellvars)
            for d in _byte_descendants(hc, kids):
                if d is not hc:
                    nested_free |= set(d.co_freevars)
        callables_ = scope.callable_descendants()
        for imp, parent in scope.imports:
            if parent is None:
                continue  # 判据①：函数体顶端的无条件导入不算本型
            for al in imp.names:
                if al.name == "*":
                    continue
                bound = _bound_name(al)
                if al.name not in mod_names:
                    continue  # 判据②：源名模块级未导入（别名形态按源名判）
                if not any(bound in d.loads for d in callables_):
                    continue  # 判据③(AST)：无嵌套函数/lambda 读它
                label_name = al.name if bound == al.name else f"{al.name} as {bound}"
                if bound in cells and bound in nested_free:  # 判据③(字节码坐实)
                    key = (label, scope.path, label_name)
                    grouped[key] = min(grouped.get(key, imp.lineno), imp.lineno)
                else:
                    discrepancies.append(
                        f"{label}:L{imp.lineno} host={scope.path} name={label_name} "
                        f"(AST 命中但字节码不坐实: in_cellvars={bound in cells} "
                        f"in_nested_freevars={bound in nested_free})"
                    )
    # 同 (file, host) 的多枚名字并成一枚站点；行号取最小，仅作展示
    merged: dict[tuple[str, str], tuple[set[str], list[int]]] = {}
    for (f, host, label_name), line in grouped.items():
        bucket = merged.setdefault((f, host), (set(), [line]))
        bucket[0].add(label_name)
        bucket[1].append(line)
    sites = [
        Site(file=f, host=host, names=frozenset(ns), first_line=min(lines))
        for (f, host), (ns, lines) in merged.items()
    ]
    sites.sort(key=lambda s: (s.file, s.first_line, s.host))
    return sites, discrepancies


def _scan_targets() -> list[Path]:
    assert _ENTRY_FILE.is_file(), f"执法面缺根文件：{_ENTRY_FILE}"
    assert _DOMAINS_DIR.is_dir(), f"执法面缺 domains 目录：{_DOMAINS_DIR}"
    return [_ENTRY_FILE] + sorted(_DOMAINS_DIR.rglob("*.py"))


_CENSUS: tuple[list[Site], list[str]] | None = None


def _live_census() -> tuple[list[Site], list[str]]:
    """对执法范围全量现算（一次缓存）。任何文件 parse/compile 失败 ⇒ 当场红。

    不许 try/skip——他席正在写盘导致半截语法也是「现在不能宣称账实相符」，
    红得明明白白比绿得含糊要紧。
    """
    global _CENSUS
    if _CENSUS is not None:
        return _CENSUS
    sites: list[Site] = []
    discrepancies: list[str] = []
    failures: list[str] = []
    for path in _scan_targets():
        rel = path.relative_to(_REPO).as_posix()
        try:
            src = path.read_text(encoding="utf-8")
            got_sites, got_disc = _scan_source(rel, src)
        except (SyntaxError, ValueError, RecursionError, UnicodeDecodeError) as exc:
            failures.append(f"{rel}: {type(exc).__name__}: {exc}")
            continue
        sites.extend(got_sites)
        discrepancies.extend(got_disc)
    assert not failures, (
        "执法面有文件不可解析/编译——普查账此刻不可信，请人查（多半是他席在写盘）：\n"
        + "\n".join(failures)
    )
    sites.sort(key=lambda s: (s.file, s.first_line, s.host))
    _CENSUS = (sites, discrepancies)
    return _CENSUS


def _fmt(key: tuple, line: int | None = None) -> str:
    f, host, names = key
    where = f"L{line}" if line is not None else "L?"
    return f"{f}:{where}  host={host}  names={sorted(names)}"


def _sort_keys(keys: Iterable[tuple]) -> list[tuple]:
    # 第三元是 frozenset，直接 sorted() 在同 (file,host) 时拿 < 比集合会 TypeError
    return sorted(keys, key=lambda k: (k[0], k[1], sorted(k[2])))


def _compare(computed: Iterable[Site], roster: Iterable[RosterEntry]):
    comp_keys = {s.key for s in computed}
    ros_keys = {(r.file, r.host, r.names) for r in roster}
    return _sort_keys(comp_keys - ros_keys), _sort_keys(ros_keys - comp_keys)


# ---------------------------------------------------------------------------
# 执法（三腿：账实相符 / 分歧站零容忍 / 名册自身卫生）
# ---------------------------------------------------------------------------


def test_ratchet_ledger_matches_live_census_both_directions() -> None:
    """甲乙两腿同时执法：名册外新命中 ⇒ 红；在册已修不摘牌 ⇒ 也红。"""
    sites, discrepancies = _live_census()
    extra, stale = _compare(sites, _ROSTER)
    msgs = []
    if extra:
        live_line = {s.key: s.first_line for s in sites}
        msgs.append(
            "【甲·新站点】实扫出现名册外命中——同型分支导入不许无痕增长。两条出路只许"
            "选一条：① 删掉分支内重复导入（源名模块级已在的，直接删即可，萌百那格的"
            "根修就是删六行）；② 在本文件 _ROSTER 追加条目并带归属（哪波/谁复核）。\n"
            + "\n".join("  + " + _fmt(k, live_line.get(k)) for k in extra)
        )
    if stale:
        hint_line = {(r.file, r.host, r.names): r.line_hint for r in _ROSTER}
        msgs.append(
            "【乙·摘牌】名册在册而实扫已无——站点已被修好（或宿主被改名/文件被搬），"
            "必须删掉该条并把修复哈希或复跑记进台账；留着条目 = 把「在册」当「已收口」。"
            "（括号行号为登记当时的名册提示值。）\n"
            + "\n".join("  - " + _fmt(k, hint_line.get(k)) for k in stale)
        )
    if discrepancies != list(_DISCREPANCY_ROSTER):
        msgs.append(
            "【分歧站】AST 命中而字节码不坐实——两腿判据打架，须人工裁决（写清为何"
            "不算本型或修掉形状），不许静默计入、也不许改判据绕开：\n"
            + "\n".join("  ? " + d for d in discrepancies)
        )
    assert not msgs, "\n".join(msgs)


def test_roster_entries_carry_attribution_and_identity() -> None:
    """丙腿：名册条目归属非空、文件在执法面内、宿主是完整作用域链、无重复身份。"""
    problems: list[str] = []
    allowed_prefix = "plugins/bot_unified_runtime/"
    seen: set[tuple] = set()
    for r in _ROSTER:
        if not r.attribution or not r.attribution.strip():
            problems.append(f"{r.file}:{r.host} 归属为空（真不可考才准写「待查」）")
        if not r.file.startswith(allowed_prefix):
            problems.append(f"{r.file} 不在执法面（{allowed_prefix}…）内")
        if not r.host.startswith("<module>."):
            problems.append(f"{r.file}:{r.host} 宿主路径不是完整作用域链")
        if not r.names or any((not n) or ("  " in n) for n in r.names):
            problems.append(f"{r.file}:{r.host} 命中名集合畸形")
        key = (r.file, r.host, r.names)
        if key in seen:
            problems.append(f"名册身份重复：{_fmt(key)}")
        seen.add(key)
    assert not problems, "\n".join(problems)


def test_domains_face_sites_equal_rostered_domain_entries() -> None:
    """domains 面单独点名（现算零命中）：日后扫出命中时本条与棘轮一起红，
    提醒如实跟账，别把 domains 悄悄移出执法面来变绿。"""
    sites, _ = _live_census()
    live = {(s.file, s.host, s.names) for s in sites if "/domains/" in s.file}
    ros = {(r.file, r.host, r.names) for r in _ROSTER if "/domains/" in r.file}
    assert live == ros, (
        f"domains 面账实不符：实扫 {sorted(live)} vs 名册 {sorted(ros)}"
    )


# ---------------------------------------------------------------------------
# 杀伤力自证（全部喂合成源码；生产文件一个字都不碰）
# ---------------------------------------------------------------------------

# 与萌百崩格同形的最小标本：async 宿主 + 分支内重复导入 + 嵌套闭包引用。
# async 与 FunctionDef 的双形态判据、以及「引用名在 co_freevars 不在 co_names」
# 两条量具教训，都由这一枚标本连带执法。
_POISON_SRC = '''\
from json import dumps


async def host(flag):
    if flag:
        from json import dumps  # 分支内重复导入：名字绑成宿主 cellvar

    def inner(x):
        return dumps(x)  # 闭包按 freevar 向外层要人

    return inner
'''

# 别名形态（`_handle_chat` 的 `_CR/_PL/_RL/_SP` 那组就是它）。
_POISON_SRC_ALIAS = '''\
from json import dumps


def host(flag):
    if flag:
        from json import dumps as _D

    fn = lambda x: _D(x)
    return fn
'''


def _poison_site_keys(src: str) -> tuple[list[Site], list[str]]:
    return _scan_source("synthetic", src)


def test_detector_catches_synthetic_async_site() -> None:
    sites, discrepancies = _poison_site_keys(_POISON_SRC)
    assert not discrepancies, discrepancies
    assert len(sites) == 1, f"注入的同型站点没被抓到：{sites}"
    assert sites[0].host == "<module>.host"
    assert sites[0].names == frozenset({"dumps"})


def test_detector_catches_synthetic_alias_site() -> None:
    sites, discrepancies = _poison_site_keys(_POISON_SRC_ALIAS)
    assert not discrepancies, discrepancies
    assert len(sites) == 1, f"别名形态漏检：{sites}"
    assert sites[0].names == frozenset({"dumps as _D"})


def test_negative_controls_three_shapes_are_not_sites() -> None:
    # (a) 函数体顶端的无条件导入——每次都执行，非本型（判据①的边界）
    top = (
        "from json import dumps\n\n\ndef host(flag):\n"
        "    from json import dumps\n\n"
        "    def inner(x):\n        return dumps(x)\n    return inner\n"
    )
    # (b) 分支内导入但源名模块级没有——判据②不成立（那是「条件局部」另一本账）
    noshadow = (
        "def host(flag):\n    if flag:\n        from json import dumps\n\n"
        "    def inner(x):\n        return dumps(x)\n    return inner\n"
    )
    # (c) 分支内遮蔽导入、但只有局部使用没有闭包——判据③不成立
    noclosure = (
        "from json import dumps\n\n\ndef host(flag):\n"
        "    if flag:\n        from json import dumps\n        return dumps(1)\n"
        "    return None\n"
    )
    # (d) 名字只出现在嵌套函数的**注解**里——注解在定义处外层求值（或被
    #     future-import 整个不评），不走「闭包向内层要人」这条路，不算 ③
    annonly = (
        "from json import dumps\n\n\ndef host(flag):\n"
        "    if flag:\n        from json import dumps\n\n"
        "    def inner(x: dumps = None) -> dumps:\n        return None\n"
        "    return inner\n"
    )
    for name, src in (("top-level", top), ("no-shadow", noshadow),
                      ("no-closure", noclosure), ("annotation-only", annonly)):
        sites, discrepancies = _scan_source(name, src)
        assert not sites, f"{name} 不该命中却给出：{sites}"
        assert not discrepancies, f"{name} 不该有分歧却给出：{discrepancies}"


def test_synthetic_site_freevar_not_global() -> None:
    """量具教训钉死：闭包名在 co_freevars、不在 co_names。按 co_names 筛=失明。"""
    code = compile(_POISON_SRC, "synthetic", "exec")

    def _walk(obj):
        yield obj
        for c in obj.co_consts:
            if hasattr(c, "co_consts"):
                yield from _walk(c)

    hosts = [c for c in _walk(code) if c.co_name == "host"]
    assert hosts, "标本里找不到 host 码对象"
    inner = next(
        (c for hc in hosts for c in _walk(hc) if c is not hc and c.co_name == "inner"),
        None,
    )
    assert inner is not None, "找不到 inner（async 双码形态变了？连本文件判据一起复核）"
    assert "dumps" in inner.co_freevars
    assert "dumps" not in inner.co_names, (
        "标本前提被换：名字进了全局名表——co_names 陷阱锁失效，须复核"
    )


def test_shape_really_raises_when_branch_skipped() -> None:
    """崩形实证：分支没跑 → 闭包一调就 NameError。本普查盯的是真崩溃面，非风格洁癖。"""
    ns: dict = {}
    specimen = (
        "from json import dumps\n\n\ndef host(flag):\n"
        "    if flag:\n        from json import dumps\n\n"
        "    def inner(x):\n        return dumps(x)\n    return inner\n"
    )
    # 内存标本、不落盘不碰生产码——本条正是「崩形真实存在」的实证，只能 exec。
    exec(compile(specimen, "specimen", "exec"), ns)  # noqa: S102
    closure = ns["host"](False)  # 走 `if flag:` 不成立的那格——cell 未填
    try:
        closure({"a": 1})
    except NameError as exc:
        assert "free variable" in str(exc) and "dumps" in str(exc), exc
    else:
        raise AssertionError(
            "注入的同型站点没炸——判据标本与生产崩形已脱钩，连本锁一起复核"
        )


def test_ratchet_leg_kills_added_site_and_stale_entry() -> None:
    """棘轮腿的杀伤力（对着内存账演，不碰盘上任何文件）：多一枚⇒甲红、少一枚⇒乙红。"""
    sites, _ = _poison_site_keys(_POISON_SRC)
    roster = [
        RosterEntry(s.file, s.host, s.names, s.first_line, "test-only attribution")
        for s in sites
    ]
    extra, stale = _compare(sites, roster)
    assert not extra and not stale, "账实相符的基线演示本身破了"

    fake = Site("plugins/bot_unified_runtime/domains/fake/x.py",
                "<module>.host", frozenset({"Thing"}), 1)
    extra, stale = _compare(list(sites) + [fake], roster)
    assert extra and not stale, "名册外新增命中没被甲腿抓到"

    extra, stale = _compare([], roster)
    assert stale and not extra, "修好不摘牌没被乙腿抓到"


def test_live_roster_survives_line_drift_in_identity() -> None:
    """身份不含行号：他波在站点之上加行不许惊动本锁（名册只认 文件/宿主/名集合）。"""
    sites, _ = _live_census()
    by_key = {s.key: s for s in sites}
    for r in _ROSTER:
        assert r.key in by_key, f"名册条目不在实扫里（该走乙腿摘牌）：{_fmt(r.key, r.line_hint)}"
        # line_hint 只当历史值陈述；漂了不红（身份无行号），真值以实扫 first_line 为准。
