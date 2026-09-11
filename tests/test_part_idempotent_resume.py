"""§9.3 分片发送幂等恢复与部分成功续发（B1）回归。

离线运行（SQLite 用 tmp_path，无网络、无 NapCat）：

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_part_idempotent_resume.py -q

覆盖项（对照 docs/handover-2026-08-29.md §9.3 验收场景）：
- part 级进度每次单 part 成功即落库（请求行 total/delivered/JSON + 明细表，
  payload 只存摘要不存正文副本）。
- 发 3 part、第 1 成功 / 第 2 结果未知 / 第 3 未开始时重启 worker：
  恢复后不重发第 1 个；第 2 个未经确认绝不盲发。
- UNKNOWN 确认协议两分支：确认已送达 → 跳过；确认未送达 → 只重发该 part。
- 明确可重试失败只补发失败 part，后续 part 照常推进。
- 崩溃重启补偿扫描：租约过期重认领 / PARTIAL 行扫描都从断点续发。
- FAILED_FINAL 前已有 part 送达 → 转 PARTIAL 断点，绝不整封盲重发。
- 重复投递同一请求不产生重复 part。
- send_onebot_v11 part_sink 的 chunk 级观测与 result_unknown 语义。
"""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.contracts import (
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.sender import onebot as onebot_sender
from plugins.bot_unified_runtime.sender import worker as worker_module
from plugins.bot_unified_runtime.sender.onebot import send_onebot_v11
from plugins.bot_unified_runtime.sender.queue import (
    PARTIAL_ROW_STATE,
    SQLiteSendRequestQueue,
)
from plugins.bot_unified_runtime.sender.worker import drain_send_queue_once

CHUNKS = ["分片一", "分片二", "分片三"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _chunk_request(request_id: str, chunks: list[str]) -> SendRequest:
    rendered = RenderedOutput(
        request_id=request_id,
        content_type="chunks",
        content_ref={"chunks": list(chunks)},
        text_fallback="".join(chunks),
        privacy_level=PrivacyLevel.PERSONAL,
    )
    return SendRequest(
        request_id=request_id,
        session_id="private:user-1",
        target_scope=SessionType.PRIVATE,
        target_id="user-1",
        capability_id="bot.chat",
        content=rendered,
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=len(chunks),
        dedupe_key=f"dedupe-{request_id}",
        cooldown_key="bot.chat:private:user-1",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="default",
    )


class ScriptedOneBot:
    """按正文映射行为的假 OneBot bot；记录全部已发出文本（含次序）。"""

    def __init__(self, outcomes: dict[str, str] | None = None) -> None:
        self.outcomes = dict(outcomes or {})
        self.sent: list[str] = []

    async def send_private_msg(self, *, user_id: object, message: list[dict]) -> dict:
        text = str(message[0]["data"]["text"])
        self.sent.append(text)
        behavior = self.outcomes.get(text, "ok")
        if behavior == "timeout":
            await asyncio.sleep(0.5)
            return {"status": "async", "retcode": 1}
        if behavior == "retcode_fail":
            return {"status": "failed", "retcode": 100}
        if behavior == "final_fail":
            return {"status": "failed", "retcode": 403}
        if behavior == "raise":
            raise RuntimeError("boom")
        return {"status": "ok", "retcode": 0, "message_id": f"mid-{len(self.sent)}"}

    async def send_group_msg(self, *, group_id: object, message: list[dict]) -> dict:
        return await self.send_private_msg(user_id=group_id, message=message)


def _build_queue(tmp_path: Path, name: str = "queue.sqlite3") -> SQLiteSendRequestQueue:
    # retry_base/kept 小值让可重试退避可用显式时间跨过；partial 退避 90s 用
    # 显式 now 跨越，不 monkeypatch 常量。
    return SQLiteSendRequestQueue(
        tmp_path / name,
        InMemoryAuditLogger(),
        retry_base_seconds=1,
        retry_max_seconds=2,
    )


def _transport(bot: ScriptedOneBot):
    async def _send(send_request: SendRequest):
        return await send_onebot_v11(bot, send_request, timeout_seconds=0.3)

    return _send


def _row_fields(tmp_path: Path, name: str, request_id: str) -> dict:
    with sqlite3.connect(tmp_path / name) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT state, parts_total, parts_delivered, parts_progress "
            "FROM send_requests WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        assert row is not None
        return dict(row)


# ==================== part 级进度落库 ====================


@pytest.mark.asyncio
async def test_part_progress_persisted_per_part(tmp_path) -> None:
    """每个 part 成功即落库：请求行汇总 + 明细表 SENT + 摘要（无正文副本）。"""
    queue = _build_queue(tmp_path)
    base = _utc_now()
    request = _chunk_request("req-persist", CHUNKS)
    queue.submit(request, now=base)
    bot = ScriptedOneBot()

    result = await drain_send_queue_once(
        queue, _transport(bot), now=base + timedelta(seconds=120)
    )

    assert result.delivered == 1
    assert result.parts_delivered == 3
    progress = queue.part_progress("req-persist")
    assert progress is not None and progress.total == 3
    assert progress.delivered == 3
    for index, chunk in enumerate(CHUNKS):
        record = progress.records[index]
        assert record.state == "sent"
        assert record.attempts == 1
        assert record.payload_digest == hashlib.sha256(chunk.encode("utf-8")).hexdigest()[:16]
    fields = _row_fields(tmp_path, "queue.sqlite3", "req-persist")
    assert fields["parts_total"] == 3
    assert fields["parts_delivered"] == 3
    assert fields["state"] == ReceiptState.SENT.value
    assert fields["parts_progress"] == '{"0":"sent","1":"sent","2":"sent"}'
    entry = queue._find_entry_by_request_id("req-persist")
    assert entry is not None and entry.state is ReceiptState.SENT


# ==================== §9.3 验收场景 1：重启不重发已送达 part ====================


@pytest.mark.asyncio
async def test_restart_resume_never_resends_delivered_parts(tmp_path) -> None:
    """第 1 part 成功、第 2 结果未知、第 3 未开始 → 重启后：不重发第 1，
    第 2 确认已送达即跳过，第 3 续发。"""
    name = "restart.sqlite3"
    queue = _build_queue(tmp_path, name)
    base = _utc_now()
    queue.submit(_chunk_request("req-restart", CHUNKS), now=base)
    bot1 = ScriptedOneBot({"分片二": "timeout"})

    first = await drain_send_queue_once(
        queue, _transport(bot1), now=base + timedelta(seconds=120)
    )
    # bot.sent 记录的是「尝试」：分片二尝试后超时（结果未知），分片三未被触达。
    assert bot1.sent == ["分片一", "分片二"]
    assert "分片三" not in bot1.sent
    assert first.partial_deferred == 1
    assert first.parts_delivered == 1
    assert first.parts_unknown == 1
    fields = _row_fields(tmp_path, name, "req-restart")
    assert fields["state"] == PARTIAL_ROW_STATE
    assert fields["parts_delivered"] == 1

    # 重启：新队列实例 + 新 bot；确认器证实分片二已送达。
    queue2 = _build_queue(tmp_path, name)
    bot2 = ScriptedOneBot()

    async def confirmer(send_request: SendRequest, part_index: int) -> bool | None:
        assert send_request.request_id == "req-restart"
        return True if part_index == 1 else None

    second = await drain_send_queue_once(
        queue2,
        _transport(bot2),
        now=base + timedelta(seconds=300),
        unknown_part_confirmer=confirmer,
    )

    assert bot2.sent == ["分片三"]  # 分片一/二绝不重发
    assert second.delivered == 1
    assert second.partials_resumed == 1
    fields = _row_fields(tmp_path, name, "req-restart")
    assert fields["state"] == ReceiptState.SENT.value
    assert fields["parts_delivered"] == 3
    progress = queue2.part_progress("req-restart")
    assert progress is not None and progress.delivered == 3


@pytest.mark.asyncio
async def test_unknown_without_confirmer_never_blind_resent(tmp_path) -> None:
    """无法确认的 UNKNOWN part：不盲发，行保持 PARTIAL；零进展后休眠。"""
    name = "unknown-hold.sqlite3"
    queue = _build_queue(tmp_path, name)
    base = _utc_now()
    queue.submit(_chunk_request("req-hold", CHUNKS), now=base)
    bot1 = ScriptedOneBot({"分片二": "timeout"})
    await drain_send_queue_once(queue, _transport(bot1), now=base + timedelta(seconds=120))

    queue2 = _build_queue(tmp_path, name)
    bot2 = ScriptedOneBot()
    # 第一轮恢复：无确认器 → 分片二保持 UNKNOWN，只续发分片三。
    await drain_send_queue_once(
        queue2, _transport(bot2), now=base + timedelta(seconds=300)
    )
    assert bot2.sent == ["分片三"]
    fields = _row_fields(tmp_path, name, "req-hold")
    assert fields["state"] == PARTIAL_ROW_STATE
    assert fields["parts_delivered"] == 2

    # 第二轮恢复：零进展 → 休眠（next_retry_at=NULL），后续扫描不再认领。
    await drain_send_queue_once(
        queue2, _transport(bot2), now=base + timedelta(seconds=420)
    )
    assert bot2.sent == ["分片三"]  # 分片二始终未被盲发
    fields = _row_fields(tmp_path, name, "req-hold")
    assert fields["state"] == PARTIAL_ROW_STATE
    with sqlite3.connect(tmp_path / name) as connection:
        next_retry_at = connection.execute(
            "SELECT next_retry_at FROM send_requests WHERE request_id = ?",
            ("req-hold",),
        ).fetchone()[0]
    assert next_retry_at is None
    partials = queue2.list_partial_requests()
    assert len(partials) == 1
    assert partials[0].parts is not None
    assert partials[0].parts.unknown_indexes() == [1]
    # 休眠行不再被 claim_due 认领（无空转）。
    assert queue2.claim_due(now=base + timedelta(seconds=100000)) == []


@pytest.mark.asyncio
async def test_unknown_confirmed_not_delivered_is_resent_once(tmp_path) -> None:
    """确认「未送达」→ 该 part 回 PENDING 并只重发一次，其余不重发。"""
    name = "unknown-resend.sqlite3"
    queue = _build_queue(tmp_path, name)
    base = _utc_now()
    queue.submit(_chunk_request("req-resend", CHUNKS), now=base)
    bot1 = ScriptedOneBot({"分片二": "timeout"})
    await drain_send_queue_once(queue, _transport(bot1), now=base + timedelta(seconds=120))

    queue2 = _build_queue(tmp_path, name)
    bot2 = ScriptedOneBot()

    async def confirmer(send_request: SendRequest, part_index: int) -> bool | None:
        return False if part_index == 1 else None

    result = await drain_send_queue_once(
        queue2,
        _transport(bot2),
        now=base + timedelta(seconds=300),
        unknown_part_confirmer=confirmer,
    )

    assert bot2.sent == ["分片二", "分片三"]  # 只补发被确认未送达的 part
    assert result.delivered == 1
    fields = _row_fields(tmp_path, name, "req-resend")
    assert fields["state"] == ReceiptState.SENT.value
    assert fields["parts_delivered"] == 3


# ==================== §9.3 验收场景 2：明确可重试失败只补发该 part ====================


@pytest.mark.asyncio
async def test_retryable_part_failure_resumes_only_failed_part(tmp_path) -> None:
    """第 2 part 明确可重试失败 → 本轮第 3 part 照常推进，下一轮只补发第 2。"""
    name = "retryable.sqlite3"
    queue = _build_queue(tmp_path, name)
    base = _utc_now()
    queue.submit(_chunk_request("req-retry", CHUNKS), now=base)
    bot1 = ScriptedOneBot({"分片二": "retcode_fail"})
    first = await drain_send_queue_once(
        queue, _transport(bot1), now=base + timedelta(seconds=120)
    )
    # 分片二被明确拒绝（尝试过但未送达）；分片三照常推进。
    assert bot1.sent == ["分片一", "分片二", "分片三"]
    assert first.retryable_failed == 1
    fields = _row_fields(tmp_path, name, "req-retry")
    assert fields["state"] == ReceiptState.FAILED_RETRYABLE.value
    assert fields["parts_delivered"] == 2

    # 退避后第二轮：只重发分片二，全部送达 → SENT。
    queue2 = _build_queue(tmp_path, name)
    bot2 = ScriptedOneBot()
    second = await drain_send_queue_once(
        queue2, _transport(bot2), now=base + timedelta(seconds=240)
    )
    assert bot2.sent == ["分片二"]
    assert second.delivered == 1
    assert bot1.sent.count("分片一") == 1  # 已送达 part 全链路只发一次
    fields = _row_fields(tmp_path, name, "req-retry")
    assert fields["state"] == ReceiptState.SENT.value


# ==================== 崩溃重启补偿扫描 ====================


@pytest.mark.asyncio
async def test_crash_after_delivered_part_resumes_from_breakpoint(tmp_path) -> None:
    """进程在 part1 送达、part2 尝试中崩溃：租约过期重认领后从断点续发。"""
    name = "crash.sqlite3"
    queue = _build_queue(tmp_path, name)
    base = _utc_now()
    request = _chunk_request("req-crash", CHUNKS)
    queue.submit(request, now=base)
    # 直接操纵存储层构造崩溃现场（与 worker 落库同一批 API）：
    # part1 已 SENT，part2 刚 mark_part_attempt（结果未知）即进程死亡。
    digests = [hashlib.sha256(chunk.encode("utf-8")).hexdigest()[:16] for chunk in CHUNKS]
    assert queue.ensure_parts_planned("req-crash", digests, now=base) is not None
    assert queue.mark_part_sent("req-crash", 0, now=base + timedelta(seconds=1))
    assert queue.mark_part_attempt("req-crash", 1, now=base + timedelta(seconds=2))
    # 内联认领（模拟崩溃前的 processing 现场）。
    claimed = queue.claim_due(now=base + timedelta(seconds=120))
    assert len(claimed) == 1

    # 重启：租约过期重认领 + part 断点续发。
    queue2 = _build_queue(tmp_path, name)
    bot = ScriptedOneBot()
    result = await drain_send_queue_once(
        queue2, _transport(bot), now=base + timedelta(seconds=300)
    )

    assert bot.sent == ["分片二", "分片三"]  # 分片一绝不重发
    assert result.delivered == 1
    fields = _row_fields(tmp_path, name, "req-crash")
    assert fields["state"] == ReceiptState.SENT.value
    assert fields["parts_delivered"] == 3


# ==================== FAILED_FINAL 前转 PARTIAL 断点 ====================


def test_terminal_failure_with_delivered_parts_converts_to_partial(tmp_path) -> None:
    """请求级 FAILED_FINAL 前若 0<已送达<总数 → 转 PARTIAL 断点。"""
    name = "convert.sqlite3"
    queue = _build_queue(tmp_path, name)
    base = _utc_now()
    digests = [hashlib.sha256(chunk.encode("utf-8")).hexdigest()[:16] for chunk in CHUNKS]
    queue.submit(_chunk_request("req-final", CHUNKS), now=base)
    assert queue.ensure_parts_planned("req-final", digests, now=base) is not None
    assert queue.mark_part_sent("req-final", 0, now=base)

    receipt = queue.mark_final_failure("req-final", "failed", now=base + timedelta(seconds=5))
    assert receipt.state is ReceiptState.FAILED_FINAL
    fields = _row_fields(tmp_path, name, "req-final")
    assert fields["state"] == PARTIAL_ROW_STATE
    assert fields["parts_delivered"] == 1
    assert queue.safe_summary()[PARTIAL_ROW_STATE] == 1
    # 断点行带扫描退避，可被补偿扫描重新认领。
    claimed = queue.claim_due(now=base + timedelta(seconds=120))
    assert len(claimed) == 1
    assert claimed[0].parts is not None


def test_retry_exhaustion_with_delivered_parts_converts_to_partial(tmp_path) -> None:
    """可重试预算烧尽但有已送达 part → PARTIAL 断点而非 FAILED_FINAL。"""
    queue = _build_queue(tmp_path, "exhaust.sqlite3")
    base = _utc_now()
    digests = [hashlib.sha256(chunk.encode("utf-8")).hexdigest()[:16] for chunk in CHUNKS]
    queue.submit(_chunk_request("req-exhaust", CHUNKS), now=base)
    assert queue.ensure_parts_planned("req-exhaust", digests, now=base) is not None
    assert queue.mark_part_sent("req-exhaust", 0, now=base)

    for round_index in range(3):
        receipt = queue.mark_retryable_failure(
            "req-exhaust", "failed", now=base + timedelta(seconds=10 * round_index)
        )
    assert receipt.state is ReceiptState.FAILED_FINAL
    fields = _row_fields(tmp_path, "exhaust.sqlite3", "req-exhaust")
    assert fields["state"] == PARTIAL_ROW_STATE


def test_expired_lease_finalization_converts_to_partial(tmp_path) -> None:
    """租约反复过期的行达上限时：已有 part 送达 → PARTIAL 断点。"""
    name = "lease.sqlite3"
    queue = _build_queue(tmp_path, name)
    base = _utc_now()
    digests = [hashlib.sha256(chunk.encode("utf-8")).hexdigest()[:16] for chunk in CHUNKS]
    queue.submit(_chunk_request("req-lease", CHUNKS), now=base)
    assert queue.ensure_parts_planned("req-lease", digests, now=base) is not None
    assert queue.mark_part_sent("req-lease", 0, now=base)

    # 认领 → 租约过期 → 重认领 ×3 触发 finalize 分支。
    queue.claim_due(now=base + timedelta(seconds=120))
    queue.claim_due(now=base + timedelta(seconds=200))
    queue.claim_due(now=base + timedelta(seconds=280))
    queue.claim_due(now=base + timedelta(seconds=360))
    fields = _row_fields(tmp_path, name, "req-lease")
    assert fields["state"] == PARTIAL_ROW_STATE
    assert queue.safe_summary()[ReceiptState.FAILED_FINAL.value] == 0


# ==================== 重复投递不产生重复 part ====================


@pytest.mark.asyncio
async def test_duplicate_submit_produces_no_duplicate_parts(tmp_path) -> None:
    queue = _build_queue(tmp_path, "dup.sqlite3")
    base = _utc_now()
    request = _chunk_request("req-dup", CHUNKS)
    first = queue.submit(request, now=base)
    # 同一请求重复投递（相同 dedupe_key）：幂等跳过，不得产生重复 part。
    duplicate = queue.submit(
        request.model_copy(update={"request_id": "req-dup-b"}), now=base
    )
    assert first.state is ReceiptState.QUEUED
    assert duplicate.state is ReceiptState.SKIPPED

    bot = ScriptedOneBot()
    await drain_send_queue_once(queue, _transport(bot), now=base + timedelta(seconds=120))
    progress = queue.part_progress("req-dup")
    assert progress is not None and len(progress.records) == 3
    assert queue.part_progress("req-dup-b") is None
    assert len(bot.sent) == 3


# ==================== onebot part_sink 观测 ====================


@pytest.mark.asyncio
async def test_onebot_part_sink_reports_sent_and_unknown_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """chunk 级观测：成功段报 sent、段内异常（结果未知）报 unknown、后续段不被触达。

    注：整段超时由外层 wait_for 裁决（与既有 result_unknown 语义一致），
    取消路径不产生 per-part 回报，故这里用段内异常代表「结果未知」。
    """
    monkeypatch.setattr(onebot_sender, "_ONEBOT_SEND_RETRY_DELAYS", ())
    bot = ScriptedOneBot({"分片二": "raise"})
    reports: list[tuple[int, str]] = []
    receipt = await send_onebot_v11(
        bot,
        _chunk_request("req-sink", CHUNKS),
        timeout_seconds=0.3,
        part_sink=lambda index, state: reports.append((index, state)),
    )
    assert reports == [(0, "sent"), (1, "unknown")]
    assert receipt.state is ReceiptState.FAILED_FINAL
    assert receipt.operational_issue is not None
    assert receipt.operational_issue.kind == "result_unknown"
    assert receipt.public_message == ""


@pytest.mark.asyncio
async def test_onebot_chunk_retcode_rejection_is_retryable_single_part(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """单段请求被平台明确拒绝（retcode≠0）：明确失败可重试，不是结果未知。"""
    monkeypatch.setattr(onebot_sender, "_ONEBOT_SEND_RETRY_DELAYS", ())
    bot = ScriptedOneBot({"分片二": "retcode_fail"})
    receipt = await send_onebot_v11(
        bot, _chunk_request("req-part2", ["分片二"]), timeout_seconds=1.0
    )
    assert receipt.state is ReceiptState.FAILED_RETRYABLE
    assert receipt.operational_issue is not None
    assert receipt.operational_issue.kind == "retcode_failure"


@pytest.mark.asyncio
async def test_onebot_part_sink_failure_never_breaks_sending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """观测回调抛异常绝不反噬发送主链路。"""
    monkeypatch.setattr(onebot_sender, "_ONEBOT_SEND_RETRY_DELAYS", ())

    def broken_sink(index: int, state: str) -> None:
        raise RuntimeError("sink boom")

    bot = ScriptedOneBot()
    receipt = await send_onebot_v11(
        bot,
        _chunk_request("req-sink-safe", CHUNKS),
        timeout_seconds=1.0,
        part_sink=broken_sink,
    )
    assert receipt.state is ReceiptState.SENT
    assert bot.sent == CHUNKS


# ==================== 无 part 存储的队列走既有整发语义 ====================


@pytest.mark.asyncio
async def test_queue_without_part_store_keeps_legacy_whole_request(tmp_path) -> None:
    """无 part 存储 API 的队列（鸭子类型探测失败）→ 完全走既有路径。"""
    from plugins.bot_unified_runtime.sender.queue import InMemorySendQueue

    audit = InMemoryAuditLogger()
    queue = InMemorySendQueue(audit)
    bot = ScriptedOneBot()
    receipt = await send_onebot_v11(bot, _chunk_request("req-mem", CHUNKS), timeout_seconds=1.0)
    assert receipt.state is ReceiptState.SENT
    assert bot.sent == CHUNKS
    assert worker_module._chunk_part_plan(_chunk_request("req-mem", CHUNKS)) == CHUNKS
    assert worker_module._part_store(queue) is None


@pytest.mark.asyncio
async def test_non_chunk_content_not_part_tracked(tmp_path) -> None:
    """非 chunks 内容不启用 part 跟踪（走既有整发语义）。"""
    from plugins.bot_unified_runtime.contracts import RenderedOutput as RO

    rendered = RO(
        request_id="req-text",
        content_type="text",
        content_ref={"text": "普通文本"},
        text_fallback="普通文本",
        privacy_level=PrivacyLevel.PERSONAL,
    )
    request = _chunk_request("req-text", CHUNKS).model_copy(
        update={"content": rendered}
    )
    assert worker_module._chunk_part_plan(request) is None
