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
例外（E-13）：文件尾真渲染烟测默认跳过，BOT_ERRCARD_SMOKE=1 才用真
playwright 出极小样本 PNG（仍不联网）。
"""

from __future__ import annotations

import os
import platform
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
from plugins.bot_unified_runtime.domains.chat_reply.runtime.pipeline import (
    RuntimePipeline,
)
from plugins.bot_unified_runtime.domains.ops.monitor import error_report
from plugins.bot_unified_runtime.domains.ops.monitor.error_report import (
    ErrorCardGate,
    ErrorCardSettings,
    build_error_report,
    build_text_fallback,
    cooldown_line,
    maybe_submit_error_card,
    render_error_card_png,
)
from plugins.bot_unified_runtime.domains.transport.sender import InMemorySendQueue
from plugins.bot_unified_runtime.domains.transport.sender.queue import (
    SQLiteSendRequestQueue,
)


class _NullAuditLogger:
    def append(self, record: object) -> None:
        return


def _message(
    session_id: str = "private:u1",
    session_type: SessionType = SessionType.PRIVATE,
    plain_text: str = "/bot status",
    message_id: str = "m-1",
    platform_name: str = "qq",
    **kwargs: Any,
) -> IncomingMessage:
    # 受众分级门（W9）之后「全量诊断」只在**管理员私聊**态给。本文件的既有锁测的
    # 全是那一档（栈帧/配置键名/IDs/兜底文本），故缺省把 u1 建模成中央角色事实里的
    # admin——`sender_roles` 就是流水线 `_prepare` 写入的那份真身
    # （`roles.RoleSettings.resolve_roles` 的产物），不是本文件自造的权限。
    # 群态与非管理态的裁剪由文件尾的 W9 双向锁专测（它们也吃这个桩，显式覆盖即可）。
    kwargs.setdefault("sender_roles", ["admin"])
    return IncomingMessage(
        platform=platform_name,
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
    # 密钥类命名一律 ***（真实密钥字段：bot.search 的 API key 族）。FIX2：
    # SEARCH 席 ACG 六键（enabled/timeout/max 等非密钥命名）随能力扩展进
    # 快照白名单——「search 全键皆密钥」旧前提过时，掩码只对密钥命名键生效，
    # 非密钥键明文展示（值走 redact_local_secrets 兜底）。
    search_report = build_error_report(
        _message(), "bot.search", _captured_exc(),
        config_getter=lambda name: (
            "leak-me" if name.endswith("_api_key") else "on"
        ),
    )
    search_rows = {
        row["label"]: row["value"] for row in search_report["config_pairs"]
    }
    assert search_rows
    api_key_rows = {
        label: value for label, value in search_rows.items()
        if label.endswith("_api_key")
    }
    assert api_key_rows and set(api_key_rows.values()) == {"***"}
    acg_rows = {
        label: value for label, value in search_rows.items()
        if label.startswith("bot_search_acg_")
    }
    assert len(acg_rows) == 6 and set(acg_rows.values()) == {"on"}
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
    # ⑥适配器版本现在由「适配器」那一行给（全景列表含 nonebot-adapter-onebot 版本），
    # 单列一行与它撞车（2026-09-25 真卡评审：合并同类项）。
    assert {"NoneBot", "插件包", "构建", "运行时长"} <= set(versions)
    # 适配器改成一行一个（2026-09-25 点名）：不再有单条「适配器」汇总行。
    assert "适配器" not in versions
    assert any(k.startswith("适配器 · ") for k in versions), sorted(versions)
    assert any(k.endswith("onebot") for k in versions)
    assert re.search(r"\d+ 小时 \d+ 分|\d+ 分钟", versions["运行时长"])
    env = {row["label"]: row["value"] for row in report["env_pairs"]}
    assert env["平台"] == "qq"
    # 形态与会话键并成 IDs 里的一行「会话」，别在两处各写一遍（评审：复读三次）。
    assert "会话" not in env
    assert {r["label"]: r["value"] for r in report["id_pairs"]}["会话"].startswith("私聊")
    ids = {row["label"]: row["value"] for row in report["id_pairs"]}
    assert ids["message_id"] == "m-1"
    assert ids["request_id"] == message.request_id
    assert ids["告警关联"] == message.debug_id
    # 群聊会话标注群号——W9 受众分级后群态那张卡**不再带 IDs 节**，这一格改由
    # 告警面锁（`test_alert_error_card.py::test_issue_card_session_identity_rows_follow_the_caller`
    # 走 `_session_label_for(GROUP, group_id)` 同一真身）继续执法；这里锁的是分级本身。
    group_report = build_error_report(
        _message("group:g1", SessionType.GROUP, group_id="g1"),
        "bot.market",
        _captured_exc(),
        config_getter=lambda name: None,
    )
    assert group_report["env_pairs"] == []
    assert {row["label"] for row in group_report["id_pairs"]} == {"触发时刻"}
    assert group_report["stack_lines"] == []


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


@pytest.mark.parametrize("line", error_report._COOLDOWN_LINES)
def test_submit_degrades_to_text_within_cooldown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, line: str
) -> None:
    monkeypatch.setattr("random.choice", lambda pool: line)
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
    # 审查 E-12：卡复用原 request_id（不再派生 "-card"），dedupe 靠 ":card" 后缀。
    assert card.request_id == ack.request_id
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
    assert degraded.content.content_ref["text"] == line.format(exc="ValueError")
    assert degraded.content.text_fallback == degraded.content.content_ref["text"]
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
    # goal-7 说人话波：机读节题中文化，`IDs 与时间` 旧串退役（单一真身＝
    # error_report 兜底节题表 + bridge._CARD_TEXT["static_err_32"]，两面同词）。
    assert "标识与时间" in fallback
    assert "IDs 与时间" not in fallback
    assert "message_id=m-1" in fallback
    # 兜底文本同样脱敏。
    assert "supersecretvalue" not in fallback


def test_help_text_wording_honest_card_not_screenshot() -> None:
    """E-11：指引句如实口径——卡图为自动生成诊断卡（非控制台截图），完整栈
    指向 runtime 事件日志；今日已入库字段族（版本/系统/配置快照/IDs）在句中
    点名自洽。纯文本兜底用文字版口径（明示「没带图」），不复用卡片「这张图」。
    """
    report = _full_report()
    help_text = str(report["help_text"])
    # 旧指引句「把这张卡截图发给创造者」废除；如实写明「不是控制台截图」。
    assert "把这张卡截图" not in help_text
    assert "不是控制台截图" in help_text
    assert "自动生成" in help_text and "不是控制台截图" in help_text
    assert "runtime 事件日志" in help_text
    for token in ("runtime 事件日志",):
        assert token in help_text
    # 2026-09-25 真卡评审：卡是按数据显隐的，旧句声称「版本、系统、配置快照和
    # IDs 都在卡上」而空节整节不出＝无效引导。这三个词现在只准出现在
    # "日志里"那个语境，不再被当作卡上内容的承诺。
    assert "都在卡上" not in help_text
    fallback = build_text_fallback(report)
    assert "截图" not in fallback
    assert "这张图" not in fallback  # 无图场景不复用卡片口径。
    assert "没能出" in fallback  # 2026-09-25 措辞重排
    assert "runtime 事件日志" in fallback


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
    """Mock 路径行为（E-13 声明）：render_error_card_png 打桩返回假 PNG 路径，
    只锁 pipeline 集成/两段式下发语义；真实出图烟测见文件尾
    （BOT_ERRCARD_SMOKE=1）。"""
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
    # 审查 E-12：卡与文本回执同 request_id（同一回执寻址路径），互不吞并靠
    # dedupe_key 后缀（:ack / :card）区分。
    assert card_request.request_id == ack_request.request_id


def test_pipeline_group_failure_receipt_silent_and_card_sent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Mock 路径行为（E-13 声明）：render_error_card_png 打桩返回假 PNG 路径，
    只锁群聊静默回执+诊断卡照发语义；真实出图烟测见文件尾。"""
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
    from plugins.bot_unified_runtime.domains.ops.monitor import error_report as _er

    assert cooldown_line("ValueError") in {
        variant.format(exc="ValueError") for variant in _er._COOLDOWN_LINES
    }
    assert len(_er._COOLDOWN_LINES) >= 10


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


