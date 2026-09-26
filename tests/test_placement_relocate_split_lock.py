"""S191 PLACEMENT-STATE-LOCKS —— 把 S165 交回的三态恒等与 movable 判据钉成常驻锁。

出处（`.superpowers/sdd/2026-09-22-taxonomy/SEAT-S165.md` §七 O-1）：S165 落了「待搬迁」
三态拆分（真可搬 movable / 落点已存在 landing_exists / 基础设施 infrastructure），但其
独占禁线里有「任何既有断言与 `tests/test_physical_placement_gate.py`」，故**未建未改**、
交回建议钉常驻锁。既有断言是禁写面，**本新建文件不是**。

三把锁（对任务书 ②）：
① **三态和 ＝ 待搬迁总数**（恒等 + 互斥覆盖 + `movable` 与 `relocate_split` 同源）；
② **movable 判据不回退**（AST 形状锁）：`relocate_state_of` 必须仍按 domains 落点判
   （`domains_landing_points` 在调用链里、`movable` 不许顶层无条件 return、也不许整体消失）；
   `three_states` 的 `movable` 只准取 `split["movable"]`——有人把它改回「domains 之外＋
   被某 fid 认领」的粗判据（＝待搬迁全量当可搬）必红；
③ **基础设施桶不得并入「已归类」**（防洗账）：活体集合判据（三桶 ⊆ 待搬迁、与已归类两两
   不相交）＋ 码路锁（`relocate` 只准由 `claiming_fids` 定义、`classified` 必须减去
   relocate、顶层 `relocate` 回读仍是被认领全量）。

纪律（任务书 ①④）：复用同一取数口（`shim_retirement_census.three_states()` 内部即调
`physical_placement_census.relocate_split()`），**禁复制逻辑**——本文件只钉形状与集合
不变量，不含任何分桶判据的第二实现；**只登记不设上限**：无新 `_CEILING`/`_BASELINE`，
转正基线归门 owner。反向自测全部走内存合成源码/合成 dict，不往源码树写一个字。

> **本纪律的一处受权例外（2026-09-25，锁④ movable Δ 哨兵）**：授权出处＝用户 P-4
> 「立哨兵，按推荐执行」（`.superpowers/sdd/2026-09-24-central-dispatch/RULINGS-20260924.md`
> §R-250925-8 第 4 条①），范围**只这一格**——给 `movable` 的单步跳变立哨兵，判据本体
> （`relocate_state_of` / `domains_landing_points` / 三态恒等 / 耦合和账）**一字未动**。
> 上方"无新 `_CEILING`"因此不再逐字成立；除锁④外本文件仍不设任何上限。
"""

from __future__ import annotations

import ast
import functools
import re
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import physical_placement_census as ppc  # 取数口一（三态判据真身）
import shim_retirement_census as src  # 取数口二（三态账目真身）

PPC_PY = REPO_ROOT / "scripts" / "physical_placement_census.py"
SRC_PY = REPO_ROOT / "scripts" / "shim_retirement_census.py"

#: S165 交回件窗值（2026-09-22，`shim_retirement_census --report` 原文 §六）：
#: 待搬迁拆分 真可搬 0 | 落点已存在 8 | 基础设施 38。留作**出处注释**——
#: 本文件不断言它（只登记不设上限；断言窗值＝变相基线，转正归门 owner）。
S165_WINDOW_SPLIT: dict[str, int] = {
    "movable": 0,
    "landing_exists": 8,
    "infrastructure": 38,
}

@functools.lru_cache(maxsize=1)
def _real_states() -> dict[str, Any]:
    """函数内取数（TX172 ②）：旧版在**模块顶层**调 `three_states()` ⇒ 并发窗口里一发瞬时坏读
    （撕裂/被删的在飞文件）会把红报成「collect error」、归因被推到删壳波头上（TX170 §3-① 放大器）。
    现改为首次**用例执行期**取数：collection 不再执行取数口；`lru_cache` 只缓存成功结果 ⇒
    全进程仍只现算一次（锁①③的活体半边与锁②的现源半边同源，防"两次现算跨窗"），且红落在
    具体用例上、可归因。不删用例、不改断言、不加 skip。
    """
    return src.three_states()


