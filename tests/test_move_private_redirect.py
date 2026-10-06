"""隐私转私聊通路（`ReviewAction.MOVE_PRIVATE` 的**第一个消费者**，缺省关）。

病根（台账 #77、`docs/HANDBOOK.md`「回执与队列」⑦、`docs/design/
audit-20260920-unify-summary.md` U15-10）：`domains/render/reviewer.py` 的隐私那一腿
（`result.privacy_level ∈ {PERSONAL, CREDENTIALED}` 且作用域是群）把动作置成
`ReviewAction.MOVE_PRIVATE`，但**全仓零消费者**——`pipeline._complete` 只看
`review.approved`，于是它与 `BLOCK` 走同一支（`ReceiptState.BLOCKED` + 一句与人格无关
的机器文案），契约里那枚「转私聊」名不副实，`ReceiptState.REDIRECTED` 也一直
「有消费者、无生产者」。

用户 2026-10-06 的裁定＝**建通路、不启用**：「转私聊功能：暂时好像没什么太大的需求。
我需要你先把它建立起来，但并不代表我现在就需要它真正启用。」⇒ 新键
`BOT_REVIEW_MOVE_PRIVATE_ENABLED` 缺省 `False`，关着时行为与今天**逐字节相同**。

本文件钉的八节判据（全离线，零网络，零平台调用，零落盘）：

① 声明面三面齐（`config.py` 字段 / `runtime/settings.py` 热改名单 / `.env.example`
   激活行；缺一必红，先例 `tests/test_message_mutation_config_faces_s34b.py`）＋缺省 False。
② 开关是唯一承重的：工厂在键关/键缺席时一律返回 `None`（⇒ pipeline 那一支不可达）。
③ 接线形态（AST 锁）：pipeline 调用点必被 `is not None` 罩住、协作者缺省值必为 `None`、
   根装配把工厂产物交进 `RuntimePipeline`、新键全树只一处读点。
④ **缺省关＝零行为变化**：隐私级 PERSONAL + 群作用域走真管线 ⇒ `ReceiptState.BLOCKED`
   且发送队列**一条新请求都没有**（这枚就是「不擅自启用」的牙）。
⑤ 开时确实转投：中央出口收到**恰一条** `target_scope=PRIVATE`、收件人＝请求者本人的
   请求；群侧零投递；正文＝原本要发的那一份（零新增文案）；审计行零正文。
⑥ 键形只有一处构造：私聊会话键只由 `domains/core/session_keys.private_session_key`
   产出，生产件里不许手拼 `private_…` / `private:…`（#33/#29 同根病类）。注毒＝改自拼必红。
⑦ 归属只给本人：转投目标恰请求者一枚，不广播给群里其他成员。
⑧ 判据不越界：只有 `MOVE_PRIVATE` 才转；`BLOCK` 一律照旧整条拦（开了开关也不许多出
   一条私聊泄露腿）。

投递只走既有中央出口 `submit_active_push`（闸关=与裸 `submit` 逐字节同形的 passthrough），
本波**不新建第二条 send 通路**。
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    PrivacyLevel,
    ReceiptState,
    ReviewAction,
    ReviewResult,
    RiskLevel,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.pipeline import (
    RuntimePipeline,
)
from plugins.bot_unified_runtime.domains.core import session_keys
from plugins.bot_unified_runtime.domains.core.contracts.runtime import IncomingMessage
from plugins.bot_unified_runtime.domains.render.renderer import render_reviewed_output
from plugins.bot_unified_runtime.domains.render.reviewer import review_capability_result
from plugins.bot_unified_runtime.domains.transport.sender import InMemorySendQueue
from plugins.bot_unified_runtime.domains.transport.sender import outbound_gate as og

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PY = ROOT / "plugins/bot_unified_runtime/config.py"
SETTINGS_PY = ROOT / "plugins/bot_unified_runtime/domains/chat_reply/runtime/settings.py"
ENV_EXAMPLE = ROOT / ".env.example"
OUTBOUND_GATE_PY = (
    ROOT / "plugins/bot_unified_runtime/domains/transport/sender/outbound_gate.py"
)
PIPELINE_PY = ROOT / "plugins/bot_unified_runtime/domains/chat_reply/runtime/pipeline.py"
ROOT_INIT_PY = ROOT / "plugins/bot_unified_runtime/__init__.py"
PLUGINS_ROOT = ROOT / "plugins"

NEW_FIELD = "bot_review_move_private_enabled"
NEW_ENV_KEY = "BOT_REVIEW_MOVE_PRIVATE_ENABLED"
CENTRAL_SESSION_KEYS_MODULE = "plugins.bot_unified_runtime.domains.core.session_keys"
CENTRAL_PRIVATE_CTOR = "private_session_key"
HOOK_PARAM = "review_move_private_redirect"

_GROUP_ID = "1108838060"
_SENDER_ID = "3865067623"
_OTHER_MEMBER_ID = "631785829"
_REQUEST_ID = "req-move-private-1"

# 一条**清白**正文（不命中 reviewer 任何词面），只是隐私级偏高——那正是 MOVE_PRIVATE
# 那一格的形状：内容没问题，只是不该出现在群里。
_BODY = "你托我记的那笔体检安排在明天下午三点，医院名字我先收着，只说给你一个人。"


# ---------------------------------------------------------------------------
# 夹具：会话键只经中央件产出（测试也不手写键形，否则判据与夹具各说各话）
# ---------------------------------------------------------------------------
def _group_message(sender_id: str = _SENDER_ID) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id=session_keys.build_session_key(_GROUP_ID, sender_id),
        session_type=SessionType.GROUP,
        sender_id=sender_id,
        group_id=_GROUP_ID,
        plain_text="帮我看看明天的安排",
        mentions_bot=True,
        message_id="m-move-private-1",
    )


def _result(**overrides: Any) -> CapabilityResult:
    base: dict[str, Any] = {
        "request_id": _REQUEST_ID,
        "capability_id": "bot.chat",
        "kind": "text",
        "title": "守岸人的回复",
        "body": _BODY,
        "privacy_level": PrivacyLevel.PERSONAL,
    }
    base.update(overrides)
    return CapabilityResult(**base)


def _decision(scope: SessionType = SessionType.GROUP) -> BotDecision:
    return BotDecision(
        request_id=_REQUEST_ID,
        should_respond=True,
        mode="chat",
        trigger="mention",
        capability_id="bot.chat",
        target_scope=scope,
        decision_reason="test",
    )


def _review(result: CapabilityResult) -> ReviewResult:
    return review_capability_result(result, _decision(SessionType.GROUP))


class _RecordingAudit:
    def __init__(self) -> None:
        self.rows: list[Any] = []

    def append(self, record: Any) -> None:
        self.rows.append(record)

    def review_rows(self) -> list[Any]:
        return [row for row in self.rows if getattr(row, "stage", "") == "review"]


def _gate() -> og.OutboundGate:
    """真闸：七枚键全缺 ⇒ `enabled=False` ⇒ 中央出口＝与裸 submit 同形的 passthrough。"""
    return og.build_outbound_gate(SimpleNamespace())


def _redirector(config: Any, queue: InMemorySendQueue, audit: _RecordingAudit) -> Any:
    builder = getattr(og, "build_move_private_redirector", None)
    assert builder is not None, (
        f"功能不存在：{OUTBOUND_GATE_PY.name} 里没有 build_move_private_redirector"
    )
    return builder(config, send_queue=queue, gate=_gate(), audit_logger=audit)


def _drive(
    result: CapabilityResult,
    *,
    message: IncomingMessage | None = None,
    redirector: Any = None,
    queue: InMemorySendQueue | None = None,
    audit: _RecordingAudit | None = None,
) -> tuple[Any, _RecordingAudit, InMemorySendQueue]:
    """把 `result` 走一遍**真管线**（`handle_async` → `_complete` → review）。

    `redirector is None` 时**根本不传那枚关键字** ⇒ 吃的是协作者的缺省值，
    与「键关 ⇒ 装配拿到 None」同形（今日形态逐字节）。
    """
    audit = audit or _RecordingAudit()
    queue = queue or InMemorySendQueue(audit_logger=audit)
    kwargs: dict[str, Any] = {}
    if redirector is not None:
        kwargs[HOOK_PARAM] = redirector
    pipeline = RuntimePipeline(send_queue=queue, audit_logger=audit, **kwargs)

    async def _capability(*_args: Any) -> CapabilityResult:
        return result

    receipt = asyncio.run(
        pipeline.handle_async(message or _group_message(), _capability, "bot.chat")
    )
    return receipt, audit, queue


# ===========================================================================
# ① 声明面三面齐 + 缺省 False
# ===========================================================================
def _config_field_present(source: str) -> bool:
    return any(
        isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == NEW_FIELD
        for node in ast.walk(ast.parse(source))
    )


def _restart_registration_present(source: str) -> bool:
    """只在 `RESTART_REQUIRED_KEYS` 那张表**自身**的字面量里找（不看别处的提及）。"""
    return NEW_ENV_KEY in _restart_table_text(source)


def _restart_table_text(source: str) -> str:
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        if node.target.id != "RESTART_REQUIRED_KEYS" or node.value is None:
            continue
        return ast.unparse(node.value)
    return ""


def _env_example_line_present(source: str) -> bool:
    return any(
        line.strip().startswith(f"{NEW_ENV_KEY}=") for line in source.splitlines()
    )


def test_new_key_defaults_to_false_on_config_class() -> None:
    """字段在册**且缺省 False**（缺省 True＝本波一落地就把没裁的行为启用了）。"""
    assert NEW_FIELD in Config.model_fields, f"{NEW_FIELD} 没进 config.py 字段面"
    assert Config.model_fields[NEW_FIELD].annotation is bool, "该键必须是布尔总闸"
    assert Config.model_fields[NEW_FIELD].default is False
    assert getattr(Config(), NEW_FIELD) is False


def test_three_faces_are_all_registered() -> None:
    """三面齐（#68★ 幽灵字段）：字段 / RESTART 名单 / `.env.example` 激活行。"""
    assert _config_field_present(CONFIG_PY.read_text(encoding="utf-8")), "面①缺：config.py"
    assert _restart_registration_present(
        SETTINGS_PY.read_text(encoding="utf-8")
    ), (
        f"面②缺：{NEW_ENV_KEY} 未登记 RESTART_REQUIRED_KEYS。该键在装配 RuntimePipeline 时"
        "取一次、产物冻进协作者，按 C-09「死开关不许骗人」不许进 SETTABLE_KEYS"
    )
    env_text = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert _env_example_line_present(env_text), f"面③缺：.env.example 无激活行 {NEW_ENV_KEY}="
    active = next(
        line.strip()
        for line in env_text.splitlines()
        if line.strip().startswith(f"{NEW_ENV_KEY}=")
    )
    assert active.split("=", 1)[1].strip().lower() == "false", (
        f".env.example 模板那行必须写 false，现值＝{active}"
    )


