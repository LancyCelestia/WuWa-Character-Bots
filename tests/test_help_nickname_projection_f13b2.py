"""F-13 乙案批 2（2026-10-07）：帮助册「昵称触发列」收进单一真身 `DEFAULT_VERB_MAP`。

判据（本锁钉四件事，逐条有牙）：

① **echo.py 不再自带那几簇词面**：`_HELP_ENTRY_META[<topic>].triggers_nickname` 的
   值节点必须是 `ast.Call` 指向 `runtime/aliases.py::nickname_verbs_for`（转述形态），
   不许是字符串元组字面量；尺＝AST 级断言，不读行号（行号随任何编辑漂移）。
   同时用 S53 那把尺的取数口现算确认：echo 侧真身位里不再出现这七簇词集。
② **词债真降**：`accounted_debt()` 现算值必须逐字等于 `WORD_SITE_CEILING`（零余量常驻锁
   另有），且上限必须低于批 1 的 472；`AUDIT_HISTORY` 尾项＝新上限、**前缀逐字不动**；
   四枚扫描面地板（1100/700/140/100）一枚都不许下调（降地板不算修债）。
③ **行为面零变化**（改前/改后逐项相等，尺跑两遍而不是"没报错"）：
   批 1 之前那七列手抄词面＝本文件冻结的 `PRE_BATCH_NICKNAME_SNAPSHOT`
   （凭据＝提交 ``064535d`` 树现取，逐枚与当时字面量全等；词面以「、」单串存放——
   容器形态会被 S33 的 ruleB 认作 tests 侧副本，那本账零余量），断言三件：
   (a) 投影口的输出**集合**与快照逐枚相等（一字不多一字不少）；
   (b) 帮助尺：快照里每枚词 `/bot help <词>` 仍落到同一个 topic（`normalize_help_topic`）；
   (c) 路由尺：快照里每枚词「守岸人<词>」仍由 `CommandAliasResolver` 解到同一个 capability。
   另加两取数口对拍：`scripts/command_catalog._entry_meta()`（静态 AST 路）必须与
   `echo._HELP_ENTRY_META`（运行时 import 路）逐枚全等——投影若只对一条路有效即红。
④ **注毒自证**：把任一簇词面退回手抄形态（虚拟件喂 S53 同一取数口，绝不写盘），
   计账必须涨回上限之上——证明批 2 降的账不是靠余量糊的。

全离线、只读源码与运行时对象、不写盘、不碰 git 写操作。
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from typing import Any, Final

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ECHO_REL: Final[str] = "plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py"
ALIASES_REL: Final[str] = "plugins/bot_unified_runtime/domains/chat_reply/runtime/aliases.py"
S53_FILE: Final[str] = "tests/test_trigger_word_single_source.py"

#: 批 1 末账（2026-10-06，raw 547／计账 472）——本批的对照基线，只做方向断言。
PRE_BATCH_CEILING: Final[int] = 472
#: 四枚扫描面地板的批 1 现值（降地板＝把尺改瞎，不算修债）。
PRE_BATCH_FLOORS: Final[tuple[int, int, int, int]] = (1100, 700, 140, 100)

#: (topic, capability, 批前手抄词面单串)。凭据＝提交 ``064535d`` 的 echo.py 字面量。
PROJECTED_TOPICS: Final[tuple[tuple[str, str, str], ...]] = (
    ("状态", "bot.status", "状态、狀態、status、查询"),
    ("暂停", "bot.control", "暂停、暫停、pause、继续、繼續、resume"),
    ("日志", "bot.logs", "日志、logs、查询日志"),
    ("订阅", "bot.subscribe", "订阅、訂閱、subscribe、查询订阅"),
    ("对话", "bot.dialogue", "对话验收、dialogue"),
    ("维基", "bot.wiki", "wiki、维基、维基百科、wikipedia"),
    ("随机图", "bot.randpic", "隨機圖、來張圖"),
)

#: 投影口必须住在这个**既有**文件里（用户明令：禁新建生产 .py；真身只准放进同职责旧件）。
PROJECTION_HOUSEHOLD: Final[str] = ALIASES_REL
PROJECTION_FUNC: Final[str] = "nickname_verbs_for"


def _load_by_path(name: str, rel: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def s53() -> Any:
    return _load_by_path("__f13b2_s53__", S53_FILE)


def _snapshot_words(single: str) -> list[str]:
    return [item for item in single.split("、") if item]


def _module_tree(rel: str) -> ast.Module:
    return ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))


def _meta_value_nodes(tree: ast.Module) -> dict[str, dict[str, ast.expr]]:
    """`_HELP_ENTRY_META` 的 topic → 字段名 → 值节点（纯 AST，不吃行号）。"""
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [getattr(node, "target", None)]
        if not any(isinstance(t, ast.Name) and t.id == "_HELP_ENTRY_META" for t in targets):
            continue
        value = getattr(node, "value", None)
        assert isinstance(value, ast.Dict), "_HELP_ENTRY_META 定义形态变了（不是 dict 字面量）"
        out: dict[str, dict[str, ast.expr]] = {}
        for key, entry in zip(value.keys, value.values):
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                continue
            if not isinstance(entry, ast.Dict):
                continue
            out[key.value] = {
                k.value: v
                for k, v in zip(entry.keys, entry.values)
                if isinstance(k, ast.Constant) and isinstance(k.value, str) and v is not None
            }
        return out
    raise AssertionError("_HELP_ENTRY_META 未找到")


# ---------------------------------------------------------------------------
# ① echo 侧不再自带那几簇词面
# ---------------------------------------------------------------------------


def test_echo_meta_projects_instead_of_hand_copying() -> None:
    fields = _meta_value_nodes(_module_tree(ECHO_REL))
    for topic, capability, _snapshot in PROJECTED_TOPICS:
        assert topic in fields, f"帮助主题 {topic} 不在 _HELP_ENTRY_META（取数口坏了，不是收口成功）"
        node = fields[topic].get("triggers_nickname")
        assert node is not None, f"{topic}.triggers_nickname 被整格删掉了＝丢功能，不是转述"
        assert isinstance(node, ast.Call), (
            f"{topic}.triggers_nickname 仍是手抄字面量（{type(node).__name__}）＝词债没还"
        )
        assert isinstance(node.func, ast.Name) and node.func.id == PROJECTION_FUNC, (
            f"{topic}.triggers_nickname 调的不是 {PROJECTION_FUNC}＝第二真身换了个窝"
        )
        assert [a.value for a in node.args] == [capability], (
            f"{topic}.triggers_nickname 投影参数不是 {capability}"
        )


def test_projection_household_is_an_existing_module() -> None:
    """投影口必须住在**既有**同职责模块（禁新建生产件），且真身表仍在同一文件。"""
    tree = _module_tree(PROJECTION_HOUSEHOLD)
    defined = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert PROJECTION_FUNC in defined, f"{PROJECTION_HOUSEHOLD} 里没有 {PROJECTION_FUNC}"
    bound = {
        t.id
        for node in tree.body
        for t in (node.targets if isinstance(node, ast.Assign) else [getattr(node, "target", None)])
        if isinstance(t, ast.Name)
    }
    assert "DEFAULT_VERB_MAP" in bound, "真身表被搬走了＝投影口成了第二真身"


def test_projection_function_carries_no_word_literal() -> None:
    """投影口自己不许揣词面（它只能读真身表），否则＝换个文件再抄一遍。"""
    tree = _module_tree(PROJECTION_HOUSEHOLD)
    fn = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == PROJECTION_FUNC
    )
    doc_node = (
        fn.body[0]
        if fn.body and isinstance(fn.body[0], ast.Expr) and isinstance(fn.body[0].value, ast.Constant)
        else None
    )
    doc_id = id(doc_node.value) if doc_node is not None and isinstance(doc_node.value, ast.Constant) else -1
    stray = [
        node.value
        for node in ast.walk(fn)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) != doc_id
    ]
    assert not stray, f"{PROJECTION_FUNC} 体内出现字符串字面量 {stray}＝投影口自藏词面"


def test_ledger_sees_no_echo_home_for_the_projected_clusters(s53: Any) -> None:
    """S53 取数口现算：echo 侧真身位里这七簇词集一枚都不许再在场。"""
    _raw, sites, _inline = s53.current_debt()
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.aliases import (
        nickname_verbs_for,
    )

    projected = {frozenset(nickname_verbs_for(cap)) for _t, cap, _s in PROJECTED_TOPICS}
    offenders = [
        f"{site.line}:{site.label}"
        for site in sites
        if site.file.endswith("capabilities/echo.py") and site.words in projected
    ]
    assert not offenders, f"echo 仍自带整簇投影词面：{offenders}"


# ---------------------------------------------------------------------------
# ② 债真降（现算值＝上限；四地板不动；历史前缀逐字不动）
# ---------------------------------------------------------------------------


def test_debt_actually_dropped_to_the_new_ceiling(s53: Any) -> None:
    acct, raw, removed = s53.accounted_debt()
    assert acct == s53.WORD_SITE_CEILING, (
        f"计账 {acct} ≠ 上限 {s53.WORD_SITE_CEILING}＝批 2 降完没把零余量钉上（留了余量）"
    )
    assert s53.WORD_SITE_CEILING < PRE_BATCH_CEILING, (
        f"上限 {s53.WORD_SITE_CEILING} 没低于批 1 的 {PRE_BATCH_CEILING}＝账没往下掉"
    )
    assert raw < PRE_BATCH_CEILING + 75, (
        f"raw {raw} 没降（批 1 现算 raw 547）＝抵销数被动手脚而非真收口"
    )
    assert removed <= 75, f"名册抵销 {removed} 比批 1 的 75 还多＝降账靠加豁免"


def test_audit_history_prefix_is_untouched(s53: Any) -> None:
    prefix = (
        ("2026-09-24", 469),
        ("2026-09-27", 467),
        ("2026-09-27", 467),
        ("2026-10-05", 477),
        ("2026-10-06", 472),
    )
    assert s53.AUDIT_HISTORY[: len(prefix)] == prefix, "核账历史前缀被改写＝对账凭据作废"
    assert s53.AUDIT_HISTORY[-1] == ("2026-10-07", s53.WORD_SITE_CEILING), (
        f"尾项没钉上批 2 的现算值：{s53.AUDIT_HISTORY[-1]}"
    )


def test_four_scan_floors_are_not_lowered(s53: Any) -> None:
    got = (
        s53.MIN_SCANNED_FILES,
        s53.MIN_VOCAB_WORDS,
        s53.MIN_HOME_SITES,
        s53.MIN_ALIAS_FIELD_SITES,
    )
    assert got == PRE_BATCH_FLOORS, (
        f"四枚地板现值 {got} ≠ 批 1 的 {PRE_BATCH_FLOORS}＝降地板换绿，本批不允许"
    )
    # 地板必须还攥得住东西（现算读数高于地板），否则「不动」也是死的。
    files_total, _homes, _copies = s53._S33.scan_tree()
    _raw, sites, inline = s53.current_debt()
    vocab = frozenset().union(*(s.words for s in sites))
    alias_sites = [
        s for s in sites if s.kind == "ALIASFIELD" or (s.kind == "S33HOME" and "dict:" in s.label)
    ]
    assert files_total >= s53.MIN_SCANNED_FILES and len(vocab) >= s53.MIN_VOCAB_WORDS
    assert len(sites) >= s53.MIN_HOME_SITES and len(alias_sites) >= s53.MIN_ALIAS_FIELD_SITES
    assert any(inline.values()), "内联面读空＝C 维度瞎了"


def test_no_new_production_module_was_created() -> None:
    """用户明令：本批不许新建生产 .py。真身与投影口都必须在册旧件里。"""
    assert (REPO_ROOT / ECHO_REL).is_file() and (REPO_ROOT / ALIASES_REL).is_file()
    untracked_new = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "plugins").rglob("*.py")
        if "__pycache__" not in path.parts and path.name in {"env_flags.py", "nickname_verbs.py"}
    ]
    assert not untracked_new, f"出现了被用户否掉的旧形态：{untracked_new}"


# ---------------------------------------------------------------------------
# ③ 行为不变：帮助尺 / 路由尺 / 两条取数口
# ---------------------------------------------------------------------------


def test_projection_reproduces_pre_batch_word_sets_exactly() -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.aliases import (
        nickname_verbs_for,
    )

    for topic, capability, snapshot in PROJECTED_TOPICS:
        got = set(nickname_verbs_for(capability))
        want = set(_snapshot_words(snapshot))
        assert got == want, (
            f"{topic}/{capability}：投影词集与批前手抄快照不等 "
            f"多出来={sorted(got - want)} 丢了={sorted(want - got)}＝删重复变成了删功能"
        )


def test_help_search_landing_is_unchanged() -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities import echo

    for topic, _capability, snapshot in PROJECTED_TOPICS:
        for word in _snapshot_words(snapshot):
            assert echo.normalize_help_topic(word) == topic, (
                f"/bot help {word} 现在落到 {echo.normalize_help_topic(word)!r}（应为 {topic}）"
            )


def test_nickname_route_resolution_is_unchanged() -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.aliases import (
        CommandAliasResolver,
    )

    resolver = CommandAliasResolver(nicknames=["守岸人"])
    for _topic, capability, snapshot in PROJECTED_TOPICS:
        for word in _snapshot_words(snapshot):
            resolution = resolver.resolve(f"守岸人{word}")
            assert resolution is not None, f"守岸人{word} 解不出＝丢投递"
            assert resolution.capability_id == capability, (
                f"守岸人{word} 解到 {resolution.capability_id}（应为 {capability}）"
            )


def test_runtime_and_static_extraction_agree() -> None:
    """两取数口对拍：运行时 import 路与生成器静态 AST 路必须逐枚全等。"""
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities import echo
    from scripts.command_catalog import _entry_meta

    static_meta = _entry_meta()
    for topic, _capability, _snapshot in PROJECTED_TOPICS:
        runtime_value = echo._HELP_ENTRY_META[topic]["triggers_nickname"]
        assert topic in static_meta, f"生成器静态路读不到 {topic}（META 求值塌了）"
        assert static_meta[topic].get("triggers_nickname") == tuple(runtime_value), (
            f"{topic}.triggers_nickname 两路不等：静态={static_meta[topic].get('triggers_nickname')!r} "
            f"运行时={tuple(runtime_value)!r}"
        )


def test_merged_entries_keep_every_nickname_field() -> None:
    """装配后每条帮助项都仍带着合并来的触发列，且帮助检索面零丢失。"""
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities import echo
    from scripts.command_catalog import merged_entries

    by_topic = {str(item.get("topic")): item for item in merged_entries()}
    for topic, _capability, snapshot in PROJECTED_TOPICS:
        entry = by_topic.get(topic)
        assert entry is not None, f"生成物里读不到主题 {topic}"
        merged_words = set(entry["triggers_nickname"] or ())  # type: ignore[index]
        assert _snapshot_words(snapshot) and merged_words >= set(_snapshot_words(snapshot)), (
            f"{topic}：装配后触发列丢了 {set(_snapshot_words(snapshot)) - merged_words}"
        )
        live = set(echo._HELP_ALIAS_MAP)
        missing_from_search = {word for word in _snapshot_words(snapshot) if word.lower() not in live}
        assert not missing_from_search, f"{topic}：{sorted(missing_from_search)} 已从帮助检索面消失"


# ---------------------------------------------------------------------------
# ④ 注毒自证：退回手抄形态必须把账顶回上限之上
# ---------------------------------------------------------------------------


def test_poison_hand_copy_back_breaks_the_new_ceiling(s53: Any) -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.aliases import (
        nickname_verbs_for,
    )

    acct_base, raw_base, _removed = s53.accounted_debt()
    assert acct_base == s53.WORD_SITE_CEILING, "前置：零余量没钉上"
    for index, (_topic, capability, _snapshot) in enumerate(PROJECTED_TOPICS):
        words = frozenset(nickname_verbs_for(capability))
        assert words, f"投影词集为空（{capability}）＝注毒前提失效"
        rel = f"plugins/bot_unified_runtime/domains/ops/_f13b2_virtual_{index}.py"
        acct, raw, _m = s53.accounted_debt(extra=((rel, s53._synth_literal_table("F13B2_WORDS", words)),))
        assert raw > raw_base, f"{capability}：退回手抄没进 raw＝取数口对这一簇失明"
        assert acct > s53.WORD_SITE_CEILING, (
            f"{capability}：退回手抄后计账 {acct} 仍 ≤ 上限 {s53.WORD_SITE_CEILING}"
            "＝批 2 的账是靠余量糊的"
        )