# ==========================================================================
# 锁① / 锁③（活体集合半边）：三态恒等 + 基础设施不被洗进「已归类」
# ==========================================================================
def check_three_state_identity(states: dict[str, Any]) -> None:
    """对 `three_states()` 形状（或其内存副本）判恒等/互斥/同源，不合即抛 AssertionError。

    判据本体全在取数口里，这里**只做集合不变量**：
    - 键恒为 `RELOCATE_STATES` 三枚、每桶有序；
    - 三桶两两不相交、并起来**恰等于** `relocate` 全量（和＝总数，不多不少不重）；
    - 三桶 ⊆ `relocate` ∧ ∧ `relocate ∩ classified = ∅` ⇒ 基础设施/落点已存在**不许**
      被并进「已归类」（防洗账：搬账洗成归类＝债凭空消失）；
    - `movable` 键 == `relocate_split["movable"]`（同一支数，禁第二真身）；
    - `counts`/`relocate_counts` 与清单逐一对账；顶层三态之和 == `outside`（分区恒等）。
    """
    relocate = list(states["relocate"])
    classified = list(states["classified"])
    buckets_raw = states["relocate_split"]
    assert isinstance(buckets_raw, dict), f"relocate_split 必须是 dict，实为 {type(buckets_raw).__name__}"
    assert set(buckets_raw) == set(ppc.RELOCATE_STATES), (
        f"三态键漂移：{sorted(buckets_raw)} ≠ {sorted(ppc.RELOCATE_STATES)}——桶名被人改/并，判据已换真身"
    )
    flat: list[str] = []
    sets: dict[str, set[str]] = {}
    for state in ppc.RELOCATE_STATES:
        members = list(buckets_raw[state])
        assert members == sorted(members), f"桶 {state} 未排序——与取数口出口形状不合"
        assert len(members) == len(set(members)), f"桶 {state} 内部有重复路径"
        sets[state] = set(members)
        flat.extend(members)
    for i, a in enumerate(ppc.RELOCATE_STATES):
        for b in ppc.RELOCATE_STATES[i + 1 :]:
            assert not (sets[a] & sets[b]), f"三态不相交被破坏：{sorted(sets[a] & sets[b])} 同落 {a}/{b} 两桶"
    assert sorted(flat) == sorted(relocate) and len(flat) == len(relocate), (
        f"三态之和（{len(flat)}）≠ 待搬迁总数（{len(relocate)}）——恒等式被破坏（缺员/虚增/重复）"
    )
    for state in ppc.RELOCATE_STATES:
        assert sets[state] <= set(relocate), f"{state} 桶里冒出待搬迁之外的路径（虚增）"
    assert not (set(relocate) & set(classified)), "relocate ∩ classified ≠ ∅——顶层三态不再互斥"
    assert not (sets["infrastructure"] & set(classified)), (
        "基础设施桶被并入「已归类」＝洗账（46 枚假阳的老路 reversed）：债必须还在 relocate 名下"
    )
    assert not (sets["landing_exists"] & set(classified)), "落点已存在桶被并入「已归类」＝洗账"
    assert list(states["movable"]) == list(buckets_raw["movable"]), (
        "movable 键与 relocate_split['movable'] 不同源——出现第二真身"
    )
    counts = states["counts"]
    assert counts["relocate"] == len(relocate), "counts.relocate 与清单枚数不符"
    assert counts["classified"] == len(classified), "counts.classified 与清单枚数不符"
    assert counts["retire_shims"] == len(states["retire_shims"]), "counts.retire_shims 与清单枚数不符"
    relocate_counts = states["relocate_counts"]
    assert relocate_counts == {s: len(buckets_raw[s]) for s in ppc.RELOCATE_STATES}, (
        "relocate_counts 与三桶实数不符——总数另算一套（假绿老路）"
    )
    assert states["outside"] == counts["retire_shims"] + counts["relocate"] + counts["classified"], (
        "顶层三态（待退役+待搬迁+已归类）之和不等于域外全量——分区恒等被破坏"
    )


def test_three_state_identity_holds_on_live_ledger() -> None:
    """锁①：现算账目上，三态和恒等于待搬迁总数，且各对账键同源（S165 O-1 第一把）。"""
    check_three_state_identity(_real_states())


def test_relocate_split_recomputes_to_the_same_three_states() -> None:
    """锁①附：`relocate_split(待搬迁全量)` 现算 == `three_states()` 内部产物（单一取数口交叉对账）。"""
    assert ppc.relocate_split(sorted(_real_states()["relocate"])) == _real_states()["relocate_split"]


def test_lock_is_not_evergreen_scan_has_members() -> None:
    """活性地板（非上限）：待搬迁桶为空 ⇒ 要么全搬完要么取数口塌了，两种都该停下来看。

    S165 窗值 46 枚；本锁立档时现算仍非空。**这不是上限**——枚数涨跌都不红，只有
    「整桶清零」才红（一条都没数到＝取数口坏了，不是大家都归位了——本仓六件套④）。
    """
    assert _real_states()["counts"]["relocate"] > 0, (
        "待搬迁整桶清零——按本仓惯例判『取数口塌陷』优先于『债已清』，交门 owner 现算核"
    )


# ==========================================================================
# 锁②：movable 判据不回退（AST 形状锁，钉两份真身的判据码路）
# ==========================================================================
def _module(source: str) -> ast.Module:
    return ast.parse(source)


def _func(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _call_names(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        if isinstance(call.func, ast.Name):
            out.add(call.func.id)
        elif isinstance(call.func, ast.Attribute):
            out.add(call.func.attr)
    return out


def _all_string_returns(fn: ast.FunctionDef) -> set[str]:
    return {
        node.value.value
        for node in ast.walk(fn)
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
    }


def _top_level_string_returns(fn: ast.FunctionDef) -> set[str]:
    """函数体**第一层**（不在任何 If/For/Try/While 里）的字符串 return——即"无条件返回"。"""
    out: set[str] = set()
    for stmt in fn.body:
        if isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
            out.add(stmt.value.value)
    return out


def _refs_name(node: ast.AST, name: str) -> bool:
    return any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(node))


def _has_membership_against(fn: ast.FunctionDef, name: str) -> bool:
    """存在 `x in domain_roots` 形的成员判定（白名单尺子的活体形状）。"""
    for node in ast.walk(fn):
        if not isinstance(node, ast.Compare):
            continue
        if not any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
            continue
        sides: list[ast.expr] = [node.left, *node.comparators]
        if any(_refs_name(side, name) for side in sides):
            return True
    return False


def _return_dict(fn: ast.FunctionDef) -> dict[str, ast.expr] | None:
    """取形如 `return { "k": v, ... }` 的字面键→值表达式映射（三态账的出口形状）。"""
    for node in ast.walk(fn):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            out: dict[str, ast.expr] = {}
            for key, value in zip(node.value.keys, node.value.values):
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    out[key.value] = value
            return out
    return None


def _assign_value(fn: ast.FunctionDef, target: str) -> ast.expr | None:
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == target for t in node.targets):
            return node.value
    return None