def test_plugin_version_resolves_from_pyproject() -> None:
    """E-01 回归：插件源码运行、无 pip 元数据，版本必须能从 pyproject 取到。"""
    from pathlib import Path

    import tomllib

    from plugins.bot_unified_runtime.domains.ops.monitor.error_report import (
        _plugin_version,
    )

    expected = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text("utf-8")
    )["project"]["version"]
    assert _plugin_version() == expected != "unknown"


# ==================== 审查补全（E-03/E-04/E-05/E-06/E-07/E-10，2026-09-14） ====================
def test_version_pairs_runtime_facts_and_adapter_list() -> None:
    """E-03：版本区补 Python / 系统 / 适配器实现全景，且进纯文本兜底。"""
    report = build_error_report(
        _message(), "bot.market", _captured_exc(), config_getter=lambda name: None
    )
    versions = {row["label"]: row["value"] for row in report["version_pairs"]}
    assert {"Python", "系统"} <= set(versions)
    # 适配器一行一个（2026-09-25 点名：顿号长串读不动）。
    assert any(k.startswith("适配器 · ") for k in versions), sorted(versions)
    assert versions["Python"].startswith("3.")
    assert platform.system().lower() in versions["系统"].lower()
    # venv 实装 nonebot-adapter-{onebot,telegram,mail,console,qq}，顿号合并列出。
    assert all(v and v != "unknown" for k, v in versions.items() if k.startswith("适配器 · "))
    assert any(k.endswith("onebot") for k in versions), sorted(versions)
    # 通用 pairs 渲染：新字段自动进纯文本兜底（结构零改动）。
    fallback = build_text_fallback(report)
    assert "Python=" in fallback
    assert "适配器 ·" in fallback


