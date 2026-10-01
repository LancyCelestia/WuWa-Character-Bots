"""SEAT-Q1-QUEUE-SCAN-20261002（P5.9）：出站队列 submit 剪枝读侧的锁。

事实底（工单 §1）：`SQLiteSendRequestQueue.submit()` 每次成功插入都走
`_prune()`，而 `_prune` 的留存窗口子查询
`ORDER BY created_at DESC, rowid DESC LIMIT ?` 在没有 created_at 索引时
＝ `SCAN send_requests` + `USE TEMP B-TREE FOR ORDER BY`——生产副本实测
1000 行（恰好 pinned 在 max_items）下 4.85 ms/次 submit，且那一轮一行都不必删。
修法只有两把，都不碰语义：建 `idx_send_requests_created_at`，把反连接键从
`dedupe_key`（TEXT 主键原文）换成 `rowid`（同集合、免回表）。

本文件的判据形状（AGENTS 规则 5 / 席位共同硬约束「双向自测」）：
- 正向不误伤：索引在场 ⇒ 剪枝语句的 plan 里有
  `COVERING INDEX idx_send_requests_created_at`、且没有 `TEMP B-TREE`。
- 注毒：把索引拔掉 ⇒ 同一条语句必须退回 `TEMP B-TREE`（证明这把尺真在量东西）；
  把形态换回 `dedupe_key NOT IN` ⇒ 必须丢掉 `COVERING`（证明形态那一半也真在付钱）。
- 语义锁：留存窗口逐档对拍纯 Python 参照实现；非终态行（含 PARTIAL）永不淘汰；
  part 明细账一字不动；NULL 主键行不再冻结剪枝。

离线运行（tmp_path，零网络、零生产库）：

    PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 python -m pytest \
      -p no:cacheprovider --basetemp=<仓库外> -q tests/test_queue_prune_index_lock.py
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

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
    PROCESSING_STATE,
    SQLiteSendRequestQueue,
    _part_key,
)

INDEX_NAME = "idx_send_requests_created_at"
TERMINAL_STATES = (
    ReceiptState.SENT.value,
    ReceiptState.FAILED_FINAL.value,
    ReceiptState.SKIPPED.value,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _request(index: int) -> SendRequest:
    rendered = RenderedOutput(
        request_id=f"q1-lock-{index}",
        content_type="text",
        content_ref={},
        text_fallback="lock",
        privacy_level=PrivacyLevel.PERSONAL,
    )
    return SendRequest(
        request_id=f"q1-lock-{index}",
        session_id="private:q1-lock",
        target_scope=SessionType.PRIVATE,
        target_id="q1-lock",
        capability_id="bot.chat",
        content=rendered,
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key=f"q1-lock-dedupe-{index}",
        cooldown_key="q1-lock-private",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="default",
    )


def _queue(tmp_path: Any, max_items: int = 4) -> SQLiteSendRequestQueue:
    queue = SQLiteSendRequestQueue(
        tmp_path / "q1_lock.sqlite3", InMemoryAuditLogger(), max_items=max_items
    )
    # 播种类用例绕开 submit() 直连写表，所以得自己把 schema（含新索引）拉起来。
    queue._ensure_schema_once()
    return queue


def _seed_row(
    connection: sqlite3.Connection,
    *,
    dedupe_key: str | None,
    state: str,
    created_at: str,
    request_id: str = "seeded",
    next_retry_at: str | None = None,
    updated_at: str | None = None,
) -> None:
    """按真表形状插一行（列集合与 submit 写的一致，NOT NULL 全给足）。

    ``next_retry_at``/``updated_at`` 要能单独给：`_prune` 顶部另有一条休眠 PARTIAL
    清扫腿（state='partial' 且 next_retry_at IS NULL 且 updated_at 超 TTL ⇒ 转
    FAILED_FINAL，转完就可被留存腿剪掉）。测「非终态永不被淘汰」时必须把该行做成
    **非休眠**（给一枚未来 next_retry_at），否则量到的是清扫腿、不是留存腿。
    """
    connection.execute(
        """
        INSERT INTO send_requests (
            dedupe_key, request_id, state, request_json, retry_count,
            next_retry_at, last_public_message, created_at, updated_at
        ) VALUES (?, ?, ?, '{}', 0, ?, 'seeded', ?, ?)
        """,
        (
            dedupe_key,
            request_id,
            state,
            next_retry_at,
            created_at,
            updated_at or created_at,
        ),
    )


def _capture_prune_statement(queue: SQLiteSendRequestQueue) -> str:
    """让真 submit 跑一遍，从执行轨迹里捞出它实际发出的剪枝 DELETE。

    语句文本从代码路径本身捞，不在测试里再抄一份字面量——抄了就成了第二把尺，
    改了正身而忘改副本时测试照样绿。
    """
    seen: list[str] = []
    connection = queue._shared_connection()
    connection.set_trace_callback(lambda statement: seen.append(statement))
    try:
        for i in range(40):
            queue.submit(_request(i))
    finally:
        connection.set_trace_callback(None)
    prune_delete = [
        statement
        for statement in seen
        if "DELETE FROM send_requests" in statement and "NOT IN" in statement
    ]
    assert prune_delete, "submit 没有发出剪枝 DELETE——现状核实塌了"
    return prune_delete[0]


def _plan(connection: sqlite3.Connection, statement: str) -> list[str]:
    placeholders = statement.count("?")
    rows = connection.execute(
        "EXPLAIN QUERY PLAN " + statement, tuple([1] * placeholders)
    ).fetchall()
    return [str(row[3]) for row in rows]


# ---------------------------------------------------------------- 读侧形态锁


def test_submit_runs_the_prune_delete_on_every_successful_insert(tmp_path) -> None:
    """现状核实腿：剪枝确实挂在 submit 热路径上（不是惰性清扫）。"""
    queue = _queue(tmp_path, max_items=4)
    seen: list[str] = []
    connection = queue._shared_connection()
    connection.set_trace_callback(lambda statement: seen.append(statement))
    try:
        queue.submit(_request(0))
        queue.submit(_request(1))
    finally:
        connection.set_trace_callback(None)
    deletes = [s for s in seen if "DELETE FROM send_requests" in s]
    assert len(deletes) >= 2, "每次成功入队都应触发一次剪枝；少一次＝热路径判断变了"


def test_prune_read_walks_the_created_at_index_without_sorting(tmp_path) -> None:
    """正向不误伤腿：改后 plan 用覆盖索引、无临时 B 树。"""
    queue = _queue(tmp_path, max_items=4)
    statement = _capture_prune_statement(queue)
    plan = _plan(queue._shared_connection(), statement)
    joined = " | ".join(plan)
    assert INDEX_NAME in joined, f"剪枝没走 created_at 索引：{joined}"
    assert "TEMP B-TREE" not in joined, f"仍在整表排序：{joined}"
    assert "COVERING INDEX" in joined, f"回表取键，形态没换成 rowid 反连接：{joined}"


def test_poison_plan_regresses_when_the_index_is_dropped(tmp_path) -> None:
    """注毒腿 A：拔掉索引 ⇒ 同一条语句必须退回 TEMP B-TREE 全表排序。

    断的是「这把尺能不能测出改动消失」，不是「现在对不对」。
    """
    queue = _queue(tmp_path, max_items=4)
    statement = _capture_prune_statement(queue)
    connection = queue._shared_connection()
    connection.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
    try:
        plan = " | ".join(_plan(connection, statement))
        assert "TEMP B-TREE" in plan, f"拔掉索引仍不排序＝这把尺量不到东西：{plan}"
        assert INDEX_NAME not in plan, f"索引已删却仍被点名：{plan}"
    finally:
        connection.execute(
            f"CREATE INDEX IF NOT EXISTS {INDEX_NAME} ON send_requests (created_at)"
        )
        plan_after = " | ".join(_plan(connection, statement))
        assert "TEMP B-TREE" not in plan_after, "补回索引后判据必须转绿（反向腿）"


def test_poison_shape_reverts_to_table_key_probe(tmp_path) -> None:
    """注毒腿 B：把反连接键换回 `dedupe_key` ⇒ 必须丢掉 COVERING。

    证明「形态」那一半真在付钱（索引在场也仍然要回表取 TEXT 主键原文）。
    """
    queue = _queue(tmp_path, max_items=4)
    statement = _capture_prune_statement(queue)
    legacy = statement.replace("rowid NOT IN", "dedupe_key NOT IN").replace(
        "SELECT rowid", "SELECT dedupe_key"
    )
    assert legacy != statement, "剪枝语句形状不是预期，替换没生效——本注毒腿空跑"
    plan = " | ".join(_plan(queue._shared_connection(), legacy))
    assert "COVERING INDEX" not in plan, f"旧形态竟也免回表：{plan}"


def test_index_is_single_column_ascending(tmp_path) -> None:
    """索引必须写成裸单列 ASC —— 写成 (created_at DESC) 会留下尾巴。

    索引叶子键恒为 (created_at, rowid ASC)，倒着走恰好等于
    `created_at DESC, rowid DESC`；写成 DESC 时叶子变成 (created_at DESC,
    rowid ASC)，正走倒走都对不上那枚 rowid DESC，优化器退回
    `USE TEMP B-TREE FOR LAST TERM OF ORDER BY`（两形都在生产副本上实测过）。
    """
    queue = _queue(tmp_path)
    queue._ensure_schema_once()
    row = queue._shared_connection().execute(
        "SELECT sql FROM sqlite_master WHERE name = ?", (INDEX_NAME,)
    ).fetchone()
    assert row is not None, "索引没建出来"
    ddl = str(row[0]).lower()
    assert "desc" not in ddl, f"created_at 索引不许带 DESC（会留临时排序）：{ddl}"
    assert "created_at" in ddl


# ---------------------------------------------------------------- 语义锁


def test_prune_keeps_exactly_the_newest_window_with_created_at_ties(tmp_path) -> None:
    """留存窗口逐档对拍纯 Python 参照实现（含 created_at 同值 ⇒ 靠 rowid DESC 定序）。"""
    for max_items in (1, 2, 3, 5, 12):
        queue = _queue(tmp_path, max_items=max_items)
        connection = queue._shared_connection()
        connection.execute("DELETE FROM send_requests")
        # 三组同 created_at、每组 5 行：组内先后只能由 rowid DESC 判出。
        for i in range(15):
            _seed_row(
                connection,
                dedupe_key=f"tie-{max_items}-{i}",
                state=ReceiptState.SENT.value,
                created_at=f"2026-01-0{1 + i // 5}T00:00:00+00:00",
            )
        connection.commit()
        rows = [
            (int(r[0]), str(r[1]), str(r[2]))
            for r in connection.execute(
                "SELECT rowid, dedupe_key, state FROM send_requests"
            ).fetchall()
        ]
        created_at_of = {
            int(r[0]): str(r[1])
            for r in connection.execute("SELECT rowid, created_at FROM send_requests").fetchall()
        }
        # 参照实现：按 (created_at DESC, rowid DESC) 全序取前 max_items 作 keeper，
        # 其余行里只有终态被剪。
        full_order = sorted(
            rows, key=lambda r: (created_at_of[r[0]], r[0]), reverse=True
        )
        keepers = {r[0] for r in full_order[:max_items]}
        expected_survivors = {
            r[0] for r in rows if r[0] in keepers or r[2] not in TERMINAL_STATES
        }
        queue._prune(connection)
        connection.commit()
        survivors = {
            int(r[0])
            for r in connection.execute("SELECT rowid FROM send_requests").fetchall()
        }
        assert survivors == expected_survivors, (
            f"max_items={max_items} 留存集与参照实现不等："
            f"多={sorted(survivors - expected_survivors)} "
            f"少={sorted(expected_survivors - survivors)}"
        )


def test_prune_never_evicts_non_terminal_rows_including_partial(tmp_path) -> None:
    """A4 契约 + PARTIAL 断点续发：非终态（QUEUED/PROCESSING/PARTIAL/
    FAILED_RETRYABLE）行数远超 cap 也一行不许剪。

    播种一律带**未来的** next_retry_at：`_prune` 顶部那条休眠 PARTIAL 清扫腿只收
    `next_retry_at IS NULL 且 updated_at 超 TTL` 的行，本测试量的是留存腿，必须
    先把清扫腿隔开（否则 partial 被转成 FAILED_FINAL 再剪掉，读数会变成「留存腿
    杀了非终态行」的假信号）。清扫腿自身的行为由
    tests/test_queue_dormant_partial_final.py 锁着，本波复跑过。
    """
    protected = [
        ReceiptState.QUEUED.value,
        PROCESSING_STATE,
        PARTIAL_ROW_STATE,
        ReceiptState.FAILED_RETRYABLE.value,
    ]
    queue = _queue(tmp_path, max_items=1)
    connection = queue._shared_connection()
    connection.execute("DELETE FROM send_requests")
    future = (_utc_now() + timedelta(days=1)).isoformat()
    for i in range(10):
        _seed_row(
            connection,
            dedupe_key=f"filler-terminal-{i}",
            state=ReceiptState.SENT.value,
            created_at=f"2026-01-01T00:00:{i:02d}+00:00",
        )
    for state in protected:
        # 保护行刻意一枚插在最旧时刻、一枚插在最新时刻：最旧那枚若被剪＝窗口在杀非终态行。
        _seed_row(
            connection,
            dedupe_key=f"protected-old-{state}",
            state=state,
            created_at="2025-01-01T00:00:00+00:00",
            next_retry_at=future,
            updated_at=_utc_now().isoformat(),
        )
        _seed_row(
            connection,
            dedupe_key=f"protected-new-{state}",
            state=state,
            created_at="2027-01-01T00:00:00+00:00",
            next_retry_at=future,
            updated_at=_utc_now().isoformat(),
        )
    connection.commit()
    queue._prune(connection)
    connection.commit()
    for state in protected:
        kept = connection.execute(
            "SELECT COUNT(*) FROM send_requests WHERE state = ?", (state,)
        ).fetchone()[0]
        assert int(kept) == 2, f"{state} 是非终态行，被剪了（剩 {kept}）"
    # 终态那批必须真被剪到窗口内（否则「留存腿还在干活」这条没锁住）。
    terminal_left = int(
        connection.execute(
            "SELECT COUNT(*) FROM send_requests WHERE state IN (?, ?, ?)",
            TERMINAL_STATES,
        ).fetchone()[0]
    )
    assert terminal_left <= 1, f"终态行没剪进窗口，剩 {terminal_left}"


def test_prune_leaves_the_part_ledger_untouched(tmp_path) -> None:
    """part 级幂等明细账：剪枝只动请求行，part 行必须原样留着供取证/续发。"""
    queue = _queue(tmp_path, max_items=1)
    connection = queue._shared_connection()
    connection.execute("DELETE FROM send_requests")
    connection.execute("DELETE FROM send_request_parts")
    connection.commit()
    for i in range(6):
        _seed_row(
            connection,
            dedupe_key=f"withparts-{i}",
            state=ReceiptState.FAILED_FINAL.value,
            created_at=f"2026-01-01T00:00:{i:02d}+00:00",
        )
    snapshot: list[tuple[Any, ...]] = []
    for i in range(6):
        for part_index in range(3):
            key = _part_key(f"req-{i}", part_index, f"withparts-{i}")
            connection.execute(
                """
                INSERT INTO send_request_parts (
                    part_key, request_id, part_index, parts_total, state,
                    attempts, last_error_kind, provider_message_id,
                    payload_digest, updated_at, dedupe_key
                ) VALUES (?, ?, ?, 3, 'sent', 1, NULL, ?, ?, '2026-01-01T00:00:00+00:00', ?)
                """,
                (key, f"req-{i}", part_index, f"mid-{part_index}", f"digest-{key}",
                 f"withparts-{i}"),
            )
    connection.commit()
    snapshot = [
        tuple(r)
        for r in connection.execute(
            "SELECT part_key, request_id, part_index, state, attempts,"
            " provider_message_id, payload_digest, dedupe_key"
            " FROM send_request_parts ORDER BY part_key"
        ).fetchall()
    ]
    assert snapshot, "播种失败"
    queue._prune(connection)
    connection.commit()
    after = [
        tuple(r)
        for r in connection.execute(
            "SELECT part_key, request_id, part_index, state, attempts,"
            " provider_message_id, payload_digest, dedupe_key"
            " FROM send_request_parts ORDER BY part_key"
        ).fetchall()
    ]
    assert after == snapshot, "剪枝动了 part 明细账"
    remaining = connection.execute(
        "SELECT COUNT(*) FROM send_requests"
    ).fetchone()[0]
    assert int(remaining) <= 1, f"窗口没生效：{remaining} 行剩着"


def test_prune_still_prunes_when_a_null_dedupe_key_row_is_the_newest(tmp_path) -> None:
    """NULL 主键行不得冻结剪枝。

    `TEXT PRIMARY KEY` 在 SQLite 里不隐含 NOT NULL（生产副本实测
    `SELECT COUNT(*) … WHERE dedupe_key IS NULL` = 0，所以现网无可观测差异），
    但旧形态 `dedupe_key NOT IN (…)` 一旦 keeper 集里落进 NULL 就对全体判
    NULL ⇒ 剪枝静默变成「一行都不删」且不报错。改后按 rowid 反连接免疫。
    这条锁的是「别再退回那个形状」。
    """
    queue = _queue(tmp_path, max_items=2)
    connection = queue._shared_connection()
    connection.execute("DELETE FROM send_requests")
    for i in range(8):
        _seed_row(
            connection,
            dedupe_key=f"nullpk-fillers-{i}",
            state=ReceiptState.SENT.value,
            created_at=f"2026-01-01T00:00:{i:02d}+00:00",
        )
    _seed_row(
        connection,
        dedupe_key=None,
        state=ReceiptState.SENT.value,
        created_at="2027-01-01T00:00:00+00:00",
    )
    connection.commit()
    before = int(
        connection.execute("SELECT COUNT(*) FROM send_requests").fetchone()[0]
    )
    queue._prune(connection)
    connection.commit()
    after = int(connection.execute("SELECT COUNT(*) FROM send_requests").fetchone()[0])
    assert after < before, "NULL 主键行使剪枝静默停摆（旧形态的坑）"
    assert after == 2, f"窗口应当剩 2 行，实剩 {after}"
    null_left = int(
        connection.execute(
            "SELECT COUNT(*) FROM send_requests WHERE dedupe_key IS NULL"
        ).fetchone()[0]
    )
    assert null_left == 1, "NULL 行是最新行，本该留在窗口内"


def test_repeated_submits_cap_the_terminal_population(tmp_path) -> None:
    """热路径总量锁。

    注意契约方向：A4 说「非终态永不淘汰」，所以全 QUEUED 的表**允许**越过
    max_items（本波实测：cap=6 时 40 条全排队会涨到 40 行，这是对的，不是回归）。
    真正必须被剪进窗口的是**终态**那批 —— 已投递（SENT）的行。本测试因此分两段：
    排队段验「一行不丢」，投递段验「终态population 不越 cap」。
    """
    max_items = 6
    queue = _queue(tmp_path, max_items=max_items)
    connection = queue._shared_connection()
    connection.execute("DELETE FROM send_requests")
    connection.commit()
    for i in range(40):
        queue.submit(_request(i))
    queued = int(
        connection.execute(
            "SELECT COUNT(*) FROM send_requests WHERE state = ?",
            (ReceiptState.QUEUED.value,),
        ).fetchone()[0]
    )
    assert queued == 40, f"在途行被剪了（剩 {queued}/40）——违反 A4"

    connection.execute(
        "UPDATE send_requests SET state = ?", (ReceiptState.SENT.value,)
    )
    connection.commit()
    for i in range(40, 60):
        queue.submit(_request(i))
        terminal = int(
            connection.execute(
                "SELECT COUNT(*) FROM send_requests WHERE state IN (?, ?, ?)",
                TERMINAL_STATES,
            ).fetchone()[0]
        )
        assert terminal <= max_items, (
            f"第 {i} 次 submit 后终态行 {terminal} 枚 > cap {max_items}＝留存腿失效"
        )
    newest = [
        str(r[0])
        for r in connection.execute(
            "SELECT dedupe_key FROM send_requests "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (max_items,),
        ).fetchall()
    ]
    assert newest, "窗口空了"
    survivors = {
        str(r[0])
        for r in connection.execute("SELECT dedupe_key FROM send_requests").fetchall()
    }
    assert set(newest) <= survivors, "最新窗口内的行必须都在"


def test_prune_is_safe_to_run_when_table_is_empty(tmp_path) -> None:
    """空表/窗口大于行数：一条不许删（防把「无事可做」写成「全删」）。"""
    queue = _queue(tmp_path, max_items=100)
    connection = queue._shared_connection()
    connection.execute("DELETE FROM send_request_parts")
    rows = [
        (str(r[0]), str(r[1]))
        for r in connection.execute(
            "SELECT dedupe_key, state FROM send_requests"
        ).fetchall()
    ]
    queue._prune(connection)
    connection.commit()
    after = [
        (str(r[0]), str(r[1]))
        for r in connection.execute(
            "SELECT dedupe_key, state FROM send_requests"
        ).fetchall()
    ]
    assert len(after) == len(rows)
    assert {s for _, s in after} <= set(
        list(TERMINAL_STATES)
        + [ReceiptState.QUEUED.value, PROCESSING_STATE, PARTIAL_ROW_STATE,
           ReceiptState.FAILED_RETRYABLE.value]
    )