def check_movable_regression(ppc_source: str, src_source: str) -> list[str]:
    """形状锁：返回问题清单（空表＝合格）。两份真身共用一支尺，注毒席直接喂合成源码。

    钉的是 S165 之后**不回退**的四条文法：
    R1 `RELOCATE_STATES` 恒为三枚 `(movable, landing_exists, infrastructure)`；
    R2 `relocate_state_of` 必须调 `domains_landing_points` 判落点，`movable` 只准在守卫里
       return（顶层无条件 `return "movable"` ＝ 粗判据塞回；`movable` 整体消失 ＝ 恒假零）；
    R3 `domains_landing_points` 必须走 G-P1 同源件（`claiming_fids` + `_domain_of` +
       `domain_roots` 成员判定），白名单改宽必然可见；
    R4 `three_states`：`relocate` 只准由 `claiming_fids` 定义（禁经 `relocate_split` 缩桶）、
       `classified` 必须引用 `relocate` 做减法、`movable` 出口必须恰为 `split["movable"]`、
       `relocate` 出口必须是被认领全量本身（不再是 split 派生）。
    """
    problems: list[str] = []
    tree_p = _module(ppc_source)
    tree_s = _module(src_source)

    # R1 —— 三态名字表
    rs: Any = None
    for node in tree_p.body:
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = node.targets
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target]
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == "RELOCATE_STATES" for t in targets) and node.value is not None:
            rs = ast.literal_eval(node.value)
    if rs != ("movable", "landing_exists", "infrastructure"):
        problems.append(f"R1 RELOCATE_STATES 不再是三枚 S165 态名（实为 {rs!r}）——三态恒等式失去对象")

    # R2 —— relocate_state_of
    f = _func(tree_p, "relocate_state_of")
    if f is None:
        problems.append("R2 `relocate_state_of` 消失——三态判定真身被摘")
    else:
        calls = _call_names(f)
        if "domains_landing_points" not in calls:
            problems.append("R2 `relocate_state_of` 不再经 `domains_landing_points` 判落点＝回退为粗判据（domains 之外＋被认领）")
        rets_all = _all_string_returns(f)
        rets_top = _top_level_string_returns(f)
        if "movable" in rets_top:
            problems.append("R2 `movable` 出现顶层无条件 return——任何被认领的域外件都会被算成真可搬（假阳复活）")
        if "movable" not in rets_all:
            problems.append("R2 `movable` 判支整体消失——真可搬恒 0 是另一种假账")
        if "infrastructure" not in rets_all:
            problems.append("R2 `infrastructure` 判支消失——基础设施假阳将重新记进搬迁任务（46 枚老账）")

    # R3 —— domains_landing_points（G-P1 同源证明的形状腿）
    g = _func(tree_p, "domains_landing_points")
    if g is None:
        problems.append("R3 `domains_landing_points` 消失——落点判定失去唯一实现")
    else:
        gcalls = _call_names(g)
        if "claiming_fids" not in gcalls:
            problems.append("R3 认领侧不再走 `claiming_fids`——出现第二套认领逻辑")
        if "_domain_of" not in gcalls:
            problems.append("R3 落点不再经 `_domain_of`（G-P1 同源判据被换掉，白名单改宽将不再联动）")
        if not _has_membership_against(g, "domain_roots"):
            problems.append("R3 domains 白名单成员判定消失——『落点是否落进白名单』这问不再被问")

    # R4 —— three_states 的记账码路
    h = _func(tree_s, "three_states")
    if h is None:
        problems.append("R4 `three_states` 消失——三态账目真身被摘")
    else:
        relocate_val = _assign_value(h, "relocate")
        if relocate_val is None:
            problems.append("R4 `relocate` 清单定义消失——账的形状已不是账的形状")
        else:
            rcalls = _call_names(relocate_val)
            if "claiming_fids" not in rcalls:
                problems.append("R4 `relocate` 不再由 `claiming_fids` 定义——『被认领的域外件』全量失去唯一实现")
            tainted = rcalls & {"relocate_split", "relocate_state_of", "domains_landing_points"}
            if tainted:
                problems.append(f"R4 `relocate` 定义里出现分桶判据 {sorted(tainted)}——用三态把待搬迁缩桶＝把真债改成不计（§0 六禁）")
        classified_val = _assign_value(h, "classified")
        if classified_val is None:
            problems.append("R4 `classified` 定义消失")
        elif not _refs_name(classified_val, "relocate"):
            problems.append("R4 `classified` 不再减去 relocate——基础设施将被并进『已归类』（洗账通道打开）")
        split_val = _assign_value(h, "split")
        if split_val is None or "relocate_split" not in _call_names(split_val):
            problems.append("R4 三态拆分不再由 `relocate_split` 现算——第二实现疑现")
        out = _return_dict(h)
        if out is None:
            problems.append("R4 `three_states` 出口不再是字面 dict——账的形状已变，本锁拒盲钉")
        else:
            # 顶层出口只有 `movable`/`relocate_split`/`relocate` 三键走 split 派生路
            # （landing_exists/infrastructure 不单列顶层键，它们的形状由 relocate_split 本体管）。
            value = out.get("movable")
            exact = (
                isinstance(value, ast.Subscript)
                and isinstance(value.value, ast.Name)
                and value.value.id == "split"
                and isinstance(value.slice, ast.Constant)
                and value.slice.value == "movable"
            )
            if not exact:
                problems.append(
                    "R4 出口 'movable' 不再是 split['movable'] 的逐字派生——"
                    "movable 被改回粗判据（或被另算）即此形"
                )
            split_out = out.get("relocate_split")
            if split_out is None or not _refs_name(split_out, "split"):
                problems.append("R4 出口 'relocate_split' 不再回读现算拆分——三态拆分被旁路")
            rel_out = out.get("relocate")
            if rel_out is None or not _refs_name(rel_out, "relocate") or _refs_name(rel_out, "split"):
                problems.append("R4 顶层 `relocate` 出口不再是『被认领域外件』全量——三态桶反噬顶层账")
    return problems


