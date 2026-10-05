"""亲密路由四张来源集的"各立一轴"结构锁（加固席 seat-setlock，2026-10-04）。

要防的事故（AGENTS 台账 #76 / content_route 模块头那节注释）：授予面与换模型面
**今天成员恰好同形**——"顺手把两张相同的集合并成一枚"看起来零成本，但一枚答
"要不要展开五维叙述"、一枚答"要不要换真实头"、一枚答"这钉该不该被 max_ttl 悄悄截"、
一枚答"重启后该以什么来源重钉"。并成一枚之后，任何一侧独立放宽都会**静默把另一侧
一起放大**（自动好感度腿白拿五维描写），正是她 09-28 立的那句「换了个档，结果文风
全部都变了」。

本文件钉的是**结构面**，不重复 `test_rp_style_directives.py` 已锁的逐来源授予读数与
`content_signal`-vs-TTL 静态探针：
  (a) 四轴（外加同族的 `_SHALLOW_DEFAULT_SOURCES`）必须是**互不相同的对象**——
      `is not`，绝不许是别名；
  (b) 每张集合在模块里**只准被绑定一次**（AST 扫描，第二处定义＝第二真身）；
  (c) 叙述授予**不可从**换模型轴或 TTL 轴**推得**——用哨兵来源做行为注入，
      证明 `grants_intimate_narration` 只读授予轴、`_head_if_switchable` 只读换模型轴。

判据一律**从代码现取**：成员表从不抄进本文件（本仓家规：测试里手抄一份成员清单＝缺陷）。
哨兵来源是合成串（不属于任何真来源），注入靠 `frozenset 原值 | {哨兵}` 现算，
monkeypatch 自动回滚。
"""
from __future__ import annotations

import ast
from pathlib import Path

from plugins.bot_unified_runtime.domains.chat_reply.runtime import content_route as cr

# 五张同族来源集（轴）。命名即真身，成员绝不写死在这里。
_AXIS_NAMES: tuple[str, ...] = (
    "_INTIMATE_NARRATION_SOURCES",
    "_MODEL_SWITCH_SOURCES",
    "_MAX_TTL_EXEMPT_SOURCES",
    "_EXPLICIT_PIN_REPIN_SOURCES",
    "_SHALLOW_DEFAULT_SOURCES",
)

# 合成哨兵：不属于任何真来源（真来源＝manual_command/admin_pin/master_love/
# content_signal/affinity_tier/""），只用来在内存里临时撑一张集、看判据跟哪张走。
_SENTINEL = "lock_axis_sentinel_source"

# 模块真身源码（AST 扫描用；cr.__file__ 始终指向 .py，即使有旁车 pyc）。
_MODULE_SRC = Path(cr.__file__).read_text(encoding="utf-8")


def _count_bindings(src: str, name: str) -> int:
    """数整棵树里对 `name` 的**绑定**次数（模块级或嵌套的 Assign / AnnAssign 目标）。

    返回 1＝只有一处真身定义；>1＝出现了第二处赋值（第二真身），本锁要拦的就是这个。
    """
    tree = ast.parse(src)
    total = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign):
            target = node.target
            if isinstance(target, ast.Name) and target.id == name:
                total += 1
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    total += 1
    return total


# ---------------------------------------------------------------- (a) 对象互异


def test_axes_are_distinct_objects_never_aliases() -> None:
    """四轴（加同族第五张）必须两两是不同对象：`is not`。

    永久锁，不随值放宽而动——今天成员同形的两张（narration/model_switch、
    repin/shallow_default）也必须是两枚独立 frozenset。有人图省事写
    `_INTIMATE_NARRATION_SOURCES = _MODEL_SWITCH_SOURCES`（别名）即在此处翻红。
    """
    objects = {name: getattr(cr, name) for name in _AXIS_NAMES}
    for name, obj in objects.items():
        assert isinstance(obj, frozenset), f"{name} 已不再是 frozenset"
    for i in range(len(_AXIS_NAMES)):
        for j in range(i + 1, len(_AXIS_NAMES)):
            a_name = _AXIS_NAMES[i]
            b_name = _AXIS_NAMES[j]
            assert objects[a_name] is not objects[b_name], (
                f"两轴被并成同一对象（别名）: {a_name} is {b_name}"
            )


