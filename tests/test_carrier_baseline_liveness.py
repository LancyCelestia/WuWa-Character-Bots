"""载体列两枚「在册但未执法」常数的**活性门**（席 S118，2026-09-22 立）。

任务书一句话：`tests/test_doc_link_integrity.py` 里

- `:96 _BASELINE_CARRIER_DEAD = 0` —— 注释自证「本常量当前不被任何断言引用」；
- `:99 _BASELINE_CARRIER_TRUTH = 5` —— 注释自证「当前实测 34 ⇒ 门仍绿」；

两枚**存在但不执法**（S111 的 C-1，假绿形态候选第 37 类）。本门把它们变成真判据，
禁写面一字不碰：不 `import` 改写、不加 skip/xfail、不回改它的断言、不动那两枚数值。

设计约束（任务书 S118 ①–④）：

1. **单一取数口**＝直接调既有门的 `collect_carrier_findings()`，本席零逻辑副本、零第二本账；
2. **方向锁**＝「实测条数只准 ≤ 在册常数」（任务书 ① 原文照做，两枚同理）；
3. **诚实账**＝carrier-truth 现算 34 > 在册常数 5 ⇒ 本门
   `test_carrier_truth_count_is_within_inbook_baseline` **今日必红**（任务书 ②）。
   本席不为让它变绿而放宽判据（§0 六禁），只把「谁该处置／三条可选路径／推荐」写进
   `.superpowers/sdd/2026-09-22-taxonomy/SEAT-S118.md` 交 doc_link 门 owner 裁决；
4. **门瞎自证**＝`test_judgment_is_threshold_sensitive_at_boundary` +
   `test_truth_leg_verdict_tracks_data`：判据必须随数据翻面，超限而不抛即本席自证腿当场红；
5. **反向自测三发**全部走内存/`monkeypatch`（不往源码树写一个字）；
6. **自锁**＝本文件手写字面量走 `ast.Assign` 与 `ast.AnnAssign` 双形态（照既有棘轮六件套形状），
   且禁止任何 `dl._BASELINE_* = ...` 形态的改写。

六件套骨架照抄 `tests/test_taxonomy_spec_gates.py`（未自创）：①单一取数口 ②上限＝手写字面量
＋AST 自锁 ③方向锁 ④扫描面地板（塌陷即红）⑤反向自测全走内存 ⑥正样控制。
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
_GATE_PATH = REPO_ROOT / "tests" / "test_doc_link_integrity.py"

# ---------------------------------------------------------------------------
# ① 单一取数口：复用既有门的判定函数（禁复制逻辑）
# ---------------------------------------------------------------------------
_spec = importlib.util.spec_from_file_location("doc_link_integrity_as_source", _GATE_PATH)
assert _spec is not None and _spec.loader is not None, f"取数口所在门文件读不到：{_GATE_PATH}"
dl: Any = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = dl
_spec.loader.exec_module(dl)


def _findings() -> dict[str, list[str]]:
    """唯一取数口：字面真身 / 垫片 / 旧路径 / 彻底不存在 四档，全部由既有门现算。"""
    return dl.collect_carrier_findings()


# ---------------------------------------------------------------------------
# ② 手写字面量（扫描面地板）＋ ③ 方向锁
# ---------------------------------------------------------------------------
#: 载体列四档行数之和的地板。现算（2026-09-22 17:5x 本席实跑）：
#: `literal=34 shim=12 moved=9 dead=0` ⇒ 合计 55，取 30 为「塌陷即红」判据。
_MIN_CARRIER_ROWS = 30

#: 被本门执法的两枚在册常数（真身住 `test_doc_link_integrity.py`，本席只读引用）。
_INBOOK_CONSTANTS = ("_BASELINE_CARRIER_DEAD", "_BASELINE_CARRIER_TRUTH")

#: 判据函数名——活性锁只认「值真的流进判决」的调用形态。
_VERDICT_HELPERS = ("_assert_within_ceiling", "_violation")


def _violation(face: str, rows: list[str], ceiling: int, constant: str) -> str | None:
    """方向锁：实测条数只准 ≤ 在册常数；返回 `None` 即放行，否则给人话判决。"""
    if len(rows) <= ceiling:
        return None
    return (
        f"{face}：实测 {len(rows)} 条 > 在册常数 {constant} = {ceiling}"
        f"（方向锁：只准 ≤）⇒ 该常数今日第一次被真判据执法。"
        f"这条红是 S118 预期内的诚实账：处置人＝doc_link 门 owner，"
        f"三条可选路径与推荐见 .superpowers/sdd/2026-09-22-taxonomy/SEAT-S118.md；"
        f"本席不改常数、不放宽判据、不降扫描面。前 5 条：\n" + "\n".join(rows[:5])
    )


def _assert_within_ceiling(
    face: str, rows: list[str], ceiling: int, constant: str
) -> None:
    verdict = _violation(face, rows, ceiling, constant)
    assert verdict is None, verdict


# ---------------------------------------------------------------------------
# 主判据：两枚常数各一枚方向锁（任务书 ①）
# ---------------------------------------------------------------------------
def test_carrier_dead_count_is_within_inbook_baseline() -> None:
    """`_BASELINE_CARRIER_DEAD` 从「无人引用的注释」变成真判据（实测 dead=0 ⇒ 绿）。

    绿的同时它**第一次被断言引用**——该常数值一改，本门立即跟随，不再需要人记着改第二处。
    """
    _assert_within_ceiling(
        "carrier-dead（载体列彻底不存在的死路径）",
        _findings()["dead"],
        dl._BASELINE_CARRIER_DEAD,
        "_BASELINE_CARRIER_DEAD",
    )


def test_carrier_truth_count_is_within_inbook_baseline() -> None:
    """`_BASELINE_CARRIER_TRUTH` 执法：实测 34 > 在册常数 5 ⇒ **本门今日必红**（任务书 ②）。

    不放宽、不豁免、不改那枚数值——红着才是「在册未执法」被治好的证据。
    """
    _assert_within_ceiling(
        "carrier-truth（载体列字面命中真身的条数）",
        _findings()["literal"],
        dl._BASELINE_CARRIER_TRUTH,
        "_BASELINE_CARRIER_TRUTH",
    )


# ---------------------------------------------------------------------------
# ④ 扫描面地板（塌陷即红）＋ 不许凭记忆造数
# ---------------------------------------------------------------------------
def test_scan_face_floor_is_measured_not_invented() -> None:
    rows = _findings()
    total = sum(len(v) for v in rows.values())
    assert total >= _MIN_CARRIER_ROWS, (
        f"载体列四档合计仅 {total} 条 < 地板 {_MIN_CARRIER_ROWS}＝取数口或 AGENTS.md "
        "载体列塌陷；此时 `dead<=0` 一类的零容忍判据会假绿，必须先修扫描面。"
    )
    assert _MIN_CARRIER_ROWS <= total, (
        f"地板 {_MIN_CARRIER_ROWS} 写死在现算值 {total} 之上＝凭空造数，请重录本行注释里的现算命令"
    )


# ---------------------------------------------------------------------------
# ⑥ 正样控制：判据必须看得见「合法件」，否则零容忍档的绿毫无意义
# ---------------------------------------------------------------------------
def test_positive_sample_literal_bucket_is_populated() -> None:
    rows = _findings()["literal"]
    assert rows, (
        "载体列一条「字面即真身」都没判出来＝分类器单向化，"
        "dead/misleading 两档的绿将只是什么都看不见"
    )


# ---------------------------------------------------------------------------
# 门瞎自证（任务书 ②「同时给『若不红则说明门瞎』的自证」）
# ---------------------------------------------------------------------------
def test_judgment_is_threshold_sensitive_at_boundary() -> None:
    """同一判据在临界两侧必须翻面：超限必抛、等于上限必放行。"""
    assert _violation("探针", ["行"] * 6, 5, "_PROBE_") is not None, "超限却没判出来＝判据恒绿"
    assert _violation("探针", ["行"] * 5, 5, "_PROBE_") is None, "恰在上限被判红＝方向锁写歪"
    assert _violation("探针", ["行"] * 1, 0, "_PROBE_") is not None, "零容忍档没牙"


def test_truth_leg_verdict_tracks_data() -> None:
    """真数据＋真常数复算判决：超限而不抛 ⇒ 本自证腿红（证「主腿不红」只可能是门瞎）。"""
    rows = _findings()["literal"]
    ceiling = int(dl._BASELINE_CARRIER_TRUTH)
    if len(rows) > ceiling:
        with pytest.raises(AssertionError):
            _assert_within_ceiling("carrier-truth", rows, ceiling, "_BASELINE_CARRIER_TRUTH")
    else:
        _assert_within_ceiling("carrier-truth", rows, ceiling, "_BASELINE_CARRIER_TRUTH")


# ---------------------------------------------------------------------------
# ③ 反向自测三发（全内存，不落盘）
# ---------------------------------------------------------------------------
def test_poison_a_new_dead_carrier_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """a) 造一枚新死载体 ⇒ 必红（零容忍档真的在数它）。"""
    fake = {
        "literal": [],
        "shim": [],
        "moved": [],
        "dead": ["假能力 | plugins/bot_unified_runtime/never_exists_s118/deadbeef.py"],
    }
    monkeypatch.setattr(sys.modules[__name__], "_findings", lambda: fake)
    with pytest.raises(AssertionError):
        _assert_within_ceiling(
            "carrier-dead", _findings()["dead"], dl._BASELINE_CARRIER_DEAD, "_BASELINE_CARRIER_DEAD"
        )


def test_within_ceiling_poison_is_released(monkeypatch: pytest.MonkeyPatch) -> None:
    """b) 把实测压进上限内 ⇒ 同一判据放行（证它不是恒红的样子货）。"""
    fake = {"literal": ["合格行"] * 3, "shim": [], "moved": [], "dead": []}
    monkeypatch.setattr(sys.modules[__name__], "_findings", lambda: fake)
    _assert_within_ceiling(
        "carrier-truth", _findings()["literal"], dl._BASELINE_CARRIER_TRUTH, "_BASELINE_CARRIER_TRUTH"
    )
    _assert_within_ceiling(
        "carrier-dead", _findings()["dead"], dl._BASELINE_CARRIER_DEAD, "_BASELINE_CARRIER_DEAD"
    )


def _source() -> str:
    return Path(__file__).resolve().read_text(encoding="utf-8")


def test_constants_are_referenced_by_live_verdicts() -> None:
    """c) 常数的值必须真的流进判决；只写在注释/文案里＝「读了常数但没用」重演 ⇒ 本腿必红。

    判据形状：在任一 `test_*` 函数体内，枚名必须以 `dl.<NAME>` 的形态出现在
    `_assert_within_ceiling` / `_violation` 的实参或某个比较式的操作数位置。
    """
    covered = _inboard_referenced_constants(ast.parse(_source()))
    missing = [name for name in _INBOOK_CONSTANTS if name not in covered]
    assert not missing, (
        f"在册常数 {missing} 没有被本门任何判决取用＝执法面被掏空（假绿形态第 37 类复发）"
    )


def test_poison_removing_constant_reference_trips_liveness_lock() -> None:
    """反向自测第三发（任务书 ③c）：把两枚常数的引用摘掉 ⇒ 活性锁必红。

    盘上门是绿的并不证明它在执法——所以本席在**内存副本**里把 `dl._BASELINE_*` 换成裸数字，
    解析同一套 AST 判据，必须当场点名。
    """
    hollow = _source().replace("dl._BASELINE_CARRIER_TRUTH", "5").replace(
        "dl._BASELINE_CARRIER_DEAD", "0"
    )
    assert hollow != _source(), "注毒没生效（字符串没命中）＝本发是空跑"
    covered = _inboard_referenced_constants(ast.parse(hollow))
    lost = [name for name in _INBOOK_CONSTANTS if name not in covered]
    assert lost == list(_INBOOK_CONSTANTS), (
        f"摘掉常数引用后活性锁仍放行（只漏了 {lost}）＝锁没牙，判据太松"
    )


def _inboard_referenced_constants(tree: ast.Module) -> set[str]:
    """AST 现算：哪些在册常量的值真的进了判决（实参位或比较操作数位）。"""
    covered: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test_"):
            continue
        for inner in ast.walk(node):
            buckets: list[ast.expr] = []
            if isinstance(inner, ast.Compare):
                buckets = [inner.left, *inner.comparators]
            elif isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name):
                if inner.func.id not in _VERDICT_HELPERS:
                    continue
                buckets = list(inner.args)
            for expr in buckets:
                covered |= {
                    sub.attr
                    for sub in ast.walk(expr)
                    if isinstance(sub, ast.Attribute) and sub.attr in _INBOOK_CONSTANTS
                }
    return covered


# ---------------------------------------------------------------------------
# ④ 门文件自带自锁：手写字面量不许被改写、不许派生、禁写面不许回改
# ---------------------------------------------------------------------------
_SELF_LOCKED = ("_MIN_CARRIER_ROWS",)


def test_hand_written_ceiling_is_literal_and_never_rebound() -> None:
    """自锁（`ast.Assign` 与 `ast.AnnAssign` **双形态**都认，防「换个写法躲自锁」）。"""
    bound: dict[str, ast.expr | None] = {}
    for node in ast.walk(ast.parse(_source())):
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                bound[target.id] = node.value
            elif isinstance(target, ast.Attribute):
                assert not target.attr.startswith("_BASELINE_"), (
                    f"本门文件试图回改在册常数 {target.attr}＝禁写面，一字不许动"
                )
    for name in _SELF_LOCKED:
        value = bound.get(name)
        assert isinstance(value, ast.Constant) and isinstance(value.value, int), (
            f"{name} 被改成派生表达式或被二次赋值＝地板跟着被检对象一起动，本门结构性失效"
        )
