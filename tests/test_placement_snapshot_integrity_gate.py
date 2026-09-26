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
- 唯一的字面量是扫描面**地板**（只拦「尺子塌了/扫描面被顶穿」，不阻止合法还债——
  P-65/R5 口径）。地板刻意取实测的一半量级。
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
# 扫描面地板（手写字面量，只拦塌陷，不拦合法下降）
# 起点值 = 本席 2026-09-24 现算（**当时值**）；现值一律以
# `../ChatBot_Runtime/venv/Scripts/python.exe scripts/physical_placement_census.py --four-accounts-human`
# 现算为准（AGENTS.md 规则 10：叙述与本注释都不充当今值）。
# --------------------------------------------------------------------------
#: ① 域外 py（find 尺）成员数。起点值（当时）100。
MIN_A1_OUTSIDE_PY = 50
#: ② 面A 受管行数。起点值（当时）460。
MIN_A2_MANAGED_LINES = 200
#: ② 面B 未归位页数。起点值（当时）170。
MIN_A2_UNMOVED_PAGES = 80
#: ④ 在册名册条目数。起点值（当时）47。
MIN_A4_ROSTER_ENTRIES = 20

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
    """
    accounts: dict[str, Any] = four["accounts"]
    a1: dict[str, Any] = accounts["a1_outside_py_dual_ruler"]
    a2: dict[str, Any] = accounts["a2_page_unplaced"]
    a4: dict[str, Any] = accounts["a4_roster_vs_real_debt"]
    checks: tuple[tuple[str, Any, int], ...] = (
        ("① 域外 py（find 尺）", a1["names"]["find_disk"]["count"], MIN_A1_OUTSIDE_PY),
        ("② 面A 受管行", a2["names"]["t3_managed"]["count"], MIN_A2_MANAGED_LINES),
        ("② 面B 未归位页", a2["names"]["t3_unmoved"]["count"], MIN_A2_UNMOVED_PAGES),
        ("④ 在册名册", a4["names"]["roster"]["count"], MIN_A4_ROSTER_ENTRIES),
    )
    for tag, measured, floor in checks:
        assert isinstance(measured, int), f"{tag}: 今值不是整数（{measured!r}）＝尺子取数失败"
        assert measured >= floor, f"{tag}: 扫描面 {measured} < 地板 {floor}＝要么尺塌了，要么地板陈旧待重录"
        print(f"[S99] 扫描面 {tag}={measured} / 地板 {floor} / 余量 {measured - floor}")


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
