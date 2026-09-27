"""SENDQ F-3/F-4（SEAT-ATK-SENDQ，主代理串行批 2026-09-27）。

F-3：part 转入 pending/unknown 时必须清 `provider_message_id`——worker 的
UNKNOWN 对账短路（`record.provider_message_id` 非空即判送达）不得信任本地残号，
保持「UNKNOWN 只由确认器/人工销案」红线。
F-4：`claim_due` 收尾的 `_entries_from_rows` 必须在同一事务内读回——事务外
SELECT 与他线程 BEGIN 交错可读到未提交态（幻影进度）。
"""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

from tests.test_part_idempotent_resume import _build_queue, _chunk_request

_QUEUE_PY = (
    Path(__file__).resolve().parents[1]
    / "plugins/bot_unified_runtime/domains/transport/sender/queue.py"
)


def _part_row(tmp_path: Path, name: str, part_index: int) -> str | None:
    with sqlite3.connect(tmp_path / name) as connection:
        row = connection.execute(
            "SELECT provider_message_id FROM send_request_parts WHERE part_index = ?",
            (part_index,),
        ).fetchone()
    assert row is not None
    return row[0]


def test_unknown_transition_clears_provider_message_id(tmp_path) -> None:
    name = "f3-unknown.sqlite3"
    queue = _build_queue(tmp_path, name)
    base = _utc_now_fixture()
    queue.submit(_chunk_request("req-f3a", ["一", "二"]), now=base)
    queue.ensure_parts_planned("req-f3a", ["d1", "d2"], now=base)
    assert queue.mark_part_sent("req-f3a", 1, provider_message_id="mid-keep", now=base)
    # 历史行/兜底路径把已带号的 part 转回 UNKNOWN ⇒ 号必须清（不短路判送达）。
    assert queue.mark_part_unknown("req-f3a", 1, now=base)
    assert _part_row(tmp_path, name, 1) is None


def test_pending_transition_clears_provider_message_id(tmp_path) -> None:
    name = "f3-pending.sqlite3"
    queue = _build_queue(tmp_path, name)
    base = _utc_now_fixture()
    queue.submit(_chunk_request("req-f3b", ["一", "二"]), now=base)
    queue.ensure_parts_planned("req-f3b", ["d1", "d2"], now=base)
    assert queue.mark_part_sent("req-f3b", 0, provider_message_id="mid-old", now=base)
    assert queue.mark_part_pending("req-f3b", 0, now=base)
    assert _part_row(tmp_path, name, 0) is None


def test_claim_due_rebuild_happens_inside_transaction() -> None:
    tree = ast.parse(_QUEUE_PY.read_text(encoding="utf-8"))
    fn = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "claim_due"
    )
    inside_with = False
    outside = False
    for with_node in [n for n in ast.walk(fn) if isinstance(n, ast.With)]:
        for ret in ast.walk(with_node):
            if (
                isinstance(ret, ast.Return)
                and isinstance(ret.value, ast.Call)
                and isinstance(ret.value.func, ast.Attribute)
                and ret.value.func.attr == "_entries_from_rows"
            ):
                inside_with = True
    for ret in ast.walk(fn):
        if (
            isinstance(ret, ast.Return)
            and isinstance(ret.value, ast.Call)
            and isinstance(ret.value.func, ast.Attribute)
            and ret.value.func.attr == "_entries_from_rows"
            and not _enclosed_in_with(fn, ret.lineno)
        ):
            outside = True
    assert inside_with and not outside, "F-4：_entries_from_rows 读回被挪出事务"


def _enclosed_in_with(fn: ast.AST, lineno: int) -> bool:
    return any(
        isinstance(node, ast.With) and node.lineno <= lineno <= node.end_lineno
        for node in ast.walk(fn)
    )


def _utc_now_fixture():
    from datetime import datetime, timezone

    return datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)
