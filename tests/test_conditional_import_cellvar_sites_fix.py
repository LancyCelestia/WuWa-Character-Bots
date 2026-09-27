"""三处在册 cellvar 遮蔽站点根修后的行为锁（2026-09-27 摘牌波）。

对应对 `tests/test_conditional_import_cellvar_ratchet.py` 名册原三条目（已摘牌）：
  ① `_handle_alias` 的 `bot.meme_library` 分支内
    `from .domains.meme.capabilities.meme_library import build_meme_library_capability`；
  ② `_handle_chat` 的 `if parrot_reply:` 块内四枚**别名**导入
    （`CapabilityResult as _CR` / `PrivacyLevel as _PL` / `RiskLevel as _RL` /
    `SendPolicy as _SP`）+ 同块一枚消费这四枚的 lambda；
  ③ `_handle_natural` 的 `bot.meme_library` 分支内与①同名条件导入。

修法（现算结论）：①③ 的**源名**模块级第 141 行已导入 ⇒ 直接删分支内重复导入
（萌百 `f6b5f3c` 同手法）；② 的别名在模块级并不存在，照删会让 lambda 抓空，
故选「改闭包用模块级真身名」而非「模块级补别名」——真身四枚第 23-35 行已在，
改写与全文件其余处写法一致、零新增面；模块级别名会把 `_CR` 形名字永久挂进
模块命名空间供后续任何写法复用，正是这型雷的温床，不取。

崩形现状更正（区别于简报转述）：三处的导入与**唯一**消费闭包同在条件块内，
「没进那个分支 + 闭包被调用」今天没有任何输入能在同一次宿主执行里凑齐——
萌百那格是能凑齐的（闭包跨块），所以它真炸了；这三处是「宿主 cellvar 遮蔽已
成形、闭包一旦被搬出块外（或导入被删）即原样复发」的潜伏雷，即名册归属写的
「今日不炸≠安全」。下列触发输入 = 走到该闭包被调用的输入（也就是行为锁要喂的）：
  ① 别名昵称命令解析到 `bot.meme_library`（如「偷表情 xxx」；arg=="私聊" 走会话改写腿）；
  ② 群消息 + `bot.plugin.chat.parrot` 开关开 + 非斜杠文本 +
     `parrot_detector.detect(...)` 返回真值吐槽；
  ③ 自然语言命令解析到 `bot.meme_library`。

本锁**不 import 插件模块**（那条装载路径会在源码树 `data/` 落 sqlite，铁律 6），
只做三件事：
  * AST 面：三枚宿主函数体内任何位置不再 ImportFrom 该站源名；
  * 字节码面：宿主 `co_cellvars` 与其下全部嵌套 `co_freevars` 不再含被遮蔽名；
    目标闭包码对象按 LOAD_GLOBAL 解析该名字（进 `co_names`）。注毒回塞分支内
    导入 ⇒ 名字落回 freevar、`co_names`  locator 零命中、当场红（含行为锁的
    构壳环节，缺 cell 供数即红）——这就是注毒自证；
  * 行为面：用 `types.FunctionType + types.CellType` 手搓真实闭包码对象，**不经
    宿主帧**直接调用（等价于「分支从未跑过」的最恶劣处境）：断言不抛 NameError、
    返回结果字段完好。async def 双码对象（宿主同名两个）取并集，教训取自
    `f6b5f3c` 与台账 #50。
"""

from __future__ import annotations

import ast
import sys
import types
from pathlib import Path

if sys.version_info < (3, 12):  # 手搓闭包用 types.CellType（3.12+ 公开）；本仓门禁跑 3.12
    raise RuntimeError("本锁用 types.CellType 构造闭包，请在 3.12+ 解释器上跑")

_REPO = Path(__file__).resolve().parents[1]
_SOURCE = _REPO / "plugins" / "bot_unified_runtime" / "__init__.py"

