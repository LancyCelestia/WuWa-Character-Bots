"""旧 `capabilities/` 垫片 import 边数棘轮（只准降，2026-09-22 统一波立）。

背景：v21r2 把能力实现迁进 `domains/<域>/capabilities/`，旧位置留下一批 PEP 562
再导出垫片。垫片让"旧路径还能 import"，于是**迁移永远做不完**——每多一处旧写法，
就多一条"入口不唯一"的活路。本门把生产侧的旧写法条数钉成只准降的账。

**两本账、一把尺子**：生产侧（`plugins/`+`scripts/`）与测试侧（`tests/`）各自独立单调，
互不相交（有专门的斥离锁）。混算一次就再也问不出"生产迁完了吗"——本波真的混算过。

判据口径（本仓实锤过的三形态，逐条防）：
- **上限是手写字面量**：与被检清单同一表达式的上限＝结构性假绿，故另有一把 AST 自锁。
- **扫描面不许塌陷**：只数边不数"扫了多少文件"，改 glob 就能悄悄把账做没。
- **杀伤力自证不碰源码树**：注毒走"同一取数函数吃一段内存源码"，不往 `plugins/**` 写东西。
"""

from __future__ import annotations

import ast
import collections
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LEGACY_PKG = "plugins.bot_unified_runtime.capabilities"
SHIM_DIR = REPO_ROOT / "plugins" / "bot_unified_runtime" / "capabilities"
SCAN_ROOTS = ("plugins", "scripts")
#: 扫描文件数下限：低于此＝扫描面塌了（改 glob/加排除），不是"大家都迁完了"。
MIN_SCANNED_FILES = 500

#: **手写字面量**上限，只准降。迁掉一批旧 import 后把它改小，并在 AUDIT_HISTORY 追加一行。
# MIG-BR1（2026-09-22）：base_router.py 24 条旧垫片边清零（23 条计入本账，auto_send 系子包
# 垫片不在 glob 面、不占数），迁移后全树现算 TOTAL=73，零余量钉死。
SHIM_EDGE_CEILING = 73
#: 逐次核账记录（日期, 当时边数）。**必须单调不升**——想调大上限就得违反这条，当场红。
#: ⚠ 口径变更（同日两次核账之间）：首行 **96 是"只数顶层 `*.py` 垫片"的旧口径**；
#: 枚举扩到目录形垫片后，同一棵树真值是 97（多出 `capabilities/auto_send/` 那一枚 import 边）。
#: 第二行 73 已按**新口径**测（顶层 73 条 + 目录形 0 条；MIG-BR1 迁掉 base_router 23 条顶层 + 1 条 auto_send）。
#: 也就是说 96→73 不是"降了 23 条"而是"降了 24 条、同口径应为 97→73"——留着这两行是为了逼后来者**先对齐尺子再对账**。
AUDIT_HISTORY: tuple[tuple[str, int], ...] = (("2026-09-22", 96), ("2026-09-22", 73), ("2026-09-22", 50))

#: 测试侧同一把尺子的**第二本账**（独立单调）：`tests/` 里指向旧垫片的 import 边。
#: 分账不合并——生产侧迁移与测试侧迁移是两批不同的活，混成一个数就分不清谁在退、谁在进。
# 2026-09-22 首账：本门立起来时只数了生产侧，"tests 里还有 245 条旧写法"这件事根本没人记账
# （主会话自报：曾把两侧混算成 296/135，口径错了两次才对齐）。这张账开在这里，往后只准降。
TESTS_SHIM_EDGE_CEILING = 202
TESTS_AUDIT_HISTORY: tuple[tuple[str, int], ...] = (("2026-09-22", 245), ("2026-09-22", 202), ("2026-09-22", 197))
#: 测试侧扫描根（与生产侧 `SCAN_ROOTS` 必须互斥——两本账不许有交集）。
TESTS_SCAN_ROOTS = ("tests",)
#: 测试侧扫描文件数下限（同"扫描面不许塌陷"口径）。
MIN_SCANNED_TEST_FILES = 400


def _is_shim_source(src: str) -> bool:
    return "Compat shim" in src or "__getattr__" in src


def _is_live_shim(leaf: str) -> bool:
    """真被本门算作"旧垫片"的，只有那些确实再导出的模块（不是同名真身）。

    **两种形态都要认**：① 顶层 `capabilities/<leaf>.py` 薄壳；② 子包
    `capabilities/<leaf>/__init__.py`（`auto_send` 就是子包形——第一版只 glob 顶层 `*.py`
    把它看漏了，正是本门自己批评过的"门只覆盖被抓过的那一件"，立门当天即被迁移席证伪）。
    """
    if leaf == "__init__":
        return False
    module = SHIM_DIR / f"{leaf}.py"
    if module.exists():
        return _is_shim_source(module.read_text(encoding="utf-8"))
    package_init = SHIM_DIR / leaf / "__init__.py"
    if package_init.exists():
        return _is_shim_source(package_init.read_text(encoding="utf-8"))
    return False


