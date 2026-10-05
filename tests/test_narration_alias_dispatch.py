"""`/bot 描写 …` 中文词头的**别名归一腿**判据锁（席 aliasgap，2026-10-04）。

席 na3-declare 把中文同义词头**硬写进派发条件式**（它那件 REPORT §缺格 A 自记的正是
这一格），理由写在 `__init__.py` 的注释里：`aliases.py` 不在它的文件域。本件把词头
搬进中央别名册，判据钉的是三件事：

1. **词面只住一处**（AGENTS 铁律：禁第二真身）：中文词头的声明位＝
   `domains/chat_reply/runtime/aliases.py::MODULE_ALIASES` 那一格（同 `功能管理 → feature`
   的在册先例）；根 `__init__.py` 的派发那一支**不许**再点名它。
2. **归一腿真在派发路径上**：`normalize_command_text` 不是只喂帮助册的文案件——
   它就是 `__init__.py` 里 `command_text` 的来源（现算：全仓只有 `__init__.py:8589` 一个
   消费者）。本件因此判「原始文本 → 归一 → 生产条件式原文 → 生产剥词头算式原文」
   这条**真链路**，测试里不写第二份解析逻辑。
3. **两支词头逐字同形**：英文正形与中文同义归一后交给 handler 的子命令串完全一致。

不开 handler、不碰库（判据只到派发面），生产库零写入。
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.runtime.aliases import (
    MODULE_ALIASES,
    normalize_command_text,
)

_ROOT = Path(__file__).resolve().parents[1]
_INIT_SRC_PATH = _ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"
_ALIASES_SRC_PATH = (
    _ROOT / "plugins" / "bot_unified_runtime" / "domains" / "chat_reply" / "runtime" / "aliases.py"
)

_EN_HEAD = "narration"
_CN_HEAD = "描写"


# ------------------------------------------------ 生产派发那一支（AST 原文抽取）


def _handle_status_tree() -> ast.AsyncFunctionDef:
    tree = ast.parse(_INIT_SRC_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_status":
            return node
    raise AssertionError("根 __init__.py 里找不到 _handle_status（命令面已搬家？）")


def narration_branch() -> tuple[str, str]:
    """返回「体内调用 build_narration_control_result」那一支的（条件式原文, 剥词头赋值句原文）。

    零命中＝接线缺席；多于一支＝第二通路。
    """
    src = _INIT_SRC_PATH.read_text(encoding="utf-8")
    hits: list[tuple[str, str]] = []
    for node in ast.walk(_handle_status_tree()):
        if not isinstance(node, ast.If):
            continue
        for stmt in node.body:
            if not _calls_named(stmt, "build_narration_control_result"):
                continue
            assign = _strip_stmt(node.body, src)
            hits.append((ast.get_source_segment(src, node.test) or "", assign))
            break
    if len(hits) > 1:
        raise AssertionError(f"描写档命令面出现 {len(hits)} 支通路（只准一支）")
    if not hits:
        raise AssertionError("根 __init__.py 里没有派发到 build_narration_control_result 的那一支")
    return hits[0]


def _calls_named(node: ast.AST, name: str) -> bool:
    return any(
        isinstance(call, ast.Call)
        and (
            (isinstance(call.func, ast.Name) and call.func.id == name)
            or (isinstance(call.func, ast.Attribute) and call.func.attr == name)
        )
        for call in ast.walk(node)
    )


def _strip_stmt(body: list[ast.stmt], src: str) -> str:
    for stmt in body:
        if not isinstance(stmt, ast.Assign) or not stmt.targets:
            continue
        target = stmt.targets[0]
        if not (isinstance(target, ast.Name) and target.id.endswith("_command")):
            continue
        seg = ast.get_source_segment(src, stmt)
        if seg and "command_text" in seg:
            return seg
    raise AssertionError("派发那一支里没有剥词头的赋值")


def dispatch(raw_command_args: str) -> tuple[bool, str]:
    """真链路：原始参数文本先过 `normalize_command_text`（生产就是这么喂条件式的），
    再把**生产条件式与剥词头算式的原文** exec 一遍。"""
    test_src, assign_src = narration_branch()
    var_name = assign_src.split("=", 1)[0].strip()
    probe = (
        "def probe(command_text):\n"
        f"    if {test_src}:\n"
        f"        {assign_src}\n"
        f"        return True, {var_name}\n"
        "    return False, ''\n"
    )
    ns: dict[str, Any] = {}
    exec(compile(probe, "<dispatch-probe>", "exec"), ns)  # noqa: S102 - 跑仓库自己的生产算式原文
    return ns["probe"](normalize_command_text(raw_command_args))


def _str_literals(path: Path) -> list[str]:
    return [
        node.value
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


# ---------------------------------------------------------------- ① 词面只住一处


def test_chinese_head_is_declared_in_the_module_alias_map() -> None:
    """中文词头是 `MODULE_ALIASES` 的一格，值＝英文正形（`功能管理 → feature` 同先例）。"""
    assert MODULE_ALIASES.get(_CN_HEAD) == _EN_HEAD, (
        "描写 不在中央别名册里 ⇒ 派发条件式只能自己点名它＝词面第二处声明位"
    )


def test_chinese_head_is_declared_in_exactly_one_file() -> None:
    """字面量 `"描写"` 作为字符串常量：**别名册一枚、派发段零枚**（总账＝1）。"""
    in_aliases = _str_literals(_ALIASES_SRC_PATH).count(_CN_HEAD)
    in_init = _str_literals(_INIT_SRC_PATH).count(_CN_HEAD)
    assert in_aliases == 1, f"中央别名册里中文词头出现 {in_aliases} 次（应为 1）"
    assert in_init == 0, (
        f"根 __init__.py 仍有 {in_init} 处硬写中文词头 ⇒ 与 MODULE_ALIASES 构成两处声明位"
    )


def test_dispatch_condition_names_only_the_canonical_head() -> None:
    """条件式与剥词头算式里都不出现中文词头字面量（只读 canonical 名）。"""
    test_src, assign_src = narration_branch()
    for segment, label in ((test_src, "条件式"), (assign_src, "剥词头算式")):
        assert _CN_HEAD not in segment, f"派发那支的{label}仍点名中文词头：{segment}"
        assert _EN_HEAD in segment, f"派发那支的{label}里连英文正形都不在了：{segment}"


# ---------------------------------------------------------------- ② 归一腿真在派发路径上


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("描写", "narration"),
        ("描写 scene", "narration scene"),
        ("描写 speech", "narration speech"),
        ("描写 reset", "narration reset"),
        ("描写 show", "narration show"),
        ("narration scene", "narration scene"),
    ],
)
def test_normalize_command_text_maps_the_head(raw: str, expected: str) -> None:
    assert normalize_command_text(raw) == expected


def test_normalize_is_the_producer_of_the_dispatch_variable() -> None:
    """归一口不是只喂帮助册文案：它唯一消费者就是命令面的 `command_text`。"""
    src = _INIT_SRC_PATH.read_text(encoding="utf-8")
    assert src.count("normalize_command_text(") >= 1
    assert 'command_text = normalize_command_text(' in src, (
        "command_text 不再由 normalize_command_text 产出 ⇒ 别名册不在派发路径上，"
        "本件的修法前提失效，请回退为条件式自带词头"
    )


# ---------------------------------------------------------------- ③ 两支词头同形到达


@pytest.mark.parametrize("arg", ["speech", "scene", "reset", "show", "scen", ""])
def test_both_heads_reach_the_same_handler_argument(arg: str) -> None:
    raw_en = f"{_EN_HEAD} {arg}".strip()
    raw_cn = f"{_CN_HEAD} {arg}".strip()
    hit_en, en_sub = dispatch(raw_en)
    hit_cn, cn_sub = dispatch(raw_cn)
    assert hit_en, f"/bot {raw_en} 派不到 handler"
    assert hit_cn, f"/bot {raw_cn} 派不到 handler（中文同义未走别名册）"
    assert en_sub == cn_sub == arg.strip(), (en_sub, cn_sub, arg)


@pytest.mark.parametrize(
    "text", ["intimate on", "亲密 scene", "帮助", "help 描写", "reply scene", "描写scene"]
)
def test_neighbour_heads_are_not_stolen(text: str) -> None:
    """近形与「亲密」那一族不被描写档吞（`亲密` 无词头别名＝本波未裁，维持缺席）。"""
    hit, _sub = dispatch(text)
    assert not hit, f"{text} 被描写档那一支吞了"


# ---------------------------------------------------------------- ④ 在册先例的一致性


def test_feature_head_precedent_is_the_same_mechanism() -> None:
    """`功能管理 → feature` 是同一先例：中文词头住别名册、派发段只读 canonical。"""
    assert MODULE_ALIASES.get("功能管理") == "feature"
    assert normalize_command_text("功能管理 get bot.x") == "feature get bot.x"


def test_intimate_head_has_no_chinese_alias_yet() -> None:
    """开关面 `intimate` 至今**没有**中文词头（`亲密` 不在册）⇒ 描写 是第二格走中央册的
    中文词头，两族从此同一机制；本件不顺手给 intimate 造词面（未裁＝越权）。"""
    assert "亲密" not in MODULE_ALIASES
    assert MODULE_ALIASES.get("亲密") is None
