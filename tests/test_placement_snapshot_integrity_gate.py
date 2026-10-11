"""具名快照自证口的常驻门（席 S99，2026-09-24 中央调度收编波）。

**被谁逼出来**：S96 在 `scripts/physical_placement_census.py` 落了「四本账具名快照」
（`_named_snapshot` / `_edge_snapshot` / `_snapshot_integrity`，见 `SEAT-S96.md` §2），
并在 §5「未执法①」与 §6 Q2 自曝：这套体检**今天只报不判**——没有任何 pytest 断言
`ok is True`，等于「能看见但没人看」。本席按 Q2 选项 A 把它升成常驻执法门。

**本门两条腿（缺一不可）**：
① 独立复算腿（本文件自己的牙）：**不读**尺子自带的体检，逐本账从同一次尺输出里重算三件事——
   槽位在不在（没退回「只存标量」的旧形态）、`count == len(items)`（取证有没有被裁）、
   `count == 标量账`（名与数对不对得上）。
② 尺子体检腿：真跑 `pc._snapshot_integrity(accounts)`，把它报的病并入，并校验它自洽
   （`ok` 与 `problems` 必须互为反值——只报 `ok=True` 却挂着问题清单，本身就是说谎）。

为什么非要两条：只留②，则 `_snapshot_integrity` 被改成恒 `ok`（注毒③，「门禁自身造假」最
省事的写法）本门当场成空跑；只留①，则尺子内部判据被改窄时本门看不见。两条并立 ⇒ 任一侧
失真都被拦。**注毒③的用例就是照这个理由设计的**：它同时断言「只信尺子体检会绿」与
「本门仍红」，证明第二条腿不是装饰。

**口径红线**：
- 单一取数口 = `scripts/physical_placement_census.py::compute_four_accounts()`，与姊妹门
  `tests/test_physical_placement_gate.py` 同一条 import 路；模块级 fixture 跑一次（实测 ≈24s）、
  全件共用，**不起第二条取数路、不起 subprocess**。
- 本门**不抄一个活的期望数**：所有对照值都从同一次尺输出的**两个独立读点**互校
  （名册长度 ↔ 标量账 ↔ 快照内嵌 scalar），写成「两口互校」而不是「抄一个数」。
- 扫描面**地板**：①②③ 仍是手写字面量（只拦「尺子塌了/扫描面被顶穿」，不阻止合法还债——
  P-65/R5 口径，刻意取实测的一半量级；其真身在别席写面，本席不越界派生）；
  **④ 自 2026-10-12 起改由真身名册自己派生**（`_a4_roster_derived_floor`，规则 10：
  会随退役漂移的总数不许写死；两枚前置与取证见该处注释）。
- 反向自证全部走**内存深拷贝**的 accounts：`scripts/` 与真树零写入。

**本门的边界（读绿之前先记住，别当它永远成立）**：
「名册非空」与「地板」两条腿都建立在**今值侧确实有成员**之上。若哪一天某本账**真被还清到 0**
（那是好消息），这两腿会同时红——那是「门该跟着还债波一起改」的信号，不是债主回来了；
owner 须在还债那一波把该腿改成「条件断言」并在 `SEAT-S99.md` 留账，禁止为过门直接删腿。

**本文件的另一半（席 S148，2026-09-24）**：上面整件是**今值侧**具名快照的自证闸（S96 落名册、
S99 落闸）。本文件下半段（「基线侧名册 + 反幻影闸」一节）补的是**基线侧**——把 BASELINE.md 现解析
出来的起点标量钉成一张**起点值名册**并逐枚对账，堵「悄悄抬 BASELINE.md 起点 / 删起点行让 delta 消失」
这条此前无人管的缝（承 S96 §6-Q1、S99 §5-未做①）。两半各证一件事，缺一不可。
"""

from __future__ import annotations

import ast
import copy
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import physical_placement_census as pc  # 唯一取数口（与姊妹门同一条路，禁第二支扫描器）

# --------------------------------------------------------------------------
# 扫描面地板（①②③ 手写字面量＝只拦塌陷、不拦合法下降；④ 派生式＝真身名册自己定，见下）
# 起点值 = 本席 2026-09-24 现算（**当时值**）；现值一律以
# `../ChatBot_Runtime/venv/Scripts/python.exe scripts/physical_placement_census.py --four-accounts --four-accounts-human`
# 现算为准（AGENTS.md 规则 10：叙述与本注释都不充当今值。⚠ `--four-accounts-human` 单独跑不落四本账分支
# ——`main()` 只在 `--four-accounts`/`--four-accounts-out` 那一支里打人读行，单旗会打印两扇门报告）。
# --------------------------------------------------------------------------
#: ① 域外 py（find 尺）成员数。起点值（当时）100。
MIN_A1_OUTSIDE_PY = 50
#: ② 面A 受管行数。起点值（当时）460。
#: 2026-09-29 重录（席 S-FIX-PLACE-FLOOR；判定＝**地板陈旧**，非尺塌）：460 是 2026-09-23
#: 批量套头的暂态——头把 23 枚审计/过程件从面B 顶进面A（0→460），用户裁定 3.A（席 S201）落地
#: `FACE_BY_CATEGORY`＋`GOVERNED_LINE_PATHS` 桶表后按设计蒸发（四把锁在
#: `tests/test_board_taxonomy_gate.py`，含旧头耦合尺 `_old_hat_coupled_face` 对照）。
#: 三基线现算：HEAD(3ea0dfb) 干净 checkout＝**80**（=名录 4 页 79 行＋板块人工区 1 行，全枚在册）／
#: 23:52 保险 zip 未含取数口与那四页（即 zip 态尺==HEAD ⇒ 同 80 量级）／工作树＝**95**（多出的
#: 15 枚是 `.superpowers` 过程副本上的 K-1 `UNVERIFIED_AUTO_ZONE` 行，非治理债）。
#: 尺身证明：`spec_gates_census.py`/`doc_fact_discipline.py` 与全部 worktree/暂存副本逐字节同 hash
#: （108209 B / ccdce239…），取数口未塌、SKIP 未放宽、目录未改名。地板按「实测一半量级」重录
#: （干净 checkout 80 之半＝40；容差一字不动，台账 #68 口径）。⚠ 面A 目标硬零（G-T3 面定义），
#: 名录页还清后本腿仍会再红——届时按本件边界条走「条件断言」并在 `SEAT-S99.md` 留账，禁删腿。
#: 复跑：PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8 \
#:   ../ChatBot_Runtime/venv/Scripts/python.exe scripts/physical_placement_census.py --four-accounts-human
MIN_A2_MANAGED_LINES = 40
#: ② 面B 未归位页数。起点值（当时）170。
MIN_A2_UNMOVED_PAGES = 80
#: ④ 在册名册地板＝**派生式**（席 SEAT-PLACE-FLOOR 2026-10-12；规则 10：会随退役漂移的总数不许写死）。
#:  lineage（当时值，逐档留账）：起点 47 → 2026-09-29 还原波收尾复录 20→15 → 现由真身派生（14）。
#: 旧形态是手抄常数 15（席 S-FIX-PLACE-FLOOR 提交 `1a92fdae`（2026-10-01）现算 15 的**当时值**）。
#: `17a160f`（2026-10-04 P2 减量波·用户授权）把 `SHIM_ROWS` 23→14 时，同批只重录了配对尺
#: `tests/test_shim_retirement_ledger.py::MIN_SHIM_FLOOR`（15→14，逐字见该笔 diff），漏了本门这枚 ⇒ 长期红。
#: 定性取证（HEAD 轴）：`git archive HEAD` → python `tarfile.extractall(filter="data")` 解进 %TEMP% 副本
#: ＋铺 gitignored 的 `.superpowers/` 整本，副本里跑同一把尺同一枚腿读到**逐字相同**的「扫描面 14 < 地板 15」
#: ⇒ 红在 HEAD 成立（非他席在飞）；且 ④ 的 (a)已还清=0 (b)门瞎=0 (c)存在零活性=0、真债同为 14
#: ⇒ 尺看得见名册里每一枚、枚枚在盘上是活垫片 ⇒ **尺没塌，是地板陈旧**。
#: 新形态：地板由真身名册自己派生＝本门**独立** AST 读 `SHIM_ROWS` 源列去重枚数（不经尺的取数口，
#: 两读点互校，与本文件「独立复算腿 ↔ 尺子体检腿」同构），判据取**等值**——比旧的「实测一半量级」更紧：
#: 少看＝取数口塌陷/SKIP 被放宽，多看＝名册被塞幻影/已退役行未清（方向锁：扫描面不许悄悄变大）。
#: 两枚前置（缺一不可）：① 反空转——声明缺席／只声明不赋值／非纯字面量／零行 一律当场抛（拒算≠放行），
#:   本腿另有 `derived > 0` 与尺侧 `available is True` 两道；② 方向锁——派生式只准 `len(真身行集)` 一形
#:   （`_a4_floor_derivation_shape` 在本文件源码上做 AST 形状闸），不许 `= 尺读数`／`max(...)`／`±常数`／
#:   字面量，地板因此**永不跟着读数降**（注毒①当场自证）。
#: ⚠ 边界一：①②③ 三枚地板仍手钉——它们的真身（板块名册 `docs/boards/**`、`.superpowers` 起点册）在别席写面，
#:   本席不越界动；本格的派生面严格限于 ④。
#: ⚠ 边界二：合法退役与派生地板**同批动**——退役一枚须走唯一写口 `scripts/shim_retirement_census.py --write-ledger`
#:   （本席不跑）把真身降到 13，尺读数随之 13 ⇒ 等值照成立；只降尺读数不动真身＝本腿红（这正是注毒①）。
#: 复跑（注意：`--four-accounts-human` 单独跑不落四本账分支，须配 `--four-accounts`，见本席报告）：
#: PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8 \
#:   ../ChatBot_Runtime/venv/Scripts/python.exe scripts/physical_placement_census.py --four-accounts --four-accounts-human
_A4_ROSTER_LEDGER_PY = REPO_ROOT / "plugins/bot_unified_runtime/domains/core/board_shim_ledger.py"