def live_shim_leaves() -> frozenset[str]:
    leaves = {p.stem for p in SHIM_DIR.glob("*.py") if _is_live_shim(p.stem)}
    leaves |= {p.name for p in SHIM_DIR.iterdir() if p.is_dir() and _is_live_shim(p.name)}
    return frozenset(leaves)


def _edges_in_tree(tree: ast.AST, leaves: frozenset[str]) -> int:
    total = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == LEGACY_PKG:
                total += sum(1 for a in node.names if a.name in leaves)
            elif module.startswith(LEGACY_PKG + ".") and module.rsplit(".", 1)[-1] in leaves:
                total += 1
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(LEGACY_PKG + ".") and alias.name.rsplit(".", 1)[-1] in leaves:
                    total += 1
    return total


def edges_in_source(source: str, filename: str = "<memory>") -> int:
    """单一取数口：既服务全树扫描，也服务注毒（内存源码即可，不碰树）。"""
    return _edges_in_tree(ast.parse(source, filename=filename), live_shim_leaves())


def _collect_over(roots: tuple[str, ...], leaves: frozenset[str]) -> dict[str, int]:
    per_file: dict[str, int] = collections.Counter()
    for root in roots:
        for path in (REPO_ROOT / root).rglob("*.py"):
            rel = path.as_posix()
            if rel.startswith("plugins/bot_unified_runtime/capabilities/"):
                continue
            count = _edges_in_tree(ast.parse(path.read_text(encoding="utf-8"), filename=rel), leaves)
            if count:
                per_file[rel] = count
    return dict(per_file)


def collect_legacy_shim_edges() -> dict[str, int]:
    return _collect_over(SCAN_ROOTS, live_shim_leaves())


def collect_tests_legacy_shim_edges() -> dict[str, int]:
    """第二本账的取数口：口径与生产侧**完全一致**（同一 `live_shim_leaves()`、同一 `_edges_in_tree`），
    只有扫描根不同。两本账互不相交，谁也不许被算进对方。"""
    return _collect_over(TESTS_SCAN_ROOTS, live_shim_leaves())


def scanned_file_count(roots: tuple[str, ...] = SCAN_ROOTS) -> int:
    return sum(
        1
        for root in roots
        for path in (REPO_ROOT / root).rglob("*.py")
        if path.as_posix() != "plugins/bot_unified_runtime/capabilities/__init__.py"
    )


def test_legacy_shim_edges_within_ceiling() -> None:
    per_file = collect_legacy_shim_edges()
    total = sum(per_file.values())
    worst = sorted(per_file.items(), key=lambda kv: -kv[1])[:5]
    assert total <= SHIM_EDGE_CEILING, (
        f"旧垫片 import 边数 {total} > 上限 {SHIM_EDGE_CEILING}＝又长了新副本。"
        f"修法：改成 `domains/<域>/capabilities/...` 真身路径（大户：{worst}）"
    )


def test_subpackage_shims_are_not_blind() -> None:
    """专门钉住"只 glob 顶层 `*.py`"这个盲点：`capabilities/` 下每个目录形垫片都必须在册。

    本门第一版就是这样把 `auto_send`（子包形垫片）看漏的——立门当天被迁移席证伪。
    若将来有人把枚举改回单形态，这条会在**盲点重新出现的当场**红，而不是等账对上才发现。
    """
    dir_shims = {
        child.name
        for child in SHIM_DIR.iterdir()
        if child.is_dir() and (child / "__init__.py").exists() and _is_live_shim(child.name)
    }
    assert dir_shims <= live_shim_leaves(), (
        f"目录形垫片没被枚举到：{sorted(dir_shims - live_shim_leaves())}——扫描面对子包失明"
    )


def test_ceiling_is_hand_written_literal() -> None:
    """结构锁：上限必须是字面量整数，不许写成 len(...)/sum(...) 派生。"""
    source = Path(__file__).read_text(encoding="utf-8")
    assigned: dict[str, ast.expr] = {}
    for node in ast.walk(ast.parse(source)):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                assigned[target.id] = node.value
    ceiling = assigned.get("SHIM_EDGE_CEILING")
    assert isinstance(ceiling, ast.Constant) and isinstance(ceiling.value, int), (
        "SHIM_EDGE_CEILING 被改成派生表达式＝上限跟着被检对象一起动，本门结构性失效"
    )
    history = assigned.get("AUDIT_HISTORY")
    assert isinstance(history, ast.Tuple) and len(history.elts) >= 1, (
        "AUDIT_HISTORY 必须留在本文件里且非空——它是'只准降'的对账凭据"
    )
    tests_ceiling = assigned.get("TESTS_SHIM_EDGE_CEILING")
    assert isinstance(tests_ceiling, ast.Constant) and isinstance(tests_ceiling.value, int), (
        "测试侧那本账的上限同样必须是字面量，不许派生"
    )
    tests_history = assigned.get("TESTS_AUDIT_HISTORY")
    assert isinstance(tests_history, ast.Tuple) and len(tests_history.elts) >= 1, (
        "TESTS_AUDIT_HISTORY 必须留在本文件里且非空"
    )