def test_adapter_dist_label_fail_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """E-03 fail-open：发行版枚举抛错整体退 unknown，诊断卡构建不抛。"""

    def boom() -> Any:
        raise RuntimeError("scan failed")

    monkeypatch.setattr(error_report.metadata, "distributions", boom)
    error_report._adapter_dists_cache_clear()
    try:
        assert error_report._adapter_dists_label() == "unknown"
    finally:
        # 缓存是进程级契约：测完复位，避免把 unknown 留给同进程后续用例。
        error_report._adapter_dists_cache_clear()


def test_protocol_and_connection_use_explicit_mapping() -> None:
    """E-04/E-05：协议/通信按显式映射精确匹配并带实现名；"nonebot" 不再被子串巧合误判成 OneBot。"""
    assert error_report._protocol_label("onebot") == "OneBot V11（SnowLuma）"
    assert error_report._protocol_label("onebot.v11") == "OneBot V11（SnowLuma）"
    assert error_report._protocol_label("telegram") == "Telegram Bot API"
    assert error_report._protocol_label("mail") == "IMAP/SMTP"
    assert error_report._protocol_label("console") == "本地控制台"
    # 生产兜底 adapter 名 "nonebot"：精确查表查不到 → unknown（旧子串逻辑误报 OneBot V11）。
    assert error_report._protocol_label("nonebot") == "unknown"
    assert error_report._protocol_label("") == "unknown"
    assert error_report._connection_mode("telegram") == "Bot API 轮询"
    assert error_report._connection_mode("mail") == "SMTP"
    assert error_report._connection_mode("console") == "本地"
    assert error_report._connection_mode("nonebot") == "unknown"
    # env_pairs 集成：协议行带实现名标注。
    report = build_error_report(
        _message(), "bot.market", _captured_exc(), config_getter=lambda name: None
    )
    env = {row["label"]: row["value"] for row in report["env_pairs"]}
    assert env["协议"] == "OneBot V11（SnowLuma）"


def test_id_pairs_add_sender_bot_group_ids() -> None:
    """E-06：sender_id/bot_id/group_id 有则显示、无则整行省略。

    W9 受众分级门（2026-10-01）之后这些行只在**全量档**存在，所以"群号那一行"改由
    告警卡面锁（`test_alert_error_card.py::test_issue_card_session_identity_rows_follow_the_caller`
    ——同吃 `_rows`/`_kv` 的省略规则，且告警载荷走管理员目标、本就是全量档）；
    异常卡这边锁的是「有则显示（管理员私聊档）」「无则整行不出」「群态那张根本不配
    拥有 ids 节」三件事。
    """
    # 私聊无群号 → group_id 行省略；兜底文本自动携带（通用 pairs）。
    private_report = build_error_report(
        _message(), "bot.market", _captured_exc(), config_getter=lambda name: None
    )
    private_ids = {row["label"] for row in private_report["id_pairs"]}
    assert "group_id" not in private_ids
    assert {"sender_id", "bot_id", "message_id"} <= private_ids
    assert "sender_id=u1" in build_text_fallback(private_report)
    # 群态：IDs 节只剩「触发时刻」一枚（内部关联 id 不外泄）。
    group_report = build_error_report(
        _message("group:g1", SessionType.GROUP, group_id="g1"),
        "bot.market",
        _captured_exc(),
        config_getter=lambda name: None,
    )
    assert {row["label"] for row in group_report["id_pairs"]} == {"触发时刻"}


def test_trigger_time_prefers_message_timestamp() -> None:
    """E-07：触发时刻优先 message.timestamp（摄取时刻），label 改「触发时刻」。"""
    ts = datetime(2026, 9, 14, 8, 30, 5, tzinfo=timezone.utc)
    message = _message(timestamp=ts)
    report = build_error_report(
        message, "bot.market", _captured_exc(), config_getter=lambda name: None
    )
    ids = {row["label"]: row["value"] for row in report["id_pairs"]}
    # 2026-09-25 真卡评审：全卡一个时刻格式（`%Y-%m-%d %H:%M:%S UTC±HH:MM`），
    # 顶行空格时区、底行 ISO `T` 的两种写法会被读成两个时刻。
    assert ids["触发时刻"] == error_report.format_clock_label(ts)


def test_trigger_time_falls_back_to_now_on_bad_timestamp() -> None:
    """E-07 fail-open：timestamp 不可解析/缺失退当前时刻，绝不抛错。"""
    # model_copy(update=...) 不做校验：故意把 datetime 字段换成坏字符串。
    broken = _message().model_copy(update={"timestamp": "not-a-date"})
    label = error_report._trigger_time_label(broken)
    parsed = datetime.strptime(label, "%Y-%m-%d %H:%M:%S UTC%z")
    assert abs(datetime.now().astimezone() - parsed) < timedelta(seconds=10)

    class _Missing:
        timestamp = None

    missing = error_report._trigger_time_label(_Missing())  # type: ignore[arg-type]
    assert "UTC" in missing and "T+" not in missing  # 统一格式：不再是 ISO 的 T 分隔 + 裸偏移


