"""统一错误报告卡回归（2026-09-13 六域批次·错误域）。

覆盖面（验收 ≥12 例）：
- 诊断收集脱敏：异常消息/栈/触发回显/配置快照的 redact_local_secrets 口径 +
  密钥键 ***；
- 卡片 payload：分区齐全（方法/路由/版本/环境/IDs）、人话区轮换、出图落盘；
- 冷却：滑动窗闸 + 冷却期降级纯文本；
- 开关关=现状：bot_error_card_enabled=false 时零动作（队列无增量）；
- 兜底：渲染失败→纯文本（栈摘录+IDs 文本版）；
- pipeline 集成：能力异常 catch 点自动带卡，回执语义不变。

全离线：fake backend + tmp 注入，无 playwright、无网络、无源码树 data/ 写入。
"""

from __future__ import annotations

import re
from concurrent.futures import Future
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import (
    IncomingMessage,
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.runtime import error_report
from plugins.bot_unified_runtime.runtime.error_report import (
    ErrorCardGate,
    ErrorCardSettings,
    build_error_report,
    build_text_fallback,
    cooldown_line,
    maybe_submit_error_card,
    render_error_card_png,
)
from plugins.bot_unified_runtime.runtime.pipeline import RuntimePipeline
from plugins.bot_unified_runtime.sender import InMemorySendQueue
from plugins.bot_unified_runtime.sender.queue import SQLiteSendRequestQueue


class _NullAuditLogger:
    def append(self, record: object) -> None:
        return


def _message(
    session_id: str = "private:u1",
    session_type: SessionType = SessionType.PRIVATE,
    plain_text: str = "/bot status",
    message_id: str = "m-1",
    **kwargs: Any,
) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id=session_id,
        session_type=session_type,
        sender_id="u1",
        plain_text=plain_text,
        message_id=message_id,
        **kwargs,
    )


def _raise_value_error() -> None:
    secret = "BOT_TOKEN=supersecretvalue sk-live1234567890abcd"
    raise ValueError(f"db unavailable at C:/Users/LancyCelestia/secrets {secret}")


def _captured_exc() -> ValueError:
    try:
        _raise_value_error()
    except ValueError as exc:
        return exc
    raise AssertionError("unreachable")


def _full_report(**overrides: Any) -> dict[str, Any]:
    report = build_error_report(
        _message(),
        "bot.market",
        _captured_exc(),
        stack_frames=8,
        config_getter=lambda name: {
            "bot_market_api_key": "must-not-leak",
            "bot_market_timeout_seconds": 6.0,
        }.get(name),
    )
    report.update(overrides)
    return report


class _FakeBackend:
    def __init__(self, png: bytes | None = b"png-bytes") -> None:
        self.png = png
        self.calls: list[dict[str, Any]] = []

    def render_card(self, payload: dict[str, Any]) -> bytes | None:
        self.calls.append(payload)
        return self.png


class _QueueStub:
    def __init__(self) -> None:
        self.requests: list[Any] = []
        # A-plus：记录每次 submit 的 kwargs（断言 ack 不带延迟、卡带延迟）。
        self.submit_calls: list[tuple[Any, dict[str, Any]]] = []

    def submit(self, send_request: Any, **kwargs: Any) -> None:
        self.requests.append(send_request)
        self.submit_calls.append((send_request, kwargs))


class _PipelineStub:
    def __init__(self) -> None:
        self.send_queue = _QueueStub()


class _ManualGate:
    """allow() 按脚本应答的桩闸（冷却语义在 ErrorCardGate 专项测）。"""

    def __init__(self, answers: list[bool]) -> None:
        self._answers = list(answers)
        self.calls: list[str] = []

    def allow(self, session_id: str) -> bool:
        self.calls.append(session_id)
        if len(self._answers) > 1:
            return self._answers.pop(0)
        return self._answers[0]


