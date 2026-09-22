"""生产接线回归（评审 C1/D2 修复，TDD，全离线）。

锁定四件事：
- C1 接线：divination 走 `_build_divination_with_backend` 工厂壳；today_history
  交互路径（matcher 复用 today_ctx）注入 render_backend 出卡；
- C1 产品裁定：today_history 推送调度器保持纯文字——推送能力构造显式
  render_backend=None（定时推送不依赖 Playwright 渲染进程），与交互能力分流；
- C1 兜底：后端缺失/失败 → 输出与纯文字版逐字一致（kind=text、images 空）；
- D2：QQ 摄取层填充 sender_display_name——OneBot v11 群内 card=群名片、
  nickname=昵称，card 优先；strip 后为空不传（保持 None）。

启动函数体（_register_nonebot_handlers）无法离线单测，接线存在性按既有
test_finance_routing 的 AST 断言切口锁定；能力行为用 fake 后端直接驱动；
调度器分流用 monkeypatch 捕获 build_today_history_capability 实参实证。
"""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime import _incoming_from_nonebot_event
from plugins.bot_unified_runtime.capabilities.divination import (
    build_divination_capability,
)
from plugins.bot_unified_runtime.capabilities.today_history import (
    build_today_history_capability,
)
from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.domains.subscribe.feeds.today_history import (
    HistoryEvent,
)

_UTC = timezone.utc
PROJECT_ROOT = Path(__file__).resolve().parents[1]
INIT_PATH = PROJECT_ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"


# ---------------------------------------------------------------------------
# 打桩工具。
# ---------------------------------------------------------------------------


class _FakeBackend:
    name = "fake"
    available = True

    def __init__(self) -> None:
        self.captured: list[dict] = []

    def render_card(self, payload: dict) -> bytes | None:
        self.captured.append(payload)
        return b"fake-png"


class _BrokenBackend:
    name = "broken"
    available = True

    def render_card(self, payload: dict) -> bytes | None:
        return None


class _RaisingBackend:
    name = "raising"
    available = True

    def render_card(self, payload: dict) -> bytes | None:
        raise RuntimeError("boom")


class _StubConfig:
    def __init__(self, card_dir: str) -> None:
        self.bot_card_render_dir = card_dir


class _StubProvider:
    """固定事件桩：离线驱动 today_history 能力（不触缓存与网络）。"""

    def __init__(self, events: list[HistoryEvent]) -> None:
        self._events = events

    def get_events(self, *, force: bool = False) -> list[HistoryEvent]:
        return list(self._events)


def _message(text: str, *, sender_id: str = "u1") -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id="private:u1",
        session_type=SessionType.PRIVATE,
        sender_id=sender_id,
        plain_text=text,
        timestamp=datetime(2026, 9, 12, 13, 51, tzinfo=_UTC),
    )


def _decision(capability_id: str) -> Any:
    return BotDecision(
        request_id="req-production-wiring",
        should_respond=True,
        mode="command",
        trigger="test",
        capability_id=capability_id,
        target_scope=SessionType.PRIVATE,
        decision_reason="test",
    )


_EVENTS = [
    HistoryEvent(year="1998", title="事件甲发生"),
    HistoryEvent(year="1949", title="事件乙发生"),
]


def _history_capability(
    card_dir: str,
    backend: Any = None,
    provider: Any = None,
) -> Any:
    return build_today_history_capability(
        _StubConfig(card_dir),
        provider=provider or _StubProvider(_EVENTS),
        push_file=str(Path(card_dir) / "push.json"),
        render_backend=backend,
    )


# ---------------------------------------------------------------------------
# D2：QQ 摄取层填充 sender_display_name（card 优先 > nickname 兜底 > 空安全）。
# ---------------------------------------------------------------------------


class _FakeOnebotEvent(SimpleNamespace):
    """type().__module__ 落在本测试模块（不含 .mail/.telegram）→ 按 OneBot 归一化。"""


