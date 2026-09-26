"""垫片「待退役」第二本账 —— 唯一取数口（G-P2 豁免清单的**并列账**，解 P-16 A 案）。

背景（`.superpowers/sdd/2026-09-22-taxonomy/PARKED.md` P-16）：`G_P2_EXEMPT` 恰 29 条且全是包命名空间
`__init__.py`（`G_P2_EXEMPT_CEILING=29` 只准降），而 §2.3 定性的那批 PEP 562 惰性转发**垫片**既未被
`impl_paths` 认领、也不在豁免里 ⇒ 全部被算进 G-P2 违规主力。任务书要求「退役前登记进豁免」与「豁免只准降」
顶牛，二者不可同时成立。⇒ 本席**不动豁免账**，另立与豁免并列的第二本账 `domains/core/board_shim_ledger.py`，
把垫片单列为「待退役」态，逐枚 `path → 真身 path → 引用方数` 由 AST/grep 现算校验、禁手抄真身路径。

C3 的「域外」（`plugins/**` 下不在 `domains/` 里的 py）在本算口里拆成三态、并列输出：
- **已归类**：域外、非垫片、未被任何 `impl_paths` 认领 —— 包命名空间 `__init__.py`、`control_plane` 子系统、
  决策/LLM 等自成一体的部件（其归位与否属 P-2/P-6 另案，本席不裁）。
- **待搬迁**：域外、非垫片、但**已被某二级功能 `impl_paths`（语义A）认领** —— 家已登记、文件还留在原地，
  搬迁由 S13/S33 做。**只准降**（搬走一枚即少一枚）。
- **待退役(垫片)**：域外、PEP 562/星号再导出薄壳且**真身可派生且存在** —— 登记进本账。退役（迁完调用方后删除）
  由 S14 做。**只准降**（退役一枚即少一枚）。

判据口径（写死，复用 `physical_placement_census` 的取数口，禁第二份扫描器）：
- **垫片** := 命中 `_SHIM_MARKERS` **且** 能由 AST 派生出**存在**的真身（`.py` 或 `<pkg>/__init__.py`）。
  仅命中记号但派生不出真身的（如用相对导入的包命名空间 `__init__.py`）不算垫片 —— 归「已归类」，
  与 BASELINE §1.1 对三枚 `character/runtime/sources __init__` 的「非垫片」定性一致。
- **真身** := 从垫片源码 AST 现算（`_CANONICAL` 字面量 或 `from <mod> import *`），**禁手抄**。
- **引用方数** := 全仓（`plugins/**`+`scripts/**`+`tests/**`+根 `bot.py`）AST 里按垫片点号名引用它的文件数。
  包垫片（`__init__.py`）按**父包点号前缀**计（引用父包或其任何子模块的写法运行期都会执行包壳）；
  相对导入按引用方所在包解析成绝对点号名；`importlib.import_module("…")` 字面量同样入册；
  交给运行期导入机器的另一入口 —— `monkeypatch.setattr("a.b.c", …)` / `mock.patch("a.b.c")`
  的字面量点号目标 —— 同样入册（同一把尺，TX319 补：旧版漏这一形 ⇒ `sources/parsers` 恒零假信号）；
  引用面不可解析 ⇒ fail-closed 点名 `文件:行`（S101 根修 S87 Critical-1 的恒零假信号）。
  账上存的是**上限**（`refs`），现算只准 `≤` 它 —— 迁走调用方让数变小是进展（放行），新增旧写法让它变大才判红。

三件事**共用同一批函数**（本仓抓到过"总数另算一套"的假绿）：① 常驻门 `tests/test_shim_retirement_ledger.py`；
② 注毒自证（喂内存合成数据，绝不往源码树写）；③ `--report` 现算值。

## 方向锁的形态：锁加数，不锁加项（P-22 裁定 A 案 · S52 落地）

S34 首版把「待退役」「待搬迁」**各自**只准降。这个判据在奖励偷懒：S33 给一枚域外件补 `impl_paths`
认领是**正确动作**，却会把枚数从别的态并入待搬迁 ⇒ 顶高那只降锁 ⇒ 门红，而唯一不变红的办法是不作为。
⇒ 硬锁改成单调下降的**「待搬迁＋待退役」之和**（域外未落地总量）与**三态之和**（域外全量）；
单态基线退为耦合算术的参照点：某态上升的部分必须由另一态**等额或更多**的下降抵掉。
该条件是_sum 锁的必然推论_（可证耦合，不是放宽判据）。

会不会出现「退役一侧真进展、另一侧偷偷长新垫片」把和锁蒙过去？不会 —— `cross_check` ①
`missing_registration` 独立执法：任何现算识别出的垫片，未经 `--write-ledger` 入账就当场红，
与和锁无关。同理 ⑤ `canonical_mismatch` 封掉「手抄一个也存在但不对的真身」。

## 逐枚 `refs` 上限：与基线对称地「只准降」＋显式审批通道（S155 · S147 机制缺口根修）

四枚基线经 `clamped_baselines` 钳 `min(既有, 现算)` ⇒ `--write-ledger` 抬不动；但逐枚 `refs` 上限旧版是
`refs = computed_refs` 直写，无钳制 —— 于是「删滞后行（正当进展）」与「抬上限（§0 六禁的糊红）」被同一
命令捆死：想取前者必须接受后者。S147 因此宁可留红也不回写。现把 `render_ledger` 的逐枚 `refs` 也钳
`min(既有, 现算)`，与基线对称。纯 `min` 会死锁「假零修好」那一族（虚 0 上限永远纠不回真值），故配一条
**显式审批通道** `approved_refs_paths`：状态件 `scripts/shim_refs_approvals.json`（owner 手工维护、本席不创建），
每枚审批带 `path/approved_by/reason/expiry`，过期自动失效（口径「临时停用要自动到期」）；
`path` 必须命中当前现算垫片，否则该审批不生效（fail-closed 拒批）。⇒ 现在「裁行」可无审批独立执行
（11 枚上限纹丝不动、门诚实红），「抬上限」必须逐枚署名且可过期，两件事终于可分离。

## 撕裂读的台账腿防线（TX201 · 续 TX191，Critical）

TX191 的双读完整性判据**只装在引用索引腿**（`_require_complete_reference_index` → `render_ledger` 的
`min(prior_refs[rel], live)` 里的 `live`）；另一操作数 `prior_refs[rel]` 与四枚基线钳制仍走裸
`LEDGER_PY.read_text` + 宽容解析（`load_ledger_rows` / `previous_baselines`）。喂空账 ⇒ `load_ledger_rows→0 行`、
`previous_baselines→{}` **双双静默放行** ⇒ 每枚走「首次入账」分支 ⇒ `ceiling=live` 免审批抬上限并持久化。
更糟：撕裂读的**生产方就是本工具自己** —— 旧 `--write-ledger` 用 `LEDGER_PY.write_text`（truncate+write 非原子）。
本段把三条补齐：① 台账读侧同装完整性判据（`_read_ledger_source_with_integrity` 双读撕裂 + 空账/解析零行/语法坏
⇒ `LedgerReadIncomplete`，不许当「没有历史」）；② `render_ledger` 在 `min()` 降账前先取「已确认完整 + 非空」的
既有账，拿不到即抛、`main` 拒写保留旧值；③ 台账写改**原子**（`_atomic_write_text`：同目录临时文件 + `os.replace`）。
回归锁见 `tests/test_ledger_read_integrity_tx201.py`（TX199 F-2：旧新测试件对 `load_ledger_rows|previous_baselines|
prior_refs` 零提及＝该腿零锁）。

## 路径解析读点的形态覆盖（S118 · CM-P-9 施工次序①，2026-09-24）

「P2 垫片降为再导出」的目标形态是**域内真身 + 域外薄壳**，而本件的判据全建立在
「路径 → 源码 → 派生真身点号名 → 盘上存在」这条读点上。壳的写法一变（星号 → 相对导入 →
`_CANONICAL_PKG` → 显式名字表 + `__all__`），读点就会**认不出而静默丢件** —— 账上表现成"垫片少了几枚"，
既不是红也不是进展，是假零（本仓记过的最坏失效形态）。本段把这条读点补齐并让它**可自证**：

- `derive_canonical(src, shim_rel)` 现在把**相对形**星号导入按引用方所在包还原成绝对点号名
  （level 算法与 `_build_reference_index` 一字同构，复用 `_referrer_package_dotted` —— 由
  `_file_package_dotted` 派生的唯一「当前包」尺，S203 归位，禁第二套相对导入口径）；
  旧版拿 `node.module` 直接当绝对名 ⇒ `from .sibling import *` 会被解析成仓根 `sibling.py`、盘上不存在
  ⇒ 整枚隐形。**今日实测该形零命中**（域外 51 枚记号命中里 level>0 者为 0），故本改动逐值中性。
- `classify_shim_candidate(rel, src)` 成为**唯一判定口**，`detect_shims`（合格集）与
  `blind_marker_hits`（盲区点名）**都只从它取数**：记号命中集 == 合格集 + 盲区集，恒等式成立后，
  "读点认不出的新形态"再也无法伪装成"确实不是垫片"。
- `three_states()` 附 `marker_blind`（只读附账，不进三态恒等式、不改任何桶计数），`--report` 逐枚点名。
- **塌陷锁** `_assert_no_detection_collapse`：域外非空、有记号命中、却零合格垫片 ⇒ 当场抛
  `ShimDetectionCollapsed`（与常驻门的 `MIN_SHIM_FLOOR` 数值地板尺分工：那把量枚数地板，本把量形态塌陷）。

**本席按「改前改后逐值等值」的硬界**没有落地的两件事（会动账，交门 owner 裁，见 SEAT-S147 §3 补丁文本）：
① `_CANONICAL_PKG`（PEP 562 包壳形，实测 `audit/contracts/decision/llm` 四枚 `__init__.py` 今天正因名字
差一枚 `_PKG` 而整枚隐形）；② 无任何记号的纯 `__all__` 显式再导出壳（实测 `output/`、`output/card_render/`、
`sources/`、`character/`、`runtime/` 等）。二者一落地就把 N 枚从「已归类/待搬迁」挪进「待退役」，
`UNLANDED_SUM_BASELINE`（只准降）当场红 —— 那是**真债现身**、不是本席改坏，须由 owner 带证据降账或先退役。
"""