class _InlinePool:
    """同步桩渲染池：submit 即在本线程执行（两段式测试的确定性注入点）。

    契约对齐 executor：submit 返回已完成 Future（_schedule_card_render 会
    add_done_callback，None 会污染真实模块级在途集合并抛 AttributeError）。
    仅用于不关心线程几何的用例；线程几何（渲染不跑在事件循环线程）由
    test_error_card_async.py 用真实专用池专项锁定。
    """

    def __init__(self) -> None:
        self.submitted: list[Any] = []

    def submit(self, fn: Any, *args: Any, **kwargs: Any) -> Future:
        self.submitted.append(fn)
        fn(*args, **kwargs)
        done: Future = Future()
        done.set_result(None)
        return done


# ==================== 诊断收集脱敏（4） ====================
def test_report_redacts_secrets_and_local_paths() -> None:
    report = _full_report()
    blob = repr(report)
    # 密钥值/本机路径不得出现；打码占位符按 plain_text 口径。
    assert "supersecretvalue" not in blob
    assert "must-not-leak" not in blob
    assert "sk-live1234567890abcd" not in blob
    assert "C:/Users" not in blob and "C:\\Users" not in blob
    assert "BOT_TOKEN=<已隐藏>" in report["exc_message"]
    for line in report["stack_lines"]:
        assert "C:/Users" not in line


def test_trigger_echo_truncated_to_80_and_redacted() -> None:
    message = _message(
        plain_text="查一下 C:/Users/LancyCelestia/secret.txt BOT_TOKEN=aaa long " + "词" * 120
    )
    report = build_error_report(
        message, "bot.weather", _captured_exc(), config_getter=lambda name: None
    )
    echo = str(report["trigger_echo"])
    assert len(echo) <= 80
    assert echo.endswith("…")
    assert "C:/Users" not in echo and "BOT_TOKEN=aaa" not in echo


def test_config_snapshot_whitelist_and_secret_masking() -> None:
    # 白名单：只取与能力同前缀（bot_market_）的真实 Config 字段；getter 返回
    # None 的字段跳过；其他前缀（bot_chat_）不进快照。
    market_values = {
        "bot_market_enabled": True,
        "bot_market_timeout_seconds": 6.0,
        "bot_chat_timeout_seconds": 9.0,
    }
    report = build_error_report(
        _message(), "bot.market", _captured_exc(), config_getter=market_values.get
    )
    rows = {row["label"]: row["value"] for row in report["config_pairs"]}
    assert rows["bot_market_enabled"] == "True"
    assert rows["bot_market_timeout_seconds"] == "6.0"
    assert all(label.startswith("bot_market_") for label in rows)
    # 密钥类命名一律 ***（真实密钥字段：bot.search 的 API key 族）。
    search_report = build_error_report(
        _message(), "bot.search", _captured_exc(),
        config_getter=lambda name: "leak-me",
    )
    search_rows = {
        row["label"]: row["value"] for row in search_report["config_pairs"]
    }
    assert search_rows
    assert set(search_rows.values()) == {"***"}
    assert "leak-me" not in repr(search_report)


def test_stack_frames_setting_and_innermost_function() -> None:
    deep_exc = _captured_exc()
    report = build_error_report(
        _message(), "bot.market", deep_exc, stack_frames=2,
        config_getter=lambda name: None,
    )
    assert len(report["stack_lines"]) == 2
    assert report["method_pairs"][1] == {"label": "函数", "value": "_raise_value_error"}
    # 帧数钳位：缺省 8，超上限钳 30（resolver 经 env 注入验证）。
    monkey = pytest.MonkeyPatch()
    try:
        monkey.setenv("BOT_ERROR_CARD_STACK_FRAMES", "99")
        monkey.delenv("BOT_ERROR_CARD_ENABLED", raising=False)
        monkey.delenv("BOT_ERROR_CARD_COOLDOWN_SECONDS", raising=False)
        settings = error_report._resolve_settings()
        assert settings.stack_frames == 30
        monkey.setenv("BOT_ERROR_CARD_STACK_FRAMES", "abc")
        assert error_report._resolve_settings().stack_frames == 8
        monkey.setenv("BOT_ERROR_CARD_COOLDOWN_SECONDS", "5")
        monkey.setenv("BOT_ERROR_CARD_ENABLED", "false")
        settings = error_report._resolve_settings()
        assert settings.enabled is False
        assert settings.cooldown_seconds == 5
    finally:
        monkey.undo()


