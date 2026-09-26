"""wired ∧ exec-bypass「已通电却直呼真身」：方向棘轮 + 反缩面 + 取数口对账（S95，全离线）。

判据原文（一句话，来自 S92 只读诊断的落地）：**一个态判为 wired 的能力，若仍有
``exec-bypass`` 形缝外直呼点（在中央汇缝之外直接 ``build_*_result`` / ``build_*_capability``），
则这条能力不得被叙述为「完全收编进中央调度层」。**

S92 的核心发现（`.superpowers/sdd/2026-09-24-central-dispatch/SEAT-S92.md`）：
普查 ``scripts/central_seam_census.py --json`` 的 ``counts.offseam_sites``（数**调用点**，今值 25）
与 ``counts.states.offseam``（数**能力 id**，因 ``_state()`` 让 wired/generic 前置短路，结构性=0）
**不矛盾**——单位不同且判据不同。真正该执法的是 ``violations_second_route``（数「wired ∧ exec-bypass」
的直呼点，今值 11）：这条形**已被尺计算、尺也备了 ``--fail-on-violations``（退出码 3），
但没有任何测试消费它**＝在册未执法（AGENTS 反复点名的最易误报成「已通电」的一形）。

本件把它升成常驻执法，三把尺各管一段、可单独归因（照 ``test_five_entry_seam_lock`` /
``test_descriptor_wiredness_ledger`` 的家规）：

* **方向棘轮（只降不升）**：prod / smoke / total / 承载 cid 数 各自钉一个**手写整数字面量**上限，
  等于本席现算实测（4 / 7 / 11 / 6）。**起点==实测：基线非空，就是「这些直呼点今天仍在缝外」的
  如实记账，不是「已收编」。** 谁新造一发「直呼真身绕过中央缝」都会把对应数顶过上限 → 当场红；
  逐枚收编后只准把上限下调（配合 `test_ceilings_are_handwritten_literals_not_derived`）。
* **反缩面塌陷锁**：``integrity.ok`` 必真、``files_scanned`` / ``seam_sites`` / ``states.wired``
  各设**地板**——把扫描面 ``SCAN_ROOTS`` 改窄让 25「变小」＝塌陷 → 红；外加内部恒等式
  ``sum(roster offseam 明细) == counts.offseam_sites``（藏点让明细 ≠ 账 → 红）。
* **取数口对账**：本件对 prod/smoke 的拆分**同时从 `roster` 与顶层 `violations_second_route`
  两处各独立现算一遍**，两值必须相等。若有人把尺里某一处的取数口改成自证式派生
  （字面量→「恒等于自己的上限」），两口径当场对不上 → 红。

设计纪律（HARDEN-1 / RF2-2 家规）：
* 上限是**手写常量**，绝不写 ``= _split_exec(real)``——与被检函数同一表达式＝棘轮对真树结构性不红。
* 注毒全走**内存 deep-copy 的合成 census dict**，``plugins/**`` 与尺本体**一个字都不写、不改**。
* 全树只读：只 shell 出 ``central_seam_census.py --json``（与 S81 量具锁同一条 CLI 出口），
  零 import 生产模块、零网络、零运行数据触点；``BOT_AUTOSYNC=0`` 下稳定绿。

复跑（席位纪律见 SEAT-S95.md）::

    export PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8 PYTHONPYCACHEPREFIX=<私有目录>
    ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest \\
        tests/test_offseam_wired_contradiction_gate.py -p no:cacheprovider --basetemp=<私有目录> -q
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_CENSUS = ROOT / "scripts" / "central_seam_census.py"

# ===========================================================================
# 方向棘轮上限（本席现算实测 2026-09-24T01:29:44Z，尺 v0.2.0-beta1，integrity.ok=true）。
# ⚠ 手写整数字面量，绝不允许改成 `= len(...)` / `= _split_exec(...)` 等派生式
#   （由 `test_ceilings_are_handwritten_literals_not_derived` AST 锁死）。
#   值与 S92 现算一致（prod 4 / smoke 7 / total 11），但**承载 cid 数**本席纠为现算 **6**
#   ——S92 补丁误写 17（把「承载任意 offseam 点含 assembly-wrap」混成「wired ∧ exec-bypass」），
#   照抄 17 会在正确树上当场红。
# ===========================================================================
CEILING_PROD_EXEC_BYPASS = 4  # 生产 __init__.py：ignore×1 + music_mode×3
CEILING_SMOKE_EXEC_BYPASS = 7  # domains/ops/smoke/：epic2 weather2 wiki2 meme1
CEILING_TOTAL_EXEC_BYPASS = 11  # = prod + smoke
CEILING_CONTRADICTED_CIDS = 6  # wired ∧ 有 exec-bypass 的能力数

# ===========================================================================
# 反缩面地板（现算值留足下浮余量；只有扫描面塌了才可能触底，正常债务收编不会）。
# ===========================================================================
FLOOR_FILES_SCANNED = 250  # 现算 files_scanned=330；把 SCAN_ROOTS 改窄会跌破
FLOOR_SEAM_SITES = 40  # 现算 seam_sites=54；中央汇缝正证据，塌陷＝扫描瞎了
FLOOR_WIRED = 20  # 现算 states.wired=34；wired 面归零＝判据对真树失明


def _is_smoke(file: str) -> bool:
    """冒烟/演示工装（非消息主链路）：路径含 ``/ops/smoke/``。与尺的 file 字段用正斜杠一致。"""
    return "/ops/smoke/" in file


def _split_exec_from_roster(census: dict[str, Any]) -> tuple[int, int, set[str]]:
    """独立取数口 ①：从 ``roster`` 现算「wired ∧ exec-bypass」的 (prod, smoke, 承载 cid 集合)。"""
    prod = smoke = 0
    cids: set[str] = set()
    for cid, row in census["roster"].items():
        if row.get("state") != "wired":
            continue  # 只有 wired 才叫「已通电却直呼」这一矛盾
        for site in row.get("offseam_sites", []):
            if site.get("tag") != "exec-bypass":
                continue  # assembly-wrap 是装配闭包（prepared 构造那一步），非债，不计
            cids.add(cid)
            if _is_smoke(site.get("file", "")):
                smoke += 1
            else:
                prod += 1
    return prod, smoke, cids


def _prod_exec_cids(census: dict[str, Any]) -> list[str]:
    """生产路径（非冒烟）带 exec-bypass 的 wired 能力，排序去重——供棘轮点名。"""
    cids: set[str] = set()
    for cid, row in census["roster"].items():
        if row.get("state") != "wired":
            continue
        for site in row.get("offseam_sites", []):
            if site.get("tag") == "exec-bypass" and not _is_smoke(site.get("file", "")):
                cids.add(cid)
    return sorted(cids)


def _split_exec_from_violations_list(census: dict[str, Any]) -> tuple[int, int]:
    """独立取数口 ②：从顶层 ``violations_second_route`` 列表现算 (prod, smoke)。"""
    prod = smoke = 0
    for v in census.get("violations_second_route", []):
        if v.get("tag") != "exec-bypass":
            continue
        if _is_smoke(v.get("file", "")):
            smoke += 1
        else:
            prod += 1
    return prod, smoke


def _offseam_detail_sum(census: dict[str, Any]) -> int:
    return sum(len(row.get("offseam_sites", [])) for row in census["roster"].values())


def _problems(census: dict[str, Any]) -> list[str]:
    """唯一判据口：喂真树或喂合成皆可，返回人读违规清单（空 == 健康）。

    活性锁与全部注毒用例共用这一支真身，绝不留第二套判定。
    """
    problems: list[str] = []

    integrity = census.get("integrity", {})
    if not integrity.get("ok", False):
        problems.append(
            f"[反缩面] 尺报缺件/解析失败（不得把解析失败当 0 站点）：{integrity}"
        )

    meta = census.get("meta", {})
    counts = census.get("counts", {})
    if meta.get("files_scanned", 0) < FLOOR_FILES_SCANNED:
        problems.append(
            f"[反缩面] files_scanned={meta.get('files_scanned')} < 地板 {FLOOR_FILES_SCANNED}"
            "＝扫描面被改窄让债『变小』（不是收编）"
        )
    if counts.get("seam_sites", 0) < FLOOR_SEAM_SITES:
        problems.append(
            f"[反缩面] seam_sites={counts.get('seam_sites')} < 地板 {FLOOR_SEAM_SITES}"
            "＝中央汇缝正证据塌陷（扫描瞎了）"
        )
    wired_now = counts.get("states", {}).get("wired", 0)
    if wired_now < FLOOR_WIRED:
        problems.append(
            f"[反缩面] states.wired={wired_now} < 地板 {FLOOR_WIRED}＝wired 面对真树失明"
        )

    detail = _offseam_detail_sum(census)
    if detail != counts.get("offseam_sites"):
        problems.append(
            f"[内部自洽] roster offseam 明细求和 {detail} ≠ counts.offseam_sites "
            f"{counts.get('offseam_sites')}＝藏点/缩面让 25 变小"
        )

    roster_prod, roster_smoke, contradicted = _split_exec_from_roster(census)
    list_prod, list_smoke = _split_exec_from_violations_list(census)
    if (roster_prod, roster_smoke) != (list_prod, list_smoke):
        problems.append(
            f"[取数口对账] roster 现算 prod/smoke=({roster_prod},{roster_smoke}) 与顶层 "
            f"violations_second_route 现算 ({list_prod},{list_smoke}) 不一致＝两处取数口漂移"
            "（尺里某一处被改成自证式派生/被抹平）"
        )

    # —— 方向棘轮：只准降不准升，升面逐枚点名 ——
    total = roster_prod + roster_smoke
    if roster_prod > CEILING_PROD_EXEC_BYPASS:
        problems.append(
            f"[棘轮·生产] 生产路径 wired∧exec-bypass 直呼点升到 {roster_prod} > 上限 "
            f"{CEILING_PROD_EXEC_BYPASS}＝新造『直呼真身绕过中央缝』被当成已收编；"
            f"承载生产直呼点的能力：{_prod_exec_cids(census)}"
        )
    if roster_smoke > CEILING_SMOKE_EXEC_BYPASS:
        problems.append(
            f"[棘轮·冒烟] 冒烟 wired∧exec-bypass 直呼点升到 {roster_smoke} > 上限 "
            f"{CEILING_SMOKE_EXEC_BYPASS}"
        )
    if total > CEILING_TOTAL_EXEC_BYPASS:
        problems.append(
            f"[棘轮·总] exec-bypass 直呼点合计 {total} > 上限 {CEILING_TOTAL_EXEC_BYPASS}"
        )
    if len(contradicted) > CEILING_CONTRADICTED_CIDS:
        problems.append(
            f"[棘轮·承载 cid] 『wired ∧ exec-bypass』能力数升到 {len(contradicted)} > 上限 "
            f"{CEILING_CONTRADICTED_CIDS}＝有新能力被写进『零缝外点』叙述：{sorted(contradicted)}"
        )
    return problems


def _run_census() -> dict[str, Any]:
    """跑尺子本体（CLI 出口，与 S81 量具锁同一条路）。``encoding`` 必钉——本仓铁律。"""
    out = subprocess.run(
        [sys.executable, str(_CENSUS), "--json"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=900,
        check=False,
    )
    assert out.returncode == 0, f"普查尺跑不起来（RC={out.returncode}）：{out.stderr[-500:]}"
    return json.loads(out.stdout)


_REAL: dict[str, Any] | None = None


def _real() -> dict[str, Any]:
    """整树只跑一次，多腿共用（与 S81/S67 门同一缓存哲学）。"""
    global _REAL
    if _REAL is None:
        _REAL = _run_census()
    return _REAL


# ===========================================================================
# ① 真树活性：现算 == 账本，且基线非空（起点==实测，禁「已收编」叙述）
# ===========================================================================
def test_real_tree_offseam_contradiction_is_within_ledger() -> None:
    """真树喂判据口必须全绿：不越棘轮上限、不塌陷、两取数口对得上。"""
    problems = _problems(_real())
    assert problems == [], "缝外矛盾账漂移：\n" + "\n".join(problems)


def test_baseline_is_honest_not_pre_cleared() -> None:
    """起点==实测：上限非空＝『这些直呼点今天仍在缝外』的如实记账，不是『已收编』。

    反向：真树现算必须真的坐在这几个上限上（否则本锁基线虚高，棘轮空转）。
    """
    assert CEILING_TOTAL_EXEC_BYPASS > 0, "总上限被写成 0＝本件在替『已收编』作证，但真树还在直呼"
    prod, smoke, contradicted = _split_exec_from_roster(_real())
    assert (prod, smoke) == (CEILING_PROD_EXEC_BYPASS, CEILING_SMOKE_EXEC_BYPASS), (
        f"真树现算 ({prod},{smoke}) ≠ 在册基线 "
        f"({CEILING_PROD_EXEC_BYPASS},{CEILING_SMOKE_EXEC_BYPASS})；若已真正收编请同步下调上限，"
        "若长出直呼点则由棘轮拦下——别让基线与实测脱钩成空锁。"
    )
    assert len(contradicted) == CEILING_CONTRADICTED_CIDS, (
        f"承载 exec-bypass 的 wired 能力数现算 {len(contradicted)} ≠ 基线 "
        f"{CEILING_CONTRADICTED_CIDS}：{sorted(contradicted)}"
    )


# ===========================================================================
# ② 上限去自指：手写整数字面量，AST 结构锁（照 ledger GAP_CEILING 家规）
# ===========================================================================
def test_ceilings_are_handwritten_literals_not_derived() -> None:
    """四枚上限必须是顶层**整数字面量**，不得写成 `= _split_exec(...)`/`= len(...)+...`。

    与被检函数同一表达式＝棘轮对真树结构性不可能红（RF2-2 定罪形态）。AST 判据才拆得穿回退。
    """
    import ast

    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    found: dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id.startswith("CEILING_"):
                    found[tgt.id] = node.value
    for name in (
        "CEILING_PROD_EXEC_BYPASS",
        "CEILING_SMOKE_EXEC_BYPASS",
        "CEILING_TOTAL_EXEC_BYPASS",
        "CEILING_CONTRADICTED_CIDS",
    ):
        assert name in found, f"源码顶层找不到 {name} 的赋值（判据被搬走？）"
        value = found[name]
        assert (
            isinstance(value, ast.Constant)
            and isinstance(value.value, int)
            and not isinstance(value.value, bool)
        ), f"{name} 不是手写整数字面量＝棘轮上限被改成派生式（自指=对真树恒不执法）"
    # 字面量算术自洽：total == prod + smoke（写成派生会被上面拦，故这里只做数值一致性核对）。
    assert (
        CEILING_TOTAL_EXEC_BYPASS
        == CEILING_PROD_EXEC_BYPASS + CEILING_SMOKE_EXEC_BYPASS
    )


# ===========================================================================
# ③ 注毒自证（全走内存 deep-copy 合成 census，plugins/** 与尺一个字不写）
# ===========================================================================
def test_poison_clearing_violations_list_is_red() -> None:
    """注毒①（清某 violations 名单）：抹掉顶层 violations_second_route、roster 不动
    → 两取数口对不上 → 红（这正是『把尺的账偷偷抹平让债消失』那形）。"""
    poisoned = copy.deepcopy(_real())
    poisoned["violations_second_route"] = []
    problems = _problems(poisoned)
    assert any("取数口对账" in p for p in problems), (
        f"抹空 violations 名单竟未被两取数口对账抓到＝该锁空转：{problems}"
    )


def test_poison_derived_census_counter_is_red() -> None:
    """注毒②（尺的取数口被改成派生式）：只动 roster 一侧（抽掉一发 exec-bypass）、
    顶层列表不动 → roster 现算 与列表现算 分叉 → 红。

    证本件对 prod/smoke 有**两个独立取数口**：尺里任一处被改成『恒等于自己上限』的派生式、
    或与 roster 脱钩，当场对不上，本门不会被单一被抹平的取数口骗过去。
    """
    poisoned = copy.deepcopy(_real())
    victim = next(
        (
            (cid, i)
            for cid, row in poisoned["roster"].items()
            if row.get("state") == "wired"
            for i, s in enumerate(row.get("offseam_sites", []))
            if s.get("tag") == "exec-bypass" and not _is_smoke(s.get("file", ""))
        ),
        None,
    )
    assert victim is not None, "找不到生产 exec-bypass 落点＝注毒失去落点（先查上面活性锁）"
    cid, idx = victim
    poisoned["roster"][cid]["offseam_sites"].pop(idx)  # 藏一发，列表仍说 prod=4 → 两口径分叉
    problems = _problems(poisoned)
    assert any("取数口对账" in p for p in problems), (
        f"roster 侧藏点、列表侧不动，两取数口未判分叉＝派生式取数口拦不住：{problems}"
    )
    # 归因唯一：这条毒不该顺手把『明细==counts』也蒙混过去（明细少了 1、counts 仍 25 → 亦红）。
    assert any("内部自洽" in p for p in problems), problems


def test_poison_new_direct_call_site_is_named_and_red() -> None:
    """注毒③（合成一条新直呼点）：给某 wired 能力补一发生产路径 exec-bypass，
    三处（roster 明细 / counts / violations 列表）同步加账 → 一致性/对账全过，
    但 prod 顶过上限 → 棘轮红，且点名到具体能力。"""
    poisoned = copy.deepcopy(_real())
    target = "bot.music_mode"  # 真树里确为 wired ∧ 带 exec-bypass 的生产直呼能力
    assert poisoned["roster"][target]["state"] == "wired", poisoned["roster"][target]["state"]
    new_site = {
        "capability_id": target,
        "file": "plugins/bot_unified_runtime/__init__.py",
        "line": 999999,
        "surface": "plugins",
        "symbol": "build_poison_music_mode_result",
        "tag": "exec-bypass",
    }
    poisoned["roster"][target]["offseam_sites"].append(dict(new_site))
    poisoned["violations_second_route"].append(dict(new_site))
    poisoned["counts"]["offseam_sites"] += 1  # 明细同步，隔离出『只有棘轮上限该红』

    problems = _problems(poisoned)
    ratchet = [p for p in problems if "棘轮·生产" in p]
    assert ratchet, f"新造一发直呼点没顶爆生产上限＝棘轮是空转：{problems}"
    assert any("bot.music_mode" in p for p in problems), (
        f"红没点名到承载新债的能力：{problems}"
    )
    # 归因唯一：明细/对账两把一致性锁此时都不该误红。
    assert not any("内部自洽" in p for p in problems), problems
    assert not any("取数口对账" in p for p in problems), problems


def test_poison_shrunken_scan_surface_is_red() -> None:
    """注毒④（反缩面）：把 files_scanned 打塌（模拟 SCAN_ROOTS 改窄）→ 塌陷锁红。"""
    poisoned = copy.deepcopy(_real())
    poisoned["meta"]["files_scanned"] = 5
    problems = _problems(poisoned)
    assert any("反缩面" in p and "files_scanned" in p for p in problems), (
        f"扫描面塌到 5 个文件都没被判塌陷＝反缩面锁空转：{problems}"
    )


def test_ratchet_allows_legitimate_debt_removal() -> None:
    """方向锁（只准降）：把一发生产直呼点真正收编（roster+列表+counts 三处同步摘账）
    → prod 3 < 上限 4 → 判据口全绿（否则将来没人敢摘基线降账）。"""
    shrunk = copy.deepcopy(_real())
    victim = next(
        (
            (cid, i)
            for cid, row in shrunk["roster"].items()
            if row.get("state") == "wired"
            for i, s in enumerate(row.get("offseam_sites", []))
            if s.get("tag") == "exec-bypass" and not _is_smoke(s.get("file", ""))
        ),
        None,
    )
    assert victim is not None
    cid, idx = victim
    removed = shrunk["roster"][cid]["offseam_sites"].pop(idx)
    shrunk["counts"]["offseam_sites"] -= 1
    shrunk["violations_second_route"] = [
        v for v in shrunk["violations_second_route"] if v.get("line") != removed.get("line")
    ]
    prod, _smoke, contradicted = _split_exec_from_roster(shrunk)
    assert prod < CEILING_PROD_EXEC_BYPASS, "收编后 prod 未下降＝摘账摘不动"
    problems = _problems(shrunk)
    # 收编一枚后，若该 cid 已无任何 exec-bypass，则承载 cid 数 -1；两值都必须 ≤ 上限（放行降账）。
    assert prod <= CEILING_PROD_EXEC_BYPASS and len(contradicted) <= CEILING_CONTRADICTED_CIDS
    assert not any("棘轮" in p for p in problems), f"真正降账被棘轮反判红＝方向写反：{problems}"
