"""`/bot narration …` 与 `/bot 描写 …` 的**派发面**判据锁（席 na3-declare，2026-10-04）。

席 na1-core 落了轴心、词表与三腿分诊口，但报告 §⑦ 第 1 条明说**派发未接线**
（根 `__init__.py` 里 `描写|build_narration_control_result` 零命中）⇒ 今天在生产认不到。
本件只钉"命令到得了 handler"这一件事，**不**重测轴（那是 `test_narration_axis_command.py`）。

四件事：

1. **两支词头都派发到同一支 handler**（G-0 乙：英文正形 + 中文同义，一个 handler、
   一张词表）：判据不抄生产表达式，而是把根 `__init__.py` 里那一支的**条件式与剥前缀
   赋值句原文**抽出来 exec——生产的字面量与算式逐字被执行，测试里没有第二份解析逻辑。
2. **词面只住一处**（G-0 乙）：派发那一段**不许**重列 ``speech``/``scene``/``reset``/``show``
   ——它们唯一的真身是 ``content_route._NARRATION_SUBCOMMAND_TABLE`` 与
   ``intimate_control.SHOW_SUBCOMMAND``。抄进命令面＝第二处声明位。
3. **认不出＝不受理，绝不悄悄开档**（照 `match_intimate_subcommand` 拒绝猜测那一形）：
   错字（``scen``）与裸命令都回用法串，且**库里那枚钉保持没钉过**。
4. **`show` 是只读腿**：读数四格在场，库里不写。

夹具铁律（AGENTS 规则 6／台账 #66★／#76★）：``shared_reply_policy_store`` 结构性
monkeypatch 到 tmp；``bot_addressing_preferences_db_path`` 交仓库外 tmp；
``SHARED_CONTENT_ROUTE_ENGINE._sessions`` 每枚用例换新；号全用合成值。
"""
from __future__ import annotations