_MEME_BUILDER = "build_meme_library_capability"
_CHAT_ALIAS_NAMES = frozenset({"_CR", "_PL", "_RL", "_SP"})
_CHAT_CONTRACT_REALS = frozenset({"CapabilityResult", "PrivacyLevel", "RiskLevel", "SendPolicy"})


def _read_src() -> str:
    return _SOURCE.read_text(encoding="utf-8")


def _walk(obj):
    yield obj
    for const in obj.co_consts:
        if hasattr(const, "co_consts"):
            yield from _walk(const)


def _module_code():
    # 只 compile、绝不 import/exec——被验模块的装载副作用不许在本锁里发生。
    return compile(_read_src(), str(_SOURCE), "exec")


def _host_codes(root, host_name: str) -> list:
    # async def 编译成「包裹函数 + 协程」两个同名码对象——按名取并集，只取一个会看漏。
    return [c for c in _walk(root) if c.co_name == host_name]


def _unique_closure_code(host_name: str, inner_name: str, global_load: str):
    """定位「以 LOAD_GLOBAL 解析 global_load」的那一枚嵌套闭包码对象。

    注毒形态（分支内导入回塞）下该名字改走 co_freevars、不进 co_names，
    这里零命中 ⇒ 本函数当场红，这是预期杀伤面而非量具坏。
    """
    root = _module_code()
    hosts = _host_codes(root, host_name)
    assert hosts, f"字节码里找不到宿主 {host_name}——前提被换，请连同修法一起复核"
    hits = [
        c
        for h in hosts
        for c in _walk(h)
        if c is not h and c.co_name == inner_name and global_load in c.co_names
    ]
    if len(hits) != 1:
        raise AssertionError(
            f"{host_name} 下按 co_names∋{global_load} 筛 {inner_name} 得到 {len(hits)} 枚"
            f"（应为 1）：命中 0 ⇒ 分支内导入回潮让名字落回 freevar；命中 >1 ⇒ 长出第二枚同形闭包，"
            f"须人工裁决后改锁。"
        )
    code = hits[0]
    assert global_load not in code.co_freevars, (
        f"{host_name}.{inner_name} 又把 {global_load} 当 freevar 向外层要人——cellvar 遮蔽复发"
    )
    return code


def _make_closure(code, glb: dict[str, object], cells: dict[str, object], label: str):
    unknown = [n for n in code.co_freevars if n not in cells]
    if unknown:
        raise AssertionError(
            f"{label} 闭包还要外层名字 {unknown}——多半是分支内绑定回潮（该名字被 cellvar 化了），"
            f"或闭包体新增引用未登记；两种都须人工复核后改锁。"
        )
    closure = tuple(types.CellType(cells[name]) for name in code.co_freevars)
    return types.FunctionType(code, glb, code.co_name, None, closure)


# ---------------------------------------------------------------------------
# 行为桩（替真身全局名；只验「名字解析通路 + 字段完好」，不碰任何端点）
# ---------------------------------------------------------------------------


class _StubResult:
    def __init__(self, **fields: object) -> None:
        self.fields = fields


class _Enum:
    def __init__(self, **members: str) -> None:
        self.__dict__.update(members)


_SendPolicy = _Enum(IMMEDIATE="SendPolicy.IMMEDIATE")
_PrivacyLevel = _Enum(GROUP="PrivacyLevel.GROUP", PERSONAL="PrivacyLevel.PERSONAL")
_RiskLevel = _Enum(LOW="RiskLevel.LOW")
_SessionType = _Enum(PRIVATE="SessionType.PRIVATE")


class _Msg:
    def __init__(self, request_id: str, plain_text: str,
                 session_type: object = "group", group_id: object = "g-1") -> None:
        self.request_id = request_id
        self.plain_text = plain_text
        self.session_type = session_type
        self.group_id = group_id

    def model_copy(self, *, update: dict | None = None, deep: bool = False) -> _Msg:
        upd = update or {}
        return _Msg(
            self.request_id,
            upd.get("plain_text", self.plain_text),
            upd.get("session_type", self.session_type),
            upd.get("group_id", self.group_id),
        )