# ==================== 卡片 payload（3） ====================
def test_report_payload_sections_complete() -> None:
    message = _message()
    report = build_error_report(
        message, "bot.market", _captured_exc(),
        config_getter=lambda name: None,
    )
    assert report["method_pairs"][0] == {"label": "能力", "value": "bot.market"}
    assert report["method_pairs"][2] == {"label": "路由", "value": "RouteKind.MARKET"}
    versions = {row["label"]: row["value"] for row in report["version_pairs"]}
    assert {"NoneBot", "OneBot 适配器", "插件包", "构建", "运行时长"} <= set(versions)
    assert re.search(r"\d+ 小时 \d+ 分|\d+ 分钟", versions["运行时长"])
    env = {row["label"]: row["value"] for row in report["env_pairs"]}
    assert env["平台"] == "qq"
    assert env["会话"] == "私聊"
    ids = {row["label"]: row["value"] for row in report["id_pairs"]}
    assert ids["message_id"] == "m-1"
    assert ids["request_id"] == message.request_id
    assert ids["告警关联"] == message.debug_id
    # 群聊会话标注群号。
    group_report = build_error_report(
        _message("group:g1", SessionType.GROUP, group_id="g1"),
        "bot.market",
        _captured_exc(),
        config_getter=lambda name: None,
    )
    group_env = {row["label"]: row["value"] for row in group_report["env_pairs"]}
    assert group_env["会话"] == "群聊 g1"


def test_human_text_persona_tone_and_rotation() -> None:
    first = build_error_report(
        _message(), "bot.market", _captured_exc(), config_getter=lambda name: None
    )["human_text"]
    second = build_error_report(
        _message(), "bot.market", _captured_exc(), config_getter=lambda name: None
    )["human_text"]
    assert "ValueError" in first
    # 禁愧疚腔/禁攻击性（红线词不出现）。
    for banned in ("抱歉", "对不起", "笨", "滚"):
        assert banned not in first
    # 同会话轮换：连发不重复。
    assert first != second


def test_render_png_writes_file_with_stable_digest(tmp_path: Path) -> None:
    backend = _FakeBackend()
    report = _full_report()
    path = render_error_card_png(
        report, backend=backend, card_dir=str(tmp_path)
    )
    assert path and Path(path).is_file()
    assert Path(path).name.startswith("error_")
    # 同 payload 同文件名（digest 稳定），重复渲染覆盖不堆积。
    again = render_error_card_png(report, backend=backend, card_dir=str(tmp_path))
    assert Path(again).name == Path(path).name
    assert len(list(tmp_path.glob("error_*.png"))) == 1
    # 渲染失败（后端返回 None）→ 空串回退。
    assert render_error_card_png(
        report, backend=_FakeBackend(png=None), card_dir=str(tmp_path)
    ) == ""


# ==================== 冷却（2） ====================
def test_gate_sliding_window_allows_then_blocks() -> None:
    ticks = iter([0.0, 1.0, 60.0, 61.0])
    gate = ErrorCardGate(60.0, clock=lambda: next(ticks))
    assert gate.allow("s1") is True
    assert gate.allow("s1") is False  # 窗口内
    assert gate.allow("s1") is True  # 60s 后窗口滑出
    assert gate.allow("s1") is False
    # 不同会话互不影响。
    gate2 = ErrorCardGate(60.0, clock=lambda: 0.0)
    assert gate2.allow("s1") is True
    assert gate2.allow("s2") is True


