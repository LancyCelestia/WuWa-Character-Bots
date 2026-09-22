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
"""

from __future__ import annotations

import argparse
import ast
import functools
import json
import sys
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


def derive_canonical(src: str) -> str | None:
    """从垫片源码 AST 现算真身的**点号模块名**。

    两形态都认：① `_CANONICAL = "<dotted>"` 字面量（PEP 562 形）；② `from <mod> import *`（星号形）。
    派生不出（例如只用相对导入的包命名空间 `__init__.py`）返回 None ⇒ 调用方据此判「非退役垫片」。
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
        if isinstance(node, ast.ImportFrom) and node.module and any(a.name == "*" for a in node.names):
            return node.module
    return None


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


def outside_py(universe: list[str] | None = None) -> list[str]:
    """域外 = `plugins/**` 下、不在 `domains/` 里的 py（与 BASELINE §1 口径一致，不含根 bot.py）。"""
    universe = ppc.py_universe() if universe is None else universe
    domains_root = ppc.load_placement()["DOMAINS_ROOT"]
    return sorted(
        rel for rel in universe
        if rel.startswith("plugins/") and not ppc._under(rel, domains_root)
    )


def detect_shims(outside: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """域外里所有**合格垫片**：命中记号 + 真身可派生 + 真身存在。返回 `{rel: {canonical_dotted, canonical}}`。"""
    outside = outside_py() if outside is None else outside
    out: dict[str, dict[str, Any]] = {}
    for rel in outside:
        src = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
        if not is_shim_text(src):
            continue
        dotted = derive_canonical(src)
        if not dotted:
            continue  # 记号命中但派生不出真身（包命名空间相对导入）⇒ 非退役垫片，归「已归类」
        resolved = resolve_canonical(dotted)
        if not resolved:
            continue  # 真身不存在 ⇒ 非合格垫片（坏桩另有 ③ 自证覆盖）
        out[rel] = {"canonical_dotted": dotted, "canonical": resolved}
    return out


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


def _file_package_dotted(rel: str) -> str:
    """引用方文件所在**包**的点号名（`__init__.py` 的包就是它自己所在目录）。"""
    parts = rel[:-3].split("/") if rel.endswith(".py") else rel.split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


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


@functools.lru_cache(maxsize=1)
def _build_reference_index() -> tuple[dict[str, frozenset[str]], tuple[str, ...]]:
    counts: dict[str, set[str]] = {}
    errors: list[str] = []
    for path in REPO_ROOT.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel.split("/")[-1] == "__pycache__" or set(rel.split("/")) & ppc.SKIP_DIR_NAMES:
            continue
        if not _reference_index_scopes(rel):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, ValueError, OSError) as exc:
            errors.append(f"{rel}:{getattr(exc, 'lineno', None) or 1}: {type(exc).__name__}: {exc}")
            continue
        pkg = _file_package_dotted(rel)
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
                literal = _importlib_literal(node)
                if literal:
                    touched.add(literal)
                    touched.add(literal.rsplit(".", 1)[0] if "." in literal else literal)
        for name in touched:
            counts.setdefault(name, set()).add(rel)
    return {k: frozenset(v) for k, v in counts.items()}, tuple(errors)


def reference_index() -> dict[str, frozenset[str]]:
    """全仓引用索引 `{点号名: 去重引用文件集合}` —— 唯一取数口，门/自测/`--report` 同源。

    对 S34 旧版的四处加严（全在同一码路上，禁第二份扫描器）：
    - 值从 `int` 升为**文件集合** —— 包垫片按点号前缀并集数文件，必须能跨键去重（旧版 int 只能 `max` 近似）；
    - 相对导入（实测根 `__init__.py:3740 from .policy import (`）按引用方所在包解析成绝对点号名 ——
      旧版只记裸名 `policy`，生产对包垫片的 dotted 引用整体隐形；
    - `importlib.import_module("…")` / `__import__("…")` 的字面量目标入册（同 `import a.b.c` 口径）；
    - 任一引用面文件不可解析 ⇒ `ReferenceIndexError` 点名 `文件:行`，绝不静默当「零引用」。
    """
    index, errors = _build_reference_index()
    if errors:
        raise ReferenceIndexError(
            "引用面不可解析＝fail-closed（禁止把「读不到」当「没人引用」）: " + "; ".join(errors)
        )
    return index


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
    （`from plugins…sender import X` / `…sender.onebot import Y` / `importlib.import_module("…sender…")`，
    含由相对导入解析出的绝对点号名）的文件都在数 —— 这些写法运行期都会执行包壳，删壳即打坏导入图。
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
    """
    claims = ppc.flatten_claims(ppc.feature_impl_paths())
    outside = outside_py()
    shims = detect_shims(outside)
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
        "counts": {"retire_shims": len(shim_paths), "relocate": len(relocate), "classified": len(classified)},
        "relocate_counts": {state: len(paths) for state, paths in split.items()},
    }


# --------------------------------------------------------------------------
# 账装载（AST 静态读声明源，不 import 插件包，避免拖起 NoneBot 初始化）
# --------------------------------------------------------------------------
def load_ledger_rows(ledger_source: str | None = None) -> list[dict[str, Any]]:
    """解析 `board_shim_ledger.py` 的 `SHIM_ROWS`：每条 = 元组 (path, canonical, refs)。"""
    source = LEDGER_PY.read_text(encoding="utf-8") if ledger_source is None else ledger_source
    tree = ast.parse(source)
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
    """
    source = LEDGER_PY.read_text(encoding="utf-8") if ledger_source is None else ledger_source
    data = ppc._read_literals(source, set(LEDGER_BASELINE_NAMES))
    return {k: int(v) for k, v in data.items() if isinstance(v, int)}


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
       反查其点号目标（包垫片=父包前缀，含相对导入解析出的绝对名与 importlib 字面量）是否重回
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
    """
    detected = {rel: detect_shims([rel])[rel] for rel in states["retire_shims"]}
    bl = clamped_baselines(previous_baselines() if LEDGER_PY.exists() else {}, states)
    retire_baseline = bl["SHIM_RETIRE_BASELINE"]
    relocate_baseline = bl["RELOCATE_BASELINE"]
    unlanded_baseline = bl["UNLANDED_SUM_BASELINE"]
    outside_baseline = bl["OUTSIDE_BASELINE"]
    prior_refs = {r["path"]: r["refs"] for r in (load_ledger_rows() if LEDGER_PY.exists() else [])}
    approved = approved_refs_paths(detected, approvals_path)
    rows = []
    for rel in sorted(detected):
        canonical = detected[rel]["canonical"]
        live = computed_refs(rel)
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
        LEDGER_PY.write_text(render_ledger(states), encoding="utf-8")
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
