"""SEAT-FIX-QKEY 修复回归：发送队列共键写扇出簇（SEAT-ATK-QUEUE Q-G1/G3/G4/G5/G6）。

离线运行（SQLite 用 tmp_path，无网络、无 SnowLuma）：

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_queue_shared_key_fanout_fix.py -q

依据 `.superpowers/sdd/2026-09-27-fullload/logs/SEAT-ATK-QUEUE.md` §一（判定表）与
§二-A/B/C（离线复刻）。核心事实：`send_requests` 行主键是 dedupe_key，
request_id 非唯一且**被刻意复用**（error_report ack/card 共键，审查 E-12；
生产库 7 组实锤）。修复前一切状态写与 part 账都以 request_id 为谓词 ⇒
兄弟行互相改写（SENT 行被复活带兄弟正文再认领＝双发）、共 part 账
（B 一条没发账上全送达＝静默丢）、内联台账共槽（A-22 防双发盾失效）。

覆盖项：
- R-A（Q-G1）：同 request_id 两行，A 成功 + B 失败 ⇒ 各持各自状态与正文、
  认领不双发（§二-A 场景的修复后固化）。
- R-A2（Q-G1 内联腿）：legacy 单参 `mark_sent(request_id)`（根装配真形）在
  兄弟行并存时按内联台账精准落自己行。
- R-B（Q-G5）：part 账兄弟隔离 + digest 守卫拒绝复用；worker 遇冲突账
  fail-closed（绝不回落整发）。
- R-C（Q-G6）：内联台账兄弟各占各槽、终结各清各槽。
- R-G3（Q-G3）：心跳列只前进不吃旧（pass-start/过去注入值被墙钟顶起）。
- R-G4（Q-G4）：expires_at 认领门 + 心跳久旱僵尸清扫（新造 processing 行
  不受影响——b3ba9ba 两案的形状保持）。
- 结构锁：queue.py 内所有 `UPDATE send_requests` 的 WHERE 必须含行主键
  （dedupe_key/rowid），所有 `UPDATE send_request_parts` 必须含身份列
  （dedupe_key/part_key）；注毒自证——把谓词改回共键形状，同一判据必咬。
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

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
from plugins.bot_unified_runtime.domains.transport.sender import worker as worker_module
from plugins.bot_unified_runtime.domains.transport.sender.queue import (
    PartLedgerConflictError,
    SQLiteSendRequestQueue,
)

QUEUE_SOURCE_PATH = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "transport"
    / "sender"
    / "queue.py"
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _send_request(
    request_id: str,
    dedupe_key: str,
    *,
    text: str = "共键扇出回归正文",
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
        session_id="private:fanout-user",
        target_scope=SessionType.PRIVATE,
        target_id="fanout-user",
        capability_id="bot.chat",
        content=rendered,
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key=dedupe_key,
        cooldown_key="bot.chat:private:fanout-user",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="default",
    )


def _chunks_request(request_id: str, dedupe_key: str, chunks: list[str]) -> SendRequest:
    rendered = RenderedOutput(
        request_id=request_id,
        content_type="chunks",
        content_ref={"chunks": list(chunks)},
        text_fallback="".join(chunks),
        privacy_level=PrivacyLevel.PERSONAL,
    )
    return SendRequest(
        request_id=request_id,
        session_id="private:fanout-user",
        target_scope=SessionType.PRIVATE,
        target_id="fanout-user",
        capability_id="bot.chat",
        content=rendered,
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=len(chunks),
        dedupe_key=dedupe_key,
        cooldown_key="bot.chat:private:fanout-user",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="default",
    )


def _build_queue(tmp_path: Path) -> SQLiteSendRequestQueue:
    return SQLiteSendRequestQueue(
        tmp_path / "send_queue.sqlite3",
        InMemoryAuditLogger(),
    )


def _row_snapshot(db_path: Path) -> dict[str, dict[str, object]]:
    """独立只读连接按行主键取 (state, retry_count, 正文文本)。"""
    connection = sqlite3.connect(str(db_path))
    try:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT dedupe_key, state, retry_count, request_json FROM send_requests"
        ).fetchall()
    finally:
        connection.close()
    snapshot: dict[str, dict[str, object]] = {}
    for row in rows:
        payload = json.loads(str(row["request_json"]))
        snapshot[str(row["dedupe_key"])] = {
            "state": str(row["state"]),
            "retry_count": int(row["retry_count"]),
            "text": str((payload.get("content") or {}).get("content_ref", {}).get("text", "")),
            "payload_dedupe": str(payload.get("dedupe_key", "")),
        }
    return snapshot


def _sent_receipt(request: SendRequest) -> DeliveryReceipt:
    return DeliveryReceipt(
        request_id=request.request_id,
        state=ReceiptState.SENT,
        transport="fake",
        public_message="sent",
    )


# ---------------------------------------------------------------------------
# R-A（Q-G1）：兄弟行不互相改写；认领不双发（§二-A 修复后固化）


def test_qg1_sibling_writes_do_not_fanout(tmp_path: Path) -> None:
    queue = _build_queue(tmp_path)
    db = tmp_path / "send_queue.sqlite3"
    base = _utc_now() - timedelta(hours=2)  # 宽限期外，纯 worker 形
    request_a = _send_request("req-shared", "dk-A", text="first")
    request_b = _send_request("req-shared", "dk-B", text="second")
    queue.submit(request_a, now=base, deliver_after=base)
    queue.submit(request_b, now=base, deliver_after=base)

    # A1'：A 送达（显式行身份）——B 不得被洗成 SENT，正文不得被覆写。
    queue.mark_sent("req-shared", "sent", now=base + timedelta(minutes=1), dedupe_key="dk-A")
    snap = _row_snapshot(db)
    assert snap["dk-A"]["state"] == ReceiptState.SENT.value
    assert snap["dk-B"]["state"] == ReceiptState.QUEUED.value
    assert snap["dk-B"]["text"] == "second"

    # A2'：B 可重试失败——A 不得被复活，两行正文各归各。
    queue.mark_retryable_failure(
        "req-shared", "boom", now=base + timedelta(minutes=2), dedupe_key="dk-B"
    )
    snap = _row_snapshot(db)
    assert snap["dk-A"]["state"] == ReceiptState.SENT.value
    assert snap["dk-A"]["text"] == "first"
    assert snap["dk-A"]["retry_count"] == 0
    assert snap["dk-B"]["state"] == ReceiptState.FAILED_RETRYABLE.value
    assert snap["dk-B"]["retry_count"] == 1

    # A3'：宽限/退避过后认领——只有 B 一行可认领，且带着它自己的正文。
    claimed = queue.claim_due(now=base + timedelta(hours=3))
    assert [entry.row_dedupe_key for entry in claimed] == ["dk-B"]
    assert claimed[0].send_request.content.content_ref["text"] == "second"


@pytest.mark.asyncio
async def test_qg1_inline_legacy_mark_resolves_own_row(tmp_path: Path) -> None:
    """根装配真形：`mark_sent(request_id)` 单参调用，兄弟行并存时按内联台账
    落自己那一行（修复前「取最新一行」启发式会把 A 的 SENT 写到 B 上）。"""
    queue = _build_queue(tmp_path)
    db = tmp_path / "send_queue.sqlite3"
    base = _utc_now() - timedelta(hours=2)
    submitted = asyncio.Event()
    both_in = asyncio.Event()
    counter = 0

    async def handler(dedupe_key: str, text: str) -> None:
        nonlocal counter
        queue.submit(_send_request("req-inline", dedupe_key, text=text), now=base)
        counter += 1
        if counter == 2:
            both_in.set()
        else:
            submitted.set()
            await both_in.wait()
        # legacy 单参终结口（不传 dedupe_key）——生产 `_record_transport_receipt` 形状。
        if dedupe_key == "dk-A":
            queue.mark_sent("req-inline", now=base + timedelta(minutes=1))
        else:
            queue.mark_retryable_failure(
                "req-inline", "boom", now=base + timedelta(minutes=1)
            )

    task_a = asyncio.create_task(handler("dk-A", "first"))
    await submitted.wait()
    task_b = asyncio.create_task(handler("dk-B", "second"))
    await asyncio.gather(task_a, task_b)

    snap = _row_snapshot(db)
    assert snap["dk-A"]["state"] == ReceiptState.SENT.value
    assert snap["dk-A"]["text"] == "first"
    assert snap["dk-B"]["state"] == ReceiptState.FAILED_RETRYABLE.value
    assert snap["dk-B"]["text"] == "second"


# ---------------------------------------------------------------------------
# R-B（Q-G5）：part 账兄弟隔离 + digest 守卫 + worker 冲突不回落整发


def test_qg5_part_ledgers_isolated_between_siblings(tmp_path: Path) -> None:
    queue = _build_queue(tmp_path)
    base = _utc_now()
    queue.submit(_send_request("req-p", "dk-A", text="first"), now=base)
    queue.submit(_send_request("req-p", "dk-B", text="second"), now=base)

    queue.ensure_parts_planned("req-p", ["dA0", "dA1"], now=base, dedupe_key="dk-A")
    assert queue.mark_part_sent("req-p", 0, now=base, dedupe_key="dk-A")
    assert queue.mark_part_sent("req-p", 1, now=base, dedupe_key="dk-A")

    # §二-B：修复前 B 规划会看到 total=2 delivered=2（一条没发账上全送达）。
    progress_b = queue.ensure_parts_planned(
        "req-p", ["dB0", "dB1"], now=base, dedupe_key="dk-B"
    )
    assert progress_b is not None
    assert progress_b.total == 2
    assert progress_b.delivered == 0
    assert progress_b.pending_indexes() == [0, 1]
    assert progress_b.unknown_indexes() == []

    progress_a = queue.part_progress("req-p", dedupe_key="dk-A")
    assert progress_a is not None and progress_a.delivered == 2


def test_qg5_digest_guard_refuses_ledger_reuse(tmp_path: Path) -> None:
    queue = _build_queue(tmp_path)
    base = _utc_now()
    queue.submit(_send_request("req-d", "dk-D"), now=base)
    queue.ensure_parts_planned("req-d", ["d0", "d1"], now=base, dedupe_key="dk-D")
    with pytest.raises(PartLedgerConflictError):
        queue.ensure_parts_planned(
            "req-d", ["d0", "CHANGED"], now=base, dedupe_key="dk-D"
        )


@pytest.mark.asyncio
async def test_qg5_worker_fences_conflict_never_wholesends(tmp_path: Path) -> None:
    """账本 digest 冲突时 worker 绝不回落整发（那是 §9.3「UNKNOWN 不盲重发」
    保证的漏口），只准按 result_unknown 终态化收口。"""
    queue = _build_queue(tmp_path)
    db = tmp_path / "send_queue.sqlite3"
    base = _utc_now() - timedelta(hours=2)
    chunks = ["分片一", "分片二", "分片三"]
    request = _chunks_request("req-conflict", "dk-C", chunks)
    queue.submit(request, now=base, deliver_after=base)
    # 预置一本 digest 不符的账（同身份 → 与 worker 规划同源同行）。
    queue.ensure_parts_planned(
        "req-conflict", ["xx0", "xx1", "xx2"], now=base, dedupe_key="dk-C"
    )

    sent: list[str] = []

    async def transport(send_request: SendRequest) -> DeliveryReceipt:
        sent.append(str(send_request.content.content_ref))
        return _sent_receipt(send_request)

    result = await worker_module.drain_send_queue_once(
        queue, transport, now=base + timedelta(hours=1)
    )
    assert sent == []  # 零投递：没发过也不重发，更不会整发
    assert result.final_failed == 1
    snap = _row_snapshot(db)
    assert snap["dk-C"]["state"] == ReceiptState.FAILED_FINAL.value
    issues = result.operational_issues
    assert any(issue.kind == "part_ledger_conflict" for issue in issues)


# ---------------------------------------------------------------------------
# R-C（Q-G6）：内联台账兄弟各占各槽


@pytest.mark.asyncio
async def test_qg6_sibling_inline_slots_do_not_evict_each_other(
    tmp_path: Path,
) -> None:
    queue = _build_queue(tmp_path)
    base = _utc_now() - timedelta(hours=2)  # 行对 worker 立即到期
    ready = asyncio.Event()
    hold_a = asyncio.Event()
    hold_b = asyncio.Event()
    arrived = 0

    async def handler(dedupe_key: str, event: asyncio.Event) -> None:
        nonlocal arrived
        queue.submit(_send_request("req-slot", dedupe_key), now=base)
        arrived += 1
        if arrived == 2:
            ready.set()
        await event.wait()
        queue.mark_sent("req-slot", now=base + timedelta(minutes=5))

    task_a = asyncio.create_task(handler("dk-A", hold_a))
    task_b = asyncio.create_task(handler("dk-B", hold_b))
    await ready.wait()

    # 两兄弟各占一槽（修复前：一槽顶掉前任，台账只剩一条）。
    assert set(queue._inline_claims.keys()) == {"dk-A", "dk-B"}
    # 双在途：外来认领者两行都拿不到。
    assert queue.claim_due(now=base + timedelta(hours=1)) == []

    # B 终结只清自己的槽；A 仍在途，其行照旧受 A-22 保护。
    hold_b.set()
    await task_b
    assert set(queue._inline_claims.keys()) == {"dk-A"}
    claimed = queue.claim_due(now=base + timedelta(hours=1))
    # B 行已 SENT 不可认领；A 行被存活台账否决——本轮零认领。
    assert claimed == []

    hold_a.set()
    await task_a
    assert queue._inline_claims == {}


# ---------------------------------------------------------------------------
# R-G3：心跳只前进不吃旧（§一 Q-G3）


def test_qg3_heartbeat_never_stamps_past_wall(tmp_path: Path) -> None:
    queue = _build_queue(tmp_path)
    db = tmp_path / "send_queue.sqlite3"
    past = _utc_now() - timedelta(minutes=40)
    queue.submit(_send_request("req-hb", "dk-HB"), now=past, deliver_after=past)
    claimed = queue.claim_due(now=past)  # 认领时刻注入在过去
    assert [entry.row_dedupe_key for entry in claimed] == ["dk-HB"]
    connection = sqlite3.connect(str(db))
    try:
        stamp = str(
            connection.execute(
                "SELECT updated_at FROM send_requests WHERE dedupe_key = 'dk-HB'"
            ).fetchone()[0]
        )
    finally:
        connection.close()
    updated_at = datetime.fromisoformat(stamp)
    # 刚发生的写入不得盖上 40 分钟前的戳：心跳 ≥ 本次认领的墙钟邻域。
    assert updated_at >= _utc_now() - timedelta(seconds=60)
    # 而调度列（租约）仍按注入时刻——调度语义不被心跳改动绑架。
    assert claimed[0].lease_expires_at is not None
    assert claimed[0].lease_expires_at <= past + timedelta(seconds=90)


# ---------------------------------------------------------------------------
# R-G4：expires_at 认领门 + 僵尸清扫（且新造 processing 行不受波及）


def test_qg4_expired_processing_row_gated_and_finalized(tmp_path: Path) -> None:
    queue = _build_queue(tmp_path)
    db = tmp_path / "send_queue.sqlite3"
    base = _utc_now() - timedelta(hours=2)
    expires = base + timedelta(minutes=2)
    request = _send_request("req-exp", "dk-EXP").model_copy(update={"expires_at": expires})
    queue.submit(request, now=base, deliver_after=base)
    claimed = queue.claim_due(now=base + timedelta(minutes=1))
    assert [entry.row_dedupe_key for entry in claimed] == ["dk-EXP"]

    # 期限已过：PROCESSING 臂不得重认领；清扫口把它终态化（不重投）。
    later = queue.claim_due(now=base + timedelta(minutes=3))
    assert [entry.row_dedupe_key for entry in later] == []
    snap = _row_snapshot(db)
    assert snap["dk-EXP"]["state"] == ReceiptState.FAILED_FINAL.value


def test_qg4_stale_heartbeat_zombie_finalized_fresh_rows_safe(tmp_path: Path) -> None:
    queue = _build_queue(tmp_path)
    db = tmp_path / "send_queue.sqlite3"
    base = _utc_now() - timedelta(hours=3)
    queue.submit(_send_request("req-zombie", "dk-Z"), now=base, deliver_after=base)
    queue.submit(_send_request("req-fresh", "dk-F"), now=base, deliver_after=base)
    claimed = queue.claim_due(now=base + timedelta(minutes=1), limit=1)
    assert [entry.row_dedupe_key for entry in claimed] == ["dk-Z"]
    # 直写制造「最后心跳距今 2 天」的僵尸（claim 注入的是过去虚构钟，
    # 心跳写会顶到墙钟——所以僵尸形态必须用直写模拟，与生产残留同形）。
    stale = (_utc_now() - timedelta(days=2)).isoformat()
    with sqlite3.connect(str(db)) as connection:
        connection.execute(
            "UPDATE send_requests SET updated_at = ?, lease_expires_at = ? "
            "WHERE dedupe_key = 'dk-Z'",
            (stale, stale),
        )
        connection.commit()
    # 清扫 + 认领：僵尸被终态化不再重投；同批健康行照常认领（新造 processing
    # 行刚被心跳顶到墙钟，绝不被误扫——b3ba9ba 两案形状保持）。
    round_two = queue.claim_due(now=_utc_now() + timedelta(minutes=2), limit=2)
    ids = [entry.row_dedupe_key for entry in round_two]
    assert "dk-F" in ids
    assert "dk-Z" not in ids
    snap = _row_snapshot(db)
    assert snap["dk-Z"]["state"] == ReceiptState.FAILED_FINAL.value


# ---------------------------------------------------------------------------
# 结构锁：一切 UPDATE 谓词收口行身份（注毒自证同路）


def _literal_sql_text(node: ast.AST) -> str | None:
    """把 Constant / JoinedStr（f-string）还原为可扫描的字面文本。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                parts.append("{expr}")
        return "".join(parts)
    return None


