"""Q-G7 休眠 PARTIAL 永久停摆——三条不变量回归（S-FIX-QPARK，2026-09-27）。

对应审计 `.superpowers/sdd/2026-09-27-fullload/logs/SEAT-ATK-QUEUE.md` §一 Q-G7
与 §二-P2 名册：`unknown_part_confirmer` 生产为 None（`bot_outbound_verify_enabled`
缺省 False），零进展轮把行置成 `state='partial' AND next_retry_at IS NULL` 的
**永久休眠**——`_prune` 只剪终态，于是未送达消息永久 parked、永不重试、永不被剪、
零告警（生产实锤 10 行，其中 5 枚是 `admin_alert_card` 告警卡自身）。

本件钉死三条不变量（修法与补丁全文见
`.superpowers/sdd/2026-09-27-fullload/logs/SEAT-FIX-QPARK.md` §待主代理落盘）：

- INV-A 休眠必须收敛，不得产生永久 parked：
  `mark_partial(resumable=False)` 在「无可推进 PENDING part」时必须直接终态化
  FAILED_FINAL（可被 `_prune` 剪），在「仍有可推进 PENDING part」时必须给出
  补偿扫描退避（绝不允许 NULL next_retry_at 的死档）。
- INV-B 告警行自豁免：`admin_alert_card:*` / `bot.alert:*` /
  capability ∈ {bot.alert, bot.error_report} / audit_tags 含 admin_alert 的行
  绝不进永久休眠，且终结时的 operational issue 必须照旧进告警链。
- INV-C 可观测：worker 每 pass 统计休眠 PARTIAL 数（`dormant_partial_count`）
  并经 operational 告警口点名（含行身份，300s 抑制）；历史遗留休眠行由
  `_prune` 顶部按 TTL 扫成终态（宁漏不双发：只终态化，绝不重投）。

**今天（HEAD 未含修复）的预期状态**——逐条注明：
- INV-A 除作用域护栏外 RED：HEAD 上 `mark_partial(resumable=False)` 无条件写
  next_retry_at=NULL 永久休眠（queue.py:1409-1431，HEAD 9358ef1），没有终态口。
- INV-B 全部 RED：HEAD 无 `_is_alert_send_request` 判定、无豁免、无清扫。
- INV-C 全部 RED：HEAD 无 `_DORMANT_PARTIAL_SWEEP_SECONDS`、无
  `list_dormant_partials`、结果模型无 `dormant_partial_count`。
- 例外（HEAD 即绿、修复后必须保持绿）：
  `test_resumable_progress_made_partial_keeps_resume_backoff`、
  `test_dormant_never_blind_resends_unknown_parts`——前者是作用域护栏（终态口
  只吃休眠轮，不得杀正常断点续发），后者是「宁漏不双发」安全底座。

等 QKEY 共键收口批与本席补丁由主代理合入 queue.py/worker.py 后全部转绿。
既有件 `tests/test_part_idempotent_resume.py::
test_unknown_without_confirmer_never_blind_resent` 钉的是**旧休眠契约**，
合入补丁时必须按 SEAT-FIX-QPARK §四 的改写稿同步更新，否则全量门会红。

运行：
    BOT_AUTOSYNC=0 PYTHONDONTWRITEBYTECODE=1 ../ChatBot_Runtime/venv/Scripts/python.exe \
        -m pytest tests/test_queue_dormant_partial_final.py -p no:cacheprovider \
        --basetemp=<仓库外私有目录> -q
"""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import sys
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
    PARTIAL_ROW_STATE,
    SQLiteSendRequestQueue,
)
from plugins.bot_unified_runtime.domains.transport.sender.worker import (
    drain_send_queue_once,
)

CHUNKS = ["分片一", "分片二", "分片三"]

queue_module = sys.modules[SQLiteSendRequestQueue.__module__]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _chunk_request(
    request_id: str,
    chunks: list[str],
    *,
    capability_id: str = "bot.chat",
    dedupe_prefix: str = "dedupe",
    audit_tags: list[str] | None = None,
) -> SendRequest:
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
        capability_id=capability_id,
        content=rendered,
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=len(chunks),
        dedupe_key=f"{dedupe_prefix}-{request_id}",
        cooldown_key=f"{capability_id}:private:user-1",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="default",
        audit_tags=list(audit_tags or []),
    )