def _a4_roster_source_rows(source_text: str) -> tuple[Any, ...]:
    """④ 地板的派生源：本门**独立** AST 读顶层 `SHIM_ROWS` 字面量（不 import 插件包，同尺纪律）。

    fail-closed（前置①反空转）：声明缺席／只声明不赋值／非纯字面量（含调用拼接）／非元组／行形状不合
    （真身契约＝`(str, str, int)` 三元组，与 `load_ledger_rows` 同口径）／声明出现两处 ⇒ 一律抛，
    绝不折成 0 或「空账」放行（`scripts/shim_retirement_census.py` 同哲学，TX201/S101 先例）。
    零行（`SHIM_ROWS = ()`）留给派生函数按「读到空＝红」判。
    """
    found: list[tuple[Any, ...]] = []
    for node in ast.parse(source_text).body:
        if isinstance(node, ast.Assign):
            names, value = [t.id for t in node.targets if isinstance(t, ast.Name)], node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names, value = [node.target.id], node.value
        else:
            continue
        if "SHIM_ROWS" not in names:
            continue
        if value is None:
            raise AssertionError("④ 派生地板取数口：SHIM_ROWS 只声明不赋值＝读不到，拒算（拒读≠空账放行）")
        try:
            raw = ast.literal_eval(value)
        except (ValueError, TypeError, SyntaxError) as exc:
            raise AssertionError(f"④ 派生地板取数口：SHIM_ROWS 不是纯字面量（手抄/加了计算）⇒ 拒算：{exc}") from exc
        if not isinstance(raw, tuple):
            raise AssertionError(  # noqa: TRY004 - 形状不合属「账不可信」，与 load_ledger_rows 同抛 AssertionError
                f"④ 派生地板取数口：SHIM_ROWS 字面量不是元组（got {type(raw).__name__}）⇒ 拒算")
        for row in raw:
            if (not isinstance(row, tuple) or len(row) != 3
                    or not isinstance(row[0], str) or not isinstance(row[1], str) or not isinstance(row[2], int)):
                raise AssertionError(f"④ 派生地板取数口：SHIM_ROWS 行不是 (str, str, int) 三元组⇒ 拒算：{row!r}")
        found.append(raw)
    if not found:
        raise AssertionError("④ 派生地板取数口：声明源里没有 SHIM_ROWS＝读到空，拒算（不许按 0 放行）")
    if len(found) > 1:
        raise AssertionError(f"④ 派生地板取数口：SHIM_ROWS 声明有 {len(found)} 处，不知吃哪本 ⇒ 拒算")
    return found[0]


def _a4_roster_derived_floor(source_text: str | None = None) -> int:
    """④ 在册名册地板＝真身名册自己派生（方向锁允许的**唯一**形状：`len(真身行集)`）。"""
    text = _A4_ROSTER_LEDGER_PY.read_text(encoding="utf-8") if source_text is None else source_text
    paths = {str(row[0]) for row in _a4_roster_source_rows(text)}
    if not paths:
        raise AssertionError("④ 派生地板取数口读到空名册（SHIM_ROWS=()）＝账具失明，当场红（0 不是地板）")
    return len(paths)


def _a4_face_vs_floor_errors(measured: Any, floor: Any) -> list[str]:
    """④ 判据内核（活例与注毒共口）：反空转 → 读数是不是整数 → 面与真身**等值**（两侧都拦）。"""
    errors: list[str] = []
    if not isinstance(floor, int) or isinstance(floor, bool) or floor <= 0:
        errors.append(f"④ 派生地板={floor!r} 不是正整数＝真身取数口读到空（反空转：0 不放行）")
    if not isinstance(measured, int) or isinstance(measured, bool):
        errors.append(f"④ 在册名册: 尺读数={measured!r} 不是整数＝尺子取数失败")
    elif isinstance(floor, int) and not isinstance(floor, bool):
        if measured < floor:
            errors.append(
                f"④ 在册名册: 尺读数 {measured} < 真身名册枚数 {floor}＝取数口塌陷/SKIP 被放宽/目录改名"
                f"（地板由真身派生，**不跟读数降**，故这里必红）")
        elif measured > floor:
            errors.append(
                f"④ 在册名册: 尺读数 {measured} > 真身名册枚数 {floor}＝名册外幻影/已退役行未清"
                f"（方向锁：扫描面不许悄悄变大而不被真身解释）")
    return errors


def _a4_floor_derivation_shape(source_text: str) -> dict[str, Any]:
    """前置②方向锁的内核：现读本文件源码里 `_a4_roster_derived_floor` 的派生形状（活例与注毒共口）。

    只接受：入参恰 `source_text` 一枚（不许接尺读数）∧ 每个 `return` 都是 `len(本函数内的局部集合名)`，
    且该局部名绑的是**集合形态**（推导式/字面量容器/`set|frozenset|sorted` 调用）。于是
    「`= 尺读数`」「`len(paths) - 1`」「`max(len(paths), 15)`」「`= 14`」「`len(标量)`」
    「多一个 measured 入参」这些让地板跟着被检对象动的写法全被拒
    （同 ③反失明锁 `_literal_baseline_roster_from_source` 的路子）。
    """
    fn = next((n for n in ast.parse(source_text).body
               if isinstance(n, ast.FunctionDef) and n.name == "_a4_roster_derived_floor"), None)
    if fn is None:
        return {"found": False, "returns": [], "bad": ["`_a4_roster_derived_floor` 失踪＝④ 地板退回手抄常数"]}
    bad: list[str] = []
    params = [a.arg for a in (*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs)]
    if params != ["source_text"]:
        bad.append(f"入参不是只有 `source_text`（现 {params}）＝地板可能吃尺读数")
    returns = [n.value for n in ast.walk(fn) if isinstance(n, ast.Return) and n.value is not None]
    if not returns:
        bad.append("函数没有 return＝派生口交不出数")
    collections: dict[str, ast.expr] = {}
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            collections[node.targets[0].id] = node.value
    for value in returns:
        rendered = ast.unparse(value)
        ok_shape = (isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "len"
                    and len(value.args) == 1 and not value.keywords and isinstance(value.args[0], ast.Name))
        if not ok_shape:
            bad.append(f"返回式不是 `len(本函数局部集合)`：{rendered}")
            continue
        local = collections.get(value.args[0].id)  # type: ignore[union-attr]
        is_collection = isinstance(local, (ast.SetComp, ast.DictComp, ast.ListComp, ast.GeneratorExp, ast.Set,
                                           ast.List, ast.Dict, ast.Tuple)) or (
            isinstance(local, ast.Call) and isinstance(local.func, ast.Name)
            and local.func.id in {"set", "frozenset", "sorted", "list"})
        if local is None or not is_collection:
            bad.append(f"`len({value.args[0].id})` 里的 {value.args[0].id!r} 不是本函数局部集合（标量/外来名＝可被读数带着动）")
    return {"found": True, "returns": [ast.unparse(v) for v in returns], "bad": bad}

#: 名册天然不得有重名（路径／页名／id 三形）；t3_managed 是「rel: 值」行、
#: 同页两行合法，故**不**列入本表（列进去就是把合法形态判成造假）。
_DISTINCT_BY_NATURE = frozenset(
    {
        "a1.names.find_disk",
        "a1.names.git_ls_files",
        "a1.names.git_worktree_reconciled",
        "a2.names.t3_unmoved",
        "a4.names.roster",
        "a4.names.real_debt",
    }
)


