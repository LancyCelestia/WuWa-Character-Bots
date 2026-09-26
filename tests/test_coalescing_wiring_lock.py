"""需求 1「分句合并单次回复」的**根装配段活性锁**（席位 S-T-COAL-LOCK）。

为什么需要这把锁
----------------
折句的行为锁全家（``tests/test_message_coalescing.py``，28 例）测的都是
``message_coalescing`` 模块自己：把同一个人连发的多条短句折成一轮。
但**生产里到底有没有人调用它**，那一族一条都没断言。

根 ``plugins/bot_unified_runtime/__init__.py`` 的装配段（现算坐标见下）一旦被人删掉、
或把关键实参换成硬编码常量，那 28 例仍然全绿，而线上退化成「每条碎片各回一句」
——静默回归。这正是 D-8(a) 那一族的病：「机制存在但装配落空 = 线上零生效而测试全绿」
（台账 #45/#47/#50 三次实犯，先例锁 = ``tests/test_progress_ack.py`` 的
「装配可达性锁」段、poke/randpic 同型）。

本锁不 import 包内任何模块
------------------------
根件近万行且 import 面会被并发席半写污染（本波已实证三次：``domains/core/safety_exec/paths.py``
一类件被半写出 ``IndentationError``，打断整条 import 链，而 ``__pycache__`` 里可能存着
编译成功的旧 .pyc ⇒ 同一命令两次给相反读数）。故一律走 ``ast`` **静态解析源码文本**，
零 import、零执行、不受在飞 .pyc 影响。

现算装配段坐标（本席 ``grep -n`` 所得，非简报抄写）
------------------------------------------------
- ``_handle_chat``：``__init__.py:8275``（装饰器 ``@chat.handle()`` 在 8274）
- 折句块：``8595``（注释起）/ ``8600-8602``（函数体内 import）/ ``8604``（门）
  / ``8605-8607``（设置→折句器）/ ``8608-8610``（``await offer(...)``）
  / ``8611-8620``（未拿到轮次 → 记账 + ``return``）/ ``8621``（``message = _turn.message``）
- 进管道：``8630`` ``pipeline.handle_async(...)`` ⇒ 折句在**入站、进管道之前**。

注毒怎么做（纪律禁写根件）
------------------------
在**内存里的源码字符串副本**上注毒，真实文件零字节改动；每条变异都先自证
"确实改动了、且改动后的 AST 里目标节点真的不在了"，否则注毒会退化成空跑
（``SEAT-MAIN`` 那条"注毒台先自试"的制度补丁）。
"""

from __future__ import annotations

import ast
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# 只读坐标（本席不许写任何生产件）
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parents[1]
ROOT_INIT = _ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"
_COALESCING = (
    _ROOT
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "chat_reply"
    / "runtime"
    / "message_coalescing.py"
)
_CONFIG = _ROOT / "plugins" / "bot_unified_runtime" / "config.py"

# 注毒复跑开关（只服务杀伤力验证，禁在日常门禁里设它）：
# 把根件复制一份、在副本上删装配段，然后
#   BOT_COALESCING_LOCK_ROOT=<副本绝对路径> pytest tests/test_coalescing_wiring_lock.py
# ⇒ 装配判据逐条字面变红，而仓库里的根 __init__.py 一个字节都不动。
ROOT_OVERRIDE_ENV = "BOT_COALESCING_LOCK_ROOT"


def _root_source() -> str:
    return (
        Path(os.environ[ROOT_OVERRIDE_ENV])
        if os.environ.get(ROOT_OVERRIDE_ENV)
        else ROOT_INIT
    ).read_text(encoding="utf-8")

HANDLER_NAME = "_handle_chat"
MODULE_ALIAS = "_coalescing"  # `import message_coalescing as _coalescing`
COALESCER_VAR_HINT = "_coalescer"
TURN_VAR_HINT = "_turn"

COALESCING_CONFIG_KEYS = frozenset(
    {
        "bot_chat_message_coalescing_enabled",
        "bot_chat_message_coalescing_quiet_seconds",
        "bot_chat_message_coalescing_max_hold_seconds",
        "bot_chat_message_coalescing_max_messages",
        "bot_chat_message_coalescing_max_chars",
    }
)


