"""垫片「待退役」第二本账的常驻门（解 P-16 A 案 · C3 三态的执法腿 · P-22 耦合锁）。

本门只管一件事：把 `scripts/shim_retirement_census.py`（唯一取数口）现算出的三态
（已归类 / 待搬迁 / 待退役垫片）与 `domains/core/board_shim_ledger.py` 那本账对死，
并锁住方向。**绝不含**改豁免账（`G_P2_EXEMPT` / `G_P2_EXEMPT_CEILING` 一字不碰，那是 S13/S33 面）——
本席只把它的**条数**读进同一门记账，防「拿豁免洗三态账」。

## 方向锁的形状（P-22 裁定 A · S52）
S34 首版把「待退役」「待搬迁」**各自**只准降 ⇒ S33 给域外件补 `impl_paths` 认领这个**唯一正当动作**
会把枚数并入待搬迁而顶红门 ⇒ 门在奖励不作为。现锁**加数不锁加项**：
- 硬锁① `待退役 + 待搬迁 <= UNLANDED_SUM_BASELINE`（域外未落地总量，单调下降）
- 硬锁② `三态之和 <= OUTSIDE_BASELINE`（域外全量，单调下降）
- 单态参照：某态高于参照点的部分，必须由另一态低于参照点的部分**等额或更多**抵掉
  —— 该条由硬锁①推出（见 `test_coupling_is_a_theorem_not_a_second_veto`），不是另开的松门。
只降账**没有变成可升账**：两枚和锁单调下降、四枚基线经 `clamped_baselines` 连 `--write-ledger` 都抬不动。

反向自测逐把注毒证明它真的会红，全在内存/合成数据里跑，绝不往源码树写：
- ①漏记一枚现算垫片⇒红 ②非垫片登记成垫片⇒红 ③账上真身不存在⇒红 ④引用方数超上限⇒红
- ⑤只升一态·另一态不降⇒红 ⑥一态升·另一态等额降⇒绿且和不变 ⑦和上升⇒红（两态和与三态和各一发）
- ⑧手抄一个「也存在但不对」的真身指针⇒红（S34 的 ③ 查存在性，洗不掉这一形）
- ⑨`--write-ledger` 想把基线抬回去⇒钳不下来⇒红（生成器不是后门）
- ⑩账「读不到」（只声明不赋值 / 字面量 None / 非字面量调用）⇒ 拒读判红，不许当成空账放行（S60 补 P-S52-1）

外加结构锁（对齐 `test_legacy_shim_import_ratchet.py` 的立门哲学）：基线是手写字面量、
和锁不比单态参照松、扫描面不许塌陷、`--report` 与门同源。
"""

from __future__ import annotations

import ast
import copy
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

import shim_retirement_census as s34

LEDGER = s34.LEDGER_PY

#: 扫描面塌陷地板（手写字面量）：低于此说明有人把判据/记号面改窄了，"0 问题"是假绿。
#: 2026-09-24 S188 现算跟随（物理归位第5项账跟随）：原 150/100 是域外~190、垫片~138 时代的地板；
#: 之后归位波把件搬进 `domains/`、退役波摘垫片，域外真实降到 100、待退役真实降到 47——**扫描没塌**
#: （本席实测 `--report` 域外 100、三态铺满），是地板 stale 过高误报进展为塌陷。现按现算写入。
#: 复跑取值：`python scripts/shim_retirement_census.py --report`（「域外 py」行 + 「三态: … 待退役」段）。
#: 铁律：此地板只准随归位继续下降，**永不因某波把件挪回域外而抬**（那是要红、不是搬账）。
MIN_OUTSIDE_FLOOR = 99  # 2026-09-24T10:4xZ 现算 99（原 100）：裁定 1.A 把 `control_plane/api/tts.py`
#   归位进 `domains/creation/tts/routes.py`（域外真少一枚，非扫描面塌陷）。复跑：
#   `python scripts/physical_placement_census.py --four-accounts` 读 accounts.a1_outside_py_dual_ruler.current
#   地板方向＝只准降不升（降须带这种"归位/迁走"证据行）；旧件已按规程备份 %TEMP%/tts-relocate-backup-20260924-184240。
MIN_SHIM_FLOOR = 47

