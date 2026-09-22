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
"""

from __future__ import annotations

import ast
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

#: 全模块现算一次（锁①③的活体半边与锁②的现源半边同源，防"两次现算跨窗"）。
_REAL: dict[str, Any] = src.three_states()


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
    check_three_state_identity(_REAL)


def test_relocate_split_recomputes_to_the_same_three_states() -> None:
    """锁①附：`relocate_split(待搬迁全量)` 现算 == `three_states()` 内部产物（单一取数口交叉对账）。"""
    assert ppc.relocate_split(sorted(_REAL["relocate"])) == _REAL["relocate_split"]


def test_lock_is_not_evergreen_scan_has_members() -> None:
    """活性地板（非上限）：待搬迁桶为空 ⇒ 要么全搬完要么取数口塌了，两种都该停下来看。

    S165 窗值 46 枚；本锁立档时现算仍非空。**这不是上限**——枚数涨跌都不红，只有
    「整桶清零」才红（一条都没数到＝取数口坏了，不是大家都归位了——本仓六件套④）。
    """
    assert _REAL["counts"]["relocate"] > 0, (
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