def test_coincident_axes_are_equal_today_yet_distinct_objects() -> None:
    """记录两处"今天恰好同形"的巧合：值相等，但必须是不同对象。

    这里断言 `==`（今天相等）而非 `!=`——若有人日后**正当**地把两轴放宽到不同成员，
    这行会红并要求他确认那是有意的轴分离（不是把一枚并掉）；而真正拦住"合并成一枚"
    的是同段落里那句 `is not`。合并＝别名＝`is not` 翻红，需要书面裁定才准改。
    """
    # 巧合①**已被 10-04 G-2 裁定正当解除**（本行 docstring 早写着"日后正当放宽会红、要求确认"）：
    # 叙述授予面新增第 4 支 `narration_pin`（描写档 `scene` 的显式钉），而**换模型面不跟着长**
    # ⇒ 关系从"相等"改为"**严格子集**"：换模型仍是叙述授予的子集，两轴仍是不同对象。
    assert cr._MODEL_SWITCH_SOURCES < cr._INTIMATE_NARRATION_SOURCES
    assert cr._INTIMATE_NARRATION_SOURCES is not cr._MODEL_SWITCH_SOURCES
    # 反向咬合：新那支**只给叙述、不换模型、不豁免 TTL**——谁把它塞进去（＝重新并轴）当场红。
    assert cr.INTIMATE_SOURCE_NARRATION_PIN in cr._INTIMATE_NARRATION_SOURCES
    assert cr.INTIMATE_SOURCE_NARRATION_PIN not in cr._MODEL_SWITCH_SOURCES
    assert cr.INTIMATE_SOURCE_NARRATION_PIN not in cr._MAX_TTL_EXEMPT_SOURCES
    # 巧合②：重钉来源面 == 缺省浅档来源面（同族里另一对今天同形的集合）。
    assert cr._EXPLICIT_PIN_REPIN_SOURCES == cr._SHALLOW_DEFAULT_SOURCES
    assert cr._EXPLICIT_PIN_REPIN_SOURCES is not cr._SHALLOW_DEFAULT_SOURCES
    # 反向对照：TTL 豁免面**不是**授予面的子集别名，且成员更少（真值差异，非别名）。
    assert cr._MAX_TTL_EXEMPT_SOURCES is not cr._INTIMATE_NARRATION_SOURCES
    assert cr._MAX_TTL_EXEMPT_SOURCES < cr._INTIMATE_NARRATION_SOURCES


# ---------------------------------------------------------------- (b) 只定义一次


def test_each_source_axis_is_bound_exactly_once() -> None:
    """每张来源集在模块里只准有一处绑定：AST 现扫真身源码。

    第二处定义＝第二真身（本仓反复定罪的那类"改一处忘另一处"）。判据从代码结构取，
    不碰成员。若有人把某张集挪到别处再赋一遍值（或加了个条件重定义），计数会变 2 而翻红。
    """
    for name in _AXIS_NAMES:
        count = _count_bindings(_MODULE_SRC, name)
        assert count == 1, f"{name} 在模块里被绑定 {count} 次（应为唯一真身 1 次）"


def test_binding_scan_is_sensitive_self_poison() -> None:
    """自证扫描尺有牙：给真身源码追加一行重复绑定，计数必须从 1 变 2。

    没这层自证，(b) 那条锁可能"写完即空转"（AST 解析口径写错、永远数到 1 也说不准）。
    这里只在内存字符串上动手，绝不落盘、绝不改真身文件。
    """
    poisoned_src = _MODULE_SRC + "\n_INTIMATE_NARRATION_SOURCES = frozenset()\n"
    assert _count_bindings(_MODULE_SRC, "_INTIMATE_NARRATION_SOURCES") == 1
    assert _count_bindings(poisoned_src, "_INTIMATE_NARRATION_SOURCES") == 2, (
        "AST 扫描尺对'第二处定义'无感＝锁已空转"
    )


# ---------------------------------------------------------------- (c) 不可从别轴推得