#: 与三态之和同门记账的豁免上限 = `BASELINE.md` 起点值（只准降）。本席**只读**该账，不改它一个字。
EXEMPT_START_CEILING = 29

#: 四枚基线名（结构锁用）—— 与算口 `LEDGER_BASELINE_NAMES` 同源核对，防两边各写一套。
BASELINE_NAMES: tuple[str, ...] = (
    "SHIM_RETIRE_BASELINE",
    "RELOCATE_BASELINE",
    "UNLANDED_SUM_BASELINE",
    "OUTSIDE_BASELINE",
)


# --------------------------------------------------------------------------
# 正向：账与现算必须严丝合缝（本门的常驻断言）
# --------------------------------------------------------------------------
def test_ledger_matches_live_detection() -> None:
    """五把锁同一发：账上登记 == 现算检测，真身都在且指针未手抄、引用数都不超上限。"""
    detected = s34.detect_shims()
    rows = s34.load_ledger_rows()
    probs = s34.cross_check(rows, detected)
    offenders = {k: v for k, v in probs.items() if v}
    assert not offenders, f"垫片账与现算不一致：{offenders}"


def test_states_only_decrease_or_move_in_coupled_balance() -> None:
    """P-22 取代 S34 的 `test_two_states_only_decrease`（各自只降 ⇒ 惩罚正当认领）。

    锁法：和单调降（硬）＋单态上升必被另一态下降抵掉（由和锁推出的归因）。
    **不是可升账** —— `relocate` 想涨，唯一路子是 `retire` 等额掉，即域外未落地总量净减。
    """
    st = s34.three_states()
    bl = s34.load_ledger_baselines()
    v = s34.coupled_ratchet(st["counts"], bl, outside=st["outside"])
    assert v["unlanded_within"], (
        f"域外未落地之和回升 {v['unlanded_now']} > 硬锁 {v['unlanded_baseline']}＝搬迁与退役的进展被倒退抵掉"
    )
    assert v["outside_within"], (
        f"三态之和（域外全量）回升 {v['outside_now']} > 硬锁 {v['outside_baseline']}＝域外长了新文件"
    )
    assert v["retire_rise_covered"], (
        f"待退役上升 {v['retire_rise']} 枚而待搬迁只降 {v['relocate_fall']} 枚＝没被等额抵掉（长新垫片副本）"
    )
    assert v["relocate_rise_covered"], (
        f"待搬迁上升 {v['relocate_rise']} 枚而待退役只降 {v['retire_fall']} 枚＝正当认领之外的增长"
    )


def test_three_states_are_a_partition_of_outside() -> None:
    """三态互斥且恰好铺满域外（防某态被偷偷并进另一态把账做没）。"""
    st = s34.three_states()
    n = st["counts"]
    assert n["retire_shims"] + n["relocate"] + n["classified"] == st["outside"], (
        "三态之和 != 域外总数＝有文件被漏进某一态或被重复计"
    )
    retire, relocate, classified = set(st["retire_shims"]), set(st["relocate"]), set(st["classified"])
    assert not (retire & relocate) and not (retire & classified) and not (relocate & classified), "三态有交集＝归属含糊"


def test_three_state_sum_and_exempt_account_are_locked() -> None:
    """P-22 要求的「三态之和与豁免 29 写进同一门」：全量硬锁 + 豁免条数只准降 + 与算口同源。"""
    st = s34.three_states()
    bl = s34.load_ledger_baselines()
    assert st["outside"] <= bl["OUTSIDE_BASELINE"], (
        f"域外全量 {st['outside']} > 硬锁 {bl['OUTSIDE_BASELINE']}（起点 193）＝域外在长，不靠改门放行"
    )
    assert bl["UNLANDED_SUM_BASELINE"] <= bl["OUTSIDE_BASELINE"], "两态和硬锁高于三态和硬锁＝有态被排除在锁外"
    count = s34.exemption_count()
    assert count <= EXEMPT_START_CEILING, (
        f"G-P2 豁免 {count} 条 > 起点上限 {EXEMPT_START_CEILING}＝拿豁免把三态账搬家（本席只记账不代改）"
    )
    assert s34.compute()["exemption"]["count"] == count, "豁免条数另算一套＝同源锁破"