def _loads(source: str, origin: str) -> ast.Module:
    """解析源码文本；语法错单独点名（并发半写 ≠ 装配段被删）。

    本波已实证三次：别的席半写某件会造成收集期 ``SyntaxError``/``IndentationError``，
    而 ``__pycache__`` 里可能存着编译成功的旧 .pyc ⇒ 同一命令两次给相反读数。
    本锁纯静态读文本，不 import、不执行，故只可能被"读到半截"影响，绝不会被旧 .pyc 骗。
    """
    try:
        return ast.parse(source)
    except SyntaxError as exc:
        raise AssertionError(
            f"{origin} 第 {exc.lineno} 行语法错 —— 该件大概率正被别的席半写，"
            "等 60 秒复跑再判定；本锁只读它、不写它"
        ) from exc


def _parse(path: Path) -> ast.Module:
    """按路径读再解析（并发半写单独点名，别让它混成「我的锁红了」）。"""
    return _loads(path.read_text(encoding="utf-8"), path.name)


def _handler(source: str) -> ast.AsyncFunctionDef:
    """定位 chat 入站处理器（恰一枚，且真的在跑管道）。"""
    tree = _loads(source, "根 __init__.py")
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == HANDLER_NAME
    ]
    assert len(found) == 1, (
        f"根 __init__.py 里 {HANDLER_NAME} 应恰一枚（折句装配就住在它体内），"
        f"实={len(found)}"
    )
    handler = found[0]
    calls = {
        node.func.attr
        for node in ast.walk(handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "handle_async" in calls, (
        f"{HANDLER_NAME} 里没有 handle_async 调用 = 定位到的不是那条聊天主链，"
        "本锁全部坐标判据随之失效"
    )
    return handler


# ---------------------------------------------------------------------------
# 逐件判据（每件一个函数：既能对现网源码跑，也能对注毒副本跑）
# ---------------------------------------------------------------------------


def check_in_handler_import(src: str) -> None:
    """折句模块必须在**处理器函数体第一层**导入。

    函数体内 import 是刻意的（装配段注释自述）：在文件顶部插行会把
    ``campus_record_matcher`` 的登记坐标顶漂，撞上 ``outbound_registry`` 活体棘轮
    （同 5a 先例、台账 #50 两次实犯）。埋进可短路的分支里则是另一种失效——
    所以这里锁的是"函数体第一层"，不是"文件里出现过这句 import"。
    """
    handler = _handler(src)
    direct = [
        node
        for node in handler.body
        if isinstance(node, ast.ImportFrom)
        and any(
            alias.name == "message_coalescing" and alias.asname == MODULE_ALIAS
            for alias in node.names
        )
    ]
    assert len(direct) == 1, (
        f"{HANDLER_NAME} 函数体第一层应恰一枚 message_coalescing 导入，"
        f"实={len(direct)}（0=根本没带进来或已被挪到文件顶部/埋进分支，"
        ">1=出现第二处导入）"
    )


def check_gate_present_and_not_constant(src: str) -> None:
    """门条件 ``_coalescing.supports_coalescing(message)`` 在场，且不被硬编码常量决定。

    锁两半：① 判据谓词必须真的出现在 ``if`` 的 test 里，实参必须是 Name ``message``
    （写成常量 = 要么永不折、要么对所有消息一律折）；② ``and`` 的合取项里不得出现
    裸常量 —— 那正是「把门条件改成永假」的写法，而存在性检查照样绿。
    """
    handler = _handler(src)
    gates = [
        node
        for node in ast.walk(handler)
        if isinstance(node, ast.If) and _has_predicate(node.test)
    ]
    assert len(gates) == 1, (
        f"折句门（supports_coalescing）应恰一处，实={len(gates)}"
        "（0 处=装配被删，>1 处=出现第二条折句通路）"
    )
    test = gates[0].test
    bad = _constant_conjuncts(test)
    assert not bad, (
        "折句门被硬编码常量决定（永真/永假都能让它线上不干活而 AST 存在性照绿）："
        f"{bad}；行 {gates[0].lineno}"
    )


def _has_predicate(test: ast.expr) -> bool:
    """test 里是否含 `supports_coalescing(名字为 message 的实参)` 这一 Call 节点。"""
    for node in ast.walk(test):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "supports_coalescing"
        ):
            return _arg_is_name(node, 0, "message")
    return False


def _constant_conjuncts(test: ast.expr) -> list[str]:
    """收集 And/Or 里以裸常量出现的合取项（`and False` / `or True` 一类）。"""
    out: list[str] = []
    for node in ast.walk(test):
        if isinstance(node, ast.BoolOp):
            for value in node.values:
                if isinstance(value, ast.Constant):
                    out.append(f"{type(node).__name__}: {value.value!r}")
    return out


def _arg_is_name(call: ast.Call, index: int, expected: str) -> bool:
    if len(call.args) <= index:
        return False
    arg = call.args[index]
    return isinstance(arg, ast.Name) and arg.id == expected


def _walk_nodes(nodes: Iterable[ast.AST]) -> list[ast.AST]:
    """对一组语句节点做 ast.walk（ast.walk 只吃单个节点，不吃 list）。"""
    out: list[ast.AST] = []
    for node in nodes:
        out.extend(ast.walk(node))
    return out


def check_settings_built_from_config(src: str) -> None:
    """``build_coalescing_settings(config)`` 的实参必须是那个 ``config`` 对象。

    传 None / 传 ``CoalescingSettings()`` / 传字面量，五枚配置键会当场变成死键，
    而"设置构造调用在场"这种存在性断言完全看不出来。
    """
    handler = _handler(src)
    builds = [
        node
        for node in ast.walk(handler)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "build_coalescing_settings"
    ]
    assert len(builds) == 1, f"设置构造应恰一处，实={len(builds)}"
    assert len(builds[0].args) == 1, "build_coalescing_settings 只该收一个 config"
    arg = builds[0].args[0]
    assert isinstance(arg, ast.Name), (
        f"设置实参不是变量而是常量/表达式（{type(arg).__name__}）"
        " ⇒ 五枚折句键不再参与装配"
    )
    assert arg.id == "config", (
        f"设置实参应为 config（装配期那份 Config），实={arg.id}"
    )


def check_settings_reach_the_coalescer(src: str) -> None:
    """构造出的设置必须真的喂进 ``shared_coalescer``。

    写成 ``shared_coalescer(CoalescingSettings())`` 时：调用在场、参数是 Call、
    一切"看起来接上了"，但每轮都拿硬编码缺省值 ⇒ 五枚键全成死键。
    """
    handler = _handler(src)
    holders = [
        node
        for node in ast.walk(handler)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "shared_coalescer"
    ]
    assert len(holders) == 1, f"折句器构造点应恰一处，实={len(holders)}"
    call = holders[0]
    assert len(call.args) == 1 and not call.keywords, (
        "shared_coalescer 的参数形状变了，请同步本锁与装配段"
    )
    arg = call.args[0]
    assert isinstance(arg, ast.Call) and isinstance(
        arg.func, ast.Attribute
    ), "喂给折句器的不是构造调用 = 十有八九是硬编码常量"
    assert arg.func.attr == "build_coalescing_settings", (
        f"折句器拿到的设置来自 {arg.func.attr}，不是 build_coalescing_settings"
        " ⇒ 配置键到不了运行时"
    )


def check_offer_awaited_with_key_and_message(src: str) -> None:
    """核心那一句：``_turn = await _coalescer.offer(utterance_turn_key(message), message)``。

    三件一起锁，缺一就不再是"折句"：
    ① 必须 await（不 await = 拿到协程对象，owned 判定永远走偏）；
    ② 被调对象必须是从 ``shared_coalescer`` 拿来的那个变量（换成随手 new 一个
       局部折句器 = 窗口状态不跨事件共享 = 永远折不住，而调用形状一模一样）；
    ③ 分键必须由 ``utterance_turn_key(message)`` 现算，且第二个实参是 Name message。
    """
    handler = _handler(src)
    coalescer_names = {
        node.targets[0].id
        for node in ast.walk(handler)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and node.value.func.attr == "shared_coalescer"
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    }
    assert coalescer_names, "找不到 shared_coalescer 的赋值目标"

    offers = [
        node
        for node in ast.walk(handler)
        if isinstance(node, ast.Await)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and node.value.func.attr == "offer"
    ]
    assert len(offers) == 1, (
        f"折句 offer 的 await 应恰一处，实={len(offers)}（0 处=装配段那句被删，"
        "线上立刻退回逐条各回一句）"
    )
    call = offers[0].value
    assert isinstance(call, ast.Call)  # mypy 收窄：上面刚从 Await 里取出的 expr
    assert isinstance(call.func, ast.Attribute)
    assert isinstance(call.func.value, ast.Name) and call.func.value.id in (
        coalescer_names
    ), (
        f"offer 调在 {ast.unparse(call.func.value)} 上，不是 shared_coalescer "
        "交出的那个共享折句器 ⇒ 窗口不跨事件共享，永远折不住"
    )
    assert len(call.args) == 2, (
        f"offer 需要 (分键, 消息) 两个实参，实={len(call.args)}"
    )
    key = call.args[0]
    assert isinstance(key, ast.Call) and isinstance(
        key.func, ast.Attribute
    ), "折句分键不是现算出来的（写死常量 = 全服共用一个窗口，串会话串人）"
    assert key.func.attr == "utterance_turn_key", (
        f"分键来自 {ast.unparse(key.func)}，不是 utterance_turn_key"
    )
    assert _arg_is_name(key, 0, "message"), "utterance_turn_key 的实参必须是 message"
    assert _arg_is_name(call, 1, "message"), (
        "offer 第二实参必须是当前消息；写死或换对象 = 折进去的不是这条内容"
    )


def check_non_owned_turn_short_circuits(src: str) -> None:
    """没拿到轮次的那一路必须**直接 return**，且不得进管道、且必须留下可见痕迹。

    「省下的正是多出来的回复次数」全在这一句 return 上：漏掉它 = 两条消息各回一句，
    而折句调用仍然在位、行为锁仍然全绿（模块内部本来就返回 owned=False）。
    观测事件 ``chat_turn_folded`` 也在这一路——被折掉的消息不能变成无痕消失
    （台账 #29⑪ 的「静默失败」口径）。
    """
    handler = _handler(src)
    branches = [
        node
        for node in ast.walk(handler)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.UnaryOp)
        and isinstance(node.test.op, ast.Not)
        and isinstance(node.test.operand, ast.Attribute)
        and node.test.operand.attr == "owned"
    ]
    assert len(branches) == 1, f"owned 判定分支应恰一处，实={len(branches)}"
    body = _walk_nodes(branches[0].body)
    returns = [node for node in body if isinstance(node, ast.Return)]
    assert returns, "未拿到轮次的那一路没有 return ⇒ 一句话仍会被回两次"
    assert all(
        node.value is None for node in returns
    ), "return 带了值 = 这条链的出口形状变了，请核对回复归属"
    piped = [
        node
        for node in body
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "handle_async"
    ]
    assert not piped, "被折掉的那条竟然还进管道 = 双份回复"
    logged = [
        node
        for node in _walk_nodes(branches[0].body)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_log_runtime_event"
        and any(
            isinstance(a, ast.Constant) and a.value == "chat_turn_folded"
            for a in node.args
        )
    ]
    assert logged, "折掉的消息未记 chat_turn_folded 事件 ⇒ 线上无从解释"


