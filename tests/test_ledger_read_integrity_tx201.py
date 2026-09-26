"""TX201 续 TX191 的注毒自证 —— 撕裂读的**台账腿**完整性防线（`scripts/shim_retirement_census.py`）。

任务书：`BRIEFS-BATCH58.md`《TX201》。共享前言＝批 50《共享前言》逐字 +
`ADDENDUM-USER-RULINGS-20260923.md`（R0–R8/三边界/两纪律）。独占写面＝`scripts/shim_retirement_census.py`
（算口）+ 本件（新建回归锁）；**不碰任何既有测试断言**（`test_shim_retirement_ledger.py` /
`test_reference_index_integrity_tx191.py` 一字不改）。

被锁的根因（TX199 F-1 现算，TX191 只装了引用腿那一半）：
- `min(prior_refs[rel], live)` 的 `live` 腿走 `_require_complete_reference_index()`（双读撕裂）；
  但另一操作数 `prior_refs[rel]` 与四枚基线钳制仍走裸 `LEDGER_PY.read_text` + 宽容解析
  （`load_ledger_rows` / `previous_baselines`）；
- 喂空账 ⇒ `load_ledger_rows→0 行`、`previous_baselines→{}` 双双静默放行 ⇒ 每枚走「首次入账」分支
  ⇒ `ceiling=live` **免审批抬上限并持久化**；
- 撕裂读的**生产方就是本工具自己**（旧 `--write-ledger` 用 `LEDGER_PY.write_text`＝truncate+write 非原子）。

修法（本件逐发验证，全在内存/tmp 树注毒，绝不写源码树）：
① 台账读侧同装完整性判据（空账/解析零行/语法坏 ⇒ `LedgerReadIncomplete`，不许当「没有历史」）；
② `render_ledger` 在 `min()` 降账前取「已确认完整 + 非空」的既有账，拿不到 ⇒ 拒写、留旧值；
③ 台账写改原子（`_atomic_write_text`：临时文件 + `os.replace`，读者永不见半档）；
④ 注毒四发（空账必抛／半账不得抬 ceiling／撕裂读不得写台账／原子写中断不留半档）；
⑤ 回归锁点名 `load_ledger_rows | previous_baselines | prior_refs`（TX199 F-2：旧新测试件对该腿零提及＝零锁）。

在册三红（C5 #16/#17/#18：`test_ledger_matches_live_detection` / `test_scan_scope_did_not_collapse` /
`test_s101_package_shim_live_counts_are_not_false_zero`）＝他席并发迁移致 policy/sender 上限 0 与域外计数漂移，
**非本席引入、本席不代修**，已在报告如实归因。
"""

from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

import shim_retirement_census as s34

# ==========================================================================
# 合成账体（内存字符串注毒，绝不写源码树）——覆盖「合法非空」与「空账」两形
# ==========================================================================
_LEDGER_VALID = (
    "SHIM_ROWS = ((\"plugins/bot_unified_runtime/x/__init__.py\", "
    "\"plugins/bot_unified_runtime/domains/x/__init__.py\", 3),)\n"
    "SHIM_RETIRE_BASELINE = 1\n"
    "RELOCATE_BASELINE = 2\n"
    "UNLANDED_SUM_BASELINE = 3\n"
    "OUTSIDE_BASELINE = 4\n"
)
#: 有 SHIM_ROWS 但一枚基线都没有 = 半账/迁移残档形态（previous_baselines 应读空 ⇒ 抛）。
_LEDGER_NO_BASELINES = 'SHIM_ROWS = (("p", "c", 1),)\n'


def _read_names_in(fn: Any) -> set[str]:
    """收集某函数源码里所有被调用的函数/方法名（含属性末端名），供结构锁「点名三件套」用。"""
    tree = ast.parse(inspect.getsource(fn))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                names.add(f.id)
            elif isinstance(f, ast.Attribute):
                names.add(f.attr)
    return names


# ==========================================================================
# ① 空账必抛 —— load_ledger_rows / previous_baselines 对空账与零行一律拒读
# ==========================================================================
@pytest.mark.parametrize(
    "source",
    (
        "",                       # 完全空文件（撕裂截断成零字节也能到这形）
        "SHIM_ROWS = ()\n",       # 解析出零行 = 合法渲染的全退役账，但仍是「没有历史」⇒ 拒
        "import os\n",            # 根本没有 SHIM_ROWS 声明 = 撕裂前缀（截断在声明之前）
    ),
)
def test_tx201_1_empty_ledger_load_rows_raises(source: str) -> None:
    with pytest.raises(s34.LedgerReadIncomplete):
        s34.load_ledger_rows(source)