def test_scan_scope_did_not_collapse() -> None:
    """非空转守卫：域外面与垫片命中都得真实存在，否则"0 问题"只是没在看。"""
    st = s34.three_states()
    assert st["outside"] >= MIN_OUTSIDE_FLOOR, f"域外只扫到 {st['outside']}（地板 {MIN_OUTSIDE_FLOOR}）＝扫描面塌陷"
    assert st["counts"]["retire_shims"] >= MIN_SHIM_FLOOR, (
        f"只认出 {st['counts']['retire_shims']} 枚垫片（地板 {MIN_SHIM_FLOOR}）＝记号面/判据被改窄"
    )
    assert s34.load_ledger_rows(), "账是空的但上面还认得出垫片＝取数口与账不一致"


def test_baselines_are_hand_written_literals() -> None:
    """结构锁：四枚基线必须是字面整数，不许写成 len(...)/现算派生（派生上限＝门永远绿）。"""
    assigned: dict[str, ast.expr | None] = {}
    for node in ast.walk(ast.parse(LEDGER.read_text(encoding="utf-8"))):
        targets: list[ast.expr] = []
        value: ast.expr | None = None  # 逐支各自取 `.value`：`node` 是 `ast.AST`，泛读它 mypy 不认（S60 清账）
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        for target in targets:
            if isinstance(target, ast.Name):
                assigned[target.id] = value
    for name in BASELINE_NAMES:
        value = assigned.get(name)
        assert isinstance(value, ast.Constant) and isinstance(value.value, int), (
            f"{name} 被改成派生表达式＝基线跟着被检对象一起动，方向锁失效"
        )
    assert set(BASELINE_NAMES) == set(s34.LEDGER_BASELINE_NAMES), "门与算口各写一套基线名＝锁的对象不是同一批"
    rows = assigned.get("SHIM_ROWS")
    assert isinstance(rows, ast.Tuple), "SHIM_ROWS 必须是纯字面量元组（禁计算/调用＝禁手抄派生）"


def test_sum_baseline_is_no_looser_than_the_state_references() -> None:
    """结构锁：和锁必须 ≤ 两枚单态参照之和 —— 否则「单态上升必被抵掉」不再是定理，而是一道更松的门。"""
    bl = s34.load_ledger_baselines()
    assert bl["UNLANDED_SUM_BASELINE"] <= bl["SHIM_RETIRE_BASELINE"] + bl["RELOCATE_BASELINE"], (
        f"和锁 {bl['UNLANDED_SUM_BASELINE']} > 参照点之和 "
        f"{bl['SHIM_RETIRE_BASELINE']}+{bl['RELOCATE_BASELINE']}＝耦合失去可证性，和锁被抬成松门"
    )


def test_coupling_is_a_theorem_not_a_second_veto() -> None:
    """穷举一张网格：和锁成立 ⇒ 两态耦合条件必成立（证明耦合是算术推论，不是另开的判据）。"""
    bl = {
        "SHIM_RETIRE_BASELINE": 138,
        "RELOCATE_BASELINE": 46,
        "UNLANDED_SUM_BASELINE": 184,
        "OUTSIDE_BASELINE": 190,
    }
    checked = 0
    for retire in range(130, 150):
        for relocate in range(38, 58):
            v = s34.coupled_ratchet({"retire_shims": retire, "relocate": relocate}, bl, outside=190)
            checked += 1
            if v["unlanded_within"]:
                assert v["retire_rise_covered"] and v["relocate_rise_covered"], (retire, relocate, v)
    assert checked == 20 * 20, "网格没跑满＝这枚自证空转"


# --------------------------------------------------------------------------
# 反向自测：账与现算对死（①–④，S34 原立；⑤–⑨ 本席补）
# 全部在内存/合成数据上注毒，绝不写源码树。
# --------------------------------------------------------------------------
def _live_rows_and_detected() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    return s34.load_ledger_rows(), s34.detect_shims()


