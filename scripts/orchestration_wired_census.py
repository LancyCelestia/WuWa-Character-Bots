"""统一接入波 · S-GAP 席只读扫描器：中央在册表 vs 生产真实通路的差额台账。

一句话——回答「还剩多少没接入」这个问题。判据全走 ast 静态解析，零运行时副作用、
零消息发送；不写任何仓内文件，结果只打 stdout。

判据同源（2026-09-22 S-CENSUS 收口，铁律 7「禁第二真身」）：本件是**唯一的**
「在册 descriptor → wired / generic_executor / not_wired」判据真身——
  ``scan_wiredness``   真树扫描（invoke 字面命中 ∪ R8 命令形接缝声明式通电 ∪ 泛型执行器命中 ∪ 根汇缝字面量第四臂）
  ``live_partition``   三桶归类（wired 优先）
  ``classify_all``     每条 id 的态（含 phantom 臂）——报表与本门账都从这里取数
常驻门 ``tests/test_descriptor_wiredness_ledger.py`` 的 ``_scan_real_tree`` / ``_live_partition``
是前两者的**再导出委托**，本件与那把门不再各存一份判据。此前 R8（2026-09-22 裁定）只扩了门侧
判据、本件未跟随 ⇒ 同一条真树门报 10/99、本件报 2/107——人读报表把已通电的 8 枚记成欠账，
正是本波要杀的「两个真身各说一套」。两本账的一致性由该件本节末三把锁执法：
``test_census_report_matches_ledger_partition``（集合）/ ``test_census_printed_counts_match_ledger_buckets``
（打印出来的数）/ ``test_census_cross_check_lock_has_teeth``（注毒）+
``test_ledger_scanners_are_reexports_not_second_copy``（结构）。

复用（不复制第二套同构实现）：tests/test_orchestration_callsite_single.py 的
``_invoker_cids`` / ``seam_registered_cids`` / ``_rel`` / ``_PKG_ROOT`` 直接 import
（先例：``scripts/doc_sync.py`` 亦把 ``tests/`` 挂上 sys.path 取判据）。

通路四态（对每个在册 capability_id）：
  wired            —— 生产里有 ``….invoke(CapabilityRequest(capability_id=X))``，
                      或唯一表 route 执行形声明 ``execution=CapabilityExecution(adapter="command")``
                      （R8：点位=capability_registry.py 那一行）
  generic_executor —— 走 ``pipeline.handle_async`` / ``_run_simple_capability`` 泛型执行器
  not_wired        —— 在册但全树零调用点（纯登记未接线）
外加「未在册」对照：调用点上出现的、但不在 CAPABILITY_DESCRIPTOR 里的 id（幽灵调用点）。
"""

from __future__ import annotations

import argparse
import ast
import importlib
import sys
from collections.abc import Iterable
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TESTS_DIR = _REPO_ROOT / "tests"
sys.path.insert(0, str(_TESTS_DIR))
sys.path.insert(0, str(_REPO_ROOT))

import test_orchestration_callsite_single as v1gate  # 复用中央判据（tests/ 已在 sys.path 上）

_PKG_ROOT = v1gate._PKG_ROOT
#: 中央真源自身的 descriptor 构造不算生产调用点（值取自 v1 门，不抄第二份）。
_CENTRAL_SHELL_REL = v1gate._SHELL_REL

#: 四态名——报表分桶与一致性锁共用的唯一字面量来源。
STATE_WIRED = "wired"
STATE_GENERIC = "generic_executor"
STATE_NOT_WIRED = "not_wired"
STATE_PHANTOM = "phantom"
REPORT_STATES: tuple[str, ...] = (STATE_WIRED, STATE_GENERIC, STATE_NOT_WIRED, STATE_PHANTOM)


def _kwarg_literal(call: ast.Call, name: str) -> str | None:
    for kw in call.keywords:
        if kw.arg == name and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            return kw.value.value
    return None


def _attr_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _generic_executor_cids(tree: ast.AST) -> set[str]:
    """``pipeline.handle_async(...)`` / ``_run_simple_capability(...)`` 上的 capability_id 字面量。"""
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _attr_name(node.func) in {"handle_async", "_run_simple_capability"}:
            cid = _kwarg_literal(node, "capability_id")
            if cid:
                found.add(cid)
    return found


def _load_descriptor_table() -> dict[str, tuple[str, ...]]:
    """{capability_id: authored_by}；import 失败交由调用方诚实处理（不在扫描器里放宽判据）。"""
    module = importlib.import_module("plugins.bot_unified_runtime.runtime.capability_protocols")
    table = module.CAPABILITY_DESCRIPTOR
    return {cid: tuple(table[cid].authored_by) for cid in table}


