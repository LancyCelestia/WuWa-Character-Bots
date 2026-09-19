"""B4b Tier1/Tier2 送达核验回归（全离线 mock，零网络零 SnowLuma）。

覆盖 B4-spec §3.2 / §4（T7/T8/T9/T10 变体/T11 方向锁/T12 结构锁）中归属
本席独占面的部分：

Tier 1（本地段数/类型一致性观测，不改 ReceiptState）：
- ``_mixed_segments`` 部分构造失败 → 观测日志携 request_id/planned/sent/
  dropped_types/sent_types（只类型名，零正文）；
- 全段失败 → 返回值与既有 ``[_text_segment(text_fallback)]`` 逐字节一致，
  仅多一条 ``reason=segment_build_fallback_text`` 观测行；
- 核验开关（缺省关）开启且 mixed 有丢段 → SENT 回执挂
  ``OperationalIssue(kind="segment_dropped_local", stage="onebot",
  retryable=False)``；开关关闭 → SENT 回执字段形态与现状逐字节一致。

Tier 2（可选接线骨架，缺省关）：
- ``OneBotV11Bot`` Protocol 声明可选只读 ``get_msg``；
- ``build_unknown_part_confirmer`` 三分支语义矩阵：命中→True；
  「明确不存在」→ False 仅当 ``_ONEBOT_GET_MSG_NOT_FOUND_PROVEN`` 翻真
  （SnowLuma 返回 schema 未取证 ⇒ 生产恒不可达，防「查询失败误判未送达
  →重投双发」，方向锁）；异常/无 get_msg/无可查 message_id→None；
- ``_register_send_queue_scheduler`` 的 ``drain_send_queue_once`` 调用点：
  开关缺位/关闭 → confirmer=None（现状逐字节）；显式开启 → 非 None。

复跑：
    PYTHONDONTWRITEBYTECODE=1 <venv>/Scripts/python.exe -m pytest \
        tests/test_delivery_verification_tier1.py -q \
        -p no:cacheprovider --basetemp=$TEMP/b4b
"""

from __future__ import annotations

