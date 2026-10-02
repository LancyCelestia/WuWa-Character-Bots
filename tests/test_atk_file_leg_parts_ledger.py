"""台账 #73「file 腿 parts 账断点」回归锁（S15 补丁 · ATK-P12 席，2026-10-03）。

缺陷本体（判据源＝``docs/HANDBOOK.md`` §73 / AGENTS 台账 #73）：
``worker._chunk_part_plan`` 的 mixed 分支原带第三条件「不含 file 部件」，见到
``type=="file"`` 段就整条 ``return None`` ⇒ mixed+file 请求**退出 part 系统**：
``queue`` 的 ``INSERT INTO send_request_parts`` 根本不执行，``send_requests.parts_total``
恒 NULL。后果＝UNKNOWN 确认协议、PARTIAL 断点续发、90s 补偿三腿对带附件的请求
天生无牙——超时/断连按「count==0 ⇒ 零副作用 ⇒ 可整发重投」恒真式盲重投
（M-63「9 发零账」的同一族根因，只是发生在 file 腿）。

修法＝删掉那第三条件：含 file 段同样进段级记账。投递形态不变——
``_is_atomic_part_delivery`` 对 mixed 恒真，file 腿仍是**一次** transport 调用；
file 腿内部的多调用形态（上传→文案→其余媒体）由 onebot 侧 ``progress.count``
守卫自持（任一段有副作用 ⇒ 终态 result_unknown ⇒ 绝不整体重投）。记账侧因此
与语音混排同构：part 行的 SENT/UNKNOWN 与整条回执同进退。

三枚锁各钉断点的一个面（摘掉补丁即红，接上补丁全绿）：

① ``test_mixed_file_leg_writes_parts_ledger``——正向账本：带 file 段的 mixed
   请求照写 ``send_request_parts``，``parts_total`` == 段数且非 NULL。
   旧形态：无 part 行、``parts_total`` 为 ``None`` ⇒ 本例红。
② ``test_chunk_part_plan_keeps_file_leg_but_keeps_scope_gate``——判定门本体：
   mixed+file 计划非 ``None``、键位与原始 parts 下标逐位对齐（与
   ``onebot._mixed_part_indexes`` 同源，含被构段跳过的非 dict 项）；同时负样本
   （非私聊/群聊 scope、空 parts）仍返回 ``None``——防"修一处塌一片"的过宽回归。
③ ``test_mixed_file_leg_result_unknown_stops_partial``——事故面：结果未知形态
   part 记 UNKNOWN、行停 PARTIAL，续轮**零再投**（出网次数恒为 1）。旧形态无账
   ⇒ 每轮整发重投 ⇒ 同一请求二次出网（重复投递）。这条才是「三腿有牙」的实证；
   续轮行态按 Q-G7 INV-A 现行契约（``test_queue_dormant_partial_final``）落
   ``failed_final``——终态化只收口、绝不重投，见该例 docstring。

离线运行（零网络、零墙钟、真身 SQLite 落 tmp_path；文件段只造路径字符串，
不经 FileTransferGateway——传输侧用计数假件）：

    PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8 python -m pytest \\
      tests/test_atk_file_leg_parts_ledger.py -q -p no:cacheprovider \\
      --basetemp=<仓库外目录>
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from helpers.voice_queue_sim import (
    PART_STATE_SENT,
    PART_STATE_UNKNOWN,
    PARTIAL_ROW_STATE,
    build_mixed_request,
    build_sqlite_queue,
    part_states,
    queue_row,
    unknown_part_indexes,
)

from plugins.bot_unified_runtime.contracts import (
    DeliveryReceipt,
    OperationalIssue,
    ReceiptState,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.domains.transport.sender.worker import (
    _chunk_part_plan,
    drain_send_queue_once,
)

_BASE = datetime(2026, 10, 3, 0, 0, 0, tzinfo=timezone.utc)

#: 带 file 段的混排（附件 + 文案 + 图片）——断点事故的真实出站形态。
_FILE_PARTS: list[dict[str, object]] = [
    {"type": "text", "text": "报告已生成，见附件。"},
    {"type": "file", "file": "C:/nowhere/report.pdf", "name": "report.pdf"},
    {"type": "image", "file": "C:/nowhere/plot.png"},
]


class _CountingTransport:
    """按 verdict 逐调用回执的假 transport；记下每次调用（=真实出网次数）。

    ``verdict="sent"``  ⇒ 整条 SENT（file 腿原子整发的成功形态）。
    ``verdict="unknown"`` ⇒ FAILED_RETRYABLE + 结果未知类 kind（超时/断连/传输
    异常同档；``retry_safety`` 留空 ⇒ 不认领 connect_phase 的免记账特例）。
    """

    def __init__(self, *, verdict: str) -> None:
        self.verdict = verdict
        self.calls: list[str] = []

    async def __call__(self, send_request: SendRequest) -> DeliveryReceipt:
        self.calls.append(send_request.request_id)
        if self.verdict == "sent":
            return DeliveryReceipt(
                request_id=send_request.request_id,
                state=ReceiptState.SENT,
                transport="onebot-v11-sim",
                provider_message_id=f"mid-{len(self.calls)}",
                public_message="sent",
            )
        return DeliveryReceipt(
            request_id=send_request.request_id,
            state=ReceiptState.FAILED_RETRYABLE,
            transport="onebot-v11-sim",
            public_message="",
            operational_issue=OperationalIssue(
                stage="onebot_v11",
                kind="send_exception",
                retryable=True,
                safe_summary="send_exception（仿真：回执缺失，是否送达未知）",
            ),
        )

    @property
    def dispatch_count(self) -> int:
        return len(self.calls)


# ==================== ① 正向账本 ====================


@pytest.mark.asyncio
async def test_mixed_file_leg_writes_parts_ledger(tmp_path) -> None:
    """①带 file 段的 mixed 请求必须写 ``send_request_parts``（parts_total 非 NULL）。

    这是台账 #73 记的那处断点的正面判据：旧形态 mixed+file 整条退出 part 系统
    ⇒ 零 part 行、``parts_total`` 恒 NULL ⇒ UNKNOWN/PARTIAL/90s 三腿无牙。
    """
    queue = build_sqlite_queue(tmp_path)
    request = build_mixed_request("file-leg-sent", parts=_FILE_PARTS)
    queue.submit(request, now=_BASE)
    transport = _CountingTransport(verdict="sent")

    result = await drain_send_queue_once(queue, transport, now=_BASE + timedelta(seconds=120))

    row = queue_row(queue, "file-leg-sent")
    assert row["parts_total"] == len(_FILE_PARTS)  # 旧形态 None ⇒ 本行即断点
    assert row["parts_total"] is not None
    assert row["state"] == ReceiptState.SENT.value
    assert row["parts_delivered"] == len(_FILE_PARTS)
    assert part_states(queue, "file-leg-sent") == {
        index: PART_STATE_SENT for index in range(len(_FILE_PARTS))
    }
    # 记账不改投递形态：mixed 仍是「一次原子整发」，绝不因段级键拆成 3 次调用。
    assert transport.dispatch_count == 1
    assert result.delivered == 1


# ==================== ② 判定门本体（含负样本）====================


def test_chunk_part_plan_keeps_file_leg_but_keeps_scope_gate() -> None:
    """②计划门：含 file 段照样出计划；键位与原始 parts 下标逐位对齐。

    同时钉死两个**不许被顺手放宽**的负样本（scope 门、空 parts 门）——本波只
    摘第三条件，另两条件与 chunks 分支同语义。
    """
    plan = _chunk_part_plan(build_mixed_request("file-leg-plan", parts=_FILE_PARTS))
    assert plan is not None
    assert len(plan) == len(_FILE_PARTS)
    # 键位对齐面：每段的身份串就是它自己的 canonical JSON（下标不偏移），与
    # onebot._mixed_part_indexes 的 0..len-1 回报索引同构。file 段绝不能被跳过
    # 或折叠——折叠一次就与回报索引错位，断点续发会拿别人的账当自己的。
    assert plan[1] == json.dumps(_FILE_PARTS[1], ensure_ascii=False, sort_keys=True)
    assert plan[0] == json.dumps(_FILE_PARTS[0], ensure_ascii=False, sort_keys=True)

    # 非 dict 项也要占位（否则键位与回报索引错位 → 断点续发拿别人的账）。
    with_hole = _chunk_part_plan(
        build_mixed_request("file-leg-hole", parts=[{"type": "file", "file": "a.bin"}, "裸串"])
    )
    assert with_hole is not None and len(with_hole) == 2

    # 负样本 1：非私聊/群聊 scope（与 chunks 既有 scope 门对齐）→ 不计划。
    assert (
        _chunk_part_plan(
            build_mixed_request(
                "file-leg-channel", parts=_FILE_PARTS, target_scope=SessionType.CHANNEL
            )
        )
        is None
    )
    # 负样本 2：空 parts / 非列表 parts → 不计划。
    assert _chunk_part_plan(build_mixed_request("file-leg-empty", parts=[])) is None


# ==================== ③ 事故面：三腿有牙 ====================


@pytest.mark.asyncio
async def test_mixed_file_leg_result_unknown_stops_partial(tmp_path) -> None:
    """③结果未知形态：第 1 轮 part 记 UNKNOWN + 行停 PARTIAL，续轮**零再投**。

    这条才是 file 腿「UNKNOWN 确认 / PARTIAL 断点 / 90s 补偿」三腿有牙的实证：
    旧形态无 part 账 ⇒ ``_deliver_parts_if_available`` 直接降级整发路径 ⇒ 请求级
    ``mark_retryable_failure`` 烧退避 ⇒ 第 2 轮整发重投（可能已送达的附件再发
    一遍，dispatch_count 变 2）。生产 ``unknown_part_confirmer=None``
    （``bot_outbound_verify_enabled`` 缺省 False）⇒ 确认不了的 UNKNOWN 保持原状，
    绝不盲发。

    第 2 轮行态钉 ``failed_final`` 而非 ``partial``＝Q-G7 INV-A 的现行契约
    （``tests/test_queue_dormant_partial_final.py`` 头部三条不变量）：零进展且
    无可推进 PENDING part 的休眠轮**必须**终态化（否则永久 parked、永不剪零告警），
    终态化只收口不重投——所以「dispatch 仍为 1」与「行落 failed_final」是同一枚
    硬币的两面，缺一即双发或永久停放。
    ⚠ 同族既有两例 ``test_h_voice_delivery.py::test_r1_*`` / ``::test_r2_*`` 仍断言
    第 2 轮为 ``partial``（旧休眠契约）⇒ 这两枚在 HEAD 上本就红，与本单元无关，
    由 Q-G7 那条线收口，本席不动它们。
    """
    queue = build_sqlite_queue(tmp_path)
    request = build_mixed_request("file-leg-unknown", parts=_FILE_PARTS)
    queue.submit(request, now=_BASE)
    transport = _CountingTransport(verdict="unknown")

    await drain_send_queue_once(queue, transport, now=_BASE + timedelta(seconds=120))

    row1 = queue_row(queue, "file-leg-unknown")
    assert row1["parts_total"] == len(_FILE_PARTS)  # 旧形态 None ⇒ 断点正面判据
    assert row1["state"] == PARTIAL_ROW_STATE  # 有进展轮：停可续发断点
    assert set(part_states(queue, "file-leg-unknown").values()) == {PART_STATE_UNKNOWN}
    assert unknown_part_indexes(queue, "file-leg-unknown") == list(range(len(_FILE_PARTS)))

    # 续轮（步进 120s > 90s PARTIAL 补偿退避）：账已存在 ⇒ 认领后确认不了 UNKNOWN
    # 就绝不重投——出网次数仍为 1（旧形态此轮整发重投 = 第 2 次出网）。
    await drain_send_queue_once(queue, transport, now=_BASE + timedelta(seconds=240))

    row2 = queue_row(queue, "file-leg-unknown")
    assert row2["state"] == ReceiptState.FAILED_FINAL.value  # Q-G7 INV-A（见 docstring）
    assert set(part_states(queue, "file-leg-unknown").values()) == {PART_STATE_UNKNOWN}
    assert transport.dispatch_count == 1

