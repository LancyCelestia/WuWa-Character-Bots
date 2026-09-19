"""离线语音队列仿真器（Wave H 先遣件，席号 T65）。

目的：让 Wave H（传输层施工）的 RED 用例零等待落地——假 OneBot bot + 可注入
失败行为 + tmp_path SQLite 队列 + 同步泵 + 断言辅助，全部离线、零真实网络、
零墙钟断言。接口按 report-T55.md §五 的 8 例 RED（R1-R8）需要反推。

蓝本与纪律（与 tests/test_part_idempotent_resume.py 同族惯例）：
- 假 bot 按**脚本逐调用**返回/抛出：成功 dict / failed dict（SnowLuma
  ``{status, retcode, data, wording}`` 形态）/ ActionFailed 形态异常
  （retcode 藏 ``.info``，NoneBot 2.5.0 实证形态）/ 无 .info 的瞬时异常
  （断连/网络类）/ 超时（sleep 超过传输预算，由外层 wait_for 裁决）。
- **dispatch 台账**（每次调用的段数组快照）是主断言对象。
- SQLite 队列落 ``tmp_path``；重试/退避用**显式 now 步进**跨越，不碰墙钟。
- RED 用例记得先 ``freeze_inline_retries(monkeypatch)`` 消灭 0.8/1.6s sleep
  （保留 3 次内联尝试语义，只清零间隔）。

本 helper 只 import 生产 transport 的公开面；唯一私有符号耦合是
``onebot._ONEBOT_SEND_RETRY_DELAYS``（freeze 用，见 freeze_inline_retries）。
"""

from __future__ import annotations