def _alert_card_request(request_id: str, chunks: list[str]) -> SendRequest:
    """生产告警卡形态（alerts.build_admin_alert_card_send_request 同键形）。"""
    return _chunk_request(
        request_id,
        chunks,
        capability_id="bot.error_report",
        dedupe_prefix=f"admin_alert_card:telegram:test-bot:t1:{request_id}",
        audit_tags=["admin_alert", "origin:admin_alert", "admin_alert_card"],
    )


def _build_queue(
    tmp_path: Path, name: str = "queue.sqlite3", **overrides: object
) -> SQLiteSendRequestQueue:
    return SQLiteSendRequestQueue(
        tmp_path / name,
        InMemoryAuditLogger(),
        retry_base_seconds=1,
        retry_max_seconds=2,
        **overrides,  # type: ignore[arg-type]
    )


def _digests(chunks: list[str]) -> list[str]:
    return [hashlib.sha256(chunk.encode("utf-8")).hexdigest()[:16] for chunk in chunks]


def _seed_partial(
    queue: SQLiteSendRequestQueue,
    request: SendRequest,
    *,
    base: datetime,
    sent_indexes: list[int],
    unknown_indexes: list[int],
) -> None:
    """经与 worker 同一批存储 API 播种 part 现场（请求行保持 QUEUED）。"""
    request_id = request.request_id
    queue.submit(request, now=base)
    # 兼容 QKEY 在飞演化的 part 账本身份参数（HEAD 无该 kwarg 时回退旧调用形）。
    try:
        queue.ensure_parts_planned(
            request_id, _digests(CHUNKS), now=base, dedupe_key=request.dedupe_key
        )
    except TypeError:
        queue.ensure_parts_planned(request_id, _digests(CHUNKS), now=base)
    for index in sent_indexes:
        assert queue.mark_part_sent(request_id, index, now=base)
    for index in unknown_indexes:
        assert queue.mark_part_unknown(request_id, index, now=base)


def _row_state_row(
    tmp_path: Path, name: str, request_id: str
) -> sqlite3.Row | None:
    with sqlite3.connect(tmp_path / name) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            "SELECT state, next_retry_at, updated_at FROM send_requests "
            "WHERE request_id = ?",
            (request_id,),
        ).fetchone()


def _force_dormant_shape(
    tmp_path: Path, name: str, request_id: str, *, updated_age_seconds: float
) -> None:
    """直写 SQL 复刻生产遗留形态：state=partial + next_retry_at=NULL。

    修复落地后正常路径不再产生休眠行，该形态只剩「修复上线前的存量」——
    INV-C 的 TTL 清扫腿就是为它准备的，所以这里只能直写模拟。
    """
    stale = (_utc_now() - timedelta(seconds=updated_age_seconds)).isoformat()
    with sqlite3.connect(tmp_path / name) as connection:
        connection.execute(
            "UPDATE send_requests SET state = ?, next_retry_at = NULL, updated_at = ? "
            "WHERE request_id = ?",
            (PARTIAL_ROW_STATE, stale, request_id),
        )
        connection.commit()