def test_config_snapshot_global_fallback_when_prefix_sparse() -> None:
    """E-10：前缀命中不足 3 条时补全局运行键（值走既有脱敏管线）；前缀充足不补。"""
    values = {
        "bot_error_card_enabled": True,
        "bot_quiet_hours_enabled": False,
        "bot_reminder_enabled": True,
    }
    report = build_error_report(
        _message(), "bot.status", _captured_exc(), config_getter=values.get
    )
    rows = {row["label"]: row["value"] for row in report["config_pairs"]}
    assert rows["bot_error_card_enabled"] == "True"
    assert rows["bot_quiet_hours_enabled"] == "False"
    assert rows["bot_reminder_enabled"] == "True"
    # 前缀充足（≥3 条）→ 不补全局键，快照仍是纯同前缀白名单。
    market_values = {
        "bot_market_enabled": True,
        "bot_market_retry_on_empty": True,
        "bot_market_timeout_seconds": 6.0,
        "bot_market_cache_seconds": 60.0,
    }
    full = build_error_report(
        _message(), "bot.market", _captured_exc(), config_getter=market_values.get
    )
    labels = {row["label"] for row in full["config_pairs"]}
    assert labels == set(market_values)
    # 兜底键的值同样过 redact_local_secrets（本机路径打码）。
    leaky = build_error_report(
        _message(),
        "bot.status",
        _captured_exc(),
        config_getter=lambda name: (
            "C:/Users/LancyCelestia/leak"
            if name == "bot_error_card_cooldown_seconds"
            else None
        ),
    )
    assert "C:/Users" not in repr(leaky["config_pairs"])


def test_long_config_value_is_clamped_and_says_so() -> None:
    """真卡实锤（2026-09-25 15:57 那张 tts 探针告警）：``bot_tts_ref_audios`` 存的是
    整段参考语料，600+ 字原样上卡＝一屏正文，把该看的挤没了。钳住可以，
    **静默钳不行**——必须标出还有多少字没显示，否则读卡的人以为那就是全部值。
    """
    long_value = "参考语音" + "甲" * 400

    report = build_error_report(
        _message(),
        "bot.tts",
        _captured_exc(),
        config_getter=lambda name: long_value if name == "bot_tts_ref_audios" else None,
    )
    rows = {row["label"]: row["value"] for row in report["config_pairs"]}
    shown = rows["bot_tts_ref_audios"]
    assert len(shown) < len(long_value), "长值没被钳住"
    assert shown.endswith("）") and "字未显示" in shown, f"截断没标出未显示字数: {shown!r}"
    omitted = len(long_value) - error_report._CONFIG_VALUE_MAX_CHARS
    assert f"另有 {omitted} 字未显示" in shown
    # 短值一个字符都不许动（不因为加了钳制就顺手改写正常值）。
    short = build_error_report(
        _message(),
        "bot.tts",
        _captured_exc(),
        config_getter=lambda name: "private" if name == "bot_tts_ref_audios" else None,
    )
    assert {r["label"]: r["value"] for r in short["config_pairs"]}["bot_tts_ref_audios"] == "private"


# ==================== 审查 E-12（2026-09-14）：卡复用原 request_id ====================
def test_card_followup_reuses_original_request_id_with_unique_dedupe(
    tmp_path: Path,
) -> None:
    """E-12 ①：卡/降级文本两分支都复用原 request_id（不再派生 "-card"）；
    去重靠 dedupe_key 的 ":card" 后缀——与文本回执 ":ack" 三态互斥不撞车。"""
    settings = ErrorCardSettings(enabled=True, cooldown_seconds=60, stack_frames=8)
    message = _message()
    # 渲染成功分支（mixed 卡）。
    success = _PipelineStub()
    maybe_submit_error_card(
        success, message, "bot.market", _captured_exc(),
        settings=settings, gate=_ManualGate([True]),
        backend=_FakeBackend(), card_dir=str(tmp_path),
        render_pool=_InlinePool(),
    )
    assert len(success.send_queue.requests) == 2
    ack, card = success.send_queue.requests
    assert ack.request_id == message.request_id  # 文本回执沿原 id（既有契约）。
    assert card.request_id == message.request_id  # E-12：卡复用同一 id。
    assert card.dedupe_key.endswith(":card")
    assert ack.dedupe_key.endswith(":ack")
    assert card.dedupe_key != ack.dedupe_key  # 后缀互斥：去重互不吞并。
    # 渲染失败分支（text_only 兜底补发）同样复用原 id。
    fallback = _PipelineStub()
    maybe_submit_error_card(
        fallback, message, "bot.market", _captured_exc(),
        settings=settings, gate=_ManualGate([True]),
        backend=_FakeBackend(png=None), card_dir=str(tmp_path),
        render_pool=_InlinePool(),
    )
    assert len(fallback.send_queue.requests) == 2
    assert fallback.send_queue.requests[1].request_id == message.request_id
    assert fallback.send_queue.requests[1].dedupe_key.endswith(":card")


