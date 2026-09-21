"""2026-09-15 生产实弹 bug 回归：媒体段被平台明确拒绝的重试风暴 + 零反馈。

事故（审计库 wuwa_audit.sqlite3 实证）：
- 13:00 账单报告（mixed [image, text]）→ NapCat 时期 ``result:-1 rich media
  transfer failed`` 整条 API 调用拒绝；NoneBot 以 ActionFailed 异常上抛。
- onebot 内联短退避（0.8/1.6s）把「明确拒绝」当瞬时异常重试 → 每轮 3 连发；
  队列级 3 次尝试 → 3 轮 × 3 发 = 9 发/人（3 管理员 27 发）。
- 终败后无任何文本降级 → 管理员零反馈。

修法语义（本文件锁死）：
1. 平台明确拒绝（异常 .info 带 retcode，即 ActionFailed 形态）→ 立即按
   retcode_failure 回执交还队列级真退避（不再内联 3 连发）；
   瞬时异常（无 retcode 形态）保持既有内联短退避 3 次语义不变。
2. 请求终败（FAILED_FINAL 且非 PARTIAL）且末次失败为明确拒绝时，worker
   一次性回退纯文本（mixed 文本部件 / image 的 text_fallback）——
   result_unknown（可能已送达）绝不回退，防重复投递。

离线运行：

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_media_rejection_retry_and_fallback.py -q
"""

from __future__ import annotations

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
from plugins.bot_unified_runtime.sender.onebot import send_onebot_v11
from plugins.bot_unified_runtime.sender.queue import SQLiteSendRequestQueue
from plugins.bot_unified_runtime.sender.worker import drain_send_queue_once

T0 = datetime(2026, 9, 15, 5, 0, 0, tzinfo=timezone.utc)


class FakeActionFailed(Exception):
    """NoneBot ActionFailed 的形态替身：retcode 落在 .info（生产实证形态）。"""

    def __init__(self, retcode: int) -> None:
        super().__init__(f"ActionFailed retcode={retcode}")
        self.info = {"status": "failed", "retcode": retcode}


class RejectingBot:
    """image 段一律以明确拒绝（rich media transfer failed 形态）失败。

    记录 image 调用与 text 调用次数；拒绝发生在 image 段 → text 段未送达
    （与生产一致：NapCat 时期对 mixed 整条 API 调用因 image 失败整体拒绝）。
    """

    def __init__(self, *, image_failures: int | None = None) -> None:
        self.image_calls = 0
        self.text_calls = 0
        self._image_failures_left = image_failures

    async def send_private_msg(self, *, user_id: object, message: list[dict]) -> dict:
        for segment in message:
            if segment.get("type") == "image":
                self.image_calls += 1
                if self._image_failures_left is None or self._image_failures_left > 0:
                    if self._image_failures_left is not None:
                        self._image_failures_left -= 1
                    raise FakeActionFailed(-1)
                continue
            if segment.get("type") == "text":
                self.text_calls += 1
        return {"status": "ok", "retcode": 0, "message_id": "mid-1"}

    async def send_group_msg(self, *, group_id: object, message: list[dict]) -> dict:
        return await self.send_private_msg(user_id=group_id, message=message)


class TransientBot:
    """无 retcode 形态的瞬时异常（断连/超时类），记录调用次数。"""

    def __init__(self) -> None:
        self.calls = 0

    async def send_private_msg(self, *, user_id: object, message: list[dict]) -> dict:
        self.calls += 1
        raise RuntimeError("websocket closed")

    async def send_group_msg(self, *, group_id: object, message: list[dict]) -> dict:
        return await self.send_private_msg(user_id=group_id, message=message)


def _mixed_image_text_request(request_id: str = "req-mixed-1") -> SendRequest:
    rendered = RenderedOutput(
        request_id=request_id,
        content_type="mixed",
        content_ref={
            "parts": [
                {"type": "image", "file": "C:/rt/data/cards/usage_report_x.png"},
                {"type": "text", "text": "[预警] 模型用量账单报告 · 账单 1.23 元"},
            ]
        },
        text_fallback="[预警] 模型用量账单报告 · 账单 1.23 元",
        privacy_level=PrivacyLevel.PERSONAL,
    )
    return SendRequest(
        request_id=request_id,
        session_id="private:admin-1",
        target_scope=SessionType.PRIVATE,
        target_id="admin-1",
        capability_id="bot.alert",
        content=rendered,
        send_policy=SendPolicy.IMMEDIATE,
        priority="high",
        max_messages=1,
        dedupe_key=f"dedupe-{request_id}",
        cooldown_key="bot.alert:private:admin-1",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="runtime",
    )