import asyncio
import copy as _copy
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.contracts import (
    DeliveryReceipt,
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.domains.transport.sender import (
    onebot as onebot_sender,
)
from plugins.bot_unified_runtime.domains.transport.sender.onebot import (
    send_onebot_v11,
)
from plugins.bot_unified_runtime.domains.transport.sender.queue import (
    PART_STATE_FAILED_FINAL,
    PART_STATE_PENDING,
    PART_STATE_SENT,
    PART_STATE_UNKNOWN,
    PARTIAL_ROW_STATE,
    PartProgress,
    QueuedSendRequest,
    SQLiteSendRequestQueue,
)
from plugins.bot_unified_runtime.domains.transport.sender.worker import (
    SendQueueWorkerResult,
    SendTransport,
    drain_send_queue_once,
)

__all__ = [
    "DEFAULT_ROW_COLUMNS",
    "DEFAULT_STEP_SECONDS",
    "DEFAULT_TRANSPORT_TIMEOUT_SECONDS",
    "PARTIAL_ROW_STATE",
    "PART_STATE_FAILED_FINAL",
    "PART_STATE_PENDING",
    "PART_STATE_SENT",
    "PART_STATE_UNKNOWN",
    "Behavior",
    "DispatchCall",
    "FakeActionFailed",
    "ReceiptState",
    "SimulatedOneBotBot",
    "build_chunks_request",
    "build_mixed_request",
    "build_sqlite_queue",
    "dispatch_count",
    "freeze_inline_retries",
    "issue_kind",
    "make_failing_transport",
    "make_transport",
    "part_states",
    "partial_rows",
    "queue_row",
    "read_queue_row",
    "record_files",
    "run_queue_rounds",
    "sent_texts",
    "sim_utc_now",
    "unknown_part_indexes",
]

# 缺省传输超时（秒）：小值让超时/慢回执形态毫秒级仿真（生产 15s 不可用）。
DEFAULT_TRANSPORT_TIMEOUT_SECONDS = 0.3
# 泵轮间显式 now 步进（秒）：120s > max(退避封顶, 90s PARTIAL 补偿退避)，
# 也跨过 60s 内联认领宽限期（submit 后首轮须 now >= submit+60s）。
DEFAULT_STEP_SECONDS = 120.0

# read_queue_row 缺省读取的 send_requests 列。
DEFAULT_ROW_COLUMNS = (
    "state",
    "retry_count",
    "parts_total",
    "parts_delivered",
    "parts_progress",
    "next_retry_at",
    "last_public_message",
)


# ==================== 行为注入 ====================
# Behavior 取值：
#   "ok"                    成功回执 {"status":"ok","retcode":0,...}
#   ("retcode", code)       平台 failed dict（SnowLuma failedResponse 形态）
#   ("action_failed", code) 抛 ActionFailed 形态异常（retcode 在 .info）
#   "raise" / ("raise",)    抛 RuntimeError（无 .info）＝断连/网络类瞬时异常
#   ("raise", exc)          抛给定异常实例（exc 须是 BaseException 实例）
#   "timeout" / ("timeout", seconds)
#                           先 sleep 再成功——sleep 须超过传输超时，由外层
#                           wait_for 裁决超时（仿真「回执慢/丢」形态）
Behavior = Any


class FakeActionFailed(Exception):
    """ActionFailed 形态异常：平台明确拒绝，retcode 藏 ``.info`` dict。

    形态对齐 NoneBot ActionFailed（``onebot._exception_platform_rejection``
    的鸭子探测目标）：``.info = {"status": "failed", "retcode": code,
    "wording": ...}``。wording 字段名遵循 SnowLuma failedResponse 契约
    （report-T46 §3.5；我方现不消费该字段，RED 用例可断言其透传）。
    """

    def __init__(self, retcode: int, wording: str = "") -> None:
        super().__init__(f"action failed retcode={retcode}")
        self.info: dict[str, Any] = {
            "status": "failed",
            "retcode": retcode,
            "wording": wording or f"simulated rejection {retcode}",
        }


@dataclass(frozen=True)
class DispatchCall:
    """一次 bot API 调用的台账记录（段数组深拷贝快照，事后改不动）。"""

    index: int
    method: str  # "send_private_msg" | "send_group_msg"
    target_id: Any  # 经 _coerce_onebot_id 归一后的目标（int 或 str）
    segments: tuple[dict[str, Any], ...]


class SimulatedOneBotBot:
    """假 OneBot v11 bot：记录全部 send 调用序列 + 按脚本注入行为。

    - ``script``：逐调用消费的行为表（先到先得）；
    - ``behavior``：脚本耗尽后的兜底行为（缺省成功）。
    两者都给时脚本优先，耗尽后回落 behavior。
    """

    def __init__(
        self,
        *,
        behavior: Behavior = "ok",
        script: Sequence[Behavior] | None = None,
    ) -> None:
        self.behavior: Behavior = behavior
        self.script: list[Behavior] = list(script or [])
        self.calls: list[DispatchCall] = []

    # ---- OneBot v11 协议面 -------------------------------------------------

    async def send_private_msg(
        self, *, user_id: int | str, message: list[dict[str, Any]]
    ) -> Any:
        return await self._handle("send_private_msg", user_id, message)

    async def send_group_msg(
        self, *, group_id: int | str, message: list[dict[str, Any]]
    ) -> Any:
        return await self._handle("send_group_msg", group_id, message)

    # forward 可选 API 故意不实现：``_call_optional_onebot_api`` 对缺失方法
    # 返回哨兵并降级（与生产 mixed 路径行为一致）；需要 forward 语义的用例
    # 自行子类化补桩。

    # ---- 台账视图 ----------------------------------------------------------

    @property
    def dispatch_count(self) -> int:
        return len(self.calls)

    @property
    def sent_texts(self) -> list[str]:
        """全部调用里 text 段正文（按发出顺序摊平）。"""
        return [
            str(segment["data"]["text"])
            for call in self.calls
            for segment in call.segments
            if segment.get("type") == "text"
        ]

    @property
    def record_files(self) -> list[str]:
        """全部调用里 record 段 file 引用（按发出顺序摊平；语音观测面）。"""
        return [
            str(segment["data"]["file"])
            for call in self.calls
            for segment in call.segments
            if segment.get("type") == "record"
        ]

    def reset(self) -> None:
        """清台账与脚本（保留兜底 behavior）——复用同一 bot 比较两轮。"""
        self.calls.clear()
        self.script.clear()

    # ---- 内部 --------------------------------------------------------------

    async def _handle(
        self, method: str, target_id: int | str, message: list[dict[str, Any]]
    ) -> Any:
        call = DispatchCall(
            index=len(self.calls),
            method=method,
            target_id=target_id,
            segments=tuple(_copy.deepcopy(segment) for segment in message),
        )
        self.calls.append(call)
        behavior = self.script.pop(0) if self.script else self.behavior
        return await self._apply(behavior)

    async def _apply(self, behavior: Behavior) -> Any:
        if behavior == "ok":
            return self._ok_result()
        if isinstance(behavior, str):
            if behavior == "raise":
                raise RuntimeError("simulated connection lost")
            if behavior == "timeout":
                await asyncio.sleep(0.5)
                return self._ok_result()
            raise ValueError(f"unknown behavior spec: {behavior!r}")
        if isinstance(behavior, tuple):
            kind = behavior[0]
            if kind == "retcode":
                return self._failed_result(int(behavior[1]))
            if kind == "action_failed":
                raise FakeActionFailed(int(behavior[1]))
            if kind == "raise":
                if len(behavior) >= 2:
                    exc = behavior[1]
                    if isinstance(exc, BaseException):
                        raise exc
                    if isinstance(exc, type) and issubclass(exc, BaseException):
                        raise exc
                    raise ValueError(
                        f"('raise', ...) expects an exception, got {exc!r}"
                    )
                raise RuntimeError("simulated connection lost")
            if kind == "timeout":
                seconds = float(behavior[1]) if len(behavior) >= 2 else 0.5
                if seconds <= 0:
                    raise ValueError("timeout behavior needs seconds > 0")
                await asyncio.sleep(seconds)
                return self._ok_result()
        raise ValueError(f"unknown behavior spec: {behavior!r}")

    def _ok_result(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "retcode": 0,
            "message_id": f"sim-{len(self.calls)}",
        }

    def _failed_result(self, retcode: int) -> dict[str, Any]:
        # SnowLuma failedResponse 形态：字段名是 wording（report-T46 §3.5）。
        return {
            "status": "failed",
            "retcode": retcode,
            "data": None,
            "wording": f"simulated rejection {retcode}",
        }


# ==================== 请求构造 ====================


def sim_utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _scope_and_ids(
    target_scope: SessionType, target_id: str
) -> tuple[SessionType, str]:
    # 不锁 PRIVATE/GROUP：R8 负样本要构造非私聊/群聊的 mixed（如 CHANNEL）
    # 断言「不计划 part」；生产门在 worker._chunk_part_plan，仿真器不预拦。
    if not isinstance(target_scope, SessionType):
        raise TypeError("target_scope must be a SessionType member")
    return target_scope, target_id


def _rendered(
    request_id: str,
    *,
    content_type: str,
    content_ref: dict[str, Any],
    text_fallback: str,
) -> RenderedOutput:
    return RenderedOutput(
        request_id=request_id,
        content_type=content_type,
        content_ref=content_ref,
        text_fallback=text_fallback,
        privacy_level=PrivacyLevel.PERSONAL,
    )


def _send_request(
    request_id: str,
    content: RenderedOutput,
    *,
    target_scope: SessionType,
    target_id: str,
    dedupe_key: str | None,
) -> SendRequest:
    scope, target_id = _scope_and_ids(target_scope, target_id)
    return SendRequest(
        request_id=request_id,
        session_id=f"{scope.value}:{target_id}",
        target_scope=scope,
        target_id=target_id,
        capability_id="bot.sim.voice",
        content=content,
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key=dedupe_key or f"dedupe-{request_id}",
        cooldown_key=f"bot.sim:{scope.value}:{target_id}",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="default",
    )


def build_mixed_request(
    request_id: str,
    *,
    text: str | None = None,
    record_file: str | None = None,
    parts: list[dict[str, Any]] | None = None,
    target_scope: SessionType = SessionType.PRIVATE,
    target_id: str = "user-1",
    dedupe_key: str | None = None,
) -> SendRequest:
    """构造 content_type="mixed" 请求（自动配音出站形态：text + record）。

    - ``text``/``record_file`` 是速记件：分别展开为
      ``{"type":"text","text":...}`` 与 ``{"type":"record","file":...}`` part；
    - ``parts`` 显式给定时优先（速记件忽略）；
    - ``record_file`` 指向不存在的路径即「毒语音」形态：生产
      ``_resolve_local_file_ref`` 对不存在路径原样返回，段照上送（R6 需要）。
    """
    if parts is None:
        built: list[dict[str, Any]] = []
        if text:
            built.append({"type": "text", "text": text})
        if record_file:
            built.append({"type": "record", "file": record_file})
        parts = built
    fallback = text or ""
    content = _rendered(
        request_id,
        content_type="mixed",
        content_ref={"parts": list(parts)},
        text_fallback=fallback,
    )
    return _send_request(
        request_id, content, target_scope=target_scope, target_id=target_id,
        dedupe_key=dedupe_key,
    )


def build_chunks_request(
    request_id: str,
    chunks: list[str],
    *,
    target_scope: SessionType = SessionType.PRIVATE,
    target_id: str = "user-1",
    dedupe_key: str | None = None,
) -> SendRequest:
    """构造 content_type="chunks" 请求（part 级幂等的既有正路，仿真器自测用）。"""
    content = _rendered(
        request_id,
        content_type="chunks",
        content_ref={"chunks": list(chunks)},
        text_fallback="".join(chunks),
    )
    return _send_request(
        request_id, content, target_scope=target_scope, target_id=target_id,
        dedupe_key=dedupe_key,
    )


# ==================== 队列 / 传输 / 泵 ====================


def build_sqlite_queue(
    tmp_path: Path,
    *,
    name: str = "queue.sqlite3",
    max_attempts: int = 3,
    retry_base_seconds: int = 1,
    retry_max_seconds: int = 2,
    bot_unavailable_max_age_seconds: float | None = None,
) -> SQLiteSendRequestQueue:
    """tmp_path SQLite 队列：小退避值让显式 now 步进跨越重试窗。

    ``bot_unavailable_max_age_seconds``：bot_unavailable 挂起的绝对年龄上限
    透传（生产默认 1800s；R5 仿真传小值让「挂起到期终态」毫秒级可见）。
    """
    return SQLiteSendRequestQueue(
        tmp_path / name,
        InMemoryAuditLogger(),
        max_attempts=max_attempts,
        retry_base_seconds=retry_base_seconds,
        retry_max_seconds=retry_max_seconds,
        bot_unavailable_max_age_seconds=bot_unavailable_max_age_seconds,
    )


def make_transport(
    bot: SimulatedOneBotBot,
    *,
    timeout_seconds: float = DEFAULT_TRANSPORT_TIMEOUT_SECONDS,
) -> SendTransport:
    """真身 ``send_onebot_v11`` 包一层显式小超时的标准传输闭包。"""

    async def _send(send_request: SendRequest) -> DeliveryReceipt:
        return await send_onebot_v11(
            bot, send_request, timeout_seconds=timeout_seconds
        )

    return _send


def make_failing_transport(
    error: str = "simulated transport down",
) -> SendTransport:
    """永远抛异常的传输桩（仿真「传输层整体故障」，走 worker 兜底分类）。"""

    async def _send(send_request: SendRequest) -> DeliveryReceipt:
        raise RuntimeError(error)

    return _send


def freeze_inline_retries(
    monkeypatch: Any, delays: tuple[float, ...] = (0.0, 0.0)
) -> None:
    """清零 sender 内联退避间隔（保留尝试次数语义）。

    缺省 ``(0.0, 0.0)``＝3 次内联尝试、零 sleep——RED 用例据此可断言
    「断连形态 dispatch = 内联次数 × 队列轮数」。必须 patch **真身模块**
    ``domains.transport.sender.onebot``（``send_onebot_v11`` 定义处读的
    就是该模块全局；patch 旧路径垫片不生效）。
    """
    monkeypatch.setattr(onebot_sender, "_ONEBOT_SEND_RETRY_DELAYS", tuple(delays))


async def run_queue_rounds(
    queue: SQLiteSendRequestQueue,
    transport,
    *,
    rounds: int = 1,
    base_now: datetime | None = None,
    start_offset_seconds: float = DEFAULT_STEP_SECONDS,
    step_seconds: float = DEFAULT_STEP_SECONDS,
    **drain_kwargs: Any,
) -> list[SendQueueWorkerResult]:
    """同步泵：显式 now 逐轮驱动 ``drain_send_queue_once``，不碰墙钟。

    - 首轮 now = base_now + start_offset（须 > 60s 内联认领宽限期）；
    - 后续每轮 +step_seconds（须 > 重试退避与 90s PARTIAL 补偿退避）。
    返回逐轮 worker 结果（delivered/retryable_failed/parts_unknown 等计数）。
    """
    base = base_now or sim_utc_now()
    results: list[SendQueueWorkerResult] = []
    for round_index in range(max(1, int(rounds))):
        now = base + timedelta(
            seconds=start_offset_seconds + round_index * step_seconds
        )
        results.append(
            await drain_send_queue_once(queue, transport, now=now, **drain_kwargs)
        )
    return results


# ==================== 断言辅助 ====================


def dispatch_count(bot: SimulatedOneBotBot) -> int:
    return bot.dispatch_count


def sent_texts(bot: SimulatedOneBotBot) -> list[str]:
    return bot.sent_texts


def record_files(bot: SimulatedOneBotBot) -> list[str]:
    return bot.record_files


def issue_kind(receipt: DeliveryReceipt) -> str | None:
    """回执携带的运维问题 kind（timeout_zero_part_delivered / result_unknown /
    retcode_failure / send_exception / bot_unavailable ...）；无则 None。"""
    issue = receipt.operational_issue
    return str(issue.kind) if issue is not None else None


def read_queue_row(
    db_path: str | Path,
    request_id: str,
    *,
    columns: Sequence[str] = DEFAULT_ROW_COLUMNS,
) -> dict[str, Any]:
    """直读 SQLite send_requests 行（绕开队列实例，独立连接）。

    行不存在抛 LookupError；``next_retry_at`` 返回 ISO 字符串或 None，
    ``parts_progress`` 返回 JSON 字符串（如 ``{"0":"sent"}``）或 None。
    """
    connection = sqlite3.connect(db_path, timeout=5.0)
    connection.row_factory = sqlite3.Row
    try:
        selected = ", ".join(columns)
        row = connection.execute(
            f"SELECT {selected} FROM send_requests WHERE request_id = ?",
            (request_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise LookupError(f"queue row not found: request_id={request_id!r}")
    return {column: row[column] for column in columns}


def queue_row(
    queue: SQLiteSendRequestQueue,
    request_id: str,
    *,
    columns: Sequence[str] = DEFAULT_ROW_COLUMNS,
) -> dict[str, Any]:
    return read_queue_row(queue.db_path, request_id, columns=columns)


def part_states(queue: SQLiteSendRequestQueue, request_id: str) -> dict[int, str]:
    """part 级状态快照 {part_index: state}；无 part 行返回 {}。"""
    progress: PartProgress | None = queue.part_progress(request_id)
    if progress is None:
        return {}
    return {
        index: record.state for index, record in progress.records.items()
    }


def unknown_part_indexes(
    queue: SQLiteSendRequestQueue, request_id: str
) -> list[int]:
    progress: PartProgress | None = queue.part_progress(request_id)
    if progress is None:
        return []
    return progress.unknown_indexes()


def partial_rows(queue: SQLiteSendRequestQueue) -> list[QueuedSendRequest]:
    """PARTIAL 断点行视图（含休眠行），RED 断言「停 PARTIAL 待确认」用。"""
    return queue.list_partial_requests()
