"""G-CM 棘轮账的**四类锁**：把「只降不升」从散文变成不可谈判的账。

席位 S65（中央调度收编波，2026-09-24 立）。

被检对象
--------
``tests/test_capability_manifest_gate.py``（G-CM 门）里的六枚棘轮常量：四枚旧账
``EXECUTION_SURFACE_BASELINE`` / ``DECLARED_UNWIRED_BASELINE`` /
``PLACEHOLDER_BASELINE`` / ``REGISTERED_FLOOR``，加本波补的两枚分母地板
``DECLARED_SCAN_FLOOR`` / ``ROSTER_SCAN_FLOOR``。

为什么立这件（S37 席 2026-09-23T23:24Z 实锤，本席不再复述其证据）
--------------------------------------------------------------
把 ``EXECUTION_SURFACE_BASELINE`` 从 62 抬到 **999**，门里那条腿**照样全绿**：
旧写法只有「一个数 + 一个裸 ``<=``」——有数、无方向、无"上限==此刻现算"的零余量锁。
"顺手放宽一格先过关再补账"这条路当时无人拦。同波另一本账（
``tests/test_descriptor_wiredness_ledger.py`` 的 ``GAP_CEILING``）已有成链锁，
本件按**同一纪律**给 G-CM 这四枚补账，**不抄它的数字**（两本账各量各的）。

四类锁（每类各拦一种造假手法，互不替代——第 ④ 类那条用例专门证「② 抓不到 ④」）
----------------------------------------------------------------------------
① **方向锁**：方向必须在 ``RATCHET_DIRECTIONS`` 里逐枚申报（唯一声明处），调用点
   必须以 ``direction=RATCHET_DIRECTIONS["<枚名>"]`` 的字面下标形把方向交回执法口；
   常量名后缀（``_BASELINE``/``_CEILING`` ⇒ ceiling、``_FLOOR`` ⇒ floor）即方向的第二份
   独立申报，三方不一致当场红。并禁止任何**裸比较**直接吃这些常量。
② **零余量锁**：每枚 ``基线 == 此刻现算``（不是 ``<=``、不是"留点余量免得老红"）。
   这一把专拦「抬 1 格就好过」：抬上限立刻不等，降地板立刻不等。
③ **反失明锁**：每枚基线在门件源码里必须是**手写整数字面量**（AST 结构）。
   写成 ``= len(现算)``／``= 现算 - 1`` 之类派生式 ⇒ 基线跟着被检对象动 ⇒ 门结构性失效。
④ **扫描面锁**：判据的分母（在册 id 总数 / 本册申报枚数 / 普查 roster 行数）设地板，
   并锁「被扫集合 == 现算全集」；把循环缩成手挑子集 ⇒ 分母掉下来 ⇒ 红。

诚实边界（不得越过去叙述）
------------------------
- 本件**故意不另立第二把尺**：所有现算都调门件自己的 ``measure_*``（判据唯一真身）。
  它独立的是**账的形状**（方向/字面量/分母/调用点），不是同一个数的第二次计数。
  真要独立复算，落点是 ``scripts/capability_manifest_projection_check.py``（第二把尺），
  该件当前被本波 P5 的摘牌动作打死（S37 §2.3，RC=1），**归该件 owner**，本席不越写面修。
- 零余量锁**双向都红**，红法是设计的一部分：现算 > 上限＝真债增加；现算 < 上限＝降了账
  但没复算改账。两条都要求"复算 + 同批改字面量"，读数时刻与尺身份已写进门件常量旁。
- 本件是**静态 + 离线**门：它红了只代表这本账不可信，不代表线上行为坏了；它绿了也**不**
  证明能力已接真（接真的判据在普查件与腿③b 的 state 上）。
- 腿②「执行体可解析」只遍历 ``declared_ids()``（13 枚）而在册 120 枚，其余 107 枚的执行体
  **从不逐枚解析**（S37 §2.2-D 残余）。这是覆盖面问题、不是棘轮方向问题，且其上限
  ``UNCOVERED_CEILING`` 住在 S32 在飞件里 ⇒ **本席未动，见 SEAT-S65.md §4**。

复跑
----
.. code-block:: bash

    cd ChatBot/ChatBot && PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 \\
      PYTHONIOENCODING=utf-8 PYTHONPYCACHEPREFIX=$TEMP/s65-pyc \\
      ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest \\
      tests/test_capability_manifest_ratchet_direction.py \\
      -p no:cacheprovider --basetemp=$TEMP/s65-bt -q
"""