def check_merged_message_flows_to_pipeline(src: str) -> None:
    """``message = _turn.message`` 必须在场，且合并轮真的喂给后面的管道。

    只 await 不回填变量 = 折句器辛苦攒一轮，链路拿到的还是那条碎片。
    """
    handler = _handler(src)
    turn_names = {
        node.targets[0].id
        for node in ast.walk(handler)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Await)
        and isinstance(node.value.value, ast.Call)
        and isinstance(node.value.value.func, ast.Attribute)
        and node.value.value.func.attr == "offer"
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    }
    assert turn_names, "找不到 offer 结果的接收变量"
    rebinds = [
        node
        for node in ast.walk(handler)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "message"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "message"
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id in turn_names
    ]
    assert rebinds, (
        "合并后的那一轮没有回写给 message ⇒ 后面进管道的还是单条碎片"
    )


def _chat_pipeline_call(handler: ast.AsyncFunctionDef) -> ast.Call:
    """定位「把这一轮交给聊天能力」的那一次 handle_async。

    同一个处理器里有三处 handle_async（复读吐槽 8484 / 聊天 8630 / 链接内容 8849），
    拿"最早那一处"当锚点会假红（复读分支本就设计在折句之前短路回一句）。
    聊天主链的识别特征＝首两个位置实参是 ``message`` 与 ``chat_capability``。
    """
    hits = [
        node
        for node in ast.walk(handler)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "handle_async"
        and len(node.args) >= 2
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == "message"
        and isinstance(node.args[1], ast.Name)
        and node.args[1].id == "chat_capability"
    ]
    assert len(hits) == 1, (
        f"聊天主链的 handle_async(message, chat_capability) 应恰一处，实="
        f"{[node.lineno for node in hits]}（0=主链形状变了，本锁锚不住；"
        ">1=出现第二条聊天通路）"
    )
    return hits[0]