import asyncio
import logging
import types
from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import (
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.domains.transport.sender import onebot as onebot_sender
from plugins.bot_unified_runtime.domains.transport.sender.onebot import (
    OneBotV11Bot,
    build_onebot_message_segments,
    send_onebot_v11,
)

_ONEBOT_LOGGER = "plugins.bot_unified_runtime.domains.transport.sender.onebot"


def _mixed_request(
    request_id: str,
    parts: list[Any],
    *,
    text_fallback: str = "兜底文案",
    content_ref_extra: dict[str, Any] | None = None,
) -> SendRequest:
    content_ref: dict[str, Any] = {"parts": parts, **(content_ref_extra or {})}
    rendered = RenderedOutput(
        request_id=request_id,
        content_type="mixed",
        content_ref=content_ref,
        text_fallback=text_fallback,
        privacy_level=PrivacyLevel.PERSONAL,
    )
    return SendRequest(
        request_id=request_id,
        session_id="private:user-1",
        target_scope=SessionType.PRIVATE,
        target_id="user-1",
        capability_id="bot.emergency_probe",
        content=rendered,
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key=f"dedupe-{request_id}",
        cooldown_key="bot.emergency_probe:private:user-1",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="default",
        adapter="onebot",
        bot_id="qq-bot",
    )


class _RecordingBot:
    """鸭子型 OneBot V11 bot：记录送出的段并回 ok 回执。"""

    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self.sent_messages: list[list[dict[str, Any]]] = []
        self._result = result or {
            "status": "ok",
            "retcode": 0,
            "data": {"message_id": 777},
        }

    async def send_private_msg(self, *, user_id: Any, message: Any) -> Any:
        self.sent_messages.append(message)
        return self._result

    async def send_group_msg(self, *, group_id: Any, message: Any) -> Any:
        self.sent_messages.append(message)
        return self._result


def _warning_text(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.name == _ONEBOT_LOGGER and record.levelno >= logging.WARNING
    )


# ==================== Tier 1：本地摘段观测（无条件日志） ====================


def test_mixed_segment_drop_logged_with_fingerprint(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """record 缺 file 被丢 → 观测行含 request_id/planned/sent/dropped_types。

    现状（实现前）零日志 ⇒ 本条必 RED（spec §4 T7）。
    """
    request = _mixed_request(
        "req-drop-1",
        [{"type": "record"}, {"type": "text", "text": "x"}],
    )
    with caplog.at_level(logging.WARNING, logger=_ONEBOT_LOGGER):
        segments = build_onebot_message_segments(request)

    assert segments == [{"type": "text", "data": {"text": "x"}}]
    text = _warning_text(caplog)
    assert "onebot mixed segment dropped" in text
    assert "req-drop-1" in text
    assert "dropped_types=['record']" in text
    assert "planned=2" in text
    assert "sent=1" in text


def test_all_parts_dropped_text_fallback_byte_identical(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """全段无效 → 返回值逐字节=现状纯文本回落；仅多观测行（spec T8 行为锁）。"""
    request = _mixed_request(
        "req-drop-all",
        [{"type": "record"}, {"type": "music"}],
        text_fallback="只剩文案了",
    )
    with caplog.at_level(logging.WARNING, logger=_ONEBOT_LOGGER):
        segments = build_onebot_message_segments(request)

    assert segments == [{"type": "text", "data": {"text": "只剩文案了"}}]
    assert segments == [onebot_sender._text_segment("只剩文案了")]
    text = _warning_text(caplog)
    assert "onebot mixed segment dropped" in text
    assert "dropped_types=['record', 'music']" in text
    assert "reason=segment_build_fallback_text" in text


def test_clean_mixed_emits_no_drop_log(caplog: pytest.LogCaptureFixture) -> None:
    """无丢段 → 不得产生任何摘段观测行（防观测噪声/恒真断言）。"""
    request = _mixed_request(
        "req-clean",
        [{"type": "text", "text": "a"}, {"type": "at", "qq": "123"}],
    )
    with caplog.at_level(logging.WARNING, logger=_ONEBOT_LOGGER):
        segments = build_onebot_message_segments(request)

    assert len(segments) == 2
    assert "onebot mixed segment dropped" not in _warning_text(caplog)


# ==================== Tier 1：核验开关 + OperationalIssue 挂接 ====================


def test_sent_receipt_unchanged_when_verify_off() -> None:
    """开关缺省（None=关）→ SENT 回执 operational_issue 恒 None（现状锁）。"""
    request = _mixed_request("req-off", [{"type": "record"}, {"type": "text", "text": "x"}])
    receipt = asyncio.run(send_onebot_v11(_RecordingBot(), request))

    assert receipt.state is ReceiptState.SENT
    assert receipt.operational_issue is None
    assert receipt.provider_message_id == "777"


def test_sent_receipt_carries_segment_dropped_local_when_verify_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """开关开 + mixed 丢段 → SENT 不变，仅追加观测性 issue（spec T9 真侧）。"""
    monkeypatch.setattr(onebot_sender, "_outbound_verify_provider", lambda: True)
    request = _mixed_request("req-on", [{"type": "record"}, {"type": "text", "text": "x"}])
    receipt = asyncio.run(send_onebot_v11(_RecordingBot(), request))

    assert receipt.state is ReceiptState.SENT  # 绝不改判 ReceiptState（spec 明文）
    issue = receipt.operational_issue
    assert issue is not None
    assert issue.kind == "segment_dropped_local"
    assert issue.stage == "onebot"
    assert issue.retryable is False


def test_verify_on_clean_mixed_adds_no_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    """开关开但零丢段 → 不挂 issue（防「开关一开全刷 issue」误实现）。"""
    monkeypatch.setattr(onebot_sender, "_outbound_verify_provider", lambda: True)
    request = _mixed_request("req-on-clean", [{"type": "text", "text": "ok"}])
    receipt = asyncio.run(send_onebot_v11(_RecordingBot(), request))

    assert receipt.state is ReceiptState.SENT
    assert receipt.operational_issue is None


def test_verify_provider_failure_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """开关 getter 自身抛异常 → 按关闭处理，绝不因观测面炸发送主链路。"""

    def _boom() -> bool:
        raise RuntimeError("config exploded")

    monkeypatch.setattr(onebot_sender, "_outbound_verify_provider", _boom)
    request = _mixed_request("req-boom", [{"type": "record"}, {"type": "text", "text": "x"}])
    receipt = asyncio.run(send_onebot_v11(_RecordingBot(), request))

    assert receipt.state is ReceiptState.SENT
    assert receipt.operational_issue is None


# ==================== Tier 1：ReceiptState 结构锁（spec T12） ====================


def test_receipt_state_enum_frozen() -> None:
    """本波任何实现不得新增/改判回执状态（Tier1 只观测+审计指纹）。"""
    assert {member.name for member in ReceiptState} == {
        "ACCEPTED",
        "RENDERED",
        "QUEUED",
        "SENT",
        "SKIPPED",
        "REDIRECTED",
        "BLOCKED",
        "FAILED_RETRYABLE",
        "FAILED_FINAL",
    }


# ==================== Tier 2-a：protocol 可选声明 + 鸭子探测 ====================


def test_onebot_protocol_declares_optional_get_msg() -> None:
    """OneBotV11Bot 声明只读 get_msg（声明本身零行为变更，spec T2-a）。"""
    assert "get_msg" in OneBotV11Bot.__dict__


# ==================== Tier 2-b：UNKNOWN part 确认器语义矩阵 ====================


class _GetMsgBot:
    def __init__(self, result: Any = None, *, error: Exception | None = None) -> None:
        self.calls: list[Any] = []
        self._result = result
        self._error = error

    async def get_msg(self, *, message_id: Any) -> Any:
        self.calls.append(message_id)
        if self._error is not None:
            raise self._error
        return self._result


def _confirmer_for(bot: Any) -> Any:
    factory = getattr(onebot_sender, "build_unknown_part_confirmer", None)
    assert callable(factory), "build_unknown_part_confirmer 未实现（Tier2-b 骨架）"
    return factory(lambda _request: bot)


def _request_with_part_ids(part_ids: Any) -> SendRequest:
    return _mixed_request(
        "req-confirm",
        [{"type": "text", "text": "x"}],
        content_ref_extra={"part_message_ids": part_ids},
    )


def test_confirmer_without_get_msg_returns_none() -> None:
    confirmer = _confirmer_for(object())  # 鸭子探测：无 get_msg 属性
    verdict = asyncio.run(confirmer(_request_with_part_ids(["5"]), 0))
    assert verdict is None


def test_confirmer_without_message_id_never_queries() -> None:
    bot = _GetMsgBot(result={"status": "ok", "retcode": 0, "data": {"message_id": 5}})
    confirmer = _confirmer_for(bot)
    request = _mixed_request("req-noid", [{"type": "text", "text": "x"}])
    verdict = asyncio.run(confirmer(request, 0))
    assert verdict is None
    assert bot.calls == []  # 无查询把手绝不盲查


def test_confirmer_hit_returns_true() -> None:
    bot = _GetMsgBot(result={"status": "ok", "retcode": 0, "data": {"message_id": 5, "segments": []}})
    confirmer = _confirmer_for(bot)
    verdict = asyncio.run(confirmer(_request_with_part_ids(["5"]), 0))
    assert verdict is True
    assert bot.calls == ["5"]


def test_confirmer_exception_returns_none() -> None:
    bot = _GetMsgBot(error=RuntimeError("network exploded"))
    confirmer = _confirmer_for(bot)
    verdict = asyncio.run(confirmer(_request_with_part_ids(["5"]), 0))
    assert verdict is None


def test_confirmer_not_found_stays_none_until_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """「消息不存在」形态在 SnowLuma schema 取证前不得判 False（防重投双发）。"""
    monkeypatch.setattr(onebot_sender, "_ONEBOT_GET_MSG_NOT_FOUND_PROVEN", False)
    bot = _GetMsgBot(result={"status": "failed", "retcode": 1400, "data": None})
    confirmer = _confirmer_for(bot)
    verdict = asyncio.run(confirmer(_request_with_part_ids(["5"]), 0))
    assert verdict is None


def test_confirmer_not_found_false_only_when_proven(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """取证翻真后：结构化「不存在」回执 → False（part 回 PENDING 重发安全）。"""
    monkeypatch.setattr(onebot_sender, "_ONEBOT_GET_MSG_NOT_FOUND_PROVEN", True)
    bot = _GetMsgBot(result={"status": "failed", "retcode": 1400, "data": None})
    confirmer = _confirmer_for(bot)
    verdict = asyncio.run(confirmer(_request_with_part_ids(["5"]), 0))
    assert verdict is False


# ==================== Tier 2-b：生产接线（缺省不启用） ====================


class _FakeScheduler:
    def __init__(self) -> None:
        self.job: Any = None

    def add_job(self, func: Any, *_args: Any, **_kwargs: Any) -> None:
        self.job = func


class _DrainableQueue:
    def list_due(self, *, now: Any = None, limit: int = 20) -> list[Any]:
        return []

    def mark_sent(self, request_id: str, public_message: str = "sent", *, now: Any = None) -> Any:
        raise NotImplementedError

    def mark_retryable_failure(self, request_id: str, public_message: str, *, now: Any = None) -> Any:
        raise NotImplementedError

    def mark_final_failure(self, request_id: str, public_message: str, *, now: Any = None) -> Any:
        raise NotImplementedError


def _queue_scheduler_config(**extra: Any) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        bot_send_queue_worker_enabled=True,
        bot_send_queue_worker_interval_seconds=5,
        bot_send_queue_worker_batch_size=3,
        **extra,
    )


def _run_registered_job(config: Any, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    import plugins.bot_unified_runtime as pkg

    captured: dict[str, Any] = {}

    async def _fake_drain(*_args: Any, **kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(pkg, "drain_send_queue_once", _fake_drain)
    scheduler = _FakeScheduler()
    result = pkg._register_send_queue_scheduler(
        scheduler=scheduler,
        config=config,
        send_queue=_DrainableQueue(),
        audit_logger=None,  # type: ignore[arg-type]
        receipt_repository=None,
        bot_provider=list,
        operational_notifier=None,
    )
    assert result["registered"] is True
    asyncio.run(scheduler.job())
    return captured


def test_production_drain_confirmer_none_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """键缺位（B4a 落地前）/关闭 → 传 None，与现状裸调用逐字节等价。"""
    captured = _run_registered_job(_queue_scheduler_config(), monkeypatch)
    assert captured.get("unknown_part_confirmer") is None


def test_production_drain_wires_confirmer_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """显式开启 → confirmer 非 None（spec T10 的开关受控版，本席缺省关裁定）。"""
    config = _queue_scheduler_config(bot_outbound_verify_enabled=True)
    captured = _run_registered_job(config, monkeypatch)
    assert callable(captured.get("unknown_part_confirmer"))