class _NullTransport:
    """什么都不发；一旦被调用即记录（用于证明零重发）。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def __call__(self, send_request: SendRequest):
        self.calls.append(send_request.request_id)
        raise AssertionError("休眠收敛路径绝不允许再触发任何投递")


def _drain(queue, transport, **kwargs):
    """同步壳：drain_send_queue_once 是协程，测试里用 asyncio.run 等同一轮。"""
    return asyncio.run(drain_send_queue_once(queue, transport, **kwargs))


# ==================== INV-A：休眠必须收敛，不得产生永久 parked ====================


def test_zero_delivered_dormancy_becomes_failed_final_and_prunable(
    tmp_path: Path,
) -> None:
    """零送达 + 无可推进 PENDING：休眠请求必须终态化为 FAILED_FINAL（可剪）。

    预期：HEAD RED（行停在 state=partial、next_retry_at=NULL，永不被剪）；
    queue.py 终态口合入后转绿。
    """
    queue = _build_queue(tmp_path)
    base = _utc_now()
    request = _chunk_request("req-dormant-zero", CHUNKS)
    _seed_partial(queue, request, base=base, sent_indexes=[], unknown_indexes=[0, 1, 2])

    receipt = queue.mark_partial("req-dormant-zero", resumable=False, now=base)
    assert receipt.state is ReceiptState.FAILED_FINAL  # 对外投影新旧一致

    row = _row_state_row(tmp_path, "queue.sqlite3", "req-dormant-zero")
    assert row is not None
    assert row["state"] == ReceiptState.FAILED_FINAL.value, (
        "休眠 PARTIAL 必须有终态出口：零送达+无可推进 PENDING 时必须写 "
        "FAILED_FINAL（当前停在 partial = Q-G7 永久 parked）"
    )
    # 终态化绝不等于重投：行不得再被补偿扫描认领。
    assert queue.claim_due(now=base + timedelta(seconds=100000)) == []
    # 终态行可剪：max_items=1 的实例再入列一行，挤占即剪掉旧终态行。
    queue2 = _build_queue(tmp_path, "queue.sqlite3", max_items=1)
    queue2.submit(
        _chunk_request("req-t1-filler", ["填充"]), now=base + timedelta(seconds=30)
    )
    assert _row_state_row(tmp_path, "queue.sqlite3", "req-dormant-zero") is None, (
        "收敛后的行必须可被 _prune 剪掉（FAILED_FINAL 属终态）；"
        "剪不动＝仍在永久堆积"
    )


def test_partial_delivered_dormancy_terminates_without_resend(tmp_path: Path) -> None:
    """有已送达 part（delivered>0）+ 只剩 UNKNOWN：休眠轮终态化，绝不盲重发。

    诚实回执方案：请求行写 FAILED_FINAL，part 明细账（send_request_parts）
    保留原态供事后取证；worker 侧回执本来就是 FAILED_FINAL（mark_partial
    对外投影从未变过），因此收敛只改变「行是否永久 parked」，不动对外契约。

    预期：HEAD RED（行停在 partial）；转绿条件同前一用例。投递零调用由
    _NullTransport 现场自证。
    """
    queue = _build_queue(tmp_path, "mixdorm.sqlite3")
    base = _utc_now()
    request = _chunk_request("req-mixed-dormant", CHUNKS)
    _seed_partial(queue, request, base=base, sent_indexes=[0], unknown_indexes=[1, 2])
    queue.mark_partial("req-mixed-dormant", resumable=False, now=base)

    row = _row_state_row(tmp_path, "mixdorm.sqlite3", "req-mixed-dormant")
    assert row is not None
    assert row["state"] == ReceiptState.FAILED_FINAL.value

    # 终态后走整轮 drain：既不认领、也不得有任何投递。
    transport = _NullTransport()
    result = _drain(queue, transport, now=base + timedelta(seconds=600))
    assert result.checked == 0
    assert transport.calls == []
    # part 明细账不销毁（取证面）：仍可查得 1 送达 / 2 未知。
    progress = queue.part_progress("req-mixed-dormant")
    assert progress is not None
    assert progress.delivered == 1
    assert progress.unknown_indexes() == [1, 2]


def test_resumable_progress_made_partial_keeps_resume_backoff(tmp_path: Path) -> None:
    """resumable=True 的常规断点行为零改动：仍带补偿退避、仍可被认领。

    本用例在 HEAD 即 GREEN——修复的作用域护栏：终态口只吃「休眠轮」，
    不得把正常断点续发也杀了。
    """
    queue = _build_queue(tmp_path, "keepresum.sqlite3")
    base = _utc_now()
    request = _chunk_request("req-keep-resumable", CHUNKS)
    _seed_partial(queue, request, base=base, sent_indexes=[0], unknown_indexes=[])
    assert queue.mark_part_sent("req-keep-resumable", 1, now=base)
    receipt = queue.mark_partial("req-keep-resumable", resumable=True, now=base)
    assert receipt.next_retry_at is not None
    claimed = queue.claim_due(now=base + timedelta(seconds=600))
    assert [entry.send_request.request_id for entry in claimed] == [
        "req-keep-resumable"
    ]


def test_pending_parts_with_attempts_never_silently_parked(tmp_path: Path) -> None:
    """仍有可推进 PENDING part 时收到休眠请求：必须给退避，不得写 NULL 死档。

    预期：HEAD RED（无条件休眠）；修复后转绿（防御分支：resumable=False 但
    还有可推进 part ⇒ 视同可续发，落 90s 退避）。worker 现役路径造不出此形
    态（可推进必致 progress_made），该分支只防未来新调用点再造死档。
    """
    queue = _build_queue(tmp_path, "pendingpark.sqlite3")
    base = _utc_now()
    request = _chunk_request("req-pending-park", CHUNKS)
    # part0 UNKNOWN，part1/part2 保持 PENDING 且 attempts=0（可推进）。
    _seed_partial(queue, request, base=base, sent_indexes=[], unknown_indexes=[0])
    queue.mark_partial("req-pending-park", resumable=False, now=base)

    row = _row_state_row(tmp_path, "pendingpark.sqlite3", "req-pending-park")
    assert row is not None
    assert not (
        row["state"] == PARTIAL_ROW_STATE and row["next_retry_at"] is None
    ), (
        "还有可推进 PENDING part 的行绝不允许落成 NULL 休眠死档："
        "要么带补偿退避，要么已终态化（Q-G7 不变量）"
    )


# ==================== INV-B：告警行不得进永久休眠（告警链不自吞） ====================


def test_alert_row_identity_predicate_covers_production_shapes() -> None:
    """行身份判定：生产名册三形（admin_alert_card / bot.alert / 标记 tag）全认。

    预期：HEAD RED（`_is_alert_send_request` 不存在）；queue.py 补丁合入后
    转绿。名册依据＝SEAT-ATK-QUEUE §二-P2（10 枚 parked 里 5 枚
    admin_alert_card:*、3 枚 bot.alert:*）。
    """
    predicate = getattr(queue_module, "_is_alert_send_request", None)
    assert predicate is not None, (
        "queue._is_alert_send_request 缺席：告警行身份判定尚未落地（等合入）"
    )
    # 认得：键形前缀 / capability 登记 / audit_tag 三种独立来源。
    assert predicate(_alert_card_request("req-card", CHUNKS)) is True
    assert predicate(_chunk_request("req-a", CHUNKS, capability_id="bot.alert")) is True
    assert (
        predicate(_chunk_request("req-t", CHUNKS, audit_tags=["admin_alert"])) is True
    )
    assert (
        predicate(
            _chunk_request("req-k", CHUNKS, dedupe_prefix="bot.alert:private:3865067623")
        )
        is True
    )
    # 不误认：普通聊天行、以及仅名字里含 alert 字样的能力。
    assert predicate(_chunk_request("req-normal", CHUNKS)) is False
    assert (
        predicate(
            _chunk_request("req-x", CHUNKS, capability_id="bot.calendar_alert")
        )
        is False
    )


def test_alert_card_dormancy_terminates_prunable_and_keeps_issue(tmp_path: Path) -> None:
    """告警卡行零送达 ⇒ 休眠轮即终态；行可剪（告警失踪变告警可见）。

    预期：HEAD RED（停在 partial，告警卡自身永久失踪——生产 5 枚在案）；
    queue.py 补丁合入后转绿。issue 面：mark_partial 的终结回执带
    FAILED_FINAL 投影 + 原 issue（worker 收敛段本就投给告警链，这里钉
    「终结不回静默」）。
    """
    queue = _build_queue(tmp_path, "alertdorm.sqlite3")
    base = _utc_now()
    request = _alert_card_request("req-alert-dorm", CHUNKS)
    _seed_partial(queue, request, base=base, sent_indexes=[], unknown_indexes=[0, 1, 2])

    receipt = queue.mark_partial("req-alert-dorm", resumable=False, now=base)
    assert receipt.state is ReceiptState.FAILED_FINAL
    row = _row_state_row(tmp_path, "alertdorm.sqlite3", "req-alert-dorm")
    assert row is not None
    assert row["state"] == ReceiptState.FAILED_FINAL.value

    # 终态可剪：max_items=1 实例挤占后行必须消失（HEAD 里 partial 永不入剪除集）。
    queue2 = _build_queue(tmp_path, "alertdorm.sqlite3", max_items=1)
    queue2.submit(
        _chunk_request("req-alert-filler", ["填充"]), now=base + timedelta(seconds=30)
    )
    with sqlite3.connect(tmp_path / "alertdorm.sqlite3") as connection:
        parked = connection.execute(
            "SELECT COUNT(*) FROM send_requests WHERE state = ?",
            (PARTIAL_ROW_STATE,),
        ).fetchone()[0]
    assert int(parked) == 0


# ==================== INV-C：可观测（计数点名 + 遗留行 TTL 清扫） ====================


def test_legacy_dormant_rows_swept_to_terminal_by_prune(tmp_path: Path) -> None:
    """存量休眠行（生产 10 枚在案）：超 TTL 后由 _prune 顶部扫成 FAILED_FINAL。

    宁漏不双发：清扫只终态化、绝不重投。TTL 常量未落地即 RED。
    """
    sweep_seconds = getattr(queue_module, "_DORMANT_PARTIAL_SWEEP_SECONDS", None)
    assert sweep_seconds is not None, (
        "queue._DORMANT_PARTIAL_SWEEP_SECONDS 缺席：遗留休眠清扫尚未落地（等合入）"
    )
    queue = _build_queue(tmp_path, "sweep.sqlite3")
    base = _utc_now()
    request = _chunk_request("req-legacy-dormant", CHUNKS)
    _seed_partial(queue, request, base=base, sent_indexes=[0], unknown_indexes=[1, 2])
    _force_dormant_shape(
        tmp_path,
        "sweep.sqlite3",
        "req-legacy-dormant",
        updated_age_seconds=float(sweep_seconds) + 3600.0,
    )

    # 清扫挂在 _prune 顶部（每次 submit 顺带执行）：再入列一行即触发。
    queue.submit(
        _chunk_request("req-sweep-trigger", ["触发"]), now=base + timedelta(seconds=10)
    )

    row = _row_state_row(tmp_path, "sweep.sqlite3", "req-legacy-dormant")
    assert row is not None
    assert row["state"] == ReceiptState.FAILED_FINAL.value, (
        "超 TTL 的遗留休眠 PARTIAL 必须被扫成终态（可剪、可见），"
        "且只终态化不重投（宁漏不双发）"
    )
    # 被扫行永不再被认领（清扫触发行本身可认领，与本断言无关）。
    claimed_ids = [
        entry.send_request.request_id
        for entry in queue.claim_due(now=base + timedelta(seconds=100000))
    ]
    assert "req-legacy-dormant" not in claimed_ids


def test_worker_reports_dormant_count_and_names_rows_via_alert(tmp_path: Path) -> None:
    """worker busy 观测 + operational 告警点名：休眠行数进结果字段、超阈出告警。

    预期：HEAD RED（结果模型无 `dormant_partial_count`，无点名告警）；
    queue.list_dormant_partials + worker 观测腿合入后转绿。
    """
    queue = _build_queue(tmp_path, "observe.sqlite3")
    base = _utc_now()
    for index in range(3):
        request = _alert_card_request(f"req-obs-{index}", CHUNKS)
        _seed_partial(
            queue, request, base=base, sent_indexes=[], unknown_indexes=[0, 1, 2]
        )
        # 未超 TTL 的休眠形：清扫不该动它，专门留给观测腿点名。
        _force_dormant_shape(
            tmp_path, "observe.sqlite3", f"req-obs-{index}", updated_age_seconds=60.0
        )

    listed = getattr(queue, "list_dormant_partials", None)
    assert listed is not None, (
        "queue.list_dormant_partials 缺席：休眠 PARTIAL 视图尚未落地（等合入）"
    )
    assert len(listed()) == 3

    notifications: list = []

    def notifier(send_request, receipt):
        notifications.append((send_request, receipt))

    transport = _NullTransport()
    result = _drain(
        queue,
        transport,
        now=base + timedelta(seconds=3600),
        operational_notifier=notifier,
    )
    count = getattr(result, "dormant_partial_count", None)
    assert count is not None, (
        "SendQueueWorkerResult 无 dormant_partial_count：休眠计数未进 "
        "busy 观测（等合入）"
    )
    assert count == 3
    # 超阈值（≥1 即病态）：必须经 operational 告警口点名。
    kinds = [
        receipt.operational_issue.kind
        for _, receipt in notifications
        if receipt.operational_issue is not None
    ]
    assert "send_queue_dormant_partial" in kinds, (
        f"休眠 PARTIAL 超阈未点名告警：实收 kinds={kinds}（等合入）"
    )
    assert transport.calls == []


# ==================== 安全底座（HEAD 与修复后都必须 GREEN） ====================


def test_dormant_never_blind_resends_unknown_parts(tmp_path: Path) -> None:
    """宁漏不双发：无论收敛成什么终态，UNKNOWN part 在 confirmer=None 下绝不重发。

    本用例在 HEAD 即 GREEN——它是修复的红线护栏：终态口/清扫只允许「更响亮地
    停放」，绝不允许「更积极地重投」。
    """
    queue = _build_queue(tmp_path, "nosend.sqlite3")
    base = _utc_now()
    request = _chunk_request("req-nosend", CHUNKS)
    _seed_partial(queue, request, base=base, sent_indexes=[0, 1], unknown_indexes=[2])

    transport = _NullTransport()
    # 第一轮：认领 + 零确认（confirmer=None）→ 收敛轮（HEAD=休眠 / 修复=终态）。
    first = _drain(queue, transport, now=base + timedelta(seconds=300))
    assert first.checked == 1
    # 第二轮：无论行处于什么态，都不许再触发任何投递。
    second = _drain(queue, transport, now=base + timedelta(seconds=1000))
    assert second.checked == 0
    assert transport.calls == []
    progress = queue.part_progress("req-nosend")
    assert progress is not None and progress.unknown_indexes() == [2]
