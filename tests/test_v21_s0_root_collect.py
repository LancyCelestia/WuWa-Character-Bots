"""S0-ROOT-c 席（v21r4-B）：根 ``__init__.py`` 四处直连点收编行为锁。

取证权威=``docs/design/v21r4-b2-direct-collect-plan.md``（DIRECT-PLAN 席）+
本席日志 ``docs/design/v21r4-b-S0-ROOT-log.md``。四处（执行序 ④②③①）：

- ④ 文档导出上传 ``_handle_admin_file_export`` → 形态 D（``CapabilityResult.files``
  → FileTransferGateway 既有链）；门 ``bot_file_export_via_queue`` 缺省关。
- ② 入群欢迎 ``_handle_group_increase`` → 形态 A（``_send_text_through_unified_pipeline``）；
  门 ``bot_group_welcome_via_queue`` 缺省关。
- ③ cookie 登录二维码图片 ``_handle_admin_cookie`` → 形态 A mixed
  （``_send_parts_through_unified_pipeline``；text=""+image 同款先例=表情回应
  meme 抽图）；门 ``bot_cookie_qr_via_queue`` 缺省关。
- ① cookie 到期提醒 ``_cookie_expiry_reminder_job`` → 形态 B（``_deliver_due_reminders``
  提醒范式：SendRequest→submit→内联投递→SENT/REDIRECTED 才算送达；
  dedupe_key/request_id 带本地日期=当日幂等）；门 ``bot_cookie_expiry_reminder_via_queue``
  缺省关。

测试方法：四处 handler 是 ``_register_nonebot_handlers()`` 内嵌套函数，无法直接
import——用 AST 提取单个函数节点（无装饰器；剪除体内内嵌 import 防遮蔽受控
接缝），在受控命名空间（闭包真名替换为离线 spy）中编译 exec 出真函数，做
「门开走统一路径 / 门关走旧路径（逐字节等价）」双态断言；① 的模块级投递助手
可直接 import（``deliver_fn`` 注入缝，零 monkeypatch）。全离线：零网络、
零 NoneBot 启动、零真实发送、零根 ``__init__.py`` 写入。
"""

from __future__ import annotations

import ast
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugins.bot_unified_runtime import _group_welcome_text
from plugins.bot_unified_runtime.contracts import CapabilityResult, ReceiptState

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PLUGIN_ROOT = _REPO_ROOT / "plugins" / "bot_unified_runtime"

_SENT_OK = {ReceiptState.SENT, ReceiptState.REDIRECTED}


# ---------------------------------------------------------------------------
# AST 提取 + 受控 exec（嵌套 handler 的离线行为测试基建）
# ---------------------------------------------------------------------------


def _extract_function_node(func_name: str) -> ast.stmt:
    source = (_PLUGIN_ROOT / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
        and node.name == func_name
    ]
    assert len(matches) == 1, f"{func_name} 应恰一处定义，现={len(matches)}"
    return matches[0]


def _prune_inline_imports(block: list[ast.stmt]) -> None:
    """剪除函数体内的内嵌 import：其绑定会遮蔽测试注入的受控接缝。

    生产语义不受影响——被剪 import 提供的名字（cookie_expiry_report /
    _DOCUMENT_PROMPT）在命名空间里由 fake 显式提供，handler 逻辑本体
    （门/分支/发送面）逐字节原样编译执行。
    """
    block[:] = [s for s in block if not isinstance(s, (ast.Import, ast.ImportFrom))]
    for stmt in block:
        for field in ("body", "orelse", "finalbody"):
            value = getattr(stmt, field, None)
            if isinstance(value, list) and value and isinstance(value[0], ast.stmt):
                _prune_inline_imports(value)
        for handler in getattr(stmt, "handlers", None) or []:
            _prune_inline_imports(handler.body)


def _exec_handler(func_name: str, **env: Any) -> Any:
    """把提取出的（无装饰器）函数 AST 在受控命名空间编译 exec 成真函数。

    装饰器不入编译单元（FunctionDef 节点本身）；注解按即时求值处理，
    命名空间预置哑元类型（PEP 563 惰性在本编译单元不生效，故注解里
    出现的名字必须可解析）。
    """
    node = _extract_function_node(func_name)
    node.decorator_list = []  # 装配装饰器（.handle() 等）不属被测面，剥离。
    _prune_inline_imports(node.body)
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace: dict[str, Any] = {
        "__package__": "plugins.bot_unified_runtime",
        "__name__": f"s0_root_collect.{func_name}",
        "Any": Any,
        "Bot": SimpleNamespace,
        "Event": SimpleNamespace,
        "IncomingMessage": SimpleNamespace,
        "DeliveryReceipt": SimpleNamespace,
    }
    namespace.update(env)
    exec(compile(module, f"<{func_name}>", "exec"), namespace)  # noqa: S102 - 测试受控提取
    return namespace[func_name]