def test_poison_missing_one_face_is_named() -> None:
    """注毒：三面各缺一次都必须被同一把尺点名（三面齐是判据，不是三选一）。"""
    assert _config_field_present(f"class Config:\n    {NEW_FIELD}: bool = False\n")
    assert not _config_field_present("class Config:\n    bot_other: bool = False\n")
    assert not _restart_registration_present(
        "RESTART_REQUIRED_KEYS: dict[str, str] = {\n    'BOT_UNRELATED': 'x',\n}\n"
    )
    assert not _env_example_line_present(f"# {NEW_ENV_KEY}=false\n"), "注释形态不算激活行"
    assert not _restart_table_text("SOME_OTHER: dict = {}\n")


# ===========================================================================
# ② 开关是唯一承重的
# ===========================================================================
def test_factory_returns_none_when_switch_is_off() -> None:
    queue = InMemorySendQueue(audit_logger=_RecordingAudit())
    for label, config in (
        ("键为 False", SimpleNamespace(**{NEW_FIELD: False})),
        ("键缺席（鸭子配置面）", SimpleNamespace()),
        ("缺省 Config()", Config()),
    ):
        assert _redirector(config, queue, _RecordingAudit()) is None, (
            f"{label} 时工厂必须返回 None——交出真产物＝本波擅自启用"
        )


