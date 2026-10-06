"""发送队列年龄闸的可见性（用户 2026-10-06 裁定：「发丢了没人喊是最贵的一种坏」）。

真机验收事故的形状（全账见 `docs/HANDBOOK.md` §76.20；盘上实据＝
`ChatBot_Runtime/data/wuwa_send_queue.sqlite3` 里 `session_id like '%662948429%'`
的 71 枚请求全 `failed_final`、parts 的 `provider_message_id` 非空数＝0）：

    验收器把 `bot_id` 写成不匹配的哨兵 → 队列选不出在线账号
    → `queue._defer_for_bot_unavailable` 挂起（90s 一跳，不烧重试预算）
    → 到绝对年龄闸 `bot_send_bot_unavailable_max_age_seconds`（缺省 1800s）
    → 置 `failed_final`。这 71 条从此不存在了，而**全程零报错、零出口、没有任何
      人说过一句"有 N 条消息因为没在线账号被丢掉了"**——事后只能读盘上账倒推。

为什么静默（现算的真因，两处都不是"漏着没写"）：
① 年龄闸那一臂写终态时，回执里带的还是挂起那枚 issue（`kind="bot_unavailable"`）；
② worker 的告警腿 `worker._notify_operational_issue_safely` 对
   `kind == "bot_unavailable"` **一律只留 DEBUG、不打管理员告警**（R2 2026-09-17 立，
   防启动期成批挂起刷屏；它注释里那句"队列审计已承载可见性"对**挂起臂**今天仍然成立，
   但**终态臂**也被同一句一起吃掉了）。

本件的判据（做成什么样，不是排期）：
- 只有"被判死刑"那一臂出声；仍在挂起/重试的那一臂照旧静默（防每个 tick 都喊）；
- 出声走**既有中央告警口**（`alerts.notify_operational_issue`；装配腿
  `__init__._notify_queue_operational_receipt`，由 `_register_send_queue_scheduler`
  以 `operational_notifier` 注入）＋**既有抑制窗**（`alerts.AdminAlertSuppression`，
  装配现场 `operational_alert_suppression`，缺省 300s）；人话只往既有
  `alerts._KIND_PLAIN` / `error_report._ISSUE_REASON_LABELS` 两张表补登记——
  **不新建 sink、不造第二张人话表、不加配置键**；
- 🔴 投递语义零改动：行状态、`retry_count`、`next_retry_at`、幂等键形，以及盘上
  `request_json` 里那枚 `operational_issue.kind = bot_unavailable`（本事故唯一的事后
  证据面）逐字不变；也不新增任何自动补发；
- 告警口抛异常不得改变回执态与盘上账（本仓 fail-open 口径）。

全离线：SQLite 走 `tmp_path`，零网络、零真投递、零卡渲染。
"""

from __future__ import annotations