def test_grant_predicate_reads_grant_axis_not_model_axis(monkeypatch) -> None:
    """叙述授予判据只跟授予轴走，**绝不**跟着换模型轴走。

    正向：只把哨兵塞进授予轴 ⇒ grants(哨兵) 变 True，而它仍不在换模型轴里 ⇒
    "被授予"与"会换模型"行为上可分。
    反向（这才是牙）：只把哨兵塞进**换模型轴**、授予轴不动 ⇒ grants(哨兵) 必须仍是
    False。若有人把 `grants_intimate_narration` 改读 `_MODEL_SWITCH_SOURCES`
    （并轴），这一句立刻翻红——而今天两轴成员相同，靠真实来源根本看不出这种并轴，
    只有哨兵注入能抓。
    """
    assert _SENTINEL not in cr._INTIMATE_NARRATION_SOURCES
    assert _SENTINEL not in cr._MODEL_SWITCH_SOURCES

    monkeypatch.setattr(
        cr, "_INTIMATE_NARRATION_SOURCES", cr._INTIMATE_NARRATION_SOURCES | {_SENTINEL}
    )
    assert cr.grants_intimate_narration(_SENTINEL) is True
    assert _SENTINEL not in cr._MODEL_SWITCH_SOURCES
    monkeypatch.undo()

    monkeypatch.setattr(
        cr, "_MODEL_SWITCH_SOURCES", cr._MODEL_SWITCH_SOURCES | {_SENTINEL}
    )
    assert _SENTINEL in cr._MODEL_SWITCH_SOURCES
    assert cr.grants_intimate_narration(_SENTINEL) is False, (
        "授予判据读到了换模型轴＝两轴已被并成一枚"
    )


def test_grant_predicate_reads_grant_axis_not_ttl_axis(monkeypatch) -> None:
    """叙述授予判据也不许跟着 TTL 豁免轴走（并轴的第二条路）。

    把哨兵塞进 TTL 豁免轴、授予轴不动 ⇒ grants(哨兵) 仍必须 False。今天 TTL 轴恰好是
    授予轴的子集（{manual, admin} ⊂ {manual, admin, content}），用真实来源同样看不出
    这种并轴 ⇒ 仍靠哨兵注入才有牙。（`test_rp_style_directives.py` 已锁过
    `content_signal`-vs-TTL 的静态不等，这里补的是**行为注入**版本，覆盖并轴改写。）
    """
    assert _SENTINEL not in cr._MAX_TTL_EXEMPT_SOURCES
    assert _SENTINEL not in cr._INTIMATE_NARRATION_SOURCES

    monkeypatch.setattr(
        cr, "_MAX_TTL_EXEMPT_SOURCES", cr._MAX_TTL_EXEMPT_SOURCES | {_SENTINEL}
    )
    assert _SENTINEL in cr._MAX_TTL_EXEMPT_SOURCES
    assert cr.grants_intimate_narration(_SENTINEL) is False, (
        "授予判据读到了 TTL 豁免轴＝两轴已被并成一枚"
    )


def test_model_switch_reads_model_axis_not_grant_axis(monkeypatch) -> None:
    """换真实头判据只跟换模型轴走，反向也不跟授予轴走（并轴的第三条路，方向相反）。

    正向：哨兵塞进换模型轴 ⇒ `_head_if_switchable(..., L2)` 交出非空头（会换模型）。
    反向（牙）：只把哨兵塞进**授予轴**、换模型轴不动 ⇒ `_head_if_switchable` 必须仍
    返回空——否则"给叙述权"就静默等于"换模型"，正是本波要堵的轴合并的另一面。
    """
    knobs = {"model": "lock_model_x", "order": ["lock_model_x", "lock_model_y"]}
    head = cr.ContentRouteEngine._head_if_switchable
    assert head(knobs, _SENTINEL, cr.INTIMATE_TIER_L2) == []

    monkeypatch.setattr(
        cr, "_MODEL_SWITCH_SOURCES", cr._MODEL_SWITCH_SOURCES | {_SENTINEL}
    )
    assert head(knobs, _SENTINEL, cr.INTIMATE_TIER_L2) != []
    monkeypatch.undo()

    monkeypatch.setattr(
        cr, "_INTIMATE_NARRATION_SOURCES", cr._INTIMATE_NARRATION_SOURCES | {_SENTINEL}
    )
    assert head(knobs, _SENTINEL, cr.INTIMATE_TIER_L2) == [], (
        "换模型判据读到了授予轴＝给叙述权会静默换模型"
    )