def test_submit_degrades_to_text_within_cooldown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        error_report, "_stable_report_digest", lambda report: "fixeddigest"
    )
    settings = ErrorCardSettings(enabled=True, cooldown_seconds=60, stack_frames=8)
    # 首发在窗口外：两段式——先即时文本回执（ack），再后台补发混合卡（图+人话区）。
    inline_pool = _InlinePool()
    first = _PipelineStub()
    maybe_submit_error_card(
        first, _message(), "bot.market", _captured_exc(),
        settings=settings, gate=_ManualGate([True]),
        backend=_FakeBackend(), card_dir=str(tmp_path),
        render_pool=inline_pool,
    )
    assert len(first.send_queue.requests) == 2
    ack = first.send_queue.requests[0]
    assert ack.content.content_type == "text"
    assert "ValueError" in ack.content.content_ref["text"]
    assert "随后补发" in ack.content.content_ref["text"]
    assert ack.dedupe_key.endswith(":ack")
    card = first.send_queue.requests[1]
    assert card.request_id == f"{ack.request_id}-card"
    assert card.capability_id == "bot.error_report"
    assert card.content.content_type == "mixed"
    assert card.content.content_ref["parts"][0]["type"] == "image"
    assert (tmp_path / "error_fixeddigest.png").is_file()
    assert "source:bot.market" in card.audit_tags
    assert card.dedupe_key.startswith("error_report:bot.market:")
    assert card.dedupe_key.endswith(":card")
    # 冷却期：第二发降级为一句纯文本（守岸人口吻），无卡、无落盘、无渲染排程。
    second = _PipelineStub()
    second_pool = _InlinePool()
    maybe_submit_error_card(
        second, _message(message_id="m-2"), "bot.market", _captured_exc(),
        settings=settings, gate=_ManualGate([False]), backend=_FakeBackend(),
        render_pool=second_pool,
    )
    assert len(second.send_queue.requests) == 1
    degraded = second.send_queue.requests[0]
    assert degraded.content.content_type == "text"
    assert "ValueError" in degraded.content.content_ref["text"]
    assert "刚才那张卡" in degraded.content.content_ref["text"]
    assert second_pool.submitted == []


# ==================== 开关关=现状（1） ====================
def test_disabled_settings_submit_is_noop() -> None:
    pipeline = _PipelineStub()
    backend = _FakeBackend()
    maybe_submit_error_card(
        pipeline, _message(), "bot.market", _captured_exc(),
        settings=ErrorCardSettings(enabled=False, cooldown_seconds=60, stack_frames=8),
        gate=_ManualGate([True]),
        backend=backend,
    )
    assert pipeline.send_queue.requests == []
    assert backend.calls == []  # 零渲染动作（字节级现状）


# ==================== 兜底（2） ====================
def test_build_text_fallback_contains_stack_and_ids() -> None:
    fallback = build_text_fallback(_full_report())
    assert fallback.startswith("[运行异常] ValueError:")
    assert "栈摘录" in fallback
    assert "_raise_value_error" in fallback
    assert "IDs 与时间" in fallback
    assert "message_id=m-1" in fallback
    # 兜底文本同样脱敏。
    assert "supersecretvalue" not in fallback


def test_submit_falls_back_to_text_when_render_fails() -> None:
    inline_pool = _InlinePool()
    pipeline = _PipelineStub()
    maybe_submit_error_card(
        pipeline, _message(), "bot.market", _captured_exc(),
        settings=ErrorCardSettings(enabled=True, cooldown_seconds=60, stack_frames=8),
        gate=_ManualGate([True]),
        backend=_FakeBackend(png=None),  # 渲染失败
        render_pool=inline_pool,
    )
    # 两段式：ack 文本先行 + 渲染失败补发全量诊断文本（诊断完整性不丢）。
    assert len(pipeline.send_queue.requests) == 2
    ack = pipeline.send_queue.requests[0]
    assert ack.content.content_type == "text"
    fallback = pipeline.send_queue.requests[1]
    assert fallback.content.content_type == "text"
    assert "栈摘录" in fallback.content.text_fallback
    assert fallback.content.content_ref["text"] == fallback.content.text_fallback
    assert fallback.dedupe_key.endswith(":card")
    assert "text_only" in fallback.audit_tags