def test_poison_1_missing_registration_is_caught() -> None:
    """①：从账里删掉一枚真垫片 ⇒ 现算检测到它却未登记 ⇒ 必红。"""
    rows, detected = _live_rows_and_detected()
    assert detected, "现算没检测到任何垫片＝自测无意义（取数口坏了）"
    victim = min(detected)
    mutated = [r for r in copy.deepcopy(rows) if r["path"] != victim]
    assert len(mutated) < len(rows), "注毒没删掉任何行（victim 不在账里）＝假自测"
    probs = s34.cross_check(mutated, detected, refs_fn=lambda _p: 0)
    assert victim in probs["missing_registration"], f"漏记 {victim} 没被判出＝①腿空转"


def test_poison_2_nonshim_registered_is_caught() -> None:
    """②：把一个存在但**不是垫片**的真身文件登记成垫片 ⇒ 必红。"""
    rows, detected = _live_rows_and_detected()
    relocate = s34.three_states()["relocate"]
    victim = next((r for r in relocate if (REPO / r).exists()), None)
    assert victim is not None, "找不到一个可注入的非垫片真身＝②腿无从注毒"
    mutated = copy.deepcopy(rows) + [{"path": victim, "canonical": victim, "refs": 9999}]
    probs = s34.cross_check(mutated, detected, refs_fn=lambda _p: 0)
    assert victim in probs["not_a_shim"], f"非垫片 {victim} 登记成垫片没被判出＝②腿空转"


def test_poison_3_missing_canonical_is_caught() -> None:
    """③：把某垫片的真身指针改成盘上不存在的文件 ⇒ 必红。"""
    rows, detected = _live_rows_and_detected()
    assert rows, "账为空＝③无从注毒"
    mutated = copy.deepcopy(rows)
    mutated[0]["canonical"] = "plugins/bot_unified_runtime/domains/__does_not_exist__/nope.py"
    probs = s34.cross_check(mutated, detected, refs_fn=lambda _p: 0)
    assert mutated[0]["path"] in probs["canonical_missing"], "真身路径不存在没被判出＝③腿空转"


def test_poison_4_refs_over_ceiling_is_caught() -> None:
    """④：把某垫片的引用上限调到比现算真值还低（模拟"新增了一条旧写法"）⇒ 必红。"""
    rows, detected = _live_rows_and_detected()
    with_refs = [r for r in rows if s34.computed_refs(r["path"]) > 0]
    assert with_refs, "现算所有垫片引用数都是 0＝④腿没样本可注毒（取数口可能坏了）"
    target = with_refs[0]
    truth = s34.computed_refs(target["path"])

    def refs_fn(path: str) -> int:
        return truth if path == target["path"] else 0

    mutated = copy.deepcopy(rows)
    for r in mutated:
        if r["path"] == target["path"]:
            r["refs"] = truth - 1
    probs = s34.cross_check(mutated, detected, refs_fn=refs_fn)
    assert target["path"] in probs["refs_over_ceiling"], (
        f"现算 {truth} > 上限 {truth - 1} 没被判出＝④腿空转"
    )


def test_poison_8_handcopied_canonical_is_caught() -> None:
    """⑧（＝任务书 ④「手抄账与现算不符」）：把真身指针手抄成**另一枚也存在**的真身 ⇒ 必红。

    关键自证：同一发必须"③ 查不出来、⑤ 查得出来"，否则这枚新腿是空转的装饰。
    """
    rows, detected = _live_rows_and_detected()
    live = [r for r in rows if r["path"] in detected]
    victim = next(
        (r for r in live if any(o["canonical"] != r["canonical"] and (REPO / o["canonical"]).exists() for o in live)),
        None,
    )
    assert victim is not None, "账上找不出两枚真身不同的垫片＝⑧腿无从注毒"
    other = next(o["canonical"] for o in live if o["canonical"] != victim["canonical"])
    mutated = copy.deepcopy(rows)
    for r in mutated:
        if r["path"] == victim["path"]:
            r["canonical"] = other
    probs = s34.cross_check(mutated, detected, refs_fn=lambda _p: 0)
    assert victim["path"] not in probs["canonical_missing"], "手抄指针指向的文件其实不存在＝这发没在考验⑤，换样本"
    assert victim["path"] in probs["canonical_mismatch"], (
        f"手抄真身 {victim['path']} → {other}（存在但不是派生真身）没被判出＝⑤腿空转"
    )