import ast
import asyncio
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

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
from plugins.bot_unified_runtime.domains.ops.monitor import alerts, error_report
from plugins.bot_unified_runtime.domains.ops.monitor.alerts import (
    AdminAlertSuppression,
    AdminTarget,
    build_operational_alert_text,
)
from plugins.bot_unified_runtime.domains.transport.sender import queue as queue_module
from plugins.bot_unified_runtime.domains.transport.sender.queue import (
    SQLiteSendRequestQueue,
)
from plugins.bot_unified_runtime.domains.transport.sender.worker import (
    drain_send_queue_once,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "bot_unified_runtime"
QUEUE_PY = PLUGIN_ROOT / "domains" / "transport" / "sender" / "queue.py"
INIT_PY = PLUGIN_ROOT / "__init__.py"
WORKER_PY = PLUGIN_ROOT / "domains" / "transport" / "sender" / "worker.py"

#: 年龄闸真身＝config `bot_send_bot_unavailable_max_age_seconds`（缺省 1800s）；
#: 本件把它压到 60s 只为让测试不睡半小时，判据本身不吃这个数值。
MAX_AGE_SECONDS = 60.0
#: 「过闸那一拍」的时刻偏移：必须同时满足两条才叫真判据——
#: ①行已到期可认领（挂臂一跳是 `max(retry_base, 90s)`＝90s，取 60+120=180s 稳超）；
#: ②入队年龄已过年龄闸（≥60s）。只满足②不满足①的那一版在空跑（现算踩到过）。
LATE_SECONDS = MAX_AGE_SECONDS + 120
#: 出声那一臂的代号（真身＝`queue._BOT_UNAVAILABLE_DROP_KIND`）。
DROP_KIND = "send_queue_dropped_bot_unavailable"
#: 挂起那一臂的代号（改前改后都必须继续静默）。
HOLD_KIND = "bot_unavailable"
#: worker 静默闸吃的代号字面（现算依据，见 test_worker_silence_gate_…）。
_HOLD_KIND_QUOTED = f"'{HOLD_KIND}'"
#: 点名器在真身里的锚（静态锁与注毒腿共用）。
#: 静态尺吃**不带括号**的那一枚——`ast.dump` 把属性调用渲染成
#: `attr='_bot_unavailable_drop_issue'`，括号根本不在 dump 里（带括号的尺永远 False，
#: 于是「干净对照」那一条先红给自己看；本席实跑踩过，现算后改锚）。
#: 注毒腿也用同一枚无括号常量整串改名（换成 `_silently_dropped_thing`）——
#: 若只替换带括号的调用形，`def _bot_unavailable_drop_issue(` 的换行签名会被咬坏，
#: `ast.parse` 直接抛 SyntaxError，判据红得毫无意义。
_DROP_WIRING_ANCHOR = "_bot_unavailable_drop_issue"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _send_request(request_id: str, dedupe_key: str) -> SendRequest:
    text = "年龄闸可见性回归正文"
    rendered = RenderedOutput(
        request_id=request_id,
        content_type="text",
        content_ref={"text": text},
        text_fallback=text,
        privacy_level=PrivacyLevel.PERSONAL,
    )
    return SendRequest(
        request_id=request_id,
        session_id="group:662948429",
        target_scope=SessionType.GROUP,
        target_id="662948429",
        capability_id="bot.chat",
        content=rendered,
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key=dedupe_key,
        cooldown_key=f"bot.chat:group:662948429:{request_id}",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="default",
        adapter="onebot",
        # 事故原形：一个认领不到任何在线账号的 bot_id。
        bot_id="sentinel-not-online",
    )


def _hold_issue() -> OperationalIssue:
    """挂起语义的 issue（真身＝装配腿 `_queue_bot_unavailable_receipt` 造的那枚）。"""
    return OperationalIssue(
        stage="queue",
        kind=HOLD_KIND,
        retryable=True,
        safe_summary="bot_unavailable",
    )


def _build_queue(tmp_path: Path) -> SQLiteSendRequestQueue:
    return SQLiteSendRequestQueue(
        tmp_path / "send_queue.sqlite3",
        InMemoryAuditLogger(),
        bot_unavailable_max_age_seconds=MAX_AGE_SECONDS,
    )


async def _resolved(value: DeliveryReceipt) -> DeliveryReceipt:
    return value


def _transport_receipt(request: SendRequest, now: datetime) -> DeliveryReceipt:
    """认领腿替身：选不出在线账号 ⇒ 挂起（真身＝`__init__._queue_bot_unavailable_receipt`）。"""
    return DeliveryReceipt(
        request_id=request.request_id,
        state=ReceiptState.FAILED_RETRYABLE,
        transport="send_queue_worker",
        public_message="",
        created_at=now,
        operational_issue=_hold_issue(),
    )


def _read_row(db_path: Path, dedupe_key: str) -> sqlite3.Row:
    with closing(sqlite3.connect(str(db_path))) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM send_requests WHERE dedupe_key = ?", (dedupe_key,)
        ).fetchone()
    assert row is not None, f"行不存在 dedupe_key={dedupe_key}"
    return row


def _persisted_issue_kind(db_path: Path, dedupe_key: str) -> str:
    """盘上 `request_json.operational_issue.kind`（事故的事后取证面，不许被改写）。"""
    payload = json.loads(str(_read_row(db_path, dedupe_key)["request_json"]))
    issue = payload.get("operational_issue") or {}
    return str(issue.get("kind", ""))