class _FakeBot:
    """记录 call_api 的离线 bot 替身（onebot 身份 + 可选按 api/user 拒绝）。"""

    def __init__(
        self,
        member_info: Any = None,
        fail_member_info: bool = False,
        fail_user_ids: tuple[int, ...] = (),
        fail_apis: tuple[str, ...] = (),
    ) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.self_id = "bot-1"
        self.adapter = SimpleNamespace(get_name=lambda: "onebot")
        self._member_info = member_info
        self._fail_member_info = fail_member_info
        self._fail_user_ids = set(fail_user_ids)
        self._fail_apis = set(fail_apis)

    async def call_api(self, api: str, **kwargs: Any) -> Any:
        self.calls.append((api, kwargs))
        if api == "get_group_member_info":
            if self._fail_member_info:
                raise RuntimeError("member info unavailable")
            return self._member_info
        if api in self._fail_apis:
            raise RuntimeError("platform rejected")
        if api == "send_private_msg" and kwargs.get("user_id") in self._fail_user_ids:
            raise RuntimeError("send rejected")
        return SimpleNamespace(retcode=0)


def _text_spy(receipt_state: Any = ReceiptState.SENT, raise_on_call: bool = False):
    calls: list[dict] = []

    async def _spy(bot: Any, event: Any, text: str, capability_id: str = "bot.file"):
        if raise_on_call:
            raise RuntimeError("unified text send blew up")
        calls.append({"text": text, "capability_id": capability_id})
        return SimpleNamespace(state=receipt_state)

    return _spy, calls


def _parts_spy(receipt_state: Any = ReceiptState.SENT, raise_on_call: bool = False):
    calls: list[dict] = []

    async def _spy(bot: Any, event: Any, *, text: str, image: Any = None, **kwargs: Any):
        if raise_on_call:
            raise RuntimeError("unified parts send blew up")
        calls.append({"text": text, "image": image, **kwargs})
        return SimpleNamespace(state=receipt_state)

    return _spy, calls


def _files_spy(receipt_state: Any = ReceiptState.SENT, raise_on_call: bool = False):
    calls: list[dict] = []

    async def _spy(
        bot: Any, event: Any, *, text: str = "", files: Any = None, **kwargs: Any
    ):
        if raise_on_call:
            raise RuntimeError("unified files send blew up")
        calls.append({"text": text, "files": files, **kwargs})
        return SimpleNamespace(state=receipt_state)

    return _spy, calls


class _GroupEventDummy:
    """isinstance(event, GroupMessageEvent) 命中的群事件哑元（含 get_plaintext）。"""

    def __init__(self, group_id: int = 123, user_id: int = 456) -> None:
        self.group_id = group_id
        self.user_id = user_id

    def get_plaintext(self) -> str:
        return ""


def _private_event(user_id: str = "789") -> SimpleNamespace:
    return SimpleNamespace(get_user_id=lambda: user_id, get_plaintext=lambda: "")


def _file_export_env(tmp_path: Path, doc: Path, via_queue: bool | None) -> dict[str, Any]:
    config_kwargs: dict[str, Any] = {"bot_download_dir": str(tmp_path)}
    if via_queue is not None:
        config_kwargs["bot_file_export_via_queue"] = via_queue
    files_spy, files_calls = _files_spy()
    text_spy, text_calls = _text_spy()
    env = {
        "parse_file_export_command": lambda _text: ("markdown", "测试主题"),
        "asyncio": asyncio,
        "_build_chat_llm_provider": lambda _config: SimpleNamespace(
            generate=lambda _messages, **_kw: SimpleNamespace(text="# 标题")
        ),
        "_Path": Path,
        "_DOCUMENT_PROMPT": "生成文档（受控接缝注入）",
        "export_document": lambda *_a, **_k: (doc, None),
        "GroupMessageEvent": _GroupEventDummy,
        "config": SimpleNamespace(**config_kwargs),
        "_send_files_through_unified_pipeline": files_spy,
        "_send_text_through_unified_pipeline": text_spy,
        "ReceiptState": ReceiptState,
    }
    return env | {"__spies__": (files_calls, text_calls)}