# --------------------------------------------------------------------------
# 反向自测：方向锁本体（⑤–⑦，纯合成数字，不碰树也不碰账）
# --------------------------------------------------------------------------
_BL = {
    "SHIM_RETIRE_BASELINE": 138,
    "RELOCATE_BASELINE": 46,
    "UNLANDED_SUM_BASELINE": 184,
    "OUTSIDE_BASELINE": 190,
}


def test_poison_5_uncoupled_single_state_rise_is_red() -> None:
    """任务书①：只升一态、另一态不降 ⇒ 红（既不满足和锁，也没有抵偿）。"""
    v = s34.coupled_ratchet({"retire_shims": 138, "relocate": 47}, _BL, outside=190)
    assert v["relocate_rise"] == 1 and v["retire_fall"] == 0, "注毒没造出「只升一态」的合成场景＝假自测"
    assert not v["relocate_rise_covered"], "待搬迁涨 1 而待退役没降，居然被判放行＝耦合锁空转"
    assert not v["unlanded_within"] and not v["ok"], f"和升 185 > 184 却没红＝锁没锁在加数上：{v}"


def test_poison_6_equal_exchange_is_green_and_sum_unchanged() -> None:
    """任务书②：一态升、另一态等额降 ⇒ 绿且和不变（这正是 S33 正当认领被 S34 旧门误杀的那一发）。"""
    v = s34.coupled_ratchet({"retire_shims": 137, "relocate": 47}, _BL, outside=190)
    assert v["unlanded_now"] == v["unlanded_baseline"] == 184, f"等额换态后和应不变：{v}"
    assert v["ok"], f"正当耦合进展被误判红＝P-22 没修掉：{v}"
    # 反向自证的对称面：旧判据（单态各自只准降）在这一发上是红的 —— 记在册上，防日后偷偷退回旧锁。
    assert v["relocate_now"] > v["relocate_baseline"], "样本不再是「旧判据会红」的情形＝这发证明不了什么"


def test_poison_7_sum_rise_is_red() -> None:
    """任务书③：和上升 ⇒ 红 —— 两态和与三态和各注一发毒。"""
    v_two = s34.coupled_ratchet({"retire_shims": 140, "relocate": 46}, _BL, outside=190)
    assert not v_two["unlanded_within"] and not v_two["ok"], f"两态和 186 > 184 没判红＝③腿（两态）空转：{v_two}"
    v_three = s34.coupled_ratchet({"retire_shims": 138, "relocate": 46}, _BL, outside=191)
    assert v_three["unlanded_within"], "注毒样本选错（两态和也升了）＝没 isolate 出三态和这一发"
    assert not v_three["outside_within"] and not v_three["ok"], (
        f"域外全量 191 > 190 没判红＝三态之和那把锁空转：{v_three}"
    )


def test_poison_9_write_ledger_cannot_raise_a_baseline() -> None:
    """任务书「变绿手段六禁」的自证：`--write-ledger` 在现算回升时也只准把基线往下钳。"""
    previous = dict(_BL)
    states = {"retire_shims": [], "relocate": ["x"], "classified": [], "outside": 195}
    out = s34.clamped_baselines(previous, states)
    assert set(out) == set(previous), "生成器写的基线名与读的不是同一批＝钳制漏了某本"
    assert all(out[k] <= previous[k] for k in previous), f"重记把基线抬高了＝生成器是后门：{out}"
    assert out["OUTSIDE_BASELINE"] == 190, (
        f"域外全量现算 195（>190）被直接记成新基线＝变相升基线（P-22 裁定 B 禁止项）：{out}"
    )
    assert out["UNLANDED_SUM_BASELINE"] <= out["SHIM_RETIRE_BASELINE"] + out["RELOCATE_BASELINE"], (
        f"钳完之后和锁反而比参照点之和松＝定理前提被生成器自己破坏：{out}"
    )