def _receipt_face(receipt: DeliveryReceipt) -> dict[str, Any]:
    """回执里属于投递语义的那几项（`debug_id`/`created_at` 是随机量，不参与比对）。"""
    return {
        "request_id": receipt.request_id,
        "state": receipt.state.value,
        "transport": receipt.transport,
        "retry_count": receipt.retry_count,
        "next_retry_at": receipt.next_retry_at,
        "public_message": receipt.public_message,
        "provider_message_id": receipt.provider_message_id,
    }


def _row_face(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "state": str(row["state"]),
        "retry_count": int(row["retry_count"]),
        "next_retry_at": row["next_retry_at"],
        "dedupe_key": str(row["dedupe_key"]),
        "last_public_message": str(row["last_public_message"]),
    }


# ---------------------------------------------------------------------------
# ① 年龄闸那一臂必须出声（行为腿）
# ---------------------------------------------------------------------------


def test_age_gate_drop_receipt_carries_an_alert_bearing_issue(tmp_path) -> None:
    """被判死刑那一臂的回执必须带一枚**不再被静默闸吃掉**的 issue，且点名原因。"""
    queue = _build_queue(tmp_path)
    base = _utc_now()
    queue.submit(_send_request("req-drop-1", "dk-drop-1"), now=base)

    receipt = queue.mark_retryable_failure(
        "req-drop-1",
        "failed",
        now=base + timedelta(seconds=MAX_AGE_SECONDS + 1),
        operational_issue=_hold_issue(),
    )

    assert receipt.state is ReceiptState.FAILED_FINAL, receipt
    issue = receipt.operational_issue
    assert issue is not None, "终态回执不带 issue ⇒ 中央告警口第一行就 return，永远不进告警链"
    assert issue.kind == DROP_KIND, (
        f"kind={issue.kind!r} 仍是挂起代号 ⇒ worker 静默闸把它一起吃掉（＝没人喊）"
    )
    assert issue.stage == "queue", issue
    # 「还能不能补发」：终态不许伪装成还能重试。
    assert issue.retryable is False, issue
    # 「哪一枚请求 / 投给哪个会话 / 撞的是哪道时限」必须能从这一行读出来。
    summary = str(issue.safe_summary)
    assert "req-drop-1" in summary, summary
    assert "group:662948429" in summary, summary
    assert f"{MAX_AGE_SECONDS:.0f}" in summary, f"没写清是哪道时限判的死：{summary}"


def test_alert_text_for_drop_issue_reads_as_chinese(tmp_path) -> None:
    """走既有人话表：主句必须是中文，且说清「没有在线账号 + 被丢弃 + 不会自动补发」。"""
    queue = _build_queue(tmp_path)
    base = _utc_now()
    queue.submit(_send_request("req-drop-text", "dk-drop-text"), now=base)
    receipt = queue.mark_retryable_failure(
        "req-drop-text",
        "failed",
        now=base + timedelta(seconds=MAX_AGE_SECONDS + 1),
        operational_issue=_hold_issue(),
    )
    issue = receipt.operational_issue
    assert issue is not None

    text = build_operational_alert_text(
        issue,
        source_adapter="onebot",
        source_bot="sentinel-not-online",
        session_type=SessionType.GROUP,
    )
    head = "\n".join(text.splitlines()[:-1])
    assert alerts.ALERT_UNREGISTERED_MARK not in head, (
        f"代号没进既有人话表，读起来仍是「还没登记中文说明」：{head}"
    )
    assert "在线" in head and "丢" in head, head
    assert "重试也没用" in head, head  # 终态：得有人看一眼
    assert "群聊" in head, head
    assert "req-drop-text" in head, head  # 「哪一枚请求」在人话块里就看得见
    # 运维 grep 契约：技术行照旧带 stage/kind/detail。
    tech = text.splitlines()[-1]
    assert f"stage=queue kind={DROP_KIND}" in tech, tech
    assert "detail=" in tech, tech


