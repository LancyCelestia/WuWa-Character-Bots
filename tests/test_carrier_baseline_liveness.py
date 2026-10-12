"""载体列两枚「在册但未执法」常数的**活性门**（席 S118，2026-09-22 立）。

任务书一句话：`tests/test_doc_link_integrity.py` 里

- `:96 _BASELINE_CARRIER_DEAD = 0` —— 注释自证「本常量当前不被任何断言引用」；
- `:99 _BASELINE_CARRIER_TRUTH = 5` —— 注释自证「当前实测 34 ⇒ 门仍绿」；

两枚**存在但不执法**（S111 的 C-1，假绿形态候选第 37 类）。本门把它们变成真判据，
禁写面一字不碰：不 `import` 改写、不加 skip/xfail、不回改它的断言、不动那两枚数值。

设计约束（任务书 S118 ①–④）：

1. **单一取数口**＝直接调既有门的 `collect_carrier_findings()`，本席零逻辑副本、零第二本账；
2. **方向锁**＝「实测条数只准 ≤ 在册常数」（任务书 ① 原文照做，两枚同理）；
   ⚠ **2026-10-13 修红席 P2-capability-ledgers 改形（判据本身改形，随判据一起改并写明理由）**：
   `_BASELINE_CARRIER_DEAD` 的真身语义是 HARD 零容忍（源件 `test_doc_link_integrity.py` 的
   `test_agents_carrier_paths_no_dead_entries` 断言 `assert not rows`）⇒ **上限**方向正确，原样保留；
   但 `_BASELINE_CARRIER_TRUTH` 在**源件**里被明确标为 **FLOOR**（源件行内注释「# FLOOR（真身实测
   底线…）」，且源件 `test_agents_carrier_truth_floor` 断言 `n >= _BASELINE_CARRIER_TRUTH`）——
   本门当年「两枚同理」把它也当上限执法，属**方向建模错**（口径冲突原委见
   `.superpowers/sdd/2026-09-22-taxonomy/SEAT-S118.md` §5，处置归 doc_link 门 owner；S118 建议族
   ＝「按源件 FLOOR 语义收口」）。修法＝给 TRUTH 另立**地板判据**（`_violation_floor` /
   `_assert_at_least_floor`，方向只准 ≥），常量值一字未动（源件 5 不动、本门 `_MIN_CARRIER_ROWS`
   不动、扫描面不缩）；**不是**「抬上限换绿」。
3. **诚实账**＝carrier-truth 现算 **38**（2026-10-13 复算；S118 立门时 34）**远高于**源件地板 5
   ⇒ 按 FLOOR 语义本门应当**绿**（"载体列字面命中真身至少 5 条"已远超）。原先按上限执法 ⇒ 必红，
   那条红是**方向建模错**、不是数据坏；改形后本门绿，而真·塌陷（命中数跌破地板）仍当场红。
   处置与三条可选路径原委见 `.superpowers/sdd/2026-09-22-taxonomy/SEAT-S118.md`。
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
_VERDICT_HELPERS = (
    "_assert_within_ceiling",
    "_violation",
    "_assert_at_least_floor",
    "_violation_floor",
)


def _violation(face: str, rows: list[str], ceiling: int, constant: str) -> str | None:
    """上限方向锁：实测条数只准 ≤ 在册常数；返回 `None` 即放行，否则给人话判决。"""
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


def _violation_floor(face: str, rows: list[str], floor: int, constant: str) -> str | None:
    """地板方向锁（2026-10-13 修红席补，专供源件语义为 FLOOR 的 `_BASELINE_CARRIER_TRUTH`）：

    实测条数只准 ≥ 在册地板；返回 `None` 即放行，否则给人话判决。
    与 `_violation` 同形不同向——两枚常数的**真身语义不同**（DEAD=HARD 零容忍上限、
    TRUTH=源件明确标注的 FLOOR），故各用各的方向，不再「两枚同理」。
    """
    if len(rows) >= floor:
        return None
    return (
        f"{face}：实测 {len(rows)} 条 < 在册地板 {constant} = {floor}"
        f"（方向锁：只准 ≥）⇒ 载体列扫描面塌陷，或该常数被凭空抬高。"
        f"源件语义＝FLOOR（test_doc_link_integrity.py 的 `n >= _BASELINE_CARRIER_TRUTH`）。"
        f"前 5 条：\n" + "\n".join(rows[:5])
    )


def _assert_at_least_floor(
    face: str, rows: list[str], floor: int, constant: str
) -> None:
    verdict = _violation_floor(face, rows, floor, constant)
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
    """`_BASELINE_CARRIER_TRUTH` 执法（**地板方向**，2026-10-13 修红席改形）。

    源件（`test_doc_link_integrity.py`）把该常数明确标为 **FLOOR** 并以 `n >= 该值` 断言；
    本门原按上限执法 ⇒ 现算 38 > 5 必红（方向建模错）。改形后按 FLOOR 语义判：实测 38 ≥ 5 ⇒ 绿，
    而真·塌陷（命中数跌破 5）仍当场红。常量值一字未动、扫描面不缩。
    """
    _assert_at_least_floor(
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
    """同一判据在临界两侧必须翻面：超限必抛、等于上限必放行；地板侧同理（低必抛、等于必放行）。"""
    assert _violation("探针", ["行"] * 6, 5, "_PROBE_") is not None, "超限却没判出来＝判据恒绿"
    assert _violation("探针", ["行"] * 5, 5, "_PROBE_") is None, "恰在上限被判红＝方向锁写歪"
    assert _violation("探针", ["行"] * 1, 0, "_PROBE_") is not None, "零容忍档没牙"
    # 地板侧（2026-10-13 修红席补）：跌破地板必抛、等于地板必放行
    assert _violation_floor("探针", ["行"] * 4, 5, "_PROBE_") is not None, "跌破地板却没判出来＝地板腿恒绿"
    assert _violation_floor("探针", ["行"] * 5, 5, "_PROBE_") is None, "恰在地板被判红＝地板方向写歪"


def test_truth_leg_verdict_tracks_data() -> None:
    """真数据＋真常数复算判决：跌破地板而不抛 ⇒ 本自证腿红（证「主腿不红」只可能是门瞎）。"""
    rows = _findings()["literal"]
    floor = int(dl._BASELINE_CARRIER_TRUTH)
    if len(rows) < floor:
        with pytest.raises(AssertionError):
            _assert_at_least_floor("carrier-truth", rows, floor, "_BASELINE_CARRIER_TRUTH")
    else:
        _assert_at_least_floor("carrier-truth", rows, floor, "_BASELINE_CARRIER_TRUTH")


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
    """b) 把实测压进上限内（TRUTH 侧＝抬到地板之上）⇒ 同一判据放行（证它不是恒红的样子货）。"""
    fake = {
        "literal": ["合格行"] * (int(dl._BASELINE_CARRIER_TRUTH) + 1),
        "shim": [],
        "moved": [],
        "dead": [],
    }
    monkeypatch.setattr(sys.modules[__name__], "_findings", lambda: fake)
    _assert_at_least_floor(
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