def test_queue_accepts_ack_and_card_sharing_request_id(tmp_path: Path) -> None:
    """E-12 ②：文本回执与卡同 request_id 时，队列去重只认 dedupe_key
    （SQLite ON CONFLICT(dedupe_key) / InMemory dedupe_key 集合）——两条行
    都入队、都可被 worker 认领投递，互不吞并；复用后回执路径
    find_request(原 id) 也能寻到卡（SQLite 取同 id 最新行）。"""
    queue = SQLiteSendRequestQueue(tmp_path / "q.sqlite3", _NullAuditLogger())
    base = datetime.now(timezone.utc)
    base_dedupe = "error_report:bot.market:private:u1:m-1"
    queue.submit(
        _queue_request("req-orig", f"{base_dedupe}:ack"),
        now=base,
    )
    queue.submit(
        _queue_request("req-orig", f"{base_dedupe}:card"),
        now=base,
        deliver_after=base + timedelta(seconds=3),
    )
    # 到点后 worker 认领：两条都在（同 id 不同 dedupe_key），顺序 ack→card。
    claimed = queue.claim_due(now=base + timedelta(seconds=120))
    assert [entry.send_request.request_id for entry in claimed] == [
        "req-orig",
        "req-orig",
    ]
    assert [entry.send_request.dedupe_key for entry in claimed] == [
        f"{base_dedupe}:ack",
        f"{base_dedupe}:card",
    ]
    # 回执寻址：find_request(原 id) 命中同 id 最新行（=卡），独立派生 id 时代
    # 任何回执查询都够不到卡——这是复用的机制收益。
    found = queue.find_request("req-orig")
    assert found is not None
    assert found.dedupe_key == f"{base_dedupe}:card"


# ==================== E-13 真渲染烟测（默认跳过，BOT_ERRCARD_SMOKE=1 启用） ====================
def test_error_card_real_render_smoke(tmp_path: Path) -> None:
    """E-13 真链路烟测：真实 error_card HTML + 真实 Playwright 出 PNG 落盘，
    补上 pipeline mock 用例（打桩 render_error_card_png）覆盖不到的真实出图段。

    门控先例与 BOT_RENDER_NET_TESTS 一致：默认跳过；设 BOT_ERRCARD_SMOKE=1
    才跑（需本机 playwright+chromium）。全离线：卡图为本地渲染产物，不联网。
    """
    if os.environ.get("BOT_ERRCARD_SMOKE", "") != "1":
        pytest.skip("真实渲染烟测默认跳过（BOT_ERRCARD_SMOKE=1 启用）")
    from plugins.bot_unified_runtime.domains.render.render_backends import (
        PlaywrightRenderBackend,
    )

    backend = PlaywrightRenderBackend()
    if not backend.available:
        pytest.skip("playwright 未安装")
    try:
        path = render_error_card_png(
            _full_report(), backend=backend, card_dir=str(tmp_path)
        )
    finally:
        backend.close()
    assert path, "真实渲染失败：render_error_card_png 返回空串（兜底契约触发）"
    png = Path(path).read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"  # 真实 PNG 魔数，非打桩假字节。
    assert len(png) > 1_000  # 1160x1800@2x 诊断卡不可能是几十字节。
    assert Path(path).name.startswith("error_")


@pytest.mark.parametrize("relative", ["data/cards", "./DATA/cards", "DATA\\cards"])
def test_error_render_relative_path_uses_runtime_root(tmp_path, monkeypatch, relative):
    report = _full_report()
    monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(tmp_path))
    original_path = Path

    def forbid_relative_path(raw):
        path = original_path(raw)
        assert path.is_absolute(), "relative paths must be resolved before filesystem writes"
        return path

    # RED 阶段也不允许真的写源码树；此保护只拦未解析的相对路径。
    monkeypatch.setattr(error_report, "Path", forbid_relative_path)
    result = render_error_card_png(report, backend=_FakeBackend(), card_dir=relative)
    assert result
    assert Path(result).parent == tmp_path / "cards"
    assert Path(result).is_file()


def test_cooldown_reply_samples_once_for_body_and_fallback(monkeypatch):
    import random

    calls = []

    def choose(pool):
        calls.append(len(calls))
        return pool[calls[-1] % len(pool)]

    monkeypatch.setattr(random, "choice", choose)
    pipeline = _PipelineStub()
    maybe_submit_error_card(pipeline, _message(), "bot.market", _captured_exc(),
        settings=ErrorCardSettings(enabled=True), gate=_ManualGate([False]))
    request = pipeline.send_queue.requests[0]
    assert request.content.content_ref["text"] == request.content.text_fallback
    assert len(calls) == 1