def test_both_prose_faces_register_the_drop_kind() -> None:
    """两面同锁（#55 告警人话族纪律）：主句表 + 诊断卡「报错原因」表都要在册。"""
    assert DROP_KIND in alerts._KIND_PLAIN, sorted(alerts._KIND_PLAIN)
    assert DROP_KIND in error_report._ISSUE_REASON_LABELS, sorted(
        error_report._ISSUE_REASON_LABELS
    )
    label = error_report._reason_label("", "", issue_kind=DROP_KIND)
    assert label and "未归类" not in label and not label.isascii(), label


def test_channel_notifies_exactly_once_when_the_age_gate_fires(tmp_path) -> None:
    """端到端（队列→worker 既有告警腿→notifier）：过闸那一拍**恰好一次**，不多喊。"""
    notified: list[tuple[str, str]] = []

    def notifier(send_request: SendRequest, receipt: DeliveryReceipt) -> None:
        issue = receipt.operational_issue
        notified.append((send_request.request_id, str(getattr(issue, "kind", ""))))

    queue = _build_queue(tmp_path)
    request = _send_request("req-once", "dk-once")
    base = _utc_now()
    queue.submit(request, now=base, deliver_after=base)

    # 第一拍：刚入队即可认领（deliver_after 覆盖了内联宽限），未到年龄闸 ⇒ 静默。
    asyncio.run(
        drain_send_queue_once(
            queue,
            lambda pending: _resolved(_transport_receipt(pending, base)),
            now=base,
            operational_notifier=notifier,
        )
    )
    assert notified == [], f"未到年龄闸就喊了＝每个 tick 都喊的刷屏形状：{notified}"

    # 第二拍：过闸 ⇒ 终态 ⇒ 恰好一次。
    late = base + timedelta(seconds=LATE_SECONDS)
    asyncio.run(
        drain_send_queue_once(
            queue,
            lambda pending: _resolved(_transport_receipt(pending, late)),
            now=late,
            operational_notifier=notifier,
        )
    )
    assert notified == [("req-once", DROP_KIND)], notified


def test_hold_arm_stays_silent_and_keeps_queue_semantics(tmp_path) -> None:
    """挂臂（未到年龄闸）零告警、零烧预算、行仍可投——既有语义一字不动。"""
    notified: list[DeliveryReceipt] = []
    queue = _build_queue(tmp_path)
    request = _send_request("req-hold", "dk-hold")
    base = _utc_now()
    queue.submit(request, now=base)

    for tick in range(3):
        receipt = queue.mark_retryable_failure(
            "req-hold",
            "failed",
            now=base + timedelta(seconds=10 * (tick + 1)),
            operational_issue=_hold_issue(),
        )
        assert receipt.state is ReceiptState.FAILED_RETRYABLE, receipt
        assert receipt.operational_issue is not None
        assert receipt.operational_issue.kind == HOLD_KIND, receipt

    asyncio.run(
        drain_send_queue_once(
            queue,
            lambda pending: _resolved(_transport_receipt(pending, base)),
            now=base + timedelta(seconds=MAX_AGE_SECONDS - 1),
            operational_notifier=lambda receipt: notified.append(receipt),
        )
    )
    assert notified == [], "挂臂被卷进告警面＝刷屏三连回潮（R2 防的就是这个）"
    entry = queue._find_entry_by_request_id("req-hold")
    assert entry is not None and entry.retry_count == 0, entry
    sent = queue.mark_sent("req-hold")
    assert sent.state is ReceiptState.SENT, sent


# ---------------------------------------------------------------------------
# ② 🔴 投递语义与盘上证据零改动（红线腿）
# ---------------------------------------------------------------------------