# ==================== pipeline 集成（2） ====================
def test_pipeline_exception_submits_error_card(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        error_report,
        "_resolve_settings",
        lambda: ErrorCardSettings(enabled=True, cooldown_seconds=60, stack_frames=8),
    )
    monkeypatch.setattr(error_report, "_module_gate", lambda cd: _ManualGate([True]))
    # 两段式：渲染段注入同步桩池（线程几何由 test_error_card_async.py 专测）。
    inline_pool = _InlinePool()
    monkeypatch.setattr(error_report, "_get_render_pool", lambda: inline_pool)
    fake_png = tmp_path / "error_fake.png"
    fake_png.write_bytes(b"png")

    def fake_render(report: Any, *, backend: Any = None, card_dir: Any = None) -> str:
        return str(fake_png)

    monkeypatch.setattr(error_report, "render_error_card_png", fake_render)
    pipeline = RuntimePipeline(
        send_queue=InMemorySendQueue(audit_logger=_NullAuditLogger()),
        audit_logger=_NullAuditLogger(),
    )

    def failing_capability(message: IncomingMessage, decision: Any) -> Any:
        raise _captured_exc()

    receipt = pipeline.handle(_message(), failing_capability, "bot.market")
    # 回执语义不变：FAILED_FINAL（既有 internal_error 行为保持）。
    assert receipt.state is ReceiptState.FAILED_FINAL
    assert receipt.public_message == ""
    # 两段式下发：文本回执（request_id 沿用原 id，matcher 内联首投可寻）+ 诊断卡。
    queue = pipeline.send_queue
    assert len(queue.sent_requests) == 2
    ack_request, card_request = queue.sent_requests
    assert ack_request.capability_id == "bot.error_report"
    assert ack_request.content.content_type == "text"
    assert ack_request.request_id  # 原 id 形态（非派生）
    assert not ack_request.request_id.endswith("-card")
    assert card_request.capability_id == "bot.error_report"
    assert card_request.content.content_type == "mixed"
    assert card_request.target_id == "u1"
    assert card_request.request_id == f"{ack_request.request_id}-card"


def test_pipeline_group_failure_receipt_silent_and_card_sent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        error_report,
        "_resolve_settings",
        lambda: ErrorCardSettings(enabled=True, cooldown_seconds=60, stack_frames=8),
    )
    monkeypatch.setattr(error_report, "_module_gate", lambda cd: _ManualGate([True]))
    inline_pool = _InlinePool()
    monkeypatch.setattr(error_report, "_get_render_pool", lambda: inline_pool)
    fake_png = tmp_path / "error_fake.png"
    fake_png.write_bytes(b"png")

    def fake_render(report: Any, *, backend: Any = None, card_dir: Any = None) -> str:
        return str(fake_png)

    monkeypatch.setattr(error_report, "render_error_card_png", fake_render)
    pipeline = RuntimePipeline(
        send_queue=InMemorySendQueue(audit_logger=_NullAuditLogger()),
        audit_logger=_NullAuditLogger(),
    )

    def failing_capability(message: IncomingMessage, decision: Any) -> Any:
        raise _captured_exc()

    message = _message("group:g1", SessionType.GROUP, group_id="g1")
    receipt = pipeline.handle(message, failing_capability, "bot.market")
    # 群聊既有静默语义不变（回执 public_message 空），诊断卡两段式照发（受冷却）。
    assert receipt.state is ReceiptState.FAILED_FINAL
    assert receipt.public_message == ""
    ack_request, card_request = pipeline.send_queue.sent_requests
    assert ack_request.target_id == "g1"
    assert card_request.target_id == "g1"
    assert card_request.content.content_type == "mixed"
    assert cooldown_line("ValueError").startswith("又有一条指令出了岔子")