def test_movable_criteria_shape_holds_on_real_sources() -> None:
    """锁②活体半边：两份真身现读 AST，形状零漂移。"""
    problems = check_movable_regression(
        PPC_PY.read_text(encoding="utf-8"),
        SRC_PY.read_text(encoding="utf-8"),
    )
    assert problems == [], "movable 判据/账路形状漂移：\n" + "\n".join(problems)


# ==========================================================================
# ③ 反向自测三发（全内存：合成源码 + 合成账目 dict，源码树零写入）
# ==========================================================================
_COARSE_STATE_OF = '''def relocate_state_of(rel, *, claims_by_fid=None, domains_root=None, domain_roots=None, path_exists=None):
    """注毒 a：把三态判定塞回粗判据——凡被认领的域外件一律『真可搬』。"""
    return "movable"


'''

_ALWAYS_INFRA_STATE_OF = '''def relocate_state_of(rel, *, claims_by_fid=None, domains_root=None, domain_roots=None, path_exists=None):
    """注毒 a′：反向假零——一律『基础设施』，movable 恒 0 也算一种不回退的假账。"""
    return "infrastructure"


'''


def _poison_ppc(body: str, needle: str = "def relocate_state_of(") -> str:
    source = PPC_PY.read_text(encoding="utf-8")
    poisoned = re.sub(r"def relocate_state_of\(.*?(?=\ndef )", lambda _m: body, source, count=1, flags=re.DOTALL)
    assert poisoned != source, f"注毒未落（找不到 {needle!r} 段）——探针本身失效，红要算探针的"
    ast.parse(poisoned)  # 合成源码必须可解析，否则"被 ast.parse 崩掉"会伪装成"被抓到"
    return poisoned


def test_poison_a_coarse_movable_criteria_is_caught() -> None:
    """注毒 a：粗判据塞回（顶层无条件 movable / 恒假 infra）⇒ 形状锁必红。"""
    problems = check_movable_regression(_poison_ppc(_COARSE_STATE_OF), SRC_PY.read_text(encoding="utf-8"))
    assert any("粗判据" in p or "顶层无条件" in p for p in problems), f"注毒 a 未被抓到：{problems}"
    problems2 = check_movable_regression(_poison_ppc(_ALWAYS_INFRA_STATE_OF), SRC_PY.read_text(encoding="utf-8"))
    assert any("movable" in p for p in problems2), f"注毒 a′（恒假零形态）未被抓到：{problems2}"


def test_poison_a2_coarse_three_states_movable_is_caught() -> None:
    """注毒 a″：账目侧粗判据——`movable` 出口改回待搬迁全量（46 枚假阳的原始形状）。"""
    source = SRC_PY.read_text(encoding="utf-8")
    poisoned = source.replace('"movable": split["movable"]', '"movable": sorted(relocate)')
    assert poisoned != source, "注毒未落：three_states 出口形状已变，探针先于判据红——交门 owner 复钉"
    ast.parse(poisoned)
    problems = check_movable_regression(PPC_PY.read_text(encoding="utf-8"), poisoned)
    assert any("movable" in p for p in problems), f"注毒 a″ 未被抓到：{problems}"


def _synthetic_base_states() -> dict[str, Any]:
    """合成账目（S165 §五 同哲学）：4 枚域外件，shim 1 / relocate 2 / classified 1。"""

    def pack(buckets: dict[str, list[str]], relocate: list[str], classified: list[str]) -> dict[str, Any]:
        return {
            "outside": 4,
            "retire_shims": ["pkg/shim.py"],
            "relocate": sorted(relocate),
            "classified": sorted(classified),
            "relocate_split": {s: sorted(buckets[s]) for s in ppc.RELOCATE_STATES},
            "movable": sorted(buckets["movable"]),
            "counts": {
                "retire_shims": 1,
                "relocate": len(relocate),
                "classified": len(classified),
            },
            "relocate_counts": {s: len(buckets[s]) for s in ppc.RELOCATE_STATES},
        }

    return pack(
        {"movable": [], "landing_exists": ["control/x1.py"], "infrastructure": ["control/x2.py"]},
        ["control/x1.py", "control/x2.py"],
        ["root_orphan.py"],
    )