def test_delivery_semantics_and_disk_evidence_are_unchanged(tmp_path) -> None:
    """只加"看得见"：认领判据/重试预算/终态判定/幂等键形/盘上 kind 全不许动。"""
    queue = _build_queue(tmp_path)
    request = _send_request("req-semantics", "dk-semantics")
    base = _utc_now()
    queue.submit(request, now=base)

    receipt = queue.mark_retryable_failure(
        "req-semantics",
        "failed",
        now=base + timedelta(seconds=MAX_AGE_SECONDS + 1),
        operational_issue=_hold_issue(),
    )
    row = _read_row(tmp_path / "send_queue.sqlite3", "dk-semantics")

    assert receipt.state is ReceiptState.FAILED_FINAL
    assert receipt.retry_count == 0, "挂臂不该烧重试预算"
    assert receipt.next_retry_at is None, "终态不该再排重试"
    assert row["state"] == ReceiptState.FAILED_FINAL.value
    assert int(row["retry_count"]) == 0
    assert row["next_retry_at"] is None
    assert str(row["dedupe_key"]) == "dk-semantics", "幂等键形不许动"
    # 本事故复跑靠的就是这一行：盘上账仍写挂起代号（事后取证面逐字不变）。
    assert _persisted_issue_kind(tmp_path / "send_queue.sqlite3", "dk-semantics") == HOLD_KIND


def test_no_auto_resubmit_is_added(tmp_path) -> None:
    """「要不要自动补发」是另一裁：本件绝不让终态行重新可认领。"""
    queue = _build_queue(tmp_path)
    base = _utc_now()
    queue.submit(_send_request("req-noresubmit", "dk-noresubmit"), now=base)
    queue.mark_retryable_failure(
        "req-noresubmit",
        "failed",
        now=base + timedelta(seconds=MAX_AGE_SECONDS + 1),
        operational_issue=_hold_issue(),
    )

    claimed = queue.claim_due(now=base + timedelta(days=7), limit=20)
    assert claimed == [], "终态行被重新认领＝顺手加了自动补发"


# ---------------------------------------------------------------------------
# ③ 告警失败不许拖垮投递（fail-open 腿）
# ---------------------------------------------------------------------------


