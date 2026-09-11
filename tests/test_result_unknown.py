from __future__ import annotations

from pathlib import Path

from plugins.bot_unified_runtime.runtime.result_unknown import ResultUnknownLedger


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _ledger(tmp_path: Path, clock: _FakeClock) -> ResultUnknownLedger:
    return ResultUnknownLedger(
        tmp_path / "result_unknown.sqlite3",
        expire_seconds=3600.0,
        clock=clock,
    )


def test_record_deduplicates_by_request_id(tmp_path) -> None:
    clock = _FakeClock()
    ledger = _ledger(tmp_path, clock)

    assert ledger.record(request_id="r1", adapter="onebot", bot_id="10000") is True
    assert ledger.record(request_id="r1", adapter="onebot", bot_id="10000") is False
    assert ledger.pending_count() == 1


def test_reconcile_marks_expired_and_reports_pending(tmp_path) -> None:
    clock = _FakeClock()
    ledger = _ledger(tmp_path, clock)
    ledger.record(request_id="old", adapter="onebot", bot_id="10000")
    clock.advance(7200.0)
    ledger.record(request_id="fresh", adapter="onebot", bot_id="20000")

    summary = ledger.reconcile(bot_id="20000")

    assert summary.expired == 1
    assert summary.pending == 1
    assert summary.by_bot == {"20000": 1}
    assert ledger.pending_count() == 1


def test_record_ignores_blank_identifiers(tmp_path) -> None:
    ledger = _ledger(tmp_path, _FakeClock())
    assert ledger.record(request_id="", adapter="onebot", bot_id="b") is False
    assert ledger.record(request_id="r", adapter="", bot_id="b") is False
    assert ledger.pending_count() == 0


def test_reconcile_purges_rows_expired_beyond_ttl(tmp_path) -> None:
    """过期行保留一个排查窗口（purge_after_seconds）后在下轮对账物理删除。"""
    clock = _FakeClock()
    ledger = _ledger(tmp_path, clock)
    ledger.record(request_id="stale", adapter="onebot", bot_id="10000")
    clock.advance(7200.0)
    summary_one = ledger.reconcile()
    # 首轮：stale 被标记 expired，但 resolved_at=now，仍在排查窗口内不删。
    assert summary_one.expired == 1
    assert summary_one.purged == 0

    clock.advance(3600.0)
    summary_two = ledger.reconcile()
    # stale 的 resolved_at=8200，此刻 now=11800，purge_cutoff=8200 → 窗口已过，删除。
    assert summary_two.purged == 1
    assert summary_two.pending == 0

    connection = __import__("sqlite3").connect(tmp_path / "result_unknown.sqlite3")
    try:
        remaining = connection.execute("SELECT COUNT(*) FROM result_unknown").fetchone()[0]
    finally:
        connection.close()
    assert remaining == 0


def test_reconcile_never_purges_pending_rows(tmp_path) -> None:
    """pending 行无论多老都只被标记过期；本轮刚过期的行保留在窗口内。"""
    clock = _FakeClock()
    ledger = _ledger(tmp_path, clock)
    ledger.record(request_id="old-pending", adapter="onebot", bot_id="10000")
    clock.advance(100000.0)

    summary = ledger.reconcile()

    assert summary.expired == 1
    assert summary.purged == 0  # 本轮标记 expired 的行 resolved_at=now，不删
    assert ledger.pending_count() == 0
    connection = __import__("sqlite3").connect(tmp_path / "result_unknown.sqlite3")
    try:
        rows = connection.execute(
            "SELECT request_id, status FROM result_unknown"
        ).fetchall()
    finally:
        connection.close()
    assert rows == [("old-pending", "expired")]


def test_purge_expired_manual_call_respects_window(tmp_path) -> None:
    """手动 purge_expired 只删过期超过窗口的行，保留窗口内与 pending 行。"""
    clock = _FakeClock()
    ledger = _ledger(tmp_path, clock)
    ledger.record(request_id="a", adapter="onebot", bot_id="b")
    clock.advance(7200.0)
    ledger.record(request_id="fresh", adapter="onebot", bot_id="b")
    clock.advance(7200.0)
    ledger.reconcile()  # a、fresh 均标记 expired，resolved_at=14400+1000

    # resolved_at 刚发生，窗口 3600 内 → 不删。
    assert ledger.purge_expired() == 0

    clock.advance(7200.0)
    assert ledger.purge_expired() == 2
    assert ledger.pending_count() == 0
    # 重复执行幂等。
    assert ledger.purge_expired() == 0


def test_purge_after_seconds_override(tmp_path) -> None:
    """purge_after_seconds 可独立于 expire_seconds 配置。"""
    clock = _FakeClock()
    ledger = ResultUnknownLedger(
        tmp_path / "result_unknown.sqlite3",
        expire_seconds=3600.0,
        purge_after_seconds=60.0,
        clock=clock,
    )
    ledger.record(request_id="x", adapter="onebot", bot_id="b")
    clock.advance(7200.0)
    summary = ledger.reconcile()
    assert summary.expired == 1
    # resolved_at=8200，purge_cutoff=8200-60=8140 → 窗口刚过不删。
    assert summary.purged == 0
    clock.advance(120.0)
    assert ledger.purge_expired() == 1
