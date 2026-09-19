"""G-4 统一性机器门 · 第二道：触发词边界判定必经中央件 text_boundary（T77）。

病根同第一道（plan-G-contract.md §G-4）：S-07 六副本时代，触发词边界判定
（字符集 + 最长词优先 + casefold + fold 变长回退）在各域手抄了六份，中央件
``domains/core/text_boundary.py``（T59 建件、T66 五副本收编）落地后，「收编」
本身也需要机器门看守——否则下一个副本悄悄长回来，统一又变成假的。

对象 = 六处消费（report-T59 §4 六副本坐标表）：

  domains/meme/capabilities/randpic.py          （T66 已收编）
  domains/media/capabilities/media_archive.py   （T66 已收编）
  domains/chat_reply/capabilities/group_info.py （T66 已收编）
  domains/chat_reply/runtime/mentions.py        （T66 收编取值）
  domains/chat_reply/runtime/base_router.py     （T66 收编子集）
  domains/media/capabilities/tts.py             （换线未落——见下方棘轮）

门规则（全部 AST 静态判定，检测器对任意源码可复用，负样本靠它注入）：

  B1 import 在位：消费模块必须从 ``…domains.core.text_boundary`` import
     边界判定面（谓词或字符集常量）。
  B2 引用非死：import 进来的中央名必须在模块代码里真实被引用——只 import
     不消费的「死引用伪装」即红。
  B3 判定委托：登记的边界判定函数体内必须引用中央名（直接引用，或经
     模块级派生名/模块级助手一跳委托）——本地手抄判定循环再现即红。
  B4 权威字符集不再声明：canonical 串（TRIGGER_BOUNDARY_CHARS 逐字值）
     不得在任何消费模块以字符串字面量整串再声明——第二真相源即红。
     （T66 登记的各域取值字面量是**有意子集/变体**，不等于 canonical，
     不在本条射程内；这正是 B4 只禁整串的原因。）

tts.py 棘轮（诚实登记，非本席不合规）：briefing 称「T61 已收编 tts」，但
report-T61 §交付清单并无换线项、工作树实读 tts.py 仍为本地手抄
（_TEXT_BOUNDARY_CHARS + extract_tts_text 自持循环）——该行归 T75（tts.py
在飞独占席）。故：
  - tts.py 的 import 级断言 = xfail(strict=True) 棘轮（沿 T71 Wave H 先例）：
    换线落树即 XPASS→全量红→必须摘 xfail 转正为硬门；
  - 过渡期硬锁 = 本地 _TEXT_BOUNDARY_CHARS 值若存在必须逐字等于 canonical
    （防两侧漂移）；换线删除该常量后本例自动满足（目标态宽容）。

负样本自检（plan-G §G-4 原文）：手抄副本 / 死引用伪装 / canonical 整串
再声明三路坏样本全部注入验证门会红；另配忠实消费正例防过度开火。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.core.text_boundary import (
    TRIGGER_BOUNDARY_CHARS,
)

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent / "plugins" / "bot_unified_runtime"
_CENTRAL_MODULE_SUFFIX = "text_boundary"


@dataclass(frozen=True)
class _Consumer:
    """六处消费登记册：路径 + 边界判定函数名 + 是否已换线中央件。"""

    key: str
    relative: str
    decision_functions: tuple[str, ...]
    wired: bool


_CONSUMERS: tuple[_Consumer, ...] = (
    _Consumer(
        key="randpic",
        relative="domains/meme/capabilities/randpic.py",
        decision_functions=("is_randpic_command",),
        wired=True,
    ),
    _Consumer(
        key="media_archive",
        relative="domains/media/capabilities/media_archive.py",
        decision_functions=("is_media_archive_command",),
        wired=True,
    ),
    _Consumer(
        key="group_info",
        relative="domains/chat_reply/capabilities/group_info.py",
        decision_functions=("is_group_info_command", "detect_group_info_intents"),
        wired=True,
    ),
    _Consumer(
        key="mentions",
        relative="domains/chat_reply/runtime/mentions.py",
        decision_functions=("detect_name_mention", "starts_with_name_mention"),
        wired=True,
    ),
    _Consumer(
        key="base_router",
        relative="domains/chat_reply/runtime/base_router.py",
        decision_functions=("natural_match",),
        wired=True,
    ),
    _Consumer(
        key="tts",
        relative="domains/media/capabilities/tts.py",
        decision_functions=("is_tts_command", "extract_tts_text"),
        wired=False,  # 换线归 T75；落线前由 xfail 棘轮 + 值漂移硬锁把守
    ),
)


# ==================== 检测器（对任意源码可复用，负样本靠它注入） ====================


def _parse(source: str) -> ast.Module:
    return ast.parse(source)


def _central_imported_names(tree: ast.Module) -> set[str]:
    """从 ImportFrom 语句收集 text_boundary 的导入名。"""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and (
            node.module == _CENTRAL_MODULE_SUFFIX
            or node.module.endswith("." + _CENTRAL_MODULE_SUFFIX)
        ):
            names.update(alias.name for alias in node.names)
    return names


def _referenced_names(node: ast.AST) -> set[str]:
    """AST 子树内被引用的名字（Name id ∪ Attribute attr；import 别名不算）。"""
    found: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            found.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            found.add(sub.attr)
    return found


def _module_level_derived_names(tree: ast.Module, central: set[str]) -> set[str]:
    """模块级「派生名」：赋值表达式引用中央名（或另一派生名）的顶层变量。

    mentions 形态：_ADDRESS_BOUNDARY_CHARS = frozenset(_CORE + ADDRESS_BOUNDARY_CHARS)
    ——判定函数引用派生名等同引用中央取值（B3 一跳委托面）。
    """
    derived: set[str] = set()
    assignments: list[tuple[str, ast.expr]] = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            if isinstance(node.targets[0], ast.Name):
                assignments.append((node.targets[0].id, node.value))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and (
            node.value is not None
        ):
            assignments.append((node.target.id, node.value))
    for _ in range(4):  # 不动点：链式派生最多几轮即稳。
        grew = False
        for name, value in assignments:
            if name in derived:
                continue
            refs = _referenced_names(value)
            if refs & (central | derived):
                derived.add(name)
                grew = True
        if not grew:
            break
    return derived


def _module_level_function_names(tree: ast.Module) -> set[str]:
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _find_functions(tree: ast.Module, name: str) -> list[ast.AST]:
    """任意深度的同名函数定义（嵌套 matcher 工厂形态如 base_router.natural_match）。"""
    found: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            node.name == name
        ):
            found.append(node)
    return found


def _function_uses_central(
    fn: ast.AST,
    central: set[str],
    derived: set[str],
    module_functions: set[str],
    tree: ast.Module,
) -> bool:
    """判定函数体是否触达中央件：直引/派生名，或一跳委托到模块级助手。"""
    refs = _referenced_names(fn)
    if refs & (central | derived):
        return True
    for helper in refs & module_functions:
        for candidate in _find_functions(tree, helper):
            if _referenced_names(candidate) & (central | derived):
                return True
    return False


def _iter_non_docstring_strings(tree: ast.Module) -> list[str]:
    """全部字符串常量（剔除模块/类/函数 docstring 位）。"""
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    values: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            values.append(node.value)
    return values


def _scan_consumer(source: str, consumer: _Consumer) -> list[str]:
    """门主体：对消费模块源码跑 B1-B4，返回人话违规清单（空=过门）。"""
    tree = _parse(source)
    problems: list[str] = []
    central = _central_imported_names(tree)

    # B1 import 在位
    if not central:
        problems.append(
            f"B1：{consumer.key} 未从 domains/core/text_boundary import 任何"
            "边界判定面——本地手抄副本再现"
        )

    # B2 引用非死
    module_refs = _referenced_names(tree)
    for name in sorted(central):
        if name not in module_refs:
            problems.append(
                f"B2：{consumer.key} import 了中央件 {name} 但全模块未引用"
                "——死引用伪装（判定实际仍走本地实现）"
            )

    # B3 判定委托
    derived = _module_level_derived_names(tree, central)
    module_functions = _module_level_function_names(tree)
    for fn_name in consumer.decision_functions:
        defs = _find_functions(tree, fn_name)
        if not defs:
            problems.append(
                f"B3：{consumer.key} 登记的边界判定函数 {fn_name} 未找到"
                "——函数改名未同步本门登记册（请评审后更新 _CONSUMERS）"
            )
            continue
        for fn in defs:
            assert isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
            if not _function_uses_central(fn, central, derived, module_functions, tree):
                problems.append(
                    f"B3：{consumer.key}.{fn_name}（行 {fn.lineno}）判定体未引用"
                    "中央件名（含一跳委托）——边界判定本地手抄再现"
                )

    # B4 权威字符集不再声明
    for value in _iter_non_docstring_strings(tree):
        if value == TRIGGER_BOUNDARY_CHARS:
            problems.append(
                f"B4：{consumer.key} 以字符串字面量整串再声明 canonical 边界"
                "字符集（TRIGGER_BOUNDARY_CHARS 逐字值）——第二真相源，"
                "请改为 import 中央件"
            )
            break
    return problems


def _load_consumer(consumer: _Consumer) -> str:
    return (_PLUGIN_ROOT / consumer.relative).read_text(encoding="utf-8")


def _consumer_by_key(key: str) -> _Consumer:
    for consumer in _CONSUMERS:
        if consumer.key == key:
            return consumer
    raise AssertionError(f"消费登记册缺少 {key}——登记册被破坏，请先修复门册")


# ==================== 正例门（对真身五处已收编消费） ====================


@pytest.mark.parametrize(
    "consumer",
    [c for c in _CONSUMERS if c.wired],
    ids=[c.key for c in _CONSUMERS if c.wired],
)
def test_gate2_wired_consumer_passes(consumer: _Consumer) -> None:
    """正例：五处已收编消费全部过门（import 在位/引用非死/判定委托/无整串再声明）。"""
    problems = _scan_consumer(_load_consumer(consumer), consumer)
    assert not problems, f"边界谓词门（{consumer.key}）被触发：\n" + "\n".join(problems)


def test_gate2_tts_local_charset_matches_central() -> None:
    """tts.py 过渡期硬锁：本地 _TEXT_BOUNDARY_CHARS 若在，必须逐字等于 canonical。

    换线（T75）删除该常量后本例自动满足——目标态宽容，不挡施工。
    """
    consumer = _consumer_by_key("tts")
    source = _load_consumer(consumer)
    tree = _parse(source)
    local_value: str | None = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(
            node.targets[0], ast.Name
        ):
            target = node.targets[0]
            if (
                target.id == "_TEXT_BOUNDARY_CHARS"
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                local_value = node.value.value
    if local_value is None:
        return  # 已换线中央件：目标态，无事可锁。
    assert local_value == TRIGGER_BOUNDARY_CHARS, (
        "tts.py 本地 _TEXT_BOUNDARY_CHARS 与中央 TRIGGER_BOUNDARY_CHARS 漂移"
        f"（本地={local_value!r} 中央={TRIGGER_BOUNDARY_CHARS!r}）——"
        "换线前两侧必须逐字一致"
    )


@pytest.mark.xfail(
    strict=True,
    reason="tts.py 换线 text_boundary 归 T75（tts.py 在飞独占席；briefing 的"
    "「T61 已收编 tts」与 report-T61 交付清单及工作树实况不符）。换线落树后"
    "本例 XPASS→strict 全量红→请摘除 xfail 转正为硬门（棘轮，沿 T71 先例）。",
)
def test_gate2_tts_central_import_ratchet() -> None:
    """tts.py 棘轮：目标态 = 与五处已收编消费同口径过全部 B1-B4。"""
    consumer = _consumer_by_key("tts")
    problems = _scan_consumer(_load_consumer(consumer), consumer)
    assert not problems, "tts.py 边界判定未过中央件门：\n" + "\n".join(problems)


# ==================== 负样本自检（注入坏样本 → 门必须变红） ====================

# 负样本①：S-07 时代的历史手抄形态（无 import、自持 startswith 循环+本地字符集）。
_HAND_ROLLED_COPY = """
_BOUNDARY_CHARS = "，,。！？!?：:、 的了呢吗呀啊哈～~"