def check_folding_precedes_chat_pipeline(src: str) -> None:
    """折句必须早于「这一轮进聊天管道」（入站合轮，不是出站拼句）。

    位置就是这条能力的定义：晚进管道 = 每条碎片都已各回一句，合并无从谈起。
    按 lineno 比，不按"字符串出现过"——unparse 会把注释与文档串一起带上，
    一句注释就能单独满足存在性断言（先例：test_progress_ack 的 S11 探针教训）。
    """
    handler = _handler(src)
    call = _chat_pipeline_call(handler)
    fold_lines = [
        node.lineno
        for node in ast.walk(handler)
        if isinstance(node, ast.Await)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and node.value.func.attr == "offer"
    ]
    assert fold_lines, "找不到折句 offer 的 await，无从比顺序"
    assert max(fold_lines) < call.lineno, (
        f"折句（行 {fold_lines}）不再早于进聊天管道（行 {call.lineno}）"
        " ⇒ 它已从「入站合轮」漂成别的什么东西"
    )
    rebinds = [
        node.lineno
        for node in ast.walk(handler)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "message"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "message"
    ]
    assert rebinds, "合并轮没回写 message，比顺序无意义"
    assert max(rebinds) < call.lineno, (
        f"合并轮回写（行 {rebinds}）晚于进管道（行 {call.lineno}）= 喂进去的仍是碎片"
    )