def test_synthetic_ledger_passes_the_identity_checker() -> None:
    """探针非恒假之一：合格合成账必须过（否则下面的『必红』全是空跑）。"""
    check_three_state_identity(_synthetic_base_states())


def test_poison_b_infrastructure_washed_into_classified_is_caught() -> None:
    """注毒 b：把基础设施桶并进「已归类」⇒ 恒等/防洗账判据必红。"""
    states = _synthetic_base_states()
    states["classified"] = sorted([*states["classified"], *states["relocate_split"]["infrastructure"]])
    with pytest.raises(AssertionError, match="互斥|已归类|洗账"):
        check_three_state_identity(states)


def test_poison_c_identity_broken_is_caught() -> None:
    """注毒 c：恒等式破坏两形——桶里丢员 / 一枚同落两桶 ⇒ 必红。"""
    lost = _synthetic_base_states()
    buckets = {k: list(v) for k, v in lost["relocate_split"].items()}
    buckets["landing_exists"] = []  # x1 从三桶里消失，但 relocate 仍含它
    lost["relocate_split"] = buckets
    lost["movable"] = buckets["movable"]
    lost["relocate_counts"] = {s: len(buckets[s]) for s in ppc.RELOCATE_STATES}
    with pytest.raises(AssertionError, match="恒等式"):
        check_three_state_identity(lost)

    dup = _synthetic_base_states()
    buckets2 = {k: list(v) for k, v in dup["relocate_split"].items()}
    buckets2["infrastructure"] = sorted([*buckets2["infrastructure"], *buckets2["landing_exists"]])  # x1 同落两桶（先排好序，让不相交锁各抓各的）
    dup["relocate_split"] = buckets2
    dup["relocate_counts"] = {s: len(buckets2[s]) for s in ppc.RELOCATE_STATES}
    with pytest.raises(AssertionError, match="不相交|恒等式"):
        check_three_state_identity(dup)


# ==========================================================================
# TX172：引用索引缓存语义 —— 错误不进缓存，一发撕裂读不钉死整进程（R2 注毒自证）
# ==========================================================================
def test_poison_e_reference_index_only_caches_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """注毒 e（R2 根修自证）：第一次注入坏文件⇒抛且点名；修好后**同进程**第二次调用⇒干净结果。

    旧实现把 `(index, errors)` 二元组一起进 `lru_cache` ⇒ 首次撕裂读把「错误＋缺那枚文件的
    半截索引」钉死在整个进程生命周期，文件改合法后复调仍抛（TX170 §3-① R2 红）。修法＝只缓存
    成功结果——`functools.lru_cache` 的既有语义是异常不进缓存（`bridge._load_icon_asset` 同尺，
    `tests/test_bridge_icon_cache.py` 已把该语义当契约钉），不造第二把量具。
    本用例对**同一个缓存函数对象**连跑「注入→抛→修好→复调」四步；入口 `cache_clear()` 只为
    隔离同进程先跑用例的缓存污染（防假绿），不是被修缺陷的一部分；finally 再清一次，把干净
    缓存状态交还后面的用例（本文件锁①与账目门都还要现算真树）。
    """
    torn = tmp_path / "plugins" / "torn_read.py"
    torn.parent.mkdir(parents=True)
    torn.write_text("def broken(:\n    pass\n", encoding="utf-8")  # 撕裂读样本：语法不可解析
    monkeypatch.setattr(src, "REPO_ROOT", tmp_path)
    src._build_reference_index.cache_clear()
    try:
        with pytest.raises(src.ReferenceIndexError) as excinfo:
            src.reference_index()
        assert "torn_read.py:" in str(excinfo.value), f"未点名文件:行＝R1 的 fail-closed 丢了: {excinfo.value}"
        # 修好文件；**不清缓存**——第二跳必须靠「错误不进缓存」自身恢复（旧实现在此仍抛＝R2）。
        torn.write_text("from os import path\n", encoding="utf-8")
        index = src.reference_index()
        assert "os.path" in index and "plugins/torn_read.py" in index["os.path"], (
            f"修好后第二次调用没拿到干净结果（错误被缓存钉死？）: keys={sorted(index)[:5]}"
        )
    finally:
        src._build_reference_index.cache_clear()


# ==========================================================================
# 锁④：`movable` 单步跳变哨兵（Δ 哨兵）——受权例外，见模块 docstring 末段
# ==========================================================================
#: 审计历史（**追加式**账）：每行 `(日期, 当时的 movable 枚数)`。只准追加、不准改写或删除——
#: 追加一行＝门 owner 对这次跳变显式签字（谁、哪天、认到几枚，diff 里看得见）。
#: 起点 `("2026-09-25", 0)` ＝ 席位 S542 现算值（`three_states()["relocate_counts"]["movable"]`；
#: 同刻 `landing_exists` 6 / `infrastructure` 40。取证：本文件 `test_poison_f_*` 与
#: `.superpowers/sdd/2026-09-24-central-dispatch/probes/s542-1-fanout.py` 实跑 rc=0）。
#: 与上方 `S165_WINDOW_SPLIT` 的**区别就在这儿**：那枚是注释（作者明写"本文件不断言它"），
#: 这枚是执法账——`movable` 0→39 那一跳今天对①②③④⑤五把尺全静默（现算见锁④各腿）。
MOVABLE_AUDIT_HISTORY: tuple[tuple[str, int], ...] = (("2026-09-25", 0),)

