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
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

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
