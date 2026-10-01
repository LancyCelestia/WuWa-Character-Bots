"""连接期失败可安全重投（TG 告警卡瞬断永久丢弃根修，2026-09-28）回归。

判据（取证席 G 钉死的事实 + 实施席 H 裁决）：mixed 告警卡走原子整发，旧实现
里任何非「明确拒绝」的失败一律记 part=UNKNOWN，而生产
``unknown_part_confirmer=None`` ⇒ UNKNOWN 永不重投 ⇒ **一次代理/网络瞬断＝
请求永久丢弃、零重试**。本波把「连接建立期失败」（请求零字节出网、必未送达）
从这一刀背里摘出来：有界退避重投；其余不确定形态维持 M-63（台账 #47
「九发零台账」）语义**逐字节不变**。

离线运行（零网络、SQLite 落 tmp_path、显式 now 步进，同
tests/test_part_idempotent_resume.py 惯例）：

    PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 \\
      ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest \\
      tests/test_connect_phase_retry.py -q -p no:cacheprovider \\
      --basetemp=../ChatBot_Runtime/cache/pytest_seatH/r1

覆盖项：
- 分类器纯函数：连接期白名单三型 + DNS/gaierror/拒连 ⇒ connect_phase；
  读超时/协议中断/写中途断/HTTP 状态错/**认不出的一切** ⇒ 不确定档。
- transport 腿打标：``send_nonebot_message`` 的 send_exception 回执携带
  retry_safety，异常消息原文照旧不进回执 JSON（atkfix M-2 同口径）。
- worker mixed 重投臂：connect_phase ⇒ part 回 PENDING、行 failed_retryable、
  next_retry_at 非空、attempts+1，下一轮**真重投并送达**；第 4 次仍失败
  （超上限）⇒ 回到既有停放/终态语义、零再投。
- M-63 反向自拼锁：uncertain 与「未打标＝修复前形态」两本账**逐字段相等**
  （part 全 UNKNOWN、续轮零再投），钉住「不确定失败一条都不许多投」。
- inline 首投记账腿：connect_phase ⇒ 不记 UNKNOWN（交请求级退避）；
  uncertain ⇒ 照常记 UNKNOWN+PARTIAL。
- 告警文本直发腿：connect_phase ⇒ 至多补发一次（成功/仍失败两态）；
  uncertain ⇒ 零补发；根装配接线活性锁。
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.contracts import (
    DeliveryReceipt,
    OperationalIssue,
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    RiskLevel,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.domains.transport.sender import (
    failure_class as failure_module,
)
from plugins.bot_unified_runtime.domains.transport.sender.failure_class import (
    RETRY_SAFETY_CONNECT_PHASE,
    RETRY_SAFETY_UNCERTAIN,
    RETRY_SAFETY_UNCLASSIFIED,
    classify_send_failure,
    issue_retry_safety,
    schedule_connect_phase_resend,
)
from plugins.bot_unified_runtime.domains.transport.sender.nonebot import (
    send_nonebot_message,
)
from plugins.bot_unified_runtime.domains.transport.sender.queue import (
    SQLiteSendRequestQueue,
)
from plugins.bot_unified_runtime.domains.transport.sender.worker import (
    _CONNECT_PHASE_RETRY_MAX_ATTEMPTS,
    book_inline_unknown_parts,
    drain_send_queue_once,
)

_TEXT = "守岸人观测到一次投递失败。"
_CARD_PNG = "alert-card.png"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _mixed_card_request(request_id: str) -> SendRequest:
    """告警诊断卡的真实形态（image+text 的 mixed，原子整发）。

    键形/audit_tags/capability_id 对齐 alerts.build_admin_alert_card_send_request
    ——本波要治的就是这条腿，夹具不许偷懒换成普通文本。
    """
    rendered = RenderedOutput(
        request_id=request_id,
        content_type="mixed",
        content_ref={
            "parts": [
                {"type": "image", "file": _CARD_PNG},
                {"type": "text", "text": _TEXT},
            ]
        },
        text_fallback=_TEXT,
        privacy_level=PrivacyLevel.PERSONAL,
    )
    return SendRequest(
        request_id=request_id,
        session_id="private:admin-1",
        target_scope=SessionType.PRIVATE,
        target_id="admin-1",
        capability_id="bot.error_report",
        content=rendered,
        send_policy=SendPolicy.IMMEDIATE,
        priority="high",
        max_messages=1,
        dedupe_key=f"admin_alert_card:telegram:tg-1:admin-1:{request_id}",
        cooldown_key=f"admin_alert_card:telegram:admin-{request_id}",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="runtime",
        adapter="telegram",
        bot_id="tg-1",
        audit_tags=["admin_alert", "origin:admin_alert", "admin_alert_card"],
    )


def _text_request(request_id: str) -> SendRequest:
    rendered = RenderedOutput(
        request_id=request_id,
        content_type="text",
        content_ref={"text": _TEXT},
        text_fallback=_TEXT,
        privacy_level=PrivacyLevel.PERSONAL,
    )
    return _mixed_card_request(request_id).model_copy(update={"content": rendered})


def _build_queue(
    tmp_path: Path, name: str = "queue.sqlite3", *, max_attempts: int = 5
) -> SQLiteSendRequestQueue:
    # max_attempts=5 > 本席重投上限 3 ⇒ 能观测到「第 4 次仍失败才停放」这一档；
    # retry_base/max 取秒级小值，配显式 now 步进跨越，不碰墙钟不 monkeypatch。
    return SQLiteSendRequestQueue(
        tmp_path / name,
        InMemoryAuditLogger(),
        max_attempts=max_attempts,
        retry_base_seconds=1,
        retry_max_seconds=2,
    )


def _row_fields(tmp_path: Path, name: str, request_id: str) -> dict[str, Any]:
    with sqlite3.connect(tmp_path / name) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT state, retry_count, next_retry_at, parts_total, parts_delivered "
            "FROM send_requests WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        assert row is not None
        return dict(row)


def _part_ledger(queue: SQLiteSendRequestQueue, request_id: str) -> list[dict[str, Any]]:
    progress = queue.part_progress(request_id)
    if progress is None:
        return []
    return [
        {
            "index": index,
            "state": record.state,
            "attempts": record.attempts,
            "last_error_kind": record.last_error_kind,
            "provider_message_id": record.provider_message_id,
        }
        for index, record in sorted(progress.records.items())
    ]


class ScriptedTelegramTransport:
    """按 verdict 逐调用抛失败回执的假 transport（模拟 nonebot 腿打标结果）。"""

    def __init__(self, *, retry_safety: str, succeed_after: int | None = None) -> None:
        self.retry_safety = retry_safety
        self.succeed_after = succeed_after
        self.calls: list[str] = []

    async def __call__(self, send_request: SendRequest) -> DeliveryReceipt:
        self.calls.append(send_request.request_id)
        if self.succeed_after is not None and len(self.calls) > self.succeed_after:
            return DeliveryReceipt(
                request_id=send_request.request_id,
                state=ReceiptState.SENT,
                transport="telegram",
                provider_message_id=f"mid-{len(self.calls)}",
                public_message="sent",
            )
        return DeliveryReceipt(
            request_id=send_request.request_id,
            state=ReceiptState.FAILED_RETRYABLE,
            transport="telegram",
            public_message="",
            operational_issue=OperationalIssue(
                stage="telegram",
                kind="send_exception",
                retryable=True,
                safe_summary="send_exception ConnectError",
                retry_safety=self.retry_safety,
            ),
        )


# ==================== 分类器纯函数 ====================


def test_classify_send_failure_connect_phase_whitelist() -> None:
    """连接建立期三型 + DNS/拒连形态 ⇒ connect_phase（唯一放行重投的一档）。"""
    for exc in (
        httpx.ConnectError("All connection attempts failed"),
        httpx.ConnectTimeout("timed out"),
        httpx.ProxyError("unable to connect to proxy"),
        ConnectionRefusedError("refused"),
    ):
        assert classify_send_failure(exc) == RETRY_SAFETY_CONNECT_PHASE, exc
    # socket.gaierror 的 DNS 失败形态（Windows 中文消息也不影响按类型判定）。
    assert classify_send_failure(socket_gaierror()) == RETRY_SAFETY_CONNECT_PHASE


def socket_gaierror() -> BaseException:
    import socket

    return socket.gaierror(11001, "getaddrinfo failed")


def test_classify_send_failure_uncertain_shapes() -> None:
    """读超时/协议中断/写中途断/状态错 ⇒ 不确定：可能已送达，禁重投。"""
    for exc in (
        httpx.ReadTimeout("read timed out"),
        httpx.WriteTimeout("write timed out"),
        httpx.PoolTimeout("pool"),
        httpx.RemoteProtocolError("peer closed connection without sending complete"),
        httpx.ReadError("connection reset"),
        httpx.WriteError("broken pipe"),
        asyncio.TimeoutError(),
        ConnectionResetError("reset by peer"),
    ):
        assert classify_send_failure(exc) == RETRY_SAFETY_UNCERTAIN, exc


def test_classify_send_failure_is_fail_closed_for_unknown_shapes() -> None:
    """认不出来的一切一律按不确定收口：绝不因「没见过」而放行重投。"""
    assert classify_send_failure(RuntimeError("boom")) == RETRY_SAFETY_UNCERTAIN
    assert classify_send_failure(ValueError("bad value")) == RETRY_SAFETY_UNCERTAIN
    assert classify_send_failure(None) == RETRY_SAFETY_UNCLASSIFIED

    # 同名洗白负锁：业务侧自造 ConnectError（非网络栈模块）不算连接期证据。
    class ConnectError(RuntimeError):
        pass

    ConnectError.__module__ = "plugins.bot_unified_runtime.somewhere_business"
    assert classify_send_failure(ConnectError("connect boom")) == RETRY_SAFETY_UNCERTAIN


def test_classify_send_failure_walks_exception_chain() -> None:
    """包装层（如 nonebot NetworkError）本身分不出形状时顺 __cause__/__context__ 取证。"""

    class Wrapper(Exception):
        pass

    Wrapper.__module__ = "nonebot.exception"
    outer = Wrapper("send failed")
    inner = httpx.ConnectError("All connection attempts failed")
    outer.__cause__ = inner
    assert classify_send_failure(outer) == RETRY_SAFETY_CONNECT_PHASE

    outer_by_context = Wrapper("send failed")
    outer_by_context.__context__ = httpx.ReadTimeout("read timed out")
    assert classify_send_failure(outer_by_context) == RETRY_SAFETY_UNCERTAIN


def test_retry_safety_reader_tolerates_old_fixtures() -> None:
    """老夹具/替身没有 retry_safety 字段 ⇒ 读作未分类，绝不因缺字段放行重投。"""

    class LegacyIssue:
        kind = "send_exception"

    assert issue_retry_safety(LegacyIssue()) == RETRY_SAFETY_UNCLASSIFIED
    assert issue_retry_safety(None) == RETRY_SAFETY_UNCLASSIFIED
    assert issue_retry_safety("not-a-model") == RETRY_SAFETY_UNCLASSIFIED


# ==================== transport 腿打标（nonebot） ====================


class _RaisingTelegramBot:
    class _Adapter:
        def get_name(self) -> str:
            return "Telegram"

    adapter = _Adapter()

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc
        self.sent: list[str] = []

    async def send(self, event: object, text: str, **kwargs: object) -> object:
        del event, text, kwargs
        self.sent.append("attempt")
        raise self._exc


@pytest.mark.asyncio
async def test_nonebot_send_exception_carries_connect_phase_label() -> None:
    """真身连接失败 ⇒ send_exception 回执带 connect_phase（kind/safe_summary 不动）。"""
    receipt = await send_nonebot_message(
        _RaisingTelegramBot(httpx.ConnectError("All connection attempts failed")),
        object(),
        _text_request("req-tg-connect"),
    )
    assert receipt.state is ReceiptState.FAILED_RETRYABLE
    issue = receipt.operational_issue
    assert issue is not None
    assert issue.kind == "send_exception"
    assert issue.retry_safety == RETRY_SAFETY_CONNECT_PHASE


@pytest.mark.asyncio
async def test_nonebot_send_exception_labels_read_timeout_as_uncertain() -> None:
    """读超时＝请求已写出 ⇒ uncertain：worker 重投臂据此绝不放行（M-63 反向锁）。"""
    receipt = await send_nonebot_message(
        _RaisingTelegramBot(httpx.ReadTimeout("read timed out")),
        object(),
        _text_request("req-tg-read"),
    )
    assert receipt.state is ReceiptState.FAILED_RETRYABLE
    assert receipt.operational_issue is not None
    assert receipt.operational_issue.kind == "send_exception"
    assert receipt.operational_issue.retry_safety == RETRY_SAFETY_UNCERTAIN


@pytest.mark.asyncio
async def test_nonebot_exception_message_text_never_enters_receipt_json() -> None:
    """atkfix M-2 同口径：打标只带上分类词，异常消息原文一个字符都不进回执。"""
    secret_text = "B0T_SUP3R_SECRET_TOKEN=sk-leak-token"
    receipt = await send_nonebot_message(
        _RaisingTelegramBot(httpx.ConnectError(secret_text)),
        object(),
        _text_request("req-tg-text-leak"),
    )
    assert secret_text not in receipt.model_dump_json()


# ==================== worker mixed 重投臂 ====================


@pytest.mark.asyncio
async def test_mixed_connect_failure_reposts_and_delivers_next_round(
    tmp_path: Path,
) -> None:
    """修复主案：连接期失败 ⇒ part 回 PENDING、行退避、下一轮真重投并送达。

    修复前该形态记 UNKNOWN + confirmer=None ⇒ 永久停放、续轮零再投（就是
    生产里「告警卡一次瞬断即蒸发」的形状）⇒ 本例先红后绿。
    """
    name = "connect-repost.sqlite3"
    queue = _build_queue(tmp_path, name)
    base = _utc_now()
    request = _mixed_card_request("req-connect-repost")
    queue.submit(request, now=base)
    transport = ScriptedTelegramTransport(retry_safety=RETRY_SAFETY_CONNECT_PHASE)

    # 第 1 轮：连接期失败。
    await drain_send_queue_once(queue, transport, now=base + timedelta(seconds=120))

    assert len(transport.calls) == 1
    ledger = _part_ledger(queue, "req-connect-repost")
    assert [row["state"] for row in ledger] == ["pending", "pending"]  # 绝不记 UNKNOWN
    assert [row["attempts"] for row in ledger] == [1, 1]
    row1 = _row_fields(tmp_path, name, "req-connect-repost")
    assert row1["state"] == ReceiptState.FAILED_RETRYABLE.value
    assert row1["retry_count"] == 1
    assert row1["next_retry_at"] is not None  # 指数退避已排，不是停放死档

    # 第 2 轮：退避到期后真重投 ⇒ 送达。
    transport.succeed_after = 1
    result = await drain_send_queue_once(
        queue, transport, now=base + timedelta(seconds=180)
    )
    assert len(transport.calls) == 2, "瞬断后必须重投，不是停放等人工"
    assert result.delivered == 1
    row2 = _row_fields(tmp_path, name, "req-connect-repost")
    assert row2["state"] == ReceiptState.SENT.value
    assert [row["state"] for row in _part_ledger(queue, "req-connect-repost")] == [
        "sent",
        "sent",
    ]


@pytest.mark.asyncio
async def test_mixed_connect_failure_parks_beyond_attempt_cap(tmp_path: Path) -> None:
    """上限治理：connect_phase 重投至多 3 次；第 4 次仍失败 ⇒ 既有停放/终态语义。

    与修复前唯一的差别是「有界重试」，超上限之后的收口形态一条都不许多投。
    """
    name = "connect-cap.sqlite3"
    queue = _build_queue(tmp_path, name, max_attempts=8)
    base = _utc_now()
    request = _mixed_card_request("req-connect-cap")
    queue.submit(request, now=base)
    transport = ScriptedTelegramTransport(retry_safety=RETRY_SAFETY_CONNECT_PHASE)

    for round_index in range(_CONNECT_PHASE_RETRY_MAX_ATTEMPTS + 1):
        await drain_send_queue_once(
            queue, transport, now=base + timedelta(seconds=120 + 60 * round_index)
        )

    # 首投 + 至多 3 次重投 = 恰 4 次真实 dispatch，第 4 次失败后不再重投。
    assert len(transport.calls) == _CONNECT_PHASE_RETRY_MAX_ATTEMPTS + 1
    ledger = _part_ledger(queue, "req-connect-cap")
    assert [row["state"] for row in ledger] == ["unknown", "unknown"]
    row = _row_fields(tmp_path, name, "req-connect-cap")
    # 超上限后离开可重投循环（停放 PARTIAL 或按 Q-G7 终态化，皆非 retryable）。
    assert row["state"] != ReceiptState.FAILED_RETRYABLE.value

    # 续轮零再投（保守收口，M-63 红线）。
    calls_before = len(transport.calls)
    await drain_send_queue_once(queue, transport, now=base + timedelta(seconds=600))
    assert len(transport.calls) == calls_before


async def _uncertain_snapshot(tmp_path: Path, name: str, retry_safety: str) -> dict[str, Any]:
    """跑两轮不确定失败，返回「行 + part 账 + dispatch 数」的逐字段快照。

    next_retry_at 取「有无」而非绝对值：两本账各用自身的 base 墙钟，时刻天然
    不等，比的是**调度形态**（退避/停放），不是时钟读数。
    """
    queue = _build_queue(tmp_path, name)
    base = _utc_now()
    request = _mixed_card_request("req-uncertain")
    queue.submit(request, now=base)
    transport = ScriptedTelegramTransport(retry_safety=retry_safety)
    for round_index in range(2):
        await drain_send_queue_once(
            queue, transport, now=base + timedelta(seconds=120 + 60 * round_index)
        )
    row = _row_fields(tmp_path, name, "req-uncertain")
    row["next_retry_at"] = row["next_retry_at"] is not None
    return {
        "row": row,
        "ledger": _part_ledger(queue, "req-uncertain"),
        "dispatches": len(transport.calls),
    }


@pytest.mark.asyncio
async def test_uncertain_failure_matches_pre_fix_field_by_field(
    tmp_path: Path,
) -> None:
    """M-63 反向自拼锁：打标 uncertain 与「未打标＝修复前形态」逐字段相等。

    两本账各跑一遍同一场景比对（新判据只准放行 connect_phase）；再钉住形态
    本身：part 全 UNKNOWN、续轮零再投、行绝不停在可重投态。
    """
    pre_fix = await _uncertain_snapshot(
        tmp_path, "uncertain-prefix.sqlite3", RETRY_SAFETY_UNCLASSIFIED
    )
    post_fix = await _uncertain_snapshot(
        tmp_path, "uncertain-postfix.sqlite3", RETRY_SAFETY_UNCERTAIN
    )
    assert pre_fix == post_fix, (
        f"不确定失败的行为被改动了（修复前 {pre_fix} / 修复后 {post_fix}）"
        "——M-63 红线只允许 connect_phase 一条窄缝"
    )
    assert [row["state"] for row in post_fix["ledger"]] == ["unknown", "unknown"]
    # 第 1 轮失败即记 UNKNOWN 停放，第 2 轮零 dispatch（confirmer 缺席时绝不盲发）
    # ——这正是 M-63「九发零账」要钉住的形态，重投臂一次都没放行。
    assert post_fix["dispatches"] == 1
    assert post_fix["row"]["state"] != ReceiptState.FAILED_RETRYABLE.value


# ==================== inline 首投记账腿 ====================


def _retryable_issue(retry_safety: str) -> OperationalIssue:
    return OperationalIssue(
        stage="telegram",
        kind="send_exception",
        retryable=True,
        safe_summary="send_exception",
        retry_safety=retry_safety,
    )


def test_inline_booking_skips_unknown_for_connect_phase(tmp_path: Path) -> None:
    """inline 首投遇连接期失败 ⇒ 不记 UNKNOWN（返回 False 交请求级退避重投）。"""
    queue = _build_queue(tmp_path, "inline-connect.sqlite3")
    request = _mixed_card_request("req-inline-connect")
    queue.submit(request, now=_utc_now())
    assert (
        book_inline_unknown_parts(
            queue, request, _retryable_issue(RETRY_SAFETY_CONNECT_PHASE)
        )
        is False
    )
    assert queue.part_progress("req-inline-connect") is None


def test_inline_booking_still_parks_uncertain(tmp_path: Path) -> None:
    """inline 首投遇不确定失败 ⇒ 照常 part 记 UNKNOWN + 行 PARTIAL（语义不变）。"""
    queue = _build_queue(tmp_path, "inline-uncertain.sqlite3")
    request = _mixed_card_request("req-inline-uncertain")
    queue.submit(request, now=_utc_now())
    assert (
        book_inline_unknown_parts(
            queue, request, _retryable_issue(RETRY_SAFETY_UNCERTAIN)
        )
        is True
    )
    assert [row["state"] for row in _part_ledger(queue, "req-inline-uncertain")] == [
        "unknown",
        "unknown",
    ]


# ==================== 告警文本直发腿 ====================


class _CountingResend:
    def __init__(self, receipts: list[DeliveryReceipt]) -> None:
        self.receipts = receipts
        self.calls = 0

    async def __call__(self) -> DeliveryReceipt:
        receipt = self.receipts[min(self.calls, len(self.receipts) - 1)]
        self.calls += 1
        return receipt


def _receipt(state: ReceiptState, retry_safety: str) -> DeliveryReceipt:
    return DeliveryReceipt(
        request_id="req-alert-text",
        state=state,
        transport="telegram",
        public_message="",
        operational_issue=OperationalIssue(
            stage="telegram",
            kind="send_exception",
            retryable=True,
            safe_summary="send_exception",
            retry_safety=retry_safety,
        ),
    )


@pytest.mark.asyncio
async def test_alert_text_leg_resends_once_on_connect_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """连接期失败的告警文本 ⇒ 短退避后台补发恰一次，成功态如实回执。"""
    monkeypatch.setattr(failure_module, "_CONNECT_PHASE_RETRY_DELAY_SECONDS", 0.01)
    request = _text_request("req-alert-text")
    resend = _CountingResend([_receipt(ReceiptState.SENT, RETRY_SAFETY_CONNECT_PHASE)])

    scheduled = schedule_connect_phase_resend(
        request,
        _receipt(ReceiptState.FAILED_RETRYABLE, RETRY_SAFETY_CONNECT_PHASE),
        resend,
    )
    assert scheduled is True
    await asyncio.sleep(0.2)
    assert resend.calls == 1


@pytest.mark.asyncio
async def test_alert_text_leg_retry_failure_does_not_recur(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """补发仍失败 ⇒ 维持现状：不入队、不再补第二刀（至多一次）。"""
    monkeypatch.setattr(failure_module, "_CONNECT_PHASE_RETRY_DELAY_SECONDS", 0.01)
    request = _text_request("req-alert-text")
    resend = _CountingResend(
        [
            _receipt(ReceiptState.FAILED_RETRYABLE, RETRY_SAFETY_CONNECT_PHASE),
            _receipt(ReceiptState.FAILED_RETRYABLE, RETRY_SAFETY_CONNECT_PHASE),
        ]
    )
    assert (
        schedule_connect_phase_resend(
            request,
            _receipt(ReceiptState.FAILED_RETRYABLE, RETRY_SAFETY_CONNECT_PHASE),
            resend,
        )
        is True
    )
    await asyncio.sleep(0.2)
    assert resend.calls == 1


@pytest.mark.asyncio
async def test_alert_text_leg_never_resends_uncertain_failure() -> None:
    """不确定类不补（可能已送达 ⇒ 补发＝双发）：零副作用返回 False。"""
    request = _text_request("req-alert-text")
    resend = _CountingResend([_receipt(ReceiptState.SENT, RETRY_SAFETY_UNCLASSIFIED)])
    for verdict in (RETRY_SAFETY_UNCLASSIFIED, RETRY_SAFETY_UNCERTAIN):
        assert (
            schedule_connect_phase_resend(
                request,
                _receipt(ReceiptState.FAILED_RETRYABLE, verdict),
                resend,
            )
            is False
        )
    await asyncio.sleep(0.05)
    assert resend.calls == 0


def test_root_assembly_alert_text_leg_is_wired() -> None:
    """接线活性锁：根装配 _deliver_admin_alert 里真调用补发调度（防被回退成裸直发）。"""
    root = (
        Path(__file__).resolve().parents[1]
        / "plugins/bot_unified_runtime/__init__.py"
    ).read_text(encoding="utf-8")
    start = root.index("async def _deliver_admin_alert(")
    body = root[start : start + 2000]
    assert "schedule_connect_phase_resend" in body, (
        "告警文本直发腿的连接期补发接线不见了（本波修复点被回退）"
    )


def test_operational_issue_field_is_backward_compatible() -> None:
    """契约面：新字段缺省＝未分类，既有构造点零改动；非法值当场拦（防拼写漂移）。"""
    issue = OperationalIssue(stage="telegram", kind="send_exception")
    assert issue.retry_safety == RETRY_SAFETY_UNCLASSIFIED
    assert issue.model_dump()["retry_safety"] == RETRY_SAFETY_UNCLASSIFIED
    with pytest.raises(ValidationError):
        OperationalIssue(
            stage="telegram", kind="send_exception", retry_safety="whatever"
        )
    # 既有字段语义零改动（kind/safe_summary/retryable 是 worker 与幂等判据承重串）。
    assert issue.attempts == 1
    assert issue.severity is RiskLevel.MEDIUM