def test_factory_returns_callable_only_when_switch_is_on() -> None:
    queue = InMemorySendQueue(audit_logger=_RecordingAudit())
    redirector = _redirector(
        SimpleNamespace(**{NEW_FIELD: True}), queue, _RecordingAudit()
    )
    assert callable(redirector), "键开时工厂必须交出可调用的转投协作者"


def test_read_point_of_the_new_key_is_solely_in_the_central_exit() -> None:
    """新键的读点**只许有一处**（住 `outbound_gate.py`）——禁第二读点（#49「在册未执法」、
    #68★ 三面齐同族：多一处读点就多一条「配置面看着开着、实际关着」的裂缝）。"""
    offenders: list[str] = []
    for path in PLUGINS_ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        if rel.endswith("config.py") or path == OUTBOUND_GATE_PY:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        for node in ast.walk(tree):
            seen: str | None = None
            if isinstance(node, ast.Attribute):
                seen = node.attr
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                seen = node.value
            elif isinstance(node, ast.keyword):
                seen = node.arg
            if seen == NEW_FIELD:
                offenders.append(f"{rel}:{getattr(node, 'lineno', 0)}")
    assert offenders == [], f"{NEW_FIELD} 长出了第二读点：{offenders}"


# ===========================================================================
# ③ 接线形态（AST 锁；形状照同文件既有协作者钩子 `outbound_voice_enricher` 的写法）
# ===========================================================================
def _hook_violations(source: str) -> list[str]:
    """「协作者缺省不是 None」或「调用点没被 `is not None` 罩住」的违规说明（合规返回空）。"""
    violations: list[str] = []
    tree = ast.parse(source)
    found_default = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "__init__":
            continue
        for arg, default in zip(reversed(node.args.args), reversed(node.args.defaults)):
            if arg.arg != HOOK_PARAM:
                continue
            found_default = True
            if not (isinstance(default, ast.Constant) and default.value is None):
                violations.append(
                    f"{getattr(node, 'lineno', 0)} 行：{HOOK_PARAM} 缺省不是 None"
                    "（⇒ 不带那枚关键字的调用点也在跑新腿）"
                )
    if not found_default:
        violations.append(f"RuntimePipeline.__init__ 没有可选协作者 {HOOK_PARAM}")

    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    def test_guards_self_attr(node: ast.AST) -> bool:
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Compare)
                and isinstance(inner.left, ast.Attribute)
                and isinstance(inner.left.value, ast.Name)
                and inner.left.value.id == "self"
                and inner.left.attr == HOOK_PARAM
            ):
                return True
        return False

    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self"
            and node.func.attr == HOOK_PARAM
        ):
            continue
        cursor: ast.AST | None = parents.get(node)
        guarded = False
        while cursor is not None:
            if isinstance(cursor, ast.If) and test_guards_self_attr(cursor.test):
                guarded = True
                break
            cursor = parents.get(cursor)
        if not guarded:
            violations.append(
                f"{getattr(node, 'lineno', 0)} 行调用 self.{HOOK_PARAM}(...) 未被"
                f" `self.{HOOK_PARAM} is not None` 罩住（关态那一支必须不可达）"
            )
    return violations


