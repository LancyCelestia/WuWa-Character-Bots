"""审计修复 A 组回归：发送队列 / 转发渲染 / 聊天文本规整。

离线运行（SQLite 用 tmp_path，无网络、无 Playwright）：

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_auditfix_sender_queue.py -q

覆盖项：
- A1 submit 写入认领宽限期：submit 后立即 claim_due 不得拿到该行。
- A3 去重原子化：重复 dedupe_key 返回 SKIPPED 回执，不抛 IntegrityError。
- A4 prune 只淘汰终态：QUEUED 行永不因容量被时间序挤掉。
- A5 租约过期重认领递增 retry_count，达 max_attempts 置 FAILED_FINAL。
- A14 forward 溢出合并后仍不突破 node_chars 硬边界。
- A15 聊天文本："$5 和 $10" 货币写法不被当公式改写；真实 TeX 仍转换。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.contracts import (
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.domains.transport.sender.queue import (
    SQLiteSendRequestQueue,
)
from plugins.bot_unified_runtime.output.plain_text import naturalize_chat_text
from plugins.bot_unified_runtime.output.renderer import split_text_chunks


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _send_request(
    request_id: str,
    dedupe_key: str,
    *,
    text: str = "审计修复回归正文",
) -> SendRequest:
    rendered = RenderedOutput(
        request_id=request_id,
        content_type="text",
        content_ref={"text": text},
        text_fallback=text,
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
        max_messages=1,
        dedupe_key=dedupe_key,
        cooldown_key="bot.chat:private:user-1",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="default",
    )


def _build_queue(tmp_path: Path, *, max_items: int = 1000) -> SQLiteSendRequestQueue:
    return SQLiteSendRequestQueue(
        tmp_path / "send_queue.sqlite3",
        InMemoryAuditLogger(),
        max_items=max_items,
    )


def test_a1_submit_row_not_claimable_immediately(tmp_path) -> None:
    """A1：submit 后立即认领必须拿不到行（内联投递宽限期）。"""
    queue = _build_queue(tmp_path)
    request = _send_request("req-a1", "dedupe-a1")
    receipt = queue.submit(request)
    assert receipt.state is ReceiptState.QUEUED
    assert queue.claim_due() == []
    assert queue.list_due() == []
    # 宽限期过后（模拟进程重启丢内联投递），worker 接管。
    future = _utc_now() + timedelta(seconds=queue.retry_base_seconds * 10)
    claimed = queue.claim_due(now=future)
    assert len(claimed) == 1
    assert claimed[0].send_request.request_id == "req-a1"


def test_a3_duplicate_dedupe_returns_skipped_not_crash(tmp_path) -> None:
    """A3：重复 dedupe_key 走 ON CONFLICT 原子路径，返回 SKIPPED 回执。"""
    queue = _build_queue(tmp_path)
    first = queue.submit(_send_request("req-a3-1", "dedupe-a3"))
    second = queue.submit(_send_request("req-a3-2", "dedupe-a3"))
    assert first.state is ReceiptState.QUEUED
    assert second.state is ReceiptState.SKIPPED
    assert second.public_message == "duplicate dedupe_key"
    summary = queue.safe_summary()
    assert summary[ReceiptState.QUEUED.value] == 1
    assert summary[ReceiptState.SKIPPED.value] == 0


def test_a4_prune_never_drops_non_terminal_rows(tmp_path) -> None:
    """A4：容量淘汰只删终态行；QUEUED 行超容量后仍保留。"""
    queue = _build_queue(tmp_path, max_items=2)
    base = _utc_now()
    old_sent = _send_request("req-a4-sent", "dedupe-a4-sent")
    queue.submit(old_sent, now=base)
    queue.mark_sent(old_sent.request_id, "sent", now=base)
    # 两条 QUEUED（次序靠后会挤掉终态的 sent 行，但不能挤掉彼此）。
    queue.submit(_send_request("req-a4-q1", "dedupe-a4-q1"), now=base + timedelta(seconds=1))
    queue.submit(_send_request("req-a4-q2", "dedupe-a4-q2"), now=base + timedelta(seconds=2))
    queue.submit(_send_request("req-a4-q3", "dedupe-a4-q3"), now=base + timedelta(seconds=3))
    summary = queue.safe_summary()
    assert summary[ReceiptState.QUEUED.value] == 3
    assert summary[ReceiptState.SENT.value] == 0
    # 终态行确实会被淘汰（对照组：容量 2 只留最新 2 条，SENT 行被清）。
    assert queue.find_request("req-a4-sent") is None
    assert queue.find_request("req-a4-q1") is not None
    assert queue.find_request("req-a4-q3") is not None


def test_a5_lease_reclaim_increments_retry_and_finalizes(tmp_path) -> None:
    """A5：租约过期重认领递增 retry_count，达 max_attempts 置终态不再投。"""
    queue = _build_queue(tmp_path)  # max_attempts=3（默认）
    request = _send_request("req-a5", "dedupe-a5")
    base = _utc_now()
    queue.submit(request, now=base)
    # 第 1 次认领（宽限期后）。
    first = queue.claim_due(now=base + timedelta(seconds=120))
    assert len(first) == 1 and first[0].retry_count == 0
    # 租约 60s 过期后第 2 次认领：重认领递增 retry_count。
    second = queue.claim_due(now=base + timedelta(seconds=200))
    assert len(second) == 1 and second[0].retry_count == 1
    # 第 3 次认领：retry_count=2，仍可投。
    third = queue.claim_due(now=base + timedelta(seconds=280))
    assert len(third) == 1 and third[0].retry_count == 2
    # 第 4 次：retry_count 达 max_attempts=3 → 置 FAILED_FINAL，不再返回。
    fourth = queue.claim_due(now=base + timedelta(seconds=360))
    assert fourth == []
    entry = queue._find_entry_by_request_id("req-a5")
    assert entry is not None
    assert entry.state is ReceiptState.FAILED_FINAL
    assert entry.retry_count == 3
    summary = queue.safe_summary()
    assert summary[ReceiptState.FAILED_FINAL.value] == 1
    assert summary["processing"] == 0


def test_a14_merged_overflow_respects_node_chars_limit() -> None:
    """A14：max_nodes 溢出反复合并后，尾块仍不突破 node_chars 硬边界。"""
    node_chars = 100
    paragraph = "字" * 60
    text = "\n".join(paragraph for _ in range(5))
    chunks = split_text_chunks(text, node_chars=node_chars, max_nodes=2)
    assert len(chunks) > 2  # 硬边界优先于节点数上限，宁超块数不超长度
    assert all(len(chunk) <= node_chars for chunk in chunks)
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")


def test_a15_currency_dollars_not_treated_as_math() -> None:
    """A15："$5 和 $10" 这类货币写法不再被当公式改写。"""
    value = naturalize_chat_text("价格 $5 和 $10")
    assert value == "价格 $5 和 $10"


def test_a15_real_tex_still_converted() -> None:
    """A15：真实 TeX（$...$ 与行级 \\frac）仍被确定性转换。"""
    inline = naturalize_chat_text("$a+b$")
    assert "加" in inline
    frac = naturalize_chat_text("$\\frac{a}{b}$")
    assert "分子为" in frac and "分母为" in frac
    # 行级规则只转换 TeX 命令 token，行内其余文字（含普通连字符）保留。
    line = naturalize_chat_text("成本-收益 \\frac{a}{b} 分析")
    assert "成本-收益" in line
    assert "分析" in line
    assert "分子为" in line