@pytest.fixture(scope="module")
def four() -> dict[str, Any]:
    """跑一次四本账全量尺（含 git 子进程与 spec_gates_census），模块内共用同一份输出。"""
    return pc.compute_four_accounts()


# --------------------------------------------------------------------------
# 判据（活用例与注毒用例吃同一张表、同一个函数——注毒才可能打红真门）
# --------------------------------------------------------------------------
def _named_pairs(acct: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    """把「具名快照 ↔ 它该对上的标量账」配成一张表（标量全部**从同一次尺输出里取**）。

    配对口径与尺子 `_snapshot_integrity` 逐字对齐（对齐不上就是两套判据在互相糊）：
    - `a1.names.find_disk` ↔ `a1.current`；另两把尺 ↔ 各自 `rulers[slot].count`；
    - `a2.names.t3_managed/t3_unmoved` ↔ `a2.current` 的面A/面B；
    - `a4.names.roster/real_debt` ↔ `a4.roster_count/real_count`。
    """
    a1: dict[str, Any] = acct.get("a1_outside_py_dual_ruler") or {}
    a2: dict[str, Any] = acct.get("a2_page_unplaced") or {}
    a4: dict[str, Any] = acct.get("a4_roster_vs_real_debt") or {}
    rulers: dict[str, Any] = a1.get("rulers") or {}
    a1_names: dict[str, Any] = a1.get("names") or {}
    cur2: dict[str, Any] = a2.get("current") or {}
    a2_names: dict[str, Any] = a2.get("names") or {}
    a4_names: dict[str, Any] = a4.get("names") or {}
    pairs: dict[str, tuple[Any, Any]] = {}
    for slot in ("find_disk", "git_ls_files", "git_worktree_reconciled"):
        scalar: Any = a1.get("current") if slot == "find_disk" else (rulers.get(slot) or {}).get("count")
        pairs[f"a1.names.{slot}"] = (a1_names.get(slot), scalar)
    pairs["a2.names.t3_managed"] = (a2_names.get("t3_managed"), cur2.get("面A_managed"))
    pairs["a2.names.t3_unmoved"] = (a2_names.get("t3_unmoved"), cur2.get("面B_unmoved"))
    pairs["a4.names.roster"] = (a4_names.get("roster"), a4.get("roster_count"))
    pairs["a4.names.real_debt"] = (a4_names.get("real_debt"), a4.get("real_count"))
    return pairs


def _roster_errors(acct: dict[str, Any]) -> list[str]:
    """腿①：独立复算——槽位存在 ∧ `count == len(items)` ∧ `count == 标量账`。

    `available is False` 属尺子诚实降级（取数失败不以空清单冒充零成员，P-S60-2 同族），
    本腿**不**替它记病；但「诚实降级」与「今值侧真的没取证」是两回事——后者由
    `test_real_tree_snapshots_are_available` 在今值侧单独拦。
    """
    errors: list[str] = []
    for tag, (snap, scalar) in _named_pairs(acct).items():
        if not isinstance(snap, dict):
            errors.append(f"{tag}: 具名快照槽缺失（只存标量的旧形态复辟）")
            continue
        if not snap.get("available"):
            continue
        items = snap.get("items")
        if not isinstance(items, list):
            errors.append(f"{tag}: items 不是全集数组（available=True 却交不出名册）")
            continue
        if snap.get("count") != len(items):
            errors.append(f"{tag}: count={snap.get('count')} ≠ len(items)={len(items)}（取证被裁）")
        if snap.get("count") != scalar:
            errors.append(f"{tag}: count={snap.get('count')} ≠ 标量账={scalar}（名与数不符）")
        if tag in _DISTINCT_BY_NATURE and len(set(items)) != len(items):
            errors.append(f"{tag}: 名册有重名（拿重复名凑数＝快照造假的一种）")
    return errors


def _edge_ledger_errors(acct: dict[str, Any]) -> list[str]:
    """腿①之垫片侧：`edges_full` 的边全集 ↔ `current` ↔ `members` ↔ 展示截断旗标。"""
    errors: list[str] = []
    a3: dict[str, Any] = acct.get("a3_shims_two_ledgers") or {}
    for led in ("prod_ledger", "tests_ledger"):
        book: dict[str, Any] = a3.get(led) or {}
        full = book.get("edges_full")
        if not isinstance(full, dict):
            errors.append(f"a3.{led}.edges_full: 具名快照槽缺失（垫片边只报 top_files[:5] 的旧形态复辟）")
            continue
        if full.get("sum_edges") != book.get("current"):
            errors.append(f"a3.{led}: sum_edges={full.get('sum_edges')} ≠ current={book.get('current')}")
        edges = full.get("edges")
        if not isinstance(edges, list):
            errors.append(f"a3.{led}.edges_full.edges: 边全集不是数组")
            continue
        if len(edges) != full.get("members"):
            errors.append(f"a3.{led}: edges 全集长度 {len(edges)} ≠ members {full.get('members')}（边取证被裁）")
        if full.get("members", 0) > 5 and not book.get("top_files_truncated"):
            errors.append(f"a3.{led}: top_files 截到 5 却没标 top_files_truncated（展示截断未显式化）")
    return errors


def _census_judge_errors(acct: dict[str, Any]) -> list[str]:
    """腿②：真跑尺子自己的 `_snapshot_integrity`，并验它自洽（`ok` 必须恰等「无 problems」）。"""
    verdict = pc._snapshot_integrity(acct)
    problems = verdict.get("problems")
    ok = verdict.get("ok")
    if not isinstance(problems, list):
        return [f"snapshot_integrity: problems 不是清单（got {type(problems).__name__}）"]
    if ok is not (not problems):
        return [f"snapshot_integrity: ok={ok} 与 problems({len(problems)} 条) 互为反值不成立（体检自身说谎）"]
    if problems:
        return [f"snapshot_integrity(尺子体检): {item}" for item in problems]
    return []


def _gate_errors(acct: dict[str, Any]) -> list[str]:
    """本门的完整判据 = 两条腿并集。活用例与注毒用例都走这里。"""
    return _roster_errors(acct) + _edge_ledger_errors(acct) + _census_judge_errors(acct)


# --------------------------------------------------------------------------
# 正向：真跑尺一次，断言体检 ok 且问题清单为空（S96 §6 Q2 要的那一句）
# --------------------------------------------------------------------------
def test_real_tree_snapshot_integrity_is_clean(four: dict[str, Any]) -> None:
    """常驻执法断言（S96 只报不判的那一枚）：真树跑出的体检必须 ok 且清单为空。"""
    errors = _gate_errors(four["accounts"])
    assert not errors, "具名快照体检不干净：\n" + "\n".join(f"  - {e}" for e in errors)
    published = four.get("snapshot_integrity")
    assert isinstance(published, dict) and published.get("ok") is True, (
        f"出口里发布的体检不是 ok：{published}"
    )
    assert published.get("problems") == [], f"出口体检挂着问题清单：{published.get('problems')}"
    # 同一次输出、两次判读必须逐字一致（否则体检非确定性，读到的绿不可复现）
    assert pc._snapshot_integrity(four["accounts"]) == published


def test_real_tree_snapshots_are_available(four: dict[str, Any]) -> None:
    """今值侧「诚实降级」不接受：四本账的具名快照必须真的取到了数（available 全 True）。"""
    not_available: list[str] = []
    for tag, (snap, _scalar) in _named_pairs(four["accounts"]).items():
        if not isinstance(snap, dict) or not snap.get("available"):
            not_available.append(tag)
    a3: dict[str, Any] = (four["accounts"].get("a3_shims_two_ledgers") or {})
    for led in ("prod_ledger", "tests_ledger"):
        full = (a3.get(led) or {}).get("edges_full")
        if not isinstance(full, dict) or not full.get("available"):
            not_available.append(f"a3.{led}.edges_full")
    assert not not_available, f"这些账今值侧交出具名快照失败（读不到 ≠ 零成员）：{not_available}"


def test_every_named_roster_is_non_empty_and_matches_scalar(four: dict[str, Any]) -> None:
    """S96 §5-未执法①补齐：每本账的具名名册**非空**，且 `count == len(items) == 标量账`。

    「三口」都在同一次尺输出里互校（名册长度 / 快照自报 count / 账上标量），
    外加快照内嵌的 `scalar` 与 `matches_scalar` 旗标——**期望值一个都不写死**。
    """
    for tag, (snap, scalar) in _named_pairs(four["accounts"]).items():
        assert isinstance(snap, dict), tag
        assert snap.get("available") is True, tag
        items = snap.get("items")
        assert isinstance(items, list), tag
        assert items, f"{tag}: 名册为空＝账具失明（今值侧一条都没数到，不是大家都归位了）"
        assert all(isinstance(x, str) and x for x in items), f"{tag}: 名册里混进空名/非字符串"
        assert snap.get("count") == len(items), f"{tag}: count 与 items 长度不符"
        assert snap.get("count") == scalar, f"{tag}: count 与标量账 {scalar!r} 不符"
        assert snap.get("matches_scalar") is True, f"{tag}: 快照自报 matches_scalar 不是 True"
        assert snap.get("scalar") == scalar, f"{tag}: 快照内嵌 scalar 与账上标量不是同一个数"
    a3: dict[str, Any] = four["accounts"].get("a3_shims_two_ledgers") or {}
    for led in ("prod_ledger", "tests_ledger"):
        book = a3.get(led) or {}
        full = book.get("edges_full")
        assert isinstance(full, dict), led
        assert full.get("available") is True, led
        # 垫片账可为 0（还清是终态），故只断言**逐值对得上**，不断言非空。
        assert full.get("sum_edges") == book.get("current"), led
        assert len(full.get("edges") or []) == full.get("members"), led


def test_a2_unmoved_page_roster_cross_checks_the_scalar(four: dict[str, Any]) -> None:
    """S87/S96 的病灶原件（面B「+10 看得见数看不见名」）：名册 ↔ 标量两口互校。

    期望值不写数：面B 标量账（`a2.current`）与具名册长度（`a2.names.t3_unmoved`）
    出自同一次尺跑的**两个不同读点**，本用例只要求它们逐字相等，并要求名册真能逐枚点名。
    """
    a2: dict[str, Any] = four["accounts"]["a2_page_unplaced"]
    snap = a2["names"]["t3_unmoved"]
    scalar_port = a2["current"]["面B_unmoved"]
    roster_port = snap["count"]
    assert roster_port == scalar_port, f"两口互校失败：名册 {roster_port} vs 标量账 {scalar_port}"
    assert snap["matches_scalar"] is True and snap["scalar"] == scalar_port
    items = snap["items"]
    assert len(items) == roster_port and len(set(items)) == roster_port
    assert all("/" in x or x.endswith(".md") for x in items), "面B 名册不是页路径形态"
    print(f"[S99] 面B 两口互校通过：{roster_port} 枚页名逐枚在册（标量账={scalar_port}）")


def test_scan_surface_floors_are_not_collapsed(four: dict[str, Any]) -> None:
    """反缩面：尺的扫描面（件数/页数/条目数）不得低于在册地板。

    地板拦的是「取数口塌陷/SKIP 被放宽/目录改名」，**不是**合法还债（P-65/R5 口径）；
    真低于地板时先判「尺塌了」还是「地板陈旧」，后者须 owner 重录并留账，不得静默下调。

    ①②③ 仍是手钉的「一半量级」地板（真身在别席写面，见 ④ 上方的边界注）；
    ④ 自 2026-10-12 起改**派生式**：地板＝本门独立 AST 读 `SHIM_ROWS` 源列的枚数，判据取等值
    （少看＝尺塌、多看＝幻影），并带两枚前置——反空转（地板必须为正整数、尺侧 `available` 必须 True）
    与方向锁（派生形状由 `_a4_floor_derivation_shape` 在本文件源码上自证，见注毒组）。
    """
    accounts: dict[str, Any] = four["accounts"]
    a1: dict[str, Any] = accounts["a1_outside_py_dual_ruler"]
    a2: dict[str, Any] = accounts["a2_page_unplaced"]
    a4: dict[str, Any] = accounts["a4_roster_vs_real_debt"]
    checks: tuple[tuple[str, Any, int], ...] = (
        ("① 域外 py（find 尺）", a1["names"]["find_disk"]["count"], MIN_A1_OUTSIDE_PY),
        ("② 面A 受管行", a2["names"]["t3_managed"]["count"], MIN_A2_MANAGED_LINES),
        ("② 面B 未归位页", a2["names"]["t3_unmoved"]["count"], MIN_A2_UNMOVED_PAGES),
    )
    for tag, measured, floor in checks:
        assert isinstance(measured, int), f"{tag}: 今值不是整数（{measured!r}）＝尺子取数失败"
        assert measured >= floor, f"{tag}: 扫描面 {measured} < 地板 {floor}＝要么尺塌了，要么地板陈旧待重录"
        print(f"[S99] 扫描面 {tag}={measured} / 地板 {floor} / 余量 {measured - floor}")
    # ④ 派生式腿（地板来自真身名册，不来自本腿读到的数）
    roster_snapshot = a4["names"]["roster"]
    derived_floor = _a4_roster_derived_floor()
    assert roster_snapshot.get("available") is True, (
        f"④ 在册名册: 尺侧具名快照 available≠True（{roster_snapshot.get('available')!r}）＝取数失败，"
        f"读不到不许当零成员放行")
    errors = _a4_face_vs_floor_errors(roster_snapshot.get("count"), derived_floor)
    assert not errors, "④ 在册名册（派生式）判据不干净：\n" + "\n".join(f"  - {e}" for e in errors)
    print(f"[S99] 扫描面 ④ 在册名册={roster_snapshot.get('count')} / 派生地板(真身名册)={derived_floor} / 差 0（等值）")


# --------------------------------------------------------------------------
# 反向自证（全部内存深拷贝；scripts/ 与真树零写入）
# --------------------------------------------------------------------------
def _poison_clear_items(accounts: dict[str, Any]) -> dict[str, Any]:
    """毒①：清空一本账的 items，但**留着标量**（「名册被抹、数还在」＝旧病复辟）。"""
    acct = copy.deepcopy(accounts)
    acct["a2_page_unplaced"]["names"]["t3_unmoved"]["items"] = []
    return acct


def _poison_scalar_vs_roster(accounts: dict[str, Any]) -> dict[str, Any]:
    """毒②：把标量账与名册枚数错开（名册 170、账上写 171）。"""
    acct = copy.deepcopy(accounts)
    acct["a2_page_unplaced"]["current"]["面B_unmoved"] += 1
    return acct


def _poison_missing_slot(accounts: dict[str, Any]) -> dict[str, Any]:
    """毒③a：删掉一枚具名快照槽（出口退回「只存标量」的旧形态）。"""
    acct = copy.deepcopy(accounts)
    del acct["a4_roster_vs_real_debt"]["names"]["roster"]
    return acct


def _poison_edge_evidence_trimmed(accounts: dict[str, Any]) -> dict[str, Any]:
    """毒③b：垫片边账的 edges 全集被裁、members 与 current 不动（截断冒充全量）。"""
    acct = copy.deepcopy(accounts)
    prod = acct["a3_shims_two_ledgers"]["prod_ledger"]
    if not prod["edges_full"]["edges"]:  # 今值侧 prod 至少 1 条；真为 0 时补一条边再裁
        prod["edges_full"]["edges"] = [["scripts/__phantom_edge__.py", 1]]
        prod["edges_full"]["members"] = 1
        prod["edges_full"]["sum_edges"] = 1
        prod["current"] = 1
    prod["edges_full"]["edges"] = []
    return acct


def test_poison_cleared_roster_with_live_scalar_is_red(four: dict[str, Any]) -> None:
    """毒①：清空 items 留标量 ⇒ 名册腿与尺子体检**两腿都**必须红。"""
    poisoned = _poison_clear_items(four["accounts"])
    assert _roster_errors(poisoned), "清空名册而标量仍在，独立复算腿没抓到＝本腿空跑"
    assert _census_judge_errors(poisoned), "同上，尺子体检腿没抓到"
    assert _gate_errors(poisoned)


def test_poison_scalar_and_roster_mismatch_is_red(four: dict[str, Any]) -> None:
    """毒②：标量与名枚数错开 ⇒ 必红（这正是「净增对不到名」的形态）。"""
    poisoned = _poison_scalar_vs_roster(four["accounts"])
    assert _roster_errors(poisoned), "标量与名册错开没被抓"
    assert _census_judge_errors(poisoned), "标量与名册错开没被尺子体检抓"
    assert _gate_errors(poisoned)


def test_poison_missing_snapshot_slot_is_red(four: dict[str, Any]) -> None:
    """毒③a：具名快照槽整枚消失 ⇒ 必红（「只存标量」的旧形态复辟）。"""
    poisoned = _poison_missing_slot(four["accounts"])
    assert _roster_errors(poisoned) and _gate_errors(poisoned)


def test_poison_trimmed_edge_ledger_is_red(four: dict[str, Any]) -> None:
    """毒③b：垫片边取证被裁而 members/current 不动 ⇒ 必红。"""
    poisoned = _poison_edge_evidence_trimmed(four["accounts"])
    assert _edge_ledger_errors(poisoned), "边全集被裁没被抓"
    assert _gate_errors(poisoned)


def test_gate_keeps_teeth_when_census_judge_always_says_ok(
    four: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """毒④（本门的**存在理由**）：把 `_snapshot_integrity` 改成恒 ok ⇒ 本门仍必红。

    并当场对照：同一份坏数据在「只信尺子体检」的写法下是**绿**的。
    两句话合起来才证明第二条腿不是装饰——这正是 S96 §6 Q2 选 A 而不是选 B 的依据。
    """
    poisoned = _poison_clear_items(four["accounts"])
    monkeypatch.setattr(pc, "_snapshot_integrity", lambda _acct: {"ok": True, "problems": []})
    # 对照：只信体检的写法（若本门只有腿②，这就是它的判定）——坏数据到此为绿
    assert _census_judge_errors(poisoned) == [], "对照失效：被 patch 的体检居然还报病"
    # 本门：独立复算腿仍红 ⇒ 门禁自身造假被抓
    errors = _gate_errors(poisoned)
    assert errors, "体检被改成恒 ok 后本门仍绿＝本门没有牙（独立复算腿失效）"
    assert any("t3_unmoved" in e for e in errors), f"红是红了，但没点名被抹的这本账：{errors}"
    # 反向控制：同一 patch 下**干净树**仍为绿（否则本腿是常量真，红得没有信息量）
    assert _gate_errors(four["accounts"]) == [], "干净树在本门下被误伤＝判据是常量真"


# ==========================================================================
# 基线侧名册 + 反幻影闸（席 S148，承 S96 §6-Q1 / S99 §5-未做①）
# --------------------------------------------------------------------------
# **为什么补这一半**：上面整件门证的是**今值侧**自证——快照 ↔ 标量三口互校（S96 落的名册、
# S99 落的闸）。基线侧（较今值更早的"起点"）此前**只有标量、没有名册、没有闸**：
# `compute_four_accounts()` 每轮从 BASELINE.md 现解析出几个起点整数（`a1.start`／
# `a2.start.面A/面B`／`a3.m_c0c_start`），但没有任何常驻门钉住它们——于是
# **改 BASELINE.md 那一行把起点抬高**（把"退步 +14"洗成"未做 0"），或**删掉那一行**
# （解析成 `None`，delta 整条静默消失），今天都**无人拦**。这正是"基线被悄悄抬"。
#
# **本闸的形态（诚实边界先说死）**：基线侧的"名册"实现为**起点值名册**（account-tag →
# 手写字面量整数），不是逐枚页名名册——因为 BASELINE.md 只存标量、从不存成员名，逐枚基线
# 名册无法从此处复原（真要它，得让 BASELINE.md 改存名册，那是 S96 §6-Q1 归主代理的写面，
# 本席越界不得）。逐枚"净增是哪 N 枚"的差集，本闸给不了；本闸给的是"起点动没动、动得对不对"。
#
# **四条锁**：
# ① 覆盖锁：名册 keyset 必须与"现解析得到的起点 keyset"逐字相等（漏钉＝有账无人管；多钉＝尺改了形）。
# ② 等值锁（本闸命门）：每一枚 `钉住的起点 == 本轮现解析的起点`（零余量，不是 `<=`）。
#    抬起点→名册落后红；删起点→None 红；真·改锚（BASELINE.md 合法重定基线）→必须同批复算改本名册并留证据。
# ③ 反失明锁（AST）：`_BASELINE_ROSTER` 在本文件源码里必须是**手写整数字面量 dict**，
#    且磁盘字面量与内存 dict 逐值相等——拦"把它写成 `= len(现算)` 之类派生式"（跟着被检对象动＝结构性失明）。
# ④ 方向自证：正向接受字面量、反向拒八种派生/负数形态（判据自己有牙，不是空跑）。
#
# **口径红线**（与今值侧同）：单一取数口 = 复用 `four` fixture（本文件已跑的那一次），
# 不起第二条 census、不起 subprocess；反向自证全走**内存深拷贝**，BASELINE.md / scripts/ 与真树零写入。
#
# 复跑：
# .. code-block:: bash
#
#     cd ChatBot/ChatBot && PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 \
#       PYTHONIOENCODING=utf-8 PYTHONPYCACHEPREFIX=$TEMP/s148-pyc \
#       ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest \
#       tests/test_placement_snapshot_integrity_gate.py -p no:cacheprovider --basetemp=$TEMP/s148-bt -q
# --------------------------------------------------------------------------

#: 本门件自身路径（③反失明锁要读自己的源码，不读别人）。
GATE_PATH = Path(__file__).resolve()

#: 基线侧**起点值名册**（account-tag → 起点整数）。
#: 值 = 本席 2026-09-24T06:56Z 现算（**当时值**）：a1.start=99 / a2.start 面A=460 面B=160 /
#: a3.m_c0c_start=23（全部取自 BASELINE.md 冻结的波起点册，"上限与地板只降不升"）。
#: 现值一律以 `scripts/physical_placement_census.py --four-accounts` 现算为准（规则 10）。
#: 改这里的前提：BASELINE.md 那几行被合法重定基线（≠ 悄悄抬）——须同批复算、改本表、并在
#: `SEAT-S148.md` 留尺身份三元组（读数时刻 + 尺身份 + 复跑命令）；只改数不留证据按"未做"记账。
_BASELINE_ROSTER: dict[str, int] = {
    "a1.start.outside_py": 99,
    "a2.start.面A_managed": 460,
    "a2.start.面B_unmoved": 160,
    "a3.start.m_c0c_marker": 23,
}


def _live_baseline_scalars(acct: dict[str, Any]) -> dict[str, Any]:
    """从同一次尺输出里抽出**基线侧起点标量**（keyset 必须与 `_BASELINE_ROSTER` 对齐）。

    这些值全部由 `compute_four_accounts()` 现解析自 BASELINE.md；读不到时尺子诚实降级为 `None`
    （`_s11_start_from_baseline` 命中失败路径），本函数**不**替它折零——`None` 正是要单独拦的形态。
    """
    a1: dict[str, Any] = acct.get("a1_outside_py_dual_ruler") or {}
    a2: dict[str, Any] = acct.get("a2_page_unplaced") or {}
    a3: dict[str, Any] = acct.get("a3_shims_two_ledgers") or {}
    a2_start: dict[str, Any] = a2.get("start") or {}
    return {
        "a1.start.outside_py": a1.get("start"),
        "a2.start.面A_managed": a2_start.get("面A_managed"),
        "a2.start.面B_unmoved": a2_start.get("面B_unmoved"),
        "a3.start.m_c0c_marker": a3.get("m_c0c_start"),
    }


def _baseline_roster_errors(roster: dict[str, int], acct: dict[str, Any]) -> list[str]:
    """①覆盖 + ②等值：名册逐枚对上下轮现解析的起点（活用例与注毒用例吃同一个函数）。"""
    errors: list[str] = []
    live = _live_baseline_scalars(acct)
    missing = sorted(set(live) - set(roster))
    extra = sorted(set(roster) - set(live))
    if missing:
        errors.append(f"这些起点尺子能解析出来、却没进基线名册（漏钉＝基线被改无人管）：{missing}")
    if extra:
        errors.append(f"基线名册钉了尺子解析不出的起点（尺形变了／名册夹带幻影条目）：{extra}")
    for tag, pinned in sorted(roster.items()):
        if tag not in live:
            continue  # 已由 extra 点名，不重复记账
        val = live[tag]
        if val is None:
            errors.append(f"{tag}: 基线起点现解析为 None（BASELINE.md 该行被删/改形 ⇒ delta 静默消失）")
        elif val != pinned:
            errors.append(
                f"{tag}: 名册钉 {pinned} ≠ 本轮现解析起点 {val}"
                f"（差 {val - pinned:+d}）＝基线被改：抬高＝洗退步，须同批复算改名册并留证据")
    return errors


def _module_assignments(tree: ast.AST) -> dict[str, ast.expr]:
    """模块级"单一目标"赋值：名字 → 值节点（``AnnAssign`` 也算）。"""
    out: dict[str, ast.expr] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            out[node.target.id] = node.value
    return out


def _int_literal(node: ast.expr | None) -> int | None:
    """整数字面量判定；`bool` 被排除（`True` 是 `int` 子类，但绝不该当账值）。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return node.value
    return None


def _literal_baseline_roster_from_source(source: str) -> dict[str, int] | None:
    """③反失明判据：`_BASELINE_ROSTER` 必须是"串键 → 整数字面量"的纯字面量 dict。

    含任何派生值（`= len(...)`／`= 现算 - 1`／`= int('3')`／负数 `UnaryOp`）或非串键 ⇒ None。
    """
    assigns = _module_assignments(ast.parse(source))
    node = assigns.get("_BASELINE_ROSTER")
    if not isinstance(node, ast.Dict):
        return None
    out: dict[str, int] = {}
    for key, value in zip(node.keys, node.values, strict=True):
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            return None
        iv = _int_literal(value)
        if iv is None:
            return None
        out[key.value] = iv
    return out


# --------------------------------------------------------------------------
# 正向：真跑尺一次（复用 `four`），基线名册逐枚对得上现解析起点
# --------------------------------------------------------------------------
def test_baseline_roster_matches_live_parsed_starts(four: dict[str, Any]) -> None:
    """①+②：基线侧起点名册逐枚钉住本轮从 BASELINE.md 现解析的起点（S99 §5-未做① 要补的那一半）。"""
    errors = _baseline_roster_errors(_BASELINE_ROSTER, four["accounts"])
    assert not errors, "基线侧名册与现解析起点不符：\n" + "\n".join(f"  - {e}" for e in errors)


def test_baseline_roster_is_hand_written_literals() -> None:
    """③反失明：名册在本文件源码里是手写整数字面量 dict，且磁盘字面量与内存 dict 逐值相等。"""
    source = GATE_PATH.read_text(encoding="utf-8")
    parsed = _literal_baseline_roster_from_source(source)
    assert parsed is not None, "_BASELINE_ROSTER 不是纯字面量 dict＝基线被写成派生式，起点跟着被检对象动"
    assert parsed == _BASELINE_ROSTER, (
        f"磁盘字面量与内存名册不符（导入期被动过手脚？）：source={parsed} in-memory={_BASELINE_ROSTER}")


# --------------------------------------------------------------------------
# 反向自证（内存深拷贝；BASELINE.md / scripts/ 与真树零写入）
# --------------------------------------------------------------------------
def test_poison_raised_baseline_pin_is_red(four: dict[str, Any]) -> None:
    """毒①（简报命门「偷偷把基线常量改大必红」）：把名册里一枚起点钉高 1 而尺子仍解析出旧值 ⇒ 必红。"""
    poisoned = copy.deepcopy(_BASELINE_ROSTER)
    tag = "a2.start.面B_unmoved"
    poisoned[tag] += 1
    errors = _baseline_roster_errors(poisoned, four["accounts"])
    assert errors, "偷偷改大基线常量没被抓＝本闸空跑"
    assert any(tag in e for e in errors), f"红了但没点名被抬的那枚基线：{errors}"
    # 反向控制：同一谓词喂**未中毒**名册应绿（判据不是常量真）
    assert _baseline_roster_errors(_BASELINE_ROSTER, four["accounts"]) == []


def test_poison_raised_live_start_is_red(four: dict[str, Any]) -> None:
    """毒②（另一侧攻击）：把尺子现解析出的起点抬高（模拟 BASELINE.md 那行被悄悄改大）⇒ 与名册对不上必红。

    与毒①对照：一个动"名册"、一个动"起点册"，两腿同一条等值判据都拦得住 ⇒ 起点只能被"名册+尺子同时
    复算改锚"合法移动，单独任一侧动手都当场红。
    """
    acct = copy.deepcopy(four["accounts"])
    acct["a2_page_unplaced"]["start"]["面B_unmoved"] = 174  # 今值 174 被写成新起点＝退步被洗
    errors = _baseline_roster_errors(_BASELINE_ROSTER, acct)
    assert any("面B_unmoved" in e for e in errors), f"抬 BASELINE.md 起点没被抓：{errors}"


def test_poison_dropped_baseline_anchor_is_red(four: dict[str, Any]) -> None:
    """毒③：删掉基线锚（现解析成 None，delta 整条消失）⇒ 必红（不能把"读不到"当"零退步"）。"""
    acct = copy.deepcopy(four["accounts"])
    acct["a2_page_unplaced"]["start"]["面B_unmoved"] = None
    errors = _baseline_roster_errors(_BASELINE_ROSTER, acct)
    assert any("None" in e and "面B_unmoved" in e for e in errors), f"基线锚被删没被抓：{errors}"


def test_poison_unpinned_surface_is_red(four: dict[str, Any]) -> None:
    """毒④：从名册摘掉一枚起点（先"退钉"再"抬尺子那行"就无人管的前半步）⇒ 覆盖锁当场红。"""
    poisoned = copy.deepcopy(_BASELINE_ROSTER)
    del poisoned["a3.start.m_c0c_marker"]
    errors = _baseline_roster_errors(poisoned, four["accounts"])
    assert any("漏钉" in e or "m_c0c_marker" in e for e in errors), f"退钉没被覆盖锁抓到：{errors}"


@pytest.mark.parametrize(
    "source",
    [
        "_BASELINE_ROSTER: dict[str, int] = {\"a\": len(live)}\n",
        "_BASELINE_ROSTER: dict[str, int] = {\"a\": 160 - 1}\n",
        "_BASELINE_ROSTER: dict[str, int] = {\"a\": int(\"3\")}\n",
        "_BASELINE_ROSTER: dict[str, int] = {\"a\": [1, 2][0]}\n",
        "_BASELINE_ROSTER: dict[str, int] = {\"a\": -1}\n",
        "_BASELINE_ROSTER: dict[str, int] = {\"a\": START}\n",
        "_BASELINE_ROSTER: dict[str, int] = {frozenset(\"a\"): 1}\n",
        "_BASELINE_ROSTER = sum([1])\n",
    ],
)
def test_literal_predicate_rejects_derived_forms(source: str) -> None:
    """④判据自证：八种"看起来也是数"的派生/负数/非串键形态必须一律被拒（含整册不是 dict）。"""
    assert _literal_baseline_roster_from_source(source) is None, f"派生形态未被拒＝③反失明锁无牙：{source}"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("_BASELINE_ROSTER: dict[str, int] = {}\n", {}),
        ("_BASELINE_ROSTER: dict[str, int] = {\"a\": 99, \"b\": 460}\n", {"a": 99, "b": 460}),
    ],
)
def test_literal_predicate_accepts_only_literal_dicts(source: str, expected: dict[str, int]) -> None:
    """④正向：只有"串键→整数字面量"的 dict（含空 dict）被接受，与反向用例合成完整牙口证明。"""
    assert _literal_baseline_roster_from_source(source) == expected


# ==========================================================================
# 席 S148-VF（2026-10-08，工单 W-2 同族补口）：四本账 × 两扇门的执法口自证
#   本件已有 module 级 `four` 全量读数（20-60s 一次），故**真树 rc 的折法**在这一件里证：
#   `--fail-on-violations` 的行与退出码必须由「行」现算折出来，不许写死今天的读数；
#   且执法行读的数必须与四本账的附尺**同一支**（本仓的病一律是"总数另算一套"）。
#   注毒只走内存里的合成上限（抬判据、不改源码树、不碰门里的字面量）。
# ==========================================================================

_VF_BAD_ROW = ("OVER_CEILING", "BUCKET_ROW_MISSING", "CEILING_SYMBOL_MISSING")


def test_vf_real_tree_rows_and_rc_fold_the_same_reading(four: dict[str, Any]) -> None:
    """真树自证：rc 恰等于「行」折出来的那一态；每行都带在册词头；上限格与四本账附尺同源同数。"""
    rows = pc.violation_rows(pc.compute(), four, pc.ceiling_literals())
    assert rows, "执法行一本都没交出来＝尺在空跑"
    assert all(r.startswith(("VF|",) + _VF_BAD_ROW) for r in rows), [r for r in rows if not r.startswith(("VF|",) + _VF_BAD_ROW)][:3]
    over = [r for r in rows if r.startswith("OVER_CEILING")]
    missing = [r for r in rows if r.startswith(("BUCKET_ROW_MISSING", "CEILING_SYMBOL_MISSING"))]
    assert pc.enforcement_rc(rows) == (2 if missing else (3 if over else 0)), (over[:2], missing[:2])
    # 单一取数口：执法行里的「G-P2 语义A 未认领」必须等于四本账②的附尺同名列（两处不同源＝假绿）
    adjacent = (four["accounts"].get("a2_page_unplaced") or {}).get("adjacent_ruler_gp2_unclaimed_py")
    if isinstance(adjacent, dict) and "unclaimed" in adjacent:
        row = next(r for r in rows if r.startswith("VF|格名=G-P2 语义A 未认领"))
        assert f"现算={adjacent['unclaimed']}" in row, (row, adjacent)


def test_vf_real_tree_rc_is_not_hardcoded(four: dict[str, Any]) -> None:
    """注毒（纯内存抬判据）：把 G-P2 违规上限压到 0 ⇒ 真树现算必越限、rc 必 3。

    这一条堵的是「执法口照今天的读数写死」：今天的 rc 该是几由**行**决定，同一次调用换个上限
    就必须换个码。若谁把这枚口改成恒 0／恒 3，本条当场红（上限真身在门里，本件一字不改它）。
    """
    lowered = dict(pc.ceiling_literals())
    lowered["G_P2_VIOLATION_CEILING"] = 0
    rows = pc.violation_rows(pc.compute(), four, lowered)
    hit = [r for r in rows if r.startswith("OVER_CEILING")]
    assert len(hit) == 1 and "G-P2 语义A 违规" in hit[0], hit
    assert pc.enforcement_rc(rows) == 3


# ==========================================================================
# 无主归账波（席 OWNER-PLACE 2026-10-11）——两枚常驻判据腿 + 各自注毒
# --------------------------------------------------------------------------
# 背景：G-P2 尺只把「板块树 `feature_impl_paths()`」当认领源；另有两条**正交**的库账在册而尺
#   不折叠——`LIBRARY_TAXONOMY` 的契约地基库成员、`board_shim_ledger.SHIM_ROWS` 的待退役垫片
#   源列。它们认领的 py 在尺账里仍算「无主」。上一席报 118、本席现算 103（对不上按现算记，
#   不圆历史数——规则 10）；本波已把可归板块的 88 枚逐枚归进板块名册，残下 15 枚全属这两条
#   库账（5 枚 SHIM_ROWS 垫片 + 10 枚 L0 契约成员），G-P2 尺结构性看不见库轴，故留账。
# 两腿（各证一件事、缺一不可；判据是纯函数、吃显式入参，注毒全走内存合成、真树零写入）：
#   ① 无主残差棘轮：任何一枚「无主」py **必须**被两条库账之一认领；且无主数 ≤ 两条库账落在扫描
#      面里的成员并集之**现算**势——上限由库账派生、不写会随代码漂的手抄常数（规则 10）。冒出一
#      枚既不在板块名册、又不在任何库账的新 py ⇒ 当场红（这才是「不高于现算读数」的真牙）。
#   ② 幽灵认领门：板块名册每条 `impl_paths` 与每条 `G_P2_EXEMPT` 都必须指向盘上真实存在的文件。
# ==========================================================================
_BOARD_TAXONOMY_PY = REPO_ROOT / "plugins/bot_unified_runtime/domains/core/board_taxonomy.py"
_SHIM_LEDGER_PY = REPO_ROOT / "plugins/bot_unified_runtime/domains/core/board_shim_ledger.py"


def _top_level_literal(source_text: str, name: str) -> Any:
    """AST 现读顶层字面量（`Assign`/`AnnAssign` 两形都认）；缺席即抛，绝不折成空值（fail-closed）。"""
    tree = ast.parse(source_text)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names, value = [t.id for t in node.targets if isinstance(t, ast.Name)], node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names, value = [node.target.id], node.value
        else:
            continue
        if name in names and value is not None:
            return ast.literal_eval(value)
    raise LookupError(f"声明源缺顶层字面量 {name!r}——读不到＝拒算，不按空账放行")


def _library_roster_members(source_text: str) -> set[str]:
    """AST 静态读 `LIBRARY_TAXONOMY` 各库的 `member_paths` 全集（不 import 插件包，同尺纪律）。

    `ReleaseLibNode(...)` 是 Call、整棵不能 `literal_eval`；只逐枚抠 `member_paths=` 关键字的字面
    量元组。`pending_seed` 是另一枚关键字，绝不当成员收进来（那是要搬而未搬的候选，不是在册成员）。
    """
    members: set[str] = set()
    for node in ast.parse(source_text).body:
        if isinstance(node, ast.Assign):
            names, value = [t.id for t in node.targets if isinstance(t, ast.Name)], node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names, value = [node.target.id], node.value
        else:
            continue
        if "LIBRARY_TAXONOMY" not in names or value is None:
            continue
        for call in ast.walk(value):
            if isinstance(call, ast.Call):
                for kw in call.keywords:
                    if kw.arg == "member_paths":
                        members |= {str(p) for p in ast.literal_eval(kw.value)}
    return members


def _shim_row_sources(source_text: str) -> set[str]:
    """AST 静态读 `SHIM_ROWS` 的**源列**（每行 `(旧顶层路径, 真身, n)` 的头一枚＝包根那头的垫片）。"""
    return {str(row[0]) for row in _top_level_literal(source_text, "SHIM_ROWS")}


def _unexplained_orphans(ownerless: set[str], library: set[str], shims: set[str]) -> list[str]:
    """判据①内核：列出既不在两条库账里的无主 py（注毒与真树共口）。"""
    return sorted(p for p in ownerless if p not in library and p not in shims)


def _ghost_claimed(
    board_rows: list[tuple[str, tuple[str, ...]]],
    exempt_paths: list[str],
) -> list[str]:
    """判据②内核：板块名册 impl_paths 与 G_P2_EXEMPT 里指向盘上无物的，逐条点名（注毒与真树共口）。"""
    ghosts: list[str] = []
    for fid, paths in board_rows:
        ghosts.extend(f"impl[{fid}]::{p}" for p in paths if not (REPO_ROOT / str(p)).exists())
    ghosts.extend(f"exempt::{p}" for p in exempt_paths if not (REPO_ROOT / str(p)).exists())
    return sorted(set(ghosts))


def test_ownerless_residual_is_explained_by_the_two_library_axes() -> None:
    """腿①（真树）：G-P2 无主残差每一枚都必须落在 LIBRARY_TAXONOMY 成员或 SHIM_ROWS 源列之内。"""
    ownerless = set(pc.compute()["a_violation_list"])
    library = _library_roster_members(_BOARD_TAXONOMY_PY.read_text(encoding="utf-8"))
    shims = _shim_row_sources(_SHIM_LEDGER_PY.read_text(encoding="utf-8"))
    unexplained = _unexplained_orphans(ownerless, library, shims)
    assert not unexplained, (
        f"无主残差冒出 {len(unexplained)} 枚既不在板块名册、又不在两条库账的孤儿 py＝归账波失守、"
        f"无主数在涨（修法：给它在板块树补一条 impl_paths 认领，或落进对应库账，不是把它塞豁免）：{unexplained}"
    )
    # 现算派生上限（规则 10：不写手抄常数）——无主数不得高出两条库账在扫描面里能解释的容量。
    derived_ceiling = len((library | shims) & set(pc.py_universe()))
    assert len(ownerless) <= derived_ceiling, (
        f"无主 {len(ownerless)} > 库账派生上限 {derived_ceiling}（该上限由 LIBRARY_TAXONOMY∪SHIM_ROWS"
        f" 与 py 扫描面交集现算，非手抄；越界＝无主数高于现算读数）"
    )


def test_no_ghost_claim_or_exemption_in_placement_roster() -> None:
    """腿②（真树）：板块名册每条认领与每条豁免都必须指向盘上真实文件（幽灵认领＝假认领）。"""
    ghosts = _ghost_claimed(
        pc.feature_impl_paths(),
        [p for p, _reason in pc.load_placement()["G_P2_EXEMPT"]],
    )
    assert not ghosts, (
        f"物理归位名册/豁免里 {len(ghosts)} 条指向盘上不存在的文件（幽灵认领，改认领名册、不在本门放宽）：{ghosts}"
    )


# ------------------------------------------- 两腿各一发注毒（纯内存、真声明源一字节未动）
def test_poison_planted_orphan_off_both_ledgers_is_red() -> None:
    """注毒①：现役残差本已全在册（前提自证），再塞一枚「哪条账都不沾」的孤儿 py ⇒ 判据必抓到。"""
    ownerless = set(pc.compute()["a_violation_list"])
    library = _library_roster_members(_BOARD_TAXONOMY_PY.read_text(encoding="utf-8"))
    shims = _shim_row_sources(_SHIM_LEDGER_PY.read_text(encoding="utf-8"))
    assert _unexplained_orphans(ownerless, library, shims) == [], "真树残差本不该有账外孤儿（前提塌了，注毒失去意义）"
    planted = "plugins/bot_unified_runtime/domains/core/__planted_orphan_off_ledgers__.py"
    hit = _unexplained_orphans(ownerless | {planted}, library, shims)
    assert hit == [planted], f"注入的账外孤儿没被判据①抓到（该腿视为失明）：{hit}"


def test_poison_ghost_claim_points_at_missing_file_is_red() -> None:
    """注毒②：往某 fid 的认领里追加一枚盘上无物的路径 ⇒ 判据②必点名；现役真名册不误伤。"""
    board = pc.feature_impl_paths()
    live = _ghost_claimed(board, [p for p, _r in pc.load_placement()["G_P2_EXEMPT"]])
    assert live == [], f"现役真名册本不该有幽灵认领（前提塌了）：{live}"
    fid, paths = board[0]
    poisoned_row = (fid, (*paths, "plugins/bot_unified_runtime/domains/__definitely_absent_ghost__.py"))
    hit = _ghost_claimed([poisoned_row] + board[1:], [])
    assert any("__definitely_absent_ghost__" in g for g in hit), f"幽灵认领没被判据②抓到（该腿视为失明）：{hit[:4]}"



# ==========================================================================
# 席 SEAT-PLACE-FLOOR（2026-10-12）：④ 在册名册地板改**派生式**后的两枚前置自证
#   来龙去脉见 ④ 地板注释（真仓/HEAD 副本两轴都逐字读到「扫描面 14 < 地板 15」⇒ 定性＝地板陈旧、
#   非尺塌、非他席在飞）。本格只动本件与取数尺；`board_shim_ledger.py` **一字节未写**（注毒全走
#   内存合成源串与本文件源码的形状闸；真 FAILED 的取证在 %TEMP% 副本里做，见本席报告）。
# ==========================================================================

#: 注毒用的合成名册行（路径在盘上不存在也无妨：派生口只读字面量、不查盘）。
_A4_POISON_ROW = ("plugins/bot_unified_runtime/__seat_poison_row__.py",
                  "plugins/bot_unified_runtime/domains/core/__seat_poison_row__.py", 0)


def _a4_ledger_source_with_rows(rows: tuple[Any, ...]) -> str:
    """把行集渲染成**只喂派生口**的合成声明源（真树零写入；同尺纪律：纯字面量元组）。"""
    return "SHIM_ROWS: tuple = " + repr(tuple(tuple(row) for row in rows)) + "\n"


def _a4_live_ledger_rows() -> tuple[Any, ...]:
    """现读真身名册行集（活例与注毒共口；真树只读）。"""
    return _a4_roster_source_rows(_A4_ROSTER_LEDGER_PY.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 正向：两读点互校
def test_a4_derived_floor_cross_checks_the_rulers_roster_reading(four: dict[str, Any]) -> None:
    """派生式腿的正向半边：本门独立读的真身枚数 ↔ 尺的 ④ 名册读数（两个取数口，同一个数）。"""
    snap: dict[str, Any] = four["accounts"]["a4_roster_vs_real_debt"]["names"]["roster"]
    derived = _a4_roster_derived_floor()
    assert derived > 0, f"派生地板={derived}＝取数口读到空（反空转前置①）"
    assert snap["available"] is True, "尺侧具名快照 available≠True＝读不到，不许当零成员放行"
    assert _a4_face_vs_floor_errors(snap["count"], derived) == [], (snap["count"], derived)
    # 第三次现读必须与前两次同数（派生口非随机、不被上一轮污染）
    assert _a4_roster_derived_floor() == derived


def test_a4_floor_derivation_shape_is_len_of_a_local_collection() -> None:
    """前置②（方向锁）：本文件源码里 ④ 地板的派生形状恰是 `len(本函数局部集合)`，无违规项。"""
    verdict = _a4_floor_derivation_shape(GATE_PATH.read_text(encoding="utf-8"))
    assert verdict["found"] is True, verdict
    assert verdict["bad"] == [], f"④ 地板的派生形状不再是纯 `len(真身行集)`（可能已跟着尺读数自随）：{verdict}"


# ---------------------------------------------------------------- 注毒①：面缩必红、地板不跟降
def test_poison_collapsed_roster_reading_is_red_and_floor_does_not_chase(four: dict[str, Any]) -> None:
    """注毒①：名册读数摘掉一枚（真身不动）⇒ 判据必如实报面缩，**地板不许跟着降**（不许自随空跑）。"""
    live_floor = _a4_roster_derived_floor()
    errors = _a4_face_vs_floor_errors(live_floor - 1, live_floor)
    assert errors, "缩一枚被判据放过＝派生式跟着读数降地板，本门成自随空跑"
    assert any(f"{live_floor - 1}" in e and "取数口塌陷" in e for e in errors), errors
    # 地板不跟读数动：同一次调用里再读两遍，仍是真身那个数
    assert _a4_roster_derived_floor() == live_floor and _a4_roster_derived_floor() == live_floor
    # 反证（派生确实随真身动，不是抄死）：真身侧摘一枚 ⇒ 地板如实降 1
    assert _a4_roster_derived_floor(_a4_ledger_source_with_rows(_a4_live_ledger_rows()[:-1])) == live_floor - 1
    # 深拷贝腿：真动 accounts 里的具名快照（items+count 一起缩），判据口照红
    acct: dict[str, Any] = copy.deepcopy(four["accounts"])
    snap = acct["a4_roster_vs_real_debt"]["names"]["roster"]
    snap["items"] = snap["items"][:-1]
    snap["count"] = len(snap["items"])
    assert _a4_face_vs_floor_errors(snap["count"], _a4_roster_derived_floor()), "深拷贝名册缩一枚没被抓"


# ---------------------------------------------------------------- 注毒②：补回一枚必跟着涨
def test_poison_added_roster_entry_raises_the_derived_floor(four: dict[str, Any]) -> None:
    """注毒②：往真身名册补一枚 ⇒ 派生地板**必须跟着涨** 1（证它是派生、不是抄数）。"""
    live_floor = _a4_roster_derived_floor()
    grown = _a4_ledger_source_with_rows(_a4_live_ledger_rows() + (_A4_POISON_ROW,))
    assert _a4_roster_derived_floor(grown) == live_floor + 1, "补一枚地板没涨＝它其实被抄死了"
    # 真身涨了而尺读数没涨＝少看一枚 ⇒ 判据照样红（不许用涨上来的地板去配旧读数了事）
    errors = _a4_face_vs_floor_errors(live_floor, live_floor + 1)
    assert errors and any("取数口塌陷" in e for e in errors), errors


def test_poison_ghost_roster_entry_above_the_ledger_is_red(four: dict[str, Any]) -> None:
    """方向锁的另一侧：尺读数比真身**多**一枚（幻影/已退役未清行）⇒ 必红（旧 `>=` 写法会放过）。"""
    live_floor = _a4_roster_derived_floor()
    errors = _a4_face_vs_floor_errors(live_floor + 1, live_floor)
    assert errors and any("幻影" in e for e in errors), errors
    assert _a4_face_vs_floor_errors(live_floor, live_floor) == [], "同一份数被判据误伤＝判据常量真"


# ---------------------------------------------------------------- 前置①：反空转（读到空＝当场红，不是 0 地板）
@pytest.mark.parametrize(
    "source",
    [
        "SHIM_ROWS: tuple = ()\n",                                              # 清成空账
        "SHIM_ROWS: tuple\n",                                                   # 只声明不赋值
        'SHIM_ROWS = tuple([("a", "b", 1)])\n',                                 # 非纯字面量（调用拼接）
        'OTHER_ROWS = (("a", "b", 1),)\n',                                      # 声明失踪
        'SHIM_ROWS = (("a", "b"),)\n',                                          # 行形状不合契约
        'SHIM_ROWS = (("a", "b", 1),)\nSHIM_ROWS = (("c", "d", 2),)\n',          # 声明两处
        "",                                                                     # 空源
    ],
)
def test_poison_blind_ledger_sources_raise_instead_of_zero_floor(source: str) -> None:
    """真身读不出行/读出零行 ⇒ 派生口一律抛（拒算≠放行）；判据口对 `floor=0` 也必红。"""
    with pytest.raises((AssertionError, SyntaxError)):
        _a4_roster_derived_floor(source)
    assert _a4_face_vs_floor_errors(0, 0), "0 地板 0 读数被判据放过＝反空转前置①无牙"


@pytest.mark.parametrize(
    ("source", "accepted"),
    [
        ("def _a4_roster_derived_floor(source_text=None):\n    return measured\n", False),
        ("def _a4_roster_derived_floor(source_text=None):\n    paths = set()\n    return len(paths) - 1\n", False),
        ("def _a4_roster_derived_floor(source_text=None):\n    paths = set()\n    return max(len(paths), 15)\n", False),
        ("def _a4_roster_derived_floor(source_text=None):\n    return 14\n", False),
        ("def _a4_roster_derived_floor(source_text=None, measured=0):\n    paths = set()\n    return len(paths)\n", False),
        ("def _a4_roster_derived_floor(source_text=None):\n    n = 1\n    return len(n)\n", False),
        ("def _a4_roster_derived_floor(source_text=None):\n    return len(paths)\n", False),
        ("def _a4_roster_derived_floor(source_text=None):\n    paths = {p for p in ()}\n    return len(paths)\n", True),
    ],
)
def test_a4_shape_lock_accepts_only_pure_derivation(source: str, accepted: bool) -> None:
    """方向锁自证：七种"也是数"的自随/抄死形态被拒，唯一纯派生形态被接受（判据自己有牙）。"""
    verdict = _a4_floor_derivation_shape(source)
    assert (verdict["bad"] == []) is accepted, (source, verdict)