def _run_export(
    tmp_path: Path,
    *,
    event: Any,
    via_queue: bool | None,
    fail_apis: tuple[str, ...] = (),
    files_receipt: Any = ReceiptState.SENT,
    files_raise: bool = False,
) -> tuple[list, list, list, _FakeBot, Path]:
    doc = tmp_path / "export" / "doc.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("# t", encoding="utf-8")
    env = _file_export_env(tmp_path, doc, via_queue)
    if files_raise:
        env["_send_files_through_unified_pipeline"], files_calls = _files_spy(
            raise_on_call=True
        )
    else:
        env["_send_files_through_unified_pipeline"], files_calls = _files_spy(
            files_receipt
        )
    env["__spies__"] = (files_calls, env["__spies__"][1])
    bot = _FakeBot(fail_apis=fail_apis)
    env["bot"] = bot
    handler = _exec_handler("_handle_admin_file_export", **env)
    asyncio.run(handler(bot, event))
    files_calls, text_calls = env["__spies__"]
    return bot.calls, files_calls, text_calls, bot, doc


# ===========================================================================
# ④ 文档导出上传（形态 D：CapabilityResult.files → FileTransferGateway）
# ===========================================================================


def test_send_files_helper_builds_files_capability() -> None:
    """新助手契约：files 原样进 CapabilityResult.files、kind=mixed、回执透传。"""
    captured: dict[str, Any] = {}

    async def _fake_run(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return SimpleNamespace(state=ReceiptState.SENT)

    helper = _exec_handler(
        "_send_files_through_unified_pipeline",
        CapabilityResult=CapabilityResult,
        config=SimpleNamespace(),
        pipeline=SimpleNamespace(),
        send_queue=SimpleNamespace(),
        audit_logger=SimpleNamespace(),
        diagnostics_store=SimpleNamespace(),
        receipt_repository=None,
        _notify_operational_receipt=None,
        _run_capability_through_pipeline=_fake_run,
    )
    receipt = asyncio.run(
        helper(
            SimpleNamespace(),
            SimpleNamespace(),
            files=[{"file": "/tmp/a.md", "name": "a.md"}],
            capability_id="bot.file",
        )
    )
    assert receipt.state is ReceiptState.SENT
    capability = captured["capability"](SimpleNamespace(request_id="req-1"), None)
    assert isinstance(capability, CapabilityResult)
    assert capability.files == [{"file": "/tmp/a.md", "name": "a.md"}]
    assert capability.kind == "mixed"
    assert capability.capability_id == "bot.file"
    assert capability.request_id == "req-1"


def test_file_export_gate_on_group_uses_unified_files_path(tmp_path: Path) -> None:
    """门开（群）：零 call_api 直传；files 件进统一管线；SENT → 成功文案。"""
    calls, files_calls, text_calls, _bot, doc = _run_export(
        tmp_path, event=_GroupEventDummy(), via_queue=True
    )
    assert calls == [], f"门开不得直连上传，现={calls}"
    assert len(files_calls) == 1
    assert files_calls[0]["files"] == [{"file": str(doc), "name": "doc.md"}]
    assert files_calls[0]["capability_id"] == "bot.file"
    assert len(text_calls) == 1
    assert "已生成并上传 MARKDOWN" in text_calls[0]["text"]


def test_file_export_gate_on_private_uses_unified_files_path(tmp_path: Path) -> None:
    """门开（私聊）：同一统一文件链（目标面由管线按会话判，直连零调用）。"""
    calls, files_calls, _text_calls, _bot, _doc = _run_export(
        tmp_path, event=_private_event(), via_queue=True
    )
    assert calls == []
    assert len(files_calls) == 1


def test_file_export_gate_on_unified_raise_sends_failure_text(tmp_path: Path) -> None:
    """门开：统一链异常 → 失败文案经统一管线发出且零异常上抛（旧语义保持）。"""
    _calls, _files_calls, text_calls, _bot, doc = _run_export(
        tmp_path, event=_GroupEventDummy(), via_queue=True, files_raise=True
    )
    assert text_calls[-1]["text"] == f"文件已生成但上传失败：{doc.name}"


def test_file_export_gate_on_failed_receipt_sends_failure_text(tmp_path: Path) -> None:
    """门开：回执 FAILED_RETRYABLE → 失败文案（回执态驱动，诚实不假成功）。"""
    _calls, _files_calls, text_calls, _bot, doc = _run_export(
        tmp_path,
        event=_GroupEventDummy(),
        via_queue=True,
        files_receipt=ReceiptState.FAILED_RETRYABLE,
    )
    assert text_calls[-1]["text"] == f"文件已生成但上传失败：{doc.name}"


def test_file_export_gate_off_keeps_direct_upload_group(tmp_path: Path) -> None:
    """门关（群，缺省）：旧直连逐字节等价——upload_group_file + 成功文案。"""
    calls, files_calls, text_calls, _bot, doc = _run_export(
        tmp_path, event=_GroupEventDummy(), via_queue=None
    )
    assert files_calls == [], "门关不得走统一文件链"
    assert calls == [
        (
            "upload_group_file",
            {"group_id": 123, "file": str(doc), "name": "doc.md"},
        )
    ]
    assert len(text_calls) == 1
    assert "已生成并上传 MARKDOWN" in text_calls[0]["text"]


def test_file_export_gate_off_keeps_direct_upload_private(tmp_path: Path) -> None:
    """门关（私聊）：upload_private_file + user_id 分支保持。"""
    calls, _files_calls, _text_calls, _bot, doc = _run_export(
        tmp_path, event=_private_event(), via_queue=None
    )
    assert calls == [
        (
            "upload_private_file",
            {"user_id": 789, "file": str(doc), "name": "doc.md"},
        )
    ]


def test_file_export_gate_off_upload_failure_failure_text(tmp_path: Path) -> None:
    """门关：旧失败语义逐字节保持——上传异常只回报失败文案，零上抛。"""
    calls, _files_calls, text_calls, _bot, doc = _run_export(
        tmp_path,
        event=_GroupEventDummy(),
        via_queue=None,
        fail_apis=("upload_group_file",),
    )
    assert calls == [("upload_group_file", {"group_id": 123, "file": str(doc), "name": "doc.md"})]
    assert text_calls[-1]["text"] == f"文件已生成但上传失败：{doc.name}"


# ===========================================================================
# ② 入群欢迎（形态 A：_send_text_through_unified_pipeline）
# ===========================================================================


def _welcome_env(via_queue: bool | None, master_enabled: bool = True):
    config_kwargs: dict[str, Any] = {"bot_group_welcome_enabled": master_enabled}
    if via_queue is not None:
        config_kwargs["bot_group_welcome_via_queue"] = via_queue
    text_spy, text_calls = _text_spy()
    events: list[str] = []
    env = {
        "config": SimpleNamespace(**config_kwargs),
        "asyncio": asyncio,
        "_group_welcome_text": _group_welcome_text,
        "_log_runtime_event": lambda _log, _level, event, **_fields: events.append(event),
        "runtime_event_log": SimpleNamespace(),
        "_send_text_through_unified_pipeline": text_spy,
        "ReceiptState": ReceiptState,
    }
    return env | {"__spies__": (text_calls, events)}


def test_welcome_gate_on_uses_unified_pipeline() -> None:
    """门开：零 send_group_msg 直发；欢迎语进统一管线；SENT → 记 runtime 事件。"""
    env = _welcome_env(via_queue=True)
    bot = _FakeBot(member_info=SimpleNamespace(card="小涉", nickname=""))
    handler = _exec_handler("_handle_group_increase", **env)
    asyncio.run(handler(bot, _GroupEventDummy()))
    text_calls, events = env["__spies__"]
    assert [api for api, _kw in bot.calls] == ["get_group_member_info"], (
        "门开只允许昵称富集读路径，零直发"
    )
    assert len(text_calls) == 1
    assert text_calls[0]["text"] == _group_welcome_text("小涉")
    assert text_calls[0]["capability_id"] == "bot.group_welcome"
    assert events == ["group_welcome_sent"]


def test_welcome_gate_on_failed_receipt_skips_runtime_event() -> None:
    """门开：回执失败 → 不假成功，不记 group_welcome_sent。"""
    env = _welcome_env(via_queue=True)
    text_spy, _calls = _text_spy(ReceiptState.FAILED_RETRYABLE)
    env["_send_text_through_unified_pipeline"] = text_spy
    bot = _FakeBot(member_info=SimpleNamespace(card="", nickname=""))
    handler = _exec_handler("_handle_group_increase", **env)
    asyncio.run(handler(bot, _GroupEventDummy()))
    _text_calls, events = env["__spies__"]
    assert events == []


def test_welcome_gate_on_unified_exception_silent() -> None:
    """门开：统一管线异常 → 静默（欢迎失败不影响主链路，旧语义保持）。"""
    env = _welcome_env(via_queue=True)
    text_spy, _calls = _text_spy(raise_on_call=True)
    env["_send_text_through_unified_pipeline"] = text_spy
    bot = _FakeBot(member_info=SimpleNamespace(card="", nickname=""))
    handler = _exec_handler("_handle_group_increase", **env)
    asyncio.run(handler(bot, _GroupEventDummy()))  # 不上抛即过
    _text_calls, events = env["__spies__"]
    assert events == []


def test_welcome_gate_off_keeps_direct_group_msg() -> None:
    """门关（缺省）：旧直连逐字节等价——昵称富集+send_group_msg+事件记录。"""
    env = _welcome_env(via_queue=None)
    bot = _FakeBot(member_info=SimpleNamespace(card="小涉", nickname=""))
    handler = _exec_handler("_handle_group_increase", **env)
    asyncio.run(handler(bot, _GroupEventDummy()))
    text_calls, events = env["__spies__"]
    assert text_calls == [], "门关不得走统一管线"
    assert bot.calls[-1] == (
        "send_group_msg",
        {
            "group_id": 123,
            "message": [
                {"type": "text", "data": {"text": _group_welcome_text("小涉")}}
            ],
        },
    )
    assert events == ["group_welcome_sent"]


def test_welcome_master_gate_off_stays_silent_both_modes() -> None:
    """总开关关：门开门关都零发送（双门串联，任一关即不发）。"""
    for via_queue in (True, None):
        env = _welcome_env(via_queue=via_queue, master_enabled=False)
        bot = _FakeBot()
        handler = _exec_handler("_handle_group_increase", **env)
        asyncio.run(handler(bot, _GroupEventDummy()))
        text_calls, events = env["__spies__"]
        assert bot.calls == []
        assert text_calls == []
        assert events == []


# ===========================================================================
# ③ cookie 登录二维码图片（形态 A mixed：text="" + image）
# ===========================================================================


def _qr_env(tmp_path: Path, via_queue: bool | None, png_path: str | Path):
    config_kwargs: dict[str, Any] = {}
    if via_queue is not None:
        config_kwargs["bot_cookie_qr_via_queue"] = via_queue
    text_spy, text_calls = _text_spy()
    parts_spy, parts_calls = _parts_spy()
    login_text = "请用手机 B 站扫码登录 bilibili（5 分钟内有效）"
    env = {
        "parse_cookie_command": lambda _text: ("login", "bilibili", None),
        "cookie_login_start": lambda _config, _platform: ("sess", str(png_path), login_text),
        "config": SimpleNamespace(**config_kwargs),
        "logging": __import__("logging"),
        "_send_text_through_unified_pipeline": text_spy,
        "_send_parts_through_unified_pipeline": parts_spy,
        "GroupMessageEvent": _GroupEventDummy,
    }
    return env | {"__spies__": (text_calls, parts_calls, login_text)}


def _run_qr(tmp_path: Path, *, event: Any, via_queue: bool | None):
    png = tmp_path / "qr.png"
    png.write_bytes(b"png")
    env = _qr_env(tmp_path, via_queue, png)
    bot = _FakeBot()
    env["bot"] = bot
    handler = _exec_handler("_handle_admin_cookie", **env)
    asyncio.run(handler(bot, event))
    text_calls, parts_calls, login_text = env["__spies__"]
    return bot.calls, text_calls, parts_calls, login_text


def test_qr_gate_on_group_uses_unified_parts(tmp_path: Path) -> None:
    """门开（群）：图片走统一管线 mixed 件（file:/// 引用与直连段同构）。"""
    calls, text_calls, parts_calls, login_text = _run_qr(
        tmp_path, event=_GroupEventDummy(), via_queue=True
    )
    assert calls == [], "门开不得直发图片"
    assert len(text_calls) == 1 and text_calls[0]["text"] == login_text
    assert len(parts_calls) == 1
    assert parts_calls[0]["text"] == ""
    assert parts_calls[0]["image"] == "file:///" + str(tmp_path / "qr.png").replace("\\", "/")
    assert parts_calls[0]["capability_id"] == "bot.cookie_login"


def test_qr_gate_on_private_uses_unified_parts(tmp_path: Path) -> None:
    """门开（私聊）：同一统一管线件，目标面由管线按会话判。"""
    calls, _text_calls, parts_calls, _login_text = _run_qr(
        tmp_path, event=_private_event(), via_queue=True
    )
    assert calls == []
    assert len(parts_calls) == 1


def test_qr_gate_on_parts_failure_silent_no_raise(tmp_path: Path) -> None:
    """门开：图片链异常/失败回执 → 静默不抛（文本兜底已先行给出）。"""
    png = tmp_path / "qr.png"
    png.write_bytes(b"png")
    env = _qr_env(tmp_path, True, png)
    parts_spy, _calls = _parts_spy(raise_on_call=True)
    env["_send_parts_through_unified_pipeline"] = parts_spy
    bot = _FakeBot()
    env["bot"] = bot
    handler = _exec_handler("_handle_admin_cookie", **env)
    asyncio.run(handler(bot, _GroupEventDummy()))  # 不上抛即过
    text_calls, _parts_calls, _login_text = env["__spies__"]
    assert len(text_calls) == 1


def test_qr_gate_off_keeps_direct_image_send(tmp_path: Path) -> None:
    """门关（缺省）：旧直连逐字节等价——send_group_msg/send_private_msg 单图段。"""
    expected_file = "file:///" + str(tmp_path / "qr.png").replace("\\", "/")
    image_segment = [{"type": "image", "data": {"file": expected_file}}]
    calls, text_calls, parts_calls, _login_text = _run_qr(
        tmp_path, event=_GroupEventDummy(), via_queue=None
    )
    assert parts_calls == [], "门关不得走统一管线"
    assert len(text_calls) == 1
    assert calls == [("send_group_msg", {"group_id": 123, "message": image_segment})]

    calls, _text_calls, _parts_calls, _login_text = _run_qr(
        tmp_path, event=_private_event(), via_queue=None
    )
    assert calls == [
        ("send_private_msg", {"user_id": 789, "message": image_segment})
    ]


def test_qr_no_png_never_sends_image_both_modes(tmp_path: Path) -> None:
    """png 为空：门开门关都只有文本、零图片件。"""
    for via_queue in (True, None):
        env = _qr_env(tmp_path, via_queue, "")
        bot = _FakeBot()
        env["bot"] = bot
        handler = _exec_handler("_handle_admin_cookie", **env)
        asyncio.run(handler(bot, _GroupEventDummy()))
        text_calls, parts_calls, _login_text = env["__spies__"]
        assert bot.calls == []
        assert parts_calls == []
        assert len(text_calls) == 1


# ===========================================================================
# ① cookie 到期提醒（形态 B：_deliver_due_reminders 提醒范式）
# ===========================================================================


class _FakeQueue:
    def __init__(self) -> None:
        self.submitted: list[Any] = []

    def submit(self, request: Any) -> None:
        self.submitted.append(request)

    def find_request(self, request_id: str) -> Any:
        for request in reversed(self.submitted):
            if request.request_id == request_id:
                return request
        return None


def _deliver_stub(states: list[Any]):
    calls: list[Any] = []

    async def _deliver(
        bot: Any,
        event: Any,
        request: Any,
        audit_logger: Any,
        receipt_repository: Any,
        send_queue: Any,
    ) -> Any:
        calls.append(request)
        state = states.pop(0) if states else ReceiptState.FAILED_RETRYABLE
        return SimpleNamespace(state=state)

    return _deliver, calls


def _reminder_bot(fail_user_ids: tuple[int, ...] = ()) -> _FakeBot:
    return _FakeBot(fail_user_ids=fail_user_ids)


def _helper_import():
    from plugins.bot_unified_runtime import _deliver_cookie_expiry_report_via_queue

    return _deliver_cookie_expiry_report_via_queue


def test_cookie_reminder_helper_first_admin_sent_request_fields() -> None:
    """形态B助手：首管理员 SENT → True；SendRequest 字段+当日 dedupe 全量断言。"""
    helper = _helper_import()
    queue = _FakeQueue()
    bot = _reminder_bot()
    deliver, deliver_calls = _deliver_stub([ReceiptState.SENT])
    from datetime import datetime

    today = datetime.now().astimezone().date().isoformat()
    delivered = asyncio.run(
        helper(
            SimpleNamespace(bot_persona_profile_id="shorekeeper"),
            queue,
            SimpleNamespace(),
            None,
            bot,
            "【凭证到期】报告内容",
            ["111", "222"],
            deliver_fn=deliver,
        )
    )
    assert delivered is True
    assert len(deliver_calls) == 1, "首管理员送达即停，不得继续换人"
    request = deliver_calls[0]
    assert request.capability_id == "bot.cookie_expiry_notice"
    assert request.dedupe_key == f"cookie-expiry:111:{today}"
    assert request.cooldown_key == "cookie-expiry:111"
    assert request.request_id == f"cookie-expiry-111-{today}"
    assert request.session_id == "private:111"
    assert request.target_scope.value == "private"
    assert request.content.text_fallback == "【凭证到期】报告内容"
    assert request.content.privacy_level.value == "personal"
    assert request.adapter == "onebot"
    assert request.bot_id == "bot-1"
    assert request.persona_profile_id == "shorekeeper"
    assert request.max_messages == 1
    assert queue.submitted == [request]


def test_cookie_reminder_helper_admin_fallback_on_failure() -> None:
    """形态B助手：首管理员未送达 → 换下一管理员（dedupe 按管理员区分）。"""
    helper = _helper_import()
    queue = _FakeQueue()
    bot = _reminder_bot()
    deliver, deliver_calls = _deliver_stub(
        [ReceiptState.FAILED_RETRYABLE, ReceiptState.SENT]
    )
    delivered = asyncio.run(
        helper(
            SimpleNamespace(),
            queue,
            SimpleNamespace(),
            None,
            bot,
            "报告",
            ["111", "222"],
            deliver_fn=deliver,
        )
    )
    assert delivered is True
    assert [r.target_id for r in deliver_calls] == ["111", "222"]
    assert {r.dedupe_key for r in deliver_calls} >= {
        "cookie-expiry:111:" + deliver_calls[0].dedupe_key.rsplit(":", 1)[1],
        "cookie-expiry:222:" + deliver_calls[1].dedupe_key.rsplit(":", 1)[1],
    }
    assert deliver_calls[0].dedupe_key != deliver_calls[1].dedupe_key


def test_cookie_reminder_helper_all_failed_returns_false_silent() -> None:
    """形态B助手：全部失败 → False、零上抛（静默语义与旧直连一致）。"""
    helper = _helper_import()
    queue = _FakeQueue()
    bot = _reminder_bot()
    deliver, _deliver_calls = _deliver_stub([])  # 永远 FAILED_RETRYABLE

    async def _exploding_deliver(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("transport blew up")

    delivered = asyncio.run(
        helper(
            SimpleNamespace(),
            queue,
            SimpleNamespace(),
            None,
            bot,
            "报告",
            ["111", "222"],
            deliver_fn=_exploding_deliver,
        )
    )
    assert delivered is False
    delivered2 = asyncio.run(
        helper(
            SimpleNamespace(),
            queue,
            SimpleNamespace(),
            None,
            bot,
            "报告",
            ["111"],
            deliver_fn=deliver,
        )
    )
    assert delivered2 is False


def test_cookie_reminder_helper_same_day_receipt_dedupe() -> None:
    """形态B助手：回执仓已有当日 SENT → 直接视为已送达，零 submit（当日幂等）。"""
    helper = _helper_import()
    queue = _FakeQueue()
    bot = _reminder_bot()
    deliver, deliver_calls = _deliver_stub([ReceiptState.SENT])
    from datetime import datetime

    today = datetime.now().astimezone().date().isoformat()

    class _Repo:
        def latest(self, request_id: str) -> Any:
            assert request_id == f"cookie-expiry-111-{today}"
            return SimpleNamespace(state=ReceiptState.SENT)

    delivered = asyncio.run(
        helper(
            SimpleNamespace(),
            queue,
            SimpleNamespace(),
            _Repo(),
            bot,
            "报告",
            ["111"],
            deliver_fn=deliver,
        )
    )
    assert delivered is True
    assert deliver_calls == [] and queue.submitted == []


def test_cookie_reminder_job_gate_on_uses_queue_helper() -> None:
    """门开：job 零直发，改投模块级统一路径助手（参数面=job 现场上下文）。"""
    spy_calls: list[dict] = []

    async def _spy(*args: Any) -> bool:
        spy_calls.append({"args": args})
        return True

    bot = _reminder_bot()
    queue = _FakeQueue()
    env = {
        "cookie_expiry_report": lambda _config: "【凭证到期】报告内容",
        "asyncio": asyncio,
        "config": SimpleNamespace(
            bot_admin_user_ids=["111", "222"],
            bot_cookie_expiry_reminder_via_queue=True,
        ),
        "_select_credential_bot": lambda _bots: bot,
        "_all_online_bots": lambda: {"bot-1": bot},
        "send_queue": queue,
        "audit_logger": SimpleNamespace(),
        "receipt_repository": None,
        "_deliver_cookie_expiry_report_via_queue": _spy,
        "logging": __import__("logging"),
    }
    job = _exec_handler("_cookie_expiry_reminder_job", **env)
    asyncio.run(job())
    assert bot.calls == [], "门开不得直连 send_private_msg"
    assert len(spy_calls) == 1
    args = spy_calls[0]["args"]
    assert args[0].bot_admin_user_ids == ["111", "222"]
    assert args[4] is bot
    assert args[5] == "【凭证到期】报告内容"
    assert args[6] == ["111", "222"]


def test_cookie_reminder_job_gate_off_keeps_direct_send() -> None:
    """门关（缺省）：旧直连逐字节等价——send_private_msg 首管理员成功即 break。"""
    bot = _reminder_bot()
    env = {
        "cookie_expiry_report": lambda _config: "【凭证到期】报告内容",
        "asyncio": asyncio,
        "config": SimpleNamespace(bot_admin_user_ids=["111", "222"]),
        "_select_credential_bot": lambda _bots: bot,
        "_all_online_bots": lambda: {"bot-1": bot},
        "logging": __import__("logging"),
    }
    job = _exec_handler("_cookie_expiry_reminder_job", **env)
    asyncio.run(job())
    assert bot.calls == [
        (
            "send_private_msg",
            {
                "user_id": 111,
                "message": [
                    {"type": "text", "data": {"text": "【凭证到期】报告内容"}}
                ],
            },
        )
    ]


def test_cookie_reminder_job_gate_off_admin_fallback() -> None:
    """门关：旧换人语义保持——首管理员异常降级 debug、换下一个。"""
    bot = _reminder_bot(fail_user_ids=(111,))
    env = {
        "cookie_expiry_report": lambda _config: "报告",
        "asyncio": asyncio,
        "config": SimpleNamespace(bot_admin_user_ids=["111", "222"]),
        "_select_credential_bot": lambda _bots: bot,
        "_all_online_bots": lambda: {"bot-1": bot},
        "logging": __import__("logging"),
    }
    job = _exec_handler("_cookie_expiry_reminder_job", **env)
    asyncio.run(job())
    assert [kwargs.get("user_id") for _api, kwargs in bot.calls] == [111, 222]


def test_cookie_reminder_job_no_bot_or_empty_report_stays_silent() -> None:
    """门开+报告空/无在线 bot：静默 return（前置语义两形态一致）。"""
    bot = _reminder_bot()
    for env_kwargs in (
        {"cookie_expiry_report": lambda _config: ""},
        {"_select_credential_bot": lambda _bots: None},
    ):
        env = {
            "cookie_expiry_report": lambda _config: "报告",
            "asyncio": asyncio,
            "config": SimpleNamespace(
                bot_admin_user_ids=["111"],
                bot_cookie_expiry_reminder_via_queue=True,
            ),
            "_select_credential_bot": lambda _bots: bot,
            "_all_online_bots": lambda: {"bot-1": bot},
            "send_queue": _FakeQueue(),
            "audit_logger": SimpleNamespace(),
            "receipt_repository": None,
            "logging": __import__("logging"),
        }
        env.update(env_kwargs)
        job = _exec_handler("_cookie_expiry_reminder_job", **env)
        asyncio.run(job())
    assert bot.calls == []


# ===========================================================================
# 配置门缺省关（三件套登记：config.py + config-catalog + .env.example）
# ===========================================================================


def test_via_queue_gates_default_off() -> None:
    """四门全部缺省关：False=旧直连逐字节等价，拨 True 才走统一路径。"""
    from plugins.bot_unified_runtime.config import Config

    config = Config()
    for key in (
        "bot_file_export_via_queue",
        "bot_group_welcome_via_queue",
        "bot_cookie_qr_via_queue",
        "bot_cookie_expiry_reminder_via_queue",
    ):
        assert getattr(config, key, "missing") is False, f"{key} 应存在且缺省 False"