def test_poison_10_unreadable_ledger_declaration_is_rejected_not_empty() -> None:
    """⑩（S60 补 · P-S52-1）：账「读不到」必须拒读判红，不许退化成**空账放行**。

    三形各验，全在内存字符串里注毒（绝不写源码树）：
    - `SHIM_ROWS: tuple[...]`（只声明不赋值，`AnnAssign.value is None`）
    - `SHIM_ROWS = None`（字面量确实是 None）
    前两形正是 mypy 曾报 `literal_eval(expr | None)` 的那条分支：旧写法把「声明成空壳」读成零行账，
    于是 ①（漏记现算垫片）在账被清空的瞬间恰好看不见 —— 门会在最需要它红的时候绿。
    第三形（非字面量调用）是既有拒读判据的回归复核，防这次改动把它顺带放宽。
    """
    sources = (
        "SHIM_ROWS: tuple[tuple[str, str, int], ...]\n",
        "SHIM_ROWS = None\n",
        "SHIM_ROWS = build_rows()\n",
    )
    for source in sources:
        try:
            s34.load_ledger_rows(source)
        except AssertionError:
            continue
        raise AssertionError(f"读不到的账被放行（未拒读）＝⑩腿空转：{source!r}")
    # 现账必须仍读得出（防把"拒读"做成无条件抛，那样门也瞎了）
    assert s34.load_ledger_rows(), "真账被误判成拒读＝取数口反向自伤"


# --------------------------------------------------------------------------
# 同源锁：--report 打印值必须由门用的同一 compute 派生（防"总数另算一套"）
# --------------------------------------------------------------------------
def test_report_lines_are_same_source_as_gate_checks() -> None:
    data = s34.compute()
    st = s34.three_states()
    assert data["states"]["retire_shims"] == st["counts"]["retire_shims"]
    assert data["states"]["relocate"] == st["counts"]["relocate"]
    assert data["states"]["outside"] == st["outside"]
    rendered = "\n".join(s34.report_lines(data))
    assert "三态" in rendered and "待退役" in rendered, "--report 未并列输出三态"
    assert "未落地之和" in rendered, "--report 没打印锁加数那条硬锁＝报告与门的判据不是同一套"
    assert "三态之和" in rendered and "豁免" in rendered, "--report 缺三态之和/豁免同门账"
    v = data["ratchet"]
    assert str(v["unlanded_now"]) in rendered and str(v["outside_now"]) in rendered, "报告数字非现算派生"


# --------------------------------------------------------------------------
# S101 新增：`__init__.py` 包垫片按父包点号前缀计真引用 ＋ `cross_check` ②b
# 「已退役被写回引用」补腿 ＋ 引用面/声明面 fail-closed（S87 Critical-1/2，只加严）。
# 注毒全在内存/合成数据，绝不往源码树写。
# --------------------------------------------------------------------------
_S101_PKG_RETIRED = "plugins/bot_unified_runtime/defunct_pkg_shim/__init__.py"
_S101_MOD_RETIRED = "plugins/bot_unified_runtime/sources/defunct_mod_shim.py"