def _onebot_event(
    text: str = "在吗",
    *,
    group: bool = True,
    sender: Any = None,
    with_sender_attr: bool = True,
) -> SimpleNamespace:
    kwargs: dict[str, Any] = {
        "get_plaintext": lambda: text,
        "get_session_id": lambda: "group_999" if group else "10086",
        "message_id": "M-in",
        "group_id": 999 if group else None,
        "get_user_id": lambda: "u1",
        "reply_to": None,
        "reply_to_message_id": None,
        "is_tome": lambda: False,
    }
    if with_sender_attr:
        kwargs["sender"] = sender
    return _FakeOnebotEvent(**kwargs)


def test_group_card_takes_priority_over_nickname() -> None:
    incoming = _incoming_from_nonebot_event(
        _onebot_event(sender=SimpleNamespace(card="群名片甲", nickname="昵称乙")),
        bot_id="bot-1",
    )
    assert incoming.sender_display_name == "群名片甲"


def test_nickname_fallback_when_card_missing_or_blank() -> None:
    for card in (None, "", "   "):
        incoming = _incoming_from_nonebot_event(
            _onebot_event(sender=SimpleNamespace(card=card, nickname="昵称乙")),
            bot_id="bot-1",
        )
        assert incoming.sender_display_name == "昵称乙", repr(card)


def test_nickname_whitespace_is_stripped() -> None:
    incoming = _incoming_from_nonebot_event(
        _onebot_event(sender=SimpleNamespace(card=None, nickname="  昵称乙 ")),
        bot_id="bot-1",
    )
    assert incoming.sender_display_name == "昵称乙"


def test_blank_names_yield_none_not_empty_string() -> None:
    incoming = _incoming_from_nonebot_event(
        _onebot_event(sender=SimpleNamespace(card="", nickname="  ")),
        bot_id="bot-1",
    )
    assert incoming.sender_display_name is None


def test_missing_sender_attr_yields_none() -> None:
    incoming = _incoming_from_nonebot_event(
        _onebot_event(with_sender_attr=False),
        bot_id="bot-1",
    )
    assert incoming.sender_display_name is None


def test_private_event_falls_back_to_nickname() -> None:
    incoming = _incoming_from_nonebot_event(
        _onebot_event(group=False, sender=SimpleNamespace(card=None, nickname="私聊昵称")),
        bot_id="bot-1",
    )
    assert incoming.session_type is SessionType.PRIVATE
    assert incoming.sender_display_name == "私聊昵称"


def test_dict_shaped_sender_is_safe() -> None:
    """sender 形态异常（裸 dict）不炸摄取，回退 None。"""
    incoming = _incoming_from_nonebot_event(
        _onebot_event(sender={"card": "甲", "nickname": "乙"}),
        bot_id="bot-1",
    )
    assert incoming.sender_display_name is None


def test_sender_without_card_nickname_attrs_yields_none() -> None:
    incoming = _incoming_from_nonebot_event(
        _onebot_event(sender=SimpleNamespace(id="u1")),
        bot_id="bot-1",
    )
    assert incoming.sender_display_name is None


# ---------------------------------------------------------------------------
# C1：交互路径卡片真进 CapabilityResult；后端缺失/失败与纯文字逐字一致。
# ---------------------------------------------------------------------------


class TestDivinationInteractiveCard:
    def test_backend_makes_result_mixed_with_png(self, tmp_path: Path) -> None:
        backend = _FakeBackend()
        capability = build_divination_capability(
            _StubConfig(str(tmp_path)), render_backend=backend
        )
        result = capability(
            _message("八字 1998年3月2日早上7点"), _decision("bot.divination")
        )
        assert result.kind == "mixed"
        assert result.images and result.images[0]["file"]
        assert Path(result.images[0]["file"]).read_bytes() == b"fake-png"
        assert "card_rendered" in result.audit_tags

    @pytest.mark.parametrize("backend_cls", [_BrokenBackend, _RaisingBackend])
    def test_failed_backend_matches_text_version_byte_identical(
        self, tmp_path: Path, backend_cls: type
    ) -> None:
        baseline = build_divination_capability(_StubConfig(str(tmp_path)))(
            _message("八字 1998年3月2日早上7点"), _decision("bot.divination")
        )
        failed = build_divination_capability(
            _StubConfig(str(tmp_path)), render_backend=backend_cls()
        )(
            _message("八字 1998年3月2日早上7点"), _decision("bot.divination")
        )
        assert failed.body == baseline.body
        # 兜底契约：kind 保持原值（divination 能力的原值即 "divination"），不翻 mixed。
        assert failed.kind == baseline.kind
        assert failed.kind != "mixed"
        assert failed.images == []