def test_exploding_alert_leaves_receipt_and_row_identical(tmp_path) -> None:
    """告警口抛异常 ⇒ 回执态与盘上账与「告警口正常」那一趟逐字相同。"""
    def run(name: str, notifier: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        db_dir = tmp_path / name
        db_dir.mkdir()
        queue = SQLiteSendRequestQueue(
            db_dir / "q.sqlite3",
            InMemoryAuditLogger(),
            bot_unavailable_max_age_seconds=MAX_AGE_SECONDS,
        )
        request = _send_request("req-failopen", "dk-failopen")
        base = _utc_now()
        queue.submit(request, now=base, deliver_after=base)
        late = base + timedelta(seconds=LATE_SECONDS)
        asyncio.run(
            drain_send_queue_once(
                queue,
                lambda pending: _resolved(_transport_receipt(pending, late)),
                now=late,
                limit=5,
                operational_notifier=notifier,
            )
        )
        # 同一枚判定再走一次（行已终态，这次调用只判定、不再改写投递语义）。
        receipt = queue.mark_retryable_failure(
            "req-failopen",
            "failed",
            now=late,
            operational_issue=_hold_issue(),
        )
        return _receipt_face(receipt), _row_face(
            _read_row(db_dir / "q.sqlite3", "dk-failopen")
        )

    def quiet(_request: SendRequest, _receipt: DeliveryReceipt) -> None:
        return None

    def explode(_request: SendRequest, _receipt: DeliveryReceipt) -> None:
        raise RuntimeError("告警口炸了")

    quiet_receipt, quiet_row = run("quiet", quiet)
    loud_receipt, loud_row = run("loud", explode)

    assert quiet_receipt["state"] == loud_receipt["state"] == "failed_final"
    assert quiet_receipt == loud_receipt, (
        f"告警口炸与不炸，回执态不该有差：{quiet_receipt} vs {loud_receipt}"
    )
    assert quiet_row == loud_row, (
        f"告警口炸与不炸，盘上投递面不该有差：{quiet_row} vs {loud_row}"
    )
    assert loud_row["state"] == "failed_final"
    assert loud_receipt["next_retry_at"] is None


# ---------------------------------------------------------------------------
# ④ 复用既有抑制窗：同一原因连撞两次只喊一次
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_reason_twice_in_one_window_shouts_once() -> None:
    """告警文本与投递走既有 `notify_operational_issue` + `AdminAlertSuppression`。"""
    target = AdminTarget(adapter="onebot", bot_id="qq-bot", target_id="90001")
    suppression = AdminAlertSuppression(window_seconds=300.0)
    delivered: list[str] = []

    async def fake_delivery(
        _target: AdminTarget, _bot: object, request: SendRequest
    ) -> DeliveryReceipt:
        delivered.append(str(request.content.text_fallback))
        return DeliveryReceipt(
            request_id=request.request_id,
            state=ReceiptState.SENT,
            transport="fake",
            public_message="sent",
        )

    def issue(index: int) -> OperationalIssue:
        return OperationalIssue(
            stage="queue",
            kind=DROP_KIND,
            retryable=False,
            safe_summary=(
                f"{DROP_KIND} held=900s>={MAX_AGE_SECONDS:.0f}s req=req-{index} sess=group:1"
            ),
        )

    first = await alerts.notify_operational_issue(
        issue(1),
        source_adapter="onebot",
        source_bot="sentinel-not-online",
        session_type=SessionType.GROUP,
        targets=[target],
        online_bots={target.bot_id: object()},
        delivery=fake_delivery,
        suppression=suppression,
    )
    second = await alerts.notify_operational_issue(
        issue(2),
        source_adapter="onebot",
        source_bot="sentinel-not-online",
        session_type=SessionType.GROUP,
        targets=[target],
        online_bots={target.bot_id: object()},
        delivery=fake_delivery,
        suppression=suppression,
    )

    assert len(delivered) == 1, f"同一原因喊了 {len(delivered)} 次＝刷屏"
    assert first[0].suppressed is False, first[0]
    assert second[0].suppressed is True, second[0]
    assert second[0].suppressed_count >= 1, second[0]
    # 「同时压着 N 条同类没重复发」＝既有量具给出的"多少条"读数。
    assert "同时压着" in delivered[0] or DROP_KIND in delivered[0], delivered[0][:200]


@pytest.fixture(autouse=True)
def _no_real_card_render(monkeypatch: pytest.MonkeyPatch) -> None:
    """全离线保底：本件绝不让诊断卡真渲染/真入队（pipeline 缺省 None 本已跳过，这是第二层）。"""

    def _boom(*_a: Any, **_kw: Any) -> None:
        raise AssertionError("可见性测试不得触达卡渲染/入队")

    monkeypatch.setattr(alerts, "schedule_issue_card", _boom)


# ---------------------------------------------------------------------------
# ⑤ 这台门今天真有进料（静态腿：告警链每一环都得在册，缺一即红）
# ---------------------------------------------------------------------------


def _function_node(source: str, name: str, node_types: tuple[type, ...]) -> ast.AST:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, node_types) and getattr(node, "name", "") == name:
            return node
    raise AssertionError(f"{name} 不在真身文件里（改名/搬走＝本锁失效，先现算再重钉）")


def _silences_this_kind(node: ast.AST) -> list[ast.Return]:
    """体内「判到某 kind 就裸 return」的语句＝把一类故障从可见面摘掉的形状。"""
    hits: list[ast.Return] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.If) or _HOLD_KIND_QUOTED not in ast.dump(child.test):
            continue
        hits.extend(
            stmt for stmt in child.body if isinstance(stmt, ast.Return) and stmt.value is None
        )
    return hits


def test_assembly_feeds_the_central_alert_door_for_the_queue() -> None:
    """队列 worker 的 `operational_notifier` 确实接在中央告警口上（治台账 #49/#56 那型）。"""
    init_source = INIT_PY.read_text(encoding="utf-8")
    assert "operational_notifier=_notify_queue_operational_receipt," in init_source, (
        "装配层不再把队列告警腿接到 `_notify_queue_operational_receipt` ⇒ 告警链整条断"
    )
    node = _function_node(
        init_source, "_notify_queue_operational_receipt", (ast.AsyncFunctionDef,)
    )
    assert any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "notify_operational_issue"
        for call in ast.walk(node)
    ), "队列终账器不再调中央告警口 ⇒ 出声的不是告警，本件的判据落空"
    # 中央口不许为这一枚代号再装第二道静默闸（C1-c 同族教训）。
    assert _silences_this_kind(node) == [], "装配腿里又出现按 kind 裸 return＝第二道静默闸"