def check_folding_follows_ingest_enrichment(src: str) -> None:
    """折句必须在「合并转发已展开 / 视频预处理已完成」之后。

    装配段注释写明了这个刻意的先后（"再早就会丢掉后补上的正文"）：
    碎片里那条被引用的合并转发，正文是上游 ``message.model_copy(...)`` 才补进
    ``plain_text`` 的（现算 8568），视频预处理 await 在 8578——折句在 8608。
    上游任一步被人摘掉或挪到折句之后 ⇒ 折出来的一句话会丢掉后补上的正文。
    """
    handler = _handler(src)
    fold_lines = [
        node.lineno
        for node in ast.walk(handler)
        if isinstance(node, ast.Await)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and node.value.func.attr == "offer"
    ]
    if not fold_lines:
        return  # 装配没了由 check_offer_awaited_* 点名，这里不重复红一次
    video = [
        node.lineno
        for node in ast.walk(handler)
        if isinstance(node, ast.Await)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "_prepare_video_understanding_message"
    ]
    forwarded = [
        node.lineno
        for node in ast.walk(handler)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "model_copy"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "message"
    ]
    assert video, "视频预处理富化步骤不在了，请核对装配段是否被搬动"
    assert forwarded, "合并转发/正文富化（message.model_copy）站点不在了，同上"
    assert min(fold_lines) > max(video), (
        f"折句（行 {min(fold_lines)}）跑到了视频预处理（行 {video}）之前"
    )
    assert min(fold_lines) > max(forwarded), (
        f"折句（行 {min(fold_lines)}）跑到了正文富化（行 {forwarded}）之前"
        " ⇒ 折出来的一句话会丢掉后补上的正文"
    )