from __future__ import annotations

import ast
import inspect
import re
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _TESTS_DIR.parents[0]
sys.path.insert(0, str(_TESTS_DIR))
sys.path.insert(0, str(_REPO_ROOT))

import test_capability_manifest_gate as gate  # 复用判据真身，禁第二把尺

GATE_PATH = _TESTS_DIR / "test_capability_manifest_gate.py"

#: 方向的两个合法值（与门件 ``_ratchet_check`` 的判定一一对应）。
CEILING = "ceiling"
FLOOR = "floor"

#: 「命名即方向」——第二份独立申报，用来拦"把地板改成 ceiling 就永远过关"这一手。
DIRECTION_BY_SUFFIX: dict[str, str] = {"_BASELINE": CEILING, "_CEILING": CEILING, "_FLOOR": FLOOR}

#: 执法口函数名与它必须交回的方向申报形（``direction=RATCHET_DIRECTIONS["<枚名>"]``）。
_CHECK_FN = "_ratchet_check"
_REGISTRY = "RATCHET_DIRECTIONS"
_MEASURES = "RATCHET_MEASURES"

#: 执法口的必备参数（``detail`` 为可选第四＋1 项，只进报错文案、不进判据）。
_REQUIRED_KWARGS = frozenset({"name", "direction", "baseline", "measured"})


# ------------------------------------------------------------------ 取数与 AST 小件
def _tree() -> ast.Module:
    assert GATE_PATH.is_file(), f"缺门件：{GATE_PATH}"
    return ast.parse(GATE_PATH.read_text(encoding="utf-8"), filename=str(GATE_PATH))


def _assignments(tree: ast.AST) -> dict[str, ast.expr]:
    """模块级「单一目标」赋值：名字 → 值节点（``AnnAssign`` 也算）。"""
    out: dict[str, ast.expr] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out[node.target.id] = node.value
    return out


