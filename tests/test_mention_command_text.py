"""开头点名剥除（mentions.strip_leading_name_mention）+ 契约派生字段 command_text。

要修的实际缺陷（用户实弹）：群里习惯「先 @ 机器人再说指令」，而 L4 手动命令
「亲密模式 开」的判据 `_MANUAL_ON_RE` 带 `^...$` 锚，吃的是 `message.plain_text`
（含 @ 段渲染出的 "@守岸人" 文本）⇒ `match_manual_command("@守岸人 亲密模式 开")`
返回 None，这条自然语言指令在群内**永远不命中**。

根因面：`mentions.py` 只有"检测点名"的函数（`detect_name_mention`/
`starts_with_name_mention` 回 bool，`normalize_mention_text` 只剥开头的
`@ / ! 空白`，不剥昵称本身），**没有"剥掉开头那句称呼、返回剩下指令文本"的公共件**。
本件补的就是这第三只函数，并把它接在摄取层的派生字段上。

三把承重锁各配一发注毒（见 tests/test_mention_command_text.py 的 docstring 尾注）：
① 剥除语义（只剥开头一处、长 term 优先、空结果给空串、垃圾输入不抛）；
② 契约字段 `command_text`（默认空串安全、绝不覆盖 `plain_text`）；
③ 摄取层真填充（AST 活性锁：根 `__init__.py` 三处构造点都填、且判定用的是
   **被引用内容拼接之前**的那份文本——同文件 :1397-1404 的既有教训）。

复跑（本仓铁律 6 的四必带环境）：
    PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX="$TEMP/pyc-seatB" BOT_AUTOSYNC=0 \
    ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_mention_command_text.py \
        -p no:cacheprovider --basetemp="$TEMP/seatB-bt" -q
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

import plugins.bot_unified_runtime as runtime
from plugins.bot_unified_runtime import _incoming_from_nonebot_event
from plugins.bot_unified_runtime.domains.chat_reply.ingest.message_context import (
    ReplyChainItem,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime import mentions
from plugins.bot_unified_runtime.domains.chat_reply.runtime.aliases import (
    DEFAULT_PERSONA_NICKNAMES,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.content_route import (
    match_manual_command,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.mentions import (
    detect_name_mention,
    strip_leading_name_mention,
)
from plugins.bot_unified_runtime.domains.core import text_boundary
from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
    IncomingMessage,
    SessionType,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = PROJECT_ROOT / "plugins" / "bot_unified_runtime"

# 词表只引真身（不在本件抄一份昵称表——抄了就是第二真身）。
TERMS: tuple[str, ...] = DEFAULT_PERSONA_NICKNAMES


def _source(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


# ---------------------------------------------------------------- ① 剥除语义


def test_strips_at_prefixed_mention() -> None:
    """生产实测形态：@ 段在 plain_text 里渲染成 "@守岸人" 文本。"""
    assert strip_leading_name_mention("@守岸人 亲密模式 开", TERMS) == "亲密模式 开"
    assert strip_leading_name_mention("＠守岸人 亲密模式 开", TERMS) == "亲密模式 开"
    assert strip_leading_name_mention("@ 守岸人 亲密模式 开", TERMS) == "亲密模式 开"


def test_strips_comma_prefixed_mention() -> None:
    """裸昵称 + 标点（无 @）同样剥。"""
    assert strip_leading_name_mention("守岸人，亲密模式 开", TERMS) == "亲密模式 开"
    assert strip_leading_name_mention("岸宝，亲密模式 开", TERMS) == "亲密模式 开"
    # 称呼后紧跟时间/请求词首字也算边界（与 detect_name_mention 同口径），
    # 但请求词本身是正文的一部分：只剥称呼，不顺手把"帮"洗掉。
    assert strip_leading_name_mention("守岸人帮我查天气", TERMS) == "帮我查天气"


def test_strips_call_prefixed_mention() -> None:
    """呼叫/召唤形态：称呼不在串首，昵称被 _CALL_PATTERN 整段带走。"""
    assert strip_leading_name_mention("呼叫守岸人 亲密模式 开", TERMS) == "亲密模式 开"
    assert strip_leading_name_mention("召唤岸宝，亲密模式 关", TERMS) == "亲密模式 关"


def test_bare_mention_returns_empty_string() -> None:
    """只称呼不说话：返回空串，不返回 " "（空串才是"没有指令"的形状）。"""
    assert strip_leading_name_mention("@守岸人", TERMS) == ""
    assert strip_leading_name_mention("守岸人", TERMS) == ""
    assert strip_leading_name_mention("守岸人，", TERMS) == ""


def test_mid_sentence_mention_is_not_stripped() -> None:
    """只剥开头那一处：句中/句尾的昵称原样留着（"帮我记 守岸人 提醒我" 不动）。"""
    for text in (
        "帮我记 守岸人 提醒我",
        "今天天气不错，守岸人",
        "大家晚上好，我的蒙娜丽莎，在吗？",
        "帮我问问呼叫守岸人有没有回",
    ):
        assert strip_leading_name_mention(text, TERMS) == text, text


def test_non_mention_text_returned_byte_identical() -> None:
    """未命中一律**原样返回**：归一化只发生在真剥掉称呼时，
    否则 `/bot help` 的斜杠会被 normalize_mention_text 白吃掉。"""
    for text in (
        "/bot help",
        "/亲密模式 开",  # 斜杠命令本体，没有任何称呼 ⇒ 一字不动
        "!important 看这里",
        "守岸人设真不错",  # 包含词不是称呼（现状边界语义保持）
        "岸宝贝真可爱",
    ):
        assert strip_leading_name_mention(text, TERMS) == text, text


def test_longest_term_wins_prefix_hazard() -> None:
    """长 term 优先：短词先试会把长称呼切成半截（"我" 吃掉 "我的蒙娜丽莎"）。

    本锁的 term 对是**合成**的（现行人格表内不存在互为前缀的两枚），
    目的只有一个：杀掉"不排序/按长度升序"这一毒形。
    """
    terms = ("我", "我的蒙娜丽莎")
    assert strip_leading_name_mention("我的蒙娜丽莎，亲密模式 开", terms) == "亲密模式 开"
    # 真实表内前缀不冲突，长称呼整段剥（反向核对，防"只认最短"）。
    assert strip_leading_name_mention("独属于我的蒙娜丽莎，在吗", TERMS) == "在吗"


def test_garbage_inputs_never_raise_and_return_asis() -> None:
    """空 terms / None terms / 纯空白文本 / None 文本：原样返回，绝不抛。"""
    assert strip_leading_name_mention("守岸人，亲密模式 开", []) == "守岸人，亲密模式 开"
    assert strip_leading_name_mention("守岸人，亲密模式 开", ()) == "守岸人，亲密模式 开"
    assert strip_leading_name_mention("守岸人，亲密模式 开", None) == "守岸人，亲密模式 开"
    assert strip_leading_name_mention("守岸人", ["", "  ", "\t"]) == "守岸人"
    assert strip_leading_name_mention("", TERMS) == ""
    assert strip_leading_name_mention("   ", TERMS) == "   "
    assert strip_leading_name_mention("\n\t ", TERMS) == "\n\t "
    assert strip_leading_name_mention(None, TERMS) == ""  # type: ignore[arg-type]
    assert strip_leading_name_mention("守岸人 在吗", [None, "守岸人"]) == "在吗"  # type: ignore[list-item]


def test_only_one_leading_address_is_stripped() -> None:
    """多连称呼只剥最前面一处（本件语义＝"开头那一处"，不做 eat.py 那种多连循环）。"""
    assert strip_leading_name_mention("@守岸人 @岸宝 亲密模式 开", TERMS) == "@岸宝 亲密模式 开"
    # 连着写、中间没有边界字符时根本不算称呼（与 detect_name_mention 现状同判）。
    assert strip_leading_name_mention("守岸人岸宝 亲密模式 开", TERMS) == "守岸人岸宝 亲密模式 开"


def test_tail_cleanup_goes_through_central_piece() -> None:
    """取值收编：尾巴清洗必须走中央 `strip_boundary` + 权威分隔符集。

    两条腿缺一不可：① 清洗段确实是中央件（AST 里真调了 `strip_boundary`，
    本模块没有 `_MENTION_STRIP_CHARS` 之类的第二份手抄字符集）；② 判定段仍是
    既有那份"核心段 ∪ 中央 ADDRESS 登记"——两处判据若被合并成一套，行为就错。
    """
    assert mentions.strip_boundary is text_boundary.strip_boundary
    fn = next(
        node
        for node in ast.walk(ast.parse(_source(mentions.__file__)))
        if isinstance(node, ast.FunctionDef) and node.name == "strip_leading_name_mention"
    )
    called = {
        node.func.id
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "strip_boundary" in called, f"清洗段没走中央件：{sorted(called)}"
    assert "lstrip" not in called and "sub" not in called
    # 判定集与清洗集必须是**不同**的两套取值（本模块判定集含虚词/请求词首字）。
    assert "TRIGGER_BOUNDARY_CHARS" in {
        node.id for node in ast.walk(fn) if isinstance(node, ast.Name)
    }
    assert not hasattr(mentions, "_MENTION_STRIP_CHARS"), "又长出一份手抄清洗集"


def test_never_strips_what_the_detector_does_not_recognize() -> None:
    """一致性单向锁：本件剥过（≠原串）的输入，检测器必须也认为被点名了。

    反向不成立是设计语义：`detect_name_mention` 还认句中称呼，而那些不该被剥。
    """
    samples = (
        "@守岸人 亲密模式 开",
        "守岸人，亲密模式 开",
        "呼叫守岸人 亲密模式 开",
        "岸宝 帮我",
        "守岸人",
        "守岸人设真不错",
        "帮我记 守岸人 提醒我",
        "/bot help",
        "今天天气不错，守岸人",
    )
    for text in samples:
        stripped = strip_leading_name_mention(text, TERMS)
        if stripped != text:
            assert detect_name_mention(text, TERMS) is True, text


# ---------------------------------------------------------------- ② 活性锁：命令真被救活


def test_intimate_command_is_revived_after_stripping() -> None:
    """承重锁：剥前缀 + 既有 L4 判据 = 群内「@守岸人 亲密模式 开」真的命中。

    前半段钉住"这条今天确实是死的"（回归哨兵），后半段钉住"接上就活了"。
    `_MANUAL_ON_RE` 的返回值（现值 "intimate"）若被主代理改签名，本锁只认
    "剥出来的文本能被同一个判据认成同一种结果"，不锁字面量。
    """
    raw = "@守岸人 亲密模式 开"
    assert match_manual_command(raw) is None, "缺陷本体：带点名的原文今天不命中"
    stripped = strip_leading_name_mention(raw, TERMS)
    assert stripped == "亲密模式 开"
    verdict = match_manual_command(stripped)
    assert verdict is not None, "剥完仍不命中 = 这条链没接上"
    assert verdict == match_manual_command("亲密模式 开")


def test_off_command_is_revived_after_stripping() -> None:
    """关闭侧同权（同一入口的两个方向都要活）。"""
    assert match_manual_command("@守岸人 亲密模式 关") is None
    assert (
        match_manual_command(strip_leading_name_mention("@守岸人 亲密模式 关", TERMS))
        == match_manual_command("亲密模式 关")
    )
    assert (
        match_manual_command(strip_leading_name_mention("呼叫岸宝，开启亲密模式", TERMS))
        == match_manual_command("开启亲密模式")
    )


# ---------------------------------------------------------------- ③ 契约字段


def _message(**overrides: object) -> IncomingMessage:
    base: dict[str, object] = {
        "platform": "qq",
        "adapter": "nonebot",
        "bot_id": "10001",
        "session_id": "group_20002_30003",
        "session_type": SessionType.GROUP,
        "sender_id": "30003",
    }
    base.update(overrides)
    return IncomingMessage(**base)  # type: ignore[arg-type]


def test_command_text_defaults_to_empty_and_is_safe() -> None:
    """缺省空串：老构造点（smoke/admin/campus 等十余处）零改动也不炸。"""
    assert _message(plain_text="亲密模式 开").command_text == ""


def test_command_text_never_overrides_plain_text() -> None:
    """派生只读：两个字段各是各的，填了 command_text 也不动 plain_text。"""
    message = _message(plain_text="@守岸人 亲密模式 开", command_text="亲密模式 开")
    assert message.plain_text == "@守岸人 亲密模式 开"
    assert message.command_text == "亲密模式 开"


def test_command_text_is_a_declared_str_field() -> None:
    """字段在册且类型是 str（不是 Optional，免得下游到处补 None）。"""
    field = IncomingMessage.model_fields["command_text"]
    assert field.annotation is str
    assert field.get_default() == ""


# ---------------------------------------------------------- ④ 摄取端到端（跑真身）


class _FakeGroupEvent:
    """QQ 群事件最小形态（照 tests/test_b07_sender_level_ingest.py 的先例）。"""

    __module__ = "nonebot.adapters.onebot.v11.event"

    def __init__(self, text: str) -> None:
        self._text = text
        self.group_id = "999"
        self.message_id = "70001"
        self.sender = SimpleNamespace(card="", nickname="路人", role="member", level="1")

    def get_plaintext(self) -> str:
        return self._text

    def get_session_id(self) -> str:
        return "group_999_u1"

    def get_user_id(self) -> str:
        return "u1"

    def is_tome(self) -> bool:
        return False


def _ingest(text: str, *, chain: list[ReplyChainItem] | None = None) -> IncomingMessage:
    """跑根文件真身摄取函数（不是仿一个算一遍）。"""
    segments = [{"type": "text", "data": {"text": text}}]
    return _incoming_from_nonebot_event(
        _FakeGroupEvent(text),
        bot_id="bot-1",
        segments=segments,
        reply_chain=chain if chain is not None else [],
    )


def test_ingestion_end_to_end_fills_command_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """端到端：真经摄取函数的消息，command_text 就是剥掉开头称呼的那半句。

    同时钉住两件事：`plain_text` 保持原文（本席严禁改它），点名判定族
    （mentions_bot / 人格名软点名）不因根侧改走 `mentions.` 属性形态而退化。
    """
    monkeypatch.setattr(runtime, "_RUNTIME_MENTION_TERMS", list(TERMS))
    monkeypatch.setattr(runtime, "_AFFINITY_NICKNAMES_CACHE", None)

    hit = _ingest("@守岸人 亲密模式 开")
    assert hit.command_text == "亲密模式 开"
    assert hit.plain_text == "@守岸人 亲密模式 开"
    assert hit.mentions_bot is True, "手打 @ 仍须算硬点名（改走模块属性后不许退化）"

    soft = _ingest("守岸人 今天天气怎么样")
    assert soft.command_text == "今天天气怎么样"
    assert soft.mentions_bot is True, "人格名软点名链路保持"

    mid = _ingest("帮我记 守岸人 提醒我")
    assert mid.command_text == "帮我记 守岸人 提醒我"
    assert mid.plain_text == mid.command_text


def test_ingestion_with_quoted_chain_strips_only_own_leading_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """带引用链时同样只认用户自己那句的开头称呼（引用块拼在后面，不改头部）。"""
    monkeypatch.setattr(runtime, "_RUNTIME_MENTION_TERMS", list(TERMS))
    monkeypatch.setattr(runtime, "_AFFINITY_NICKNAMES_CACHE", None)
    chain = [ReplyChainItem(layer=1, message_id="", sender_id="other", text="上一条的内容")]
    incoming = _ingest("岸宝，亲密模式 开", chain=chain)
    assert incoming.command_text == "亲密模式 开"
    assert incoming.plain_text.startswith("岸宝，亲密模式 开")
    assert "上一条的内容" in incoming.plain_text


def test_ingestion_without_terms_leaves_plain_text_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """昵称表为空（生产未配 BOT_PERSONA_NICKNAMES 的极端形态）：零行为变化。"""
    monkeypatch.setattr(runtime, "_RUNTIME_MENTION_TERMS", [])
    monkeypatch.setattr(runtime, "_AFFINITY_NICKNAMES_CACHE", None)
    incoming = _ingest("@守岸人 亲密模式 开")
    assert incoming.command_text == "@守岸人 亲密模式 开"
    assert incoming.plain_text == "@守岸人 亲密模式 开"


# ---------------------------------------------------------------- ④ 摄取层活性锁（AST）


def _root_tree() -> ast.Module:
    return ast.parse((PLUGIN_ROOT / "__init__.py").read_text(encoding="utf-8"))


def _incoming_message_calls(tree: ast.AST) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "IncomingMessage"
    ]


def _ingestion_call() -> ast.Call:
    """根文件摄取函数 `_incoming_from_nonebot_event` 里的那一处构造。

    按函数名定位，不按 ast.walk 的先后顺序猜——同文件另有两处内置构造点，
    靠"第一个带 command_text 的"这种排序假设会测到错的那一处。
    """
    tree = _root_tree()
    fn = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_incoming_from_nonebot_event"
        ),
        None,
    )
    assert fn is not None, "摄取函数改名/消失了，本锁要跟着核对"
    calls = _incoming_message_calls(fn)
    assert len(calls) == 1, f"摄取函数内应恰一处构造，现={len(calls)}"
    return calls[0]


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((kw.value for kw in call.keywords if kw.arg == name), None)


def _strip_call_value(node: ast.Call) -> ast.expr | None:
    """取 command_text=... 的值节点（要求它确实是中央件的调用）。"""
    value = _keyword(node, "command_text")
    if not isinstance(value, ast.Call):
        return None
    func = value.func
    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
    return value if name == "strip_leading_name_mention" else None


def test_root_reaches_the_function_through_the_central_module() -> None:
    """摄取层必须用中央件：根文件 `import mentions` 并 `mentions.strip_leading_name_mention`。

    （具名 import 两个函数会让该行超 88 列、被 ruff I001 判成要拆行＝插行顶漂
    全册坐标门，故根侧走模块属性形态。这里锁的是"确实走中央件"，不是行写法。）
    """
    tree = _root_tree()
    source = _source(PLUGIN_ROOT / "__init__.py")
    imported_modules = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    uses_central = "mentions" in imported_modules or "strip_leading_name_mention" in imported_modules
    assert uses_central, "根文件没有引入 mentions 中央件"
    assert "def strip_leading_name_mention" not in source, "根文件里长出第二真身了"
    assert "strip_mentions" not in source, "根文件不许改用 eat.py 那份局部副本"


def test_every_root_construction_fills_command_text() -> None:
    """根 `__init__.py` 的三处 `IncomingMessage(...)` 全部填 command_text。

    少了任何一处 ⇒ 那条路的指令文本永远是空串，字段就成了"在册但没接线"。
    """
    calls = _incoming_message_calls(_root_tree())
    assert len(calls) == 3, f"根构造点数量变了，请核对本锁：{len(calls)}"
    for call in calls:
        args = {keyword.arg for keyword in call.keywords}
        assert "command_text" in args, f"第 {call.lineno} 行没填 command_text"


def test_ingestion_strips_the_pre_quote_text_not_the_concatenated_one() -> None:
    """判定必须落在 `own_text`（引用拼接**之前**）上，昵称来源是 `_RUNTIME_MENTION_TERMS`。

    同文件既有教训：引用内容里出现的 "@某人" 不算用户点名（旧代码把检测放在
    拼接之后，注释声明的语义并未成立，评审 L1）。此处若写成 `text` 就是重犯。
    """
    value = _strip_call_value(_ingestion_call())
    assert value is not None, "command_text 不是中央件的调用结果"
    positional = [ast.unparse(item) for item in value.args]
    assert positional[0] == "own_text", f"用的是拼接后的文本？{positional}"
    assert "_RUNTIME_MENTION_TERMS" in positional[1]
    # plain_text 那条腿必须还是拼接后的 text（本席严禁改它的构造结果）。
    plain = _keyword(_ingestion_call(), "plain_text")
    assert isinstance(plain, ast.Name) and plain.id == "text"


def test_command_text_consumers_fall_back_when_absent() -> None:
    """语义哨兵：默认空串 + `or plain_text` 回退 = 未接线消费方零破坏。

    本席**没有**改动 `chat.py` 的 L4 读取口径（那会动既有锁），因此这里只钉住
    "空串可安全回退"这条契约事实，供下一步接线引用。
    """
    message = _message(plain_text="@守岸人 亲密模式 开")
    effective = message.command_text or message.plain_text
    assert effective == "@守岸人 亲密模式 开"
    filled = _message(
        plain_text="@守岸人 亲密模式 开",
        command_text=strip_leading_name_mention("@守岸人 亲密模式 开", TERMS),
    )
    assert (filled.command_text or filled.plain_text) == "亲密模式 开"
    assert filled.plain_text == "@守岸人 亲密模式 开"