CHECKS = (
    check_in_handler_import,
    check_gate_present_and_not_constant,
    check_settings_built_from_config,
    check_settings_reach_the_coalescer,
    check_offer_awaited_with_key_and_message,
    check_non_owned_turn_short_circuits,
    check_merged_message_flows_to_pipeline,
    check_folding_precedes_chat_pipeline,
    check_folding_follows_ingest_enrichment,
)


# ---------------------------------------------------------------------------
# 现网源码：逐件断言在位
# ---------------------------------------------------------------------------


def test_root_chat_handler_exists() -> None:
    handler = _handler(_root_source())
    assert handler.lineno > 0


def test_module_imported_inside_the_handler() -> None:
    check_in_handler_import(_root_source())


def test_gate_calls_supports_coalescing_on_message() -> None:
    check_gate_present_and_not_constant(_root_source())


def test_settings_come_from_the_assembly_config() -> None:
    check_settings_built_from_config(_root_source())


def test_settings_are_fed_into_the_shared_coalescer() -> None:
    check_settings_reach_the_coalescer(_root_source())


def test_offer_is_awaited_on_shared_coalescer_with_per_sender_key() -> None:
    check_offer_awaited_with_key_and_message(_root_source())


def test_non_owned_fragment_returns_without_replying_and_leaves_a_trace() -> None:
    check_non_owned_turn_short_circuits(_root_source())


def test_merged_turn_is_handed_back_as_the_message() -> None:
    check_merged_message_flows_to_pipeline(_root_source())


def test_folding_sits_before_the_chat_pipeline_call() -> None:
    check_folding_precedes_chat_pipeline(_root_source())


def test_folding_sits_after_the_ingest_enrichment() -> None:
    check_folding_follows_ingest_enrichment(_root_source())


def test_wiring_block_is_singled_out_not_duplicated() -> None:
    """全根只准有一处折句装配（禁第二真身，板块规范硬门）。"""
    tree = _loads(_root_source(), "根 __init__.py")
    for attr in (
        "supports_coalescing",
        "build_coalescing_settings",
        "shared_coalescer",
        "utterance_turn_key",
    ):
        hits = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == attr
        ]
        assert len(hits) == 1, f"{attr} 的调用点应全根唯一，实={hits}"


def test_coalescing_keys_are_real_config_fields() -> None:
    """五枚键名必须真是 ``Config`` 的字段。

    ``getattr(config, "bot_chat_message_coalescing_quiet_seconds", 缺省)`` 拼错一个
    字母不会报错，只会永远回落缺省值 ⇒ 键"在册、有读点、从不生效"。
    折句族的行为锁与装配锁都不碰这一层，故在此补一把纯 AST 的键名锁。
    """
    module = _parse(_COALESCING)
    builder = next(
        (
            node
            for node in ast.walk(module)
            if isinstance(node, ast.FunctionDef)
            and node.name == "build_coalescing_settings"
        ),
        None,
    )
    assert builder is not None, "message_coalescing.py 找不到 build_coalescing_settings"
    read_keys: set[str] = set()
    for node in ast.walk(builder):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "config"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
        ):
            read_keys.add(str(node.args[1].value))
    assert read_keys == set(COALESCING_CONFIG_KEYS), (
        f"折句读到的配置键与在册五枚不符：多={read_keys - COALESCING_CONFIG_KEYS} "
        f"少={COALESCING_CONFIG_KEYS - read_keys}"
    )

    config_tree = _parse(_CONFIG)
    classes = [
        node
        for node in ast.walk(config_tree)
        if isinstance(node, ast.ClassDef) and node.name == "Config"
    ]
    assert len(classes) == 1, f"config.py 里 Config 类应恰一枚，实={len(classes)}"
    fields = {
        target.id
        for node in classes[0].body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        for target in [node.target]
    }
    missing = sorted(read_keys - fields)
    assert not missing, (
        f"折句在读、Config 上没有的键（永远回落缺省）：{missing}"
    )