def _literal_int(node: ast.expr | None) -> int | None:
    """整数字面量判定：``bool`` 被排除（``True`` 是 ``int`` 的子类，但绝不该当账用）。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return node.value
    return None


def _literal_int_of_name(source: str, name: str) -> int | None:
    """同一条判据，但作用在**任意源码文本**上——注毒自证用它，不碰门件一个字节。"""
    return _literal_int(_assignments(ast.parse(source)).get(name))


def _str_dict(node: ast.expr | None) -> dict[str, str] | None:
    """``{"字面量": "字面量"}`` 形态的 dict 才回收，含任何非串成员即 None。"""
    if not isinstance(node, ast.Dict):
        return None
    out: dict[str, str] = {}
    for key, value in zip(node.keys, node.values, strict=True):
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            return None
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            return None
        out[key.value] = value.value
    return out


def _bare_ratchet_comparisons(tree: ast.AST, names: frozenset[str]) -> list[str]:
    """列出**裸比较**里直接吃棘轮常量的位置（①的"禁裸比较"腿）。"""
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        for operand in (node.left, *node.comparators):
            if isinstance(operand, ast.Name) and operand.id in names:
                offenders.append(f"行 {node.lineno}：{ast.unparse(node)[:90]}")
                break
    return offenders


def _check_call_sites(tree: ast.AST) -> tuple[dict[str, ast.Call], list[ast.Call], list[str]]:
    """返回（合规调用点 ``账名→调用``，全部调用点，"判定被短路"清单）。

    合规＝该调用是某个 ``test_*`` 函数**体首层**的表达式语句，且前面没有 ``return``。
    藏在 ``if``/``try``/循环/嵌套函数里、被包进 ``BoolOp``（``... or True``）、整条被删、
    或**函数体内先 return 再判定**，都不算合规——最后这一形最容易写也最难看出来：
    形状全对、判定永不触发。
    """
    all_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == _CHECK_FN
    ]
    ok: dict[str, ast.Call] = {}
    disabled: list[str] = []
    for func in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        if not func.name.startswith("test_"):
            continue
        for index, stmt in enumerate(func.body):
            if isinstance(stmt, ast.Return):
                for later in func.body[index + 1:]:
                    if isinstance(later, ast.Expr) and later.value in all_calls:
                        key = _kwarg(later.value, "name")
                        label = key.value if isinstance(key, ast.Constant) else "?"
                        disabled.append(
                            f"{func.name} 行 {later.lineno} 的判定（{label}）排在 return 之后＝永不触发")
            if isinstance(stmt, ast.Expr) and stmt.value in all_calls:
                name = _kwarg(stmt.value, "name")
                if isinstance(name, ast.Constant) and isinstance(name.value, str):
                    ok[name.value] = stmt.value
    return ok, all_calls, disabled


def _kwarg(call: ast.Call, arg: str) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg == arg:
            return keyword.value
    return None


def _name_suffix(name: str) -> str | None:
    """命名字面上像不像一本棘轮账（返回命中的后缀，用于"漏登记"探测）。"""
    return next((suffix for suffix in DIRECTION_BY_SUFFIX if name.endswith(suffix)), None)


def _direction_implied_by_name(name: str) -> str | None:
    """「命名即方向」：后缀翻成方向；后缀不认识 ⇒ None（方向不可由名字判，另条红）。"""
    suffix = _name_suffix(name)
    return None if suffix is None else DIRECTION_BY_SUFFIX[suffix]


def _measured(name: str) -> int:
    """按 ``RATCHET_MEASURES`` 的申报取现算尺（不在此处手写任何计数）。"""
    fn_name = gate.RATCHET_MEASURES[name]
    fn = getattr(gate, fn_name, None)
    assert callable(fn), f"门件里没有现算尺函数 {fn_name}（尺身份断链）"
    return int(fn())


_NAMES = frozenset(gate.RATCHET_DIRECTIONS)


# ============================================== ① 方向锁
def test_registry_covers_every_ratchet_constant_and_is_literal() -> None:
    """账本自封：``RATCHET_DIRECTIONS``/``RATCHET_MEASURES`` 必须是字面量 dict、
    两边键集相等、且门件里**每一枚**后缀像账的常量都被登记（漏登记＝有账无人管）。"""
    assigns = _assignments(_tree())
    directions = _str_dict(assigns.get(_REGISTRY))
    measures = _str_dict(assigns.get(_MEASURES))
    assert directions is not None, f"{_REGISTRY} 不是纯字面量 dict＝方向申报被改成派生式"
    assert measures is not None, f"{_MEASURES} 不是纯字面量 dict"
    assert directions, "方向申报册为空＝六枚账的账本被清空"
    assert set(directions) == set(measures), (
        f"方向账与现算尺账键集不符：仅方向有={sorted(set(directions) - set(measures))} "
        f"仅尺有={sorted(set(measures) - set(directions))}")
    missing = sorted(name for name in directions if name not in assigns)
    assert not missing, f"申报了方向却在门件里找不到账值赋值行（账本与现实脱钩）：{missing}"
    # 注：账值**是不是字面量**不由本条判——那是③反失明锁的活，两条各管一面，
    # 否则一发注毒会同时打红两把，红不可归因。
    unregistered = sorted(
        name for name, value in assigns.items()
        if _name_suffix(name) is not None and _literal_int(value) is not None
        and name not in directions)
    assert not unregistered, f"这些账有字面量、像棘轮命名，却没进方向申报册（漏管）：{unregistered}"


def test_direction_matches_name_suffix() -> None:
    """「命名即方向」：``*_FLOOR`` 只能是地板、``*_BASELINE``/``*_CEILING`` 只能是上限。

    这一把拦的是"方向改标"：把 ``REGISTERED_FLOOR`` 的方向改成 ``ceiling``，活账
    ``120 <= 120`` 立刻通过（＝地板失效），但后缀与申报不符 ⇒ 当场红。
    """
    bad = []
    for name, declared in sorted(gate.RATCHET_DIRECTIONS.items()):
        expected = _direction_implied_by_name(name)
        if expected is None:
            bad.append(f"{name}：名字后缀不属于 {sorted(DIRECTION_BY_SUFFIX)}，方向不可由名字判")
        elif declared != expected:
            bad.append(f"{name}：申报 {declared!r} 而后缀要求 {expected!r}")
    assert not bad, "方向申报与命名冲突（改标换绿嫌疑）：" + "；".join(bad)


def test_measure_functions_exist_and_take_no_required_args() -> None:
    """每枚账的现算尺必须是门件里**零必填参数**的函数（有参＝可以被喂好看的数）。"""
    problems = []
    for name, fn_name in sorted(gate.RATCHET_MEASURES.items()):
        fn = getattr(gate, fn_name, None)
        if not callable(fn):
            problems.append(f"{name}→{fn_name} 取不到函数")
            continue
        params = [
            p for p in inspect.signature(fn).parameters.values()
            if p.default is inspect.Parameter.empty
            and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
        ]
        if params:
            problems.append(f"{name}→{fn_name} 有必填参数 {[p.name for p in params]}＝活账取不到数")
    assert not problems, "现算尺不可信：" + "；".join(problems)


def test_call_sites_declare_direction_and_are_top_level() -> None:
    """调用点形状：每枚账**恰一处**调用、位置在 ``test_*`` 体首层、四个 kwarg 齐形：

    ``name=`` 字面量串＝账名；``direction=`` 必须是 ``RATCHET_DIRECTIONS["<账名>"]`` 的
    字面下标形（不许写裸串，更不许由循环动态生成）；``baseline=`` 必须是该账常量的名字；
    ``measured=`` 必须是申报的那把现算尺的**零参调用**（不许写字面 0、不许写 ``len(...)``）。
    """
    ok, all_calls, disabled = _check_call_sites(_tree())
    assert not disabled, "判定被短路（return 在前），形状全对却永不触发：" + "；".join(disabled)
    assert len(all_calls) == len(_NAMES), (
        f"执法口调用点共 {len(all_calls)} 处，与账数 {len(_NAMES)} 不符")
    assert set(ok) == set(_NAMES), (
        f"合规调用点与账本不符：仅账本有={sorted(_NAMES - set(ok))} "
        f"仅调用有={sorted(set(ok) - _NAMES)}（判据被挪进 if/循环/或被 `or True` 包起来＝形状不合规）")
    measures = gate.RATCHET_MEASURES
    problems: list[str] = []
    for name, call in sorted(ok.items()):
        given = {keyword.arg for keyword in call.keywords}
        if given not in (_REQUIRED_KWARGS, _REQUIRED_KWARGS | {"detail"}):
            problems.append(f"{name}：kwarg 集合不合规（{sorted(given)}）")
        direction = _kwarg(call, "direction")
        if not (isinstance(direction, ast.Subscript)
                and isinstance(direction.value, ast.Name) and direction.value.id == _REGISTRY
                and isinstance(direction.slice, ast.Constant) and direction.slice.value == name):
            problems.append(f"{name}：direction 未由 {_REGISTRY}[{name!r}] 申报")
        baseline = _kwarg(call, "baseline")
        if not (isinstance(baseline, ast.Name) and baseline.id == name):
            problems.append(f"{name}：baseline 参数不是同名常量")
        measured = _kwarg(call, "measured")
        if not (isinstance(measured, ast.Call) and isinstance(measured.func, ast.Name)
                and measured.func.id == measures[name] and not measured.args and not measured.keywords):
            problems.append(f"{name}：measured 不是 {measures[name]}() 的零参调用")
    assert not problems, "调用点失去可归因性：" + "；".join(problems)


def test_no_bare_comparison_against_ratchet_constants() -> None:
    """禁裸比较：这些常量只能经 ``_ratchet_check`` 参与判定，不许再被 ``<=``/``>=``/``==`` 直吃。

    裸比较＝"方向语义只活在注释里"的源头（S37 实锤的那种写法）。
    """
    offenders = _bare_ratchet_comparisons(_tree(), _NAMES)
    assert not offenders, "棘轮常量被裸比较直接吃（方向未申报）：" + "；".join(offenders)


def test_bare_comparison_predicate_has_teeth() -> None:
    """①自证：把"裸比较"这一手在合成源码上跑同一条判据，必须抓到（防判据只活在自己的脑里）。"""
    names = frozenset({"PLACEHOLDER_BASELINE"})
    guilty = "def test_x() -> None:\n    assert len(rows) <= PLACEHOLDER_BASELINE\n"
    innocent = "def test_x() -> None:\n    assert len(rows) <= len(allowed)\n"
    assert _bare_ratchet_comparisons(ast.parse(guilty), names), "注毒样本未被抓到＝这条锁无牙"
    assert not _bare_ratchet_comparisons(ast.parse(innocent), names), "放行样本被误抓＝判据过宽"


def test_ratchet_check_entry_point_is_fail_closed() -> None:
    """执法口本身三向验牙：ceiling 只放行「不升」、floor 只放行「不降」、未知方向必红。"""
    with pytest.raises(AssertionError, match="既不是 ceiling 也不是 floor"):
        gate._ratchet_check(name="X", direction="sideways", baseline=1, measured=1)
    with pytest.raises(AssertionError, match="超过上限"):
        gate._ratchet_check(name="X", direction=CEILING, baseline=1, measured=2)
    gate._ratchet_check(name="X", direction=CEILING, baseline=2, measured=1)
    with pytest.raises(AssertionError, match="跌破地板"):
        gate._ratchet_check(name="X", direction=FLOOR, baseline=2, measured=1)
    gate._ratchet_check(name="X", direction=FLOOR, baseline=1, measured=2)


def test_live_ledgers_satisfy_declared_direction() -> None:
    """①活账腿：六枚账按**各自申报的方向**与此刻现算比一次。"""
    for name in sorted(_NAMES):
        gate._ratchet_check(
            name=name,
            direction=gate.RATCHET_DIRECTIONS[name],
            baseline=int(getattr(gate, name)),
            measured=_measured(name),
        )


# ============================================== ② 零余量锁
@pytest.mark.parametrize("name", sorted(_NAMES))
def test_ratchet_baselines_equal_live_measurement(name: str) -> None:
    """②零余量：``基线 == 此刻现算``，**不许留一格余量**。

    这是唯一能拦住"把基线抬高 1 就好过"的锁（方向锁与结构锁都拦不住它——63 仍是
    手写字面量、62<=63 仍满足 ceiling）。红了只有两条诚实路径，两条都要复算：
      上限：真消化一枚 ⇒ 把常量改小到现算值；
      地板：名册合法增长 ⇒ 把常量改大到现算值。
    读数时刻、尺身份三元组、复跑命令写在门件常量旁（``test_capability_manifest_gate.py``
    的「棘轮账」段）与本席报告 §1。
    """
    baseline = int(getattr(gate, name))
    measured = _measured(name)
    assert baseline == measured, (
        f"{name} 登记 {baseline}、此刻现算 {measured}（差 {measured - baseline:+d}，"
        f"方向 {gate.RATCHET_DIRECTIONS[name]}）＝账与实况脱钩。抬上限换绿当场拦；"
        "真降账请复算后同批改字面量。")


# ============================================== ③ 反失明锁
def test_ratchet_baselines_are_hand_written_literals() -> None:
    """③反失明：六枚基线在门件源码里必须是**手写整数字面量**。

    派生式（``= len(cm.PLACEHOLDER_UNIMPLEMENTED)``／``= 现算 - 1``）会让基线跟着被检
    对象一起动 ⇒ ②的等值锁自动永远成立 ⇒ 整本账结构性失明。这一把是②的前提。
    """
    assigns = _assignments(_tree())
    problems: list[str] = []
    for name in sorted(_NAMES):
        node = assigns.get(name)
        if node is None:
            problems.append(f"{name} 在门件里找不到模块级赋值")
            continue
        if _literal_int(node) is None:
            problems.append(f"{name} = {ast.unparse(node)[:60]!r} 不是整数字面量")
    assert not problems, "基线被写成派生式或缺位：" + "；".join(problems)


@pytest.mark.parametrize(("source", "expected"), [
    ("PLACEHOLDER_BASELINE = 0\n", 0),
    ("PLACEHOLDER_BASELINE = 62\n", 62),
])
def test_literal_predicate_accepts_only_literals_positive(source: str, expected: int) -> None:
    assert _literal_int_of_name(source, "PLACEHOLDER_BASELINE") == expected


@pytest.mark.parametrize("source", [
    "PLACEHOLDER_BASELINE = len(cm.PLACEHOLDER_UNIMPLEMENTED)\n",
    "PLACEHOLDER_BASELINE = 62 - 1\n",
    "PLACEHOLDER_BASELINE = REGISTERED_FLOOR\n",
    "PLACEHOLDER_BASELINE = int('3')\n",
    "PLACEHOLDER_BASELINE = [1, 2][0]\n",
    "PLACEHOLDER_BASELINE = 0 if rows else 1\n",
    "PLACEHOLDER_BASELINE = sum(1 for _ in rows)\n",
    "PLACEHOLDER_BASELINE = -1\n",
])
def test_literal_predicate_rejects_derived_forms(source: str) -> None:
    """③自证：八种"看起来也等于现算"的写法必须一律被拒——包括**负数字面量**
    （``UnaryOp`` 不是 ``Constant``，而负数根本不可能是合法账值）。"""
    assert _literal_int_of_name(source, "PLACEHOLDER_BASELINE") is None


# ============================================== ④ 扫描面锁
def test_denominators_are_the_full_live_sets() -> None:
    """④分母完整性：三条判据的**被扫集合必须就是现算全集**，且不低于各自地板。

    分子掉了但分母也掉了，不叫降账——那叫把尺子锯短。三对都当场核：
      腿⑤ 被扫枚数 == 在册 id 总数；腿③b 被扫枚数 == 本册申报枚数；
      roster 行数 == 普查件自报的行数（且非空）。
    """
    _, exec_scanned = gate.execution_surface_rows()
    _, _, declared_scanned = gate.declared_unwired_rows()
    registered_total = len(gate.registered_capability_ids())
    declared_total = len(gate.cm.declared_ids())
    assert exec_scanned == registered_total, (
        f"腿⑤扫描面 {exec_scanned} ≠ 在册总数 {registered_total}＝循环被缩")
    assert declared_scanned == declared_total, (
        f"腿③b扫描面 {declared_scanned} ≠ 本册申报枚数 {declared_total}＝循环被缩")
    roster_rows = gate.measure_roster_rows()
    assert roster_rows == len(gate._census()["roster"]) and roster_rows > 0, (
        f"普查 roster 行数 {roster_rows} 不自洽或为空＝量具瞎")
    assert registered_total >= gate.REGISTERED_FLOOR
    assert declared_scanned >= gate.DECLARED_SCAN_FLOOR
    assert roster_rows >= gate.ROSTER_SCAN_FLOOR


def test_live_path_does_not_use_the_injection_seam() -> None:
    """④诚实腿：活账必须走真普查件，注入缝只在自证用例里被显式喂参。

    否则"注入形"会变成第二条通路——活账拿合成名册算出好看的数（本波同型事故见
    AGENTS #50「测夹具不测代码」两回）。
    """
    params = inspect.signature(gate.declared_unwired_rows).parameters
    for seam in ("roster", "declared"):
        assert seam in params, f"注入缝 {seam} 不见了＝④的两条自证会退化成空跑"
        assert params[seam].default is None, f"注入缝 {seam} 的缺省不再是 None＝活账可能被喂假数据"
    unwired, blind, scanned = gate.declared_unwired_rows()
    real = [cid for cid in sorted(gate.cm.declared_ids()) if gate._state_of(cid) != "wired"]
    assert unwired == real, f"活账未接真普查：{unwired} vs {real}"
    assert blind == [] and scanned == len(gate.cm.declared_ids())
    assert gate.measure_declared_scan() == len(gate.cm.declared_ids())


def test_declared_side_shrink_with_unchanged_numerator_is_caught() -> None:
    """④牙口自证（分母侧之一）：循环少看一枚**已 wired 的已申报能力**——

    分子逐枚不变 ⇒ ②零余量锁看不见它；被扫枚数 −1 ⇒ ``DECLARED_SCAN_FLOOR`` 当场红。
    这条用例的存在理由＝证明 ④ 不可由 ② 代劳，不是装饰。注入缝等价于"有人把
    ``for cid in ids`` 缩成手挑子集"这一手法，判据本身一行未动。
    """
    unwired_live, _, scanned_live = gate.declared_unwired_rows()
    wired_declared = [cid for cid in sorted(gate.cm.declared_ids())
                      if gate._state_of(cid) == "wired"]
    assert wired_declared, (
        "注入样本失效：本册已无「已 wired 的已申报能力」可摘 ⇒ 请改用别的分母注毒，"
        "别把本条改成放宽判据（本波实测 victim=creation.tts.synthesize）")
    victim = wired_declared[0]
    narrowed = [cid for cid in sorted(gate.cm.declared_ids()) if cid != victim]

    unwired_poison, blind_poison, scanned_poison = gate.declared_unwired_rows(declared=narrowed)
    assert unwired_poison == unwired_live, "注毒把分子也改了＝这条自证失去区分力"
    assert blind_poison == [] and scanned_poison == scanned_live - 1
    assert scanned_poison == gate.DECLARED_SCAN_FLOOR - 1
    with pytest.raises(AssertionError, match="跌破地板"):
        gate._ratchet_check(
            name="DECLARED_SCAN_FLOOR", direction=FLOOR,
            baseline=gate.DECLARED_SCAN_FLOOR, measured=scanned_poison)
    # 反面对照（同一条注毒数据交给②的等值判据看）：分子账此刻"看起来"完全没坏。
    assert len(unwired_poison) == gate.DECLARED_UNWIRED_BASELINE == gate.measure_declared_unwired()


def test_roster_side_shrink_is_caught_by_ceiling_or_blindness() -> None:
    """④牙口自证（分母侧之二）：普查 roster 少一行 ⇒ 两把都拦得住，且各说各的话。

    - 从名册里摘掉一枚**已申报且 wired** 的行：该 id 变成"看不见"（腿③b 的失明锁抓，
      这是既有牙，S37 §2.2-C 当时判它"真有牙"，本席复证）；
    - roster 总行数 −1：``ROSTER_SCAN_FLOOR`` 抓（本席新加的地板）。
    两条同轴（④），分工不同：失明锁管"已申报的别丢"，地板管"量具整体别看少了"。
    """
    roster = dict(gate._census()["roster"])
    unwired_live, _, _ = gate.declared_unwired_rows()
    victims = [cid for cid in sorted(gate.cm.declared_ids())
               if gate._state_of(cid) == "wired" and cid in roster]
    assert victims, "注入样本失效：无「在册且进过普查」的 wired 能力可摘，改判据前先重推样本"
    victim = victims[0]
    shrunk = {cid: row for cid, row in roster.items() if cid != victim}

    unwired_poison, blind_poison, _ = gate.declared_unwired_rows(roster=shrunk)
    assert blind_poison == [victim], "失明锁的取数路径变了，本自证需重推"
    assert unwired_poison == unwired_live
    assert len(shrunk) == gate.ROSTER_SCAN_FLOOR - 1
    with pytest.raises(AssertionError, match="跌破地板"):
        gate._ratchet_check(
            name="ROSTER_SCAN_FLOOR", direction=FLOOR,
            baseline=gate.ROSTER_SCAN_FLOOR, measured=len(shrunk))


# ============================================== 账本自身的出处锁
def test_measurement_provenance_is_written_next_to_the_numbers() -> None:
    """每枚账的**读数时刻 + 尺身份**必须留在门件常量旁（离开这两样数字就不成立）。

    只改数不写证据＝本波禁令。这里核三样：一次 ``20xx-xx-xxT..Z`` 读数戳、
    「尺身份三元组」段、以及六枚账名与 ``measure_`` 函数名在同一段文本里可寻。
    """
    source = GATE_PATH.read_text(encoding="utf-8")
    assert "尺身份三元组" in source, "门件常量旁缺尺身份段"
    stamps = sorted(set(re.findall(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", source)))
    assert stamps, "门件里找不到任何 ISO-8601 UTC 读数时刻＝账无出处"
    assert "2026-09-24T00:19:08Z" in stamps, (
        f"本波 S65 现算读数戳（2026-09-24T00:19:08Z）不在门件中（stamps={stamps}）")
    for name in sorted(_NAMES):
        assert f"{name} =" in source, f"门件里找不到 {name} 的赋值行"