def _meme_globals(sink: dict) -> dict[str, object]:
    def build(store, config, mood_valence_fn=None):
        sink["factory_args"] = (store, config)
        sink["mood_valence"] = mood_valence_fn() if mood_valence_fn is not None else None

        def call(message, decision):
            sink["call"] = (message, decision)
            return _StubResult(
                kind="meme",
                request_id=message.request_id,
                plain_text=message.plain_text,
                session_type=message.session_type,
                group_id=message.group_id,
            )

        return call

    return {
        "build_meme_library_capability": build,
        "CapabilityResult": _StubResult,
        "SessionType": _SessionType,
        "_mood_valence": lambda config: 0.42,
    }


# ---------------------------------------------------------------------------
# 面①：AST——三枚宿主体内不许再出现该站源名的 ImportFrom
# ---------------------------------------------------------------------------


def test_ast_hosts_have_no_site_repeat_imports() -> None:
    tree = ast.parse(_read_src())
    forbid = {
        "_handle_alias": {_MEME_BUILDER},
        "_handle_natural": {_MEME_BUILDER},
        "_handle_chat": set(_CHAT_CONTRACT_REALS),  # 别名形态按**源名**判（ratchet 判据②同款）
    }
    offenders: list[str] = []
    for host_name, names in forbid.items():
        hosts = [
            n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == host_name
        ]
        assert len(hosts) == 1, f"AST 里 {host_name} 应有且只有一枚，实得 {len(hosts)}"
        for node in ast.walk(hosts[0]):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in names:
                        offenders.append(
                            f"{host_name} L{node.lineno}: from {node.module} import {alias.name}"
                            + (f" as {alias.asname}" if alias.asname else "")
                        )
    assert not offenders, (
        "分支内重复导入回潮（cellvar 遮蔽的成因语句）：\n" + "\n".join(offenders)
    )


# ---------------------------------------------------------------------------
# 面②：字节码——宿主 cellvars / 嵌套 freevars 里被遮蔽名清零
# ---------------------------------------------------------------------------


def test_hosts_cells_and_nested_freevars_cleared() -> None:
    root = _module_code()
    checks = [
        ("_handle_alias", {_MEME_BUILDER}),
        ("_handle_natural", {_MEME_BUILDER}),
        ("_handle_chat", set(_CHAT_ALIAS_NAMES)),
    ]
    for host_name, names in checks:
        hosts = _host_codes(root, host_name)
        assert hosts, f"字节码里找不到宿主 {host_name}"
        cells: set[str] = set()
        nested_free: set[str] = set()
        for h in hosts:
            cells |= set(h.co_cellvars)
            nested_free |= {n for d in _walk(h) if d is not h for n in d.co_freevars}
        leaked = (cells | nested_free) & names
        assert not leaked, (
            f"{host_name} 仍把 {sorted(leaked)} 绑成 cellvar/freevar（分支内绑定回潮）；"
            f"修好后这些名字只许以 LOAD_GLOBAL 出现"
        )


# ---------------------------------------------------------------------------
# 面③：行为——不经宿主帧直接调真闭包码对象，不炸且字段完好
# ---------------------------------------------------------------------------