# ---------------------------------------------------------------------------
# 杀伤力自证：对内存副本注毒，本锁必须红（真实文件零改动）
# ---------------------------------------------------------------------------


def _drop_statement(src: str, marker: str) -> str:
    """删掉以 ``marker`` 起始那条语句（含其跨行括号尾巴）——在副本上操作。

    只认"这一句在场且唯一"，不认行号：根件正被别的席反复插行（本席实测同一分钟内
    9979 ↔ 10025 行来回跳），任何写死行号的注毒台都会打空。
    """
    lines = src.splitlines(keepends=True)
    start = [i for i, line in enumerate(lines) if marker in line]
    assert len(start) == 1, f"注毒目标 {marker!r} 命中 {len(start)} 行，判据不唯一"
    i = start[0]
    depth = 0
    j = i
    while j < len(lines):
        depth += lines[j].count("(") - lines[j].count(")")
        if depth <= 0:
            break
        j += 1
    assert j < len(lines), f"{marker!r} 这条语句括号永不闭合"
    del lines[i : j + 1]
    out = "".join(lines)
    assert marker not in out, "注毒未生效（等于空跑）"
    return out


def _drop_wiring_block(src: str) -> str:
    """删掉整段折句装配：从那句 ``from … import (message_coalescing as _coalescing,)``
    所在的多行 import 语句起，到 ``message = _turn.message`` 止。

    起点要回退到 import 语句的第一行，否则会把 ``from … import (`` 留下成半截语法。
    """
    lines = src.splitlines(keepends=True)
    hits = [i for i, line in enumerate(lines) if "message_coalescing as _coalescing" in line]
    assert len(hits) == 1, f"导入行命中 {len(hits)} 处，判据不唯一"
    start = hits[0]
    while start >= 0 and not lines[start].lstrip().startswith("from "):
        start -= 1
    assert start >= 0, "找不到那句 import 的起始行"
    ends = [i for i, line in enumerate(lines) if line.strip() == "message = _turn.message"]
    assert len(ends) == 1, f"装配段终点命中 {len(ends)} 处，判据不唯一"
    assert start < ends[0]
    del lines[start : ends[0] + 1]
    out = "".join(lines)
    assert "supports_coalescing" not in out, "注毒③没真的删掉装配段"
    return out


def _replace_once(src: str, old: str, new: str) -> str:
    assert src.count(old) == 1, f"注毒目标命中 {src.count(old)} 次，判据不唯一"
    out = src.replace(old, new)
    assert out != src, "注毒未生效（等于空跑）"
    return out


def _assert_parses(src: str, label: str) -> None:
    """注毒后的副本必须仍是**能解析的合法源码**。

    不加这一条，杀伤力可以是假的：变异若碰巧弄坏了括号/缩进，`_loads` 会把语法错
    转成 AssertionError ⇒ 十条判据"全红"，看起来锁很凶，实际测的是我的字符串手术。
    """
    _loads(src, f"{label}（注毒副本）")


def _assert_any_check_fails(src: str, label: str) -> list[str]:
    """返回变红的判据名；一个都没红 = 本锁对这种回归无杀伤力。"""
    failed: list[str] = []
    for check in CHECKS:
        try:
            check(src)
        except AssertionError:
            failed.append(check.__name__)
    assert failed, f"{label}：注毒后本锁全绿 = 假锁"
    return failed


def _check_fails(check, src: str) -> bool:
    try:
        check(src)
    except AssertionError:
        return True
    return False


# ---- 简报点名的两发 --------------------------------------------------------