# ==================== 钩子自身 fail-open ====================
def test_pipeline_hook_survives_error_report_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_submit(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("hook exploded")

    monkeypatch.setattr(error_report, "maybe_submit_error_card", broken_submit)
    pipeline = RuntimePipeline(
        send_queue=InMemorySendQueue(audit_logger=_NullAuditLogger()),
        audit_logger=_NullAuditLogger(),
    )

    def failing_capability(message: IncomingMessage, decision: Any) -> Any:
        raise RuntimeError("boom")

    receipt = pipeline.handle(_message(), failing_capability, "bot.market")
    assert receipt.state is ReceiptState.FAILED_FINAL
    assert pipeline.send_queue.sent_requests == []


# ==================== A-plus 补发延迟（deliver_after） ====================
def _queue_request(request_id: str, dedupe_key: str) -> SendRequest:
    """队列级行为测试用最小 SendRequest（离线，无渲染）。"""
    rendered = RenderedOutput(
        request_id=request_id,
        content_type="text",
        content_ref={"text": "诊断卡补发正文"},
        text_fallback="诊断卡补发正文",
        privacy_level=PrivacyLevel.PERSONAL,
    )
    return SendRequest(
        request_id=request_id,
        session_id="private:u1",
        target_scope=SessionType.PRIVATE,
        target_id="u1",
        capability_id="bot.error_report",
        content=rendered,
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key=dedupe_key,
        cooldown_key="bot.error_report:private:u1",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="default",
    )


def test_queue_deliver_after_defers_claim_until_due(tmp_path: Path) -> None:
    """A-plus：带 deliver_after 的入队，到点前 worker 不认领（不投递），到点后接管。"""
    queue = SQLiteSendRequestQueue(tmp_path / "q.sqlite3", _NullAuditLogger())
    base = datetime.now(timezone.utc)
    due = base + timedelta(seconds=3)
    queue.submit(
        _queue_request("req-err-card", "dedupe-err-card"),
        now=base,
        deliver_after=due,
    )
    # 到点前：claim_due / list_due 都拿不到该行 → worker 不投递。
    assert queue.claim_due(now=base + timedelta(seconds=2)) == []
    assert queue.list_due(now=base + timedelta(seconds=2)) == []
    # 到点后：worker 正常接管（后台渲染线程崩溃也不丢卡，跨重启续发语义不变）。
    claimed = queue.claim_due(now=due + timedelta(seconds=1))
    assert [entry.send_request.request_id for entry in claimed] == ["req-err-card"]


def test_queue_default_submit_keeps_inline_grace(tmp_path: Path) -> None:
    """A-plus：缺省（不传 deliver_after）=现状——60s 内联宽限期内 worker 不认领。"""
    queue = SQLiteSendRequestQueue(tmp_path / "q.sqlite3", _NullAuditLogger())
    base = datetime.now(timezone.utc)
    queue.submit(_queue_request("req-plain", "dedupe-plain"), now=base)
    # 宽限期（60s）内立即认领拿不到，与 A1 语义字节级一致。
    assert queue.claim_due(now=base + timedelta(seconds=30)) == []
    assert queue.list_due(now=base + timedelta(seconds=30)) == []
    claimed = queue.claim_due(now=base + timedelta(seconds=120))
    assert [entry.send_request.request_id for entry in claimed] == ["req-plain"]


def test_error_card_resubmit_passes_deliver_after(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A-plus：补发请求（:card）带 deliver_after≈+3s；即时 ack 不带（零变化）。"""
    monkeypatch.setattr(
        error_report, "_stable_report_digest", lambda report: "fixeddigest"
    )
    settings = ErrorCardSettings(enabled=True, cooldown_seconds=60, stack_frames=8)
    pipeline = _PipelineStub()
    maybe_submit_error_card(
        pipeline, _message(), "bot.market", _captured_exc(),
        settings=settings, gate=_ManualGate([True]),
        backend=_FakeBackend(), card_dir=str(tmp_path),
        render_pool=_InlinePool(),
    )
    assert len(pipeline.send_queue.requests) == 2
    ack_request, card_request = pipeline.send_queue.requests
    # 第一段 ack：无 deliver_after（缺省路径字节级现状）。
    assert ack_request.dedupe_key.endswith(":ack")
    assert pipeline.send_queue.submit_calls[0][1] == {}
    # 第二段卡：deliver_after = 提交时刻 + ~3s（aware UTC；上限含执行抖动）。
    assert card_request.dedupe_key.endswith(":card")
    deliver_after = pipeline.send_queue.submit_calls[1][1]["deliver_after"]
    assert deliver_after.tzinfo is timezone.utc
    delay = (deliver_after - datetime.now(timezone.utc)).total_seconds()
    assert 0 <= delay <= 5