def test_worker_silence_gate_does_not_cover_the_drop_kind() -> None:
    """worker 静默闸只吃挂起代号；年龄闸那枚新代号必须从它手上漏出去（＝被投出）。"""
    node = _function_node(
        WORKER_PY.read_text(encoding="utf-8"),
        "_notify_operational_issue_safely",
        (ast.AsyncFunctionDef,),
    )
    compared = {
        value.value
        for child in ast.walk(node)
        if isinstance(child, ast.Compare)
        for value in ([child.left, *child.comparators])
        if isinstance(value, ast.Constant) and isinstance(value.value, str)
    }
    assert HOLD_KIND in compared, (
        "静默闸真身变了（R2 早退被搬走/改名）＝本锁失效，先现算再重钉"
    )
    assert DROP_KIND not in compared, "年龄闸那枚代号也被静默闸吃掉 ⇒「发丢了没人喊」原样回潮"


def _drop_branch_is_wired(source: str) -> bool:
    """`_defer_for_bot_unavailable` 的 `if hold_expired:` 分支引用点名器，else 分支不引用。"""
    node = _function_node(source, "_defer_for_bot_unavailable", (ast.FunctionDef,))
    for child in ast.walk(node):
        if not isinstance(child, ast.If) or "hold_expired" not in ast.dump(child.test):
            continue
        body = ast.dump(ast.Module(body=list(child.body), type_ignores=[]))
        other = ast.dump(ast.Module(body=list(child.orelse), type_ignores=[]))
        return _DROP_WIRING_ANCHOR in body and _DROP_WIRING_ANCHOR not in other
    raise AssertionError("年龄闸分支（if hold_expired）不在真身里＝判据尺已瞎，先现算再动锁")


def test_age_gate_branch_is_wired_to_the_drop_issue() -> None:
    assert _drop_branch_is_wired(QUEUE_PY.read_text(encoding="utf-8")), (
        "年龄闸那一臂没接上点名器 `_bot_unavailable_drop_issue` ⇒ 这条死路仍无人喊"
    )


def test_static_lock_bites_when_the_alert_call_is_ripped_out() -> None:
    """注毒自证（静态腿）：内存副本里摘掉点名器 ⇒ 尺必须点名红；真树同尺必须为绿。"""
    source = QUEUE_PY.read_text(encoding="utf-8")
    assert _DROP_WIRING_ANCHOR in source, "锚点失配＝现状已变，先现算再动锁"
    poisoned = source.replace(_DROP_WIRING_ANCHOR, "_silently_dropped_thing")
    assert poisoned != source, "注毒没打进去＝这一发在空跑"
    assert _drop_branch_is_wired(source), "干净对照就该是绿的（绿得诚实，不是分母空转）"
    assert not _drop_branch_is_wired(poisoned), "摘掉告警调用后判据仍不红＝这把门是装饰"


def test_behavior_lock_bites_when_the_drop_issue_is_neutralized(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """注毒腿（行为面）：点名器退回挂起代号（＝等价于告警调用被摘掉）⇒ 端到端零告警。

    为什么两腿都要：只测「队列返回了新 kind」而 worker/装配那两环没接上，仍是台账
    #49 的「在册未执法」形状——所以行为判据必须打到 notifier 真被叫过一次。
    """
    monkeypatch.setattr(
        queue_module.SQLiteSendRequestQueue,
        "_bot_unavailable_drop_issue",
        lambda self, entry, issue, *, now: issue,
    )
    notified: list[DeliveryReceipt] = []
    queue = _build_queue(tmp_path)
    request = _send_request("req-poison", "dk-poison")
    base = _utc_now()
    queue.submit(request, now=base, deliver_after=base)
    late = base + timedelta(seconds=LATE_SECONDS)
    asyncio.run(
        drain_send_queue_once(
            queue,
            lambda pending: _resolved(_transport_receipt(pending, late)),
            now=late,
            operational_notifier=lambda receipt: notified.append(receipt),
        )
    )
    assert notified == [], "注毒后仍告警＝这条行为判据在测别的东西（假绿）"