class TestTodayHistoryInteractiveCard:
    def test_push_message_with_backend_is_mixed(self, tmp_path: Path) -> None:
        backend = _FakeBackend()
        capability = _history_capability(str(tmp_path), backend=backend)
        result = capability(
            _message("历史上的今天"), _decision("bot.today_history")
        )
        assert result.kind == "mixed"
        assert result.images and result.images[0]["file"]
        assert Path(result.images[0]["file"]).exists()
        assert "card_rendered" in result.audit_tags

    def test_no_backend_matches_text_version_byte_identical(self, tmp_path: Path) -> None:
        baseline = _history_capability(str(tmp_path))(
            _message("历史上的今天"), _decision("bot.today_history")
        )
        broken = _history_capability(str(tmp_path), backend=_BrokenBackend())(
            _message("历史上的今天"), _decision("bot.today_history")
        )
        raising = _history_capability(str(tmp_path), backend=_RaisingBackend())(
            _message("历史上的今天"), _decision("bot.today_history")
        )
        assert broken.body == raising.body == baseline.body
        assert broken.kind == raising.kind == baseline.kind == "text"
        assert broken.images == [] and raising.images == []


# ---------------------------------------------------------------------------
# C1：调度器分流——推送纯文字（render_backend=None），交互能力注入后端。
# ---------------------------------------------------------------------------


def _register_history_scheduler_with_stubs(tmp_path: Path, backend: Any) -> tuple[list[dict], dict]:
    """monkeypatch 能力工厂与 Provider，捕获 _register_today_history_scheduler 实参。"""
    from plugins.bot_unified_runtime import (
        _register_today_history_scheduler,
    )

    build_calls: list[dict] = []
    provider_calls: list[dict] = []

    def _stub_build(config: Any = None, **kwargs: Any) -> str:
        build_calls.append(kwargs)
        return f"capability#{len(build_calls)}"

    def _stub_provider(**kwargs: Any) -> str:
        provider_calls.append(kwargs)
        return f"provider#{len(provider_calls)}"

    scheduler_stub = SimpleNamespace(
        get_jobs=list,
        remove_job=lambda job_id: None,
        add_job=lambda *args, **kwargs: None,
    )
    config_stub = SimpleNamespace(
        bot_today_history_push_file=str(tmp_path / "push.json"),
        bot_download_proxy="",
        bot_today_history_cache_file=str(tmp_path / "cache.json"),
    )
    import plugins.bot_unified_runtime.domains.subscribe.capabilities.today_history as cap_module
    import plugins.bot_unified_runtime.domains.subscribe.feeds.today_history as src_module

    with (
        pytest.MonkeyPatch.context() as mp,
    ):
        mp.setattr(cap_module, "build_today_history_capability", _stub_build)
        mp.setattr(src_module, "TodayHistoryProvider", _stub_provider)
        ctx = _register_today_history_scheduler(
            scheduler=scheduler_stub,
            config=config_stub,
            pipeline=SimpleNamespace(),
            send_queue=SimpleNamespace(),
            audit_logger=SimpleNamespace(),
            receipt_repository=None,
            bot_provider=lambda: None,
            render_backend=backend,
        )
    return build_calls, ctx


