"""终态退码撞上「已有副作用」时的 part 记账断点（SEAT-PARTIALFIX §8-A，2026-10-04）。

治的残余空白（前席 SEAT-SENDTERM §8-A 移交）：``sender/onebot.py`` 的失败出口
共四道，其中三道（``_ChunkRejectedError`` :1050、超时 :1106、异常 :1153）都
**无条件**先看 ``progress.count > 0``——只要本次尝试已产生对外副作用（有内容
送达），就按 ``result_unknown`` 终态化，把整条回执交回 worker 的原子臂记
UNKNOWN→PARTIAL，绝不整体重投。唯独第四道「返回失败 dict」臂（:1239，M10 补的
那条）在 ``count > 0`` 之后还多挂一句 ``and not _is_final_failure_retcode(retcode)``：
一旦那枚退码落在白名单里，它就从 result_unknown 臂滑进 ``retcode_failure``
FAILED_FINAL，worker 原子臂（``_deliver_atomic_mixed_parts`` :1545）据此把**每一
个 pending part 写成 failed_final**——包括那个其实已经投递成功的文件部件。已投递
的事实因此被抹成「确定没送到」，断点守卫（``queue._convert_terminal_to_partial_in``）
按 SENT 计数判 0<已送达<总数，收到的是全 failed_final ⇒ 判定 delivered==0 ⇒
守卫不介入 ⇒ 记录被擦。这是四道出口里唯一的语义分歧。

真身可达性（本文件用「合成适配器结果对象」驱动真函数证明，不碰在线 bot、不碰生产库）：
``_is_atomic_part_delivery`` 对**一切** mixed 返回 True（含带 file 部件的 mixed），
``worker._chunk_part_plan`` 注释 :802 早已把这一腿的契约写死——「file 腿的多调用
形态由 onebot 侧 progress.count 守卫自持（部分已送达 ⇒ result_unknown 终态，绝不
整体重投）」。可 ``_send_file_parts`` 恰是多调用形态：网关投递成功（progress.count
自增、真实副作用）之后，caption 文本调用若回一枚「返回失败 dict」的白名单退码，
就正好命中第四道出口。本文件钉的就是这条链。

修法（本席只动 ``sender/onebot.py`` 一处判据）：删掉第四道出口里那句
``and not _is_final_failure_retcode(retcode)``，让 ``count > 0`` 单独决定走
result_unknown——与其余三道出口一字对齐。**退码白名单成员集一个都不动**：
count==0（零副作用，含单条 mixed 原子整发的明确拒绝）仍照旧由白名单判
retcode_failure 终态/可重试；result_unknown 亦是 FAILED_FINAL（终态），终态化
不放宽、不新增重投。判死用的那枚数字退码仍写进 ``last_error_detail``（result_unknown
臂本就带 ``_onebot_failure_detail``），事后仍能从库里复核白名单。

离线运行（SQLite 走 tmp_path，无网络、无 SnowLuma、绝不碰生产库）：

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_send_partial_chunk_accounting.py -q \
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
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.domains.transport.sender import onebot as onebot_module
from plugins.bot_unified_runtime.domains.transport.sender.onebot import (
    send_onebot_v11,
)
from plugins.bot_unified_runtime.domains.transport.sender.queue import (
    SQLiteSendRequestQueue,
)
from plugins.bot_unified_runtime.domains.transport.sender.worker import (
    drain_send_queue_once,
)

# 白名单成员（_is_final_failure_retcode 判 True）——本席绝不动它，只借它触发分歧。
TERMINAL_RETCODE = 403
# 白名单外的可重试码——用来锁「非白名单的已有副作用」行为一字不变（本就在 result_unknown 臂）。
RETRYABLE_RETCODE = 500


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _request(
    request_id: str,
    *,
    content_type: str,
    content_ref: dict,
    text_fallback: str,
    parts_total: int = 2,
) -> SendRequest:
    rendered = RenderedOutput(
        request_id=request_id,
        content_type=content_type,
        content_ref=dict(content_ref),
        text_fallback=text_fallback,
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
        dedupe_key=f"dedupe-{request_id}",
        cooldown_key="bot.chat:private:user-1",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="default",
    )


def _file_plus_text_request(request_id: str) -> SendRequest:
    """带 file 部件的 mixed：触发 _send_file_parts 的多调用形态。

    parts[0]=file（网关投递）、parts[1]=text（caption 调用）。text_fallback 非空
    ⇒ caption 分支必跑（``_send_file_parts`` 以 request.content.text_fallback 为
    caption 触发门）。网关投递成功后 progress.count 已 +1（真实副作用），此时
    caption 回一枚失败 dict 即命中第四道「返回失败 dict」出口，且 count>0。
    """
    return _request(
        request_id,
        content_type="mixed",
        content_ref={
            "parts": [
                {"type": "file", "file": "https://example.test/report.pdf", "name": "report.pdf"},
                {"type": "text", "text": "正文部件"},
            ]
        },
        text_fallback="正文部件",
        parts_total=2,
    )


def _text_only_mixed_request(request_id: str) -> SendRequest:
    """纯文本 mixed：单次原子整发（无 file ⇒ 不进 _send_file_parts）。

    用来锁「零副作用 + 白名单退码」仍判 retcode_failure（本席改动不得波及这条
    既有判据）：单发失败 dict 时 progress.count 恒 0（成功才 +1），走的是
    count==0 分支，白名单照旧终态化。
    """
    return _request(
        request_id,
        content_type="mixed",
        content_ref={
            "parts": [
                {"type": "text", "text": "部件甲"},
                {"type": "text", "text": "部件乙"},
            ]
        },
        text_fallback="正文",
        parts_total=2,
    )


class _FakeFileReceipt:
    def __init__(self, provider_result: dict) -> None:
        self.provider_result = provider_result


class _FakeGateway:
    """文件网关替身：stage 直接给票、deliver 一律成功回一枚 retcode=0 的 provider_result。

    真实网关对 retcode 拒绝会抛 FileTransferError（绝不落进第四道出口），所以
    「文件其实投递成功」这一事实只能由网关侧的无异常返回来表达——本替身就扮演
    这一次成功的 upload，让 progress.count 如实 +1（真副作用）。
    """

    def __init__(self) -> None:
        self.staged = 0
        self.delivered = 0

    def stage(self, source: object, *, request_id: str = "") -> object:
        self.staged += 1
        return object()  # 占位票，替身不校验落盘

    async def deliver(
        self,
        bot: object,
        ticket: object,
        *,
        target: object,
        part_index: int,
        budget: float,
        **kwargs: object,
    ) -> _FakeFileReceipt:
        self.delivered += 1
        return _FakeFileReceipt({"status": "ok", "retcode": 0, "message_id": f"file-{part_index}"})


class _CaptionResultBot:
    """send_*_msg 一律回一枚「返回失败 dict」的假 bot（不回 raise）。

    这是本仓发送路径显式支持的两种失败形态之一（另一是 NoneBot ActionFailed
    异常）：``send_onebot_v11`` 的第四道出口（:1239 ``if not _onebot_result_is_success(result)``）
    就是为回 dict 的适配器而存在——前席 test_send_failure_reason_ledger 里
    RejectingOneBot 亦用回 dict 形态端到端驱动 mixed。文件部件走网关、不经本 bot，
    所以本 bot 被调用的次数即 caption 调用次数。
    """

    def __init__(self, retcode: int) -> None:
        self.retcode = retcode
        self.send_calls = 0

    async def send_private_msg(self, *, user_id: object, message: list[dict]) -> dict:
        self.send_calls += 1
        return {"status": "failed", "retcode": self.retcode, "wording": "no sink C:\\Users\\x"}

    async def send_group_msg(self, *, group_id: object, message: list[dict]) -> dict:
        self.send_calls += 1
        return {"status": "failed", "retcode": self.retcode, "wording": "no sink"}


@pytest.fixture()
def fake_gateway(monkeypatch: pytest.MonkeyPatch) -> _FakeGateway:
    gateway = _FakeGateway()
    monkeypatch.setattr(onebot_module, "get_default_file_gateway", lambda: gateway)
    return gateway


def _transport(bot: _CaptionResultBot):
    async def _send(send_request: SendRequest):
        return await send_onebot_v11(bot, send_request, timeout_seconds=0.5)

    return _send


def _build_queue(tmp_path: Path, name: str) -> SQLiteSendRequestQueue:
    return SQLiteSendRequestQueue(
        tmp_path / name,
        InMemoryAuditLogger(),
        retry_base_seconds=1,
        retry_max_seconds=2,
    )


def _part_rows(tmp_path: Path, name: str, request_id: str) -> list[sqlite3.Row]:
    with sqlite3.connect(tmp_path / name) as connection:
        connection.row_factory = sqlite3.Row
        return list(
            connection.execute(
                "SELECT part_index, state, attempts, last_error_kind, last_error_detail"
                " FROM send_request_parts WHERE request_id = ? ORDER BY part_index",
                (request_id,),
            ).fetchall()
        )


def _request_row(tmp_path: Path, name: str, dedupe_key: str) -> sqlite3.Row:
    with sqlite3.connect(tmp_path / name) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            "SELECT state, last_public_message FROM send_requests WHERE dedupe_key = ?",
            (dedupe_key,),
        ).fetchone()


# ==================== 一、onebot 出口层：已有副作用 + 白名单退码 ⇒ result_unknown ====================


def test_terminal_retcode_after_side_effect_is_result_unknown(fake_gateway) -> None:
    """残余空洞正解：文件已投（count>0）+ caption 白名单退码 ⇒ result_unknown，不是 retcode_failure。

    改前＝第四道出口的 ``and not _is_final_failure_retcode(retcode)`` 让白名单码绕过
    副作用守卫，回执判成 retcode_failure；改后＝与其余三道出口一致，凡有副作用即
    result_unknown（worker 原子臂据此记 UNKNOWN→PARTIAL，已投文件不被抹成 failed_final）。
    """
    req = _file_plus_text_request("req-term-partial")
    bot = _CaptionResultBot(TERMINAL_RETCODE)
    receipt = asyncio.run(send_onebot_v11(bot, req, timeout_seconds=0.5))

    # 网关投递确实发生了一次（真实副作用），caption 也真调了一次。
    assert fake_gateway.delivered == 1
    assert bot.send_calls == 1

    # 终态轴不动：result_unknown 仍是 FAILED_FINAL（绝不因本改变成可重试→无限重投）。
    assert receipt.state is ReceiptState.FAILED_FINAL
    issue = receipt.operational_issue
    assert issue is not None
    # 判据轴：有副作用的白名单退码必须被记为 result_unknown（改前此处是 retcode_failure）。
    assert issue.kind == "result_unknown"
    assert issue.retryable is False
    # 判死依据留痕：那枚白名单数字仍进 safe_summary（result_unknown 臂本就带 _onebot_failure_detail）。
    assert str(TERMINAL_RETCODE) in issue.safe_summary
    # 裁决锁：适配器 wording 原文（含盘符形态）绝不进回执。
    assert "no sink" not in issue.safe_summary
    assert "Users" not in issue.safe_summary


def test_retryable_retcode_after_side_effect_unchanged(fake_gateway) -> None:
    """非白名单退码 + 已有副作用：改前改后都是 result_unknown（本席不动这条，锁它一字未变）。"""
    req = _file_plus_text_request("req-retry-partial")
    bot = _CaptionResultBot(RETRYABLE_RETCODE)
    receipt = asyncio.run(send_onebot_v11(bot, req, timeout_seconds=0.5))

    assert fake_gateway.delivered == 1
    assert receipt.state is ReceiptState.FAILED_FINAL
    issue = receipt.operational_issue
    assert issue is not None and issue.kind == "result_unknown"
    assert str(RETRYABLE_RETCODE) in issue.safe_summary


def test_zero_side_effect_terminal_retcode_stays_retcode_failure() -> None:
    """零副作用（单条原子整发失败 dict、count 恒 0）+ 白名单 ⇒ 仍 retcode_failure FAILED_FINAL。

    本席的改动只在 count>0 那一句；count==0 分支必须一字未动，否则就是拿「顺手」
    把明确拒绝（重发必同败）也降级成 result_unknown，正踩前席反复钉的「白名单不许放宽」。
    无需网关（纯文本 mixed 走单发 else 分支）。
    """
    req = _text_only_mixed_request("req-zero-effect")
    bot = _CaptionResultBot(TERMINAL_RETCODE)
    receipt = asyncio.run(send_onebot_v11(bot, req, timeout_seconds=0.5))

    assert receipt.state is ReceiptState.FAILED_FINAL
    issue = receipt.operational_issue
    assert issue is not None and issue.kind == "retcode_failure"
    assert issue.retryable is False
    assert str(TERMINAL_RETCODE) in issue.safe_summary


# ==================== 二、端到端记账锁：已投文件不被擦成 failed_final ====================


@pytest.mark.asyncio
async def test_partial_delivery_ledger_is_not_erased_to_failed_final(tmp_path, fake_gateway) -> None:
    """worker 原子臂据 result_unknown 把两段记 UNKNOWN、行置 PARTIAL，而非全写 failed_final。

    这是本席真正要钉的账：残余空洞的真害处＝已投递的文件部件被抹成「确定没送到」，
    断点守卫按 SENT 计数判 0<已送达<总数，收到全 failed_final ⇒ delivered==0 ⇒ 守卫
    不介入 ⇒ 记录被擦。改前（retcode_failure）＝part 全 failed_final、行 failed_final；
    改后（result_unknown）＝part 全 unknown、行 partial（可续，UNKNOWN 永不盲重发）。
    """
    name = "partial_ledger.sqlite3"
    queue = _build_queue(tmp_path, name)
    base = _utc_now()
    req = _file_plus_text_request("req-partial-e2e")
    queue.submit(req, now=base)
    bot = _CaptionResultBot(TERMINAL_RETCODE)

    # now +120s 越过内联宽限期，交 worker 认领（同前席 test_send_failure_reason_ledger 先例）。
    await drain_send_queue_once(queue, _transport(bot), now=base + timedelta(seconds=120))

    rows = _part_rows(tmp_path, name, "req-partial-e2e")
    assert [r["part_index"] for r in rows] == [0, 1]
    # 已投递的文件部件（index 0）绝不被擦成 failed_final；连同 caption 一起记 UNKNOWN。
    assert all(r["state"] == "unknown" for r in rows), [
        (r["part_index"], r["state"]) for r in rows
    ]
    # 判死数字仍随 detail 入明细账（result_unknown 臂带 _onebot_failure_detail）。
    assert all(str(TERMINAL_RETCODE) in str(r["last_error_detail"]) for r in rows)
    # 请求行收在可续断点 PARTIAL（不是被剪枝的 failed_final）——记录在场、事后能查送达了几段。
    assert str(_request_row(tmp_path, name, req.dedupe_key)["state"]) == "partial"


@pytest.mark.asyncio
async def test_partial_delivery_never_blindly_resent_across_passes(tmp_path, fake_gateway) -> None:
    """PARTIAL 续扫第二趟：UNKNOWN 段不在 PENDING 集内 ⇒ 绝不再调 send_*_msg（不双发已投内容）。

    残余空洞若放行重投，风险是「重发把已投递的文件再送一遍」。这里第二趟把 now 推过
    90s 断点回退，观察 worker 认领后是否再触发 caption 调用：改后 result_unknown 记
    UNKNOWN→PARTIAL，pending 为空 ⇒ 整发被跳过，bot.send_calls 不增。
    """
    name = "partial_noresend.sqlite3"
    queue = _build_queue(tmp_path, name)
    base = _utc_now()
    req = _file_plus_text_request("req-partial-noresend")
    queue.submit(req, now=base)
    bot = _CaptionResultBot(TERMINAL_RETCODE)

    await drain_send_queue_once(queue, _transport(bot), now=base + timedelta(seconds=120))
    first_pass_send_calls = bot.send_calls
    first_pass_gateway_deliveries = fake_gateway.delivered
    assert first_pass_send_calls == 1  # 首趟只发了 caption 一次（文件走网关）

    # 第二趟：推过 _PARTIAL_RESUME_BACKOFF_SECONDS（90s），PARTIAL 行到期可再认领。
    await drain_send_queue_once(queue, _transport(bot), now=base + timedelta(seconds=260))

    # 已投内容绝不重发：send_*_msg 与网关投递都不再增加（UNKNOWN 段永不盲发）。
    assert bot.send_calls == first_pass_send_calls, bot.send_calls
    assert fake_gateway.delivered == first_pass_gateway_deliveries

    rows = _part_rows(tmp_path, name, "req-partial-noresend")
    assert all(r["state"] == "unknown" for r in rows), [
        (r["part_index"], r["state"]) for r in rows
    ]


# ==================== 三、白名单成员集一字不动（防本席顺手放宽）====================


def test_terminal_whitelist_membership_unchanged() -> None:
    """本席绝不改判退码白名单成员集：摘除任一枚都须带真机退码分布证据另案施工。"""
    from plugins.bot_unified_runtime.domains.transport.sender.onebot import (
        _is_final_failure_retcode,
    )

    for member in (403, 404, 100, 1003, 1200, 1201, 1400, 1401, 1403, 1404):
        assert _is_final_failure_retcode(member) is True, member
    for outsider in (500, 429, None):
        assert _is_final_failure_retcode(outsider) is False, outsider