# ==================== W9 受众分级裁剪门（2026-10-01）====================
# 病根：卡投回**事发会话**本体（带 gate:bypass_by_design），而 stack_lines /
# config_pairs / env_pairs / version_pairs / id_pairs 曾是无条件渲染的——群内任意
# 非管理员都能读到源码文件名+行号+函数名+源码行+配置键名（值经打码，键名与模块
# 结构不脱）。下面这一节是双向锁：对外档必须裁干净、管理员私聊档必须留全量
# （裁到查不了＝下次线上出问题没人能定位）。
_ROSTER: dict[str, Any] = {
    "bot_admin_user_ids": ["u1"],
    "bot_super_admin_user_ids": ["999"],
    "bot_admin_profiles": {"999": "澜汐"},
    "bot_market_timeout_seconds": 6.0,
    "bot_market_api_key": "sk-abcdefghijklmnop",
}


def _roster_getter(name: str) -> object:
    return _ROSTER.get(name)


def _leaky_exc() -> ValueError:
    """一枚原文里带键名/盘符路径/源码片段的异常（分级门的靶子）。"""
    try:
        raise ValueError(
            "缺 bot_market_timeout_seconds 且 BOT_TOKEN=<x> 在 "
            "C:/Users/LancyCelestia/Runtime/private.sqlite3；def inner(x): 走歪了"
        )
    except ValueError as exc:
        return exc


def _group_message(**kwargs: Any) -> IncomingMessage:
    """群态消息（`_message` 缺省把 u1 建模成 admin，这里只覆盖形态）。"""
    return _message("group:g1", SessionType.GROUP, group_id="g1", **kwargs)


def _labels(rows: Any) -> list[str]:
    return [str(row["label"]) for row in rows or ()]


def _artifact_text(report: dict[str, Any]) -> str:
    """把载荷里**会被印到卡上/写进文本**的内容拼成一段（只看值，不看载荷字典
    自己的键名——`bot_name`/`bot_avatar_url` 这类载荷键名不是卡面内容，拿 `repr`
    当靶子会把"实现细节"误判成泄露）。"""
    parts = [
        str(report.get(key) or "")
        for key in (
            "card_title", "exc_type", "exc_message", "human_text", "trigger_echo",
            "help_text", "fallback_help_text", "bot_name", "bot_name_en",
        )
    ]
    parts.extend(str(line) for line in report.get("stack_lines") or ())
    for key in (
        "method_pairs", "self_review_pairs", "contact_pairs", "config_pairs",
        "version_pairs", "env_pairs", "id_pairs",
    ):
        for row in report.get(key) or ():
            parts.append(f"{row.get('label')}={row.get('value')}")
    return "\n".join(parts)


def test_group_audience_payload_drops_every_internal_section() -> None:
    """注毒腿：群态那张卡六面内部结构全裁，联系方式不点名不报号。"""
    report = build_error_report(
        _group_message(), "bot.market", _leaky_exc(), config_getter=_roster_getter
    )
    assert error_report._audience_tier(_group_message(), _roster_getter) == (
        error_report.AUDIENCE_PUBLIC
    )
    assert report["stack_lines"] == []
    assert report["exc_message"] == ""
    assert report["config_pairs"] == []
    assert report["version_pairs"] == []
    assert report["env_pairs"] == []
    assert report["self_review_pairs"] == []
    # 「函数/路由/归属」＝代码符号＋内部枚举＋模块归属，正是"模块结构不脱"那一面。
    assert _labels(report["method_pairs"]) == ["能力", "原因"]
    assert _labels(report["id_pairs"]) == ["触发时刻"]
    blob = _artifact_text(report)
    assert "999" not in blob and "澜汐" not in blob, "对外档不许印管理端联系方式"
    assert error_report.public_tier_leaks(blob) == []


def test_admin_private_payload_keeps_the_full_diagnostic_surface() -> None:
    """反向腿：管理员私聊那张卡**必须仍是全量**——裁到查不了等于把运维的眼睛戳瞎。"""
    report = build_error_report(
        _message(), "bot.market", _leaky_exc(), config_getter=_roster_getter
    )
    assert error_report._audience_tier(_message(), _roster_getter) == (
        error_report.AUDIENCE_ADMIN_FULL
    )
    assert report["stack_lines"], "栈帧被裁没了＝下次线上出问题查不了"
    assert any(".py:" in line for line in report["stack_lines"])
    assert {"函数", "路由", "归属"} <= set(_labels(report["method_pairs"]))
    assert "bot_market_timeout_seconds" in _labels(report["config_pairs"])
    assert report["version_pairs"] and report["env_pairs"]
    assert {"message_id", "sender_id", "告警关联", "会话"} <= set(_labels(report["id_pairs"]))
    assert "def inner" in report["exc_message"]
    assert len(report["self_review_pairs"]) == 2
    assert "999" in repr(report["contact_pairs"]), "管理员档联系方式本来就该给"