def test_tx201_1b_empty_baselines_previous_raises() -> None:
    # 有账行、零基线 = 半账/迁移残档：previous_baselines 不许退化成 {} 再被 render 当「无历史」。
    with pytest.raises(s34.LedgerReadIncomplete):
        s34.previous_baselines(_LEDGER_NO_BASELINES)


def test_tx201_1c_truncated_source_is_rejected() -> None:
    # 撕裂截断成非法 Python（元组未闭合）⇒ 语法坏 ⇒ 拒读（不当合法零行、不当「没历史」）。
    with pytest.raises(s34.LedgerReadIncomplete):
        s34.load_ledger_rows('SHIM_ROWS = (("a", "b", 1),\n')  # 缺右括号 = SyntaxError


# 反向自证：判据不能是「无条件抛」——合法非空账必须照常读得出（否则取数口反向自伤、门也瞎）。
def test_tx201_1d_valid_ledger_still_reads() -> None:
    rows = s34.load_ledger_rows(_LEDGER_VALID)
    assert rows and rows[0]["refs"] == 3, f"合法账被误拒＝判据反向自伤: {rows}"
    bl = s34.previous_baselines(_LEDGER_VALID)
    assert bl["OUTSIDE_BASELINE"] == 4, f"合法基线被误拒: {bl}"
    assert s34.load_ledger_rows(), "真账被误判成拒读＝取数口自伤（TX201 判据过头）"


# ==========================================================================
# ② 半账/撕裂账不得抬 ceiling —— render_ledger 在 min() 之前先抛，绝不产出抬到 live 的账
# ==========================================================================
def _shim_tree(tmp_path: Path) -> dict[str, str]:
    """搭一棵可被 detect_shims/computed_refs 认出的极小垫片树（两枚包垫片，各被引用 1 次 ⇒ live=1）。"""
    pkg = tmp_path / "plugins" / "pkg"
    for name in ("a", "b", "a_real", "b_real"):
        (pkg / name).mkdir(parents=True, exist_ok=True)
        (pkg / name / "__init__.py").write_text("# pkg\n", encoding="utf-8")
    (pkg / "a" / "__init__.py").write_text(
        "# Compat shim\n_CANONICAL = \"plugins.pkg.a_real\"\nfrom plugins.pkg.a_real import *\n", encoding="utf-8"
    )
    (pkg / "b" / "__init__.py").write_text(
        "# Compat shim\n_CANONICAL = \"plugins.pkg.b_real\"\nfrom plugins.pkg.b_real import *\n", encoding="utf-8"
    )
    (pkg / "consumer.py").write_text(
        "from plugins.pkg.a import x\nfrom plugins.pkg.b import y\n", encoding="utf-8"
    )
    return {
        "a": "plugins/pkg/a/__init__.py",
        "b": "plugins/pkg/b/__init__.py",
    }


def _ledger_with(rel: str, ceiling: int, *, with_baselines: bool = True) -> str:
    lines = [
        "SHIM_ROWS = (",
        f'    ("{rel}", "plugins/pkg/a_real/__init__.py", {ceiling}),',
        ")",
    ]
    if with_baselines:
        lines += [
            "SHIM_RETIRE_BASELINE = 99",
            "RELOCATE_BASELINE = 99",
            "UNLANDED_SUM_BASELINE = 99",
            "OUTSIDE_BASELINE = 99",
        ]
    return "\n".join(lines) + "\n"