def is_randpic_command(text, trigger_words=None):
    stripped = (text or "").strip()
    for word in trigger_words or []:
        if stripped.startswith(word):
            tail = stripped[len(word):]
            if not tail or tail[0] not in _BOUNDARY_CHARS:
                return False
            return True
    return False
"""

# 负样本②：死引用伪装——import 了中央件但登记判定函数仍走本地循环。
_DEAD_IMPORT_MASQUERADE = """
from plugins.bot_unified_runtime.domains.core.text_boundary import is_trigger


def _unrelated_helper(text, words):
    return is_trigger(text, words)


def is_randpic_command(text, trigger_words=None):
    stripped = (text or "").strip()
    for word in trigger_words or []:
        if stripped.startswith(word):
            tail = stripped[len(word):]
            if not tail or tail[0] not in "，,。！？!?：:、 的了呢吗呀啊哈～~":
                return False
            return True
    return False
"""

# 负样本③：canonical 整串再声明（第二真相源）——判定本身合规也不行。
_CANONICAL_REDECLARED = """
from plugins.bot_unified_runtime.domains.core.text_boundary import is_trigger

TRIGGER_BOUNDARY_CHARS_LOCAL = "，,。！？!?：:、 　\t～~"


def is_randpic_command(text, trigger_words=None):
    return bool(is_trigger(text, list(trigger_words or [])))