def _image_only_request(request_id: str = "req-img-1") -> SendRequest:
    rendered = RenderedOutput(
        request_id=request_id,
        content_type="image",
        content_ref={"file": "C:/rt/data/cards/usage_report_x.png"},
        text_fallback="[预警] 卡片纯文本版 · 账单 1.23 元",
        privacy_level=PrivacyLevel.PERSONAL,
    )
    request = _mixed_image_text_request(request_id)
    return request.model_copy(update={"content": rendered})


def _onebot_transport(bot: object):
    async def _send(send_request: SendRequest):
        return await send_onebot_v11(bot, send_request, timeout_seconds=2.0)

    return _send


def _build_queue(tmp_path: Path, name: str = "queue.sqlite3") -> SQLiteSendRequestQueue:
    # retry_base=1/retry_max=2：退避用显式 now 跨越（既有测试同款手法）。
    return SQLiteSendRequestQueue(
        tmp_path / name,
        InMemoryAuditLogger(),
        retry_base_seconds=1,
        retry_max_seconds=2,
    )


def test_platform_rejection_exception_no_inline_retry() -> None:
    """明确拒绝（ActionFailed 形态）→ 恰好 1 次 API 调用，立即回执可重试失败。"""
    bot = RejectingBot()
    request = _image_only_request()

    async def _run() -> None:
        receipt = await send_onebot_v11(bot, request, timeout_seconds=2.0)
        assert receipt.state is ReceiptState.FAILED_RETRYABLE
        assert receipt.operational_issue is not None
        assert receipt.operational_issue.kind == "retcode_failure"
        assert receipt.operational_issue.retryable is True

    import asyncio

    asyncio.run(_run())
    assert bot.image_calls == 1, "明确拒绝不得内联重试（事故中 3 连发的根因）"


def test_transient_exception_keeps_inline_retry() -> None:
    """无 retcode 的瞬时异常保持既有内联短退避 3 次语义（回归守卫）。"""
    bot = TransientBot()
    request = _image_only_request()

    async def _run() -> None:
        receipt = await send_onebot_v11(bot, request, timeout_seconds=2.0)
        assert receipt.state is ReceiptState.FAILED_RETRYABLE
        assert receipt.operational_issue is not None
        assert receipt.operational_issue.kind == "send_exception"

    import asyncio

    asyncio.run(_run())
    assert bot.calls == 3, "瞬时异常保持 3 次内联尝试（0.8/1.6s 退避）"


def test_worker_media_final_failure_falls_back_to_text_once(tmp_path: Path) -> None:
    """确定性媒体失败：3 轮 × 1 发的退避节奏 + 终败文本降级恰好一次。"""
    queue = _build_queue(tmp_path)
    bot = RejectingBot()
    request = _mixed_image_text_request()
    # deliver_after=T0：声明无内联首投（与管理员告警链装配一致），worker 到点认领。
    queue.submit(request, now=T0, deliver_after=T0)
    transport = _onebot_transport(bot)

    async def _run() -> None:
        # 第 1 轮：image 拒绝 → rc=1 → backoff(1)=1s。
        await drain_send_queue_once(queue, transport, now=T0 + timedelta(seconds=1))
        # 第 2 轮：rc=2 → backoff(2)=2s。
        await drain_send_queue_once(queue, transport, now=T0 + timedelta(seconds=4))
        # 第 3 轮：rc=3 ≥ max_attempts → FAILED_FINAL + 文本降级。
        result = await drain_send_queue_once(
            queue, transport, now=T0 + timedelta(seconds=7)
        )
        assert result.final_failed == 1
        # 第 4 轮：终态行不再认领，不得再发任何内容。
        await drain_send_queue_once(queue, transport, now=T0 + timedelta(seconds=9))

    import asyncio

    asyncio.run(_run())
    assert bot.image_calls == 3, "每轮恰好 1 发（事故中每轮 3 连发 = 内联重试放大）"
    assert bot.text_calls == 1, "终败文本降级恰好一次"
    entry_rows = [
        row
        for row in queue.safe_summary().items()
        if row[0] == "failed_final"
    ]
    assert entry_rows and entry_rows[0][1] == 1