#: 允许的**单步上升**枚数。取 1 不是随手挑的数：一次只碰一枚文件的改动最多让一枚文件进 `movable`；
#: 一旦 >1，成因必然落在"一处声明翻动一整棵子树"（fid 目录形认领的广播效应——实测一枚
#: `B09.control-plane-api` 一次能翻 39 枚）。**下降不执法**：真搬走是进展，且"把件从 movable 改判
#: 成别的态"由锁①的恒等＋耦合和账管；把上限往抬的方向由 V4 当场判死。
MOVABLE_DELTA_CEILING = 1

#: 本文件自身源码（防回潮锁的读取口；`__file__` 解析，不依赖 cwd）。
SELF_PY = Path(__file__).resolve()


def fid_fanout_upper_bound(states: dict[str, Any]) -> dict[str, int]:
    """「一枚 fid 补一条落点声明最多能翻动几枚 movable 候选」的上界＝它前缀认领到的待搬迁件数。

    只调既有取数口 `physical_placement_census.claiming_fids`（语义 A 前缀认领，与判据真身同源），
    本函数**不含第二套认领实现**；按枚数降序返回，供哨兵报错时点名"是谁一发声明能翻多少"。
    """
    claims = ppc.flatten_claims(ppc.feature_impl_paths())
    counts: dict[str, int] = {}
    for rel in states["relocate"]:
        for fid in ppc.claiming_fids(rel, claims, semantic="prefix"):
            counts[fid] = counts.get(fid, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def check_movable_delta(
    states: dict[str, Any],
    *,
    history: tuple[tuple[str, int], ...] = MOVABLE_AUDIT_HISTORY,
    ceiling: int = MOVABLE_DELTA_CEILING,
) -> list[str]:
    """Δ 哨兵的唯一判据（纯函数，返回问题清单，空表＝合格；注毒自测直接喂合成账）。

    五腿（每腿各有一发注毒，见 `test_poison_f*`）：
    V1 账的形状——非空、逐枚 `(非空 str, 非负 int)`（`bool` 不算 int）、日期不递减（乱序＝把"上次
       签字值"变成任意值）。
    V2 读数同源——`len(movable)` 必须等于 `relocate_counts["movable"]`：哨兵钉的必须是**派单在用的
       那支数**，有人另算一套就等于把哨兵接到假表上。
    V3 跳变——现值 − 末次签字值 > ceiling ⇒ 红，点名扇出最大的 fid 与唯一合法过账方式。
    V4 反自废——扇出上界仍 >1（广播效应还在）而 `ceiling ≥ 上界` ⇒ 红：上限抬到能盖住整棵子树，
       哨兵只剩形式。将来真把落点判据改 per-file（扇出降到 1）这条自然不成立，属"洞被填了"。
    V5 塌陷——待搬迁全量为 0 时**拒绝宣布合格**：塌了以后 Δ 只会算成"下降"，哨兵会在空账上常青。
    """
    if not history:
        return ["V1 MOVABLE_AUDIT_HISTORY 被清空＝哨兵失去参照点（Δ 无从算起，永不红）"]
    problems: list[str] = []
    for row in history:
        ok_shape = (
            isinstance(row, tuple)
            and len(row) == 2
            and isinstance(row[0], str)
            and bool(row[0].strip())
            and isinstance(row[1], int)
            and not isinstance(row[1], bool)
            and row[1] >= 0
        )
        if not ok_shape:
            problems.append(f"V1 审计行形状不合（应为 (非空日期串, 非负整数)）：{row!r}")
    dates = [row[0] for row in history if isinstance(row, tuple) and len(row) == 2 and isinstance(row[0], str)]
    if dates != sorted(dates):
        problems.append(f"V1 审计日期未升序——把签字行插回中间＝'末次签字值'变成任选值：{dates}")

    if int(states["counts"]["relocate"]) <= 0:
        problems.append(
            "V5 待搬迁全量为 0——取数口塌陷时 Δ 只会算成『下降』，哨兵必须拒绝在这种账上宣布合格"
            "（同 `test_lock_is_not_evergreen_scan_has_members` 的『塌陷优先于债清』口径）"
        )
        return problems

    fan = fid_fanout_upper_bound(states)
    movable_now = len(states["movable"])
    derived = int(states["relocate_counts"]["movable"])
    if movable_now != derived:
        problems.append(
            f"V2 哨兵读数不同源：len(movable)={movable_now} ≠ relocate_counts['movable']={derived}"
            "——movable 被另算了一套，Δ 钉在没人用的数上等于没钉"
        )
    step = movable_now - int(history[-1][1])
    if step > ceiling:
        top = "、".join(f"{fid}×{n}" for fid, n in list(fan.items())[:3]) or "（无 fid 认领）"
        problems.append(
            f"V3 movable 单步上升 {step} 枚（{history[-1][1]} → {movable_now}）> 上限 {ceiling}"
            "——典型成因＝给某个 fid 补了一枚 domains 落点，目录形认领把它名下**整棵子树**一起翻成"
            f"『真可搬』。当前扇出上界前三：{top}。唯一合法过账＝门 owner 追加一行审计历史"
            "（日期 + 当时枚数）并写明理由；禁改写历史行、禁抬上限（上限 ≥ 扇出会立即被 V4 判死）"
        )
    fanout_max = max(fan.values(), default=0)
    if fanout_max > 1 and ceiling >= fanout_max:
        problems.append(
            f"V4 哨兵被自废：MOVABLE_DELTA_CEILING={ceiling} ≥ 当前单-fid 扇出上界 {fanout_max}"
            "——一次广播式声明正好落在上限之内，等于把这一跳放回去"
            "（要放宽就先把落点判据改 per-file，让扇出真的降到 1）"
        )
    return problems


def check_sentinel_wiring(source: str) -> list[str]:
    """防回潮锁（AST，钉本文件自身）：哨兵的**执法半边**必须还活着。

    "字段在册、门不检查"是本窗反复栽倒的形态（新增判据没人执行＝零信号）。这一支专防三种拆法：
    W1 常量或判据函数被摘；W2 没有任何 `test_*` 调它；W3 调用了、但第一枚实参不再是真树取数口
    `_real_states()`（换成合成账＝门常青而读数与树无关）。
    """
    problems: list[str] = []
    tree = ast.parse(source)
    assigned = {
        t.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for t in node.targets
        if isinstance(t, ast.Name)
    } | {
        node.target.id
        for node in tree.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    for const in ("MOVABLE_AUDIT_HISTORY", "MOVABLE_DELTA_CEILING"):
        if const not in assigned:
            problems.append(f"W1 常量 {const} 消失——Δ 哨兵的参照点/阈值被摘")
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    if "check_movable_delta" not in funcs:
        problems.append("W1 `check_movable_delta` 消失——哨兵判据本体被摘")
    live_calls = 0
    for name, fn in funcs.items():
        if not name.startswith("test_"):
            continue
        for call in ast.walk(fn):
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
                continue
            if call.func.id != "check_movable_delta" or not call.args:
                continue
            first = call.args[0]
            if isinstance(first, ast.Call) and isinstance(first.func, ast.Name) and first.func.id == "_real_states":
                live_calls += 1
    if live_calls == 0:
        problems.append(
            "W3 没有任何 `test_*` 拿 `_real_states()`（真树取数口）调 `check_movable_delta`"
            "——哨兵只剩定义没有执法半边（注毒 g 实测过这支的杀伤力）"
        )
    return problems


def test_movable_delta_sentinel_holds_on_live_ledger() -> None:
    """锁④活体半边：真树现算账必须合格（今值 movable=0，与末次签字行同值）。"""
    problems = check_movable_delta(_real_states())
    assert problems == [], "movable Δ 哨兵判红：\n" + "\n".join(problems)


def test_movable_delta_sentinel_is_wired_live() -> None:
    """锁④防回潮：本文件里哨兵的执法半边（常量／判据／真树调用点）三件齐全。"""
    problems = check_sentinel_wiring(SELF_PY.read_text(encoding="utf-8"))
    assert problems == [], "Δ 哨兵的执法半边断了：\n" + "\n".join(problems)


def _synthetic_landing_flip(states: dict[str, Any]) -> dict[str, Any]:
    """全内存"合法翻正"：给扇出最大的 fid 追加一枚**落进 domains 白名单且盘上不存在**的落点，
    再用**判据真身**（`ppc.relocate_split` 的 `claims_by_fid` 注入缝）重算三态——源码树零写入。

    注入的是声明数据，不是判据代码：走的仍是 `relocate_state_of` → `domains_landing_points`
    那条唯一码路（锁②的 AST 形状对它一字未动），所以这一发测的是"真跳变能不能被哨兵抓到"，
    不是"我造的假账能不能被抓到"。
    """
    rows = ppc.feature_impl_paths()
    fan = fid_fanout_upper_bound(states)
    assert fan, "扇出上界为空——没有可翻的对象，注毒会空跑（红要算探针的）"
    victim_fid = next(iter(fan))
    domains_root = str(ppc.load_placement()["DOMAINS_ROOT"])
    root = min(ppc.registered_domain_roots())
    landing = f"{domains_root}/{root}/s542-nonexistent-landing.py"
    assert not (ppc.REPO_ROOT / landing).exists(), "合成落点必须不存在，否则测的不是 movable 那一跳"
    synthetic = sorted(
        (fid, tuple(dict.fromkeys([*paths, landing]))) if fid == victim_fid else (fid, paths)
        for fid, paths in rows
    )
    flipped = ppc.relocate_split(sorted(states["relocate"]), claims_by_fid=synthetic)
    out = dict(states)
    out["relocate_split"] = flipped
    out["movable"] = flipped["movable"]
    out["relocate_counts"] = {k: len(v) for k, v in flipped.items()}
    out["_s542_victim_fid"] = victim_fid
    return out


def test_poison_f_one_legal_landing_flip_is_caught() -> None:
    """注毒 f（真·合法翻正，全内存）：补一枚 domains 落点 ⇒ 整棵子树翻 movable ⇒ Δ 哨兵必红一次。

    同时钉住"这一跳有多大"：报出的跳变枚数必须恰等于该 fid 的扇出上界（否则就是哨兵在报一支
    与扇出无关的数，正对照不成立）。
    """
    live = _real_states()
    flipped = _synthetic_landing_flip(live)
    victim = str(flipped["_s542_victim_fid"])
    fan = fid_fanout_upper_bound(live)
    problems = check_movable_delta(flipped)
    hits = [p for p in problems if p.startswith("V3")]
    assert hits, f"注毒 f 未被抓到（合法翻正静默通过＝哨兵是死的）：{problems}"
    jumped = len(flipped["movable"]) - len(live["movable"])
    assert jumped == fan[victim] > 1, f"跳变量 {jumped} 不等于扇出 {fan.get(victim)}——探针没打在广播效应上"
    assert victim in hits[0], f"红没点名肇事 fid {victim}：{hits[0][:200]}"


def test_poison_f1_positive_control_countersigned_flip_passes() -> None:
    """正对照（防恒假）：同一枚翻正，只要**追加**一行签字（当时枚数），Δ 腿就必须放行。

    没有这一发，"注毒 f 必红"只证明判据在报任意跳变，不证明它区分"没人签字"与"有人签字"。
    """
    flipped = _synthetic_landing_flip(_real_states())
    signed = (*MOVABLE_AUDIT_HISTORY, ("2026-09-26", len(flipped["movable"])))
    problems = [p for p in check_movable_delta(flipped, history=signed) if p.startswith("V3")]
    assert problems == [], f"已签字的翻正仍被 V3 拦住＝签字路是死的（门只准变严，不准变成过不去）：{problems}"


def test_poison_f2_raised_ceiling_defangs_sentinel() -> None:
    """注毒 f2（抬上限＝自废）：把 ceiling 抬到扇出上界之上/之 ⇒ V4 必红。"""
    live = _real_states()
    fanout_max = max(fid_fanout_upper_bound(live).values(), default=0)
    assert fanout_max > 1, "扇出上界已 ≤1（广播效应消失）——V4 这条腿今天失去对象，须交 owner 复判"
    problems = check_movable_delta(live, ceiling=fanout_max)
    assert any(p.startswith("V4") for p in problems), f"抬上限到 {fanout_max} 未被 V4 抓到：{problems}"


def test_poison_f3_history_shape_and_disorder_are_caught() -> None:
    """注毒 f3（签字账被做坏）：空账 / 负数 / bool / 日期倒序 —— 四种各必红一次。"""
    live = _real_states()
    assert check_movable_delta(live, history=()) != [], "空历史未被抓：Δ 无从算起，哨兵永不红"
    assert any("V1" in p for p in check_movable_delta(live, history=(("2026-09-25", -3),))), "负数签字值未被抓"
    assert any(
        "V1" in p for p in check_movable_delta(live, history=(("2026-09-25", True),))
    ), "bool 混进枚数列未被抓（bool 是 int 子类，漏判＝签字值可以被写成任何东西）"
    messy = (("2026-12-31", 0), ("2026-09-25", 39))
    assert any("V1" in p for p in check_movable_delta(live, history=messy)), "日期倒序未被抓"


def test_poison_f4_movable_second_reading_is_caught() -> None:
    """注毒 f4（读数另算一套）：`movable` 与 `relocate_counts['movable']` 不符 ⇒ V2 必红。"""
    live = _real_states()
    drifted = dict(live)
    drifted["relocate_counts"] = {**live["relocate_counts"], "movable": len(live["movable"]) + 1}
    problems = check_movable_delta(drifted)
    assert any(p.startswith("V2") for p in problems), f"movable 第二真身未被抓到：{problems}"


def test_poison_f5_collapsed_bucket_is_caught() -> None:
    """注毒 f5（取数口塌陷）：待搬迁清零 ⇒ V5 必红，绝不在空账上宣布合格。"""
    live = _real_states()
    collapsed = dict(live)
    collapsed["counts"] = {**live["counts"], "relocate": 0}
    collapsed["relocate"] = []
    collapsed["movable"] = []
    collapsed["relocate_counts"] = {**live["relocate_counts"], "movable": 0}
    problems = check_movable_delta(collapsed)
    assert any(p.startswith("V5") for p in problems), f"整桶清零未被抓到，哨兵会在塌了的账上常青：{problems}"


def test_poison_g_sentinel_unwired_is_caught() -> None:
    """注毒 g（拆执法半边，全内存改源码文本）：真树调用点被摘 ⇒ 防回潮锁必红；三种拆法各验一发。"""
    source = SELF_PY.read_text(encoding="utf-8")
    assert check_sentinel_wiring(source) == [], "本文件当前就不合防回潮锁——后面的注毒全是空跑"

    def _poison(text: str, old: str, new: str, label: str) -> str:
        out = text.replace(old, new, 1)
        assert out != text, f"{label}：注毒未落（找不到锚点），红要算探针的"
        ast.parse(out)  # 合成源码必须可解析，否则"被 ast.parse 崩掉"会伪装成"被抓到"
        return out

    w3 = _poison(source, "check_movable_delta(_real_states())", "check_movable_delta(_synthetic_base_states())", "W3")
    assert any(p.startswith("W3") for p in check_sentinel_wiring(w3)), "W3：换成合成账没被抓到"
    w1 = _poison(source, "MOVABLE_DELTA_CEILING = 1", "MOVABLE_DELTA_CEILING_S542_GONE = 1", "W1")
    assert any(p.startswith("W1") for p in check_sentinel_wiring(w1)), "W1：常量改名/摘除没被抓到"
    w2 = _poison(source, "def test_movable_delta_sentinel_holds_on_live_ledger()", "def _gone_test_live_ledger()", "W2")
    assert any(p.startswith("W3") for p in check_sentinel_wiring(w2)), "W2：把活体用例改私有＝没人再执行，没被抓到"

