"""中央缝外直呼点普查（S01 量具件 · AST 静态解析，零运行时 import 生产模块）。

一句话——对 ``plugins/**`` 与 ``tests/**`` 逐文件静态解析，为每个能力 id 回答三问：
  ① 是否经中央汇合缝（``_run_capability_through_pipeline`` / ``orchestrated_command``
     / adapter 的 command|prepared 申报形）；
  ② 缝外直呼点在哪（``handle*`` / ``build_*_capability`` / descriptor
     ``implementation_ref`` 所指能力模块函数真身 —— 文件:行号 + 语境标签）；
  ③ 入口形态（命令 / 别名 / 自然语言 / 主动投递 / 语音回执，按缝调用点的包络函数链判定）。

三态判据（production 面；tests 面只记证据、不改态）：
  wired    —— invoke 字面点 ∪ 汇合缝调用点（id 字面绑定）∪ execution 申报
              （adapter ∈ {command, prepared}；缺省 adapter 值现读
              ``CapabilityExecution`` 类定义，不在此抄第二份）；
  generic  —— 泛型执行器 ``pipeline.handle_async`` 上的 capability_id 字面量，且 ¬wired；
  offseam  —— ¬wired ∧ ¬generic ∧ 存在该真身的缝外直呼点；
  none     —— 三态皆空（在册未接）。
与基线尺的口径差（如实，不藏）：基线 ``orchestration_wired_census`` 把
``_run_simple_capability`` 的 capability_id 字面量记 generic_executor；本件把它记 wired——
该函数体内（根 ``__init__.py``:8531-8537）恒经 ``orchestrated_command`` 入中央缝，
"存在性归 generic、活性归缝"正是本波要拆开量的一对。差值逐枚可由
``--json`` 的 sites 明细复核。

缺件即红：REQUIRED_FILES 任何一份缺失/读不出/解析失败 ⇒ 退出码 2；
扫描面内任何被载入文件解析失败/读不出 ⇒ 同样记红点名，**绝不默认成"无调用点"**。
对账：``--baseline-json`` 吃 ``scripts/orchestration_wired_census.py --json`` 的快照，
输出「本件 id 全集 vs 基线 id 全集」双向差集 + 态交叉表（差集必须显式列出）。
注毒牙：``--poison FILE``（可重复）把仓外合成件并入生产扫描面——缝外直呼必被抓；
``--fail-on-violations`` 让「已通电却直呼真身」(wired ∧ exec-bypass) 从报告升级为退出码 3。

v0.2.0（S81 2026-09-24「unknown_ids 到底是什么」）——两处，**方向都是加账、不减扫描面**：
  · 判据⑦ 除记 id 外，另记每处落点及其**形态**（routed / record）；并新增判据⑧「变量携带」：
    ``capability_id = "<字面量>"`` 赋值 + 同一作用域链把该变量交给执行点。此前 ``/bot`` 派发表
    （根 ``__init__.py::_handle_status`` 一条缝收 30+ 分支）的 id 全部只以"幽灵 id"名义出现、
    零坐标，现按 routed 入账。分档输出 ``unknown_id_partition``，带 ``covers_exactly`` 不变量
    （routed ∪ record_only 必须**恰好**等于 unknown_ids）。
    ⚠ ``unknown_ids`` 本身一字不删：record_only 是"这枚不是债"的**判据可派生说明**，不是白名单、
    更不是把账抹掉。
  · 修 ``_state`` 的 ``list & set`` TypeError：``execution`` 已申报 ∧ 无 seam/invoke 证据 这条组合
    会把整把尺打死（收编波施工中间态必踩；S67 门只会报"量具跑不起来"，不报根因）。
    判据未动，只把类型对上；``roster[*].decl.adapters`` 仍出 sorted list，出口形状不变。
  · 刻意**未**把同步 ``pipeline.handle`` 并入 ``GENERIC_FUNCS``：那会把一批 id 从 ``none`` 搬进
    ``generic``＝动三态账的形状，属判据改判、需人裁（见 SEAT-S81 §6-R2）。它只在
    ``SITE_EXEC_FUNCS``（unknown 形态分档专用）里被认，不喂 ``_state``。

v0.3.0（S200 2026-09-24「非能力署名标签显式桶」，用户裁定 2.A）——一处，**方向是销噪声、不减扫描面**：
  · 新增 ``SIGNATURE_LABEL_IDS`` 登记处（唯一 authoring 真身）＋派生判据 ``_derived_signature_ids``：
    把「只在根上作 ``SendRequest``/``AuditRecord``/``_log_runtime_event`` 落款、全仓无任何执行点」
    的 id 判成**非能力署名标签**——① 不入真身册、② 不计入「在册表外」差集（``unknown_ids`` 现算
    48 → 摘出登记处 5 枚 → 43）、③ **仍逐枚留在 roster + signature_label_sites 明细里**（不许隐身）。
    ⚠ 桶不是豁免抽屉：实际摘出 = claimed ∩ derived（派生没证的绝不因被申报就消失），
    且只摘 authoring 明确认领的（record_only 里其余未认领者照旧留在差集）；反向锁 + 方向棘轮见
    ``tests/test_signature_label_bucket.py``。routed ∪ record_only 现恰好划分**去掉桶后**的差集，
    ``covers_exactly`` 不变量随之仍成立（S81 锁读的是本件自报的 ``unknown_ids``/``unknown_id_sites``，
    两者一并收敛到 off_manifest，等式不破）。

判据点位（尺身份三元组的「件」，全部现读不抄）：
  申报源      plugins/bot_unified_runtime/runtime/capability_protocols.py
              plugins/bot_unified_runtime/domains/chat_reply/runtime/capability_registry.py
  汇合缝      plugins/bot_unified_runtime/__init__.py::_run_capability_through_pipeline
              runtime/capability_protocols.py::orchestrated_command
  泛型执行器  pipeline.handle_async（域内裸调 = 第二通路嫌疑）
复用不复制（铁律 6「禁第二真身」）：invoke 字面判据与 v1 门
``tests/test_orchestration_callsite_single.py::_invoker_cids`` 同形，provider 注入
豁免与 ``_is_injection`` 同形——本件是**量具**（报告），常驻执法归该门与七腿门，勿混。

复跑命令（环境咒语见 .superpowers/sdd/2026-09-24-central-dispatch/BRIEFS.md 前言）：
  PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8 \
  PYTHONPYCACHEPREFIX="$TEMP/s01-pyc" ../ChatBot_Runtime/venv/Scripts/python.exe \
      scripts/central_seam_census.py --report
  … 同上 … scripts/central_seam_census.py --json --baseline-json "$TEMP/s01-baseline.json"
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import time
from pathlib import Path
from typing import TypeAlias

#: 函数定义节点的并集（typeshed 里 AsyncFunctionDef 与 FunctionDef 同级，不能只写后者）。
_Fn: TypeAlias = ast.FunctionDef | ast.AsyncFunctionDef

VERSION = "0.3.0-beta1"

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG_ROOT = REPO_ROOT / "plugins" / "bot_unified_runtime"

#: 缺件即红的必备文件（相对包根）。
REQUIRED_FILES: tuple[str, ...] = (
    "runtime/capability_protocols.py",  # 唯一在册表 + orchestrated_command 真身
    "domains/chat_reply/runtime/capability_registry.py",  # route execution 申报 + CapabilityExecution
    "__init__.py",  # 根汇合缝
)
#: 中央壳自身：壳内直呼不算缝外直呼（v1 门 _SHELL_REL 同形）。
SHELL_REL = "plugins/bot_unified_runtime/runtime/capability_protocols.py"
#: 声明源（只在这两份里抽 descriptor / execution 申报行）。
DECL_FILES = (
    "plugins/bot_unified_runtime/runtime/capability_protocols.py",
    "plugins/bot_unified_runtime/domains/chat_reply/runtime/capability_registry.py",
)

#: 汇合缝调用点：pos=允许出现 id 字面量位置参的下标；default=无 capability_id 关键字时的形参缺省值。
SEAM_FUNCS: dict[str, dict[str, object]] = {
    "orchestrated_command": {"pos": (0,), "kw": "capability_id"},
    "_run_capability_through_pipeline": {"pos": (), "kw": "capability_id"},
    "_run_simple_capability": {"pos": (3,), "kw": "capability_id"},
    "_send_text_through_unified_pipeline": {"pos": (), "kw": "capability_id", "default": "bot.file"},
    "_send_parts_through_unified_pipeline": {"pos": (), "kw": "capability_id", "default": "bot.poke"},
    "_send_files_through_unified_pipeline": {"pos": (), "kw": "capability_id", "default": "bot.file"},
}
GENERIC_FUNCS = frozenset({"handle_async"})
PUSH_FUNCS = frozenset({"submit_active_push"})

#: 「这一点是不是把能力交出去执行」的**只用于 unknown_ids 形态分档**的执行点集。
#: ⚠ 刻意**不**喂 ``_state()``：把同步的 ``pipeline.handle`` 并进 ``GENERIC_FUNCS`` 会把
#: 一批 id 从 ``none`` 搬到 ``generic``＝动了三态账的形状，那属于判据改判、要人裁（S81 §6-R2），
#: 不由量具席单方面做。这里多认一枚 ``handle`` 只会**增加** routed 证据，不会减少任何债。
#: 依据：根汇合缝自己就调 ``pipeline.handle(message, capability, capability_id=...)``
#: （``__init__.py``:2581），它与 ``handle_async`` 是同一泛型执行器的同/异步两形。
SITE_EXEC_FUNCS = frozenset(SEAM_FUNCS) | GENERIC_FUNCS | frozenset({"handle", "invoke"})

_ALIAS_FN = "_handle_alias"
_NATURAL_FN = "_handle_natural"
_VOICE_FN = "_attach_voice_reply"
_CAPFUNC_RE = re.compile(r"^(?:_?handle_(?!async$)\w+|_?build_\w*_capability\w*)$")
_IDISH_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.\-]*\.[A-Za-z][A-Za-z0-9_.\-]+$")
_BUILDER_FN_RE = re.compile(r"^_?build_\w*$")

#: 预筛子串（并集超集——RF2-5 教训：宁可多载入，绝不因预筛漏文件；符号名在第二遍并入）。
_BASE_MARKERS = (
    "capability_id",
    "handle_async(",
    "_run_simple_capability(",
    "orchestrated_command(",
    "_run_capability_through_pipeline(",
    "_send_text_through_unified_pipeline(",
    "_send_parts_through_unified_pipeline(",
    "_send_files_through_unified_pipeline(",
    "submit_active_push(",
    "invoke(",
)

# ===========================================================================
# 非能力署名标签登记处（S200 · 用户裁定 2.A：把纯落款 id 判成非能力标签，给一个显式桶）
# ---------------------------------------------------------------------------
# 一句话：下面这几枚 id 字面量只是「落款」——某条主动投递 / 审计 / 运行日志记录对象上
#   署名用的 capability_id 字段值（``SendRequest`` / ``AuditRecord`` / ``_log_runtime_event``），
#   全仓从不把它们交给任何执行点（缝 / 泛型 handle(_async) / invoke / descriptor execution）。
#   它们因此**不是能力**：调度层不会、也不该按这个 id 去寻址一条能力；把它们算进
#   「在册表外」差集，等于让尺把"记录字段的署名"谎报成"未接的债"。
# 语义（三条，逐条可机检，见 tests/test_signature_label_bucket.py）：
#   ① 不入唯一真身册（self.decls）——它们本就不是在册能力，被申报也进不了册；
#   ② 不计入「在册表外」差集（unknown_ids）——普查的 headline 债数把它们摘出去；
#   ③ **仍出现在普查明细里**（roster 行 + signature_label_sites）——**不许隐身**：
#      隐身就再也查不到，这正是"把桶当豁免抽屉"的形态，一票否决。
# 与 CONTROLLED_INTERNAL_CAPABILITIES 的区别（务必读，别混，否则本桶沦为第二个免检册）：
#   CONTROLLED_INTERNAL（capability_registry.py）= FeatureGate 的「无 RouteKind 主表项、
#     但仍是一条被 gate 的真能力」白名单；其成员里有**真在执行/投递**的（bot.chat 直呼、
#     bot.campus_forward 走中央管线出站…）。那是「能力名册的另一页」，不是「非能力」。
#   本桶 = 这些 id **纯落款**，连"作为能力被调度"都不是——判据是"零执行点 + 全落款形态"，
#     不是"名字在这份清单里"。二者判据不同、执法点不同、互不替代。
#     本桶成员恰好也在 CONTROLLED_INTERNAL（因为投递/审计字段需要 gate 认识这个名字），
#     但**反之绝不成立**：CONTROLLED_INTERNAL 里的真能力（如 bot.chat）永不得进本桶。
# 归属由**派生判据** ``_derived_signature_ids`` 现算复核（不写名字白名单）：
#   本清单是 authoring claim；普查只摘「claimed ∩ derived」——派生没证的（有执行点、
#   或压根没出现过）绝不因被申报就隐身。claimed ⊄ derived 由反向锁当场红。
# 方向：只准缩、不许涨——新增成员必须自带「这枚 id 全仓只作落款、无任何执行点」的证据，
#   且过派生判据；否则方向棘轮（count 上限）与一致性锁一起红。落点唯一真身在此，
#   别处（含任何 .md / 别的 py）不得再抄一份成员清单。
# ===========================================================================
SIGNATURE_LABEL_IDS: frozenset[str] = frozenset(
    {
        "bot.cookie_expiry_notice",  # 只在 SendRequest(capability_id=…) 落款（cookie 到期提醒投递）
        "bot.credential_check",  # 只在 AuditRecord(capability_id=…) 落款（凭据巡检日志）
        "bot.group_digest_push",  # 只在 SendRequest(capability_id=…) 落款（群摘要每日投递）
        "bot.mail.notify",  # 只在 AuditRecord / _log_runtime_event(capability_id=…) 落款
        "bot.send_queue_worker",  # 只在 AuditRecord(capability_id=…) 落款（worker 不可用告警）
    }
)

sys.setrecursionlimit(30000)


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return "<external>/" + path.name


def _callee_name(func: ast.expr) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _lit_str(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _kwarg(call: ast.Call, name: str) -> ast.keyword | None:
    for kw in call.keywords:
        if kw.arg == name:
            return kw
    return None


def _build_parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return parents


def _walk_with_func_stack(tree: ast.AST):
    """yield (node,  enclosing 函数名链)。与 ast.walk 同覆盖，只多带包络栈。"""
    stack: list[str] = []

    def rec(node: ast.AST):
        pushed = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        if pushed:
            assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            stack.append(node.name)
        yield node, stack
        for child in ast.iter_child_nodes(node):
            yield from rec(child)
        if pushed:
            stack.pop()

    yield from rec(tree)


def _is_consumed(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """v1 门同形：造出的对象当场被成员访问/链式执行 ⇒ 它就是执行路径。"""
    parent = parents.get(node)
    return isinstance(parent, ast.Attribute) and parent.value is node


def _is_injection(call: ast.Call, parents: dict[ast.AST, ast.AST]) -> bool:
    """v1 门同形：作为 provider/capability 类关键字实参交出整枚对象 ⇒ 装配注入，非直呼。"""
    node: ast.AST = call
    for _ in range(3):
        parent = parents.get(node)
        if isinstance(parent, ast.keyword) and (parent.arg or "").endswith(
            ("provider", "provider_factory", "capability", "capability_factory")
        ):
            return not _is_consumed(parents.get(parent), parents)
        if isinstance(parent, ast.Lambda):
            node = parent
            continue
        return False
    return False


def _inside_feed(call: ast.Call, parents: dict[ast.AST, ast.AST]) -> bool:
    """直呼结果直接作为 缝/泛型/push/invoke 调用的实参 ⇒ 交给中央，非缝外。"""
    node: ast.AST = call
    for _ in range(4):
        parent = parents.get(node)
        if parent is None:
            return False
        if isinstance(parent, ast.Call):
            fname = _callee_name(parent.func)
            if fname in SEAM_FUNCS or fname in GENERIC_FUNCS or fname in PUSH_FUNCS or fname == "invoke":
                return True
        if isinstance(parent, (ast.keyword, ast.Expr)):
            node = parent
            continue
        if isinstance(parent, ast.Call):
            node = parent
            continue
        return False
    return False


def _entry_form(fn_stack: list[str]) -> str:
    """入口形态：按包络函数链（内层优先）判；表外一律 other，不猜。"""
    s = set(fn_stack)
    if _ALIAS_FN in s:
        return "别名"
    if _NATURAL_FN in s:
        return "自然语言"
    if _VOICE_FN in s:
        return "语音回执"
    if any(n.startswith(("_push", "_deliver")) or n.endswith("_job") for n in s):
        return "主动投递"
    if any(n.startswith(("_handle_", "handle_")) for n in s):
        return "命令"
    return "other"


class Census:
    """一次采集，两个出口（--json / --report）共用同一份账，不分第二次真树。"""

    def __init__(self, poison_paths: list[str]) -> None:
        self.poison_paths = poison_paths
        # 完整性账（任何非空 ⇒ 退出码 2）
        self.missing_required: list[str] = []
        self.unreadable: list[str] = []
        self.syntax_errors: list[str] = []
        # 申报账
        self.decls: dict[str, list[dict]] = {}
        self.adapter_default: str | None = None
        # 证据账（id -> site dicts）；tests 面另桶
        self.seam: dict[str, list[dict]] = {}
        self.seam_variable_sites: list[dict] = []
        self.invoke: dict[str, list[dict]] = {}
        self.generic: dict[str, list[dict]] = {}
        self.offseam: dict[str, list[dict]] = {}
        self.entry_forms: dict[str, set[str]] = {}
        self.unassigned_direct: dict[str, list[dict]] = {}
        self.unknown_ids: set[str] = set()
        #: id -> 该 id 在生产面的每个 ``capability_id`` 落点（带形态标签 routed/record）。
        #: 只增不改 ``unknown_ids`` 本身：分档是**加证**，不是删账（S81 §3）。
        self.unknown_id_sites: dict[str, list[dict]] = {}
        self.tests_evidence: dict[str, list[dict]] = {}
        # 扫描账
        self.files_scanned = 0
        self.capfunc_defs: dict[str, set[str]] = {}  # 能力模块函数符号 -> 定义文件集
        self.symbols: dict[str, set[str]] = {}  # 真身符号 -> 归属 id 集
        self.ref_modules: dict[str, set[str]] = {}  # 真身符号 -> 豁免的自身模块

    # ---------- 采集：申报 ----------
    def _extract_decls(self, rel: str, tree: ast.AST) -> None:
        for node, stack in _walk_with_func_stack(tree):
            if not isinstance(node, ast.Call):
                continue
            cid_kw = _kwarg(node, "capability_id")
            cid = _lit_str(cid_kw.value) if cid_kw is not None else None
            if cid is None or not _IDISH_RE.match(cid):
                continue
            adapter = None
            ref = None
            execution_declared = False
            for sub in ast.walk(node):
                if isinstance(sub, ast.keyword):
                    if sub.arg == "adapter":
                        adapter = adapter or _lit_str(sub.value)
                    elif sub.arg == "implementation_ref":
                        ref = ref or _lit_str(sub.value)
                    elif sub.arg == "execution" and isinstance(sub.value, ast.Call):
                        execution_declared = True
            self.decls.setdefault(cid, []).append(
                {
                    "file": rel,
                    "line": node.lineno,
                    "adapter": adapter,
                    "implementation_ref": ref,
                    "execution_declared": execution_declared,
                    "in_func": stack[-1] if stack else "<module>",
                }
            )
            if ref and "#" in ref:
                symbol = ref.rpartition("#")[2]
                module = ref.rpartition("#")[0]
                self.symbols.setdefault(symbol, set()).add(cid)
                self.ref_modules.setdefault(symbol, set()).add(module)

    def _extract_adapter_default(self, tree: ast.AST) -> None:
        """现读 CapabilityExecution.adapter 的字段缺省值（不抄第二份字面量）。"""
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "CapabilityExecution":
                for item in node.body:
                    if (
                        isinstance(item, ast.AnnAssign)
                        and isinstance(item.target, ast.Name)
                        and item.target.id == "adapter"
                        and item.value is not None
                    ):
                        self.adapter_default = _lit_str(item.value)
                        return
                self.adapter_default = None  # 类在册但 adapter 无缺省：申报行必须自带字面量

    # ---------- 采集：证据 ----------
    def _scan_file(self, rel: str, surface: str, tree: ast.AST, src: str) -> None:
        parents = _build_parents(tree)
        production = surface in ("plugins", "poison")
        # ① 能力模块函数定义（capabilities/** 下的 handle*/build_*_capability*）
        if "/capabilities/" in f"/{rel}":
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _CAPFUNC_RE.match(node.name):
                    self.capfunc_defs.setdefault(node.name, set()).add(rel)
        for node, stack in _walk_with_func_stack(tree):
            if not isinstance(node, ast.Call):
                continue
            fname = _callee_name(node.func)
            site = {"file": rel, "line": node.lineno, "surface": surface}
            # ② invoke 字面点（v1 _invoker_cids 同形）
            if isinstance(node.func, ast.Attribute) and node.func.attr == "invoke":
                for sub in ast.walk(node):
                    if isinstance(sub, ast.keyword) and sub.arg == "capability_id":
                        cid = _lit_str(sub.value)
                        if cid:
                            self._record_invoke(cid, site, stack, production)
            # ③ 汇合缝调用点
            if fname in SEAM_FUNCS:
                spec = SEAM_FUNCS[fname]
                assert isinstance(spec["kw"], str)
                cid = None
                via_default = False
                kw = _kwarg(node, spec["kw"])
                if kw is not None:
                    cid = _lit_str(kw.value)
                if cid is None:
                    for idx in spec["pos"]:  # type: ignore[union-attr]
                        if len(node.args) > idx:
                            cand = _lit_str(node.args[idx])
                            if cand and _IDISH_RE.match(cand):
                                cid = cand
                                break
                if cid is None and "default" in spec and kw is None:
                    cid = str(spec["default"])
                    via_default = True
                if cid is None:
                    self.seam_variable_sites.append({**site, "fn": fname})
                else:
                    self._record_seam(cid, {**site, "fn": fname, "via_default": via_default}, stack, production)
            # ④ 泛型执行器字面量（handle_async；_run_simple_capability 归缝，见模块 docstring）
            if fname in GENERIC_FUNCS:
                cid = _lit_str(_kwarg(node, "capability_id").value) if _kwarg(node, "capability_id") else None
                if cid:
                    if production:
                        self.generic.setdefault(cid, []).append({**site, "fn": fname})
                    else:
                        self.tests_evidence.setdefault(cid, []).append({**site, "kind": "generic", "fn": fname})
            # ⑤ 主动投递唯一出口（带 id 字面量才算入口形态证据）
            if fname in PUSH_FUNCS:
                cid = _lit_str(_kwarg(node, "capability_id").value) if _kwarg(node, "capability_id") else None
                if cid and production:
                    self.entry_forms.setdefault(cid, set()).add("主动投递")
                    self.seam.setdefault(cid, []).append({**site, "fn": fname, "kind": "push-exit"})
            # ⑥ 直呼真身（ref 符号 → 按 id 记；能力模块函数符号 → 未归属账）
            if fname in self.symbols or fname in self.capfunc_defs:
                if rel == SHELL_REL:
                    continue
                if rel in self.ref_modules.get(fname, set()) or rel in self.capfunc_defs.get(fname, set()):
                    continue
                if _is_injection(node, parents):
                    continue
                if _inside_feed(node, parents):
                    tag = "seam-feed"
                elif stack and _BUILDER_FN_RE.match(stack[-1]):
                    tag = "assembly-wrap"
                elif stack and _CAPFUNC_RE.match(stack[-1]) and len(stack) == 1:
                    tag = "self-composition"
                else:
                    tag = "exec-bypass"
                rec = {**site, "symbol": fname, "tag": tag, "enclosing": stack[-1] if stack else "<module>"}
                if not production:
                    for cid in sorted(self.symbols.get(fname, ())):
                        self.tests_evidence.setdefault(cid, []).append({**rec, "kind": "direct"})
                    if fname not in self.symbols:
                        self.tests_evidence.setdefault("<unassigned>", []).append({**rec, "kind": "direct"})
                    continue
                if fname in self.symbols:
                    for cid in sorted(self.symbols[fname]):
                        self.offseam.setdefault(cid, []).append(rec)
                else:
                    self.unassigned_direct.setdefault(fname, []).append(rec)
            # ⑦ 全扫 capability_id 字面量 → 幽灵 id 观测（只记生产面，与基线尺同域）
            kw = _kwarg(node, "capability_id")
            if kw is not None and production:
                lit = _lit_str(kw.value)
                if lit and _IDISH_RE.match(lit) and lit not in self.decls:
                    self.unknown_ids.add(lit)
                    self.unknown_id_sites.setdefault(lit, []).append(
                        {
                            **site,
                            "fn": fname,
                            "via": "literal",
                            "shape": "routed" if fname in SITE_EXEC_FUNCS else "record",
                            "enclosing": stack[-1] if stack else "<module>",
                            "entry": _entry_form(stack),
                        }
                    )
            # ⑧ 见 ``_scan_carried_ids``（主循环只走 Call 节点，赋值形要单独一遍）。

        self._scan_carried_ids(rel, surface, tree, production)

    def _scan_carried_ids(self, rel: str, surface: str, tree: ast.AST, production: bool) -> None:
        """⑧ 变量携带的 id（S81 补盲）。

        ``capability_id = "<字面量>"`` 赋值，且**含它的全部外层作用域**里有执行点把这个变量
        交出去 ⇒ 这是一条真路由申报，只是 id 不写在实参字面量上，判据 ①③④⑦ 全看不见它
        （``/bot`` 派发表 29 枚就藏在这儿）。作用域取「最内层到最外层的全部函数」而非只看
        最内层：方向上只会**多记**、不会漏记——漏记＝让债变小，是本波一票否决面。
        """
        if not production:
            return
        var_exec_calls: dict[int, list[tuple[int, str]]] = {}
        # 注意：运行时 AsyncFunctionDef 继承 FunctionDef，但 typeshed 把它建模成**同级**类
        # ⇒ 注解必须显式写并集，否则 mypy 在 append 处判不兼容（S81 实跑踩过一次）。
        scopes: list[_Fn] = []
        for fn in (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
            hits: list[tuple[int, str]] = []
            for call in (c for c in ast.walk(fn) if isinstance(c, ast.Call)):
                callee = _callee_name(call.func)
                if callee not in SITE_EXEC_FUNCS:
                    continue
                by_arg = any(isinstance(a, ast.Name) and a.id == "capability_id" for a in call.args)
                kw = _kwarg(call, "capability_id")
                by_kw = kw is not None and isinstance(kw.value, ast.Name) and kw.value.id == "capability_id"
                if by_arg or by_kw:
                    hits.append((call.lineno, callee))
            var_exec_calls[id(fn)] = hits
            scopes.append(fn)

        def _scope_chain(node: ast.Assign) -> list[_Fn]:
            return [f for f in scopes if f.lineno <= node.lineno <= (f.end_lineno or f.lineno)]

        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            chain = sorted(_scope_chain(node), key=lambda f: -f.lineno)  # 最内层在前
            if not chain:
                continue
            for tgt in node.targets:
                if not (isinstance(tgt, ast.Name) and tgt.id == "capability_id"):
                    continue
                lit = _lit_str(node.value)
                if not lit or not _IDISH_RE.match(lit) or lit in self.decls:
                    continue
                consumers = [(ln, cn) for fnode in chain for ln, cn in var_exec_calls.get(id(fnode), ())]
                if not consumers:
                    continue
                ln, cn = min(consumers)
                # 入口形态复用尺自己的唯一判据 `_entry_form`（栈序＝最内层在前），
                # 不在这里另立第二套名字启发式。
                stack = [f.name for f in chain]
                self.unknown_ids.add(lit)
                self.unknown_id_sites.setdefault(lit, []).append(
                    {
                        "file": rel,
                        "line": node.lineno,
                        "surface": surface,
                        "fn": cn,
                        "via": "variable",
                        "shape": "routed",
                        "enclosing": stack[0] if stack else "<module>",
                        "entry": _entry_form(stack),
                        "consumer_line": ln,
                    }
                )

    def _record_invoke(self, cid: str, site: dict, stack: list[str], production: bool) -> None:
        rec = {**site, "fn": "invoke", "entry": _entry_form(stack) if production else None}
        if production:
            self.invoke.setdefault(cid, []).append(rec)
        else:
            self.tests_evidence.setdefault(cid, []).append({**rec, "kind": "invoke"})

    def _record_seam(self, cid: str, rec: dict, stack: list[str], production: bool) -> None:
        if production:
            self.seam.setdefault(cid, []).append(rec)
            if rec.get("fn") in SEAM_FUNCS and "kind" not in rec:
                self.entry_forms.setdefault(cid, set()).add(_entry_form(stack))
        else:
            self.tests_evidence.setdefault(cid, []).append({**rec, "kind": "seam"})

    # ---------- 主流程 ----------
    def collect(self) -> dict:
        candidates: list[tuple[Path, str, str]] = []  # (path, rel, surface)
        for req in REQUIRED_FILES:
            path = PKG_ROOT / req
            if not path.is_file():
                self.missing_required.append(f"plugins/bot_unified_runtime/{req}")
                continue
            candidates.append((path, _rel(path), "plugins"))
        for base, surface in ((PKG_ROOT, "plugins"), (REPO_ROOT / "tests", "tests")):
            for path in sorted(base.rglob("*.py")):
                if "__pycache__" in path.parts:
                    continue
                rel = _rel(path)
                if surface == "plugins" and not rel.startswith("plugins/bot_unified_runtime"):
                    continue
                candidates.append((path, rel, surface))
        # 去重：REQUIRED 同时也在 rglob 里，重复入账=同一树 parse 两遍、申报翻倍
        uniq: dict[str, tuple[Path, str, str]] = {}
        for p, r, s in candidates:
            uniq.setdefault(r, (p, r, s))
        candidates = list(uniq.values())
        first_pass = [(p, r, s) for (p, r, s) in candidates if r in DECL_FILES or "/capabilities/" in f"/{r}"]
        texts: dict[str, tuple[Path, str, str]] = {}
        for path, rel, surface in first_pass:
            texts[rel] = (path, rel, surface)
            try:
                src = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                self.unreadable.append(rel)
                continue
            try:
                tree = ast.parse(src)
            except SyntaxError:
                self.syntax_errors.append(rel)
                continue
            self.files_scanned += 1
            if rel in DECL_FILES:
                if rel.endswith("capability_registry.py"):
                    self._extract_adapter_default(tree)
                self._extract_decls(rel, tree)
        # 第二遍：全集（markers 超集含第一遍拿到的符号名）
        markers = set(_BASE_MARKERS) | set(self.symbols) | set(self.capfunc_defs)
        poison_rels: list[str] = []
        for raw in self.poison_paths:
            path = Path(raw)
            if not path.is_file():
                self.missing_required.append(f"<poison>{raw}")
                continue
            rel = f"<poison>{path.name}"
            poison_rels.append(rel)
            texts[rel] = (path, rel, "poison")
        for path, rel, surface in candidates:
            if rel in texts:
                continue
            texts[rel] = (path, rel, surface)
        for rel, (path, _r, surface) in list(texts.items()):
            if rel in DECL_FILES or (rel.startswith("plugins/bot_unified_runtime") and "/capabilities/" in f"/{rel}"):
                continue  # 第一遍已 parse 过（符号采集除外：见下）
            try:
                src = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                self.unreadable.append(rel)
                continue
            # 预筛真值表逐字不变：注毒件无条件解析；其余必须命中 marker 并集才载入
            # （RF2-5 教训：宁可多载入，绝不因预筛漏文件）。旧写法把命中记进一个从不被
            # 读的局部标志位（ruff F841），这里把标志位去掉、只留判定本身。
            if surface != "poison" and not any(m in src for m in markers):
                continue
            try:
                tree = ast.parse(src)
            except SyntaxError:
                self.syntax_errors.append(rel)
                continue
            self.files_scanned += 1
            self._scan_file(rel, surface, tree, src)
        # 声明文件与 capabilities/** 同样要过证据扫描（第一遍只抽了申报/定义）
        for path, rel, surface in first_pass:
            if rel not in DECL_FILES and "/capabilities/" not in f"/{rel}":
                continue  # 其余（如根 __init__.py）已在标记循环里扫过证据，不重复入账
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, SyntaxError):
                continue  # 已在上面记过红，不重复
            self._scan_file(rel, surface, tree, "")
        return self._build_output(poison_rels)

    # ---------- 归类与输出 ----------
    def _decl_execution(self, cid: str) -> dict:
        rows = self.decls.get(cid, [])
        execution_declared = any(r["execution_declared"] for r in rows)
        adapters = {r["adapter"] for r in rows if r["adapter"]}
        if execution_declared and self.adapter_default:
            adapters.add(self.adapter_default)
        return {"declared": bool(rows), "execution_declared": execution_declared, "adapters": sorted(adapters)}

    def _state(self, cid: str) -> str:
        wired_ev = bool(self.seam.get(cid)) or bool(self.invoke.get(cid))
        decl = self._decl_execution(cid)
        known_adapters = {"command", "prepared"}
        # ⚠ ``_decl_execution`` 返回的 ``adapters`` 是 **sorted list**（它是 roster 的 JSON
        # 出口形状，消费者按列表读，不改）。list 与 set 不能 ``&`` ——旧写法在
        # 「``execution`` 已申报 ∧ 无缝/invoke 证据」这条组合上直接抛 TypeError 把整把尺
        # 打死（S81 2026-09-24T00:49Z 实炸一次，S67 门把它报成「量具跑不起来」）。
        # 收口只在这儿：判据不变（申报形 ∈ {command, prepared} ⇒ wired），只把类型对上。
        wired = wired_ev or (decl["execution_declared"] and bool(set(decl["adapters"]) & known_adapters))
        if wired:
            return "wired"
        if self.generic.get(cid):
            return "generic"
        if self.offseam.get(cid):
            return "offseam"
        return "none"

    def _derived_signature_ids(self) -> set[str]:
        """从**本次采集的 AST 证据**派生「纯落款 id」集合（S200 · 裁定 2.A）。

        判据全部现算、可复算，**不查 SIGNATURE_LABEL_IDS 这份名字清单**（那会自证）：
          ① 不在唯一在册表（``self.decls``）——在册者本就是能力，绝不在此列；
          ② 无任何执行点证据——``seam`` / ``invoke`` / ``generic`` / ``offseam`` 全空；
          ③ 每一处 ``capability_id`` 落点形态都是 ``record``（只写进契约/审计/日志字段，
             从不进 ``SITE_EXEC_FUNCS``）；
          ④ 至少有一处落款落点（从没出现过的 id 无需摘，摘了＝凭空造隐身）。
        它比 authoring claim **更严或相等**：本席的 5 枚必须落在这里，否则登记处与实况脱钩。
        反过来，本方法命中的其它 id（如 ``bot.decision`` 一类同样"只在字段里出现"的在册表外
        id）**不会**因此被摘出 unknown_ids——只有被 authoring claim 明确认领的才摘。
        这是刻意保守：桶不是"把所有 record_only 一键抹掉"的抽屉。
        """
        out: set[str] = set()
        for cid in self.unknown_ids:
            if cid in self.decls:
                continue
            if self.seam.get(cid) or self.invoke.get(cid) or self.generic.get(cid) or self.offseam.get(cid):
                continue
            sites = self.unknown_id_sites.get(cid) or []
            if not sites:
                continue
            if all(s["shape"] == "record" for s in sites):
                out.add(cid)
        return out

    def _build_output(self, poison_rels: list[str]) -> dict:
        universe = set(self.decls) | set(self.unknown_ids) | {cid for cid in self._evidence_ids() if cid not in self.decls}
        roster: dict[str, dict] = {}
        violations: list[dict] = []
        state_counts = {"wired": 0, "generic": 0, "offseam": 0, "none": 0}
        for cid in sorted(universe):
            state = self._state(cid)
            state_counts[state] += 1
            off_sites = self.offseam.get(cid, [])
            bypass = [s for s in off_sites if s["tag"] in ("exec-bypass", "assembly-wrap")]
            if state == "wired":
                for s in bypass:
                    if s["tag"] == "exec-bypass":
                        violations.append({"capability_id": cid, **s})
            roster[cid] = {
                "declared": cid in self.decls,
                "state": state,
                "decl": self.decls.get(cid, []),
                "seam_sites": self.seam.get(cid, []),
                "invoke_sites": self.invoke.get(cid, []),
                "generic_sites": self.generic.get(cid, []),
                "offseam_sites": off_sites,
                "entry_forms": sorted(self.entry_forms.get(cid, set())),
                "test_sites": self.tests_evidence.get(cid, []),
                "unknown_sites": self.unknown_id_sites.get(cid, []),
            }
        # unknown_ids 的形态分档：**纯加证**，`unknown_ids` 本身一字不动。
        # routed      = 该 id 至少有一处被交给执行点（缝 / 泛型 handle(_async) / invoke），
        #               含「变量携带」那形——这就是"在册表之外还有一条在跑的路"＝收编候选。
        # record_only = 全部落点都只是契约/记录对象的字段写入（CapabilityResult /
        #               AuditRecord / SendRequest / FeatureDescriptor / ActionPlan / 结果壳），
        #               从不参与路由 ⇒ 尺的口径噪声，不是债。
        # 两桶必须恰好划分「在册表外」差集（不变量随输出走，门 ``test_central_seam_census_s81`` 执法）。
        # ---- 非能力署名标签桶（S200 · 用户裁定 2.A）----
        # claimed = 登记处 authoring；derived = 从本次证据现算的"纯落款"判据（见 _derived_signature_ids）。
        # 实际摘出 = claimed ∩ derived（安全侧：派生没证的绝不因被申报就隐身）。
        claimed_signature = SIGNATURE_LABEL_IDS
        derived_signature = self._derived_signature_ids()
        signature = sorted(claimed_signature & derived_signature)
        signature_set = set(signature)
        # 反向锁信号：声称是署名、却被派生判据否掉（有执行点 / 未在册却无非落款证据）。
        # 真树必须为空；非空即 tests/test_signature_label_bucket.py 红（桶不得当豁免抽屉）。
        signature_claimed_not_derived = sorted(claimed_signature - derived_signature)
        # 「在册表外」差集 = unknown_ids 去掉署名桶；桶内 id 仍留 roster + signature_label_sites（不隐身）。
        off_manifest = set(self.unknown_ids) - signature_set
        unknown_sites = {cid: sorted(v, key=lambda s: (s["file"], s["line"])) for cid, v in self.unknown_id_sites.items()}
        routed = sorted(cid for cid in off_manifest if any(s["shape"] == "routed" for s in unknown_sites.get(cid, [])))
        record_only = sorted(off_manifest - set(routed))
        signature_label_sites = {cid: unknown_sites[cid] for cid in signature if cid in unknown_sites}
        integrity = {
            "ok": not (self.missing_required or self.unreadable or self.syntax_errors),
            "missing_required": self.missing_required,
            "unreadable": self.unreadable,
            "syntax_errors": self.syntax_errors,
        }
        return {
            "meta": {
                "tool": "scripts/central_seam_census.py",
                "seat": "S01 中央调度收编波·波次A",
                "version": VERSION,
                "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "files_scanned": self.files_scanned,
                "poison_files": poison_rels,
                "adapter_default_from_class": self.adapter_default,
                "seam_variable_sites": self.seam_variable_sites,
            },
            "counts": {
                "universe": len(universe),
                "declared": len(self.decls),
                "states": state_counts,
                "seam_sites": sum(len(v) for v in self.seam.values()),
                "offseam_sites": sum(len(v) for v in self.offseam.values()),
                "violations_second_route": len(violations),
                # 「在册表外」差集＝去掉署名桶后的 unknown_ids（桶内 id 见 unknown_ids_signature）。
                "unknown_ids": len(off_manifest),
                "unknown_ids_routed": len(routed),
                "unknown_ids_record_only": len(record_only),
                "unknown_ids_signature": len(signature),
                "unknown_ids_offmanifest_raw": len(self.unknown_ids),
            },
            "roster": roster,
            "unassigned_capability_function_calls": self.unassigned_direct,
            "violations_second_route": violations,
            "unknown_ids": sorted(off_manifest),
            "unknown_id_partition": {
                "routed": routed,
                "record_only": record_only,
                # 不变量：两桶必须**恰好**划分「在册表外」差集 off_manifest（既不重叠、更不丢账）。
                # 丢账＝尺自证变窄，一票否决面 ⇒ 直接随输出供门读。
                "covers_exactly": set(routed) | set(record_only) == off_manifest
                and not (set(routed) & set(record_only)),
            },
            "unknown_id_sites": {cid: unknown_sites[cid] for cid in off_manifest},
            # 非能力署名标签桶（S200 · 裁定 2.A）：不计入差集，但**逐枚留明细、不许隐身**。
            "signature_labels": signature,
            "signature_label_sites": signature_label_sites,
            "signature_claimed_not_derived": signature_claimed_not_derived,
            "integrity": integrity,
        }

    def _evidence_ids(self):
        for coll in (self.seam, self.invoke, self.generic, self.offseam, self.entry_forms):
            yield from coll

    def reconcile(self, output: dict, baseline_path: str) -> dict:
        """本件 id 全集 vs 基线尺快照：双向差集显式列出 + 态交叉表。"""
        path = Path(baseline_path)
        if not path.is_file():
            output["integrity"]["missing_required"].append(f"<baseline>{baseline_path}")
            output["integrity"]["ok"] = False
            return {"error": f"基线快照不存在：{baseline_path}"}
        try:
            snap = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            output["integrity"]["unreadable"].append(f"<baseline>{baseline_path}: {type(exc).__name__}")
            output["integrity"]["ok"] = False
            return {"error": f"基线快照不可读/不可解析：{type(exc).__name__}"}
        baseline_states = {}
        for cid, entry in snap.items():
            if entry.get("phantom"):
                baseline_states[cid] = "phantom"
            elif entry.get("wired"):
                baseline_states[cid] = "wired"
            elif entry.get("generic"):
                baseline_states[cid] = "generic_executor"
            else:
                baseline_states[cid] = "not_wired"
        mine = {cid: row["state"] for cid, row in output["roster"].items()}
        cross: dict[str, dict[str, int]] = {}
        for cid in sorted(set(mine) | set(baseline_states)):
            m = mine.get(cid, "<absent>")
            b = baseline_states.get(cid, "<absent>")
            cross.setdefault(m, {}).setdefault(b, 0)
            cross[m][b] += 1
        return {
            "baseline_total": len(baseline_states),
            "census_total": len(mine),
            "only_in_census": sorted(set(mine) - set(baseline_states)),
            "only_in_baseline": sorted(set(baseline_states) - set(mine)),
            "state_cross_table_mine_x_baseline": cross,
        }


def render_report(output: dict, reconciliation: dict | None) -> str:
    out: list[str] = []
    meta, counts = output["meta"], output["counts"]
    out.append(f"中央缝外直呼点普查 · {meta['seat']} · v{meta['version']} · {meta['generated_at_utc']}")
    out.append(
        f"扫描文件 {meta['files_scanned']}；id 全集 {counts['universe']}（在册 {counts['declared']}）；"
        f"三态 wired/generic/offseam/none = "
        + "/".join(str(counts["states"][k]) for k in ("wired", "generic", "offseam", "none"))
    )
    out.append(
        f"汇合缝调用点 {counts['seam_sites']}；缝外直呼点 {counts['offseam_sites']}；"
        f"第二通路violations(exec-bypass ∧ wired) {counts['violations_second_route']}"
    )
    integ = output["integrity"]
    out.append(
        f"完整性：ok={integ['ok']} missing={len(integ['missing_required'])} "
        f"unreadable={len(integ['unreadable'])} syntax_errors={len(integ['syntax_errors'])}"
    )
    for label, items in (
        ("缺件", integ["missing_required"]),
        ("读不出", integ["unreadable"]),
        ("解析失败(绝不默认无调用点)", integ["syntax_errors"]),
    ):
        for item in items:
            out.append(f"  ! {label}: {item}")
    if reconciliation is not None:
        out.append("")
        out.append("── 与基线尺对账（orchestration_wired_census --json 快照）──")
        if "error" in reconciliation:
            out.append(f"  !! {reconciliation['error']}")
        else:
            out.append(
                f"  基线 {reconciliation['baseline_total']} vs 本件 {reconciliation['census_total']}；"
                f"差集 只在本件 {len(reconciliation['only_in_census'])} / 只在基线 {len(reconciliation['only_in_baseline'])}"
            )
            for cid in reconciliation["only_in_census"]:
                out.append(f"    + 只在本件: {cid}")
            for cid in reconciliation["only_in_baseline"]:
                out.append(f"    - 只在基线: {cid}")
            for m, row in sorted(reconciliation["state_cross_table_mine_x_baseline"].items()):
                out.append(f"    态[本件]={m}: " + ", ".join(f"{b}={n}" for b, n in sorted(row.items())))
    out.append("")
    out.append("── 缝外直呼点全量名册（file:line [tag] symbol ∈ fn）──")
    for cid, row in output["roster"].items():
        if not row["offseam_sites"]:
            continue
        out.append(f"  {cid} (state={row['state']}, 入口形态={','.join(row['entry_forms']) or '—'})")
        for s in row["offseam_sites"]:
            out.append(f"    {s['file']}:{s['line']} [{s['tag']}] {s['symbol']} ∈ {s['enclosing']}")
    if output["unassigned_capability_function_calls"]:
        out.append("  ── 未归属能力模块函数直呼（handle*/build_*_capability 无在册 id 对应）──")
        for sym, sites in sorted(output["unassigned_capability_function_calls"].items()):
            for s in sites:
                out.append(f"    {s['file']}:{s['line']} [{s['tag']}] {sym} ∈ {s['enclosing']}")
    if output["violations_second_route"]:
        out.append("── 第二通路 violations（wired ∧ exec-bypass：已通电却直呼真身）──")
        for s in output["violations_second_route"]:
            out.append(f"    {s['capability_id']} @ {s['file']}:{s['line']} {s['symbol']} ∈ {s['enclosing']}")
    out.append("── 三态名册 ──")
    for state in ("wired", "generic", "offseam", "none"):
        ids = [cid for cid, row in output["roster"].items() if row["state"] == state]
        out.append(f"  [{state}] {len(ids)}")
        if state in ("offseam", "generic"):
            out.extend(f"    · {cid}" for cid in ids)
        fam: dict[str, int] = {}
        for cid in ids:
            head = cid.split(".", 1)[0]
            fam[head] = fam.get(head, 0) + 1
        out.append("    家族分布: " + ", ".join(f"{k}={v}" for k, v in sorted(fam.items())))
    tested = sum(1 for row in output["roster"].values() if row["test_sites"])
    out.append(f"  [带 tests 面证据的 id 数] {tested}")
    part = output.get("unknown_id_partition", {})
    routed, record_only = part.get("routed", []), part.get("record_only", [])
    out.append("")
    out.append(
        f"── 在册表外 id 分档（共 {len(routed) + len(record_only)}，已去掉署名桶；"
        f"routed={len(routed)} / record_only={len(record_only)}；"
        f"恰好划分={part.get('covers_exactly')}）──"
    )
    out.append("  routed＝被交给执行点（在册表外的在跑路，收编候选）：")
    for cid in routed:
        row = output["roster"].get(cid, {})
        sites = row.get("unknown_sites", [])
        forms = sorted({s.get("entry", "other") for s in sites})
        head = "; ".join(f"{s['file']}:{s['line']}[{s['via']}→{s['fn']}]" for s in sites[:3])
        more = f" …共{len(sites)}处" if len(sites) > 3 else ""
        out.append(f"    · {cid} 入口={','.join(forms) or '—'}  {head}{more}")
    out.append(f"  record_only＝只在契约/记录对象字段里出现（口径噪声，非债）: {', '.join(record_only) or '—'}")
    sig = output.get("signature_labels", [])
    sig_sites = output.get("signature_label_sites", {})
    out.append(
        f"  非能力署名标签桶＝纯落款、不入册也不计入差集但仍列此（{len(sig)}，authoring 认领数；"
        f"S200 裁定 2.A）: {', '.join(sig) or '—'}"
    )
    for cid in sig:
        head = "; ".join(f"{s['file']}:{s['line']}[{s['via']}→{s['fn']}]" for s in sig_sites.get(cid, [])[:3])
        out.append(f"    · {cid}（落款点）  {head}")
    claimed_not_derived = output.get("signature_claimed_not_derived", [])
    if claimed_not_derived:
        out.append(
            "  !! 反向锁告警：以下 id 被申报为署名却有执行点/无落款证据（桶不得当豁免抽屉）："
            + ", ".join(claimed_not_derived)
        )
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="中央缝外直呼点普查（S01，AST 静态、缺件即红）")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--json", action="store_true", help="机读名册 JSON（stdout 纯净）")
    group.add_argument("--report", action="store_true", help="人读报告")
    parser.add_argument("--baseline-json", default=None, help="orchestration_wired_census --json 的快照文件（对账用，缺文件即红）")
    parser.add_argument("--poison", action="append", default=[], help="注毒：把仓外合成件并入生产扫描面（可重复）")
    parser.add_argument("--fail-on-violations", action="store_true", help="第二通路 violations 非空时退出码 3")
    args = parser.parse_args(argv)

    census = Census(args.poison)
    output = census.collect()
    reconciliation = census.reconcile(output, args.baseline_json) if args.baseline_json else None
    if args.json:
        if reconciliation is not None:
            output["reconciliation"] = reconciliation
        print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_report(output, reconciliation))
    if not output["integrity"]["ok"]:
        return 2
    if args.fail_on_violations and output["violations_second_route"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