"""

# 正例对照：忠实消费形态（import + 委托 + 无整串再声明）。
_FAITHFUL_CONSUMER = """
from plugins.bot_unified_runtime.domains.core.text_boundary import is_trigger

_TRIGGERS = ("随机图",)


def is_randpic_command(text, trigger_words=None):
    words = list(trigger_words) if trigger_words else list(_TRIGGERS)
    return bool(is_trigger(text, words))
"""


def _pseudo_consumer() -> _Consumer:
    return _Consumer(
        key="pseudo",
        relative="<pseudo>",
        decision_functions=("is_randpic_command",),
        wired=True,
    )


def test_gate2_negative_hand_rolled_copy_caught() -> None:
    """负样本①必须被抓：手抄副本（无 import + 本地判定循环）。"""
    problems = _scan_consumer(_HAND_ROLLED_COPY, _pseudo_consumer())
    assert any(p.startswith("B1") for p in problems), (
        "负样本①（手抄副本）未被 B1 抓红——门失效：" + repr(problems)
    )
    assert any(p.startswith("B3") for p in problems), (
        "负样本①（手抄副本）未被 B3 抓红——门失效：" + repr(problems)
    )


def test_gate2_negative_dead_import_caught() -> None:
    """负样本②必须被抓：import 在场但判定仍走本地循环。"""
    problems = _scan_consumer(
        _DEAD_IMPORT_MASQUERADE, _pseudo_consumer()
    )
    assert any(p.startswith("B3") for p in problems), (
        "负样本②（死引用伪装）未被 B3 抓红——门失效：" + repr(problems)
    )
    assert not any(p.startswith("B1") for p in problems), (
        "负样本②不应触发 B1（import 在位是本样本前提）：" + repr(problems)
    )


def test_gate2_negative_canonical_redeclaration_caught() -> None:
    """负样本③必须被抓：canonical 字符集整串再声明。"""
    problems = _scan_consumer(
        _CANONICAL_REDECLARED, _pseudo_consumer()
    )
    assert any(p.startswith("B4") for p in problems), (
        "负样本③（canonical 整串再声明）未被 B4 抓红——门失效：" + repr(problems)
    )


def test_gate2_positive_faithful_consumer_zero_violations() -> None:
    """正例对照：忠实消费形态零违规——防检测器过度开火。"""
    problems = _scan_consumer(_FAITHFUL_CONSUMER, _pseudo_consumer())
    assert not problems, "忠实消费被误判（门过度开火）：" + repr(problems)