def test_pipeline_hook_is_optional_and_guarded() -> None:
    source = PIPELINE_PY.read_text(encoding="utf-8")
    assert _hook_violations(source) == [], f"pipeline 接线形态不合规矩：{_hook_violations(source)}"


def test_pipeline_hook_guard_lock_has_teeth() -> None:
    """注毒：摘掉 None 守卫（当作恒可达）必须被同一把尺点名。"""
    source = PIPELINE_PY.read_text(encoding="utf-8")
    needle = f"if self.{HOOK_PARAM} is not None:"
    assert needle in source, "前提已变：pipeline 里的守卫写法变了，尺要跟着改"
    poisoned = source.replace(needle, "if True:", 1)
    assert _hook_violations(poisoned), "摘掉守卫仍判合规 ⇒ 这枚锁是装饰"
    assert not _hook_violations(source), "还原后必须复绿（红只许来自判据）"


def test_root_assembly_wires_the_factory_into_the_pipeline() -> None:
    """根装配只经工厂取协作者并交进 `RuntimePipeline`（禁自己另开一条投递腿）。"""
    source = ROOT_INIT_PY.read_text(encoding="utf-8")
    assert "build_move_private_redirector" in source, "根装配没接工厂"
    wired = any(
        any(kw.arg == HOOK_PARAM for kw in node.keywords)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "RuntimePipeline"
    )
    assert wired, f"RuntimePipeline(...) 调用点没把 {HOOK_PARAM} 交进去"