def test_tx201_2_torn_ledger_read_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 双读撕裂（首读全、次读被截半）⇒ _read_ledger_source_with_integrity 抛，台账腿与引用腿同尺。
    ledger = tmp_path / "board_shim_ledger.py"
    ledger.write_text(_LEDGER_VALID, encoding="utf-8")
    monkeypatch.setattr(s34, "LEDGER_PY", ledger)

    calls = 0

    def fake_read(path: Path) -> bytes:
        nonlocal calls
        real = path.read_bytes()
        if path.name == "board_shim_ledger.py":
            calls += 1
            return real[: len(real) // 2] if calls == 2 else real  # 次轮截半 ⇒ 两读不一致
        return real

    monkeypatch.setattr(s34, "_read_file_bytes", fake_read)
    with pytest.raises(s34.LedgerReadIncomplete):
        s34.load_ledger_rows()  # 走真实双读校验（不传 source）


def test_tx201_2b_render_ledger_refuses_on_torn_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = _shim_tree(tmp_path)
    ledger = tmp_path / "board_shim_ledger.py"
    ledger.write_text(_ledger_with(tree["a"], 0), encoding="utf-8")
    monkeypatch.setattr(s34, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(s34, "LEDGER_PY", ledger)

    calls = 0

    def fake_read(path: Path) -> bytes:
        nonlocal calls
        real = path.read_bytes()
        if path.name == "board_shim_ledger.py":
            calls += 1
            if calls == 2:
                return b""  # 台账次轮读空 ⇒ 撕裂
        return real

    monkeypatch.setattr(s34, "_read_file_bytes", fake_read)
    s34._build_reference_index.cache_clear()
    states = {
        "outside": 6,
        "retire_shims": [tree["a"]],
        "relocate": [],
        "classified": [],
        "counts": {"retire_shims": 1, "relocate": 0, "classified": 0},
    }
    try:
        with pytest.raises(s34.LedgerReadIncomplete):
            s34.render_ledger(states, approvals_path=tmp_path / "no_approvals.json")
        # 关键：撕裂台账绝不该产出一份把 ceiling 抬到 live 的账体（此处根本没返回文本）。
    finally:
        s34._build_reference_index.cache_clear()


def test_tx201_2c_prior_refs_demotes_but_first_entry_uses_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """锁 `prior_refs` 真被当上限用：在册一枚 ceiling=0、live 现算=1 ⇒ 输出仍 0（min 生效、不抬）；
    未在册的另一枚（账非空但缺它）走首次入账 ⇒ 输出取 live=1。两枚对照证明 min(prior, live) 与首建分支都真跑。"""
    tree = _shim_tree(tmp_path)
    ledger = tmp_path / "board_shim_ledger.py"
    ledger.write_text(_ledger_with(tree["a"], 0), encoding="utf-8")
    monkeypatch.setattr(s34, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(s34, "LEDGER_PY", ledger)
    s34._build_reference_index.cache_clear()
    states = {
        "outside": 6,
        "retire_shims": [tree["a"], tree["b"]],
        "relocate": [],
        "classified": [],
        "counts": {"retire_shims": 2, "relocate": 0, "classified": 0},
    }
    try:
        out = s34.render_ledger(states, approvals_path=tmp_path / "no_approvals.json")
    finally:
        s34._build_reference_index.cache_clear()
    assert s34.computed_refs(tree["a"]) == 1, "本发前提：a 的 live 引用数应为 1（tmp 树 consumer 引一次）"
    rows = _rows_from_render(out)
    assert rows[tree["a"]] == 0, f"prior ceiling=0 被抬到 live ⇒ 抬上限绕过了 min() 钳制: {rows[tree['a']]}"
    assert rows[tree["b"]] == 1, f"首建分支未取 live（应 1）: {rows[tree['b']]}"


def _rows_from_render(rendered: str) -> dict[str, int]:
    """从 render_ledger 产出的完整模块文本里 AST 解析 `SHIM_ROWS` → {path: ceiling}。"""
    tree = ast.parse(rendered)
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        else:
            continue
        if value is not None and any(isinstance(t, ast.Name) and t.id == "SHIM_ROWS" for t in targets):
            raw = ast.literal_eval(value)
            return {r[0]: int(r[2]) for r in raw}
    raise AssertionError("render 里找不到 SHIM_ROWS")


# ==========================================================================
# ③ 撕裂读不得写台账 —— main --write-ledger 在台账撕裂时 rc=1、旧文件逐字节不动
# ==========================================================================
def test_tx201_3_main_does_not_write_on_torn_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = _shim_tree(tmp_path)
    old_bytes = _ledger_with(tree["a"], 5).encode("utf-8")
    ledger = tmp_path / "board_shim_ledger.py"
    ledger.write_bytes(old_bytes)
    monkeypatch.setattr(s34, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(s34, "LEDGER_PY", ledger)

    calls = 0

    def fake_read(path: Path) -> bytes:
        nonlocal calls
        real = path.read_bytes()
        if path.name == "board_shim_ledger.py":
            calls += 1
            if calls % 2 == 0:
                return real[:-3]  # 每次第二读截 3 字节 ⇒ 双读必不一致
        return real

    monkeypatch.setattr(s34, "_read_file_bytes", fake_read)
    monkeypatch.setattr(
        s34, "three_states",
        lambda: {
            "outside": 6,
            "retire_shims": [tree["a"]],
            "relocate": [],
            "classified": [],
            "counts": {"retire_shims": 1, "relocate": 0, "classified": 0},
        },
    )
    monkeypatch.setattr(sys, "argv", ["shim_retirement_census.py", "--write-ledger"])
    s34._build_reference_index.cache_clear()
    try:
        rc = s34.main()
        assert rc == 1, f"台账撕裂下 --write-ledger 返回 {rc}（应 1＝拒写）"
        assert ledger.read_bytes() == old_bytes, "撕裂读竟改了台账字节＝台账腿防线被绕过（会持久化抬/钉）"
        assert not list(tmp_path.glob("board_shim_ledger.py*.tmp")), "留下了半档临时文件＝非原子写"
    finally:
        s34._build_reference_index.cache_clear()


# ==========================================================================
# ④ 原子写：中断不留半档 + 成功与 write_text 字节一致
# ==========================================================================
def test_tx201_4_atomic_write_interrupt_keeps_old_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "board_shim_ledger.py"
    target.write_text("OLD-CONTENT", encoding="utf-8")

    def boom(*_a: Any, **_k: Any) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(s34.os, "replace", boom)
    with pytest.raises(OSError):
        s34._atomic_write_text(target, "NEW-CONTENT-PARTIAL")
    assert target.read_text(encoding="utf-8") == "OLD-CONTENT", "os.replace 失败却动了目标＝非原子"
    assert list(tmp_path.glob("board_shim_ledger.py*.tmp")) == [], "失败后残留临时文件＝清理没做"


def test_tx201_4b_atomic_write_success_is_byte_identical(tmp_path: Path) -> None:
    target = tmp_path / "board_shim_ledger.py"
    body = "SHIM_ROWS = (\n)\nOUTSIDE_BASELINE = 131\n"
    s34._atomic_write_text(target, body)
    ref = tmp_path / "ref.py"
    ref.write_text(body, encoding="utf-8")  # 与旧 write_text 路径同字节（Windows 上 \n→\r\n）
    assert target.read_bytes() == ref.read_bytes(), "原子写与旧 write_text 字节不一致＝可能翻行尾（TX182-C4）"
    assert list(tmp_path.glob("board_shim_ledger.py*.tmp")) == [], "成功后残留临时文件"


# ==========================================================================
# ⑤ 结构锁：判据真装在读侧与写侧（防有人日后退回裸 read_text / 非原子写 / 不拒空账）
# ==========================================================================
def test_tx201_5_readers_use_integrity_helper_not_bare_read_text() -> None:
    for fn in (s34.load_ledger_rows, s34.previous_baselines):
        src = inspect.getsource(fn)
        assert "_read_ledger_source_with_integrity" in _read_names_in(fn), f"{fn.__name__} 未经双读撕裂校验口"
        assert "LEDGER_PY.read_text" not in src, f"{fn.__name__} 仍留裸 read_text（撕裂/空账洞未堵）"
    assert "LedgerReadIncomplete" in inspect.getsource(s34.load_ledger_rows), "load_ledger_rows 不再拒空账"
    assert "LedgerReadIncomplete" in inspect.getsource(s34.previous_baselines), "previous_baselines 不再拒空账"


def test_tx201_5b_render_wires_all_three_ledger_operands() -> None:
    """render_ledger 必须点名三件套：完整读凭据 + load_ledger_rows + previous_baselines（prior_refs 的来源）。"""
    calls = _read_names_in(s34.render_ledger)
    for name in ("_require_complete_reference_index", "_read_ledger_source_with_integrity",
                 "load_ledger_rows", "previous_baselines"):
        assert name in calls, f"render_ledger 未接 {name}＝台账腿某侧被绕过"


def test_tx201_5c_main_refuses_write_on_ledger_incomplete() -> None:
    """main 的 except 必须把 LedgerReadIncomplete 纳入拒写面（否则撕裂账仍会落盘）。"""
    tree = ast.parse(inspect.getsource(s34.main))
    caught: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and isinstance(node.type, ast.Tuple):
            for elt in node.type.elts:
                caught.add(getattr(elt, "id", getattr(elt, "attr", "")))
        elif isinstance(node, ast.ExceptHandler) and isinstance(node.type, ast.Name):
            caught.add(node.type.id)
    assert "LedgerReadIncomplete" in caught, f"main 未捕获台账不完整读＝拒写防线没接上: {caught}"


def test_tx201_5d_atomic_write_uses_replace_not_truncate() -> None:
    src = inspect.getsource(s34._atomic_write_text)
    calls = _read_names_in(s34._atomic_write_text)
    assert "os.replace(" in src and "replace" in calls, "原子写没走 os.replace（仍可能 truncate+write）"
    assert "mkstemp" in calls, "临时文件没经 tempfile.mkstemp（同目录原子替换的前提）"
    assert "LEDGER_PY.write_text" not in inspect.getsource(s34.main), "main 仍用非原子 write_text（撕裂读生产方）"