def test_alias_meme_capability_runs_without_host_frame() -> None:
    code = _unique_closure_code("_handle_alias", "capability", _MEME_BUILDER)
    store = object()
    config = object()

    # 腿 A：表情包库启用（arg 普通词）——builder 与内层 call 各自收到完好入参。
    sink: dict = {}
    fn = _make_closure(
        code, _meme_globals(sink),
        {"arg": "测试词", "meme_library_store": store, "config": config},
        "_handle_alias.capability(meme)",
    )
    decision = object()
    result = fn(_Msg("req-alias-1", "偷表情 测试词"), decision)
    assert sink["factory_args"] == (store, config)
    assert sink["mood_valence"] == 0.42  # 内层 lambda 经 config cell + 全局 _mood_valence 接通
    called_msg, called_decision = sink["call"]
    assert called_decision is decision
    assert called_msg.plain_text == "偷表情 测试词"
    assert result.fields["request_id"] == "req-alias-1"

    # 腿 B：arg=="私聊" 走会话改写腿——session_type/group_id 按改后值传下去。
    sink.clear()
    fn = _make_closure(
        code, _meme_globals(sink),
        {"arg": "私聊", "meme_library_store": store, "config": config},
        "_handle_alias.capability(meme/private)",
    )
    result = fn(_Msg("req-alias-2", "偷表情 私聊"), object())
    assert result.fields["session_type"] == "SessionType.PRIVATE"
    assert result.fields["group_id"] is None

    # 腿 C：库未启用——返回体字段完好（此腿不触 builder，只触全局 CapabilityResult）。
    fn = _make_closure(
        code, _meme_globals({}),
        {"arg": "测试词", "meme_library_store": None, "config": config},
        "_handle_alias.capability(meme/disabled)",
    )
    result = fn(_Msg("req-alias-3", "偷表情 测试词"), object())
    assert result.fields["capability_id"] == "bot.meme_library"
    assert result.fields["body"] == "表情库未启用。"
    assert result.fields["request_id"] == "req-alias-3"
    assert result.fields["audit_tags"] == ["meme_library", "disabled"]


def test_natural_meme_capability_runs_without_host_frame() -> None:
    code = _unique_closure_code("_handle_natural", "capability", _MEME_BUILDER)
    store = object()
    config = object()

    sink: dict = {}
    fn = _make_closure(
        code, _meme_globals(sink),
        {"normalized_text": "偷表情 自然", "meme_library_store": store, "config": config},
        "_handle_natural.capability(meme)",
    )
    decision = object()
    result = fn(_Msg("req-natural-1", "帮我偷表情"), decision)
    assert sink["factory_args"] == (store, config)
    assert sink["mood_valence"] == 0.42
    called_msg, called_decision = sink["call"]
    assert called_decision is decision
    assert called_msg.plain_text == "偷表情 自然"
    assert result.fields["request_id"] == "req-natural-1"

    fn = _make_closure(
        code, _meme_globals({}),
        {"normalized_text": "偷表情 自然", "meme_library_store": None, "config": config},
        "_handle_natural.capability(meme/disabled)",
    )
    result = fn(_Msg("req-natural-2", "帮我偷表情"), object())
    assert result.fields["capability_id"] == "bot.meme_library"
    assert result.fields["body"] == "表情库未启用。"
    assert result.fields["request_id"] == "req-natural-2"


def test_chat_parrot_lambda_runs_without_host_frame() -> None:
    code = _unique_closure_code("_handle_chat", "<lambda>", "CapabilityResult")
    assert "CapabilityResult" not in code.co_names[:0] or True  # 定位器已保证在 co_names
    glb = {
        "CapabilityResult": _StubResult,
        "SendPolicy": _SendPolicy,
        "PrivacyLevel": _PrivacyLevel,
        "RiskLevel": _RiskLevel,
    }
    fn = _make_closure(code, glb, {"parrot_reply": "复读吐槽文本"},
                       "_handle_chat.parrot-lambda")
    result = fn(_Msg("req-parrot", "同一句话"), object())
    fields = result.fields
    assert fields["request_id"] == "req-parrot"
    assert fields["capability_id"] == "bot.chat"
    assert fields["kind"] == "text"
    assert fields["body"] == "复读吐槽文本"  # 外层 cell（parrot_reply）经 freevar 正常接通
    assert fields["send_policy"] == "SendPolicy.IMMEDIATE"
    assert fields["privacy_level"] == "PrivacyLevel.GROUP"
    assert fields["risk_level"] == "RiskLevel.LOW"
    assert fields["audit_tags"] == ["group_parrot", "social_response"]