def _update_predicate_violations(source: str) -> list[str]:
    """扫 queue.py 源码里所有对 send_requests / send_request_parts 的 UPDATE。

    判据（写路径谓词必须按行身份，杜绝共键扇出）：
    - UPDATE send_requests … WHERE 必须含 dedupe_key 或 rowid；
    - UPDATE send_request_parts … WHERE 必须含 dedupe_key 或 part_key。
    唯一豁免＝按列名精确登记的回填扫描（列回填不触任何行状态；新增豁免
    必须连同理由来这里登记，默认零豁免）。
    """
    allowlist = {
        # 存量列回填：WHERE 以「待回填列 IS NULL」筛行，不写状态/正文列。
        "UPDATE send_requests": {"_backfill_session_id", "_backfill_expires_at"},
        "UPDATE send_request_parts": set(),
    }
    tree = ast.parse(source)
    violations: list[str] = []

    def _check(sql: str, func_name: str) -> None:
        for table, needles in (
            ("UPDATE send_requests", ("dedupe_key", "rowid")),
            ("UPDATE send_request_parts", ("dedupe_key", "part_key")),
        ):
            for match in re.finditer(re.escape(table), sql):
                tail = sql[match.start():]
                # 只看到本条语句体：截到下一条 UPDATE 之前。
                nxt = tail.find("UPDATE ", len(table))
                if nxt > 0:
                    tail = tail[:nxt]
                where = re.search(r"\bWHERE\b", tail, re.IGNORECASE)
                label = f"{table} in {func_name}"
                if func_name in allowlist[table]:
                    continue
                if where is None:
                    violations.append(f"{label}: 无 WHERE（全表写）")
                    continue
                predicate = tail[where.end():]
                if not any(needle in predicate for needle in needles):
                    violations.append(f"{label}: WHERE 缺行主键谓词（{'/'.join(needles)}）")

    seen_ids: set[int] = set()
    # f-string 的字面片段单独看会「只见 UPDATE 不见 WHERE」——判据只看整串
    # （JoinedStr 整体），其子节点全部跳过，免生幻影违规。
    joined_children: set[int] = set()
    for joined in (n for n in ast.walk(tree) if isinstance(n, ast.JoinedStr)):
        for sub in ast.walk(joined):
            if sub is not joined:
                joined_children.add(id(sub))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for sub in ast.walk(node):
                if id(sub) in joined_children:
                    continue
                sql = _literal_sql_text(sub)
                if sql and ("UPDATE send_requests" in sql or "UPDATE send_request_parts" in sql):
                    seen_ids.add(id(sub))
                    _check(sql, node.name)
    for sub in ast.walk(tree):
        if id(sub) in seen_ids or id(sub) in joined_children:
            continue
        sql = _literal_sql_text(sub)
        if sql and ("UPDATE send_requests" in sql or "UPDATE send_request_parts" in sql):
            _check(sql, "<module>")
    return violations