def test_s101_package_shim_live_counts_are_not_false_zero() -> None:
    """反假零主锁：被父包点号形态真实引用的包垫片，`computed_refs()` 必须报出非零。

    旧实现拿 `<pkg>.__init__` 点号去查索引 ⇒ 七枚包垫片全恒 0，谁据「refs=0 ⇒ 可删」
    动手就当场打坏生产导入图。本锁里 `policy` 一枚**只有**实测根 `__init__.py:3740
    `from .policy import (`` 这一种相对形态引用 —— 相对导入解析成绝对点号这条腿不生效它就还是 0。
    只钉 **>0** 地板不钉绝对值 —— 正当迁走调用方让数变小是进展（账语义），不得误伤。

    2026-09-24 S188 换腿（S146 §3 P3 / S146 option ②，非缩面）：原四腿里
    `sender/__init__.py`、`sources/subscriptions/__init__.py` 今日 `computed_refs()==0`
    （本席实测两枚 `_referencing_files` 皆 `owners=[]` —— 消费方已迁走，是账语义的正向进展，
    强钉 >0 会拿「迁完了」当「取数口坏」误伤）。现留两枚仍有真引用的包垫片，且两种形态各居其一：
    - `policy/__init__.py`：仅靠根 `__init__.py` 的**相对形态** `from .policy import` 命中（level=1）；
    - `sources/parsers/__init__.py`：仅靠 `tests/test_auditfix_subscriptions_capabilities.py` 的
      **点号串**（monkeypatch/importlib 字面量目标）命中。
    ⇒ 反假零牙齿不降：相对腿坏 ⇒ policy 归零当场红；点号串腿坏 ⇒ parsers 归零当场红。
    复跑取值：`python -c "import scripts.shim_retirement_census as s; idx=s.reference_index(); \
    print([(k, s.computed_refs('plugins/bot_unified_runtime/'+k, index=idx)) for k in \
    ('policy/__init__.py','sources/parsers/__init__.py')])"`（两值必 >0）。
    """
    for rel in (
        "plugins/bot_unified_runtime/sources/parsers/__init__.py",
        "plugins/bot_unified_runtime/policy/__init__.py",
    ):
        assert s34.computed_refs(rel) > 0, f"{rel} 仍恒零＝父包点号引用没被数到（S87 Critical-1 未修好）"


def test_s101_poison_a_dropping_reference_records_moves_the_count() -> None:
    """注毒 a：在内存索引里删光一枚包垫片的引用记录 ⇒ 计数必须同步归零 ——
    证明数的是真引用，不是常数 0。

    2026-09-24 S188 换受害枚：旧样本 `sender/__init__.py` 今日真引用归零（消费方迁走，见
    `test_s101_package_shim_live_counts_are_not_false_zero` docstring），改钉 `policy/__init__.py`
    （根 `__init__.py` `from .policy import` 相对形态真实引用，现算 base==1）。"""
    row = "plugins/bot_unified_runtime/policy/__init__.py"
    index = s34.reference_index()
    base = s34.computed_refs(row, index=index)
    assert base > 0, "policy 包垫片真引用已是 0＝本席注毒样本过期（引用面变了，换受害枚再钉）"
    target = s34.shim_target_dotted(row)
    pruned = {
        k: v
        for k, v in index.items()
        if k != target and k != f"{target}.*" and not k.startswith(target + ".")
    }
    dropped = s34.computed_refs(row, index=pruned)
    assert dropped == 0 < base, f"删光父包点号引用后计数为 {dropped}（应 0）＝没在数真引用"


def test_s101_poison_b_retired_dotted_written_back_is_red() -> None:
    """注毒 b：「已登记但盘上不存在」（视为已退役）的垫片，其点号重回引用索引 ⇒
    `cross_check` ②b 必红**并点名是谁在引**（S87 Critical-2：旧版对不存在路径无条件放行）。
    包垫片与普通模块两形态各注一发，全合成数据零写盘；反向断言（无引用 ⇒ 该腿静默）
    证明它不是无条件红的假锁。"""
    live_rows = s34.load_ledger_rows()
    rows = copy.deepcopy(live_rows) + [
        {"path": _S101_PKG_RETIRED, "canonical": live_rows[0]["canonical"], "refs": 0},
        {"path": _S101_MOD_RETIRED, "canonical": live_rows[0]["canonical"], "refs": 0},
    ]
    assert not (REPO / _S101_PKG_RETIRED).exists() and not (REPO / _S101_MOD_RETIRED).exists()
    poison_index = {
        "plugins.bot_unified_runtime.defunct_pkg_shim.queue": frozenset({"plugins/bot_unified_runtime/__init__.py"}),
        "plugins.bot_unified_runtime.sources.defunct_mod_shim": frozenset({"scripts/e2e_acceptance.py"}),
    }
    probs = s34.cross_check(rows, {}, refs_fn=lambda _p: 0, index=poison_index)
    hits = probs["retired_re_referenced"]
    assert len(hits) == 2, f"已退役垫片被写回引用没判红（应 2 条）: {hits}"
    assert any(_S101_PKG_RETIRED in h and "bot_unified_runtime/__init__.py" in h for h in hits), hits
    assert any(_S101_MOD_RETIRED in h and "e2e_acceptance.py" in h for h in hits), hits
    clean = s34.cross_check(rows, {}, refs_fn=lambda _p: 0, index={})
    assert clean["retired_re_referenced"] == [], "无引用也被 ②b 判红＝无条件红，不是反查"
    assert {
        "missing_registration", "not_a_shim", "canonical_missing",
        "refs_over_ceiling", "canonical_mismatch", "retired_re_referenced",
    } == set(probs), "②b 只准新增，既有五类不许改名或合并"


