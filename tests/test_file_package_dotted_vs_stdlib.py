"""S197 —— `_file_package_dotted()` 派生点分名 vs stdlib 权威判据对拍锁（本席新建，只建锁不改取数口）。

## 对简报的两处事实更正（现算，非我臆断）
1. `_file_package_dotted` 真身在 **`scripts/shim_retirement_census.py:185`**（不是简报写的
   `spec_gates_census.py`）。它只有一处调用点：`_build_reference_index()`（同文件 :220），把
   「引用方文件所在包」的绝对点分名喂进全仓引用索引。
2. 简报点名的下游 `should_have_template()`（`spec_gates_census.py:447`）收的是 `category` 参数，
   **不消费点分名**，与 `_file_package_dotted` 无调用边。真正的消费方是引用索引前缀匹配那一路：
   `_referencing_files`(:282) ← `computed_refs`(:293) ← `cross_check`(:557/:576) 与 `reference_index`(:255)。
   ⇒ 取数口本体（S78/S126/S131/S152/S164/S175 六席共用）交主会话单点改，本席一字不碰。

## 现算结论：简报"当前存在幻影键"的前提**不复现**（phantom = 0）
全树 in-scope py 文件 **1218** 枚 → `_file_package_dotted` 派生 **1218** 个互异点分名，逐枚过
`importlib.util.find_spec`（一次性独立复核）**全部 resolve**（ok=1218 / 幻影 0）。所谓"1217 枚点分名
含无 `__init__.py` 的中间目录"，实为顶层 `scripts`/`tests`/`plugins` 三枚 **PEP 420 命名空间包**——
简报第五条取证更正里的 `import scripts.<件>` 冒烟本身即走命名空间导入，证明其合法可导。若按"每级都
须有 `__init__.py`"的严格包口径判幻影，会把整棵树 1217 枚全判成缺陷，那是**判据选错**（把正确名字当
bug）的假红反面教材，非本锁所为。

## 那这把锁还立不立？立 —— 它是前瞻回归门，不是凑数
`_file_package_dotted` 是**纯路径→字符串变换，不校验可导入性**。只要将来落入下列形态，索引会静收录
一个运行期永不匹配的幻影键 → 垫片"引用方数"被低估 → 误判"零引用"而**误删垫片**：
- (c) 某目录/文件段非合法标识符（连字符、前导数字、内嵌点、大小写/分隔符差异）；
- (a) 相对导入解析出的 base 不再 round-trip 到盘上真身（重命名/移动后）。
⇒ 幻影数**只准 = 0（只准降）**，扫描面地板守住防空集恒真，注毒证明探针非恒假。

## stdlib 权威口径三选一 → 本锁选 **pathlib**
- **pathlib**（选中）：`_file_package_dotted` 契约本身是文件系统路径变换，pathlib 判据与它**同源、离线、
  零 import 副作用**（不触发父包 `__init__.py` 执行），最贴合"这条点分名对应的模块在不在盘上"。
- `find_spec`：语义等价但会**逐枚 import 父包**（含 `bot_unified_runtime`），放进常驻 pytest 有副作用 /
  耗时 / 离线脆弱风险 ⇒ 仅用作本席一次性离线复核（结论同为 0），不入锁。
- `iter_modules`：列的是某 path entry 的**直接子项**，对"校验一条完整点分路径"不适用 ⇒ 不选。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts import physical_placement_census as ppc
from scripts import shim_retirement_census as S  # 真身取数口，禁重解析

# --- 六件套①：字面量上限（本席现算值 = 0；只准降） ---
_BASELINE_PHANTOM_MAX: int = 0
# --- 六件套⑤：扫描面地板（防"集合为空恒真"；现算实测 1218，取 500 为灾难性塌陷下限） ---
_SCAN_FACE_FLOOR: int = 500


def _iter_scoped_rel() -> list[str]:
    """枚举 `_file_package_dotted` 的真实输入集。

    复用真身自己的 scope 谓词 `S._reference_index_scopes` 与 skip 集 `ppc.SKIP_DIR_NAMES`，
    与 `_build_reference_index` 的扫描口径**同源**（禁在锁里另立一套扫描判据 = 第二真身）。
    """
    skip = set(ppc.SKIP_DIR_NAMES)
    out: list[str] = []
    for path in S.REPO_ROOT.rglob("*.py"):
        rel = path.relative_to(S.REPO_ROOT).as_posix()
        if rel.split("/")[-1] == "__pycache__" or set(rel.split("/")) & skip:
            continue
        if not S._reference_index_scopes(rel):
            continue
        out.append(rel)
    return out


def _phantom_reason(pkg: str, repo: Path) -> str | None:
    """pathlib 宽松包口径判一条派生点分名是否幻影；None = 合法（允许命名空间父包）。

    三分（对齐简报②）：
    - (c) 任一段非合法 Python 标识符 ⇒ 运行期永不可导 ⇒ `"invalid-identifier"`；
    - (a) 点分名 round-trip 回的 `.py` / `__init__.py` 在盘上不存在 ⇒ `"leaf-missing"`；
    - (b) 中间目录缺 `__init__.py` ⇒ 命名空间包，本项目合法（rule-④ 冒烟为证），**不判幻影**。
    """
    if not pkg:
        return None
    parts = pkg.split(".")
    if any(not p.isidentifier() for p in parts):
        return "invalid-identifier"
    module = repo.joinpath(*parts).with_suffix(".py")
    pkg_init = repo.joinpath(*parts, "__init__.py")
    if not (module.exists() or pkg_init.exists()):
        return "leaf-missing"
    return None


def _scan_and_classify() -> tuple[list[str], list[tuple[str, str]]]:
    """一次跑完：返回 (全部派生点分名, [(幻影名, 原因), ...])。禁一文件一次外部调用。"""
    derived = [S._file_package_dotted(rel) for rel in _iter_scoped_rel()]
    phantoms = [(n, r) for n in derived if (r := _phantom_reason(n, S.REPO_ROOT)) is not None]
    return derived, phantoms


def test_scan_face_floor_guard():
    """六件套⑤：扫描面必须远超地板，否则'集合为空恒真'会把幻影锁糊绿。"""
    derived, _ = _scan_and_classify()
    assert len(derived) >= _SCAN_FACE_FLOOR, f"扫描面塌陷：{len(derived)} < {_SCAN_FACE_FLOOR}"


def test_every_derived_name_is_importable_shape():
    """现算主断言：幻影数只准 ≤ 字面量基线（只准降），并列出任何越界枚点名。"""
    _derived, phantoms = _scan_and_classify()
    assert len(phantoms) <= _BASELINE_PHANTOM_MAX, (
        f"发现派生式幻影点分名 {len(phantoms)} > 基线 {_BASELINE_PHANTOM_MAX}：{phantoms[:20]}"
    )


def test_projection_is_injective():
    """1218 枚输入应派生 1218 个互异点分名（无碰撞）；碰撞=另一形派生式错值，须现算暴露。"""
    derived, _ = _scan_and_classify()
    assert len(derived) == len(set(derived)), "派生点分名出现碰撞（第二文件映射到同一名）"


# --- 六件套⑥：内存注毒自证（绝不写源码树）；反向两针证明探针既非常真亦非常假 ---

def test_poison_must_be_caught():
    """注两枚必·幻影：非法标识符段 + 盘上不存在的叶子 ⇒ 皆须被记（探针非恒假）。"""
    # (c) 连字符段非合法标识符 ⇒ 永不可导
    assert _phantom_reason("scripts.some-dir.mod", S.REPO_ROOT) == "invalid-identifier"
    # (a) 段皆为合法标识符，但点分名 round-trip 回的叶子盘上不存在 ⇒ leaf-missing
    assert _phantom_reason("scripts.definitely_not_on_disk_xyz123", S.REPO_ROOT) == "leaf-missing"
    assert _phantom_reason("plugins.bot_unified_runtime.__no_such_pkg__.zz", S.REPO_ROOT) == "leaf-missing"


def test_poison_legal_not_flagged():
    """注两枚合法：真实模块名 + 命名空间顶层（无 __init__ 但可导）⇒ 必不被记（防过拦 / 证非恒真）。"""
    assert _phantom_reason("scripts.shim_retirement_census", S.REPO_ROOT) is None
    # bot 顶层既非包也无父链，盘上有 bot.py ⇒ 合法
    assert _phantom_reason("bot", S.REPO_ROOT) is None
    # 命名空间顶层脚本（scripts 无 __init__.py）不得被误判幻影
    assert _phantom_reason("scripts.physical_placement_census", S.REPO_ROOT) is None


# --- 六件套②③：AST 自锁（基线为纯字面量 + 方向锁为 <=），对齐 test_legacy_shim_import_ratchet 哲学 ---

def test_baseline_is_plain_int_literal_and_direction_is_only_down():
    src = Path(__file__).resolve().read_text(encoding="utf-8")
    tree = ast.parse(src)
    baseline_is_int_literal = False
    for node in ast.walk(tree):
        # Assign 形态：`_BASELINE_PHANTOM_MAX = 0`
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "_BASELINE_PHANTOM_MAX":
                    assert isinstance(node.value, ast.Constant) and isinstance(node.value.value, int), (
                        "_BASELINE_PHANTOM_MAX 必须是手写字面量整数，不得为计算/调用值"
                    )
                    baseline_is_int_literal = True
        # AnnAssign 形态：`_BASELINE_PHANTOM_MAX: int = 0`
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "_BASELINE_PHANTOM_MAX"
        ):
            assert isinstance(node.value, ast.Constant) and isinstance(node.value.value, int), (
                "_BASELINE_PHANTOM_MAX 必须是手写字面量整数"
            )
            baseline_is_int_literal = True
    assert baseline_is_int_literal, "未找到 _BASELINE_PHANTOM_MAX 的整数字面量赋值（Assign/AnnAssign）"

    # 方向锁：存在一处 `len(<=phantom...) <= _BASELINE_PHANTOM_MAX` 且算子只准 LtE（只准降）
    direction_locked = False
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Compare)
            and node.ops
            and isinstance(node.ops[0], ast.LtE)
            and any(isinstance(cmp, ast.Name) and cmp.id == "_BASELINE_PHANTOM_MAX" for cmp in node.comparators)
        ):
            direction_locked = True
    assert direction_locked, "方向锁缺失或算子非 <=（幻影数只准降）"