from __future__ import annotations

import argparse
import ast
import functools
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

# 复用物理归位取数口（同一 AST 解析，禁第二份扫描器）。这些文件归 S13/S33，本席**只 import 不改**。
import physical_placement_census as ppc

LEDGER_PY = REPO_ROOT / "plugins/bot_unified_runtime/domains/core/board_shim_ledger.py"

#: 垫片特征记号（与 BASELINE §0 的 grep 口径一致）。仅命中记号不足以定性，还须能派生存在的真身。
_SHIM_MARKERS: tuple[str, ...] = ("Compat shim", "Live re-export", "_CANONICAL")


# --------------------------------------------------------------------------
# 垫片识别 + 真身派生（全部 AST 现算，禁手抄真身路径）
# --------------------------------------------------------------------------
def is_shim_text(src: str) -> bool:
    """命中任一枚垫片特征记号。定性垫片还须叠加『可派生真身』这一条（见 detect_shims）。"""
    return any(marker in src for marker in _SHIM_MARKERS)


def _rel_to_dotted(rel: str) -> str:
    return rel[:-3].replace("/", ".") if rel.endswith(".py") else rel.replace("/", ".")


def canonical_to_rel(dotted: str) -> tuple[str, ...]:
    """点号模块名 → 可能落盘的真身相对路径（模块文件或包目录 __init__）。"""
    base = dotted.replace(".", "/")
    return (f"{base}.py", f"{base}/__init__.py")


def resolve_canonical(dotted: str) -> str | None:
    """把派生出的点号真身解析成**实际存在**的相对路径；都不存在返回 None。"""
    for rel in canonical_to_rel(dotted):
        if (REPO_ROOT / rel).exists():
            return rel
    return None


def _absolute_dotted_for_import(level: int, module: str | None, shim_rel: str | None) -> str | None:
    """把 `from [. / ..] mod import …` 还原成**绝对点号名**（真身路径解析的锚点腿）。

    level 算法与 `_build_reference_index` 里那段**一字同构**（同一把尺，禁第二套相对导入口径）：
    `level=1` 锚在引用方所在包，每多一个点向上退一层，越过顶层即不可解析 ⇒ None。
    这里刻意复用 `_referrer_package_dotted`（由 `_file_package_dotted` 派生的唯一「当前包」尺，
    模块定义在后面，按名字运行期解析）而不是重算一遍路径，
    因为「相对导入按引用方所在包解析」这件事在本件里只准有一个实现。
    """
    if level <= 0:
        return module or None
    if not shim_rel:
        return None  # 没有引用方路径就无从定锚（调用方 detect_shims/blind_marker_hits 一律带 rel）
    pkg = _referrer_package_dotted(shim_rel)
    segs = pkg.split(".") if pkg else []
    up = level - 1
    if up > len(segs):
        return None
    anchor = ".".join(segs[: len(segs) - up])
    return ".".join(p for p in (anchor, module) if p) or None