def test_audit_history_never_rises() -> None:
    counts = [count for _, count in AUDIT_HISTORY]
    assert counts == sorted(counts, reverse=True), f"核账记录出现回升（方向锁）：{AUDIT_HISTORY}"
    assert SHIM_EDGE_CEILING <= counts[0], (
        f"上限 {SHIM_EDGE_CEILING} 超过首届核账值 {counts[0]}＝把账调大换绿，本门不允许"
    )


def test_tests_side_edges_within_ceiling() -> None:
    per_file = collect_tests_legacy_shim_edges()
    total = sum(per_file.values())
    worst = sorted(per_file.items(), key=lambda kv: -kv[1])[:5]
    assert total <= TESTS_SHIM_EDGE_CEILING, (
        f"测试侧旧垫片 import 边数 {total} > 上限 {TESTS_SHIM_EDGE_CEILING}＝又长了新副本。"
        f"修法：测试也 import 真身路径 `domains/<域>/capabilities/...`（大户：{worst}）"
    )


def test_tests_audit_history_never_rises() -> None:
    counts = [count for _, count in TESTS_AUDIT_HISTORY]
    assert counts == sorted(counts, reverse=True), f"测试侧核账记录出现回升（方向锁）：{TESTS_AUDIT_HISTORY}"
    assert TESTS_SHIM_EDGE_CEILING <= counts[0], (
        f"测试侧上限 {TESTS_SHIM_EDGE_CEILING} 超过首届核账值 {counts[0]}＝调大换绿"
    )


def test_two_ledgers_are_disjoint() -> None:
    """两本账不许有交集：同一文件同时被两侧数到＝有人把 `tests` 塞进 `SCAN_ROOTS`（或反向）。

    合并计数会让"生产侧迁完了吗"这个问题永远没有答案——历史上就混算过一次（296/135）。
    """
    prod = set(collect_legacy_shim_edges())
    tests_side = set(collect_tests_legacy_shim_edges())
    overlap = sorted(prod & tests_side)
    assert not overlap, f"两本账出现交集文件 {overlap}＝扫描根重叠，账不再可归因"


def test_scan_scope_did_not_collapse() -> None:
    """非空转守卫：扫描面与命中面都要真实存在，否则"零红"只是没在看。"""
    files = scanned_file_count()
    assert files >= MIN_SCANNED_FILES, f"只扫到 {files} 个文件（下限 {MIN_SCANNED_FILES}）＝扫描面塌陷"
    per_file = collect_legacy_shim_edges()
    assert per_file, "一条旧垫片 import 都没数到——要么全迁完了（那请同时删本门并留说明），要么取数口坏了"
    leaves = live_shim_leaves()
    assert leaves, "垫片清单为空但上面还数得到边＝两份判据不一致，取数口必坏"
    # 命中数与"逐文件明细"必须同源（防"总数另算一套"）
    assert sum(per_file.values()) == sum(
        edges_in_source((REPO_ROOT / rel).read_text(encoding="utf-8"), rel) for rel in per_file
    )
    # 第二本账同样要有扫描面地板，否则它也能被"改 glob"做没
    test_files = scanned_file_count(TESTS_SCAN_ROOTS)
    assert test_files >= MIN_SCANNED_TEST_FILES, (
        f"测试侧只扫到 {test_files} 个文件（下限 {MIN_SCANNED_TEST_FILES}）＝测试侧扫描面塌陷"
    )
    assert collect_tests_legacy_shim_edges(), "测试侧一条都没数到＝取数口对 tests/ 失明"


def test_new_legacy_import_is_caught() -> None:
    """注毒自证（内存样本，不碰源码树）：新增一枚旧写法必被同一取数口数到。"""
    leaf = min(live_shim_leaves())
    poison_a = f"from {LEGACY_PKG}.{leaf} import anything\n"
    poison_b = f"from {LEGACY_PKG} import {leaf}\n"
    assert edges_in_source(poison_a) == 1, "旧点号路径写法没被数到＝取数口对形态①失明"
    assert edges_in_source(poison_b) == 1, "从包里 import 垫片名（形态②）没被数到＝漏判"
    # 反例：真身路径不计入（否则本门会把迁移动力也判成违规）
    assert edges_in_source(f"from plugins.bot_unified_runtime.domains.{leaf} import anything\n") == 0