def test_scheduler_splits_push_and_interactive_capabilities(tmp_path: Path) -> None:
    backend = _FakeBackend()
    build_calls, ctx = _register_history_scheduler_with_stubs(tmp_path, backend)

    assert len(build_calls) == 2, "调度器应构造推送与交互两个能力实例"
    # 产品裁定：推送能力显式 render_backend=None（保持纯文字，不依赖渲染进程）。
    push_kwargs = next(c for c in build_calls if c["render_backend"] is None)
    # 交互能力与生产同源后端出卡。
    interactive_kwargs = next(
        c for c in build_calls if c["render_backend"] is backend
    )
    # 两个实例共享同一 provider / push_file / 订阅重挂回调。
    for key in ("provider", "push_file", "on_subscriptions_changed"):
        assert push_kwargs[key] is interactive_kwargs[key], key
    # 推送订阅表路径来自 config（经 runtime_paths 解析的临时目录）。
    assert push_kwargs["push_file"] == str(tmp_path / "push.json")
    assert ctx["registered"] is True
    assert ctx["capability"] is not None
    assert ctx["interactive_capability"] is not None
    assert ctx["capability"] != ctx["interactive_capability"]


# ---------------------------------------------------------------------------
# C1：__init__.py 接线存在性（AST 断言，仿 test_finance_routing 切口）。
# ---------------------------------------------------------------------------


def _init_tree() -> ast.Module:
    return ast.parse(INIT_PATH.read_text(encoding="utf-8"), filename=str(INIT_PATH))


def _function_def(tree: ast.Module, name: str) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"__init__.py 缺函数 {name}")


def test_divination_dispatches_backend_factory_shell() -> None:
    tree = _init_tree()
    handle = _function_def(tree, "_handle_divination")
    calls = [
        call
        for call in ast.walk(handle)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "_run_simple_capability"
    ]
    assert calls, "_handle_divination 缺 _run_simple_capability 分发"
    names = [arg.id for arg in calls[0].args if isinstance(arg, ast.Name)]
    constants = [arg.value for arg in calls[0].args if isinstance(arg, ast.Constant)]
    assert "_build_divination_with_backend" in names
    assert "bot.divination" in constants


def test_scheduler_push_capability_is_explicitly_none() -> None:
    """产品裁定锁：推送能力构造显式 render_backend=None；交互能力注入同源后端。"""
    tree = _init_tree()
    scheduler_fn = _function_def(tree, "_register_today_history_scheduler")
    assignments: dict[str, ast.Call] = {}
    for node in ast.walk(scheduler_fn):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "build_today_history_capability"
        ):
            assignments[node.targets[0].id] = node.value
    assert "capability" in assignments, "推送能力构造缺失"
    assert "interactive_capability" in assignments, "交互能力构造缺失"

    def _kwarg_value(call: ast.Call, arg: str) -> ast.expr:
        for kw in call.keywords:
            if kw.arg == arg:
                return kw.value
        raise AssertionError(f"调用缺 {arg} kwarg")

    push_backend = _kwarg_value(assignments["capability"], "render_backend")
    assert isinstance(push_backend, ast.Constant) and push_backend.value is None, (
        "推送能力必须显式 render_backend=None（产品裁定：调度器保持纯文字）"
    )
    interactive_backend = _kwarg_value(assignments["interactive_capability"], "render_backend")
    assert isinstance(interactive_backend, ast.Name) and interactive_backend.id == "render_backend", (
        "交互能力必须注入闭包内同源 render_backend"
    )
    # 返回字典暴露 interactive_capability 供交互 matcher 复用。
    return_keys: list[str] = []
    for node in ast.walk(scheduler_fn):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            return_keys = [
                key.value for key in node.value.keys if isinstance(key, ast.Constant)
            ]
    assert "interactive_capability" in return_keys


def test_today_history_matcher_uses_interactive_capability() -> None:
    tree = _init_tree()
    handle = _function_def(tree, "_handle_today_history")
    subscript_keys: list[str] = []
    for node in ast.walk(handle):
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "today_ctx"
            and isinstance(node.slice, ast.Constant)
        ):
            subscript_keys.append(node.slice.value)
    assert "interactive_capability" in subscript_keys, (
        "交互 matcher 应复用 today_ctx['interactive_capability']（注入后端实例）"
    )
    # 兜底分支（调度器装配失败）也带 render_backend。
    fallback_calls = [
        call
        for call in ast.walk(handle)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "build_today_history_capability"
    ]
    assert fallback_calls, "_handle_today_history 缺直查兜底分支"
    for call in fallback_calls:
        assert any(kw.arg == "render_backend" for kw in call.keywords)
