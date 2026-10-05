"""发送终态「为什么失败」落账 + 兄弟行 part 账身份隔离（SEAT-SENDTERM，2026-10-04）。

治的生产事实（2026-10-04 只读现算，取证件＝ChatBot_Runtime/cache/seat-sendterm/db_probe.json，
计数系**当时值**、随库存漂移不复述）：79/79 枚 failed_final 明细行
``last_error_kind='retcode_failure'``
且 ``attempts=1``，``send_requests.last_public_message`` 全空——判死用的那枚 OneBot
retcode 在 ``sender/onebot.py`` 的分支里算出来、用完即丢，库里一个数字都没留，
事后无从判断它到底是真终态码还是暂态码（白名单 ``_is_final_failure_retcode``
因此无法复核）。

判据与改动一一对应（不是并列清单）：
- A1 退码上回执：``retcode_failure`` 的 ``safe_summary`` 带 ``retcode=<n> status=<tok>``。
  **只带结构 token**：``nonebot._send_failure_summary`` 与
  tests/test_operational_failures.py:368-373 的裁决锁钉死「适配器/异常消息原文
  绝不进回执 JSON」，所以这里补的是数字与协议状态词，不是 failedResponse.wording。
- A2 退码上 part 明细账：``send_request_parts.last_error_detail``（additive
  ALTER-if-missing，先例＝同表 ``dedupe_key`` 列），重启后仍可读。
- C 兄弟行不互踩：worker「mixed 原子整发」终态臂补 ``dedupe_key``（Q-G5：段级
  记账一律带行身份；同函数其余各臂都带着，独此臂漏写）。

离线运行（SQLite 用 tmp_path，无网络、无 SnowLuma、绝不碰生产库）：

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_send_failure_reason_ledger.py -q \
        -p no:cacheprovider --basetemp=<仓库外>
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.contracts import (
    DeliveryReceipt,
    OperationalIssue,
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.domains.transport.sender.onebot import send_onebot_v11
from plugins.bot_unified_runtime.domains.transport.sender.queue import (
    SQLiteSendRequestQueue,
)
from plugins.bot_unified_runtime.domains.transport.sender.worker import (
    drain_send_queue_once,
)

CHUNKS = ["分片甲", "分片乙"]
MIXED_PARTS = [{"type": "text", "text": "部件甲"}, {"type": "text", "text": "部件乙"}]
# sender 侧富化后的结构因形状（A1 的产物，A2/C 的输入）。
DETAIL_403 = "retcode_failure retcode=403 status=failed"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _request(
    request_id: str,
    *,
    content_type: str,
    content_ref: dict,
    dedupe_key: str | None = None,
    parts_total: int = 2,
) -> SendRequest:
    rendered = RenderedOutput(
        request_id=request_id,
        content_type=content_type,
        content_ref=dict(content_ref),
        text_fallback="正文",
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
        max_messages=parts_total,
        dedupe_key=dedupe_key or f"dedupe-{request_id}",
        cooldown_key="bot.chat:private:user-1",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="default",
    )


def _chunks_request(
    request_id: str, chunks: list[str], *, dedupe_key: str | None = None
) -> SendRequest:
    return _request(
        request_id,
        content_type="chunks",
        content_ref={"chunks": list(chunks)},
        dedupe_key=dedupe_key,
        parts_total=len(chunks),
    )


def _mixed_request(
    request_id: str, *, dedupe_key: str | None = None, parts: list[dict] | None = None
) -> SendRequest:
    return _request(
        request_id,
        content_type="mixed",
        content_ref={"parts": list(parts or MIXED_PARTS)},
        dedupe_key=dedupe_key,
    )


class RejectingOneBot:
    """按正文返回平台失败回执的假 bot；wording 是刻意埋的毒（不得进库）。"""

    def __init__(self, outcomes: dict[str, dict[str, object]]) -> None:
        self.outcomes = dict(outcomes)
        self.sent: list[str] = []

    async def send_private_msg(self, *, user_id: object, message: list[dict]) -> dict:
        text = str(message[0]["data"]["text"])
        self.sent.append(text)
        outcome = self.outcomes.get(text)
        if outcome is None:
            return {"status": "ok", "retcode": 0, "message_id": f"mid-{len(self.sent)}"}
        return dict(outcome)

    async def send_group_msg(self, *, group_id: object, message: list[dict]) -> dict:
        return await self.send_private_msg(user_id=group_id, message=message)


def _build_queue(tmp_path: Path, name: str = "reason_ledger.sqlite3") -> SQLiteSendRequestQueue:
    # 新入队行有 60s 内联宽限期（queue._INLINE_DELIVERY_GRACE_SECONDS）：宽限期内
    # worker 不认领（首投归 handler 内联）。本文件测的是 worker 接管后的账，
    # 故 drain 的 now 一律 +120s（同 test_part_idempotent_resume 先例）。
    return SQLiteSendRequestQueue(
        tmp_path / name,
        InMemoryAuditLogger(),
        retry_base_seconds=1,
        retry_max_seconds=2,
    )


def _transport(bot: RejectingOneBot):
    async def _send(send_request: SendRequest):
        return await send_onebot_v11(bot, send_request, timeout_seconds=0.3)

    return _send


def _receipt_for(
    send_request: SendRequest,
    *,
    state: ReceiptState,
    issue: OperationalIssue | None,
) -> DeliveryReceipt:
    return DeliveryReceipt(
        request_id=send_request.request_id,
        state=state,
        transport="onebot.v11",
        public_message="sent" if state is ReceiptState.SENT else "",
        provider_message_id="mid-1" if state is ReceiptState.SENT else None,
        operational_issue=issue,
    )


def _issue(kind: str, *, retryable: bool, safe_summary: str) -> OperationalIssue:
    return OperationalIssue(
        stage="onebot", kind=kind, retryable=retryable, safe_summary=safe_summary
    )


def _part_rows(tmp_path: Path, name: str, request_id: str) -> list[sqlite3.Row]:
    with sqlite3.connect(tmp_path / name) as connection:
        connection.row_factory = sqlite3.Row
        return list(
            connection.execute(
                "SELECT part_index, state, attempts, last_error_kind, last_error_detail,"
                " dedupe_key FROM send_request_parts WHERE request_id = ?"
                " ORDER BY dedupe_key, part_index",
                (request_id,),
            ).fetchall()
        )


def _request_row(tmp_path: Path, name: str, dedupe_key: str) -> sqlite3.Row:
    with sqlite3.connect(tmp_path / name) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            "SELECT state, retry_count, request_json, last_public_message FROM send_requests"
            " WHERE dedupe_key = ?",
            (dedupe_key,),
        ).fetchone()


# ==================== A1：退码上回执（safe_summary 带结构 token）====================


def test_terminal_retcode_receipt_keeps_numeric_code() -> None:
    """白名单终态码：回执 safe_summary 必须带上那枚数字（改前＝只剩 'retcode_failure'）。"""
    bot = RejectingOneBot(
        {"分片甲": {"status": "failed", "retcode": 403, "wording": "secret C:\\Users\\x\\.env"}}
    )
    receipt = asyncio.run(
        send_onebot_v11(bot, _chunks_request("req-keep-403", ["分片甲"]), timeout_seconds=0.3)
    )
    assert receipt.state is ReceiptState.FAILED_FINAL
    issue = receipt.operational_issue
    assert issue is not None
    # kind 是 worker 判据与幂等去重逐字消费的承重串，一个字节都不许动。
    assert issue.kind == "retcode_failure"
    assert issue.retryable is False
    assert "403" in issue.safe_summary
    # 裁决锁：适配器 wording 原文（含盘符形态）绝不进回执。
    assert "secret" not in issue.safe_summary
    assert "Users" not in issue.safe_summary


def test_retryable_retcode_receipt_keeps_numeric_code() -> None:
    """白名单外的可重试码同样要记账——否则运维只看得到同一个 'retcode_failure'。"""
    bot = RejectingOneBot({"分片甲": {"status": "failed", "retcode": 500}})
    receipt = asyncio.run(
        send_onebot_v11(bot, _chunks_request("req-keep-500", ["分片甲"]), timeout_seconds=0.3)
    )
    assert receipt.state is ReceiptState.FAILED_RETRYABLE
    issue = receipt.operational_issue
    assert issue is not None and issue.kind == "retcode_failure"
    assert issue.retryable is True
    assert "500" in issue.safe_summary


class ActionFailedLike(Exception):
    """NoneBot ActionFailed 的实形（生产 nonebot 2.5.0：无 .retcode 属性，码在 .info）。"""

    def __init__(self, retcode: object, wording: str) -> None:
        super().__init__(f"action failed: {wording}")
        self.info = {"retcode": retcode, "wording": wording}


def test_action_failed_rejection_keeps_code() -> None:
    """第二处退码分支（异常形态 .info.retcode）：码同样不许丢。"""
    class _RaiseBot:
        async def send_private_msg(self, *, user_id: object, message: list[dict]) -> dict:
            raise ActionFailedLike(100, "internal transient C:\\Users\\x")

        async def send_group_msg(self, *, group_id: object, message: list[dict]) -> dict:
            raise ActionFailedLike(100, "internal transient")

    receipt = asyncio.run(
        send_onebot_v11(_RaiseBot(), _chunks_request("req-af-100", ["分片甲"]), timeout_seconds=0.3)
    )
    issue = receipt.operational_issue
    assert issue is not None and issue.kind == "retcode_failure"
    # 100 在终态白名单内 ⇒ 判死；无论判成什么，数字都必须留痕。
    assert "100" in issue.safe_summary
    assert "internal transient" not in issue.safe_summary
    assert receipt.state is ReceiptState.FAILED_FINAL


@pytest.mark.asyncio
async def test_mixed_whole_message_failure_dict_keeps_code_end_to_end(tmp_path) -> None:
    """第三处退码分支（返回失败 dict）＝生产 mixed 告警卡的真形态，端到端带到 part 账。

    mixed 走单次 send_*_msg 多段整发（onebot.py:805-881），失败 dict 不进
    _ChunkRejectedError 臂而落 `not _onebot_result_is_success(result)` 臂——
    即用户报的那枚 req_358d05bb0f05 形状（parts_total=2、attempts=1）。
    """
    name = "reason_mixed_e2e.sqlite3"
    queue = _build_queue(tmp_path, name)
    base = _utc_now()
    queue.submit(_mixed_request("req-mixed-e2e"), now=base)
    bot = RejectingOneBot(
        {"部件甲": {"status": "failed", "retcode": 1200, "wording": "no sink C:\\Users\\x"}}
    )

    await drain_send_queue_once(queue, _transport(bot), now=base + timedelta(seconds=120))

    rows = _part_rows(tmp_path, name, "req-mixed-e2e")
    assert rows and all(r["state"] == "failed_final" for r in rows)
    assert all(r["last_error_kind"] == "retcode_failure" for r in rows)
    assert all("1200" in str(r["last_error_detail"]) for r in rows)
    assert all("no sink" not in str(r["last_error_detail"]) for r in rows)


def test_non_retcode_issue_summary_untouched() -> None:
    """零破坏面：不带退码的既有分支 safe_summary 仍逐字等于 kind。"""
    bot = RejectingOneBot({})
    receipt = asyncio.run(
        send_onebot_v11(bot, _chunks_request("req-clean", ["分片甲"]), timeout_seconds=0.3)
    )
    assert receipt.state is ReceiptState.SENT
    channel_request = _chunks_request("req-scope", ["分片甲"]).model_copy(
        update={"target_scope": SessionType.CHANNEL}
    )
    unsupported = asyncio.run(send_onebot_v11(bot, channel_request, timeout_seconds=0.3))
    issue = unsupported.operational_issue
    assert issue is not None and issue.kind == "unsupported_target"
    assert issue.safe_summary == "unsupported_target"


# ==================== A2：退码上 part 明细账（additive 列，重启仍可读）====================


def test_part_detail_column_is_additive_and_idempotent(tmp_path) -> None:
    """旧库（无该列）打开即补列；重复打开不报错、已写的值不丢。"""
    name = "reason_ledger.sqlite3"
    queue = _build_queue(tmp_path, name)
    base = _utc_now()
    queue.submit(_chunks_request("req-col", CHUNKS), now=base)
    queue.ensure_parts_planned("req-col", ["d1", "d2"], now=base)
    assert queue.mark_part_failed_final(
        "req-col", 0, error_kind="retcode_failure", error_detail="retcode=403", now=base
    )

    _build_queue(tmp_path, name)  # 第二次 _ensure_schema：ALTER 必须跳过（幂等）
    rows = _part_rows(tmp_path, name, "req-col")
    assert rows[0]["last_error_detail"] == "retcode=403"  # 重开之后仍在＝重启仍可读


def test_part_detail_stays_none_when_not_supplied(tmp_path) -> None:
    """不传 detail 的既有调用零破坏：列写 NULL，不造「无原因」假串。"""
    name = "reason_default.sqlite3"
    queue = _build_queue(tmp_path, name)
    base = _utc_now()
    queue.submit(_chunks_request("req-plain", CHUNKS), now=base)
    queue.ensure_parts_planned("req-plain", ["d1", "d2"], now=base)
    assert queue.mark_part_failed_final("req-plain", 0, error_kind="x", now=base)
    assert queue.mark_part_unknown("req-plain", 1, error_kind="y", now=base)
    rows = _part_rows(tmp_path, name, "req-plain")
    assert all(r["last_error_detail"] is None for r in rows)


def test_part_detail_is_length_bounded(tmp_path) -> None:
    """写侧自截：超长结构因截到 96 字符入库，不把明细账撑成正文仓库。"""
    name = "reason_bound.sqlite3"
    queue = _build_queue(tmp_path, name)
    base = _utc_now()
    queue.submit(_chunks_request("req-long", CHUNKS), now=base)
    queue.ensure_parts_planned("req-long", ["d1", "d2"], now=base)
    assert queue.mark_part_failed_final(
        "req-long", 0, error_kind="retcode_failure", error_detail="r" * 400, now=base
    )
    assert len(str(_part_rows(tmp_path, name, "req-long")[0]["last_error_detail"])) <= 96


# ==================== A1+A2 合流：真链路把退码一路带到 part 账 ====================


@pytest.mark.asyncio
async def test_drain_threads_retcode_reason_into_mixed_parts(tmp_path) -> None:
    """生产 79/79 枚终态行的形态＝mixed 原子整发臂；detail 必须跟到 part 账与请求行。"""
    name = "reason_drain.sqlite3"
    queue = _build_queue(tmp_path, name)
    base = _utc_now()
    queue.submit(_mixed_request("req-drain-term"), now=base)
    calls: list[str] = []

    async def transport(send_request: SendRequest):
        calls.append(send_request.request_id)
        return _receipt_for(
            send_request,
            state=ReceiptState.FAILED_FINAL,
            issue=_issue("retcode_failure", retryable=False, safe_summary=DETAIL_403),
        )

    await drain_send_queue_once(queue, transport, now=base + timedelta(seconds=120))

    rows = _part_rows(tmp_path, name, "req-drain-term")
    assert [r["part_index"] for r in rows] == [0, 1]
    for row in rows:
        assert row["state"] == "failed_final"
        assert row["last_error_kind"] == "retcode_failure"
        assert "403" in str(row["last_error_detail"])
    # 请求行侧：落进 request_json 的 operational_issue 也要带码（重启后的取证面）。
    assert "403" in str(_request_row(tmp_path, name, "dedupe-req-drain-term")["request_json"])
    assert calls == ["req-drain-term", "req-drain-term-textfb"]
    # ^ mixed 原子整发一轮 + W1 文字兜底伴发件，**没有**第二次整发重投。


@pytest.mark.asyncio
async def test_chunk_per_part_terminal_keeps_detail(tmp_path) -> None:
    """chunks 逐段臂（另一条投递通路）同样带上结构因；后续段仍按既有语义留 PENDING。"""
    name = "reason_chunk.sqlite3"
    queue = _build_queue(tmp_path, name)
    base = _utc_now()
    queue.submit(_chunks_request("req-chunk-term", CHUNKS), now=base)
    bot = RejectingOneBot({"分片甲": {"status": "failed", "retcode": 403}})

    await drain_send_queue_once(queue, _transport(bot), now=base + timedelta(seconds=120))

    rows = _part_rows(tmp_path, name, "req-chunk-term")
    by_index = {r["part_index"]: r for r in rows}
    assert by_index[0]["state"] == "failed_final"
    assert "403" in str(by_index[0]["last_error_detail"])
    # 既有判据一字不动：明确终败即停止后续段（连接可能已不可靠）。
    assert by_index[1]["state"] == "pending"
    assert by_index[1]["attempts"] == 0


@pytest.mark.asyncio
async def test_result_unknown_parts_still_never_retry(tmp_path) -> None:
    """富化 safe_summary 之后，result_unknown 仍走 UNKNOWN→PARTIAL（M-63 红线不放宽）。"""
    name = "reason_unknown.sqlite3"
    queue = _build_queue(tmp_path, name)
    base = _utc_now()
    queue.submit(_mixed_request("req-unknown"), now=base)
    calls: list[str] = []

    async def transport(send_request: SendRequest):
        calls.append(send_request.request_id)
        return _receipt_for(
            send_request,
            state=ReceiptState.FAILED_FINAL,
            issue=_issue(
                "result_unknown", retryable=False, safe_summary="result_unknown retcode=100"
            ),
        )

    await drain_send_queue_once(queue, transport, now=base + timedelta(seconds=120))

    rows = _part_rows(tmp_path, name, "req-unknown")
    assert rows and all(r["state"] == "unknown" for r in rows)
    assert all("100" in str(r["last_error_detail"]) for r in rows)
    assert str(_request_row(tmp_path, name, "dedupe-req-unknown")["state"]) == "partial"
    assert calls == ["req-unknown"]  # UNKNOWN 绝不当可重投放行（不双发）


# ==================== C：兄弟行 part 账不互踩（worker 终态臂缺 dedupe_key）==========


@pytest.mark.asyncio
async def test_terminal_sibling_does_not_hijack_other_row_ledger(tmp_path) -> None:
    """同 request_id 两行（生产 7 组实锤，error_report ack/card 共键）。

    A 行平台明确拒绝、B 行全部送达 ⇒ 两行各自的 part 账只许反映自己的结局。
    worker 终态臂少传 dedupe_key 时按「最新行」启发式解析身份 ⇒ A 的终态写
    扇到 B 的账上（B 已送达段被踩成终态 / A 自己留 PENDING 幽灵终态行），
    B 的断点续发从此打死。判定与状态值一字未动，只补寻址。
    """
    name = "reason_sibling.sqlite3"
    queue = _build_queue(tmp_path, name)
    base = _utc_now()
    queue.submit(_mixed_request("req-dup", dedupe_key="dk-A", parts=[
        {"type": "text", "text": "A1"}, {"type": "text", "text": "A2"}]), now=base)
    queue.submit(
        _mixed_request(
            "req-dup",
            dedupe_key="dk-B",
            parts=[{"type": "text", "text": "B1"}, {"type": "text", "text": "B2"}],
        ),
        now=base + timedelta(milliseconds=1),
    )

    async def transport(send_request: SendRequest):
        if send_request.dedupe_key == "dk-A":
            return _receipt_for(
                send_request,
                state=ReceiptState.FAILED_FINAL,
                issue=_issue("retcode_failure", retryable=False, safe_summary=DETAIL_403),
            )
        return _receipt_for(send_request, state=ReceiptState.SENT, issue=None)

    await drain_send_queue_once(queue, transport, now=base + timedelta(seconds=120))

    rows = _part_rows(tmp_path, name, "req-dup")
    a_rows = [r for r in rows if r["dedupe_key"] == "dk-A"]
    b_rows = [r for r in rows if r["dedupe_key"] == "dk-B"]
    assert a_rows and b_rows, "两行各自的 part 账都必须存在"
    assert all(r["state"] == "failed_final" for r in a_rows), [
        (r["dedupe_key"], r["part_index"], r["state"]) for r in a_rows
    ]
    assert all("403" in str(r["last_error_detail"]) for r in a_rows)
    # B 行成功 ⇒ B 的每一段都得是 sent，绝不被兄弟行的失败踩成终态。
    assert all(r["state"] == "sent" for r in b_rows), [
        (r["dedupe_key"], r["part_index"], r["state"]) for r in b_rows
    ]
    assert str(_request_row(tmp_path, name, "dk-B")["state"]) == "sent"


# ==================== 反向锁：终态臂不新增重投、不放宽退码语义 ====================


@pytest.mark.asyncio
async def test_terminal_parts_do_not_reach_retry_budget(tmp_path) -> None:
    """终态臂行为不变：一次判定即终态（宁快不双发的既有裁定保持），每段只烧 1 次尝试。"""
    name = "reason_budget.sqlite3"
    queue = _build_queue(tmp_path, name)
    base = _utc_now()
    queue.submit(_mixed_request("req-onceround"), now=base)
    calls: list[str] = []

    async def transport(send_request: SendRequest):
        calls.append(send_request.request_id)
        return _receipt_for(
            send_request,
            state=ReceiptState.FAILED_FINAL,
            issue=_issue("retcode_failure", retryable=False, safe_summary=DETAIL_403),
        )

    await drain_send_queue_once(queue, transport, now=base + timedelta(seconds=120))

    rows = _part_rows(tmp_path, name, "req-onceround")
    assert rows and all(r["attempts"] == 1 for r in rows)
    assert calls == ["req-onceround", "req-onceround-textfb"]
    # 白名单成员没被本批改判：终态回执仍把请求行直接落 FAILED_FINAL。
    assert str(_request_row(tmp_path, name, "dedupe-req-onceround")["state"]) == "failed_final"


class _RecordingQueue:
    """透明代理：把 worker 每次段级写用的行身份录下来（Q-G5 接线锁，非行为锁）。

    兄弟行共 request_id 时，「终态写有没有带 dedupe_key」决定了账落在哪本账上；
    单靠落库状态反推会被认领次序与启发式掩盖（本席实测：去掉 **dkw 后 drain
    仍绿，而独立探针复现出「请求行 failed_final、段账全 pending」的幽灵终态行，
    见 cache/seat-sendterm/dbg/dbg3_poison.json）。故这里直接钉住调用面：
    **每一次 mark_part_* 都必须携带被认领那行的身份**。
    """

    def __init__(self, inner: SQLiteSendRequestQueue) -> None:
        self._inner = inner
        self.part_calls: list[tuple[str, str | None, str | None]] = []

    def __getattr__(self, name: str):
        return getattr(self._inner, name)

    def mark_part_attempt(self, request_id: str, part_index: int, **kwargs):
        self.part_calls.append(("mark_part_attempt", kwargs.get("dedupe_key"), None))
        return self._inner.mark_part_attempt(request_id, part_index, **kwargs)

    def mark_part_sent(self, request_id: str, part_index: int, **kwargs):
        self.part_calls.append(("mark_part_sent", kwargs.get("dedupe_key"), None))
        return self._inner.mark_part_sent(request_id, part_index, **kwargs)

    def mark_part_unknown(self, request_id: str, part_index: int, **kwargs):
        self.part_calls.append(
            ("mark_part_unknown", kwargs.get("dedupe_key"), kwargs.get("error_detail"))
        )
        return self._inner.mark_part_unknown(request_id, part_index, **kwargs)

    def mark_part_failed_final(self, request_id: str, part_index: int, **kwargs):
        self.part_calls.append(
            ("mark_part_failed_final", kwargs.get("dedupe_key"), kwargs.get("error_detail"))
        )
        return self._inner.mark_part_failed_final(request_id, part_index, **kwargs)

    def mark_part_pending(self, request_id: str, part_index: int, **kwargs):
        self.part_calls.append(("mark_part_pending", kwargs.get("dedupe_key"), None))
        return self._inner.mark_part_pending(request_id, part_index, **kwargs)


@pytest.mark.asyncio
async def test_every_part_write_carries_row_identity(tmp_path) -> None:
    """每一条段级写都按行身份寻址（治 mixed 终态臂独漏 **dkw，判定值一字未动）。"""
    name = "reason_identity.sqlite3"
    queue = _build_queue(tmp_path, name)
    base = _utc_now()
    queue.submit(_mixed_request("req-dup", dedupe_key="dk-A"), now=base)
    queue.submit(
        _mixed_request(
            "req-dup",
            dedupe_key="dk-B",
            parts=[{"type": "text", "text": "B1"}, {"type": "text", "text": "B2"}],
        ),
        now=base + timedelta(milliseconds=1),
    )
    recorder = _RecordingQueue(queue)

    async def transport(send_request: SendRequest):
        if send_request.dedupe_key == "dk-A":
            return _receipt_for(
                send_request,
                state=ReceiptState.FAILED_FINAL,
                issue=_issue("retcode_failure", retryable=False, safe_summary=DETAIL_403),
            )
        return _receipt_for(send_request, state=ReceiptState.SENT, issue=None)

    await drain_send_queue_once(recorder, transport, now=base + timedelta(seconds=120))

    terminal = [c for c in recorder.part_calls if c[0] == "mark_part_failed_final"]
    assert terminal, "终态臂必须真的写过段级账（否则本锁空转）"
    assert all(dedup is not None for _, dedup, _ in recorder.part_calls), recorder.part_calls
    # detail 只随终态/未知写走，且等于回执 safe_summary 的增量段。
    assert all(d == DETAIL_403 for _, _, d in terminal), terminal
    assert all(r["state"] == "failed_final" for r in _part_rows(tmp_path, name, "req-dup")
               if r["dedupe_key"] == "dk-A")


def test_terminal_whitelist_membership_unchanged() -> None:
    """退码白名单成员集**本席一律不动**（判据未成立，见本席报告 §B）。

    锁的是「别顺手放宽」：这三枚是既有裁定成员，摘除任一枚都必须带着真机
    退码分布证据另案施工（scripts/tts_retcode_collect.py，或本席 A2 落库的
    last_error_detail 读数，才是取证面）。
    """
    from plugins.bot_unified_runtime.domains.transport.sender.onebot import (
        _is_final_failure_retcode,
    )

    assert _is_final_failure_retcode(403) is True
    assert _is_final_failure_retcode(100) is True
    assert _is_final_failure_retcode(1400) is True
    assert _is_final_failure_retcode(500) is False
    assert _is_final_failure_retcode(None) is False