# ===========================================================================
# ④ 缺省关＝零行为变化（本波最硬的一枚牙）
# ===========================================================================
def test_group_personal_output_is_still_blocked_and_nothing_is_sent() -> None:
    assert _review(_result()).action is ReviewAction.MOVE_PRIVATE, (
        "前提已变：reviewer 不再产出 MOVE_PRIVATE ⇒ 本文件的靶子没了"
    )
    assert _review(_result()).approved is False
    receipt, audit, queue = _drive(_result())  # 不装协作者＝今日形态
    assert receipt.state is ReceiptState.BLOCKED, receipt
    assert receipt.transport == "reviewer", receipt
    assert queue.sent_requests == [], (
        f"关态却往队列里塞了 {len(queue.sent_requests)} 条请求＝本波擅自启用"
    )
    assert audit.review_rows(), "BLOCK 那一支原有的审计行不许被新腿吃掉"


def test_poison_dropping_the_switch_check_breaks_the_default_off_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """注毒：把开关判定当**恒开** ⇒ ④ 那枚「关态零变化」必须红（开关是承重的）。"""
    assert getattr(og, "move_private_redirect_enabled", None) is not None, (
        "功能不存在：outbound_gate 里没有开关判据函数"
    )
    monkeypatch.setattr(og, "move_private_redirect_enabled", lambda config: True)
    audit = _RecordingAudit()
    queue = InMemorySendQueue(audit_logger=audit)
    redirector = og.build_move_private_redirector(
        SimpleNamespace(),  # 键关/键缺席的配置面；开关被摘掉后照样产出真协作者
        send_queue=queue,
        gate=_gate(),
        audit_logger=audit,
    )
    assert redirector is not None, "摘掉开关判定仍拿到 None ⇒ 工厂里没人读那枚开关（空跑）"
    receipt, _rows, polluted = _drive(
        _result(), redirector=redirector, queue=queue, audit=audit
    )
    assert polluted.sent_requests, "恒开态也没有新请求 ⇒ 转投腿根本没接上"
    assert receipt.state is not ReceiptState.BLOCKED, "恒开态仍判 BLOCKED ⇒ ④ 的红不来自判据"


# ===========================================================================
# ⑤ 开时确实转投
# ===========================================================================
def test_switch_on_redirects_the_reply_to_a_private_request() -> None:
    result = _result()
    expected = render_reviewed_output(result, _review(result))
    audit = _RecordingAudit()
    queue = InMemorySendQueue(audit_logger=audit)
    redirector = _redirector(SimpleNamespace(**{NEW_FIELD: True}), queue, audit)
    receipt, _rows, _queue = _drive(result, redirector=redirector, queue=queue, audit=audit)

    requests = list(queue.sent_requests)
    assert len(requests) == 1, f"转投必须恰一条，实得 {len(requests)}"
    request = requests[0]
    assert request.target_scope is SessionType.PRIVATE, request.target_scope
    assert request.target_id == _SENDER_ID, "收件人必须是请求者本人"
    assert receipt.state is ReceiptState.REDIRECTED, (
        "REDIRECTED 在契约里一直是「有消费者无生产者」，本波给它补上生产者"
    )
    assert receipt.public_message == "", "群侧不发言：回执不许带任何引导句/说明句"
    # 零新增人格文案：转出去的那封＝原本要发的那一份，逐字节同一个成形口。
    assert request.content.text_fallback == expected.text_fallback
    assert request.content.content_ref == expected.content_ref