def _iter_sources() -> list[tuple[str, str]]:
    """候选源文件枚举（廉价预筛）。

    RF2-5 根修：旧预筛只认 `"capability_id="` 字面量 ⇒ **纯 positional 形**的泛型调用
    （`_run_simple_capability(bot, ev, factory, "cid", grp)` / `pipeline.handle_async(...)`）若整文件
    不含该字面量会被**整文件滤掉**，令 facets/descriptor 双门对这类旁路失明（评审 P3b）。预筛并集补上
    两族执行器入口的子串，宁可多载入（后续各自 ast 判据仍精确），绝不因预筛漏文件。
    """
    out: list[tuple[str, str]] = []
    for path in sorted(_PKG_ROOT.rglob("*.py")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if (
            "capability_id=" in text
            or "handle_async(" in text
            or "_run_simple_capability(" in text
        ):
            out.append((v1gate._rel(path), text))
    return out


def scan_wiredness(
    syntax_errors: list[str] | None = None,
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """真树「通电 / 泛型」扫描的唯一判据：返回 (invoke 命中 cid→文件集, 泛型命中 cid→文件集)。

    四支命中合成一份账（缺任一支即一笔假账，历史上都咬过）：
      1. ``v1gate._invoker_cids``  —— 字面量形 ``invoke(CapabilityRequest(capability_id="x"))``；
      2. ``v1gate.seam_registered_cids``（R8）—— 命令形接缝传**变量**、中央件内部才落成
         invoke ⇒ 只看字面量会让已通电的命令形能力在账上永远记 not_wired（三席独立点名的假账源）；
         点位=唯一表 ``capability_registry.py`` 里那行 ``execution=CapabilityExecution(...)`` 声明本身；
      3. ``_generic_executor_cids`` —— 泛型执行器上的 ``capability_id=`` 字面量；
      4. 根汇缝字面量（``root_funnel_literal_cids``，S-SEAM-FOLLOW-c 2026-09-27 补臂）——
         P0-A 迁进 ``_run_capability_through_pipeline(..., capability_id=<字面>)`` 的站点上面
         三支都看不见（1 不涉 invoke 字面、2 只认注册册声明、3 只认 handle_async/
         _run_simple_capability 名）⇒ 曾由台账门挂过渡臂代扫，其注记白纸黑字写明
         「旧尺补第四臂后撤过渡臂」；本臂即按该撤臂条件落地，判据真身仍唯一支
         ``test_central_via_identity_and_entry_durability.root_funnel_literal_cids``
         （§5 入口耐久锁同源，零复制、零第二支扫描器；函数内延迟 import， facets-only
         复用本件 ``_iter_sources`` 时不顺带装载中央件）。点位＝根 ``__init__.py``，
         与台账 WIRED 登记点位同字面。

    ``syntax_errors``：传入列表则坏文件记名后继续（普查是报告脚本，一份坏文件不能让整个台账不可用）；
    不传则由调用方决定如何处理——常驻门选择「当场炸」（RF2-5 口径，静默 continue=假绿温床）。
    """
    invoke_hits: dict[str, set[str]] = {}
    generic_hits: dict[str, set[str]] = {}
    for rel, src in _iter_sources():
        if rel == _CENTRAL_SHELL_REL:
            continue  # 中央真源自身的 descriptor 构造不算生产调用点
        try:
            tree = ast.parse(src)
        except SyntaxError:
            if syntax_errors is not None:
                syntax_errors.append(rel)
            continue
        for cid in v1gate._invoker_cids(tree):
            invoke_hits.setdefault(cid, set()).add(rel)
        for cid in _generic_executor_cids(tree):
            generic_hits.setdefault(cid, set()).add(rel)
    for cid, files in v1gate.seam_registered_cids().items():
        invoke_hits.setdefault(cid, set()).update(files)
    # 第四臂（根汇缝字面量，S-SEAM-FOLLOW-c 2026-09-27；判据理由见上方 docstring 第 4 支）。
    # 走模块属性现取：台账门注毒锁（test_funnel_arm_lock_has_teeth）monkeypatch 同一真身即断电。
    import test_central_via_identity_and_entry_durability as viaid

    root_rel = v1gate._rel(_PKG_ROOT / "__init__.py")
    for cid in viaid.root_funnel_literal_cids():
        invoke_hits.setdefault(cid, set()).add(root_rel)
    return invoke_hits, generic_hits


def live_partition(
    descriptor_ids: Iterable[str],
    invoke_hits: dict[str, set[str]],
    generic_hits: Iterable[str],
) -> tuple[set[str], set[str], set[str]]:
    """三桶归类（wired 优先）的唯一判据：invoke 出现即 wired，其残留泛型字面量不计 generic。

    常驻门（缺口账四条不变量）与人读普查报表**共用本函数** ⇒ 「报表数字」与「机器账」
    不可能各说一套；回归方向由 ``test_census_report_matches_ledger_partition`` 执法。
    """
    ids = set(descriptor_ids)
    generic_ids = set(generic_hits)
    wired = {cid for cid in ids if invoke_hits.get(cid)}
    generic = {cid for cid in ids if not invoke_hits.get(cid) and cid in generic_ids}
    not_wired = ids - wired - generic
    return wired, generic, not_wired


def classify_all(
    descriptor_ids: Iterable[str],
    invoke_hits: dict[str, set[str]],
    generic_hits: dict[str, set[str]],
) -> dict[str, str]:
    """{capability_id: 态}，在册三态**全部**由 ``live_partition`` 派生（本函数不含第二套优先级规则）；
    未在册但出现在调用点上的 id 记 ``phantom``。"""
    ids = set(descriptor_ids)
    wired, generic, not_wired = live_partition(ids, invoke_hits, generic_hits)
    states: dict[str, str] = {}
    for cid in ids:
        if cid in wired:
            states[cid] = STATE_WIRED
        elif cid in generic:
            states[cid] = STATE_GENERIC
        elif cid in not_wired:
            states[cid] = STATE_NOT_WIRED
        else:  # pragma: no cover  live_partition 三桶铺满 ids，走到这里=判据自身漏网
            raise AssertionError(f"live_partition 未把在册 id {cid} 归入任何一桶（判据漏网，须修）")
    for cid in set(invoke_hits) | set(generic_hits):
        if cid not in ids:
            states[cid] = STATE_PHANTOM
    return states


def _collect(
    syntax_errors: list[str] | None = None,
) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, str]]:
    """一次扫描 + 一次归类，供「机读 JSON」与「人读表格」两条出口共用（不分第二次真树）。"""
    invoke_hits, generic_hits = scan_wiredness(syntax_errors)
    states = classify_all(_load_descriptor_table(), invoke_hits, generic_hits)
    return invoke_hits, generic_hits, states