def test_kill_power_deleting_the_offer_call_turns_the_lock_red() -> None:
    """注毒①：删掉 ``_turn = await _coalescer.offer(...)`` 那一句。

    这正是简报点名的回归：行为锁 28 例对这种删法完全无感（模块自己没被改），
    线上却立刻退回逐条各回一句。
    """
    src = _drop_statement(_root_source(), "await _coalescer.offer(")
    assert _check_fails(
        check_offer_awaited_with_key_and_message, src
    ), "删掉调用那一句，核心判据竟然还绿"
    failed = _assert_any_check_fails(src, "注毒①删调用")
    assert "check_offer_awaited_with_key_and_message" in failed


def test_kill_power_never_false_gate_turns_the_lock_red() -> None:
    """注毒②：把门条件改成永假（``... and False``）。

    门、调用、return 全部字面在场，只有真值变了——纯存在性锁对这种写法是瞎的，
    所以本锁额外锁「合取项里不得出现裸常量」。
    """
    src = _replace_once(
        _root_source(),
        "supports_coalescing(message)",
        "supports_coalescing(message) and False",
    )
    assert _check_fails(
        check_gate_present_and_not_constant, src
    ), "门被钉成永假，门判据竟然还绿"
    _assert_any_check_fails(src, "注毒②门永假")


# ---- 追加两发：证明锁不是只对着那两行字面量 --------------------------------


def test_kill_power_deleting_the_whole_wiring_block_turns_many_locks_red() -> None:
    """注毒③：整段折句装配删干净（简报"删掉这段装配"的完整形态）。"""
    mutated = _drop_wiring_block(_root_source())
    failed = _assert_any_check_fails(mutated, "注毒③删整段")
    assert len(failed) >= 4, f"整段装配都没了，只红 {len(failed)} 把：{failed}"


def test_kill_power_hardcoded_settings_turns_the_key_wiring_red() -> None:
    """注毒④：折句器改吃硬编码缺省设置（五枚配置键当场变死键）。

    这是最阴的一种：调用形状、await、门、return 全在，配置却再也到不了运行时。
    """
    src = _replace_once(
        _root_source(),
        "_coalescing.build_coalescing_settings(config)",
        "_coalescing.CoalescingSettings()",
    )
    assert _check_fails(
        check_settings_reach_the_coalescer, src
    ), "设置被换成硬编码常量，喂入判据竟然还绿"
    assert _check_fails(
        check_settings_built_from_config, src
    ), "设置构造被换掉，来源判据竟然还绿"


# ---- 注毒台自身的两条自证（防"以为在测毒、其实在测真身"）-------------------


def test_lock_reads_the_real_root_file_when_no_override_is_set() -> None:
    """日常判据必须读仓库真身；本席（和任何席）都不许为了让它红而去写真身。"""
    assert ROOT_OVERRIDE_ENV not in os.environ, (
        f"{ROOT_OVERRIDE_ENV} 正把本锁指向别的副本 ⇒ 此刻跑的不是真身，"
        "这个红/绿都不能当门禁结论（该变量只服务杀伤力复跑）"
    )
    assert _root_source() == ROOT_INIT.read_text(encoding="utf-8")
    assert ROOT_INIT.is_file(), f"根件不在位：{ROOT_INIT}"


def test_env_override_really_redirects_the_lock(monkeypatch) -> None:
    """开关必须是**真的**换了读取源，否则注毒台是在空跑（同一份源码测两遍）。"""
    live = _root_source()
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "root_init_mutated.py"
        copy.write_text(
            _drop_statement(live, "await _coalescer.offer("), encoding="utf-8"
        )
        monkeypatch.setenv(ROOT_OVERRIDE_ENV, str(copy))
        redirected = _root_source()
        assert redirected != live, "设了开关却没改变读取源 = 注毒台是假的"
        assert "await _coalescer.offer(" not in redirected
        # 从"副本"这条路进来，判据同样必须红（与 test_kill_power_* 同一条杀伤力，
        # 只是走的是外部可复跑的路径）。
        with pytest.raises(AssertionError):
            check_offer_awaited_with_key_and_message(redirected)