def test_redirect_audit_row_carries_no_reply_text() -> None:
    """转投这件事要可见，但落盘面零正文、零他人号（AGENTS 铁律 3 同族）。"""
    audit = _RecordingAudit()
    queue = InMemorySendQueue(audit_logger=audit)
    redirector = _redirector(SimpleNamespace(**{NEW_FIELD: True}), queue, audit)
    _drive(_result(), redirector=redirector, queue=queue, audit=audit)
    rows = audit.review_rows()
    assert rows, "转投必须留一行 review 审计（否则现网查不到「哪条走了私聊」）"
    blob = "｜".join(f"{row.event}{row.private_debug}{row.public_message}" for row in rows)
    assert _BODY not in blob, "回复原文落进了审计盘"
    assert _GROUP_ID not in blob and _OTHER_MEMBER_ID not in blob, blob


# ===========================================================================
# ⑥ 键形只有一处构造
# ===========================================================================
def _session_key_shape_offenders(source: str) -> list[str]:
    """`session_id=` 实参里手拼私聊键的形状（字面量或以 `private` 打头的 f-string）。

    尺只着 `session_id=` 那一个槽位 ⇒ 审计字段名 `private_debug` 一类不在射程内。
    真身只许来自中央件 `session_keys.private_session_key`（另见下一条「必须真调用」锁）。
    """
    offenders: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.keyword) or node.arg != "session_id":
            continue
        hand_built = [
            f"{ast.unparse(child)!r}"
            for child in ast.walk(node.value)
            if (
                isinstance(child, ast.Constant)
                and isinstance(child.value, str)
                and child.value.strip().lower().startswith("private")
            )
            or isinstance(child, ast.JoinedStr)
        ]
        if hand_built:
            offenders.append(f"{getattr(node, 'lineno', 0)} 行自拼会话键：{hand_built}")
    return offenders


def _calls_central_private_ctor(source: str) -> bool:
    """该源件必须**从中央件导入并调用** `private_session_key`（在册未执法的反面）。"""
    tree = ast.parse(source)
    imported = any(
        isinstance(node, ast.ImportFrom)
        and (node.module or "") == CENTRAL_SESSION_KEYS_MODULE
        and any(alias.name == CENTRAL_PRIVATE_CTOR for alias in node.names)
        for node in ast.walk(tree)
    )
    called = any(
        isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == CENTRAL_PRIVATE_CTOR)
            or (isinstance(node.func, ast.Attribute)
                and node.func.attr == CENTRAL_PRIVATE_CTOR)
        )
        for node in ast.walk(tree)
    )
    return imported and called


def test_private_session_key_is_built_by_the_central_constructor_only() -> None:
    source = OUTBOUND_GATE_PY.read_text(encoding="utf-8")
    assert _calls_central_private_ctor(source), (
        f"{OUTBOUND_GATE_PY.name} 没从 {CENTRAL_SESSION_KEYS_MODULE} 取 "
        f"{CENTRAL_PRIVATE_CTOR} ⇒ 键形第二真身的入口"
    )
    assert _session_key_shape_offenders(source) == [], (
        f"生产件里手拼私聊会话键：{_session_key_shape_offenders(source)}"
    )


def test_session_key_shape_lock_has_teeth() -> None:
    """注毒：把中央件那一次产出换成自拼串，同一把尺必须红。"""
    source = OUTBOUND_GATE_PY.read_text(encoding="utf-8")
    assert _session_key_shape_offenders(source) == [], "前提已变：真件里已有自拼形状"
    poisoned = source.replace(
        "session_id=private_key,",
        'session_id=f"private_{message.sender_id}",',
        1,
    )
    assert poisoned != source, "注毒替换未生效 ⇒ 这枚锁在空跑（落笔形状变了要同步改这里）"
    assert _session_key_shape_offenders(poisoned), "自拼串仍判合规 ⇒ 这枚锁是装饰"
    # 尺的形状自证：中央件那一形判绿、手拼那一形判红，两副面孔都要有主。
    central_shape = (
        f"from {CENTRAL_SESSION_KEYS_MODULE} import {CENTRAL_PRIVATE_CTOR}\n"
        f"request = SendRequest(session_id={CENTRAL_PRIVATE_CTOR}(uid))\n"
    )
    assert not _session_key_shape_offenders(central_shape)
    assert _calls_central_private_ctor(central_shape)
    hand_shape = 'request = SendRequest(session_id=f"private_{uid}")\n'
    assert _session_key_shape_offenders(hand_shape)
    assert not _calls_central_private_ctor(hand_shape)