def test_public_tier_does_not_even_compute_the_env_inventory() -> None:
    """对外档连"算了又要扔"的贵件都不算（回执/渲染线程不为看不到的数据付秒级代价）。"""
    seen: list[str] = []

    def spy(name: str) -> object:
        seen.append(name)
        return _ROSTER.get(name)

    build_error_report(
        _group_message(), "bot.market", _leaky_exc(), config_getter=spy, include_env=True
    )
    assert not [n for n in seen if n.startswith("bot_market_")], seen
    assert "bot_protocol_client_dir" not in seen, "环境盘点没跳过＝秒级扫描白付"
    # 反向自检：同一把尺在管理员档确实会读快照键（否则上面那条断言是恒真的空炮）。
    seen.clear()
    build_error_report(
        _message(), "bot.market", _leaky_exc(), config_getter=spy, include_env=True
    )
    assert [n for n in seen if n.startswith("bot_market_")], seen


def test_private_non_admin_audience_is_trimmed_as_well() -> None:
    """私聊但触发者不在管理名单＝同样对外档（转发一次就完成了群广播）。"""
    message = _message(sender_roles=["user"])
    report = build_error_report(
        message, "bot.market", _leaky_exc(), config_getter=lambda name: None
    )
    assert error_report._audience_tier(message, lambda name: None) == error_report.AUDIENCE_PUBLIC
    assert report["stack_lines"] == [] and report["config_pairs"] == []
    assert error_report.public_tier_leaks(_artifact_text(report)) == []
    assert error_report.public_tier_leaks(build_text_fallback(report)) == []


def test_audience_gate_grants_via_roster_and_blocks_cross_platform_lookalike() -> None:
    """分级门只认中央角色口：名单腿能给，跨平台同号不能给（F-A 同源 fail-closed）。"""
    roster_leg = _message(sender_roles=["user"], platform_name="qq")
    assert error_report._audience_tier(roster_leg, _roster_getter) == (
        error_report.AUDIENCE_ADMIN_FULL
    ), "is_admin_message 没接上＝分级门只吃 sender_roles，旁路口会一律降级"
    lookalike = _message(sender_roles=["user"], platform_name="telegram")
    assert error_report._audience_tier(lookalike, _roster_getter) == (
        error_report.AUDIENCE_PUBLIC
    ), "QQ 裸号名单被 TG 同号借走＝跨平台提权把全量诊断递给无权限的脸"
    # 超管走角色事实腿（resolve_roles 里超管自动叠 admin）。
    assert error_report._audience_tier(
        _message(sender_roles=["user", "admin", "super_admin"]), lambda name: None
    ) == error_report.AUDIENCE_ADMIN_FULL


def test_audience_gate_fails_closed_when_the_config_getter_explodes() -> None:
    """判据取不到＝落对外档（少给信息，不多给），且绝不把卡自己搞挂。"""
    def angry(name: str) -> object:
        raise RuntimeError("config 面塌了")

    message = _message(sender_roles=["user"])
    assert error_report._audience_tier(message, angry) == error_report.AUDIENCE_PUBLIC
    report = build_error_report(message, "bot.market", _leaky_exc(), config_getter=angry)
    assert report["card_title"] == "运行异常"
    assert report["human_text"] and report["trigger_echo"] == "/bot status"


def test_group_audience_trim_survives_the_two_phase_rebuild(tmp_path: Path) -> None:
    """两段式：后台渲染线程重建全量报告时受众信息仍在（吃的是同一枚 message 闭包），
    补出来的**卡图 HTML 与兜底文本**都不许带内部结构——回执/卡/文本三条腿同档。"""
    backend = _FakeBackend()
    pipeline = _PipelineStub()
    maybe_submit_error_card(
        pipeline, _group_message(), "bot.market", _leaky_exc(),
        settings=ErrorCardSettings(enabled=True, cooldown_seconds=60, stack_frames=8),
        gate=_ManualGate([True]), backend=backend, card_dir=str(tmp_path),
        render_pool=_InlinePool(),
    )
    assert len(pipeline.send_queue.requests) == 2
    assert backend.calls, "后台没重建全量＝这条腿压根没跑"
    body = str(backend.calls[-1]["html"]).split("<body>", 1)[-1]
    for marker in (".py:", "def ", "BOT_", "bot_", "C:/", "C:\\", "/home/", "澜汐", "999"):
        assert marker not in body, f"群态卡面 HTML 带出 {marker!r}"
    # 四节整节消失（模板按 `{% if pairs %}` 显隐，渲染契约零改动）；「标识与时间」
    # 这一节**留着**但只剩「触发时刻」一行——它不是 id，是管理员对账的抓手。
    for token in ("栈摘录", "配置快照", "版本与构建", "平台与协议"):
        assert token not in body, f"整节没裁干净：{token}"
    assert "标识与时间" in body and "触发时刻" in body
    assert "message_id" not in body and "sender_id" not in body and "debug" not in body
    card = pipeline.send_queue.requests[1]
    assert error_report.public_tier_leaks(card.content.text_fallback) == []
    assert error_report.public_tier_leaks(str(card.content.content_ref["parts"][1]["text"])) == []