import ast
import textwrap
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character import (
    reply_policy as rp_module,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.reply_policy import (
    ReplyPolicyStore,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime import content_route as cr
from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
    intimate_control as ic,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.aliases import (
    normalize_command_text,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.content_route import (
    SHARED_CONTENT_ROUTE_ENGINE,
)

_ROOT = Path(__file__).resolve().parents[1]
_INIT_SRC_PATH = _ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"

_EN_HEAD = "narration"
_CN_HEAD = "描写"
_PRIVATE_QQ = "9000000001"


# ---------------------------------------------------------------- 夹具


@pytest.fixture(autouse=True)
def _isolate_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setattr(SHARED_CONTENT_ROUTE_ENGINE, "_sessions", OrderedDict())
    store = ReplyPolicyStore(Path(tmp_path) / "reply_policy.sqlite3")
    monkeypatch.setattr(rp_module, "shared_reply_policy_store", lambda _config: store)


def _config(tmp_path: Any) -> SimpleNamespace:
    return SimpleNamespace(
        bot_addressing_preferences_db_path=str(Path(tmp_path) / "addressing.sqlite3"),
        bot_content_route_enabled=True,
        bot_content_route_intimate_ttl_minutes=60.0,
        bot_reply_detail_mode="medium",
    )


# -------------------------------------------------- 从根 __init__.py 抽出那一支


def _init_tree() -> ast.Module:
    return ast.parse(_INIT_SRC_PATH.read_text(encoding="utf-8"))


def _status_handler(tree: ast.Module) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_status":
            return node
    raise AssertionError("根 __init__.py 里找不到 _handle_status（命令面已搬家？）")


def narration_dispatch_branch() -> tuple[str, list[ast.stmt]]:
    """返回「体内调用 build_narration_control_result」那一支的（条件式源码, 语句表）。

    零命中＝接线缺席（本波开工时的 RED 形态）；多于一支＝第二通路。
    """
    src = _INIT_SRC_PATH.read_text(encoding="utf-8")
    tree = _init_tree()
    handler = _status_handler(tree)
    hits: list[tuple[str, list[ast.stmt]]] = []
    for node in ast.walk(handler):
        if not isinstance(node, ast.If):
            continue
        for stmt in node.body:
            if _calls_named(stmt, "build_narration_control_result"):
                test_src = ast.get_source_segment(src, node.test) or ""
                hits.append((test_src, node.body))
                break
    if len(hits) > 1:
        raise AssertionError(f"描写档命令面出现 {len(hits)} 支通路（只准一支）")
    if not hits:
        raise AssertionError(
            "根 __init__.py 的 _handle_status 里没有任何一支调用 build_narration_control_result"
            " ⇒ /bot 描写 与 /bot narration 今天派不到 handler（未接线）"
        )
    return hits[0]


def _calls_named(node: ast.AST, name: str) -> bool:
    return any(
        isinstance(call, ast.Call)
        and (
            isinstance(call.func, ast.Name) and call.func.id == name
            or isinstance(call.func, ast.Attribute) and call.func.attr == name
        )
        for call in ast.walk(node)
    )


def _strip_stmt(body: list[ast.stmt], src: str) -> tuple[str, str]:
    """交出「从 command_text 剥掉词头」那一句的源码与它的目标变量名。"""
    for stmt in body:
        if not isinstance(stmt, ast.Assign) or not stmt.targets:
            continue
        target = stmt.targets[0]
        if not (isinstance(target, ast.Name) and target.id.endswith("_command")):
            continue
        seg = ast.get_source_segment(src, stmt)
        if seg and "command_text" in seg:
            return target.id, seg
    raise AssertionError("派发那一支里没有剥词头的赋值（command_text 未交回子命令）")


def dispatch_head_and_arg(command_text: str) -> tuple[bool, str]:
    """**执行**生产那一支的条件式与剥前缀算式（不另写第二份解析逻辑）。

    入参是**用户原始参数串**：生产里条件式吃的是 `normalize_command_text` 的产出
    （`__init__.py` 里 `command_text` 的唯一来源），所以这里先走同一口归一
    （席 aliasgap：中文词头 `描写` 的真身＝`MODULE_ALIASES`，条件式只读 canonical 名）。
    """
    src = _INIT_SRC_PATH.read_text(encoding="utf-8")
    test_src, body = narration_dispatch_branch()
    var_name, assign_src = _strip_stmt(body, src)
    probe = (
        "def probe(command_text):\n"
        f"    if {test_src}:\n"
        f"        {assign_src}\n"
        f"        return True, {var_name}\n"
        "    return False, ''\n"
    )
    ns: dict[str, Any] = {}
    exec(compile(probe, "<dispatch-probe>", "exec"), ns)  # noqa: S102 - 跑仓库自己的生产算式原文
    return ns["probe"](normalize_command_text(command_text))


# ---------------------------------------------------------------- ① 两支词头都派得到


def test_both_command_heads_dispatch_to_the_narration_handler() -> None:
    """`/bot narration …` 与 `/bot 描写 …` 派到同一支、剥出的子命令逐字相同。"""
    for arg in ("speech", "scene", "reset", "show", "scen"):
        hit_en, en_arg = dispatch_head_and_arg(f"{_EN_HEAD} {arg}")
        hit_cn, cn_arg = dispatch_head_and_arg(f"{_CN_HEAD} {arg}")
        assert hit_en, f"/bot {_EN_HEAD} {arg} 派不到 handler"
        assert hit_cn, f"/bot {_CN_HEAD} {arg} 派不到 handler（中文同义未接线）"
        assert en_arg == cn_arg == arg, (en_arg, cn_arg, arg)


def test_bare_head_still_dispatches_and_reaches_the_usage_leg() -> None:
    """裸词头不落 help 兜底：派到 handler、剥出空串（用法由 handler 自己交）。"""
    for head in (_EN_HEAD, _CN_HEAD):
        hit, arg = dispatch_head_and_arg(head)
        assert hit and arg == "", (head, hit, arg)


def test_other_heads_are_not_stolen_by_the_narration_branch() -> None:
    """近形词头不被误吞（尤其 `intimate` 那一支与带前缀的别的命令）。"""
    for text in ("intimate on", "帮助", "help 描写", "reply scene"):
        hit, _arg = dispatch_head_and_arg(text)
        assert not hit, f"{text} 被描写档那一支吞了"


# ---------------------------------------------------------------- ② 词面只住一处


def test_dispatch_branch_does_not_relist_the_token_table() -> None:
    """G-0 乙：派发段只认词头，四枚子命令的字面量**不得**出现在那里（真身＝那张表）。"""
    _test_src, body = narration_dispatch_branch()
    src = _INIT_SRC_PATH.read_text(encoding="utf-8")
    seg = "\n".join(ast.get_source_segment(src, stmt) or "" for stmt in body)
    for token in (*cr.NARRATION_MODES, "reset", ic.SHOW_SUBCOMMAND):
        assert f'"{token}"' not in seg, f"派发段重列了 {token}＝词表第二处声明位"


def test_dispatch_reuses_the_intimate_capability_id() -> None:
    """能力 id 复用 bot.chat（与开关面同一先例），且角色/隐私两参照 intimate 那一支转交。"""
    _test_src, body = narration_dispatch_branch()
    src = _INIT_SRC_PATH.read_text(encoding="utf-8")
    seg = "\n".join(ast.get_source_segment(src, stmt) or "" for stmt in body)
    assert '"bot.chat"' in seg or "'bot.chat'" in seg, seg
    assert "actor_roles" in seg, "sender_roles 没转交＝群侧作用域门永远看不见角色"
    assert "privacy_level" in seg, "隐私档没转交＝群回执会被审核判 move_private"


# ---------------------------------------------------------------- ③ 认不出＝不受理


def test_unknown_token_returns_usage_and_writes_no_pin(tmp_path: Any) -> None:
    """错字不悄悄开档：回用法串、库里那枚钉仍为「没钉过」（照 match_intimate_subcommand 的拒猜形）。

    两格分开记账（真身口径）：非空但认不出＝`slash_narration:unknown`（附一句"没认出"）、
    空串＝`slash_narration:usage`（裸命令，不带"没认出"那句）——两格都交同一份用法表，
    也都**一个字节都不写**。
    """
    cfg = _config(tmp_path)
    cases = {
        "scen": "slash_narration:unknown",
        "Speech!": "slash_narration:unknown",
        "snene": "slash_narration:unknown",
        "  ": "slash_narration:usage",
    }
    for typo, expected_tag in cases.items():
        result = ic.build_narration_control_result(
            config=cfg,
            request_id="req-typo",
            subcommand=typo,
            session_type="private",
            session_key=f"private:{_PRIVATE_QQ}",
            sender_id=_PRIVATE_QQ,
            sender_roles=[],
        )
        tags = list(result.audit_tags or [])
        assert expected_tag in tags, (typo, tags)
        assert "slash_narration:scene" not in tags and "slash_narration:speech" not in tags, (
            typo,
            tags,
        )
        body = str(result.body or "")
        for line in ic._NARRATION_USAGE_LINES:
            assert line in body, (typo, body)
        assert cr.read_narration_pin(
            f"private:{_PRIVATE_QQ}", sender_id=_PRIVATE_QQ, config=cfg
        ) == "", f"错字 {typo} 把钉写下去了"


def test_show_is_read_only(tmp_path: Any) -> None:
    """show 只交出读数四格，不动库。"""
    cfg = _config(tmp_path)
    result = ic.build_narration_control_result(
        config=cfg,
        request_id="req-show",
        subcommand=ic.SHOW_SUBCOMMAND,
        session_type="private",
        session_key=f"private:{_PRIVATE_QQ}",
        sender_id=_PRIVATE_QQ,
        sender_roles=[],
    )
    assert "slash_narration:show" in list(result.audit_tags or [])
    body = str(result.body or "")
    for prefix in ("描写档：", "依据：", "细节描写：", "库里的钉："):
        assert prefix in body, body
    assert cr.read_narration_pin(
        f"private:{_PRIVATE_QQ}", sender_id=_PRIVATE_QQ, config=cfg
    ) == ""


def test_handler_still_writes_for_both_heads_after_dispatch(tmp_path: Any) -> None:
    """派发表的剥前缀结果直接喂 handler ⇒ 钉落下（端到端：词头 → 剥前缀 → 写腿）。"""
    cfg = _config(tmp_path)
    for head in (_EN_HEAD, _CN_HEAD):
        hit, arg = dispatch_head_and_arg(f"{head} scene")
        assert hit
        result = ic.build_narration_control_result(
            config=cfg,
            request_id=f"req-{head}",
            subcommand=arg,
            session_type="private",
            session_key=f"private:{_PRIVATE_QQ}",
            sender_id=_PRIVATE_QQ,
            sender_roles=[],
        )
        assert "slash_narration:scene" in list(result.audit_tags or [])
        assert cr.read_narration_pin(
            f"private:{_PRIVATE_QQ}", sender_id=_PRIVATE_QQ, config=cfg
        ) == cr.NARRATION_MODE_SCENE
        cr.clear_narration_pin(f"private:{_PRIVATE_QQ}", sender_id=_PRIVATE_QQ, config=cfg)


# ===========================================================================
# G-3 腿②（席 CB-CMDUNIFY-20261008）：链尾「未知子命令必须被拒」
# ===========================================================================
# 与本文件既有条文同族（上面第 ③ 组判的正是"认不出＝不受理，绝不悄悄开档"），
# 那一族判的是 narration 自家子命令表；本组把同一条纪律抬到**根分发链的链尾**：
# `/bot <认不出的东西>` 不许再静默坠帮助总览（旧形态下 /bot chat、打错的
# /bot recemt 都会拿到一张无关总览页，看着像"回了"，其实什么都没发生）。
# 尺沿用上文 dispatch_head_and_arg 的口径：**执行**根里那一支的条件式原文
# （不另写第二份解析逻辑），末支 builder 名与词头集都从 AST 现算，一枚不手抄。
# 注毒三枚：①末支被换回 help 兜底 ⇒ 红；②条件式退回 `!= "status"` 那种
# Catch-all ⇒ 红；③在册裸形被收过头拒掉 ⇒ 红（防反向事故）。

_UNREGISTERED_PROBES: tuple[str, ...] = ("zzzfabricated", "chat", "recemt")
#: 注毒③样本＝「以后谁把兜底收过头」的形态（commands 族被一并拒掉）
_OVER_TIGHT_GUARD = 'is_help_surface_form(command_text) and command_text != "commands"'
#: 在册默认裸形（G-1 显式登记；这把尺只验它们**仍然**不被拒，词表真身在 echo）
_REGISTERED_DEFAULT_FORMS: tuple[str, ...] = ("", "help 点歌", "帮助", "commands", "命令目录")


def _status_chain_legs() -> list[tuple[str, list[ast.stmt]]]:
    """把 `_handle_status` 的 if/elif 链**按序**摊平：(条件式源码, 体内语句)；末支 else 记作空串。"""
    src = _INIT_SRC_PATH.read_text(encoding="utf-8")
    handler = _status_handler(_init_tree())
    root = next((st for st in handler.body if isinstance(st, ast.If)), None)
    if root is None:
        raise AssertionError("_handle_status 里找不到 if/elif 分发链")
    legs: list[tuple[str, list[ast.stmt]]] = []
    node: ast.If | None = root
    while isinstance(node, ast.If):
        legs.append((ast.get_source_segment(src, node.test) or "", node.body))
        orelse = node.orelse
        if len(orelse) == 1 and isinstance(orelse[0], ast.If):
            node = orelse[0]
        elif orelse:
            legs.append(("", list(orelse)))
            node = None
        else:
            node = None
    return legs


def _head_of(value: object) -> str:
    return str(value or "").strip().lower().split(maxsplit=1)[0].strip()


def dispatch_facts() -> dict[str, object]:
    """现算：链上字面词头集 / 链尾末支 builder 名 / 帮助支条件式原文 / 支数。"""
    legs = _status_chain_legs()
    heads: set[str] = set()
    for test_src, _body in legs:
        node = ast.parse(f"if ({test_src}): pass").body[0].test
        for comp in ast.walk(node):
            if isinstance(comp, ast.Compare) and isinstance(comp.left, ast.Name) \
                    and comp.left.id == "command_text":
                for other in comp.comparators:
                    values = other.elts if isinstance(other, (ast.Tuple, ast.List, ast.Set)) else [other]
                    for element in values:
                        if isinstance(element, ast.Constant):
                            heads.add(_head_of(element.value))
            if isinstance(comp, ast.Call) and isinstance(comp.func, ast.Attribute) \
                    and comp.func.attr == "startswith" and isinstance(comp.func.value, ast.Name) \
                    and comp.func.value.id == "command_text" and comp.args:
                first = comp.args[0]
                values = first.elts if isinstance(first, (ast.Tuple, ast.List)) else [first]
                for element in values:
                    if isinstance(element, ast.Constant):
                        heads.add(_head_of(element.value).rstrip(" "))
    terminal_calls = {
        call.func.id
        for call in ast.walk(ast.Module(body=list(legs[-1][1]), type_ignores=[]))
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
        and call.func.id.startswith("build_")
    }
    help_leg = next(
        (t for t, body in legs if t and any(_calls_named(st, "build_help_result") for st in body)),
        "",
    )
    return {
        "heads": frozenset(heads),
        "terminal_builders": frozenset(terminal_calls),
        "help_guard_src": help_leg,
        "leg_count": len(legs),
    }


def help_guard_swallows(guard_src: str, command_text_value: str) -> bool:
    """**执行**帮助那一支的条件式原文（真口 resolve_help_query），判它收不收得住。"""
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import (
        is_help_surface_form,
        resolve_help_query,
    )

    ns: dict[str, object] = {
        "resolve_help_query": resolve_help_query,
        "is_help_surface_form": is_help_surface_form,
    }
    exec(  # noqa: S102 - 跑仓库自己的生产条件式原文（与 dispatch_head_and_arg 同法）
        "def probe(command_text):\n    return bool((" + guard_src + "))\n",
        ns,
    )
    return bool(ns["probe"](command_text_value))  # type: ignore[operator]


def _rejection_problems(
    facts: dict[str, object], forms: tuple[str, ...] = _REGISTERED_DEFAULT_FORMS
) -> list[str]:
    problems: list[str] = []
    heads = set(facts["heads"])  # type: ignore[arg-type]
    if facts["terminal_builders"] != {"build_unknown_subcommand_result"}:
        problems.append(
            f"链尾末支不是拒绝口（实为 {sorted(facts['terminal_builders'])}）"  # type: ignore[arg-type]
        )
    guard = str(facts["help_guard_src"])
    for probe in _UNREGISTERED_PROBES:
        text = normalize_command_text(probe)
        if text in heads:
            problems.append(f"未登记动词 {probe} 竟然在册（词头集被当了垃圾桶）")
        elif help_guard_swallows(guard, text):
            problems.append(f"未知子命令 {probe} 又被帮助支吞了＝静默兜底复活")
    for form in forms:
        if normalize_command_text(form) not in heads and not help_guard_swallows(
            guard, normalize_command_text(form)
        ):
            problems.append(f"在册裸形 {form!r} 被拒了＝手感变了（G-1 不许动这一格）")
    if "status" not in heads:
        problems.append("`status` 不再是链上的字面支＝旧 else 兜底又被当成状态口")
    if "decision" not in heads:
        problems.append("`decision` 分发支不见了＝G-2（乙）的接线被摘掉")
    return problems


def test_unknown_subcommand_is_refused_and_registered_defaults_kept() -> None:
    """主门：链尾必是拒绝口；未登记动词一律拒；在册裸形一枚不许变。"""
    facts = dispatch_facts()
    assert facts["terminal_builders"], "链尾末支里没有任何 builder 调用＝尺读空"
    problems = _rejection_problems(facts)
    assert not problems, "链尾兜底纪律破了：" + "；".join(problems)


def test_rejection_leg_catches_silent_fallback_return() -> None:
    """注毒①＋②：末支换回旧 help 兜底、或条件式退回 Catch-all ⇒ 必红。"""
    facts = dispatch_facts()
    old_shape = dict(facts, terminal_builders={"build_help_result"})
    assert any("不是拒绝口" in p for p in _rejection_problems(old_shape)), (
        "注毒①未奏效：链尾被换成 help 兜底，门照样绿"
    )
    catch_all = dict(facts, help_guard_src="command_text != 'status'")
    assert any("又被帮助支吞了" in p for p in _rejection_problems(catch_all)), (
        "注毒②未奏效：条件式改回 Catch-all，门照样绿"
    )


def test_rejection_leg_catches_registered_default_removal() -> None:
    """注毒③：让在册裸形 `commands` 被帮助面拒收 ⇒ 「手感变了」必红（防反向事故）。"""
    facts = dispatch_facts()
    assert not _rejection_problems(facts), "前提失效：当前树上已有别的破绽"
    over_tight = dict(facts, help_guard_src=_OVER_TIGHT_GUARD)
    problems = _rejection_problems(over_tight)
    assert any("commands" in p for p in problems), (
        "注毒③未奏效：在册裸形被拒，门照样绿"
    )


# ===========================================================================
# G-4 腿（席 CMD-SLASH-HEADS-20261008）：把「册上没登记成子令、过去靠兜底混一张总览页」
# 的那几枚中文/英文词头补成**真分派支**之后的判据（用户 2026-10-08 裁「把这几枚补成真支，
# 能补都补」＋「中英文都要」；被点名的形＝`/bot 天气 上海`｜`/bot 点歌 X`｜`/bot wiki X`｜
# `/bot 人格`｜`/bot 维基 …`｜`/bot 百科 …`）
# ===========================================================================
# 与本件既有条文**同法**：尺不抄生产表达式，而是把根链里那一支的条件式与剥词头算式原文
# 抽出来 exec——生产的字面量与算式逐字被执行，测试里没有第二份解析逻辑。四件事：
# ① 每族**有且只有一支**通路（零命中＝分派支缺席、又被拒止支拒掉；两命中＝第二通路）；
# ② 英文正形与每一枚中文同义派到同一支、剥出的参数串逐字相同（旧敲形＝在册兼容别名，
#    词面真身住 `runtime/aliases.py::MODULE_ALIASES`，本件不抄清单、逐枚现问过归一口）；
# ③ 参数**真交到了能力手里**：连 `def capability` 整支 body 一起 exec，把装配现场那枚
#    构造口换成间谍，断它收到的 plain_text 逐字含「上海」/「晴天」/「量子力学」——
#    🔴 不是只断"没抛"（简报判据③）。
# ④ 管理面/隐私面不被新支绕过：`/bot 人格` 走的仍是原来那支 `bot.persona`（本波对它
#    零新增分支＝零新增绕门面，门在 `build_persona_query_result` 体内的 `_is_admin`）；
#    `/bot 点歌模式` 只把 `actor_roles` 交给既有 `build_music_mode_result`，接入层
#    自己不写第二道 admin 门。

#: 族名 → (那一支调用的构造口/builder 名, 英文正形词头列)
_HEAD_FAMILY: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("weather", "_build_weather_with_backend", ("weather",)),
    ("music", "build_music_capability", ("music",)),
    ("music_mode", "build_music_mode_result", ("music_mode", "music mode")),
    ("wiki", "_build_wiki_with_backend", ("wiki",)),
)

#: 中文同义词头（＝她点名的旧可敲形；归一后必须落到上面的英文正形）
_CN_HEADS: dict[str, tuple[str, ...]] = {
    "weather": ("天气", "查天气", "天气预报", "天氣", "查天氣", "天氣預報"),
    "music": ("点歌", "點歌", "点唱", "點唱"),
    "music_mode": ("点歌模式", "點歌模式"),
    "wiki": ("维基", "百科", "維基", "维基百科", "維基百科"),
    "persona": ("人格",),
}


def leg_calling(builder: str) -> tuple[str, list[ast.stmt]]:
    """根链里「体内调用 builder」那唯一一支的（条件式原文, 语句表）。

    零命中 ⇒ 分派支缺席（这一族词头今天会被链尾拒止支拒掉）；多于一支 ⇒ 第二通路。
    两种都当场报警，不退化成"绿着承认没接线"。
    """
    hits: list[tuple[str, list[ast.stmt]]] = []
    for test_src, body in _status_chain_legs():
        if any(_calls_named(stmt, builder) for stmt in body):
            hits.append((test_src, body))
    if not hits:
        raise AssertionError(
            f"根链 _handle_status 里没有任何一支调用 {builder}"
            " ⇒ 该词头派不到能力（册上教它、链上拒它）"
        )
    if len(hits) > 1:
        raise AssertionError(f"{builder} 在根链上有 {len(hits)} 支通路（禁第二通路）")
    return hits[0]


def _head_strip_stmt(body: list[ast.stmt], src: str) -> tuple[str, str]:
    """交出「从 command_text 剥掉词头」那一句的源码与目标变量名。"""
    for stmt in body:
        if not isinstance(stmt, ast.Assign) or not stmt.targets:
            continue
        target = stmt.targets[0]
        if not (
            isinstance(target, ast.Name)
            and (target.id.endswith("_query") or target.id.endswith("_argument"))
        ):
            continue
        seg = ast.get_source_segment(src, stmt)
        if seg and "command_text" in seg:
            return target.id, seg
    raise AssertionError("这一支里没有剥词头的赋值（参数串没交回子命令）")


def branch_head_and_arg(builder: str, raw_args: str) -> tuple[bool, str]:
    """**执行**生产条件式与剥词头算式原文；入参是用户原始参数串（先过真口归一）。"""
    src = _INIT_SRC_PATH.read_text(encoding="utf-8")
    test_src, body = leg_calling(builder)
    var_name, assign_src = _head_strip_stmt(body, src)
    probe = (
        "def probe(command_text):\n"
        f"    if {test_src}:\n"
        f"{textwrap.indent(assign_src, '        ')}\n"
        f"        return True, {var_name}\n"
        "    return False, ''\n"
    )
    ns: dict[str, Any] = {}
    exec(compile(probe, "<dispatch-probe>", "exec"), ns)  # noqa: S102 - 跑仓库自己的生产算式原文
    return ns["probe"](normalize_command_text(raw_args))


class _SpyMessage:
    """最小契约替身：生产那一支只会 `model_copy(update={"plain_text": …})`。"""

    def __init__(self, plain_text: str = "") -> None:
        self.plain_text = plain_text
        self.request_id = "req-g4"

    def model_copy(self, update: dict[str, Any] | None = None) -> _SpyMessage:
        clone = _SpyMessage(self.plain_text)
        clone.request_id = self.request_id
        for key, value in (update or {}).items():
            setattr(clone, key, value)
        return clone


class _SpyDecision:
    actor_roles: ClassVar[list[str]] = ["user"]


def run_branch_capability(builder: str, raw_args: str) -> dict[str, Any]:
    """**执行整支生产分支**（条件式＋剥词头＋`def capability`），把能力构造口换成间谍。

    body 用 `ast.unparse` 重排缩进（字面量与算式逐字保留，只由 AST 负责缩进），
    测试里仍然没有第二份解析逻辑。返回间谍读数。
    """
    from plugins.bot_unified_runtime.contracts import CapabilityResult, IncomingMessage

    test_src, body = leg_calling(builder)
    body_src = textwrap.indent(
        ast.unparse(ast.Module(body=list(body), type_ignores=[])), "        "
    )
    probe = (
        "def probe(command_text, message, _decision):\n"
        f"    if {test_src}:\n"
        f"{body_src}\n"
        "        return capability(message, _decision), capability_id\n"
        "    return None, ''\n"
    )
    seen: dict[str, Any] = {"called": False, "plain_text": "", "kwargs": {}, "args": ()}

    def _record(message: Any, decision: Any) -> Any:
        seen["called"] = True
        seen["plain_text"] = str(getattr(message, "plain_text", ""))
        seen["decision"] = decision
        return CapabilityResult(
            request_id="req-g4", capability_id="bot.g4", kind="text", body="间谍回执"
        )

    def _factory(*args: Any, **kwargs: Any) -> Any:
        seen["args"] = args
        seen["kwargs"] = dict(kwargs)
        return _record

    ns: dict[str, Any] = {
        "CapabilityResult": CapabilityResult,
        "IncomingMessage": IncomingMessage,
        "Any": Any,
        "config": SimpleNamespace(bot_music_default_mode="card+voice+link"),
        "runtime_settings": SimpleNamespace(get=lambda _key, _cfg: "card+voice+link"),
        "music_request_store": object(),
        "music_candidate_providers": lambda _provider: {},
        "build_cookie_provider": lambda _cfg: object(),
        "render_backend": None,
        "build_music_capability": _factory,
        "_build_weather_with_backend": _factory,
        "_build_wiki_with_backend": _factory,
    }
    exec(compile(probe, "<branch-probe>", "exec"), ns)  # noqa: S102 - 跑仓库自己的生产分支原文
    result, capability_id = ns["probe"](
        normalize_command_text(raw_args), _SpyMessage(), _SpyDecision()
    )
    seen["capability_id"] = capability_id
    seen["result"] = result
    return seen


# ------------------------------------------------------ ①＋② 两支都派得到、参数逐字同形


@pytest.mark.parametrize(("canonical", "builder", "en_heads"), _HEAD_FAMILY)
def test_english_head_and_chinese_synonyms_dispatch_to_the_same_leg(
    canonical: str, builder: str, en_heads: tuple[str, ...]
) -> None:
    """英文正形与每一枚中文同义派到**同一支**，剥出的参数串逐字相同（旧敲形＝在册别名）。"""
    baseline: str | None = None
    for head in (*en_heads, *_CN_HEADS[canonical]):
        hit, stripped = branch_head_and_arg(builder, f"{head} 参数甲")
        assert hit, f"/bot {head} 参数甲 派不到 {builder}＝这一枚还没补成真支"
        assert stripped == "参数甲", (head, stripped)
        baseline = baseline if baseline is not None else stripped
        assert stripped == baseline, f"{head} 剥出的参数与同族别支不同形＝手感分裂"


def test_bare_persona_head_dispatches_through_the_original_leg_only() -> None:
    """`/bot 人格`（无参数）走的仍是原来那支 `bot.persona`：本波对它零新增分支。

    🔴 这一支**按设计就没有剥词头那一句**（只有裸词头成立，带参数不进这支），所以不能
    复用 `branch_head_and_arg`——那个 helper 的前置条件是"支里有 `_query`/`_argument`
    赋值"，拿它判裸支只会得到"没剥词头"这种**假红**（2026-10-08 实测就是这个形状）。
    这里改成只 exec 生产条件式原文，并且**比原来更严**：裸形必须派得到、带参数必须派不到。
    """
    src = _INIT_SRC_PATH.read_text(encoding="utf-8")
    test_src, _body = leg_calling("build_persona_query_result")
    probe = f"def probe(command_text):\n    return bool(({test_src}))\n"
    ns: dict[str, Any] = {}
    exec(compile(probe, "<bare-persona-probe>", "exec"), ns)  # noqa: S102 - 跑生产条件式原文
    for head in ("persona", "人格"):
        assert ns["probe"](normalize_command_text(head)) is True, head
        assert ns["probe"](normalize_command_text(f"{head} 参数甲")) is False, head
    seg = src.count("build_persona_query_result(")
    assert seg == 1, f"根链里 `build_persona_query_result` 出现 {seg} 处（>1＝第二通路）"


@pytest.mark.parametrize(("canonical", "builder", "en_heads"), _HEAD_FAMILY)
def test_head_family_survives_the_chain_tail(
    canonical: str, builder: str, en_heads: tuple[str, ...]
) -> None:
    """拒止支不再拒这一族：链上字面词头集必须认得每一枚（归一后的正形才算）。"""
    del builder
    heads = set(dispatch_facts()["heads"])
    for head in (*en_heads, *_CN_HEADS[canonical]):
        normalized = normalize_command_text(head).split(maxsplit=1)[0]
        assert normalized in heads or head in heads, (
            f"/bot {head} 既不在链上字面词头集、归一后也不在 ⇒ 又被链尾拒止支拒掉"
        )


# ------------------------------------------------------ ③ 参数真交出去（不是"没抛"）


def test_weather_branch_hands_the_city_string_to_the_weather_capability() -> None:
    """`/bot 天气 上海` 交出去的 plain_text 逐字＝「天气 上海」（能力自家 `_WEATHER_RE` 的口）。"""
    for head in ("天气", "weather", "天氣", "查天气"):
        seen = run_branch_capability("_build_weather_with_backend", f"{head} 上海")
        assert seen["called"], f"/bot {head} 上海 根本没派到天气能力"
        assert seen["plain_text"] == "天气 上海", (head, seen["plain_text"])
        assert seen["capability_id"] == "bot.weather", seen["capability_id"]


def test_district_branch_hands_the_province_to_the_weather_capability() -> None:
    """`/bot 支持区县 浙江` 交出去的 plain_text 逐字＝「支持区县 浙江」（能力的第二条腿）。"""
    for head in ("支持区县", "districts", "可查区县"):
        seen = run_branch_capability("_build_weather_with_backend", f"{head} 浙江")
        assert seen["called"], f"/bot {head} 浙江 根本没派到天气能力"
        assert seen["plain_text"] == "支持区县 浙江", (head, seen["plain_text"])
        assert seen["capability_id"] == "bot.weather", seen["capability_id"]


def test_music_branch_hands_the_song_to_the_music_capability() -> None:
    """`/bot 点歌 晴天`／`/bot music 晴天` 交出去的 plain_text 逐字＝「点歌 晴天」。"""
    for head in ("点歌", "music", "點歌", "点唱"):
        seen = run_branch_capability("build_music_capability", f"{head} 晴天")
        assert seen["called"], f"/bot {head} 晴天 根本没派到点歌能力"
        assert seen["plain_text"] == "点歌 晴天", (head, seen["plain_text"])
        assert seen["capability_id"] == "bot.music", seen["capability_id"]
        # 运行期模式与候选 providers 必须同源交出去（否则新支就成了"丢注入"的第二通路）
        assert "default_mode" in seen["kwargs"] and "request_store" in seen["kwargs"], seen["kwargs"]


def test_wiki_branch_hands_the_entry_to_the_wiki_capability() -> None:
    """`/bot wiki X`／`/bot 维基 X`／`/bot 百科 X` 交出去的 plain_text 逐字带词条名。"""
    for head in ("wiki", "维基", "百科", "維基", "维基百科"):
        seen = run_branch_capability("_build_wiki_with_backend", f"{head} 量子力学")
        assert seen["called"], f"/bot {head} 量子力学 根本没派到维基能力"
        assert seen["plain_text"] == "维基 量子力学", (head, seen["plain_text"])
        assert seen["capability_id"] == "bot.wiki", seen["capability_id"]


def test_music_mode_branch_strips_head_and_forwards_roles_without_a_second_gate() -> None:
    """`/bot 点歌模式 卡片+语音`：剥词头交给**既有** builder，接入层不重写第二道管理门。"""
    for head in ("点歌模式", "music_mode", "music mode"):
        hit, stripped = branch_head_and_arg("build_music_mode_result", f"{head} 卡片+语音")
        assert hit, f"/bot {head} 卡片+语音 派不到点歌模式支"
        assert stripped == "卡片+语音", (head, stripped)
    _test_src, body = leg_calling("build_music_mode_result")
    seg = ast.unparse(ast.Module(body=list(body), type_ignores=[]))
    assert "actor_roles" in seg, "点歌模式支没转交角色＝管理门会被新支绕过"
    assert '"admin"' not in seg, "接入层自己另写了一道 admin 门＝第二处管理门（门只住 builder 体内）"


def test_music_mode_branch_beats_music_branch_for_the_mode_phrase() -> None:
    """🔴 序判据：`/bot music mode 卡片` 归点歌模式，不归点歌（否则成"搜一首叫 mode 卡片 的歌"）。

    判法只能按**链序取第一支命中**：`music ` 前缀本来就吃 `music mode …`，两支持有人的
    条件式对这串都成立——真正守住手感的是先后顺序，不是某一支自己写得多严。所以这里
    不再要求"`music` 支的条件式判不到"（那形不可能成立，硬要就变成假红），改成直接问链
    上第一个命中的是谁。
    """

    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import (
        is_help_surface_form,
    )
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.memory import (
        is_memory_command_text,
    )

    def first_matching_leg(text: str) -> str:
        probe_value = normalize_command_text(text)
        for cond, body in _status_chain_legs():
            if not cond.strip():
                continue
            ns: dict[str, Any] = {
                # 链上条件式里出现的两枚谓词必须给真身（不是替身）：缺一枚就是
                # NameError＝整条序判据变成假绿，所以宁可让它响亮地红。
                "is_memory_command_text": is_memory_command_text,
                "is_help_surface_form": is_help_surface_form,
            }
            exec(  # noqa: S102 - 跑生产条件式原文，不另写第二份判定
                compile(
                    f"def probe(command_text):\n    return bool(({cond}))\n",
                    "<order-probe>",
                    "exec",
                ),
                ns,
            )
            if ns["probe"](probe_value):
                return ast.unparse(ast.Module(body=list(body), type_ignores=[]))
        return ""

    mode_seg = first_matching_leg("music mode 卡片")
    assert "build_music_mode_result" in mode_seg, (
        f"第一命中的不是点歌模式支，而是：{mode_seg[:160]!r}"
    )
    assert "build_music_capability(" not in mode_seg, "点歌模式支里混进点歌构造＝两支没分开"
    song_seg = first_matching_leg("music 晴天")
    assert "build_music_capability(" in song_seg, (
        f"普通点歌没落到点歌支，而是：{song_seg[:160]!r}"
    )
    hit_mode, stripped_mode = branch_head_and_arg("build_music_mode_result", "music mode 卡片")
    assert hit_mode and stripped_mode == "卡片", (hit_mode, stripped_mode)
    hit_song, stripped_song = branch_head_and_arg("build_music_capability", "music 晴天")
    assert hit_song and stripped_song == "晴天", (hit_song, stripped_song)


# ------------------------------------------------------ 注毒：尺两头都要有牙


def test_g4_leg_catches_a_detached_dispatch_branch() -> None:
    """注毒①：把某一枚词头从链上字面量里摘掉（模拟分派支被撤）⇒ 「又被拒止支拒掉」必红。"""
    heads = set(dispatch_facts()["heads"])
    assert "weather" in heads, "前提失效：天气分派支本就不在链上"
    for head in ("music", "wiki"):
        assert head in heads, f"前提失效：{head} 支不在链上"
    poisoned = heads - {"weather"}
    victim = normalize_command_text("天气").split(maxsplit=1)[0]
    assert victim not in poisoned, (
        "注毒未奏效：摘掉 `startswith(\"weather \")` 的字面量后归一形仍在词头集里"
        " ⇒ 本腿其实没在比真字面量"
    )
    # 反向不误伤：其余成员仍在
    assert {"music", "wiki"} <= poisoned


def test_g4_leg_catches_parameter_being_dropped_on_the_floor() -> None:
    """注毒②：把剥词头算式改成常量（生产里若有人写死参数）⇒ 参数透传腿必红。"""
    src = _INIT_SRC_PATH.read_text(encoding="utf-8")
    _test_src, body = leg_calling("_build_weather_with_backend")
    var_name, _assign_src = _head_strip_stmt(body, src)
    fake = f"{var_name} = ''"
    probe = (
        "def probe(command_text):\n"
        f"    if {textwrap.indent(_test_src, '    ').lstrip()}:\n"
        f"{textwrap.indent(fake, '        ')}\n"
        f"        return True, {var_name}\n"
        "    return False, ''\n"
    )
    ns: dict[str, Any] = {}
    exec(compile(probe, "<poison-probe>", "exec"), ns)  # noqa: S102 - 合成的是本件自己的形状
    assert ns["probe"](normalize_command_text("天气 上海")) == (True, ""), "合成毒形未被剥出空串"
    # 真件那支剥出的必须是「上海」——两形不同 ⇒ 上面那条断言确实抓到了"参数被吃掉"这一型
    assert branch_head_and_arg("_build_weather_with_backend", "天气 上海") == (True, "上海")