def census_states(syntax_errors: list[str] | None = None) -> dict[str, str]:
    """{capability_id: 态}——人读报表的取数出口（态全部来自 ``classify_all``）。"""
    return _collect(syntax_errors)[2]


def buckets_of(states: dict[str, str]) -> dict[str, list[str]]:
    """按态归桶打印（态名唯一来源 ``REPORT_STATES``；数全现算，不手写计数）。"""
    buckets: dict[str, list[str]] = {state: [] for state in REPORT_STATES}
    for cid, state in sorted(states.items()):
        assert state in buckets, f"普查冒出未知态 {state}（{cid}）——态名与报表桶名脱节"
        buckets[state].append(cid)
    return buckets


def build_census(syntax_errors: list[str] | None = None) -> dict[str, dict[str, list[str]]]:
    """{capability_id: {"wired":[rel…],"generic":[rel…],"phantom":[rel…]}}（机读 --json 出口）。

    每条的态请走 ``census_states``（同一支判据）——本函数只给「命中在哪些文件」的明细。

    RF2-5：扫描途中遇语法错误文件不再静默 `continue`——记进 `syntax_errors`（若传入）交调用方
    在输出里显式点名，与 parity 门「当场炸」口径一致（普查是报告脚本：坏文件采点名而非 raise，
    免一份坏文件让整个台账不可用，但绝不无声吞掉）。"""
    invoke_hits, generic_hits, states = _collect(syntax_errors)
    census: dict[str, dict[str, list[str]]] = {}
    for cid in sorted(states):
        entry = {
            "wired": sorted(invoke_hits.get(cid, set())),
            "generic": sorted(generic_hits.get(cid, set())),
            "phantom": [],
        }
        if states[cid] == STATE_PHANTOM:  # 幽灵调用点：调用点上出现、但不在册的 id。
            entry["phantom"] = ["<不在 CAPABILITY_DESCRIPTOR>"]
        census[cid] = entry
    return census


def _family(cid: str) -> str:
    head = cid.split(".", 1)[0]
    return head if "." in cid else cid


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="输出机读 JSON（默认人读表格）")
    args = parser.parse_args(argv)

    syntax_errors: list[str] = []
    if args.json:
        census = build_census(syntax_errors)
    else:
        states = census_states(syntax_errors)
    if syntax_errors:  # RF2-5：语法错误必须显式点名，绝不静默（走 stderr，--json 的 stdout 保持纯净）
        print(
            f"[SYNTAX-ERROR] 扫描期解析失败 {len(syntax_errors)} 份文件（未计入任何态，须修）："
            + "".join(f"\n  ! {rel}" for rel in syntax_errors),
            file=sys.stderr,
        )
    import json

    if args.json:
        print(json.dumps(census, ensure_ascii=False, indent=2))
        return 0

    by_state = buckets_of(states)
    registered_total = len(states) - len(by_state[STATE_PHANTOM])
    print(f"在册 descriptor 总数：{registered_total}")
    for state in REPORT_STATES:
        cids = by_state[state]
        print(f"\n[{state}] {len(cids)} 条")
        fam: dict[str, int] = {}
        for cid in cids:
            fam[_family(cid)] = fam.get(_family(cid), 0) + 1
        for f in sorted(fam):
            members = [c for c in cids if _family(c) == f]
            print(f"  - {f}: {fam[f]}  ({', '.join(members)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