def test_admin_private_card_render_still_carries_the_stack(tmp_path: Path) -> None:
    """反向腿（渲染产物面）：管理员私聊那张卡的 HTML 里栈帧与配置快照照旧在。"""
    backend = _FakeBackend()
    maybe_submit_error_card(
        _PipelineStub(), _message(), "bot.market", _leaky_exc(),
        settings=ErrorCardSettings(enabled=True, cooldown_seconds=60, stack_frames=8),
        gate=_ManualGate([True]), backend=backend, card_dir=str(tmp_path),
        render_pool=_InlinePool(),
    )
    html = str(backend.calls[-1]["html"])
    assert ".py:" in html and "bot_market_timeout_seconds" in html


def test_audience_tag_is_stamped_on_ack_card_and_cooldown_paths(tmp_path: Path) -> None:
    """审计留痕：三态（回执/卡/冷却降级）都带 audience 档，且 gate:bypass 语义不动。"""
    for message, expected in (
        (_group_message(), "audience:public"),
        (_message(), "audience:admin_full"),
    ):
        pipeline = _PipelineStub()
        maybe_submit_error_card(
            pipeline, message, "bot.market", _captured_exc(),
            settings=ErrorCardSettings(enabled=True, cooldown_seconds=60, stack_frames=8),
            gate=_ManualGate([True]), backend=_FakeBackend(), card_dir=str(tmp_path),
            render_pool=_InlinePool(),
        )
        for request in pipeline.send_queue.requests:
            assert expected in request.audit_tags, request.audit_tags
            assert "gate:bypass_by_design" in request.audit_tags
    cooldown = _PipelineStub()
    maybe_submit_error_card(
        cooldown, _group_message(), "bot.market", _captured_exc(),
        settings=ErrorCardSettings(enabled=True), gate=_ManualGate([False]),
        backend=_FakeBackend(), render_pool=_InlinePool(),
    )
    assert "audience:public" in cooldown.send_queue.requests[0].audit_tags


def test_gate_removed_payload_would_leak_proving_the_lock_has_teeth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """注毒腿：把裁决口钉成全量档，群态载荷必须立刻带出栈帧与键名——否则上面那批
    "没有 X"的断言可能只是靶子本身是空的（恒真锁）。"""
    monkeypatch.setattr(
        error_report, "_audience_tier", lambda *_a, **_k: error_report.AUDIENCE_ADMIN_FULL
    )
    report = build_error_report(
        _group_message(), "bot.market", _leaky_exc(), config_getter=_roster_getter
    )
    leaked = error_report.public_tier_leaks(_artifact_text(report))
    assert leaked, "门被摘掉都不漏＝本节的裁剪断言全是空炮"
    assert ".py:" in leaked and "bot_" in leaked


def test_public_help_text_points_at_the_admin_tier_instead_of_missing_sections() -> None:
    """页脚必须如实说明"这一份只留人话与归类"，且 E-11 口径不破（非截图/日志真落点）。"""
    group = build_error_report(
        _group_message(), "bot.market", _leaky_exc(), config_getter=_roster_getter
    )
    admin = build_error_report(
        _message(), "bot.market", _leaky_exc(), config_getter=_roster_getter
    )
    assert group["help_text"] == error_report._HELP_TEXT_PUBLIC
    assert admin["help_text"] == error_report._HELP_TEXT
    for text, keys in (
        (
            group["help_text"],
            ("自动生成", "不是控制台截图", "runtime 事件日志", "私聊任一管理员"),
        ),
        (
            group["fallback_help_text"],
            ("没能出", "runtime 事件日志", "私聊任一管理员"),
        ),
    ):
        for key in keys:
            assert key in text, f"{key} 缺失：{text}"
    assert "把这张卡截图" not in group["help_text"]
    assert "截图" not in group["fallback_help_text"]


def test_audience_gate_body_calls_the_central_role_check() -> None:
    """结构锁（同 test_admin_origin_platform_domain_k1b.py 的规矩）：分级门必须照抄
    中央口 `roles.is_admin_message`，不许在 ops 侧养第二套名单判定。含注毒腿。"""
    source = Path(error_report.__file__).read_text(encoding="utf-8")
    start = source.index("def _sender_is_admin(")
    body = source[start:source.index("def _audience_tier(", start)]
    assert "is_admin_message(" in body, "分级门没走中央管理判定口＝造了第二套权限判定"
    assert "sender_roles" in body, "分级门没吃中央角色事实（超管那一腿会瞎）"
    poisoned = body.replace("is_admin_message(", "raw_id_check(", 1)
    assert "is_admin_message(" not in poisoned, "注毒没打掉中央调用＝这发毒无效"
    for second_system in (" in admin_ids", "sender_id in", '== "admin"'):
        assert second_system not in body, f"门里出现自判形态 {second_system!r}"