def test_s101_poison_c_illegal_declaration_literal_is_named() -> None:
    """注毒 c（声明面）：`SHIM_ROWS` 含非法字面量（裸整数／错元数／refs 非整数）⇒
    fail-closed 拒读**并点名**。旧写法会在深处抛不点名的 TypeError 或被静默解包 ——
    本席补成形校验（S94 同哲学）。"""
    for source in (
        "SHIM_ROWS = 42\n",
        "SHIM_ROWS = (('a', 'b'),)\n",
        "SHIM_ROWS = (('a', 'b', 'c'),)\n",
    ):
        try:
            s34.load_ledger_rows(source)
        except AssertionError as exc:
            assert "拒读" in str(exc) and "SHIM_ROWS" in str(exc), f"拒读未点名＝fail-closed 不完整: {exc}"
            continue
        raise AssertionError(f"非法字面量被放行＝注毒 c（声明面）空转: {source!r}")
    assert s34.load_ledger_rows(), "真账被误拒＝判据反向自伤"


def test_s101_poison_c_unreadable_reference_file_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """注毒 c（引用面）：引用面存在不可 AST 解析的文件 ⇒ `computed_refs()` 不许静默当
    「没人引用」，必须抛 `ReferenceIndexError` 点名 `文件:行`（假零的第三种形态，就地堵死）。"""
    broken = tmp_path / "plugins" / "bot_unified_runtime" / "broken_syntax.py"
    broken.parent.mkdir(parents=True)
    broken.write_text("def broken(:\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(s34, "REPO_ROOT", tmp_path)
    s34._build_reference_index.cache_clear()
    try:
        with pytest.raises(s34.ReferenceIndexError) as excinfo:
            s34.computed_refs("plugins/bot_unified_runtime/sender/__init__.py")
        assert "broken_syntax.py:" in str(excinfo.value), f"未点名文件:行＝fail-closed 不完整: {excinfo.value}"
    finally:
        s34._build_reference_index.cache_clear()


def test_s101_poison_d_states_and_sum_lock_untouched_by_criterion_fix() -> None:
    """注毒 d：修判据后的现状 —— 三态与和锁数**分毫不动**、和锁仍绿。

    引用方数（`computed_refs`）不喂养三态归类与和锁；本锁钉死该面分离，防日后
    「改计数判据顺手移动方向锁」（§0 六禁的判据漂移形态）。和锁字面值 184/190 为
    `BASELINE.md` 起点，只准降不准升。"""
    st = s34.three_states()
    bl = s34.load_ledger_baselines()
    v = s34.coupled_ratchet(st["counts"], bl, outside=st["outside"])
    assert st["counts"]["retire_shims"] + st["counts"]["relocate"] + st["counts"]["classified"] == st["outside"]
    assert v["unlanded_within"] and v["outside_within"] and v["retire_rise_covered"] and v["relocate_rise_covered"], (
        f"判据修复不该动和锁却动了＝实现副作用: {v}"
    )
    assert v["unlanded_baseline"] == bl["UNLANDED_SUM_BASELINE"] <= 184, "未落地和锁漂出 184 起点值"
    assert v["outside_baseline"] == bl["OUTSIDE_BASELINE"] <= 190, "三态和锁漂出 190 起点值"