def test_redirected_session_key_is_the_central_private_form() -> None:
    """开态那一条请求的 `session_id` 逐字节等于中央件产物，且形态判得是私聊。"""
    audit = _RecordingAudit()
    queue = InMemorySendQueue(audit_logger=audit)
    redirector = _redirector(SimpleNamespace(**{NEW_FIELD: True}), queue, audit)
    _drive(_result(), redirector=redirector, queue=queue, audit=audit)
    request = queue.sent_requests[0]
    assert request.session_id == session_keys.private_session_key(_SENDER_ID)
    parsed = session_keys.parse_session_key(request.session_id)
    assert parsed.kind == session_keys.KIND_PRIVATE, parsed
    assert parsed.form == session_keys.FORM_BARE, parsed
    assert parsed.user_id == _SENDER_ID, parsed
    # 群号绝不进私聊键（#33 同族：TG 群号与 QQ 用户号撞同一枚那一类）。
    assert _GROUP_ID not in request.session_id


# ===========================================================================
# ⑦ 归属只给本人
# ===========================================================================
def test_switch_on_sends_nothing_to_the_group() -> None:
    audit = _RecordingAudit()
    queue = InMemorySendQueue(audit_logger=audit)
    redirector = _redirector(SimpleNamespace(**{NEW_FIELD: True}), queue, audit)
    _drive(_result(), redirector=redirector, queue=queue, audit=audit)
    group_side = [
        request
        for request in queue.sent_requests
        if request.target_id == _GROUP_ID or request.target_scope is SessionType.GROUP
    ]
    assert group_side == [], f"群侧发言了：{group_side}"


def test_redirect_targets_the_requester_and_nobody_else() -> None:
    for sender in (_SENDER_ID, _OTHER_MEMBER_ID):
        audit = _RecordingAudit()
        queue = InMemorySendQueue(audit_logger=audit)
        redirector = _redirector(SimpleNamespace(**{NEW_FIELD: True}), queue, audit)
        _drive(
            _result(request_id=f"req-move-private-{sender}"),
            message=_group_message(sender),
            redirector=redirector,
            queue=queue,
            audit=audit,
        )
        targets = {request.target_id for request in queue.sent_requests}
        assert targets == {sender}, f"转投目标={targets}，本该只有本人 {sender}"
        assert {
            request.target_scope for request in queue.sent_requests
        } == {SessionType.PRIVATE}


# ===========================================================================
# ⑧ 判据不越界：BLOCK 绝不因为开了开关而走私聊
# ===========================================================================
def test_block_is_still_block_even_with_the_switch_on() -> None:
    critical = _result(risk_level=RiskLevel.CRITICAL)
    assert _review(critical).action is ReviewAction.BLOCK
    audit = _RecordingAudit()
    queue = InMemorySendQueue(audit_logger=audit)
    redirector = _redirector(SimpleNamespace(**{NEW_FIELD: True}), queue, audit)
    receipt, _rows, _queue = _drive(
        critical, redirector=redirector, queue=queue, audit=audit
    )
    assert receipt.state is ReceiptState.BLOCKED, receipt
    assert queue.sent_requests == [], "BLOCK 的内容被转投到私聊＝新增一条泄露腿"


def test_central_exit_is_the_only_submit_throat_in_the_redirect_leg() -> None:
    """转投腿只经中央出口 `submit_active_push`，不许直调 `send_queue.submit`（禁第二通路）。"""
    source = OUTBOUND_GATE_PY.read_text(encoding="utf-8")
    factory = next(
        (
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.FunctionDef)
            and node.name == "build_move_private_redirector"
        ),
        None,
    )
    assert factory is not None, "功能不存在：outbound_gate.py 里没有 build_move_private_redirector"
    calls: set[str] = set()
    direct_submits: list[int] = []
    for node in ast.walk(factory):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            calls.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            calls.add(node.func.attr)
            if node.func.attr == "submit" and isinstance(
                node.func.value, ast.Name
            ) and node.func.value.id == "send_queue":
                direct_submits.append(getattr(node, "lineno", 0))
    assert "submit_active_push" in calls, f"转投腿没走中央出口，实调={sorted(calls)}"
    assert not direct_submits, f"绕闸直调 send_queue.submit：{direct_submits}"