def test_structural_lock_queue_updates_address_row_identity() -> None:
    source = QUEUE_SOURCE_PATH.read_text(encoding="utf-8")
    assert _update_predicate_violations(source) == []


def test_structural_lock_poison_is_caught() -> None:
    """注毒自证：把任一 UPDATE 谓词改回共键旧形，同一判据当场咬出。"""
    source = QUEUE_SOURCE_PATH.read_text(encoding="utf-8")

    poisoned = source.replace(
        """            WHERE dedupe_key = ?
            \"\"\",
            (
                state.value,""",
        """            WHERE request_id = ?
            \"\"\",
            (
                state.value,""",
        1,
    )
    assert poisoned != source, "注毒点未命中（_update_state_in 谓词形状变了）"
    violations = _update_predicate_violations(poisoned)
    assert violations and any("_update_state_in" in item for item in violations)

    # 第二把毒：part 明细写改回 request_id+part_index（丢身份）。
    poisoned_parts = source.replace(
        """                    UPDATE send_request_parts
                    SET {", ".join(assignments)}
                    WHERE request_id = ? AND part_index = ?
                      AND dedupe_key IS ?""",
        """                    UPDATE send_request_parts
                    SET {", ".join(assignments)}
                    WHERE request_id = ? AND part_index = ?""",
        1,
    )
    assert poisoned_parts != source, "注毒点未命中（_update_part_row 谓词形状变了）"
    violations_parts = _update_predicate_violations(poisoned_parts)
    assert violations_parts and any("_update_part_row" in item for item in violations_parts)

    # 同判据打在无删改的还原态上必须不咬（还原＝重读真身文件）。
    restored = QUEUE_SOURCE_PATH.read_text(encoding="utf-8")
    assert _update_predicate_violations(restored) == []