def test_worker_fallback_text_uses_mixed_text_part(tmp_path: Path) -> None:
    """降级文本取 mixed 文本部件（预警五要素），管理员拿到数字而非零反馈。"""
    queue = _build_queue(tmp_path, "q2.sqlite3")
    sent_texts: list[str] = []

    class CaptureBot(RejectingBot):
        async def send_private_msg(self, *, user_id: object, message: list[dict]) -> dict:
            # 只对真正送达的消息计数：mixed 消息在 image 段即被 super() 拒绝
            # （与生产一致，text 段未送达），不得计入降级文本。
            if not any(segment.get("type") == "image" for segment in message):
                for segment in message:
                    if segment.get("type") == "text":
                        sent_texts.append(str(segment["data"]["text"]))
            return await super().send_private_msg(user_id=user_id, message=message)

    bot = CaptureBot()
    request = _mixed_image_text_request("req-mixed-2")
    queue.submit(request, now=T0, deliver_after=T0)
    transport = _onebot_transport(bot)

    async def _run() -> None:
        for offset in (1, 4, 7):
            await drain_send_queue_once(
                queue, transport, now=T0 + timedelta(seconds=offset)
            )

    import asyncio

    asyncio.run(_run())
    assert bot.image_calls == 3
    assert sent_texts == ["[预警] 模型用量账单报告 · 账单 1.23 元"]


def test_worker_result_unknown_never_text_fallback(tmp_path: Path) -> None:
    """result_unknown（可能已送达）终败绝不回退文本，防重复投递。"""
    queue = _build_queue(tmp_path, "q3.sqlite3")
    sent_texts: list[str] = []

    async def transport(send_request: SendRequest):
        if send_request.content.content_type == "text":
            sent_texts.append(send_request.content.text_fallback)
            from plugins.bot_unified_runtime.contracts import DeliveryReceipt

            return DeliveryReceipt(
                request_id=send_request.request_id,
                state=ReceiptState.SENT,
                transport="scripted",
                public_message="sent",
            )
        from plugins.bot_unified_runtime.contracts import (
            DeliveryReceipt,
            OperationalIssue,
        )

        return DeliveryReceipt(
            request_id=send_request.request_id,
            state=ReceiptState.FAILED_FINAL,
            transport="scripted",
            public_message="",
            operational_issue=OperationalIssue(
                stage="onebot",
                kind="result_unknown",
                retryable=False,
                safe_summary="result_unknown",
            ),
        )

    request = _image_only_request("req-img-unknown")
    queue.submit(request, now=T0, deliver_after=T0)

    async def _run() -> None:
        await drain_send_queue_once(queue, transport, now=T0 + timedelta(seconds=1))

    import asyncio

    asyncio.run(_run())
    assert sent_texts == [], "结果未知不得回退文本（图片可能已送达）"


def test_worker_retryable_rounds_do_not_fallback_early(tmp_path: Path) -> None:
    """前两轮可重试失败（非终败）不得提前回退文本（保住图片重试机会）。"""
    queue = _build_queue(tmp_path, "q4.sqlite3")
    bot = RejectingBot()
    request = _mixed_image_text_request("req-mixed-3")
    queue.submit(request, now=T0, deliver_after=T0)
    transport = _onebot_transport(bot)

    async def _run() -> None:
        await drain_send_queue_once(queue, transport, now=T0 + timedelta(seconds=1))

    import asyncio

    asyncio.run(_run())
    assert bot.image_calls == 1
    assert bot.text_calls == 0, "非终败轮次不回退文本"


@pytest.mark.parametrize("content_type", ["mixed", "image"])
def test_fallback_text_extraction(content_type: str) -> None:
    from plugins.bot_unified_runtime.sender.worker import _fallback_text_for_media

    request = _mixed_image_text_request()
    if content_type == "image":
        request = _image_only_request()
    text = _fallback_text_for_media(request)
    assert text == "[预警] 模型用量账单报告 · 账单 1.23 元" or text == (
        "[预警] 卡片纯文本版 · 账单 1.23 元"
    )
    # 无可用文本 → None（不构造空消息）。
    bare = _image_only_request()
    bare = bare.model_copy(
        update={
            "content": bare.content.model_copy(update={"text_fallback": "  "}),
        }
    )
    assert _fallback_text_for_media(bare) is None