def derive_canonical(src: str, shim_rel: str | None = None) -> str | None:
    """从垫片源码 AST 现算真身的**绝对点号模块名**。

    认两形态：① `_CANONICAL = "<dotted>"` 字面量（PEP 562 形）；② `from <mod> import *`（星号形，
    **含相对形**：`from .sibling import *` / `from ..pkg.mod import *` 按 `shim_rel` 所在包还原成绝对名）。
    派生不出（例如只用相对导入的包命名空间 `__init__.py`）返回 None ⇒ 调用方据此判「非退役垫片」，
    并由 `blind_marker_hits` **点名**（S118：绝不再静默 continue —— 静默跳过就是假零的成因）。

    `shim_rel` 缺省 None 时相对形按旧口径返回 None（既有调用方与合成夹具行为不变），
    取数口 `detect_shims`/`blind_marker_hits` 一律带 rel ⇒ 目标形态「域内真身 + 域外再导出壳」
    用相对导入时不再掉出账外。
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        target: ast.expr | None
        value: ast.expr | None
        if isinstance(node, ast.Assign):
            target = node.targets[0] if node.targets else None
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            value = node.value
        else:
            continue
        if (
            isinstance(target, ast.Name)
            and target.id == "_CANONICAL"
            and isinstance(value, ast.Constant)
            and isinstance(value.value, str)
        ):
            return value.value
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and any(a.name == "*" for a in node.names):
            dotted = _absolute_dotted_for_import(node.level, node.module, shim_rel)
            if dotted:
                return dotted
    return None


def outside_py(universe: list[str] | None = None) -> list[str]:
    """域外 = `plugins/**` 下、不在 `domains/` 里的 py（与 BASELINE §1 口径一致，不含根 bot.py）。"""
    universe = ppc.py_universe() if universe is None else universe
    domains_root = ppc.load_placement()["DOMAINS_ROOT"]
    return sorted(
        rel for rel in universe
        if rel.startswith("plugins/") and not ppc._under(rel, domains_root)
    )


def _source_of(rel: str) -> str:
    """域外相对路径 → 源码文本（路径解析读点的**唯一落点**；`--json`/门/盲区点名共用，禁两套读法）。"""
    return (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")


def classify_shim_candidate(rel: str, src: str | None = None) -> dict[str, Any]:
    """一枚域外文件的**唯一判定口**（读点全串：路径 → 源码 → 记号 → 派生真身 → 真身存在）。

    返回 `{path, marker_hit, dotted, canonical, stage}`，`stage` 穷尽且互斥：
    - `not-marked`：没命中 `_SHIM_MARKERS`（记号面之外，另由盲区之外的账管）；
    - `no-canonical-derived`：命中记号，但 `derive_canonical` 认不出该再导出形态；
    - `canonical-not-on-disk`：认出了点号真身，但盘上不存在（坏桩形态）；
    - `qualified`：三者全过 ⇒ 合格垫片，进「待退役」账。
    `detect_shims` 与 `blind_marker_hits` **都只从本口取数**（禁第二份判据），二者合起来恰等于
    命中记号的全集 —— 于是"读点认不出的新形态"与"确实不是垫片"再也混不起来。
    """
    source = _source_of(rel) if src is None else src
    if not is_shim_text(source):
        return {"path": rel, "marker_hit": False, "dotted": None, "canonical": None, "stage": "not-marked"}
    dotted = derive_canonical(source, rel)
    if not dotted:
        return {"path": rel, "marker_hit": True, "dotted": None, "canonical": None,
                "stage": "no-canonical-derived"}
    canonical = resolve_canonical(dotted)
    if not canonical:
        return {"path": rel, "marker_hit": True, "dotted": dotted, "canonical": None,
                "stage": "canonical-not-on-disk"}
    return {"path": rel, "marker_hit": True, "dotted": dotted, "canonical": canonical, "stage": "qualified"}


def detect_shims(outside: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """域外里所有**合格垫片**（`classify_shim_candidate` 的 `qualified` 集）。返回 `{rel: {canonical_dotted, canonical}}`。

    被派生/解析**淘汰**的命中件不在这里出现 —— 它们由 `blind_marker_hits` 逐枚点名（同一判定口）。
    旧版把落选者静默丢掉，于是"记号认得出、真身解析不出"与"确实不是垫片"在账上长得一模一样
    （S118 要堵的就是这一形）。
    """
    outside = outside_py() if outside is None else outside
    out: dict[str, dict[str, Any]] = {}
    for rel in outside:
        verdict = classify_shim_candidate(rel)
        if verdict["stage"] == "qualified":
            out[rel] = {"canonical_dotted": verdict["dotted"], "canonical": verdict["canonical"]}
    return out


#: `blind_marker_hits` 认得的两个落选阶段（`not-marked` 不叫盲区，它压根没命中记号）。
BLIND_STAGES: frozenset[str] = frozenset({"no-canonical-derived", "canonical-not-on-disk"})


def blind_marker_hits(outside: list[str] | None = None) -> list[dict[str, str]]:
    """**读点盲区点名**：命中垫片记号却没进「待退役」账的域外件，逐枚给阶段与细节。

    这是 S118（CM-P-9 施工次序①）的可见性腿：**桶账一字不动**（该枚仍按现判据留在「已归类」或
    「待搬迁」，三态恒等式与降锁算术照旧成立），但"记号认得出、真身解析不出"从**静默 continue**
    变成**具名清单**并随 `--report`/`compute()` 出到面上，于是"垫片换再导出形态 ⇒ 读点失效 ⇒ 假零"
    至少当场可见、可逐枚点名，而不是等某次数目莫名少了几枚才发现。
    """
    outside = outside_py() if outside is None else outside
    blind: list[dict[str, str]] = []
    for rel in sorted(outside):
        verdict = classify_shim_candidate(rel)
        if verdict["stage"] not in BLIND_STAGES:
            continue
        detail = (
            "" if verdict["dotted"] is None
            else f"dotted={verdict['dotted']} candidates={'、'.join(canonical_to_rel(verdict['dotted']))}"
        )
        blind.append({"path": rel, "stage": verdict["stage"], "detail": detail})
    return blind


class ShimDetectionCollapsed(RuntimeError):
    """域外里有垫片记号、却**一枚合格垫片都认不出** ⇒ 读点塌陷（CM-P-9 要的「塌陷锁」）。

    与常驻门 `tests/test_shim_retirement_ledger.py::test_scan_scope_did_not_collapse` 的地板尺分工：
    那把量"认出的枚数是否掉到地板下"（数值面，本席一字不改它），本枚量"记号还在、真身解析全灭"
    （**形态面**：把 `_CANONICAL` 改错一个字母、或把 `resolve_canonical` 的锚点改歪，都能让枚数瞬间归零，
    而地板尺只在跌破 MIN_SHIM_FLOOR 时才红）。抛在取数口 ⇒ 门与四本账第④本一起红，绝不静默出空账。
    """


def _assert_no_detection_collapse(outside: list[str], shims: dict[str, Any], blind: list[dict[str, str]]) -> None:
    """塌陷锁（纯判据，不改任何计数）：有记号命中、却零合格垫片 ⇒ 当场抛，点名盲区。"""
    if shims or not blind or not outside:
        return
    names = "、".join(item["path"] for item in blind[:5])
    raise ShimDetectionCollapsed(
        f"域外 {len(outside)} 件里 {len(blind)} 枚命中垫片记号却**一枚都没认出真身**"
        f"（盲区前 5 枚：{names}）——读点塌陷，禁止把『解析不出』当成『不是垫片』出账"
    )


# --------------------------------------------------------------------------
# 引用方计数（一次全树 AST 走，建点号名 → 引用文件集合）
# --------------------------------------------------------------------------
def _reference_index_scopes(rel: str) -> bool:
    if rel == "bot.py":
        return True
    return rel.startswith(("plugins/", "scripts/", "tests/"))


class ReferenceIndexError(RuntimeError):
    """引用面存在**不可解析**的文件 —— 取数口 fail-closed 上抛（S94 同哲学）。

    旧实现 `except (SyntaxError, UnicodeDecodeError): continue` 会把「读不到」静默伪装成
    「没人引用」：造一枚语法坏的文件就能让任何垫片的计数重新假零 —— 与 S87 Critical-1
    的恒零假信号同族，这次从取数口根上堵死。
    """


class ReferenceIndexUnstable(RuntimeError):
    """引用面某文件在**本轮读取窗口内发生变化**（撕裂读），半截索引不可信。

    与 `ReferenceIndexError` 分家：那个是「文件读不动/读出来不是合法 Python」，本枚是
    「文件读得动、甚至 parse 成功，但读到的是半截」。TX183/TX179/TX182 三席复现的正是这条
    ——并发写者（`scripts/**`+`tests/**` 归本波各席）把某 `.py` 截成一个仍能 parse 的前缀，
    旧实现 `ast.parse(read_text())` 零异常 ⇒ **半截索引进 `lru_cache`**，文件修好后同进程复调
    仍半索引（键 1 vs 5）；更狠的是 `render_ledger` 的 `min(既有, 现算)` 把 refs 上限钉成 0
    并写进退役台账，以「合法棘轮只降不升」形态**持久化**（清缓存也撤不回）。

    判据（TX191 根修）：对每枚在架文件双读比对 `(len, sha256)`，两次不一致即判撕裂 ⇒
    抛本枚、**且绝不进缓存**（`lru_cache` 异常不入缓存的既有语义，与 `bridge._load_icon_asset`
    同一把尺，不造第二把量具）。台账侧另设 `_require_complete_reference_index()` 防线：
    `min()` 降账前必须经它取「已确认完整」的索引，取不到就拒写、宁可保留旧值。
    """


class LedgerReadIncomplete(RuntimeError):
    """台账（`board_shim_ledger.py`）本轮读到的是**空账 / 解析零行 / 撕裂读 / 语法坏** —— 不许当「没有历史」。

    与引用腿的 `ReferenceIndexUnstable`/`ReferenceIndexError` 同哲学，只是受害面从「引用索引」换到
    「既有账」这一侧（TX199 F-1 现算：双读完整性判据旧版**只装在索引腿**，`min(prior_refs, live)` 的另一
    操作数仍走裸 `LEDGER_PY.read_text` + 宽容解析）。喂空账 ⇒ `load_ledger_rows→0 行`、
    `previous_baselines→{}` 双双静默放行 ⇒ 每枚走「首次入账」分支 ⇒ `ceiling=live` 免审批抬上限并持久化。
    台账读侧（`load_ledger_rows` / `previous_baselines`）与写入侧（`render_ledger` 的 `min()` 之前）**同装**
    这条判据：拿不到「已确认完整 + 非空」的本轮读 ⇒ 抛本枚 ⇒ `main` 拒写、保留旧账。
    """


def _read_file_bytes(path: Path) -> bytes:
    """单枚文件字节读取的**唯一落点**（撕裂检测的注入缝 —— 生产即 `path.read_bytes()`）。

    刻意薄到只有一行，好让注毒用例能确定性地喂进「两读不一致」的字节，同时 `_read_source_with_integrity`
    里的**比对逻辑本身**（size+sha256 双读核对）仍走真实码路 —— 测的是判据，不是测夹具。
    """
    return path.read_bytes()


def _integrity_token(raw: bytes) -> tuple[int, str]:
    """字节 → `(长度, sha256[:16])` 完整性凭据（与撕裂检测口径同源，禁另立一套）。"""
    return (len(raw), hashlib.sha256(raw).hexdigest()[:16])


def _read_source_with_integrity(path: Path, rel: str) -> str:
    """双读校验地读入一枚引用面源码，返回文本；撕裂读 ⇒ `ReferenceIndexUnstable` 点名 `rel`。

    序列＝读→取凭据→**再**读→取凭据→比对：只有两次完全一致才算「完整读」。
    真实撕裂（另一进程在两次读之间改了文件）必然让两读不同 ⇒ 抛。抛之前**不**返回、
    也不入缓存（调用方 `_build_reference_index` 是 `lru_cache`，异常天然不入缓存）。
    解码只走一次（用第一读），`UnicodeDecodeError` 属「读出来不是合法源码」而非「撕裂」，
    交由调用方既有 `except (..., UnicodeDecodeError, ...)` 归入 `ReferenceIndexError` 面，语义不变。
    """
    first = _read_file_bytes(path)
    second = _read_file_bytes(path)
    if _integrity_token(first) != _integrity_token(second):
        raise ReferenceIndexUnstable(
            f"{rel}: 撕裂读（两次读取不一致 size {len(first)}≠{len(second)}）"
            "——半截索引不可信，既不当作合法计数、也不入缓存、更不写台账"
        )
    return first.decode("utf-8")


def _read_ledger_source_with_integrity(path: Path | None = None) -> str:
    """台账文件的**双读完整性读入**（TX201 任务① —— 台账腿与引用腿同装判据、复用同一把尺）。

    与 `_read_source_with_integrity` 共用 `_read_file_bytes`（撕裂注毒缝）与 `_integrity_token`
    （size+sha256 比对）：读→再读→两读凭据不一致 ⇒ 撕裂（并发写者/本工具旧版非原子写截断）⇒ 抛
    `LedgerReadIncomplete`，绝不当作合法历史读进 `min()`。这里**只做撕裂检测**，空账/零行由
    `load_ledger_rows` / `previous_baselines` 各自的「解析零行 ⇒ 抛」判据兜（分工：撕裂 vs 内容）。
    """
    target = LEDGER_PY if path is None else path
    first = _read_file_bytes(target)
    second = _read_file_bytes(target)
    if _integrity_token(first) != _integrity_token(second):
        raise LedgerReadIncomplete(
            f"{target.name}: 台账撕裂读（两读不一致 size {len(first)}≠{len(second)}）"
            "——半截账不可信，既不当作合法历史、更不写台账（宁可保留旧账）"
        )
    return first.decode("utf-8")


def _atomic_write_text(path: Path, text: str) -> None:
    """原子写：同目录临时文件 → flush+fsync → `os.replace` 顶替（TX201 任务③）。

    撕裂读的**生产方就是本工具自己** —— 旧 `LEDGER_PY.write_text` 是 truncate+write 非原子，并发读者
    （门/`--check`/另一席现算）可能读到 truncate 之后、write 完成之前的半档，正喂进 `load_ledger_rows`
    的「空账」洞。`os.replace` 在同卷上是原子重命名 ⇒ 读者只会看到「旧完整版」或「新完整版」，永不见半档。
    写失败（含 replace 抛）⇒ 删临时文件、目标文件逐字节保持旧值（任务④「原子写中断不留半档」）。
    文本模式 `newline=None` 与旧 `write_text` 一致（Windows 上 `\n`→`\r\n`），生成物字节与既有台账同形。
    """
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:  # newline=None：与 Path.write_text 默认一致
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _file_package_dotted(rel: str) -> str:
    """引用方文件**自身**的点号名（import 身份）：普通模块＝`目录链 + 模块名` 全串，
    `__init__.py`＝其代表的包（去 `__init__` 段）。尺＝`tests/test_file_package_dotted_vs_stdlib.py`。

    三史对账（S203 2026-09-24，证据全录 `.superpowers/sdd/2026-09-24-central-dispatch/SEAT-S203.md` §1–§2）：
    - S146 前本函数就对普通模块返回此**自身点号名**，其病真实存在：level>=1 的相对导入锚点
      整体深一级 ⇒ `control_plane/*.py` 的 `from ..llm...` 被错记成 `control_plane.llm...`，
      4 枚垫片 9 条边被吞（ledger 5->6 / model_router 13->15 / providers 11->13 / plain_text 16->17；
      前三枚修后 `refs_over_ceiling` 转红＝真债现形、非本改引入；ceiling 的 min() 钳制与
      approvals 升账通道一字不动）。
    - S146 把「去一段」的锚点运算**放错了位置**——直接改在本原语上（无脑返回父目录点号名）⇒
      顶层非包目录 `scripts/`、`tests/`（无 `__init__.py`）派生出 round-trip 永不成立的
      `scripts`/`tests` 包名：S197 尺实跑 721 枚幻影、1291→139 碰撞、两锁红；且**任何「包」语义
      都永不可满足该锁的互异性**（同目录两文件必共享一个包名），修法不可能回到本原语上。
      （简报曾提「沿目录上溯、遇无 `__init__.py` 即停」：S203 现算同样双红——136 互异/569 幻影，
      且会把 `plugins/`（无 `__init__.py` 的 PEP 420 命名空间顶段）整段裁掉，令 plugins/** 全部
      点分名不再 round-trip、引用边整体坠空——比现码更坏，不采。）
    - S203 落点：本函数恢复自身点号名（与 S197 两锁逐文件等值），锚点「去一段」运算下沉到
      `_referrer_package_dotted` —— 两处消费边取到的锚基底与 S146 修后**逐文件全等**
      （现算 1291 枚 in-scope 差 0），9 条相对边与 approvals 五枚上限账零跟随。
    PEP 420：`scripts`/`tests`/`plugins` 为合法命名空间包（`find_spec` 现算全部 resolve；
    S197 判「严格包口径把正确名字当 bug＝判据选错」，S203 复核该判仍成立）。
    """
    parts = rel[:-3].split("/") if rel.endswith(".py") else rel.split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _referrer_package_dotted(rel: str) -> str:
    """引用方文件的**当前包**点号名——level>=1 相对导入的唯一锚基底（单一派生口，禁第二套）。

    由 `_file_package_dotted` 派生：普通模块去末段（模块名），`__init__.py` 恰代表其所在包、不去。
    对一切在架路径，本函数 ≡ 父目录点号链 ≡ `tests/test_legacy_shim_import_ratchet._collect_over`
    内联的 `".".join(rel.split("/")[:-1])`（S203 现算 1291/1291 等值；两尺不互 import、
    同构性由各注毒形态自证——S146 原设计保留）。锚点语义取 **import 模式**（仓根在 sys.path 上、
    `import scripts.foo` 的 `__package__` 即 `scripts`）；脚本模式下 level>=1 本就运行期报错，
    越顶层的边仍走消费边既有 fail-closed `errors` 腿，绝不静默计。
    """
    pkg = _file_package_dotted(rel)
    if not pkg:
        return ""
    if rel == "__init__.py" or rel.endswith("/__init__.py"):
        return pkg
    return pkg.rsplit(".", 1)[0] if "." in pkg else ""


def _importlib_literal(node: ast.AST) -> str | None:
    """`importlib.import_module("a.b.c")` / `__import__("a.b.c")` 的**字面量**目标；动态目标返回 None。"""
    if not isinstance(node, ast.Call) or not node.args:
        return None
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else (func.id if isinstance(func, ast.Name) else None)
    if name not in {"import_module", "__import__"}:
        return None
    arg = node.args[0]
    return arg.value if isinstance(arg, ast.Constant) and isinstance(arg.value, str) else None


def _patch_target_literal(node: ast.AST) -> str | None:
    """`monkeypatch.setattr("a.b.c", …)` / `mock.patch("a.b.c")` 的**字面量**目标；动态目标返回 None。

    与 `_importlib_literal` 是**同一把尺的两个入口**，不是第二把尺：两者量的都是「把点号字符串交给
    运行期导入机器」这一形态 —— pytest `MonkeyPatch.setattr` 与 `unittest.mock.patch` 都会对目标串取
    最长可导入前缀去 `import_module`，所以 `plugins…sources.parsers.http_util.http_get_json` 这种串
    **运行期真的会执行父包壳**，删壳当场 AttributeError（与 `import a.b.c` 同害）。
    旧版只认 `import_module`/`__import__` 两个口 ⇒ S101 反假零主锁里 `sources/parsers` 一枚恒报 0：
    实测全树对它**只剩这一种串形态引用**（`tests/test_auditfix_subscriptions_capabilities.py:317`）。
    只认**位置首参**的字面量串：`target=` 关键字形、以及变量拼接的动态目标一律返回 None ⇒ 不计，
    口径与 `importlib` 那条一字同构 —— 本函数只补漏认的入口，不放宽任何既有判据、无白名单。
    """
    if not isinstance(node, ast.Call) or not node.args:
        return None
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else (func.id if isinstance(func, ast.Name) else None)
    if name not in {"setattr", "patch"}:
        return None
    arg = node.args[0]
    if not isinstance(arg, ast.Constant) or not isinstance(arg.value, str):
        return None
    return arg.value


@functools.lru_cache(maxsize=1)
def _build_reference_index() -> dict[str, frozenset[str]]:
    """全树引用索引构建口（TX172 R2 根修：**只有成功结果进缓存**）。

    旧版把 `(index, errors)` 二元组一起进缓存 ⇒ 一发瞬时撕裂读就把「错误＋缺那枚文件的半截
    索引」钉死在整个进程生命周期，文件改合法后同进程复调仍抛（TX170 §3-①：本波并发写者改的
    正是 `scripts/**`+`tests/**`，误伤半径＝全进程）。`functools.lru_cache` 的既有语义是
    **异常不进缓存** —— `domains/render/card_render/bridge.py::_load_icon_asset` 与
    `tests/test_bridge_icon_cache.py` 已把该语义当契约用，本件复用同一把尺、不造第二把量具。
    TX172 只删了「错误进缓存」这一形；TX191 再补**撕裂读完整性判据** —— 每枚在架文件走
    `_read_source_with_integrity`（双读比对 size+sha256），半截读 ⇒ `ReferenceIndexUnstable` 上抛
    且同样不入缓存。原「不可解析 ⇒ `ReferenceIndexError`」那条 fail-closed 口径保持不变。
    """
    counts: dict[str, set[str]] = {}
    errors: list[str] = []
    for path in REPO_ROOT.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel.split("/")[-1] == "__pycache__" or set(rel.split("/")) & ppc.SKIP_DIR_NAMES:
            continue
        if not _reference_index_scopes(rel):
            continue
        try:
            # 双读完整性校验读入（TX191）：撕裂读抛 ReferenceIndexUnstable（RuntimeError 子辈，
            # 不被下面 except 捕获）→ 整个 _build_reference_index 当场中断且**不入 lru_cache**；
            # 真正的「读不出/不是合法源码」(OSError/UnicodeDecodeError/SyntaxError/ValueError) 仍归
            # errors → 末尾 ReferenceIndexError（口径一字未动）。
            tree = ast.parse(_read_source_with_integrity(path, rel))
        except (SyntaxError, UnicodeDecodeError, ValueError, OSError) as exc:
            errors.append(f"{rel}:{getattr(exc, 'lineno', None) or 1}: {type(exc).__name__}: {exc}")
            continue
        pkg = _referrer_package_dotted(rel)
        touched: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    touched.add(a.name)
                    touched.add(a.name.rsplit(".", 1)[0] if "." in a.name else a.name)
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0:
                    base = node.module or ""
                else:
                    segs = pkg.split(".") if pkg else []
                    up = node.level - 1
                    if up > len(segs):
                        errors.append(f"{rel}:{node.lineno}: 相对导入 level={node.level} 越过顶层，点号目标不可解析")
                        continue
                    anchor = ".".join(segs[: len(segs) - up])
                    base = ".".join(p for p in (anchor, node.module) if p)
                if not base:
                    continue
                touched.add(base)
                touched.add(f"{base}.*")
                for a in node.names:
                    if a.name != "*":
                        touched.add(f"{base}.{a.name}")
            else:
                # 两个「把点号串交给运行期导入机器」的入口共用同一累加口径（同 `import a.b.c`）：
                # `importlib.import_module`/`__import__` 与 monkeypatch/mock 的点号目标串。
                literal = _importlib_literal(node) or _patch_target_literal(node)
                if literal:
                    touched.add(literal)
                    touched.add(literal.rsplit(".", 1)[0] if "." in literal else literal)
        for name in touched:
            counts.setdefault(name, set()).add(rel)
    if errors:
        raise ReferenceIndexError(
            "引用面不可解析＝fail-closed（禁止把「读不到」当「没人引用」）: " + "; ".join(errors)
        )
    return {k: frozenset(v) for k, v in counts.items()}


def reference_index() -> dict[str, frozenset[str]]:
    """全仓引用索引 `{点号名: 去重引用文件集合}` —— 唯一取数口，门/自测/`--report` 同源。

    对 S34 旧版的加严（全在同一码路上，禁第二份扫描器）：
    - 值从 `int` 升为**文件集合** —— 包垫片按点号前缀并集数文件，必须能跨键去重（旧版 int 只能 `max` 近似）；
    - 相对导入（实测根 `__init__.py:3740 from .policy import (`）按引用方所在包解析成绝对点号名 ——
      旧版只记裸名 `policy`，生产对包垫片的 dotted 引用整体隐形；
    - `importlib.import_module("…")` / `__import__("…")` 的字面量目标入册（同 `import a.b.c` 口径）；
    - `monkeypatch.setattr("a.b.c", …)` / `mock.patch("a.b.c")` 的字面量点号目标同样入册
      （`_patch_target_literal`，与上一条同一把尺 —— 都是「把点号串交给运行期导入机器」，
      父包壳运行期必被执行；TX319 补此形以根修 S87 Critical-1 的残余恒零）；
    - 引用面两类坏读各归各的门，都不许静默退化成「零引用」（TX191 把 :276 的旧散文兑现为实况）：
      ① **读不出/不是合法源码**（语法坏、字节坏、文件消失）⇒ `ReferenceIndexError` 点名 `文件:行`；
      ② **读得动、甚至 parse 成功、但读到半截**（撕裂读，两遍比对 size+sha256 不一致）⇒
         `ReferenceIndexUnstable` 点名该文件；
      两者都**只在成功完整构建时**才进 `lru_cache`（异常天然不入缓存，TX172 R2 根修的同一把尺）
      ⇒ 一发坏读/撕裂读都不钉死整进程，文件稳定后同进程复调即恢复。
    - 返回**新构造的 dict 浅拷贝**（值本就是不可变 `frozenset`）：调用方增删键改不动缓存本体，
      杜绝「拿返回值 .pop() 一下就把共享索引削薄」这条自伤路。
    """
    return dict(_build_reference_index())


def _require_complete_reference_index() -> dict[str, frozenset[str]]:
    """台账写入侧的「本轮读是否完整」闸门 —— 只认 `_build_reference_index` 的**成功完整**返回。

    坏读两类都会在此抛（从而让 `render_ledger` 在建 `ceiling` 之前中断、`--write-ledger` 不落盘）：
    - `ReferenceIndexUnstable`：撕裂读（双读 size+sha256 不一致），半截索引不可信；
    - `ReferenceIndexError`：某引用面文件读不出/不是合法源码。
    成功返回即意味**整轮是完整一致读**（lru_cache 只在无异常时缓存）——这是「可安全 `min()` 降账」的
    唯一凭据。与 `reference_index()` 的分工：那个面向外部只读取数、返回**新拷贝**；本个面向写账、
    直接把已验证的缓存对象交给调用方**只读**使用（`computed_refs` 内部不再改它）。
    """
    return _build_reference_index()


def shim_target_dotted(shim_rel: str) -> str:
    """垫片被引用的**点号目标**：包垫片（`<pkg>/__init__.py`）的目标是父包 `<pkg>`，
    普通垫片是其模块点号名。单一推导口 —— `computed_refs()` 与 `cross_check` ②b 补腿同源共用。"""
    dotted = _rel_to_dotted(shim_rel)
    if dotted.endswith(".__init__"):
        return dotted[: -len(".__init__")]
    return dotted


def _referencing_files(target: str, index: dict[str, frozenset[str]]) -> frozenset[str]:
    """命中 `target` 本名、`target.*` 或点号前缀 `target.<任何>…` 的去重文件集合。"""
    prefix = target + "."
    star = f"{target}.*"
    files: set[str] = set()
    for key, owners in index.items():
        if key == target or key == star or key.startswith(prefix):
            files |= owners
    return frozenset(files)


def computed_refs(shim_rel: str, index: dict[str, frozenset[str]] | None = None) -> int:
    """某个垫片 rel path 的引用方数 = 现算索引里命中其点号目标的去重文件数。

    包垫片（`__init__.py`）按**父包点号前缀**计：凡引用父包本体或其任何子模块
    （`from plugins…sender import X` / `…sender.onebot import Y` / `importlib.import_module("…sender…")` /
    `monkeypatch.setattr("…sender.http_util.X", …)`，含由相对导入解析出的绝对点号名）的文件都在数 —— 这些写法运行期都会执行包壳，删壳即打坏导入图。
    旧实现拿 `<pkg>.__init__` 点号名去查索引 ⇒ 对七枚包垫片**恒报 0**（S87 Critical-1 假零）。
    同一函数、单一取数口，包垫片不走第二条码路；计数异常 ⇒ fail-closed 点名 `文件:行`（同 S94 哲学）。
    """
    index = reference_index() if index is None else index
    return len(_referencing_files(shim_target_dotted(shim_rel), index))


# --------------------------------------------------------------------------
# 三态现算
# --------------------------------------------------------------------------
def three_states() -> dict[str, Any]:
    """域外 → 已归类 / 待搬迁 / 待退役(垫片)，互斥且覆盖整个域外集。

    **待搬迁桶内部的三态拆分（S165 · S160 方案 A）**：旧判据只问「domains 之外 + 被某 fid 认领」，
    于是把「fid 把家声明在 domains 之外」的基础件（`control_plane/**` 整块、根 `__init__.py`）也算成
    待归位件 —— S160 现算证伪：46 枚里真可搬 **0**。现按**声明落点是否落进 domains 白名单**分三态
    （判据与 G-P1 同源，见 `ppc.relocate_state_of`），随 `relocate_split` / `movable` 两个新键输出。
    顶层三态的桶账**一字未动**：`relocate` 仍是「被认领的域外件」全量（和锁 146/184、152/190 与
    三态分区恒等式都不因此改变），只是**派单可读的活性数**降为 `movable`（真可搬），假阳归位为具名形态。

    `marker_blind`（S118 新增）是**只读附账**：命中垫片记号却没进「待退役」的域外件点名清单，
    不参与三态归属、不进任何恒等式、不改任何计数；它唯一的作用是把"读点认不出的再导出形态"
    从静默丢件变成面上可见。塌陷时（有记号命中却零合格垫片）由 `_assert_no_detection_collapse`
    当场抛 `ShimDetectionCollapsed`，绝不出一张看起来"垫片已清零"的账。
    """
    claims = ppc.flatten_claims(ppc.feature_impl_paths())
    outside = outside_py()
    shims = detect_shims(outside)
    blind = blind_marker_hits(outside)
    _assert_no_detection_collapse(outside, shims, blind)  # 塌陷锁：只抛不改账（枚数/桶账一字不动）
    shim_paths = set(shims)
    relocate = [r for r in outside if r not in shim_paths and ppc.claiming_fids(r, claims, semantic="prefix")]
    classified = [r for r in outside if r not in shim_paths and r not in set(relocate)]
    split = ppc.relocate_split(sorted(relocate))
    return {
        "outside": len(outside),
        "retire_shims": sorted(shim_paths),
        "relocate": sorted(relocate),
        "classified": sorted(classified),
        "relocate_split": split,
        "movable": split["movable"],
        "marker_blind": blind,
        "counts": {"retire_shims": len(shim_paths), "relocate": len(relocate), "classified": len(classified)},
        "relocate_counts": {state: len(paths) for state, paths in split.items()},
    }


# --------------------------------------------------------------------------
# 账装载（AST 静态读声明源，不 import 插件包，避免拖起 NoneBot 初始化）
# --------------------------------------------------------------------------
def load_ledger_rows(ledger_source: str | None = None) -> list[dict[str, Any]]:
    """解析 `board_shim_ledger.py` 的 `SHIM_ROWS`：每条 = 元组 (path, canonical, refs)。

    台账腿完整性（TX201 任务①）：① 从磁盘读时走 `_read_ledger_source_with_integrity()`（双读撕裂校验）；
    ② `ast.parse` 语法坏（含撕裂截断成非法前缀）⇒ `LedgerReadIncomplete`；③ 解析出**零行**
    （找不到 `SHIM_ROWS` 声明、或 `SHIM_ROWS = ()`）⇒ `LedgerReadIncomplete`。三形一律抛，
    绝不当「没有历史」放行 —— 那会让 `render_ledger` 里 `min(prior_refs, live)` 的 `prior_refs` 退化成 `{}`、
    每枚走首次入账分支、`ceiling=live` 免审批抬上限并持久化（正是 TX199 F-1 兑现的洞）。
    """
    source = _read_ledger_source_with_integrity() if ledger_source is None else ledger_source
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise LedgerReadIncomplete(f"台账语法坏/撕裂截断 ⇒ 解析失败，本账拒读：{exc}") from exc
    rows: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        targets: list[ast.expr]
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == "SHIM_ROWS" for t in targets):
            continue
        # 语义定死：`None` 在这里**只有一种含义 = 读不到**（`ast.AnnAssign` 可以「只声明不赋值」，
        # 其 `.value` 为 None；字面量写成 `None` 同样是「这张账没内容」）。两者一律计入异常并拒读，
        # 绝不静默 continue —— 静默跳过会把「SHIM_ROWS 被改成光声明 / 被清成 None」读成**空账**，
        # 于是 `cross_check` ①（漏记现算垫片）永远看不见，门在账被清空的瞬间正好变绿。
        value: ast.expr | None = node.value
        if value is None:
            raise AssertionError("SHIM_ROWS 声明缺字面量赋值 = 取数口读不到，本账拒读（拒读≠空账放行）")
        try:
            raw = ast.literal_eval(value)  # SHIM_ROWS 必须是纯字面量元组，禁任何计算/调用
        except (ValueError, SyntaxError):
            raise AssertionError("SHIM_ROWS 不是纯字面量元组 = 有人手抄/加了计算，本账拒读")
        if raw is None:
            raise AssertionError("SHIM_ROWS 字面量为 None = 账没内容，本账拒读（放行等于漏记全表隐形）")
        # 形状也属「非法字面量」：非三元组元组、含非字符串路径/非整数 refs 一律拒读并点名声明行
        # （S101 fail-closed 加严，S94 同哲学 —— 旧写法会让 `item[0]` 抛 TypeError 崩在深处不点名）。
        if not isinstance(raw, tuple) or not all(
            isinstance(item, tuple)
            and len(item) == 3
            and isinstance(item[0], str)
            and isinstance(item[1], str)
            and isinstance(item[2], int)
            for item in raw
        ):
            raise AssertionError(
                "SHIM_ROWS 字面量形状非法（须为 (str, str, int) 三元组的元组）= 声明含非法字面量，"
                f"本账拒读：{LEDGER_PY.name}: 声明行 {node.lineno}"
            )
        for item in raw:
            path, canonical, refs = item[0], item[1], item[2]
            rows.append({"path": path, "canonical": canonical, "refs": int(refs)})
    if not rows:
        # 空账/解析零行 ⇒ 抛，不许当「没有历史」（TX201 任务①）。合法「无历史」只有一种形态：
        # 台账文件根本不存在（render_ledger 以 LEDGER_PY.exists() 分诊、传 None 走首建分支，不经此口）。
        raise LedgerReadIncomplete(
            "台账解析出零行（找不到 SHIM_ROWS 声明或 SHIM_ROWS=()）= 空账/撕裂截断，"
            "本账拒读；放行会把 prior_refs 读成 {} 使每枚抬到 live 上限并持久化"
        )
    return rows


def load_ledger_baselines(ledger_source: str | None = None) -> dict[str, int]:
    source = LEDGER_PY.read_text(encoding="utf-8") if ledger_source is None else ledger_source
    names = set(LEDGER_BASELINE_NAMES)
    data = ppc._read_literals(source, names)
    missing = sorted(names - set(data))
    assert not missing, f"board_shim_ledger.py 缺基线 {missing}——取数口不接受静默补空值"
    return {k: int(data[k]) for k in names}


#: 域外「未落地」两态（和锁的锁对象）；「已归类」不计 —— 它不是待办，是已定性归属。
UNLANDED_STATES: tuple[str, ...] = ("retire_shims", "relocate")

#: 四枚基线字面量（名字即契约；`load_ledger_baselines` 缺一即拒读，不许静默补空）。
LEDGER_BASELINE_NAMES: frozenset[str] = frozenset(
    {"SHIM_RETIRE_BASELINE", "RELOCATE_BASELINE", "UNLANDED_SUM_BASELINE", "OUTSIDE_BASELINE"}
)


def previous_baselines(ledger_source: str | None = None) -> dict[str, int]:
    """**宽容**读既有基线，仅供 `--write-ledger` 做"只准降"的钳制用。

    与 `load_ledger_baselines` 的分工是刻意的：执法口缺基线必须红（不许把缺失当 0 放行），
    而生成器面对 S34 首版只有两枚基线的旧账要能迁移（缺的那枚 = 无历史值 = 取现算值）。

    台账腿完整性（TX201 任务①）：从磁盘读走双读撕裂校验；解析坏/撕裂 ⇒ `LedgerReadIncomplete`；
    **一枚基线都读不到**（`{}`）⇒ `LedgerReadIncomplete` —— 「空账」绝不退化成「全取现算值」。
    个别基线缺失仍按迁移语义放行（返回少于 4 枚），只有整体读空才拒。合法「无历史」唯一形态是
    台账文件不存在，由 `render_ledger` 的 `LEDGER_PY.exists()` 分流，不经过本函数。
    """
    source = _read_ledger_source_with_integrity() if ledger_source is None else ledger_source
    try:
        data = ppc._read_literals(source, set(LEDGER_BASELINE_NAMES))
    except SyntaxError as exc:
        raise LedgerReadIncomplete(f"台账语法坏/撕裂截断 ⇒ 基线解析失败，本账拒读：{exc}") from exc
    except ppc.PlacementDeclarationError as exc:
        raise LedgerReadIncomplete(f"台账基线非可静态求值字面量 ⇒ 本账拒读：{exc}") from exc
    result = {k: int(v) for k, v in data.items() if isinstance(v, int)}
    if not result:
        raise LedgerReadIncomplete(
            "既有基线一枚都读不到 = 空账/无历史，本账拒读（放行会把四枚基线全刷成现算值＝变相升/降基线）"
        )
    return result


# --------------------------------------------------------------------------
# refs 上限上调的**显式审批通道**（S155 · S147 机制缺口根修）
# --------------------------------------------------------------------------
#: 审批状态件路径（数据件，**由 owner 手工维护**；本席与 `--write-ledger` 都不创建它）。
#: 缺失＝无任何审批 ⇒ 默认「只降」钳生效（11 枚上限纹丝不动、门诚实红，属预期不是故障）。
#: 口径「临时停用要自动到期」：每枚审批必带 `expiry`，过期即失效、无人工回滚。
SHIM_REFS_APPROVALS_PATH = REPO_ROOT / "scripts" / "shim_refs_approvals.json"


def _approval_not_expired(expiry: Any, now: datetime) -> bool:
    """`expiry` 可解析且晚于 `now` ⇒ 未过期。缺失/空白/格式非法一律判**已过期**（fail-closed 不批）。"""
    if not isinstance(expiry, str) or not expiry.strip():
        return False
    raw = expiry.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)  # 无时区的时间戳一律按 UTC 解释（确定化，不随机器 locale 漂移）
    return dt > now


def approved_refs_paths(
    detected: dict[str, dict[str, Any]],
    approvals_path: Path | None = None,
) -> set[str]:
    """现算哪些垫片的 refs 上限被**显式审批**允许上调（返回合格 path 集合，全内存判定）。

    审批状态件 = JSON：`{"approvals": [{"path","approved_by","reason","expiry"}, ...]}`。
    逐枚**同时**满足四条件才算有效审批，任一不满足 ⇒ 该枚不批 ⇒ 仍走「只降」钳 ⇒ 门诚实红：
    - `path` 命中当前**现算合格垫片**（`detected`）——不存在 / 非垫片 / 未落地的审批一律不生效（fail-closed 拒批）；
    - `approved_by`、`reason` 均为非空字符串（署名与理由缺一不批）；
    - `expiry` 可解析且**未过期**（口径「临时停用要自动到期」，过期自动失效）；
    - 整体 JSON 读不到 / 形状非法 ⇒ **无任何审批生效**（fail-closed，绝不因文件坏而放宽）。
    """
    path = SHIM_REFS_APPROVALS_PATH if approvals_path is None else approvals_path
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    entries = data.get("approvals") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return set()
    now = datetime.now(timezone.utc)
    approved: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        p = entry.get("path")
        if not isinstance(p, str) or p not in detected:
            continue
        for field in ("approved_by", "reason"):
            value = entry.get(field)
            if not (isinstance(value, str) and value.strip()):
                break
        else:
            if _approval_not_expired(entry.get("expiry"), now):
                approved.add(p)
    return approved


def exemption_count() -> int:
    """G-P2 豁免账条数（只读取数，本席**一字不改**它）：与三态之和同门记账，防「豁免搬家」洗账。"""
    return len(ppc.load_placement()["G_P2_EXEMPT"])


def coupled_ratchet(
    counts: dict[str, int],
    baselines: dict[str, int],
    *,
    outside: int | None = None,
) -> dict[str, Any]:
    """「锁加数不锁加项」的唯一判据（纯函数 —— 门、`--check`、`--report`、注毒自测共用）。

    硬锁（单调下降，任何方向都不许升）：
    - `unlanded_within`：`待退役 + 待搬迁 <= UNLANDED_SUM_BASELINE`
    - `outside_within`：`三态之和 <= OUTSIDE_BASELINE`
    单态条件（由和锁必然推出的耦合算术，只作归因与判别）：
    - `retire_rise_covered` / `relocate_rise_covered`：某态高于基线的部分 <= 另一态低于基线的部分
    """
    retire = counts["retire_shims"]
    relocate = counts["relocate"]
    unlanded_now = sum(counts[name] for name in UNLANDED_STATES)
    unlanded_baseline = baselines["UNLANDED_SUM_BASELINE"]
    retire_base = baselines["SHIM_RETIRE_BASELINE"]
    relocate_base = baselines["RELOCATE_BASELINE"]
    retire_rise = max(0, retire - retire_base)
    relocate_rise = max(0, relocate - relocate_base)
    retire_fall = max(0, retire_base - retire)
    relocate_fall = max(0, relocate_base - relocate)
    verdict: dict[str, Any] = {
        "unlanded_now": unlanded_now,
        "unlanded_baseline": unlanded_baseline,
        "retire_now": retire,
        "relocate_now": relocate,
        "retire_baseline": retire_base,
        "relocate_baseline": relocate_base,
        "retire_rise": retire_rise,
        "relocate_rise": relocate_rise,
        "retire_fall": retire_fall,
        "relocate_fall": relocate_fall,
        "unlanded_within": unlanded_now <= unlanded_baseline,
        "retire_rise_covered": retire_rise <= relocate_fall,
        "relocate_rise_covered": relocate_rise <= retire_fall,
    }
    if outside is not None:
        verdict["outside_now"] = outside
        verdict["outside_baseline"] = baselines["OUTSIDE_BASELINE"]
        verdict["outside_within"] = outside <= baselines["OUTSIDE_BASELINE"]
    verdict["ok"] = all(
        verdict[key]
        for key in ("unlanded_within", "retire_rise_covered", "relocate_rise_covered", "outside_within")
        if key in verdict
    )
    return verdict


# --------------------------------------------------------------------------
# 一致性核对（各把锁的纯函数，门与自测共用；喂合成数据即可注毒，不碰树）
# --------------------------------------------------------------------------
def cross_check(
    rows: list[dict[str, Any]],
    detected: dict[str, dict[str, Any]],
    *,
    refs_fn=None,
    index: dict[str, frozenset[str]] | None = None,
) -> dict[str, list[str]]:
    """把「账上登记」与「现算检测」对账。返回各类问题清单（全空 = 账一致）。

    ① `missing_registration`：现算检测到垫片却未登记（漏记 ⇒ 红）。
    ② `not_a_shim`：登记了 path 但该文件现在存在且**不是**合格垫片（非垫片登记成垫片 ⇒ 红）。
       path 不存在视为已退役（进展，不算违规）—— 但「已退役被写回引用」由 ②b 补腿执法。
    ②b `retired_re_referenced`：S101 补腿（S87 Critical-2）—— 对「已登记但盘上不存在」的垫片，
       反查其点号目标（包垫片=父包前缀，含相对导入解析出的绝对名、importlib 字面量与
       monkeypatch/mock 的点号目标串）是否重回
       `reference_index()`；有 ⇒ 判红并点名是谁在引。旧版对不存在路径**无条件放行**，
       「已删垫片被写回引用」这一形态只由导入图执法、不由账执法。
    ③ `canonical_missing`：账上真身路径在盘上不存在（真身不存在 ⇒ 红）。
    ④ `refs_over_ceiling`：现算引用方数 > 账上登记上限（新增旧写法 ⇒ 红；迁走变小放行）。
    ⑤ `canonical_mismatch`：账上真身 ≠ 现算派生真身（**手抄一个也存在但不对的指针** ⇒ 红；
       S52 补腿 —— ③ 只查存在性，洗不掉"指到另一枚真实文件"的手抄账）。
    """
    refs_fn = computed_refs if refs_fn is None else refs_fn
    registered = {r["path"] for r in rows}
    missing_registration = sorted(set(detected) - registered)
    not_a_shim = sorted(
        r["path"] for r in rows
        if (REPO_ROOT / r["path"]).exists() and r["path"] not in detected
    )
    retired_re_referenced: list[str] = []
    retired_paths = sorted(
        r["path"] for r in rows if not (REPO_ROOT / r["path"]).exists()
    )
    if retired_paths:
        idx = reference_index() if index is None else index
        for path in retired_paths:
            owners = _referencing_files(shim_target_dotted(path), idx)
            if owners:
                retired_re_referenced.append(f"{path} ← 被引用方 {'、'.join(sorted(owners))}")
    canonical_missing = sorted(
        r["path"] for r in rows
        if not (REPO_ROOT / r["canonical"]).exists()
    )
    refs_over_ceiling = sorted(
        r["path"] for r in rows
        if refs_fn(r["path"]) > r["refs"]
    )
    canonical_mismatch = sorted(
        r["path"] for r in rows
        if r["path"] in detected and r["canonical"] != detected[r["path"]]["canonical"]
    )
    return {
        "missing_registration": missing_registration,
        "not_a_shim": not_a_shim,
        "retired_re_referenced": retired_re_referenced,
        "canonical_missing": canonical_missing,
        "refs_over_ceiling": refs_over_ceiling,
        "canonical_mismatch": canonical_mismatch,
    }


# --------------------------------------------------------------------------
# --write-ledger：用 AST/grep 现算生成账（禁手抄真身路径）
# --------------------------------------------------------------------------
def clamped_baselines(previous: dict[str, int], states: dict[str, Any]) -> dict[str, int]:
    """四枚基线一律「只准降」—— `--write-ledger` 抬不动任何一本（P-22 裁定 B＝变相升基线，禁止）。

    - 每枚取 `min(既有值, 现算值)`：现算值高于既有基线时**保留既有值**，回升由 `--check` 与门当场喊红，
      生成器绝不代洗（S34 首版直接写现算值 ⇒ 重记一次就把基线抬上去，是本函数要堵的洞）。
    - `UNLANDED_SUM_BASELINE` 另钳到两枚单态参照点之和以内 —— 这正是「单态上升必被抵掉」
      成为**定理**（而非第二道更松的门）的前提，门内有同构结构锁 `test_sum_baseline_is_no_looser_...`。
    """

    def only_down(name: str, current: int) -> int:
        prior = previous.get(name)
        return int(current) if prior is None else min(int(prior), int(current))

    retire = only_down("SHIM_RETIRE_BASELINE", len(states["retire_shims"]))
    relocate = only_down("RELOCATE_BASELINE", len(states["relocate"]))
    unlanded = min(
        only_down("UNLANDED_SUM_BASELINE", len(states["retire_shims"]) + len(states["relocate"])),
        retire + relocate,
    )
    outside = only_down("OUTSIDE_BASELINE", states["outside"])
    return {
        "SHIM_RETIRE_BASELINE": retire,
        "RELOCATE_BASELINE": relocate,
        "UNLANDED_SUM_BASELINE": unlanded,
        "OUTSIDE_BASELINE": outside,
    }


def render_ledger(states: dict[str, Any], *, approvals_path: Path | None = None) -> str:
    """生成账体。**关键（S155 根修 S147 机制缺口）**：逐枚 `refs` 上限与四枚基线一样「只准降」——

    默认 `refs = min(既有上限, 现算真值)`（迁走调用方让数变小 = 合法进展；行减少 = 合法裁剪）。
    唯一例外是经 `approved_refs_paths`（显式审批状态件、带 `approved_by/reason/expiry`、过期自动失效）
    放行的枚，才取现算真值。这样**「裁滞后行」与「抬 refs 上限」被拆开**：
    无审批跑 `--write-ledger` ⇒ 11 枚被 S101 假零修复顶高的上限纹丝不动（门 `refs_over_ceiling` 继续红），
    但那 38 枚干净退役的滞后行照样能删（这才是可分离的正解，而非 §0 六禁的「靠调上限糊掉」）。

    **写入侧防线（TX191 任务②）**：`min(既有, 现算)` 降账前，先经 `_require_complete_reference_index()`
    取一份**已确认完整**的引用索引（撕裂读会在 `_build_reference_index` 内抛 `ReferenceIndexUnstable`）。
    取不到完整读 ⇒ 本函数在算任何 `ceiling` 之前就抛出 ⇒ `main` 的写盘步骤根本不执行
    ⇒ **宁可保留旧账，也绝不让一发撕裂读把某枚 refs 上限钉成 0 再持久化进退役台账**。
    绕行面自查（TX199 会打）：`lru_cache` 一旦缓存过完整读，后续同进程只复用该份、不再重读，
    「先完整后撕裂」改不动已缓存的索引；而若本轮首读即撕裂则抛错不入缓存 —— 两个方向都堵。

    **台账腿防线（TX201 任务①②，补上 TX191 只装了引用腿那一半）**：`min()` 的另一操作数 `prior_refs`
    旧版走裸 `LEDGER_PY.read_text` + 宽容解析，喂空账/撕裂账 ⇒ `prior_refs={}` ⇒ 每枚走首次入账分支、
    `ceiling=live` 免审批抬上限并持久化。现在 min() 之前先经 `_read_ledger_source_with_integrity()`（双读撕裂）
    + `load_ledger_rows`/`previous_baselines`（空账/零行/语法坏 ⇒ 抛）取一份「已确认完整 + 非空」的既有账，
    拿不到就在此抛 ⇒ 与引用腿同向：两个方向（引用腿撕、台账腿撕/空）都堵，绝不落一份被抬 live 或钉 0 的账。
    """
    index = _require_complete_reference_index()  # 引用腿完整读凭据：拿不到（撕裂/坏读）就在此抛，不往下写账
    detected = {rel: detect_shims([rel])[rel] for rel in states["retire_shims"]}
    # 台账腿完整读凭据（TX201 任务②）：min() 降账前先把既有账读成「已确认完整 + 非空」——双读撕裂校验
    # 走一次，同一份文本喂给 load_ledger_rows/previous_baselines（不再各自重读，避免两读之间再撕裂）。
    # 撕裂/空账/语法坏 ⇒ 在 `_read_ledger_source_with_integrity` 或下游两函数内抛 LedgerReadIncomplete
    # ⇒ 本函数在算任何 ceiling 之前中断 ⇒ main 不落盘、保留旧账（宁可旧值也不写一份被钉 0/抬 live 的账）。
    ledger_source = _read_ledger_source_with_integrity() if LEDGER_PY.exists() else None
    prior_rows = load_ledger_rows(ledger_source) if ledger_source is not None else []
    bl = clamped_baselines(
        previous_baselines(ledger_source) if ledger_source is not None else {}, states
    )
    retire_baseline = bl["SHIM_RETIRE_BASELINE"]
    relocate_baseline = bl["RELOCATE_BASELINE"]
    unlanded_baseline = bl["UNLANDED_SUM_BASELINE"]
    outside_baseline = bl["OUTSIDE_BASELINE"]
    prior_refs = {r["path"]: r["refs"] for r in prior_rows}
    approved = approved_refs_paths(detected, approvals_path)
    rows = []
    for rel in sorted(detected):
        canonical = detected[rel]["canonical"]
        live = computed_refs(rel, index=index)
        if rel in approved:
            ceiling = live  # 显式审批放行：取现算真值（唯一可升路径，署名+理由+未过期）
        elif rel in prior_refs:
            ceiling = min(prior_refs[rel], live)  # 只准降：既有上限是天花板，绝不被现算顶高
        else:
            ceiling = live  # 首次入账：无既有上限可钳，非「上调」（①漏记腿本就强制登记现算垫片）
        rows.append(f'    ("{rel}",\n     "{canonical}",\n     {ceiling}),')
    body = "\n".join(rows) if rows else ""
    header = (
        '"""垫片「待退役」第二本账（声明源 · 与 `G_P2_EXEMPT` 并列 · 解 P-16 A 案）。\n\n'
        "本文件由 `scripts/shim_retirement_census.py --write-ledger` 现算生成，**请勿手改**：\n"
        "- 每枚 `path` 是域外垫片，`canonical`（真身）与 `refs`（引用方数上限）均由 AST/grep 现算，\n"
        "  **禁手抄真身路径**（改指针 = 让 `--check` 与门的 ③④⑤ 当场红）。\n"
        "- 退役一枚垫片（迁完调用方后删除）⇒ 重跑 `--write-ledger`，`SHIM_RETIRE_BASELINE` 只准降。\n"
        "- 逐枚 `refs` 上限同样**只准降**（`--write-ledger` 默认 `min(既有, 现算)`，抬不动它）：\n"
        "  想上调某枚上限，唯一通道是 `scripts/shim_refs_approvals.json` 里的显式审批\n"
        "  （`{path, approved_by, reason, expiry}`，过期自动失效）；无审批 ⇒ 上限不动、`refs_over_ceiling` 继续红。\n"
        "  这把「删滞后行（正当进展）」与「抬上限（糊红）」拆开，见 S147 机制缺口 / S155。\n"
        "- `SHIM_ROWS` 必须是纯字面量元组（取数口用 `ast.literal_eval` 读，任何计算/调用都拒读）。\n"
        "- 方向锁是**加数不是加项**（P-22）：硬锁 = `UNLANDED_SUM_BASELINE`（待搬迁＋待退役）与\n"
        "  `OUTSIDE_BASELINE`（三态之和）；单态基线只作耦合算术参照，某态上升须另一态等额或更多下降。\n"
        "  四枚基线一律只准降，`--write-ledger` 也抬不动它们。\n\n"
        "口径、判据、三态定义全在算口 `scripts/shim_retirement_census.py` 顶注与 `PARKED.md` P-16/P-22。\n"
        '"""\n\n'
        "from __future__ import annotations\n\n"
        "#: 每条 = (垫片 path, 真身 path, 引用方数上限)。字段顺序即契约，勿加派生表达式。\n"
        "SHIM_ROWS: tuple[tuple[str, str, int], ...] = (\n"
    )
    tail = (
        ")\n\n"
        f"#: 待退役(垫片) 现算快照参照点（手写字面量 · 只准降；上升仅在待搬迁等额或更多下降时可放行）。\n"
        f"SHIM_RETIRE_BASELINE = {retire_baseline}\n"
        f"#: 待搬迁 现算快照参照点（手写字面量 · 只准降；上升仅在待退役等额或更多下降时可放行）。\n"
        f"RELOCATE_BASELINE = {relocate_baseline}\n"
        f"#: 【硬锁】域外未落地总量 = 待搬迁＋待退役 之和（手写字面量 · 单调下降，锁加数不锁加项）。\n"
        f"UNLANDED_SUM_BASELINE = {unlanded_baseline}\n"
        f"#: 【硬锁】三态之和 = 域外全量（手写字面量 · 单调下降；正当认领只改分配不改全量）。\n"
        f"OUTSIDE_BASELINE = {outside_baseline}\n"
    )
    return header + body + ("\n" if body else "") + tail


# --------------------------------------------------------------------------
# 现算总账与打印（--report 与门共用同一 compute）
# --------------------------------------------------------------------------
def compute() -> dict[str, Any]:
    states = three_states()
    detected = {rel: detect_shims([rel])[rel] for rel in states["retire_shims"]}
    rows = load_ledger_rows() if LEDGER_PY.exists() else []
    problems = cross_check(rows, detected) if rows else {}
    baselines = load_ledger_baselines() if LEDGER_PY.exists() else {}
    ratchet = (
        coupled_ratchet(states["counts"], baselines, outside=states["outside"])
        if baselines
        else {}
    )
    return {
        "states": {
            "outside": states["outside"],
            "retire_shims": states["counts"]["retire_shims"],
            "relocate": states["counts"]["relocate"],
            "classified": states["counts"]["classified"],
            "relocate_split": states["relocate_counts"],
            "movable": len(states["movable"]),
        },
        "ledger_rows": len(rows),
        "baselines": baselines,
        "ratchet": ratchet,
        "exemption": {"count": exemption_count()},
        "cross_check": problems,
        # S118 只读附账：命中记号却未进待退役的盲区点名（不进三态恒等式、不参与任何降锁算术）。
        "marker_blind": states["marker_blind"],
    }


def report_lines(data: dict[str, Any]) -> list[str]:
    s = data["states"]
    split = s.get("relocate_split") or {}
    lines = [
        f"域外 py（不在 domains/ 下）: {s['outside']}",
        f"  三态: 已归类 {s['classified']} | 待搬迁 {s['relocate']} | 待退役(垫片) {s['retire_shims']}",
    ]
    if split:
        # 派单口径：待搬迁是**桶账**，活性数是「真可搬」；把基础设施假阳点名，别按 46 派搬迁席（S160 教训）。
        lines.append(
            "  待搬迁拆分: "
            + " | ".join(
                f"{ppc.RELOCATE_STATE_LABELS[state]} {split.get(state, 0)}"
                for state in ppc.RELOCATE_STATES
            )
            + f" —— 真可搬 {s.get('movable', split.get('movable', 0))} 枚才是搬迁面"
        )
    r = data["ratchet"]
    if r:
        lines.append(
            f"  硬锁·未落地之和(待搬迁＋待退役) {r['unlanded_now']}/基线 {r['unlanded_baseline']} "
            f"({'OK' if r['unlanded_within'] else 'RISE!'})"
        )
        lines.append(
            f"  硬锁·三态之和(域外全量) {r['outside_now']}/基线 {r['outside_baseline']} "
            f"({'OK' if r['outside_within'] else 'RISE!'})"
        )
        lines.append(
            f"  单态参照: 待退役 {r['retire_now']}/参照 {r['retire_baseline']} "
            f"(升 {r['retire_rise']}·被另一态降 {r['relocate_fall']} 抵 → "
            f"{'OK' if r['retire_rise_covered'] else '未抵消!'}), "
            f"待搬迁 {r['relocate_now']}/参照 {r['relocate_baseline']} "
            f"(升 {r['relocate_rise']}·被另一态降 {r['retire_fall']} 抵 → "
            f"{'OK' if r['relocate_rise_covered'] else '未抵消!'})"
        )
    else:
        lines.append("  硬锁: 账未生成（先跑 --write-ledger）")
    lines.append(f"账上登记垫片: {data['ledger_rows']} 枚")
    blind = data.get("marker_blind") or []
    lines.append(
        f"读点盲区（命中垫片记号却未进待退役，**只读附账·不改桶**）: {len(blind)} 枚"
        + ("" if not blind else " —— " + "；".join(
            f"{item['path']} [{item['stage']}]" + (f" ({item['detail']})" if item["detail"] else "")
            for item in blind
        ))
    )
    ex = data.get("exemption") or {}
    lines.append(
        f"并列账·G-P2 豁免条数: {ex.get('count', '—')}（只读取数，本席不代改；同门记 29 上限）"
    )
    cc = data["cross_check"]
    if cc:
        lines.append(
            f"对账问题: ①漏记 {len(cc['missing_registration'])} | ②非垫片登记 {len(cc['not_a_shim'])} | "
            f"②b已退役被回引 {len(cc['retired_re_referenced'])} | "
            f"③真身不存在 {len(cc['canonical_missing'])} | ④引用超上限 {len(cc['refs_over_ceiling'])} | "
            f"⑤手抄真身不符 {len(cc['canonical_mismatch'])}"
        )
    else:
        lines.append("对账问题: 账未生成（先跑 --write-ledger）")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true", help="打印三态现算值 + 对账结果")
    parser.add_argument(
        "--check",
        action="store_true",
        help="对账：账与现算不一致或后两态回升 ⇒ 退出码 1（常驻门以外的机读校验口）",
    )
    parser.add_argument("--write-ledger", action="store_true", help="用 AST/grep 现算重写 board_shim_ledger.py（禁手抄）")
    parser.add_argument("--json", metavar="OUT", help="把明细写成 JSON（写到指定路径，不落源码树默认位置）")
    args = parser.parse_args()
    if args.write_ledger:
        states = three_states()
        try:
            # render_ledger 第一步取「引用腿完整读凭据」、随后取「台账腿完整读凭据」；
            # 撕裂读(ReferenceIndexUnstable)/坏读(ReferenceIndexError)/空账或台账撕裂(LedgerReadIncomplete)
            # 在算任何 ceiling 之前抛出 ⇒ 下面写盘根本不执行，绝不落一份被钉 0 或抬 live 的上限（宁可保留旧账）。
            ledger_text = render_ledger(states)
        except (ReferenceIndexUnstable, ReferenceIndexError, LedgerReadIncomplete) as exc:
            print(
                f"本轮读不完整（引用腿或台账腿）⇒ 拒写台账、保留旧值：{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return 1
        _atomic_write_text(LEDGER_PY, ledger_text)  # 原子写（TX201 任务③）：读者永不见 truncate 后的半档
        print(f"已写账: {LEDGER_PY.relative_to(REPO_ROOT).as_posix()}  待退役 {len(states['retire_shims'])} 枚")
        return 0
    if args.check:
        if not LEDGER_PY.exists():
            print("账未生成：先跑 --write-ledger", file=sys.stderr)
            return 1
        data = compute()
        cc = data["cross_check"]
        problems = {k: v for k, v in cc.items() if v}
        ratchet = data["ratchet"]
        bad_ratchet = [
            name for name, ok in ratchet.items()
            if isinstance(ok, bool) and not ok
        ] if ratchet else ["账未生成"]
        for line in report_lines(data):
            print(line)
        if problems or bad_ratchet:
            print(f"对账问题: {problems}", file=sys.stderr)
            print(f"方向锁违规: {bad_ratchet}", file=sys.stderr)
            return 1
        return 0
    data = compute()
    for line in report_lines(data):
        print(line)
    if args.json:
        Path(args.json).write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
